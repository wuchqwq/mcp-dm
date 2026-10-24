# Complete-region request isolation and SHOW interpretation

This follow-up integrates the reviewed lifecycle/region work from `19b3b23`.
It changes the external Node exporter and MCP response annotation only: no
vendor entrypoints, native numerical algorithms, C++ reference handling, GMS
fingerprints or default v0.6 configuration are changed.

## Reproduced request collision

The old wire prefix used image ID, ROI, block size, session/PID and a short
user export ID. Two different output workspaces could reuse those values.
The native core correctly deduplicates same-session IDs, so a second export
could save the first export's READ bytes even if the source changed between
completed tasks. Internally consistent hashes do not detect that stale input.
An offline stateful peer reproduces the issue for both float32 and uint32;
it implements actual same-ID reuse rather than an always-fresh echo.

Every new capture now generates a random capture identity and records it with
its full plan before connecting. Wire request IDs derive from that identity.
Recovery uses the original identity and checks the saved STATUS and block
requests. Canonical workspace binding rejects copied partial journals.
Same-directory, same-ID completed reuse remains offline and does not reread DM.
Native deduplication and uncertain-operation QUERY behavior are unchanged.

Completed legacy captures remain offline evidence only, with an explicit
legacy namespace status. Incomplete legacy captures are not automatically
migrated: their old IDs could already refer to another export. Preserve their
files and start a new export ID/output instead. No prior PASS or saved bytes
are rewritten to claim a fresh-source observation.

## SHOW is document delivery, not tab activation

The MCP facade adds a `display_context` to completed SHOW and recovered SHOW
results. Active-workspace visibility is `unknown`; no workspace activation
was requested by this interface and no model viewing was verified. The
original native fields/receipt remain unchanged. This annotation is policy,
not a fresh GUI probe when an old operation is queried.

## Validation scope

Regression cases cover independent directories, changed pixels between tasks,
float32 and high-bit uint32 values, durable identity before dispatch, same-ID
recovery, copied partial journals, changed namespaces/STATUS identities, and
legacy evidence handling. Existing independent NPY reopening, coverage, failure,
lifecycle and protocol tests remain required. SHOW tests check both immediate
and recovered replies without creating another document or altering records.

These new cases are offline/synthetic. This review does not operate a user's
DM, load vendor DLLs or claim a new actual-GMS qualification. The previously
reported ADF inverse-transform accuracy failure remains a failure; no numerical
threshold was relaxed. GUI ROI, profile/histogram and workspace activation
remain the next native-interface work, not features supplied by this fix.

## Subsequent targeted actual-host check

A later prepared synthetic GMS session exercised the merged repair through the
real Node handoff runner and native pipe: float32 (including signed zero) and
high-bit uint32 inputs, distinct workspaces with the same user label, then
intentional edits to only those synthetic inputs between completed captures.
The second captures had fresh capture/wire identities and the new exact bytes.
Completed reuse in the original workspace returned its saved package with a
transport guard that rejects any live call. Four outputs independently reopened
with exact values, dtype, axes and signed calibration. Saved files remained
usable after the original saved-ID STOP and normal host exit; manifest-owned
cleanup completed. This is a targeted follow-up, not a rewrite of the original
review's offline-only scope or a new GUI ROI qualification.
