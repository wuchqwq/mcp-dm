# Structure display directions and owned helper lifecycle

The optional local 3Dmol view is a presentation of fixed ASE structure data.
It does not edit atomic positions, simulation parameters or files, and does not
contact DM. Existing geometric-neighbor display limits still apply.

## Incomplete cells

A structure may have one or two valid periodic directions without a complete
three-dimensional cell. The viewer requires only that the declared periodic
vectors are actual, nonzero and independent. It displays those vectors using
the component's [arrow API](https://3dmol.org/doc/GLViewer.html#addArrow), without
inventing a missing third vector or drawing a fictitious volume. Cell-free XYZ
remains viewable. This does not grant periodic simulation or reciprocal-metric
operations that require a full-rank cell.

## Initial observation direction

`structure_view(orientation_id:...)` uses the same saved orientation as the
simulation. The viewer client checks that the orientation belongs to the exact
source structure and is a finite, right-handed orthonormal matrix. It applies
`v_display = v_source @ R.T` to a separate display copy of atom positions and
cell vectors. The original source coordinates remain fixed and hash-bound.
The default view is x right, y up, observing from +z toward the origin.
`viewer_initial_orientation` and the page's status say whether the orientation
was applied. Subsequent mouse rotation changes only the camera.

The legacy ASE projection's nonzero `rotation_deg_xyz` is not automatically
translated into a 3Dmol camera convention. Such an interactive view explicitly
reports that the requested legacy rotation was **not applied**. Use a shared
orientation record when the initial direction must agree with simulation.
Scientific reciprocal coordinates and a raster's downward image-y convention
must still be distinguished; viewing does not silently flip simulation data.

## Reuse and closure

Different saved view wrappers reuse one helper when their source structure,
typed display snapshot, orientation and renderer asset agree. The result keeps
the requested view ID and separately reports `viewer_owner_view_object_id`.
The immutable source snapshots and each view's launch identity remain distinct.

Use `structure_viewer_close` with an exact saved **view object ID**, not a source
structure ID, and a request ID saved before submission:

```json
{"object_id":"<saved-view-object-id>","request_id":"close-view-1"}
```

Closing a shared helper affects every alias listed in
`affected_view_object_ids`. It does not close DM, delete scientific files or
change a model. The tool uses a bounded token-authenticated, same-origin local
close request; it does not kill a PID. Completion requires the helper's exact
closure record, its process to be absent, and its loopback port to refuse a
connection. A `closing` acknowledgement alone is not success.

The close-request namespace is explicitly separate from Python scientific
requests. Recover by calling **`structure_viewer_close` with the same original
request ID and object ID**, rather than `structure_result`. A repeated call only
queries its recorded operation and never sends the close again. Different
arguments with the same ID are refused. Missing closure evidence or an alive
process/port remains unknown; another operation's receipt cannot qualify it.

An old view ID always refers to its original helper, even after it stops. The
client never automatically relaunches an uncertain or stopped old view. After
a shutdown has been independently confirmed, a **new explicit view request** may
start a new generation; old aliases and receipts remain historical. Generation
lookup is bounded and fails explicitly instead of rewriting old launch records.

Transport and component doubles do not prove WebGL rendering. Actual browser
direction, camera and display checks must be reported separately from stdio
MCP, file, process and HTTP lifecycle checks.
