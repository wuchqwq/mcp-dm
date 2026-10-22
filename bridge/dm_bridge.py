#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""dm_bridge.py -- X-ray into DigitalMicrograph's analysis engine.

Scope: POST-ACQUISITION ANALYSIS ONLY. No stage, no beam, no detector
commands. The point is to use what DigitalMicrograph is uniquely good at:
reading dm3/dm4 with full calibration + metadata fidelity, and running
DM's own processing on the data.

Runs INSIDE DigitalMicrograph's supported embedded Python environment
and serves newline-delimited JSON over 127.0.0.1:8765.

Start inside DM:  Python workspace -> open this file -> Run Script
Offline test:     set DM_BRIDGE_MOCK=1 && python dm_bridge.py

Python 3.7 compatible on purpose (no walrus, no builtin generics).
"""

import json
import ctypes
import ipaddress
import hashlib
import importlib.util
import math
import numbers
import os
import shutil
import socket
import sys
import tempfile
import time
import traceback
import uuid

HOST = os.environ.get("DM_BRIDGE_HOST", "127.0.0.1")
PORT = int(os.environ.get("DM_BRIDGE_PORT", "8765"))
MOCK = os.environ.get("DM_BRIDGE_MOCK", "0") == "1"
VERBOSE = os.environ.get("DM_BRIDGE_VERBOSE", "1") == "1"
BRIDGE_VERSION = "0.6.0"

MAX_TAG_NODES = 4000
# GetNumArray maps shared DM memory. This cap limits selected working regions,
# because dtype conversion, finite filtering and FFT allocate new arrays.
MAX_TRANSFER_PIXELS = int(os.environ.get("DM_MCP_MAX_PIXELS", "64000000"))
MAX_NATIVE_OPEN_BYTES = int(os.environ.get("DM_MCP_MAX_NATIVE_OPEN_BYTES", "536870912"))
MAX_REQUEST_BYTES = 4 * 1024 * 1024
MAX_TAG_VALUE_BYTES = 65536
IDLE_TIMEOUT = float(os.environ.get("DM_BRIDGE_IDLE_TIMEOUT", "3600"))
CLIENT_IDLE_TIMEOUT = float(os.environ.get("DM_BRIDGE_CLIENT_IDLE_TIMEOUT", "15"))
MAX_2D_CAPTURE_WORKING_BYTES = 256 * 1024 * 1024

# Conservative known real-scalar Gatan image types. Do not inspect pixels to
# infer unknown/complex/RGB types. Shared by listing and bounded 2D capture.
_DM_REAL_SCALAR_DTYPES = {
    1: "int16", 2: "float32", 6: "uint8", 7: "int32",
    9: "int8", 10: "uint16", 11: "uint32", 12: "float64",
}


def _native_scalar_dtype_name(code):
    if isinstance(code, bool) or not isinstance(code, numbers.Integral):
        return None
    return _DM_REAL_SCALAR_DTYPES.get(int(code))


try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None

DOCS = {
    "dm_script_reference": r"C:\ProgramData\Gatan\Documentation\Scripting_DigitalMicrograph.pdf",
    "python_api_reference": r"C:\ProgramData\Gatan\Documentation\PythonReference.pdf",
    "python_guide": r"C:\ProgramData\Gatan\Documentation\Python.pdf",
}


def log(msg):
    if VERBOSE:
        sys.stderr.write("[dm_bridge] " + str(msg) + "\n")
        sys.stderr.flush()


def _j(value):
    """Best-effort conversion of numpy / DM types into JSON-safe values."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_j(v) for v in value]
    if isinstance(value, dict):
        return dict((str(k), _j(v)) for k, v in value.items())
    if np is not None:
        if isinstance(value, np.generic):
            return _j(value.item())
        if isinstance(value, np.ndarray):
            return _j(value.tolist())
    return str(value)


def _num(v):
    v = _j(v)
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, (int, float)):
        return float(v)
    return None


def _arr(img):
    return np.asarray(img.GetNumArray())


def _rect_bounds(shape, rect):
    """Validate a half-open 2D ROI without reading pixels or changing input.

    Only None means the full frame. Explicit empty, noninteger, degenerate or
    out-of-bounds rectangles fail; there is no rounding or clipping mode.
    """
    if len(shape) != 2:
        raise ValueError("rect requires a two-dimensional image")
    h, w = [int(v) for v in shape]
    if h <= 0 or w <= 0:
        raise ValueError("rect requires a nonempty image")
    if rect is None:
        return [0, 0, w, h]
    if not isinstance(rect, (list, tuple)) or len(rect) != 4:
        raise ValueError("rect must be [x0,y0,x1,y1] with exclusive upper bounds")
    if any(isinstance(v, bool) or not isinstance(v, numbers.Integral) for v in rect):
        raise ValueError("rect coordinates must be integers, not booleans or rounded values")
    x0, y0, x1, y1 = [int(v) for v in rect]
    if x1 <= x0 or y1 <= y0:
        raise ValueError("rect must have positive width and height")
    if not (0 <= x0 < x1 <= w and 0 <= y0 < y1 <= h):
        raise ValueError("OUT_OF_BOUNDS: rect %r exceeds image [width=%d,height=%d]; no clipping"
                         % ([x0, y0, x1, y1], w, h))
    return [x0, y0, x1, y1]


def _rect(a, rect):
    """Return the strictly validated view and its effective source bounds."""
    used = _rect_bounds(a.shape, rect)
    x0, y0, x1, y1 = used
    return a[y0:y1, x0:x1], used


def _metadata_prefix_parts(prefix):
    """JSON Pointer tokens; also accept the documented slashless shorthand.

    None/empty selects the root; '/' selects a literal empty label. Do not
    strip whitespace or trailing separators, which can be actual tag labels.
    """
    if prefix is None or prefix == "":
        return []
    if not isinstance(prefix, str):
        raise ValueError("metadata prefix must be a string")
    if len(prefix.encode("utf-8")) > MAX_TAG_VALUE_BYTES:
        raise ValueError("metadata prefix exceeds the byte limit")
    raw = (prefix[1:] if prefix.startswith("/") else prefix).split("/")
    if len(raw) > 64:
        raise ValueError("metadata prefix exceeds 64 path segments")
    for part in raw:
        if any(c == "~" and (i + 1 == len(part) or part[i + 1] not in "01")
               for i, c in enumerate(part)):
            raise ValueError("metadata prefix has an invalid JSON Pointer escape")
    return [part.replace("~1", "/").replace("~0", "~") for part in raw]


def _classify(shape, ndim):
    if ndim == 2:
        return "image"
    if ndim == 3:
        return "stack_or_spectrum_image"
    if ndim == 1:
        return "spectrum_or_profile"
    return "%dD" % ndim


_SPECTROSCOPY_HELPER = None
_SPECTROSCOPY_CODE_SHA256 = None
_FOURDSTEM_HELPERS = {}
_ANALYSIS2D_HELPER = None


def _fourdstem_helper(name):
    if name not in ("dm4_header", "native_stream", "fourdstem"):
        raise ValueError("Unknown 4D-STEM helper")
    if name not in _FOURDSTEM_HELPERS:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), name + ".py")
        spec = importlib.util.spec_from_file_location("dm_mcp_" + name, path)
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        with open(path, "rb") as stream:
            digest = hashlib.sha256(stream.read()).hexdigest()
        _FOURDSTEM_HELPERS[name] = (helper, digest)
    return _FOURDSTEM_HELPERS[name][0]


def _spectroscopy_helper():
    global _SPECTROSCOPY_HELPER, _SPECTROSCOPY_CODE_SHA256
    if _SPECTROSCOPY_HELPER is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "spectroscopy.py")
        spec = importlib.util.spec_from_file_location("dm_mcp_spectroscopy", path)
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        with open(path, "rb") as stream:
            _SPECTROSCOPY_CODE_SHA256 = hashlib.sha256(stream.read()).hexdigest()
        _SPECTROSCOPY_HELPER = helper
    return _SPECTROSCOPY_HELPER


def _analysis2d_helper():
    global _ANALYSIS2D_HELPER
    if _ANALYSIS2D_HELPER is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "analysis2d_core.py")
        spec = importlib.util.spec_from_file_location("dm_mcp_analysis2d_core", path)
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        _ANALYSIS2D_HELPER = helper
    return _ANALYSIS2D_HELPER


