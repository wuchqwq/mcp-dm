# Native core partial integration

## Accepted scope

Main integrates the previously reviewed native MVP snapshot `3c9715c` as an
**explicitly selected experiment**, not as a stable replacement for v0.6.
The Python backend and its existing 21-tool catalog remain the default.
The native catalog contains status, datasets, raw native mean, result query
and a plugin-retained crop. The native adapter retains its exact build gate,
ASCII-qualified scope, idle-host/serialized-operation requirement and existing
bounded ownership rules. No native runtime or ABI code is changed by this
integration follow-up.

One facade-only safeguard is added: native `dm_crop` requires a caller-saved
`request_id` before any submission. Missing/invalid IDs fail before dispatch.
An old ID can only recover a result in its original live session, not after
STOP, host restart or a new session. Read-only tools keep optional IDs.

## Deliberately not integrated

The later commits through `6837bab` remain on `feature/native-bridge-mvp`:
visible document SHOW and lifetime handoff, relaxed spatial-calibration policy
for raw mean, the latest client-trial scripts, cross-client Windows E2E/fault
injection additions, and the latest Unicode investigation. They form one
uncompleted trial revision and must not inherit this baseline's acceptance.
Do not cherry-pick those tests alone: they depend on the later implementation.

The current feature trial remains HOLD. Its pending desktop/document checks,
independent pixel/source checks, post-STOP ownership, final document-reference
release, normal removal and actual WorkBuddy use must be completed separately.
The last reported local state was stopped experimental IPC with the test DM
and DLL still loaded; this document does not assert the current machine state.

Before further host acceptance, fix the reviewed trial-oracle gaps: bind the
actual oracle process PID, validate the saved STOP request identity, and
preserve bytes/str distinctions in the Unicode diagnostic. Do not retrofit
old PASS evidence or guess an encoding conversion.

## Validation boundary

The integration follow-up runs isolated Python, Node and mock regression;
Windows synthetic native tests are recorded separately when run. No genuine
DM process, installation or scientific data is accessed here. Historical
real-host evidence belongs to the unchanged baseline implementation, not to
new operators or broader compatibility. No Release/tag is created.

## Continuing development

Keep the existing feature branch; do not reset or force-push it to this
snapshot. Fetch main and reconcile the small request-ID/doc changes by a
normal merge when needed. Preserve newer feature code and its HOLD notes.
Unlocking the desktop permits inspection; it is not by itself acceptance.

The initial integration regression exposed a test-only Windows short/long
path comparison mismatch. The corrected test checks absolute paths and real
file identity while retaining the checksum, ownership and foreign-file
protection assertions. Installer implementation and deletion rules are unchanged.
