# C1: a short-lived registration script and a retained Python listener

This is an isolated feasibility experiment, **not a replacement Bridge**.
Production MCP tools, TCP protocol, launcher and configuration are unchanged.
No microscope hardware, real experimental data, background Python worker,
periodic task or arbitrary-script MCP permission is used.

## What this tests

The registration script creates a small calibrated ramp and a separate
single-pixel trigger image. Only the trigger's **name** changes. A
`DM.Py_ScriptObject` listens for its name-change event, checks the request's
session/operation identity, reads one bounded JSON file, checks the ramp's
pixels/calibration, and writes one reply. It never calculates on display pixels.

The module is retained in `sys.modules`, with an explicit strong reference to
the listener. This is a hypothesis about GMS interpreter lifetime to test,
not a guarantee. No SWIG ownership transfer via `__disown__` is attempted.
The callback rejects an unexpected Python thread **before calling DM APIs**.
The known thread is established by running registration on DM's foreground.
Callback duration is recorded; short duration alone does not prove UI
responsiveness or thread safety for other DM operations.

Gatan's official live-copy example warns about listener crashes in GMS
3.5.0/3.5.1 and describes explicit unregistration in 3.5.2+. This experiment
queries the actual host version into its own synthetic tags, rejects older
3.x APIs and unknown major versions, and requires `UnregisterAllListeners`.
Version acceptance is a safety gate, not a claim of version-wide support.

## Run with a private, new output directory

Use the repository's development Python outside DM to prepare the scripts:

```powershell
python -B experiments/dm-event-listener/probe.py prepare D:\dm-c1-private\run01
```

Before host execution, disconnect MCP clients and normally stop an existing
Bridge with its existing launcher. A listening/nonresponsive port is
busy/unknown, not a reason to inject another script. Do not restart DM or close
unrelated documents. Keep the same DM process throughout the sequence.

Open the generated scripts in DM and run them **one at a time**, waiting for
each to return. Python steps must run on the foreground (uncheck
`Execute in background`). The scripts are finite and operate only on their
two newly created images.

| Order | Script | Required observation |
|---|---|---|
| 1 | `01_register.py` | Returns; `registration_complete.json`, `registered.json`, `lifecycle.json`, event log and two synthetic images exist; no registration-failure artifact |
| 2 | `02_after_return.s` | A matching reply appears after the registration script has ended |
| 3 | `03_second_script.py` | A separate normal Python execution returns, calculates 55 and sees the retained listener |
| 4 | `04_after_second.s` | The original listener produces another matching reply |
| 5 | An externally prepared request below | Distinguish payload delivery from the mechanism used to wake DM |
| 6 | `06_cleanup.py` | Explicit unregister returns; the listener reference is released |
| 7 | `07_after_cleanup.s` | Trigger name changes, but no callback/reply appears |
| 8 | `08_verify_cleanup.py` | Checks the actual post-cleanup trigger name, callback count, weak reference and unchanged ramp/calibration |
| 9 | `09_release.py` | Closes only documents carrying this session's ownership tag; removes the module root |

The expected ramp has shape `[8,12]`, values `10*y+x`, sum 3888, mean 40.5,
minimum 0, maximum 81. Physical zero/scale are `(1.25,-0.25)` for X and
`(-2.5,0.5)` for Y, in nm. These values are exactly representable as float32;
this experiment needs no relaxed calibration tolerance.

Do not use `01_register.py` again as a status query. A missing receipt or a
timeout means unknown until the host/module is inspected. Re-registration
could leave additional subscriptions. If registration partly fails, preserve
`registration_failure.json`, then run explicit cleanup, verification and
release. If unregister fails, the script deliberately retains references.
If cleanup cannot be verified, leave its images open and stop host experiments.
After successful explicit unregistration, `10_verify_release_after_unregister.py`
is a finite alternative to steps 7–9: it sends the fixed post-removal name
change, verifies the weak reference/count/source, closes only the owned
synthetic documents and removes the module root. It cannot register a listener.
The successful host check used this alternative. Long observation windows for
delayed callbacks remain untested.

## External request candidate: this is a separate test

From an external process:

