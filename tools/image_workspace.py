"""Explicit external TIFF/pixel workspace; no DM imports or native fallback.

One JSON request on stdin produces one JSON result on stdout. Objects and
request identities are durable and immutable after successful publication.
Python >=3.10 with requirements-images.txt belongs outside GMS Python.
"""
import hashlib
import io
import json
import math
import os
import platform
from pathlib import Path
import re
import sys
from datetime import datetime, timezone
import uuid

import numpy as np
import PIL
from PIL import Image, ImageDraw
import tifffile

BACKEND = "external-image-workspace"
MAX_PIXELS = 4 * 1024 * 1024
MAX_ARRAY_BYTES = 64 * 1024 * 1024
MAX_SOURCE_BYTES = 4 * 1024 * 1024 * 1024
MAX_PAGES = 4096
MAX_JSON_BYTES = 2 * 1024 * 1024
REQUEST_ID = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
OBJECT_ID = re.compile(r"[a-f0-9]{32}\Z")
FIELDS = {
    "open": {"source_path"}, "frame": {"object_id", "frame_index"},
    "import_capture": {"source_path"},
    "view": {"object_id", "rect", "display_range", "gamma", "max_size"},
    "compare": {"object_ids", "rect", "display_range", "gamma", "max_size"},
    "fft": {"object_id", "rect", "window", "subtract_mean", "max_size"},
    "annotate": {"object_id", "annotations"}, "context": {"object_id", "metadata"},
    "measure": {"object_id", "points"}, "export": {"object_id", "output_dir"},
    "get": {"object_id"}, "result": {"query_request_id"},
}


class WorkspaceError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def need(condition, message, code="INVALID_ARGUMENT"):
    if not condition:
        raise WorkspaceError(code, message)


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def integer(value, minimum, maximum):
    return type(value) is int and minimum <= value <= maximum


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def strict_json(raw):
    def pairs(rows):
        result = {}
        for key, value in rows:
            need(key not in result, "Duplicate JSON key")
            result[key] = value
        return result
    def finite_float(token):
        result = float(token)
        need(math.isfinite(result), "Nonfinite JSON number")
        return result
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_float=finite_float,
                      parse_constant=lambda value: (_ for _ in ()).throw(WorkspaceError("INVALID_ARGUMENT", "Nonfinite JSON")))


def sha_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        while True:
            block = source.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def write_new(path, raw):
    with Path(path).open("xb") as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())


def read_json(path):
    path = Path(path)
    need(path.is_file() and not path.is_symlink() and path.stat().st_size <= MAX_JSON_BYTES,
         "Missing, linked or oversized metadata", "CORRUPT_OBJECT")
    return strict_json(path.read_text(encoding="utf-8"))


def stat_identity(path):
    value = Path(path).stat()
    # These identities can exceed JSON/JavaScript's exact integer range.
    # Decimal strings preserve the Python -> Node -> MCP round trip.
    return {"size": value.st_size, "mtime_ns": str(value.st_mtime_ns), "ctime_ns": str(value.st_ctime_ns),
            "inode": str(value.st_ino), "device": str(value.st_dev)}


def source_identity(path):
    path = Path(path)
    need(path.is_file() and not path.is_symlink(), "Source must be an ordinary file")
    before = stat_identity(path)
    need(0 < before["size"] <= MAX_SOURCE_BYTES, "Source file exceeds streaming hash budget", "BUDGET_EXCEEDED")
    digest = sha_file(path)
    need(before == stat_identity(path), "Source changed while hashing", "SOURCE_CHANGED")
    return {"path": str(path.resolve()), "stat": before, "sha256": digest}


def check_source(identity):
    need(source_identity(identity["path"]) == identity, "Original source changed; open a new explicit identity", "SOURCE_CHANGED")


def absolute(value, label):
    need(type(value) is str and bool(value) and Path(value).is_absolute(), label + " must be an explicit absolute path")
    return Path(value)


def scalar_shape(shape, dtype):
    need(len(shape) == 2 and all(integer(int(n), 1, MAX_PIXELS) for n in shape), "Only a nonempty scalar XY plane is supported")
    pixels = int(shape[0]) * int(shape[1])
    need(pixels <= MAX_PIXELS and pixels * np.dtype(dtype).itemsize <= MAX_ARRAY_BYTES,
         "Plane exceeds pixel/decoded byte budget", "BUDGET_EXCEEDED")


def page_info(page, index):
    shape, dtype = tuple(page.shape), np.dtype(page.dtype)
    scalar_shape(shape, dtype)
    need(dtype == np.dtype("uint16") and page.samplesperpixel == 1 and
         int(page.photometric) in (0, 1), "TIFF requires ordinary 2D grayscale uint16 pages; RGB/palette/other dtypes are unsupported", "UNSUPPORTED_LAYOUT")
    return {"frame_index": index, "shape_yx": list(shape), "dtype": "uint16", "axes": ["y", "x"],
            "decoded_bytes": int(np.prod(shape)) * 2, "photometric_code": int(page.photometric),
            "compression_code": int(page.compression)}


