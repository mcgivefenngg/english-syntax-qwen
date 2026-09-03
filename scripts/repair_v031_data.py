#!/usr/bin/env python3
"""Apply explicit fixture-specific V0.4 data-shape repairs to existing records.

This is deliberately not the generic V0.2 schema migration.  It performs no
new linguistic adjudication; framework-sensitive lexical items are downgraded
to unresolved candidates and the existing benchmark count/content is retained.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TARGET_SCHEMA_VERSION = "0.4"
REPAIR_VERSION = "0.4.0"


def _unresolved_candidate(form: str) -> dict[str, Any] | None:
    form = form.casefold()
    candidates = {
        "that": [("pronoun", "relative"), ("subordinator", "marker")],
        "those": [("determinative", "determiner"), ("pronoun", "subject_or_object")],
        "what": [("pronoun", "interrogative_or_relative"), ("subordinator", "marker")],
        "where": [("adverb", "interrogative_or_relative"), ("subordinator", "marker")],
        "for": [("preposition", "complement"), ("subordinator", "marker")],
        "be": [("auxiliary", "predicator"), ("verb", "predicator")],
        "is": [("auxiliary", "predicator"), ("verb", "predicator")],
        "are": [("auxiliary", "predicator"), ("verb", "predicator")],
        "was": [("auxiliary", "predicator"), ("verb", "predicator")],
        "were": [("auxiliary", "predicator"), ("verb", "predicator")],
    }
    values = candidates.get(form)
    if not values:
        return None
    return {
        "status": "unresolved",
        "review_required": True,
        "candidates": [
            {"category": category, "lexical_category": category, "category_namespace": "cgel_inspired", "status": "unresolved", "syntactic_function": function, "framework": "cgel_inspired"}
            for category, function in values
        ],
        "note": "Framework-sensitive lexical item retained without canonical adjudication.",
    }


def repair_record(record: dict[str, Any]) -> dict[str, Any]:
    for word in record.get("words", []):
        if not isinstance(word, dict):
            continue
        if word.get("lexical_category") == "determiner":
            word["lexical_category"] = "determinative"
        lexical_analysis = _unresolved_candidate(str(word.get("form", "")))
        if lexical_analysis is not None:
            word["lexical_category"] = None
            word["lexical_analysis"] = lexical_analysis
    for item in record.get("constituents", []):
        if isinstance(item, dict) and item.get("function") == "determinative":
            item["function"] = "determiner"

    clauses = [clause for clause in record.get("clauses", []) if isinstance(clause, dict)]
    wrappers = [item for item in record.get("constituents", []) if isinstance(item, dict) and item.get("node_kind") == "clause"]
    clause_map = {clause.get("id"): clause for clause in clauses}
    sensitive = False
    for clause in clauses:
        if "clause_construction" in clause and isinstance(clause.get("integration"), list):
            # Already repaired records are left untouched (repair idempotence).
            if clause.get("legacy_function") == "main" and "root" not in clause["integration"]:
                clause["integration"] = ["root"]
                if record.get("sentence_type") in {"interrogative", "exclamative", "declarative"}:
                    clause["clause_construction"] = record["sentence_type"]
            continue
        old_type = clause.pop("clause_type", None)
        old_status = clause.pop("clause_status", None)
        old_function = clause.pop("function", None)
        construction_map = {"declarative_content": "content", "interrogative": "interrogative", "relative": "relative", "exclamative": "exclamative", "conditional": "conditional", "comparative": "comparative", "coordinate": "coordinate"}
        construction = construction_map.get(old_type, old_type if old_type in {"declarative", "content", "unresolved"} else "unresolved")
        if old_status == "root":
            if record.get("sentence_type") in {"interrogative", "exclamative", "declarative"}:
                construction = record["sentence_type"]
            integration = ["root"]
        elif old_status == "coordinate_member":
            integration = ["coordinate_member"]
            if old_type != "coordinate":
                integration.append("subordinate")
        elif old_status == "supplement":
            integration = ["supplementary"]
        else:
            integration = ["unresolved"]
        clause["clause_construction"] = construction or "other"
        clause["integration"] = integration
        if clause["clause_construction"] == "unresolved" or "unresolved" in integration:
            sensitive = True
        if old_function:
            clause["legacy_function"] = old_function
        if construction in {"relative", "interrogative"} and any(word.get("lexical_analysis", {}).get("status") == "unresolved" for word in record.get("words", []) if isinstance(word, dict)):
            sensitive = True
    if clauses and not any("root" in clause.get("integration", []) for clause in clauses):
        # Existing coordination records encode the root as a spanning first
        # clause; restoring that structural relation does not choose a theory.
        clauses[0]["integration"] = ["root"]
        if record.get("sentence_type") in {"interrogative", "exclamative", "declarative"}:
            clauses[0]["clause_construction"] = record["sentence_type"]

    for wrapper in wrappers:
        clause = clause_map.get(wrapper.get("clause_ref"))
        if not clause:
            continue
        clause_span = clause.get("span", {})
        wrapper_span = wrapper.get("span", {})
        if clause_span == wrapper_span:
            relation = "same_span_alias"
        elif isinstance(clause_span, dict) and isinstance(wrapper_span, dict) and wrapper_span.get("start", 0) <= clause_span.get("start", 0) and wrapper_span.get("end", 0) >= clause_span.get("end", 0):
            relation = "expanded_realization"
        else:
            relation = "other"
            sensitive = True
        wrapper["realization"] = {"clause_ref": wrapper["clause_ref"], "relation": relation}

    old_scope = record.get("annotation_scope", {})
    if isinstance(old_scope, dict) and isinstance(old_scope.get("dimensions"), list) and old_scope["dimensions"]:
        dimensions = [dict(entry) for entry in old_scope["dimensions"] if isinstance(entry, dict)]
    else:
        old_dimensions = old_scope.get("annotated_dimensions", []) if isinstance(old_scope, dict) else []
        dimensions = []
        for dimension in old_dimensions:
            if dimension == "dependencies" and record.get("dependencies") == []:
                dimensions.append({"dimension": dimension, "scope": {"kind": "record"}, "completeness": "partial", "omission": "intentional", "evidence": "unannotated"})
            else:
                dimensions.append({"dimension": dimension, "scope": {"kind": "record"}, "completeness": "partial", "omission": "none", "evidence": "present"})
    for dimension, field in (("semantic_roles", "semantic_roles"), ("lexical_valency", "lexical_valency"), ("framework_mapping", "framework"), ("construction_relations", "construction_type")):
        if dimension not in {entry.get("dimension") for entry in dimensions} and ((isinstance(record.get(field), list) and record[field]) or (dimension == "framework_mapping" and isinstance(record.get(field), dict)) or (dimension == "construction_relations" and record.get(field))):
            dimensions.append({"dimension": dimension, "scope": {"kind": "record"}, "completeness": "partial", "omission": "none", "evidence": "present"})
    if "semantic_roles" in record.get("capability_tags", []) and "semantic_roles" not in {entry.get("dimension") for entry in dimensions}:
        record.setdefault("semantic_roles", [])
        dimensions.append({"dimension": "semantic_roles", "scope": {"kind": "record"}, "completeness": "partial", "omission": "intentional", "evidence": "unannotated"})
    if "lexical_valency" in record.get("capability_tags", []) and "lexical_valency" not in {entry.get("dimension") for entry in dimensions}:
        record.setdefault("lexical_valency", [])
        dimensions.append({"dimension": "lexical_valency", "scope": {"kind": "record"}, "completeness": "partial", "omission": "intentional", "evidence": "unannotated"})
    if not any(entry.get("dimension") == "dependencies" for entry in dimensions):
        dimensions.append({"dimension": "dependencies", "scope": {"kind": "record"}, "completeness": "partial", "omission": "intentional", "evidence": "unannotated" if record.get("dependencies") == [] else "present"})
    record["annotation_scope"] = {
        "coverage": "task_focused_partial",
        "dimensions": dimensions,
        "annotated_dimensions": [entry["dimension"] for entry in dimensions if entry["omission"] == "none"],
        "intentionally_omitted": [entry["dimension"] for entry in dimensions if entry["omission"] != "none"],
    }
    metadata = record.setdefault("review_metadata", {})
    analysis = record.get("canonical_analysis", {})
    label = str(analysis.get("label", "")).casefold()
    claims = " ".join(str(claim) for claim in analysis.get("claims", []) if isinstance(claim, str)).casefold()
    unresolved_theory = ("ecm", "raising", "control", "perception", "small-clause", "small clause", "fused-relative", "fused relative", "secondary predication")
    if any(term in label or term in claims for term in unresolved_theory):
        sensitive = True
        if isinstance(analysis, dict):
            analysis["typed_analysis"] = {
                "kind": "unresolved_construction",
                "framework": "cgel_inspired",
                "status": "review_required",
                "notes": "Existing construction claim retained as explanatory evidence; final adjudication deferred.",
            }
    metadata["migration_version"] = REPAIR_VERSION
    migration_metadata = record.setdefault("migration_metadata", {})
    if isinstance(migration_metadata, dict):
        migration_metadata["fixture_repair_version"] = REPAIR_VERSION
    if sensitive or any(isinstance(word, dict) and isinstance(word.get("lexical_analysis"), dict) for word in record.get("words", [])):
        metadata["review_status"] = "review_required"
    record["schema_version"] = TARGET_SCHEMA_VERSION
    return record


def _load_manifest(path: Path) -> dict[str, dict[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    entries = value.get("records") if isinstance(value, dict) else value
    if not isinstance(entries, list):
        raise ValueError("repair manifest must contain a records array")
    manifest: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str) or not isinstance(entry.get("source_version"), str):
            raise ValueError("each repair manifest entry requires id and source_version")
        if entry["id"] in manifest:
            raise ValueError(f"repair manifest contains duplicate id {entry['id']!r}")
        manifest[entry["id"]] = entry
    return manifest


def repair_file(path: Path, manifest_path: Path | None = None) -> None:
    if manifest_path is None:
        raise ValueError("fixture-specific repairs require an explicit manifest")
    manifest = _load_manifest(manifest_path)
    rows = []
    changed = False
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                record = json.loads(line)
                entry = manifest.get(record.get("id"))
                if entry is None:
                    rows.append(record)
                    continue
                metadata = record.get("review_metadata") if isinstance(record.get("review_metadata"), dict) else {}
                if metadata.get("review_status") in {"linguistically_reviewed", "approved_for_training", "canonical_gold"}:
                    raise ValueError(f"{record.get('id')}: refusing repair of reviewed/approved record")
                already_repaired = (
                    record.get("schema_version") == TARGET_SCHEMA_VERSION
                    and isinstance(record.get("migration_metadata"), dict)
                    and record["migration_metadata"].get("fixture_repair_version") == REPAIR_VERSION
                )
                if record.get("schema_version") != entry["source_version"] and not already_repaired:
                    raise ValueError(f"{record.get('id')}: manifest source_version mismatch")
                if already_repaired:
                    rows.append(record)
                    continue
                expected_hash = entry.get("source_hash")
                if expected_hash:
                    import hashlib
                    actual_hash = hashlib.sha256(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                    if actual_hash != expected_hash:
                        raise ValueError(f"{record.get('id')}: source hash mismatch")
                before = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                repaired = repair_record(record)
                after = json.dumps(repaired, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                changed = changed or before != after
                rows.append(repaired)
    unknown = set(manifest) - {str(row.get("id")) for row in rows}
    if unknown:
        raise ValueError(f"manifest IDs missing from input: {sorted(unknown)}")
    if changed:
        with path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    arguments = parser.parse_args()
    for path in arguments.paths:
        repair_file(path, arguments.manifest)
