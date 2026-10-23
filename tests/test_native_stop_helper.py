"""Offline STOP-helper ordering tests with a fake Pipe; never accesses DM."""
import builtins
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "experiments" / "native-bridge" / "mvp" / "stop_native.py"
SESSION = "0123456789abcdef0123456789abcdef"


def _write(path, value):
    Path(path).write_text(json.dumps(value), encoding="utf-8")


def _child(state_path):
    state = json.loads(Path(state_path).read_text(encoding="utf-8"))
    events = []
    request_path = Path(state["request_path"])
    real_open, real_fsync = builtins.open, os.fsync
    opened = []

    class TrackedFile:
        def __init__(self, file):
            self.file = file

        def __enter__(self):
            self.file.__enter__()
            return self

        def __exit__(self, *args):
            result = self.file.__exit__(*args)
            events.append("record_closed")
            if state.get("failure") == "close":
                raise OSError("injected record close failure")
            return result

        def write(self, value):
            events.append("record_write")
            if state.get("failure") == "write":
                raise OSError("injected record write failure")
            return self.file.write(value)

        def flush(self):
            result = self.file.flush()
            events.append("record_flushed")
            return result

        def fileno(self):
            return self.file.fileno()

    def tracked_open(path, mode="r", *args, **kwargs):
        is_request = isinstance(path, (str, bytes, os.PathLike)) and os.path.normcase(
            os.path.abspath(path)) == os.path.normcase(str(request_path))
        if is_request and mode == "x":
            events.append("record_open_x")
            wrapped = TrackedFile(real_open(path, mode, *args, **kwargs))
            opened.append(wrapped)
            return wrapped
        return real_open(path, mode, *args, **kwargs)

    def tracked_fsync(fd):
        if opened and not opened[-1].file.closed and fd == opened[-1].file.fileno():
            events.append("record_fsync_called")
            if state.get("failure") == "fsync":
                raise OSError("injected record fsync failure")
            result = real_fsync(fd)
            events.append("record_fsynced")
            return result
        return real_fsync(fd)

    expected = {"protocol": "NB1", "session": SESSION, "id": "stop-synthetic", "op": "STOP",
                "args": [], "host_pid": 101, "wire": "NB1 %s stop-synthetic STOP\n" % SESSION}

    class Pipe:
        def __init__(self, session, timeout):
            events.append("pipe_init")
            # This assertion observes the real persisted file and its actual
            # closed handle before allowing even a simulated connection.
            assert opened and opened[-1].file.closed, "Pipe constructed before request file closed"
            for marker in ("record_open_x", "record_write", "record_flushed", "record_fsynced", "record_closed"):
                assert marker in events and events.index(marker) < events.index("pipe_init"), marker
            with real_open(str(request_path), encoding="utf-8") as file:
                assert json.load(file) == expected, "Wrong saved original request"
            assert session == SESSION and timeout == 3
            if state.get("failure") == "connect":
                raise ConnectionError("injected pipe connection failure")

        def __enter__(self):
            events.append("pipe_enter")
            return self

        def __exit__(self, *args):
            events.append("pipe_exit")

        def io(self, wire):
            assert wire == expected["wire"].encode("ascii"), "Sent wire differs from saved request"
            events.append("send")

        def read_reply(self):
            events.append("reply")
            return state["reply"]

    fake = types.ModuleType("test_transport")
    fake.Pipe = Pipe
    sys.modules["test_transport"] = fake
    argv = [str(SCRIPT), "--session", SESSION, "--request-id", "stop-synthetic", "--request-record",
            str(request_path), "--expected-host-pid", "101", "--evidence", state["evidence_path"]]
    for option, value in state.get("options", {}).items():
        index = argv.index(option)
        if value is None:
            del argv[index:index + 2]
        else:
            argv[index + 1] = str(value)
    try:
        with mock.patch("builtins.open", side_effect=tracked_open), mock.patch("os.fsync", side_effect=tracked_fsync), \
                mock.patch.object(sys, "argv", argv):
            runpy.run_path(str(SCRIPT), run_name="__main__")
    finally:
        _write(Path(state_path).with_name("events.json"), events)


class NativeStopHelperTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="native-stop-helper-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.request = self.directory / "stop-request.json"
        self.evidence = self.directory / "stop-receipt.json"
        self.state_path = self.directory / "state.json"

    def reply(self):
        return {"protocol": "NB1", "session": SESSION, "id": "stop-synthetic", "state": "completed",
                "host_pid": 101, "worker_tid": 202, "exec_tid": 0,
                "timings_us": {"queue": 0, "execute": 0}, "result": {"ipc_stopped": True}}

    def invoke(self, failure=None, options=None, reply=None, code=0, error=None):
        state = {"request_path": str(self.request), "evidence_path": str(self.evidence),
                 "failure": failure, "options": options or {}, "reply": self.reply() if reply is None else reply}
        _write(self.state_path, state)
        env = dict(os.environ, PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1")
        env.pop("PYTHONPATH", None)
        result = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), "--fake-stop-helper",
                                 str(self.state_path)], cwd=str(self.directory), env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
        output = result.stdout.decode("utf-8", "replace") + result.stderr.decode("utf-8", "replace")
        self.assertEqual(result.returncode, code, output)
        self.assertNotIn("PASS", result.stdout.decode("utf-8", "replace"))
        if error:
            self.assertIn(error, output)
        events = json.loads((self.directory / "events.json").read_text(encoding="utf-8"))
        return events

    def assert_no_pipe(self, events):
        self.assertNotIn("pipe_init", events)
        self.assertNotIn("send", events)

    def test_durable_original_request_precedes_pipe_and_single_send(self):
        events = self.invoke()
        self.assertLess(events.index("record_flushed"), events.index("record_fsynced"))
        self.assertLess(events.index("record_fsynced"), events.index("record_closed"))
        self.assertLess(events.index("record_closed"), events.index("pipe_init"))
        self.assertLess(events.index("pipe_init"), events.index("send"))
        self.assertEqual(events.count("send"), 1)
        request = json.loads(self.request.read_text(encoding="utf-8"))
        self.assertEqual(request, {"protocol": "NB1", "session": SESSION, "id": "stop-synthetic", "op": "STOP",
                                   "args": [], "host_pid": 101, "wire": "NB1 %s stop-synthetic STOP\n" % SESSION})
        self.assertEqual(json.loads(self.evidence.read_text(encoding="utf-8")), self.reply())

    def test_existing_request_or_receipt_is_never_overwritten_or_sent(self):
        for target in (self.request, self.evidence):
            with self.subTest(target=target.name):
                target.write_bytes(b"historical evidence; preserve exactly")
                events = self.invoke(code=2, error="already exists")
                self.assert_no_pipe(events)
                self.assertEqual(target.read_bytes(), b"historical evidence; preserve exactly")
                self.assertFalse((self.evidence if target == self.request else self.request).exists())
                target.unlink()

    def test_write_fsync_and_close_failure_never_construct_pipe(self):
        for failure in ("write", "fsync", "close"):
            with self.subTest(failure=failure):
                events = self.invoke(failure=failure, code=1, error="injected record " + failure + " failure")
                self.assert_no_pipe(events)
                self.assertTrue(self.request.exists())
                self.assertFalse(self.evidence.exists())
                self.request.unlink()

    def test_new_required_options_and_invalid_inputs_fail_before_transport(self):
        cases = [("--request-record", None, "required"), ("--expected-host-pid", None, "required"),
                 ("--expected-host-pid", 0, "positive uint32"), ("--expected-host-pid", -1, "positive uint32"),
                 ("--expected-host-pid", 4294967296, "positive uint32"),
                 ("--session", "wrong", "32 lowercase"), ("--request-id", "has space", "bounded ASCII")]
        for option, value, error in cases:
            with self.subTest(option=option, value=value):
                self.assert_no_pipe(self.invoke(options={option: value}, code=2, error=error))
                self.assertFalse(self.request.exists())
                self.assertFalse(self.evidence.exists())

    def test_record_and_receipt_paths_must_differ(self):
        events = self.invoke(options={"--evidence": str(self.request)}, code=2, error="distinct new files")
        self.assert_no_pipe(events)
        self.assertFalse(self.request.exists())

    def test_failed_connection_retains_original_and_cannot_automatically_resend(self):
        events = self.invoke(failure="connect", code=1, error="injected pipe connection failure")
        self.assertIn("pipe_init", events)
        self.assertNotIn("send", events)
        original = self.request.read_bytes()
        self.assertFalse(self.evidence.exists())
        self.assert_no_pipe(self.invoke(code=2, error="request-record already exists"))
        self.assertEqual(self.request.read_bytes(), original)

    def test_duplicate_helper_call_cannot_submit_a_second_stop(self):
        events = self.invoke()
        self.assertEqual(events.count("send"), 1)
        original, receipt = self.request.read_bytes(), self.evidence.read_bytes()
        self.assert_no_pipe(self.invoke(code=2, error="request-record already exists"))
        self.assertEqual(self.request.read_bytes(), original)
        self.assertEqual(self.evidence.read_bytes(), receipt)

    def test_raw_failed_receipt_is_saved_but_never_acknowledged_as_qualified(self):
        cases = [("id", "different", "STOP was not acknowledged"),
                 ("session", "fedcba9876543210fedcba9876543210", "STOP was not acknowledged"),
                 ("state", "failed", "STOP was not acknowledged"),
                 ("result", {"ipc_stopped": 1}, "STOP was not acknowledged"),
                 ("host_pid", 999, "malformed or wrong-host STOP receipt"),
                 ("exec_tid", 303, "malformed or wrong-host STOP receipt"),
                 ("worker_tid", 0, "malformed or wrong-host STOP receipt"),
                 ("timings_us", {"queue": -1, "execute": 0}, "malformed or wrong-host STOP receipt"),
                 ("error", "injected native failure", "malformed or wrong-host STOP receipt")]
        for field, value, error in cases:
            with self.subTest(field=field):
                reply = self.reply()
                reply[field] = value
                events = self.invoke(reply=reply, code=1, error=error)
                self.assertEqual(events.count("send"), 1)
                self.assertEqual(json.loads(self.evidence.read_text(encoding="utf-8")), reply)
                self.assertTrue(self.request.is_file())
                self.evidence.unlink()
                self.request.unlink()


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--fake-stop-helper":
        _child(Path(sys.argv[2]))
    else:
        unittest.main()
