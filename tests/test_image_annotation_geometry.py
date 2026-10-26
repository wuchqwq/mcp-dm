"""Independent overlay geometry checks over saved scalar/complex scientific data.

The expected coordinates below come from the stated pixel-centre/edge geometry,
not from the production mapping helpers. All TIFFs are synthetic and temporary.
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


class ImageAnnotationGeometryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="annotation-geometry-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / "workspace"
        self.source = self.root / "asymmetric.tiff"
        self.pixels = np.arange(96 * 160, dtype=np.uint16).reshape(96, 160)
        tifffile.imwrite(self.source, np.stack([self.pixels, self.pixels + 1000]),
                         photometric="minisblack", metadata=None)
        self.original_file = self.source.read_bytes()
        self.counter = 0
        self.opened = self.ok("open", source_path=str(self.source))
        self.frame = self.ok("frame", object_id=self.opened["object_id"], frame_index=0)
        self.other = self.ok("frame", object_id=self.opened["object_id"], frame_index=1)

    def execute(self, action, **arguments):
        self.counter += 1
        return engine.execute({"workspace": str(self.workspace), "action": action,
                               "request_id": "geometry-{}".format(self.counter), **arguments})

    def ok(self, action, **arguments):
        response = self.execute(action, **arguments)
        self.assertTrue(response["ok"], response)
        return response["result"]

    def view(self, **arguments):
        return self.ok("view", object_id=self.frame["object_id"],
                       rect=[20, 12, 140, 84], max_size=60, **arguments)

    def mark(self, parent, kind, coordinates, **extra):
        return self.ok("annotate", object_id=parent["object_id"], annotations=[{
            "kind": kind, "coordinates": coordinates, "coordinate_space": "source_pixels",
            "source_object_id": self.frame["object_id"], "annotation_id": "candidate-a",
            "status": "hypothesized", **extra}])

    def assert_coordinates(self, actual, expected):
        self.assertEqual(len(actual), len(expected))
        for a, b in zip(actual, expected):
            self.assertAlmostEqual(a, b, places=10)

    def assert_anchor(self, annotation, coordinates, source=None, space="source_pixels"):
        self.assertEqual(annotation["anchor"], {
            "coordinate_space": space, "source_object_id": source or self.frame["object_id"],
            "coordinates": coordinates})

    def assert_source_unchanged(self):
        self.assertEqual(self.source.read_bytes(), self.original_file)
        np.testing.assert_array_equal(np.load(self.frame["array_path"]), self.pixels)

    def png_size(self, metadata):
        with Image.open(metadata["image_path"]) as image:
            return image.size

    def test_source_line_centres_survive_non_square_thumbnail_and_display_revision(self):
        view = self.view(display_range=[0, 20000])
        self.assertEqual(self.png_size(view), (60, 36))
        coordinates = [40, 30, 100, 66]
        marked = self.mark(view, "line", coordinates)
        self.assert_coordinates(marked["annotations"][0]["coordinates"], [9.75, 8.75, 39.75, 26.75])
        self.assert_anchor(marked["annotations"][0], coordinates)
        revised = self.ok("view", object_id=marked["object_id"], max_size=120, gamma=2)
        self.assertEqual(self.png_size(revised), (120, 72))
        self.assert_coordinates(revised["annotations"][0]["coordinates"], [20, 18, 80, 54])
        self.assert_anchor(revised["annotations"][0], coordinates)
        self.assertEqual(revised["display"]["display_range"], [0, 20000])
        self.assertEqual(revised["annotations"][0]["status"], "hypothesized")
        np.testing.assert_array_equal(np.load(revised["array_path"]), self.pixels[12:84, 20:140])
        self.assert_source_unchanged()

    def test_arrow_and_point_use_centres_while_rectangles_and_polygons_use_edges(self):
        view = self.view()
        checks = [
            ("point", [40, 30], [9.75, 8.75]),
            ("text", [40, 30], [9.75, 8.75]),
            ("arrow", [40, 30, 100, 66], [9.75, 8.75, 39.75, 26.75]),
            ("rectangle", [40, 24, 100, 60], [10, 6, 40, 24]),
            ("polygon", [24, 18, 60, 18, 72, 54, 24, 54], [2, 3, 20, 3, 26, 21, 2, 21]),
        ]
        for kind, coordinates, rendered in checks:
            with self.subTest(kind=kind):
                marked = self.mark(view, kind, coordinates, text="candidate")
                self.assert_coordinates(marked["annotations"][0]["coordinates"], rendered)
                self.assert_anchor(marked["annotations"][0], coordinates)

    def test_nested_roi_composes_offsets_and_keeps_original_frame_identity(self):
        first = self.view()
        nested = self.ok("view", object_id=first["object_id"], rect=[10, 6, 70, 54], max_size=60)
        self.assertEqual(nested["panels"][0]["source_object_id"], self.frame["object_id"])
        self.assertEqual(nested["panels"][0]["source_rect_xyxy"], [30, 18, 90, 66])
        marked = self.mark(nested, "arrow", [40, 30, 80, 60])
        self.assert_coordinates(marked["annotations"][0]["coordinates"], [10, 12, 50, 42])
        np.testing.assert_array_equal(np.load(nested["array_path"]), self.pixels[18:66, 30:90])
        self.assert_source_unchanged()

    def test_crop_excluding_anchor_preserves_it_without_drawing_or_clipping(self):
        view = self.view()
        coordinates = [40, 30, 100, 66]
        marked = self.mark(view, "line", coordinates)
        # The new ROI includes one endpoint only. The old line must not be
        # clipped into a misleading shorter line or attached to another source.
        cropped = self.ok("view", object_id=marked["object_id"], rect=[60, 40, 120, 72])
        record = cropped["annotations"][0]
        self.assert_anchor(record, coordinates)
        self.assertEqual(record["visibility"], "outside_view")
        plain = self.ok("view", object_id=view["object_id"], rect=[60, 40, 120, 72])
        np.testing.assert_array_equal(np.asarray(Image.open(cropped["image_path"]).convert("RGB")),
                                      np.asarray(Image.open(plain["image_path"]).convert("RGB")))

    def test_two_panel_anchor_selects_explicit_frame_and_reprojects_with_panel_offset(self):
        compared = self.ok("compare", object_ids=[self.frame["object_id"], self.other["object_id"]],
                           rect=[20, 12, 140, 84], max_size=80, display_range=[0, 20000])
        self.assertEqual(self.png_size(compared), (80, 24))
        coordinates = [50, 36]
        marked = self.ok("annotate", object_id=compared["object_id"], annotations=[{
            "kind": "point", "coordinates": coordinates, "coordinate_space": "source_pixels",
            "source_object_id": self.other["object_id"], "annotation_id": "right-only"}])
        self.assert_coordinates(marked["annotations"][0]["coordinates"], [49 + 2/3, 7 + 2/3])
        revised = self.ok("view", object_id=marked["object_id"], max_size=120, gamma=.8)
        self.assertEqual(self.png_size(revised), (120, 36))
        self.assert_coordinates(revised["annotations"][0]["coordinates"], [74.75, 11.75])
        self.assert_anchor(revised["annotations"][0], coordinates, source=self.other["object_id"])
        self.assertEqual(revised["display"]["display_range"], [0, 20000])
        self.assertEqual(len([name for name in revised["files_sha256"] if name.endswith(".npy")]), 2)

    def test_cross_panel_legacy_rectangle_stays_legacy_and_refuses_automatic_projection(self):
        compared = self.ok("compare", object_ids=[self.frame["object_id"], self.other["object_id"]],
                           rect=[20, 12, 140, 84], max_size=80)
        # Rendered rectangle crosses the boundary at x=40, so no single source
        # identity can justify an automatic coordinate conversion.
        marked = self.ok("annotate", object_id=compared["object_id"], annotations=[{
            "kind": "rectangle", "coordinates": [30, 5, 50, 20], "status": "hypothesized"}])
        failed = self.execute("view", object_id=marked["object_id"], max_size=120)
        self.assertFalse(failed["ok"], failed)

    def test_legacy_rendered_point_obtains_one_source_anchor_for_safe_revision(self):
        view = self.view()
        marked = self.ok("annotate", object_id=view["object_id"], annotations=[{
            "kind": "point", "coordinates": [9.75, 8.75], "status": "hypothesized"}])
        self.assert_anchor(marked["annotations"][0], [40., 30.])
        revised = self.ok("view", object_id=marked["object_id"], max_size=120)
        self.assert_coordinates(revised["annotations"][0]["coordinates"], [20, 18])

    def test_odd_non_square_fft_frequency_anchor_preserves_signed_axes_and_complex_bytes(self):
        fft = self.ok("fft", object_id=self.frame["object_id"], rect=[11, 9, 106, 64],
                      max_size=32, subtract_mean=True, window="hann")
        self.assertEqual(fft["shape_yx"], [55, 95])
        self.assertEqual(self.png_size(fft), (32, 19))
        original = Path(fft["array_path"]).read_bytes()
        frequency = [9/95, -5/55]
        marked = self.ok("annotate", object_id=fft["object_id"], annotations=[{
            "kind": "point", "coordinates": frequency, "coordinate_space": "frequency_cycles_per_pixel",
            "source_object_id": fft["object_id"], "annotation_id": "signed-frequency"}])
        # Positive fx: bin 47+9=56. Negative fy: bin 27-5=22.
        self.assert_coordinates(marked["annotations"][0]["coordinates"],
                                [56.5 * 32/95 - .5, 22.5 * 19/55 - .5])
        with patch.object(np.fft, "fft2", side_effect=AssertionError("Re-render must not recompute FFT")):
            revised = self.ok("view", object_id=marked["object_id"], max_size=95,
                              representation="amplitude", gamma=2)
        self.assert_coordinates(revised["annotations"][0]["coordinates"], [56, 22])
        self.assert_anchor(revised["annotations"][0], frequency, source=fft["object_id"],
                           space="frequency_cycles_per_pixel")
        self.assertEqual(revised["panels"][0]["source_object_id"], fft["object_id"])
        self.assertEqual(revised["frequency_axes"], fft["frequency_axes"])
        self.assertIsNone(revised["physical_frequency_unit"])
        self.assertEqual(Path(revised["array_path"]).read_bytes(), original)
        self.assertEqual(Path(fft["array_path"]).read_bytes(), original)
        self.assert_source_unchanged()

    def test_frequency_rectangle_edges_are_distinct_from_point_centres(self):
        fft = self.ok("fft", object_id=self.frame["object_id"], rect=[11, 9, 106, 64], max_size=32)
        marked = self.ok("annotate", object_id=fft["object_id"], annotations=[{
            "kind": "rectangle", "coordinates": [-.1, -.1, .1, .1],
            "coordinate_space": "frequency_cycles_per_pixel", "source_object_id": fft["object_id"]}])
        self.assert_coordinates(marked["annotations"][0]["coordinates"], [12.8, 7.6, 19.2, 11.4])
        point = self.ok("annotate", object_id=fft["object_id"], annotations=[{
            "kind": "point", "coordinates": [0, 0], "coordinate_space": "frequency_cycles_per_pixel",
            "source_object_id": fft["object_id"]}])
        self.assert_coordinates(point["annotations"][0]["coordinates"], [15.5, 9.])

    def test_last_bin_of_eleven_pixel_fft_stays_visible_after_rerender(self):
        fft = self.ok("fft", object_id=self.frame["object_id"], rect=[1, 2, 12, 13], max_size=32)
        marked = self.ok("annotate", object_id=fft["object_id"], annotations=[{
            "kind": "point", "coordinates": [10, 10], "annotation_id": "last-bin",
            "status": "hypothesized"}])
        # With DC at index5 the last bin is exactly the binary64 result of
        # (10-5)/11. Separately rounded -5/11+10*(1/11) lies one ulp higher,
        # which previously made the same valid bin disappear on re-render.
        self.assert_anchor(marked["annotations"][0], [5/11, 5/11], source=fft["object_id"],
                           space="frequency_cycles_per_pixel")
        with patch.object(np.fft, "fft2", side_effect=AssertionError("No FFT on display revision")):
            revised = self.ok("view", object_id=marked["object_id"], gamma=2, max_size=64)
        self.assertEqual(revised["annotations"][0]["visibility"], "visible")
        self.assert_coordinates(revised["annotations"][0]["coordinates"], [10, 10])
        self.assertEqual(revised["annotations"][0]["anchor"], marked["annotations"][0]["anchor"])
        self.assertEqual(Path(revised["array_path"]).read_bytes(), Path(fft["array_path"]).read_bytes())

    def test_rendered_centres_beyond_last_centre_reject_but_pixel_edges_remain_valid(self):
        view = self.view()
        for kind, coordinates in [("point", [59.1, 10]), ("point", [20, 35.1]),
                                  ("text", [59.9, 20]), ("line", [2, 3, 59.9, 10]),
                                  ("arrow", [2, 3, 20, 35.9])]:
            with self.subTest(kind=kind, coordinates=coordinates):
                response = self.execute("annotate", object_id=view["object_id"], annotations=[{
                    "kind": kind, "coordinates": coordinates, "text": "candidate"}])
                self.assertFalse(response["ok"], response)
        # Edges remain half-open pixel boundaries, so right=60,bottom=36 is
        # legitimate for a region, but cannot be a point/line centre.
        valid = self.ok("annotate", object_id=view["object_id"], annotations=[{
            "kind": "rectangle", "coordinates": [0, 0, 60, 36]}])
        self.assert_anchor(valid["annotations"][0], [20., 12., 140., 84.])

    def test_duplicate_annotation_identity_refuses_whole_replacement_revision(self):
        view = self.view()
        response = self.execute("annotate", object_id=view["object_id"], annotations=[{
            "kind": "point", "coordinates": [10, 10], "annotation_id": "same-candidate",
            "status": "hypothesized"}, {
            "kind": "point", "coordinates": [20, 20], "annotation_id": "same-candidate",
            "status": "user_confirmed"}])
        self.assertFalse(response["ok"], response)
        self.assertIn("Duplicate annotation_id", response["error"]["message"])
        # There was no partially published success, and the input view remains
        # readable and unchanged after the rejected conflicting layer.
        current = self.ok("get", object_id=view["object_id"])
        self.assertEqual(current["files_sha256"], view["files_sha256"])
        self.assert_source_unchanged()

    def test_source_and_frequency_spaces_cannot_be_confused_or_rebound(self):
        view = self.view()
        fft = self.ok("fft", object_id=self.frame["object_id"], rect=[11, 9, 106, 64])
        invalid = [
            (view, {"coordinate_space": "source_pixels", "coordinates": [40, 30]}),
            (view, {"coordinate_space": "source_pixels", "source_object_id": self.other["object_id"], "coordinates": [40, 30]}),
            (view, {"coordinate_space": "frequency_cycles_per_pixel", "source_object_id": self.frame["object_id"], "coordinates": [0, 0]}),
            (fft, {"coordinate_space": "source_pixels", "source_object_id": fft["object_id"], "coordinates": [40, 30]}),
            (fft, {"coordinate_space": "frequency_cycles_per_pixel", "source_object_id": self.frame["object_id"], "coordinates": [0, 0]}),
        ]
        for parent, item in invalid:
            with self.subTest(item=item):
                response = self.execute("annotate", object_id=parent["object_id"],
                                        annotations=[{"kind": "point", **item}])
                self.assertFalse(response["ok"], response)

    def test_malformed_geometry_and_status_are_rejected(self):
        view = self.view()
        invalid = [
            {"kind": "line", "coordinates": [1, 2]},
            {"kind": "arrow", "coordinates": [1, 2, 3]},
            {"kind": "polygon", "coordinates": [1, 2, 3, 4]},
            {"kind": "polygon", "coordinates": [1, 2, 3, 4, 5, 6, 7]},
            {"kind": "polygon", "coordinates": [1, 2] * 33},
            {"kind": "line", "coordinates": [1, 2, float("nan"), 4]},
            {"kind": "rectangle", "coordinates": [10, 2, 5, 6]},
            {"kind": "point", "coordinates": [1, 2], "status": "automatically_confirmed"},
        ]
        for item in invalid:
            with self.subTest(item=item):
                self.assertFalse(self.execute("annotate", object_id=view["object_id"], annotations=[item])["ok"])

    def test_annotation_status_revisions_export_values_picture_and_history(self):
        view = self.view(display_range=[0, 20000])
        coordinates = [40, 30, 100, 66]
        proposed = self.mark(view, "line", coordinates, note="Possible stripe; no defect claim")
        confirmed = self.mark(proposed, "line", coordinates, status="user_confirmed", note="User confirmed location only")
        withdrawn = self.mark(confirmed, "line", coordinates, status="retracted", note="User withdrew interpretation")
        self.assertEqual(self.ok("get", object_id=proposed["object_id"])["annotations"][0]["status"], "hypothesized")
        self.assertEqual(self.ok("get", object_id=confirmed["object_id"])["annotations"][0]["status"], "user_confirmed")
        self.assertEqual(withdrawn["annotations"][0]["status"], "retracted")
        np.testing.assert_array_equal(np.asarray(Image.open(withdrawn["image_path"]).convert("RGB")),
                                      np.asarray(Image.open(view["image_path"]).convert("RGB")))
        revised = self.ok("view", object_id=withdrawn["object_id"], gamma=2, max_size=120)
        destination = self.root / "new-export"
        self.ok("export", object_id=revised["object_id"], output_dir=str(destination))
        manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
        provenance = json.loads((destination / "provenance.json").read_text(encoding="utf-8"))
        np.testing.assert_array_equal(np.load(destination / "data.npy"), self.pixels[12:84, 20:140])
        self.assertEqual((destination / "preview.png").read_bytes(), Path(revised["image_path"]).read_bytes())
        self.assertEqual(manifest["display_object"]["annotations"][0]["status"], "retracted")
        self.assert_anchor(manifest["display_object"]["annotations"][0], coordinates)
        self.assertTrue(manifest["scientific_NPY_is_not_display_PNG"])
        self.assertFalse(manifest["dm_save_as_called"])
        for historical in (proposed, confirmed, withdrawn):
            self.assertIn(historical["object_id"], provenance["objects"])
        self.assertFalse(self.execute("export", object_id=revised["object_id"], output_dir=str(destination))["ok"])
        self.assert_source_unchanged()


if __name__ == "__main__":
    unittest.main()
