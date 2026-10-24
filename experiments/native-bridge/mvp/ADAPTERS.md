# GMS native adapter compatibility

The common Node MCP, NB2 request records, named pipe, host-thread dispatch and
retained-result lifecycle are shared. Vendor layouts, typed calls, module
fingerprints, exports and RVAs belong to a version adapter. Loading the plugin
does not qualify a host ABI or any processing operation.

| Host build | Adapter | Qualification |
| --- | --- | --- |
| Windows x64 GMS 3.53.4137.0, all pinned module identities matching | `gms-3.53.4137.0-windows-x64` | LIMITED_SYNTHETIC_REAL_HOST_PASS: final production DLL passed the public-MCP-to-NPY/external-mean workflow and same-host oracle without a preparation switch, original-STOP result release, normal exit and manifest-owned removal |
| Other GMS 3.x | None | NOT_TESTED; native operation admission is UNSUPPORTED_BUILD |
| Unknown build or architecture | None | UNSUPPORTED_BUILD when identity is readable; otherwise NOT_READY |

The uint32 extension is separate from the float32/complex production evidence
above. Its prepared synthetic trial passed `PASS_BOUNDED_UINT32`, original-STOP
output release, normal host exit and manifest-owned plugin removal. The final
uint32 production DLL independently repeated the full workflow and same-PID
oracle in a fresh host, including its own original STOP, output release,
normal exit/removal and saved-data reopening afterwards. Its temporary
preparation switch was removed. This is limited synthetic qualification;
see [the uint32 record](UINT32_ACCEPTANCE.md). No earlier float32 PASS is
substituted for this production artifact's observations.

The subsequent [uint32 operations extension](UINT32_OPERATIONS_ACCEPTANCE.md)
has its own final normal-handler qualification: 32 newly created synthetic
outputs through Node MCP and a same-PID numerical oracle, two-result visible
delivery, original STOP, document-held/last-reference release, normal exit,
manifest-owned removal and unchanged uint32/float32 NPY reopening afterwards.
Its four additional operation groups do not admit another GMS build or expand
the underlying five-module fingerprint gate.

The line/profile continuation adds `native_line_profile` and ROIS version 2
under this same exact adapter. The catalog now has nineteen entries. Limited
prepared synthetic-host acceptance passed explicit GUI line identity, true 1D
float64 extraction/NPY, unchanged source/GUI/documents, original-ID recovery,
RELEASE/STOP after-idle invalidation and normal exit/removal. Profile admission
is enabled for that narrow scope. The final qualified artifact independently
passed a fresh session with loaded identity matched to the source build,
post-idle baseline before MCP, directional/boundary controls, exact 1D values,
NPY and source/GUI invariance. Original release/STOP, idle-reference invalidity,
normal exit/removal and post-exit reopening passed. This is the artifact's own
evidence; earlier rectangle or uint32 qualification does not substitute for it.
These remain API-created synthetic GUI fixtures, not experimental data or
ordinary model-client acceptance.

Admission requires width one, nonzero integer horizontal/vertical pixel-centre
endpoints, complete equal signed scales/units, ordinary float32/uint32 2D direct
source and at most 4096 samples. Both ordered endpoints are included; output is
native rank-one float64 with its actual signed axis and copied, unapplied
intensity calibration. Known retained Fourier/unresolved lineage is refused.
Frozen response bytes can be explicitly encoded to true 1D NPY; this does not
extend 2D READ/SHOW or add a general spectrum/histogram pipeline. See
[the full profile contract](../../../docs/NATIVE_LINE_PROFILE.md).

Failed fractional-fixture geometry and STOP-oracle assumptions remain preserved.
The successful session first passed an independent integer-fixture baseline
after host idle. STOP is worker-acknowledged with `exec_tid:0`, not a scientific
host callback; the original worker, request, PID and `ipc_stopped:true` remain
mandatory. No fingerprint or numerical/source check was relaxed.

This is a multi-version **selection architecture**, not a claim of multi-version
GMS support. Synthetic version tests do not qualify another GMS build. The new
selection integration itself must be distinguished from historical host passes.
The first new prepared session completed normal host exit with code 0. Its
Fourier records use the prepared v1 schema. A second synthetic host independently
passed the public MCP workflow, including Fourier v2 FFT/IFFT/REAL, four filters,
READ bit preservation, NPY reopening and an explicit external mean. Its original
STOP, same-host release of all 11 explicitly recorded outputs, unchanged nine
sources/document count and persistent capture hashes passed, followed by normal
exit code 0 and manifest-owned removal. Those two runs used prepared binaries.
The final production-admission DLL has now separately passed the third-host
public MCP workflow and same-PID independent oracle, with loaded artifact identity
bound and no preparation environment switch. Its own original STOP and same-host
oracle verified release of all nine unshown outputs, unchanged nine sources and
document count, and persistent capture hashes. It then exited normally with code
0 and completed manifest-owned plugin removal. A new explicit external run after
host exit reopened the saved NPY and obtained the same mean without changing its
capture. These are separate third-host observations, not inherited lifecycle
claims. See
[operation acceptance](OPERATIONS_ACCEPTANCE.md) for exact numerical/lifecycle
scope and [the workflow](NATIVE_WORKFLOW.md) for explicit handoff commands.

## Admission and diagnostics

