from pathlib import Path
root=Path.cwd()
p=root/'docs/NATIVE_LIFECYCLE_HANDOFF.md';s=p.read_text();a='''Use a unique export ID and retain its original workspace and journal. Export IDs
are scoped to that workspace; copying journals to another workspace is not a
cross-directory recovery mechanism.
''';b='''Use a unique export ID and retain its original workspace and journal. Export IDs
are scoped to that workspace; copying journals to another workspace is not a
cross-directory recovery mechanism. Each newly created capture now has a random
`capture_id` persisted before any connection; STATUS/READ IDs include that
capture's namespace. Independent directories using the same short export ID
therefore cannot retrieve one another's cached READs. The journal records
`request_namespace_version:2` and its canonical workspace. Explicit recovery
uses the saved capture ID and original wire plan, never a newly generated ID.

Completed legacy journals without that version can be verified offline only;
the returned `request_namespace_status` is `legacy_unscoped_saved_evidence_only`.
Hash agreement verifies the saved bytes, not their freshness at the old capture
time. Incomplete legacy journals are refused with `LEGACY_REGION_RECOVERY_UNSAFE`,
even with `--recover`: preserve their evidence and use a new export ID/output.
No automatic journal migration, old-ID resend or overwrite is performed.
''';assert a in s;s=s.replace(a,b,1)
a='''The current
`document_visible`/visible-document receipt is **not proof of visibility in the
active workspace**, focus, or model viewing.'''
b='''The legacy
`document_visible`/visible-document receipt is **not proof of visibility in the
active workspace**, focus, or model viewing. The MCP facade adds `display_context`
to completed SHOW responses and their QUERY results: `scope:document_delivery_only`,
`active_workspace_visibility:unknown`, `workspace_activation_requested:false`,
`model_visual_verification:false`, and `observation:not_performed_by_mcp`.
This is a conservative interface policy, not a live workspace observation or a
mutation of the original native receipt.''';assert a in s;s=s.replace(a,b,1);p.write_text(s)
p=root/'README.agent.md';s=p.read_text();needle='Native DATASETS includes images across workspaces.';assert needle in s;s=s.replace(needle,'New complete-region exports persist a per-capture request namespace before dispatch. Resume only the original journal in its original workspace; incomplete legacy unscoped journals are refused, never migrated or replayed. Completed old packages remain offline evidence, not newly verified source reads.\n\n'+needle,1)
s=s.replace('Its receipt does not prove active-workspace visibility or model viewing.','Its receipt does not prove active-workspace visibility or model viewing. MCP SHOW/QUERY adds `display_context` with active-workspace visibility explicitly unknown; this does not probe or activate a workspace.',1);p.write_text(s)
p=root/'AGENTS.md';s=p.read_text();s+='''
Complete-region export requests must be isolated by a random, durably recorded
capture instance, not just the user-facing export name or mutable source ID.
New journals bind their canonical workspace and namespace version; recovery
reuses the exact saved wire IDs. Incomplete legacy unscoped journals must not
be silently migrated or replayed. Completed legacy packages are saved evidence
only and cannot be retroactively qualified as fresh reads by a hash check.
MCP SHOW/QUERY `display_context` describes document-delivery policy, not a fresh
GUI observation; preserve historical native receipts and report unknown active
workspace visibility rather than claiming a tab was activated.
''';p.write_text(s)
p=root/'docs/REGION_ID_REPAIR.md';p.write_text('''# Complete-region request isolation and SHOW interpretation

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
''')
