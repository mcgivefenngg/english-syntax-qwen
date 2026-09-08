"""Deterministic resolution for scoped annotation coverage."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

try:
    from dimension_registry import dimension_spec
except ImportError:
    from scripts.dimension_registry import dimension_spec

try:
    from collection_contract import collection_target_ids, validate_coverage_target
except ImportError:
    from scripts.collection_contract import collection_target_ids, validate_coverage_target

try:
    from authoritative_payload import (
        AuthoritativePayload,
        AuthoritativePayloadState,
        authoritative_payload,
        authoritative_payload_state,
        confirmed_empty_eligible,
    )
except ImportError:
    from scripts.authoritative_payload import (
        AuthoritativePayload,
        AuthoritativePayloadState,
        authoritative_payload,
        authoritative_payload_state,
        confirmed_empty_eligible,
    )

try:
    from canonical_schema import canonical_schema_issues, canonical_schema_issue_text
except ImportError:
    from scripts.canonical_schema import canonical_schema_issues, canonical_schema_issue_text


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


def _record_identity_issues(record: dict[str, Any]) -> list[str]:
    seen: dict[str, str] = {}
    issues: list[str] = []
    for collection in ("words", "constituents", "clauses"):
        values = record.get(collection, [])
        if not isinstance(values, list):
            continue
        for index, item in enumerate(values):
            if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
                continue
            identifier = item["id"]
            location = f"{collection}[{index}]"
            previous = seen.get(identifier)
            if previous is not None:
                issues.append(f"duplicate canonical object id {identifier!r} ({previous} and {location})")
            else:
                seen[identifier] = location
    return issues


def _record_object(record: dict[str, Any], target: str) -> tuple[str, dict[str, Any]] | None:
    for collection in ("words", "constituents", "clauses"):
        values = record.get(collection, [])
        if not isinstance(values, list):
            continue
        for item in values:
            if isinstance(item, dict) and item.get("id") == target:
                return collection, item
    return None


def _target_exists(record: dict[str, Any], target: str) -> bool:
    if not isinstance(target, str) or not target:
        return False
    return target in _record_objects(record)


def _target_span(record: dict[str, Any], target: str) -> tuple[int, int] | None:
    object_entry = _record_object(record, target)
    if object_entry is None:
        return None
    collection, target_object = object_entry
    words = record.get("words", [])
    if collection == "words":
        if isinstance(words, list):
            for index, word in enumerate(words):
                if word is target_object:
                    return index, index + 1
        return None
    if target_object.get("node_kind") not in {"phrase", "clause"}:
        return None
    span = target_object.get("span")
    if not isinstance(span, dict) or type(span.get("start")) is not int or type(span.get("end")) is not int:
        return None
    token_count = len(words) if isinstance(words, list) else 0
    if span["start"] < 0 or span["end"] <= span["start"] or span["end"] > token_count:
        return None
    if span["end"] <= token_count and isinstance(words[span["end"] - 1], dict):
        ends_with_punctuation = words[span["end"] - 1].get("lexical_category") == "punctuation"
        is_main_clause = collection == "clauses" and target_object.get("clause_category") == "main_clause"
        if ends_with_punctuation and not is_main_clause:
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


def _collection_content_issues(
    record: dict[str, Any],
    valid_entries: list[tuple[int, dict[str, Any]]],
) -> list[CoverageIssue]:
    issues: list[CoverageIssue] = []
    for index, entry in valid_entries:
        dimension = entry.get("dimension")
        scope = entry.get("scope")
        if not isinstance(dimension, str) or not isinstance(scope, dict):
            continue
        target: str | dict[str, Any] | None = None
        if scope.get("kind") == "node":
            target = scope.get("node")
        elif scope.get("kind") == "region":
            target = scope
        payload = authoritative_payload(record, dimension, target)
        evidence = entry.get("evidence")
        omission = entry.get("omission")
        completeness = entry.get("completeness")
        scope_label = f"{dimension} {entry.get('scope')}"
        excluded = omission in {"intentional", "not_applicable"} or completeness in {"unannotated", "omitted", "out_of_scope"}
        if excluded:
            if payload.has_authoritative_content:
                issues.append(CoverageIssue(index, f"{scope_label} is unannotated/omitted but has authoritative payload content"))
            continue
        if evidence == "present":
            if not payload.has_resolved_content:
                issues.append(CoverageIssue(index, f"{scope_label} evidence='present' requires resolved authoritative payload in the covered scope"))
            elif completeness == "complete" and not payload.fully_resolved:
                issues.append(CoverageIssue(index, f"{scope_label} complete coverage requires all applicable authoritative payload to be resolved"))
        elif evidence == "empty":
            if payload.has_authoritative_content:
                issues.append(CoverageIssue(index, f"{scope_label} evidence='empty' cannot coexist with owned authoritative payload"))
            elif not confirmed_empty_eligible(record, dimension_spec(dimension), payload):
                issues.append(CoverageIssue(index, f"{scope_label} evidence='empty' requires an explicit empty content collection with no missing or malformed owned payload"))
        elif not payload.has_resolved_content:
            issues.append(CoverageIssue(index, f"{scope_label} annotated coverage requires evidence='empty' or resolved authoritative payload"))
    return issues


def _dimension_entry_issue(
    record: dict[str, Any],
    entry: dict[str, Any],
    objects: dict[str, dict[str, Any]],
    token_count: int,
) -> str | None:
    dimension = entry.get("dimension")
    spec = dimension_spec(dimension)
    if spec is None:
        return f"unknown coverage dimension {dimension!r}"
    scope = entry.get("scope")
    issue = _scope_issue(scope, set(objects), token_count)
    if issue is not None:
        return issue
    scope_kind = scope["kind"]
    if not spec.allows_scope(scope_kind):
        return f"dimension {dimension!r} does not support {scope_kind} scope"
    if scope_kind == "node":
        node_kind = objects[scope["node"]].get("node_kind")
        if not isinstance(node_kind, str) or not spec.allows_node(node_kind):
            expected = ", ".join(sorted(spec.allowed_node_kinds))
            return f"dimension {dimension!r} node scope must reference {expected} node(s)"
        target_validation = validate_coverage_target(record, dimension, scope["node"])
        if not target_validation.valid:
            return target_validation.reason
    completeness = entry.get("completeness")
    omission = entry.get("omission")
    evidence = entry.get("evidence")
    if completeness not in {"complete", "partial", "unannotated", "omitted", "out_of_scope"}:
        return "coverage completeness must be complete, partial, unannotated, omitted, or out_of_scope"
    if omission not in {"none", "intentional", "not_applicable"}:
        return "coverage omission must be none, intentional, or not_applicable"
    if omission == "none" and evidence is None:
        return "annotated coverage requires explicit evidence"
    if omission == "none" and evidence == "unannotated":
        return "unannotated evidence requires omission intentional or not_applicable"
    if completeness in {"unannotated", "omitted", "out_of_scope"} and omission == "none":
        return "unannotated/omitted/out_of_scope completeness cannot use omission='none'"
    if completeness == "complete" and omission in {"intentional", "not_applicable"}:
        return "complete coverage cannot be marked intentionally omitted or not applicable"
    if omission in {"intentional", "not_applicable"} and evidence not in {None, "unannotated"}:
        return "omitted coverage must use evidence='unannotated' when evidence is declared"
    if evidence is not None and evidence not in spec.allowed_evidence_modes:
        return f"dimension {dimension!r} does not support evidence={evidence!r}"
    if evidence == "empty":
        if not spec.allows_confirmed_empty(scope_kind):
            return f"dimension {dimension!r} cannot represent confirmed-empty at {scope_kind} scope"
        if entry.get("completeness") != "complete":
            return "confirmed-empty evidence requires completeness='complete'"
    if entry.get("completeness") == "partial":
        if not spec.allows_partial(scope_kind):
            return f"dimension {dimension!r} does not support partial coverage at {scope_kind} scope"
        if scope_kind == "record" and evidence == "present" and spec.partial_present_target_source is None:
            return f"dimension {dimension!r} record-level partial present coverage has no identifiable target representation"
    return None


def coverage_declaration_issues(
    record: dict[str, Any],
    dimension: str | None = None,
    *,
    include_content: bool = True,
) -> list[CoverageIssue]:
    """Return shared H2 declaration/content issues for validation and resolution."""
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
    requested_dimension = dimension
    for index, entry in enumerate(dimensions):
        if not isinstance(entry, dict):
            issues.append(CoverageIssue(index, "coverage dimension must be an object"))
            continue
        if not isinstance(entry.get("dimension"), str):
            issues.append(CoverageIssue(index, "coverage dimension requires a string dimension"))
            continue
        entry_dimension = entry["dimension"]
        if requested_dimension is not None and requested_dimension != entry_dimension:
            continue
        scope = entry.get("scope")
        issue = _dimension_entry_issue(record, entry, objects, token_count)
        if issue is not None:
            issues.append(CoverageIssue(index, issue))
            continue
        valid_entries.append((index, entry))
        identity = (entry_dimension, coverage_scope_key(scope))
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
    if include_content:
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


def declared_coverage_state(
    record: dict[str, Any],
    dimension: str,
    target: str | dict[str, Any] | None = None,
) -> CoverageState:
    """Resolve raw declaration precedence without canonical or payload validation."""
    if dimension_spec(dimension) is None:
        raise CoverageResolutionError(f"unknown coverage dimension {dimension!r}")
    target_validation = validate_coverage_target(record, dimension, target)
    if not target_validation.valid:
        raise CoverageResolutionError(target_validation.reason)
    if target_validation.target_kind == "region_target":
        raise CoverageResolutionError("coverage resolution targets must be node IDs or the record target")
    target = target_validation.normalized_target
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
        if not isinstance(target, str):
            raise CoverageResolutionError("coverage target must be a node ID or record target")
        target_span = _target_span(record, target)
        if target_span is None:
            raise CoverageResolutionError("coverage target span cannot be resolved")
        node_entries = [
            entry for entry in entries
            if entry["scope"].get("kind") == "node" and entry["scope"].get("node") == target
        ]
        if node_entries:
            return _collapse_states(node_entries, partial_is_covered=True)

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


def _derive_partial_present_coverage(
    record: dict[str, Any],
    dimension: str,
    target: str | dict[str, Any] | None,
) -> CoverageState | None:
    """Activate registry-declared partial-present target semantics.

    A record-level ``partial + evidence="present"`` declaration states that a
    positive subset is explicitly annotated; ``partial_present_target_source``
    identifies that subset from resolved authoritative payload. Absence outside
    the subset remains unknown, never negative gold. Raw declaration
    resolution stays separate so confirmed-empty helpers never recurse
    through payload derivation.
    """
    spec = dimension_spec(dimension)
    if spec is None:
        return None
    source = spec.partial_present_target_source
    if source is None:
        return None
    validation = validate_coverage_target(record, dimension, target)
    if not validation.valid:
        return None
    if source == "record":
        if not validation.is_record_target:
            return None
        payload_target: str | dict[str, Any] | None = None
    else:
        if validation.is_record_target:
            return None
        normalized = validation.normalized_target
        if not isinstance(normalized, str):
            return None
        payload_target = normalized
    payload = authoritative_payload(record, dimension, payload_target)
    return CoverageState.PARTIAL_COVERED if payload.has_resolved_content else None


def resolve_coverage(
    record: dict[str, Any],
    dimension: str,
    target: str | dict[str, Any] | None = None,
) -> CoverageState:
    """Resolve by exact node, containment-minimal region, then record scope."""
    schema_issues = canonical_schema_issues(record)
    if schema_issues:
        raise CoverageResolutionError(
            f"canonical schema validation failed: {canonical_schema_issue_text(schema_issues[0])}"
        )
    if dimension_spec(dimension) is None:
        raise CoverageResolutionError(f"unknown coverage dimension {dimension!r}")
    identity_issues = _record_identity_issues(record)
    if identity_issues:
        raise CoverageResolutionError(identity_issues[0])
    issues = coverage_declaration_issues(record, include_content=False)
    if issues:
        issue = issues[0]
        raise CoverageResolutionError(f"{issue.message} (declaration index {issue.index})")
    issues = coverage_declaration_issues(record, dimension)
    if issues:
        issue = issues[0]
        raise CoverageResolutionError(f"{issue.message} (declaration index {issue.index})")
    state = declared_coverage_state(record, dimension, target)
    if state is CoverageState.PARTIAL_UNCOVERED:
        derived = _derive_partial_present_coverage(record, dimension, target)
        if derived is not None:
            return derived
    return state


def _collection_item_coverage_state(
    record: dict[str, Any],
    dimension: str,
    item: Any,
) -> CoverageState | None:
    spec = dimension_spec(dimension)
    if spec is None:
        return None
    targets = collection_target_ids(record, dimension, item)
    if spec.allowed_scope_kinds == frozenset({"record"}):
        try:
            return resolve_coverage(record, dimension)
        except CoverageResolutionError:
            return None
    if len(targets) != 1:
        return None
    try:
        return resolve_coverage(record, dimension, targets[0])
    except CoverageResolutionError:
        return None


def collection_item_coverage_state(
    record: dict[str, Any],
    dimension: str,
    item: Any,
) -> CoverageState | None:
    """Resolve the effective coverage state for one collection item."""
    return _collection_item_coverage_state(record, dimension, item)


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
