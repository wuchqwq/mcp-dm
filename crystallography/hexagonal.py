"""External, bounded HCP-compatible hexagonal reciprocal-metric candidates.

ASE supplies the conventional cell and reciprocal basis without 2*pi.  The
common assignment, proper-frame fit and residual policy reuse the cubic
companion.  HCP is a primitive hexagonal lattice *with a two-atom basis*, not a
Bravais centering.  Ideal-basis cancellations are diagnostics, never dynamical
electron-diffraction exclusion rules or chemical phase identification.
"""

import itertools
import math
from functools import lru_cache

import numpy as np
from ase.cell import Cell

from .indexing import (_assign, _fit, _integer, _joint_angle_error, _number,
                       _primitive_zone)
from .geometry import _require_noncollinear

IDEAL_C_OVER_A = math.sqrt(8. / 3.)
MAX_HCP_SEARCH_SEEDS = 50000


def hexagonal_cell(c_over_a):
    """Dimensionless direct rows: |a1|=|a2|=1, a1.a2=-1/2, |c|=c/a."""
    ratio = _number(c_over_a, "c_over_a", .5, 4.)
    return Cell([[1., 0., 0.], [-.5, math.sqrt(3.) / 2., 0.], [0., 0., ratio]])


def direction_three_to_four(uvw):
    """Primitive Miller-Bravais direction, not plane conversion.

    U=(2u-v)/3, V=(2v-u)/3, T=-(u+v)/3, W=w.  Multiplying
    *all four* entries by three before reducing retains the required W factor.
    """
    if len(uvw) != 3 or any(isinstance(v, bool) or not isinstance(v, (int, np.integer))
                            for v in uvw) or not any(uvw):
        raise ValueError("uvw must be a nonzero integer direction")
    u, v, w = [int(v) for v in uvw]
    result = [2 * u - v, 2 * v - u, -u - v, 3 * w]
    divisor = math.gcd(math.gcd(abs(result[0]), abs(result[1])),
                       math.gcd(abs(result[2]), abs(result[3])))
    return [v // divisor for v in result]


def hcp_basis_diagnostic(hkl):
    """Two identical unit scatterers at 000 and (1/3,2/3,1/2).

    This is a relative geometric basis factor, not measured/simulated electron
    intensity.  The positions and general structure-factor sum follow IUCr's
    close-packed structures pamphlet and Structure_factor dictionary entry.
    """
    if len(hkl) != 3 or any(isinstance(v, bool) or not isinstance(v, (int, np.integer))
                            for v in hkl):
        raise ValueError("hkl must contain three integer reflection indices")
    h, k, l = [int(v) for v in hkl]
    absent = (h + 2 * k) % 3 == 0 and l % 2 != 0
    phase = 2 * math.pi * ((h + 2 * k) / 3. + l / 2.)
    factor = 0. if absent else min(4., max(0., 2. + 2. * math.cos(phase)))
    return {"ideal_identical_atom_basis_factor_squared": factor,
            "kinematic_basis_cancellation": bool(absent),
            "used_as_hard_rejection": False,
            "electron_dynamical_intensity_modelled": False}


@lru_cache(maxsize=4)
def _indices(max_index):
    rows = np.array(list(itertools.product(range(-max_index, max_index + 1), repeat=3)),
                    dtype=np.int64)
    rows = rows[np.any(rows, axis=1) & (np.abs(rows[:, 0] + rows[:, 1]) <= max_index)]
    anchors = rows[(rows[:, 0] >= rows[:, 1]) & (rows[:, 1] >= 0) & (rows[:, 2] >= 0)]
    return rows, anchors


def _hexagonal_key(assignments, matched):
    """Hexagonal 6/mmm axis equivalence, never cubic permutations."""
    original = assignments[matched]
    choices = []
    for reflect in (False, True):
        rows = original.copy()
        if reflect:
            rows[:, 0], rows[:, 1] = (original[:, 0] + original[:, 1], -original[:, 1])
        for _ in range(6):
            for sign in (-1, 1):
                candidate = rows.copy()
                candidate[:, 2] *= sign
                choices.append(tuple(candidate.ravel().tolist()))
            old_h = rows[:, 0].copy()
            old_k = rows[:, 1].copy()
            rows[:, 0], rows[:, 1] = -old_k, old_h + old_k
    return tuple(np.flatnonzero(matched).tolist()), min(choices)


def _input_vectors(vectors):
    try:
        raw = np.asarray(vectors)
        if raw.dtype.kind not in "iuf":
            raise ValueError("real numeric vectors required")
        values = raw.astype(np.float64, copy=False)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("vectors must be finite real numeric Nx2 coordinates")
    if values.ndim != 2 or values.shape[1] != 2 or not 3 <= len(values) <= 12:
        raise ValueError("vectors must have shape [3..12,2]")
    if not np.all(np.isfinite(values)) or np.max(np.abs(values)) > 1e12:
        raise ValueError("vectors must be finite and bounded by 1e12")
    norms = np.linalg.norm(values, axis=1)
    if np.min(norms) < 1e-12 or np.max(norms) / np.min(norms) > 1e6:
        raise ValueError("zero or numerically unresolved reciprocal vectors")
    distances = np.linalg.norm(values[:, None, :] - values[None, :, :], axis=2)
    np.fill_diagonal(distances, np.inf)
    if np.min(distances) <= np.max(norms) * 1e-10:
        raise ValueError("duplicate reciprocal observations")
    return values, norms


def index_hcp(vectors, *, calibrated, max_index=3, relative_tolerance=.03,
              angle_tolerance_deg=2., lattice_parameter_a_nm=None,
              c_over_a=None, c_over_a_candidates=None, max_candidates=20,
              max_unmatched=0):
    """Return common-frame hexagonal metrics plus explicit HCP basis diagnostics.

    Input vectors are already physical reciprocal XY cycles/nm, or explicitly
    isotropic relative coordinates.  A fixed reference ``a`` is never refitted.
    ``c/a`` is either specified, selected from a predeclared finite grid (<=13),
    or explicitly assumed ideal sqrt(8/3).  There is no continuous c/a fitting
    and no recalibration of input.  Basal-only data cannot constrain c/a.

    Search bounds apply to |h|, |k|, |i=-h-k| and |l|, all <=max_index, rather
    than an incorrect cubic index box.  The 50,000-seed budget is shared over
    all ratios; overflow raises without returning partial successful results.
    """
    if not isinstance(calibrated, bool):
        raise ValueError("calibrated must be boolean")
    observed, norms = _input_vectors(vectors)
    max_index = _integer(max_index, "max_index", 1, 4)
    max_candidates = _integer(max_candidates, "max_candidates", 1, 100)
    max_unmatched = _integer(max_unmatched, "max_unmatched", 0, len(observed) - 3)
    relative_tolerance = _number(relative_tolerance, "relative_tolerance", 1e-6, .15)
    angle_tolerance_deg = _number(angle_tolerance_deg, "angle_tolerance_deg", .001, 10.)
    fixed_a = None
    if lattice_parameter_a_nm is not None:
        if not calibrated:
            raise ValueError("fixed a requires absolute reciprocal calibration")
        fixed_a = _number(lattice_parameter_a_nm, "lattice_parameter_a_nm", 1e-6, 1e6)
    if c_over_a is not None and c_over_a_candidates is not None:
        raise ValueError("provide c_over_a or c_over_a_candidates, not both")
    if c_over_a_candidates is not None:
        if not isinstance(c_over_a_candidates, (list, tuple)) or not 1 <= len(c_over_a_candidates) <= 13:
            raise ValueError("c_over_a_candidates must be a predeclared grid of 1..13 values")
        ratios = [_number(r, "c_over_a candidate", .5, 4.) for r in c_over_a_candidates]
        if len(set(ratios)) != len(ratios):
            raise ValueError("c_over_a_candidates must be unique")
        ratio_source = "predeclared_finite_grid_not_continuous_fit"
    elif c_over_a is not None:
        ratios = [_number(c_over_a, "c_over_a", .5, 4.)]
        ratio_source = "specified_reference_ratio"
    else:
        ratios = [IDEAL_C_OVER_A]
        ratio_source = "assumed_ideal_hcp_sqrt_8_over_3"
    _require_noncollinear(observed)
    all_hkl, anchors = _indices(max_index)
    fixed_scale = None if fixed_a is None else 1. / fixed_a
    found = {}
    stats = {"anchor_pairs_considered": 0, "anchor_seeds_after_geometric_pruning": 0,
             "joint_fits_evaluated": 0}
    for ratio in ratios:
        direct = np.asarray(hexagonal_cell(ratio))
        reciprocal = np.asarray(Cell(direct).reciprocal())
        all_cart = all_hkl @ reciprocal
        all_norms = np.linalg.norm(all_cart, axis=1)
        seed_keys = set()
        for i, j in itertools.combinations(range(len(observed)), 2):
            cross_observed = float(np.linalg.det(observed[[i, j]]))
            if abs(cross_observed) <= norms[i] * norms[j] * 1e-7:
                continue
            observed_angle = math.degrees(math.acos(np.clip(
                np.dot(observed[i], observed[j]) / (norms[i] * norms[j]), -1, 1)))
            observed_ratio = norms[j] / norms[i]
            image_u = observed[i] / norms[i]
            image_v = np.array([-image_u[1], image_u[0]]) * np.sign(cross_observed)
            image_basis = np.stack((image_u, image_v))
            for first_hkl in anchors:
                first = first_hkl @ reciprocal
                first_norm = float(np.linalg.norm(first))
                stats["anchor_pairs_considered"] += len(all_hkl)
                ratio_limit = 2 * relative_tolerance / (1 - relative_tolerance)
                possible = np.abs(all_norms / first_norm / observed_ratio - 1) <= ratio_limit
                angles = np.degrees(np.arccos(np.clip(all_cart @ first / (all_norms * first_norm), -1, 1)))
                possible &= np.abs(angles - observed_angle) <= angle_tolerance_deg
                if fixed_scale is not None:
                    possible &= abs(first_norm * fixed_scale / norms[i] - 1) <= relative_tolerance
                    possible &= np.abs(all_norms * fixed_scale / norms[j] - 1) <= relative_tolerance
                for second_hkl in all_hkl[possible]:
                    integer_normal = np.cross(first_hkl, second_hkl)
                    if not np.any(integer_normal):
                        continue
                    zone = _primitive_zone(integer_normal)
                    seed_key = (i, j, tuple(first_hkl), tuple(zone))
                    if seed_key in seed_keys:
                        continue
                    seed_keys.add(seed_key)
                    stats["anchor_seeds_after_geometric_pruning"] += 1
                    if stats["anchor_seeds_after_geometric_pruning"] > MAX_HCP_SEARCH_SEEDS:
                        raise ValueError("HCP search seed budget exceeded; reduce indices, points, ratio grid "
                                         "or tolerances; no partial candidate result returned")
                    cart_normal = np.cross(first, second_hkl @ reciprocal)
                    cart_normal /= np.linalg.norm(cart_normal)
                    crystal_u = first / first_norm
                    crystal_basis = np.stack((crystal_u, np.cross(cart_normal, crystal_u)))
                    plane_hkl = all_hkl[(all_hkl @ integer_normal) == 0]
                    local = (plane_hkl @ reciprocal) @ crystal_basis.T
                    rotation = image_basis
                    scale = fixed_scale if fixed_scale is not None else norms[i] / first_norm
                    for _ in range(3):
                        columns, matched = _assign(observed, scale * local @ rotation,
                                                   relative_tolerance, angle_tolerance_deg)
                        if np.count_nonzero(matched) < len(observed) - max_unmatched:
                            break
                        selected_local = local[columns[matched]]
                        if np.linalg.svd(selected_local, compute_uv=False)[-1] < 1e-8:
                            break
                        rotation, scale = _fit(selected_local, observed[matched], fixed_scale,
                                               np.sign(cross_observed))
                        if not math.isfinite(scale) or scale <= 0:
                            break
                    stats["joint_fits_evaluated"] += 1
                    predicted_all = scale * local @ rotation
                    columns, matched = _assign(observed, predicted_all,
                                               relative_tolerance, angle_tolerance_deg)
                    if np.count_nonzero(matched) < len(observed) - max_unmatched:
                        continue
                    selected = plane_hkl[columns[matched]]
                    if np.linalg.svd(selected.astype(float), compute_uv=False)[1] < 1e-8:
                        continue
                    predicted = predicted_all[columns[matched]]
                    pair_error = _joint_angle_error(observed[matched], predicted)
                    if pair_error > angle_tolerance_deg + 1e-8:
                        continue
                    assignments = np.zeros((len(observed), 3), dtype=int)
                    assignments[matched] = selected
                    key = (ratio, _hexagonal_key(assignments, matched))
                    errors = np.linalg.norm(predicted - observed[matched], axis=1)
                    relative_errors = errors / norms[matched]
                    rms = float(np.sqrt(np.mean(relative_errors ** 2)))
                    if key in found and found[key]["rms_relative_vector_residual"] <= rms:
                        continue
                    oriented_xy = rotation.T @ crystal_basis
                    orientation = np.vstack((oriented_xy, np.cross(oriented_xy[0], oriented_xy[1])))
                    if np.dot(orientation[2], np.array(zone) @ direct) < 0:
                        zone = [-v for v in zone]
                    observations = []
                    cursor = 0
                    for k in range(len(observed)):
                        if not matched[k]:
                            observations.append({"observation_index": k, "matched": False, "hkl": None,
                                                 "hkil": None, "reason": "outside_joint_candidate_tolerance"})
                            continue
                        h, kk, l = [int(v) for v in assignments[k]]
                        prediction = predicted[cursor]
                        predicted_norm = float(np.linalg.norm(prediction))
                        direction_cosine = np.dot(prediction, observed[k]) / (predicted_norm * norms[k])
                        observations.append({"observation_index": k, "matched": True,
                                             "hkl": [h, kk, l], "hkil": [h, kk, -h - kk, l],
                                             "predicted_vector": prediction.tolist(),
                                             "observed_magnitude": float(norms[k]), "predicted_magnitude": predicted_norm,
                                             "relative_radial_residual": float(abs(predicted_norm / norms[k] - 1)),
                                             "direction_residual_deg": math.degrees(math.acos(np.clip(direction_cosine, -1, 1))),
                                             "vector_residual": float(errors[cursor]),
                                             "relative_vector_residual": float(relative_errors[cursor]),
                                             "hcp_basis_diagnostic": hcp_basis_diagnostic([h, kk, l])})
                        cursor += 1
                    cancellations = [o["observation_index"] for o in observations if o["matched"] and
                                     o["hcp_basis_diagnostic"]["kinematic_basis_cancellation"]]
                    a = fixed_a if fixed_a is not None else (float(1 / scale) if calibrated else None)
                    found[key] = {
                        "model": "HCP", "centering": "P", "structure_label": "HCP-compatible hexagonal metric",
                        "lattice_parameter_nm": a, "lattice_parameter_a_nm": a,
                        "lattice_parameter_c_nm": None if a is None else a * ratio,
                        "lattice_parameter_source": "fixed_reference" if fixed_a is not None else
                            ("joint_geometric_fit_under_declared_c_over_a" if calibrated else "not_absolutely_calibrated"),
                        "c_over_a": ratio, "c_over_a_source": ratio_source, "c_over_a_continuously_fitted": False,
                        "c_over_a_sensitivity": "basal_only_c_over_a_unconstrained" if np.all(selected[:, 2] == 0) else
                            "contains_c_axis_information_but_only_declared_ratios_tested",
                        "c_parameter_interpretation": "derived_from_reference_or_assumed_ratio_not_independent_c_measurement",
                        "reciprocal_scale_per_hkl": float(scale),
                        "reciprocal_scale_unit": "cycles/nm" if calibrated else "relative",
                        "direct_basis_dimensionless_rows": direct.tolist(),
                        "reciprocal_basis_dimensionless_rows": reciprocal.tolist(),
                        "crystal_to_image_orientation": orientation.tolist(),
                        "orientation_convention": "g_image_xyz = orientation @ (hkl @ reciprocal_basis_rows) / a; proper right-handed; beam +z",
                        "zone_axis_uvw": zone, "zone_axis_uvtw": direction_three_to_four(zone),
                        "zone_direction_convention": "u*a1+v*a2+w*c; U=(2u-v)/3,V=(2v-u)/3,T=-(u+v)/3,W=w; common integer normalization",
                        "matched_count": int(np.count_nonzero(matched)),
                        "unmatched_observation_indices": np.flatnonzero(~matched).tolist(),
                        "rms_relative_vector_residual": rms, "max_pair_angle_residual_deg": pair_error,
                        "observations": observations,
                        "ideal_basis_cancellation_observation_indices": cancellations,
                        "hcp_basis_interpretation": "kinematic_diagnostic_only_not_dynamical_exclusion",
                        "chemical_phase_identified": False,
                    }
    ordered = sorted(found.values(), key=lambda c: (-c["matched_count"], c["rms_relative_vector_residual"],
                      c["c_over_a"], c["reciprocal_scale_per_hkl"], c["zone_axis_uvw"]))
    # A display limit must not erase an explicitly declared c/a alternative.
    representatives = [next(c for c in ordered if c["c_over_a"] == ratio)
                       for ratio in ratios if any(c["c_over_a"] == ratio for c in ordered)]
    chosen = list(representatives)
    for candidate in ordered:
        if len(chosen) >= max(max_candidates, len(representatives)):
            break
        if not any(candidate is c for c in chosen):
            chosen.append(candidate)
    chosen.sort(key=lambda c: (-c["matched_count"], c["rms_relative_vector_residual"], c["c_over_a"]))
    stats.update({"max_index": max_index, "index_bounds": "|h|,|k|,|i=-h-k|,|l| <= max_index",
                  "max_observations": 12, "max_search_seeds": MAX_HCP_SEARCH_SEEDS,
                  "c_over_a_candidates": ratios, "c_over_a_source": ratio_source,
                  "total_distinct_candidates": len(ordered), "returned_candidates": len(chosen),
                  "requested_max_candidates": max_candidates, "output_truncated": len(ordered) > len(chosen),
                  "anchor_enumeration_exhausted": True, "global_noisy_solution_completeness_proven": False,
                  "method": "hexagonal_two_anchor_with_shared_cubic_assignment_and_procrustes_policy"})
    return {"schema_version": 1, "computation_source": "external_python_crystallography", "model": "HCP",
            "calibrated": calibrated, "input_vectors": observed.tolist(),
            "frequency_convention": "cycles_per_length; |g|=1/d; ASE reciprocal excludes 2*pi",
            "tolerances": {"relative_radial": relative_tolerance, "angle_deg": angle_tolerance_deg,
                           "max_unmatched": max_unmatched},
            "candidates": chosen, "search": stats,
            "ambiguity": {"multiple_candidates": len(ordered) > 1, "unique_chemical_phase_claim": False,
                          "bounded_search_does_not_establish_uniqueness": True,
                          "compatible_c_over_a_values": [r for r in ratios if any(c["c_over_a"] == r for c in ordered)]},
            "basis": {"fractional_positions": [[0., 0., 0.], [1. / 3., 2. / 3., .5]],
                      "assumption": "two_identical_unit_scatterers_ideal_AB_stacking",
                      "diagnostics_only": True},
            "limitations": ["Hexagonal metric compatibility is not proof of HCP stacking or chemical phase.",
                            "Two-atom identical-scatterer cancellations are diagnostics, not dynamical electron exclusion rules.",
                            "No continuous c/a fitting; default ideal c/a is an explicit assumption.",
                            "Basal-only reflections cannot constrain c/a, even when a is absolutely calibrated.",
                            "Finite hkil bounds and local refinement may miss alternatives; no uniqueness guarantee."]}
