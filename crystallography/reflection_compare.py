"""Bounded reflection geometry comparison over immutable saved measurements.

This module does not find peaks, fit a registration, change experimental
calibration, simulate scattering, compare display PNGs or identify a phase.
"""
import hashlib
import json
import math
from pathlib import Path
import re

import numpy as np
from scipy.optimize import linear_sum_assignment

from tools.image_calibration import UNITS, unit_kind

OBJECT_ID = re.compile(r"[a-f0-9]{32}\Z")
MAX_MEASUREMENTS = 32
MAX_REFLECTIONS = 4096
MAX_CANDIDATE_EDGES = 8192
MAX_BYTES = 2 * 1024 * 1024


class ComparisonError(ValueError):
    code = "INVALID_COMPARISON"


def require(value, message):
    if not value:
        raise ComparisonError(message)


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def decode(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "Duplicate measurement JSON key")
            result[key] = value
        return result
    return json.loads(raw.decode("utf-8"), object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ComparisonError("Nonfinite measurement JSON")))


def read(path, maximum=MAX_BYTES):
    path = Path(path)
    require(path.is_absolute() and path.is_file() and not path.is_symlink() and path.stat().st_size <= maximum,
            "Explicit bounded ordinary measurement record required")
    with path.open("rb") as stream:
        raw = stream.read(maximum + 1)
    require(0 < len(raw) <= maximum, "Measurement record exceeded byte budget")
    return raw


def load_measurement(path, _depth=0):
    """Read the narrow committed image_measure manifest/journal contract.

    The journal proves internal immutable-record consistency, not authenticity
    of an experimental calibration or the absence of unknown future revisions.
    """
    require(type(_depth) is int and 0 <= _depth <= 16, "Remeasurement ancestry exceeds budget")
    path = Path(path)
    require(path.is_absolute() and path.name == "object.json" and OBJECT_ID.fullmatch(path.parent.name) and
            path.parent.parent.name == "objects", "Use an explicit saved image_measure object.json")
    workspace = path.parent.parent.parent.resolve()
    require(path.resolve().parent.parent == workspace / "objects" and not path.parent.is_symlink(),
            "Measurement record escapes its image workspace")
    raw = read(path)
    metadata = decode(raw)
    creator = metadata.get("request_id")
    require(metadata.get("object_id") == path.parent.name and metadata.get("backend") == "external-image-workspace" and
            metadata.get("kind") == "measure" and type(creator) is str and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", creator),
            "A committed explicit image_measure result is required")
    journal_path = workspace / "requests" / (creator + ".json")
    journal_raw = read(journal_path, 4 * MAX_BYTES)
    journal = decode(journal_raw)
    parameters = journal.get("parameters", {})
    require(journal.get("request_id") == creator and journal.get("state") == "completed" and
            parameters.get("action") in ("measure", "remeasure") and parameters.get("request_id") == creator and
            Path(parameters.get("workspace", "")).resolve() == workspace and
            journal.get("parameters_sha256") == sha(canonical(parameters)) and
            journal.get("object_manifest_sha256") == sha(raw) and
            journal.get("response") == {"ok": True, "state": "completed", "backend": "external-image-workspace", "request_id": creator, **metadata},
            "Measurement manifest differs from its immutable original request")
    allowed = {"workspace", "action", "request_id", "object_id", "points", "coordinate_space"}
    if parameters["action"] == "remeasure":
        allowed = {"workspace", "action", "request_id", "object_id", "measurement_object_id", "points", "source_text"}
    require(set(parameters) <= allowed and
            type(parameters.get("object_id")) is str and OBJECT_ID.fullmatch(parameters["object_id"]) and
            metadata.get("parent_object_id") == parameters["object_id"],
            "Measurement parent object contradicts the saved original request")
    if parameters["action"] == "measure":
        require(type(parameters.get("points")) is list and
                canonical(parameters["points"]) == canonical(metadata.get("points")),
                "Measurement points contradict the saved original request")
    else:
        # Reuse the image workspace's exact original-request/point/centre
        # validator rather than maintaining a second remeasurement algorithm.
        from tools.image_workspace import Workspace
        image_workspace = Workspace(str(workspace), writable=False)
        committed, _ = image_workspace.committed_measurement(metadata["object_id"], depth=_depth)
        require(canonical(committed) == canonical(metadata),
                "Remeasurement differs from its committed image-workspace revision")
    # Omitted coordinate_space selects the actual object's domain at creation.
    # An explicit value must match; unsupported aliases are not guessed here.
    require(metadata.get("coordinate_space") in ("source_pixels", "source_array_indices", "frequency_cycles_per_pixel") and
            ("coordinate_space" not in parameters or parameters["coordinate_space"] == metadata["coordinate_space"]),
            "Measurement coordinate space contradicts the saved original request")
    require(metadata.get("files_sha256") == {}, "Only standalone image_measure metadata is accepted; no hidden scientific-file substitution")
    return metadata, {"path": str(path.resolve()), "sha256": sha(raw), "bytes": len(raw),
                      "journal_path": str(journal_path), "journal_sha256": sha(journal_raw)}, raw, journal_raw


