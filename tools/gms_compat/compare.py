"""Deterministic comparison of two module manifests.

Design rules encoded here:

* A shared export *name* is never ABI evidence. Neither is a shared RVA, a
  shared ordinal, or similar-looking code (which this tool does not read).
* The result never grants qualification. ``qualification.state`` is always
  ``REFUSED``; the field exists so a downstream agent cannot mistake a diff for
  an admission decision.
* Missing evidence is reported as missing, never filled in by inference.
"""
import manifest as manifest_model

SCHEMA_NAME = "mcp-dm/gms-compat/comparison"
SCHEMA_VERSION = 1

_LIMITATIONS = [
    "An identical export name does not establish an identical call shape.",
    "An identical RVA does not establish an identical function body.",
    "Similar machine code is not a qualification criterion and is not inspected here.",
    "This tool reads declared PE metadata only; it does not load, resolve or call "
    "the inspected modules.",
    "Only the exact pinned build has recorded qualification. Any other build is "
    "unqualified regardless of this diff.",
]


def _sorted(items, key):
    return sorted(items, key=key)


def _name_key(item):
    return (item.get("name") or "", item.get("ordinal") or 0)


def _export_view(entry):
    return {
        "name": entry.get("name"),
        "ordinal": entry.get("ordinal"),
        "rva": entry.get("rva"),
        "section": entry.get("section"),
        "executable": bool(entry.get("executable")),
        "forwarder": entry.get("forwarder"),
    }


def _identity(reference, candidate):
    def field(key, sub=None):
        if sub is None:
            return {"reference": reference.get(key), "candidate": candidate.get(key),
                    "equal": reference.get(key) == candidate.get(key)}
        return {"reference": (reference.get(key) or {}).get(sub),
                "candidate": (candidate.get(key) or {}).get(sub),
                "equal": (reference.get(key) or {}).get(sub) == (candidate.get(key) or {}).get(sub)}
    return {
        "sha256": field("sha256"),
        "architecture": field("architecture"),
        "file_version": field("version", "file_version"),
        "size_bytes": field("size_bytes"),
    }


def _compare_exports(reference_module, candidate_module):
    reference_exports = manifest_model.export_index(reference_module)
    candidate_exports = manifest_model.export_index(candidate_module)
    identical = []
    rva_changed = []
    forwarder_changed = []
    section_changed = []
    removed = []
    added = []
    for name in sorted(set(reference_exports) & set(candidate_exports)):
        left = reference_exports[name]
        right = candidate_exports[name]
        if left["rva"] != right["rva"]:
            rva_changed.append({
                "name": name,
                "reference_rva": left["rva"],
                "candidate_rva": right["rva"],
                "reference_section": left.get("section"),
                "candidate_section": right.get("section"),
            })
        elif left.get("forwarder") != right.get("forwarder"):
            forwarder_changed.append({
                "name": name,
                "reference_forwarder": left.get("forwarder"),
                "candidate_forwarder": right.get("forwarder"),
            })
        elif left.get("section") != right.get("section"):
            section_changed.append({
                "name": name,
                "reference_section": left.get("section"),
                "candidate_section": right.get("section"),
            })
        else:
            identical.append({
                "name": name,
                "ordinal": right["ordinal"],
                "rva": right["rva"],
                "section": right.get("section"),
            })
    for name in sorted(set(reference_exports) - set(candidate_exports)):
        removed.append(_export_view(reference_exports[name]))
    for name in sorted(set(candidate_exports) - set(reference_exports)):
        added.append(_export_view(candidate_exports[name]))
    return {
        "identical": identical,
        "rva_changed": _sorted(rva_changed, _name_key),
        "forwarder_changed": _sorted(forwarder_changed, _name_key),
        "section_changed": _sorted(section_changed, _name_key),
        "removed": _sorted(removed, _name_key),
        "added": _sorted(added, _name_key),
    }


def _rename_candidates(removed, added):
    """Pair a removed and an added export that share one exact RVA.

    The pair is a *lead for manual investigation only*. Nothing in the emitted
    record may be read as evidence that the two names implement the same ABI.
    """
    by_rva = {}
    for entry in added:
        by_rva.setdefault(entry["rva"], []).append(entry)
    pairs = []
    for entry in _sorted(removed, _name_key):
        matches = by_rva.get(entry["rva"]) or []
        if len(matches) != 1:
            continue
        partner = matches[0]
        if partner["forwarder"] or entry["forwarder"]:
            continue
        pairs.append({
            "removed_name": entry["name"],
            "added_name": partner["name"],
            "shared_rva": entry["rva"],
            "section": partner.get("section") or entry.get("section"),
            "confidence": "low",
            "establishes_equivalent_abi": False,
            "note": "same RVA only; the function body was not inspected",
        })
        by_rva.pop(entry["rva"], None)
    return _sorted(pairs, lambda item: item["removed_name"] or "")


