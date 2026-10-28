#!/usr/bin/env python3
"""Export two independent candidates from committed Git objects; never move/push code.

Python >=3.10, standard library only. This is an offline migration utility, not
part of either provider runtime. All paths in the ownership manifest are scoped
to Git-tracked blobs; working trees, credentials and scientific workspaces are
never copied. Source and recipe commits are recorded separately.
"""
from __future__ import annotations

import argparse
import ast
import fnmatch
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tempfile

MAX_BLOB_BYTES = 16 * 1024 * 1024
MANIFEST_PATH = "migration/ownership.json"
HEX = re.compile(r"[a-f0-9]{40}\Z")
JS_REF = re.compile(r"(?:\bfrom\s*|\bimport\s*\(\s*|\bimport\s*|\bnew\s+URL\s*\(\s*)['\"]([^'\"\n]+)['\"]")
FORBIDDEN_SUFFIXES = {".dm3", ".dm4", ".npy", ".npz", ".tif", ".tiff", ".dll", ".exe", ".pdb", ".pdf", ".pem", ".key"}


class SplitError(ValueError):
    """A migration precondition or boundary check failed."""


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def safe_path(value):
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise SplitError("Invalid repository-relative path")
    parts = PurePosixPath(value).parts
    if value.startswith("/") or any(p in ("..", ".git") or ":" in p for p in parts) or str(PurePosixPath(value)) != value:
        raise SplitError("Unsafe repository-relative path: " + value)
    return value


