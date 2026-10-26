"""ABI evidence inventory: validation, lookup and Markdown rendering.

The inventory is the reviewable artifact. Its validator is the guarantee that
the document and the data cannot drift and that no claim outruns its evidence:

* every cited file and heading anchor must exist in this repository;
* a ``QUALIFIED_LIMITED`` entry needs a recorded real-host result, not a static
  finding or a plausible function name;
* an entry that only has a name (``name_only``) or only a similarity argument
  (``similarity_only``) can never be qualified;
* object layouts may only be present when they carry their own source anchor;
* a non-exported entry point must not duplicate a vendor RVA; the address stays
  in the version profile, which is exactly what must be re-derived per build.
"""
import io
import json
import os
import re

SCHEMA_NAME = "mcp-dm/gms-compat/abi-evidence"
SCHEMA_VERSION = 1

QUALIFICATIONS = (
    # Bounded real-host acceptance was recorded for this exact pinned build.
    "QUALIFIED_LIMITED",
    # Static/offline evidence only. Nothing has executed in a host.
    "STATIC_CANDIDATE",
    # Evidence is insufficient or contradicting; do not bind.
    "UNRESOLVED",
    # Deliberately refused: wrong signature, policy boundary, or superseded.
    "BLOCKED",
)

DERIVATIONS = ("documented", "static_inspection", "similarity_only", "name_only")

_REQUIRED_ENTRY_KEYS = (
    "id", "title", "area", "build_profile", "modules", "symbols", "call_shape",
    "layout", "static_evidence", "verification", "uncertainties", "conflicts",
    "scope", "qualification", "derivation", "revalidation",
)

_HEX64 = re.compile(r"^[0-9a-f]{64}$")

DEFAULT_EVIDENCE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "evidence", "abi_evidence.json")


class EvidenceError(Exception):
    def __init__(self, code, detail=""):
        Exception.__init__(self, code if not detail else "%s: %s" % (code, detail))
        self.code = code
        self.detail = detail


def repo_root():
    """Repository root inferred from this package location."""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read_text(root, relative):
    path = os.path.join(root, relative.replace("/", os.sep))
    try:
        with io.open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return None


def _heading_set(text):
    headings = set()
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            headings.add(stripped)
    return headings


def check_anchor(root, source, anchor, cache):
    """Return None when the citation resolves, else a stable issue code."""
    if not isinstance(source, str) or not source:
        return "evidence_source_missing"
    if not isinstance(anchor, str) or len(anchor.strip()) < 4:
        return "evidence_anchor_missing"
    key = source
    if key not in cache:
        cache[key] = _read_text(root, source)
    text = cache[key]
    if text is None:
        return "evidence_source_not_found"
    if source.lower().endswith(".md"):
        if not anchor.strip().startswith("#"):
            return "evidence_anchor_not_a_heading"
        if anchor.strip() not in _heading_set(text):
            return "evidence_anchor_not_found"
        return None
    if anchor not in text:
        return "evidence_anchor_not_found"
    return None


class Evidence(object):
    def __init__(self, document, path=None, root=None):
        self.document = document
        self.path = path
        self.root = root or repo_root()
        self.entries = document.get("entries") or []
        self.build = document.get("build") or {}

    @classmethod
    def load(cls, path=None, root=None):
        target = path or DEFAULT_EVIDENCE
        try:
            with io.open(target, "r", encoding="utf-8") as handle:
                document = json.load(handle)
        except OSError:
            raise EvidenceError("evidence_unreadable")
        except ValueError:
            raise EvidenceError("evidence_json_invalid")
        if not isinstance(document, dict):
            raise EvidenceError("evidence_root_invalid")
        return cls(document, target, root)

    # -- lookup ------------------------------------------------------------
    def entry(self, entry_id):
        for entry in self.entries:
            if entry.get("id") == entry_id:
                return entry
        return None

    def symbol_index(self):
        """Map an exact export name to the first entry that binds it.

        Only exact ``export`` bindings are indexed. Ordinal-only, plain-name and
        non-exported contracts are deliberately excluded so a comparison can
        never resolve them from a name alone.
        """
        index = {}
        for entry in self.entries:
            for symbol in entry.get("symbols") or []:
                if symbol.get("kind") != "export":
                    continue
                name = symbol.get("name")
                if name and name not in index:
                    index[name] = entry
        return index

    def module_names(self):
        return [module.get("name") for module in self.build.get("modules") or []]

    def operations(self):
        found = set()
        for entry in self.entries:
            for operation in (entry.get("scope") or {}).get("operations") or []:
                found.add(operation)
        return sorted(found)

    def counts(self):
        counts = dict((name, 0) for name in QUALIFICATIONS)
        for entry in self.entries:
            counts[entry.get("qualification")] = counts.get(entry.get("qualification"), 0) + 1
        return counts


