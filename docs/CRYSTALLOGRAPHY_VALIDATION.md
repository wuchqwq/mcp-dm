# Crystallography companion qualification

These checks qualify the explicit external companion over saved files, not a
new DM operator or an experimental material. Runtime code/tests were frozen for
regression. The native plugin, Node catalog, default v0.6 implementation and GMS
installation were not changed by this work.

| Scope | Result |
| --- | --- |
| New external companion tests | PASS, 97 methods: capture, geometry, detection, cubic/hexagonal joint candidates, actual ASE CIF parsing and file workflow |
| Node complete regression | PASS, 206/206, zero skipped; existing Windows synthetic host and scientific fixture enabled |
| Default backend selftest | PASS, existing 21-tool behavior |
| Full Python regression | PASS, 701/701, zero errors/failures/skips; original deadlines unchanged |
| Blind independent Agent over saved synthetic inputs | PASS, both automatic run/verify workflows completed without additional human input; no source/test/answer access |
| Independent withheld-truth check of blind results | PASS, centre/spacing and fixed hexagonal reference checks; ambiguous alternatives retained; input files unchanged |
| Fresh real DM / experimental diffraction or fringe task | NOT_TESTED by this companion change |
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

Keep historical native FFT numerical FAIL, Unicode NOT_QUALIFIED and earlier
native trial/regression records separate. No threshold in those records was
relaxed. Next qualification should use an authorized bounded diffraction
capture/known standard and compare the actual researcher task against manual
DM measurement, then exercise an ordinary client end to end.
