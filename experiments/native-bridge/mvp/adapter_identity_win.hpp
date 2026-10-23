#pragma once
#include "adapter_profile.hpp"
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <bcrypt.h>
#include <winver.h>
#include <cwchar>
#include <stdexcept>

// Only Windows loader/file metadata is read here. GetProcAddress resolves an
// explicitly profiled name/ordinal; it never invokes the returned address.
namespace nb::identity {
struct Handle {
    HANDLE value = INVALID_HANDLE_VALUE;
    explicit Handle(HANDLE handle) : value(handle) {}
    ~Handle() { if (value && value != INVALID_HANDLE_VALUE) CloseHandle(value); }
    Handle(const Handle&) = delete;
};
inline std::wstring path(HMODULE module) {
    std::vector<wchar_t> text(32768);
    const auto n = GetModuleFileNameW(module, text.data(), static_cast<DWORD>(text.size()));
    if (!n || n >= text.size()) throw std::runtime_error("module_path_unavailable");
    return {text.data(), n};
}
inline HostVersion version(const std::wstring& filename) {
    DWORD ignored = 0;
    const auto n = GetFileVersionInfoSizeW(filename.c_str(), &ignored);
    if (!n || n > 1048576) throw std::runtime_error("version_unavailable");
    std::vector<unsigned char> buffer(n);
    if (!GetFileVersionInfoW(filename.c_str(), 0, n, buffer.data())) throw std::runtime_error("version_unavailable");
    VS_FIXEDFILEINFO* info = nullptr;
    UINT size = 0;
    if (!VerQueryValueW(buffer.data(), L"\\", reinterpret_cast<void**>(&info), &size) ||
        size < sizeof(*info) || info->dwSignature != 0xfeef04bd) throw std::runtime_error("version_invalid");
    return {{{static_cast<std::uint16_t>(info->dwFileVersionMS >> 16),
        static_cast<std::uint16_t>(info->dwFileVersionMS),
        static_cast<std::uint16_t>(info->dwFileVersionLS >> 16),
        static_cast<std::uint16_t>(info->dwFileVersionLS)}}};
}
inline void read_at(HANDLE file, std::uint32_t offset, void* out, DWORD size) {
    LARGE_INTEGER where{}; where.QuadPart = offset;
    DWORD read = 0;
    if (!SetFilePointerEx(file, where, nullptr, FILE_BEGIN) ||
        !ReadFile(file, out, size, &read, nullptr) || read != size) throw std::runtime_error("module_header_unavailable");
}
inline std::string architecture(const std::wstring& filename) {
    Handle file(CreateFileW(filename.c_str(), GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_DELETE,
        nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr));
    IMAGE_DOS_HEADER dos{};
    if (file.value == INVALID_HANDLE_VALUE) throw std::runtime_error("module_open_failed");
    read_at(file.value, 0, &dos, sizeof(dos));
    if (dos.e_magic != IMAGE_DOS_SIGNATURE || dos.e_lfanew < 0 || dos.e_lfanew > 1048576)
        throw std::runtime_error("module_header_invalid");
    struct Header { DWORD signature; IMAGE_FILE_HEADER file; } header{};
    read_at(file.value, static_cast<std::uint32_t>(dos.e_lfanew), &header, sizeof(header));
    if (header.signature != IMAGE_NT_SIGNATURE) throw std::runtime_error("module_header_invalid");
    if (header.file.Machine == IMAGE_FILE_MACHINE_AMD64) return "x64";
    if (header.file.Machine == IMAGE_FILE_MACHINE_I386) return "x86";
    if (header.file.Machine == IMAGE_FILE_MACHINE_ARM64) return "arm64";
    return "unknown";
}
inline std::string sha256(const std::wstring& filename) {
    Handle file(CreateFileW(filename.c_str(), GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_DELETE,
        nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr));
    if (file.value == INVALID_HANDLE_VALUE) throw std::runtime_error("module_hash_open_failed");
    BCRYPT_ALG_HANDLE algorithm = nullptr;
    BCRYPT_HASH_HANDLE hash = nullptr;
    struct Guard {
        BCRYPT_ALG_HANDLE& algorithm; BCRYPT_HASH_HANDLE& hash;
        ~Guard() { if (hash) BCryptDestroyHash(hash); if (algorithm) BCryptCloseAlgorithmProvider(algorithm, 0); }
    } guard{algorithm, hash};
    if (BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, nullptr, 0) < 0 ||
        BCryptCreateHash(algorithm, &hash, nullptr, 0, nullptr, 0, 0) < 0) throw std::runtime_error("module_hash_init_failed");
    unsigned char buffer[32768], digest[32];
    for (;;) {
        DWORD n = 0;
        if (!ReadFile(file.value, buffer, sizeof(buffer), &n, nullptr)) throw std::runtime_error("module_hash_read_failed");
        if (!n) break;
        if (BCryptHashData(hash, buffer, n, 0) < 0) throw std::runtime_error("module_hash_update_failed");
    }
    if (BCryptFinishHash(hash, digest, sizeof(digest), 0) < 0) throw std::runtime_error("module_hash_finish_failed");
    constexpr char hex[] = "0123456789abcdef";
    std::string result;
    for (auto byte : digest) { result += hex[byte >> 4]; result += hex[byte & 15]; }
    return result;
}
inline HMODULE module(const std::string& name) {
    if (name == "DigitalMicrograph.exe") return GetModuleHandleW(nullptr);
    const std::wstring wide(name.begin(), name.end()); // Profile names are ASCII constants.
    return GetModuleHandleW(wide.c_str());
}
inline FARPROC resolve(HMODULE handle, const std::string& symbol) {
    if (!symbol.empty() && symbol.front() == '#') {
        std::uint32_t ordinal = 0;
        if (symbol.size() < 2 || symbol.size() > 6) return nullptr;
        for (std::size_t i = 1; i < symbol.size(); ++i) {
            if (symbol[i] < '0' || symbol[i] > '9') return nullptr;
            ordinal = ordinal * 10 + static_cast<unsigned>(symbol[i] - '0');
        }
        if (!ordinal || ordinal > 65535) return nullptr;
        return GetProcAddress(handle, MAKEINTRESOURCEA(ordinal));
    }
    return GetProcAddress(handle, symbol.c_str());
}
inline HostObservation observe(const std::vector<const AdapterProfile*>& profiles) {
    HostObservation host;
    try {
        const auto filename = path(GetModuleHandleW(nullptr));
        const auto slash = filename.find_last_of(L"\\/");
        const auto basename = filename.substr(slash == std::wstring::npos ? 0 : slash + 1);
        host.recognized_gms = _wcsicmp(basename.c_str(), L"DigitalMicrograph.exe") == 0;
        if (!host.recognized_gms) return host;
        host.version = version(filename); host.version_readable = true;
        host.architecture = architecture(filename);
        const AdapterProfile* match = nullptr;
        for (const auto* profile : profiles)
            if (profile && profile->version == host.version && profile->architecture == host.architecture) match = profile;
        if (!match) return host; // Unknown build: no export/RVA/layout exploration.
        for (const auto& required : match->modules) {
            ModuleObservation item; item.name = required.name;
            const auto loaded = module(item.name);
            item.loaded = loaded != nullptr;
            if (loaded) try {
                const auto filename = path(loaded);
                item.architecture = architecture(filename);
                if (required.check_version) item.version = version(filename);
                item.sha256 = sha256(filename);
                item.readable = true;
                // Do not even resolve optional symbols of a mismatched binary.
                if (item.sha256 == required.sha256 && item.architecture == match->architecture &&
                    (!required.check_version || item.version == match->version)) {
                    for (const auto& spec : match->core_symbols)
                        if (item.name == spec.module && resolve(loaded, spec.name)) item.symbols.insert(spec.name);
                    for (const auto& capability : match->capabilities)
                        for (const auto& spec : capability.symbols)
                            if (item.name == spec.module && resolve(loaded, spec.name)) item.symbols.insert(spec.name);
                }
            } catch (const std::exception&) { item.readable = false; }
            host.modules.push_back(std::move(item));
        }
    } catch (const std::exception&) { /* Explicit NOT_READY observation, no vendor call. */ }
    return host;
}
} // namespace nb::identity
