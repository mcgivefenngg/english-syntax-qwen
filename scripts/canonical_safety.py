"""Narrow canonical-record admission checks shared by authoritative consumers."""

from __future__ import annotations

import re
from typing import Any

try:
    from data_common import ANNOTATION_COVERAGES, CANONICAL_SCHEMA_VERSION
except ImportError:
    from scripts.data_common import ANNOTATION_COVERAGES, CANONICAL_SCHEMA_VERSION


CANONICAL_REQUIRED_FIELDS = frozenset({
    "schema_version", "id", "sentence", "capability_tags", "difficulty", "source_type",
    "framework", "sentence_type", "annotation_scope", "clauses", "constituents", "words",
    "dependencies", "explanation", "split",
})
_CANONICAL_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_CANONICAL_COLLECTIONS = ("clauses", "constituents", "words", "dependencies")
_ANNOTATION_SCOPE_FIELDS = frozenset({
    "coverage", "annotated_dimensions", "intentionally_omitted", "dimensions", "notes",
})


def canonical_record_safety_issues(record: Any) -> list[str]:
    """Return record-level issues that block authoritative coverage resolution."""
    if not isinstance(record, dict):
        return ["coverage record must be an object"]

    issues: list[str] = []
    missing = sorted(CANONICAL_REQUIRED_FIELDS - record.keys())
    if missing:
        issues.append(f"missing required canonical field {missing[0]!r}")

    if record.get("schema_version") != CANONICAL_SCHEMA_VERSION:
        issues.append("coverage resolution requires a canonical V0.4 record")

    record_id = record.get("id")
    if not isinstance(record_id, str) or not record_id:
        issues.append("canonical record id must be a non-empty string")
    elif _CANONICAL_ID_PATTERN.fullmatch(record_id) is None:
        issues.append(f"canonical record id {record_id!r} has invalid format")

    annotation_scope = record.get("annotation_scope")
    if not isinstance(annotation_scope, dict):
        issues.append("annotation_scope must be an object")
    else:
        unknown_fields = set(annotation_scope) - _ANNOTATION_SCOPE_FIELDS
        if unknown_fields:
            issues.append(f"annotation_scope contains unknown fields: {sorted(unknown_fields)!r}")
        coverage = annotation_scope.get("coverage")
        if coverage not in ANNOTATION_COVERAGES:
            issues.append("annotation_scope.coverage must be complete_constituency or task_focused_partial")
        dimensions = annotation_scope.get("dimensions")
        if not isinstance(dimensions, list) or not dimensions:
            issues.append("annotation_scope.dimensions must be a non-empty list")

    for field in _CANONICAL_COLLECTIONS:
        value = record.get(field)
        if not isinstance(value, list):
            issues.append(f"canonical field {field!r} must be an array")
    words = record.get("words")
    if isinstance(words, list) and not words:
        issues.append("canonical field 'words' must be a non-empty array")

    if record.get("schema_version") == CANONICAL_SCHEMA_VERSION:
        canonical_analysis = record.get("canonical_analysis")
        if not isinstance(canonical_analysis, dict):
            issues.append("canonical V0.4 record requires an object 'canonical_analysis'")
        if "preferred_analysis" in record:
            issues.append("canonical V0.4 record cannot contain 'preferred_analysis'")

    return issues
