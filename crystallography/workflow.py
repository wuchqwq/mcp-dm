"""Reproducible external selected-point workflow over an existing DM handoff.

Run from this checkout in a separate Python environment. No host imports,
native requests, hidden operator fallback, source writes or network access.
"""
import csv
import hashlib
import html
import io
import json
import math
import os
from pathlib import Path
import platform
import re
import sys

import numpy as np
import scipy
import ase

from . import __version__
from .capture import load_capture
from .geometry import calibration_map, measure_geometry, require, NonIdentifiableGeometry
from .indexing import index_cubic


MAX_REQUEST_BYTES = 1024 * 1024


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read_request(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= MAX_REQUEST_BYTES,
            "Bounded ordinary JSON request required")
    raw = path.read_bytes()
    require(len(raw) <= MAX_REQUEST_BYTES, "Request exceeded byte budget")
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "Duplicate request key")
            result[key] = value
        return result
    value = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=pairs,
                       parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Nonfinite request JSON")))
    require(type(value) is dict and type(value.get("schema_version")) is int and value["schema_version"] == 1,
            "Request schema_version must be 1")
    require(value.get("coordinate_frame") == "source_pixel_centers_xy",
            "Coordinates must explicitly use source_pixel_centers_xy")
    return value, raw


def _path(base, value):
    require(type(value) is str and value and not any(ord(c) < 32 for c in value), "Explicit bounded input path required")
    path = Path(value)
    return path if path.is_absolute() else base / path


def _index(vectors, calibrated, spec, reference=None):
    models = spec.get("models", ["FCC", "BCC", "HCP", "P"]) if reference is None else [reference["model"]]
    require(type(models) is list and 1 <= len(models) <= 4 and len(set(models)) == len(models) and
            set(models) <= {"FCC", "BCC", "HCP", "P"}, "Select distinct FCC/BCC/HCP/P models")
    common = {key: spec[key] for key in ("max_index", "relative_tolerance", "angle_tolerance_deg", "max_candidates", "max_unmatched") if key in spec}
    cubic = {"FCC": "F", "BCC": "I", "P": "P"}
    result = []
    non_identifiable = None
    for model in models:
        if model == "HCP":
            from .hexagonal import index_hcp
            kw = dict(common)
            if reference is None:
                kw.update({k: spec[k] for k in ("c_over_a", "c_over_a_candidates") if k in spec})
                if not any(k in kw for k in ("c_over_a", "c_over_a_candidates")):
                    kw["c_over_a_candidates"] = [1.50, 1.55, 1.58, 1.60, math.sqrt(8/3),
                                                   1.65, 1.70, 1.75, 1.80, 1.85, 1.90]
            else:
                kw.update(lattice_parameter_a_nm=reference["lattice_parameter_a_nm"], c_over_a=reference["c_over_a"])
            try:
                record = index_hcp(vectors, calibrated=calibrated, **kw)
            except NonIdentifiableGeometry as error:
                non_identifiable = error
                continue
        else:
            kw = dict(common, centerings=[cubic[model]])
            if reference is not None:
                kw["candidate_lattice_nm"] = {cubic[model]: reference["lattice_parameter_nm"]}
            try:
                record = index_cubic(vectors, calibrated=calibrated, **kw)
            except NonIdentifiableGeometry as error:
                non_identifiable = error
                continue
        record["requested_model"] = model
        result.append(record)
    if non_identifiable is not None:
        # Validate every requested model's options before preserving a review
        # result. A malformed later model must still fail the whole request.
        raise non_identifiable
    return {"model_results": result, "chemical_phase_identified": False,
            "compatible_models": [r["requested_model"] for r in result if r["candidates"]],
            "comparison_policy": "Same frozen measured vectors and declared tolerance for every model; intensity/absence not scored; finite geometry candidates only"}


