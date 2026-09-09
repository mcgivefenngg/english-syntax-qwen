"""Canonical record-level consistency contract.

This module exposes pure, machine-readable record-global consistency issues
that the validator, authoritative payload, and renderer all consume. It does
not perform linguistic inference; it only detects structural contradictions
within a single canonical record.

B04 invariants:
- B04-A: duplicate canonical clause wrappers (same clause_ref/context/layer)
- B04-B: multiple root clauses
- B04-C: sentence_type / root-construction contradiction
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

try:
    from data_common import CLAUSE_CONSTRUCTIONS
except ImportError:
    from scripts.data_common import CLAUSE_CONSTRUCTIONS


ALTERNATIVE_LINK_FIELDS = {
    "linked_wrapper_ids", "linked_constituent_ids", "linked_clause_refs", "linked_relation_ids",
}
AMBIGUITY_LINK_FIELDS = {
    "alternative_ids", "wrapper_ids", "relation_ids", "constituent_ids", "clause_refs",
}


@dataclass(frozen=True)
class CanonicalConsistencyIssue:
    """One record-global canonical consistency violation."""

    code: str
    message: str
    affected_dimensions: frozenset[str]
    affected_targets: frozenset[str]
    record_level: bool = False


def _typed_reference_identifier(reference: Any) -> str | None:
    if isinstance(reference, dict) and isinstance(reference.get("id"), str):
        return reference["id"]
    if isinstance(reference, str) and ":" in reference:
        _, identifier = reference.split(":", 1)
        return identifier or None
    return None


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


def _wrapper_authority(record: dict[str, Any], wrappers: list[dict[str, Any]]) -> bool:
    """Check whether duplicate wrappers are authorized by ambiguity/alternative."""
    relevant_wrapper_ids = {
        wrapper.get("id") for wrapper in wrappers
        if isinstance(wrapper.get("id"), str)
    }
    relevant_clause_refs = {
        wrapper.get("clause_ref") for wrapper in wrappers
        if isinstance(wrapper.get("clause_ref"), str)
    }
    alternative_values = record.get("alternative_analyses", [])
    if not isinstance(alternative_values, list):
        alternative_values = []
    alternatives_by_id = {
        item.get("id"): item for item in alternative_values
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    relation_nodes: dict[str, set[str]] = {}
    analyses_for_relations = []
    for field in ("canonical_analysis", "preferred_analysis"):
        if isinstance(record.get(field), dict):
            analyses_for_relations.append(record[field])
    analyses_for_relations.extend(value for value in alternatives_by_id.values())
    for analysis in analyses_for_relations:
        typed = analysis.get("typed_analysis") if isinstance(analysis, dict) else None
        for relation in typed.get("relations", []) if isinstance(typed, dict) and isinstance(typed.get("relations"), list) else []:
            if not isinstance(relation, dict) or not isinstance(relation.get("id"), str):
                continue
            nodes = {
                identifier for identifier in (
                    _typed_reference_identifier(relation.get("source")),
                    _typed_reference_identifier(relation.get("target")),
                ) if isinstance(identifier, str)
            }
            relation_nodes[relation["id"]] = nodes

    established_nodes: set[str] = set()
    established_relation_nodes: set[str] = set()

    def string_ids(values: Any) -> set[str]:
        if not isinstance(values, list):
            return set()
        return {value for value in values if isinstance(value, str)}

    def linked_relation_nodes(relation_ids: Any) -> set[str]:
        nodes: set[str] = set()
        for relation_id in string_ids(relation_ids):
            nodes.update(relation_nodes.get(relation_id, set()))
        return nodes

    for alternative in alternatives_by_id.values():
        if alternative.get("status") != "established":
            continue
        linked_relation_ids = string_ids(alternative.get("linked_relation_ids"))
        established_nodes.update(_linked_ids(alternative, ALTERNATIVE_LINK_FIELDS) - linked_relation_ids)
        established_relation_nodes.update(linked_relation_nodes(alternative.get("linked_relation_ids")))
    ambiguity = record.get("ambiguity")
    relevant_ambiguity_analyses = 0
    ambiguity_nodes: set[str] = set()
    ambiguity_relation_nodes: set[str] = set()
    if (
        isinstance(ambiguity, dict)
        and ambiguity.get("status") in {"genuinely_ambiguous", "multiple_established_analyses_with_preferred_reading"}
        and isinstance(ambiguity.get("analyses"), list)
    ):
        for analysis in ambiguity["analyses"]:
            if not isinstance(analysis, dict):
                continue
            relation_ids = string_ids(analysis.get("relation_ids"))
            alternative_ids = analysis.get("alternative_ids")
            alternative_id_values = string_ids(alternative_ids)
            analysis_nodes = _linked_ids(analysis, AMBIGUITY_LINK_FIELDS) - relation_ids - alternative_id_values
            analysis_relation_nodes: set[str] = set()
            for relation_id in relation_ids:
                if isinstance(relation_id, str):
                    analysis_relation_nodes.update(relation_nodes.get(relation_id, set()))
            if isinstance(alternative_ids, list):
                for alternative_id in alternative_ids:
                    alternative = alternatives_by_id.get(alternative_id)
                    if not isinstance(alternative, dict) or alternative.get("status") != "established":
                        continue
                    linked_relation_ids = string_ids(alternative.get("linked_relation_ids"))
                    analysis_nodes.update(_linked_ids(alternative, ALTERNATIVE_LINK_FIELDS) - linked_relation_ids)
                    for relation_id in linked_relation_ids:
                        if isinstance(relation_id, str):
                            analysis_relation_nodes.update(relation_nodes.get(relation_id, set()))
            if (
                bool(relevant_clause_refs & analysis_nodes)
                or bool(relevant_wrapper_ids & analysis_nodes)
                or bool(relevant_clause_refs & analysis_relation_nodes)
                or bool(relevant_wrapper_ids & analysis_relation_nodes)
            ):
                relevant_ambiguity_analyses += 1
            ambiguity_nodes.update(analysis_nodes)
            ambiguity_relation_nodes.update(analysis_relation_nodes)
    ambiguity_authorizes = relevant_ambiguity_analyses >= 2 and (
        bool(relevant_clause_refs & ambiguity_nodes)
        or relevant_wrapper_ids.issubset(ambiguity_nodes)
        or bool(relevant_clause_refs & ambiguity_relation_nodes)
        or relevant_wrapper_ids.issubset(ambiguity_relation_nodes)
    )
    established_alternative_authorizes = (
        bool(relevant_clause_refs & established_nodes)
        or relevant_wrapper_ids.issubset(established_nodes)
        or bool(relevant_clause_refs & established_relation_nodes)
        or relevant_wrapper_ids.issubset(established_relation_nodes)
    )
    return established_alternative_authorizes or ambiguity_authorizes


def _duplicate_wrapper_issues(record: dict[str, Any]) -> list[CanonicalConsistencyIssue]:
    """B04-A: Detect duplicate canonical clause wrappers."""
    if record.get("schema_version") != "0.4":
        return []
    constituents = record.get("constituents")
    if not isinstance(constituents, list):
        return []
    realization_groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for constituent in constituents:
        if not isinstance(constituent, dict) or constituent.get("node_kind") != "clause":
            continue
        clause_ref = constituent.get("clause_ref")
        span = constituent.get("span")
        if isinstance(clause_ref, str) and isinstance(span, dict) and isinstance(span.get("start"), int) and isinstance(span.get("end"), int):
            realization = constituent.get("realization") if isinstance(constituent.get("realization"), dict) else {}
            context = realization.get("context") if isinstance(realization.get("context"), str) else ""
            layer = realization.get("layer") if isinstance(realization.get("layer"), str) else ""
            realization_groups.setdefault((clause_ref, context, layer), []).append(constituent)

    issues: list[CanonicalConsistencyIssue] = []
    for key, wrappers in realization_groups.items():
        if len(wrappers) <= 1 or _wrapper_authority(record, wrappers):
            continue
        wrapper_ids = frozenset(
            wrapper.get("id") for wrapper in wrappers
            if isinstance(wrapper.get("id"), str)
        )
        spans = {
            (wrapper.get("span", {}).get("start"), wrapper.get("span", {}).get("end"))
            for wrapper in wrappers if isinstance(wrapper.get("span"), dict)
        }
        functions = {wrapper.get("function") for wrapper in wrappers}
        if len(spans) > 1:
            message = f"clause realization {key!r} has incompatible unlinked multi-span wrappers"
        elif len(functions) > 1:
            message = f"clause realization {key!r} has conflicting canonical wrapper functions; link an explicit ambiguity or established alternative"
        else:
            message = f"clause realization {key!r} has duplicate canonical wrappers"
        issues.append(CanonicalConsistencyIssue(
            code="duplicate_clause_wrapper",
            message=message,
            affected_dimensions=frozenset({"phrase_constituency", "constituency", "syntactic_function", "vp_complementation"}),
            affected_targets=wrapper_ids,
            record_level=False,
        ))
    return issues


def _multiple_root_issues(record: dict[str, Any]) -> list[CanonicalConsistencyIssue]:
    """B04-B: Detect multiple root clauses."""
    if record.get("schema_version") != "0.4":
        return []
    clauses = record.get("clauses")
    if not isinstance(clauses, list):
        return []
    root_clauses = [
        item for item in clauses
        if isinstance(item, dict) and isinstance(item.get("integration"), list) and "root" in item.get("integration", [])
    ]
    if len(root_clauses) != 1:
        root_ids = frozenset(
            clause.get("id") for clause in root_clauses
            if isinstance(clause.get("id"), str)
        )
        return [CanonicalConsistencyIssue(
            code="multiple_root_clauses",
            message="V0.4 records must contain exactly one root clause",
            affected_dimensions=frozenset({"clause_structure", "clause_ontology"}),
            affected_targets=root_ids,
            record_level=True,
        )]
    return []


def _sentence_type_contradiction_issues(record: dict[str, Any]) -> list[CanonicalConsistencyIssue]:
    """B04-C: Detect sentence_type / root-construction contradiction."""
    if record.get("schema_version") != "0.4":
        return []
    clauses = record.get("clauses")
    if not isinstance(clauses, list):
        return []
    root_clauses = [
        item for item in clauses
        if isinstance(item, dict) and isinstance(item.get("integration"), list) and "root" in item.get("integration", [])
    ]
    if len(root_clauses) != 1:
        return []
    root_construction = root_clauses[0].get("clause_construction")
    sentence_type = record.get("sentence_type")
    if root_construction in {"declarative", "interrogative", "exclamative"} and sentence_type != root_construction:
        root_id = root_clauses[0].get("id")
        targets = frozenset({root_id}) if isinstance(root_id, str) else frozenset()
        return [CanonicalConsistencyIssue(
            code="sentence_type_root_construction_contradiction",
            message="sentence_type is derived from the root clause and cannot contradict its construction",
            affected_dimensions=frozenset({"clause_structure", "clause_ontology"}),
            affected_targets=targets,
            record_level=True,
        )]
    return []


def canonical_record_consistency_issues(record: dict[str, Any]) -> tuple[CanonicalConsistencyIssue, ...]:
    """Return all record-global canonical consistency issues.

    This is the single source of truth for B04 invariants. The validator,
    authoritative payload, and renderer all consume this helper.
    """
    if not isinstance(record, dict):
        return ()
    issues: list[CanonicalConsistencyIssue] = []
    issues.extend(_duplicate_wrapper_issues(record))
    issues.extend(_multiple_root_issues(record))
    issues.extend(_sentence_type_contradiction_issues(record))
    return tuple(issues)


def consistency_issue_codes(record: dict[str, Any]) -> frozenset[str]:
    """Return the set of issue codes present in a record."""
    return frozenset(issue.code for issue in canonical_record_consistency_issues(record))


def targets_in_consistency_conflict(record: dict[str, Any]) -> frozenset[str]:
    """Return all target IDs participating in any consistency conflict."""
    targets: set[str] = set()
    for issue in canonical_record_consistency_issues(record):
        targets.update(issue.affected_targets)
    return frozenset(targets)


def dimensions_affected_by_consistency_issues(record: dict[str, Any]) -> frozenset[str]:
    """Return all dimensions implicated by any consistency conflict."""
    dimensions: set[str] = set()
    for issue in canonical_record_consistency_issues(record):
        dimensions.update(issue.affected_dimensions)
    return frozenset(dimensions)
