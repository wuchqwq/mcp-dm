#include "bridge.hpp"
#include <memory>

namespace {
std::unique_ptr<nb::Bridge> bridge;
bool attempted = false;
void stop() {
    if (!bridge) return;
    try { if (bridge->shutdown()) bridge.reset(); }
    catch (const std::exception& e) { OutputDebugStringA(e.what()); }
}
}
extern "C" __declspec(dllexport) void PlugInGetSDKVersion(int* major, int* minor) {
    if (major) *major = 3; if (minor) *minor = 5;
}
extern "C" __declspec(dllexport) void DMPlugIn_Link_2(void*) {}
extern "C" __declspec(dllexport) void PlugInStartup() {
    if (attempted) return;
    attempted = true;
    try { bridge = std::make_unique<nb::Bridge>(); bridge->start(); }
    catch (const std::exception& e) { OutputDebugStringA(e.what()); stop(); }
}
extern "C" __declspec(dllexport) void PlugInRegisterFloatingWindows() {}
extern "C" __declspec(dllexport) void PlugInRun() {}
extern "C" __declspec(dllexport) void PlugInCleanup() { stop(); }
extern "C" __declspec(dllexport) int PlugInRequestClose() { return !bridge || bridge->can_close() ? 1 : 0; }
extern "C" __declspec(dllexport) void PlugInPrepareClose() {}
extern "C" __declspec(dllexport) void PlugInShutdown() { stop(); }
