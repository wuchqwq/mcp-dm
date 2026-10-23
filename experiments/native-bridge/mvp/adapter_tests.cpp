// Deterministic ownership/ABI-shim guard tests. No vendor DLL is loaded.
// Including the implementation injects C-shaped surrogates only in this EXE.
#include "dm_adapter.cpp"
#include <cstdlib>
#include <iostream>
#include <limits>
#include <memory>

namespace {
struct FakeImage {
    LONG64 references = 1;
    std::uint32_t id = 17, width = 11, height = 7, code = 2, dimensions = 2;
    float origin[2] = {5, 5}, scale[2] = {-0.25f, 0.5f};
    std::wstring unit[2] = {L"nm", L"nm"};
    std::vector<float> pixels;
    bool generated = false;
} fake;
std::map<std::uint32_t, FakeImage*> registry;
std::uint32_t next_image_id = 100, last_output_id = 0;
int crop_calls = 0;
std::string crop_fault;
int releases = 0, destructions = 0, assertions = 0;
bool invalid_scale = false;
double expected_mean = -24.375;
void check(bool value) { ++assertions; if (!value) throw std::runtime_error("adapter assertion"); }
void fill(MsvcWString353* out, const std::wstring& text) {
    *out = MsvcWString353{};
    out->length = text.size();
    if (text.size() <= 7) {
        for (std::size_t i = 0; i < text.size(); ++i) out->storage.small[i] = text[i];
    } else {
        out->capacity = text.size();
        auto bytes = (text.size() + 1) * sizeof(wchar_t);
        auto raw = static_cast<unsigned char*>(std::malloc(bytes + 40));
        if (!raw) throw std::bad_alloc();
        auto data = bytes < 4096 ? reinterpret_cast<wchar_t*>(raw)
            : reinterpret_cast<wchar_t*>((reinterpret_cast<std::uintptr_t>(raw + 39)) & ~std::uintptr_t(31));
        if (bytes >= 4096) reinterpret_cast<void**>(data)[-1] = raw;
        out->storage.heap = data;
        for (std::size_t i = 0; i <= text.size(); ++i) data[i] = text.c_str()[i];
    }
}
NativeRef* find_fake(NativeRef* out, std::uint32_t id) {
    out->image = nullptr;
    const auto found = registry.find(id);
    if (found != registry.end()) { InterlockedIncrement64(&found->second->references); out->image = found->second; }
    return out;
}
NativeRef* index_fake(NativeRef* out, std::uint32_t index) {
    out->image = nullptr;
    if (index >= registry.size()) return out;
    auto entry = registry.begin(); std::advance(entry, index);
    InterlockedIncrement64(&entry->second->references); out->image = entry->second; return out;
}
std::uint32_t count_fake() { return static_cast<std::uint32_t>(registry.size()); }
std::uint32_t id_fake(const void* image) { return static_cast<const FakeImage*>(image)->id; }
std::uint32_t ndim_fake(const void* image) { return static_cast<const FakeImage*>(image)->dimensions; }
std::uint32_t dtype_fake(const void* image) { return static_cast<const FakeImage*>(image)->code; }
std::uint32_t dimension_fake(const void* image, std::int32_t dim) {
    const auto* data = static_cast<const FakeImage*>(image); return dim == 0 ? data->width : data->height;
}
MsvcWString353* name_fake(const void*, MsvcWString353* out) { fill(out, L"synthetic ownership test"); return out; }
void calibration_fake(void* image, std::uint32_t dim, float* origin, float* scale, void* unit, std::int32_t format) {
    auto* data = static_cast<FakeImage*>(image);
    *scale = invalid_scale ? 0 : data->scale[dim];
    *origin = format == 0 ? -(data->scale[dim] * data->origin[dim]) : data->origin[dim];
    if (unit) fill(static_cast<MsvcWString353*>(unit), data->unit[dim]);
}
double mean_fake(const NativeRef* ref) {
    const auto* image = static_cast<const FakeImage*>(ref->image);
    if (!image->generated) { check(ref->image == &fake); return expected_mean; }
    double sum = 0;
    for (float value : image->pixels) sum += value;
    return sum / image->pixels.size();
}
void delete_fake(void* pointer) {
    ++destructions;
    auto* image = static_cast<FakeImage*>(pointer);
    if (image->generated) { registry.erase(image->id); delete image; }
}
NativeRef* crop_fake(const void* pointer, NativeRef* out, const nb::NativeDataSlice353* slice) {
    ++crop_calls;
    const auto* source = static_cast<const FakeImage*>(pointer);
    if (crop_fault == "empty") { out->image = nullptr; return out; }
    if (crop_fault == "alias") {
        out->image = const_cast<FakeImage*>(source);
        InterlockedIncrement64(&static_cast<FakeImage*>(out->image)->references); return out;
    }
    auto created = std::make_unique<FakeImage>();
    created->generated = true; created->id = next_image_id++;
    created->width = static_cast<std::uint32_t>(slice->output_axes[0].length);
    created->height = static_cast<std::uint32_t>(slice->output_axes[1].length);
    for (unsigned d = 0; d < 2; ++d) {
        created->origin[d] = source->origin[d] - static_cast<float>(slice->source_start[d]);
        created->scale[d] = source->scale[d]; created->unit[d] = source->unit[d];
    }
    for (std::uint32_t y = 0; y < created->height; ++y)
        for (std::uint32_t x = 0; x < created->width; ++x) {
            const auto index = static_cast<std::size_t>(y + slice->source_start[1]) * source->width + x + slice->source_start[0];
            created->pixels.push_back(source->pixels.at(index));
        }
    if (crop_fault == "dtype") created->code = 10;
    if (crop_fault == "size") ++created->width;
    if (crop_fault == "calibration") created->origin[0] += 1;
    if (crop_fault == "unit") created->unit[1] = L"pm";
    if (crop_fault == "source_changed") const_cast<FakeImage*>(source)->origin[0] += 1;
    last_output_id = created->id;
    registry.emplace(created->id, created.get()); out->image = created.release();
    if (crop_fault == "own_exception") throw std::runtime_error("surrogate allocation failure");
    return crop_fault == "return_pointer" ? nullptr : out;
}
void free_fake(void* ptr) { ++releases; std::free(ptr); }
void inject_fake() {
    api.find_id = find_fake; api.id = id_fake; api.ndim = ndim_fake;
    api.find_index = index_fake; api.count = count_fake; api.crop = crop_fake;
    api.dtype = dtype_fake; api.dimension = dimension_fake;
    api.calibration = calibration_fake; api.name = name_fake;
    api.mean = mean_fake; api.destroy = delete_fake; api.deallocate = free_fake;
    host_thread = GetCurrentThreadId(); gate_error.clear(); fatal_abi = false;
    registry.emplace(fake.id, &fake);
}
void expect_crop_failure(std::vector<std::uint32_t> args, const std::string& message) {
    try { execute_native({"crop_failure", "CROP", std::move(args)}); check(false); }
    catch (const std::runtime_error& e) { check(e.what() == message); }
    check(fake.references == 1 && retained_crops.empty() && retained_crop_bytes == 0);
    check(registry.size() == 1);
}
void crop_tests() {
    inject_fake(); invalid_scale = false;
    fake.width = 5; fake.height = 4;
    fake.origin[0] = 3.25f; fake.origin[1] = -2.5f;
    fake.scale[0] = -0.125f; fake.scale[1] = 0.5f;
    fake.pixels = {-4.5f,-3.25f,-2.0f,-0.75f,0.5f,
                    1.75f,3.0f,4.25f,5.5f,6.75f,
                    8.0f,9.25f,10.5f,11.75f,13.0f,
                    14.25f,15.5f,16.75f,18.0f,19.25f};
    const auto original = fake.pixels;
    const auto plan = nb::crop_plan(5, 4, {1,1,4,3}, 0, 0);
    check(plan.width == 3 && plan.height == 2 && plan.bytes == 24);
    check(plan.slice.source_dimensions == 2 && plan.slice.output_dimensions == 2);
    check(plan.slice.source_start[0] == 1 && plan.slice.source_start[1] == 1);
    check(plan.slice.output_axes[0].source_dimension == 0 && plan.slice.output_axes[0].length == 3 && plan.slice.output_axes[0].step == 1);
    check(plan.slice.output_axes[1].source_dimension == 1 && plan.slice.output_axes[1].length == 2 && plan.slice.output_axes[1].step == 1);
    check(plan.slice.source_start[4] == 0 && plan.slice.output_axes[4].length == 0);
    auto response = execute_native({"crop_ok", "CROP", {fake.id,1,1,4,3}});
    check(nb::valid_json(response));
    check(response.find("\"requested_rect\":[1,1,4,3]") != std::string::npos);
    check(response.find("\"effective_rect\":[1,1,4,3]") != std::string::npos);
    check(response.find("GMS::Image::GetSubSliceAsImage") != std::string::npos);
    check(response.find("\"visible_dm_document\":false") != std::string::npos);
    check(response.find("\"source_write_requested\":false") != std::string::npos);
    check(response.find("source_mutated") == std::string::npos);
    check(fake.pixels == original && fake.origin[0] == 3.25f && fake.origin[1] == -2.5f);
    check(retained_crops.size() == 1 && retained_crop_bytes == 24 && fake.references == 1);
    const auto cropped_id = last_output_id;
    const auto* cropped = registry.at(cropped_id);
    // Hand-enumerated oracle: source rows y=1,2 and columns x=1,2,3.
    check(cropped->pixels == std::vector<float>({3,4.25f,5.5f,9.25f,10.5f,11.75f}));
    check(cropped->references == 1 && cropped->pixels.data() != fake.pixels.data());
    check(cropped->origin[0] == 2.25f && cropped->origin[1] == -3.5f);
    check(-(cropped->origin[0] * cropped->scale[0]) == 0.28125f);
    check(-(cropped->origin[1] * cropped->scale[1]) == 1.75f);
    const auto mean = execute_native({"cropped_mean", "MEAN", {cropped_id}});
    check(mean.find("\"mean\":7.375") != std::string::npos);
    check(registry.at(cropped_id)->references == 1);
    const auto info = execute_native({"cropped_info", "INFO", {cropped_id}});
    check(info.find("\"dm_dimensions\":[3,2]") != std::string::npos);
    const auto datasets = execute_native({"cropped_list", "DATASETS", {}});
    check(datasets.find("\"count\":2") != std::string::npos);
    shutdown_native();
    check(retained_crops.empty() && retained_crop_bytes == 0 && registry.size() == 1 && fake.references == 1);
    inject_fake();
    try { execute_native({"released", "INFO", {cropped_id}}); check(false); }
    catch (const std::runtime_error& e) { check(std::string(e.what()) == "image_not_found"); }

    const auto calls_before_rejections = crop_calls;
    expect_crop_failure({fake.id,1,1,1,3}, "native_crop_empty_or_reversed_rect");
    expect_crop_failure({fake.id,4,1,2,3}, "native_crop_empty_or_reversed_rect");
    expect_crop_failure({fake.id,0,0,6,4}, "native_crop_rect_out_of_bounds");
    fake.width = fake.height = 2048;
    expect_crop_failure({fake.id,0,0,1025,1024}, "native_crop_output_over_budget");
    fake.width = 20000000; fake.height = 4;
    expect_crop_failure({fake.id,16777217,0,16777218,1}, "native_crop_offset_not_exact_float32");
    fake.width = 5; fake.height = 4; fake.code = 10;
    expect_crop_failure({fake.id,1,1,4,3}, "native_crop_requires_float32_2d");
    fake.code = 2;
    check(crop_calls == calls_before_rejections);

    const std::pair<const char*, const char*> faults[] = {
        {"empty", "native_crop_no_output_reference"}, {"alias", "native_crop_output_identity_invalid"},
        {"dtype", "native_crop_output_descriptor_mismatch"}, {"size", "native_crop_output_descriptor_mismatch"},
        {"calibration", "native_crop_output_calibration_mismatch"}, {"unit", "native_crop_output_calibration_mismatch"},
        {"return_pointer", "native_crop_no_output_reference"}, {"own_exception", "surrogate allocation failure"},
        {"source_changed", "native_crop_source_descriptor_changed"}
    };
    for (const auto& fault : faults) {
        crop_fault = fault.first;
        const auto destroyed_before = destructions;
        expect_crop_failure({fake.id,1,1,4,3}, fault.second);
        if (crop_fault != "empty" && crop_fault != "alias") check(destructions == destroyed_before + 1);
        else check(destructions == destroyed_before);
        fake.origin[0] = 3.25f;
    }
    crop_fault.clear();
    for (unsigned i = 0; i < nb::kCropRetainedCount; ++i)
        execute_native({"retained_small", "CROP", {fake.id,0,0,1,1}});
    check(retained_crops.size() == 32 && retained_crop_bytes == 128);
    const auto count_full_calls = crop_calls;
    try { execute_native({"count_full", "CROP", {fake.id,0,0,1,1}}); check(false); }
    catch (const std::runtime_error& e) { check(std::string(e.what()) == "native_crop_retention_capacity"); }
    check(crop_calls == count_full_calls && fake.references == 1);
    shutdown_native(); check(registry.size() == 1 && retained_crop_bytes == 0);

    inject_fake(); fake.width = fake.height = 1024;
    fake.pixels.assign(1024 * 1024, -0.25f);
    for (unsigned i = 0; i < 4; ++i)
        execute_native({"retained_large", "CROP", {fake.id,0,0,1024,1024}});
    check(retained_crops.size() == 4 && retained_crop_bytes == nb::kCropRetainedBytes);
    const auto bytes_full_calls = crop_calls;
    try { execute_native({"bytes_full", "CROP", {fake.id,0,0,1,1}}); check(false); }
    catch (const std::runtime_error& e) { check(std::string(e.what()) == "native_crop_retained_bytes_over_budget"); }
    check(crop_calls == bytes_full_calls && fake.references == 1);
    shutdown_native(); check(registry.size() == 1 && retained_crops.empty() && retained_crop_bytes == 0);

    // Cancellation near zero needs propagated float32 ULPs, not relative epsilon.
    const auto cancellation = nb::crop_zero_check(0.3f, -0.1f, 3.0f, 3, 0.0f);
    check(cancellation.expected != 0 && cancellation.absolute_error <= cancellation.tolerance);
    const auto wrong_zero = nb::crop_zero_check(0.40625f, -0.125f, 3.25f, 1, 0.29f);
    check(wrong_zero.absolute_error > wrong_zero.tolerance);
}
}
int main() {
    try {
        inject_fake();
        for (int i = 0; i < 200; ++i) {
            auto result = execute_native({"mean", "MEAN", {fake.id}});
            check(nb::valid_json(result));
            check(result.find("\"mean\":-24.375") != std::string::npos);
            check(fake.references == 1 && destructions == 0);
        }
        check(releases == 200);
        try { execute_native({"missing", "INFO", {99}}); check(false); }
        catch (const std::runtime_error& e) { check(std::string(e.what()) == "image_not_found"); }
        check(fake.references == 1 && destructions == 0);
        invalid_scale = true;
        try { execute_native({"badcal", "MEAN", {fake.id}}); check(false); }
        catch (const std::runtime_error& e) { check(std::string(e.what()) == "invalid_image_calibration"); }
        check(fake.references == 1 && releases == 201);
        auto partial = metadata(&fake, false);
        check(nb::valid_json(partial));
        check(partial.find("\"calibration_complete\":false") != std::string::npos);
        check(partial.find("\"native_mean_supported\":false") != std::string::npos);
        invalid_scale = false; expected_mean = std::numeric_limits<double>::infinity();
        try { execute_native({"badmean", "MEAN", {fake.id}}); check(false); }
        catch (const std::runtime_error& e) { check(std::string(e.what()) == "native_mean_nonfinite_result"); }
        check(fake.references == 1 && releases == 203);
        {
            VendorString large;
            fill(&large.value, std::wstring(2500, L'x'));
            check(large.utf8(2500) == std::string(2500, 'x'));
        }
        check(releases == 204 && !fatal_abi);
        {
            VendorString unicode;
            fill(&unicode.value, L"\u4e2d\u6587\u00b5m");
            check(unicode.utf8(10) == "\xe4\xb8\xad\xe6\x96\x87\xc2\xb5m");
        }
        {
            VendorString malformed;
            malformed.value.length = 9; malformed.value.capacity = 8;
        }
        check(fatal_abi && releases == 204);
        try { execute_native({"disabled", "INFO", {fake.id}}); check(false); }
        catch (const std::runtime_error& e) { check(std::string(e.what()) == "native_abi_invalid_output_path_disabled"); }
        check(fake.references == 1);
        crop_tests();
        std::cout << "PASS adapter surrogate: " << assertions << " assertions; no DM loaded\n";
        return 0;
    } catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}
