# External crystallography dependencies

The first workflow uses an independent Python environment with **NumPy, SciPy
and ASE**. None of these packages is
installed into GMS-managed Python or loaded by the native plugin. DM operations
remain DM-native; the companion's geometry and candidate matching are explicitly
external computations over fixed, exported inputs.

NumPy supplies array operations and mature linear algebra. SciPy supplies the
one-to-one linear assignment used in joint reflection matching. ASE supplies
the mature `Cell.reciprocal()` implementation for the hexagonal metric, as well
as the CIF reader when a user supplies a reference. Its documented reciprocal
cell [does not include a factor of 2*pi](https://docs.ase-lib.org/ase/cell.html#ase.cell.Cell.reciprocal).
Supporting both cubic and HCP candidates therefore justifies ASE in the base
companion environment; it is no longer a CIF-only dependency. The small
workflow-specific code preserves measurement/calibration contracts, enumerates a
bounded cubic/hexagonal hypothesis space and records residuals; it does not recreate a
general crystallographic library, CIF parser or diffraction simulator.

## Options reviewed

The release observations below were checked on **2026-10-25**. They describe
upstream releases, not a claim that every version or platform was tested here.
Requirements allow compatible releases; each result records the actual software
versions used. Installing from wheels in a separate environment avoids changing
the host's old Python and reduces local compiler requirements.

| Package | Useful capability | Maintenance / dependency cost | License and decision |
| --- | --- | --- | --- |
| [NumPy](https://numpy.org/about/) | Vectors, units, arrays, SVD, NPY | [2.5.4](https://pypi.org/project/numpy/) released 2026-10-10; current release requires Python 3.12+. Older compatible releases can satisfy the companion's supported environment. | Main project BSD-3-Clause; wheels include additional third-party notices. Required. |
| [SciPy](https://scipy.org/) | Mature assignment and optional future numerical fitting | [1.18.1](https://scipy.org/news/) released 2026-08-21; [current metadata](https://pypi.org/project/scipy/) requires Python 3.12+. Compiled numerical dependency in addition to NumPy. | BSD. Required for joint one-to-one assignment; no custom replacement solver. |
| [ASE](https://docs.ase-lib.org/ase/io/formatoptions.html#cif) | Mature reciprocal-cell metric, CIF reader, atomic structure and cell representation | [3.29.0](https://pypi.org/project/ase/) released 2026-06-21, Python 3.10+; requires NumPy, SciPy and Matplotlib. Development documentation may describe a newer Python floor than the selected release. | LGPL-2.1-or-later. Required for the HCP metric and reused for the narrow CIF adapter. |
| [spglib](https://spglib.readthedocs.io/en/stable/python-interface.html) | Symmetry search and standardization for supplied atomic structures | [2.8.0](https://pypi.org/project/spglib/) released 2026-10-10, Python 3.11+, NumPy and a compiled C library; Windows wheels available. It is not a diffraction-image indexer. | BSD-3-Clause. Defer until a concrete structure-symmetry task requires it; no automatic standardization in the current CIF adapter. |
| [pymatgen](https://pymatgen.org/pymatgen.analysis.diffraction.html) | Rich structure/CIF, lattice comparison and TEM calculation | Documentation identifies 2026.10.16. Its newer core split still brings [pandas, Plotly, SymPy, SciPy, spglib and other dependencies](https://raw.githubusercontent.com/materialsproject/pymatgen-core/main/pyproject.toml). This is substantial for the bounded manual-point cubic/hexagonal task. | MIT. A good future structure-analysis adapter, but not installed for this first workflow. |
| [diffsims](https://diffsims.readthedocs.io/en/latest/) | Electron diffraction simulation from a specified structure and orientation | [0.7.0](https://pypi.org/project/diffsims/) released 2025-06-04; [dependencies](https://raw.githubusercontent.com/pyxem/diffsims/main/setup.py) include diffpy.structure, orix, numba, SciPy and Matplotlib. Its available simulation model is not a general experimental intensity oracle. | GPLv3+. Defer to an explicit optional simulation workflow; no copied implementation or hidden runtime fallback. |
| [scikit-image](https://scikit-image.org/docs/stable/user_guide/install.html) | Peak detection and image-region methods | [0.26.0](https://pypi.org/project/scikit-image/) released 2025-12-20, Python 3.11+; adds SciPy, networkx, Pillow, imageio, tifffile and other [dependencies](https://raw.githubusercontent.com/scikit-image/scikit-image/v0.26.0/pyproject.toml). | BSD. Not required: the first bounded automatic localization reuses the already selected SciPy ndimage/optimization routines. More advanced localization can justify it later. |

An alternative for a future lattice-only CIF adapter is
[Gemmi](https://gemmi.readthedocs.io/en/latest/cell.html). Its
[0.7.5 release](https://pypi.org/project/gemmi/) provides small Windows wheels,
CIF/space-group/unit-cell functions and `calculate_d`, with MPL-2.0 or LGPLv3
licensing. It is attractive when only lattice/symmetry data is needed. The first
adapter selects ASE for its mature reciprocal-cell metric and established
atomic-structure representation; it does not install both libraries for the same job.
These are upstream license observations, not a substitute for preserving each
installed distribution's license and bundled-component notices.

## Narrow CIF reference contract

`crystallography.structures.load_reference(path, label=..., model=...)`
accepts a user-selected ordinary, uncompressed `.cif` of at most 1 MiB. It uses
ASE's parser to require one data block with atomic structure, then
`ase.io.read(..., format="cif", index=0, primitive_cell=False)`. This loader
imports ASE lazily. The full companion environment nevertheless includes ASE
for HCP metric construction. Missing ASE produces an explicit installation
instruction for that external environment.

The explicit model is `FCC`, `BCC`, `P` (primitive cubic), or `HCP`. No model is
guessed from a file name, space-group tag or chemical symbol. The compatible
`load_cubic_reference(..., centering="F"/"I"/"P")` entrypoint retains its cubic
contract and returns the same reference information.

For FCC/BCC/P, the input must already have a conventional cubic metric. The fixed
length spread limit is `(max(a,b,c)-min(a,b,c))/mean(a,b,c) <= 1e-6`; every angle
must be within `1e-5` degrees of 90 degrees. Cell lengths, volume and atomic
coordinates must be finite, and lengths/volume positive. A primitive FCC
rhombohedral cell is refused rather than silently converted. The mean of the
three admitted lengths is converted from ASE's angstrom to nm using 0.1; the
original six cell parameters and tolerance policy remain in the result.

For HCP, the input must already use a conventional **hexagonal** cell: `a` and
`b` agree within a relative spread of `1e-6`, alpha and beta are within `1e-5`
degrees of 90 degrees, and gamma is within `1e-5` degrees of 120 degrees. Its
positive finite `c` is independent; no ideal `c/a` ratio is imposed. The reference
returns `lattice_parameter_a_nm`, `lattice_parameter_c_nm`, `c_over_a`, and the
full original cell parameters. It does not expose the cubic
`lattice_parameter_nm` shortcut for HCP. Rhombohedral and 60-degree settings are
refused instead of automatically reindexed.

The recorded hexagonal basis uses `a1=(a,0,0)`,
`a2=(-a/2,sqrt(3)*a/2,0)`, `c=(0,0,c)`, with reciprocal vectors in cycles/length
without a factor of `2*pi`. Reflection labels use three-index `(h,k,l)`;
Miller-Bravais `i=-(h+k)` is explicit. Zone `[u,v,w]` uses this three-index
direct basis and must not be relabeled as four-index `[u,v,t,w]`. This reference
basis is not an observed orientation in the microscope.

`F`, `I` or `P` is the caller's explicit cubic centering hypothesis; the HCP
model uses a primitive hexagonal metric and a separately declared HCP structural
hypothesis. A hexagonal metric and successfully parsed atomic sites do **not**
qualify the two-site HCP basis, occupancies, structure-factor extinctions or an
actual HCP material. The adapter never
deduces it, the material's chemistry or a phase name from space-group tags or
the displayed atomic symbols. It returns the original byte hash, byte count,
selected block/index, ASE version, atomic count and captured parser warnings.
Successful parsing is marked `user_supplied_not_phaseproof`, with
`symmetry_qualified:false` and `basis_qualified:false`; ASE may expand listed
sites during CIF reading. FCC/BCC and HCP references must be dispatched by the
explicit `model`, not by the `centering` field alone.
Numerical uncertainties written in CIF tokens are not propagated into the
reference lattice parameter and are disclosed as a limitation.

The original bytes are never rewritten. The
[ASE CIF1 parser](https://gitlab.com/ase/ase/-/blob/3.29.0/ase/io/cif.py)
owns its documented Latin-1 byte interpretation; this adapter does not guess or
cycle through encodings. Binary/control bytes and the CIF2 format marker are
refused. This bounded-file check is not a sandbox for arbitrary hostile files.
No data is uploaded and no structure database is queried automatically.

## Scientific interpretation

The [IUCr integral reflection conditions](https://dictionary.iucr.org/Integral_reflection_conditions)
justify the bounded P/I/F centering hypotheses. They do not supply the
additional basis extinctions of every structure or make a Bravais-lattice
candidate a chemical phase. Multiple joint geometric candidates are retained;
the [cubic SAED protocol](https://doi.org/10.1107/S1600576724004333) and its
[reindexing addendum](https://doi.org/10.1107/S1600576726003031) describe
equivalent patterns and ambiguities. A candidate's assumed lattice constant is
not permission to recalibrate unknown data to fit it.

The [diffsims generator](https://diffsims.readthedocs.io/en/latest/reference/generated/diffsims.generators.diffraction_generator.DiffractionGenerator.html)
uses kinematic structure-factor intensities, and pymatgen's TEM API similarly
uses `|F|^2` while listing sample thickness/excitation-error modeling as future
work. Electron diffraction can show strong thickness dependence and
kinematically forbidden reflections; see the
[IUCr dynamical comparison](https://journals.iucr.org/m/issues/2023/01/00/vq5003/index.html).
Neither simple parity filtering nor one simulated pattern uniquely proves a
phase. The current companion compares geometry, preserves alternatives and
reports what is not determined.

HCP metric matching reuses ASE's `Cell.reciprocal()` rather than adding a
handwritten inverse-cell implementation. Without an explicit user reference or
ratio, a bounded `c/a` grid from 1.50 to 1.90 is a search prior, not a universal
HCP restriction or an assumption that all HCP structures are ideal. Explicit
reference parameters retain their own independent `a` and `c`; the CIF loader
does not impose the grid or an ideal ratio. Supporting HCP geometry does not
qualify an arbitrary CIF basis, dynamical intensities or a second structure
library.
