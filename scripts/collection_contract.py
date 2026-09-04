"""Shared V0.4 collection ownership and predicate-reference rules."""

from __future__ import annotations

from typing import Any

try:
    from dimension_registry import dimension_spec
except ImportError:
    from scripts.dimension_registry import dimension_spec


def _word_ids(record: dict[str, Any]) -> tuple[str, ...]:
    values = record.get("words", [])
    if not isinstance(values, list):
        return ()
    return tuple(
        word["id"]
        for word in values
        if isinstance(word, dict) and isinstance(word.get("id"), str) and word["id"]
    )


def _word_ids_by_field(record: dict[str, Any], field: str) -> dict[str, tuple[str, ...]]:
    values = record.get("words", [])
    if not isinstance(values, list):
        return {}
    matches: dict[str, list[str]] = {}
    for word in values:
        if not isinstance(word, dict):
            continue
        identifier = word.get("id")
        value = word.get(field)
        if isinstance(identifier, str) and identifier and isinstance(value, str) and value:
            matches.setdefault(value, []).append(identifier)
    return {value: tuple(identifiers) for value, identifiers in matches.items()}


def normalize_predicate_reference(record: dict[str, Any], reference: Any) -> str | None:
    """Return an explicit word ID for an ID or uniquely matching legacy lemma."""
    if not isinstance(reference, str) or not reference:
        return None
    word_ids = set(_word_ids(record))
    if reference in word_ids:
        return reference
    lemma_matches = _word_ids_by_field(record, "lemma").get(reference, ())
    if lemma_matches:
        if len(lemma_matches) == 1:
            return lemma_matches[0]
        return None
    form_matches = _word_ids_by_field(record, "form").get(reference, ())
    if len(form_matches) == 1:
        return form_matches[0]
    return None


def predicate_reference_issue(record: dict[str, Any], reference: Any, label: str) -> str | None:
    if not isinstance(reference, str) or not reference:
        return f"{label} must be a non-empty word ID or lemma"
    word_ids = set(_word_ids(record))
    if reference in word_ids:
        return None
    lemma_matches = _word_ids_by_field(record, "lemma").get(reference, ())
    if len(lemma_matches) == 1:
        return None
    if len(lemma_matches) > 1:
        return f"{label} lemma {reference!r} maps to multiple word IDs; use an explicit word ID"
    form_matches = _word_ids_by_field(record, "form").get(reference, ())
    if len(form_matches) == 1:
        return None
    if len(form_matches) > 1:
        return f"{label} surface form {reference!r} maps to multiple word IDs; use an explicit word ID"
    return f"{label} must reference a known word ID or a unique word lemma/surface form"


def collection_target_ids(record: dict[str, Any], dimension: str, item: Any) -> tuple[str, ...]:
    """Return only coverage owners, never relation endpoints or selected content."""
    if not isinstance(item, dict):
        return ()
    spec = dimension_spec(dimension)
    if spec is None:
        return ()
    if spec.allowed_scope_kinds == frozenset({"record"}):
        return ()
    if spec.target_lemma_field:
        target = normalize_predicate_reference(record, item.get(spec.target_lemma_field))
        return (target,) if target is not None else ()
    return tuple(
        item[field]
        for field in spec.target_fields
        if isinstance(item.get(field), str) and item[field]
    )


def collection_item_in_scope(
    record: dict[str, Any],
    dimension: str,
    item: Any,
    scope: Any,
) -> bool:
    """Return whether a collection item has a deterministic owner in scope."""
    if not isinstance(scope, dict):
        return False
    scope_kind = scope.get("kind")
    if scope_kind == "record":
        return True
    targets = collection_target_ids(record, dimension, item)
    if scope_kind == "node":
        return isinstance(scope.get("node"), str) and scope["node"] in targets
    if scope_kind != "region":
        return False
    start, end = scope.get("start"), scope.get("end")
    if type(start) is not int or type(end) is not int:
        return False
    words = record.get("words", [])
    word_spans = {
        word.get("id"): (index, index + 1)
        for index, word in enumerate(words)
        if isinstance(word, dict) and isinstance(word.get("id"), str)
    } if isinstance(words, list) else {}
    objects: dict[str, dict[str, Any]] = {}
    for field in ("constituents", "clauses"):
        values = record.get(field, [])
        if not isinstance(values, list):
            continue
        objects.update({
            value["id"]: value
            for value in values
            if isinstance(value, dict) and isinstance(value.get("id"), str)
        })
    for target in targets:
        target_span = word_spans.get(target)
        if target_span is None:
            value = objects.get(target)
            span = value.get("span") if isinstance(value, dict) else None
            if isinstance(span, dict) and type(span.get("start")) is int and type(span.get("end")) is int:
                target_span = (span["start"], span["end"])
        if target_span is not None and start <= target_span[0] and target_span[1] <= end:
            return True
    return False


def normalize_collection_item(record: dict[str, Any], dimension: str, item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    spec = dimension_spec(dimension)
    if spec is None or not spec.target_lemma_field or spec.target_lemma_field not in item:
        return dict(item)
    target = normalize_predicate_reference(record, item.get(spec.target_lemma_field))
    if target is None:
        return None
    normalized = dict(item)
    normalized[spec.target_lemma_field] = target
    return normalized
