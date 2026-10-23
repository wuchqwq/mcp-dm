"""Explicitly stop only this experimental IPC session; never closes DM.

Uses the bounded Win32 client also exercised by the offline transport tests.
STOP acknowledgement alone is not proof of all host cleanup postconditions.
"""
import argparse
import json
import os
import re
from test_transport import Pipe

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--session", default=os.environ.get("DM_NATIVE_SESSION"))
parser.add_argument("--request-id", required=True)
parser.add_argument("--evidence", help="Optional new private JSON file")
args = parser.parse_args()
if not args.session or not re.fullmatch(r"[0-9a-f]{32}", args.session):
    parser.error("session must be exactly 32 lowercase hexadecimal characters")
if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", args.request_id):
    parser.error("request-id must be bounded ASCII")
with Pipe(args.session, timeout=3) as pipe:
    pipe.io(("NB1 %s %s STOP\n" % (args.session, args.request_id)).encode("ascii"))
    reply = pipe.read_reply()
if args.evidence:
    with open(args.evidence, "x", encoding="utf-8") as file:
        json.dump(reply, file, indent=2, allow_nan=False)
if (reply.get("protocol") != "NB1" or reply.get("session") != args.session
        or reply.get("id") != args.request_id or reply.get("state") != "completed"
        or reply.get("result") != {"ipc_stopped": True}):
    raise SystemExit("FAIL: STOP was not acknowledged: " + json.dumps(reply))
def uint(value, minimum=0, maximum=0xffffffff):
    return type(value) is int and minimum <= value <= maximum
timings = reply.get("timings_us")
if (not uint(reply.get("host_pid"), 1) or not uint(reply.get("worker_tid"), 1)
        or not uint(reply.get("exec_tid")) or reply["exec_tid"] != 0
        or not isinstance(timings, dict)
        or not all(uint(timings.get(key), 0, (1 << 53) - 1) for key in ("queue", "execute"))
        or "error" in reply or "code" in reply):
    raise SystemExit("FAIL: malformed STOP receipt: " + json.dumps(reply))
print("STOP acknowledged for the explicit session; DM remains open. " +
      "Allow its host cleanup callback to finish before closing DM normally.")
