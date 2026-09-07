"""Pure Draft 2020-12 validation for canonical gold records."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

try:
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover - exercised by the dependency failure path
    Draft202012Validator = None


@dataclass(frozen=True)
class SchemaValidationIssue:
    path: tuple[Any, ...]
    message: str


def _schema_path(path: Any) -> str:
    parts: list[str] = []
    for part in path:
        parts.append(f"[{part}]" if isinstance(part, int) else f".{part}")
    return "".join(parts) or ".<record>"


@lru_cache(maxsize=4)
def _canonical_schema_validator(schema_path_value: str | None = None) -> Any:
    if Draft202012Validator is None:
        raise RuntimeError("jsonschema dependency is required for canonical validation")
    schema_path = (
        Path(schema_path_value)
        if schema_path_value
        else Path(__file__).resolve().parents[1] / "schemas" / "gold_annotation.schema.json"
    )
    with schema_path.open(encoding="utf-8") as handle:
        schema_document = json.load(handle)
    validator = Draft202012Validator(schema_document)
    validator.check_schema(schema_document)
    return validator


def canonical_schema_required_fields(schema_path: Path | None = None) -> frozenset[str]:
    """Return the required root fields declared by the canonical schema."""
    validator = _canonical_schema_validator(str(schema_path) if schema_path else None)
    return frozenset(validator.schema.get("required", ()))


def canonical_schema_issues(
    record: Any,
    schema_path: Path | None = None,
) -> list[SchemaValidationIssue]:
    """Return pure JSON-Schema validation issues for one canonical record."""
    try:
        validator = _canonical_schema_validator(str(schema_path) if schema_path else None)
    except (OSError, json.JSONDecodeError, RuntimeError, TypeError) as error:
        return [SchemaValidationIssue((), f"schema engine unavailable: {error}")]
    return [
        SchemaValidationIssue(tuple(schema_error.path), schema_error.message)
        for schema_error in sorted(validator.iter_errors(record), key=lambda item: list(item.path))
    ]


def canonical_schema_issue_text(issue: SchemaValidationIssue) -> str:
    """Format one issue without adding non-schema validation semantics."""
    return f"{_schema_path(issue.path)}: {issue.message}"
