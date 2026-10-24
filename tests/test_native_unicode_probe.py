# -*- coding: utf-8 -*-
"""Unicode diagnostic fault injection in isolated, explicitly fake DM children.

These tests never import the real host module or contact DM/GUI/native IPC.
They qualify diagnostic retention only, not any host encoding conversion.
"""
import ast
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import types
import unittest


ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "experiments" / "native-bridge" / "mvp" / "create_unicode_fixture.py"
SESSION = "0123456789abcdef0123456789abcdef"


def _run_fake_probe(state_path):
    """Child entry point: install a fake before executing the explicit probe."""
    state = json.loads(Path(state_path).read_text(encoding="utf-8"))
    calls = []
    images = []

    def fault_value(spec, default):
        if spec is None:
            return default
        kind = spec["kind"]
        if kind == "bytes":
            return bytes.fromhex(spec["hex"])
        if kind == "value":
            return spec["value"]
        if kind == "encoding_error":
            raise UnicodeEncodeError("utf-8", "A\ud800", 1, 2, "test surrogate")
        if kind == "decoding_error":
            raise UnicodeDecodeError("utf-8", b"\xff\x80", 0, 1, "test invalid byte")
        if kind == "getter_error":
            raise RuntimeError("fake getter failed: \u03a9")
        raise AssertionError("unsupported fake scenario")

    def record(image, method, axis=None):
        call = {"id": image.image_id, "method": method}
        if axis is not None:
            call["axis"] = axis
        calls.append(call)

    class Image:
        def __init__(self, image_id):
            self.image_id = image_id
            self.name = "unset"
            self.axes = [[0.0, 1.0, ""], [0.0, 1.0, ""]]

        def GetID(self):
            record(self, "GetID")
            return self.image_id

        def SetName(self, name):
            record(self, "SetName")
            fault_value(state.get("setter"), None)
            self.name = name

        def GetName(self):
            record(self, "GetName")
            return fault_value(state.get("name"), self.name)

        def SetDimensionCalibration(self, axis, zero, scale, unit, style):
            record(self, "SetDimensionCalibration", axis)
            if style != 0:
                raise AssertionError("probe must explicitly use physical-zero style")
            self.axes[axis] = [zero, scale, unit]

        def GetDimensionCalibration(self, axis, style):
            record(self, "GetDimensionCalibration", axis)
            if style != 0:
                raise AssertionError("probe must explicitly use physical-zero style")
            zero, scale, unit = self.axes[axis]
            if "calibration" in state:
                return fault_value(state["calibration"], None)
            if state.get("nonfinite_zero"):
                zero = float("nan")
            unit = fault_value(state.get("unit"), unit)
            return zero, scale, unit

        def GetOrCreateImageDocument(self):
            record(self, "GetOrCreateImageDocument")
            return Document(self)

        def Close(self):
            raise AssertionError("must not close any image")

    class Document:
        def __init__(self, image):
            self.image = image

        def Show(self):
            record(self.image, "Show")

        def Close(self):
            raise AssertionError("must not close any document")

    def create_image(array):
        # Independently require the known tiny synthetic input; no user array exists.
        if array.shape != (2, 2) or str(array.dtype) != "float32":
            raise AssertionError("unexpected synthetic shape/dtype")
        if array.tolist() != [[1.25, -2.0], [3.0, 4.5]]:
            raise AssertionError("unexpected synthetic pixels")
        image = Image(801 + len(images))
        images.append(image)
        record(image, "CreateImage")
        return image

    def forbidden(*args, **kwargs):
        calls.append({"method": "FORBIDDEN_EXISTING_IMAGE_ACCESS"})
        raise AssertionError("existing images are outside the probe scope")

    fake = types.ModuleType("DigitalMicrograph")
    fake.CreateImage = create_image
    for name in ("GetFrontImage", "FindImageByID", "FindImageByName", "GetImage",
                 "GetImageDocumentOfAllWorkspaces", "CountImageDocumentsOfAllWorkspaces"):
        setattr(fake, name, forbidden)
    sys.modules["DigitalMicrograph"] = fake
    try:
        runpy.run_path(str(PROBE), run_name="__main__")
    finally:
        Path(state["calls_path"]).write_text(json.dumps(calls), encoding="utf-8")


