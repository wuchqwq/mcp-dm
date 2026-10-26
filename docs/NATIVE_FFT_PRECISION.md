# Native FFT precision: error attribution and bounded evidence

The native bridge calls DM's `GMSImageProcessing::Real_FFT` and `IFFT`.
It does not cast the input pixels, replace the transform with NumPy, or promise
a lossless integer round trip. The supported build and fingerprint gates remain
unchanged; see [Fourier contracts](../experiments/native-bridge/mvp/FFT_READINESS.md).

## Size, operation and memory admission

The base scope remains power-of-two axes 4..256, at most 65,536 pixels.
Version 2 has a bounded extension to power-of-two axes 4..1024 and at most
1,048,576 pixels. An axis above 256 requires the matching available large
capability for each operation and original float32/uint32 lineage. Forward,
inverse, real, imaginary, phase and power have separate groups; a complex64
storage dtype does not erase uint32 lineage. Large uint32 inverse remains
unqualified. Historical v1 QUERY records keep their original smaller contract.
Consult actual `dm_status.native_capabilities`; a transport validator accepting
a descriptor is not scientific qualification of that operation or loaded DLL.

Fourier complex results are bounded to 8 MiB and scalar results to 4 MiB. The
shared retained-result pool stays at 16 MiB/32 objects, with known validation
temporaries included in admission. Inverting a retained 1024-square spectrum
needs 20 MiB of accounted images and must fail before the native transform.
A permitted dimension does not promise sufficient remaining pool capacity.
Vendor-private workspaces are not a bounded total-process-memory guarantee.
FILTER remains independently limited to axes 5..256; scalar READ still admits
at most 16,384 samples per block. Larger scalar handoffs use the existing
chunked NPY/schema-1 path, without changing Fourier values or frequency axes.

Persist the request ID, session and exact arguments before every producing
call. Cancellation/timeout stops waiting, not the DM operation: query the
original ID, never resubmit an unknown operation. SHOW then RELEASE can leave
an exact result held by its document; RELEASE drops only plugin ownership.
Creation QUERY stays immutable, while fresh RESULT_INFO checks availability.
Records are volatile across STOP/host exit; file persistence is a separate
validated handoff, not a side effect of receiving an image ID.

## What the comparison separates

The acceptance tools compare the same explicit input through two paths:

- Actual Node MCP → native bridge → DM transform, followed by exact-ID host
  observation and native READ of the inverse real component.
- A separate, fixed, one-shot DM-Script `RealFFT(source)` → `IFFT(spectrum)`
  control, with explicit source and output IDs. Both outputs must be ordinary
  full-complex data; packed complex or `RealIFFT` is not an equivalent control.

The fixed convention is a positive-exponent, unnormalized, centered forward
transform and a negative-exponent inverse normalized by the pixel count.
The verifier never searches for the best-matching sign, shift or normalization.
Native calibration and mathematical frequency bins remain distinct.

For original input `x`, let `q` be its binary32 conversion, `F` the stored native
complex64 spectrum, and `z` the stored native inverse. The external verifier
reports these separately:

| Diagnostic | Meaning |
|---|---|
| `q - x` | Input conversion error, before the transform |
| `F - reference_forward(q)` | Error in stored forward components |
| `reference_inverse(F) - q` | Error already represented by the stored spectrum |
| `z - reference_inverse(F)` | Additional native inverse error |
| `real(z) - x` and `real(z) - q` | Complete round trip against original and converted inputs |
| Direct DM versus MCP, and READ versus host pixels | Bitwise comparison of the actual stored values |

The reference calculations use external float64/complex128 arithmetic only as
an independent numerical oracle. Their maxima are separate diagnostics, not
an additive identity or a rigorous decomposition of every floating-point error.
Imaginary inverse residuals are reported independently.

The absolute round-trip threshold remains the predeclared **0.5 raw intensity
units**. The forward threshold remains the predeclared factor of input absolute
sum in `fft_precision_fixture.POLICY`. Neither is fitted after observation.
Bitwise path equivalence can pass while numerical accuracy remains
`FAIL_NUMERICAL_TOLERANCE`; the verifier returns nonzero for that numerical FAIL.

## Observed scope

The bounded larger-window continuation has separate exact-build synthetic
numerical and lifecycle qualification. An authorized read-only experimental
forward workflow also passed exact-ID crop/FFT/power readback, independently
reopened scientific exports, unchanged original pixels/calibration/file, and
document ownership after original-request STOP. Exact owned closure, separate
idle invalidity and normal host exit were checked independently. This is
limited forward/handoff evidence, not integer inverse qualification or unique
phase identification; interrupted historical sessions retain their missing
evidence and are not repaired by a later process.

