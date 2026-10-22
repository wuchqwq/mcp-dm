# D0 handoff: client-readiness candidate

D0 means code-side review, synthetic validation and a fixed testable delivery. P0 means the user's actual DM/client/model acceptance. These are separate gates, not assertions that a model is more or less capable than another.

Baseline: `4127953115936ec480fd55d1250d4337c850fd85` (`feature/2d-analysis-loop`). Delivery branch: `release/d0-client-candidate-20261022`. Record its exact SHA when starting local acceptance; do not silently switch versions mid-test.

## Changes

- Keep the local worker hard deadline alive after a client cancels its wait. Clear it only at process close/spawn failure; request termination at the deadline without claiming side effects were rolled back.
- Handle stdin pipe failure, invalid response envelopes and output overflow as tool failures, not uncaught process errors. Reject oversized input before spawning and stop buffering after cancellation/overflow.
- Reject negative/unsafe image IDs, non-positive source ROIs, coincident profile endpoints and blank operation IDs before dispatch.
- Return captured x/y calibration and metadata identity with previews so a general client need not read sidecar files or query a live image for stale calibration.
- Correct misleading tool descriptions; distinguish DM health from external preview dependency failures. Keep reports optional and all existing tool names.
- Provide generic preview config, a manually invoked two-image synthetic fixture and a short ordinary-client acceptance checklist. Do not auto-install Skills or modify user/client settings.
- Ignore local preview environments and WorkBuddy settings to reduce accidental commits of machine-specific data.

## Validation gate

The isolated Windows check must first reproduce the old cancellation-deadline regression, then apply the guarded repair and run all Python, Node and mock suites. A test that fails before the repair is expected red/green evidence, not a claim that the baseline was fully valid. Temporary workflow/builder files are excluded from the product commit; normal Actions remain manual.

No real DM, WorkBuddy UI or actual model is available in this hosted check. These remain `NOT_TESTED`. Python 3.7 syntax checking is not GMS runtime validation. Full process memory, crash recovery, multi-client scheduling, authentication and directory authorization are not added here. Cancelling a wait does not cancel a native DM operation; the external worker deadline is not a global process-lifetime guarantee after server/OS failure.

## Local handoff / 本机交接

See [CLIENT_ACCEPTANCE.md](CLIENT_ACCEPTANCE.md). Test without the Skill first. Do not compensate for missing MCP capabilities by letting a stronger coding agent silently rewrite the workflow. Small setup assistance is fine; record it. Do not classify a client transport/rendering limitation as a numerical error or as proof of model incompetence.

Keep this as a candidate until local P0 is recorded. No stable tag, release announcement or automatic merge is implied. 4D-STEM expansion and new analysis algorithms remain deferred.
