# uint32 ADF-like data: native processing and handoff

This page retains the initial five-group qualification and its historical
refusal tests. Later native arithmetic, filters, Fourier and visible delivery
have their own [operation qualification](UINT32_OPERATIONS_ACCEPTANCE.md);
the earlier refusal observations below are not current blanket refusals.

This extension concerns ordinary-packed two-dimensional uint32 intensities,
not detector identification or acquisition control. A uint32 image does not
establish HAADF geometry, electron counts or intensity calibration.

## Qualification

The prepared build passed a new real synthetic host: public Node MCP, native
statistics/crop/preview/READ, exact high-bit NPY reopening, independent same-PID
oracle and matched original STOP release. It exited normally with code 0 and
completed manifest-owned removal. The final production-admission DLL then
independently passed the same workflow and original-STOP oracle in a fresh
host, without a preparation switch. It also exited normally with code 0 and
completed owned removal. Both captures reopened unchanged afterwards; a new
explicit external run reproduced the exact integer sum and fractional mean.
This is **LIMITED_SYNTHETIC_UINT32_REAL_HOST_PASS**. Offline surrogates do not
prove a host ABI. The existing float32 acceptance remains separate. Only the
exact fingerprinted Windows x64 GMS 3.53.4137.0 is eligible.

| Independent observation | Result |
| --- | --- |
| Actual native backend/profile and dataset enumeration | PASS, both explicit synthetic source IDs, code 11, uint32 and support fields |
| Native mean/SUMMARY with and without spatial units | PASS, fixed integer/scalar truth and raw-intensity semantics |
| Same-dtype crop, translated signed calibration, independent storage | PASS, non-square ROI; full source pixels, names, spatial/intensity calibration and documents unchanged |
| Fresh-client QUERY, duplicate and conflicting crop parameters | PASS, original record and unique retained crop preserved |
| Native READ, display preview, `<u4` NPY and external example | PASS, complete small arrays and bytes, including 32-bit maximum and adjacent high-bit values; PNG mapping separately checked |
| Unsupported uint32 operators and SHOW | PASS, explicit errors; SHOW failed QUERY is immutable and creates no result/document |
| Original STOP, output release, normal exit and owned removal | PASS, each host has its own pre-saved request and actual-PID oracle |
| Saved data after final exit | PASS, original six capture-file hashes, dtype/shape and new external run |
| Real experimental ADF, ordinary model client, other builds | NOT_TESTED |

The numerical real-host fixtures are 4 by 4 sources and a 2 by 3 crop. Large
working-set/performance and every input up to an admission limit were not
measured. Boundary/missing-symbol/error rejection has separate offline tests.

A final record audit subsequently tightened the conflict-receipt timing check:
exactly `queue` and `execute`, both nonnegative safe integers. Both preserved
actual records passed that stricter offline recheck; injected negative timings
were rejected. This is record-only validation after the live observations,
not a new live-pixel run, and no historical receipt or oracle was rewritten.

## Bounded contract

| Operation | uint32 scope |
| --- | --- |
| Dataset metadata | Explicit ID, native type code, row-major shape and spatial calibration; no dtype inferred from a name or thumbnail |
| Native mean and SUMMARY | At most 2,097,152 pixels; raw intensity; SUMMARY is minimum, maximum, sum and mean |
| Native crop | At most 4,194,304 source pixels; explicit half-open rectangle, separate same-dtype image, complete spatial calibration, at most 4 MiB output |
| Display preview | At most 4,194,304 source pixels and 128 by 128 samples; gray8 display only |
| Native READ | At most 4,194,304 source pixels and 16,384 ROI samples / 65,536 raw bytes; exact little-endian uint32 |
| Explicit scientific handoff | Existing `input.npy`, `input.json`, `capture.json`; NPY descriptor `<u4`, exact bytes and provenance; new path only |

The conservative statistics bound satisfies
`2,097,152 * (2^32 - 1) < 2^53`. Thus every possible integer sum in this scope
is representable in the native double result. The mean is a binary64 fraction;
an exact integer sum does not make every fractional mean exactly representable.
A larger image may be previewed or read within its own budgets, then explicitly
cropped before statistics. No automatic clipping or hidden dtype conversion
is performed. A full 2048 by 2048 uint32 image exceeds the statistics budget.