def _overlay(array, spots, center, source_roi):
    """Bounded SVG position check; sampled display intensities are not data export."""
    h, w = array.shape
    stride = max(1, math.ceil(max(w, h) / 96))
    sampled = array[::stride, ::stride].astype(float)
    lo, hi = float(sampled.min()), float(sampled.max())
    gray = np.zeros(sampled.shape, dtype=np.uint8) if hi == lo else np.asarray(np.clip((sampled-lo)/(hi-lo)*255, 0, 255), dtype=np.uint8)
    margin, extent = max(w, h) * .06, max(w, h)
    pieces = ['<svg xmlns="http://www.w3.org/2000/svg" width="720" height="760" viewBox="{} {} {} {}">'.format(-margin, -margin, w+2*margin, h+3*margin),
              '<title>Display-only selected spot coordinates; scientific values remain in the NPY</title>',
              '<rect x="-.5" y="-.5" width="{}" height="{}" fill="black"/>'.format(w, h)]
    for y in range(gray.shape[0]):
        for x in range(gray.shape[1]):
            g = int(gray[y, x])
            pieces.append('<rect x="{}" y="{}" width="{}" height="{}" fill="rgb({},{},{})"/>'.format(x*stride-.5, y*stride-.5, stride, stride, g, g, g))
    radius = extent * .012
    for spot in spots:
        x, y = spot["xy"]
        pieces.append('<circle cx="{}" cy="{}" r="{}" fill="none" stroke="#ff5050" stroke-width="{}"/>'.format(x, y, radius, radius/4))
        pieces.append('<text x="{}" y="{}" font-size="{}" fill="#ffff60">{}</text>'.format(x+radius, y-radius, extent*.025, html.escape(spot["id"])))
    if center is not None:
        x, y = center
        pieces.append('<path d="M {} {} h {} M {} {} v {}" stroke="#00ffff" stroke-width="{}"/>'.format(x-2*radius, y, 4*radius, x, y-2*radius, 4*radius, radius/3))
    pieces.append('<text x="0" y="{}" font-size="{}" fill="#333">Source offset {}. Display only; captured pixel centres.</text></svg>'.format(h+margin, extent*.023, html.escape(str(source_roi[:2]))))
    return "\n".join(pieces).encode("utf-8")


