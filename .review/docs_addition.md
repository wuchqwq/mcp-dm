## Revising context and an existing FFT display

Context attached to a frame, scalar view, FFT or FFT view is inherited by later
partial `image_context` updates. An omitted field retains its current value;
an explicit `null` withdraws that field, including after a preview. Original
objects and requests remain immutable. This is user-supplied interpretation,
not permission to invent or apply physical calibration.

`image_preview` now accepts the `fft` object returned by `image_fft`, or a prior
`fft_view`. It reads the saved complex128 NPY rather than executing FFT again.
The new view preserves the exact complex values, original spectrum identity and
frequency axes. `representation` selects `log_amplitude` (the initial default),
`amplitude`, or `power` for **display only**; the scientific NPY remains complex.
Native scalar FFT captures remain scalar views, not reconstructed complex data.

For an existing scalar or FFT view, omitted `display_range`, `gamma` and
`max_size` inherit the existing recipe. To ask for a new automatic range, pass
`display_range:null`. Changing a spectrum's representation automatically
recalculates the range unless a new range is supplied, because amplitude, power
and log amplitude cannot share an implicit numerical range. Gamma and size
still inherit. Rendering always starts from numerical values, not from the
previous PNG, so adjustments do not compound on already-quantized pixels.

For example, call `image_fft` once, then `image_preview` on that result with
`gamma:2`; reference the returned view for a later `representation:"power"`
request. Each step needs its own saved request ID. Annotating and exporting the
new FFT view retain the original frequency-bin mapping and exact complex NPY.

FFT re-rendering currently uses the full saved spectrum: a `rect` is rejected
rather than silently cropping/recomputing it. Choose the spatial ROI before
FFT. Annotated images and comparison composites are not directly re-rendered;
use an annotation's `render_base_object_id`, then explicitly reapply annotations
against the new view. Automatic annotation reprojection, frequency-cropped
views, arbitrary curves and new native processing are not added here.

