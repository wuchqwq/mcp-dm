"""Versioned user-stated real-space XY calibration, independent of DM.

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


def validated_scale(value):
    require(type(value) is dict and set(value) <= {"x", "y", "unit", "uncertainty_x", "uncertainty_y"},
            "xy_scale requires signed x/y, a supported real-space length unit and optional absolute scale uncertainties")
    require(all(finite(value.get(axis)) and value[axis] != 0 for axis in ("x", "y")),
            "Both XY scales must be explicit finite nonzero signed values; square pixels are never inferred")
    unit = ALIASES.get(value.get("unit"), value.get("unit")) if type(value.get("unit")) is str else None
    require(unit in UNITS, "Real-space XY unit must be m, mm, um, nm or angstrom (Å accepted); diffraction and intensity units are separate")
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


def active_scale(record):
    return record.get("xy_scale") if type(record) is dict and record.get("status") == "active" else None


def dependency(record):
    return {"calibration_id": record["calibration_id"], "revision": record["revision"],
            "status": record["status"], "source": "user_statement_not_independently_verified"} if record else None


def geometry(dx, dy, record, frequency=False):
    """Convert mathematical cycles/pixel, never radians, with signed XY axes."""
    require(finite(dx) and finite(dy), "Measurement displacement must be finite")
    scale = active_scale(record)
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
                  limitation="Geometry based on a sourced user statement; no independent calibration verification or phase identification")
    if frequency:
        period = 1. / length if length else None
        require(period is None or finite(period), "Reciprocal period exceeds finite binary64")
        result.update(physical_distance=None, physical_unit=None,
                      physical_frequency_magnitude=length, physical_frequency_unit="cycles/" + scale["unit"],
                      period=period, period_unit=scale["unit"],
                      zero_frequency_reason="DC has no finite reciprocal period" if not length else None,
                      frequency_convention="cycles, not radians; fx_physical=fx_cycles_per_pixel/signed_scale_x; analogous y; no 2pi")
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
            "provenance": "user_statement_not_independently_verified", "display_only": True}
