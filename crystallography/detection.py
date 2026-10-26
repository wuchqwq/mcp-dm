"""Optional external SciPy spot localization with conservative centre evidence.

No DigitalMicrograph calls or crystallographic/phase feedback occur here.
Positions are capture-local pixel centres. Returned sigma_px is unknown: a
centroid or a Friedel-pair residual is not a statistical localization error.
"""
import math

import numpy as np
import scipy
from scipy import ndimage
from scipy.cluster.hierarchy import fclusterdata
from scipy.optimize import least_squares, linear_sum_assignment
from scipy.spatial.distance import cdist
from scipy.stats import median_abs_deviation


MAX_ARRAY_BYTES = 16 * 1024 * 1024
MAX_CANDIDATES = 64
MAX_CENTER_HYPOTHESES = 32
_METHOD = "external SciPy Gaussian/local-maxima/connected-components/centre-of-mass; explicit-centre disk excluded before localization; Friedel assignment and robust least-squares centre"


def _require(value, message):
    if not value:
        raise ValueError(message)


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _base_diagnostics(array, threshold_rel, min_distance, exclude_radius, tolerance):
    return {"execution": "explicit external Python/SciPy", "scipy_version": scipy.__version__,
            "numpy_version": np.__version__, "dm_called": False,
            "coordinate_convention": "capture-local pixel centres, XY; x increases right, y down",
            "shape_yx": list(array.shape), "input_dtype": str(array.dtype),
            "original_pixels_changed": False, "input_byte_budget": MAX_ARRAY_BYTES,
            "input_pixel_budget": MAX_ARRAY_BYTES//4,
            "candidate_budget": MAX_CANDIDATES, "center_hypothesis_budget": MAX_CENTER_HYPOTHESES,
            "threshold_rel": threshold_rel, "min_distance_px": min_distance,
            "exclude_radius_px": exclude_radius, "center_tolerance_px": tolerance,
            "centre_is_not_assumed_brightest_or_image_midpoint": True,
            "uncertainty_status": "UNKNOWN: centroid and pair residual are not localization sigma",
            "limitations": ["geometric Friedel symmetry does not prove the direct beam or a phase",
                            "overlap, saturation, a cropped pattern or dynamical asymmetry may require review",
                            "no indexing or reference-structure fit is used to choose or recalibrate the centre"],
            "reasons": []}


def _answer(center, spots, status, diagnostics):
    return {"center_xy": None if center is None else [float(v) for v in center],
            "spots": [{"id": "auto-{:03d}".format(index+1), "xy": [float(v) for v in point], "sigma_px": None}
                      for index, point in enumerate(spots)],
            "status": status, "diagnostics": diagnostics, "method": _METHOD}


