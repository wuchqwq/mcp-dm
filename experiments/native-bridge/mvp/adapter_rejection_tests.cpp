// Exercise the production dispatcher in a non-GMS process. Even deliberately
// injected callable surrogates must remain unreachable on a rejected identity.
#include "dm_adapter.cpp"
#include <iostream>

namespace {
int native_calls = 0, implementation_calls = 0, checks = 0;
NativeRef* must_not_find(NativeRef* out, std::uint32_t) { ++native_calls; return out; }
std::string counted_implementation(const NativeRequest&) { ++implementation_calls; return "{}"; }
void check(bool value) { ++checks; if (!value) throw std::runtime_error("rejection check failed"); }
void must_reject(const NativeRequest& request, const std::string& expected = {}) {
    std::string failure;
    try { (void)execute_native(request); } catch (const std::runtime_error& error) { failure = error.what(); }
    check(!failure.empty() && native_calls == 0 && implementation_calls == 0);
    if (!expected.empty()) check(failure == expected);
}
}
int main() {
    try {
        initialize_native();
        check(selected_adapter.compatibility == nb::Compatibility::NotReady);
        check(!active_implementation && !GetModuleHandleW(L"GMSImage.dll"));
        api.find_id = must_not_find;
        const std::vector<std::pair<NativeRequest, const char*>> operations{
            {{"test", "DATASETS", {}}, "native_datasets"}, {{"test", "INFO", {17}}, "native_datasets"},
            {{"test", "MEAN", {17}}, "native_mean"}, {{"test", "SUMMARY", {17}}, "native_statistics"},
            {{"test", "CROP", {17, 0, 0, 2, 2}}, "native_crop"}, {{"test", "SHOW", {17}}, "native_display"},
            {{"test", "UNARY", {17, 1}}, "native_image_arithmetic"}, {{"test", "BINARY", {17, 18, 1}}, "native_image_arithmetic"},
            {{"test", "FFT", {17}}, "native_fft"}, {{"test", "IFFT", {17}}, "native_fft"},
            {{"test", "REAL", {17}}, "native_fft"}, {{"test", "IMAG", {17}}, "native_fft"},
            {{"test", "VENDOR_ARG", {17}}, "native_fft"}, {{"test", "VENDOR_NORM", {17}}, "native_fft"},
            {{"test", "FILTER", {17, 1}}, "native_filters"}, {{"test", "PREVIEW", {17, 128, 128}}, "native_preview"},
            {{"test", "READ", {17, 0, 0, 1, 1}}, "native_read"},
            {{"test", "ROIS", {17}}, "native_gui_rois"},
            {{"test", "PROFILE", {17,31,9,7,2,1,7,1,1}}, "native_line_profile"},
            {{"test", "HISTOGRAM", {17,4,0,1098907648}}, "native_histogram"},
            {{"test", "FRAME", {17,0}}, "native_frame"},
            {{"test", "CROP_PIXEL", {17,0,0,2,2}}, "native_pixel_crop"},
            {{"test", "FILTER_PIXEL", {17,1}}, "native_pixel_filters"},
            {{"test", "FFT_PIXEL", {17}}, "native_pixel_fft"},
            {{"test", "IFFT_PIXEL", {17}}, "native_pixel_fft"},
            {{"test", "REAL_PIXEL", {17}}, "native_pixel_fft"},
            {{"test", "IMAG_PIXEL", {17}}, "native_pixel_fft"},
            {{"test", "VENDOR_ARG_PIXEL", {17}}, "native_pixel_fft"},
            {{"test", "VENDOR_NORM_PIXEL", {17}}, "native_pixel_fft"}
        };
        // A former preparation variable cannot bypass version or group gates.
        SetEnvironmentVariableA("DM_NATIVE_QUALIFY_OPERATIONS", "1");
        for (const auto state : {nb::Compatibility::UnsupportedBuild, nb::Compatibility::AbiMismatch, nb::Compatibility::NotReady}) {
            selected_adapter.compatibility = state;
            selected_adapter.reason = "deliberately rejected offline identity";
            active_implementation = &implementations().front();
            for (const auto& operation : operations) must_reject(operation.first);
            const auto status = execute_native({"status", "STATUS", {}});
            check(nb::valid_json(status) && status.find("\"ready\":false") != std::string::npos &&
                  status.find(nb::compatibility_name(state)) != std::string::npos && native_calls == 0);
        }
        // A spy proves rejection occurs before entering a version implementation,
        // rather than incidentally throwing on a null binding or wrong thread.
        auto instrumented = implementations().front();
        instrumented.execute = counted_implementation;
        instrumented.ready = [] { return true; };
        gate_error.clear(); fatal_abi = false;
        selected_adapter.compatibility = nb::Compatibility::Supported;
        selected_adapter.profile = &nb::gms353::profile();
        active_implementation = &instrumented;
        selected_adapter.capabilities.clear();
        for (const auto& operation : operations)
            must_reject(operation.first, std::string("native_capability_unavailable:") + operation.second);
        for (const auto* group : {"native_image_arithmetic", "native_fft", "native_filters", "native_preview", "native_read", "native_gui_rois", "native_line_profile", "native_histogram", "native_frame"}) {
            selected_adapter.capabilities.clear();
            for (const auto& spec : nb::gms353::profile().capabilities)
                selected_adapter.capabilities.push_back({spec.name, spec.scope, "synthetic observation",
                    spec.qualified && std::string(spec.name) != group});
            check(selected_adapter.available("native_datasets") && selected_adapter.available("native_statistics"));
            for (const auto& operation : operations) if (std::string(operation.second) == group)
                must_reject(operation.first, std::string("native_capability_unavailable:") + group);
        }
        // Coordinate qualification supplements, never replaces, the original
        // operator binding/qualification. Inject a candidate observation only.
        for (const auto* missing : {"native_crop","native_filters","native_fft"}) {
            selected_adapter.capabilities.clear();
            for (const auto& spec:nb::gms353::profile().capabilities)
                selected_adapter.capabilities.push_back({spec.name,spec.scope,"synthetic observation",
                    std::string(spec.name)!=missing && (spec.qualified || std::string(spec.name).find("native_pixel_")==0)});
            for (const auto& operation:operations) {
                const auto base=nb::base_operation353(operation.first.op);
                if (nb::pixel_mode353(operation.first.op) && ((base=="CROP" && std::string(missing)=="native_crop") ||
                    (base=="FILTER" && std::string(missing)=="native_filters") ||
                    (nb::is_fft_operation353(base) && std::string(missing)=="native_fft")))
                    must_reject(operation.first,std::string("native_capability_unavailable:")+missing);
            }
        }
        check(execute_native({"healthy_core", "INFO", {17}}) == "{}");
        check(implementation_calls == 1 && native_calls == 0);
        SetEnvironmentVariableA("DM_NATIVE_QUALIFY_OPERATIONS", nullptr);
        active_implementation = nullptr;
        shutdown_native();
        check(!GetModuleHandleW(L"GMSImage.dll") && native_calls == 0);
        std::cout << "PASS production adapter rejection " << checks << " checks; vendor calls=0\n";
        return 0;
    } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
