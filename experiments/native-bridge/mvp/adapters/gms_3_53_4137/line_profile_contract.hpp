#pragma once
#include "roi_contract.hpp"
#include <cstring>
#include <string>
namespace nb {
struct RoiLine353 { float x0, y0, x1, y1; };
struct NativeDataIndex1D353 { std::uint32_t dimensions = 1, padding = 0; std::int64_t x = 0; };
static_assert(sizeof(RoiLine353) == 16 && sizeof(NativeDataIndex1D353) == 16);
static_assert(offsetof(NativeDataIndex1D353, x) == 8);
inline constexpr std::uint32_t kProfileSampleLimit353 = 4096;
inline constexpr std::uint32_t kProfileFloat64Code353 = 12;
inline const char* roi_line_issue353(const RoiLine353& r, std::uint32_t width, std::uint32_t height) {
    for (float v : {r.x0,r.y0,r.x1,r.y1})
        if (!std::isfinite(v)) throw std::runtime_error("native_roi_nonfinite_line");
    if (r.x0 == r.x1 && r.y0 == r.y1) return "empty_line";
    for (float v : {r.x0,r.y0,r.x1,r.y1}) if (std::trunc(v) != v) return "fractional_line";
    if (r.x0 != r.x1 && r.y0 != r.y1) return "unsupported_line_orientation";
    if (r.x0 < 0 || r.y0 < 0 || r.x1 < 0 || r.y1 < 0 ||
        r.x0 >= width || r.x1 >= width || r.y0 >= height || r.y1 >= height)
        return "out_of_bounds_line";
    if (std::floor(std::hypot(static_cast<double>(r.x1)-r.x0, static_cast<double>(r.y1)-r.y0))+1 > kProfileSampleLimit353)
        return "line_sample_budget";
    return nullptr;
}
inline std::uint32_t profile_samples353(const RoiLine353& line, std::uint32_t width, std::uint32_t height) {
    if (const auto* issue = roi_line_issue353(line,width,height)) throw std::runtime_error(issue);
    return static_cast<std::uint32_t>(std::floor(std::hypot(static_cast<double>(line.x1)-line.x0,
        static_cast<double>(line.y1)-line.y0)))+1;
}
inline void append_profile_float64_le353(std::string& bytes, double value) {
    if (!std::isfinite(value)) throw std::runtime_error("native_profile_nonfinite_value");
    static_assert(sizeof(double) == 8);
    std::uint64_t bits; std::memcpy(&bits,&value,8);
    for (unsigned i=0;i<8;++i) bytes.push_back(static_cast<char>((bits>>(8*i))&255));
}
} // namespace nb