def _localize(array, min_distance, threshold_rel, diagnostics, center_xy=None, exclude_radius=0):
    # SciPy owns filtering, connected-component detection and subpixel centroid
    # evaluation. Float64 is localization working storage, not a new scientific
    # intensity file or an altered source array.
    source = np.array(array, dtype=np.float64, copy=True)
    excluded = None
    mask_evidence = {"applied": False, "center_xy": None, "radius_px": exclude_radius,
                     "coordinate_rule": "hypot(x-center_x,y-center_y) <= radius_px; pixel centres",
                     "masked_pixels": 0, "replacement": None,
                     "scope": "independent localization working copy only; scientific input unchanged",
                     "reason": "NO_EXPLICIT_CENTER"}
    if center_xy is not None:
        yy, xx = np.ogrid[:array.shape[0], :array.shape[1]]
        excluded = np.hypot(xx-center_xy[0], yy-center_xy[1]) <= exclude_radius
        count = int(np.count_nonzero(excluded))
        mask_evidence.update(center_xy=list(center_xy), masked_pixels=count,
                             applied=count > 0,
                             reason="EXPLICIT_CENTER_DISK" if count else "DISK_OUTSIDE_CAPTURE")
        diagnostics["prelocalization_center_exclusion"] = mask_evidence
        if count == source.size:
            diagnostics["reasons"].append("NO_UNMASKED_LOCALIZATION_PIXELS")
            return [], []
    surviving = source if excluded is None else source[~excluded]
    magnitude = float(np.max(np.abs(surviving)))
    # Normalize using surviving values, so an excluded bright DC cannot impose
    # either a floating-point floor or a Gaussian halo on faint reflections.
    if excluded is not None:
        source[excluded] = 0
    if magnitude:
        source /= magnitude
    if excluded is not None and mask_evidence["applied"]:
        replacement = float(np.median(source[~excluded]))
        source[excluded] = replacement
        mask_evidence.update(replacement="median of unmasked normalized working values",
                             replacement_normalized=replacement)
    diagnostics["prelocalization_center_exclusion"] = mask_evidence
    work = ndimage.gaussian_filter(source, sigma=.65, mode="nearest")
    background = float(np.median(work))
    noise = float(median_abs_deviation(work, scale="normal", axis=None))
    contrast = float(np.max(work) - background)
    diagnostics.update(background_smoothed=background, robust_noise_sigma_smoothed=noise,
                       smoothing_sigma_px=.65, noise_gate_sigma=5., working_intensity_scale=magnitude,
                       localization_intensity_units="raw values / max absolute unmasked raw value; localization only, no intensity calibration")
    if contrast <= 0:
        diagnostics["reasons"].append("NO_POSITIVE_PEAK_CONTRAST")
        return [], []
    maxima = work == ndimage.maximum_filter(work, size=2*min_distance+1, mode="constant", cval=-np.inf)
    if excluded is not None:
        maxima &= ~excluded
    # Excluding the single brightest peak from a threshold reference is not a
    # centre choice. A median of at most twelve candidate heights lets a bright
    # direct beam coexist with weaker spots instead of defining their cutoff.
    preliminary = maxima & (work > background + max(5*noise, contrast*1e-12))
    heights = work[preliminary] - background
    if not heights.size:
        diagnostics["reasons"].append("NO_PEAK_ABOVE_NOISE_GATE")
        return [], []
    reference = float(np.median(np.sort(heights)[-12:]))
    threshold = background + max(5*noise, threshold_rel*reference)
    labels, count = ndimage.label(maxima & (work >= threshold))
    diagnostics.update(threshold_reference="median of up to twelve largest local-maxima contrasts; not brightest-beam centre",
                       threshold_reference_contrast=reference, threshold_smoothed=threshold,
                       detected_maximum_components=int(count))
    if count > MAX_CANDIDATES:
        diagnostics["reasons"].append("CANDIDATE_BUDGET_EXCEEDED")
        return [], []
    points, values, evidence = [], [], []
    radius = min(3, max(1, min_distance))
    edge_count, plateau_count = 0, 0
    for index, bounds in enumerate(ndimage.find_objects(labels)):
        if bounds is None:
            continue
        plateau = labels[bounds] == index+1
        if int(np.count_nonzero(plateau)) > 9:
            plateau_count += 1
            continue
        plateau_center = ndimage.center_of_mass(plateau)
        y = int(round(bounds[0].start + plateau_center[0]))
        x = int(round(bounds[1].start + plateau_center[1]))
        if x < radius or y < radius or x+radius >= array.shape[1] or y+radius >= array.shape[0]:
            edge_count += 1
            continue
        patch = work[y-radius:y+radius+1, x-radius:x+radius+1]
        weights = np.maximum(patch-background, 0)
        cy, cx = ndimage.center_of_mass(weights)
        px, py = x-radius+float(cx), y-radius+float(cy)
        if not math.isfinite(px+py) or abs(px-x) > 1. or abs(py-y) > 1.:
            continue
        point = [px, py]
        height = float(work[y, x]-background)
        points.append(point); values.append(height)
        evidence.append({"xy": point, "local_maximum_pixel_xy": [x, y],
                         "smoothed_height_above_background": height,
                         "centroid_patch_radius_px": radius, "sigma_px": None})
    diagnostics.update(localization="SciPy centre_of_mass of positive background-subtracted smoothed local patches",
                       peak_localization=evidence, edge_candidates_excluded=edge_count,
                       unresolved_plateaus_excluded=plateau_count, localized_candidates=len(points))
    return points, values


def _pairs(points, center, exclude_radius, tolerance):
    n = len(points)
    if n < 2:
        return [], 0
    radii = np.linalg.norm(points-center, axis=1)
    eligible = radii > exclude_radius
    # Dummy assignments permit unmatched spots; no bad match is forced merely
    # to fill an assignment. Reciprocal i<->j pairs are independent observations.
    distance = cdist(points, 2*center-points)
    np.fill_diagonal(distance, 1e12)
    distance[~eligible, :] = 1e12
    distance[:, ~eligible] = 1e12
    penalty = 2*tolerance
    cost = np.full((2*n, 2*n), 1e12)
    cost[:n, :n] = np.where(distance <= penalty, distance, 1e12)
    cost[n:, n:] = 0
    cost[np.arange(n), n+np.arange(n)] = penalty
    cost[n+np.arange(n), np.arange(n)] = penalty
    rows, columns = linear_sum_assignment(cost)
    mapping = dict(zip(rows.tolist(), columns.tolist()))
    pairs = [(i, j) for i, j in mapping.items() if i < n and i < j < n and
             mapping.get(j) == i and distance[i, j] <= penalty]
    return pairs, int(np.count_nonzero(eligible))


