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

The labeled candidate has limited synthetic actual-host MCP evidence for new
image creation, exact READ/NPY round trips, original-ID recovery without a second
object, explicit document delivery and external diffsims data handoff. A fresh
same-host independent oracle checked float32 array bits (including signed zero),
axis order, signed scales, raw origins, physical zero and the ASCII units `nm`
and `1/nm`. It bound each displayed document to the exact image. The document
kept its image after plugin RELEASE; after a pre-recorded, identity-checked STOP,
hidden plugin-only results disappeared while shown images remained. Closing
only the returned result's document then released that image, leaving the other
shown arrays unchanged. These observations follow host return/idle, not immediate
destruction inside the same Python stack. The test host then exited normally;
the installer removed only its manifest-owned candidate DLL. Saved scientific
NPY inputs reopened with unchanged hashes after exit. Separate GUI-created DM4
backups are not an MCP SaveAs qualification.

Earlier failures remain evidence: the initial opened-path refusal and a legacy
GMS Python unit getter returning `1/?` where the native path reported `1/Å`.
That earlier session was interrupted by a computer restart; its unfinished
checks are not reclassified by the new session. ASCII-unit qualification does
not resolve the Unicode discrepancy. Actual researcher pixel editing followed
by recapture is still NOT_TESTED. Full qualification stays on HOLD and the
normal build capability remains disabled.

One external integration gap remains: `image_measure` does not automatically
activate native axis metadata as an operational `image_calibrate` record. The
tested relay preserved that metadata but returned pixel geometry only; it did
not invent or claim a physical measurement.

Offline fakes and scientific NPY checks do not establish real DM behavior.
Live native readback, independent host-array/oracle checks, document display,
STOP/reference ownership and real researcher editing must be reported separately.
Data in a DM document remains editable by the researcher; recapture afterwards
rather than reuse an immutable old snapshot. Original experimental data must not
be used for candidate writes or uploaded in validation evidence.
