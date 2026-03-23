from __future__ import annotations

import json
from typing import Any

from backend.schemas.extraction import ExtractionResult


def parse_template_fields(fields_json: str) -> list[dict]:
    """Deserialise fields_json string → list of {field_path, display_name, include} dicts."""
    return json.loads(fields_json)


def _get_anchor_value(result: ExtractionResult, key: str) -> Any:
    """Read a value from result.anchor, supporting both dataclass attributes and dict-like access."""
    anchor = result.anchor
    if isinstance(anchor, dict):
        return anchor.get(key)
    return getattr(anchor, key, None)


def _get_discovered_value(result: ExtractionResult, key: str) -> Any:
    """Read a value from result.discovered dict."""
    return result.discovered.get(key)


def filter_extraction_by_template(
    result: ExtractionResult,
    template_fields: list[dict],
) -> dict[str, Any]:
    """
    Returns flat dict {display_name: value} for all fields where include=True.

    field_path navigation:
    - "anchor.X"     → reads from result.anchor for attribute/key X
    - "discovered.X" → reads from result.discovered dict for key X
    - "lines"        → returns result.discovered.get("line_items")

    Returns empty dict if template_fields is empty or all include=False.
    """
    output: dict[str, Any] = {}

    for field in template_fields:
        if not field.get("include", False):
            continue

        field_path: str = field["field_path"]
        display_name: str = field["display_name"]

        if field_path == "lines":
            value = result.discovered.get("line_items")
        elif "." in field_path:
            section, _, key = field_path.partition(".")
            if section == "anchor":
                value = _get_anchor_value(result, key)
            elif section == "discovered":
                value = _get_discovered_value(result, key)
            else:
                value = None
        else:
            value = None

        output[display_name] = value

    return output
