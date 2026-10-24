#pragma once
#include <cmath>
#include <cstdint>
#include <stdexcept>
#include <string>

namespace nb {
// Fixed-build descriptor contract, independently checked with synthetic uint32
// host arrays and exact high-bit reads. Other host builds remain unsupported.
constexpr std::uint32_t kUint32Code353 = 11;
constexpr std::uint64_t kUint32SourcePixels353 = 4194304;
constexpr std::uint64_t kUint32Maximum353 = UINT32_MAX;
constexpr std::uint64_t kExactDoubleInteger353 = (std::uint64_t{1} << 53) - 1;
constexpr std::uint64_t kUint32StatisticsPixels353 = std::uint64_t{1} << 21;
static_assert(kUint32StatisticsPixels353 * kUint32Maximum353 <= kExactDoubleInteger353);
static_assert((kUint32StatisticsPixels353 + 1) * kUint32Maximum353 > kExactDoubleInteger353);
inline void require_uint32_admission353(bool qualified, bool bindings, const char* group) {
    if (!qualified) throw std::runtime_error(std::string("native_uint32_not_qualified:") + group);
    if (!bindings) throw std::runtime_error(std::string("native_uint32_symbol_unavailable:") + group);
}
inline bool valid_uint32_sample353(double value) {
    return std::isfinite(value) && !std::signbit(value) &&
           value <= static_cast<double>(kUint32Maximum353) && std::trunc(value) == value;
}
inline void require_uint32_sample353(double value, const char* error) {
    if (!valid_uint32_sample353(value)) throw std::runtime_error(error);
}
inline void require_uint32_mean353(double value) {
    if (!std::isfinite(value) || std::signbit(value) || value > static_cast<double>(kUint32Maximum353))
        throw std::runtime_error("native_uint32_mean_out_of_range");
}
inline void require_uint32_sum353(double sum, std::uint64_t pixels) {
    if (!pixels || pixels > kUint32StatisticsPixels353 || !std::isfinite(sum) || std::signbit(sum) ||
        std::trunc(sum) != sum || sum > static_cast<double>(pixels * kUint32Maximum353))
        throw std::runtime_error("native_uint32_summary_invalid_integer_sum");
}
inline void validate_uint32_summary353(double minimum, double maximum, double sum, double mean,
                                       std::uint64_t pixels) {
    require_uint32_sample353(minimum, "native_uint32_summary_invalid_integer_result");
    require_uint32_sample353(maximum, "native_uint32_summary_invalid_integer_result");
    require_uint32_sum353(sum, pixels);
    require_uint32_mean353(mean);
    // Range validation only: never derive a returned scalar from another one.
    if (minimum > maximum || mean < minimum || mean > maximum ||
        sum < minimum * static_cast<double>(pixels) || sum > maximum * static_cast<double>(pixels))
        throw std::runtime_error("native_uint32_summary_inconsistent_ranges");
}
} // namespace nb