```powershell
python -B experiments/dm-event-listener/probe.py request D:\dm-c1-private\run01
```

This writes a new immutable request and a fixed `external_<id>.s` trigger. It
returns `wake_required`, **not success**. Running this file manually in DM
tests file delivery plus a manual wake; it does not prove unattended MCP
dispatch. Replies bind session, operation ID, nonce and parameter hash. An
already-seen ID with changed parameters is rejected. Existing outputs are
never overwritten. There are at most 16 processed requests per experiment.

`run_step.ps1` preserves the one-shot **experimental** CLI forwarding attempt.
**It is disabled by default:** actual forwarding reached the original host,
but its helper did not exit and reported a second-instance error. Do not use
this runner for the normal lifecycle sequence. The explicit
`-AllowUnvalidatedForwarding` switch is only for separately reviewed further
transport experiments; no more forwarding was attempted after that failure.

```powershell
.\experiments\dm-event-listener\run_step.ps1 `
  -SessionDirectory D:\dm-c1-private\run01 -ExpectedDmPid 1234 -Step register
# Expected: explicit refusal, with no process launched.
```

If deliberately enabled, the PID must come from the currently open,
user-owned DM. The runner refuses
missing/multiple/unresponsive hosts, an occupied Bridge port, an expired
session PID and a previously attempted step. It records dispatch attempts and
does not retry, kill a helper, start a missing DM, or change MCP permissions.
A helper exit code is not a callback/result verification. Check artifacts and
the original host PID after every step; stop if a helper remains alive.

**Limitation:** Gatan documents that `/ef` starts DM if none is running.
The check-to-launch race cannot be eliminated by checking a PID twice.
This runner therefore cannot claim an existing-instance-only dispatch
guarantee, and is not proposed as production transport. A modal or another
user script can also prevent dispatch; absence of a reply is `unknown`.
Do not run it while DM is busy or a file dialog/error dialog is open.

## Cleanup and evidence limits

All runtime artifacts remain in the private session directory; do not add it
to Git. `events.ndjson` contains callback thread identity, duration and failures.
`registered.json` records actual host PID/version/runtime and loaded probe
source hash. Replies contain only synthetic values and their calibration.

The directory is local IPC, **not authentication or a security sandbox**.
Another process under the same user's account can alter it. No claim of
crash recovery, exactly-once execution, interruption of running computations,
concurrent request safety, production performance or compatibility with all
21 tools is made by this prototype.

Read-only receipt/numerical verification after a completed lifecycle:

```powershell
python -B experiments/dm-event-listener/verify_run.py D:\dm-c1-private\run01
```

The verifier independently enumerates the full ramp, checks reply identity,
nonce and parameter hashes, signed calibration, event ordering around the
second script, cleanup references/counts and source identity. It exits nonzero
on missing, incomplete or inconsistent artifacts. It does not independently
prove host provenance or certify the external wake mechanism.

Run the fake-DM tests independently:

```powershell
python -B -m unittest discover -s experiments/dm-event-listener -p test_probe.py -v
```

Also run this suite with the installed GMS-managed Python executable outside
DM to check Python/NumPy compatibility; do not install or upgrade anything in
that environment. Fake-DM tests do not test native callbacks, GMS scheduling
or SWIG reference release. See [FINDINGS.md](FINDINGS.md) for the audit,
evidence categories and architectural decision.

## Official references (not redistributed)

- Installed Gatan Python Help: `Py_ScriptObject` class; local Python wrapper's
  `ImageHandleNameChangedEvent`, `HandleNameChangedEvent`,
  `UnregisterAllListeners` and `__disown__` signatures.
- Installed *DigitalMicrograph Scripting*: “Running Scripts” command-line
  `/ef` behavior; “Threading / Tasks” documents DM-Script main-thread tasks.
  Those tasks do not establish a Python socket-thread dispatch API.
- [Gatan live-copy example and version warning](https://www.gatan.com/ja/Software/Scripts/Python-Library/Live-simple-copy).
- [Gatan SDK request and C++ integration overview](https://www.gatan.com/Software/Software-Development-Kits).

Only API names and original experiment code are included here. Vendor manuals,
sample code, headers, plugins and binaries are not redistributed.
