# Histogram axis: evidence and remaining ABI boundary

The integrated histogram continues to publish `axis_mode:"bin_index"`. Its
native count image is uint32; its bounded wire payload uses binary64 because
every admitted count is exactly representable there. Neither encoding changes
the scientific meaning of the X axis or applies the source intensity calibration.

## Official example and native contract

Gatan's [Interactive histogram example](https://www.gatan.com/Software/Scripts/DigitalMicrograph-Library/Interactive-histogram)
creates a one-dimensional unsigned four-byte integer image. Before calculating
the histogram it sets the X calibration with origin equal to the lower requested
bound, scale equal to range width divided by the number of channels, the source
intensity unit, and format zero. It separately sets the output intensity
calibration to zero origin, unit scale and `#pixels`. The example therefore
distinguishes bin coordinates from count values. It does not document the C++
ABI or define the numeric `format` enumeration.

The pinned export inventory independently identifies two different native
`Image::SetDimensionCalibration` overloads. One takes a dimension and a
`DimensionCalibrationInfo` object; the other takes a dimension, two floats,
a wide-character begin/end range and an integer format. They cannot be
interchanged with a Python method, a script wrapper, or a `std::wstring`
argument. The existing begin/end POD and getter ABI do not alone qualify a
setter call or an unknown calibration-info object layout.

The already qualified getter preserves two different quantities: its format-zero
value is the physical coordinate at pixel zero; format one supplies the stored
origin. The bridge's coordinate contract is
`physical(i)=physical_zero+i*signed_scale`. Under the separately established
stored-origin convention, `physical_zero=-stored_origin*signed_scale`.
Consequently, interpreting a requested lower intensity edge as a stored pixel
origin would generally give a different axis. This is a diagnostic distinction,
not proof that it caused the earlier setter failure.

## What the independent integration review established

The prior PR records a failed attempted format-zero setter/readback comparison.
That failure is preserved. The available historical calibration probe source
sets a nonzero lower bound and reads both getter formats, but its saved output
was not present in the reviewed evidence directory. The retained successful
histogram receipt instead has the untouched index axis: raw origin zero,
physical zero zero, unit scale and unknown unit. The review cannot reconstruct
the failed call's exact inputs, returned values or root cause from that receipt,
and does not relabel the historical report as an independently reproduced FAIL.

No setter was added, called or qualified in this review. In particular, the
official script's last parameter being zero does not authorize trying several
native formats until one happens to look plausible. Source intensity units also
do not justify labelling raw bin boundaries as calibrated electron counts.

## Required controlled follow-up

Before enabling an intensity axis, retain the exact typed call contract and
its static evidence, then run a fresh idle synthetic-host comparison. Record
the submitted setter parameters, exact host identity, both getter formats,
stored origin, physical pixel zero, signed scale and unit before and after.
Compare script/Python and direct native paths separately. Include nonzero
positive and negative lower edges and non-unit scales; a zero origin alone
cannot distinguish the two conventions. Check the output document's axis
against the returned metadata without changing the source.

Also qualify counts at each bin boundary, including the requested upper edge,
using the DM operator and an independent saved-input oracle. Explicit range and
bin geometry are retained even while the display remains an index plot. No
claim about a physical intensity display axis or untested overflow handling is
implied by count conservation or successful file export.
