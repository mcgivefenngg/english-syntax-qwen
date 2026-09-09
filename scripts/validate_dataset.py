#!/usr/bin/env python3
"""Validate canonical English Syntax Tutor JSONL data.

The validator checks deterministic data-contract invariants. It deliberately does
not try to decide whether a linguist's preferred analysis is theoretically true.
"""

from __future__ import annotations

import argparse
import json
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

try:
    from canonical_schema import canonical_schema_issues, canonical_schema_required_fields
except ImportError:
    from scripts.canonical_schema import canonical_schema_issues, canonical_schema_required_fields

try:
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover - exercised by the dependency failure path
    Draft202012Validator = None

try:
    from data_common import (
        AMBIGUITY_STATUSES, ANNOTATED_DIMENSIONS, ANNOTATION_COVERAGES,
        CANONICAL_SCHEMA_VERSION, LEGACY_SCHEMA_VERSIONS,
        CAPABILITY_TAGS, CANONICAL_FRAMEWORK, CLAUSE_CONSTRUCTIONS, CLAUSE_FINITE_VALUES, CLAUSE_FORMS, CLAUSE_INTEGRATIONS, CLAUSE_STATUSES, CLAUSE_TYPES, DIFFICULTIES, FRAMEWORKS, LEXICAL_CATEGORIES,
        NOMINAL_SUBJECT_CATEGORIES, PHRASE_CATEGORIES, PREDICAND_KINDS, PREDICAND_TARGET_REQUIRED_KINDS,
        SCHEMA_VERSIONS, SEMANTIC_ROLES, SENTENCE_CLASSIFICATION_LABELS, SENTENCE_TYPES,
        SOURCE_TYPES, SPLITS, construction_signature, iter_jsonl_paths, normalized_text,
        normalized_surface_tokens, read_jsonl, sentence_from_record, sentence_word_alignment,
    )
except ImportError:
    from scripts.data_common import (
        AMBIGUITY_STATUSES, ANNOTATED_DIMENSIONS, ANNOTATION_COVERAGES,
        CANONICAL_SCHEMA_VERSION, LEGACY_SCHEMA_VERSIONS,
        CAPABILITY_TAGS, CANONICAL_FRAMEWORK, CLAUSE_CONSTRUCTIONS, CLAUSE_FINITE_VALUES, CLAUSE_FORMS, CLAUSE_INTEGRATIONS, CLAUSE_STATUSES, CLAUSE_TYPES, DIFFICULTIES, FRAMEWORKS, LEXICAL_CATEGORIES,
        NOMINAL_SUBJECT_CATEGORIES, PHRASE_CATEGORIES, PREDICAND_KINDS, PREDICAND_TARGET_REQUIRED_KINDS,
        SCHEMA_VERSIONS, SEMANTIC_ROLES, SENTENCE_CLASSIFICATION_LABELS, SENTENCE_TYPES,
        SOURCE_TYPES, SPLITS, construction_signature, iter_jsonl_paths, normalized_text,
        normalized_surface_tokens, read_jsonl, sentence_from_record, sentence_word_alignment,
    )

try:
    from coverage_resolution import (
        coverage_declaration_issues, coverage_scope_key, resolve_scoring_eligibility,
    )
except ImportError:
    from scripts.coverage_resolution import (
        coverage_declaration_issues, coverage_scope_key, resolve_scoring_eligibility,
    )

try:
    from dimension_registry import CAPABILITY_DIMENSIONS, dimension_spec
except ImportError:
    from scripts.dimension_registry import CAPABILITY_DIMENSIONS, dimension_spec

try:
    from collection_contract import normalize_predicate_reference, predicate_reference_issue
except ImportError:
    from scripts.collection_contract import normalize_predicate_reference, predicate_reference_issue

try:
    from canonical_record_contract import canonical_record_consistency_issues
except ImportError:
    from scripts.canonical_record_contract import canonical_record_consistency_issues

ANALYSIS_LEVELS = {"lexical_category", "phrase_category", "syntactic_function", "clause_structure", "framework", "semantic_role", "span", "none"}
FRAMEWORK_SENSITIVE_ANALYSIS_TYPES = {"ecm", "small_clause", "ud_pos", "ptb_pos", "gerund_as_noun", "control", "raising", "perception", "perception_construction"}
REVIEW_STATUSES = {"schema_migrated", "structurally_validated", "review_required", "linguistically_reviewed", "approved_for_training", "canonical_gold"}
REVIEWER_TYPES = {"automated_structural", "independent_linguistic", "human_annotation", "mixed"}
APPROVED_REVIEW_STATUSES = {"approved_for_training", "canonical_gold"}
ALTERNATIVE_STATUSES = {"established", "unresolved", "review_required"}
TYPED_REFERENCE_NAMESPACES = {"word", "constituent", "clause", "analysis"}
CORE_TYPED_RELATION_TYPES = {
    "attachment", "construction", "control", "coreference", "cross_node",
    "dependency", "framework_relation", "predication", "raising",
    "realization_link", "selection",
}
BINARY_TYPED_RELATION_TYPES = CORE_TYPED_RELATION_TYPES
CANONICAL_SCALAR_RELATION_TYPES = {
    "category", "clause_construction", "clause_integration", "constituent_function",
    "external_realization", "finiteness", "function", "integration", "realization", "realization_link",
    "lexical_category", "phrase_category", "syntactic_function",
}
ALTERNATIVE_LINK_FIELDS = {
    "linked_wrapper_ids", "linked_constituent_ids", "linked_clause_refs", "linked_relation_ids",
}
AMBIGUITY_LINK_FIELDS = {
    "alternative_ids", "wrapper_ids", "relation_ids", "constituent_ids", "clause_refs",
}


@lru_cache(maxsize=1)
def _rendered_schema_validator() -> Any:
    if Draft202012Validator is None:
        raise RuntimeError("jsonschema dependency is required for rendered-target validation")
    schema_path = Path(__file__).resolve().parents[1] / "schemas" / "rendered_sft_target.schema.json"
    with schema_path.open(encoding="utf-8") as handle:
        schema_document = json.load(handle)
    validator = Draft202012Validator(schema_document)
    validator.check_schema(schema_document)
    return validator


def _schema_path(path: Any) -> str:
    parts: list[str] = []
    for part in path:
        parts.append(f"[{part}]" if isinstance(part, int) else f".{part}")
    return "".join(parts) or ".<record>"


def _validate_json_schema(record: dict[str, Any], location: str, errors: list[str], schema_path: Path | None = None) -> None:
    record_id = record.get("id", "<missing-id>")
    for schema_issue in canonical_schema_issues(record, schema_path):
        _error(errors, f"{location} record {record_id!r}{_schema_path(schema_issue.path)}", f"schema validation failed: {schema_issue.message}")


def _validate_rendered_schema(record: dict[str, Any], location: str, errors: list[str]) -> None:
    try:
        validator = _rendered_schema_validator()
    except (OSError, json.JSONDecodeError, RuntimeError, TypeError) as error:
        _error(errors, location, f"rendered-target schema engine unavailable: {error}")
        return
    for schema_error in sorted(validator.iter_errors(record), key=lambda item: list(item.path)):
        _error(errors, f"{location}{_schema_path(schema_error.path)}", f"rendered-target schema validation failed: {schema_error.message}")


def _error(errors: list[str], location: str, message: str) -> None:
    errors.append(f"{location}: {message}")


