#pragma once
#include <cstddef>
#include <cstdint>
namespace nb {
// Imaging::DataSize is a rank/extent POD: a uint32 dimension count at offset 0
// followed by int64 extents at offset 8. Check_ImageDataSize reads exactly that
// pair (rank dword, non-zero int64 extents indexed by dimension), and the same
// pattern is already qualified for Imaging::DataSlice.
struct NativeDataSize353 {
    std::uint32_t dimensions = 0, padding = 0;
    std::int64_t size[5] = {0, 0, 0, 0, 0};
};
static_assert(sizeof(NativeDataSize353) == 48 && alignof(NativeDataSize353) == 8);
static_assert(offsetof(NativeDataSize353, size) == 8);
// Gatan::char_range_t<wchar_t> is a begin/end pair, NOT pointer+length:
// SetUnicodeName computes (end-begin)/2 and compares wchar elements.
struct NativeCharRange353 { const wchar_t* begin = nullptr; const wchar_t* end = nullptr; };
static_assert(sizeof(NativeCharRange353) == 16);
inline constexpr std::uint32_t kHistogramBinsMin353 = 2;
inline constexpr std::uint32_t kHistogramBinsMax353 = 4096;
inline constexpr std::uint32_t kHistogramUint32Code353 = 11;
} // namespace nb
