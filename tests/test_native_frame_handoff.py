"""Independent saved-metadata checks only; no DM, vendor ABI or live-source proof."""
import copy
import json
from pathlib import Path
import subprocess
import struct
import unittest

from tools.verify_native_region import validate_frame_payload, verify_frame_ancestry, verify_frame_samples


ROOT = Path(__file__).resolve().parents[1]


class NativeFrameHandoff(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        module = (ROOT / 'tests/fixtures/native-frame-handoff.mjs').as_uri()
        code = "import {frameHandoffFixture} from MODULE;console.log(JSON.stringify(frameHandoffFixture({unknownUnits:true})));".replace('MODULE', json.dumps(module))
        cls.fixture = json.loads(subprocess.check_output(['node', '--input-type=module', '-e', code], cwd=str(ROOT)))

    def value(self):
        frame = copy.deepcopy(self.fixture)
        return {'source_image_id': 77, 'source': frame['result']['image'],
                'source_provenance': frame['provenance'], 'frame_ancestry': frame['ancestry']}

    def test_native_uint16_to_float32_metadata_keeps_signed_raw_axes_and_unknown_units(self):
        value = self.value()
        original = copy.deepcopy(value)
        ancestry = verify_frame_ancestry(value)
        self.assertEqual(ancestry['normalized_args'], [31, 1])
        self.assertEqual(ancestry['result']['source']['dtype'], 'uint16')
        self.assertEqual(ancestry['result']['image']['dtype'], 'float32')
        self.assertEqual(ancestry['result']['frame_axis']['calibrated_value'], .75)
        self.assertIsNone(ancestry['result']['frame_axis']['unit'])
        self.assertFalse(ancestry['result']['frame_axis']['usable'])
        self.assertEqual(ancestry['result']['image']['calibration'][0]['scale'], -.25)
        self.assertFalse(ancestry['result']['image']['calibration_complete'])
        self.assertEqual(value, original)

    def test_unavailable_raw_sequence_coordinate_remains_null(self):
        value = self.value()
        result = value['frame_ancestry']['result']
        axis = result['source']['calibration'][2]
        axis.update(origin=None, scale=None, calibrated_value_at_pixel_zero=None, issue='invalid_calibration_and_unknown_units')
        result['frame_axis']['calibrated_value'] = None
        verify_frame_ancestry(value)
        result['frame_axis']['calibrated_value'] = 0
        with self.assertRaises(ValueError):
            verify_frame_ancestry(value)

    def test_legacy_missing_field_is_unknown_without_backfilling(self):
        value = {'source_image_id': 77, 'source_provenance': None}
        self.assertIsNone(verify_frame_ancestry(value))
        self.assertNotIn('frame_ancestry', value)
        with self.assertRaises(ValueError):
            verify_frame_ancestry({'source_provenance': self.fixture['provenance']})

    def test_single_parent_processing_preserves_identity_without_forging_current_roi_mapping(self):
        value = self.value()
        value['source_image_id'] = value['source']['id'] = 88
        value['source_provenance'] = {'operation': 'CROP', 'request_id': 'later-crop', 'source_image_ids': [77], 'semantics': 'explicit native crop'}
        frame = verify_frame_ancestry(value)
        self.assertEqual(frame['result']['image']['id'], 77)
        self.assertNotIn('source_offset_xy', frame)
        value['source_provenance']['request_id'] = frame['request_id']
        with self.assertRaisesRegex(ValueError, 'distinct single-parent'):
            verify_frame_ancestry(value)
        value['source_provenance']['request_id'] = 'later-crop'
        value['source_provenance']['operation'] = 'BINARY'
        value['source_provenance']['source_image_ids'] = [77, 99]
        with self.assertRaises(ValueError):
            verify_frame_ancestry(value)

    def test_invalid_typed_frame_metadata_cannot_become_pass_from_self_consistent_hashes(self):
        def changed(path, replacement):
            def mutate(value):
                current = value['frame_ancestry']['result']
                for key in path[:-1]:
                    current = current[key]
                current[path[-1]] = replacement
            return mutate
        mutations = [changed(['source', 'data_type_code'], 11), changed(['source', 'dtype'], 'int16'),
                     changed(['source', 'ndim'], 2), changed(['source', 'pixels'], 1),
                     changed(['source', 'packing_style'], 0), changed(['source', 'shape'], [3, 9, 7]),
                     changed(['source', 'calibration', 2, 'numpy_axis'], 2),
                     changed(['source', 'calibration', 0, 'unit'], 'nm'),
                     changed(['image', 'data_type_code'], 10), changed(['image', 'dtype'], 'uint16'),
                     changed(['image', 'calibration', 0, 'scale'], 1), changed(['image_id'], 31),
                     changed(['frame_index'], 3), changed(['frame_axis', 'count'], 4),
                     changed(['frame_axis', 'role'], 'time'), changed(['frame_axis', 'index_base'], 1),
                     changed(['frame_axis', 'calibrated_value'], 1.5), changed(['frame_axis', 'unit'], 'nm'),
                     changed(['dtype_conversion', 'lossless_values'], False), changed(['output_bytes'], 126),
                     changed(['validation_peak_new_image_bytes'], 1), changed(['source_write_requested'], True),
                     changed(['candidate_probe'], True), changed(['qualification'], 'NOT_QUALIFIED'),
                     changed(['intensity_calibration_applied'], True), changed(['intensity_calibration_output', 'scale'], 2)]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                value = self.value()
                mutate(value)
                with self.assertRaises(ValueError):
                    verify_frame_ancestry(value)

    def test_request_parent_output_and_mixed_ancestry_fail(self):
        for mutate in [lambda v: v['frame_ancestry'].update(status='unresolved_lineage'),
                       lambda v: v['frame_ancestry'].update(request_id='bad id'),
                       lambda v: v['frame_ancestry'].update(normalized_args=[31, True]),
                       lambda v: v['frame_ancestry'].update(normalized_args=[32, 1]),
                       lambda v: v['source_provenance'].update(request_id='another-request'),
                       lambda v: v['source_provenance'].update(source_image_ids=[32]),
                       lambda v: v.update(source_image_id=78),
                       lambda v: v['frame_ancestry']['result'].update(retention={})]:
            value = self.value()
            mutate(value)
            with self.assertRaises(ValueError):
                verify_frame_ancestry(value)

    def test_bounded_selected_plane_rejected_before_any_external_array_allocation(self):
        frame = copy.deepcopy(self.fixture['result'])
        frame['source'].update(shape=[3, 2048, 2048], dm_dimensions=[2048, 2048, 3], pixels=3*2048*2048)
        with self.assertRaises(ValueError):
            validate_frame_payload(frame, [31, 1])

    def test_direct_frame_pixels_require_exact_unsigned_values_but_derived_data_keep_their_own_semantics(self):
        value = self.value()
        value['dtype'] = 'float32'
        verify_frame_samples(struct.pack('<4f', 0, 32767, 32768, 65535), value)
        for number in (-1, -32768, .5, 65536, float('inf'), float('nan')):
            with self.subTest(number=number), self.assertRaises(ValueError):
                verify_frame_samples(struct.pack('<f', number), value)
        value['source_provenance']['operation'] = 'UNARY'
        verify_frame_samples(struct.pack('<2f', -1, .5), value)


if __name__ == '__main__':
    unittest.main()
