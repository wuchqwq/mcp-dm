"""T3 busy test: measure what an external request does while a Python script occupies
the host main thread.

Sequence: wait for the plugin pipe, send a baseline request, wait for py_started.txt,
send a request while the script is running, then one after py_done.txt.
"""

import os
import time

PIPE = r"\\.\pipe\dm_nb_probe"
MARK = r"C:\dmtest"


def send(line, timeout=40.0):
    start = time.perf_counter()
    try:
        f = open(PIPE, "r+b", buffering=0)
    except OSError as exc:
        return None, "CONNECT_FAILED %s" % exc
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
        return (time.perf_counter() - start) * 1000.0, buf.decode("ascii", "replace").strip()
    finally:
        try:
            f.close()
        except OSError:
            pass


def wait_file(name, timeout):
    path = os.path.join(MARK, name)
    end = time.time() + timeout
    while time.time() < end:
        if os.path.exists(path):
            return True
        time.sleep(0.05)
    return False


def wait_pipe(timeout=180.0):
    end = time.time() + timeout
    while time.time() < end:
        if os.path.exists(PIPE):
            return True
        time.sleep(0.1)
    return False


def main():
    ok = wait_pipe()
    print("pipe ready    %s" % ("yes" if ok else "TIMEOUT"))
    if not ok:
        return 1

    ms, reply = send("PING 101")
    print("baseline      %8.2f ms  %s" % (ms if ms is not None else -1, reply))

    started = wait_file("py_started.txt", 120.0)
    print("py_started    %s" % ("seen" if started else "TIMEOUT"))

    if started:
        ms, reply = send("PING 102")
        print("during-script %8.2f ms  %s" % (ms if ms is not None else -1, reply))

    done = wait_file("py_done.txt", 60.0)
    print("py_done       %s" % ("seen" if done else "TIMEOUT"))

    ms, reply = send("PING 103")
    print("after-script  %8.2f ms  %s" % (ms if ms is not None else -1, reply))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
