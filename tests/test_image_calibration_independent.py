"""Independent, hand-enumerable calibration/identity/render checks.

No vendor API or experimental file is used. Expected 3-4-5 vectors, original
FFT bin positions and scale-bar lengths are stated explicitly, rather than
computed with the production conversion helpers.
"""
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image
import tifffile

from tools import image_workspace as engine


class IndependentCalibrationChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="independent-calibration-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / "workspace"
        self.source = self.root / "two-frames.tiff"
        self.values = np.arange(32 * 48, dtype=np.uint16).reshape(32, 48)
        tifffile.imwrite(self.source, np.stack([self.values, self.values + 2000]),
                         photometric="minisblack", metadata=None)
        self.source_before = self.source.read_bytes()
        self.counter = 0
        self.opened = self.ok("open", source_path=str(self.source))
        self.frame = self.ok("frame", object_id=self.opened["object_id"], frame_index=0)

    def call(self, action, **arguments):
        self.counter += 1
        return engine.execute({"action": action, "workspace": str(self.workspace),
                               "request_id": "independent-calibration-" + str(self.counter), **arguments})

    def ok(self, action, **arguments):
        reply = self.call(action, **arguments)
        self.assertTrue(reply["ok"], reply)
        return reply["result"]

    def calibrate(self, object_id=None, x=-.5, y=2., unit="nm", scope="image"):
        return self.ok("calibrate", object_id=object_id or self.frame["object_id"], scope=scope,
                       xy_scale={"x": x, "y": y, "unit": unit},
                       source_text="Synthetic user statement, not an experimental calibration")

    def assert_source_unchanged(self):
        self.assertEqual(self.source.read_bytes(), self.source_before)
        np.testing.assert_array_equal(np.load(self.frame["array_path"]), self.values)

    def test_signed_anisotropic_spatial_vector_is_hand_enumerable_3_4_5(self):
        calibrated = self.calibrate()
        measured = self.ok("measure", object_id=calibrated["object_id"], points=[[2, 3], [8, 5]])
        # Six x pixels at -0.5 nm and two y pixels at 2 nm give (-3,4) nm.
        self.assertEqual(measured["physical_vector_xy"], [-3., 4.])
        self.assertEqual(measured["physical_distance"], 5.)
        self.assertEqual(measured["physical_unit"], "nm")
        self.assertAlmostEqual(measured["physical_angle_degrees"], 126.86989764584402, places=12)
        self.assertAlmostEqual(measured["distance_pixels"], math.sqrt(40), places=12)
        self.assertNotAlmostEqual(measured["physical_angle_degrees"], measured["image_coordinate_angle_degrees"])
        self.assertEqual(measured["uncertainty_status"], "unknown; localization uncertainty and scale covariance are not supplied")
        self.assert_source_unchanged()

    def test_no_calibration_retains_pixel_3_4_5_and_no_physical_angle(self):
        measured = self.ok("measure", object_id=self.frame["object_id"], points=[[2, 3], [5, 7]])
        self.assertEqual(measured["distance_pixels"], 5.)
        self.assertIsNone(measured["physical_distance"])
        self.assertIsNone(measured["physical_unit"])
        self.assertIsNone(measured["physical_angle_degrees"])
        self.assertFalse(measured["physical_angle"])

    def test_nonzero_geometry_underflow_refuses_instead_of_false_zero_or_dc(self):
        spatial = self.calibrate(x=1e-250, y=1., unit="m")
        refused = self.call("measure", object_id=spatial["object_id"], points=[[0, 0], [1e-100, 0]])
        self.assertFalse(refused["ok"], refused)
        self.assertEqual(refused["error"]["code"], "INVALID_ARGUMENT")
        reciprocal = self.calibrate(x=1e100, y=1., unit="m")
        fft = self.ok("fft", object_id=reciprocal["object_id"])
        refused = self.call("measure", object_id=fft["object_id"], points=[[0, 0], [1e-300, 0]])
        self.assertFalse(refused["ok"], refused)
        self.assertEqual(refused["error"]["code"], "INVALID_ARGUMENT")

    def test_reciprocal_3_4_5_uses_cycles_and_correct_signed_axis_not_2pi(self):
        calibrated = self.calibrate(x=-.05, y=.025)
        fft = self.ok("fft", object_id=calibrated["object_id"])
        measured = self.ok("measure", object_id=fft["object_id"], points=[[0., 0.], [.15, .1]])
        # .15 / -.05 = -3 and .1 / .025 = 4 cycles/nm: |g|=5, d=0.2 nm.
        np.testing.assert_allclose(measured["physical_vector_xy"], [-3., 4.], rtol=0, atol=1e-14)
        self.assertAlmostEqual(measured["physical_frequency_magnitude"], 5., places=14)
        self.assertEqual(measured["physical_frequency_unit"], "cycles/nm")
        self.assertAlmostEqual(measured["period"], .2, places=14)
        self.assertAlmostEqual(measured["d_spacing"], .2, places=14)
        self.assertEqual(measured["d_spacing_unit"], "nm")
        self.assertAlmostEqual(measured["physical_angle_degrees"], 126.86989764584402, places=12)
        self.assertEqual(fft["physical_frequency_axes"][0]["step"], 1.25)
        self.assertEqual(fft["physical_frequency_axes"][0]["value_at_index_zero"], -20.)
        self.assertAlmostEqual(fft["physical_frequency_axes"][1]["step"], -5. / 12., places=14)
        self.assertAlmostEqual(fft["physical_frequency_axes"][1]["value_at_index_zero"], 10., places=14)

    def test_two_non_dc_peaks_have_difference_period_without_claiming_d_spacing(self):
        calibrated = self.calibrate(x=-.05, y=.025)
        fft = self.ok("fft", object_id=calibrated["object_id"])
        measured = self.ok("measure", object_id=fft["object_id"], points=[[.1, .1], [.25, .2]])
        self.assertAlmostEqual(measured["period"], .2, places=14)
        self.assertIsNone(measured["d_spacing"])
        self.assertIsNone(measured["d_spacing_unit"])

    def test_angstrom_alias_keeps_unit_and_unknown_uncertainty_explicit(self):
        calibrated = self.calibrate(x=-.5, y=2., unit="Å")
        self.assertEqual(calibrated["xy_calibration"]["xy_scale"]["unit"], "angstrom")
        self.assertIsNone(calibrated["xy_calibration"]["xy_scale"]["uncertainty_x"])
        measured = self.ok("measure", object_id=calibrated["object_id"], points=[[2, 3], [8, 5]])
        self.assertEqual(measured["physical_distance"], 5.)
        self.assertEqual(measured["physical_unit"], "angstrom")
        self.assertIsNone(measured["measurement_uncertainty"])

    def test_sequence_scope_is_explicit_and_cannot_leak_to_a_second_open(self):
        calibrated = self.calibrate(object_id=self.opened["object_id"], x=.5, y=.5, scope="sequence")
        first = self.ok("frame", object_id=calibrated["object_id"], frame_index=0)
        second = self.ok("frame", object_id=calibrated["object_id"], frame_index=1)
        for frame in (first, second):
            measured = self.ok("measure", object_id=frame["object_id"], points=[[2, 3], [5, 7]])
            self.assertEqual(measured["physical_distance"], 2.5)
            self.assertEqual(measured["calibration_dependency"]["calibration_id"], calibrated["xy_calibration"]["calibration_id"])
        # Even the identical filename/hash in a separately opened handle does
        # not silently acquire the first immutable sequence's calibration.
        reopened = self.ok("open", source_path=str(self.source))
        other = self.ok("frame", object_id=reopened["object_id"], frame_index=0)
        refused = self.call("calibrate", object_id=other["object_id"], calibration_object_id=calibrated["object_id"])
        self.assertFalse(refused["ok"], refused)
        self.assertEqual(refused["error"]["code"], "CALIBRATION_SCOPE_MISMATCH")
        uncalibrated = self.ok("measure", object_id=other["object_id"], points=[[2, 3], [5, 7]])
        self.assertIsNone(uncalibrated["physical_distance"])
        # An existing frame from the original handle can opt into that exact scope.
        attached = self.ok("calibrate", object_id=self.frame["object_id"], calibration_object_id=calibrated["object_id"])
        self.assertEqual(attached["xy_calibration"], calibrated["xy_calibration"])
        self.assert_source_unchanged()

    def test_single_image_scope_refuses_another_frame_and_a_mixed_comparison(self):
        calibrated = self.calibrate()
        second = self.ok("frame", object_id=self.opened["object_id"], frame_index=1)
        other = self.call("calibrate", object_id=second["object_id"], calibration_object_id=calibrated["object_id"])
        self.assertFalse(other["ok"], other)
        self.assertEqual(other["error"]["code"], "CALIBRATION_SCOPE_MISMATCH")
        compared = self.ok("compare", object_ids=[self.frame["object_id"], second["object_id"]])
        mixed = self.call("calibrate", object_id=compared["object_id"], scope="image", xy_scale={"x": 1, "y": 1, "unit": "nm"}, source_text="Synthetic")
        self.assertFalse(mixed["ok"], mixed)

    def test_scale_bar_has_hand_checked_source_and_actual_display_length(self):
        calibrated = self.calibrate(x=-.5, y=2.)
        view = self.ok("view", object_id=calibrated["object_id"], max_size=192, upscale=True)
        bar = view["scale_bar"]
        # 48-pixel width at 0.5 nm/px: the 1-2-5 rule chooses 5 nm =10 px.
        self.assertEqual(bar["length"], 5.)
        self.assertEqual(bar["source_length_pixels"], 10.)
        self.assertEqual(bar["signed_scale"], -.5)
        self.assertEqual(bar["image_endpoints_xyxy"], [12, 115, 52., 115])
        with Image.open(view["image_path"]) as image:
            pixels = np.asarray(image.convert("RGB"))
        self.assertTrue(np.all(pixels[115, 12:53] == 255), "The recorded bar is actually drawn in the PNG")
        resized = self.ok("view", object_id=view["object_id"], max_size=384)
        self.assertEqual(resized["scale_bar"]["image_endpoints_xyxy"], [12, 243, 92., 243])
        self.assertEqual(resized["scale_bar"]["length"], 5.)
        self.assertEqual(Path(view["array_path"]).read_bytes(), Path(self.frame["array_path"]).read_bytes())
        self.assert_source_unchanged()

    def test_saved_fft_axis_labels_use_original_bins_and_new_calibration_without_fft(self):
        fft = self.ok("fft", object_id=self.frame["object_id"])
        original = Path(fft["array_path"]).read_bytes()
        calibrated = self.calibrate(object_id=fft["object_id"], x=-.05, y=.025)
        labels = []
        real_draw = engine.ImageDraw.Draw
        def capture_draw(*args, **kwargs):
            draw = real_draw(*args, **kwargs)
            real_text = draw.text
            def capture_text(position, text, *text_args, **text_kwargs):
                labels.append(text)
                return real_text(position, text, *text_args, **text_kwargs)
            draw.text = capture_text
            return draw
        with patch.object(engine.np.fft, "fft2", side_effect=AssertionError("Saved FFT must not be recomputed")), \
             patch.object(engine.ImageDraw, "Draw", side_effect=capture_draw):
            view = self.ok("view", object_id=calibrated["object_id"], spectrum_axes=True,
                           frequency_rect=[24, 16, 36, 24], max_size=384, upscale=True)
        # Original bins x24..35 map to fx0..11/48; signed -0.05 nm/px.
        self.assertIn("-4.583", labels)
        # Original bins y16..23 map to fy0..7/32; +0.025 nm/px.
        self.assertIn("8.75", labels)
        self.assertIn("fx/fy (cycles/nm)", labels)
        self.assertFalse(view["fft_recomputed"])
        self.assertEqual(Path(view["array_path"]).read_bytes(), original)
        self.assertEqual(view["panels"][0]["source_object_id"], fft["object_id"])
        self.assertEqual(view["panels"][0]["fft_rect_xyxy"], [24, 16, 36, 24])

    def test_comparison_bar_endpoints_locate_each_actual_global_image_panel(self):
        source = self.root / "larger-comparison.tiff"
        tifffile.imwrite(source, np.zeros((2, 64, 96), dtype=np.uint16),
                         photometric="minisblack", metadata=None)
        sequence = self.ok("open", source_path=str(source))
        calibrated = self.calibrate(object_id=sequence["object_id"], x=.5, y=.5, scope="sequence")
        first = self.ok("frame", object_id=calibrated["object_id"], frame_index=0)
        second = self.ok("frame", object_id=calibrated["object_id"], frame_index=1)
        compared = self.ok("compare", object_ids=[first["object_id"], second["object_id"]], max_size=192)
        for candidate in (compared, self.ok("view", object_id=compared["object_id"], max_size=256)):
            with Image.open(candidate["image_path"]) as image:
                pixels = np.asarray(image.convert("RGB"))
            for item in candidate["panels"]:
                left, top, right, bottom = item["image_rect_xyxy"]
                x0, y0, x1, y1 = item["scale_bar"]["image_endpoints_xyxy"]
                self.assertEqual(x0, left + 12)
                self.assertEqual(y0, bottom - 13)
                self.assertEqual(y0, y1)
                self.assertGreater(x1, x0)
                self.assertLess(x1, right)
                self.assertTrue(np.all(pixels[int(y0), math.ceil(x0):math.floor(x1) + 1] == 255))

    def test_revision_and_withdrawal_cannot_pair_old_render_with_new_scale(self):
        first = self.calibrate(x=.5, y=.5)
        view = self.ok("view", object_id=first["object_id"], max_size=192, upscale=True)
        marked = self.ok("annotate", object_id=view["object_id"], annotations=[
            {"annotation_id": "candidate", "kind": "arrow", "coordinates": [3, 3, 20, 10],
             "coordinate_space": "source_pixels", "source_object_id": self.frame["object_id"],
             "status": "user_confirmed", "text": "prior candidate"}])
        old_directory = self.root / "old-export"
        self.ok("export", object_id=marked["object_id"], output_dir=str(old_directory))
        old_files = {file.name: file.read_bytes() for file in old_directory.iterdir()}
        revised = self.calibrate(object_id=marked["object_id"], x=1., y=.5)
        self.assertEqual(revised["xy_calibration"]["revision"], 2)
        self.assertEqual(revised["xy_calibration"]["previous_calibration_id"], first["xy_calibration"]["calibration_id"])
        for action, fields in (("annotate", {"updates": [{"annotation_id": "candidate", "text": "revised"}]}),
                               ("export", {"output_dir": str(self.root / "stale-export")})):
            refused = self.call(action, object_id=revised["object_id"], **fields)
            self.assertFalse(refused["ok"], refused)
            self.assertEqual(refused["error"]["code"], "STALE_CALIBRATION_DISPLAY")
        updated = self.ok("view", object_id=revised["object_id"])
        self.assertEqual(updated["scale_bar"]["length"], 10.)
        self.assertEqual(updated["annotations"][0]["anchor"], marked["annotations"][0]["anchor"])
        self.assertEqual(updated["calibration_review"]["candidate_interpretations"], "review_required_after_calibration_change")
        self.ok("annotate", object_id=updated["object_id"], updates=[{"annotation_id": "candidate", "text": "revised after scale review"}])
        withdrawn = self.ok("calibrate", object_id=updated["object_id"], scope="image", xy_scale=None,
                            source_text="Synthetic user retracts the estimate")
        self.assertEqual(withdrawn["xy_calibration"]["revision"], 3)
        self.assertEqual(withdrawn["xy_calibration"]["status"], "withdrawn")
        pixel_view = self.ok("view", object_id=withdrawn["object_id"])
        self.assertIsNone(pixel_view["scale_bar"])
        measured = self.ok("measure", object_id=pixel_view["object_id"], points=[[2, 3], [5, 7]])
        self.assertEqual(measured["distance_pixels"], 5.)
        self.assertIsNone(measured["physical_distance"])
        self.assertEqual({file.name: file.read_bytes() for file in old_directory.iterdir()}, old_files)
        self.assert_source_unchanged()


if __name__ == "__main__":
    unittest.main()
