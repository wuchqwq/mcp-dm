// Static one-shot native extraction. No live profile, evaluator or listener.
void initialize_line_profile353(HMODULE gms, HMODULE image) noexcept {
    try {
        LineApi353 next;
        next.is_line = rva_symbol<decltype(next.is_line)>(gms,entry_rva("roi_is_line"));
        next.line = rva_symbol<decltype(next.line)>(gms,entry_rva("roi_line"));
        next.extract = rva_symbol<decltype(next.extract)>(gms,entry_rva("line_profile_extract"));
        next.intensity_calibration = symbol<decltype(next.intensity_calibration)>(image,
            "?GetIntensityCalibration@Image@GMS@@QEAAXAEAM0AEAV?$basic_string@_WU?$char_traits@_W@std@@V?$allocator@_W@2@@std@@@Z");
        next.real_value = symbol<decltype(next.real_value)>(image,
            "?GetRealValue@Image@GMS@@QEBANAEBVDataIndex@Imaging@Gatan@@@Z");
        line_api353 = next;
    } catch (...) { line_api353 = LineApi353{}; }
}
std::string profile_intensity353(void* image) {
    float origin = 0, scale = 0; VendorString unit;
    line_api353.intensity_calibration(image,&origin,&scale,&unit.value);
    require_ready();
    if (!std::isfinite(origin) || !std::isfinite(scale)) throw std::runtime_error("native_profile_invalid_intensity_calibration");
    const auto units = unit.utf8(256);
    auto out=json_stream();out << "{\"origin\":" << origin << ",\"scale\":" << scale << ",\"unit\":"
        << (units.empty()?"null":nb::quote(units)) << '}';return out.str();
}
std::string execute_line_profile353(const NativeRequest& request) {
    require_ready();
    if (request.args.size()!=9) throw std::runtime_error("native_profile_requires_gui_identity_line_and_width");
    if (!line_api353.ready() || !roi_api353.ready() || !api.real_value || !api.packing)
        throw std::runtime_error("native_profile_bindings_unavailable");
    if (request.args[8]!=1) throw std::runtime_error("native_profile_requires_width_one");
    for (unsigned i=1;i<4;++i) if (request.args[i]>INT32_MAX) throw std::runtime_error("native_profile_invalid_gui_identity");
    ImageRef source(api.find_id,request.args[0]);
    const auto before=fft_image353(source.value.image);
    if (before.id!=request.args[0]) throw std::runtime_error("image_identity_mismatch");
    const auto lineage=retained_results.find(before.id);
    if (lineage!=retained_results.end() && (lineage->second.scientific_unresolved || lineage->second.scientific_result!="null"))
        throw std::runtime_error("native_profile_scientific_source_context_unsupported");
    if (before.dimensions!=2 || (before.data_type!=2 && before.data_type!=nb::kUint32Code353) || before.packing!=1 ||
        !before.width || !before.height || static_cast<std::uint64_t>(before.width)*before.height>4194304)
        throw std::runtime_error("native_profile_requires_bounded_ordinary_float32_or_uint32_2d");
    nb::RoiLine353 expected{static_cast<float>(request.args[4]),static_cast<float>(request.args[5]),
        static_cast<float>(request.args[6]),static_cast<float>(request.args[7])};
    const std::array<float,4> expected_values{expected.x0,expected.y0,expected.x1,expected.y1};
    for (unsigned i=0;i<4;++i)
        if (static_cast<double>(expected_values[i])!=request.args[i+4]) throw std::runtime_error("native_profile_line_not_exact_float32");
    const auto samples=nb::profile_samples353(expected,before.width,before.height);
    const auto bytes=static_cast<std::uint64_t>(samples)*8;
    if (retained_results.size()>=nb::kCropRetainedCount || retained_result_bytes>nb::kCropRetainedBytes || bytes>nb::kCropRetainedBytes-retained_result_bytes)
        throw std::runtime_error("native_result_retention_capacity");
    const auto source_info=metadata(source.value.image);
    const auto cal=crop_calibration(source.value.image);
    if (cal[0].unit!=cal[1].unit || cal[0].scale!=cal[1].scale)
        throw std::runtime_error("native_profile_requires_equal_signed_spatial_scales_and_units");
    const auto source_intensity=profile_intensity353(source.value.image);
    LineTarget353 target{request.args[1],request.args[2],request.args[3]};
    const auto snapshot=collect_rois353(source.value,before.id,before.width,before.height,true,&target);
    if (!target.found) throw std::runtime_error("native_profile_gui_line_missing");
    if (target.issue) throw std::runtime_error(target.issue);
    if (target.line.x0!=expected.x0 || target.line.y0!=expected.y0 || target.line.x1!=expected.x1 || target.line.y1!=expected.y1)
        throw std::runtime_error("native_profile_gui_line_changed");
    LineTarget353 stable{request.args[1],request.args[2],request.args[3]};
    if (collect_rois353(source.value,before.id,before.width,before.height,true,&stable)!=snapshot || !stable.found || stable.json!=target.json ||
        metadata(source.value.image)!=source_info || profile_intensity353(source.value.image)!=source_intensity)
        throw std::runtime_error("native_profile_source_snapshot_changed");
    require_ready();
    // Raw this pointer and raw owned Image* return are established independently
    // of the script registration: no hidden NativeRef/sret on this boundary.
    ImageRef output;
    output.value.image=line_api353.extract(source.value.image,expected.x0,expected.y0,expected.x1,expected.y1,1);
    if (!output.value.image) throw std::runtime_error("native_profile_missing_output");
    try { validate_roi_object353(output.value.image,sizeof(std::int64_t)); }
    catch (...) { output.relinquish(); throw; }
    const auto output_id=api.id(output.value.image);
    if (!output_id || output.value.image==source.value.image || output_id==before.id || retained_results.count(output_id))
        throw std::runtime_error("native_profile_output_identity_invalid");
    if (api.ndim(output.value.image)!=1 || api.dtype(output.value.image)!=nb::kProfileFloat64Code353 ||
        packing_style(output.value.image)!=1 || api.dimension(output.value.image,0)!=samples)
        throw std::runtime_error("native_profile_output_descriptor_mismatch");
    const auto output_info=metadata(output.value.image,true,true);
    const auto output_cal=crop_axis_calibration(output.value.image,0);
    if (output_cal.origin!=0 || output_cal.zero!=0 || output_cal.scale!=cal[0].scale || output_cal.unit!=cal[0].unit)
        throw std::runtime_error("native_profile_output_calibration_mismatch");
    const auto intensity=profile_intensity353(output.value.image);
    if (intensity!=source_intensity) throw std::runtime_error("native_profile_output_intensity_calibration_mismatch");
    std::string raw;raw.reserve(static_cast<std::size_t>(bytes));
    for(std::uint32_t i=0;i<samples;++i) {
        const nb::NativeDataIndex1D353 index{1,0,static_cast<std::int64_t>(i)};
        const auto value=line_api353.real_value(output.value.image,&index);
        require_ready();nb::append_profile_float64_le353(raw,value);
    }
    LineTarget353 after_target{request.args[1],request.args[2],request.args[3]};
    if (collect_rois353(source.value,before.id,before.width,before.height,true,&after_target)!=snapshot ||
        !after_target.found || after_target.json!=target.json || metadata(source.value.image)!=source_info ||
        crop_calibration(source.value.image)!=cal || profile_intensity353(source.value.image)!=source_intensity ||
        metadata(output.value.image,true,true)!=output_info || profile_intensity353(output.value.image)!=intensity)
        throw std::runtime_error("native_profile_metadata_or_gui_snapshot_changed");
    const double step_x=(static_cast<double>(expected.x1)-expected.x0)/(samples-1);
    const double step_y=(static_cast<double>(expected.y1)-expected.y0)/(samples-1);
    auto out=json_stream();
    out << "{\"backend\":\"digitalmicrograph-native\",\"operation\":\"PROFILE\",\"source_image_id\":" << before.id
        << ",\"image_id\":" << output_id << ",\"source\":" << source_info << ",\"image\":" << output_info
        << ",\"source_gui_line\":" << target.json << ",\"width\":1,\"shape\":[" << samples
        << "],\"dtype\":\"float64\",\"axes\":[\"native_profile_axis\"],\"byte_order\":\"little\",\"array_order\":\"C\",\"data_encoding\":\"base64\""
        << ",\"sample_count\":" << samples << ",\"raw_bytes\":" << bytes << ",\"output_bytes\":" << bytes
        << ",\"values_base64\":" << nb::quote(nb::read_base64_353(raw))
        << ",\"source_sample_start_xy\":[" << expected.x0 << ',' << expected.y0 << "],\"source_sample_end_xy\":[" << expected.x1 << ',' << expected.y1
        << "],\"source_sample_step_xy\":[" << step_x << ',' << step_y << "]"
        << ",\"distance_zero\":0,\"distance_step\":" << std::abs(static_cast<double>(output_cal.scale)) << ",\"distance_unit\":" << nb::quote(output_cal.unit)
        << ",\"source_intensity_calibration\":" << source_intensity << ",\"intensity_calibration\":" << intensity
        << ",\"calibration_complete\":true,\"operator\":\"LiveProfile_ExtractLineProfile\",\"computation\":\"DM native\""
        << ",\"intensity_calibration_applied\":false,\"intensity_semantics\":\"raw pixel intensity\",\"source_write_requested\":false,\"snapshot_atomic\":false"
        << ",\"ownership\":\"plugin retained strong reference until normal native STOP/cleanup; shown document may retain image\"}";
    const auto result=out.str();
    if(result.size()>nb::kMaxReply-2048 || !nb::valid_json(result)) throw std::runtime_error("native_profile_result_over_budget_or_invalid");
    retain_native_result(output,output_id,bytes,request,"LiveProfile_ExtractLineProfile",{before.id},{source_info},output_info,"raw pixel intensity sampled by DM native profile");
    return result;
}
