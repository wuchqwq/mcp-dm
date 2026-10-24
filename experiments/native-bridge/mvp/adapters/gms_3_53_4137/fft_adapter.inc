// Include inside dm_adapter.cpp's anonymous namespace after shared retained-result
// helpers. All scientific work remains in the exact vendor function pointers.
// Exact-profile qualification admits operations; no runtime override exists.
nb::FftImage353 fft_image353(void* image) {
    if (!api.packing) throw std::runtime_error("native_fft_packing_unavailable");
    nb::NativePacking353 packing{UINT32_MAX};
    if (api.packing(image, &packing) != &packing) {
        fatal_abi = true;
        throw std::runtime_error("native_fft_packing_result_mismatch");
    }
    require_ready();
    const auto dimensions = api.ndim(image);
    return {api.id(image), dimensions, api.dtype(image), packing.value,
            dimensions == 2 ? api.dimension(image, 0) : 0u,
            dimensions == 2 ? api.dimension(image, 1) : 0u};
}

void validate_fft_finite_complex353(const NativeRef& image, const nb::FftImage353& descriptor) {
    if (!api.real_component || !api.imag_component)
        throw std::runtime_error("native_fft_component_check_unavailable");
    for (const auto component : {api.real_component, api.imag_component}) {
        ImageRef temporary;
        require_ready();
        if (component(&temporary.value, &image) != &temporary.value || !temporary.value.image)
            throw std::runtime_error("native_fft_component_check_no_output");
        require_ready();
        if (temporary.value.image == image.image)
            throw std::runtime_error("native_fft_component_check_alias");
        const auto actual = fft_image353(temporary.value.image);
        if (!actual.id || actual.id == descriptor.id || retained_results.count(actual.id) ||
            actual.dimensions != 2 || actual.data_type != 2 || actual.packing != 1 ||
            actual.width != descriptor.width || actual.height != descriptor.height)
            throw std::runtime_error("native_fft_component_check_descriptor_mismatch");
        validate_native_finite_image(temporary.value, "native_fft_nonfinite_component");
        temporary.reset();
        require_ready();
    }
}

void write_fft_frequency_grid353(std::ostringstream& stream, const nb::FftImage353& descriptor,
                                 const std::array<CropAxisCalibration, 2>& calibration) {
    stream << "{\"native_calibration_has_half_bin_offset\":true,\"axes\":[";
    for (unsigned axis = 0; axis < 2; ++axis) {
        if (axis) stream << ',';
        const auto size = axis == 0 ? descriptor.width : descriptor.height;
        const auto dc = size / 2;
        const double step = calibration[axis].scale;
        const double zero = calibration[axis].zero;
        stream << "{\"dm_dimension\":" << axis << ",\"size\":" << size << ",\"dc_index\":" << dc
          << ",\"cycles_per_pixel_step\":" << 1.0 / size
          << ",\"physical_frequency_step\":" << step << ",\"unit\":" << nb::quote(calibration[axis].unit)
          << ",\"frequency_at_index_zero\":" << -static_cast<double>(dc) * step
          << ",\"native_calibrated_value_at_pixel_zero\":" << zero
          << ",\"native_calibration_dc_value\":" << zero + static_cast<double>(dc) * step
          << ",\"coordinate_rule\":\"f(i)=(i-dc_index)*physical_frequency_step\"}";
    }
    stream << "]}";
}