def load_array(path, allow_complex=False):
    path = Path(path)
    need(path.is_file() and not path.is_symlink() and path.stat().st_size <= MAX_ARRAY_BYTES + 65536,
         "Scientific NPY exceeds budget or is missing", "CORRUPT_OBJECT")
    with path.open("rb") as source:
        version = np.lib.format.read_magic(source)
        need(version in ((1, 0), (2, 0)), "Unsupported NPY header")
        shape, fortran, dtype = (np.lib.format.read_array_header_1_0(source) if version == (1, 0)
                                 else np.lib.format.read_array_header_2_0(source))
        need(not dtype.hasobject and not fortran and dtype.kind in (("u", "i", "f", "c") if allow_complex else ("u", "i", "f")),
             "Unsupported scientific NPY scalar layout")
        scalar_shape(shape, dtype)
        need(source.tell() + int(np.prod(shape)) * dtype.itemsize == path.stat().st_size, "NPY payload size differs")
    values = np.load(path, allow_pickle=False)
    need(values.dtype in tuple(np.dtype(name) for name in ("uint8", "uint16", "uint32", "int8", "int16", "int32", "float32", "float64", "complex128")) and
         (allow_complex or values.dtype.kind != "c"), "Unsupported scalar precision; uint64/int64 are not silently converted")
    need(np.isfinite(values).all(), "Nonfinite scientific pixels are not supported")
    return values


def save_array(directory, name, values):
    with (directory / name).open("xb") as output:
        np.save(output, np.ascontiguousarray(values), allow_pickle=False)
        output.flush()
        os.fsync(output.fileno())


def save_png(path, image):
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    write_new(path, buffer.getvalue())


def rectangle(value, shape):
    height, width = shape
    rect = [0, 0, width, height] if value is None else value
    need(type(rect) is list and len(rect) == 4 and all(integer(v, 0, MAX_PIXELS) for v in rect) and
         0 <= rect[0] < rect[2] <= width and 0 <= rect[1] < rect[3] <= height,
         "rect requires in-bounds half-open integer [x0,y0,x1,y1]; no clipping")
    return list(rect)


def cut(values, rect):
    return values[rect[1]:rect[3], rect[0]:rect[2]]


def display_options(request, values):
    gamma, maximum = request.get("gamma", 1.0), request.get("max_size", 1024)
    need(number(gamma) and gamma > 0 and math.isfinite(1.0 / gamma), "gamma must be finite and positive")
    need(integer(maximum, 1, 1024), "max_size must be an integer in 1..1024")
    supplied = request.get("display_range")
    if supplied is None:
        low = min(float(value.min()) for value in values)
        high = max(float(value.max()) for value in values)
    else:
        need(type(supplied) is list and len(supplied) == 2 and all(number(v) for v in supplied) and supplied[0] < supplied[1],
             "display_range requires finite [minimum,maximum] with minimum<maximum")
        low, high = map(float, supplied)
    return {"display_range": [low, high], "range_source": "explicit" if supplied is not None else "shared_raw_minmax",
            "gamma": float(gamma), "max_size": maximum, "constant_range": low == high,
            "display_only": True, "quantitative": False,
            "resampling": "Pillow LANCZOS thumbnail; display interpolation only, no scientific resampling"}


def render(values, settings, bound):
    low, high = settings["display_range"]
    scaled = np.zeros(values.shape, dtype=np.float64) if low == high else np.clip((values.astype(np.float64) - low) / (high - low), 0, 1)
    scaled = np.power(scaled, 1.0 / settings["gamma"])
    pixels = np.floor(scaled * 255 + 0.5).astype(np.uint8)
    image = Image.fromarray(pixels)
    image.thumbnail(bound, Image.Resampling.LANCZOS)
    return image


def stats(values):
    floating = values.astype(np.float64)
    result = {"sample_count": int(values.size), "dtype": str(values.dtype), "minimum": float(floating.min()),
              "maximum": float(floating.max()), "mean": float(np.mean(floating)), "stddev": float(np.std(floating))}
    need(all(number(v) for k, v in result.items() if k != "dtype"), "Statistics exceed finite binary64 range")
    return result


