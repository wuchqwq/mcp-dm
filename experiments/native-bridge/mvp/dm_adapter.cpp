// Build-specific post-acquisition adapter. No SDK or vendor source code.
// Only explicit PODs cross the vendor boundary; see ABI_NOTES.md.
#include "adapter.hpp"
#include "core.hpp"
#include "crop_contract.hpp"
#include "show_contract.hpp"
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <bcrypt.h>
#include <winver.h>
#include <cmath>
#include <cstddef>
#include <iomanip>
#include <locale>
#include <map>
#include <set>
#include <sstream>
#include <stdexcept>

namespace {
struct NativeRef { void* image = nullptr; };
static_assert(sizeof(NativeRef) == 8 && alignof(NativeRef) == 8);
// This build's proven MSVC string layout, NOT a MinGW std::wstring.
struct MsvcWString353 {
    union { wchar_t small[8]; wchar_t* heap; } storage{};
    std::uint64_t length = 0, capacity = 7;
};
static_assert(sizeof(wchar_t) == 2 && sizeof(MsvcWString353) == 32);
static_assert(offsetof(MsvcWString353, length) == 16);
static_assert(offsetof(MsvcWString353, capacity) == 24);
using Find = NativeRef* (*)(NativeRef*, std::uint32_t);
using Getter = std::uint32_t (*)(const void*);
using Dimension = std::uint32_t (*)(const void*, std::int32_t);
using Calibration = void (*)(void*, std::uint32_t, float*, float*, void*, std::int32_t);
using Name = MsvcWString353* (*)(const void*, MsvcWString353*);
using Mean = double (*)(const NativeRef*);
using Reduction = double (*)(const NativeRef*);
using Crop = NativeRef* (*)(const void*, NativeRef*, const nb::NativeDataSlice353*);
using Delete = void (*)(void*);
using VendorFree = void (*)(void*);
using GetDocument = nb::ScriptImageDocument353* (*)(void*);
using ShowDocument = void* (*)(nb::ScriptImageDocument353*);
struct Api {
    Find find_id = nullptr, find_index = nullptr;
    std::uint32_t (*count)() = nullptr;
    Getter id = nullptr, ndim = nullptr, dtype = nullptr;
    Dimension dimension = nullptr;
    Calibration calibration = nullptr;
    Name name = nullptr;
    Mean mean = nullptr;
    Reduction minimum = nullptr, maximum = nullptr, sum = nullptr;
    Crop crop = nullptr;
    Delete destroy = nullptr;
    VendorFree deallocate = nullptr;
    GetDocument get_document = nullptr;
    ShowDocument show_document = nullptr;
    Delete destroy_document_holder = nullptr, destroy_window = nullptr;
} api;
DWORD host_thread = 0;
std::string gate_error = "native_adapter_not_initialized";
bool fatal_abi = false;
struct RetainedCrop { NativeRef value; std::uint64_t bytes; };
std::map<std::uint32_t, RetainedCrop> retained_crops;
std::uint64_t retained_crop_bytes = 0;

struct WinHandle {
    HANDLE value;
    explicit WinHandle(HANDLE v) : value(v) {}
    ~WinHandle() { if (value != INVALID_HANDLE_VALUE && value) CloseHandle(value); }
};
std::wstring module_path(HMODULE module) {
    std::vector<wchar_t> path(32768);
    DWORD n = GetModuleFileNameW(module, path.data(), static_cast<DWORD>(path.size()));
    if (!n || n >= path.size()) throw std::runtime_error("module_path_unavailable");
    return std::wstring(path.data(), n);
}
void require_build_version(HMODULE module) {
    auto path = module_path(module);
    DWORD ignored = 0;
    DWORD n = GetFileVersionInfoSizeW(path.c_str(), &ignored);
    if (!n || n > 1048576) throw std::runtime_error("host_version_unavailable");
    std::vector<unsigned char> data(n);
    if (!GetFileVersionInfoW(path.c_str(), 0, n, data.data()))
        throw std::runtime_error("host_version_unavailable");
    VS_FIXEDFILEINFO* version = nullptr;
    UINT size = 0;
    if (!VerQueryValueW(data.data(), L"\\", reinterpret_cast<void**>(&version), &size)
        || size < sizeof(*version) || version->dwSignature != 0xfeef04bd
        || version->dwFileVersionMS != ((3u << 16) | 53u)
        || version->dwFileVersionLS != (4137u << 16))
        throw std::runtime_error("unsupported_gms_build");
}
std::string sha256(HMODULE module) {
    auto path = module_path(module);
    WinHandle file(CreateFileW(path.c_str(), GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_DELETE,
                              nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr));
    if (file.value == INVALID_HANDLE_VALUE) throw std::runtime_error("module_hash_open_failed");
    BCRYPT_ALG_HANDLE algorithm = nullptr;
    BCRYPT_HASH_HANDLE hash = nullptr;
    if (BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, nullptr, 0) < 0)
        throw std::runtime_error("sha256_provider_failed");
    struct Guard {
        BCRYPT_ALG_HANDLE& a; BCRYPT_HASH_HANDLE& h;
        ~Guard() { if (h) BCryptDestroyHash(h); if (a) BCryptCloseAlgorithmProvider(a, 0); }
    } guard{algorithm, hash};
    if (BCryptCreateHash(algorithm, &hash, nullptr, 0, nullptr, 0, 0) < 0)
        throw std::runtime_error("sha256_create_failed");
    unsigned char buffer[32768], digest[32];
    DWORD n = 0;
    for (;;) {
        if (!ReadFile(file.value, buffer, sizeof(buffer), &n, nullptr))
            throw std::runtime_error("module_hash_read_failed");
        if (!n) break;
        if (BCryptHashData(hash, buffer, n, 0) < 0) throw std::runtime_error("sha256_update_failed");
    }
    if (BCryptFinishHash(hash, digest, sizeof(digest), 0) < 0)
        throw std::runtime_error("sha256_finish_failed");
    constexpr char hex[] = "0123456789abcdef";
    std::string result;
    for (auto byte : digest) { result += hex[byte >> 4]; result += hex[byte & 15]; }
    return result;
}
HMODULE checked_module(const wchar_t* name, const char* fingerprint, bool gms = true) {
    HMODULE module = GetModuleHandleW(name);
    if (!module) throw std::runtime_error("required_vendor_module_not_loaded");
    if (gms) require_build_version(module);
    if (sha256(module) != fingerprint) throw std::runtime_error("unsupported_vendor_binary");
    return module;
}
template<class T> T symbol(HMODULE module, const char* name) {
    FARPROC p = GetProcAddress(module, name);
    if (!p) throw std::runtime_error("required_native_symbol_missing");
    return reinterpret_cast<T>(p);
}
bool accessible_memory(const void* pointer, std::size_t bytes, bool writable = false) noexcept {
    auto address = reinterpret_cast<std::uintptr_t>(pointer);
    if (!address || bytes > UINTPTR_MAX - address) return false;
    const auto end = address + bytes;
    while (address < end) {
        MEMORY_BASIC_INFORMATION region{};
        if (VirtualQuery(reinterpret_cast<void*>(address), &region, sizeof(region)) != sizeof(region) ||
            region.State != MEM_COMMIT || (region.Protect & (PAGE_GUARD | PAGE_NOACCESS))) return false;
        const auto protection = region.Protect & 0xff;
        const bool can_write = protection == PAGE_READWRITE || protection == PAGE_WRITECOPY ||
            protection == PAGE_EXECUTE_READWRITE || protection == PAGE_EXECUTE_WRITECOPY;
        if (writable ? !can_write : !(can_write || protection == PAGE_READONLY || protection == PAGE_EXECUTE_READ))
            return false;
        const auto base = reinterpret_cast<std::uintptr_t>(region.BaseAddress);
        if (region.RegionSize > UINTPTR_MAX - base) return false;
        const auto next = base + region.RegionSize;
        if (next <= address) return false;
        address = next;
    }
    return true;
}
template<class T> T rva_symbol(HMODULE module, std::uint32_t rva) {
    const auto* base = reinterpret_cast<const unsigned char*>(module);
    if (!accessible_memory(base, sizeof(IMAGE_DOS_HEADER)))
        throw std::runtime_error("invalid_native_module_headers");
    const auto* dos = reinterpret_cast<const IMAGE_DOS_HEADER*>(base);
    if (dos->e_magic != IMAGE_DOS_SIGNATURE || dos->e_lfanew < 0 || dos->e_lfanew > 1048576 ||
        !accessible_memory(base + dos->e_lfanew, sizeof(IMAGE_NT_HEADERS64)))
        throw std::runtime_error("invalid_native_module_headers");
    const auto* nt = reinterpret_cast<const IMAGE_NT_HEADERS64*>(base + dos->e_lfanew);
    if (nt->Signature != IMAGE_NT_SIGNATURE || nt->FileHeader.Machine != IMAGE_FILE_MACHINE_AMD64 ||
        nt->OptionalHeader.Magic != IMAGE_NT_OPTIONAL_HDR64_MAGIC ||
        nt->FileHeader.SizeOfOptionalHeader != sizeof(IMAGE_OPTIONAL_HEADER64) ||
        !nt->FileHeader.NumberOfSections || nt->FileHeader.NumberOfSections > 96 ||
        rva < nt->OptionalHeader.SizeOfHeaders || rva >= nt->OptionalHeader.SizeOfImage)
        throw std::runtime_error("native_entrypoint_outside_image");
    const auto* sections = IMAGE_FIRST_SECTION(nt);
    if (!accessible_memory(sections, sizeof(*sections) * nt->FileHeader.NumberOfSections))
        throw std::runtime_error("invalid_native_module_headers");
    bool executable_section = false;
    for (unsigned i = 0; i < nt->FileHeader.NumberOfSections; ++i) {
        const auto& section = sections[i];
        const auto length = section.Misc.VirtualSize > section.SizeOfRawData ? section.Misc.VirtualSize : section.SizeOfRawData;
        const auto end = static_cast<std::uint64_t>(section.VirtualAddress) + length;
        if (rva >= section.VirtualAddress && rva < end && end <= nt->OptionalHeader.SizeOfImage &&
            (section.Characteristics & IMAGE_SCN_MEM_EXECUTE)) executable_section = true;
    }
    MEMORY_BASIC_INFORMATION region{};
    const auto* address = base + rva;
    if (!executable_section || VirtualQuery(address, &region, sizeof(region)) != sizeof(region) ||
        region.State != MEM_COMMIT || region.Type != MEM_IMAGE || region.AllocationBase != module ||
        (region.Protect & (PAGE_GUARD | PAGE_NOACCESS)))
        throw std::runtime_error("native_entrypoint_not_executable");
    const auto protection = region.Protect & 0xff;
    if (protection != PAGE_EXECUTE && protection != PAGE_EXECUTE_READ &&
        protection != PAGE_EXECUTE_READWRITE && protection != PAGE_EXECUTE_WRITECOPY)
        throw std::runtime_error("native_entrypoint_not_executable");
    return reinterpret_cast<T>(const_cast<unsigned char*>(address));
}
volatile LONG64* reference_counter(void* pointer, std::size_t offset) noexcept {
    const auto address = reinterpret_cast<std::uintptr_t>(pointer);
    if (!address || offset > UINTPTR_MAX - address) return nullptr;
    auto* count = reinterpret_cast<volatile LONG64*>(address + offset);
    if (reinterpret_cast<std::uintptr_t>(count) % alignof(LONG64) ||
        !accessible_memory(const_cast<const LONG64*>(count), sizeof(*count), true)) return nullptr;
    return count;
}
void release_show_reference(void*& pointer, std::size_t offset, Delete destroy) noexcept {
    void* object = pointer;
    pointer = nullptr;
    if (!object) return;
    auto* count = reference_counter(object, offset);
    if (!count || InterlockedCompareExchange64(count, 0, 0) <= 0) { fatal_abi = true; return; }
    const auto remaining = InterlockedDecrement64(count);
    if (remaining == 0) { if (destroy) destroy(object); else fatal_abi = true; }
    if (remaining < 0) fatal_abi = true;
}
class ShowRef {
    const std::size_t offset_;
    const Delete destroy_;
public:
    void* value;
    ShowRef(void* pointer, std::size_t offset, Delete destroy) : offset_(offset), destroy_(destroy), value(pointer) {}
    ShowRef(const ShowRef&) = delete;
    ~ShowRef() { release_show_reference(value, offset_, destroy_); }
    void abandon_invalid_layout() noexcept { value = nullptr; }
};
void validate_show_reference(void* pointer, std::size_t offset) {
    auto* count = reference_counter(pointer, offset);
    if (!count || InterlockedCompareExchange64(count, 0, 0) <= 0) {
        fatal_abi = true;
        throw std::runtime_error("native_show_invalid_reference_layout");
    }
}
void release_image(NativeRef& value) noexcept {
    if (!value.image) return;
    void* image = value.image;
    value.image = nullptr;
    // ref_ptr_delete is a final destructor, never a release operation.
    const auto remaining = InterlockedDecrement64(static_cast<volatile LONG64*>(image));
    if (remaining == 0) {
        if (api.destroy) api.destroy(image); else fatal_abi = true;
    }
    if (remaining < 0) fatal_abi = true;
}
class ImageRef {
public:
    NativeRef value;
    ImageRef() = default;
    explicit ImageRef(Find find, std::uint32_t id) {
        find(&value, id);
        if (!value.image) throw std::runtime_error("image_not_found");
    }
    ImageRef(const ImageRef&) = delete;
    ~ImageRef() { release_image(value); }
    void reset() noexcept { release_image(value); }
    void relinquish() noexcept { value.image = nullptr; }
};
class VendorString {
public:
    MsvcWString353 value;
    VendorString() = default;
    VendorString(const VendorString&) = delete;
    ~VendorString() noexcept {
        // Malformed ABI output latches the whole adapter off. Leaking an
        // unidentifiable allocation is safer than freeing a guessed pointer.
        if (value.length > value.capacity || value.capacity > (UINT64_MAX / 2) - 1) {
            fatal_abi = true; return;
        }
        if (value.capacity <= 7) return;
        void* memory = value.storage.heap;
        if (!memory) { fatal_abi = true; return; }
        if ((value.capacity + 1) * 2 >= 4096) {
            auto aligned = reinterpret_cast<std::uintptr_t>(memory);
            if (aligned % 32 != 0) { fatal_abi = true; return; }
            auto base = reinterpret_cast<std::uintptr_t>(reinterpret_cast<void**>(memory)[-1]);
            if (base >= aligned || aligned - base < 8 || aligned - base > 39) {
                fatal_abi = true; return;
            }
            memory = reinterpret_cast<void*>(base);
        }
        api.deallocate(memory);
        value = MsvcWString353{};
    }
    std::string utf8(std::size_t maximum) const {
        if (value.length > value.capacity || value.length > maximum)
            throw std::runtime_error("vendor_string_over_budget");
        const wchar_t* text = value.capacity <= 7 ? value.storage.small : value.storage.heap;
        if (!text || text[value.length] != 0) throw std::runtime_error("invalid_vendor_string");
        if (!value.length) return {};
        int n = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, text,
                                   static_cast<int>(value.length), nullptr, 0, nullptr, nullptr);
        if (n <= 0) throw std::runtime_error("invalid_vendor_unicode");
        std::string out(n, '\0');
        if (WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, text,
              static_cast<int>(value.length), &out[0], n, nullptr, nullptr) != n)
            throw std::runtime_error("vendor_unicode_conversion_failed");
        return out;
    }
};
std::ostringstream json_stream() {
    std::ostringstream s;
    s.imbue(std::locale::classic());
    s << std::setprecision(17);
    return s;
}
void require_ready();
std::string metadata(void* image, bool strict_calibration = true) {
    auto ndim = api.ndim(image), code = api.dtype(image);
    if (ndim < 1 || ndim > 4) throw std::runtime_error("unsupported_dimension_count");
    std::vector<std::uint32_t> sizes;
    std::uint64_t pixels = 1;
    for (std::uint32_t d = 0; d < ndim; ++d) {
        auto n = api.dimension(image, static_cast<std::int32_t>(d));
        if (!n || pixels > UINT64_MAX / n) throw std::runtime_error("invalid_image_dimensions");
        sizes.push_back(n); pixels *= n;
    }
    VendorString name;
    api.name(image, &name.value);
    auto s = json_stream();
    s << "{\"id\":" << api.id(image) << ",\"name\":" << nb::quote(name.utf8(1024))
      << ",\"ndim\":" << ndim << ",\"data_type_code\":" << code
      << ",\"dtype\":" << (code == 2 ? "\"float32\"" : "null")
      << ",\"shape\":[";
    for (std::uint32_t i = 0; i < ndim; ++i) { if (i) s << ','; s << sizes[ndim - i - 1]; }
    s << "],\"dm_dimensions\":[";
    for (std::uint32_t i = 0; i < ndim; ++i) { if (i) s << ','; s << sizes[i]; }
    s << "],\"shape_order\":\"numpy (last axis is X)\",\"pixels\":" << pixels
      << ",\"calibration\":[";
    bool calibration_complete = true;
    for (std::uint32_t d = 0; d < ndim; ++d) {
        require_ready();
        float zero = 0, scale = 0, raw_origin = 0, raw_scale = 0;
        VendorString unit;
        api.calibration(image, d, &zero, &scale, &unit.value, 0);
        api.calibration(image, d, &raw_origin, &raw_scale, nullptr, 1);
        bool numbers_valid = std::isfinite(zero) && std::isfinite(scale) && scale != 0
            && std::isfinite(raw_origin) && raw_scale == scale;
        if (!numbers_valid && strict_calibration) throw std::runtime_error("invalid_image_calibration");
        auto units = unit.utf8(256);
        if (units.empty() && strict_calibration) throw std::runtime_error("unknown_image_units");
        bool valid = numbers_valid && !units.empty();
        calibration_complete = calibration_complete && valid;
        if (d) s << ',';
        s << "{\"dm_dimension\":" << d << ",\"numpy_axis\":" << ndim - d - 1
          << ",\"size\":" << sizes[d] << ",\"origin\":";
        if (std::isfinite(raw_origin)) s << raw_origin; else s << "null";
        s << ",\"calibrated_value_at_pixel_zero\":";
        if (std::isfinite(zero)) s << zero; else s << "null";
        s << ",\"scale\":";
        if (std::isfinite(scale)) s << scale; else s << "null";
        s << ",\"unit\":" << (units.empty() ? "null" : nb::quote(units))
          << ",\"usable\":" << (valid ? "true" : "false")
          << ",\"issue\":" << (valid ? "null" : !numbers_valid ?
              (units.empty() ? "\"invalid_calibration_and_unknown_units\"" : "\"invalid_calibration\"") :
              "\"unknown_units\"") << '}';
    }
    require_ready();
    s << "],\"calibration_complete\":" << (calibration_complete ? "true" : "false")
      << ",\"native_mean_supported\":" << (code == 2 && ndim == 2 && pixels <= 4194304 ? "true" : "false")
      << ",\"native_summary_supported\":" << (code == 2 && ndim == 2 && pixels <= 4194304 ? "true" : "false")
      << ",\"coordinate_rule\":\"physical(i)=calibrated_value_at_pixel_zero+i*scale\"}";
    return s.str();
}
void require_ready() {
    if (GetCurrentThreadId() != host_thread) throw std::runtime_error("wrong_native_execution_thread");
    if (fatal_abi) throw std::runtime_error("native_abi_invalid_output_path_disabled");
    if (!gate_error.empty()) throw std::runtime_error(gate_error);
}
struct CropAxisCalibration {
    float zero = 0, scale = 0, origin = 0;
    std::string unit;
    bool operator==(const CropAxisCalibration& other) const {
        return zero == other.zero && scale == other.scale && origin == other.origin && unit == other.unit;
    }
};
CropAxisCalibration crop_axis_calibration(void* image, std::uint32_t axis) {
    CropAxisCalibration result;
    float raw_scale = 0;
    {
        VendorString unit;
        api.calibration(image, axis, &result.zero, &result.scale, &unit.value, 0);
        api.calibration(image, axis, &result.origin, &raw_scale, nullptr, 1);
        result.unit = unit.utf8(256);
    }
    require_ready();
    if (!std::isfinite(result.zero) || !std::isfinite(result.scale) || result.scale == 0 ||
        !std::isfinite(result.origin) || raw_scale != result.scale || result.unit.empty())
        throw std::runtime_error("native_crop_requires_valid_calibration");
    return result;
}
std::array<CropAxisCalibration, 2> crop_calibration(void* image) {
    return {crop_axis_calibration(image, 0), crop_axis_calibration(image, 1)};
}
void write_rect(std::ostringstream& s, const std::array<std::uint32_t, 4>& rect) {
    s << '[' << rect[0] << ',' << rect[1] << ',' << rect[2] << ',' << rect[3] << ']';
}
std::string execute_show(const NativeRequest& request) {
    if (request.args.size() != 1) throw std::runtime_error("native_show_requires_one_image_id");
    const auto id = request.args[0];
    const auto owned = retained_crops.find(id);
    if (!id || owned == retained_crops.end()) throw std::runtime_error("native_show_requires_plugin_crop");
    ImageRef image(api.find_id, id);
    if (image.value.image != owned->second.value.image || api.id(image.value.image) != id)
        throw std::runtime_error("image_identity_mismatch");
    if (!api.get_document || !api.show_document || !api.destroy_document_holder || !api.destroy_window)
        throw std::runtime_error("native_show_entrypoint_unavailable");
    // Finish bounded local result construction before requesting any UI change.
    auto s = json_stream();
    s << "{\"backend\":\"digitalmicrograph-native\",\"image_id\":" << id
      << ",\"delivery\":\"visible_dm_document\",\"document_visible\":true"
      << ",\"operator\":\"ImageGetOrCreateImageDocument + ImageDocumentShow\""
      << ",\"ownership\":\"host document holds image; plugin crop reference released at normal STOP/cleanup\""
      << ",\"source_write_requested\":false,\"snapshot_atomic\":false"
      << ",\"file_saved\":false,\"model_visual_verification\":false}";
    const auto result = s.str();
    if (!nb::valid_json(result)) throw std::runtime_error("native_show_result_invalid");
    require_ready();
    ShowRef holder(api.get_document(image.value.image), 0, api.destroy_document_holder);
    if (!holder.value) throw std::runtime_error("native_show_document_unavailable");
    validate_show_reference(holder.value, 0);
    auto* document = static_cast<nb::ScriptImageDocument353*>(holder.value);
    // Do not invoke a destructor that could follow a malformed document pointer.
    if (!accessible_memory(document, sizeof(*document)) || !document->document ||
        !reference_counter(document->document, 8) ||
        InterlockedCompareExchange64(reference_counter(document->document, 8), 0, 0) <= 0) {
        fatal_abi = true;
        holder.abandon_invalid_layout();
        throw std::runtime_error("native_show_invalid_document_layout");
    }
    require_ready();
    ShowRef window(api.show_document(document), nb::kNativeWindowReferenceOffset353, api.destroy_window);
    if (!window.value) throw std::runtime_error("native_show_window_unavailable");
    validate_show_reference(window.value, nb::kNativeWindowReferenceOffset353);
    require_ready();
    // Reverse-order guards release our Window and holder references here. No
    // document/window is retained by the plugin or closed during native STOP.
    return result;
}
std::string execute_crop(const NativeRequest& request) {
    if (request.args.size() != 5) throw std::runtime_error("native_crop_requires_id_and_rect");
    ImageRef source(api.find_id, request.args[0]);
    void* source_image = source.value.image;
    if (api.id(source_image) != request.args[0]) throw std::runtime_error("image_identity_mismatch");
    if (api.ndim(source_image) != 2 || api.dtype(source_image) != 2)
        throw std::runtime_error("native_crop_requires_float32_2d");
    const auto width = api.dimension(source_image, 0), height = api.dimension(source_image, 1);
    const auto plan = nb::crop_plan(width, height,
        {request.args[1], request.args[2], request.args[3], request.args[4]},
        retained_crop_bytes, retained_crops.size());
    if (!api.crop) throw std::runtime_error("native_crop_symbol_unavailable");
    // All dimensions, rectangle and retained-output budgets precede allocation.
    const auto source_info = metadata(source_image);
    require_ready();
    const auto source_calibration = crop_calibration(source_image);
    ImageRef output;
    if (api.crop(source_image, &output.value, &plan.slice) != &output.value || !output.value.image)
        throw std::runtime_error("native_crop_no_output_reference");
    require_ready();
    void* output_image = output.value.image;
    const auto output_id = api.id(output_image);
    if (output_image == source_image || !output_id || output_id == request.args[0] || retained_crops.count(output_id))
        throw std::runtime_error("native_crop_output_identity_invalid");
    if (api.ndim(output_image) != 2 || api.dtype(output_image) != 2 ||
        api.dimension(output_image, 0) != plan.width || api.dimension(output_image, 1) != plan.height)
        throw std::runtime_error("native_crop_output_descriptor_mismatch");
    const auto output_info = metadata(output_image);
    require_ready();
    const auto output_calibration = crop_calibration(output_image);
    std::array<nb::CropZeroCheck, 2> zero_checks;
    for (unsigned axis = 0; axis < 2; ++axis) {
        const auto& before = source_calibration[axis];
        const auto& after = output_calibration[axis];
        const float expected_origin = before.origin - static_cast<float>(plan.rect[axis]);
        zero_checks[axis] = nb::crop_zero_check(before.zero, before.scale, before.origin,
                                              plan.rect[axis], after.zero);
        if (after.unit != before.unit || after.scale != before.scale || after.origin != expected_origin ||
            zero_checks[axis].absolute_error > zero_checks[axis].tolerance)
            throw std::runtime_error("native_crop_output_calibration_mismatch");
    }
    // Matching descriptors/calibration do not establish an atomic pixel snapshot.
    // This operation is admitted only under the documented idle/no-edit contract.
    if (api.id(source_image) != request.args[0] || api.ndim(source_image) != 2 || api.dtype(source_image) != 2 ||
        api.dimension(source_image, 0) != width || api.dimension(source_image, 1) != height ||
        crop_calibration(source_image) != source_calibration || metadata(source_image) != source_info)
        throw std::runtime_error("native_crop_source_descriptor_changed");
    require_ready();
    auto s = json_stream();
    s << "{\"backend\":\"digitalmicrograph-native\",\"source_image_id\":" << request.args[0]
      << ",\"image_id\":" << output_id << ",\"requested_rect\":";
    write_rect(s, plan.rect);
    s << ",\"effective_rect\":"; write_rect(s, plan.rect);
    s << ",\"rect_convention\":\"zero-based half-open [x0,y0,x1,y1]\",\"source\":" << source_info
      << ",\"image\":" << output_info << ",\"operator\":\"GMS::Image::GetSubSliceAsImage\""
      << ",\"computation\":\"DM native independent pixel copy\",\"output_bytes\":" << plan.bytes
      << ",\"ownership\":\"plugin retained strong reference until normal native STOP/cleanup\""
      << ",\"visible_dm_document\":false,\"source_write_requested\":false,\"snapshot_atomic\":false"
      << ",\"calibration_zero_verification\":[";
    for (unsigned axis = 0; axis < 2; ++axis) {
        if (axis) s << ',';
        s << "{\"dm_dimension\":" << axis << ",\"expected\":" << zero_checks[axis].expected
          << ",\"absolute_error\":" << zero_checks[axis].absolute_error
          << ",\"tolerance\":" << zero_checks[axis].tolerance << '}';
    }
    s << "],\"calibration_tolerance_rule\":\"propagated binary32 half-ULPs of source zero, shifted index origin and output zero\"}";
    auto result = s.str();
    if (!nb::valid_json(result)) throw std::runtime_error("native_crop_result_over_budget_or_invalid");
    source.reset();
    require_ready();
    // Commit ownership last. A failed validation or allocation leaves output's
    // guard responsible for its single reference; the weak registry cannot own it.
    const auto inserted = retained_crops.emplace(output_id, RetainedCrop{output.value, plan.bytes});
    if (!inserted.second) throw std::runtime_error("native_crop_output_identity_invalid");
    retained_crop_bytes += plan.bytes;
    output.relinquish();
    return result;
}
} // namespace

