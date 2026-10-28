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
from PIL import Image, ImageDraw, ImageFont
import tifffile

if __package__:
    from .image_annotation_updates import plan_annotation_updates
    from . import image_calibration as calibration
    from . import image_numeric as numeric
else:
    from image_annotation_updates import plan_annotation_updates
    import image_calibration as calibration
    import image_numeric as numeric

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
    "view": {"object_id", "rect", "frequency_rect", "display_range", "gamma", "max_size", "interpolation", "representation", "spectrum_filter", "upscale", "spectrum_axes", "display_preset", "scale_bar"},
    "compare": {"object_ids", "rect", "display_range", "gamma", "max_size"},
    "fft": {"object_id", "rect", "window", "subtract_mean", "max_size"},
    "annotate": {"object_id", "annotations", "updates"}, "context": {"object_id", "metadata"},
    "measure": {"object_id", "points", "coordinate_space"}, "export": {"object_id", "output_dir"},
    "statistics": {"object_id", "rect", "frequency_rect", "component"},
    "profile": {"object_id", "points", "coordinate_space", "component", "sample_count", "line_width", "interpolation"},
    "centre": {"object_id", "center_xy", "coordinate_space", "source_text"},
    "remeasure": {"object_id", "measurement_object_id", "points", "source_text"},
    "calibrate": {"object_id", "scope", "xy_scale", "source_text", "calibration_object_id", "coordinate_domain", "declare_reciprocal"},
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


def display_options(request, values, inherited=None):
    # Omitted fields revise a saved view; explicit null range requests a fresh
    # auto-range. This never reapplies a display transform to scientific values.
    inherited = inherited if inherited is not None else {}
    gamma = request.get("gamma", inherited.get("gamma", 1.0))
    maximum = request.get("max_size", inherited.get("max_size", 1024))
    upscale = request.get("upscale", inherited.get("upscale", False))
    interpolation = request.get("interpolation", inherited.get("interpolation", "lanczos"))
    need(interpolation in ("nearest", "lanczos"), "interpolation must be nearest or lanczos for PNG display only")
    need(type(upscale) is bool, "upscale must be boolean and affects PNG only")
    need(number(gamma) and gamma > 0 and math.isfinite(1.0 / gamma), "gamma must be finite and positive")
    need(integer(maximum, 1, 1024), "max_size must be an integer in 1..1024")
    supplied = request.get("display_range")
    if "display_range" not in request and "display_range" in inherited:
        # A constant image can have an automatically calculated equal range;
        # that saved range is valid even though explicit equal limits reject.
        low, high = inherited["display_range"]
        need(number(low) and number(high) and low <= high,
             "Invalid inherited display range", "CORRUPT_OBJECT")
        range_source = "inherited_display"
    elif supplied is None:
        low = min(float(value.min()) for value in values)
        high = max(float(value.max()) for value in values)
        range_source = "shared_raw_minmax"
    else:
        need(type(supplied) is list and len(supplied) == 2 and all(number(v) for v in supplied) and supplied[0] < supplied[1],
             "display_range requires finite [minimum,maximum] with minimum<maximum")
        low, high = map(float, supplied)
        range_source = "explicit"
    return {"display_range": [low, high], "range_source": range_source,
            "gamma": float(gamma), "max_size": maximum, "upscale": upscale, "interpolation": interpolation, "constant_range": low == high,
            "display_only": True, "quantitative": False,
            "resampling": "Pillow {} display resizing; optional enlargement adds no measured detail; scientific array unchanged".format(interpolation.upper())}


def spectrum_display(values, representation):
    """Presentation of already saved complex values, never a second FFT."""
    expressions = {"log_amplitude": "log1p(abs(complex128 spectrum))",
                   "amplitude": "abs(complex128 spectrum)",
                   "power": "abs(complex128 spectrum)**2"}
    need(representation in expressions, "FFT representation must be log_amplitude, amplitude or power")
    with np.errstate(over="ignore", invalid="ignore"):
        shown = np.abs(values)
        if representation == "log_amplitude":
            shown = np.log1p(shown)
        elif representation == "power":
            shown = np.square(shown)
    need(np.isfinite(shown).all(), "FFT display representation exceeds finite range")
    return shown, expressions[representation]


def spectrum_filter_display(shown, specification):
    """Explicit presentation filter of amplitudes, never complex coefficients."""
    if specification is None:
        return shown, None
    need(type(specification) is dict and set(specification) == {"smooth_sigma_bins", "background_sigma_bins"},
         "spectrum_filter requires explicit smooth_sigma_bins and background_sigma_bins, or null")
    smooth, background = specification["smooth_sigma_bins"], specification["background_sigma_bins"]
    need(number(smooth) and number(background) and 0 <= smooth <= 4 and 1 <= background <= 64 and background > smooth,
         "spectrum_filter needs 0<=smooth<=4, 1<=background<=64 and background>smooth (FFT bins)")
    import scipy
    from scipy.ndimage import gaussian_filter
    work = gaussian_filter(shown, smooth, mode="reflect", truncate=4.0) if smooth else shown
    background_values = gaussian_filter(work, background, mode="reflect", truncate=4.0)
    shown = np.maximum(work-background_values, 0.0)
    need(np.isfinite(shown).all(), "Spectrum presentation filter produced nonfinite values")
    return shown, {"library": "SciPy", "version": scipy.__version__, "function": "scipy.ndimage.gaussian_filter",
                   "mode": "reflect", "truncate": 4.0, "sigma_unit": "FFT bins before display resizing",
                   "expression": "max(0, Gaussian(representation,smooth)-Gaussian(Gaussian(representation,smooth),background))",
                   "scientific_data_changed": False, "quantitative": False}


def render(values, settings, bound):
    low, high = settings["display_range"]
    scaled = np.zeros(values.shape, dtype=np.float64) if low == high else np.clip((values.astype(np.float64) - low) / (high - low), 0, 1)
    scaled = np.power(scaled, 1.0 / settings["gamma"])
    pixels = np.floor(scaled * 255 + 0.5).astype(np.uint8)
    image = Image.fromarray(pixels)
    sampling = Image.Resampling.NEAREST if settings.get("interpolation") == "nearest" else Image.Resampling.LANCZOS
    if settings.get("upscale"):
        scale = min(bound[0]/image.width, bound[1]/image.height)
        size = (max(1, min(bound[0], round(image.width*scale))), max(1, min(bound[1], round(image.height*scale))))
        image = image.resize(size, sampling)
    else:
        image.thumbnail(bound, sampling)
    return image


def stats(values):
    floating = values.astype(np.float64)
    result = {"sample_count": int(values.size), "dtype": str(values.dtype), "minimum": float(floating.min()),
              "maximum": float(floating.max()), "mean": float(np.mean(floating)), "stddev": float(np.std(floating))}
    need(all(number(v) for k, v in result.items() if k != "dtype"), "Statistics exceed finite binary64 range")
    return result


