#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Private, bounded native-periodic experiment. Never launches DM or scripts."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import time
import uuid

HERE = Path(__file__).resolve().parent
OPS = ("ping", "stats", "fail")
LIMIT = 32


def identifier(value):
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{32}", value) is None:
        raise ValueError("Expected lowercase 32-character hex identity")
    return value


def save(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)


def read(path):
    with Path(path).open("rb") as stream:
        data = stream.read(16385)
    if len(data) > 16384:
        raise ValueError("Receipt exceeds budget")
    return json.loads(data.decode("utf-8"))


def atomic_publish(temporary, destination):
    # Same-directory hard link exposes a fully closed file atomically, and fails
    # if destination exists on Windows AND POSIX. No rename-overwrite race.
    os.link(str(temporary), str(destination))
    Path(temporary).unlink()


def ordinary_script(root, filename="02_ordinary_python.py"):
    root = Path(root).resolve()
    session = read(root / "session.json")
    token = identifier(session["token"])
    path = root.as_posix()
    if any(ord(c) < 32 or ord(c) > 126 or c == '"' for c in path):
        raise ValueError("Unsafe DM-Script path")
    if filename not in ("02_ordinary_python.py", "02b_host_checked_python.py", "02c_verified_host_python.py"):
        raise ValueError("Only fixed experiment script names")
    native = ('object task = GetScriptObjectFromID(OBJECT_ID)\n'
              'if (!task.ScriptObjectIsValid()) Throw("Native task not present in this host")\n'
              'number major, minor, build\nGetApplicationVersion(major,minor,build)\n'
              'string p = "%s/ordinary_native_proof.json"\n'
              'if (DoesFileExist(p)) Throw("Host proof already exists")\n'
              'number f=CreateFileForWriting(p)\n'
              'WriteFile(f,"{\\"token\\":\\"%s\\",\\"object_id\\":OBJECT_ID,\\"version\\":["+major+","+minor+","+build+"],\\"object_valid\\":1}")\n'
              'CloseFile(f)\n') % (path, token)
    code = ("import json, os, threading, time\nfrom pathlib import Path\n"
            "import DigitalMicrograph as DM\n"
            "if not DM.IsScriptOnMainThread(): raise RuntimeError('Run on DM foreground')\n"
            "root=Path(%r)\n"
            "binding=json.loads((root/'host_binding.json').read_text())\n"
            "if os.getpid()!=binding['expected_host_pid']: raise RuntimeError('Not the bound DM process')\n"
            "registration=json.loads((root/'registered.json').read_text())\n"
            "if registration['token'] != %r: raise RuntimeError('Wrong session')\n"
            "identity=registration['object_id']\n"
            "if isinstance(identity,bool) or not isinstance(identity,int) or identity<0: raise RuntimeError('Bad native object ID')\n"
            "DM.ExecuteScriptString(%r.replace('OBJECT_ID',str(identity)))\n"
            "with (root/'ordinary_host_checked.json').open('x') as f:\n"
            "    json.dump(dict(token=%r,pid=os.getpid(),thread=threading.get_ident(),"
            "sum_0_to_10=sum(range(11)),time=time.time(),host_checked=True),f)\n") % (
                str(root), token, native, token)
    with (root / filename).open("x", encoding="utf-8") as stream:
        stream.write(code)
    return {"state": "prepared_not_executed", "script": str(root / filename)}


def bind_host(root, expected_host_pid):
    if isinstance(expected_host_pid, bool) or not isinstance(expected_host_pid, int) or expected_host_pid <= 0:
        raise ValueError("Expected an observed, existing DM PID")
    session = read(Path(root) / "session.json")
    save(Path(root) / "host_binding.json", dict(token=session["token"], expected_host_pid=expected_host_pid))


def prepare(root, ttl=600):
    root = Path(root).resolve()
    path = root.as_posix()
    if not 10 <= ttl <= 600 or isinstance(ttl, bool):
        raise ValueError("TTL must be 10..600 seconds")
    if any(ord(c) < 32 or ord(c) > 126 or c == '"' for c in path):
        raise ValueError("Use an ASCII private directory without quotes")
    root.mkdir(parents=True, exist_ok=False)
    (root / "issued").mkdir()
    token = uuid.uuid4().hex
    template = (HERE / "task.s.in").read_text(encoding="utf-8")
    template_sha = hashlib.sha256(template.encode("utf-8")).hexdigest()
    script = template
    for key, value in {"ROOT": path, "TOKEN": token, "CLASS": token[:12],
                       "TTL": str(ttl), "MAXTICKS": str(ttl * 2 + 4),
                       "SHA": template_sha}.items():
        script = script.replace("@" + key + "@", value)
    (root / "01_register.s").write_text(script, encoding="utf-8")
    save(root / "session.json", dict(token=token, ttl_seconds=ttl,
         template_sha256=template_sha,
         register_sha256=hashlib.sha256(script.encode("utf-8")).hexdigest(),
         created_at=time.time()))
    ordinary_script(root)
    return {"state": "prepared_not_registered", "directory": str(root), "token": token}


