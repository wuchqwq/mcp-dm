"""Bounded *external* cubic reciprocal-geometry candidate search.

This is not a DM operator, diffraction simulation, or phase identifier.  The
only extinction rules used are integral P/I/F centring conditions (IUCr
Integral_reflection_conditions).  A chemical basis, dynamical scattering and
missing reflections are deliberately not inferred.  NumPy supplies linear
algebra; SciPy supplies one-to-one linear assignment.
"""

import itertools
import math
from functools import lru_cache

import numpy as np
from scipy.optimize import linear_sum_assignment
from .geometry import _require_noncollinear

MAX_SEARCH_SEEDS = 50000


def _integer(value, name, lower, upper):
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise ValueError("{} must be an integer".format(name))
    if not lower <= value <= upper:
        raise ValueError("{} must be in [{}, {}]".format(name, lower, upper))
    return int(value)


def _number(value, name, lower, upper):
    if isinstance(value, (bool, str, bytes)):
        raise ValueError("{} must be a finite number".format(name))
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("{} must be a finite number".format(name))
    if not math.isfinite(value) or not lower <= value <= upper:
        raise ValueError("{} must be in [{}, {}]".format(name, lower, upper))
    return value


def _allowed(hkl, centering):
    if centering == "I":
        return np.sum(hkl, axis=1) % 2 == 0
    if centering == "F":
        parity = hkl % 2
        return np.all(parity == parity[:, :1], axis=1)
    return np.ones(len(hkl), dtype=bool)


@lru_cache(maxsize=12)
def _lattice(max_index, centering):
    hkl = np.array(list(itertools.product(range(-max_index, max_index + 1), repeat=3)),
                   dtype=np.int64)
    hkl = hkl[np.any(hkl != 0, axis=1)]
    hkl = hkl[_allowed(hkl, centering)]
    anchors = hkl[(hkl[:, 0] >= hkl[:, 1]) & (hkl[:, 1] >= hkl[:, 2]) &
                  (hkl[:, 2] >= 0)]
    return hkl, anchors


