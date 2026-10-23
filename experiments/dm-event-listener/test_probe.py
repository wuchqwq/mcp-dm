"""Synthetic/fake-DM tests only; not evidence about GMS scheduling or SWIG."""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest

import numpy as np

spec = importlib.util.spec_from_file_location("c1_test_subject", str(Path(__file__).with_name("probe.py")))
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class Tags(object):
    def __init__(self):
        self.data = {}

    def SetTagAsString(self, name, value):
        self.data[name] = value

    def GetTagAsString(self, name):
        return name in self.data, self.data.get(name, "")

    def GetTagAsLong(self, name):
        return name in self.data, self.data.get(name, 0)


class Document(object):
    def __init__(self):
        self.closed = False

    def Show(self):
        pass

    def Close(self, saving):
        assert saving is False
        self.closed = True


class Image(object):
    def __init__(self, array, identity):
        self.array = np.array(array, copy=True)
        self.identity = identity
        self.tags = Tags()
        self.doc = Document()
        self.calib = {}
        self.name = ""

    def GetID(self):
        return self.identity

    def SetName(self, value):
        self.name = value

    def GetName(self):
        return self.name

    def GetTagGroup(self):
        return self.tags

    def GetOrCreateImageDocument(self):
        return self.doc

    def SetDimensionCalibration(self, axis, zero, scale, unit, fmt):
        self.calib[axis] = (zero, scale, unit)

    def GetDimensionCalibration(self, axis, fmt):
        return self.calib[axis]

    def GetNumArray(self):
        return self.array


class FakeDM(object):
    def __init__(self, version=(3, 53, 100)):
        self.images = []
        self.version = version
        self.foreground = True
        self.unregistration_fails = False
        self.registrations = []
        owner = self

        class ScriptObject(object):
            def ImageHandleNameChangedEvent(self, image, client):
                owner.registrations.append(self)
                return 1

            def UnregisterAllListeners(self):
                if owner.unregistration_fails:
                    raise RuntimeError("injected unregister failure")
                owner.registrations.remove(self)

        self.Py_ScriptObject = ScriptObject

    def IsScriptOnMainThread(self):
        return self.foreground

    def CreateImage(self, array):
        image = Image(array, len(self.images) + 1)
        self.images.append(image)
        return image

    def ExecuteScriptString(self, script):
        assert "GetApplicationVersion" in script
        for key, value in zip(("major", "minor", "build"), self.version):
            self.images[-1].tags.data["MCP_C1:" + key] = value


