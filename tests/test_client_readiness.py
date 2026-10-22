"""D0 handoff checks: synthetic only, no real WorkBuddy or DM claims."""
import contextlib
import io
import json
import os
import runpy
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

import numpy as np
from test_analysis import FakeImage
import test_analysis2d_worker as worker_tests

ROOT = worker_tests.ROOT


class ClientReadinessTests(unittest.TestCase):
    def test_fixture_is_small_exact_and_uses_only_new_images(self):
        created = []
        def create(array):
            image = FakeImage(array.copy(), image_id=4000 + len(created))
            created.append(image)
            return image
        fake = SimpleNamespace(CreateImage=create)
        with mock.patch.dict(sys.modules, {'DigitalMicrograph': fake}), contextlib.redirect_stdout(io.StringIO()):
            runpy.run_path(os.path.join(ROOT, 'examples', 'create_2d_client_fixture.py'))
        self.assertEqual(len(created), 2)
        source, other = created
        self.assertTrue(source.name.startswith('MCP_D0_RAMP_'))
        self.assertTrue(other.name.startswith('MCP_D0_OTHER_'))
        self.assertEqual(source.array.shape, (48, 64))
        self.assertEqual(source.array.dtype, np.dtype('float32'))
        selected = source.array[8:18, 10:30]
        self.assertEqual(int(selected.size), 200)
        self.assertEqual(float(selected.min()), 810.0)
        self.assertEqual(float(selected.max()), 1729.0)
        self.assertEqual(float(selected.mean()), 1269.5)
        np.testing.assert_array_equal(source.array[12, 10:30], np.arange(1210, 1230))
        self.assertEqual(source.scales, [-0.25, 0.5])
        self.assertEqual(source.origins, [1.25, -2.5])
        self.assertEqual(19 * abs(source.scales[0]), 4.75)
        self.assertEqual(source.origins[0] + 10 * source.scales[0], -1.25)
        self.assertEqual(source.origins[1] + 8 * source.scales[1], 1.5)
        self.assertTrue(np.all(other.array[8:18, 40:54] == 2000))
        self.assertTrue(np.all(other.array[28:40, 8:22] == 0))
        self.assertEqual(float(other.array[0, 0]), 777.0)

    def test_preview_example_is_generic_json_not_codex_toml(self):
        with open(os.path.join(ROOT, 'mcp.preview.json.example'), encoding='utf-8') as stream:
            config = json.load(stream)
        server = config['mcpServers']['digitalmicrograph']
        self.assertEqual(set(server), {'command', 'args', 'env'})
        self.assertIn('DM_ANALYSIS_PYTHON', server['env'])
        self.assertEqual(server['env']['DM_MCP_ALLOW_DMSCRIPT'], '0')
        self.assertEqual(server['env']['DM_BRIDGE_HOST'], '127.0.0.1')
        self.assertNotIn('disabled_tools', server)
        self.assertNotIn('tool_timeout_sec', server)
        self.assertNotIn('DM_BRIDGE_MOCK', server['env'])

    @unittest.skipUnless(worker_tests.HAS_ANALYSIS_DEPS, 'install external analysis test dependencies')
    def test_preview_returns_the_captured_calibration_without_file_read_tools(self):
        fixture = worker_tests.Analysis2DWorkerTests('runTest')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        result = fixture.worker({'action': 'preview', 'capture_dir': fixture.capture, 'max_side': 32})['result']
        info = fixture.read_json(os.path.join(fixture.capture, 'input.json'))
        capture = fixture.read_json(os.path.join(fixture.capture, 'capture.json'))
        self.assertEqual(result['working_calibration_xy'], info['working_calibration_xy'])
        self.assertEqual(result['source_image_id'], info['source_image_id'])
        self.assertEqual(result['input_metadata_sha256'], capture['input_metadata_sha256'])
        self.assertEqual(result['intensity_calibration'], info['intensity_calibration'])
        self.assertIn('raw', result['intensity_values'])
        self.assertIn('captured', result['calibration_coordinate_frame'])
        self.assertEqual(result['input_sha256'], info['input_sha256'])


if __name__ == '__main__':
    unittest.main()
