#include "bridge.hpp"
#include <cstdlib>
#include <iostream>
#include <vector>
#include <utility>

extern int fake_initialize_count, fake_shutdown_count, fake_execute_count;
extern int fake_shutdown_during_execute;
extern void (*fake_reentrant_hook)();
static nb::Bridge* fake_bridge = nullptr;
static bool fake_close_refused = false, fake_shutdown_deferred = false;
static void reenter() {
    fake_close_refused = !fake_bridge->can_close();
    fake_shutdown_deferred = !fake_bridge->shutdown();
}
static unsigned setting(const char* name) {
    const char* v = std::getenv(name); return v ? static_cast<unsigned>(std::strtoul(v, nullptr, 10)) : 0;
}
int main() {
    DWORD handles_before = 0; GetProcessHandleCount(GetCurrentProcess(), &handles_before);
    const char* fail_stage = std::getenv("NB_FAKE_START_FAIL_STAGE");
    nb::Bridge bridge(fail_stage ? fail_stage : "", true); int exit_code = 0;
    fake_bridge = &bridge; fake_reentrant_hook = reenter;
    try {
        bridge.start();
        std::cout << "{\"fake_host\":true,\"pid\":" << GetCurrentProcessId() << ",\"host_tid\":" << GetCurrentThreadId() << "}" << std::endl;
        const auto started = GetTickCount64(); const auto close_ms = setting("NB_FAKE_CLOSE_AFTER_MS");
        std::vector<std::pair<ULONGLONG, MSG>> deferred;
        bool running = true;
        while (running && bridge.started()) {
            HANDLE stopped = bridge.stopped_event();
            DWORD result = MsgWaitForMultipleObjects(1, &stopped, FALSE, 20, QS_ALLINPUT);
            // STOP is complete only after the posted host cleanup callback has
            // released adapter/window/event resources. The worker never waits.
            if (result == WAIT_FAILED) throw std::runtime_error("fake host wait failed");
            if (close_ms && GetTickCount64() - started >= close_ms) break;
            MSG msg{};
            while (PeekMessageW(&msg, nullptr, 0, 0, PM_REMOVE)) {
                if (msg.message == WM_QUIT) { running = false; break; }
                unsigned delay = msg.message == nb::kWorkMessage ? setting("NB_FAKE_DISPATCH_DELAY_MS") :
                    (msg.message == nb::kReadyMessage ? setting("NB_FAKE_READY_DELAY_MS") : 0);
                if (delay) deferred.emplace_back(GetTickCount64() + delay, msg);
                else { TranslateMessage(&msg); DispatchMessageW(&msg); }
            }
            for (auto it = deferred.begin(); it != deferred.end();) {
                if (it->first > GetTickCount64()) { ++it; continue; }
                DispatchMessageW(&it->second); it = deferred.erase(it);
            }
        }
        bridge.shutdown();
    } catch (const std::exception& e) {
        exit_code = 2; std::cerr << e.what() << '\n'; bridge.shutdown();
    }
    DWORD handles_after = 0; GetProcessHandleCount(GetCurrentProcess(), &handles_after);
    std::cout << "{\"mock_lifecycle\":true,\"initialize\":" << fake_initialize_count <<
        ",\"shutdown\":" << fake_shutdown_count << ",\"execute\":" << fake_execute_count <<
        ",\"shutdown_during_execute\":" << fake_shutdown_during_execute <<
        ",\"close_refused\":" << (fake_close_refused ? "true" : "false") <<
        ",\"shutdown_deferred\":" << (fake_shutdown_deferred ? "true" : "false") <<
        ",\"owned_resources_released\":" << (bridge.audited_resources_released() ? "true" : "false") <<
        ",\"worker_cleanup_dispatched\":" << (bridge.worker_cleanup_dispatched() ? "true" : "false") <<
        ",\"handle_delta\":" << static_cast<long>(handles_after) - static_cast<long>(handles_before) << "}" << std::endl;
    return exit_code;
}
