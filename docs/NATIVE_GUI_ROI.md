# Native GUI rectangles: explicit image, display and ROI identity

**Qualification: limited synthetic actual-host PASS.** The corrected direct
source-layout and coordinate contracts passed their own prepared-host native
MCP and independent oracle checks. The profile now admits `native_gui_rois`
for this narrow scope. The newly built qualified artifact also passed a separate same-build session
with independent source/ROI, original-STOP and final-reference checks. Tool presence alone is insufficient: the
exact supported GMS build, module fingerprints, readiness and optional-entry
gates remain mandatory.

The supported narrow workflow is: the user draws a rectangle in DM, the Agent reads
its exact identity and pixel edges, then submits an existing supported crop or
READ. This tool only inspects objects; it does not draw, select, crop, switch
workspaces or compute a measurement. It never invokes a Python listener or GUI
automation as its native implementation.

## Identity and coordinates

Call `dm_native_rois` with an explicit `image_id` and preferably a pre-saved
`request_id`. Source admission is bounded ordinary-packed 2D float32/uint32.
The response preserves:

- The same image ID and metadata, plus every admitted display's document and
  display component IDs. Reverse lookup must resolve to the same image object.
- Every ROI's ID, selected flag, type, native rotation and raw rectangle.
- `slice_ids`, `source_layout` and the native display coordinate mapping, together
  with eligibility or an explicit diagnostic.

Use the composite `(image_id, document_id, display_id, roi_id)` identity.
Neither a name, an ROI ID alone nor the latest/front window identifies the
selection. Multiple displays may show the same image, and selection is scoped
to a display. The tool does not choose among ambiguous or multiple selections.

Raw rectangle fields are `top,left,bottom,right`. An eligible `rect` is
`[left,top,right,bottom]` in source-pixel edges, with exclusive upper bounds.
Only finite, integral, nonempty, in-bounds, unrotated rectangles qualify.
There is no rounding, clipping or fallback to the full image.

This raster getter reports a **normalized** display mapping. Its selected-ID
getter returns slice identifiers, not axis identifiers: `slice_ids:[0]` must
never be reinterpreted as an axis list. Eligibility additionally requires the
exact fixed-build `ImageSource_Simple` class, a typed reverse identity matching
the requested image object, and its direct canonical XY size contract. This is
reported as `source_layout:"direct_image_canonical_xy"`. No axis-reorder getter
is used to infer that layout. Sliced, grouped, summed or other source classes
remain `source_layout:"unsupported"`.

With that direct-image layout and `slice_ids:[0]`, zero mapping offsets and
scales exactly equal to the native binary32 reciprocals of source width and
height establish `coordinate_mapping.source_pixel_aligned:true`. This is not
a claim that normalized coordinates are mathematical identity. GUI zoom is not
a reason to rescale an already source-pixel rectangle.

Fractional, rotated, out-of-bounds, degenerate or unsupported ROIs retain their
diagnostics with `analysis_eligible:false` and `rect:null`. Unsupported displays
or source layouts are not silently treated as ordinary direct-image data;
unsupported displays report `slice_ids:null` and `source_layout:null`.
Unreadable references, failed native getters, nonfinite values, broken reverse
identity or a changed snapshot fail the request; they do not become an empty
selection. A completed result may legitimately contain no displays or no ROIs.

The bounded enumeration limits are separate from scientific-operation budgets.
Spatial calibration is returned as metadata; an eligible pixel rectangle does
not waive crop, Fourier or physical-coordinate validation.

## Agent continuation

1. Confirm native backend, readiness, supported profile and available
   `native_gui_rois`. Resolve the user's explicit image ID through datasets.
2. Read `dm_native_rois`; retain the original session, request and full composite
   selection identity. Use only an explicitly chosen eligible rectangle. If
   selection is ambiguous, obtain the user's intended object before processing.
3. Save a new side-effect request ID and all arguments before `dm_crop`, or use
   an explicit bounded `dm_native_read` for numerical handoff. Pass the returned
   source-pixel `rect`; do not reconstruct it from a screenshot or physical units.