class NativeUnicodeProbeTests(unittest.TestCase):
    def _probe(self, state=None, existing=None, session=SESSION):
        with tempfile.TemporaryDirectory(prefix="native-unicode-fake-") as directory:
            directory = Path(directory)
            output = directory / "unicode-python.json"
            if existing is not None:
                output.write_bytes(existing)
            state = dict(state or {})
            state["calls_path"] = str(directory / "calls.json")
            state_path = directory / "state.json"
            state_path.write_text(json.dumps(state, ensure_ascii=True), encoding="utf-8")
            env = os.environ.copy()
            env["DM_NATIVE_EVIDENCE_DIR"] = str(directory)
            if session is None:
                env.pop("DM_NATIVE_SESSION", None)
            else:
                env["DM_NATIVE_SESSION"] = session
            child = subprocess.run(
                [sys.executable, "-B", str(Path(__file__).resolve()),
                 "--run-unicode-probe", str(state_path)],
                env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
            raw = output.read_bytes() if output.exists() else None
            record = json.loads(raw.decode("utf-8")) if raw and existing is None else None
            calls = json.loads(Path(state["calls_path"]).read_text(encoding="utf-8"))
            return child, record, raw, calls

    def _scope(self, record):
        self.assertEqual(record["schema"], 1)
        self.assertEqual(record["qualification"], "NOT_QUALIFIED")
        self.assertEqual(record["ui_observation"], "NOT_TESTED")
        self.assertEqual(record["native_observation"], "NOT_TESTED")
        self.assertNotEqual(record["status"], "PASS")

    def _bytes(self, observed, expected_hex):
        self.assertEqual(observed, {"type": "bytes", "hex": expected_hex,
                                   "length": len(expected_hex) // 2,
                                   "decoding": "NOT_ATTEMPTED"})
        self.assertNotIn("codepoints", observed)
        self.assertNotIn("value", observed)

    def test_str_values_are_exact_and_all_operations_use_new_images(self):
        child, report, raw, calls = self._probe()
        self.assertEqual(child.returncode, 0, child.stderr)
        self._scope(report)
        self.assertEqual(report["status"], "RECORDED")
        self.assertEqual(report["errors"], [])
        self.assertEqual(len(report["images"]), 5)
        chinese = report["images"][2]["python_readback"]
        self.assertEqual(chinese, {"type": "str", "value": "中文",
                                  "codepoints": ["U+4E2D", "U+6587"],
                                  "contains_surrogates": False, "surrogate_indices": []})
        last = report["images"][4]["python_readback"]
        self.assertEqual(last["value"], "µm_Å_Ω_é_😀")
        self.assertEqual(last["codepoints"], ["U+00B5", "U+006D", "U+005F", "U+00C5",
                                              "U+005F", "U+03A9", "U+005F", "U+00E9",
                                              "U+005F", "U+1F600"])
        self.assertTrue(raw.isascii())
        new_ids = [call["id"] for call in calls if call["method"] == "CreateImage"]
        self.assertEqual(new_ids, [801, 802, 803, 804, 805])
        self.assertTrue(all(call.get("id") in new_ids for call in calls))
        self.assertEqual(sum(call["method"] == "Show" for call in calls), 5)

    def test_invalid_utf8_bytes_remain_exact_bytes(self):
        child, report, _, _ = self._probe({"name": {"kind": "bytes", "hex": "fffe80c328"}})
        self.assertEqual(child.returncode, 0, child.stderr)
        self._scope(report)
        self.assertEqual(report["status"], "RECORDED")
        for image in report["images"]:
            self._bytes(image["python_readback"], "fffe80c328")

    def test_valid_utf8_bytes_are_never_decoded(self):
        child, report, _, _ = self._probe({"name": {"kind": "bytes", "hex": "e4b8ade69687"}})
        self.assertEqual(child.returncode, 0, child.stderr)
        self._scope(report)
        for image in report["images"]:
            self._bytes(image["python_readback"], "e4b8ade69687")

    def test_unit_bytes_are_raw_in_unit_and_full_calibration(self):
        for hex_value in ("ff80", "c2b56d", ""):
            with self.subTest(hex_value=hex_value):
                child, report, _, _ = self._probe({"unit": {"kind": "bytes", "hex": hex_value}})
                self.assertEqual(child.returncode, 0, child.stderr)
                self._scope(report)
                for image in report["images"]:
                    for axis in image["python_units"]:
                        self._bytes(axis["unit"], hex_value)
                        self._bytes(axis["raw_return"]["items"][2], hex_value)

    def test_lone_surrogates_preserved_marked_and_fail(self):
        for text, expected_points, indices in (("A\ud800Z", ["U+0041", "U+D800", "U+005A"], [1]),
                                               ("\udfff", ["U+DFFF"], [0])):
            with self.subTest(text=repr(text)):
                child, report, raw, _ = self._probe({"name": {"kind": "value", "value": text}})
                self.assertNotEqual(child.returncode, 0)
                self._scope(report)
                self.assertEqual(report["status"], "FAIL")
                observed = report["images"][0]["python_readback"]
                self.assertEqual(observed["value"], text)
                self.assertEqual(observed["codepoints"], expected_points)
                self.assertEqual(observed["surrogate_indices"], indices)
                self.assertTrue(observed["contains_surrogates"])
                self.assertTrue(raw.isascii())
                self.assertTrue(any(error["code"] == "surrogate_codepoint" for error in report["errors"]))

    def test_unexpected_text_type_fails_but_retains_values_and_other_getters(self):
        for field, value in (("name", 37), ("name", None), ("unit", 89)):
            with self.subTest(field=field, value=value):
                child, report, _, _ = self._probe({field: {"kind": "value", "value": value}})
                self.assertNotEqual(child.returncode, 0)
                self._scope(report)
                self.assertEqual(report["status"], "FAIL")
                image = report["images"][0]
                observed = image["python_readback"] if field == "name" else image["python_units"][0]["unit"]
                self.assertEqual(observed["value"], value)
                self.assertNotIn("codepoints", observed)
                self.assertEqual(len(image["python_units"]), 2)
                self.assertTrue(any(error["code"] == "unexpected_text_type" for error in report["errors"]))

    def test_surrogate_unit_is_saved_without_losing_name_or_raw_tuple(self):
        child, report, raw, _ = self._probe({"unit": {"kind": "value", "value": "m\ud800"}})
        self.assertNotEqual(child.returncode, 0)
        self._scope(report)
        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["images"][2]["python_readback"]["value"], "中文")
        axis = report["images"][0]["python_units"][0]
        self.assertEqual(axis["unit"]["value"], "m\ud800")
        self.assertEqual(axis["unit"]["codepoints"], ["U+006D", "U+D800"])
        self.assertEqual(axis["unit"]["surrogate_indices"], [1])
        self.assertEqual(axis["raw_return"]["items"][2], axis["unit"])
        self.assertTrue(raw.isascii())

    def test_getter_and_encoding_exceptions_are_retained_before_exit(self):
        for field, kind in (("name", "getter_error"), ("name", "encoding_error"),
                            ("name", "decoding_error"),
                            ("unit", "getter_error"), ("setter", "encoding_error")):
            with self.subTest(field=field, kind=kind):
                child, report, _, _ = self._probe({field: {"kind": kind}})
                self.assertNotEqual(child.returncode, 0)
                self._scope(report)
                self.assertEqual(report["status"], "FAIL")
                self.assertEqual(len(report["images"]), 5)
                self.assertEqual(len(report["images"][0]["python_units"]), 2)
                errors = [error for error in report["errors"] if error["code"] == "call_exception"]
                self.assertTrue(errors)
                expected = {"encoding_error": "builtins.UnicodeEncodeError",
                            "decoding_error": "builtins.UnicodeDecodeError",
                            "getter_error": "builtins.RuntimeError"}[kind]
                self.assertEqual(errors[0]["detail"]["type"], expected)
                self.assertIn("repr", errors[0]["detail"])
                if kind in ("encoding_error", "decoding_error"):
                    encoding_error = errors[0]["detail"]["unicode_error"]
                    self.assertEqual(encoding_error["encoding"], "utf-8")
                    if kind == "encoding_error":
                        self.assertEqual(encoding_error["object"]["value"], "A\ud800")
                        self.assertEqual(encoding_error["object"]["codepoints"], ["U+0041", "U+D800"])
                        self.assertEqual((encoding_error["start"], encoding_error["end"]), (1, 2))
                    else:
                        self._bytes(encoding_error["object"], "ff80")
                        self.assertEqual((encoding_error["start"], encoding_error["end"]), (0, 1))
                if field == "unit":
                    self.assertEqual(report["images"][2]["python_readback"]["value"], "中文")
                    self.assertEqual(report["images"][0]["python_units"][0]["raw_return"]["type"], "exception")
                elif field == "name":
                    self.assertEqual(report["images"][0]["python_readback"]["type"], "exception")
                    self.assertEqual(report["images"][0]["python_units"][0]["unit"]["value"], "µm")

    def test_bad_calibration_return_and_nonfinite_values_are_retained(self):
        for state in ({"calibration": {"kind": "value", "value": [3.5, "bad"]}},
                      {"nonfinite_zero": True}):
            with self.subTest(state=state):
                child, report, raw, _ = self._probe(state)
                self.assertNotEqual(child.returncode, 0)
                self._scope(report)
                self.assertEqual(report["status"], "FAIL")
                axis = report["images"][0]["python_units"][0]
                self.assertIn("raw_return", axis)
                self.assertEqual(report["images"][0]["python_readback"]["value"], "Short")
                self.assertNotIn(b": NaN", raw)
                if state.get("nonfinite_zero"):
                    self.assertEqual(axis["raw_return"]["items"][0], {"type": "float", "value": "nan"})
                    self.assertEqual(axis["unit"]["value"], "µm")
                else:
                    self.assertEqual(axis["raw_return"]["items"][1]["value"], "bad")

    def test_existing_evidence_is_untouched_before_any_host_call(self):
        original = b"\x00previous evidence\xff\r\n"
        child, report, raw, calls = self._probe(existing=original)
        self.assertNotEqual(child.returncode, 0)
        self.assertIsNone(report)
        self.assertEqual(raw, original)
        self.assertEqual(calls, [])
        self.assertIn(b"FileExistsError", child.stderr)

    def test_missing_session_saves_failure_before_host_calls(self):
        child, report, _, calls = self._probe(session=None)
        self.assertNotEqual(child.returncode, 0)
        self._scope(report)
        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["images"], [])
        self.assertEqual(calls, [])
        self.assertEqual(report["errors"][0]["detail"]["type"], "builtins.ValueError")

    def test_probe_parses_with_python37_grammar(self):
        for path in (PROBE, Path(__file__)):
            source = path.read_text(encoding="utf-8")
            if sys.version_info >= (3, 8):
                ast.parse(source, feature_version=7)
            else:
                ast.parse(source)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--run-unicode-probe":
        _run_fake_probe(sys.argv[2])
    else:
        unittest.main()
