"""Bounded proper in-plane rotation proposals over saved reciprocal geometry.

No peak finding, scale/centre fit, reflection search, image warp or intensity
model lives here. The caller validates and freezes the original manifests;
this module reuses their strict numerical vector and comparison contracts.
"""
import copy
import math

import numpy as np
from scipy.linalg import svd

from crystallography.reflection_compare import (
    MAX_MEASUREMENTS, MAX_REFLECTIONS, OBJECT_ID, canonical, compare, finite,
    hkl_key, measurement_vector, registration, sha,
)


class RegistrationError(ValueError):
    code = "INVALID_REGISTRATION_PROPOSAL"


def require(value, message):
    if not value:
        raise RegistrationError(message)


def geometry_binding(measurements):
    """Identify one fixed science plane and one exact calibration/centre version.

    Object/request IDs remain separate evidence. The semantic hash also binds
    their ordered point geometry, so new wrappers cannot silently reuse an old
    scale, centre, source/frame, ROI or registration proposal.
    """
    require(type(measurements) is list and 1 <= len(measurements) <= MAX_MEASUREMENTS,
            "Use 1..32 saved reciprocal measurement records")
    observations = [measurement_vector(row) for row in measurements]
    require(len({row["measurement_object_id"] for row in observations}) == len(observations),
            "Duplicate measurement identities cannot establish independent evidence")
    first = observations[0]
    # A display wrapper is provenance, not the scientific producer. Current
    # callers have already checked these grids against committed workspace
    # objects in bind_geometry(). Historical records without grids retain the
    # old exact-source contract; never mix the two evidence generations.
    with_grid = ["scientific_grid_identity" in row for row in measurements]
    require(all(with_grid) or not any(with_grid),
            "Cannot mix grid-bound and historical measurements; remeasure on the selected grid")
    grid = measurements[0].get("scientific_grid_identity") if all(with_grid) else None
    if all(with_grid):
        require(type(grid) is dict and set(grid) == {
                    "source_grid_object_id", "shape_yx", "dtype", "array_sha256",
                    "source_rect_xyxy", "coordinate_space"} and
                type(grid.get("source_grid_object_id")) is str and
                OBJECT_ID.fullmatch(grid["source_grid_object_id"]) and
                grid.get("coordinate_space") == first["coordinate_space"],
                "A complete committed scientific grid identity is required")
        require(all(type(row.get("scientific_grid_identity")) is dict and
                    canonical(row["scientific_grid_identity"]) == canonical(grid)
                    for row in measurements),
                "Registration measurements must share the exact scientific grid, not merely equal pixels")
    source = grid["source_grid_object_id"] if grid is not None else first["source_object_id"]
    require(type(source) is str and OBJECT_ID.fullmatch(source),
            "An exact immutable source science object is required")
    record = canonical(first["calibration_record"])
    centre = first["original_points"][first["dc_reference_point_index"]]
    point_rows = []
    for row, original in zip(observations, measurements):
        require((grid is not None or row["source_object_id"] == source) and row["coordinate_space"] == first["coordinate_space"] and
                canonical(row["calibration_dependency"]) == canonical(first["calibration_dependency"]) and
                canonical(row["calibration_record"]) == record and
                row["original_points"][row["dc_reference_point_index"]] == centre,
                "Registration measurements must share the same source/frame, coordinate domain, calibration and centre revision")
        require(original.get("source_rect_xyxy") == measurements[0].get("source_rect_xyxy"),
                "Registration measurements cannot mix distinct source ROI extents")
        point_rows.append({"points": row["original_points"],
                           "dc_reference_point_index": row["dc_reference_point_index"],
                           "q_xy_inv_angstrom": row["q_xy_inv_angstrom"]})
    value = {"binding_version": 2 if grid is not None else 1, "source_object_id": source,
             **({"scientific_grid_identity": grid} if grid is not None else {}),
             "coordinate_space": first["coordinate_space"], "dc_point": centre,
             "source_rect_xyxy": measurements[0].get("source_rect_xyxy"),
             "calibration_dependency": first["calibration_dependency"],
             "calibration_record_sha256": sha(record), "ordered_measurement_geometry": point_rows}
    return {**copy.deepcopy(value), "sha256": sha(canonical(value))}


