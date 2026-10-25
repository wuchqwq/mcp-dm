from pathlib import Path
import sys
root = Path(sys.argv[1]).resolve()
payload = Path(__file__).resolve().parent
p = root / 'tools/image_workspace.py'
s = p.read_text(encoding='utf-8')
def replace(old, new):
    global s
    assert s.count(old) == 1, (old[:110], s.count(old))
    s = s.replace(old, new)
replace('"view": {"object_id", "rect", "display_range", "gamma", "max_size"},',
        '"view": {"object_id", "rect", "display_range", "gamma", "max_size", "representation"},')
replace('def display_options(request, values):\n    gamma, maximum = request.get("gamma", 1.0), request.get("max_size", 1024)', '''def display_options(request, values, inherited=None):
    # Omitted fields revise a saved view; explicit null range requests a fresh
    # auto-range. This never reapplies a display transform to scientific values.
    inherited = inherited if inherited is not None else {}
    gamma = request.get("gamma", inherited.get("gamma", 1.0))
    maximum = request.get("max_size", inherited.get("max_size", 1024))''')
replace('''    supplied = request.get("display_range")
    if supplied is None:
        low = min(float(value.min()) for value in values)
        high = max(float(value.max()) for value in values)
    else:
        need(type(supplied) is list and len(supplied) == 2 and all(number(v) for v in supplied) and supplied[0] < supplied[1],
             "display_range requires finite [minimum,maximum] with minimum<maximum")
        low, high = map(float, supplied)
    return {"display_range": [low, high], "range_source": "explicit" if supplied is not None else "shared_raw_minmax",''', '''    supplied = request.get("display_range")
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
    return {"display_range": [low, high], "range_source": range_source,''')
replace('''def render(values, settings, bound):''', '''def spectrum_display(values, representation):
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


def render(values, settings, bound):''')
replace('''            if metadata["kind"] != "context":
                return metadata, directory, context''', '''            if metadata["kind"] != "context":
                # Derived views/FFTs already carry effective user context.
                # None means absent; empty patches and explicit null fields
                # must not resurrect or discard an earlier interpretation.
                if context is None:
                    context = metadata.get("user_context")
                return metadata, directory, context''')
replace('''        elif action in ("view", "fft", "measure"):
            parent, _, context, values = self.scalar(request.get("object_id"))
            metadata.update(parent_object_id=request["object_id"], user_context=context or parent.get("user_context"),
                            source_object_id=parent["object_id"])
            if action == "measure":''', '''        elif action in ("view", "fft", "measure"):
            spectral_view = False
            if action == "view":
                parent, parent_directory, context = self.resolved(request.get("object_id"))
                spectral_view = parent["kind"] in ("fft", "fft_view")
                need(parent["kind"] in ("frame", "view", "fft", "fft_view"),
                     "preview requires a frame/view or FFT; for annotations use render_base_object_id and reapply annotations")
                values = load_array(parent_directory / "data.npy", allow_complex=spectral_view)
                need(spectral_view or "representation" not in request,
                     "representation is only valid for a saved complex FFT")
            else:
                parent, _, context, values = self.scalar(request.get("object_id"))
            metadata.update(parent_object_id=request["object_id"], user_context=context,
                            source_object_id=parent["object_id"])
            if spectral_view:
                need(values.dtype == np.dtype("complex128"), "FFT view requires the saved complex128 spectrum")
                need(request.get("rect") is None,
                     "FFT re-rendering uses the full saved spectrum; select a spatial ROI before FFT, not a hidden frequency crop")
                old_display = dict(parent.get("display") or {})
                previous_mode = old_display.get("representation", "log_amplitude")
                mode = request.get("representation", previous_mode)
                shown, expression = spectrum_display(values, mode)
                if mode != previous_mode:
                    # Amplitude, power and log amplitude have different units;
                    # preserve gamma/size, but never inherit their old limits.
                    old_display.pop("display_range", None)
                settings = display_options(request, [shown], old_display)
                settings["representation"] = mode
                image = render(shown, settings, (settings["max_size"], settings["max_size"]))
                spectrum_id = parent.get("spectrum_object_id", parent["object_id"])
                save_array(directory, "data.npy", values)
                save_png(directory / "preview.png", image)
                metadata.update(kind="fft_view", source_object_id=spectrum_id, spectrum_object_id=spectrum_id,
                                dtype="complex128", shape_yx=list(values.shape), axes=["fy", "fx"], array_domain="frequency",
                                frequency_unit=parent["frequency_unit"], physical_frequency_unit=parent["physical_frequency_unit"],
                                frequency_axes=parent["frequency_axes"], display_representation=expression, display=settings,
                                panels=[frequency_panel(spectrum_id, values.shape, [0, 0, image.width, image.height])],
                                fft_recomputed=False, scientific_data_changed=False,
                                rendering_scope="saved external complex FFT; amplitude/power/log are display-only; NPY remains complex")
            elif action == "measure":''')
