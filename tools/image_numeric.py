"""Bounded raw-array observation for the explicit external image provider.

NumPy sampling and reductions; never Canvas brightness, a DM fallback or a
scientific interpretation of undocumented intensity units.
"""
import math
import hashlib
import platform
from pathlib import Path
from collections import OrderedDict
import numpy as np
HELPER_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


class NumericError(ValueError):
    code = 'INVALID_ARGUMENT'


def require(ok, text):
    if not ok:
        raise NumericError(text)


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


class NumericReader:
    def __init__(self):
        self.cache = OrderedDict()

    def operand(self, workspace, request):
        # These existing methods check immutable journals/manifests and payload
        # SHA-256 on each request. The cache does not waive identity validation.
        parent, directory, context = workspace.measurement_operand(request.get('object_id'))
        require(parent['kind'] in ('frame', 'view', 'fft', 'fft_view'), 'Numeric observation requires one saved scientific plane, not a comparison or screenshot')
        digest = parent.get('files_sha256', {}).get('data.npy')
        require(digest is not None, 'Scientific NPY required')
        key = (parent['object_id'], digest)
        if key not in self.cache:
            values = np.load(directory / 'data.npy', allow_pickle=False)
            require(values.ndim == 2 and values.size <= 4194304 and values.nbytes <= 64*1024*1024 and
                    values.dtype in tuple(np.dtype(name) for name in ('uint8','uint16','uint32','int8','int16','int32','float32','float64','complex128')) and
                    values.flags.c_contiguous and list(values.shape) == parent.get('shape_yx') and str(values.dtype) == parent.get('dtype'),
                    'Scientific plane exceeds numeric observation budget or disagrees with saved shape/dtype')
            require(np.isfinite(values).all(), 'Nonfinite scientific values')
            values.flags.writeable = False
            self.cache[key] = values
            while len(self.cache) > 2 or sum(v.nbytes for v in self.cache.values()) > 128*1024*1024:
                self.cache.popitem(last=False)
        self.cache.move_to_end(key)
        values = self.cache[key]
        spectral = parent['kind'] in ('fft', 'fft_view')
        panel = parent.get('panels', [None])[0] if len(parent.get('panels', [])) == 1 else None
        if spectral:
            bounds = [0, 0, values.shape[1], values.shape[0]]
            space = 'frequency_cycles_per_pixel'
            source = parent.get('spectrum_object_id', parent['object_id'])
        else:
            bounds = panel['source_rect_xyxy'] if parent['kind'] == 'view' and panel else [0, 0, values.shape[1], values.shape[0]]
            source = panel['source_object_id'] if parent['kind'] == 'view' and panel else parent['object_id']
            space = 'source_array_indices' if parent.get('array_domain') in ('frequency', 'reciprocal') else 'source_pixels'
        require(request.get('coordinate_space', space) == space, 'coordinate_space must match the saved scientific array domain')
        component = request.get('component', 'raw')
        require(component in ('raw', 'real', 'imag', 'amplitude', 'power'), 'Unsupported numeric component')
        require((values.dtype.kind == 'c' and component != 'raw') or (values.dtype.kind != 'c' and component == 'raw'), 'Complex data requires explicit real/imag/amplitude/power; scalar data uses raw')
        grid = dict(source_grid_object_id=source, shape_yx=list(values.shape), dtype=str(values.dtype),
                    array_sha256=digest, source_rect_xyxy=None if spectral else bounds, coordinate_space=space)
        return dict(parent=parent, values=values, bounds=bounds, spectral=spectral, coordinate_space=space,
                    component=component, scientific_grid_identity=grid, user_context=context)


def components(values, component):
    if component == 'raw':
        result = values
    elif component == 'real':
        result = values.real
    elif component == 'imag':
        result = values.imag
    elif component == 'amplitude':
        result = np.abs(values)
    else:
        result = np.square(np.abs(values))
    require(np.isfinite(result).all(), 'Numeric component is nonfinite')
    return result


