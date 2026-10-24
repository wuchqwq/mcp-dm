# uint32 native operations and result delivery

This extends the separately qualified [uint32 read/crop/statistics subset](UINT32_ACCEPTANCE.md).
DM executes every scientific operator. There is no bridge pixel cast, substitute
kernel, Python listener or native-backend fallback. Only the exact fingerprinted
Windows x64 GMS 3.53.4137.0 adapter is eligible. Real experimental ADF data and
ordinary model clients remain NOT_TESTED.

## Input and output types

| Operation | Native input → output | Numerical contract |
| --- | --- | --- |
| negate / abs / square | uint32 → float32 | DM loads the integer into binary64, applies its operator and rounds the result to binary32 |
| add / subtract / multiply | uint32 + uint32 → float32 | DM operates in binary64, then stores binary32; no mixed dtype, broadcasting or division |
| smooth / sharpen | uint32 → uint32 | Native double coefficient accumulation; negative output saturates to 0, overflow to UINT32_MAX, otherwise fractional output truncates toward zero |
| sobel / laplace | uint32 → float32 | Native convolution; Sobel combines its native float32 gradient components |
| forward FFT | uint32 → complex64 | DM first rounds input to binary32, then performs its existing positive-exponent, unnormalized, centered transform |
| paired inverse / components | own retained complex64 → complex64 / float32 | Existing Fourier v2 lineage, normalization, frequency-grid and calibration rules apply |
| visible document | exact eligible retained result → same image | A document holds the image independently of the plugin; no file is saved |

`dtype_semantics` identifies the immediate input types, actual native output
type, selection by the DM operator and precision. A float32 or complex64 result
is **not lossless for arbitrary uint32 values**. In particular, the FFT input
rounding differs from the arithmetic path. Multiplication does not promise an
exact 64-bit integer product. Integer smoothing/sharpening also quantizes or
saturates its computed values. Intensity calibration is not applied.

Use READ on the original uint32 image when exact original samples are needed.
READ on a processed float32 result exports that result as `<f4`; it must not be
relabelled `<u4` because its ancestor was uint32. Scientific data handoff uses
the existing NPY/schema-1 capture, with actual dtype, axis order, signed scales,
raw origin, physical pixel zero, ROI and immutable creation provenance. This
encoder is not DM SaveAs. PNG remains display-only.

## Admission and lifecycle

All inputs are ordinary-packed 2D images with complete usable spatial
calibration. Arithmetic uses the shared 4 MiB per-result budget; filters use
axes 5..256 and FFT uses power-of-two axes 4..256. The shared pool remains at
most 32 results and 16 MiB, without eviction. Native internal workspaces are
not claimed to have a complete process-memory bound. Sources must remain idle
and must not be edited concurrently.

SHOW accepts an exact plugin-retained eligible uint32 crop or qualified
Smooth/Sharpen result, not an arbitrary source or the latest window. It does
not copy pixels, save a file or demonstrate that a model has viewed an image.
STOP releases the plugin's references. A displayed document may continue
holding its image until that document closes or the host exits.

Save request ID, session and arguments before every image-producing operation
and SHOW. Recover with QUERY of that original ID; an unknown or timed-out
operation is never automatically resubmitted. Same ID with different arguments
fails; completed same-ID requests reuse the original record. Recovery is
limited to the same still-queryable session, not STOP or a host restart.

## Qualification stages

The initial private preparation build has separately recorded raw NB2 calls,
same-PID detached observations, fixed numerical comparisons and three SHOW
lifecycle phases. Its unqualified high-dynamic-range Fourier observations
remain historical NOT_QUALIFIED records. They are not rewritten as final MCP
qualification. The preparation host exited normally and its manifest-owned
DLL was removed after exit.

On 2026-10-24, the final normal-handler artifact passed a fresh synthetic
real-host trial through the actual Node stdio MCP. A separate same-PID oracle
qualified all 32 recorded outputs and confirmed all nine sources unchanged.
The final binary and its frozen source hashes were checked independently.

