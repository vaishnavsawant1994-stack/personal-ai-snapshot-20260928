from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


class ContractValidationError(ValueError):
    """Raised when a provider/tool value violates its declared contract."""


def _type_matches(value: Any, expected: str) -> bool:
    expected = str(expected).strip().lower()
    if expected == "object":
        return isinstance(value, Mapping)
    if expected == "array":
        return isinstance(value, (list, tuple))
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    raise ContractValidationError(f"unsupported contract type: {expected}")


def validate_contract(value: Any, schema: Mapping[str, Any] | None, *, label: str = "value", path: str = "$", depth: int = 0) -> Any:
    """Validate a bounded JSON-Schema-like contract without a runtime dependency.

    Supported keywords are intentionally small and deterministic: type, enum,
    required, properties, additionalProperties, items, minItems, maxItems,
    minLength, maxLength, minimum and maximum. Unknown keywords are ignored so
    manifests can evolve without weakening the checks implemented here.
    """

    if schema is None:
        return value
    if not isinstance(schema, Mapping):
        raise ContractValidationError(f"{label} contract must be an object")
    if depth > 12:
        raise ContractValidationError(f"{label} contract nesting exceeds limit")

    expected = schema.get("type")
    if expected is not None:
        choices = [expected] if isinstance(expected, str) else list(expected) if isinstance(expected, Sequence) else []
        if not choices or not any(_type_matches(value, item) for item in choices):
            raise ContractValidationError(f"{label} at {path} must match type {expected}")

    if "enum" in schema:
        allowed = schema.get("enum")
        if not isinstance(allowed, Sequence) or isinstance(allowed, (str, bytes)):
            raise ContractValidationError(f"{label} enum contract is invalid")
        if value not in allowed:
            raise ContractValidationError(f"{label} at {path} is outside the allowed enum")

    if isinstance(value, Mapping):
        required = schema.get("required") or ()
        if not isinstance(required, Sequence) or isinstance(required, (str, bytes)):
            raise ContractValidationError(f"{label} required contract is invalid")
        missing = [str(key) for key in required if key not in value]
        if missing:
            raise ContractValidationError(f"{label} at {path} is missing required fields: {', '.join(missing)}")
        properties = schema.get("properties") or {}
        if not isinstance(properties, Mapping):
            raise ContractValidationError(f"{label} properties contract is invalid")
        if schema.get("additionalProperties") is False:
            unknown = [str(key) for key in value if key not in properties]
            if unknown:
                raise ContractValidationError(f"{label} at {path} contains unknown fields: {', '.join(sorted(unknown))}")
        for key, child_schema in properties.items():
            if key in value:
                validate_contract(value[key], child_schema, label=label, path=f"{path}.{key}", depth=depth + 1)

    if isinstance(value, (list, tuple)):
        minimum = schema.get("minItems")
        maximum = schema.get("maxItems")
        if minimum is not None and len(value) < int(minimum):
            raise ContractValidationError(f"{label} at {path} has too few items")
        if maximum is not None and len(value) > int(maximum):
            raise ContractValidationError(f"{label} at {path} has too many items")
        item_schema = schema.get("items")
        if item_schema is not None:
            for index, item in enumerate(value):
                validate_contract(item, item_schema, label=label, path=f"{path}[{index}]", depth=depth + 1)

    if isinstance(value, str):
        minimum = schema.get("minLength")
        maximum = schema.get("maxLength")
        if minimum is not None and len(value) < int(minimum):
            raise ContractValidationError(f"{label} at {path} is shorter than allowed")
        if maximum is not None and len(value) > int(maximum):
            raise ContractValidationError(f"{label} at {path} is longer than allowed")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if minimum is not None and value < minimum:
            raise ContractValidationError(f"{label} at {path} is below minimum")
        if maximum is not None and value > maximum:
            raise ContractValidationError(f"{label} at {path} is above maximum")

    return value
