#!/usr/bin/env python3
"""Render V0.4 canonical annotations into chat SFT JSONL."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

try:
    from data_common import read_jsonl
except ImportError:
    from scripts.data_common import read_jsonl


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
    "word": {"node_kind", "id", "form", "lemma", "lexical_category", "syntactic_function", "external_pos_tags", "morphology", "lexical_analysis"},
    "morphology": {"tense", "aspect", "mood", "number", "person", "form", "voice", "degree", "case", "features"},
    "lexical_analysis": {"candidates", "note"},
    "lexical_candidate": {"category", "lexical_category", "category_namespace", "framework", "syntactic_function", "claim"},
    "typed_analysis": {"kind", "framework", "arguments", "entities", "relations", "notes"},
    "typed_entity": {"id", "kind"},
    "typed_reference": {"namespace", "id"},
    "typed_arguments": {"id", "kind", "type", "target", "source", "head", "dependent", "relation", "role", "category", "function", "span", "clause_ref", "constituent_ref", "word_ref", "predicate", "value", "label"},
    "typed_relation": {"id", "kind", "type", "arity", "target", "source", "namespace", "framework", "status", "note"},
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
    "dependencies": "dependencies", "semantic_roles": "semantic_roles", "lexical_valency": "lexical_valency",
    "clause_ontology": "clauses", "clause_structure": "clauses", "phrase_constituency": "constituents",
    "constituency": "constituents", "np_internal_constituency": "constituents", "syntactic_function": "constituents",
    "vp_complementation": "constituents", "construction_relations": "construction_signature", "framework_mapping": "framework",
}
GOVERNANCE_FIELDS = {
    "schema_version", "id", "split", "source_type", "difficulty", "capability_tags", "annotation_scope",
    "review_metadata", "migration_metadata", "migration_review_required", "migration_note", "provenance",
    "legacy_preferred_analysis", "legacy_annotation_scope", "legacy_annotations",
}
LEGACY_NESTED_FIELDS = {"legacy_function", "legacy_clause_category", "legacy_pos", "status", "review_required"}
RENDERING_MODES = {"default", "learner_facing"}


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
            status_is_linguistic = key == "status" and context == "ambiguity"
            id_is_linguistic = key == "id" and context in {"word", "clause", "constituent", "ambiguity_analysis", "alternative_analysis", "typed_relation", "typed_entity"}
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


def _omitted_dimensions(record: dict[str, Any]) -> set[str]:
    scope = record.get("annotation_scope")
    omitted: set[str] = set()
    if not isinstance(scope, dict):
        return omitted
    declared = set()
    for entry in scope.get("dimensions", []):
        if not isinstance(entry, dict):
            continue
        dimension = str(entry.get("dimension"))
        declared.add(dimension)
        if (entry.get("omission") in {"intentional", "not_applicable"} or entry.get("completeness") in {"unannotated", "omitted", "out_of_scope"}) and entry.get("scope", {}).get("kind") == "record":
            omitted.add(dimension)
    declared_fields = {DIMENSION_FIELDS.get(dimension) for dimension in declared}
    omitted.update(
        dimension for dimension, field in DIMENSION_FIELDS.items()
        if dimension not in declared and field not in declared_fields
    )
    return omitted


def _apply_partial_scopes(record: dict[str, Any], projection: dict[str, Any]) -> None:
    scope = record.get("annotation_scope")
    if not isinstance(scope, dict):
        return
    for entry in scope.get("dimensions", []):
        if not isinstance(entry, dict) or entry.get("omission") != "none" or entry.get("completeness") != "partial":
            continue
        coverage_scope = entry.get("scope")
        field = DIMENSION_FIELDS.get(entry.get("dimension"))
        if field not in projection or not isinstance(coverage_scope, dict) or coverage_scope.get("kind") == "record":
            continue
        values = projection[field]
        if not isinstance(values, list):
            continue
        node_id = coverage_scope.get("node") if coverage_scope.get("kind") == "node" else None
        start = coverage_scope.get("start") if coverage_scope.get("kind") == "region" else None
        end = coverage_scope.get("end") if coverage_scope.get("kind") == "region" else None
        allowed_ids = {node_id} if isinstance(node_id, str) else set()
        objects = {item.get("id"): item for key in ("words", "clauses", "constituents") for item in record.get(key, []) if isinstance(item, dict) and isinstance(item.get("id"), str)}
        if node_id in objects and isinstance(objects[node_id].get("span"), dict):
            span = objects[node_id]["span"]
            start, end = span.get("start"), span.get("end")
        def covered(item: Any) -> bool:
            if not isinstance(item, dict):
                return False
            if item.get("id") in allowed_ids:
                return True
            span = item.get("span")
            return isinstance(start, int) and isinstance(end, int) and isinstance(span, dict) and isinstance(span.get("start"), int) and isinstance(span.get("end"), int) and start <= span["start"] and span["end"] <= end
        if field == "dependencies":
            if not allowed_ids and isinstance(start, int) and isinstance(end, int):
                allowed_ids = {
                    identifier for identifier, object_item in objects.items()
                    if isinstance(object_item.get("span"), dict)
                    and isinstance(object_item["span"].get("start"), int)
                    and isinstance(object_item["span"].get("end"), int)
                    and start <= object_item["span"]["start"]
                    and object_item["span"]["end"] <= end
                }
            projection[field] = [item for item in values if isinstance(item, dict) and (item.get("head") in allowed_ids or item.get("dependent") in allowed_ids)]
        else:
            projection[field] = [item for item in values if covered(item)]


def linguistic_projection(record: dict[str, Any], *, include_governance: bool = False, rendering_mode: str = "default") -> dict[str, Any]:
    """Return only explicitly allowed linguistic fields, honoring coverage."""
    if rendering_mode not in RENDERING_MODES:
        raise ValueError(f"unknown rendering mode {rendering_mode!r}; expected one of {sorted(RENDERING_MODES)}")
    if include_governance:
        return copy.deepcopy(record)
    projection = {key: _without_governance(record[key], key, rendering_mode=rendering_mode) for key in LINGUISTIC_FIELDS if key in record}
    _apply_partial_scopes(record, projection)
    for dimension in _omitted_dimensions(record):
        field = DIMENSION_FIELDS.get(dimension)
        if field and field in projection:
            del projection[field]
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
