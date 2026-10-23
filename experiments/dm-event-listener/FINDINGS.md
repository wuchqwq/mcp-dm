# Nonblocking host exploration: current findings

后续结果见 [原生周期入口实验](../dm-native-periodic/FINDINGS.md)：已验证自动原生
文件入口及空闲监听器唤醒，但 busy 时唤醒出现真实宿主崩溃，混合路径已隔离。
以下保留原 C1 顺序生命周期实验的历史证据，不代表并发安全或最新整体结论。

中文结论：**已实测证明，监听器可以在注册脚本结束后存活，并允许第二个常规
Python 脚本运行；但尚未证明可靠的自动外部 MCP 唤醒机制。**
外部请求文件经界面触发的往返通过，`/ef` 自动转发则残留辅助进程。
因此继续保留现有 Bridge，下一步只研究安全的外部唤醒与 busy 语义，不迁移工具。

This experiment starts from mainline `5e6feb4`. Its code is isolated here;
`bridge/`, `server.mjs`, `setup/` and the production MCP configuration are not
modified. Native-host results must be distinguished from fake-DM arithmetic
and Python-version compatibility tests. Detailed host receipts stay local.

## Audit of the current Bridge

`bridge/dm_bridge.py` calls `serve(Dispatcher(backend))` from its regular
embedded Python script. `serve()` performs blocking socket accept/receive and
dispatches operations synchronously on **that same GMS script thread**. There
is no Python network worker calling DM in parallel. A half-second socket
timeout allows shutdown/idle checks, but does not end the enclosing Python
execution. Registration as a background script keeps the UI available; it
does not free the single regular Python script slot.

The server accepts one connection and consumes it before accepting another.
The listen backlog is not a pool of active handlers. A connected client can
delay another client's status/shutdown until the client-idle deadline.
Node's `Bridge.call()` serializes requests per facade process and keeps a
connection; this is not a cross-client DM scheduler. A timeout or cancellation
can settle the Node wait while a dispatched DM operation continues.

The existing launcher normally sends `shutdown`, handles an occupied but
nonresponsive port as busy/unknown, and uses a two-stage startup. The audit
also notes its explicit termination of its own `/ef` helper; this experiment
does not invoke that path or terminate any DM process. Removing the Python
serve loop requires proving a new DM-side wake/dispatch mechanism, not merely
moving `socket.accept()` to an arbitrary Python thread.

### Which state must survive?

| State | Present owner | Implication |
|---|---|---|
| Visible image ID | DM native document | Can be resolved in another request while the object exists; not a content version or a cross-process identity |
| Hidden documents | `DmBackend._opened_documents` | Strong native wrapper roots are necessary; a stateless script may release them |
| Provenance | `_source_files` | Cannot silently disappear/rebind when changing transport |
| 4D descriptors/session tokens | `_fourdstem_sources` | Current tokens belong to one backend instance; no new 4D work is included here |
| Native 4D temporary buffers/stream | `NativePatternReader` per call | Existing lifetime/budget contracts must be preserved, without moving APIs to unverified threads |
| Metadata traversal budgets/type cache | Backend scratch fields | Per-operation state; can reset, but must not overlap across callbacks |
| Imported arithmetic/helpers | Module cache | Can be reimported; not equivalent to an open native document |
| Captured 2D inputs, previews/optional report results | On disk / external worker | Already usable independently of a persistent host Python execution |

`status`, visible-dataset enumeration, metadata and bounded stats can
conceptually be short calls. That does not prove automatic dispatch or make
currently hidden documents/session handles stateless. Retaining a module
between scripts is smaller than a new snapshot framework, but its GMS/native
lifecycle is precisely what C1 must verify.

## What the official interfaces establish

The installed wrapper exposes name/data/calibration, ROI, window, workspace
and application listeners with explicit removal methods. It does not expose
a general Python socket-to-host `PostMessage`, idle listener or an obvious
Python `AddMainThreadSingleTask` dispatcher. This is a bounded local API
inspection, not a claim that no Gatan version or SDK has another interface.

The scripting manual guarantees main-thread execution for **DM-Script**
single/periodic tasks. That statement does not prove the threading semantics
of `Py_ScriptObject` callbacks, Python interpreter admission while another
script is running, or an external process's ability to enqueue those tasks.
An image event is an observable event source, not an external-request API.

Gatan's live-copy example supports investigating retained listeners and
explicit unregistration, but neither that example nor its version warning
proves this MCP lifecycle. The original experiment uses name changes on its
own trigger image rather than an acquisition stream or real source edits.

## Evidence status

