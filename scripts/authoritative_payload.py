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
    from data_common import LEXICAL_CATEGORIES, PHRASE_CATEGORIES, SEMANTIC_ROLES
except ImportError:
    from scripts.data_common import LEXICAL_CATEGORIES, PHRASE_CATEGORIES, SEMANTIC_ROLES

try:
    from dimension_registry import DimensionSpec, PayloadSpec, dimension_spec
except ImportError:
    from scripts.dimension_registry import DimensionSpec, PayloadSpec, dimension_spec


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


def _constituent_status(record: dict[str, Any], item: dict[str, Any]) -> str:
    if not isinstance(item.get("id"), str) or not item.get("id"):
        return "missing"
    node_kind = item.get("node_kind")
    if node_kind == "phrase":
        return "resolved" if _item_span(record, item) is not None and item.get("phrase_category") in PHRASE_CATEGORIES and item.get("phrase_category") != "word" else "missing"
    if node_kind == "clause":
        return "resolved" if _item_span(record, item) is not None and isinstance(item.get("clause_ref"), str) and item.get("clause_ref") else "missing"
    return "missing"


def _clause_status(record: dict[str, Any], item: dict[str, Any]) -> str:
    if not isinstance(item.get("id"), str) or not item.get("id") or _item_span(record, item) is None:
        return "missing"
    if item.get("clause_construction") == "unresolved" or item.get("finiteness") == "unspecified" or "unresolved" in (item.get("integration") or []):
        return "unresolved"
    if item.get("finiteness") not in {"finite", "nonfinite", "verbless"} or not isinstance(item.get("clause_construction"), str) or not isinstance(item.get("integration"), list) or not item.get("integration"):
        return "missing"
    return "resolved"


def _typed_analyses(record: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    analyses: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for field_name in ("canonical_analysis", "preferred_analysis"):
        analysis = record.get(field_name)
        if isinstance(analysis, dict) and isinstance(analysis.get("typed_analysis"), dict):
            analyses.append((analysis["typed_analysis"], analysis))
    alternatives = record.get("alternative_analyses")
    if isinstance(alternatives, list):
        for analysis in alternatives:
            if isinstance(analysis, dict) and isinstance(analysis.get("typed_analysis"), dict):
                analyses.append((analysis["typed_analysis"], analysis))
    return analyses


def _typed_relation_status(typed: dict[str, Any], relation: dict[str, Any]) -> str:
    status = relation.get("status", typed.get("status"))
    if status in {"descriptive", "established"}:
        return "resolved"
    if status in {"unresolved", "review_required"}:
        return "unresolved"
    return "missing"


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
    for typed, _analysis in _typed_analyses(record):
        relations = typed.get("relations")
        if not isinstance(relations, list):
            continue
        for index, relation in enumerate(relations):
            if not isinstance(relation, dict) or relation.get("type") not in relation_types:
                continue
            references = _payload_targets(record, "typed_relation", relation)
            if scope.get("kind") != "record":
                if scope.get("kind") == "node" and scope.get("node") not in references:
                    continue
                if scope.get("kind") == "region":
                    objects = _record_objects(record)
                    if not any(_in_scope(record, objects[reference], scope) for reference in references if reference in objects):
                        continue
            if not _payload_owned_in_scope(record, spec.name, references, scope):
                continue
            identifier = relation.get("id") if isinstance(relation.get("id"), str) else f"typed_relation[{index}]"
            status = _typed_relation_status(typed, relation)
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
                status = "resolved" if isinstance(item.get("frame"), str) and item["frame"] and isinstance(item.get("selected_complements"), list) else "missing"
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


def _typed_reference_namespace_pair(reference: Any) -> tuple[Any, Any]:
    if isinstance(reference, str) and ":" in reference:
        namespace, identifier = reference.split(":", 1)
        return namespace, identifier
    if isinstance(reference, dict):
        return reference.get("namespace"), reference.get("id")
    return None, None


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


def _non_construction_referenced_entity_ids(typed: dict[str, Any], relation_types: set[str]) -> set[str]:
    """Collect entity ids referenced by relations outside the construction-owned types."""
    referenced: set[str] = set()
    relations = typed.get("relations")
    if not isinstance(relations, list):
        return referenced
    for relation in relations:
        if not isinstance(relation, dict) or relation.get("type") in relation_types:
            continue
        for key in ("source", "target"):
            namespace, identifier = _typed_reference_namespace_pair(relation.get(key))
            if namespace == "analysis" and isinstance(identifier, str) and identifier:
                referenced.add(identifier)
    return referenced


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
    preserved_ids: set[str],
) -> list[tuple[str, Any, tuple[str | int, ...]]]:
    entries: list[tuple[str, Any, tuple[str | int, ...]]] = []
    if "entities" not in typed or typed.get("entities") is None:
        return entries
    entities = typed["entities"]
    if isinstance(entities, list):
        for index, entity in enumerate(entities):
            if isinstance(entity, dict) and isinstance(entity.get("id"), str) and entity["id"] in preserved_ids:
                continue
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
    for analysis_path, typed in _typed_analysis_paths(record):
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
                        status=_typed_relation_status(typed, relation),
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
            preserved_ids = _non_construction_referenced_entity_ids(typed, relation_types)
            for identifier, value, path in _typed_entity_entries(typed, analysis_path, preserved_ids):
                items.append(AuthoritativePayloadItem(
                    field="typed_entity",
                    identifier=identifier,
                    value=value,
                    status=_typed_entity_status(typed, value),
                    path=path,
                ))
    return items


