"""Read-only ASE adapter for one user-supplied crystal CIF reference.

This module deliberately imports no scientific package at import time. It reads
an existing reference file, not a DM image, and does not infer a phase, a
centering condition, or a conventional cell from an arbitrary primitive cell.
"""

import hashlib
import importlib
import io
import math
import os
from pathlib import Path
import stat
import warnings


MAX_CIF_BYTES = 1024 * 1024
CUBIC_LENGTH_RELATIVE_TOLERANCE = 1e-6
CUBIC_ANGLE_TOLERANCE_DEGREES = 1e-5
HEXAGONAL_LENGTH_RELATIVE_TOLERANCE = 1e-6
HEXAGONAL_ANGLE_TOLERANCE_DEGREES = 1e-5


class CubicReferenceError(ValueError):
    """The supplied reference cannot satisfy the selected narrow cell contract.

    The historical name remains compatible with callers of the cubic adapter.
    """


StructureReferenceError = CubicReferenceError


class OptionalDependencyError(ImportError):
    """The independent crystallography environment is missing a dependency.

    The existing name remains compatible; ASE is now a base companion
    dependency for the mature HCP reciprocal-cell implementation as well.
    """


def _ase_modules():
    try:
        ase = importlib.import_module("ase")
        ase_io = importlib.import_module("ase.io")
        ase_cif = importlib.import_module("ase.io.cif")
    except ImportError as error:
        raise OptionalDependencyError(
            "CIF references require ASE and its dependencies in the independent "
            "crystallography environment. Run that environment's Python with "
            "'-m pip install -r requirements-crystallography.txt'; "
            "do not install into GMS Python."
        ) from error
    return ase, ase_io, ase_cif


def _read_reference_bytes(path):
    if isinstance(path, (bytes, bool)) or not isinstance(path, (str, os.PathLike)):
        raise CubicReferenceError("CIF path must be a filesystem path, not file bytes")
    source = Path(path)
    if source.suffix.lower() != ".cif":
        raise CubicReferenceError("Only an ordinary, uncompressed .cif reference is supported")
    try:
        source_stat = source.lstat()
        if not stat.S_ISREG(source_stat.st_mode) or source.is_symlink():
            raise CubicReferenceError("CIF reference must be an ordinary file")
        if not 0 < source_stat.st_size <= MAX_CIF_BYTES:
            raise CubicReferenceError("CIF reference must contain 1..1048576 bytes")
        with source.open("rb") as stream:
            payload = stream.read(MAX_CIF_BYTES + 1)
    except OSError as error:
        raise CubicReferenceError("Cannot read CIF reference: {}".format(error)) from error
    if not 0 < len(payload) <= MAX_CIF_BYTES:
        raise CubicReferenceError("CIF reference must contain 1..1048576 bytes")
    if any(value < 32 and value not in (9, 10, 13) for value in payload) or b"\x7f" in payload:
        raise CubicReferenceError("CIF reference contains binary/control bytes")
    # ASE's CIF1 parser owns its documented Latin-1 byte interpretation. Do not
    # guess another encoding or rewrite the original bytes. Its CIF2 warning is
    # not sufficient qualification for a file format this adapter does not own.
    if payload.lstrip().startswith(b"#\\#CIF_2.0"):
        raise CubicReferenceError("CIF 2.0 is not supported by this CIF1 reference adapter")
    return source.resolve(), payload


def _cell_parameters(values):
    try:
        parameters = [float(value) for value in values]
    except (TypeError, ValueError, OverflowError) as error:
        raise CubicReferenceError("CIF must declare six finite numeric cell parameters") from error
    if len(parameters) != 6 or not all(math.isfinite(value) for value in parameters):
        raise CubicReferenceError("CIF must declare six finite numeric cell parameters")
    lengths = parameters[:3]
    if min(lengths) <= 0:
        raise CubicReferenceError("CIF cell lengths must be strictly positive")
    return parameters


def _cubic_parameters(values):
    parameters = _cell_parameters(values)
    lengths = parameters[:3]
    angles = parameters[3:]
    mean_length = math.fsum(lengths) / 3.0
    relative_spread = (max(lengths) - min(lengths)) / mean_length
    if relative_spread > CUBIC_LENGTH_RELATIVE_TOLERANCE:
        raise CubicReferenceError("CIF must already use a conventional cubic cell: a, b and c differ")
    if any(abs(angle - 90.0) > CUBIC_ANGLE_TOLERANCE_DEGREES for angle in angles):
        raise CubicReferenceError(
            "CIF must already use a conventional cubic cell with 90 degree angles; "
            "primitive/rhombohedral cells are not silently standardized"
        )
    return parameters, mean_length


