# Bounded numerical relay into DM

The intended relay is an explicit DM image/frame/ROI snapshot, further Agent
measurement or external computation, then an independent new DM image. A new
handoff after manual editing captures the new state; old snapshots stay historical.
Unknown earlier GUI processing history is recorded as unknown, not invented.

Current outbound tools already provide explicit-ID bounded `dm_native_read`,
frame copies, calibrated numeric metadata and saved-response NPY handoff. A
screenshot or display PNG is never the numerical input. Keep sources unchanged
during capture; a native descriptor/identity check is not a promise to synchronize
unknown concurrent editing. Unsupported complex data/layouts remain unsupported.

## New import candidate

`dm_native_import` adds a restricted NPY + UTF-8 JSON handoff, not script execution,
file-open automation, a new processing backend or native SaveAs. Its initial
scope is finite little-endian C-order **2D float32**, at most **16,384 samples**.
It stages exact immutable bytes under the explicit native session, sends a fixed
ticket plus both hashes, and creates an independent DM image through native
interfaces. The source NPY, source metadata and existing DM images are read-only.
Other dtypes, complex arrays, arbitrary format decoding, intensity-unit setters
and source-image overwrite are absent. Convert explicitly outside the native
runtime and preserve conversion error/old arrays when necessary.
The source JSON read is bounded to 24 KiB; the staged handoff, including its
source record, is bounded to 32 KiB of raw UTF-8 and 16 KiB after JSON quoting
in the native receipt. Oversized provenance is refused before dispatch;
the bridge does not silently truncate it. The exact original JSON text and hash
remain authoritative, including values unsafe for JavaScript numeric parsing.

Provide the coordinate domain (`image_coordinates`, `real_space` or
`reciprocal_space`) and raw DM X/Y origin plus signed scale. The convention is
`physical=(index-origin)*scale`, with `[y,x]` storage. Units are limited to empty,
nm/Å/µm or their reciprocal units in the matching domain. Empty units do not imply
a physical length. Requested binary64 calibration and native binary32 rounding
are both recorded. Nonfinite/overflowed native coordinates are refused. Source
history/provenance remains an exact hash-bound external record, not unverified
DM tag writes.

Save `request_id` **before submission**. Same original arguments query the
original operation, even if the input files have since changed or disappeared;
that query remains historical. A fresh capture needs a new ID. Different
arguments with the same ID are rejected. Timeout/cancellation never implies
rollback or automatically creates a second image. Recovery is restricted to
the still-queryable native session. A separate saved-ID `dm_native_show` delivers
an admitted result to a DM document; it is not an import or a file save.

## Qualification boundary

Only the exact pinned Windows x64 GMS adapter is eligible. Finding exports is
insufficient. `native_numeric_import` remains disabled in the normal build
until its own creation, dtype, signed-calibration, readback and reference-lifetime
tests qualify the final artifact. A separately labeled qualification build is
for synthetic idle-host testing, not release support. Preserve the host/module
fingerprint gates and the existing qualified operations.

Offline fakes and scientific NPY checks do not establish real DM behavior.
Live native readback, independent host-array/oracle checks, document display,
STOP/reference ownership and real researcher editing must be reported separately.
Data in a DM document remains editable by the researcher; recapture afterwards
rather than reuse an immutable old snapshot. Original experimental data must not
be used for candidate writes or uploaded in validation evidence.
