# Optional structures and electron diffraction

These composable MCP tools use an independent ASE/diffsims environment. They
do not require a DM process, invoke a GMS Python interpreter, identify a unique
phase, or replace a failed native operation. Existing FCC/BCC/HCP indexing
examples remain optional; generic structure input does not enter that pipeline.

For a bounded batch over 1–3 candidates without preassigned HKL, see the
[Hypothesis Explorer recipe](HYPOTHESIS_EXPLORER.md): an executed synthetic
experiment, static overlays/tables, retained ambiguity and prospective next
observations. It reuses these tools through an optional local CLI.

## Enable and use

Create a separate Python environment and install `requirements-structure-tools.txt`.
Configure `DM_STRUCTURE_WORKSPACE` as a new absolute output directory and
`DM_STRUCTURE_PYTHON` as that environment's executable. These tools can accompany
an explicitly configured image or native backend. For a combined DM-independent
setup, keep `DM_MCP_BACKEND=images`, `DM_IMAGE_WORKSPACE` and `DM_IMAGE_PYTHON`
configured as described in [the image guide](PIXEL_IMAGE_WORKFLOW.md). Existing
default v0.6 configuration is unchanged.

| Tool | Actual scope |
|---|---|
| `structure_open` | Read one bounded CIF1 or XYZ/extXYZ through ASE; save a hash-bound source copy and generic atom/cell snapshot |
| `structure_info` | Inspect that snapshot or its derived result; optionally return atoms, Cartesian Å positions, row-vector cell and PBC |
| `structure_view` | Return an ASE projection PNG; optionally attach the separately configured local 3Dmol viewer |
| `structure_measure` | Atomic distance/angle/dihedral; three-index HKL spacing/angle, UVW direction angle and plane/zone relation; explicit zero-based atom indices and applicable periodicity |
| `structure_derive` | New bounded repeat/active Cartesian rotation of atoms and cell; source remains immutable |
| `structure_simulate` | Actual diffsims kinematic electron diffraction with explicit voltage/orientation/cutoffs |
| `structure_result` | Query the caller's original request, without recomputation |
| `structure_orient` | Save a shared three-index UVW orientation from the actual cell, with an explicit or recorded in-plane convention |
| `structure_compare` | Compare sourced reciprocal measurements against saved unrastered reflections using explicit registration; retain unmatched and ambiguous candidates |
| `structure_viewer_close` | Close the exact owned viewer and its aliases; recover this operation with the same close tool and original request ID |

Write calls require a request ID saved before dispatch. Cancelled waiting does
not stop an accepted scientific worker; query its original `structure_result`
instead of creating another request. Viewer closure has a separate request
namespace: query `structure_viewer_close` with its original ID and view object.
Missing cell information permits observation and nonperiodic atomic geometry.
Periodic simulation requires an actual full-rank periodic cell. Units follow the
ASE input convention (Cartesian Å); this does not verify a user's experimental
length calibration. A three-index HKL plane uses the actual reciprocal metric,
including nonorthogonal cells, in cycles/Å without a `2π` factor.
Crystal metrics and periodic distances require a numerically full-rank cell;
three nonzero but linearly dependent cell vectors do not establish one.
Plane normals and direct-space directions use their distinct reciprocal/direct
metrics. Hexagonal four-index notation is not silently treated as three indices.

## Mature display component

