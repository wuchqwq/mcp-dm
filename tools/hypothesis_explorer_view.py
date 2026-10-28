"""Static researcher view of already committed hypothesis comparisons.

Rendering reads saved evidence only. It neither matches reflections nor changes
calibration, scientific arrays, orientation records or hypothesis authority.
"""
import base64
import html
import io
import json
from pathlib import Path

import numpy as np


def _text(value):
    return html.escape(str(value), quote=True)


def _number(value, precision=6):
    return "n/a" if value is None else format(value, ".{}g".format(precision))


def _zone(row):
    return "[{}]".format(" ".join(str(v) for v in row["zone_axis_uvw"]))


def _load_comparison(row):
    # Verification belongs to the scientific provider, before this display call.
    with Path(row["comparison_path"]).open(encoding="utf-8") as stream:
        return json.load(stream)


def _experimental_coordinates(comparison, simulation_points):
    """Undo the saved comparison-only transform on a presentation copy."""
    registration = comparison["registration"]
    matrix = np.asarray(registration["matrix_xy"], dtype=float)
    translation = np.asarray(registration["translation_xy_inv_angstrom"], dtype=float)
    points = np.asarray(simulation_points, dtype=float).reshape(-1, 2)
    return (points - translation) @ np.linalg.inv(matrix).T


def _best_candidates(rows):
    selected, seen = [], set()
    for row in rows:
        if row["label"] not in seen:
            selected.append(row)
            seen.add(row["label"])
        if len(selected) == 3:
            break
    return selected


def _figure(report, best_rows, comparisons):
    # Plotting is optional and remains outside the GMS interpreter.
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from matplotlib.lines import Line2D

    figure = Figure(figsize=(5.1 * len(best_rows), 5.8), layout="constrained")
    FigureCanvasAgg(figure)
    axes = figure.subplots(1, len(best_rows), squeeze=False)[0]
    span = 0.0
    for axis, row, comparison in zip(axes, best_rows, comparisons):
        observations = np.asarray([item["q_xy_inv_angstrom"] for item in comparison["observations"]])
        matched_indices = {item["measurement_index"] for item in comparison["matched"]}
        matched_mask = np.asarray([i in matched_indices for i in range(len(observations))])
        if np.any(matched_mask):
            axis.scatter(*observations[matched_mask].T, s=50, facecolors="none", edgecolors="#147d60", linewidths=1.6, zorder=4)
        if np.any(~matched_mask):
            axis.scatter(*observations[~matched_mask].T, s=56, marker="x", c="#c13b32", linewidths=1.6, zorder=4)
        all_simulated = []
        for item in comparison["matched"]:
            predicted = _experimental_coordinates(comparison, [item["simulation_q_xyz_inv_angstrom"][:2]])[0]
            actual = observations[item["measurement_index"]]
            axis.plot([actual[0], predicted[0]], [actual[1], predicted[1]], color="#8e9197", linewidth=.8, zorder=2)
            all_simulated.append(predicted)
        if all_simulated:
            axis.scatter(*np.asarray(all_simulated).T, marker="s", s=21, facecolors="none", edgecolors="#225ab2", linewidths=1.2, zorder=3)
        if comparison["unmatched_simulated"]:
            extras = _experimental_coordinates(comparison, [item["coordinates_inv_angstrom"][:2] for item in comparison["unmatched_simulated"]])
            axis.scatter(*extras.T, marker="+", s=52, c="#7395bf", linewidths=1.2, alpha=.8, zorder=2)
            all_simulated.extend(extras)
        for index, point in enumerate(observations):
            axis.annotate(str(index + 1), point, xytext=(5, 5), textcoords="offset points", fontsize=8, color="#424750")
        axis.scatter([0], [0], s=15, color="#60666f", marker="+", zorder=1)
        axis.axhline(0, color="#e5e7eb", linewidth=.7, zorder=0)
        axis.axvline(0, color="#e5e7eb", linewidth=.7, zorder=0)
        values = np.concatenate((observations, np.asarray(all_simulated).reshape(-1, 2)), axis=0)
        span = max(span, float(np.max(np.abs(values))))
        axis.set_aspect("equal", adjustable="box")
        axis.grid(alpha=.18)
        axis.set_xlabel(r"Measured $q_x$ ($\mathrm{\AA}^{-1}$)")
        axis.set_ylabel(r"Measured $q_y$ ($\mathrm{\AA}^{-1}$)")
        compatible = "compatible" if row["compatible"] else "incomplete match"
        axis.set_title("{} {}\n{}/{} matched; RMS {} Å⁻¹\nHypothesized; {}".format(
            row["label"], _zone(row), row["matched_count"], report["measurement_count"],
            _number(row["rms_residual_inv_angstrom"], 4), compatible), fontsize=10, pad=10)
    for axis in axes:
        axis.set_xlim(-span * 1.18, span * 1.18)
        axis.set_ylim(-span * 1.18, span * 1.18)
    handles = [
        Line2D([], [], marker="o", markerfacecolor="none", markeredgecolor="#147d60", linestyle="none", label="Matched measured reflection"),
        Line2D([], [], marker="x", color="#c13b32", linestyle="none", label="Unmatched measured reflection"),
        Line2D([], [], marker="s", markerfacecolor="none", markeredgecolor="#225ab2", linestyle="none", label="Assigned simulation"),
        Line2D([], [], marker="+", color="#7395bf", linestyle="none", label="Unassigned simulation"),
    ]
    figure.legend(handles=handles, loc="outside lower center", ncols=2, frameon=False, fontsize=9)
    figure.suptitle("Reflection hypotheses — geometric comparison only\nOriginal measured coordinates; numbered peaks; q_y plotted upward", fontsize=13)
    image = io.BytesIO()
    figure.savefig(image, format="png", dpi=150)
    return image.getvalue()