class Snapshot:
    def __init__(self, repo, ref):
        self.repo = Path(repo).resolve()
        self.repo = Path(self.git("rev-parse", "--show-toplevel").decode().strip()).resolve()
        if ref != "HEAD" and not HEX.fullmatch(ref):
            raise SplitError("Use HEAD or an explicit full 40-character commit SHA, not a moving branch")
        self.sha = self.git("rev-parse", "--verify", ref + "^{commit}").decode().strip()
        if not HEX.fullmatch(self.sha):
            raise SplitError("Cannot resolve an immutable source commit")
        self.files = {}
        for row in self.git("ls-tree", "-rz", "--full-tree", self.sha).split(b"\0"):
            if not row:
                continue
            header, raw_path = row.split(b"\t", 1)
            mode, kind, oid = header.decode().split()
            name = safe_path(raw_path.decode("utf-8"))
            self.files[name] = (mode, kind, oid)

    def git(self, *args):
        result = subprocess.run(["git", "-C", str(self.repo), *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        if result.returncode:
            raise SplitError("Git read failed: " + result.stderr.decode(errors="replace").strip())
        return result.stdout

    def read(self, name):
        name = safe_path(name)
        if name not in self.files:
            raise SplitError("Required committed file missing: " + name)
        mode, kind, oid = self.files[name]
        if kind != "blob" or mode not in ("100644", "100755"):
            raise SplitError("Symlink/submodule/non-ordinary source refused: " + name)
        size = int(self.git("cat-file", "-s", oid))
        if size > MAX_BLOB_BYTES:
            raise SplitError("Source blob exceeds migration budget: " + name)
        raw = self.git("cat-file", "blob", oid)
        if len(raw) != size:
            raise SplitError("Git blob size mismatch")
        return raw, mode, oid


def admit_file(name):
    safe_path(name)
    if Path(name).suffix.lower() in FORBIDDEN_SUFFIXES or PurePosixPath(name).name.startswith(".env"):
        raise SplitError("Private/generated/vendor payload is not a migration source: " + name)


def matches(name, patterns):
    return any(fnmatch.fnmatchcase(name, pattern) for pattern in patterns)


def local_module_exists(files, module):
    return module + ".py" in files or module + "/__init__.py" in files or any(p.startswith(module + "/") for p in files)


def audit(profile, files):
    """Static local imports + runtime paths. Dynamic/host acceptance is separate."""
    missing = []
    if profile == "microscopy-core":
        forbidden = [p for p in files if p.startswith(("bridge/", "experiments/", "lib/native_")) or p in ("lib/tools/builtin_modules.mjs", "lib/tools/create_server_runtime.mjs") or p.startswith("lib/tools/dm_")]
    else:
        forbidden = [p for p in files if p.startswith(("ui/", "crystallography/", "lib/science/")) or p.startswith(("lib/image_", "lib/structure_"))]
    if forbidden:
        raise SplitError("Forbidden " + profile + " ownership: " + ", ".join(forbidden))
    roots = {p.split("/")[0] for p in files if "/" in p}
    for name, (raw, _mode, _origin) in files.items():
        if name.startswith(("tests/", "docs/", "skills/", "experiments/")):
            continue
        if name.endswith(".mjs"):
            text = raw.decode()
            for ref in JS_REF.findall(text):
                if not ref.startswith("."):
                    continue
                target = os.path.normpath(str(PurePosixPath(name).parent / ref)).replace("\\", "/")
                if target == ".":
                    continue
                if target.startswith("../") or (target not in files and not any(p.startswith(target.rstrip("/") + "/") for p in files)):
                    missing.append(name + " -> " + ref)
        elif name.endswith(".py"):
            tree = ast.parse(raw, filename=name)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules = [(alias.name, 0) for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    modules = [(node.module or "", node.level)]
                else:
                    continue
                for module, level in modules:
                    if profile == "microscopy-core" and module.split(".")[0] in ("DigitalMicrograph", "bridge"):
                        raise SplitError("Host import in science core: " + name + " -> " + module)
                    if level:
                        parent = PurePosixPath(name).parent
                        for _ in range(level - 1):
                            parent = parent.parent
                        candidate = str(parent / module.replace(".", "/"))
                        if module and not local_module_exists(files, candidate):
                            missing.append(name + " -> " + module)
                    elif module.split(".")[0] in roots:
                        if not local_module_exists(files, module.replace(".", "/")):
                            missing.append(name + " -> " + module)
                    elif "/" in name and module and "." not in module:
                        # Bare local imports are used when a worker runs as a file.
                        candidate = str(PurePosixPath(name).parent / module)
                        if module.startswith(("image_", "structure_")) and not local_module_exists(files, candidate):
                            missing.append(name + " -> " + module)
    if missing:
        raise SplitError("Unresolved local dependencies: " + "; ".join(sorted(set(missing))))


def adapt_launcher(raw, adaptation):
    if adaptation.get("schema_version") != 1 or adaptation.get("source_path") != "tools/image_panel.mjs":
        raise SplitError("Unsupported launcher adaptation")
    before, after = adaptation.get("before"), adaptation.get("after")
    if not isinstance(before, str) or not before or not isinstance(after, str) or not after or before == after:
        raise SplitError("Invalid launcher adaptation")
    before, after = before.encode(), after.encode()
    counts = (raw.count(before), raw.count(after))
    if counts == (1, 0):
        return raw.replace(before, after, 1), True
    if counts == (0, 1):
        return raw, False
    raise SplitError("Panel launcher changed or is ambiguous; review the exact source, do not blindly patch it")


def package(profile, unit_tests):
    result = {"name": profile, "version": "0.1.0" if profile == "microscopy-core" else "0.6.0", "private": True,
              "type": "module", "license": "MIT", "engines": {"node": ">=18"},
              "scripts": {"start": "node server.mjs", "test": "node --test --test-concurrency=2 " + " ".join(["tests/standalone-boundary.test.mjs", *unit_tests])}}
    if profile == "microscopy-core":
        result["scripts"].update({"inspect": "node tools/researcher_inspector.mjs", "test:science": "node tests/standalone-science-smoke.mjs"})
    return json_bytes(result)


def plan(repo, source_ref, recipe_ref="HEAD"):
    source, recipe = Snapshot(repo, source_ref), Snapshot(repo, recipe_ref)
    manifest_raw, _, manifest_oid = recipe.read(MANIFEST_PATH)
    config = json.loads(manifest_raw)
    if config.get("schema_version") != 1 or set(config.get("profiles", {})) != {"microscopy-core", "mcp-dm"}:
        raise SplitError("Unsupported ownership manifest")
    for label, pinned in config.get("acceptance_inputs", {}).items():
        if not HEX.fullmatch(pinned):
            raise SplitError("Invalid acceptance commit pin: " + label)
        source.git("merge-base", "--is-ancestor", pinned, source.sha)
    products, inventories = {}, {}
    for profile, spec in config["profiles"].items():
        if not isinstance(spec, dict) or any(not isinstance(spec.get(key), list) or not all(isinstance(v, str) for v in spec[key]) for key in ("include", "required", "unit_tests")) or not isinstance(spec.get("templates"), dict):
            raise SplitError("Invalid profile declaration: " + profile)
        if any(not re.fullmatch(r"tests/[A-Za-z0-9_./-]+\.mjs", name) for name in spec["unit_tests"]):
            raise SplitError("Unsafe test command path")
        files = {}
        required = set(spec["required"])
        selected = sorted(p for p in source.files if matches(p, spec["include"]) and not matches(p, spec.get("exclude", [])))
        if not required.issubset(selected):
            raise SplitError("Source lacks required reviewed features: " + ", ".join(sorted(required - set(selected))) + ". Integrate the entry and GUI PRs in an isolated branch first.")
        for name in selected:
            admit_file(name)
            raw, mode, oid = source.read(name)
            files[name] = (raw, mode, {"commit": source.sha, "path": name, "git_blob": oid, "kind": "copied"})
        for destination, original in spec.get("source_map", {}).items():
            admit_file(destination)
            admit_file(original)
            raw, mode, oid = source.read(original)
            files[destination] = (raw, mode, {"commit": source.sha, "path": original, "git_blob": oid, "kind": "copied"})
        for destination, template in spec["templates"].items():
            admit_file(destination)
            admit_file(template)
            raw, mode, oid = recipe.read(template)
            files[destination] = (raw, mode, {"commit": recipe.sha, "path": template, "git_blob": oid, "kind": "template"})
        if spec.get("launcher_adaptation"):
            if profile != "microscopy-core":
                raise SplitError("Only the independent core has a panel launcher adaptation")
            adapter_path = safe_path(spec["launcher_adaptation"])
            adapter_raw, _, adapter_oid = recipe.read(adapter_path)
            adapter = json.loads(adapter_raw)
            target = "tools/image_panel.mjs"
            if target not in files:
                raise SplitError("Panel launcher missing from source snapshot")
            raw, mode, origin = files[target]
            changed, applied = adapt_launcher(raw, adapter)
            files[target] = (changed, mode, {**origin, "kind": "adapted" if applied else origin["kind"],
                "launcher_adaptation": {"commit": recipe.sha, "path": adapter_path, "git_blob": adapter_oid, "applied": applied}})
        files["package.json"] = (package(profile, spec["unit_tests"]), "100644", {"commit": recipe.sha, "path": "tools/prepare_repository_split.py", "kind": "generated"})
        audit(profile, files)
        # Validate every selected test exists, without silently dropping old tests.
        for name in ["tests/standalone-boundary.test.mjs", *spec["unit_tests"]]:
            if name not in files:
                raise SplitError("Selected standalone test missing: " + name)
        inventory = [{"path": p, "mode": mode, "sha256": hashlib.sha256(raw).hexdigest(), "source": origin} for p, (raw, mode, origin) in sorted(files.items())]
        inventories[profile] = inventory
        products[profile] = files
    receipt = {"schema_version": 1, "source_repository": "wuchqwq/mcp-dm", "source_commit": source.sha, "recipe_commit": recipe.sha,
               "ownership_manifest_git_blob": manifest_oid, "profiles": inventories,
               "source_tree": source.git("rev-parse", source.sha + "^{tree}").decode().strip(),
               "acceptance_inputs": config.get("acceptance_inputs", {}),
               "scope": "Source-bound migration candidates, not completed installation, host qualification or repository publication. Numerical kernels copied unchanged; the exact-match panel launcher adaptation is separately recorded. Original repository is retained for history."}
    return products, receipt


def export(repo, source_ref, recipe_ref, destination):
    destination = Path(os.path.abspath(destination))
    repo = Snapshot(repo, source_ref).repo
    if destination.exists() or destination.is_symlink():
        raise SplitError("Destination must not exist; nothing will be overwritten")
    if not destination.parent.is_dir() or destination.parent.resolve() != destination.parent:
        raise SplitError("Use an existing, non-symlinked absolute parent directory")
    if destination == repo or repo in destination.parents:
        raise SplitError("Export outside the source checkout; do not mix code and generated candidates")
    products, receipt = plan(repo, source_ref, recipe_ref)
    with tempfile.TemporaryDirectory(prefix=".split-staging-", dir=destination.parent) as temporary:
        staging = Path(temporary)
        for profile, files in products.items():
            for name, (raw, mode, _origin) in files.items():
                path = staging / profile / name
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("xb") as stream:
                    stream.write(raw)
                path.chmod(0o755 if mode == "100755" else 0o644)
            (staging / profile / "MIGRATION_MANIFEST.json").write_bytes(json_bytes({**{k: v for k, v in receipt.items() if k != "profiles"}, "profile": profile, "files": receipt["profiles"][profile]}))
        # Exclusive reservation protects even an empty directory created meanwhile.
        destination.mkdir()
        incomplete = destination / "INCOMPLETE.txt"
        incomplete.write_text("Do not use until split-manifest.json exists and this marker is absent.\n")
        try:
            for profile in sorted(products):
                os.rename(staging / profile, destination / profile)
            with (destination / "split-manifest.json").open("xb") as stream:
                stream.write(json_bytes(receipt))
            incomplete.unlink()
        except Exception:
            # Keep explicit incomplete evidence. Never broadly delete user paths.
            raise
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--source-ref", required=True, help="Full immutable commit SHA (or HEAD) containing the accepted entry and GUI code")
    parser.add_argument("--recipe-ref", default="HEAD", help="Commit containing this migration recipe; full SHA or HEAD")
    parser.add_argument("--output", help="New directory outside the source checkout; parent must already exist")
    parser.add_argument("--check", action="store_true", help="Audit committed inputs and print inventory counts without writing")
    args = parser.parse_args(argv)
    try:
        if args.check:
            _, receipt = plan(args.repo, args.source_ref, args.recipe_ref)
        elif args.output:
            receipt = export(args.repo, args.source_ref, args.recipe_ref, args.output)
        else:
            parser.error("Choose --check or --output")
        print(json.dumps({"source_commit": receipt["source_commit"], "recipe_commit": receipt["recipe_commit"],
                          "files": {key: len(value) for key, value in receipt["profiles"].items()}, "checked": True, "written": not args.check}, indent=2))
        return 0
    except (SplitError, OSError, ValueError, SyntaxError) as error:
        print("Migration refused: " + str(error), file=__import__("sys").stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