def _typed_analysis_paths(record: dict[str, Any]) -> list[tuple[tuple[str | int, ...], dict[str, Any]]]:
    paths: list[tuple[tuple[str | int, ...], dict[str, Any]]] = []
    for field_name in ("canonical_analysis", "preferred_analysis"):
        analysis = record.get(field_name)
        if isinstance(analysis, dict) and isinstance(analysis.get("typed_analysis"), dict):
            paths.append(((field_name, "typed_analysis"), analysis["typed_analysis"]))
    alternatives = record.get("alternative_analyses")
    if isinstance(alternatives, list):
        for index, analysis in enumerate(alternatives):
            if isinstance(analysis, dict) and isinstance(analysis.get("typed_analysis"), dict):
                paths.append((("alternative_analyses", index, "typed_analysis"), analysis["typed_analysis"]))
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
            for index, value in enumerate(values):
                if field_name == "dependencies":
                    status = "resolved" if isinstance(value, dict) and isinstance(value.get("relation"), str) and value["relation"] and isinstance(value.get("head"), str) and value["head"] in objects and isinstance(value.get("dependent"), str) and value["dependent"] in objects else "missing"
                else:
                    predicate = value.get("predicate") if isinstance(value, dict) else None
                    status = "resolved" if (
                        isinstance(value, dict)
                        and isinstance(value.get("constituent"), str)
                        and value["constituent"] in objects
                        and value.get("role") in SEMANTIC_ROLES
                        and (predicate is None or normalize_predicate_reference(record, predicate) is not None)
                    ) else "missing"
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
        status = "resolved" if isinstance(item.get("frame"), str) and item["frame"] and isinstance(item.get("selected_complements"), list) else "missing"
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
    if not accumulator.resolved_count and not accumulator.unresolved_count and _declared_confirmed_empty(record, dimension, effective_target if isinstance(effective_target, str) else None):
        return accumulator.result(dimension, target, AuthoritativePayloadState.CONFIRMED_EMPTY)
    return accumulator.result(dimension, target)


def authoritative_payload_state(
    record: dict[str, Any],
    dimension: str,
    target: str | dict[str, Any] | None = None,
) -> AuthoritativePayloadState:
    """Return the compact authoritative payload state for a target scope."""
    return authoritative_payload(record, dimension, target).state


payload_state = authoritative_payload_state
