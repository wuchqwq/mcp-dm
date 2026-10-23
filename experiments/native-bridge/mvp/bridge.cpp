#include "bridge.hpp"
#include <sddl.h>
#include <exception>
#include <vector>
#include <utility>

namespace nb {
namespace {
constexpr DWORD kIoTimeoutMs = 1500;
struct Handle {
    HANDLE h = INVALID_HANDLE_VALUE;
    explicit Handle(HANDLE value = INVALID_HANDLE_VALUE) : h(value) {}
    ~Handle() { if (h && h != INVALID_HANDLE_VALUE) CloseHandle(h); }
    Handle(const Handle&) = delete; Handle& operator=(const Handle&) = delete;
};
struct Security {
    PSECURITY_DESCRIPTOR descriptor = nullptr;
    SECURITY_ATTRIBUTES attributes{};
    Security() {
        Handle token; if (!OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &token.h)) throw std::runtime_error("OpenProcessToken failed");
        DWORD bytes = 0; GetTokenInformation(token.h, TokenUser, nullptr, 0, &bytes);
        if (!bytes || bytes > 64 * 1024) throw std::runtime_error("GetTokenInformation size failed");
        std::vector<unsigned char> buffer(bytes);
        if (!GetTokenInformation(token.h, TokenUser, buffer.data(), bytes, &bytes)) throw std::runtime_error("GetTokenInformation failed");
        LPWSTR sid = nullptr;
        if (!ConvertSidToStringSidW(reinterpret_cast<TOKEN_USER*>(buffer.data())->User.Sid, &sid)) throw std::runtime_error("ConvertSidToStringSid failed");
        std::wstring sddl = L"D:P(A;;GA;;;" + std::wstring(sid) + L")"; LocalFree(sid);
        if (!ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl.c_str(), SDDL_REVISION_1, &descriptor, nullptr)) throw std::runtime_error("pipe DACL construction failed");
        attributes.nLength = sizeof(attributes); attributes.lpSecurityDescriptor = descriptor; attributes.bInheritHandle = FALSE;
    }
    ~Security() { if (descriptor) LocalFree(descriptor); }
};
void diagnostic(const std::string& text) { OutputDebugStringA(("native-bridge: " + text + "\n").c_str()); }
std::string request_id_hint(const std::string& line) {
    // Do not reflect arbitrary malformed frame bytes as an identifier.
    const auto first = line.find(' '); if (first == std::string::npos) return {};
    const auto second = line.find(' ', first + 1); if (second == std::string::npos) return {};
    auto third = line.find(' ', second + 1); auto id = line.substr(second + 1, third - second - 1);
    if (id.empty() || id.size() > 64) return {};
    for (char c : id) if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '_' || c == '-')) return {};
    return id;
}
}
Bridge::Bridge(std::string failure, bool audit) : startup_test_failure_(std::move(failure)), test_audit_(audit) {}
void Bridge::audit_handle(HANDLE handle) {
    if (!test_audit_ || !handle || handle == INVALID_HANDLE_VALUE) return;
    std::lock_guard<std::mutex> lock(startup_mutex_); audited_handles_.push_back(handle);
}
bool Bridge::audited_resources_released() {
    if (!test_audit_) throw std::runtime_error("resource audit is available only to the offline harness");
    std::lock_guard<std::mutex> lock(startup_mutex_);
    for (HANDLE handle : audited_handles_) {
        DWORD flags = 0;
        SetLastError(ERROR_SUCCESS);
        if (GetHandleInformation(handle, &flags) || GetLastError() != ERROR_INVALID_HANDLE) return false;
    }
    if (!window_class_.empty()) {
        WNDCLASSW cls{};
        if (GetClassInfoW(instance_, window_class_.c_str(), &cls) ||
            FindWindowExW(HWND_MESSAGE, nullptr, window_class_.c_str(), nullptr)) return false;
    }
    return !stop_ && !stopped_ && !worker_ && !worker_ready_ && !window_ && !adapter_initialized_;
}
void Bridge::inject_start_failure(const std::string& stage) const {
    if (startup_test_failure_ == stage) throw std::runtime_error("injected offline startup failure at " + stage);
}
Bridge::~Bridge() {
    // Exported lifecycle and the fake host explicitly call shutdown on the
    // startup thread. Destruction on another thread is a programmer error.
    if (stop_ || stopped_ || window_ || worker_ || worker_ready_) {
        if (GetCurrentThreadId() != host_tid_) std::terminate();
        shutdown();
    }
}
void Bridge::start() {
    if (attempted_) throw std::runtime_error("startup is one-shot; a new process/session is required");
    attempted_ = true; host_tid_ = GetCurrentThreadId();
    char session[34]{}; DWORD n = GetEnvironmentVariableA("DM_NATIVE_SESSION", session, sizeof(session));
    if (n != 32 || !valid_session(std::string(session, n))) throw std::runtime_error("DM_NATIVE_SESSION must be 32 lowercase hexadecimal characters");
    session_.assign(session, n); pipe_name_ = L"\\\\.\\pipe\\dm_mcp_native_" + std::wstring(session_.begin(), session_.end());
    core_ = std::make_unique<Core>(session_, GetCurrentProcessId(), host_tid_);
    try {
        // Even partially failed adapter initialization is followed by shutdown.
        adapter_initialized_ = true; initialize_native(); inject_start_failure("adapter");
        stop_ = CreateEventW(nullptr, TRUE, FALSE, nullptr); stopped_ = CreateEventW(nullptr, TRUE, FALSE, nullptr);
        worker_ready_ = CreateEventW(nullptr, TRUE, FALSE, nullptr);
        audit_handle(stop_); audit_handle(stopped_); audit_handle(worker_ready_);
        if (!stop_ || !stopped_ || !worker_ready_) throw std::runtime_error("CreateEvent failed");
        inject_start_failure("events");
        if (!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
            reinterpret_cast<LPCWSTR>(&Bridge::worker_entry), &instance_)) throw std::runtime_error("GetModuleHandleEx failed");
        window_class_ = L"dm_mcp_native_" + std::to_wstring(GetCurrentProcessId()) + L"_" + std::wstring(session_.begin(), session_.end());
        WNDCLASSW wc{}; wc.lpfnWndProc = window_proc; wc.hInstance = instance_; wc.lpszClassName = window_class_.c_str();
        if (!RegisterClassW(&wc)) throw std::runtime_error("RegisterClass failed"); class_registered_ = true;
        inject_start_failure("class");
        window_ = CreateWindowExW(0, window_class_.c_str(), L"native bridge", 0, 0, 0, 0, 0,
            HWND_MESSAGE, nullptr, instance_, this);
        if (!window_) throw std::runtime_error("CreateWindowEx failed");
        inject_start_failure("window");
        if (!PostMessageW(window_, kReadyMessage, 0, 0)) throw std::runtime_error("readiness PostMessage failed");
        worker_ = CreateThread(nullptr, 0, worker_entry, this, 0, nullptr);
        audit_handle(worker_);
        if (!worker_) throw std::runtime_error("CreateThread failed");
        // The handshake covers Security and the first successful pipe creation.
        // It never depends on the queued host readiness callback.
        if (WaitForSingleObject(worker_ready_, 5000) != WAIT_OBJECT_0) throw std::runtime_error("worker startup handshake failed or timed out");
        {
            std::lock_guard<std::mutex> lock(startup_mutex_);
            if (!worker_start_error_.empty()) throw std::runtime_error(worker_start_error_);
        }
        inject_start_failure("worker"); started_ = true;
    } catch (...) { shutdown(); throw; }
}
void Bridge::request_stop() { if (stop_) SetEvent(stop_); }
bool Bridge::shutdown() {
    if (host_tid_ && GetCurrentThreadId() != host_tid_) throw std::runtime_error("shutdown must run on startup thread");
    if (core_) core_->close();
    request_stop();
    if (!can_close()) { shutdown_deferred_ = true; return false; }
    shutdown_deferred_ = false;
    if (worker_) {
        // Every worker wait includes stop_. It never waits for a host callback.
        // Confirm termination before freeing any state or unloading the DLL.
        if (WaitForSingleObject(worker_, INFINITE) != WAIT_OBJECT_0)
            throw std::runtime_error("worker termination was not confirmed; live state was retained");
        CloseHandle(worker_); worker_ = nullptr;
    }
    if (window_) {
        MSG msg{};
        while (PeekMessageW(&msg, window_, kReadyMessage, kShutdownMessage, PM_REMOVE)) {}
        DestroyWindow(window_); window_ = nullptr;
    }
    if (class_registered_) { UnregisterClassW(window_class_.c_str(), instance_); class_registered_ = false; }
    if (adapter_initialized_) {
        adapter_initialized_ = false;
        try { shutdown_native(); } catch (const std::exception& e) { diagnostic(e.what()); } catch (...) { diagnostic("adapter shutdown exception"); }
    }
    if (stop_) { CloseHandle(stop_); stop_ = nullptr; }
    if (stopped_) { CloseHandle(stopped_); stopped_ = nullptr; }
    if (worker_ready_) { CloseHandle(worker_ready_); worker_ready_ = nullptr; }
    started_ = false;
    return true;
}
LRESULT CALLBACK Bridge::window_proc(HWND hwnd, UINT message, WPARAM w, LPARAM l) {
    if (message == WM_NCCREATE) {
        auto* create = reinterpret_cast<CREATESTRUCTW*>(l);
        SetWindowLongPtrW(hwnd, GWLP_USERDATA, reinterpret_cast<LONG_PTR>(create->lpCreateParams));
    }
    auto* self = reinterpret_cast<Bridge*>(GetWindowLongPtrW(hwnd, GWLP_USERDATA));
    if (!self || (message != kReadyMessage && message != kWorkMessage && message != kShutdownMessage)) return DefWindowProcW(hwnd, message, w, l);
    bool active = false;
    try {
        if (message == kShutdownMessage) {
            self->worker_cleanup_dispatched_ = true;
            self->shutdown(); // May defer while a reentrant native callback runs.
            return 0;
        }
        if (message == kReadyMessage) { self->core_->mark_ready(GetCurrentThreadId()); return 0; }
        auto record = self->core_->begin(static_cast<std::uint64_t>(w), GetCurrentThreadId());
        if (!record) return 0;
        self->active_callbacks_.fetch_add(1, std::memory_order_release);
        active = true;
        try { self->core_->finish(record, execute_native(record->request)); }
        catch (const std::exception& e) { self->core_->finish(record, {}, "native_error", e.what()); }
        catch (...) { self->core_->finish(record, {}, "native_exception", "unknown C++ exception during native execution"); }
    } catch (const std::exception& e) { diagnostic(e.what()); self->request_stop(); }
    if (active) {
        self->active_callbacks_.fetch_sub(1, std::memory_order_release);
        if (self->shutdown_deferred_) {
            try { self->shutdown(); } catch (const std::exception& e) { diagnostic(e.what()); }
        }
    }
    return 0;
}
bool Bridge::io(HANDLE pipe, bool writing, void* data, DWORD count, DWORD& transferred, DWORD timeout) {
    Handle event(CreateEventW(nullptr, TRUE, FALSE, nullptr)); if (!event.h) return false;
    OVERLAPPED ov{}; ov.hEvent = event.h; transferred = 0;
    BOOL ok = writing ? WriteFile(pipe, data, count, &transferred, &ov) : ReadFile(pipe, data, count, &transferred, &ov);
    if (ok) return true;
    if (GetLastError() != ERROR_IO_PENDING) return false;
    HANDLE waits[] = {stop_, event.h}; DWORD wait = WaitForMultipleObjects(2, waits, FALSE, timeout);
    if (wait != WAIT_OBJECT_0 + 1) {
        CancelIoEx(pipe, &ov);
        // Cancellation completion precedes destruction of the stack OVERLAPPED.
        GetOverlappedResult(pipe, &ov, &transferred, TRUE); return false;
    }
    return GetOverlappedResult(pipe, &ov, &transferred, FALSE) != FALSE;
}
bool Bridge::connect(HANDLE pipe) {
    Handle event(CreateEventW(nullptr, TRUE, FALSE, nullptr)); if (!event.h) return false;
    OVERLAPPED ov{}; ov.hEvent = event.h;
    if (ConnectNamedPipe(pipe, &ov)) return true;
    DWORD error = GetLastError(); if (error == ERROR_PIPE_CONNECTED) return true;
    if (error != ERROR_IO_PENDING) return false;
    HANDLE waits[] = {stop_, event.h}; DWORD wait = WaitForMultipleObjects(2, waits, FALSE, INFINITE);
    DWORD transferred = 0;
    if (wait != WAIT_OBJECT_0 + 1) { CancelIoEx(pipe, &ov); GetOverlappedResult(pipe, &ov, &transferred, TRUE); return false; }
    return GetOverlappedResult(pipe, &ov, &transferred, FALSE) != FALSE;
}
void Bridge::serve(HANDLE pipe) {
    std::string frame, response; bool stop_after = false;
    const auto deadline = GetTickCount64() + kIoTimeoutMs;
    try {
        while (true) {
            char chunk[kMaxFrame + 1]; DWORD got = 0;
            auto now = GetTickCount64();
            if (now >= deadline || !io(pipe, false, chunk, sizeof(chunk), got, static_cast<DWORD>(deadline - now)) || !got) return;
            frame.append(chunk, got);
            auto lf = frame.find('\n');
            if (frame.size() > kMaxFrame) throw ProtocolError("frame_too_large", "frame exceeds 512 bytes including LF");
            if (lf != std::string::npos) {
                if (lf + 1 != frame.size()) throw ProtocolError("extra_frame", "one request frame is permitted per connection");
                DWORD extra = 0;
                if (!PeekNamedPipe(pipe, nullptr, 0, nullptr, &extra, nullptr)) return;
                if (extra) throw ProtocolError("extra_frame", "extra request bytes after final LF");
                frame.pop_back(); break;
            }
            if (frame.size() == kMaxFrame) throw ProtocolError("frame_too_large", "frame has no LF within 512 bytes");
        }
        auto p = parse_line(frame); auto admission = core_->accept(p);
        if (admission.dispatch_token && !PostMessageW(window_, kWorkMessage, static_cast<WPARAM>(admission.dispatch_token), 0)) {
            core_->dispatch_failed(admission.dispatch_token);
            p.request.op = "QUERY"; p.request.args.clear(); admission.receipt = core_->accept(p).receipt;
        }
        response = std::move(admission.receipt); stop_after = admission.stop;
    } catch (const ProtocolError& e) { response = core_->failure(request_id_hint(frame), e.code, e.what()); }
    if (response.empty() || response.size() > kMaxReply) return;
    std::size_t sent = 0; const auto write_deadline = GetTickCount64() + kIoTimeoutMs;
    while (sent < response.size()) {
        const auto now = GetTickCount64(); if (now >= write_deadline) break;
        DWORD wrote = 0;
        if (!io(pipe, true, response.data() + sent, static_cast<DWORD>(response.size() - sent), wrote, static_cast<DWORD>(write_deadline - now)) || !wrote) break;
        sent += wrote;
    }
    // Do not FlushFileBuffers: a silent reader can block that API indefinitely.
    // Keep the pipe alive until the client closes after reading LF, so its last
    // buffered response bytes are not discarded by DisconnectNamedPipe.
    if (sent == response.size()) { char extra = 0; DWORD got = 0; io(pipe, false, &extra, 1, got, kIoTimeoutMs); }
    if (stop_after) { core_->close(); SetEvent(stop_); }
}
DWORD WINAPI Bridge::worker_entry(void* p) {
    auto* self = static_cast<Bridge*>(p);
    try { self->worker(); } catch (const std::exception& e) { self->report_worker_start(e.what()); diagnostic(e.what()); self->core_->close(); }
    catch (...) { self->report_worker_start("unknown worker startup exception"); diagnostic("unknown worker exception"); self->core_->close(); }
    SetEvent(self->stopped_);
    // The worker never waits for this callback. The host joins the exited worker
    // before releasing adapter refs, the window and events. The Bridge object
    // remains owned by the plugin lifecycle; WndProc never deletes itself.
    if (!PostMessageW(self->window_, kShutdownMessage, 0, 0))
        diagnostic("worker exited but host cleanup PostMessage failed; normal plugin cleanup is still required");
    return 0;
}
void Bridge::report_worker_start(const std::string& error) {
    std::lock_guard<std::mutex> lock(startup_mutex_);
    if (worker_start_reported_) return;
    worker_start_reported_ = true; worker_start_error_ = error; SetEvent(worker_ready_);
}
void Bridge::worker() {
    core_->set_worker(GetCurrentThreadId()); inject_start_failure("security"); Security security;
    inject_start_failure("pipe");
    Handle pipe(CreateNamedPipeW(pipe_name_.c_str(), PIPE_ACCESS_DUPLEX | FILE_FLAG_OVERLAPPED | FILE_FLAG_FIRST_PIPE_INSTANCE,
        PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT | PIPE_REJECT_REMOTE_CLIENTS,
        1, 4096, 4096, 0, &security.attributes));
    if (pipe.h == INVALID_HANDLE_VALUE) throw std::runtime_error("CreateNamedPipe failed; server did not become available");
    audit_handle(pipe.h);
    report_worker_start({});
    while (WaitForSingleObject(stop_, 0) != WAIT_OBJECT_0) {
        if (connect(pipe.h) && WaitForSingleObject(stop_, 0) != WAIT_OBJECT_0) serve(pipe.h);
        CancelIoEx(pipe.h, nullptr); DisconnectNamedPipe(pipe.h);
    }
}
} // namespace nb
