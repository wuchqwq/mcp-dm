"""Create a reproducible, explicitly synthetic Image Panel interaction fixture.

Run with the independent requirements-images.txt environment, never GMS Python.
The periodic texture is a teaching/interaction input, not a TEM image formation
or multislice simulation. All 28 marks are editable hypotheses, not indexing.
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
from tools.image_workspace import execute


def write_json(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build(output):
    output = Path(output)
    if not output.is_absolute():
        raise ValueError("--output must be an absolute, new directory")
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    requests = output / "calls"
    requests.mkdir()
    workspace = output / "image-workspace"
    sequence = 0

    def call(action, **parameters):
        nonlocal sequence
        sequence += 1
        request = {"workspace": str(workspace), "action": action,
                   "request_id": "workbench-fixture-{:03d}".format(sequence), **parameters}
        write_json(requests / (request["request_id"] + ".json"), request)
        response = execute(request)
        if not response.get("ok"):
            raise RuntimeError(json.dumps(response, ensure_ascii=False))
        return response["result"]

    height, width = 384, 512
    y, x = np.indices((height, width), dtype=np.float64)
    frames = []
    for phase in (0., .35):
        values = (27000 + 12000*np.cos(2*np.pi*x/16+phase)
                  + 8000*np.cos(2*np.pi*y/24-phase)
                  + 3000*np.cos(2*np.pi*(x+y)/31))
        if np.any(values < 0) or np.any(values > 65535):
            raise ValueError("Fixture values must fit uint16 without clipping")
        frames.append(np.rint(values).astype(np.uint16))
    pixels = np.stack(frames)
    source = output / "synthetic-periodic-texture.tiff"
    with source.open("xb") as stream:
        tifffile.imwrite(stream, pixels, photometric="minisblack", metadata={"axes": "IYX"})
        stream.flush()
        os.fsync(stream.fileno())
    source_hash = digest(source)
    if not np.array_equal(tifffile.imread(source), pixels):
        raise ValueError("Reopened TIFF differs from generated uint16 pixels")
    opened = call("open", source_path=str(source))
    frame = call("frame", object_id=opened["object_id"], frame_index=0)
    calibrated = call("calibrate", object_id=frame["object_id"], scope="sequence",
                      xy_scale={"x": .02, "y": .02, "unit": "nm"},
                      source_text="Known synthetic teaching grid: signed XY +0.02 nm/pixel in both axes; not experimental metrology.")
    context = call("context", object_id=calibrated["object_id"], metadata={
        "data_meaning": "synthetic_demo",
        "source_text": "Explicitly generated periodic uint16 teaching texture for Image Panel interaction; no actual TEM or multislice claim."})
    view = call("view", object_id=context["object_id"], max_size=768,
                display_range=[4000, 50000], gamma=1.)
    panel = view["panels"][0]
    annotations = []
    for row in range(4):
        for column in range(6):
            number = row*6+column+1
            annotations.append({"annotation_id": "peak-{:02d}".format(number), "kind": "point",
                                "coordinates": [64+76*column, 55+85*row], "text": "P{}".format(number),
                                "coordinate_space": "source_pixels", "source_object_id": panel["source_object_id"],
                                "status": "hypothesized", "color": "cyan"})
    for ident, rect, color in (("A", [32, 30, 240, 200], "cyan"), ("B", [280, 160, 480, 350], "orange")):
        annotations.append({"annotation_id": "region-"+ident, "kind": "rectangle", "coordinates": rect,
                            "text": ident, "coordinate_space": "source_pixels", "source_object_id": panel["source_object_id"],
                            "status": "hypothesized", "color": color, "line_width": 1})
    for ident, coords in (("spacing-x", [90, 340, 170, 340]), ("spacing-y", [475, 40, 475, 120])):
        annotations.append({"annotation_id": ident, "kind": "line", "coordinates": coords,
                            "text": "1.6 nm (synthetic)", "coordinate_space": "source_pixels", "source_object_id": panel["source_object_id"],
                            "status": "hypothesized", "color": "white", "line_width": 1})
    marked = call("annotate", object_id=view["object_id"], annotations=annotations)
    if digest(source) != source_hash:
        raise ValueError("Original TIFF changed while creating views/annotations")
    fixture = {"schema_version": 1, "kind": "synthetic_image_panel_interaction_fixture", "dm_called": False,
               "image_workspace": str(workspace), "object_id": marked["object_id"], "manifest_path": marked["manifest_path"],
               "source_path": str(source), "source_sha256": source_hash, "source_unchanged": True,
               "shape_frames_y_x": list(pixels.shape), "dtype": "uint16", "annotation_count": len(annotations),
               "data_meaning": "synthetic_demo", "xy_scale_nm_per_pixel": [.02, .02],
               "generator": {"texture": "27000 + 12000*cos(2*pi*x/16+phase) + 8000*cos(2*pi*y/24-phase) + 3000*cos(2*pi*(x+y)/31)",
                             "frame_phases_rad": [0., .35], "conversion": "round to uint16; no clipping",
                             "limits": "Teaching/interaction texture only, not a TEM/multislice or experimental image."},
               "manifest_sha256": digest(marked["manifest_path"]), "generator_source_sha256": digest(__file__)}
    write_json(output / "fixture.json", fixture)
    return fixture


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    fixture = build(args.output)
    print(json.dumps({key: fixture[key] for key in ("image_workspace", "object_id", "manifest_path", "source_path", "annotation_count")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
