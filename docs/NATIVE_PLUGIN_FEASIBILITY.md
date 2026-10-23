# Native plugin route: feasibility assessment

Status: historical assessment. This assessment itself changed no production
code, tool or bridge; that statement describes its original scope, not the
repository's current implementation. Nothing here is supported by Gatan.

The subsequent [native MVP](../experiments/native-bridge/mvp/README.md) now has
limited acceptance on its pinned build with an idle host and serialized
requests, including core MCP/mean and independent crop/cleanup checks. The
default Python backend remains unchanged. Current evidence and remaining
limits belong to [RESULTS.md](../experiments/native-bridge/RESULTS.md), including
the ASCII-qualified name scope and unqualified non-ASCII interoperability.
Concurrent native/script image access remains unverified and is not a
prerequisite for that accepted idle-host scope.

## Question

The current bridge runs as resident Python inside DigitalMicrograph, which
consumes the single script-execution slot and makes re-entrancy risky. Before
committing to that design, we asked a narrower question:

> Without the vendor C++ SDK, is a native plugin route reachable at all — one
> that keeps DM's own image objects, calibration and processing, and does not
> depend on resident embedded Python?

## Method

1. Read-only inspection of the locally installed product modules (headers,
   import/export tables, string literals, entry-point code) — no patching, no
   patching of licence checks, no injection into a running session.
2. Comparison with public open-source plugins to establish what a third-party
   plugin is expected to provide versus what the vendor library provides.
3. Two minimal probe DLLs, built from scratch with no SDK and no C runtime, used
   to test the load gate and script-function registration.

Vendor binaries, decompiled output, addresses, offsets and build fingerprints
were **not** published and are not part of this document.

## Findings

| Question | Result |
|---|---|
| Does the product accept a third-party native plugin at all? | Yes. A minimal DLL that reports a compatible interface version is loaded and taken through its initialize / start / run phases. |
| Is the accepted interface version negotiated, not assumed? | Yes. A plugin states the interface generation it was built against; mismatches are rejected with an explicit "not compatible" path. |
| Can a plugin register a script function visible to DM script? | Yes. A function registered by the probe resolves in a DM script and returns the expected value. |
| Is a vendor marshalling layer required to expose a function? | No. A plain C function was callable; the registration is a property of the interface object the host hands to the plugin. |
| Are image access, calibration and pixel-buffer locking reachable natively? | Yes, and the shipped vendor plugins use the same paths, so these are maintained entry points rather than incidental symbols. |
| Is anyone supporting this? | No. It is an undocumented interface with no compatibility promise. |

## Operational findings worth keeping

These are product behaviours, independent of any reverse engineering, and they
matter for this project's own launchers:

- A second instance refuses to start while another instance is running, and it
  does **not** forward a script command to the running one. Script execution at
  launch therefore requires the instance to be started with the command.
- Executing a script *file* at launch failed in our environment with a
  file-not-found error for every path form we tried, while executing an inline
  command worked. Any launcher that depends on script-file execution should be
  verified on the target machine rather than assumed.

## Limits

- **Threading and re-entrancy are unresolved.** We verified registration and a
  single call on the normal path. Whether a worker thread may initiate work,
  and whether the image or script engine tolerates re-entry while a script is
  running, is exactly the question this route was meant to answer — and it is
  not answered yet.
- **Per-build fragility.** The interface has no published contract. Every
  conclusion above is tied to the build it was measured on and must be
  re-checked after any product upgrade.
- **Licence and support.** Using an undocumented interface is unsupported and
  may conflict with the product's terms. It is not a substitute for the vendor
  SDK, which is available on request.

## Historical recommendation

Ask the vendor for the SDK first. It removes most of the uncertainty above at
the cost of a request form, and it converts "a measured snapshot" into "a
documented contract".

At this assessment stage, the proposed gate was whether a worker could safely
hand work to the main thread while a script was running. Registration alone
did not answer that question. The later MVP deliberately qualified idle,
serialized post-acquisition operations instead, without making concurrent
image access a condition of that narrower result. Do not apply this historical
gate as a current requirement to perform concurrent experiments, or inherit
its early probe observations as acceptance of changed code.
