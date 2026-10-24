// Build-specific post-acquisition adapter. No SDK or vendor source code.
// Only explicit PODs cross the vendor boundary; see ABI_NOTES.md.
#include "adapter.hpp"
#include "core.hpp"
#include "crop_contract.hpp"
#include "show_contract.hpp"
#include "result_contract.hpp"
#include "fft_contract.hpp"
#include "preview_contract.hpp"
#include "read_contract.hpp"
#include "adapters/gms_3_53_4137/profile.hpp"
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <bcrypt.h>
#include <winver.h>
#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <cstddef>
#include <iomanip>
#include <locale>
#include <map>
#include <memory>
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
using Unary = NativeRef* (*)(NativeRef*, const NativeRef*);
using Binary = NativeRef* (*)(NativeRef*, const NativeRef*, const NativeRef*);
using Packing = nb::NativePacking353* (*)(const void*, nb::NativePacking353*);
using RealValue = double (*)(const void*, const nb::NativeDataIndex2D353*);
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
    Unary negate = nullptr, abs = nullptr, square = nullptr;
    Binary add = nullptr, subtract = nullptr, multiply = nullptr;
    Unary real_fft = nullptr, ifft = nullptr, real_component = nullptr, imag_component = nullptr, arg = nullptr, norm = nullptr;
    Unary smooth_filter = nullptr, sobel_filter = nullptr, laplace_filter = nullptr, sharpen_filter = nullptr;
    Packing packing = nullptr;
    RealValue real_value = nullptr;
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
enum class ResultKind { Crop, Unary, Binary, NativeOperation };
struct RetainedResult {
    NativeRef value;
    std::uint64_t bytes;
    ResultKind kind;
    std::uint32_t data_type_code;
    std::string operation, request_id, vendor_operator;
    std::vector<std::uint32_t> source_ids;
    std::vector<std::string> source_metadata;
    std::string metadata, semantics;
    bool uint32_operation_lineage = false;
};
std::map<std::uint32_t, RetainedResult> retained_results;
std::uint64_t retained_result_bytes = 0;
// Internal legacy names alias the same pool; crop, arithmetic and FFT share
// one total retention limit, never independent budgets.
auto& retained_crops = retained_results;
auto& retained_crop_bytes = retained_result_bytes;
bool qualified_capability353(const char* name) {
    for (const auto& capability : nb::gms353::profile().capabilities)
        if (std::string(capability.name) == name) return capability.qualified;
    return false;
}
void require_uint32_operation353(const char* group, bool bindings) {
    nb::require_uint32_admission353(qualified_capability353(group), bindings, group);
}
std::string uint32_dtype_semantics353(std::size_t count, std::uint32_t input, std::uint32_t output) {
    const auto name = [](std::uint32_t code) -> const char* {
        if (code == 2) return "float32";
        if (code == 3) return "complex64";
        if (code == 11) return "uint32";
        throw std::runtime_error("native_uint32_dtype_semantics_unsupported");
    };
    const auto precision = output == 11 ? "uint32 native result storage" : output == 3 ?
        "complex binary32 result; not lossless for arbitrary uint32 inputs" :
        "binary32 result; not lossless for arbitrary uint32 inputs";
    std::string result = "{\"input_dtypes\":[";
    for (std::size_t i = 0; i < count; ++i) { if (i) result += ','; result += nb::quote(name(input)); }
    result += "],\"output_dtype\":" + nb::quote(name(output)) +
        ",\"selection\":\"DM native operator output; no bridge pixel cast\",\"precision\":" + nb::quote(precision) + '}';
    return result;
}

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
HMODULE checked_module(const char* name) {
    const nb::ModuleRequirement* requirement = nullptr;
    for (const auto& entry : nb::gms353::profile().modules)
        if (std::string(entry.name) == name) requirement = &entry;
    if (!requirement) throw std::runtime_error("module_absent_from_adapter_profile");
    const std::string module_name(name);
    const std::wstring wide(module_name.begin(), module_name.end());
    HMODULE module = module_name == "DigitalMicrograph.exe" ? GetModuleHandleW(nullptr) : GetModuleHandleW(wide.c_str());
    if (!module) throw std::runtime_error("required_vendor_module_not_loaded");
    if (requirement->check_version) require_build_version(module);
    if (sha256(module) != requirement->sha256) throw std::runtime_error("unsupported_vendor_binary");
    return module;
}
std::uint32_t entry_rva(const char* key) {
    for (const auto& entry : nb::gms353::profile().entries)
        if (std::string(entry.key) == key) return entry.rva;
    throw std::runtime_error("entry_absent_from_adapter_profile");
}
template<class T> T symbol(HMODULE module, const char* name) {
    FARPROC p = GetProcAddress(module, name);
    if (!p) throw std::runtime_error("required_native_symbol_missing");
    return reinterpret_cast<T>(p);
}
template<class T> T optional_symbol(HMODULE module, const char* name) noexcept {
    return reinterpret_cast<T>(GetProcAddress(module, name));
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
        try {
            if (!find || find(&value, id) != &value)
                throw std::runtime_error("native_find_result_mismatch");
            if (!value.image) throw std::runtime_error("image_not_found");
        } catch (...) {
            // Construction did not complete, so the destructor cannot guard
            // an owned reference already written before a vendor exception.
            release_image(value);
            throw;
        }
    }
    ImageRef(const ImageRef&) = delete;
    ~ImageRef() { release_image(value); }
    void reset() noexcept { release_image(value); }
    void relinquish() noexcept { value.image = nullptr; }
};
void require_ready();
void retain_native_result(ImageRef& output, std::uint32_t output_id, std::uint64_t bytes,
                          const NativeRequest& request, const std::string& vendor_operator,
                          const std::vector<std::uint32_t>& source_ids,
                          const std::vector<std::string>& source_metadata,
                          const std::string& output_metadata, const std::string& semantics,
                          bool uint32_lineage = false) {
    require_ready();
    if (!output.value.image || !output_id || api.id(output.value.image) != output_id || retained_results.count(output_id))
        throw std::runtime_error("native_result_output_identity_invalid");
    if (!bytes || bytes > nb::kCropOutputBytes) throw std::runtime_error("native_result_output_over_budget");
    if (retained_results.size() >= nb::kCropRetainedCount) throw std::runtime_error("native_result_retention_capacity");
    if (retained_result_bytes > nb::kCropRetainedBytes || bytes > nb::kCropRetainedBytes - retained_result_bytes)
        throw std::runtime_error("native_result_retained_bytes_over_budget");
    const auto kind = request.op == "CROP" ? ResultKind::Crop : request.op == "UNARY" ? ResultKind::Unary :
                      request.op == "BINARY" ? ResultKind::Binary : ResultKind::NativeOperation;
    RetainedResult retained{output.value, bytes, kind, api.dtype(output.value.image), request.op, request.id,
                            vendor_operator, source_ids, source_metadata, output_metadata, semantics, uint32_lineage};
    if (!retained_results.emplace(output_id, std::move(retained)).second)
        throw std::runtime_error("native_result_output_identity_invalid");
    retained_result_bytes += bytes;
    output.relinquish();
}
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
std::uint32_t packing_style(void* image) {
    if (!api.packing) throw std::runtime_error("native_packing_entrypoint_unavailable");
    nb::NativePacking353 packing{UINT32_MAX};
    if (api.packing(image, &packing) != &packing) {
        fatal_abi = true;
        throw std::runtime_error("native_packing_result_mismatch");
    }
    require_ready();
    return packing.value;
}
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
      << ",\"dtype\":" << (code == 2 ? "\"float32\"" : code == 3 ? "\"complex64\"" : code == nb::kUint32Code353 ? "\"uint32\"" : "null");
    if (code == nb::kUint32Code353) s << ",\"is_integer\":true,\"is_unsigned\":true";
    const auto packing = api.packing ? packing_style(image) : UINT32_MAX;
    s << ",\"packing_style\":" << (api.packing ? std::to_string(packing) : "null")
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
      << ",\"native_mean_supported\":" << (api.mean && ndim == 2 &&
          ((code == 2 && pixels <= 4194304) || (code == nb::kUint32Code353 && packing == 1 &&
            pixels <= nb::kUint32StatisticsPixels353 && qualified_capability353("native_uint32_mean"))) ? "true" : "false")
      << ",\"native_summary_supported\":" << (api.minimum && api.maximum && api.sum && api.mean && ndim == 2 &&
          ((code == 2 && pixels <= 4194304) || (code == nb::kUint32Code353 && packing == 1 &&
            pixels <= nb::kUint32StatisticsPixels353 && qualified_capability353("native_uint32_statistics"))) ? "true" : "false")
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
    const auto owned = retained_results.find(id);
    if (!id || owned == retained_results.end()) throw std::runtime_error("native_show_requires_plugin_result");
    const bool uint32 = owned->second.data_type_code == nb::kUint32Code353;
    if (uint32) {
        require_uint32_operation353("native_uint32_display", api.get_document && api.show_document &&
            api.destroy_document_holder && api.destroy_window && api.packing);
        const bool filter = owned->second.operation == "FILTER" && owned->second.uint32_operation_lineage &&
            (owned->second.vendor_operator == "GMSImageProcessing::SmoothFilter" ||
             owned->second.vendor_operator == "GMSImageProcessing::SharpenFilter");
        if (owned->second.kind != ResultKind::Crop && !filter)
            throw std::runtime_error("native_show_uint32_requires_crop_or_qualified_filter");
    }
    ImageRef image(api.find_id, id);
    if (image.value.image != owned->second.value.image || api.id(image.value.image) != id)
        throw std::runtime_error("image_identity_mismatch");
    // Image IDs and pointers can survive user edits. Creation-time dtype must
    // not admit a different current dtype through another display policy.
    if (api.dtype(image.value.image) != owned->second.data_type_code)
        throw std::runtime_error("native_show_result_descriptor_changed");
    if (uint32 && (api.dtype(image.value.image) != 11 || api.ndim(image.value.image) != 2 ||
        packing_style(image.value.image) != 1))
        throw std::runtime_error("native_show_uint32_descriptor_mismatch");
    if (!api.get_document || !api.show_document || !api.destroy_document_holder || !api.destroy_window)
        throw std::runtime_error("native_show_entrypoint_unavailable");
    // Finish bounded local result construction before requesting any UI change.
    auto s = json_stream();
    s << "{\"backend\":\"digitalmicrograph-native\",\"image_id\":" << id
      << ",\"delivery\":\"visible_dm_document\",\"document_visible\":true"
      << ",\"operator\":\"ImageGetOrCreateImageDocument + ImageDocumentShow\""
      << ",\"ownership\":\"host document holds image; plugin result reference released at normal STOP/cleanup\""
      << ",\"source_write_requested\":false,\"snapshot_atomic\":false"
      << ",\"file_saved\":false,\"model_visual_verification\":false";
    if (uint32) s << ",\"image\":" << metadata(image.value.image);
    s << '}';
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
    const auto source_code = api.dtype(source_image);
    const bool uint32 = source_code == nb::kUint32Code353;
    if (api.ndim(source_image) != 2 || (source_code != 2 && !uint32))
        throw std::runtime_error("native_crop_requires_float32_2d");
    if (uint32) {
        require_uint32_operation353("native_uint32_crop", api.crop && api.packing);
        if (packing_style(source_image) != 1) throw std::runtime_error("native_uint32_requires_ordinary_packing");
    }
    const auto width = api.dimension(source_image, 0), height = api.dimension(source_image, 1);
    if (uint32 && static_cast<std::uint64_t>(width) * height > nb::kUint32SourcePixels353)
        throw std::runtime_error("native_uint32_crop_source_over_budget");
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
    if (api.ndim(output_image) != 2 || api.dtype(output_image) != source_code ||
        (uint32 && packing_style(output_image) != 1) ||
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
    if (api.id(source_image) != request.args[0] || api.ndim(source_image) != 2 || api.dtype(source_image) != source_code ||
        (uint32 && packing_style(source_image) != 1) ||
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
    retain_native_result(output, output_id, plan.bytes, request, "GMS::Image::GetSubSliceAsImage",
                         {request.args[0]}, {source_info}, output_info, "independent native crop copy");
    return result;
}
struct ArithmeticImage {
    std::uint32_t id, width, height, data_type;
    std::array<CropAxisCalibration, 2> calibration;
    std::string information;
};
ArithmeticImage arithmetic_image(void* image, std::uint32_t expected_id) {
    require_ready();
    if (api.id(image) != expected_id) throw std::runtime_error("image_identity_mismatch");
    const auto code = api.dtype(image);
    if (api.ndim(image) != 2 || (code != 2 && code != 11))
        throw std::runtime_error("native_arithmetic_requires_float32_2d");
    if (code == 11) require_uint32_operation353("native_uint32_image_arithmetic", api.packing &&
        api.negate && api.abs && api.square && api.add && api.subtract && api.multiply &&
        api.minimum && api.maximum && api.sum && api.mean);
    if (packing_style(image) != 1) throw std::runtime_error("native_arithmetic_requires_ordinary_packing");
    const auto width = api.dimension(image, 0), height = api.dimension(image, 1);
    if (!width || !height) throw std::runtime_error("invalid_image_dimensions");
    return {expected_id, width, height, code, crop_calibration(image), metadata(image)};
}
void validate_native_finite_image(const NativeRef& image, const char* nonfinite_error) {
    if (!api.minimum || !api.maximum || !api.sum || !api.mean)
        throw std::runtime_error("native_arithmetic_finite_check_unavailable");
    // Only DM performs pixel reductions. No C++ pixel traversal, repair or
    // substitute computation is permitted by this adapter.
    for (const auto function : std::array<Reduction, 4>{api.minimum, api.maximum, api.sum, api.mean}) {
        require_ready();
        if (!std::isfinite(function(&image))) throw std::runtime_error(nonfinite_error);
    }
    require_ready();
}
void arithmetic_source_unchanged(void* image, const ArithmeticImage& before) {
    if (api.id(image) != before.id || api.ndim(image) != 2 || api.dtype(image) != before.data_type || packing_style(image) != 1 ||
        api.dimension(image, 0) != before.width || api.dimension(image, 1) != before.height ||
        crop_calibration(image) != before.calibration || metadata(image) != before.information)
        throw std::runtime_error("native_arithmetic_source_metadata_changed");
}
std::string execute_arithmetic(const NativeRequest& request) {
    const bool binary = request.op == "BINARY";
    if (request.args.size() != (binary ? 3u : 2u))
        throw std::runtime_error("native_arithmetic_argument_count");
    const auto opcode = request.args[binary ? 2 : 1];
    const auto name = binary ? nb::binary_operation(opcode) : nb::unary_operation(opcode);
    Unary unary = nullptr;
    Binary paired = nullptr;
    const char* vendor_operator = nullptr;
    if (binary) {
        paired = opcode == 1 ? api.add : opcode == 2 ? api.subtract : api.multiply;
        vendor_operator = opcode == 1 ? "GMSImageProcessing::operator+" : opcode == 2 ?
            "GMSImageProcessing::operator-" : "GMSImageProcessing::operator*";
    } else {
        unary = opcode == 1 ? api.negate : opcode == 2 ? api.abs : api.square;
        vendor_operator = opcode == 1 ? "GMSImageProcessing::Negate" : opcode == 2 ?
            "GMSImageProcessing::Abs" : "GMSImageProcessing::Square";
    }
    if (binary ? !paired : !unary) throw std::runtime_error("native_arithmetic_symbol_unavailable");
    if (!api.packing) throw std::runtime_error("native_arithmetic_packing_unavailable");
    if (!api.minimum || !api.maximum || !api.sum || !api.mean)
        throw std::runtime_error("native_arithmetic_finite_check_unavailable");
    ImageRef source(api.find_id, request.args[0]);
    const auto lhs = arithmetic_image(source.value.image, request.args[0]);
    const auto bytes = nb::native_result_bytes(lhs.width, lhs.height, sizeof(float),
                                               retained_result_bytes, retained_results.size());
    std::unique_ptr<ImageRef> rhs;
    std::vector<std::uint32_t> source_ids{lhs.id};
    std::vector<std::string> source_metadata{lhs.information};
    std::unique_ptr<ArithmeticImage> right;
    if (binary) {
        rhs = std::make_unique<ImageRef>(api.find_id, request.args[1]);
        right = std::make_unique<ArithmeticImage>(arithmetic_image(rhs->value.image, request.args[1]));
        if (right->data_type != lhs.data_type) throw std::runtime_error("native_binary_dtype_mismatch");
        if (right->width != lhs.width || right->height != lhs.height)
            throw std::runtime_error("native_binary_shape_mismatch");
        if (right->calibration != lhs.calibration)
            throw std::runtime_error("native_binary_spatial_calibration_mismatch");
        source_ids.push_back(right->id); source_metadata.push_back(right->information);
    }
    validate_native_finite_image(source.value, "native_arithmetic_source_nonfinite");
    if (rhs) validate_native_finite_image(rhs->value, "native_arithmetic_source_nonfinite");
    require_ready();
    ImageRef output;
    NativeRef* returned = binary ? paired(&output.value, &source.value, &rhs->value) : unary(&output.value, &source.value);
    if (returned != &output.value || !output.value.image)
        throw std::runtime_error("native_arithmetic_no_output_reference");
    require_ready();
    const auto output_id = api.id(output.value.image);
    if (!output_id || output_id == lhs.id || (right && output_id == right->id) ||
        output.value.image == source.value.image || (rhs && output.value.image == rhs->value.image) || retained_results.count(output_id))
        throw std::runtime_error("native_arithmetic_output_identity_invalid");
    if (api.ndim(output.value.image) != 2 || api.dtype(output.value.image) != 2 || packing_style(output.value.image) != 1 ||
        api.dimension(output.value.image, 0) != lhs.width || api.dimension(output.value.image, 1) != lhs.height)
        throw std::runtime_error("native_arithmetic_output_descriptor_mismatch");
    if (crop_calibration(output.value.image) != lhs.calibration)
        throw std::runtime_error("native_arithmetic_output_spatial_calibration_mismatch");
    const auto output_info = metadata(output.value.image);
    validate_native_finite_image(output.value, "native_arithmetic_output_nonfinite");
    arithmetic_source_unchanged(source.value.image, lhs);
    if (rhs) arithmetic_source_unchanged(rhs->value.image, *right);
    auto stream = json_stream();
    stream << "{\"backend\":\"digitalmicrograph-native\",\"operation\":" << nb::quote(name)
      << ",\"opcode\":" << opcode << ",\"image_id\":" << output_id << ",\"source_image_ids\":[";
    for (std::size_t i = 0; i < source_ids.size(); ++i) { if (i) stream << ','; stream << source_ids[i]; }
    stream << "],\"sources\":[";
    for (std::size_t i = 0; i < source_metadata.size(); ++i) { if (i) stream << ','; stream << source_metadata[i]; }
    stream << "],\"image\":" << output_info << ",\"operator\":" << nb::quote(vendor_operator);
    if (lhs.data_type == 11) stream << ",\"dtype_semantics\":" << uint32_dtype_semantics353(binary ? 2u : 1u, 11, 2);
    stream
      << ",\"computation\":\"DM native\",\"intensity_calibration_applied\":false,\"intensity_semantics\":\"raw pixel intensity\""
      << ",\"output_bytes\":" << bytes << ",\"ownership\":\"plugin retained strong reference until normal native STOP/cleanup; shown document may retain image\""
      << ",\"finite_check\":\"DM native GetMinimum/GetMaximum/GetSum/GetMean\",\"visible_dm_document\":false"
      << ",\"source_write_requested\":false,\"snapshot_atomic\":false}";
    auto result = stream.str();
    if (!nb::valid_json(result)) throw std::runtime_error("native_arithmetic_result_over_budget_or_invalid");
    source.reset(); if (rhs) rhs->reset(); require_ready();
    const std::string semantics = lhs.data_type == 11 ?
        "DM native uint32 inputs; binary64 native arithmetic then binary32 result; not lossless for arbitrary uint32 inputs; bridge performs no pixel cast" :
        "DM native raw pixel arithmetic; intensity/spatial metadata copied from first input";
    retain_native_result(output, output_id, bytes, request, vendor_operator, source_ids, source_metadata,
                         output_info, semantics, lhs.data_type == 11);
    return result;
}
#include "fft_adapter.inc"
#include "filter_adapter.inc"
#include "preview_adapter.inc"
#include "read_adapter.inc"
} // namespace

