"""Structured module-manifest model: validation, canonical form, stable I/O.

A manifest is the only input ``compare`` accepts. It is deliberately a flat,
machine-checkable description of what a PE file *declares*, not a statement of
what its code does. Nothing here asserts ABI compatibility.
"""
import json
import os
import re

SCHEMA_NAME = "mcp-dm/gms-compat/module-manifest"
SCHEMA_VERSION = 1
TOOL_NAME = "gms-compat"
TOOL_VERSION = "0.1.0"

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_NAME = re.compile(r"^[A-Za-z0-9._\-]{1,260}$")

DISCLOSURE_MODES = ("none", "basename", "relative", "full")


class ManifestError(Exception):
    def __init__(self, code, detail=""):
        Exception.__init__(self, code if not detail else "%s: %s" % (code, detail))
        self.code = code
        self.detail = detail


def dumps(document):
    """Canonical JSON text: sorted keys, fixed separators, trailing newline."""
    return json.dumps(document, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def loads(text):
    try:
        return json.loads(text)
    except ValueError:
        raise ManifestError("manifest_json_invalid")


def load_manifest(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
    except OSError:
        raise ManifestError("manifest_unreadable")
    return normalize_manifest(loads(text))


def redact_path(path, root=None, mode="basename"):
    """Deterministic local-path disclosure control.

    ``none``      -> ``null``
    ``basename``  -> file name only (default; no machine layout leaks)
    ``relative``  -> path relative to ``root`` when it is inside ``root``
    ``full``      -> the caller-supplied path, explicitly requested
    """
    if mode not in DISCLOSURE_MODES:
        raise ManifestError("path_disclosure_invalid")
    if mode == "none":
        return None
    if mode == "full":
        return path
    if mode == "basename":
        return os.path.basename(path)
    if not root:
        raise ManifestError("path_disclosure_requires_root")
    try:
        relative = os.path.relpath(path, root)
    except ValueError:
        return os.path.basename(path)
    if relative.startswith(".."):
        return os.path.basename(path)
    return relative.replace(os.sep, "/")


def _require(mapping, key, kinds, code):
    if not isinstance(mapping, dict) or key not in mapping:
        raise ManifestError(code)
    value = mapping[key]
    if not isinstance(value, kinds):
        raise ManifestError(code)
    return value


def _normalize_export(entry):
    if not isinstance(entry, dict):
        raise ManifestError("manifest_export_invalid")
    ordinal = _require(entry, "ordinal", int, "manifest_export_invalid")
    rva = _require(entry, "rva", int, "manifest_export_invalid")
    if ordinal < 0 or rva < 0:
        raise ManifestError("manifest_export_invalid")
    name = entry.get("name")
    if name is not None and not isinstance(name, str):
        raise ManifestError("manifest_export_invalid")
    section = entry.get("section")
    if section is not None and not isinstance(section, str):
        raise ManifestError("manifest_export_invalid")
    forwarder = entry.get("forwarder")
    if forwarder is not None and not isinstance(forwarder, str):
        raise ManifestError("manifest_export_invalid")
    return {
        "ordinal": ordinal,
        "name": name,
        "rva": rva,
        "section": section,
        "executable": bool(entry.get("executable", False)),
        "forwarder": forwarder,
    }


def _normalize_import(entry):
    if not isinstance(entry, dict):
        raise ManifestError("manifest_import_invalid")
    module = _require(entry, "module", str, "manifest_import_invalid")
    if not module:
        raise ManifestError("manifest_import_invalid")
    return {
        "module": module,
        "kind": str(entry.get("kind", "import")),
        "function_count": int(entry.get("function_count", 0)),
        "thunk_count_bounded": bool(entry.get("thunk_count_bounded", False)),
    }


def normalize_module(record):
    if not isinstance(record, dict):
        raise ManifestError("manifest_module_invalid")
    name = _require(record, "name", str, "manifest_module_invalid")
    if not name or not _SAFE_NAME.match(name):
        raise ManifestError("manifest_module_name_invalid")
    sha256 = _require(record, "sha256", str, "manifest_module_invalid")
    if not _HEX64.match(sha256):
        raise ManifestError("manifest_module_hash_invalid")
    architecture = _require(record, "architecture", str, "manifest_module_invalid")
    version = record.get("version") or {}
    if not isinstance(version, dict):
        raise ManifestError("manifest_module_version_invalid")
    exports = [_normalize_export(entry) for entry in record.get("exports") or []]
    exports.sort(key=lambda item: (item["ordinal"], item["name"] or ""))
    imports = [_normalize_import(entry) for entry in record.get("imports") or []]
    imports.sort(key=lambda item: item["module"])
    return {
        "name": name,
        "source": record.get("source"),
        "sha256": sha256,
        "architecture": architecture,
        "size_bytes": int(record.get("size_bytes", 0)),
        "pe": record.get("pe") or {},
        "version": {
            "file_version": version.get("file_version"),
            "product_version": version.get("product_version"),
            "source": str(version.get("source", "absent")),
        },
        "exports": exports,
        "export_summary": record.get("export_summary") or {},
        "imports": imports,
    }


def normalize_manifest(document):
    if not isinstance(document, dict):
        raise ManifestError("manifest_root_invalid")
    if document.get("schema") != SCHEMA_NAME:
        raise ManifestError("manifest_schema_mismatch")
    if document.get("schema_version") != SCHEMA_VERSION:
        raise ManifestError("manifest_schema_version_unsupported")
    modules = [normalize_module(record) for record in document.get("modules") or []]
    modules.sort(key=lambda item: item["name"].lower())
    names = [item["name"].lower() for item in modules]
    if len(names) != len(set(names)):
        raise ManifestError("manifest_duplicate_module")
    return {
        "schema": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "tool": {"name": TOOL_NAME, "version": TOOL_VERSION},
        "generated_by": str(document.get("generated_by", "external")),
        "inputs": document.get("inputs") or {},
        "modules": modules,
    }


def new_manifest(generated_by, inputs, modules):
    return normalize_manifest({
        "schema": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "tool": {"name": TOOL_NAME, "version": TOOL_VERSION},
        "generated_by": generated_by,
        "inputs": inputs,
        "modules": modules,
    })


def module_index(manifest):
    return dict((module["name"].lower(), module) for module in manifest["modules"])


def export_index(module):
    """Named exports keyed by exact decorated name.

    Unnamed exports are excluded: an ordinal-only binding is never sufficient
    identity for a cross-build comparison.
    """
    index = {}
    for entry in module.get("exports") or []:
        if entry.get("name"):
            index[entry["name"]] = entry
    return index


def export_index_by_ordinal(module):
    index = {}
    for entry in module.get("exports") or []:
        index[entry["ordinal"]] = entry
    return index
