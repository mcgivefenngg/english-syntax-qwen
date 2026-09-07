"""Shared V0.4 collection ownership and predicate-reference rules."""

from __future__ import annotations

from dataclasses import dataclass
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


def predicate_reference_candidates(record: dict[str, Any], reference: Any) -> tuple[str, ...]:
    """Return every deterministic candidate for a predicate reference."""
    if not isinstance(reference, str) or not reference:
        return ()
    word_ids = set(_word_ids(record))
    if reference in word_ids:
        return (reference,)
    lemma_matches = _word_ids_by_field(record, "lemma").get(reference, ())
    if lemma_matches:
        return lemma_matches
    return _word_ids_by_field(record, "form").get(reference, ())


def normalize_predicate_reference(record: dict[str, Any], reference: Any) -> str | None:
    """Return an explicit word ID for an ID or uniquely matching legacy lemma."""
    candidates = predicate_reference_candidates(record, reference)
    return candidates[0] if len(candidates) == 1 else None


@dataclass(frozen=True)
class CoverageTargetValidation:
    """Classify one coverage target against a dimension's owner contract."""

    valid: bool
    target_kind: str
    reason: str
    normalized_target: str | dict[str, Any] | None = None
    node_kind: str | None = None

    @property
    def kind(self) -> str:
        return self.target_kind

    @property
    def is_record_target(self) -> bool:
        return self.target_kind == "record_target"

    @property
    def is_dimension_target(self) -> bool:
        return self.target_kind in {"dimension_node", "region_target"}


def _coverage_target_result(
    valid: bool,
    target_kind: str,
    reason: str,
    *,
    normalized_target: str | dict[str, Any] | None = None,
    node_kind: str | None = None,
) -> CoverageTargetValidation:
    return CoverageTargetValidation(
        valid=valid,
        target_kind=target_kind,
        reason=reason,
        normalized_target=normalized_target,
        node_kind=node_kind,
    )


def _coverage_target_objects(record: dict[str, Any], target: str) -> tuple[tuple[str, dict[str, Any]], ...]:
    matches: list[tuple[str, dict[str, Any]]] = []
    for collection in ("words", "constituents", "clauses"):
        values = record.get(collection, [])
        if not isinstance(values, list):
            continue
        matches.extend(
            (collection, item)
            for item in values
            if isinstance(item, dict) and item.get("id") == target
        )
    return tuple(matches)


def _lexical_valency_owner_ids(record: dict[str, Any]) -> tuple[set[str], set[str]]:
    values = record.get("lexical_valency", [])
    if not isinstance(values, list):
        return set(), set()
    owners: set[str] = set()
    ambiguous: set[str] = set()
    for item in values:
        if not isinstance(item, dict):
            continue
        candidates = predicate_reference_candidates(record, item.get("predicate"))
        if len(candidates) == 1:
            owners.add(candidates[0])
        elif len(candidates) > 1:
            ambiguous.update(candidates)
    return owners, ambiguous


