"""Reproducible scientific inputs for the three Image Panel figure presets.

These are explicitly synthetic geometry/interaction demonstrations, not TEM
image formation or experimental phase identification. Run in the independent
analysis environment. An optional --twin-revision reuses the immutable #42
comparison; omission reproduces that existing bounded recipe first.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import tifffile
from tools.image_workspace import Workspace, execute


def write_json(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Calls:
    def __init__(self, output, workspace=None):
        self.output = Path(output)
        self.workspace = Path(workspace) if workspace else self.output / "image-workspace"
        self.requests = self.output / "calls"
        self.requests.mkdir(exist_ok=True)
        self.sequence = 0
        self.namespace = hashlib.sha256(str(self.output.resolve()).encode("utf-8")).hexdigest()[:12]

    def __call__(self, action, **parameters):
        self.sequence += 1
        # A distinct prefix also permits additive reuse of a saved twin workspace.
        request = {"workspace": str(self.workspace), "action": action,
                   "request_id": "publication-{}-{:03d}".format(self.namespace, self.sequence),
                   **parameters}
        write_json(self.requests / (request["request_id"] + ".json"), request)
        response = execute(request)
        if not response.get("ok"):
            raise RuntimeError(json.dumps(response, ensure_ascii=False))
        return response["result"]


def presentation(text=None, category="none", layer="experimental", important=True,
                 offset=None, shape=None):
    value = {"category": category, "layer": layer, "geometry_visible": True,
             "marker_radius": 5, "line_width": 1.25,
             "label": {"font_size": 12, "leader": True, "pinned": False,
                       "visible": True, "figure_visible": True, "important": important}}
    if text is not None:
        value["label"]["text"] = text
    if offset is not None:
        value["label"]["offset"] = offset
    if shape:
        value["marker_shape"] = shape
    return value


def mark(ident, kind, coords, source, space="source_pixels", text="", **extra):
    return {"annotation_id": ident, "kind": kind, "coordinates": list(coords),
            "source_object_id": source, "coordinate_space": space,
            "text": text, "color": "white", "status": "hypothesized", **extra}


def save_tiff(path, pixels):
    with path.open("xb") as stream:
        tifffile.imwrite(stream, pixels, photometric="minisblack")
        stream.flush()
        os.fsync(stream.fileno())
    if not np.array_equal(tifffile.imread(path), pixels):
        raise ValueError("Reopened TIFF differs from generated pixels")
    return digest(path)


def open_calibrated(calls, source):
    opened = calls("open", source_path=str(source))
    frame = calls("frame", object_id=opened["object_id"], frame_index=0)
    calibrated = calls("calibrate", object_id=frame["object_id"], scope="image",
                      xy_scale={"x": .02, "y": .02, "unit": "nm"},
                      source_text="Explicit synthetic sampling +0.02 nm/pixel in X and Y; not experimental metrology.")
    return calls("context", object_id=calibrated["object_id"], metadata={
        "data_meaning": "synthetic_demo",
        "source_text": "Generated periodic uint16 teaching texture; no TEM, multislice, phase or specimen claim."})


def real_space(output):
    output.mkdir()
    calls = Calls(output)
    y, x = np.indices((384, 512), dtype=np.float64)
    phase = np.where(x < 266, 0., .6)
    values = 30000 + 12000*np.cos(2*np.pi*x/16+phase) + 9000*np.cos(2*np.pi*y/24)
    pixels = np.rint(values).astype(np.uint16)
    source = output / "synthetic-real-space.tiff"
    before = save_tiff(source, pixels)
    context = open_calibrated(calls, source)
    view = calls("view", object_id=context["object_id"], max_size=768,
                 display_range=[9000, 51000], scale_bar=False)
    sid = view["panels"][0]["source_object_id"]
    lines = [[82, 316, 98, 316], [428, 76, 428, 100]]
    measured = [calls("measure", object_id=view["object_id"], coordinate_space="source_pixels",
                      points=[c[:2], c[2:]]) for c in lines]
    marks = [mark("region-A", "rectangle", [52, 50, 226, 232], sid, text="A",
                  presentation=presentation("A", offset=[-13, -12])),
             mark("region-B", "rectangle", [308, 178, 472, 340], sid, text="B",
                  presentation=presentation("B", offset=[-13, -12])),
             mark("observed-boundary", "line", [266, 24, 266, 356], sid,
                  note="Position of the explicitly generated phase discontinuity, not a TB/GB assignment.",
                  presentation=presentation("boundary", important=False, offset=[12, 20]))]
    for i, (coordinates, record) in enumerate(zip(lines, measured)):
        text = "d = {:.3f} {}".format(record["physical_distance"], record["physical_unit"])
        display = presentation(text, offset=[-8, 21] if i == 0 else [-112, 4])
        display["label"].update(measurement_object_id=record["object_id"], measurement_kind="distance")
        marks.append(mark("distance-{}".format(i+1), "line", coordinates, sid, text=text,
                          note="Measured by image_measure record {}".format(record["object_id"]),
                          presentation=display))
    annotated = calls("annotate", object_id=view["object_id"], annotations=marks)
    if digest(source) != before:
        raise ValueError("Original real-space TIFF changed")
    result = {"case": "A", "preset": "real-space", "image_workspace": str(calls.workspace),
              "object_id": annotated["object_id"], "manifest_path": annotated["manifest_path"],
              "source_path": str(source), "source_sha256": before, "source_unchanged": True,
              "measurements": [{"object_id": r["object_id"], "manifest_path": r["manifest_path"],
                                "points": r["points"], "physical_distance": r["physical_distance"],
                                "physical_unit": r["physical_unit"]} for r in measured],
              "annotation_count": len(marks), "scale_bar": "Use active +0.02 nm/pixel calibration; figure layer, not baked into clean base.",
              "generator": "30000+12000*cos(2*pi*x/16+phase)+9000*cos(2*pi*y/24); phase=0 left of x266,0.6 right",
              "scope": "Synthetic periodic texture and descriptive boundary, not an atomistic interface."}
    write_json(output / "case.json", result)
    return result


def diffraction(output):
    output.mkdir()
    calls = Calls(output)
    h, w = 384, 512
    y, x = np.indices((h, w), dtype=np.float64)
    components = [(16, 0), (0, 12), (16, 12), (16, -12), (32, 0), (0, 24), (32, 12), (16, 24)]
    values = np.full((h, w), 30000.)
    for i, (kx, ky) in enumerate(components):
        values += (2200+90*i)*np.cos(2*np.pi*(kx*x/w+ky*y/h)+.17*i)
    if values.min() < 0 or values.max() > 65535:
        raise ValueError("Synthetic values require clipping")
    source = output / "synthetic-fft-components.tiff"
    before = save_tiff(source, np.rint(values).astype(np.uint16))
    context = open_calibrated(calls, source)
    spectrum = calls("fft", object_id=context["object_id"], window="none", subtract_mean=True,
                     max_size=768)
    # Verify peaks in the actual immutable FFT coefficients before measuring.
    spectrum_values = np.load(spectrum["array_path"], allow_pickle=False)
    bins = [(sign*kx, sign*ky) for kx, ky in components for sign in (1, -1)]
    dc = [w//2, h//2]
    for kx, ky in bins:
        py, px = dc[1]+ky, dc[0]+kx
        local = np.abs(spectrum_values[py-1:py+2, px-1:px+2])
        if np.unravel_index(np.argmax(local), local.shape) != (1, 1):
            raise ValueError("Expected synthetic component is not an observed local FFT maximum")
    local_view = calls("view", object_id=spectrum["object_id"], frequency_rect=[212, 156, 300, 228],
                       max_size=768, upscale=True, spectrum_axes=False)
    sid = local_view["panels"][0]["source_object_id"]
    points = [[kx/w, ky/h] for kx, ky in bins]
    measurements = [calls("measure", object_id=spectrum["object_id"],
                          coordinate_space="frequency_cycles_per_pixel", points=[[0, 0], point]) for point in points]
    marks = []
    for i, (point, record) in enumerate(zip(points, measurements)):
        label = "g{}".format(i+1)
        # Typography examples remain explicit hypotheses, never confirmed HKL.
        text = "(1 -1 1)" if i == 2 else "[1 -1 0]" if i == 3 else label
        note = "Actual FFT maximum and image_measure {}; index text is a typography hypothesis, not indexing evidence.".format(record["object_id"])
        marks.append(mark("fft-peak-{:02d}".format(i+1), "point", point, sid,
                          space="frequency_cycles_per_pixel", text=label, note=note,
                          presentation=presentation(text, important=i < 6)))
    for i in (0, 2):
        marks.append(mark("key-vector-{}".format(i+1), "arrow", [0., 0., *points[i]], sid,
                          space="frequency_cycles_per_pixel", text="g{}".format(i+1),
                          arrow_length=None, arrowhead_size=5, line_width=1,
                          note="Starts at saved mathematical FFT DC [0,0], not local crop centre.",
                          presentation=presentation("", important=True)))
    annotated = calls("annotate", object_id=local_view["object_id"], annotations=marks)
    if digest(source) != before:
        raise ValueError("Original diffraction input changed")
    result = {"case": "B", "preset": "diffraction", "image_workspace": str(calls.workspace),
              "object_id": annotated["object_id"], "manifest_path": annotated["manifest_path"],
              "source_path": str(source), "source_sha256": before, "source_unchanged": True,
              "fft_object_id": spectrum["object_id"], "fft_array_sha256": digest(spectrum["array_path"]),
              "frequency_crop": [212, 156, 300, 228], "mathematical_dc": [0, 0],
              "observed_reflection_count": len(points), "annotation_count": len(marks),
              "component_bins_xy": [list(v) for v in components],
              "measured_points_cycles_per_pixel": points,
              "measurement_paths": [r["manifest_path"] for r in measurements],
              "scope": "Synthetic Fourier components; labels g1..g16, with two explicitly hypothetical typography examples. No phase assignment."}
    write_json(output / "case.json", result)
    return result


def build_twin_revision(output):
    from examples.twin_feedback_demo import build_fixture
    from tools.hypothesis_explorer import run
    from tools.twin_feedback import prepare_initial, revise
    config_path = build_fixture(output / "twin-input")
    run(json.loads(config_path.read_text(encoding="utf-8")), output / "twin-search")
    initial = prepare_initial(output / "twin-search" / "report.json", output / "twin-initial")
    (output / "twin-observation").mkdir()
    calls = Calls(output / "twin-observation", initial["image_workspace"])
    observation = calls("context", object_id=initial["display_object_id"], metadata={
        "research_observation": {"kind": "twinning_present", "authority": "synthetic_fixture",
                                 "source_text": "Synthetic acceptance script states the generated two periodic domains; no human confirmation."}})
    result = revise(output / "twin-initial" / "initial.json", observation["object_id"], output / "twin-revision")
    return Path(result["revision_path"])


def multi_domain(output, revision_path):
    output.mkdir()
    revision_path = Path(revision_path).resolve()
    revision = json.loads(revision_path.read_text(encoding="utf-8"))
    if revision.get("stage") != "two_domain_after_scoped_feedback" or revision.get("status") != "hypothesized":
        raise ValueError("Expected saved bounded #42 two-domain hypothesis")
    if revision.get("observation", {}).get("authority") != "synthetic_fixture":
        raise ValueError("This fixture only labels an explicitly synthetic twin demonstration")
    workspace = Workspace(revision["image_workspace"], writable=False)
    saved, _ = workspace.object(revision["display_object_id"])
    if any(item.get("status") == "user_confirmed" for item in saved.get("annotations", [])):
        raise ValueError("Do not replace a researcher's confirmed marks with fixture annotations")
    source = Path(saved["xy_calibration"]["applies_to"]["source_identity"]["path"])
    source_hash = digest(source)
    calls = Calls(output, revision["image_workspace"])
    context = calls("context", object_id=saved["object_id"], metadata={
        "data_meaning": "synthetic_demo", "source_text": "Reused bounded synthetic double-domain kinematic raster; no identification of the user's image."})
    view = calls("view", object_id=context["object_id"], max_size=768, scale_bar=False)
    sid = view["panels"][0]["source_object_id"]
    categories = revision["best"]["joint"]["rows"]
    input_config = Path(revision["initial"]["initial_report_path"]).parent / "input.json"
    config = json.loads(input_config.read_text(encoding="utf-8"))
    records = [json.loads(Path(path).read_text(encoding="utf-8")) for path in config["measurement_paths"]]
    marks = []
    for row in categories:
        i, category = row["measurement_index"], row["classification"]
        record = records[i]
        point = record["points"][1-record["dc_reference_point_index"]]
        marks.append(mark("domain-observed-{:02d}".format(i+1), "point", point, sid,
                          space=record["coordinate_space"], text=str(i+1),
                          note="Category from saved joint comparison {} row {}; no reclassification by colour.".format(revision_path.name, i),
                          presentation=presentation(str(i+1), category=category, important=category == "unexplained")))
    comparison = json.loads(Path(revision["comparison_a_path"]).read_text(encoding="utf-8"))
    registration = comparison["registration"]
    matrix = np.asarray(registration["matrix_xy"])
    translation = np.asarray(registration["translation_xy_inv_angstrom"])
    calibration = view["xy_calibration"]
    dc = calibration["dc_index_xy"]
    scales = [calibration["xy_scale"][key] for key in ("x", "y")]
    for domain, path in (("A", revision["simulation_a_path"]), ("B", revision["best"]["simulation_b_path"])):
        simulation = json.loads(Path(path).read_text(encoding="utf-8"))
        q = np.asarray(simulation["reflections"]["coordinates_inv_angstrom"])[:, :2]
        predicted = (q-translation) @ np.linalg.inv(matrix).T
        for i, vector in enumerate(predicted):
            point = [float(vector[j]/scales[j]+dc[j]) for j in range(2)]
            if not (0 <= point[0] < 512 and 0 <= point[1] < 512):
                continue
            marks.append(mark("domain-{}-prediction-{:02d}".format(domain, i+1), "point", point, sid,
                              space="source_array_indices", text="", note="Predicted by immutable simulation {}; explicit fixed experimental registration.".format(simulation["object_id"]),
                              presentation=presentation("", category=domain, layer="simulation_"+domain,
                                                        shape="cross", important=False)))
    annotated = calls("annotate", object_id=view["object_id"], annotations=marks)
    if digest(source) != source_hash:
        raise ValueError("Original twin demonstration TIFF changed")
    result = {"case": "C", "preset": "multi-domain", "image_workspace": str(calls.workspace),
              "object_id": annotated["object_id"], "manifest_path": annotated["manifest_path"],
              "revision_path": str(revision_path), "revision_sha256": digest(revision_path),
              "source_path": str(source), "source_sha256": source_hash, "source_unchanged": True,
              "counts": revision["best"]["joint"]["counts"], "annotation_count": len(marks),
              "measurement_paths": config["measurement_paths"],
              "measurements_used_in_search": True, "independent_validation": False,
              "source_identity": "Explicitly synthetic #42 demonstration; no identification of user data.",
              "status": "hypothesized", "scope": revision["evidence_scope"]}
    write_json(output / "case.json", result)
    return result


def build(output, twin_revision=None):
    output = Path(output)
    if not output.is_absolute():
        raise ValueError("--output must be an absolute new directory")
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    a = real_space(output / "real-space")
    b = diffraction(output / "diffraction")
    revision = Path(twin_revision) if twin_revision else build_twin_revision(output)
    c = multi_domain(output / "multi-domain", revision)
    result = {"schema_version": 1, "kind": "synthetic_publication_annotation_cases", "dm_called": False,
              "generator_source_sha256": digest(__file__), "cases": [a, b, c]}
    write_json(output / "fixture.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--twin-revision", type=Path,
                        help="Optional existing immutable #42 revision.json; omission reproduces its scientific recipe")
    args = parser.parse_args()
    result = build(args.output, args.twin_revision)
    print(json.dumps({"manifest": str(args.output / "fixture.json"),
                      "cases": [{key: row[key] for key in ("case", "preset", "image_workspace", "object_id", "annotation_count")} for row in result["cases"]]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
