"""Bounded external ASE structures and diffsims kinematic diffraction.

This optional companion does not import DM, identify phases, standardize cells,
run calculators, install dependencies or call the network. It retains immutable
input copies. Simulation is an explicit kinematic approximation, not a TEM image
formation or dynamical scattering model.
"""
import hashlib
import importlib.metadata
import io
import json
import math
import os
from pathlib import Path
import platform
import re
import warnings
from datetime import datetime, timezone
import uuid

import numpy as np
import ase
from ase import Atoms
from ase.io import read as ase_read
from crystallography.orientation import from_zone_axis
from crystallography.reflection_compare import compare as compare_reflections, load_measurement
from crystallography.analysis_revision import bind_geometry, comparison_revision

BACKEND = "external-structure-workspace"
MAX_ATOMS = 4096
MAX_BYTES = 2 * 1024 * 1024
MAX_CANDIDATES = 100000
MAX_ATOM_REFLECTION_PAIRS = 5000000
ID = re.compile(r"[a-f0-9]{32}\Z")
REQUEST_ID = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
FIELDS = {
    "open": {"source_path"}, "get": {"object_id", "include_atoms"},
    "view": {"object_id", "rotation_deg_xyz", "orientation_id", "max_size", "interactive"},
    "measure": {"object_id", "kind", "atom_indices", "hkls", "directions", "mic"},
    "derive": {"object_id", "repeat", "rotation_deg_xyz", "orientation_id"},
    "orient": {"object_id", "zone_axis_uvw", "in_plane_direction_uvw", "in_plane_rotation_deg"},
    "compare": {"object_id", "measurement_paths", "experimental_kind", "registration", "registration_object_id", "max_residual_inv_angstrom", "correspondences", "current_image_object_id", "analysis_mode", "previous_comparison_id", "source_change_basis"},
    "register": {"object_id", "measurement_paths", "experimental_kind", "current_image_object_id", "fit_correspondences", "validation_correspondences", "screen_axes", "confirmation", "max_residual_inv_angstrom"},
    "simulate": {"object_id", "voltage_kv", "euler_rzxz_deg", "orientation_id", "reciprocal_radius_inv_angstrom",
                 "max_excitation_error_inv_angstrom", "size", "sigma_pixels", "with_direct_beam", "native_float32"},
    "result": {"query_request_id"},
}


class StructureError(ValueError):
    def __init__(self, message, code="INVALID_ARGUMENT"):
        super().__init__(message)
        self.code = code


def need(condition, message, code="INVALID_ARGUMENT"):
    if not condition:
        raise StructureError(message, code)


def finite(value):
    return type(value) in (float, int) and math.isfinite(value)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def strict_json(raw):
    def pairs(values):
        result = {}
        for key, value in values:
            need(key not in result, "Duplicate JSON key")
            result[key] = value
        return result
    result = json.loads(raw, object_pairs_hook=pairs,
                        parse_constant=lambda token: (_ for _ in ()).throw(StructureError("Nonfinite JSON")))
    canonical(result)
    return result


def read_bytes(file, limit=MAX_BYTES):
    file = Path(file)
    need(file.is_file() and not file.is_symlink() and 0 < file.stat().st_size <= limit,
         "Bounded ordinary file required: " + file.name, "BUDGET_OR_FILE")
    with file.open("rb") as stream:
        raw = stream.read(limit + 1)
    need(0 < len(raw) <= limit, "File grew beyond byte budget", "BUDGET_OR_FILE")
    return raw


def write_new(file, raw):
    with Path(file).open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def json_file(file):
    return strict_json(read_bytes(file, 8 * MAX_BYTES).decode("utf-8"))


def triple(value, label, default=None):
    value = default if value is None else value
    need(type(value) is list and len(value) == 3 and all(finite(v) and abs(v) <= 360 for v in value),
         label + " must be three finite degrees in [-360,360]")
    return [float(v) for v in value]


def validate_atoms(atoms):
    need(1 <= len(atoms) <= MAX_ATOMS, "Structure exceeds 1..4096 atom budget", "BUDGET_EXCEEDED")
    need(np.isfinite(atoms.positions).all() and np.isfinite(atoms.cell.array).all(), "Atomic positions/cell must be finite")
    need(np.max(np.abs(atoms.positions)) <= 1e7 and np.max(np.abs(atoms.cell.array)) <= 1e7,
         "Atomic coordinates/cell exceed bounded Angstrom range")


def atoms_data(atoms):
    return {"symbols": atoms.get_chemical_symbols(), "positions_angstrom": atoms.positions.tolist(),
            "cell_angstrom": atoms.cell.array.tolist(), "pbc": [bool(v) for v in atoms.pbc],
            "occupancy": atoms.info.get("occupancy")}


def from_data(data):
    need(type(data) is dict and type(data.get("symbols")) is list and 1 <= len(data["symbols"]) <= MAX_ATOMS,
         "Invalid stored atom budget", "CORRUPT_OBJECT")
    atoms = Atoms(symbols=data["symbols"], positions=data["positions_angstrom"], cell=data["cell_angstrom"], pbc=data["pbc"])
    if data.get("occupancy") is not None:
        atoms.info["occupancy"] = data["occupancy"]
    validate_atoms(atoms)
    return atoms


def load_structure(source):
    source = Path(source)
    need(source.is_absolute() and source.suffix.lower() in (".cif", ".xyz"), "Explicit absolute .cif or .xyz file required")
    raw = read_bytes(source)
    need(not any(value < 32 and value not in (9, 10, 13) for value in raw), "Structure contains binary/control bytes")
    fmt = source.suffix.lower()[1:]
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        if fmt == "cif":
            from ase.io.cif import parse_cif
            from ase.spacegroup import Spacegroup
            need(not raw.lstrip().startswith(b"#\\#CIF_2.0"), "Only ASE CIF1 parsing is qualified")
            blocks = list(parse_cif(io.BytesIO(raw), reader="ase"))
            need(len(blocks) == 1 and blocks[0].has_structure(), "CIF requires exactly one atomic structure block")
            block = blocks[0]
            sites = block.get("_atom_site_fract_x", block.get("_atom_site_cartn_x", []))
            need(1 <= len(sites) <= MAX_ATOMS, "CIF asymmetric site count exceeds budget", "BUDGET_EXCEEDED")
            operations = block.get("_space_group_symop_operation_xyz", block.get("_symmetry_equiv_pos_as_xyz"))
            if operations is not None:
                multiplicity = len(operations) if type(operations) is list else 1
            else:
                group = block.get("_space_group_it_number", block.get("_symmetry_int_tables_number"))
                if group is None:
                    group = block.get("_space_group_name_h-m_alt", block.get("_symmetry_space_group_name_h-m", 1))
                multiplicity = len(Spacegroup(group if type(group) is str else int(group)).get_symop())
            need(multiplicity <= 192 and len(sites) * multiplicity <= MAX_ATOMS,
                 "CIF symmetry expansion exceeds preallocation atom budget", "BUDGET_EXCEEDED")
            atoms = ase_read(io.BytesIO(raw), format="cif", index=0, reader="ase", primitive_cell=False)
        else:
            text = raw.decode("utf-8")
            lines = text.splitlines()
            try:
                count = int(lines[0])
            except (ValueError, IndexError) as error:
                raise StructureError("XYZ requires an explicit atom count") from error
            need(1 <= count <= MAX_ATOMS, "XYZ atom count exceeds budget", "BUDGET_EXCEEDED")
            need(len(lines) >= count + 2 and not any(line.strip() for line in lines[count + 2:]),
                 "Only one complete XYZ configuration is supported; no implicit frame selection")
            atoms = ase_read(io.StringIO(text), format="extxyz", index=0)
        validate_atoms(atoms)
    return atoms, raw, [{"category": row.category.__name__, "message": str(row.message)} for row in caught]


