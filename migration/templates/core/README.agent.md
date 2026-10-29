# Agent guide: independent microscopy science

Use this provider on Windows, macOS or Linux without DM/GMS or the old repository.
Start with [client setup](docs/CLIENT_SETUP.md). Discover the actual `image_*`,
optional `structure_*` and context tools from this connection. Missing optional
modules are not permission to call a peer DM provider or invent a capability.

The [no-model inspector](docs/RESEARCHER_DATA_INSPECTOR.md) uses the same saved
arrays and measurement records. [Numerical inspection](docs/IMAGE_NUMERIC_INSPECTION.md)
reads original values, not preview brightness. Keep coordinates, signed XY
calibration, frame/ROI and FFT ancestry explicit; unknown scale stays pixel-based.
Save original request IDs before scientific writes and query original outcomes
after timeout. Preserve data and existing user/client settings.

[Panel usage](docs/LOCAL_IMAGE_PANEL.md), [annotation contracts](docs/IMAGE_ANNOTATIONS.md)
and [reflection comparison](docs/REFLECTION_COMPARISON.md) describe the retained
scientific behavior. Older copied technical examples mentioning `DM_IMAGE_*`
refer to the pre-split combined checkout; for this package use the `MICROSCOPY_*`
configuration in client setup. Do not install GMS to satisfy those old examples.

Skills are optional user-installed directories. Copy a whole selected Skill
with its scripts and references, refusing overwrite. They do not establish that
an external Materials Project provider is connected. Do not install dependencies
or alter approval settings without explicit authorization.

DM is a separately registered peer MCP. Its native failures do not trigger a
hidden fallback. Imported saved captures are read-only scientific file transfer,
not a live host connection. New repository naming does not justify renaming old
request IDs, manifests, stored schemas or calibration records.
