# Native candidate integration plan

This is a review plan, not a merge or release approval. Preserve the complete
SHOW candidate, trial scripts and offline tests for review. Their real-host
desktop/ownership acceptance remains HOLD; synthetic success does not remove
that gate. The default Python backend and its 21-tool catalog stay unchanged.
No merge, rebase, checkout replacement, installation or DM action was performed
to prepare this document.

## Compared Git snapshots

The local, already-fetched refs inspected for this plan were:

| Ref | Commit | Role |
|---|---|---|
| `origin/main` | `64b5124` | Reviewed native core integration, including `dd71601` |
| `feature/native-bridge-mvp` and its remote ref | `6837bab` | Later raw-mean/SHOW/trial candidate |
| Merge base | `3c9715c` | Shared reviewed native MVP snapshot |

Main already contains `0f74c82`, `2623425`, `3c9715c` and `dd71601` by ancestry.
Do not import the original native core, crop implementation or mandatory crop
ID safeguard again. Main's follow-up requires `dm_crop.request_id` before
dispatch and retains optional IDs for existing read-only tools.

The feature has four commits after the common base: `27895bc`, `4e68b55`,
`32adcd1`, `6837bab`. Main has `dd71601` and its merge commit on the other
side. `git cherry` marks all four feature commits `+`, and stable whole-commit
patch IDs differ. That proves absence of identical complete patches, not
absence of overlapping changes: `27895bc` mixes the already-integrated crop
ID rule with new implementation and tests.

| Commit | Stable patch ID prefix | Contents relevant to the next review |
|---|---|---|
| `dd71601` | `884d8780709f` | Main's crop ID safeguard, partial-integration notes and installer test correction |
| `27895bc` | `75586ff2e91a` | Mixed recovery-ID work, raw mean policy, SHOW implementation and tests |
| `4e68b55` | `7b10531464b5` | Trial creation/acceptance/oracles and current HOLD documentation |
| `32adcd1` | `b7a6a9528adc` | C++/Node synthetic E2E and oracle fault-injection hardening |
| `6837bab` | `e10119cda9fe` | Offline evidence limits, Unicode investigation and trial documentation |

These identifiers describe public Git content, not private execution artifacts.
Recompute the comparison after either ref advances. The closeout described
below and this document are later follow-ups, outside those recorded
committed tree/patch comparisons; preserve their final frozen versions too.

Read-only commands for repeating the inventory:

```text
git status --short
git rev-parse origin/main origin/feature/native-bridge-mvp
git merge-base origin/main origin/feature/native-bridge-mvp
git log --left-right --cherry-mark --oneline origin/main...origin/feature/native-bridge-mvp
git cherry -v origin/main origin/feature/native-bridge-mvp
git diff --name-status origin/main origin/feature/native-bridge-mvp
git diff origin/main origin/feature/native-bridge-mvp -- <reviewed-paths>
git show --format= --binary <commit> | git patch-id --stable
```

Use the two-endpoint tree diff for the final reconciliation. A three-dot diff
shows only changes since the merge base and conceals main's later safeguards.
Neither diff is an instruction to apply every hunk without review.

## Net additions to retain

| Area | Feature additions beyond the main baseline | Paths to review together |
|---|---|---|
| Raw native mean | Separate supported float32/2D/budget eligibility from recognized unusable spatial calibration; preserve nulls/issues, raw intensity semantics, finite-result and native/ABI errors. Dataset capability metadata agrees. Crop calibration stays strict. | `dm_adapter.cpp`, raw-mean cases in `adapter_tests.cpp` |
| SHOW candidate | Exact retained-crop ID/pointer lookup, typed document/window calls, additional pinned-module and executable-entry checks, temporary reference cleanup, explicit no-file/no-model-vision claims. STOP releases plugin crop ownership without closing shown documents. | `dm_adapter.cpp`, `show_contract.hpp`, `core.cpp`, `core_tests.cpp`, SHOW cases in `adapter_tests.cpp` |
| MCP facade | Add NB1 SHOW with one explicit numeric image ID and saved request ID; validate completed delivery/image identity. Keep main's required crop ID and extend the explicit-ID policy to newly added side-effect tools. Native catalog grows from five to six; no Python fallback. | Root `server.mjs`, `lib/native_bridge.mjs`, `tests/native-bridge.test.mjs`, `tests/native-mcp.test.mjs` |
| Acceptance clients | Check required schemas and permit the sixth native tool without automatically invoking it in the core acceptance client. | `accept_mcp.py`, `accept_crop_mcp.py` |
| Prepared trial | Prepared synthetic inputs and strict native acceptance, independent pixel/calibration/source/document checks and later final-release checks. | `TRIAL_ACCEPTANCE.md`, `accept_trial_mcp.py`, `create_trial_fixture.py`, `verify_trial.py`, `verify_trial_closed.py` |
| Unicode diagnostic | Keep the prepared diagnostic and the distinction between legacy Python bytes/text, native UTF-16/UTF-8, units and independent UI truth. Interoperability remains NOT_QUALIFIED. | `create_unicode_fixture.py`, `../ABI_NOTES.md`, trial instructions |
| Synthetic recovery E2E | Actual Node facade/transport, Windows pipe, C++ Core/message window and fake adapter; controlled running/cancel/timeout events, new-client QUERY, immutable/conflicting IDs, creation counters and normal STOP. No Gatan module or real document is involved. | `fake_adapter.cpp`, `fake_host.cpp`, root `tests/native-e2e.test.mjs` |
| Oracle fault suite | Execute the actual one-shot scripts against an isolated fake DM API, with independent arrays, passing controls and exact-error failures. Keep original failures separate from corrected tests. | Root `tests/test_native_trial_oracles.py`, both trial verification scripts |

