"""Read-only bridge to existing schema-1 native scientific captures.

This module never imports DigitalMicrograph, submits a native request, changes
an array, or interprets a display PNG as scientific data. Hashes establish the
internal consistency of saved evidence, not the truth of a mutable live image.
The explicit source_mode is a user's declaration; inverse-looking unit text
cannot turn an untracked image into an FFT.
"""
import copy
import hashlib
import io
import json
import math
from pathlib import Path
import re

import numpy as np

from tools.verify_native_region import verify as verify_region
from tools.verify_native_region import verify_science, verify_frame_ancestry, verify_frame_samples, PIXEL_OPERATIONS


MAX_NPY_BYTES = 16 * 1024 * 1024
MAX_METADATA_BYTES = 1024 * 1024
MAX_POINTS = 128
MAX_BLOCKS = 512
_HASH = re.compile(r"[a-f0-9]{64}\Z")
_SESSION = re.compile(r"[a-f0-9]{32}\Z")
_ID = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")


class CaptureError(ValueError):
    """Saved scientific input failed a bounded consistency check."""


def _require(value, message):
    if not value:
        raise CaptureError(message)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _read(path, limit):
    _require(path.is_file() and not path.is_symlink(), "Ordinary capture file required: " + path.name)
    _require(path.stat().st_size <= limit, "Capture file exceeds byte budget: " + path.name)
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    _require(len(raw) <= limit, "Capture file grew beyond byte budget: " + path.name)
    return raw


def _json(raw):
    def unique(pairs):
        value = {}
        for key, entry in pairs:
            _require(key not in value, "Duplicate JSON key")
            value[key] = entry
        return value
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=unique,
                          parse_constant=lambda token: (_ for _ in ()).throw(CaptureError("Nonfinite JSON")))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise CaptureError("Invalid UTF-8 JSON capture metadata") from error


def _uint(value, minimum=0):
    return type(value) is int and minimum <= value <= 0xffffffff


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _digest(value):
    return type(value) is str and _HASH.fullmatch(value) is not None


def _receipt(receipt, image_id, rect):
    _require(type(receipt) is dict, "Original native READ receipt required")
    _require(receipt.get("protocol") == "NB2" and receipt.get("state") == "completed" and
             receipt.get("original_operation") == "READ" and
             receipt.get("result_type") == "native_data_snapshot" and
             type(receipt.get("result_version")) is int and receipt["result_version"] == 1 and
             type(receipt.get("session")) is str and _SESSION.fullmatch(receipt["session"]) and
             type(receipt.get("id")) is str and _ID.fullmatch(receipt["id"]) and
             receipt["id"] == receipt.get("request_id") and
             receipt.get("normalized_args") == [image_id] + rect and
             all(_uint(value) for value in receipt.get("normalized_args", [])) and
             all(_uint(receipt.get(key), 1) for key in ("host_pid", "exec_tid", "worker_tid")) and
             receipt["exec_tid"] != receipt["worker_tid"] and
             not any(key in receipt for key in ("result", "error", "code")),
             "Native READ host/session/request/arguments/type identity mismatch")
    timings = receipt.get("timings_us")
    _require(type(timings) is dict and set(timings) == {"queue", "execute"} and
             all(type(value) is int and 0 <= value <= 2**53 - 1 for value in timings.values()),
             "Native READ timing identity missing")


