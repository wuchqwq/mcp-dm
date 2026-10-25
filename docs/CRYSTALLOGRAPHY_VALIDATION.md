# Crystallography companion qualification

These checks qualify the explicit external companion and the bounded handoff
from existing DM native operations. They do not establish an experimental
material or add a native operator. The native plugin, Node catalog and default
v0.6 implementation remain unchanged. New dependencies stay outside GMS Python.

The initial companion baseline below is historical; its full-suite PASS must
not be substituted for the current revision's regression result.

| Scope | Result |
| --- | --- |
| Initial external companion tests | Historical PASS, 97 methods: capture, geometry, detection, cubic/hexagonal joint candidates, actual ASE CIF parsing and file workflow |
| Initial Node complete regression | Historical PASS, 206/206, zero skipped; existing Windows synthetic host and scientific fixture enabled |
| Initial default backend selftest | Historical PASS, existing 21-tool behavior |
| Initial full Python regression | Historical PASS, 701/701, zero errors/failures/skips; original deadlines unchanged |
| Current companion tests | PASS, 103 methods, including all 19 detector tests and six added DC/localization controls |
| Current Node complete regression / default backend selftest | PASS, 206/206, zero skipped; Windows synthetic-host/scientific fixtures executed; default 21-tool selftest PASS |
| Current full Python regression | FAILED, 707 methods, three existing 15-second subprocess timeouts, zero assertion failures/skips. One installation-recovery method and two STOP-identity subcases timed out; cause is not established |
| Subsequent serial diagnosis of the affected methods | PASS, 2/2 methods, including the existing 20 STOP-identity negative subcases; original deadlines and source hashes unchanged. This does not replace the complete failed run |
| Blind independent Agent over saved synthetic inputs | PASS, both automatic run/verify workflows completed without additional human input; no source/test/answer access |
| Independent withheld-truth check of blind results | PASS, centre/spacing and fixed hexagonal reference checks; ambiguous alternatives retained; input files unchanged |
| Actual synthetic DM FFT → scalar power → MCP READ → NPY → companion | PASS, limited scope: two independently prepared inputs yielded the expected six/eight automatic peaks with zero coordinate error; same-host numerical/source and saved-file checks are separate from phase indexing |
| Authorized bounded ADF → native FFT/power → complete region handoff → companion | PASS for actual data handoff, automatic measurement and preserved evidence; no experimental phase-identification claim |
| Current trial result lifecycle / normal host exit / manifest-owned cleanup | PASS: hidden results invalid after release/STOP, shown documents retained exact results; explicit owned document close followed by independent idle invalidation; normal host exit code 0 and manifest-only DLL removal |
| Ordinary MCP-only model client | NOT_TESTED; the current companion requires explicit filesystem/process execution |

Independent controls include signed/anisotropic scales and origins, nm versus
angstrom, radians versus cycles, off-centre/cropped mathematical FFT axes,
out-of-ROI DC, missing absolute calibration, noise, repeated/collinear points,
unmatched observations, rotation/mirroring and F/I/P geometric ambiguity.
Hexagonal checks include basal, prismatic and oblique zones, four-index W
conversion, non-ideal c/a, a common proper orientation and fixed reference
parameters that cannot be silently refitted. Basal-only data retain their
unconstrained c/a alternatives.

The automatic centre negative controls include missing opposite reflections,
collinear pairs, competing centres and two separated symmetric subpatterns.
An initial two-subpattern false READY was caught by an independent negative;
the implementation now explicitly returns NEEDS_REVIEW for that case. Other
initial integration failures, including incomplete output/inventory validation,
remain in private logs; corrected passing runs do not rewrite them.

The current detector excludes an explicitly supplied centre disk before
normalization, Gaussian smoothing, thresholding and localization. It fills only
an independent localization working copy with the unmasked median and records
the mask evidence. This prevents dominant FFT DC and its smoothing halo from
setting the scale for nearby reflections. Mathematical FFT DC still comes from
the recorded native frequency grid; source arrays and display PNGs are not
substituted or modified. Focused controls cover this admission boundary; the
current full regression remains distinct from those targeted checks.

File checks reject tampered numerical bytes, metadata/receipt/session identity,
forged frequency axes, missing outputs, rehashed inconsistent request identities,
an omitted input inventory and changed original capture files. There is no
overwrite or automatic replay. A completion marker is written last; a partial
directory has no completed qualification. Verification establishes internal
saved-file consistency, not independent authenticity of a live host.

The blind tasks use external Gaussian point fixtures, including a case without
a bright central beam. Arbitrary spot intensities are not electron scattering
simulations. The runtime never reads the separate answer record. This is an
Agent saved-file usability trial, not a substitute for DM numerical acceptance,
live client acceptance or experimental phase identification.

The newer actual-host continuation instead uses the existing fingerprint-gated
native FFT and squared-magnitude operators, explicit saved request identities,
real MCP READs and the existing schema-1 scalar handoff. Independently prepared
synthetic values check the positive-exponent centered forward transform against
the unchanged historical forward bound and check power against stored complex
components. Authorized experimental regions use complete bounded multiblock
handoff; the external companion consumes the exact saved bytes. Signed spatial
scales, mathematical frequency axes and the separate raw DM half-bin calibration
are preserved. Detailed source identities, measurements, coordinates, reference
comparisons and earlier oracle failures remain private.

The ADF continuation records automatic peak locations, spacings, angles and
fixed-reference alternatives. It does not turn limited frequency resolution,
single-spot agreement, a generic FCC/HCP metric or the user's expected phases
into proof of a material. Reference atomic-basis diagnostics are separate from
the common-zone geometric comparison; ideal basis cancellation is not a hard
experimental rejection. There is no external FFT fallback. This trial does not
add IFFT or round-trip accuracy qualification, and the historical native FFT
numerical FAIL and its original thresholds remain unchanged.

Keep historical native FFT numerical FAIL, Unicode NOT_QUALIFIED and earlier
native trial/regression records separate. No threshold in those records was
relaxed. Further qualification should use a known diffraction standard and
compare the actual researcher task against independent manual DM measurement,
then exercise an ordinary client end to end.