def _rendered_governance_leaks(value: Any, context: str | None = None, path: str = "") -> list[str]:
    """Find governance/legacy keys that escaped the renderer allowlist."""
    leaks: list[str] = []
    forbidden = {
        "schema_version", "split", "source_type", "difficulty", "capability_tags", "annotation_scope",
        "review_metadata", "migration_metadata", "migration_review_required", "migration_note", "provenance",
        "legacy_preferred_analysis", "legacy_annotation_scope", "legacy_annotations", "review_required",
        "legacy_function", "legacy_clause_category", "legacy_pos",
    }
    if isinstance(value, dict):
        for key, item in value.items():
            key_path = f"{path}.{key}" if path else key
            if key in forbidden or (key == "status" and context != "ambiguity") or (key in {"notes", "note"} and context in {"typed_analysis", "typed_relation"}):
                leaks.append(key_path)
                continue
            child_context = {
                "ambiguity": "ambiguity", "analyses": "ambiguity_analysis", "clauses": "clause",
                "constituents": "constituent", "words": "word", "dependencies": "dependency",
                "typed_analysis": "typed_analysis", "typed_relation": "typed_relation", "relations": "typed_relation", "lexical_analysis": "lexical_analysis",
            }.get(key)
            leaks.extend(_rendered_governance_leaks(item, child_context, key_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            leaks.extend(_rendered_governance_leaks(item, context, f"{path}[{index}]"))
    return leaks


def _rendered_typed_reference(value: Any) -> tuple[str, str] | None:
    if isinstance(value, dict) and isinstance(value.get("namespace"), str) and isinstance(value.get("id"), str):
        return value["namespace"], value["id"]
    if isinstance(value, str) and ":" in value:
        namespace, identifier = value.split(":", 1)
        if namespace and identifier:
            return namespace, identifier
    return None


def _validate_rendered_references(payload: dict[str, Any], location: str, errors: list[str]) -> None:
    """Check references remaining after coverage-aware linguistic projection."""
    collections = {field: payload.get(field) for field in ("words", "constituents", "clauses")}
    ids_by_kind: dict[str, set[str]] = {"word": set(), "constituent": set(), "clause": set()}
    objects: dict[str, str] = {}
    for field, values in collections.items():
        if not isinstance(values, list):
            continue
        kind = field[:-1] if field != "constituents" else "constituent"
        for index, item in enumerate(values):
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                _error(errors, f"{location}.{field}[{index}]", "projected node must have an id")
                continue
            identifier = item["id"]
            if identifier in objects:
                _error(errors, f"{location}.{field}[{index}].id", "projected node id must be unique")
            objects[identifier] = kind
            ids_by_kind[kind].add(identifier)

    def require(identifier: Any, expected: set[str], path: str) -> None:
        if identifier is None:
            return
        if not isinstance(identifier, str) or identifier not in objects or objects[identifier] not in expected:
            _error(errors, path, "projected reference must target a retained node")

    for field, values in collections.items():
        if not isinstance(values, list):
            continue
        for index, item in enumerate(values):
            if not isinstance(item, dict):
                continue
            item_path = f"{location}.{field}[{index}]"
            if field == "clauses":
                for ref_field in ("subject", "head", "integration_parent"):
                    require(item.get(ref_field), {"word", "constituent", "clause"}, f"{item_path}.{ref_field}")
                predicand = item.get("predicand")
                if isinstance(predicand, dict):
                    require(predicand.get("target"), {"word", "constituent", "clause"}, f"{item_path}.predicand.target")
                for marker_index, marker in enumerate(item.get("marker_ids", []) if isinstance(item.get("marker_ids"), list) else []):
                    require(marker, {"word"}, f"{item_path}.marker_ids[{marker_index}]")
            elif field == "constituents":
                for ref_field in ("head", "parent"):
                    require(item.get(ref_field), {"word", "constituent", "clause"}, f"{item_path}.{ref_field}")
                require(item.get("clause_ref"), {"clause"}, f"{item_path}.clause_ref")
                realization = item.get("realization")
                if isinstance(realization, dict):
                    require(realization.get("clause_ref"), {"clause"}, f"{item_path}.realization.clause_ref")

    for field, values in (("dependencies", payload.get("dependencies")), ("heads", payload.get("heads"))):
        if not isinstance(values, list):
            continue
        for index, item in enumerate(values):
            if not isinstance(item, dict):
                continue
            item_path = f"{location}.{field}[{index}]"
            require(item.get("head"), {"word", "constituent", "clause"}, f"{item_path}.head")
            require(item.get("dependent"), {"word", "constituent", "clause"}, f"{item_path}.dependent")

    for index, value in enumerate(payload.get("complements", []) if isinstance(payload.get("complements"), list) else []):
        require(value, {"constituent", "clause"}, f"{location}.complements[{index}]")
    for index, value in enumerate(payload.get("adjuncts", []) if isinstance(payload.get("adjuncts"), list) else []):
        require(value, {"constituent", "clause"}, f"{location}.adjuncts[{index}]")
    for index, item in enumerate(payload.get("lexical_valency", []) if isinstance(payload.get("lexical_valency"), list) else []):
        if not isinstance(item, dict):
            continue
        predicate = item.get("predicate")
        predicate_issue = predicate_reference_issue(payload, predicate, "rendered lexical valency predicate")
        if predicate_issue is not None:
            _error(errors, f"{location}.lexical_valency[{index}].predicate", predicate_issue)
        elif predicate != normalize_predicate_reference(payload, predicate):
            _error(errors, f"{location}.lexical_valency[{index}].predicate", "rendered valency predicate must use an explicit word ID")
        for selected_index, selected in enumerate(item.get("selected_complements", []) if isinstance(item.get("selected_complements"), list) else []):
            require(selected, {"constituent", "clause"}, f"{location}.lexical_valency[{index}].selected_complements[{selected_index}]")
    for index, item in enumerate(payload.get("semantic_roles", []) if isinstance(payload.get("semantic_roles"), list) else []):
        if isinstance(item, dict):
            require(item.get("constituent"), {"constituent"}, f"{location}.semantic_roles[{index}].constituent")
            predicate = item.get("predicate")
            if predicate is not None:
                predicate_issue = predicate_reference_issue(payload, predicate, "rendered semantic role predicate")
                if predicate_issue is not None:
                    _error(errors, f"{location}.semantic_roles[{index}].predicate", predicate_issue)
                elif predicate != normalize_predicate_reference(payload, predicate):
                    _error(errors, f"{location}.semantic_roles[{index}].predicate", "rendered semantic-role predicate must use an explicit word ID")
    for index, item in enumerate(payload.get("fusion_relations", []) if isinstance(payload.get("fusion_relations"), list) else []):
        if not isinstance(item, dict):
            continue
        path = f"{location}.fusion_relations[{index}]"
        require(item.get("fused_element"), {"word"}, f"{path}.fused_element")
        require(item.get("whole_constituent"), {"constituent", "clause"}, f"{path}.whole_constituent")
        require(item.get("relative_clause"), {"clause"}, f"{path}.relative_clause")
        dependency = item.get("dependency")
        if isinstance(dependency, dict):
            require(dependency.get("head"), {"word", "constituent", "clause"}, f"{path}.dependency.head")
            require(dependency.get("dependent"), {"word", "constituent", "clause"}, f"{path}.dependency.dependent")

    relation_ids: set[str] = set()
    for analysis_field in ("canonical_analysis", "preferred_analysis"):
        analysis = payload.get(analysis_field)
        typed = analysis.get("typed_analysis") if isinstance(analysis, dict) else None
        relations = typed.get("relations") if isinstance(typed, dict) else None
        if not isinstance(relations, list):
            continue
        for index, relation in enumerate(relations):
            if not isinstance(relation, dict):
                continue
            relation_id = relation.get("id")
            if isinstance(relation_id, str):
                relation_ids.add(relation_id)
            relation_path = f"{location}.{analysis_field}.typed_analysis.relations[{index}]"
            for ref_field in ("source", "target"):
                reference = _rendered_typed_reference(relation.get(ref_field))
                if reference is None:
                    continue
                namespace, identifier = reference
                if namespace in ids_by_kind and identifier not in ids_by_kind[namespace]:
                    _error(errors, f"{relation_path}.{ref_field}", "typed relation reference targets a node omitted from the projection")
    for alternative_index, alternative in enumerate(payload.get("alternative_analyses", []) if isinstance(payload.get("alternative_analyses"), list) else []):
        typed = alternative.get("typed_analysis") if isinstance(alternative, dict) else None
        relations = typed.get("relations") if isinstance(typed, dict) else None
        if not isinstance(relations, list):
            continue
        for relation_index, relation in enumerate(relations):
            if not isinstance(relation, dict):
                continue
            relation_id = relation.get("id")
            if isinstance(relation_id, str):
                relation_ids.add(relation_id)
            relation_path = f"{location}.alternative_analyses[{alternative_index}].typed_analysis.relations[{relation_index}]"
            for ref_field in ("source", "target"):
                reference = _rendered_typed_reference(relation.get(ref_field))
                if reference is None:
                    continue
                namespace, identifier = reference
                if namespace in ids_by_kind and identifier not in ids_by_kind[namespace]:
                    _error(errors, f"{relation_path}.{ref_field}", "typed relation reference targets a node omitted from the projection")

    for field in ("alternative_analyses",):
        for index, item in enumerate(payload.get(field, []) if isinstance(payload.get(field), list) else []):
            if not isinstance(item, dict):
                continue
            path = f"{location}.{field}[{index}]"
            for link_field in ("linked_wrapper_ids", "linked_constituent_ids", "linked_clause_refs"):
                for link_index, link in enumerate(item.get(link_field, []) if isinstance(item.get(link_field), list) else []):
                    if link not in objects:
                        _error(errors, f"{path}.{link_field}[{link_index}]", "alternative linkage targets a node omitted from the projection")
            for link_index, link in enumerate(item.get("linked_relation_ids", []) if isinstance(item.get("linked_relation_ids"), list) else []):
                if link not in relation_ids:
                    _error(errors, f"{path}.linked_relation_ids[{link_index}]", "alternative linkage targets a relation omitted from the projection")

    ambiguity = payload.get("ambiguity")
    if isinstance(ambiguity, dict) and isinstance(ambiguity.get("analyses"), list):
        for index, item in enumerate(ambiguity["analyses"]):
            if not isinstance(item, dict):
                continue
            path = f"{location}.ambiguity.analyses[{index}]"
            for ref_field in ("attachment", "target", "constituent", "clause"):
                if ref_field in item:
                    require(item.get(ref_field), {"word", "constituent", "clause"}, f"{path}.{ref_field}")
            for link_field in ("wrapper_ids", "constituent_ids", "clause_refs"):
                for link_index, link in enumerate(item.get(link_field, []) if isinstance(item.get(link_field), list) else []):
                    if link not in objects:
                        _error(errors, f"{path}.{link_field}[{link_index}]", "ambiguity linkage targets a node omitted from the projection")
            for link_index, link in enumerate(item.get("relation_ids", []) if isinstance(item.get("relation_ids"), list) else []):
                if link not in relation_ids:
                    _error(errors, f"{path}.relation_ids[{link_index}]", "ambiguity linkage targets a relation omitted from the projection")


def _is_v2(record: dict[str, Any]) -> bool:
    return record.get("schema_version") == "0.2"


def _is_v3(record: dict[str, Any]) -> bool:
    return record.get("schema_version") in {"0.3", CANONICAL_SCHEMA_VERSION}


def _is_v4(record: dict[str, Any]) -> bool:
    return record.get("schema_version") == CANONICAL_SCHEMA_VERSION


def _valid_ref(value: Any, ids: set[str]) -> bool:
    return value is None or (isinstance(value, str) and value in ids)


def _known(value: Any, values: set[str]) -> bool:
    return isinstance(value, str) and value in values


def _ref_kind(value: Any, objects: dict[str, dict[str, Any]]) -> str | None:
    if not isinstance(value, str):
        return None
    item = objects.get(value)
    return item.get("node_kind") if isinstance(item, dict) else None


def _require_ref_kind(value: Any, objects: dict[str, dict[str, Any]], kinds: set[str], location: str, errors: list[str], description: str) -> None:
    kind = _ref_kind(value, objects)
    if kind not in kinds:
        expected = ", ".join(sorted(kinds))
        _error(errors, location, f"{description} must reference {expected}; got {value!r} ({kind or 'unknown'})")


def _typed_reference_ids(record: dict[str, Any]) -> dict[str, set[str]]:
    def ids(collection: Any) -> set[str]:
        return {
            item.get("id") for item in collection
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        } if isinstance(collection, list) else set()

    return {
        "word": ids(record.get("words")),
        "constituent": ids(record.get("constituents")),
        "clause": ids(record.get("clauses")),
    }


def _validate_typed_reference(
    reference: Any,
    location: str,
    reference_ids: dict[str, set[str]],
    analysis_entity_ids: set[str],
    errors: list[str],
) -> None:
    if isinstance(reference, str) and ":" in reference:
        namespace, identifier = reference.split(":", 1)
    elif isinstance(reference, dict):
        namespace = reference.get("namespace")
        identifier = reference.get("id")
    else:
        _error(errors, location, "typed reference must be a namespaced string or object with namespace and id")
        return
    if namespace not in TYPED_REFERENCE_NAMESPACES or not isinstance(identifier, str) or not identifier:
        _error(errors, location, "typed reference requires a known namespace and non-empty id")
        return
    allowed = analysis_entity_ids if namespace == "analysis" else reference_ids.get(namespace, set())
    if identifier not in allowed:
        _error(errors, location, f"dangling typed {namespace} reference {identifier!r}")


def _validate_typed_analysis(
    typed: Any,
    location: str,
    record: dict[str, Any],
    errors: list[str],
    *,
    preferred_authority: bool,
) -> set[str]:
    relation_ids: set[str] = set()
    if not isinstance(typed, dict):
        return relation_ids
    reference_ids = _typed_reference_ids(record)
    canonical_dependencies = record.get("dependencies") if isinstance(record.get("dependencies"), list) else []
    canonical_dependency_pairs = {
        (dependency.get("head"), dependency.get("dependent"))
        for dependency in canonical_dependencies
        if isinstance(dependency, dict) and isinstance(dependency.get("head"), str) and isinstance(dependency.get("dependent"), str)
    }
    entity_ids: set[str] = set()
    entities = typed.get("entities", [])
    if not isinstance(entities, list):
        _error(errors, f"{location}.entities", "typed analysis entities must be an array")
        entities = []
    for index, entity in enumerate(entities):
        entity_location = f"{location}.entities[{index}]"
        if not isinstance(entity, dict) or not isinstance(entity.get("id"), str) or not entity.get("id") or not isinstance(entity.get("kind"), str) or not entity.get("kind"):
            _error(errors, entity_location, "analysis-local entity requires stable id and kind")
            continue
        if entity["id"] in entity_ids:
            _error(errors, entity_location, f"duplicate analysis-local entity id {entity['id']!r}")
        entity_ids.add(entity["id"])
    relations = typed.get("relations", [])
    if not isinstance(relations, list):
        _error(errors, f"{location}.relations", "typed analysis relations must be an array")
        return relation_ids
    for index, relation in enumerate(relations):
        relation_location = f"{location}.relations[{index}]"
        if not isinstance(relation, dict):
            _error(errors, relation_location, "typed relation must be an object")
            continue
        relation_id = relation.get("id")
        if not isinstance(relation_id, str) or not relation_id:
            _error(errors, relation_location, "typed relation requires a stable non-empty id")
        elif relation_id in relation_ids:
            _error(errors, relation_location, f"duplicate typed relation id {relation_id!r}")
        else:
            relation_ids.add(relation_id)
        relation_type = relation.get("type")
        if not isinstance(relation_type, str) or not relation_type:
            _error(errors, relation_location, "typed relation requires a non-empty relation type")
        else:
            if relation_type in CANONICAL_SCALAR_RELATION_TYPES:
                _error(
                    errors,
                    relation_location,
                    f"typed relation {relation_type!r} duplicates a canonical scalar authority layer",
                )
            if relation_type not in CORE_TYPED_RELATION_TYPES and relation_type not in CANONICAL_SCALAR_RELATION_TYPES:
                qualified_type = ":" in relation_type or "/" in relation_type
                qualified_metadata = isinstance(relation.get("namespace"), str) and bool(relation.get("namespace"))
                qualified_metadata = qualified_metadata or _known(relation.get("framework"), FRAMEWORKS)
                if not qualified_type and not qualified_metadata:
                    _error(errors, relation_location, "unknown extension relation requires an explicit namespace, qualified type, or known framework")
        if relation.get("framework") is not None and not _known(relation.get("framework"), FRAMEWORKS):
            _error(errors, relation_location, "typed relation framework must name a known framework")
        if relation_type == "framework_relation" and not _known(relation.get("framework"), FRAMEWORKS) and not (isinstance(relation.get("namespace"), str) and relation.get("namespace")):
            _error(errors, relation_location, "framework_relation requires framework or namespace attribution")
        arity = relation.get("arity")
        has_target_field = "target" in relation
        has_target = has_target_field and relation.get("target") is not None
        if arity is None:
            _error(errors, relation_location, "typed relation requires explicit arity")
        elif arity not in {"unary", "binary"}:
            _error(errors, relation_location, "typed relation arity must be unary or binary")
        if arity == "binary" and not has_target:
            _error(errors, relation_location, "binary typed relation requires target")
        if arity == "unary" and has_target_field:
            _error(errors, relation_location, "unary typed relation cannot carry target")
        if relation_type in BINARY_TYPED_RELATION_TYPES and not has_target:
            _error(errors, relation_location, f"binary typed relation type {relation_type!r} requires target")
        _validate_typed_reference(relation.get("source"), f"{relation_location}.source", reference_ids, entity_ids, errors)
        if has_target:
            _validate_typed_reference(relation.get("target"), f"{relation_location}.target", reference_ids, entity_ids, errors)
        if preferred_authority and relation_type == "dependency" and has_target:
            source_id = _typed_reference_identifier(relation.get("source"))
            target_id = _typed_reference_identifier(relation.get("target"))
            if (source_id, target_id) in canonical_dependency_pairs:
                _error(errors, relation_location, "typed dependency duplicates the canonical dependencies layer")
    return relation_ids


def _authoritative_alternative_key(alternative: dict[str, Any]) -> str:
    typed = alternative.get("typed_analysis")
    typed_authority = {}
    if isinstance(typed, dict):
        typed_authority = {
            key: typed[key] for key in ("kind", "framework", "status", "arguments", "entities", "relations")
            if key in typed
        }
        if isinstance(typed_authority.get("entities"), list):
            typed_authority["entities"] = [
                {key: entity[key] for key in ("kind",) if key in entity}
                for entity in typed_authority["entities"]
                if isinstance(entity, dict)
            ]
        if isinstance(typed_authority.get("relations"), list):
            typed_authority["relations"] = [
                {key: relation[key] for key in ("type", "arity", "source", "target", "framework", "namespace", "status") if key in relation}
                for relation in typed_authority["relations"]
                if isinstance(relation, dict)
            ]
    return json.dumps(
        {
            "framework": alternative.get("framework"),
            "status": alternative.get("status"),
            "typed_analysis": typed_authority,
            "links": {key: alternative.get(key) for key in sorted(ALTERNATIVE_LINK_FIELDS) if key in alternative},
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _linked_ids(item: Any, fields: set[str]) -> set[str]:
    if not isinstance(item, dict):
        return set()
    linked: set[str] = set()
    for field in fields:
        values = item.get(field)
        if isinstance(values, list):
            linked.update(value for value in values if isinstance(value, str))
    for field in ("attachment", "target", "constituent", "clause"):
        if isinstance(item.get(field), str):
            linked.add(item[field])
    return linked


def _typed_reference_identifier(reference: Any) -> str | None:
    if isinstance(reference, dict) and isinstance(reference.get("id"), str):
        return reference["id"]
    if isinstance(reference, str) and ":" in reference:
        _, identifier = reference.split(":", 1)
        return identifier or None
    return None


def _validate_review_metadata(record: dict[str, Any], location: str, errors: list[str]) -> None:
    metadata = record.get("review_metadata")
    if metadata is None:
        return
    if not isinstance(metadata, dict):
        _error(errors, f"{location}.review_metadata", "review_metadata must be an object")
        return
    if not _known(metadata.get("review_status"), REVIEW_STATUSES):
        _error(errors, f"{location}.review_metadata", "review_status must be a known governance status")
    if not _known(metadata.get("reviewer_type"), REVIEWER_TYPES):
        _error(errors, f"{location}.review_metadata", "reviewer_type must be a known reviewer type")
    elif _known(metadata.get("review_status"), {"linguistically_reviewed", "approved_for_training", "canonical_gold"}) and metadata.get("reviewer_type") == "automated_structural":
        _error(errors, f"{location}.review_metadata", "linguistic/training/canonical status requires a human or mixed reviewer type")
    if not isinstance(metadata.get("migration_version"), str) or not metadata["migration_version"]:
        _error(errors, f"{location}.review_metadata", "migration_version must be a non-empty string")
    elif _is_v4(record) and not metadata.get("migration_version"):
        _error(errors, f"{location}.review_metadata", "V0.4 records require migration_version for process provenance")
    if "review_date" in metadata and (not isinstance(metadata["review_date"], str) or not metadata["review_date"]):
        _error(errors, f"{location}.review_metadata", "review_date must be a non-empty string when supplied")
    if metadata.get("review_status") == "canonical_gold":
        words = record.get("words") if isinstance(record.get("words"), list) else []
        clauses = record.get("clauses") if isinstance(record.get("clauses"), list) else []
        unresolved = any(isinstance(word, dict) and isinstance(word.get("lexical_analysis"), dict) and word["lexical_analysis"].get("status") == "unresolved" for word in words)
        unresolved = unresolved or any(
            isinstance(clause, dict)
            and (
                clause.get("clause_construction") == "unresolved"
                or "unresolved" in (clause.get("integration") or [])
                or clause.get("finiteness") == "unspecified"
                or clause.get("clause_form") == "unspecified"
            )
            for clause in clauses
        )
        unresolved = unresolved or any(
            isinstance(analysis, dict)
            and isinstance(analysis.get("typed_analysis"), dict)
            and analysis["typed_analysis"].get("status") in {"unresolved", "review_required"}
            for analysis in (record.get("canonical_analysis"), record.get("preferred_analysis"))
        )
        unresolved = unresolved or record.get("migration_review_required") is True
        all_alternatives = record.get("alternative_analyses", [])
        if not isinstance(all_alternatives, list):
            all_alternatives = []
        unresolved = unresolved or any(
            isinstance(analysis, dict) and isinstance(analysis.get("typed_analysis"), dict)
            and analysis["typed_analysis"].get("status") in {"unresolved", "review_required"}
            for analysis in all_alternatives
        )
        if isinstance(record.get("annotation_scope"), dict):
            required_dimensions = {"tokens", "lexical_category", "phrase_constituency", "clause_ontology", "syntactic_function"}
            declared = {
                entry.get("dimension") for entry in record["annotation_scope"].get("dimensions", [])
                if isinstance(entry, dict)
                and entry.get("omission") == "none"
                and entry.get("completeness") == "complete"
                and isinstance(entry.get("scope"), dict)
                and entry["scope"].get("kind") == "record"
            }
            if not required_dimensions.issubset(declared):
                unresolved = True
        if unresolved:
            _error(errors, f"{location}.review_metadata", "unresolved lexical or clause analysis cannot be canonical_gold")


def _validate_analysis(item: Any, location: str, errors: list[str], alternative: bool = False) -> None:
    if not isinstance(item, dict):
        _error(errors, location, "analysis must be an object")
        return
    if alternative:
        if not isinstance(item.get("id"), str) or not item.get("id"):
            _error(errors, location, "alternative analysis requires a stable non-empty id")
        if not _known(item.get("framework"), FRAMEWORKS):
            _error(errors, location, "alternative analysis must name a known framework")
        if item.get("status") not in ALTERNATIVE_STATUSES:
            _error(errors, location, "alternative analysis status must be established, unresolved, or review_required")
    else:
        if not item.get("label") or not isinstance(item.get("claims"), list) or not item.get("claims") or any(not isinstance(claim, str) or not claim for claim in item.get("claims", [])):
            _error(errors, location, "canonical analysis requires a non-empty label and claims list")
        if item.get("framework") is not None and not _known(item.get("framework"), FRAMEWORKS):
            _error(errors, location, "analysis framework attribution must name a known framework")
        typed = item.get("typed_analysis")
        if item.get("analysis_type") in FRAMEWORK_SENSITIVE_ANALYSIS_TYPES and item.get("framework") is None and not (isinstance(typed, dict) and _known(typed.get("framework"), FRAMEWORKS)):
            _error(errors, location, "framework-sensitive analysis_type requires explicit framework attribution")
    if alternative and "claims" in item and (not isinstance(item.get("claims"), list) or not item.get("claims") or any(not isinstance(claim, str) or not claim for claim in item.get("claims", []))):
        _error(errors, location, "alternative claims must be a non-empty string list when supplied")
    typed = item.get("typed_analysis")
    if not isinstance(typed, dict):
        _error(errors, location, "machine-authoritative analysis requires typed_analysis; claims prose is explanatory only")
    elif (not _known(typed.get("framework"), FRAMEWORKS) or not typed.get("kind") or typed.get("status") not in {"descriptive", "established", "unresolved", "review_required"}):
        _error(errors, location, "typed_analysis requires kind, known framework, and a valid status")
    elif alternative:
        if typed.get("framework") != item.get("framework"):
            _error(errors, location, "alternative framework must agree with typed_analysis.framework")
        if typed.get("status") != item.get("status"):
            _error(errors, location, "alternative status must agree with typed_analysis.status")


def _validate_predicand(value: Any, location: str, ids: set[str], objects: dict[str, dict[str, Any]], version: str, errors: list[str]) -> None:
    if value is None:
        return
    if isinstance(value, str):
        if version == "0.2":
            _error(errors, location, "V0.2 predicand must be a structured object")
        elif value not in ids:
            _error(errors, location, "predicand must reference a known ID")
        return
    if not isinstance(value, dict) or not _known(value.get("kind"), PREDICAND_KINDS):
        _error(errors, location, "predicand kind is invalid")
        return
    target = value.get("target")
    if value["kind"] in PREDICAND_TARGET_REQUIRED_KINDS:
        if not isinstance(target, str) or target not in ids:
            _error(errors, location, "overt_constituent and implicit_control predicands require a known target")
    elif target is not None and (not isinstance(target, str) or target not in ids):
        _error(errors, location, "predicand target must reference a known ID when supplied")


def _validate_coverage(record: dict[str, Any], location: str, errors: list[str]) -> None:
    scope = record.get("annotation_scope")
    if not isinstance(scope, dict):
        _error(errors, location, "annotation_scope must be an object")
        return
    coverage = scope.get("coverage")
    if not _known(coverage, ANNOTATION_COVERAGES):
        _error(errors, f"{location}.annotation_scope", "coverage must be complete_constituency or task_focused_partial")
    dimensions = scope.get("dimensions")
    if not isinstance(dimensions, list) or not dimensions:
        _error(errors, f"{location}.annotation_scope", "dimensions must declare dimension, scope, completeness, and omission")
        dimensions = []
    legacy_annotated = set(scope.get("annotated_dimensions", [])) if isinstance(scope.get("annotated_dimensions"), list) else set()
    legacy_omitted = set(scope.get("intentionally_omitted", [])) if isinstance(scope.get("intentionally_omitted"), list) else set()
    if "annotated_dimensions" in scope and (not isinstance(scope.get("annotated_dimensions"), list) or any(not _known(value, ANNOTATED_DIMENSIONS) for value in scope.get("annotated_dimensions", []))):
        _error(errors, f"{location}.annotation_scope", "annotated_dimensions contains an unknown dimension")
    if "intentionally_omitted" in scope and (not isinstance(scope.get("intentionally_omitted"), list) or any(not _known(value, ANNOTATED_DIMENSIONS) for value in scope.get("intentionally_omitted", []))):
        _error(errors, f"{location}.annotation_scope", "intentionally_omitted contains an unknown dimension")
    overlap = legacy_annotated & legacy_omitted
    if overlap:
        _error(errors, f"{location}.annotation_scope", f"legacy coverage summaries conflict for dimensions: {sorted(overlap)}")
    for issue in coverage_declaration_issues(record):
        _error(errors, f"{location}.annotation_scope.dimensions[{issue.index}]", issue.message)
    entries: dict[tuple[str, tuple[Any, ...]], dict[str, Any]] = {}
    for index, entry in enumerate(dimensions):
        entry_location = f"{location}.annotation_scope.dimensions[{index}]"
        if not isinstance(entry, dict):
            _error(errors, entry_location, "coverage dimension must be an object")
            continue
        dimension = entry.get("dimension")
        spec = dimension_spec(dimension)
        if spec is None:
            _error(errors, entry_location, "unknown coverage dimension")
            continue
        coverage_scope = entry.get("scope")
        scope_key = (dimension, coverage_scope_key(coverage_scope))
        entries[scope_key] = entry
    by_dimension: dict[str, list[dict[str, Any]]] = {}
    for (dimension, _), entry in entries.items():
        by_dimension.setdefault(dimension, []).append(entry)
    for dimension, entries_for_dimension in by_dimension.items():
        annotated = [entry for entry in entries_for_dimension if entry.get("omission") == "none"]
    if coverage == "complete_constituency":
        required_dimensions = {"tokens", "lexical_category", "phrase_constituency", "clause_ontology", "syntactic_function"}
        declared = {dimension for dimension, values in by_dimension.items() if any(value.get("omission") == "none" for value in values)}
        if not required_dimensions.issubset(declared):
            _error(errors, f"{location}.annotation_scope", "complete_constituency must annotate all core structural dimensions")
        if any(
            not any(
                value.get("completeness") == "complete"
                and value.get("omission") == "none"
                and isinstance(value.get("scope"), dict)
                and value["scope"].get("kind") == "record"
                for value in by_dimension.get(dimension, [])
            )
            for dimension in required_dimensions
        ):
            _error(errors, f"{location}.annotation_scope", "complete_constituency core dimensions must be complete at record scope")
        if not isinstance(record.get("constituents"), list) or not record["constituents"]:
            _error(errors, f"{location}.annotation_scope", "complete_constituency requires actual constituent structure")


def coverage_allows_score(record: dict[str, Any], dimension: str, target: str | None = None) -> bool:
    """Return whether a requested dimension/target is declared scorable."""
    return resolve_scoring_eligibility(record, dimension, target).scoreable


def validate_record(record: Any, location: str, schema_path: Path | None = None) -> list[str]:
    errors: list[str] = []
    if not isinstance(record, dict):
        _error(errors, location, "record must be an object")
        return errors
    if "messages" in record and "schema_version" not in record:
        _validate_rendered_schema(record, location, errors)
        messages = record.get("messages")
        if not isinstance(record.get("id"), str) or not record["id"]:
            _error(errors, location, "rendered record id must be a non-empty string")
        if not isinstance(messages, list) or [message.get("role") for message in messages if isinstance(message, dict)] != ["system", "user", "assistant"]:
            _error(errors, location, "rendered messages must contain system, user, assistant in order")
        else:
            for index, message in enumerate(messages):
                if not isinstance(message.get("content"), str) or not message["content"]:
                    _error(errors, f"{location}.messages[{index}]", "message content must be a non-empty string")
            if len(messages) == 3 and isinstance(messages[2], dict) and isinstance(messages[2].get("content"), str):
                try:
                    payload = json.loads(messages[2]["content"])
                except json.JSONDecodeError as error:
                    _error(errors, f"{location}.messages[2].content", f"assistant content must be valid JSON: {error.msg}")
                else:
                    if not isinstance(payload, dict):
                        _error(errors, f"{location}.messages[2].content", "assistant JSON payload must be an object")
                    else:
                        sidecar = record.get("governance_sidecar") if isinstance(record.get("governance_sidecar"), dict) else {}
                        if sidecar.get("record_id") != record.get("id"):
                            _error(errors, f"{location}.governance_sidecar.record_id", "governance sidecar record_id must match rendered record id")
                        payload_id = payload.get("id")
                        if payload_id is not None and payload_id != record.get("id"):
                            _error(errors, f"{location}.messages[2].content.id", "assistant payload id must match rendered record id when supplied")
                        if not isinstance(payload.get("sentence"), str):
                            _error(errors, f"{location}.messages[2].content", "linguistic projection must include sentence")
                        for field in ("words", "clauses", "constituents", "dependencies", "semantic_roles"):
                            if field in payload and not isinstance(payload[field], list):
                                _error(errors, f"{location}.messages[2].content.{field}", "projected linguistic collection must be an array when present")
                        if sidecar.get("schema_version") != "0.4":
                            _error(errors, f"{location}.governance_sidecar.schema_version", "rendered target must identify canonical V0.4")
                        if any(key in payload for key in {"review_metadata", "migration_metadata", "migration_review_required", "schema_version", "split", "id"}):
                            _error(errors, f"{location}.messages[2].content", "assistant projection contains governance-only fields")
                        leaks = _rendered_governance_leaks(payload)
                        if leaks:
                            _error(errors, f"{location}.messages[2].content", f"assistant projection contains governance-only fields at {leaks}")
                        _validate_rendered_references(payload, f"{location}.messages[2].content", errors)
        return errors
    _validate_json_schema(record, location, errors, schema_path)
    try:
        required_fields = canonical_schema_required_fields(schema_path)
    except (OSError, json.JSONDecodeError, RuntimeError, TypeError):
        return errors
    missing = required_fields - record.keys()
    for field in sorted(missing):
        _error(errors, location, f"missing required field {field!r}")
    if missing:
        return errors
    _validate_review_metadata(record, location, errors)
    version = record["schema_version"]
    if version not in SCHEMA_VERSIONS:
        _error(errors, location, "schema_version must be '0.1', '0.2', or canonical '0.4'; legacy '0.3' requires explicit legacy handling")
    if _is_v3(record):
        _validate_coverage(record, location, errors)
        construction_tags = record.get("construction_tags")
        if construction_tags is not None and (not isinstance(construction_tags, list) or any(not isinstance(item, str) or not item.strip() for item in construction_tags)):
            _error(errors, location, "construction_tags must be a list of non-empty strings")
    if not isinstance(record["id"], str) or not record["id"]:
        _error(errors, location, "id must be a non-empty string")
    if not isinstance(record["sentence"], str) or not record["sentence"].strip():
        _error(errors, location, "sentence must be a non-empty string")
    tags = record["capability_tags"]
    if not isinstance(tags, list) or not tags or any(not _known(tag, CAPABILITY_TAGS) for tag in tags):
        _error(errors, location, "capability_tags must contain only known, non-empty tags")
    if isinstance(tags, list) and all(isinstance(tag, str) for tag in tags) and len(tags) != len(set(tags)):
        _error(errors, location, "capability_tags must be unique")
    if not _known(record["difficulty"], DIFFICULTIES):
        _error(errors, location, f"invalid difficulty {record['difficulty']!r}")
    if not _known(record["source_type"], SOURCE_TYPES):
        _error(errors, location, f"invalid source_type {record['source_type']!r}")
    framework = record["framework"]
    if not isinstance(framework, dict) or not _known(framework.get("preferred"), FRAMEWORKS):
        _error(errors, location, "framework.preferred must be a known framework")
    else:
        if _is_v4(record) and framework.get("preferred") != CANONICAL_FRAMEWORK:
            _error(errors, location, "V0.4 canonical records must use framework.preferred='cgel_inspired'; alternatives need explicit attribution")
        if _is_v4(record) and "alternatives" in framework:
            _error(errors, f"{location}.framework.alternatives", "framework.alternatives is a legacy/non-authoritative channel; use alternative_analyses")
    if _is_v4(record) and "framework_alternatives" in record:
        _error(errors, f"{location}.framework_alternatives", "framework_alternatives is a legacy/non-authoritative channel; use alternative_analyses")
    if not _known(record["sentence_type"], SENTENCE_TYPES):
        _error(errors, location, f"invalid sentence_type {record['sentence_type']!r}")
    metadata = record.get("sentence_type_metadata")
    if metadata is not None and (not isinstance(metadata, dict) or not isinstance(metadata.get("scheme"), str) or not metadata["scheme"]):
        _error(errors, location, "sentence_type_metadata.scheme must be a non-empty string")
    classification = record.get("sentence_classification")
    if classification is not None and (not isinstance(classification, dict) or not _known(classification.get("label"), SENTENCE_CLASSIFICATION_LABELS) or not isinstance(classification.get("scheme"), str) or not classification["scheme"]):
        _error(errors, location, "sentence_classification requires a known scheme and simple/compound/complex label")

    words = record["words"]
    word_ids: set[str] = set()
    if not isinstance(words, list) or not words:
        _error(errors, location, "words must be a non-empty list")
        words = []
    for index, word in enumerate(words):
        word_location = f"{location}.words[{index}]"
        if not isinstance(word, dict):
            _error(errors, word_location, "word must be an object")
            continue
        for field in ("id", "form", "lemma"):
            if not isinstance(word.get(field), str) or not word[field]:
                _error(errors, word_location, f"{field} must be a non-empty string")
        if "lexical_category" not in word:
            _error(errors, word_location, "lexical_category must be present; use null with lexical_analysis when unresolved")
        if _is_v2(record) and word.get("node_kind") != "word":
            _error(errors, word_location, "V0.2 words must have node_kind='word'")
        word_id = word.get("id")
        if isinstance(word_id, str):
            if word_id in word_ids:
                _error(errors, word_location, f"duplicate word id {word_id!r}")
            word_ids.add(word_id)
        lexical_category = word.get("lexical_category")
        lexical_analysis = word.get("lexical_analysis")
        if word.get("syntactic_function") == "determinative":
            _error(errors, word_location, "determinative is a lexical category; syntactic function must be 'determiner'")
        if lexical_category is not None and not _known(lexical_category, LEXICAL_CATEGORIES):
            _error(errors, word_location, "unknown lexical_category; syntactic function 'determiner' is not a lexical category")
        if lexical_category is None:
            if not isinstance(lexical_analysis, dict) or lexical_analysis.get("status") != "unresolved":
                _error(errors, word_location, "null lexical_category requires an unresolved lexical_analysis")
        if isinstance(lexical_analysis, dict):
            if lexical_analysis.get("status") != "unresolved" or lexical_analysis.get("review_required") is not True:
                _error(errors, f"{word_location}.lexical_analysis", "unresolved lexical analyses require status='unresolved' and review_required=true")
            if lexical_analysis.get("status") == "unresolved" and lexical_category is not None:
                _error(errors, f"{word_location}.lexical_analysis", "unresolved lexical analyses cannot retain a canonical lexical_category")
            candidates = lexical_analysis.get("candidates")
            if not isinstance(candidates, list) or not candidates:
                _error(errors, f"{word_location}.lexical_analysis", "unresolved lexical analysis requires candidate analyses")
            else:
                for candidate_index, candidate in enumerate(candidates):
                    candidate_location = f"{word_location}.lexical_analysis.candidates[{candidate_index}]"
                    candidate_category = candidate.get("category", candidate.get("lexical_category")) if isinstance(candidate, dict) else None
                    candidate_namespace = candidate.get("category_namespace", candidate.get("framework")) if isinstance(candidate, dict) else None
                    if not isinstance(candidate, dict) or not isinstance(candidate_category, str) or not candidate_category.strip() or not isinstance(candidate_namespace, str) or not candidate_namespace.strip():
                        _error(errors, candidate_location, "each lexical candidate requires a non-empty category and category namespace/framework")
                    elif candidate.get("framework") is not None and not _known(candidate.get("framework"), FRAMEWORKS):
                        _error(errors, candidate_location, "lexical candidate framework must name a known framework when supplied")
                    elif candidate.get("category") == "determiner" or candidate.get("lexical_category") == "determiner" or candidate.get("syntactic_function") == "determinative":
                        _error(errors, candidate_location, "candidate must keep lexical category and syntactic function in separate fields")
                    if isinstance(candidate, dict) and any(key in candidate for key in ("external_pos_tags", "pos", "pos_tagset")):
                        _error(errors, candidate_location, "external_pos_tags are a separate layer and cannot be embedded in lexical candidates")
        tags_for_word = word.get("external_pos_tags")
        if tags_for_word is not None:
            if not isinstance(tags_for_word, list):
                _error(errors, word_location, "external_pos_tags must be an array")
            else:
                for tag_index, tag in enumerate(tags_for_word):
                    if not isinstance(tag, dict) or not isinstance(tag.get("tagset"), str) or not tag["tagset"] or not isinstance(tag.get("tag"), str) or not tag["tag"]:
                        _error(errors, f"{word_location}.external_pos_tags[{tag_index}]", "external POS tags require tagset and tag")
        if _is_v3(record) and "pos" in word:
            _error(errors, word_location, "V0.3 words must use lexical_category and external_pos_tags; legacy pos is migration-only")
        if _is_v3(record) and "pos_tagset" in word:
            _error(errors, word_location, "V0.3 words must use external_pos_tags; legacy pos_tagset is migration-only")
        if (_is_v2(record) or _is_v3(record)) and "pos" in word and "pos_tagset" not in word and not tags_for_word:
            _error(errors, word_location, "legacy pos requires pos_tagset; use external_pos_tags with an explicit tagset")
        if (_is_v2(record) or _is_v3(record)) and "pedagogical_terms" in word:
            _error(errors, word_location, "pedagogical terms belong in framework-qualified pedagogical_aliases")

    max_token = len(words)
    sentence_tokens, word_tokens = sentence_word_alignment(record)
    normalized_sentence_tokens = normalized_surface_tokens(record.get("sentence", ""))
    normalized_word_tokens = [str(token).casefold() for token in word_tokens]
    if normalized_sentence_tokens != normalized_word_tokens:
        _error(
            errors,
            location,
            "sentence/words token alignment mismatch: sentence surface tokens "
            f"{sentence_tokens!r} do not equal words.form sequence {word_tokens!r}",
        )
    constituent_items = record["constituents"] if isinstance(record["constituents"], list) else []
    clause_items = record["clauses"] if isinstance(record["clauses"], list) else []
    ids: set[str] = set()
    for item in constituent_items + clause_items:
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            if item["id"] in ids:
                _error(errors, location, f"duplicate constituent/clause id {item['id']!r}")
            ids.add(item["id"])
    for duplicate_id in sorted(word_ids & ids):
        _error(errors, location, f"word and constituent/clause IDs must be unique; repeated {duplicate_id!r}")
    all_ids = ids | word_ids
    objects: dict[str, dict[str, Any]] = {}
    for word in words:
        if isinstance(word, dict) and isinstance(word.get("id"), str):
            objects[word["id"]] = word
    for item in constituent_items + clause_items:
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            objects[item["id"]] = item
    for field_name in ("constituents", "clauses"):
        items = record[field_name]
        if not isinstance(items, list):
            _error(errors, location, f"{field_name} must be a list")
            continue
        for index, item in enumerate(items):
            item_location = f"{location}.{field_name}[{index}]"
            if not isinstance(item, dict):
                _error(errors, item_location, "item must be an object")
                continue
            required = ("id", "span", "function") if field_name == "constituents" else ("id", "span", "node_kind", "finiteness", "clause_construction", "integration")
            for field in required:
                if field not in item:
                    _error(errors, item_location, f"missing {field}")
            span = item.get("span", {})
            if not isinstance(span, dict) or not isinstance(span.get("start"), int) or not isinstance(span.get("end"), int) or span.get("start", -1) < 0 or span.get("end", 0) <= span.get("start", 0) or span.get("end", 0) > max_token:
                _error(errors, item_location, "span must be a valid half-open token span")
            elif isinstance(words[span["end"] - 1], dict) and words[span["end"] - 1].get("lexical_category") == "punctuation":
                if _is_v3(record):
                    _error(errors, item_location, "structural spans must exclude sentence-final punctuation")
                else:
                    is_main_clause = field_name == "clauses" and item.get("clause_category") == "main_clause"
                    if not is_main_clause:
                        _error(errors, item_location, "only main_clause spans may terminate at a punctuation token")
            if field_name == "constituents" and (not isinstance(item.get("function"), str) or not item.get("function")):
                _error(errors, item_location, "function must be a non-empty string")
            if field_name == "constituents":
                constituent_category = item.get("phrase_category") or item.get("category")
                if item.get("function") == "determinative":
                    _error(errors, item_location, "determinative is a lexical category; syntactic function must be 'determiner'")
                if _is_v2(record) or _is_v3(record):
                    if item.get("node_kind") not in {"phrase", "clause", "word"}:
                        _error(errors, item_location, "V0.3/V0.2 constituents require node_kind phrase, clause, or word")
                    if item.get("node_kind") == "phrase":
                        if not _known(item.get("phrase_category"), PHRASE_CATEGORIES):
                            _error(errors, item_location, "phrase nodes require a valid phrase category in phrase_category; Clause is not a phrase category")
                        if item.get("phrase_category") == "word":
                            _error(errors, item_location, "word category requires node_kind='word', not a phrase node")
                        if "clause_ref" in item:
                            _error(errors, item_location, "clause_ref is reserved for node_kind='clause' wrappers")
                        if "category" in item:
                            _error(errors, item_location, "V0.2 phrase nodes must use phrase_category; category is a V0.1 compatibility field")
                    elif item.get("node_kind") == "clause":
                        clause_ids = {
                            clause.get("id") for clause in clause_items
                            if isinstance(clause, dict) and isinstance(clause.get("id"), str)
                        }
                        if not isinstance(item.get("clause_ref"), str) or item.get("clause_ref") not in clause_ids:
                            _error(errors, item_location, "clause node must reference a known clause with clause_ref")
                        if item.get("phrase_category") is not None or item.get("category") is not None:
                            _error(errors, item_location, "clause nodes must use clause_ref, not phrase/category")
                        realization = item.get("realization")
                        if not isinstance(realization, dict):
                            _error(errors, item_location, "clause-valued constituents require an explicit realization relation")
                        else:
                            if realization.get("clause_ref") != item.get("clause_ref"):
                                _error(errors, item_location, "realization.clause_ref must agree with clause_ref")
                            if realization.get("relation") not in {"same_span_alias", "expanded_realization", "other"}:
                                _error(errors, item_location, "realization relation is invalid")
                            elif isinstance(span, dict) and isinstance(objects.get(item.get("clause_ref")), dict):
                                clause_span = objects[item["clause_ref"]].get("span", {})
                                if isinstance(clause_span, dict) and realization.get("relation") == "same_span_alias" and span != clause_span:
                                    _error(errors, item_location, "same_span_alias requires wrapper and clause spans to match")
                                if isinstance(clause_span, dict) and realization.get("relation") == "expanded_realization" and not (span.get("start", 0) <= clause_span.get("start", 0) and span.get("end", 0) >= clause_span.get("end", 0)):
                                    _error(errors, item_location, "expanded_realization wrapper must contain the clause span")
                        if "span_relation" in item and item.get("span_relation") != (realization or {}).get("relation"):
                            _error(errors, item_location, "span_relation must agree with realization.relation")
                    elif item.get("node_kind") == "word" and any(key in item for key in ("phrase_category", "category", "clause_ref")):
                        _error(errors, item_location, "word nodes must use the words collection, not phrase/clause category fields")
                elif not _known(item.get("category"), PHRASE_CATEGORIES | {"Clause"}):
                    _error(errors, item_location, "unknown phrase category")
                if constituent_category == "PP" and item.get("function") == "AdvP":
                    _error(errors, item_location, "PP is a phrase category; AdvP is not a syntactic function")
                if (_is_v2(record) or _is_v3(record)) and "role" in item:
                    _error(errors, item_location, "semantic roles belong in semantic_roles, not constituent.role")
                if "head" in item and item.get("head") is not None:
                    _require_ref_kind(item.get("head"), objects, {"word"}, f"{item_location}.head", errors, "constituent.head")
                if "parent" in item and item.get("parent") is not None:
                    _require_ref_kind(item.get("parent"), objects, {"phrase", "clause"}, f"{item_location}.parent", errors, "constituent.parent")
            else:
                category = item.get("clause_category") or item.get("category")
                if _is_v3(record):
                    if item.get("node_kind") != "clause":
                        _error(errors, item_location, "V0.3 clause entries require node_kind='clause'")
                    if any(key in item for key in ("clause_category", "category", "clause_type", "clause_status")):
                        _error(errors, item_location, "V0.3 clauses must use clause_construction and integration; legacy clause fields are rejected")
                    if "function" in item:
                        _error(errors, item_location, "clause function is not authoritative; put external function on a clause-valued constituent")
                    if not _known(item.get("clause_construction"), CLAUSE_CONSTRUCTIONS):
                        _error(errors, item_location, "clause_construction must be a known construction value")
                    integration = item.get("integration")
                    if not isinstance(integration, list) or not integration or any(not _known(value, CLAUSE_INTEGRATIONS) for value in integration) or len(integration) != len(set(integration or [])):
                        _error(errors, item_location, "integration must be a non-empty unique list of known relations")
                    elif "root" in integration and len(integration) != 1:
                        _error(errors, item_location, "root integration cannot mix unresolved or another integration relation")
                    elif "unresolved" in integration and len(integration) != 1:
                        _error(errors, item_location, "integration cannot mix unresolved with a resolved relation")
                    if not _known(item.get("finiteness"), CLAUSE_FINITE_VALUES):
                        _error(errors, item_location, "finiteness must be finite, nonfinite, verbless, or unspecified")
                    clause_form = item.get("clause_form")
                    if item.get("finiteness") == "nonfinite" and not _known(clause_form, CLAUSE_FORMS):
                        _error(errors, item_location, "nonfinite clauses require a known clause_form")
                    if item.get("finiteness") != "nonfinite" and clause_form is not None:
                        _error(errors, item_location, "clause_form is only permitted for nonfinite clauses")
                    marker_ids = item.get("marker_ids", [])
                    if not isinstance(marker_ids, list) or any(not isinstance(marker, str) or marker not in all_ids for marker in marker_ids):
                        _error(errors, f"{item_location}.marker_ids", "marker_ids must reference known IDs")
                    else:
                        for marker in marker_ids:
                            if _ref_kind(marker, objects) != "word":
                                _error(errors, f"{item_location}.marker_ids", "marker_ids must reference words")
                            elif isinstance(span, dict) and isinstance(span.get("start"), int) and isinstance(span.get("end"), int):
                                marker_index = next((position for position, word in enumerate(words) if isinstance(word, dict) and word.get("id") == marker), None)
                                if marker_index is not None and not (span["start"] <= marker_index < span["end"]):
                                    _error(errors, f"{item_location}.marker_ids", "clause marker must lie inside clause span")
                elif _is_v2(record):
                    if item.get("node_kind") != "clause":
                        _error(errors, item_location, "V0.2 clause entries require node_kind='clause'")
                    if not _known(item.get("clause_category"), CLAUSE_CATEGORIES):
                        _error(errors, item_location, "V0.2 clauses require clause_category")
                    if "category" in item:
                        _error(errors, item_location, "V0.2 clauses must use clause_category; category is a V0.1 compatibility field")
                elif not _known(category, CLAUSE_CATEGORIES):
                    _error(errors, item_location, "unknown clause category")
                if not _is_v3(record):
                    if not _known(item.get("finiteness"), {"finite", "non-finite"}):
                        _error(errors, item_location, "finiteness must be finite or non-finite")
                    if item.get("finiteness") == "finite" and isinstance(category, str) and category in {"nonfinite_clause", "gerund_participial_clause", "infinitival_clause"}:
                        _error(errors, item_location, "non-finite clause category cannot be marked finite")
                for ref_field in ("subject", "head"):
                    if ref_field in item and not _valid_ref(item.get(ref_field), all_ids):
                        _error(errors, item_location, f"{ref_field} must reference a known ID")
                if "integration_parent" in item and item.get("integration_parent") is not None:
                    parent = item.get("integration_parent")
                    if not isinstance(parent, str) or parent not in {clause.get("id") for clause in clause_items if isinstance(clause, dict)}:
                        _error(errors, f"{item_location}.integration_parent", "integration_parent must reference a known clause ID")
                    elif _ref_kind(parent, objects) != "clause":
                        _error(errors, f"{item_location}.integration_parent", "integration_parent must reference a clause, not another node kind")
                if item.get("subject") is not None:
                    subject_id = item.get("subject")
                    subject_kind = _ref_kind(subject_id, objects)
                    subject_object = objects.get(subject_id) if isinstance(subject_id, str) else None
                    if subject_kind not in {"word", "phrase", "clause"}:
                        _error(errors, f"{item_location}.subject", "clause.subject must reference a word, phrase, or clause")
                    elif subject_kind == "word" and subject_object.get("lexical_category") not in NOMINAL_SUBJECT_CATEGORIES:
                        _error(errors, f"{item_location}.subject", "clause.subject word reference must be nominal, not a marker/verb/punctuation")
                    elif subject_kind == "phrase" and subject_object.get("phrase_category") != "NP":
                        _error(errors, f"{item_location}.subject", "clause.subject phrase reference must be an NP")
                _validate_predicand(item.get("predicand"), f"{item_location}.predicand", all_ids, objects, version, errors)

    if _is_v4(record) and isinstance(record.get("constituents"), list):
        for issue in canonical_record_consistency_issues(record):
            if issue.code == "duplicate_clause_wrapper":
                _error(errors, location, issue.message)
        wrapped_clause_ids = {
            item.get("clause_ref") for item in record["constituents"]
            if isinstance(item, dict) and item.get("node_kind") == "clause" and isinstance(item.get("clause_ref"), str)
        }
        annotation_scope = record.get("annotation_scope")
        coverage_entries = annotation_scope.get("dimensions", []) if isinstance(annotation_scope, dict) else []
        if not isinstance(coverage_entries, list):
            coverage_entries = []
        for clause in record.get("clauses", []):
            if not isinstance(clause, dict) or "root" in (clause.get("integration") or []) or clause.get("id") in wrapped_clause_ids:
                continue
            clause_span = clause.get("span") if isinstance(clause.get("span"), dict) else {}
            clause_start, clause_end = clause_span.get("start"), clause_span.get("end")
            function_coverage_applies = False
            for entry in coverage_entries:
                if not isinstance(entry, dict) or entry.get("dimension") != "syntactic_function" or entry.get("omission") != "none" or entry.get("completeness") != "complete":
                    continue
                coverage_scope = entry.get("scope") if isinstance(entry.get("scope"), dict) else {}
                if coverage_scope.get("kind") == "record":
                    function_coverage_applies = True
                elif (
                    coverage_scope.get("kind") == "region"
                    and type(coverage_scope.get("start")) is int
                    and type(coverage_scope.get("end")) is int
                    and type(clause_start) is int
                    and type(clause_end) is int
                    and coverage_scope["start"] <= clause_start
                    and clause_end <= coverage_scope["end"]
                ):
                    function_coverage_applies = True
                if function_coverage_applies:
                    break
            if function_coverage_applies:
                _error(errors, location, f"complete syntactic-function coverage requires an external realization wrapper for clause {clause.get('id')!r}")

    if _is_v3(record) and isinstance(record.get("clauses"), list):
        for issue in canonical_record_consistency_issues(record):
            if issue.code in {"multiple_root_clauses", "sentence_type_root_construction_contradiction"}:
                _error(errors, location, issue.message)

    dependencies = record["dependencies"] if isinstance(record["dependencies"], list) else []
    if not isinstance(record["dependencies"], list):
        _error(errors, location, "dependencies must be a list")
    for index, dependency in enumerate(dependencies):
        dependency_head = dependency.get("head") if isinstance(dependency, dict) else None
        dependency_dependent = dependency.get("dependent") if isinstance(dependency, dict) else None
        if not isinstance(dependency, dict) or not dependency.get("relation") or not isinstance(dependency_head, str) or dependency_head not in all_ids or not isinstance(dependency_dependent, str) or dependency_dependent not in all_ids:
            _error(errors, f"{location}.dependencies[{index}]", "dependency must reference known IDs")
        elif dependency.get("source") is not None or dependency.get("target") is not None:
            for field in ("source", "target"):
                if dependency.get(field) is not None and (not isinstance(dependency.get(field), str) or dependency.get(field) not in all_ids):
                    _error(errors, f"{location}.dependencies[{index}].{field}", "dependency source/target must reference a known ID")
    for field_name in ("complements", "adjuncts"):
        values = record.get(field_name)
        if values is not None and (not isinstance(values, list) or any(not isinstance(value, str) or value not in ids for value in values)):
            _error(errors, location, f"{field_name} must be a list of constituent/clause IDs")
    heads = record.get("heads")
    if heads is not None and (not isinstance(heads, list) or any(not isinstance(item, dict) or not isinstance(item.get("head"), str) or item.get("head") not in all_ids or not isinstance(item.get("dependent"), str) or item.get("dependent") not in all_ids for item in heads)):
        _error(errors, location, "heads must contain references to known IDs")
    if isinstance(heads, list):
        for index, item in enumerate(heads):
            if not isinstance(item, dict):
                continue
            if isinstance(item.get("head"), str) and item.get("head") in all_ids:
                _require_ref_kind(item.get("head"), objects, {"word", "phrase", "clause"}, f"{location}.heads[{index}].head", errors, "head relation head")
            if isinstance(item.get("dependent"), str) and item.get("dependent") in all_ids:
                _require_ref_kind(item.get("dependent"), objects, {"word", "phrase", "clause"}, f"{location}.heads[{index}].dependent", errors, "head relation dependent")

    lexical_valency = record.get("lexical_valency", [])
    if lexical_valency is not None and not isinstance(lexical_valency, list):
        _error(errors, location, "lexical_valency must be an array")
        lexical_valency = []
    for index, valency in enumerate(lexical_valency or []):
        valency_location = f"{location}.lexical_valency[{index}]"
        if not isinstance(valency, dict):
            _error(errors, valency_location, "lexical valency must be an object")
            continue
        predicate_issue = predicate_reference_issue(record, valency.get("predicate"), "lexical valency predicate")
        if predicate_issue is not None:
            _error(errors, f"{valency_location}.predicate", predicate_issue)
        selected = valency.get("selected_complements")
        if not isinstance(selected, list):
            _error(errors, valency_location, "selected_complements must be an array")
        else:
            for selected_index, reference in enumerate(selected):
                if not isinstance(reference, str) or reference not in all_ids:
                    _error(errors, f"{valency_location}.selected_complements[{selected_index}]", "selected complement must reference a known ID")
                elif _ref_kind(reference, objects) not in {"phrase", "clause"}:
                    _error(errors, f"{valency_location}.selected_complements[{selected_index}]", "selected complement must reference a phrase or clause, not a word")

    analyses = []
    typed_relation_ids: set[str] = set()

    def merge_typed_relation_ids(relation_ids: set[str], relation_location: str) -> None:
        overlap = typed_relation_ids & relation_ids
        if overlap:
            _error(errors, relation_location, f"typed relation IDs must be unique within the record; repeated {sorted(overlap)}")
        typed_relation_ids.update(relation_ids)

    if "canonical_analysis" in record:
        _validate_analysis(record["canonical_analysis"], f"{location}.canonical_analysis", errors)
        analyses.append(record["canonical_analysis"])
        if isinstance(record["canonical_analysis"], dict):
            merge_typed_relation_ids(_validate_typed_analysis(
                record["canonical_analysis"].get("typed_analysis"),
                f"{location}.canonical_analysis.typed_analysis",
                record,
                errors,
                preferred_authority=True,
            ), f"{location}.canonical_analysis.typed_analysis")
    if "preferred_analysis" in record:
        _validate_analysis(record["preferred_analysis"], f"{location}.preferred_analysis", errors)
        analyses.append(record["preferred_analysis"])
        if isinstance(record["preferred_analysis"], dict):
            merge_typed_relation_ids(_validate_typed_analysis(
                record["preferred_analysis"].get("typed_analysis"),
                f"{location}.preferred_analysis.typed_analysis",
                record,
                errors,
                preferred_authority=True,
            ), f"{location}.preferred_analysis.typed_analysis")
        if _is_v3(record):
            _error(errors, location, "V0.4 records must use canonical_analysis; preferred_analysis is migration-only")
    if not analyses:
        _error(errors, location, "record requires canonical_analysis or preferred_analysis")
    if len(analyses) == 2 and analyses[0] != analyses[1]:
        _error(errors, location, "canonical_analysis and preferred_analysis disagree; keep one source of truth")
    alternative_ids: set[str] = set()
    alternative_keys: set[str] = set()
    alternatives = record.get("alternative_analyses", [])
    if not isinstance(alternatives, list):
        _error(errors, location, "alternative_analyses must be an array")
        alternatives = []
    clause_ids = {
        clause.get("id") for clause in clause_items
        if isinstance(clause, dict) and isinstance(clause.get("id"), str)
    }
    wrapper_ids = {
        item.get("id") for item in constituent_items
        if isinstance(item, dict) and item.get("node_kind") == "clause" and isinstance(item.get("id"), str)
    }
    for index, item in enumerate(alternatives):
        alternative_location = f"{location}.alternative_analyses[{index}]"
        _validate_analysis(item, alternative_location, errors, alternative=True)
        if not isinstance(item, dict):
            continue
        alternative_id = item.get("id")
        if isinstance(alternative_id, str):
            if alternative_id in alternative_ids:
                _error(errors, alternative_location, f"duplicate alternative id {alternative_id!r}")
            alternative_ids.add(alternative_id)
        alternative_key = _authoritative_alternative_key(item)
        if alternative_key in alternative_keys:
            _error(errors, alternative_location, "duplicate equivalent authoritative alternative")
        alternative_keys.add(alternative_key)
        merge_typed_relation_ids(_validate_typed_analysis(
            item.get("typed_analysis"),
            f"{alternative_location}.typed_analysis",
            record,
            errors,
            preferred_authority=False,
        ), f"{alternative_location}.typed_analysis")
        for field in ALTERNATIVE_LINK_FIELDS:
            values = item.get(field)
            if values is None:
                continue
            if not isinstance(values, list) or any(not isinstance(value, str) or not value for value in values):
                _error(errors, f"{alternative_location}.{field}", "alternative linkage must be a list of non-empty IDs")
                continue
            if field == "linked_wrapper_ids":
                unknown = set(values) - wrapper_ids
            elif field == "linked_constituent_ids":
                unknown = set(values) - ids
            elif field == "linked_clause_refs":
                unknown = set(values) - clause_ids
            else:
                unknown = set(values) - typed_relation_ids
            if unknown:
                _error(errors, f"{alternative_location}.{field}", f"alternative linkage references unknown IDs: {sorted(unknown)}")
    aliases = record.get("pedagogical_aliases")
    if aliases is not None:
        if not isinstance(aliases, list):
            _error(errors, location, "pedagogical_aliases must be an array")
        else:
            for index, alias in enumerate(aliases):
                if not isinstance(alias, dict) or not alias.get("term") or alias.get("framework") != "traditional_pedagogical":
                    _error(errors, f"{location}.pedagogical_aliases[{index}]", "pedagogical aliases require framework='traditional_pedagogical'")

    semantic_roles = record.get("semantic_roles", [])
    if semantic_roles is not None and not isinstance(semantic_roles, list):
        _error(errors, location, "semantic_roles must be an array")
        semantic_roles = []
    for index, role_item in enumerate(semantic_roles or []):
        role_constituent = role_item.get("constituent") if isinstance(role_item, dict) else None
        if not isinstance(role_item, dict) or not isinstance(role_constituent, str) or role_constituent not in ids or not _known(role_item.get("role"), SEMANTIC_ROLES):
            _error(errors, f"{location}.semantic_roles[{index}]", "semantic role must reference a constituent and use the controlled vocabulary")
        elif role_item.get("predicate") is not None:
            predicate_issue = predicate_reference_issue(record, role_item.get("predicate"), "semantic role predicate")
            if predicate_issue is not None:
                _error(errors, f"{location}.semantic_roles[{index}].predicate", predicate_issue)

    fusion_items = record.get("fusion_relations", [])
    if fusion_items is not None:
        if not isinstance(fusion_items, list):
            _error(errors, location, "fusion_relations must be an array")
        else:
            fusion_ids: set[str] = set()
            clause_ids = {
                clause.get("id") for clause in clause_items
                if isinstance(clause, dict) and isinstance(clause.get("id"), str)
            }
            for index, fusion in enumerate(fusion_items):
                fusion_location = f"{location}.fusion_relations[{index}]"
                if not isinstance(fusion, dict):
                    _error(errors, fusion_location, "fusion relation must be an object")
                    continue
                if isinstance(fusion.get("id"), str) and fusion.get("id") in fusion_ids:
                    _error(errors, fusion_location, "duplicate fusion relation id")
                if isinstance(fusion.get("id"), str):
                    fusion_ids.add(fusion.get("id"))
                for field in ("fused_element", "whole_constituent"):
                    if not isinstance(fusion.get(field), str) or fusion.get(field) not in all_ids:
                        _error(errors, fusion_location, f"{field} must reference a known ID")
                if isinstance(fusion.get("fused_element"), str) and fusion.get("fused_element") in all_ids:
                    _require_ref_kind(fusion.get("fused_element"), objects, {"word"}, f"{fusion_location}.fused_element", errors, "fusion.fused_element")
                if isinstance(fusion.get("whole_constituent"), str) and fusion.get("whole_constituent") in all_ids:
                    _require_ref_kind(fusion.get("whole_constituent"), objects, {"phrase", "clause"}, f"{fusion_location}.whole_constituent", errors, "fusion.whole_constituent")
                if not isinstance(fusion.get("relative_clause"), str) or fusion.get("relative_clause") not in clause_ids:
                    _error(errors, fusion_location, "relative_clause must reference a known clause")
                dependency = fusion.get("dependency")
                if dependency is not None and (not isinstance(dependency, dict) or not isinstance(dependency.get("head"), str) or dependency.get("head") not in all_ids or not isinstance(dependency.get("dependent"), str) or dependency.get("dependent") not in all_ids or not dependency.get("relation")):
                    _error(errors, fusion_location, "fusion dependency must reference known IDs")
                elif isinstance(dependency, dict):
                    if isinstance(dependency.get("head"), str) and dependency.get("head") in all_ids:
                        _require_ref_kind(dependency.get("head"), objects, {"word", "phrase", "clause"}, f"{fusion_location}.dependency.head", errors, "fusion dependency head")
                    if isinstance(dependency.get("dependent"), str) and dependency.get("dependent") in all_ids:
                        _require_ref_kind(dependency.get("dependent"), objects, {"word", "phrase", "clause"}, f"{fusion_location}.dependency.dependent", errors, "fusion dependency dependent")

    ambiguity = record.get("ambiguity")
    if ambiguity is not None:
        if not isinstance(ambiguity, dict) or not _known(ambiguity.get("status"), AMBIGUITY_STATUSES) or not isinstance(ambiguity.get("analyses"), list):
            _error(errors, location, "ambiguity requires a known status and analyses array")
        else:
            status = ambiguity["status"]
            ambiguity_analyses = ambiguity["analyses"]
            if status == "genuinely_ambiguous" and len(ambiguity_analyses) < 2:
                _error(errors, location, "genuinely_ambiguous requires at least two structural analyses")
            if status == "unambiguous" and len(ambiguity_analyses) != 1:
                _error(errors, location, "unambiguous records require exactly one analysis")
            preferred_id = ambiguity.get("preferred_analysis")
            ambiguity_ids = {
                item.get("id") for item in ambiguity_analyses
                if isinstance(item, dict) and isinstance(item.get("id"), str)
            }
            alternatives_by_id = {
                item.get("id"): item for item in alternatives
                if isinstance(item, dict) and isinstance(item.get("id"), str)
            }
            if len(ambiguity_ids) != len(ambiguity_analyses):
                _error(errors, f"{location}.ambiguity", "ambiguity analysis IDs must be unique and non-empty")
            if status == "multiple_established_analyses_with_preferred_reading" and (len(ambiguity_analyses) < 2 or not isinstance(preferred_id, str) or preferred_id not in ambiguity_ids):
                _error(errors, location, "multiple established analyses require two analyses and a preferred_analysis id")
            for index, item in enumerate(ambiguity_analyses):
                if not isinstance(item, dict) or not item.get("id") or not isinstance(item.get("structural_claims"), list) or any(not isinstance(claim, str) or not claim for claim in item.get("structural_claims", [])) or not item.get("interpretation"):
                    _error(errors, f"{location}.ambiguity.analyses[{index}]", "ambiguity analysis requires id, structural_claims, and interpretation")
                if isinstance(item, dict):
                    if not _linked_ids(item, AMBIGUITY_LINK_FIELDS):
                        _error(errors, f"{location}.ambiguity.analyses[{index}]", "ambiguity analysis must link an alternative or structured wrapper/constituent/clause/relation")
                    for field in AMBIGUITY_LINK_FIELDS:
                        values = item.get(field)
                        if values is None:
                            continue
                        if not isinstance(values, list) or any(not isinstance(value, str) or not value for value in values):
                            _error(errors, f"{location}.ambiguity.analyses[{index}].{field}", "ambiguity linkage must be a list of non-empty IDs")
                            continue
                        if field == "alternative_ids":
                            unknown = set(values) - alternative_ids
                        elif field == "wrapper_ids":
                            unknown = set(values) - wrapper_ids
                        elif field == "relation_ids":
                            unknown = set(values) - typed_relation_ids
                        elif field == "constituent_ids":
                            unknown = set(values) - ids
                        else:
                            unknown = set(values) - clause_ids
                        if unknown:
                            _error(errors, f"{location}.ambiguity.analyses[{index}].{field}", f"ambiguity linkage references unknown IDs: {sorted(unknown)}")
                        if field == "alternative_ids" and status == "multiple_established_analyses_with_preferred_reading":
                            non_established = {
                                alternative_id for alternative_id in values
                                if isinstance(alternatives_by_id.get(alternative_id), dict)
                                and alternatives_by_id[alternative_id].get("status") != "established"
                            }
                            if non_established:
                                _error(errors, f"{location}.ambiguity.analyses[{index}].alternative_ids", "multiple_established_analyses_with_preferred_reading requires established alternatives")
                if "attachment" in item and item.get("attachment") is not None:
                    attachment = item.get("attachment")
                    if not isinstance(attachment, str) or attachment not in all_ids:
                        _error(errors, f"{location}.ambiguity.analyses[{index}].attachment", "ambiguity attachment must reference a known ID")
                    else:
                        _require_ref_kind(attachment, objects, {"phrase", "clause"}, f"{location}.ambiguity.analyses[{index}].attachment", errors, "ambiguity attachment")
                for ref_field in ("target", "constituent", "clause"):
                    if ref_field in item and item[ref_field] is not None:
                        if not isinstance(item[ref_field], str) or item[ref_field] not in all_ids:
                            _error(errors, f"{location}.ambiguity.analyses[{index}].{ref_field}", "ambiguity reference must reference a known ID")

    signature = record.get("construction_signature")
    if signature is not None:
        if not isinstance(signature, dict) or not all(isinstance(signature.get(field), str) and signature[field] for field in ("predicate_lemma", "construction_type")) or not isinstance(signature.get("argument_pattern"), list) or not isinstance(signature.get("function_pattern"), list) or not signature["argument_pattern"] or not signature["function_pattern"]:
            _error(errors, location, "construction_signature requires predicate_lemma, construction_type, argument_pattern, and function_pattern")
        elif len(signature["argument_pattern"]) != len(signature["function_pattern"]):
            _error(errors, location, "construction_signature argument_pattern and function_pattern must have equal lengths")
        elif any(value in all_ids for value in signature["argument_pattern"] + signature["function_pattern"] if isinstance(value, str)):
            _error(errors, location, "construction_signature patterns must use stable descriptors, not record-local IDs")
        elif record.get("construction_type") is not None and record.get("construction_type") != signature["construction_type"]:
            _error(errors, location, "construction_signature construction_type must agree with construction_type")
        elif isinstance(record.get("lexical_valency"), list) and record["lexical_valency"]:
            signature_predicate_id = normalize_predicate_reference(record, signature["predicate_lemma"])
            valency_predicate_ids = {
                normalize_predicate_reference(record, item.get("predicate"))
                for item in record["lexical_valency"]
                if isinstance(item, dict)
            }
            if signature_predicate_id is None or signature_predicate_id not in valency_predicate_ids:
                _error(errors, location, "construction_signature predicate_lemma must agree with lexical_valency")

    if not isinstance(record["explanation"], str) or not record["explanation"].strip():
        _error(errors, location, "explanation must be non-empty")
    if not _known(record["split"], SPLITS):
        _error(errors, location, f"invalid split {record['split']!r}")
    diagnosis = record.get("error_diagnosis")
    if diagnosis is not None:
        if not isinstance(diagnosis, dict) or not diagnosis.get("student_analysis") or not isinstance(diagnosis.get("diagnoses"), list):
            _error(errors, location, "error_diagnosis requires student_analysis and diagnoses")
        else:
            for index, item in enumerate(diagnosis["diagnoses"]):
                if not isinstance(item, dict) or not _known(item.get("verdict"), {"error", "acceptable_alternative", "correct"}) or not _known(item.get("error_level"), ANALYSIS_LEVELS) or not item.get("claim") or not item.get("correct_analysis") or not item.get("why"):
                    _error(errors, f"{location}.error_diagnosis.diagnoses[{index}]", "malformed diagnosis")
    return errors


def _signature_key(record: dict[str, Any]) -> tuple[Any, ...] | None:
    signature = construction_signature(record)
    if not isinstance(signature, dict):
        return None
    if not isinstance(signature.get("argument_pattern"), list) or not isinstance(signature.get("function_pattern"), list):
        return None
    if not isinstance(signature.get("predicate_lemma"), str) or not isinstance(signature.get("construction_type"), str):
        return None
    if not all(isinstance(value, str) for value in signature.get("argument_pattern", []) + signature.get("function_pattern", [])):
        return None
    return (
        signature.get("predicate_lemma"), signature.get("construction_type"),
        tuple(signature.get("argument_pattern", [])), tuple(signature.get("function_pattern", [])),
    )


def validate_files(paths: list[Path], benchmark_path: Path | None = None, schema_path: Path | None = None) -> list[str]:
    errors: list[str] = []
    all_records: list[tuple[Path, int, dict[str, Any]]] = []
    for requested_path in paths:
        if not requested_path.exists():
            errors.append(f"{requested_path}: input path does not exist")
    for path in iter_jsonl_paths(paths):
        try:
            rows = read_jsonl(path)
        except ValueError as error:
            errors.append(str(error))
            continue
        for line_number, record in rows:
            all_records.append((path, line_number, record))
            errors.extend(validate_record(record, f"{path}:{line_number}", schema_path))
    seen_ids: dict[str, str] = {}
    seen_sentences: dict[str, str] = {}
    for path, line_number, record in all_records:
        location = f"{path}:{line_number}"
        identifier = record.get("id")
        if isinstance(identifier, str) and identifier in seen_ids:
            errors.append(f"{location}: duplicate id {identifier!r}; first seen at {seen_ids[identifier]}")
        elif isinstance(identifier, str):
            seen_ids[identifier] = location
        sentence = record.get("sentence")
        if isinstance(sentence, str):
            key = normalized_text(sentence)
            if key in seen_sentences:
                errors.append(f"{location}: duplicate normalized sentence; first seen at {seen_sentences[key]}")
            else:
                seen_sentences[key] = location
    if benchmark_path and not benchmark_path.exists():
        errors.append(f"{benchmark_path}: benchmark path does not exist")
    elif benchmark_path and benchmark_path.exists():
        try:
            benchmark_rows = read_jsonl(benchmark_path)
        except ValueError as error:
            errors.append(str(error))
            benchmark_rows = []
        for benchmark_line, benchmark_record in benchmark_rows:
            errors.extend(validate_record(benchmark_record, f"{benchmark_path}:{benchmark_line}", schema_path))
            metadata = benchmark_record.get("review_metadata")
            if not isinstance(metadata, dict):
                errors.append(f"{benchmark_path}:{benchmark_line} record {benchmark_record.get('id')!r}: benchmark records require review_metadata")
            elif metadata.get("review_status") in {"approved_for_training", "canonical_gold"}:
                errors.append(f"{benchmark_path}:{benchmark_line} record {benchmark_record.get('id')!r}: benchmark records are evaluation-only and cannot claim training approval")
        benchmark_seen_ids: dict[str, int] = {}
        benchmark_seen_sentences: dict[str, int] = {}
        for benchmark_line, benchmark_record in benchmark_rows:
            benchmark_id = benchmark_record.get("id")
            if isinstance(benchmark_id, str) and benchmark_id in benchmark_seen_ids:
                errors.append(f"{benchmark_path}:{benchmark_line}: duplicate benchmark id {benchmark_id!r}; first seen at line {benchmark_seen_ids[benchmark_id]}")
            elif isinstance(benchmark_id, str):
                benchmark_seen_ids[benchmark_id] = benchmark_line
            benchmark_sentence = benchmark_record.get("sentence")
            if isinstance(benchmark_sentence, str):
                benchmark_sentence_key = normalized_text(benchmark_sentence)
                if benchmark_sentence_key in benchmark_seen_sentences:
                    errors.append(f"{benchmark_path}:{benchmark_line}: duplicate benchmark normalized sentence; first seen at line {benchmark_seen_sentences[benchmark_sentence_key]}")
                else:
                    benchmark_seen_sentences[benchmark_sentence_key] = benchmark_line
        benchmark_ids = {row.get("id") for _, row in benchmark_rows if isinstance(row.get("id"), str)}
        benchmark_sentences = {normalized_text(row.get("sentence", "")) for _, row in benchmark_rows if isinstance(row.get("sentence"), str)}
        benchmark_signatures = {_signature_key(row): (line, row.get("id")) for line, row in benchmark_rows if _signature_key(row) is not None}
        for benchmark_line, benchmark_record in benchmark_rows:
            if benchmark_record.get("split") != "benchmark":
                errors.append(f"{benchmark_path}:{benchmark_line}: benchmark records must use split='benchmark'")
        for path, line_number, record in all_records:
            record_split = record.get("split")
            if isinstance(record_split, str) and record_split in {"train", "validation"} and isinstance(record.get("id"), str) and record.get("id") in benchmark_ids:
                errors.append(f"{path}:{line_number}: benchmark id leaks into {record.get('split')}")
            if isinstance(record_split, str) and record_split in {"train", "validation"} and record.get("source_type") == "legacy_baseline":
                errors.append(f"{path}:{line_number}: legacy_baseline is benchmark-only")
            candidate_sentence = sentence_from_record(record) or ""
            if isinstance(record_split, str) and record_split in {"train", "validation"} and normalized_text(candidate_sentence) in benchmark_sentences:
                errors.append(f"{path}:{line_number}: benchmark sentence leaks into {record.get('split')}")
            key = _signature_key(record)
            if isinstance(record_split, str) and record_split in {"train", "validation"} and key in benchmark_signatures and normalized_text(candidate_sentence) not in benchmark_sentences:
                benchmark_line, benchmark_id = benchmark_signatures[key]
                errors.append(f"{path}:{line_number}: construction signature matches benchmark {benchmark_id} (line {benchmark_line})")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path, help="JSONL files or directories")
    parser.add_argument("--benchmark", type=Path, default=Path("eval/benchmark_v1.jsonl"))
    parser.add_argument("--no-benchmark", action="store_true", help="skip held-out benchmark validation")
    parser.add_argument("--schema", type=Path, default=Path("schemas/gold_annotation.schema.json"), help="JSON Schema document to require alongside semantic checks")
    parser.add_argument("--expected-split", choices=tuple(SPLITS), help="require every canonical input record to use this split")
    arguments = parser.parse_args()
    try:
        with arguments.schema.open(encoding="utf-8") as schema_handle:
            schema_document = json.load(schema_handle)
        if schema_document.get("$id") != "https://english-syntax-tutor.local/schema/gold-annotation-0.4.json":
            raise ValueError("unexpected gold schema $id")
    except (OSError, json.JSONDecodeError, ValueError, AttributeError) as error:
        print(f"Schema check failed: {error}", file=sys.stderr)
        return 1
    paths = arguments.paths or [Path("data/gold"), Path("data/reviewed")]
    benchmark_path = None if arguments.no_benchmark else arguments.benchmark
    errors = validate_files(paths, benchmark_path, arguments.schema)
    if arguments.expected_split:
        for path in iter_jsonl_paths(paths):
            try:
                rows = read_jsonl(path)
            except ValueError:
                continue
            for line_number, record in rows:
                if "schema_version" in record and record.get("split") != arguments.expected_split:
                    errors.append(f"{path}:{line_number}: expected split {arguments.expected_split!r}, got {record.get('split')!r}")
    if errors:
        print("Dataset validation failed:", file=sys.stderr)
        print("\n".join(f"- {error}" for error in errors), file=sys.stderr)
        return 1
    print(f"Dataset validation passed ({len(iter_jsonl_paths(paths))} file(s)).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
