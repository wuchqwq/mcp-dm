#!/usr/bin/env python
"""Independent, read-only receipt checks. No DigitalMicrograph import or launch.

Verifies the synthetic C1 lifecycle. Does not certify automatic external wake,
UI latency, concurrent user-script admission, other GMS versions or MCP tools.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np


def read(path):
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def verify(root):
    root = Path(root)
    registered = read(root / "registered.json")
    completed = read(root / "registration_complete.json")
    lifecycle = read(root / "lifecycle.json")
    second = read(root / "second_script.json")
    removed = read(root / "unregistered.json")
    clean = read(root / "cleanup_verified.json")
    released = read(root / "released.json")
    events = [json.loads(line) for line in (root / "events.ndjson").read_text(encoding="utf-8").splitlines()]
    checks = []

    def check(name, condition):
        checks.append({"check": name, "status": "PASS" if condition else "FAIL"})

    check("real-host scope on every lifecycle artifact", all(
        r.get("scope") == "real_dm" for r in (registered, completed, second, removed, clean, released)))
    check("registration fully completed without failure artifact",
          completed["state"] == "registered" and not (root / "registration_failure.json").exists())
    code_hash = hashlib.sha256(Path(__file__).with_name("probe.py").read_bytes()).hexdigest()
    check("loaded source matches current probe", completed["probe_code_sha256"] == registered["probe_code_sha256"] == code_hash)
    check("separate Python execution completed in same host", second["sum_0_through_10"] == 55
          and second["listener_present"] is True and second["host_pid"] == registered["host_pid"])
    # Enumerated oracle, independent of np.indices used by the host generator.
    expected = np.array([[10 * y + x for x in range(12)] for y in range(8)], dtype=np.float32)
    expected_hash = hashlib.sha256(expected.tobytes()).hexdigest()
    check("created source equals complete independently enumerated ramp", registered["source_sha256"] == expected_hash)
    replies = []
    for path in sorted((root / "replies").glob("*.json")):
        reply = read(path)
        request = read(root / "requests" / (reply["id"] + ".json"))
        digest = hashlib.sha256(json.dumps(request, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        result = reply["result"]
        identity = (reply["state"] == "completed" and reply["scope"] == "real_dm"
                    and reply["token"] == registered["token"] == request["token"]
                    and reply["host_pid"] == registered["host_pid"]
                    and reply["id"] == request["id"]
                    and reply["request_sha256"] == digest
                    and result["echo_nonce"] == request["nonce"]
                    and result["source_image_id"] == registered["source_id"])
        check("reply identity/nonce/parameter binding: " + reply["phase"], identity)
        check("complete ramp, arithmetic and signed calibration: " + reply["phase"],
              result["source_sha256"] == expected_hash and result["shape_yx"] == [8, 12]
              and result["dtype"] == "float32" and result["sum"] == 3888
              and result["mean"] == 40.5 and result["min"] == 0 and result["max"] == 81
              and result["calibration_xy"] == [[1.25, -0.25, "nm"], [-2.5, 0.5, "nm"]])
        replies.append(reply)
    for phase in ("after_return", "after_second", "external"):
        check("matching lifecycle reply: " + phase, sum(r["phase"] == phase for r in replies) == 1)
    callbacks = [e for e in events if e["event"] == "callback"]
    check("no logged callback errors/rejections", not any("error" in e or "rejected" in e for e in events))
    check("callbacks on known registration main thread", registered["registration_on_main_thread"] is True
          and bool(callbacks) and all(e["thread"] == registered["registration_thread"] for e in callbacks))
    by_id = dict((e.get("request_id"), e) for e in callbacks)
    before = by_id.get(lifecycle["after_return"], {}).get("time", float("inf"))
    after = by_id.get(lifecycle["after_second"], {}).get("time", float("-inf"))
    second_time = (root / "second_script.json").stat().st_mtime
    check("independent events bracket second normal Python script", before < second_time < after)
    check("unregister released native/Python listener references", removed["listener_still_alive"] is False)
    check("no residual callbacks after actual post-removal trigger", clean["state"] == "verified"
          and clean["callback_count"] == removed["callback_count"] == len(callbacks)
          and not (root / "replies" / (lifecycle["after_cleanup"] + ".json")).exists())
    check("owned documents released", released["state"] == "released")
    return {"status": "PASS" if all(c["status"] == "PASS" for c in checks) else "FAIL",
            "scope": "independent read-only real-host receipt/numerical verification",
            "checks": checks, "callback_duration_ms": [e["duration_ms"] for e in callbacks],
            "automatic_external_wake": "NOT_TESTED_BY_THIS_VERIFIER",
            "concurrent_user_script_and_ui_latency": "NOT_TESTED"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session_dir")
    args = parser.parse_args()
    try:
        result = verify(args.session_dir)
    except Exception as exc:
        result = {"status": "FAIL", "error": "%s: %s" % (type(exc).__name__, exc)}
    print(json.dumps(result, sort_keys=True, indent=2, allow_nan=False))
    sys.exit(0 if result["status"] == "PASS" else 1)