def sample(operand, points):
    require(type(points) is list and 1 <= len(points) <= 4096 and all(type(p) is list and len(p) == 2 and all(finite(x) for x in p) for p in points), 'Bounded finite coordinate pairs required')
    positions = np.asarray(points, dtype=np.float64)
    h, w = operand['values'].shape
    if operand['spectral']:
        require(np.all(positions >= [-(w//2)/w, -(h//2)/h]) and
                np.all(positions <= [(w-1-w//2)/w, (h-1-h//2)/h]),
                'Coordinates must be inside saved array centres; no clipping')
        indices = positions * [w, h] + [w//2, h//2]
    else:
        bounds = operand['bounds']
        require(np.all(positions >= bounds[:2]) and np.all(positions <= [bounds[2]-1, bounds[3]-1]),
                'Coordinates must be inside saved array centres; no clipping')
        indices = positions - operand['bounds'][:2]
    # NumPy index sampling, with explicit deterministic ties and no interpolation.
    nearest = np.floor(indices + .5).astype(np.int64)
    require(np.all(nearest >= 0) and np.all(nearest < [w, h]), 'Nearest sample lies outside saved array; no clipping')
    raw = operand['values'][nearest[:, 1], nearest[:, 0]]
    result = components(raw, operand['component'])
    sampled = ((nearest - [w//2, h//2]) / [w, h] if operand['spectral'] else nearest + operand['bounds'][:2])
    return nearest, sampled, result


def common(operand):
    return dict(component=operand['component'], dtype=str(operand['values'].dtype),
                coordinate_space=operand['coordinate_space'], scientific_grid_identity=operand['scientific_grid_identity'],
                xy_calibration=operand['parent'].get('xy_calibration'),
                user_context=operand['user_context'],
                intensity_semantics=('raw stored scalar values; intensity unit not inferred' if operand['component'] == 'raw' else
                                     'complex FFT '+operand['component']+'; not display brightness or electron counts'),
                intensity_calibration_applied=False,
                software_provenance=dict(python=platform.python_version(), numpy=np.__version__, numeric_helper_sha256=HELPER_SHA256),
                computation='explicit external NumPy; DM not called', dm_called=False)


def probe(workspace, request, reader=None):
    require(type(request.get('points')) is list and 1 <= len(request['points']) <= 64, 'Probe batch must contain 1..64 points')
    operand = (reader or NumericReader()).operand(workspace, request)
    indices, sampled, values = sample(operand, request['points'])
    return dict(object_id=request['object_id'], kind='probe', **common(operand),
                sampling=dict(interpolation='nearest', line_width=1, tie_rule='floor(array_index+0.5)'),
                samples=[dict(point=p, array_index_xy=i.tolist(), sampled_coordinate_xy=q.tolist(), value=v.item())
                         for p, i, q, v in zip(request['points'], indices, sampled, values)])


def statistics(workspace, request):
    operand = NumericReader().operand(workspace, request)
    bounds = operand['bounds']; spectral = operand['spectral']
    require(not ('rect' in request and 'frequency_rect' in request), 'Choose source rect or FFT frequency_rect, never both')
    require('rect' not in request if spectral else 'frequency_rect' not in request, 'ROI edges must match the scientific coordinate domain')
    rect = request.get('frequency_rect' if spectral else 'rect', bounds)
    require(type(rect) is list and len(rect) == 4 and all(type(v) is int for v in rect) and
            bounds[0] <= rect[0] < rect[2] <= bounds[2] and bounds[1] <= rect[1] < rect[3] <= bounds[3], 'ROI must be valid half-open scientific array/source edges; no clipping')
    x0, y0, x1, y1 = [v-bounds[i % 2] for i, v in enumerate(rect)]
    values = components(operand['values'][y0:y1, x0:x1], operand['component'])
    floating = values.astype(np.float64)
    result = dict(sample_count=int(values.size), dtype=str(values.dtype), minimum=float(np.min(floating)),
                  maximum=float(np.max(floating)), mean=float(np.mean(floating)), stddev=float(np.std(floating, ddof=0)))
    require(all(math.isfinite(v) for k, v in result.items() if k != 'dtype'), 'Statistics exceed finite binary64 range')
    return dict(**common(operand), statistics=result, standard_deviation='population; NumPy ddof=0; binary64 reductions',
                **({'frequency_rect': rect} if spectral else {'source_rect_xyxy': rect}))


def profile(workspace, request):
    require(request.get('line_width', 1) == 1 and type(request.get('line_width', 1)) is int, 'First profile supports exactly one pixel/bin width')
    require(request.get('interpolation', 'nearest') == 'nearest', 'Only explicit nearest-neighbor sampling is supported')
    operand = NumericReader().operand(workspace, request)
    points = request.get('points')
    require(type(points) is list and len(points) == 2, 'Profile requires exactly two endpoints')
    sample(operand, points)  # validate endpoints before allocating the line
    delta = np.asarray(points[1], dtype=np.float64)-points[0]
    index_delta = delta * [operand['values'].shape[1], operand['values'].shape[0]] if operand['spectral'] else delta
    length = float(np.linalg.norm(delta)); pixel_length = float(np.linalg.norm(index_delta))
    require(pixel_length > 0, 'Distinct profile endpoints required')
    count = request.get('sample_count', int(math.ceil(pixel_length))+1)
    require(type(count) is int and 2 <= count <= 4096, 'Profile sample_count must be 2..4096; oversized lines require an explicit bounded sample count')
    coordinates = np.linspace(points[0], points[1], count).tolist()
    indices, sampled, values = sample(operand, coordinates)
    physical = None; unit = None
    record = operand['parent'].get('xy_calibration')
    if record and record.get('status') == 'active' and record.get('xy_scale'):
        scale = record['xy_scale']; sx, sy = scale['x'], scale['y']
        physical_length = math.hypot(delta[0]/sx, delta[1]/sy) if operand['spectral'] else math.hypot(delta[0]*sx, delta[1]*sy)
        require(math.isfinite(physical_length), 'Calibrated profile distance is nonfinite')
        unit = ('cycles/' if operand['spectral'] else '')+scale['unit']
        physical = np.linspace(0, physical_length, count).tolist()
    samples = dict(coordinates_xy=coordinates, indices_xy=indices.tolist(), sampled_coordinates_xy=sampled.tolist(),
                   distance=np.linspace(0, length, count).tolist(), value=values.tolist(), physical_distance=physical)
    result = dict(**common(operand), points=points, samples=samples, length=length,
                  distance_unit='cycles/pixel' if operand['spectral'] else 'pixel', physical_distance_unit=unit,
                  sampling=dict(interpolation='nearest', line_width=1, sample_count=count, tie_rule='floor(array_index+0.5)',
                                path='evenly spaced requested centre coordinates; nearest saved array sample, endpoints included'),
                  physical_distance_semantics='path distance in the calibrated coordinate domain; reciprocal-axis distance is not d-spacing')
    return result, values
