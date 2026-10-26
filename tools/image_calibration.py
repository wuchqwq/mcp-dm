"""Versioned sourced XY calibration, independent of the live DM runtime.

Only geometry is converted. Stored pixels, intensity semantics, Fourier arrays,
phase units and frame/depth meaning are deliberately outside this module.
"""
import math


class CalibrationError(ValueError):
    code = "INVALID_ARGUMENT"


UNITS = {"m": 1., "mm": 1e-3, "um": 1e-6, "nm": 1e-9, "angstrom": 1e-10}
ALIASES = {"Å": "angstrom", "Å": "angstrom", "Angstrom": "angstrom",
           "µm": "um", "μm": "um"}


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def require(condition, message):
    if not condition:
        raise CalibrationError(message)


def unit_kind(value):
    """Exact recognized unit spellings only; no guessing or encoding repair."""
    if type(value) is not str:
        return None
    if value.startswith("cycles/"):
        value = "1/" + value[7:]
    inverse = value.startswith("1/")
    base = value[2:] if inverse else value
    base = ALIASES.get(base, base)
    return ("reciprocal_space" if inverse else "real_space", base) if base in UNITS else None


def validated_scale(value, coordinate_domain="real_space"):
    require(type(value) is dict and set(value) <= {"x", "y", "unit", "uncertainty_x", "uncertainty_y"},
            "xy_scale requires signed x/y, a supported real-space length unit and optional absolute scale uncertainties")
    require(all(finite(value.get(axis)) and value[axis] != 0 for axis in ("x", "y")),
            "Both XY scales must be explicit finite nonzero signed values; square pixels are never inferred")
    require(coordinate_domain in ("real_space", "reciprocal_space"), "Explicit real-space or reciprocal-space calibration domain required")
    parsed = unit_kind(value.get("unit"))
    require(parsed is not None and parsed[0] == coordinate_domain,
            "XY unit must match the declared real-space length or reciprocal-space inverse-length domain; intensity units are separate")
    unit = ("1/" if coordinate_domain == "reciprocal_space" else "") + parsed[1]
    require(all(math.isfinite(1. / value[axis]) for axis in ("x", "y")), "XY inverse scale exceeds finite binary64")
    result = {"x": float(value["x"]), "y": float(value["y"]), "unit": unit,
              "uncertainty_x": None, "uncertainty_y": None,
              "uncertainty_convention": "absolute scale standard uncertainty when supplied; correlation and localization uncertainty unspecified"}
    for axis in ("x", "y"):
        field = "uncertainty_" + axis
        if field in value:
            require(finite(value[field]) and value[field] >= 0,
                    "Scale uncertainties must be finite nonnegative absolute values; omit for unknown")
            result[field] = float(value[field])
    return result


def revised_reciprocal_origin(previous, scale):
    """A scale-only revision preserves a known pixel DC, not an old unit value.

    Call only after exact image/scope/domain validation. Withdrawal retains the
    recorded centre as evidence but supplies no active physical coordinates.
    No centre is inferred for an input that never had one.
    """
    if not previous or previous.get("coordinate_domain") != "reciprocal_space":
        return {}
    dc = previous.get("dc_index_xy")
    if dc is None:
        return {}
    require(type(dc) is list and len(dc) == 2 and all(finite(v) for v in dc),
            "Saved reciprocal DC must contain two finite pixel coordinates")
    result = {"dc_index_xy": list(dc),
              "origin_inherited_from_calibration_id": previous["calibration_id"],
              "origin_revision_policy": "scale-only correction; unchanged captured pixel DC"}
    if "dc_identity_source" in previous:
        result["dc_identity_source"] = previous["dc_identity_source"]
    for field in ("centre_revision_id", "centre_source"):
        if field in previous:
            result[field] = previous[field]
    if scale is not None:
        zeros = [-value * scale[axis] for value, axis in zip(dc, ("x", "y"))]
        require(all(finite(v) for v in zeros) and
                all(index == 0 or zero != 0 for index, zero in zip(dc, zeros)),
                "Revised physical zero underflows or overflows binary64")
        result["physical_zero_xy"] = zeros
    return result


