// Deterministic ownership/ABI-shim guard tests. No vendor DLL is loaded.
// Including the implementation injects C-shaped surrogates only in this EXE.
#include "adapters/gms_3_53_4137/implementation.inc"
#include <cstdlib>
#include <iostream>
#include <limits>
#include <memory>

namespace {
struct FakeImage {
    LONG64 references = 1;
    std::uint32_t id = 17, width = 11, height = 7, code = 2, dimensions = 2, packing = 1;
    float origin[2] = {5, 5}, scale[2] = {-0.25f, 0.5f};
    std::wstring unit[2] = {L"nm", L"nm"};
    std::vector<float> pixels;
    std::vector<std::uint32_t> uint32_pixels; // Synthetic-only exact integer oracle storage.
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
std::array<double, 3> expected_summary{-101.125, 92.75, -42.5};
std::vector<std::string> summary_trace;
bool summary_tracking = false;
bool operation_tracking = false;
std::string operation_fault, packing_fault, preview_fault;
int operation_calls = 0, point_calls = 0;
int summary_throw_index = -1, summary_gate_after_index = -1;
void record_summary(unsigned index) {
    static const char* names[] = {"minimum", "maximum", "sum", "mean"};
    summary_trace.emplace_back(names[index]);
    if (summary_throw_index == static_cast<int>(index))
        throw std::runtime_error("surrogate native summary failure");
    if (summary_gate_after_index == static_cast<int>(index))
        gate_error = "surrogate summary gate changed";
}
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
NativeRef* find_throw_fake(NativeRef* out, std::uint32_t id) {
    find_fake(out, id);
    throw std::runtime_error("surrogate find failure after owned reference");
}
NativeRef* find_return_fake(NativeRef* out, std::uint32_t id) {
    find_fake(out, id);
    return nullptr;
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
nb::NativePacking353* packing_fake(const void* image, nb::NativePacking353* out) {
    out->value = static_cast<const FakeImage*>(image)->packing;
    return packing_fault == "return_pointer" ? nullptr : out;
}
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
    if (summary_tracking) record_summary(3);
    if (mean_throws) throw std::runtime_error("surrogate native mean failure");
    const auto* image = static_cast<const FakeImage*>(ref->image);
    if (!operation_tracking && !image->generated) { check(ref->image == &fake); return expected_mean; }
    double sum = 0;
    for (float value : image->pixels) sum += value;
    return sum / image->pixels.size();
}
double minimum_fake(const NativeRef* ref) {
    if (operation_tracking) {
        const auto& pixels = static_cast<const FakeImage*>(ref->image)->pixels;
        check(!pixels.empty());
        float value = pixels[0];
        for (const auto pixel : pixels) { if (!std::isfinite(pixel)) return pixel; if (pixel < value) value = pixel; }
        return value;
    }
    check(ref && ref->image == &fake); record_summary(0); return expected_summary[0];
}
double maximum_fake(const NativeRef* ref) {
    if (operation_tracking) {
        const auto& pixels = static_cast<const FakeImage*>(ref->image)->pixels;
        check(!pixels.empty());
        float value = pixels[0];
        for (const auto pixel : pixels) { if (!std::isfinite(pixel)) return pixel; if (pixel > value) value = pixel; }
        return value;
    }
    check(ref && ref->image == &fake); record_summary(1); return expected_summary[1];
}
double sum_fake(const NativeRef* ref) {
    if (operation_tracking) {
        double value = 0;
        for (const auto pixel : static_cast<const FakeImage*>(ref->image)->pixels) value += pixel;
        return value;
    }
    check(ref && ref->image == &fake); record_summary(2); return expected_summary[2];
}
void delete_fake(void* pointer) {
    ++destructions;
    auto* image = static_cast<FakeImage*>(pointer);
    if (image->generated) {
        const auto entry = registry.find(image->id);
        if (entry != registry.end() && entry->second == image) registry.erase(entry);
        delete image;
    }
}
// These callbacks are numerical/ownership surrogates confined to this test EXE.
// FFT/filter copies below exercise call shape and guards, never vendor science.
NativeRef* operation_fake(NativeRef* out, const NativeRef* left, const NativeRef* right, unsigned kind) {
    ++operation_calls;
    auto* source = static_cast<FakeImage*>(left->image);
    if (operation_fault == "empty") return out;
    if (operation_fault == "alias" || operation_fault == "right_alias") {
        out->image = operation_fault == "right_alias" ? right->image : left->image;
        InterlockedIncrement64(&static_cast<FakeImage*>(out->image)->references);
        return out;
    }
    auto image = std::make_unique<FakeImage>(*source);
    image->references = 1; image->generated = true; image->id = next_image_id++;
    const auto* rhs = right ? static_cast<const FakeImage*>(right->image) : nullptr;
    for (std::size_t i = 0; i < image->pixels.size(); ++i) {
        const auto a = source->pixels[i];
        if (kind == 1) image->pixels[i] = -a;
        if (kind == 2) image->pixels[i] = std::fabs(a);
        if (kind == 3) image->pixels[i] = a * a;
        if (kind == 4) image->pixels[i] = a + rhs->pixels.at(i);
        if (kind == 5) image->pixels[i] = a - rhs->pixels.at(i);
        if (kind == 6) image->pixels[i] = a * rhs->pixels.at(i);
    }
    if (kind == 7 || kind == 8) {
        image->code = 3;
        for (unsigned axis = 0; axis < 2; ++axis) {
            const auto size = axis == 0 ? image->width : image->height;
            image->scale[axis] = 1.0f / (static_cast<float>(size) * source->scale[axis]);
            image->origin[axis] = kind == 7 ? (static_cast<float>(size) + 1.0f) / 2.0f : 0.0f;
            image->unit[axis] = kind == 7 ? L"1/" + source->unit[axis] : source->unit[axis].substr(2);
        }
    }
    if (kind == 9) image->code = 2;
    if (operation_fault == "dtype") image->code = 10;
    if (operation_fault == "packing") image->packing = 2;
    if (operation_fault == "size") ++image->width;
    if (operation_fault == "calibration") image->origin[0] += 1;
    if (operation_fault == "source_changed") source->origin[0] += 1;
    if (operation_fault == "fft_source_changed" && kind == 7) source->origin[0] += 1;
    if (operation_fault == "fft_frequency_scale" && kind == 7)
        image->scale[0] = std::nextafter(image->scale[0], 0.0f);
    if (operation_fault == "nonfinite") image->pixels[0] = std::numeric_limits<float>::infinity();
    last_output_id = image->id;
    registry.emplace(image->id, image.get()); out->image = image.release();
    if (operation_fault == "throw") throw std::runtime_error("surrogate operation failure");
    return operation_fault == "return_pointer" ? nullptr : out;
}
NativeRef* negate_fake(NativeRef* out, const NativeRef* source) { return operation_fake(out, source, nullptr, 1); }
NativeRef* abs_fake(NativeRef* out, const NativeRef* source) { return operation_fake(out, source, nullptr, 2); }
NativeRef* square_fake(NativeRef* out, const NativeRef* source) { return operation_fake(out, source, nullptr, 3); }
NativeRef* add_fake(NativeRef* out, const NativeRef* a, const NativeRef* b) { return operation_fake(out, a, b, 4); }
NativeRef* subtract_fake(NativeRef* out, const NativeRef* a, const NativeRef* b) { return operation_fake(out, a, b, 5); }
NativeRef* multiply_fake(NativeRef* out, const NativeRef* a, const NativeRef* b) { return operation_fake(out, a, b, 6); }
NativeRef* fft_fake(NativeRef* out, const NativeRef* source) { return operation_fake(out, source, nullptr, 7); }
NativeRef* ifft_fake(NativeRef* out, const NativeRef* source) { return operation_fake(out, source, nullptr, 8); }
NativeRef* component_fake(NativeRef* out, const NativeRef* source) { return operation_fake(out, source, nullptr, 9); }
NativeRef* filter_fake(NativeRef* out, const NativeRef* source) { return operation_fake(out, source, nullptr, 0); }
double point_fake(const void* pointer, const nb::NativeDataIndex2D353* index) {
    ++point_calls;
    auto* image = const_cast<FakeImage*>(static_cast<const FakeImage*>(pointer));
    check(index->dimensions == 2 && index->padding == 0 && index->x >= 0 && index->y >= 0);
    check(static_cast<std::uint64_t>(index->x) < image->width && static_cast<std::uint64_t>(index->y) < image->height);
    if (preview_fault == "throw") throw std::runtime_error("surrogate point failure");
    if (preview_fault == "source_changed") image->origin[0] += 1;
    if (preview_fault == "nonfinite") return std::numeric_limits<double>::quiet_NaN();
    return image->pixels.at(static_cast<std::size_t>(index->y) * image->width + index->x);
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
    api.minimum = minimum_fake; api.maximum = maximum_fake; api.sum = sum_fake;
    api.packing = packing_fake; api.real_value = point_fake;
    api.negate = negate_fake; api.abs = abs_fake; api.square = square_fake;
    api.add = add_fake; api.subtract = subtract_fake; api.multiply = multiply_fake;
    api.real_fft = fft_fake; api.ifft = ifft_fake;
    api.real_component = component_fake; api.imag_component = component_fake;
    api.arg = component_fake; api.norm = component_fake;
    api.smooth_filter = filter_fake; api.sobel_filter = filter_fake;
    api.laplace_filter = filter_fake; api.sharpen_filter = filter_fake;
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
void summary_failure(std::uint32_t id, const std::string& expected, unsigned called = 0) {
    summary_trace.clear();
    std::string actual;
    try { execute_native({"summary_failure", "SUMMARY", {id}}); }
    catch (const std::runtime_error& error) { actual = error.what(); }
    if (actual != expected) throw std::runtime_error("expected " + expected + ", received " + actual);
    const std::vector<std::string> order{"minimum", "maximum", "sum", "mean"};
    check(summary_trace == std::vector<std::string>(order.begin(), order.begin() + called));
    check(fake.references == 1 && retained_crops.empty() && retained_crop_bytes == 0);
}
std::string accepted_summary(bool calibration_complete) {
    summary_trace.clear();
    const auto result = execute_native({"raw_summary", "SUMMARY", {fake.id}});
    check(nb::valid_json(result));
    check(summary_trace == std::vector<std::string>({"minimum", "maximum", "sum", "mean"}));
    // Independently injected callback values deliberately do not follow a
    // sum=mean*count relation: a bridge must pass each native value unchanged.
    check(result.find("\"minimum\":-101.125") != std::string::npos);
    check(result.find("\"maximum\":92.75") != std::string::npos);
    check(result.find("\"sum\":-42.5") != std::string::npos);
    check(result.find("\"mean\":-0.375") != std::string::npos);
    check(result.find("\"image_id\":17,\"image\":{\"id\":17") != std::string::npos);
    check(result.find("\"shape\":[7,11]") != std::string::npos);
    check(result.find("\"native_mean_supported\":true,\"native_summary_supported\":true") != std::string::npos);
    check(result.find("\"calibration_complete\":" + std::string(calibration_complete ? "true" : "false")) != std::string::npos);
    check(result.find("\"operators\":[\"GMSImageProcessing::GetMinimum\",\"GMSImageProcessing::GetMaximum\",\"GMSImageProcessing::GetSum\",\"GMSImageProcessing::GetMean\"]") != std::string::npos);
    check(result.find("\"computation\":\"DM native\"") != std::string::npos);
    check(result.find("\"intensity_calibration_applied\":false,\"intensity_semantics\":\"raw pixel intensity\"") != std::string::npos);
    check(result.find("\"source_write_requested\":false,\"snapshot_atomic\":false") != std::string::npos);
    check(result.find("stddev") == std::string::npos && result.find("variance") == std::string::npos);
    check(fake.references == 1 && registry.size() == 1 && retained_crops.empty());
    return result;
}
void summary_tests() {
    inject_fake(); invalid_scale = false; summary_tracking = true;
    const auto original = fake;
    const auto original_mean = expected_mean;
    expected_mean = -0.375;
    const auto status = execute_native({"summary_status", "STATUS", {}});
    check(status.find("\"summary_float32_2d\"") != std::string::npos);
    accepted_summary(true);
    fake.unit[0].clear();
    check(accepted_summary(false).find("\"issue\":\"unknown_units\"") != std::string::npos);
    invalid_scale = true;
    check(accepted_summary(false).find("\"issue\":\"invalid_calibration_and_unknown_units\"") != std::string::npos);
    fake.unit[0] = original.unit[0]; invalid_scale = false;
    fake.scale[1] = std::numeric_limits<float>::quiet_NaN();
    check(accepted_summary(false).find("\"calibrated_value_at_pixel_zero\":null,\"scale\":null") != std::string::npos);
    fake.scale[1] = original.scale[1];
    fake.origin[0] = std::numeric_limits<float>::infinity(); accepted_summary(false);
    fake.origin[0] = original.origin[0];
    const auto before_crop = crop_calls;
    fake.unit[0].clear(); expect_crop_failure({fake.id,0,0,1,1}, "unknown_image_units");
    check(crop_calls == before_crop); fake.unit[0] = original.unit[0];
    fake.code = 10; summary_failure(fake.id, "native_summary_requires_float32_2d");
    check(execute_native({"summary_unsupported_list", "DATASETS", {}}).find("\"native_summary_supported\":false") != std::string::npos);
    fake.code = original.code; fake.dimensions = 3;
    summary_failure(fake.id, "native_summary_requires_float32_2d"); fake.dimensions = original.dimensions;
    fake.width = 4194305; fake.height = 1;
    summary_failure(fake.id, "native_summary_working_region_over_budget");
    fake.width = 4194304; summary_trace.clear();
    const auto budget_edge = execute_native({"summary_budget_edge", "SUMMARY", {fake.id}});
    check(nb::valid_json(budget_edge) && budget_edge.find("\"pixels\":4194304") != std::string::npos);
    check(summary_trace == std::vector<std::string>({"minimum", "maximum", "sum", "mean"}));
    fake.width = 0; summary_failure(fake.id, "invalid_image_dimensions");
    fake.width = original.width; fake.height = original.height;
    summary_failure(99, "image_not_found");
    registry.emplace(99, &fake); summary_failure(99, "image_identity_mismatch"); registry.erase(99);
    calibration_throws = true; summary_failure(fake.id, "surrogate calibration getter failure"); calibration_throws = false;
    fake.unit[1] = std::wstring(1, static_cast<wchar_t>(0xd800));
    summary_failure(fake.id, "invalid_vendor_unicode"); fake.unit[1] = original.unit[1];
    const auto saved_summary = expected_summary;
    for (unsigned field = 0; field < 4; ++field) {
        for (const double value : {std::numeric_limits<double>::infinity(), -std::numeric_limits<double>::infinity(),
                                   std::numeric_limits<double>::quiet_NaN()}) {
            if (field < 3) expected_summary[field] = value; else expected_mean = value;
            summary_failure(fake.id, "native_summary_nonfinite_result", field + 1);
            expected_summary = saved_summary; expected_mean = -0.375;
        }
        summary_throw_index = static_cast<int>(field);
        summary_failure(fake.id, "surrogate native summary failure", field + 1); summary_throw_index = -1;
        summary_gate_after_index = static_cast<int>(field);
        summary_failure(fake.id, "surrogate summary gate changed", field + 1);
        summary_gate_after_index = -1; gate_error.clear();
    }
    api.sum = nullptr; summary_failure(fake.id, "native_summary_not_available"); api.sum = sum_fake;
    gate_error = "surrogate adapter not ready"; summary_failure(fake.id, "surrogate adapter not ready"); gate_error.clear();
    fatal_abi = true; summary_failure(fake.id, "native_abi_invalid_output_path_disabled"); fatal_abi = false;
    const auto saved_thread = host_thread; host_thread = saved_thread + 1;
    summary_failure(fake.id, "wrong_native_execution_thread"); host_thread = saved_thread;
    for (const std::vector<std::uint32_t>& args : {std::vector<std::uint32_t>{}, {fake.id, fake.id}}) {
        summary_trace.clear(); std::string error;
        try { execute_native({"summary_bad_shape", "SUMMARY", args}); }
        catch (const std::runtime_error& e) { error = e.what(); }
        check(error == "native_summary_requires_one_image_id" && summary_trace.empty() && fake.references == 1);
    }
    accepted_summary(true);
    check(fake.origin[0] == original.origin[0] && fake.origin[1] == original.origin[1]);
    check(fake.scale[0] == original.scale[0] && fake.scale[1] == original.scale[1]);
    check(fake.unit[0] == original.unit[0] && fake.unit[1] == original.unit[1]);
    check(fake.pixels == original.pixels && fake.id == original.id);
    summary_tracking = false; expected_mean = original_mean;
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
    rejected({0}, "native_show_requires_plugin_result");
    rejected({fake.id}, "native_show_requires_plugin_result");
    rejected({99}, "native_show_requires_plugin_result");
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
void production_operation_tests() {
    check(retained_results.empty() && host_documents.empty() && host_windows.empty());
    fake = FakeImage{};
    fake.width = 3; fake.height = 2; fake.pixels = {-2, -0.5f, 0, 3, 2, -1};
    FakeImage right;
    right.id = 18; right.width = 3; right.height = 2; right.pixels = {4, -1, 2, 0.25f, -0.5f, 1.5f};
    registry.emplace(right.id, &right);
    inject_fake(); operation_tracking = true; summary_tracking = false;
    SetEnvironmentVariableA("DM_NATIVE_QUALIFY_OPERATIONS", nullptr);
    const auto reject = [&](const char* op, std::vector<std::uint32_t> args, const char* expected, int calls = 0) {
        const auto before_calls = operation_calls;
        const auto before_registry = registry.size(), before_retained = retained_results.size();
        const auto before_bytes = retained_result_bytes;
        std::string actual;
        try { execute_native({"candidate_failure", op, std::move(args)}); }
        catch (const std::runtime_error& error) { actual = error.what(); }
        if (actual != expected) throw std::runtime_error(std::string("candidate expected ") + expected + ", received " + actual);
        check(operation_calls == before_calls + calls);
        check(registry.size() == before_registry && retained_results.size() == before_retained && retained_result_bytes == before_bytes);
        check(fake.references == 1 && right.references == 1);
    };
    const auto status = execute_native({"production_status", "STATUS", {}});
    check(nb::valid_json(status));
    for (const auto* name : {"unary_float32_2d", "binary_float32_2d", "fourier_small_2d",
                            "filter_small_float32_2d", "sampled_preview_float32_2d", "bounded_read_float32_2d",
                            "show_plugin_result_visible_document"})
        check(status.find(nb::quote(name)) != std::string::npos);
    check(status.find("candidate_execution_enabled") == std::string::npos &&
          status.find("candidate_capabilities") == std::string::npos);
    // Process environment is irrelevant to production qualification. Even "1"
    // cannot change available groups or bypass their profile/dispatch contract.
    for (const auto* value : {"true", "01", "1 ", "11", "1"}) {
        SetEnvironmentVariableA("DM_NATIVE_QUALIFY_OPERATIONS", value);
        check(execute_native({"environment_independent_status", "STATUS", {}}) == status);
        reject("UNARY", {17,99}, "native_unary_opcode_unsupported");
    }
    SetEnvironmentVariableA("DM_NATIVE_QUALIFY_OPERATIONS", nullptr);
    reject("UNARY", {17}, "native_arithmetic_argument_count");
    reject("UNARY", {17,4}, "native_unary_opcode_unsupported");
    reject("BINARY", {17,18,4}, "native_divide_not_qualified");
    reject("BINARY", {17,18,0}, "native_binary_opcode_unsupported");
    api.negate = nullptr;
    reject("UNARY", {17,1}, "native_arithmetic_symbol_unavailable");
    api.negate = negate_fake;
    api.find_id = find_throw_fake;
    reject("UNARY", {17,1}, "surrogate find failure after owned reference");
    api.find_id = find_return_fake;
    reject("UNARY", {17,1}, "native_find_result_mismatch");
    api.find_id = find_fake;
    api.minimum = nullptr;
    reject("UNARY", {17,1}, "native_arithmetic_finite_check_unavailable");
    api.minimum = minimum_fake;
    fake.code = 10; reject("UNARY", {17,1}, "native_arithmetic_requires_float32_2d"); fake.code = 2;
    fake.packing = 2; reject("UNARY", {17,1}, "native_arithmetic_requires_ordinary_packing"); fake.packing = 1;
    right.width = 4; reject("BINARY", {17,18,1}, "native_binary_shape_mismatch"); right.width = 3;
    right.origin[1] += 1; reject("BINARY", {17,18,1}, "native_binary_spatial_calibration_mismatch"); right.origin[1] -= 1;
    right.unit[1] = L"pm"; reject("BINARY", {17,18,1}, "native_binary_spatial_calibration_mismatch"); right.unit[1] = L"nm";
    fake.pixels[0] = std::numeric_limits<float>::quiet_NaN();
    reject("UNARY", {17,1}, "native_arithmetic_source_nonfinite"); fake.pixels[0] = -2;
    for (const auto& fault : std::vector<std::pair<std::string, const char*>>{
        {"empty", "native_arithmetic_no_output_reference"}, {"alias", "native_arithmetic_output_identity_invalid"},
        {"return_pointer", "native_arithmetic_no_output_reference"}, {"throw", "surrogate operation failure"},
        {"dtype", "native_arithmetic_output_descriptor_mismatch"}, {"packing", "native_arithmetic_output_descriptor_mismatch"},
        {"size", "native_arithmetic_output_descriptor_mismatch"}, {"calibration", "native_arithmetic_output_spatial_calibration_mismatch"},
        {"nonfinite", "native_arithmetic_output_nonfinite"}, {"source_changed", "native_arithmetic_source_metadata_changed"}}) {
        operation_fault = fault.first;
        reject("UNARY", {17,1}, fault.second, 1);
        if (operation_fault == "source_changed") fake.origin[0] -= 1;
    }
    operation_fault = "right_alias";
    reject("BINARY", {17,18,1}, "native_arithmetic_output_identity_invalid", 1);
    operation_fault.clear();
    const std::vector<std::vector<float>> golden{{2,0.5f,0,-3,-2,1}, {2,0.5f,0,3,2,1}, {4,0.25f,0,9,4,1},
        {2,-1.5f,2,3.25f,1.5f,0.5f}, {-6,0.5f,-2,2.75f,2.5f,-2.5f}, {-8,0.5f,0,0.75f,-1,-1.5f}};
    std::uint32_t first_result = 0;
    for (unsigned index = 0; index < golden.size(); ++index) {
        const bool binary = index >= 3;
        const auto opcode = binary ? index - 2 : index + 1;
        const NativeRequest request{"candidate_" + std::to_string(index), binary ? "BINARY" : "UNARY",
            binary ? std::vector<std::uint32_t>{17,18,opcode} : std::vector<std::uint32_t>{17,opcode}};
        const auto before_calls = operation_calls;
        const auto result = execute_native(request);
        check(nb::valid_json(result) && operation_calls == before_calls + 1);
        const auto output_id = last_output_id;
        if (!index) first_result = output_id;
        check(output_id != 17 && output_id != 18 && registry.at(output_id)->pixels == golden[index]);
        const auto& retained = retained_results.at(output_id);
        check(retained.request_id == request.id && retained.operation == request.op && retained.bytes == 24);
        check(retained.kind == (binary ? ResultKind::Binary : ResultKind::Unary));
        check(retained.source_ids == (binary ? std::vector<std::uint32_t>{17,18} : std::vector<std::uint32_t>{17}));
        check(result.find("\"intensity_calibration_applied\":false") != std::string::npos);
        check(result.find("\"visible_dm_document\":false") != std::string::npos);
        check(fake.references == 1 && right.references == 1 && registry.at(output_id)->references == 1);
    }
    check(fake.pixels == std::vector<float>({-2,-0.5f,0,3,2,-1}));
    check(right.pixels == std::vector<float>({4,-1,2,0.25f,-0.5f,1.5f}));
    execute_native({"mixed_crop", "CROP", {17,0,0,1,1}});
    check(retained_results.size() == 7 && retained_result_bytes == 148);
    check(retained_results.at(last_output_id).kind == ResultKind::Crop);

    // A synthetic FFT copies payloads only. Its acceptance here proves typed
    // calls, descriptor guards, temporary cleanup and retention, not FFT math.
    const auto arithmetic_width = fake.width, arithmetic_height = fake.height;
    const auto arithmetic_pixels = fake.pixels;
    fake.width = 257;
    reject("FFT", {17}, "native_fft_input_over_budget"); fake.width = 3;
    reject("FFT", {17}, "native_fft_requires_power_of_two_dimensions_4_to_256");
    fake.width = 6; fake.height = 4;
    reject("FFT", {17}, "native_fft_requires_power_of_two_dimensions_4_to_256");
    fake.width = 4; fake.height = 4; fake.pixels.assign(16, 1.25f);
    // Unsupported/unowned complex sources fail before invoking even Find.
    api.find_id = find_throw_fake;
    reject("IFFT", {17}, "native_ifft_requires_plugin_retained_fft");
    reject("REAL", {17}, "native_fft_component_requires_plugin_transform");
    reject("IMAG", {first_result}, "native_fft_component_requires_plugin_transform");
    api.find_id = find_fake;
    api.real_fft = nullptr;
    reject("FFT", {17}, "native_fft_symbol_unavailable"); api.real_fft = fft_fake;
    const auto scale_before_fft = fake.scale[0];
    fake.unit[0].clear();
    reject("FFT", {17}, "native_crop_requires_valid_calibration"); fake.unit[0] = L"nm";
    invalid_scale = true;
    reject("FFT", {17}, "native_crop_requires_valid_calibration"); invalid_scale = false;
    fake.scale[0] = std::numeric_limits<float>::denorm_min();
    reject("FFT", {17}, "native_fft_frequency_scale_unrepresentable");
    const auto raw_origin_before_fft = fake.origin[0]; fake.origin[0] = 0;
    fake.scale[0] = std::numeric_limits<float>::max();
    reject("FFT", {17}, "native_fft_frequency_scale_unrepresentable");
    fake.scale[0] = scale_before_fft; fake.origin[0] = raw_origin_before_fft;
    for (const auto& fault : std::vector<std::pair<std::string, const char*>>{
        {"alias", "native_fft_output_alias"}, {"empty", "native_fft_no_output_reference"},
        {"return_pointer", "native_fft_no_output_reference"}, {"throw", "surrogate operation failure"},
        {"dtype", "native_fft_output_descriptor_mismatch"}, {"packing", "native_fft_output_descriptor_mismatch"},
        {"size", "native_fft_output_descriptor_mismatch"}}) {
        operation_fault = fault.first; reject("FFT", {17}, fault.second, 1);
    }
    operation_fault.clear();
    operation_fault = "calibration";
    reject("FFT", {17}, "native_fft_frequency_calibration_mismatch", 3);
    operation_fault = "fft_frequency_scale";
    reject("FFT", {17}, "native_fft_frequency_calibration_mismatch", 3);
    operation_fault = "fft_source_changed";
    reject("FFT", {17}, "native_fft_source_metadata_changed", 3);
    fake.origin[0] -= 1;
    operation_fault.clear();
    const auto before_fft_registry = registry.size();
    const auto fft = execute_native({"synthetic_fft", "FFT", {17}});
    check(nb::valid_json(fft) && registry.size() == before_fft_registry + 1);
    const auto fft_id = retained_results.rbegin()->first;
    check(registry.at(fft_id)->code == 3 && registry.at(fft_id)->packing == 1);
    check(fft.find("\"dtype\":\"complex64\"") != std::string::npos);
    check(fft.find("\"native_summary_supported\":false") != std::string::npos);
    check(fft.find("\"normalization\":\"none\",\"centering\":\"fftshift_data\",\"phase_units\":\"not_applicable\"") != std::string::npos);
    check(fft.find("\"transform_signs\":{\"forward\":\"+\",\"inverse\":\"-\"}") != std::string::npos);
    check(fft.find("\"frequency_grid\":{\"native_calibration_has_half_bin_offset\":true") != std::string::npos);
    check(fft.find("\"frequency_at_index_zero\":2,\"native_calibrated_value_at_pixel_zero\":2.5,\"native_calibration_dc_value\":0.5") != std::string::npos);
    check(fft.find("\"input_index_origin\":\"zero-based pixel indices\",\"source_spatial_origin_used\":false") != std::string::npos);
    check(fft.find("\"intensity_calibration_applied\":false,\"inverse_restores_source_origin\":false") != std::string::npos);
    const auto before_components = registry.size();
    const auto real = execute_native({"synthetic_component", "REAL", {fft_id}});
    check(nb::valid_json(real) && registry.size() == before_components + 1);
    check(registry.at(retained_results.rbegin()->first)->code == 2);
    const auto real_id = retained_results.rbegin()->first;
    check(real.find("\"normalization\":\"inherited_parent_transform\",\"centering\":\"fftshift_data\"") != std::string::npos);
    reject("IFFT", {real_id}, "native_ifft_requires_plugin_retained_fft");
    reject("REAL", {real_id}, "native_fft_component_requires_plugin_transform");
    auto* retained_fft = registry.at(fft_id);
    retained_fft->origin[0] += 1;
    reject("REAL", {fft_id}, "native_fft_retained_metadata_changed"); retained_fft->origin[0] -= 1;
    FakeImage replacement_fft = *retained_fft; replacement_fft.references = 1;
    registry[fft_id] = &replacement_fft;
    reject("REAL", {fft_id}, "native_fft_retained_identity_mismatch");
    check(replacement_fft.references == 1); registry[fft_id] = retained_fft;
    // An owned component alias must release only the extra returned ref.
    operation_fault = "alias";
    reject("REAL", {fft_id}, "native_fft_component_check_alias", 1);
    operation_fault.clear();
    check(registry.at(fft_id)->references == 1);
    operation_fault = "calibration";
    reject("REAL", {fft_id}, "native_fft_component_calibration_mismatch", 3);
    operation_fault.clear();
    const auto arg_result = execute_native({"synthetic_arg", "VENDOR_ARG", {fft_id}});
    check(arg_result.find("\"representation\":\"phase_radians\"") != std::string::npos);
    check(arg_result.find("\"phase_units\":\"radians\"") != std::string::npos);
    const auto norm_result = execute_native({"synthetic_norm", "VENDOR_NORM", {fft_id}});
    check(norm_result.find("\"representation\":\"squared_magnitude\"") != std::string::npos);
    operation_fault = "calibration";
    reject("IFFT", {fft_id}, "native_ifft_spatial_calibration_mismatch", 5);
    operation_fault.clear();
    const auto inverse = execute_native({"synthetic_inverse", "IFFT", {fft_id}});
    check(nb::valid_json(inverse) && registry.at(retained_results.rbegin()->first)->code == 3);
    const auto inverse_id = retained_results.rbegin()->first;
    check(inverse.find("\"normalization\":\"1/(width*height)\",\"centering\":\"spatial_origin_zero\"") != std::string::npos);
    check(inverse.find("\"frequency_grid\":null") != std::string::npos);
    reject("IFFT", {inverse_id}, "native_ifft_requires_plugin_retained_fft");
    const auto inverse_real = execute_native({"synthetic_inverse_real", "REAL", {inverse_id}});
    check(inverse_real.find("\"centering\":\"spatial_origin_zero\"") != std::string::npos);
    check(inverse_real.find("\"frequency_grid\":null") != std::string::npos);
    check(fake.width == 4 && fake.height == 4 && fake.pixels == std::vector<float>(16, 1.25f));
    fake.width = arithmetic_width; fake.height = arithmetic_height; fake.pixels = arithmetic_pixels;

    reject("FILTER", {17,1}, "native_filter_requires_dimensions_at_least_5");
    const auto small_width = fake.width, small_height = fake.height;
    const auto small_pixels = fake.pixels;
    fake.width = 5; fake.height = 5; fake.pixels.assign(25, -1.5f);
    for (std::uint32_t kind = 1; kind <= 4; ++kind) {
        const auto result = execute_native({"synthetic_filter_" + std::to_string(kind), "FILTER", {17,kind}});
        check(nb::valid_json(result) && result.find("\"operation\":\"FILTER\"") != std::string::npos);
        check(registry.at(last_output_id)->pixels == fake.pixels);
    }
    reject("FILTER", {17,5}, "native_filter_kind_unsupported");
    operation_fault = "calibration";
    reject("FILTER", {17,1}, "native_filter_output_calibration_mismatch", 1);
    operation_fault = "nonfinite";
    reject("FILTER", {17,1}, "native_filter_nonfinite_output", 1);
    operation_fault.clear();
    fake.width = small_width; fake.height = small_height; fake.pixels = small_pixels;

    const auto preview_registry = registry.size(), preview_retained = retained_results.size();
    const auto preview_calls = point_calls;
    const auto preview = execute_native({"synthetic_preview", "PREVIEW", {17,128,128}});
    check(nb::valid_json(preview) && preview.find("\"gray8_hex\":\"004d66ffcc33\"") != std::string::npos);
    check(preview.find("\"width\":3,\"height\":2") != std::string::npos && point_calls == preview_calls + 6);
    check(preview.find("\"quantitative\":false") != std::string::npos);
    check(registry.size() == preview_registry && retained_results.size() == preview_retained);
    reject("PREVIEW", {17,0,1}, "native_preview_dimensions_out_of_range");
    reject("PREVIEW", {17,129,1}, "native_preview_dimensions_out_of_range");
    const auto preview_small = execute_native({"synthetic_preview_small", "PREVIEW", {17,2,1}});
    check(preview_small.find("\"gray8_hex\":\"00ff\"") != std::string::npos);
    for (const auto& fault : std::vector<std::pair<std::string, const char*>>{
        {"nonfinite", "native_preview_nonfinite_sample"}, {"throw", "surrogate point failure"},
        {"source_changed", "native_preview_source_metadata_changed"}}) {
        preview_fault = fault.first;
        const auto origin_before = fake.origin[0];
        reject("PREVIEW", {17,2,1}, fault.second);
        fake.origin[0] = origin_before;
    }
    preview_fault.clear();

    // All result types consume the exact same count budget as old crop.
    while (retained_results.size() < nb::kCropRetainedCount)
        execute_native({"fill_shared_pool", "UNARY", {17,1}});
    reject("UNARY", {17,1}, "native_result_retention_capacity");
    fake.width = 4; fake.height = 4; fake.pixels.assign(16, 1.25f);
    reject("FFT", {17}, "native_fft_retention_capacity");
    fake.width = 5; fake.height = 5; fake.pixels.assign(25, -1.5f);
    reject("FILTER", {17,2}, "native_filter_retention_capacity");
    fake.width = small_width; fake.height = small_height; fake.pixels = small_pixels;
    const auto documents_before = document_calls;
    execute_native({"show_unary", "SHOW", {first_result}});
    execute_native({"show_same_unary", "SHOW", {first_result}});
    check(document_calls == documents_before + 2 && host_documents.size() == 1);
    auto* shown = registry.at(first_result);
    check(shown->references == 2);
    shutdown_native();
    check(retained_results.empty() && retained_result_bytes == 0 && shown->references == 1);
    check(registry.size() == 3 && fake.references == 1 && right.references == 1);
    close_surrogate_documents();
    check(registry.size() == 2 && !registry.count(first_result));
    registry.erase(right.id);
    operation_tracking = false;
    SetEnvironmentVariableA("DM_NATIVE_QUALIFY_OPERATIONS", nullptr);
    inject_fake();
    api.mean = nullptr;
    reject("MEAN", {17}, "native_mean_not_available");
    check(metadata(&fake, false).find("\"native_mean_supported\":false") != std::string::npos);
    inject_fake();
    packing_fault = "return_pointer";
    SetEnvironmentVariableA("DM_NATIVE_QUALIFY_OPERATIONS", "1");
    reject("UNARY", {17,1}, "native_packing_result_mismatch");
    check(fatal_abi);
    packing_fault.clear(); fatal_abi = false;
    SetEnvironmentVariableA("DM_NATIVE_QUALIFY_OPERATIONS", nullptr);
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
        summary_tests();
        crop_tests();
        show_tests();
        production_operation_tests();
        std::cout << "PASS adapter surrogate: " << assertions << " assertions; no DM loaded\n";
        return 0;
    } catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}
