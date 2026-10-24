#include "adapter_profile.hpp"
#include "adapter_identity_win.hpp"
#include "adapters/gms_3_53_4137/profile.hpp"
#include <iostream>
#include <stdexcept>

namespace {
int checks = 0, vendor_calls = 0;
void check(bool pass) {
    ++checks;
    if (!pass) throw std::runtime_error("adapter-profile assertion " + std::to_string(checks));
}
nb::HostObservation valid_host() {
    const auto& profile = nb::gms353::profile();
    nb::HostObservation host;
    host.recognized_gms = host.version_readable = true;
    host.version = profile.version;
    host.architecture = "x64";
    for (const auto& required : profile.modules) {
        nb::ModuleObservation module;
        module.name = required.name;
        module.loaded = module.readable = true;
        module.version = profile.version;
        module.architecture = "x64";
        module.sha256 = required.sha256;
        host.modules.push_back(module);
    }
    for (auto& module : host.modules) {
        for (const auto& symbol : profile.core_symbols)
            if (module.name == symbol.module) module.symbols.insert(symbol.name);
        for (const auto& capability : profile.capabilities) {
            for (const auto& symbol : capability.symbols)
                if (module.name == symbol.module) module.symbols.insert(symbol.name);
            for (const auto* entry : capability.entry_contracts) host.valid_entry_contracts.insert(entry);
        }
    }
    return host;
}
nb::AdapterSelection select(const nb::HostObservation& host) {
    return nb::select_adapter(host, {&nb::gms353::profile()});
}
// Same admission predicate as the production dispatcher: a failed selection
// must never enter an implementation, regardless of available symbol addresses.
void attempt(const nb::AdapterSelection& selected, const std::string& capability) {
    try { nb::require_selected_adapter(selected); }
    catch (const std::runtime_error&) { return; }
    if (selected.available(capability)) ++vendor_calls;
}
void rejected(const nb::HostObservation& host, nb::Compatibility expected) {
    const auto selected = select(host);
    check(selected.compatibility == expected && !selected.safe());
    for (const auto& capability : nb::gms353::profile().capabilities) attempt(selected, capability.name);
    check(vendor_calls == 0);
}
}
int main() {
    try {
        const auto good = valid_host();
        auto selected = select(good);
        check(selected.safe() && selected.profile == &nb::gms353::profile());
        check(selected.available("native_statistics") && selected.available("native_crop"));
        check(selected.available("native_display") && selected.available("native_datasets"));
        for (const auto* name : {"native_mean", "native_statistics", "native_crop", "native_display", "native_datasets",
                                 "native_image_arithmetic", "native_fft", "native_filters", "native_preview", "native_read",
                                 "native_uint32_mean", "native_uint32_statistics", "native_uint32_crop", "native_uint32_preview", "native_uint32_read"})
            check(selected.available(name));
        for (const auto* name : {"native_save", "invented"}) {
            check(!selected.available(name)); attempt(selected, name); check(vendor_calls == 0);
        }
        // Complete addresses cannot qualify a deliberately unqualified group.
        for (const auto* name : {"native_image_arithmetic", "native_fft", "native_filters", "native_preview", "native_read",
                                 "native_uint32_mean", "native_uint32_statistics", "native_uint32_crop", "native_uint32_preview", "native_uint32_read"}) {
            auto unqualified = nb::gms353::profile();
            for (auto& capability : unqualified.capabilities)
                if (std::string(capability.name) == name) capability.qualified = false;
            const auto blocked = nb::select_adapter(good, {&unqualified});
            check(blocked.safe() && !blocked.available(name));
            check(blocked.available("native_datasets") && blocked.available("native_statistics"));
            attempt(blocked, name); check(vendor_calls == 0);
        }
        for (std::size_t i = 0; i < good.modules.size(); ++i) {
            auto bad = good; bad.modules[i].sha256[0] ^= 1;
            rejected(bad, nb::Compatibility::AbiMismatch);
            bad = good; bad.modules[i].loaded = false;
            rejected(bad, nb::Compatibility::NotReady);
            bad = good; bad.modules[i].readable = false;
            rejected(bad, nb::Compatibility::NotReady);
            bad = good; bad.modules[i].architecture = "arm64";
            rejected(bad, nb::Compatibility::AbiMismatch);
        }
        for (std::size_t component = 0; component < 4; ++component) {
            auto bad = good; ++bad.version.components[component];
            rejected(bad, nb::Compatibility::UnsupportedBuild);
        }
        for (const auto* architecture : {"x86", "arm64", "unknown"}) {
            auto bad = good; bad.architecture = architecture;
            rejected(bad, nb::Compatibility::UnsupportedBuild);
        }
        auto bad = good; bad.architecture.clear(); rejected(bad, nb::Compatibility::NotReady);
        bad = good; bad.recognized_gms = false; rejected(bad, nb::Compatibility::NotReady);
        bad = good; bad.version_readable = false; rejected(bad, nb::Compatibility::NotReady);
        bad = good; bad.modules.clear(); rejected(bad, nb::Compatibility::NotReady);
        bad = good; bad.modules.push_back(good.modules[0]); rejected(bad, nb::Compatibility::NotReady);
        for (const auto& required : nb::gms353::profile().core_symbols) {
            bad = good;
            for (auto& module : bad.modules) if (module.name == required.module) module.symbols.erase(required.name);
            rejected(bad, nb::Compatibility::AbiMismatch);
        }
        // An optional operation failing resolution disables only that capability.
        for (const auto& spec : nb::gms353::profile().capabilities) {
            for (const auto& symbol : spec.symbols) {
                bad = good;
                for (auto& module : bad.modules) if (module.name == symbol.module) module.symbols.erase(symbol.name);
                selected = select(bad);
                check(selected.safe() && !selected.available(spec.name));
                check(selected.available("native_datasets"));
                // Shared dependencies may disable several groups; every
                // independently bound qualified group stays available.
                for (const auto& other : nb::gms353::profile().capabilities) {
                    bool shares = false;
                    for (const auto& dependency : other.symbols)
                        if (std::string(dependency.module) == symbol.module &&
                            std::string(dependency.name) == symbol.name) shares = true;
                    if (other.qualified && !shares) check(selected.available(other.name));
                }
                attempt(selected, spec.name); check(vendor_calls == 0);
            }
            for (const auto* entry : spec.entry_contracts) {
                bad = good; bad.valid_entry_contracts.erase(entry);
                selected = select(bad);
                check(selected.safe() && !selected.available(spec.name));
                check(selected.available("native_statistics") && selected.available("native_crop"));
                attempt(selected, spec.name); check(vendor_calls == 0);
            }
        }
        auto ambiguous = nb::select_adapter(good, {&nb::gms353::profile(), &nb::gms353::profile()});
        check(ambiguous.compatibility == nb::Compatibility::AbiMismatch && !ambiguous.safe());
        check(!nb::select_adapter(good, {}).safe());
        selected = select(good);
        int expected_calls = 0;
        for (const auto& spec : nb::gms353::profile().capabilities) if (spec.qualified) {
            attempt(selected, spec.name); check(vendor_calls == ++expected_calls);
        }
        // The real Windows observation code must not mistake this test EXE for
        // GMS or load any vendor module to try to make a profile match.
        const auto self = nb::identity::observe({&nb::gms353::profile()});
        check(!self.recognized_gms && self.modules.empty());
        check(select(self).compatibility == nb::Compatibility::NotReady);
        check(nb::identity::architecture(nb::identity::path(GetModuleHandleW(nullptr))) == "x64");
        std::cout << "adapter profile offline checks PASS " << checks << " (synthetic identities only)\n";
        return 0;
    } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
