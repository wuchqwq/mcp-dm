#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Isolated C1 experiment, Python 3.7 / NumPy 1.18 compatible.

No socket, worker thread, timer, polling loop, production Bridge import or
arbitrary script endpoint. Run generated Python scripts in DM's foreground.
Only this experiment's two tiny images may be accessed or changed.
"""
import gc
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import threading
import time
import uuid
import weakref

MODULE_KEY = "mcp_dm_c1_probe"
MAX_JSON_BYTES = 16384
SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
SESSION = None


def write_json(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=True, sort_keys=True, indent=2,
                  allow_nan=False)


def read_json(path):
    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_JSON_BYTES + 1)
    if len(raw) > MAX_JSON_BYTES:
        raise ValueError("JSON exceeds experiment budget")
    return json.loads(raw.decode("utf-8"))


def checked_id(value):
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{32}", value) is None:
        raise ValueError("Expected a 32-character lowercase hex ID")
    return value


def fingerprint(request):
    return hashlib.sha256(json.dumps(request, sort_keys=True,
                                    separators=(",", ":")).encode("utf-8")).hexdigest()


def trigger_script(image_id, token, request_id):
    checked_id(token)
    checked_id(request_id)
    if isinstance(image_id, bool) or not isinstance(image_id, int) or image_id <= 0:
        raise ValueError("Invalid image ID")
    # Fixed, documented DM-Script operations; no payload is executable code.
    return ('image trigger := FindImageByID(%d)\n'
            'if (!trigger.ImageIsValid()) Throw("C1 trigger missing")\n'
            'string token\n'
            'if (!trigger.ImageGetTagGroup().TagGroupGetTagAsString('
            '"MCP_C1:session", token)) Throw("C1 ownership missing")\n'
            'if (token != "%s") Throw("C1 ownership mismatch")\n'
            'SetName(trigger, "MCP_C1_%s_%s")\n'
            'Result("C1 name-change trigger returned\\n")\n') % (
                image_id, token, token, request_id)


def version_script(image_id):
    # Version values go only into the newly created synthetic trigger's tags.
    return ('image trigger := FindImageByID(%d)\n'
            'number major, minor, build\n'
            'GetApplicationVersion(major, minor, build)\n'
            'taggroup tags = trigger.ImageGetTagGroup()\n'
            'tags.TagGroupSetTagAsLong("MCP_C1:major", major)\n'
            'tags.TagGroupSetTagAsLong("MCP_C1:minor", minor)\n'
            'tags.TagGroupSetTagAsLong("MCP_C1:build", build)\n') % image_id


def check_version(version):
    # This installed API uses 53 for 3.5.3, not minor=5, patch=3.
    # Older listener implementations and unknown major versions are out of scope.
    if len(version) != 3 or version[0] != 3 or version[1] < 52:
        raise RuntimeError("C1 requires GMS 3.5.2+ in the 3.x API; "
                           "3.5.0/3.5.1 have a documented listener crash bug")


class Session(object):
    def __init__(self, root, dm, scope="real_dm"):
        self.root = Path(root)
        self.config = read_json(self.root / "session.json")
        self.token = checked_id(self.config["token"])
        self.DM = dm
        self.scope = scope
        self.thread_id = threading.get_ident()
        self.images = []
        self.documents = []
        self.listener = None
        self.listener_weak = None
        self.callback_count = 0
        self.cleanup_count = None
        self.in_callback = False
        self.active = False
        self.seen = {}

    def main_thread_only(self):
        if threading.get_ident() != self.thread_id:
            raise RuntimeError("Unknown callback thread; no DM API was called")
        if not self.DM.IsScriptOnMainThread():
            raise RuntimeError("Run this short experiment on the DM foreground thread")

    def log(self, event):
        event = dict(event, time=time.time(), scope=self.scope)
        with (self.root / "events.ndjson").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=True, allow_nan=False) + "\n")

    def start(self):
        self.main_thread_only()
        if not hasattr(self.DM.Py_ScriptObject, "UnregisterAllListeners"):
            raise RuntimeError("Host lacks explicit listener unregistration")
        import numpy as np
        y, x = np.indices((8, 12), dtype=np.float32)
        for label, array in (("SOURCE", 10 * y + x),
                             ("TRIGGER", np.zeros((1, 1), dtype=np.float32))):
            image = self.DM.CreateImage(array)
            self.images.append(image)
            image.SetName("MCP_C1_%s_%s" % (self.token, label))
            image.GetTagGroup().SetTagAsString("MCP_C1:session", self.token)
            image.SetDimensionCalibration(0, 1.25, -0.25, "nm", 0)
            image.SetDimensionCalibration(1, -2.5, 0.5, "nm", 0)
            doc = image.GetOrCreateImageDocument()
            self.documents.append(doc)
            doc.Show()
        source, trigger = self.images
        self.source_id = int(source.GetID())
        self.trigger_id = int(trigger.GetID())
        self.source_digest = hashlib.sha256(source.GetNumArray().tobytes()).hexdigest()
        self.calibration = [list(source.GetDimensionCalibration(i, 0)) for i in (0, 1)]
        self.DM.ExecuteScriptString(version_script(self.trigger_id))
        tags = trigger.GetTagGroup()
        version = []
        for key in ("major", "minor", "build"):
            ok, value = tags.GetTagAsLong("MCP_C1:" + key)
            if not ok:
                raise RuntimeError("Host version query did not return a value")
            version.append(int(value))
        check_version(version)
        owner = self
        dm = self.DM

        class Listener(dm.Py_ScriptObject):
            def __init__(self):
                dm.Py_ScriptObject.__init__(self)

            def HandleNameChangedEvent(self, flags, image):
                owner.callback(flags, image)

        self.listener = Listener()
        self.listener_weak = weakref.ref(self.listener)
        self.subscription_id = self.listener.ImageHandleNameChangedEvent(trigger, "mcp_c1")
        self.active = True
        state = {"token": self.token, "host_pid": os.getpid(),
                 "version": version, "registration_thread": self.thread_id,
                 "probe_code_sha256": SOURCE_SHA256, "python": sys.version,
                 "numpy": np.__version__, "registration_on_main_thread": True,
                 "source_id": self.source_id, "trigger_id": self.trigger_id,
                 "source_sha256": self.source_digest,
                 "scope": self.scope, "state": "registered"}
        write_json(self.root / "registered.json", state)
        lifecycle = {}
        for phase, filename in (("after_return", "02_after_return.s"),
                                ("after_second", "04_after_second.s"),
                                ("after_cleanup", "07_after_cleanup.s")):
            lifecycle[phase] = make_request(self.root, phase, filename)["request_id"]
        write_json(self.root / "lifecycle.json", lifecycle)
        # The installed native API returns a SWIG handle despite the reference's
        # generic "subscriber id" wording. Do not coerce or serialize pointers.
        self.log({"event": "registered", "subscription_return_type": type(self.subscription_id).__name__})
        write_json(self.root / "registration_complete.json",
                   {"state": "registered", "probe_code_sha256": SOURCE_SHA256,
                    "scope": self.scope})

    def source_check(self):
        import numpy as np
        source = self.images[0]
        ok, token = source.GetTagGroup().GetTagAsString("MCP_C1:session")
        if not ok or token != self.token or int(source.GetID()) != self.source_id:
            raise RuntimeError("Synthetic source ownership changed")
        array = source.GetNumArray()
        if array.shape != (8, 12) or array.dtype != np.dtype("float32"):
            raise RuntimeError("Synthetic source descriptor changed")
        digest = hashlib.sha256(array.tobytes()).hexdigest()
        calibration = [list(source.GetDimensionCalibration(i, 0)) for i in (0, 1)]
        if digest != self.source_digest or calibration != self.calibration:
            raise RuntimeError("Synthetic source changed")
        return {"shape_yx": [8, 12], "dtype": "float32", "sum": float(array.sum(dtype=np.float64)),
                "mean": float(array.mean(dtype=np.float64)), "min": float(array.min()),
                "max": float(array.max()), "source_sha256": digest,
                "calibration_xy": calibration}

    def callback(self, flags, image):
        started = time.perf_counter()
        self.callback_count += 1
        event = {"event": "callback", "thread": threading.get_ident(),
                 "registration_thread": self.thread_id, "count": self.callback_count}
        # Before ANY DM method, reject a thread other than the known UI thread.
        if threading.get_ident() != self.thread_id or not self.active or self.in_callback:
            event["rejected"] = "unknown_thread_or_inactive_or_reentrant"
            self.log(event)
            return
        self.in_callback = True
        try:
            if int(image.GetID()) != self.trigger_id:
                raise RuntimeError("Unrelated event image rejected")
            prefix = "MCP_C1_" + self.token + "_"
            name = image.GetName()
            if not name.startswith(prefix):
                raise ValueError("Invalid trigger name")
            request_id = checked_id(name[len(prefix):])
            request = read_json(self.root / "requests" / (request_id + ".json"))
            if set(request) != {"token", "id", "action", "phase", "nonce"}:
                raise ValueError("Unexpected request fields")
            if (request["token"] != self.token or request["id"] != request_id
                    or request["action"] != "probe"):
                raise ValueError("Request identity/action mismatch")
            checked_id(request["nonce"])
            if request["phase"] not in ("after_return", "after_second", "after_cleanup", "external"):
                raise ValueError("Invalid phase")
            digest = fingerprint(request)
            result_path = self.root / "replies" / (request_id + ".json")
            if request_id in self.seen:
                if self.seen[request_id] != digest:
                    raise ValueError("Operation ID already bound to different parameters")
                event["duplicate"] = True
                return
            if result_path.exists():
                raise RuntimeError("Unknown existing result; no overwrite or recomputation")
            if len(self.seen) >= 16:
                raise RuntimeError("Experiment request budget exhausted")
            result = self.source_check()
            result.update(echo_nonce=request["nonce"], source_image_id=self.source_id)
            write_json(result_path, {"id": request_id, "token": self.token,
                                    "request_sha256": digest, "phase": request["phase"],
                                    "state": "completed", "scope": self.scope,
                                    "host_pid": os.getpid(), "result": result})
            self.seen[request_id] = digest
            event["request_id"] = request_id
        except Exception as exc:
            event["error"] = "%s: %s" % (type(exc).__name__, exc)
        finally:
            self.in_callback = False
            event["duration_ms"] = 1000 * (time.perf_counter() - started)
            self.log(event)

    def second_script(self):
        # A separate normal Python script invokes this finite calculation.
        value = sum(range(11))
        write_json(self.root / "second_script.json",
                   {"sum_0_through_10": value, "listener_present": self.listener is not None,
                    "host_pid": os.getpid(), "scope": self.scope})
        if value != 55 or self.listener is None:
            raise RuntimeError("Second-script check failed")

    def cleanup(self):
        self.main_thread_only()
        if self.in_callback:
            raise RuntimeError("Busy callback; cleanup not performed")
        # If unregister fails, keep all strong refs so cleanup can be inspected.
        if self.listener is not None:
            self.listener.UnregisterAllListeners()
        self.active = False
        self.listener = None
        gc.collect()
        self.cleanup_count = self.callback_count
        write_json(self.root / "unregistered.json",
                   {"callback_count": self.cleanup_count,
                    "listener_still_alive": bool(self.listener_weak and self.listener_weak()),
                    "scope": self.scope})

    def verify_cleanup(self):
        self.main_thread_only()
        if self.cleanup_count is None or self.callback_count != self.cleanup_count:
            raise RuntimeError("Cleanup missing or a residual callback occurred")
        if self.listener is not None or (self.listener_weak and self.listener_weak() is not None):
            raise RuntimeError("Listener reference still alive")
        lifecycle_path = self.root / "lifecycle.json"
        if lifecycle_path.exists():
            after_id = read_json(lifecycle_path)["after_cleanup"]
            expected = "MCP_C1_%s_%s" % (self.token, after_id)
            if self.images[1].GetName() != expected:
                raise RuntimeError("Post-unregistration trigger has not actually run")
        if hasattr(self, "source_id"):
            self.source_check()
        write_json(self.root / "cleanup_verified.json",
                   {"state": "verified", "callback_count": self.callback_count, "scope": self.scope})

    def release(self):
        self.main_thread_only()
        if read_json(self.root / "cleanup_verified.json")["state"] != "verified":
            raise RuntimeError("Verify cleanup before closing synthetic documents")
        for image, document in zip(self.images, self.documents):
            ok, token = image.GetTagGroup().GetTagAsString("MCP_C1:session")
            if not ok or token != self.token:
                raise RuntimeError("Ownership missing; document left open")
            document.Close(False)
        self.images = []
        self.documents = []
        write_json(self.root / "released.json", {"state": "released", "scope": self.scope})


def register(root):
    global SESSION
    if SESSION is not None:
        raise RuntimeError("Session already exists; do not register twice")
    import DigitalMicrograph as DM
    SESSION = Session(root, DM)
    try:
        SESSION.start()
    except Exception as exc:
        write_json(Path(root) / "registration_failure.json",
                   {"error": "%s: %s" % (type(exc).__name__, exc)})
        raise  # SESSION stays rooted for explicit cleanup; no silent replacement.


def make_request(root, phase="external", filename=None):
    root = Path(root)
    config = read_json(root / "session.json")
    state = read_json(root / "registered.json")
    if (root / "registration_failure.json").exists():
        raise RuntimeError("Registration failed; inspect and unregister before any new request")
    if (root / "unregistered.json").exists():
        raise RuntimeError("Session has been unregistered")
    token = checked_id(config["token"])
    if token != state["token"]:
        raise ValueError("Session identity mismatch")
    request_id = uuid.uuid4().hex
    request = {"token": token, "id": request_id, "action": "probe",
               "phase": phase, "nonce": uuid.uuid4().hex}
    write_json(root / "requests" / (request_id + ".json"), request)
    filename = filename or ("external_" + request_id + ".s")
    with (root / filename).open("x", encoding="utf-8") as stream:
        stream.write(trigger_script(int(state["trigger_id"]), token, request_id))
    return {"request_id": request_id, "script": str(root / filename),
            "reply": str(root / "replies" / (request_id + ".json")),
            "state": "wake_required", "automatic_external_dispatch": "NOT_TESTED"}


def prepare(root):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=False)
    (root / "requests").mkdir()
    (root / "replies").mkdir()
    write_json(root / "session.json", {"token": uuid.uuid4().hex, "schema_version": 1})
    source = str(Path(__file__).resolve())
    register_code = (
        "import importlib.util, sys\n"
        "key = %r\n"
        "if key in sys.modules: raise RuntimeError('Existing C1 module; inspect and clean up first')\n"
        "spec = importlib.util.spec_from_file_location(key, %r)\n"
        "module = importlib.util.module_from_spec(spec)\n"
        "sys.modules[key] = module\n"
        "spec.loader.exec_module(module)\n"
        "module.register(%r)\n"
        "print('C1 registration script is returning; no loop or worker was started')\n"
    ) % (MODULE_KEY, source, str(root))
    scripts = {"01_register.py": register_code,
               "10_verify_release_after_unregister.py": recovery_code()}
    for filename, method in (("03_second_script.py", "second_script"),
                             ("06_cleanup.py", "cleanup"),
                             ("08_verify_cleanup.py", "verify_cleanup"),
                             ("09_release.py", "release")):
        code = ("import sys\n"
                "module = sys.modules.get(%r)\n"
                "if module is None: raise RuntimeError('C1 module did not survive; do not re-register')\n"
                "module.SESSION.%s()\n"
                "print('C1 %s returned')\n") % (MODULE_KEY, method, method)
        if method == "release":
            code += "sys.modules.pop(%r, None)\nmodule.SESSION = None\ndel module\n" % MODULE_KEY
        scripts[filename] = code
    for name, code in scripts.items():
        with (root / name).open("x", encoding="utf-8") as stream:
            stream.write(code)
    return str(root)


def recovery_code():
    """Finite cleanup verifier, only after explicit native unregistration.

    Used if a failed registration left an already-unregistered session rooted.
    No new listener, polling, replacement input or arbitrary payload is accepted.
    """
    return ("import sys\n"
            "module = sys.modules.get(%r)\n"
            "if module is None: raise RuntimeError('No retained C1 module')\n"
            "s = module.SESSION\n"
            "s.main_thread_only()\n"
            "if s.listener is not None or s.cleanup_count is None: raise RuntimeError('Unregister first')\n"
            "life = module.read_json(s.root / 'lifecycle.json')\n"
            "s.DM.ExecuteScriptString(module.trigger_script(s.trigger_id, s.token, life['after_cleanup']))\n"
            "s.verify_cleanup()\n"
            "s.release()\n"
            "sys.modules.pop(%r, None)\n"
            "module.SESSION = None\n"
            "del s, module, life\n"
            "print('C1 post-unregister trigger, verification and owned-document release returned')\n"
            ) % (MODULE_KEY, MODULE_KEY)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "request"))
    parser.add_argument("session_dir")
    args = parser.parse_args()
    output = prepare(args.session_dir) if args.command == "prepare" else make_request(args.session_dir)
    print(json.dumps(output, ensure_ascii=True))
