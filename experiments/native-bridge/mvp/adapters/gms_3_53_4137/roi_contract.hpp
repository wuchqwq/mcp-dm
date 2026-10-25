#pragma once
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <stdexcept>

namespace nb {
// These PODs describe only the separately traced fixed-build getter boundary.
// They are not a Gatan::DM C++ wrapper, a host vtable, or an SDK replacement.
struct RoiComponentHolder353 {
    std::int64_t references;
    void* document;
    std::int32_t component_id;
    std::uint32_t padding;
    void* cached_component;
};
static_assert(sizeof(RoiComponentHolder353) == 32);
static_assert(offsetof(RoiComponentHolder353, document) == 8);
static_assert(offsetof(RoiComponentHolder353, component_id) == 16);
static_assert(offsetof(RoiComponentHolder353, cached_component) == 24);
struct RoiRectangle353 { float top, left, bottom, right; };
struct RoiMapping353 { float offset_x, offset_y, scale_x, scale_y; };
struct RoiDimensions353 { std::uint32_t count; std::uint8_t valid; std::uint8_t padding[3]; };
struct RoiSliceId353 { std::uint32_t count; std::uint32_t components[5]; };
static_assert(sizeof(RoiSliceId353) == 24);
static_assert(sizeof(RoiMapping353) == 16 && sizeof(RoiDimensions353) == 8);
static_assert(sizeof(RoiRectangle353) == 16);
static_assert(offsetof(RoiRectangle353, left) == 4);
static_assert(offsetof(RoiRectangle353, bottom) == 8);
static_assert(offsetof(RoiRectangle353, right) == 12);
inline constexpr std::uint32_t kRoiDisplayLimit353 = 16;
inline constexpr std::uint32_t kRoiPerDisplayLimit353 = 64;
inline constexpr std::uint32_t kRoiTotalLimit353 = 128;
inline constexpr std::size_t kComponentIdentityOffset353 = 0x40;
inline constexpr std::size_t kDocumentIdentityOffset353 = 0xbc;
// SF ROIGetRotationAngle reads this double directly; SF setter's registered
// contract specifies angle_deg. Do not use the SF catch/default-zero route.
inline constexpr std::size_t kRoiRotationOffset353 = 0xc0;
inline constexpr std::size_t kRasterRoiCountSlot353 = 0x538;
inline constexpr std::size_t kRasterRoiGetSlot353 = 0x590;
inline constexpr std::size_t kRasterRoiDimensionsSlot353 = 0x3a0;
inline constexpr std::size_t kRasterRoiMappingSlot353 = 0x3a8;
inline constexpr std::size_t kRasterRoiSliceIdSlot353 = 0x3d0;
inline constexpr std::size_t kRasterImageSourceOffset353 = 0xd8;
inline constexpr std::size_t kImageSourceImplementationOffset353 = 0xa0;
inline constexpr std::size_t kSimpleSourceImageOffset353 = 0x50;
inline constexpr std::size_t kSimpleSourceCountSlot353 = 0x18;
inline constexpr std::size_t kSimpleSourceSliceIdSlot353 = 0x20;
inline constexpr std::size_t kSimpleSourceExtentsSlot353 = 0x30;

// Preserve native coordinates. Only exact integral, nonempty, in-bounds edges
// become a crop/READ rectangle; no floor, ceil, clipping or fallback to a frame.
inline const char* roi_rectangle_issue353(const RoiRectangle353& r,
                                         std::uint32_t width, std::uint32_t height) {
    for (float value : {r.top, r.left, r.bottom, r.right})
        if (!std::isfinite(value)) throw std::runtime_error("native_roi_nonfinite_rectangle");
    if (r.left >= r.right || r.top >= r.bottom) return "empty_or_reversed_rectangle";
    for (float value : {r.top, r.left, r.bottom, r.right})
        if (std::trunc(value) != value) return "fractional_rectangle";
    if (r.left < 0 || r.top < 0 || static_cast<double>(r.right) > width ||
        static_cast<double>(r.bottom) > height) return "out_of_bounds_rectangle";
    return nullptr;
}
} // namespace nb
