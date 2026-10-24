// Actual fixed-version ROI adapter with C-shaped offline callbacks only.
#define main existing_adapter_test_main
#include "adapter_tests.cpp"
#undef main
#include <fstream>

namespace {
struct FakeRoi353 {
    LONG64 references = 1;
    std::uint64_t unused = 0;
    std::int32_t id = 7;
    bool rectangle = true, selected = true;
    nb::RoiRectangle353 coordinates{1, 2, 6, 10};
    unsigned char padding[nb::kRoiRotationOffset353 - 40]{};
    double rotation = 0;
};
static_assert(offsetof(FakeRoi353, rotation) == nb::kRoiRotationOffset353);
struct FakeDisplay353 {
    const void* table = nullptr;
    unsigned char prefix[0x38]{};
    std::int32_t id = 9;
    unsigned char source_padding[nb::kRasterImageSourceOffset353 - 0x44]{};
    void* source = nullptr;
    std::vector<FakeRoi353*> rois;
};
static_assert(offsetof(FakeDisplay353, id) == nb::kComponentIdentityOffset353);
static_assert(offsetof(FakeDisplay353, source) == nb::kRasterImageSourceOffset353);
struct FakeSource353 { unsigned char prefix[nb::kImageSourceImplementationOffset353]{}; void* implementation = nullptr; };
struct FakeSimpleSource353 { const void* table = nullptr; unsigned char prefix[nb::kSimpleSourceImageOffset353 - 8]{}; void* image = nullptr; };
static_assert(offsetof(FakeSimpleSource353, image) == nb::kSimpleSourceImageOffset353);
FakeSource353 roi_source353;
FakeSimpleSource353 roi_simple353;
std::array<void*, 7> roi_source_table353{};
void roi_simple_count_fake353(void*) { check(false); }
void roi_simple_id_fake353(void*) { check(false); }
void roi_simple_extents_fake353(void*) { check(false); }
std::array<void*, 0x598 / 8> roi_table353{};
std::array<unsigned char, 0xc0> roi_document353{};
FakeRoi353 roi_fake353;
FakeImage roi_other_image353;
FakeDisplay353 roi_display353;
std::string roi_fault353;
int roi_hold_created353 = 0, roi_hold_freed353 = 0, roi_rect_calls353 = 0, roi_count_calls353 = 0;
int roi_display_count_calls353 = 0, roi_at_calls353 = 0;
std::uint32_t roi_requested_displays353 = 1, roi_requested_count353 = 1;
bool roi_unique_identities353 = false;
void* roi_partial_output353 = nullptr;
int roi_partial_destroy_calls353 = 0;
NativeRef* roi_partial_throw_fake353(void*, NativeRef* out, std::uint32_t) {
    out->image = roi_partial_output353;
    throw std::runtime_error("surrogate_partial_owned_output_then_throw");
}
void roi_partial_destroy_fake353(void*) { ++roi_partial_destroy_calls353; }
std::size_t roi_count_displays_fake353(const NativeRef* source, const NativeRef* doc) {
    check(source->image == &fake && !doc->image);
    ++roi_display_count_calls353;
    if (roi_fault353 == "display-count-throw") throw std::runtime_error("surrogate_display_count_error");
    if (roi_fault353 == "display-count-change" && roi_display_count_calls353 > 1) return 0;
    return roi_requested_displays353;
}
void* roi_display_at_fake353(void* source, std::uint32_t index) {
    check(source == &fake && index < roi_requested_displays353);
    if (roi_fault353 == "display-missing") return nullptr;
    ++roi_hold_created353;
    if (roi_unique_identities353) roi_display353.id = 9 + index;
    return new nb::RoiComponentHolder353{1, roi_document353.data(),
        roi_display353.id + (roi_fault353 == "holder-id" ? 1 : 0), 0, &roi_display353};
}
void roi_destroy_holder_fake353(void* value) {
    ++roi_hold_freed353; delete static_cast<nb::RoiComponentHolder353*>(value);
}
void* roi_resolve_fake353(void* holder) {
    return roi_fault353 == "invalid-display" ? nullptr : static_cast<nb::RoiComponentHolder353*>(holder)->cached_component;
}
void* roi_reverse_fake353(void*) {
    if (roi_fault353 == "reverse-missing") return nullptr;
    if (roi_fault353 == "reverse-other") { InterlockedIncrement64(&roi_other_image353.references); return &roi_other_image353; }
    InterlockedIncrement64(&fake.references); return &fake;
}
std::uint32_t roi_count_fake353(void* display) {
    check(display == &roi_display353); ++roi_count_calls353;
    if (roi_fault353 == "roi-count-throw") throw std::runtime_error("surrogate_roi_count_error");
    if (roi_fault353 == "roi-count-change" && roi_count_calls353 > 1) return 0;
    return roi_requested_count353;
}
NativeRef* roi_at_fake353(void* display, NativeRef* out, std::uint32_t index) {
    check(display == &roi_display353 && index < roi_requested_count353); ++roi_at_calls353;
    if (roi_fault353 == "roi-missing") { out->image = nullptr; return out; }
    if (roi_unique_identities353) roi_fake353.id = 7 + index;
    InterlockedIncrement64(&roi_fake353.references); out->image = &roi_fake353;
    if (roi_fault353 == "roi-throw-after-acquire") throw std::runtime_error("surrogate_roi_lookup_error_after_acquire");
    return out;
}
void roi_destroy_fake353(void*) { check(false); }
std::int32_t roi_id_fake353(void* value) { return static_cast<FakeRoi353*>(value)->id; }
bool roi_rectangle_type_fake353(void* value) { return static_cast<FakeRoi353*>(value)->rectangle; }
nb::RoiRectangle353* roi_rectangle_fake353(void* value, nb::RoiRectangle353* out) {
    ++roi_rect_calls353; *out = static_cast<FakeRoi353*>(value)->coordinates;
    if (roi_fault353 == "geometry-change" && roi_rect_calls353 > 1) out->right -= 1;
    return out;
}
bool roi_selected_fake353(void* display, const NativeRef* value) {
    check(display == &roi_display353); return static_cast<FakeRoi353*>(value->image)->selected;
}
void roi_dimensions_fake353(void*, nb::RoiDimensions353* out) {
    *out = {2,1,{0,0,0}};
    if (roi_fault353 == "dimensions") out->count = 1;
}
nb::RoiMapping353* roi_mapping_fake353(void*, nb::RoiMapping353* out, const NativeRef*) {
    *out = {0,0,1.0f/static_cast<float>(fake.width),1.0f/static_cast<float>(fake.height)};
    if (roi_fault353 == "nonidentity-mapping") out->scale_x = 0.5f;
    if (roi_fault353 == "unit-mapping") out->scale_x = out->scale_y = 1;
    if (roi_fault353 == "offset-mapping") out->offset_x = 1;
    if (roi_fault353 == "nonfinite-mapping") out->scale_x = std::numeric_limits<float>::infinity();
    if (roi_fault353 == "zero-mapping") out->scale_x = 0;
    return out;
}
nb::RoiSliceId353* roi_slice_id_fake353(void*, nb::RoiSliceId353* out) {
    *out = {1,{0,0,0,0,0}};
    if (roi_fault353 == "nondefault-slice") out->components[0] = 1;
    if (roi_fault353 == "nested-slice") { out->count = 2; out->components[1] = 1; }
    if (roi_fault353 == "invalid-slice-id-count") out->count = 6;
    if (roi_fault353 == "slice-id-throw") throw std::runtime_error("surrogate_roi_slice_id_error");
    return out;
}
void setup_roi_fake353() {
    fake = FakeImage{}; registry.clear();
    inject_fake();
    roi_other_image353 = FakeImage{}; roi_other_image353.id = 19;
    roi_fault353.clear(); roi_fake353 = FakeRoi353{}; roi_display353 = FakeDisplay353{};
    roi_hold_created353 = roi_hold_freed353 = roi_rect_calls353 = roi_count_calls353 = 0;
    roi_display_count_calls353 = roi_at_calls353 = 0;
    roi_requested_displays353 = roi_requested_count353 = 1;
    roi_unique_identities353 = false;
    roi_table353.fill(nullptr);
    roi_table353[nb::kRasterRoiCountSlot353 / 8] = reinterpret_cast<void*>(roi_count_fake353);
    roi_table353[nb::kRasterRoiGetSlot353 / 8] = reinterpret_cast<void*>(roi_at_fake353);
    roi_table353[nb::kRasterRoiDimensionsSlot353 / 8] = reinterpret_cast<void*>(roi_dimensions_fake353);
    roi_table353[nb::kRasterRoiMappingSlot353 / 8] = reinterpret_cast<void*>(roi_mapping_fake353);
    roi_table353[nb::kRasterRoiSliceIdSlot353 / 8] = reinterpret_cast<void*>(roi_slice_id_fake353);
    roi_display353.table = roi_table353.data();
    roi_source_table353.fill(nullptr);
    roi_source_table353[nb::kSimpleSourceCountSlot353/8] = reinterpret_cast<void*>(roi_simple_count_fake353);
    roi_source_table353[nb::kSimpleSourceSliceIdSlot353/8] = reinterpret_cast<void*>(roi_simple_id_fake353);
    roi_source_table353[nb::kSimpleSourceExtentsSlot353/8] = reinterpret_cast<void*>(roi_simple_extents_fake353);
    roi_simple353 = {roi_source_table353.data(), {}, &fake};
    roi_source353.implementation = &roi_simple353;
    roi_display353.source = &roi_source353;
    roi_document353.fill(0); *reinterpret_cast<std::int32_t*>(roi_document353.data() + nb::kDocumentIdentityOffset353) = 31;
    roi_api353 = {roi_count_displays_fake353, roi_display_at_fake353, roi_resolve_fake353,
        roi_reverse_fake353, roi_count_fake353, roi_at_fake353, roi_id_fake353,
        roi_rectangle_type_fake353, roi_rectangle_fake353, roi_selected_fake353, roi_dimensions_fake353, roi_mapping_fake353, roi_slice_id_fake353,
        roi_destroy_holder_fake353, roi_destroy_fake353, roi_table353.data(),
        roi_source_table353.data(), reinterpret_cast<void*>(roi_simple_count_fake353),
        reinterpret_cast<void*>(roi_simple_id_fake353), reinterpret_cast<void*>(roi_simple_extents_fake353)};
}
std::string run_roi_fake353() { return execute_native({"roi-offline", "ROIS", {17}}); }
void roi_expect_failure353(const std::string& expected) {
    try { run_roi_fake353(); check(false); }
    catch (const std::runtime_error& error) { check(std::string(error.what()) == expected); }
    check(roi_hold_created353 == roi_hold_freed353 && roi_fake353.references == 1 && fake.references == 1);
}
} // namespace

