"""Selected-point geometry in physical reciprocal coordinates, not display pixels.

No peak finder, native operation or phase inference lives here. NumPy evaluates
the affine map and first-order uncertainty propagation. The common centre and
axis-scale errors are correlated between observations, including angle errors.
"""
import math
import numpy as np


class GeometryError(ValueError):
    pass


class NonIdentifiableGeometry(ValueError):
    """Valid measured vectors cannot constrain a two-dimensional index frame."""


def _require_noncollinear(vectors):
    # Keep the existing indexer conditioning threshold; this is a typed cause,
    # not a relaxed measurement, fit tolerance or substitute indexing method.
    singular = np.linalg.svd(vectors, compute_uv=False)
    if singular[-1] <= singular[0] * 1e-8:
        raise NonIdentifiableGeometry("noncollinear reciprocal observations are required")


def require(condition, message):
    if not condition:
        raise GeometryError(message)


def vector2(value, name, nonnegative=False):
    require(isinstance(value, (list, tuple, np.ndarray)) and len(value) == 2,
            name + " must contain x and y")
    require(all(type(v) in (int, float) and math.isfinite(v) for v in value),
            name + " must contain finite numbers, not booleans")
    result = np.asarray(value, dtype=float)
    require(not nonnegative or bool((result >= 0).all()), name + " must be nonnegative")
    return result


def reciprocal_unit(unit, convention):
    """Return factor into cycles/nm; never infer 2*pi from an inverse unit."""
    factors = {"1/nm": 1.0, "nm^-1": 1.0, "1/angstrom": 10.0,
               "angstrom^-1": 10.0, "1/Å": 10.0, "Å^-1": 10.0,
               "rad/nm": 1.0, "rad/angstrom": 10.0}
    require(unit in factors, "Unsupported reciprocal unit; supply an explicit supported calibration")
    require(convention in ("cycles_per_length", "radians_per_length"),
            "Explicit cycles_per_length or radians_per_length convention required")
    require(not unit.startswith("rad/") or convention == "radians_per_length",
            "rad/length requires radians_per_length convention")
    factor = factors[unit]
    if convention == "radians_per_length":
        factor /= 2 * math.pi
    return factor


def calibration_map(spec, capture_axes=None):
    """Normalize a recorded calibration, independently of candidate fitting."""
    require(type(spec) is dict, "Explicit calibration object required")
    mode = spec.get("mode")
    if mode == "relative":
        require(type(spec.get("isotropic_pixel_geometry_confirmed")) is bool,
                "Relative geometry needs an explicit isotropic-pixel confirmation")
        return {"mode": mode, "scale_xy": [1.0, 1.0], "zero_xy": [0.0, 0.0],
                "calibrated": False,
                "geometry_usable": spec["isotropic_pixel_geometry_confirmed"],
                "unit": "relative", "scale_sigma_xy": None,
                "basis": "user-confirmed isotropic pixels" if spec["isotropic_pixel_geometry_confirmed"]
                else "pixel geometry only; physical angles and ratios unavailable",
                "input": spec}
    require(mode in ("explicit", "capture_axes"), "Unknown calibration mode")
    if mode == "capture_axes":
        require(type(capture_axes) is list and len(capture_axes) == 2,
                "Two saved XY calibration axes required")
        units = [axis.get("unit") for axis in capture_axes]
        scales = [axis.get("scale") for axis in capture_axes]
        zeros = [axis.get("calibrated_value_at_pixel_zero") for axis in capture_axes]
        # Different nm/angstrom units on the two axes are converted separately.
        factors = [reciprocal_unit(unit, spec.get("convention")) for unit in units]
        scale = vector2(scales, "saved signed scale") * factors
        zero = vector2(zeros, "saved physical zero") * factors
        basis = "saved capture axes; user declared reciprocal convention"
    else:
        require(type(spec.get("basis")) is str and 0 < len(spec["basis"]) <= 1024,
                "Explicit calibration must record its independent basis")
        factor = reciprocal_unit(spec.get("unit"), spec.get("convention"))
        factors = [factor, factor]
        scale = vector2(spec.get("scale_xy"), "explicit signed scale") * factor
        zero = vector2(spec.get("zero_xy", [0.0, 0.0]), "explicit physical zero") * factor
        basis = spec["basis"]
    require(bool((scale != 0).all()), "Reciprocal scales must be nonzero")
    sigma = spec.get("scale_sigma_xy")
    if sigma is not None:
        sigma = (vector2(sigma, "scale uncertainty", True) * factors).tolist()
    return {"mode": mode, "scale_xy": scale.tolist(), "zero_xy": zero.tolist(),
            "calibrated": True, "geometry_usable": True, "unit": "cycles/nm",
            "scale_sigma_xy": sigma, "basis": basis, "input": spec}


