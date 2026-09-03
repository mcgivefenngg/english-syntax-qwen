#!/usr/bin/env python3
"""Deterministic migration from the real V0.2 wire contract to V0.4.

The release tag ``v0.2.1`` is provenance only: records in that release carry
``schema_version: "0.2"``. V0.4 input is an exact no-op; every other source
version is rejected instead of being guessed.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


SOURCE_SCHEMA_VERSION = "0.2"
TARGET_SCHEMA_VERSION = "0.4"
MIGRATION_VERSION = "0.4.0"


def _ensure_review_metadata(record: dict[str, Any], *, required: bool = False) -> None:
    metadata = record.get("review_metadata")
    if not isinstance(metadata, dict):
        record["review_metadata"] = {
            "review_status": "review_required" if required else "schema_migrated",
            "reviewer_type": "automated_structural",
            "migration_version": MIGRATION_VERSION,
            "provenance": "v0.2 to v0.4 deterministic schema migration",
        }
        return
    metadata.setdefault("migration_version", MIGRATION_VERSION)


def _mark_review_required(record: dict[str, Any], note: str) -> None:
    _ensure_review_metadata(record, required=True)
    metadata = record.get("review_metadata")
    if isinstance(metadata, dict) and metadata.get("review_status") not in {"linguistically_reviewed", "approved_for_training", "canonical_gold"}:
        metadata["review_status"] = "review_required"
    record["migration_review_required"] = True
    record["migration_note"] = note


def _map_clause_category(clause: dict[str, Any]) -> bool:
    """Map only explicit legacy category labels; no surface/geometry inference."""
    review_required = False
    category = clause.pop("clause_category", None)
    if category is None:
        category = clause.pop("category", None)
    if category is not None:
        clause["legacy_clause_category"] = category
    direct = {"relative_clause": "relative", "interrogative_clause": "interrogative", "comparative_clause": "comparative"}
    if clause.get("clause_construction") is None:
        clause["clause_construction"] = direct.get(category, "unresolved")
    elif category in direct and clause["clause_construction"] != direct[category]:
        review_required = True
    if clause.get("integration") is None:
        clause["integration"] = ["root" if category == "main_clause" else "unresolved"]
    if category == "supplementary_clause" and clause["integration"] == ["unresolved"]:
        clause["integration"] = ["supplementary"]
    return review_required


def _migrate_clause(clause: dict[str, Any]) -> bool:
    review_required = _map_clause_category(clause)
    clause.setdefault("node_kind", "clause")
    if clause.get("finiteness") is None:
        clause["finiteness"] = "unspecified"
        review_required = True
    if clause.get("finiteness") == "non-finite":
        clause["finiteness"] = "nonfinite"
    if clause.get("finiteness") == "nonfinite" and "clause_form" not in clause:
        clause["clause_form"] = "unspecified"
        review_required = True
    if "function" in clause:
        clause["legacy_function"] = clause.pop("function")
        review_required = True
    return review_required


def _migrate_word(word: dict[str, Any]) -> bool:
    """Move a tagged legacy POS value to the independent external POS layer."""
    if "pos" not in word:
        return False
    legacy_pos = word.pop("pos", None)
    tagset = word.pop("pos_tagset", None)
    mapped = {"tagset": tagset, "tag": legacy_pos} if isinstance(tagset, str) and tagset and isinstance(legacy_pos, str) and legacy_pos else None
    external = word.get("external_pos_tags")
    if mapped is not None and (external is None or external == []):
        word["external_pos_tags"] = [mapped]
        word.pop("pos_tagset", None)
        return False
    if mapped is not None and isinstance(external, list) and mapped in external:
        return False
    if legacy_pos is not None:
        word["legacy_pos"] = legacy_pos
    return True


def _migrate_constituent(constituent: dict[str, Any], clauses: dict[str, dict[str, Any]]) -> bool:
    """Create a realization only where the relation is structurally unique."""
    clause_ref = constituent.get("clause_ref")
    if constituent.get("node_kind") is None and isinstance(clause_ref, str):
        constituent["node_kind"] = "clause"
    if constituent.get("node_kind") != "clause" or not isinstance(clause_ref, str) or isinstance(constituent.get("realization"), dict):
        return False
    clause = clauses.get(clause_ref)
    wrapper_span = constituent.get("span")
    clause_span = clause.get("span") if isinstance(clause, dict) else None
    relation = "other"
    review_required = True
    if isinstance(wrapper_span, dict) and isinstance(clause_span, dict):
        if wrapper_span == clause_span:
            relation, review_required = "same_span_alias", False
        elif all(isinstance(span.get(key), int) for span in (wrapper_span, clause_span) for key in ("start", "end")) and wrapper_span["start"] <= clause_span["start"] and wrapper_span["end"] >= clause_span["end"]:
            relation, review_required = "expanded_realization", False
    constituent["realization"] = {"clause_ref": clause_ref, "relation": relation}
    return review_required


def _migrate_scope(record: dict[str, Any]) -> None:
    old_scope = record.get("annotation_scope")
    if isinstance(old_scope, dict) and isinstance(old_scope.get("dimensions"), list) and old_scope["dimensions"]:
        for entry in old_scope["dimensions"]:
            if isinstance(entry, dict) and entry.get("omission") in {"intentional", "not_applicable"}:
                entry["evidence"] = "unannotated"
            elif isinstance(entry, dict) and "evidence" not in entry:
                entry["evidence"] = "present"
        return
    if isinstance(old_scope, dict) and old_scope:
        record["legacy_annotation_scope"] = old_scope
    dimensions = []
    for dimension, field in (("tokens", "words"), ("lexical_category", "words"), ("phrase_constituency", "constituents"), ("clause_ontology", "clauses"), ("syntactic_function", "constituents")):
        if isinstance(record.get(field), list) and record[field]:
            dimensions.append({"dimension": dimension, "scope": {"kind": "record"}, "completeness": "partial", "omission": "none", "evidence": "present"})
    dependencies = record.get("dependencies")
    dependencies_present = isinstance(dependencies, list) and bool(dependencies)
    dimensions.append({"dimension": "dependencies", "scope": {"kind": "record"}, "completeness": "partial", "omission": "none" if dependencies_present else "intentional", "evidence": "present" if dependencies_present else "unannotated"})
    if "semantic_roles" in record.get("capability_tags", []) and not any(item.get("dimension") == "semantic_roles" for item in dimensions):
        record.setdefault("semantic_roles", [])
        dimensions.append({"dimension": "semantic_roles", "scope": {"kind": "record"}, "completeness": "partial", "omission": "intentional", "evidence": "unannotated"})
    record["annotation_scope"] = {"coverage": "task_focused_partial", "dimensions": dimensions}


def _ensure_typed_analysis(record: dict[str, Any]) -> None:
    framework = record.get("framework", {}).get("preferred", "cgel_inspired") if isinstance(record.get("framework"), dict) else "cgel_inspired"
    for field in ("canonical_analysis", "preferred_analysis"):
        analysis = record.get(field)
        if isinstance(analysis, dict) and "typed_analysis" not in analysis:
            analysis["typed_analysis"] = {
                "kind": "record_level_analysis", "framework": framework, "status": "unresolved",
                "notes": "Typed authority was not present in V0.2; linguistic review is required.",
            }


def _migrate_alternatives(record: dict[str, Any]) -> bool:
    """Move historical framework alternatives into the sole V0.4 channel."""
    framework = record.get("framework") if isinstance(record.get("framework"), dict) else {}
    old_values: list[Any] = []
    malformed_legacy = False
    if isinstance(framework, dict):
        legacy = framework.pop("alternatives", None)
        if isinstance(legacy, list):
            old_values.extend(legacy)
        elif legacy is not None:
            malformed_legacy = True
    legacy_top_level = record.pop("framework_alternatives", None)
    if isinstance(legacy_top_level, list):
        old_values.extend(legacy_top_level)
    elif legacy_top_level is not None:
        malformed_legacy = True
    if not old_values and not malformed_legacy:
        return False
    alternatives = record.setdefault("alternative_analyses", [])
    if not isinstance(alternatives, list):
        alternatives = []
        record["alternative_analyses"] = alternatives
    record_id = record.get("id", "record")
    review_required = malformed_legacy or bool(old_values)
    for index, legacy in enumerate(old_values, 1):
        if not isinstance(legacy, dict):
            continue
        framework_name = legacy.get("framework")
        prose = legacy.get("analysis")
        if not isinstance(framework_name, str) or not framework_name or not isinstance(prose, str) or not prose:
            continue
        alternatives.append({
            "id": f"{record_id}-alternative-{index}",
            "label": f"{framework_name} established alternative",
            "claims": [prose],
            "framework": framework_name,
            "status": "review_required",
            "typed_analysis": {
                "kind": "framework_alternative",
                "framework": framework_name,
                "status": "review_required",
                "notes": "Migrated prose-only legacy framework alternative; typed authority requires review.",
            },
        })
    return review_required


def migrate(record: dict[str, Any]) -> dict[str, Any]:
    """Migrate V0.2 in place; V0.4 is an exact no-op; unknown versions fail."""
    if not isinstance(record, dict):
        raise ValueError("migration input must be an object")
    source = record.get("schema_version")
    if source == TARGET_SCHEMA_VERSION:
        return record
    if source != SOURCE_SCHEMA_VERSION:
        raise ValueError(f"unsupported source schema_version {source!r}; expected '0.2' or exact '0.4'")
    review_required = False
    preferred = record.pop("preferred_analysis", None)
    if preferred is not None:
        if "canonical_analysis" not in record:
            record["canonical_analysis"] = preferred
        elif record["canonical_analysis"] != preferred:
            record["legacy_preferred_analysis"] = preferred
            review_required = True
    for word in record.get("words", []):
        if isinstance(word, dict):
            review_required = _migrate_word(word) or review_required
            word.setdefault("node_kind", "word")
            if word.get("lexical_category") == "determiner":
                word["lexical_category"] = "determinative"
    for clause in record.get("clauses", []):
        if isinstance(clause, dict):
            review_required = _migrate_clause(clause) or review_required
    clause_map = {clause.get("id"): clause for clause in record.get("clauses", []) if isinstance(clause, dict) and isinstance(clause.get("id"), str)}
    for constituent in record.get("constituents", []):
        if isinstance(constituent, dict):
            review_required = _migrate_constituent(constituent, clause_map) or review_required
            if constituent.get("function") == "determinative":
                constituent["function"] = "determiner"
    review_required = _migrate_alternatives(record) or review_required
    _migrate_scope(record)
    _ensure_typed_analysis(record)
    words = record.get("words", [])
    for clause in record.get("clauses", []):
        if isinstance(clause, dict) and isinstance(clause.get("span"), dict) and isinstance(words, list) and clause["span"].get("end") == len(words) and words and isinstance(words[-1], dict) and words[-1].get("lexical_category") == "punctuation":
            clause["span"]["end"] -= 1
    record["schema_version"] = TARGET_SCHEMA_VERSION
    migration_metadata = record.setdefault("migration_metadata", {})
    if isinstance(migration_metadata, dict):
        migration_metadata["source_schema_version"] = SOURCE_SCHEMA_VERSION
        migration_metadata["target_schema_version"] = TARGET_SCHEMA_VERSION
        migration_metadata.setdefault("source_release", "v0.2.1")
        migration_metadata["deterministic"] = True
    _ensure_review_metadata(record, required=review_required)
    if review_required:
        _mark_review_required(record, "Source fields lacked a unique deterministic V0.4 mapping; human review is required.")
    return record


def migrate_file(path: Path) -> list[str]:
    rows: list[dict[str, Any]] = []
    review_ids: list[str] = []
    changed = False
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                source_version = record.get("schema_version") if isinstance(record, dict) else None
                migrate(record)
                changed = changed or source_version != TARGET_SCHEMA_VERSION
            except (json.JSONDecodeError, ValueError) as error:
                raise ValueError(f"{path}:{line_number}: {error}") from error
            rows.append(record)
            if record.get("migration_review_required"):
                review_ids.append(str(record.get("id", "<missing-id>")))
    if not changed:
        return review_ids
    with path.open("w", encoding="utf-8") as handle:
        for record in rows:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    return review_ids


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    for path in parser.parse_args().paths:
        print(f"{path}: review_required={migrate_file(path)}")