def summary(atoms):
    # ASE Cell.rank counts nonzero vectors; it is not the matrix rank. Never
    # let a linearly dependent periodic basis yield pseudoinverse spacings.
    rank = int(np.linalg.matrix_rank(atoms.cell.array))
    return {"atom_count": len(atoms), "formula": atoms.get_chemical_formula(), "length_unit": "angstrom",
            "cell_angstrom": atoms.cell.array.tolist(), "cell_rank": rank, "cell_nonzero_vector_count": int(atoms.cell.rank),
            "cell_parameters_angstrom_degrees": atoms.cell.cellpar().tolist(),
            "pbc": [bool(v) for v in atoms.pbc], "has_periodic_3d_cell": rank == 3 and bool(np.all(atoms.pbc)),
            "cell_standardized": False, "phase_identified": False,
            "occupancy_status": "ASE supplied occupancy metadata retained" if atoms.info.get("occupancy") else "no explicit disorder metadata",
            "uncertainty_status": "input numerical uncertainties not propagated"}


def render_atoms(atoms, directory, rotation, size):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from ase.visualize.plot import plot_atoms
    figure, ax = plt.subplots(figsize=(size / 100, size / 100), dpi=100)
    try:
        plot_atoms(atoms, ax, rotation=",".join("{}{}".format(value, axis) for value, axis in zip(rotation, "xyz")),
                   show_unit_cell=2, radii=0.5)
        ax.set_aspect("equal")
        ax.set_axis_off()
        figure.tight_layout(pad=.15)
        memory = io.BytesIO()
        figure.savefig(memory, format="png", dpi=100)
        write_new(directory / "preview.png", memory.getvalue())
    finally:
        plt.close(figure)


def measure(atoms, request):
    kind = request.get("kind")
    mic = request.get("mic", False)
    need(type(mic) is bool, "mic must be boolean")
    if kind in ("distance", "angle", "dihedral"):
        need("hkls" not in request and "directions" not in request, "Atomic geometry cannot also supply crystal indices")
        expected = {"distance": 2, "angle": 3, "dihedral": 4}[kind]
        ids = request.get("atom_indices")
        need(type(ids) is list and len(ids) == expected and all(type(v) is int and 0 <= v < len(atoms) for v in ids)
             and len(set(ids)) == expected, "Use distinct, in-bounds zero-based atom_indices")
        if mic:
            periodic = atoms.cell.array[atoms.pbc]
            need(bool(np.any(atoms.pbc)) and np.linalg.matrix_rank(periodic) == len(periodic),
                 "Minimum-image geometry requires a declared linearly independent periodic cell")
        value = {"distance": atoms.get_distance, "angle": atoms.get_angle, "dihedral": atoms.get_dihedral}[kind](*ids, mic=mic)
        need(finite(float(value)), "Atomic measurement is nonfinite")
        return {"kind": kind, "atom_indices": ids, "minimum_image": mic, "value": float(value),
                "unit": "angstrom" if kind == "distance" else "degree", "engine": "ASE Atoms geometry"}
    need(kind in ("d_spacing", "reciprocal_angle", "direction_angle", "zone_relation") and "atom_indices" not in request and not mic,
         "Choose a supported atomic or reciprocal measurement with matching parameters")
    need(np.linalg.matrix_rank(atoms.cell.array) == 3, "Crystal direction/reciprocal geometry requires a full-rank cell")
    def indices(value, count, label):
        need(type(value) is list and len(value) == count and all(type(row) is list and len(row) == 3 and
             all(type(v) is int and abs(v) <= 32 for v in row) and any(row) for row in value),
             label + " require nonzero integer triples, |index|<=32 in the exact supplied cell basis")
        return np.asarray(value)
    if kind in ("direction_angle", "zone_relation"):
        directions = request.get("directions")
        direct = atoms.cell.cartesian_positions(indices(directions, 2 if kind == "direction_angle" else 1, "directions"))
        direct_magnitudes = np.linalg.norm(direct, axis=1)
        need(np.isfinite(direct).all() and np.isfinite(direct_magnitudes).all() and bool(np.all(direct_magnitudes > 0)),
             "Direct vectors/magnitudes are not finite/nonzero")
        if kind == "direction_angle":
            need("hkls" not in request, "direction_angle compares UVW, not HKL")
            denominator = float(np.prod(direct_magnitudes))
            need(finite(denominator) and denominator > 0, "Direct angle metric overflow/underflow")
            cosine = float(np.dot(direct[0], direct[1]) / denominator)
            need(finite(cosine), "Direct angle cosine is nonfinite")
            value = math.degrees(math.acos(float(np.clip(cosine, -1., 1.))))
            need(finite(value), "Direct angle is nonfinite")
            return {"kind": kind, "directions_uvw": directions, "direct_vectors_angstrom": direct.tolist(),
                    "value": value, "unit": "degree",
                    "index_convention": "three_index_direct_basis_UVW_not_four_index_Miller_Bravais",
                    "engine": "ASE Cell Cartesian metric", "phase_identified": False}
        hkls = request.get("hkls")
        reciprocal = indices(hkls, 1, "hkls") @ atoms.cell.reciprocal().array
        lengths = float(np.linalg.norm(reciprocal[0]) * np.linalg.norm(direct[0]))
        need(np.isfinite(reciprocal).all() and finite(lengths) and lengths > 0, "Invalid reciprocal/direct metric")
        zone_law = int(np.dot(np.asarray(hkls[0]), np.asarray(directions[0])))
        dot = float(np.dot(reciprocal[0], direct[0]))
        need(finite(dot), "Reciprocal/direct dot product is nonfinite")
        cosine = dot / lengths
        need(finite(cosine), "Reciprocal/direct angle cosine is nonfinite")
        angle = math.degrees(math.acos(float(np.clip(cosine, -1., 1.))))
        need(finite(angle), "Reciprocal/direct angle is nonfinite")
        return {"kind": kind, "hkl": hkls[0], "direction_uvw": directions[0], "zone_law_hu_kv_lw": zone_law,
                "reciprocal_direct_dot": dot, "plane_contains_direction": zone_law == 0,
                "angle_to_plane_normal_degrees": angle, "acute_angle_to_plane_degrees": abs(90. - angle),
                "direct_vector_angstrom": direct[0].tolist(), "reciprocal_vector_inv_angstrom": reciprocal[0].tolist(),
                "index_convention": "three_index_direct_basis_UVW_and_reciprocal_HKL",
                "engine": "ASE Cell direct/reciprocal metric; exact integer zone law", "phase_identified": False}
    need("directions" not in request, "Reciprocal HKL measurement cannot also supply direct directions")
    hkls = request.get("hkls")
    count = 1 if kind == "d_spacing" else 2
    vectors = indices(hkls, count, "hkls") @ atoms.cell.reciprocal().array
    magnitudes = np.linalg.norm(vectors, axis=1)
    need(np.isfinite(vectors).all() and np.isfinite(magnitudes).all() and bool(np.all(magnitudes > 0)),
         "Reciprocal vectors/magnitudes are not finite/nonzero")
    if count == 1:
        value = float(1. / magnitudes[0])
        need(finite(value) and value > 0, "Derived d-spacing is not finite/positive")
    else:
        denominator = float(np.prod(magnitudes))
        need(finite(denominator) and denominator > 0, "Reciprocal angle metric overflow/underflow")
        cosine = float(np.dot(vectors[0], vectors[1]) / denominator)
        need(finite(cosine), "Reciprocal angle cosine is nonfinite")
        value = math.degrees(math.acos(float(np.clip(cosine, -1., 1.))))
        need(finite(value), "Reciprocal angle is nonfinite")
    return {"kind": kind, "hkls": hkls, "reciprocal_vectors_inv_angstrom": vectors.tolist(), "value": float(value),
            "unit": "angstrom" if count == 1 else "degree", "reciprocal_convention": "cycles_per_angstrom_no_2pi",
            "engine": "ASE Cell reciprocal metric", "phase_identified": False}