def _primitive_zone(normal):
    normal = [int(v) for v in normal]
    divisor = math.gcd(math.gcd(abs(normal[0]), abs(normal[1])), abs(normal[2]))
    return [v // divisor for v in normal]


def _canonical_assignment(hkl, matched):
    """Quotient cubic signed-axis permutations, not arbitrary equal Gram sets."""
    rows = hkl[matched]
    choices = []
    for perm in itertools.permutations(range(3)):
        permuted = rows[:, perm]
        for signs in itertools.product((-1, 1), repeat=3):
            choices.append(tuple((permuted * signs).ravel().tolist()))
    return tuple(np.flatnonzero(matched).tolist()), min(choices)


def _assign(observed, predicted, relative_tolerance, angle_tolerance):
    norms = np.linalg.norm(observed, axis=1)
    predicted_norms = np.linalg.norm(predicted, axis=1)
    radial = np.abs(norms[:, None] - predicted_norms[None, :]) / norms[:, None]
    cosine = observed @ predicted.T / (norms[:, None] * predicted_norms[None, :])
    angles = np.degrees(np.arccos(np.clip(cosine, -1., 1.)))
    allowed = (radial <= relative_tolerance + 1e-12) & (angles <= angle_tolerance + 1e-9)
    # A dummy is cheaper than every forbidden match; all valid assignments are
    # cheaper than a dummy.  This maximises matched count before residual.
    score = radial / relative_tolerance + angles / angle_tolerance
    cost = np.where(allowed, score, 1e9)
    cost = np.concatenate((cost, np.full((len(observed), len(observed)), 1e6)), axis=1)
    _, columns = linear_sum_assignment(cost)
    matched = columns < len(predicted)
    return columns, matched


def _fit(local, observed, fixed_scale, in_plane_parity):
    # In-plane handedness follows the two observed anchors.  Both signs yield
    # a proper 3D orientation when its beam row is their cross product; a
    # mirrored pattern reverses the signed zone rather than implying chirality.
    left, _, right = np.linalg.svd(local.T @ observed)
    rotation = left @ right
    if np.linalg.det(rotation) * in_plane_parity < 0:
        left[:, -1] *= -1
        rotation = left @ right
    fitted = local @ rotation
    scale = fixed_scale
    if scale is None:
        scale = float(np.sum(fitted * observed) / np.sum(local * local))
    return rotation, scale


def _joint_angle_error(observed, predicted):
    lengths_a = np.linalg.norm(observed, axis=1)
    lengths_b = np.linalg.norm(predicted, axis=1)
    ca = observed @ observed.T / np.outer(lengths_a, lengths_a)
    cb = predicted @ predicted.T / np.outer(lengths_b, lengths_b)
    aa = np.degrees(np.arccos(np.clip(ca, -1, 1)))
    ab = np.degrees(np.arccos(np.clip(cb, -1, 1)))
    np.fill_diagonal(aa, 0)
    np.fill_diagonal(ab, 0)
    return float(np.max(np.abs(aa - ab)))


def index_cubic(vectors, *, calibrated, max_index=3, centerings=("F", "I", "P"),
                relative_tolerance=0.03, angle_tolerance_deg=2.0,
                candidate_lattice_nm=None, max_candidates=20, max_unmatched=0):
    """Jointly match 3..12 explicit reciprocal vectors to bounded cubic candidates.

    ``vectors`` are physical XY cycles/nm when calibrated, or explicitly
    isotropic relative reciprocal XY coordinates otherwise.  Pixel calibration,
    FFT conventions and distortion must be resolved by the caller.  A supplied
    ``candidate_lattice_nm`` maps F/I/P to fixed positive lattice parameters;
    absent entries are fitted once, jointly.  Fixed parameters are never refit.
    ``max_unmatched`` is an explicit outlier allowance, zero by default.

    The search exhausts canonical first reflections, all second reflections and
    every usable observation pair within the reported bounds.  It is a bounded
    two-anchor/local joint least-squares search, not a proof that every noisy
    indexing exists or that the best geometric candidate is a chemical phase.
    """
    if not isinstance(calibrated, bool):
        raise ValueError("calibrated must be boolean")
    max_index = _integer(max_index, "max_index", 1, 4)
    max_candidates = _integer(max_candidates, "max_candidates", 1, 100)
    relative_tolerance = _number(relative_tolerance, "relative_tolerance", 1e-6, .15)
    angle_tolerance_deg = _number(angle_tolerance_deg, "angle_tolerance_deg", .001, 10.)
    try:
        raw = np.asarray(vectors)
        if raw.dtype.kind not in "iuf":
            raise ValueError("vectors must contain real numeric values, without string coercion")
        observed = raw.astype(np.float64, copy=False)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("vectors must be a finite real Nx2 array")
    if observed.ndim != 2 or observed.shape[1] != 2 or not 3 <= len(observed) <= 12:
        raise ValueError("vectors must have shape [3..12, 2]")
    if not np.all(np.isfinite(observed)) or np.max(np.abs(observed)) > 1e12:
        raise ValueError("vectors must be finite and bounded by 1e12")
    norms = np.linalg.norm(observed, axis=1)
    if np.min(norms) < 1e-12 or np.max(norms) / np.min(norms) > 1e6:
        raise ValueError("zero or numerically unresolved reciprocal vectors")
    distances = np.linalg.norm(observed[:, None, :] - observed[None, :, :], axis=2)
    np.fill_diagonal(distances, np.inf)
    if np.min(distances) <= np.max(norms) * 1e-10:
        raise ValueError("duplicate reciprocal observations")
    max_unmatched = _integer(max_unmatched, "max_unmatched", 0, len(observed) - 3)
    if not isinstance(centerings, (list, tuple)) or not centerings or any(
            c not in ("F", "I", "P") for c in centerings) or len(set(centerings)) != len(centerings):
        raise ValueError("centerings must be a nonempty unique list of F/I/P")
    centerings = tuple(c for c in ("F", "I", "P") if c in centerings)
    if candidate_lattice_nm is None:
        candidate_lattice_nm = {}
    if not isinstance(candidate_lattice_nm, dict) or any(
            c not in centerings for c in candidate_lattice_nm):
        raise ValueError("candidate_lattice_nm must map requested centerings to lattice nm")
    if candidate_lattice_nm and not calibrated:
        raise ValueError("fixed lattice parameters require absolute reciprocal calibration")
    fixed = {c: _number(v, "candidate lattice nm", 1e-6, 1e6)
             for c, v in candidate_lattice_nm.items()}
    _require_noncollinear(observed)
    found = {}
    stats = {"anchor_pairs_considered": 0, "anchor_seeds_after_geometric_pruning": 0,
             "joint_fits_evaluated": 0}
    for centering in centerings:
        all_hkl, first_hkl = _lattice(max_index, centering)
        all_norms = np.linalg.norm(all_hkl, axis=1)
        fixed_scale = 1. / fixed[centering] if centering in fixed else None
        seen_seeds = set()
        for i, j in itertools.combinations(range(len(observed)), 2):
            cross_observed = float(np.linalg.det(observed[[i, j]]))
            if abs(cross_observed) <= norms[i] * norms[j] * 1e-7:
                continue
            cosine_observed = float(np.dot(observed[i], observed[j]) / (norms[i] * norms[j]))
            observed_angle = math.degrees(math.acos(np.clip(cosine_observed, -1, 1)))
            observed_ratio = norms[j] / norms[i]
            image_u = observed[i] / norms[i]
            image_v = np.array([-image_u[1], image_u[0]]) * np.sign(cross_observed)
            image_basis = np.stack((image_u, image_v))
            for first in first_hkl:
                first_norm = float(np.linalg.norm(first))
                stats["anchor_pairs_considered"] += len(all_hkl)
                ratios = all_norms / first_norm
                ratio_limit = 2 * relative_tolerance / (1 - relative_tolerance)
                pair_mask = np.abs(ratios / observed_ratio - 1) <= ratio_limit
                pair_angles = np.degrees(np.arccos(np.clip(all_hkl @ first /
                                                          (all_norms * first_norm), -1, 1)))
                pair_mask &= np.abs(pair_angles - observed_angle) <= angle_tolerance_deg
                if fixed_scale is not None:
                    pair_mask &= abs(first_norm * fixed_scale / norms[i] - 1) <= relative_tolerance
                    pair_mask &= np.abs(all_norms * fixed_scale / norms[j] - 1) <= relative_tolerance
                for second in all_hkl[pair_mask]:
                    normal = np.cross(first, second)
                    if not np.any(normal):
                        continue
                    primitive = _primitive_zone(normal)
                    # Same plane and initial reflection have identical initial
                    # orientation/scale regardless of which collinear second
                    # reflection produced the seed.
                    seed_key = (i, j, tuple(first), tuple(primitive))
                    if seed_key in seen_seeds:
                        continue
                    seen_seeds.add(seed_key)
                    stats["anchor_seeds_after_geometric_pruning"] += 1
                    if stats["anchor_seeds_after_geometric_pruning"] > MAX_SEARCH_SEEDS:
                        raise ValueError("cubic search seed budget exceeded; reduce observations, "
                                         "max_index or tolerances; no partial candidate result returned")
                    unit_normal = normal / np.linalg.norm(normal)
                    crystal_u = first / first_norm
                    crystal_v = np.cross(unit_normal, crystal_u)
                    crystal_basis = np.stack((crystal_u, crystal_v))
                    plane_hkl = all_hkl[(all_hkl @ normal) == 0]
                    local = plane_hkl @ crystal_basis.T
                    scale = fixed_scale if fixed_scale is not None else norms[i] / first_norm
                    rotation = image_basis
                    matched = None
                    # Three bounded refinement steps, each one-to-one and using
                    # one shared orientation/scale, never a per-spot lattice.
                    for _ in range(3):
                        predicted_all = scale * local @ rotation
                        columns, matched = _assign(observed, predicted_all,
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
                    key = (centering, _canonical_assignment(assignments, matched))
                    errors = np.linalg.norm(predicted - observed[matched], axis=1)
                    relative_errors = errors / norms[matched]
                    rms = float(np.sqrt(np.mean(relative_errors ** 2)))
                    previous = found.get(key)
                    if previous is not None and previous["rms_relative_vector_residual"] <= rms:
                        continue
                    oriented_xy = rotation.T @ crystal_basis
                    orientation = np.vstack((oriented_xy, np.cross(oriented_xy[0], oriented_xy[1])))
                    zone = _primitive_zone(normal)
                    if np.dot(orientation[2], zone) < 0:
                        zone = [-v for v in zone]
                    observations = []
                    cursor = 0
                    for k in range(len(observed)):
                        if matched[k]:
                            predicted_norm = float(np.linalg.norm(predicted[cursor]))
                            direction_cosine = np.dot(predicted[cursor], observed[k]) / (predicted_norm * norms[k])
                            observations.append({"observation_index": k, "matched": True,
                                                 "hkl": assignments[k].tolist(),
                                                 "predicted_vector": predicted[cursor].tolist(),
                                                 "observed_magnitude": float(norms[k]),
                                                 "predicted_magnitude": predicted_norm,
                                                 "relative_radial_residual": float(abs(predicted_norm / norms[k] - 1)),
                                                 "direction_residual_deg": math.degrees(math.acos(np.clip(direction_cosine, -1, 1))),
                                                 "individual_lattice_estimate_nm": float(np.linalg.norm(assignments[k]) / norms[k]) if calibrated else None,
                                                 "vector_residual": float(errors[cursor]),
                                                 "relative_vector_residual": float(relative_errors[cursor])})
                            cursor += 1
                        else:
                            observations.append({"observation_index": k, "matched": False,
                                                 "hkl": None, "reason": "outside_joint_candidate_tolerance"})
                    found[key] = {
                        "centering": centering, "structure_label": {"F": "FCC", "I": "BCC", "P": "primitive cubic"}[centering],
                        "lattice_parameter_nm": fixed.get(centering, float(1 / scale)) if calibrated else None,
                        "lattice_parameter_source": "fixed_reference" if fixed_scale is not None else
                            ("joint_geometric_fit" if calibrated else "not_absolutely_calibrated"),
                        "reciprocal_scale_per_hkl": float(scale),
                        "reciprocal_scale_unit": "cycles/nm" if calibrated else "relative",
                        "zone_axis_uvw": zone, "crystal_to_image_orientation": orientation.tolist(),
                        "orientation_convention": "column g_image_xyz = orientation @ hkl * reciprocal_scale; right-handed; beam +z",
                        "matched_count": int(np.count_nonzero(matched)),
                        "unmatched_observation_indices": np.flatnonzero(~matched).tolist(),
                        "rms_relative_vector_residual": rms,
                        "max_pair_angle_residual_deg": pair_error,
                        "observations": observations,
                        "chemical_phase_identified": False,
                    }
    candidates = sorted(found.values(), key=lambda c: (-c["matched_count"],
                         c["rms_relative_vector_residual"], c["centering"],
                         c["reciprocal_scale_per_hkl"], c["zone_axis_uvw"]))
    counts = {c: sum(v["centering"] == c for v in candidates) for c in centerings}
    # Show at least one candidate from every successful centering, even when a
    # caller's display limit is smaller.  A limit must never erase ambiguity.
    representatives = [next(v for v in candidates if v["centering"] == c)
                       for c in centerings if counts[c]]
    selected = list(representatives)
    for candidate in candidates:
        if len(selected) >= max(max_candidates, len(representatives)):
            break
        if not any(candidate is previous for previous in selected):
            selected.append(candidate)
    selected.sort(key=lambda c: (-c["matched_count"], c["rms_relative_vector_residual"], c["centering"]))
    stats.update({"max_index": max_index, "max_observations": 12,
                  "max_search_seeds": MAX_SEARCH_SEEDS,
                  "requested_centerings": list(centerings), "candidate_counts_by_centering": counts,
                  "total_distinct_candidates": len(candidates), "returned_candidates": len(selected),
                  "requested_max_candidates": max_candidates,
                  "output_truncated": len(candidates) > len(selected),
                  "anchor_enumeration_exhausted": True,
                  "method": "canonical_cubic_two_anchor_then_three_joint_procrustes_assignment_steps",
                  "global_noisy_solution_completeness_proven": False})
    return {"schema_version": 1, "computation_source": "external_python_crystallography",
            "model": "bounded_cubic_reciprocal_geometry", "calibrated": calibrated,
            "input_vectors": observed.tolist(),
            "frequency_convention": "cycles_per_length; |g|=1/d",
            "tolerances": {"relative_radial": relative_tolerance, "angle_deg": angle_tolerance_deg,
                           "max_unmatched": max_unmatched},
            "candidates": selected, "search": stats,
            "ambiguity": {"multiple_candidates": len(candidates) > 1,
                          "compatible_centerings": [c for c in centerings if counts[c]],
                          "unique_chemical_phase_claim": False,
                          "bounded_search_does_not_establish_uniqueness": True},
            "limitations": ["Cubic metric and integral centering only; no chemical basis or intensities.",
                            "Dynamical/multiple scattering and unobserved reflections are not modelled.",
                            "A common lattice parameter and orientation are checked; this is not phase identification.",
                            "Supplied absolute calibration and fixed reference lattice are never adjusted to force a match.",
                            "Finite hkl bounds and local noisy refinement can miss alternatives."]}
