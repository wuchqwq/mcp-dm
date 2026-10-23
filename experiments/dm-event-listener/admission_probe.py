#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Finite, isolated host-admission experiment; no DM Python APIs or images.

Prepare outside DM; execute the three generated DM-Script files in order.
This is an admission measurement, not a global Python-slot status API.
"""
import argparse
import json
from pathlib import Path
import time
import uuid


def save(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, indent=2)


def prepare(root):
    root = Path(root).resolve()
    # DM-Script literals are deliberately restricted, not user code interpolation.
    path = root.as_posix()
    if any(ord(c) < 32 or ord(c) > 126 or c == '"' for c in path):
        raise ValueError("Use an ASCII directory without quotes/control characters")
    root.mkdir(exist_ok=False)
    token = uuid.uuid4().hex
    save(root / "session.json", {"token": token, "hold_seconds": 10,
                                "prepared_at": time.time()})
    header = ("import json, os, threading, time\nfrom pathlib import Path\n"
              "root = Path(%r)\ntoken = %r\n"
              "def mark(name):\n"
              "    with (root / (name + '.json')).open('x') as f:\n"
              "        json.dump(dict(token=token, pid=os.getpid(), "
              "thread=threading.get_ident(), time=time.time()), f)\n") % (str(root), token)
    for phase in ("idle", "overlap", "after"):
        (root / (phase + ".py")).write_text(
            header + "mark(%r)\nmark(%r)\n" %
            (phase + "_entered", phase + "_finished"), encoding="utf-8")
    (root / "bounded_busy.py").write_text(
        header + "mark('busy_started')\ntry:\n    time.sleep(10)\n"
        "finally:\n    mark('busy_finished')\n", encoding="utf-8")

    def native_mark(name):
        return ('number f = CreateFileForWriting("%s/%s.marker")\n'
                'WriteFile(f, "%s")\nCloseFile(f)\n') % (path, name, token)

    def attempt(phase):
        return ('{\n' + native_mark(phase + "_before") + '}\ntry\n{\n'
                'ExecutePythonScriptFile("%s/%s.py", 0)\n}\ncatch\n{\n' % (path, phase)
                + native_mark(phase + "_caught") + 'break\n}\n{\n'
                + native_mark(phase + "_returned") + '}\n')

    def one_shot(phase):
        return ('if (DoesFileExist("%s/%s_attempted.marker")) '
                'Throw("Already attempted; inspect receipts, do not retry")\n{\n'
                % (path, phase) + native_mark(phase + "_attempted") + '}\n')

    (root / "01_idle.s").write_text(one_shot("idle") + attempt("idle"), encoding="utf-8")
    (root / "02_overlap.s").write_text(
        one_shot("overlap") +
        'if (!DoesFileExist("%s/idle_finished.json")) Throw("Run idle first")\n'
        'ExecutePythonScriptFile("%s/bounded_busy.py", 1)\nSleep(0.3)\n'
        'if (!DoesFileExist("%s/busy_started.json") || '
        'DoesFileExist("%s/busy_finished.json")) Throw("No measured overlap")\n'
        % (path, path, path, path) + attempt("overlap"), encoding="utf-8")
    (root / "03_after.s").write_text(
        one_shot("after") +
        'if (!DoesFileExist("%s/busy_finished.json")) Throw("Busy script still running")\n'
        % path + attempt("after"), encoding="utf-8")
    return {"state": "prepared_not_executed", "directory": str(root), "token": token}


def verify(root):
    root = Path(root)
    session = json.loads((root / "session.json").read_text())
    token = session["token"]

    def record(name):
        p = root / (name + ".json")
        if not p.exists():
            return None
        data = json.loads(p.read_text())
        if data["token"] != token:
            raise ValueError("Receipt session mismatch")
        return data

    def marker(name):
        p = root / (name + ".marker")
        if not p.exists():
            return False
        if p.read_text() != token:
            raise ValueError("Native receipt session mismatch")
        return True

    checks = {}
    for phase in ("idle", "after"):
        entered, finished = record(phase + "_entered"), record(phase + "_finished")
        checks[phase + "_admitted"] = bool(entered and finished and
            marker(phase + "_before") and marker(phase + "_returned") and
            not marker(phase + "_caught") and finished["time"] >= entered["time"])
    started, finished = record("busy_started"), record("busy_finished")
    entered, ended = record("overlap_entered"), record("overlap_finished")
    checks["bounded_busy_finished"] = bool(started and finished and
        finished["time"] - started["time"] >= session["hold_seconds"] - 0.05)
    checks["same_host"] = bool(started and finished and
        all(record(n) and record(n)["pid"] == started["pid"] for n in
            ("idle_entered", "idle_finished", "busy_finished", "after_entered",
             "after_finished")) and
        all(r["pid"] == started["pid"] for r in (entered, ended) if r))
    checks["measured_overlap"] = bool(started and finished and
        marker("overlap_before") and started["time"] <=
        (root / "overlap_before.marker").stat().st_mtime < finished["time"])
    checks["normal_phase_order"] = bool(started and finished and
        record("idle_finished") and record("after_entered") and
        record("idle_finished")["time"] <= started["time"] and
        finished["time"] <= record("after_entered")["time"])
    if not checks["measured_overlap"]:
        overlap = "unknown"
    elif marker("overlap_caught") and not entered and marker("overlap_returned"):
        overlap = "rejected_catchable"  # Not every caught exception means busy.
    elif (entered and ended and finished and marker("overlap_returned") and
          not marker("overlap_caught") and
          (root / "overlap_before.marker").stat().st_mtime <= entered["time"] <= ended["time"]):
        overlap = ("entered_while_busy" if entered["time"] < finished["time"]
                   else "deferred_until_free")
    else:
        overlap = "unknown"
    return {"checks": checks, "overlap_outcome": overlap,
            "observations": {"overlap_call_returned": marker("overlap_returned"),
                             "overlap_exception_caught": marker("overlap_caught"),
                             "overlap_python_entered": bool(entered),
                             "overlap_python_finished": bool(ended)},
            "catch_based_busy_detection": (
                "FAIL_unacknowledged_return_during_overlap" if
                checks["measured_overlap"] and marker("overlap_returned") and
                not marker("overlap_caught") and not entered else "NOT_ESTABLISHED"),
            "global_busy_query": "NOT_TESTED_no_documented_query_identified",
            "external_wake": "NOT_TESTED_this_uses_GUI_execution",
            "scientific_data_touched": False,
            "status": "PASS" if all(checks.values()) and overlap != "unknown" else "INCOMPLETE"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "verify"))
    parser.add_argument("directory")
    args = parser.parse_args()
    result = prepare(args.directory) if args.action == "prepare" else verify(args.directory)
    print(json.dumps(result, sort_keys=True, indent=2))
    if args.action == "verify" and result["status"] != "PASS":
        raise SystemExit(1)