The optional read-only viewer uses [3Dmol.js](https://3dmol.org/doc/GLViewer.html),
not a new three-dimensional engine. Install `3dmol@2.5.5` in an independent Node
directory and configure `DM_STRUCTURE_VIEWER_ASSET` as its absolute
`node_modules/3dmol/build/3Dmol-min.js` path. `structure_view(interactive:true)`
returns the local viewer URL plus its projection PNG. It serves only the fixed
snapshot and local component; no CIF, coordinates or images are uploaded.
Camera rotation/zoom does not modify atom positions or the simulation orientation.
Use `structure_derive` for an actual model transform. An unavailable component
leaves the PNG explicitly two-dimensional. URL readiness is distinct from actual
browser/WebGL acceptance. The viewer survives MCP disconnect and reuses the same
view's original connection; uncertain launches are not repeated automatically.
The viewer defaults to atoms. Its optional “几何近邻球棍” display uses the pinned
component's [distance-only `assignBonds()`](https://3dmol.org/doc/GLModel.html#assignBonds),
not a chemical/DFT calculation: the renderer's radius-table sum plus 0.25 Å,
with its 1.6 Å fallback for missing table entries, excluding squared distances
below 0.5 Å². It does not check valence or infer bond
order/covalency, and searches only atoms present in this snapshot, without
periodic-image contacts. This presentation is limited to 512 atoms and 8,192
undirected links; exceeding either limit refuses the whole contact display,
without truncation. Counts and the policy remain visible. Switching display
preserves the camera, source coordinates, cell, PBC and fixed snapshot hash.
Reuse an existing interactive view for camera changes. Equivalent snapshots
and scientific orientations can share one helper across view IDs. Explicit
`structure_viewer_close` confirms the owned process and port have stopped;
an uncertain or closed old view is never automatically relaunched. Partial
periodic cells display their actual independent vectors without inventing a
third vector. See [viewer lifecycle and direction limits](STRUCTURE_VIEWER_LIFECYCLE.md).

Use [a shared orientation record](STRUCTURE_ORIENTATION.md) for both the initial
structure direction and simulation. Dragging the camera never changes this
scientific record. [Reflection comparison](REFLECTION_COMPARISON.md) consumes
committed `image_measure` evidence, preserves its calibration version and
reports geometric residuals rather than claiming a unique phase or an FFT/SAED
intensity match.

## Simulation contract and limits

The first engine is [diffsims 0.7.0](https://diffsims.readthedocs.io/en/latest/):
fast kinematic reflection positions and approximate elastic intensities. It uses
the library's scattering factors, excitation model and rasterizer. All effective
parameters and software versions are saved. Explicit inputs include voltage,
RZXZ Euler angles, reciprocal cutoff and excitation-error cutoff; raster sampling,
spot width and direct-beam choice remain visible. The supplied structure basis
is retained. Work/atom/reflection/raster budgets are checked before simulation.
Mixed/partial occupancy is retained for viewing but currently refused for
simulation.

The tested engine's reciprocal-lattice enumeration can omit cancelling HKLs
for some skew cells. A conservative analytic completeness check therefore
refuses an unqualified cell/cutoff combination before simulation, rather than
silently returning an incomplete pattern. This restriction does not block
generic structure display or valid lattice geometry. Synthetic FCC, BCC, HCP
and admitted nonorthogonal cases have separate checks; this is not a promise
that every full-rank cell is simulation-qualified.

Authoritative un-rasterized reflection coordinates, HKLs and kinematic intensities
are saved separately. The Gaussian normalized raster is qualitative relative
intensity, not detector counts. Its log-mapped PNG is display-only.
The upstream raster uses an integer center and overwrites coincident pixel
spots rather than summing them; these limitations are recorded with the saved
sampling and display recipe. Quantitative reflection measurements use the
un-rasterized coordinates, not peak positions inferred from this preview.
The scientific float64 raster is an existing schema-1 NPY capture, importable through
`image_open(source_kind:"capture")` for selection, measurement and export.
`native_float32:true` additionally makes a bounded float32 copy with both hashes,
maximum conversion errors and explicit reciprocal calibration. It never replaces
the original float64 array and does not qualify a native DM import.

Experimental comparison must retain its independently established scale,
registration/rotation and any normalization. An HRTEM/reconstruction FFT is not
a SAED intensity image. Compatible spots or an extinction rule do not prove a
unique phase, a twin boundary, defects or phase fractions. This initial path has
no multislice/dynamical scattering, thickness-dependent multiple scattering or
image contrast transfer. [abTEM's multislice route](https://abtem.github.io/doc/user_guide/walkthrough/multislice.html)
is a future option for those questions; it has not been implemented or qualified
here. No thickness is inferred from an excitation cutoff.

ASE is LGPL, diffsims is GPLv3, and the optional 3Dmol package is BSD-3-Clause;
refer to their distributed licenses. No third-party engine is vendored in this
repository or added to the default runtime. New environments record the versions
actually used rather than implying all allowed versions were tested.

For a possible first-principles connection through ASE, see the separate
[VASP integration assessment](VASP_INTEGRATION_ASSESSMENT.md). VASP execution
and POSCAR/CONTCAR MCP import are not part of the current tools.