Native arithmetic, FFT, filters and visible-document delivery do not inherit
this five-group qualification; their later independent scope is linked above.
Their existing float32/complex scopes remain explicit.
Native SaveAs/Open are still unavailable. Encoding saved READ bytes as NPY is
bridge-owned data handoff, not an unverified DM SaveAs call.

## Independent synthetic trial

Use fresh small images containing zero, values on both sides of `2^24`, the
signed 32-bit boundary and `2^32 - 1`. Bind native code 11 to the host's actual
NumPy uint32 view and exact high-bit READ values; an old dtype table alone is
insufficient. Include signed spatial scales, nonzero origins, nontrivial
intensity calibration and a source without spatial units.

The trial must bind the actual host PID/session and caller-saved request IDs.
Check explicit source and crop IDs, original-ID QUERY/duplicate/conflict,
native scalar values, the complete small raw arrays, source invariance,
independent crop storage, preview mapping, dtype, axes and translated ROI
calibration. Reopen `<u4` NPY and compare every value and raw byte. Run the
external example explicitly in a new workspace and retain its script,
parameters and results. That example is not a native processing fallback.

Before STOP, save its original request. After STOP, verify only the explicitly
recorded unshown output IDs are released, while original source data,
calibrations, names, documents and saved files remain unchanged. Close the
test host normally, remove only the manifest-owned plugin, then reopen the
saved data again. Preserve failed attempts and all earlier evidence.

Wrong PID/session/STOP identity, signed or float dtype substituted for uint32,
truncated high bits, incorrect scalar values, transposed arrays, changed
calibration and falsely rehashed output must fail independent acceptance.
Real experimental data and ordinary Agent/model-client use remain NOT_TESTED.

## Historical five-group procedure

The following entrypoints preserve the earlier five-group trial, including
its then-required operator refusals. They are not the current artifact's
expanded-operation qualification. For the current build use the separate
[uint32 operations procedure](UINT32_OPERATIONS_ACCEPTANCE.md); do not expect
the historical refusal matrix to pass against newly qualified operators.

Use a new idle synthetic host following [INSTALL](INSTALL.md), with a fresh
`DM_NATIVE_SESSION` and private existing `DM_NATIVE_EVIDENCE_DIR` set before
launch. Record the actual loaded artifact hash and PID. In the ordinary DM
Python editor, add this MVP directory to `sys.path` and run
`create_uint32_fixture.py` once. It creates only the two fixed synthetic
sources and exclusive NPY/truth files; `RECORDED` is not native acceptance.

Outside DM, run from the repository root, using a new absolute attempt path:

```powershell
python -B experiments/native-bridge/mvp/accept_uint32_mcp.py `
  --directory $fixture --output-directory $attempt `
  --qualification-mode production --analysis-python $externalPython
```

That strict client preserves requests before submission, runs the two-client
recovery checks and invokes the explicit NPY encoder/external example. It
does not start DM or inject scripts. Its `RECORDED` still requires the
independent same-host check. In a new one-shot DM Python script, set
`os.environ['DM_NATIVE_UINT32_REPORT']` to the attempt's
`uint32-mcp-report.json`, `DM_NATIVE_UINT32_LEDGER` to `uint32-requests.jsonl`
and `DM_NATIVE_UINT32_RECOVERY_LEDGER` to `uint32-recovery-requests.jsonl`.
Set `DM_NATIVE_UINT32_OUTPUT` to a new private oracle filename, then run
`verify_uint32.py`. Changing an external shell's environment does not change
an already running DM process. The oracle binds its own `os.getpid()`.

After PASS and release of all oracle wrappers, use the existing explicit
`stop_native.py` procedure to persist and submit a fresh STOP request. In
another one-shot DM script keep the three attempt paths, set
`DM_NATIVE_UINT32_INDEPENDENT` to the accepted oracle file,
`DM_NATIVE_UINT32_STOP_REQUEST` / `DM_NATIVE_UINT32_STOP_RECEIPT` to the original
STOP files and `DM_NATIVE_UINT32_STOPPED_OUTPUT` to a new result filename.
Run `verify_uint32_stopped.py`. Then close only this prepared synthetic host
normally and perform manifest-owned removal. Finally reopen the captures and
run the external example with a new output subdirectory. Preserve earlier
attempts; never edit evidence to make an oracle pass.
