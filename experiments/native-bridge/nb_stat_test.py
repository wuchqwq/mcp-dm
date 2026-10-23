"""T4/T5: drive a native GMS call from an external request, idle and while Python runs.

The setup script starts asynchronously, creates the image, publishes its id, then waits for
go.txt. This client waits for the host to answer a PING, then triggers the busy window and
samples STAT before / during / after it.
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


def touch(name, text="1"):
    with open(os.path.join(MARK, name), "w", encoding="utf-8") as f:
        f.write(text)


def exists(name):
    return os.path.exists(os.path.join(MARK, name))


def wait(name, timeout):
    end = time.time() + timeout
    while time.time() < end:
        if exists(name):
            return True
        time.sleep(0.05)
    return False


def main():
    # 1) wait until the host actually answers (message pump alive)
    ok = False
    for i in range(240):
        ms, reply = send("PING 0", timeout=8.0)
        if reply.startswith("OK"):
            ok = True
            print("host ready    after %d probe(s): %s" % (i + 1, reply))
            break
        time.sleep(0.5)
    if not ok:
        print("host never answered")
        return 1

    # 2) wait for the setup script to publish the image id
    imgid = None
    for _ in range(400):
        p = os.path.join(MARK, "img_id.txt")
        if os.path.exists(p):
            imgid = open(p, encoding="utf-8").read().strip()
            if imgid:
                break
        time.sleep(0.1)
    print("image id      %s" % imgid)
    if not imgid:
        return 1

    ms, reply = send("STAT 301 %s" % imgid)
    print("idle          %8.2f ms  %s" % (ms if ms is not None else -1, reply))

    # 3) trigger the busy window, then sample inside it
    touch("go.txt")
    started = wait("py_started.txt", 30.0)
    print("py_started    %s" % ("seen" if started else "TIMEOUT"))

    if started:
        ms, reply = send("STAT 302 %s" % imgid)
        print("during-script %8.2f ms  %s" % (ms if ms is not None else -1, reply))

    done = wait("py_done.txt", 60.0)
    print("py_done       %s" % ("seen" if done else "TIMEOUT"))

    ms, reply = send("STAT 303 %s" % imgid)
    print("after-script  %8.2f ms  %s" % (ms if ms is not None else -1, reply))

    ms, reply = send("STAT 304 999999")
    print("bad-id        %8.2f ms  %s" % (ms if ms is not None else -1, reply))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
