"""Offline Windows real-pipe tests; fake_host never loads or controls DM.

Run: python -B experiments/native-bridge/mvp/test_transport.py --exe PATH
All subprocesses are explicitly synthetic and create private per-test sessions.
"""
import argparse
import ctypes
from ctypes import wintypes as w
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
import uuid

if os.name != "nt":
    raise SystemExit("Windows named-pipe integration tests require Windows")

k = ctypes.WinDLL("kernel32", use_last_error=True)
INVALID = ctypes.c_void_p(-1).value
class OVERLAPPED(ctypes.Structure):
    _fields_ = [("Internal", ctypes.c_size_t), ("InternalHigh", ctypes.c_size_t),
                ("Offset", w.DWORD), ("OffsetHigh", w.DWORD), ("hEvent", w.HANDLE)]

k.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, w.LPVOID, w.DWORD, w.DWORD, w.HANDLE]
k.CreateFileW.restype = w.HANDLE
k.CreateEventW.argtypes = [w.LPVOID, w.BOOL, w.BOOL, w.LPCWSTR]
k.CreateEventW.restype = w.HANDLE
k.ReadFile.argtypes = [w.HANDLE, w.LPVOID, w.DWORD, ctypes.POINTER(w.DWORD), ctypes.POINTER(OVERLAPPED)]
k.WriteFile.argtypes = k.ReadFile.argtypes
k.GetOverlappedResult.argtypes = [w.HANDLE, ctypes.POINTER(OVERLAPPED), ctypes.POINTER(w.DWORD), w.BOOL]
k.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
k.CancelIoEx.argtypes = [w.HANDLE, ctypes.POINTER(OVERLAPPED)]
k.CloseHandle.argtypes = [w.HANDLE]
k.WaitNamedPipeW.argtypes = [w.LPCWSTR, w.DWORD]