void initialize_native() {
    host_thread = GetCurrentThreadId();
    try {
        checked_module("DigitalMicrograph.exe");
        auto image = checked_module("GMSImage.dll");
        auto processing = checked_module("GMSImageProcessing.dll");
        auto gms = checked_module("GMS.dll");
        auto mfc = checked_module("mfc140.dll");
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
        api.mean = optional_symbol<Mean>(processing,
            "?GetMean@GMSImageProcessing@@YANAEBV?$ref_ptr@VImage@GMS@@@Gatan@@@Z");
        api.minimum = optional_symbol<Reduction>(processing,
            "?GetMinimum@GMSImageProcessing@@YANAEBV?$ref_ptr@VImage@GMS@@@Gatan@@@Z");
        api.maximum = optional_symbol<Reduction>(processing,
            "?GetMaximum@GMSImageProcessing@@YANAEBV?$ref_ptr@VImage@GMS@@@Gatan@@@Z");
        api.sum = optional_symbol<Reduction>(processing,
            "?GetSum@GMSImageProcessing@@YANAEBV?$ref_ptr@VImage@GMS@@@Gatan@@@Z");
        api.packing = optional_symbol<Packing>(image,
            "?GetPackingStyle@Image@GMS@@QEBA?AUDataPackingStyle@Imaging@Gatan@@XZ");
        api.real_value = optional_symbol<RealValue>(image,
            "?GetRealValue@Image@GMS@@QEBANAEBVDataIndex@Imaging@Gatan@@@Z");
        api.negate = optional_symbol<Unary>(processing,
            "?Negate@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z");
        api.abs = optional_symbol<Unary>(processing,
            "?Abs@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z");
        api.square = optional_symbol<Unary>(processing,
            "?Square@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z");
        api.add = optional_symbol<Binary>(processing,
            "??HGMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV12@0@Z");
        api.subtract = optional_symbol<Binary>(processing,
            "??GGMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV12@0@Z");
        api.multiply = optional_symbol<Binary>(processing,
            "??DGMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV12@0@Z");
        api.real_fft = optional_symbol<Unary>(processing,
            "?Real_FFT@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z");
        api.ifft = optional_symbol<Unary>(processing,
            "?IFFT@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z");
        api.real_component = optional_symbol<Unary>(processing,
            "?Real@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z");
        api.imag_component = optional_symbol<Unary>(processing,
            "?Imag@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z");
        api.arg = optional_symbol<Unary>(processing,
            "?Arg@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z");
        api.norm = optional_symbol<Unary>(processing,
            "?Norm@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z");
        api.smooth_filter = optional_symbol<Unary>(processing,
            "?SmoothFilter@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z");
        api.sobel_filter = optional_symbol<Unary>(processing,
            "?SobelFilter@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z");
        api.laplace_filter = optional_symbol<Unary>(processing,
            "?LaplaceFilter@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z");
        api.sharpen_filter = optional_symbol<Unary>(processing,
            "?SharpenFilter@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z");
        api.destroy = symbol<Delete>(image, "?ref_ptr_delete@Gatan@@YAXPEAVImage@GMS@@@Z");
        api.deallocate = symbol<VendorFree>(mfc, MAKEINTRESOURCEA(1487));
        api.crop = optional_symbol<Crop>(image,
            "?GetSubSliceAsImage@Image@GMS@@QEBA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBVDataSlice@Imaging@4@@Z");
        try {
            api.get_document = rva_symbol<GetDocument>(gms, entry_rva("image_get_or_create_document"));
            api.show_document = rva_symbol<ShowDocument>(gms, entry_rva("image_document_show"));
            api.destroy_document_holder = rva_symbol<Delete>(gms, entry_rva("destroy_document_holder"));
            api.destroy_window = rva_symbol<Delete>(gms, entry_rva("destroy_window"));
        } catch (const std::exception&) {
            api.get_document = nullptr; api.show_document = nullptr;
            api.destroy_document_holder = nullptr; api.destroy_window = nullptr;
        }
        gate_error.clear();
    } catch (const std::exception& error) { gate_error = error.what(); }
}

