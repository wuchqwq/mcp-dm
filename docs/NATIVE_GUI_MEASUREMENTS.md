# Continue from a GUI selection

The experimental native backend can continue from an explicitly identified DM
rectangle or a limited line selection, show a true one-dimensional result and
hand off its scientific values. The Agent does not have to identify a result by
the newest window or manually transcribe samples. This remains an exact-build,
bounded workflow; check [adapter compatibility](../experiments/native-bridge/mvp/ADAPTERS.md)
and [the native workflow](../experiments/native-bridge/mvp/NATIVE_WORKFLOW.md).

## Small synthetic trial

Use an idle synthetic-only host. Do not edit its source while requests run.

1. Call `dm_status`; require `backend:digitalmicrograph-native`, `ready:true`,
   `compatibility.state:SUPPORTED` and the capabilities for the chosen operation.
2. Call `dm_datasets` and choose the explicit source image ID. Call
   `dm_native_rois(image_id)` with a new request ID to read current document,
   display and ROI identities. An old QUERY is historical, not a fresh selection.
3. For a line, require the returned eligible integer horizontal/vertical,
   width-one geometry. Save the session, request ID, complete GUI identities,
   ordered `expected_line` and width before calling `dm_native_profile`.
   Diagonal, fractional, wide and ambiguous selections are refused.
4. For a rectangle, preserve its admitted half-open source coordinates and use
   `dm_crop` with a saved request ID. A float32 result may then feed
   `dm_native_histogram` with explicit raw-value range and bin count. The range
   must cover the complete selected image's native minimum and maximum.
5. Save the successful creation response. With a separately saved ID, call
   `dm_native_show` on that exact result image ID. PROFILE stays native float64;
   HISTOGRAM stays native uint32. Neither is a one-row raster.
6. Explicitly encode the saved response in a new external workspace using
   `tools/native_snapshot_handoff.mjs` as described below. Independently reopen
   the NPY and check dtype, shape, values and sidecar calibration.
7. When intermediate plugin ownership is no longer needed, call
   `dm_native_release` with the exact image ID, creation retention token and its
   own pre-saved request ID. The visible document may continue to own the image.

If a request times out or local waiting is cancelled, use `dm_native_result`
with the **original** creation/SHOW/release ID. Do not generate a replacement
operation. Same-ID QUERY returns the same immutable operation record within
that still-queryable native session; it does not promise recovery after STOP
or restart. Use a new `dm_native_result_info` request to inspect current retained
availability, separately from old creation history.

## Explicit file handoff

The encoder is a command-line companion, not a new MCP processing tool. The
Agent needs ordinary file/command capabilities to invoke it:

```powershell
node tools/native_snapshot_handoff.mjs --workspace C:\analysis\trial --output measurement-01 --request-id export-measurement-01 --snapshot C:\analysis\trial\creation-response.json
```

Save `export-measurement-01` and its parameters before invocation. The workspace
must already exist and the output directory must be new. The encoder persists
its own journal, refuses overwrite and verifies files before same-ID reuse.
PROFILE produces true rank-one `<f8` NPY. HISTOGRAM produces true rank-one `<u4`
NPY; its exact binary64 wire representation has a separate hash. Source and
output identity, native axis, raw bin/trajectory geometry, calibration status,
parameters and original receipt remain in the schema-1 sidecar.

Raw pixels and counts do not acquire physical intensity units merely because a
source unit is present. Histogram raw bin geometry and display axis mode are
separate; see [histogram semantics](NATIVE_HISTOGRAM.md). A display PNG is not
scientific data, SHOW is not permanent file saving, and producing an image does
not prove a model has viewed it.

After explicit export, an external scientific script may read these files in a
separate workspace. Keep that script, parameters and results with its inputs
and identify it as external computation. It is not a native fallback. General
import back into DM, native SaveAs and general workspace activation remain
unavailable.

## Acceptance boundaries

Offline protocol/ABI substitutes, actual DM processing, independent source and
numeric checks, document lifetime and ordinary model-client acceptance are
reported separately in [RESULTS](../experiments/native-bridge/RESULTS.md).
Manual drawing counts as a manual-selection trial only when observed in that
same host with a new baseline before processing. API-created fixture lines do
not substitute for it. Last-reference checks run after returning to host idle;
a same-stack reference cannot prove destruction. Keep every original failed
run and its saved request records.
