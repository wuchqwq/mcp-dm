"""A narrow, resumable researcher correction recipe over existing saved tools.

Initial single-domain comparison -> scoped observation -> FCC Sigma3 trials.
No new simulator, registration confirmation bypass or general session runtime.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation

from crystallography.analysis_revision import bind_geometry
from crystallography.reflection_compare import assign_within_tolerance, load_measurement
from crystallography.structure_tools import StructureWorkspace, execute as structure_execute
from tools.image_workspace import Workspace, execute as image_execute
from tools.hypothesis_explorer import require, save_json

COINCIDENCE_BOUND = 2e-12  # numerical projection equality, NOT the experimental tolerance
TWIN_LAW_SOURCE = "https://doi.org/10.1107/S1600576715004896"


def read_json(path):
    path = Path(path)
    require(path.stat().st_size <= 8*1024*1024, "Saved recipe/evidence exceeds 8 MiB")
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def saved_structure(path):
    path = Path(path).resolve()
    workspace = StructureWorkspace(str(path.parent.parent.parent))
    value, directory = workspace.object(path.parent.name)
    require(path == directory / "object.json", "Use the original structure manifest path")
    return value, workspace


class RecipeCalls:
    def __init__(self, output, image_workspace, structure_workspace=None):
        self.output = Path(output).resolve()
        self.output.mkdir(parents=True, exist_ok=False)
        (self.output / "calls").mkdir()
        self.image_workspace, self.structure_workspace = str(image_workspace), str(structure_workspace)

    def call(self, provider, action, **args):
        request_id = "feedback-" + uuid.uuid4().hex
        request = {"workspace": self.image_workspace if provider == "image" else self.structure_workspace,
                   "action": action, "request_id": request_id, **args}
        save_json(self.output / "calls" / (request_id + ".json"), request)
        result = (image_execute if provider == "image" else structure_execute)(request)
        require(result.get("ok"), "Existing tool refused: " + json.dumps(result, ensure_ascii=False))
        return result["result"]


def measurements(config, current_id):
    loaded = [load_measurement(path) for path in config["measurement_paths"]]
    require(sum(len(row[2])+len(row[3]) for row in loaded) <= 2*1024*1024, "Measurement evidence exceeds 2 MiB")
    records, sources = [r[0] for r in loaded], [r[1] for r in loaded]
    binding = bind_geometry(records, sources, current_id, "continue_current")
    workspace = Path(sources[0]["journal_path"]).parent.parent
    return records, binding, workspace


def classify_joint(simulations, comparisons, tolerance):
    """Reconcile existing comparison candidate graphs, not independent scores.

    Domain-qualified HKLs stay unchanged. Numerically coincident projections
    share ONE assignment column; each observed peak is counted at most once.
    The existing max-cardinality/min-residual matcher performs joint assignment.
    """
    require(len(simulations) == len(comparisons) == 2, "Exactly two explicit domains are supported")
    observations = comparisons[0]["observations"]
    require(comparisons[1]["observations"] == observations and
            comparisons[0]["registration"]["matrix_xy"] == comparisons[1]["registration"]["matrix_xy"],
            "Both domains must use the same observations and fixed registration")
    members, points, lookup = [], [], {}
    for domain, simulation in zip(("A", "B"), simulations):
        table = simulation["reflections"]
        for index, (point, hkl) in enumerate(zip(table["coordinates_inv_angstrom"], table["hkl"])):
            lookup[(domain, index)] = len(points)
            points.append(point[:2])
            members.append({"domain": domain, "hkl": hkl, "simulation_reflection_index": index,
                            "simulation_object_id": simulation["object_id"], "status": "hypothesized"})
    require(len(points) <= 8192, "Two-domain reflection budget exceeded")
    points = np.asarray(points)
    tree = cKDTree(points)
    require(int(np.sum(tree.query_ball_point(points, COINCIDENCE_BOUND, return_length=True))) <= len(points)+16384,
            "Coincident-projection grouping exceeds bounded resources; nothing truncated")
    parents = list(range(len(points)))

    def find(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i

    for a, b in tree.query_pairs(COINCIDENCE_BOUND):
        parents[find(b)] = find(a)
    grouped = {}
    for index in range(len(points)):
        grouped.setdefault(find(index), []).append(index)
    groups = list(grouped.values())
    for group in groups:
        require(all(np.linalg.norm(points[index]-points[group[0]]) <= COINCIDENCE_BOUND for index in group),
                "Numerical projection grouping forms a non-coincident chain; no tolerance clustering substituted")
    column = {index: j for j, group in enumerate(groups) for index in group}
    distance = np.full((len(observations), len(groups)), 2*tolerance)
    feasible_members = {}
    for domain, comparison in zip(("A", "B"), comparisons):
        for evidence in comparison["ambiguity"]:
            i = evidence["measurement_index"]
            for edge in evidence["candidates"]:
                member = lookup[(domain, edge["simulation_reflection_index"])]
                j = column[member]
                distance[i, j] = min(distance[i, j], edge["residual_inv_angstrom"])
                feasible_members.setdefault((i, j), []).append(member)
    assignment = dict(assign_within_tolerance(distance, tolerance))
    rows, used_members = [], set()
    for i in range(len(observations)):
        assigned = assignment.get(i)
        # Numerical projection equality is not permission to widen a strict
        # experimental tolerance. Only individually feasible domain edges count.
        eligible = feasible_members[(i, assigned)] if assigned is not None else []
        used_members.update(eligible)
        labels = sorted({members[index]["domain"] for index in eligible})
        rows.append({"measurement_index": i, "classification": "shared" if len(labels) == 2 else labels[0] if labels else "unexplained",
                     "members": [members[index] for index in eligible],
                     "residual_inv_angstrom": float(distance[i, assigned]) if assigned is not None else None,
                     "feasible_projection_groups": np.flatnonzero(distance[i] <= tolerance).tolist(),
                     "status": "hypothesized", "assignment_is_unique_proof": False})
    residuals = [row["residual_inv_angstrom"] for row in rows if row["residual_inv_angstrom"] is not None]
    return {"rows": rows, "observations": observations, "matched_count": len(residuals),
            "unexplained_count": len(rows)-len(residuals), "total_residual_inv_angstrom": sum(residuals),
            "rms_residual_inv_angstrom": math.sqrt(sum(x*x for x in residuals)/len(residuals)) if residuals else None,
            "counts": {label: sum(row["classification"] == label for row in rows) for label in ("A", "B", "shared", "unexplained")},
            "coincident_projection_bound_inv_angstrom": COINCIDENCE_BOUND,
            "unassigned_simulated_groups": [[members[i] for i in group if i not in used_members] for group in groups if any(i not in used_members for i in group)],
            "matching": "existing max-cardinality/min-residual assignment over domain-qualified projection groups; no double-counted observed peaks"}


def annotate(calls, current_id, records, classes):
    preview = calls.call("image", "view", object_id=current_id, max_size=768)
    panel = preview["panels"][0]
    colors = {"A": "green", "B": "orange", "shared": "cyan", "unexplained": "amber"}
    # Preserve unrelated researcher marks. Only this recipe's stable peak marks
    # are revised; the entire old annotation object remains immutable.
    prefixes = {"hyp-" + row["object_id"][:20] + suffix for row in records for suffix in ("", "-agent")}
    confirmed = {m["annotation_id"] for m in preview.get("annotations", []) if m.get("status") == "user_confirmed"}
    marks = []
    for mark in preview.get("annotations", []):
        if mark["annotation_id"] not in prefixes or mark["annotation_id"] in confirmed:
            marks.append({**{k: mark[k] for k in ("annotation_id", "kind", "status", "text", "note", "color", "line_width", "arrowhead_size", "arrow_length") if k in mark}, **mark["anchor"]})
    for i, (record, label) in enumerate(zip(records, classes)):
        peak = record["points"][1-record["dc_reference_point_index"]]
        ident = "hyp-" + record["object_id"][:20]
        if ident in confirmed:
            ident += "-agent"
        if ident in confirmed:
            ident += "-" + uuid.uuid4().hex[:8]
        marks.append({"annotation_id": ident, "kind": "point", "status": "hypothesized",
                      "text": "{} {} (hyp.)".format(i+1, label), "color": colors[label], "coordinates": peak,
                      "coordinate_space": record["coordinate_space"], "source_object_id": panel["source_object_id"]})
    return calls.call("image", "annotate", object_id=preview["object_id"], annotations=marks)


def prepare_initial(report_path, output):
    report_path = Path(report_path).resolve()
    report, config = read_json(report_path), read_json(report_path.parent / "input.json")
    require(digest(report_path.parent / "input.json") == report["input_sha256"], "Initial configuration changed")
    best = report["rows"][0]
    comparison, _ = saved_structure(best["comparison_path"])
    require(comparison["kind"] == "compare", "Initial result must be a committed comparison")
    records, binding, image_workspace = measurements(config, config["current_image_object_id"])
    require([r["object_id"] for r in records] == [r["measurement_object_id"] for r in comparison["observations"]], "Initial measurements differ")
    matched = {m["measurement_index"] for m in comparison["matched"]}
    calls = RecipeCalls(output, image_workspace)
    display = annotate(calls, config["current_image_object_id"], records, ["A" if i in matched else "unexplained" for i in range(len(records))])
    stage = {"stage": "single_domain_before_feedback", "initial_report_path": str(report_path), "initial_report_sha256": digest(report_path),
             "comparison_path": best["comparison_path"], "row": best, "image_workspace": str(image_workspace),
             "display_object_id": display["object_id"], "display_manifest_path": display["manifest_path"],
             "analysis_binding": binding, "matched_count": len(matched), "unexplained_count": len(records)-len(matched),
             "source_measurement_hashes": {path: digest(path) for path in config["measurement_paths"]}}
    save_json(calls.output / "initial.json", stage)
    return stage


def primitive(vector):
    rounded = np.rint(3*np.asarray(vector)).astype(int)
    require(np.allclose(rounded/3, vector, rtol=0, atol=2e-12) and np.any(rounded), "Twin direction is not an admitted rational cubic UVW")
    divisor = math.gcd(*rounded.tolist())
    return (rounded//divisor).tolist()


def require_conventional_fcc(atoms):
    cell = np.asarray(atoms["cell_angstrom"])
    a = cell[0, 0]
    require(a > 0 and np.allclose(cell, np.eye(3)*a, atol=1e-10, rtol=0) and all(atoms["pbc"]),
            "This narrow Sigma3 recipe requires a conventional axis-aligned periodic cubic FCC cell")
    occupancy = atoms.get("occupancy")
    require(len(atoms["symbols"]) == 4 and len(set(atoms["symbols"])) == 1 and
            (not occupancy or all(len(row) == 1 and list(row.values()) == [1.] for row in occupancy.values())),
            "This recipe admits only a fully occupied monatomic four-atom FCC model")
    fractions = np.mod(np.asarray(atoms["positions_angstrom"])/a, 1.)
    expected = np.array([[0, 0, 0], [0, .5, .5], [.5, 0, .5], [.5, .5, 0]])
    require(all(any(np.linalg.norm(p-q-np.rint(p-q)) < 1e-10 for q in expected) for p in fractions) and
            len({tuple(np.rint(p*2).astype(int) % 2) for p in fractions}) == 4, "Source motif is not the supported conventional FCC basis")


def revise(initial_path, observation_id, output):
    initial_path = Path(initial_path).resolve()
    initial = read_json(initial_path)
    report_path = Path(initial["initial_report_path"])
    require(digest(report_path) == initial["initial_report_sha256"], "Initial report changed; old results are not overwritten")
    config = read_json(report_path.parent / "input.json")
    require(digest(report_path.parent / "input.json") == read_json(report_path)["input_sha256"], "Initial search configuration changed")
    require(all(digest(path) == value for path, value in initial["source_measurement_hashes"].items()), "Original measurements changed")
    image_workspace = Workspace(initial["image_workspace"], writable=False)
    observation, _ = image_workspace.object(observation_id)
    statement = observation.get("user_context", {}).get("research_observation")
    observation_request = read_json(Path(initial["image_workspace"]) / "requests" / (observation["request_id"] + ".json"))
    require(observation["kind"] == "context" and statement == observation_request["parameters"].get("metadata", {}).get("research_observation") and
            statement is not None and statement["kind"] == "twinning_present", "Use the original committed scoped research observation")
    scope = observation.get("research_observation_scope", {})
    require(scope.get("confirmation_scope") == "twinning_present_only" and
            scope.get("scientific_grid_identity") == initial["analysis_binding"]["scientific_grid_identity"], "Observation belongs to another scientific image/grid")
    records, binding, _ = measurements(config, observation_id)
    row = initial["row"]
    previous, workspace = saved_structure(row["comparison_path"])
    simulation_a, _ = workspace.object(previous["simulation_object_id"])
    orientation_a = simulation_a["orientation"]
    structure_id = simulation_a["structure_object_id"]
    structure, directory = workspace.object(structure_id)
    atoms = read_json(directory / "atoms.json")
    require_conventional_fcc(atoms)
    calls = RecipeCalls(output, initial["image_workspace"], workspace.root)
    common = {"measurement_paths": config["measurement_paths"], "current_image_object_id": observation_id,
              "analysis_mode": "continue_current", "experimental_kind": config["experimental_kind"],
              "registration": previous["parameters"]["registration"], "max_residual_inv_angstrom": config["max_residual_inv_angstrom"]}
    comparison_a = calls.call("structure", "compare", object_id=simulation_a["object_id"], previous_comparison_id=previous["object_id"], **common)
    ref = orientation_a["reference"]["direction_uvw"] or orientation_a["reference"]["cartesian_source_unit"]
    matrix_a = np.asarray(orientation_a["rotation_matrix_cartesian"])
    trials, best = [], None
    for axis in ([1, 1, 1], [1, 1, -1], [1, -1, 1], [1, -1, -1]):
        for angle in (-60., 60.):
            twin = Rotation.from_rotvec(np.asarray(axis)/math.sqrt(3)*math.radians(angle)).as_matrix()
            zone_b, reference_b = primitive(twin.T @ orientation_a["zone_axis_uvw"]), primitive(twin.T @ ref)
            oriented = calls.call("structure", "orient", object_id=structure_id, zone_axis_uvw=zone_b,
                                  in_plane_direction_uvw=reference_b, in_plane_rotation_deg=orientation_a["in_plane_rotation_deg"])
            matrix_error = float(np.max(np.abs(np.asarray(oriented["orientation"]["rotation_matrix_cartesian"])-matrix_a @ twin)))
            require(matrix_error < 2e-12, "Existing orientation tool does not reproduce the proposed twin relation")
            simulation_b = calls.call("structure", "simulate", object_id=structure_id, orientation_id=oriented["object_id"], **config["simulation"])
            comparison_b = calls.call("structure", "compare", object_id=simulation_b["object_id"], **common)
            joint = classify_joint([simulation_a, simulation_b], [comparison_a, comparison_b], config["max_residual_inv_angstrom"])
            trial = {"status": "hypothesized", "twin_axis_uvw": axis, "twin_rotation_deg": angle, "twin_matrix_source_cartesian": twin.tolist(),
                     "zone_b_uvw": zone_b, "reference_b_uvw": reference_b, "orientation_matrix_error": matrix_error,
                     "orientation_b_path": oriented["manifest_path"], "simulation_b_path": simulation_b["manifest_path"],
                     "comparison_b_path": comparison_b["manifest_path"], "joint": joint}
            trials.append(trial)
            if best is None or (-joint["matched_count"], joint["total_residual_inv_angstrom"]) < (-best["joint"]["matched_count"], best["joint"]["total_residual_inv_angstrom"]):
                best = trial
    display = annotate(calls, observation_id, records, [r["classification"] for r in best["joint"]["rows"]])
    result = {"stage": "two_domain_after_scoped_feedback", "status": "hypothesized", "phase_identified": False,
              "initial_stage_path": str(initial_path), "initial_stage_sha256": digest(initial_path), "initial": initial,
              "observation": {"object_id": observation_id, "manifest_path": observation["manifest_path"], "sha256": digest(observation["manifest_path"]), **statement, "scope": scope},
              "confirmation_boundary": "Only twinning presence is caller-confirmed (or synthetic_fixture); twin law, both orientations, domain allocation and every HKL remain hypothesized.",
              "image_workspace": initial["image_workspace"], "analysis_binding": binding,
              "comparison_a_path": comparison_a["manifest_path"], "simulation_a_path": simulation_a["manifest_path"],
              "best": best, "alternatives": trials, "twin_law_source": TWIN_LAW_SOURCE,
              "display_object_id": display["object_id"], "display_manifest_path": display["manifest_path"],
              "fixed_registration": common["registration"], "max_residual_inv_angstrom": config["max_residual_inv_angstrom"],
              "evidence_scope": "All peaks used in search; no independent validation. Two periodic kinematic domains, no atomistic boundary, coherence, double diffraction or dynamical scattering.",
              "next_observation": "Acquire separate local patterns from either side of the proposed boundary: test whether A-only and B-only peaks segregate while shared peaks persist. A superposed pattern and extra fit capacity alone do not prove twinning. Keep the remaining unexplained peaks visible."}
    save_json(calls.output / "revision.json", result)
    from tools.twin_feedback_view import render_revision
    return {"revision_path": str(calls.output / "revision.json"), "display_object_id": display["object_id"], **render_revision(result, calls.output)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    initial = commands.add_parser("initial")
    initial.add_argument("--report", required=True)
    initial.add_argument("--output", required=True)
    revised = commands.add_parser("revise")
    revised.add_argument("--initial", required=True)
    revised.add_argument("--observation", required=True)
    revised.add_argument("--output", required=True)
    args = parser.parse_args()
    require(Path(args.output).is_absolute(), "Use a new absolute output directory")
    if args.command == "initial":
        stage = prepare_initial(args.report, args.output)
        result = {"initial_path": str(Path(args.output).resolve() / "initial.json"), "display_object_id": stage["display_object_id"],
                  "matched_count": stage["matched_count"], "unexplained_count": stage["unexplained_count"]}
    else:
        result = revise(args.initial, args.observation, args.output)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
