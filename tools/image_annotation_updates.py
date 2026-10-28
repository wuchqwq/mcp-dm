"""Plan sparse edits to saved annotations; never alter arrays or parent records.

The existing annotation validator/renderer remains authoritative for geometry,
style ranges and scientific coordinate domains. Each result is (item, reproject).
"""
from copy import deepcopy
import re

_ID = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
_EDITABLE = frozenset(("coordinates", "text", "note", "status", "color",
                       "line_width", "arrowhead_size", "arrow_length", "presentation"))
_INPUT_FIELDS = frozenset(("kind", "coordinates", "text", "note", "status",
                           "color", "line_width", "arrowhead_size", "arrow_length",
                           "annotation_id", "coordinate_space", "source_object_id", "presentation"))


class AnnotationUpdateError(ValueError):
    code = "INVALID_ANNOTATION_UPDATE"


def _require(condition, message):
    if not condition:
        raise AnnotationUpdateError(message)


def _as_input(mark):
    """Discard derived PNG fields; preserve old pre-cap arrow semantics."""
    item = {key: deepcopy(value) for key, value in mark.items() if key in _INPUT_FIELDS}
    if mark.get("kind") == "arrow" and "arrow_length" not in mark:
        item["arrow_length"] = None
    return item


def plan_annotation_updates(saved, updates):
    """Edit existing stable IDs, preserving order and omitted/anonymous marks.

    Coordinates are in the saved anchor's coordinate system, not the current
    PNG or shortened arrow tail. A move is validated as new geometry against
    the current panel. Unmoved anchors may remain outside the current view.
    Legacy unanchored marks permit style/text/status edits, not coordinate edits.
    Retraction uses status='retracted'; this never deletes history or promotes
    a hypothesis implicitly. Adding marks still uses the replacement interface.
    """
    _require(type(saved) is list and len(saved) <= 128, "Invalid saved annotation list")
    _require(type(updates) is list and 1 <= len(updates) <= 100,
             "updates must contain 1..100 edits; use annotations:[] to clear all marks")
    indexed = {}
    for mark in saved:
        _require(type(mark) is dict, "Invalid saved annotation record")
        ident = mark.get("annotation_id")
        if ident is not None:
            _require(type(ident) is str and _ID.fullmatch(ident), "Invalid saved annotation_id")
            _require(ident not in indexed, "Ambiguous duplicate saved annotation_id")
            indexed[ident] = mark
    edits = {}
    for edit in updates:
        _require(type(edit) is dict and set(edit) <= _EDITABLE | {"annotation_id", "presentation_replace"},
                 "An update cannot change kind, source, coordinate domain or derived fields")
        _require("presentation_replace" not in edit or type(edit["presentation_replace"]) is bool and "presentation" in edit,
                 "presentation_replace must be an explicit boolean with presentation metadata")
        ident = edit.get("annotation_id")
        _require(type(ident) is str and _ID.fullmatch(ident), "Every update requires a stable annotation_id")
        _require(ident in indexed, "Unknown annotation_id; inspect this exact view before editing")
        _require(ident not in edits, "Duplicate annotation_id in one updates request")
        _require(len(edit) > 1, "An update must explicitly change at least one field")
        _require("coordinates" not in edit or indexed[ident].get("anchor") is not None,
                 "Coordinate edits require a unique saved anchor; replace an unanchored mark explicitly")
        edits[ident] = edit
    planned = []
    for mark in saved:
        edit = edits.get(mark.get("annotation_id"), {})
        changes = {key: deepcopy(value) for key, value in edit.items() if key not in ("annotation_id", "presentation_replace")}
        if isinstance(changes.get("presentation"), dict) and not edit.get("presentation_replace", False):
            # A label adjustment is a sparse display patch, never a new anchor.
            # Omitted presentation and label fields remain unchanged just like
            # the existing top-level style/text fields.
            old = mark.get("presentation", {})
            merged = {**deepcopy(old), **changes["presentation"]}
            if isinstance(changes["presentation"].get("label"), dict):
                merged["label"] = {**deepcopy(old.get("label", {})), **changes["presentation"]["label"]}
            changes["presentation"] = merged
        anchor = mark.get("anchor")
        if "coordinates" in changes:
            # Reuse the stable source/domain, never the displayed short shaft.
            item = _as_input(mark)
            item.update(deepcopy(anchor))
            item.update(changes)
            planned.append((item, False))
        elif anchor is not None:
            item = deepcopy(mark)
            item.update(changes)
            planned.append((item, True))
        else:
            # The same render base is used by the caller, so legacy PNG marks
            # can be retained without inventing a cross-panel source anchor.
            item = _as_input(mark)
            item.update(changes)
            planned.append((item, False))
    return planned
