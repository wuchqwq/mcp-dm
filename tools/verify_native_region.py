"""Independent bounded NumPy reopening of a native chunked schema-1 capture.

No DigitalMicrograph import, live calls, retries or scientific processing.
This verifies assembled files against their individual original READs, not
that a mutable live source was an atomic snapshot or an experimental truth.
"""
import argparse
import base64
import hashlib
import json
import math
from pathlib import Path


def require(value, message):
    if not value:
        raise ValueError(message)


def digest_file(filename, skip=0):
    digest = hashlib.sha256()
    with filename.open('rb') as source:
        source.seek(skip)
        while True:
            block = source.read(65536)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def unique(pairs):
    out = {}
    for key, value in pairs:
        require(key not in out, 'Duplicate JSON key')
        out[key] = value
    return out


def load(filename, limit=1024 * 1024):
    require(filename.is_file() and not filename.is_symlink() and filename.stat().st_size <= limit,
            'Bounded ordinary evidence required')
    return json.loads(filename.read_text(encoding='utf-8'), object_pairs_hook=unique,
                      parse_constant=lambda token: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def verify_science(info):
    context, semantics = info.get('scientific_context'), info.get('scientific_semantics', {})
    require(semantics.get('schema_version') == 1 and semantics.get('native_calibration_preserved') is True,
            'Scientific semantics schema/native calibration missing')
    if context is None or context.get('status') == 'unresolved_lineage':
        require(semantics.get('status') == ('not_recorded' if context is None else 'unresolved_lineage') and
                semantics.get('domain') == semantics.get('representation') == 'unknown' and
                semantics.get('coordinate_axes') is None and semantics.get('phase_units') is None,
                'Unknown lineage must not invent quantitative axes/representation')
        return
    require(type(context) is dict and context.get('schema_version') == 1 and context.get('status') == 'tracked_fourier',
            'Invalid scientific creation context')
    producer = context['result']
    frequency = producer['frequency_grid'] is not None
    processed = bool(context['postprocessing'])
    require(semantics.get('status') == 'tracked_fourier' and semantics.get('domain') == ('frequency' if frequency else 'spatial') and
            semantics.get('representation') == ('processed_scalar' if processed else producer['representation']) and
            semantics.get('original_representation') == producer['representation'] and
            semantics.get('phase_units') == ('radians' if not processed and producer.get('phase_units') == 'radians' else None) and
            semantics.get('source_operation') == context['original_operation'] and semantics.get('source_request_id') == context['request_id'] and
            semantics.get('postprocessing') == context['postprocessing'], 'Representation/phase/producer mismatch')
    for key in ('transform_signs', 'normalization', 'centering', 'source_spatial_origin_used',
                'inverse_restores_source_origin', 'intensity_calibration_policy'):
        require(semantics.get(key) == producer.get(key), 'Transform interpretation differs: ' + key)
    require(len(semantics.get('coordinate_axes', [])) == 2, 'Two scientific coordinate axes required')
    for dim, axis in enumerate(semantics['coordinate_axes']):
        offset = context['source_offset_xy'][dim] + info['source_rect_xyxy'][dim]
        native = info['working_calibration_xy'][dim]
        grid = producer['frequency_grid']['axes'][dim] if frequency else producer['image']['calibration'][dim]
        step = grid['physical_frequency_step'] if frequency else grid['scale']
        zero = grid['frequency_at_index_zero'] if frequency else grid['calibrated_value_at_pixel_zero']
        mathematical = zero + offset * step
        require(axis.get('dm_dimension') == dim and axis.get('numpy_axis') == 1-dim and
                axis.get('size') == info['shape_yx'][1-dim] and axis.get('source_index_offset') == offset and
                axis.get('transform_size') == producer['image']['dm_dimensions'][dim] and
                axis.get('dc_index_in_roi') == (grid['dc_index']-offset if frequency else None) and
                axis.get('scale') == step and axis.get('unit') == native['unit'] and
                axis.get('calibrated_value_at_pixel_zero') == mathematical and
                axis.get('native_calibrated_value_at_pixel_zero') == native['calibrated_value_at_pixel_zero'] and
                axis.get('native_minus_mathematical_zero') == native['calibrated_value_at_pixel_zero']-mathematical,
                'Scientific/native coordinate or out-of-ROI DC mismatch')


def verify(capture, expected_pid=None, expected_session=None):
    import numpy as np
    capture = Path(capture).resolve(strict=True)
    info, manifest = load(capture / 'input.json'), load(capture / 'capture.json')
    require(info.get('schema_version') == manifest.get('schema_version') == 1 and
            info.get('capture_mode') == manifest.get('capture_mode') == 'native_chunked_read' and
            manifest.get('state') == 'captured' and manifest.get('complete_coverage') is True and
            info.get('capture_id') == manifest.get('capture_id') and
            info.get('native_receipt') is None and info.get('native_receipt_scope') == 'per_block' and
            info.get('pixel_capture_atomic') is False and info.get('dm_file_save') is False,
            'Complete explicit chunked capture required')
    require(expected_pid is None or manifest.get('host_pid') == expected_pid, 'Expected host PID mismatch')
    require(expected_session is None or manifest.get('native_session') == expected_session, 'Expected session mismatch')
    require(hashlib.sha256(canonical(info)).hexdigest() == manifest.get('input_metadata_sha256'), 'Metadata digest mismatch')
    filename = capture / 'input.npy'
    require(filename.is_file() and not filename.is_symlink() and filename.stat().st_size <= 17 * 1024 * 1024,
            'Bounded ordinary NPY required')
    require(digest_file(filename) == info.get('input_sha256') == manifest.get('input_sha256'), 'NPY digest mismatch')
    require(info.get('dtype') in ('float32', 'uint32'), 'Unsupported dtype')
    array = np.load(str(filename), mmap_mode='r', allow_pickle=False)
    try:
        dtype = np.dtype('<u4' if info['dtype'] == 'uint32' else '<f4')
        shape = info.get('shape_yx')
        require(type(shape) is list and len(shape) == 2 and all(type(n) is int and n > 0 for n in shape) and
                math.prod(shape) <= 4194304 and list(array.shape) == shape and array.dtype == dtype and
                array.flags.c_contiguous and info.get('byte_order') == 'little' and info.get('axes') == ['y', 'x'] and
                info.get('array_order') == 'C' and info.get('raw_bytes') == math.prod(shape) * 4 and
                info.get('input_file_bytes') == filename.stat().st_size == array.offset + array.nbytes,
                'NPY dtype/shape/order/byte count mismatch')
        require(digest_file(filename, array.offset) == info.get('pixel_sha256') == manifest.get('pixel_sha256'), 'Pixel digest mismatch')
        rect = info.get('source_rect_xyxy')
        require(type(rect) is list and len(rect) == 4 and all(type(n) is int and n >= 0 for n in rect) and
                rect[2] - rect[0] == shape[1] and rect[3] - rect[1] == shape[0] and rect == manifest.get('source_rect_xyxy'), 'ROI mismatch')
        blocks = manifest.get('blocks')
        require(type(blocks) is list and 0 < len(blocks) <= 512 and len(info.get('native_receipts', [])) == len(blocks), 'Block count mismatch')
        # Independent scanline cover; no image-sized coverage bitmap or array copy.
        expected_x, expected_y, row_bottom, covered = rect[0], rect[1], None, 0
        anchor, first_calibration = None, None
        ids = set()
        for index, block in enumerate(blocks):
            require(block.get('index') == index and block.get('state') == 'COMPLETED', 'Missing/duplicate/out-of-order block')
            request = block.get('request', {})
            args = request.get('args', [])
            require(len(args) == 5 and args[0] == info.get('source_image_id') and
                    all(type(n) is int and 0 <= n <= 0xffffffff for n in args) and request.get('op') == 'READ' and
                    request.get('protocol') == 'NB2' and request.get('session') == manifest.get('native_session') and
                    request.get('host_pid') == manifest.get('host_pid') and request.get('id') not in ids and
                    request.get('wire') == 'NB2 {} {} READ {}\n'.format(request['session'], request['id'], ' '.join(map(str, args))),
                    'Original request identity mismatch')
            ids.add(request['id'])
            x0, y0, x1, y1 = args[1:]
            require(x0 == expected_x and y0 == expected_y and x0 < x1 <= rect[2] and y0 < y1 <= rect[3] and
                    (row_bottom is None or row_bottom == y1), 'Coverage gap/overlap/wrong block position')
            row_bottom = y1
            expected_x = x1
            if x1 == rect[2]:
                expected_x, expected_y, row_bottom = rect[0], y1, None
            count = (x1 - x0) * (y1 - y0)
            require(count <= 16384, 'Block sample budget exceeded')
            saved = capture / 'read-{}.json'.format(index)
            value = load(saved, 128 * 1024)
            require(digest_file(saved) == block.get('snapshot_sha256'), 'Block file digest mismatch')
            receipt = value.get('native_receipt', {})
            require(receipt.get('protocol') == 'NB2' and receipt.get('state') == 'completed' and
                    receipt.get('session') == request['session'] and receipt.get('id') == receipt.get('request_id') == request['id'] and
                    receipt.get('host_pid') == request['host_pid'] and receipt.get('original_operation') == 'READ' and
                    receipt.get('normalized_args') == args and receipt.get('result_type') == 'native_data_snapshot' and
                    receipt.get('result_version') == 1 and type(receipt.get('exec_tid')) is int and receipt['exec_tid'] > 0 and
                    type(receipt.get('worker_tid')) is int and receipt['worker_tid'] > 0 and receipt['exec_tid'] != receipt['worker_tid'],
                    'Block receipt host/session/ID/type/thread mismatch')
            require(info['native_receipts'][index] == {'request': request, 'snapshot_file': saved.name, 'snapshot_sha256': block['snapshot_sha256']},
                    'Metadata block identity mismatch')
            require(value.get('source_image_id') == args[0] and value.get('requested_rect') == value.get('effective_rect') == args[1:] and
                    value.get('shape') == [y1-y0, x1-x0] and value.get('dtype') == info['dtype'] and value.get('raw_bytes') == count*4 and
                    value.get('sample_count') == count and value.get('byte_order') == 'little' and value.get('array_order') == 'C' and
                    value.get('axes') == ['y', 'x'] and value.get('intensity_calibration_applied') is False and
                    value.get('source_write_requested') is False and value.get('snapshot_atomic') is False, 'Block numeric contract mismatch')
            raw = base64.b64decode(value['values_base64'], validate=True)
            require(base64.b64encode(raw).decode('ascii') == value['values_base64'] and len(raw) == count * 4 and
                    hashlib.sha256(raw).hexdigest() == block.get('pixel_sha256'), 'Block encoding/bytes mismatch')
            source = value.get('source', {})
            current = {key: value.get(key) for key in ('source', 'scientific_context', 'source_provenance', 'source_provenance_scope', 'coordinate_mapping_policy')}
            require(anchor is None or current == anchor, 'Source/calibration/lineage changed between blocks')
            if anchor is None:
                anchor = current
                first_calibration = value.get('roi_calibration')
                require(source == info.get('source_metadata') and value.get('scientific_context') == info.get('scientific_context'), 'Source metadata differs')
            require(source.get('dtype') == info['dtype'] and source.get('id') == args[0] and source.get('packing_style') == 1 and
                    source.get('shape') == info.get('source_shape_yx') and x1 <= source['shape'][1] and y1 <= source['shape'][0], 'Source descriptor mismatch')
            for axis, offset in enumerate((x0, y0)):
                original, roi = source['calibration'][axis], value['roi_calibration'][axis]
                require(roi['source_offset'] == offset and roi['source_origin'] == original['origin'] and roi['source_calibrated_value_at_pixel_zero'] == original['calibrated_value_at_pixel_zero'] and
                        roi['scale'] == original['scale'] and roi['unit'] == original['unit'] and roi['size'] == (x1-x0 if axis == 0 else y1-y0), 'Block calibration identity mismatch')
                if roi['usable']:
                    require(roi['origin'] == original['origin'] - offset and
                            roi['calibrated_value_at_pixel_zero'] == original['calibrated_value_at_pixel_zero'] + offset * original['scale'], 'Signed calibration/origin mismatch')
            for row in range(y1-y0):
                actual = array[y0-rect[1]+row, x0-rect[0]:x1-rect[0]].tobytes(order='C')
                require(actual == raw[row*(x1-x0)*4:(row+1)*(x1-x0)*4], 'NPY pixel/placement differs from native READ')
            covered += count
        require(expected_y == rect[3] and expected_x == rect[0] and covered == math.prod(shape), 'Incomplete coverage')
        require(info.get('source_calibration_dm') == [dict(axis, axis='x' if dim == 0 else 'y')
                for dim, axis in enumerate(info['source_metadata']['calibration'])] and
                info.get('working_calibration_xy') == [dict(axis, size=shape[1-dim], axis='x' if dim == 0 else 'y')
                for dim, axis in enumerate(first_calibration)], 'Aggregate axes/calibration differ from original READ')
        creation = info.get('native_source_creation_record')
        provenance = info.get('native_source_provenance')
        if creation is not None:
            source_record = load(capture / 'source-creation.json', 128 * 1024)
            contracts = {'CROP': (5, 'image_crop', 1), 'UNARY': (2, 'native_image_operation', 1),
                         'BINARY': (3, 'native_image_operation', 1), 'FILTER': (2, 'native_image_operation', 1),
                         **{op: (1, 'native_fourier_operation', 2) for op in
                            ('FFT', 'IFFT', 'REAL', 'IMAG', 'VENDOR_ARG', 'VENDOR_NORM')}}
            operation = source_record.get('original_operation')
            contract = contracts.get(operation)
            args = source_record.get('normalized_args')
            require(contract is not None and type(args) is list and len(args) == contract[0] and
                    all(type(arg) is int and 0 <= arg <= 0xffffffff for arg in args) and
                    source_record.get('result_type') == contract[1] and source_record.get('result_version') == contract[2] and
                    all(type(source_record.get(key)) is int and 0 < source_record[key] <= 0xffffffff
                        for key in ('exec_tid', 'worker_tid')) and source_record['exec_tid'] != source_record['worker_tid'] and
                    source_record.get('result', {}).get('backend') == 'digitalmicrograph-native' and
                    type(provenance) is dict and provenance.get('source_image_ids') == args[:2 if operation == 'BINARY' else 1],
                    'Invalid original source creation contract')
            require(type(provenance) is dict and creation.get('file') == 'source-creation.json' and
                    creation.get('sha256') == digest_file(capture / 'source-creation.json') and
                    creation.get('request_id') == source_record.get('id') == provenance.get('request_id') and
                    creation.get('original_operation') == source_record.get('original_operation') == provenance.get('operation') and
                    creation.get('normalized_args') == source_record.get('normalized_args') and
                    source_record.get('protocol') == 'NB2' and source_record.get('state') == 'completed' and
                    source_record.get('host_pid') == manifest['host_pid'] and source_record.get('session') == manifest['native_session'] and
                    source_record.get('result', {}).get('image_id') == info['source_image_id'] and
                    source_record['result'].get('image') == info['source_metadata'] and
                    info.get('source_creation_parameters_status') == 'ORIGINAL_QUERY_SAVED', 'Original source processing parameters mismatch')
        elif 'native_source_creation_record' in info:
            require(provenance is None and info.get('source_creation_parameters_status') == 'NOT_PLUGIN_CREATED',
                    'Plugin source is missing its original creation parameters')
        for axis, offset in enumerate(rect[:2]):
            source = info['source_metadata']['calibration'][axis]
            work = info['working_calibration_xy'][axis]
            require(work['source_offset'] == offset and work['size'] == shape[1-axis] and work['scale'] == source['scale'] and
                    work['unit'] == source['unit'] and work['source_origin'] == source['origin'], 'Aggregate calibration mismatch')
            if work['usable']:
                require(work['origin'] == source['origin'] - offset and work['calibrated_value_at_pixel_zero'] == source['calibrated_value_at_pixel_zero'] + offset * source['scale'],
                        'Aggregate physical zero mismatch')
        verify_science(info)
        return {'status': 'PASS_INDEPENDENT_CHUNKED_FILES', 'shape_yx': shape, 'dtype': info['dtype'],
                'blocks': len(blocks), 'host_pid': manifest['host_pid'], 'native_session': manifest['native_session'],
                'pixel_capture_atomic': False, 'scope': 'saved original READ bytes, placement, descriptor/calibration and reopened NPY; no live-source or operator qualification'}
    finally:
        array._mmap.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', required=True)
    parser.add_argument('--host-pid', type=int)
    parser.add_argument('--session')
    args = parser.parse_args()
    try:
        result = verify(args.capture, args.host_pid, args.session)
        print(json.dumps(result, ensure_ascii=True, allow_nan=False))
        return 0
    except Exception as error:
        print(json.dumps({'status': 'FAIL', 'error': str(error)}, ensure_ascii=True, allow_nan=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
