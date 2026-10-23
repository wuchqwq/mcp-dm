#include "adapter.hpp"
#include <windows.h>
#include <cstdlib>
#include <stdexcept>
#include <string>

// Explicit offline mock: no vendor DLL is loaded or called by this executable.
int fake_initialize_count = 0, fake_shutdown_count = 0, fake_execute_count = 0;
int fake_shutdown_during_execute = 0;
bool fake_inside_execute = false;
void (*fake_reentrant_hook)() = nullptr;
static unsigned setting(const char* name) {
    const char* v = std::getenv(name); return v ? static_cast<unsigned>(std::strtoul(v, nullptr, 10)) : 0;
}
void initialize_native() {
    ++fake_initialize_count;
    if (setting("NB_FAKE_INIT_FAIL")) throw std::runtime_error("injected mock initialization failure");
}
void shutdown_native() { ++fake_shutdown_count; if (fake_inside_execute) ++fake_shutdown_during_execute; }
std::string execute_native(const NativeRequest& r) {
    struct ExecuteScope { ExecuteScope() { fake_inside_execute = true; } ~ExecuteScope() { fake_inside_execute = false; } } scope;
    ++fake_execute_count;
    Sleep(setting("NB_FAKE_EXECUTE_DELAY_MS"));
    if (r.op != "STATUS" && setting("NB_FAKE_REENTER_SHUTDOWN") && fake_reentrant_hook) fake_reentrant_hook();
    if (setting("NB_FAKE_BAD_JSON")) return "{\"mean\":NaN}";
    if (r.op == "STATUS") return "{\"backend\":\"synthetic_mock\",\"ready\":true,\"host_tid\":" + std::to_string(GetCurrentThreadId()) + "}";
    if (r.op == "DATASETS") {
        unsigned bytes = setting("NB_FAKE_REPLY_BYTES");
        if (bytes) return "{\"backend\":\"synthetic_mock\",\"padding\":\"" + std::string(bytes, 'x') + "\"}";
        return u8"{\"backend\":\"synthetic_mock\",\"datasets\":[{\"image_id\":1,\"name\":\"中文图像\",\"unit\":\"µm\"},{\"image_id\":2}]}";
    }
    if (r.args.empty() || r.args[0] == 0 || r.args[0] > 2) throw std::runtime_error("mock image id not found");
    if (r.op == "MEAN") return r.args[0] == 1 ? "{\"backend\":\"synthetic_mock\",\"mean\":-1.25}" : "{\"backend\":\"synthetic_mock\",\"mean\":0.125}";
    if (r.op == "INFO") return "{\"backend\":\"synthetic_mock\",\"image_id\":" + std::to_string(r.args[0]) + ",\"shape\":[3,4],\"dtype\":\"float32\"}";
    if (r.op == "SHOW") {
        if (r.args.size() != 1) throw std::runtime_error("mock show requires one image id");
        return "{\"backend\":\"synthetic_mock\",\"image_id\":" + std::to_string(r.args[0]) +
            ",\"delivery\":\"visible_dm_document\",\"document_visible\":true,\"operator\":\"ImageGetOrCreateImageDocument + ImageDocumentShow\","
            "\"ownership\":\"mock delivery only; no host document exists\",\"source_write_requested\":false,\"snapshot_atomic\":false,"
            "\"file_saved\":false,\"model_visual_verification\":false}";
    }
    if (r.op == "CROP") {
        if (r.args.size() != 5 || r.args[1] >= r.args[3] || r.args[2] >= r.args[4] || r.args[3] > 4 || r.args[4] > 3)
            throw std::runtime_error("mock crop must use valid half-open bounds");
        return "{\"backend\":\"synthetic_mock\",\"source_unchanged\":true,\"shape\":[" +
            std::to_string(r.args[4] - r.args[2]) + "," + std::to_string(r.args[3] - r.args[1]) + "]}";
    }
    throw std::runtime_error("unsupported mock operation");
}
