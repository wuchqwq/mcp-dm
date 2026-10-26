"""Independent checks for display-only zoom of a saved complex FFT.

All inputs are synthetic. Expected positions use hand-enumerated absolute
fftshift bins, never the production coordinate-transform or rendering helpers.
"""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image
import tifffile

from tools import image_workspace as engine


class ImageFrequencyZoomTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="frequency-zoom-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / "workspace"
        self.source = self.root / "offset-source.tiff"
        y, x = np.indices((96, 160))
        self.pixels = ((17*x + 31*y + (x*y) % 53) % 1000).astype(np.uint16)
        tifffile.imwrite(self.source, np.stack([self.pixels, self.pixels+1000]),
                         photometric="minisblack", metadata=None)
        self.source_before = self.source.read_bytes()
        self.counter = 0
        self.opened = self.ok("open", source_path=str(self.source))
        self.frame = self.ok("frame", object_id=self.opened["object_id"], frame_index=0)
        # A large nonzero spatial offset must not offset the frequency bins.
        self.fft = self.ok("fft", object_id=self.frame["object_id"],
                           rect=[31, 23, 126, 78], subtract_mean=True, window="hann")
        self.complex_before = Path(self.fft["array_path"]).read_bytes()
        self.assertEqual(self.fft["shape_yx"], [55, 95])

    def execute(self, action, **arguments):
        self.counter += 1
        return engine.execute({"workspace": str(self.workspace), "action": action,
                               "request_id": "frequency-{}".format(self.counter), **arguments})

    def ok(self, action, **arguments):
        response = self.execute(action, **arguments)
        self.assertTrue(response["ok"], response)
        return response["result"]

    def assert_coords(self, actual, expected):
        self.assertEqual(len(actual), len(expected))
        for found, wanted in zip(actual, expected):
            self.assertAlmostEqual(found, wanted, places=10)

    def assert_unchanged(self):
        self.assertEqual(self.source.read_bytes(), self.source_before)
        self.assertEqual(Path(self.fft["array_path"]).read_bytes(), self.complex_before)
        np.testing.assert_array_equal(np.load(self.frame["array_path"]), self.pixels)

    def png(self, metadata):
        with Image.open(metadata["image_path"]) as image:
            return image.copy()

    def frequency_mark(self, parent, coordinates, kind="point", **extra):
        return self.ok("annotate", object_id=parent["object_id"], annotations=[{
            "kind": kind, "coordinates": coordinates,
            "coordinate_space": "frequency_cycles_per_pixel",
            "source_object_id": self.fft["object_id"], "annotation_id": "candidate",
            "status": "hypothesized", "color": "white", "line_width": 1,
            "arrowhead_size": 2, **extra}])

    def test_zoom_is_only_a_crop_of_full_display_with_unchanged_complex_export(self):
        full = self.ok("view", object_id=self.fft["object_id"], representation="amplitude",
                       gamma=.8, max_size=95, upscale=False, display_range=[0, 200000])
        rect = [53, 17, 73, 29]  # Does not include DC (47,27).
        with patch.object(np.fft, "fft2", side_effect=AssertionError("Zoom must not recompute FFT")):
            zoom = self.ok("view", object_id=full["object_id"], frequency_rect=rect)
        np.testing.assert_array_equal(np.asarray(self.png(zoom)),
                                      np.asarray(self.png(full).crop(tuple(rect))))
        self.assertEqual(self.png(zoom).size, (20, 12))
        self.assertEqual(zoom["display"]["frequency_rect"], rect)
        pane = zoom["panels"][0]
        self.assertEqual(pane["fft_shape_yx"], [55, 95])
        self.assertEqual(pane["fft_rect_xyxy"], rect)
        self.assertEqual(pane["dc_bin_xy"], [47, 27])
        self.assertEqual(pane["source_object_id"], self.fft["object_id"])
        self.assertEqual(zoom["frequency_axes"], self.fft["frequency_axes"])
        self.assertEqual(zoom["shape_yx"], [55, 95])
        self.assertFalse(zoom["fft_recomputed"])
        self.assertFalse(zoom["scientific_data_changed"])
        self.assertIsNone(zoom["physical_frequency_unit"])
        self.assertEqual(Path(zoom["array_path"]).read_bytes(), self.complex_before)
        destination = self.root / "zoom-export"
        self.ok("export", object_id=zoom["object_id"], output_dir=str(destination))
        self.assertEqual((destination / "data.npy").read_bytes(), self.complex_before)
        np.testing.assert_array_equal(np.load(destination / "data.npy"), np.load(self.fft["array_path"]))
        manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["display_mapping"]["frequency_rect"], rect)
        self.assertEqual(manifest["display_object"]["panels"][0]["fft_shape_yx"], [55, 95])
        self.assertEqual((destination / "preview.png").read_bytes(), Path(zoom["image_path"]).read_bytes())
        self.assert_unchanged()

    def test_zoom_resize_pan_and_reset_use_absolute_original_bins(self):
        full = self.ok("view", object_id=self.fft["object_id"], gamma=1.3,
                       max_size=120, upscale=True, display_range=[0, 12])
        first = self.ok("view", object_id=full["object_id"], frequency_rect=[39, 19, 59, 35])
        resized = self.ok("view", object_id=first["object_id"], max_size=240)
        self.assertEqual(resized["display"]["frequency_rect"], [39, 19, 59, 35])
        self.assertEqual(self.png(resized).size, (240, 192))
        pan = self.ok("view", object_id=resized["object_id"], frequency_rect=[63, 5, 83, 21])
        self.assertEqual(pan["panels"][0]["fft_rect_xyxy"], [63, 5, 83, 21])
        self.assertEqual(self.png(pan).size, (240, 192))
        restored = self.ok("view", object_id=pan["object_id"], frequency_rect=None)
        self.assertEqual(restored["display"]["frequency_rect"], [0, 0, 95, 55])
        self.assertEqual(restored["panels"][0]["fft_rect_xyxy"], [0, 0, 95, 55])
        for value in (first, resized, pan, restored):
            self.assertEqual(value["display"]["display_range"], [0, 12])
            self.assertEqual(value["display"]["gamma"], 1.3)
            self.assertEqual(value["spectrum_object_id"], self.fft["object_id"])
            self.assertEqual(value["frequency_axes"], self.fft["frequency_axes"])
            self.assertEqual(Path(value["array_path"]).read_bytes(), self.complex_before)
        self.assert_unchanged()

    def test_point_centres_keep_original_dc_and_signed_frequency_after_zoom(self):
        zoom = self.ok("view", object_id=self.fft["object_id"],
                       frequency_rect=[39, 19, 59, 35], max_size=120, upscale=True)
        self.assertEqual(self.png(zoom).size, (120, 96))
        dc = self.frequency_mark(zoom, [0, 0])
        # DC stays at original bin (47,27), not the zoom centre (48.5,26.5).
        self.assert_coords(dc["annotations"][0]["coordinates"], [50.5, 50.5])
        frequency = [9/95, -5/55]  # Original bins (56,22).
        mark = self.frequency_mark(zoom, frequency)
        self.assert_coords(mark["annotations"][0]["coordinates"], [104.5, 20.5])
        self.assert_coords(mark["annotations"][0]["source_mappings"][0]["fft_bin_coordinates"], [56, 22])
        self.assertEqual(mark["annotations"][0]["anchor"]["coordinates"], frequency)
        self.assertEqual(mark["annotations"][0]["status"], "hypothesized")

    def test_rectangle_edges_have_half_bin_offset_distinct_from_point_centres(self):
        zoom = self.ok("view", object_id=self.fft["object_id"],
                       frequency_rect=[39, 19, 59, 35], max_size=120, upscale=True)
        # Continuous bin edges are (39.5,19.5)..(57.5,33.5).
        frequency = [-7.5/95, -7.5/55, 10.5/95, 6.5/55]
        marked = self.frequency_mark(zoom, frequency, kind="rectangle")
        self.assert_coords(marked["annotations"][0]["coordinates"], [6, 6, 114, 90])
        self.assert_coords(marked["annotations"][0]["source_mappings"][0]["fft_bin_coordinates"],
                           [39.5, 19.5, 57.5, 33.5])
        # A rendered rectangle covering all zoom bin edges maps to +/- half-bin
        # outer edges of the original frequency lattice, not a new FFT grid.
        rendered = self.ok("annotate", object_id=zoom["object_id"], annotations=[{
            "kind": "rectangle", "coordinates": [0, 0, 120, 96], "color": "white"}])
        self.assert_coords(rendered["annotations"][0]["anchor"]["coordinates"],
                           [-8.5/95, -8.5/55, 11.5/95, 7.5/55])

    def test_outside_anchor_is_preserved_hidden_and_restored_without_clipping(self):
        original = [0, 0, 9/95, -5/55]
        marked = self.frequency_mark(self.fft, original, kind="arrow")
        before = marked["annotations"][0]["anchor"]
        with patch.object(np.fft, "fft2", side_effect=AssertionError("No FFT on annotation reprojection")):
            excluded = self.ok("view", object_id=marked["object_id"], frequency_rect=[0, 0, 20, 10],
                               upscale=True, max_size=120)
            restored = self.ok("view", object_id=excluded["object_id"], frequency_rect=None)
        record = excluded["annotations"][0]
        self.assertEqual(record["visibility"], "outside_view")
        self.assertEqual(record["anchor"], before)
        plain = self.ok("view", object_id=self.fft["object_id"], frequency_rect=[0, 0, 20, 10],
                        upscale=True, max_size=120)
        np.testing.assert_array_equal(np.asarray(self.png(excluded).convert("RGB")),
                                      np.asarray(self.png(plain).convert("RGB")))
        self.assertEqual(restored["annotations"][0]["visibility"], "visible")
        self.assertEqual(restored["annotations"][0]["anchor"], before)
        self.assertEqual(restored["annotations"][0]["arrowhead_size"], 2)
        self.assertEqual(restored["annotations"][0]["line_width"], 1)
        self.assertEqual(restored["annotations"][0]["color"], "white")
        self.assert_unchanged()

    def test_axes_margins_and_asymmetric_zoom_transform_are_both_applied(self):
        zoom = self.ok("view", object_id=self.fft["object_id"], frequency_rect=[39, 19, 59, 35],
                       spectrum_axes=True, max_size=512, upscale=True)
        self.assertEqual(zoom["panels"][0]["image_rect_xyxy"], [64, 44, 492, 386])
        self.assertEqual(zoom["panels"][0]["fft_shape_yx"], [55, 95])
        marked = self.frequency_mark(zoom, [0, 0])
        self.assert_coords(marked["annotations"][0]["coordinates"], [245.4, 225.1875])
        self.assertEqual(self.png(marked).size, (512, 442))
        revised = self.ok("view", object_id=marked["object_id"], spectrum_axes=False, max_size=120)
        self.assert_coords(revised["annotations"][0]["coordinates"], [50.5, 50.5])
        self.assertEqual(revised["panels"][0]["image_rect_xyxy"], [0, 0, 120, 96])

    def test_narrow_near_nyquist_zoom_has_distinct_original_frequency_tick_labels(self):
        # Four neighbouring bins of a wide original grid should not all read
        # "0.49", and zoom must not relabel their frequency about zero.
        shown = np.ones((4, 100000), dtype=np.float64)
        settings = {"display_range": [0, 2], "gamma": .8, "max_size": 512,
                    "upscale": True, "spectrum_axes": True, "representation": "amplitude",
                    "spectrum_filter": None, "frequency_rect": [99000, 1, 99004, 3]}
        labels = []
        original = engine.ImageDraw.ImageDraw.text

        def observe(draw, xy, text, *args, **kwargs):
            if kwargs.get("anchor") == "mt":
                try:
                    labels.append(float(text))
                except ValueError:
                    pass  # The horizontal axis caption is not a numeric tick.
            return original(draw, xy, text, *args, **kwargs)

        with patch.object(engine.ImageDraw.ImageDraw, "text", autospec=True, side_effect=observe):
            _, pane = engine.spectrum_canvas(shown, settings, self.fft["object_id"])
        self.assertEqual(len(labels), 3)
        self.assertEqual(len(set(labels)), 3)
        self.assert_coords(labels, [.49, .490015, .49003])
        self.assertTrue(all(.48 < value < .5 for value in labels))
        self.assertEqual(pane["fft_shape_yx"], [4, 100000])
        self.assertEqual(pane["fft_rect_xyxy"], [99000, 1, 99004, 3])

    def test_historical_full_spectrum_panel_without_zoom_field_still_maps_identically(self):
        # Historical manifests are immutable and cannot be backfilled just to
        # add a new presentation field. Its absence must mean the full grid.
        historical = {"domain": "frequency", "source_object_id": self.fft["object_id"],
                      "fft_shape_yx": [55, 95], "dc_bin_xy": [47, 27],
                      "image_rect_xyxy": [0, 0, 95, 55]}
        result = engine.annotation({"kind": "point", "coordinates": [56, 22]},
                                   (95, 55), [historical])
        self.assert_coords(result["anchor"]["coordinates"], [9/95, -5/55])
        self.assert_coords(result["source_mappings"][0]["fft_bin_coordinates"], [56, 22])
        revised = engine.annotation(result, (95, 55), [historical], reproject=True)
        self.assert_coords(revised["coordinates"], [56, 22])
        self.assertEqual(revised["visibility"], "visible")

    def test_one_bin_and_exact_full_boundaries_are_valid_without_implicit_expansion(self):
        for rect, size in [([0, 0, 1, 1], (1, 1)), ([94, 54, 95, 55], (1, 1)),
                           ([0, 0, 95, 55], (95, 55)), ([47, 27, 48, 28], (1, 1))]:
            with self.subTest(rect=rect):
                zoom = self.ok("view", object_id=self.fft["object_id"], frequency_rect=rect,
                               max_size=95, upscale=False)
                self.assertEqual(self.png(zoom).size, size)
                self.assertEqual(zoom["panels"][0]["fft_rect_xyxy"], rect)
                self.assertEqual(zoom["panels"][0]["fft_shape_yx"], [55, 95])
                self.assertEqual(Path(zoom["array_path"]).read_bytes(), self.complex_before)

    def test_last_bin_and_its_outer_region_edges_remain_valid_in_single_bin_zoom(self):
        zoom = self.ok("view", object_id=self.fft["object_id"], frequency_rect=[94, 54, 95, 55],
                       max_size=32, upscale=True)
        point = self.frequency_mark(zoom, [47/95, 27/55])
        self.assertEqual(point["annotations"][0]["visibility"], "visible")
        self.assert_coords(point["annotations"][0]["coordinates"], [15.5, 15.5])
        # The outer edge is half a bin beyond the last centre. It remains an
        # edge of the original spectrum, not a new frequency sample.
        rectangle = self.frequency_mark(zoom, [46.5/95, 26.5/55, 47.5/95, 27.5/55], kind="rectangle")
        self.assert_coords(rectangle["annotations"][0]["coordinates"], [0, 0, 32, 32])
        self.assertEqual(rectangle["annotations"][0]["visibility"], "visible")
        invalid = self.execute("annotate", object_id=zoom["object_id"], annotations=[{
            "kind": "point", "coordinates": [47.5/95, 27/55],
            "coordinate_space": "frequency_cycles_per_pixel", "source_object_id": self.fft["object_id"]}])
        self.assertFalse(invalid["ok"], invalid)

    def test_malformed_out_of_bounds_and_noninteger_frequency_rectangles_refuse(self):
        invalid = [[], [0, 0, 1], [0, 0, 1, 1, 2], [0, 0, 0, 1], [2, 1, 1, 2],
                   [-1, 0, 1, 1], [0, 0, 96, 55], [0, 0, 95, 56], [94, 54, 96, 56],
                   [False, 0, 1, 1], [0, True, 1, 2], [0, 0, 1.0, 1], [0, 0, 1, 1.5],
                   "0,0,1,1", {"x0": 0, "y0": 0, "x1": 1, "y1": 1}]
        for rect in invalid:
            with self.subTest(rect=rect):
                failed = self.execute("view", object_id=self.fft["object_id"], frequency_rect=rect)
                self.assertFalse(failed["ok"], failed)
        self.assert_unchanged()

    def test_spatial_rect_and_frequency_rect_cannot_be_confused_or_applied_to_scalar_compare(self):
        other = self.ok("frame", object_id=self.opened["object_id"], frame_index=1)
        comparison = self.ok("compare", object_ids=[self.frame["object_id"], other["object_id"]])
        for source in (self.frame, comparison):
            for rectangle in ([0, 0, 8, 8], None):
                with self.subTest(kind=source["kind"], rectangle=rectangle):
                    self.assertFalse(self.execute("view", object_id=source["object_id"],
                                                 frequency_rect=rectangle)["ok"])
        for arguments in ({"rect": [0, 0, 8, 8]},
                          {"rect": [0, 0, 8, 8], "frequency_rect": [0, 0, 8, 8]}):
            self.assertFalse(self.execute("view", object_id=self.fft["object_id"], **arguments)["ok"])

    def test_zoom_inherits_full_spectrum_range_and_filter_instead_of_recomputing_local_range(self):
        parameters = {"smooth_sigma_bins": .5, "background_sigma_bins": 3}
        full = self.ok("view", object_id=self.fft["object_id"], spectrum_filter=parameters,
                       gamma=.9, display_range=[0, 3], max_size=95, upscale=False)
        original_filter = engine.spectrum_filter_display
        shapes = []

        def observe(values, specification):
            shapes.append(list(values.shape))
            return original_filter(values, specification)

        with patch.object(engine, "spectrum_filter_display", side_effect=observe), \
             patch.object(np.fft, "fft2", side_effect=AssertionError("Display crop must not recompute FFT")):
            zoom = self.ok("view", object_id=full["object_id"], frequency_rect=[53, 17, 73, 29])
        self.assertEqual(shapes, [[55, 95]])
        self.assertEqual(zoom["display"]["spectrum_filter"], parameters)
        self.assertEqual(zoom["display"]["gamma"], .9)
        self.assertEqual(zoom["display"]["display_range"], [0, 3])
        np.testing.assert_array_equal(np.asarray(self.png(zoom)),
                                      np.asarray(self.png(full).crop((53, 17, 73, 29))))
        # Explicit null means a full-spectrum reset, never a zoom-local stretch.
        unfiltered = self.ok("view", object_id=zoom["object_id"], spectrum_filter=None,
                             display_range=None)
        original_values = np.log1p(np.abs(np.load(self.fft["array_path"])))
        np.testing.assert_allclose(unfiltered["display"]["display_range"],
                                   [original_values.min(), original_values.max()], rtol=0, atol=1e-12)

    def test_gentle_fft_detail_darkens_only_display_without_smoothing_or_background_subtraction(self):
        preset = self.ok("view", object_id=self.fft["object_id"], display_preset="fft_detail",
                         max_size=95, upscale=False)
        self.assertEqual(preset["display"]["gamma"], .8)
        self.assertEqual(preset["display"]["display_preset_revision"], 2)
        self.assertIsNone(preset["display"]["spectrum_filter"])
        self.assertIsNone(preset["display"]["filter_provenance"])
        self.assertEqual(preset["display"]["range_percentiles"], [5, 99.8])
        values = np.log1p(np.abs(np.load(self.fft["array_path"])))
        np.testing.assert_allclose(preset["display"]["display_range"], np.percentile(values, [5, 99.8]),
                                   rtol=0, atol=1e-12)
        plain_gamma = self.ok("view", object_id=preset["object_id"], gamma=1)
        dark, previous = np.asarray(self.png(preset)), np.asarray(self.png(plain_gamma))
        self.assertTrue(np.all(dark <= previous))
        self.assertTrue(np.any(dark < previous))
        zoom = self.ok("view", object_id=preset["object_id"], frequency_rect=[39, 19, 59, 35])
        self.assertEqual(zoom["display"]["gamma"], .8)
        self.assertEqual(zoom["display"]["display_range"], preset["display"]["display_range"])
        self.assertEqual(Path(zoom["array_path"]).read_bytes(), self.complex_before)
        self.assert_unchanged()

    def test_nearest_bin_display_is_an_exact_repeat_and_retains_frequency_coordinates(self):
        # A 5 by 3 bin region enlarged 4x must repeat each display sample,
        # rather than inventing intermediate levels or changing FFT values.
        selected = [51, 29, 56, 32]
        native = self.ok("view", object_id=self.fft["object_id"], frequency_rect=selected,
                         display_range=[0, 14], gamma=.8, upscale=False, max_size=95)
        enlarged = self.ok("view", object_id=native["object_id"], interpolation="nearest", upscale=True, max_size=20)
        self.assertEqual(enlarged["display"]["interpolation"], "nearest")
        self.assertIn("NEAREST", enlarged["display"]["resampling"])
        expected = np.repeat(np.repeat(np.asarray(self.png(native)), 4, axis=0), 4, axis=1)
        np.testing.assert_array_equal(np.asarray(self.png(enlarged)), expected)
        self.assertEqual(enlarged["panels"][0]["fft_rect_xyxy"], selected)
        self.assertEqual(enlarged["panels"][0]["fft_shape_yx"], [55, 95])
        inherited = self.ok("view", object_id=enlarged["object_id"], gamma=.9)
        self.assertEqual(inherited["display"]["interpolation"], "nearest")
        for value in ("auto", "bicubic", None, 0):
            self.assertFalse(self.execute("view", object_id=self.fft["object_id"], interpolation=value)["ok"])
        self.assertEqual(Path(enlarged["array_path"]).read_bytes(), self.complex_before)
        self.assert_unchanged()

    def test_invalid_frequency_region_rejects_before_spectrum_presentation_work(self):
        with patch.object(engine, "spectrum_display", side_effect=AssertionError("Validate the bin window before preparing amplitude")), \
             patch.object(engine, "spectrum_filter_display", side_effect=AssertionError("Invalid window must not filter the spectrum")):
            invalid = self.execute("view", object_id=self.fft["object_id"], frequency_rect=[94, 0, 96, 20])
        self.assertFalse(invalid["ok"], invalid)
        self.assertEqual(invalid["error"]["code"], "INVALID_ARGUMENT")
        self.assert_unchanged()

    def test_original_request_queries_same_zoom_and_changed_bin_parameters_conflict(self):
        request = {"workspace": str(self.workspace), "action": "view", "object_id": self.fft["object_id"],
                   "request_id": "saved-before-zoom", "frequency_rect": [39, 19, 59, 35], "max_size": 120}
        first = engine.execute(request)
        self.assertTrue(first["ok"], first)
        before = sorted(path.name for path in (self.workspace / "objects").iterdir())
        self.assertEqual(engine.execute(request), first)
        queried = engine.execute({"workspace": str(self.workspace), "action": "result",
                                  "query_request_id": "saved-before-zoom"})
        self.assertEqual(queried, first)
        conflict = engine.execute(dict(request, frequency_rect=[40, 19, 60, 35]))
        self.assertFalse(conflict["ok"], conflict)
        self.assertEqual(conflict["error"]["code"], "REQUEST_CONFLICT")
        self.assertEqual(sorted(path.name for path in (self.workspace / "objects").iterdir()), before)
        self.assert_unchanged()


if __name__ == "__main__":
    unittest.main()
