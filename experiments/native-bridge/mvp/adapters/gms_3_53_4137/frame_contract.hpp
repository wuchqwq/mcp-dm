#pragma once
#include "crop_contract.hpp"
#include <cstdint>
#include <stdexcept>

namespace nb {
constexpr std::uint32_t kFrameUint16Code353 = 10;
constexpr std::uint64_t kFramePixels353 = 1048576;
struct FramePlan353 {
    NativeDataSlice353 slice{};
    std::uint32_t width, height, frames, index;
    std::uint64_t pixels, bytes, peak_bytes;
};
inline FramePlan353 frame_plan353(std::uint32_t width, std::uint32_t height,
                                 std::uint32_t frames, std::uint32_t index,
                                 std::uint64_t retained_bytes, std::size_t retained_count) {
    if (!width || !height || !frames) throw std::runtime_error("native_frame_invalid_dimensions");
    if (index >= frames) throw std::runtime_error("native_frame_index_out_of_bounds");
    const auto pixels = static_cast<std::uint64_t>(width) * height;
    // The qualified native ordinary-data reader checks a uint32 byte offset.
    // Bound the complete stack without overflowing a multiplied frame count.
    if (pixels > UINT32_MAX / 2 || frames > (UINT32_MAX / 2) / pixels)
        throw std::runtime_error("native_frame_source_over_budget");
    if (pixels > kFramePixels353) throw std::runtime_error("native_frame_plane_over_budget");
    const auto bytes = pixels * 4, peak = pixels * 6;
    if (retained_count > kCropRetainedCount - 2)
        throw std::runtime_error("native_frame_temporary_object_capacity");
    if (retained_bytes > kCropRetainedBytes || peak > kCropRetainedBytes - retained_bytes)
        throw std::runtime_error("native_frame_temporary_bytes_over_budget");
    FramePlan353 plan{{}, width, height, frames, index, pixels, bytes, peak};
    plan.slice.source_dimensions = 3;
    plan.slice.source_start[2] = index;
    plan.slice.output_dimensions = 2;
    plan.slice.output_axes[0] = {0, 0, width, 1};
    plan.slice.output_axes[1] = {1, 0, height, 1};
    return plan;
}
} // namespace nb
