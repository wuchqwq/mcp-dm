"""Scope-boundary regressions. Synthetic inputs; no real DM or user data."""
import builtins
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tracemalloc
import unittest
from unittest import mock

import numpy as np
import test_analysis2d_worker as fixtures

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / 'tools' / 'analysis_worker.py'


def load_worker():
    spec = importlib.util.spec_from_file_location('scope_test_worker', str(WORKER))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def invoke(payload, blocked=()):
    # Import blocking establishes which optional libraries each action needs,
    # even when the full test environment has all dependencies installed.
    code = '''import builtins, io, json, runpy, sys
request, denied, script = json.loads(sys.argv[1]), set(json.loads(sys.argv[2])), sys.argv[3]
original_import = builtins.__import__
def checked(name, *args, **kwargs):
    if name.split('.')[0] in denied:
        raise ImportError('intentionally absent optional dependency: ' + name)
    return original_import(name, *args, **kwargs)
builtins.__import__ = checked
sys.stdin = io.StringIO(json.dumps(request))
runpy.run_path(script, run_name='__main__')
'''
    run = subprocess.run([sys.executable, '-B', '-c', code,
                          json.dumps(payload), json.dumps(list(blocked)), str(WORKER)],
                         text=True, capture_output=True, timeout=90)
    try:
        response = json.loads(run.stdout)
    except Exception:
        raise AssertionError(run.stderr + run.stdout)
    return run, response


