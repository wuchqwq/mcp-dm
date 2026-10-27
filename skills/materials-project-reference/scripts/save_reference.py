"""Local format handoff for an already fetched official MP MCP response.

No API, search, server, simulator or DM dependency. ASE converts POSCAR to CIF;
the original bytes and candidate provenance remain beside the converted file.
"""
import argparse
from datetime import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import re

import ase
from ase.io import read, write
import numpy as np

MAX_BYTES = 2 * 1024 * 1024
MAX_ATOMS = 4096


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def need(ok, message):
    if not ok:
        raise ValueError(message)


def strict_object(pairs):
    value = {}
    for key, item in pairs:
        need(key not in value, "Duplicate JSON field")
        value[key] = item
    return value


def write_new(path, raw):
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def save_reference(input_json, output_dir, query, retrieved_utc, provider_version=None):
    source, output = Path(input_json), Path(output_dir)
    need(source.is_absolute() and source.is_file() and not source.is_symlink(),
         "An absolute ordinary fetched JSON file is required")
    need(0 < source.stat().st_size <= MAX_BYTES, "Fetched JSON exceeds 2 MiB budget")
    with source.open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    need(0 < len(raw) <= MAX_BYTES, "Fetched JSON changed beyond byte budget")
    data = json.loads(raw.decode("utf-8"), object_pairs_hook=strict_object,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite JSON")))
    need(type(data) is dict and set(data) <= {"id", "title", "text", "url", "metadata"},
         "Save the exact official fetch object, not an MCP transport envelope")
    mp_id = data.get("id")
    need(isinstance(mp_id, str) and re.fullmatch(r"mp-[0-9]+", mp_id), "An exact MP ID is required")
    metadata = data.get("metadata")
    need(type(metadata) is dict and metadata.get("material_id", mp_id) in (None, mp_id),
         "Fetched metadata has a conflicting MP identity")
    poscar = metadata.get("poscar")
    need(isinstance(poscar, str) and 0 < len(poscar.encode("utf-8")) <= MAX_BYTES,
         "Official response has no bounded POSCAR structure; do not infer one")
    lines = poscar.splitlines()
    need(len(lines) >= 8, "Incomplete POSCAR")
    # The official serializer supplies VASP5 species/count lines. Check the
    # resource bound before ASE allocates atoms; legacy variants are not guessed.
    counts = lines[6].split()
    need(counts and all(re.fullmatch(r"[0-9]+", value) for value in counts),
         "Expected official VASP5 POSCAR counts")
    need(len(lines[5].split()) == len(counts) and 1 <= sum(map(int, counts)) <= MAX_ATOMS,
         "POSCAR exceeds 1..4096 atom budget or species/count mismatch")
    atoms = read(io.StringIO(poscar), format="vasp")
    need(1 <= len(atoms) <= MAX_ATOMS and np.isfinite(atoms.positions).all()
         and np.isfinite(atoms.cell.array).all() and np.linalg.matrix_rank(atoms.cell.array) == 3,
         "Structure requires finite sites and a full-rank cell")
    need(metadata.get("nsites", len(atoms)) in (None, len(atoms)), "Fetched atom count disagrees with POSCAR")
    if metadata.get("atoms") is not None:
        need(metadata["atoms"] == atoms.get_chemical_symbols(), "Fetched species disagree with POSCAR")
    if metadata.get("cell_vectors") is not None:
        declared_cell = np.asarray(metadata["cell_vectors"], dtype=float)
        need(declared_cell.shape == (3, 3) and np.isfinite(declared_cell).all()
             and np.allclose(declared_cell, atoms.cell.array, atol=1e-10, rtol=1e-12),
             "Fetched cell vectors disagree with POSCAR")
    if metadata.get("cartesian_coordinates") is not None:
        declared_positions = np.asarray(metadata["cartesian_coordinates"], dtype=float)
        need(declared_positions.shape == (len(atoms), 3) and np.isfinite(declared_positions).all(),
             "Fetched Cartesian sites are malformed")
        fractional_delta = (declared_positions - atoms.positions) @ np.linalg.inv(atoms.cell.array)
        fractional_delta -= np.rint(fractional_delta)
        need(np.max(np.abs(fractional_delta)) <= 1e-10, "Fetched sites disagree with POSCAR")
    need(isinstance(query, str) and 0 < len(query) <= 4000, "Record the actual bounded search query")
    stamp = datetime.fromisoformat(retrieved_utc.replace("Z", "+00:00"))
    need(stamp.utcoffset() is not None and stamp.utcoffset().total_seconds() == 0,
         "Retrieval time must include UTC offset")
    need(provider_version is None or isinstance(provider_version, str) and 0 < len(provider_version) <= 128,
         "Invalid provider version")

    buffer = io.BytesIO()
    write(buffer, atoms, format="cif")
    cif = buffer.getvalue()
    need(0 < len(cif) <= MAX_BYTES, "Converted CIF exceeds existing structure-file budget")
    reopened = read(io.BytesIO(cif), format="cif", reader="ase", primitive_cell=False)
    need(atoms.get_chemical_symbols() == reopened.get_chemical_symbols(), "CIF round trip changed sites")
    # CIF stores lengths/angles, so its Cartesian basis may be canonicalized.
    # Compare metric and fractional sites, not an arbitrary Cartesian rotation.
    metric = atoms.cell.array @ atoms.cell.array.T
    reopened_metric = reopened.cell.array @ reopened.cell.array.T
    delta = atoms.get_scaled_positions() - reopened.get_scaled_positions()
    delta -= np.rint(delta)
    need(np.allclose(metric, reopened_metric, atol=1e-10, rtol=1e-12)
         and np.max(np.abs(delta)) <= 1e-10, "CIF round trip failed fixed metric/site tolerance")

    need(output.is_absolute() and output.parent.is_dir(), "Fresh absolute output directory with existing parent required")
    output.mkdir()  # Existing targets, including incomplete attempts, refuse.
    original_poscar = poscar.encode("utf-8")
    files = {"fetch-response.json": raw, "source.poscar": original_poscar, "structure.cif": cif}
    for filename, payload in files.items():
        write_new(output / filename, payload)
    record = {"schema_version": 1, "state": "completed", "interpretation_status": "hypothesized",
              "candidate_origin": "Materials Project reference; not an experimental phase confirmation",
              "mp_id": mp_id, "url": "https://next-gen.materialsproject.org/materials/" + mp_id,
              "returned_url": data.get("url"), "query": query, "retrieved_utc": retrieved_utc,
              "provider": "official mp_api.mcp.server", "provider_version": provider_version,
              "structure_version": metadata.get("last_updated"),
              "structure_path": str(output / "structure.cif"), "length_unit": "angstrom",
              "conversion": {"engine": "ASE", "version": ase.__version__, "from": "POSCAR", "to": "CIF1",
                             "cartesian_basis": "CIF may canonicalize orientation; metric and fractional sites verified",
                             "max_metric_error_angstrom_squared": float(np.max(np.abs(metric - reopened_metric))),
                             "max_fractional_site_error": float(np.max(np.abs(delta))),
                             "metric_atol": 1e-10, "metric_rtol": 1e-12, "fractional_atol": 1e-10},
              "files": {name: {"sha256": sha(value), "bytes": len(value)} for name, value in files.items()}}
    # A directory without this last fsynced completion record is incomplete.
    write_new(output / "reference.json", (json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8"))
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-json", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--retrieved-utc", required=True)
    parser.add_argument("--provider-version")
    args = parser.parse_args()
    record = save_reference(args.input_json, args.output_dir, args.query, args.retrieved_utc, args.provider_version)
    print(json.dumps(record, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