def _noncollinear(points, pairs, center):
    if len(pairs) < 3:
        return False
    vectors = np.asarray([points[i]-center for i, _ in pairs])
    norms = np.linalg.norm(vectors, axis=1)
    if np.any(norms <= 0):
        return False
    singular = np.linalg.svd(vectors / norms[:, None], compute_uv=False)
    return bool(len(singular) == 2 and singular[1] / singular[0] >= .08)


def _centre(points, exclude_radius, tolerance, diagnostics):
    if len(points) < 6:
        diagnostics["reasons"].append("AUTO_CENTER_REQUIRES_AT_LEAST_THREE_OPPOSITE_PAIRS")
        return None, []
    # Candidate midpoints and SciPy complete-link clustering bound hypotheses.
    # This purely geometric step has no chemistry, indexing or intensity score.
    left, right = np.triu_indices(len(points), k=1)
    midpoints = (points[left]+points[right]) / 2
    clusters = fclusterdata(midpoints, t=tolerance, criterion="distance", method="complete")
    candidates = []
    for label in np.unique(clusters):
        members = midpoints[clusters == label]
        if len(members) >= 3:
            candidates.append(np.median(members, axis=0))
    diagnostics["center_hypotheses_tested"] = len(candidates)
    if len(candidates) > MAX_CENTER_HYPOTHESES:
        diagnostics["reasons"].append("CENTER_HYPOTHESIS_BUDGET_EXCEEDED")
        return None, []
    solutions = []
    for candidate in candidates:
        center = np.asarray(candidate, dtype=np.float64)
        for _ in range(2):
            pairs, eligible = _pairs(points, center, exclude_radius, tolerance)
            if len(pairs) < 3:
                break
            pair_points = np.asarray([(points[i]+points[j])/2 for i, j in pairs])
            fitted = least_squares(lambda xy: (pair_points-xy).ravel(), center,
                                   loss="soft_l1", f_scale=tolerance, max_nfev=64)
            if not fitted.success or not np.isfinite(fitted.x).all():
                break
            center = fitted.x
        pairs, eligible = _pairs(points, center, exclude_radius, tolerance)
        if len(pairs) < 3 or not _noncollinear(points, pairs, center):
            continue
        errors = np.asarray([np.linalg.norm((points[i]+points[j])/2-center) for i, j in pairs])
        coverage = 2*len(pairs) / eligible if eligible else 0
        if float(np.max(errors)) > tolerance:
            continue
        if any(np.linalg.norm(center-old["center"]) <= tolerance for old in solutions):
            continue
        solutions.append({"center": center, "pairs": pairs, "eligible": eligible,
                          "coverage": coverage, "rms": float(np.sqrt(np.mean(errors**2))),
                          "maximum_residual": float(np.max(errors))})
    solutions.sort(key=lambda value: (-len(value["pairs"]), value["rms"]))
    diagnostics["center_candidates"] = [
        {"xy": solution["center"].tolist(), "independent_opposite_pairs": len(solution["pairs"]),
         "paired_fraction": solution["coverage"], "midpoint_rms_px": solution["rms"],
         "maximum_midpoint_residual_px": solution["maximum_residual"]}
        for solution in solutions]
    diagnostics["auto_center_acceptance"] = {
        "minimum_independent_pairs": 3, "minimum_paired_fraction": .70,
        "minimum_direction_singular_value_ratio": .08,
        "maximum_midpoint_residual_px": tolerance,
        "ambiguity": "distinct centres with at least max(3,best_pairs-1) pairs require review"}
    qualified = [value for value in solutions if value["coverage"] >= .70]
    if not qualified:
        diagnostics["reasons"].append("NO_UNIQUE_NONCOLLINEAR_FRIEDEL_CONSENSUS")
        return None, []
    best = qualified[0]
    diagnostics["best_center_candidate_xy"] = best["center"].tolist()
    alternatives = [value for value in solutions if np.linalg.norm(value["center"]-best["center"]) > tolerance]
    # A union of two translated symmetric patterns can have a perfect, spurious
    # global inversion centre. Keep their disjoint local consensuses rather
    # than discarding them for failing the global coverage gate.
    disjoint = False
    for i, first in enumerate(alternatives):
        first_indices = {index for pair in first["pairs"] for index in pair}
        for second in alternatives[i+1:]:
            second_indices = {index for pair in second["pairs"] for index in pair}
            if not first_indices.intersection(second_indices) and len(first_indices | second_indices) >= .70*len(points):
                disjoint = True
    if disjoint:
        diagnostics["reasons"].append("MULTIPLE_DISJOINT_LOCAL_FRIEDEL_CENTERS")
        return None, []
    if any(candidate["coverage"] >= .70 and len(candidate["pairs"]) >= max(3, len(best["pairs"])-1)
           for candidate in alternatives):
        diagnostics["reasons"].append("AMBIGUOUS_FRIEDEL_CENTERS")
        return None, []
    diagnostics["center_evidence"] = {
        "source": "geometric Friedel-pair consensus, not direct-beam identity proof",
        "independent_opposite_pairs": len(best["pairs"]), "paired_fraction": best["coverage"],
        "midpoint_rms_px": best["rms"], "maximum_midpoint_residual_px": best["maximum_residual"],
        "sigma_px": None}
    return best["center"], best["pairs"]


