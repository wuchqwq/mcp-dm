"""Run after applying to PR18: real workspace + renderer; synthetic TIFF only.

These tests require the full target repository, NumPy, Pillow and tifffile.
They are distinct from the separately runnable pure edit-planning tests.
"""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

import numpy as np
import tifffile
from tools import image_workspace as engine


class AnnotationUpdateIntegration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="annotation-updates-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "synthetic.tiff"
        tifffile.imwrite(self.source, np.arange(32 * 48, dtype=np.uint16).reshape(32, 48))
        self.source_before = self.source.read_bytes()
        self.counter = 0
        opened = self.ok("open", source_path=str(self.source))
        self.frame = self.ok("frame", object_id=opened["object_id"], frame_index=0)
        self.view = self.ok("view", object_id=self.frame["object_id"])
        self.marked = self.ok("annotate", object_id=self.view["object_id"], annotations=[
            dict(annotation_id="a", kind="arrow", coordinates=[3, 3, 20, 10],
                 coordinate_space="source_pixels", source_object_id=self.frame["object_id"], status="hypothesized"),
            dict(annotation_id="b", kind="point", coordinates=[40, 25],
                 coordinate_space="source_pixels", source_object_id=self.frame["object_id"], status="user_confirmed")])

    def call(self, action, **kwargs):
        self.counter += 1
        return engine.execute(dict(workspace=str(self.root / "workspace"), action=action,
                                   request_id="update-test-" + str(self.counter), **kwargs))

    def ok(self, action, **kwargs):
        answer = self.call(action, **kwargs)
        self.assertTrue(answer["ok"], answer)
        return answer["result"]

    def test_edit_one_mark_keeps_others_and_source(self):
        old = deepcopy(self.marked["annotations"])
        changed = self.ok("annotate", object_id=self.marked["object_id"], updates=[dict(annotation_id="a", text="revised")])
        self.assertEqual(changed["annotations"][0]["text"], "revised")
        self.assertEqual(changed["annotations"][1], old[1])
        self.assertEqual(self.marked["annotations"], old)
        self.assertEqual(self.source.read_bytes(), self.source_before)
        self.assertFalse(changed["scientific_data_changed"])
        self.assertEqual(changed["annotation_edit_mode"], "update")

    def test_move_keeps_scientific_anchor_through_resize(self):
        moved = self.ok("annotate", object_id=self.marked["object_id"], updates=[dict(annotation_id="a", coordinates=[4, 4, 22, 11])])
        resized = self.ok("view", object_id=moved["object_id"], max_size=96, upscale=True)
        self.assertEqual(resized["annotations"][0]["anchor"]["coordinates"], [4, 4, 22, 11])
        self.assertEqual(resized["annotations"][0]["status"], "hypothesized")
        self.assertEqual(resized["annotations"][1]["anchor"], self.marked["annotations"][1]["anchor"])

    def test_retract_hidden_mark_without_clipping_or_revival(self):
        cropped = self.ok("view", object_id=self.marked["object_id"], rect=[0, 0, 25, 20])
        self.assertEqual(cropped["annotations"][1]["visibility"], "outside_view")
        changed = self.ok("annotate", object_id=cropped["object_id"], updates=[dict(annotation_id="b", status="retracted")])
        self.assertEqual(changed["annotations"][1]["visibility"], "outside_view")
        self.assertEqual(changed["annotations"][1]["status"], "retracted")
        self.assertEqual(changed["annotations"][1]["anchor"], self.marked["annotations"][1]["anchor"])

    def test_invalid_moves_and_requests_refuse_without_touching_parent(self):
        before = Path(self.marked["manifest_path"]).read_bytes()
        cases = [dict(updates=[]), dict(updates=None), dict(updates=[dict(annotation_id="missing", text="x")]),
                 dict(updates=[dict(annotation_id="a", coordinates=[1000, 0, 2000, 0])]),
                 dict(updates=[dict(annotation_id="a", text="x")], annotations=[]), {}]
        for args in cases:
            with self.subTest(args=args):
                self.assertFalse(self.call("annotate", object_id=self.marked["object_id"], **args)["ok"])
        self.assertEqual(Path(self.marked["manifest_path"]).read_bytes(), before)
        self.assertEqual(self.source.read_bytes(), self.source_before)

    def test_same_id_recovers_original_edit_and_conflicting_edit_refuses(self):
        req = dict(workspace=str(self.root / "workspace"), action="annotate", request_id="original-sparse-edit",
                   object_id=self.marked["object_id"], updates=[dict(annotation_id="a", text="one")])
        first = engine.execute(req)
        self.assertTrue(first["ok"], first)
        self.assertEqual(engine.execute(req), first)
        conflict = deepcopy(req)
        conflict["updates"][0]["text"] = "different"
        self.assertEqual(engine.execute(conflict)["error"]["code"], "REQUEST_CONFLICT")

    def test_replacement_clear_remains_supported(self):
        cleared = self.ok("annotate", object_id=self.marked["object_id"], annotations=[])
        self.assertEqual(cleared["annotations"], [])
        self.assertEqual(cleared["annotation_edit_mode"], "replace")

    def test_frequency_move_keeps_full_complex_export(self):
        fft = self.ok("fft", object_id=self.frame["object_id"], rect=[0, 0, 40, 20])
        original = Path(fft["array_path"]).read_bytes()
        marked = self.ok("annotate", object_id=fft["object_id"], annotations=[
            dict(annotation_id="peak", kind="point", coordinates=[.1, .1], status="hypothesized",
                 coordinate_space="frequency_cycles_per_pixel", source_object_id=fft["object_id"])])
        updated = self.ok("annotate", object_id=marked["object_id"], updates=[dict(annotation_id="peak", coordinates=[.15, .05])])
        self.assertEqual(updated["annotations"][0]["anchor"]["source_object_id"], fft["object_id"])
        destination = self.root / "export"
        self.ok("export", object_id=updated["object_id"], output_dir=str(destination))
        self.assertEqual((destination / "data.npy").read_bytes(), original)
        self.assertEqual(self.source.read_bytes(), self.source_before)


if __name__ == "__main__":
    unittest.main()
