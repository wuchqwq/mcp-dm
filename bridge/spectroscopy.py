#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Small, explicit-axis spectroscopy operations (Python 3.7 / NumPy 1.18).

These are synthetic-tested arithmetic primitives, not EDS/EELS identification,
background subtraction or quantification. An energy-labelled axis must be
chosen explicitly; a multidimensional DM file is never assumed to be a spectrum.
All bounds use original NumPy-axis order and half-open integer index intervals.
"""

import math
import numbers

import numpy as np


MAX_OUTPUT_CHANNELS = 16384
MAX_OUTPUT_MAP_ELEMENTS = 262144
SAFE_INTEGER = 2 ** 53


def _integer(value, name):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, numbers.Integral):
        raise ValueError("%s must be a strict integer (booleans/floats are invalid)" % name)
    return int(value)


def _finite(value, name):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, numbers.Real):
        raise ValueError("%s must be a finite real number" % name)
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("%s must be a finite real number" % name)
    return result


def _shape(shape):
    if not isinstance(shape, (list, tuple)) or not 1 <= len(shape) <= 3:
        raise ValueError("Only 1D spectra, 2D line spectra or 3D spectrum images are supported; 4D diffraction is not spectroscopy")
    result = tuple(_integer(size, "shape size") for size in shape)
    if any(size <= 0 for size in result):
        raise ValueError("Every source dimension must be nonempty")
    return result


def _axis_records(calibration, shape):
    if not isinstance(calibration, (list, tuple)):
        raise ValueError("calibration must be a list of explicit NumPy-axis records")
    records = {}
    for record in calibration:
        if not isinstance(record, dict):
            raise ValueError("Every calibration record must be an object")
        axis = _integer(record.get("numpy_axis"), "calibration numpy_axis")
        if not 0 <= axis < len(shape):
            raise ValueError("Calibration numpy_axis is outside source dimensions")
        if axis in records:
            raise ValueError("Exactly one calibration record per NumPy axis is allowed")
        if record.get("size") is not None:
            size = _finite(record["size"], "calibration size")
            if size != shape[axis]:
                raise ValueError("Calibration size does not match source shape")
        # Retained descriptive fields must also be JSON-safe. Do not pass
        # arbitrary numpy scalar/object metadata through into tool results.
        record = dict(record)
        if record.get("dm_dimension") is not None:
            record["dm_dimension"] = _integer(record["dm_dimension"], "calibration dm_dimension")
        if record.get("axis") is not None and not isinstance(record["axis"], str):
            raise ValueError("calibration axis label must be a string or null")
        if record.get("unit") is not None and not isinstance(record["unit"], str):
            raise ValueError("calibration unit must be a string or null")
        records[axis] = record
    return records


def _spatial_calibration(record, axis, size, start, stop):
    """Return known cropped calibration; never manufacture a missing origin."""
    result = {"numpy_axis": axis, "source_size": size, "size": stop - start}
    if record is None:
        result.update({"available": False, "reason": "No calibration record for this spatial axis"})
        return result
    result["dm_dimension"] = record.get("dm_dimension")
    result["axis"] = record.get("axis")
    result["unit"] = record.get("unit")
    try:
        scale = _finite(record.get("scale"), "spatial scale")
        source_zero = _finite(record.get("calibrated_value_at_pixel_zero"), "spatial physical zero")
        if scale == 0:
            raise ValueError("Spatial scale is zero")
        cropped_zero = source_zero + start * scale
        if not math.isfinite(cropped_zero):
            raise ValueError("Cropped spatial physical zero is not finite")
        result.update({"available": True, "scale": scale,
                       "source_calibrated_value_at_pixel_zero": source_zero,
                       "calibrated_value_at_pixel_zero": cropped_zero,
                       "formula": "coordinate[j] = calibrated_value_at_pixel_zero + j * scale"})
    except ValueError as exc:
        result.update({"available": False, "reason": str(exc)})
    # DM's raw 'origin' is deliberately not copied: a cropped axis requires its
    # physical zero, and raw origin conventions differ between file/API paths.
    return result


def _context(shape, calibration, energy_axis, spatial_bounds, max_elements):
    shape = _shape(shape)
    energy_axis = _integer(energy_axis, "energy_axis")
    if not 0 <= energy_axis < len(shape):
        raise ValueError("energy_axis must explicitly name a NumPy axis from 0 to ndim-1")
    max_elements = _integer(max_elements, "max_elements")
    if max_elements <= 0:
        raise ValueError("max_elements must be positive")
    records = _axis_records(calibration, shape)
    record = records.get(energy_axis)
    if record is None:
        raise ValueError("Exactly one calibration record matching energy_axis is required")
    unit = record.get("unit")
    if unit not in ("eV", "keV"):
        raise ValueError("Chosen energy axis must have explicit eV or keV units; axes/technique are never guessed")
    scale = _finite(record.get("scale"), "energy scale")
    zero = _finite(record.get("calibrated_value_at_pixel_zero"), "energy physical zero")
    if scale == 0:
        raise ValueError("Energy scale must be nonzero")
    factor = 1000.0 if unit == "keV" else 1.0
    step = scale * factor
    first = zero * factor
    last = (zero + (shape[energy_axis] - 1) * scale) * factor
    upper = max(first, last) + abs(step)
    if not all(math.isfinite(v) for v in (step, first, last, upper)):
        raise ValueError("Energy calibration overflows finite eV coordinates")
    if step == 0 or (shape[energy_axis] > 1 and first == last):
        raise ValueError("Energy calibration cannot resolve distinct channel centers in float64")
    spatial_axes = [axis for axis in range(len(shape)) if axis != energy_axis]
    if spatial_bounds is None:
        spatial_bounds = [[0, shape[axis]] for axis in spatial_axes]
    if not isinstance(spatial_bounds, (list, tuple)) or len(spatial_bounds) != len(spatial_axes):
        raise ValueError("spatial_bounds requires one [start,stop] pair for each remaining NumPy axis, in ascending order")
    slices = [slice(None)] * len(shape)
    spatial = []
    selected_shape = list(shape)
    spatial_count = 1
    for axis, bounds in zip(spatial_axes, spatial_bounds):
        if not isinstance(bounds, (list, tuple)) or len(bounds) != 2:
            raise ValueError("Each spatial bound must be [start,stop]")
        start = _integer(bounds[0], "spatial bound start")
        stop = _integer(bounds[1], "spatial bound stop")
        if not 0 <= start < stop <= shape[axis]:
            raise ValueError("Spatial bounds must be nonempty and inside source dimensions; bounds are never clamped")
        slices[axis] = slice(start, stop)
        selected_shape[axis] = stop - start
        spatial_count *= stop - start
        spatial.append({"numpy_axis": axis, "source_size": shape[axis], "start": start,
                        "stop": stop, "size": stop - start,
                        "calibration": _spatial_calibration(records.get(axis), axis, shape[axis], start, stop)})
    energy = {"numpy_axis": energy_axis, "dm_dimension": record.get("dm_dimension"),
              "input_unit": unit, "input_scale": scale, "input_pixel_zero": zero,
              "scale_eV": step, "pixel_zero_eV": first, "channel_count": shape[energy_axis],
              "first_center_eV": first, "last_center_eV": last,
              "min_center_eV": min(first, last), "max_center_eV": max(first, last),
              "window_upper_exclusive_limit_eV": upper,
              "formula": "E[i] = (input_pixel_zero + i * input_scale) * (1000 if input_unit == 'keV' else 1)"}
    source_axes = []
    for axis, size in enumerate(shape):
        if axis == energy_axis:
            cal = dict(energy)
        else:
            cal = _spatial_calibration(records.get(axis), axis, size, 0, size)
        source_axes.append({"numpy_axis": axis, "size": size,
                            "role": "energy" if axis == energy_axis else "spatial", "calibration": cal})
    info = {"source_shape": list(shape), "ndim": len(shape), "energy_axis": energy_axis,
            "energy_calibration": energy, "source_axes": source_axes, "spatial_axes": spatial,
            "selected_shape": selected_shape, "selected_elements": spatial_count * shape[energy_axis],
            "spatial_sample_count": spatial_count,
            "axis_convention": "energy_axis and spatial axes use NumPy array order, not DM dimension order",
            "bounds_semantics": "spatial [start,stop) indices; energy low <= channel center < high; original channel order retained",
            "experimental": True,
            "validation_scope": {"real_eds": "NOT_TESTED", "real_eels": "NOT_TESTED", "real_si": "NOT_TESTED", "synthetic_arithmetic": "TESTED"},
            "no_quantification_performed": True,
            "technique": "unspecified; no inference of EDS versus EELS"}
    return info, tuple(slices), max_elements


def _window(info, energy_window_eV):
    cal = info["energy_calibration"]
    n = cal["channel_count"]
    if energy_window_eV is None:
        start, stop = 0, n
        window = None
    else:
        if not isinstance(energy_window_eV, (list, tuple)) or len(energy_window_eV) != 2:
            raise ValueError("energy_window_eV must be [low,high]")
        low = _finite(energy_window_eV[0], "energy window low")
        high = _finite(energy_window_eV[1], "energy window high")
        if low >= high:
            raise ValueError("Energy window must satisfy low < high")
        if low < cal["min_center_eV"] or high > cal["window_upper_exclusive_limit_eV"]:
            raise ValueError("Energy window is outside channel-center coverage; upper exclusive bound may extend by one absolute channel step")
        # Binary search avoids allocating coordinates proportional to an
        # untrusted source dimension before the selected-work guard is applied.
        def coordinate(index):
            return (cal["input_pixel_zero"] + index * cal["input_scale"]) * (1000.0 if cal["input_unit"] == "keV" else 1.0)
        def ascending_lower_bound(value):
            lo, hi = 0, n
            while lo < hi:
                mid = (lo + hi) // 2
                index = mid if cal["scale_eV"] > 0 else n - 1 - mid
                if coordinate(index) < value:
                    lo = mid + 1
                else:
                    hi = mid
            return lo
        left, right = ascending_lower_bound(low), ascending_lower_bound(high)
        if cal["scale_eV"] > 0:
            start, stop = left, right
        else:
            start, stop = n - right, n - left
        window = [low, high]
    if start >= stop:
        raise ValueError("Energy window selects no channel centers")
    count = stop - start
    return start, stop, count, window


def spectrum_info(shape, calibration, energy_axis, spatial_bounds=None, max_elements=64000000):
    """Describe explicit axes without obtaining or allocating source pixels."""
    info, unused_slices, max_elements = _context(shape, calibration, energy_axis, spatial_bounds, max_elements)
    info["within_work_limit"] = info["selected_elements"] <= max_elements
    info["work_limit_elements"] = max_elements
    info["output_limits"] = {"channels": MAX_OUTPUT_CHANNELS, "map_elements": MAX_OUTPUT_MAP_ELEMENTS}
    return info


def _selection(shape, calibration, energy_axis, spatial_bounds, energy_window_eV, max_elements, output_kind):
    """One shape-only selection/limit implementation shared by both paths."""
    if output_kind not in ("spectrum", "map"):
        raise ValueError("output_kind must be 'spectrum' or 'map'")
    if output_kind == "map" and energy_window_eV is None:
        raise ValueError("integrate_window requires an explicit energy_window_eV")
    info, slices, max_elements = _context(shape, calibration, energy_axis, spatial_bounds, max_elements)
    start, stop, count, window = _window(info, energy_window_eV)
    work = info["spatial_sample_count"] * count
    if work > max_elements:
        raise ValueError("Selected work exceeds max_elements before source-array access or dtype conversion")
    if count > MAX_OUTPUT_CHANNELS:
        raise ValueError("Output exceeds 16384 channels; select a smaller energy window")
    if output_kind == "map" and info["spatial_sample_count"] > MAX_OUTPUT_MAP_ELEMENTS:
        raise ValueError("Integrated output exceeds 262144 map elements; select a smaller spatial region")
    slices = list(slices)
    slices[info["energy_axis"]] = slice(start, stop)
    info["selected_shape"][info["energy_axis"]] = count
    info["selected_elements"] = work
    info["energy_window_eV"] = window
    info["selected_channel_range"] = [start, stop]
    return info, tuple(slices), start, stop, count


def validate_selection(shape, calibration, energy_axis, spatial_bounds=None, energy_window_eV=None, max_elements=64000000, output_kind="spectrum"):
    """Validate selected work/output limits before fetching source pixels.

    Only dimensions, calibration and scalar bounds are inspected. No coordinate
    vector or source array is allocated, even for huge metadata-only shapes.
    The same private selection routine is used when processing actual arrays.
    """
    info, unused_slices, unused_start, unused_stop, unused_count = _selection(
        shape, calibration, energy_axis, spatial_bounds, energy_window_eV, max_elements, output_kind)
    return info


def _selected(array, calibration, energy_axis, spatial_bounds, window, max_elements, output_kind):
    # Shape/guards precede dtype conversion or any full selected-array copy.
    if not isinstance(array, np.ndarray):
        raise ValueError("array must be a NumPy array; implicit full-array conversion is refused")
    info, slices, start, stop, count = _selection(
        array.shape, calibration, energy_axis, spatial_bounds, window, max_elements, output_kind)
    if array.dtype.kind not in ("i", "u", "f"):
        raise ValueError("Only real numeric arrays are supported; RGB/structured/object/complex/bool arrays are refused")
    view = array[slices]
    if not np.isfinite(view).all():
        raise ValueError("Selected source data contains NaN or Inf")
    if array.dtype.kind in ("i", "u"):
        lo, hi = int(view.min()), int(view.max())
        largest = max(abs(lo), abs(hi))
        if largest > SAFE_INTEGER:
            raise ValueError("Integer source magnitude exceeds exact float64 safe integer limit 2**53")
        reduction_count = info["spatial_sample_count"] if output_kind == "spectrum" else count
        # Sufficient bound on every accumulator, including mixed-sign data.
        # Conservatively reject if exactness cannot be guaranteed without an
        # expensive arbitrary-precision reduction of the full source.
        if largest * reduction_count > SAFE_INTEGER:
            raise ValueError("Integer accumulation cannot be guaranteed within exact float64 limit 2**53 (conservative max-absolute-value bound)")
    indices = np.arange(start, stop, dtype=np.int64)
    cal = info["energy_calibration"]
    energies = (cal["input_pixel_zero"] + indices.astype(np.float64) * cal["input_scale"]) * (1000.0 if cal["input_unit"] == "keV" else 1.0)
    if not np.isfinite(energies).all() or (count > 1 and not np.all(np.diff(energies) * np.sign(cal["scale_eV"]) > 0)):
        raise ValueError("Energy calibration cannot resolve finite, ordered channel centers in float64")
    return view, info, indices.tolist(), energies.tolist()


def _result_finite(values):
    if not np.isfinite(values).all():
        raise ValueError("Float64 reduction overflowed or produced a nonfinite result")
    return values.tolist()


def extract_spectrum(array, calibration, energy_axis, spatial_bounds=None, reduction="sum", energy_window_eV=None, max_elements=64000000):
    """Reduce only selected spatial axes; preserve raw intensity per channel."""
    if reduction not in ("sum", "mean"):
        raise ValueError("reduction must be 'sum' or 'mean'")
    view, info, indices, energies = _selected(array, calibration, energy_axis, spatial_bounds, energy_window_eV, max_elements, "spectrum")
    axes = tuple(axis for axis in range(view.ndim) if axis != info["energy_axis"])
    with np.errstate(over="ignore", invalid="ignore"):
        if axes:
            result = np.sum(view, axis=axes, dtype=np.float64)
            if reduction == "mean":
                result = result / float(info["spatial_sample_count"])
        else:
            result = view.astype(np.float64)
    info.update({"channel_indices": indices, "energy_eV": energies, "intensity": _result_finite(result),
                 "reduction": reduction,
                 "method": "float64 spatial %s for each selected original channel; no background subtraction" % reduction,
                 "intensity_semantics": "raw source intensity per channel; counts versus density unknown; no bin-width, dose or cross-section conversion"})
    return info


def integrate_window(array, calibration, energy_axis, energy_window_eV, spatial_bounds=None, max_elements=64000000):
    """Sum selected channel values, without multiplying by energy-bin width."""
    if energy_window_eV is None:
        raise ValueError("integrate_window requires an explicit energy_window_eV")
    view, info, indices, energies = _selected(array, calibration, energy_axis, spatial_bounds, energy_window_eV, max_elements, "map")
    with np.errstate(over="ignore", invalid="ignore"):
        result = np.sum(view, axis=info["energy_axis"], dtype=np.float64)
    output_axes = []
    for output_axis, source in enumerate(info["spatial_axes"]):
        record = dict(source["calibration"])
        record["source_numpy_axis"] = source["numpy_axis"]
        record["output_numpy_axis"] = output_axis
        record["source_index_range"] = [source["start"], source["stop"]]
        output_axes.append(record)
    info.update({"selected_channel_indices": indices, "selected_energy_eV": energies,
                 "integrated_values": _result_finite(result), "output_shape": list(result.shape), "output_axes": output_axes,
                 "method": "float64 sum of selected channel values; low <= center < high; no trapezoidal integration and no bin-width multiplier",
                 "intensity_semantics": "sum of raw source channel intensities; counts versus density unknown; no background subtraction, dose or cross-section conversion"})
    return info
