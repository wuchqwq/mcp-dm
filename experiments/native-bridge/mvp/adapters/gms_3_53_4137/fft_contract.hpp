#pragma once
#include "crop_contract.hpp"
#include <cstddef>
#include <cstdint>
#include <cmath>
#include <stdexcept>
#include <string_view>
#include <type_traits>

namespace nb {
// Explicit vendor output representation. Its member getter uses this in RCX
// and the caller's 4-byte result address in RDX, returning that address in RAX.
// Never bind GetPackingStyle as a uint32-returning image Getter.
struct NativePacking353 { std::uint32_t value; };
static_assert(std::is_standard_layout<NativePacking353>::value);
static_assert(std::is_trivial<NativePacking353>::value);
static_assert(sizeof(NativePacking353) == 4 && alignof(NativePacking353) == 4);
static_assert(offsetof(NativePacking353, value) == 0);

enum class FftOperation353 { RealForward, ComplexInverse, Real, Imag, VendorArg, VendorNorm };
constexpr std::uint32_t kFftMaximumDimension353 = 256;
constexpr std::uint64_t kFftMaximumPixels353 = 65536;

inline bool is_fft_operation353(std::string_view operation) noexcept {
    return operation == "FFT" || operation == "IFFT" || operation == "REAL" ||
           operation == "IMAG" || operation == "VENDOR_ARG" || operation == "VENDOR_NORM";
}
inline FftOperation353 fft_operation353(std::string_view operation) {
    if (operation == "FFT") return FftOperation353::RealForward;
    if (operation == "IFFT") return FftOperation353::ComplexInverse;
    if (operation == "REAL") return FftOperation353::Real;
    if (operation == "IMAG") return FftOperation353::Imag;
    if (operation == "VENDOR_ARG") return FftOperation353::VendorArg;
    if (operation == "VENDOR_NORM") return FftOperation353::VendorNorm;
    throw std::runtime_error("native_fft_unknown_operation");
}
inline const char* fft_operator353(FftOperation353 operation) {
    switch (operation) {
    case FftOperation353::RealForward: return "GMSImageProcessing::Real_FFT";
    case FftOperation353::ComplexInverse: return "GMSImageProcessing::IFFT";
    case FftOperation353::Real: return "GMSImageProcessing::Real";
    case FftOperation353::Imag: return "GMSImageProcessing::Imag";
    case FftOperation353::VendorArg: return "GMSImageProcessing::Arg";
    case FftOperation353::VendorNorm: return "GMSImageProcessing::Norm";
    }
    throw std::runtime_error("native_fft_unknown_operation");
}
inline const char* fft_representation353(FftOperation353 operation) {
    switch (operation) {
    case FftOperation353::RealForward:
    case FftOperation353::ComplexInverse: return "full_complex";
    case FftOperation353::Real: return "real_component";
    case FftOperation353::Imag: return "imaginary_component";
    case FftOperation353::VendorArg: return "phase_radians";
    case FftOperation353::VendorNorm: return "squared_magnitude";
    }
    throw std::runtime_error("native_fft_unknown_operation");
}
struct FftImage353 {
    std::uint32_t id, dimensions, data_type, packing, width, height;
};
struct FftPlan353 {
    FftOperation353 operation;
    std::uint32_t width, height, output_data_type;
    std::uint64_t pixels, output_bytes, peak_new_bytes;
    std::size_t peak_new_images;
};
inline bool fft_dimension_supported353(std::uint32_t size) noexcept {
    return size >= 4 && size <= kFftMaximumDimension353 && (size & (size - 1)) == 0;
}
inline const char* fft_normalization353(FftOperation353 operation) {
    if (operation == FftOperation353::RealForward) return "none";
    if (operation == FftOperation353::ComplexInverse) return "1/(width*height)";
    (void)fft_operator353(operation);
    return "inherited_parent_transform";
}
inline constexpr const char* kFftIntensityPolicy353 =
    "DM Fourier outputs reset intensity calibration to origin 0, scale 1, empty unit; components inherit parent calibration";
inline float fft_reciprocal_scale353(std::uint32_t size, float scale) {
    // The vendor calibration stores binary32 and uses this binary32 operation
    // order. This validates metadata only, never transforms scientific pixels.
    const float divisor = static_cast<float>(size) * scale;
    const float reciprocal = 1.0f / divisor;
    if (!std::isfinite(divisor) || divisor == 0 || !std::isfinite(reciprocal) || reciprocal == 0)
        throw std::runtime_error("native_fft_frequency_scale_unrepresentable");
    return reciprocal;
}
inline void validate_fft_frequency_calibration353(std::uint32_t size, float input_scale,
                                                 float actual_scale, float raw_origin, float zero) {
    const float expected_scale = fft_reciprocal_scale353(size, input_scale);
    const float expected_origin = (static_cast<float>(size) + 1.0f) / 2.0f;
    if (actual_scale != expected_scale || raw_origin != expected_origin ||
        !std::isfinite(zero) || zero != -(actual_scale * raw_origin))
        throw std::runtime_error("native_fft_frequency_calibration_mismatch");
}
inline void validate_ifft_spatial_calibration353(std::uint32_t size, float input_scale,
                                                float actual_scale, float raw_origin, float zero) {
    if (actual_scale != fft_reciprocal_scale353(size, input_scale) || raw_origin != 0 || zero != 0)
        throw std::runtime_error("native_ifft_spatial_calibration_mismatch");
}
inline FftPlan353 fft_plan353(FftOperation353 operation, const FftImage353& source,
                             std::uint64_t retained_bytes, std::size_t retained_count) {
    // Resolve enum validity before any native allocation, including casted enums.
    (void)fft_operator353(operation);
    const auto expected_input = operation == FftOperation353::RealForward ? 2u : 3u;
    if (source.dimensions != 2 || (source.data_type != expected_input &&
        !(operation == FftOperation353::RealForward && source.data_type == 11)))
        throw std::runtime_error("native_fft_input_type_or_dimensions_unsupported");
    if (source.packing != 1)
        throw std::runtime_error("native_fft_requires_ordinary_packing");
    if (!source.width || !source.height)
        throw std::runtime_error("invalid_image_dimensions");
    const auto pixels = static_cast<std::uint64_t>(source.width) * source.height;
    if (source.width > kFftMaximumDimension353 || source.height > kFftMaximumDimension353 ||
        pixels > kFftMaximumPixels353)
        throw std::runtime_error("native_fft_input_over_budget");
    if (!fft_dimension_supported353(source.width) || !fft_dimension_supported353(source.height))
        throw std::runtime_error("native_fft_requires_power_of_two_dimensions_4_to_256");
    const auto output_type = operation == FftOperation353::RealForward ||
                             operation == FftOperation353::ComplexInverse ? 3u : 2u;
    // Code3 ordinary complex has two binary32 components; this is byte accounting,
    // not permission to reinterpret or compute on the vendor pixel buffer.
    const auto bytes = pixels * (output_type == 3 ? 8ull : 4ull);
    // Complex results remain guarded while one native Real/Imag verification
    // image exists. Real and imaginary temporaries are checked/released one at
    // a time. For real derivations, input temporaries finish before the result
    // is allocated, so their maximum is one real image rather than an addition.
    const auto peak_bytes = bytes + (output_type == 3 ? pixels * 4ull : 0ull);
    const std::size_t peak_images = output_type == 3 ? 2u : 1u;
    if (bytes > kCropOutputBytes)
        throw std::runtime_error("native_fft_output_over_budget");
    if (retained_count > kCropRetainedCount || peak_images > kCropRetainedCount - retained_count)
        throw std::runtime_error("native_fft_retention_capacity");
    if (retained_bytes > kCropRetainedBytes || peak_bytes > kCropRetainedBytes - retained_bytes)
        throw std::runtime_error("native_fft_retained_bytes_over_budget");
    return {operation, source.width, source.height, output_type, pixels, bytes, peak_bytes, peak_images};
}
inline void validate_fft_output353(const FftPlan353& plan, const FftImage353& source,
                                   const FftImage353& output) {
    if (!output.id || output.id == source.id)
        throw std::runtime_error("native_fft_output_identity_invalid");
    if (output.dimensions != 2 || output.data_type != plan.output_data_type || output.packing != 1 ||
        output.width != plan.width || output.height != plan.height)
        throw std::runtime_error("native_fft_output_descriptor_mismatch");
}
// The small-input policy does not bound native temporary workspace or qualify
// arbitrary-size numerical accuracy, source nonmutation or pixel independence.
// The v2 conventions were independently checked on the small prepared fixture;
// accepted IFFT inputs are plugin-retained FFTs, never arbitrary complex images.
} // namespace nb
