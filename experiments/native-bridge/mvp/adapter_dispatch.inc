// Common adapter dispatch. Include after the registered version implementation(s).
// No vendor address, object layout, symbol signature or approximate-version rule
// belongs here. A new implementation is registered once beside its profile.
namespace {
struct AdapterImplementation {
    const nb::AdapterProfile* profile;
    void (*initialize)();
    std::string (*execute)(const NativeRequest&);
    void (*shutdown)();
    bool (*ready)();
    std::string (*error)();
    void (*observe_entries)(nb::HostObservation&);
};
const std::vector<AdapterImplementation>& implementations() {
    static const std::vector<AdapterImplementation> values{{&nb::gms353::profile(),
        nb353_initialize, nb353_execute, nb353_shutdown,
        nb353_ready, nb353_error, nb353_observe_entries}};
    return values;
}
nb::HostObservation observed_host;
nb::AdapterSelection selected_adapter;
const AdapterImplementation* active_implementation = nullptr;
DWORD adapter_owner_thread = 0;

std::string compatibility_fields() {
    std::string fields = ",\"host_build\":" + (observed_host.version_readable ? nb::quote(observed_host.version.str()) : "null") +
        ",\"host_architecture\":" + (observed_host.architecture.empty() ? "null" : nb::quote(observed_host.architecture)) +
        ",\"adapter_profile\":" + (selected_adapter.profile ? nb::quote(selected_adapter.profile->id) : "null") +
        ",\"adapter_active\":" + (selected_adapter.safe() && active_implementation ? "true" : "false") +
        ",\"compatibility\":{\"state\":" + nb::quote(nb::compatibility_name(selected_adapter.compatibility)) +
        ",\"reason\":" + nb::quote(selected_adapter.reason) + "},\"native_capabilities\":[";
    if (selected_adapter.profile) {
        bool first = true;
        for (const auto& spec : selected_adapter.profile->capabilities) {
            if (!first) fields += ',';
            first = false;
            std::string reason = selected_adapter.reason;
            for (const auto& capability : selected_adapter.capabilities)
                if (capability.name == spec.name) reason = capability.reason;
            fields += "{\"name\":" + nb::quote(spec.name) + ",\"available\":" +
                (selected_adapter.available(spec.name) ? "true" : "false") +
                ",\"qualification\":" + nb::quote(spec.qualified ? "LIMITED_REAL_HOST" : "NOT_QUALIFIED") +
                ",\"scope\":" + nb::quote(spec.scope) + ",\"reason\":" + nb::quote(reason) + '}';
        }
    }
    fields += "],\"module_identity\":[";
    bool first = true;
    for (const auto& module : observed_host.modules) {
        if (!first) fields += ',';
        first = false;
        fields += "{\"name\":" + nb::quote(module.name) + ",\"loaded\":" + (module.loaded ? "true" : "false") +
            ",\"readable\":" + (module.readable ? "true" : "false") + ",\"sha256\":" +
            (module.sha256.empty() ? "null" : nb::quote(module.sha256)) + '}';
    }
    return fields + ']';
}
} // namespace

void initialize_native() {
    adapter_owner_thread = GetCurrentThreadId();
    std::vector<const nb::AdapterProfile*> profiles;
    for (const auto& implementation : implementations()) profiles.push_back(implementation.profile);
    observed_host = nb::identity::observe(profiles);
    selected_adapter = nb::select_adapter(observed_host, profiles);
    if (!selected_adapter.safe()) return;
    for (const auto& implementation : implementations()) if (implementation.profile == selected_adapter.profile) {
        // Selection is the only entrance into a version implementation.
        nb::require_selected_adapter(selected_adapter);
        active_implementation = &implementation;
        implementation.initialize();
        if (!implementation.ready()) {
            selected_adapter.compatibility = nb::Compatibility::AbiMismatch;
            selected_adapter.reason = implementation.error();
            return;
        }
        implementation.observe_entries(observed_host);
        selected_adapter = nb::select_adapter(observed_host, profiles);
        return;
    }
    selected_adapter.compatibility = nb::Compatibility::NotReady;
    selected_adapter.reason = "adapter_implementation_unavailable";
}

std::string execute_native(const NativeRequest& request) {
    if (active_implementation && selected_adapter.safe() && !active_implementation->ready()) {
        selected_adapter.compatibility = nb::Compatibility::AbiMismatch;
        selected_adapter.reason = active_implementation->error();
    }
    if (request.op == "STATUS") {
        std::string result;
        if (selected_adapter.safe() && active_implementation) result = active_implementation->execute(request);
        else result = "{\"backend\":\"digitalmicrograph-native\",\"ready\":false,\"binary_gate\":false,"
            "\"supported_build\":null,\"host_pid\":" + std::to_string(GetCurrentProcessId()) +
            ",\"host_thread\":" + std::to_string(adapter_owner_thread) +
            ",\"resident_python_required\":false,\"arbitrary_script\":false,\"requires_idle_host\":true,"
            "\"capabilities\":[],\"build_error\":" + nb::quote(selected_adapter.reason) + '}';
        if (!nb::valid_json(result) || result.empty() || result.back() != '}')
            throw std::runtime_error("invalid_adapter_status_contract");
        result.pop_back();
        return result + compatibility_fields() + '}';
    }
    nb::require_selected_adapter(selected_adapter);
    if (!active_implementation) throw std::runtime_error("native_adapter_NOT_READY:no_implementation");
    const char* required = request.op == "DATASETS" || request.op == "INFO" ? "native_datasets" :
        request.op == "MEAN" ? "native_mean" : request.op == "SUMMARY" ? "native_statistics" :
        request.op == "CROP" ? "native_crop" : request.op == "SHOW" ? "native_display" :
        request.op == "UNARY" || request.op == "BINARY" ? "native_image_arithmetic" :
        request.op == "FFT" || request.op == "IFFT" || request.op == "REAL" || request.op == "IMAG" ||
            request.op == "VENDOR_ARG" || request.op == "VENDOR_NORM" ? "native_fft" :
        request.op == "FILTER" ? "native_filters" : request.op == "PREVIEW" ? "native_preview" :
        request.op == "READ" ? "native_read" :
        request.op == "ROIS" ? "native_gui_rois" :
        request.op == "PROFILE" ? "native_line_profile" :
        request.op == "RELEASE" || request.op == "RESULT_INFO" ? "native_result_release" : nullptr;
    if (required && !selected_adapter.available(required))
        throw std::runtime_error(std::string("native_capability_unavailable:") + required);
    return active_implementation->execute(request);
}

void shutdown_native() {
    // An unknown/rejected host never enters version-specific destruction code.
    if (active_implementation) active_implementation->shutdown();
    active_implementation = nullptr;
    selected_adapter.compatibility = nb::Compatibility::NotReady;
    selected_adapter.reason = "native_adapter_stopped";
    selected_adapter.capabilities.clear();
}
