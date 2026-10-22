"""Explicit real-host acceptance using only owned, small synthetic images.

Not collected by unittest. Run ``run(output_directory)`` in DM's background
Python workspace. Never enables the arbitrary-script MCP tool or opens data.
The only embedded DM-Script builds a fixed synthetic list on an owned image.
Detailed host evidence belongs in a private output directory, not git.
"""
import hashlib
import importlib.util
import json
import os
import traceback
from pathlib import Path

import numpy as np


def run(output_directory):
    import DigitalMicrograph as DM
    destination = Path(output_directory)
    destination.mkdir(parents=True, exist_ok=False)
    module_path = Path(__file__).resolve().parents[1] / 'bridge' / 'dm_bridge.py'
    spec = importlib.util.spec_from_file_location('real_2d_acceptance_bridge', str(module_path))
    bridge = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bridge)
    backend = bridge.DmBackend(DM)
    owned = []
    report = {'scope': 'real DM, fixed synthetic operations only', 'checks': [],
              'backend': backend.ping(), 'failures': [], 'not_tested': []}

    def save():
        (destination / 'summary.json').write_text(
            json.dumps(bridge._j(report), ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')

    def check(name, function):
        try:
            detail = function()
            report['checks'].append({'name': name, 'status': 'PASS', 'detail': detail})
        except Exception:
            report['checks'].append({'name': name, 'status': 'FAIL', 'error': traceback.format_exc()})
            report['failures'].append(name)
        save()

    def describe(img):
        return {'id': int(img.GetID()), 'name': backend._safe(img.GetName),
                'shape': backend._dims(img)[1], 'calibration': backend._calib(img, 2)}

    def listing():
        return {int(i.GetID()): describe(i) for _, _, _, i in backend._iter_images()}

    def array(img):
        return np.array(img.GetNumArray(), copy=True)

    def create(data, name):
        # GMS rejects a contiguous NumPy *view* even when shape/dtype are valid.
        img = DM.CreateImage(np.array(data, copy=True, order='C'))
        if img is None or not img.IsValid():
            raise RuntimeError('Synthetic CreateImage returned an invalid image')
        owned.append(img)
        img.SetName(name)
        # Hold hidden documents; their wrappers otherwise disappear from lookup.
        backend._opened_documents[(int(img.GetID()),)] = img.GetOrCreateImageDocument()
        return img

    before = listing()
    try:
        expected = np.arange(117, dtype=np.float32).reshape(9, 13)
        source = create(expected, 'mcp synthetic duplicate')
        other = create(np.full((9, 13), 777, dtype=np.float32), 'mcp synthetic duplicate')
        for img in (source, other):
            img.SetDimensionCalibration(0, 1.23456789, 0.125, 'nm', 0)
            img.SetDimensionCalibration(1, -2.34567891, -0.25, 'nm', 0)
        sid = int(source.GetID())
        source_before, other_before = describe(source), describe(other)
        source_pixels, other_pixels = array(source), array(other)
        report['source_calibration'] = source_before['calibration']

        def crop(rect):
            result = backend.crop(sid, rect, 'mcp synthetic duplicate')
            target = backend._resolve(result['new_image']['id'])
            owned.append(target)
            x0, y0, x1, y1 = rect
            np.testing.assert_array_equal(array(target), expected[y0:y1, x0:x1])
            assert result['requested_rect'] == result['effective_rect'] == rect
            assert result['new_image']['shape'] == [y1-y0, x1-x0]
            rounding = []
            for d, start in ((0, x0), (1, y0)):
                zero, scale, unit = source.GetDimensionCalibration(d, 0)
                got_zero, got_scale, got_unit = target.GetDimensionCalibration(d, 0)
                requested = zero + start * scale
                # GMS native origin is float32, not a double-precision promise.
                native_expected = float(np.float32(requested))
                assert abs(got_zero - native_expected) <= 1e-9
                assert abs(got_scale - scale) <= 1e-12 and got_unit == unit
                rounding.append({'dimension': d, 'requested': requested, 'actual': got_zero,
                                 'float32_expected': native_expected})
            return {'image_id': int(target.GetID()), 'rect': rect, 'rounding': rounding}

        for rect in ([2, 1, 7, 5], [0, 0, 13, 9], [12, 8, 13, 9]):
            check('crop:' + str(rect), lambda r=rect: crop(r))

        def colliding_window():
            collision = []
            class FixtureDM(object):
                def __getattr__(self, key):
                    return getattr(DM, key)
                def ExecuteScriptString(self, script):
                    DM.ExecuteScriptString(script)
                    unrelated = create(np.full((4, 5), 999, dtype=np.float32),
                                       'mcp synthetic duplicate')
                    collision.append((unrelated, describe(unrelated), array(unrelated)))
            backend.DM = FixtureDM()
            try:
                result = crop([2, 1, 7, 5])
                unrelated, descriptor, pixels = collision[0]
                assert result['image_id'] != int(unrelated.GetID())
                assert describe(unrelated) == descriptor
                np.testing.assert_array_equal(array(unrelated), pixels)
                return {'owned_result': result['image_id'], 'unrelated_image_preserved': True}
            finally:
                backend.DM = DM
        check('same-name same-size window created during crop', colliding_window)

        def invalid(rect):
            ids = set(listing())
            for method in (lambda: backend.crop(sid, rect, 'mcp synthetic duplicate'),
                           lambda: backend.stats(sid, rect), lambda: backend.fft(sid, rect, 3)):
                try:
                    method()
                except ValueError:
                    pass
                else:
                    raise AssertionError('Invalid ROI was accepted')
            assert ids == set(listing()), 'Invalid ROI created an image'

        for rect in ([100, 100, 110, 110], [12, 8, 14, 10], [-1, 0, 2, 2],
                     [0.0, 0, 2, 2], [False, 0, 2, 2], [0, 0, 0, 2]):
            check('reject:' + str(rect), lambda r=rect: invalid(r))

        root = source.GetTagGroup()
        noise = DM.NewTagGroup()
        for n in range(24):
            noise.SetTagAsLong('n%d' % n, n)
        root.SetTagAsTagGroup('Noise', noise)
        target = DM.NewTagGroup()
        deep = DM.NewTagGroup()
        deep.SetTagAsLong('answer', 42)
        target.SetTagAsTagGroup('Deep', deep)
        root.SetTagAsTagGroup('Target', target)
        root.SetTagAsLong('a/b~c', 55)
        # Literal fixed fixture, no caller-controlled script or source access.
        DM.ExecuteScriptString(
            'image img := FindImageByID(%d)\n'
            'TagGroup root = img.ImageGetTagGroup()\n'
            'TagGroup items = NewTagList()\n'
            'TagGroup child = NewTagGroup()\n'
            'child.TagGroupSetTagAsLong("value", 73)\n'
            'items.TagGroupInsertTagAsLong(0, 11)\n'
            'items.TagGroupInsertTagAsTagGroup(1, child)\n'
            'root.TagGroupSetTagAsTagGroup("List", items)\n' % sid)

        def metadata(prefix, value, depth=0):
            result = backend.metadata(sid, depth, prefix)
            assert result['path_status'] == 'found' and result['complete'], result
            assert result['tags'] == value, result
            return result

        check('metadata:deep prefix at depth zero', lambda: metadata('/Target/Deep', {'answer': 42}))
        check('metadata:escaped label', lambda: metadata('/a~1b~0c', 55))
        check('metadata:list index', lambda: metadata('/List/1/value', 73))

        def missing():
            result = backend.metadata(sid, 0, '/Target/Absent')
            assert result['path_status'] == 'not_found' and result['tags'] is None, result
            return result
        check('metadata:confirmed absence', missing)

        def budgets():
            old = bridge.MAX_TAG_NODES
            try:
                bridge.MAX_TAG_NODES = 8
                selected = metadata('/Target/Deep', {'answer': 42})
                truncated = backend.metadata(sid, 0, '/Noise')
                assert truncated['path_status'] == 'found' and not truncated['complete'], truncated
                assert any(i['reason'] == 'node_budget' for i in truncated['issues']), truncated
                return {'target': selected, 'incomplete': truncated}
            finally:
                bridge.MAX_TAG_NODES = old
        check('metadata:separate lookup and subtree budgets', budgets)

        def fixed_capture():
            capture_dir = destination / 'capture-region'
            result = backend.capture2d(sid, [2, 1, 7, 5], str(capture_dir))
            captured = np.load(str(capture_dir / 'input.npy'), allow_pickle=False)
            input_info = json.loads((capture_dir / 'input.json').read_text(encoding='utf-8'))
            capture_manifest = json.loads((capture_dir / 'capture.json').read_text(encoding='utf-8'))
            np.testing.assert_array_equal(captured, expected[1:5, 2:7])
            assert result['shape_yx'] == [4, 5] and captured.dtype == np.dtype('float32')
            assert input_info['source_rect_xyxy'] == [2, 1, 7, 5]
            assert input_info['input_sha256'] == result['input_sha256'] == capture_manifest['input_sha256']
            metadata_hash = hashlib.sha256(json.dumps(input_info, ensure_ascii=False, sort_keys=True,
                                                      separators=(',', ':')).encode('utf-8')).hexdigest()
            assert capture_manifest['input_metadata_sha256'] == metadata_hash
            assert capture_manifest['state'] == 'captured'
            assert capture_manifest['pixel_capture_atomic'] is False
            source_cal = source.GetDimensionCalibration(0, 0)
            y_cal = source.GetDimensionCalibration(1, 0)
            expected_x_zero = float(source_cal[0] + 2 * source_cal[1])
            expected_y_zero = float(y_cal[0] + 1 * y_cal[1])
            assert abs(input_info['working_calibration_xy'][0]['calibrated_value_at_pixel_zero'] - expected_x_zero) <= 1e-9
            assert abs(input_info['working_calibration_xy'][1]['calibrated_value_at_pixel_zero'] - expected_y_zero) <= 1e-9
            original_capture = captured.copy()
            shared = source.GetNumArray()
            old_value = float(shared[1, 2])
            shared[1, 2] = old_value + 1000.0
            try:
                after_edit = np.load(str(capture_dir / 'input.npy'), allow_pickle=False)
                np.testing.assert_array_equal(after_edit, original_capture)
            finally:
                shared[1, 2] = old_value
            too_small = destination / 'capture-over-budget'
            old_budget = bridge.MAX_2D_CAPTURE_WORKING_BYTES
            try:
                bridge.MAX_2D_CAPTURE_WORKING_BYTES = 1
                try:
                    backend.capture2d(sid, [2, 1, 7, 5], str(too_small))
                except RuntimeError as error:
                    assert '超过' in str(error)
                else:
                    raise AssertionError('capture budget was not enforced')
                assert not too_small.exists(), 'budget rejection must happen before creating output'
            finally:
                bridge.MAX_2D_CAPTURE_WORKING_BYTES = old_budget
            return {'capture_id': result['capture_id'], 'shape_yx': result['shape_yx'],
                    'dtype': result['dtype'], 'input_sha256': result['input_sha256'],
                    'shifted_xy_zero': [expected_x_zero, expected_y_zero],
                    'captured_pixels_survive_later_source_edit': True,
                    'budget_rejected_before_output_creation': True}
        check('bounded immutable 2D capture and signed calibration', fixed_capture)

        def unchanged():
            np.testing.assert_array_equal(array(source), source_pixels)
            np.testing.assert_array_equal(array(other), other_pixels)
            assert describe(source) == source_before
            assert describe(other) == other_before
            now = listing()
            assert all(now.get(i) == value for i, value in before.items())
            return {'source_pixels_and_calibration': True, 'unrelated_documents': True}
        check('source and unrelated image invariant', unchanged)
        report['not_tested'].append('Native getter failure/crash injection is not performed on user host')
    except Exception:
        report['failures'].append('fixture/setup')
        report['setup_error'] = traceback.format_exc()
    finally:
        # Delete only IDs created by this fixed acceptance invocation.
        for image in reversed(owned):
            try:
                DM.DeleteImage(image)
            except Exception:
                report.setdefault('cleanup_errors', []).append(traceback.format_exc())
        report['status'] = 'PASS' if not report['failures'] and not report.get('cleanup_errors') else 'FAIL'
        save()
    return report