def spectrum_canvas(shown, settings, spectrum_id, xy_calibration=None):
    """Bounded optional figure axes; panel transforms include the margins."""
    axes = settings.get("spectrum_axes", False)
    need(type(axes) is bool, "spectrum_axes must be boolean")
    maximum = settings["max_size"]
    need(not axes or maximum >= 256, "Frequency-axis labels require max_size>=256")
    full_shape = shown.shape
    rect = rectangle(settings.get("frequency_rect"), full_shape)
    physical = calibration.frequency_axes(full_shape, xy_calibration)
    if not axes:
        plot = render(cut(shown, rect), settings, (maximum, maximum))
        info = frequency_panel(spectrum_id, full_shape, [0, 0, plot.width, plot.height], rect)
        info.update(physical_frequency_axes=physical, calibration_dependency=calibration.dependency(xy_calibration))
        return plot, info
    font = ImageFont.load_default(size=13)
    h, w = full_shape
    def tick_rows(start, stop, size, signed_scale):
        # A visible DC tick is placed at the actual original DC bin. The mean
        # endpoint bin of an even-size full spectrum is not DC; never label it
        # zero merely to make the layout symmetric.
        dc, last = size // 2, stop - 1
        middle = dc if start < dc < last else (start + last) / 2
        bins = sorted(set((start, middle, last)))
        values = [(index - dc) / size for index in bins]
        if physical:
            displayed = [value / signed_scale for value in values]
            precision = 4
            labels = [format(value, ".{}g".format(precision)) if value else "0" for value in displayed]
            # Narrow near-Nyquist windows can need more digits to distinguish
            # their ticks. This is presentation rounding only: values and
            # scientific axes remain full binary64 in metadata.
            while len(set(labels)) < len(labels) and precision < 16:
                precision += 1
                labels = [format(value, ".{}g".format(precision)) if value else "0" for value in displayed]
        else:
            displayed = values
            precision = int(math.ceil(math.log10(2*size))) + 1
            labels = [format(value, ".{}f".format(precision)).rstrip("0").rstrip(".") if value else "0" for value in values]
        return [{"bin_index": index, "cycles_per_pixel": value, "value": actual, "label": label}
                for index, value, actual, label in zip(bins, values, displayed, labels)]
    scale = calibration.active_scale(xy_calibration) or {"x": 1., "y": 1.}
    xticks = tick_rows(rect[0], rect[2], w, scale["x"])
    yticks = tick_rows(rect[1], rect[3], h, scale["y"])
    def text_width(label):
        box = font.getbbox(label)
        return box[2] - box[0]
    left = max(64, max(text_width(row["label"]) for row in yticks) + 12,
               int(math.ceil(text_width(xticks[0]["label"]) / 2)) + 2)
    right = max(20, int(math.ceil(text_width(xticks[-1]["label"]) / 2)) + 2)
    top = 44
    plot = render(cut(shown, rect), settings, (maximum-left-right, maximum-100))
    # Tiny spectra can retain their native display size when upscale is false;
    # reserve a minimum legend canvas so axes/title are not silently cropped.
    image = Image.new("RGB", (max(256, plot.width+left+right), max(192, plot.height+100)), "#171b22")
    image.paste(plot, (left, top))
    panel_info = frequency_panel(spectrum_id, full_shape, [left, top, left+plot.width, top+plot.height], rect)
    panel_info.update(physical_frequency_axes=physical, calibration_dependency=calibration.dependency(xy_calibration))
    draw = ImageDraw.Draw(image)
    title = "FFT | filtered display" if settings.get("spectrum_filter") else "FFT | " + settings["representation"]
    draw.text((left, 8), title, fill="white", font=font)
    frequency_unit = physical[0]["unit"] if physical else "cycles/pixel"
    settings["axis_labels_unit"] = frequency_unit
    settings["axis_calibration_dependency"] = calibration.dependency(xy_calibration)
    settings["axis_ticks"] = {"fx": xticks, "fy": yticks, "unit": frequency_unit,
                              "rounding": "physical ticks start at4 significant digits; increase only to distinguish adjacent ticks; scientific axes unchanged"}
    draw.text((8, 28), "fy", fill="white", font=font)
    draw.rectangle([left-1, top-1, left+plot.width, top+plot.height], outline="#a0a8b4")
    # Label original signed frequencies visible in this subregion. Cropping
    # never recentres DC or changes the frequency denominator/resolution.
    for row in xticks:
        fx = row["cycles_per_pixel"]
        x, _ = coordinate_transform([fx, 0], panel_info, False, inverse=True)
        draw.line([x, top+plot.height, x, top+plot.height+4], fill="white")
        row["image_coordinate"] = x
        draw.text((x, top+plot.height+7), row["label"], fill="white", font=font, anchor="mt")
    for row in yticks:
        fy = row["cycles_per_pixel"]
        _, y = coordinate_transform([0, fy], panel_info, False, inverse=True)
        draw.line([left-4, y, left, y], fill="white")
        row["image_coordinate"] = y
        draw.text((left-8, y), row["label"], fill="white", font=font, anchor="rm")
    draw.text((max(128, left+plot.width/2), top+plot.height+30), "fx/fy ({})".format(frequency_unit),
              fill="white", font=font, anchor="mt")
    return image, panel_info


def spatial_scale_bar(image, panel_info, record, enabled=True):
    """Draw a separately recorded display layer without changing geometry."""
    need(type(enabled) is bool, "scale_bar must be boolean")
    specification = calibration.scale_bar_spec(panel_info, record) if enabled else None
    if specification and specification.get("visible"):
        image = image.convert("RGB")
        draw = ImageDraw.Draw(image)
        line = specification["image_endpoints_xyxy"]
        draw.line(line, fill="black", width=5)
        draw.line(line, fill="white", width=3)
        label = "{:.5g} {}".format(specification["length"], specification["unit"])
        draw.text((line[0], line[1]-6), label, font=ImageFont.load_default(size=12),
                  anchor="lb", fill="white", stroke_width=1, stroke_fill="black")
    return image, specification