def revised_centre(previous, centre, ident, source_text):
    """Correct only the reciprocal scalar's declared DC, never its values."""
    require(previous and previous.get("coordinate_domain") == "reciprocal_space",
            "Centre revision requires an established reciprocal scalar domain")
    require(type(centre) is list and len(centre) == 2 and all(finite(v) for v in centre),
            "centre requires two finite original array-index coordinates")
    record = dict(previous)
    record.update(calibration_id=ident, revision=previous["revision"] + 1,
                  previous_calibration_id=previous["calibration_id"],
                  source="user_statement_not_independently_verified", source_text=source_text,
                  dc_index_xy=list(centre), centre_revision_id=ident,
                  centre_source={"source": "user_statement_not_independently_verified", "source_text": source_text,
                                 "previous_dc_index_xy": previous.get("dc_index_xy"),
                                 "previous_calibration_id": previous["calibration_id"]},
                  dc_identity_source="explicit sourced user centre correction; not independently verified",
                  calibration_revision_kind="centre_correction",
                  native_axes_semantics="original captured axes retained as evidence; effective centre is dc_index_xy/physical_zero_xy")
    scale = previous.get("xy_scale") if previous.get("status") == "active" else None
    record.pop("physical_zero_xy", None)
    if scale is not None:
        record.update(revised_reciprocal_origin(record, scale))
        # This is an explicit correction, not inheritance of the old centre.
        record.pop("origin_inherited_from_calibration_id", None)
        record["origin_revision_policy"] = "explicit sourced centre correction; physical zero recomputed with unchanged signed XY scale"
    return record


def active_scale(record):
    return record.get("xy_scale") if type(record) is dict and record.get("status") == "active" and record.get("coordinate_domain", "real_space") == "real_space" else None


def dependency(record):
    return {"calibration_id": record["calibration_id"], "revision": record["revision"],
            "status": record["status"], "source": record.get("source", "user_statement_not_independently_verified"),
            **({"coordinate_domain": record["coordinate_domain"]} if "coordinate_domain" in record else {}),
            **({"centre_revision_id": record["centre_revision_id"]} if "centre_revision_id" in record else {})} if record else None