Fixed synthetic controls include low values, high unsigned values with
conversion loss, and representable integer values with no input conversion
loss, each paired with its exact binary32 input. Actual host observations found
bitwise agreement between the direct DM and MCP transform outputs, between
paired input-type controls, and between native READ and the stored inverse real
component. Some controls still failed the original round-trip accuracy threshold.

A separately authorized copy of an already saved experimental ROI input also
reproduced the historical stored FFT and inverse bitwise. Its direct DM and MCP
paths agreed bitwise, as did READ and host pixels. Its input conversion was exact,
yet the original round-trip accuracy FAIL remained. This rules out an additional
MCP value difference for that reproduced input and distinguishes the observed
failure from input conversion loss. It does not claim that every unsigned input
has exact conversion or that DM Fourier processing is generally lossless.

That control used an equivalent new work image from the saved bounded input.
The original scientific file was not reopened or modified; this is not a fresh
original-file acquisition or provenance check. Source pixels and metadata were
checked unchanged in the test host. Owned hidden results, documents and normal
host exit were checked separately. Historical FAIL records were preserved.

These historical small-input comparisons do not qualify the larger-size
extension, another GMS build, arbitrary complex input, concurrent editing, or
an ordinary model/client workflow. Any larger operation requires its own
numerical and lifecycle evidence, with the original accuracy policy retained.
No numerical algorithm or tolerance was changed to make the failure disappear.

## Reproduce the fixed synthetic comparison

These are explicit acceptance helpers, outside the MCP/plugin runtime. Use a
prepared idle test session with the qualified build, a fresh private directory,
and an actual native `dm_status` showing `digitalmicrograph-native`, ready and
`SUPPORTED`. Keep its session, process identity and original receipts. Do not
run the persistent Python bridge or a listener.

1. In a one-shot host Python script, put the repository's
   `experiments/native-bridge/mvp` directory on `sys.path`, then call
   `observe_fft_precision.create(trial_directory, session, actual_host_pid)`.
   The helper checks the actual process and prepared session environment,
   creates only new fixed inputs plus a dedicated control image, and saves
   `fixture.json`. Keep existing unrelated documents unchanged.
2. For every entry in `fixture.json` → `images`, use its explicit image ID and
   dimensions. Persist a distinct request ID, session and complete arguments
   **before each submission**, then call the actual native MCP in this order:

   | Saved result key | Tool and parameters |
   |---|---|
   | `fft` | `dm_native_fft`: source `image_id`, `direction:"forward"`, saved `request_id` |
   | `ifft` | `dm_native_fft`: returned FFT ID, `direction:"inverse"`, saved `request_id` |
   | `real` | `dm_native_complex`: returned inverse ID, `component:"real"`, saved `request_id` |
   | `read` | `dm_native_read`: returned real-component ID, `rect:[0,0,width,height]`, saved `request_id` |

   Save parsed result objects, including their original `native_receipt`, in
   `native-map.json` as `{fixture_label:{fft:result,ifft:result,real:result,read:result}}`.
   Do not save an MCP text-content wrapper in place of a parsed result. On an
   uncertain request, query its original ID; do not repeat the operation.
3. In the same host, call
   `observe_fft_precision.observe(trial_directory, actual_host_pid)` once.
   If that module was loaded before a source update, explicitly reload it first.
   The fixed direct script is saved before execution. Its result IDs are handed
   back through the new control image's tags, never inferred from names or the
   latest window. The helper checks full-complex types and source invariance,
   then saves `observation.json`. Preserve a partial failure; do not overwrite
   evidence or blindly rerun direct operations.
4. In external Python with NumPy, run:

   ```text
   python -B experiments/native-bridge/mvp/verify_fft_precision.py --directory TRIAL_DIRECTORY --host-pid ACTUAL_HOST_PID --session SAVED_SESSION --output NEW_VERDICT_JSON
   ```

   Inspect both the numerical verdict and the separate bitwise equivalence
   fields. An output file or a completed native receipt alone is not a PASS.
5. Follow the existing native acceptance cleanup procedure: preserve the original
   STOP request before dispatch, verify owned unshown results become invalid,
   close only owned test documents, and exit the test host normally. Do not force
   restart DM or replace a loaded DLL. Reopen evidence externally as needed.

The fixed helpers enforce small bounded inputs, require exact identities and
never modify source pixels. Their full-complex NPY snapshots are **acceptance
oracle observations through one-shot host Python**, not a newly implemented
MCP complex64 READ/export facility. Native user data handoff still follows the
supported scalar READ and [existing lifecycle/export contracts](NATIVE_LIFECYCLE_HANDOFF.md).
