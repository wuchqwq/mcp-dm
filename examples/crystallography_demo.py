"""Generate an independent synthetic SAED-style task; never connects to DM.

Creates the existing mock schema-1 NPY capture, an automatic workflow request,
and a separate answer record. No generated arrays or private inputs belong in Git.
Run from the repository: python -m examples.crystallography_demo --workspace NEW
"""
import argparse
import json
import math
from pathlib import Path

import numpy as np

from bridge.dm_bridge import MockBackend


def prepare(workspace, model="FCC"):
    workspace = Path(workspace)
    workspace.mkdir()  # Never replace a previous demonstration or answer record.
    center = np.array([64.3, 61.7])
    scale = np.array([.2, -.2])
    if model == "FCC":
        vectors = np.array([[5., 0.], [0., 5.], [5., 5.]])
        truth = {"model": "FCC", "a_nm": .4, "zone_axis": [0, 0, 1],
                 "g_vectors_cycles_per_nm": vectors.tolist(),
                 "warning": "The square projection also admits BCC/P metric hypotheses; no unique phase expected"}
    elif model == "HCP":
        a, c = .295, .468
        x = 2 / (math.sqrt(3) * a)
        vectors = np.array([[x, 0.], [0., 2/c], [x, 2/c], [x, 1/c]])
        truth = {"model": "HCP", "a_nm": a, "c_nm": c, "c_over_a": c/a,
                 "g_vectors_cycles_per_nm": vectors.tolist(),
                 "warning": "Hexagonal metric truth; intensities are arbitrary Gaussian markers, not a dynamical electron simulation"}
    else:
        raise ValueError("Choose FCC or HCP demo")
    positions = np.concatenate((center + vectors/scale, center - vectors/scale))
    y, x = np.indices((128, 128))
    values = np.full((128, 128), 1., dtype=float)
    for i, (px, py) in enumerate(positions):
        values += (100. + 10 * (i % len(vectors))) * np.exp(-((x-px)**2+(y-py)**2)/(2*.75**2))
    # Deliberately no central bright spot: centre must be justified by pairs.
    values += np.random.default_rng(614).normal(0, .08, values.shape)

    class PreparedMock(MockBackend):
        def _mk(self, image_id, rect):
            rec = dict(self._images[1000], width=128, height=128, scale=.2, unit="1/nm")
            return rec, values

    PreparedMock().capture2d(1000, [8, 6, 120, 118], str(workspace/"capture"))
    request = {"schema_version": 1, "coordinate_frame": "source_pixel_centers_xy",
               "source": {"kind": "synthetic_diffraction", "capture_directory": "capture"},
               "center": {"mode": "auto"}, "spots": "auto",
               "calibration": {"mode": "explicit", "scale_xy": scale.tolist(), "unit": "1/nm",
                               "convention": "cycles_per_length", "basis": "independent synthetic reciprocal scale"},
               "indexing": {"models": ["FCC", "BCC", "HCP", "P"], "max_index": 3,
                            "relative_tolerance": .03, "angle_tolerance_deg": 2., "max_candidates": 8},
               "detection": {"max_spots": 10, "min_distance": 3, "threshold_rel": .15}}
    if model == "HCP":
        cif = """data_generated_hexagonal_reference
_cell_length_a 2.95
_cell_length_b 2.95
_cell_length_c 4.68
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 120
_space_group_name_H-M_alt 'P 1'
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
Ti1 Ti 0 0 0
Ti2 Ti 0.666666666666667 0.333333333333333 0.5
"""
        (workspace/"reference.cif").write_text(cif, encoding="ascii")
        request["references"] = [{"label": "generated-hexagonal-reference", "model": "HCP", "cif": "reference.cif"}]
    (workspace/"request.json").write_text(json.dumps(request, indent=2), encoding="utf-8")
    (workspace/"answer-record.json").write_text(json.dumps(dict(truth, center_source_xy=center.tolist(),
        spot_source_xy=positions.tolist(), actual_dm=False, external_synthetic=True), indent=2), encoding="utf-8")
    return workspace/"request.json"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--model", choices=("FCC", "HCP"), default="FCC")
    args = parser.parse_args()
    print(prepare(args.workspace, args.model))
