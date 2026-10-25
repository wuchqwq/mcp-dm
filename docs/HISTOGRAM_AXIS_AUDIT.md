# Histogram axis: native arithmetic and scientific limits

The histogram range and binning inputs remain raw pixel values. The native count
image is uint32; binary64 is its exact bounded wire transport. Neither a unit
label nor a display-axis setter applies source intensity calibration to those
values or counts.

## Traced contract and historical failure

Gatan's [Interactive histogram example](https://www.gatan.com/Software/Scripts/DigitalMicrograph-Library/Interactive-histogram)
sets a bin-left-edge X calibration separately from the count intensity axis. It
is evidence of script-level intent, not proof of a C++ calling convention or
permission to treat non-identity calibrated values as raw positions.

The pinned native overload takes a dimension, two binary32 values, a UTF-16
begin/end range and an integer format. Format zero receives a physical value
at pixel zero. The native setter divides that value by the signed scale and
stores the negative quotient; the format-zero getter multiplies it back.
Format one instead exposes the stored origin. Preserve both values.

The original exact-readback comparison failed. Later tracing and an independent
legacy API comparison explain a binary32 division/multiplication round trip;
they do not erase that FAIL or establish the scientific meaning of an arbitrary
source unit. Exact equality is possible for some inputs and fails for others.
The integration also rejected a broad `epsilon * max(abs(origin),abs(scale),1)`
bound: its absolute floor could exceed a tiny bin width and conceal a wrong axis.

## Current predefined checks

Only identity source intensity origin/scale (zero/one) plus a nonempty unit may
use the source-unit display axis. Non-identity or missing calibration stays
`bin_index`, retaining the complete original calibration for later explicit
interpretation. There is no hidden physical-intensity transformation.

For raw lower edge `a`, mathematical bin width `w` and `n` bins, the plan uses
binary32 `s=round32(w)`, `q=round32(a/s)` and `z=round32(q*s)`. Scale must be
positive and normal; quotient and reconstructed zero must be finite and normal
when the lower edge is nonzero. The native stored origin must read back as
`-q`, physical zero as `z`, and scale/unit must match exactly.

The predefined error bound is `ULP32(q)*s + ULP32(z)`, using the larger adjacent
finite binary32 spacing. It has no unit-sized floor. The bound plus accumulated
scale rounding over `n-1` bins must remain below one quarter of a mathematical
bin. This is a resolution admission check, not permission to move bin edges.
The receipt exposes requested/observed zero, scale, error and bound. An axis
which cannot pass the plan is reported as a bin index with an explicit reason.
The count range and numerical results never change to make a display pass.

Creation, SHOW, QUERY and saved NPY validation share this contract. SHOW carries
the frozen creation axis context and rechecks the actual live axis; metadata
saying only `calibration_complete:true` is insufficient. Independent actual-host
checks must compare both getter formats and the original raw bin geometry.

## Qualification boundaries

Offline cases include zero/nonzero and signed lower edges, non-unit/tiny scales,
subnormal or overflowing plans, forged offsets/tolerances, wrong source
calibration and both historical bin-index and current display receipts. These
are contract checks, not another native build qualification.

The fresh synthetic host separately checks native counts against independent
saved input, exact axis readback, unchanged sources, exact document ownership,
release/STOP and last-reference behavior. See [RESULTS](../experiments/native-bridge/RESULTS.md)
for actual completed scopes. General physical-intensity conversion, non-covering
ranges and other GMS builds remain unsupported. Raw trace material and detailed
run records remain private.