static std::string execute_operation(const NativeRequest& request) {
    if (request.op == "STATUS") {
        std::size_t crop_count = 0;
        std::uint64_t crop_bytes = 0;
        for (const auto& entry : retained_results) {
            if (entry.second.kind == ResultKind::Crop) { ++crop_count; crop_bytes += entry.second.bytes; }
        }
        const bool operational = gate_error.empty() && !fatal_abi;
        const bool finite_checks = api.minimum && api.maximum && api.sum && api.mean;
        const auto available = [operational](const char* group, bool bindings) {
            return operational && qualified_capability353(group) && bindings;
        };
        const bool arithmetic = available("native_image_arithmetic", api.packing && finite_checks &&
            api.negate && api.abs && api.square && api.add && api.subtract && api.multiply);
        const bool fourier = available("native_fft", api.packing && finite_checks &&
            api.real_fft && api.ifft && api.real_component && api.imag_component && api.arg && api.norm);
        const bool filters = available("native_filters", api.packing && finite_checks &&
            api.smooth_filter && api.sobel_filter && api.laplace_filter && api.sharpen_filter);
        const bool display = available("native_display",
            api.get_document && api.show_document && api.destroy_document_holder && api.destroy_window);
        auto s = json_stream();
        s << "{\"backend\":\"digitalmicrograph-native\",\"ready\":" << (operational ? "true" : "false")
          << ",\"supported_build\":\"3.53.4137.0-x64\",\"binary_gate\":" << (gate_error.empty() ? "true" : "false")
          << ",\"host_pid\":" << GetCurrentProcessId() << ",\"host_thread\":" << host_thread
          << ",\"resident_python_required\":false,\"arbitrary_script\":false,\"requires_idle_host\":true"
          << ",\"capabilities\":[";
        bool first = true;
        const auto capability = [&s, &first](const char* name, bool enabled) {
            if (!enabled) return;
            if (!first) s << ',';
            first = false;
            s << nb::quote(name);
        };
        capability("datasets", available("native_datasets", true));
        capability("image_info", available("native_datasets", true));
        capability("mean_float32_2d", available("native_mean", api.mean != nullptr));
        capability("summary_float32_2d", available("native_statistics", finite_checks));
        capability("crop_float32_2d", available("native_crop", api.crop != nullptr));
        // The old crop label remains a truthful compatibility subset.
        capability("show_plugin_crop_visible_document", display);
        capability("show_plugin_result_visible_document", display);
        capability("unary_float32_2d", arithmetic);
        capability("binary_float32_2d", arithmetic);
        capability("fourier_small_2d", fourier);
        capability("filter_small_float32_2d", filters);
        capability("sampled_preview_float32_2d", available("native_preview", api.packing && api.real_value));
        capability("bounded_read_float32_2d", available("native_read", api.packing && api.real_value));
        capability("mean_uint32_2d", available("native_uint32_mean", api.packing && api.mean));
        capability("summary_uint32_2d", available("native_uint32_statistics", api.packing && finite_checks));
        capability("crop_uint32_2d", available("native_uint32_crop", api.packing && api.crop));
        capability("sampled_preview_uint32_2d", available("native_uint32_preview", api.packing && api.real_value));
        capability("bounded_read_uint32_2d", available("native_uint32_read", api.packing && api.real_value));
        capability("show_plugin_uint32_crop_or_filter_visible_document", available("native_uint32_display", display && api.packing));
        capability("unary_uint32_to_float32_2d", available("native_uint32_image_arithmetic", arithmetic));
        capability("binary_uint32_to_float32_2d", available("native_uint32_image_arithmetic", arithmetic));
        capability("filter_small_uint32_2d", available("native_uint32_filters", filters));
        capability("fourier_uint32_small_2d", available("native_uint32_fft", fourier));
        s << "],\"retained_result_count\":" << retained_results.size() << ",\"retained_result_bytes\":" << retained_result_bytes
          << ",\"retained_crop_count\":" << crop_count << ",\"retained_crop_bytes\":" << crop_bytes
          << ",\"build_error\":" << (fatal_abi ? "\"native_abi_invalid_output_path_disabled\"" : gate_error.empty() ? "null" : nb::quote(gate_error)) << '}';
        return s.str();
    }
    require_ready();
    if (request.op == "UNARY" || request.op == "BINARY" || request.op == "FILTER" || request.op == "PREVIEW" || request.op == "READ" || nb::is_fft_operation353(request.op)) {
        const char* group = request.op == "UNARY" || request.op == "BINARY" ? "native_image_arithmetic" :
            request.op == "FILTER" ? "native_filters" : request.op == "PREVIEW" ? "native_preview" :
            request.op == "READ" ? "native_read" : "native_fft";
        if (!qualified_capability353(group))
            throw std::runtime_error(std::string("native_operation_not_qualified:") + group);
        if (request.op == "UNARY" || request.op == "BINARY") return execute_arithmetic(request);
        if (request.op == "FILTER") return execute_filter(request);
        if (request.op == "PREVIEW") return execute_preview(request);
        if (request.op == "READ") return execute_read(request);
        return execute_fft(request);
    }
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
        if (request.op == "MEAN" && !api.mean) throw std::runtime_error("native_mean_not_available");
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
        const auto source_code = api.dtype(image.value.image);
        const bool uint32 = source_code == nb::kUint32Code353;
        if (api.ndim(image.value.image) != 2 || (source_code != 2 && !uint32))
            throw std::runtime_error(summary ? "native_summary_requires_float32_2d" : "native_mean_requires_float32_2d");
        if (uint32) {
            require_uint32_operation353(summary ? "native_uint32_statistics" : "native_uint32_mean",
                api.packing && api.mean && (!summary || (api.minimum && api.maximum && api.sum)));
            if (packing_style(image.value.image) != 1) throw std::runtime_error("native_uint32_requires_ordinary_packing");
        }
        auto w = api.dimension(image.value.image, 0), h = api.dimension(image.value.image, 1);
        if (!w || !h) throw std::runtime_error("invalid_image_dimensions");
        const auto pixels = static_cast<std::uint64_t>(w) * h;
        if (uint32 && pixels > nb::kUint32StatisticsPixels353)
            throw std::runtime_error("native_uint32_statistics_exact_sum_budget_exceeded");
        if (pixels > 4194304)
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
            if (uint32) nb::require_uint32_sample353(minimum, "native_uint32_summary_invalid_integer_result");
            const double maximum = finite_result(api.maximum(&image.value));
            require_ready();
            if (uint32) nb::require_uint32_sample353(maximum, "native_uint32_summary_invalid_integer_result");
            const double sum = finite_result(api.sum(&image.value));
            require_ready();
            if (uint32) nb::require_uint32_sum353(sum, pixels);
            const double mean = finite_result(api.mean(&image.value));
            require_ready();
            if (uint32) {
                nb::validate_uint32_summary353(minimum, maximum, sum, mean, pixels);
                if (metadata(image.value.image, false) != info)
                    throw std::runtime_error("native_uint32_statistics_source_metadata_changed");
            }
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
        if (uint32) {
            nb::require_uint32_mean353(mean);
            if (metadata(image.value.image, false) != info)
                throw std::runtime_error("native_uint32_statistics_source_metadata_changed");
        }
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
bool nb353_ready() { return gate_error.empty() && !fatal_abi; }
std::string nb353_error() {
    return fatal_abi ? "native_abi_invalid_output_path_disabled" : gate_error;
}
void nb353_observe_entries(nb::HostObservation& host) {
    if (api.get_document) host.valid_entry_contracts.insert("image_get_or_create_document");
    if (api.show_document) host.valid_entry_contracts.insert("image_document_show");
    if (api.destroy_document_holder) host.valid_entry_contracts.insert("destroy_document_holder");
    if (api.destroy_window) host.valid_entry_contracts.insert("destroy_window");
}