4. Continue on the exact returned result ID. Preserve dtype, calibration,
   provenance and request identity through the existing
   [lifecycle and handoff contract](NATIVE_LIFECYCLE_HANDOFF.md).

The response is an execution-time, non-atomic GUI snapshot. IDs, membership,
selection, geometry and source metadata are rechecked, but there is no source
lock or general concurrent-edit guarantee. Keep the source and selection idle.
QUERY of the same request ID returns its historical snapshot; refreshing the
current selection requires a new request ID. Cancellation or timeout calls for
querying the original record, not assuming an empty selection or resubmitting
an uncertain downstream crop.

Workspace auto-activation is not a prerequisite. Explicit-ID lookup crosses
workspaces; neither ROI enumeration nor SHOW guarantees an active tab or model
viewing. No native workspace-switch API is added here.

## Evidence and remaining gaps

The first actual-host discovery returned the expected raw document/display/ROI
identities and rectangle geometry, but rejected analysis eligibility under an
incorrect identity-mapping assumption. A subsequent actual-host observation
also exposed slice identifiers misread as selected axes: raw selected ROI
geometry was correct, but analysis eligibility failed. Both failures and the
immutable older QUERY snapshot remain preserved. Static tracing closed the
direct-image source/size contract. The corrected implementation then passed
actual native MCP enumeration for float32 and uint32 fixtures, multiple
documents, empty/hidden images and explicit ineligible fractional, rotated and
line selections. A manually drawn selected rectangle continued through exact-ID
native crop, mean, READ and multiblock NPY handoff. Independent same-process
observations matched full source pixels, calibration, selected identity,
rectangle and exported values. Repeated fresh queries kept the result pool
stable; an old empty QUERY remained immutable.

The original pre-saved STOP request was verified, sources and GUI ROIs remained
unchanged, and the hidden crop became invalid. A same-stack assertion that
fixture sources were already invalid immediately after closing owned documents
and removing fixture references **failed and remains preserved**. After the
one-shot returned to an idle host, a separate observation found those fixtures
invalid, documents restored and the fixture holder absent, without further
native operations. Qualification is bounded to release after host return/idle;
it does not promise synchronous destruction inside the same Python call stack.
Static reference accounting was checked separately. The qualified artifact
passed its own separate session, loaded-binary identity, source/ROI and
original-STOP checks, final references after host idle, normal exit and
manifest-owned removal.
Ordinary model-client acceptance remains **NOT_TESTED**.

Line selection and native LiveProfile bindings are separate ABI candidates.
They are not exposed by this rectangle tool. Native profile/histogram delivery
still needs its own typed call, ownership, axis/bin semantics, bounded 1D READ
and scientific handoff qualification. No new profile, histogram or annotation
tool is promised; unsupported ROI types remain explicit diagnostics.

The already completed region-export isolation repair was checked on a real
synthetic host using independent workspaces, reused user labels, changed
synthetic inputs and cached completed reuse without rereading. Exact files,
calibration, source protection and normal STOP/exit cleanup were checked; this
does not qualify the new ROI ABI. Fourier precision attribution is separate:
see [direct DM versus MCP comparison](NATIVE_FFT_PRECISION.md), which preserves
the original numerical FAIL and does not add a complex64 MCP export tool.

## Executed engineering checks

The full Node regression passed 169 tests, including the Windows synthetic pipe
end-to-end checks, with no skips. All eleven C++ offline executables passed;
the ROI adapter had 827 assertions including its serialized fixture check,
and the qualified profile had 1827 checks. The complete Python regression
passed 572 tests before the final targeted acceptance refinements; those final
changes separately passed all 13 ROI oracle and 6 precision tests. Default-backend selftest
passed. Synthetic peers and callbacks do not qualify DM ABI calls.

Negative coverage includes partial returned ROI objects on exceptions, wrong
image/document/display/ROI identities, native int32 object-ID bounds, foreign
host/session receipts, changed snapshots, unsupported source layouts, slice
paths and mappings, coordinate errors, and oversized or malformed evidence
arrays rejected before NumPy loads them. The real-DM checks above are separate
from these engineering checks; model-client acceptance remains NOT_TESTED.
