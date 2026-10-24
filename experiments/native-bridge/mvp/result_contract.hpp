#pragma once
#include "crop_contract.hpp"
#include <cstdint>
#include <stdexcept>

namespace nb {
enum class UnaryOpcode : std::uint32_t { Negate = 1, Abs = 2, Square = 3 };
enum class BinaryOpcode : std::uint32_t { Add = 1, Subtract = 2, Multiply = 3, DivideBlocked = 4 };
inline const char* unary_operation(std::uint32_t code) {
    switch (code) {
    case 1: return "negate";
    case 2: return "abs";
    case 3: return "square";
    default: throw std::runtime_error("native_unary_opcode_unsupported");
    }
}
inline const char* binary_operation(std::uint32_t code) {
    switch (code) {
    case 1: return "add";
    case 2: return "subtract";
    case 3: return "multiply";
    case 4: throw std::runtime_error("native_divide_not_qualified");
    default: throw std::runtime_error("native_binary_opcode_unsupported");
    }
}
inline std::uint64_t native_result_bytes(std::uint32_t width, std::uint32_t height,
                                       std::uint32_t bytes_per_pixel,
                                       std::uint64_t retained_bytes, std::size_t retained_count) {
    if (!width || !height || !bytes_per_pixel) throw std::runtime_error("invalid_image_dimensions");
    const auto pixels = static_cast<std::uint64_t>(width) * height;
    if (pixels > kCropOutputBytes / bytes_per_pixel) throw std::runtime_error("native_result_output_over_budget");
    const auto bytes = pixels * bytes_per_pixel;
    if (retained_count >= kCropRetainedCount) throw std::runtime_error("native_result_retention_capacity");
    if (retained_bytes > kCropRetainedBytes || bytes > kCropRetainedBytes - retained_bytes)
        throw std::runtime_error("native_result_retained_bytes_over_budget");
    return bytes;
}
} // namespace nb
