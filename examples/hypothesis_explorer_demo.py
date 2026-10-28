"""Generate a sourced synthetic diffraction experiment for Hypothesis Explorer.

Run in the independent environment from requirements-structure-tools.txt. This
does not call DM, fetch Materials Project data, or modify an existing output.
The search receives measured vectors and candidate CIFs, never the truth HKLs.
This is algorithmically blind synthetic recovery, not a blinded human trial or
independent validation of the simulator used to generate the experiment.
"""

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from ase.build import bulk
from ase.io import write
from scipy.ndimage import maximum_filter
import tifffile

from crystallography.structure_tools import execute as structure_execute
from tools.image_workspace import execute as image_execute


def sha_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    """Publish only to a new file; save request IDs durably before calls."""
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def build_fixture(output):
    output = Path(output)
    if not output.is_absolute():
        raise ValueError("--output must be an absolute, new directory")
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    fixture = output / "fixture"
    fixture.mkdir()
    requests = output / "requests"
    requests.mkdir()
    sequence_number = 0

    def call(provider, action, **arguments):
        nonlocal sequence_number
        sequence_number += 1
        name = "structure" if provider is structure_execute else "image"
        request = {
            "workspace": str(output / (name + "-workspace")),
            "action": action,
            "request_id": "fixture-{:03d}".format(sequence_number),
            **arguments,
        }
        write_json(requests / (request["request_id"] + ".json"), request)
        response = provider(request)
        if not response.get("ok"):
            raise RuntimeError(json.dumps(response, ensure_ascii=False))
        return response["result"]

    candidates = []
    candidate_provenance = []
    truth_structure = None
    for symbol, crystal, lattice in (("Al", "fcc", 4.05),
                                      ("Fe", "bcc", 2.86),
                                      ("Cu", "fcc", 3.615)):
        source = fixture / (symbol.lower() + "-" + crystal + ".cif")
        atoms = bulk(symbol, crystal, a=lattice, cubic=True)
        with source.open("xb") as stream:
            write(stream, atoms, format="cif")
            stream.flush()
            os.fsync(stream.fileno())
        opened = call(structure_execute, "open", source_path=str(source))
        if symbol == "Al":
            truth_structure = opened
        candidates.append({
            "label": symbol + " " + crystal.upper(),
            "source_path": str(source),
            "zone_axes": [[0, 0, 1], [1, 1, 0], [1, 1, 1]],
        })
        candidate_provenance.append({
            "label": symbol + " " + crystal.upper(),
            "source_path": str(source),
            "source_sha256": sha_file(source),
            "generator": "ase.build.bulk(symbol, crystal, a=lattice, cubic=True)",
            "symbol": symbol,
            "crystal": crystal,
            "lattice_parameter_angstrom": lattice,
            "parameter_status": "explicit ideal synthetic model; not measured lattice constants",
            "structure_object_id": opened["object_id"],
        })

    size, radius = 512, 0.9
    scale = 2.0 * radius / size
    dc = [size // 2, size // 2]
    truth_orientation = call(
        structure_execute, "orient", object_id=truth_structure["object_id"],
        zone_axis_uvw=[0, 0, 1], in_plane_rotation_deg=17.0,
    )
    truth = call(
        structure_execute, "simulate", object_id=truth_structure["object_id"],
        orientation_id=truth_orientation["object_id"], voltage_kv=200,
        reciprocal_radius_inv_angstrom=radius,
        max_excitation_error_inv_angstrom=0.02, size=size,
        sigma_pixels=1.0, with_direct_beam=False,
    )
    raster = np.load(truth["array_path"], allow_pickle=False)
    if raster.shape != (size, size) or not np.isfinite(raster).all():
        raise ValueError("Synthetic simulator returned an invalid raster")
    pixels = np.rint(raster * 60000.0).astype(np.uint16)
    tiff = fixture / "synthetic-detector.tiff"
    with tiff.open("xb") as stream:
        tifffile.imwrite(stream, pixels, photometric="minisblack")
        stream.flush()
        os.fsync(stream.fileno())
    source_hash = sha_file(tiff)

    sequence = call(image_execute, "open", source_path=str(tiff))
    frame = call(image_execute, "frame", object_id=sequence["object_id"], frame_index=0)
    calibrated = call(
        image_execute, "calibrate", object_id=frame["object_id"], scope="image",
        coordinate_domain="reciprocal_space", declare_reciprocal=True,
        xy_scale={"x": scale, "y": scale, "unit": "1/angstrom"},
        source_text=("Synthetic generator grid: 2*0.9/512 cycles/angstrom per pixel; "
                     "pinned diffsims maps +labX to columns and +labY to rows. "
                     "Fixed synthetic scale, not independent experimental metrology."),
    )
    centred = call(
        image_execute, "centre", object_id=calibrated["object_id"], center_xy=dc,
        coordinate_space="source_array_indices",
        source_text="Synthetic generator DC is [256,256]; known grid centre, no centre fit.",
    )

    # Peak selection uses the saved TIFF pixels, not the truth reflection list.
    measured_pixels = tifffile.imread(tiff)
    if not np.array_equal(measured_pixels, pixels):
        raise ValueError("The reopened TIFF differs from the generated uint16 array")
    ys, xs = np.nonzero(
        (measured_pixels == maximum_filter(measured_pixels, size=7))
        & (measured_pixels > 600)
    )
    points = [[int(x), int(y)] for x, y in zip(xs, ys)
              if 0.1 < math.hypot(x - dc[0], y - dc[1]) * scale < 0.85]
    if not 2 <= len(points) <= 32:
        raise ValueError("Synthetic peak selection must provide 2..32 measured reflections")
    measurements = [call(
        image_execute, "measure", object_id=centred["object_id"],
        coordinate_space="source_array_indices", points=[dc, point],
    ) for point in points]
    if sha_file(tiff) != source_hash:
        raise ValueError("Synthetic source TIFF changed during measurement")

    # One-pixel truncation per axis is the pinned raster's documented policy.
    # Declare its geometric bound before searching any candidate or angle.
    tolerance = math.sqrt(2.0) * scale
    config = {
        "measurement_paths": [item["manifest_path"] for item in measurements],
        "current_image_object_id": centred["object_id"],
        "experimental_kind": "other_diffraction",
        "screen_axes": {
            "flip_y": False,
            "basis": ("Pinned diffsims raster maps +labX to increasing columns and "
                      "+labY to increasing rows; the TIFF preserves that grid. "
                      "No screen reflection is fitted or inferred."),
        },
        "max_residual_inv_angstrom": tolerance,
        "rotation_range_deg": [-180, 180],
        "simulation": {
            "voltage_kv": 200, "reciprocal_radius_inv_angstrom": radius,
            "max_excitation_error_inv_angstrom": 0.02, "size": 128,
            "sigma_pixels": 1.0, "with_direct_beam": False,
        },
        "candidates": candidates,
        "followup_radius_inv_angstrom": 1.25,
    }
    config_path = output / "config.json"
    write_json(config_path, config)
    write_json(output / "fixture.json", {
        "schema_version": 1,
        "kind": "ideal_synthetic_kinematic_diffraction_experiment",
        "dm_called": False,
        "independent_simulator_validation": False,
        "blindness_scope": ("Search config contains no truth label, true orientation or HKL "
                            "correspondences; this is algorithmically blind synthetic recovery, "
                            "not a blinded human trial. The same simulator generates and tests models."),
        "candidates": candidate_provenance,
        "truth": {"candidate_label": "Al FCC", "zone_axis_uvw": [0, 0, 1],
                  "in_plane_rotation_deg": 17.0, "simulation_manifest_path": truth["manifest_path"],
                  "simulation_manifest_sha256": sha_file(truth["manifest_path"]),
                  "array_path": truth["array_path"], "array_sha256": sha_file(truth["array_path"]),
                  "parameters": truth["parameters"]},
        "detector": {"path": str(tiff), "sha256": source_hash, "dtype": "uint16",
                     "shape_yx": [size, size], "dc_index_xy": dc,
                     "xy_scale_inv_angstrom": scale,
                     "pixel_mapping": "column=+labX; row=+labY",
                     "conversion": "round(normalized qualitative diffsims raster * 60000) to uint16",
                     "maximum_conversion_error_normalized": float(np.max(np.abs(pixels / 60000.0 - raster))),
                     "intensity_semantics": "arbitrary synthetic raster values; not detector counts",
                     "source_unchanged_after_measurement": True},
        "peak_selection": {"source": "reopened TIFF pixel values",
                           "method": "scipy.ndimage.maximum_filter(size=7); value>600; 0.1<|q|<0.85",
                           "points_xy_pixels": points, "count": len(points),
                           "measurement_paths": config["measurement_paths"],
                           "detection_completeness_claimed": False},
        "calibration": {"current_image_object_id": centred["object_id"],
                        "source": "known synthetic generator grid; stored as an explicit sourced calibration statement",
                        "max_residual_inv_angstrom": tolerance,
                        "tolerance_basis": "sqrt(2) * pixel scale: pinned diffsims truncates each in-frame raster centre by <1 pixel per axis",
                        "independent_experimental_metrology": False},
        "evidence_scope": "All selected points are search evidence; no independent held-out validation.",
        "software": {"python": platform.python_version(), **{
            name: importlib.metadata.version(name) for name in
            ("numpy", "scipy", "ase", "diffsims", "diffpy.structure", "tifffile")}},
        "generator_source_sha256": sha_file(__file__),
        "scientific_worker_source_sha256": {
            "crystallography/structure_tools.py": sha_file(Path(__file__).resolve().parents[1] / "crystallography/structure_tools.py"),
            "tools/image_workspace.py": sha_file(Path(__file__).resolve().parents[1] / "tools/image_workspace.py"),
        },
        "config_path": str(config_path), "config_sha256": sha_file(config_path),
    })
    return config_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="New absolute output directory; existing directories are refused")
    args = parser.parse_args()
    config = build_fixture(args.output)
    print("Created synthetic experiment and committed image measurements:")
    print(config)
    print("Next: python tools/hypothesis_explorer.py --config <config.json> --output <new-absolute-directory>")


if __name__ == "__main__":
    main()
