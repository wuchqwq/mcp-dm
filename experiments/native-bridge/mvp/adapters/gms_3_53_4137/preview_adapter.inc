// Include inside dm_adapter.cpp's anonymous namespace after fft_adapter.inc.
// Source values are read by the exact native GetRealValue export. The only
// local pixel arithmetic is the user-authorized display scaling/hex encoding.
std::string execute_preview(const NativeRequest& request) {
    require_ready();
    if (request.args.size() != 3) throw std::runtime_error("native_preview_requires_image_id_and_max_dimensions");
    if (!request.args[1] || !request.args[2] || request.args[1] > nb::kPreviewDimension353 ||
        request.args[2] > nb::kPreviewDimension353)
        throw std::runtime_error("native_preview_dimensions_out_of_range");
    if (!api.real_value || !api.packing) throw std::runtime_error("native_preview_symbol_unavailable");
    ImageRef source(api.find_id, request.args[0]);
    const auto descriptor = fft_image353(source.value.image);
    if (descriptor.id != request.args[0]) throw std::runtime_error("image_identity_mismatch");
    const bool uint32 = descriptor.data_type == nb::kUint32Code353;
    if (descriptor.dimensions != 2 || (descriptor.data_type != 2 && !uint32) || descriptor.packing != 1)
        throw std::runtime_error("native_preview_requires_float32_2d_ordinary_packing");
    if (uint32) require_uint32_operation353("native_uint32_preview", api.packing && api.real_value);
    const auto plan = nb::preview_plan353(descriptor.width, descriptor.height, request.args[1], request.args[2]);
    const auto source_info = metadata(source.value.image, false);
    require_ready();
    std::vector<double> values;
    values.reserve(static_cast<std::size_t>(plan.samples));
    double minimum = 0, maximum = 0;
    for (std::uint32_t py = 0; py < plan.height; ++py) {
        for (std::uint32_t px = 0; px < plan.width; ++px) {
            const auto index = nb::preview_index353(plan, px, py);
            const double value = api.real_value(source.value.image, &index);
            require_ready();
            if (!std::isfinite(value)) throw std::runtime_error("native_preview_nonfinite_sample");
            if (uint32) nb::require_uint32_sample353(value, "native_preview_value_not_exact_uint32");
            if (values.empty() || value < minimum) minimum = value;
            if (values.empty() || value > maximum) maximum = value;
            values.push_back(value);
        }
    }
    static constexpr char hex[] = "0123456789abcdef";
    std::string gray8;
    gray8.reserve(static_cast<std::size_t>(plan.samples) * 2);
    const double span = maximum - minimum;
    for (const double value : values) {
        // Small finite float32 source values promoted by the native getter fit
        // this binary64 display range. A constant sampled range maps to black.
        double scaled = span > 0 ? (value - minimum) / span * 255.0 : 0.0;
        if (!std::isfinite(scaled)) throw std::runtime_error("native_preview_invalid_display_range");
        if (scaled < 0) scaled = 0;
        if (scaled > 255) scaled = 255;
        const auto byte = static_cast<unsigned>(scaled + 0.5);
        gray8.push_back(hex[byte >> 4]);
        gray8.push_back(hex[byte & 15]);
    }
    const auto after = fft_image353(source.value.image);
    if (after.id != descriptor.id || after.dimensions != descriptor.dimensions || after.data_type != descriptor.data_type ||
        after.packing != descriptor.packing || after.width != descriptor.width || after.height != descriptor.height ||
        metadata(source.value.image, false) != source_info)
        throw std::runtime_error("native_preview_source_metadata_changed");
    require_ready();
    auto stream = json_stream();
    stream << "{\"backend\":\"digitalmicrograph-native\",\"operation\":\"PREVIEW\",\"image_id\":" << descriptor.id
      << ",\"source\":" << source_info << ",\"width\":" << plan.width << ",\"height\":" << plan.height
      << ",\"gray8_hex\":" << nb::quote(gray8) << ",\"sample_count\":" << plan.samples
      << ",\"sampled_minimum\":" << minimum << ",\"sampled_maximum\":" << maximum
      << ",\"range_source\":\"sampled native point values\",\"constant_range_gray8\":0"
      << ",\"mapping\":\"x=floor(px*source_width/width);y=floor(py*source_height/height)\""
      << ",\"orientation\":\"row-major [y,x], x increases right, y increases down\""
      << ",\"sampling\":\"nearest source integer index, no averaging\""
      << ",\"operator\":\"GMS::Image::GetRealValue\",\"computation\":\"DM native value reads; display adaptation only\""
      << ",\"quantitative\":false,\"source_write_requested\":false,\"snapshot_atomic\":false}";
    auto result = stream.str();
    // Leave additional room for the NB2 receipt/envelope above the native body.
    if (result.size() > nb::kMaxReply - 2048 || !nb::valid_json(result))
        throw std::runtime_error("native_preview_result_over_budget_or_invalid");
    source.reset();
    require_ready();
    return result;
}
