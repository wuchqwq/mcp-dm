"""End-to-end synthetic result-package, preview and replay checks."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import numpy as np
try:
    from PIL import Image
    import matplotlib  # noqa: F401
    HAS_ANALYSIS_DEPS = True
except ImportError:
    HAS_ANALYSIS_DEPS = False


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
WORKER = os.path.join(ROOT, "tools", "analysis_worker.py")


@unittest.skipUnless(HAS_ANALYSIS_DEPS, "install requirements-analysis.txt in external Python")
class Analysis2DWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dm_2d_worker_test_")
        self.addCleanup(self.temp.cleanup)
        self.capture = os.path.join(self.temp.name, "capture")
        os.makedirs(self.capture)
        self.result = os.path.join(self.temp.name, "result")
        self.replay_result = os.path.join(self.temp.name, "replayed")
        x = np.arange(64, dtype="float64")[None, :]
        self.source_pixels = np.broadcast_to(100.0 + 2.0 * np.cos(2 * np.pi * 8 * (x - 8) / 32), (48, 64)).astype("float32").copy()
        self.original = self.source_pixels.copy()
        path = os.path.join(self.capture, "input.npy")
        with open(path, "xb") as stream:
            np.save(stream, self.source_pixels, allow_pickle=False)
        digest = self.sha(path)
        self.capture_id = "synthetic-capture-4d31"
        info = {
            "schema_version": 1, "capture_id": self.capture_id,
            "shape_yx": [48, 64], "dtype": "float32", "source_image_id": 812,
            "source_shape_yx": [68, 74], "source_rect_xyxy": [10, 20, 74, 68],
            "source_rect_convention": "zero-based half-open [x0,y0,x1,y1]",
            "source_calibration_dm": [
                {"dm_dimension": 0, "numpy_axis": 1, "axis": "x", "scale": -0.25, "unit": "nm",
                 "origin": -5.0, "calibrated_value_at_pixel_zero": 1.25, "size": 64},
                {"dm_dimension": 1, "numpy_axis": 0, "axis": "y", "scale": 0.5, "unit": "nm",
                 "origin": 4.0, "calibrated_value_at_pixel_zero": -2.5, "size": 48}],
            "working_calibration_xy": [
                {"axis": "x", "scale": -0.25, "unit": "nm", "calibrated_value_at_pixel_zero": 1.25, "size": 64},
                {"axis": "y", "scale": 0.5, "unit": "nm", "calibrated_value_at_pixel_zero": -2.5, "size": 48}],
            "pixel_coordinate_model": "pixel centers at integer x,y",
            "intensity_calibration": {"origin": 0.0, "scale": 1.0, "unit": "counts"},
            "input_file": "input.npy", "input_sha256": digest, "source_path_included": False,
        }
        self.write_json(os.path.join(self.capture, "input.json"), info)
        info_hash = hashlib.sha256(json.dumps(info, ensure_ascii=False, sort_keys=True,
                                             separators=(",", ":")).encode("utf-8")).hexdigest()
        self.write_json(os.path.join(self.capture, "capture.json"), {
            "schema_version": 1, "capture_id": self.capture_id, "state": "captured",
            "input_sha256": digest, "input_metadata_sha256": info_hash,
            "source_image_id": 812})

    @staticmethod
    def sha(path):
        digest = hashlib.sha256()
        with open(path, "rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    @staticmethod
    def write_json(path, value):
        with open(path, "x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def read_json(path):
        with open(path, encoding="utf-8") as stream:
            return json.load(stream)

    def worker(self, request, expected=0):
        run = subprocess.run([sys.executable, WORKER], input=json.dumps(request),
                             text=True, capture_output=True, cwd=ROOT, timeout=180)
        self.assertEqual(run.returncode, expected, run.stderr + run.stdout)
        result = json.loads(run.stdout)
        return result

    def test_preview_mapping_overlays_fixed_input_and_display_only_scaling(self):
        source_hash = self.sha(os.path.join(self.capture, "input.npy"))
        request = {"action": "preview", "capture_dir": self.capture,
                   "max_side": 32, "roi": [18, 32, 50, 56],
                   "profile": {"start": [18, 44], "end": [49, 44], "width": 3}}
        result = self.worker(request)["result"]
        self.assertEqual(result["capture_id"], self.capture_id)
        self.assertTrue(result["preview_path"].endswith(".png"))
        self.assertEqual(result["preview_sha256"], self.sha(result["preview_path"]))
        self.assertEqual(result["mapping"]["preview_shape_yx"], [24, 32])
        self.assertEqual(result["mapping"]["source_rect_xyxy"], [10, 20, 74, 68])
        self.assertEqual(result["mapping"]["overlay"]["roi_source_xyxy"], [18, 32, 50, 56])
        with Image.open(result["preview_path"]) as preview:
            self.assertEqual(preview.size, (32, 24))
            self.assertEqual(preview.getpixel((4, 6)), (255, 32, 32))
            self.assertEqual(preview.getpixel((10, 12)), (0, 255, 64))
        self.assertEqual(source_hash, self.sha(os.path.join(self.capture, "input.npy")))
        self.source_pixels[0, 0] = -999
        self.assertEqual(result["input_sha256"], source_hash)

    def test_task_a_bundle_has_hand_checkable_results_and_independent_replay(self):
        source_hash = self.sha(os.path.join(self.capture, "input.npy"))
        # Emulate editing the DM source after capture; every downstream result
        # must continue to describe the saved input.npy copy.
        self.source_pixels[:] = -999.0
        np.testing.assert_array_equal(np.load(os.path.join(self.capture, "input.npy")), self.original)
        request = {"action": "analyze", "capture_dir": self.capture,
                   "result_dir": self.result, "operation_id": "synthetic-op-1",
                   "roi": [18, 32, 50, 56], "profile": {"start": [18, 44], "end": [49, 44], "width": 1},
                   "top_n": 4}
        response = self.worker(request)
        self.assertTrue(response["ok"], response)
        result = response["result"]
        self.assertEqual(result["state"], "succeeded")
        self.assertEqual(result["stats"]["finite_count"], 24 * 32)
        self.assertAlmostEqual(result["stats"]["mean"], 100.0, places=6)
        self.assertAlmostEqual(result["stats"]["stddev"], np.sqrt(2), places=5)
        self.assertEqual(result["profile_points"], 32)
        self.assertEqual(result["fft_shape_yx"], [24, 32])
        stats = self.read_json(os.path.join(self.result, "stats.json"))
        self.assertEqual(stats["calibration_xy"][0]["calibrated_value_at_pixel_zero"], -0.75)
        self.assertEqual(stats["calibration_xy"][1]["calibrated_value_at_pixel_zero"], 3.5)
        profile = self.read_json(os.path.join(self.result, "profile.json"))
        self.assertEqual(profile["request"]["start"], [18.0, 44.0])
        self.assertAlmostEqual(profile["distance"][-1], 7.75)
        for i in range(32):
            expected = 100 + 2 * np.cos(2 * np.pi * 8 * i / 32)
            self.assertAlmostEqual(profile["values"][i], expected, places=5)
        fft = np.load(os.path.join(self.result, "fft_magnitude.npy"), allow_pickle=False)
        self.assertAlmostEqual(float(fft[12, 16 + 8]), 24 * 32, places=4)
        self.assertAlmostEqual(float(fft[12, 16 - 8]), 24 * 32, places=4)
        fft_info = self.read_json(os.path.join(self.result, "fft.json"))
        peak = next(p for p in fft_info["peaks"] if p["dy"] == 0 and p["dx"] == 8)
        self.assertEqual(peak["fx"], -1.0)
        self.assertEqual(peak["frequency_unit"] if "frequency_unit" in peak else peak["fx_unit"], "1/(nm)")
        self.assertEqual(source_hash, self.sha(os.path.join(self.capture, "input.npy")))
        bundle_copy = np.load(os.path.join(self.result, "input.npy"), allow_pickle=False)
        np.testing.assert_array_equal(bundle_copy, self.original)
        for name in ("report.md", "replay.py", "analysis_worker.py", "analysis2d_core.py",
                     "input_preview.png", "selection_overlay.png", "profile.png", "fft.png",
                     "capture.json", "environment.json", "manifest.json"):
            self.assertTrue(os.path.isfile(os.path.join(self.result, name)), name)
        self.assertFalse(os.path.exists(os.path.join(self.result, "__pycache__")))
        manifest = self.read_json(os.path.join(self.result, "manifest.json"))
        self.assertEqual(manifest["state"], "succeeded")
        self.assertIn("fft_magnitude.npy", manifest["outputs"])
        replay = subprocess.run([sys.executable, os.path.join(self.result, "replay.py"), "--verify"],
                                text=True, capture_output=True, timeout=180)
        self.assertEqual(replay.returncode, 0, replay.stderr + replay.stdout)
        self.assertEqual(json.loads(replay.stdout)["result"]["state"], "verified")
        regenerated = subprocess.run([sys.executable, os.path.join(self.result, "replay.py"), "--output", self.replay_result],
                                     text=True, capture_output=True, timeout=180)
        self.assertEqual(regenerated.returncode, 0, regenerated.stderr + regenerated.stdout)
        self.assertEqual(json.loads(regenerated.stdout)["result"]["state"], "succeeded")
        np.testing.assert_allclose(np.load(os.path.join(self.replay_result, "fft_magnitude.npy")), fft,
                                   rtol=1e-10, atol=1e-12)
        cached = self.worker(request)
        self.assertEqual(cached["result"]["state"], "succeeded")
        mismatch = dict(request, top_n=2)
        self.assertFalse(self.worker(mismatch, expected=2)["ok"])
        node = shutil.which("node")
        if node:
            mcp_result = os.path.join(self.temp.name, "mcp_result")
            env = dict(os.environ, DM_ANALYSIS_PYTHON=sys.executable,
                       DM_ANALYSIS_TEST_CAPTURE_DIR=self.capture,
                       DM_ANALYSIS_TEST_RESULT_DIR=mcp_result)
            client = subprocess.run([node, os.path.join(ROOT, "tests", "analysis2d_mcp_acceptance.mjs")],
                                    text=True, capture_output=True, cwd=ROOT, env=env, timeout=180)
            self.assertEqual(client.returncode, 0, client.stderr + client.stdout)
            self.assertEqual(json.loads(client.stdout)["preview_image_block"], "PASS")

    def test_invalid_selection_hash_change_and_unknown_operation_do_not_compute(self):
        invalid = {"action": "preview", "capture_dir": self.capture, "roi": [8, 8, 99, 99]}
        self.assertFalse(self.worker(invalid, expected=2)["ok"])
        running_dir = os.path.join(self.temp.name, "running")
        os.makedirs(running_dir)
        self.write_json(os.path.join(running_dir, "manifest.json"),
                        {"state": "running", "operation_id": "still-running"})
        state = self.worker({"action": "result", "result_dir": running_dir})["result"]
        self.assertEqual(state["state"], "unknown")
        metadata_path = os.path.join(self.capture, "input.json")
        with open(metadata_path, "rb") as stream:
            original_metadata = stream.read()
        altered = json.loads(original_metadata.decode("utf-8"))
        altered["working_calibration_xy"][0]["scale"] *= 2
        with open(metadata_path, "w", encoding="utf-8") as stream:
            json.dump(altered, stream)
        metadata_tamper = self.worker({"action": "preview", "capture_dir": self.capture}, expected=2)
        self.assertIn("metadata hash mismatch", metadata_tamper["error"])
        with open(metadata_path, "wb") as stream:
            stream.write(original_metadata)
        with open(os.path.join(self.capture, "input.npy"), "ab") as stream:
            stream.write(b"tamper")
        tampered = self.worker({"action": "preview", "capture_dir": self.capture}, expected=2)
        self.assertIn("hash mismatch", tampered["error"])


if __name__ == "__main__":
    unittest.main()
