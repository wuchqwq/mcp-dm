"""Deterministic direct-lattice zone axis to a shared laboratory rotation.

This is coordinate geometry, not a scattering engine. Source atoms remain
immutable. The authoritative active matrix is shared by a display copy and
diffsims' intrinsic RZXZ reciprocal-vector transform.
"""
import math
import warnings

import numpy as np
from scipy.spatial.transform import Rotation


class OrientationError(ValueError):
    code = "INVALID_ORIENTATION"


def require(condition, message):
    if not condition:
        raise OrientationError(message)


def indices(value, name):
    require(type(value) is list and len(value) == 3 and
            all(type(v) is int and abs(v) <= 32 for v in value) and any(value),
            name + " requires a nonzero three-index integer UVW direction, |index|<=32; no Miller-Bravais shorthand")
    return np.asarray(value, dtype=float)


def unit_vector(vector, name):
    vector = np.asarray(vector, dtype=float)
    length = math.hypot(*vector)
    require(vector.shape == (3,) and np.isfinite(vector).all() and math.isfinite(length) and length > 0,
            name + " resolves to a missing, zero or nonfinite Cartesian vector")
    return vector / length


def from_zone_axis(cell, zone_axis_uvw, in_plane_direction_uvw=None, in_plane_rotation_deg=0.):
    """Build R such that R @ unit(uvw @ row_cell) == laboratory +Z.

    At zero in-plane angle the projected reference points along laboratory +X;
    +Y completes a right-handed basis. Positive in-plane rotation is an active
    right-handed rotation around laboratory +Z (reference +X moves toward +Y).
    """
    cell = np.asarray(cell, dtype=float)
    require(cell.shape == (3, 3) and np.isfinite(cell).all() and np.max(np.abs(cell)) <= 1e7,
            "A finite bounded row-vector Cartesian Angstrom cell is required")
    uvw = indices(zone_axis_uvw, "zone_axis_uvw")
    require(all(value == 0 or math.hypot(*cell[i]) > 0 for i, value in enumerate(uvw)),
            "zone_axis_uvw uses a missing cell vector; unknown axes cannot be replaced with zero")
    beam = unit_vector(uvw @ cell, "zone_axis_uvw")
    require(type(in_plane_rotation_deg) in (int, float) and math.isfinite(in_plane_rotation_deg) and
            abs(in_plane_rotation_deg) <= 360,
            "in_plane_rotation_deg must be finite degrees in [-360,360]")
    if in_plane_direction_uvw is not None:
        reference_uvw = indices(in_plane_direction_uvw, "in_plane_direction_uvw")
        require(all(value == 0 or math.hypot(*cell[i]) > 0 for i, value in enumerate(reference_uvw)),
                "in_plane_direction_uvw uses a missing cell vector; no inferred axis")
        reference = unit_vector(reference_uvw @ cell, "in_plane_direction_uvw")
        choice = {"kind": "projected_direct_lattice_direction", "direction_uvw": list(in_plane_direction_uvw)}
    else:
        # A zone alone leaves a roll degree of freedom. This deterministic
        # Cartesian convention is explicit; it is not an inferred crystal axis.
        axis = int(np.argmin(np.abs(beam)))
        reference = np.eye(3)[axis]
        choice = {"kind": "cartesian_axis_least_parallel_to_beam", "cartesian_axis": "xyz"[axis],
                  "tie_rule": "first of Cartesian x,y,z with minimal absolute beam component",
                  "direction_uvw": None}
    projected = reference - float(np.dot(reference, beam)) * beam
    require(math.hypot(*projected) > 1e-12,
            "The in-plane reference is parallel or numerically indistinguishable from the beam")
    x_axis = unit_vector(projected, "projected in-plane reference")
    y_axis = unit_vector(np.cross(beam, x_axis), "right-handed laboratory Y")
    basis = np.stack((x_axis, y_axis, beam))
    roll = Rotation.from_rotvec(np.asarray([0., 0., math.radians(in_plane_rotation_deg)])).as_matrix()
    matrix = roll @ basis
    determinant = float(np.linalg.det(matrix))
    require(np.allclose(matrix @ matrix.T, np.eye(3), atol=2e-12, rtol=0) and
            abs(determinant - 1.) <= 2e-12 and
            np.allclose(matrix @ beam, [0., 0., 1.], atol=2e-12, rtol=0),
            "The derived laboratory transform is not a proper right-handed beam rotation")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        angles = Rotation.from_matrix(matrix).as_euler("ZXZ", degrees=True)
    reconstructed = Rotation.from_euler("ZXZ", angles, degrees=True).as_matrix()
    require(np.allclose(matrix, reconstructed, atol=2e-12, rtol=0),
            "Intrinsic ZXZ angles do not reproduce the authoritative matrix")
    return {
        "record_version": 1, "zone_axis_uvw": list(zone_axis_uvw),
        "index_convention": "three-index direct lattice UVW; beam_cartesian = UVW @ row_vector_cell",
        "source_cell_angstrom": cell.tolist(), "beam_direction_cartesian_source_unit": beam.tolist(),
        "beam_direction_lab_unit": (matrix @ beam).tolist(),
        "reference": {**choice, "cartesian_source_unit": reference.tolist(),
                      "projected_cartesian_source_unit": x_axis.tolist(),
                      "projected_cartesian_lab_unit": (matrix @ x_axis).tolist()},
        "in_plane_rotation_deg": float(in_plane_rotation_deg),
        "in_plane_rotation_convention": "active right-handed laboratory +Z; positive rotates +X toward +Y",
        "rotation_matrix_cartesian": matrix.tolist(),
        "inverse_rotation_matrix_cartesian": matrix.T.tolist(),
        "row_vector_rule": "v_lab = v_source @ R.T; column_vector_rule: v_lab = R @ v_source",
        "matrix_semantics": "active Cartesian source-to-laboratory rotation; source positions/cell are never overwritten",
        "handedness": "right", "determinant": determinant,
        "euler_rzxz_deg": angles.tolist(),
        "euler_convention": "SciPy intrinsic ZXZ in degrees; same active matrix as diffsims0.7.0 transforms3d.euler.euler2mat(axes='rzxz')",
        "euler_gimbal_lock": any("Gimbal lock" in str(item.message) for item in caught),
        "euler_nonuniqueness": "At gimbal lock the matrix remains unique; SciPy sets the third angle to zero",
        "quaternion_xyzw": Rotation.from_matrix(matrix).as_quat().tolist(),
        "laboratory_axes": {"x": "transverse horizontal +X", "y": "right-handed transverse +Y; ASE/3Dmol screen up, diffsims raster increasing rows (down)",
                            "z": "selected positive zone-axis beam; diffsims optical axis"},
        "display_raster_relation": "Same laboratory vectors; ASE/3Dmol use screen +Y up, pinned diffsims raster maps +Y to increasing rows. Compare scientific coordinates with explicit image-axis mapping, never silently mirror data.",
        "view_direction": "exit-side back-view: beam propagation is +laboratory Z; standard display observer is at +Z looking toward origin (camera line-of-sight -Z); camera motion is presentation only",
        "source_coordinates_modified": False, "phase_identified": False,
    }
