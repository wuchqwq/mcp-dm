// Offline histogram adapter checks. Synthetic C callbacks only; no GMS loaded.
#include <optional>
#define main existing_adapter_test_main
#include "adapter_tests.cpp"
#undef main

namespace {
std::map<const void*, std::vector<double>> histogram_counts353;
std::string histogram_fault353;
int histogram_create_calls353 = 0, histogram_calc_calls353 = 0, histogram_set_calls353 = 0;
double histogram_intensity_origin353 = 2.5, histogram_intensity_scale353 = -3;
std::wstring histogram_intensity_unit353 = L"counts";

NativeRef* histogram_create_fake353(NativeRef* out, const nb::NativeDataSize353* size, std::uint32_t type,
                                     const nb::NativeCharRange353* name) {
    ++histogram_create_calls353;
    check(out != nullptr && size != nullptr && type == 11 && name != nullptr && name->begin != name->end);
    check(size->dimensions == 1 && size->size[0] > 0 && size->size[1] == 0);
    if (histogram_fault353 == "create_null") { out->image = nullptr; return out; }
    auto* created = new FakeImage;
    created->generated = true;
    created->id = next_image_id++;
    created->dimensions = histogram_fault353 == "output_rank" ? 2 : 1;
    created->code = histogram_fault353 == "output_dtype" ? 2 : 11;
    created->packing = histogram_fault353 == "output_packing" ? 2 : 1;
    created->width = histogram_fault353 == "output_bins" ? static_cast<std::uint32_t>(size->size[0]) + 1
                                                        : static_cast<std::uint32_t>(size->size[0]);
    created->height = 1;
    created->scale[0] = 1; created->origin[0] = 0; created->unit[0] = L"";
    registry.emplace(created->id, created);
    out->image = created;
    return out;
}
void histogram_calc_fake353(const NativeRef* source, const NativeRef* destination, double minimum, double maximum) {
    ++histogram_calc_calls353;
    check(source && destination && destination->image);
    const auto bins = static_cast<std::uint32_t>(static_cast<const FakeImage*>(destination->image)->width);
    const auto width = (maximum - minimum) / bins;
    std::vector<double> counts(bins, 0.0);
    for (const auto value : static_cast<const FakeImage*>(source->image)->pixels) {
        auto index = static_cast<long>(std::floor((value - minimum) / width));
        if (index < 0) index = 0;
        if (index >= static_cast<long>(bins)) index = static_cast<long>(bins) - 1;
        counts[static_cast<std::size_t>(index)] += 1.0;
    }
    if (histogram_fault353 == "incomplete") counts.front() -= 1;
    if (histogram_fault353 == "fractional") counts.front() += 0.5;
    if (histogram_fault353 == "negative") counts.front() = -3;
    if (histogram_fault353 == "nonfinite") counts.front() = std::numeric_limits<double>::infinity();
    if (histogram_fault353 == "oversized") counts.front() = 1e9;
    histogram_counts353[destination->image] = counts;
}
void histogram_intensity_fake353(void* image, float* origin, float* scale, void* unit) {
    *origin = static_cast<float>(histogram_intensity_origin353);
    *scale = static_cast<float>(histogram_intensity_scale353);
    fill(static_cast<MsvcWString353*>(unit), histogram_intensity_unit353);
    (void)image;
}
double histogram_value_fake353(const void* image, const nb::NativeDataIndex1D353* index) {
    const auto found = histogram_counts353.find(image);
    check(index && index->dimensions == 1 && index->padding == 0 && found != histogram_counts353.end());
    check(static_cast<std::size_t>(index->x) < found->second.size());
    return found->second[static_cast<std::size_t>(index->x)];
}
void setup_histogram_fake353() {
    shutdown_native();
    inject_fake();
    close_surrogate_documents();
    histogram_counts353.clear();
    histogram_fault353.clear();
    histogram_create_calls353 = histogram_calc_calls353 = histogram_set_calls353 = 0;
    histogram_intensity_origin353 = 2.5; histogram_intensity_scale353 = -3;
    histogram_intensity_unit353 = L"counts";
    fake.width = 4; fake.height = 4; fake.dimensions = 2; fake.code = 2; fake.packing = 1;
    fake.pixels.assign(16, 0.0f);
    for (std::size_t i = 0; i < 16; ++i) fake.pixels[i] = static_cast<float>(i);
    expected_summary = {0.0, 15.0, 120.0};
    histogram_api353 = HistogramApi353{histogram_create_fake353, histogram_intensity_fake353,
                                       histogram_value_fake353, histogram_calc_fake353};
}
std::uint32_t float_bits353(float value) {
    std::uint32_t bits = 0;
    std::memcpy(&bits, &value, sizeof(bits));
    return bits;
}
NativeRequest histogram_request353(std::optional<std::uint32_t> bins = std::nullopt,
                                   std::optional<std::uint32_t> minimum = std::nullopt,
                                   std::optional<std::uint32_t> maximum = std::nullopt) {
    return {"histogram-test", "HISTOGRAM", {17, bins.value_or(4), minimum.value_or(float_bits353(0.0f)),
                                            maximum.value_or(float_bits353(16.0f))}};
}
void expect_histogram_failure353(const char* message, NativeRequest request = histogram_request353()) {
    const auto created = histogram_create_calls353, calculated = histogram_calc_calls353;
    try { execute_native(request); check(false); }
    catch (const std::runtime_error& error) {
        if (std::string(error.what()) != message) std::cerr << "expected " << message << " got " << error.what() << '\n';
        check(std::string(error.what()) == message);
    }
    check(retained_results.empty() && retained_result_bytes == 0);
    check(histogram_create_calls353 == created && histogram_calc_calls353 == calculated);
    histogram_counts353.clear();
}
} // namespace

