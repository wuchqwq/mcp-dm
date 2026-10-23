#include "candidate_calls.hpp"
#include <cmath>
#include <stdexcept>
#include <utility>

namespace nb::candidate {
namespace {
constexpr std::string_view kUnaryEvidence =
    "WRAPPER_REVIEWED_STATIC_PARTIAL; domains, packing, calibration, source protection and ownership NOT_QUALIFIED";
constexpr std::string_view kFftEvidence =
    "FFT_WRAPPER_REVIEWED_STATIC_PARTIAL; complex/real/packed inputs differ; normalization, center and ownership NOT_QUALIFIED";
constexpr std::string_view kFilterEvidence =
    "WRAPPER_REVIEWED_STATIC_PARTIAL; native CreateImage/filter delegation; dtype, kernel, boundary and calibration NOT_QUALIFIED";
constexpr std::string_view kBinaryEvidence =
    "WRAPPER_REVIEWED_STATIC_PARTIAL; native BinaryOp delegation; domains, shape policy, source protection and ownership NOT_QUALIFIED";
constexpr std::string_view kPhaseEvidence =
    "WRAPPER_REVIEWED_STATIC_PARTIAL; phase correlation, not ordinary cross correlation; numerical and ownership semantics NOT_QUALIFIED";
constexpr std::string_view kReductionEvidence =
    "WRAPPER_REVIEWED_STATIC_PARTIAL; native locked reduction; dtype, nonfinite, precision, median and variance/stddev conventions NOT_QUALIFIED";
constexpr std::string_view kOtherShape =
    "EXPORTED_OTHER_SIGNATURE; not adapted to Unary/Binary/Reduction; NOT_QUALIFIED";
constexpr std::string_view kUnadapted =
    "BLOCKED_CATEGORY; no asserted export or call shape; NOT_QUALIFIED";
constexpr auto kNotQualified = Qualification::NotQualified;

// These literal names/symbols come from reviewed export and thin-wrapper
// shapes. No ordinal, address, generic-op enum or runtime resolver is supplied.
// All callable entries mean SYNTHETIC CALLBACK COVERAGE ONLY, not DM support.
#define NB_UNARY(KEY, NAME, EVIDENCE) \
    {KEY, "?" NAME "@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z", Signature::Unary, EVIDENCE, kNotQualified, true}
#define NB_REDUCTION(KEY, NAME) \
    {KEY, "?" NAME "@GMSImageProcessing@@YANAEBV?$ref_ptr@VImage@GMS@@@Gatan@@@Z", Signature::Reduction, kReductionEvidence, kNotQualified, true}
constexpr OperationSpec kCatalog[] = {
    NB_UNARY("fft", "FFT", kFftEvidence),
    NB_UNARY("real_fft", "Real_FFT", kFftEvidence),
    NB_UNARY("packed_fft", "Packed_FFT", kFftEvidence),
    NB_UNARY("ifft", "IFFT", kFftEvidence),
    NB_UNARY("real_ifft", "Real_IFFT", kFftEvidence),
    NB_UNARY("packed_ifft", "Packed_IFFT", kFftEvidence),
    NB_UNARY("abs", "Abs", kUnaryEvidence),
    NB_UNARY("negate", "Negate", kUnaryEvidence),
    NB_UNARY("square", "Square", kUnaryEvidence),
    NB_UNARY("sqrt", "Sqrt", kUnaryEvidence),
    NB_UNARY("log", "Log", kUnaryEvidence),
    NB_UNARY("log10", "Log10", kUnaryEvidence),
    NB_UNARY("exp", "Exp", kUnaryEvidence),
    NB_UNARY("real", "Real", kUnaryEvidence),
    NB_UNARY("imag", "Imag", kUnaryEvidence),
    NB_UNARY("arg", "Arg", kUnaryEvidence),
    NB_UNARY("conj", "Conj", kUnaryEvidence),
    NB_UNARY("norm", "Norm", kUnaryEvidence),
    NB_UNARY("smooth", "SmoothFilter", kFilterEvidence),
    NB_UNARY("sobel", "SobelFilter", kFilterEvidence),
    NB_UNARY("laplace", "LaplaceFilter", kFilterEvidence),
    NB_UNARY("sharpen", "SharpenFilter", kFilterEvidence),
    {"add", "??HGMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV12@0@Z",
     Signature::Binary, kBinaryEvidence, kNotQualified, true},
    {"subtract", "??GGMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV12@0@Z",
     Signature::Binary, kBinaryEvidence, kNotQualified, true},
    {"multiply", "??DGMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV12@0@Z",
     Signature::Binary, kBinaryEvidence, kNotQualified, true},
    {"divide", "??KGMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV12@0@Z",
     Signature::Binary, kBinaryEvidence, kNotQualified, true},
    {"phase_cross_correlation", "?PhaseCrossCorrelation@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@0@Z",
     Signature::Binary, kPhaseEvidence, kNotQualified, true},
    NB_REDUCTION("maximum", "GetMaximum"),
    NB_REDUCTION("mean", "GetMean"),
    NB_REDUCTION("minimum", "GetMinimum"),
    NB_REDUCTION("sum", "GetSum"),
    NB_REDUCTION("variance", "GetVariance"),
    NB_REDUCTION("median", "GetMedian"),
    NB_REDUCTION("stddev", "GetStdDev"),
    {"pixel_count", "?GetPixelCount@GMSImageProcessing@@YA_KAEBV?$ref_ptr@VImage@GMS@@@Gatan@@@Z",
     Signature::Blocked, kOtherShape, kNotQualified, false},
    {"mean_and_variance", "?GetMeanAndVariance@GMSImageProcessing@@YAXAEBV?$ref_ptr@VImage@GMS@@@Gatan@@AEAN1@Z",
     Signature::Blocked, kOtherShape, kNotQualified, false},
    {"minimum_maximum", "?GetMinimumMaximum@GMSImageProcessing@@YAXAEBV?$ref_ptr@VImage@GMS@@@Gatan@@AEAN1@Z",
     Signature::Blocked, kOtherShape, kNotQualified, false},
    // Categories only: these are not guessed vendor operation names.
    {"geometry", {}, Signature::Blocked, kUnadapted, kNotQualified, false},
    {"save", {}, Signature::Blocked, kUnadapted, kNotQualified, false},
    {"preview", {}, Signature::Blocked, kUnadapted, kNotQualified, false},
};
#undef NB_UNARY
#undef NB_REDUCTION

[[noreturn]] void fail(const char* code) { throw std::runtime_error(code); }

void validate_spec(const OperationSpec& operation, Signature expected) {
    bool known = false;
    for (const auto& entry : kCatalog) {
        if (&entry == &operation) { known = true; break; }
    }
    if (!known) fail("candidate_operation_not_catalogued");
    if (!operation.synthetic_callable || operation.signature == Signature::Blocked)
        fail("candidate_operation_blocked");
    if (operation.signature != expected) fail("candidate_signature_mismatch");
}

void validate_bindings(const SyntheticBindings& bindings, Signature expected) {
    if ((expected != Signature::Unary && bindings.unary) ||
        (expected != Signature::Binary && bindings.binary) ||
        (expected != Signature::Reduction && bindings.reduction))
        fail("candidate_binding_shape_mismatch");
    if ((expected == Signature::Unary && !bindings.unary) ||
        (expected == Signature::Binary && !bindings.binary) ||
        (expected == Signature::Reduction && !bindings.reduction))
        fail("candidate_missing_binding");
    if (expected != Signature::Reduction && !bindings.release)
        fail("candidate_missing_release");
}

struct OutputGuard {
    ImageRef value{};
    Release release;
    void* context;
    OutputGuard(Release callback, void* callback_context) noexcept
        : release(callback), context(callback_context) {}
    OutputGuard(const OutputGuard&) = delete;
    OutputGuard& operator=(const OutputGuard&) = delete;
    ~OutputGuard() {
        // A nonnull written slot owns one returned reference, including when
        // a contract-violating alias must be rejected. Release that extra
        // ownership; never independently release the borrowed inputs.
        if (value.image) release(context, value);
    }
    ImageRef take() noexcept { return std::exchange(value, ImageRef{}); }
};

void validate_output(const OutputGuard& output, const ImageRef* returned,
                     ImageRef source, ImageRef rhs = {}) {
    if (returned != &output.value) fail("candidate_sret_mismatch");
    if (!output.value.image) fail("candidate_output_null");
    if (output.value.image == source.image ||
        (rhs.image && output.value.image == rhs.image))
        fail("candidate_output_alias");
}
} // namespace

const OperationSpec* catalog(std::size_t& count) noexcept {
    count = sizeof(kCatalog) / sizeof(kCatalog[0]);
    return kCatalog;
}

const OperationSpec* find_operation(std::string_view key) noexcept {
    for (const auto& operation : kCatalog) if (operation.key == key) return &operation;
    return nullptr;
}

OwnedImage::OwnedImage(ImageRef image, Release release, void* context) noexcept
    : image_(image), release_(release), context_(context) {}

OwnedImage::~OwnedImage() { reset(); }

OwnedImage::OwnedImage(OwnedImage&& other) noexcept
    : image_(std::exchange(other.image_, ImageRef{})),
      release_(std::exchange(other.release_, nullptr)),
      context_(std::exchange(other.context_, nullptr)) {}

OwnedImage& OwnedImage::operator=(OwnedImage&& other) noexcept {
    if (this != &other) {
        reset();
        image_ = std::exchange(other.image_, ImageRef{});
        release_ = std::exchange(other.release_, nullptr);
        context_ = std::exchange(other.context_, nullptr);
    }
    return *this;
}

void OwnedImage::reset() noexcept {
    const auto image = std::exchange(image_, ImageRef{});
    const auto release = std::exchange(release_, nullptr);
    void* const context = std::exchange(context_, nullptr);
    if (image.image) release(context, image);
}

OwnedImage invoke_unary(const OperationSpec& operation, const SyntheticBindings& bindings,
                        ImageRef source) {
    validate_spec(operation, Signature::Unary);
    validate_bindings(bindings, Signature::Unary);
    if (!source.image) fail("candidate_null_source");
    const auto callback = bindings.unary;
    const auto release = bindings.release;
    void* const context = bindings.release_context;
    OutputGuard output(release, context);
    ImageRef argument = source;
    const auto returned = callback(&output.value, &argument);
    if (argument.image != source.image) fail("candidate_input_ref_changed");
    validate_output(output, returned, source);
    return OwnedImage(output.take(), release, context);
}

OwnedImage invoke_binary(const OperationSpec& operation, const SyntheticBindings& bindings,
                         ImageRef source, ImageRef rhs) {
    validate_spec(operation, Signature::Binary);
    validate_bindings(bindings, Signature::Binary);
    if (!source.image) fail("candidate_null_source");
    if (!rhs.image) fail("candidate_null_rhs");
    const auto callback = bindings.binary;
    const auto release = bindings.release;
    void* const context = bindings.release_context;
    OutputGuard output(release, context);
    ImageRef argument = source, rhs_argument = rhs;
    const auto returned = callback(&output.value, &argument, &rhs_argument);
    if (argument.image != source.image || rhs_argument.image != rhs.image)
        fail("candidate_input_ref_changed");
    validate_output(output, returned, source, rhs);
    return OwnedImage(output.take(), release, context);
}

double invoke_reduction(const OperationSpec& operation, const SyntheticBindings& bindings,
                        ImageRef source) {
    validate_spec(operation, Signature::Reduction);
    validate_bindings(bindings, Signature::Reduction);
    if (!source.image) fail("candidate_null_source");
    ImageRef argument = source;
    const double value = bindings.reduction(&argument);
    if (argument.image != source.image) fail("candidate_input_ref_changed");
    if (!std::isfinite(value)) fail("candidate_nonfinite_reduction");
    return value;
}

} // namespace nb::candidate