def compare(reference, candidate, evidence=None, module_filter=None):
    """Return a comparison document. See module docstring for invariants."""
    reference_modules = manifest_model.module_index(reference)
    candidate_modules = manifest_model.module_index(candidate)
    names = set(reference_modules) | set(candidate_modules)
    if module_filter:
        allowed = set(name.lower() for name in module_filter)
        names &= allowed
    report_modules = []
    abi_unknown = []
    high_risk = []
    manual_review = []
    affected = {}
    totals = {
        "identical_modules": 0,
        "changed_modules": 0,
        "missing_modules": 0,
        "added_modules": 0,
        "exports_identical": 0,
        "exports_added": 0,
        "exports_removed": 0,
        "exports_rva_changed": 0,
        "rename_candidates": 0,
        "high_risk": 0,
        "manual_review": 0,
        "affected_operations": 0,
    }
    for key in sorted(names):
        left = reference_modules.get(key)
        right = candidate_modules.get(key)
        if left is None:
            totals["added_modules"] += 1
            report_modules.append({
                "name": right["name"],
                "status": "ADDED_IN_CANDIDATE",
                "identity": {"sha256": {"reference": None, "candidate": right["sha256"],
                                        "equal": False}},
                "exports": {"added": len(manifest_model.export_index(right)),
                            "removed": 0, "identical": 0, "rva_changed": 0},
                "assessment": [{
                    "severity": "HIGH",
                    "detail": "module is absent from the reference manifest; no pinned "
                              "evidence exists for it",
                }],
            })
            continue
        if right is None:
            totals["missing_modules"] += 1
            report_modules.append({
                "name": left["name"],
                "status": "MISSING_IN_CANDIDATE",
                "identity": {"sha256": {"reference": left["sha256"], "candidate": None,
                                        "equal": False}},
                "exports": {"added": 0, "removed": len(manifest_model.export_index(left)),
                            "identical": 0, "rva_changed": 0},
                "assessment": [{
                    "severity": "HIGH",
                    "detail": "reference module is missing from the candidate; every "
                              "capability depending on it is unavailable",
                }],
            })
            continue
        identity = _identity(left, right)
        exports = _compare_exports(left, right)
        renames = _rename_candidates(exports["removed"], exports["added"])
        identical_module = (identity["sha256"]["equal"] and identity["architecture"]["equal"]
                            and not exports["added"] and not exports["removed"]
                            and not exports["rva_changed"]
                            and not exports["forwarder_changed"]
                            and not exports["section_changed"])
        status = "IDENTICAL" if identical_module else "CHANGED"
        if status == "IDENTICAL":
            totals["identical_modules"] += 1
        else:
            totals["changed_modules"] += 1
        totals["exports_identical"] += len(exports["identical"])
        totals["exports_added"] += len(exports["added"])
        totals["exports_removed"] += len(exports["removed"])
        totals["exports_rva_changed"] += len(exports["rva_changed"])
        totals["rename_candidates"] += len(renames)
        assessment = []
        if not identity["sha256"]["equal"]:
            assessment.append({
                "severity": "HIGH",
                "detail": "module SHA-256 changed; every bound layout, call shape and "
                          "ownership rule for this module must be re-derived",
            })
        if not identity["architecture"]["equal"]:
            assessment.append({
                "severity": "CRITICAL",
                "detail": "module architecture changed; no existing call shape applies",
            })
        if identity["file_version"]["equal"] is False:
            assessment.append({
                "severity": "MEDIUM",
                "detail": "reported file version changed",
            })
        if exports["rva_changed"]:
            assessment.append({
                "severity": "HIGH",
                "detail": "%d export(s) kept their name but moved; a name match is not "
                          "ABI evidence" % len(exports["rva_changed"]),
            })
        if exports["forwarder_changed"]:
            assessment.append({
                "severity": "HIGH",
                "detail": "export forwarding changed; the effective implementation module "
                          "must be re-identified",
            })
        if renames:
            assessment.append({
                "severity": "MEDIUM",
                "detail": "%d rename candidate(s) found by shared RVA only; investigate "
                          "manually, do not map them automatically" % len(renames),
            })
        if status == "IDENTICAL":
            assessment.append({
                "severity": "INFO",
                "detail": "binary hash and named export surface match the reference; this "
                          "is identity, not a new qualification",
            })
        report_modules.append({
            "name": right["name"],
            "status": status,
            "identity": identity,
            "exports": {
                "reference_named": len(manifest_model.export_index(left)),
                "candidate_named": len(manifest_model.export_index(right)),
                "identical": len(exports["identical"]),
                "added": len(exports["added"]),
                "removed": len(exports["removed"]),
                "rva_changed": len(exports["rva_changed"]),
                "forwarder_changed": len(exports["forwarder_changed"]),
                "section_changed": len(exports["section_changed"]),
                "detail": exports,
                "rename_candidates": renames,
            },
            "assessment": assessment,
        })
        if not identity["sha256"]["equal"]:
            for entry in exports["identical"]:
                abi_unknown.append({
                    "module": right["name"],
                    "export": entry["name"],
                    "rva": entry["rva"],
                    "reason": "module binary changed; identical export name and RVA do not "
                              "prove an identical call shape or object layout",
                })
            for entry in exports["rva_changed"]:
                abi_unknown.append({
                    "module": right["name"],
                    "export": entry["name"],
                    "rva": entry["candidate_rva"],
                    "reason": "module binary changed and the export moved; the previous "
                              "call shape must not be reused",
                })
        for entry in exports["forwarder_changed"] + exports["section_changed"]:
            abi_unknown.append({
                "module": right["name"],
                "export": entry["name"],
                "rva": None,
                "reason": "export resolution or containing section changed",
            })
    result = {
        "schema": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "tool": {"name": manifest_model.TOOL_NAME, "version": manifest_model.TOOL_VERSION},
        "reference": {
            "generated_by": reference.get("generated_by"),
            "module_count": len(reference_modules),
        },
        "candidate": {
            "generated_by": candidate.get("generated_by"),
            "module_count": len(candidate_modules),
        },
        "summary": totals,
        "modules": report_modules,
        "abi_unknown": _sorted(abi_unknown, lambda item: (item["module"].lower(),
                                                          item["export"] or "")),
        "high_risk": [],
        "manual_review": [],
        "affected_operations": [],
        "limitations": list(_LIMITATIONS),
        "qualification": {
            "state": "REFUSED",
            "may_authorize_calls": False,
            "reason": "a manifest diff cannot qualify a build; qualification requires "
                      "recorded real-host acceptance for this exact build",
        },
    }
    if evidence is not None:
        _apply_evidence(result, evidence, reference, candidate)
    return result


