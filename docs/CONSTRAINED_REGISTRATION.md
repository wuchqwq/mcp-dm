# Constrained reciprocal-geometry registration proposals

`structure_register` uses saved `image_measure` records and a saved diffsims
simulation to propose an in-plane alignment. It is optional and composable;
it does not choose an analysis sequence, find peaks, identify a phase or
replace experimental calibration.

Supply `measurement_paths`, `fit_correspondences` and a separate
`validation_correspondences` list. Each correspondence has an exact
`measurement_index` and a three-index `hkl` present in the unrastered simulation
table. Record the correspondence authority in
`confirmation:{source,source_text}`: `user_confirmed` means the caller is
reporting the researcher's statement; `synthetic_fixture` is reserved for
synthetic reference inputs. This is recorded scientific provenance, not an
authentication mechanism. An Agent hypothesis is not silently upgraded to a
user confirmation.

## One estimated degree of freedom

The first scope estimates only a proper two-dimensional rotation. Experimental
scale remains exactly 1, translation remains exactly zero, and distortion is
absent. `screen_axes:{flip_y,basis}` declares a **known, fixed** screen-axis
mapping. The tool does not try both mirrors and select whichever fits better.
Unknown experimental crystal orientation is distinct from this known display
convention. Correct the explicit image centre and remeasure before fitting;
registration cannot hide a centre error in an arbitrary translation.

The column-vector convention is
`q_comparison = Rccw @ diag(1, flip_y ? -1 : 1) @ q_experiment`.
`rotation_matrix_xy` is proper with determinant +1.
`comparison_matrix_xy` also includes the caller's fixed screen reflection, so
its determinant can be -1. Neither is a three-dimensional crystal orientation
or a substitute for the shared [UVW orientation](STRUCTURE_ORIENTATION.md).

At least two non-collinear confirmed fit reflections are required in both the
experimental and simulated transverse coordinates. A single vector can specify
a formal angle, but supplies insufficient independent directional constraints
for this tool's admission. Numerical rank and angle-uniqueness guards refuse
unresolved inputs rather than inventing an angle. They do not replace or widen
`max_residual_inv_angstrom`, the caller's fixed geometric tolerance.

The implementation uses [SciPy's SVD factorization](https://docs.scipy.org/doc/scipy/reference/generated/scipy.linalg.svd.html)
for the determinant-constrained orthogonal Procrustes construction. Ordinary
[orthogonal Procrustes](https://docs.scipy.org/doc/scipy/reference/generated/scipy.linalg.orthogonal_procrustes.html)
also permits a reflection, so it cannot be used without this proper-rotation
constraint. Uniform numerical normalization prevents covariance underflow;
it is not an estimated physical scale. Residuals are evaluated in the original
cycles/angstrom coordinates by the existing comparison code.

## Fit evidence is not validation

Fit and held-out lists must be disjoint by measurement identity, original peak
anchor and theoretical HKL. Renaming a measurement cannot turn the same peak
into validation. Coincident simulated projections, Friedel mates and conjugate
experimental vectors cannot count as independent held-out constraints. The
held-out list itself cannot double-count those equivalents either.
The direct beam or a purely longitudinal simulated vector cannot supply a
fit or held-out transverse reflection, even with a large declared tolerance.

Adjacent binary64 anchors/projections are reported as unresolved independence,
rather than promoted to a new independent reflection by a one-ULP difference.
This machine-representation warning is not a localization uncertainty or a
change to the caller's tolerance. General experimental/statistical independence
and resolving power remain unverified without suitable uncertainty evidence.

The result keeps `fit_evidence`, `validation_evidence`, their statuses and
`held_out_validation_passed` separately. No held-out list means
`validation_status:"not_tested_no_held_out"` and a null validation outcome.
Inconsistent fit evidence cannot borrow a successful held-out residual to claim
success. Bad held-out reflections do not refit the angle or scale.

The full existing [reflection comparison](REFLECTION_COMPARISON.md) remains in
`comparison`, including unmatched reflections, competing in-tolerance matches
and unused observations. Every matched/unused experimental row identifies its
fit, held-out or unassigned role. The inferred rotation is unique only for the
fixed correspondences and admitted numerical constraints; scientific indexing,
phase identity and alternative structures/orientations are not uniquely proved.

## Correct continuation and history

All measurements must share one immutable scientific source plane/frame/ROI,
coordinate space, active calibration record and exact centre version. Current
records use a version-2 binding of their verified `scientific_grid_identity`:
changing gamma, annotations or a display-only frequency window does not change
that identity. Original view IDs remain in each observation's provenance.
Different captures/frames/FFT producers, array hashes or scientific ROI extents
still reject. Historical records without a grid use the old strict source-ID
contract; they cannot be mixed with grid-bound records. An old saved proposal
remains historical; make a new proposal before continuing with the v2 binding. The
proposal records `experimental_geometry_binding`, including the ordered point
geometry and a hash. A scale, centre, source or point revision needs fresh
measurements and a new proposal; the old proposal remains historical.
An explicit reference to a saved proposal cannot silently apply it to a
different current geometry. Original arrays, calibration records, simulated
reflections and original files are never changed by this tool.

The same physical-unit/DC checks and simulation-enumeration qualification used
by comparison remain mandatory. This adds no permission for uncertified skew
cells, arbitrary imported reflection JSON, unknown scale, or a guessed beam
centre. It performs no image resampling or hidden backend fallback.

Validation is geometric only. Real-space HRTEM/ptychography FFT and SAED do not
share a general intensity-formation model; normalized PNG similarity, kinematic
intensity agreement and a small positional residual are not unique phase proof
or dynamical-scattering validation.