def validate(evidence, check_repo_paths=True):
    """Return a list of ``{"code", "entry", "detail"}`` issues. Empty is valid."""
    issues = []
    document = evidence.document
    if document.get("schema") != SCHEMA_NAME:
        issues.append({"code": "schema_mismatch", "entry": None, "detail": ""})
    if document.get("schema_version") != SCHEMA_VERSION:
        issues.append({"code": "schema_version_unsupported", "entry": None, "detail": ""})
    build = evidence.build
    modules = build.get("modules") or []
    if not modules:
        issues.append({"code": "build_modules_missing", "entry": None, "detail": ""})
    module_hashes = {}
    for module in modules:
        name = module.get("name")
        digest = module.get("sha256")
        if not name:
            issues.append({"code": "build_module_name_missing", "entry": None, "detail": ""})
            continue
        if not isinstance(digest, str) or not _HEX64.match(digest):
            issues.append({"code": "build_module_hash_invalid", "entry": None,
                           "detail": name})
            continue
        module_hashes[name.lower()] = digest
    seen_ids = set()
    seen_symbols = {}
    cache = {}
    for entry in evidence.entries:
        entry_id = entry.get("id")
        label = entry_id if isinstance(entry_id, str) else "<missing-id>"
        for key in _REQUIRED_ENTRY_KEYS:
            if key not in entry:
                issues.append({"code": "entry_field_missing", "entry": label,
                               "detail": key})
        if not isinstance(entry_id, str) or not entry_id:
            continue
        if entry_id in seen_ids:
            issues.append({"code": "entry_id_duplicate", "entry": entry_id, "detail": ""})
        seen_ids.add(entry_id)
        qualification = entry.get("qualification")
        derivation = entry.get("derivation")
        if qualification not in QUALIFICATIONS:
            issues.append({"code": "qualification_unknown", "entry": entry_id,
                           "detail": str(qualification)})
        if derivation not in DERIVATIONS:
            issues.append({"code": "derivation_unknown", "entry": entry_id,
                           "detail": str(derivation)})
        if derivation in ("name_only", "similarity_only") and qualification == "QUALIFIED_LIMITED":
            issues.append({"code": "qualification_exceeds_derivation", "entry": entry_id,
                           "detail": derivation})
        if entry.get("build_profile") != build.get("profile_id"):
            issues.append({"code": "entry_build_profile_mismatch", "entry": entry_id,
                           "detail": str(entry.get("build_profile"))})
        # module identity must be one of the recorded build modules
        for module in entry.get("modules") or []:
            name = (module.get("module") or "").lower()
            digest = module.get("sha256")
            if name not in module_hashes:
                issues.append({"code": "entry_module_unknown", "entry": entry_id,
                               "detail": module.get("module") or ""})
                continue
            if digest != module_hashes[name]:
                issues.append({"code": "entry_module_hash_mismatch", "entry": entry_id,
                               "detail": module.get("module") or ""})
        symbols = entry.get("symbols") or []
        if not symbols and qualification not in ("BLOCKED", "UNRESOLVED"):
            issues.append({"code": "entry_symbols_empty", "entry": entry_id, "detail": ""})
        if not symbols and not entry.get("unbound_reason"):
            issues.append({"code": "entry_unbound_reason_missing", "entry": entry_id,
                           "detail": ""})
        for symbol in symbols:
            kind = symbol.get("kind")
            if kind not in ("export", "export_ordinal", "export_name_unverified", "rva"):
                issues.append({"code": "symbol_kind_unknown", "entry": entry_id,
                               "detail": str(kind)})
            name = symbol.get("name")
            if kind == "export":
                if not name:
                    issues.append({"code": "symbol_export_name_missing", "entry": entry_id,
                                   "detail": ""})
                else:
                    if name in seen_symbols:
                        issues.append({"code": "symbol_bound_twice", "entry": entry_id,
                                       "detail": name})
                    seen_symbols[name] = entry_id
            if kind == "export_ordinal" and not symbol.get("ordinal"):
                issues.append({"code": "symbol_ordinal_missing", "entry": entry_id,
                               "detail": ""})
            if kind == "export_name_unverified" and not symbol.get("name"):
                issues.append({"code": "symbol_plain_name_missing", "entry": entry_id,
                               "detail": ""})
            if kind == "rva":
                if symbol.get("rva") is not None:
                    issues.append({"code": "rva_duplicated_in_evidence", "entry": entry_id,
                                   "detail": "vendor RVA belongs in the version profile"})
                if not symbol.get("entry_contract"):
                    issues.append({"code": "rva_contract_missing", "entry": entry_id,
                                   "detail": ""})
                if not symbol.get("note"):
                    issues.append({"code": "rva_revalidation_note_missing", "entry": entry_id,
                                   "detail": ""})
        shape = entry.get("call_shape")
        if shape is None and not entry.get("call_shape_absent_reason"):
            issues.append({"code": "call_shape_absent_reason_missing", "entry": entry_id,
                           "detail": ""})
        if shape is not None:
            for key in ("abi", "returns", "params"):
                if key not in shape:
                    issues.append({"code": "call_shape_field_missing", "entry": entry_id,
                                   "detail": key})
        layout = entry.get("layout")
        if layout is None:
            if not entry.get("layout_absent_reason"):
                issues.append({"code": "layout_absent_reason_missing", "entry": entry_id,
                               "detail": ""})
        else:
            if not layout.get("ownership"):
                issues.append({"code": "layout_ownership_missing", "entry": entry_id,
                               "detail": ""})
            code = check_anchor(evidence.root, layout.get("evidence_source"),
                                layout.get("evidence_anchor"), cache)
            if code:
                issues.append({"code": code, "entry": entry_id,
                               "detail": "layout:%s" % (layout.get("evidence_source") or "")})
        static_evidence = entry.get("static_evidence") or []
        if not static_evidence:
            issues.append({"code": "static_evidence_empty", "entry": entry_id, "detail": ""})
        for item in static_evidence:
            if check_repo_paths:
                code = check_anchor(evidence.root, item.get("source"),
                                    item.get("anchor"), cache)
                if code:
                    issues.append({"code": code, "entry": entry_id,
                                   "detail": item.get("source") or ""})
            if not item.get("claim"):
                issues.append({"code": "static_evidence_claim_missing", "entry": entry_id,
                               "detail": ""})
        verification = entry.get("verification") or {}
        offline = verification.get("offline_tests") or []
        real_host = verification.get("real_host") or []
        for test in offline:
            path = test.get("path")
            if not path:
                issues.append({"code": "offline_test_path_missing", "entry": entry_id,
                               "detail": ""})
            elif check_repo_paths and not os.path.exists(
                    os.path.join(evidence.root, path.replace("/", os.sep))):
                issues.append({"code": "offline_test_not_found", "entry": entry_id,
                               "detail": path})
        passing = [record for record in real_host
                   if str(record.get("status", "")).startswith("PASS")]
        for record in real_host:
            status = record.get("status")
            if status not in ("PASS", "PASS_LIMITED", "FAIL", "NOT_TESTED"):
                issues.append({"code": "real_host_status_unknown", "entry": entry_id,
                               "detail": str(status)})
            if check_repo_paths:
                code = check_anchor(evidence.root, record.get("record"),
                                    record.get("anchor"), cache)
                if code:
                    issues.append({"code": code, "entry": entry_id,
                                   "detail": record.get("record") or ""})
        if qualification == "QUALIFIED_LIMITED" and not passing:
            issues.append({"code": "qualified_without_real_host_pass", "entry": entry_id,
                           "detail": ""})
        if qualification == "QUALIFIED_LIMITED" and passing and any(
                record.get("status") == "FAIL" for record in real_host):
            issues.append({"code": "qualified_with_unresolved_fail", "entry": entry_id,
                           "detail": "keep the FAIL record separate from the PASS scope"})
        for conflict in entry.get("conflicts") or []:
            if not conflict.get("resolved", False) and qualification == "QUALIFIED_LIMITED":
                issues.append({"code": "qualified_with_open_conflict", "entry": entry_id,
                               "detail": conflict.get("summary") or ""})
        scope = entry.get("scope") or {}
        for key in ("operations", "dtypes", "versions", "limits"):
            if key not in scope:
                issues.append({"code": "scope_field_missing", "entry": entry_id,
                               "detail": key})
        for operation in scope.get("operations") or []:
            if operation not in (evidence.document.get("known_operations") or []):
                issues.append({"code": "scope_operation_unknown", "entry": entry_id,
                               "detail": operation})
        if not entry.get("revalidation"):
            issues.append({"code": "revalidation_empty", "entry": entry_id, "detail": ""})
    return issues


