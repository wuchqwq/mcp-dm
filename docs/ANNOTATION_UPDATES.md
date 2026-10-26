# Update one existing annotation without replacing the others

`image_annotate` accepts exactly one of:

- `annotations`: the existing complete replacement list. `[]` clears all marks.
- `updates`: 1..100 sparse edits to existing, unique `annotation_id` values on the
  supplied immutable `object_id`. Omitted marks/fields and mark order persist.

Sparse updates reuse the existing `image_annotate` tool. They do not change
source images, native code, calibration, FFT values, display defaults or client
configuration.

For example, use the current view ID and a fresh request ID, then pass:

```json
{"updates": [{"annotation_id": "stripe-a", "text": "possible streak", "color": "orange"}]}
```

Move an existing mark with `coordinates` in **that mark's saved anchor** space:
source pixels, imported array indices, or original cycles/pixel. This is not the
PNG coordinate system or the shortened displayed arrow tail. Kind, source ID,
coordinate domain and ID itself cannot be changed by a sparse update. Inspect
`image_info`/`panels` first; source-domain reassignment needs explicit replacement.
New geometry must pass the existing renderer's bounds/type/domain validation.

`status:"retracted"` hides the mark without deleting it or its history. A color,
position or text edit never automatically confirms the hypothesis. Existing
out-of-view anchors remain available for text/style/status edits. A legacy
cross-panel mark without a unique anchor permits text/style/status changes only;
replace it explicitly before changing coordinates. Old full-length arrows keep
their pre-cap behavior.

Unknown/duplicate IDs, no-op entries, an empty updates list and requests carrying
both lists fail. No current-view guessing, name matching, implicit additions or
array mutations occur. Requests use the existing same-ID recovery/conflict rules.
The exact immutable input `object_id` is the revision base; applying an edit to
an older view creates a branch from it rather than silently merging newer edits.

Validation is split: the standalone edit-planning tests do not prove complete
MCP or Windows behavior. Run the integration tests and existing image suites
against the applied target before publishing. This addition does not implement
physical calibration or a graphical selection panel by itself; those features
have their own contracts and validation.
