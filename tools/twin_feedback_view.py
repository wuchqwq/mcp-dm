"""Static before/after views of already saved scoped twin-feedback evidence.

This module only reads results. It does not match peaks, infer authority,
modify arrays or calibration, or replace the existing interactive Image Panel.
"""
import base64
import html
import io
import json
from pathlib import Path

import numpy as np


COLORS = {"A": "#147d60", "B": "#d5801d", "shared": "#1495ad", "unexplained": "#c13b32"}


def text(value):
    return html.escape(str(value), quote=True)


def number(value):
    return "n/a" if value is None else format(value, ".7g")


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def back_transform(simulation, comparison):
    registration = comparison["registration"]
    matrix = np.asarray(registration["matrix_xy"])
    translation = np.asarray(registration["translation_xy_inv_angstrom"])
    points = np.asarray(simulation["reflections"]["coordinates_inv_angstrom"])[:, :2]
    return (points-translation) @ np.linalg.inv(matrix).T


def draw(result, initial_comparison, comparison_a, simulation_a, simulation_b):
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from matplotlib.lines import Line2D

    joint = result["best"]["joint"]
    observations = np.asarray([row["q_xy_inv_angstrom"] for row in joint["observations"]])
    predictions_a = back_transform(simulation_a, comparison_a)
    predictions_b = back_transform(simulation_b, comparison_a)
    classified = {row["measurement_index"]: row["classification"] for row in joint["rows"]}
    initial_matched = {row["measurement_index"] for row in initial_comparison["matched"]}
    figure = Figure(figsize=(12., 7.5))
    FigureCanvasAgg(figure)
    axes = figure.subplots(1, 2)
    figure.subplots_adjust(left=.08, right=.98, top=.82, bottom=.2, wspace=.2)
    span = float(np.max(np.abs(np.concatenate((observations, predictions_a, predictions_b))))) * 1.2
    for index, axis in enumerate(axes):
        labels = ["A" if i in initial_matched else "unexplained" for i in range(len(observations))] if index == 0 else [classified[i] for i in range(len(observations))]
        for category, color in COLORS.items():
            indices = [i for i, label in enumerate(labels) if label == category]
            if indices:
                points = observations[indices]
                axis.scatter(*points.T, s=62, marker="x" if category == "unexplained" else "o",
                             c=color, linewidths=1.5, zorder=4,
                             edgecolors="none" if category != "unexplained" else None)
        axis.scatter(*predictions_a.T, marker="s", s=110, facecolors="none", edgecolors="#315c99", linewidths=1.1, zorder=3)
        if index == 1:
            axis.scatter(*predictions_b.T, marker="^", s=125, facecolors="none", edgecolors="#d5801d", linewidths=1.1, zorder=3)
        for i, point in enumerate(observations):
            axis.annotate(str(i+1), point, xytext=(6, 5), textcoords="offset points", fontsize=8, color="#404854")
        axis.scatter([0], [0], marker="+", s=22, c="#687282", zorder=1)
        axis.axhline(0, color="#dfe4eb", linewidth=.7, zorder=0)
        axis.axvline(0, color="#dfe4eb", linewidth=.7, zorder=0)
        axis.set_aspect("equal", adjustable="box")
        axis.set_xlim(-span, span)
        axis.set_ylim(-span, span)
        axis.grid(alpha=.18)
        axis.set_xlabel(r"Original measured $q_x$ ($\mathrm{\AA}^{-1}$)")
        axis.set_ylabel(r"Original measured $q_y$ ($\mathrm{\AA}^{-1}$)")
    axes[0].set_title("Before: single-domain hypothesis\n{}/{} matched; {} unexplained".format(
        len(initial_matched), len(observations), len(observations)-len(initial_matched)), fontsize=11, pad=10)
    counts = joint["counts"]
    axes[1].set_title("After scoped feedback: two-domain hypothesis\n{}/{} matched; A={} B={} shared={} unexplained={}".format(
        joint["matched_count"], len(observations), counts["A"], counts["B"], counts["shared"], counts["unexplained"]), fontsize=11, pad=10)
    handles = [Line2D([], [], marker="o" if label != "unexplained" else "x", linestyle="none", color=color,
                      label={"A": "Measured: proposed A", "B": "Measured: proposed B", "shared": "Measured: shared projection", "unexplained": "Measured: still unexplained"}[label])
               for label, color in COLORS.items()]
    handles.extend([Line2D([], [], marker="s", markerfacecolor="none", markeredgecolor="#315c99", linestyle="none", label="Simulated A"),
                    Line2D([], [], marker="^", markerfacecolor="none", markeredgecolor="#d5801d", linestyle="none", label="Simulated B")])
    figure.legend(handles=handles, loc="lower center", bbox_to_anchor=(.5, .02), ncols=3, frameon=False, fontsize=9)
    figure.suptitle("Scoped feedback changes the explanation; all orientations and HKLs remain hypotheses\nSame measured points and fixed calibration; q_y plotted upward", fontsize=12, y=.985)
    memory = io.BytesIO()
    figure.savefig(memory, format="png", dpi=150)
    return memory.getvalue()


