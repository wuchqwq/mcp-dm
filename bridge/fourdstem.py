#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Bounded, explicit-axis virtual detector arithmetic (Python 3.7 / NumPy 1.18).

This module never opens a DM file or guesses an axis, diffraction centre, beam
energy, camera length, or scattering angle. Coordinates refer to calibrated
pixel centres. A detector contains centres at r_inner <= radius < r_outer.
The continuous outer circle must fit inside the detector pixel-edge FOV.
No area weighting, diffraction alignment, COM correction or HAADF assignment
is implied by these geometric BF/ADF windows.
"""

import math
import numbers

import numpy as np


UINT64_MAX = 2 ** 64 - 1
MAX_DETECTORS = 64
_Q_UNITS = {"1/nm": "1/nm", "nm^-1": "1/nm", "nm-1": "1/nm",
            "1/um": "1/um", "um^-1": "1/um", "1/µm": "1/um",
            "1/angstrom": "1/angstrom", "1/A": "1/angstrom",
            "1/Å": "1/angstrom", "Å^-1": "1/angstrom"}


def _integer(value, name):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, numbers.Integral):
        raise ValueError("%s must be a strict integer" % name)
    return int(value)


def _finite(value, name):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, numbers.Real):
        raise ValueError("%s must be finite and real" % name)
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("%s must be finite and real" % name)
    return value


def _axes(axes, name):
    if not isinstance(axes, (tuple, list)) or len(axes) != 2:
        raise ValueError("%s must explicitly contain two NumPy axes" % name)
    result = [_integer(axis, name) for axis in axes]
    if any(axis < 0 or axis > 3 for axis in result) or len(set(result)) != 2:
        raise ValueError("%s must contain two distinct axes from 0 to 3" % name)
    return result


def _context(array_shape, calibration, scan_axes, detector_axes):
    if not isinstance(array_shape, (tuple, list)) or len(array_shape) != 4:
        raise ValueError("Exactly four source dimensions are required")
    shape = tuple(_integer(size, "shape size") for size in array_shape)
    if any(size <= 0 for size in shape):
        raise ValueError("Every source dimension must be nonempty")
    scan_axes = _axes(scan_axes, "scan_axes [scan_y,scan_x]")
    detector_axes = _axes(detector_axes, "detector_axes [q_y,q_x]")
    if len(set(scan_axes + detector_axes)) != 4:
        raise ValueError("Scan and detector axes must be distinct and cover all four dimensions")
    if not isinstance(calibration, (list, tuple)):
        raise ValueError("calibration must contain one explicit record per NumPy axis")
    records = {}
    for source in calibration:
        if not isinstance(source, dict):
            raise ValueError("Every calibration record must be an object")
        axis = _integer(source.get("numpy_axis"), "calibration numpy_axis")
        if axis not in range(4) or axis in records:
            raise ValueError("Calibration axes must uniquely cover the four NumPy axes")
        if source.get("size") is not None and _integer(source["size"], "calibration size") != shape[axis]:
            raise ValueError("Calibration size does not match source shape")
        scale = _finite(source.get("scale"), "calibration scale")
        zero = _finite(source.get("calibrated_value_at_pixel_zero"), "calibration physical zero")
        if scale == 0:
            raise ValueError("Calibration scale must be nonzero")
        last = zero + (shape[axis] - 1) * scale
        if not math.isfinite(last) or (shape[axis] > 1 and last == zero):
            raise ValueError("Calibration cannot resolve finite distinct pixel centres")
        unit = source.get("unit")
        if not isinstance(unit, str) or not unit.strip():
            raise ValueError("Every axis needs explicit units")
        low = min(zero, last) - abs(scale) * 0.5
        high = max(zero, last) + abs(scale) * 0.5
        if not all(math.isfinite(value) for value in (low, high)) or not low < high:
            raise ValueError("Calibration pixel-edge FOV is not finite and resolvable")
        record = {"numpy_axis": axis, "size": shape[axis], "unit": unit,
                  "scale": scale, "calibrated_value_at_pixel_zero": zero,
                  "last_pixel_centre": last, "pixel_edge_bounds": [low, high]}
        if source.get("dm_dimension") is not None:
            record["dm_dimension"] = _integer(source["dm_dimension"], "dm_dimension")
        records[axis] = record
    if len(records) != 4:
        raise ValueError("Explicit calibration is required for all four axes")
    q_units = [_Q_UNITS.get(records[axis]["unit"]) for axis in detector_axes]
    if None in q_units or q_units[0] != q_units[1]:
        raise ValueError("Detector axes require matching explicit reciprocal units; no angle conversion is assumed")
    if records[scan_axes[0]]["unit"] != records[scan_axes[1]]["unit"]:
        raise ValueError("Scan axes require matching explicit units")
    return shape, records, scan_axes, detector_axes, q_units[0]


def info(array_shape, calibration, scan_axes, detector_axes):
    """Describe an explicitly assigned 4D layout without reading source pixels."""
    shape, records, scan_axes, detector_axes, unit = _context(
        array_shape, calibration, scan_axes, detector_axes)
    return {"source_shape": list(shape), "scan_axes": scan_axes,
            "detector_axes": detector_axes,
            "scan_shape": [shape[axis] for axis in scan_axes],
            "detector_shape": [shape[axis] for axis in detector_axes],
            "scan_calibration": [records[axis] for axis in scan_axes],
            "detector_calibration": [records[axis] for axis in detector_axes],
            "q_unit": unit,
            "coordinate_convention": "physical_zero + pixel_index * scale; pixel centres",
            "scope": "Geometric virtual detector arithmetic; detector-angle/HAADF/phase identification unverified"}


def _bounds(bounds, shape, axes):
    if bounds is None:
        return [[0, shape[axis]] for axis in axes]
    if not isinstance(bounds, (list, tuple)) or len(bounds) != 2:
        raise ValueError("scan_bounds must be [[sy_start,sy_stop],[sx_start,sx_stop]]")
    result = []
    for bound, axis in zip(bounds, axes):
        if not isinstance(bound, (list, tuple)) or len(bound) != 2:
            raise ValueError("Each scan bound must be [start,stop]")
        start, stop = [_integer(value, "scan bound") for value in bound]
        if not 0 <= start < stop <= shape[axis]:
            raise ValueError("Scan bounds must be nonempty and inside source dimensions; never clamped")
        result.append([start, stop])
    return result


def _detector_specs(detectors, records, detector_axes):
    if not isinstance(detectors, (list, tuple)) or not 1 <= len(detectors) <= MAX_DETECTORS:
        raise ValueError("detectors must contain 1 to %s explicit windows" % MAX_DETECTORS)
    result = []
    labels = set()
    qy_record, qx_record = [records[axis] for axis in detector_axes]
    for detector in detectors:
        if not isinstance(detector, dict):
            raise ValueError("Every detector window must be an object")
        label = detector.get("label")
        if not isinstance(label, str) or not label.strip() or label in labels:
            raise ValueError("Detector labels must be nonempty unique strings")
        labels.add(label)
        centre = detector.get("center_q")
        if not isinstance(centre, (list, tuple)) or len(centre) != 2:
            raise ValueError("center_q must explicitly be [qx,qy] in reciprocal units")
        qx, qy = [_finite(value, "detector centre") for value in centre]
        inner = _finite(detector.get("r_inner"), "r_inner")
        outer = _finite(detector.get("r_outer"), "r_outer")
        if not 0 <= inner < outer:
            raise ValueError("Detector radii require 0 <= r_inner < r_outer")
        for centre_value, record in ((qx, qx_record), (qy, qy_record)):
            low, high = record["pixel_edge_bounds"]
            tolerance = 16 * np.finfo(np.float64).eps * max(abs(low), abs(high), abs(centre_value), outer)
            if centre_value - outer < low - tolerance or centre_value + outer > high + tolerance:
                raise ValueError("Detector outer circle is clipped by the calibrated pixel-edge FOV")
        result.append({"label": label, "center_q": [qx, qy], "r_inner": inner,
                       "r_outer": outer, "outer_circle_fully_contained": True})
    return result


def virtual_detectors(array, calibration, scan_axes, detector_axes, scan_bounds,
                      detectors, chunk_patterns=128, max_chunk_bytes=33554432):
    """Reduce bounded scan-row chunks; never coerce or copy a complete 4D cube.

    The caller supplies a read-only ndarray/memmap or bounded-slice provider
    with shape/dtype. Output maps are in requested [scan_y, scan_x] order.
    Unsigned and nonnegative signed integers use exact uint64 sums, with a
    conservative dtype-based overflow check before any source read. Floating
    sources use float64 arithmetic and require finite values throughout the
    selected scan ROI. max_chunk_bytes budgets explicit working allocations
    including maps, masks, mean-DP buffers and worst-case per-chunk copies;
    it excludes the source mapping and NumPy/runtime internal allocator costs.
    """
    shape, records, scan_axes, detector_axes, unit = _context(
        tuple(array.shape), calibration, scan_axes, detector_axes)
    bounds = _bounds(scan_bounds, shape, scan_axes)
    specs = _detector_specs(detectors, records, detector_axes)
    dtype = np.dtype(array.dtype)
    if dtype.kind not in "uif" or dtype.itemsize > 8:
        raise ValueError("Only real integer or float sources of at most 64 bits are supported")
    integer_source = dtype.kind in "ui"
    chunk_patterns = _integer(chunk_patterns, "chunk_patterns")
    max_chunk_bytes = _integer(max_chunk_bytes, "max_chunk_bytes")
    if chunk_patterns <= 0 or max_chunk_bytes <= 0:
        raise ValueError("Chunk limits must be positive")
    ny, nx = [stop - start for start, stop in bounds]
    qny, qnx = [shape[axis] for axis in detector_axes]
    q_pixels, patterns = qny * qnx, ny * nx
    if integer_source:
        maximum = int(np.iinfo(dtype).max)
        if maximum * q_pixels > UINT64_MAX or maximum * patterns > UINT64_MAX:
            raise ValueError("Integer dtype/shape could overflow exact uint64 sums")
    # Budget before masks, coordinate arrays, outputs, reduction buffers or
    # source reads. 6 DP-sized float64 buffers conservatively cover coordinate
    # generation, distances, reduction, mean accumulation and final division.
    fixed_bytes = ((len(specs) + 1) * patterns * 8 +
                   (len(specs) + 1) * q_pixels + 6 * q_pixels * 8 +
                   (qny + qnx) * 8)
    # One raw source block plus one worst-case masked-index copy; float
    # conversion and its masked copy are additionally allowed for float input.
    bytes_per_pattern = 2 * q_pixels * dtype.itemsize + (0 if integer_source else 16 * q_pixels) + 64
    affordable = (max_chunk_bytes - fixed_bytes) // bytes_per_pattern
    if affordable < 1:
        raise ValueError("Memory budget cannot hold fixed outputs and one bounded diffraction pattern")
    effective = min(chunk_patterns, nx, int(affordable))
    qy_record, qx_record = [records[axis] for axis in detector_axes]
    qy = qy_record["calibrated_value_at_pixel_zero"] + np.arange(qny, dtype=np.float64) * qy_record["scale"]
    qx = qx_record["calibrated_value_at_pixel_zero"] + np.arange(qnx, dtype=np.float64) * qx_record["scale"]
    masks = []
    for spec in specs:
        radius = np.hypot(qy[:, None] - spec["center_q"][1], qx[None, :] - spec["center_q"][0])
        mask = (radius >= spec["r_inner"]) & (radius < spec["r_outer"])
        count = int(np.count_nonzero(mask))
        if count == 0:
            raise ValueError("Detector %s selects no diffraction pixel centres" % spec["label"])
        spec["selected_pixels"] = count
        spec["q_unit"] = unit
        spec["boundary_rule"] = "r_inner <= radius < r_outer; pixel centres; no area weighting"
        masks.append(mask)
    del radius
    accumulator_dtype = np.uint64 if integer_source else np.float64
    maps = {spec["label"]: np.zeros((ny, nx), dtype=accumulator_dtype) for spec in specs}
    total = np.zeros((ny, nx), dtype=accumulator_dtype)
    mean_sum = np.zeros((qny, qnx), dtype=accumulator_dtype)
    remaining_axes = [axis for axis in range(4) if axis != scan_axes[0]]
    transpose = [remaining_axes.index(axis) for axis in [scan_axes[1]] + detector_axes]
    reads = 0
    largest_read = 0
    sy0, sy1 = bounds[0]
    sx0, sx1 = bounds[1]
    with np.errstate(over="ignore", invalid="ignore"):
        for sy in range(sy0, sy1):
            for sx in range(sx0, sx1, effective):
                stop = min(sx + effective, sx1)
                selectors = [slice(None)] * 4
                selectors[scan_axes[0]] = sy
                selectors[scan_axes[1]] = slice(sx, stop)
                # np.asarray is deliberately applied only after bounded slicing.
                block = np.asarray(array[tuple(selectors)]).transpose(transpose)
                if block.shape != (stop - sx, qny, qnx) or block.dtype != dtype:
                    raise ValueError("Source slice provider returned unexpected shape or dtype")
                reads += 1
                largest_read = max(largest_read, int(block.nbytes))
                if integer_source and dtype.kind == "i" and np.any(block < 0):
                    raise ValueError("Negative signed integer intensities cannot be summed into uint64")
                if not integer_source:
                    if not np.isfinite(block).all():
                        raise ValueError("Selected scan ROI contains NaN or infinite intensities")
                    block = np.asarray(block, dtype=np.float64)
                output_slice = (sy - sy0, slice(sx - sx0, stop - sx0))
                total[output_slice] = np.sum(block, axis=(1, 2), dtype=accumulator_dtype)
                for spec, mask in zip(specs, masks):
                    maps[spec["label"]][output_slice] = np.sum(block[:, mask], axis=1, dtype=accumulator_dtype)
                mean_sum += np.sum(block, axis=0, dtype=accumulator_dtype)
    if not integer_source and (not np.isfinite(mean_sum).all() or not np.isfinite(total).all() or
                               any(not np.isfinite(value).all() for value in maps.values())):
        raise ValueError("Float64 accumulation overflowed to a nonfinite result")
    mean_dp = mean_sum.astype(np.float64) / float(patterns)
    scan_calibration = []
    for axis, (start, stop) in zip(scan_axes, bounds):
        record = dict(records[axis])
        record.update({"source_size": shape[axis], "size": stop - start,
                       "source_start": start, "source_stop": stop,
                       "source_calibrated_value_at_pixel_zero": records[axis]["calibrated_value_at_pixel_zero"],
                       "calibrated_value_at_pixel_zero": records[axis]["calibrated_value_at_pixel_zero"] + start * records[axis]["scale"]})
        record["last_pixel_centre"] = record["calibrated_value_at_pixel_zero"] + (record["size"] - 1) * record["scale"]
        record["pixel_edge_bounds"] = [min(record["calibrated_value_at_pixel_zero"], record["last_pixel_centre"]) - abs(record["scale"]) / 2,
                                       max(record["calibrated_value_at_pixel_zero"], record["last_pixel_centre"]) + abs(record["scale"]) / 2]
        scan_calibration.append(record)
    return {"maps": maps, "total_counts": total, "mean_dp": mean_dp, "sum_dp_counts": mean_sum,
            "source_shape": list(shape), "source_dtype": str(dtype),
            "scan_axes": scan_axes, "detector_axes": detector_axes,
            "scan_bounds": bounds, "scan_shape": [ny, nx],
            "scan_calibration": scan_calibration,
            "detector_calibration": [records[axis] for axis in detector_axes],
            "detector_metadata": specs, "q_unit": unit,
            "sum_arithmetic": "exact uint64" if integer_source else "float64, finite ROI, rounding dependent on reduction order",
            "mean_dp_arithmetic": "uint64 pixel sums then float64 division" if integer_source else "float64 pixel sums and division",
            "chunking": {"requested_patterns": chunk_patterns, "effective_max_patterns": effective,
                         "read_count": reads, "largest_source_read_bytes": largest_read,
                         "max_chunk_bytes": max_chunk_bytes, "estimated_fixed_bytes": fixed_bytes,
                         "estimated_max_working_bytes": fixed_bytes + effective * bytes_per_pattern,
                         "source_mapping_excluded_from_budget": True,
                         "numpy_internal_allocator_costs_excluded_from_budget": True},
            "scope": "Geometric virtual detector windows; no alignment, COM correction, angular calibration or HAADF assignment"}


class _CanonicalReaderSource(object):
    """Adapt one bounded native reader to the same reduction kernel."""
    def __init__(self, shape, dtype, read_patterns):
        self.shape = tuple(shape)
        self.dtype = np.dtype(dtype)
        self.read_patterns = read_patterns

    def __getitem__(self, selectors):
        sy, scan_x, qy, qx = selectors
        if not isinstance(sy, int) or not isinstance(scan_x, slice) or scan_x.step is not None or \
                qy != slice(None) or qx != slice(None):
            raise ValueError("Native pattern reader requires canonical bounded scan-row slices")
        return self.read_patterns(sy, scan_x.start, scan_x.stop)


def virtual_detectors_from_reader(shape, dtype, read_patterns, calibration,
                                  scan_axes, detector_axes, scan_bounds, detectors,
                                  chunk_patterns=128, max_chunk_bytes=33554432):
    """Use a native bounded reader callback(sy, x0, x1) with the same kernel.

    The callback must return an array of shape [x1-x0,q_y,q_x] and the declared
    dtype, in canonical detector order. Scan indices are original source pixel
    indices. This initial callback API requires source scan axes [0,1] and
    detector axes [2,3]; array/memmap input supports all explicit permutations.
    A callback is never invoked before validation and the working-memory budget
    establish the maximum requested number of patterns.
    """
    if _axes(scan_axes, "scan_axes") != [0, 1] or _axes(detector_axes, "detector_axes") != [2, 3]:
        raise ValueError("Native reader currently requires canonical scan_axes [0,1], detector_axes [2,3]")
    if not callable(read_patterns):
        raise ValueError("read_patterns must be a bounded callable(sy,x0,x1)")
    source = _CanonicalReaderSource(shape, dtype, read_patterns)
    result = virtual_detectors(source, calibration, scan_axes, detector_axes,
                               scan_bounds, detectors, chunk_patterns, max_chunk_bytes)
    result["source_access"] = "bounded native reader callback(sy,x0,x1); canonical axes"
    return result