def period(magnitude, label):
    require(finite(magnitude) and magnitude >= 0, label + " magnitude is nonfinite or negative")
    if magnitude == 0:
        return None  # Explicit DC has no finite reciprocal period.
    result = 1. / magnitude
    require(finite(result) and result > 0, label + " period overflows or underflows finite binary64")
    return result


def measurement_vector(metadata):
    record, dependency = metadata.get("xy_calibration"), metadata.get("calibration_dependency")
    require(type(record) is dict and type(dependency) is dict and record.get("status") == "active" and
            OBJECT_ID.fullmatch(record.get("calibration_id", "")) and type(record.get("revision")) is int and record["revision"] >= 1,
            "An active versioned physical calibration is required; unknown/withdrawn scales remain pixel-only")
    source = record.get("source")
    require(source in ("native_dm_capture", "user_statement_not_independently_verified") and
            all(dependency.get(k) == record.get(k) for k in ("calibration_id", "revision", "status", "source", "coordinate_domain")) and
            "stale" not in str(metadata.get("calibration_result_status", "")),
            "Measurement/calibration dependency is unknown, stale or contradictory")
    require(metadata.get("measurement_domain") == "reciprocal_space", "Reflection comparison requires reciprocal geometry, not real-space distances or pixel units")
    points, vector = metadata.get("points"), metadata.get("physical_vector_xy")
    require(type(points) is list and len(points) == 2 and all(type(p) is list and len(p) == 2 and all(finite(v) for v in p) for p in points) and
            type(vector) is list and len(vector) == 2 and all(finite(v) for v in vector), "Explicit finite measurement points/vector required")
    dc = metadata.get("dc_reference_point_index")
    require(type(dc) is int and dc in (0, 1), "A two-peak displacement is not an absolute reflection: supply an explicit DC-to-peak measurement")
    scale = record.get("xy_scale")
    require(type(scale) is dict and all(finite(scale.get(axis)) and scale[axis] != 0 for axis in ("x", "y")),
            "Finite nonzero signed XY calibration is required")
    space = metadata.get("coordinate_space")
    delta = [points[1][j] - points[0][j] for j in (0, 1)]
    if space == "frequency_cycles_per_pixel":
        require(record.get("coordinate_domain") == "real_space" and points[dc] == [0, 0],
                "A saved real-space FFT requires mathematical DC [0,0] and real-space source calibration")
        expected = [delta[0] / scale["x"], delta[1] / scale["y"]]
        scale_unit = unit_kind(scale.get("unit"))
        require(scale_unit is not None and scale_unit[0] == "real_space", "FFT source scale must be a physical length unit")
    elif space == "source_array_indices":
        require(record.get("coordinate_domain") == "reciprocal_space" and
                type(record.get("dc_index_xy")) is list and len(record["dc_index_xy"]) == 2 and
                all(finite(v) for v in record["dc_index_xy"]) and points[dc] == record["dc_index_xy"],
                "A reciprocal array requires the explicit validated calibrated DC index, never a guessed near-zero position")
        expected = [delta[0] * scale["x"], delta[1] * scale["y"]]
        scale_unit = unit_kind(scale.get("unit"))
        require(scale_unit is not None and scale_unit[0] == "reciprocal_space", "Reciprocal array scale must be an inverse-length unit")
    else:
        raise ComparisonError("Unsupported measurement coordinate space; screenshots and real-space pixel distances cannot supply reflections")
    require(all(finite(v) for v in expected) and vector == expected,
            "Saved physical vector contradicts its exact points/signed calibration; no tolerance-based repair")
    require(all(dx == 0 or value != 0 for dx, value in zip(delta, expected)),
            "A nonzero calibration component underflows to zero; no physical-vector repair")
    parsed = unit_kind(metadata.get("physical_frequency_unit"))
    require(parsed is not None and parsed[0] == "reciprocal_space" and parsed[1] == scale_unit[1],
            "Measurement frequency units differ from its calibration; radians are not cycles")
    factor = 1e-10 / UNITS[parsed[1]]
    sign = 1 if dc == 0 else -1
    q = [sign * float(v) * factor for v in vector]
    require(all(v == 0 or converted != 0 for v, converted in zip(vector, q)),
            "A nonzero reciprocal component underflows during unit conversion")
    require(all(finite(v) and abs(v) <= 1e6 for v in q) and math.hypot(*q) > 0,
            "A nonzero bounded reciprocal reflection is required; DC has no finite period")
    magnitude = math.hypot(*q)
    return {"measurement_object_id": metadata["object_id"], "measurement_request_id": metadata["request_id"],
            "source_object_id": metadata.get("source_object_id"), "coordinate_space": space,
            "original_points": points, "dc_reference_point_index": dc,
            "original_physical_vector_xy": vector, "original_physical_frequency_unit": metadata["physical_frequency_unit"],
            "conversion_to_inverse_angstrom": factor, "q_xy_inv_angstrom": q,
            "projected_period_angstrom": period(magnitude, "Experimental reciprocal"),
            "calibration_dependency": dependency, "calibration_record": record,
            "calibration_snapshot_semantics": "active at this immutable measurement version; later revisions are not discovered globally; remeasure after correction/withdrawal",
            "dc_identity_source": metadata.get("dc_identity_source", "saved FFT mathematical DC"),
            "dc_scope": "saved FFT mathematical zero frequency" if space == "frequency_cycles_per_pixel" else "explicit calibrated reciprocal origin; not independent verification of the experimental direct-beam centre",
            "experimental_beam_center_independently_verified": False,
            "uncertainty_status": metadata.get("uncertainty_status", "unknown")}


