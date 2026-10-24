// Synthetic only: never imports or loads a vendor module.
#define main legacy_adapter_tests_main
#include "adapter_tests.cpp"
#undef main

namespace {
int uint32_reductions = 0;
std::string uint32_fault;
double uint32_point(const void* pointer, const nb::NativeDataIndex2D353* index) {
    ++point_calls;
    const auto* image = static_cast<const FakeImage*>(pointer);
    check(index->dimensions == 2 && !index->padding && index->x >= 0 && index->y >= 0);
    check(static_cast<std::uint64_t>(index->x) < image->width && static_cast<std::uint64_t>(index->y) < image->height);
    if (uint32_fault == "point_negative") return -1;
    if (uint32_fault == "point_fraction") return 1.5;
    if (uint32_fault == "point_overflow") return 4294967296.0;
    if (uint32_fault == "point_throw") throw std::runtime_error("surrogate uint32 point exception");
    return image->uint32_pixels.at(static_cast<std::size_t>(index->y)*image->width+index->x);
}
double uint32_minimum(const NativeRef* ref) {
    ++uint32_reductions;
    if (uint32_fault == "minimum_fraction") return 0.5;
    const auto& pixels = static_cast<const FakeImage*>(ref->image)->uint32_pixels;
    return *std::min_element(pixels.begin(), pixels.end());
}
double uint32_maximum(const NativeRef* ref) {
    ++uint32_reductions;
    if (uint32_fault == "maximum_overflow") return 4294967296.0;
    const auto& pixels = static_cast<const FakeImage*>(ref->image)->uint32_pixels;
    return *std::max_element(pixels.begin(), pixels.end());
}
double uint32_sum(const NativeRef* ref) {
    ++uint32_reductions;
    if (uint32_fault == "sum_fraction") return 0.5;
    std::uint64_t total = 0;
    for (const auto value : static_cast<const FakeImage*>(ref->image)->uint32_pixels) total += value;
    return static_cast<double>(total);
}
double uint32_mean(const NativeRef* ref) {
    ++uint32_reductions;
    if (uint32_fault == "mean_negative") return -1;
    if (uint32_fault == "mean_throw") throw std::runtime_error("surrogate uint32 mean exception");
    const auto& pixels = static_cast<const FakeImage*>(ref->image)->uint32_pixels;
    std::uint64_t total = 0;
    for (const auto value : pixels) total += value;
    return static_cast<double>(total)/pixels.size();
}
NativeRef* uint32_crop(const void* pointer, NativeRef* out, const nb::NativeDataSlice353* slice) {
    ++crop_calls;
    const auto* source = static_cast<const FakeImage*>(pointer);
    auto result = std::make_unique<FakeImage>();
    result->generated = true; result->id = next_image_id++; result->code = source->code;
    result->width = static_cast<std::uint32_t>(slice->output_axes[0].length);
    result->height = static_cast<std::uint32_t>(slice->output_axes[1].length);
    for (unsigned axis = 0; axis < 2; ++axis) {
        result->origin[axis] = source->origin[axis]-static_cast<float>(slice->source_start[axis]);
        result->scale[axis] = source->scale[axis]; result->unit[axis] = source->unit[axis];
    }
    for (std::uint32_t y = 0; y < result->height; ++y)
        for (std::uint32_t x = 0; x < result->width; ++x)
            result->uint32_pixels.push_back(source->uint32_pixels.at(
                (y+slice->source_start[1])*source->width+x+slice->source_start[0]));
    if (uint32_fault == "crop_float_conversion") result->code = 2;
    if (uint32_fault == "crop_packing") result->packing = 2;
    registry.emplace(result->id, result.get()); last_output_id = result->id; out->image = result.release();
    if (uint32_fault == "crop_owned_throw") throw std::runtime_error("surrogate uint32 crop exception");
    return out;
}
void reject_uint32(const NativeRequest& request, const char* expected) {
    const auto retained = retained_results.size();
    const auto bytes = retained_result_bytes;
    std::string actual;
    try { (void)execute_native(request); } catch (const std::runtime_error& error) { actual = error.what(); }
    if (actual != expected) throw std::runtime_error(std::string("uint32 expected ")+expected+", received "+actual);
    check(retained_results.size() == retained && retained_result_bytes == bytes && fake.references == 1);
}
void contract_checks() {
    check(nb::kUint32StatisticsPixels353 == 2097152);
    check(nb::kUint32StatisticsPixels353*UINT32_MAX == 9007199252643840ULL);
    for (const auto value : {0u, 1u, 16777215u, 16777216u, 16777217u, 2147483647u, 2147483648u, 2147483649u, 4294967294u, UINT32_MAX}) {
        std::string bytes;
        nb::append_read_uint32_le353(bytes, static_cast<double>(value));
        check(bytes.size() == 4);
        for (unsigned offset = 0; offset < 4; ++offset)
            check(static_cast<unsigned char>(bytes[offset]) == ((value >> (8*offset)) & 255u));
    }
    for (const double value : {-1.0, -0.0, 0.5, 4294967296.0,
                              std::numeric_limits<double>::infinity(), std::numeric_limits<double>::quiet_NaN()}) {
        std::string bytes = "unchanged"; bool rejected = false;
        try { nb::append_read_uint32_le353(bytes, value); } catch (const std::runtime_error&) { rejected = true; }
        check(rejected && bytes == "unchanged");
    }
    nb::validate_uint32_summary353(UINT32_MAX, UINT32_MAX, 9007199252643840.0, UINT32_MAX, 2097152);
    check(true);
}
void adapter_checks() {
    inject_fake();
    fake.code = 11; fake.width = fake.height = 4;
    fake.uint32_pixels = {0,1,16777215,16777216,16777217,2147483647,2147483648u,2147483649u,
                         4294967294u,UINT32_MAX,3,5,7,11,13,17};
    const auto original = fake.uint32_pixels;
    api.real_value = uint32_point; api.crop = uint32_crop;
    api.mean = uint32_mean; api.minimum = uint32_minimum; api.maximum = uint32_maximum; api.sum = uint32_sum;
    const auto info = metadata(&fake, false);
    check(info.find("\"dtype\":\"uint32\"") != std::string::npos &&
          info.find("\"is_integer\":true,\"is_unsigned\":true") != std::string::npos);
    for (const auto* group : {"native_uint32_mean","native_uint32_statistics","native_uint32_crop","native_uint32_preview","native_uint32_read"})
        check(qualified_capability353(group));
    const auto status = execute_native({"status","STATUS",{}});
    check(status.find("prepared_uint32_execution_enabled") == std::string::npos);
    for (const auto* capability : {"mean_uint32_2d", "summary_uint32_2d", "crop_uint32_2d",
                                   "sampled_preview_uint32_2d", "bounded_read_uint32_2d"})
        check(status.find(nb::quote(capability)) != std::string::npos);
    check(info.find("\"native_mean_supported\":true") != std::string::npos);
    const auto mean = execute_native({"mean","MEAN",{17}});
    const auto summary = execute_native({"summary","SUMMARY",{17}});
    check(nb::valid_json(mean) && nb::valid_json(summary));
    check(mean.find("\"mean\":942669827.375") != std::string::npos);
    check(summary.find("\"minimum\":0,\"maximum\":4294967295,\"sum\":15082717238,\"mean\":942669827.375") != std::string::npos);
    const auto read = execute_native({"read","READ",{17,0,0,4,4}});
    std::string bytes;
    for (const auto value : original) nb::append_read_uint32_le353(bytes, value);
    check(read.find("\"dtype\":\"uint32\"") != std::string::npos &&
          read.find(nb::quote(nb::read_base64_353(bytes))) != std::string::npos);
    const auto preview = execute_native({"preview","PREVIEW",{17,4,4}});
    check(preview.find("\"sampled_maximum\":4294967295") != std::string::npos && nb::valid_json(preview));
    for (const auto& fault : {"point_negative","point_fraction","point_overflow"}) {
        uint32_fault = fault;
        reject_uint32({"badread","READ",{17,0,0,1,1}}, "native_read_value_not_exact_uint32");
        reject_uint32({"badpreview","PREVIEW",{17,1,1}}, "native_preview_value_not_exact_uint32");
    }
    uint32_fault = "point_throw";
    reject_uint32({"badread","READ",{17,0,0,1,1}}, "surrogate uint32 point exception");
    for (const auto& item : std::vector<std::pair<std::string,const char*>>{
        {"minimum_fraction","native_uint32_summary_invalid_integer_result"},
        {"maximum_overflow","native_uint32_summary_invalid_integer_result"},
        {"sum_fraction","native_uint32_summary_invalid_integer_sum"},
        {"mean_negative","native_uint32_mean_out_of_range"},
        {"mean_throw","surrogate uint32 mean exception"}}) {
        uint32_fault = item.first;
        const int before = uint32_reductions;
        reject_uint32({"badsummary","SUMMARY",{17}}, item.second);
        const int expected = item.first == "minimum_fraction" ? 1 : item.first == "maximum_overflow" ? 2 : item.first == "sum_fraction" ? 3 : 4;
        check(uint32_reductions == before+expected);
    }
    uint32_fault.clear();
    fake.width = 2097153; fake.height = 1;
    const auto before_reductions = uint32_reductions;
    check(metadata(&fake,false).find("\"native_mean_supported\":false") != std::string::npos);
    reject_uint32({"large","MEAN",{17}}, "native_uint32_statistics_exact_sum_budget_exceeded");
    reject_uint32({"large","SUMMARY",{17}}, "native_uint32_statistics_exact_sum_budget_exceeded");
    check(uint32_reductions == before_reductions);
    fake.width = 2048; fake.height = 1024;
    check(metadata(&fake,false).find("\"native_summary_supported\":true") != std::string::npos);
    fake.width = fake.height = 4;
    fake.packing = 2;
    reject_uint32({"packed","MEAN",{17}}, "native_uint32_requires_ordinary_packing");
    fake.packing = 1;
    for (const auto& fault : {"crop_float_conversion","crop_packing","crop_owned_throw"}) {
        uint32_fault = fault;
        const auto before_destroy = destructions;
        reject_uint32({"cropfail","CROP",{17,1,1,4,3}}, fault == std::string("crop_owned_throw") ?
            "surrogate uint32 crop exception" : "native_crop_output_descriptor_mismatch");
        check(destructions == before_destroy+1 && registry.size() == 1);
    }
    uint32_fault.clear();
    const auto before_crop_limit = crop_calls;
    fake.width = 4194305; fake.height = 1;
    reject_uint32({"source_large","CROP",{17,0,0,1,1}}, "native_uint32_crop_source_over_budget");
    check(crop_calls == before_crop_limit && registry.size() == 1);
    fake.width = 4194304;
    const auto boundary = execute_native({"source_boundary","CROP",{17,0,0,1,1}});
    check(nb::valid_json(boundary) && crop_calls == before_crop_limit+1 && retained_results.size() == 1);
    check(registry.at(last_output_id)->uint32_pixels == std::vector<std::uint32_t>{0});
    fake.width = fake.height = 4;
    const auto crop = execute_native({"u32crop","CROP",{17,1,1,4,3}});
    const auto id = last_output_id;
    check(nb::valid_json(crop) && retained_results.count(id) && retained_results.at(id).data_type_code == 11);
    const auto* cropped = registry.at(id);
    check(cropped->uint32_pixels == (std::vector<std::uint32_t>{2147483647u,2147483648u,2147483649u,UINT32_MAX,3,5}));
    check(fake.uint32_pixels == original && cropped->code == 11 && cropped->uint32_pixels.data() != fake.uint32_pixels.data());
    check(retained_result_bytes == 28 && retained_results.size() == 2 && cropped->references == 1);
    // The separate uint32_operations_tests exercises the qualified document
    // handoff. This suite keeps all its crops unshown for the STOP release check.
    check(!document_calls && !show_calls);
    // Production uses this exact pure admission guard. A copied unqualified
    // profile decision rejects without introducing an override in real code.
    const auto before_rejection_reductions = uint32_reductions;
    const auto before_rejection_crop = crop_calls, before_rejection_points = point_calls;
    for (const auto* group : {"native_uint32_mean","native_uint32_statistics","native_uint32_crop","native_uint32_preview","native_uint32_read"}) {
        for (const bool bindings : {true,false}) {
            std::string actual;
            try { nb::require_uint32_admission353(false,bindings,group); }
            catch (const std::runtime_error& error) { actual = error.what(); }
            check(actual == std::string("native_uint32_not_qualified:")+group);
        }
    }
    api.packing = nullptr;
    reject_uint32({"missing","MEAN",{17}}, "native_uint32_symbol_unavailable:native_uint32_mean");
    reject_uint32({"missing","SUMMARY",{17}}, "native_uint32_symbol_unavailable:native_uint32_statistics");
    reject_uint32({"missing","CROP",{17,0,0,2,2}}, "native_uint32_symbol_unavailable:native_uint32_crop");
    reject_uint32({"missing","PREVIEW",{17,4,4}}, "native_preview_symbol_unavailable");
    reject_uint32({"missing","READ",{17,0,0,2,2}}, "native_read_packing_unavailable");
    api.packing = packing_fake;
    api.mean = nullptr;
    reject_uint32({"missing","MEAN",{17}}, "native_mean_not_available");
    reject_uint32({"missing","SUMMARY",{17}}, "native_summary_not_available");
    api.mean = uint32_mean;
    api.minimum = nullptr;
    reject_uint32({"missing","SUMMARY",{17}}, "native_summary_not_available");
    api.minimum = uint32_minimum;
    api.crop = nullptr;
    reject_uint32({"missing","CROP",{17,0,0,2,2}}, "native_uint32_symbol_unavailable:native_uint32_crop");
    api.crop = uint32_crop;
    api.real_value = nullptr;
    reject_uint32({"missing","PREVIEW",{17,4,4}}, "native_preview_symbol_unavailable");
    reject_uint32({"missing","READ",{17,0,0,2,2}}, "native_read_symbol_unavailable");
    api.real_value = uint32_point;
    check(uint32_reductions == before_rejection_reductions && crop_calls == before_rejection_crop &&
          point_calls == before_rejection_points);
    for (const auto code : {1u,6u,7u,9u,10u,12u}) {
        fake.code = code;
        const auto before_calls = point_calls;
        reject_uint32({"signed","READ",{17,0,0,1,1}}, "native_read_requires_float32_2d_ordinary_packing");
        reject_uint32({"other","PREVIEW",{17,1,1}}, "native_preview_requires_float32_2d_ordinary_packing");
        check(point_calls == before_calls);
    }
    fake.code = 9; // Signed/other integer storage must not inherit uint32 admission.
    reject_uint32({"unary","UNARY",{17,1}}, "native_arithmetic_requires_float32_2d");
    reject_uint32({"binary","BINARY",{17,17,1}}, "native_arithmetic_requires_float32_2d");
    reject_uint32({"fft","FFT",{17}}, "native_fft_input_type_or_dimensions_unsupported");
    reject_uint32({"filter","FILTER",{17,1}}, "native_filter_requires_float32_2d_ordinary_packing");
    check(!operation_calls && fake.uint32_pixels == original);
    fake.code = 11;
    shutdown_native();
    check(retained_results.empty() && !retained_result_bytes && registry.size() == 1 && fake.references == 1);
}
}
int main() {
    try {
        contract_checks(); adapter_checks();
        std::cout << "PASS uint32 production surrogate " << assertions << " assertions; no vendor loaded; rejection processing callbacks unchanged\n";
        return 0;
    } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
