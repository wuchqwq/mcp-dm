# Explicit experimental–simulation reflection comparison

`structure_compare` combines existing tools without prescribing an analysis
sequence. Its `object_id` is an actual saved diffsims simulation. Supply the
`manifest_path` values returned by `image_measure` or `image_remeasure` through
`measurement_paths`, declare `experimental_kind`, and give explicit registration
parameters or an exact saved `structure_register` proposal, plus a
reciprocal-coordinate residual tolerance. See [continuing an analysis](CONTINUING_DIFFRACTION.md)
for selected current wrappers, correction/history semantics and a connected
tool example. No peak finding,
scientific arrays, PNG similarities or Agent-written temporary coordinate JSON
are substituted for those measurements.

The first scope is 1–32 **DC-to-peak** physical reciprocal measurements. A saved
real-space FFT uses `frequency_cycles_per_pixel`, mathematical DC `[0,0]` and an
active real-space source calibration. A calibrated native reciprocal scalar
capture uses `source_array_indices` and its explicitly recorded mathematical
or raw-origin DC identity. Two arbitrary peaks only define a difference vector;
they cannot be passed as an absolute reflection. Unknown, withdrawn, stale or
contradictory calibration dependencies are refused for physical comparison.
Pixel-domain observation and measurements remain usable independently.

The tool validates the saved measurement manifest against its original
committed image-workspace journal, checks the points/signed calibration against
the physical vector, cross-checks original requested points, parent identity
and explicit/default coordinate domain, and fixes the exact original bytes and hashes in the new
comparison record. It retains calibration ID, revision, source and coordinate
domain. This establishes internal evidence consistency, not independent
metrological accuracy. An old immutable measurement retains its active-at-the-
time calibration: later revisions are not discovered through a hidden global
state. After correction or withdrawal, select the new calibration wrapper and
remeasure; old exports remain historical.

All comparison vectors use cycles/Å (no `2π`). For example, 2 cycles/nm becomes
0.2 cycles/Å; the original units and conversion factor remain in the result.
Positive/negative and unequal XY scales are preserved. With DC as the second
point, the difference vector is explicitly reversed to obtain DC→peak.
Nonzero unit-conversion or registration components that underflow to zero are
refused. Reciprocal periods must remain finite; residual lengths use `hypot`
and angular comparisons normalize vectors before their dot/cross products.
These numerical guards do not relax the caller's geometric tolerance.

Registration requires all of:

- `rotation_deg`: active counterclockwise XY rotation;
- `scale`: explicit positive comparison scale (use 1 when intended);
- `translation_inv_angstrom`: explicit XY offset;
- `flip_y`: explicit reflection of the experimental Y component;
- `basis`: the supplied alignment evidence or identity assumption.

The transform is `q_compare = scale * Rccw @ diag(1, flip_y ? -1 : 1) @ q_exp + t`.
The source calibration and measurements are never changed. Comparison does not
fit parameters; optional [constrained registration](CONSTRAINED_REGISTRATION.md)
is a separate explicit tool. Identity parameters are still an assumption unless their
basis has been independently checked; the tool does not mark registration
verified merely because it can apply it.

Optional `correspondences` give explicit `measurement_index`/HKL pairs. Otherwise
SciPy performs a one-to-one assignment within the caller's fixed tolerance,
first maximizing the number of feasible matches, then minimizing their total
reciprocal-coordinate residual. Normalized bounded costs and dummy assignments
keep distant spots from being forced to match; a smaller partial assignment
cannot defeat a complete in-tolerance one merely because its residual is lower. Every
in-tolerance candidate and ambiguity is retained, together with unmatched
experimental and simulated reflections. A resource overflow is refused without
truncating candidates. An assigned HKL is not a uniquely established HKL.
Different structures/orientations can be compared through independent records.

Results include XY reciprocal residuals, projected signed-angle residuals,
original/registered experimental projected periods, simulated projected periods
and separate full-3D simulated lattice d-spacings. These are distinct quantities:
projection and Ewald-sphere excitation need not make a simulated 3D reciprocal
vector exactly transverse. Localization/calibration covariance is not converted
into a statistical confidence. The tool never reports unique phase identity.

Intensity comparison is deliberately absent. Real-space HRTEM/ptychography FFT,
SAED and a kinematic diffsims pattern have different intensity-formation
mechanisms. Numerical simulated intensities are retained as evidence, while
the library's qualitative raster/PNG is not used for geometric matching.
Existing unqualified skew-cell simulation ranges remain refused; structure
viewing and valid crystal geometry are independent of that restriction.
