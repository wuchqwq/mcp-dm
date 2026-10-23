#pragma once
#include <array>
#include <cstdint>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>

// Safe, file/loader-metadata-only selection. No vendor ABI object is constructed
// and no vendor function is invoked by this layer.
namespace nb {
enum class Compatibility { Supported, UnsupportedBuild, AbiMismatch, NotReady };
inline const char* compatibility_name(Compatibility value) {
    switch (value) {
    case Compatibility::Supported: return "SUPPORTED";
    case Compatibility::UnsupportedBuild: return "UNSUPPORTED_BUILD";
    case Compatibility::AbiMismatch: return "ABI_MISMATCH";
    case Compatibility::NotReady: return "NOT_READY";
    }
    return "NOT_READY";
}
struct HostVersion {
    std::array<std::uint16_t, 4> components{};
    bool operator==(const HostVersion& other) const { return components == other.components; }
    bool operator!=(const HostVersion& other) const { return !(*this == other); }
    std::string str() const {
        return std::to_string(components[0]) + "." + std::to_string(components[1]) + "." +
            std::to_string(components[2]) + "." + std::to_string(components[3]);
    }
};
struct ModuleRequirement {
    const char* name;
    const char* sha256;
    bool check_version;
};
struct SymbolRequirement {
    const char* module;
    const char* name;
};
struct CapabilityProfile {
    const char* name;
    bool qualified;
    const char* scope;
    std::vector<SymbolRequirement> symbols;
    // These are validated executable entries, never scanned/guessed addresses.
    std::vector<const char*> entry_contracts;
};
struct EntryRequirement {
    const char* key;
    const char* module;
    std::uint32_t rva;
};
struct AdapterProfile {
    const char* id;
    HostVersion version;
    const char* architecture;
    std::vector<ModuleRequirement> modules;
    std::vector<SymbolRequirement> core_symbols;
    std::vector<CapabilityProfile> capabilities;
    std::vector<EntryRequirement> entries;
};
struct ModuleObservation {
    std::string name;
    bool loaded = false, readable = false;
    HostVersion version;
    std::string architecture, sha256;
    std::set<std::string> symbols;
};
struct HostObservation {
    bool recognized_gms = false, version_readable = false;
    HostVersion version;
    std::string architecture;
    std::vector<ModuleObservation> modules;
    std::set<std::string> valid_entry_contracts;
};
struct CapabilityAvailability {
    std::string name, scope, reason;
    bool available = false;
};
struct AdapterSelection {
    Compatibility compatibility = Compatibility::NotReady;
    const AdapterProfile* profile = nullptr;
    std::string reason = "host_identity_unavailable";
    std::vector<CapabilityAvailability> capabilities;
    bool safe() const { return compatibility == Compatibility::Supported && profile; }
    bool available(const std::string& name) const {
        if (!safe()) return false;
        for (const auto& capability : capabilities)
            if (capability.name == name) return capability.available;
        return false;
    }
};
inline const ModuleObservation* observed_module(const HostObservation& host, const std::string& name) {
    const ModuleObservation* match = nullptr;
    for (const auto& module : host.modules) if (module.name == name) {
        if (match) return nullptr; // Ambiguous inventories cannot qualify.
        match = &module;
    }
    return match;
}
inline bool symbol_present(const HostObservation& host, const SymbolRequirement& symbol) {
    const auto* module = observed_module(host, symbol.module);
    return module && module->loaded && module->readable && module->symbols.count(symbol.name);
}
inline AdapterSelection select_adapter(const HostObservation& host,
                                      const std::vector<const AdapterProfile*>& profiles) {
    AdapterSelection selected;
    if (!host.recognized_gms || !host.version_readable || host.architecture.empty()) return selected;
    for (const auto* profile : profiles) {
        if (!profile || profile->version != host.version || host.architecture != profile->architecture) continue;
        if (selected.profile) {
            selected.compatibility = Compatibility::AbiMismatch;
            selected.reason = "ambiguous_adapter_profile";
            return selected;
        }
        selected.profile = profile;
    }
    if (!selected.profile) {
        selected.compatibility = Compatibility::UnsupportedBuild;
        selected.reason = "no_qualified_adapter_for_build_and_architecture";
        return selected;
    }
    for (const auto& required : selected.profile->modules) {
        const auto* module = observed_module(host, required.name);
        if (!module || !module->loaded || !module->readable) {
            selected.reason = std::string("required_module_not_ready:") + required.name;
            return selected;
        }
        if (module->architecture != selected.profile->architecture ||
            module->sha256 != required.sha256 ||
            (required.check_version && module->version != selected.profile->version)) {
            selected.compatibility = Compatibility::AbiMismatch;
            selected.reason = std::string("required_module_identity_mismatch:") + required.name;
            return selected;
        }
    }
    for (const auto& required : selected.profile->core_symbols) if (!symbol_present(host, required)) {
        selected.compatibility = Compatibility::AbiMismatch;
        selected.reason = std::string("required_symbol_missing:") + required.name;
        return selected;
    }
    selected.compatibility = Compatibility::Supported;
    selected.reason = "exact_verified_profile_match";
    for (const auto& spec : selected.profile->capabilities) {
        CapabilityAvailability capability{spec.name, spec.scope, "NOT_QUALIFIED", false};
        if (spec.qualified) {
            capability.available = true;
            capability.reason = "qualified_adapter_implementation";
            for (const auto& symbol : spec.symbols) if (!symbol_present(host, symbol)) {
                capability.available = false;
                capability.reason = std::string("optional_symbol_missing:") + symbol.name;
                break;
            }
            for (const auto* entry : spec.entry_contracts) if (!host.valid_entry_contracts.count(entry)) {
                capability.available = false;
                capability.reason = std::string("optional_entry_contract_mismatch:") + entry;
                break;
            }
        }
        selected.capabilities.push_back(std::move(capability));
    }
    return selected;
}
inline void require_selected_adapter(const AdapterSelection& selection) {
    if (!selection.safe()) throw std::runtime_error(std::string("native_adapter_") +
        compatibility_name(selection.compatibility) + ":" + selection.reason);
}
} // namespace nb