class Workspace:
    def __init__(self, root, writable):
        root = absolute(root, "workspace")
        need(not root.is_symlink(), "Linked workspace is unsupported")
        if writable:
            root.mkdir(parents=True, exist_ok=True)
        need(root.is_dir(), "Workspace does not exist")
        self.root = root.resolve()
        for name in ("objects", "requests"):
            path = self.root / name
            if writable:
                path.mkdir(exist_ok=True)
            need(path.is_dir() and not path.is_symlink(), "Workspace directory is missing or linked")

    def object(self, ident):
        need(type(ident) is str and OBJECT_ID.fullmatch(ident), "Explicit workspace object_id required")
        directory = self.root / "objects" / ident
        need(directory.is_dir() and not directory.is_symlink(), "Object does not exist", "OBJECT_NOT_FOUND")
        metadata = read_json(directory / "object.json")
        need(metadata.get("object_id") == ident and metadata.get("backend") == BACKEND, "Object identity mismatch", "CORRUPT_OBJECT")
        creator = metadata.get("request_id")
        need(type(creator) is str and REQUEST_ID.fullmatch(creator), "Object creator identity missing", "CORRUPT_OBJECT")
        original = read_json(self.root / "requests" / (creator + ".json"))
        need(original.get("state") == "completed" and original.get("object_manifest_sha256") == sha_file(directory / "object.json") and
             original.get("response", {}).get("object_id") == ident, "Immutable object manifest changed or was not committed", "CORRUPT_OBJECT")
        need(original["response"] == {"ok": True, "state": "completed", "backend": BACKEND, "request_id": creator, **metadata},
             "Immutable object and original response disagree", "CORRUPT_OBJECT")
        for name, digest in metadata.get("files_sha256", {}).items():
            need(Path(name).name == name and name not in (".", "..", "object.json"), "Unsafe object file", "CORRUPT_OBJECT")
            path = directory / name
            need(path.is_file() and not path.is_symlink() and sha_file(path) == digest, "Immutable object file changed", "CORRUPT_OBJECT")
        if metadata.get("kind") == "export":
            output = Path(metadata["output_dir"])
            for name, digest in metadata["exported_files_sha256"].items():
                need(Path(name).name == name and (output / name).is_file() and not (output / name).is_symlink() and
                     sha_file(output / name) == digest, "Exported immutable file changed", "CORRUPT_OBJECT")
        return metadata, directory

    def resolved(self, ident):
        context, visited = None, set()
        while True:
            need(ident not in visited and len(visited) < 32, "Object context cycle or depth exceeded", "CORRUPT_OBJECT")
            visited.add(ident)
            metadata, directory = self.object(ident)
            if metadata["kind"] != "context":
                return metadata, directory, context
            if context is None:
                context = metadata["user_context"]
            ident = metadata["base_object_id"]

    def scalar(self, ident):
        metadata, directory, context = self.resolved(ident)
        need(metadata["kind"] in ("frame", "view"), "Operation requires a scalar frame/view object, not a TIFF source, composite or complex spectrum")
        return metadata, directory, context, load_array(directory / "data.npy")

    def export_provenance(self, ident):
        """Bounded immutable parent metadata, not a mutable analysis registry."""
        pending_ids, objects, upstream = [ident], {}, {}
        while pending_ids:
            current = pending_ids.pop()
            if current in objects:
                continue
            need(len(objects) < 64, "Export provenance chain exceeds object budget", "BUDGET_EXCEEDED")
            metadata, directory = self.object(current)
            objects[current] = metadata
            if "upstream-metadata.json" in metadata["files_sha256"]:
                upstream[current] = read_json(directory / "upstream-metadata.json")
            for key in ("parent_object_id", "base_object_id", "source_object_id", "render_base_object_id"):
                target = metadata.get(key)
                if target is not None:
                    need(type(target) is str and OBJECT_ID.fullmatch(target), "Invalid provenance parent", "CORRUPT_OBJECT")
                    pending_ids.append(target)
            for target in metadata.get("object_ids", []):
                need(type(target) is str and OBJECT_ID.fullmatch(target), "Invalid comparison source", "CORRUPT_OBJECT")
                pending_ids.append(target)
        result = {"schema_version": 1, "root_object_id": ident, "objects": objects,
                  "upstream_capture_metadata": upstream,
                  "scope": "immutable workspace parents and imported original capture metadata; no live-source claim"}
        need(len(canonical(result)) <= 8 * 1024 * 1024, "Export provenance metadata exceeds byte budget", "BUDGET_EXCEEDED")
        return result

    def publish(self, metadata, directory):
        files = {p.name: sha_file(p) for p in directory.iterdir() if p.is_file()}
        metadata.update(schema_version=1, backend=BACKEND, computation="explicit external Python; DM not called",
                        dm_called=False, files_sha256=files,
                        software_provenance={"python": platform.python_version(), "numpy": np.__version__,
                                             "Pillow": PIL.__version__, "tifffile": tifffile.__version__,
                                             "worker_sha256": sha_file(Path(__file__))})
        metadata["manifest_path"] = str(directory / "object.json")
        if "preview.png" in files:
            metadata["image_path"] = str(directory / "preview.png")
        if "data.npy" in files:
            metadata["array_path"] = str(directory / "data.npy")
        write_new(directory / "object.json", canonical(metadata) + b"\n")
        return metadata

    def action(self, action, request, ident):
        directory = self.root / "objects" / ident
        directory.mkdir()
        metadata = {"object_id": ident, "kind": action, "created_utc": datetime.now(timezone.utc).isoformat(),
                    "request_id": request["request_id"]}
        if action == "open":
            path = absolute(request.get("source_path"), "source_path")
            identity = source_identity(path)
            pages = []
            with tifffile.TiffFile(path) as tiff:
                for index, page in enumerate(tiff.pages):
                    need(index < MAX_PAGES, "TIFF page metadata budget exceeded", "BUDGET_EXCEEDED")
                    pages.append(page_info(page, index))
            need(pages, "TIFF has no pages")
            check_source(identity)
            metadata.update(kind="tiff_source", source_identity=identity, page_count=len(pages), pages=pages,
                            frame_axis_role="unspecified_sequence", pixel_data_loaded=False,
                            source_hash_method="streaming complete file SHA-256; no whole-volume pixel decode")
        elif action == "frame":
            parent, _, context = self.resolved(request.get("object_id"))
            need(parent["kind"] == "tiff_source", "frame requires an opened TIFF source")
            index = request.get("frame_index")
            need(integer(index, 0, parent["page_count"] - 1), "frame_index must explicitly select an existing zero-based TIFF page")
            check_source(parent["source_identity"])
            with tifffile.TiffFile(parent["source_identity"]["path"]) as tiff:
                page = tiff.pages[index]
                need(page_info(page, index) == parent["pages"][index], "TIFF page metadata changed", "SOURCE_CHANGED")
                values = page.asarray()
            scalar_shape(values.shape, values.dtype)
            check_source(parent["source_identity"])
            save_array(directory, "data.npy", values)
            metadata.update(kind="frame", parent_object_id=request["object_id"], source_object_id=parent["object_id"],
                            frame_index=index, frame_axis_role="unspecified_sequence", shape_yx=list(values.shape),
                            dtype=str(values.dtype), axes=["y", "x"], source_identity=parent["source_identity"],
                            intensity_calibration_applied=False, intensity_semantics="raw pixel intensity",
                            calibration={"status": "unknown", "unit": None}, user_context=context)
        elif action == "import_capture":
            capture = absolute(request.get("source_path"), "source_path")
            need(capture.is_dir() and not capture.is_symlink(), "source_path must be a saved capture directory")
            capture = capture.resolve()
            info, manifest = read_json(capture / "input.json"), read_json(capture / "capture.json")
            pixel_path = capture / "input.npy"
            need(pixel_path.is_file() and not pixel_path.is_symlink() and pixel_path.stat().st_size <= MAX_ARRAY_BYTES + 65536,
                 "Captured NPY exceeds budget or is linked", "BUDGET_EXCEEDED")
            hashes = {name: sha_file(capture / name) for name in ("input.npy", "input.json", "capture.json")}
            need(info.get("schema_version") == manifest.get("schema_version") == 1 and manifest.get("state") == "captured" and
                 info.get("capture_id") == manifest.get("capture_id") and info.get("input_file") == "input.npy" and
                 hashes["input.npy"] == info.get("input_sha256") == manifest.get("input_sha256"),
                 "Incomplete or changed schema-1 capture")
            if "input_metadata_sha256" in manifest:
                need(hashlib.sha256(canonical(info)).hexdigest() == manifest["input_metadata_sha256"], "Capture metadata digest mismatch")
            native = (info.get("capture_mode") == "native_chunked_read" or
                      "digitalmicrograph-native" in str(manifest.get("capture_backend", "")) or
                      any(key in info for key in ("native_receipt", "native_receipt_sha256", "native_source_provenance",
                                                  "native_source_creation_record", "frame_ancestry", "scientific_context")) or
                      any(key in manifest for key in ("native_session", "native_request_id", "native_receipt_sha256", "frame_ancestry")))
            if native:
                # Existing independent validators, never Gatan or a runtime
                # fallback. Import requires no ASE dependency.
                sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
                from crystallography.capture import load_capture
                checked = load_capture(capture, "image")
                values = checked.array
                checked.assert_unchanged()
            else:
                values = load_array(capture / "input.npy")
            scalar_shape(values.shape, values.dtype)
            need(values.ndim == 2 and values.dtype.kind in "uif" and np.isfinite(values).all(), "Only finite scalar capture planes are supported")
            need(info.get("dtype") == str(values.dtype) and info.get("shape_yx") == list(values.shape) and
                 info.get("axes") == ["y", "x"] and info.get("array_order") == "C" and info.get("byte_order") == "little",
                 "Capture dtype, shape or axis metadata disagrees with NPY")
            save_array(directory, "data.npy", values)
            need(all(sha_file(capture / name) == digest for name, digest in hashes.items()), "Capture changed during import", "SOURCE_CHANGED")
            write_new(directory / "upstream-metadata.json", canonical({"input": info, "capture": manifest}) + b"\n")
            metadata.update(kind="frame", origin="explicit_imported_saved_capture", source_capture_path=str(capture),
                            source_capture_files_sha256=hashes, shape_yx=list(values.shape), dtype=str(values.dtype),
                            axes=["y", "x"], calibration=info.get("working_calibration_xy", info.get("calibration")),
                            upstream_backend=manifest.get("capture_backend"), intensity_calibration_applied=False,
                            intensity_semantics="raw imported values; original metadata preserved",
                            scientific_semantics=info.get("scientific_semantics"),
                            scientific_context=info.get("scientific_context"),
                            array_domain=(info.get("scientific_semantics") or {}).get("domain", "unspecified_image"),
                            capture_verification_mode="image" if native else "default_schema1_hashes_dtype_axes")
        elif action in ("view", "fft", "measure"):
            parent, _, context, values = self.scalar(request.get("object_id"))
            metadata.update(parent_object_id=request["object_id"], user_context=context or parent.get("user_context"),
                            source_object_id=parent["object_id"])
            if action == "measure":
                points = request.get("points")
                need(type(points) is list and len(points) == 2 and all(type(p) is list and len(p) == 2 and all(number(v) for v in p) for p in points),
                     "measure requires two explicit [x,y] pixel-center coordinates")
                need(all(0 <= p[0] <= values.shape[1] - 1 and 0 <= p[1] <= values.shape[0] - 1 for p in points), "Measurement points lie outside the scalar image")
                dx, dy = points[1][0] - points[0][0], points[1][1] - points[0][1]
                need(dx != 0 or dy != 0, "Distinct measurement points required")
                metadata.update(points=points, dx=dx, dy=dy, distance_pixels=math.hypot(dx, dy),
                                image_coordinate_angle_degrees=math.degrees(math.atan2(dy, dx)),
                                coordinate_system="scalar image pixel centers; x right, y down", physical_angle=False,
                                physical_distance=None, physical_unit=None,
                                limitation="pixel geometry only; unknown aspect/calibration never becomes a physical angle")
            else:
                rect = rectangle(request.get("rect"), values.shape)
                roi = cut(values, rect)
                metadata.update(source_rect_xyxy=rect, source_shape_yx=list(values.shape), rect_convention="half-open pixel edges [x0,y0,x1,y1]")
                if action == "fft":
                    window, subtract = request.get("window", "none"), request.get("subtract_mean", False)
                    need(window in ("none", "hann") and type(subtract) is bool, "FFT requires window none/hann and boolean subtract_mean")
                    work = roi.astype(np.float64)
                    removed = float(np.mean(work)) if subtract else 0.0
                    if subtract:
                        work -= removed
                    if window == "hann":
                        work *= np.hanning(work.shape[0])[:, None]
                        work *= np.hanning(work.shape[1])[None, :]
                    spectrum = np.fft.fftshift(np.fft.fft2(work))
                    need(np.isfinite(spectrum).all(), "External FFT produced nonfinite results")
                    save_array(directory, "data.npy", spectrum)
                    displayed = np.log1p(np.abs(spectrum))
                    settings = display_options({"max_size": request.get("max_size", 1024)}, [displayed])
                    image = render(displayed, settings, (settings["max_size"], settings["max_size"]))
                    metadata.update(dtype="complex128", shape_yx=list(spectrum.shape), axes=["fy", "fx"],
                                    algorithm="NumPy fft2 + fftshift; forward negative exponent, unnormalized",
                                    window=window, subtract_mean=subtract, removed_mean=removed,
                                    preprocessing_order="subtract raw ROI mean, then separable Hann if requested",
                                    frequency_unit="cycles/pixel", physical_frequency_unit=None,
                                    frequency_axes=[{"axis": axis, "numpy_axis": dim, "size": n, "step": 1.0 / n,
                                                     "dc_index": n // 2, "value_at_index_zero": -(n // 2) / n}
                                                    for dim, (axis, n) in enumerate(zip(("fy", "fx"), spectrum.shape))],
                                    display_representation="log1p(abs(complex128 spectrum))", display=settings)
                else:
                    save_array(directory, "data.npy", roi)
                    settings = display_options(request, [roi])
                    image = render(roi, settings, (settings["max_size"], settings["max_size"]))
                    metadata.update(dtype=str(roi.dtype), shape_yx=list(roi.shape), axes=["y", "x"], display=settings,
                                    array_domain=parent.get("array_domain", "spatial"),
                                    scientific_semantics=parent.get("scientific_semantics"),
                                    scientific_context=parent.get("scientific_context"))
                save_png(directory / "preview.png", image)
                metadata["panels"] = ([frequency_panel(ident, spectrum.shape, [0, 0, image.width, image.height])]
                                      if action == "fft" else
                                      [panel(parent["object_id"], rect, [0, 0, image.width, image.height],
                                             array_domain=parent.get("array_domain"))])
        elif action == "compare":
            ids = request.get("object_ids")
            need(type(ids) is list and 2 <= len(ids) <= 4 and len(set(ids)) == len(ids), "compare requires 2..4 distinct scalar object IDs")
            loaded = [self.scalar(ident) for ident in ids]
            shape = loaded[0][3].shape
            need(all(row[3].shape == shape for row in loaded), "Comparison requires equal source pixel shapes")
            grids = [(row[0].get("source_shape_yx", list(row[3].shape)),
                      row[0].get("source_rect_xyxy", [0, 0, row[3].shape[1], row[3].shape[0]])) for row in loaded]
            need(all(grid == grids[0] for grid in grids), "Comparison views require the same source shape and ROI")
            rect = rectangle(request.get("rect"), shape)
            rois = [cut(row[3], rect) for row in loaded]
            settings = display_options(request, rois)
            need(settings["max_size"] >= len(ids), "max_size is too small for comparison panels")
            images = [render(roi, settings, (settings["max_size"] // len(ids), settings["max_size"])) for roi in rois]
            composite = Image.new("L", (sum(image.width for image in images), max(image.height for image in images)))
            panels, left = [], 0
            for index, (ident, roi, image) in enumerate(zip(ids, rois, images)):
                composite.paste(image, (left, 0))
                panels.append(panel(ident, rect, [left, 0, left + image.width, image.height],
                                    array_domain=loaded[index][0].get("array_domain")))
                left += image.width
                save_array(directory, "data-{}.npy".format(index), roi)
            save_png(directory / "preview.png", composite)
            differences = []
            for index in range(1, len(rois)):
                delta = rois[index].astype(np.float64) - rois[0].astype(np.float64)
                differences.append({"left_object_id": ids[index], "right_object_id": ids[0],
                                    "operation": "external raw left-minus-right in float64", **stats(delta)})
            metadata.update(object_ids=ids, source_shape_yx=list(shape), source_rect_xyxy=rect, display=settings,
                            panels=panels, raw_statistics=[stats(roi) for roi in rois], raw_differences=differences,
                            comparison_scope="same half-open pixel ROI and shared display mapping; no registration or physical alignment inferred")
        elif action == "annotate":
            parent, _, context = self.resolved(request.get("object_id"))
            need(parent["kind"] in ("view", "compare", "fft", "annotate"), "annotate requires a rendered view/compare/FFT object")
            base_id = parent.get("render_base_object_id", parent["object_id"])
            render_base, base_directory = self.object(base_id)
            annotations = request.get("annotations")
            need(type(annotations) is list and len(annotations) <= 128, "annotations must be an explicit list of at most128 items")
            image = Image.open(base_directory / "preview.png").convert("RGB")
            draw = ImageDraw.Draw(image)
            validated = []
            for item in annotations:
                normalized = annotation(item, image.size, render_base.get("panels", []))
                validated.append(normalized)
                if normalized["status"] != "retracted":
                    color = "#00e060" if normalized["status"] == "user_confirmed" else "#ffba30"
                    coords = normalized["coordinates"]
                    if normalized["kind"] == "point":
                        x, y = coords
                        draw.ellipse([x - 3, y - 3, x + 3, y + 3], outline=color, width=2)
                    elif normalized["kind"] == "rectangle":
                        draw.rectangle(coords, outline=color, width=2)
                    else:
                        draw.text(coords, normalized["text"], fill=color)
            save_png(directory / "preview.png", image)
            metadata.update(parent_object_id=request["object_id"], render_base_object_id=base_id,
                            panels=render_base.get("panels", []), annotations=validated,
                            user_context=context or parent.get("user_context"),
                            revision_semantics="annotations replace the previous revision; empty list restores the original unannotated render",
                            scientific_data_changed=False)
        elif action == "context":
            previous, _ = self.object(request.get("object_id"))
            base, _, inherited = self.resolved(previous["object_id"])
            provided = request.get("metadata")
            allowed = {"reconstruction_type", "data_meaning", "frame_meaning", "xy_scale", "source_text", "value_unit", "frame_scale"}
            need(type(provided) is dict and set(provided) <= allowed, "Only explicit versioned user-context fields are allowed")
            combined = dict(inherited or {})
            for key, value in provided.items():
                if key == "frame_scale" and value is not None:
                    need(type(value) is dict and set(value) <= {"origin", "step", "unit", "source"} and
                         all(value.get(field) is None or number(value[field]) for field in ("origin", "step")) and
                         all(value.get(field) is None or type(value[field]) is str and len(value[field]) <= 2048 for field in ("unit", "source")),
                         "frame_scale is explicit user metadata only; provide finite origin/step and unit/source text")
                elif key == "xy_scale" and value is not None:
                    need(type(value) is dict and set(value) <= {"x", "y", "unit", "source", "source_text"} and
                         all(value.get(axis) is None or number(value[axis]) and value[axis] != 0 for axis in ("x", "y")) and
                         all(value.get(field) is None or type(value[field]) is str and len(value[field]) <= 2048 for field in ("unit", "source", "source_text")) and
                         any(type(value.get(field)) is str and bool(value[field].strip()) for field in ("source", "source_text")),
                         "xy_scale requires explicit finite signed scales/unit and source description; unknown fields remain null")
                else:
                    need(value is None or type(value) is str and len(value) <= 4096, "Context values must be user-provided text or null")
                combined[key] = value
            metadata.update(base_object_id=base["object_id"], parent_object_id=previous["object_id"], user_context=combined,
                            context_source="user_provided_not_independently_verified", calibration_applied=False,
                            revision=(previous.get("revision", 0) + 1), unknown_fields_are_not_inferred=True)
        elif action == "export":
            parent, _, context = self.resolved(request.get("object_id"))
            image_object = parent
            scientific = parent
            if parent["kind"] == "annotate":
                scientific, _ = self.object(parent["render_base_object_id"])
            context = context or image_object.get("user_context") or scientific.get("user_context")
            source_directory = self.root / "objects" / scientific["object_id"]
            names = [name for name in scientific["files_sha256"] if name.endswith(".npy")]
            need(names, "Export requires actual scientific arrays; a TIFF metadata handle/context-only record is not pixel data")
            provenance = self.export_provenance(request["object_id"])
            output = absolute(request.get("output_dir"), "output_dir")
            need(output.parent.is_dir() and not output.exists() and not output.is_symlink(), "output_dir must be a new explicit directory with an existing parent", "OUTPUT_EXISTS")
            resolved_parent = output.parent.resolve()
            need(not any(resolved_parent == self.root / name or self.root / name in resolved_parent.parents for name in ("objects", "requests")),
                 "Export cannot be written inside immutable object/request storage")
            output.mkdir()
            exported = {}
            for name in names:
                write_new(output / name, (source_directory / name).read_bytes())
                exported[name] = sha_file(output / name)
            if image_object.get("image_path"):
                write_new(output / "preview.png", Path(image_object["image_path"]).read_bytes())
                exported["preview.png"] = sha_file(output / "preview.png")
                export_display = image_object.get("display") or scientific.get("display")
            else:
                values = load_array(source_directory / names[0])
                export_display = display_options({}, [values])
                save_png(output / "preview.png", render(values, export_display, (1024, 1024)))
                exported["preview.png"] = sha_file(output / "preview.png")
            write_new(output / "provenance.json", canonical(provenance) + b"\n")
            exported["provenance.json"] = sha_file(output / "provenance.json")
            for upstream_id in provenance["upstream_capture_metadata"]:
                name = "upstream-{}.json".format(upstream_id)
                original = self.root / "objects" / upstream_id / "upstream-metadata.json"
                write_new(output / name, original.read_bytes())
                exported[name] = sha_file(output / name)
            export_manifest = {"schema_version": 1, "backend": BACKEND, "source_object_id": parent["object_id"],
                               "scientific_object": scientific, "display_object": image_object, "user_context": context,
                               "display_mapping": export_display,
                               "provenance_file": "provenance.json", "provenance_sha256": exported["provenance.json"],
                               "files_sha256": exported, "scientific_NPY_is_not_display_PNG": True, "dm_save_as_called": False}
            write_new(output / "manifest.json", canonical(export_manifest) + b"\n")
            metadata.update(parent_object_id=request["object_id"], output_dir=str(output.resolve()),
                            exported_files_sha256={**exported, "manifest.json": sha_file(output / "manifest.json")},
                            scientific_NPY_is_not_display_PNG=True, dm_save_as_called=False)
        else:
            raise WorkspaceError("INVALID_ARGUMENT", "Unknown action")
        return self.publish(metadata, directory)


def panel(object_id, source_rect, image_rect, array_domain=None):
    frequency = array_domain == "frequency"
    return {"domain": "source_array_indices" if frequency else "spatial_pixels", "source_object_id": object_id,
            "source_rect_xyxy": list(source_rect), "image_rect_xyxy": list(image_rect),
            **({"upstream_array_domain": "frequency", "spatial_roi_mapping_performed": False,
                "frequency_mapping_performed": False,
                "limitation": "indices of the imported scalar array only; original FFT and spatial coordinates remain upstream provenance"} if frequency else {}),
            "pixel_center_mapping": "source_x=x0+(image_x-panel_left+0.5)*source_width/panel_width-0.5; analogous y",
            "edge_mapping": "source_x=x0+(image_x-panel_left)*source_width/panel_width; analogous y"}


def frequency_panel(object_id, shape, image_rect):
    height, width = map(int, shape)
    return {"domain": "frequency", "source_object_id": object_id, "image_rect_xyxy": list(image_rect),
            "fft_shape_yx": [height, width], "dc_bin_xy": [width // 2, height // 2], "unit": "cycles/pixel",
            "bin_center_mapping": "fft_x=(image_x-panel_left+0.5)*fft_width/panel_width-0.5; analogous y",
            "frequency_coordinate_rule": "fx=(fft_x-floor(fft_width/2))/fft_width; fy=(fft_y-floor(fft_height/2))/fft_height",
            "spatial_roi_mapping": "not performed; the FFT input spatial ROI is separate operation provenance"}


def annotation(item, image_size, panels):
    need(type(item) is dict and set(item) <= {"kind", "coordinates", "text", "status", "note"}, "Unknown annotation field")
    kind, coords = item.get("kind"), item.get("coordinates")
    need(kind in ("point", "rectangle", "text") and type(coords) is list and len(coords) == (4 if kind == "rectangle" else 2) and
         all(number(value) for value in coords), "Annotation requires explicit finite rendered-image pixel coordinates")
    width, height = image_size
    need(0 <= coords[0] < width and 0 <= coords[1] < height, "Annotation starts outside the rendered image")
    if kind == "rectangle":
        need(coords[0] < coords[2] <= width and coords[1] < coords[3] <= height, "Invalid half-open annotation rectangle")
    status = item.get("status", "hypothesized")
    need(status in ("hypothesized", "user_confirmed", "retracted"), "Explicit annotation status required")
    text, note = item.get("text", ""), item.get("note", "")
    need(type(text) is str and len(text) <= 256 and type(note) is str and len(note) <= 2048, "Annotation text/note exceeds budget")
    if kind == "text":
        need(bool(text), "Text annotation requires text")
    mappings = []
    for current in panels:
        left, top, right, bottom = current["image_rect_xyxy"]
        contained = left <= coords[0] < right and top <= coords[1] < bottom
        if kind == "rectangle":
            contained = contained and coords[2] <= right and coords[3] <= bottom
        if contained:
            if current.get("domain") == "frequency":
                fft_height, fft_width = current["fft_shape_yx"]
                if kind == "rectangle":
                    mapped = [(coords[0] - left) * fft_width / (right-left) - 0.5,
                              (coords[1] - top) * fft_height / (bottom-top) - 0.5,
                              (coords[2] - left) * fft_width / (right-left) - 0.5,
                              (coords[3] - top) * fft_height / (bottom-top) - 0.5]
                    frequencies = [(mapped[0] - fft_width // 2) / fft_width,
                                   (mapped[1] - fft_height // 2) / fft_height,
                                   (mapped[2] - fft_width // 2) / fft_width,
                                   (mapped[3] - fft_height // 2) / fft_height]
                else:
                    mapped = [(coords[0] - left + 0.5) * fft_width / (right-left) - 0.5,
                              (coords[1] - top + 0.5) * fft_height / (bottom-top) - 0.5]
                    frequencies = [(mapped[0] - fft_width // 2) / fft_width,
                                   (mapped[1] - fft_height // 2) / fft_height]
                mappings.append({"source_object_id": current["source_object_id"], "domain": "frequency",
                                 "fft_bin_coordinates": mapped, "frequency_cycles_per_pixel": frequencies,
                                 "coordinate_convention": "FFT bin center indices; rectangles denote pixel-edge positions in this continuous index system",
                                 "frequency_coordinate_rule": current["frequency_coordinate_rule"],
                                 "physical_frequency_unit": None, "spatial_roi_mapping_performed": False})
                continue
            x0, y0, x1, y1 = current["source_rect_xyxy"]
            if kind == "rectangle":
                mapped = [x0 + (coords[0] - left) * (x1-x0)/(right-left), y0 + (coords[1] - top) * (y1-y0)/(bottom-top),
                          x0 + (coords[2] - left) * (x1-x0)/(right-left), y0 + (coords[3] - top) * (y1-y0)/(bottom-top)]
            else:
                mapped = [x0 + (coords[0] - left + 0.5) * (x1-x0)/(right-left) - 0.5,
                          y0 + (coords[1] - top + 0.5) * (y1-y0)/(bottom-top) - 0.5]
            if current.get("domain") == "source_array_indices":
                mappings.append({"source_object_id": current["source_object_id"], "domain": "source_array_indices",
                                 "array_index_coordinates": mapped, "spatial_roi_mapping_performed": False,
                                 "frequency_mapping_performed": False,
                                 "limitation": current["limitation"]})
            else:
                mappings.append({"source_object_id": current["source_object_id"], "domain": "spatial_pixels", "coordinates": mapped})
    return {"kind": kind, "coordinates": list(coords), "coordinate_space": "rendered_image_pixels; compare uses whole horizontal composite",
            "status": status, "text": text, "note": note, "source_mappings": mappings,
            "mapping_status": "one_source" if len(mappings) == 1 else "not_a_single_source_region"}


def _execute(request):
    need(type(request) is dict and type(request.get("action")) is str, "One JSON object with action is required")
    action = request["action"]
    need(action in FIELDS and set(request) <= FIELDS[action] | {"workspace", "action", "request_id"}, "Unknown action/argument")
    canonical(request)
    readonly = action in ("get", "result")
    ident = request.get("request_id")
    if not readonly:
        need(type(ident) is str and REQUEST_ID.fullmatch(ident), "Write actions require a pre-saved request_id")
    workspace = Workspace(request.get("workspace"), not readonly)
    if action == "get":
        metadata, _ = workspace.object(request.get("object_id"))
        return {"ok": True, "state": "completed", "backend": BACKEND, **metadata}
    if action == "result":
        ident = request.get("query_request_id")
        need(type(ident) is str and REQUEST_ID.fullmatch(ident), "query_request_id requires the original saved identity")
        path = workspace.root / "requests" / (ident + ".json")
        need(path.is_file(), "Original request not found", "REQUEST_NOT_FOUND")
        try:
            saved = read_json(path)
        except (OSError, ValueError, WorkspaceError):
            return pending(ident)
        if saved["state"] in ("completed", "failed"):
            need(saved.get("request_id") == ident and saved.get("response", {}).get("request_id") == ident,
                 "Stored request/response belongs to another original ID", "CORRUPT_OBJECT")
            if saved["state"] == "completed":
                workspace.object(saved["response"]["object_id"])
            return saved["response"]
        return pending(ident)
    normalized = {**request, "workspace": str(workspace.root)}
    fingerprint = hashlib.sha256(canonical(normalized)).hexdigest()
    journal = workspace.root / "requests" / (ident + ".json")
    try:
        stream = journal.open("x+", encoding="utf-8")
    except FileExistsError:
        try:
            previous = read_json(journal)
        except (OSError, ValueError, WorkspaceError):
            return pending(ident)
        need(previous.get("parameters_sha256") == fingerprint, "Same request_id has different action/parameters", "REQUEST_CONFLICT")
        if previous.get("state") == "completed":
            workspace.object(previous["response"]["object_id"])
            return previous["response"]
        if previous.get("state") == "failed":
            return previous["response"]
        return pending(ident)
    record = {"schema_version": 1, "request_id": ident, "state": "prepared", "parameters": normalized, "parameters_sha256": fingerprint}
    with stream:
        def update():
            stream.seek(0)
            stream.truncate()
            stream.write(canonical(record).decode("utf-8"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        update()
        try:
            metadata = workspace.action(action, normalized, uuid.uuid4().hex)
            response = {"ok": True, "state": "completed", "backend": BACKEND, "request_id": ident, **metadata}
            record.update(state="completed", response=response, object_manifest_sha256=sha_file(metadata["manifest_path"]))
        except Exception as error:
            response = failure(error, ident)
            record.update(state="failed", response=response)
        update()
        return response


def failure(error, request_id=None):
    return {"ok": False, "state": "failed", "backend": BACKEND, "request_id": request_id,
            "error": {"code": getattr(error, "code", "IMAGE_WORKSPACE_ERROR"), "message": str(error)}}


def pending(request_id):
    return {"ok": False, "state": "unknown", "backend": BACKEND, "request_id": request_id, "automatic_retry": False,
            "error": {"code": "INCOMPLETE_REQUEST", "message": "Original request is incomplete or unreadable; preserved without replay"}}


def execute(request):
    try:
        response = _execute(request)
        if response.get("ok"):
            return {"ok": True, "result": {key: value for key, value in response.items() if key != "ok"}}
        return response
    except Exception as error:
        return failure(error, request.get("request_id") if type(request) is dict else None)


def main():
    try:
        raw = sys.stdin.buffer.read(MAX_JSON_BYTES + 1)
        need(len(raw) <= MAX_JSON_BYTES, "JSON request exceeds byte budget")
        response = execute(strict_json(raw.decode("utf-8")))
    except Exception as error:
        response = failure(error)
    sys.stdout.write(json.dumps(response, ensure_ascii=True, allow_nan=False) + "\n")
    return 0 if response.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