def reserve(root, operation, request_id=None):
    root = Path(root)
    if operation not in OPS:
        raise ValueError("Only fixed operations are supported")
    session = read(root / "session.json")
    if (root / "stopped.json").exists():
        raise RuntimeError("Task stopped; no new submission")
    request_id = identifier(request_id or uuid.uuid4().hex)
    body = (identifier(session["token"]) + "|" + request_id + "|" +
            operation.ljust(8)).ljust(128).encode("ascii")
    for slot in range(LIMIT):
        receipt = dict(token=session["token"], request_id=request_id, slot=slot,
                       operation=operation, request_sha256=hashlib.sha256(body).hexdigest(),
                       reserved_at=time.time())
        try:
            save(root / "issued" / (str(slot) + ".json"), receipt)
        except FileExistsError:
            continue
        temporary = root / ("request_%d.pending" % slot)
        with temporary.open("xb") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        return dict(receipt, state="reserved_not_published")
    raise RuntimeError("Bounded experiment request limit reached")


def publish(root, slot):
    root = Path(root)
    issued = read(root / "issued" / (str(slot) + ".json"))
    temporary = root / ("request_%d.pending" % slot)
    if hashlib.sha256(temporary.read_bytes()).hexdigest() != issued["request_sha256"]:
        raise ValueError("Staged input changed")
    atomic_publish(temporary, root / ("request_%d.ready" % slot))
    return dict(issued, state="published_outcome_unknown")


def query(root, slot):
    root = Path(root)
    issued = read(root / "issued" / (str(slot) + ".json"))
    result = root / ("reply_%d.json" % slot)
    if not result.exists():
        return dict(issued, state="unknown", reason="no_completed_receipt_do_not_retry")
    try:
        reply = read(result)
        for key in ("token", "request_id", "slot"):
            if reply[key] != issued[key]:
                raise ValueError("Reply identity mismatch")
        if reply["state"] not in ("success", "failed", "unknown"):
            raise ValueError("Invalid completion state")
        return reply
    except (ValueError, KeyError, UnicodeError):
        return dict(issued, state="unknown", reason="invalid_reply_do_not_retry")


def stop(root):
    root = Path(root)
    temporary = root / "stop.pending"
    with temporary.open("xb") as stream:
        stream.write(read(root / "session.json")["token"].encode("ascii"))
        stream.flush()
        os.fsync(stream.fileno())
    atomic_publish(temporary, root / "stop.ready")
    return {"state": "stop_requested_not_proof_of_stopped"}


def cleanup_check(root):
    root = Path(root).resolve()
    session = read(root / "session.json")
    registered = read(root / "registered.json")
    if registered["token"] != session["token"]:
        raise ValueError("Registration identity mismatch")
    object_id = registered["object_id"]
    if isinstance(object_id, bool) or not isinstance(object_id, int) or object_id < 0:
        raise ValueError("Invalid native object identity")
    destination = root / "cleanup_check.json"
    # Original directory already passed strict DM-Script path validation.
    script = ('object retained = GetScriptObjectFromID(%d)\n'
              'number valid = retained.ScriptObjectIsValid()\n'
              'if (DoesFileExist("%s")) Throw("Cleanup already checked")\n'
              'number f = CreateFileForWriting("%s")\n'
              'WriteFile(f, "{\\"token\\":\\"%s\\",\\"object_id\\":%d,\\"object_valid\\":"+valid+"}")\n'
              'CloseFile(f)\nResult("Native periodic object validity: "+valid+"\\n")\n') % (
                  object_id, destination.as_posix(), destination.as_posix(), session["token"], object_id)
    with (root / "03_check_removed.s").open("x", encoding="utf-8") as stream:
        stream.write(script)
    return {"state": "prepared_not_executed", "script": str(root / "03_check_removed.s")}


