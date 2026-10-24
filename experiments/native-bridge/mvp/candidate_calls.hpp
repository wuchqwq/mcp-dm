#pragma once
#include <cstddef>
#include <string_view>
#include <type_traits>

namespace nb::candidate {

// OFFLINE CANDIDATE ONLY. This module neither loads vendor code nor supplies a
// production binding/resolver. Its injected callbacks must be synthetic. The
// signatures below are Win64 call-shape candidates, not qualified DM APIs.
struct ImageRef { void* image; };
static_assert(std::is_trivial<ImageRef>::value);
static_assert(std::is_standard_layout<ImageRef>::value);
static_assert(sizeof(void*) == 8 && sizeof(ImageRef) == 8);
static_assert(alignof(ImageRef) == 8 && offsetof(ImageRef, image) == 0);

using Unary = ImageRef* (*)(ImageRef* out, const ImageRef* source);
using Binary = ImageRef* (*)(ImageRef* out, const ImageRef* source, const ImageRef* rhs);
using Reduction = double (*)(const ImageRef* source);
// Release exactly one owned reference. The injector supplies the reference
// decrement/conditional destruction policy; a vendor final-delete alone is NOT
// a release callback. Context must outlive every OwnedImage using it.
using Release = void (*)(void* context, ImageRef owned) noexcept;

enum class Signature { Unary, Binary, Reduction, Blocked };
enum class Qualification { NotQualified };
struct OperationSpec {
    std::string_view key;
    std::string_view exact_symbol;
    Signature signature;
    std::string_view evidence;
    Qualification qualification;
    bool synthetic_callable;
};

// Immutable catalogue: exact exports are evidence labels, never addresses to
// resolve. Every entry remains NOT_QUALIFIED for production. Blocked
// pixel_count/mean_and_variance/minimum_maximum have known exact exports but
// signatures outside these three adapters. geometry/save/preview are only
// categories with no asserted symbol. All blocked entries reject invocation.
const OperationSpec* catalog(std::size_t& count) noexcept;
const OperationSpec* find_operation(std::string_view key) noexcept;

struct SyntheticBindings {
    Unary unary = nullptr;
    Binary binary = nullptr;
    Reduction reduction = nullptr;
    Release release = nullptr;
    void* release_context = nullptr;
};

class OwnedImage {
public:
    OwnedImage() noexcept = default;
    ~OwnedImage();
    OwnedImage(const OwnedImage&) = delete;
    OwnedImage& operator=(const OwnedImage&) = delete;
    OwnedImage(OwnedImage&& other) noexcept;
    OwnedImage& operator=(OwnedImage&& other) noexcept;

    // Borrowed view only: the caller must not release this reference itself.
    ImageRef get() const noexcept { return image_; }
    explicit operator bool() const noexcept { return image_.image != nullptr; }
    void reset() noexcept;

private:
    OwnedImage(ImageRef image, Release release, void* context) noexcept;
    ImageRef image_{};
    Release release_ = nullptr;
    void* context_ = nullptr;
    friend OwnedImage invoke_unary(const OperationSpec&, const SyntheticBindings&, ImageRef);
    friend OwnedImage invoke_binary(const OperationSpec&, const SyntheticBindings&, ImageRef, ImageRef);
};

// Accept only an original catalogue entry and exactly its typed callback.
// Borrowed input descriptors are copied; no input reference is acquired or
// released. An output must be a distinct, nonnull owned reference written only
// into `out`, with the callback returning that exact sret address. Writing a
// nonnull out transfers one owned reference even if it aliases an input: the
// callback must have acquired that extra reference. On rejection (including
// alias) or a C++ exception, release that returned ownership exactly once;
// borrowed input ownership is never released. Never
// inspect/dereference a foreign returned sret pointer. Native faults are not
// isolated and cannot be made safe by this C++ exception boundary.
OwnedImage invoke_unary(const OperationSpec& operation, const SyntheticBindings& bindings,
                        ImageRef source);
OwnedImage invoke_binary(const OperationSpec& operation, const SyntheticBindings& bindings,
                         ImageRef source, ImageRef rhs);
double invoke_reduction(const OperationSpec& operation, const SyntheticBindings& bindings,
                        ImageRef source);

} // namespace nb::candidate