def detect_spots(array, *, center_xy=None, max_spots=12, min_distance=3,
                 threshold_rel=.1, exclude_radius=2, center_tolerance_px=1):
    """Locate bounded spots; infer a centre only from a unique Friedel consensus.

    READY means the declared localization checks passed, never an indexed or
    uniquely identified phase. User/native-grid centres may lie outside a crop.
    NEEDS_REVIEW forbids a caller from silently using a best centre candidate.
    """
    _require(type(array) is np.ndarray and array.ndim == 2 and array.size > 0 and
             array.dtype.kind in "fiu" and array.nbytes <= MAX_ARRAY_BYTES and
             array.size <= MAX_ARRAY_BYTES//4 and
             np.isfinite(array).all(), "Bounded finite 2D real ndarray (<=16 MiB) required")
    if array.dtype.kind in "iu" and array.dtype.itemsize >= 8:
        _require(int(array.min()) >= -2**53 and int(array.max()) <= 2**53,
                 "Integer localization input exceeds exact binary64 range")
    _require(type(max_spots) is int and 2 <= max_spots <= 32 and
             type(min_distance) is int and 1 <= min_distance <= 64 and
             _finite(threshold_rel) and 0 < threshold_rel < 1 and
             _finite(exclude_radius) and 0 <= exclude_radius <= 4096 and
             _finite(center_tolerance_px) and 0 < center_tolerance_px <= 8,
             "Invalid bounded spot detection parameters")
    if center_xy is not None:
        _require(type(center_xy) in (list, tuple) and len(center_xy) == 2 and all(_finite(v) for v in center_xy),
                 "Explicit finite centre XY pixel coordinates required")
    diagnostics = _base_diagnostics(array, threshold_rel, min_distance, exclude_radius, center_tolerance_px)
    points, heights = _localize(array, min_distance, threshold_rel, diagnostics, center_xy, exclude_radius)
    if not points:
        diagnostics["reasons"].append("NO_RELIABLY_LOCALIZED_SPOTS")
        return _answer(center_xy, [], "NEEDS_REVIEW", diagnostics)
    points = np.asarray(points, dtype=np.float64)
    heights = np.asarray(heights)
    if center_xy is None:
        center, pairs = _centre(points, exclude_radius, center_tolerance_px, diagnostics)
        if center is None:
            return _answer(None, [], "NEEDS_REVIEW", diagnostics)
        # Select complete opposite pairs for the optional output budget. Pair
        # ranking uses the weaker partner, avoiding a single bright reflection.
        pairs.sort(key=lambda pair: -float(min(heights[pair[0]], heights[pair[1]])))
        indices = [index for pair in pairs[:max_spots//2] for index in pair]
        diagnostics["selection_policy"] = "complete independent Friedel pairs ranked by weaker-partner height"
    else:
        center = np.asarray(center_xy, dtype=np.float64)
        eligible = np.flatnonzero(np.linalg.norm(points-center, axis=1) > exclude_radius)
        indices = sorted(eligible.tolist(), key=lambda index: -float(heights[index]))[:max_spots]
        diagnostics["selection_policy"] = "provided centre; highest localized contrasts outside explicit exclusion radius"
        diagnostics["center_evidence"] = {"source": "explicit caller-supplied centre; not inferred from brightness", "sigma_px": None}
    diagnostics["selected_spots"] = len(indices)
    diagnostics["excluded_radius_candidates"] = int(np.count_nonzero(np.linalg.norm(points-center, axis=1) <= exclude_radius))
    if len(indices) < 2:
        diagnostics["reasons"].append("FEWER_THAN_TWO_SELECTED_SPOTS")
        return _answer(center, points[indices], "NEEDS_REVIEW", diagnostics)
    return _answer(center, points[indices], "READY", diagnostics)
