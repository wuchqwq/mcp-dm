// An explicit frame copy uses the native slice-copy and native type-conversion
// entrypoints. No bridge pixel write, projection, resampling or arithmetic cast.
struct FrameCalibration353 {
    float zero = 0, scale = 0, origin = 0, raw_scale = 0;
    std::string unit;
    bool operator==(const FrameCalibration353& other) const {
        // Recognized unavailable calibration is preserved too. Bit comparison
        // keeps NaN fields comparable without treating two lost fields as valid.
        return std::memcmp(&zero, &other.zero, sizeof(float)) == 0 &&
               std::memcmp(&scale, &other.scale, sizeof(float)) == 0 &&
               std::memcmp(&origin, &other.origin, sizeof(float)) == 0 &&
               std::memcmp(&raw_scale, &other.raw_scale, sizeof(float)) == 0 && unit == other.unit;
    }
    bool usable() const {
        return std::isfinite(zero) && std::isfinite(scale) && scale != 0 &&
               std::isfinite(origin) && raw_scale == scale && !unit.empty();
    }
};
FrameCalibration353 frame_calibration353(void* image, std::uint32_t axis) {
    FrameCalibration353 result;
    VendorString unit;
    api.calibration(image, axis, &result.zero, &result.scale, &unit.value, 0);
    require_ready();
    api.calibration(image, axis, &result.origin, &result.raw_scale, nullptr, 1);
    require_ready();
    result.unit = unit.utf8(256);
    return result;
}
struct FrameIntensity353 {
    float origin = 0, scale = 0;
    std::string unit;
    bool operator==(const FrameIntensity353& other) const {
        return std::memcmp(&origin, &other.origin, sizeof(float)) == 0 &&
               std::memcmp(&scale, &other.scale, sizeof(float)) == 0 && unit == other.unit;
    }
};
FrameIntensity353 frame_intensity353(void* image) {
    FrameIntensity353 result;
    VendorString unit;
    api.intensity_calibration(image, &result.origin, &result.scale, &unit.value);
    require_ready();
    result.unit = unit.utf8(256);
    return result;
}
std::string frame_number353(double value) {
    if (!std::isfinite(value)) return "null";
    auto out = json_stream(); out << value; return out.str();
}
std::string frame_intensity_json353(const FrameIntensity353& value) {
    return "{\"origin\":" + frame_number353(value.origin) + ",\"scale\":" + frame_number353(value.scale) +
        ",\"unit\":" + (value.unit.empty() ? "null" : nb::quote(value.unit)) + '}';
}
void frame_owned353(ImageRef& reference) {
    void* image = reference.value.image;
    if (!image || !accessible_memory(image, sizeof(std::int64_t)) || !reference_counter(image, 0) ||
        InterlockedCompareExchange64(reference_counter(image, 0), 0, 0) <= 0) {
        // An invalid owned pointer cannot be safely decremented by ImageRef's
        // ordinary destructor. Latch off the adapter and abandon that pointer.
        reference.relinquish();
        fatal_abi = true;
        throw std::runtime_error("native_frame_invalid_owned_reference");
    }
}
void frame_descriptor353(void* image, std::uint32_t id, const nb::FramePlan353& plan, std::uint32_t code) {
    if (!id || api.id(image) != id || api.ndim(image) != 2 || api.dtype(image) != code ||
        packing_style(image) != 1 || api.dimension(image, 0) != plan.width ||
        api.dimension(image, 1) != plan.height)
        throw std::runtime_error("native_frame_output_descriptor_mismatch");
    require_ready();
}
std::string execute_frame353(const NativeRequest& request) {
    require_ready();
    if (request.args.size() != 2) throw std::runtime_error("native_frame_requires_image_id_and_index");
    if (!api.crop || !api.image_convert || !api.intensity_calibration || !api.packing)
        throw std::runtime_error("native_frame_bindings_unavailable");
    ImageRef source(api.find_id, request.args[0]);
    auto* source_image = source.value.image;
    const auto source_id = request.args[0];
    if (api.id(source_image) != source_id) throw std::runtime_error("image_identity_mismatch");
    if (api.ndim(source_image) != 3 || api.dtype(source_image) != nb::kFrameUint16Code353 ||
        packing_style(source_image) != 1)
        throw std::runtime_error("native_frame_requires_ordinary_uint16_rank3");
    const auto plan = nb::frame_plan353(api.dimension(source_image, 0), api.dimension(source_image, 1),
        api.dimension(source_image, 2), request.args[1], retained_result_bytes, retained_results.size());
    const auto source_info = metadata(source_image, false);
    const std::array<FrameCalibration353, 3> axes{{frame_calibration353(source_image, 0),
        frame_calibration353(source_image, 1), frame_calibration353(source_image, 2)}};
    const auto intensity = frame_intensity353(source_image);
    require_ready();
    ImageRef plane;
    NativeRef* plane_return = nullptr;
    try { plane_return = api.crop(source_image, &plane.value, &plan.slice); }
    catch (...) { if (plane.value.image) frame_owned353(plane); throw; }
    if (plane.value.image) frame_owned353(plane);
    if (plane_return != &plane.value || !plane.value.image)
        throw std::runtime_error("native_frame_slice_no_output_reference");
    require_ready();
    const auto plane_id = api.id(plane.value.image);
    if (plane.value.image == source_image || plane_id == source_id || !plane_id || retained_results.count(plane_id))
        throw std::runtime_error("native_frame_slice_identity_invalid");
    frame_descriptor353(plane.value.image, plane_id, plan, nb::kFrameUint16Code353);
    for (unsigned axis = 0; axis < 2; ++axis)
        if (!(frame_calibration353(plane.value.image, axis) == axes[axis]))
            throw std::runtime_error("native_frame_slice_calibration_mismatch");
    if (!(frame_intensity353(plane.value.image) == intensity))
        throw std::runtime_error("native_frame_slice_intensity_mismatch");
    ImageRef output;
    NativeRef* output_return = nullptr;
    try { output_return = api.image_convert(&output.value, &plane.value, 2); }
    catch (...) { if (output.value.image) frame_owned353(output); throw; }
    if (output.value.image) frame_owned353(output);
    if (output_return != &output.value || !output.value.image)
        throw std::runtime_error("native_frame_convert_no_output_reference");
    require_ready();
    const auto output_id = api.id(output.value.image);
    if (output.value.image == source_image || output.value.image == plane.value.image || !output_id ||
        output_id == source_id || output_id == plane_id || retained_results.count(output_id))
        throw std::runtime_error("native_frame_output_identity_invalid");
    frame_descriptor353(output.value.image, output_id, plan, 2);
    for (unsigned axis = 0; axis < 2; ++axis)
        if (!(frame_calibration353(output.value.image, axis) == axes[axis]))
            throw std::runtime_error("native_frame_output_calibration_mismatch");
    const auto output_intensity = frame_intensity353(output.value.image);
    if (!(output_intensity == intensity)) throw std::runtime_error("native_frame_output_intensity_mismatch");
    const auto output_info = metadata(output.value.image, false);
    if (api.id(source_image) != source_id || api.ndim(source_image) != 3 ||
        api.dtype(source_image) != nb::kFrameUint16Code353 || packing_style(source_image) != 1 ||
        api.dimension(source_image, 0) != plan.width || api.dimension(source_image, 1) != plan.height ||
        api.dimension(source_image, 2) != plan.frames || metadata(source_image, false) != source_info ||
        !(frame_intensity353(source_image) == intensity))
        throw std::runtime_error("native_frame_source_metadata_changed");
    for (unsigned axis = 0; axis < 3; ++axis)
        if (!(frame_calibration353(source_image, axis) == axes[axis]))
            throw std::runtime_error("native_frame_source_calibration_changed");
    const bool coordinate_numbers = std::isfinite(axes[2].origin) && std::isfinite(axes[2].zero) &&
        std::isfinite(axes[2].scale) && axes[2].scale != 0 && axes[2].raw_scale == axes[2].scale;
    const auto coordinate = coordinate_numbers ?
        static_cast<double>(axes[2].zero) + static_cast<double>(plan.index) * axes[2].scale :
        std::numeric_limits<double>::quiet_NaN();
    auto s = json_stream();
    s << "{\"backend\":\"digitalmicrograph-native\",\"operation\":\"FRAME\",\"source_image_id\":" << source_id
      << ",\"image_id\":" << output_id << ",\"frame_index\":" << plan.index
      << ",\"frame_axis\":{\"dm_dimension\":2,\"numpy_axis\":0,\"index_base\":0,\"role\":\"unspecified_sequence\",\"count\":"
      << plan.frames << ",\"calibrated_value\":" << frame_number353(coordinate)
      << ",\"unit\":" << (axes[2].unit.empty() ? "null" : nb::quote(axes[2].unit))
      << ",\"usable\":" << (axes[2].usable() && std::isfinite(coordinate) ? "true" : "false") << '}'
      << ",\"source\":" << source_info << ",\"image\":" << output_info
      << ",\"operator\":\"GMS::Image::GetSubSliceAsImage + GMSImageProcessing::ImageConvert\""
      << ",\"computation\":\"DM native frame copy and explicit uint16-to-float32 conversion\""
      << ",\"output_bytes\":" << plan.bytes << ",\"validation_peak_new_image_bytes\":" << plan.peak_bytes
      << ",\"dtype_conversion\":{\"input_dtype\":\"uint16\",\"input_data_type_code\":10,\"output_dtype\":\"float32\",\"output_data_type_code\":2,\"lossless_values\":true,\"operator\":\"GMSImageProcessing::ImageConvert\"}"
      << ",\"intensity_calibration_source\":" << frame_intensity_json353(intensity)
      << ",\"intensity_calibration_output\":" << frame_intensity_json353(output_intensity)
      << ",\"intensity_calibration_applied\":false,\"intensity_semantics\":\"raw pixel intensity\""
      << ",\"ownership\":\"plugin retained strong reference until normal native STOP/cleanup\""
      << ",\"visible_dm_document\":false,\"source_write_requested\":false,\"snapshot_atomic\":false}";
    const auto result = s.str();
    if (!nb::valid_json(result) || result.size() > nb::kMaxReply - 2048)
        throw std::runtime_error("native_frame_result_over_budget_or_invalid");
    plane.reset(); // Native temporary must be dropped before output ownership commits.
    source.reset();
    require_ready();
    retain_native_result(output, output_id, plan.bytes, request,
        "GMS::Image::GetSubSliceAsImage + GMSImageProcessing::ImageConvert", {source_id}, {source_info}, output_info,
        "independent native frame copy; explicit lossless uint16-to-float32 conversion; intensity calibration not applied",
        false, "null", nb::kCropOutputBytes, result);
    return result;
}
