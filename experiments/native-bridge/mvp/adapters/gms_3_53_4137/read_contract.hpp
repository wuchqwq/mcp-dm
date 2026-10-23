#pragma once
#include "preview_contract.hpp"
#include <array>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <limits>
#include <stdexcept>
#include <string>

namespace nb {
constexpr std::uint64_t kReadSamples353 = 16384;
constexpr std::uint64_t kReadBytes353 = 65536;
static_assert(sizeof(float) == 4 && std::numeric_limits<float>::is_iec559,
              "READ requires IEEE754 binary32");

struct ReadPlan353 {
    std::uint32_t source_width, source_height, width, height;
    std::array<std::uint32_t, 4> rect;
    std::uint64_t samples, bytes;
};
inline ReadPlan353 read_plan353(std::uint32_t source_width, std::uint32_t source_height,
                                 const std::array<std::uint32_t, 4>& rect) {
    if (!source_width || !source_height) throw std::runtime_error("invalid_image_dimensions");
    if (static_cast<std::uint64_t>(source_width)*source_height > kPreviewSourcePixels353)
        throw std::runtime_error("native_read_source_over_budget");
    if (rect[0] >= rect[2] || rect[1] >= rect[3] || rect[2] > source_width || rect[3] > source_height)
        throw std::runtime_error("native_read_rect_out_of_bounds_or_empty");
    const auto width = rect[2]-rect[0], height = rect[3]-rect[1];
    const auto samples = static_cast<std::uint64_t>(width)*height;
    if (samples > kReadSamples353) throw std::runtime_error("native_read_roi_over_budget");
    return {source_width, source_height, width, height, rect, samples, samples*4u};
}
inline NativeDataIndex2D353 read_index353(const ReadPlan353& plan, std::uint32_t x, std::uint32_t y) {
    if (x >= plan.width || y >= plan.height) throw std::runtime_error("native_read_index_out_of_bounds");
    return {2, 0, static_cast<std::int64_t>(plan.rect[0])+x, static_cast<std::int64_t>(plan.rect[1])+y};
}
inline std::uint32_t read_float32_bits353(double value) {
    if (!std::isfinite(value)) throw std::runtime_error("native_read_nonfinite_sample");
    if (value > static_cast<double>(std::numeric_limits<float>::max()) ||
        value < -static_cast<double>(std::numeric_limits<float>::max()))
        throw std::runtime_error("native_read_value_not_exact_float32");
    const float narrowed = static_cast<float>(value);
    if (!std::isfinite(narrowed) || static_cast<double>(narrowed) != value ||
        (value == 0.0 && std::signbit(narrowed) != std::signbit(value)))
        throw std::runtime_error("native_read_value_not_exact_float32");
    std::uint32_t bits = 0;
    std::memcpy(&bits, &narrowed, sizeof(bits));
    return bits;
}
inline void append_read_float32_le353(std::string& bytes, double value) {
    const auto bits = read_float32_bits353(value);
    for (unsigned shift = 0; shift < 32; shift += 8)
        bytes.push_back(static_cast<char>((bits >> shift) & 255u));
}
inline std::string read_base64_353(const std::string& bytes) {
    if (bytes.size() > kReadBytes353) throw std::runtime_error("native_read_raw_bytes_over_budget");
    static constexpr char alphabet[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    std::string output;
    output.reserve(((bytes.size()+2)/3)*4);
    for (std::size_t start = 0; start < bytes.size(); start += 3) {
        const auto a = static_cast<unsigned char>(bytes[start]);
        const auto b = start+1 < bytes.size() ? static_cast<unsigned char>(bytes[start+1]) : 0u;
        const auto c = start+2 < bytes.size() ? static_cast<unsigned char>(bytes[start+2]) : 0u;
        const auto group = (static_cast<std::uint32_t>(a) << 16) | (b << 8) | c;
        output.push_back(alphabet[(group >> 18) & 63]);
        output.push_back(alphabet[(group >> 12) & 63]);
        output.push_back(start+1 < bytes.size() ? alphabet[(group >> 6) & 63] : '=');
        output.push_back(start+2 < bytes.size() ? alphabet[group & 63] : '=');
    }
    return output;
}
} // namespace nb