void initialize_native() {
    host_thread = GetCurrentThreadId();
    try {
        checked_module(nullptr, "2f03ccd751b2abc7f55d3bda5b975895c3527660a03080618005a134d6fbfddb");
        auto image = checked_module(L"GMSImage.dll",
            "0d8e22006a1023eb9f0de2b497ef1629c5a22c562741d3e4b0405d308590da3b");
        auto processing = checked_module(L"GMSImageProcessing.dll",
            "6be3044d049b6b2184404ea5adc2588d0677ae9b2f78ceb80169d315aef82042");
        auto gms = checked_module(L"GMS.dll",
            "9056884e38c090b7fff1cefe70150dc49d10dbc1f823fed6c7a661d255c01f93");
        auto mfc = checked_module(L"mfc140.dll",
            "b784303d86232a1b316c79839aa78bf631b4fc182e55d9d947688adb066dff26", false);
        api.find_id = symbol<Find>(image, "?FindByID@Image@GMS@@SA?AV?$ref_ptr@VImage@GMS@@@Gatan@@K@Z");
        api.find_index = symbol<Find>(image, "?FindByIndex@Image@GMS@@SA?AV?$ref_ptr@VImage@GMS@@@Gatan@@K@Z");
        api.count = symbol<decltype(api.count)>(image, "?CountAllImages@Image@GMS@@SAKXZ");
        api.id = symbol<Getter>(image, "?GetID@Image@GMS@@QEBAKXZ");
        api.ndim = symbol<Getter>(image, "?GetDimensions@Image@GMS@@QEBAKXZ");
        api.dtype = symbol<Getter>(image, "?GetDataType@Image@GMS@@QEBAKXZ");
        api.dimension = symbol<Dimension>(image, "?GetNthDimension@Image@GMS@@QEBAKJ@Z");
        api.calibration = symbol<Calibration>(image,
            "?GetDimensionCalibration@Image@GMS@@QEAAXKPEAM0PEAV?$basic_string@_WU?$char_traits@_W@std@@V?$allocator@_W@2@@std@@J@Z");
        api.name = symbol<Name>(image,
            "?GetUnicodeName@Image@GMS@@QEBA?AV?$basic_string@_WU?$char_traits@_W@std@@V?$allocator@_W@2@@std@@XZ");
        api.mean = symbol<Mean>(processing,
            "?GetMean@GMSImageProcessing@@YANAEBV?$ref_ptr@VImage@GMS@@@Gatan@@@Z");
        api.minimum = symbol<Reduction>(processing,
            "?GetMinimum@GMSImageProcessing@@YANAEBV?$ref_ptr@VImage@GMS@@@Gatan@@@Z");
        api.maximum = symbol<Reduction>(processing,
            "?GetMaximum@GMSImageProcessing@@YANAEBV?$ref_ptr@VImage@GMS@@@Gatan@@@Z");
        api.sum = symbol<Reduction>(processing,
            "?GetSum@GMSImageProcessing@@YANAEBV?$ref_ptr@VImage@GMS@@@Gatan@@@Z");
        api.destroy = symbol<Delete>(image, "?ref_ptr_delete@Gatan@@YAXPEAVImage@GMS@@@Z");
        api.deallocate = symbol<VendorFree>(mfc, MAKEINTRESOURCEA(1487));
        api.crop = symbol<Crop>(image,
            "?GetSubSliceAsImage@Image@GMS@@QEBA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBVDataSlice@Imaging@4@@Z");
        api.get_document = rva_symbol<GetDocument>(gms, 0x4c3040);
        api.show_document = rva_symbol<ShowDocument>(gms, 0x4b8a20);
        api.destroy_document_holder = rva_symbol<Delete>(gms, 0x060e70);
        api.destroy_window = rva_symbol<Delete>(gms, 0x57bab0);
        gate_error.clear();
    } catch (const std::exception& error) { gate_error = error.what(); }
}