int main(int argc, char** argv) {
    try {
        setup_roi_fake353();
        const auto result = run_roi_fake353();
        check(nb::valid_json(result));
        check(result.find("\"display_identity\":{\"document_id\":31,\"display_id\":9}") != std::string::npos);
        check(result.find("\"raw_rectangle\":{\"top\":1,\"left\":2,\"bottom\":6,\"right\":10}") != std::string::npos);
        check(result.find("\"rect\":[2,1,10,6],\"analysis_eligible\":true") != std::string::npos);
        check(roi_rect_calls353 == 2 && roi_hold_freed353 == 2 && roi_fake353.references == 1 && fake.references == 1);
        if (argc == 2) { std::ofstream file(argv[1]); file << result << '\n'; check(file.good()); }
        for (const auto& item : std::vector<std::pair<nb::RoiRectangle353, const char*>>{
            {{1,2.5f,6,10},"fractional_rectangle"}, {{1,-1,6,10},"out_of_bounds_rectangle"},
            {{1,2,8,10},"out_of_bounds_rectangle"}, {{1,2,6,12},"out_of_bounds_rectangle"},
            {{2,2,2,10},"empty_or_reversed_rectangle"}, {{6,2,1,10},"empty_or_reversed_rectangle"}}) {
            setup_roi_fake353(); roi_fake353.coordinates = item.first;
            const auto captured = run_roi_fake353();
            check(captured.find(std::string("\"issue\":\"") + item.second + '"') != std::string::npos);
            check(captured.find("\"rect\":null,\"analysis_eligible\":false") != std::string::npos);
            check(roi_hold_created353 == roi_hold_freed353 && roi_fake353.references == 1 && fake.references == 1);
        }
        setup_roi_fake353(); roi_fake353.coordinates = {0,0,7,11};
        check(run_roi_fake353().find("\"rect\":[0,0,11,7]") != std::string::npos);
        setup_roi_fake353(); roi_fake353.rectangle = false;
        check(run_roi_fake353().find("\"issue\":\"unsupported_roi_type\"") != std::string::npos);
        check(roi_rect_calls353 == 0);
        setup_roi_fake353(); roi_display353.table = nullptr;
        check(run_roi_fake353().find("\"display_type\":\"unsupported\",\"slice_ids\":null,\"source_layout\":null,\"roi_count\":null") != std::string::npos);
        check(roi_count_calls353 == 0 && roi_at_calls353 == 0 && roi_hold_created353 == roi_hold_freed353);
        setup_roi_fake353(); roi_requested_count353 = 0;
        check(run_roi_fake353().find("\"roi_count\":0,\"rois\":[]") != std::string::npos && roi_at_calls353 == 0);
        setup_roi_fake353(); roi_requested_displays353 = 0;
        check(run_roi_fake353().find("\"displays\":[]") != std::string::npos && roi_hold_created353 == 0);
        for (const char* fault : {"nonidentity-mapping", "unit-mapping", "offset-mapping"}) {
            setup_roi_fake353(); roi_fault353 = fault;
            check(run_roi_fake353().find("\"issue\":\"unsupported_coordinate_mapping\"") != std::string::npos);
        }
        for (const char* fault : {"nondefault-slice", "nested-slice"}) {
            setup_roi_fake353(); roi_fault353 = fault;
            const auto captured = run_roi_fake353();
            check(captured.find("\"issue\":\"unsupported_image_source\"") != std::string::npos);
            check(captured.find("\"source_pixel_aligned\":false") != std::string::npos);
        }
        setup_roi_fake353(); fake.width = fake.height = 7; roi_fake353.coordinates = {1,2,6,6}; roi_fault353 = "nested-slice";
        check(run_roi_fake353().find("\"issue\":\"unsupported_image_source\"") != std::string::npos);
        setup_roi_fake353(); roi_simple353.table = reinterpret_cast<void*>(1);
        check(run_roi_fake353().find("\"source_layout\":\"unsupported\"") != std::string::npos);
        setup_roi_fake353(); roi_simple353.image = &roi_other_image353;
        roi_expect_failure353("native_roi_direct_source_image_mismatch");
        setup_roi_fake353(); roi_source353.implementation = nullptr;
        roi_expect_failure353("native_roi_source_binding_missing");
        setup_roi_fake353(); roi_display353.source = reinterpret_cast<void*>(1);
        roi_expect_failure353("native_roi_source_layout_unreadable"); check(roi_count_calls353 == 0 && fatal_abi);
        setup_roi_fake353(); roi_source353.implementation = reinterpret_cast<void*>(1);
        roi_expect_failure353("native_roi_source_layout_unreadable"); check(roi_count_calls353 == 0 && fatal_abi);
        setup_roi_fake353(); roi_source_table353[nb::kSimpleSourceExtentsSlot353/8] = nullptr;
        roi_expect_failure353("native_roi_source_vtable_contract_mismatch"); check(roi_count_calls353 == 0);
        for (double angle : {30., -45., 360.}) {
            setup_roi_fake353(); roi_fake353.rotation = angle;
            const auto captured = run_roi_fake353();
            check(captured.find("\"issue\":\"rotated_rectangle\"") != std::string::npos);
            check(captured.find("\"rect\":null,\"analysis_eligible\":false") != std::string::npos);
        }
        for (double angle : {std::numeric_limits<double>::infinity(), std::numeric_limits<double>::quiet_NaN()}) {
            setup_roi_fake353(); roi_fake353.rotation = angle; roi_expect_failure353("native_roi_nonfinite_rotation");
        }
        for (const auto& item : std::vector<std::pair<const char*,const char*>>{
            {"display-count-throw","surrogate_display_count_error"}, {"display-count-change","native_roi_display_set_changed"},
            {"display-missing","native_roi_display_missing"}, {"invalid-display","native_roi_display_invalid"},
            {"reverse-missing","native_roi_reverse_image_missing"}, {"roi-count-throw","surrogate_roi_count_error"},
            {"reverse-other","native_roi_reverse_image_mismatch"}, {"holder-id","native_roi_display_identity_changed"},
            {"roi-count-change","native_roi_set_changed"}, {"roi-missing","native_roi_lookup_mismatch"},
            {"roi-throw-after-acquire","surrogate_roi_lookup_error_after_acquire"},
            {"geometry-change","native_roi_snapshot_changed"}, {"dimensions","native_roi_display_dimensions_mismatch"},
            {"invalid-slice-id-count","native_roi_display_slice_id_invalid"}, {"slice-id-throw","surrogate_roi_slice_id_error"},
            {"nonfinite-mapping","native_roi_nonfinite_mapping"}, {"zero-mapping","native_roi_invalid_mapping"}}) {
            setup_roi_fake353(); roi_fault353 = item.first; roi_expect_failure353(item.second);
        }
        setup_roi_fake353(); roi_requested_displays353 = 17; roi_expect_failure353("native_roi_display_budget");
        check(roi_hold_created353 == 0);
        setup_roi_fake353(); roi_requested_count353 = 65; roi_expect_failure353("native_roi_count_budget");
        check(roi_at_calls353 == 0);
        setup_roi_fake353(); roi_requested_displays353 = 3; roi_requested_count353 = 64; roi_unique_identities353 = true;
        roi_expect_failure353("native_roi_count_budget"); check(roi_at_calls353 == 128);
        setup_roi_fake353(); roi_requested_count353 = 2; roi_expect_failure353("native_roi_identity_changed");
        setup_roi_fake353(); roi_requested_displays353 = 2; roi_expect_failure353("native_roi_display_identity_changed");
        for (float value : {std::numeric_limits<float>::infinity(), -std::numeric_limits<float>::infinity(), std::numeric_limits<float>::quiet_NaN()}) {
            setup_roi_fake353(); roi_fake353.coordinates.right = value; roi_expect_failure353("native_roi_nonfinite_rectangle");
        }
        setup_roi_fake353(); roi_table353[nb::kRasterRoiCountSlot353/8] = nullptr;
        roi_expect_failure353("native_roi_vtable_contract_mismatch"); check(roi_count_calls353 == 0);
        setup_roi_fake353(); roi_table353[nb::kRasterRoiSliceIdSlot353/8] = nullptr;
        roi_expect_failure353("native_roi_vtable_contract_mismatch"); check(roi_count_calls353 == 0);
        // A valid first-word refcount does not establish a full ROI layout.
        // On throw-after-write, abandon a truncated object and disable ABI
        // calls without decrementing it or entering the final deleter.
        {
            setup_roi_fake353(); SYSTEM_INFO system{}; GetSystemInfo(&system);
            auto* pages = static_cast<unsigned char*>(VirtualAlloc(nullptr, system.dwPageSize * 2,
                MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE));
            check(pages != nullptr);
            struct Pages { void* value; ~Pages() { VirtualFree(value, 0, MEM_RELEASE); } } guard{pages};
            DWORD old_protection = 0;
            check(VirtualProtect(pages + system.dwPageSize, system.dwPageSize, PAGE_NOACCESS, &old_protection) != FALSE);
            roi_partial_output353 = pages + system.dwPageSize - sizeof(LONG64);
            *static_cast<LONG64*>(roi_partial_output353) = 1;
            roi_partial_destroy_calls353 = 0;
            roi_api353.roi_at = roi_partial_throw_fake353;
            roi_api353.destroy_roi = roi_partial_destroy_fake353;
            roi_table353[nb::kRasterRoiGetSlot353/8] = reinterpret_cast<void*>(roi_partial_throw_fake353);
            roi_expect_failure353("native_roi_invalid_owned_reference");
            check(fatal_abi && roi_partial_destroy_calls353 == 0 && *static_cast<LONG64*>(roi_partial_output353) == 1);
            roi_partial_output353 = nullptr;
        }
        setup_roi_fake353(); fake.code = 3; roi_expect_failure353("native_roi_requires_bounded_ordinary_float32_or_uint32_2d");
        check(roi_display_count_calls353 == 0);
        setup_roi_fake353(); fake.dimensions = 3; roi_expect_failure353("native_roi_requires_bounded_ordinary_float32_or_uint32_2d");
        setup_roi_fake353(); fake.code = 11;
        check(run_roi_fake353().find("\"dtype\":\"uint32\"") != std::string::npos);
        // Common closed operation contract is readonly and keeps the caller's
        // exact image ID. Wrong arity is rejected before any vendor callback.
        const std::string session(32,'a');
        const auto operation = nb::parse_line("NB2 " + session + " rectangle ROIS 17");
        check(operation.request.args == std::vector<std::uint32_t>{17});
        check(std::string(nb::operation_contract("ROIS")->result_type) == "native_gui_rois");
        for (const char* args : {"", " 17 1", " -1"}) {
            try { nb::parse_line("NB2 " + session + " invalid ROIS" + args); check(false); }
            catch (const nb::ProtocolError&) { check(true); }
        }
        std::cout << assertions << " ROI adapter assertions passed (offline callbacks only)\n";
        return 0;
    } catch (const std::exception& error) { std::cerr << "FAIL " << error.what() << '\n'; return 1; }
}
