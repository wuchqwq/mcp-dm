"""Strict 2D selection and native-crop ownership regressions; synthetic only.

These tests do not launch DM. Fake-DM evidence is not real-host acceptance.
"""
import copy
import types
import unittest
from unittest import mock

import numpy as np

from test_analysis import FakeImage, backend_for, bridge


class StrictROIContractTests(unittest.TestCase):
    def setUp(self):
        self.image = FakeImage(np.arange(80, dtype=np.float32).reshape(8, 10))
        self.backend = backend_for(self.image)

    def calls(self, rect):
        return (
            ("stats", lambda: self.backend.stats(1, rect)),
            ("fft", lambda: self.backend.fft(1, rect, 4)),
            ("crop", lambda: self.backend.crop(1, rect, "requested")),
        )

    def test_completely_disjoint_and_partially_outside_requests_fail(self):
        bad = ([100, 100, 110, 110], [9, 7, 11, 9], [-1, 0, 2, 2],
               [0, -1, 2, 2], [0, 0, 11, 8], [0, 0, 10, 9])
        for rect in bad:
            for name, call in self.calls(rect):
                with self.subTest(tool=name, rect=rect):
                    with self.assertRaisesRegex(ValueError, "OUT_OF_BOUNDS"):
                        call()
        self.assertEqual(len(self.backend.DM.images), 1)
        self.assertEqual(self.backend.DM.scripts, [])
        np.testing.assert_array_equal(self.image.array, np.arange(80).reshape(8, 10))
        self.assertEqual(self.image.origins, [2.0, 3.0])

    def test_empty_inverted_malformed_and_false_are_not_full_frame(self):
        bad = ([], False, 0, "", {}, [0, 0, 0, 1], [0, 0, 1, 0],
               [4, 2, 3, 5], [0, 0, 3], [0, 0, 2, 2, 7], "0022")
        for rect in bad:
            for name, call in self.calls(rect):
                with self.subTest(tool=name, rect=rect):
                    with self.assertRaises(ValueError):
                        call()
        self.assertEqual(self.backend.DM.scripts, [])

    def test_boolean_float_string_and_nonfinite_coordinates_are_rejected(self):
        bad = ([False, 0, 2, 2], [0, True, 2, 2], [np.bool_(False), 0, 2, 2],
               [0.0, 0, 2, 2], [0, 0, 2.6, 2], ["0", 0, 2, 2],
               [float('nan'), 0, 2, 2], [0, 0, float('inf'), 2])
        for rect in bad:
            for name, call in self.calls(rect):
                with self.subTest(tool=name, rect=rect):
                    with self.assertRaises(ValueError):
                        call()
        self.assertEqual(self.backend.DM.scripts, [])

    def test_omitted_selection_is_full_frame_for_stats_and_fft_only(self):
        for result in (self.backend.stats(1, None), self.backend.fft(1, None, 4)):
            self.assertIsNone(result['requested_rect'])
            self.assertEqual(result['effective_rect'], [0, 0, 10, 8])
            self.assertEqual(result['rect'], [0, 0, 10, 8])
            self.assertEqual(result['shape'], [8, 10])
        with self.assertRaises(ValueError):
            self.backend.crop(1, None, 'no_implicit_full_crop')
        self.assertEqual(self.backend.DM.scripts, [])

    def test_positive_single_pixel_and_edges_preserve_exact_bounds(self):
        for rect in ([9, 7, 10, 8], [0, 0, 10, 8], [1, 2, 6, 7]):
            original = list(rect)
            for name, call in self.calls(rect):
                with self.subTest(tool=name, rect=rect):
                    result = call()
                    self.assertEqual(result['requested_rect'], original)
                    self.assertEqual(result['effective_rect'], original)
                    self.assertEqual(rect, original)
        one = self.backend.stats(1, [9, 7, 10, 8])
        self.assertEqual(one['count'], 1)
        self.assertEqual(one['mean'], 79.0)
        # Independent hand enumeration for a non-square selected patch.
        sub = self.backend.stats(1, [1, 2, 4, 4])
        self.assertEqual(sub['count'], 6)
        self.assertEqual(sub['mean'], sum([21, 22, 23, 31, 32, 33]) / 6.0)

    def test_failure_preserves_original_request(self):
        rect = [100, 100, 110, 110]
        for name, call in self.calls(rect):
            with self.subTest(tool=name):
                with self.assertRaises(ValueError):
                    call()
                self.assertEqual(rect, [100, 100, 110, 110])

    def test_invalid_fft_never_reaches_transform(self):
        with mock.patch.object(bridge.np.fft, 'fft2', side_effect=AssertionError('must not transform')) as fft:
            with self.assertRaisesRegex(ValueError, 'OUT_OF_BOUNDS'):
                self.backend.fft(1, [100, 100, 110, 110], 4)
            fft.assert_not_called()

    def test_invalid_crop_does_not_read_pixels_or_execute_script(self):
        with mock.patch.object(self.image, 'GetNumArray', side_effect=AssertionError('must not read')):
            with self.assertRaisesRegex(ValueError, 'OUT_OF_BOUNDS'):
                self.backend.crop(1, [100, 100, 110, 110], 'no_side_effect')
        self.assertEqual(self.backend.DM.scripts, [])
        self.assertEqual(len(self.backend.DM.images), 1)

    def test_native_integer_types_are_accepted_without_rounding(self):
        rect = [np.int64(1), np.int32(2), np.int64(4), np.int32(4)]
        self.assertEqual(bridge._rect_bounds((8, 10), rect), [1, 2, 4, 4])

    def test_dispatcher_does_not_bypass_validation(self):
        dispatcher = bridge.Dispatcher(self.backend)
        for op in ('stats', 'fft', 'crop'):
            with self.subTest(op=op):
                with self.assertRaisesRegex(ValueError, 'OUT_OF_BOUNDS'):
                    dispatcher.handle({'op': op, 'args': {'image_id': 1, 'rect': [100, 100, 110, 110]}})
        self.assertEqual(self.backend.DM.scripts, [])

    def test_mock_backend_rejects_same_invalid_rectangles(self):
        backend = bridge.MockBackend()
        initial = copy.deepcopy(backend._images)
        for rect in ([10000, 10000, 10010, 10010], [-1, 0, 2, 2], [], [False, 0, 2, 2], [0.0, 0, 2, 2]):
            for op in ('stats', 'fft', 'crop'):
                with self.subTest(op=op, rect=rect):
                    args = {'image_id': 1001, 'rect': rect}
                    with self.assertRaises(ValueError):
                        bridge.Dispatcher(backend).handle({'op': op, 'args': args})
        self.assertEqual(backend._images, initial)

    def test_mock_result_reports_original_and_effective_bounds(self):
        backend = bridge.MockBackend()
        rect = [1, 2, 4, 5]
        for op in ('stats', 'fft', 'crop'):
            result = bridge.Dispatcher(backend).handle({'op': op, 'args': {'image_id': 1001, 'rect': rect}})
            self.assertEqual(result['requested_rect'], rect)
            self.assertEqual(result['effective_rect'], rect)


class CropOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.image = FakeImage(np.arange(80, dtype=np.float32).reshape(8, 10), sx=-0.2, sy=0.5)
        self.backend = backend_for(self.image)
        self.rect = [2, 1, 5, 3]
        self.before_pixels = self.image.array.copy()

    def assert_source_unchanged(self):
        np.testing.assert_array_equal(self.image.array, self.before_pixels)
        self.assertEqual(self.image.origins, [2.0, 3.0])
        self.assertEqual(self.image.scales, [-0.2, 0.5])

    def test_success_uses_private_token_then_restores_display_name(self):
        result = self.backend.crop(1, self.rect, 'wanted')
        created = self.backend.DM.images[-1]
        self.assertEqual(created.name, 'wanted')
        self.assertEqual(result['new_image']['id'], created.image_id)
        self.assertEqual(result['requested_rect'], self.rect)
        self.assertEqual(result['effective_rect'], self.rect)
        token = result['result_identity']['operation_token']
        self.assertTrue(token.startswith('dm_mcp_crop_'))
        self.assertIn('SetName(dst, "%s")' % token, self.backend.DM.scripts[0])
        self.assertNotIn('SetName(dst, "wanted")', self.backend.DM.scripts[0])
        np.testing.assert_array_equal(created.array, [[12, 13, 14], [22, 23, 24]])
        np.testing.assert_allclose(created.origins, [1.6, 3.5])
        self.assertFalse(np.shares_memory(created.array, self.image.array))
        self.assert_source_unchanged()

    def test_no_result_fails_instead_of_claiming_latest_image(self):
        self.backend.DM.ExecuteScriptString = lambda script: None
        with self.assertRaisesRegex(RuntimeError, 'CROP_RESULT_UNVERIFIED'):
            self.backend.crop(1, self.rect, 'wanted')
        self.assertEqual(len(self.backend.DM.images), 1)
        self.assert_source_unchanged()

    def test_unrelated_same_name_and_shape_are_never_recalibrated(self):
        unrelated = [FakeImage(np.zeros((2, 3)), image_id=i, name='wanted') for i in (20, 21)]
        def only_unrelated(script):
            self.backend.DM.images.extend(unrelated)
        self.backend.DM.ExecuteScriptString = only_unrelated
        with self.assertRaisesRegex(RuntimeError, 'CROP_RESULT_UNVERIFIED'):
            self.backend.crop(1, self.rect, 'wanted')
        for image in unrelated:
            self.assertEqual(image.name, 'wanted')
            self.assertEqual(image.origins, [2.0, 3.0])
            np.testing.assert_array_equal(image.array, np.zeros((2, 3)))
        self.assert_source_unchanged()

    def test_valid_result_is_not_replaced_by_a_later_unrelated_image(self):
        execute = self.backend.DM.ExecuteScriptString
        unrelated = FakeImage(np.zeros((2, 3)), image_id=90, name='wanted')
        def with_extra(script):
            execute(script)
            self.backend.DM.images.append(unrelated)
        self.backend.DM.ExecuteScriptString = with_extra
        result = self.backend.crop(1, self.rect, 'wanted')
        self.assertEqual(result['new_image']['id'], 2)
        self.assertEqual(unrelated.origins, [2.0, 3.0])
        self.assertEqual(unrelated.name, 'wanted')
        self.assert_source_unchanged()

    def test_duplicate_operation_tokens_fail_before_calibration(self):
        execute = self.backend.DM.ExecuteScriptString
        def duplicate(script):
            execute(script)
            created = self.backend.DM.images[-1]
            self.backend.DM.images.append(FakeImage(created.array.copy(), image_id=77, name=created.name))
        self.backend.DM.ExecuteScriptString = duplicate
        with self.assertRaisesRegex(RuntimeError, 'CROP_RESULT_UNVERIFIED'):
            self.backend.crop(1, self.rect, 'wanted')
        for image in self.backend.DM.images:
            self.assertEqual(image.origins, [2.0, 3.0])
        self.assert_source_unchanged()

    def test_existing_image_with_matching_token_is_not_a_new_result(self):
        token = 'dm_mcp_crop_' + 'a' * 32
        existing = FakeImage(np.zeros((2, 3)), image_id=88, name=token)
        self.backend.DM.images.append(existing)
        self.backend.DM.ExecuteScriptString = lambda script: None
        with mock.patch.object(bridge.uuid, 'uuid4', return_value=types.SimpleNamespace(hex='a' * 32)):
            with self.assertRaisesRegex(RuntimeError, 'CROP_RESULT_UNVERIFIED'):
                self.backend.crop(1, self.rect, 'wanted')
        self.assertEqual(existing.name, token)
        self.assertEqual(existing.origins, [2.0, 3.0])
        self.assert_source_unchanged()

    def test_wrong_sized_token_result_fails_before_calibration_or_rename(self):
        execute = self.backend.DM.ExecuteScriptString
        def wrong_size(script):
            execute(script)
            self.backend.DM.images[-1].array = np.zeros((1, 1))
        self.backend.DM.ExecuteScriptString = wrong_size
        with self.assertRaises(RuntimeError):
            self.backend.crop(1, self.rect, 'wanted')
        created = self.backend.DM.images[-1]
        self.assertTrue(created.name.startswith('dm_mcp_crop_'))
        self.assertEqual(created.origins, [2.0, 3.0])
        self.assert_source_unchanged()

    def test_each_successful_crop_has_a_distinct_operation_token(self):
        first = self.backend.crop(1, self.rect, 'same_name')
        second = self.backend.crop(1, self.rect, 'same_name')
        self.assertNotEqual(first['result_identity']['operation_token'], second['result_identity']['operation_token'])
        self.assertNotEqual(first['new_image']['id'], second['new_image']['id'])
        self.assertEqual(first['new_image']['name'], second['new_image']['name'])
        self.assert_source_unchanged()


if __name__ == '__main__':
    unittest.main()