def analyse(request, base):
    require(set(request) <= {"schema_version", "coordinate_frame", "source", "center", "spots",
                             "calibration", "detection", "indexing", "references"}, "Unsupported workflow parameter")
    source = request.get("source", {})
    require(type(source) is dict, "Explicit source required")
    kind = source.get("kind")
    capture = load_capture(_path(base, source.get("capture_directory")), kind,
                           expected_capture_id=source.get("expected_capture_id"),
                           expected_session=source.get("expected_session"), expected_host_pid=source.get("expected_host_pid"))
    spec = request.get("indexing", {})
    require(type(spec) is dict, "Indexing options must be an object")
    require(set(spec) <= {"enabled", "models", "max_index", "relative_tolerance", "angle_tolerance_deg",
                          "max_candidates", "max_unmatched", "c_over_a", "c_over_a_candidates"}, "Unsupported indexing option")
    require(type(spec.get("enabled", True)) is bool, "Indexing enabled must be boolean")
    center = request.get("center", {"mode": "frequency_grid_dc" if kind == "fft" else "auto"})
    require(type(center) is dict, "Centre specification must be an object")
    sigma = center.get("sigma_px")
    if kind == "fft":
        require(center.get("mode") == "frequency_grid_dc", "FFT centre must come from its mathematical frequency grid, not image midpoint or brightness")
        axes = capture.frequency_axes_cycles_per_nm()
        center_local = [-axis["calibrated_value_at_pixel_zero"] / axis["scale"] for axis in axes]
        mapping = calibration_map({"mode": "capture_axes", "convention": "cycles_per_length",
                                   **({"scale_sigma_xy": request["calibration"]["scale_sigma_xy"]} if "scale_sigma_xy" in request.get("calibration", {}) else {})}, axes)
        center_note = "Recorded native Fourier mathematical DC; may be outside ROI. No half-bin display calibration substituted."
        if sigma is None:
            sigma = [0., 0.]  # Mathematical bin origin, not an estimated physical beam.
    else:
        cal = request.get("calibration")
        if type(cal) is dict and cal.get("mode") == "explicit" and "zero_xy" in cal:
            require(cal.get("zero_frame") in ("source_pixel_zero", "capture_pixel_zero"),
                    "An explicit zero_xy must declare zero_frame: source_pixel_zero or capture_pixel_zero")
            if cal["zero_frame"] == "source_pixel_zero":
                from .geometry import vector2
                zero = vector2(cal["zero_xy"], "source physical zero")
                scale = vector2(cal.get("scale_xy"), "explicit signed scale")
                cal = dict(cal, zero_xy=(zero + np.asarray(capture.source_roi[:2])*scale).tolist())
        mapping = calibration_map(cal, capture.coordinate_axes)
        mapping["original_declaration"] = request.get("calibration")
        mapping["normalized_zero_frame"] = "capture_pixel_zero"
        if center.get("mode") == "user_confirmed":
            center_local = capture.source_to_local_xy([center.get("xy")])[0]
            center_note = "User-confirmed diffraction centre; no centre inferred from image midpoint"
        else:
            require(center.get("mode") == "auto", "Unknown diffraction centre mode")
            center_local = None
            center_note = "Automatic Friedel-pair centre; independent of structure fitting"
    selected = request.get("spots", "auto")
    detection = None
    if selected == "auto" or center_local is None:
        require(selected == "auto", "Automatic centre currently requires automatic spots; or supply an explicit centre")
        from .detection import detect_spots
        options = request.get("detection", {})
        require(type(options) is dict and set(options) <= {"max_spots", "min_distance", "threshold_rel", "exclude_radius", "center_tolerance_px"}, "Unsupported detection option")
        if spec.get("enabled", True):
            require(type(options.get("max_spots", 12)) is int and 3 <= options.get("max_spots", 12) <= 12,
                    "Automatic indexing needs detection.max_spots within 3..12; disable indexing for larger measurement tables")
        detection = detect_spots(capture.array, center_xy=center_local, **options)
        center_local, selected = detection["center_xy"], detection["spots"]
        if detection["status"] != "READY":
            capture.assert_unchanged()
            return {"state": "NEEDS_REVIEW", "reason": "automatic centre/spot evidence insufficient; inspect overlay and supply centre/spots",
                    "detection": detection, "source": capture.provenance, "chemical_phase_identified": False}, capture, _overlay(capture.array, selected, center_local, capture.source_roi), []
    else:
        require(type(selected) is list and 1 <= len(selected) <= 128, "Explicit spots list or auto required")
        local = capture.source_to_local_xy([spot.get("xy") for spot in selected])
        selected = [dict(spot, xy=xy) for spot, xy in zip(selected, local)]
    measurement = measure_geometry(center_local, selected, mapping, sigma)
    for item in measurement["spots"]:
        item["source_xy"] = [item["xy"][dim] + capture.source_roi[dim] for dim in range(2)]
        item["coordinate_frame"] = "capture_pixel_centers_xy"
    measurement["center_source_xy"] = [center_local[dim] + capture.source_roi[dim] for dim in range(2)]
    measurement["center_basis"] = center_note
    indexed = None
    references, reference_results = [], []
    insufficient = spec.get("enabled", True) and not 3 <= len(selected) <= 12
    review_reason = "Joint indexing needs 3..12 noncollinear reflections; measured table remains available" if insufficient else None
    if spec.get("enabled", True) and not insufficient:
        require(mapping["geometry_usable"], "Cannot index physical geometry without calibration or explicit isotropic relative-geometry confirmation")
        vectors = [spot["g_xy_cycles_per_nm"] if mapping["calibrated"] else spot["relative_vector_xy"] for spot in measurement["spots"]]
        entries = request.get("references", [])
        require(type(entries) is list and len(entries) <= 8, "At most eight explicit CIF references")
        for entry in entries:
            from .structures import load_reference
            reference = load_reference(_path(base, entry.get("cif")), label=entry.get("label"), model=entry.get("model"))
            require(mapping["calibrated"], "Fixed CIF lattice comparison requires absolute calibration; no scale fitting allowed")
            references.append(reference)
        try:
            indexed = _index(vectors, mapping["calibrated"], spec)
        except NonIdentifiableGeometry as error:
            insufficient = True
            review_reason = str(error) + "; measured table remains available"
        for reference in references:
            try:
                comparison = _index(vectors, True, spec, reference)
            except NonIdentifiableGeometry as error:
                insufficient = True
                review_reason = str(error) + "; measured table remains available"
                reference_results.append({"reference": reference, "comparison": None, "review_reason": str(error)})
            else:
                reference_results.append({"reference": reference, "comparison": comparison})
    capture.assert_unchanged()
    return {"state": "NEEDS_REVIEW" if insufficient else "COMPLETE", "computation_source": "explicit_external_python_crystallography",
            "review_reason": review_reason,
            "source": capture.provenance, "saved_source_metadata": capture.metadata,
            "measurement": measurement, "indexing": indexed, "reference_comparisons": reference_results,
            "detection": detection, "chemical_phase_identified": False, "dm_called": False,
            "live_source_reobserved": False, "result_returned_to_dm": False}, capture, _overlay(capture.array, selected, center_local, capture.source_roi), references