Fake-DM tests, GMS Python/NumPy compatibility checks and existing synthetic
regressions passed. A repaired native-host run subsequently passed the
bounded synthetic lifecycle below. The first native attempt failed while
serializing a SWIG subscriber handle; its failure artifacts were retained,
then native unregistration and release were verified before another run.
The fix records the return type, never a pointer coerced into a JSON ID.
`registration_complete.json` now distinguishes full registration from an
earlier provisional identity record.

| Native-host question | Status | Evidence and boundary |
|---|---|---|
| 1. Register | PASS after repair; initial FAIL retained | Actual version/runtime/source hash, full completion artifact and visible script return |
| 2. Survive registration end | PASS | Independent DM-Script name trigger and matching reply after return |
| 3. Second regular Python script | PASS | New normal foreground Python execution returns expected arithmetic in same host |
| 4. Survive that second script | PASS | Later independent trigger reaches the original listener; artifact/event ordering checked |
| 5a. Callback thread | PASS, limited | All observed callbacks match the known registration UI thread; unknown-thread guard is fake-DM tested |
| 5b. UI latency, overlapping listener callbacks, other event sources | NOT_TESTED | The bounded normal-script overlap experiment below does not test listener callback admission while Python is busy |
| 6. Unregister and release | PASS, bounded observation | Native unregister, dead weak reference, actual post-removal name change, unchanged callback count/source, owned-document release |
| 7a. External payload plus GUI wake | PASS, limited | External process writes a fresh nonce/request; GUI runs the fixed DM-Script; original host returns a matching reply |
| 7b. Automatic `/ef` wake lifecycle | FAIL | Request reached original host, but helper stayed alive with a second-instance error; no helper was killed and no forwarding was retried |
| 7c. Reliable unattended MCP-to-host wake | NOT_TESTED / not established | No supported existing-instance-only, busy-aware wake mechanism was demonstrated |
| 7d. `try/catch` as normal-Python busy detection | FAIL in measured overlap | Native call returned without caught exception or Python entry receipt; safe execution outcome is unknown |
| 7e. Ordinary slot recovery after bounded busy | PASS | Idle, background hold and later foreground entry/completion receipts bind the same host/session |

Detailed receipts, timings, native identifiers and failure history are kept
in a private local report, not redistributed here. `verify_run.py` independently
checks the bounded receipt chain and complete synthetic numerical oracle;
it does not turn GUI wake into unattended MCP acceptance. The first failed
session and repaired session are separate directories.

## Follow-up: external wake and busy admission

The failed `/ef` route is retired in `run_step.ps1`, including its old override.
The script now performs read-only process/port checks, returns
`refused_not_dispatched` with Python slot `unknown`, and exits 2. A real check
with the legacy override confirmed refusal: the responsive primary and prior
windowless helper were observed, no new DM process was created, and no request
was sent. A responsive window is not evidence of a free Python execution slot.

The new `admission_probe.py` generates finite, fixed experiments. A host-managed
background Python script writes a start receipt, sleeps for ten seconds and
writes completion. It calls no DM APIs. Native DM-Script attempts a second,
fixed foreground payload during measured overlap, with a `try/catch`, then a
later independent step tests recovery. The verifier distinguishes actual
entry, deferred entry, catchable rejection and missing/ambiguous evidence.
It does not infer that every caught exception means busy.

Real-host observations:

- Idle foreground payload: **PASS**, entry and completion receipts.
- Bounded background hold: **PASS**, start/completion, about ten seconds.
- Measured overlap: **PASS** as an experimental condition; the native
  pre-call marker falls between the background start and end.
- Catch-based busy detection: **FAIL**. The native post-call marker exists;
  neither caught-error marker nor attempted Python entry/completion exists.
  The request's execution outcome is **unknown**, not "safely canceled".
- Later independent foreground payload: **PASS**, same host and registration
  UI thread, after the background script completed.
- The user reported `No measured overlap` in step 2 and a screenshot shows a
  Python traceback in the marker function. These failure observations and the
  original generated files are preserved. Their exact invocation sequence and
  full Python exception text are not independently established; do not silently
  attribute the guard error to the earlier measured-overlap attempt.
- Fully unattended external wake, a supported global Python-slot query, and
  safe listener callback admission during arbitrary user Python: **NOT_TESTED**.

Two window-activation attempts failed, so no further UI automation was attempted.
The user ran the fixed native scripts manually. This sequence does not improve
the earlier external-wake claim. No images or hardware were accessed by this
admission experiment. No host/helper was killed or restarted. No production
Bridge, launcher, protocol or dependency was changed.

