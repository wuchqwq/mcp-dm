#include "adapter.hpp"
#include "core.hpp"
#include <windows.h>
#include <cstdlib>
#include <iostream>
#include <map>
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
namespace {
// Opt-in full-chain test state only. Neither this EXE nor its event-signalling
// helper loads a Gatan module, creates a real image or opens a DM document.
struct SyntheticCrop {
    std::uint32_t source;
    std::vector<std::uint32_t> args;
    bool document = false;
};
std::map<std::uint32_t, SyntheticCrop> synthetic_crops;
std::map<std::string, std::uint32_t> synthetic_creations;
unsigned synthetic_show_calls = 0, synthetic_documents = 0;
unsigned synthetic_gates_started = 0, synthetic_gates_released = 0;
unsigned synthetic_gates_closed = 0, synthetic_gate_close_failures = 0;
bool valid_gate_id(const std::string& id) {
    if (id.empty() || id.size() > 64) return false;
    for (unsigned char c : id)
        if (!(c >= 'a' && c <= 'z') && !(c >= 'A' && c <= 'Z') &&
            !(c >= '0' && c <= '9') && c != '_' && c != '-') return false;
    return true;
}
std::wstring gate_name(const std::string& session, const std::string& id) {
    if (!nb::valid_session(session) || !valid_gate_id(id)) throw std::runtime_error("invalid synthetic gate identity");
    const std::string name = "Local\\dm_mcp_synthetic_" + session + "_" + id;
    return std::wstring(name.begin(), name.end());
}
void crop_gate(const NativeRequest& r) {
    const char* gates = std::getenv("NB_FAKE_E2E_GATE_IDS");
    if (!gates || ("," + std::string(gates) + ",").find("," + r.id + ",") == std::string::npos) return;
    const char* session = std::getenv("DM_NATIVE_SESSION");
    if (!session) throw std::runtime_error("synthetic gate session missing");
    HANDLE event = CreateEventW(nullptr, TRUE, FALSE, gate_name(session, r.id).c_str());
    if (!event) throw std::runtime_error("synthetic gate creation failed");
    const DWORD created = GetLastError();
    struct Close {
        HANDLE value;
        ~Close() { if (CloseHandle(value)) ++synthetic_gates_closed; else ++synthetic_gate_close_failures; }
    } close{event};
    if (created == ERROR_ALREADY_EXISTS) throw std::runtime_error("synthetic gate already exists");
    ++synthetic_gates_started;
    // Core::begin already marked this immutable operation running. Emit only
    // after the real event exists; the test also QUERYs its running receipt.
    std::cout << "{\"synthetic_event\":\"crop_running\",\"request_id\":" << nb::quote(r.id)
              << ",\"gate_created\":true,\"exec_tid\":" << GetCurrentThreadId() << "}" << std::endl;
    if (WaitForSingleObject(event, 15000) != WAIT_OBJECT_0)
        throw std::runtime_error("synthetic crop gate timed out");
    ++synthetic_gates_released;
}
std::string synthetic_execute(const NativeRequest& r) {
    if (r.op == "STATUS") return "{\"backend\":\"synthetic_mock\",\"synthetic_only\":true,\"ready\":true,\"host_tid\":" +
        std::to_string(GetCurrentThreadId()) + ",\"synthetic_crops_created\":" + std::to_string(synthetic_crops.size()) +
        ",\"synthetic_documents_created\":" + std::to_string(synthetic_documents) +
        ",\"synthetic_show_calls\":" + std::to_string(synthetic_show_calls) + "}";
    if (r.op == "CROP") {
        if (r.args.size() != 5 || r.args[0] < 1 || r.args[0] > 2 || r.args[1] >= r.args[3] ||
            r.args[2] >= r.args[4] || r.args[3] > 4 || r.args[4] > 3)
            throw std::runtime_error("synthetic crop requires explicit source and valid half-open bounds");
        crop_gate(r);
        const auto id = static_cast<std::uint32_t>(101 + synthetic_crops.size());
        synthetic_crops.emplace(id, SyntheticCrop{r.args[0], r.args, false});
        if (!synthetic_creations.emplace(r.id, id).second)
            throw std::runtime_error("synthetic crop was executed twice for one request ID");
        std::cout << "{\"synthetic_event\":\"crop_created\",\"request_id\":" << nb::quote(r.id)
                  << ",\"image_id\":" << id << ",\"creation_count\":" << synthetic_crops.size() << "}" << std::endl;
        const auto rect = "[" + std::to_string(r.args[1]) + "," + std::to_string(r.args[2]) + "," +
            std::to_string(r.args[3]) + "," + std::to_string(r.args[4]) + "]";
        return "{\"backend\":\"synthetic_mock\",\"synthetic_only\":true,\"source_image_id\":" + std::to_string(r.args[0]) +
            ",\"image_id\":" + std::to_string(id) + ",\"requested_rect\":" + rect + ",\"effective_rect\":" + rect +
            ",\"shape\":[" + std::to_string(r.args[4] - r.args[2]) + "," + std::to_string(r.args[3] - r.args[1]) +
            "],\"dtype\":\"float32\",\"source_write_requested\":false,\"snapshot_atomic\":false}";
    }
    if (r.op == "SHOW") {
        if (r.args.size() != 1 || synthetic_crops.find(r.args[0]) == synthetic_crops.end())
            throw std::runtime_error("synthetic show requires this fake host's crop");
        auto& crop = synthetic_crops.at(r.args[0]);
        ++synthetic_show_calls;
        if (!crop.document) { crop.document = true; ++synthetic_documents; }
        return "{\"backend\":\"synthetic_mock\",\"synthetic_only\":true,\"image_id\":" + std::to_string(r.args[0]) +
            ",\"delivery\":\"visible_dm_document\",\"document_visible\":true,"
            "\"operator\":\"synthetic document delivery only; no Gatan call\","
            "\"ownership\":\"synthetic counter only; no real host document exists\","
            "\"source_write_requested\":false,\"snapshot_atomic\":false,\"file_saved\":false,\"model_visual_verification\":false}";
    }
    if (r.op == "MEAN" && r.args.size() == 1 && r.args[0] >= 1 && r.args[0] <= 2)
        return "{\"backend\":\"synthetic_mock\",\"synthetic_only\":true,\"image_id\":" + std::to_string(r.args[0]) +
            ",\"mean\":" + (r.args[0] == 1 ? "-1.25}" : "0.125}");
    throw std::runtime_error("unsupported synthetic E2E operation");
}
} // namespace
bool fake_e2e_enabled() { return setting("NB_FAKE_E2E") == 1; }
void fake_e2e_ready() {
    if (fake_e2e_enabled()) std::cout << "{\"synthetic_event\":\"host_ready\",\"host_tid\":" << GetCurrentThreadId() << "}" << std::endl;
}
int fake_release_gate(const std::string& session, const std::string& id) {
    const char* expected_session = std::getenv("DM_NATIVE_SESSION");
    if (!fake_e2e_enabled() || !expected_session || session != expected_session) return 2;
    HANDLE event = OpenEventW(EVENT_MODIFY_STATE, FALSE, gate_name(session, id).c_str());
    if (!event) return 2;
    const bool released = SetEvent(event) != FALSE;
    CloseHandle(event);
    if (released) std::cout << "{\"synthetic_gate_released\":true,\"request_id\":" << nb::quote(id) << "}" << std::endl;
    return released ? 0 : 2;
}
std::string fake_e2e_lifecycle() {
    std::string out = ",\"synthetic_e2e\":" + std::string(fake_e2e_enabled() ? "true" : "false") +
        ",\"synthetic_crops_created\":" + std::to_string(synthetic_crops.size()) +
        ",\"synthetic_documents_created\":" + std::to_string(synthetic_documents) +
        ",\"synthetic_show_calls\":" + std::to_string(synthetic_show_calls) +
        ",\"synthetic_gates_started\":" + std::to_string(synthetic_gates_started) +
        ",\"synthetic_gates_released\":" + std::to_string(synthetic_gates_released) +
        ",\"synthetic_gates_closed\":" + std::to_string(synthetic_gates_closed) +
        ",\"synthetic_gate_close_failures\":" + std::to_string(synthetic_gate_close_failures) + ",\"synthetic_creations\":[";
    bool first = true;
    for (const auto& entry : synthetic_creations) {
        if (!first) out += ',';
        first = false;
        out += "{\"request_id\":" + nb::quote(entry.first) + ",\"image_id\":" + std::to_string(entry.second) + "}";
    }
    return out + "]";
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
    if (fake_e2e_enabled()) return synthetic_execute(r);
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
