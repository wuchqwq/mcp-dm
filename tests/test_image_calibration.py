"""Independent hand-computable XY geometry and immutable workspace tests."""
import hashlib
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import tifffile

from tools import image_calibration as cal
from tools import image_workspace as engine


class ImageCalibrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="image-calibration-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / "workspace"
        self.source = self.root / "synthetic.tiff"
        self.values = np.arange(2 * 80 * 120, dtype=np.uint16).reshape(2, 80, 120)
        tifffile.imwrite(self.source, self.values, photometric="minisblack", metadata={"axes": "IYX"})
        self.original = self.source.read_bytes()
        self.counter = 0
        self.sequence = self.ok("open", source_path=str(self.source))
        self.frame = self.ok("frame", object_id=self.sequence["object_id"], frame_index=0)

    def request(self, action, **args):
        self.counter += 1
        return {"workspace": str(self.workspace), "action": action, "request_id": "cal-{}".format(self.counter), **args}

    def ok(self, action, **args):
        response = engine.execute(self.request(action, **args))
        self.assertTrue(response["ok"], response)
        return response["result"]

    def calibration(self, object_id=None, scope="image", x=.2, y=-.5, unit="nm", **kwargs):
        return self.ok("calibrate", object_id=object_id or self.frame["object_id"], scope=scope,
                       xy_scale={"x": x, "y": y, "unit": unit}, source_text="synthetic explicit signed XY statement", **kwargs)

    def test_signed_anisotropic_spatial_distance_angle_and_unknown_uncertainty(self):
        selected = self.calibration()
        result = self.ok("measure", object_id=selected["object_id"], points=[[1, 2], [4, 6]])
        self.assertEqual(result["distance_pixels"], 5)
        self.assertAlmostEqual(result["physical_distance"], math.sqrt(.6 ** 2 + 2 ** 2))
        self.assertAlmostEqual(result["physical_angle_degrees"], math.degrees(math.atan2(-2, .6)))
        self.assertEqual(result["physical_vector_xy"], [.6000000000000001, -2.])
        self.assertEqual(result["physical_unit"], "nm")
        self.assertTrue(result["physical_angle"])
        self.assertIsNone(result["measurement_uncertainty"])
        self.assertEqual(result["xy_calibration"]["uncertainty_status"], "unknown")
        self.assertEqual(self.source.read_bytes(), self.original)
        np.testing.assert_array_equal(np.load(self.frame["array_path"]), self.values[0])

    def test_sequence_inheritance_exact_scope_and_existing_saved_fft_attachment(self):
        fft = self.ok("fft", object_id=self.frame["object_id"], rect=[10, 10, 26, 18])
        original = Path(fft["array_path"]).read_bytes()
        selected = self.calibration(self.sequence["object_id"], "sequence")
        frame = self.ok("frame", object_id=selected["object_id"], frame_index=1)
        self.assertEqual(frame["xy_calibration"], selected["xy_calibration"])
        attached = self.ok("calibrate", object_id=fft["object_id"], calibration_object_id=selected["object_id"])
        self.assertEqual(attached["xy_calibration"], selected["xy_calibration"])
        with patch.object(np.fft, "fft2", side_effect=AssertionError("saved FFT must not recompute")):
            revised = self.ok("view", object_id=attached["object_id"], spectrum_axes=True, max_size=512, upscale=True)
            measured = self.ok("measure", object_id=revised["object_id"], coordinate_space="frequency_cycles_per_pixel",
                               points=[[0, 0], [.125, .25]])
        self.assertEqual(Path(revised["array_path"]).read_bytes(), original)
        self.assertEqual(measured["physical_vector_xy"], [.625, -.5])
        magnitude = math.sqrt(.625 ** 2 + .5 ** 2)
        self.assertAlmostEqual(measured["physical_frequency_magnitude"], magnitude)
        self.assertAlmostEqual(measured["d_spacing"], 1. / magnitude)
        self.assertEqual(measured["physical_frequency_unit"], "cycles/nm")
        self.assertEqual(measured["calibration_dependency"]["calibration_id"], selected["object_id"])
        self.assertEqual(revised["display"]["axis_labels_unit"], "cycles/nm")
        self.assertAlmostEqual(revised["physical_frequency_axes"][0]["step"], -.25)
        self.assertAlmostEqual(revised["physical_frequency_axes"][1]["step"], .3125)
        self.assertEqual(revised["panels"][0]["unit"], "cycles/pixel")
        self.assertFalse(revised["fft_recomputed"])

    def test_calibration_revisions_withdrawal_and_old_exports_stay_identical(self):
        first = self.calibration()
        view = self.ok("view", object_id=first["object_id"], max_size=320, upscale=True)
        self.assertTrue(view["scale_bar"]["visible"])
        bar = view["scale_bar"]
        self.assertAlmostEqual(bar["source_length_pixels"] * .2, bar["length"])
        self.assertEqual(bar["calibration_id"], first["object_id"])
        destination = self.root / "old-export"
        exported = self.ok("export", object_id=view["object_id"], output_dir=str(destination))
        hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in destination.iterdir()}
        measured = self.ok("measure", object_id=view["object_id"], points=[[1, 1], [4, 5]])
        revised = self.calibration(measured["object_id"], x=.4, y=.5)
        self.assertEqual(revised["xy_calibration"]["revision"], 2)
        self.assertEqual(revised["xy_calibration"]["previous_calibration_id"], first["object_id"])
        self.assertIn("stale", revised["calibration_review"]["physical_measurements"])
        self.assertEqual(revised["calibration_review"]["old_measurement_object_id"], measured["object_id"])
        withdrawn = self.ok("calibrate", object_id=revised["object_id"], scope="image", xy_scale=None,
                            source_text="synthetic user explicitly withdrew the calibration")
        self.assertEqual(withdrawn["xy_calibration"]["revision"], 3)
        self.assertEqual(withdrawn["xy_calibration"]["status"], "withdrawn")
        attach_frame = self.ok("calibrate", object_id=self.frame["object_id"], calibration_object_id=withdrawn["object_id"])
        unscaled = self.ok("view", object_id=attach_frame["object_id"], max_size=320, upscale=True)
        self.assertIsNone(unscaled["scale_bar"])
        pixel = self.ok("measure", object_id=unscaled["object_id"], points=[[1, 1], [4, 5]])
        self.assertIsNone(pixel["physical_distance"])
        self.assertEqual(pixel["distance_pixels"], 5.)
        self.assertFalse(pixel["physical_angle"])
        self.assertEqual(hashes, {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in destination.iterdir()})
        self.assertTrue(engine.execute({"workspace": str(self.workspace), "action": "result", "query_request_id": exported["request_id"]})["ok"])

    def test_same_request_recovery_conflict_missing_id_and_no_raw_metadata_rewrite(self):
        request = self.request("calibrate", object_id=self.frame["object_id"], scope="image",
                               xy_scale={"x": .2, "y": .2, "unit": "nm"}, source_text="synthetic assertion")
        response = engine.execute(request)
        self.assertTrue(response["ok"], response)
        self.assertEqual(engine.execute(dict(request)), response)
        recovered = engine.execute({"workspace": str(self.workspace), "action": "result", "query_request_id": request["request_id"]})
        self.assertEqual(recovered, response)
        conflict = engine.execute({**request, "source_text": "different statement"})
        self.assertEqual(conflict["error"]["code"], "REQUEST_CONFLICT")
        self.assertFalse(engine.execute({k: v for k, v in request.items() if k != "request_id"})["ok"])
        original_frame = self.ok("get", object_id=self.frame["object_id"])
        self.assertNotIn("xy_calibration", original_frame)
        self.assertEqual(original_frame["calibration"], {"status": "unknown", "unit": None})
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_unknown_legacy_context_never_activates_scientific_scale(self):
        legacy = self.ok("context", object_id=self.frame["object_id"], metadata={"xy_scale": {
            "x": .1, "y": .1, "unit": "nm", "source": "old descriptive context"}})
        measured = self.ok("measure", object_id=legacy["object_id"], points=[[0, 0], [3, 4]])
        self.assertEqual(measured["distance_pixels"], 5.)
        self.assertIsNone(measured["physical_distance"])
        self.assertFalse(measured["physical_angle"])
        fft = self.ok("fft", object_id=legacy["object_id"])
        measured_fft = self.ok("measure", object_id=fft["object_id"], points=[[0, 0], [.125, 0]])
        self.assertEqual(measured_fft["pixel_period"], 8.)
        self.assertIsNone(measured_fft["d_spacing"])

    def test_unit_equivalence_no2pi_signed_odd_rectangular_and_dc(self):
        for unit, x, y, metres in [("nm", .2, -.5, 1e-9), ("Å", 2., -5., 1e-10),
                                   ("um", .0002, -.0005, 1e-6)]:
            selected = self.calibration(x=x, y=y, unit=unit)
            measured = self.ok("measure", object_id=selected["object_id"], points=[[0, 0], [3, 4]])
            self.assertAlmostEqual(measured["physical_distance"] * metres, math.sqrt(.6 ** 2 + 2. ** 2) * 1e-9, places=20)
        record = {"status": "active", "calibration_id": "synthetic", "revision": 1,
                  "xy_scale": cal.validated_scale({"x": .2, "y": -.5, "unit": "nm"})}
        axes = cal.frequency_axes([9, 15], record)
        self.assertAlmostEqual(axes[0]["step"], -2 / 9)
        self.assertAlmostEqual(axes[1]["value_at_index_zero"], -7 / 3)
        self.assertAlmostEqual(cal.geometry(.125, 0, record, frequency=True)["period"], 1.6)
        fft = self.ok("fft", object_id=self.frame["object_id"], rect=[0, 0, 15, 9])
        attached = self.ok("calibrate", object_id=fft["object_id"], calibration_object_id=selected["object_id"])
        dc = self.ok("measure", object_id=attached["object_id"], points=[[0, 0], [0, 0]])
        self.assertIsNone(dc["period"])
        self.assertIsNone(dc["d_spacing"])
        self.assertIn("DC", dc["zero_frequency_reason"])

    def test_reject_bad_scales_missing_source_mixed_source_and_frame_scope_leaks(self):
        selected = self.calibration()
        second_frame = self.ok("frame", object_id=self.sequence["object_id"], frame_index=1)
        refused = engine.execute(self.request("calibrate", object_id=second_frame["object_id"], calibration_object_id=selected["object_id"]))
        self.assertEqual(refused["error"]["code"], "CALIBRATION_SCOPE_MISMATCH")
        reopened = self.ok("open", source_path=str(self.source))
        seq_cal = self.calibration(self.sequence["object_id"], "sequence")
        self.assertFalse(engine.execute(self.request("calibrate", object_id=reopened["object_id"], calibration_object_id=seq_cal["object_id"]))["ok"])
        composite = self.ok("compare", object_ids=[self.frame["object_id"], second_frame["object_id"]])
        self.assertFalse(engine.execute(self.request("calibrate", object_id=composite["object_id"], scope="image",
                                                      xy_scale={"x": .1, "y": .1, "unit": "nm"}, source_text="bad mixed frame"))["ok"])
        for scale in ({"x": 0, "y": 1, "unit": "nm"}, {"x": True, "y": 1, "unit": "nm"},
                      {"x": .1, "unit": "nm"}, {"x": 1, "y": 1, "unit": "radians"},
                      {"x": 1, "y": 1, "unit": "1/nm"}, {"x": 1, "y": 1, "unit": "nm", "uncertainty_x": -1}):
            self.assertFalse(engine.execute(self.request("calibrate", object_id=self.frame["object_id"], scope="image", xy_scale=scale,
                                                          source_text="synthetic invalid scale"))["ok"], scale)
        self.assertFalse(engine.execute(self.request("calibrate", object_id=self.frame["object_id"], scope="image", xy_scale=None,
                                                      source_text="no prior record"))["ok"])
        self.assertFalse(engine.execute(self.request("calibrate", object_id=self.frame["object_id"], scope="image",
                                                      xy_scale={"x": 1, "y": 1, "unit": "nm"}, source_text=" "))["ok"])
        self.assertFalse(engine.execute(self.request("calibrate", object_id=self.frame["object_id"], calibration_object_id=selected["object_id"],
                                                      scope="image"))["ok"])

    def test_source_coordinate_measurement_after_crops_and_calibrated_overlay(self):
        selected = self.calibration()
        view = self.ok("view", object_id=selected["object_id"], rect=[20, 10, 100, 70], max_size=320, upscale=True)
        revised = self.ok("view", object_id=view["object_id"], rect=[5, 4, 60, 50], gamma=2)
        measured = self.ok("measure", object_id=revised["object_id"], points=[[25, 14], [28, 18]])
        self.assertEqual(measured["distance_pixels"], 5)
        self.assertEqual(measured["source_rect_xyxy"], [25, 14, 80, 60])
        self.assertFalse(engine.execute(self.request("measure", object_id=revised["object_id"], points=[[0, 0], [3, 4]]))["ok"])
        annotated = self.ok("annotate", object_id=revised["object_id"], annotations=[{
            "annotation_id": "guide", "kind": "arrow", "coordinate_space": "source_pixels",
            "source_object_id": self.frame["object_id"], "coordinates": [35, 20, 40, 25], "status": "hypothesized"}])
        wrapped = self.calibration(annotated["object_id"], x=.4, y=.5)
        bad_annotation = engine.execute(self.request("annotate", object_id=wrapped["object_id"], updates=[{"annotation_id": "guide", "text": "new"}]))
        self.assertEqual(bad_annotation["error"]["code"], "STALE_CALIBRATION_DISPLAY")
        refused = engine.execute(self.request("export", object_id=wrapped["object_id"], output_dir=str(self.root / "stale")))
        self.assertEqual(refused["error"]["code"], "STALE_CALIBRATION_DISPLAY")
        fresh = self.ok("view", object_id=wrapped["object_id"], gamma=.8)
        self.assertEqual(fresh["annotations"][0]["anchor"], annotated["annotations"][0]["anchor"])
        self.assertEqual(fresh["annotations"][0]["status"], "hypothesized")
        self.assertEqual(fresh["scale_bar"]["calibration_id"], wrapped["object_id"])
        self.ok("export", object_id=fresh["object_id"], output_dir=str(self.root / "fresh"))
        manifest = json.loads((self.root / "fresh" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["xy_calibration"]["calibration_id"], wrapped["object_id"])
        self.assertTrue(manifest["scientific_NPY_is_not_display_PNG"])
        self.assertFalse(manifest["dm_save_as_called"])

    def test_physical_tick_labels_fit_canvas_and_dc_is_at_original_bin(self):
        # A non-round real-space scale previously produced a clipped long
        # negative Y label and an artificial near-zero midpoint on even FFTs.
        fft = self.ok("fft", object_id=self.frame["object_id"], rect=[0, 0, 64, 64])
        calibrated = self.calibration(fft["object_id"], x=.0524, y=.0524)
        drawn, real_draw = [], engine.ImageDraw.Draw
        def capture(*args, **kwargs):
            draw = real_draw(*args, **kwargs)
            real_text = draw.text
            def text(position, label, *a, **kw):
                if kw.get("anchor") in ("rm", "mt"):
                    try:
                        float(label)
                    except ValueError:
                        pass
                    else:
                        drawn.append(draw.textbbox(position, label, font=kw.get("font"), anchor=kw.get("anchor")))
                return real_text(position, label, *a, **kw)
            draw.text = text
            return draw
        with patch.object(engine.ImageDraw, "Draw", side_effect=capture):
            result = self.ok("view", object_id=calibrated["object_id"], spectrum_axes=True, max_size=256, upscale=True)
        with engine.Image.open(result["image_path"]) as image:
            width, height = image.size
        self.assertEqual(len(drawn), 6)
        self.assertTrue(all(0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height for x0, y0, x1, y1 in drawn), drawn)
        for axis in ("fx", "fy"):
            rows = result["display"]["axis_ticks"][axis]
            dc = next(row for row in rows if row["label"] == "0")
            self.assertEqual(dc["bin_index"], 32)
            self.assertEqual(dc["cycles_per_pixel"], 0.)
            self.assertEqual(dc["value"], 0.)
        panel = result["panels"][0]
        left, top, right, bottom = panel["image_rect_xyxy"]
        dc = result["display"]["axis_ticks"]["fx"][1]
        self.assertAlmostEqual(dc["image_coordinate"], left + 32.5 * (right-left) / 64 - .5)
        self.assertNotEqual(dc["image_coordinate"], (left+right-1)/2)
        self.assertEqual(Path(result["array_path"]).read_bytes(), Path(fft["array_path"]).read_bytes())

    def test_narrow_physical_frequency_ticks_remain_distinct_and_visible_without_recentring(self):
        # A narrow near-Nyquist crop needs more than four significant digits.
        shown = np.zeros((3, 100000), dtype=np.float64)
        record = {"status": "active", "calibration_id": "synthetic", "revision": 1,
                  "xy_scale": cal.validated_scale({"x": .0524, "y": -.075, "unit": "nm"})}
        settings = {"max_size": 512, "upscale": True, "gamma": .8, "display_range": [0., 1.],
                    "representation": "log_amplitude", "spectrum_axes": True, "frequency_rect": [99000, 0, 99004, 3]}
        image, panel = engine.spectrum_canvas(shown, settings, "a" * 32, record)
        rows = settings["axis_ticks"]["fx"]
        self.assertEqual(len(set(row["label"] for row in rows)), 3)
        self.assertTrue(all(row["cycles_per_pixel"] > .48 for row in rows))
        self.assertTrue(all(float(row["label"]) > 9. for row in rows))
        self.assertFalse(panel["dc_visible"])
        self.assertEqual(panel["fft_rect_xyxy"], [99000, 0, 99004, 3])
        self.assertLessEqual(image.width, 512)