After inspecting the failure, the generator gained one-shot native markers to
refuse replay before launching the bounded script. Original host-run files were
not rewritten. These revised native guards are **NOT_TESTED in DM**. Synthetic
verifier tests cover identity mismatch, incomplete/ambiguous outcomes, measured
overlap, deferred/overlapping entry and missing/reordered evidence. Both current
development Python and the installed GMS Python run the experiment suite;
these are numerical/receipt and fake-DM tests, not additional host acceptance.
The current experiment suite passed **33 tests in each environment** (the same
33 tests run twice, including the 18 existing fake-DM lifecycle tests).

The smallest missing evidence remains a supported external entry that runs only
in the existing host and offers host-side admission or reliable rejection before
entering Python. Ask the matched SDK/documentation whether such an entry and
Python execution-ownership mechanism exist, including listener reentrancy and
teardown guarantees. DM-Script main-thread tasks, OS responsiveness and Windows
message delivery alone do not establish these properties. No undocumented
window message hook, unknown-thread DM API or infinite polling fallback is
introduced. Retain the current Bridge while this is unresolved.

## C1, B and C2

| Route | Expected benefit | Main unknown/risk | Cost / current recommendation |
|---|---|---|---|
| C1: retained Python listener | Registration returns and ordinary Python slot reuse is now demonstrated; existing arithmetic/backend code may stay Python | Safe unattended wake, admission while another user script is active, broad lifecycle/version coverage | Continue only the external-wake experiment; do not migrate tools yet |
| B: external Node plus short normal Python scripts | No idle Python serve loop; reuse visible native image operations | Admission/busy detection, reliable existing-instance dispatch, short slot occupation per request, hidden-document/session roots | Moderate integration; retain as fallback, not automatically implemented because C1 has not been disproved |
| C2: native C++ plugin | Native lifecycle and documented host-thread marshalling may provide a better IPC entry | Exact SDK/ABI/toolchain, documented dispatch guarantees, plugin teardown and crash isolation | Highest maintenance; obtain matching GMS 3.x SDK/license/compiler requirements before writing a plugin |
| Current persistent Bridge | Existing tool protocol and tested sequential DM API path | Occupies ordinary Python slot while idle | Keep available while investigating alternatives |

No SDK headers/import libraries/project were found in the inspected Gatan
installation directories. This is not a machine-wide search and does not
establish entitlement. Gatan's current official SDK page offers a GMS 3.x
SDK request; it does not specify the local host's exact compiler or ABI.
Those details need the matched SDK documentation. No plugin was built or
installed.

## Impact if C1 later passes

The 21 public MCP tool names and their argument/result contracts can remain
at the Node facade. Internally, the current TCP server would need a transport
adapter and a serialized, host-owned dispatch callback. The prototype only
implements a synthetic `probe`, so compatibility is a **design possibility**,
not an acceptance result for the production catalog.

Use a session epoch plus explicit image IDs; refuse closed/stale objects.
An ID does not freeze pixels/calibration. Preserve existing capture semantics
for fixed-input tasks. Retain hidden native documents only in a verified
host-owned lifetime root, and explicitly dispose them on teardown. Do not
reopen/copy/hash large data on every request to compensate for missing state.

Keep one DM operation at a time; do not parallelize native APIs. Express
predispatch busy/refused separately from dispatched/unknown. Canceling a wait
does not stop a callback. Store bounded operation identity/parameter binding
and completed result locations; after timeout inspect the existing result,
without blindly resending. A reply left incomplete by failure is not success.
This calls for a small transport state machine, not a general job platform.

Do only small native reads/checks on a verified callback thread. After a
bounded scientific capture, use the existing independent Python environment
for expensive numerical work/plotting. Actual callback admission and measured
latency need to establish that even ordinary 2D operations are usable.

## Decision rule

Do not claim a reliable nonblocking MCP host from listener registration alone.
Tests 3/4/6 now hold for the bounded synthetic sequence. Continue C1 only to
resolve external dispatch and busy behavior. A GUI-executed trigger proves
the listener path but leaves
automatic external wake unproven. Even successful `/ef` forwarding leaves its
check-to-launch cold-start race and GUI-focus/helper-process behavior to solve.

If a documented, safely callable external wake is still missing, retain the
current Bridge and its explicit stop/use-Python/restart workflow while
testing B narrowly. C2 is justified only if a matched SDK provides a supported
dispatch/lifecycle mechanism worth its maintenance cost. None of these
experiments authorizes a production migration or an expansion of 4D-STEM.
