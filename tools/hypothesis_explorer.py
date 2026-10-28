"""Bounded Agent-side batch recipe over existing structure/image evidence tools.

Run in the independent requirements-structure-tools.txt environment, never GMS.
This is an explicit CLI, not a new provider, scientific kernel or phase classifier.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np

from crystallography.analysis_revision import bind_geometry
from crystallography.reflection_compare import compare, load_measurement, measurement_vector
from crystallography.structure_tools import execute, strict_json

MAX_ROTATIONS = 256
MAX_ORIENTATIONS = 24


def require(condition, message):
    if not condition:
        raise ValueError(message)


def save_json(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def validate_config(config):
    required = {"measurement_paths", "current_image_object_id", "experimental_kind",
                "screen_axes", "max_residual_inv_angstrom", "rotation_range_deg",
                "simulation", "candidates"}
    require(type(config) is dict and required <= set(config) and
            set(config) <= required | {"followup_radius_inv_angstrom"}, "Unknown or missing configuration fields")
    paths = config["measurement_paths"]
    require(type(paths) is list and 1 <= len(paths) <= 32 and
            all(type(p) is str and Path(p).is_absolute() for p in paths), "Supply 1..32 absolute committed measurement paths")
    require(config["experimental_kind"] in ("saed", "other_diffraction", "real_space_fft"), "Declare the experiment formation kind")
    axes = config["screen_axes"]
    require(type(axes) is dict and set(axes) == {"flip_y", "basis"} and type(axes["flip_y"]) is bool and
            type(axes["basis"]) is str and 1 <= len(axes["basis"].strip()) <= 500, "Screen parity needs an explicit fixed source basis")
    tolerance = config["max_residual_inv_angstrom"]
    require(finite(tolerance) and 1e-12 <= tolerance <= 1, "Declare a fixed reciprocal residual tolerance")
    bounds = config["rotation_range_deg"]
    require(type(bounds) is list and len(bounds) == 2 and all(finite(v) for v in bounds) and
            -180 <= bounds[0] < bounds[1] <= 180, "Use a bounded rotation interval inside [-180,180], upper exclusive")
    candidates = config["candidates"]
    require(type(candidates) is list and 1 <= len(candidates) <= 3, "Explore 1..3 explicit candidate structures")
    labels, count = set(), 0
    for candidate in candidates:
        require(type(candidate) is dict and set(candidate) == {"label", "source_path", "zone_axes"}, "Each candidate needs label, source_path, zone_axes")
        label = candidate["label"]
        require(type(label) is str and 1 <= len(label.strip()) <= 100 and label not in labels, "Candidate labels must be distinct short strings")
        labels.add(label)
        require(type(candidate["source_path"]) is str and Path(candidate["source_path"]).is_absolute(), "Candidate source paths must be absolute")
        zones = candidate["zone_axes"]
        require(type(zones) is list and 1 <= len(zones) <= 12, "Specify 1..12 low-index zones per candidate")
        for zone in zones:
            require(type(zone) is list and len(zone) == 3 and all(type(v) is int and abs(v) <= 3 for v in zone) and
                    any(zone) and math.gcd(*zone) == 1, "Zones must be nonzero primitive three-index UVW with |index|<=3")
        require(len({tuple(z) for z in zones}) == len(zones), "Duplicate zones are not extra evidence")
        count += len(zones)
    require(count <= MAX_ORIENTATIONS, "At most 24 candidate/zone combinations per run")
    simulation = config["simulation"]
    fields = {"voltage_kv", "reciprocal_radius_inv_angstrom", "max_excitation_error_inv_angstrom",
              "size", "sigma_pixels", "with_direct_beam"}
    require(type(simulation) is dict and set(simulation) == fields, "Supply explicit simulation conditions and raster parameters")
    for name, lo, hi in (("voltage_kv", 20, 400), ("reciprocal_radius_inv_angstrom", .05, 2),
                         ("max_excitation_error_inv_angstrom", 1e-5, .2), ("sigma_pixels", .2, 8)):
        require(finite(simulation[name]) and lo <= simulation[name] <= hi, "Out of bounded simulation range: " + name)
    require(type(simulation["size"]) is int and 64 <= simulation["size"] <= 256 and
            simulation["with_direct_beam"] is False, "Use a 64..256 qualitative raster without the direct beam")
    followup = config.get("followup_radius_inv_angstrom")
    require(followup is None or finite(followup) and simulation["reciprocal_radius_inv_angstrom"] < followup <= 2,
            "Optional followup radius must exceed the search radius and be <=2 cycles/angstrom")


def transform(angle, axes):
    return {"rotation_deg": angle, "scale": 1., "translation_inv_angstrom": [0., 0.],
            "flip_y": axes["flip_y"], "basis": "hypothesized polar-angle trial; " + axes["basis"]}


def propose_rotations(q, vectors, tolerance, bounds):
    """Only polar differences of radially feasible pairs, plus interval start.

    Does not estimate scale, mirror, translation or a 3D orientation. This finite
    proposal set is deliberately not a complete continuous angular optimization.
    """
    angles = {float(bounds[0])}
    for measured in q:
        for predicted in vectors:
            if abs(math.hypot(*measured) - math.hypot(*predicted)) <= tolerance:
                angle = math.degrees(math.atan2(predicted[1], predicted[0]) - math.atan2(measured[1], measured[0]))
                angle = (angle + 180.) % 360. - 180.
                if bounds[0] <= angle < bounds[1]:
                    angles.add(angle)
                    require(len(angles) <= MAX_ROTATIONS, "More than 256 rotation proposals; narrow the zone/peak set or fixed angle interval; nothing truncated")
    return sorted(angles)


def metrics(comparison):
    residuals = [m["position_residual_inv_angstrom"] for m in comparison["matched"]]
    return {"matched_count": len(residuals), "unmatched_experimental_count": len(comparison["unmatched_experimental"]),
            "unmatched_simulated_count": len(comparison["unmatched_simulated"]),
            "rms_residual_inv_angstrom": math.sqrt(sum(v*v for v in residuals)/len(residuals)) if residuals else None,
            "total_residual_inv_angstrom": sum(residuals),
            "compatible": comparison["all_experimental_reflections_matched_within_tolerance"]}


def rank(row):
    return (-row["matched_count"], row["total_residual_inv_angstrom"])


def experimental_predictions(simulation, comparison):
    matrix = np.asarray(comparison["registration"]["matrix_xy"])
    # q_sim = M q_exp; M is orthogonal (proper rotation plus fixed parity).
    return np.asarray(simulation["reflections"]["coordinates_inv_angstrom"])[:, :2] @ matrix


def neighborhood_inside_cutoff(projected_radius, separation, simulation):
    """Certify XY neighbors cannot be lost at the full-3D sphere boundary.

    Pinned diffsims (zero precession) admits |z_Ewald(r)-g_z|<excitation.
    Thus all admitted reflections at XY radius <=r have 3D length bounded
    by hypot(r, z_Ewald(r)+excitation). Use the library's wavelength.
    """
    from diffsims.utils.sim_utils import get_electron_wavelength
    parameters = simulation["parameters"]
    ewald_radius = 1./get_electron_wavelength(parameters["voltage_kv"])
    r = projected_radius + separation
    if r >= ewald_radius:
        return False
    sagitta = r*r/(ewald_radius + math.sqrt(ewald_radius*ewald_radius-r*r))
    bound = math.hypot(r, sagitta + parameters["max_excitation_error_inv_angstrom"])
    return bound < parameters["reciprocal_radius_inv_angstrom"]


def next_observation(hypotheses, observations, tolerance, search_radius):
    """Maximin position disagreement outside the already searched radial range.

    This is a prospective geometric observation, never evidence of an absence,
    a visibility/intensity guarantee or an independently validated reflection.
    """
    if len({item[0]["label"] for item in hypotheses}) < 2:
        return {"status": "needs_more_evidence", "text": "No cross-structure outer-position comparison was calculated. Acquire a new calibrated reflection or a controlled tilt; this bounded search is not phase proof."}
    if sum(len(item[1]["reflections"]["hkl"]) for item in hypotheses) > 262144:
        return {"status": "followup_budget_exceeded", "text": "All search alternatives remain saved. Their expanded prediction tables exceed the 262144-point recommendation budget; narrow the explicit next-observation question."}
    from scipy.spatial import cKDTree
    # Trees include every retained zone/rotation for each other structure. This
    # avoids quadratic reflection/alternative scans and picking a favorable roll.
    models = {}
    for row, simulation, comparison in hypotheses:
        points = experimental_predictions(simulation, comparison)
        model = models.setdefault(row["label"], {"points": [], "sources": []})
        model["points"].extend(points)
        model["sources"].extend([{"zone_axis_uvw": row["zone_axis_uvw"], "rotation_deg": row["rotation_deg"]}] * len(points))
    for model in models.values():
        model["points"] = np.asarray(model["points"])
        model["tree"] = cKDTree(model["points"])
    scopes = {tuple(item[1]["parameters"][key] for key in
                    ("voltage_kv", "max_excitation_error_inv_angstrom", "reciprocal_radius_inv_angstrom")): item[1]
              for item in hypotheses}
    choices = []
    for row, simulation, comparison in hypotheses:
        predicted = experimental_predictions(simulation, comparison)
        distances = {label: model["tree"].query(predicted) for label, model in models.items() if label != row["label"]}
        for j, point in enumerate(predicted):
            if math.hypot(*point) <= search_radius + tolerance:
                continue
            if np.min(np.linalg.norm(observations-point, axis=1)) <= tolerance:
                continue
            nearest = []
            for label, (distance, index) in distances.items():
                model, match = models[label], int(index[j])
                nearest.append({"label": label, **model["sources"][match],
                                "q_xy_inv_angstrom": model["points"][match].tolist(),
                                "separation_inv_angstrom": float(distance[j])})
            separation = min(v["separation_inv_angstrom"] for v in nearest)
            if not all(neighborhood_inside_cutoff(math.hypot(*point), separation, scope) for scope in scopes.values()):
                continue
            choices.append((separation, row, simulation, j, point, nearest))
    if not choices:
        return {"status": "no_new_separated_position", "text": "No unmeasured outer reflection was proposed. Acquire a controlled tilt or independent composition measurement; the present geometry remains ambiguous."}
    separation, row, simulation, j, point, nearest = max(choices, key=lambda item: item[0])
    distinguishable = separation > 2*tolerance
    return {"status": "prospective_position" if distinguishable else "insufficient_current_precision",
            "prediction_scope": "saved kinematic reflections; every retained competing structure/zone/rotation; XY neighborhood certified inside full-3D cutoff",
            "target_label": row["label"], "target_zone_axis_uvw": row["zone_axis_uvw"],
            "target_rotation_deg": row["rotation_deg"],
            "target_hkl": simulation["reflections"]["hkl"][j], "status_of_hkl": "hypothesized",
            "target_q_xy_inv_angstrom": point.tolist(), "nearest_alternatives": nearest,
            "model_separation_inv_angstrom": separation, "required_error_bound_inv_angstrom": separation/2,
            "text": ("Observe a NEW outer reflection near q=({:.6f}, {:.6f}) cycles/angstrom, predicted as {} {}. "
                     "The nearest retained alternative differs by {:.6g} cycles/angstrom. "
                     "A combined position/calibration/model error bound below {:.6g} per prediction is required for disjoint tolerance disks. "
                     "{} This is a prospective geometric target, not held-out validation or guaranteed spot visibility; absence alone does not reject a model.").format(
                         point[0], point[1], row["label"], simulation["reflections"]["hkl"][j], separation, separation/2,
                         "The current tolerance can separate these predictions." if distinguishable else
                         "The current tolerance cannot separate them; improve metrology or use a controlled tilt/independent composition observation.")}


class Calls:
    def __init__(self, output):
        self.output = output
        (output / "calls").mkdir()

    def __call__(self, action, **parameters):
        request_id = "explore-" + uuid.uuid4().hex
        request = {"workspace": str(self.output / "structure"), "action": action,
                   "request_id": request_id, **parameters}
        save_json(self.output / "calls" / (request_id + ".json"), request)
        response = execute(request)
        require(response.get("ok"), "Existing structure tool refused: " + json.dumps(response, ensure_ascii=False))
        return response["result"]


def run(config, output_dir):
    validate_config(config)
    output = Path(output_dir)
    require(output.is_absolute(), "Output must be an absolute NEW directory")
    require(not output.exists(), "Output already exists; preserve it and query saved requests rather than overwrite/replay")
    records, sources, evidence_bytes = [], [], 0
    for path in config["measurement_paths"]:
        row, source, manifest_raw, journal_raw = load_measurement(path)
        evidence_bytes += len(manifest_raw) + len(journal_raw)
        require(evidence_bytes <= 2*1024*1024, "Committed measurement evidence exceeds 2 MiB")
        records.append(row)
        sources.append(source)
    binding = bind_geometry(records, sources, config["current_image_object_id"], "continue_current")
    q = np.asarray([measurement_vector(row)["q_xy_inv_angstrom"] for row in records])
    parity_q = q * [1, -1 if config["screen_axes"]["flip_y"] else 1]
    output.mkdir(parents=True, exist_ok=False)
    save_json(output / "input.json", config)
    calls = Calls(output)
    tolerance = config["max_residual_inv_angstrom"]
    rows, saved_hypotheses = [], []
    for candidate in config["candidates"]:
        opened = calls("open", source_path=candidate["source_path"])
        for zone in candidate["zone_axes"]:
            orientation = calls("orient", object_id=opened["object_id"], zone_axis_uvw=zone)
            simulation = calls("simulate", object_id=opened["object_id"], orientation_id=orientation["object_id"], **config["simulation"])
            vectors = np.asarray(simulation["reflections"]["coordinates_inv_angstrom"])[:, :2]
            trials, best = [], None
            for angle in propose_rotations(parity_q, vectors, tolerance, config["rotation_range_deg"]):
                comparison = compare(records, simulation, transform(angle, config["screen_axes"]), tolerance, config["experimental_kind"])
                trial = {"rotation_deg": angle, "status": "hypothesized", **metrics(comparison),
                         "correspondences": [{"measurement_index": m["measurement_index"], "hkl": m["hkl"], "status": "hypothesized"} for m in comparison["matched"]]}
                trials.append(trial)
                if best is None or rank(trial) < rank(best):
                    best = trial
            # Trial scoring calls the SAME comparison helper; the selected full
            # evidence is committed through structure_compare and revalidated.
            comparison = calls("compare", object_id=simulation["object_id"], measurement_paths=config["measurement_paths"],
                               current_image_object_id=config["current_image_object_id"], analysis_mode="continue_current",
                               experimental_kind=config["experimental_kind"], registration=transform(best["rotation_deg"], config["screen_axes"]),
                               max_residual_inv_angstrom=tolerance)
            row = {"label": candidate["label"], "zone_axis_uvw": zone, "status": "hypothesized",
                   "rotation_deg": best["rotation_deg"], **metrics(comparison),
                   "compatible_rotations_deg": [t["rotation_deg"] for t in trials if t["compatible"]],
                   "structure_path": opened["manifest_path"], "orientation_path": orientation["manifest_path"],
                   "simulation_path": simulation["manifest_path"], "comparison_path": comparison["manifest_path"],
                   "rotation_trials": trials, "basis": "explicit low-index UVW plus polar-angle proposals from the search measurements"}
            rows.append(row)
            saved_hypotheses.append((row, opened, orientation, simulation, comparison))
    rows.sort(key=rank)
    followup = []
    if config.get("followup_radius_inv_angstrom"):
        # Retain ALL fully compatible zone and symmetry-rotation alternatives,
        # not only the nominal residual winner, for the prospective target.
        for row, opened, orientation, simulation, comparison in saved_hypotheses:
            if not row["compatible"]:
                continue
            expanded = calls("simulate", object_id=opened["object_id"], orientation_id=orientation["object_id"],
                             **{**config["simulation"], "reciprocal_radius_inv_angstrom": config["followup_radius_inv_angstrom"]})
            row["followup_simulation_path"] = expanded["manifest_path"]
            for angle in row["compatible_rotations_deg"]:
                trial_comparison = {"registration": {"matrix_xy": np.asarray(compare(records, simulation, transform(angle, config["screen_axes"]), tolerance,
                                                                                     config["experimental_kind"])["registration"]["matrix_xy"]).tolist()}}
                followup.append(({**row, "rotation_deg": angle}, expanded, trial_comparison))
    limits = ["Every structure, UVW, rotation and HKL assignment is hypothesized; no researcher confirmation is asserted.",
              "All supplied points participated in rotation/HKL/candidate search: independent validation NOT_TESTED.",
              "Rank maximizes matched observations then minimizes total residual; it is not probability or unique phase identification.",
              "Unmatched simulated reflections are not evidence of experimental absence or detectability.",
              "Kinematic intensities are retained by the existing tools, never compared to FFT/SAED counts.",
              "Only explicit zones and finite polar-angle proposals were searched; continuous rotation/global orientation search is incomplete.",
              "Scale=1, translation=0, fixed supplied parity; no lattice/strain/centre/scale optimization."]
    report = {"schema_version": 1, "status": "hypothesized", "measurement_count": len(records), "rows": rows,
              "max_residual_inv_angstrom": tolerance, "screen_axes": config["screen_axes"], "simulation": config["simulation"],
              "rotation_range_deg": config["rotation_range_deg"], "measurement_sources": sources, "analysis_binding": binding,
              "input_sha256": hashlib.sha256((output / "input.json").read_bytes()).hexdigest(),
              "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "evidence_scope": "all measurements used in search; no independent validation", "phase_identified": False,
              "limits": limits, "next_observation": next_observation(followup, q, tolerance, config["simulation"]["reciprocal_radius_inv_angstrom"])}
    save_json(output / "report.json", report)
    from tools.hypothesis_explorer_view import render_report
    return {"report_path": str(output / "report.json"), **render_report(report, output)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    require(args.config.stat().st_size <= 64*1024, "Configuration exceeds 64 KiB")
    result = run(strict_json(args.config.read_text(encoding="utf-8")), args.output)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
