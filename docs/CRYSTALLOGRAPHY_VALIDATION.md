# Crystallography companion qualification

These checks qualify the explicit external companion and the bounded handoff
from existing DM native operations. They do not establish an experimental
material or add a native operator. The native plugin, Node catalog and default
v0.6 implementation remain unchanged. New dependencies stay outside GMS Python.

The records below describe distinct revisions and scopes. The initial companion
baseline and the later 707-test timeout run remain historical. PR #12 at
`c8723c1` reports a newer full Python 715/715 PASS, Node 214/214 PASS, 13 C++
offline executables PASS and a passing default-backend selftest. These newer
figures are taken from the PR author's closeout report, not a fresh independent
run of the candidate by this documentation-only review. An earlier full-suite
FAIL is preserved even when a subsequent complete run passes; its underlying
timeout cause has not been established.

| Scope | Result |
| --- | --- |
| Initial external companion tests | Historical PASS, 97 methods: capture, geometry, detection, cubic/hexagonal joint candidates, actual ASE CIF parsing and file workflow |
| Initial Node complete regression | Historical PASS, 206/206, zero skipped; existing Windows synthetic host and scientific fixture enabled |
| Initial default backend selftest | Historical PASS, existing 21-tool behavior |
| Initial full Python regression | Historical PASS, 701/701, zero errors/failures/skips; original deadlines unchanged |
| Earlier post-localization companion tests | Historical PASS, 103 methods, including all 19 detector tests and six added DC/localization controls |
| Earlier post-localization Node complete regression / default selftest | Historical PASS, 206/206, zero skipped; Windows synthetic-host/scientific fixtures executed; default 21-tool selftest PASS |
| Earlier post-localization full Python regression | Historical **FAILED**, 707 methods, three original 15-second subprocess timeouts, zero assertion failures/skips. One installation-recovery method and two STOP-identity subcases timed out; cause is not established |
| Latest PR #12 reported full Python regression | **Reported PASS**, 715/715, zero failures/skips; original deadlines unchanged; not independently rerun in this documentation-only review |
| Latest PR #12 reported full Node and default selftest | **Reported PASS**, 214/214 Node, zero failures/skips; default backend selftest PASS; not independently rerun in this review |
| Latest PR #12 reported C++ offline suites | **Reported PASS**, 13 test executables; offline/surrogate evidence, not an additional live-host qualification |
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
later reported full regression, historical failed full regression and targeted checks remain separate evidence.

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