int main() {
    try {
        // Success path: native counts with an exact total and explicit bin geometry.
        setup_histogram_fake353();
        const auto result = execute_native(histogram_request353());
        check(nb::valid_json(result));
        check(histogram_create_calls353 == 1 && histogram_calc_calls353 == 1 && histogram_set_calls353 == 0);
        check(result.find("\"operation\":\"HISTOGRAM\"") != std::string::npos);
        check(result.find("\"bins\":4") != std::string::npos && result.find("\"counts_sum\":16") != std::string::npos);
        check(result.find("\"counts_complete\":true") != std::string::npos);
        check(result.find("\"axis_mode\":\"bin_index\"") != std::string::npos);
        check(result.find("\"axis_calibration_is_bin_left_edge\":false") != std::string::npos);
        check(result.find("\"shape\":[4]") != std::string::npos && result.find("\"dtype\":\"uint32\"") != std::string::npos);
        check(result.find("\"raw_bytes\":32") != std::string::npos && result.find("\"output_bytes\":16") != std::string::npos);
        check(result.find("\"retention\":{") != std::string::npos);
        check(result.find("\"intensity_calibration_applied\":false") != std::string::npos);
        const auto counts = retained_results.begin()->second;
        check(counts.bytes == 16 && counts.operation == "HISTOGRAM" && counts.data_type_code == 11);
        const auto output_id = retained_results.begin()->first;
        const auto output_image = registry.at(output_id);
        check(output_image->unit[0].empty() && output_image->scale[0] == 1.0f && output_image->origin[0] == 0.0f);
        // A rank-one counter image is delivered through its own group and keeps
        // its true [bins] shape instead of a fabricated 2D raster.
        const auto shown = execute_native({"show-histogram", "SHOW", {output_id}});
        check(nb::valid_json(shown) && document_calls == 1);
        check(shown.find("\"rank\":1") != std::string::npos);
        check(shown.find("\"retained_operation\":\"PROFILE\"") == std::string::npos);
        close_surrogate_documents();
        histogram_counts353.clear();

        // The axis never becomes an intensity axis in v1, with or without a
        // complete source intensity calibration.
        setup_histogram_fake353();
        histogram_intensity_unit353 = L"";
        check(execute_native(histogram_request353()).find("\"axis_mode\":\"bin_index\"") != std::string::npos);
        check(histogram_set_calls353 == 0);
        histogram_counts353.clear();

        // Rejections that must not create or fill any native image.
        for (const auto& item : std::vector<std::pair<NativeRequest, const char*>>{
                 {histogram_request353(1), "native_histogram_bin_budget"},
                 {histogram_request353(4097), "native_histogram_bin_budget"},
                 {histogram_request353(std::nullopt, float_bits353(1.0f)), "native_histogram_range_does_not_cover_source"},
                 {histogram_request353(std::nullopt, std::nullopt, float_bits353(14.0f)), "native_histogram_range_does_not_cover_source"},
                 {histogram_request353(std::nullopt, float_bits353(std::numeric_limits<float>::infinity())),
                  "native_histogram_requires_finite_increasing_range"},
                 {histogram_request353(std::nullopt, float_bits353(8.0f), float_bits353(4.0f)),
                  "native_histogram_requires_finite_increasing_range"},
                 {{"histogram-test", "HISTOGRAM", {17, 4, float_bits353(0.0f)}}, "native_histogram_requires_id_bins_and_float32_range"}}) {
            setup_histogram_fake353();
            expect_histogram_failure353(item.second, item.first);
        }
        setup_histogram_fake353();
        fake.code = 11;
        expect_histogram_failure353("native_histogram_requires_bounded_ordinary_float32_2d");
        setup_histogram_fake353();
        fake.packing = 2;
        expect_histogram_failure353("native_histogram_requires_bounded_ordinary_float32_2d");
        setup_histogram_fake353();
        fake.dimensions = 3;
        expect_histogram_failure353("native_histogram_requires_bounded_ordinary_float32_2d");

        // Vendor-output and count-integrity guards.
        for (const auto& fault : {"create_null", "output_rank", "output_dtype", "output_packing", "output_bins"}) {
            setup_histogram_fake353();
            histogram_fault353 = fault;
            const auto expected = std::string(fault) == "create_null" ? "native_histogram_missing_output"
                                                                      : "native_histogram_output_descriptor_mismatch";
            const auto created = histogram_create_calls353;
            try { execute_native(histogram_request353()); check(false); }
            catch (const std::runtime_error& error) { check(std::string(error.what()) == expected); }
            check(histogram_create_calls353 == created + 1 && retained_results.empty());
            histogram_counts353.clear();
        }
        for (const auto& fault : {"incomplete", "fractional", "negative", "nonfinite", "oversized"}) {
            setup_histogram_fake353();
            histogram_fault353 = fault;
            const auto expected = std::string(fault) == "incomplete" ? "native_histogram_counts_incomplete"
                                                                     : "native_histogram_count_not_exact";
            try { execute_native(histogram_request353()); check(false); }
            catch (const std::runtime_error& error) { check(std::string(error.what()) == expected); }
            check(retained_results.empty() && retained_result_bytes == 0);
            histogram_counts353.clear();
        }
        check(histogram_set_calls353 == 0);
        // A retained Fourier result has no raw-intensity meaning for binning.
        setup_histogram_fake353();
        {
            RetainedResult tracked{};
            tracked.value.image = &fake;
            InterlockedIncrement64(&fake.references);
            tracked.scientific_result = "{}";
            retained_results.emplace(17, std::move(tracked));
            try { execute_native(histogram_request353()); check(false); }
            catch (const std::runtime_error& error) { check(std::string(error.what()) == "native_histogram_scientific_source_context_unsupported"); }
            check(histogram_create_calls353 == 0 && fake.references == 2);
            shutdown_native();
        }
        shutdown_native();
        std::cout << assertions << " histogram adapter assertions passed (offline callbacks only)\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
