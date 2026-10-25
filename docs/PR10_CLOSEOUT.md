# PR #10 closeout — 2026-10-25

The maintainer authorized consolidating the current PRs and moving the next task to diffraction/lattice-spacing analysis. PR #10 is the single integration path to main; #7, #8 and #9 are superseded, not independently re-merged. Their original head commits are verified ancestors of `217597e195abf6fbca7a53dbcb49235787d695fa`. Branches and original evidence are retained. Compatibility-generator Draft #3 stays deferred.

## New independent evidence

An isolated Windows hosted run checked the **unchanged** runtime/test source at `217597e195abf6fbca7a53dbcb49235787d695fa`, tree `97e1c6e2f1d3451f200d46b3815ffb68e8d12a3b`:

[Full run and logs](https://github.com/wuchqwq/mcp-dm/actions/runs/40183214845)

| Scope | New result |
|---|---|
| Native DLL compilation and all 13 C++ offline executables | PASS; no Gatan runtime loaded |
| Windows synthetic named-pipe transport | 13 PASS |
| Complete Node suite, including the current synthetic C++ outputs | 206 PASS, zero failed/skipped |
| Default backend mock | 21 PASS |
| Complete Python unittest run 1 | 604 PASS, zero failed/errors/skipped |
| Complete Python unittest run 2, same fixed source/environment | 604 PASS, zero failed/errors/skipped |
| Tracked source/index after tests | Unchanged |

The two full Python runs were scheduled in advance, not retried until green. All original test deadlines were retained; no test was excluded or patched. The recorded environment uses Node 22, external Python 3.11, and LLVM-MinGW 20250528 / Clang 20.1.6. The dependency list and full logs are retained with the run. Expected fault-injection diagnostics printed after the unittest summary are not failed assertions; each run separately reports all 604 methods `ok` and `OK`.

A supplementary local Linux Node run passed 204 cases with its two existing Windows/cross-language cases skipped. This does not replace the zero-skip Windows run.

## What this does not establish

The previous maintainer-machine complete Python run remains **FAILED** with five subprocess deadline errors. Its cause is still unresolved. The new clean-host passes show that the error did not reproduce in this environment; they do not prove a root-cause fix on the original machine. Preserve that distinction if it recurs.

No user workstation was accessed, no DM session was started/stopped, and no original experiment was processed during this closeout. This is independent engineering evidence, not new real-host qualification. Existing limited actual-DM/manual-selection records keep their original scope. Historical FFT accuracy FAIL, unsupported builds/types, and ordinary model-client NOT_TESTED are unchanged.

Bar-style admission remains disabled. Default v0.6, exact native module fingerprints, source protection, result ownership and request recovery are unchanged. This merge is an opt-in experimental integration, not a stable native Release.

## Next work

Only documentation changed after the tested source: the next milestone and human-facing roadmap. The active priority is [diffraction calibration, d spacing/angles and bounded cubic candidates](DIFFRACTION_NEXT_STAGE.md), tracked in [Issue #11](https://github.com/wuchqwq/mcp-dm/issues/11). General profiles/histograms remain available as building blocks; polishing them is not the next product milestone. Existing historical acceptance records are not rewritten to describe these plans as implemented features.
