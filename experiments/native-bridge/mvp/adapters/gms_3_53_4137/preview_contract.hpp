#pragma once
#include <cstddef>
#include <cstdint>
#include <stdexcept>
#include <type_traits>

namespace nb {
// This is the completely described prefix consumed by the selected ordinary,
// strictly 2D GetRealValue path, NOT an assertion about sizeof the vendor's
// general DataIndex class. Code inspection of IsValidCoordinate/CoordToOffset
// reads uint32 dimension count at0 and int64 indices at8+8*axis. With both the
// image and this count fixed to2, only offsets0,8,16 are read. No DataIndex
// constructor/destructor, full-object copy or opaque lock crosses this path.
struct NativeDataIndex2D353 {
    std::uint32_t dimensions;
    std::uint32_t padding;
    std::int64_t x, y;
};
static_assert(std::is_standard_layout<NativeDataIndex2D353>::value);
static_assert(std::is_trivial<NativeDataIndex2D353>::value);
static_assert(sizeof(NativeDataIndex2D353) == 24 && alignof(NativeDataIndex2D353) == 8);
static_assert(offsetof(NativeDataIndex2D353, dimensions) == 0);
static_assert(offsetof(NativeDataIndex2D353, x) == 8);
static_assert(offsetof(NativeDataIndex2D353, y) == 16);

constexpr std::uint32_t kPreviewDimension353 = 128;
constexpr std::uint64_t kPreviewSamples353 = 16384;
constexpr std::uint64_t kPreviewSourcePixels353 = 4194304;
struct PreviewPlan353 {
    std::uint32_t source_width, source_height, width, height;
    std::uint64_t samples;
};
inline PreviewPlan353 preview_plan353(std::uint32_t source_width, std::uint32_t source_height,
                                     std::uint32_t max_width, std::uint32_t max_height) {
    if (!max_width || !max_height || max_width > kPreviewDimension353 || max_height > kPreviewDimension353)
        throw std::runtime_error("native_preview_dimensions_out_of_range");
    if (!source_width || !source_height) throw std::runtime_error("invalid_image_dimensions");
    // Keep the selected native offset path inside the existing bounded scalar
    // image scope. This does not imply that the whole source is read or copied.
    if (static_cast<std::uint64_t>(source_width) * source_height > kPreviewSourcePixels353)
        throw std::runtime_error("native_preview_source_over_budget");
    const auto width = source_width < max_width ? source_width : max_width;
    const auto height = source_height < max_height ? source_height : max_height;
    const auto samples = static_cast<std::uint64_t>(width) * height;
    if (samples > kPreviewSamples353) throw std::runtime_error("native_preview_samples_over_budget");
    return {source_width, source_height, width, height, samples};
}
inline NativeDataIndex2D353 preview_index353(const PreviewPlan353& plan,
                                            std::uint32_t px, std::uint32_t py) {
    if (!plan.width || !plan.height || px >= plan.width || py >= plan.height)
        throw std::runtime_error("native_preview_sample_out_of_bounds");
    // Display-only nearest index mapping, no averaging or scientific resampling.
    const auto x = static_cast<std::uint64_t>(px) * plan.source_width / plan.width;
    const auto y = static_cast<std::uint64_t>(py) * plan.source_height / plan.height;
    if (x >= plan.source_width || y >= plan.source_height)
        throw std::runtime_error("native_preview_source_index_out_of_bounds");
    return {2, 0, static_cast<std::int64_t>(x), static_cast<std::int64_t>(y)};
}
} // namespace nb
