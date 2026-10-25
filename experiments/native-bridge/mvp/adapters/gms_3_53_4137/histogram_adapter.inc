// DM-native intensity histogram. The bridge creates the destination through the
// exported Image::CreateImage(DataSize, type, char_range) and fills it with the
// exported GMSImageProcessing::CalcHistogram(ref_ptr, ref_ptr, double, double).
// No bridge binning kernel and no NumPy fallback exist on this path.
struct HistogramApi353 {
    NativeRef* (*create_image)(NativeRef*, const nb::NativeDataSize353*, std::uint32_t,
                              const nb::NativeCharRange353*) = nullptr;
    // Disassembly of the pinned build: XMM2 carries the "origin" expressed in the
    // requested format and XMM3 the scale; the trailing int32 is the format. For
    // format 0 the vendor divides by the scale and stores the index origin, so a
    // later physical read re-multiplies and can differ from the requested value.
    void (*set_dimension_calibration)(void*, std::uint32_t, float, float,
                                      const nb::NativeCharRange353*, std::int32_t) = nullptr;
    void (*intensity_calibration)(void*, float*, float*, void*) = nullptr;
    double (*real_value)(const void*, const nb::NativeDataIndex1D353*) = nullptr;
    void (*calc_histogram)(const NativeRef*, const NativeRef*, double, double) = nullptr;
    bool ready() const {
        return create_image && intensity_calibration && real_value && calc_histogram;
    }
} histogram_api353;
struct HistogramAxisPlan353 {
    float scale = 0, quotient = 0, zero = 0;
    double bound = 0, maximum_error = 0;
};
double histogram_ulp353(float value) {
    const auto up = std::nextafter(value, std::numeric_limits<float>::infinity());
    const auto down = std::nextafter(value, -std::numeric_limits<float>::infinity());
    if (!std::isfinite(up) || !std::isfinite(down)) return std::numeric_limits<double>::infinity();
    return std::max(static_cast<double>(up) - value, static_cast<double>(value) - down);
}
bool histogram_axis_plan353(float lower, double width, std::uint32_t bins, HistogramAxisPlan353& plan) {
    plan.scale = static_cast<float>(width);
    if (!std::isnormal(plan.scale) || plan.scale <= 0) return false;
    plan.quotient = lower / plan.scale;
    if (!std::isfinite(plan.quotient) || (lower != 0 && !std::isnormal(plan.quotient))) return false;
    plan.zero = plan.quotient * plan.scale;
    if (!std::isfinite(plan.zero) || (lower != 0 && !std::isnormal(plan.zero))) return false;
    // One local binary32 ULP per native operation is conservative even at
    // exponent transitions. There is no unit-sized absolute tolerance floor.
    plan.bound = histogram_ulp353(plan.quotient) * plan.scale + histogram_ulp353(plan.zero);
    plan.maximum_error = plan.bound + std::fabs(static_cast<double>(plan.scale) - width) * (bins - 1);
    return std::isfinite(plan.bound) && std::isfinite(plan.maximum_error) && plan.maximum_error < width / 4;
}
std::string histogram_number353(double value) { auto out = json_stream(); out << value; return out.str(); }
// Bounded local UTF-16 conversion for the vendor unit range; no vendor
// allocation is created or freed here.
bool histogram_wide353(const std::string& utf8, std::wstring& out) {
    if (utf8.empty() || utf8.size() > 256) return false;
    const int needed = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, utf8.data(),
                                           static_cast<int>(utf8.size()), nullptr, 0);
    if (needed <= 0 || needed > 128) return false;
    out.assign(static_cast<std::size_t>(needed), L'\0');
    return MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, utf8.data(), static_cast<int>(utf8.size()),
                               &out[0], needed) == needed;
}
void initialize_histogram353(HMODULE image, HMODULE processing) noexcept {
    try {
        HistogramApi353 next;
        next.create_image = symbol<decltype(next.create_image)>(image,
            "?CreateImage@Image@GMS@@SA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBVDataSize@Imaging@4@KAEBV?$char_range_t@_WU?$char_traits@_W@std@@@4@@Z");
        try { next.set_dimension_calibration = symbol<decltype(next.set_dimension_calibration)>(image,
            "?SetDimensionCalibration@Image@GMS@@QEAAXKMMAEBV?$char_range_t@_WU?$char_traits@_W@std@@@Gatan@@J@Z"); }
        catch (...) { next.set_dimension_calibration = nullptr; }
        next.intensity_calibration = symbol<decltype(next.intensity_calibration)>(image,
            "?GetIntensityCalibration@Image@GMS@@QEAAXAEAM0AEAV?$basic_string@_WU?$char_traits@_W@std@@V?$allocator@_W@2@@std@@@Z");
        next.real_value = symbol<decltype(next.real_value)>(image,
            "?GetRealValue@Image@GMS@@QEBANAEBVDataIndex@Imaging@Gatan@@@Z");
        next.calc_histogram = symbol<decltype(next.calc_histogram)>(processing,
            "?CalcHistogram@GMSImageProcessing@@YAXAEBV?$ref_ptr@VImage@GMS@@@Gatan@@0NN@Z");
        histogram_api353 = next;
    } catch (...) { histogram_api353 = HistogramApi353{}; }
}
float histogram_float353(std::uint32_t bits) noexcept {
    float value = 0;
    std::memcpy(&value, &bits, sizeof(value));
    return value;
}
void validate_histogram_owned353(void* value) {
    if (!value || !accessible_memory(value, sizeof(std::int64_t)) || !reference_counter(value, 0) ||
        InterlockedCompareExchange64(reference_counter(value, 0), 0, 0) <= 0) {
        fatal_abi = true;
        throw std::runtime_error("native_histogram_invalid_owned_reference");
    }
}
void validate_histogram_descriptor353(void* image, std::uint32_t output_id, std::uint32_t bins) {
    if (api.id(image) != output_id || api.ndim(image) != 1 || api.dtype(image) != nb::kHistogramUint32Code353 ||
        packing_style(image) != 1 || api.dimension(image, 0) != bins)
        throw std::runtime_error("native_histogram_output_descriptor_mismatch");
}
std::string execute_histogram353(const NativeRequest& request) {
    require_ready();
    if (request.args.size() != 4) throw std::runtime_error("native_histogram_requires_id_bins_and_float32_range");
    if (!histogram_api353.ready() || !api.minimum || !api.maximum)
        throw std::runtime_error("native_histogram_bindings_unavailable");
    const auto source_id = request.args[0];
    const auto bins = request.args[1];
    if (bins < nb::kHistogramBinsMin353 || bins > nb::kHistogramBinsMax353)
        throw std::runtime_error("native_histogram_bin_budget");
    const auto range_min = histogram_float353(request.args[2]), range_max = histogram_float353(request.args[3]);
    if (!std::isfinite(range_min) || !std::isfinite(range_max) || !(range_min < range_max))
        throw std::runtime_error("native_histogram_requires_finite_increasing_range");
    ImageRef source(api.find_id, source_id);
    const auto before = fft_image353(source.value.image);
    if (before.id != source_id) throw std::runtime_error("image_identity_mismatch");
    // Fourier or otherwise unresolved retained results have no raw-intensity
    // meaning here, so they are refused instead of silently labelled as counts.
    const auto lineage = retained_results.find(before.id);
    if (lineage != retained_results.end() &&
        (lineage->second.scientific_unresolved || lineage->second.scientific_result != "null"))
        throw std::runtime_error("native_histogram_scientific_source_context_unsupported");
    if (before.dimensions != 2 || before.data_type != 2 || before.packing != 1 ||
        !before.width || !before.height || static_cast<std::uint64_t>(before.width) * before.height > 4194304)
        throw std::runtime_error("native_histogram_requires_bounded_ordinary_float32_2d");
    const auto pixels = static_cast<std::uint64_t>(before.width) * before.height;
    // Native reductions establish the actual source range. Requiring the caller
    // range to cover it avoids inventing an under/overflow rule that DM never
    // documented for this call.
    const auto source_min = api.minimum(&source.value);
    require_ready();
    const auto source_max = api.maximum(&source.value);
    require_ready();
    if (!std::isfinite(source_min) || !std::isfinite(source_max) || source_min > source_max)
        throw std::runtime_error("native_histogram_source_range_invalid");
    if (static_cast<double>(range_min) > source_min || static_cast<double>(range_max) < source_max)
        throw std::runtime_error("native_histogram_range_does_not_cover_source");
    const std::uint64_t bytes = static_cast<std::uint64_t>(bins) * sizeof(std::uint32_t);
    if (retained_results.size() >= nb::kCropRetainedCount || retained_result_bytes > nb::kCropRetainedBytes ||
        bytes > nb::kCropRetainedBytes - retained_result_bytes)
        throw std::runtime_error("native_result_retention_capacity");
    const auto source_info = metadata(source.value.image);
    float intensity_origin = 0, intensity_scale = 0;
    std::string intensity_unit;
    {
        VendorString unit;
        histogram_api353.intensity_calibration(source.value.image, &intensity_origin, &intensity_scale, &unit.value);
        require_ready();
        intensity_unit = unit.utf8(256);
    }
    const auto width_value = (static_cast<double>(range_max) - range_min) / bins;
    if (!std::isfinite(width_value) || width_value <= 0)
        throw std::runtime_error("native_histogram_bin_width_invalid");
    require_ready();
    nb::NativeDataSize353 size;
    size.dimensions = 1;
    size.size[0] = bins;
    const wchar_t name[] = L"MCP native histogram";
    nb::NativeCharRange353 name_range{name, name + (sizeof(name) / sizeof(wchar_t)) - 1};
    ImageRef output;
    // Static members returning ref_ptr<Image> receive the hidden result pointer
    // first and hand back that same pointer; the image reference is read from the
    // destination, never from the return value.
    NativeRef* returned = histogram_api353.create_image(&output.value, &size, nb::kHistogramUint32Code353, &name_range);
    if (returned != &output.value || !output.value.image)
        throw std::runtime_error("native_histogram_missing_output");
    try { validate_histogram_owned353(output.value.image); }
    catch (...) { output.relinquish(); throw; }
    const auto output_id = api.id(output.value.image);
    if (!output_id || output.value.image == source.value.image || output_id == before.id || retained_results.count(output_id))
        throw std::runtime_error("native_histogram_output_identity_invalid");
    validate_histogram_descriptor353(output.value.image, output_id, bins);
    require_ready();
    histogram_api353.calc_histogram(&source.value, &output.value, static_cast<double>(range_min),
                                    static_cast<double>(range_max));
    require_ready();
    // A vendor call must not turn the typed rank-one read into a different
    // object or a shorter/incompatible descriptor before the first sample.
    validate_histogram_descriptor353(output.value.image, output_id, bins);
    // Counts are read as native doubles: every uint32 count is exact in binary64.
    // The complete-source-range admission makes the total exact, so a vendor
    // edge-rule surprise fails closed instead of being reported as a histogram.
    std::uint64_t total = 0, count_bytes = 0;
    std::string raw;
    raw.reserve(static_cast<std::size_t>(bytes));
    for (std::uint32_t i = 0; i < bins; ++i) {
        const nb::NativeDataIndex1D353 index{1, 0, static_cast<std::int64_t>(i)};
        const auto count = histogram_api353.real_value(output.value.image, &index);
        require_ready();
        if (!std::isfinite(count) || count < 0 || std::trunc(count) != count ||
            count > static_cast<double>(pixels))
            throw std::runtime_error("native_histogram_count_not_exact");
        total += static_cast<std::uint64_t>(count);
        if (total > pixels) throw std::runtime_error("native_histogram_counts_over_source");
        nb::append_profile_float64_le353(raw, count);
        count_bytes += 8;
    }
    if (total != pixels) throw std::runtime_error("native_histogram_counts_incomplete");
    if (count_bytes != static_cast<std::uint64_t>(bins) * 8) throw std::runtime_error("native_histogram_count_bytes_invalid");
    // Source metadata must still match the original snapshot. This is change
    // detection only; an independent host oracle is needed for source pixels.
    validate_histogram_descriptor353(output.value.image, output_id, bins);
    {
        float after_origin = 0, after_scale = 0;
        VendorString unit;
        histogram_api353.intensity_calibration(source.value.image, &after_origin, &after_scale, &unit.value);
        require_ready();
        if (after_origin != intensity_origin || after_scale != intensity_scale || unit.utf8(256) != intensity_unit ||
            metadata(source.value.image) != source_info)
            throw std::runtime_error("native_histogram_source_metadata_changed");
    }
    std::string axis_mode = "bin_index";
    const char* axis_reason = nullptr;
    HistogramAxisPlan353 axis_plan;
    float axis_zero_observed = 0, axis_scale_observed = 0;
    double axis_roundtrip = 0;
    if (intensity_origin != 0 || intensity_scale != 1) axis_reason = "source_intensity_calibration_not_identity";
    else if (intensity_unit.empty()) axis_reason = "source_intensity_units_unavailable";
    else if (!qualified_capability353("native_histogram_axis") || !histogram_api353.set_dimension_calibration)
        axis_reason = "axis_entrypoint_unavailable";
    else if (!histogram_axis_plan353(range_min, width_value, bins, axis_plan))
        axis_reason = "binary32_axis_not_resolved";
    if (!axis_reason) {
        std::wstring wide_unit;
        if (!histogram_wide353(intensity_unit, wide_unit))
            throw std::runtime_error("native_histogram_axis_unit_not_convertible");
        nb::NativeCharRange353 unit_range{wide_unit.c_str(), wide_unit.c_str() + wide_unit.size()};
        histogram_api353.set_dimension_calibration(output.value.image, 0, range_min, axis_plan.scale, &unit_range, 0);
        require_ready();
        const auto read_back = crop_axis_calibration(output.value.image, 0);
        axis_zero_observed = read_back.zero;
        axis_scale_observed = read_back.scale;
        if (!std::isfinite(read_back.zero)) throw std::runtime_error("native_histogram_axis_origin_not_finite");
        axis_roundtrip = std::fabs(static_cast<double>(read_back.zero) - range_min);
        if (read_back.origin != -axis_plan.quotient || read_back.zero != axis_plan.zero || axis_roundtrip > axis_plan.bound)
            throw std::runtime_error("native_histogram_axis_origin_mismatch");
        if (read_back.scale != axis_plan.scale)
            throw std::runtime_error("native_histogram_axis_scale_mismatch");
        if (read_back.unit != intensity_unit)
            throw std::runtime_error("native_histogram_axis_unit_mismatch");
        axis_mode = "source_intensity_units";
    }
    validate_histogram_descriptor353(output.value.image, output_id, bins);
    {
        float after_origin = 0, after_scale = 0; VendorString unit;
        histogram_api353.intensity_calibration(source.value.image, &after_origin, &after_scale, &unit.value);
        require_ready();
        if (after_origin != intensity_origin || after_scale != intensity_scale || unit.utf8(256) != intensity_unit ||
            metadata(source.value.image) != source_info)
            throw std::runtime_error("native_histogram_source_metadata_changed");
    }
    const auto output_info = metadata(output.value.image, false, "one-dimensional native histogram bins");
    std::string frozen_axis_unit;
    const auto frozen_axis = histogram_axis_values353(output.value.image, frozen_axis_unit);
    auto intensity_json = json_stream();
    intensity_json << "{\"origin\":" << intensity_origin << ",\"scale\":" << intensity_scale
        << ",\"unit\":" << (intensity_unit.empty() ? "null" : nb::quote(intensity_unit)) << '}';
    auto axis_fields = json_stream();
    axis_fields << "\"axis_mode\":" << nb::quote(axis_mode)
        << ",\"axis_calibration_is_bin_left_edge\":" << (axis_reason ? "false" : "true")
        << ",\"axis_zero_requested\":" << (axis_reason ? "null" : histogram_number353(range_min))
        << ",\"axis_zero_observed\":" << (axis_reason ? "null" : histogram_number353(axis_zero_observed))
        << ",\"axis_scale_observed\":" << (axis_reason ? "null" : histogram_number353(axis_scale_observed))
        << ",\"axis_roundtrip_error\":" << (axis_reason ? "null" : histogram_number353(axis_roundtrip))
        << ",\"axis_roundtrip_bound\":" << (axis_reason ? "null" : histogram_number353(axis_plan.bound))
        << ",\"axis_max_coordinate_error\":" << (axis_reason ? "null" : histogram_number353(axis_plan.maximum_error))
        << ",\"axis_tolerance\":\"binary32_local_ulp_v1\",\"axis_unavailable_reason\":"
        << (axis_reason ? nb::quote(axis_reason) : "null");
    auto context = json_stream();
    context << '{' << axis_fields.str() << ",\"requested_range\":[" << range_min << ',' << range_max
        << "],\"bins\":" << bins << ",\"bin_width\":" << width_value << ",\"bin_left_edge\":" << range_min
        << ",\"source_intensity_calibration\":" << intensity_json.str() << '}';
    auto frozen_context = context.str();
    auto out = json_stream();
    out << "{\"backend\":\"digitalmicrograph-native\",\"operation\":\"HISTOGRAM\",\"source_image_id\":" << before.id
        << ",\"image_id\":" << output_id << ",\"source\":" << source_info
        << ",\"source_min\":" << source_min << ",\"source_max\":" << source_max
        << ",\"source_pixels\":" << pixels
        << ",\"requested_range\":[" << range_min << ',' << range_max << ']'
        << ",\"range_covers_source\":true,\"bins\":" << bins << ",\"bin_width\":" << width_value
        << ",\"binning\":\"uniform linear bins over the caller range; the range must cover the complete native source minimum/maximum\""
        << ",\"bin_edge_rule\":\"left edge at range_min, width = (max-min)/bins\""
        << ",\"counts_sum\":" << total << ",\"counts_complete\":true"
        << ",\"shape\":[" << bins << "],\"dtype\":\"uint32\",\"axes\":[\"intensity_bin\"]"
        << ",\"counts_encoding\":\"exact uint32 counts little-endian binary64 payload\""
        << ",\"values_base64\":" << nb::quote(nb::read_base64_353(raw))
        << ",\"raw_bytes\":" << count_bytes << ",\"output_bytes\":" << bytes
        << ",\"bin_left_edge\":" << range_min
        << ',' << axis_fields.str()
        << ",\"source_intensity_calibration\":" << intensity_json.str()
        << ",\"image\":" << output_info
        << ",\"operator\":\"GMSImageProcessing::CalcHistogram\",\"computation\":\"DM native\""
        << ",\"intensity_calibration_applied\":false,\"intensity_semantics\":\"raw pixel intensity counts per bin\""
        << ",\"source_write_requested\":false,\"snapshot_atomic\":false"
        << ",\"ownership\":\"plugin retained strong reference until normal native STOP/cleanup; shown document may retain image\"}";
    const auto result = out.str();
    if (result.size() > nb::kMaxReply - 2048 || !nb::valid_json(result))
        throw std::runtime_error("native_histogram_result_over_budget_or_invalid");
    retain_native_result(output, output_id, bytes, request, "GMSImageProcessing::CalcHistogram",
                         {before.id}, {source_info}, output_info,
                         "native intensity bin counts over a caller-explicit range; raw counts, no intensity calibration applied");
    auto& retained = retained_results.at(output_id);
    retained.histogram_axis_context = std::move(frozen_context);
    retained.histogram_axis_values = frozen_axis;
    retained.histogram_axis_unit = std::move(frozen_axis_unit);
    return result;
}
