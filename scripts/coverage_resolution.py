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


@dataclass(frozen=True)
class ScoringEligibility:
    scoreable: bool
    coverage_state: CoverageState | None
    reason: str

    @property
    def state(self) -> CoverageState | None:
        return self.coverage_state


class CoverageResolutionError(ValueError):
    """Raised when invalid declarations or targets cannot produce one coverage state."""


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


def _target_exists(record: dict[str, Any], target: str) -> bool:
    if not isinstance(target, str) or not target:
        return False
    return target in _record_objects(record)


def _target_span(record: dict[str, Any], target: str) -> tuple[int, int] | None:
    words = record.get("words", [])
    if isinstance(words, list):
        for index, word in enumerate(words):
            if isinstance(word, dict) and word.get("id") == target:
                return index, index + 1
    target_object = _record_objects(record).get(target)
    if not isinstance(target_object, dict):
        return None
    span = target_object.get("span")
    if not isinstance(span, dict) or type(span.get("start")) is not int or type(span.get("end")) is not int:
        return None
    token_count = len(words) if isinstance(words, list) else 0
    if span["start"] < 0 or span["end"] <= span["start"] or span["end"] > token_count:
        return None
    return span["start"], span["end"]


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


_COLLECTION_DIMENSIONS: dict[str, str] = {
    "dependencies": "dependencies",
    "semantic_roles": "semantic_roles",
    "lexical_valency": "lexical_valency",
}


def _collection_targets(record: dict[str, Any], dimension: str, item: Any) -> list[str]:
    if not isinstance(item, dict):
        return []
    if dimension == "dependencies":
        values = [item.get("head"), item.get("dependent"), item.get("source"), item.get("target")]
        return [value for value in values if isinstance(value, str)]
    if dimension == "semantic_roles":
        values = [item.get("constituent"), item.get("predicate")]
        targets = [value for value in values if isinstance(value, str)]
        objects = _record_objects(record)
        words = record.get("words", [])
        predicate = item.get("predicate")
        if isinstance(predicate, str) and predicate not in objects and isinstance(words, list):
            targets.extend(
                word["id"] for word in words
                if isinstance(word, dict) and word.get("lemma") == predicate and isinstance(word.get("id"), str)
            )
        return targets
    values = item.get("selected_complements", [])
    targets = [value for value in values if isinstance(value, str)] if isinstance(values, list) else []
    predicate = item.get("predicate")
    objects = _record_objects(record)
    if isinstance(predicate, str):
        if predicate in objects:
            targets.append(predicate)
        else:
            words = record.get("words", [])
            if isinstance(words, list):
                targets.extend(
                    word["id"] for word in words
                    if isinstance(word, dict) and word.get("lemma") == predicate and isinstance(word.get("id"), str)
                )
    return targets


def _target_in_scope(record: dict[str, Any], target: str, scope: dict[str, Any]) -> bool:
    kind = scope.get("kind")
    if kind == "record":
        return True
    if kind == "node":
        return target == scope.get("node")
    target_span = _target_span(record, target)
    start, end = scope.get("start"), scope.get("end")
    return (
        target_span is not None
        and type(start) is int
        and type(end) is int
        and start <= target_span[0]
        and target_span[1] <= end
    )


def _has_more_specific_scope(record: dict[str, Any], dimension: str, target: str, scope: dict[str, Any]) -> bool:
    annotation_scope = record.get("annotation_scope")
    dimensions = annotation_scope.get("dimensions", []) if isinstance(annotation_scope, dict) else []
    if not isinstance(dimensions, list):
        return False
    for entry in dimensions:
        if not isinstance(entry, dict) or entry.get("dimension") != dimension:
            continue
        other_scope = entry.get("scope")
        if not isinstance(other_scope, dict) or other_scope.get("kind") == "record":
            continue
        if _target_in_scope(record, target, other_scope):
            return True
    return False