Before entering a vendor implementation, `adapter_identity_win.hpp` reads only
Windows loader/file metadata. It identifies the executable, exact version and PE
architecture, selects an exact profile and checks each required module version,
architecture and SHA-256. Only then does it resolve explicitly listed symbols.
It does not load another copy of a vendor DLL, scan for entrypoints or invoke a
vendor function to discover its ABI.

`dm_status` keeps its existing fields and adds adapter/host compatibility and
per-capability diagnostics. A safe status response on a rejected host does not
mean an image operation can run.

- `SUPPORTED`: an exact qualified profile and all core requirements match.
- `UNSUPPORTED_BUILD`: readable GMS identity, no exact qualified build/architecture.
- `ABI_MISMATCH`: a selected build has a different fingerprint, module version,
  architecture, required symbol or violated adapter contract.
- `NOT_READY`: host identity or a necessary loaded module cannot yet be verified.

The existing five module fingerprint gates remain in force. A missing optional
operator or invalid optional executable-entry contract disables its capability,
with a reason, while safe core metadata operations remain usable. Neither an
export name nor a synthetic call marks a scientific operation qualified.

Capability names include `native_statistics`, `native_crop`, `native_display`,
`native_image_arithmetic`, `native_fft`, `native_filters`, `native_preview`,
`native_read`, `native_gui_rois`, `native_line_profile` and `native_save`. Each profile declares qualification, scope and
required symbols or entry contracts. The five added groups are now qualified
for the bounded scope below; status reports `LIMITED_REAL_HOST` only when their
complete required bindings are available. This is a profile declaration backed
by the recorded limited experiments, not proof that every newly built DLL has
completed its own host acceptance.
`native_statistics` denotes the complete four-reduction SUMMARY set. The
separate `native_mean` capability can remain available when an optional SUMMARY
reduction is missing; neither a partial group nor an export lookup qualifies a
new operation. Unavailable published operations reject before entering the
version implementation or looking up an image. Production has no
`DM_NATIVE_QUALIFY_OPERATIONS` admission switch: setting that former preparation
variable cannot enable an unqualified or missing capability. Status lists the
qualified available groups and no candidate-execution bypass. A catalog listing
or a broader default Python tool does not override admission. Native SaveAs
remains unqualified; the explicit saved-READ-to-NPY encoder does not implement
DM file saving.

Uint32 has five separate dtype capabilities: `native_uint32_mean`,
`native_uint32_statistics`, `native_uint32_crop`, `native_uint32_preview` and
`native_uint32_read`. A capability must be qualified and have its complete
bindings; uint32 mean does not require the optional SUMMARY reductions.
The fixed-build descriptor is code 11 with `is_integer:true`,
`is_unsigned:true` and packing 1. The booleans describe that fixed-build type
mapping, not calls to additional vendor type getters. Type-code, actual uint32
storage and high-bit numerical reads need joint real-host acceptance.
Statistics stop at 2,097,152 pixels. Uint32 crop checks its 4,194,304-pixel source
bound before allocation, keeps dtype and complete calibration, and limits output
to 4 MiB. Preview/READ source bounds remain 4,194,304 pixels; preview samples at
most 128x128, while READ returns at most 16,384 four-byte values. Their original
float32 contracts are retained. Four additional groups, `native_uint32_display`,
`native_uint32_image_arithmetic`, `native_uint32_filters` and `native_uint32_fft`,
have [separate operation qualification](UINT32_OPERATIONS_ACCEPTANCE.md).
Their native input/output types and precision are explicit, including binary32
rounding and integer-filter saturation/truncation. Qualification of one group
does not qualify another. SaveAs remains unqualified, as do other integers, native
4D, experimental data or model-client viewing.

## Adding one version

1. Add a version directory beside `adapters/gms_3_53_4137`. Keep its own module
   identities, ABI POD layouts, signatures, ownership rules and exact entrypoints.
   Recheck string allocation/release and owned-reference final release; do not
   copy a C++ class layout or cross-compiler STL object by assumption. Never add
   an approximate version range to the existing profile.
2. Register its profile with the common selector and add offline rejection tests.
   Cover unknown version/architecture, changed fingerprints, missing optional
   symbols and invalid entry ranges. Fail before any vendor image call on an
   unknown/mismatched build. Synthetic profiles remain test-only until qualified.
3. On that exact host, record the loaded binary and actual PID/session, then
   qualify each proposed capability with new small synthetic inputs. Bind saved
   request IDs/arguments, direct native results and independent raw snapshots;
   test signed calibration, type/shape/packing, finite/domain errors, source
   invariance and independent memory. Do not inherit another version's Fourier
   sign, phase/power, filter edge or file semantics.
4. Verify duplicate/conflict and fresh QUERY behavior, document ownership,
   STOP pipe/window cleanup, shown/unshown result release, final close and normal
   exit separately. READ must also pass bitwise external NPY reopening and its
   provenance/hash chain; a preview is not that proof. No force-close or loaded
   plugin replacement substitutes for normal lifecycle acceptance.
5. Only then promote that profile's individual qualification declarations and
   publish the matched tool/result schemas with bounded evidence. Keep missing
   capabilities unsupported; optional groups may differ by version. A result
   contract change needs its own version, not relaxed validation of old records.

Request IDs, original-operation identities, QUERY recovery, pixel coordinates,
axis order, raw-intensity semantics and reference ownership do not change with a
new adapter. New scientific semantics need an explicit result contract/version;
they must not be silently inferred by Node from arbitrary JSON fields. The
default v0.6 Python backend remains separately selected and unchanged.
