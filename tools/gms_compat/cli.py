"""Command line interface for the offline GMS compatibility tool.

Two operations exist in this release:

``inspect``  static, read-only PE/export/version inventory of a caller-named
             local file or directory. Never loads the module.
``compare``  structural comparison of two manifests. Never grants qualification.

``evidence`` manages the machine-readable ABI evidence inventory.

Exit codes: 0 success, 1 evidence/policy failure, 2 input failure,
3 drift detected by a ``--check`` invocation.
"""
import argparse
import glob
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import compare as compare_module  # noqa: E402
import evidence as evidence_module  # noqa: E402
import manifest as manifest_module  # noqa: E402
import pe  # noqa: E402

EXIT_OK = 0
EXIT_POLICY = 1
EXIT_INPUT = 2
EXIT_DRIFT = 3


def _emit_json(document, stream=None):
    stream = stream or sys.stdout
    stream.write(manifest_module.dumps(document))


def _fail(code, detail="", stream=None):
    stream = stream or sys.stderr
    payload = {"schema": "mcp-dm/gms-compat/error", "schema_version": 1,
               "error": {"code": code}}
    if detail:
        payload["error"]["detail"] = detail
    stream.write(manifest_module.dumps(payload))
    return EXIT_INPUT


# -- inspect ---------------------------------------------------------------
def _collect_inputs(paths, patterns, recursive, max_modules):
    patterns = patterns or ["*.dll", "*.exe"]
    files = []
    errors = []
    for path in paths:
        if os.path.isdir(path):
            found = []
            for pattern in patterns:
                base = os.path.join(path, pattern)
                if recursive:
                    matches = glob.iglob(os.path.join(path, "**", pattern), recursive=True)
                else:
                    matches = glob.iglob(base)
                for match in matches:
                    if os.path.isfile(match):
                        found.append(match)
            unique = sorted(set(found), key=lambda item: os.path.basename(item).lower())
            if len(unique) > max_modules:
                errors.append({"code": "pe_directory_too_many_modules",
                               "module": manifest_module.redact_path(path, None, "basename"),
                               "detail": "%d matches, limit %d" % (len(unique), max_modules)})
                unique = unique[:max_modules]
            files.extend(unique)
        elif os.path.isfile(path):
            files.append(path)
        else:
            errors.append({"code": "pe_file_missing",
                           "module": manifest_module.redact_path(path, None, "basename"),
                           "detail": ""})
    return files, errors


def command_inspect(args):
    if args.disclosure == "relative" and not args.redact_root:
        return _fail("path_disclosure_requires_root")
    files, errors = _collect_inputs(args.paths, args.pattern, args.recursive,
                                   args.max_modules)
    if not files and not errors:
        return _fail("pe_no_input")
    modules = []
    for path in files:
        try:
            record = pe.inspect_module(path, max_file_bytes=args.max_file_bytes)
        except pe.PeFormatError as error:
            errors.append({
                "code": error.code,
                "module": manifest_module.redact_path(path, args.redact_root,
                                                      args.disclosure),
                "detail": error.detail,
            })
            continue
        record["source"] = manifest_module.redact_path(path, args.redact_root,
                                                       args.disclosure)
        modules.append(record)
    document = manifest_module.new_manifest("inspect", {
        "path_disclosure": args.disclosure,
        "requested": len(files) + len([item for item in errors
                                       if item["code"] == "pe_file_missing"]),
        "inspected": len(modules),
        "failed": len(errors),
        "read_only": True,
        "loaded_any_module": False,
        "executed_any_target_code": False,
    }, modules)
    if errors:
        document["errors"] = sorted(errors, key=lambda item: (item["module"] or "",
                                                              item["code"]))
    _write_output(document, args.output)
    if errors and not modules:
        return EXIT_INPUT
    return EXIT_INPUT if errors else EXIT_OK


# -- compare ---------------------------------------------------------------
def command_compare(args):
    try:
        reference = manifest_module.load_manifest(args.reference)
        candidate = manifest_module.load_manifest(args.candidate)
    except manifest_module.ManifestError as error:
        return _fail(error.code, error.detail)
    evidence = None
    if not args.no_evidence:
        try:
            evidence = evidence_module.Evidence.load(args.evidence)
        except evidence_module.EvidenceError as error:
            if args.evidence:
                return _fail(error.code, error.detail)
    report = compare_module.compare(reference, candidate, evidence=evidence,
                                    module_filter=args.module)
    _write_output(report, args.output)
    if args.fail_on_change and report["summary"]["changed_modules"]:
        return EXIT_POLICY
    return EXIT_OK


