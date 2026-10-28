"""Presentation edits are persisted display metadata, not scientific moves."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

HAS_IMAGES = all(importlib.util.find_spec(name) is not None for name in ("numpy", "PIL", "tifffile"))
if HAS_IMAGES:
    import numpy as np
    import tifffile
    from tools.image_workspace import execute


@unittest.skipUnless(HAS_IMAGES, "Independent image dependencies are required")
class AnnotationPresentationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.workspace = self.root / "images"
        self.counter = 0
        self.source = self.root / "synthetic.tiff"
        y, x = np.indices((96, 128))
        tifffile.imwrite(self.source, np.rint(2000+500*np.cos(2*np.pi*x/16)+300*np.cos(2*np.pi*y/24)).astype(np.uint16), photometric="minisblack")
        opened = self.call("open", source_path=str(self.source))
        self.frame = self.call("frame", object_id=opened["object_id"], frame_index=0)
        self.view = self.call("view", object_id=self.frame["object_id"], max_size=64)

    def tearDown(self):
        self.temporary.cleanup()

    def request(self, action, **arguments):
        self.counter += 1
        return {"workspace": str(self.workspace), "action": action, "request_id": "presentation-{}".format(self.counter), **arguments}

    def call(self, action, **arguments):
        response = execute(self.request(action, **arguments))
        self.assertTrue(response.get("ok"), response)
        return response["result"]

    def mark(self, presentation=None):
        mark = {"annotation_id": "measured-peak", "kind": "point", "coordinates": [24., 24.],
                "coordinate_space": "source_pixels", "source_object_id": self.view["panels"][0]["source_object_id"],
                "status": "user_confirmed", "text": "Only peak location confirmed", "color": "white"}
        if presentation is not None:
            mark["presentation"] = presentation
        return self.call("annotate", object_id=self.view["object_id"], annotations=[mark])

    def test_label_drag_and_style_patch_preserve_scientific_anchor_text_status_and_other_presentation_fields(self):
        initial = self.mark({"marker_shape": "double_circle", "marker_radius": 6, "line_width": 1.25, "category": "shared",
                             "label": {"text": "g₁", "offset": [16., -12.], "font_size": 13., "leader": True, "important": True}})
        initial_manifest = Path(initial["manifest_path"]).read_bytes()
        source, pixels = self.source.read_bytes(), Path(self.frame["array_path"]).read_bytes()
        changed = self.call("annotate", object_id=initial["object_id"], updates=[
            {"annotation_id": "measured-peak", "presentation": {"label": {"text": "g₂", "offset": [28., -20.], "pinned": True}}}])
        old, new = initial["annotations"][0], changed["annotations"][0]
        for key in ("anchor", "source_mappings", "status", "text", "color", "coordinates"):
            self.assertEqual(new[key], old[key])
        self.assertEqual(new["presentation"]["marker_shape"], "double_circle")
        self.assertEqual(new["presentation"]["line_width"], 1.25)
        self.assertEqual(new["presentation"]["label"], {"text": "g₂", "offset": [28., -20.], "font_size": 13., "leader": True, "important": True, "pinned": True})
        self.assertEqual(Path(initial["manifest_path"]).read_bytes(), initial_manifest)
        self.assertEqual(self.source.read_bytes(), source)
        self.assertEqual(Path(self.frame["array_path"]).read_bytes(), pixels)

    def test_anchor_move_retains_independent_label_layout_and_presentation_survives_reprojection_and_export(self):
        presentation = {"marker_shape": "square", "category": "A", "layer": "experimental", "geometry_visible": True,
                        "label": {"offset": [18, -10], "visible": True, "figure_visible": False}}
        initial = self.mark(presentation)
        moved = self.call("annotate", object_id=initial["object_id"], updates=[{"annotation_id": "measured-peak", "coordinates": [40., 30.]}])
        new_view = self.call("view", object_id=moved["object_id"], max_size=128, gamma=.8)
        mark = new_view["annotations"][0]
        self.assertEqual(mark["anchor"]["coordinates"], [40., 30.])
        self.assertEqual(mark["presentation"], presentation)
        self.assertEqual(mark["status"], "user_confirmed")
        output = self.root / "export"
        self.call("export", object_id=new_view["object_id"], output_dir=str(output))
        manifest = json.loads((output / "manifest.json").read_text(encoding="utf8"))
        self.assertEqual(manifest["display_object"]["annotations"][0]["presentation"], presentation)
        self.assertEqual((output / "data.npy").read_bytes(), Path(self.frame["array_path"]).read_bytes())

    def test_saved_fft_label_edit_reuses_exact_complex_array_and_frequency_anchor(self):
        fft = self.call("fft", object_id=self.frame["object_id"], rect=[0, 0, 128, 96], window="none", subtract_mean=True, max_size=128)
        original = Path(fft["array_path"]).read_bytes()
        marked = self.call("annotate", object_id=fft["object_id"], annotations=[
            {"annotation_id": "frequency", "kind": "point", "coordinates": [1/16, 0], "coordinate_space": "frequency_cycles_per_pixel",
             "source_object_id": fft["object_id"], "status": "hypothesized", "text": "g1"}])
        changed = self.call("annotate", object_id=marked["object_id"], updates=[
            {"annotation_id": "frequency", "presentation": {"label": {"offset": [20, 14], "text": "g₁"}}}])
        viewed = self.call("view", object_id=changed["object_id"], max_size=256)
        self.assertFalse(viewed["fft_recomputed"])
        self.assertEqual(viewed["annotations"][0]["anchor"]["coordinates"], [1/16, 0])
        self.assertEqual(viewed["annotations"][0]["status"], "hypothesized")
        self.assertEqual(Path(fft["array_path"]).read_bytes(), original)
        self.assertEqual(Path(viewed["array_path"]).read_bytes(), original)

    def test_numeric_label_measurement_reference_survives_sparse_label_layout_patch(self):
        measured = self.call("measure", object_id=self.view["object_id"], coordinate_space="source_pixels", points=[[0, 0], [24, 24]])
        reference = {"measurement_object_id": measured["object_id"], "measurement_kind": "distance"}
        initial = self.mark({"label": {"text": "measured distance", **reference}})
        changed = self.call("annotate", object_id=initial["object_id"], updates=[
            {"annotation_id": "measured-peak", "presentation": {"label": {"offset": [18, -10]}}}])
        self.assertEqual({key: changed["annotations"][0]["presentation"]["label"][key] for key in reference}, reference)
        self.assertEqual(changed["annotations"][0]["anchor"], initial["annotations"][0]["anchor"])
        self.assertEqual(changed["annotations"][0]["status"], "user_confirmed")

    def test_recipe_replacement_clears_later_style_override_without_changing_scientific_anchor(self):
        initial = self.mark({"marker_shape": "diamond", "label": {"text": "later text", "offset": [25, -8], "pinned": True}})
        old = Path(initial["manifest_path"]).read_bytes()
        recipe = {"label": {"text": "original recipe", "offset": [12, -6]}}
        changed = self.call("annotate", object_id=initial["object_id"], updates=[
            {"annotation_id": "measured-peak", "presentation": recipe, "presentation_replace": True}])
        mark = changed["annotations"][0]
        self.assertEqual(mark["presentation"], recipe)
        self.assertNotIn("marker_shape", mark["presentation"])
        self.assertNotIn("presentation_replace", mark)
        self.assertEqual(mark["anchor"], initial["annotations"][0]["anchor"])
        self.assertEqual(mark["status"], "user_confirmed")
        self.assertEqual(Path(initial["manifest_path"]).read_bytes(), old)
        for update in ({"presentation_replace": True}, {"presentation": {}, "presentation_replace": "yes"}):
            response = execute(self.request("annotate", object_id=initial["object_id"], updates=[
                {"annotation_id": "measured-peak", **update}]))
            self.assertFalse(response.get("ok"), response)

    def test_invalid_presentation_cannot_smuggle_authority_coordinates_executable_attributes_or_nonfinite_layout(self):
        initial = self.mark()
        before = Path(initial["manifest_path"]).read_bytes()
        invalid = [{"status": "user_confirmed"}, {"coordinates": [0, 0]}, {"marker_shape": "<script>"},
                   {"marker_radius": 13}, {"line_width": .1}, {"geometry_visible": 1},
                   {"label": {"offset": [1, float("inf")]}}, {"label": {"offset": [0, 4097]}},
                   {"label": {"font_size": 7}}, {"label": {"href": "javascript:alert(1)"}},
                   {"label": {"visible": "yes"}}, {"label": {"text": "x"*257}},
                   {"label": {"measurement_object_id": "not-a-saved-id"}},
                   {"label": {"measurement_object_id": "a"*33}}, {"label": {"measurement_kind": "intensity"}}]
        for presentation in invalid:
            with self.subTest(presentation=presentation):
                response = execute(self.request("annotate", object_id=initial["object_id"], updates=[
                    {"annotation_id": "measured-peak", "presentation": copy.deepcopy(presentation)}]))
                self.assertFalse(response.get("ok"), response)
        self.assertEqual(Path(initial["manifest_path"]).read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
