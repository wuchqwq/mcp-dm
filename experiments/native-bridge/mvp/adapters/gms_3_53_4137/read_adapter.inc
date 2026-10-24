#ifndef NB_READ_ADAPTER_353_INCLUDED
#define NB_READ_ADAPTER_353_INCLUDED
// Include inside the pinned adapter namespace after fft_image353/metadata and
// the shared RetainedResult definitions. No native image or file is created.
std::string read_roi_calibration353(void* image, const nb::ReadPlan353& plan, bool& complete) {
    auto stream = json_stream();
    complete = true;
    stream << '[';
    for (std::uint32_t axis = 0; axis < 2; ++axis) {
        float zero = 0, scale = 0, origin = 0, raw_scale = 0;
        VendorString unit;
        require_ready();
        api.calibration(image, axis, &zero, &scale, &unit.value, 0);
        require_ready();
        api.calibration(image, axis, &origin, &raw_scale, nullptr, 1);
        require_ready();
        const auto units = unit.utf8(256);
        const double offset = static_cast<double>(plan.rect[axis]);
        const bool numbers = std::isfinite(zero) && std::isfinite(scale) && scale != 0 &&
                             std::isfinite(origin) && raw_scale == scale;
        const double roi_origin = static_cast<double>(origin)-offset;
        const double roi_zero = static_cast<double>(zero)+offset*static_cast<double>(scale);
        const bool valid_numbers = numbers && std::isfinite(roi_origin) && std::isfinite(roi_zero);
        const bool usable = valid_numbers && !units.empty();
        complete = complete && usable;
        if (axis) stream << ',';
        stream << "{\"dm_dimension\":" << axis << ",\"numpy_axis\":" << 1-axis
          << ",\"size\":" << (axis ? plan.height : plan.width) << ",\"source_offset\":" << plan.rect[axis]
          << ",\"source_origin\":";
        if (std::isfinite(origin)) stream << origin; else stream << "null";
        stream << ",\"source_calibrated_value_at_pixel_zero\":";
        if (std::isfinite(zero)) stream << zero; else stream << "null";
        stream << ",\"origin\":";
        if (valid_numbers) stream << roi_origin; else stream << "null";
        stream << ",\"calibrated_value_at_pixel_zero\":";
        if (valid_numbers) stream << roi_zero; else stream << "null";
        stream << ",\"scale\":";
        if (std::isfinite(scale)) stream << scale; else stream << "null";
        stream << ",\"unit\":" << (units.empty() ? "null" : nb::quote(units))
          << ",\"usable\":" << (usable ? "true" : "false")
          << ",\"issue\":" << (usable ? "null" : !valid_numbers ?
              (units.empty() ? "\"invalid_calibration_and_unknown_units\"" : "\"invalid_calibration\"") : "\"unknown_units\"")
          << '}';
    }
    stream << ']';
    require_ready();
    return stream.str();
}