def write_new(path, payload):
    with path.open("xb") as out:
        out.write(payload)
        out.flush()
        os.fsync(out.fileno())


def run(request_path, output_path, request_id):
    require(type(request_id) is str and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", request_id), "Save an explicit bounded request_id before invoking the companion")
    request_path = Path(request_path).resolve(strict=True)
    request, raw = read_request(request_path)
    output_arg = Path(output_path)
    require(not output_arg.exists() and not output_arg.is_symlink(), "Output must be a new directory; use verify for an existing result")
    parent = output_arg.parent.resolve(strict=True)
    require(parent.is_dir() and output_arg.name not in ("", ".", ".."), "Existing output parent required")
    output = parent / output_arg.name
    # Numerical work has no side effects. All input validation precedes output creation.
    result, capture, overlay, references = analyse(request, request_path.parent)
    require(capture.path != output and capture.path not in output.parents, "Result must be outside its source capture")
    files = {"request.json": raw, "results.json": canonical(dict(result, request_id=request_id)) + b"\n", "positions.svg": overlay}
    rows = result.get("measurement", {}).get("spots", [])
    stream = io.StringIO(newline="")
    columns = ["id", "source_x", "source_y", "gx_cycles_per_nm", "gy_cycles_per_nm", "d_nm", "d_sigma_nm", "length_ratio_to_first", "uncertainty_status"]
    writer = csv.writer(stream); writer.writerow(columns)
    for spot in rows:
        writer.writerow([spot["id"], *spot["source_xy"], *(spot["g_xy_cycles_per_nm"] or [None, None]),
                         spot["d_nm"], spot["d_sigma_nm"], spot["length_ratio_to_first"], spot["uncertainty_status"]])
    files["measurements.csv"] = stream.getvalue().encode("utf-8")
    # Preserve the exact companion source, request and optional CIFs alongside results.
    for code in sorted(Path(__file__).parent.glob("*.py")):
        files["code_" + code.name] = code.read_bytes()
    files["code_shared_verify_native_region.py"] = (Path(__file__).resolve().parents[1]/"tools/verify_native_region.py").read_bytes()
    for number, reference in enumerate(references):
        payload = Path(reference["source"]["path"]).read_bytes()
        require(sha(payload) == reference["source"]["sha256"], "Reference CIF changed after parsing")
        files["reference-{}.cif".format(number)] = payload
    files["parameters.json"] = canonical({"request_id": request_id, "request_sha256": sha(raw),
        "companion_version": __version__, "python": sys.version, "numpy": np.__version__, "scipy": scipy.__version__, "ase": ase.__version__,
        "platform": platform.platform(), "input_capture_directory": str(capture.path),
        "input_files_sha256": capture.provenance["capture_files_sha256"],
        "code_sha256": {name: sha(data) for name, data in files.items() if name.startswith("code_")},
        "source_writes": False, "dm_called": False}) + b"\n"
    original_record = canonical({"schema_version": 1, "request_id": request_id,
        "request_sha256": sha(raw), "state": "CREATED", "action": "external_crystallography_analysis"})
    files = {"request-record.json": original_record, **files}
    capture.assert_unchanged()
    output.mkdir()  # Exclusive; no existing file or prior result can be replaced.
    for name, data in files.items():
        write_new(output / name, data)
    capture.assert_unchanged()
    manifest = {"schema_version": 1, "request_id": request_id, "state": result["state"],
                "files_sha256": {name: sha(data) for name, data in files.items()},
                "source_verified_unchanged": True, "dm_called": False}
    write_new(output / "manifest.json", canonical(manifest) + b"\n")  # Completion marker written last.
    return {"state": result["state"], "request_id": request_id, "output": str(output),
            "compatible_models": (result.get("indexing") or {}).get("compatible_models", []),
            "absolute_calibration": (result.get("measurement") or {}).get("calibration", {}).get("calibrated"),
            "chemical_phase_identified": False}


def verify(output_path):
    folder = Path(output_path).resolve(strict=True)
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    require(manifest.get("state") in ("COMPLETE", "NEEDS_REVIEW") and manifest.get("schema_version") == 1,
            "No complete result marker; never automatically repeat an incomplete output")
    required = {"request-record.json", "request.json", "results.json", "parameters.json", "positions.svg", "measurements.csv",
                "code_workflow.py", "code_geometry.py", "code_capture.py", "code_indexing.py", "code_hexagonal.py",
                "code_detection.py", "code_structures.py", "code_shared_verify_native_region.py"}
    require(type(manifest.get("files_sha256")) is dict and required <= set(manifest["files_sha256"]),
            "Completion marker omits required scientific output or source files")
    for name, expected in manifest["files_sha256"].items():
        require(Path(name).name == name and not (folder/name).is_symlink() and sha((folder/name).read_bytes()) == expected,
                "Result file missing or changed: " + name)
    parameters = json.loads((folder / "parameters.json").read_text(encoding="utf-8"))
    original = json.loads((folder / "request-record.json").read_text(encoding="utf-8"))
    result = json.loads((folder / "results.json").read_text(encoding="utf-8"))
    require(parameters["request_id"] == manifest["request_id"] == original["request_id"] and
            result["request_id"] == original["request_id"] and result["state"] == manifest["state"] and
            parameters["request_sha256"] == original["request_sha256"] == sha((folder/"request.json").read_bytes()),
            "Original request identity mismatch")
    require(original.get("schema_version") == 1 and original.get("state") == "CREATED" and
            original.get("action") == "external_crystallography_analysis", "Original request record contract mismatch")
    require(parameters["code_sha256"] == {k: v for k, v in manifest["files_sha256"].items() if k.startswith("code_")},
            "Recorded source-code identity mismatch")
    source = Path(parameters["input_capture_directory"])
    expected_inputs = parameters.get("input_files_sha256")
    require(type(expected_inputs) is dict and {"input.npy", "input.json", "capture.json"} <= set(expected_inputs) and
            expected_inputs == result["source"].get("capture_files_sha256"), "Recorded scientific input inventory mismatch")
    saved_source = result["source"]
    reopened = load_capture(source, saved_source["source_mode_declared"],
                            expected_capture_id=saved_source["capture_id"],
                            expected_session=saved_source.get("native_session"), expected_host_pid=saved_source.get("native_host_pid"))
    require(reopened.provenance == saved_source, "Reopened saved source identity differs from result")
    for name, expected in parameters["input_files_sha256"].items():
        relative = Path(name)
        require(not relative.is_absolute() and ".." not in relative.parts and not (source/relative).is_symlink() and
                sha((source/relative).read_bytes()) == expected, "Saved input capture changed or is unavailable")
    return {"state": "VERIFIED", "analysis_state": manifest["state"], "request_id": manifest["request_id"],
            "scope": "saved files only; not a fresh DM observation"}