def _simulation(value):
    require(type(value) is dict and
            value.get("reciprocal_enumeration", {}).get("completeness_certified") is True,
            "Use a saved simulation with its certified reciprocal enumeration; unqualified skew-cell tables cannot supply a proposal")
    table = value.get("reflections", {})
    require(type(table) is dict and table.get("reciprocal_convention") == "cycles_per_angstrom_no_2pi" and
            table.get("coordinates_frame") == "rotated laboratory xyz; beam +z; raster columns +x, rows +y",
            "Simulation requires its unrastered laboratory coordinates in cycles/angstrom")
    coords, hkls, intensities = (table.get(key) for key in
                                ("coordinates_inv_angstrom", "hkl", "kinematic_intensity"))
    require(type(coords) is list and 1 <= len(coords) <= MAX_REFLECTIONS and
            type(hkls) is list and type(intensities) is list and len(coords) == len(hkls) == len(intensities),
            "A bounded complete simulation reflection table is required")
    require(all(type(row) is list and len(row) == 3 and all(finite(v) and abs(v) <= 1e6 for v in row) for row in coords) and
            all(finite(v) and v >= 0 for v in intensities),
            "Simulation coordinates and retained intensities must be finite")
    keys = [hkl_key(row) for row in hkls]
    require(len(set(keys)) == len(keys), "Simulation HKL identities must be unique")
    return np.asarray(coords, dtype=float), keys


def _pairs(value, count, keys, label, minimum):
    require(type(value) is list and minimum <= len(value) <= count,
            label + " requires an explicit bounded correspondence list")
    result = []
    for item in value:
        require(type(item) is dict and set(item) == {"measurement_index", "hkl"} and
                type(item["measurement_index"]) is int and 0 <= item["measurement_index"] < count,
                label + " requires exact measurement_index/HKL pairs")
        key = hkl_key(item["hkl"])
        require(key in keys, label + " HKL is absent from this simulation")
        result.append((item["measurement_index"], keys.index(key)))
    require(len({i for i, _ in result}) == len(result) and len({j for _, j in result}) == len(result),
            label + " correspondences must be one-to-one")
    return result


def _normalized(points, label):
    maximum = float(np.max(np.abs(points)))
    require(finite(maximum) and maximum > 0, label + " needs nonzero transverse vectors")
    result = points / maximum
    require(np.isfinite(result).all() and not bool(np.any((points != 0) & (result == 0))),
            label + " normalization underflows or overflows a nonzero component")
    singular = svd(result, full_matrices=False, compute_uv=False, check_finite=True)
    threshold = float(np.finfo(float).eps * max(result.shape) * singular[0])
    require(len(singular) == 2 and singular[1] > threshold,
            label + " requires at least two numerically non-collinear reciprocal reflections")
    return result, {"normalization_max_abs": maximum, "singular_values": singular.tolist(),
                    "numerical_rank_threshold": threshold, "rank": 2,
                    "normalization_is_not_a_fitted_scale": True}


