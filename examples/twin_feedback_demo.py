"""Create a sourced FCC twin experiment before any researcher feedback.

Run in the independent requirements-structure-tools.txt environment. The initial
search config contains candidate structures and measured pixels, but no truth
HKL, twin law, domain partition or researcher statement. The separate fixture
record documents the known synthetic truth for checking the later revision.
"""
import argparse
import importlib.metadata
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

from examples.hypothesis_explorer_demo import sha_file, write_json
from crystallography.structure_tools import execute as structure_execute
from tools.image_workspace import execute as image_execute


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
        request = {"workspace": str(output / (name + "-workspace")),
                   "action": action,
                   "request_id": "twin-fixture-{:03d}".format(sequence_number),
                   **arguments}
        write_json(requests / (request["request_id"] + ".json"), request)
        response = provider(request)
        if not response.get("ok"):
            raise RuntimeError(str(response))
        return response["result"]

    source = fixture / "cu-fcc.cif"
    with source.open("xb") as stream:
        write(stream, bulk("Cu", "fcc", a=3.615, cubic=True), format="cif")
        stream.flush()
        os.fsync(stream.fileno())
    source_hash = sha_file(source)
    opened = call(structure_execute, "open", source_path=str(source))
    size, radius, roll = 512, .9, 13.
    simulation_parameters = {"voltage_kv": 200,
                             "reciprocal_radius_inv_angstrom": radius,
                             "max_excitation_error_inv_angstrom": .02,
                             "size": size, "sigma_pixels": 1.,
                             "with_direct_beam": False}
    domains, rasters = [], []
    for label, zone in (("A", [1, -1, 0]), ("B", [0, -1, 1])):
        orientation = call(structure_execute, "orient", object_id=opened["object_id"],
                           zone_axis_uvw=zone, in_plane_direction_uvw=[1, 1, 1],
                           in_plane_rotation_deg=roll)
        simulation = call(structure_execute, "simulate", object_id=opened["object_id"],
                          orientation_id=orientation["object_id"], **simulation_parameters)
        raster = np.load(simulation["array_path"], allow_pickle=False)
        if raster.shape != (size, size) or not np.isfinite(raster).all() or np.any(raster < 0):
            raise ValueError("Invalid synthetic diffraction raster")
        rasters.append(raster)
        domains.append({"label": label, "zone_axis_uvw": zone,
                        "in_plane_direction_uvw": [1, 1, 1], "in_plane_rotation_deg": roll,
                        "orientation_manifest_path": orientation["manifest_path"],
                        "orientation_manifest_sha256": sha_file(orientation["manifest_path"]),
                        "rotation_matrix_cartesian": orientation["orientation"]["rotation_matrix_cartesian"],
                        "simulation_manifest_path": simulation["manifest_path"],
                        "simulation_manifest_sha256": sha_file(simulation["manifest_path"]),
                        "array_path": simulation["array_path"],
                        "array_sha256": sha_file(simulation["array_path"]),
                        "reflection_count": simulation["reflection_count"],
                        "effective_parameters": simulation["parameters"]})

    # The two proper orientations give the exact FCC Sigma3 60deg/[111]
    # relationship. Both beam directions are contained in the (111) plane.
    relation = np.array([[2., -1., 2.], [2., 2., -1.], [-1., 2., 2.]]) / 3.
    actual = np.asarray(domains[0]["rotation_matrix_cartesian"]).T @ np.asarray(domains[1]["rotation_matrix_cartesian"])
    if not np.allclose(actual, relation, atol=2e-12, rtol=0):
        raise ValueError("Existing orientation records do not reproduce the declared twin law")

    # This explicit detector artifact is deliberately not a Bragg reflection.
    # Its position comes from generated pixel values and is measured normally;
    # no measurement manifest or post-search unexplained point is fabricated.
    y, x = np.indices((size, size))
    artifact = .35 * np.exp(-((x-335.)**2 + (y-322.)**2) / 2.)
    combined = rasters[0] + rasters[1] + artifact
    normalized = combined / combined.max()
    pixels = np.rint(normalized * 60000.).astype(np.uint16)
    tiff = fixture / "synthetic-twin-detector.tiff"
    with tiff.open("xb") as stream:
        tifffile.imwrite(stream, pixels, photometric="minisblack")
        stream.flush()
        os.fsync(stream.fileno())
    tiff_hash = sha_file(tiff)

    sequence = call(image_execute, "open", source_path=str(tiff))
    frame = call(image_execute, "frame", object_id=sequence["object_id"], frame_index=0)
    scale = 2.*radius/size
    dc = [size//2, size//2]
    calibrated = call(image_execute, "calibrate", object_id=frame["object_id"], scope="image",
                      coordinate_domain="reciprocal_space", declare_reciprocal=True,
                      xy_scale={"x": scale, "y": scale, "unit": "1/angstrom"},
                      source_text=("Known synthetic diffsims grid: 2*0.9/512 cycles/angstrom per pixel; "
                                   "columns=+labX, rows=+labY. Fixed generator calibration, "
                                   "not independent experimental metrology."))
    centred = call(image_execute, "centre", object_id=calibrated["object_id"], center_xy=dc,
                   coordinate_space="source_array_indices",
                   source_text="Known synthetic raster mathematical DC at [256,256]; no fitted centre.")
    measured_pixels = tifffile.imread(tiff)
    if not np.array_equal(measured_pixels, pixels):
        raise ValueError("Reopened synthetic TIFF differs from the stored uint16 pixels")
    ys, xs = np.nonzero((measured_pixels == maximum_filter(measured_pixels, size=7)) &
                        (measured_pixels > 600))
    points = [[int(px), int(py)] for px, py in zip(xs, ys)
              if .1 < math.hypot(px-dc[0], py-dc[1])*scale < .85]
    if not 2 <= len(points) <= 32:
        raise ValueError("Synthetic peak selection must produce 2..32 measured points")
    measurements = [call(image_execute, "measure", object_id=centred["object_id"],
                         coordinate_space="source_array_indices", points=[dc, point]) for point in points]
    if sha_file(tiff) != tiff_hash or sha_file(source) != source_hash:
        raise ValueError("A synthetic input changed during computation or measurement")

    tolerance = math.sqrt(2.)*scale
    config = {"measurement_paths": [measurement["manifest_path"] for measurement in measurements],
              "current_image_object_id": centred["object_id"],
              "experimental_kind": "other_diffraction",
              "screen_axes": {"flip_y": False,
                              "basis": "Pinned diffsims maps +labX to columns and +labY to rows; the TIFF preserves that grid. No fitted mirror."},
              "max_residual_inv_angstrom": tolerance,
              "rotation_range_deg": [-180, 180],
              "simulation": {**simulation_parameters, "size": 128},
              "candidates": [{"label": "Cu FCC", "source_path": str(source),
                              "zone_axes": [[1, -1, 0], [0, -1, 1], [0, 0, 1]]}]}
    config_path = output / "config.json"
    write_json(config_path, config)
    write_json(output / "fixture.json", {
        "schema_version": 1,
        "kind": "synthetic_two_domain_FCC_Sigma3_diffraction_with_detector_artifact",
        "dm_called": False,
        "image_workspace": str(output / "image-workspace"),
        "current_image_object_id": centred["object_id"],
        "measurement_paths": config["measurement_paths"],
        "structure": {"label": "Cu FCC", "source_path": str(source), "source_sha256": source_hash,
                      "generator": "ase.build.bulk('Cu','fcc',a=3.615,cubic=True)",
                      "lattice_parameter_angstrom": 3.615,
                      "parameter_status": "explicit ideal synthetic model, not experimentally measured",
                      "structure_manifest_path": opened["manifest_path"]},
        "truth": {"domains": domains,
                  "twin_relation": {"name": "FCC Sigma3(111)", "rotation_axis_uvw": [1, 1, 1],
                                    "rotation_deg": 60., "matrix_domain_B_to_A": relation.tolist(),
                                    "verified_R_A_transpose_R_B": actual.tolist(),
                                    "matrix_convention": "column vectors: v_A=T@v_B; R_B=R_A@T",
                                    "source_url": "https://doi.org/10.1107/S1600576715004896"},
                  "atomic_interface_constructed": False,
                  "scattering_scope": "sum of two separate periodic-domain kinematic qualitative rasters; no interference, dynamical scattering or double diffraction"},
        "artifact": {"kind": "explicit synthetic non-Bragg detector signal", "center_xy_pixels": [335, 322],
                     "sigma_pixels": 1., "amplitude_before_sum_normalization": .35,
                     "generator": ".35*exp(-((x-335)^2+(y-322)^2)/2)",
                     "purpose": "retain an honest unexplained observation after revising to a twin model"},
        "detector": {"path": str(tiff), "sha256": tiff_hash, "dtype": "uint16", "shape_yx": [size, size],
                     "xy_scale_inv_angstrom": scale, "dc_index_xy": dc, "pixel_mapping": "columns=+labX; rows=+labY",
                     "composition": "sum independently normalized diffsims rasters A+B plus declared detector artifact, then divide by combined maximum",
                     "domain_brightness_weights": [1., 1.],
                     "brightness_weight_semantics": "arbitrary synthetic display weights; not domain volume fractions or detector counts",
                     "conversion": "round(normalized sum * 60000) to uint16",
                     "maximum_conversion_error_normalized": float(np.max(np.abs(pixels/60000.-normalized))),
                     "source_unchanged_after_measurement": True},
        "peak_selection": {"source": "reopened TIFF pixel values", "points_xy_pixels": points, "count": len(points),
                           "method": "scipy.ndimage.maximum_filter(size=7); value>600; 0.1<|q|<0.85",
                           "truth_reflection_table_used_for_selection": False, "detection_completeness_claimed": False},
        "calibration": {"max_residual_inv_angstrom": tolerance,
                        "tolerance_basis": "sqrt(2)*pixel scale; pinned diffsims truncates each raster centre by less than one pixel per axis",
                        "independent_experimental_metrology": False},
        "feedback_created": False,
        "evidence_scope": "All selected points are search evidence. No independent held-out validation. Same simulator generates and compares models.",
        "initial_config_scope": "No truth HKL, twin relation, domain partition or researcher feedback is supplied to the initial single-domain search.",
        "software": {"python": platform.python_version(), **{name: importlib.metadata.version(name) for name in
                     ("numpy", "scipy", "ase", "diffsims", "diffpy.structure", "tifffile")}},
        "generator_source_sha256": sha_file(__file__),
        "scientific_worker_source_sha256": {relative: sha_file(Path(__file__).resolve().parents[1] / relative)
                                             for relative in ("crystallography/structure_tools.py", "tools/image_workspace.py")},
        "config_path": str(config_path), "config_sha256": sha_file(config_path),
    })
    return config_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="New absolute output directory; no existing result is overwritten")
    arguments = parser.parse_args()
    config = build_fixture(arguments.output)
    print("Created synthetic twin experiment and committed image measurements:")
    print(config)
    print("Next: python tools/hypothesis_explorer.py --config <config.json> --output <new-absolute-search-directory>")


if __name__ == "__main__":
    main()