def translate_scale_bar(specification, left):
    if not specification or not specification.get("visible"):
        return specification
    x0, y0, x1, y1 = specification["image_endpoints_xyxy"]
    return {**specification, "image_endpoints_xyxy": [x0 + left, y0, x1 + left, y1],
            "coordinate_space": "rendered_image_pixels"}


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
        context, xy_record, calibration_review, visited = None, None, None, set()
        while True:
            need(ident not in visited and len(visited) < 32, "Object context cycle or depth exceeded", "CORRUPT_OBJECT")
            visited.add(ident)
            metadata, directory = self.object(ident)
            if xy_record is None:
                xy_record = metadata.get("xy_calibration")
            if calibration_review is None:
                calibration_review = metadata.get("calibration_review")
            if metadata["kind"] not in ("context", "calibration"):
                # Derived views/FFTs already carry effective user context.
                # None means absent; empty patches and explicit null fields
                # must not resurrect or discard an earlier interpretation.
                if context is None:
                    context = metadata.get("user_context")
                result = {**metadata, **({"xy_calibration": xy_record} if xy_record else {})}
                if xy_record and xy_record.get("domain_declaration"):
                    result["array_domain"] = "reciprocal"
                    result["domain_declaration"] = xy_record["domain_declaration"]
                if calibration_review:
                    result["calibration_review"] = calibration_review
                dependency = metadata.get("calibration_dependency")
                if dependency and xy_record and dependency["calibration_id"] != xy_record["calibration_id"]:
                    result["calibration_result_status"] = "stale_relative_to_selected_calibration; recompute before physical interpretation"
                return result, directory, context
            if context is None:
                context = metadata.get("user_context")
            ident = metadata["base_object_id"]

    def calibration_scope(self, ident, scope, coordinate_domain="real_space", allow_unknown_reciprocal=False):
        """Exact immutable source/frame identity, never filename/latest matching."""
        need(scope in ("image", "sequence"), "scope must explicitly be image or sequence")
        pending, seen, frames, sequences = [ident], set(), {}, {}
        while pending:
            current = pending.pop()
            if current in seen:
                continue
            need(len(seen) < 64, "Calibration source ancestry exceeds budget", "BUDGET_EXCEEDED")
            seen.add(current)
            metadata, directory = self.object(current)
            if metadata["kind"] == "tiff_source":
                sequences[current] = metadata
            elif metadata["kind"] == "frame":
                need(metadata.get("array_domain") not in ("frequency", "reciprocal") or coordinate_domain == "reciprocal_space",
                     "Real-space XY calibration cannot relabel an imported frequency-domain array; declare reciprocal_space and inverse-length units explicitly")
                need(metadata.get("array_domain") != "spatial" or coordinate_domain == "real_space",
                     "Reciprocal-space XY calibration cannot relabel a known spatial image; calibration revises scale, not the scientific array domain")
                if coordinate_domain == "reciprocal_space":
                    if metadata.get("array_domain") not in ("frequency", "reciprocal"):
                        need(allow_unknown_reciprocal and metadata.get("array_domain") in (None, "unspecified_image"),
                             "Unknown inputs require an explicit declare_reciprocal user statement; known spatial inputs cannot be reinterpreted")
                        self.require_unknown_reciprocal_frame(metadata, directory)
                frames[current] = metadata
            for key in ("base_object_id", "parent_object_id", "source_object_id", "render_base_object_id", "spectrum_object_id"):
                target = metadata.get(key)
                if target and target != current:
                    pending.append(target)
            pending.extend(metadata.get("object_ids", []))
        targets = sequences if scope == "sequence" else frames
        need(len(targets) == 1,
             "Calibration {} scope requires exactly one immutable {}; mixed-source or unresolved objects are refused".format(
                 scope, "TIFF sequence" if scope == "sequence" else "frame"))
        target_id, target = next(iter(targets.items()))
        return {"object_id": target_id, "kind": target["kind"],
                "source_identity": target.get("source_identity"),
                "frame_index": target.get("frame_index"),
                "source_capture_files_sha256": target.get("source_capture_files_sha256")}

    def require_unknown_reciprocal_frame(self, frame, directory):
        need(not frame.get("xy_calibration"), "Existing physical calibration cannot be replaced by a domain declaration")
        context = frame.get("user_context") or {}
        # Free-text data_meaning is retained context, not an established
        # coordinate domain. The explicit sourced declaration owns that choice;
        # reconstruction_type and typed native/scale evidence still forbid a
        # silent reinterpretation. Do not parse or delete the user's text.
        need(not context.get("reconstruction_type"),
             "Domain declaration cannot override an existing reconstruction-type statement")
        semantics = frame.get("scientific_semantics") or {}
        need(semantics.get("domain") not in ("spatial", "real_space"),
             "Known real-space native lineage cannot become reciprocal by calibration")
        upstream = directory / "upstream-metadata.json"
        if upstream.is_file():
            original = read_json(upstream)["input"]
            history = original.get("native_external_import") or {}
            need(history.get("coordinate_domain") != "real_space",
                 "Known native real-space creation lineage cannot become reciprocal by calibration")
            for axis in original.get("working_calibration_xy", []) or []:
                kind = calibration.unit_kind(axis.get("unit"))
                need(kind is None or kind[0] != "real_space",
                     "Known native real-space axis units cannot become reciprocal by calibration")

    def new_calibration(self, request, ident):
        previous, _, context = self.resolved(request.get("object_id"))
        old = previous.get("xy_calibration")
        if "calibration_object_id" in request:
            need(not any(key in request for key in ("scope", "xy_scale", "source_text", "coordinate_domain", "declare_reciprocal")),
                 "Attach an existing calibration OR provide a new statement; do not combine modes")
            reference, _ = self.object(request["calibration_object_id"])
            record = reference.get("xy_calibration")
            need(type(record) is dict and (reference["kind"] == "calibration" or
                 reference["kind"] == "frame" and record.get("source") == "native_dm_capture"),
                 "calibration_object_id must be an explicit calibration result or its validated native-capture frame")
            target = self.calibration_scope(request["object_id"], record["scope"], record.get("coordinate_domain", "real_space"),
                                            allow_unknown_reciprocal=bool(record.get("domain_declaration")))
            need(target == record["applies_to"], "Calibration belongs to a different immutable image/sequence", "CALIBRATION_SCOPE_MISMATCH")
            return previous, context, dict(record), {"attached_existing_calibration": True,
                                                     "calibration_object_id": request["calibration_object_id"]}
        scope = request.get("scope")
        need(not (old and old.get("domain_declaration")) or scope == "image",
             "A user reciprocal domain declaration remains image-scoped; other frames require their own explicit declaration")
        domain = request.get("coordinate_domain", old.get("coordinate_domain", "real_space") if old else "real_space")
        need(domain in ("real_space", "reciprocal_space"), "coordinate_domain must be real_space or reciprocal_space")
        need(old is None or domain == old.get("coordinate_domain", "real_space"),
             "Calibration revisions cannot change an established real-space/reciprocal-space domain; this is not an array reinterpretation interface")
        need(previous["kind"] not in ("fft", "fft_view") or domain == "real_space",
             "Saved external FFT calibration uses its source real-space pixel scale, never a reciprocal scale on the complex array")
        declared = request.get("declare_reciprocal", False)
        need(type(declared) is bool, "declare_reciprocal must be an explicit boolean")
        if declared:
            need(old is None and domain == "reciprocal_space" and scope == "image" and request.get("xy_scale") is not None,
                 "A reciprocal declaration requires a previously unknown scalar image, inverse-length XY scale and image scope")
            need(not (context or {}).get("reconstruction_type"),
                 "Domain declaration cannot silently replace an existing user reconstruction-type statement")
        target = self.calibration_scope(request["object_id"], scope, domain,
                                        allow_unknown_reciprocal=declared or bool(old and old.get("domain_declaration")))
        source = request.get("source_text")
        need(type(source) is str and 1 <= len(source) <= 4000 and source.strip(),
             "A new or withdrawn calibration requires the actual user source_text")
        need("xy_scale" in request, "xy_scale must be supplied; explicit null withdraws a calibration")
        scale = calibration.validated_scale(request["xy_scale"], domain) if request["xy_scale"] is not None else None
        if scale is None:
            need(old is not None and old["scope"] == scope and old["applies_to"] == target,
                 "Withdrawal must reference an existing calibration with the same explicit scope")
        same_scope = old is not None and old["scope"] == scope and old["applies_to"] == target
        record = {"calibration_id": ident, "revision": old["revision"] + 1 if same_scope else 1,
                  "previous_calibration_id": old["calibration_id"] if same_scope else None,
                  "status": "active" if scale else "withdrawn", "scope": scope, "applies_to": target,
                  "xy_scale": scale, "source_text": source,
                  "source": "user_statement_not_independently_verified",
                  "uncertainty_status": ("scale uncertainty supplied; measurement uncertainty remains unknown without localization/covariance"
                                         if scale and any(scale["uncertainty_" + a] is not None for a in ("x", "y")) else "unknown"),
                  "coordinate_domain": domain, "real_space_only": domain == "real_space", "original_file_metadata_modified": False,
                  "value_unit_or_frame_depth_inferred": False}
        if same_scope:
            record.update(calibration.revised_reciprocal_origin(old, scale))
            if old.get("domain_declaration"):
                record["domain_declaration"] = old["domain_declaration"]
        if declared:
            record["domain_declaration"] = {"coordinate_domain": "reciprocal_space", "source": "user_statement_not_independently_verified",
                                            "source_text": source, "declared_for": target, "declaration_object_id": ident,
                                            "scope": "previously unknown scalar image only; source metadata/pixels unchanged"}
        return previous, context, record, {"attached_existing_calibration": False}

    def scalar(self, ident):
        metadata, directory, context = self.resolved(ident)
        need(metadata["kind"] in ("frame", "view"), "Operation requires a scalar frame/view object, not a TIFF source, composite or complex spectrum")
        return metadata, directory, context, load_array(directory / "data.npy")

    def measurement_operand(self, ident):
        """Resolve a selected revision without resurrecting an old measure's scale."""
        parent, directory, context = self.resolved(ident)
        selected_record = parent.get("xy_calibration")
        visited = set()
        while parent["kind"] in ("measure", "annotate"):
            need(parent["object_id"] not in visited and len(visited) < 32,
                 "Measurement ancestry cycle or depth exceeded", "CORRUPT_OBJECT")
            visited.add(parent["object_id"])
            target = parent["parent_object_id"] if parent["kind"] == "measure" else parent["render_base_object_id"]
            parent, directory, older_context = self.resolved(target)
            if context is None:
                context = older_context
        if selected_record is not None:
            parent = {**parent, "xy_calibration": selected_record}
            if selected_record.get("domain_declaration"):
                parent["array_domain"] = "reciprocal"
        return parent, directory, context

    def measurement_grid(self, ident):
        parent, directory, _ = self.measurement_operand(ident)
        spectral = parent["kind"] in ("fft", "fft_view")
        need(parent["kind"] in ("frame", "view", "fft", "fft_view"),
             "Measurement requires one scalar frame/view or saved external FFT")
        values = load_array(directory / "data.npy", allow_complex=spectral)
        if spectral:
            source = parent.get("spectrum_object_id", parent["object_id"])
            bounds = None
        else:
            current = spatial_panel(parent, [0, 0, values.shape[1], values.shape[0]], [0, 0, values.shape[1], values.shape[0]])
            source, bounds = current["source_object_id"], current["source_rect_xyxy"]
        reciprocal = not spectral and parent.get("array_domain") in ("frequency", "reciprocal")
        return {"source_grid_object_id": source, "shape_yx": list(values.shape), "dtype": str(values.dtype),
                "array_sha256": sha_file(directory / "data.npy"), "source_rect_xyxy": bounds,
                "coordinate_space": "frequency_cycles_per_pixel" if spectral else "source_array_indices" if reciprocal else "source_pixels"}

    def measurement_grid_identity(self, ident):
        """Shared exact scientific grid contract for revision-aware consumers."""
        return self.measurement_grid(ident)

    def new_centre(self, request, ident):
        parent, directory, context = self.measurement_operand(request.get("object_id"))
        need(parent["kind"] in ("frame", "view") and parent.get("array_domain") in ("frequency", "reciprocal"),
             "Centre correction is only for an established reciprocal scalar array; saved external FFT mathematical DC is fixed")
        need((parent.get("scientific_semantics") or {}).get("status") != "tracked_fourier" and
             (parent.get("scientific_context") or {}).get("status") != "tracked_fourier",
             "A tracked native Fourier scalar also has fixed mathematical DC; it is not a movable diffraction centre")
        need(request.get("coordinate_space") == "source_array_indices",
             "Centre must use original source_array_indices, never PNG or FFT coordinates")
        old = parent.get("xy_calibration")
        need(type(old) is dict and old.get("coordinate_domain") == "reciprocal_space" and old.get("scope") == "image",
             "Centre correction requires an existing image-scoped reciprocal calibration; unknown input must be declared first")
        text = request.get("source_text")
        need(type(text) is str and 1 <= len(text) <= 4000 and text.strip(),
             "Centre correction requires the actual user source_text")
        values = load_array(directory / "data.npy")
        grid = self.measurement_grid(request["object_id"])
        bounds = grid["source_rect_xyxy"]
        centre = request.get("center_xy")
        need(type(centre) is list and len(centre) == 2 and all(number(v) for v in centre) and
             bounds[0] <= centre[0] <= bounds[2]-1 and bounds[1] <= centre[1] <= bounds[3]-1,
             "Centre must lie within the selected original array-index extent; no clipping")
        record = calibration.revised_centre(old, centre, ident, text)
        return parent, context, record, {"attached_existing_calibration": False,
                                        "centre_revision": {"center_xy": centre, "coordinate_space": "source_array_indices",
                                                            "scientific_grid_identity": grid, "source_text": text}}

    def committed_measurement(self, ident, depth=0):
        """Bind saved points to their exact original request, including revisions."""
        need(depth < 16, "Measurement revision depth exceeded", "BUDGET_EXCEEDED")
        previous, previous_directory = self.object(ident)
        need(previous.get("kind") == "measure", "measurement_object_id must identify a committed image_measure result")
        journal = read_json(self.root / "requests" / (previous["request_id"] + ".json"))
        parameters = journal.get("parameters")
        need(type(parameters) is dict and parameters.get("action") in ("measure", "remeasure") and
             set(parameters) <= FIELDS[parameters["action"]] | {"workspace", "action", "request_id"} and
             parameters.get("workspace") == str(self.root) and parameters.get("request_id") == previous["request_id"] and
             parameters.get("object_id") == previous.get("parent_object_id") and
             journal.get("parameters_sha256") == hashlib.sha256(canonical(parameters)).hexdigest(),
             "Saved measurement original request identity or parameters changed", "CORRUPT_OBJECT")
        if parameters["action"] == "measure":
            need(parameters.get("points") == previous.get("points") and
                 parameters.get("coordinate_space", previous.get("coordinate_space")) == previous.get("coordinate_space"),
                 "Saved measurement points/coordinate space contradict its original request", "CORRUPT_OBJECT")
        else:
            effective, revision = self.remeasurement(parameters, depth + 1)
            need(previous.get("points") == effective["points"] and previous.get("coordinate_space") == effective["coordinate_space"] and
                 previous.get("remeasurement") == revision,
                 "Saved remeasurement differs from its original points/centre revision", "CORRUPT_OBJECT")
        grid = self.measurement_grid(parameters["object_id"])
        need("scientific_grid_identity" not in previous or previous["scientific_grid_identity"] == grid,
             "Saved measurement scientific grid differs from its original input", "CORRUPT_OBJECT")
        return previous, previous_directory

    def remeasurement(self, request, depth=0):
        previous, previous_directory = self.committed_measurement(request.get("measurement_object_id"), depth)
        before = self.measurement_grid(previous["parent_object_id"])
        current = self.measurement_grid(request.get("object_id"))
        need(before == current, "Saved points belong to a different source/frame/ROI/FFT grid", "MEASUREMENT_SCOPE_MISMATCH")
        parent, _, _ = self.measurement_operand(request["object_id"])
        current_record = parent.get("xy_calibration")
        old_record = previous.get("xy_calibration")
        explicit = "points" in request
        text = request.get("source_text")
        if explicit:
            need(type(text) is str and 1 <= len(text) <= 4000 and text.strip(),
                 "Explicit corrected points require actual user source_text")
            points = request["points"]
        else:
            need(text is None or type(text) is str and len(text) <= 4000,
                 "source_text must be bounded text")
            points = [list(p) for p in previous["points"]]
        dc_index = previous.get("dc_reference_point_index")
        old_dc = old_record.get("dc_index_xy") if old_record else None
        new_dc = current_record.get("dc_index_xy") if current_record else None
        move_dc = not explicit and current["coordinate_space"] == "source_array_indices" and type(dc_index) is int and dc_index in (0, 1)
        if move_dc:
            need(type(old_dc) is list and previous["points"][dc_index] == old_dc and type(new_dc) is list,
                 "Original/current explicit DC identity required to update a centre-referenced measurement")
            points[dc_index] = list(new_dc)
        revision = {"previous_measurement_object_id": previous["object_id"],
                    "previous_manifest_sha256": sha_file(previous_directory / "object.json"),
                    "previous_parent_object_id": previous["parent_object_id"], "previous_points": previous["points"],
                    "reused_saved_points": not explicit, "dc_endpoint_updated": bool(move_dc and old_dc != new_dc),
                    "previous_dc_reference_point_index": dc_index, "previous_dc_index_xy": old_dc,
                    "current_dc_index_xy": new_dc, "source_text": text, "scientific_grid_identity": current}
        effective = {"object_id": request["object_id"], "points": points, "coordinate_space": current["coordinate_space"],
                     "request_id": request["request_id"]}
        return effective, revision

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
            for key in ("parent_object_id", "base_object_id", "source_object_id", "render_base_object_id", "calibration_object_id"):
                target = metadata.get(key)
                if target is not None:
                    need(type(target) is str and OBJECT_ID.fullmatch(target), "Invalid provenance parent", "CORRUPT_OBJECT")
                    pending_ids.append(target)
            for target in metadata.get("object_ids", []):
                need(type(target) is str and OBJECT_ID.fullmatch(target), "Invalid comparison source", "CORRUPT_OBJECT")
                pending_ids.append(target)
            record = metadata.get("xy_calibration")
            if record and record["calibration_id"] != current:
                pending_ids.append(record["calibration_id"])
            if record and record.get("previous_calibration_id"):
                pending_ids.append(record["previous_calibration_id"])
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
                                             "worker_sha256": sha_file(Path(__file__)),
                                             "helper_modules_sha256": {name: sha_file(Path(__file__).with_name(name)) for name in
                                                                       ("image_annotation_updates.py", "image_calibration.py", "image_numeric.py")}})
        metadata["manifest_path"] = str(directory / "object.json")
        if "preview.png" in files:
            metadata["image_path"] = str(directory / "preview.png")
        if "data.npy" in files:
            metadata["array_path"] = str(directory / "data.npy")
        write_new(directory / "object.json", canonical(metadata) + b"\n")
        return metadata

    def action(self, action, request, ident):
        remeasurement = None
        if action == "remeasure":
            request, remeasurement = self.remeasurement(request)
            action = "measure"
        directory = self.root / "objects" / ident
        directory.mkdir()
        metadata = {"object_id": ident, "kind": action, "created_utc": datetime.now(timezone.utc).isoformat(),
                    "request_id": request["request_id"]}
        if remeasurement is not None:
            metadata["remeasurement"] = remeasurement
        if "object_id" in request:
            inherited, _, _ = self.resolved(request["object_id"])
            if inherited.get("xy_calibration"):
                metadata["xy_calibration"] = inherited["xy_calibration"]
            if inherited.get("calibration_review"):
                metadata["calibration_review"] = inherited["calibration_review"]
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
            if native:
                target = {"object_id": ident, "kind": "frame", "source_identity": None,
                          "frame_index": None, "source_capture_files_sha256": hashes}
                record, admission = calibration.native_record(info, checked.provenance, ident, target)
                metadata["calibration_admission"] = admission
                if record:
                    metadata["xy_calibration"] = record
                    metadata["array_domain"] = "reciprocal" if record["coordinate_domain"] == "reciprocal_space" else "spatial"
            else:
                metadata["calibration_admission"] = {"status": "pixel_only", "source": "unknown",
                    "reason": "generic schema-1 metadata is preserved but is not validated native READ calibration; use an explicit user calibration"}
        elif action in ("calibrate", "centre"):
            previous, context, record, extra = (self.new_centre(request, ident) if action == "centre" else self.new_calibration(request, ident))
            old = previous.get("xy_calibration")
            changed = old is not None and old["calibration_id"] != record["calibration_id"]
            metadata.update(kind="calibration", parent_object_id=request["object_id"], base_object_id=previous["object_id"],
                            user_context=context, xy_calibration=record, **extra,
                            scientific_data_changed=False, raw_metadata_modified=False,
                            calibration_review={"previous_calibration_id": old["calibration_id"] if old else None,
                                                "current_calibration_id": record["calibration_id"],
                                                "physical_measurements": "stale; recompute using this revision" if changed else "record dependency when measured",
                                                "candidate_interpretations": "review_required_after_calibration_change" if changed else "not automatically confirmed",
                                                "old_measurement_object_id": previous["object_id"] if changed and previous["kind"] == "measure" else None,
                                                "pixel_anchors_changed": action == "centre",
                                                "pixel_anchor_policy": ("new centre reference; saved peak anchors and old measurements remain unchanged; remeasure the explicit DC endpoint" if action == "centre" else "scale-only revision preserves saved point coordinates"),
                                                "old_exports_immutable": True},
                            next_step="image_preview on this wrapper to redraw physical scale/axes; image_measure to calculate geometry with the selected record")
        elif action in ("statistics", "profile"):
            metadata.update(parent_object_id=request["object_id"])
            if action == "statistics":
                metadata.update(numeric.statistics(self, request))
                write_new(directory / "statistics.json", canonical(metadata["statistics"])+b"\n")
            else:
                result, values = numeric.profile(self, request)
                metadata.update(result)
                save_array(directory, "profile.npy", values)
                import csv
                with (directory / "profile.csv").open("x", encoding="utf-8", newline="") as stream:
                    writer = csv.writer(stream)
                    writer.writerow(["sample", "x", "y", "array_x", "array_y", "distance", "distance_unit", "physical_distance", "physical_distance_unit", "value", "component", "dtype"])
                    samples = result["samples"]
                    for i in range(len(values)):
                        writer.writerow([i, *samples["coordinates_xy"][i], *samples["indices_xy"][i], samples["distance"][i], result["distance_unit"],
                                         samples["physical_distance"][i] if samples["physical_distance"] is not None else "", result["physical_distance_unit"] or "", values[i].item(), result["component"], result["dtype"]])
                    stream.flush()
                    os.fsync(stream.fileno())
        elif action in ("view", "fft", "measure"):
            spectral_view = False
            inherited_annotations = []
            if action == "view" or action == "measure":
                parent, parent_directory, context = (self.measurement_operand(request.get("object_id")) if action == "measure" else self.resolved(request.get("object_id")))
                inherited_annotations = parent.get("annotations", [])
                if parent["kind"] == "annotate":
                    parent, parent_directory = self.object(parent["render_base_object_id"])
                if parent["kind"] == "compare":
                    need(action == "view", "Measure one explicit comparison input, not an ambiguous composite")
                    return self.revise_comparison(parent, parent_directory, context, request, metadata, directory,
                                                  inherited_annotations)
                spectral_view = parent["kind"] in ("fft", "fft_view")
                need(not spectral_view or "scale_bar" not in request,
                     "A real-space scale_bar cannot be drawn on a frequency spectrum; use spectrum_axes")
                need(parent["kind"] in ("frame", "view", "fft", "fft_view"),
                     "preview requires a frame/view, comparison, annotated view or FFT")
                values = load_array(parent_directory / "data.npy", allow_complex=spectral_view)
                need(spectral_view or "representation" not in request,
                     "representation is only valid for a saved complex FFT")
                need(spectral_view or "spectrum_filter" not in request,
                     "spectrum_filter is only valid for a saved complex FFT display")
                need(spectral_view or "spectrum_axes" not in request,
                     "spectrum_axes is only valid for a saved complex FFT display")
                need(spectral_view or "display_preset" not in request,
                     "fft_detail display_preset requires a saved complex FFT")
                need(spectral_view or "frequency_rect" not in request,
                     "frequency_rect requires a saved complex FFT; spatial ROI uses rect")
            else:
                parent, _, context, values = self.scalar(request.get("object_id"))
            metadata.update(parent_object_id=request["object_id"], user_context=context,
                            source_object_id=parent["object_id"])
            record = metadata.get("xy_calibration")
            if action == "measure":
                metadata["scientific_grid_identity"] = self.measurement_grid(request["object_id"])
                points = request.get("points")
                need(type(points) is list and len(points) == 2 and all(type(p) is list and len(p) == 2 and all(number(v) for v in p) for p in points),
                     "measure requires two explicit [x,y] coordinates")
                reciprocal_array = not spectral_view and parent.get("array_domain") in ("frequency", "reciprocal")
                expected_space = "frequency_cycles_per_pixel" if spectral_view else "source_array_indices" if reciprocal_array else "source_pixels"
                space = request.get("coordinate_space", expected_space)
                need(space == expected_space,
                     "coordinate_space must match the actual spatial image, reciprocal scalar-array indices or saved complex FFT")
                if spectral_view:
                    h, w = values.shape
                    need(all(-(w//2)/w <= p[0] <= (w-1-w//2)/w and
                             -(h//2)/h <= p[1] <= (h-1-h//2)/h for p in points),
                         "Frequency points must lie on the original saved fftshift frequency extent")
                    bounds = None
                else:
                    current = spatial_panel(parent, [0, 0, values.shape[1], values.shape[0]], [0, 0, values.shape[1], values.shape[0]])
                    bounds = current["source_rect_xyxy"]
                    need(all(bounds[0] <= p[0] <= bounds[2]-1 and bounds[1] <= p[1] <= bounds[3]-1 for p in points),
                         "Measurement points lie outside the selected source-pixel extent; no clipping")
                dx, dy = points[1][0] - points[0][0], points[1][1] - points[0][1]
                need((dx != 0 or dy != 0) or spectral_view and points[0] == [0, 0],
                     "Distinct measurement points required, except explicit FFT DC inspection")
                measured = calibration.geometry(dx, dy, record, frequency=spectral_view)
                metadata.update(points=points, dx=dx, dy=dy, coordinate_space=space,
                                coordinate_system="original fftshift cycles/pixel; no2pi" if spectral_view else "source array centres; x right,y down; current calibrated domain is explicit",
                                source_rect_xyxy=bounds,
                                measurement_domain=("reciprocal_space" if measured.get("physical_frequency_magnitude") is not None else
                                                    "real_space" if measured.get("physical_distance") is not None else "pixel_geometry"), **measured)
                if spectral_view:
                    magnitude = math.hypot(dx, dy)
                    metadata.update(frequency_distance_cycles_per_pixel=magnitude,
                                    pixel_period=1. / magnitude if magnitude else None,
                                    zero_frequency_reason="DC has no finite reciprocal period" if not magnitude else None,
                                    image_coordinate_angle_degrees=math.degrees(math.atan2(dy, dx)) if magnitude else None,
                                    d_spacing=measured.get("period") if [0, 0] in points else None,
                                    d_spacing_unit=measured.get("period_unit") if [0, 0] in points else None,
                                    dc_reference_point_index=points.index([0, 0]) if [0, 0] in points else None,
                                    reciprocal_interpretation="geometric period of frequency difference; d_spacing only for a vector referenced to explicit DC, not an hkl/phase identification")
                else:
                    metadata.update(distance_pixels=math.hypot(dx, dy),
                                    image_coordinate_angle_degrees=math.degrees(math.atan2(dy, dx)))
                    physical = calibration.physical_points(points, record)
                    metadata.update(physical_points_xy=physical,
                                    physical_points_unit=record["xy_scale"]["unit"] if physical else None)
                    if reciprocal_array:
                        # A frequency difference is a geometric period; d-spacing
                        # requires one endpoint at the actual calibrated DC.
                        # A recorded centre is a pixel/index identity even when
                        # its physical scale is withdrawn. Keep the endpoint
                        # role for later remeasurement, without a physical claim.
                        at_dc = record is not None and record.get("dc_index_xy") in points
                        metadata.update(d_spacing=measured.get("period") if at_dc else None,
                                        d_spacing_unit=measured.get("period_unit") if at_dc else None,
                                        dc_reference_point_index=points.index(record["dc_index_xy"]) if at_dc else None,
                                        reciprocal_interpretation="calibrated reciprocal-array geometry; d_spacing only when an endpoint is explicit mathematical/calibrated DC; not an hkl or phase assertion")
            elif spectral_view:
                need(values.dtype == np.dtype("complex128"), "FFT view requires the saved complex128 spectrum")
                need(request.get("rect") is None,
                     "FFT display selection uses frequency_rect in original FFT bins; rect selects a spatial ROI before FFT")
                old_display = dict(parent.get("display") or {})
                selection = request.get("frequency_rect", old_display.get("frequency_rect"))
                selected_rect = rectangle(selection, values.shape)
                recipe = dict(request)
                detail_preset = "display_preset" in request
                if detail_preset:
                    need(request["display_preset"] == "fft_detail", "Only the explicit fft_detail display preset is supported")
                    # A reusable starting point, not a sample-specific denoiser.
                    # Explicit caller parameters always override the recipe.
                    recipe = {"representation": "log_amplitude", "spectrum_filter": None,
                              "spectrum_axes": False, "upscale": True, "max_size": 512, "gamma": 0.8, **request}
                previous_mode = old_display.get("representation", "log_amplitude")
                mode = recipe.get("representation", previous_mode)
                shown, expression = spectrum_display(values, mode)
                filter_spec = recipe.get("spectrum_filter", old_display.get("spectrum_filter"))
                shown, filter_provenance = spectrum_filter_display(shown, filter_spec)
                if mode != previous_mode or filter_spec != old_display.get("spectrum_filter"):
                    # Amplitude, power and log amplitude have different units;
                    # preserve gamma/size, but never inherit their old limits.
                    old_display.pop("display_range", None)
                percentile_range = detail_preset and "display_range" not in request
                if percentile_range:
                    limits = np.percentile(shown, [5, 99.8]).tolist()
                    recipe["display_range"] = limits if limits[0] < limits[1] else None
                settings = display_options(recipe, [shown], old_display)
                if percentile_range:
                    if limits[0] < limits[1]:
                        settings.update(range_source="percentile", range_percentiles=[5, 99.8])
                    else:
                        settings.update(range_source="percentile_fallback_raw_minmax", attempted_range_percentiles=[5, 99.8],
                                        range_fallback_reason="percentile limits are equal")
                elif "display_range" not in request and mode == previous_mode and filter_spec == old_display.get("spectrum_filter"):
                    if "range_percentiles" in old_display:
                        settings["range_percentiles"] = old_display["range_percentiles"]
                settings["display_preset"] = "fft_detail" if detail_preset else old_display.get("display_preset")
                settings["display_preset_revision"] = 2 if detail_preset else old_display.get("display_preset_revision")
                settings["representation"] = mode
                settings.update(spectrum_filter=filter_spec, filter_provenance=filter_provenance)
                settings["spectrum_axes"] = recipe.get("spectrum_axes", old_display.get("spectrum_axes", False))
                settings["frequency_rect"] = selected_rect
                settings["frequency_rect_convention"] = "absolute half-open bin edges in original fftshift grid; omission inherits, null restores full spectrum"
                spectrum_id = parent.get("spectrum_object_id", parent["object_id"])
                image, spectrum_panel = spectrum_canvas(shown, settings, spectrum_id, record)
                save_array(directory, "data.npy", values)
                metadata.update(kind="fft_view", source_object_id=spectrum_id, spectrum_object_id=spectrum_id,
                                dtype="complex128", shape_yx=list(values.shape), axes=["fy", "fx"], array_domain="frequency",
                                frequency_unit=parent["frequency_unit"],
                                physical_frequency_unit=("cycles/" + record["xy_scale"]["unit"]) if calibration.active_scale(record) else None,
                                physical_frequency_axes=calibration.frequency_axes(values.shape, record),
                                frequency_axes=parent["frequency_axes"], display_representation=expression, display=settings,
                                panels=[spectrum_panel],
                                fft_recomputed=False, scientific_data_changed=False,
                                rendering_scope="saved external complex FFT; frequency selection and amplitude/power/log are display-only; NPY retains the full unchanged complex spectrum")
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
                    displayed, expression = spectrum_display(spectrum, "log_amplitude")
                    settings = display_options({"max_size": request.get("max_size", 1024)}, [displayed])
                    settings["representation"] = "log_amplitude"
                    image = render(displayed, settings, (settings["max_size"], settings["max_size"]))
                    metadata.update(dtype="complex128", shape_yx=list(spectrum.shape), axes=["fy", "fx"],
                                    algorithm="NumPy fft2 + fftshift; forward negative exponent, unnormalized",
                                    window=window, subtract_mean=subtract, removed_mean=removed,
                                    preprocessing_order="subtract raw ROI mean, then separable Hann if requested",
                                    frequency_unit="cycles/pixel", physical_frequency_unit=None,
                                    frequency_axes=[{"axis": axis, "numpy_axis": dim, "size": n, "step": 1.0 / n,
                                                     "dc_index": n // 2, "value_at_index_zero": -(n // 2) / n}
                                                    for dim, (axis, n) in enumerate(zip(("fy", "fx"), spectrum.shape))],
                                    display_representation=expression, display=settings, array_domain="frequency")
                    metadata.update(physical_frequency_unit=("cycles/" + record["xy_scale"]["unit"]) if calibration.active_scale(record) else None,
                                    physical_frequency_axes=calibration.frequency_axes(spectrum.shape, record))
                else:
                    save_array(directory, "data.npy", roi)
                    settings = display_options(request, [roi], parent.get("display"))
                    image = render(roi, settings, (settings["max_size"], settings["max_size"]))
                    metadata.update(dtype=str(roi.dtype), shape_yx=list(roi.shape), axes=["y", "x"], display=settings,
                                    array_domain=parent.get("array_domain", "spatial"),
                                    scientific_semantics=parent.get("scientific_semantics"),
                                    scientific_context=parent.get("scientific_context"))
                metadata["panels"] = ([frequency_panel(ident, spectrum.shape, [0, 0, image.width, image.height])]
                                      if action == "fft" else
                                      [spatial_panel(parent, rect, [0, 0, image.width, image.height])])
                if action == "view":
                    settings["scale_bar"] = request.get("scale_bar", (parent.get("display") or {}).get("scale_bar", True))
                    image, bar = spatial_scale_bar(image, metadata["panels"][0], record, settings["scale_bar"])
                    metadata["scale_bar"] = bar
                    settings["scale_bar_calibration_dependency"] = calibration.dependency(record)
                else:
                    metadata["panels"][0].update(physical_frequency_axes=metadata.get("physical_frequency_axes"),
                                                calibration_dependency=calibration.dependency(record))
            if action == "view" and inherited_annotations:
                save_png(directory / "unannotated.png", image)
                image, projected = overlay(image, inherited_annotations, metadata["panels"], reproject=True)
                metadata.update(annotations=projected, annotation_reprojection=True, scientific_data_changed=False)
            if action in ("view", "fft"):
                metadata["display_calibration_id"] = record["calibration_id"] if record else None
                save_png(directory / "preview.png", image)
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
            records = [row[0].get("xy_calibration") for row in loaded]
            composite = Image.new("RGB" if any(calibration.active_scale(r) for r in records) else "L",
                                  (sum(image.width for image in images), max(image.height for image in images)))
            panels, left = [], 0
            for index, (ident, roi, image) in enumerate(zip(ids, rois, images)):
                local_panel = spatial_panel(loaded[index][0], rect, [0, 0, image.width, image.height])
                image, bar = spatial_scale_bar(image, local_panel, records[index])
                composite.paste(image, (left, 0))
                panels.append({**local_panel, "image_rect_xyxy": [left, 0, left + image.width, image.height],
                               "xy_calibration": records[index], "scale_bar": translate_scale_bar(bar, left)})
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
                            xy_calibration=records[0] if all(r == records[0] for r in records) else None,
                            panel_calibrations=records,
                            display_calibration_id=records[0]["calibration_id"] if records[0] and all(r == records[0] for r in records) else None,
                            comparison_scope="same half-open pixel ROI and shared display mapping; no registration or physical alignment inferred")
        elif action == "annotate":
            parent, _, context = self.resolved(request.get("object_id"))
            need(parent["kind"] in ("view", "compare", "fft", "fft_view", "annotate"), "annotate requires a rendered view/compare/FFT object")
            base_id = parent.get("render_base_object_id", parent["object_id"])
            render_base, base_directory = self.object(base_id)
            current_record = metadata.get("xy_calibration")
            need(render_base.get("display_calibration_id") == (current_record["calibration_id"] if current_record else None),
                 "The selected calibration differs from this PNG's render dependency; call image_preview on the calibrated wrapper before editing annotations",
                 "STALE_CALIBRATION_DISPLAY")
            patch_mode = "updates" in request
            need(("annotations" in request) != patch_mode,
                 "Supply exactly one of annotations (replacement) or updates (existing IDs)")
            updates = request.get("updates")
            if patch_mode:
                need(type(updates) is list and 1 <= len(updates) <= 100,
                     "updates must contain 1..100 edits; annotations:[] explicitly clears all marks")
                annotations = parent.get("annotations", [])
            else:
                annotations = request["annotations"]
            need(type(annotations) is list and len(annotations) <= 128, "annotations must be an explicit list of at most128 items")
            base_file = "unannotated.png" if "unannotated.png" in render_base["files_sha256"] else "preview.png"
            with Image.open(base_directory / base_file) as unannotated:
                image, validated = overlay(unannotated, annotations, render_base.get("panels", []), updates=updates)
            save_png(directory / "preview.png", image)
            metadata.update(parent_object_id=request["object_id"], render_base_object_id=base_id,
                            panels=render_base.get("panels", []), annotations=validated,
                            user_context=context,
                            display_calibration_id=render_base.get("display_calibration_id"),
                            revision_semantics=("updates change only named existing annotations; omitted fields and marks persist"
                                                if patch_mode else
                                                "annotations replace the previous revision; empty list restores the original unannotated render"),
                            annotation_edit_mode="update" if patch_mode else "replace",
                            scientific_data_changed=False)
        elif action == "context":
            previous, _ = self.object(request.get("object_id"))
            base, _, inherited = self.resolved(previous["object_id"])
            provided = request.get("metadata")
            allowed = {"reconstruction_type", "data_meaning", "frame_meaning", "xy_scale", "source_text", "value_unit", "frame_scale", "research_observation"}
            need(type(provided) is dict and set(provided) <= allowed, "Only explicit versioned user-context fields are allowed")
            combined = dict(inherited or {})
            for key, value in provided.items():
                if key == "research_observation":
                    need(type(value) is dict and set(value) == {"kind", "source_text", "authority"} and
                         value["kind"] == "twinning_present" and value["authority"] in ("user_confirmed", "synthetic_fixture") and
                         type(value["source_text"]) is str and bool(value["source_text"].strip()) and len(value["source_text"]) <= 1000,
                         "A scoped twinning observation needs its actual statement and researcher/synthetic authority; it cannot confirm a twin law or HKL")
                    metadata["research_observation_scope"] = {
                        "confirmation_scope": "twinning_present_only",
                        "scientific_grid_identity": self.measurement_grid_identity(previous["object_id"]),
                        "source_object_id": previous["object_id"],
                        "authority_semantics": "caller-reported statement, not independently authenticated or scientific proof"}
                elif key == "frame_scale" and value is not None:
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
            if context is None:
                context = scientific.get("user_context")
            source_directory = self.root / "objects" / scientific["object_id"]
            record = metadata.get("xy_calibration")
            if image_object.get("image_path"):
                need(scientific.get("display_calibration_id") == (record["calibration_id"] if record else None),
                     "The selected calibration differs from this PNG's render dependency; call image_preview before export",
                     "STALE_CALIBRATION_DISPLAY")
            numeric_result = scientific["kind"] in ("statistics", "profile")
            names = [name for name in scientific["files_sha256"] if name.endswith(".npy") or numeric_result and name in ("statistics.json", "profile.csv")]
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
            elif numeric_result:
                export_display = None
            else:
                values = load_array(source_directory / names[0])
                export_display = display_options({}, [values])
                exported_image = render(values, export_display, (1024, 1024))
                exported_image, bar = spatial_scale_bar(exported_image, spatial_panel(scientific, [0, 0, values.shape[1], values.shape[0]],
                                                                                     [0, 0, exported_image.width, exported_image.height]), record)
                export_display.update(scale_bar=bar, calibration_dependency=calibration.dependency(record))
                save_png(output / "preview.png", exported_image)
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
                               "xy_calibration": record, "calibration_review": metadata.get("calibration_review"),
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

    def revise_comparison(self, parent, parent_directory, context, request, metadata, directory, annotations):
        need(request.get("rect") is None and not any(key in request for key in ("representation", "spectrum_filter", "spectrum_axes", "display_preset", "frequency_rect")),
             "Saved comparison preview changes display only; choose a new ROI using image_compare")
        names = ["data-{}.npy".format(i) for i in range(len(parent["panels"]))]
        values = [load_array(parent_directory / name) for name in names]
        settings = display_options(request, values, parent["display"])
        need(settings["max_size"] >= len(values), "max_size is too small for comparison panels")
        images = [render(v, settings, (settings["max_size"] // len(values), settings["max_size"])) for v in values]
        record = parent.get("xy_calibration")
        records = [record] * len(images) if record else parent.get("panel_calibrations", [None] * len(images))
        settings["scale_bar"] = request.get("scale_bar", parent["display"].get("scale_bar", True))
        image = Image.new("RGB" if any(calibration.active_scale(r) for r in records) else "L",
                          (sum(v.width for v in images), max(v.height for v in images)))
        panels, left = [], 0
        for old, png, name, values_part, selected_record in zip(parent["panels"], images, names, values, records):
            local_panel = {**old, "image_rect_xyxy": [0, 0, png.width, png.height]}
            png, bar = spatial_scale_bar(png, local_panel, selected_record, settings["scale_bar"])
            image.paste(png, (left, 0))
            panels.append({**old, "image_rect_xyxy": [left, 0, left + png.width, png.height],
                           "xy_calibration": selected_record, "scale_bar": translate_scale_bar(bar, left)})
            left += png.width
            save_array(directory, name, values_part)
        if annotations:
            save_png(directory / "unannotated.png", image)
            image, annotations = overlay(image, annotations, panels, reproject=True)
        save_png(directory / "preview.png", image)
        for key in ("object_ids", "source_shape_yx", "source_rect_xyxy", "raw_statistics", "raw_differences", "comparison_scope"):
            metadata[key] = parent[key]
        metadata.update(kind="compare", parent_object_id=request["object_id"], user_context=context,
                        display=settings, panels=panels, scientific_data_changed=False,
                        xy_calibration=record, panel_calibrations=records,
                        display_calibration_id=record["calibration_id"] if record else None,
                        annotations=annotations, annotation_reprojection=bool(annotations))
        return self.publish(metadata, directory)


def panel(object_id, source_rect, image_rect, array_domain=None):
    frequency = array_domain in ("frequency", "reciprocal")
    return {"domain": "source_array_indices" if frequency else "spatial_pixels", "source_object_id": object_id,
            "source_rect_xyxy": list(source_rect), "image_rect_xyxy": list(image_rect),
            **({"upstream_array_domain": "frequency", "spatial_roi_mapping_performed": False,
                "frequency_mapping_performed": False,
                "limitation": "indices of the imported scalar array only; original FFT and spatial coordinates remain upstream provenance"} if frequency else {}),
            "pixel_center_mapping": "source_x=x0+(image_x-panel_left+0.5)*source_width/panel_width-0.5; analogous y",
            "edge_mapping": "source_x=x0+(image_x-panel_left)*source_width/panel_width; analogous y"}


def spatial_panel(parent, rect, image_rect):
    """Compose crop offsets; a display object is not a new source coordinate grid."""
    if parent.get("kind") == "view" and len(parent.get("panels", [])) == 1:
        old = parent["panels"][0]
        x, y = old["source_rect_xyxy"][:2]
        mapped = [rect[0] + x, rect[1] + y, rect[2] + x, rect[3] + y]
        return {**old, "source_rect_xyxy": mapped, "image_rect_xyxy": list(image_rect)}
    return panel(parent["object_id"], rect, image_rect, array_domain=parent.get("array_domain"))


def frequency_panel(object_id, shape, image_rect, frequency_rect=None):
    height, width = map(int, shape)
    selected = rectangle(frequency_rect, shape)
    x0, y0, x1, y1 = selected
    return {"domain": "frequency", "source_object_id": object_id, "image_rect_xyxy": list(image_rect),
            "fft_rect_xyxy": selected,
            "dc_visible": x0 <= width//2 < x1 and y0 <= height//2 < y1,
            "frequency_bounds_centers_xyxy": [(x0-width//2)/width, (y0-height//2)/height,
                                               (x1-1-width//2)/width, (y1-1-height//2)/height],
            "fft_shape_yx": [height, width], "dc_bin_xy": [width // 2, height // 2], "unit": "cycles/pixel",
            "bin_center_mapping": "fft_x=fft_rect_x0+(image_x-panel_left+0.5)*fft_rect_width/panel_width-0.5; analogous y",
            "frequency_coordinate_rule": "fx=(fft_x-floor(fft_width/2))/fft_width; fy=(fft_y-floor(fft_height/2))/fft_height",
            "spatial_roi_mapping": "not performed; the FFT input spatial ROI is separate operation provenance"}


def coordinate_transform(coords, current, edges, inverse=False):
    """Continuous coordinate transform, independent x/y sizes, no clipping."""
    left, top, right, bottom = current["image_rect_xyxy"]
    if current["domain"] == "frequency":
        h, w = current["fft_shape_yx"]
        # Frequency coordinates are bin centres; edges lie half a bin outside.
        offsets = [-(w // 2), -(h // 2)]
        x0, y0, x1, y1 = current.get("fft_rect_xyxy", [0, 0, w, h])
        source0, extent = [x0, y0], [x1-x0, y1-y0]
        grid = [w, h]
    else:
        x0, y0, x1, y1 = current["source_rect_xyxy"]
        source0, extent = [x0, y0], [x1-x0, y1-y0]
    result = []
    for i, value in enumerate(coords):
        axis = i % 2
        start, size = (left, right-left) if axis == 0 else (top, bottom-top)
        # Spatial edges use source edge indices; frequency edges use continuous
        # centre indices (edge zero = bin -0.5), as in the existing FFT panel.
        centre = 0.5 if not edges or current["domain"] == "frequency" else 0.0
        image_centre = 0.0 if edges else 0.5
        if inverse:
            local = value*grid[axis]-offsets[axis] if current["domain"] == "frequency" else value
            result.append(start + (local-source0[axis]+centre)*size/extent[axis]-image_centre)
        else:
            local = source0[axis]+(value-start+image_centre)*extent[axis]/size-centre
            result.append((local+offsets[axis])/grid[axis] if current["domain"] == "frequency" else local)
    need(all(number(value) for value in result), "Annotation transform exceeds finite coordinates")
    return result


def annotation_presentation(value):
    """Validate display-only metadata without modifying a scientific anchor.

    Offsets use base-render pixels. They never supply source coordinates or an
    authority change; no SVG, HTML, styling program or arbitrary font is stored.
    """
    fields = {"marker_shape", "marker_radius", "line_width", "category", "layer", "label", "geometry_visible"}
    need(type(value) is dict and set(value) <= fields, "Unknown annotation presentation field")
    enums = {"marker_shape": ("circle", "square", "double_circle", "diamond", "cross"),
             "category": ("A", "B", "shared", "unexplained", "none"),
             "layer": ("experimental", "simulation_A", "simulation_B")}
    for key, choices in enums.items():
        need(key not in value or value[key] in choices, "Invalid annotation presentation " + key)
    for key, lower, upper in (("marker_radius", 4, 12), ("line_width", .5, 3)):
        need(key not in value or number(value[key]) and lower <= value[key] <= upper,
             "Annotation presentation " + key + " is out of range")
    need("geometry_visible" not in value or type(value["geometry_visible"]) is bool,
         "geometry_visible must be an explicit boolean")
    if "label" in value:
        label = value["label"]
        need(type(label) is dict and set(label) <= {"text", "offset", "font_size", "leader", "pinned", "visible", "figure_visible", "important",
                                                  "measurement_object_id", "measurement_kind"},
             "Unknown presentation label field")
        need("text" not in label or type(label["text"]) is str and len(label["text"]) <= 256,
             "Presentation label text exceeds its display-only budget")
        need("offset" not in label or type(label["offset"]) is list and len(label["offset"]) == 2 and
             all(number(v) and abs(v) <= 4096 for v in label["offset"]),
             "Presentation label offset requires two finite bounded base-render pixels")
        need("font_size" not in label or number(label["font_size"]) and 8 <= label["font_size"] <= 32,
             "Presentation label font_size must be in 8..32 display pixels")
        need("measurement_object_id" not in label or type(label["measurement_object_id"]) is str and
             re.fullmatch(r"[a-f0-9]{32}", label["measurement_object_id"]) is not None,
             "Presentation measurement_object_id must be a saved 32-hex object reference")
        need("measurement_kind" not in label or label["measurement_kind"] in ("distance", "period"),
             "Presentation measurement_kind must be distance or period")
        for key in ("leader", "pinned", "visible", "figure_visible", "important"):
            need(key not in label or type(label[key]) is bool, "Presentation label " + key + " must be an explicit boolean")
    return value


def annotation(item, image_size, panels, reproject=False):
    if reproject:
        anchor = item.get("anchor")
        need(anchor is not None, "Annotation has no unique source anchor; replace or remove it before re-rendering")
        supplied = {key: item[key] for key in ("kind", "text", "status", "note", "annotation_id", "line_width", "arrowhead_size", "arrow_length", "color", "presentation") if key in item}
        # Old immutable records predate the display-length cap. Re-render their
        # original shaft rather than retroactively applying the new default.
        if item.get("kind") == "arrow" and "arrow_length" not in item:
            supplied["arrow_length"] = None
        supplied.update(anchor)
        item = supplied
    allowed = {"kind", "coordinates", "text", "status", "note", "annotation_id", "coordinate_space", "source_object_id",
               "line_width", "arrowhead_size", "arrow_length", "color", "presentation"}
    need(type(item) is dict and set(item) <= allowed, "Unknown annotation field")
    presentation = annotation_presentation(item["presentation"]) if "presentation" in item else None
    kind, coords = item.get("kind"), item.get("coordinates")
    lengths = {"point": 2, "text": 2, "rectangle": 4, "line": 4, "arrow": 4}
    need(type(coords) is list and all(number(value) for value in coords) and
         (kind == "polygon" and 6 <= len(coords) <= 64 and len(coords) % 2 == 0 or
          kind in lengths and len(coords) == lengths[kind]), "Invalid annotation kind or finite coordinate count")
    edges = kind in ("rectangle", "polygon")
    if kind == "rectangle":
        need(coords[0] < coords[2] and coords[1] < coords[3], "Invalid half-open annotation rectangle")
    if kind in ("line", "arrow"):
        need(coords[:2] != coords[2:], "Line/arrow needs distinct endpoints")
    status = item.get("status", "hypothesized")
    need(status in ("hypothesized", "user_confirmed", "retracted"), "Explicit annotation status required")
    text, note = item.get("text", ""), item.get("note", "")
    need(type(text) is str and len(text) <= 256 and type(note) is str and len(note) <= 2048, "Annotation text/note exceeds budget")
    need(kind != "text" or bool(text), "Text annotation requires text")
    ident = item.get("annotation_id")
    need(ident is None or type(ident) is str and REQUEST_ID.fullmatch(ident), "Invalid annotation_id")
    line_width = item.get("line_width", 3 if kind == "arrow" else 1)
    arrowhead_size = item.get("arrowhead_size", 6 if kind == "arrow" else 4)
    need(integer(line_width, 1, 4) and integer(arrowhead_size, 1, 12), "Annotation line_width needs 1..4 and arrowhead_size 1..12 display pixels")
    arrow_length = item.get("arrow_length", 24)
    need("arrow_length" not in item or kind == "arrow", "arrow_length is only valid for arrows")
    need(arrow_length is None or integer(arrow_length, 4, 128), "arrow_length needs null or 4..128 display pixels")
    color = item.get("color", "cyan" if kind == "arrow" else "green" if status == "user_confirmed" else "amber")
    need(color in ("white", "cyan", "orange", "amber", "green"), "Unsupported display annotation color")
    space = item.get("coordinate_space", "rendered_image_pixels")
    need(space in ("rendered_image_pixels", "source_pixels", "source_array_indices", "frequency_cycles_per_pixel"),
         "Unsupported annotation coordinate space")
    rendered, matches, anchor = list(coords), [], None
    def contains(values, bounds):
        l, t, r, b = bounds
        return all(l <= x <= r and t <= y <= b if edges else l <= x <= r-1 and t <= y <= b-1
                   for x, y in zip(values[::2], values[1::2]))
    if space == "rendered_image_pixels":
        need("source_object_id" not in item, "Rendered coordinates do not take a source_object_id")
        need(contains(coords, [0, 0, *image_size]), "Annotation lies outside the rendered image")
        matches = [p for p in panels if contains(coords, p["image_rect_xyxy"])]
        if len(matches) == 1:
            current = matches[0]
            anchor = {"coordinate_space": {"frequency": "frequency_cycles_per_pixel", "spatial_pixels": "source_pixels",
                                           "source_array_indices": "source_array_indices"}[current["domain"]],
                      "source_object_id": current["source_object_id"],
                      "coordinates": coordinate_transform(coords, current, edges)}
    else:
        source = item.get("source_object_id")
        need(type(source) is str and OBJECT_ID.fullmatch(source), "Anchored annotations require an explicit source_object_id from panels")
        domain = {"frequency_cycles_per_pixel": "frequency", "source_pixels": "spatial_pixels",
                  "source_array_indices": "source_array_indices"}[space]
        matches = [p for p in panels if p["source_object_id"] == source and p["domain"] == domain]
        need(len(matches) == 1, "Annotation source/domain must match exactly one panel; no name/recency matching")
        current = matches[0]
        anchor = {"coordinate_space": space, "source_object_id": source, "coordinates": list(coords)}
        rendered = coordinate_transform(coords, current, edges, inverse=True)
        # Coordinate centres at the last source pixel can map slightly past the
        # last displayed centre under downsampling; check source bounds instead.
        if current["domain"] == "frequency":
            h, w = current["fft_shape_yx"]
            x0, y0, x1, y1 = current.get("fft_rect_xyxy", [0, 0, w, h])
            margin = 0.5 if edges else 0
            bounds = [(x0-w//2-margin)/w, (y0-h//2-margin)/h,
                      (x1-1-w//2+margin)/w, (y1-1-h//2+margin)/h]
        else:
            x0, y0, x1, y1 = current["source_rect_xyxy"]
            bounds = [x0, y0, x1 if edges else x1-1, y1 if edges else y1-1]
        visible = all(bounds[0] <= x <= bounds[2] and bounds[1] <= y <= bounds[3]
                      for x, y in zip(coords[::2], coords[1::2]))
        need(reproject or visible, "Annotation lies outside its source panel")
    mappings = []
    if len(matches) == 1:
        current = matches[0]
        mapped = anchor["coordinates"]
        if current["domain"] == "frequency":
            h, w = current["fft_shape_yx"]
            mappings.append({"source_object_id": current["source_object_id"], "domain": "frequency",
                             "frequency_cycles_per_pixel": mapped,
                             "fft_bin_coordinates": [v*n+n//2 for v, n in zip(mapped, [w, h]*(len(mapped)//2))],
                             "physical_frequency_unit": None, "spatial_roi_mapping_performed": False})
        else:
            key = "array_index_coordinates" if current["domain"] == "source_array_indices" else "coordinates"
            mappings.append({"source_object_id": current["source_object_id"], "domain": current["domain"], key: mapped,
                             **({"spatial_roi_mapping_performed": False, "frequency_mapping_performed": False} if key == "array_index_coordinates" else {})})
    arrow_display = {}
    if kind == "arrow":
        x0, y0, x1, y1 = rendered
        distance = math.hypot(x1-x0, y1-y0)
        need(number(distance) and distance > 0, "Arrow endpoints must remain distinct finite display positions")
        ratio = min(1., arrow_length/distance) if arrow_length is not None else 1.
        # Only the displayed tail moves. Scientific anchors and the arrow tip
        # retain their exact coordinates; a short original arrow is not extended.
        arrow_display = {"arrow_length": arrow_length,
                         "arrow_render_coordinates": [x1+(x0-x1)*ratio, y1+(y0-y1)*ratio, x1, y1]}
    return {"kind": kind, "coordinates": rendered, "coordinate_space": "rendered_image_pixels",
            "coordinate_convention": "pixel edges" if edges else "pixel/bin centres; x right, y down",
            "status": status, "text": text, "note": note, "source_mappings": mappings, "anchor": anchor,
            "line_width": line_width, "arrowhead_size": arrowhead_size,
            **arrow_display,
            "color": color,
            **({"presentation": presentation} if presentation is not None else {}),
            **({"annotation_id": ident} if ident is not None else {}),
            "visibility": "outside_view" if space != "rendered_image_pixels" and not visible else "visible",
            "mapping_status": "one_source" if len(matches) == 1 else "not_a_single_source_region"}


def overlay(image, annotations, panels, reproject=False, updates=None):
    image = image.convert("RGB")
    draw, result, seen = ImageDraw.Draw(image), [], set()
    entries = (plan_annotation_updates(annotations, updates) if updates is not None else
               ((item, reproject) for item in annotations))
    for item, project in entries:
        mark = annotation(item, image.size, panels, reproject=project)
        ident = mark.get("annotation_id")
        need(ident is None or ident not in seen, "Duplicate annotation_id in replacement revision")
        seen.add(ident)
        result.append(mark)
        if mark["status"] == "retracted" or mark["visibility"] != "visible":
            continue
        color = {"white": "#ffffff", "cyan": "#45e8ff", "orange": "#ff8c32", "amber": "#ffba30", "green": "#00e060"}[mark["color"]]
        coords, kind = mark["coordinates"], mark["kind"]
        if kind == "arrow":
            coords = mark["arrow_render_coordinates"]
        if kind == "point":
            x, y = coords
            draw.ellipse([x-3, y-3, x+3, y+3], outline=color, width=mark["line_width"])
        elif kind == "rectangle":
            draw.rectangle(coords, outline=color, width=mark["line_width"])
        elif kind == "polygon":
            points = list(zip(coords[::2], coords[1::2]))
            draw.line(points + points[:1], fill=color, width=mark["line_width"])
        elif kind in ("line", "arrow"):
            draw.line(coords, fill=color, width=mark["line_width"])
            if kind == "arrow":
                x0, y0, x1, y1 = coords
                angle = math.atan2(y1-y0, x1-x0)
                size = min(mark["arrowhead_size"], math.hypot(x1-x0, y1-y0)/3)
                points = [(x1, y1)] + [(x1-size*math.cos(angle+a), y1-size*math.sin(angle+a)) for a in (-.5, .5)]
                draw.polygon(points, fill=color)
        else:
            draw.text(coords, mark["text"], fill=color)
        if mark["text"] and kind != "text":
            draw.text(coords[:2], mark["text"], fill=color)
    return image, result


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