def _proper_rotation(experiment, theory):
    # This is the determinant-constrained orthogonal Procrustes construction.
    # scipy.linalg.orthogonal_procrustes alone also admits reflections; the
    # SciPy SVD factorization below explicitly restricts the result to SO(2).
    x, x_rank = _normalized(experiment, "Fit experiment")
    y, y_rank = _normalized(theory, "Fit simulation")
    terms = x[:, :, None] * y[:, None, :]
    require(not bool(np.any((x[:, :, None] != 0) & (y[:, None, :] != 0) & (terms == 0))),
            "Nonzero Procrustes covariance component underflows")
    covariance = np.sum(terms, axis=0)
    u, singular, vh = svd(covariance, full_matrices=False, check_finite=True)
    amplitude = math.hypot(float(np.trace(covariance)), float(covariance[0, 1] - covariance[1, 0]))
    threshold = float(np.finfo(float).eps * max(covariance.shape) * singular[0])
    require(amplitude > threshold,
            "Proper rotation is numerically non-unique; fixed screen axes/correspondences do not determine an angle")
    correction = np.diag([1., 1. if np.linalg.det(u @ vh) > 0 else -1.])
    matrix = (u @ correction @ vh).T
    require(np.isfinite(matrix).all() and
            np.allclose(matrix.T @ matrix, np.eye(2), rtol=0, atol=64 * np.finfo(float).eps) and
            math.isclose(float(np.linalg.det(matrix)), 1., rel_tol=0, abs_tol=64 * np.finfo(float).eps),
            "SVD did not produce a finite proper right-handed in-plane rotation")
    angle = math.degrees(math.atan2(float(matrix[1, 0]), float(matrix[0, 0])))
    return angle, {"engine": "scipy.linalg.svd", "construction": "proper orthogonal Procrustes in SO(2), uncentred equal-weight vectors",
                   "column_vector_rule": "q_theory = Rccw @ diag(1, screen_flip_y?-1:1) @ q_experiment",
                   "svd_rotation_matrix_xy": matrix.tolist(), "proper_determinant": float(np.linalg.det(matrix)),
                   "experimental_rank": x_rank, "simulation_rank": y_rank,
                   "covariance_singular_values": singular.tolist(), "proper_rotation_objective_amplitude": amplitude,
                   "numerical_uniqueness_threshold": threshold,
                   "numerical_threshold_scope": "binary64 rank/uniqueness only; never replaces the caller's reciprocal residual tolerance",
                   "statistical_uncertainty": "not estimated; no localization/calibration covariance supplied"}


def _adjacent_location(a, b):
    """Only a binary64 representation warning, never an experimental error bar."""
    return all(abs(float(x)-float(y)) <= max(math.ulp(float(x)), math.ulp(float(y))) for x, y in zip(a, b))


def _proposal_comparison_provenance(result):
    # compare() normally receives a fully caller-specified transform. Here its
    # angle was estimated by the separate fit stage, so preserve that source
    # distinction without changing any scientific arithmetic or constraints.
    result["registration"]["parameter_source"] = (
        "rotation from this proposal's fit correspondences only; fixed screen mapping/scale/centre; "
        "the comparison stage does not refit")
    result["registration"]["rotation_parameter_source"] = "constrained_fit_correspondences_only"
    result["scientific_limits"] = [
        "Registration rotation comes from the separate fit-only proposal; this comparison stage does not fit or change experimental calibration."
        if line.startswith("Registration is caller supplied") else line
        for line in result["scientific_limits"]]
    return result


