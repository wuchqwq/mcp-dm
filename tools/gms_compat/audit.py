"""Offline conformance audit: one manifest against the recorded ABI evidence.

``compare`` answers "what changed between two builds". ``audit`` answers a
different and narrower question: "for this build, which recorded ABI bindings
are present, which are absent, and which can never be checked without loading
the module".

It is deliberately *not* an admission decision. The runtime gate additionally
requires a capability's own qualification flag and, for non-exported
contracts, a validated executable entry in a page-mapped section. Those checks
need the loaded host, so this report keeps ``qualification.state: REFUSED``.
"""
import manifest as manifest_model

SCHEMA_NAME = "mcp-dm/gms-compat/audit"
SCHEMA_VERSION = 1

_LIMITATIONS = [
    "Presence of an export name does not prove its call shape, layout or ownership.",
    "A matching module hash is identity, not a new qualification.",
    "Non-exported contracts cannot be verified from a file; the recorded RVA is "
    "specific to the pinned build and must be re-derived.",
    "This tool never loads, resolves or executes anything, so it cannot observe "
    "entry-page validity, callback readiness or host behaviour.",
    "Admission also requires the version profile's own capability flags, which "
    "this report does not read or modify.",
    "Capability coverage is the union of the evidence entries that declare the "
    "operation. It is not the version profile's per-capability symbol list, so a "
    "capability may additionally require symbols the inventory does not attribute "
    "to it.",
]

NO_EVIDENCE = "NO_EVIDENCE"
SYMBOL_MISSING = "SYMBOL_MISSING"
REFUSED_BY_EVIDENCE = "REFUSED_BY_EVIDENCE"
EVIDENCE_INCOMPLETE = "EVIDENCE_INCOMPLETE"
CONTRACT_UNVERIFIABLE = "CONTRACT_UNVERIFIABLE"
EVIDENCE_COMPLETE = "EVIDENCE_COMPLETE"


def _module_lookup(manifest):
    return manifest_model.module_index(manifest)


def _export_names(module):
    return set(entry["name"] for entry in (module or {}).get("exports") or []
               if entry.get("name"))


def _ordinals(module):
    return set(entry["ordinal"] for entry in (module or {}).get("exports") or [])


def _binding_state(symbol, modules):
    """Return (present, reason) for one evidence symbol against the manifest."""
    module = modules.get(symbol["module"].lower())
    if module is None:
        return (False, "module_absent")
    if symbol["kind"] == "export":
        return (symbol["name"] in _export_names(module), "export_absent")
    if symbol["kind"] == "export_ordinal":
        return (symbol["ordinal"] in _ordinals(module), "ordinal_absent")
    if symbol["kind"] == "export_name_unverified":
        return (None, "plain_name_not_bindable")
    return (None, "non_export_contract")


def _capability_index(evidence):
    """operation -> ordered list of evidence entries that reference it."""
    index = {}
    for entry in evidence.entries:
        for operation in entry.get("scope", {}).get("operations") or []:
            index.setdefault(operation, []).append(entry)
    return index


