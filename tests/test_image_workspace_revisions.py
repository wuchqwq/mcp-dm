"""Multi-turn regressions on real saved TIFF/NPY objects; no DM or UI required."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image
import tifffile

from tools import image_workspace as engine


class ImageRevisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="image-revisions-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / "workspace"
        self.source = self.root / "input.tiff"
        self.pixels = np.arange(96, dtype=np.uint16).reshape(8, 12)
        tifffile.imwrite(self.source, self.pixels, photometric="minisblack")
        self.source_bytes = self.source.read_bytes()
        self.counter = 0
        self.opened = self.ok("open", source_path=str(self.source))
        self.frame = self.ok("frame", object_id=self.opened["object_id"], frame_index=0)

    def execute(self, action, **args):
        self.counter += 1
        return engine.execute({"workspace": str(self.workspace), "action": action,
                               "request_id": "revision-{}".format(self.counter), **args})

    def ok(self, action, **args):
        reply = self.execute(action, **args)
        self.assertTrue(reply["ok"], reply)
        return reply["result"]

    def assert_source_unchanged(self):
        self.assertEqual(self.source.read_bytes(), self.source_bytes)
        np.testing.assert_array_equal(np.load(self.frame["array_path"]), self.pixels)

    def test_context_survives_view_then_partial_context_and_withdrawal(self):
        fields = {"data_meaning": "user-described phase", "reconstruction_type": "ptychography",
                  "xy_scale": {"x": .1, "y": .2, "unit": "nm", "source": "user note"}}
        initial = self.ok("context", object_id=self.frame["object_id"], metadata=fields)
        viewed = self.ok("view", object_id=initial["object_id"])
        revision = self.ok("context", object_id=viewed["object_id"],
                           metadata={"frame_meaning": "reconstruction slice"})
        self.assertEqual(revision["user_context"], dict(fields, frame_meaning="reconstruction slice"))
        withdrawn = self.ok("context", object_id=revision["object_id"], metadata={"xy_scale": None})
        again = self.ok("view", object_id=withdrawn["object_id"], gamma=2)
        final = self.ok("context", object_id=again["object_id"], metadata={"source_text": "updated"})
        self.assertIsNone(final["user_context"]["xy_scale"])
        self.assertEqual(final["user_context"]["data_meaning"], fields["data_meaning"])
        self.assertEqual(final["user_context"]["frame_meaning"], "reconstruction slice")
        self.assertEqual(self.ok("get", object_id=initial["object_id"])["user_context"], fields)
        output = self.root / "context-export"
        self.ok("export", object_id=final["object_id"], output_dir=str(output))
        manifest = json.loads((output / "manifest.json").read_text())
        self.assertEqual(manifest["user_context"], final["user_context"])
        self.assert_source_unchanged()

    def test_empty_context_patch_after_view_does_not_drop_existing_fields(self):
        context = self.ok("context", object_id=self.frame["object_id"], metadata={"value_unit": None,
                                                                                 "data_meaning": "unknown"})
        viewed = self.ok("view", object_id=context["object_id"])
        revision = self.ok("context", object_id=viewed["object_id"], metadata={})
        self.assertEqual(revision["user_context"], context["user_context"])

    def test_partial_display_update_keeps_range_and_size(self):
        viewed = self.ok("view", object_id=self.frame["object_id"], rect=[2, 1, 10, 7],
                         display_range=[0, 65535], gamma=1, max_size=4)
        revision = self.ok("view", object_id=viewed["object_id"], gamma=2)
        self.assertEqual(revision["display"]["display_range"], [0., 65535.])
        self.assertEqual(revision["display"]["max_size"], 4)
        self.assertEqual(revision["display"]["gamma"], 2.)
        self.assertEqual(Path(viewed["array_path"]).read_bytes(), Path(revision["array_path"]).read_bytes())
        reset = self.ok("view", object_id=revision["object_id"], display_range=None)
        self.assertEqual(reset["display"]["display_range"], [14., 81.])
        self.assertEqual(reset["display"]["gamma"], 2.)
        self.assertEqual(reset["display"]["max_size"], 4)
        self.assert_source_unchanged()

    def test_constant_auto_range_can_be_inherited_but_invalid_explicit_range_rejects(self):
        other = self.root / "constant.tiff"
        tifffile.imwrite(other, np.full((4, 4), 7, np.uint16))
        opened = self.ok("open", source_path=str(other))
        frame = self.ok("frame", object_id=opened["object_id"], frame_index=0)
        view = self.ok("view", object_id=frame["object_id"], gamma=2)
        revised = self.ok("view", object_id=view["object_id"], max_size=2)
        self.assertTrue(revised["display"]["constant_range"])
        self.assertEqual(revised["display"]["gamma"], 2)
        self.assertTrue(np.all(np.asarray(Image.open(revised["image_path"])) == 0))
        self.assertFalse(self.execute("view", object_id=view["object_id"], display_range=[7, 7])["ok"])

    def test_fft_view_reuses_complex_bytes_and_does_not_execute_another_fft(self):
        context = self.ok("context", object_id=self.frame["object_id"], metadata={"data_meaning": "test slices"})
        fft = self.ok("fft", object_id=context["object_id"], rect=[1, 1, 10, 8], subtract_mean=True)
        original = Path(fft["array_path"]).read_bytes()
        with patch.object(np.fft, "fft2", side_effect=AssertionError("display must not compute FFT")):
            view = self.ok("view", object_id=fft["object_id"], gamma=2, max_size=5)
            revised_context = self.ok("context", object_id=view["object_id"], metadata={"frame_meaning": "slice index"})
            again = self.ok("view", object_id=revised_context["object_id"], gamma=.8)
        self.assertEqual(view["kind"], "fft_view")
        self.assertFalse(view["fft_recomputed"])
        self.assertFalse(view["scientific_data_changed"])
        self.assertEqual(view["spectrum_object_id"], fft["object_id"])
        self.assertEqual(again["spectrum_object_id"], fft["object_id"])
        self.assertEqual(again["frequency_axes"], fft["frequency_axes"])
        self.assertEqual(again["display"]["display_range"], fft["display"]["display_range"])
        self.assertEqual(again["user_context"], {"data_meaning": "test slices", "frame_meaning": "slice index"})
        self.assertEqual(original, Path(view["array_path"]).read_bytes())
        self.assertEqual(original, Path(again["array_path"]).read_bytes())
        self.assertEqual(original, Path(fft["array_path"]).read_bytes())
        self.assert_source_unchanged()

    def test_fft_display_modes_have_independent_ranges_and_keep_frequency_mapping(self):
        other = self.root / "known-bins.tiff"
        tifffile.imwrite(other, np.tile([0, 1, 0, 1], (4, 1)).astype(np.uint16))
        opened = self.ok("open", source_path=str(other))
        frame = self.ok("frame", object_id=opened["object_id"], frame_index=0)
        fft = self.ok("fft", object_id=frame["object_id"])
        amplitude = self.ok("view", object_id=fft["object_id"], representation="amplitude", gamma=2)
        power = self.ok("view", object_id=amplitude["object_id"], representation="power")
        self.assertEqual(amplitude["display"]["display_range"], [0., 8.])
        self.assertEqual(power["display"]["display_range"], [0., 64.])
        self.assertEqual(power["display"]["gamma"], 2.)
        self.assertEqual(power["dtype"], "complex128")
        annotation = self.ok("annotate", object_id=power["object_id"], annotations=[
            {"kind": "point", "coordinates": [2, 2], "status": "hypothesized"}])
        mapping = annotation["annotations"][0]["source_mappings"][0]
        self.assertEqual(mapping["source_object_id"], fft["object_id"])
        self.assertEqual(mapping["frequency_cycles_per_pixel"], [0., 0.])
        retracted = self.ok("annotate", object_id=annotation["object_id"], annotations=[])
        np.testing.assert_array_equal(np.asarray(Image.open(retracted["image_path"])),
                                      np.asarray(Image.open(power["image_path"]).convert("RGB")))
        output = self.root / "spectrum-export"
        self.ok("export", object_id=annotation["object_id"], output_dir=str(output))
        self.assertEqual((output / "data.npy").read_bytes(), Path(fft["array_path"]).read_bytes())
        manifest = json.loads((output / "manifest.json").read_text())
        self.assertEqual(manifest["scientific_object"]["frequency_axes"], fft["frequency_axes"])
        self.assertEqual(manifest["display_mapping"]["representation"], "power")

    def test_fft_representation_change_resets_only_range_unless_explicitly_supplied(self):
        fft = self.ok("fft", object_id=self.frame["object_id"])
        first = self.ok("view", object_id=fft["object_id"], representation="amplitude",
                        display_range=[0, 100], gamma=2, max_size=4)
        second = self.ok("view", object_id=first["object_id"], representation="power")
        expected_max = float(np.max(np.abs(np.load(fft["array_path"])) ** 2))
        self.assertEqual(second["display"]["display_range"][1], expected_max)
        self.assertEqual(second["display"]["gamma"], 2.)
        self.assertEqual(second["display"]["max_size"], 4)
        explicit = self.ok("view", object_id=second["object_id"], representation="log_amplitude",
                           display_range=[0, 3])
        self.assertEqual(explicit["display"]["display_range"], [0., 3.])

    def test_spectrum_views_cannot_be_misread_as_spatial_data_or_silently_cropped(self):
        fft = self.ok("fft", object_id=self.frame["object_id"])
        view = self.ok("view", object_id=fft["object_id"])
        for action, args in [("measure", {"points": [[0, 0], [1, 1]]}), ("fft", {}),
                             ("view", {"rect": [0, 0, 4, 4]})]:
            with self.subTest(action=action):
                self.assertFalse(self.execute(action, object_id=view["object_id"], **args)["ok"])
        self.assertFalse(self.execute("view", object_id=self.frame["object_id"], representation="power")["ok"])
        self.assertFalse(self.execute("view", object_id=fft["object_id"], representation="invented")["ok"])

    def test_display_revision_original_id_is_durable_and_conflicting_parameters_refuse(self):
        fft = self.ok("fft", object_id=self.frame["object_id"])
        request = {"workspace": str(self.workspace), "action": "view", "object_id": fft["object_id"],
                   "gamma": 2, "request_id": "saved-view"}
        first = engine.execute(request)
        self.assertTrue(first["ok"], first)
        self.assertEqual(engine.execute(request), first)
        queried = engine.execute({"workspace": str(self.workspace), "action": "result",
                                  "query_request_id": "saved-view"})
        self.assertEqual(queried, first)
        conflict = engine.execute(dict(request, gamma=3))
        self.assertEqual(conflict["error"]["code"], "REQUEST_CONFLICT")


if __name__ == "__main__":
    unittest.main()