std::string execute_fft(const NativeRequest& request) {
    require_ready();
    if (request.args.size() != 1) throw std::runtime_error("native_fft_requires_one_image_id");
    const auto operation = nb::fft_operation353(request.op);
    // A retained record is authoritative lineage, not parsed receipt JSON or
    // the current front image. Reject unsupported complex sources before Find.
    const RetainedResult* retained_source = nullptr;
    bool frequency_output = operation == nb::FftOperation353::RealForward;
    if (operation != nb::FftOperation353::RealForward) {
        const auto found = retained_results.find(request.args[0]);
        if (found == retained_results.end() || found->second.data_type_code != 3 ||
            found->second.kind != ResultKind::NativeOperation || found->second.source_ids.size() != 1 ||
            (operation == nb::FftOperation353::ComplexInverse ? found->second.operation != "FFT" :
                (found->second.operation != "FFT" && found->second.operation != "IFFT")))
            throw std::runtime_error(operation == nb::FftOperation353::ComplexInverse ?
                "native_ifft_requires_plugin_retained_fft" : "native_fft_component_requires_plugin_transform");
        retained_source = &found->second;
        frequency_output = operation != nb::FftOperation353::ComplexInverse && retained_source->operation == "FFT";
    }
    auto function = api.real_fft;
    switch (operation) {
    case nb::FftOperation353::RealForward: function = api.real_fft; break;
    case nb::FftOperation353::ComplexInverse: function = api.ifft; break;
    case nb::FftOperation353::Real: function = api.real_component; break;
    case nb::FftOperation353::Imag: function = api.imag_component; break;
    case nb::FftOperation353::VendorArg: function = api.arg; break;
    case nb::FftOperation353::VendorNorm: function = api.norm; break;
    }
    if (!function) throw std::runtime_error("native_fft_symbol_unavailable");
    if (!api.packing || !api.real_component || !api.imag_component ||
        !api.minimum || !api.maximum || !api.sum || !api.mean)
        throw std::runtime_error("native_fft_validation_unavailable");
    ImageRef source(api.find_id, request.args[0]);
    const auto source_descriptor = fft_image353(source.value.image);
    if (source_descriptor.id != request.args[0]) throw std::runtime_error("image_identity_mismatch");
    if (retained_source && source.value.image != retained_source->value.image)
        throw std::runtime_error("native_fft_retained_identity_mismatch");
    const bool uint32_lineage = source_descriptor.data_type == 11 ||
        (retained_source && retained_source->uint32_operation_lineage);
    if (uint32_lineage) require_uint32_operation353("native_uint32_fft", api.packing && api.minimum && api.maximum &&
        api.sum && api.mean && api.real_fft && api.ifft && api.real_component && api.imag_component && api.arg && api.norm);
    const auto plan = nb::fft_plan353(operation, source_descriptor,
                                     retained_result_bytes, retained_results.size());
    // Metadata and shared budget checks precede any vendor result allocation.
    const auto source_calibration = crop_calibration(source.value.image);
    const auto source_info = metadata(source.value.image);
    if (retained_source && source_info != retained_source->metadata)
        throw std::runtime_error("native_fft_retained_metadata_changed");
    // Reject unrepresentable reciprocal axes before any native allocation.
    if (operation == nb::FftOperation353::RealForward || operation == nb::FftOperation353::ComplexInverse)
        for (unsigned axis = 0; axis < 2; ++axis)
            (void)nb::fft_reciprocal_scale353(axis == 0 ? plan.width : plan.height, source_calibration[axis].scale);
    require_ready();
    if (source_descriptor.data_type == 3)
        validate_fft_finite_complex353(source.value, source_descriptor);
    else
        validate_native_finite_image(source.value, "native_fft_nonfinite_source");
    require_ready();
    ImageRef output;
    if (function(&output.value, &source.value) != &output.value || !output.value.image)
        throw std::runtime_error("native_fft_no_output_reference");
    require_ready();
    if (output.value.image == source.value.image)
        throw std::runtime_error("native_fft_output_alias");
    const auto output_descriptor = fft_image353(output.value.image);
    nb::validate_fft_output353(plan, source_descriptor, output_descriptor);
    if (retained_results.count(output_descriptor.id))
        throw std::runtime_error("native_fft_output_identity_invalid");
    if (output_descriptor.data_type == 3)
        validate_fft_finite_complex353(output.value, output_descriptor);
    else
        validate_native_finite_image(output.value, "native_fft_nonfinite_output");
    require_ready();
    const auto output_calibration = crop_calibration(output.value.image);
    for (unsigned axis = 0; axis < 2; ++axis) {
        const auto size = axis == 0 ? plan.width : plan.height;
        const auto& actual = output_calibration[axis];
        if (operation == nb::FftOperation353::RealForward)
            nb::validate_fft_frequency_calibration353(size, source_calibration[axis].scale,
                                                     actual.scale, actual.origin, actual.zero);
        else if (operation == nb::FftOperation353::ComplexInverse)
            nb::validate_ifft_spatial_calibration353(size, source_calibration[axis].scale,
                                                   actual.scale, actual.origin, actual.zero);
        else if (!(actual == source_calibration[axis]))
            throw std::runtime_error("native_fft_component_calibration_mismatch");
    }
    const auto output_info = metadata(output.value.image);
    const auto source_after = fft_image353(source.value.image);
    if (source_after.id != source_descriptor.id || source_after.dimensions != source_descriptor.dimensions ||
        source_after.data_type != source_descriptor.data_type || source_after.packing != source_descriptor.packing ||
        source_after.width != source_descriptor.width || source_after.height != source_descriptor.height ||
        crop_calibration(source.value.image) != source_calibration || metadata(source.value.image) != source_info)
        throw std::runtime_error("native_fft_source_metadata_changed");
    require_ready();
    const std::string semantics = std::string(nb::fft_representation353(operation)) +
        "; positive-sign centered forward; normalized negative-sign paired inverse; native values and calibration unchanged by bridge" +
        (uint32_lineage ? "; uint32 ancestry; DM rounds input to binary32 before Fourier transform; binary32-component results not lossless for arbitrary uint32 inputs; no bridge pixel cast" : "");
    auto stream = json_stream();
    stream << "{\"backend\":\"digitalmicrograph-native\",\"operation\":" << nb::quote(request.op)
      << ",\"source_image_id\":" << source_descriptor.id << ",\"image_id\":" << output_descriptor.id
      << ",\"source\":" << source_info << ",\"image\":" << output_info
      << ",\"operator\":" << nb::quote(nb::fft_operator353(operation));
    if (uint32_lineage) stream << ",\"dtype_semantics\":" <<
        uint32_dtype_semantics353(1,source_descriptor.data_type,output_descriptor.data_type);
    stream
      << ",\"computation\":\"DM native\",\"representation\":" << nb::quote(nb::fft_representation353(operation))
      << ",\"normalization\":" << nb::quote(nb::fft_normalization353(operation))
      << ",\"centering\":" << nb::quote(frequency_output ? "fftshift_data" : "spatial_origin_zero")
      << ",\"phase_units\":" << nb::quote(operation == nb::FftOperation353::VendorArg ? "radians" : "not_applicable")
      << ",\"transform_signs\":{\"forward\":\"+\",\"inverse\":\"-\"}"
      << ",\"input_index_origin\":\"zero-based pixel indices\",\"source_spatial_origin_used\":false"
      << ",\"intensity_calibration_applied\":false,\"inverse_restores_source_origin\":false"
      << ",\"intensity_calibration_policy\":" << nb::quote(nb::kFftIntensityPolicy353)
      << ",\"frequency_grid\":";
    if (frequency_output) write_fft_frequency_grid353(stream, output_descriptor, output_calibration);
    else stream << "null";
    stream
      << ",\"semantics\":" << nb::quote(semantics) << ",\"output_bytes\":" << plan.output_bytes
      << ",\"validation_peak_new_image_bytes\":" << plan.peak_new_bytes
      << ",\"ownership\":\"plugin retained strong reference until normal native STOP/cleanup\""
      << ",\"visible_dm_document\":false,\"source_write_requested\":false,\"snapshot_atomic\":false}";
    auto result = stream.str();
    if (!nb::valid_json(result)) throw std::runtime_error("native_fft_result_over_budget_or_invalid");
    // The shared helper rechecks readiness/capacity and commits ownership last.
    // All earlier failures release exactly this freshly returned owned ref.
    source.reset();
    require_ready();
    retain_native_result(output, output_descriptor.id, plan.output_bytes, request,
                         nb::fft_operator353(operation), {source_descriptor.id},
                         {source_info}, output_info, semantics, uint32_lineage);
    return result;
}