def registration(value):
    keys = {"rotation_deg", "scale", "translation_inv_angstrom", "flip_y", "basis"}
    require(type(value) is dict and set(value) == keys, "registration requires explicit rotation_deg, scale, translation_inv_angstrom, flip_y and basis")
    require(finite(value["rotation_deg"]) and abs(value["rotation_deg"]) <= 360 and
            finite(value["scale"]) and 1e-6 <= value["scale"] <= 1e6 and type(value["flip_y"]) is bool and
            type(value["translation_inv_angstrom"]) is list and len(value["translation_inv_angstrom"]) == 2 and
            all(finite(v) and abs(v) <= 1e6 for v in value["translation_inv_angstrom"]) and
            type(value["basis"]) is str and 1 <= len(value["basis"].strip()) <= 2000,
            "Invalid finite bounded explicit registration parameters/basis")
    radians = math.radians(value["rotation_deg"])
    c, s = math.cos(radians), math.sin(radians)
    reflection = np.diag([1., -1. if value["flip_y"] else 1.])
    matrix = float(value["scale"]) * np.asarray([[c, -s], [s, c]]) @ reflection
    return {**value, "matrix_xy": matrix.tolist(), "translation_xy_inv_angstrom": value["translation_inv_angstrom"],
            "convention": "q_comparison = scale * Rccw(rotation_deg) @ diag(1,flip_y?-1:1) @ q_experiment + translation",
            "parameter_source": "all explicitly caller supplied; no automatic fit", "registration_verified": False,
            "identity_parameters": value["rotation_deg"] == 0 and value["scale"] == 1 and value["translation_inv_angstrom"] == [0, 0] and not value["flip_y"],
            "experimental_calibration_modified": False,
            "scale_semantics": "comparison-only registration scale; experimental calibration remains unchanged"}