def _npy(raw, info):
    # Parse and bound the header before any shape-based allocation. np.load is
    # deliberately avoided: frombuffer makes the result immutable bytes-backed.
    stream = io.BytesIO(raw)
    try:
        version = np.lib.format.read_magic(stream)
        _require(version in ((1, 0), (2, 0)), "Only scientific NPY v1/v2 is accepted; PNG is display-only")
        header = (np.lib.format.read_array_header_1_0 if version == (1, 0)
                  else np.lib.format.read_array_header_2_0)
        shape, fortran, dtype = header(stream)
    except (ValueError, TypeError, EOFError) as error:
        raise CaptureError("Invalid bounded scientific NPY header; PNG is display-only") from error
    _require(len(shape) == 2 and all(type(n) is int and 0 < n <= 4194304 for n in shape),
             "Two-dimensional positive NPY shape required")
    count = shape[0] * shape[1]
    expected = np.dtype("<u4" if info.get("dtype") == "uint32" else "<f4")
    _require(info.get("dtype") in ("float32", "uint32") and dtype == expected and not fortran and
             dtype.str in ("<u4", "<f4") and count <= (MAX_NPY_BYTES // 4) and
             type(info.get("shape_yx")) is list and all(type(n) is int for n in info["shape_yx"]) and
             list(shape) == info["shape_yx"] and len(raw) == stream.tell() + count * 4 and
             all(type(info.get(key)) is int for key in ("raw_bytes", "sample_count", "input_file_bytes")) and
             info.get("raw_bytes") == count * 4 and info.get("sample_count") == count and
             info.get("input_file_bytes") == len(raw), "NPY shape/dtype/order/length mismatch")
    array = np.frombuffer(raw, dtype=dtype, count=count, offset=stream.tell()).reshape(shape)
    _require(np.isfinite(array).all(), "Nonfinite captured scientific pixels")
    _require(_sha(array.tobytes(order="C")) == info.get("pixel_sha256"), "Pixel hash mismatch")
    return array


def _axes(info):
    source, rect, shape = info["source_metadata"], info["source_rect_xyxy"], info["shape_yx"]
    original, work = info.get("source_calibration_dm"), info.get("working_calibration_xy")
    _require(type(source.get("calibration")) is list and len(source["calibration"]) == 2 and
             original == [dict(axis, axis="x" if dim == 0 else "y")
                          for dim, axis in enumerate(source["calibration"])] and
             type(work) is list and len(work) == 2, "Source/capture coordinate axes missing")
    for dim, axis in enumerate(work):
        base, offset = original[dim], rect[dim]
        _require(type(axis) is dict and axis.get("axis") == ("x" if dim == 0 else "y") and
                 axis.get("dm_dimension") == base.get("dm_dimension") == dim and
                 axis.get("numpy_axis") == base.get("numpy_axis") == 1 - dim and
                 axis.get("size") == shape[1-dim] and base.get("size") == info["source_shape_yx"][1-dim] and
                 axis.get("source_offset") == offset and axis.get("source_origin") == base.get("origin") and
                 axis.get("source_calibrated_value_at_pixel_zero") == base.get("calibrated_value_at_pixel_zero") and
                 axis.get("scale") == base.get("scale") and axis.get("unit") == base.get("unit") and
                 type(axis.get("usable")) is bool and type(base.get("usable")) is bool,
                 "Axis order/source offset/signed calibration identity mismatch")
        numbers = base.get("issue") not in ("invalid_calibration", "invalid_calibration_and_unknown_units") and all(
            _finite(base.get(key)) for key in ("origin", "scale", "calibrated_value_at_pixel_zero")) and base["scale"] != 0
        known = type(base.get("unit")) is str and bool(base["unit"])
        _require(base["usable"] == axis["usable"] == (numbers and known), "Calibration usable flag is inconsistent")
        if numbers:
            _require(axis.get("origin") == base["origin"] - offset and
                     axis.get("calibrated_value_at_pixel_zero") == base["calibrated_value_at_pixel_zero"] + offset * base["scale"],
                     "Capture physical zero/origin does not include READ offset")
        else:
            _require(axis.get("origin") is None and axis.get("calibrated_value_at_pixel_zero") is None,
                     "Unavailable calibration cannot invent coordinates")
    _require(info.get("calibration_complete") is all(axis["usable"] for axis in work), "Calibration completeness mismatch")


def _fourier(info, analysis=True):
    """Validate mathematical bins against immutable creation fields, not labels."""
    context, semantics = info.get("scientific_context"), info.get("scientific_semantics", {})
    _require(type(context) is dict and context.get("schema_version") == 1 and
             context.get("status") == "tracked_fourier" and context.get("result_version") == 2 and
             set(context) == {'schema_version', 'status', 'original_operation', 'request_id', 'normalized_args',
                              'result_version', 'result', 'source_offset_xy', 'postprocessing'} and
             PIXEL_OPERATIONS.get(context.get("original_operation"), context.get("original_operation")) in
             ("REAL", "IMAG", "VENDOR_ARG", "VENDOR_NORM") and
             type(context.get("request_id")) is str and _ID.fullmatch(context["request_id"]) and
             type(context.get("normalized_args")) is list and len(context["normalized_args"]) == 1 and
             all(_uint(value) for value in context["normalized_args"]) and
             type(context.get("source_offset_xy")) is list and len(context["source_offset_xy"]) == 2 and
             all(_uint(value) for value in context["source_offset_xy"]) and
             type(context.get('postprocessing')) is list and len(context['postprocessing']) <= 32 and
             all(value in ('GMSImageProcessing::Negate', 'GMSImageProcessing::Abs', 'GMSImageProcessing::Square',
                           'GMSImageProcessing::SmoothFilter', 'GMSImageProcessing::SobelFilter',
                           'GMSImageProcessing::LaplaceFilter', 'GMSImageProcessing::SharpenFilter')
                 for value in context['postprocessing']) and
             info["dtype"] == "float32", "FFT requires tracked, unprocessed native Fourier scalar creation; no unit-label inference")
    producer, provenance = context.get("result", {}), info.get("native_source_provenance")
    image, grid = producer.get("image", {}), producer.get("frequency_grid", {})
    representations = {"REAL": "real_component", "IMAG": "imaginary_component", "VENDOR_ARG": "phase_radians",
                       "VENDOR_NORM": "squared_magnitude"}
    operation = context["original_operation"]
    base_operation = PIXEL_OPERATIONS.get(operation, operation)
    pixel = operation in PIXEL_OPERATIONS
    frequency = grid is not None
    if analysis:
        _require(frequency and context['postprocessing'] == [] and base_operation != 'VENDOR_ARG',
                 "FFT analysis requires an unprocessed native frequency scalar; image mode is the generic pixel entry")
    _require(producer.get("backend") == "digitalmicrograph-native" and producer.get("operation") == operation and
             producer.get("source_image_id") == context["normalized_args"][0] and
             _uint(producer.get("image_id"), 1) and image.get("id") == producer["image_id"] and
             image.get("dtype") == "float32" and producer.get("representation") == representations[base_operation] and
             producer.get('candidate_probe') is not True and producer.get('qualification') != 'NOT_QUALIFIED' and
             (producer.get('coordinate_mode') == 'pixel' if pixel else producer.get('coordinate_mode') in (None, 'physical')) and
             producer.get("centering") == ('fftshift_data' if frequency else 'spatial_origin_zero') and
             producer.get("normalization") == "inherited_parent_transform" and
             producer.get("transform_signs") == {"forward": "+", "inverse": "-"} and
             producer.get("source_spatial_origin_used") is False and producer.get("intensity_calibration_applied") is False and
             producer.get("inverse_restores_source_origin") is False and producer.get("source_write_requested") is False and
             producer.get("snapshot_atomic") is False and type(provenance) is dict and
             ((type(grid) is dict and grid.get("native_calibration_has_half_bin_offset") is True and
               type(grid.get("axes")) is list and len(grid["axes"]) == 2) if frequency else grid is None) and
             type(image.get("dm_dimensions")) is list and len(image["dm_dimensions"]) == 2 and
             type(image.get("calibration")) is list and len(image["calibration"]) == 2,
             "Invalid native Fourier producer/grid identity")
    if info["source_image_id"] == producer["image_id"]:
        _require(context["source_offset_xy"] == [0, 0] and provenance.get("request_id") == context["request_id"] and
                 provenance.get("operation") == operation and provenance.get('source_image_ids') == context['normalized_args'] and
                 context['postprocessing'] == [], "Direct Fourier source/creation mismatch")
    else:
        current_op = PIXEL_OPERATIONS.get(provenance.get('operation'), provenance.get('operation'))
        scalar_steps = {'UNARY': ('GMSImageProcessing::Negate', 'GMSImageProcessing::Abs', 'GMSImageProcessing::Square'),
                        'FILTER': ('GMSImageProcessing::SmoothFilter', 'GMSImageProcessing::SobelFilter',
                                   'GMSImageProcessing::LaplaceFilter', 'GMSImageProcessing::SharpenFilter')}
        final_step = context['postprocessing'][-1] if context['postprocessing'] else None
        _require(provenance.get('request_id') != context['request_id'] and
                 (current_op == 'CROP' or final_step in scalar_steps.get(current_op, ())),
                 'Fourier descendant must retain a distinct matching crop or scalar-processing identity')
    for dim in range(2):
        axis = grid['axes'][dim] if frequency else None
        native, size = image["calibration"][dim], image["dm_dimensions"][dim]
        # Only explicit v2 Fourier records reach here. Historical v1 records
        # remain ineligible; an enlarged mathematical grid never proves a live
        # operator or host qualification by itself.
        _require(type(size) is int and 4 <= size <= 1024 and size & (size - 1) == 0 and
                 all(_finite(native.get(key)) for key in ('origin', 'scale', 'calibrated_value_at_pixel_zero')) and
                 native['scale'] != 0 and native.get('issue') not in ('invalid_calibration', 'invalid_calibration_and_unknown_units'),
                 'Invalid original native Fourier numeric calibration')
        if frequency:
            _require(
                 axis.get("size") == native.get("size") == size and axis.get("dm_dimension") == dim and
                 axis.get("dc_index") == size // 2 and axis.get("cycles_per_pixel_step") == 1 / size and
                 ((grid.get('coordinate_mode') == 'pixel' and axis.get('physical_frequency_step') is None and
                   axis.get('unit') == 'cycles_per_pixel' and axis.get('native_calibration_scale') == native.get('scale') and
                   axis.get('native_calibration_unit') == native.get('unit')) if pixel else
                  (_finite(axis.get("physical_frequency_step")) and axis["physical_frequency_step"] != 0 and
                   axis["physical_frequency_step"] == native.get("scale") and axis.get("unit") == native.get("unit"))) and
                 axis.get("frequency_at_index_zero") == -size / 2 * (1 / size if pixel else native["scale"]) and
                 native.get("origin") == (size + 1) / 2 and
                 axis.get("native_calibrated_value_at_pixel_zero") == native.get("calibrated_value_at_pixel_zero") and
                 axis.get("native_calibration_dc_value") == native["calibrated_value_at_pixel_zero"] + size / 2 * native["scale"] and
                 axis.get("coordinate_rule") == ("f(i)=(i-dc_index)*cycles_per_pixel_step" if pixel else "f(i)=(i-dc_index)*physical_frequency_step"),
                 "Native Fourier mathematical frequency grid mismatch")
        else:
            _require(native.get('size') == size and native.get('dm_dimension') == dim and
                     native['origin'] == 0 and native['calibrated_value_at_pixel_zero'] == 0,
                     'Native inverse spatial component origin mismatch')
        source = info["source_metadata"]["calibration"][dim]
        offset = context["source_offset_xy"][dim]
        # Same binary32 native offset tolerance as the existing strict Node
        # validator; this never changes the mathematical grid or caller input.
        near = lambda actual, wanted, scale: _finite(actual) and abs(actual-wanted) <= 8 * 2**-23 * max(abs(actual), abs(wanted), abs(scale), 2**-126)
        _require(offset + source["size"] <= size and source["scale"] == native["scale"] and source["unit"] == native["unit"] and
                 near(source["origin"], native["origin"] - offset, 1) and
                 near(source["calibrated_value_at_pixel_zero"], native["calibrated_value_at_pixel_zero"] + offset*native["scale"], native["scale"]),
                 "Fourier crop offset/native calibration mismatch")
    # Existing schema-1 verifier independently recomputes cumulative crop+READ
    # offsets and distinguishes raw native half-bin labels from true FFT bins.
    verify_science(info)


class Capture:
    def __init__(self, path, array, metadata, provenance, hashes, source_mode):
        self.path = path
        self.array = array
        self.metadata = copy.deepcopy(metadata)
        self.provenance = provenance
        self.source_roi = list(metadata["source_rect_xyxy"])
        self.source_mode = source_mode
        self.coordinate_axes = copy.deepcopy(metadata["scientific_semantics"]["coordinate_axes"] if source_mode == "fft" or
                                             source_mode == 'image' and metadata.get('scientific_semantics', {}).get('status') == 'tracked_fourier'
                                             else metadata["working_calibration_xy"])
        self._hashes = hashes

    def source_to_local_xy(self, points):
        """Source pixel centers -> capture pixel centers; never clip or round."""
        _require(type(points) in (list, tuple) and 0 < len(points) <= MAX_POINTS, "One to 128 explicit source XY points required")
        rect = self.source_roi
        result = []
        for point in points:
            _require(type(point) in (list, tuple) and len(point) == 2 and all(_finite(v) for v in point), "Finite XY pixel centers required")
            x, y = point
            _require(rect[0] <= x <= rect[2]-1 and rect[1] <= y <= rect[3]-1,
                     "Point is outside captured pixel-center bounds; no clipping")
            result.append([x-rect[0], y-rect[1]])
        return result

    def frequency_axes_cycles_per_nm(self):
        _require(self.source_mode == "fft", "Only tracked native FFT supplies mathematical frequency axes")
        _require(self.metadata['scientific_semantics'].get('coordinate_mode') != 'pixel',
                 'Pixel FFT has no physical calibration; its axes remain cycles_per_pixel')
        # This closed table is a unit conversion, never an encoding or lineage
        # guess. A caller's radians/length calibration belongs to measurement.
        factors = {"1/nm": 1.0, "1/angstrom": 10.0, "1/Angstrom": 10.0,
                   "1/Å": 10.0, "1/Å": 10.0, "1/pm": 1000.0, "1/um": .001,
                   "1/µm": .001, "1/μm": .001, "1/m": 1e-9}
        output = []
        for axis in self.coordinate_axes:
            _require(axis["unit"] in factors, "Unsupported explicitly recorded FFT reciprocal unit: " + str(axis["unit"]))
            factor = factors[axis["unit"]]
            normalized = dict(axis, source_unit=axis["unit"], unit="1/nm", conversion_to_cycles_per_nm=factor,
                              frequency_convention="cycles_per_length; |g|=1/d",
                              scale=axis["scale"]*factor,
                              calibrated_value_at_pixel_zero=axis["calibrated_value_at_pixel_zero"]*factor)
            output.append(normalized)
        return output

    def assert_unchanged(self):
        """Recheck every consumed file after external analysis, without repair."""
        for name, expected in self._hashes.items():
            limit = MAX_NPY_BYTES if name == "input.npy" else MAX_METADATA_BYTES
            _require(_sha(_read(self.path / name, limit)) == expected, "Capture changed during external analysis: " + name)


def _synthetic(capture, raw, info, manifest, expected_capture_id, expected_session, expected_host_pid):
    """The existing mock capture2d schema, explicitly synthetic end to end."""
    _require(expected_session is None and expected_host_pid is None,
             "Synthetic captures cannot claim a native session or host PID")
    _require(info.get("synthetic") is True and manifest.get("capture_consistency") == "synthetic mock only" and
             info.get("schema_version") == manifest.get("schema_version") == 1 and
             manifest.get("state") == "captured" and type(info.get("capture_id")) is str and
             _SESSION.fullmatch(info["capture_id"]) and info["capture_id"] == manifest.get("capture_id") and
             info.get("input_file") == "input.npy" and
             _sha(raw["input.npy"]) == info.get("input_sha256") == manifest.get("input_sha256") and
             _sha(_canonical(info)) == manifest.get("input_metadata_sha256") and
             info.get("native_receipt") is None and info.get("scientific_context") is None and
             manifest.get("pixel_capture_atomic") is False,
             "Explicit existing schema-1 synthetic mock capture required")
    _require(expected_capture_id is None or info["capture_id"] == expected_capture_id, "Expected capture ID mismatch")
    shape, rect, source_shape = info.get("shape_yx"), info.get("source_rect_xyxy"), info.get("source_shape_yx")
    _require(type(shape) is list and len(shape) == 2 and all(_uint(n, 1) for n in shape) and
             type(rect) is list and len(rect) == 4 and all(_uint(n) for n in rect) and
             [rect[3]-rect[1], rect[2]-rect[0]] == shape and
             type(source_shape) is list and len(source_shape) == 2 and all(_uint(n, 1) for n in source_shape) and
             rect[2] <= source_shape[1] and rect[3] <= source_shape[0] and
             info.get("source_image_id") == manifest.get("source_image_id") and _uint(info["source_image_id"], 1) and
             manifest.get("source_shape_yx") == source_shape and manifest.get("source_rect_xyxy") == rect and
             manifest.get("source_dtype") == info.get("dtype") == "float32", "Synthetic source/shape/ROI identity mismatch")
    _require(shape[0]*shape[1] <= MAX_NPY_BYTES//4, "Synthetic pixel budget exceeded")
    # Older generic schema-1 captures have no redundant raw/pixel fields. Validate
    # their NPY header against actual existing fields without backfilling files.
    normalized = dict(info, raw_bytes=shape[0]*shape[1]*4, sample_count=shape[0]*shape[1],
                      input_file_bytes=len(raw["input.npy"]))
    stream = io.BytesIO(raw["input.npy"])
    try:
        version = np.lib.format.read_magic(stream)
        header = { (1, 0): np.lib.format.read_array_header_1_0,
                   (2, 0): np.lib.format.read_array_header_2_0 }.get(version)
        _require(header is not None, "Synthetic capture requires scientific NPY")
        header(stream)
    except (ValueError, TypeError, EOFError) as error:
        raise CaptureError("Invalid synthetic scientific NPY") from error
    normalized["pixel_sha256"] = _sha(raw["input.npy"][stream.tell():])
    array = _npy(raw["input.npy"], normalized)
    source_axes, axes = info.get("source_calibration_dm"), info.get("working_calibration_xy")
    _require(type(source_axes) is list and len(source_axes) == 2 and type(axes) is list and len(axes) == 2,
             "Synthetic source/capture axes missing")
    for dim, (original, axis) in enumerate(zip(source_axes, axes)):
        name = "x" if dim == 0 else "y"
        _require(original.get("axis") == axis.get("axis") == name and
                 original.get("dm_dimension") == dim and original.get("numpy_axis") == 1-dim and
                 original.get("size") == source_shape[1-dim] and axis.get("size") == shape[1-dim] and
                 all(_finite(original.get(key)) for key in ("origin", "scale", "calibrated_value_at_pixel_zero")) and
                 original["scale"] != 0 and axis.get("scale") == original["scale"] and
                 axis.get("unit") == original.get("unit") and type(axis.get("unit")) is str and
                 axis.get("calibrated_value_at_pixel_zero") == original["calibrated_value_at_pixel_zero"] + rect[dim]*original["scale"],
                 "Synthetic explicit source/capture coordinates mismatch")
    hashes = {name: _sha(value) for name, value in raw.items()}
    provenance = {"capture_id": info["capture_id"], "capture_files_sha256": dict(hashes),
                  "source_image_id": info["source_image_id"], "source_rect_xyxy": rect,
                  "source_shape_yx": source_shape, "source_mode_declared": "synthetic_diffraction",
                  "synthetic": True, "actual_dm": False, "native_session": None, "native_host_pid": None,
                  "native_read_request_ids": [], "dm_called_by_companion": False,
                  "pixel_capture_atomic": False, "live_source_reobserved": False,
                  "capture_verification_scope": "existing synthetic mock capture2d files only; no DM or native execution"}
    result = Capture(capture, array, info, provenance, hashes, "synthetic_diffraction")
    result.assert_unchanged()
    return result


def load_capture(path, source_mode, expected_capture_id=None, expected_session=None, expected_host_pid=None):
    """Validate an existing native READ capture, bounded to a 16 MiB NPY.

    Accepts the existing single-READ and complete native_chunked_read layouts.
    source_mode='image' validates a generic saved pixel input without declaring
    diffraction or admitting it to a physical analysis. No live software is called.
    expected_* values bind independently saved identities when available.
    """
    try:
        _require(source_mode in ("image", "diffraction", "fft", "synthetic_diffraction"),
                 "Explicit source_mode must be image, diffraction, fft or synthetic_diffraction")
        capture = Path(path)
        _require(capture.is_dir() and not capture.is_symlink(), "Existing ordinary capture directory required")
        capture = capture.resolve(strict=True)
        raw = {name: _read(capture / name, MAX_NPY_BYTES if name == "input.npy" else MAX_METADATA_BYTES)
               for name in ("input.npy", "input.json", "capture.json")}
        info, manifest = _json(raw["input.json"]), _json(raw["capture.json"])
        _require(type(info) is dict and type(manifest) is dict, "Object capture metadata required")
        if source_mode == "synthetic_diffraction":
            return _synthetic(capture, raw, info, manifest, expected_capture_id, expected_session, expected_host_pid)
        _require(type(info) is dict and type(manifest) is dict and
                 type(info.get("schema_version")) is int and type(manifest.get("schema_version")) is int and
                 info["schema_version"] == manifest["schema_version"] == 1 and
                 manifest.get("state") == "captured" and type(info.get("capture_id")) is str and
                 _SESSION.fullmatch(info["capture_id"]) and info["capture_id"] == manifest.get("capture_id") and
                 info.get("input_file") == "input.npy" and
                 _sha(raw["input.npy"]) == info.get("input_sha256") == manifest.get("input_sha256") and
                 _sha(_canonical(info)) == manifest.get("input_metadata_sha256") and
                 info.get("axes") == ["y", "x"] and info.get("axis_roles") == [
                     {"numpy_axis": 0, "dm_dimension": 1, "role": "y"}, {"numpy_axis": 1, "dm_dimension": 0, "role": "x"}] and
                 info.get("byte_order") == "little" and info.get("array_order") == "C" and
                 info.get("intensity_calibration_applied") is False and
                 info.get("intensity_calibration") == {"origin": None, "scale": None, "unit": None, "status": "NOT_READ"} and
                 info.get("pixel_capture_atomic") is False and info.get("dm_file_save") is False,
                 "Complete native schema-1 capture/file/metadata/axis identity required")
        if "input_metadata_file_sha256" in manifest:
            _require(manifest["input_metadata_file_sha256"] == _sha(raw["input.json"]), "Raw metadata file hash mismatch")
        _require(expected_capture_id is None or expected_capture_id == info["capture_id"], "Expected capture ID mismatch")
        array = _npy(raw["input.npy"], info)
        _require(manifest.get("pixel_sha256") == info["pixel_sha256"], "Manifest pixel hash mismatch")
        source, rect = info.get("source_metadata"), info.get("source_rect_xyxy")
        _require(type(source) is dict and _uint(info.get("source_image_id"), 1) and
                 type(rect) is list and len(rect) == 4 and all(_uint(value) for value in rect) and
                 rect[2] > rect[0] and rect[3] > rect[1] and
                 [rect[3]-rect[1], rect[2]-rect[0]] == list(array.shape) and
                 type(info.get("source_shape_yx")) is list and len(info["source_shape_yx"]) == 2 and
                 all(_uint(n, 1) for n in info["source_shape_yx"]) and
                 rect[2] <= info["source_shape_yx"][1] and rect[3] <= info["source_shape_yx"][0] and
                 manifest.get("source_image_id") == source.get("id") == info["source_image_id"] and
                 source.get("shape") == info["source_shape_yx"] and
                 source.get("dm_dimensions") == list(reversed(source["shape"])) and source.get("ndim") == 2 and
                 source.get("pixels") == source["shape"][0]*source["shape"][1] and
                 source.get("dtype") == info["dtype"] and source.get("packing_style") == 1 and
                 source.get("data_type_code") == (11 if info["dtype"] == "uint32" else 2) and
                 (info["dtype"] != "uint32" or (source.get("is_integer") is True and source.get("is_unsigned") is True)) and
                 manifest.get("source_rect_xyxy") == rect,
                 "Source image/ROI/dtype/shape identity mismatch")
        _axes(info)
        frame = verify_frame_ancestry(info)
        _require(manifest.get('frame_ancestry') == frame, "Manifest original frame identity mismatch")
        verify_frame_samples(array, info)
        hashes = {name: _sha(value) for name, value in raw.items()}
        mode = info.get("capture_mode")
        if mode == "native_chunked_read":
            blocks = manifest.get("blocks")
            _require(type(blocks) is list and 0 < len(blocks) <= MAX_BLOCKS, "Bounded completed block evidence required")
            for index, block in enumerate(blocks):
                name = "read-{}.json".format(index)
                evidence = _read(capture / name, 128*1024)
                hashes[name] = _sha(evidence)
                value = _json(evidence)
                request = block.get("request", {})
                _receipt(value.get("native_receipt"), info["source_image_id"], request.get("args", [])[1:])
            if info.get("native_source_creation_record") is not None:
                hashes["source-creation.json"] = _sha(_read(capture / "source-creation.json", 128*1024))
            evidence = verify_region(capture, expected_pid=expected_host_pid, expected_session=expected_session)
            session, pid = manifest["native_session"], manifest["host_pid"]
            requests = [block["request"]["id"] for block in blocks]
        else:
            _require(mode is None, "Only native 2D READ captures are accepted, not profile/histogram/PNG")
            receipt = info.get("native_receipt")
            _receipt(receipt, info["source_image_id"], rect)
            _require(array.size <= 16384 and _sha(_canonical(receipt)) == info.get("native_receipt_sha256") == manifest.get("native_receipt_sha256") and
                     manifest.get("native_session") == receipt["session"] and
                     manifest.get("native_request_id") == receipt["id"] and
                     manifest.get("source_shape_yx") == info["source_shape_yx"] and
                     manifest.get("source_dtype") == info["dtype"] and
                     manifest.get("source_data_type_code") == source["data_type_code"] and
                     _digest(info.get("saved_snapshot_sha256")) and manifest.get("saved_snapshot_sha256") == info["saved_snapshot_sha256"] and
                     manifest.get("calibration_before") == manifest.get("calibration_after") == info["source_calibration_dm"] and
                     info.get("external_saved_response_encoding") is True,
                     "Original single READ receipt/manifest/calibration/hash mismatch")
            verify_science(info)
            session, pid, requests = receipt["session"], receipt["host_pid"], [receipt["id"]]
            evidence = {"scope": "saved single native READ evidence only; no live-source or operator qualification"}
        _require(type(session) is str and _SESSION.fullmatch(session) and _uint(pid, 1), "Native session/PID invalid")
        _require(expected_session is None or session == expected_session, "Expected session mismatch")
        _require(expected_host_pid is None or pid == expected_host_pid, "Expected host PID mismatch")
        if source_mode == "fft":
            _fourier(info)
            _require(info["scientific_semantics"]["representation"] != "squared_magnitude" or bool(np.all(array >= 0)),
                     "Native squared magnitude cannot contain negative values")
        elif source_mode == 'image':
            if (info.get('scientific_context') or {}).get('status') == 'tracked_fourier':
                _fourier(info, analysis=False)
                _require(info['scientific_semantics']['representation'] != 'squared_magnitude' or bool(np.all(array >= 0)),
                         'Native squared magnitude cannot contain negative values')
            elif info.get('scientific_context') is None:
                source_operation = (info.get('native_source_provenance') or {}).get('operation')
                _require(PIXEL_OPERATIONS.get(source_operation, source_operation) not in
                         ('FFT', 'IFFT', 'REAL', 'IMAG', 'VENDOR_ARG', 'VENDOR_NORM'),
                         'Recorded Fourier source requires its saved coordinate/representation context')
        else:
            _require(info.get("scientific_context") is None and
                     info.get("scientific_semantics", {}).get("status") == "not_recorded" and
                     PIXEL_OPERATIONS.get((info.get("native_source_provenance") or {}).get("operation"),
                                          (info.get("native_source_provenance") or {}).get("operation")) not in
                     ("FFT", "IFFT", "REAL", "IMAG", "VENDOR_ARG", "VENDOR_NORM"),
                     "Diffraction declaration conflicts with recorded Fourier/unresolved lineage")
        provenance = {"capture_id": info["capture_id"], "capture_files_sha256": dict(hashes),
                      "source_image_id": info["source_image_id"], "source_shape_yx": info["source_shape_yx"],
                      "source_rect_xyxy": rect, "native_session": session, "native_host_pid": pid,
                      "native_read_request_ids": requests, "source_mode_declared": source_mode,
                      "scientific_context": info.get("scientific_context"), "scientific_semantics": info.get("scientific_semantics"),
                      "frame_ancestry": frame,
                      "source_intensity_calibration_applied": False, "pixel_capture_atomic": False,
                      "synthetic": False, "actual_dm": None,
                      "live_source_reobserved": False, "dm_called_by_companion": False,
                      "capture_verification_scope": evidence["scope"]}
        result = Capture(capture, array, info, provenance, hashes, source_mode)
        result.assert_unchanged()
        return result
    except CaptureError:
        raise
    except (KeyError, TypeError, ValueError, IndexError, AttributeError, OSError, OverflowError) as error:
        raise CaptureError("Malformed or unavailable scientific capture: " + str(error)) from error
