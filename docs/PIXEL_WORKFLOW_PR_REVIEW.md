# Pixel workflow: integration review

This review separates branch dependencies from qualified behaviour. It does not
merge a pull request or qualify a new native operator or model client.

| PR | Base | Reviewed head | Contribution |
| --- | --- | --- | --- |
| [#12](https://github.com/wuchqwq/mcp-dm/pull/12) | `main` | `c8723c1` | Optional external crystallography companion and bounded larger native Fourier operations |
| [#13](https://github.com/wuchqwq/mcp-dm/pull/13) | PR #12 branch | `e1edc52` | Three-file validation-history and automatic-localization wording correction |
| [#14](https://github.com/wuchqwq/mcp-dm/pull/14) | `main` | `370909a` | Six documentation files describing the planned iterative image/FFT workflow |
| [#15](https://github.com/wuchqwq/mcp-dm/pull/15) | PR #12 branch | `3c7fa25` | Explicit native uint16 sequence-frame working copies and scientific handoff |

`feature/pixel-image-workflow` starts from PR #15, so it already contains PR #12.
PR #13 and PR #14 are independent additions to that starting point. Integrate
their actual commits with normal three-way resolution; do not replace current
files with entire older branch snapshots. In particular, a two-tip diff against
PR #14 contains the absence of PR #12 code, not deletions made by that docs PR.
Preserve the current native catalog, FRAME support, Fourier limits and researcher
homepage when resolving overlapping documentation.

This integration branch now includes both reviewed heads through normal local
three-way merges. README conflicts retain the twenty-tool FRAME support and
optional companion while incorporating the iterative-workflow direction.
Upstream PRs remain separate review items; nothing was merged into `main`.

## Independent contract findings

PR #15's Node validator rejects explicitly unqualified/candidate FRAME producers
and forbids a derived operation from reusing its original FRAME creation request
ID. Its independent Python capture validator omitted those two checks. Synthetic
saved NPY packages with recomputed metadata hashes reproduced both inconsistencies;
this was a saved-evidence validation issue, not evidence of a live DM mutation.
The integration aligns the Python gates and adds independently rehashed negative
controls. Hash consistency alone must never qualify a candidate or resolve an
impossible request identity.

The generic saved-data entry now declares `source_mode=image`, without calling
an ordinary microscopy image a diffraction pattern. It verifies original READ
identity, hashes, bounded coordinates and FRAME ancestry. Tracked Fourier inputs
also retain their producer, native calibration, mathematical axes and scalar
processing history. This does not admit a pixel-only image to physical reciprocal
units or expand the existing crystallography analysis gate.

Independent external-workspace controls also check that removing a native receipt
cannot downgrade a native package to the generic schema reader. Scientific export
must carry the actual upstream metadata and bounded processing ancestry, including
for a later view, instead of leaving only source paths and sidecar hashes. Native
frequency data must not acquire an implied spatial ROI through the display path.

The reviewed FRAME path keeps these useful boundaries:

- An explicit source ID and zero-based DM dimension-2 frame produce an independent
  2D float32 copy through DM. Every uint16 value is exact; storage is explicitly
  float32 rather than a claimed uint16 export.
- Source rank/type/packing, selected-plane and logical-storage budgets, native
  temporary allocation and the shared retained-result pool are checked separately.
- Unknown units remain unknown. Frame ancestry identifies the original selection;
  it does not prove immutable live pixels or supply later ROI/FFT coordinates.
- READ is bounded and non-atomic. Descriptor equality and `source_write_requested:false`
  do not replace independent source-protection or ownership acceptance.
- Existing physical crop/filter/Fourier gates remain the PR #15 contract. Pixel
  operation modes need explicit, separately tested coordinate semantics; they must
  not fabricate a physical ruler or silently invoke an external native substitute.

## Next integration boundary

Prioritize a visible, reversible image workflow rather than a required phase
classifier. Keep DM-native operations distinct from explicitly requested external
file/display work. TIFF files and validated DM captures are separate read-only
inputs to a fixed working copy; rendered PNGs are display products, never numeric
analysis inputs. Missing spatial units can still permit pixel coordinates and
cycles-per-pixel results, while physical distances remain unavailable.

Retain source/capture/frame identity, raw calibration and processing provenance
across both input paths. Client image delivery needs actual client evidence:
creating a PNG, retaining an image ID or showing a DM document alone does not prove
that the Agent received the image. Pending native pixel-mode and ordinary-client
acceptance remain explicitly unqualified until their own checks finish.