@unittest.skipUnless(fixtures.HAS_ANALYSIS_DEPS, 'full report tests need optional analysis dependencies')
class ScopeContracts(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.Analysis2DWorkerTests('test_preview_mapping_overlays_fixed_input_and_display_only_scaling')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.worker = load_worker()
        self.info = self.fixture.read_json(os.path.join(self.fixture.capture, 'input.json'))

    def request(self):
        return {'action': 'analyze', 'capture_dir': self.fixture.capture,
                'result_dir': self.fixture.result, 'operation_id': 'scope-contract',
                'roi': [18, 32, 50, 56], 'top_n': 4,
                'profile': {'start': [18, 44], 'end': [49, 44], 'width': 1}}

    def generate(self):
        run, response = invoke(self.request())
        self.assertEqual(run.returncode, 0, run.stderr + run.stdout)
        self.assertEqual(response['result']['state'], 'succeeded')

    def test_cropped_profile_exports_source_and_local_coordinates(self):
        result = self.worker._profile_result(self.fixture.original, self.info,
                    {'start': [18, 44], 'end': [49, 44], 'width': 1})
        self.assertEqual(result['sampled_coordinates'][0], [18.0, 44.0])
        self.assertEqual(result['sampled_coordinates'][-1], [49.0, 44.0])
        self.assertEqual(result['sampled_coordinates_local'][0], [8.0, 24.0])
        self.assertEqual(result['sampled_coordinates_local'][-1], [39.0, 24.0])
        np.testing.assert_allclose(np.array(result['sampled_coordinates']) -
                                   np.array(result['sampled_coordinates_local']),
                                   np.tile([10, 20], (32, 1)))
        self.assertEqual(result['calibration_coordinate_frame'], 'captured array pixel centers')
        self.assertAlmostEqual(result['distance'][-1], 7.75)

    def test_preview_runs_without_matplotlib(self):
        run, response = invoke({'action': 'preview', 'capture_dir': self.fixture.capture, 'max_side': 32}, ('matplotlib',))
        self.assertEqual(run.returncode, 0, run.stderr + run.stdout)
        self.assertEqual(response['result']['mapping']['preview_shape_yx'], [24, 32])
        self.assertTrue(Path(response['result']['preview_path']).is_file())

    def test_status_runs_without_pillow_or_matplotlib(self):
        run, response = invoke({'action': 'result', 'capture_dir': self.fixture.capture}, ('PIL', 'matplotlib'))
        self.assertEqual(run.returncode, 0, run.stderr + run.stdout)
        self.assertTrue(response['ok'])
        self.assertEqual(response['result']['state'], 'captured')
        run, response = invoke({'action': 'result', 'result_dir': self.fixture.result}, ('PIL', 'matplotlib'))
        self.assertEqual(run.returncode, 0)
        self.assertEqual(response['result']['state'], 'unknown')

    def test_report_missing_dependency_does_not_reserve_output_dir(self):
        run, response = invoke(self.request(), ('matplotlib',))
        self.assertNotEqual(run.returncode, 0)
        self.assertFalse(response['ok'])
        self.assertIn('requirements-analysis.txt', response['error'])
        self.assertFalse(os.path.exists(self.fixture.result))

    def test_preview_missing_dependency_is_actionable(self):
        run, response = invoke({'action': 'preview', 'capture_dir': self.fixture.capture}, ('PIL', 'matplotlib'))
        self.assertNotEqual(run.returncode, 0)
        self.assertIn('requirements-preview.txt', response['error'])

    def test_verification_needs_no_rendering_libraries(self):
        self.generate()
        run, response = invoke({'action': 'verify', 'bundle_dir': self.fixture.result}, ('PIL', 'matplotlib'))
        self.assertEqual(run.returncode, 0, run.stderr + run.stdout)
        self.assertTrue(response['ok'])
        self.assertEqual(response['result']['state'], 'verified')

    def test_verification_failure_exits_nonzero_in_replay_wrapper(self):
        self.generate()
        with open(os.path.join(self.fixture.result, 'stats.json'), 'a', encoding='utf-8') as stream:
            stream.write('\n ')
        run = subprocess.run([sys.executable, os.path.join(self.fixture.result, 'replay.py'), '--verify'],
                             text=True, capture_output=True, timeout=90)
        self.assertNotEqual(run.returncode, 0, run.stdout)
        response = json.loads(run.stdout)
        self.assertFalse(response['ok'])
        self.assertEqual(response['result']['state'], 'failed')
        self.assertIn('checksum', response['error'])

    def test_unresolved_verification_is_not_a_success(self):
        os.makedirs(self.fixture.result)
        self.fixture.write_json(os.path.join(self.fixture.result, 'manifest.json'),
                                {'state': 'running', 'operation_id': 'incomplete'})
        run, response = invoke({'action': 'verify', 'bundle_dir': self.fixture.result})
        self.assertNotEqual(run.returncode, 0)
        self.assertFalse(response['ok'])
        self.assertEqual(response['result']['state'], 'unknown')

    def test_preview_workspace_bounded_by_display_not_full_source(self):
        self.worker._require_preview()  # Exclude one-time Pillow module setup.
        source = np.ones((2048, 2048), dtype=np.uint8)
        info = {'source_rect_xyxy': [0, 0, 2048, 2048], 'source_shape_yx': [2048, 2048]}
        tracemalloc.start()
        try:
            image, mapping = self.worker._preview_image(source, info, 64)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertEqual(image.size, (64, 64))
        self.assertLess(peak, 16 * 1024 * 1024)
        self.assertEqual(mapping['display']['finite_pixels'], 2048 * 2048)
        self.assertEqual(image.getpixel((20, 20)), (128, 128, 128))
        self.assertIn('nearest', mapping['display']['resampling'])

    def test_preview_budget_check_precedes_range_scan(self):
        with mock.patch.object(self.worker, 'PREVIEW_MEMORY_BUDGET', 1), \
             mock.patch.object(self.worker, '_finite_range', side_effect=AssertionError('must not scan')):
            with self.assertRaisesRegex(RuntimeError, 'budget'):
                self.worker._preview_image(self.fixture.original, self.info, 32)

    def test_preview_range_includes_pixels_not_sampled_in_thumbnail(self):
        source = np.zeros((4, 64), dtype=np.float32)
        source[0, 0] = -50
        source[0, 2] = 200
        info = {'source_rect_xyxy': [10, 20, 74, 24], 'source_shape_yx': [24, 74]}
        _, mapping = self.worker._preview_image(source, info, 32)
        self.assertEqual(mapping['display']['display_min'], -50)
        self.assertEqual(mapping['display']['display_max'], 200)
        self.assertEqual(mapping['source_rect_xyxy'], [10, 20, 74, 24])

    def test_preview_nonfinite_and_extreme_values_keep_source_unchanged(self):
        array = np.array([[-1e308, 1e308], [np.nan, np.inf]])
        saved = array.copy()
        info = {'source_rect_xyxy': [0, 0, 2, 2], 'source_shape_yx': [2, 2]}
        image, mapping = self.worker._preview_image(array, info, 32)
        self.assertEqual(image.getpixel((0, 0)), (0, 0, 0))
        self.assertEqual(image.getpixel((1, 0)), (255, 255, 255))
        self.assertEqual(image.getpixel((0, 1)), (255, 0, 255))
        self.assertEqual(mapping['display']['finite_pixels'], 2)
        np.testing.assert_array_equal(array, saved)

    def test_operation_reuse_binds_calibration_metadata(self):
        self.generate()
        self.info['working_calibration_xy'][0]['scale'] *= 2
        metadata_path = Path(self.fixture.capture) / 'input.json'
        metadata_path.write_text(json.dumps(self.info), encoding='utf-8')
        manifest_path = Path(self.fixture.capture) / 'capture.json'
        manifest = self.fixture.read_json(str(manifest_path))
        canonical = json.dumps(self.info, sort_keys=True, ensure_ascii=False,
                               separators=(',', ':'), allow_nan=False).encode('utf-8')
        manifest['input_metadata_sha256'] = hashlib.sha256(canonical).hexdigest()
        manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
        run, response = invoke(self.request())
        self.assertNotEqual(run.returncode, 0)
        self.assertIn('different input', response['error'])

    def test_unapplied_intensity_scale_is_explicitly_raw(self):
        self.info['intensity_calibration'] = {'origin': 5, 'scale': 10, 'unit': 'electrons'}
        result = self.worker._profile_result(self.fixture.original, self.info,
                    {'start': [18, 44], 'end': [49, 44], 'width': 1})
        self.assertAlmostEqual(result['values'][0], 102.0)
        self.assertIn('raw', result['intensity_value_mode'])
        self.assertEqual(result['intensity_calibration']['scale'], 10)

    def test_documentation_keeps_reports_optional_and_skill_metadata_valid(self):
        for filename, word in [('README.md', '可选'), ('README.en.md', 'optional')]:
            text = (ROOT / filename).read_text(encoding='utf-8')
            self.assertIn(word, text.lower())
            self.assertIn('requirements-preview.txt', text)
        skill = (ROOT / 'skills' / 'dm-2d-analysis' / 'SKILL.md').read_text(encoding='utf-8')
        self.assertTrue(skill.startswith('---\nname: dm-2d-analysis\n'))
        self.assertIn('\ndescription:', skill)


if __name__ == '__main__':
    unittest.main()
