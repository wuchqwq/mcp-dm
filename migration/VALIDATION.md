# Migration preparation — executed evidence

Source inputs are the pinned #46 (`e6f1301`) and GUI stack #50 (`a158b1a`) named
in `ownership.json`. Tests run on exported candidates, not just imports from the
original combined repository. No private sample, GMS host or vendor runtime is
used. The final CI records its own exact recipe/source tree and file hashes in
the downloadable candidate manifests.

## Local checks completed

| Scope | Result |
| --- | --- |
| Migration safety over disposable Git fixtures | 21 PASS, 0 FAIL |
| Final scientific candidate `npm test` | 195 PASS, 0 FAIL, 4 explicit opt-in SKIP |
| Final DM-only candidate `npm test` | 66 PASS, 0 FAIL, 1 explicit C++ surrogate SKIP |
| Original/exported full MCP definitions + instructions, both DM backends and science optional modules; timeout guard | 5 PASS, 0 FAIL |
| Real exported science stdio/Python round trip | PASS |
| Selected exported Python AST and JavaScript syntax | PASS |

Counts are separate scopes, **not summed** into a unique test total. The default
Node science run deliberately leaves the pre-existing extended real-provider
HTTP tests opt-in. Native surrogate/actual GMS acceptance is not inferred.

The actual scientific round trip creates a public synthetic two-frame uint16
TIFF, selects a frame, uses independently supplied signed XY scale, computes a
non-square ROI FFT, measures a known frequency vector, exports complex128 NPY,
checks it against a direct-sum DFT (not a second np.fft call), revises only the
display, reconnects and recovers the original request, and opens the local panel
HTTP page. Source TIFF and exported scientific bytes remain unchanged. This is
not a browser-gesture or model-vision claim.

For an earlier equivalent candidate, the original source checkout/integration
paths and the peer provider directory were temporarily absent during the
independent science round trip and DM catalog/protocol tests; both still passed.
The final packaging adds an exact-match, provenance-recorded panel configuration
adaptation rather than editing the parallel GUI branch. The final candidate was
re-exported and its catalog/unit/scientific checks were run again.

## Failures and exclusions retained

The first static extraction attempt refused `examples/crystallography_demo.py`
because that historical demo imports the DM mock bridge. It is intentionally
excluded from the standalone package; the actual independent kernels and the
new synthetic scientific smoke are retained. The checker was not weakened.

An additional extended HTTP run exceeded the container call's initial 60-second
wall-clock bound and was not counted as a pass. Its 220-second bounded follow-up
also timed out (exit 124): the reflection-table/revision, uncalibrated-frame and
statistics/profile checks completed, but the full extended sequence did not.
The overall supplemental run is INCOMPLETE, not PASS, and is not folded into the
default counts. No timeout, scientific tolerance or assertion was relaxed to
make it green. These optional extended tests are not in the lightweight CI.

## Not tested by this change

Actual macOS or Windows device/client behavior, live DigitalMicrograph/GMS,
new native ABI qualification, a real specimen, model seeing an image, complete
browser pointer interaction, optional ASE/diffsims numerical execution, remote
MCP/data transfer and relocation of historical workspaces. Existing qualified
scopes and historical failures are unchanged.

## Reproduction

Run the handoff in `README.md`, then `npm test` in each exported directory.
In the science candidate, install the existing image requirements in a separate
Python environment, set absolute `MICROSCOPY_PYTHON`, and run
`npm run test:science`. For exact catalog comparison set absolute
`SPLIT_SOURCE_ROOT` (the isolated integration tree) and `SPLIT_OUTPUT_ROOT`
(the export root), then run `node --test tests/repository-split-catalog.test.mjs`
from the preparation checkout. No full suite or native build is triggered.