# -- evidence --------------------------------------------------------------
def command_evidence(args):
    try:
        evidence = evidence_module.Evidence.load(args.evidence)
    except evidence_module.EvidenceError as error:
        return _fail(error.code, error.detail)
    if args.action == "summary":
        document = {
            "schema": "mcp-dm/gms-compat/evidence-summary",
            "schema_version": 1,
            "build": {
                "profile_id": evidence.build.get("profile_id"),
                "version": evidence.build.get("version"),
                "architecture": evidence.build.get("architecture"),
                "modules": evidence.module_names(),
            },
            "counts": evidence.counts(),
            "areas": sorted(set(entry.get("area") for entry in evidence.entries)),
            "operations": evidence.operations(),
            "entry_count": len(evidence.entries),
        }
        _write_output(document, args.output)
        return EXIT_OK
    if args.action == "show":
        entry = evidence.entry(args.entry_id)
        if entry is None:
            return _fail("evidence_entry_not_found", args.entry_id)
        _write_output(entry, args.output)
        return EXIT_OK
    if args.action == "validate":
        issues = evidence_module.validate(evidence, check_repo_paths=not args.no_path_check)
        issues.extend(evidence_module.cross_check_profile(evidence))
        document = {
            "schema": "mcp-dm/gms-compat/evidence-validation",
            "schema_version": 1,
            "entry_count": len(evidence.entries),
            "valid": not issues,
            "issues": issues,
        }
        if args.json:
            _write_output(document, args.output)
        else:
            if issues:
                for issue in issues:
                    sys.stdout.write("%s %s %s\n" % (issue["code"], issue["entry"] or "-",
                                                     issue["detail"]))
            else:
                sys.stdout.write("evidence valid: %d entries\n" % len(evidence.entries))
        return EXIT_OK if not issues else EXIT_POLICY
    if args.action == "render":
        rendered = evidence_module.render_markdown(evidence)
        target = args.output or os.path.join(evidence_module.repo_root(),
                                             "docs", "GMS_COMPAT_ABI_EVIDENCE.md")
        if args.check:
            try:
                with open(target, "r", encoding="utf-8") as handle:
                    current = handle.read()
            except OSError:
                sys.stderr.write("evidence render drift: %s missing\n" % target)
                return EXIT_DRIFT
            if current != rendered:
                sys.stderr.write("evidence render drift: %s is stale\n" % target)
                return EXIT_DRIFT
            sys.stdout.write("evidence render up to date: %s\n" % target)
            return EXIT_OK
        with open(target, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(rendered)
        sys.stdout.write("evidence rendered: %s\n" % target)
        return EXIT_OK
    return _fail("evidence_action_unknown")


def _write_output(document, path):
    text = manifest_module.dumps(document)
    if path:
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    else:
        sys.stdout.write(text)


# -- parser ----------------------------------------------------------------
def build_parser():
    parser = argparse.ArgumentParser(
        prog="gms-compat",
        description="Offline, read-only GMS compatibility inspection. "
                    "Never loads a vendor module or grants qualification.")
    parser.add_argument("--version", action="version",
                        version="%(prog)s " + manifest_module.TOOL_VERSION)
    subparsers = parser.add_subparsers(dest="command")

    inspect = subparsers.add_parser(
        "inspect", help="static PE inventory of local files or a directory")
    inspect.add_argument("paths", nargs="+", help="file or directory to inspect")
    inspect.add_argument("--pattern", action="append", default=None,
                         help="directory glob (default: *.dll, *.exe)")
    inspect.add_argument("--recursive", action="store_true",
                         help="search sub-directories (default: no)")
    inspect.add_argument("--max-modules", type=int, default=64,
                         help="directory module budget (default: 64)")
    inspect.add_argument("--max-file-bytes", type=int, default=pe.DEFAULT_MAX_FILE_BYTES,
                         help="reject files larger than this (default: 1 GiB)")
    inspect.add_argument("--disclosure", choices=manifest_module.DISCLOSURE_MODES,
                         default="basename",
                         help="local path disclosure in the report (default: basename)")
    inspect.add_argument("--redact-root", default=None,
                         help="root for --disclosure relative")
    inspect.add_argument("--output", default=None, help="write report to this file")
    inspect.set_defaults(func=command_inspect)

    compare = subparsers.add_parser(
        "compare", help="compare two module manifests")
    compare.add_argument("reference", help="manifest of the known/reference build")
    compare.add_argument("candidate", help="manifest of the candidate build")
    compare.add_argument("--evidence", default=None,
                         help="ABI evidence inventory (default: packaged inventory)")
    compare.add_argument("--no-evidence", action="store_true",
                         help="skip capability impact mapping")
    compare.add_argument("--module", action="append", default=None,
                         help="restrict to a module name (repeatable)")
    compare.add_argument("--output", default=None, help="write report to this file")
    compare.add_argument("--fail-on-change", action="store_true",
                         help="exit 1 when any module differs")
    compare.set_defaults(func=command_compare)

    evidence = subparsers.add_parser(
        "evidence", help="validate, render or query the ABI evidence inventory")
    evidence_sub = evidence.add_subparsers(dest="action")
    validate = evidence_sub.add_parser("validate", help="check invariants and citations")
    validate.add_argument("--evidence", default=None)
    validate.add_argument("--no-path-check", action="store_true",
                          help="skip repository citation checks")
    validate.add_argument("--json", action="store_true")
    validate.add_argument("--output", default=None)
    validate.set_defaults(func=command_evidence)

    render = evidence_sub.add_parser("render", help="render the Markdown view")
    render.add_argument("--evidence", default=None)
    render.add_argument("--output", default=None)
    render.add_argument("--check", action="store_true",
                        help="fail if the rendered document is stale")
    render.set_defaults(func=command_evidence)

    summary = evidence_sub.add_parser("summary", help="print qualification counts")
    summary.add_argument("--evidence", default=None)
    summary.add_argument("--output", default=None)
    summary.set_defaults(func=command_evidence)

    show = evidence_sub.add_parser("show", help="print one evidence entry")
    show.add_argument("entry_id")
    show.add_argument("--evidence", default=None)
    show.add_argument("--output", default=None)
    show.set_defaults(func=command_evidence)

    evidence.set_defaults(func=command_evidence, action=None)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help(sys.stderr)
        return EXIT_INPUT
    if args.command == "evidence" and not getattr(args, "action", None):
        parser.print_help(sys.stderr)
        return EXIT_INPUT
    try:
        return args.func(args)
    except BrokenPipeError:
        return EXIT_OK
    except (pe.PeFormatError, manifest_module.ManifestError,
            evidence_module.EvidenceError) as error:
        return _fail(error.code, error.detail)
    except json.JSONDecodeError:
        return _fail("json_invalid")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