def evidence_link(path, label):
    return '<a href="{}">{}</a>'.format(text(Path(path).resolve().as_uri()), text(label))


def render_revision(result, output_dir):
    """Write an exclusive PNG and self-contained HTML; return absolute paths."""
    output_dir = Path(output_dir).resolve()
    if not output_dir.is_dir():
        raise ValueError("Use the already-created revision directory")
    index_path, image_path = output_dir / "index.html", output_dir / "before-after.png"
    if index_path.exists() or image_path.exists():
        raise FileExistsError("Before/after views already exist; preserve the saved revision")
    initial = result["initial"]
    initial_comparison = load(initial["comparison_path"])
    comparison_a = load(result["comparison_a_path"])
    simulation_a = load(result["simulation_a_path"])
    simulation_b = load(result["best"]["simulation_b_path"])
    png = draw(result, initial_comparison, comparison_a, simulation_a, simulation_b)
    joint = result["best"]["joint"]
    observation = result["observation"]
    authority = observation["authority"]
    authority_notice = ("synthetic_fixture — NOT human confirmation. This is an explicitly simulated researcher correction."
                        if authority == "synthetic_fixture" else
                        "user_confirmed — caller-reported researcher statement; not independently authenticated scientific proof.")
    trial_rows = []
    for trial in result["alternatives"]:
        value = trial["joint"]
        trial_rows.append("<tr><td>{}</td><td>{}</td><td>{}</td><td>hypothesized</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            text(trial["twin_axis_uvw"]), number(trial["twin_rotation_deg"]), text(trial["zone_b_uvw"]),
            value["matched_count"], value["unexplained_count"], number(value["rms_residual_inv_angstrom"])))
    per_peak, unexplained = [], []
    for row in joint["rows"]:
        i = row["measurement_index"]
        q = joint["observations"][i]["q_xy_inv_angstrom"]
        members = "; ".join("{}: {}".format(member["domain"], member["hkl"]) for member in row["members"])
        per_peak.append("<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>hypothesized</td></tr>".format(
            i+1, number(q[0]), number(q[1]), text(row["classification"]), text(members or "none"), number(row["residual_inv_angstrom"])))
        if row["classification"] == "unexplained":
            unexplained.append(i+1)
    unassigned_rows = []
    for group in joint["unassigned_simulated_groups"]:
        unassigned_rows.append("<li>{}</li>".format(text("; ".join("{}: {}".format(member["domain"], member["hkl"]) for member in group))))
    fixed = result["fixed_registration"]
    best = result["best"]
    document = """<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Twin feedback: retained initial result and revised hypotheses</title>
<style>
body{{font:16px/1.55 system-ui,sans-serif;max-width:1200px;margin:32px auto;padding:0 24px;color:#26313e;background:#fafbfc}}
h1,h2{{line-height:1.2}}h2{{font-size:1.25rem;margin-top:28px}}img{{width:100%;height:auto;background:#fff;border:1px solid #d9e0e8}}
table{{border-collapse:collapse;width:100%;background:white;font-size:14px}}th,td{{padding:8px 10px;border:1px solid #d9e0e8;text-align:left;vertical-align:top}}th{{background:#edf2f7}}
.notice{{padding:14px 18px;background:#fff2d2;border-left:4px solid #c38d18}}.next{{padding:14px 18px;background:#e7f2ee;border-left:4px solid #2b8465}}
blockquote{{margin:12px 0;padding:12px 18px;background:white;border-left:4px solid #8e9caf;white-space:pre-wrap;overflow-wrap:anywhere}}.scroll{{overflow-x:auto}}.muted{{color:#526376}}li{{margin:6px 0}}
</style>
<h1>Researcher feedback → revised twin hypothesis</h1>
<p class="notice">{} Nothing in this page confirms the specific twin law, either orientation, domain membership or HKL assignments.</p>
<h2>1. Retained single-domain initial calculation</h2>
<p>{}/{} reflections matched; {} remained unexplained. The initial result is preserved: {} · {}.</p>
<h2>2. Scoped feedback</h2><blockquote>{}</blockquote>
<p>Recorded authority: <strong>{}</strong>. Confirmation scope: <strong>twinning presence only</strong>. {}</p>
<h2>3. Agent proposes and tests revised explanations</h2>
<p>All {} tested FCC Σ3 variants remain <strong>hypothesized</strong>. The selected example proposes axis {}, angle {}°, B beam {}. Selection uses the search measurements, not independent validation.</p>
<p>Fixed registration: rotation {}°, scale {}, translation {}, flip_y={}. Fixed tolerance {} Å⁻¹. The source pixels, measured points, calibration and initial result are retained.</p>
<div class="scroll"><table><thead><tr><th>Proposed twin axis</th><th>Angle / °</th><th>B zone</th><th>Authority</th><th>Matched</th><th>Unexplained</th><th>Matched RMS / Å⁻¹</th></tr></thead><tbody>{}</tbody></table></div>
<h2>4. Compare before and after</h2><img src="data:image/png;base64,{}" alt="Before and after comparison of the same measured peaks, including A, B, shared and unexplained classes">
<p>The revised joint assignment matches {}/{} reflections, with {} still unexplained. Numbered peaks are the same observations in both panels; measured q_y is plotted upward without changing source array semantics.</p>
<div class="scroll"><table><thead><tr><th>Peak</th><th>q_x / Å⁻¹</th><th>q_y / Å⁻¹</th><th>Proposed class</th><th>Domain-qualified proposed HKLs</th><th>Residual / Å⁻¹</th><th>Authority</th></tr></thead><tbody>{}</tbody></table></div>
<p><strong>Still unexplained peak numbers: {}.</strong> Shared means numerically coincident predicted projections; each measured peak is counted once. It does not confirm a domain fraction or unique HKL.</p>
<details><summary>Unassigned simulated projection groups</summary><ul>{}</ul></details>
<h2>5. Next observation</h2><div class="next">{}</div>
<h2>Scientific limits</h2><ul>
<li>Two periodic-domain kinematic models are compared. No atomistic twin boundary, coherent interference, dynamical scattering or double diffraction is simulated.</li>
<li>The same simulator generates and compares the synthetic example. Every measured point participates in search; there is no independent held-out validation.</li>
<li>More parameters can improve a geometric match without proving twinning. The scoped statement does not confirm any particular twin law or proposed reflection assignment.</li>
<li>Unassigned simulated positions do not establish experimental absence or guaranteed visibility. Kinematic intensities are not compared with detector counts or HRTEM FFT contrast.</li>
<li>{}</li></ul>
</html>""".format(
        text(authority_notice), initial["matched_count"], len(joint["observations"]), initial["unexplained_count"],
        evidence_link(result["initial_stage_path"], "initial stage"), evidence_link(initial["comparison_path"], "original committed comparison"),
        text(observation["source_text"]), text(authority), text(result["confirmation_boundary"]),
        len(result["alternatives"]), text(best["twin_axis_uvw"]), number(best["twin_rotation_deg"]), text(best["zone_b_uvw"]),
        number(fixed["rotation_deg"]), number(fixed["scale"]), text(fixed["translation_inv_angstrom"]), text(fixed["flip_y"]), number(result["max_residual_inv_angstrom"]),
        "".join(trial_rows), base64.b64encode(png).decode("ascii"), joint["matched_count"], len(joint["observations"]), joint["unexplained_count"],
        "".join(per_peak), text(unexplained or "none"), "".join(unassigned_rows) or "<li>None</li>",
        text(result["next_observation"]), text(result["evidence_scope"]))
    with image_path.open("xb") as stream:
        stream.write(png)
    with index_path.open("x", encoding="utf-8") as stream:
        stream.write(document)
    return {"index_path": str(index_path), "image_path": str(image_path)}
