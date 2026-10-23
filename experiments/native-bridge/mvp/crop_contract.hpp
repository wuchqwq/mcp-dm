#pragma once
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <stdexcept>
#include <type_traits>

namespace nb {
// Explicit fixed-build DataSlice representation. No STL object crosses DM's ABI.
struct NativeSliceAxis353 {
    std::uint32_t source_dimension;
    std::uint32_t padding;
    std::int64_t length;
    std::int64_t step;
};
struct NativeDataSlice353 {
    std::uint32_t source_dimensions;
    std::uint32_t padding0;
    std::int64_t source_start[5];
    std::uint32_t output_dimensions;
    std::uint32_t padding1;
    NativeSliceAxis353 output_axes[5];
};
static_assert(std::is_standard_layout<NativeDataSlice353>::value);
static_assert(std::is_trivial<NativeDataSlice353>::value);
static_assert(sizeof(NativeSliceAxis353) == 24 && alignof(NativeSliceAxis353) == 8);
static_assert(offsetof(NativeSliceAxis353, source_dimension) == 0);
static_assert(offsetof(NativeSliceAxis353, length) == 8);
static_assert(offsetof(NativeSliceAxis353, step) == 16);
static_assert(sizeof(NativeDataSlice353) == 176 && alignof(NativeDataSlice353) == 8);
static_assert(offsetof(NativeDataSlice353, source_dimensions) == 0);
static_assert(offsetof(NativeDataSlice353, source_start) == 8);
static_assert(offsetof(NativeDataSlice353, output_dimensions) == 48);
static_assert(offsetof(NativeDataSlice353, output_axes) == 56);

constexpr std::uint64_t kCropOutputBytes = 4ull * 1024 * 1024;
constexpr std::uint64_t kCropRetainedBytes = 16ull * 1024 * 1024;
constexpr std::size_t kCropRetainedCount = 32;
struct CropPlan {
    NativeDataSlice353 slice{};
    std::array<std::uint32_t, 4> rect;
    std::uint32_t width, height;
    std::uint64_t bytes;
};
inline CropPlan crop_plan(std::uint32_t source_width, std::uint32_t source_height,
                          std::array<std::uint32_t, 4> rect,
                          std::uint64_t retained_bytes, std::size_t retained_count) {
    if (!source_width || !source_height) throw std::runtime_error("invalid_image_dimensions");
    if (rect[0] >= rect[2] || rect[1] >= rect[3])
        throw std::runtime_error("native_crop_empty_or_reversed_rect");
    if (rect[2] > source_width || rect[3] > source_height)
        throw std::runtime_error("native_crop_rect_out_of_bounds");
    // This native calibration routine first converts the offset to float32.
    // Reject an inexact offset instead of silently changing its spatial meaning.
    for (unsigned d = 0; d < 2; ++d) {
        if (static_cast<double>(static_cast<float>(rect[d])) != rect[d])
            throw std::runtime_error("native_crop_offset_not_exact_float32");
    }
    const auto width = rect[2] - rect[0], height = rect[3] - rect[1];
    const auto pixels = static_cast<std::uint64_t>(width) * height;
    if (pixels > kCropOutputBytes / sizeof(float))
        throw std::runtime_error("native_crop_output_over_budget");
    const auto bytes = pixels * sizeof(float);
    if (retained_count >= kCropRetainedCount)
        throw std::runtime_error("native_crop_retention_capacity");
    if (retained_bytes > kCropRetainedBytes || bytes > kCropRetainedBytes - retained_bytes)
        throw std::runtime_error("native_crop_retained_bytes_over_budget");
    CropPlan plan{{}, rect, width, height, bytes};
    plan.slice.source_dimensions = plan.slice.output_dimensions = 2;
    plan.slice.source_start[0] = rect[0];
    plan.slice.source_start[1] = rect[1];
    plan.slice.output_axes[0] = {0, 0, width, 1};
    plan.slice.output_axes[1] = {1, 0, height, 1};
    return plan;
}

inline double half_float_ulp(float value) {
    const auto infinity = std::numeric_limits<float>::infinity();
    const auto up = std::nextafter(value, infinity);
    const auto down = std::nextafter(value, -infinity);
    const double upper = std::isfinite(up) ? static_cast<double>(up) - value : 0;
    const double lower = std::isfinite(down) ? static_cast<double>(value) - down : 0;
    return (upper > lower ? upper : lower) / 2;
}
struct CropZeroCheck { double expected, absolute_error, tolerance; };
inline CropZeroCheck crop_zero_check(float source_zero, float source_scale,
                                    float source_origin, std::uint32_t offset,
                                    float output_zero) {
    const float shifted_origin = source_origin - static_cast<float>(offset);
    const double expected = static_cast<double>(source_zero) +
                            static_cast<double>(offset) * source_scale;
    const double next = std::nextafter(expected, std::numeric_limits<double>::infinity());
    const double double_rounding = std::isfinite(next) ? (next - expected) / 2 : 0;
    // Error propagation for binary32 source zero, shifted index origin, and
    // output zero, plus the final binary64 oracle addition. No relative epsilon.
    const double tolerance = half_float_ulp(source_zero) +
        std::abs(static_cast<double>(source_scale)) * half_float_ulp(shifted_origin) +
        half_float_ulp(output_zero) + double_rounding;
    return {expected, std::abs(static_cast<double>(output_zero) - expected), tolerance};
}
} // namespace nb
