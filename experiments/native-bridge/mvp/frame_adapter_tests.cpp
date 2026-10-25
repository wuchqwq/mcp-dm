// The production implementation, injected C-shaped callbacks only. No GMS DLL
// or process is loaded. Pixel loops here are independent synthetic test oracles.
#include <fstream>
#define main existing_adapter_test_main
#include "adapter_tests.cpp"
#undef main

namespace {
std::uint32_t frame_count = 5;
float frame_origin = 2.5f, frame_scale = -0.125f;
std::wstring frame_unit = L"step";
int frame_slices = 0, frame_conversions = 0;
std::string frame_fault;
std::string cross_layer_fixture;
std::uint32_t frame_dimension_fake(const void* image, std::int32_t axis) {
    return axis == 2 ? frame_count : dimension_fake(image, axis);
}
void frame_calibration_fake(void* image, std::uint32_t axis, float* origin, float* scale,
                            void* unit, std::int32_t format) {
    if (axis != 2) { calibration_fake(image, axis, origin, scale, unit, format); return; }
    *origin = format ? frame_origin : -(frame_origin * frame_scale);
    *scale = frame_scale;
    if (unit) fill(static_cast<MsvcWString353*>(unit), frame_unit);
}
void frame_intensity_fake(void* image, float* origin, float* scale, void* unit) {
    if (frame_fault == "intensity_throw") throw std::runtime_error("surrogate intensity failure");
    *origin = 7.25f; *scale = -2.5f;
    const auto* value = static_cast<const FakeImage*>(image);
    if (value->generated && frame_fault == "slice_intensity") *scale = 1;
    if (value->code == 2 && frame_fault == "output_intensity") *origin = 0;
    fill(static_cast<MsvcWString353*>(unit), L"a.u.");
}
NativeRef* frame_slice_fake(const void* pointer, NativeRef* out, const nb::NativeDataSlice353* slice) {
    ++frame_slices;
    const auto* source = static_cast<const FakeImage*>(pointer);
    check(source == &fake && source->dimensions == 3 && source->code == 10);
    check(slice->source_dimensions == 3 && slice->output_dimensions == 2);
    check(slice->source_start[0] == 0 && slice->source_start[1] == 0 && slice->source_start[2] >= 0 &&
        static_cast<std::uint64_t>(slice->source_start[2]) < frame_count);
    check(slice->output_axes[0].source_dimension == 0 && slice->output_axes[0].length == source->width &&
        slice->output_axes[0].step == 1 && slice->output_axes[1].source_dimension == 1 &&
        slice->output_axes[1].length == source->height && slice->output_axes[1].step == 1);
    for (unsigned axis = 2; axis < 5; ++axis) {
        check(slice->output_axes[axis].source_dimension == 0 && slice->output_axes[axis].length == 0 &&
            slice->output_axes[axis].step == 0);
    }
    if (frame_fault == "slice_null") return out;
    if (frame_fault == "slice_invalid_pointer") { out->image = reinterpret_cast<void*>(1); return out; }
    if (frame_fault == "slice_alias") {
        out->image = const_cast<FakeImage*>(source); InterlockedIncrement64(&fake.references); return out;
    }
    auto created = std::make_unique<FakeImage>(*source);
    created->references = 1; created->dimensions = 2; created->generated = true; created->id = next_image_id++;
    created->pixels.clear();
    const auto pixels = static_cast<std::size_t>(source->width) * source->height;
    for (std::size_t i = 0; i < pixels; ++i)
        created->pixels.push_back(source->pixels.at(static_cast<std::size_t>(slice->source_start[2]) * pixels + i));
    if (frame_fault == "slice_rank") created->dimensions = 3;
    if (frame_fault == "slice_dtype") created->code = 2;
    if (frame_fault == "slice_packing") created->packing = 3;
    if (frame_fault == "slice_size") ++created->width;
    if (frame_fault == "slice_calibration") created->origin[0] += 1;
    if (frame_fault == "source_changed") ++const_cast<FakeImage*>(source)->origin[0];
    registry.emplace(created->id, created.get()); out->image = created.release();
    if (frame_fault == "slice_throw") throw std::runtime_error("surrogate slice failure after owned reference");
    return frame_fault == "slice_return" ? nullptr : out;
}
NativeRef* frame_convert_fake(NativeRef* out, const NativeRef* source_ref, std::uint32_t target) {
    ++frame_conversions;
    const auto* source = static_cast<const FakeImage*>(source_ref->image);
    check(target == 2 && source->code == 10 && source->dimensions == 2 && source != &fake);
    // Source plus its independent uint16 temporary are live at this point.
    check(registry.size() >= 2 && fake.references == 2);
    if (frame_fault == "output_null") return out;
    if (frame_fault == "output_invalid_pointer") { out->image = reinterpret_cast<void*>(1); return out; }
    if (frame_fault == "output_alias") {
        out->image = source_ref->image; InterlockedIncrement64(&static_cast<FakeImage*>(out->image)->references); return out;
    }
    if (frame_fault == "output_source_alias") {
        out->image = &fake; InterlockedIncrement64(&fake.references); return out;
    }
    auto created = std::make_unique<FakeImage>(*source);
    created->references = 1; created->id = next_image_id++; created->code = 2;
    if (frame_fault == "output_rank") created->dimensions = 3;
    if (frame_fault == "output_dtype") created->code = 10;
    if (frame_fault == "output_packing") created->packing = 2;
    if (frame_fault == "output_size") ++created->height;
    if (frame_fault == "output_calibration") created->scale[1] *= -1;
    registry.emplace(created->id, created.get()); out->image = created.release();
    if (frame_fault == "output_throw") throw std::runtime_error("surrogate conversion failure after owned reference");
    return frame_fault == "output_return" ? nullptr : out;
}
void inject_frame() {
    inject_fake();
    api.crop = frame_slice_fake; api.image_convert = frame_convert_fake;
    api.intensity_calibration = frame_intensity_fake; api.dimension = frame_dimension_fake;
    api.calibration = frame_calibration_fake;
    fake.dimensions = 3; fake.code = 10; fake.width = 7; fake.height = 3;
    fake.pixels.clear();
    const std::uint16_t edge[] = {0,1,32767,32768,65534,65535};
    for (std::uint32_t z = 0; z < frame_count; ++z)
        for (std::uint32_t y = 0; y < fake.height; ++y)
            for (std::uint32_t x = 0; x < fake.width; ++x)
                fake.pixels.push_back(x < 6 && y == 0 ? edge[(x+z)%6] : 1000*z+100*y+x);
}
void frame_failure(std::vector<std::uint32_t> args, const char* expected, int slices = 0, int conversions = 0) {
    const auto previous_slices = frame_slices, previous_conversions = frame_conversions;
    const auto previous_bytes = retained_result_bytes, previous_size = retained_results.size();
    std::string actual;
    try { execute_frame353({"frame_failure","FRAME",args}); }
    catch (const std::runtime_error& error) { actual = error.what(); }
    if (actual != expected) throw std::runtime_error("FRAME expected " + std::string(expected) + ", received " + actual);
    check(frame_slices == previous_slices+slices && frame_conversions == previous_conversions+conversions);
    check(fake.references == 1 && registry.size() == 1 && !fatal_abi);
    check(retained_result_bytes == previous_bytes && retained_results.size() == previous_size);
}
void frame_tests() {
    inject_frame();
    const auto source_pixels = fake.pixels;
    check(metadata(&fake,false).find("\"dtype\":\"uint16\",\"is_integer\":true,\"is_unsigned\":true") != std::string::npos);
    // Production admission uses the qualified group. A separately unqualified
    // profile is still refused before implementation/vendor calls in the
    // independent profile/dispatcher rejection tests.
    check(qualified_capability353("native_frame"));
    const auto admitted = execute_native({"shipping_admission","FRAME",{fake.id,0}});
    check(admitted.find("\"operation\":\"FRAME\"") != std::string::npos);
    check(admitted.find("\"retention\":{\"token\":") != std::string::npos);
    check(frame_slices == 1 && frame_conversions == 1 && fake.references == 1 && retained_results.size() == 1);
    const auto admitted_id = last_retained_result353;
    const auto admitted_token = retained_results.at(admitted_id).retention_token;
    result_lifecycle353({"shipping_release","RELEASE",{admitted_id,admitted_token}});
    check(retained_results.empty() && retained_result_bytes == 0 && registry.size() == 1);
    frame_failure({fake.id},"native_frame_requires_image_id_and_index");
    frame_failure({99,0},"image_not_found");
    for (const auto what : {0,1,2,3}) {
        const auto saved = api;
        if (what == 0) api.crop = nullptr;
        if (what == 1) api.image_convert = nullptr;
        if (what == 2) api.intensity_calibration = nullptr;
        if (what == 3) api.packing = nullptr;
        frame_failure({fake.id,0},"native_frame_bindings_unavailable"); api = saved;
    }
    fake.dimensions = 2; frame_failure({fake.id,0},"native_frame_requires_ordinary_uint16_rank3"); fake.dimensions = 3;
    for (const auto type : {2u,3u,11u,12u}) {
        fake.code = type; frame_failure({fake.id,0},"native_frame_requires_ordinary_uint16_rank3");
    }
    fake.code = 10; fake.packing = 3;
    frame_failure({fake.id,0},"native_frame_requires_ordinary_uint16_rank3"); fake.packing = 1;
    frame_failure({fake.id,frame_count},"native_frame_index_out_of_bounds");
    frame_failure({fake.id,UINT32_MAX},"native_frame_index_out_of_bounds");
    retained_result_bytes = nb::kCropRetainedBytes-125;
    frame_failure({fake.id,0},"native_frame_temporary_bytes_over_budget"); retained_result_bytes = 0;
    const auto saved_width = fake.width;
    fake.width = 1048577; frame_failure({fake.id,0},"native_frame_plane_over_budget"); fake.width = saved_width;
    const auto saved_frames = frame_count;
    frame_count = UINT32_MAX; frame_failure({fake.id,0},"native_frame_source_over_budget"); frame_count = saved_frames;
    calibration_throws = true;
    frame_failure({fake.id,0},"surrogate calibration getter failure"); calibration_throws = false;
    frame_fault = "intensity_throw"; frame_failure({fake.id,0},"surrogate intensity failure"); frame_fault.clear();
    for (const auto index : {0u,2u,4u}) {
        const auto request_id = "frame_create_"+std::to_string(index);
        const auto result = execute_frame353({request_id,"FRAME",{fake.id,index}});
        check(nb::valid_json(result) && result.find("\"operation\":\"FRAME\"") != std::string::npos);
        check(result.find("\"dtype_conversion\":{\"input_dtype\":\"uint16\"") != std::string::npos);
        check(result.find("\"output_bytes\":84,\"validation_peak_new_image_bytes\":126") != std::string::npos);
        const auto output_id = last_retained_result353;
        const auto& owned = retained_results.at(output_id);
        auto* output = static_cast<FakeImage*>(owned.value.image);
        check(output->dimensions == 2 && output->code == 2 && output->pixels.size() == 21);
        for (std::size_t i = 0; i < 21; ++i) check(output->pixels[i] == source_pixels[index*21+i]);
        check(fake.pixels == source_pixels && fake.references == 1 && registry.size() == 2);
        check(owned.frame_ancestry.find("\"status\":\"tracked_frame\"") != std::string::npos);
        check(owned.frame_ancestry.find(result) != std::string::npos && owned.frame_ancestry.find("\"retention\"") == std::string::npos);
        const auto decorated = attach_retention353({request_id,"FRAME",{fake.id,index}},result);
        check(decorated.find("\"retention\":{\"token\":") != std::string::npos);
        const auto read = execute_read({"frame_read","READ",{output_id,0,0,7,3}});
        check(read.find("\"frame_ancestry\":"+owned.frame_ancestry) != std::string::npos);
        check(read.find("\"source_provenance\":{\"operation\":\"FRAME\"") != std::string::npos);
        if (index == 2) cross_layer_fixture = "{\"frame_args\":[17,2],\"frame_result\":" + decorated +
            ",\"read_args\":[" + std::to_string(output_id) + ",0,0,7,3],\"read_result\":" + read + '}';
        // Single-parent transformations propagate only the frozen frame identity.
        ImageRef descendant;
        operation_fake(&descendant.value, &owned.value, nullptr, 0);
        const auto descendant_id = api.id(descendant.value.image);
        const auto descendant_metadata = metadata(descendant.value.image,false);
        retain_native_result(descendant,descendant_id,84,{"derived","UNARY",{output_id,1}},"test native unary",
            {output_id},{owned.metadata},descendant_metadata,"test");
        check(retained_results.at(descendant_id).frame_ancestry == owned.frame_ancestry);
        release_image(retained_results.at(descendant_id).value); retained_results.erase(descendant_id); retained_result_bytes -= 84;
        for (const auto* operation : {"BINARY","UNARY"}) {
            ImageRef mixed;
            operation_fake(&mixed.value,&owned.value,nullptr,0);
            const auto mixed_id = api.id(mixed.value.image);
            retain_native_result(mixed,mixed_id,84,{"mixed",operation,{output_id,output_id}},"test operation",
                std::string(operation)=="BINARY" ? std::vector<std::uint32_t>{output_id,output_id} : std::vector<std::uint32_t>{output_id},
                {"changed metadata"},metadata(mixed.value.image,false),"test");
            check(retained_results.at(mixed_id).frame_ancestry == "{\"schema_version\":1,\"status\":\"unresolved_lineage\"}");
            release_image(retained_results.at(mixed_id).value); retained_results.erase(mixed_id); retained_result_bytes -= 84;
        }
        // Changed source calibration cannot retain a seemingly trustworthy frame.
        output->origin[0] += 1;
        const auto changed_read = execute_read({"frame_changed","READ",{output_id,0,0,1,1}});
        check(changed_read.find("\"frame_ancestry\":{\"schema_version\":1,\"status\":\"unresolved_lineage\"}") != std::string::npos);
        output->origin[0] -= 1;
        const auto token = owned.retention_token;
        check(execute_show({"frame_show","SHOW",{output_id}}).find("\"document_visible\":true") != std::string::npos);
        result_lifecycle353({"frame_release","RELEASE",{output_id,token}});
        check(retained_results.empty() && retained_result_bytes == 0 && registry.count(output_id) == 1);
        close_surrogate_documents();
        check(registry.size() == 1 && fake.references == 1);
    }
    fake.unit[0].clear(); fake.unit[1].clear(); frame_unit.clear();
    const auto unitless = execute_frame353({"frame_unitless","FRAME",{fake.id,1}});
    check(unitless.find("\"calibration_complete\":false") != std::string::npos);
    check(unitless.find("\"calibrated_value\":0.1875,\"unit\":null,\"usable\":false") != std::string::npos);
    for (auto& pair : retained_results) release_image(pair.second.value);
    retained_results.clear(); retained_result_bytes = 0;
    fake.unit[0] = fake.unit[1] = L"nm"; frame_unit = L"step";
    frame_scale = 0;
    const auto invalid = execute_frame353({"frame_invalid_axis","FRAME",{fake.id,1}});
    check(invalid.find("\"calibrated_value\":null,\"unit\":\"step\",\"usable\":false") != std::string::npos);
    for (auto& pair : retained_results) release_image(pair.second.value);
    retained_results.clear(); retained_result_bytes = 0; frame_scale = -0.125f;
    const auto saved_xy_scale = fake.scale[0];
    fake.scale[0] = std::numeric_limits<float>::quiet_NaN();
    const auto invalid_xy = execute_frame353({"frame_invalid_xy","FRAME",{fake.id,1}});
    check(invalid_xy.find("\"issue\":\"invalid_calibration\"") != std::string::npos);
    check(invalid_xy.find("\"scale\":null") != std::string::npos);
    for (auto& pair : retained_results) release_image(pair.second.value);
    retained_results.clear(); retained_result_bytes = 0; fake.scale[0] = saved_xy_scale;
    for (const auto& fault : std::vector<std::pair<const char*,const char*>>{
        {"slice_null","native_frame_slice_no_output_reference"}, {"slice_return","native_frame_slice_no_output_reference"},
        {"slice_alias","native_frame_slice_identity_invalid"}, {"slice_rank","native_frame_output_descriptor_mismatch"},
        {"slice_dtype","native_frame_output_descriptor_mismatch"}, {"slice_packing","native_frame_output_descriptor_mismatch"},
        {"slice_size","native_frame_output_descriptor_mismatch"}, {"slice_calibration","native_frame_slice_calibration_mismatch"},
        {"slice_intensity","native_frame_slice_intensity_mismatch"},
        {"slice_throw","surrogate slice failure after owned reference"},
        {"output_null","native_frame_convert_no_output_reference"}, {"output_return","native_frame_convert_no_output_reference"},
        {"output_alias","native_frame_output_identity_invalid"}, {"output_source_alias","native_frame_output_identity_invalid"},
        {"output_rank","native_frame_output_descriptor_mismatch"}, {"output_dtype","native_frame_output_descriptor_mismatch"},
        {"output_packing","native_frame_output_descriptor_mismatch"}, {"output_size","native_frame_output_descriptor_mismatch"},
        {"output_calibration","native_frame_output_calibration_mismatch"}, {"output_intensity","native_frame_output_intensity_mismatch"},
        {"output_throw","surrogate conversion failure after owned reference"},
        {"source_changed","native_frame_source_metadata_changed"}}) {
        frame_fault = fault.first;
        const auto origin = fake.origin[0];
        frame_failure({fake.id,1},fault.second,1,frame_fault.find("output_")==0 || frame_fault == "source_changed" ? 1 : 0);
        fake.origin[0] = origin;
    }
    frame_fault.clear();
    for (const auto* fault : {"slice_invalid_pointer","output_invalid_pointer"}) {
        frame_fault = fault;
        try { execute_frame353({"invalid_abi","FRAME",{fake.id,1}}); check(false); }
        catch (const std::runtime_error& error) { check(std::string(error.what()) == "native_frame_invalid_owned_reference"); }
        check(fatal_abi && fake.references == 1 && retained_results.empty() && registry.size() == 1);
        fatal_abi = false;
    }
    frame_fault.clear();
    // The two-image peak is an admission condition, not only final-output bytes.
    check(nb::frame_plan353(1024,1024,1,0,nb::kCropRetainedBytes-6291456,30).peak_bytes == 6291456);
    for (const auto counts : {31u,32u}) {
        try { nb::frame_plan353(1,1,1,0,0,counts); check(false); }
        catch (const std::runtime_error& error) { check(std::string(error.what())=="native_frame_temporary_object_capacity"); }
    }
    check(fake.pixels == source_pixels && retained_results.empty() && retained_result_bytes == 0 && registry.size() == 1);
}
}
int main(int argc, char** argv) {
    try {
        frame_tests();
        if (argc != 1) {
            if (argc != 3 || std::string(argv[1]) != "--write-fixture" || !nb::valid_json(cross_layer_fixture))
                throw std::runtime_error("expected --write-fixture new_file.json");
            HANDLE file = CreateFileA(argv[2],GENERIC_WRITE,0,nullptr,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,nullptr);
            if (file == INVALID_HANDLE_VALUE) throw std::runtime_error("fixture destination exists or cannot be created");
            DWORD written = 0;
            const auto text = cross_layer_fixture + '\n';
            const bool success = WriteFile(file,text.data(),static_cast<DWORD>(text.size()),&written,nullptr) != 0;
            CloseHandle(file);
            if (!success || written != text.size()) throw std::runtime_error("fixture write failed");
        }
        std::cout << "PASS FRAME surrogate: " << assertions << " assertions; no DM loaded\n"; return 0;
    }
    catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