def propose(measurements, simulation, fit_correspondences, validation_correspondences,
            screen_axes, max_residual_inv_angstrom, experimental_kind, confirmation):
    """Propose one proper rotation; never turn fitted residuals into validation.

    Correspondences are caller assertions with recorded scientific authority,
    not authentication. Empty held-out evidence remains explicitly NOT_TESTED.
    """
    require(type(screen_axes) is dict and set(screen_axes) == {"flip_y", "basis"} and
            type(screen_axes["flip_y"]) is bool and type(screen_axes["basis"]) is str and
            1 <= len(screen_axes["basis"].strip()) <= 500,
            "Declare fixed screen_axes.flip_y and its known basis; an unknown mirror is not a fit parameter")
    require(type(confirmation) is dict and set(confirmation) == {"source", "source_text"} and
            confirmation.get("source") in ("user_confirmed", "synthetic_fixture") and
            type(confirmation["source_text"]) is str and 1 <= len(confirmation["source_text"].strip()) <= 1000,
            "Correspondence confirmation requires user_confirmed or synthetic_fixture source and explicit source_text")
    require(finite(max_residual_inv_angstrom) and 1e-12 <= max_residual_inv_angstrom <= 1,
            "max_residual_inv_angstrom must be explicit in [1e-12,1]")
    require(experimental_kind in ("real_space_fft", "saed", "other_diffraction"),
            "Declare the experimental formation kind; FFT and SAED intensities differ")
    binding = geometry_binding(measurements)
    observations = [measurement_vector(row) for row in measurements]
    require(experimental_kind == "real_space_fft" or all(row["coordinate_space"] != "frequency_cycles_per_pixel" for row in observations),
            "Real-space FFT measurements cannot be relabelled as SAED")
    coords, keys = _simulation(simulation)
    fit = _pairs(fit_correspondences, len(observations), keys, "Fit", 2)
    validation = _pairs(validation_correspondences, len(observations), keys, "Held-out validation", 0)
    require(all(math.hypot(*coords[j, :2]) > 0 for _, j in fit + validation),
            "A direct beam or zero transverse simulated vector cannot be a fitted/held-out reflection")
    fit_ids, fit_refs = {i for i, _ in fit}, {j for _, j in fit}
    require(not fit_ids.intersection(i for i, _ in validation) and not fit_refs.intersection(j for _, j in validation),
            "Fit and held-out validation cannot reuse a measurement or theoretical HKL")
    peaks = [tuple(row["original_points"][1 - row["dc_reference_point_index"]]) for row in observations]
    require(len({peaks[i] for i, _ in fit}) == len(fit),
            "Different measurement IDs at the same experimental peak cannot supply separate fit reflections")
    require(len({peaks[i] for i, _ in validation}) == len(validation) and
            not {peaks[i] for i, _ in fit}.intersection(peaks[i] for i, _ in validation),
            "Held-out validation cannot reuse an experimental peak through another measurement ID")
    # A different HKL with the same transverse projection is not an independent
    # held-out location. Likewise a Friedel mate of a fitted reflection is not
    # admitted as independent validation of real-FFT/conjugate geometry.
    fit_xy = [coords[j, :2] for _, j in fit]
    require(len({tuple(v) for v in fit_xy}) == len(fit_xy),
            "Coincident simulated projections cannot supply separate fit constraints")
    require(len({tuple(coords[j, :2]) for _, j in validation}) == len(validation),
            "Coincident simulated projections cannot supply separate held-out constraints")
    original = np.asarray([row["q_xy_inv_angstrom"] for row in observations], dtype=float)
    unresolved = []
    for i, j in validation:
        require(not any(np.array_equal(coords[j, :2], v) for v in fit_xy),
                "Held-out validation cannot reuse a coincident simulated transverse projection")
        require(not any(keys[j] == tuple(-k for k in keys[fj]) for _, fj in fit),
                "A fitted reflection's Friedel mate is not independent held-out validation")
        require(not any(np.array_equal(coords[j, :2], -v) for v in fit_xy),
                "An antipodal simulated projection is not independent held-out validation")
        require(not any(np.array_equal(original[i], -original[fi]) for fi, _ in fit),
                "A fitted experimental peak's conjugate vector is not independent held-out validation")
        for fi, fj in fit:
            if _adjacent_location(peaks[i], peaks[fi]):
                unresolved.append({"fit_measurement_index": fi, "validation_measurement_index": i,
                                   "reason": "experimental source peaks differ by at most one binary64 ULP"})
            if _adjacent_location(coords[j, :2], coords[fj, :2]):
                unresolved.append({"fit_simulation_reflection_index": fj, "validation_simulation_reflection_index": j,
                                   "reason": "simulated transverse projections differ by at most one binary64 ULP"})
            if _adjacent_location(original[i], -original[fi]):
                unresolved.append({"fit_measurement_index": fi, "validation_measurement_index": i,
                                   "reason": "experimental vectors are conjugate within one binary64 ULP"})
    for n, (i, j) in enumerate(validation):
        for vi, vj in validation[n+1:]:
            require(keys[j] != tuple(-k for k in keys[vj]) and
                    not np.array_equal(original[i], -original[vi]) and
                    not np.array_equal(coords[j, :2], -coords[vj, :2]),
                    "Held-out reflections cannot count Friedel/conjugate or antipodal mates as separate independent evidence")
            if _adjacent_location(peaks[i], peaks[vi]) or _adjacent_location(coords[j, :2], coords[vj, :2]):
                unresolved.append({"validation_measurement_indices": [i, vi],
                                   "reason": "held-out source peaks/projections differ by at most one binary64 ULP"})
    screened = original.copy()
    if screen_axes["flip_y"]:
        screened[:, 1] *= -1
    angle, method = _proper_rotation(screened[[i for i, _ in fit]], coords[[j for _, j in fit], :2])
    basis = "Fixed experimental scale/DC; SO(2) fit from caller-asserted correspondences. Screen basis: " + screen_axes["basis"]
    transform = {"rotation_deg": angle, "scale": 1., "translation_inv_angstrom": [0., 0.],
                 "flip_y": screen_axes["flip_y"], "basis": basis}
    # The original compare implementation owns all vector arithmetic, residual
    # budgets, matching, ambiguities, unmatched reflections and scientific limits.
    fitted = _proposal_comparison_provenance(compare(measurements, simulation, transform, max_residual_inv_angstrom,
                                                    experimental_kind, fit_correspondences))
    held = (_proposal_comparison_provenance(compare(measurements, simulation, transform, max_residual_inv_angstrom,
                                                   experimental_kind, validation_correspondences)) if validation else None)
    all_comparison = _proposal_comparison_provenance(compare(measurements, simulation, transform,
                                                           max_residual_inv_angstrom, experimental_kind))
    validation_ids = {i for i, _ in validation}
    roles = {i: "fit" if i in fit_ids else "held_out_validation" if i in validation_ids else "not_used_for_fit_or_validation"
             for i in range(len(observations))}
    for row in all_comparison["matched"]:
        row["evidence_role"] = roles[row["measurement_index"]]
    for row in all_comparison["unmatched_experimental"]:
        row["evidence_role"] = roles[row["measurement_index"]]
    fit_pass = all(row["within_declared_tolerance"] for row in fitted["matched"])
    held_pass = all(row["within_declared_tolerance"] for row in held["matched"]) if held else None
    status = ("not_tested_no_held_out" if held is None else "fit_inconsistent" if not fit_pass else
              "held_out_independence_unresolved" if unresolved else
              "held_out_geometry_consistent" if held_pass else "held_out_inconsistent")
    return {"proposal_kind": "proper_in_plane_rotation_fixed_experimental_scale_and_dc",
            "registration": transform,
            "rotation_matrix_xy": registration({**transform, "flip_y": False})["matrix_xy"],
            "comparison_matrix_xy": registration(transform)["matrix_xy"],
            "allowed_degrees_of_freedom": ["in_plane_rotation"],
            "fixed_parameters": {"scale": 1., "translation_inv_angstrom": [0., 0.],
                                 "screen_flip_y": screen_axes["flip_y"], "experimental_calibration_modified": False,
                                 "experimental_centre_modified": False, "distortion_model": None},
            "screen_axes": copy.deepcopy(screen_axes), "confirmation": copy.deepcopy(confirmation),
            "confirmation_scope": "caller-supplied scientific assertion; not identity authentication or independent verification",
            "experimental_geometry_binding": binding, "input_measurement_ids": [row["measurement_object_id"] for row in observations],
            "fit_correspondences": copy.deepcopy(fit_correspondences), "validation_correspondences": copy.deepcopy(validation_correspondences),
            "fit_evidence": fitted["matched"], "validation_evidence": held["matched"] if held else [],
            "fit_status": "within_declared_tolerance" if fit_pass else "outside_declared_tolerance",
            "validation_status": status, "held_out_validation_passed": (fit_pass and held_pass and not unresolved) if held else None,
            "held_out_independence": {"scope": "disjoint original peak anchors/HKL/projections; not a proof of statistical or experimental resolving power",
                                      "unresolved_binary64_aliases": unresolved,
                                      "ulp_warning_is_not_a_measurement_uncertainty_or_residual_tolerance": True},
            "unassigned_measurement_indices": [i for i in range(len(observations)) if i not in fit_ids and i not in validation_ids],
            "max_residual_inv_angstrom": max_residual_inv_angstrom, "method": method,
            "rotation_candidates": [{"rotation_deg": angle, "numerically_unique_for_fixed_correspondences": True,
                                     "unique_scientific_indexing_proven": False}],
            "comparison": all_comparison, "phase_identified": False, "intensity_comparison_performed": False,
            "scientific_limits": ["Only a proper in-plane rotation is estimated; scale, centre, screen reflection and distortion are not fitted.",
                                  "Revise the explicit centre/scale and remeasure before making a new proposal; an old proposal is historical.",
                                  "Held-out points and HKLs are distinct from fit evidence; this is geometric consistency, not statistical independence or unique phase identification.",
                                  "Friedel mates and coincident projections are not admitted as independent held-out constraints.",
                                  "The full comparison retains all ambiguities and unmatched reflections; fit residuals are not validation.",
                                  "FFT and SAED do not share a general intensity-formation model; no intensity match or dynamical scattering is performed."]}
