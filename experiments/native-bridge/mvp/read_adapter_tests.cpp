// READ boundary and bit-preserving snapshot tests. No vendor DLL is loaded.
#include "read_contract.hpp"
#define main nb_existing_adapter_surrogate_main
#include "adapter_tests.cpp"
#undef main
namespace {

std::string read_field(const std::string& result, const char* name) {
    const auto prefix = std::string("\"")+name+"\":\"";
    const auto begin = result.find(prefix);
    check(begin != std::string::npos);
    const auto start = begin+prefix.size();
    const auto end = result.find('"',start);
    check(end != std::string::npos);
    return result.substr(start,end-start);
}
std::string decode_base64_test(const std::string& encoded) {
    const std::string alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    std::uint32_t accumulator = 0;
    int bits = -8;
    std::string decoded;
    for (const auto byte : encoded) {
        if (byte == '=') break;
        const auto value = alphabet.find(byte);
        check(value != std::string::npos);
        accumulator = (accumulator << 6) | static_cast<std::uint32_t>(value);
        bits += 6;
        if (bits >= 0) {
            decoded.push_back(static_cast<char>((accumulator >> bits) & 255u));
            bits -= 8;
        }
    }
    return decoded;
}
std::string read_fault;
double read_point_fake(const void* image, const nb::NativeDataIndex2D353* index) {
    if (read_fault == "inexact") { ++point_calls; return 0.1; }
    if (read_fault == "overflow") { ++point_calls; return std::numeric_limits<double>::max(); }
    if (read_fault == "infinite") { ++point_calls; return std::numeric_limits<double>::infinity(); }
    if (read_fault == "throw") { ++point_calls; throw std::runtime_error("read surrogate point failure"); }
    return point_fake(image,index);
}
void read_failure(std::vector<std::uint32_t> args, const char* expected, int expected_points = 0) {
    const auto references = fake.references;
    const auto previous_points = point_calls;
    const auto pool_size = retained_results.size();
    const auto pool_bytes = retained_result_bytes;
    std::string message;
    try { execute_read({"read_failure","READ",std::move(args)}); }
    catch (const std::runtime_error& error) { message = error.what(); }
    if (message != expected) throw std::runtime_error(std::string("READ expected ")+expected+", received "+message);
    check(point_calls == previous_points+expected_points && fake.references == references);
    check(retained_results.size() == pool_size && retained_result_bytes == pool_bytes);
}
void read_tests() {
    inject_fake();
    fake.width = 4; fake.height = 2; fake.pixels = {-0.0f,0.0f,-2.5f,1.25f,3.75f,-8.0f,11.0f,-0.5f};
    api.real_value = read_point_fake;
    read_failure({17,0,0,1},"native_read_requires_image_id_and_rect");
    api.real_value = nullptr;
    read_failure({17,0,0,1,1},"native_read_symbol_unavailable");
    api.real_value = read_point_fake;
    api.packing = nullptr;
    read_failure({17,0,0,1,1},"native_read_packing_unavailable");
    api.packing = packing_fake;
    calibration_throws = true;
    read_failure({17,0,0,1,1},"surrogate calibration getter failure");
    calibration_throws = false;
    read_failure({99,0,0,1,1},"image_not_found");
    fake.code = 10;
    read_failure({17,0,0,1,1},"native_read_requires_float32_2d_ordinary_packing"); fake.code = 2;
    fake.packing = 2;
    read_failure({17,0,0,1,1},"native_read_requires_float32_2d_ordinary_packing"); fake.packing = 1;
    for (const auto& rect : std::vector<std::vector<std::uint32_t>>{
            {17,0,0,0,1},{17,1,0,0,1},{17,0,0,5,1},{17,0,0,1,3}})
        read_failure(rect,"native_read_rect_out_of_bounds_or_empty");
    const auto before_points = point_calls;
    const auto result = execute_read({"read_roi","READ",{17,0,0,3,2}});
    check(nb::valid_json(result) && point_calls == before_points+6 && fake.references == 1);
    const unsigned char golden[] = {0,0,0,128,0,0,0,0,0,0,32,192,0,0,112,64,0,0,0,193,0,0,48,65};
    const auto bytes = decode_base64_test(read_field(result,"values_base64"));
    check(bytes == std::string(reinterpret_cast<const char*>(golden),sizeof(golden)));
    check(result.find("\"shape\":[2,3]") != std::string::npos && result.find("\"raw_bytes\":24") != std::string::npos);
    check(result.find("\"source_provenance\":null") != std::string::npos && retained_results.empty());
    check(result.find("\"source_offset\":0") != std::string::npos && result.find("\"array_order\":\"C\"") != std::string::npos);
    const auto shifted = execute_read({"read_shifted","READ",{17,1,1,4,2}});
    check(shifted.find("\"source_offset\":1,\"source_origin\":5") != std::string::npos);
    check(shifted.find("\"origin\":4,\"calibrated_value_at_pixel_zero\":1") != std::string::npos);
    check(shifted.find("\"origin\":4,\"calibrated_value_at_pixel_zero\":-2") != std::string::npos);
    fake.pixels[0] = 42;
    const auto changed = execute_read({"read_changed_source","READ",{17,0,0,3,2}});
    check(read_field(changed,"values_base64") != read_field(result,"values_base64"));
    check(decode_base64_test(read_field(result,"values_base64")) == bytes); // prior response owns fixed values
    fake.pixels[0] = -0.0f;
    for (const auto& fault : std::vector<std::pair<const char*,const char*>>{
            {"inexact","native_read_value_not_exact_float32"},{"overflow","native_read_value_not_exact_float32"},
            {"infinite","native_read_nonfinite_sample"},{"throw","read surrogate point failure"}}) {
        read_fault = fault.first;
        read_failure({17,0,0,1,1},fault.second,1);
    }
    read_fault.clear();
    fake.pixels[0] = std::numeric_limits<float>::quiet_NaN();
    read_failure({17,0,0,1,1},"native_read_nonfinite_sample",1); fake.pixels[0] = -0.0f;
    preview_fault = "source_changed";
    const auto saved_origin = fake.origin[0];
    read_failure({17,0,0,3,2},"native_read_source_metadata_changed",6);
    fake.origin[0] = saved_origin; preview_fault.clear();
    fake.unit[1].clear();
    const auto unitless = execute_read({"read_unitless","READ",{17,0,0,1,1}});
    check(unitless.find("\"calibration_complete\":false") != std::string::npos);
    check(unitless.find("\"unit\":null,\"usable\":false,\"issue\":\"unknown_units\"") != std::string::npos);
    fake.unit[1] = L"nm";
    fake.scale[0] = 0;
    const auto badcal = execute_read({"read_invalid_cal","READ",{17,0,0,1,1}});
    check(badcal.find("\"origin\":null,\"calibrated_value_at_pixel_zero\":null") != std::string::npos);
    check(badcal.find("\"issue\":\"invalid_calibration\"") != std::string::npos);
    fake.scale[0] = -0.25f;

    InterlockedIncrement64(&fake.references);
    retained_results.emplace(fake.id,RetainedResult{NativeRef{&fake},32,ResultKind::Unary,2,"UNARY","original-create",
        "GMSImageProcessing::Negate",{99},{"{}"},"{}","immutable raw negate record"});
    retained_result_bytes = 32;
    const auto provenance = execute_read({"read_provenance","READ",{17,0,0,1,1}});
    check(provenance.find("\"source_provenance\":{\"operation\":\"UNARY\",\"request_id\":\"original-create\",\"source_image_ids\":[99],\"semantics\":\"immutable raw negate record\"}") != std::string::npos);
    FakeImage foreign;
    retained_results.at(fake.id).value.image = &foreign;
    read_failure({17,0,0,1,1},"native_read_source_provenance_identity_mismatch");
    retained_results.at(fake.id).value.image = &fake;
    release_image(retained_results.at(fake.id).value); retained_results.clear(); retained_result_bytes = 0;
    check(fake.references == 1);

    fake.width = 129; fake.height = 128;
    read_failure({17,0,0,129,128},"native_read_roi_over_budget");
    fake.width = 128;
    fake.pixels.assign(16384,1.0f);
    const auto max_before = point_calls;
    const auto maximum = execute_read({"read_max","READ",{17,0,0,128,128}});
    const auto max_encoded = read_field(maximum,"values_base64");
    check(max_encoded.size() == 87384 && decode_base64_test(max_encoded).size() == 65536);
    check(maximum.size() <= nb::kMaxReply-2048 && point_calls == max_before+16384);
    // The callback exposes only the requested point. No full source array read
    // or allocation is required for a one-pixel ROI in the maximum source shape.
    fake.width = 4194304; fake.height = 1; fake.pixels.assign(1,1.0f);
    const auto bounded_before = point_calls;
    check(nb::valid_json(execute_read({"read_large_source_small_roi","READ",{17,0,0,1,1}})));
    check(point_calls == bounded_before+1);
    fake.width = 4194305;
    read_failure({17,0,0,1,1},"native_read_source_over_budget");

    check(nb::read_float32_bits353(-0.0) == 0x80000000u);
    check(nb::read_float32_bits353(+0.0) == 0u);
    for (const auto bits : {1u,0x007fffffu,0x00800000u,0x3f800000u,0x7f7fffffu,0x80000001u}) {
        float value = 0;
        std::memcpy(&value,&bits,sizeof(value));
        check(nb::read_float32_bits353(static_cast<double>(value)) == bits);
    }
    check(nb::read_base64_353("") == "");
    check(nb::read_base64_353("f") == "Zg==" && nb::read_base64_353("fo") == "Zm8=");
    check(nb::read_base64_353("foo") == "Zm9v" && nb::read_base64_353("foobar") == "Zm9vYmFy");
    check(fake.references == 1 && retained_results.empty() && registry.size() == 1 && !fatal_abi);
}
}
int main() {
    try {
        read_tests();
        std::cout << "PASS READ surrogate: " << assertions << " assertions; finite exact binary32/signed-zero/ROI/provenance/bounded bytes; no DM loaded\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n'; return 1;
    }
}
