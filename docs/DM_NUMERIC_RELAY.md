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

## Limited numerical import

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

The normal build accepts `coordinate_domain:"real_space"` with ASCII `nm`, or
`coordinate_domain:"reciprocal_space"` with ASCII `1/nm`, on both axes. Provide
raw DM X/Y origin plus signed scale. The convention is
`physical=(index-origin)*scale`, with `[y,x]` storage. The broader diagnostic
contract includes empty, nm/Å/µm and reciprocal units, but empty units,
`image_coordinates` and non-ASCII units are **not admitted by the normal
build**. Requested binary64 calibration and native binary32 rounding
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

Only the exact fingerprint-matched Windows x64 GMS 3.53.4137.0 adapter is
eligible. Finding exports is insufficient. The normal build now enables
`native_numeric_import` only for the finite, bounded float32 ASCII-unit subset
above. A fresh final normal artifact, without a qualification-build flag, passed
synthetic actual-host IMPORT/SHOW/READ, independent exact array/calibration
checks, source-NPY protection, original-ID recovery/conflict and rejected-unit
checks. Rejection occurs before staged-file loading or vendor image creation.
This is limited synthetic-host qualification, not full-range support or a stable
release. Other units, dtypes and builds remain unqualified. A separately labeled
broader diagnostic build does not extend normal admission.

The earlier labeled candidate has limited synthetic actual-host MCP evidence for new
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
backups are not an MCP SaveAs qualification. In a later candidate trial, a
researcher actually applied a DM GUI arithmetic operation to a new work image.
Fresh MCP READ/capture saw the new image and exact edited values; the old
snapshot, source values and calibration were unchanged. This human-edit trial
is distinct from the final normal-artifact short qualification.

The final normal artifact separately repeated RELEASE, original-request/PID-
bound STOP and last-document-reference closure checks. Shown images survived
plugin release/STOP; closing the specified result document invalidated only
that image after host return/idle. The host exited normally and removal touched
only manifest-owned files. Scientific NPY inputs remained usable and unchanged.
Neither synthetic session establishes arbitrary concurrent GUI editing safety.

Earlier failures remain evidence: the initial opened-path refusal and a legacy
GMS Python unit getter returning `1/?` where the native path reported `1/Å`.
That earlier session was interrupted by a computer restart; its unfinished
checks are not reclassified by the new session. ASCII-unit qualification does
not resolve the Unicode discrepancy. Broader import qualification, including
Unicode units and other dtypes, stays on HOLD. The historical interrupted trial
is not retroactively completed by the later scoped tests.

## Captured calibration in external analysis

`image_open(source_kind:"capture")` now activates internally validated native
READ/schema-1 axes through the existing versioned `image_calibrate` record.
`image_measure`, scale bars and saved-FFT physical axes share that record, so a
supported native scale does not need to be re-entered. Signed/unequal axes,
recognized mixed units and crop offsets are preserved with original provenance.
Real-space lengths and reciprocal-space frequencies stay separate; d-spacing
requires explicit DC identity. Unknown or conflicting calibration leaves pixel
exploration available. Malformed receipts or changed hashes still fail capture
import. See [calibration admission and revisions](NATIVE_CALIBRATION_HANDOFF.md).

An actual-host synthetic crop/native-processing/READ/external-measurement trial
checked inherited physical geometry before returning a new work image. Later
DM edits require a fresh capture and active record, not reuse of the immutable
old input. User corrections/withdrawals retain the native record and old
versions; updating saved-FFT physical axes does not recompute complex values.
This validates the recorded handoff, not the metrological truth of DM metadata.

Offline fakes and scientific NPY checks do not establish real DM behavior.
Live native readback, independent host-array/oracle checks, document display,
STOP/reference ownership and real researcher editing must be reported separately.
Data in a DM document remains editable by the researcher; recapture afterwards
rather than reuse an immutable old snapshot. Original experimental data must not
be used for candidate writes or uploaded in validation evidence.