def audit(manifest, evidence):
    modules = _module_lookup(manifest)
    build = evidence.build
    pinned = dict((module["name"].lower(), module) for module in build["modules"])

    report_modules = []
    missing_total = 0
    required_total = 0
    present_total = 0
    unverifiable_total = 0
    seen = set()
    for key in sorted(set(pinned) | set(modules)):
        pinned_module = pinned.get(key)
        actual = modules.get(key)
        name = (pinned_module or {}).get("name") or actual["name"]
        required = []
        missing = []
        contracts = []
        seen_bindings = set()
        for entry in evidence.entries:
            for symbol in entry["symbols"]:
                if symbol["module"].lower() != key:
                    continue
                if symbol["kind"] == "rva":
                    contracts.append(symbol["entry_contract"])
                    continue
                binding_key = (symbol["kind"], symbol.get("name"), symbol.get("ordinal"))
                if binding_key in seen_bindings:
                    continue
                seen_bindings.add(binding_key)
                item = {"entry": entry["id"], "kind": symbol["kind"],
                        "name": symbol.get("name"), "ordinal": symbol.get("ordinal")}
                required.append(item)
                present, reason = _binding_state(symbol, modules)
                if present is False:
                    item = dict(item)
                    item["reason"] = reason
                    missing.append(item)
        required_total += len(required)
        missing_total += len(missing)
        present_total += len(required) - len(missing)
        unverifiable_total += len(contracts)
        seen.add(key)
        architecture_match = None
        version_match = None
        hash_match = None
        if actual is not None and pinned_module is not None:
            hash_match = actual["sha256"] == pinned_module["sha256"]
            architecture_match = actual["architecture"] == build["architecture"]
            if pinned_module.get("check_version"):
                version_match = (actual.get("version") or {}).get("file_version") == \
                    build["version"]
        report_modules.append({
            "name": name,
            "present": actual is not None,
            "pinned": pinned_module is not None,
            "pinned_sha256_match": hash_match,
            "architecture_match": architecture_match,
            "version_match": version_match,
            "export_count": len((actual or {}).get("exports") or []),
            "required_exports": len(required),
            "missing_exports": _sorted(missing, lambda item: item["name"] or ""),
            "non_export_contracts": sorted(set(contracts)),
        })

    capabilities = []
    index = _capability_index(evidence)
    for operation in sorted(index):
        entries = index[operation]
        missing_symbols = []
        contracts = []
        entries_incomplete = []
        for entry in entries:
            if entry["qualification"] != "QUALIFIED_LIMITED":
                entries_incomplete.append(entry["id"])
            for symbol in entry["symbols"]:
                if symbol["kind"] == "rva":
                    contracts.append(symbol["entry_contract"])
                    continue
                present, _reason = _binding_state(symbol, modules)
                if present is False:
                    missing_symbols.append(symbol.get("name") or
                                           "#%s" % symbol.get("ordinal"))
        if missing_symbols:
            state = SYMBOL_MISSING
        elif all(entry["qualification"] == "BLOCKED" for entry in entries):
            state = REFUSED_BY_EVIDENCE
        elif entries_incomplete:
            state = EVIDENCE_INCOMPLETE
        elif contracts:
            state = CONTRACT_UNVERIFIABLE
        else:
            state = EVIDENCE_COMPLETE
        capabilities.append({
            "operation": operation,
            "state": state,
            "basis": "evidence_scope_union",
            "evidence_entries": sorted(entry["id"] for entry in entries),
            "export_bindings": len([symbol for entry in entries
                                    for symbol in entry["symbols"]
                                    if symbol["kind"] in ("export", "export_ordinal")]),
            "missing_symbols": sorted(set(missing_symbols)),
            "non_export_contracts": sorted(set(contracts)),
            "evidence_incomplete_entries": sorted(set(entries_incomplete)),
        })

    capability_states = {}
    for item in capabilities:
        capability_states[item["state"]] = capability_states.get(item["state"], 0) + 1

    return {
        "schema": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "tool": {"name": manifest_model.TOOL_NAME, "version": manifest_model.TOOL_VERSION},
        "reference": {
            "profile_id": build["profile_id"],
            "version": build["version"],
            "architecture": build["architecture"],
            "module_count": len(build["modules"]),
            "version_policy": build.get("version_policy"),
        },
        "inputs": {
            "manifest_generated_by": manifest.get("generated_by"),
            "modules_inspected": len(manifest["modules"]),
        },
        "summary": {
            "modules_present": len([item for item in report_modules if item["present"]]),
            "modules_missing": len([item for item in report_modules
                                    if not item["present"]]),
            "modules_hash_matched": len([item for item in report_modules
                                         if item["pinned_sha256_match"] is True]),
            "modules_hash_mismatched": len([item for item in report_modules
                                            if item["pinned_sha256_match"] is False]),
            "export_bindings_required": required_total,
            "export_bindings_present": present_total,
            "export_bindings_missing": missing_total,
            "non_export_contracts": unverifiable_total,
            "capability_states": capability_states,
        },
        "modules": report_modules,
        "capabilities": capabilities,
        "limitations": list(_LIMITATIONS),
        "qualification": {
            "state": "REFUSED",
            "may_authorize_calls": False,
            "reason": "an offline audit confirms presence, not call safety; admission "
                      "still requires the version profile's gates and real-host evidence",
        },
    }


def _sorted(items, key):
    return sorted(items, key=key)