def cross_check_profile(evidence):
    """Compare recorded module hashes and entry contracts with the pinned profile.

    The version profile is the runtime source of truth for fingerprints and for
    the non-exported entry contracts each capability group resolves. A mismatch
    means the inventory describes a different build, or silently omits a bound
    entry, which is a blocking inconsistency rather than cosmetic drift.
    """
    source = (evidence.build or {}).get("identity_source")
    if not source:
        return [{"code": "identity_source_missing", "entry": None, "detail": ""}]
    text = _read_text(evidence.root, source)
    if text is None:
        return [{"code": "identity_source_not_found", "entry": None, "detail": source}]
    found = {}
    for line in text.splitlines():
        match = re.search(r'\{"([A-Za-z0-9._\-]+)",\s*"([0-9a-f]{64})",\s*(true|false)\}', line)
        if match:
            found[match.group(1).lower()] = (match.group(2), match.group(3) == "true")
    issues = []
    for module in (evidence.build or {}).get("modules") or []:
        name = (module.get("name") or "").lower()
        if name not in found:
            issues.append({"code": "profile_module_not_found", "entry": None,
                           "detail": module.get("name") or ""})
            continue
        digest, check_version = found[name]
        if digest != module.get("sha256"):
            issues.append({"code": "profile_module_hash_mismatch", "entry": None,
                           "detail": module.get("name") or ""})
        if bool(module.get("check_version")) != check_version:
            issues.append({"code": "profile_check_version_mismatch", "entry": None,
                           "detail": module.get("name") or ""})
    issues.extend(_cross_check_contracts(evidence, text))
    return issues


