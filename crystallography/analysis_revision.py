"""Bind a comparison to an explicitly selected image revision, not global state.

This is metadata over existing immutable objects/journals. It does not schedule
tools, discover a front image, choose peaks or maintain a second current-state
database. Historical comparison remains an explicit, separate operation.
"""
from pathlib import Path

from crystallography.reflection_compare import ComparisonError, canonical
from tools.image_calibration import dependency


def require(condition, message):
    if not condition:
        raise ComparisonError(message)


def bind_geometry(measurements, sources, current_image_object_id=None,
                  mode="standalone_snapshot"):
    require(mode in ("continue_current", "historical_review", "standalone_snapshot"),
            "Unknown comparison analysis_mode")
    if mode != "continue_current":
        require(current_image_object_id is None,
                "Historical/standalone snapshots cannot claim a current image revision")
        return {"analysis_mode": mode, "current_geometry_checked": False,
                "semantics": "Explicit saved measurements only; no claim of observing or continuing a current image"}
    require(type(current_image_object_id) is str,
            "Continuing requires the explicitly selected current_image_object_id")
    roots = {str(Path(source["journal_path"]).parent.parent.resolve()) for source in sources}
    require(len(roots) == 1, "Current analysis requires one explicit image workspace")
    # Optional image dependencies belong in the external structure environment.
    # Import lazily so historical structure-only operations remain compatible.
    from tools.image_workspace import Workspace
    workspace = Workspace(next(iter(roots)), writable=False)
    parent, _, _ = workspace.measurement_operand(current_image_object_id)
    grid = workspace.measurement_grid_identity(current_image_object_id)
    record = parent.get("xy_calibration")
    require(type(record) is dict and record.get("status") == "active",
            "Current physical comparison requires active selected calibration; pixel observation remains available")
    for measurement in measurements:
        original_parent = measurement.get("parent_object_id")
        require(workspace.measurement_grid_identity(original_parent) == grid,
                "Measurement belongs to a different capture/frame/ROI/FFT; create a fresh matching measurement")
        require(canonical(measurement.get("xy_calibration")) == canonical(record) and
                measurement.get("calibration_dependency") == dependency(record),
                "Measurement uses a different centre/scale revision; image_remeasure before continuing current analysis")
        saved_grid = measurement.get("scientific_grid_identity")
        require(saved_grid is None or saved_grid == grid,
                "Saved measurement scientific grid contradicts its original image")
    return {"analysis_mode": mode, "current_geometry_checked": True,
            "current_image_object_id": current_image_object_id,
            "resolved_image_object_id": parent["object_id"],
            "scientific_grid_identity": grid,
            "calibration_dependency": dependency(record),
            "centre_revision_id": record.get("centre_revision_id"),
            "semantics": "Current means this explicitly selected immutable image/calibration revision, not global latest/front state; DM changes require a new capture"}


def comparison_revision(ident, previous, binding, observations, simulation_id,
                        source_change_basis=None):
    if previous is None:
        require(source_change_basis is None, "source_change_basis requires a previous comparison")
        return {"analysis_root_id": ident, "analysis_revision": 1,
                "previous_comparison_id": None, "analysis_binding": binding,
                "history_preserved": True}
    require(previous.get("kind") == "compare", "previous_comparison_id must be a committed comparison")
    require(binding["analysis_mode"] in ("continue_current", "historical_review"),
            "Choose continue_current or historical_review explicitly when linking an earlier comparison")
    old_grid = previous.get("analysis_binding", {}).get("scientific_grid_identity")
    new_grid = binding.get("scientific_grid_identity")
    old_sources = {row.get("source_object_id") for row in previous.get("observations", [])}
    new_sources = {row.get("source_object_id") for row in observations}
    changed_source = (old_grid != new_grid if old_grid and new_grid else old_sources != new_sources)
    if changed_source and binding["analysis_mode"] == "continue_current":
        require(type(source_change_basis) is str and 0 < len(source_change_basis.strip()) <= 2000,
                "A new capture/frame/ROI requires explicit source_change_basis, never silently transferred point identity")
    elif source_change_basis is not None:
        require(type(source_change_basis) is str and 0 < len(source_change_basis.strip()) <= 2000,
                "source_change_basis must be an explicit bounded statement")
    old_deps = [row.get("calibration_dependency") for row in previous.get("observations", [])]
    new_deps = [row.get("calibration_dependency") for row in observations]
    old_points = [row.get("original_points") for row in previous.get("observations", [])]
    new_points = [row.get("original_points") for row in observations]
    old_revision = previous.get("analysis_revision", 1)
    require(type(old_revision) is int and 1 <= old_revision < 10000, "Comparison revision exceeds budget")
    return {"analysis_root_id": previous.get("analysis_root_id", previous["object_id"]),
            "analysis_revision": old_revision + 1, "previous_comparison_id": previous["object_id"],
            "analysis_binding": binding, "history_preserved": True,
            "revision_changes": {"source_changed": changed_source,
                                 "calibration_or_centre_changed": old_deps != new_deps,
                                 "measurement_points_changed": old_points != new_points,
                                 "reference_simulation_changed": previous.get("simulation_object_id") != simulation_id},
            "source_change_basis": source_change_basis,
            "unchanged_scientific_array_reused": bool(old_grid and old_grid == new_grid),
            "new_fft_computed_by_comparison": False}