The subsequent closeout adds these changes to that committed snapshot:

| Closeout group | Final contracts to retain | Additional paths |
|---|---|---|
| Actual oracle process | Direct `os.getpid()` binding rejects another host's internally consistent receipts; synthetic tests explicitly simulate the process, with no production override | Both trial oracles and `tests/test_native_trial_oracles.py` |
| Saved STOP identity | Existing STOP helper persists the exact original request before transport; strict oracles match ID/session/op/args/PID/wire and reject ambiguous duplicate keys. Missing old records remain UNVERIFIED | `stop_native.py`, both trial oracles, root `tests/test_native_stop_helper.py` |
| Preserved-session observations | Explicit legacy mode uses separate files and is always UNVERIFIED; strict qualification cannot consume those observations as PASS | Both trial oracles, `UNLOCK_CHECKLIST.md`, operator instructions |
| Typed Unicode evidence | Exact bytes or text/code points, retained encoding exceptions and failed diagnostics; never a Unicode qualification claim | `create_unicode_fixture.py`, root `tests/test_native_unicode_probe.py` |

These changes belong with their corresponding implementation and tests. Do
not use the older oracle or diagnostic from the recorded snapshot while
claiming the current closeout contracts.

Paths without a root prefix in this table are in this MVP directory. The
candidate's additional module gate runs during native initialization: review
its effect on all native operations, not just SHOW. It does not broaden build
compatibility or provide vendor exception isolation or general host admission.

Documentation to reconcile includes:
`AGENTS.md`, `README.md`, `README.en.md`, `ROADMAP.md`,
`experiments/native-bridge/README.md`, `experiments/native-bridge/ABI_NOTES.md`,
`experiments/native-bridge/RESULTS.md`, and MVP `HANDOFF.md`, `INSTALL.md`,
`README.md`, and the current `TRIAL_ACCEPTANCE.md`. The acceptance guide's
replacement is a follow-up to the recorded snapshots. Reconcile their current-candidate statements
with main's reviewed-core history; do not replace one scope with the other.

## Main changes that must survive reconciliation

1. **Keep the mandatory crop ID once.** Main already requires
   `image_id`, `rect`, `request_id` and tests missing/invalid IDs before native
   dispatch. Preserve those assertions while adding the feature's stronger
   side-effect guard and recovery tests. ROI-negative tests still need a valid
   saved ID so they reach the ROI check.
2. **Keep the installer test fix.** Main's `tests/test_native_install.py`
   checks absolute paths and `os.path.samefile`; the feature still has the old
   string-equality assertions. A blind feature-tree copy reverses that Windows
   short/long-path correction. There is no feature installer implementation
   change to import.
3. **Keep `docs/NATIVE_MERGE_SCOPE.md`.** It was added only on main. Its apparent
   deletion in the main-to-feature tree diff is branch divergence, not an
   intended removal. Preserve the historical reviewed-core decision and add a
   clearly scoped later-integration note if a new candidate is approved.
4. **Preserve current HOLD.** Historical core/crop numerical and cleanup
   acceptance is separate from this candidate's native SHOW receipts. Pending
   desktop/document, current pixel/source, post-STOP lifetime, final release,
   normal exit/removal checks must not become PASS by integration.

Six paths changed on both branches since the common base:
`server.mjs`, `tests/native-mcp.test.mjs`, `README.md`, `README.en.md`, and MVP
`README.md`, `HANDOFF.md`. These need semantic reconciliation. The main-only
installer test and scope document need explicit preservation. No merge
simulation was run; this is a conflict-risk inventory, not a claim about exact
automatic conflict markers.

## Why whole-commit cherry-picks are insufficient

- `27895bc` contains shared crop-ID semantics and overlapping facade/test hunks
  together with raw mean and SHOW. Its whole patch ID cannot identify the
  already-integrated subset. Import only the net additions against main.
- `4e68b55` depends on the later mean/SHOW catalog and introduces the initial
  trial oracles. Do not select its scripts while omitting subsequent oracle
  corrections or overwrite main's partial-integration notes.
