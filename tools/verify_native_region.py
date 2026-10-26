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
import re
import struct


_REQUEST_ID = re.compile(r'[A-Za-z0-9_-]{1,64}\Z')
PIXEL_OPERATIONS = {name + '_PIXEL': name for name in
                    ('CROP', 'FILTER', 'FFT', 'IFFT', 'REAL', 'IMAG', 'VENDOR_ARG', 'VENDOR_NORM')}


def _uint(value, minimum=0):
    return type(value) is int and minimum <= value <= 0xffffffff


def _number(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _frame_metadata(image, source):
    rank = 3 if source else 2
    require(type(image) is dict and _uint(image.get('id'), 1) and type(image.get('name')) is str and
            type(image.get('ndim')) is int and image['ndim'] == rank and image.get('dtype') == ('uint16' if source else 'float32') and
            type(image.get('data_type_code')) is int and image['data_type_code'] == (10 if source else 2) and
            type(image.get('packing_style')) is int and image['packing_style'] == 1,
            'FRAME typed source/output descriptor mismatch')
    shape = image.get('shape')
    require(type(shape) is list and len(shape) == rank and all(_uint(n, 1) for n in shape) and
            type(image.get('dm_dimensions')) is list and all(_uint(n, 1) for n in image['dm_dimensions']) and
            image['dm_dimensions'] == list(reversed(shape)) and _uint(image.get('pixels'), 1) and image['pixels'] == math.prod(shape) and
            image.get('shape_order') == 'numpy (last axis is X)' and
            image.get('coordinate_rule') == 'physical(i)=calibrated_value_at_pixel_zero+i*scale' and
            (not source or image.get('is_integer') is True and image.get('is_unsigned') is True) and
            type(image.get('native_mean_supported')) is bool and type(image.get('native_summary_supported')) is bool and
            (not source or image['native_mean_supported'] is image['native_summary_supported'] is False) and
            image['pixels'] * (2 if source else 4) <= 0xffffffff and
            math.prod(shape[-2:]) <= 1048576,
            'FRAME bounded canonical shape/packing mismatch')
    axes = image.get('calibration')
    require(type(axes) is list and len(axes) == rank, 'FRAME source/output axes missing')
    for dim, axis in enumerate(axes):
        require(type(axis) is dict and _uint(axis.get('dm_dimension')) and axis['dm_dimension'] == dim and
                _uint(axis.get('numpy_axis')) and axis['numpy_axis'] == rank-1-dim and
                _uint(axis.get('size'), 1) and axis['size'] == shape[rank-1-dim] and
                all(axis.get(key) is None or _number(axis[key]) for key in
                    ('origin', 'scale', 'calibrated_value_at_pixel_zero')) and
                (axis.get('unit') is None or type(axis['unit']) is str and bool(axis['unit'])) and
                type(axis.get('usable')) is bool, 'FRAME axis descriptor mismatch')
        numbers = all(_number(axis.get(key)) for key in ('origin', 'scale', 'calibrated_value_at_pixel_zero')) and axis['scale'] != 0
        unit = axis['unit'] is not None
        if axis['usable']:
            require(numbers and unit and axis.get('issue') is None, 'FRAME usable calibration mismatch')
        elif axis.get('issue') == 'unknown_units':
            require(numbers and not unit, 'FRAME missing-unit calibration mismatch')
        elif axis.get('issue') == 'invalid_calibration':
            require(unit, 'FRAME invalid calibration issue mismatch')
        else:
            require(axis.get('issue') == 'invalid_calibration_and_unknown_units' and not unit,
                    'FRAME unknown calibration issue')
    require(image.get('calibration_complete') is all(axis['usable'] for axis in axes),
            'FRAME calibration completeness mismatch')


def validate_frame_payload(result, args):
    """Independent metadata/identity validation; never calls DM or computes pixels."""
    require(type(args) is list and len(args) == 2 and _uint(args[0], 1) and _uint(args[1]) and
            type(result) is dict and result.get('backend') == 'digitalmicrograph-native' and
            result.get('operation') == 'FRAME' and result.get('source_image_id') == args[0] and
            result.get('candidate_probe') is not True and result.get('qualification') != 'NOT_QUALIFIED' and
            _uint(result.get('frame_index')) and result['frame_index'] == args[1] and _uint(result.get('image_id'), 1) and
            result['image_id'] != args[0], 'FRAME original image/index/output identity mismatch')
    source, image = result.get('source'), result.get('image')
    _frame_metadata(source, True)
    _frame_metadata(image, False)
    require(source['id'] == args[0] and image['id'] == result['image_id'] and
            args[1] < source['shape'][0] and image['shape'] == source['shape'][1:] and
            image['pixels'] == math.prod(source['shape'][1:]), 'FRAME source/frame/output shape mismatch')
    for dim in range(2):
        original, output = source['calibration'][dim], image['calibration'][dim]
        require(all(output.get(key) == original.get(key) for key in
                    ('dm_dimension', 'size', 'origin', 'scale', 'unit', 'calibrated_value_at_pixel_zero', 'usable', 'issue')),
                'FRAME native XY calibration changed')
    axis, selected = source['calibration'][2], result.get('frame_axis')
    numbers = all(_number(axis.get(key)) for key in ('origin', 'scale', 'calibrated_value_at_pixel_zero')) and axis['scale'] != 0
    numbers = numbers and axis.get('issue') not in ('invalid_calibration', 'invalid_calibration_and_unknown_units')
    # Vendor/C++/JSON coordinates are binary64, including integer-looking JSON
    # tokens. Preserve those arithmetic semantics rather than Python big ints.
    coordinate = float(axis['calibrated_value_at_pixel_zero']) + args[1] * float(axis['scale']) if numbers else None
    require(coordinate is None or _number(coordinate), 'FRAME selected sequence coordinate is not finite')
    require(type(selected) is dict and all(_uint(selected.get(key)) for key in ('dm_dimension', 'numpy_axis', 'index_base', 'count')) and
            type(selected.get('usable')) is bool and selected == {'dm_dimension': 2, 'numpy_axis': 0, 'index_base': 0,
            'role': 'unspecified_sequence', 'count': source['shape'][0], 'calibrated_value': coordinate,
            'unit': axis['unit'], 'usable': axis['usable']}, 'FRAME sequence axis/index/coordinate mismatch')
    conversion = result.get('dtype_conversion')
    require(type(conversion) is dict and conversion.get('lossless_values') is True and
            all(_uint(conversion.get(key)) for key in ('input_data_type_code', 'output_data_type_code')) and
            conversion == {'input_dtype': 'uint16', 'input_data_type_code': 10,
            'output_dtype': 'float32', 'output_data_type_code': 2, 'lossless_values': True,
            'operator': 'GMSImageProcessing::ImageConvert'} and
            _uint(result.get('output_bytes'), 1) and result['output_bytes'] == image['pixels'] * 4 and
            _uint(result.get('validation_peak_new_image_bytes'), 1) and result['validation_peak_new_image_bytes'] == image['pixels'] * 6 and
            result.get('operator') == 'GMS::Image::GetSubSliceAsImage + GMSImageProcessing::ImageConvert' and
            result.get('computation') == 'DM native frame copy and explicit uint16-to-float32 conversion' and
            result.get('intensity_calibration_applied') is False and result.get('intensity_semantics') == 'raw pixel intensity' and
            result.get('source_write_requested') is False and result.get('snapshot_atomic') is False and
            result.get('visible_dm_document') is False and result.get('ownership') ==
            'plugin retained strong reference until normal native STOP/cleanup',
            'FRAME native conversion/budget/ownership/raw semantics mismatch')
    intensity = result.get('intensity_calibration_source')
    require(type(intensity) is dict and set(intensity) == {'origin', 'scale', 'unit'} and
            all(intensity.get(key) is None or _number(intensity[key]) for key in ('origin', 'scale')) and
            (intensity.get('unit') is None or type(intensity['unit']) is str) and
            result.get('intensity_calibration_output') == intensity, 'FRAME intensity calibration was not copied')
    return result


def verify_frame_ancestry(value):
    """Unknown old records remain unknown; reject ambiguous ancestry for scientific use."""
    ancestry = value.get('frame_ancestry')
    provenance = value.get('source_provenance', value.get('native_source_provenance'))
    if ancestry is None:
        require(not provenance or provenance.get('operation') != 'FRAME', 'FRAME source is missing its original frame ancestry')
        return None
    require(type(ancestry) is dict and set(ancestry) == {'schema_version', 'status', 'request_id', 'normalized_args', 'result', 'scope'} and
            type(ancestry.get('schema_version')) is int and ancestry['schema_version'] == 1 and ancestry.get('status') == 'tracked_frame' and
            type(ancestry.get('request_id')) is str and _REQUEST_ID.fullmatch(ancestry['request_id']) and
            ancestry.get('scope') == 'original frame identity only; current values and coordinates follow current operation metadata',
            'Unresolved or malformed frame ancestry cannot be a scientific capture')
    producer = validate_frame_payload(ancestry.get('result'), ancestry.get('normalized_args'))
    require('retention' not in producer and 'native_receipt' not in producer and 'frame_ancestry' not in producer,
            'Frame ancestry must freeze the original payload before transport decoration')
    require(type(provenance) is dict and set(provenance) == {'operation', 'request_id', 'source_image_ids', 'semantics'} and
            type(provenance.get('request_id')) is str and _REQUEST_ID.fullmatch(provenance['request_id']) and
            type(provenance.get('semantics')) is str and bool(provenance['semantics']) and
            type(provenance.get('source_image_ids')) is list and len(provenance['source_image_ids']) == 1 and
            _uint(provenance['source_image_ids'][0], 1), 'Frame ancestry requires a single-parent creation provenance')
    current = value.get('source', value.get('source_metadata'))
    require(type(current) is dict, 'Frame ancestry current source missing')
    if provenance['operation'] == 'FRAME':
        require(current == producer['image'] and value.get('source_image_id') == producer['image_id'] and
                provenance['request_id'] == ancestry['request_id'] and
                provenance['source_image_ids'] == ancestry['normalized_args'][:1],
                'Direct FRAME source differs from original frame creation')
    else:
        require(PIXEL_OPERATIONS.get(provenance['operation'], provenance['operation']) in
                ('CROP', 'UNARY', 'FILTER', 'FFT', 'IFFT', 'REAL', 'IMAG', 'VENDOR_ARG', 'VENDOR_NORM') and
                provenance['request_id'] != ancestry['request_id'] and
                current.get('id') == value.get('source_image_id') and current['id'] != producer['image_id'],
                'Frame ancestry is not a distinct single-parent derived image')
    return ancestry


def verify_frame_samples(raw, value):
    """A direct lossless uint16 frame copy can only contain those exact values.

    Derived float operations keep their own value semantics. This check does
    not claim that a mutable frame has stayed unchanged since its creation.
    """
    provenance = value.get('source_provenance', value.get('native_source_provenance'))
    if not provenance or provenance.get('operation') != 'FRAME':
        return
    data = memoryview(raw).cast('B')
    require(value.get('dtype') == 'float32' and 0 < len(data) <= 1048576 * 4 and len(data) % 4 == 0,
            'Direct FRAME pixels must use bounded float32 storage')
    for (number,) in struct.iter_unpack('<f', data):
        require(math.isfinite(number) and 0 <= number <= 65535 and number.is_integer(),
                'Direct FRAME pixels are not exact uint16 values in float32 storage')


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
    require(type(context) is dict and context.get('schema_version') == 1 and context.get('status') == 'tracked_fourier' and
            set(context) == {'schema_version', 'status', 'original_operation', 'request_id', 'normalized_args',
                             'result_version', 'result', 'source_offset_xy', 'postprocessing'} and
            context.get('result_version') == 2 and type(context.get('request_id')) is str and
            _REQUEST_ID.fullmatch(context['request_id']) and type(context.get('normalized_args')) is list and
            len(context['normalized_args']) == 1 and _uint(context['normalized_args'][0], 1) and
            type(context.get('source_offset_xy')) is list and len(context['source_offset_xy']) == 2 and
            all(_uint(n) for n in context['source_offset_xy']) and type(context.get('postprocessing')) is list and
            len(context['postprocessing']) <= 32 and all(value in ('GMSImageProcessing::Negate', 'GMSImageProcessing::Abs',
                'GMSImageProcessing::Square', 'GMSImageProcessing::SmoothFilter', 'GMSImageProcessing::SobelFilter',
                'GMSImageProcessing::LaplaceFilter', 'GMSImageProcessing::SharpenFilter') for value in context['postprocessing']),
            'Invalid scientific creation context')
    producer = context['result']
    operation = context.get('original_operation')
    base = PIXEL_OPERATIONS.get(operation, operation)
    pixel = operation in PIXEL_OPERATIONS
    require(base in ('FFT', 'IFFT', 'REAL', 'IMAG', 'VENDOR_ARG', 'VENDOR_NORM') and
            type(producer) is dict and producer.get('backend') == 'digitalmicrograph-native' and
            producer.get('operation') == operation and
            producer.get('candidate_probe') is not True and producer.get('qualification') != 'NOT_QUALIFIED' and
            (producer.get('coordinate_mode') == 'pixel' if pixel else producer.get('coordinate_mode') in (None, 'physical')),
            'Scientific producer operation/qualification/coordinate mode mismatch')
    provenance, current, image = info.get('native_source_provenance'), info.get('source_metadata'), producer.get('image')
    require(type(provenance) is dict and type(current) is dict and type(image) is dict and
            _uint(producer.get('image_id'), 1) and image.get('id') == producer['image_id'] and
            producer.get('source_image_id') == context['normalized_args'][0] and
            image.get('dtype') == current.get('dtype') == info.get('dtype') == 'float32',
            'Scientific scalar source/producer identity mismatch')
    if info.get('source_image_id') == producer['image_id']:
        require(context['source_offset_xy'] == [0, 0] and not context['postprocessing'] and
                provenance.get('request_id') == context['request_id'] and provenance.get('operation') == operation and
                provenance.get('source_image_ids') == context['normalized_args'], 'Direct scientific creation identity mismatch')
    else:
        final = context['postprocessing'][-1] if context['postprocessing'] else None
        allowed = {'UNARY': ('GMSImageProcessing::Negate', 'GMSImageProcessing::Abs', 'GMSImageProcessing::Square'),
                   'FILTER': ('GMSImageProcessing::SmoothFilter', 'GMSImageProcessing::SobelFilter',
                              'GMSImageProcessing::LaplaceFilter', 'GMSImageProcessing::SharpenFilter')}
        current_op = PIXEL_OPERATIONS.get(provenance.get('operation'), provenance.get('operation'))
        require(provenance.get('request_id') != context['request_id'] and
                (current_op == 'CROP' or final in allowed.get(current_op, ())), 'Derived scientific creation identity mismatch')
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
    require((semantics.get('coordinate_mode') == 'pixel' and semantics.get('physical_calibration_applied') is False)
            if pixel else semantics.get('coordinate_mode') in (None, 'physical'),
            'Scientific pixel coordinates cannot claim a physical calibration')
    require(len(semantics.get('coordinate_axes', [])) == 2, 'Two scientific coordinate axes required')
    for dim, axis in enumerate(semantics['coordinate_axes']):
        original, source = image['calibration'][dim], current['calibration'][dim]
        shift = context['source_offset_xy'][dim]
        near = lambda actual, wanted, scale: _number(actual) and _number(wanted) and abs(actual-wanted) <= 8 * 2**-23 * max(abs(actual), abs(wanted), abs(scale), 2**-126)
        require(shift + source['size'] <= image['dm_dimensions'][dim] and source['scale'] == original['scale'] and
                source['unit'] == original['unit'] and near(source['origin'], original['origin']-shift, 1) and
                near(source['calibrated_value_at_pixel_zero'], original['calibrated_value_at_pixel_zero']+shift*original['scale'], original['scale']),
                'Scientific original source/native calibration mismatch')
        offset = context['source_offset_xy'][dim] + info['source_rect_xyxy'][dim]
        native = info['working_calibration_xy'][dim]
        grid = producer['frequency_grid']['axes'][dim] if frequency else producer['image']['calibration'][dim]
        step = (grid['cycles_per_pixel_step'] if pixel else grid['physical_frequency_step']) if frequency else (1 if pixel else grid['scale'])
        zero = grid['frequency_at_index_zero'] if frequency else (0 if pixel else grid['calibrated_value_at_pixel_zero'])
        unit = ('cycles_per_pixel' if frequency else 'pixel') if pixel else native['unit']
        if pixel and frequency:
            original = producer['image']['calibration'][dim]
            size = producer['image']['dm_dimensions'][dim]
            require(type(size) is int and 4 <= size <= 1024 and size & (size-1) == 0 and
                    all(_number(original.get(key)) for key in ('origin', 'scale', 'calibrated_value_at_pixel_zero')) and
                    original['scale'] != 0 and original.get('issue') not in ('invalid_calibration', 'invalid_calibration_and_unknown_units') and
                    producer['frequency_grid'].get('coordinate_mode') == 'pixel' and
                    grid.get('physical_frequency_step') is None and grid.get('unit') == 'cycles_per_pixel' and
                    grid.get('cycles_per_pixel_step') == 1 / size and grid.get('size') == size and
                    grid.get('dc_index') == size // 2 and grid.get('frequency_at_index_zero') == -.5 and
                    grid.get('native_calibration_scale') == original.get('scale') and
                    grid.get('native_calibration_unit') == original.get('unit') and
                    grid.get('native_calibrated_value_at_pixel_zero') == original.get('calibrated_value_at_pixel_zero') and
                    grid.get('native_calibration_dc_value') == original['calibrated_value_at_pixel_zero'] + size / 2 * original['scale'] and
                    grid.get('coordinate_rule') == 'f(i)=(i-dc_index)*cycles_per_pixel_step',
                    'Pixel Fourier grid must preserve native calibration separately from mathematical bins')
        mathematical = zero + offset * step
        require(axis.get('dm_dimension') == dim and axis.get('numpy_axis') == 1-dim and
                axis.get('size') == info['shape_yx'][1-dim] and axis.get('source_index_offset') == offset and
                axis.get('transform_size') == producer['image']['dm_dimensions'][dim] and
                axis.get('dc_index_in_roi') == (grid['dc_index']-offset if frequency else None) and
                axis.get('scale') == step and axis.get('unit') == unit and
                axis.get('calibrated_value_at_pixel_zero') == mathematical and
                axis.get('native_calibrated_value_at_pixel_zero') == native['calibrated_value_at_pixel_zero'] and
                axis.get('native_minus_mathematical_zero') == (None if pixel else native['calibrated_value_at_pixel_zero']-mathematical),
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
    frame = verify_frame_ancestry(info)
    require(manifest.get('frame_ancestry') == frame, 'Manifest frame ancestry differs from capture metadata')
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
            verify_frame_samples(raw, value)
            source = value.get('source', {})
            current = {key: value.get(key) for key in ('source', 'scientific_context', 'source_provenance', 'source_provenance_scope', 'coordinate_mapping_policy')}
            current['frame_ancestry'] = verify_frame_ancestry(value)
            require(current['frame_ancestry'] == frame, 'READ block belongs to a different original frame')
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
            contracts = {'FRAME': (2, 'native_frame_copy', 1), 'CROP': (5, 'image_crop', 1), 'UNARY': (2, 'native_image_operation', 1),
                         'BINARY': (3, 'native_image_operation', 1), 'FILTER': (2, 'native_image_operation', 1),
                         **{op: (1, 'native_fourier_operation', 2) for op in
                            ('FFT', 'IFFT', 'REAL', 'IMAG', 'VENDOR_ARG', 'VENDOR_NORM')}}
            contracts.update({name: contracts[base] for name, base in PIXEL_OPERATIONS.items()})
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
            if operation in PIXEL_OPERATIONS:
                require(source_record['result'].get('coordinate_mode') == 'pixel' and
                        (PIXEL_OPERATIONS[operation] == 'CROP' or source_record['result'].get('operation') == operation),
                        'Pixel source creation must retain its explicit coordinate mode and operation')
            if operation == 'FRAME':
                validate_frame_payload(source_record['result'], args)
                payload = {key: item for key, item in source_record['result'].items() if key not in ('retention', 'native_receipt')}
                require(frame is not None and frame['request_id'] == source_record['id'] and
                        frame['normalized_args'] == args and frame['result'] == payload,
                        'Original FRAME creation record differs from frozen ancestry')
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
                'frame_ancestry': frame,
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
