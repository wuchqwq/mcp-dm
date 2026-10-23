# Native main-thread periodic file entry (experimental)

This branch tests **only** a small native DM-Script entry. It does not replace
the production Bridge or migrate any MCP tool. No hardware, real data, `/ef`,
new native plugin, Python environment changes or arbitrary script endpoint.

The [official Gatan file-wait example](https://www.gatan.com/sites/default/files/images/scripts/Having_a_script_wait_for_a_file_to_appear.s)
documents main-thread periodic file checks. Its unbounded signal wait is not
used here. `task.s.in` is original experiment code, not a redistributed manual
or copy of the example. Installed scripting documentation supplies the task,
file, timer, image and calibration API signatures.

## Minimal lifecycle

Use a new private ASCII directory; never reuse a run directory:

```powershell
Get-Process DigitalMicrograph | Select-Object Id, MainWindowHandle, Responding
# Replace 1234 with the observed, already-open DM main process PID.
$dmHostPid = 1234
python -B experiments/dm-native-periodic/client.py prepare D:\dm-native-private\run01 --host-pid $dmHostPid
```

With the existing DM open and the ordinary Bridge normally stopped, open and
run generated `01_register.s` **once** as DM Script. It registers a 0.5-second
native main-thread task and returns immediately. Do not use an old registration
script as a status query. On failure preserve files and inspect before retrying.
No image is created until a valid `stats` request arrives.

From an external Python process, without another DM GUI action:

```powershell
python -B experiments/dm-native-periodic/client.py submit D:\dm-native-private\run01 --operation ping
python -B experiments/dm-native-periodic/client.py query D:\dm-native-private\run01 --slot 0
```

Run the generated finite `02_ordinary_python.py` in DM once. Then publish a
second ping and verify its new ID reply. Only after native entry and ordinary
Python coexistence pass, submit `--operation stats`. That fixed action creates
one owned float32 ramp, reads its dimensions/calibration and a fixed half-open
ROI, and returns actual native statistics. It never targets a front/real image.

The ordinary Python proof must import the actual DM API, run on the foreground,
match the bound host PID, and use built-in native APIs to check the retained
object and host version before writing its receipt. A plain Python arithmetic
file written outside DM is not host acceptance. For an already prepared run,
`bind-host --host-pid N` adds an exclusive host binding without starting DM.

`--operation fail` is an intentional fixed failure with no scientific action.
Duplicate IDs in separate slots are rejected, including changed operations.
There is no execute-code field, user-supplied native expression, path or ROI.

Stop externally and **query the receipt**, without assuming a stop request
already stopped the callback:

```powershell
python -B experiments/dm-native-periodic/client.py stop D:\dm-native-private\run01
python -B experiments/dm-native-periodic/client.py cleanup-check D:\dm-native-private\run01
# After stopped.json exists, run the generated 03_check_removed.s once in DM.
python -B experiments/dm-native-periodic/client.py verify D:\dm-native-private\run01
```

`stopped.json` records task removal, processed counts, complete synthetic pixel
and calibration checks, and owned-document closure. No unrelated document is
closed. If ownership/source checks fail, that document is left open for review.
The separate finite removal check queries the recorded native object's weak
identity; the verifier requires it to be gone, not just a reported stop marker.
Keep artifacts; cleanup does not delete requests, results or failure history.

## Bounds, identity and unknown outcomes

- At most 32 ordered slots; one file/operation per callback. Missing earlier
  slots block later slots by design; this is a single-writer experiment, not
  a general task queue. A client crash after reservation can leave such a gap.
- Requests are exactly 128 ASCII bytes, containing session, request ID and
  one fixed operation. Only `.ready` files are examined. The external writer
  closes/fsyncs a temporary file, then atomically links it under its final
  name without replacing an existing destination. This requires a filesystem
  supporting hard links; a failure is reported, not silently downgraded.
- Native results are written to a fresh temporary file, closed and moved to
  a fresh final name. The Gatan `MoveFile` documentation alone does not prove
  atomicity on every filesystem. The client still validates complete JSON and
  identity; missing/malformed/conflicting receipts remain `unknown`.
- IDs are deduplicated within the retained task object. This is not crash-safe
  exactly-once execution. Unknown requests are never automatically resubmitted.
- Lifetime defaults to 600 seconds (configurable 10..600), with a secondary
  callback-count bound and external stop marker. Expiration is checked at the
  next callback: it cannot interrupt a blocked UI or an already-running action.
- Task state is native, with no Python serve loop, background Python worker,
  blocking signal wait or infinite loop. DM API calls remain on the documented
  native main-thread task. Individual read/compute/I/O calls can still block.
- The private directory is local IPC, not authentication or a security sandbox.
  Do not run multiple registered tasks over the same directory or publish
  private runtime paths, receipts, screenshots or vendor manuals to Git.

For the staged-publication negative test, use `reserve` then `publish --slot N`;
the pending file should produce no reply until publication. `query` is read-only.
It returns unknown before a valid terminal receipt and never retries.

## Independent verification

The synthetic ramp is `10*y+x`, `[y,x]=[8,12]`, with signed X/Y calibration.
The fixed source rectangle `[x0,y0,x1,y1]=[2,1,7,5]` has 20 pixels, sum 580,
mean 29, minimum 12 and maximum 46. Full-source preservation checks all 96
values and both signed calibrations before closing the owned document.

The external verifier independently enumerates the ROI; checks all issued
slots, IDs, expected success/failure codes and exact execution accounting;
requires native roundtrips before/after ordinary Python; and checks stop and
source-preservation receipts. A complete JSON response alone is not success.
It does not certify host provenance, UI latency, callback reentrancy, or a
Python-listener busy policy. Those require separate real-host observations.

```powershell
python -B -m unittest discover -s experiments/dm-native-periodic -p "test_*.py" -v
```

Run the same tests with the installed GMS Python outside DM without upgrading
dependencies. Client tests are not native-host scheduling or image acceptance.
Results and current limitations are recorded in `FINDINGS.md`.

## Python-listener busy experiment: QUARANTINED

The separate `listener_probe.py` / `listener_task.s.in` experiment reused the
existing C1 listener and synthetic source. Idle native-to-Python wake completed
with a verified nonce, source, calibration and values. A subsequent wake during
a fixed background Python sleep was followed by a real DM crash; Windows
recorded a `python37.dll` access violation. The interrupted operation has no
completion receipt and remains unknown. It must not be retried.

**Do not run this listener/busy experiment in a normal DM session.** Newly
generated starters now refuse before any host import or allocation, and the
public request function always refuses. The native hold operation is disabled;
a cooperative own-busy guard was added, but that guard is NOT_TESTED in DM and
does not detect arbitrary user scripts or make Python reentry safe. There is
no automatic restart or permission flag to bypass this quarantine.

Original executed source, initial observations and crash events are retained
privately without rewriting. The current listener files are review artifacts,
not the exact ungated host-run source and not a repaired production transport.
Its private protocol helper is used only by synthetic tests. Do not use it to
bypass quarantine. The direct native-only prototype remains separate.
