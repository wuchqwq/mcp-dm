"""Pure annotation edit planning: no DM, image files or numerical processing."""
from copy import deepcopy
import unittest

from tools.image_annotation_updates import AnnotationUpdateError, plan_annotation_updates


def mark(ident="stripe-a", **values):
    item = {"annotation_id": ident, "kind": "arrow", "coordinates": [1, 2, 3, 4],
            "coordinate_space": "rendered_image_pixels", "text": "candidate",
            "status": "hypothesized", "note": "", "color": "cyan", "line_width": 3,
            "arrowhead_size": 6, "arrow_length": 24,
            "arrow_render_coordinates": [2, 3, 3, 4],
            "anchor": {"coordinate_space": "source_pixels", "source_object_id": "a" * 32,
                       "coordinates": [20, 30, 80, 60]}, "visibility": "visible"}
    item.update(values)
    return item


class AnnotationUpdates(unittest.TestCase):
    def setUp(self):
        self.saved = [mark(), mark("other", color="orange", status="user_confirmed")]
        self.original = deepcopy(self.saved)

    def test_text_edit_preserves_other_marks_order_and_status(self):
        result = plan_annotation_updates(self.saved, [{"annotation_id": "stripe-a", "text": "revised"}])
        self.assertEqual(result[0][0]["text"], "revised")
        self.assertEqual(result[0][0]["status"], "hypothesized")
        self.assertEqual(result[1], (self.saved[1], True))
        self.assertEqual(self.saved, self.original)

    def test_coordinate_edit_uses_anchor_not_shortened_png_arrow(self):
        result = plan_annotation_updates(self.saved, [{"annotation_id": "stripe-a", "coordinates": [22, 30, 82, 60]}])
        item, reproject = result[0]
        self.assertFalse(reproject)
        self.assertEqual(item["coordinates"], [22, 30, 82, 60])
        self.assertEqual(item["coordinate_space"], "source_pixels")
        self.assertEqual(item["source_object_id"], "a" * 32)
        self.assertNotIn("arrow_render_coordinates", item)
        self.assertNotIn("anchor", item)
        self.assertEqual(self.saved, self.original)

    def test_frequency_move_keeps_original_spectrum_and_units(self):
        self.saved[0]["anchor"] = {"coordinate_space": "frequency_cycles_per_pixel",
                                    "source_object_id": "b" * 32, "coordinates": [0., 0., .1, -.2]}
        edited, reproject = plan_annotation_updates(self.saved, [{"annotation_id": "stripe-a", "coordinates": [0., 0., .2, -.1]}])[0]
        self.assertEqual(edited["coordinate_space"], "frequency_cycles_per_pixel")
        self.assertEqual(edited["source_object_id"], "b" * 32)
        self.assertFalse(reproject)

    def test_retraction_is_not_deletion(self):
        items = plan_annotation_updates(self.saved, [{"annotation_id": "stripe-a", "status": "retracted"}])
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0][0]["status"], "retracted")
        self.assertEqual(items[0][0]["anchor"], self.saved[0]["anchor"])
        self.assertEqual(self.saved, self.original)

    def test_style_change_does_not_confirm_hypothesis(self):
        item, _ = plan_annotation_updates(self.saved, [{"annotation_id": "stripe-a", "color": "orange", "line_width": 2}])[0]
        self.assertEqual(item["status"], "hypothesized")
        self.assertEqual(item["color"], "orange")

    def test_out_of_view_unmoved_anchor_stays_reprojectable(self):
        self.saved[0]["visibility"] = "outside_view"
        item, project = plan_annotation_updates(self.saved, [{"annotation_id": "stripe-a", "text": "still outside"}])[0]
        self.assertTrue(project)
        self.assertEqual(item["visibility"], "outside_view")

    def test_anonymous_other_marks_are_preserved(self):
        self.saved[1].pop("annotation_id")
        items = plan_annotation_updates(self.saved, [{"annotation_id": "stripe-a", "text": "x"}])
        self.assertEqual(items[1], (self.saved[1], True))

    def test_legacy_cross_panel_mark_retains_only_valid_input_fields(self):
        self.saved[1]["anchor"] = None
        item, reproject = plan_annotation_updates(self.saved, [{"annotation_id": "other", "text": "legacy"}])[1]
        self.assertFalse(reproject)
        self.assertNotIn("anchor", item)
        self.assertNotIn("visibility", item)
        self.assertEqual(item["coordinates"], self.saved[1]["coordinates"])
        self.assertEqual(item["text"], "legacy")

    def test_legacy_pre_cap_arrow_keeps_full_length(self):
        self.saved[1].pop("arrow_length")
        self.saved[1]["anchor"] = None
        item, _ = plan_annotation_updates(self.saved, [{"annotation_id": "stripe-a", "text": "x"}])[1]
        self.assertIsNone(item["arrow_length"])

    def test_moved_pre_cap_arrow_keeps_full_length(self):
        self.saved[0].pop("arrow_length")
        item, _ = plan_annotation_updates(self.saved, [{"annotation_id": "stripe-a", "coordinates": [1, 1, 5, 5]}])[0]
        self.assertIsNone(item["arrow_length"])

    def test_two_edits_keep_saved_order_not_update_order(self):
        items = plan_annotation_updates(self.saved, [{"annotation_id": "other", "text": "b"}, {"annotation_id": "stripe-a", "text": "a"}])
        self.assertEqual([item[0]["annotation_id"] for item in items], ["stripe-a", "other"])
        self.assertEqual([item[0]["text"] for item in items], ["a", "b"])

    def test_output_does_not_alias_saved_input(self):
        items = plan_annotation_updates(self.saved, [{"annotation_id": "stripe-a", "text": "x"}])
        items[1][0]["anchor"]["coordinates"][0] = 999
        self.assertEqual(self.saved, self.original)

    def test_move_list_does_not_alias_update(self):
        edit = {"annotation_id": "stripe-a", "coordinates": [1, 1, 5, 5]}
        items = plan_annotation_updates(self.saved, [edit])
        items[0][0]["coordinates"][0] = 999
        self.assertEqual(edit["coordinates"], [1, 1, 5, 5])

    def test_rejects_missing_unknown_and_malformed_ids(self):
        for ident in (None, "missing", "../bad", "", True):
            with self.subTest(ident=ident), self.assertRaises(AnnotationUpdateError):
                plan_annotation_updates(self.saved, [{"annotation_id": ident, "text": "x"}])

    def test_rejects_duplicate_update_ids(self):
        with self.assertRaises(AnnotationUpdateError):
            plan_annotation_updates(self.saved, [{"annotation_id": "stripe-a", "text": "a"}, {"annotation_id": "stripe-a", "text": "b"}])

    def test_rejects_ambiguous_saved_ids(self):
        with self.assertRaises(AnnotationUpdateError):
            plan_annotation_updates([self.saved[0], deepcopy(self.saved[0])], [{"annotation_id": "stripe-a", "text": "x"}])

    def test_rejects_identity_domain_and_kind_changes(self):
        for key in ("kind", "source_object_id", "coordinate_space", "anchor", "visibility", "array_path"):
            with self.subTest(key=key), self.assertRaises(AnnotationUpdateError):
                plan_annotation_updates(self.saved, [{"annotation_id": "stripe-a", key: "x"}])

    def test_rejects_empty_noop_and_oversized_updates(self):
        for updates in ([], None, {}, [{"annotation_id": "stripe-a"}], [{}] * 101):
            with self.subTest(updates=str(updates)[:40]), self.assertRaises(AnnotationUpdateError):
                plan_annotation_updates(self.saved, updates)

    def test_unanchored_coordinate_edit_is_refused(self):
        self.saved[0]["anchor"] = None
        with self.assertRaises(AnnotationUpdateError):
            plan_annotation_updates(self.saved, [{"annotation_id": "stripe-a", "coordinates": [1, 1, 5, 5]}])

    def test_invalid_later_edit_does_not_change_any_parent(self):
        with self.assertRaises(AnnotationUpdateError):
            plan_annotation_updates(self.saved, [{"annotation_id": "stripe-a", "text": "x"}, {"annotation_id": "missing", "text": "y"}])
        self.assertEqual(self.saved, self.original)


if __name__ == "__main__":
    unittest.main()
