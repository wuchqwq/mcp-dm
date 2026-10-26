#pragma once
#include <array>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <regex>
#include <stdexcept>
#include <string>
#include <vector>

namespace nb {
constexpr std::uint64_t kImportSamples353 = 16384;
constexpr std::uint64_t kImportBytes353 = kImportSamples353 * 4;
constexpr std::size_t kImportHeader353 = 4096, kImportManifest353 = 32768;
constexpr std::size_t kImportQuotedManifest353 = 16384;
struct ImportSpec353 {
    std::string ticket, npy_sha256, manifest_sha256;
    std::uint32_t width = 0, height = 0, domain = 0, unit = 0;
    std::array<float, 2> origin{}, scale{};
};
inline float import_float353(std::uint32_t bits) { float value; std::memcpy(&value, &bits, 4); return value; }
inline std::uint32_t import_bits353(float value) { std::uint32_t bits; std::memcpy(&bits, &value, 4); return bits; }
inline std::string import_hex353(const std::vector<std::uint32_t>& args, std::size_t first, std::size_t count) {
    constexpr char hex[] = "0123456789abcdef";
    std::string result;
    for (std::size_t i = first; i < first + count; ++i)
        for (int shift = 28; shift >= 0; shift -= 4) result += hex[(args.at(i) >> shift) & 15];
    return result;
}
inline ImportSpec353 import_spec353(const std::vector<std::uint32_t>& args) {
    if (args.size() != 27) throw std::runtime_error("native_import_requires_27_arguments");
    ImportSpec353 value;
    value.ticket = import_hex353(args, 0, 4); value.npy_sha256 = import_hex353(args, 4, 8);
    value.manifest_sha256 = import_hex353(args, 12, 8); value.width = args[20]; value.height = args[21];
    const auto samples = static_cast<std::uint64_t>(value.width) * value.height;
    if (!samples || samples > kImportSamples353) throw std::runtime_error("native_import_shape_over_budget");
    value.origin = {{import_float353(args[22]), import_float353(args[24])}};
    value.scale = {{import_float353(args[23]), import_float353(args[25])}};
    for (unsigned i = 0; i < 2; ++i) {
        const float zero = -(value.origin[i] * value.scale[i]);
        const float endpoint_index = static_cast<float>((i ? value.height : value.width)-1) - value.origin[i];
        const float endpoint = endpoint_index * value.scale[i];
        if (!std::isfinite(value.origin[i]) || !std::isfinite(value.scale[i]) || value.scale[i] == 0 ||
            !std::isfinite(zero) || !std::isfinite(endpoint))
            throw std::runtime_error("native_import_invalid_numeric_calibration");
    }
    value.domain = args[26] >> 4; value.unit = args[26] & 15;
    if (value.domain > 2 || value.unit > 6 ||
        (value.domain == 0 && value.unit != 0) ||
        (value.domain == 1 && value.unit > 3) ||
        (value.domain == 2 && value.unit > 0 && value.unit < 4))
        throw std::runtime_error("native_import_coordinate_domain_unit_mismatch");
    return value;
}
inline const char* import_domain353(std::uint32_t domain) {
    return domain == 1 ? "real_space" : domain == 2 ? "reciprocal_space" : "image_coordinates";
}
inline std::wstring import_unit353(std::uint32_t unit) {
    switch (unit) {
    case 0: return L""; case 1: return L"nm"; case 2: return L"\u00c5"; case 3: return L"\u00b5m";
    case 4: return L"1/nm"; case 5: return L"1/\u00c5"; case 6: return L"1/\u00b5m";
    default: throw std::runtime_error("native_import_unknown_unit");
    }
}
// Narrow canonical NumPy v1/v2 parser. No Python evaluation, pickle, dtype
// conversion, alternate storage order or inferred axis interpretation.
inline std::vector<float> import_npy353(const std::string& bytes, const ImportSpec353& spec) {
    if (bytes.size() < 10 || bytes.size() > kImportBytes353 + kImportHeader353 + 12 ||
        bytes.compare(0, 6, std::string("\x93NUMPY", 6)) != 0 || bytes[7] != 0 ||
        (bytes[6] != 1 && bytes[6] != 2)) throw std::runtime_error("native_import_invalid_npy");
    const auto prefix = bytes[6] == 1 ? 10u : 12u;
    if (bytes.size() < prefix) throw std::runtime_error("native_import_invalid_npy");
    std::uint32_t length = 0;
    for (unsigned i = 0; i < (bytes[6] == 1 ? 2u : 4u); ++i)
        length |= static_cast<std::uint32_t>(static_cast<unsigned char>(bytes[8+i])) << (8*i);
    if (!length || length > kImportHeader353 || prefix + length > bytes.size())
        throw std::runtime_error("native_import_npy_header_over_budget");
    const auto header = bytes.substr(prefix, length);
    if (header.back() != '\n' || header.find_first_not_of("\t\n\r !\"#$%&'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`abcdefghijklmnopqrstuvwxyz{|}~") != std::string::npos)
        throw std::runtime_error("native_import_npy_header_not_ascii");
    const std::regex grammar(R"(^\s*\{\s*(['"])descr\1\s*:\s*(['"])<f4\2\s*,\s*(['"])fortran_order\3\s*:\s*False\s*,\s*(['"])shape\4\s*:\s*\(\s*([0-9]{1,10})\s*,\s*([0-9]{1,10})\s*,?\s*\)\s*,?\s*\}\s*$)");
    std::smatch match;
    if (!std::regex_match(header, match, grammar)) throw std::runtime_error("native_import_requires_canonical_float32_npy");
    if (std::stoull(match[5].str()) != spec.height || std::stoull(match[6].str()) != spec.width)
        throw std::runtime_error("native_import_npy_shape_mismatch");
    const auto count = static_cast<std::size_t>(spec.width) * spec.height;
    if (bytes.size() != prefix + length + count * 4) throw std::runtime_error("native_import_npy_byte_count_mismatch");
    std::vector<float> values; values.reserve(count);
    for (std::size_t i = 0; i < count; ++i) {
        std::uint32_t bits = 0;
        for (unsigned j = 0; j < 4; ++j)
            bits |= static_cast<std::uint32_t>(static_cast<unsigned char>(bytes[prefix+length+i*4+j])) << (8*j);
        const auto value = import_float353(bits);
        if (!std::isfinite(value)) throw std::runtime_error("native_import_nonfinite_pixel");
        values.push_back(value);
    }
    return values;
}
} // namespace nb