def _evidence_details(row, comparison):
    matches = []
    for item in comparison["matched"]:
        matches.append("<tr><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            item["measurement_index"] + 1, _text(item["hkl"]),
            _number(item["position_residual_inv_angstrom"])))
    unmeasured = [item["measurement_index"] + 1 for item in comparison["unmatched_experimental"]]
    unassigned = [item["hkl"] for item in comparison["unmatched_simulated"]]
    angles = row.get("compatible_rotations_deg", [])
    return ("<details><summary>{} {}: assignments and unmatches</summary>"
            "<p>All assignments remain hypothesized. Rotations satisfying all measurements: {}.</p>"
            "<table><thead><tr><th>Measured peak</th><th>Proposed HKL</th><th>Residual (Å⁻¹)</th></tr></thead>"
            "<tbody>{}</tbody></table><p>Unmatched measured peak numbers: {}.</p>"
            "<p>Unassigned simulated HKLs: {}.</p></details>").format(
                _text(row["label"]), _text(_zone(row)), _text(angles or "none"),
                "".join(matches), _text(unmeasured or "none"), _text(unassigned or "none"))


def render_report(report, output_dir):
    """Write exclusive PNG/standalone HTML views; return their absolute paths."""
    output_dir = Path(output_dir).resolve()
    if not output_dir.is_dir():
        raise ValueError("A pre-created output directory is required")
    rows = report["rows"]
    if not rows:
        raise ValueError("At least one completed hypothesis comparison is required")
    comparisons = [_load_comparison(row) for row in rows]
    best_rows = _best_candidates(rows)
    best_comparisons = [comparisons[rows.index(row)] for row in best_rows]
    png = _figure(report, best_rows, best_comparisons)
    image_path, index_path = output_dir / "overlay.png", output_dir / "index.html"
    if image_path.exists() or index_path.exists():
        raise FileExistsError("Researcher views already exist; use a fresh output directory")
    with image_path.open("xb") as stream:
        stream.write(png)

    table_rows = []
    for row in rows:
        table_rows.append("<tr><td>{}</td><td>{}</td><td>hypothesized</td><td>{}</td><td>{}/{}</td>"
                          "<td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            _text(row["label"]), _text(_zone(row)), _number(row["rotation_deg"]),
            row["matched_count"], report["measurement_count"], row["unmatched_experimental_count"],
            row["unmatched_simulated_count"], _number(row["rms_residual_inv_angstrom"]),
            "compatible" if row["compatible"] else "incomplete match"))
    first_observations = comparisons[0]["observations"]
    observation_rows = "".join("<tr><td>{}</td><td>{}</td><td>{}</td></tr>".format(
        index + 1, _number(item["q_xy_inv_angstrom"][0], 9), _number(item["q_xy_inv_angstrom"][1], 9))
        for index, item in enumerate(first_observations))
    screen = report["screen_axes"]
    next_observation = report.get("next_observation", {})
    limits = list(report.get("limits", []))
    limits.extend([
        "Ranking is descriptive: the smallest residual is not a unique phase or HKL proof.",
        "Unassigned simulated spots do not establish absent experimental reflections without a visibility/detection model.",
        "Kinematic intensities are not matched to SAED counts or HRTEM/ptychography FFT contrast.",
        "The plot uses original measured reciprocal coordinates, with q_y upward; source arrays and their row convention are unchanged.",
    ])
    document = """<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Hypothesis Explorer — reflection comparison</title>
<style>
body{{font:16px/1.55 system-ui,sans-serif;max-width:1240px;margin:32px auto;padding:0 24px;color:#202932;background:#fafbfc}}
h1,h2{{line-height:1.2}} h1{{margin-bottom:8px}} h2{{font-size:1.25rem;margin-top:30px}}
table{{border-collapse:collapse;width:100%;font-size:14px;background:white}} th,td{{border:1px solid #d9dee5;padding:8px 10px;text-align:left;vertical-align:top}}
th{{background:#eef2f7}} img{{width:100%;height:auto;background:white;border:1px solid #e0e4e9}}
.notice{{padding:14px 18px;background:#fff5d7;border-left:4px solid #c18b17}} .next{{padding:16px 18px;background:#e9f3ef;border-left:4px solid #338468}}
.scroll{{overflow-x:auto}} .muted{{color:#526170}} details{{margin:12px 0;padding:10px 14px;background:white;border:1px solid #d9dee5}} summary{{cursor:pointer;font-weight:600}}
li{{margin:6px 0}} code{{overflow-wrap:anywhere}}
</style>
<h1>Hypothesis Explorer</h1><p class="muted">Bounded orientation and reflection exploration · all explanations hypothesized</p>
<p class="notice">{} No unique phase is established. Every candidate and rotation was selected using the search measurements.</p>
<h2>Measured and simulated reflections</h2><img src="data:image/png;base64,{}" alt="Candidate overlays in original measured reciprocal coordinates, with matched and unmatched reflections">
<p class="muted">One best tested orientation per candidate is plotted. Numbered peaks refer to the measurement table below. All coordinates are cycles/Å, without 2π.</p>
<h2>Candidate comparison</h2><p>Fixed residual tolerance: <strong>{} Å⁻¹</strong>. Experimental scale = 1; translation = [0, 0]. Declared screen parity flip_y = <strong>{}</strong>. {}</p>
<p>Rows retain every tested zone. Angles transform measured vectors into the simulation frame; they are not an independently measured crystal roll.</p>
<div class="scroll"><table><thead><tr><th>Candidate</th><th>Zone axis</th><th>Authority</th><th>Trial angle (°)</th><th>Matched</th><th>Unmatched measured</th><th>Unassigned simulated</th><th>Matched RMS (Å⁻¹)</th><th>Geometry</th></tr></thead><tbody>{}</tbody></table></div>
<h2>Next observation</h2><div class="next">{}</div>
<h2>Measured reflections</h2><p>These are search inputs. There is no independent held-out validation in this run.</p>
<table><thead><tr><th>Peak number</th><th>q_x (Å⁻¹)</th><th>q_y (Å⁻¹)</th></tr></thead><tbody>{}</tbody></table>
<h2>Proposed correspondences and unmatched reflections</h2>{}
<h2>Scientific limits</h2><ul>{}</ul>
</html>""".format(
        _text(report.get("evidence_scope", "All measurements participated in the hypothesis search.")),
        base64.b64encode(png).decode("ascii"), _number(report["max_residual_inv_angstrom"], 9),
        _text(screen["flip_y"]), _text(screen["basis"]), "".join(table_rows),
        _text(next_observation.get("text", "No discriminating next observation was calculated.")),
        observation_rows, "".join(_evidence_details(row, comparison) for row, comparison in zip(rows, comparisons)),
        "".join("<li>{}</li>".format(_text(limit)) for limit in limits))
    with index_path.open("x", encoding="utf-8") as stream:
        stream.write(document)
    return {"image_path": str(image_path), "index_path": str(index_path)}
