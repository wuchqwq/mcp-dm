"""Bounded, typed metadata path regressions. Synthetic/fake-DM only."""
import unittest
from unittest import mock

import numpy as np

from test_analysis import FakeImage, FakeTagGroup, backend_for, bridge


class MetadataPathTests(unittest.TestCase):
    def setUp(self):
        self.image = FakeImage(np.arange(15).reshape(3, 5))
        self.backend = backend_for(self.image)

    def get(self, prefix=None, depth=8):
        return self.backend.metadata(1, depth, prefix)

    def reason(self, result, reason):
        self.assertTrue(any(i['reason'] == reason for i in result['issues']), result)

    def test_root_remains_complete_with_explicit_status(self):
        result = self.get()
        self.assertEqual(result['path_status'], 'found')
        self.assertEqual(result['prefix'], '')
        self.assertTrue(result['complete'])
        self.assertEqual(result['tags']['Instrument']['Voltage'], 200000)
        self.assertEqual(result['complete_scope'], 'requested subtree')

    def test_deep_prefix_is_resolved_before_depth_limit(self):
        self.image.tags = FakeTagGroup({'A': FakeTagGroup({'B': FakeTagGroup({
            'C': FakeTagGroup({'Voltage': 300000})})})})
        result = self.get('A/B/C', 0)
        self.assertEqual(result['tags'], {'Voltage': 300000})
        self.assertEqual(result['prefix'], '/A/B/C')
        self.assertTrue(result['complete'], result)

    def test_depth_is_relative_to_selected_subtree(self):
        result = self.get('/List/2', 0)
        self.assertEqual(result['tags'], {'value': 3})
        self.assertTrue(result['complete'])
        self.image.tags = FakeTagGroup({'Target': FakeTagGroup({
            'plain': 1, 'Nested': FakeTagGroup({'value': 2})})})
        result = self.get('/Target', 0)
        self.assertEqual(result['path_status'], 'found')
        self.assertFalse(result['complete'])
        self.assertEqual(result['tags']['plain'], 1)
        self.reason(result, 'depth_limit')
        self.assertTrue(self.get('/Target', 1)['complete'])

    def test_sibling_values_do_not_spend_subtree_budget(self):
        self.image.tags = FakeTagGroup({
            'Noise': FakeTagGroup(dict(('n%d' % i, i) for i in range(100))),
            'Target': FakeTagGroup({'answer': 42})})
        with mock.patch.object(bridge, 'MAX_TAG_NODES', 2), mock.patch.object(
                self.image.tags, 'GetTagTypeLength', wraps=self.image.tags.GetTagTypeLength) as type_lengths:
            result = self.get('/Target', 0)
        self.assertTrue(result['complete'], result)
        self.assertEqual(result['tags'], {'answer': 42})
        self.assertEqual(self.image.tags.group_reads, [1])
        # A group has an empty descriptor, so GetTagType itself is never called.
        # Observe the actual introspection entry point, not a nonexistent scalar read.
        type_lengths.assert_called_once_with(1)
        self.assertNotIn('/Noise', result['tag_types'])

    def test_lookup_budget_exhaustion_is_not_absence(self):
        self.image.tags = FakeTagGroup(dict(('n%d' % i, i) for i in range(8)))
        with mock.patch.object(bridge, 'MAX_TAG_NODES', 2):
            result = self.get('/n7')
        self.assertEqual(result['path_status'], 'unavailable')
        self.assertFalse(result['complete'])
        self.reason(result, 'lookup_budget')
        self.assertNotIn('not found', result.get('error', ''))
        self.assertEqual(self.image.tags.reader_calls, [])

    def test_unknown_sibling_payload_is_not_decoded(self):
        self.image.tags = FakeTagGroup({'opaque': object(), 'Target': 7})
        result = self.get('/Target')
        self.assertEqual(result['tags'], 7)
        self.assertTrue(result['complete'])
        self.assertEqual(self.image.tags.reader_calls, [(1, 'GetIndexedTagAsLong')])

    def test_missing_path_retains_explicit_diagnostics(self):
        result = self.get('/Instrument/Missing')
        self.assertEqual(result['path_status'], 'not_found')
        self.assertIsNone(result['tags'])
        self.assertFalse(result['complete'])
        self.reason(result, 'path_not_found')
        self.assertIn('limits', result)
        self.assertIn('tag_types', result)

    def test_list_path_uses_original_zero_based_indices(self):
        result = self.get('/List/2/value')
        self.assertEqual(result['tags'], 3)
        self.assertTrue(result['complete'])
        for suffix in ('-1', '01', '-', '3', '1.0', '\u0661'):
            with self.subTest(suffix=suffix):
                failed = self.get('/List/' + suffix)
                self.assertEqual(failed['path_status'], 'not_found')
                self.assertFalse(failed['complete'])

    def test_json_pointer_escapes_and_numeric_group_labels(self):
        self.image.tags = FakeTagGroup({'a/b~c': FakeTagGroup({'0': 19}), '~1': 23})
        result = self.get('/a~1b~0c/0')
        self.assertEqual(result['tags'], 19)
        self.assertEqual(result['prefix'], '/a~1b~0c/0')
        self.assertEqual(self.get('/~01')['tags'], 23)

    def test_literal_empty_names_are_not_stripped(self):
        self.image.tags = FakeTagGroup({'': 7, 'group': FakeTagGroup({'': 11})})
        self.assertEqual(self.get('/')['tags'], 7)
        self.assertEqual(self.get('/group/')['tags'], 11)
        self.assertIn('group', self.get('')['tags'])

    def test_whitespace_in_labels_is_significant(self):
        self.image.tags = FakeTagGroup({' spaced ': 13})
        self.assertEqual(self.get(' spaced ')['tags'], 13)
        self.assertEqual(self.get('/spaced')['path_status'], 'not_found')

    def test_legacy_byte_labels_are_decoded_without_native_path_getters(self):
        raw_label = b'Emission Current (\xb5A)'
        self.image.tags = FakeTagGroup({raw_label: 0.125})
        result = self.get('/Emission Current (\u00b5A)')
        self.assertTrue(result['complete'])
        self.assertEqual(result['tags'], 0.125)
        self.assertEqual(result['tag_types'][result['prefix']]['label_encoding'], 'cp1252')
        self.assertEqual(self.image.tags.group_reads, [])

    def test_invalid_prefix_is_rejected_before_resolving_image(self):
        for prefix in ('/a~2b', '/trailing~', [], False, 1, '/x' * 65):
            with self.subTest(prefix=prefix), mock.patch.object(self.backend, '_resolve') as resolve:
                with self.assertRaises(ValueError):
                    self.get(prefix)
                resolve.assert_not_called()

    def test_prefix_byte_limit_precedes_host_access(self):
        with mock.patch.object(bridge, 'MAX_TAG_VALUE_BYTES', 4), mock.patch.object(self.backend, '_resolve') as resolve:
            with self.assertRaises(ValueError):
                self.get('/12345')
            resolve.assert_not_called()

    def test_dispatcher_forwards_prefix_without_second_filter(self):
        result = bridge.Dispatcher(self.backend).handle({
            'op': 'metadata', 'args': {'image_id': 1, 'prefix': '/List/2', 'max_depth': 0}})
        self.assertEqual(result['tags'], {'value': 3})
        self.assertTrue(result['complete'])

    def test_known_scalar_ancestor_is_not_probed_as_group(self):
        self.image.tags = FakeTagGroup({'scalar': 5})
        result = self.get('/scalar/child')
        self.assertEqual(result['path_status'], 'not_found')
        self.reason(result, 'not_a_container')
        self.assertEqual(self.image.tags.group_reads, [])

    def test_unsupported_leaf_exists_but_is_not_complete(self):
        self.image.tags = FakeTagGroup({'opaque': object()})
        result = self.get('/opaque')
        self.assertEqual(result['path_status'], 'found')
        self.assertFalse(result['complete'])
        self.reason(result, 'unsupported_dm_type')
        self.assertEqual(self.image.tags.group_reads, [])

    def test_unsupported_ancestor_leaves_resolution_unknown(self):
        self.image.tags = FakeTagGroup({'opaque': object()})
        result = self.get('/opaque/child')
        self.assertEqual(result['path_status'], 'unavailable')
        self.reason(result, 'unsupported_dm_type')
        self.assertNotIn('not found', result.get('error', ''))

    def test_failed_type_introspection_never_guesses_group_getter(self):
        class BrokenTypes(FakeTagGroup):
            def GetTagTypeLength(self, index):
                raise RuntimeError('synthetic introspection failure')
        self.image.tags = BrokenTypes({'Group': FakeTagGroup({'v': 1})})
        for prefix in (None, '/Group'):
            result = self.get(prefix)
            self.assertFalse(result['complete'])
            self.reason(result, 'type_read_error')
            self.assertEqual(self.image.tags.group_reads, [])
            self.assertEqual(self.image.tags.reader_calls, [])

    def test_oversized_type_descriptor_never_uses_partial_descriptor(self):
        class OversizedTypes(FakeTagGroup):
            def GetTagTypeLength(self, index):
                return 65
        self.image.tags = OversizedTypes({'Group': FakeTagGroup({})})
        result = self.get('/Group')
        self.assertFalse(result['complete'])
        self.reason(result, 'type_descriptor_limit')
        self.assertEqual(self.image.tags.type_calls, [])
        self.assertEqual(self.image.tags.group_reads, [])

    def test_size_failure_stops_before_native_value_getters(self):
        class BrokenSize(FakeTagGroup):
            def GetTagSize(self, index):
                raise RuntimeError('synthetic size failure')
        self.image.tags = BrokenSize({'Group': FakeTagGroup({})})
        result = self.get('/Group')
        self.assertFalse(result['complete'])
        self.reason(result, 'tag_size_read_error')
        self.assertEqual(self.image.tags.group_reads, [])

    def test_failed_label_lookup_cannot_prove_absence(self):
        class BrokenLabels(FakeTagGroup):
            def GetTagLabel(self, index):
                raise RuntimeError('synthetic label failure')
        self.image.tags = BrokenLabels({'target': 1})
        result = self.get('/missing')
        self.assertEqual(result['path_status'], 'unavailable')
        self.reason(result, 'label_read_error')
        self.assertEqual(self.image.tags.reader_calls, [])

    def test_duplicate_labels_do_not_select_first_candidate(self):
        class DuplicateLabels(FakeTagGroup):
            def GetTagLabel(self, index):
                return 'target'
        self.image.tags = DuplicateLabels({'first': 1, 'second': 2})
        result = self.get('/target')
        self.assertEqual(result['path_status'], 'unavailable')
        self.reason(result, 'duplicate_label')
        self.assertEqual(self.image.tags.reader_calls, [])

    def test_leaf_read_error_keeps_existence_and_failure_separate(self):
        class BrokenValue(FakeTagGroup):
            def GetIndexedTagAsLong(self, index):
                raise RuntimeError('synthetic value failure')
        self.image.tags = BrokenValue({'value': 7})
        result = self.get('/value')
        self.assertEqual(result['path_status'], 'found')
        self.assertFalse(result['complete'])
        self.reason(result, 'read_error')
        self.assertEqual(result['tags'], {'__unavailable__': 'read_error'})

    def test_unreadable_root_reports_unavailable(self):
        with mock.patch.object(self.image, 'GetTagGroup', side_effect=RuntimeError('synthetic root failure')):
            result = self.get('/Instrument')
        self.assertEqual(result['path_status'], 'unavailable')
        self.assertFalse(result['complete'])
        self.reason(result, 'read_error')

    def test_metadata_never_requests_pixels(self):
        with mock.patch.object(self.image, 'GetNumArray', side_effect=AssertionError('no pixels')):
            result = self.get('/Instrument')
        self.assertTrue(result['complete'])
        np.testing.assert_array_equal(self.image.array, np.arange(15).reshape(3, 5))

    def test_each_request_resets_lookup_traversal_and_issues(self):
        self.assertFalse(self.get('/missing')['complete'])
        result = self.get('/Instrument/Voltage')
        self.assertTrue(result['complete'])
        self.assertEqual(result['tags'], 200000)
        self.assertEqual(result['issues'], [])
        self.assertNotIn('/missing', result['tag_types'])

    def test_large_integer_precision_survives_prefix_selection(self):
        self.image.tags = FakeTagGroup({'large': np.int64(2 ** 63 - 1)})
        result = self.get('/large')
        self.assertEqual(result['tags'], {'__type__': 'integer', 'decimal': '9223372036854775807'})
        self.assertTrue(result['complete'])


    def test_invalid_native_root_is_not_complete_even_without_prefix(self):
        for root in (None, {}, 7, object()):
            for prefix in (None, '/Instrument'):
                with self.subTest(root=type(root).__name__, prefix=prefix), mock.patch.object(
                        self.image, 'GetTagGroup', return_value=root):
                    result = self.get(prefix)
                    self.assertEqual(result['path_status'], 'unavailable')
                    self.assertFalse(result['complete'])
                    self.reason(result, 'read_error')

    def test_empty_native_root_is_valid_and_complete(self):
        self.image.tags = FakeTagGroup({})
        result = self.get()
        self.assertEqual(result['path_status'], 'found')
        self.assertTrue(result['complete'])
        self.assertEqual(result['tags'], {})

    def test_invalid_sizes_stop_before_native_value_getters(self):
        for size in (None, -1, float('nan'), float('inf'), True, '4'):
            with self.subTest(size=size):
                self.image.tags = FakeTagGroup({'value': 7})
                with mock.patch.object(self.image.tags, 'GetTagSize', return_value=size):
                    result = self.get('/value')
                self.assertEqual(result['path_status'], 'found')
                self.assertFalse(result['complete'])
                self.reason(result, 'tag_size_read_error')
                self.assertEqual(self.image.tags.reader_calls, [])
                self.assertEqual(self.image.tags.group_reads, [])