def native_record(info, provenance, ident, applies_to):
    """Admit geometry only after the caller's complete saved-READ validator.

    Hashes attest internal evidence consistency, not metrological accuracy or
    concurrent/live-source stability. Preserve raw native axes separately.
    """
    admission = {"status": "pixel_only", "source": "native_dm_capture",
                 "reason": "native XY physical calibration is incomplete or unsupported"}
    semantics = info.get("scientific_semantics") or {}
    context = info.get("scientific_context") or {}
    if context.get("status") == "unresolved_lineage":
        admission["reason"] = "unresolved scientific lineage; native units cannot establish the current domain"
        return None, admission
    axes = info.get("working_calibration_xy")
    mathematical = semantics.get("status") == "tracked_fourier"
    if mathematical:
        if semantics.get("coordinate_mode") == "pixel":
            admission["reason"] = "tracked native pixel Fourier coordinates have no physical scale; preserved native units are not mathematical frequency calibration"
            return None, admission
        axes = semantics.get("coordinate_axes")
    if type(axes) is not list or len(axes) != 2:
        return None, admission
    observed, kinds = [], []
    for dim, axis in enumerate(axes):
        if type(axis) is not dict or axis.get("dm_dimension") != dim or axis.get("numpy_axis") != 1-dim:
            return None, admission
        kind = unit_kind(axis.get("unit"))
        step = axis.get("scale")
        zero = axis.get("calibrated_value_at_pixel_zero")
        if kind is None or not finite(step) or step == 0 or not finite(zero) or (not mathematical and axis.get("usable") is not True):
            return None, admission
        kinds.append(kind)
        observed.append({"axis": "x" if dim == 0 else "y", "dm_dimension": dim,
                         "numpy_axis": 1-dim, "size": axis["size"],
                         "raw_origin": None if mathematical else axis.get("origin"),
                         "physical_zero": float(zero), "signed_scale": float(step), "unit": axis["unit"],
                         "coordinate_source": "validated_mathematical_fourier_axis" if mathematical else "fresh_native_READ_axis"})
    if kinds[0][0] != kinds[1][0]:
        admission["reason"] = "X/Y physical domains disagree; no real-space/reciprocal-space mixing"
        return None, admission
    domain = kinds[0][0]
    if mathematical and domain != ("reciprocal_space" if semantics.get("domain") == "frequency" else "real_space"):
        admission["reason"] = "unit domain conflicts with validated mathematical scientific coordinates"
        return None, admission
    history = info.get("native_external_import")
    if not mathematical and type(history) is dict and history.get("coordinate_domain") in ("real_space", "reciprocal_space") and history["coordinate_domain"] != domain:
        admission["reason"] = "current unit domain conflicts with historical external-import domain; creation metadata does not establish the edited current domain"
        return None, admission
    # Convert both signed axes to the first axis's length unit. A reciprocal
    # frequency has the inverse conversion factor; preserve every raw field.
    scales, zeros = [], []
    for row, kind in zip(observed, kinds):
        factor = UNITS[kind[1]] / UNITS[kinds[0][1]]
        if domain == "reciprocal_space":
            factor = 1. / factor
        scale, zero = row["signed_scale"] * factor, row["physical_zero"] * factor
        if (not all(finite(v) for v in (factor, scale, zero)) or scale == 0 or not finite(1. / scale) or
                row["physical_zero"] != 0 and zero == 0):
            admission["reason"] = "native unit conversion exceeds finite nonzero binary64 resolution"
            return None, admission
        row["to_record_unit_factor"] = factor
        scales.append(scale); zeros.append(zero)
    unit = ("1/" if domain == "reciprocal_space" else "") + kinds[0][1]
    scale = validated_scale({"x": scales[0], "y": scales[1], "unit": unit}, domain)
    record = {"calibration_id": ident, "revision": 1, "previous_calibration_id": None,
              "status": "active", "scope": "image", "applies_to": applies_to,
              "xy_scale": scale, "source": "native_dm_capture", "coordinate_domain": domain,
              "source_text": "Native dimension calibration from the exact validated immutable READ capture; no user statement substituted",
              "uncertainty_status": "unknown; native metadata provides no independent calibration uncertainty",
              "real_space_only": domain == "real_space", "original_file_metadata_modified": False,
              "value_unit_or_frame_depth_inferred": False, "native_axes": observed,
              "physical_zero_xy": zeros, "raw_native_calibration": info.get("working_calibration_xy"),
              "native_capture_provenance": provenance,
              "verification_scope": "internally validated saved native READ/array/axis evidence; no metrological or atomic live-source guarantee"}
    if domain == "reciprocal_space":
        dc = [a.get("dc_index_in_roi") if mathematical else a.get("origin") for a in axes]
        if all(finite(v) for v in dc):
            record["dc_index_xy"] = dc
            record["dc_identity_source"] = "validated mathematical Fourier bins" if mathematical else "native raw-index calibration origin; physical-zero getter rounding is preserved separately"
    admission.update(status="active", reason="validated saved native READ with consistent physical XY axes", coordinate_domain=domain)
    return record, admission


def physical_points(points, record):
    if not record or record.get("status") != "active" or "physical_zero_xy" not in record:
        return None
    scale, zero = record["xy_scale"], record["physical_zero_xy"]
    result = []
    for point in points:
        converted = []
        for dim, name in enumerate(("x", "y")):
            component = point[dim] * scale[name]
            require(finite(component) and not (point[dim] != 0 and component == 0),
                    "A nonzero physical point component underflows or overflows binary64; cannot report a false absolute coordinate")
            converted.append(zero[dim] + component)
        result.append(converted)
    require(all(finite(v) for p in result for v in p), "Physical point coordinates exceed finite binary64")
    return result