def validate_coverage_target(
    record: dict[str, Any],
    dimension: str,
    target: str | dict[str, Any] | None = None,
) -> CoverageTargetValidation:
    """Validate record, node, and region target applicability for a dimension."""
    spec = dimension_spec(dimension)
    if spec is None:
        return _coverage_target_result(False, "invalid_dimension", f"unknown coverage dimension {dimension!r}")
    if target is None or target == {"kind": "record"}:
        if spec.allows_scope("record"):
            return _coverage_target_result(True, "record_target", "record target is applicable")
        return _coverage_target_result(
            False,
            "unsupported_record_target",
            f"dimension {dimension!r} does not support record target semantics",
        )
    if isinstance(target, dict):
        target_kind = target.get("kind")
        if target_kind == "region":
            if not spec.allows_scope("region"):
                return _coverage_target_result(
                    False,
                    "unsupported_non_record_target",
                    f"dimension {dimension!r} does not support region targets",
                )
            if set(target) != {"kind", "start", "end"}:
                return _coverage_target_result(False, "invalid_target", "coverage region target has invalid fields")
            start, end = target.get("start"), target.get("end")
            token_count = record.get("words", [])
            token_count = len(token_count) if isinstance(token_count, list) else 0
            if type(start) is not int or type(end) is not int or start < 0 or end <= start or end > token_count:
                return _coverage_target_result(False, "invalid_target", "coverage region target must be a valid token span")
            return _coverage_target_result(True, "region_target", "region target is applicable", normalized_target=target)
        if target_kind == "node" and set(target) == {"kind", "node"}:
            target = target.get("node")
        else:
            return _coverage_target_result(False, "invalid_target", "coverage target must be a node ID or record target")
    if not isinstance(target, str) or not target:
        return _coverage_target_result(False, "invalid_target", "coverage target must be a non-empty node ID or record target")
    if not spec.allows_scope("node"):
        return _coverage_target_result(
            False,
            "unsupported_non_record_target",
            f"dimension {dimension!r} has no supported non-record target semantics",
        )
    matches = _coverage_target_objects(record, target)
    if not matches:
        return _coverage_target_result(False, "unknown_target", "coverage target must reference a known word, constituent, or clause")
    if len(matches) != 1:
        return _coverage_target_result(False, "ambiguous_target", f"coverage target {target!r} has ambiguous canonical identity")
    collection, item = matches[0]
    node_kind = item.get("node_kind")
    if not isinstance(node_kind, str) or not spec.allows_node(node_kind):
        expected = ", ".join(sorted(spec.allowed_node_kinds))
        return _coverage_target_result(
            False,
            "invalid_node_kind",
            f"dimension {dimension!r} target {target!r} must reference {expected} node(s)",
            node_kind=node_kind if isinstance(node_kind, str) else None,
        )
    if spec.target_owner == "canonical_word" and (collection != "words" or node_kind != "word"):
        return _coverage_target_result(
            False,
            "invalid_node_kind",
            f"dimension {dimension!r} target {target!r} must reference a canonical word node",
            node_kind=node_kind,
        )
    if spec.target_owner == "canonical_clause" and (collection != "clauses" or node_kind != "clause"):
        return _coverage_target_result(
            False,
            "invalid_node_kind",
            f"dimension {dimension!r} target {target!r} must reference a canonical clause node",
            node_kind=node_kind,
        )
    if spec.target_owner == "syntactic_function_owner" and collection == "clauses":
        return _coverage_target_result(
            False,
            "wrong_owner",
            f"dimension {dimension!r} target {target!r} is a canonical clause; external syntactic function belongs on a constituent realization owner",
            node_kind=node_kind,
        )
    if spec.target_owner == "np_phrase" and (collection != "constituents" or node_kind != "phrase" or item.get("phrase_category") != "NP"):
        return _coverage_target_result(
            False,
            "wrong_owner",
            f"dimension {dimension!r} target {target!r} must reference an applicable NP phrase owner",
            node_kind=node_kind,
        )
    if spec.target_owner == "lexical_head_word":
        if collection != "words" or node_kind != "word":
            return _coverage_target_result(
                False,
                "invalid_node_kind",
                f"dimension {dimension!r} target {target!r} must reference a lexical-head word node",
                node_kind=node_kind,
            )
        owners, ambiguous = _lexical_valency_owner_ids(record)
        if target in ambiguous:
            return _coverage_target_result(
                False,
                "ambiguous_owner",
                f"dimension {dimension!r} target {target!r} has ambiguous lexical-head owner identity",
                node_kind=node_kind,
            )
        if target not in owners:
            return _coverage_target_result(
                False,
                "wrong_owner",
                f"dimension {dimension!r} target {target!r} does not own an applicable lexical-valency item",
                node_kind=node_kind,
            )
    return _coverage_target_result(
        True,
        "dimension_node",
        f"dimension {dimension!r} target {target!r} is applicable",
        normalized_target=target,
        node_kind=node_kind,
    )


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
    if spec is None:
        return None
    if not spec.target_lemma_field:
        return dict(item)
    if spec.target_lemma_field not in item:
        return dict(item) if spec.target_lemma_optional else None
    target = normalize_predicate_reference(record, item.get(spec.target_lemma_field))
    if target is None:
        return None
    normalized = dict(item)
    normalized[spec.target_lemma_field] = target
    return normalized
