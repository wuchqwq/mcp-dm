"""External client for the nb_probe plugin. Standard library only.

Usage:
    python nb_client.py ping             # one request
    python nb_client.py ping 10          # ten sequential requests
    python nb_client.py bad              # malformed request
    python nb_client.py stop             # ask the plugin to stop serving
"""

import os
import sys
import time

PIPE = r"\\.\pipe\dm_nb_probe"


def send(line, timeout=5.0):
    """Open the pipe, send one line, read one reply. Returns (elapsed_ms, reply)."""
    start = time.perf_counter()
    try:
        f = open(PIPE, "r+b", buffering=0)
    except OSError as exc:
        return None, "CONNECT_FAILED: %s" % exc
    try:
        f.write((line + "\n").encode("ascii"))
        buf = b""
        deadline = time.time() + timeout
        while time.time() < deadline:
            chunk = f.read(1)
            if not chunk:
                break
            buf += chunk
            if chunk == b"\n":
                break
        elapsed = (time.perf_counter() - start) * 1000.0
        return elapsed, buf.decode("ascii", "replace").strip()
    finally:
        try:
            f.close()
        except OSError:
            pass


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    cmd = sys.argv[1]

    if cmd == "ping":
        count = int(sys.argv[2]) if len(sys.argv) > 2 else 1
        for i in range(1, count + 1):
            ms, reply = send("PING %d" % i)
            print("%8.2f ms  %s" % (ms if ms is not None else -1.0, reply))
            time.sleep(0.05)
        return 0

    if cmd == "bad":
        ms, reply = send("HELLO there")
        print("%8.2f ms  %s" % (ms if ms is not None else -1.0, reply))
        return 0

    if cmd == "stat":
        idfile = r"C://dmtest//img_id.txt"
        imgid = sys.argv[2] if len(sys.argv) > 2 else None
        if imgid is None:
            if not os.path.exists(idfile):
                print("no image id file")
                return 2
            imgid = open(idfile, "r", encoding="utf-8").read().strip()
        ms, reply = send("STAT 201 %s" % imgid, timeout=30.0)
        print("%8.2f ms  %s" % (ms if ms is not None else -1.0, reply))
        return 0

    if cmd == "stop":
        ms, reply = send("STOP")
        print("%8.2f ms  %s" % (ms if ms is not None else -1.0, reply))
        return 0

    print("unknown command")
    return 2


if __name__ == "__main__":
    sys.exit(main())