def geometry(dx, dy, record, frequency=False):
    """Convert mathematical cycles/pixel, never radians, with signed XY axes."""
    require(finite(dx) and finite(dy), "Measurement displacement must be finite")
    reciprocal = bool(record and record.get("status") == "active" and record.get("coordinate_domain") == "reciprocal_space" and not frequency)
    scale = record["xy_scale"] if reciprocal else active_scale(record)
    result = {"calibration_dependency": dependency(record),
              "physical_angle": False, "physical_angle_degrees": None,
              "measurement_uncertainty": None,
              "uncertainty_status": "unknown; localization uncertainty and scale covariance are not supplied"}
    if not scale:
        return {**result, "physical_distance": None, "physical_unit": None,
                "physical_frequency_magnitude": None, "physical_frequency_unit": None,
                "period": None, "period_unit": None,
                "limitation": "No active operational XY calibration; pixel geometry remains available. Legacy image_context.xy_scale is descriptive only."}
    x = dx / scale["x"] if frequency else dx * scale["x"]
    y = dy / scale["y"] if frequency else dy * scale["y"]
    length = math.hypot(x, y)
    require(all(finite(v) for v in (x, y, length)), "Calibrated measurement exceeds finite binary64")
    require(not (dx != 0 and x == 0 or dy != 0 and y == 0),
            "A nonzero calibrated component underflows binary64; cannot report false zero/DC")
    result.update(physical_angle=length != 0,
                  physical_angle_degrees=math.degrees(math.atan2(y, x)) if length else None,
                  physical_vector_xy=[x, y],
                  limitation=("Geometry based on validated saved native metadata; no independent metrological verification or phase identification" if record.get("source") == "native_dm_capture" else
                              "Geometry based on a sourced user statement; no independent calibration verification or phase identification"))
    if frequency or reciprocal:
        period = 1. / length if length else None
        require(period is None or finite(period), "Reciprocal period exceeds finite binary64")
        result.update(physical_distance=None, physical_unit=None,
                      physical_frequency_magnitude=length, physical_frequency_unit="cycles/" + (scale["unit"][2:] if reciprocal else scale["unit"]),
                      period=period, period_unit=scale["unit"][2:] if reciprocal else scale["unit"],
                      zero_frequency_reason="DC has no finite reciprocal period" if not length else None,
                      frequency_convention=("cycles, not radians; original array-index displacement times signed reciprocal calibration; no 2pi" if reciprocal else
                                            "cycles, not radians; fx_physical=fx_cycles_per_pixel/signed_scale_x; analogous y; no 2pi"))
    else:
        result.update(physical_distance=length, physical_unit=scale["unit"])
    return result


def frequency_axes(shape, record):
    scale = active_scale(record)
    if not scale:
        return None
    rows = []
    for dim, (axis, size, spacing) in enumerate(zip(("fy", "fx"), shape, (scale["y"], scale["x"]))):
        step = 1. / size / spacing
        origin = -(size // 2) * step
        require(finite(step) and step != 0 and finite(origin), "Physical frequency axis exceeds finite nonzero binary64 resolution")
        rows.append({"axis": axis, "numpy_axis": dim, "size": int(size), "step": step,
                     "dc_index": int(size // 2), "value_at_index_zero": origin,
                     "unit": "cycles/" + scale["unit"], "calibration_id": record["calibration_id"],
                     "convention": "original fftshift cycles/pixel divided by signed real-space axis scale; no2pi"})
    return rows


def scale_bar_spec(panel, record):
    """A horizontal real-space bar; physical XY aspect never distorts pixels."""
    scale = active_scale(record)
    if not scale or panel.get("domain") != "spatial_pixels":
        return None
    x0, _, x1, _ = panel["source_rect_xyxy"]
    left, top, right, bottom = panel["image_rect_xyxy"]
    if right - left < 72 or bottom - top < 40:
        return {"visible": False, "reason": "display panel too small for a legible physical scale bar",
                "calibration_id": record["calibration_id"]}
    target = (x1 - x0) * abs(scale["x"]) * .25
    require(finite(target) and target > 0, "Scale-bar range exceeds finite binary64")
    base = 10. ** math.floor(math.log10(target))
    length = max(v * base for v in (1, 2, 5, 10) if v * base <= target * (1 + 1e-14))
    length_pixels = length / abs(scale["x"])
    width = length_pixels * (right - left) / (x1 - x0)
    return {"visible": True, "length": length, "unit": scale["unit"], "source_length_pixels": length_pixels,
            "image_endpoints_xyxy": [left + 12, bottom - 13, left + 12 + width, bottom - 13],
            "axis": "x", "signed_scale": scale["x"], "calibration_id": record["calibration_id"],
            "provenance": record.get("source", "user_statement_not_independently_verified"), "display_only": True}