def hkl_key(row):
    require(type(row) is list and len(row) == 3 and all(finite(v) and int(v) == v and abs(v) <= 100000 for v in row),
            "Explicit simulated HKL must be three bounded integers")
    return tuple(int(v) for v in row)


def assign_within_tolerance(distance, tolerance):
    """Existing bounded max-cardinality/min-residual assignment, also for domains.

    Columns are caller-defined, unique reflection identities or exactly
    coincident projection groups. This helper does not calculate coordinates.
    """
    distance = np.asarray(distance, dtype=float)
    require(distance.ndim == 2 and 1 <= len(distance) <= MAX_MEASUREMENTS and
            distance.shape[1] <= 2*MAX_REFLECTIONS and np.isfinite(distance).all() and
            bool(np.all(distance >= 0)) and finite(tolerance) and 1e-12 <= tolerance <= 1,
            "A bounded finite nonnegative residual matrix and fixed tolerance are required")
    candidates = distance <= tolerance
    require(int(np.count_nonzero(candidates)) <= MAX_CANDIDATE_EDGES,
            "Candidate graph exceeds8192edges; no candidates were truncated")
    dummy = float(len(distance) + 1)
    costs = np.concatenate((np.where(candidates, distance/tolerance, 2*dummy+1),
                            np.full((len(distance), len(distance)), dummy)), axis=1)
    rows, columns = linear_sum_assignment(costs)
    return [(int(i), int(j)) for i, j in zip(rows, columns) if j < distance.shape[1] and candidates[i, j]]