class SpectroscopyMixin(object):
    """Read-only experimental spectroscopy shared by real and synthetic backends.

    Backend context returns a lazy array reader. Calibration/selection limits are
    checked before GetNumArray, and no spectrum-axis or detector type is guessed.
    """

    def _spectral_context_checked(self, image_id, energy_axis, spatial_bounds):
        if isinstance(image_id, bool) or not isinstance(image_id, int) or image_id < 0:
            raise ValueError("光谱接口要求显式非负整数 image_id，不使用 front")
        context = self._spectrum_context(image_id)
        helper = _spectroscopy_helper()
        helper.spectrum_info(context["shape"], context["calibration"], energy_axis,
                             spatial_bounds, max_elements=MAX_TRANSFER_PIXELS)
        return context, helper

    def _spectral_result(self, context, result):
        result.update({"id": context["id"], "name": context["name"],
                       "backend": self.name, "synthetic": self.name == "mock",
                       "source_file": context.get("source_file"),
                       "source_calibration": context["calibration"],
                       "source_intensity_unit": context.get("intensity_unit") or None,
                       "technique": "unclassified; no EDS/EELS identity inferred"})
        return result

    @staticmethod
    def _spectral_array(context):
        array = context["read_array"]()
        if list(array.shape) != context["shape"]:
            raise RuntimeError("DM 数组轴序/尺寸与维度元数据不一致；拒绝猜测能量轴")
        return array

    def spectrum_info(self, image_id, energy_axis, spatial_bounds=None):
        context, helper = self._spectral_context_checked(image_id, energy_axis, spatial_bounds)
        info = helper.spectrum_info(context["shape"], context["calibration"], energy_axis,
                                    spatial_bounds, max_elements=MAX_TRANSFER_PIXELS)
        return self._spectral_result(context, info)

    def spectrum(self, image_id, energy_axis, spatial_bounds=None, reduction="sum",
                 energy_window_eV=None):
        if reduction not in ("sum", "mean"):
            raise ValueError("reduction must be sum or mean")
        context, helper = self._spectral_context_checked(image_id, energy_axis, spatial_bounds)
        helper.validate_selection(context["shape"], context["calibration"], energy_axis,
                    spatial_bounds=spatial_bounds, energy_window_eV=energy_window_eV,
                    max_elements=MAX_TRANSFER_PIXELS, output_kind="spectrum")
        result = helper.extract_spectrum(self._spectral_array(context), context["calibration"],
                    energy_axis, spatial_bounds=spatial_bounds, reduction=reduction,
                    energy_window_eV=energy_window_eV, max_elements=MAX_TRANSFER_PIXELS)
        return self._spectral_result(context, result)

    def spectrum_integrate(self, image_id, energy_axis, energy_window_eV,
                           spatial_bounds=None):
        context, helper = self._spectral_context_checked(image_id, energy_axis, spatial_bounds)
        helper.validate_selection(context["shape"], context["calibration"], energy_axis,
                    spatial_bounds=spatial_bounds, energy_window_eV=energy_window_eV,
                    max_elements=MAX_TRANSFER_PIXELS, output_kind="map")
        result = helper.integrate_window(self._spectral_array(context), context["calibration"],
                    energy_axis, energy_window_eV, spatial_bounds=spatial_bounds,
                    max_elements=MAX_TRANSFER_PIXELS)
        return self._spectral_result(context, result)

    @staticmethod
    def _publish_spectral_file(source, destination):
        created = False
        try:
            with open(destination, "xb") as target:
                created = True
                with open(source, "rb") as stream:
                    shutil.copyfileobj(stream, target)
        except Exception:
            if created:
                os.remove(destination)
            raise

    def spectrum_export(self, image_id, energy_axis, path, spatial_bounds=None,
                        reduction="sum", energy_window_eV=None):
        path = os.path.abspath(path)
        if os.path.splitext(path)[1].lower() != ".csv":
            raise ValueError("光谱导出仅支持 .csv，列为 energy_eV,intensity；原始多维数据请另用 dm_export npy")
        sidecar = path + ".metadata.json"
        if os.path.lexists(path) or os.path.lexists(sidecar):
            raise FileExistsError("拒绝覆盖已有光谱 CSV 或 sidecar: %s" % path)
        spectrum = self.spectrum(image_id, energy_axis, spatial_bounds, reduction, energy_window_eV)
        folder = os.path.dirname(path)
        if not os.path.isdir(folder):
            os.makedirs(folder)
        metadata = dict((k, v) for k, v in spectrum.items() if k not in ("energy_eV", "intensity"))
        metadata.update({"format": "csv", "columns": ["energy_eV", "intensity"],
                         "writer": "dm_mcp.spectrum_csv (17 significant digits; no display scaling)",
                         "data_mode": "derived raw spectrum; reduction explicitly recorded; no background subtraction",
                         "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        with tempfile.TemporaryDirectory(prefix=".dm_mcp_spectrum_", dir=folder) as staging:
            staged = os.path.join(staging, "spectrum.csv")
            with open(staged, "x", encoding="utf-8", newline="\n") as stream:
                stream.write("energy_eV,intensity\n")
                for energy, intensity in zip(spectrum["energy_eV"], spectrum["intensity"]):
                    stream.write("%.17g,%.17g\n" % (energy, intensity))
            with open(staged, "rb") as stream:
                metadata["sha256"] = hashlib.sha256(stream.read()).hexdigest()
            created = False
            try:
                with open(sidecar, "x", encoding="utf-8") as stream:
                    created = True
                    json.dump(_j(metadata), stream, ensure_ascii=False, indent=2, allow_nan=False)
                self._publish_spectral_file(staged, path)
            except Exception:
                if created:
                    os.remove(sidecar)
                raise
        return {"exported": True, "path": path, "metadata_path": sidecar,
                "sha256": metadata["sha256"], "writer": metadata["writer"],
                "channels": len(spectrum["energy_eV"]), "backend": self.name,
                "synthetic": self.name == "mock", "experimental": True,
                "validation_scope": spectrum["validation_scope"]}


# --------------------------------------------------------------------------
# Mock backend (offline chain test, mirrors the real contract)
# --------------------------------------------------------------------------


class MockBackend(SpectroscopyMixin):
    name = "mock"

    def __init__(self):
        self._images = {}
        specs = [
            (1000, "Mock_HRTEM", 512, 384, "nm", 0.051),
            (1001, "Mock_2D_TestImage", 64, 32, "nm", 1.2),
        ]
        for img_id, name, w, h, unit, scale in specs:
            self._images[img_id] = dict(
                id=img_id, name=name, doc_index=0, doc_name="Mock.dm4",
                width=w, height=h, unit=unit, scale=scale,
            )
        # Small deterministic fixtures, not experimental observations or fitted
        # elemental signals. A spectrum and an explicitly energy-last SI.
        if np is not None:
            self._spectral_fixtures = {
                1002: ("SYNTHETIC_EELS_1D", np.array([2, 4, 10, 4, 2, 0], dtype=np.uint32),
                       [{"dm_dimension": 0, "numpy_axis": 0, "axis": "x", "scale": 0.5,
                         "unit": "eV", "origin": 2.0, "calibrated_value_at_pixel_zero": -1.0, "size": 6}]),
                1003: ("SYNTHETIC_EDS_SI", np.fromfunction(lambda y, x, e: 100*y+10*x+e,
                           (2, 3, 8), dtype=int).astype(np.uint32),
                       [{"dm_dimension": 0, "numpy_axis": 2, "axis": "x", "scale": 0.25,
                         "unit": "keV", "origin": 0.0, "calibrated_value_at_pixel_zero": 0.0, "size": 8},
                        {"dm_dimension": 1, "numpy_axis": 1, "axis": "y", "scale": 0.2,
                         "unit": "nm", "origin": 0.0, "calibrated_value_at_pixel_zero": 0.0, "size": 3},
                        {"dm_dimension": 2, "numpy_axis": 0, "axis": "z", "scale": 0.3,
                         "unit": "nm", "origin": 0.0, "calibrated_value_at_pixel_zero": 0.0, "size": 2}]),
            }
        else:
            self._spectral_fixtures = {}

    def _spectrum_context(self, image_id):
        if image_id in self._spectral_fixtures:
            name, array, calibration = self._spectral_fixtures[image_id]
            return {"id": image_id, "name": name, "shape": list(array.shape),
                    "calibration": calibration, "intensity_unit": "a.u. (synthetic)",
                    "read_array": lambda: array}
        rec, array = self._mk(image_id, None)
        shape = list(array.shape)
        cal = [{"dm_dimension": 1-a, "numpy_axis": a, "axis": "yx"[a],
                "scale": rec["scale"], "unit": rec["unit"], "origin": 0.0,
                "calibrated_value_at_pixel_zero": 0.0, "size": shape[a]} for a in range(2)]
        return {"id": image_id, "name": rec["name"], "shape": shape,
                "calibration": cal, "read_array": lambda: array}

    def ping(self):
        _spectroscopy_helper()
        return {
            "backend": self.name,
            "bridge_version": BRIDGE_VERSION,
            "spectroscopy_code_sha256": _SPECTROSCOPY_CODE_SHA256,
            "spectroscopy_validation": {"real_eds": "NOT_TESTED", "real_eels": "NOT_TESTED",
                                        "real_si": "NOT_TESTED", "scope": "synthetic arithmetic and protocol only"},
            "dm_version": "MOCK",
            "host_python": sys.version.split()[0],
            "numpy": getattr(np, "__version__", None),
            "docs": DOCS,
            "scope": "analysis-only",
        }

    def list_datasets(self):
        imgs = []
        for rec in self._images.values():
            imgs.append({
                "id": rec["id"], "name": rec["name"], "doc_index": rec["doc_index"],
                "doc_name": rec["doc_name"], "shape": [rec["height"], rec["width"]],
                "ndim": 2, "dtype": "float32", "kind": "image",
                "calibration": [{"scale": rec["scale"], "unit": rec["unit"], "origin": 0.0,
                                 "size": rec["width"]}] * 2,
                "intensity_unit": "counts",
            })
        for iid in sorted(self._spectral_fixtures):
            name, array, calibration = self._spectral_fixtures[iid]
            imgs.append({"id": iid, "name": name, "shape": list(array.shape),
                         "ndim": array.ndim, "dtype": str(array.dtype),
                         "kind": _classify(array.shape, array.ndim), "calibration": calibration,
                         "synthetic": True, "intensity_unit": "a.u. (synthetic)"})
        return {"count": len(imgs), "datasets": imgs}

    def metadata(self, image_id, max_depth, prefix):
        parts = _metadata_prefix_parts(prefix)
        result = self._metadata_fixture(image_id, max_depth, None)
        max_depth = max(0, min(int(max_depth), 64))
        path = ""
        issues = []
        status = "found"
        node = result["tags"]
        for part in parts:
            path += "/" + part.replace("~", "~0").replace("/", "~1")
            if isinstance(node, dict) and part in node:
                node = node[part]
            elif (isinstance(node, list) and part.isascii() and part.isdigit()
                  and (part == "0" or not part.startswith("0"))
                  and len(part) <= len(str(len(node))) and int(part) < len(node)):
                node = node[int(part)]
            else:
                status = "not_found"
                issues.append({"path": path, "reason": "path_not_found"})
                node = None
                break
        remaining = [MAX_TAG_NODES]
        def visit(value, depth, current):
            if not isinstance(value, (dict, list)):
                return value
            if depth > max_depth:
                issues.append({"path": current or "/", "reason": "depth_limit"})
                return {"__unavailable__": "depth_limit"}
            is_dict = isinstance(value, dict)
            out = {} if is_dict else []
            for key, child in (value.items() if is_dict else enumerate(value)):
                if remaining[0] <= 0:
                    issues.append({"path": current or "/", "reason": "node_budget"})
                    break
                remaining[0] -= 1
                child_path = current + "/" + str(key).replace("~", "~0").replace("/", "~1")
                converted = visit(child, depth + 1, child_path)
                if is_dict:
                    out[key] = converted
                else:
                    out.append(converted)
            return out
        canonical = "".join("/" + part.replace("~", "~0").replace("/", "~1") for part in parts)
        result.update({"tags": visit(node, 0, canonical) if status == "found" else None,
                       "prefix": canonical, "path_status": status,
                       "complete": status == "found" and not issues, "issues": issues,
                       "complete_scope": "requested subtree", "synthetic": True})
        if status == "not_found":
            result["error"] = "tag path not found: %s" % canonical
        return result

    def _metadata_fixture(self, image_id, max_depth, prefix):
        if image_id in self._spectral_fixtures:
            name, array, calibration = self._spectral_fixtures[image_id]
            return {"id": image_id, "name": name,
                    "tags": {"SyntheticFixture": {"experimental_data": False,
                               "description": "Deterministic arithmetic fixture; not an elemental spectrum"}},
                    "complete": True, "issues": [], "synthetic": True,
                    "note": "mock backend; real EDS/EELS/SI NOT_TESTED"}
        return {
            "id": int(image_id or 1000),
            "name": "Mock_HRTEM",
            "tags": {
                "Acquisition": {
                    "Instrument": {"Name": "MOCK-TEM", "Voltage_kV": 200.0},
                    "DwellTime_us": 2.0,
                },
                "EELS": {"Spectrometer": {"EnergyRange_eV": 1200.0}},
            },
            "note": "mock backend",
        }

    def _mk(self, image_id, rect):
        rec = self._images[int(image_id or 1000)]
        a = np.fromfunction(
            lambda y, x: 1000.0 + 300.0 * np.sin(x / 9.0) * np.cos(y / 11.0),
            (rec["height"], rec["width"]), dtype="float64",
        )
        return rec, a

    def stats(self, image_id, rect):
        rec, a = self._mk(image_id, None)
        sub, used = _rect(a, rect)
        return {
            "id": rec["id"], "rect": used, "shape": list(sub.shape),
            "requested_rect": list(rect) if rect is not None else None, "effective_rect": list(used),
            "count": int(sub.size),
            "min": float(sub.min()), "max": float(sub.max()),
            "mean": float(sub.mean()), "stddev": float(sub.std()),
            "percentiles": {"0": float(np.percentile(sub, 0)), "50": float(np.percentile(sub, 50)),
                            "99": float(np.percentile(sub, 99)), "100": float(np.percentile(sub, 100))},
        }

    def capture2d(self, image_id, rect, output_dir):
        if np is None:
            raise RuntimeError("mock capture requires numpy")
        rec, array = self._mk(image_id, None)
        array = array.astype("float32")
        used = _rect_bounds(array.shape, rect)
        x0, y0, x1, y1 = used
        captured = np.array(array[y0:y1, x0:x1], copy=True, order="C")
        output_dir = os.path.abspath(output_dir)
        os.makedirs(output_dir)
        capture_id = uuid.uuid4().hex
        calibration = [
            {"dm_dimension": 0, "numpy_axis": 1, "axis": "x", "scale": rec["scale"],
             "unit": rec["unit"], "origin": 0.0, "calibrated_value_at_pixel_zero": 0.0,
             "size": rec["width"]},
            {"dm_dimension": 1, "numpy_axis": 0, "axis": "y", "scale": rec["scale"],
             "unit": rec["unit"], "origin": 0.0, "calibrated_value_at_pixel_zero": 0.0,
             "size": rec["height"]},
        ]
        work_calibration = [
            {"axis": "x", "scale": rec["scale"], "unit": rec["unit"],
             "calibrated_value_at_pixel_zero": x0 * rec["scale"], "size": x1 - x0},
            {"axis": "y", "scale": rec["scale"], "unit": rec["unit"],
             "calibrated_value_at_pixel_zero": y0 * rec["scale"], "size": y1 - y0},
        ]
        with open(os.path.join(output_dir, "input.npy"), "xb") as stream:
            np.save(stream, captured, allow_pickle=False)
        digest = hashlib.sha256()
        with open(os.path.join(output_dir, "input.npy"), "rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        info = {"schema_version": 1, "capture_id": capture_id,
                "shape_yx": list(captured.shape), "dtype": captured.dtype.name,
                "source_image_id": int(image_id or rec["id"]),
                "source_shape_yx": [rec["height"], rec["width"]],
                "source_rect_xyxy": used, "source_rect_convention": "zero-based half-open [x0,y0,x1,y1]",
                "source_calibration_dm": calibration, "working_calibration_xy": work_calibration,
                "pixel_coordinate_model": "pixel centers at integer x,y; physical value = calibrated_value_at_pixel_zero + index*scale",
                "intensity_calibration": {"origin": 0.0, "scale": 1.0, "unit": "counts"},
                "input_file": "input.npy", "input_sha256": digest.hexdigest(),
                "source_path_included": False, "synthetic": True}
        with open(os.path.join(output_dir, "input.json"), "x", encoding="utf-8") as stream:
            json.dump(info, stream, sort_keys=True, indent=2)
        info_digest = hashlib.sha256(json.dumps(info, ensure_ascii=False, sort_keys=True,
                                                separators=(",", ":")).encode("utf-8")).hexdigest()
        manifest = {"schema_version": 1, "capture_id": capture_id, "state": "captured",
                    "source_image_id": int(image_id or rec["id"]),
                    "source_shape_yx": [rec["height"], rec["width"]],
                    "source_rect_xyxy": used, "source_dtype": "float32",
                    "input_sha256": digest.hexdigest(), "input_metadata_sha256": info_digest,
                    "pixel_capture_atomic": False,
                    "capture_consistency": "synthetic mock only"}
        with open(os.path.join(output_dir, "capture.json"), "x", encoding="utf-8") as stream:
            json.dump(manifest, stream, sort_keys=True, indent=2)
        return {"capture_id": capture_id, "state": "captured", "capture_dir": output_dir,
                "shape_yx": list(captured.shape), "dtype": "float32",
                "source_rect_xyxy": used, "input_sha256": digest.hexdigest(),
                "synthetic": True, "pixel_capture_atomic": False}

    def profile(self, image_id, x0, y0, x1, y1, width):
        n = max(2, min(int(((float(x1) - float(x0)) ** 2 + (float(y1) - float(y0)) ** 2) ** 0.5) + 1, 4096))
        xs = np.linspace(float(x0), float(x1), n)
        return {"id": int(image_id or 1000), "n": n, "width": int(width or 1),
                "distance": [float(v) for v in np.linspace(0, 1, n)],
                "unit": "nm",
                "values": [float(1000 + 300 * np.sin(x / 9.0)) for x in xs]}

    def fft(self, image_id, rect, top_n):
        rec, a = self._mk(image_id, rect)
        sub, used = _rect(a, rect)
        f = np.fft.fftshift(np.abs(np.fft.fft2(sub - sub.mean())))
        cy, cx = f.shape[0] // 2, f.shape[1] // 2
        idx = np.argsort(f.ravel())[::-1]
        peaks = []
        for k in idx:
            y, x = divmod(int(k), f.shape[1])
            if y == cy and x == cx:
                continue
            peaks.append({"dy": y - cy, "dx": x - cx, "magnitude": float(f[y, x]),
                          "d_pix": float(np.hypot(y - cy, x - cx))})
            if len(peaks) >= int(top_n or 12):
                break
        return {"id": rec["id"], "rect": used, "shape": list(sub.shape),
            "requested_rect": list(rect) if rect is not None else None, "effective_rect": list(used),
                "dc": float(f[cy, cx]), "peaks": peaks}

    def export(self, image_id, path, fmt):
        return {"exported": False, "path": path, "format": fmt, "note": "mock backend"}

    def run_script(self, script, expect_new_image):
        return {"executed": False, "note": "mock backend does not execute DM-Script",
                "script_length": len(script), "new_images": []}

    def open_file(self, path, show):
        return {"opened": False, "path": path, "note": "mock backend"}

    def crop(self, image_id, rect, name):
        rec = self._images[int(image_id or 1000)]
        if rect is None:
            raise ValueError("crop requires an explicit rect")
        x0, y0, x1, y1 = _rect_bounds((rec["height"], rec["width"]), rect)
        new_id = max(self._images.keys()) + 1
        self._images[new_id] = dict(
            rec, id=new_id, name=name or "crop_mock",
            width=x1 - x0, height=y1 - y0,
        )
        return {"source_id": rec["id"], "requested_rect": list(rect),
                "effective_rect": [x0, y0, x1, y1],
                "new_image": {"id": new_id, "name": self._images[new_id]["name"],
                              "shape": [y1 - y0, x1 - x0]},
                "note": "mock backend"}


# --------------------------------------------------------------------------
# Real backend
# --------------------------------------------------------------------------


TAG_SCALARS = [
    ("string", "GetTagAsString"),
    ("text", "GetTagAsText"),
    ("double", "GetTagAsDouble"),
    ("long", "GetTagAsLong"),
    ("short", "GetTagAsShort"),
    ("float", "GetTagAsFloat"),
    ("uint16", "GetTagAsUInt16"),
    ("uint32", "GetTagAsUInt32"),
    ("bool", "GetTagAsBoolean"),
]

INDEXED_SCALARS = [
    ("string", "GetIndexedTagAsString"),
    ("text", "GetIndexedTagAsText"),
    ("double", "GetIndexedTagAsDouble"),
    ("long", "GetIndexedTagAsLong"),
    ("short", "GetIndexedTagAsShort"),
    ("float", "GetIndexedTagAsFloat"),
    ("uint16", "GetIndexedTagAsUInt16"),
    ("uint32", "GetIndexedTagAsUInt32"),
    ("bool", "GetIndexedTagAsBoolean"),
]


class DmBackend(SpectroscopyMixin):
    name = "digitalmicrograph"

    def __init__(self, dm):
        self.DM = dm
        self._host_pid = os.getpid()
        self._bridge_version = BRIDGE_VERSION
        self._bridge_code_sha256 = None
        try:
            with open(__file__, "rb") as source:
                self._bridge_code_sha256 = hashlib.sha256(source.read()).hexdigest()
        except (OSError, NameError):
            pass
        self._node_budget = MAX_TAG_NODES
        self._tag_types = {}
        self._metadata_issues = []
        self._source_files = {}
        # Hidden documents are not owned/enumerated by a DM workspace. Keep
        # their native wrappers alive until this backend is released; never
        # make a document visible merely to preserve its lifetime.
        self._opened_documents = {}
        self._fourdstem_sources = {}

    # -- basics -----------------------------------------------------------
    def ping(self):
        _spectroscopy_helper()
        ver = None
        for name in ("GetApplicationVersion", "GetVersion"):
            try:
                ver = str(getattr(self.DM, name)())
                break
            except Exception:
                continue
        return {
            "backend": self.name,
            "host_pid": self._host_pid,
            "bridge_version": self._bridge_version,
            "bridge_code_sha256": self._bridge_code_sha256,
            "spectroscopy_code_sha256": _SPECTROSCOPY_CODE_SHA256,
            "fourdstem_helpers": dict((name, value[1]) for name, value in _FOURDSTEM_HELPERS.items()),
            "spectroscopy_validation": {"real_eds": "NOT_TESTED", "real_eels": "NOT_TESTED",
                                        "real_si": "NOT_TESTED", "scope": "synthetic arithmetic and protocol only"},
            "dm_version": ver or "unknown",
            "host_python": sys.version.split()[0],
            "numpy": getattr(np, "__version__", None),
            "on_main_thread": self._safe(lambda: bool(self.DM.IsScriptOnMainThread())),
            "docs": DOCS,
            "scope": "analysis-only",
        }

    @staticmethod
    def _safe(fn, *args):
        try:
            return fn(*args)
        except Exception:
            return None

    def _doc(self, i):
        return self.DM.GetImageDocument(int(i))

    def _iter_images(self):
        all_count = getattr(self.DM, "CountImageDocumentsOfAllWorkspaces", None)
        all_doc = getattr(self.DM, "GetImageDocumentOfAllWorkspaces", None)
        across_workspaces = all_count is not None and all_doc is not None
        count = all_count() if across_workspaces else self.DM.CountImageDocuments()
        documents = []
        for d in range(int(count)):
            try:
                doc = all_doc(d) if across_workspaces else self._doc(d)
                documents.append((d, doc))
            except Exception:
                continue
        for key, doc in list(self._opened_documents.items()):
            try:
                valid = bool(doc.IsValid())
            except Exception:
                valid = False
            if not valid:
                del self._opened_documents[key]
                continue
            # -1 means retained by the bridge rather than a workspace index.
            documents.append((-1, doc))
        seen = set()
        for d, doc in documents:
            try:
                doc_name = self._safe(doc.GetName) or ""
                n = int(doc.CountImages())
            except Exception:
                continue
            for k in range(n):
                try:
                    image = doc.GetImage(k)
                    if not bool(image.IsValid()):
                        continue
                    image_id = int(image.GetID())
                    if image_id in seen:
                        continue
                    seen.add(image_id)
                    yield d, doc, doc_name, image
                except Exception:
                    continue

    def _resolve(self, image_id):
        if image_id in (None, "", "front"):
            img = self.DM.GetFrontImage()
            if img is None:
                raise RuntimeError("前台没有图像窗口；请先 dm_open_file 或指定 image_id")
            return img
        target = int(image_id)
        find = getattr(self.DM, "FindImageByID", None)
        if find is not None:
            try:
                img = find(target)
                if img is not None and bool(img.IsValid()):
                    return img
            except Exception:
                pass
        for _, _, _, img in self._iter_images():
            if int(img.GetID()) == target:
                return img
        raise RuntimeError("找不到 image_id=%s 的图像" % target)

    # -- metadata ---------------------------------------------------------
    @staticmethod
    def _tag_path(path, label):
        return path + "/" + str(label).replace("~", "~0").replace("/", "~1")

    def _metadata_issue(self, path, reason, detail=None):
        issue = {"path": path or "/", "reason": reason}
        if detail is not None:
            issue["detail"] = str(detail)
        self._metadata_issues.append(issue)
        return {"__unavailable__": reason}

    @staticmethod
    def _decode_dm_text(value):
        """GMS returns some labels as legacy US/Windows bytes (not Unicode)."""
        if not isinstance(value, bytes):
            return str(value), None
        for encoding in ("utf-8", "cp1252", "latin-1"):
            try:
                return value.decode(encoding), encoding
            except UnicodeDecodeError:
                pass
        raise ValueError("无法解码 DM 文本")

    def _read_tag_typed(self, tg, index, descriptor, path):
        # Groups cannot be classified from a guessed scalar code: some GMS
        # versions expose empty/unhelpful descriptors for a container. The
        # documented indexed group getter has an explicit output parameter.
        if descriptor in ([], [3]) and self._tag_types[path]["tag_size"] == 0:
            # Group descriptors may be [] or legacy [3] with size 0.
            # A scalar long is
            # [3] with size 4 and must never reach the container getter.
            # Do NOT call a container getter on scalar/unknown tags: native
            # mismatched-type probes can crash the host instead of raising.
            subgroup = self.DM.NewTagGroup()
            if not tg.GetIndexedTagAsTagGroup(index, subgroup):
                raise RuntimeError("已确认容器标签的 GetIndexedTagAsTagGroup 返回失败")
            self._tag_types[path]["reader"] = "GetIndexedTagAsTagGroup"
            self._tag_types[path]["container"] = "list" if subgroup.IsList() else "group"
            return subgroup
        # Confirmed with this installation's synthetic typed-tag probe. Every
        # numeric getter can coerce other numeric types, so trying getters in
        # sequence would truncate values or turn all numbers into booleans.
        readers = {
            (2,): "GetIndexedTagAsShort", (3,): "GetIndexedTagAsLong",
            (4,): "GetIndexedTagAsUInt16", (5,): "GetIndexedTagAsUInt32",
            (6,): "GetIndexedTagAsFloat", (7,): "GetIndexedTagAsDouble",
            (8,): "GetIndexedTagAsBoolean",
            (11,): "GetIndexedTagAsSInt64", (12,): "GetIndexedTagAsUInt64",
            (15, 0, 2, 0, 7, 0, 7): "GetIndexedTagAsDoubleComplex",
        }
        reader = readers.get(tuple(descriptor))
        if len(descriptor) == 3 and descriptor[:2] == [20, 4]:
            reader = "GetIndexedTagAsString"  # Native String/Text: UTF-16 code units.
        if reader is None:
            raise NotImplementedError("unsupported DM tag descriptor %s" % descriptor)
        result = getattr(tg, reader)(index)
        if not isinstance(result, (tuple, list)) or len(result) != 2 or not result[0]:
            raise RuntimeError("%s(index=%d) 没有返回成功状态和值" % (reader, index))
        value = result[1]
        self._tag_types[path]["reader"] = reader
        if reader == "GetIndexedTagAsString" and isinstance(value, bytes):
            decoded, encoding = self._decode_dm_text(value)
            self._tag_types[path]["value_bytes_hex"] = value.hex()
            self._tag_types[path]["value_encoding"] = encoding
            return decoded
        return value

    def _metadata_value(self, value, depth, max_depth, path):
        if hasattr(value, "CountTags") and hasattr(value, "IsList"):
            return self._walk_tags(value, depth, max_depth, path)
        if np is not None and isinstance(value, np.generic):
            value = value.item()
        if isinstance(value, int) and not isinstance(value, bool) and abs(value) > 9007199254740991:
            # MCP's JavaScript facade cannot represent larger integer JSON
            # numbers exactly. Keep the original decimal digits explicitly.
            return {"__type__": "integer", "decimal": str(value)}
        if value is None or isinstance(value, (bool, int, str)):
            if isinstance(value, str) and len(value) > MAX_TAG_VALUE_BYTES:
                self._metadata_issue(path, "value_length_limit", len(value))
                return {"__type__": "string", "preview": value[:MAX_TAG_VALUE_BYTES],
                        "length": len(value), "truncated": True}
            return value
        if isinstance(value, float):
            if math.isfinite(value):
                return value
            return {"__type__": "float", "value": str(value)}
        if isinstance(value, complex):
            return {"__type__": "complex", "real": _j(value.real), "imag": _j(value.imag)}
        if isinstance(value, bytes):
            if len(value) > MAX_TAG_VALUE_BYTES:
                self._metadata_issue(path, "value_length_limit", len(value))
                return {"__type__": "bytes", "length": len(value), "truncated": True}
            return {"__type__": "bytes", "hex": value.hex()}
        if np is not None and isinstance(value, np.ndarray):
            if value.size > self._node_budget or value.nbytes > MAX_TAG_VALUE_BYTES:
                self._metadata_issue(path, "array_size_limit", list(value.shape))
                return {"__type__": "ndarray", "shape": list(value.shape),
                        "dtype": str(value.dtype), "truncated": True}
            self._node_budget -= int(value.size)
            return {"__type__": "ndarray", "shape": list(value.shape),
                    "dtype": str(value.dtype), "values": _j(value)}
        if isinstance(value, (dict, list, tuple)):
            if depth > max_depth:
                return self._metadata_issue(path, "depth_limit", max_depth)
            is_dict = isinstance(value, dict)
            out = {} if is_dict else []
            items = value.items() if is_dict else enumerate(value)
            for key, item in items:
                if self._node_budget <= 0:
                    self._metadata_issue(path, "node_budget", MAX_TAG_NODES)
                    break
                self._node_budget -= 1
                child = self._metadata_value(item, depth + 1, max_depth,
                                             self._tag_path(path, key))
                if is_dict:
                    out[str(key)] = child
                else:
                    out.append(child)
            return out
        return self._metadata_issue(path, "unsupported_python_type", type(value).__name__)

    def _metadata_read_entry(self, tg, index, path, raw_label=None, label_encoding=None):
        record = {"dm_type": None, "tag_size": None}
        self._tag_types[path] = record
        if isinstance(raw_label, bytes):
            record.update({"label_bytes_hex": raw_label.hex(), "label_encoding": label_encoding})
        try:
            length = int(tg.GetTagTypeLength(index))
            if not 0 <= length <= 64:
                return self._metadata_issue(path, "type_descriptor_limit", length), False
            descriptor = [int(tg.GetTagType(index, k)) for k in range(length)]
            record["dm_type"] = descriptor
        except Exception as exc:
            return self._metadata_issue(path, "type_read_error", exc), False
        try:
            size = tg.GetTagSize(index)
            if (isinstance(size, bool) or not isinstance(size, numbers.Real)
                    or not math.isfinite(size) or size < 0):
                raise ValueError("unknown, nonfinite or negative native tag size")
            record["tag_size"] = size
        except Exception as exc:
            return self._metadata_issue(path, "tag_size_read_error", exc), False
        if size > MAX_TAG_VALUE_BYTES and descriptor[:1] != [0]:
            return self._metadata_issue(path, "tag_size_limit", size), False
        try:
            # Never guess a getter after failed/truncated type introspection.
            return self._read_tag_typed(tg, index, descriptor, path), True
        except NotImplementedError as exc:
            return self._metadata_issue(path, "unsupported_dm_type", exc), False
        except Exception as exc:
            return self._metadata_issue(path, "read_error", exc), False

    def _metadata_locate(self, node, parts):
        """Read only the selected ancestry; scan sibling labels, not values.

        Lookup has its own bounded budget. An unreadable/ambiguous directory
        cannot establish absence, even when another label matches the request.
        """
        if not (hasattr(node, "CountTags") and hasattr(node, "IsList")):
            return self._metadata_issue("", "read_error", "invalid native metadata root"), "unavailable"
        path = ""
        for step, part in enumerate(parts):
            child_path = self._tag_path(path, part)
            if not (hasattr(node, "CountTags") and hasattr(node, "IsList")):
                return self._metadata_issue(child_path, "not_a_container"), "not_found"
            try:
                count = int(node.CountTags())
                is_list = bool(node.IsList())
                if count < 0:
                    raise ValueError("negative tag count")
            except Exception as exc:
                return self._metadata_issue(path, "read_error", exc), "unavailable"
            raw_label = label_encoding = None
            if is_list:
                if not (part.isascii() and part.isdigit()
                        and (part == "0" or not part.startswith("0"))
                        and len(part) <= len(str(count)) and int(part) < count):
                    return self._metadata_issue(child_path, "path_not_found"), "not_found"
                if self._lookup_budget <= 0:
                    return self._metadata_issue(child_path, "lookup_budget", MAX_TAG_NODES), "unavailable"
                self._lookup_budget -= 1
                index = int(part)
            else:
                index = None
                for i in range(count):
                    if self._lookup_budget <= 0:
                        return self._metadata_issue(child_path, "lookup_budget", MAX_TAG_NODES), "unavailable"
                    self._lookup_budget -= 1
                    try:
                        candidate = node.GetTagLabel(i)
                        label, encoding = self._decode_dm_text(candidate)
                    except Exception as exc:
                        return self._metadata_issue(child_path, "label_read_error", exc), "unavailable"
                    if label == part:
                        if index is not None:
                            return self._metadata_issue(child_path, "duplicate_label", i), "unavailable"
                        index, raw_label, label_encoding = i, candidate, encoding
                if index is None:
                    return self._metadata_issue(child_path, "path_not_found"), "not_found"
            value, readable = self._metadata_read_entry(node, index, child_path, raw_label, label_encoding)
            if not readable:
                # The final label exists, even when its payload cannot be read.
                return value, "found" if step == len(parts) - 1 else "unavailable"
            node, path = value, child_path
        return node, "found"

    def _walk_tags(self, tg, depth, max_depth, path=""):
        if depth > max_depth:
            return self._metadata_issue(path, "depth_limit", max_depth)
        try:
            count = int(tg.CountTags())
            is_list = bool(tg.IsList())
        except Exception as exc:
            return self._metadata_issue(path, "read_error", exc)
        out = [] if is_list else {}
        for i in range(count):
            if self._node_budget <= 0:
                self._metadata_issue(path, "node_budget", MAX_TAG_NODES)
                break
            self._node_budget -= 1
            raw_label = None
            label_encoding = None
            try:
                if is_list:
                    key = i
                else:
                    raw_label = tg.GetTagLabel(i)
                    key, label_encoding = self._decode_dm_text(raw_label)
            except Exception as exc:
                key = i if is_list else "__index_%d" % i
                self._metadata_issue(self._tag_path(path, key), "label_read_error", exc)
            child_path = self._tag_path(path, key)
            value, readable = self._metadata_read_entry(tg, i, child_path, raw_label, label_encoding)
            child = self._metadata_value(value, depth + 1, max_depth, child_path) if readable else value
            if is_list:
                out.append(child)
            elif key in out:
                self._metadata_issue(child_path, "duplicate_label", i)
            else:
                out[key] = child
        return out

    def metadata(self, image_id, max_depth, prefix):
        parts = _metadata_prefix_parts(prefix)
        canonical = "".join(self._tag_path("", part) for part in parts)
        img = self._resolve(image_id)
        self._node_budget = MAX_TAG_NODES
        self._lookup_budget = MAX_TAG_NODES
        self._tag_types = {}
        self._metadata_issues = []
        max_depth = max(0, min(int(max_depth), 64))
        result = {"id": int(img.GetID()), "name": self._safe(img.GetName)}
        try:
            node, status = self._metadata_locate(img.GetTagGroup(), parts)
            tree = (self._metadata_value(node, 0, max_depth, canonical)
                    if status == "found" and not self._metadata_issues else node)
        except Exception as exc:
            tree = self._metadata_issue(canonical, "read_error", exc)
            status = "unavailable"
        result.update({"tags": None if status == "not_found" else tree,
                       "prefix": canonical, "path_status": status,
                       "tag_types": self._tag_types,
                       "complete": status == "found" and not bool(self._metadata_issues),
                       "complete_scope": "requested subtree", "issues": self._metadata_issues,
                       "limits": {"max_depth": max_depth, "max_nodes": MAX_TAG_NODES,
                                  "max_lookup_nodes": MAX_TAG_NODES, "max_path_segments": 64,
                                  "max_tag_value_bytes": MAX_TAG_VALUE_BYTES},
                       "tag_path_format": "JSON Pointer; calibration dimensions use DM order X,Y,Z,..."})
        if status == "not_found":
            result["error"] = "tag path not found: %s" % canonical
        elif status == "unavailable":
            result["error"] = "tag path could not be resolved completely; inspect issues"
        return result

    # -- datasets ---------------------------------------------------------
    def _calib(self, img, ndim):
        out = []
        for d in range(ndim):
            at_zero = self._safe(lambda: img.GetDimensionCalibration(d, 0))
            out.append({
                "dm_dimension": d, "numpy_axis": ndim - 1 - d,
                "axis": ("x", "y", "z")[d] if d < 3 else "axis%d" % d,
                "scale": _num(self._safe(img.GetDimensionScale, d)),
                "unit": self._safe(img.GetDimensionUnitString, d),
                "origin": _num(self._safe(img.GetDimensionOrigin, d)),
                "calibrated_value_at_pixel_zero": _num(at_zero[0]) if at_zero is not None else None,
                "size": _num(self._safe(img.GetDimensionSize, d)),
            })
        return out

    def _dims(self, img):
        """Dimension sizes without touching pixel data (cheap even for GB files)."""
        ndim = int(img.GetNumDimensions())
        dims = []
        for d in range(ndim):
            v = self._safe(img.GetDimensionSize, d)
            dims.append(int(v) if v else 0)
        if not dims or any(v <= 0 for v in dims):
            dims = [int(img.GetImgWidth()), int(img.GetImgHeight())]
            if ndim > 2:
                dims.append(int(img.GetImgDepth()))
        return ndim, dims

    @staticmethod
    def _npixels(dims):
        n = 1
        for v in dims:
            n *= max(1, int(v))
        return n

    def _guard(self, img, dims):
        """Refuse to pull a whole array we cannot afford to copy."""
        n = self._npixels(dims)
        if n > MAX_TRANSFER_PIXELS:
            raise RuntimeError(
                "所选计算区域约 %d 像素（%s），超过工作区域上限 %d（环境变量 DM_MCP_MAX_PIXELS）。"
                "GetNumArray() 共享 DM 内存，但数值计算会分配临时数组；请缩小 rect 或先选切片。"
                % (n, "x".join(str(v) for v in dims), MAX_TRANSFER_PIXELS)
            )
        return n

    def list_datasets(self):
        out = []
        for d, doc, doc_name, img in self._iter_images():
            try:
                ndim, dims = self._dims(img)
                n = self._npixels(dims)
                # Native type introspection does not map the pixel buffer.
                data_type_code = self._safe(img.GetDataType)
                dtype = _native_scalar_dtype_name(data_type_code)
                out.append({
                    "id": int(img.GetID()),
                    "name": self._safe(img.GetName),
                    "source_file": self._source_files.get(int(img.GetID())),
                    "doc_index": d,
                    "workspace_id": self._safe(doc.GetWorkspace),
                    "doc_name": doc_name,
                    "shape": list(reversed(dims)),
                    "dm_dimensions": dims,
                    "shape_order": "numpy (last axis is X)",
                    "ndim": ndim,
                    "dtype": dtype,
                    "data_type_code": data_type_code,
                    "pixels": n,
                    "transfer_ok": bool(n <= MAX_TRANSFER_PIXELS),
                    "kind": _classify(dims, ndim),
                    "calibration": self._calib(img, ndim),
                    "intensity_unit": self._safe(img.GetIntensityUnitString),
                })
            except Exception:
                continue
        return {"count": len(out), "datasets": out,
                "max_transfer_pixels": MAX_TRANSFER_PIXELS}

    # -- numeric ops ------------------------------------------------------
    def _need_numpy(self):
        if np is None:
            raise RuntimeError("宿主 Python 没有 numpy，无法做数值计算")
        return np

    def _array_2d(self, img):
        self._need_numpy()
        if self._dims(img)[0] != 2:
            raise RuntimeError("本工具只支持二维实数图像；请先显式选取二维切片")
        a = _arr(img)
        if a.ndim != 2 or a.dtype.kind not in "biuf":
            raise RuntimeError("本工具只支持二维实数强度数组；复数/RGB 数据需要明确转换方法")
        return a

    # -- bounded 4D-STEM, native Gatan byte streams -------------------------
    def fourdstem_open(self, path, scan_axes, detector_axes):
        self._need_numpy()
        if scan_axes != [0, 1] or detector_axes != [2, 3]:
            raise ValueError("Native 4D file route requires explicit scan_axes=[0,1], detector_axes=[2,3]")
        path = os.path.abspath(path)
        index = _fourdstem_helper("dm4_header").HeaderIndex(path)
        candidates = [d for d in index.datasets if len(d["shape"]) == 4]
        if len(candidates) != 1:
            raise ValueError("DM4 must contain exactly one explicitly selected 4D scalar dataset")
        dataset = candidates[0]
        if np.dtype(dataset["dtype"]) != np.dtype("uint8"):
            raise ValueError("Native 4D raw-stream route currently supports uint8 only")
        axes = _fourdstem_helper("fourdstem").info(dataset["shape"], dataset["calibration"], scan_axes, detector_axes)
        opened_path = self._windows_short_path(path) or path
        st = os.stat(path)
        token = "4d-%d" % (len(self._fourdstem_sources) + 1)
        record = {"dataset_id": token, "path": path, "opened_path": opened_path,
                  "size_bytes": int(st.st_size), "mtime_ns": int(st.st_mtime_ns),
                  "dataset": dataset, "axes": axes, "index": index.describe()}
        self._fourdstem_sources[token] = record
        return {"opened": True, "dataset_id": token, "dataset": dataset, "axes": axes,
                "source_file": {k: record[k] for k in ("path", "opened_path", "size_bytes", "mtime_ns")},
                "indexing": index.describe(), "backend": self.name,
                "reading_mode": "seek-only DM4 index, then bounded native Gatan read-only binary streams",
                "whole_document_opened": False,
                "native_dm4_document_loader_verified": False,
                "note": "No OpenImage of the full source; masks use explicit reciprocal coordinates, not hardware collection angles"}

    def _fourdstem_record(self, dataset_id):
        if dataset_id not in self._fourdstem_sources:
            raise ValueError("Unknown 4D dataset_id; first use dm_4dstem_open")
        record = self._fourdstem_sources[dataset_id]
        st = os.stat(record["path"])
        if int(st.st_size) != record["size_bytes"] or int(st.st_mtime_ns) != record["mtime_ns"]:
            raise RuntimeError("4D source size/mtime changed; refusing stale header offsets")
        return record

    def _fourdstem_image(self, array, calibration, record, label, history):
        # Gatan scalar image types do not include uint64. Publish counts only
        # after proving that conversion is exact; never clip/wrap detector sums.
        conversion = "none"
        if array.dtype == np.dtype("uint64"):
            maximum = int(array.max())
            if maximum <= np.iinfo(np.uint32).max:
                array = array.astype(np.uint32)
                conversion = "exact uint64 -> uint32 for native DM publication"
            elif maximum <= 2 ** 53:
                array = array.astype(np.float64)
                conversion = "exact uint64 -> float64 within 2**53 for native DM publication"
            else:
                raise ValueError("Counts cannot be published exactly in supported native DM scalar types")
        img = self.DM.CreateImage(np.ascontiguousarray(array))
        if not bool(img.IsValid()) or self._dims(img)[1] != list(reversed(array.shape)):
            raise RuntimeError("Native DM image shape differs from bounded source/result")
        view = img.GetNumArray()
        try:
            if view.dtype != array.dtype or view.shape != array.shape or not np.array_equal(view, array):
                raise RuntimeError("Native DM CreateImage changed result dtype/pixels")
        finally:
            del view
        img.SetName(label)
        origin_rounding = []
        for item in calibration:
            axis = item["numpy_axis"]
            dim = array.ndim - 1 - axis
            img.SetDimensionCalibration(dim, item["calibrated_value_at_pixel_zero"], item["scale"], item["unit"], 0)
            zero, scale, unit = img.GetDimensionCalibration(dim, 0)
            if isinstance(unit, bytes):
                unit = unit.decode("utf-8")
            requested_zero = item["calibrated_value_at_pixel_zero"]
            expected_native_zero = float(np.float32(requested_zero))
            origin_rounding.append({"numpy_axis": axis, "requested": requested_zero,
                                    "actual_native": float(zero), "absolute_error": abs(float(zero)-requested_zero)})
            if not (math.isclose(float(zero), expected_native_zero, rel_tol=0, abs_tol=1e-9)
                    and math.isclose(float(scale), item["scale"], rel_tol=1e-10, abs_tol=1e-12) and unit == item["unit"]):
                raise RuntimeError("Native DM calibration did not round-trip: dimension=%d, requested=%r, actual=%r"
                                   % (dim, (item["calibrated_value_at_pixel_zero"], item["scale"], item["unit"]), (zero, scale, unit)))
        iid = int(img.GetID())
        doc = img.GetOrCreateImageDocument()
        self._opened_documents[(iid,)] = doc
        source = {"path": record["path"], "opened_path": record["opened_path"],
                  "same_file_verified": True, "size_bytes": record["size_bytes"],
                  "mtime_ns": str(record["mtime_ns"]), "history": history,
                  "native_publication_conversion": conversion}
        self._source_files[iid] = source
        return {"id": iid, "name": label, "shape": list(array.shape), "dtype": str(array.dtype),
                "calibration": self._calib(img, array.ndim), "conversion": conversion,
                "requested_calibration": calibration, "native_origin_rounding": origin_rounding,
                "native_calibration_precision": "GMS stores physical origin as float32; actual API value checked against float32-rounded requested value"}

    def fourdstem_read(self, dataset_id, scan_bounds):
        record = self._fourdstem_record(dataset_id)
        dataset = record["dataset"]
        bounds = self._fourdstem_bounds(scan_bounds, dataset["shape"], 256)
        sy0, sy1 = bounds[0]; sx0, sx1 = bounds[1]
        shape = [sy1-sy0, sx1-sx0] + dataset["shape"][2:]
        if self._npixels(shape) > 16 * 1024 * 1024:
            raise ValueError("4D native preview exceeds 16 MiB; request a smaller scan ROI")
        output = np.empty(shape, dtype=np.uint8)
        reader_class = _fourdstem_helper("native_stream").NativePatternReader
        evidence = []
        with reader_class(self.DM, record["opened_path"], dataset["data_offset"], dataset["shape"], dataset["dtype"]) as reader:
            for sy in range(sy0, sy1):
                for x0 in range(sx0, sx1, reader.max_patterns):
                    x1 = min(sx1, x0+reader.max_patterns)
                    output[sy-sy0, x0-sx0:x1-sx0] = reader.read_patterns(sy, x0, x1)
                    evidence.append(dict(reader.last_read_evidence))
        calibration = [dict(item) for item in dataset["calibration"]]
        for item in calibration:
            axis = item["numpy_axis"]
            if axis < 2:
                item["calibrated_value_at_pixel_zero"] += bounds[axis][0] * item["scale"]
                item["size"] = shape[axis]
        image = self._fourdstem_image(output, calibration, record, "4D bounded native tile", [{"operation": "native_4d_read", "scan_bounds": bounds}])
        return {"dataset_id": dataset_id, "scan_bounds": bounds, "image": image,
                "native_reads": evidence, "whole_document_opened": False, "source_unchanged": True}

    @staticmethod
    def _fourdstem_bounds(bounds, shape, max_patterns):
        if not isinstance(bounds, list) or len(bounds) != 2:
            raise ValueError("scan_bounds must be [[y0,y1],[x0,x1]]")
        for axis, pair in enumerate(bounds):
            if not isinstance(pair, list) or len(pair) != 2 or any(isinstance(v, bool) or not isinstance(v, int) for v in pair):
                raise ValueError("scan_bounds use strict integer half-open intervals")
            if not 0 <= pair[0] < pair[1] <= shape[axis]:
                raise ValueError("scan_bounds are outside source scan axes")
        if (bounds[0][1]-bounds[0][0]) * (bounds[1][1]-bounds[1][0]) > max_patterns:
            raise ValueError("Too many scan positions per call; split scan_bounds into bounded batches")
        return bounds

    def fourdstem_virtual(self, dataset_id, scan_bounds, detectors, chunk_patterns=128):
        record = self._fourdstem_record(dataset_id)
        dataset = record["dataset"]
        reserved = {"total", "sum_dp", "mean_dp", "mean_diffraction", "sum_diffraction"}
        if not isinstance(detectors, list) or any(not isinstance(d, dict) or d.get("label") in reserved for d in detectors):
            raise ValueError("Virtual detector labels must be objects with non-reserved output names")
        bounds = self._fourdstem_bounds(scan_bounds, dataset["shape"], 8192)
        reader_class = _fourdstem_helper("native_stream").NativePatternReader
        first = last = None
        native_reads = 0
        with reader_class(self.DM, record["opened_path"], dataset["data_offset"], dataset["shape"], dataset["dtype"]) as reader:
            def read(sy, x0, x1):
                nonlocal first, last, native_reads
                block = reader.read_patterns(sy, x0, x1)
                last = dict(reader.last_read_evidence)
                if first is None:
                    first = last
                native_reads += 1
                return block
            if isinstance(chunk_patterns, bool) or not isinstance(chunk_patterns, int) or not 1 <= chunk_patterns <= reader.max_patterns:
                raise ValueError("chunk_patterns exceeds native read/copy budget")
            result = _fourdstem_helper("fourdstem").virtual_detectors_from_reader(dataset["shape"], dataset["dtype"], read,
                dataset["calibration"], [0,1], [2,3], bounds, detectors, chunk_patterns=chunk_patterns)
            reader_info = dict(reader.info)
        history = [{"operation": "virtual_detectors", "scan_bounds": bounds,
                    "detectors": result["detector_metadata"], "arithmetic": result["sum_arithmetic"]}]
        scan_cal = []
        for axis, item in enumerate(result["scan_calibration"]):
            entry = dict(item); entry["numpy_axis"] = axis; scan_cal.append(entry)
        qcal = []
        for axis, item in enumerate(result["detector_calibration"]):
            entry = dict(item); entry["numpy_axis"] = axis; qcal.append(entry)
        images = {}
        for label, array in result["maps"].items():
            images[label] = self._fourdstem_image(array, scan_cal, record, "Virtual " + label, history)
        images["total"] = self._fourdstem_image(result["total_counts"], scan_cal, record, "Virtual full detector", history)
        images["sum_dp"] = self._fourdstem_image(result["sum_dp_counts"], qcal, record, "Sum diffraction", history)
        images["mean_dp"] = self._fourdstem_image(result["mean_dp"], qcal, record, "Mean diffraction", history)
        return {"dataset_id": dataset_id, "scan_bounds": bounds, "images": images,
                "detectors": result["detector_metadata"], "q_unit": result["q_unit"],
                "chunking": result["chunking"], "native_reader": reader_info,
                "native_read_count": native_reads, "first_native_read": first, "last_native_read": last,
                "arithmetic": result["sum_arithmetic"], "scope": result["scope"],
                "whole_document_opened": False, "source_unchanged": True}

    def _spectrum_context(self, image_id):
        self._need_numpy()
        img = self._resolve(image_id)
        # Known scalar DM types. Reject RGB/packed/complex/unknown native
        # types before exposing their pixel buffer as a putative spectrum.
        if self._safe(img.GetDataType) not in (1, 2, 6, 7, 9, 10, 11, 12):
            raise ValueError("光谱接口仅支持已知 DM 实数标量类型；拒绝 RGB、packed、复数或未知类型")
        ndim, dims = self._dims(img)
        return {"id": int(img.GetID()), "name": self._safe(img.GetName),
                "shape": list(reversed(dims)), "calibration": self._calib(img, ndim),
                "source_file": self._source_files.get(int(img.GetID())),
                "intensity_unit": self._safe(img.GetIntensityUnitString),
                "read_array": lambda: _arr(img)}

    def _roi(self, img, rect):
        # GetNumArray is a shared view. Slice BEFORE any dtype conversion.
        sub, used = _rect(self._array_2d(img), rect)
        self._guard(img, sub.shape)
        return sub, used

    def stats(self, image_id, rect):
        img = self._resolve(image_id)
        sub, used = self._roi(img, rect)
        result = _analysis2d_helper().statistics(sub)
        result.update({
            "id": int(img.GetID()), "rect": used, "shape": list(sub.shape),
            "requested_rect": list(rect) if rect is not None else None, "effective_rect": list(used),
            "calibration": self._calib(img, 2),
            "rect_convention": "[x0,y0,x1,y1], right/bottom excluded; strict bounds, no rounding or clipping",
        })
        return result

    def profile(self, image_id, x0, y0, x1, y1, width):
        img = self._resolve(image_id)
        a = self._array_2d(img)
        calibration = self._calib(img, 2)
        result = _analysis2d_helper().profile(a, calibration, x0, y0, x1, y1, width)
        result["id"] = int(img.GetID())
        return result

    def fft(self, image_id, rect, top_n):
        img = self._resolve(image_id)
        selected, used = self._roi(img, rect)
        calibration = self._calib(img, 2)
        result, _ = _analysis2d_helper().fft(selected, calibration, top_n)
        result.update({"id": int(img.GetID()), "rect": used, "shape": list(selected.shape),
            "requested_rect": list(rect) if rect is not None else None, "effective_rect": list(used),
        })
        return result

    def capture2d(self, image_id, rect, output_dir):
        """Capture one bounded 2D selection into a new, immutable NPY bundle."""
        np_ = self._need_numpy()
        if not isinstance(output_dir, str) or not output_dir or "\x00" in output_dir:
            raise ValueError("output_dir must be an absolute new directory")
        output_dir = os.path.abspath(output_dir)
        if not os.path.isabs(output_dir) or os.path.exists(output_dir):
            raise FileExistsError("capture output_dir must not already exist")
        img = self._resolve(image_id)  # Resolve 'front' exactly once.
        ndim, dims = self._dims(img)
        if ndim != 2 or len(dims) != 2:
            raise ValueError("只支持显式二维实数图像；请先在 DM 中选择二维数据集")
        source_shape = [int(dims[1]), int(dims[0])]
        data_type_code = self._safe(img.GetDataType)
        dtype_name = _native_scalar_dtype_name(data_type_code)
        if dtype_name is None:
            raise ValueError("拒绝未知或非实数 DM 数据类型；不猜测 NumPy dtype")
        expected_dtype = np_.dtype(dtype_name)
        used = _rect_bounds(source_shape, rect)
        x0, y0, x1, y1 = used
        selected_shape = [y1 - y0, x1 - x0]
        pixel_count = selected_shape[0] * selected_shape[1]
        selected_bytes = pixel_count * expected_dtype.itemsize
        estimated_peak = selected_bytes * 2 + 65536
        if pixel_count > MAX_TRANSFER_PIXELS:
            raise RuntimeError("捕获区域超过 DM 像素预算；请显式缩小 rect")
        if estimated_peak > MAX_2D_CAPTURE_WORKING_BYTES:
            raise RuntimeError("捕获区域预计工作内存 %d bytes，超过 %d bytes；未自动缩小区域"
                               % (estimated_peak, MAX_2D_CAPTURE_WORKING_BYTES))
        calibration_before = self._calib(img, 2)
        before = {"shape": source_shape, "data_type_code": int(data_type_code),
                  "calibration": calibration_before}
        os.makedirs(output_dir)  # Exclusive: refuses an existing directory.
        capture_id = uuid.uuid4().hex
        manifest = {"schema_version": 1, "capture_id": capture_id,
                    "state": "capturing", "operation": "bounded 2D capture",
                    "source_image_id": int(img.GetID()),
                    "source_shape_yx": source_shape,
                    "source_rect_xyxy": used,
                    "source_rect_convention": "zero-based half-open [x0,y0,x1,y1]",
                    "source_dtype": expected_dtype.name,
                    "source_data_type_code": int(data_type_code),
                    "calibration_before": calibration_before,
                    "memory_estimate_bytes": estimated_peak,
                    "memory_budget_bytes": MAX_2D_CAPTURE_WORKING_BYTES,
                    "pixel_capture_atomic": False,
                    "capture_consistency": "copy is independent after completion; capture requires no concurrent edits; matching descriptors do not prove pixels were unchanged during copy",
                    "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        manifest_path = os.path.join(output_dir, "capture.json")
        try:
            with open(manifest_path, "x", encoding="utf-8") as stream:
                json.dump(manifest, stream, ensure_ascii=False, sort_keys=True, indent=2)
            array = self._array_2d(img)
            if list(array.shape) != source_shape or array.dtype != expected_dtype:
                raise RuntimeError("DM image descriptor and pixel array shape/dtype disagree; capture refused")
            working = np_.array(array[y0:y1, x0:x1], copy=True, order="C")
            if working.shape != tuple(selected_shape) or working.dtype != expected_dtype:
                raise RuntimeError("captured working array has unexpected shape or dtype")
            calibration_after = self._calib(img, 2)
            after_ndim, after_dims = self._dims(img)
            after = {"shape": list(reversed(after_dims)),
                     "data_type_code": self._safe(img.GetDataType),
                     "calibration": calibration_after}
            if after_ndim != 2 or after != before:
                raise RuntimeError("DM image descriptor changed during capture; package marked failed")
            source_calibration = calibration_before
            work_calibration = []
            for rec, start, size in zip(source_calibration, (x0, y0), selected_shape[::-1]):
                value0, scale = rec.get("calibrated_value_at_pixel_zero"), rec.get("scale")
                if value0 is None or scale is None:
                    work_zero = None
                else:
                    work_zero = float(value0) + float(start) * float(scale)
                work_calibration.append({"axis": rec.get("axis"), "scale": rec.get("scale"),
                                         "unit": rec.get("unit"),
                                         "calibrated_value_at_pixel_zero": work_zero,
                                         "size": int(size)})
            input_path = os.path.join(output_dir, "input.npy")
            with open(input_path, "xb") as stream:
                np_.save(stream, working, allow_pickle=False)
                stream.flush()
                os.fsync(stream.fileno())
            digest = hashlib.sha256()
            with open(input_path, "rb") as stream:
                while True:
                    block = stream.read(1024 * 1024)
                    if not block:
                        break
                    digest.update(block)
            input_info = {"schema_version": 1, "capture_id": capture_id,
                          "shape_yx": list(working.shape), "dtype": working.dtype.name,
                          "source_image_id": int(img.GetID()),
                          "source_shape_yx": source_shape,
                          "source_rect_xyxy": used,
                          "source_rect_convention": "zero-based half-open [x0,y0,x1,y1]",
                          "source_calibration_dm": source_calibration,
                          "working_calibration_xy": work_calibration,
                          "pixel_coordinate_model": "pixel centers at integer x,y; physical value = calibrated_value_at_pixel_zero + index*scale",
                          "intensity_calibration": {
                              "origin": self._safe(img.GetIntensityOrigin),
                              "scale": self._safe(img.GetIntensityScale),
                              "unit": self._safe(img.GetIntensityUnitString)},
                          "input_file": "input.npy", "input_sha256": digest.hexdigest(),
                          "source_path_included": False}
            with open(os.path.join(output_dir, "input.json"), "x", encoding="utf-8") as stream:
                json.dump(input_info, stream, ensure_ascii=False, sort_keys=True, indent=2)
            info_digest = hashlib.sha256(json.dumps(input_info, ensure_ascii=False, sort_keys=True,
                                                    separators=(",", ":")).encode("utf-8")).hexdigest()
            manifest.update({"state": "captured", "calibration_after": calibration_after,
                             "input_sha256": digest.hexdigest(),
                             "input_metadata_sha256": info_digest,
                             "descriptor_unchanged": True,
                             "completed_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
            with open(manifest_path, "w", encoding="utf-8") as stream:
                json.dump(manifest, stream, ensure_ascii=False, sort_keys=True, indent=2)
            del working, array
            return {"capture_id": capture_id, "state": "captured",
                    "capture_dir": output_dir, "shape_yx": selected_shape,
                    "dtype": expected_dtype.name, "source_rect_xyxy": used,
                    "input_sha256": digest.hexdigest(), "memory_estimate_bytes": estimated_peak,
                    "pixel_capture_atomic": False,
                    "note": "所有后续分析只读取此独立副本；捕获期间必须避免编辑源图。"}
        except Exception as exc:
            manifest["state"] = "failed"
            manifest["error"] = str(exc)
            try:
                with open(manifest_path, "w", encoding="utf-8") as stream:
                    json.dump(manifest, stream, ensure_ascii=False, sort_keys=True, indent=2)
            except Exception:
                pass
            raise

    # -- io ---------------------------------------------------------------
    @staticmethod
    def _script_string(value):
        # DM string literals use double quotes. Use forward slashes for Windows
        # paths, and reject control characters rather than permitting injection.
        value = str(value).replace("\\", "/")
        if any(ord(c) < 32 for c in value) or '"' in value:
            raise ValueError("DM-Script 字符串不能含双引号或控制字符")
        return '"' + value + '"'

    @staticmethod
    def _publish_file(source, destination):
        # Exclusive create is atomic and refuses existing destinations, including
        # a file another client creates after the initial existence check.
        created = False
        try:
            with open(destination, "xb") as target:
                created = True
                with open(source, "rb") as original:
                    shutil.copyfileobj(original, target, 1024 * 1024)
        except Exception:
            if created:
                os.remove(destination)
            raise

    def export(self, image_id, path, fmt):
        np_ = self._need_numpy()
        img = self._resolve(image_id)
        fmt = (fmt or "").lower().lstrip(".") or os.path.splitext(path)[1].lstrip(".").lower()
        fmt = {"tiff": "tif"}.get(fmt, fmt)
        if fmt not in ("npy", "csv", "txt", "tif", "dm4", "dm3"):
            raise ValueError("支持无损数值导出 npy/csv/txt/tif/dm4/dm3；PNG 展示图需另设明确的强度映射")
        path = os.path.abspath(path)
        suffix = os.path.splitext(path)[1].lower().lstrip(".")
        if not suffix:
            path += "." + fmt
        elif {"tiff": "tif"}.get(suffix, suffix) != fmt:
            raise ValueError("path 扩展名与 format 不一致")
        sidecar = path + ".metadata.json"
        if os.path.lexists(path) or os.path.lexists(sidecar):
            raise FileExistsError("拒绝覆盖已有导出文件或标定 sidecar: %s" % path)
        folder = os.path.dirname(os.path.abspath(path))
        if folder and not os.path.isdir(folder):
            os.makedirs(folder)
        ndim, dims = self._dims(img)
        calibration = self._calib(img, ndim)
        metadata = {"source_id": int(img.GetID()), "source_name": self._safe(img.GetName),
                    "source_file": self._source_files.get(int(img.GetID())),
                    "shape": list(reversed(dims)), "dm_dimensions": dims,
                    "shape_order": "numpy (last axis is X)", "calibration": calibration,
                    "intensity_calibration": {
                        "origin": self._safe(img.GetIntensityOrigin),
                        "scale": self._safe(img.GetIntensityScale),
                        "unit": self._safe(img.GetIntensityUnitString)},
                    "data_type_code": self._safe(img.GetDataType),
                    "format": fmt, "data_mode": "raw numerical data; no display scaling",
                    "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        writer = None
        with tempfile.TemporaryDirectory(prefix=".dm_mcp_export_", dir=folder) as staging:
            # Only this newly created directory is removed by TemporaryDirectory.
            if os.path.commonpath([os.path.abspath(staging), folder]) != folder:
                raise RuntimeError("导出临时目录超出目标文件夹")
            stagebase = os.path.join(staging, "export")
            if fmt in ("npy", "csv", "txt", "tif"):
                self._guard(img, dims)
                a = np_.asarray(_arr(img))
                metadata["dtype"] = str(a.dtype)
                if fmt == "tif":
                    helper_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lossless_tiff.py")
                    spec = importlib.util.spec_from_file_location("dm_mcp_lossless_tiff", helper_path)
                    helper = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(helper)
                    metadata["tiff"] = helper.write_tiff(stagebase, a, _j(metadata))
                    writer = "dm_mcp.lossless_tiff (uncompressed original dtype; no DM display preferences)"
                elif fmt == "npy":
                    with open(stagebase, "xb") as stream:
                        np_.save(stream, a, allow_pickle=False)
                    writer = "numpy.save (original dtype and shape)"
                else:
                    if a.ndim > 2 or a.dtype.kind not in "biuf":
                        raise ValueError("csv/txt 只支持一维/二维实数数据；多维/复数数据请用 npy")
                    flat = a.reshape(-1, a.shape[-1]) if a.ndim > 1 else a.reshape(-1, 1)
                    with open(stagebase, "x") as stream:
                        np_.savetxt(stream, flat, delimiter="," if fmt == "csv" else "\t",
                                    fmt="%d" if a.dtype.kind in "biu" else "%.17g")
                    writer = "numpy.savetxt (integer exact or 17 significant digits)"
            else:
                doc = img.GetOrCreateImageDocument()
                if int(doc.CountImages()) != 1:
                    raise RuntimeError("原生导出要求文档仅含一幅图，避免将其它图像一同保存；请先裁剪/另建副本")
                handler = "Gatan Format" if fmt == "dm4" else "Gatan 3 Format"
                doc.SaveToFile(handler, stagebase)
                writer = "ImageDocument.SaveToFile(%s)" % handler
                outputs = [os.path.join(staging, f) for f in os.listdir(staging)
                           if os.path.isfile(os.path.join(staging, f))]
                if len(outputs) != 1:
                    raise RuntimeError("原生 writer 未生成唯一文件；请查看 DM Results（找到 %d 个文件）" % len(outputs))
                stagebase = outputs[0]
                with open(stagebase, "rb") as stream:
                    signature = stream.read(4)
                valid = (signature in (b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+") if fmt == "tif"
                         else signature == b"\x00\x00\x00" + bytes([4 if fmt == "dm4" else 3]))
                if not valid:
                    raise RuntimeError("导出内容签名与请求的 %s 格式不符: %r" % (fmt, signature))
                metadata["file_signature_hex"] = signature.hex()
            digest = hashlib.sha256()
            with open(stagebase, "rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            metadata["sha256"] = digest.hexdigest()
            metadata["writer"] = writer
            # Reserve sidecar before publishing data so neither file can overwrite
            # an existing result. A failure cleans up only this call's new files.
            sidecar_created = False
            try:
                with open(sidecar, "x", encoding="utf-8") as stream:
                    sidecar_created = True
                    json.dump(_j(metadata), stream, ensure_ascii=False, indent=2, allow_nan=False)
                self._publish_file(stagebase, path)
            except Exception:
                if sidecar_created:
                    os.remove(sidecar)
                raise
        return {"exported": True, "path": path, "actual_path": path, "format": fmt,
                "exists": True, "size_bytes": os.path.getsize(path),
                "sha256": metadata["sha256"], "metadata_path": sidecar,
                "writer": writer, "data_mode": "raw numerical data; no display scaling",
                "note": "标定记录于 sidecar；原生格式的可重读强度/标定仍需验收；未调用源文档 SetCurrentFile/Save"}

    @staticmethod
    def _windows_short_path(path):
        """Read-only Win32 fallback for GMS's legacy non-ASCII path handling.

        No copy, rename, or source modification is performed. A short name is
        accepted only when it is ASCII and the OS confirms the identical file.
        """
        if os.name != "nt" or str(path).isascii():
            return None
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        get_short = kernel32.GetShortPathNameW
        get_short.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
        get_short.restype = wintypes.DWORD
        needed = get_short(path, None, 0)
        if not needed:
            raise ctypes.WinError(ctypes.get_last_error())
        buffer = ctypes.create_unicode_buffer(needed)
        written = get_short(path, buffer, needed)
        if not written or written >= needed:
            raise ctypes.WinError(ctypes.get_last_error())
        short_path = buffer.value
        if not short_path.isascii() or not os.path.isfile(short_path):
            raise RuntimeError("GetShortPathNameW 未返回存在的 ASCII 文件路径")
        if not os.path.samefile(path, short_path):
            raise RuntimeError("GetShortPathNameW 路径未通过 samefile 验证")
        return short_path

    def _try_open_document(self, path):
        errors = []
        doc = None
        method = None
        # OpenImage is the documented image-loading API, including the official
        # dm3/dm4 batch-processing example. Some GMS installations reject these
        # files through NewImageDocumentFromFile even when OpenImage works.
        opener = getattr(self.DM, "OpenImage", None)
        if opener is not None:
            try:
                img = opener(path)
                if img is None or not bool(img.IsValid()):
                    raise RuntimeError("OpenImage 返回无效图像")
                _, dims = self._dims(img)
                if not dims or any(v <= 0 for v in dims):
                    raise RuntimeError("OpenImage 返回空尺寸")
                doc = img.GetOrCreateImageDocument()
                if doc is None or not bool(doc.IsValid()) or int(doc.CountImages()) <= 0:
                    doc = None
                    raise RuntimeError("OpenImage 的图像没有有效的非空文档")
                method = "DigitalMicrograph.OpenImage"
            except Exception as exc:
                doc = None
                errors.append({"method": "DigitalMicrograph.OpenImage", "path": path,
                               "error": "%s: %s" % (type(exc).__name__, exc)})
        if doc is None:
            try:
                doc = self.DM.NewImageDocumentFromFile(path)
                if doc is None or not bool(doc.IsValid()) or int(doc.CountImages()) <= 0:
                    doc = None
                    raise RuntimeError("NewImageDocumentFromFile 返回无效或空文档")
                method = "DigitalMicrograph.NewImageDocumentFromFile"
            except Exception as exc:
                doc = None
                errors.append({"method": "DigitalMicrograph.NewImageDocumentFromFile", "path": path,
                               "error": "%s: %s" % (type(exc).__name__, exc)})
        return doc, method, errors

    def open_file(self, path, show):
        path = os.path.abspath(path)
        if not os.path.isfile(path):
            raise RuntimeError("文件不存在: %s" % path)
        if os.path.getsize(path) > MAX_NATIVE_OPEN_BYTES:
            raise RuntimeError("整文档原生打开超过有界内存策略上限；4D uint8 DM4请使用dm_4dstem_open分块只读路线")
        opened_path = path
        path_resolution = "original"
        doc, method, errors = self._try_open_document(path)
        if doc is None and os.name == "nt" and not path.isascii():
            try:
                short_path = self._windows_short_path(path)
                if short_path:
                    opened_path = short_path
                    path_resolution = "windows_short_path"
                    doc, method, short_errors = self._try_open_document(short_path)
                    errors.extend(short_errors)
            except Exception as exc:
                errors.append({"method": "Win32.GetShortPathNameW", "path": path,
                               "error": "%s: %s" % (type(exc).__name__, exc)})
        if doc is None:
            raise RuntimeError("DM 打开失败（%s）: %s" % (path, json.dumps(errors, ensure_ascii=False)))
        ids = []
        images = []
        for k in range(int(doc.CountImages())):
            image = doc.GetImage(k)
            if not bool(image.IsValid()):
                raise RuntimeError("文件打开后文档包含无效图像（index=%d）" % k)
            ndim, dims = self._dims(image)
            if any(v <= 0 for v in dims):
                raise RuntimeError("文件打开后图像尺寸无效（index=%d）" % k)
            iid = int(image.GetID())
            ids.append(iid)
            images.append({"id": iid, "name": self._safe(image.GetName),
                           "shape": list(reversed(dims)), "dm_dimensions": dims,
                           "ndim": ndim, "calibration": self._calib(image, ndim)})
        if not ids:
            raise RuntimeError("DM 返回零图像文档；不标记 opened=true")
        source_stat = os.stat(path)
        source = {"path": path, "opened_path": opened_path,
                  "path_resolution": path_resolution,
                  "same_file_verified": os.path.samefile(path, opened_path),
                  "size_bytes": int(source_stat.st_size),
                  "mtime_ns": str(source_stat.st_mtime_ns)}
        for iid in ids:
            self._source_files[iid] = dict(source)
        self._opened_documents[tuple(ids)] = doc
        if show:
            try:
                doc.Show()
            except Exception as exc:
                raise RuntimeError("已读取 image_ids=%s，但显示文档失败: %s" % (ids, exc))
        return {"opened": True, "path": path, "opened_path": opened_path,
                "path_resolution": path_resolution, "source_file": source,
                "doc_name": self._safe(doc.GetName), "image_ids": ids,
                "images": images, "method": method, "shown": bool(show),
                "open_attempt_errors": errors}

    def crop(self, image_id, rect, name):
        """Crop natively inside DM so nothing large crosses the bridge.

        DM-Script sub-image syntax is img[top,left,bottom,right], with
        NONinclusive bottom/right (Scripting manual, Image Subareas).
        ImageClone is required to detach the result from its parent. A fresh
        internal image label is a one-shot result handoff, not a user display
        name; missing or duplicate handoffs fail without touching other images.
        """
        img = self._resolve(image_id)
        ndim, dims = self._dims(img)
        if ndim != 2:
            raise RuntimeError(
                "%dD 数据不能直接裁剪；请用 dm_run_script 配 Slice3()/Slice2() 取一个 2D 切片，"
                "再对切片调用 dm_crop 或其它分析工具。当前形状: %s"
                % (ndim, "x".join(str(v) for v in dims))
            )
        if rect is None:
            raise ValueError("crop requires an explicit rect")
        x0, y0, x1, y1 = _rect_bounds((dims[1], dims[0]), rect)
        label = (name or ("crop_%dx%d" % (x1 - x0, y1 - y0)))
        label = label.replace('"', "'").replace("\\", "/").replace("\n", " ").replace("\r", " ")
        sid = int(img.GetID())
        operation_token = "dm_mcp_crop_" + uuid.uuid4().hex
        script = (
            'image src := FindImageByID(%d)\n'
            'image dst := ImageClone( src[%d, %d, %d, %d] )\n'
            'SetName(dst, "%s")\n'
            'ShowImage(dst)\n'
        ) % (sid, y0, x0, y1, x1, operation_token)

        before = set(int(i.GetID()) for _, _, _, i in self._iter_images())
        self.DM.ExecuteScriptString(script)
        made = [i for _, _, _, i in self._iter_images()
                if int(i.GetID()) not in before and int(i.GetID()) != sid
                and self._safe(i.GetName) == operation_token]
        if len(made) != 1:
            raise RuntimeError(
                "CROP_RESULT_UNVERIFIED: expected exactly one new image carrying this "
                "operation token, found %d. No existing/unrelated image was selected "
                "or recalibrated; inspect DM Results. Do not automatically retry." % len(made)
            )
        target = made[0]
        nw, nh = int(target.GetImgWidth()), int(target.GetImgHeight())
        expected = [y1 - y0, x1 - x0]
        if [nh, nw] != expected:
            raise RuntimeError("DM 裁剪尺寸错误：期望 %s，实际 %s（new_image_id=%d）"
                               % (expected, [nh, nw], int(target.GetID())))
        # Format 0 is explicitly documented as the calibrated value at pixel 0.
        # Shift only the NEW image calibration; source pixels/tags remain untouched.
        for dimension, offset in ((0, x0), (1, y0)):
            origin_at_zero, scale, units = img.GetDimensionCalibration(dimension, 0)
            target.SetDimensionCalibration(dimension, origin_at_zero + offset * scale,
                                           scale, units, 0)
        # Apply the human-readable name only after ownership and shape checks.
        target.SetName(label)
        source_file = self._source_files.get(sid)
        if source_file is not None:
            provenance = dict(source_file)
            provenance["processing_history"] = list(source_file.get("processing_history", [])) + [
                {"operation": "crop", "source_image_id": sid,
                 "rect": [x0, y0, x1, y1], "rect_convention": "right/bottom excluded"}]
            self._source_files[int(target.GetID())] = provenance
        return {
            "source_id": sid,
            "requested_rect": list(rect),
            "effective_rect": [x0, y0, x1, y1],
            "result_identity": {"method": "per-operation nonce and new image id",
                                "operation_token": operation_token},
            "new_image": {"id": int(target.GetID()), "name": self._safe(target.GetName),
                          "shape": [nh, nw], "dm_dimensions": [nw, nh],
                          "calibration": self._calib(target, 2)},
            "rect_convention": "[x0,y0,x1,y1], right/bottom excluded; strict bounds, no rounding or clipping",
            "size_verified": True,
            "note": "裁剪后的图像已显示在 DM 中；后续 dm_stats/dm_fft 请用 new_image.id",
        }

    def run_script(self, script, expect_new_image):
        if os.environ.get("DM_MCP_ALLOW_DMSCRIPT", "0") != "1":
            raise PermissionError("dm_run_script 默认关闭；必须在 DM bridge 宿主环境显式设置 DM_MCP_ALLOW_DMSCRIPT=1")
        before = set(int(img.GetID()) for _, _, _, img in self._iter_images())
        self.DM.ExecuteScriptString(script)
        after = {}
        for _, _, _, img in self._iter_images():
            i = int(img.GetID())
            after[i] = {"id": i, "name": self._safe(img.GetName),
                        "shape": list(reversed(self._dims(img)[1]))}
        new_ids = [i for i in after if i not in before]
        removed = [i for i in before if i not in after]
        out = {
            "executed": True,
            "success_verified": False,
            "script_length": len(script),
            "new_images": [after[i] for i in new_ids],
            "removed_image_ids": removed,
            "note": "executed 仅表示 ExecuteScriptString 返回；未验证脚本分析结果。检查 Results 与明确的后置条件",
        }
        if expect_new_image and not new_ids:
            out["warning"] = "脚本执行完成但没有产生新图像"
        return out


# --------------------------------------------------------------------------
# Dispatch
# --------------------------------------------------------------------------


class Dispatcher(object):
    def __init__(self, backend):
        self.backend = backend
        self.stopping = False

    def handle(self, req):
        if not isinstance(req, dict):
            raise ValueError("请求必须是 JSON object")
        op = req.get("op")
        handler = getattr(self, "op_" + str(op), None)
        if handler is None:
            raise ValueError("unknown op: %r" % (op,))
        return handler(req.get("args") or {})

    def op_ping(self, a):
        return self.backend.ping()

    def op_shutdown(self, a):
        self.stopping = True
        return {"stopping": True, "backend": self.backend.name}

    def op_list_datasets(self, a):
        return self.backend.list_datasets()

    def op_metadata(self, a):
        return self.backend.metadata(a.get("image_id"), a.get("max_depth", 8), a.get("prefix"))

    def op_stats(self, a):
        return self.backend.stats(a.get("image_id"), a.get("rect"))

    def op_capture2d(self, a):
        return self.backend.capture2d(a.get("image_id"), a.get("rect"), a.get("output_dir"))

    def op_spectrum_info(self, a):
        return self.backend.spectrum_info(a.get("image_id"), a.get("energy_axis"), a.get("spatial_bounds"))

    def op_fourdstem_open(self, a):
        return self.backend.fourdstem_open(a.get("path"), a.get("scan_axes"), a.get("detector_axes"))

    def op_fourdstem_read(self, a):
        return self.backend.fourdstem_read(a.get("dataset_id"), a.get("scan_bounds"))

    def op_fourdstem_virtual(self, a):
        return self.backend.fourdstem_virtual(a.get("dataset_id"), a.get("scan_bounds"), a.get("detectors"), a.get("chunk_patterns", 128))

    def op_spectrum(self, a):
        return self.backend.spectrum(a.get("image_id"), a.get("energy_axis"),
                    a.get("spatial_bounds"), a.get("reduction", "sum"), a.get("energy_window_eV"))

    def op_spectrum_integrate(self, a):
        return self.backend.spectrum_integrate(a.get("image_id"), a.get("energy_axis"),
                    a.get("energy_window_eV"), a.get("spatial_bounds"))

    def op_spectrum_export(self, a):
        if not a.get("path"):
            raise ValueError("需要新的 CSV path")
        return self.backend.spectrum_export(a.get("image_id"), a.get("energy_axis"), a["path"],
                    a.get("spatial_bounds"), a.get("reduction", "sum"), a.get("energy_window_eV"))

    def op_profile(self, a):
        return self.backend.profile(
            a.get("image_id"), a.get("x0", 0), a.get("y0", 0), a.get("x1", 1), a.get("y1", 0),
            a.get("width", 1),
        )

    def op_fft(self, a):
        return self.backend.fft(a.get("image_id"), a.get("rect"), a.get("top_n", 12))

    def op_export(self, a):
        path = a.get("path")
        if not path:
            raise ValueError("需要 path")
        return self.backend.export(a.get("image_id"), path, a.get("format"))

    def op_open_file(self, a):
        path = a.get("path")
        if not path:
            raise ValueError("需要 path")
        return self.backend.open_file(path, a.get("show", True))

    def op_crop(self, a):
        rect = a.get("rect")
        if not rect or len(rect) != 4:
            raise ValueError("需要 rect = [x0, y0, x1, y1]")
        return self.backend.crop(a.get("image_id"), rect, a.get("name"))

    def op_run_script(self, a):
        if os.environ.get("DM_MCP_ALLOW_DMSCRIPT", "0") != "1":
            raise PermissionError("dm_run_script 默认关闭；需在 bridge 环境显式设置 DM_MCP_ALLOW_DMSCRIPT=1")
        script = a.get("script") or ""
        if not script.strip():
            raise ValueError("需要 script")
        return self.backend.run_script(script, a.get("expect_new_image", False))


def serve(dispatcher):
    try:
        address = ipaddress.ip_address(HOST)
    except ValueError:
        raise ValueError("DM_BRIDGE_HOST 必须是 IPv4 loopback 地址（推荐 127.0.0.1）")
    if address.version != 4 or not address.is_loopback:
        raise ValueError("桥仅允许绑定 IPv4 loopback 地址，拒绝 %s" % HOST)
    if IDLE_TIMEOUT < 0 or CLIENT_IDLE_TIMEOUT <= 0:
        raise ValueError("idle timeout 必须非负，client idle timeout 必须大于零")
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((HOST, PORT))
    srv.listen(8)
    srv.settimeout(0.5)
    log("listening on %s:%d (backend=%s, scope=analysis)" % (HOST, PORT, dispatcher.backend.name))
    last_request = time.monotonic()
    try:
        while not dispatcher.stopping:
            if IDLE_TIMEOUT and time.monotonic() - last_request >= IDLE_TIMEOUT:
                log("idle timeout reached; stopping")
                break
            try:
                conn, addr = srv.accept()
            except socket.timeout:
                continue
            log("client %s connected" % (addr,))
            conn.settimeout(0.5)
            buffer = b""
            last_data = time.monotonic()
            try:
                while not dispatcher.stopping:
                    if time.monotonic() - last_data >= CLIENT_IDLE_TIMEOUT:
                        log("client idle timeout")
                        break
                    if IDLE_TIMEOUT and time.monotonic() - last_request >= IDLE_TIMEOUT:
                        dispatcher.stopping = True
                        break
                    try:
                        chunk = conn.recv(65536)
                    except socket.timeout:
                        continue
                    if not chunk:
                        break
                    last_data = time.monotonic()
                    buffer += chunk
                    if len(buffer) > MAX_REQUEST_BYTES:
                        raise ValueError("请求超出最大字节数 %d" % MAX_REQUEST_BYTES)
                    while b"\n" in buffer and not dispatcher.stopping:
                        line, buffer = buffer.split(b"\n", 1)
                        if not line.strip():
                            continue
                        req = {}
                        last_request = time.monotonic()
                        try:
                            req = json.loads(line.decode("utf-8"))
                            result = dispatcher.handle(req)
                            resp = {"id": req.get("id"), "ok": True, "result": _j(result)}
                        except Exception as exc:
                            log("error: %s" % exc)
                            resp = {"id": req.get("id") if isinstance(req, dict) else None, "ok": False,
                                    "error": "%s: %s" % (type(exc).__name__, exc),
                                    "traceback": traceback.format_exc(limit=4)}
                        conn.sendall((json.dumps(resp, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8"))
                        last_request = time.monotonic()
                        # Synchronous analysis time is active work, not client
                        # inactivity. Start the idle window after the response.
                        last_data = last_request
            except Exception as exc:
                log("connection dropped: %s" % exc)
            finally:
                conn.close()
                log("client disconnected")
    finally:
        srv.close()
        log("bridge stopped; Python execution slot released")


def main():
    if MOCK:
        backend = MockBackend()
    else:
        # A missing DM host is an error, never a successful synthetic fallback.
        import DigitalMicrograph as DM  # noqa: N806

        backend = DmBackend(DM)
        if bool(DM.IsScriptOnMainThread()):
            raise RuntimeError("常驻桥必须勾选 Execute in background；前台运行会阻塞 DM 界面且无法中断")
    serve(Dispatcher(backend))


if __name__ == "__main__":
    main()
