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
bool calibration_throws = false, mean_throws = false;
int mean_calls = 0;
double expected_mean = -24.375;
struct FakeDocument { void* marker = nullptr; LONG64 references = 1; FakeImage* image = nullptr; };
struct FakeWindow { unsigned char prefix[0x50]{}; LONG64 references = 1; };
static_assert(offsetof(FakeDocument, references) == 8);
static_assert(offsetof(FakeWindow, references) == nb::kNativeWindowReferenceOffset353);
std::map<std::uint32_t, FakeDocument*> host_documents;
std::map<std::uint32_t, FakeWindow*> host_windows;
std::vector<nb::ScriptImageDocument353*> malformed_holders;
std::vector<FakeWindow*> malformed_windows;
int document_calls = 0, show_calls = 0, holder_destructions = 0, window_destructions = 0;
std::string show_fault;
void check_at(bool value, int line) {
    ++assertions;
    if (!value) throw std::runtime_error("adapter assertion at line " + std::to_string(line));
}
#define check(value) check_at((value), __LINE__)
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
    if (calibration_throws) throw std::runtime_error("surrogate calibration getter failure");
    auto* data = static_cast<FakeImage*>(image);
    *scale = invalid_scale ? 0 : data->scale[dim];
    *origin = format == 0 ? -(data->scale[dim] * data->origin[dim]) : data->origin[dim];
    if (unit) fill(static_cast<MsvcWString353*>(unit), data->unit[dim]);
}
double mean_fake(const NativeRef* ref) {
    ++mean_calls;
    if (mean_throws) throw std::runtime_error("surrogate native mean failure");
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
void delete_document_holder_fake(void* pointer) {
    auto* holder = static_cast<nb::ScriptImageDocument353*>(pointer);
    check(holder->references == 0);
    if (holder->document) {
        auto* document = static_cast<FakeDocument*>(holder->document);
        check(InterlockedDecrement64(&document->references) == 1);
    }
    ++holder_destructions;
    delete holder;
}
void delete_window_fake(void* pointer) {
    auto* window = static_cast<FakeWindow*>(pointer);
    check(window->references == 0);
    ++window_destructions;
    delete window;
}
nb::ScriptImageDocument353* get_document_fake(void* pointer) {
    ++document_calls;
    if (show_fault == "document_throw") throw std::runtime_error("surrogate document factory failure");
    if (show_fault == "document_null") return nullptr;
    if (show_fault == "holder_bad_pointer") return reinterpret_cast<nb::ScriptImageDocument353*>(1);
    auto* image = static_cast<FakeImage*>(pointer);
    auto found = host_documents.find(image->id);
    if (found == host_documents.end()) {
        auto document = std::make_unique<FakeDocument>();
        document->image = image;
        InterlockedIncrement64(&image->references);
        found = host_documents.emplace(image->id, document.release()).first;
    }
    auto* document = found->second;
    auto* holder = new nb::ScriptImageDocument353{1, document};
    InterlockedIncrement64(&document->references);
    if (show_fault == "holder_zero") holder->references = 0;
    if (show_fault == "holder_null_doc") holder->document = nullptr;
    if (show_fault == "document_zero") document->references = 0;
    if (show_fault == "holder_zero" || show_fault == "holder_null_doc" || show_fault == "document_zero")
        malformed_holders.push_back(holder);
    return holder;
}
void* show_document_fake(nb::ScriptImageDocument353* holder) {
    ++show_calls;
    check(holder && holder->references == 1);
    auto* document = static_cast<FakeDocument*>(holder->document);
    check(document && document->references == 2);
    if (show_fault == "show_throw") throw std::runtime_error("surrogate native show failure");
    if (show_fault == "window_null") return nullptr;
    if (show_fault == "window_zero") {
        auto* window = new FakeWindow;
        window->references = 0;
        malformed_windows.push_back(window);
        return window;
    }
    auto found = host_windows.find(document->image->id);
    if (found == host_windows.end()) found = host_windows.emplace(document->image->id, new FakeWindow).first;
    InterlockedIncrement64(&found->second->references);
    return found->second;
}
void close_surrogate_documents() {
    // Repair deliberately malformed allocations only in this test process.
    // Production latches off and avoids following unidentifiable layouts.
    for (auto* holder : malformed_holders) {
        auto* document = host_documents.begin()->second;
        document->references = 2; holder->document = document; holder->references = 0;
        delete_document_holder_fake(holder);
    }
    malformed_holders.clear();
    for (auto* window : malformed_windows) delete_window_fake(window);
    malformed_windows.clear();
    for (const auto& entry : host_windows) {
        check(InterlockedDecrement64(&entry.second->references) == 0);
        delete_window_fake(entry.second);
    }
    host_windows.clear();
    for (const auto& entry : host_documents) {
        auto* document = entry.second;
        check(InterlockedDecrement64(&document->references) == 0);
        auto* image = document->image;
        if (InterlockedDecrement64(&image->references) == 0) delete_fake(image);
        delete document;
    }
    host_documents.clear();
}
void inject_fake() {
    api.find_id = find_fake; api.id = id_fake; api.ndim = ndim_fake;
    api.find_index = index_fake; api.count = count_fake; api.crop = crop_fake;
    api.dtype = dtype_fake; api.dimension = dimension_fake;
    api.calibration = calibration_fake; api.name = name_fake;
    api.mean = mean_fake; api.destroy = delete_fake; api.deallocate = free_fake;
    api.get_document = get_document_fake; api.show_document = show_document_fake;
    api.destroy_document_holder = delete_document_holder_fake; api.destroy_window = delete_window_fake;
    host_thread = GetCurrentThreadId(); gate_error.clear(); fatal_abi = false;
    registry.emplace(fake.id, &fake);
}
void expect_crop_failure(std::vector<std::uint32_t> args, const std::string& message) {
    try { execute_native({"crop_failure", "CROP", std::move(args)}); check(false); }
    catch (const std::runtime_error& e) { check(e.what() == message); }
    check(fake.references == 1 && retained_crops.empty() && retained_crop_bytes == 0);
    check(registry.size() == 1);
}
void expect_mean_failure(std::uint32_t id, const std::string& message, bool calls_operator = false) {
    const auto before = mean_calls;
    std::string actual;
    try { execute_native({"mean_failure", "MEAN", {id}}); }
    catch (const std::runtime_error& e) { actual = e.what(); }
    if (actual != message) throw std::runtime_error("expected " + message + ", received " + actual);
    check(actual == message);
    check(mean_calls == before + (calls_operator ? 1 : 0));
    check(fake.references == 1 && retained_crops.empty() && retained_crop_bytes == 0);
}
std::string accepted_mean(double value, const char* wire_value, bool calibration_complete) {
    expected_mean = value;
    const auto before = mean_calls;
    const auto result = execute_native({"raw_mean", "MEAN", {fake.id}});
    check(nb::valid_json(result));
    check(result.find(std::string("\"mean\":") + wire_value) != std::string::npos);
    check(result.find("\"intensity_calibration_applied\":false") != std::string::npos);
    check(result.find("\"intensity_semantics\":\"raw pixel intensity\"") != std::string::npos);
    check(result.find("\"calibration_complete\":" + std::string(calibration_complete ? "true" : "false")) != std::string::npos);
    check(result.find("\"native_mean_supported\":true") != std::string::npos);
    check(mean_calls == before + 1 && fake.references == 1);
    return result;
}
void raw_mean_calibration_tests() {
    inject_fake();
    check(fake.references == 1 && registry.size() == 1);
    const auto original = fake;
    invalid_scale = false;

    // Independently supplied binary-fraction native results retain sign and
    // fraction; spatial calibration is reported, never applied to intensity.
    const auto normal = accepted_mean(0.125, "0.125", true);
    check(normal.find("\"issue\":null") != std::string::npos);
    accepted_mean(-0.375, "-0.375", true);

    fake.unit[0].clear();
    const auto missing_units = accepted_mean(-0.375, "-0.375", false);
    check(missing_units.find("\"unit\":null,\"usable\":false,\"issue\":\"unknown_units\"") != std::string::npos);
    check(missing_units.find("\"unit\":\"nm\",\"usable\":true,\"issue\":null") != std::string::npos);
    const auto listed = execute_native({"uncalibrated_list", "DATASETS", {}});
    check(nb::valid_json(listed));
    check(listed.find("\"calibration_complete\":false") != std::string::npos);
    check(listed.find("\"native_mean_supported\":true") != std::string::npos);
    const auto before_crop = crop_calls;
    expect_crop_failure({fake.id,0,0,1,1}, "unknown_image_units");
    check(crop_calls == before_crop);
    fake.unit[0] = original.unit[0];

    invalid_scale = true;
    const auto zero_scale = accepted_mean(0.125, "0.125", false);
    check(zero_scale.find("\"issue\":\"invalid_calibration\"") != std::string::npos);
    expect_crop_failure({fake.id,0,0,1,1}, "invalid_image_calibration");
    check(crop_calls == before_crop);
    fake.unit[0].clear();
    const auto invalid_and_unmarked = accepted_mean(-0.375, "-0.375", false);
    check(invalid_and_unmarked.find("\"unit\":null,\"usable\":false,\"issue\":\"invalid_calibration_and_unknown_units\"") != std::string::npos);
    fake.unit[0] = original.unit[0];
    invalid_scale = false;

    fake.scale[0] = std::numeric_limits<float>::quiet_NaN();
    const auto nonfinite_calibration = accepted_mean(-0.375, "-0.375", false);
    check(nonfinite_calibration.find("\"calibrated_value_at_pixel_zero\":null,\"scale\":null") != std::string::npos);
    check(nonfinite_calibration.find("\"issue\":\"invalid_calibration\"") != std::string::npos);
    expect_crop_failure({fake.id,0,0,1,1}, "invalid_image_calibration");
    check(crop_calls == before_crop);
    fake.scale[0] = original.scale[0];
    fake.origin[1] = std::numeric_limits<float>::infinity();
    const auto unusable_origin = accepted_mean(0.125, "0.125", false);
    check(unusable_origin.find("\"origin\":null,\"calibrated_value_at_pixel_zero\":null") != std::string::npos);
    fake.origin[1] = original.origin[1];

    // Relaxing known calibration-data defects must not relax operation gates
    // or turn native getter/ABI failures into apparent numerical success.
    fake.code = 10;
    expect_mean_failure(fake.id, "native_mean_requires_float32_2d");
    const auto unsupported = execute_native({"unsupported_list", "DATASETS", {}});
    check(nb::valid_json(unsupported));
    check(unsupported.find("\"native_mean_supported\":false") != std::string::npos);
    fake.code = original.code; fake.dimensions = 3;
    expect_mean_failure(fake.id, "native_mean_requires_float32_2d");
    fake.dimensions = original.dimensions; fake.width = 4194305; fake.height = 1;
    expect_mean_failure(fake.id, "native_mean_working_region_over_budget");
    fake.width = 0;
    expect_mean_failure(fake.id, "invalid_image_dimensions");
    fake.width = original.width; fake.height = original.height;
    expect_mean_failure(99, "image_not_found");
    registry.emplace(99, &fake);
    expect_mean_failure(99, "image_identity_mismatch");
    registry.erase(99);

    calibration_throws = true;
    fake.unit[0].clear();
    expect_mean_failure(fake.id, "surrogate calibration getter failure");
    calibration_throws = false;
    fake.unit[0] = std::wstring(1, static_cast<wchar_t>(0xd800));
    expect_mean_failure(fake.id, "invalid_vendor_unicode");
    fake.unit[0] = original.unit[0];
    mean_throws = true;
    expect_mean_failure(fake.id, "surrogate native mean failure", true);
    mean_throws = false;
    for (double value : {std::numeric_limits<double>::infinity(), -std::numeric_limits<double>::infinity(),
                         std::numeric_limits<double>::quiet_NaN()}) {
        expected_mean = value;
        expect_mean_failure(fake.id, "native_mean_nonfinite_result", true);
    }
    gate_error = "surrogate adapter not ready";
    expect_mean_failure(fake.id, "surrogate adapter not ready");
    gate_error.clear(); fatal_abi = true;
    expect_mean_failure(fake.id, "native_abi_invalid_output_path_disabled");
    fatal_abi = false;
    accepted_mean(-0.375, "-0.375", true);
    check(fake.origin[0] == original.origin[0] && fake.origin[1] == original.origin[1]);
    check(fake.scale[0] == original.scale[0] && fake.scale[1] == original.scale[1]);
    check(fake.unit[0] == original.unit[0] && fake.unit[1] == original.unit[1]);
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
void show_tests() {
    inject_fake(); invalid_scale = false;
    fake.width = 3; fake.height = 2;
    fake.pixels = {-2, -1, 0, 1, 2, 3};
    const auto original_pixels = fake.pixels;
    const auto factory_before = document_calls;
    auto rejected = [&](std::vector<std::uint32_t> args, const char* expected) {
        std::string error;
        try { execute_native({"show_failure", "SHOW", std::move(args)}); }
        catch (const std::runtime_error& e) { error = e.what(); }
        check(error == expected);
    };
    rejected({}, "native_show_requires_one_image_id");
    rejected({0}, "native_show_requires_plugin_crop");
    rejected({fake.id}, "native_show_requires_plugin_crop");
    rejected({99}, "native_show_requires_plugin_crop");
    check(document_calls == factory_before && fake.references == 1);
    execute_native({"work_copy", "CROP", {fake.id,0,0,2,2}});
    const auto output_id = last_output_id;
    auto* output = registry.at(output_id);
    registry.erase(output_id);
    rejected({output_id}, "image_not_found");
    registry.emplace(output_id, &fake);
    rejected({output_id}, "image_identity_mismatch");
    registry.at(output_id) = output;
    check(document_calls == factory_before && output->references == 1 && fake.references == 1);
    api.show_document = nullptr;
    rejected({output_id}, "native_show_entrypoint_unavailable");
    check(document_calls == factory_before && output->references == 1);
    api.show_document = show_document_fake;

    const auto holders_before = holder_destructions;
    auto result = execute_native({"show_work_copy", "SHOW", {output_id}});
    check(nb::valid_json(result));
    for (const auto& part : {"\"backend\":\"digitalmicrograph-native\"", "\"delivery\":\"visible_dm_document\"",
                            "\"document_visible\":true", "\"source_write_requested\":false", "\"snapshot_atomic\":false",
                            "\"file_saved\":false", "\"model_visual_verification\":false"})
        check(result.find(part) != std::string::npos);
    check(result.find("\"image_id\":" + std::to_string(output_id)) != std::string::npos);
    check(result.find("document_id") == std::string::npos);
    check(host_documents.size() == 1 && host_windows.size() == 1);
    check(output->references == 2 && host_documents.at(output_id)->references == 1);
    check(host_windows.at(output_id)->references == 1 && holder_destructions == holders_before + 1);
    auto* original_doc = host_documents.at(output_id);
    auto* original_window = host_windows.at(output_id);
    execute_native({"show_existing_doc", "SHOW", {output_id}});
    check(host_documents.at(output_id) == original_doc && host_windows.at(output_id) == original_window);
    check(host_documents.size() == 1 && host_windows.size() == 1 && holder_destructions == holders_before + 2);
    check(output->references == 2 && original_doc->references == 1 && original_window->references == 1);
    const auto windows_before_stop = window_destructions;
    shutdown_native();
    check(host_documents.at(output_id) == original_doc && host_windows.at(output_id) == original_window);
    check(window_destructions == windows_before_stop && holder_destructions == holders_before + 2);
    check(retained_crops.empty() && retained_crop_bytes == 0 && registry.at(output_id)->references == 1);
    check(output->pixels == std::vector<float>({-2,-1,1,2}) && fake.pixels == original_pixels);
    close_surrogate_documents();
    check(registry.count(output_id) == 0 && fake.references == 1);

    inject_fake();
    execute_native({"work_copy_failures", "CROP", {fake.id,0,0,2,2}});
    const auto failure_id = last_output_id;
    auto* failure_output = registry.at(failure_id);
    const std::pair<const char*, const char*> failures[] = {
        {"document_throw", "surrogate document factory failure"}, {"document_null", "native_show_document_unavailable"},
        {"show_throw", "surrogate native show failure"}, {"window_null", "native_show_window_unavailable"},
        {"holder_zero", "native_show_invalid_reference_layout"}, {"holder_null_doc", "native_show_invalid_document_layout"},
        {"document_zero", "native_show_invalid_document_layout"}, {"holder_bad_pointer", "native_show_invalid_reference_layout"},
        {"window_zero", "native_show_invalid_reference_layout"}
    };
    for (const auto& failure : failures) {
        show_fault = failure.first;
        const auto showed_before = show_calls;
        rejected({failure_id}, failure.second);
        check(show_calls == showed_before + ((show_fault == "show_throw" || show_fault == "window_null" || show_fault == "window_zero") ? 1 : 0));
        const bool malformed = show_fault == "holder_zero" || show_fault == "holder_null_doc" || show_fault == "document_zero" ||
            show_fault == "holder_bad_pointer" || show_fault == "window_zero";
        check(fatal_abi == malformed);
        if (malformed) rejected({failure_id}, "native_abi_invalid_output_path_disabled");
        close_surrogate_documents();
        check(failure_output->references == 1 && retained_crops.size() == 1 && fake.references == 1);
        fatal_abi = false;
    }
    show_fault.clear();
    // A sole temporary reference must run final deletion exactly once; host
    // references in the successful path above must never run that destructor.
    const auto final_windows_before = window_destructions;
    { ShowRef temporary(new FakeWindow, nb::kNativeWindowReferenceOffset353, delete_window_fake); }
    check(window_destructions == final_windows_before + 1);
    const auto final_holders_before = holder_destructions;
    { ShowRef temporary(new nb::ScriptImageDocument353{1, nullptr}, 0, delete_document_holder_fake); }
    check(holder_destructions == final_holders_before + 1 && !fatal_abi);
    auto* wide_window = new FakeWindow;
    wide_window->references = 0x100000001LL;
    const auto wide_windows_before = window_destructions;
    { ShowRef temporary(wide_window, nb::kNativeWindowReferenceOffset353, delete_window_fake); }
    check(wide_window->references == 0x100000000LL && window_destructions == wide_windows_before);
    wide_window->references = 0; delete_window_fake(wide_window);
    auto* wide_holder = new nb::ScriptImageDocument353{0x100000001LL, nullptr};
    const auto wide_holders_before = holder_destructions;
    { ShowRef temporary(wide_holder, 0, delete_document_holder_fake); }
    check(wide_holder->references == 0x100000000LL && holder_destructions == wide_holders_before);
    wide_holder->references = 0; delete_document_holder_fake(wide_holder);
    auto* invalid_holder = new nb::ScriptImageDocument353{-1, nullptr};
    const auto invalid_holders_before = holder_destructions;
    { ShowRef temporary(invalid_holder, 0, delete_document_holder_fake); }
    check(fatal_abi && invalid_holder->references == -1 && holder_destructions == invalid_holders_before);
    invalid_holder->references = 0; delete_document_holder_fake(invalid_holder); fatal_abi = false;
    shutdown_native(); check(registry.size() == 1 && fake.references == 1);

    // Resolve only addresses inside this test EXE. No vendor DLL is loaded.
    auto module = GetModuleHandleW(nullptr);
    const auto base = reinterpret_cast<std::uintptr_t>(module);
    const auto code_rva = reinterpret_cast<std::uintptr_t>(&delete_fake) - base;
    check(code_rva <= UINT32_MAX && rva_symbol<Delete>(module, static_cast<std::uint32_t>(code_rva)) == delete_fake);
    for (const auto rva : {std::uint32_t(0), std::uint32_t(UINT32_MAX), static_cast<std::uint32_t>(reinterpret_cast<std::uintptr_t>(&fake) - base)}) {
        bool failed = false;
        try { rva_symbol<Delete>(module, rva); } catch (const std::runtime_error&) { failed = true; }
        check(failed);
    }
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
        const auto badcal = execute_native({"badcal", "MEAN", {fake.id}});
        check(nb::valid_json(badcal));
        check(badcal.find("\"mean\":-24.375") != std::string::npos);
        check(badcal.find("\"calibration_complete\":false") != std::string::npos);
        check(fake.references == 1 && releases == 201);
        auto partial = metadata(&fake, false);
        check(nb::valid_json(partial));
        check(partial.find("\"calibration_complete\":false") != std::string::npos);
        check(partial.find("\"native_mean_supported\":true") != std::string::npos);
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
        raw_mean_calibration_tests();
        crop_tests();
        show_tests();
        std::cout << "PASS adapter surrogate: " << assertions << " assertions; no DM loaded\n";
        return 0;
    } catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}
