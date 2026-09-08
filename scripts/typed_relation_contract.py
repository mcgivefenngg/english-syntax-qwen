"""Typed relation structural contract for V0.4 authoritative payload.

This module provides pure validation functions for typed relations that can be
shared by the authoritative payload collector and renderer without creating
import cycles with the full validator.
"""
from __future__ import annotations

from typing import Any

try:
    from data_common import FRAMEWORKS
except ImportError:
    from scripts.data_common import FRAMEWORKS


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

TYPED_REFERENCE_NAMESPACES = {"word", "constituent", "clause", "analysis"}


def parse_typed_reference(reference: Any) -> tuple[str, str] | None:
    """Parse a typed reference into (namespace, id) or None if invalid."""
    if isinstance(reference, str) and ":" in reference:
        namespace, identifier = reference.split(":", 1)
        if namespace and identifier:
            return namespace, identifier
    elif isinstance(reference, dict):
        namespace = reference.get("namespace")
        identifier = reference.get("id")
        if isinstance(namespace, str) and isinstance(identifier, str) and identifier:
            return namespace, identifier
    return None


def typed_reference_identifier(reference: Any) -> str | None:
    """Extract the ID portion of a typed reference."""
    parsed = parse_typed_reference(reference)
    return parsed[1] if parsed else None


def validate_typed_relation_structure(
    relation: dict[str, Any],
    typed_analysis: dict[str, Any],
    record: dict[str, Any],
    *,
    analysis_entity_ids: set[str] | None = None,
) -> str:
    """Validate typed relation structural integrity.
    
    Returns:
        "resolved" - structurally valid
        "unresolved" - structurally valid but with unresolved authority
        "missing" - structurally invalid
    
    This validates:
    - Relation identity (id, type)
    - Arity contract (unary/binary)
    - Reference integrity (source, target)
    - Framework/attribution rules
    - Canonical scalar duplicate detection
    - Extension relation qualification
    """
    if not isinstance(relation, dict):
        return "missing"
    
    # Check relation identity
    relation_id = relation.get("id")
    if not isinstance(relation_id, str) or not relation_id:
        return "missing"
    
    relation_type = relation.get("type")
    if not isinstance(relation_type, str) or not relation_type:
        return "missing"
    
    # Check canonical scalar duplicate
    if relation_type in CANONICAL_SCALAR_RELATION_TYPES:
        return "missing"
    
    # Check arity
    arity = relation.get("arity")
    has_target_field = "target" in relation
    has_target = has_target_field and relation.get("target") is not None
    
    if arity is None:
        return "missing"
    if arity not in {"unary", "binary"}:
        return "missing"
    
    # Binary relations require target
    if arity == "binary" and not has_target:
        return "missing"
    
    # Unary relations cannot carry target
    if arity == "unary" and has_target_field:
        return "missing"
    
    # Core binary types require target
    if relation_type in BINARY_TYPED_RELATION_TYPES and not has_target:
        return "missing"
    
    # Check framework attribution
    framework = relation.get("framework")
    if framework is not None and framework not in FRAMEWORKS:
        return "missing"
    
    # framework_relation requires framework or namespace
    if relation_type == "framework_relation":
        namespace = relation.get("namespace")
        has_namespace = isinstance(namespace, str) and bool(namespace)
        has_framework = framework in FRAMEWORKS
        if not has_framework and not has_namespace:
            return "missing"
    
    # Check extension relation qualification
    if relation_type not in CORE_TYPED_RELATION_TYPES and relation_type not in CANONICAL_SCALAR_RELATION_TYPES:
        qualified_type = ":" in relation_type or "/" in relation_type
        namespace = relation.get("namespace")
        qualified_metadata = isinstance(namespace, str) and bool(namespace)
        qualified_metadata = qualified_metadata or (framework in FRAMEWORKS)
        if not qualified_type and not qualified_metadata:
            return "missing"
    
    # Validate source reference
    source = relation.get("source")
    if not _validate_typed_reference(source, record, analysis_entity_ids):
        return "missing"
    
    # Validate target reference if present
    if has_target:
        target = relation.get("target")
        if not _validate_typed_reference(target, record, analysis_entity_ids):
            return "missing"
    
    # Check status
    status = relation.get("status", typed_analysis.get("status"))
    if status in {"descriptive", "established"}:
        return "resolved"
    if status in {"unresolved", "review_required"}:
        return "unresolved"
    
    return "missing"


def _validate_typed_reference(
    reference: Any,
    record: dict[str, Any],
    analysis_entity_ids: set[str] | None,
) -> bool:
    """Validate a typed reference exists in the appropriate collection."""
    parsed = parse_typed_reference(reference)
    if parsed is None:
        return False
    
    namespace, identifier = parsed
    if namespace not in TYPED_REFERENCE_NAMESPACES:
        return False
    
    if not identifier:
        return False
    
    # Analysis-local references
    if namespace == "analysis":
        if analysis_entity_ids is None:
            return False
        return identifier in analysis_entity_ids
    
    # Canonical collection references
    collection_map = {
        "word": "words",
        "constituent": "constituents",
        "clause": "clauses",
    }
    
    collection_name = collection_map.get(namespace)
    if collection_name is None:
        return False
    
    collection = record.get(collection_name)
    if not isinstance(collection, list):
        return False
    
    for item in collection:
        if isinstance(item, dict) and item.get("id") == identifier:
            return True
    
    return False


def get_analysis_entity_ids(typed_analysis: dict[str, Any]) -> set[str]:
    """Extract entity IDs from a typed analysis for local reference validation."""
    if not isinstance(typed_analysis, dict):
        return set()
    
    entities = typed_analysis.get("entities")
    if not isinstance(entities, list):
        return set()
    
    return {
        entity.get("id")
        for entity in entities
        if isinstance(entity, dict) and isinstance(entity.get("id"), str) and entity["id"]
    }


def validate_typed_analysis_container(typed_analysis: dict[str, Any]) -> bool:
    """Validate typed analysis container has minimum required fields.
    
    Returns True if the container is structurally valid for interpreting
    nested relation/entity authority.
    """
    if not isinstance(typed_analysis, dict):
        return False
    
    kind = typed_analysis.get("kind")
    if not isinstance(kind, str) or not kind:
        return False
    
    framework = typed_analysis.get("framework")
    if framework not in FRAMEWORKS:
        return False
    
    status = typed_analysis.get("status")
    if status not in {"descriptive", "established", "unresolved", "review_required"}:
        return False
    
    return True
