# Shared zone-axis orientation

`structure_orient` creates one immutable orientation record from a fixed ASE
structure and a three-index direct-lattice `zone_axis_uvw`. Optional
`in_plane_direction_uvw` supplies a projected transverse reference; optional
`in_plane_rotation_deg` adds an active right-handed roll around laboratory +Z.
Save the operation request ID before calling it. Reuse the returned object ID
as `orientation_id` in `structure_view` or `structure_simulate`.

The exact supplied **row-vector cell** is used: the Cartesian beam vector is
`[u,v,w] @ cell`, normalized afterwards. Hexagonal and skew-cell indices are
therefore not treated as Cartesian components. This is three-index notation;
four-index Miller-Bravais input is not silently converted. A partial cell can
define a direct direction when that combination is nonzero; it does not become
a complete cell or qualify periodic diffraction simulation.
Every nonzero UVW component must refer to a supplied nonzero cell vector;
`[101]` cannot silently become `[100]` because the third vector is missing.

The authoritative matrix `R` maps the selected **positive** beam direction to
laboratory +Z. Column vectors use `v_lab = R @ v_source`; row vectors use
`v_lab = v_source @ R.T`. At zero roll, the projected reference maps to +X and
`Y = Z cross X`, so the transform is orthonormal with determinant +1. Reversing
the zone direction is a different record; no implicit Friedel or sign folding
is performed. A parallel/missing reference is refused. Without a reference,
the record explicitly chooses the Cartesian axis least parallel to the beam
(ties x, then y, then z); this is a reproducible roll convention, not a measured
crystal orientation.

The record includes R, its inverse, beam/reference vectors, determinant,
quaternion and intrinsic ZXZ angles in degrees. SciPy converts the matrix using
[intrinsic uppercase `ZXZ`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.spatial.transform.Rotation.as_euler.html).
The pinned [diffsims source](https://github.com/pyxem/diffsims/blob/v0.7.0/diffsims/generators/diffraction_generator.py)
uses `transforms3d.euler.euler2mat(..., axes="rzxz")` and actively multiplies
reciprocal vectors by that matrix. Before simulation, the adapter independently
reconstructs that actual pinned-engine matrix and checks it against R. Euler
gimbal lock is recorded: the angles are not unique, but R remains authoritative.
The existing reciprocal-enumeration completeness gate is unchanged.

`structure_view(orientation_id=...)` rotates an independent display copy of
the atoms and cell by R before the ASE projection. The mature interactive viewer
applies the same matrix to its renderer copy and reports whether it did so.
Source atoms, source cell and the original file remain unchanged. To create a
new scientific model, use `structure_derive(orientation_id=...)`; that produces
a new structure ID. Its old orientation cannot silently be reapplied as though
it still referred to the original cell. Explicit legacy Cartesian display
rotation or simulation Euler angles remain available, but cannot be combined
with `orientation_id` in the same call.

The view is explicitly an **exit-side back-view**: beam propagation is +lab Z,
while the standard observer is at +Z looking toward the origin, with camera
line-of-sight -Z and screen +Y up. Dragging changes only the camera, never R or
the simulated scientific orientation. The pinned diffsims raster maps +lab Y
to increasing image rows (down); its PNG is consequently not the same screen
axis convention as the structure view. Numerical reflection coordinates stay
in the common laboratory frame. Any comparison mirror/rotation must be stated
explicitly rather than silently flipping scientific data.

Hand-solvable cubic [110], hexagonal, nonorthogonal, negative-zone, roll and
partial-cell cases have separate synthetic checks, including actual diffsims
reflection coordinates and immutable request recovery. These are coordinate
tests, not proof of an experimental zone axis or unique phase.
