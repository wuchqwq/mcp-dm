#pragma once
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <atomic>
#include "core.hpp"
#include <memory>
#include <string>
#include <vector>

namespace nb {
constexpr UINT kReadyMessage = WM_APP + 0x221;
constexpr UINT kWorkMessage = WM_APP + 0x222;
constexpr UINT kShutdownMessage = WM_APP + 0x223;
class Bridge {
public:
    explicit Bridge(std::string startup_test_failure = {}, bool test_audit = false);
    ~Bridge();
    Bridge(const Bridge&) = delete;
    Bridge& operator=(const Bridge&) = delete;
    void start(); // startup thread only; no retry following failure or STOP
    bool shutdown(); // false means deferred until the active host callback exits
    void request_stop(); // thread safe
    HANDLE stopped_event() const { return stopped_; }
    bool started() const { return started_; }
    bool can_close() const { return active_callbacks_.load(std::memory_order_acquire) == 0; }
    bool audited_resources_released(); // Offline harness only; inspects real OS handles.
    bool worker_cleanup_dispatched() const { return worker_cleanup_dispatched_; }
private:
    static LRESULT CALLBACK window_proc(HWND, UINT, WPARAM, LPARAM);
    static DWORD WINAPI worker_entry(void*);
    void worker();
    bool connection(HANDLE pipe);
    bool io(HANDLE pipe, bool writing, void* bytes, DWORD count, DWORD& transferred, DWORD timeout_ms);
    bool connect(HANDLE pipe);
    void serve(HANDLE pipe);
    void report_worker_start(const std::string& error);
    void inject_start_failure(const std::string& stage) const;
    void audit_handle(HANDLE handle);
    std::string session_;
    std::wstring pipe_name_, window_class_;
    std::unique_ptr<Core> core_;
    HINSTANCE instance_ = nullptr;
    HWND window_ = nullptr;
    HANDLE stop_ = nullptr, stopped_ = nullptr, worker_ = nullptr, worker_ready_ = nullptr;
    DWORD host_tid_ = 0;
    bool attempted_ = false, started_ = false, adapter_initialized_ = false, class_registered_ = false;
    std::atomic<unsigned> active_callbacks_{0};
    bool shutdown_deferred_ = false;
    bool worker_cleanup_dispatched_ = false;
    const std::string startup_test_failure_;
    const bool test_audit_;
    std::vector<HANDLE> audited_handles_;
    std::mutex startup_mutex_;
    bool worker_start_reported_ = false;
    std::string worker_start_error_;
};
} // namespace nb
