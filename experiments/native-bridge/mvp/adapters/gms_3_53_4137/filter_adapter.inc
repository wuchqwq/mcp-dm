// Include inside the adapter's anonymous namespace after fft_adapter.inc.
// FILTER selects a reviewed named DM filter; no coefficients or pixel kernel
// are implemented here. Admission is controlled by the prepared-host gate.
std::string execute_filter(const NativeRequest& request) {
    require_ready();
    if (request.args.size() != 2) throw std::runtime_error("native_filter_requires_image_id_and_kind");
    auto function = api.smooth_filter;
    const char* name = nullptr;
    switch (request.args[1]) {
    case 1: function = api.smooth_filter; name = "GMSImageProcessing::SmoothFilter"; break;
    case 2: function = api.sobel_filter; name = "GMSImageProcessing::SobelFilter"; break;
    case 3: function = api.laplace_filter; name = "GMSImageProcessing::LaplaceFilter"; break;
    case 4: function = api.sharpen_filter; name = "GMSImageProcessing::SharpenFilter"; break;
    default: throw std::runtime_error("native_filter_kind_unsupported");
    }
    if (!function) throw std::runtime_error("native_filter_symbol_unavailable");
    if (!api.packing || !api.minimum || !api.maximum || !api.sum || !api.mean)
        throw std::runtime_error("native_filter_finite_check_unavailable");
    ImageRef source(api.find_id, request.args[0]);
    const auto source_descriptor = fft_image353(source.value.image);
    if (source_descriptor.id != request.args[0]) throw std::runtime_error("image_identity_mismatch");
    if (source_descriptor.dimensions != 2 || source_descriptor.data_type != 2 || source_descriptor.packing != 1)
        throw std::runtime_error("native_filter_requires_float32_2d_ordinary_packing");
    if (!source_descriptor.width || !source_descriptor.height)
        throw std::runtime_error("invalid_image_dimensions");
    if (source_descriptor.width < 5 || source_descriptor.height < 5)
        throw std::runtime_error("native_filter_requires_dimensions_at_least_5");
    const auto pixels = static_cast<std::uint64_t>(source_descriptor.width) * source_descriptor.height;
    if (source_descriptor.width > nb::kFftMaximumDimension353 ||
        source_descriptor.height > nb::kFftMaximumDimension353 || pixels > nb::kFftMaximumPixels353)
        throw std::runtime_error("native_filter_input_over_budget");
    const auto bytes = pixels * sizeof(float);
    // Sobel's reviewed wrapper keeps one extra convolution image alive while
    // producing the output. Reserve explicit images even though lower vendor
    // convolution/locking workspace remains unknown and is not claimed bounded.
    const auto peak_bytes = bytes * (request.args[1] == 2 ? 2u : 1u);
    const std::size_t peak_images = request.args[1] == 2 ? 2u : 1u;
    if (bytes > nb::kCropOutputBytes)
        throw std::runtime_error("native_filter_output_over_budget");
    if (retained_results.size() > nb::kCropRetainedCount ||
        peak_images > nb::kCropRetainedCount - retained_results.size())
        throw std::runtime_error("native_filter_retention_capacity");
    if (retained_result_bytes > nb::kCropRetainedBytes ||
        peak_bytes > nb::kCropRetainedBytes - retained_result_bytes)
        throw std::runtime_error("native_filter_retained_bytes_over_budget");
    const auto source_info = metadata(source.value.image);
    const auto calibration = crop_calibration(source.value.image);
    validate_native_finite_image(source.value, "native_filter_nonfinite_source");
    require_ready();
    ImageRef output;
    if (function(&output.value, &source.value) != &output.value || !output.value.image)
        throw std::runtime_error("native_filter_no_output_reference");
    require_ready();
    if (output.value.image == source.value.image)
        throw std::runtime_error("native_filter_output_alias");
    const auto actual = fft_image353(output.value.image);
    if (!actual.id || actual.id == source_descriptor.id || retained_results.count(actual.id))
        throw std::runtime_error("native_filter_output_identity_invalid");
    if (actual.dimensions != 2 || actual.data_type != 2 || actual.packing != 1 ||
        actual.width != source_descriptor.width || actual.height != source_descriptor.height)
        throw std::runtime_error("native_filter_output_descriptor_mismatch");
    const auto output_info = metadata(output.value.image);
    if (crop_calibration(output.value.image) != calibration)
        throw std::runtime_error("native_filter_output_calibration_mismatch");
    validate_native_finite_image(output.value, "native_filter_nonfinite_output");
    const auto source_after = fft_image353(source.value.image);
    if (source_after.id != source_descriptor.id || source_after.dimensions != source_descriptor.dimensions ||
        source_after.data_type != source_descriptor.data_type || source_after.packing != source_descriptor.packing ||
        source_after.width != source_descriptor.width || source_after.height != source_descriptor.height ||
        crop_calibration(source.value.image) != calibration || metadata(source.value.image) != source_info)
        throw std::runtime_error("native_filter_source_metadata_changed");
    require_ready();
    const std::string semantics = "DM native filter; kernel and edge behavior vendor-defined pending independent qualification";
    auto stream = json_stream();
    stream << "{\"backend\":\"digitalmicrograph-native\",\"operation\":\"FILTER\",\"filter_kind\":" << request.args[1]
      << ",\"source_image_id\":" << source_descriptor.id << ",\"image_id\":" << actual.id
      << ",\"source\":" << source_info << ",\"image\":" << output_info << ",\"operator\":" << nb::quote(name)
      << ",\"computation\":\"DM native\",\"kernel\":\"vendor_defined\",\"edge_behavior\":\"vendor_defined\""
      << ",\"semantics\":" << nb::quote(semantics) << ",\"output_bytes\":" << bytes
      << ",\"validation_peak_new_image_bytes\":" << peak_bytes
      << ",\"ownership\":\"plugin retained strong reference until normal native STOP/cleanup\""
      << ",\"visible_dm_document\":false,\"source_write_requested\":false,\"snapshot_atomic\":false}";
    auto result = stream.str();
    if (!nb::valid_json(result)) throw std::runtime_error("native_filter_result_over_budget_or_invalid");
    source.reset();
    require_ready();
    retain_native_result(output, actual.id, bytes, request, name, {source_descriptor.id},
                         {source_info}, output_info, semantics);
    return result;
}