std::string execute_read(const NativeRequest& request) {
    require_ready();
    if (request.args.size() != 5) throw std::runtime_error("native_read_requires_image_id_and_rect");
    if (!api.real_value) throw std::runtime_error("native_read_symbol_unavailable");
    if (!api.packing) throw std::runtime_error("native_read_packing_unavailable");
    ImageRef source(api.find_id, request.args[0]);
    const auto before = fft_image353(source.value.image);
    if (before.id != request.args[0]) throw std::runtime_error("image_identity_mismatch");
    const bool uint32 = before.data_type == nb::kUint32Code353;
    if (before.dimensions != 2 || (before.data_type != 2 && !uint32) || before.packing != 1)
        throw std::runtime_error("native_read_requires_float32_2d_ordinary_packing");
    if (uint32) require_uint32_operation353("native_uint32_read", api.packing && api.real_value);
    const auto plan = nb::read_plan353(before.width, before.height,
                       {request.args[1], request.args[2], request.args[3], request.args[4]});
    const auto source_info = metadata(source.value.image, false);
    bool calibration_complete = false;
    const auto calibration = read_roi_calibration353(source.value.image, plan, calibration_complete);
    std::string provenance = "null";
    const auto retained = retained_results.find(before.id);
    if (retained != retained_results.end()) {
        if (retained->second.value.image != source.value.image)
            throw std::runtime_error("native_read_source_provenance_identity_mismatch");
        const auto& original = retained->second;
        auto provenance_stream = json_stream();
        provenance_stream << "{\"operation\":" << nb::quote(original.operation)
          << ",\"request_id\":" << nb::quote(original.request_id) << ",\"source_image_ids\":[";
        for (std::size_t i = 0; i < original.source_ids.size(); ++i) {
            if (i) provenance_stream << ',';
            provenance_stream << original.source_ids[i];
        }
        provenance_stream << "],\"semantics\":" << nb::quote(original.semantics) << '}';
        provenance = provenance_stream.str();
    }
    std::string bytes;
    bytes.reserve(static_cast<std::size_t>(plan.bytes));
    for (std::uint32_t y = 0; y < plan.height; ++y) {
        for (std::uint32_t x = 0; x < plan.width; ++x) {
            const auto index = nb::read_index353(plan, x, y);
            const double value = api.real_value(source.value.image, &index);
            require_ready();
            if (uint32) nb::append_read_uint32_le353(bytes, value);
            else nb::append_read_float32_le353(bytes, value);
        }
    }
    if (bytes.size() != plan.bytes) throw std::runtime_error("native_read_snapshot_size_mismatch");
    const auto after = fft_image353(source.value.image);
    if (after.id != before.id || after.dimensions != before.dimensions || after.data_type != before.data_type ||
        after.packing != before.packing || after.width != before.width || after.height != before.height ||
        metadata(source.value.image, false) != source_info)
        throw std::runtime_error("native_read_source_metadata_changed");
    require_ready();
    const auto base64 = nb::read_base64_353(bytes);
    auto stream = json_stream();
    stream << "{\"backend\":\"digitalmicrograph-native\",\"operation\":\"READ\",\"source_image_id\":" << before.id
      << ",\"source\":" << source_info << ",\"requested_rect\":";
    write_rect(stream, plan.rect);
    stream << ",\"effective_rect\":";
    write_rect(stream, plan.rect);
    stream << ",\"shape\":[" << plan.height << ',' << plan.width
      << "],\"dtype\":" << (uint32 ? "\"uint32\"" : "\"float32\"")
      << ",\"byte_order\":\"little\",\"axes\":[\"y\",\"x\"],\"array_order\":\"C\""
      << ",\"data_encoding\":\"base64\",\"values_base64\":" << nb::quote(base64)
      << ",\"sample_count\":" << plan.samples << ",\"raw_bytes\":" << plan.bytes
      << ",\"roi_calibration\":" << calibration << ",\"calibration_complete\":" << (calibration_complete ? "true" : "false")
      << ",\"coordinate_mapping_policy\":\"logical ROI only; source_x=x0+roi_x; source_y=y0+roi_y; source unchanged\""
      << ",\"source_provenance\":" << provenance
      << ",\"source_provenance_scope\":\"immutable creation record only; source image remains mutable\""
      << ",\"operator\":\"GMS::Image::GetRealValue\",\"computation\":\"DM native point reads; data handoff only\""
      << ",\"intensity_calibration_applied\":false,\"intensity_semantics\":\"raw pixel intensity\""
      << ",\"ownership\":\"response-owned numeric snapshot; no native result image\""
      << ",\"source_write_requested\":false,\"snapshot_atomic\":false}";
    auto result = stream.str();
    if (result.size() > nb::kMaxReply-2048 || !nb::valid_json(result))
        throw std::runtime_error("native_read_result_over_budget_or_invalid");
    source.reset();
    require_ready();
    return result;
}
#endif
