#!/usr/bin/env python3
"""Render V0.4 canonical annotations into chat SFT JSONL."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

try:
    from coverage_resolution import CoverageResolutionError, CoverageState, collection_item_coverage_state, resolve_coverage
except ImportError:
    from scripts.coverage_resolution import CoverageResolutionError, CoverageState, collection_item_coverage_state, resolve_coverage

try:
    from collection_contract import normalize_collection_item
except ImportError:
    from scripts.collection_contract import normalize_collection_item

try:
    from data_common import read_jsonl
except ImportError:
    from scripts.data_common import read_jsonl

try:
    from dimension_registry import DIMENSION_REGISTRY, PROJECTION_FIELD_DIMENSIONS, dimension_spec, projection_property_dimensions
except ImportError:
    from scripts.dimension_registry import DIMENSION_REGISTRY, PROJECTION_FIELD_DIMENSIONS, dimension_spec, projection_property_dimensions


DEFAULT_SYSTEM = "You are English Syntax Tutor. Distinguish lexical category, phrase category, syntactic function, semantic role, and framework-specific terminology."

LINGUISTIC_FIELDS = {
    "sentence", "framework", "sentence_type", "sentence_type_metadata",
    "sentence_classification", "construction_type", "construction_signature",
    "construction_tags", "clauses", "constituents", "heads", "complements",
    "adjuncts", "words", "dependencies", "lexical_valency", "semantic_roles",
    "alternative_analyses", "pedagogical_aliases",
    "fusion_relations", "ambiguity", "rejected_analyses", "explanation", "rationale",
    "error_diagnosis", "canonical_analysis", "preferred_analysis",
}
LINGUISTIC_NESTED_FIELDS = {
    "framework": {"preferred", "notes"},
    "span": {"start", "end"},
    "sentence_type_metadata": {"scheme", "framework", "notes"},
    "sentence_classification": {"scheme", "label", "framework", "notes"},
    "construction_signature": {"predicate_lemma", "construction_type", "argument_pattern", "function_pattern"},
    "word": {"node_kind", "id", "form", "lemma", "lexical_category", "syntactic_function", "external_pos_tags", "morphology", "lexical_analysis"},
    "morphology": {"tense", "aspect", "mood", "number", "person", "form", "voice", "degree", "case", "features"},
    "lexical_analysis": {"candidates", "note"},
    "lexical_candidate": {"category", "lexical_category", "category_namespace", "framework", "syntactic_function", "claim"},
    "typed_analysis": {"kind", "framework", "arguments", "entities", "relations", "notes"},
    "typed_entity": {"id", "kind"},
    "typed_reference": {"namespace", "id"},
    "typed_arguments": {"id", "kind", "type", "target", "source", "head", "dependent", "relation", "role", "category", "function", "span", "clause_ref", "constituent_ref", "word_ref", "predicate", "value", "label"},
    "typed_relation": {"id", "kind", "type", "arity", "target", "source", "namespace", "framework", "role", "function", "category", "status", "note"},
    "analysis": {"label", "claims", "framework", "construction_type", "analysis_type", "typed_analysis"},
    "canonical_analysis": {"label", "claims", "framework", "construction_type", "analysis_type", "typed_analysis"},
    "preferred_analysis": {"label", "claims", "framework", "construction_type", "analysis_type", "typed_analysis"},
    "alternative_analysis": {"id", "label", "claims", "framework", "construction_type", "analysis_type", "status", "typed_analysis", "learner_explanation", "linked_wrapper_ids", "linked_constituent_ids", "linked_clause_refs", "linked_relation_ids"},
    "alternative_analyses": {"id", "label", "claims", "framework", "construction_type", "analysis_type", "status", "typed_analysis", "learner_explanation", "linked_wrapper_ids", "linked_constituent_ids", "linked_clause_refs", "linked_relation_ids"},
    "alternative_framework": {"framework", "analysis"},
    "clause": {"node_kind", "id", "span", "finiteness", "clause_form", "clause_construction", "integration", "subject", "predicand", "head", "marker_ids", "integration_parent"},
    "constituent": {"node_kind", "id", "span", "phrase_category", "clause_ref", "function", "head", "parent", "relation_label", "realization", "span_relation"},
    "dependency": {"relation", "head", "dependent", "note"},
    "head_relation": {"head", "dependent", "relation"},
    "valency": {"predicate", "frame", "selected_complements", "note"},
    "semantic_role": {"constituent", "role", "predicate"},
    "external_pos_tag": {"tagset", "tag"},
    "pedagogical_aliases": {"term", "framework", "applies_to"},
    "pedagogical_alias": {"term", "framework", "applies_to"},
    "ambiguity": {"status", "preferred_analysis", "analyses"},
    "ambiguity_analysis": {"id", "structural_claims", "interpretation", "framework", "preference_basis", "attachment", "target", "constituent", "clause", "alternative_ids", "wrapper_ids", "relation_ids", "constituent_ids", "clause_refs"},
    "error_diagnosis": {"student_analysis", "diagnoses"},
    "diagnosis": {"claim", "verdict", "error_level", "correct_analysis", "why"},
    "fusion_relations": {"id", "type", "fused_element", "whole_constituent", "relative_clause", "fused_functions", "external_function", "dependency"},
    "fusion_relation": {"id", "type", "fused_element", "whole_constituent", "relative_clause", "fused_functions", "external_function", "dependency"},
    "realization": {"clause_ref", "relation", "context", "layer"},
    "rejected_analyses": {"analysis", "reason"},
    "rejected": {"analysis", "reason"},
}
DIMENSION_FIELDS = {
    name: spec.primary_field
    for name, spec in DIMENSION_REGISTRY.items()
    if spec.primary_field is not None
}
DIMENSION_PROPERTY_MAP = {
    name: dict(spec.property_map)
    for name, spec in DIMENSION_REGISTRY.items()
}
GOVERNANCE_FIELDS = {
    "schema_version", "id", "split", "source_type", "difficulty", "capability_tags", "annotation_scope",
    "review_metadata", "migration_metadata", "migration_review_required", "migration_note", "provenance",
    "legacy_preferred_analysis", "legacy_annotation_scope", "legacy_annotations",
}
LEGACY_NESTED_FIELDS = {"legacy_function", "legacy_clause_category", "legacy_pos", "status", "review_required"}
RENDERING_MODES = {"default", "learner_facing"}
_CONTENT_COVERED_STATES = frozenset({CoverageState.COMPLETE, CoverageState.PARTIAL_COVERED})
_REFERENCE_KEYS = frozenset({
    "head", "dependent", "parent", "clause_ref", "integration_parent", "subject", "constituent",
    "attachment", "source", "target", "clause", "fused_element", "whole_constituent", "relative_clause",
    "selected_complements", "predicate", "marker_ids", "linked_wrapper_ids", "linked_constituent_ids",
    "linked_clause_refs", "linked_relation_ids", "constituent_ids", "clause_refs", "wrapper_ids",
})


def render_user(record: dict[str, Any]) -> str:
    if record.get("error_diagnosis"):
        return f"Diagnose the following proposed syntax analysis.\nSentence: {record['sentence']}\nProposed analysis: {record['error_diagnosis']['student_analysis']}"
    return f"Analyze the syntax of this sentence and explain the important constructions.\nSentence: {record['sentence']}"


def _without_governance(value: Any, context: str | None = None, *, rendering_mode: str = "default") -> Any:
    if isinstance(value, dict):
        allowed = LINGUISTIC_NESTED_FIELDS.get(context, set()) if context else set()
        result = {}
        for key, item in value.items():
            if key == "lexical_analysis" and rendering_mode != "learner_facing":
                continue
            if key in {"notes", "note"} and context in {"typed_analysis", "typed_relation"}:
                continue
            status_is_linguistic = key == "status" and context == "ambiguity"
            id_is_linguistic = key == "id" and context in {"word", "clause", "constituent", "ambiguity_analysis", "alternative_analysis", "typed_relation", "typed_entity", "typed_reference", "typed_arguments"}
            if (key in GOVERNANCE_FIELDS and not id_is_linguistic) or (key in LEGACY_NESTED_FIELDS and not status_is_linguistic):
                continue
            if allowed is not None and key not in allowed:
                continue
            child_context = {
                "framework": "framework", "lexical_analysis": "lexical_analysis", "typed_analysis": "typed_analysis",
                "arguments": "typed_arguments", "entities": "typed_entity", "relations": "typed_relation",
                "source": "typed_reference", "target": "typed_reference",
                "morphology": "morphology", "realization": "realization", "rejected_analyses": "rejected_analyses",
                "span": "span",
                "canonical_analysis": "analysis", "preferred_analysis": "analysis",
                "alternative_analyses": "alternative_analysis",
                "alternatives": "alternative_framework", "ambiguity": "ambiguity", "analyses": "ambiguity_analysis",
                "error_diagnosis": "error_diagnosis", "diagnoses": "diagnosis",
                "pedagogical_aliases": "pedagogical_alias", "fusion_relations": "fusion_relation",
                "clauses": "clause", "constituents": "constituent", "dependencies": "dependency",
                "heads": "head_relation", "lexical_valency": "valency", "semantic_roles": "semantic_role",
                "external_pos_tags": "external_pos_tag", "dependency": "dependency",
            }.get(key)
            result[key] = _without_governance(item, child_context, rendering_mode=rendering_mode)
        return result
    if isinstance(value, list):
        child_context = context
        child_context = {
            "words": "word", "candidates": "lexical_candidate", "clauses": "clause",
            "constituents": "constituent", "dependencies": "dependency", "heads": "head_relation",
            "lexical_valency": "valency", "semantic_roles": "semantic_role", "external_pos_tags": "external_pos_tag",
            "alternative_analyses": "alternative_analysis",
            "alternatives": "alternative_framework", "analyses": "ambiguity_analysis", "diagnoses": "diagnosis",
            "pedagogical_aliases": "pedagogical_alias", "fusion_relations": "fusion_relation", "rejected_analyses": "rejected",
            "arguments": "typed_arguments", "entities": "typed_entity", "relations": "typed_relation",
        }.get(context, context)
        return [_without_governance(item, child_context, rendering_mode=rendering_mode) for item in value]
    return copy.deepcopy(value)


def _content_flags(record: dict[str, Any]) -> list[str]:
    """Capture unresolved linguistic content in governance-only sidecar data."""
    flags: list[str] = []
    for index, word in enumerate(record.get("words", []) if isinstance(record.get("words"), list) else []):
        if isinstance(word, dict) and isinstance(word.get("lexical_analysis"), dict) and word["lexical_analysis"].get("status") == "unresolved":
            flags.append(f"words[{index}].lexical_analysis")
    for index, clause in enumerate(record.get("clauses", []) if isinstance(record.get("clauses"), list) else []):
        if not isinstance(clause, dict):
            continue
        if clause.get("clause_construction") == "unresolved" or "unresolved" in (clause.get("integration") or []):
            flags.append(f"clauses[{index}]")
        if clause.get("finiteness") == "unspecified":
            flags.append(f"clauses[{index}].finiteness")
    analyses: list[tuple[str, Any]] = []
    for field in ("canonical_analysis", "preferred_analysis"):
        if isinstance(record.get(field), dict):
            analyses.append((field, record[field]))
    for field in ("alternative_analyses",):
        for index, analysis in enumerate(record.get(field, []) if isinstance(record.get(field), list) else []):
            if isinstance(analysis, dict):
                analyses.append((f"{field}[{index}]", analysis))
    for path, analysis in analyses:
        typed = analysis.get("typed_analysis")
        if isinstance(typed, dict) and typed.get("status") in {"unresolved", "review_required"}:
            flags.append(f"{path}.typed_analysis")
    if record.get("migration_review_required") is True:
        flags.append("migration_review_required")
    if isinstance(record.get("migration_metadata"), dict) and record["migration_metadata"].get("review_required") is True:
        flags.append("migration_metadata.review_required")
    return flags


def _coverage_state(record: dict[str, Any], dimension: str, target: str | None = None) -> CoverageState | None:
    try:
        return resolve_coverage(record, dimension, target)
    except CoverageResolutionError:
        return None


def _covered(record: dict[str, Any], dimension: str, target: str | None = None) -> bool:
    return _coverage_state(record, dimension, target) in _CONTENT_COVERED_STATES


def _any_covered(record: dict[str, Any], dimensions: tuple[str, ...], target: str | None = None) -> bool:
    return any(_covered(record, dimension, target) for dimension in dimensions)


def _record_complete(record: dict[str, Any], dimensions: tuple[str, ...]) -> bool:
    return any(_coverage_state(record, dimension) == CoverageState.COMPLETE for dimension in dimensions)


def _record_complete_all(record: dict[str, Any], dimensions: tuple[str, ...]) -> bool:
    return all(_coverage_state(record, dimension) == CoverageState.COMPLETE for dimension in dimensions)


def _property_covered(record: dict[str, Any], field: str, property_name: str, target: str | None = None) -> bool:
    dimensions = projection_property_dimensions(field, property_name)
    return any(_covered(record, dimension, target) for dimension in dimensions)


def _raw_objects(record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    objects: dict[str, dict[str, Any]] = {}
    for collection in ("words", "constituents", "clauses"):
        values = record.get(collection)
        if not isinstance(values, list):
            continue
        for item in values:
            if isinstance(item, dict) and isinstance(item.get("id"), str):
                objects[item["id"]] = item
    return objects


def _span(value: Any) -> tuple[int, int] | None:
    if not isinstance(value, dict):
        return None
    start, end = value.get("start"), value.get("end")
    if type(start) is int and type(end) is int:
        return start, end
    return None


def _contains(outer: Any, inner: Any) -> bool:
    outer_span, inner_span = _span(outer), _span(inner)
    return outer_span is not None and inner_span is not None and outer_span[0] <= inner_span[0] and inner_span[1] <= outer_span[1]


def _constituent_ancestors(record: dict[str, Any], item: dict[str, Any]) -> list[dict[str, Any]]:
    values = [value for value in record.get("constituents", []) if isinstance(value, dict)]
    by_id = {value.get("id"): value for value in values if isinstance(value.get("id"), str)}
    ancestors: list[dict[str, Any]] = []
    parent = item.get("parent")
    seen: set[str] = set()
    while isinstance(parent, str) and parent not in seen:
        seen.add(parent)
        ancestor = by_id.get(parent)
        if ancestor is None:
            break
        ancestors.append(ancestor)
        parent = ancestor.get("parent")
    for candidate in values:
        if candidate is item or candidate.get("id") == item.get("id"):
            continue
        if candidate.get("phrase_category") == "NP" and _contains(candidate.get("span"), item.get("span")) and candidate not in ancestors:
            ancestors.append(candidate)
    return ancestors


def _np_internal_covered(record: dict[str, Any], item: dict[str, Any]) -> bool:
    identifier = item.get("id")
    if not isinstance(identifier, str):
        return False
    if _covered(record, "np_internal_constituency", identifier):
        return True
    return any(
        _covered(record, "np_internal_constituency", ancestor.get("id"))
        for ancestor in _constituent_ancestors(record, item)
        if isinstance(ancestor.get("id"), str)
        and ancestor.get("phrase_category") == "NP"
        and _covered(record, "np_internal_constituency", ancestor.get("id"))
    )


def _internal_omitted(record: dict[str, Any], item: dict[str, Any]) -> bool:
    scope = record.get("annotation_scope")
    dimensions = scope.get("dimensions", []) if isinstance(scope, dict) else []
    if not any(isinstance(entry, dict) and entry.get("dimension") == "np_internal_constituency" for entry in dimensions):
        return False
    for ancestor in _constituent_ancestors(record, item):
        if ancestor.get("phrase_category") != "NP":
            continue
        identifier = ancestor.get("id")
        if isinstance(identifier, str) and not _covered(record, "np_internal_constituency", identifier):
            state = _coverage_state(record, "np_internal_constituency", identifier)
            if state in {CoverageState.OMITTED, CoverageState.UNANNOTATED, CoverageState.OUT_OF_SCOPE, CoverageState.PARTIAL_UNCOVERED}:
                return True
    return False


def _target_span(record: dict[str, Any], target: str) -> tuple[int, int] | None:
    words = record.get("words")
    if isinstance(words, list):
        for index, word in enumerate(words):
            if isinstance(word, dict) and word.get("id") == target:
                return index, index + 1
    source = _raw_objects(record).get(target)
    span = _span(source.get("span")) if isinstance(source, dict) else None
    return span


def _target_in_scope(record: dict[str, Any], target: str, scope: dict[str, Any]) -> bool:
    if scope.get("kind") == "node":
        return scope.get("node") == target
    if scope.get("kind") != "region":
        return False
    target_span = _target_span(record, target)
    start, end = scope.get("start"), scope.get("end")
    return (
        target_span is not None
        and type(start) is int
        and type(end) is int
        and start <= target_span[0]
        and target_span[1] <= end
    )


def _explicit_nonrecord_coverage(record: dict[str, Any], dimension: str, target: str) -> bool:
    scope = record.get("annotation_scope")
    dimensions = scope.get("dimensions", []) if isinstance(scope, dict) else []
    if not any(
        isinstance(entry, dict)
        and entry.get("dimension") == dimension
        and isinstance(entry.get("scope"), dict)
        and entry["scope"].get("kind") != "record"
        and _target_in_scope(record, target, entry["scope"])
        and entry.get("completeness") in {"complete", "partial"}
        and entry.get("omission") == "none"
        and entry.get("evidence") != "unannotated"
        for entry in dimensions
    ):
        return False
    return _covered(record, dimension, target)


def _project_words(record: dict[str, Any], rendering_mode: str) -> list[dict[str, Any]] | None:
    values = record.get("words")
    if not isinstance(values, list):
        return None
    result: list[dict[str, Any]] = []
    for source in values:
        if not isinstance(source, dict) or not isinstance(source.get("id"), str):
            continue
        identifier = source["id"]
        token_covered = _property_covered(record, "words", "form", identifier)
        lexical_covered = _property_covered(record, "words", "lexical_category", identifier)
        function_covered = _property_covered(record, "words", "syntactic_function", identifier)
        item: dict[str, Any] = {"id": identifier, "node_kind": "word"}
        if token_covered:
            for key in ("form", "lemma"):
                if key in source:
                    item[key] = _without_governance(source[key], "word", rendering_mode=rendering_mode)
        if lexical_covered:
            for key in ("lexical_category", "external_pos_tags"):
                if key in source:
                    item[key] = _without_governance(source[key], "external_pos_tag" if key == "external_pos_tags" else "word", rendering_mode=rendering_mode)
            if rendering_mode == "learner_facing" and "lexical_analysis" in source:
                item["lexical_analysis"] = _without_governance(source["lexical_analysis"], "lexical_analysis", rendering_mode=rendering_mode)
        if function_covered and "syntactic_function" in source:
            item["syntactic_function"] = copy.deepcopy(source["syntactic_function"])
        if len(item) > 2:
            result.append(item)
    return result or None


def _project_clauses(record: dict[str, Any], rendering_mode: str) -> list[dict[str, Any]] | None:
    values = record.get("clauses")
    if not isinstance(values, list):
        return None
    result: list[dict[str, Any]] = []
    for source in values:
        if not isinstance(source, dict) or not isinstance(source.get("id"), str):
            continue
        identifier = source["id"]
        covered = _property_covered(record, "clauses", "finiteness", identifier)
        if not covered:
            continue
        item = {"id": identifier, "node_kind": "clause"}
        for key in ("span", "finiteness", "clause_form", "clause_construction", "integration", "subject", "predicand", "head", "marker_ids", "integration_parent"):
            if key in source:
                item[key] = _without_governance(source[key], "span" if key == "span" else "clause", rendering_mode=rendering_mode)
        result.append(item)
    return result or None


def _project_constituents(record: dict[str, Any], rendering_mode: str) -> list[dict[str, Any]] | None:
    values = record.get("constituents")
    if not isinstance(values, list):
        return None
    result: list[dict[str, Any]] = []
    for source in values:
        if not isinstance(source, dict) or not isinstance(source.get("id"), str):
            continue
        identifier = source["id"]
        phrase_covered = _property_covered(record, "constituents", "phrase_category", identifier)
        internal_covered = _np_internal_covered(record, source)
        function_covered = _property_covered(record, "constituents", "function", identifier)
        omitted_internal = _internal_omitted(record, source)
        if omitted_internal and not internal_covered:
            phrase_covered = False
            internal_covered = False
            if function_covered and not _explicit_nonrecord_coverage(record, "syntactic_function", identifier):
                function_covered = False
        if not any((phrase_covered, internal_covered, function_covered)):
            continue
        item: dict[str, Any] = {"id": identifier, "node_kind": source.get("node_kind", "phrase")}
        if phrase_covered or internal_covered:
            for key in ("span", "phrase_category", "head", "parent", "relation_label", "span_relation"):
                if key in source:
                    item[key] = _without_governance(source[key], "span" if key == "span" else "constituent", rendering_mode=rendering_mode)
        elif "span" in source:
            item["span"] = _without_governance(source["span"], "span", rendering_mode=rendering_mode)
        if function_covered and "function" in source:
            item["function"] = copy.deepcopy(source["function"])
        if function_covered and "clause_ref" in source:
            item["clause_ref"] = copy.deepcopy(source["clause_ref"])
        if function_covered and "realization" in source:
            item["realization"] = _without_governance(source["realization"], "realization", rendering_mode=rendering_mode)
        result.append(item)
    return result or None


def _project_relation_collection(record: dict[str, Any], field: str, dimension: str, identifiers: Any, rendering_mode: str) -> list[dict[str, Any]] | None:
    record_state = _coverage_state(record, dimension)
    values = record.get(field)
    spec = dimension_spec(dimension)
    if record_state == CoverageState.CONFIRMED_EMPTY:
        return []
    if not isinstance(values, list):
        return None
    context = {"dependencies": "dependency", "semantic_roles": "semantic_role", "heads": "head_relation"}.get(field, field)
    if spec is not None and spec.allowed_scope_kinds == frozenset({"record"}):
        if record_state != CoverageState.COMPLETE:
            return None
        result = []
        for value in values:
            normalized = normalize_collection_item(record, dimension, value)
            if normalized is not None:
                result.append(_without_governance(normalized, context, rendering_mode=rendering_mode))
        return result or None
    if record_state == CoverageState.COMPLETE:
        return [_without_governance(item, context, rendering_mode=rendering_mode) for item in values]
    if record_state in {CoverageState.OMITTED, CoverageState.UNANNOTATED, CoverageState.OUT_OF_SCOPE, CoverageState.PARTIAL_UNCOVERED}:
        filtered = []
        for item in values:
            if not isinstance(item, dict):
                continue
            targets = identifiers(item)
            if any(isinstance(target, str) and _covered(record, dimension, target) for target in targets):
                filtered.append(_without_governance(item, context, rendering_mode=rendering_mode))
        return filtered or None
    filtered = []
    for item in values:
        if isinstance(item, dict) and any(isinstance(target, str) and _covered(record, dimension, target) for target in identifiers(item)):
            filtered.append(_without_governance(item, context, rendering_mode=rendering_mode))
    return filtered or None


def _project_dependencies(record: dict[str, Any], rendering_mode: str) -> list[dict[str, Any]] | None:
    return _project_relation_collection(record, "dependencies", "dependencies", lambda item: [item.get("head"), item.get("dependent")], rendering_mode)


def _project_semantic_roles(record: dict[str, Any], rendering_mode: str) -> list[dict[str, Any]] | None:
    return _project_relation_collection(record, "semantic_roles", "semantic_roles", lambda item: [item.get("constituent"), item.get("predicate")], rendering_mode)


def _project_heads(record: dict[str, Any], rendering_mode: str) -> list[dict[str, Any]] | None:
    return _project_relation_collection(record, "heads", "construction_relations", lambda item: [item.get("head"), item.get("dependent")], rendering_mode)


def _project_valency(record: dict[str, Any], rendering_mode: str) -> list[dict[str, Any]] | None:
    values = record.get("lexical_valency")
    if not isinstance(values, list):
        return None
    result: list[dict[str, Any]] = []
    for source in values:
        if not isinstance(source, dict):
            continue
        if collection_item_coverage_state(record, "lexical_valency", source) not in _CONTENT_COVERED_STATES:
            continue
        normalized = normalize_collection_item(record, "lexical_valency", source)
        if normalized is not None:
            result.append(_without_governance(normalized, "valency", rendering_mode=rendering_mode))
    if result:
        return result
    if _coverage_state(record, "lexical_valency") == CoverageState.CONFIRMED_EMPTY:
        return []
    return None


def _project_id_list(record: dict[str, Any], field: str, rendering_mode: str) -> list[str] | None:
    values = record.get(field)
    if not isinstance(values, list):
        return None
    dimensions = projection_property_dimensions(field, "value")
    if not dimensions:
        return None
    if any(_coverage_state(record, dimension) == CoverageState.CONFIRMED_EMPTY for dimension in dimensions):
        return []
    filtered = [value for value in values if isinstance(value, str) and any(_covered(record, dimension, value) for dimension in dimensions)]
    return filtered or None


def _typed_reference(value: Any) -> tuple[str, str] | None:
    if isinstance(value, dict) and isinstance(value.get("namespace"), str) and isinstance(value.get("id"), str):
        return value["namespace"], value["id"]
    if isinstance(value, str) and ":" in value:
        namespace, identifier = value.split(":", 1)
        if namespace and identifier:
            return namespace, identifier
    return None


def _typed_relation_targets(relation: dict[str, Any]) -> list[str]:
    targets: list[str] = []
    for key in ("source", "target"):
        reference = _typed_reference(relation.get(key))
        if reference and reference[0] in {"word", "constituent", "clause"}:
            targets.append(reference[1])
    return targets


def _typed_relation_all_targets(relation: dict[str, Any]) -> list[str]:
    targets: list[str] = []
    for key in ("source", "target"):
        reference = _typed_reference(relation.get(key))
        if reference:
            targets.append(reference[1])
    return targets


def _typed_relation_dimension(relation: dict[str, Any]) -> str:
    return "dependencies" if relation.get("type") == "dependency" else "construction_relations"


def _typed_relation_is_covered(record: dict[str, Any], relation: dict[str, Any]) -> bool:
    dimension = _typed_relation_dimension(relation)
    state = _coverage_state(record, dimension)
    if state == CoverageState.COMPLETE:
        return True
    if state == CoverageState.PARTIAL_COVERED:
        return True
    return any(_covered(record, dimension, target) for target in _typed_relation_targets(relation))


def _typed_target(record: dict[str, Any], value: Any) -> tuple[str, str] | None:
    if not isinstance(value, dict):
        return None
    for key in ("target", "constituent_ref", "word_ref", "clause_ref"):
        reference = _typed_reference(value.get(key))
        if reference and reference[0] in {"word", "constituent", "clause"}:
            return reference
        identifier = value.get(key)
        if isinstance(identifier, str):
            source = _raw_objects(record).get(identifier)
            if isinstance(source, dict):
                node_kind = source.get("node_kind")
                if node_kind == "word":
                    return "word", identifier
                if node_kind == "clause":
                    return "clause", identifier
                return "constituent", identifier
    return None


def _typed_property_dimensions(context: str, property_name: str, target: tuple[str, str] | None) -> tuple[str, ...]:
    if property_name == "role":
        return projection_property_dimensions("semantic_roles", "role")
    if property_name == "function":
        field = "words" if target is not None and target[0] == "word" else "constituents"
        property_name = "syntactic_function" if field == "words" else "function"
        return projection_property_dimensions(field, property_name)
    if property_name == "category":
        if target is not None and target[0] == "word":
            return projection_property_dimensions("words", "lexical_category")
        return projection_property_dimensions("constituents", "phrase_category")
    return projection_property_dimensions(context, property_name)


def _typed_property_is_covered(
    record: dict[str, Any],
    context: str,
    property_name: str,
    value: dict[str, Any],
) -> bool:
    target = _typed_target(record, value)
    dimensions = _typed_property_dimensions(context, property_name, target)
    if target is None:
        return any(_covered(record, dimension) for dimension in dimensions)
    return any(_covered(record, dimension, target[1]) for dimension in dimensions)


def _filter_typed_properties(
    record: dict[str, Any],
    value: Any,
    context: str,
    relation_dimension: str,
    rendering_mode: str,
) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if key in {"role", "function", "category"} and not _typed_property_is_covered(record, context, key, value):
                continue
            if key not in {"role", "function", "category"}:
                dimensions = projection_property_dimensions(context, key)
                if dimensions and relation_dimension not in dimensions:
                    continue
            child_context = {
                "source": "typed_reference", "target": "typed_reference",
            }.get(key, context)
            result[key] = _filter_typed_properties(record, item, child_context, relation_dimension, rendering_mode)
        return result
    if isinstance(value, list):
        return [_filter_typed_properties(record, item, context, relation_dimension, rendering_mode) for item in value]
    return copy.deepcopy(value)


def _project_typed_object(
    record: dict[str, Any],
    value: Any,
    context: str,
    relation_dimension: str,
    rendering_mode: str,
) -> Any:
    projected = _without_governance(value, context, rendering_mode=rendering_mode)
    return _filter_typed_properties(record, projected, context, relation_dimension, rendering_mode)


def _project_typed_arguments(record: dict[str, Any], value: Any, relation_dimension: str, rendering_mode: str) -> Any:
    if isinstance(value, list):
        return [_project_typed_object(record, item, "typed_arguments", relation_dimension, rendering_mode) for item in value]
    if not isinstance(value, dict):
        return None
    argument_fields = set(LINGUISTIC_NESTED_FIELDS["typed_arguments"])
    if any(key in argument_fields for key in value):
        return _project_typed_object(record, value, "typed_arguments", relation_dimension, rendering_mode)
    result = {
        key: _project_typed_object(record, item, "typed_arguments", relation_dimension, rendering_mode)
        for key, item in value.items()
        if isinstance(item, dict)
    }
    return result or None


def _project_typed_analysis(record: dict[str, Any], value: Any, rendering_mode: str) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    relations = value.get("relations")
    projected_relations: list[dict[str, Any]] = []
    if isinstance(relations, list):
        for relation in relations:
            if isinstance(relation, dict) and _typed_relation_is_covered(record, relation):
                dimension = _typed_relation_dimension(relation)
                projected_relations.append(_project_typed_object(record, relation, "typed_relation", dimension, rendering_mode))
    construction_covered = _record_complete(record, ("construction_relations",))
    analysis_dimension = "construction_relations" if construction_covered else "dependencies"
    result: dict[str, Any] = {}
    for key in ("kind", "framework"):
        if key in value:
            result[key] = copy.deepcopy(value[key])
    if construction_covered or projected_relations:
        if "arguments" in value and (construction_covered or projected_relations):
            arguments = _project_typed_arguments(record, value["arguments"], analysis_dimension, rendering_mode)
            if arguments:
                result["arguments"] = arguments
        if isinstance(value.get("entities"), list):
            referenced = {target for relation in projected_relations for target in _typed_relation_all_targets(relation)}
            entities = [
                _project_typed_object(record, entity, "typed_entity", analysis_dimension, rendering_mode)
                for entity in value["entities"]
                if isinstance(entity, dict) and entity.get("id") in referenced
            ]
            if entities:
                result["entities"] = entities
        if projected_relations:
            result["relations"] = projected_relations
    return result or None


def _project_analysis(record: dict[str, Any], field: str, value: Any, rendering_mode: str, covered: bool, allow_prose: bool) -> dict[str, Any] | None:
    if not isinstance(value, dict) or not covered:
        return None
    result = _without_governance(value, "analysis", rendering_mode=rendering_mode)
    if not allow_prose:
        result.pop("label", None)
        result.pop("claims", None)
    if "framework" in result and not _record_complete(record, PROJECTION_FIELD_DIMENSIONS["framework"]):
        result.pop("framework", None)
    if "construction_type" in result and not _record_complete(record, PROJECTION_FIELD_DIMENSIONS["construction_type"]):
        result.pop("construction_type", None)
    if "analysis_type" in result and not _record_complete(record, ("construction_relations",)):
        result.pop("analysis_type", None)
    if isinstance(value.get("typed_analysis"), dict):
        typed = _project_typed_analysis(record, value["typed_analysis"], rendering_mode)
        if typed is None:
            result.pop("typed_analysis", None)
        else:
            result["typed_analysis"] = typed
    return result or None


def _reference_namespace(key: str) -> str | None:
    return {
        "clause_ref": "clause", "integration_parent": "clause", "relative_clause": "clause",
        "linked_clause_refs": "clause", "clause_refs": "clause", "clause": "clause",
        "marker_ids": "word", "fused_element": "word", "predicate": "word",
        "linked_constituent_ids": "constituent", "linked_wrapper_ids": "constituent",
        "constituent_ids": "constituent", "wrapper_ids": "constituent", "constituent": "constituent",
    }.get(key)


def _collect_references(value: Any) -> set[tuple[str | None, str]]:
    references: set[tuple[str | None, str]] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key in _REFERENCE_KEYS:
                if isinstance(item, str):
                    typed = _typed_reference(item) if key in {"source", "target"} else None
                    if typed and typed[0] in {"word", "constituent", "clause"}:
                        references.add(typed)
                    elif key != "linked_relation_ids":
                        references.add((_reference_namespace(key), item))
                elif isinstance(item, list):
                    namespace = _reference_namespace(key)
                    if key != "linked_relation_ids":
                        references.update((namespace, value) for value in item if isinstance(value, str))
                elif key in {"target", "source"}:
                    reference = _typed_reference(item)
                    if reference and reference[0] in {"word", "constituent", "clause"}:
                        references.add(reference)
            references.update(_collect_references(item))
    elif isinstance(value, list):
        for item in value:
            references.update(_collect_references(item))
    return references


def _add_reference_shells(record: dict[str, Any], projection: dict[str, Any]) -> None:
    collection_names = {"word": "words", "constituent": "constituents", "clause": "clauses"}
    raw_by_namespace: dict[tuple[str, str], dict[str, Any]] = {}
    raw_unqualified: dict[str, tuple[str, dict[str, Any]]] = {}
    for namespace, collection in collection_names.items():
        values = record.get(collection, [])
        if not isinstance(values, list):
            continue
        for item in values:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                continue
            raw_by_namespace[(namespace, item["id"])] = item
            raw_unqualified[item["id"]] = (namespace, item)

    def present_references() -> set[tuple[str, str]]:
        return {
            (namespace, item["id"])
            for namespace, collection in collection_names.items()
            for item in projection.get(collection, [])
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }

    pending = _collect_references(projection)
    while True:
        present = present_references()
        added = False
        for namespace, identifier in sorted(pending - present, key=lambda value: (value[0] or "", value[1])):
            source_entry = raw_by_namespace.get((namespace, identifier)) if namespace else raw_unqualified.get(identifier)
            if source_entry is None:
                continue
            source_namespace, source = source_entry if namespace is None else (namespace, source_entry)
            collection = collection_names[source_namespace]
            if (source_namespace, identifier) in present:
                continue
            if source_namespace == "word":
                shell = {"id": identifier, "node_kind": "word"}
            elif source_namespace == "clause":
                shell = {"id": identifier, "node_kind": "clause"}
                if "span" in source:
                    shell["span"] = copy.deepcopy(source["span"])
            else:
                shell = {"id": identifier, "node_kind": source.get("node_kind", "phrase")}
                if "span" in source:
                    shell["span"] = copy.deepcopy(source["span"])
                if isinstance(source.get("clause_ref"), str):
                    shell["clause_ref"] = source["clause_ref"]
            projection.setdefault(collection, []).append(shell)
            added = True
        if not added:
            break
        pending = _collect_references(projection)
    for field in ("words", "clauses", "constituents"):
        if field not in projection or not isinstance(projection[field], list):
            continue
        order = {
            item.get("id"): index
            for index, item in enumerate(record.get(field, []) if isinstance(record.get(field), list) else [])
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        projection[field].sort(key=lambda item: order.get(item.get("id") if isinstance(item, dict) else None, len(order)))


def _project_alternatives(record: dict[str, Any], projection: dict[str, Any], rendering_mode: str) -> list[dict[str, Any]] | None:
    values = record.get("alternative_analyses")
    if not isinstance(values, list):
        return None
    result: list[dict[str, Any]] = []
    for value in values:
        if not isinstance(value, dict):
            continue
        links = []
        for field in ("linked_wrapper_ids", "linked_constituent_ids", "linked_clause_refs", "linked_relation_ids"):
            links.extend(value.get(field, []) if isinstance(value.get(field), list) else [])
        covered = _record_complete(record, ("construction_relations",)) or any(isinstance(link, str) and _any_covered(record, ("construction_relations",), link) for link in links)
        if not covered:
            continue
        item = _without_governance(value, "alternative_analysis", rendering_mode=rendering_mode)
        if isinstance(value.get("typed_analysis"), dict) and isinstance(item, dict):
            typed = _project_typed_analysis(record, value["typed_analysis"], rendering_mode)
            if typed is None:
                item.pop("typed_analysis", None)
            else:
                item["typed_analysis"] = typed
        retained_nodes = {
            node.get("id") for field in ("words", "constituents", "clauses")
            for node in projection.get(field, []) if isinstance(node, dict) and isinstance(node.get("id"), str)
        }
        retained_nodes.update(_raw_objects(record))
        retained_relations = {
            relation.get("id")
            for analysis in [projection.get("canonical_analysis"), projection.get("preferred_analysis")]
            if isinstance(analysis, dict)
            for typed_analysis in [analysis.get("typed_analysis")] if isinstance(analysis.get("typed_analysis"), dict)
            for relation in typed_analysis.get("relations", []) if isinstance(relation, dict) and isinstance(relation.get("id"), str)
        }
        retained_relations.update(
            relation.get("id")
            for alternative in projection.get("alternative_analyses", []) if isinstance(alternative, dict)
            for typed_analysis in [alternative.get("typed_analysis")] if isinstance(alternative.get("typed_analysis"), dict)
            for relation in typed_analysis.get("relations", []) if isinstance(relation, dict) and isinstance(relation.get("id"), str)
        )
        own_typed = item.get("typed_analysis") if isinstance(item, dict) else None
        if isinstance(own_typed, dict):
            retained_relations.update(
                relation.get("id")
                for relation in own_typed.get("relations", []) if isinstance(relation, dict) and isinstance(relation.get("id"), str)
            )
        for field in ("linked_wrapper_ids", "linked_constituent_ids", "linked_clause_refs", "linked_relation_ids"):
            if isinstance(item, dict) and isinstance(item.get(field), list):
                allowed = retained_relations if field == "linked_relation_ids" else retained_nodes
                item[field] = [link for link in item[field] if link in allowed]
                if not item[field]:
                    item.pop(field, None)
        result.append(item)
    return result or None


def _prune_linkages(projection: dict[str, Any]) -> None:
    relation_ids = {
        relation.get("id")
        for analysis in [projection.get("canonical_analysis"), projection.get("preferred_analysis")]
        if isinstance(analysis, dict)
        for typed in [analysis.get("typed_analysis")] if isinstance(analysis.get("typed_analysis"), dict)
        for relation in typed.get("relations", []) if isinstance(relation, dict) and isinstance(relation.get("id"), str)
    }
    relation_ids.update(
        relation.get("id")
        for alternative in projection.get("alternative_analyses", []) if isinstance(alternative, dict)
        for typed in [alternative.get("typed_analysis")] if isinstance(alternative.get("typed_analysis"), dict)
        for relation in typed.get("relations", []) if isinstance(relation, dict) and isinstance(relation.get("id"), str)
    )
    ambiguity = projection.get("ambiguity")
    if isinstance(ambiguity, dict) and isinstance(ambiguity.get("analyses"), list):
        for analysis in ambiguity["analyses"]:
            if isinstance(analysis, dict) and isinstance(analysis.get("relation_ids"), list):
                analysis["relation_ids"] = [identifier for identifier in analysis["relation_ids"] if identifier in relation_ids]
                if not analysis["relation_ids"]:
                    analysis.pop("relation_ids", None)


def linguistic_projection(record: dict[str, Any], *, include_governance: bool = False, rendering_mode: str = "default") -> dict[str, Any]:
    """Project only covered linguistic properties and retain reference shells."""
    if rendering_mode not in RENDERING_MODES:
        raise ValueError(f"unknown rendering mode {rendering_mode!r}; expected one of {sorted(RENDERING_MODES)}")
    if include_governance:
        return copy.deepcopy(record)
    projection: dict[str, Any] = {"sentence": copy.deepcopy(record["sentence"])} if isinstance(record.get("sentence"), str) else {}
    words = _project_words(record, rendering_mode)
    clauses = _project_clauses(record, rendering_mode)
    constituents = _project_constituents(record, rendering_mode)
    for field, value in (("words", words), ("clauses", clauses), ("constituents", constituents)):
        if value is not None:
            projection[field] = value
    dependencies = _project_dependencies(record, rendering_mode)
    semantic_roles = _project_semantic_roles(record, rendering_mode)
    heads = _project_heads(record, rendering_mode)
    valency = _project_valency(record, rendering_mode)
    for field, value in (("dependencies", dependencies), ("semantic_roles", semantic_roles), ("heads", heads), ("lexical_valency", valency)):
        if value is not None:
            projection[field] = value
    for field in ("complements", "adjuncts"):
        value = _project_id_list(record, field, rendering_mode)
        if value is not None:
            projection[field] = value
    scalar_dimensions = PROJECTION_FIELD_DIMENSIONS
    for field, dimensions in scalar_dimensions.items():
        if field not in record:
            continue
        if field in {"pedagogical_aliases", "fusion_relations", "ambiguity", "rejected_analyses", "error_diagnosis"}:
            if not _record_complete(record, dimensions):
                continue
        elif field in {"explanation", "rationale"}:
            if not _record_complete_all(record, dimensions):
                continue
        elif not _record_complete(record, dimensions):
            continue
        context = {
            "framework": "framework", "sentence_type_metadata": "sentence_type_metadata", "sentence_classification": "sentence_classification",
            "construction_signature": "construction_signature", "fusion_relations": "fusion_relations", "ambiguity": "ambiguity",
            "rejected_analyses": "rejected_analyses", "error_diagnosis": "error_diagnosis", "pedagogical_aliases": "pedagogical_aliases",
        }.get(field)
        projection[field] = _without_governance(record[field], context, rendering_mode=rendering_mode)
    for field in ("canonical_analysis", "preferred_analysis"):
        if field in record:
            analysis_covered = bool(projection) and any(key != "sentence" for key in projection)
            analysis_covered = analysis_covered or _record_complete(record, ("construction_relations", "dependencies"))
            allow_prose = _record_complete_all(record, ("clause_structure", "phrase_constituency", "syntactic_function"))
            analysis = _project_analysis(record, field, record[field], rendering_mode, analysis_covered, allow_prose)
            if analysis is not None:
                projection[field] = analysis
    alternatives = _project_alternatives(record, projection, rendering_mode)
    if alternatives is not None:
        projection["alternative_analyses"] = alternatives
    _prune_linkages(projection)
    _add_reference_shells(record, projection)
    return projection


def _legacy_annotations(record: dict[str, Any]) -> dict[str, Any]:
    annotations: dict[str, Any] = {}
    for collection in ("words", "clauses", "constituents"):
        values = record.get(collection)
        if not isinstance(values, list):
            continue
        retained = []
        for item in values:
            if not isinstance(item, dict):
                continue
            fields = {key: copy.deepcopy(item[key]) for key in ("legacy_function", "legacy_clause_category", "legacy_pos") if key in item}
            if fields:
                retained.append({"id": item.get("id"), "fields": fields})
        if retained:
            annotations[collection] = retained
    return annotations


def governance_sidecar(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "record_id": record.get("id"), "schema_version": record.get("schema_version"), "split": record.get("split"),
        "source_type": record.get("source_type"), "difficulty": record.get("difficulty"),
        "review_metadata": copy.deepcopy(record.get("review_metadata")), "migration_metadata": copy.deepcopy(record.get("migration_metadata")),
        "migration_review_required": record.get("migration_review_required"), "migration_note": record.get("migration_note"),
        "provenance": copy.deepcopy(record.get("provenance")), "annotation_scope": copy.deepcopy(record.get("annotation_scope")),
        "legacy_annotation_scope": copy.deepcopy(record.get("legacy_annotation_scope")), "legacy_annotations": _legacy_annotations(record),
        "capability_tags": copy.deepcopy(record.get("capability_tags")), "content_flags": _content_flags(record),
    }


def render_assistant(record: dict[str, Any], *, include_governance: bool = False, rendering_mode: str = "default") -> str:
    return json.dumps(linguistic_projection(record, include_governance=include_governance, rendering_mode=rendering_mode), ensure_ascii=False, sort_keys=True)


def render_record(record: dict[str, Any], system_prompt: str = DEFAULT_SYSTEM, *, include_governance: bool = False, rendering_mode: str = "default") -> dict[str, Any]:
    return {"id": record["id"], "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": render_user(record)}, {"role": "assistant", "content": render_assistant(record, include_governance=include_governance, rendering_mode=rendering_mode)}], "governance_sidecar": governance_sidecar(record)}


def render_files(input_paths: list[Path], output_path: Path, system_prompt: str = DEFAULT_SYSTEM, split: str | None = None, *, include_governance: bool = False, rendering_mode: str = "default") -> int:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with output_path.open("w", encoding="utf-8") as output:
        for input_path in input_paths:
            for line_number, record in read_jsonl(input_path):
                if split is not None and record.get("split") != split:
                    continue
                try:
                    rendered = render_record(record, system_prompt, include_governance=include_governance, rendering_mode=rendering_mode)
                except KeyError as error:
                    raise ValueError(f"{input_path}:{line_number}: cannot render missing field {error.args[0]!r}") from error
                output.write(json.dumps(rendered, ensure_ascii=False) + "\n")
                count += 1
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--system-prompt", default=DEFAULT_SYSTEM)
    parser.add_argument("--split", choices=("train", "validation", "benchmark"))
    parser.add_argument("--include-governance", action="store_true", help="debug only")
    parser.add_argument("--rendering-mode", choices=sorted(RENDERING_MODES), default="default")
    arguments = parser.parse_args()
    try:
        count = render_files(arguments.inputs, arguments.output, arguments.system_prompt, arguments.split, include_governance=arguments.include_governance, rendering_mode=arguments.rendering_mode)
    except (OSError, ValueError) as error:
        print(f"Rendering failed: {error}")
        return 1
    print(f"Rendered {count} example(s) to {arguments.output}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
