# PR #7/#8 integration: paused checkpoint

Paused at the user's explicit request on 2026-10-25 because another Agent may
also be operating DM. Do not resume desktop or host work without coordinating
exclusive ownership of the test session. No further DM input, STOP, close,
restart, plugin installation or removal was performed for this checkpoint.

## Repository state

- Checkout: `native-bridge-mvp`; branch `integration/native-gui-measurements-20261025`.
- Last fetched main: `77a02e2`, unchanged by this task.
- PR #7: `0417c17`, open against `feature/native-gui-roi` (`82564a7`).
- PR #8: `121cd9e`, open against the same base; it did not include #7.
- Local merge commit: `f1cf407`, retaining both PR histories and both sets of
  PROFILE enumeration/display tests.
- The integration fixes, export support, new tests and documentation are still
  **uncommitted working-tree changes**. Do not reset/clean them or rebuild from
  HEAD alone. No integration branch push or new PR has been made.
- PR #7/#8 and main were not merged, closed or otherwise modified on GitHub.

## Implemented working-tree changes

- Correct the merged C++ metadata signature and preserve exact owned PROFILE
  float64 and HISTOGRAM uint32 descriptors in DATASETS.
- Admit bins greater than source pixels; keep the independent 2..4096 budget.
- Correct MCP text to the actually supported `bin_index` axis. Strengthen
  source, count, binary64 encoding, native uint32 and retention validation.
- Preserve separate true-1D display groups and the PR #7 ownership regressions.
- Register HISTOGRAM in common capability dispatch, state actual optional
  dependencies and include its previously omitted C++ test target.
- Recheck destination descriptors and source metadata/intensity calibration
  around the native histogram call. This is not an atomic pixel lock.
- Reuse schema-1 NPY/sidecar handoff, encoding native counts as `<u4` and
  preserving binary64 wire bytes/hashes separately. Historical v1 receipts do
  not gain a retroactive source-invariance guarantee.
- Extend strict Python receipt identity to HISTOGRAM, with lazy argument
  conversion so unrelated tools do not evaluate absent histogram parameters.
- Add synthetic fixture, same-PID independent oracle and adversarial tests.
  Manual ROI freezing preserves its own new baseline and the original evidence.

## Evidence at the pause

Private evidence is outside the checkout under
`analysis/2026-10-25-pr8-integration/`; never commit machine identities, raw logs,
installation manifests or vendor inspection material.

| Scope | Actual result |
|---|---|
| Full C++ build and 13 offline suites | PASS; including PROFILE 520, HISTOGRAM 8542, profile selection 3021; rejection vendor calls zero |
| Full Node run | 196 PASS, zero failures/skips |
| Default v0.6 selftest | PASS, original 21-tool catalog |
| Initial complete Python run | 585 methods, 21 FAIL and 10 ERROR; preserve this run |
| Initial 21 Python failures | SUMMARY saw an intermediate eager histogram-argument conversion error; fixed, then SUMMARY 12/12 passed |
| Initial 10 Python errors | Six STOP-helper 10-second and four trial-oracle 15-second subprocess timeouts; separate from the conversion defect |
| STOP helper with original deadlines | 8/8 PASS |
| New measurement oracle negatives | 12/12 PASS |
| Final frozen-source full Python run | User-requested interruption of owned session; TERMINATED / INCOMPLETE, not PASS and not a completed regression FAIL |
| Fresh pinned actual host | Exact loaded DLL identity, independent baseline, six strict-original-ID PROFILE and two HISTOGRAM (8/64 bins over 24 pixels), QUERY/NPY and same-host source/GUI oracle PASS |
| Saved real outputs reopened after host exit | PASS for all eight packages; saved-file evidence only |
| Current-build SHOW/manual-ROI full loop/RELEASE/STOP/normal cleanup | HOLD; not supplied by earlier PR #8 evidence |
| Ordinary model-client acceptance | NOT_TESTED |

The real boundary fixture includes negative/fractional values, internal edges
and the exact requested upper endpoint. For its 8/64-bin cases, native results
matched the independent reference including the upper endpoint in the final
bin. This does not establish a physical intensity axis or every rounding case.

An earlier private PROFILE driver saved integer-valued coordinates as floating
NB2 wire tokens. The independent oracle correctly failed. Those original
records were not repaired. Known completed old outputs were explicitly released;
new operations with new pre-saved integer requests were separately accepted.
The original two histogram records remained valid and were reused unchanged.

## Host discontinuity and ownership

After the passing same-host observation and before manual measurement
processing, the original host exited with code `0xffffffff`. A different DM
process was observed later. The user states they did not close or reopen DM and
suspects another Agent may also be operating it. **Cause is unresolved.** No
matching Application 1000/1001/1002 event was found in the inspected interval;
that does not prove the absence of a vendor failure.

The subsequent readonly old-session ROIS request timed out with `sent:false`.
It was not automatically replayed. No new manual PROFILE or CROP was submitted.
The prepared `manual-freeze.s` binds the old PID/session and is now stale; do not
run it in a replacement host or reconstruct its baseline after the fact.

Only this task's launcher and its owned Node/test subprocesses were managed.
The integration launcher has no kill/close path. A readonly review found no
name-wide DM termination in the executed offline test sources; it did not
identify the exit cause. PROFILE retains output images and metadata, not ROI
pointers or a GUI-change listener; this is not a general vendor-safety proof.

The test DLL was installed through a dedicated ownership manifest before the
original host started. This task has **not removed it**. Another Agent may have
changed the live state: recheck all processes, the manifest and current hashes
before any future installation/removal. Never replace a loaded DLL or clean a
plugin directory.

## First work after an explicit resume

1. Coordinate exclusive DM ownership, fetch again and inspect all branch and
   dirty-worktree changes. Preserve this checkpoint and private snapshots.
2. Fix the remaining reviewed contract hole: HISTOGRAM's shared 1D SHOW
   validator currently accepts a complete or changed axis, while creation only
   admits exact `bin_index`. Enforce the same invariant and add direct/QUERY
   negative tests; do not enable an unverified setter.
3. Finish a frozen-source full Python run with unchanged deadlines. Preserve
   original failures, the interrupted run and individual targeted passes.
4. Establish a new explicitly prepared idle synthetic host/session. Do not reuse
   old IDs or claim cross-restart recovery. Repeat fresh manual selection,
   native processing, exact-document SHOW, export and independent release/STOP/
   after-close checks, then normal exit and manifest-owned removal.
5. Reconcile current documentation, review the final diff, commit/push the
   independent integration branch and open a review PR. Do not merge main.

The intensity-axis setter remains unbound. The official script is evidence of
script-level use, not a C++ format-enumeration definition; the earlier reported
setter failure lacks its exact saved readback in the available private archive.
See [axis audit](HISTOGRAM_AXIS_AUDIT.md) and [histogram handoff](NATIVE_HISTOGRAM.md).
