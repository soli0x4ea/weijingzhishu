"""DLC Protocol v1.0 — Schema Validator.

P0-15: jsonschema-based validation engine.

Validates card.json and individual module configs against JSON Schemas.
Uses local $ref resolution — all schemas live in dlc/schemas/.
"""
from __future__ import annotations

import json, os
from typing import Any


# Cache: { schema_id: loaded_schema }
_SCHEMA_CACHE = {}
_SCHEMA_DIR = os.path.join(os.path.dirname(__file__), "schemas")


def _load_schema(schema_ref: str) -> dict:
    """Load a JSON Schema file, with caching."""
    if schema_ref in _SCHEMA_CACHE:
        return _SCHEMA_CACHE[schema_ref]

    filename = os.path.basename(schema_ref)
    path = os.path.join(_SCHEMA_DIR, filename)

    if not os.path.isfile(path):
        return {"type": "object"}

    with open(path, "r", encoding="utf-8") as f:
        schema = json.load(f)

    _SCHEMA_CACHE[schema_ref] = schema
    return schema


def _format_jsonschema_error(err: Any) -> str:
    """Format a jsonschema ValidationError into a readable string."""
    path = ".".join(str(p) for p in err.absolute_path) if err.absolute_path else "(root)"
    return f"{path}: {err.message}"


def _resolve_refs(schema: dict) -> dict:
    """Walk schema tree and resolve local $ref pointers.

    Replaces { "$ref": "identity.schema.json" } with the loaded
    contents of identity.schema.json. Only resolves local refs
    (non-http, relative filenames).
    """
    if isinstance(schema, dict):
        if "$ref" in schema and isinstance(schema["$ref"], str):
            ref = schema["$ref"]
            if not ref.startswith("http"):
                return _load_schema(ref)
        return {k: _resolve_refs(v) for k, v in schema.items()}
    elif isinstance(schema, list):
        return [_resolve_refs(item) for item in schema]
    return schema


def validate_card(card: dict, schema_id: str = "card.schema.json") -> list[str]:
    """Validate a card.json against its JSON Schema.

    Resolves local $ref pointers in the schema, then validates.

    Args:
        card: Parsed card.json as a dict.
        schema_id: Schema file name (default: card.schema.json).

    Returns:
        List of error messages (empty = valid).
    """
    try:
        import jsonschema
    except ImportError:
        return ["jsonschema library not installed — cannot validate"]

    schema = _load_schema(schema_id)

    # Validate the schema itself is well-formed
    from jsonschema.validators import validator_for
    cls = validator_for(schema)
    try:
        cls.check_schema(schema)
    except jsonschema.SchemaError as e:
        return [f"Schema error: {e.message}"]

    # Resolve local $ref in the schema tree
    resolved = _resolve_refs(schema)

    # Validate
    validator = jsonschema.Draft202012Validator(resolved)
    errors = list(validator.iter_errors(card))

    if not errors:
        return []

    return [_format_jsonschema_error(e) for e in errors]


def validate_module(data: dict, schema_id: str) -> list[str]:
    """Validate a single module config against its schema.

    Args:
        data: Module config as a dict.
        schema_id: Schema file name (e.g. "identity.schema.json").

    Returns:
        List of error messages (empty = valid).
    """
    return validate_card(data, schema_id=schema_id)
