#pragma once
#include <cstddef>
#include <cstdint>

namespace nb {
// Fixed-build holder returned by the native image-to-document factory. The
// allocation and its document reference remain owned by the vendor runtime.
struct ScriptImageDocument353 {
    std::int64_t references;
    void* document;
};
static_assert(sizeof(ScriptImageDocument353) == 16);
static_assert(alignof(ScriptImageDocument353) == 8);
static_assert(offsetof(ScriptImageDocument353, references) == 0);
static_assert(offsetof(ScriptImageDocument353, document) == 8);
constexpr std::size_t kNativeWindowReferenceOffset353 = 0x50;
} // namespace nb
