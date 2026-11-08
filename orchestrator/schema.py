"""Tiny JSON-Schema subset validator (type, required, properties, enum, items,
pattern, minimum, additionalProperties=false, $ref to #/definitions).

Keeps the runtime dependency-free; tests cross-check it against the reference
`jsonschema` implementation.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

SCHEMAS = Path(__file__).parent / "schemas"
_TYPES = {"object": dict, "array": list, "string": str, "integer": int, "number": (int, float), "boolean": bool, "null": type(None)}


def load(name: str) -> dict:
    return json.loads((SCHEMAS / f"{name}.schema.json").read_text(encoding="utf-8"))


def validate(instance: Any, schema: dict, path: str = "$", root: dict | None = None) -> list[str]:
    root = root or schema
    if "$ref" in schema:
        ref = schema["$ref"].removeprefix("#/definitions/")
        return validate(instance, root["definitions"][ref], path, root)
    errors: list[str] = []
    t = schema.get("type")
    if t:
        types = t if isinstance(t, list) else [t]
        ok = any(isinstance(instance, _TYPES[x]) and not (x in ("integer", "number") and isinstance(instance, bool)) for x in types)
        if not ok:
            return [f"{path}: expected {t}, got {type(instance).__name__}"]
    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: {instance!r} not in {schema['enum']}")
    if isinstance(instance, str) and "pattern" in schema and not re.search(schema["pattern"], instance):
        errors.append(f"{path}: {instance!r} does not match {schema['pattern']}")
    if isinstance(instance, (int, float)) and "minimum" in schema and instance < schema["minimum"]:
        errors.append(f"{path}: {instance} < {schema['minimum']}")
    if isinstance(instance, dict):
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"{path}: missing required '{key}'")
        props = schema.get("properties", {})
        for key, val in instance.items():
            if key in props:
                errors += validate(val, props[key], f"{path}.{key}", root)
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}: unexpected property '{key}'")
            elif isinstance(schema.get("additionalProperties"), dict):
                errors += validate(val, schema["additionalProperties"], f"{path}.{key}", root)
    if isinstance(instance, list) and "items" in schema:
        for i, item in enumerate(instance):
            errors += validate(item, schema["items"], f"{path}[{i}]", root)
    return errors
