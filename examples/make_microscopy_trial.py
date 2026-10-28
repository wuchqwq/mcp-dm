"""Create a small, public synthetic input for the Codex/Image Panel walkthrough.

Run with the independent requirements-images.txt environment, never GMS Python.
The manifest is an independent fixture specification, not experimental evidence.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import tifffile


def create_trial(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    y, x = np.mgrid[:96, :128]
    frames = []
    for phase in (0.0, np.pi / 4, np.pi / 2):
        values = (24000 + 6000 * np.cos(2 * np.pi * x / 8 + phase)
                  + 3000 * np.cos(2 * np.pi * y / 16))
        frames.append(np.rint(values).astype(np.uint16))
    source = output / "periodic-sequence.tiff"
    # Separate ordinary 2D grayscale pages; no inferred physical TIFF scale.
    with tifffile.TiffWriter(source) as writer:
        for frame in frames:
            writer.write(frame, photometric="minisblack", metadata=None)
    manifest = {
        "kind": "synthetic-microscopy-trial", "schema_version": 1,
        "source": source.name, "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "shape_fyx": [3, 96, 128], "dtype": "uint16",
        "frequency_cycles_per_pixel_xy": [[1 / 8, 0], [0, 1 / 16]],
        "suggested_roi_xyxy": [16, 16, 112, 80],
        "synthetic_user_statement": "Synthetic trial only: X/Y = 0.02 nm per original pixel, entire sequence.",
        "expected_periods_nm": [0.16, 0.32],
        "limits": "Known ideal tones test coordinates and revisable measurements, not phase identification or resolution.",
    }
    (output / "fixture-specification.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return source


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", help="New output directory; existing directories are refused")
    print(create_trial(parser.parse_args().output))