def _apply_evidence(result, evidence, reference, candidate):
    """Attach capability impact and manual re-derivation requirements."""
    symbols = evidence.symbol_index()
    contract_entries = [entry for entry in evidence.entries
                        if any(symbol.get("kind") == "rva" for symbol in entry["symbols"])]
    high_risk = []
    manual = []
    affected = {}
    changed_modules = set()
    for module in result["modules"]:
        if module["status"] != "IDENTICAL":
            changed_modules.add(module["name"].lower())
        detail = module.get("exports", {}).get("detail") or {}
        names = []
        for bucket in ("rva_changed", "forwarder_changed", "section_changed"):
            names.extend(item["name"] for item in detail.get(bucket) or [])
        names.extend(item["name"] for item in detail.get("removed") or [])
        for name in sorted(set(names)):
            entry = symbols.get(name)
            if entry is None:
                high_risk.append({
                    "module": module["name"],
                    "symbol": name,
                    "evidence_entry": None,
                    "reason": "changed export has no recorded ABI evidence entry",
                    "action": "derive a new evidence entry before any binding",
                })
                continue
            high_risk.append({
                "module": module["name"],
                "symbol": name,
                "evidence_entry": entry["id"],
                "reason": "changed export is bound by recorded evidence for another build",
                "action": "re-derive call shape, layout and ownership; do not copy",
                "revalidation": entry.get("revalidation") or [],
            })
            for operation in entry.get("scope", {}).get("operations") or []:
                affected.setdefault(operation, set()).add(entry["id"])
    for entry in contract_entries:
        module_names = set(symbol["module"].lower() for symbol in entry["symbols"])
        if module_names & changed_modules:
            manual.append({
                "evidence_entry": entry["id"],
                "modules": sorted(module_names),
                "reason": "non-exported entry contract cannot be derived from the export "
                          "table; the pinned RVA does not transfer to another build",
                "action": "locate the entry manually on the candidate build and record new "
                          "static evidence before use",
            })
    for module in result["modules"]:
        if module["status"] == "MISSING_IN_CANDIDATE":
            for name in ("GMSImage.dll", "GMSImageProcessing.dll", "GMS.dll"):
                if module["name"].lower() != name.lower():
                    continue
                manual.append({
                    "evidence_entry": None,
                    "modules": [module["name"]],
                    "reason": "required module is missing; all dependent capabilities are "
                              "unavailable without further evidence",
                    "action": "restore the module or re-scope the adapter",
                })
    result["high_risk"] = _sorted(high_risk, lambda item: (item["module"].lower(),
                                                          item["symbol"] or ""))
    result["manual_review"] = _sorted(manual, lambda item: item["evidence_entry"] or "")
    result["affected_operations"] = [
        {"operation": operation, "evidence_entries": sorted(affected[operation]),
         "impact": "UNVERIFIED_ON_CANDIDATE_BUILD"}
        for operation in sorted(affected)
    ]
    result["summary"]["high_risk"] = len(result["high_risk"])
    result["summary"]["manual_review"] = len(result["manual_review"])
    result["summary"]["affected_operations"] = len(result["affected_operations"])