def _profile_contracts(text):
    """Return the (module, contract) pairs the version profile resolves."""
    pairs = set()
    for line in text.splitlines():
        match = re.search(
            r'\{"([a-z0-9_]+)",\s*"([A-Za-z0-9._\-]+)",\s*0x([0-9a-fA-F]+)\}', line)
        if match:
            pairs.add((match.group(2).lower(), match.group(1)))
    return pairs


def _cross_check_contracts(evidence, text):
    """Every non-exported entry the profile resolves must appear in the inventory."""
    covered = set()
    for entry in evidence.entries:
        for symbol in entry.get("symbols") or []:
            if symbol.get("kind") == "rva" and symbol.get("entry_contract"):
                covered.add(((symbol.get("module") or "").lower(),
                             symbol["entry_contract"]))
    issues = []
    for module, contract in sorted(_profile_contracts(text)):
        if (module, contract) not in covered:
            issues.append({"code": "profile_contract_not_in_evidence", "entry": None,
                           "detail": "%s:%s" % (module, contract)})
    return issues


def render_markdown(evidence):
    """Render the reviewable ABI evidence document from the JSON inventory."""
    build = evidence.build
    out = []
    write = out.append
    write("# GMS native ABI evidence inventory")
    write("")
    write("<!-- GENERATED FILE. Edit tools/gms_compat/evidence/abi_evidence.json and run")
    write("     python tools/gms_compat/cli.py evidence render. Hand edits are rejected")
    write("     by the evidence validator. -->")
    write("")
    write("This document is a machine-verified inventory of what is known about the")
    write("fixed-build native ABI, separated from what has actually been observed in a")
    write("real host. It is not an API reference for Gatan software and it grants no")
    write("capability.")
    write("")
    write("## Build identity")
    write("")
    write("| Field | Value |")
    write("| --- | --- |")
    write("| Adapter profile | `%s` |" % build.get("profile_id"))
    write("| Host | `%s` |" % build.get("host"))
    write("| Version | `%s` |" % build.get("version"))
    write("| Architecture | `%s` |" % build.get("architecture"))
    write("| Identity source | `%s` |" % build.get("identity_source"))
    write("| Version policy | %s |" % build.get("version_policy"))
    write("")
    write("| Module | SHA-256 (pinned) | Version checked |")
    write("| --- | --- | --- |")
    for module in build.get("modules") or []:
        write("| `%s` | `%s` | %s |" % (module.get("name"), module.get("sha256"),
                                        "yes" if module.get("check_version") else "no"))
    write("")
    write("Pinned fingerprints are the ones the shipping adapter gate already uses. The")
    write("inventory restates them only to detect drift; the runtime gate remains the")
    write("source of truth and is cross-checked by `evidence validate`.")
    write("")
    counts = evidence.counts()
    write("## Qualification summary")
    write("")
    write("| State | Count | Meaning |")
    write("| --- | --- | --- |")
    meanings = {
        "QUALIFIED_LIMITED": "bounded synthetic real-host acceptance recorded for this exact build",
        "STATIC_CANDIDATE": "static or offline evidence only; never executed in a host",
        "UNRESOLVED": "evidence insufficient or contradictory; must not be bound",
        "BLOCKED": "deliberately refused (signature, policy or superseded)",
    }
    for name in QUALIFICATIONS:
        write("| `%s` | %d | %s |" % (name, counts.get(name, 0), meanings[name]))
    write("")
    write("Counts are not capability claims: a qualified ABI entry only means its call")
    write("shape and ownership were exercised for the recorded scope, not that any")
    write("operation built on it is admitted for another build or dtype.")
    write("")
    write("## Entry index")
    write("")
    write("| ID | Area | Bindings | Qualification | Operations |")
    write("| --- | --- | --- | --- | --- |")
    for entry in evidence.entries:
        bindings = ", ".join(
            "`%s`" % (symbol.get("name") or symbol.get("entry_contract"))
            for symbol in entry.get("symbols") or [])
        operations = ", ".join((entry.get("scope") or {}).get("operations") or []) or "-"
        write("| `%s` | %s | %s | `%s` | %s |" % (
            entry.get("id"), entry.get("area"), bindings, entry.get("qualification"),
            operations))
    write("")
    for area in sorted(set(entry.get("area") for entry in evidence.entries)):
        write("## Area: %s" % area)
        write("")
        for entry in evidence.entries:
            if entry.get("area") != area:
                continue
            _render_entry(write, entry)
    return "\n".join(out) + "\n"


