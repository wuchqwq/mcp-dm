"""Explicitly stop only this experimental IPC session; never closes DM.

The original request must be durably saved before any pipe is constructed.
Raw acknowledgement evidence alone does not qualify cleanup or ownership.
"""
import argparse
import json
import os
import re
from test_transport import Pipe


def uint(value, minimum=0, maximum=0xffffffff):
    return type(value) is int and minimum <= value <= maximum


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", default=os.environ.get("DM_NATIVE_SESSION"))
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--request-record", required=True, help="New private pre-submission request JSON")
    parser.add_argument("--expected-host-pid", required=True, type=int)
    parser.add_argument("--evidence", help="Optional new private raw receipt JSON")
    args = parser.parse_args()
    if not args.session or not re.fullmatch(r"[0-9a-f]{32}", args.session):
        parser.error("session must be exactly 32 lowercase hexadecimal characters")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", args.request_id):
        parser.error("request-id must be bounded ASCII")
    if not uint(args.expected_host_pid, 1):
        parser.error("expected-host-pid must be a positive uint32")
    request_path = os.path.abspath(args.request_record)
    evidence_path = os.path.abspath(args.evidence) if args.evidence else None
    if evidence_path and os.path.normcase(request_path) == os.path.normcase(evidence_path):
        parser.error("request-record and evidence must be distinct new files")
    if os.path.lexists(request_path):
        parser.error("request-record already exists; never reconstruct or overwrite an original STOP request")
    if evidence_path and os.path.lexists(evidence_path):
        parser.error("evidence already exists; no STOP was sent")
    wire = "NB2 %s %s STOP\n" % (args.session, args.request_id)
    request = {"protocol": "NB2", "session": args.session, "id": args.request_id,
               "op": "STOP", "args": [], "host_pid": args.expected_host_pid, "wire": wire}
    # Do not move Pipe construction above this exclusive write, flush, fsync
    # and close. A failed/partial save must leave the host untouched.
    with open(request_path, "x", encoding="utf-8") as file:
        json.dump(request, file, indent=2, allow_nan=False)
        file.flush()
        os.fsync(file.fileno())
    with Pipe(args.session, timeout=3) as pipe:
        pipe.io(wire.encode("ascii"))
        reply = pipe.read_reply()
    if evidence_path:
        with open(evidence_path, "x", encoding="utf-8") as file:
            json.dump(reply, file, indent=2, allow_nan=False)
    result = reply.get("result")
    if (reply.get("protocol") != "NB2" or reply.get("session") != args.session
            or reply.get("id") != args.request_id or reply.get("state") != "completed"
            or reply.get("original_operation") != "STOP" or reply.get("normalized_args") != []
            or reply.get("result_type") != "ipc_stop" or type(reply.get("result_version")) is not int or reply["result_version"] != 1
            or not isinstance(result, dict) or set(result) != {"ipc_stopped"}
            or result["ipc_stopped"] is not True):
        raise SystemExit("FAIL: STOP was not acknowledged: " + json.dumps(reply))
    timings = reply.get("timings_us")
    if (not uint(reply.get("host_pid"), 1) or reply["host_pid"] != args.expected_host_pid
            or not uint(reply.get("worker_tid"), 1) or not uint(reply.get("exec_tid"))
            or reply["exec_tid"] != 0 or not isinstance(timings, dict)
            or not all(uint(timings.get(key), 0, (1 << 53) - 1) for key in ("queue", "execute"))
            or "error" in reply or "code" in reply):
        raise SystemExit("FAIL: malformed or wrong-host STOP receipt: " + json.dumps(reply))
    print("STOP acknowledged for the saved original request; DM remains open. "
          "Allow its host cleanup callback to finish. This receipt alone does not qualify cleanup.")


if __name__ == "__main__":
    main()
