// Coordinate admission/ownership and exact metadata surrogates only. No DM,
// vendor library or live pipe is loaded; callbacks do not prove FFT science.
#define main existing_adapter_test_main
#include "adapter_tests.cpp"
#undef main
#include <fstream>

namespace {
std::vector<std::string> packets;
void packet(const NativeRequest& request, const std::string& result) {
    std::string args;
    for (auto value : request.args) { if (!args.empty()) args += ','; args += std::to_string(value); }
    packets.push_back("{\"operation\":" + nb::quote(request.op) + ",\"args\":[" + args +
        "],\"result_version\":" + std::to_string(nb::operation_contract(request.op)->result_version) +
        ",\"result\":" + result + '}');
}
template<class Function> void pixel_fails(Function function, const char* expected) {
    std::string actual;
    try { function(); } catch (const std::runtime_error& error) { actual = error.what(); }
    if (actual != expected) throw std::runtime_error("pixel expected " + std::string(expected) + ", received " + actual);
    check(fake.references == 1 && !fatal_abi);
}
NativeRef* pixel_crop_fake(const void* source, NativeRef* out, const nb::NativeDataSlice353* slice) {
    auto* result = crop_fake(source,out,slice);
    if (out->image && out->image != source && crop_fault.empty())
        static_cast<FakeImage*>(out->image)->code = static_cast<const FakeImage*>(source)->code;
    return result;
}
NativeRef* pixel_filter_fake(NativeRef* out, const NativeRef* source, bool floating) {
    auto* result = filter_fake(out,source);
    if (floating && out->image && operation_fault.empty()) static_cast<FakeImage*>(out->image)->code = 2;
    return result;
}
NativeRef* pixel_sobel_fake(NativeRef* out, const NativeRef* source) { return pixel_filter_fake(out,source,true); }
void clear_pixel_results() {
    for (auto& item : retained_results) release_image(item.second.value);
    retained_results.clear(); retained_result_bytes = 0;
    check(registry.size() == 1 && fake.references == 1);
}
void pixel_tests() {
    inject_fake(); operation_tracking = true;
    fake.width = fake.height = 8; fake.pixels.resize(64);
    for (unsigned i = 0; i < 64; ++i) fake.pixels[i] = static_cast<float>(i) - 31.25f;
    const auto original = fake.pixels;
    fake.unit[0].clear(); fake.unit[1].clear();
    api.crop = pixel_crop_fake; api.sobel_filter = api.laplace_filter = pixel_sobel_fake;
    // Exercise declared production admission; a separately unqualified profile
    // is independently refused in profile/dispatcher tests before vendor calls.
    for (const auto* name : {"native_pixel_crop","native_pixel_filters","native_pixel_fft"})
        check(qualified_capability353(name));
    std::uint32_t admitted_fft=0;
    for (const auto* op : {"CROP_PIXEL","FILTER_PIXEL","FFT_PIXEL","IFFT_PIXEL","REAL_PIXEL","IMAG_PIXEL","VENDOR_ARG_PIXEL","VENDOR_NORM_PIXEL"}) {
        NativeRequest request{std::string("admitted_")+op,op,{17}};
        if (request.op == "CROP_PIXEL") request.args = {17,0,0,4,4};
        else if (request.op == "FILTER_PIXEL") request.args = {17,1};
        else if (request.op != "FFT_PIXEL") request.args = {admitted_fft};
        const auto admitted=execute_native(request);
        check(admitted.find("\"coordinate_mode\":\"pixel\"")!=std::string::npos);
        check(admitted.find("\"retention\":{\"token\":")!=std::string::npos);
        if (request.op == "FFT_PIXEL") admitted_fft=last_retained_result353;
    }
    clear_pixel_results();
    const auto before = operation_calls + crop_calls;
    pixel_fails([] { execute_crop({"old_crop","CROP",{17,1,2,5,6}}); },"unknown_image_units");
    pixel_fails([] { execute_filter({"old_filter","FILTER",{17,1}}); },"unknown_image_units");
    pixel_fails([] { execute_fft({"old_fft","FFT",{17}}); },"native_crop_requires_valid_calibration");
    check(operation_calls + crop_calls == before);
    NativeRequest crop{"pixel_crop","CROP_PIXEL",{17,1,2,5,6}};
    auto result = attach_retention353(crop,execute_crop(crop)); packet(crop,result);
    auto crop_id = last_retained_result353;
    auto* cropped = static_cast<FakeImage*>(retained_results.at(crop_id).value.image);
    check(result.find("\"coordinate_mode\":\"pixel\"") != std::string::npos);
    check(result.find("\"calibration_complete\":false") != std::string::npos);
    check(retained_results.at(crop_id).kind == ResultKind::Crop);
    for (unsigned y=0;y<4;++y) for (unsigned x=0;x<4;++x)
        check(cropped->pixels[y*4+x] == original[(y+2)*8+x+1]);
    clear_pixel_results();
    // These calls deliberately exercise only the implementation callbacks;
    // unlike shipping dispatch they do not grant real-host qualification.
    for (const auto code : {2u,11u}) {
        fake.code = code;
        if (code == 11) for (unsigned i=0;i<64;++i) fake.pixels[i]=static_cast<float>(i);
        const auto typed_source=fake.pixels;
        for (unsigned kind=1;kind<=4;++kind) {
            NativeRequest filter{"pixel_filter_"+std::to_string(code)+'_'+std::to_string(kind),"FILTER_PIXEL",{17,kind}};
            result=attach_retention353(filter,execute_filter(filter)); packet(filter,result);
            check(result.find("\"coordinate_mode\":\"pixel\"") != std::string::npos);
            check(result.find("\"calibration_complete\":false") != std::string::npos);
            check(fake.pixels == typed_source);
            clear_pixel_results();
        }
        NativeRequest typed_crop{"typed_crop_"+std::to_string(code),"CROP_PIXEL",{17,0,0,4,4}};
        result=attach_retention353(typed_crop,execute_crop(typed_crop)); packet(typed_crop,result);
        check(retained_results.at(last_retained_result353).data_type_code == code); clear_pixel_results();
    }
    fake.code=2; fake.pixels=original;
    NativeRequest fft{"pixel_fft","FFT_PIXEL",{17}};
    result=attach_retention353(fft,execute_fft(fft)); packet(fft,result);
    const auto fft_id=last_retained_result353;
    check(result.find("\"physical_frequency_step\":null") != std::string::npos);
    check(result.find("\"unit\":\"cycles_per_pixel\"") != std::string::npos);
    check(result.find("\"frequency_at_index_zero\":-0.5") != std::string::npos);
    const auto transform_before=operation_calls;
    pixel_fails([&] { execute_fft({"wrong_mode","IFFT",{fft_id}}); },"native_fft_coordinate_mode_mismatch");
    check(operation_calls==transform_before);
    std::uint32_t real_id=0;
    for (const auto* op : {"REAL_PIXEL","IMAG_PIXEL","VENDOR_ARG_PIXEL","VENDOR_NORM_PIXEL","IFFT_PIXEL"}) {
        NativeRequest derived{std::string("pixel_")+op,op,{fft_id}};
        result=attach_retention353(derived,execute_fft(derived)); packet(derived,result);
        const auto id=last_retained_result353;
        if (derived.op == "REAL_PIXEL") real_id=id;
        if (derived.op == "IFFT_PIXEL") {
            NativeRequest inverse_real{"pixel_inverse_real","REAL_PIXEL",{id}};
            result=attach_retention353(inverse_real,execute_fft(inverse_real)); packet(inverse_real,result);
            NativeRequest read{"pixel_inverse_read","READ",{last_retained_result353,0,0,2,2}};
            packet(read,execute_read(read));
        }
    }
    NativeRequest tracked_crop{"pixel_frequency_crop","CROP_PIXEL",{real_id,1,1,7,7}};
    result=attach_retention353(tracked_crop,execute_crop(tracked_crop)); packet(tracked_crop,result);
    crop_id=last_retained_result353;
    check(retained_results.at(crop_id).scientific_operation == "REAL_PIXEL");
    check(retained_results.at(crop_id).scientific_offset[0] == 1);
    NativeRequest tracked_filter{"pixel_frequency_smooth","FILTER_PIXEL",{crop_id,1}};
    result=attach_retention353(tracked_filter,execute_filter(tracked_filter)); packet(tracked_filter,result);
    NativeRequest read{"pixel_frequency_read","READ",{last_retained_result353,1,1,3,4}};
    packet(read,execute_read(read));
    check(fake.pixels==original);
    clear_pixel_results();
    calibration_throws=true;
    const auto no_call=operation_calls+crop_calls;
    pixel_fails([] { execute_filter({"getter_failure","FILTER_PIXEL",{17,1}}); },"surrogate calibration getter failure");
    calibration_throws=false; fake.scale[0]=0;
    pixel_fails([] { execute_crop({"zero_scale","CROP_PIXEL",{17,0,0,4,4}}); },"native_crop_requires_valid_calibration");
    pixel_fails([] { execute_fft({"zero_fft_scale","FFT_PIXEL",{17}}); },"native_crop_requires_valid_calibration");
    check(operation_calls+crop_calls==no_call); fake.scale[0]=-0.25f;
    for (const auto bad:{std::numeric_limits<float>::quiet_NaN(),std::numeric_limits<float>::infinity()}) {
        fake.scale[0]=bad;
        pixel_fails([] { execute_filter({"invalid_numeric","FILTER_PIXEL",{17,1}}); },"native_crop_requires_valid_calibration");
        pixel_fails([] { execute_fft({"invalid_numeric_fft","FFT_PIXEL",{17}}); },"native_crop_requires_valid_calibration");
    }
    fake.scale[0]=-0.25f;check(operation_calls+crop_calls==no_call);
    fake.packing=2;
    pixel_fails([] { execute_crop({"packed","CROP_PIXEL",{17,0,0,4,4}}); },"native_pixel_crop_requires_ordinary_packing");
    fake.packing=1;fake.code=3;
    pixel_fails([] { execute_crop({"complex_copy","CROP_PIXEL",{17,0,0,4,4}}); },"native_crop_requires_float32_2d");
    fake.code=2;check(operation_calls+crop_calls==no_call);
    operation_fault="calibration";
    pixel_fails([] { execute_filter({"bad_output","FILTER_PIXEL",{17,1}}); },"native_filter_output_calibration_mismatch");
    operation_fault.clear();
    crop_fault="unit";
    pixel_fails([] { execute_crop({"bad_units","CROP_PIXEL",{17,0,0,4,4}}); },"native_crop_output_calibration_mismatch");
    crop_fault.clear();
    check(retained_results.empty() && retained_result_bytes==0 && registry.size()==1 && fake.pixels==original);
}
}
int main(int argc,char** argv) {
    try {
        pixel_tests();
        if (argc != 1) {
            if (argc != 2) throw std::runtime_error("expected optional new fixture path");
            const auto destination=CreateFileA(argv[1],GENERIC_WRITE,0,nullptr,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,nullptr);
            if (destination==INVALID_HANDLE_VALUE) throw std::runtime_error("fixture path exists or cannot be created");
            std::string output="[";
            for (const auto& value:packets) { if (output.size()>1) output+=','; output+=value; }
            output+="]\n"; DWORD written=0;
            const auto success=WriteFile(destination,output.data(),static_cast<DWORD>(output.size()),&written,nullptr);
            CloseHandle(destination);
            if (!success || written!=output.size()) throw std::runtime_error("fixture write failed");
        }
        std::cout << "PASS pixel mode surrogates: " << assertions << " assertions; no DM loaded\n";
        return 0;
    } catch (const std::exception& error) { std::cerr << error.what() << '\n';return 1; }
}