def _hexagonal_parameters(values):
    parameters = _cell_parameters(values)
    a, b, c, alpha, beta, gamma = parameters
    mean_a = math.fsum((a, b)) / 2.0
    if abs(a - b) / mean_a > HEXAGONAL_LENGTH_RELATIVE_TOLERANCE:
        raise CubicReferenceError("CIF must already use a conventional hexagonal cell: a and b differ")
    if (abs(alpha - 90.0) > HEXAGONAL_ANGLE_TOLERANCE_DEGREES or
            abs(beta - 90.0) > HEXAGONAL_ANGLE_TOLERANCE_DEGREES or
            abs(gamma - 120.0) > HEXAGONAL_ANGLE_TOLERANCE_DEGREES):
        raise CubicReferenceError(
            "CIF must already use a conventional hexagonal cell with alpha=beta=90 and gamma=120 degrees; "
            "rhombohedral/other settings are not silently standardized"
        )
    if not math.isfinite(c / mean_a):
        raise CubicReferenceError("Hexagonal c/a must be finite")
    return parameters, mean_a


def load_reference(path, *, label, model):
    """Read one CIF using ASE, preserving its bytes and explicit assumptions.

    ``model`` must be the explicit ``FCC``, ``BCC``, ``P`` (cubic) or ``HCP``
    hypothesis. Cubic models require a conventional cubic cell. HCP requires
    a declared conventional hexagonal cell, with its own independent a and c.
    Model, centering, symmetry and material identity are never inferred from
    CIF tags. In particular, a hexagonal metric does not qualify an HCP basis,
    occupancies, structure-factor extinction, or chemical phase.
    """
    if not isinstance(label, str) or not label.strip() or len(label) > 128:
        raise CubicReferenceError("Reference label must be a nonempty string of at most 128 characters")
    if any(ord(character) < 32 or ord(character) == 127 for character in label):
        raise CubicReferenceError("Reference label must not contain control characters")
    if model not in ("FCC", "BCC", "P", "HCP"):
        raise CubicReferenceError("Reference model must be explicitly supplied as FCC, BCC, P or HCP")
    centering = {"FCC": "F", "BCC": "I", "P": "P", "HCP": "P"}[model]
    hexagonal = model == "HCP"
    parameter_reader = _hexagonal_parameters if hexagonal else _cubic_parameters
    source, payload = _read_reference_bytes(path)
    ase, ase_io, ase_cif = _ase_modules()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            # Use the mature parser for block boundaries and declared cell tags;
            # do not introduce a competing CIF tokenizer or silently pick one
            # structure from a multi-reference file.
            blocks = list(ase_cif.parse_cif(io.BytesIO(payload), reader="ase"))
            if len(blocks) != 1 or not blocks[0].has_structure():
                raise CubicReferenceError("CIF must contain exactly one data block with atomic structure")
            declared_parameters, mean_length = parameter_reader(blocks[0].get_cellpar())
            atoms = ase_io.read(
                io.BytesIO(payload), format="cif", index=0,
                reader="ase", primitive_cell=False, store_tags=False,
            )
            observed_parameters, _ = parameter_reader(atoms.cell.cellpar())
            if int(atoms.cell.rank) != 3:
                raise CubicReferenceError("CIF must have a full-rank three-dimensional cell")
            volume = float(atoms.get_volume())
            if not math.isfinite(volume) or volume <= 0:
                raise CubicReferenceError("CIF cell volume must be finite and strictly positive")
            if len(atoms) < 1:
                raise CubicReferenceError("CIF must contain at least one atomic site")
            if not all(math.isfinite(float(value)) for value in atoms.positions.flat):
                raise CubicReferenceError("CIF atomic positions must be finite")
            # The raw cell supplied by the user must survive parsing; this is
            # intentionally not a primitive-to-conventional transformation.
            for declared, observed in zip(declared_parameters, observed_parameters):
                if not math.isclose(declared, observed, rel_tol=1e-12, abs_tol=1e-10):
                    raise CubicReferenceError("ASE changed the declared cell; no automatic standardization is allowed")
        except CubicReferenceError:
            raise
        except Exception as error:
            raise CubicReferenceError(
                "ASE could not parse the supported {} CIF reference ({}): {}".format(
                    model,
                    type(error).__name__, error
                )
            ) from error
    parser_warnings = []
    for warning in caught:
        item = {"category": warning.category.__name__, "message": str(warning.message)}
        if item not in parser_warnings:
            parser_warnings.append(item)
    names = ("a_angstrom", "b_angstrom", "c_angstrom", "alpha_deg", "beta_deg", "gamma_deg")
    metric_policy = {
        "length_relative_tolerance": (HEXAGONAL_LENGTH_RELATIVE_TOLERANCE if hexagonal
                                      else CUBIC_LENGTH_RELATIVE_TOLERANCE),
        "angle_tolerance_degrees": (HEXAGONAL_ANGLE_TOLERANCE_DEGREES if hexagonal
                                    else CUBIC_ANGLE_TOLERANCE_DEGREES),
        "cell_standardized": False,
        "symmetry_qualified": False,
        "basis_qualified": False,
    }
    result = {
        "label": label,
        "model": model,
        "lattice_system": "hexagonal" if hexagonal else "cubic",
        "centering": centering,
        "centering_source": "explicit_user_hypothesis_not_inferred_from_cif",
        "cell_parameters": dict(zip(names, declared_parameters)),
        "cell_volume_angstrom3": volume,
        "atom_count": len(atoms),
        "reference_kind": "user_supplied_not_phaseproof",
        "computation_source": "external_python_ase",
        "source": {
            "path": str(source),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size_bytes": len(payload),
            "format": "cif1",
            "data_block": str(blocks[0].name),
            "structure_index": 0,
            "bytes_modified": False,
        },
        "library": {"name": "ase", "version": str(ase.__version__), "reader": "ase.io.read"},
        "metric_policy": metric_policy,
        "parser_warnings": parser_warnings,
        "warnings": [
            "User-supplied lattice metric only; a successful parse does not prove a material phase.",
            "Centering is an explicit hypothesis, not verified CIF symmetry or basis extinction.",
            "Atomic sites may be expanded by ASE's CIF reader; chemistry and occupancies are not qualified.",
            "CIF numerical uncertainties are not propagated into this lattice parameter.",
        ],
    }
    if hexagonal:
        c_nm = declared_parameters[2] * 0.1
        result.update({
            "lattice_parameter_a_nm": mean_length * 0.1,
            "lattice_parameter_c_nm": c_nm,
            "c_over_a": declared_parameters[2] / mean_length,
            "lattice_parameter_policy": "mean_of_declared_a_b_and_independent_declared_c",
            "hexagonal_metric_policy": dict(metric_policy),
            "orientation_convention": {
                "cell_setting": "declared_conventional_hexagonal_gamma_120_degrees",
                "direct_basis": "a1=(a,0,0); a2=(-a/2,sqrt(3)*a/2,0); c=(0,0,c)",
                "reciprocal_convention": "cycles_per_length_no_2pi",
                "reflection_indices": "three_index_(h,k,l); Miller-Bravais_i=-(h+k)",
                "zone_indices": "three_index_direct_basis_[u,v,w]; not_Miller-Bravais_[u,v,t,w]",
                "orientation_inferred_from_cif": False,
            },
        })
        result["warnings"].append(
            "The HCP hypothesis uses a primitive hexagonal metric; the supplied atomic basis, "
            "occupancies and HCP structure-factor extinction are not qualified by this loader."
        )
        result["warnings"].append("No ideal HCP c/a ratio is imposed; a and c come from the user reference.")
    else:
        result.update({
            "lattice_parameter_nm": mean_length * 0.1,
            "lattice_parameter_a_nm": mean_length * 0.1,
            "lattice_parameter_policy": "mean_of_declared_conventional_cubic_lengths",
            "cubic_metric_policy": dict(metric_policy),
        })
    return result


def load_cubic_reference(path, *, label, centering):
    """Backward-compatible F/I/P entrypoint for conventional cubic references."""
    if centering not in ("F", "I", "P"):
        raise CubicReferenceError("Reference centering must be explicitly supplied as F, I or P")
    model = {"F": "FCC", "I": "BCC", "P": "P"}[centering]
    return load_reference(path, label=label, model=model)
