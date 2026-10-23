// Offline POD/reference-ownership tests. No scientific kernel or vendor code.
#include "candidate_calls.hpp"
#include <cmath>
#include <cstdint>
#include <iostream>
#include <limits>
#include <set>
#include <stdexcept>
#include <string>
#include <utility>

namespace c = nb::candidate;
namespace {
unsigned checks = 0;
void check(bool value) {
    ++checks;
    if (!value) throw std::runtime_error("candidate test assertion failed");
}
template<class F> void rejects(const char* expected, F action) {
    try { action(); }
    catch (const std::runtime_error& error) {
        check(std::string(error.what()) == expected);
        return;
    }
    throw std::runtime_error("expected candidate rejection");
}
const c::OperationSpec& op(const char* key) {
    const auto* found = c::find_operation(key);
    check(found != nullptr);
    return *found;
}
struct Image { int refs = 0; };
enum class Mode { Good, Empty, NullSret, ForeignSret, AliasSource, AliasRhs,
                  ThrowBefore, ThrowAfter, ChangeSource, ChangeRhs };
struct Harness {
    Image source{10}, rhs{20}, output{}, second{}, other{};
    Mode mode = Mode::Good;
    unsigned calls = 0, releases = 0;
    double scalar = -2.75;
    c::ImageRef src() { return {&source}; }
    c::ImageRef right() { return {&rhs}; }
    void inputs_intact() { check(source.refs == 10); check(rhs.refs == 20); }
};
Harness* active = nullptr;
void release(void* context, c::ImageRef owned) noexcept {
    auto& h = *static_cast<Harness*>(context);
    ++h.releases;
    --static_cast<Image*>(owned.image)->refs;
}
c::ImageRef* make_output(c::ImageRef* out, const c::ImageRef* source,
                         const c::ImageRef* rhs = nullptr) {
    auto& h = *active;
    ++h.calls;
    check(source->image == &h.source);
    if (rhs) check(rhs->image == &h.rhs);
    if (h.mode == Mode::ThrowBefore) throw std::runtime_error("synthetic_failure");
    if (h.mode == Mode::Empty) return out;
    auto* created = h.mode == Mode::AliasSource ? &h.source :
        h.mode == Mode::AliasRhs ? &h.rhs : &h.output;
    ++created->refs; // Even an aliased output contributes one NEW owned ref.
    out->image = created;
    if (h.mode == Mode::ThrowAfter) throw std::runtime_error("synthetic_failure");
    if (h.mode == Mode::ChangeSource)
        const_cast<c::ImageRef*>(source)->image = &h.other;
    if (h.mode == Mode::ChangeRhs && rhs)
        const_cast<c::ImageRef*>(rhs)->image = &h.other;
    if (h.mode == Mode::NullSret) return nullptr;
    if (h.mode == Mode::ForeignSret)
        return reinterpret_cast<c::ImageRef*>(static_cast<std::uintptr_t>(1));
    return out;
}
c::ImageRef* unary(c::ImageRef* out, const c::ImageRef* source) {
    return make_output(out, source);
}
c::ImageRef* binary(c::ImageRef* out, const c::ImageRef* source, const c::ImageRef* rhs) {
    return make_output(out, source, rhs);
}
double reduction(const c::ImageRef* source) {
    auto& h = *active;
    ++h.calls;
    check(source->image == &h.source);
    if (h.mode == Mode::ThrowBefore) throw std::runtime_error("synthetic_failure");
    if (h.mode == Mode::ChangeSource)
        const_cast<c::ImageRef*>(source)->image = &h.other;
    return h.scalar;
}
c::SyntheticBindings image_binding(Harness& h, bool pair = false) {
    c::SyntheticBindings result;
    if (pair) result.binary = binary;
    else result.unary = unary;
    result.release = release;
    result.release_context = &h;
    return result;
}
c::SyntheticBindings scalar_binding() {
    c::SyntheticBindings result;
    result.reduction = reduction;
    return result;
}
void catalog_contract() {
    std::size_t count = 0;
    const auto* all = c::catalog(count);
    check(all && count == 40);
    std::set<std::string> keys, symbols;
    unsigned blocked = 0;
    for (std::size_t i = 0; i < count; ++i) {
        const auto& spec = all[i];
        check(keys.emplace(spec.key).second);
        check(c::find_operation(spec.key) == &spec);
        check(spec.qualification == c::Qualification::NotQualified);
        check(!spec.evidence.empty());
        if (spec.signature == c::Signature::Blocked) {
            ++blocked;
            check(!spec.synthetic_callable);
        } else {
            check(spec.synthetic_callable);
            check(symbols.emplace(spec.exact_symbol).second);
            check(spec.exact_symbol.find("GMSImageProcessing@@") != std::string_view::npos);
        }
    }
    check(blocked == 6);
    for (const char* key : {"pixel_count", "mean_and_variance", "minimum_maximum",
                            "geometry", "save", "preview"}) {
        const auto& spec = op(key);
        check(spec.signature == c::Signature::Blocked && !spec.synthetic_callable);
    }
    check(c::find_operation("not_a_dm_operator") == nullptr);
    const std::pair<const char*, const char*> named[] = {
        {"abs", "Abs"}, {"negate", "Negate"}, {"square", "Square"},
        {"sqrt", "Sqrt"}, {"log", "Log"}, {"log10", "Log10"}, {"exp", "Exp"},
        {"real", "Real"}, {"imag", "Imag"}, {"arg", "Arg"}, {"conj", "Conj"},
        {"norm", "Norm"}, {"smooth", "SmoothFilter"}, {"sobel", "SobelFilter"},
        {"laplace", "LaplaceFilter"}, {"sharpen", "SharpenFilter"},
        {"fft", "FFT"}, {"real_fft", "Real_FFT"}, {"packed_fft", "Packed_FFT"},
        {"ifft", "IFFT"}, {"real_ifft", "Real_IFFT"}, {"packed_ifft", "Packed_IFFT"}
    };
    for (const auto& entry : named) {
        const auto& spec = op(entry.first);
        check(spec.signature == c::Signature::Unary);
        check(spec.exact_symbol == std::string("?") + entry.second +
            "@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z");
    }
    const std::pair<const char*, const char*> arithmetic[] = {
        {"add", "??H"}, {"subtract", "??G"}, {"multiply", "??D"}, {"divide", "??K"}
    };
    for (const auto& entry : arithmetic) {
        const auto& spec = op(entry.first);
        check(spec.signature == c::Signature::Binary);
        check(spec.exact_symbol == std::string(entry.second) +
            "GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV12@0@Z");
    }
    check(op("phase_cross_correlation").signature == c::Signature::Binary);
    check(c::find_operation("cross_correlation") == nullptr);
    const std::pair<const char*, const char*> scalars[] = {
        {"mean", "GetMean"}, {"sum", "GetSum"}, {"minimum", "GetMinimum"},
        {"maximum", "GetMaximum"}, {"variance", "GetVariance"},
        {"stddev", "GetStdDev"}, {"median", "GetMedian"}
    };
    for (const auto& entry : scalars) {
        const auto& spec = op(entry.first);
        check(spec.signature == c::Signature::Reduction);
        check(spec.exact_symbol == std::string("?") + entry.second +
            "@GMSImageProcessing@@YANAEBV?$ref_ptr@VImage@GMS@@@Gatan@@@Z");
    }
}
void preflight() {
    Harness h;
    active = &h;
    auto u = image_binding(h);
    const auto& spec = op("abs");
    const auto copy = spec;
    rejects("candidate_operation_not_catalogued", [&] { c::invoke_unary(copy, u, h.src()); });
    rejects("candidate_signature_mismatch", [&] { c::invoke_binary(spec, u, h.src(), h.right()); });
    auto missing = u;
    missing.unary = nullptr;
    rejects("candidate_missing_binding", [&] { c::invoke_unary(spec, missing, h.src()); });
    missing = u;
    missing.release = nullptr;
    rejects("candidate_missing_release", [&] { c::invoke_unary(spec, missing, h.src()); });
    auto mixed = u;
    mixed.binary = binary;
    rejects("candidate_binding_shape_mismatch", [&] { c::invoke_unary(spec, mixed, h.src()); });
    rejects("candidate_null_source", [&] { c::invoke_unary(spec, u, {nullptr}); });
    auto b = image_binding(h, true);
    rejects("candidate_null_rhs", [&] { c::invoke_binary(op("add"), b, h.src(), {nullptr}); });
    auto s = scalar_binding();
    rejects("candidate_null_source", [&] { c::invoke_reduction(op("mean"), s, {nullptr}); });
    std::size_t count = 0;
    const auto* all = c::catalog(count);
    for (std::size_t i = 0; i < count; ++i)
        if (all[i].signature == c::Signature::Blocked)
            rejects("candidate_operation_blocked", [&] { c::invoke_unary(all[i], u, h.src()); });
    check(h.calls == 0 && h.releases == 0);
    h.inputs_intact();
}
void ownership_and_failures() {
    for (bool pair : {false, true}) {
        Harness h;
        active = &h;
        const auto binding = image_binding(h, pair);
        auto invoke = [&]() {
            return pair ? c::invoke_binary(op("add"), binding, h.src(), h.right()) :
                c::invoke_unary(op("abs"), binding, h.src());
        };
        {
            auto output = invoke();
            check(output && output.get().image == &h.output && h.output.refs == 1);
            auto moved = std::move(output);
            check(!output && moved);
            c::OwnedImage assigned;
            assigned = std::move(moved);
            check(!moved && assigned);
            assigned.reset();
            assigned.reset();
            check(h.output.refs == 0 && h.releases == 1);
        }
        const std::pair<Mode, const char*> modes[] = {
            {Mode::Empty, "candidate_output_null"},
            {Mode::NullSret, "candidate_sret_mismatch"},
            {Mode::ForeignSret, "candidate_sret_mismatch"},
            {Mode::AliasSource, "candidate_output_alias"},
            {Mode::ThrowBefore, "synthetic_failure"},
            {Mode::ThrowAfter, "synthetic_failure"},
            {Mode::ChangeSource, "candidate_input_ref_changed"}
        };
        for (const auto& entry : modes) {
            h.mode = entry.first;
            const auto before = h.releases;
            rejects(entry.second, [&] { invoke(); });
            const bool wrote = entry.first != Mode::Empty && entry.first != Mode::ThrowBefore;
            check(h.releases == before + (wrote ? 1u : 0u));
            check(h.output.refs == 0);
            h.inputs_intact();
        }
        if (pair) {
            h.mode = Mode::AliasRhs;
            rejects("candidate_output_alias", [&] { invoke(); });
            h.inputs_intact();
            h.mode = Mode::ChangeRhs;
            rejects("candidate_input_ref_changed", [&] { invoke(); });
            h.inputs_intact();
        }
        h.mode = Mode::Good;
        {
            auto first = invoke();
            auto second = invoke();
            const auto before = h.releases;
            first = std::move(second); // Dispose previous ownership, preserve incoming one.
            check(!second && first && h.output.refs == 1);
            check(h.releases == before + 1);
        }
        check(h.output.refs == 0);
        h.inputs_intact();
    }
}
void reductions() {
    Harness h;
    active = &h;
    const auto binding = scalar_binding();
    for (double value : {-2.75, 0.0, 1.125}) {
        h.scalar = value;
        check(c::invoke_reduction(op("mean"), binding, h.src()) == value);
    }
    for (double value : {std::numeric_limits<double>::infinity(),
                         -std::numeric_limits<double>::infinity(),
                         std::numeric_limits<double>::quiet_NaN()}) {
        h.scalar = value;
        rejects("candidate_nonfinite_reduction", [&] { c::invoke_reduction(op("mean"), binding, h.src()); });
    }
    h.mode = Mode::ChangeSource;
    rejects("candidate_input_ref_changed", [&] { c::invoke_reduction(op("mean"), binding, h.src()); });
    h.mode = Mode::ThrowBefore;
    rejects("synthetic_failure", [&] { c::invoke_reduction(op("mean"), binding, h.src()); });
    check(h.releases == 0);
    h.inputs_intact();
}
void every_candidate_uses_its_declared_shape() {
    std::size_t count = 0;
    const auto* all = c::catalog(count);
    for (std::size_t i = 0; i < count; ++i) {
        const auto& spec = all[i];
        if (!spec.synthetic_callable) continue;
        Harness h;
        active = &h;
        if (spec.signature == c::Signature::Reduction) {
            check(c::invoke_reduction(spec, scalar_binding(), h.src()) == h.scalar);
            check(h.releases == 0);
        } else {
            {
                const bool pair = spec.signature == c::Signature::Binary;
                const auto binding = image_binding(h, pair);
                auto image = pair ? c::invoke_binary(spec, binding, h.src(), h.right()) :
                    c::invoke_unary(spec, binding, h.src());
                check(image.get().image == &h.output && h.output.refs == 1);
            }
            check(h.output.refs == 0 && h.releases == 1);
        }
        check(h.calls == 1);
        h.inputs_intact();
    }
}
void move_preserves_release_context() {
    Harness first, second;
    active = &first;
    auto binding = image_binding(first);
    auto a = c::invoke_unary(op("abs"), binding, first.src());
    // Later edits to a caller's binding must not change existing ownership.
    binding.release_context = &second;
    active = &second;
    auto b = c::invoke_unary(op("square"), image_binding(second), second.src());
    a = std::move(b);
    check(first.output.refs == 0 && first.releases == 1);
    check(second.output.refs == 1 && second.releases == 0);
    auto* same = &a;
    a = std::move(*same);
    check(a && second.output.refs == 1 && second.releases == 0);
    a.reset();
    check(second.output.refs == 0 && second.releases == 1);
    first.inputs_intact();
    second.inputs_intact();
}
} // namespace
int main() {
    try {
        catalog_contract();
        preflight();
        ownership_and_failures();
        reductions();
        every_candidate_uses_its_declared_shape();
        move_preserves_release_context();
        std::size_t count = 0, callable = 0;
        const auto* all = c::catalog(count);
        for (std::size_t i = 0; i < count; ++i) if (all[i].synthetic_callable) ++callable;
        std::cout << "PASS: " << checks << " offline candidate call assertions; synthetic callbacks only\n";
        std::cout << "Catalog: " << callable << " synthetic-callable, "
                  << count - callable << " blocked; all NOT_QUALIFIED for DM\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "FAIL: " << error.what() << '\n';
        return 1;
    }
}