def raster_geometry(result, size, calibration, sigma):
    """Describe the pinned library's geometry; never calculate scattering."""
    continuous_xy = result._get_transformed_coordinates(0, (size // 2, size // 2), False, units="pixel")
    inside = ((continuous_xy[:, 0] >= 0) & (continuous_xy[:, 0] < size) &
              (continuous_xy[:, 1] >= 0) & (continuous_xy[:, 1] < size))
    integer_xy = continuous_xy[inside].astype(int)
    _, multiplicities = np.unique(integer_xy, axis=0, return_counts=True)
    quantization = np.abs(integer_xy - continuous_xy[inside])
    return {"authority": "Unrastered coordinates/HKL/intensities in reflections.json; raster is qualitative only",
            "engine": "diffsims0.7.0 DiffractionSimulation.get_diffraction_pattern",
            "coordinate_transform": "same pinned library _get_transformed_coordinates(in_plane_angle=0, mirrored=False)",
            "continuous_center_xy_pixels": continuous_xy.tolist(), "in_frame_reflection_indices": np.flatnonzero(inside).tolist(),
            "integer_center_xy_pixels": integer_xy.tolist(), "integer_center_row_col": integer_xy[:, ::-1].tolist(),
            "pixel_mapping": "column=x; row=y; +x increases columns; +y increases rows",
            "integer_center_policy": "library astype(int), truncation after nonnegative in-frame selection; no subpixel raster centers",
            "in_frame_reflection_count": int(np.count_nonzero(inside)), "outside_frame_reflection_count": int(np.count_nonzero(~inside)),
            "unique_integer_center_count": int(len(multiplicities)),
            "cumulative_collision_count": int(np.sum(multiplicities - 1)),
            "colliding_integer_center_count": int(np.count_nonzero(multiplicities > 1)),
            "coincident_center_policy": "library NumPy indexed assignment overwrites coincident centers, does not sum their intensities",
            "maximum_center_quantization_error_pixels": float(quantization.max()) if quantization.size else 0.,
            "maximum_center_quantization_error_inv_angstrom": float(quantization.max() * calibration) if quantization.size else 0.,
            "sigma_pixels": float(sigma), "sigma_inv_angstrom": float(sigma * calibration),
            "normalization": "library divides qualitative Gaussian raster by its maximum; integrated intensity is not conserved"}


def simulate(atoms, request, directory, ident, source_provenance=None, resolved_structure_object_id=None, orientation=None):
    # The library enumerates reciprocal points: bound its integer box and the
    # atom/reflection work BEFORE invoking a native/JIT scientific dependency.
    need(np.linalg.matrix_rank(atoms.cell.array) == 3 and bool(np.all(atoms.pbc)), "Kinematic simulation requires a full-rank explicitly periodic 3D cell")
    need(float(np.linalg.cond(atoms.cell.array)) <= 1e6, "Cell is numerically ill-conditioned")
    occupancy = atoms.info.get("occupancy")
    need(not occupancy or all(type(row) is dict and len(row) == 1 and
         all(finite(value) and value == 1. for value in row.values()) for row in occupancy.values()),
         "Mixed/partial occupancy is retained for viewing but not qualified for simulation")
    need(bool(np.all(atoms.numbers > 0)), "Dummy/unknown elements cannot supply atomic scattering")
    voltage, radius, excitation = (request.get(key) for key in ("voltage_kv", "reciprocal_radius_inv_angstrom", "max_excitation_error_inv_angstrom"))
    need(finite(voltage) and 20 <= voltage <= 400, "voltage_kv must be explicit in 20..400")
    need(finite(radius) and .05 <= radius <= 5., "reciprocal_radius_inv_angstrom must be explicit in .05..5")
    need(finite(excitation) and 1e-5 <= excitation <= .2, "max_excitation_error_inv_angstrom must be explicit in 1e-5...2")
    need((orientation is None) == ("orientation_id" not in request), "A verified orientation reference is required")
    need(not (orientation is not None and "euler_rzxz_deg" in request),
         "Choose orientation_id or explicit euler_rzxz_deg, never both")
    rotation = triple(orientation["euler_rzxz_deg"] if orientation is not None else request.get("euler_rzxz_deg"), "euler_rzxz_deg")
    if orientation is not None:
        from transforms3d.euler import euler2mat
        actual_matrix = euler2mat(*np.deg2rad(rotation), axes="rzxz")
        need(np.allclose(actual_matrix, np.asarray(orientation["rotation_matrix_cartesian"]), atol=2e-12, rtol=0),
             "Pinned diffsims RZXZ conversion differs from the shared orientation matrix", "INVALID_ORIENTATION")
    size, sigma = request.get("size", 256), request.get("sigma_pixels", 1.)
    direct = request.get("with_direct_beam", False)
    need(type(size) is int and 64 <= size <= 512 and finite(sigma) and .2 <= sigma <= 8 and type(direct) is bool,
         "Raster size64..512, sigma_pixels .2..8 and explicit boolean direct beam required")
    native = request.get("native_float32", False)
    need(type(native) is bool and (not native or size <= 128), "Optional native_float32 handoff requires explicit boolean and size<=128")
    bounds = 2 * np.ceil(radius * np.linalg.norm(atoms.cell.array, axis=1)).astype(np.int64) + 1
    candidates = math.prod(int(v) for v in bounds)
    need(candidates <= MAX_CANDIDATES and candidates * len(atoms) <= MAX_ATOM_REFLECTION_PAIRS,
         "Reciprocal enumeration or atom/reflection work exceeds preallocation budget", "BUDGET_EXCEEDED")
    from diffpy.structure import Atom, Lattice, Structure
    from diffsims.generators.diffraction_generator import DiffractionGenerator
    # base= preserves the supplied Cartesian basis, including nonorthogonal
    # cells. Setting abc alone would rotate a generic source basis silently.
    lattice = Lattice(base=atoms.cell.array)
    reciprocal_lattice = lattice.reciprocal()
    library_extent = np.floor(radius / np.array([reciprocal_lattice.a, reciprocal_lattice.b, reciprocal_lattice.c])).astype(np.int64)
    # For every vector |g|<R, h_i=g dot a_i implies |h_i|<R|a_i|.
    # diffsims0.7.0 instead bounds each index by R/|a_i*|, which can miss
    # cancellations in skew cells. Certify its existing box; do not replace
    # enumeration or silently reduce/rotate the user's crystallographic basis.
    required_extent = np.maximum(0, np.ceil(radius * np.linalg.norm(atoms.cell.array, axis=1)).astype(np.int64) - 1)
    need(bool(np.all(library_extent >= required_extent)),
         "Pinned diffsims reciprocal enumeration is not certified complete for this cell/cutoff; skew-cell cancellations may be omitted. "
         "ASE viewing/geometry remain available; no basis rewrite or alternate simulator was substituted.", "UNQUALIFIED_ENUMERATION")
    enumeration = {"completeness_certified": True, "library_integer_extents_hkl": library_extent.tolist(),
                   "required_integer_extents_hkl": required_extent.tolist(),
                   "certificate": "All |g|<R satisfy integer |h_i|<R*|a_i|; the pinned library box contains this conservative bound",
                   "basis_reduced": False, "library_enumeration_replaced": False}
    fractions = atoms.get_scaled_positions(wrap=False)
    structure = Structure([Atom(atype=symbol, xyz=position, occupancy=1.) for symbol, position in
                           zip(atoms.get_chemical_symbols(), fractions)], lattice=lattice)
    generator = DiffractionGenerator(voltage, scattering_params="lobato", precession_angle=0,
                                    shape_factor_model="lorentzian", minimum_intensity=1e-12)
    result = generator.calculate_ed_data(structure, reciprocal_radius=radius, rotation=tuple(rotation),
                                        with_direct_beam=direct, max_excitation_error=excitation,
                                        shape_factor_width=excitation, debye_waller_factors={})
    coords, indices, intensities = np.asarray(result.coordinates), np.asarray(result.indices), np.asarray(result.intensities)
    need(len(intensities) > 0 and len(intensities) <= 4096 and np.isfinite(coords).all() and
         np.isfinite(intensities).all() and bool(np.all(intensities >= 0)), "No finite nonnegative simulated reflections in the selected scope")
    calibration = 2. * radius / size
    result.calibration = calibration
    # Geometry diagnostics call the same pinned library transform as its own
    # rasterizer. This is not an alternative scattering or raster kernel.
    rasterization = raster_geometry(result, size, calibration, sigma)
    raster = np.asarray(result.get_diffraction_pattern(shape=(size, size), sigma=sigma, direct_beam_position=None,
                                                      in_plane_angle=0), dtype="<f8")
    need(raster.shape == (size, size) and np.isfinite(raster).all() and bool(np.all(raster >= 0)) and raster.max() > 0,
         "Simulation library returned an invalid raster")
    with (directory / "input.npy").open("xb") as stream:
        np.save(stream, np.ascontiguousarray(raster), allow_pickle=False)
        stream.flush(); os.fsync(stream.fileno())
    array_hash = sha(read_bytes(directory / "input.npy", 4 * MAX_BYTES))
    axes = [{"axis": axis, "origin": float(size // 2), "scale": calibration, "unit": "1/angstrom",
             "physical_pixel_zero": -(size // 2) * calibration} for axis in ("x", "y")]
    info = {"schema_version": 1, "capture_id": ident, "input_file": "input.npy", "input_sha256": array_hash,
            "dtype": "float64", "shape_yx": [size, size], "axes": ["y", "x"], "array_order": "C", "byte_order": "little",
            "calibration": axes, "intensity_calibration_applied": False,
            "scientific_semantics": {"domain": "frequency", "kind": "simulated_kinematic_electron_diffraction",
                                     "reciprocal_convention": "cycles_per_angstrom_no_2pi", "intensity": "relative_normalized_kinematic_not_counts"},
            "external_provenance": {"engine": "diffsims", "dm_called": False,
                                    "input_object_id": request["object_id"], "structure_object_id": resolved_structure_object_id,
                                    "structure_snapshot": atoms_data(atoms), "structure_snapshot_sha256": sha(canonical(atoms_data(atoms))),
                                    "source_provenance": source_provenance or {"status": "direct_in_memory_library_test_no_source_file_claim"},
                                    "orientation": orientation,
                                    "requested_parameters": {key: value for key, value in request.items() if key not in ("workspace", "action", "request_id")},
                                    "effective_parameters": {"voltage_kv": voltage, "euler_rzxz_deg": rotation,
                                                             "reciprocal_radius_inv_angstrom": radius,
                                                             "max_excitation_error_inv_angstrom": excitation,
                                                             "scattering_params": "lobato", "shape_factor": "lorentzian",
                                                             "shape_factor_width": excitation, "debye_waller_factors": {},
                                                             "minimum_intensity_relative": 1e-12, "with_direct_beam": direct,
                                                             "size": size, "sigma_pixels": sigma, "raster_normalized": True},
                                    "software": {"ase": ase.__version__, "diffsims": importlib.metadata.version("diffsims"),
                                                 "diffpy.structure": importlib.metadata.version("diffpy.structure"), "numpy": np.__version__},
                                    "module_sha256": sha(Path(__file__).read_bytes()),
                                    "rasterization": rasterization,
                                    "reciprocal_enumeration": enumeration,
                                    "kinematic_not_dynamical": True, "phase_identified": False}}
    write_new(directory / "input.json", canonical(info) + b"\n")
    capture = {"schema_version": 1, "capture_id": ident, "state": "captured", "input_sha256": array_hash,
               "input_metadata_sha256": sha(canonical(info)), "capture_backend": "external-diffsims-kinematic"}
    write_new(directory / "capture.json", canonical(capture) + b"\n")
    native_metadata = {}
    if native:
        converted = raster.astype("<f4")
        need(np.isfinite(converted).all(), "Explicit float32 handoff conversion is nonfinite")
        with (directory / "native_float32.npy").open("xb") as stream:
            np.save(stream, np.ascontiguousarray(converted), allow_pickle=False)
            stream.flush(); os.fsync(stream.fileno())
        delta = np.abs(converted.astype(np.float64) - raster)
        nonzero = raster != 0
        conversion = {"schema_version": 1, "conversion": "explicit_requested_binary64_to_binary32",
                      "source_float64_npy_sha256": array_hash,
                      "float32_npy_sha256": sha(read_bytes(directory / "native_float32.npy", MAX_BYTES)),
                      "dtype": "float32", "shape_yx": [size, size], "axes": ["y", "x"], "array_order": "C", "byte_order": "little",
                      "maximum_absolute_error": float(delta.max()),
                      "maximum_relative_error_nonzero": float(np.max(delta[nonzero] / raster[nonzero])) if np.any(nonzero) else 0.,
                      "zeros_preserved": bool(np.all(converted[~nonzero] == 0)),
                      "nonzero_values_rounded_to_zero": int(np.count_nonzero(nonzero & (converted == 0))),
                      "calibration_xy": axes, "source_original_float64_retained": True,
                      "scientific_semantics": info["scientific_semantics"], "external_provenance": info["external_provenance"]}
        write_new(directory / "native-float32.json", canonical(conversion) + b"\n")
        native_metadata = {"native_float32_path": str(directory / "native_float32.npy"),
                           "native_float32_sidecar_path": str(directory / "native-float32.json"), "native_float32_conversion": conversion}
    reflections = {"coordinates_inv_angstrom": coords.tolist(), "hkl": indices.tolist(), "kinematic_intensity": intensities.tolist(),
                   "coordinates_frame": "rotated laboratory xyz; beam +z; raster columns +x, rows +y",
                   "reciprocal_convention": "cycles_per_angstrom_no_2pi", "measurement_authority": "unrastered reflection geometry, not quantized Gaussian raster"}
    write_new(directory / "reflections.json", canonical(reflections) + b"\n")
    from PIL import Image
    shown = np.log1p(raster * 1000.) / math.log1p(1000.)
    memory = io.BytesIO(); Image.fromarray(np.rint(shown * 255).astype(np.uint8)).save(memory, format="PNG")
    write_new(directory / "preview.png", memory.getvalue())
    return {**native_metadata, "orientation": orientation, "reflection_count": len(intensities), "reflections": reflections, "rasterization": rasterization,
            "reciprocal_enumeration": enumeration, "capture_path": str(directory),
            "array_path": str(directory / "input.npy"), "dtype": "float64", "shape_yx": [size, size], "axes": ["gy", "gx"],
            "reciprocal_pixel_scale_inv_angstrom": calibration, "physical_pixel_zero_inv_angstrom": [-(size // 2) * calibration] * 2,
            "parameters": {"voltage_kv": voltage, "euler_rzxz_deg": rotation, "reciprocal_radius_inv_angstrom": radius,
                           "max_excitation_error_inv_angstrom": excitation, "shape_factor": "lorentzian", "shape_factor_width": excitation,
                           "scattering_params": "lobato", "debye_waller_factors": {}, "minimum_intensity_relative": 1e-12,
                           "with_direct_beam": direct, "size": size, "sigma_pixels": sigma, "raster_normalized": True, "native_float32": native},
            "resource_estimate": {"integer_box_candidates": candidates, "atom_reflection_pairs_upper_bound": candidates * len(atoms)},
            "display_recipe": {"mapping": "log1p", "multiplier": 1000., "normalization": "divide_by_log1p_1000",
                               "output_dtype": "uint8", "scientific_raster_modified": False},
            "limitations": ["Kinematic elastic approximation; multiple/dynamical scattering and image contrast transfer are absent.",
                            "Relative intensities are not measured detector counts or phase fractions.",
                            "The library raster quantizes spot centers to integer pixels and overwrites coincident centers; it is qualitative only.",
                            "A compatible projection or reflection set is not unique phase confirmation.",
                            "No thermal displacement factors were supplied; empty library defaults are recorded."],
            "engine": "diffsims.DiffractionGenerator.calculate_ed_data + get_diffraction_pattern", "phase_identified": False}


class StructureWorkspace:
    def __init__(self, root, create=False):
        need(type(root) is str and Path(root).is_absolute(), "Explicit absolute structure workspace required")
        self.root = Path(root).resolve()
        if create:
            (self.root / "objects").mkdir(parents=True, exist_ok=True)
            (self.root / "requests").mkdir(exist_ok=True)
        need(self.root.is_dir(), "Structure workspace does not exist")
        for name in ("objects", "requests"):
            member = self.root / name
            need(member.is_dir() and member.resolve().parent == self.root and not member.is_symlink(),
                 "Structure namespace escapes its configured workspace", "CORRUPT_OBJECT")

    def object(self, ident):
        need(type(ident) is str and ID.fullmatch(ident), "Explicit structure object_id required")
        directory = self.root / "objects" / ident
        need(directory.is_dir() and not directory.is_symlink() and directory.resolve().parent == (self.root / "objects"),
             "Structure object not found or outside workspace", "OBJECT_NOT_FOUND")
        metadata = json_file(directory / "object.json")
        creator = metadata.get("request_id")
        need(metadata.get("object_id") == ident and type(creator) is str and REQUEST_ID.fullmatch(creator), "Stored structure identity differs", "CORRUPT_OBJECT")
        journal = json_file(self.root / "requests" / (creator + ".json"))
        need(journal.get("request_id") == creator and journal.get("parameters", {}).get("request_id") == creator and
             journal.get("parameters", {}).get("workspace") == str(self.root) and
             journal.get("parameters_sha256") == sha(canonical(journal.get("parameters"))) and
             journal.get("state") == "completed" and journal.get("object_manifest_sha256") == sha(read_bytes(directory / "object.json", 8 * MAX_BYTES))
             and journal.get("response") == {"ok": True, "state": "completed", "backend": BACKEND, **metadata},
             "Structure manifest differs from original committed request", "CORRUPT_OBJECT")
        for name, digest in metadata.get("files_sha256", {}).items():
            need(Path(name).name == name and name not in (".", "..", "object.json"), "Unsafe structure file name", "CORRUPT_OBJECT")
            need(sha(read_bytes(directory / name, 8 * MAX_BYTES)) == digest, "Stored structure/scientific file changed", "CORRUPT_OBJECT")
        return metadata, directory

    def structure(self, ident):
        metadata, directory = self.object(ident)
        source_id = metadata.get("structure_object_id", ident)
        if source_id != ident:
            source, directory = self.object(source_id)
        else:
            source = metadata
        need(source["kind"] == "structure", "An atomic structure object is required")
        return metadata, from_data(json_file(directory / "atoms.json")), source_id

    def orientation(self, ident, source_id, atoms):
        metadata, _ = self.object(ident)
        need(metadata.get("kind") == "orient" and metadata.get("structure_object_id") == source_id,
             "orientation_id must reference an orientation of this exact immutable structure", "INVALID_ORIENTATION")
        record = metadata.get("orientation")
        need(type(record) is dict and record.get("orientation_id") == ident and
             record.get("structure_object_id") == source_id and
             record.get("source_atoms_sha256") == sha(canonical(atoms_data(atoms))),
             "Orientation source identity/geometry changed", "INVALID_ORIENTATION")
        return record

    def source_provenance(self, ident):
        """Fixed source and derivations, without re-reading the original file.

        Also understands already-saved objects from before this export field
        existed. Every link is verified against its own immutable journal.
        """
        chain, visited = [], set()
        current = ident
        for _ in range(64):
            need(current not in visited, "Cyclic structure ancestry", "CORRUPT_OBJECT")
            visited.add(current)
            metadata, _ = self.object(current)
            need(metadata.get("kind") == "structure", "Structure ancestry contains a nonstructure", "CORRUPT_OBJECT")
            if "source" in metadata:
                return {"status": "fixed_source_and_verified_derivations", "source_object_id": current,
                        "source": metadata["source"], "parser": {"library": "ASE", "version": metadata["software_provenance"]["ase"],
                                                                 "format": metadata["source"]["format"],
                                                                 "warnings": metadata.get("parser_warnings", [])},
                        "source_atoms_json_sha256": metadata["files_sha256"]["atoms.json"],
                        "derivation_chain": list(reversed(chain)), "original_source_reread": False}
            parent = metadata.get("source_structure_object_id")
            need(type(parent) is str and ID.fullmatch(parent), "Structure source ancestry is missing", "CORRUPT_OBJECT")
            chain.append({"object_id": current, "source_structure_object_id": parent,
                          "request_id": metadata["request_id"], "repeat": metadata["repeat"],
                          "rotation_deg_xyz": metadata["rotation_deg_xyz"],
                          "rotation_convention": metadata["rotation_convention"],
                          "atoms_json_sha256": metadata["files_sha256"]["atoms.json"],
                          "software_provenance": metadata["software_provenance"],
                          **({"orientation": metadata["orientation"]} if metadata.get("orientation") else {})})
            current = parent
        raise StructureError("Structure ancestry exceeds64 immutable derivations", "BUDGET_EXCEEDED")

    def action(self, request):
        action, ident = request["action"], uuid.uuid4().hex
        directory = self.root / "objects" / ident
        directory.mkdir()
        metadata = {"object_id": ident, "request_id": request["request_id"], "kind": action,
                    "created_utc": datetime.now(timezone.utc).isoformat(), "parameters": {k: v for k, v in request.items() if k not in ("workspace", "action", "request_id")}}
        if action == "open":
            atoms, raw, parser_warnings = load_structure(request.get("source_path"))
            extension = Path(request["source_path"]).suffix.lower()
            write_new(directory / ("source" + extension), raw)
            write_new(directory / "atoms.json", canonical(atoms_data(atoms)) + b"\n")
            metadata.update(kind="structure", **summary(atoms), parser_warnings=parser_warnings,
                            source={"path": str(Path(request["source_path"]).resolve()), "sha256": sha(raw), "bytes": len(raw),
                                    "format": extension[1:], "fixed_input_copy": True, "original_file_modified": False,
                                    "coordinate_unit_convention": "ASE CIF1 Angstrom convention" if extension == ".cif" else "ASE XYZ/extXYZ Angstrom convention; not independently verified physical units"})
        else:
            previous, atoms, source_id = self.structure(request.get("object_id"))
            provenance = self.source_provenance(source_id)
            metadata.update(parent_object_id=previous["object_id"], structure_object_id=source_id,
                            source_provenance=provenance, **summary(atoms))
            orientation = self.orientation(request["orientation_id"], source_id, atoms) if "orientation_id" in request else None
            if action == "view":
                need(not (orientation is not None and "rotation_deg_xyz" in request),
                     "Choose orientation_id or display rotation_deg_xyz, never both")
                rotation, size = triple(request.get("rotation_deg_xyz"), "rotation_deg_xyz", [0, 0, 0]), request.get("max_size", 512)
                need(type(size) is int and 128 <= size <= 1024, "max_size must be an integer128..1024")
                need(type(request.get("interactive", False)) is bool, "interactive must be boolean")
                display_atoms = atoms.copy()
                if orientation is not None:
                    matrix = np.asarray(orientation["rotation_matrix_cartesian"])
                    display_atoms.positions = atoms.positions @ matrix.T
                    display_atoms.set_cell(atoms.cell.array @ matrix.T, scale_atoms=False)
                render_atoms(display_atoms, directory, rotation, size)
                metadata.update(renderer="ase.visualize.plot.plot_atoms", projection_only=True, rotation_deg_xyz=rotation,
                                display_does_not_change_atoms=True, max_size=size, interactive_requested=request.get("interactive", False),
                                orientation=orientation,
                                display_recipe={"renderer": "ase.visualize.plot.plot_atoms", "radii": .5, "show_unit_cell": 2,
                                                "rotation_deg_xyz": rotation, "scientific_coordinates_modified": False,
                                                "rotation_matrix_cartesian": orientation["rotation_matrix_cartesian"] if orientation else None,
                                                "display_coordinates_transformed": orientation is not None})
            elif action == "orient":
                record = from_zone_axis(atoms.cell.array, request.get("zone_axis_uvw"),
                                        request.get("in_plane_direction_uvw"), request.get("in_plane_rotation_deg", 0.))
                record.update(orientation_id=ident, structure_object_id=source_id,
                              source_atoms_sha256=sha(canonical(atoms_data(atoms))))
                metadata["orientation"] = record
            elif action == "measure":
                metadata["measurement"] = measure(atoms, request)
            elif action in ("compare", "register"):
                need(previous.get("kind") == "simulate" and previous.get("software_provenance", {}).get("diffsims") == "0.7.0",
                     "object_id must be an actual saved qualified diffsims simulation, not a structure/view/PNG")
                _, simulation_directory = self.object(previous["object_id"])
                need(json_file(simulation_directory / "reflections.json") == previous.get("reflections"),
                     "Saved simulation reflection table contradicts its original result", "CORRUPT_OBJECT")
                paths = request.get("measurement_paths")
                need(type(paths) is list and 1 <= len(paths) <= 32 and all(type(p) is str for p in paths),
                     "Supply1..32 explicit saved image_measure object.json paths")
                measurements, sources, total = [], [], 0
                for index, path in enumerate(paths):
                    row, source, manifest_raw, journal_raw = load_measurement(path)
                    total += len(manifest_raw) + len(journal_raw)
                    need(total <= MAX_BYTES, "Fixed experimental measurement records exceed2MiB", "BUDGET_EXCEEDED")
                    manifest_name = "measurement-{:02d}.json".format(index)
                    journal_name = "measurement-{:02d}-original-request.json".format(index)
                    write_new(directory / manifest_name, manifest_raw)
                    write_new(directory / journal_name, journal_raw)
                    measurements.append(row)
                    sources.append({**source, "fixed_manifest_file": manifest_name, "fixed_journal_file": journal_name,
                                    "measurement_object_id": row["object_id"], "measurement_request_id": row["request_id"]})
                from crystallography.registration_proposal import propose, geometry_binding
                mode = request.get("analysis_mode", "continue_current" if request.get("current_image_object_id") else "standalone_snapshot")
                if action == "register":
                    need(type(request.get("current_image_object_id")) is str,
                         "Registration proposals require an explicitly selected current image revision")
                binding = bind_geometry(measurements, sources, request.get("current_image_object_id"), mode)
                if action == "register":
                    compared = propose(measurements, previous, request.get("fit_correspondences"),
                                       request.get("validation_correspondences", []), request.get("screen_axes"),
                                       request.get("max_residual_inv_angstrom"), request.get("experimental_kind"),
                                       request.get("confirmation"))
                    compared["analysis_binding"] = binding
                else:
                    need(("registration" in request) != ("registration_object_id" in request),
                         "Choose exactly one explicit registration or saved registration_object_id")
                    registration = request.get("registration")
                    registration_record = None
                    if "registration_object_id" in request:
                        need(mode == "continue_current", "A saved registration requires explicit current geometry; use structure_result to review historical records")
                        registration_record, _ = self.object(request["registration_object_id"])
                        need(registration_record.get("kind") == "register" and
                             registration_record.get("simulation_object_id") == previous["object_id"] and
                             registration_record.get("simulation_reflections_sha256") == previous["files_sha256"]["reflections.json"] and
                             registration_record.get("parameters", {}).get("experimental_kind") == request.get("experimental_kind"),
                             "Registration belongs to a different saved simulation")
                        need(canonical(registration_record.get("experimental_geometry_binding")) == canonical(geometry_binding(measurements)) and
                             registration_record.get("analysis_binding", {}).get("scientific_grid_identity") == binding.get("scientific_grid_identity") and
                             registration_record.get("analysis_binding", {}).get("calibration_dependency") == binding.get("calibration_dependency"),
                             "Registration uses different points/centre/scale/capture; remeasure and propose a new registration")
                        registration = registration_record["registration"]
                    compared = compare_reflections(measurements, previous, registration,
                                                   request.get("max_residual_inv_angstrom"), request.get("experimental_kind"),
                                                   request.get("correspondences"))
                    if registration_record:
                        compared["registration"]["parameter_source"] = "proper in-plane rotation from the exact saved constrained registration proposal; no refit during this comparison"
                        compared["registration"]["proposal_object_id"] = registration_record["object_id"]
                        compared["registration"]["fixed_degrees_of_freedom"] = {"scale": 1., "translation_inv_angstrom": [0., 0.], "flip_y": registration["flip_y"]}
                        compared["scientific_limits"] = [
                            "Registration rotation is sourced from a saved constrained fit; this comparison does not refit or change experimental calibration."
                            if value.startswith("Registration is caller supplied") else value
                            for value in compared["scientific_limits"]]
                        compared.update(registration_object_id=registration_record["object_id"],
                                        fit_validation_evidence={key: registration_record.get(key) for key in
                                            ("fit_evidence", "validation_evidence", "fit_status", "validation_status", "held_out_validation_passed")},
                                        comparison_is_not_new_independent_validation=True)
                    old = self.object(request["previous_comparison_id"])[0] if "previous_comparison_id" in request else None
                    compared.update(comparison_revision(ident, old, binding, compared["observations"], previous["object_id"],
                                                        request.get("source_change_basis")))
                need(len(canonical(compared)) <= MAX_BYTES // 2,
                     "Comparison evidence exceeds1MiB; narrow the explicit reflection list/tolerance; no evidence was truncated", "BUDGET_EXCEEDED")
                metadata.update(**compared, simulation_object_id=previous["object_id"],
                                simulation_orientation=previous.get("orientation"),
                                simulation_reflections_sha256=previous["files_sha256"]["reflections.json"],
                                experimental_sources=sources, experimental_source_files_modified=False,
                                source_capture_semantics="fixed original image_measure manifest/request bytes; scientific calibration versions retained without re-reading live DM")
            elif action == "derive":
                need(not (orientation is not None and "rotation_deg_xyz" in request),
                     "Choose orientation_id or active rotation_deg_xyz, never both")
                repeat = request.get("repeat", [1, 1, 1])
                need(type(repeat) is list and len(repeat) == 3 and all(type(v) is int and 1 <= v <= 32 for v in repeat), "repeat must be three positive integers<=32")
                need(len(atoms) * math.prod(repeat) <= MAX_ATOMS, "Repeated structure exceeds atom budget", "BUDGET_EXCEEDED")
                rotation = triple(request.get("rotation_deg_xyz"), "rotation_deg_xyz", [0, 0, 0])
                atoms = atoms.repeat(repeat)
                if orientation is not None:
                    matrix = np.asarray(orientation["rotation_matrix_cartesian"])
                    atoms.positions = atoms.positions @ matrix.T
                    atoms.set_cell(atoms.cell.array @ matrix.T, scale_atoms=False)
                else:
                    for angle, axis in zip(rotation, "xyz"):
                        atoms.rotate(angle, axis, center=(0, 0, 0), rotate_cell=True)
                validate_atoms(atoms)
                write_new(directory / "atoms.json", canonical(atoms_data(atoms)) + b"\n")
                metadata.pop("structure_object_id")
                metadata.update(kind="structure", **summary(atoms), repeat=repeat, rotation_deg_xyz=rotation,
                                orientation=orientation,
                                rotation_convention="active shared orientation matrix; positions+cell rotated about origin" if orientation else "active Cartesian x then y then z; positions+cell rotated about origin", source_structure_object_id=source_id)
            elif action == "simulate":
                metadata.update(**simulate(atoms, request, directory, ident, source_provenance=provenance,
                                           resolved_structure_object_id=source_id, orientation=orientation))
            else:
                raise StructureError("Unknown action")
        metadata.update(schema_version=1, backend=BACKEND, dm_called=False, computation_source="explicit_external_python",
                        software_provenance={"python": platform.python_version(), "ase": ase.__version__, "numpy": np.__version__,
                                             "scipy": importlib.metadata.version("scipy"),
                                             **({"diffsims": importlib.metadata.version("diffsims"), "diffpy.structure": importlib.metadata.version("diffpy.structure")} if action == "simulate" else {}),
                                             "module_sha256": sha(Path(__file__).read_bytes()),
                                             "helper_modules_sha256": {name: sha(Path(__file__).with_name(name).read_bytes()) for name in ("orientation.py", "reflection_compare.py", "registration_proposal.py", "analysis_revision.py")}},
                        files_sha256={file.name: sha(file.read_bytes()) for file in directory.iterdir() if file.is_file()},
                        manifest_path=str(directory / "object.json"))
        if (directory / "preview.png").is_file():
            metadata["image_path"] = str(directory / "preview.png")
        write_new(directory / "object.json", canonical(metadata) + b"\n")
        return metadata


def _execute(request):
    need(type(request) is dict and request.get("action") in FIELDS, "One supported structure action is required")
    action = request["action"]
    need(set(request) <= FIELDS[action] | {"workspace", "action", "request_id"}, "Unknown structure argument")
    canonical(request)
    readonly = action in ("get", "result")
    if not readonly:
        need(type(request.get("request_id")) is str and REQUEST_ID.fullmatch(request["request_id"]), "Save request_id before a write")
    workspace = StructureWorkspace(request.get("workspace"), create=not readonly)
    if action == "get":
        metadata, _ = workspace.object(request.get("object_id"))
        include = request.get("include_atoms", False)
        need(type(include) is bool, "include_atoms must be boolean")
        if include:
            _, atoms, _ = workspace.structure(request["object_id"])
            metadata = {**metadata, "atoms": atoms_data(atoms)}
        return {"ok": True, "state": "completed", "backend": BACKEND, **metadata}
    if action == "result":
        ident = request.get("query_request_id")
        need(type(ident) is str and REQUEST_ID.fullmatch(ident), "Original request_id required")
        original = workspace.root / "requests" / (ident + ".json")
        need(original.is_file(), "Original request not found", "REQUEST_NOT_FOUND")
        try:
            saved = json_file(original)
        except (OSError, ValueError):
            return failure(StructureError("Original request unreadable; not replayed", "INCOMPLETE_REQUEST"), ident, "unknown")
        if saved.get("state") not in ("completed", "failed"):
            return failure(StructureError("Original request is incomplete; not replayed", "INCOMPLETE_REQUEST"), ident, "unknown")
        need(saved.get("request_id") == ident and saved.get("response", {}).get("request_id") == ident, "Request/response identity differs", "CORRUPT_OBJECT")
        if saved["state"] == "completed":
            workspace.object(saved["response"]["object_id"])
        return saved["response"]
    normalized = {**request, "workspace": str(workspace.root)}
    ident = normalized["request_id"]
    fingerprint = sha(canonical(normalized))
    journal = workspace.root / "requests" / (ident + ".json")
    try:
        stream = journal.open("x+", encoding="utf-8")
    except FileExistsError:
        try:
            saved = json_file(journal)
        except (OSError, ValueError):
            return failure(StructureError("Original request unreadable; not replayed", "INCOMPLETE_REQUEST"), ident, "unknown")
        need(saved.get("parameters_sha256") == fingerprint, "Same request_id has different action/parameters", "REQUEST_CONFLICT")
        need(saved.get("request_id") == ident and saved.get("parameters") == normalized,
             "Original request record identity/parameters differ", "CORRUPT_OBJECT")
        if saved.get("state") not in ("completed", "failed"):
            return failure(StructureError("Original request incomplete; not replayed", "INCOMPLETE_REQUEST"), ident, "unknown")
        need(saved.get("response", {}).get("request_id") == ident, "Original response belongs to another request", "CORRUPT_OBJECT")
        if saved["state"] == "completed":
            workspace.object(saved["response"]["object_id"])
        return saved["response"]
    record = {"schema_version": 1, "request_id": ident, "state": "prepared", "parameters": normalized, "parameters_sha256": fingerprint}
    with stream:
        def update():
            stream.seek(0); stream.truncate(); stream.write(canonical(record).decode("utf-8") + "\n"); stream.flush(); os.fsync(stream.fileno())
        update()
        try:
            metadata = workspace.action(normalized)
            response = {"ok": True, "state": "completed", "backend": BACKEND, **metadata}
            record.update(state="completed", response=response, object_manifest_sha256=sha(read_bytes(metadata["manifest_path"], 8 * MAX_BYTES)))
        except Exception as error:
            response = failure(error, ident)
            record.update(state="failed", response=response)
        update()
        return response


def failure(error, ident=None, state="failed"):
    return {"ok": False, "state": state, "backend": BACKEND, "request_id": ident, "automatic_retry": False,
            "error": {"code": getattr(error, "code", "STRUCTURE_ERROR"), "message": str(error)}}


def execute(request):
    try:
        response = _execute(request)
        return {"ok": True, "result": {k: v for k, v in response.items() if k != "ok"}} if response.get("ok") else response
    except Exception as error:
        return failure(error, request.get("request_id") if type(request) is dict else None)
