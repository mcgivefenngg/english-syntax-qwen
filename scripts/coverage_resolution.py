"""Deterministic resolution for scoped annotation coverage."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class CoverageState(str, Enum):
    COMPLETE = "complete"
    PARTIAL_COVERED = "partial_covered"
    PARTIAL_UNCOVERED = "partial_uncovered"
    OMITTED = "omitted"
    UNANNOTATED = "unannotated"
    OUT_OF_SCOPE = "out_of_scope"
    CONFIRMED_EMPTY = "confirmed_empty"


class CoverageResolutionError(ValueError):
    """Raised when invalid declarations cannot produce one coverage state."""


@dataclass(frozen=True)
class CoverageIssue:
    index: int
    message: str


def coverage_scope_key(scope: dict[str, Any] | None) -> tuple[Any, ...]:
    if not isinstance(scope, dict):
        return ("invalid",)
    kind = scope.get("kind")
    if kind == "record":
        return ("record",)
    if kind == "node":
        return ("node", scope.get("node"))
    if kind == "region":
        return ("region", scope.get("start"), scope.get("end"))
    return (kind,)


def _record_objects(record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    objects: dict[str, dict[str, Any]] = {}
    for collection in ("words", "constituents", "clauses"):
        values = record.get(collection, [])
        if not isinstance(values, list):
            continue
        for item in values:
            if isinstance(item, dict) and isinstance(item.get("id"), str):
                objects[item["id"]] = item
    return objects


def _target_span(record: dict[str, Any], target: str) -> tuple[int, int] | None:
    target_object = _record_objects(record).get(target, {})
    span = target_object.get("span")
    if isinstance(span, dict) and type(span.get("start")) is int and type(span.get("end")) is int:
        return span["start"], span["end"]
    words = record.get("words", [])
    if isinstance(words, list):
        for index, word in enumerate(words):
            if isinstance(word, dict) and word.get("id") == target:
                return index, index + 1
    return None


def _scope_issue(
    scope: Any,
    node_ids: set[str],
    token_count: int,
) -> str | None:
    if not isinstance(scope, dict) or scope.get("kind") not in {"record", "node", "region"}:
        return "coverage scope must identify a record, node, or region"
    kind = scope["kind"]
    keys = set(scope)
    if kind == "record":
        if keys != {"kind"}:
            return "record coverage scope cannot include node or region fields"
        return None
    if kind == "node":
        node = scope.get("node")
        if not isinstance(node, str) or not node:
            return "node coverage scope requires a non-empty node"
        if keys != {"kind", "node"}:
            return "node coverage scope cannot include region fields"
        if node not in node_ids:
            return "node coverage scope must reference a known node"
        return None
    start = scope.get("start")
    end = scope.get("end")
    if type(start) is not int or type(end) is not int:
        return "region coverage scope requires integer start/end"
    if keys != {"kind", "start", "end"}:
        return "region coverage scope cannot include node or other fields"
    if start < 0 or end <= start or end > token_count:
        return "region coverage scope must be a valid non-empty span within the token sequence"
    return None


def _entry_state(entry: dict[str, Any], partial_is_covered: bool) -> CoverageState | None:
    completeness = entry.get("completeness")
    omission = entry.get("omission")
    evidence = entry.get("evidence")
    if completeness == "out_of_scope" or omission == "not_applicable":
        return CoverageState.OUT_OF_SCOPE
    if completeness == "omitted":
        return CoverageState.OMITTED
    if completeness == "unannotated":
        return CoverageState.UNANNOTATED
    if omission == "intentional":
        if evidence == "unannotated":
            return CoverageState.UNANNOTATED
        return CoverageState.OMITTED
    if completeness == "complete":
        if evidence == "empty":
            return CoverageState.CONFIRMED_EMPTY
        return CoverageState.COMPLETE
    if completeness == "partial":
        if partial_is_covered:
            return CoverageState.PARTIAL_COVERED
        return CoverageState.PARTIAL_UNCOVERED
    return None


def _semantic_key(entry: dict[str, Any]) -> tuple[Any, ...]:
    state = _entry_state(entry, partial_is_covered=True)
    if state is not None:
        return (state.value,)
    return (entry.get("completeness"), entry.get("omission"), entry.get("evidence"))


def _region_contains(outer: dict[str, Any], inner: dict[str, Any]) -> bool:
    return outer["start"] <= inner["start"] and inner["end"] <= outer["end"]


def _regions_overlap(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return max(left["start"], right["start"]) < min(left["end"], right["end"])


def coverage_declaration_issues(record: dict[str, Any]) -> list[CoverageIssue]:
    """Return structural declaration issues used by dataset validation."""
    annotation_scope = record.get("annotation_scope")
    dimensions = annotation_scope.get("dimensions", []) if isinstance(annotation_scope, dict) else []
    if not isinstance(dimensions, list):
        return []
    objects = _record_objects(record)
    words = record.get("words")
    token_count = len(words) if isinstance(words, list) else 0
    issues: list[CoverageIssue] = []
    valid_entries: list[tuple[int, dict[str, Any]]] = []
    exact_scopes: dict[tuple[str, tuple[Any, ...]], tuple[int, dict[str, Any]]] = {}
    for index, entry in enumerate(dimensions):
        if not isinstance(entry, dict) or not isinstance(entry.get("dimension"), str):
            continue
        scope = entry.get("scope")
        issue = _scope_issue(scope, set(objects), token_count)
        if issue is not None:
            issues.append(CoverageIssue(index, issue))
            continue
        valid_entries.append((index, entry))
        identity = (entry["dimension"], coverage_scope_key(scope))
        previous = exact_scopes.get(identity)
        if previous is not None:
            if _semantic_key(previous[1]) == _semantic_key(entry):
                message = "duplicate dimension + scope coverage declaration"
            else:
                message = "same dimension + scope cannot have contradictory coverage states"
            issues.append(CoverageIssue(index, message))
        else:
            exact_scopes[identity] = (index, entry)

    regions_by_dimension: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    for index, entry in valid_entries:
        scope = entry["scope"]
        if scope["kind"] == "region":
            regions_by_dimension.setdefault(entry["dimension"], []).append((index, entry))
    for regions in regions_by_dimension.values():
        for left_offset, (left_index, left) in enumerate(regions):
            left_scope = left["scope"]
            for right_index, right in regions[left_offset + 1:]:
                right_scope = right["scope"]
                if not _regions_overlap(left_scope, right_scope):
                    continue
                if _region_contains(left_scope, right_scope) or _region_contains(right_scope, left_scope):
                    continue
                if _semantic_key(left) != _semantic_key(right):
                    issues.append(CoverageIssue(
                        right_index,
                        f"overlapping peer regions have contradictory coverage states (peer declaration at index {left_index})",
                    ))
    return issues


def _collapse_states(
    entries: list[dict[str, Any]],
    partial_is_covered: bool,
) -> CoverageState:
    states = {
        state
        for entry in entries
        if (state := _entry_state(entry, partial_is_covered)) is not None
    }
    if not states:
        return CoverageState.UNANNOTATED
    if len(states) != 1:
        values = ", ".join(sorted(state.value for state in states))
        raise CoverageResolutionError(f"applicable coverage declarations conflict: {values}")
    return next(iter(states))


def resolve_coverage(
    record: dict[str, Any],
    dimension: str,
    target: str | None = None,
) -> CoverageState:
    """Resolve by exact node, containment-minimal region, then record scope."""
    annotation_scope = record.get("annotation_scope")
    dimensions = annotation_scope.get("dimensions", []) if isinstance(annotation_scope, dict) else []
    if not isinstance(dimensions, list):
        return CoverageState.UNANNOTATED
    entries = [
        entry for entry in dimensions
        if isinstance(entry, dict)
        and entry.get("dimension") == dimension
        and isinstance(entry.get("scope"), dict)
    ]
    if target is not None:
        node_entries = [
            entry for entry in entries
            if entry["scope"].get("kind") == "node" and entry["scope"].get("node") == target
        ]
        if node_entries:
            return _collapse_states(node_entries, partial_is_covered=True)

        target_span = _target_span(record, target)
        if target_span is not None:
            target_start, target_end = target_span
            regions = [
                entry for entry in entries
                if entry["scope"].get("kind") == "region"
                and type(entry["scope"].get("start")) is int
                and type(entry["scope"].get("end")) is int
                and entry["scope"]["start"] <= target_start
                and target_end <= entry["scope"]["end"]
            ]
            most_specific = [
                entry for entry in regions
                if not any(
                    other is not entry
                    and coverage_scope_key(other["scope"]) != coverage_scope_key(entry["scope"])
                    and _region_contains(entry["scope"], other["scope"])
                    for other in regions
                )
            ]
            if most_specific:
                return _collapse_states(most_specific, partial_is_covered=True)

    record_entries = [entry for entry in entries if entry["scope"].get("kind") == "record"]
    if record_entries:
        return _collapse_states(record_entries, partial_is_covered=False)
    return CoverageState.UNANNOTATED