replace('''                    displayed = np.log1p(np.abs(spectrum))
                    settings = display_options({"max_size": request.get("max_size", 1024)}, [displayed])''', '''                    displayed, expression = spectrum_display(spectrum, "log_amplitude")
                    settings = display_options({"max_size": request.get("max_size", 1024)}, [displayed])
                    settings["representation"] = "log_amplitude"''')
replace('''                                    display_representation="log1p(abs(complex128 spectrum))", display=settings)''', '''                                    display_representation=expression, display=settings, array_domain="frequency")''')
replace('''                    settings = display_options(request, [roi])''', '''                    settings = display_options(request, [roi], parent.get("display"))''')
replace('''            need(parent["kind"] in ("view", "compare", "fft", "annotate"), "annotate requires a rendered view/compare/FFT object")''', '''            need(parent["kind"] in ("view", "compare", "fft", "fft_view", "annotate"), "annotate requires a rendered view/compare/FFT object")''')
replace('''                            user_context=context or parent.get("user_context"),''', '''                            user_context=context,''')
replace('''            context = context or image_object.get("user_context") or scientific.get("user_context")''', '''            if context is None:
                context = scientific.get("user_context")''')
p.write_bytes(s.encode('utf-8'))
p = root / 'lib/image_workspace.mjs'
s = p.read_text(encoding='utf-8')
s = s.replace("display_range:{type:'array',items:{type:'number'},minItems:2,maxItems:2}", "display_range:{type:['array','null'],items:{type:'number'},minItems:2,maxItems:2,description:'Explicit display limits; image_preview inherits an existing view when omitted. New frames/comparisons or null use auto-range.'}")
s = s.replace("write('image_preview','Return a viewable PNG of an explicit image or pixel ROI. Display range/gamma affect rendering only, never scientific values. No physical calibration required.',{object_id:id,rect,...display},['object_id'])", "write('image_preview','Render an image/ROI or re-render a saved external FFT without recomputing it. Existing views inherit omitted display limits/gamma/size; null display_range recalculates range. FFT representation changes reset the range unless supplied; FFT rect is unsupported. PNG is display-only.',{object_id:id,rect,...display,representation:{type:'string',enum:['log_amplitude','amplitude','power'],description:'Saved complex FFT display only, not a scientific transform; omit to keep its current representation.'}},['object_id'])")
p.write_bytes(s.encode('utf-8'))
p = root / 'tests/test_image_workspace_revisions.py'
assert not p.exists()
p.write_bytes((payload / 'test_image_workspace_revisions.py').read_bytes())
p = root / 'tests/image-workspace-mcp.test.mjs'
p.write_bytes(p.read_bytes() + (payload / 'mcp_addition.mjs').read_bytes())
p = root / 'docs/PIXEL_IMAGE_WORKFLOW.md'
s = p.read_text(encoding='utf-8')
s = s.replace('| `image_preview` | Render a full plane or half-open pixel ROI with a display recipe |', '| `image_preview` | Render a scalar plane/ROI, or re-render a saved external FFT without recomputing it |')
s = s.replace('## Validation and remaining boundaries\n', (payload / 'docs_addition.md').read_text(encoding='utf-8') + '## Validation and remaining boundaries\n')
p.write_bytes(s.encode('utf-8'))
# Byte identities from the locally tested candidate. No payload files ship.
import hashlib
expected = {
 'tools/image_workspace.py': '518b7eea6a968985f8d0f8eb7989a78ed360afe3',
 'lib/image_workspace.mjs': 'b25cdf0c8753f0d560605d9855b9bee9071b2ce1',
 'tests/image-workspace-mcp.test.mjs': 'be42e44a4c9d1cc89a2d36cf3dfcf0db95e00edd',
 'tests/test_image_workspace_revisions.py': '8f2b92f3d42ba7aea261d70b601eb1e021a1392d',
 'docs/PIXEL_IMAGE_WORKFLOW.md': '95573a0aacbeb44355fc9c12a8605a23606bb3e9',
}
for name, wanted in expected.items():
 raw = (root / name).read_bytes()
 actual = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
 print(name, actual)
 assert actual == wanted, (name, actual, wanted)