def verify(root):
    root = Path(root)
    session = read(root / "session.json")
    registration = read(root / "registered.json") if (root / "registered.json").exists() else {}
    checks = {"registered": registration.get("token") == session["token"],
              "loaded_template_identity": registration.get("source_template_sha256") == session["template_sha256"]}
    issued_files = sorted((root / "issued").glob("*.json"), key=lambda p: int(p.stem))
    replies = [query(root, int(p.stem)) for p in issued_files]
    checks["all_requests_have_terminal_receipts"] = bool(replies) and all(
        r["state"] in ("success", "failed") for r in replies)
    checks["reply_slots_exact"] = {p.name for p in root.glob("reply_*.json")} == {
        "reply_%s.json" % p.stem for p in issued_files}
    seen = set()
    expected_executions = 0
    accounting = bool(replies)
    for p, reply in zip(issued_files, replies):
        issued = read(p)
        duplicate = issued["request_id"] in seen
        seen.add(issued["request_id"])
        expected_code = "duplicate_request_id" if duplicate else {
            "ping": "pong", "stats": "stats", "fail": "intentional_failure"}[issued["operation"]]
        expected_state = "failed" if duplicate or issued["operation"] == "fail" else "success"
        if expected_state == "success": expected_executions += 1
        accounting = accounting and (reply.get("code"), reply["state"], reply.get("executions")) == (
            expected_code, expected_state, expected_executions)
    checks["exact_execution_accounting"] = accounting
    stats = [r for r in replies if r.get("code") == "stats" and r["state"] == "success"]
    expected = dict(shape_yx=[8, 12], dtype="float32", zero_xy=[1.25, -2.5],
                    scale_xy=[-0.25, 0.5], units_xy=["nm", "nm"],
                    rect_xyxy=[2, 1, 7, 5], count=20,
                    sum=sum(10*y+x for y in range(1, 5) for x in range(2, 7)),
                    mean=29, min=12, max=46)
    checks["independent_stats_oracle"] = bool(stats) and all(
        all(r.get(k) == v for k, v in expected.items()) for r in stats)
    ordinary_path = root / "ordinary_host_checked.json"
    ordinary = read(ordinary_path) if ordinary_path.exists() else {}
    proof = read(root / "ordinary_native_proof.json") if (root / "ordinary_native_proof.json").exists() else {}
    binding = read(root / "host_binding.json") if (root / "host_binding.json").exists() else {}
    checks["ordinary_python_completed"] = (ordinary.get("token") == session["token"] and
        ordinary.get("sum_0_to_10") == 55 and ordinary.get("host_checked") is True and
        proof.get("token") == session["token"] and proof.get("object_id") == registration.get("object_id") and
        proof.get("object_valid") == 1 and proof.get("version") == registration.get("version") and
        binding.get("token") == session["token"] and ordinary.get("pid") == binding.get("expected_host_pid") and
        isinstance(ordinary.get("pid"), int))
    pong_paths = [root / ("reply_%d.json" % r["slot"]) for r in replies if r.get("code") == "pong"]
    checks["native_roundtrips_around_python"] = bool(ordinary and len(pong_paths) >= 2 and
        min(p.stat().st_mtime for p in pong_paths) <= ordinary_path.stat().st_mtime <=
        max(p.stat().st_mtime for p in pong_paths))
    stopped = read(root / "stopped.json") if (root / "stopped.json").exists() else {}
    checks["stop_received"] = stopped.get("token") == session["token"]
    checks["final_slot_and_execution_counts"] = (bool(stopped) and
        stopped.get("processed_slots") == len(issued_files) and
        stopped.get("executions") == expected_executions)
    checks["source_preserved_and_owned_image_closed"] = bool(stats) and stopped.get("source_unchanged") == 1 and stopped.get("owned_image_closed") == 1
    removed = read(root / "cleanup_check.json") if (root / "cleanup_check.json").exists() else {}
    checks["native_task_object_released"] = bool(stopped) and removed.get("token") == session["token"] and removed.get("object_id") == registration.get("object_id") and removed.get("object_valid") == 0
    return {"checks": checks, "status": "PASS" if all(checks.values()) else "INCOMPLETE",
            "request_count": len(replies), "listener_busy": "NOT_TESTED_by_this_verifier"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "submit", "reserve", "publish", "query", "stop", "cleanup-check", "repair-coexist", "bind-host", "verify"))
    parser.add_argument("directory")
    parser.add_argument("--operation", choices=OPS, default="ping")
    parser.add_argument("--slot", type=int, default=0)
    parser.add_argument("--request-id")
    parser.add_argument("--ttl", type=int, default=600)
    parser.add_argument("--host-pid", type=int)
    args = parser.parse_args()
    if args.action == "prepare":
        result = prepare(args.directory, args.ttl)
        if args.host_pid is not None: bind_host(args.directory, args.host_pid)
    elif args.action in ("reserve", "submit"):
        result = reserve(args.directory, args.operation, args.request_id)
        if args.action == "submit": result = publish(args.directory, result["slot"])
    elif args.action == "publish": result = publish(args.directory, args.slot)
    elif args.action == "query": result = query(args.directory, args.slot)
    elif args.action == "stop": result = stop(args.directory)
    elif args.action == "cleanup-check": result = cleanup_check(args.directory)
    elif args.action == "repair-coexist": result = ordinary_script(args.directory, "02b_host_checked_python.py")
    elif args.action == "bind-host":
        bind_host(args.directory, args.host_pid)
        result = {"state": "bound_to_observed_existing_host_not_liveness_proof"}
    else: result = verify(args.directory)
    print(json.dumps(result, indent=2, sort_keys=True))
    if args.action == "verify" and result["status"] != "PASS": raise SystemExit(1)