def _collection_items_for_declaration(
    record: dict[str, Any],
    dimension: str,
    entry: dict[str, Any],
    values: list[Any],
) -> list[Any]:
    scope = entry.get("scope")
    if not isinstance(scope, dict):
        return []
    selected: list[Any] = []
    for item in values:
        targets = _collection_targets(record, dimension, item)
        if not targets:
            if scope.get("kind") == "record":
                selected.append(item)
            continue
        if scope.get("kind") == "record":
            specific_states: list[CoverageState] = []
            for target in targets:
                if not _has_more_specific_scope(record, dimension, target, scope):
                    continue
                try:
                    state = resolve_coverage(record, dimension, target)
                except CoverageResolutionError:
                    continue
                specific_states.append(state)
            if any(state in {CoverageState.COMPLETE, CoverageState.CONFIRMED_EMPTY, CoverageState.PARTIAL_COVERED} for state in specific_states):
                continue
        owned_targets: list[str] = []
        for target in targets:
            if not _target_in_scope(record, target, scope):
                continue
            if not _has_more_specific_scope(record, dimension, target, scope):
                owned_targets.append(target)
                continue
            try:
                state = resolve_coverage(record, dimension, target)
            except CoverageResolutionError:
                continue
            expected = _entry_state(entry, partial_is_covered=True)
            if expected is not None and state is expected:
                owned_targets.append(target)
        if owned_targets:
            selected.append(item)
    return selected


def _collection_content_issues(
    record: dict[str, Any],
    valid_entries: list[tuple[int, dict[str, Any]]],
) -> list[CoverageIssue]:
    issues: list[CoverageIssue] = []
    for index, entry in valid_entries:
        dimension = entry.get("dimension")
        field = _COLLECTION_DIMENSIONS.get(dimension)
        if field is None:
            continue
        values = record.get(field)
        values = values if isinstance(values, list) else []
        owned_items = _collection_items_for_declaration(record, dimension, entry, values)
        evidence = entry.get("evidence")
        omission = entry.get("omission")
        completeness = entry.get("completeness")
        scope_label = f"{dimension} {entry.get('scope')}"
        excluded = omission in {"intentional", "not_applicable"} or completeness in {"unannotated", "omitted", "out_of_scope"}
        if excluded:
            if owned_items:
                issues.append(CoverageIssue(index, f"{scope_label} is unannotated/omitted but has authoritative collection content"))
            continue
        if evidence == "present":
            if not owned_items:
                issues.append(CoverageIssue(index, f"evidence='present' requires non-empty authoritative {field} content in the covered scope"))
        elif evidence == "empty":
            if owned_items:
                issues.append(CoverageIssue(index, f"evidence='empty' requires an empty {field} collection in the covered scope"))
        elif not owned_items:
            issues.append(CoverageIssue(index, f"annotated empty {field} collection requires evidence='empty'"))
    return issues


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
    issues.extend(_collection_content_issues(record, valid_entries))
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
        if not _target_exists(record, target):
            raise CoverageResolutionError("coverage target must reference a known word, constituent, or clause")
        node_entries = [
            entry for entry in entries
            if entry["scope"].get("kind") == "node" and entry["scope"].get("node") == target
        ]
        if node_entries:
            return _collapse_states(node_entries, partial_is_covered=True)

        target_span = _target_span(record, target)
        if target_span is None:
            raise CoverageResolutionError("coverage target span cannot be resolved")
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


_SCOREABLE_COVERAGE_STATES = frozenset({
    CoverageState.COMPLETE,
    CoverageState.CONFIRMED_EMPTY,
    CoverageState.PARTIAL_COVERED,
})

_SCORING_REASONS = {
    CoverageState.COMPLETE: "complete coverage is scoreable",
    CoverageState.CONFIRMED_EMPTY: "confirmed empty coverage is scoreable",
    CoverageState.PARTIAL_COVERED: "partial coverage explicitly covers this target",
    CoverageState.PARTIAL_UNCOVERED: "partial coverage does not cover this target; absence is not negative gold",
    CoverageState.OMITTED: "coverage is omitted; absence is not negative gold",
    CoverageState.UNANNOTATED: "coverage is unannotated; absence is not negative gold",
    CoverageState.OUT_OF_SCOPE: "target is out of scope; absence is not negative gold",
}


def resolve_scoring_eligibility(
    record: dict[str, Any],
    dimension: str,
    target: str | None = None,
) -> ScoringEligibility:
    """Resolve coverage once and return the corresponding scoring decision."""
    try:
        state = resolve_coverage(record, dimension, target)
    except CoverageResolutionError:
        return ScoringEligibility(
            scoreable=False,
            coverage_state=None,
            reason="coverage resolution failed; scoring is disabled",
        )
    return ScoringEligibility(
        scoreable=state in _SCOREABLE_COVERAGE_STATES,
        coverage_state=state,
        reason=_SCORING_REASONS[state],
    )