class Pipe:
    def __init__(self, session, timeout=2):
        name = r"\\.\pipe\dm_mcp_native_" + session
        deadline = time.monotonic() + timeout
        while True:
            self.h = k.CreateFileW(name, 0xC0000000, 0, None, 3, 0x40000000, None)
            if self.h != INVALID:
                return
            error = ctypes.get_last_error()
            if error not in (2, 231) or time.monotonic() >= deadline:
                raise OSError(error, "open private mock pipe failed")
            k.WaitNamedPipeW(name, 30)
            time.sleep(0.003)
    def close(self):
        if self.h is not None:
            k.CloseHandle(self.h)
            self.h = None
    def __enter__(self): return self
    def __exit__(self, *_): self.close()
    def io(self, data=None, size=4096, timeout_ms=2500):
        event = k.CreateEventW(None, True, False, None)
        ov = OVERLAPPED(); ov.hEvent = event
        transferred = w.DWORD()
        buf = ctypes.create_string_buffer(data) if data is not None else ctypes.create_string_buffer(size)
        count = len(data) if data is not None else size
        method = k.WriteFile if data is not None else k.ReadFile
        try:
            ok = method(self.h, buf, count, ctypes.byref(transferred), ctypes.byref(ov))
            if not ok:
                error = ctypes.get_last_error()
                if error != 997:
                    raise OSError(error, "mock pipe IO failed")
                if k.WaitForSingleObject(event, timeout_ms) != 0:
                    k.CancelIoEx(self.h, ctypes.byref(ov))
                    k.GetOverlappedResult(self.h, ctypes.byref(ov), ctypes.byref(transferred), True)
                    raise TimeoutError("bounded mock pipe IO timeout")
                if not k.GetOverlappedResult(self.h, ctypes.byref(ov), ctypes.byref(transferred), False):
                    raise OSError(ctypes.get_last_error(), "mock pipe completion failed")
            return transferred.value if data is not None else buf.raw[:transferred.value]
        finally:
            k.CloseHandle(event)
    def read_reply(self):
        data = b""
        while b"\n" not in data:
            chunk = self.io()
            if not chunk:
                raise ValueError("reply ended without LF")
            data += chunk
            if len(data) > 128 * 1024:
                raise ValueError("unbounded response")
        line, tail = data.split(b"\n", 1)
        if tail:
            raise ValueError("extra reply bytes")
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate JSON key")
                result[key] = value
            return result
        def finite_float(text):
            number = float(text)
            if not math.isfinite(number):
                raise ValueError("nonfinite JSON exponent")
            return number
        reply = json.loads(line.decode("utf-8", errors="strict"), object_pairs_hook=unique,
                           parse_float=finite_float,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
        # Caller closes immediately after LF; never waits for server EOF.
        self.close()
        return reply

EXE = None
class Host:
    def __init__(self, **settings):
        self.session = uuid.uuid4().hex
        env = dict(os.environ, DM_NATIVE_SESSION=self.session, NB_FAKE_CLOSE_AFTER_MS="10000")
        env.update({"NB_FAKE_" + key.upper(): str(value) for key, value in settings.items()})
        self.p = subprocess.Popen([str(EXE)], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  text=True, creationflags=subprocess.CREATE_NO_WINDOW)
        self.finished = None
    def frame(self, tail): return ("NB1 " + self.session + " " + tail + "\n").encode("ascii")
    def raw(self, frame, fragments=None):
        with Pipe(self.session) as pipe:
            if fragments:
                for chunk in fragments:
                    self.assert_write(pipe, chunk)
                    time.sleep(0.002)
            else:
                self.assert_write(pipe, frame)
            return pipe.read_reply()
    @staticmethod
    def assert_write(pipe, frame):
        if pipe.io(frame) != len(frame): raise AssertionError("partial test client write")
    def request(self, tail):
        reply = self.raw(self.frame(tail))
        if reply["protocol"] != "NB1" or reply["session"] != self.session:
            raise AssertionError("bad response correlation")
        if not isinstance(reply["host_pid"], int) or not isinstance(reply["timings_us"], dict):
            raise AssertionError("missing process/timing evidence")
        return reply
    def ready(self):
        for i in range(100):
            reply = self.request("ready STATUS")
            if reply.get("code") == "bridge_not_ready":
                time.sleep(.01); continue
            if reply["state"] != "queued": raise AssertionError(reply)
            return self.result("ready")
        raise AssertionError("mock host readiness callback not observed")
    def result(self, ident, timeout=3):
        deadline = time.monotonic() + timeout
        while True:
            reply = self.request(ident + " QUERY")
            if reply["state"] not in ("queued", "running"): return reply
            if time.monotonic() >= deadline: raise TimeoutError("mock operation remains pending")
            time.sleep(.01)
    def execute(self, tail):
        reply = self.request(tail)
        return self.result(tail.split()[0]) if reply["state"] in ("queued", "running") else reply
    def finish(self, stop=True):
        if self.finished is None:
            if stop and self.p.poll() is None:
                try: self.request("test_stop STOP")
                except (OSError, TimeoutError): pass
            try: self.finished = self.p.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                self.p.kill(); self.finished = self.p.communicate(); raise AssertionError("mock cleanup failed to terminate")
        return self.finished
    def lifecycle(self):
        out, _ = self.finish()
        return json.loads(out.strip().splitlines()[-1])

class TransportTests(unittest.TestCase):
    def setUp(self): self.hosts = []
    def host(self, **settings):
        h = Host(**settings); self.hosts.append(h); return h
    def tearDown(self):
        for h in self.hosts: h.finish()
    def test_fragmentation_and_numeric_results(self):
        h = self.host(); self.assertTrue(h.ready()["result"]["ready"])
        frame = h.frame("fragments INFO 1")
        response = h.raw(frame, [frame[i:i+3] for i in range(0, len(frame), 3)])
        self.assertEqual(response["state"], "queued")
        done = h.result("fragments"); self.assertEqual(done["result"]["shape"], [3, 4])
        self.assertNotEqual(done["worker_tid"], done["exec_tid"])
        self.assertEqual(h.execute("negative MEAN 1")["result"]["mean"], -1.25)
        self.assertEqual(h.execute("fraction MEAN 2")["result"]["mean"], .125)
        self.assertEqual(h.execute("crop CROP 1 1 0 4 2")["result"]["shape"], [2, 3])
        self.assertEqual(h.execute("bad_image INFO 4294967295")["state"], "failed")
        self.assertEqual(h.execute("bad_crop CROP 1 0 0 5 2")["state"], "failed")
        datasets = h.execute("unicode DATASETS")["result"]["datasets"]
        self.assertEqual(datasets[0]["name"], "中文图像")
        self.assertEqual(datasets[0]["unit"], "µm")
    def test_strict_frames(self):
        h = self.host(); h.ready()
        for tail in ["bad.id STATUS", "i STATUSX", "i INFO -1", "i INFO 4294967296", "i MEAN 1.2",
                     "i STATUS 1", "i  STATUS", "i STATUS ", "i\tSTATUS"]:
            self.assertEqual(h.raw(h.frame(tail))["state"], "failed", tail)
        for frame in [b"\n", b"x" * 513 + b"\n", h.frame("x STATUS") + h.frame("y STATUS"), h.frame("x STATUS").replace(b"\n", b"\r\n")]:
            self.assertEqual(h.raw(frame)["state"], "failed")
        mismatched = h.frame("mismatch STATUS").replace(h.session.encode(), b"0" * 32)
        self.assertEqual(h.raw(mismatched)["code"], "session_mismatch")
        self.assertEqual(h.lifecycle()["execute"], 1) # only readiness STATUS executed
    def test_duplicate_conflict_late_dispatch_and_no_retry(self):
        h = self.host(dispatch_delay_ms=250); h.ready()
        # Submit once and disconnect without reading. There is no automatic retry.
        with Pipe(h.session) as p: p.io(h.frame("first MEAN 1"))
        time.sleep(.03)
        self.assertEqual(h.request("first MEAN 1")["state"], "queued")
        self.assertEqual(h.request("first MEAN 2")["code"], "id_conflict")
        self.assertEqual(h.request("second MEAN 2")["code"], "busy")
        self.assertEqual(h.result("first")["result"]["mean"], -1.25)
        self.assertEqual(h.execute("second MEAN 2")["result"]["mean"], .125)
        self.assertEqual(h.request("first MEAN 1")["result"]["mean"], -1.25)
        self.assertEqual(h.request("absent QUERY")["state"], "unknown")
        self.assertEqual(h.lifecycle()["execute"], 3)
    def test_running_record_is_queryable(self):
        h = self.host(execute_delay_ms=300); h.ready()
        h.request("slow MEAN 1"); time.sleep(.06)
        self.assertEqual(h.request("slow QUERY")["state"], "running")
        self.assertEqual(h.request("other MEAN 2")["code"], "busy")
        self.assertEqual(h.result("slow")["state"], "completed")
    def test_stop_with_silent_connected_client(self):
        h = self.host(close_after_ms=300)
        with Pipe(h.session):
            before = time.monotonic(); h.finish(stop=False)
            self.assertLess(time.monotonic() - before, 1.5)
        self.assertEqual(h.lifecycle()["shutdown"], 1)
    def test_cleanup_drops_queued_callback(self):
        h = self.host(close_after_ms=350, dispatch_delay_ms=1000)
        # Readiness STATUS need not execute; readiness window callback already ran.
        for _ in range(100):
            response = h.request("pending MEAN 1")
            if response.get("code") != "bridge_not_ready": break
            time.sleep(.01)
        self.assertEqual(response["state"], "queued")
        h.finish(stop=False)
        self.assertEqual(h.lifecycle()["execute"], 0)
        self.assertEqual(h.lifecycle()["shutdown"], 1)
    def test_cleanup_with_unread_large_response(self):
        h = self.host(close_after_ms=700, reply_bytes=120000); h.ready()
        h.request("large DATASETS"); time.sleep(.04)
        with Pipe(h.session) as p:
            p.io(h.frame("large QUERY")) # response exceeds pipe capacity; deliberately do not read
            before = time.monotonic(); h.finish(stop=False)
            self.assertLess(time.monotonic() - before, 1.5)
        self.assertEqual(h.lifecycle()["shutdown"], 1)
    def test_response_bound_and_bad_adapter_json(self):
        h = self.host(reply_bytes=131050); h.ready()
        self.assertEqual(h.execute("large DATASETS")["code"], "response_too_large")
        bad = self.host(bad_json=1)
        # A successful host callback may return rejected mock JSON.
        for _ in range(100):
            response = bad.request("invalid MEAN 1")
            if response.get("code") != "bridge_not_ready": break
            time.sleep(.01)
        self.assertEqual(bad.result("invalid")["code"], "invalid_adapter_result")
    def test_initialization_failure_cleanup(self):
        h = self.host(init_fail=1); out, err = h.finish(stop=False)
        self.assertEqual(h.p.returncode, 2)
        life = json.loads(out.strip()); self.assertEqual(life["initialize"], 1); self.assertEqual(life["shutdown"], 1)
        self.assertIn("initialization failure", err)
        with self.assertRaises(OSError): Pipe(h.session, timeout=.05)
    def test_worker_and_partial_startup_failures_release_resources(self):
        for stage in ["adapter", "events", "class", "window", "security", "pipe", "worker"]:
            with self.subTest(stage=stage):
                h = self.host(start_fail_stage=stage)
                out, err = h.finish(stop=False)
                self.assertEqual(h.p.returncode, 2)
                lifecycle = json.loads(out.strip())
                self.assertEqual(lifecycle["initialize"], 1)
                self.assertEqual(lifecycle["shutdown"], 1)
                self.assertTrue(lifecycle["owned_resources_released"])
                self.assertIn(stage, err)
    def test_pipe_existence_does_not_prove_host_readiness(self):
        h = self.host(ready_delay_ms=200)
        self.assertEqual(h.request("before_callback STATUS")["code"], "bridge_not_ready")
        self.assertTrue(h.ready()["result"]["ready"])
    def test_reentrant_shutdown_defers_native_resource_release(self):
        h = self.host(reenter_shutdown=1); h.ready()
        try: h.request("reenter INFO 1")
        except (OSError, TimeoutError): pass # cancellation may win the queued receipt write
        h.finish(stop=False)
        lifecycle = h.lifecycle()
        self.assertTrue(lifecycle["close_refused"])
        self.assertTrue(lifecycle["shutdown_deferred"])
        self.assertEqual(lifecycle["shutdown_during_execute"], 0)
        self.assertEqual(lifecycle["shutdown"], 1)
        self.assertTrue(lifecycle["owned_resources_released"])
    def test_stop_posts_host_cleanup_and_releases_adapter_resources(self):
        h = self.host(); h.ready()
        reply = h.request("explicit_stop STOP")
        self.assertTrue(reply["result"]["ipc_stopped"])
        h.finish(stop=False)
        lifecycle = h.lifecycle()
        self.assertTrue(lifecycle["worker_cleanup_dispatched"])
        self.assertTrue(lifecycle["owned_resources_released"])
        self.assertEqual(lifecycle["shutdown"], 1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--exe", type=Path, default=Path(__file__).parent / "build" / "fake_host.exe")
    args, remaining = parser.parse_known_args(); EXE = args.exe.resolve()
    unittest.main(argv=[sys.argv[0]] + remaining, verbosity=2)