- `32adcd1` assumes the matching SHOW parser/facade, synthetic host controls and
  trial-script shapes. Taking the E2E/fault tests alone is not a valid port.
- `6837bab` documents those implementations and evidence boundaries; it neither
  implements them nor closes Unicode/desktop qualification. It shares document
  context with main's integration notes.
- New follow-up patches may overlap the same oracle, diagnostic and test paths.
  Review them against the frozen feature source and then the latest main. Do
  not blindly append them after a cherry-pick and assume earlier evidence still
  validates the resulting tree.

## Proposed future review sequence

This sequence is for a later explicitly authorized integration. Do not reset
the feature branch or force-push it to main's baseline.

1. Recheck the latest main, feature and working-tree state. Freeze the complete
   proposed feature revision after follow-up contracts/tests finish. Record
   source revisions separately from run artifacts; do not rewrite old evidence.
2. Start a future review branch from that latest main. Use a path/hunk allowlist
   derived from the two-endpoint diff above. Do not copy the entire feature tree
   or apply deletions/main-only test reversions wholesale.
3. Build reviewable increments: raw-mean policy with its adapter tests; SHOW
   protocol/adapter/facade with its tests; recovery guards and synthetic E2E;
   complete trial/Unicode diagnostics and oracle tests; reconciled documentation.
   Keep each dependent implementation/test group complete and buildable. Retain
   SHOW as an explicitly selected candidate instead of discarding it to hide
   its outstanding acceptance.
4. Carry the follow-up oracle-process identity, saved STOP request identity and
   legacy bytes/text contracts through the corresponding helpers and fault
   tests. Main's scope note names these pending gaps; do not mark them fixed
   merely because the older status-anchor tests pass.
5. Review the final diff against the new main. Confirm preserved crop IDs,
   installer file identity, the scope-history document and unchanged default
   backend/configuration. Explain any difference from the frozen candidate.
6. Run the regression groups below on the actual proposed tree, then obtain a
   scope review. Integration approval and real-host qualification are separate
   decisions. Neither permits an unrequested installation, client change,
   release, main update or replacement of current private continuation records.

## Required regression and evidence checklist

| Group | Required checks |
|---|---|
| Default behavior | Full Node suite and default `selftest.mjs`; original 21-tool catalog, script gate, serialization, timeout/cancellation and default Python selection unchanged |
| Native facade/transport | Schema failures before dispatch, mandatory crop/new side-effect IDs, honest backend, unknown/failed handling, no fallback/replay, same-session new-client QUERY, duplicate/conflict/late-result isolation, SHOW completed identity/delivery validation |
| C++ offline | Parameterized local build; core and adapter surrogate tests; raw-mean incomplete-calibration cases without swallowed native/ABI failures; strict crop calibration, type/shape/budgets; SHOW ownership/failure/module-entry gates |
| Windows full chain | `test_transport.py` and `tests/native-e2e.test.mjs` with the newly built synthetic EXE; C++ execution-start handshake before cancellation; C++ creation/handle counters and normal STOP/exit. A compiler/platform SKIP is not a PASS; no automatic downloads |
| Python and file ownership | Full isolated Python regression plus `test_native_install.py`; preserve same-file identity assertions, changed/foreign-file refusal, prepared-state recovery and exact owned-file removal. Temp directories only |
| Acceptance helpers | `test_native_accept_mcp.py`, `test_native_trial_oracles.py`, `test_native_stop_helper.py`; independent positive controls, intended-error negative controls, no PASS output on failure, no earlier-check false coverage, source/oracle hash and shape/calibration checks, actual-process and STOP-ID binding; original request persistence before any pipe and no replay |
| Diagnostic contracts | `test_native_unicode_probe.py`: fake legacy bytes/str getter cases, raw-byte/code-point preservation, exact image ID and independent name/unit truth; no heuristic encoding repair or Unicode qualification from a synthetic round trip |
| Review hygiene | `git diff --check`, explicit changed-path review, no unrelated runtime/config/default-backend edits, no private fixtures/arrays/logs/manifests/vendor binaries or machine-specific run details |

At the compared snapshots, `bridge/`, `setup/`, `tools/`, `.github/`,
`selftest.mjs`, `mcp.native.json.example`, and native `bridge.cpp`, `bridge.hpp`,
`plugin.cpp`, `manage_plugin.ps1`, `build.ps1`, `test_transport.py` have identical
trees. A future difference in one of these paths needs its own explanation.

Offline regressions do not complete the pending real-host gates. A later
prepared-host acceptance must independently bind the actual process/build and
request IDs; compare live source/crop pixels, dtype/shape and physical axes;
observe the exact shown document and duplicate document count; verify it still
owns the image after STOP; normally close only that document and verify final
image release while the host remains running; then confirm normal exit and
manifest-based removal. UI-entered Unicode, legacy getter bytes/text, native
names and units need separate qualification. Strict protocol success does not
replace those independent host observations.