def compare(measurements, simulation, transform, tolerance, experimental_kind, correspondences=None):
    require(experimental_kind in ("real_space_fft", "saed", "other_diffraction"),
            "Declare experimental_kind; FFT contrast and SAED intensities are different formation mechanisms")
    require(finite(tolerance) and 1e-12 <= tolerance <= 1, "max_residual_inv_angstrom must be explicit in [1e-12,1]")
    require(type(measurements) is list and 1 <= len(measurements) <= MAX_MEASUREMENTS, "Compare 1..32 explicit measurement records")
    observations = [measurement_vector(item) for item in measurements]
    require(len({item["measurement_object_id"] for item in observations}) == len(observations), "Duplicate experimental measurement IDs")
    require(experimental_kind == "real_space_fft" or all(item["coordinate_space"] != "frequency_cycles_per_pixel" for item in observations),
            "A saved real-space FFT cannot be relabeled SAED/diffraction intensity")
    reflections = simulation.get("reflections", {})
    require(reflections.get("reciprocal_convention") == "cycles_per_angstrom_no_2pi" and
            reflections.get("coordinates_frame") == "rotated laboratory xyz; beam +z; raster columns +x, rows +y",
            "Simulation must retain the explicit laboratory frame and cycles-per-Angstrom convention")
    coords, hkls, intensities = reflections.get("coordinates_inv_angstrom"), reflections.get("hkl"), reflections.get("kinematic_intensity")
    require(type(coords) is list and 1 <= len(coords) <= MAX_REFLECTIONS and type(hkls) is list and type(intensities) is list and
            len(coords) == len(hkls) == len(intensities), "A bounded actual simulation reflection table is required")
    require(all(type(row) is list and len(row) == 3 and all(finite(v) and abs(v) <= 1e6 for v in row) for row in coords) and
            all(finite(v) and v >= 0 for v in intensities), "Simulation coordinates/intensities must be finite")
    keys = [hkl_key(row) for row in hkls]
    require(len(set(keys)) == len(keys), "Simulation contains duplicate HKL identities")
    alignment = registration(transform)
    original = np.asarray([item["q_xy_inv_angstrom"] for item in observations])
    matrix = np.asarray(alignment["matrix_xy"])
    terms = original[:, None, :] * matrix[None, :, :]
    require(not bool(np.any((original[:, None, :] != 0) & (matrix[None, :, :] != 0) & (terms == 0))),
            "A nonzero registration component underflows during multiplication")
    aligned = np.sum(terms, axis=2) + np.asarray(alignment["translation_xy_inv_angstrom"])
    require(np.isfinite(aligned).all() and np.max(np.abs(aligned)) <= 1e6, "Registration produces out-of-budget reciprocal coordinates")
    # hypot preserves tiny nonzero residuals that squared Euclidean sums lose.
    residual_x = np.asarray(coords)[None, :, 0] - aligned[:, None, 0]
    residual_y = np.asarray(coords)[None, :, 1] - aligned[:, None, 1]
    distance = np.hypot(residual_x, residual_y)
    require(np.isfinite(distance).all(), "Nonfinite reciprocal residuals")
    candidates = distance <= tolerance
    require(int(np.count_nonzero(candidates)) <= MAX_CANDIDATE_EDGES,
            "Candidate graph exceeds8192edges; narrow the caller tolerance or experimental peak list, no candidates were truncated")
    explicit = correspondences is not None
    if explicit:
        require(type(correspondences) is list and 1 <= len(correspondences) <= len(observations), "Explicit correspondences require bounded measurement_index/HKL rows")
        pairs = []
        for item in correspondences:
            require(type(item) is dict and set(item) == {"measurement_index", "hkl"} and
                    type(item["measurement_index"]) is int and 0 <= item["measurement_index"] < len(observations),
                    "Invalid explicit correspondence measurement index")
            key = hkl_key(item["hkl"])
            require(key in keys, "Caller-specified HKL is absent from this actual simulation")
            pairs.append((item["measurement_index"], keys.index(key)))
        require(len({p[0] for p in pairs}) == len(pairs) and len({p[1] for p in pairs}) == len(pairs), "Explicit correspondences must be one-to-one")
        assignment = pairs
    else:
        # There are enough dummy columns for every observation to stay unmatched.
        # No out-of-tolerance edge is forced by the one-to-one assignment.
        # Lexicographic objective: maximize feasible cardinality first, then
        # minimize total physical residual. Valid normalized costs are <=1;
        # one dummy must cost more than every row's possible residual sum.
        assignment = assign_within_tolerance(distance, tolerance)
    used_measurements, used_simulation = {i for i, _ in assignment}, {j for _, j in assignment}
    matched = []
    for i, j in assignment:
        actual, predicted = aligned[i], np.asarray(coords[j][:2])
        observed_norm, predicted_norm = math.hypot(*actual), math.hypot(*predicted)
        lattice_norm = math.hypot(*coords[j])
        matched.append({"measurement_index": i, "measurement_object_id": observations[i]["measurement_object_id"],
                        "simulation_reflection_index": j, "hkl": list(keys[j]),
                        "experiment_original_q_xy_inv_angstrom": original[i].tolist(),
                        "experiment_registered_q_xy_inv_angstrom": actual.tolist(),
                        "simulation_q_xyz_inv_angstrom": coords[j], "position_residual_xy_inv_angstrom": (predicted-actual).tolist(),
                        "position_residual_inv_angstrom": float(distance[i, j]), "within_declared_tolerance": bool(distance[i, j] <= tolerance),
                        "experiment_original_projected_period_angstrom": observations[i]["projected_period_angstrom"],
                        "experiment_registered_projected_period_angstrom": period(observed_norm, "Registered experimental reciprocal"),
                        "simulation_projected_period_angstrom": period(predicted_norm, "Projected simulation reciprocal"),
                        "simulation_lattice_d_spacing_angstrom": period(lattice_norm, "Simulated lattice reciprocal"),
                        "kinematic_intensity_retained_not_compared": intensities[j]})
    ambiguity = []
    for i, row in enumerate(candidates):
        js = np.flatnonzero(row)
        ambiguity.append({"measurement_index": i, "candidate_count": len(js),
                          "assignment_is_unique_proof": False,
                          "ambiguous_within_tolerance": len(js) > 1 or any(np.count_nonzero(candidates[:, j]) > 1 for j in js),
                          "candidates": [{"simulation_reflection_index": int(j), "hkl": list(keys[j]), "residual_inv_angstrom": float(distance[i, j])} for j in js]})
    angles = []
    def angle(a, b):
        norm_a, norm_b = math.hypot(*a), math.hypot(*b)
        if norm_a == 0 or norm_b == 0:
            return None
        a, b = a/norm_a, b/norm_b
        return math.degrees(math.atan2(float(a[0]*b[1]-a[1]*b[0]), float(np.dot(a, b))))
    for n, (i, j) in enumerate(assignment):
        for k, l in assignment[n+1:]:
            observed_angle, simulated_angle = angle(aligned[i], aligned[k]), angle(np.asarray(coords[j][:2]), np.asarray(coords[l][:2]))
            delta = simulated_angle-observed_angle if observed_angle is not None and simulated_angle is not None else None
            if delta is not None:
                if delta > 180.:
                    delta -= 360.
                elif delta < -180.:
                    delta += 360.
            angles.append({"measurement_indices": [i, k], "simulation_reflection_indices": [j, l],
                           "experimental_registered_signed_angle_deg": observed_angle, "simulation_projected_signed_angle_deg": simulated_angle,
                           "angle_residual_deg": delta, "angle_scope": "projected transverse reciprocal vectors, not a 3D plane-normal angle"})
    passed = len(matched) == len(observations) and all(row["within_declared_tolerance"] for row in matched)
    return {"comparison_kind": "explicit_reciprocal_geometry_only", "experimental_kind": experimental_kind,
            "observations": observations, "registration": alignment,
            "max_residual_inv_angstrom": tolerance,
            "matching_method": "caller_explicit_one_to_one_HKL" if explicit else "SciPy linear_sum_assignment: maximum in-tolerance cardinality, then minimum total reciprocal residual; bounded dummy assignments",
            "matched": matched,
            "unmatched_experimental": [{"measurement_index": i, **observations[i]} for i in range(len(observations)) if i not in used_measurements],
            "unmatched_simulated": [{"simulation_reflection_index": j, "hkl": list(keys[j]), "coordinates_inv_angstrom": coords[j], "kinematic_intensity": intensities[j]} for j in range(len(coords)) if j not in used_simulation],
            "ambiguity": ambiguity, "pairwise_angles": angles,
            "all_experimental_reflections_matched_within_tolerance": passed,
            "comparison_status": "within_declared_geometric_tolerance" if passed else "partially_matched_or_inconsistent",
            "intensity_comparison_performed": False, "phase_identified": False,
            "scientific_limits": ["Geometric agreement does not identify a unique phase or prove an HKL assignment.",
                                  "Real-space HRTEM/ptychography FFT and SAED/kinematic electron diffraction do not share a general intensity-formation model.",
                                  "Only projected reciprocal geometry is compared; exact lattice d-spacings use full simulated 3D reciprocal vectors.",
                                  "Registration is caller supplied, never fitted or independently verified; experimental calibration remains unchanged.",
                                  "Measurement snapshots retain their active-at-measurement calibration version; remeasure after later calibration correction/withdrawal.",
                                  "Localization, calibration covariance and model uncertainty are not combined into an inferred statistical confidence."]}