| Scope | Result | Evidence boundary |
| --- | --- | --- |
| Native arithmetic, filters and Fourier | PASS, limited | 32 outputs, including crop, inverse/components, high-bit, saturation, non-square impulse and 256-square controls; independent raw pixels, actual dtypes and calibration |
| Original-ID recovery | PASS | Fresh clients queried the same 32 records without creating another result; this trial did not inject cancellation |
| Scientific handoff | PASS, limited | Actual uint32 filter and float32 arithmetic READ results, exact reopened NPY bytes, metadata and explicit external examples |
| SHOW and ownership | PASS, limited | Exact crop and Sharpen objects; original/repeat/QUERY/new-ID reuse create only two documents; 11 total source/result documents |
| Original STOP | PASS | Pre-saved original STOP identity and actual-PID receipt; only the two shown outputs remain valid, all 30 unshown outputs release |
| Last document reference | PASS | Closing only the two delivered documents invalidates all 32 outputs and restores nine unchanged source documents |
| Normal host cleanup | PASS | Normal exit code 0, then exact manifest-owned DLL removal; no loaded DLL replacement |
| Persistence after exit/removal | PASS, limited | Both saved uint32/float32 captures reopened byte-for-byte with matching ROI/calibration; external examples ran again in new directories and all 49 original files retained their hashes |
| Real experimental files / ordinary model client | NOT_TESTED | Only new synthetic sources and the strict protocol client were used |

The initial final-client attempt completed all native operations and READs,
then failed to launch an explicitly requested external example because its
Python executable path was wrong. That FAIL and its files remain immutable.
A narrowly validated `--resume-report` path used a new client to QUERY all
original IDs and encode the already saved READ responses into fresh captures.
It does not resubmit producers or accept arbitrary partial/unknown attempts.
Executable validation now happens before starting the client or creating files.
A completed receipt alone does not qualify scientific values or lifecycle.

The final procedure uses a fresh synthetic fixture, including high-bit values,
saturating filter cases and a 256-square boundary control. All original requests
are persisted before submission. A separate in-host oracle binds its actual
PID to the native receipts and compares source/result arrays, dtype, shape,
axis order, spatial/intensity calibration, memory independence and reopened
NPY bytes. SHOW is submitted only after that numerical check passes.

For the preregistered small dense high-range FFT control, the acceptance policy
is complex absolute error at most `32 * 2^-24 * L1(round_binary32(input))`,
against an independent exact-quarter-turn DFT. This is an empirical acceptance
tolerance for that fixture, **not a general theoretical FFT error bound**.
Low-valued controls, the impulse and the constant boundary have separate
strict value checks; arithmetic and integer-filter references are fixed from
their independently traced native conversion rules. Fourier zero sign is not
specified; scientific READ/NPY byte preservation remains exact.

After original STOP, the two explicitly delivered result documents must retain
their unchanged images and all unshown recorded outputs must be invalid.
Closing only those documents must release the remaining result IDs and restore
the source document count. Normal host exit, manifest-only removal and reopening
the saved captures complete the test. Historical evidence is never overwritten.

## Reproduction entrypoints

Use a new idle synthetic session following [INSTALL](INSTALL.md), with its
session and private evidence directory set before normal launch. Run
`create_uint32_production_fixture.py` once in the ordinary Python
editor; it creates only this test's synthetic sources. This is a one-shot
fixture, not a runtime bridge.

Run `accept_uint32_operations_mcp.py` outside DM, then the independent
`verify_uint32_operations.py` once inside that same host. The client uses the
normal Node stdio MCP and explicit NPY encoder; it cannot certify live source
protection or GUI visibility. After a successful independent numerical check,
record and submit SHOW for the two explicit verified targets, then run the
production lifecycle oracle before STOP, after STOP and after closing only
those result documents. Preserve the original STOP request and receipt.

Native SaveAs/Open, direct complex scientific export, other GMS builds,
concurrent native image calls and non-ASCII legacy name interoperability are
not qualified by this extension. The default v0.6 backend is unchanged.