static std::string execute_operation(const NativeRequest& request) {
    if (request.op == "STATUS") {
        auto s = json_stream();
        s << "{\"backend\":\"digitalmicrograph-native\",\"ready\":" << (gate_error.empty() && !fatal_abi ? "true" : "false")
          << ",\"supported_build\":\"3.53.4137.0-x64\",\"binary_gate\":" << (gate_error.empty() ? "true" : "false")
          << ",\"host_pid\":" << GetCurrentProcessId() << ",\"host_thread\":" << host_thread
          << ",\"resident_python_required\":false,\"arbitrary_script\":false,\"requires_idle_host\":true"
          << ",\"capabilities\":[\"datasets\",\"image_info\",\"mean_float32_2d\",\"summary_float32_2d\",\"crop_float32_2d\",\"show_plugin_crop_visible_document\"]"
          << ",\"retained_crop_count\":" << retained_crops.size() << ",\"retained_crop_bytes\":" << retained_crop_bytes
          << ",\"build_error\":" << (fatal_abi ? "\"native_abi_invalid_output_path_disabled\"" : gate_error.empty() ? "null" : nb::quote(gate_error)) << '}';
        return s.str();
    }
    require_ready();
    if (request.op == "SHOW") return execute_show(request);
    if (request.op == "CROP") return execute_crop(request);
    if (request.op == "DATASETS") {
        auto count = api.count();
        if (count > 128) throw std::runtime_error("dataset_enumeration_over_budget");
        auto s = json_stream();
        std::set<std::uint32_t> ids;
        s << "{\"backend\":\"digitalmicrograph-native\",\"datasets\":[";
        for (std::uint32_t i = 0; i < count; ++i) {
            require_ready();
            ImageRef image(api.find_index, i);
            auto id = api.id(image.value.image);
            if (!ids.insert(id).second) throw std::runtime_error("dataset_enumeration_changed");
            if (i) s << ',';
            s << metadata(image.value.image, false);
            require_ready();
        }
        require_ready();
        if (api.count() != count) throw std::runtime_error("dataset_enumeration_changed");
        s << "],\"count\":" << count << ",\"complete\":true,\"snapshot_atomic\":false"
          << ",\"enumeration_scope\":\"native registry including hidden utility images\"}";
        return s.str();
    }
    if (request.op == "INFO" || request.op == "MEAN" || request.op == "SUMMARY") {
        const bool summary = request.op == "SUMMARY";
        if (summary && request.args.size() != 1)
            throw std::runtime_error("native_summary_requires_one_image_id");
        if (summary && (!api.minimum || !api.maximum || !api.sum || !api.mean))
            throw std::runtime_error("native_summary_not_available");
        ImageRef image(api.find_id, request.args.at(0));
        if (api.id(image.value.image) != request.args[0]) throw std::runtime_error("image_identity_mismatch");
        if (request.op == "INFO") {
            // First real-host probe deliberately avoids strings/calibration and
            // processing. Accept numeric identity/dimensions before those APIs.
            auto dims = api.ndim(image.value.image);
            if (dims < 1 || dims > 4) throw std::runtime_error("unsupported_dimension_count");
            auto s = json_stream();
            s << "{\"backend\":\"digitalmicrograph-native\",\"image_id\":" << request.args[0]
              << ",\"ndim\":" << dims << ",\"data_type_code\":" << api.dtype(image.value.image)
              << ",\"dm_dimensions\":[";
            for (std::uint32_t d = 0; d < dims; ++d) {
                if (d) s << ',';
                auto size = api.dimension(image.value.image, static_cast<std::int32_t>(d));
                if (!size) throw std::runtime_error("invalid_image_dimensions");
                s << size;
            }
            s << "]}";
            return s.str();
        }
        require_ready();
        if (api.ndim(image.value.image) != 2 || api.dtype(image.value.image) != 2)
            throw std::runtime_error(summary ? "native_summary_requires_float32_2d" : "native_mean_requires_float32_2d");
        auto w = api.dimension(image.value.image, 0), h = api.dimension(image.value.image, 1);
        if (!w || !h) throw std::runtime_error("invalid_image_dimensions");
        if (static_cast<std::uint64_t>(w) * h > 4194304)
            throw std::runtime_error(summary ? "native_summary_working_region_over_budget" : "native_mean_working_region_over_budget");
        // Raw intensity does not depend on a usable spatial calibration. Keep
        // recognized missing/invalid calibration visible in metadata, while
        // propagating vendor, object-identity and ABI failures unchanged.
        auto info = metadata(image.value.image, false);
        require_ready();
        if (summary) {
            const auto finite_result = [](double value) {
                if (!std::isfinite(value)) throw std::runtime_error("native_summary_nonfinite_result");
                return value;
            };
            // Four native reductions, never a C++ numerical kernel or a value
            // derived from another field. Raw intensity is a candidate semantic
            // contract that needs independent nontrivial intensity-calibration
            // acceptance before this new operation is qualified on a real host.
            const double minimum = finite_result(api.minimum(&image.value));
            require_ready();
            const double maximum = finite_result(api.maximum(&image.value));
            require_ready();
            const double sum = finite_result(api.sum(&image.value));
            require_ready();
            const double mean = finite_result(api.mean(&image.value));
            require_ready();
            auto s = json_stream();
            s << "{\"backend\":\"digitalmicrograph-native\",\"image_id\":" << request.args[0]
              << ",\"image\":" << info << ",\"minimum\":" << minimum << ",\"maximum\":" << maximum
              << ",\"sum\":" << sum << ",\"mean\":" << mean
              << ",\"operators\":[\"GMSImageProcessing::GetMinimum\",\"GMSImageProcessing::GetMaximum\",\"GMSImageProcessing::GetSum\",\"GMSImageProcessing::GetMean\"]"
              << ",\"computation\":\"DM native\",\"intensity_calibration_applied\":false"
              << ",\"intensity_semantics\":\"raw pixel intensity\",\"source_write_requested\":false,\"snapshot_atomic\":false}";
            return s.str();
        }
        double mean = api.mean(&image.value);
        if (!std::isfinite(mean)) throw std::runtime_error("native_mean_nonfinite_result");
        auto s = json_stream();
        s << "{\"backend\":\"digitalmicrograph-native\",\"image_id\":" << request.args[0]
          << ",\"image\":" << info << ",\"mean\":" << mean
          << ",\"operator\":\"GMSImageProcessing::GetMean\",\"computation\":\"DM native\""
          << ",\"intensity_calibration_applied\":false,\"intensity_semantics\":\"raw pixel intensity\""
          << ",\"source_write_requested\":false,\"snapshot_atomic\":false}";
        return s.str();
    }
    throw std::runtime_error("unsupported_native_operation");
}
std::string execute_native(const NativeRequest& request) {
    auto result = execute_operation(request);
    // Guards have now released all temporary vendor objects. A malformed
    // destructor output must turn this operation into a failure too.
    if (request.op != "STATUS") require_ready();
    return result;
}
void shutdown_native() {
    for (auto& crop : retained_crops) release_image(crop.second.value);
    retained_crops.clear();
    retained_crop_bytes = 0;
    api = Api{};
    gate_error = "native_adapter_stopped";
}