def _render_entry(write, entry):
    write("### `%s` — %s" % (entry.get("id"), entry.get("title")))
    write("")
    write("- Qualification: `%s` (derivation: `%s`)" % (entry.get("qualification"),
                                                        entry.get("derivation")))
    write("- Bindings:")
    for symbol in entry.get("symbols") or []:
        kind = symbol.get("kind")
        if kind == "export":
            write("  - export `%s` in `%s`" % (symbol.get("name"), symbol.get("module")))
        elif kind == "export_ordinal":
            write("  - ordinal `%s` in `%s`" % (symbol.get("name"), symbol.get("module")))
        elif kind == "export_name_unverified":
            write("  - plain name `%s` in `%s` (decorated export name not recorded; not a "
                  "binding)" % (symbol.get("name"), symbol.get("module")))
        else:
            write("  - non-exported entry contract `%s` in `%s` (RVA lives only in the "
                  "version profile)" % (symbol.get("entry_contract"), symbol.get("module")))
    if not entry.get("symbols"):
        write("  - none: %s" % entry.get("unbound_reason"))
    shape = entry.get("call_shape")
    if shape is None:
        write("- Call shape: unknown — %s" % entry.get("call_shape_absent_reason"))
    else:
        write("- Call shape: `%s`, returns `%s`%s" % (
            shape.get("abi"), shape.get("returns"),
            ", hidden structure-return pointer first" if shape.get("hidden_sret") else ""))
        if shape.get("params"):
            write("")
            write("  | # | Parameter | Type | Notes |")
            write("  | --- | --- | --- | --- |")
            for index, param in enumerate(shape.get("params") or [], 1):
                write("  | %d | `%s` | `%s` | %s |" % (index, param.get("name"),
                                                       param.get("type"),
                                                       param.get("notes") or ""))
        if shape.get("notes"):
            write("")
            write("  %s" % shape.get("notes"))
    layout = entry.get("layout")
    if layout is None:
        write("- Layout / ownership: not recorded — %s" % entry.get("layout_absent_reason"))
    else:
        write("- Layout source: `%s` %s" % (layout.get("evidence_source"),
                                            layout.get("evidence_anchor")))
        for structure in layout.get("structures") or []:
            write("  - `%s` size %s alignment %s: %s" % (
                structure.get("name"), structure.get("size"), structure.get("alignment"),
                structure.get("fields")))
        write("- Ownership: %s" % layout.get("ownership"))
    write("")
    write("Static evidence:")
    for item in entry.get("static_evidence") or []:
        write("- `%s` %s — %s" % (item.get("source"), item.get("anchor"),
                                  item.get("claim")))
    write("")
    write("Verification:")
    offline = (entry.get("verification") or {}).get("offline_tests") or []
    real_host = (entry.get("verification") or {}).get("real_host") or []
    if not offline and not real_host:
        write("- none recorded")
    for test in offline:
        write("- offline: `%s`%s" % (test.get("path"),
                                     " (%s)" % test.get("note") if test.get("note") else ""))
    for record in real_host:
        write("- real host: `%s` — `%s` %s" % (record.get("status"), record.get("record"),
                                               record.get("anchor")))
    if entry.get("uncertainties"):
        write("")
        write("Uncertainties:")
        for item in entry.get("uncertainties"):
            write("- %s" % item)
    if entry.get("conflicts"):
        write("")
        write("Conflicts:")
        for item in entry.get("conflicts"):
            write("- %s%s" % (item.get("summary"),
                              " (resolved)" if item.get("resolved") else " (OPEN)"))
    scope = entry.get("scope") or {}
    write("")
    write("Scope: operations %s; dtypes %s; versions %s." % (
        ", ".join(scope.get("operations") or []) or "-",
        ", ".join(scope.get("dtypes") or []) or "-",
        ", ".join(scope.get("versions") or []) or "-"))
    for limit in scope.get("limits") or []:
        write("- limit: %s" % limit)
    write("")
    write("On any build change re-derive: %s." % ", ".join(entry.get("revalidation") or []))
    write("")
