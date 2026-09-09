"""Executable V0.4 authoritative-payload contract.

Coverage declarations describe what a record claims to cover. This module
answers whether the corresponding structured linguistic payload actually
exists, while keeping unresolved evidence separate from resolved gold.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

try:
    from collection_contract import normalize_predicate_reference, validate_coverage_target
except ImportError:
    from scripts.collection_contract import normalize_predicate_reference, validate_coverage_target

try:
    from data_common import (
        CLAUSE_CONSTRUCTIONS,
        CLAUSE_FINITE_VALUES,
        CLAUSE_FORMS,
        CLAUSE_INTEGRATIONS,
        LEXICAL_CATEGORIES,
        NOMINAL_SUBJECT_CATEGORIES,
        PHRASE_CATEGORIES,
        PREDICAND_KINDS,
        PREDICAND_TARGET_REQUIRED_KINDS,
        SEMANTIC_ROLES,
    )
except ImportError:
    from scripts.data_common import (
        CLAUSE_CONSTRUCTIONS,
        CLAUSE_FINITE_VALUES,
        CLAUSE_FORMS,
        CLAUSE_INTEGRATIONS,
        LEXICAL_CATEGORIES,
        NOMINAL_SUBJECT_CATEGORIES,
        PHRASE_CATEGORIES,
        PREDICAND_KINDS,
        PREDICAND_TARGET_REQUIRED_KINDS,
        SEMANTIC_ROLES,
    )

try:
    from dimension_registry import DIMENSION_REGISTRY, DimensionSpec, PayloadSpec, dimension_spec
except ImportError:
    from scripts.dimension_registry import DIMENSION_REGISTRY, DimensionSpec, PayloadSpec, dimension_spec

try:
    from typed_relation_contract import (
        validate_typed_relation_structure,
        validate_typed_analysis_container,
        get_analysis_entity_ids,
        valid_analysis_entity_ids,
        TypedRelationValidationContext,
        _canonical_dependency_pairs,
        CANONICAL_SCALAR_RELATION_TYPES,
        parse_typed_reference,
    )
except ImportError:
    from scripts.typed_relation_contract import (
        validate_typed_relation_structure,
        validate_typed_analysis_container,
        get_analysis_entity_ids,
        valid_analysis_entity_ids,
        TypedRelationValidationContext,
        _canonical_dependency_pairs,
        CANONICAL_SCALAR_RELATION_TYPES,
        parse_typed_reference,
    )


class AuthoritativePayloadState(str, Enum):
    PRESENT = "present"
    CONFIRMED_EMPTY = "confirmed_empty"
    UNRESOLVED_ONLY = "unresolved_only"
    ABSENT = "absent"

    RESOLVED = "present"
    EMPTY = "confirmed_empty"
    UNRESOLVED = "unresolved_only"


@dataclass(frozen=True)
class AuthoritativePayload:
    """Payload facts for one dimension and effective target scope."""

    dimension: str
    target: str | dict[str, Any] | None
    state: AuthoritativePayloadState
    applicable_count: int = 0
    resolved_count: int = 0
    unresolved_count: int = 0
    missing_count: int = 0
    resolved_ids: tuple[str, ...] = ()
    unresolved_ids: tuple[str, ...] = ()
    fields: tuple[str, ...] = ()

    @property
    def has_resolved_content(self) -> bool:
        return self.resolved_count > 0

    @property
    def has_unresolved_content(self) -> bool:
        return self.unresolved_count > 0

    @property
    def has_authoritative_content(self) -> bool:
        return self.has_resolved_content or self.has_unresolved_content

    @property
    def fully_resolved(self) -> bool:
        return (
            self.applicable_count > 0
            and self.resolved_count == self.applicable_count
            and self.unresolved_count == 0
            and self.missing_count == 0
        )


@dataclass(frozen=True)
class AuthoritativePayloadItem:
    """One registry-owned payload item and its canonicalization status."""

    field: str
    identifier: str
    value: Any
    status: str
    path: tuple[str | int, ...]


@dataclass
class _PayloadAccumulator:
    applicable_count: int = 0
    resolved_count: int = 0
    unresolved_count: int = 0
    missing_count: int = 0
    resolved_ids: list[str] = field(default_factory=list)
    unresolved_ids: list[str] = field(default_factory=list)
    fields: set[str] = field(default_factory=set)

    def add(self, identifier: str, field_name: str, status: str) -> None:
        self.applicable_count += 1
        self.fields.add(field_name)
        if status == "resolved":
            self.resolved_count += 1
            self.resolved_ids.append(identifier)
        elif status == "unresolved":
            self.unresolved_count += 1
            self.unresolved_ids.append(identifier)
        else:
            self.missing_count += 1

    def result(
        self,
        dimension: str,
        target: str | dict[str, Any] | None,
        state: AuthoritativePayloadState | None = None,
    ) -> AuthoritativePayload:
        if state is None:
            if self.resolved_count:
                state = AuthoritativePayloadState.PRESENT
            elif self.unresolved_count:
                state = AuthoritativePayloadState.UNRESOLVED_ONLY
            else:
                state = AuthoritativePayloadState.ABSENT
        return AuthoritativePayload(
            dimension=dimension,
            target=target,
            state=state,
            applicable_count=self.applicable_count,
            resolved_count=self.resolved_count,
            unresolved_count=self.unresolved_count,
            missing_count=self.missing_count,
            resolved_ids=tuple(self.resolved_ids),
            unresolved_ids=tuple(self.unresolved_ids),
            fields=tuple(sorted(self.fields)),
        )


def _payload_spec(spec: DimensionSpec, field_name: str) -> PayloadSpec | None:
    return next((payload for payload in spec.payloads if payload.field == field_name), None)


def _has_field(spec: DimensionSpec, field_name: str) -> bool:
    return _payload_spec(spec, field_name) is not None


def _record_objects(record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    objects: dict[str, dict[str, Any]] = {}
    for field_name in ("words", "constituents", "clauses"):
        values = record.get(field_name)
        if not isinstance(values, list):
            continue
        for item in values:
            if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"]:
                objects[item["id"]] = item
    return objects


def _item_span(record: dict[str, Any], item: dict[str, Any]) -> tuple[int, int] | None:
    if item.get("node_kind") == "word":
        words = record.get("words")
        if isinstance(words, list):
            for index, word in enumerate(words):
                if word is item or (isinstance(word, dict) and word.get("id") == item.get("id")):
                    return index, index + 1
        return None
    span = item.get("span")
    if not isinstance(span, dict):
        return None
    start, end = span.get("start"), span.get("end")
    token_count = len(record.get("words", [])) if isinstance(record.get("words"), list) else 0
    if type(start) is not int or type(end) is not int or start < 0 or end <= start or end > token_count:
        return None
    return start, end


def _scope(target: str | dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(target, dict):
        return target
    if isinstance(target, str) and target:
        return {"kind": "node", "node": target}
    return {"kind": "record"}


def _in_scope(record: dict[str, Any], item: dict[str, Any], scope: dict[str, Any]) -> bool:
    kind = scope.get("kind")
    if kind == "record":
        return True
    if kind == "node":
        return item.get("id") == scope.get("node")
    if kind != "region":
        return False
    item_span = _item_span(record, item)
    start, end = scope.get("start"), scope.get("end")
    return (
        item_span is not None
        and type(start) is int
        and type(end) is int
        and start <= item_span[0]
        and item_span[1] <= end
    )


def _target_in_scope(record: dict[str, Any], target: str, scope: dict[str, Any]) -> bool:
    item = _record_objects(record).get(target)
    return isinstance(item, dict) and _in_scope(record, item, scope)


def _region_contains(outer: dict[str, Any], inner: dict[str, Any]) -> bool:
    return (
        outer.get("kind") == "region"
        and inner.get("kind") == "region"
        and type(outer.get("start")) is int
        and type(outer.get("end")) is int
        and type(inner.get("start")) is int
        and type(inner.get("end")) is int
        and outer["start"] <= inner["start"]
        and inner["end"] <= outer["end"]
    )


def _more_specific_scope(
    record: dict[str, Any],
    dimension: str,
    target: str,
    current_scope: dict[str, Any],
) -> bool:
    dimensions = record.get("annotation_scope", {}).get("dimensions", [])
    if not isinstance(dimensions, list):
        return False
    for entry in dimensions:
        if not isinstance(entry, dict) or entry.get("dimension") != dimension:
            continue
        other_scope = entry.get("scope")
        if not isinstance(other_scope, dict):
            continue
        if other_scope == current_scope:
            continue
        other_kind = other_scope.get("kind")
        current_kind = current_scope.get("kind")
        if current_kind == "node" or other_kind == "record":
            continue
        if other_kind == "node":
            if _target_in_scope(record, target, other_scope):
                return True
        elif other_kind == "region":
            if current_kind == "record" and _target_in_scope(record, target, other_scope):
                return True
            if current_kind == "region" and _region_contains(current_scope, other_scope) and _target_in_scope(record, target, other_scope):
                return True
    return False


def _payload_targets(
    record: dict[str, Any],
    field_name: str,
    item: Any,
    *,
    np_internal: bool = False,
) -> tuple[str, ...]:
    if field_name in {"words", "constituents", "clauses"}:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
            return ()
        targets = [item["id"]]
        if np_internal and (item.get("node_kind") != "phrase" or item.get("phrase_category") != "NP"):
            item_span = _item_span(record, item)
            if item_span is not None:
                constituents = record.get("constituents")
                if isinstance(constituents, list):
                    for ancestor in constituents:
                        if not isinstance(ancestor, dict) or ancestor.get("phrase_category") != "NP" or ancestor.get("id") == item.get("id"):
                            continue
                        ancestor_span = _item_span(record, ancestor)
                        if ancestor_span is not None and ancestor_span[0] <= item_span[0] and item_span[1] <= ancestor_span[1] and isinstance(ancestor.get("id"), str):
                            targets.append(ancestor["id"])
        return tuple(targets)
    if field_name == "lexical_valency" and isinstance(item, dict):
        target = normalize_predicate_reference(record, item.get("predicate"))
        return (target,) if target is not None else ()
    if field_name in {"complements", "adjuncts"} and isinstance(item, str) and item:
        return (item,)
    if field_name == "typed_relation" and isinstance(item, dict):
        targets: list[str] = []
        for reference_field in ("source", "target"):
            reference = item.get(reference_field)
            if isinstance(reference, dict) and isinstance(reference.get("id"), str) and reference["id"]:
                targets.append(reference["id"])
            elif isinstance(reference, str) and ":" in reference and reference.split(":", 1)[1]:
                targets.append(reference.split(":", 1)[1])
        return tuple(targets)
    return ()


def _payload_owned_in_scope(
    record: dict[str, Any],
    dimension: str,
    targets: tuple[str, ...],
    scope: dict[str, Any],
) -> bool:
    kind = scope.get("kind")
    if kind == "node":
        return True
    if not targets:
        return kind == "record"
    for target in targets:
        if _target_in_scope(record, target, scope) and not _more_specific_scope(record, dimension, target, scope):
            return True
    return False


def _subtree_scope(record: dict[str, Any], item: dict[str, Any], scope: dict[str, Any]) -> bool:
    if scope.get("kind") != "node":
        return _in_scope(record, item, scope)
    target = _record_objects(record).get(scope.get("node"))
    if not isinstance(target, dict):
        return False
    target_span = _item_span(record, target)
    item_span = _item_span(record, item)
    return target_span is not None and item_span is not None and target_span[0] <= item_span[0] and item_span[1] <= target_span[1]


def _word_status(word: dict[str, Any]) -> str:
    analysis = word.get("lexical_analysis")
    if isinstance(analysis, dict) and analysis.get("status") == "unresolved":
        return "unresolved"
    category = word.get("lexical_category")
    if isinstance(category, str) and category in LEXICAL_CATEGORIES:
        return "resolved"
    return "missing"


def _ref_kind(objects: dict[str, dict[str, Any]], value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    item = objects.get(value)
    return item.get("node_kind") if isinstance(item, dict) else None


def _clause_ids(record: dict[str, Any]) -> set[str]:
    clauses = record.get("clauses")
    if not isinstance(clauses, list):
        return set()
    return {item["id"] for item in clauses if isinstance(item, dict) and isinstance(item.get("id"), str)}


def _constituent_ids(record: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for field_name in ("constituents", "clauses"):
        values = record.get(field_name)
        if not isinstance(values, list):
            continue
        for item in values:
            if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"]:
                ids.add(item["id"])
    return ids


def _dependency_status(record: dict[str, Any], objects: dict[str, dict[str, Any]], value: Any) -> str:
    if not isinstance(value, dict):
        return "missing"
    relation = value.get("relation")
    if not isinstance(relation, str) or not relation:
        return "missing"
    head = value.get("head")
    dependent = value.get("dependent")
    if not isinstance(head, str) or head not in objects:
        return "missing"
    if not isinstance(dependent, str) or dependent not in objects:
        return "missing"
    for field in ("source", "target"):
        ref = value.get(field)
        if ref is not None and (not isinstance(ref, str) or ref not in objects):
            return "missing"
    return "resolved"


def _semantic_role_status(
    record: dict[str, Any],
    objects: dict[str, dict[str, Any]],
    constituent_ids: set[str],
    value: Any,
) -> str:
    if not isinstance(value, dict):
        return "missing"
    constituent = value.get("constituent")
    if not isinstance(constituent, str) or constituent not in constituent_ids:
        return "missing"
    role = value.get("role")
    if not isinstance(role, str) or role not in SEMANTIC_ROLES:
        return "missing"
    predicate = value.get("predicate")
    if predicate is not None and normalize_predicate_reference(record, predicate) is None:
        return "missing"
    return "resolved"


def _lexical_valency_status(record: dict[str, Any], objects: dict[str, dict[str, Any]], value: Any) -> str:
    if not isinstance(value, dict):
        return "missing"
    predicate = normalize_predicate_reference(record, value.get("predicate"))
    if predicate is None:
        return "missing"
    frame = value.get("frame")
    if not isinstance(frame, str) or not frame:
        return "missing"
    selected = value.get("selected_complements")
    if not isinstance(selected, list):
        return "missing"
    for reference in selected:
        if not isinstance(reference, str) or reference not in objects:
            return "missing"
        if _ref_kind(objects, reference) not in {"phrase", "clause"}:
            return "missing"
    return "resolved"


def _payload_span(record: dict[str, Any], item: dict[str, Any]) -> tuple[int, int] | None:
    """Structural span under the canonical contract: valid half-open token span
    that does not terminate at a punctuation token."""
    span = _item_span(record, item)
    if span is None:
        return None
    words = record.get("words")
    if isinstance(words, list) and 0 < span[1] <= len(words):
        last = words[span[1] - 1]
        if isinstance(last, dict) and last.get("lexical_category") == "punctuation":
            return None
    return span


def _optional_typed_reference(objects: dict[str, dict[str, Any]], item: dict[str, Any], field: str, kinds: set[str]) -> bool:
    if field not in item or item[field] is None:
        return True
    return _ref_kind(objects, item[field]) in kinds


_VALID_REALIZATION_RELATIONS = frozenset({"same_span_alias", "expanded_realization", "other"})


def _clause_span(record: dict[str, Any], clause_ref: str) -> tuple[int, int] | None:
    clauses = record.get("clauses")
    if not isinstance(clauses, list):
        return None
    for clause in clauses:
        if isinstance(clause, dict) and clause.get("id") == clause_ref:
            return _item_span(record, clause)
    return None


def _clause_wrapper_realization_is_valid(
    record: dict[str, Any],
    item: dict[str, Any],
    wrapper_span: tuple[int, int],
) -> bool:
    clause_ref = item.get("clause_ref")
    realization = item.get("realization")
    if not isinstance(realization, dict):
        return False
    if realization.get("clause_ref") != clause_ref:
        return False
    relation = realization.get("relation")
    if relation not in _VALID_REALIZATION_RELATIONS:
        return False
    if "span_relation" in item and item.get("span_relation") != relation:
        return False
    clause_sp = _clause_span(record, clause_ref)
    if clause_sp is None:
        return False
    if relation == "same_span_alias" and wrapper_span != clause_sp:
        return False
    if relation == "expanded_realization" and not (wrapper_span[0] <= clause_sp[0] and wrapper_span[1] >= clause_sp[1]):
        return False
    return True


def _constituent_status(record: dict[str, Any], item: dict[str, Any]) -> str:
    """Canonical payload status for one constituent-family node.

    Resolved requires every constituent-owned payload property to satisfy the
    canonical contract: identity, structural span, phrase category or existing
    clause reference, span_relation agreement, and head/parent reference kinds.
    Function and realization are syntactic-function-owned and stay out of scope.
    """
    if not isinstance(item.get("id"), str) or not item.get("id"):
        return "missing"
    wrapper_span = _payload_span(record, item)
    if wrapper_span is None:
        return "missing"
    objects = _record_objects(record)
    node_kind = item.get("node_kind")
    if node_kind == "phrase":
        category = item.get("phrase_category")
        if category not in PHRASE_CATEGORIES or category == "word":
            return "missing"
    elif node_kind == "clause":
        if item.get("phrase_category") is not None:
            return "missing"
        clause_ref = item.get("clause_ref")
        if not isinstance(clause_ref, str) or clause_ref not in _clause_ids(record):
            return "missing"
        if not _clause_wrapper_realization_is_valid(record, item, wrapper_span):
            return "missing"
    else:
        return "missing"
    if not _optional_typed_reference(objects, item, "head", {"word"}):
        return "missing"
    if not _optional_typed_reference(objects, item, "parent", {"phrase", "clause"}):
        return "missing"
    return "resolved"


def _integration_is_canonical(integration: Any) -> bool:
    return (
        isinstance(integration, list)
        and bool(integration)
        and all(isinstance(value, str) and value in CLAUSE_INTEGRATIONS for value in integration)
        and len(integration) == len(set(integration))
        and ("root" not in integration or len(integration) == 1)
        and ("unresolved" not in integration or len(integration) == 1)
    )


def _clause_subject_is_valid(objects: dict[str, dict[str, Any]], subject: Any) -> bool:
    if subject is None:
        return True
    kind = _ref_kind(objects, subject)
    if kind not in {"word", "phrase", "clause"}:
        return False
    target = objects[subject]
    if kind == "word":
        return target.get("lexical_category") in NOMINAL_SUBJECT_CATEGORIES
    if kind == "phrase":
        return target.get("phrase_category") == "NP"
    return True


def _clause_markers_are_valid(record: dict[str, Any], objects: dict[str, dict[str, Any]], item: dict[str, Any], span: tuple[int, int]) -> bool:
    if "marker_ids" not in item:
        return True
    markers = item["marker_ids"]
    if not isinstance(markers, list):
        return False
    words = record.get("words")
    words = words if isinstance(words, list) else []
    for marker in markers:
        if _ref_kind(objects, marker) != "word":
            return False
        index = next(
            (position for position, word in enumerate(words) if isinstance(word, dict) and word.get("id") == marker),
            None,
        )
        if index is not None and not span[0] <= index < span[1]:
            return False
    return True


def _integration_parent_is_valid(objects: dict[str, dict[str, Any]], clause_ids: set[str], parent: Any) -> bool:
    if parent is None:
        return True
    return isinstance(parent, str) and parent in clause_ids and _ref_kind(objects, parent) == "clause"


def _predicand_is_valid(objects: dict[str, dict[str, Any]], value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value in objects
    if not isinstance(value, dict):
        return False
    kind = value.get("kind")
    if not isinstance(kind, str) or kind not in PREDICAND_KINDS:
        return False
    target = value.get("target")
    if kind in PREDICAND_TARGET_REQUIRED_KINDS:
        return isinstance(target, str) and target in objects
    return target is None or (isinstance(target, str) and target in objects)


def _clause_status(record: dict[str, Any], item: dict[str, Any]) -> str:
    """Canonical payload status for one clause-family node.

    Resolved requires every clause-owned payload property to satisfy the
    canonical contract: identity, structural span, controlled finiteness,
    clause_construction, clause_form, and integration vocabularies plus the
    subject/head/marker_ids/integration_parent/predicand reference rules.
    Explicit canonical unresolved authority stays unresolved, never resolved;
    contradictory content (such as mixed integration values) is missing.
    """
    if not isinstance(item.get("id"), str) or not item.get("id"):
        return "missing"
    if item.get("node_kind") != "clause":
        return "missing"
    span = _payload_span(record, item)
    if span is None:
        return "missing"
    integration = item.get("integration")
    if not _integration_is_canonical(integration):
        return "missing"
    if item.get("clause_construction") == "unresolved" or item.get("finiteness") == "unspecified" or integration == ["unresolved"]:
        return "unresolved"
    finiteness = item.get("finiteness")
    if finiteness not in CLAUSE_FINITE_VALUES or item.get("clause_construction") not in CLAUSE_CONSTRUCTIONS:
        return "missing"
    clause_form = item.get("clause_form")
    if finiteness == "nonfinite":
        if clause_form not in CLAUSE_FORMS:
            return "missing"
    elif clause_form is not None:
        return "missing"
    objects = _record_objects(record)
    if not _clause_subject_is_valid(objects, item.get("subject")):
        return "missing"
    head = item.get("head")
    if head is not None and (not isinstance(head, str) or head not in objects):
        return "missing"
    if not _clause_markers_are_valid(record, objects, item, span):
        return "missing"
    if not _integration_parent_is_valid(objects, _clause_ids(record), item.get("integration_parent")):
        return "missing"
    if not _predicand_is_valid(objects, item.get("predicand")):
        return "missing"
    return "resolved"


def _typed_analyses(record: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any], bool]]:
    analyses: list[tuple[dict[str, Any], dict[str, Any], bool]] = []
    for field_name in ("canonical_analysis", "preferred_analysis"):
        analysis = record.get(field_name)
        if isinstance(analysis, dict) and isinstance(analysis.get("typed_analysis"), dict):
            analyses.append((analysis["typed_analysis"], analysis, True))
    alternatives = record.get("alternative_analyses")
    if isinstance(alternatives, list):
        for analysis in alternatives:
            if isinstance(analysis, dict) and isinstance(analysis.get("typed_analysis"), dict):
                analyses.append((analysis["typed_analysis"], analysis, False))
    return analyses


def _typed_relation_status(
    record: dict[str, Any],
    typed: dict[str, Any],
    relation: dict[str, Any],
    *,
    context: TypedRelationValidationContext | None = None,
) -> str:
    """Comprehensive typed relation status with structural validation.

    A1c: Validator-invalid typed relations must not be classified as resolved.
    A1c1: Uses shared context for parity across validator/collector/renderer.
    """
    if not isinstance(relation, dict):
        return "missing"

    if not validate_typed_analysis_container(typed):
        return "missing"

    ctx = context if context is not None else TypedRelationValidationContext(
        valid_analysis_entity_ids=valid_analysis_entity_ids(typed),
    )

    return validate_typed_relation_structure(
        relation,
        typed,
        record,
        context=ctx,
    )


_CANONICAL_TYPED_REFERENCE_NAMESPACES = frozenset({"word", "constituent", "clause"})

_NAMESPACE_COLLECTION_MAP: dict[str, str] = {
    "word": "words",
    "constituent": "constituents",
    "clause": "clauses",
}


def _namespace_collection_has_id(record: dict[str, Any], namespace: str, identifier: str) -> bool:
    collection_name = _NAMESPACE_COLLECTION_MAP.get(namespace)
    if collection_name is None:
        return False
    collection = record.get(collection_name)
    if not isinstance(collection, list):
        return False
    return any(
        isinstance(item, dict) and item.get("id") == identifier
        for item in collection
    )


def _typed_relation_canonical_targets(
    record: dict[str, Any],
    relation: dict[str, Any],
) -> list[str]:
    """Return canonical object IDs referenced by a typed relation's endpoints.

    Only word/constituent/clause namespace references that resolve to actual
    canonical objects in the namespace-specific collection are routing targets.
    Analysis-local and dangling references are not canonical routing targets.
    Namespace kind must match: word references only resolve against words,
    constituent references against constituents, clause references against clauses.
    """
    targets: list[str] = []
    for reference_field in ("source", "target"):
        parsed = parse_typed_reference(relation.get(reference_field))
        if parsed is None:
            continue
        namespace, identifier = parsed
        if namespace in _CANONICAL_TYPED_REFERENCE_NAMESPACES and _namespace_collection_has_id(record, namespace, identifier):
            targets.append(identifier)
    return targets


def _typed_relation_all_endpoints_routable(
    record: dict[str, Any],
    relation: dict[str, Any],
) -> bool:
    """Check whether every present endpoint of a typed relation is routable.

    Returns False if any endpoint is unparseable, uses an unknown namespace,
    or references a missing identifier in the namespace-specific collection.
    Analysis-local references are not canonical routing targets but are
    considered routable for scope-exclusion purposes.
    """
    for reference_field in ("source", "target"):
        reference = relation.get(reference_field)
        if reference is None:
            continue
        parsed = parse_typed_reference(reference)
        if parsed is None:
            return False
        namespace, identifier = parsed
        if namespace == "analysis":
            continue
        if namespace not in _CANONICAL_TYPED_REFERENCE_NAMESPACES:
            return False
        if not _namespace_collection_has_id(record, namespace, identifier):
            return False
    return True


def _typed_relation_owned_in_scope(
    record: dict[str, Any],
    dimension: str,
    relation: dict[str, Any],
    scope: dict[str, Any],
) -> bool:
    """Typed-relation-specific scope routing.

    Canonical routing targets (word/constituent/clause references resolving to
    actual objects in the namespace-specific collection) determine node/region
    ownership. When no canonical routing target exists, record scope is the
    fallback authority location.

    A relation with any malformed/unroutable endpoint must not be excluded from
    record scope by more-specific ownership. Only structurally routable relations
    may be excluded from record scope when all canonical targets have a
    more-specific scope owner.
    """
    canonical_targets = _typed_relation_canonical_targets(record, relation)
    kind = scope.get("kind")

    if kind == "record":
        if not canonical_targets:
            return True
        if not _typed_relation_all_endpoints_routable(record, relation):
            return True
        for target in canonical_targets:
            if not _more_specific_scope(record, dimension, target, scope):
                return True
        return False

    if kind == "node":
        return scope.get("node") in canonical_targets

    if kind == "region":
        objects = _record_objects(record)
        return any(
            _in_scope(record, objects[target], scope)
            for target in canonical_targets
            if target in objects
        )

    return False


def _typed_relation_items(
    record: dict[str, Any],
    spec: DimensionSpec,
    scope: dict[str, Any],
    accumulator: _PayloadAccumulator,
) -> None:
    relation_specs = [payload for payload in spec.payloads if payload.field == "typed_relation" and payload.relation_types]
    relation_types = set().union(*(payload.relation_types for payload in relation_specs)) if relation_specs else set()
    if not relation_types:
        return

    # Compute relation ID occurrences across all analyses for duplicate detection
    relation_id_occurrences: dict[str, int] = {}
    for typed, _analysis, _preferred in _typed_analyses(record):
        relations = typed.get("relations")
        if not isinstance(relations, list):
            continue
        for relation in relations:
            if isinstance(relation, dict):
                relation_id = relation.get("id")
                if isinstance(relation_id, str) and relation_id:
                    relation_id_occurrences[relation_id] = relation_id_occurrences.get(relation_id, 0) + 1

    dep_pairs = _canonical_dependency_pairs(record)

    for typed, _analysis, preferred_authority in _typed_analyses(record):
        relations = typed.get("relations")
        if not isinstance(relations, list):
            continue
        ctx = TypedRelationValidationContext(
            preferred_authority=preferred_authority,
            relation_id_occurrences=relation_id_occurrences,
            valid_analysis_entity_ids=valid_analysis_entity_ids(typed),
            canonical_dependency_pairs=dep_pairs,
        )
        for index, relation in enumerate(relations):
            if not isinstance(relation, dict) or relation.get("type") not in relation_types:
                continue
            if not _typed_relation_owned_in_scope(record, spec.name, relation, scope):
                continue
            identifier = relation.get("id") if isinstance(relation.get("id"), str) else f"typed_relation[{index}]"
            status = _typed_relation_status(
                record,
                typed,
                relation,
                context=ctx,
            )
            accumulator.add(identifier, "typed_relation", status)


def _collect_words(record: dict[str, Any], spec: DimensionSpec, scope: dict[str, Any], accumulator: _PayloadAccumulator, lexical: bool) -> None:
    if not _has_field(spec, "words"):
        return
    words = record.get("words")
    if not isinstance(words, list):
        return
    for item in words:
        if not isinstance(item, dict) or not _in_scope(record, item, scope):
            continue
        identifier = item.get("id") if isinstance(item.get("id"), str) else "word"
        targets = _payload_targets(record, "words", item)
        if not _payload_owned_in_scope(record, spec.name, targets, scope):
            continue
        if lexical:
            accumulator.add(identifier, "words", _word_status(item))
        else:
            status = "resolved" if all(isinstance(item.get(field_name), str) and item[field_name] for field_name in ("id", "form", "lemma")) else "missing"
            accumulator.add(identifier, "words", status)


def _collect_constituents(record: dict[str, Any], spec: DimensionSpec, scope: dict[str, Any], accumulator: _PayloadAccumulator, np_internal: bool = False) -> None:
    if not _has_field(spec, "constituents"):
        return
    constituents = record.get("constituents")
    if not isinstance(constituents, list):
        return
    np_nodes = [
        item for item in constituents
        if isinstance(item, dict) and item.get("node_kind") == "phrase" and item.get("phrase_category") == "NP"
    ]
    for item in constituents:
        if not isinstance(item, dict):
            continue
        if np_internal:
            if item.get("node_kind") != "phrase" or item.get("phrase_category") not in PHRASE_CATEGORIES:
                continue
            if scope.get("kind") == "node":
                target = _record_objects(record).get(scope.get("node"))
                if not isinstance(target, dict) or target.get("phrase_category") != "NP" or not _subtree_scope(record, item, scope):
                    continue
            elif not _in_scope(record, item, scope) or (
                item.get("phrase_category") != "NP"
                and not any(
                    ancestor.get("id") != item.get("id")
                    and _subtree_scope(record, item, {"kind": "node", "node": ancestor.get("id")})
                    for ancestor in np_nodes
                    if isinstance(ancestor.get("id"), str)
                )
            ):
                continue
        elif not _in_scope(record, item, scope):
            continue
        targets = _payload_targets(record, "constituents", item, np_internal=np_internal)
        if not _payload_owned_in_scope(record, spec.name, targets, scope):
            continue
        identifier = item.get("id") if isinstance(item.get("id"), str) else "constituent"
        accumulator.add(identifier, "constituents", _constituent_status(record, item))


def _collect_clauses(record: dict[str, Any], spec: DimensionSpec, scope: dict[str, Any], accumulator: _PayloadAccumulator) -> None:
    if not _has_field(spec, "clauses"):
        return
    clauses = record.get("clauses")
    if not isinstance(clauses, list):
        return
    for item in clauses:
        if not isinstance(item, dict) or not _in_scope(record, item, scope):
            continue
        targets = _payload_targets(record, "clauses", item)
        if not _payload_owned_in_scope(record, spec.name, targets, scope):
            continue
        identifier = item.get("id") if isinstance(item.get("id"), str) else "clause"
        accumulator.add(identifier, "clauses", _clause_status(record, item))


def _collect_functions(record: dict[str, Any], spec: DimensionSpec, scope: dict[str, Any], accumulator: _PayloadAccumulator) -> None:
    if _has_field(spec, "constituents"):
        constituents = record.get("constituents")
        if isinstance(constituents, list):
            for item in constituents:
                if not isinstance(item, dict) or not _in_scope(record, item, scope):
                    continue
                targets = _payload_targets(record, "constituents", item)
                if not _payload_owned_in_scope(record, spec.name, targets, scope):
                    continue
                identifier = item.get("id") if isinstance(item.get("id"), str) else "constituent"
                status = "resolved" if isinstance(item.get("function"), str) and item["function"] else "missing"
                accumulator.add(identifier, "constituents", status)
    if _has_field(spec, "words"):
        words = record.get("words")
        if isinstance(words, list):
            for item in words:
                if not isinstance(item, dict) or not _in_scope(record, item, scope) or "syntactic_function" not in item:
                    continue
                targets = _payload_targets(record, "words", item)
                if not _payload_owned_in_scope(record, spec.name, targets, scope):
                    continue
                identifier = item.get("id") if isinstance(item.get("id"), str) else "word"
                status = "resolved" if isinstance(item.get("syntactic_function"), str) and item["syntactic_function"] else "missing"
                accumulator.add(identifier, "words", status)


_COMPLEMENTATION_FUNCTIONS = frozenset({
    "adjunct", "complement", "selected_complement", "selected_locative_complement",
    "object_predicative_complement", "subject_predicative_complement",
})


def _collect_complementation(record: dict[str, Any], spec: DimensionSpec, scope: dict[str, Any], accumulator: _PayloadAccumulator) -> None:
    if _has_field(spec, "constituents"):
        constituents = record.get("constituents")
        if isinstance(constituents, list):
            for item in constituents:
                if not isinstance(item, dict) or not _in_scope(record, item, scope) or item.get("function") not in _COMPLEMENTATION_FUNCTIONS:
                    continue
                targets = _payload_targets(record, "constituents", item)
                if not _payload_owned_in_scope(record, spec.name, targets, scope):
                    continue
                identifier = item.get("id") if isinstance(item.get("id"), str) else "constituent"
                accumulator.add(identifier, "constituents", "resolved")
    if _has_field(spec, "lexical_valency"):
        values = record.get("lexical_valency")
        if isinstance(values, list):
            objects = _record_objects(record)
            for index, item in enumerate(values):
                if not isinstance(item, dict):
                    if scope.get("kind") == "record":
                        accumulator.add(f"lexical_valency[{index}]", "lexical_valency", "missing")
                    continue
                predicate = normalize_predicate_reference(record, item.get("predicate"))
                if predicate is None:
                    if scope.get("kind") == "record":
                        accumulator.add(f"lexical_valency[{index}]", "lexical_valency", "missing")
                    continue
                if scope.get("kind") != "record":
                    predicate_object = objects.get(predicate)
                    if predicate_object is None or not _in_scope(record, predicate_object, scope):
                        continue
                if not _payload_owned_in_scope(record, spec.name, (predicate,), scope):
                    continue
                status = _lexical_valency_status(record, objects, item)
                accumulator.add(predicate or f"lexical_valency[{index}]", "lexical_valency", status)
    for field_name in ("complements", "adjuncts"):
        if not _has_field(spec, field_name):
            continue
        values = record.get(field_name)
        if not isinstance(values, list):
            continue
        objects = _record_objects(record)
        for index, value in enumerate(values):
            if not isinstance(value, str) or value not in objects or not _in_scope(record, objects[value], scope):
                continue
            if not _payload_owned_in_scope(record, spec.name, (value,), scope):
                continue
            accumulator.add(f"{field_name}[{index}]", field_name, "resolved")
    _typed_relation_items(record, spec, scope, accumulator)


def _construction_signature_status(value: Any) -> str:
    if not isinstance(value, dict):
        return "missing"
    required = ("predicate_lemma", "construction_type", "argument_pattern", "function_pattern")
    if not all(isinstance(value.get(field_name), str) and value[field_name] for field_name in required[:2]):
        return "missing"
    if not all(
        isinstance(value.get(field_name), list)
        and value[field_name]
        and all(isinstance(item, str) and item for item in value[field_name])
        for field_name in required[2:]
    ):
        return "missing"
    return "resolved" if len(value["argument_pattern"]) == len(value["function_pattern"]) else "missing"


def _collect_construction(record: dict[str, Any], spec: DimensionSpec, accumulator: _PayloadAccumulator) -> None:
    field_values = (
        ("construction_signature", _construction_signature_status(record.get("construction_signature"))),
        ("construction_type", "resolved" if isinstance(record.get("construction_type"), str) and record["construction_type"] else "missing"),
        ("construction_tags", "resolved" if isinstance(record.get("construction_tags"), list) and any(isinstance(value, str) and value for value in record["construction_tags"]) else "missing"),
    )
    for field_name, status in field_values:
        if _has_field(spec, field_name) and field_name in record:
            accumulator.add(field_name, field_name, status)
    objects = _record_objects(record)
    for field_name in ("heads", "complements", "adjuncts", "fusion_relations"):
        if not _has_field(spec, field_name):
            continue
        values = record.get(field_name)
        if not isinstance(values, list):
            continue
        for index, value in enumerate(values):
            status = "missing"
            if field_name == "heads":
                status = "resolved" if isinstance(value, dict) and isinstance(value.get("head"), str) and value["head"] in objects and isinstance(value.get("dependent"), str) and value["dependent"] in objects else "missing"
            elif field_name in {"complements", "adjuncts"}:
                status = "resolved" if isinstance(value, str) and value in objects else "missing"
            else:
                required = ("id", "type", "fused_element", "whole_constituent", "relative_clause", "fused_functions")
                status = "resolved" if (
                    isinstance(value, dict)
                    and isinstance(value.get("id"), str)
                    and isinstance(value.get("type"), str)
                    and isinstance(value.get("fused_element"), str)
                    and value["fused_element"] in objects
                    and isinstance(value.get("whole_constituent"), str)
                    and value["whole_constituent"] in objects
                    and isinstance(value.get("relative_clause"), str)
                    and value["relative_clause"] in objects
                    and isinstance(value.get("fused_functions"), list)
                    and len(value["fused_functions"]) >= 2
                    and all(isinstance(function, str) and function for function in value["fused_functions"])
                ) else "missing"
            accumulator.add(f"{field_name}[{index}]", field_name, status)
    _typed_relation_items(record, spec, {"kind": "record"}, accumulator)


def _construction_payload_item_status(record: dict[str, Any], field_name: str, value: Any) -> str:
    objects = _record_objects(record)
    if field_name == "construction_signature":
        return _construction_signature_status(value)
    if field_name == "construction_type":
        return "resolved" if isinstance(value, str) and value else "missing"
    if field_name == "construction_tags":
        return "resolved" if isinstance(value, list) and any(isinstance(item, str) and item for item in value) else "missing"
    if field_name == "heads":
        return "resolved" if (
            isinstance(value, dict)
            and isinstance(value.get("head"), str)
            and value["head"] in objects
            and isinstance(value.get("dependent"), str)
            and value["dependent"] in objects
        ) else "missing"
    if field_name in {"complements", "adjuncts"}:
        return "resolved" if isinstance(value, str) and value in objects else "missing"
    if field_name == "fusion_relations":
        required = ("id", "type", "fused_element", "whole_constituent", "relative_clause", "fused_functions")
        return "resolved" if (
            isinstance(value, dict)
            and isinstance(value.get("id"), str)
            and isinstance(value.get("type"), str)
            and isinstance(value.get("fused_element"), str)
            and value["fused_element"] in objects
            and isinstance(value.get("whole_constituent"), str)
            and value["whole_constituent"] in objects
            and isinstance(value.get("relative_clause"), str)
            and value["relative_clause"] in objects
            and isinstance(value.get("fused_functions"), list)
            and len(value["fused_functions"]) >= 2
            and all(isinstance(function, str) and function for function in value["fused_functions"])
        ) else "missing"
    return "missing"


CONSTRUCTION_RELATION_DIMENSION = "construction_relations"

_NESTED_GOVERNANCE_KEYS = frozenset({"status", "notes", "note"})


def construction_typed_relation_types() -> frozenset[str]:
    """Return the typed relation types the registry declares construction-owned."""
    spec = dimension_spec(CONSTRUCTION_RELATION_DIMENSION)
    if spec is None:
        return frozenset()
    relation_types: set[str] = set()
    for payload in spec.payloads:
        if payload.field == "typed_relation":
            relation_types.update(payload.relation_types)
    return frozenset(relation_types)


def typed_relation_owner_dimensions(relation_type: Any) -> frozenset[str]:
    """Return registry dimensions other than construction that own one typed relation type."""
    if not isinstance(relation_type, str) or not relation_type:
        return frozenset()
    return frozenset(
        spec.name
        for spec in DIMENSION_REGISTRY.values()
        if spec.name != CONSTRUCTION_RELATION_DIMENSION
        for payload in spec.payloads
        if payload.field == "typed_relation" and relation_type in payload.relation_types
    )


def typed_argument_owner_dimensions(argument: Any) -> frozenset[str]:
    """Return registry dimensions other than construction whose typed_arguments ownership covers this item.

    Ownership requires that every linguistic property of the nested argument falls
    inside the dimension's declared ``typed_arguments`` property set; a mere field
    listing is not treated as participation evidence.
    """
    if not isinstance(argument, dict):
        return frozenset()
    properties = {key for key in argument if key not in _NESTED_GOVERNANCE_KEYS}
    if not properties:
        return frozenset()
    return frozenset(
        spec.name
        for spec in DIMENSION_REGISTRY.values()
        if spec.name != CONSTRUCTION_RELATION_DIMENSION
        for payload in spec.payloads
        if payload.field == "typed_arguments" and properties <= payload.properties
    )


def typed_analysis_relation_entries(record: dict[str, Any]) -> list[tuple[tuple[str | int, ...], dict[str, Any]]]:
    """Return every typed relation paired with its analysis-local container path."""
    entries: list[tuple[tuple[str | int, ...], dict[str, Any]]] = []
    for analysis_path, typed, _preferred in _typed_analysis_paths(record):
        relations = typed.get("relations")
        if not isinstance(relations, list):
            continue
        for relation in relations:
            if isinstance(relation, dict):
                entries.append((analysis_path, relation))
    return entries


def _typed_nested_status(typed: dict[str, Any], value: Any) -> str:
    if not isinstance(value, dict):
        return "missing"
    status = value.get("status", typed.get("status"))
    if status in {"descriptive", "established"}:
        return "resolved"
    if status in {"unresolved", "review_required"}:
        return "unresolved"
    return "missing"


def _typed_entity_status(typed: dict[str, Any], entity: Any) -> str:
    if not isinstance(entity, dict) or not isinstance(entity.get("id"), str) or not entity["id"] or not isinstance(entity.get("kind"), str) or not entity["kind"]:
        return "missing"
    return _typed_nested_status(typed, entity)


def _typed_entity_status_with_duplicates(
    typed: dict[str, Any],
    entity: Any,
    entity_id_occurrences: dict[str, int],
) -> str:
    """Entity status with duplicate ID detection.

    A1c: Duplicate entity IDs within the same typed analysis must not be clean resolved authority.
    """
    if not isinstance(entity, dict):
        return "missing"

    entity_id = entity.get("id")
    if not isinstance(entity_id, str) or not entity_id:
        return "missing"

    # Check for duplicate entity IDs
    if entity_id_occurrences.get(entity_id, 0) > 1:
        return "missing"

    if not isinstance(entity.get("kind"), str) or not entity["kind"]:
        return "missing"

    return _typed_nested_status(typed, entity)


def _typed_argument_entries(
    typed: dict[str, Any],
    spec: DimensionSpec,
    analysis_path: tuple[str | int, ...],
) -> list[tuple[str, Any, tuple[str | int, ...]]]:
    entries: list[tuple[str, Any, tuple[str | int, ...]]] = []
    if "arguments" not in typed or typed.get("arguments") is None:
        return entries
    value = typed["arguments"]
    payload = _payload_spec(spec, "typed_arguments")
    argument_fields = set(payload.properties) if payload is not None else set()

    def identifier_for(item: Any, fallback: str) -> str:
        if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"]:
            return item["id"]
        return fallback

    if isinstance(value, list):
        for index, item in enumerate(value):
            entries.append((identifier_for(item, f"typed_arguments[{index}]"), item, analysis_path + ("arguments", index)))
    elif isinstance(value, dict):
        if any(key in argument_fields for key in value):
            entries.append((identifier_for(value, "typed_arguments"), value, analysis_path + ("arguments",)))
        else:
            for key, item in value.items():
                entries.append((identifier_for(item, f"typed_arguments[{key}]"), item, analysis_path + ("arguments", key)))
    elif value not in (None, {}, []):
        entries.append(("typed_arguments", value, analysis_path + ("arguments",)))
    return entries


def _typed_entity_entries(
    typed: dict[str, Any],
    analysis_path: tuple[str | int, ...],
) -> list[tuple[str, Any, tuple[str | int, ...]]]:
    entries: list[tuple[str, Any, tuple[str | int, ...]]] = []
    if "entities" not in typed or typed.get("entities") is None:
        return entries
    entities = typed["entities"]
    if isinstance(entities, list):
        for index, entity in enumerate(entities):
            identifier = entity.get("id") if isinstance(entity, dict) and isinstance(entity.get("id"), str) and entity["id"] else f"typed_entity[{index}]"
            entries.append((identifier, entity, analysis_path + ("entities", index)))
    elif entities not in (None, {}, []):
        entries.append(("typed_entity", entities, analysis_path + ("entities",)))
    return entries


def _construction_typed_payload_items(
    record: dict[str, Any],
    spec: DimensionSpec,
) -> list[AuthoritativePayloadItem]:
    items: list[AuthoritativePayloadItem] = []
    relation_specs = [
        payload for payload in spec.payloads
        if payload.field == "typed_relation" and payload.relation_types
    ]
    relation_types = set().union(*(payload.relation_types for payload in relation_specs)) if relation_specs else set()

    # Compute relation ID occurrences across all analyses for duplicate detection
    relation_id_occurrences: dict[str, int] = {}
    for _analysis_path, typed, _preferred in _typed_analysis_paths(record):
        relations = typed.get("relations")
        if not isinstance(relations, list):
            continue
        for relation in relations:
            if isinstance(relation, dict):
                relation_id = relation.get("id")
                if isinstance(relation_id, str) and relation_id:
                    relation_id_occurrences[relation_id] = relation_id_occurrences.get(relation_id, 0) + 1

    dep_pairs = _canonical_dependency_pairs(record)

    for analysis_path, typed, preferred_authority in _typed_analysis_paths(record):
        ctx = TypedRelationValidationContext(
            preferred_authority=preferred_authority,
            relation_id_occurrences=relation_id_occurrences,
            valid_analysis_entity_ids=valid_analysis_entity_ids(typed),
            canonical_dependency_pairs=dep_pairs,
        )
        if relation_types and _has_field(spec, "typed_relation"):
            relations = typed.get("relations")
            if isinstance(relations, list):
                for index, relation in enumerate(relations):
                    if not isinstance(relation, dict) or relation.get("type") not in relation_types:
                        continue
                    identifier = relation.get("id") if isinstance(relation.get("id"), str) else f"typed_relation[{index}]"
                    items.append(AuthoritativePayloadItem(
                        field="typed_relation",
                        identifier=identifier,
                        value=relation,
                        status=_typed_relation_status(
                            record,
                            typed,
                            relation,
                            context=ctx,
                        ),
                        path=analysis_path + ("relations", index),
                    ))
            elif relations not in (None, {}, []):
                items.append(AuthoritativePayloadItem(
                    field="typed_relation",
                    identifier="typed_relation",
                    value=relations,
                    status="missing",
                    path=analysis_path + ("relations",),
                ))
        if _has_field(spec, "typed_arguments"):
            for identifier, value, path in _typed_argument_entries(typed, spec, analysis_path):
                items.append(AuthoritativePayloadItem(
                    field="typed_arguments",
                    identifier=identifier,
                    value=value,
                    status=_typed_nested_status(typed, value),
                    path=path,
                ))
        if _has_field(spec, "typed_entity"):
            # Compute entity ID occurrences for duplicate detection
            entity_id_occurrences: dict[str, int] = {}
            entities = typed.get("entities")
            if isinstance(entities, list):
                for entity in entities:
                    if isinstance(entity, dict):
                        entity_id = entity.get("id")
                        if isinstance(entity_id, str) and entity_id:
                            entity_id_occurrences[entity_id] = entity_id_occurrences.get(entity_id, 0) + 1

            for identifier, value, path in _typed_entity_entries(typed, analysis_path):
                status = _typed_entity_status_with_duplicates(typed, value, entity_id_occurrences)
                items.append(AuthoritativePayloadItem(
                    field="typed_entity",
                    identifier=identifier,
                    value=value,
                    status=status,
                    path=path,
                ))
    return items


def _typed_analysis_paths(record: dict[str, Any]) -> list[tuple[tuple[str | int, ...], dict[str, Any], bool]]:
    paths: list[tuple[tuple[str | int, ...], dict[str, Any], bool]] = []
    for field_name in ("canonical_analysis", "preferred_analysis"):
        analysis = record.get(field_name)
        if isinstance(analysis, dict) and isinstance(analysis.get("typed_analysis"), dict):
            paths.append(((field_name, "typed_analysis"), analysis["typed_analysis"], True))
    alternatives = record.get("alternative_analyses")
    if isinstance(alternatives, list):
        for index, analysis in enumerate(alternatives):
            if isinstance(analysis, dict) and isinstance(analysis.get("typed_analysis"), dict):
                paths.append((("alternative_analyses", index, "typed_analysis"), analysis["typed_analysis"], False))
    return paths


def authoritative_payload_items(record: dict[str, Any], dimension: str) -> tuple[AuthoritativePayloadItem, ...]:
    """Enumerate registry-owned construction payload for quarantine callers."""
    spec = dimension_spec(dimension)
    if spec is None or spec.payload_family != "construction_relation_collection":
        return ()
    items: list[AuthoritativePayloadItem] = []
    nested_fields = {"typed_analysis", "typed_arguments", "typed_entity", "typed_relation"}
    top_level_fields = {
        payload.field for payload in spec.payloads
        if payload.field not in nested_fields
    }
    for payload in spec.payloads:
        field_name = payload.field
        if field_name not in top_level_fields or field_name not in record:
            continue
        value = record[field_name]
        if field_name == "construction_tags":
            items.append(AuthoritativePayloadItem(
                field=field_name,
                identifier=field_name,
                value=value,
                status=_construction_payload_item_status(record, field_name, value),
                path=(field_name,),
            ))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                items.append(AuthoritativePayloadItem(
                    field=field_name,
                    identifier=f"{field_name}[{index}]",
                    value=item,
                    status=_construction_payload_item_status(record, field_name, item),
                    path=(field_name, index),
                ))
        else:
            items.append(AuthoritativePayloadItem(
                field=field_name,
                identifier=field_name,
                value=value,
                status=_construction_payload_item_status(record, field_name, value),
                path=(field_name,),
            ))
    items.extend(_construction_typed_payload_items(record, spec))
    return tuple(items)


def _collect_dependency_like(record: dict[str, Any], spec: DimensionSpec, accumulator: _PayloadAccumulator, field_name: str) -> None:
    if _has_field(spec, field_name):
        values = record.get(field_name)
        if isinstance(values, list):
            objects = _record_objects(record)
            constituent_ids = _constituent_ids(record)
            for index, value in enumerate(values):
                if field_name == "dependencies":
                    status = _dependency_status(record, objects, value)
                else:
                    status = _semantic_role_status(record, objects, constituent_ids, value)
                accumulator.add(f"{field_name}[{index}]", field_name, status)
    _typed_relation_items(record, spec, {"kind": "record"}, accumulator)


def _collect_valency(record: dict[str, Any], spec: DimensionSpec, scope: dict[str, Any], accumulator: _PayloadAccumulator) -> None:
    if not _has_field(spec, "lexical_valency"):
        return
    values = record.get("lexical_valency")
    if not isinstance(values, list):
        return
    objects = _record_objects(record)
    for index, item in enumerate(values):
        if not isinstance(item, dict):
            if scope.get("kind") == "record":
                accumulator.add(f"lexical_valency[{index}]", "lexical_valency", "missing")
            continue
        predicate = normalize_predicate_reference(record, item.get("predicate"))
        if predicate is None:
            if scope.get("kind") == "record":
                accumulator.add(f"lexical_valency[{index}]", "lexical_valency", "missing")
            continue
        predicate_object = objects.get(predicate)
        if scope.get("kind") != "record" and (predicate_object is None or not _in_scope(record, predicate_object, scope)):
            continue
        if not _payload_owned_in_scope(record, spec.name, (predicate,), scope):
            continue
        status = _lexical_valency_status(record, objects, item)
        accumulator.add(predicate or f"lexical_valency[{index}]", "lexical_valency", status)


def _collect_framework(record: dict[str, Any], spec: DimensionSpec, accumulator: _PayloadAccumulator) -> None:
    if not _has_field(spec, "framework") or not isinstance(record.get("framework"), dict):
        return
    accumulator.add("framework", "framework", "resolved" if isinstance(record["framework"].get("preferred"), str) and record["framework"]["preferred"] else "missing")


def _collect_payload(record: dict[str, Any], spec: DimensionSpec, scope: dict[str, Any], accumulator: _PayloadAccumulator) -> None:
    family = spec.payload_family
    if family == "word_collection":
        _collect_words(record, spec, scope, accumulator, lexical=False)
    elif family == "word_scalar_properties":
        _collect_words(record, spec, scope, accumulator, lexical=True)
    elif family == "constituent_collection":
        _collect_constituents(record, spec, scope, accumulator, np_internal=spec.name == "np_internal_constituency")
    elif family == "clause_collection":
        _collect_clauses(record, spec, scope, accumulator)
    elif family == "node_scalar_properties":
        _collect_functions(record, spec, scope, accumulator)
    elif family == "complementation_collection":
        _collect_complementation(record, spec, scope, accumulator)
    elif family == "dependency_collection":
        _collect_dependency_like(record, spec, accumulator, "dependencies")
    elif family == "semantic_role_collection":
        _collect_dependency_like(record, spec, accumulator, "semantic_roles")
    elif family == "valency_collection":
        _collect_valency(record, spec, scope, accumulator)
    elif family == "framework_scalar":
        _collect_framework(record, spec, accumulator)
    elif family == "construction_relation_collection":
        _collect_construction(record, spec, accumulator)


def _declared_confirmed_empty(record: dict[str, Any], dimension: str, target: str | None) -> bool:
    if target is not None and not isinstance(target, str):
        return False
    try:
        try:
            from coverage_resolution import CoverageState, declared_coverage_state
        except ImportError:
            from scripts.coverage_resolution import CoverageState, declared_coverage_state
        return declared_coverage_state(record, dimension, target) is CoverageState.CONFIRMED_EMPTY
    except (TypeError, ValueError):
        return False


def confirmed_empty_eligible(
    record: dict[str, Any],
    spec: DimensionSpec | None,
    payload: AuthoritativePayload,
) -> bool:
    """Whether a declared confirmed-empty is positively evidenced by the payload.

    Confirmed-empty means the annotator explicitly inspected the dimension and
    established that the applicable canonical collection contains zero items for
    this scope. It requires an explicit empty collection in the record; a
    non-empty list whose items are all owned by more-specific scopes does not
    satisfy the contract. The registry's ``requires_payload_field``/``content_field``
    contract is the single source of truth for which dimensions carry an explicit
    empty representation.
    """
    if spec is None or not spec.requires_payload_field or spec.content_field is None:
        return False
    if spec.content_field not in record:
        return False
    if not isinstance(record[spec.content_field], list):
        return False
    if record[spec.content_field] != []:
        return False
    return (
        payload.resolved_count == 0
        and payload.unresolved_count == 0
        and payload.missing_count == 0
    )


def authoritative_payload(
    record: dict[str, Any],
    dimension: str,
    target: str | dict[str, Any] | None = None,
) -> AuthoritativePayload:
    """Return authoritative payload facts for an effective target scope."""
    spec = dimension_spec(dimension)
    if spec is None:
        return AuthoritativePayload(dimension, target, AuthoritativePayloadState.ABSENT)
    target_validation = validate_coverage_target(record, dimension, target)
    if not target_validation.valid:
        return AuthoritativePayload(dimension, target, AuthoritativePayloadState.ABSENT)
    effective_target = None if target_validation.is_record_target else target_validation.normalized_target
    accumulator = _PayloadAccumulator()
    _collect_payload(record, spec, _scope(effective_target), accumulator)
    payload = accumulator.result(dimension, target)
    if _declared_confirmed_empty(record, dimension, effective_target if isinstance(effective_target, str) else None) and confirmed_empty_eligible(record, spec, payload):
        return accumulator.result(dimension, target, AuthoritativePayloadState.CONFIRMED_EMPTY)
    return payload


def authoritative_payload_state(
    record: dict[str, Any],
    dimension: str,
    target: str | dict[str, Any] | None = None,
) -> AuthoritativePayloadState:
    """Return the compact authoritative payload state for a target scope."""
    return authoritative_payload(record, dimension, target).state


payload_state = authoritative_payload_state
