"""Safe normalization and merging for Prompt Studio advanced-field overrides."""
from __future__ import annotations

import json


_MAIN_UI_FIELD_IDS = frozenset({
    "positive_general_lakis_external",
    "positive_general_lakis_external_base",
    "positive_general_lakis_external_fixed",
    "positive_quality_lakis_external",
    "positive_artist_lakis_external",
    "positive_trigger_lakis_external",
    "negative_general_lakis_external",
    "negative_general_lakis_external_fixed",
    "negative_quality_lakis_external",
    "negative_artist_lakis_external",
    "positive_general_kr_camera_bridge",
})
_MAIN_UI_PANES = frozenset({"positive", "negative"})
_MAIN_UI_TYPES = frozenset({"general", "fixed", "quality", "artist", "trigger"})


def _reject_constant(value):
    raise ValueError(f"Invalid JSON constant: {value}")


def _parse_fields(serialized):
    if not isinstance(serialized, str):
        raise ValueError("advanced_fields must be a JSON string")
    try:
        fields = json.loads(serialized, parse_constant=_reject_constant)
    except (json.JSONDecodeError, RecursionError) as error:
        raise ValueError("advanced_fields must be a JSON array of objects") from error
    if not isinstance(fields, list):
        raise ValueError("advanced_fields must be a JSON array of objects")
    for item in fields:
        if not isinstance(item, dict):
            raise ValueError("advanced_fields entries must be objects")
        field_id = item.get("id")
        if not isinstance(field_id, str) or not field_id.strip():
            raise ValueError("advanced_fields entries must have a nonempty string id")
    return fields


def _is_main_ui_owned(item):
    if item["id"] in _MAIN_UI_FIELD_IDS:
        return True
    return (
        item.get("pane") in _MAIN_UI_PANES
        and item.get("type") in _MAIN_UI_TYPES
    )


def _normalized_fields(serialized):
    return [item for item in _parse_fields(serialized) if not _is_main_ui_owned(item)]


def _canonical_json(fields):
    return json.dumps(fields, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def normalize_override(serialized) -> str | None:
    """Remove Main-UI-owned fields and serialize the remaining editable fields."""
    fields = _normalized_fields(serialized)
    return _canonical_json(fields) if fields else None


def merge_override(current_serialized, requested_serialized) -> str:
    """Merge editable requested fields into current fields without replacing UI-owned data."""
    current = _parse_fields(current_serialized)
    normalized_requested = normalize_override(requested_serialized)
    requested = [] if normalized_requested is None else _parse_fields(normalized_requested)

    merged = [dict(item) for item in current]
    protected_ids = {item["id"] for item in current if _is_main_ui_owned(item)}
    editable_indices = {}
    for index, item in enumerate(merged):
        if item["id"] not in protected_ids:
            editable_indices.setdefault(item["id"], []).append(index)

    for item in requested:
        field_id = item["id"]
        if field_id in protected_ids:
            continue
        indices = editable_indices.get(field_id)
        if indices:
            for index in indices:
                merged[index] = {**merged[index], **item}
        else:
            editable_indices[field_id] = [len(merged)]
            merged.append(dict(item))

    return _canonical_json(merged)