def measure_geometry(center_xy, spots, mapping, center_sigma_px=None):
    """Coordinates share one pixel frame; sigma_px denotes independent 1-sigma SD.

    Missing uncertainty stays unknown. An explicit zero is an assumption of no
    error in that term, not an estimate inferred from deterministic data.
    """
    centre = vector2(center_xy, "centre")
    require(type(spots) is list and 1 <= len(spots) <= 128, "Provide 1..128 selected spots")
    scale = vector2(mapping["scale_xy"], "mapping scale")
    zero = vector2(mapping["zero_xy"], "mapping zero")
    require(bool((scale != 0).all()), "Zero mapping scale")
    c_sigma = None if center_sigma_px is None else vector2(center_sigma_px, "centre uncertainty", True)
    s_sigma = mapping.get("scale_sigma_xy")
    s_sigma = None if s_sigma is None else vector2(s_sigma, "scale uncertainty", True)
    items, seen, positions = [], set(), []
    for spot in spots:
        require(type(spot) is dict and type(spot.get("id")) is str and
                0 < len(spot["id"]) <= 64 and spot["id"] not in seen, "Unique bounded spot IDs required")
        seen.add(spot["id"])
        xy = vector2(spot.get("xy"), "spot coordinate")
        require(not any(np.array_equal(xy, previous) for previous in positions), "Repeated spot coordinates")
        positions.append(xy)
        delta = xy - centre
        g = delta * scale
        norm = float(np.linalg.norm(g))
        require(norm > 0 and math.isfinite(norm), "A selected reflection coincides with the centre or overflows")
        p_sigma = None if spot.get("sigma_px") is None else vector2(spot["sigma_px"], "spot uncertainty", True)
        known = c_sigma is not None and p_sigma is not None and s_sigma is not None
        sigma_g = None
        if known:
            variance = scale ** 2 * (p_sigma ** 2 + c_sigma ** 2) + delta ** 2 * s_sigma ** 2
            sigma_g = float(np.sqrt(np.sum((g / norm) ** 2 * variance)))
        absolute = mapping["calibrated"]
        usable = mapping["geometry_usable"]
        items.append({"id": spot["id"], "xy": xy.tolist(), "delta_xy": delta.tolist(),
                      "absolute_coordinate_xy": (zero + xy * scale).tolist() if absolute else None,
                      "g_xy_cycles_per_nm": g.tolist() if absolute else None,
                      "relative_vector_xy": g.tolist() if not absolute and usable else None,
                      "vector_length": norm, "vector_unit": mapping["unit"],
                      "d_nm": 1.0 / norm if absolute else None,
                      "d_unavailable_reason": None if absolute else "absolute reciprocal calibration missing",
                      "g_sigma": sigma_g, "d_sigma_nm": sigma_g / norm ** 2 if absolute and known else None,
                      "uncertainty_status": "first_order_independent_inputs_shared_centre_and_scale" if known else "UNKNOWN",
                      "sigma_px": None if p_sigma is None else p_sigma.tolist()})
    first = items[0]["vector_length"]
    for item in items:
        item["length_ratio_to_first"] = item["vector_length"] / first if mapping["geometry_usable"] else None
    angles = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            a = np.asarray(items[i]["delta_xy"]) * scale
            b = np.asarray(items[j]["delta_xy"]) * scale
            # atan2 remains accurate at almost parallel and antiparallel points.
            cross = a[0] * b[1] - a[1] * b[0]
            angle = math.degrees(math.atan2(abs(float(cross)), float(a @ b)))
            sigma_angle = None
            if all(items[k]["uncertainty_status"] != "UNKNOWN" for k in (i, j)):
                ja = np.array([-a[1], a[0]]) / float(a @ a)
                jb = np.array([-b[1], b[0]]) / float(b @ b)
                pa = np.asarray(items[i]["sigma_px"])
                pb = np.asarray(items[j]["sigma_px"])
                da, db = np.asarray(items[i]["delta_xy"]), np.asarray(items[j]["delta_xy"])
                variance = np.sum((ja * scale * pa) ** 2 + (jb * scale * pb) ** 2 +
                                  ((ja - jb) * scale * c_sigma) ** 2 +
                                  ((jb * db - ja * da) * s_sigma) ** 2)
                sigma_angle = math.degrees(math.sqrt(float(variance)))
            angles.append({"from": items[i]["id"], "to": items[j]["id"],
                           "angle_deg": angle if mapping["geometry_usable"] else None,
                           "sigma_deg": sigma_angle if mapping["geometry_usable"] else None,
                           "uncertainty_method": "linearized_unwrapped_angle; unreliable_at_0_or_180" if sigma_angle is not None else "UNKNOWN"})
    return {"computation": "explicit external NumPy selected-point geometry", "dm_called": False,
            "center_xy": centre.tolist(), "center_sigma_px": None if c_sigma is None else c_sigma.tolist(),
            "calibration": mapping, "spots": items, "angles": angles,
            "uncertainty_model": "Independent spot positions and independent x/y scale errors; centre and scales shared across spots. No distortion model or fitted covariance inferred.",
            "limitations": ["Geometry consumes supplied centre/spot coordinates; optional automatic localization is documented separately in detection evidence",
                            "Pixel/scale uncertainty is user supplied; missing terms remain unknown",
                            "Single-pattern geometry is not unique chemical phase evidence; dynamical scattering may produce forbidden reflections"]}