class MockMetadataPathTests(unittest.TestCase):
    def setUp(self):
        self.dispatcher = bridge.Dispatcher(bridge.MockBackend())

    def get(self, prefix=None, depth=8):
        return self.dispatcher.handle({'op': 'metadata', 'args': {
            'image_id': 1000, 'prefix': prefix, 'max_depth': depth}})

    def test_mock_path_and_root_are_explicitly_synthetic(self):
        for prefix in ('Acquisition/Instrument', '/Acquisition/Instrument'):
            result = self.get(prefix, 0)
            self.assertEqual(result['tags']['Name'], 'MOCK-TEM')
            self.assertEqual(result['path_status'], 'found')
            self.assertTrue(result['complete'])
            self.assertTrue(result['synthetic'])
        self.assertIn('Acquisition', self.get()['tags'])

    def test_mock_missing_path_is_not_complete(self):
        result = self.get('/Missing')
        self.assertEqual(result['path_status'], 'not_found')
        self.assertFalse(result['complete'])
        self.assertIsNone(result['tags'])

    def test_mock_depth_applies_to_selected_subtree(self):
        result = self.get('/Acquisition', 0)
        self.assertFalse(result['complete'])
        self.assertEqual(result['tags']['Instrument'], {'__unavailable__': 'depth_limit'})
        self.assertEqual(result['tags']['DwellTime_us'], 2.0)

    def test_mock_spectral_fixture_still_reports_validation_boundary(self):
        result = self.dispatcher.handle({'op': 'metadata', 'args': {
            'image_id': 1002, 'prefix': '/SyntheticFixture/experimental_data', 'max_depth': 0}})
        self.assertIs(result['tags'], False)
        self.assertTrue(result['complete'])
        self.assertIn('NOT_TESTED', result['note'])


if __name__ == '__main__':
    unittest.main()
