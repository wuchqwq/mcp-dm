"""Display-only spectrum filtering/upscaling, independent of native DM.

SciPy is required rather than skipped. The reference checks the declared tool
contract; it neither replaces the scientific FFT nor supplies a runtime fallback.
"""
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter
import tifffile

from tools import image_workspace as engine


class ImageSpectrumPresentationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="spectrum-presentation-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / "workspace"
        self.counter = 0
        self.values = (np.arange(9 * 15).reshape(9, 15) * 23).astype(np.uint16)
        self.frame, self.source = self.new_frame("asymmetric", self.values)
        self.source_before = self.source.read_bytes()
        self.fft = self.ok("fft", object_id=self.frame["object_id"], max_size=32)
        self.complex_before = Path(self.fft["array_path"]).read_bytes()

    def execute(self, action, **arguments):
        self.counter += 1
        return engine.execute({"workspace": str(self.workspace), "action": action,
                               "request_id": "spectrum-presentation-{}".format(self.counter), **arguments})

    def ok(self, action, **arguments):
        result = self.execute(action, **arguments)
        self.assertTrue(result["ok"], result)
        return result["result"]

    def new_frame(self, name, values):
        source = self.root / (name + ".tiff")
        tifffile.imwrite(source, values, photometric="minisblack", metadata=None)
        opened = self.ok("open", source_path=str(source))
        return self.ok("frame", object_id=opened["object_id"], frame_index=0), source

    def png(self, result):
        with Image.open(result["image_path"]) as image:
            return image.copy()

    def assert_coordinates(self, actual, expected):
        self.assertEqual(len(actual), len(expected))
        for left, right in zip(actual, expected):
            self.assertAlmostEqual(left, right, places=10)

    def assert_inputs_unchanged(self):
        self.assertEqual(self.source.read_bytes(), self.source_before)
        self.assertEqual(Path(self.fft["array_path"]).read_bytes(), self.complex_before)
        np.testing.assert_array_equal(np.load(self.frame["array_path"]), self.values)

    def test_constant_amplitude_spectrum_filters_to_zero_without_scientific_change(self):
        impulse = np.zeros((9, 15), dtype=np.uint16)
        impulse[0, 0] = 1
        frame, _ = self.new_frame("spatial-impulse", impulse)
        fft = self.ok("fft", object_id=frame["object_id"], max_size=32)
        raw = Path(fft["array_path"]).read_bytes()
        with patch.object(np.fft, "fft2", side_effect=AssertionError("Display filtering must not recompute FFT")):
            filtered = self.ok("view", object_id=fft["object_id"], representation="amplitude",
                               spectrum_filter={"smooth_sigma_bins": .5, "background_sigma_bins": 3})
        self.assertEqual(filtered["display"]["display_range"], [0., 0.])
        self.assertTrue(np.all(np.asarray(self.png(filtered)) == 0))
        self.assertEqual(Path(filtered["array_path"]).read_bytes(), raw)
        self.assertFalse(filtered["fft_recomputed"])

    def test_gaussian_display_filter_order_and_parameters_match_independent_scipy(self):
        parameters = {"smooth_sigma_bins": .75, "background_sigma_bins": 2.5}
        original = np.load(self.fft["array_path"])
        shown = np.log1p(np.abs(original)).astype(np.float64)
        smooth = gaussian_filter(shown, sigma=.75, mode="reflect", truncate=4)
        reference = np.maximum(0., smooth - gaussian_filter(smooth, sigma=2.5, mode="reflect", truncate=4))
        filtered = self.ok("view", object_id=self.fft["object_id"], spectrum_filter=parameters)
        limits = filtered["display"]["display_range"]
        np.testing.assert_allclose(limits, [reference.min(), reference.max()], rtol=0, atol=1e-13)
        gray = np.floor(np.clip((reference-reference.min())/(reference.max()-reference.min()), 0, 1)*255+.5).astype(np.uint8)
        np.testing.assert_array_equal(np.asarray(self.png(filtered)), gray)
        self.assertEqual(filtered["display"]["spectrum_filter"], parameters)
        self.assertEqual(Path(filtered["array_path"]).read_bytes(), self.complex_before)
        self.assertEqual(filtered["spectrum_object_id"], self.fft["object_id"])
        self.assert_inputs_unchanged()

    def test_small_sigma_central_impulse_has_independently_calculated_peak(self):
        # A spatial constant7 gives a single amplitude945 Fourier impulse at
        # bin(7,4). Its centre is far enough from the smoothing support edge to
        # compute the two Gaussian passes from their finite normalized kernels.
        frame, _ = self.new_frame("spatial-constant", np.full((9, 15), 7, np.uint16))
        fft = self.ok("fft", object_id=frame["object_id"], max_size=32)
        def kernel(sigma):
            radius = int(4*sigma+.5)
            weights = {i: math.exp(-.5*(i/sigma)**2) for i in range(-radius, radius+1)}
            total = sum(weights.values())
            return {i: weight/total for i, weight in weights.items()}
        small, background = kernel(.5), kernel(1)
        central_smooth = 945 * small[0]**2
        convolution_centre = sum(weight*background[index] for index, weight in small.items())
        expected_peak = central_smooth - 945*convolution_centre**2
        filtered = self.ok("view", object_id=fft["object_id"], representation="amplitude",
                           spectrum_filter={"smooth_sigma_bins": .5, "background_sigma_bins": 1})
        self.assertAlmostEqual(filtered["display"]["display_range"][0], 0., places=12)
        self.assertAlmostEqual(filtered["display"]["display_range"][1], expected_peak, places=10)
        self.assertEqual(np.unravel_index(np.asarray(self.png(filtered)).argmax(), (9, 15)), (4, 7))

    def test_filter_inherits_and_explicit_null_restores_raw_representation(self):
        parameters = {"smooth_sigma_bins": .5, "background_sigma_bins": 3}
        first = self.ok("view", object_id=self.fft["object_id"], spectrum_filter=parameters,
                        display_range=[0, 10], gamma=2, max_size=128, upscale=True)
        inherited = self.ok("view", object_id=first["object_id"], gamma=3)
        self.assertEqual(inherited["display"]["spectrum_filter"], parameters)
        self.assertEqual(inherited["display"]["display_range"], [0, 10])
        self.assertTrue(inherited["display"]["upscale"])
        self.assertEqual(inherited["display"]["max_size"], 128)
        with patch.object(np.fft, "fft2", side_effect=AssertionError("Filter changes must not recompute FFT")):
            restored = self.ok("view", object_id=inherited["object_id"], spectrum_filter=None)
        raw_display = np.log1p(np.abs(np.load(self.fft["array_path"])))
        self.assertIsNone(restored["display"]["spectrum_filter"])
        self.assertEqual(restored["display"]["gamma"], 3)
        np.testing.assert_allclose(restored["display"]["display_range"], [raw_display.min(), raw_display.max()], rtol=0, atol=1e-13)
        self.assertTrue(restored["display"]["upscale"])
        self.assertEqual(Path(restored["array_path"]).read_bytes(), self.complex_before)
        explicit = self.ok("view", object_id=restored["object_id"], spectrum_filter=parameters,
                           display_range=[2, 9])
        self.assertEqual(explicit["display"]["display_range"], [2, 9])

    def test_upscaled_spectrum_keeps_frequency_centre_and_edge_anchors(self):
        marked = self.ok("annotate", object_id=self.fft["object_id"], annotations=[{
            "kind": "point", "coordinates": [0, 0], "coordinate_space": "frequency_cycles_per_pixel",
            "source_object_id": self.fft["object_id"], "annotation_id": "dc", "status": "hypothesized"}, {
            "kind": "rectangle", "coordinates": [-.1, -.1, .1, .1],
            "coordinate_space": "frequency_cycles_per_pixel", "source_object_id": self.fft["object_id"],
            "annotation_id": "region", "status": "hypothesized"}])
        revised = self.ok("view", object_id=marked["object_id"], max_size=128, upscale=True,
                          spectrum_filter={"smooth_sigma_bins": .5, "background_sigma_bins": 3})
        self.assertEqual(self.png(revised).size, (128, 77))
        self.assert_coordinates(revised["annotations"][0]["coordinates"], [63.5, 38.])
        self.assert_coordinates(revised["annotations"][1]["coordinates"], [51.2, 30.8, 76.8, 46.2])
        for old, new in zip(marked["annotations"], revised["annotations"]):
            self.assertEqual(old["anchor"], new["anchor"])
            self.assertEqual(new["visibility"], "visible")
        self.assertEqual(Path(revised["array_path"]).read_bytes(), self.complex_before)
        shrunk = self.ok("view", object_id=revised["object_id"], upscale=False)
        self.assertEqual(self.png(shrunk).size, (15, 9))
        self.assert_coordinates(shrunk["annotations"][0]["coordinates"], [7, 4])
        self.assert_inputs_unchanged()

    def test_upscaled_spatial_roi_preserves_pixel_centre_and_edge_distinction(self):
        view = self.ok("view", object_id=self.frame["object_id"], rect=[2, 1, 12, 8], max_size=32)
        marked = self.ok("annotate", object_id=view["object_id"], annotations=[{
            "kind": "point", "coordinates": [4, 3], "coordinate_space": "source_pixels",
            "source_object_id": self.frame["object_id"], "status": "hypothesized"}, {
            "kind": "rectangle", "coordinates": [3, 2, 9, 6], "coordinate_space": "source_pixels",
            "source_object_id": self.frame["object_id"], "status": "hypothesized"}])
        revised = self.ok("view", object_id=marked["object_id"], max_size=100, upscale=True)
        self.assertEqual(self.png(revised).size, (100, 70))
        self.assert_coordinates(revised["annotations"][0]["coordinates"], [24.5, 24.5])
        self.assert_coordinates(revised["annotations"][1]["coordinates"], [10, 10, 70, 50])
        np.testing.assert_array_equal(np.load(revised["array_path"]), self.values[1:8, 2:12])

    def test_invalid_filter_values_and_wrong_domain_refuse(self):
        invalid = [True, [], {}, {"smooth_sigma_bins": .5}, {"background_sigma_bins": 2},
                   {"smooth_sigma_bins": -.1, "background_sigma_bins": 2},
                   {"smooth_sigma_bins": 4.1, "background_sigma_bins": 8},
                   {"smooth_sigma_bins": 0, "background_sigma_bins": .9},
                   {"smooth_sigma_bins": 0, "background_sigma_bins": 64.1},
                   {"smooth_sigma_bins": 4, "background_sigma_bins": 4},
                   {"smooth_sigma_bins": True, "background_sigma_bins": 2},
                   {"smooth_sigma_bins": 0, "background_sigma_bins": float("inf")},
                   {"smooth_sigma_bins": 0, "background_sigma_bins": 2, "algorithm": "other"}]
        for parameters in invalid:
            with self.subTest(parameters=parameters):
                self.assertFalse(self.execute("view", object_id=self.fft["object_id"], spectrum_filter=parameters)["ok"])
        for parameters in (None, {"smooth_sigma_bins": 0, "background_sigma_bins": 2}):
            with self.subTest(spatial=parameters):
                self.assertFalse(self.execute("view", object_id=self.frame["object_id"], spectrum_filter=parameters)["ok"])
        for value in (1, 0, "true", None):
            with self.subTest(upscale=value):
                self.assertFalse(self.execute("view", object_id=self.fft["object_id"], upscale=value)["ok"])

    def test_small_arrow_style_survives_rerender_and_export_records_presentation(self):
        filtered = self.ok("view", object_id=self.fft["object_id"], max_size=128, upscale=True,
                           spectrum_filter={"smooth_sigma_bins": .5, "background_sigma_bins": 3})
        coordinates = [0, 0, 2/15, -1/9]
        marked = self.ok("annotate", object_id=filtered["object_id"], annotations=[{
            "kind": "arrow", "coordinates": coordinates, "coordinate_space": "frequency_cycles_per_pixel",
            "source_object_id": self.fft["object_id"], "annotation_id": "small-arrow",
            "line_width": 1, "arrowhead_size": 2, "status": "hypothesized",
            "note": "Candidate only; no twin or defect determination"}])
        revised = self.ok("view", object_id=marked["object_id"], gamma=1.5, max_size=256)
        mark = revised["annotations"][0]
        self.assertEqual(mark["line_width"], 1)
        self.assertEqual(mark["arrowhead_size"], 2)
        self.assertEqual(mark["status"], "hypothesized")
        self.assertEqual(mark["anchor"], marked["annotations"][0]["anchor"])
        output = self.root / "new-display-export"
        self.ok("export", object_id=revised["object_id"], output_dir=str(output))
        manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["display_mapping"]["spectrum_filter"], filtered["display"]["spectrum_filter"])
        self.assertTrue(manifest["display_mapping"]["upscale"])
        self.assertEqual(manifest["display_object"]["annotations"][0]["arrowhead_size"], 2)
        self.assertEqual(manifest["display_object"]["annotations"][0]["line_width"], 1)
        self.assertEqual((output / "data.npy").read_bytes(), self.complex_before)
        self.assertEqual((output / "preview.png").read_bytes(), Path(revised["image_path"]).read_bytes())
        self.assertFalse(manifest["dm_save_as_called"])
        self.assertTrue(manifest["scientific_NPY_is_not_display_PNG"])
        self.assert_inputs_unchanged()

    def test_annotation_style_defaults_and_budgets_are_explicit(self):
        view = self.ok("view", object_id=self.frame["object_id"], upscale=True, max_size=128)
        original = {"kind": "arrow", "coordinates": [20, 20, 60, 40], "status": "hypothesized"}
        marked = self.ok("annotate", object_id=view["object_id"], annotations=[original])
        mark = marked["annotations"][0]
        self.assertEqual(mark["line_width"], 3)
        self.assertEqual(mark["arrowhead_size"], 6)
        self.assertEqual(mark["color"], "cyan")
        self.assertEqual(mark["arrow_length"], 24)
        self.assertEqual(mark["coordinates"], original["coordinates"])
        self.assertEqual(mark["arrow_render_coordinates"][2:], original["coordinates"][2:])
        self.assertAlmostEqual(math.dist(mark["arrow_render_coordinates"][:2], mark["coordinates"][2:]), 24)
        for field, values in (("line_width", (0, 5, 1.5, True)), ("arrowhead_size", (0, 13, 1.5, True)),
                              ("arrow_length", (0, 3, 129, 24.5, True, "24"))):
            for value in values:
                with self.subTest(field=field, value=value):
                    self.assertFalse(self.execute("annotate", object_id=view["object_id"],
                                                 annotations=[dict(original, **{field: value})])["ok"])

    def test_short_cyan_arrows_preserve_tip_and_anchor_on_resize_and_export(self):
        view = self.ok("view", object_id=self.fft["object_id"], display_preset="fft_detail")
        original = {"kind": "arrow", "coordinates": [-.3, -.2, .2, .1],
                    "coordinate_space": "frequency_cycles_per_pixel", "source_object_id": self.fft["object_id"],
                    "annotation_id": "candidate", "status": "hypothesized", "text": "A"}
        marked = self.ok("annotate", object_id=view["object_id"], annotations=[original])
        revised = self.ok("view", object_id=marked["object_id"], max_size=768)
        for current in (marked, revised):
            mark = current["annotations"][0]
            self.assertEqual(mark["anchor"]["coordinates"], original["coordinates"])
            self.assertEqual(mark["source_mappings"][0]["frequency_cycles_per_pixel"], original["coordinates"])
            self.assertEqual(mark["arrow_render_coordinates"][2:], mark["coordinates"][2:])
            self.assertAlmostEqual(math.dist(mark["arrow_render_coordinates"][:2], mark["coordinates"][2:]), 24)
            self.assertEqual((mark["color"], mark["line_width"], mark["arrowhead_size"]), ("cyan", 3, 6))
            expected = self.png(view if current is marked else self.ok("view", object_id=view["object_id"], max_size=768)).convert("RGB")
            # Independent render oracle: short horizontal/diagonal guide and
            # label position use the actual tail, not the far original endpoint.
            from PIL import ImageDraw
            draw = ImageDraw.Draw(expected)
            x0, y0, x1, y1 = mark["arrow_render_coordinates"]
            draw.line([x0, y0, x1, y1], fill="#45e8ff", width=3)
            angle = math.atan2(y1-y0, x1-x0)
            draw.polygon([(x1, y1)]+[(x1-6*math.cos(angle+a), y1-6*math.sin(angle+a)) for a in (-.5, .5)], fill="#45e8ff")
            draw.text([x0, y0], "A", fill="#45e8ff")
            np.testing.assert_array_equal(np.asarray(self.png(current)), np.asarray(expected))
        confirmed = self.ok("annotate", object_id=view["object_id"], annotations=[dict(original, status="user_confirmed")])
        self.assertEqual(confirmed["annotations"][0]["color"], "cyan")
        np.testing.assert_array_equal(np.asarray(self.png(marked)), np.asarray(self.png(confirmed)))
        output = self.root / "cyan-export"
        self.ok("export", object_id=revised["object_id"], output_dir=str(output))
        manifest = json.loads((output/"manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["display_object"]["annotations"], revised["annotations"])
        self.assertEqual((output/"data.npy").read_bytes(), self.complex_before)
        self.assert_inputs_unchanged()

    def test_orange_candidate_explicit_styles_and_short_segments_are_not_reclassified(self):
        view = self.ok("view", object_id=self.frame["object_id"], upscale=True, max_size=128)
        original = {"kind": "arrow", "coordinates": [20, 20, 23, 24], "status": "hypothesized",
                    "color": "orange", "note": "second-phase candidate, not confirmed"}
        marked = self.ok("annotate", object_id=view["object_id"], annotations=[original])
        mark = marked["annotations"][0]
        self.assertEqual(mark["arrow_render_coordinates"], original["coordinates"])
        self.assertEqual((mark["color"], mark["status"], mark["note"]), ("orange", "hypothesized", original["note"]))
        full = self.ok("annotate", object_id=view["object_id"], annotations=[dict(original, coordinates=[20,20,90,60],
                       arrow_length=None, line_width=1, arrowhead_size=2)])
        self.assertEqual(full["annotations"][0]["arrow_render_coordinates"], [20,20,90,60])
        resized = self.ok("view", object_id=full["object_id"], max_size=256)
        restored = resized["annotations"][0]
        self.assertIsNone(restored["arrow_length"])
        self.assertEqual(restored["arrow_render_coordinates"], restored["coordinates"])
        self.assertEqual((restored["line_width"], restored["arrowhead_size"], restored["color"]), (1,2,"orange"))
        self.assertFalse(self.execute("annotate", object_id=view["object_id"],
                                    annotations=[dict(original, kind="line", arrow_length=24)])["ok"])

    def test_historical_arrow_rerender_keeps_full_shaft_and_collapsed_display_rejects(self):
        panels = [{"source_object_id": "a"*32, "domain": "spatial_pixels",
                   "source_rect_xyxy": [0,0,64,64], "image_rect_xyxy": [0,0,128,128]}]
        old = {"kind":"arrow", "anchor":{"coordinate_space":"source_pixels", "source_object_id":"a"*32,
                                         "coordinates":[0,0,60,60]},
               "line_width":1, "arrowhead_size":4, "color":"amber", "status":"hypothesized"}
        mark = engine.annotation(old, [128,128], panels, reproject=True)
        self.assertIsNone(mark["arrow_length"])
        self.assertEqual(mark["arrow_render_coordinates"], mark["coordinates"])
        self.assertEqual((mark["color"], mark["line_width"], mark["arrowhead_size"]), ("amber",1,4))
        with self.assertRaises(engine.WorkspaceError):
            engine.annotation({"kind":"arrow", "coordinates":[0,0,1e-20,0], "coordinate_space":"source_pixels",
                               "source_object_id":"a"*32}, [128,128], panels)

    def test_frequency_axes_margins_keep_dc_arrow_and_region_mathematically_anchored(self):
        axes = self.ok("view", object_id=self.fft["object_id"], max_size=256, upscale=True,
                       spectrum_axes=True, spectrum_filter={"smooth_sigma_bins": .5, "background_sigma_bins": 3})
        # At budget256 the plot fits in172x156. A15x9 spectrum becomes172x103;
        # margins are left64/top44/right20/bottom56, not scientific pixels.
        self.assertEqual(self.png(axes).size, (256, 203))
        self.assertEqual(axes["panels"][0]["image_rect_xyxy"], [64, 44, 236, 147])
        self.assertEqual(axes["panels"][0]["source_object_id"], self.fft["object_id"])
        frequency = [0, 0, 2/15, -1/9]
        marked = self.ok("annotate", object_id=axes["object_id"], annotations=[{
            "kind": "point", "coordinates": [0, 0], "coordinate_space": "frequency_cycles_per_pixel",
            "source_object_id": self.fft["object_id"], "status": "hypothesized", "annotation_id": "dc"}, {
            "kind": "arrow", "coordinates": frequency, "coordinate_space": "frequency_cycles_per_pixel",
            "source_object_id": self.fft["object_id"], "status": "hypothesized", "annotation_id": "arrow",
            "line_width": 1, "arrowhead_size": 2}, {
            "kind": "rectangle", "coordinates": [-.1, -.1, .1, .1],
            "coordinate_space": "frequency_cycles_per_pixel", "source_object_id": self.fft["object_id"],
            "status": "hypothesized", "annotation_id": "region"}])
        self.assert_coordinates(marked["annotations"][0]["coordinates"], [149.5, 95.])
        self.assert_coordinates(marked["annotations"][1]["coordinates"],
                                [149.5, 95., 64+9.5*172/15-.5, 44+3.5*103/9-.5])
        self.assert_coordinates(marked["annotations"][2]["coordinates"], [132.8, 85.2, 167.2, 105.8])
        self.assertEqual(marked["annotations"][1]["anchor"]["coordinates"], frequency)
        self.assertEqual(Path(axes["array_path"]).read_bytes(), self.complex_before)
        self.assertIsNone(axes["physical_frequency_unit"])

    def test_frequency_axes_inherit_disable_and_export_keep_plot_mapping_and_values(self):
        initial = self.ok("view", object_id=self.fft["object_id"], max_size=256,
                          spectrum_axes=True, upscale=True, gamma=2)
        marked = self.ok("annotate", object_id=initial["object_id"], annotations=[{
            "kind": "point", "coordinates": [0, 0], "coordinate_space": "frequency_cycles_per_pixel",
            "source_object_id": self.fft["object_id"], "status": "hypothesized", "annotation_id": "dc"}])
        with patch.object(np.fft, "fft2", side_effect=AssertionError("Axes changes must not recompute FFT")):
            inherited = self.ok("view", object_id=marked["object_id"], max_size=512)
            disabled = self.ok("view", object_id=inherited["object_id"], spectrum_axes=False)
        self.assertTrue(inherited["display"]["spectrum_axes"])
        self.assertEqual(inherited["display"]["gamma"], 2)
        self.assertEqual(self.png(inherited).size, (512, 357))
        self.assertEqual(inherited["panels"][0]["image_rect_xyxy"], [64, 44, 492, 301])
        self.assert_coordinates(inherited["annotations"][0]["coordinates"], [277.5, 172.])
        self.assertFalse(disabled["display"]["spectrum_axes"])
        self.assertEqual(self.png(disabled).size, (512, 307))
        self.assertEqual(disabled["panels"][0]["image_rect_xyxy"], [0, 0, 512, 307])
        self.assert_coordinates(disabled["annotations"][0]["coordinates"], [255.5, 153.])
        self.assertEqual(disabled["annotations"][0]["anchor"], marked["annotations"][0]["anchor"])
        output = self.root / "axes-export"
        self.ok("export", object_id=inherited["object_id"], output_dir=str(output))
        manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        self.assertTrue(manifest["display_mapping"]["spectrum_axes"])
        self.assertEqual(manifest["display_object"]["panels"], inherited["panels"])
        self.assertEqual((output / "data.npy").read_bytes(), self.complex_before)
        self.assertEqual((output / "preview.png").read_bytes(), Path(inherited["image_path"]).read_bytes())
        self.assert_inputs_unchanged()

    def test_frequency_axes_reject_nonboolean_wrong_domain_and_small_budget(self):
        for value in (1, 0, None, "true"):
            with self.subTest(value=value):
                self.assertFalse(self.execute("view", object_id=self.fft["object_id"],
                                             spectrum_axes=value, max_size=256)["ok"])
        for maximum in (32, 128, 192, 255):
            with self.subTest(maximum=maximum):
                self.assertFalse(self.execute("view", object_id=self.fft["object_id"],
                                             spectrum_axes=True, max_size=maximum)["ok"])
        for value in (True, False):
            with self.subTest(spatial=value):
                self.assertFalse(self.execute("view", object_id=self.frame["object_id"],
                                             spectrum_axes=value, max_size=256)["ok"])
        # A scalar comparison must not acquire Fourier labels, even if its two
        # selected frames have equal shapes and the caller supplied a budget.
        other, _ = self.new_frame("other", self.values+1)
        compare = self.ok("compare", object_ids=[self.frame["object_id"], other["object_id"]], max_size=256)
        self.assertFalse(self.execute("view", object_id=compare["object_id"], spectrum_axes=True)["ok"])
        valid = self.ok("view", object_id=self.fft["object_id"], spectrum_axes=True, max_size=256)
        self.assertFalse(self.execute("view", object_id=valid["object_id"], max_size=192)["ok"])

    def test_fft_detail_preset_starts_from_complex_with_light_percentile_display(self):
        heavy = self.ok("view", object_id=self.fft["object_id"], representation="power", gamma=4,
                        spectrum_filter={"smooth_sigma_bins": 3, "background_sigma_bins": 8},
                        spectrum_axes=True, max_size=256, upscale=False, display_range=[0, 10])
        previous_png = Path(heavy["image_path"]).read_bytes()
        raw = np.load(self.fft["array_path"])
        expected = np.percentile(np.log1p(np.abs(raw)), [5, 99.8])
        with patch.object(np.fft, "fft2", side_effect=AssertionError("Preset must reuse original complex spectrum")):
            detail = self.ok("view", object_id=heavy["object_id"], display_preset="fft_detail")
        settings = detail["display"]
        self.assertEqual(settings["display_preset"], "fft_detail")
        self.assertEqual(settings["representation"], "log_amplitude")
        self.assertIsNone(settings["spectrum_filter"])
        self.assertFalse(settings["spectrum_axes"])
        self.assertEqual(settings["gamma"], .8)
        self.assertEqual(settings["display_preset_revision"], 2)
        self.assertTrue(settings["upscale"])
        self.assertEqual(settings["max_size"], 512)
        self.assertEqual(settings["range_source"], "percentile")
        self.assertEqual(settings["range_percentiles"], [5, 99.8])
        self.assertNotIn("attempted_range_percentiles", settings)
        self.assertNotIn("range_fallback_reason", settings)
        np.testing.assert_allclose(settings["display_range"], expected, rtol=0, atol=1e-13)
        self.assertEqual(detail["spectrum_object_id"], self.fft["object_id"])
        self.assertEqual(Path(detail["array_path"]).read_bytes(), self.complex_before)
        self.assertEqual(Path(heavy["image_path"]).read_bytes(), previous_png)
        self.assertEqual(self.ok("get", object_id=heavy["object_id"])["display"]["spectrum_filter"],
                         {"smooth_sigma_bins": 3, "background_sigma_bins": 8})
        self.assert_inputs_unchanged()

    def test_fft_detail_inherits_range_without_reapplying_defaults_or_percentiles(self):
        first = self.ok("view", object_id=self.fft["object_id"], display_preset="fft_detail")
        with patch.object(np, "percentile", side_effect=AssertionError("Omitted preset must not run again")), \
             patch.object(np.fft, "fft2", side_effect=AssertionError("No FFT during display revision")):
            revised = self.ok("view", object_id=first["object_id"], gamma=1.7, max_size=768)
        self.assertEqual(revised["display"]["display_preset"], "fft_detail")
        self.assertEqual(revised["display"]["display_range"], first["display"]["display_range"])
        self.assertEqual(revised["display"]["gamma"], 1.7)
        self.assertEqual(revised["display"]["max_size"], 768)
        self.assertIsNone(revised["display"]["spectrum_filter"])
        self.assertEqual(Path(revised["array_path"]).read_bytes(), self.complex_before)

    def test_explicit_range_and_null_override_preset_percentiles_with_honest_metadata(self):
        direct = self.ok("view", object_id=self.fft["object_id"], display_preset="fft_detail", display_range=[1, 9])
        self.assertEqual(direct["display"]["display_range"], [1, 9])
        self.assertEqual(direct["display"]["range_source"], "explicit")
        self.assertNotIn("range_percentiles", direct["display"])
        first = self.ok("view", object_id=self.fft["object_id"], display_preset="fft_detail")
        reset = self.ok("view", object_id=first["object_id"], display_range=None)
        log_values = np.log1p(np.abs(np.load(self.fft["array_path"])))
        self.assertEqual(reset["display"]["range_source"], "shared_raw_minmax")
        np.testing.assert_allclose(reset["display"]["display_range"], [log_values.min(), log_values.max()], rtol=0, atol=1e-13)
        self.assertNotIn("range_percentiles", reset["display"])
        simultaneous = self.ok("view", object_id=self.fft["object_id"], display_preset="fft_detail", display_range=None)
        self.assertEqual(simultaneous["display"]["range_source"], "shared_raw_minmax")
        self.assertEqual(simultaneous["display"]["display_range"], reset["display"]["display_range"])
        self.assertNotIn("range_percentiles", simultaneous["display"])

    def test_explicit_fields_override_fft_detail_recipe(self):
        parameters = {"smooth_sigma_bins": .5, "background_sigma_bins": 2}
        detail = self.ok("view", object_id=self.fft["object_id"], display_preset="fft_detail",
                         representation="amplitude", spectrum_filter=parameters, spectrum_axes=True,
                         gamma=1.3, max_size=256, upscale=False, display_range=[0, 100])
        settings = detail["display"]
        self.assertEqual(settings["representation"], "amplitude")
        self.assertEqual(settings["spectrum_filter"], parameters)
        self.assertTrue(settings["spectrum_axes"])
        self.assertEqual(settings["gamma"], 1.3)
        self.assertEqual(settings["max_size"], 256)
        self.assertFalse(settings["upscale"])
        self.assertEqual(settings["display_range"], [0, 100])
        self.assertEqual(settings["range_source"], "explicit")
        self.assertEqual(Path(detail["array_path"]).read_bytes(), self.complex_before)

    def test_fft_detail_rejects_unknown_preset_and_non_spectrum_inputs(self):
        for value in ("auto", "fft_smooth", "", 1, None):
            with self.subTest(preset=value):
                self.assertFalse(self.execute("view", object_id=self.fft["object_id"], display_preset=value)["ok"])
        self.assertFalse(self.execute("view", object_id=self.frame["object_id"], display_preset="fft_detail")["ok"])
        other, _ = self.new_frame("preset-other", self.values+1)
        compare = self.ok("compare", object_ids=[self.frame["object_id"], other["object_id"]])
        self.assertFalse(self.execute("view", object_id=compare["object_id"], display_preset="fft_detail")["ok"])

    def test_equal_percentiles_report_raw_minmax_fallback_for_constant_and_dc_only_spectra(self):
        impulse = np.zeros((32, 32), np.uint16)
        impulse[0, 0] = 1
        cases = [("constant-spectrum", impulse), ("dc-only-spectrum", np.full((32, 32), 7, np.uint16))]
        for name, pixels in cases:
            with self.subTest(case=name):
                frame, source = self.new_frame(name, pixels)
                source_before = source.read_bytes()
                fft = self.ok("fft", object_id=frame["object_id"])
                complex_before = Path(fft["array_path"]).read_bytes()
                log_values = np.log1p(np.abs(np.load(fft["array_path"])))
                attempted = np.percentile(log_values, [5, 99.8])
                self.assertEqual(attempted[0], attempted[1])
                raw_range = [float(log_values.min()), float(log_values.max())]
                with patch.object(np.fft, "fft2", side_effect=AssertionError("Fallback must not recompute FFT")):
                    detail = self.ok("view", object_id=fft["object_id"], display_preset="fft_detail")
                    inherited = self.ok("view", object_id=detail["object_id"], gamma=1.5, max_size=256)
                settings = detail["display"]
                self.assertEqual(settings["range_source"], "percentile_fallback_raw_minmax")
                self.assertEqual(settings["display_range"], raw_range)
                self.assertEqual(settings["attempted_range_percentiles"], [5, 99.8])
                self.assertEqual(settings["range_fallback_reason"], "percentile limits are equal")
                self.assertNotIn("range_percentiles", settings)
                self.assertEqual(inherited["display"]["range_source"], "inherited_display")
                self.assertEqual(inherited["display"]["display_range"], raw_range)
                self.assertNotIn("range_percentiles", inherited["display"])
                # Any retained fallback details remain true provenance of the
                # inherited numerical range, never an active percentile claim.
                if "attempted_range_percentiles" in inherited["display"]:
                    self.assertEqual(inherited["display"]["attempted_range_percentiles"], [5, 99.8])
                    self.assertEqual(inherited["display"]["range_fallback_reason"], "percentile limits are equal")
                explicit = self.ok("view", object_id=detail["object_id"], display_range=[0, 1])
                self.assertEqual(explicit["display"]["range_source"], "explicit")
                self.assertEqual(explicit["display"]["display_range"], [0, 1])
                self.assertNotIn("range_percentiles", explicit["display"])
                self.assertNotIn("attempted_range_percentiles", explicit["display"])
                self.assertNotIn("range_fallback_reason", explicit["display"])
                for result in (detail, inherited, explicit):
                    self.assertEqual(Path(result["array_path"]).read_bytes(), complex_before)
                self.assertEqual(Path(fft["array_path"]).read_bytes(), complex_before)
                self.assertEqual(source.read_bytes(), source_before)
                if name == "constant-spectrum":
                    self.assertTrue(settings["constant_range"])
                    self.assertTrue(np.all(np.asarray(self.png(detail)) == 0))
                else:
                    self.assertEqual(raw_range[0], 0)
                    self.assertAlmostEqual(raw_range[1], math.log1p(7*32*32), places=13)
                    self.assertFalse(settings["constant_range"])

    def test_annotation_color_is_independent_of_status_and_survives_preset_revision(self):
        detail = self.ok("view", object_id=self.fft["object_id"], display_preset="fft_detail")
        original = {"kind": "point", "coordinates": [0, 0], "coordinate_space": "frequency_cycles_per_pixel",
                    "source_object_id": self.fft["object_id"], "annotation_id": "white-candidate",
                    "color": "white", "status": "hypothesized"}
        candidate = self.ok("annotate", object_id=detail["object_id"], annotations=[original])
        confirmed = self.ok("annotate", object_id=detail["object_id"],
                            annotations=[dict(original, status="user_confirmed")])
        self.assertEqual(candidate["annotations"][0]["color"], "white")
        self.assertEqual(confirmed["annotations"][0]["color"], "white")
        np.testing.assert_array_equal(np.asarray(self.png(candidate)), np.asarray(self.png(confirmed)))
        before = np.asarray(self.png(detail).convert("RGB"))
        after = np.asarray(self.png(candidate).convert("RGB"))
        changed = np.any(before != after, axis=2)
        self.assertTrue(changed.any())
        self.assertTrue(np.all(after[changed] == 255))
        revised = self.ok("view", object_id=candidate["object_id"], gamma=1.4, max_size=768)
        self.assertEqual(revised["annotations"][0]["color"], "white")
        self.assertEqual(revised["annotations"][0]["status"], "hypothesized")
        self.assertEqual(revised["annotations"][0]["anchor"], candidate["annotations"][0]["anchor"])
        output = self.root / "detail-white-export"
        self.ok("export", object_id=revised["object_id"], output_dir=str(output))
        manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["display_mapping"]["display_preset"], "fft_detail")
        self.assertEqual(manifest["display_object"]["annotations"][0]["color"], "white")
        self.assertEqual((output / "data.npy").read_bytes(), self.complex_before)

    def test_color_choices_reject_unknown_and_keep_default_status_palette_compatible(self):
        view = self.ok("view", object_id=self.frame["object_id"], upscale=True, max_size=128)
        original = {"kind": "line", "coordinates": [10, 10, 50, 30], "status": "hypothesized"}
        default = self.ok("annotate", object_id=view["object_id"], annotations=[original])
        amber = self.ok("annotate", object_id=view["object_id"], annotations=[dict(original, color="amber")])
        np.testing.assert_array_equal(np.asarray(self.png(default)), np.asarray(self.png(amber)))
        for color in ("white", "cyan", "orange", "amber", "green"):
            with self.subTest(color=color):
                marked = self.ok("annotate", object_id=view["object_id"], annotations=[dict(original, color=color)])
                self.assertEqual(marked["annotations"][0]["color"], color)
        for color in ("red", "White", "", True):
            with self.subTest(invalid_color=color):
                self.assertFalse(self.execute("annotate", object_id=view["object_id"],
                                             annotations=[dict(original, color=color)])["ok"])


    def test_small_unscaled_spectrum_keeps_a_readable_legend_canvas(self):
        # Coordinate labels need their own space even if scientific bins are
        # intentionally displayed without enlargement.
        shown = np.ones((9, 15), dtype=np.float64)
        settings = engine.display_options({"max_size": 256, "upscale": False}, [shown])
        settings.update(representation="amplitude", spectrum_axes=True, spectrum_filter=None)
        figure, panel = engine.spectrum_canvas(shown, settings, "a" * 32)
        self.assertEqual(figure.size, (256, 192))
        self.assertEqual(panel["image_rect_xyxy"], [64, 44, 79, 53])


if __name__ == "__main__":
    unittest.main()