class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "session"
        probe.prepare(self.root)
        self.dm = FakeDM()
        self.session = probe.Session(self.root, self.dm, scope="fake_dm_unit")

    def tearDown(self):
        self.temp.cleanup()

    def start(self):
        self.session.start()

    def trigger(self, phase="external", request=None):
        request = request or probe.make_request(self.root, phase)
        identity = request["request_id"]
        image = self.session.images[1]
        image.name = "MCP_C1_%s_%s" % (self.session.token, identity)
        self.session.listener.HandleNameChangedEvent(0, image)
        return request

    def events(self):
        return [json.loads(s) for s in (self.root / "events.ndjson").read_text().splitlines()]

    def post_cleanup_signal(self):
        after_id = probe.read_json(self.root / "lifecycle.json")["after_cleanup"]
        self.dm.images[1].name = "MCP_C1_%s_%s" % (self.session.token, after_id)

    def test_hand_enumerated_source_and_signed_calibration(self):
        self.start()
        request = self.trigger()
        reply = probe.read_json(request["reply"])
        result = reply["result"]
        self.assertEqual(result["shape_yx"], [8, 12])
        self.assertEqual(result["sum"], 3888)
        self.assertEqual(result["mean"], 40.5)
        self.assertEqual((result["min"], result["max"]), (0, 81))
        self.assertEqual(result["calibration_xy"], [[1.25, -0.25, "nm"], [-2.5, 0.5, "nm"]])
        req = probe.read_json(self.root / "requests" / (request["request_id"] + ".json"))
        self.assertEqual(result["echo_nonce"], req["nonce"])
        self.assertEqual(reply["scope"], "fake_dm_unit")

    def test_dangerous_and_unknown_versions_fail_before_subscription(self):
        for version in ((3, 50, 1), (3, 51, 1), (3, 43, 1), (4, 0, 1)):
            with self.assertRaises(RuntimeError):
                probe.check_version(version)
        self.dm.version = (3, 51, 1)
        with self.assertRaises(RuntimeError):
            self.start()
        self.assertEqual(self.dm.registrations, [])

    def test_background_registration_refused_before_creating_images(self):
        self.dm.foreground = False
        with self.assertRaises(RuntimeError):
            self.start()
        self.assertEqual(self.dm.images, [])

    def test_native_subscription_handle_need_not_be_json_serializable(self):
        base = self.dm.Py_ScriptObject
        class NativeLikeObject(base):
            def ImageHandleNameChangedEvent(self, image, client):
                base.ImageHandleNameChangedEvent(self, image, client)
                return object()
        self.dm.Py_ScriptObject = NativeLikeObject
        self.start()
        self.assertEqual(probe.read_json(self.root / "registration_complete.json")["state"], "registered")
        self.assertEqual(self.events()[-1]["subscription_return_type"], "object")

    def test_unknown_thread_never_calls_image_api(self):
        self.start()
        class ForbiddenImage(object):
            def GetID(self):
                raise AssertionError("DM API must not be called on this thread")
        thread = threading.Thread(target=self.session.callback, args=(0, ForbiddenImage()))
        thread.start()
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertIn("rejected", self.events()[-1])

    def test_unrelated_image_rejected(self):
        self.start()
        unrelated = Image(np.zeros((2, 3)), 999)
        self.session.callback(0, unrelated)
        self.assertIn("Unrelated", self.events()[-1]["error"])
        self.assertFalse(unrelated.doc.closed)
        self.assertEqual(unrelated.name, "")

    def test_source_edit_is_reported_and_never_repaired(self):
        self.start()
        self.dm.images[0].array[0, 0] = -1
        request = self.trigger()
        self.assertFalse(Path(request["reply"]).exists())
        self.assertIn("source changed", self.events()[-1]["error"])
        self.assertEqual(self.dm.images[0].array[0, 0], -1)

    def test_duplicate_request_is_bound_to_its_parameters(self):
        self.start()
        request = self.trigger()
        before = Path(request["reply"]).read_bytes()
        self.trigger(request=request)
        self.assertTrue(self.events()[-1]["duplicate"])
        reqpath = self.root / "requests" / (request["request_id"] + ".json")
        changed = probe.read_json(reqpath)
        changed["nonce"] = "f" * 32
        reqpath.write_text(json.dumps(changed))
        self.trigger(request=request)
        self.assertIn("already bound", self.events()[-1]["error"])
        self.assertEqual(Path(request["reply"]).read_bytes(), before)

    def test_bad_request_and_oversize_json_fail(self):
        self.start()
        request = probe.make_request(self.root)
        path = self.root / "requests" / (request["request_id"] + ".json")
        path.write_bytes(b" " * (probe.MAX_JSON_BYTES + 1))
        self.trigger(request=request)
        self.assertIn("budget", self.events()[-1]["error"])
        self.assertFalse(Path(request["reply"]).exists())

    def test_session_mismatch_and_extra_fields_fail(self):
        self.start()
        for mode in ("token", "extra"):
            request = probe.make_request(self.root)
            path = self.root / "requests" / (request["request_id"] + ".json")
            value = probe.read_json(path)
            value[mode] = "0" * 32
            path.write_text(json.dumps(value))
            self.trigger(request=request)
            self.assertIn("error", self.events()[-1])
            self.assertFalse(Path(request["reply"]).exists())

    def test_unregister_failure_preserves_references(self):
        self.start()
        listener = self.session.listener
        self.dm.unregistration_fails = True
        with self.assertRaises(RuntimeError):
            self.session.cleanup()
        self.assertIs(self.session.listener, listener)
        self.assertTrue(self.session.active)
        self.assertFalse((self.root / "unregistered.json").exists())

    def test_cleanup_and_release_only_owned_documents(self):
        self.start()
        self.trigger()
        source_hash = hashlib.sha256(self.dm.images[0].array.tobytes()).hexdigest()
        self.session.cleanup()
        self.assertIsNone(self.session.listener_weak())
        self.post_cleanup_signal()
        self.session.verify_cleanup()
        self.session.release()
        self.assertTrue(all(i.doc.closed for i in self.dm.images))
        self.assertEqual(hashlib.sha256(self.dm.images[0].array.tobytes()).hexdigest(), source_hash)

    def test_residual_callback_fails_verification(self):
        self.start()
        self.session.cleanup()
        self.session.callback(0, object())
        with self.assertRaises(RuntimeError):
            self.session.verify_cleanup()

    def test_changed_ownership_prevents_close(self):
        self.start()
        self.session.cleanup()
        self.post_cleanup_signal()
        self.session.verify_cleanup()
        self.dm.images[0].tags.data["MCP_C1:session"] = "other"
        with self.assertRaises(RuntimeError):
            self.session.release()
        self.assertFalse(any(i.doc.closed for i in self.dm.images))

    def test_missing_post_cleanup_signal_cannot_pass(self):
        self.start()
        self.session.cleanup()
        with self.assertRaisesRegex(RuntimeError, "has not actually run"):
            self.session.verify_cleanup()

    def test_failed_registration_can_still_release_own_images(self):
        self.dm.version = (3, 51, 1)
        with self.assertRaises(RuntimeError):
            self.start()
        self.session.cleanup()
        self.session.verify_cleanup()
        self.session.release()
        self.assertTrue(all(i.doc.closed for i in self.dm.images))

    def test_paths_and_script_injection_rejected(self):
        for bad in ("../anything", '"\nThrow(1)', "0" * 31, "F" * 32):
            with self.assertRaises(ValueError):
                probe.trigger_script(1, "0" * 32, bad)
        with self.assertRaises(ValueError):
            probe.trigger_script(True, "0" * 32, "1" * 32)

    def test_no_overwrite_and_python37_syntax(self):
        with self.assertRaises(FileExistsError):
            probe.prepare(self.root)
        for path in [Path(probe.__file__)] + list(self.root.glob("*.py")):
            text = path.read_text(encoding="utf-8")
            ast.parse(text, filename=str(path))
            # The actual GMS Python run is the authoritative 3.7 parser test.


if __name__ == "__main__":
    unittest.main(verbosity=2)
