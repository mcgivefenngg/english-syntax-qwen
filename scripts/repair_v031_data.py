#!/usr/bin/env python3
"""Apply explicit fixture-specific V0.4 data-shape repairs to existing records.

This is deliberately not the generic V0.2 schema migration.  It performs no
new linguistic adjudication; framework-sensitive lexical items are downgraded
to unresolved candidates and the existing benchmark count/content is retained.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

try:
    from migration_safety import (
        canonicalize_coverage_entry,
        normalize_reference_collections,
        quarantine_uncovered_collection_content,
        retain_migrated_coverage_entry,
        sort_coverage_entries,
        validate_canonical_record,
    )
except ImportError:
    from scripts.migration_safety import (
        canonicalize_coverage_entry,
        normalize_reference_collections,
        quarantine_uncovered_collection_content,
        retain_migrated_coverage_entry,
        sort_coverage_entries,
        validate_canonical_record,
    )


ROOT = Path(__file__).resolve().parents[1]
TARGET_SCHEMA_VERSION = "0.4"
REPAIR_VERSION = "0.4.0"
REPAIR_OUTPUT_HASH_FIELD = "repair_output_hash"
PROTECTED_REVIEW_STATUSES = frozenset(
    {"linguistically_reviewed", "approved_for_training", "canonical_gold"}
)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _repair_output_hash_input(record: dict[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(record)
    metadata = value.get("migration_metadata")
    if isinstance(metadata, dict):
        metadata.pop(REPAIR_OUTPUT_HASH_FIELD, None)
    return value


def _repair_output_hash(record: dict[str, Any]) -> str:
    """Hash repaired output without making the hash field self-referential."""
    return _canonical_hash(_repair_output_hash_input(record))


def assert_fixture_repair_allowed(record: dict[str, Any]) -> None:
    metadata = record.get("review_metadata")
    status = metadata.get("review_status") if isinstance(metadata, dict) else None
    if status in PROTECTED_REVIEW_STATUSES:
        raise ValueError(f"{record.get('id')}: refusing repair of reviewed/approved record")


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


def _repair_record_unchecked(record: dict[str, Any]) -> dict[str, Any]:
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
    review_required = normalize_reference_collections(record)
    preserve_scope = False
    if isinstance(old_scope, dict) and isinstance(old_scope.get("dimensions"), list) and old_scope["dimensions"]:
        dimensions = []
        for source in old_scope["dimensions"]:
            entry, entry_review = canonicalize_coverage_entry(
                record,
                source,
            )
            review_required = review_required or entry_review
            preserve_scope = preserve_scope or entry_review or entry != source
            if entry is not None and retain_migrated_coverage_entry(entry):
                dimensions.append(entry)
    else:
        old_dimensions = old_scope.get("annotated_dimensions", []) if isinstance(old_scope, dict) else []
        dimensions = []
        for dimension in old_dimensions:
            source = {"dimension": dimension, "scope": {"kind": "record"}, "completeness": "partial", "omission": "none"}
            entry, entry_review = canonicalize_coverage_entry(record, source)
            review_required = review_required or entry_review
            preserve_scope = preserve_scope or entry_review or entry != source
            if entry is not None and retain_migrated_coverage_entry(entry):
                dimensions.append(entry)
    if preserve_scope and "legacy_annotation_scope" not in record:
        legacy_scope = copy.deepcopy(old_scope)
        if isinstance(legacy_scope, dict) and isinstance(legacy_scope.get("dimensions"), list) and all(isinstance(entry, dict) for entry in legacy_scope["dimensions"]):
            legacy_scope["dimensions"] = sort_coverage_entries(legacy_scope["dimensions"])
        if isinstance(legacy_scope, dict):
            record["legacy_annotation_scope"] = legacy_scope
    existing = {entry.get("dimension") for entry in dimensions}
    record.setdefault("dependencies", [])
    for dimension, field in (
        ("semantic_roles", "semantic_roles"),
        ("lexical_valency", "lexical_valency"),
        ("dependencies", "dependencies"),
    ):
        if dimension in existing:
            continue
        if dimension == "dependencies" or field in record or dimension in record.get("capability_tags", []):
            if dimension != "dependencies":
                record.setdefault(field, [])
            dimensions.append({
                "dimension": dimension,
                "scope": {"kind": "record"},
                "completeness": "unannotated",
                "omission": "intentional",
                "evidence": "unannotated",
            })
            review_required = True
    dimensions = sort_coverage_entries(dimensions)
    review_required = quarantine_uncovered_collection_content(record, dimensions) or review_required
    record["annotation_scope"] = {
        "coverage": "task_focused_partial",
        "dimensions": dimensions,
        "annotated_dimensions": [entry["dimension"] for entry in dimensions if entry["omission"] == "none"],
        "intentionally_omitted": [entry["dimension"] for entry in dimensions if entry["omission"] != "none"],
    }
    metadata = record.get("review_metadata")
    if not isinstance(metadata, dict):
        metadata = {}
        record["review_metadata"] = metadata
    metadata.setdefault("review_status", "schema_migrated")
    metadata.setdefault("reviewer_type", "automated_structural")
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
    if review_required:
        sensitive = True
        if metadata.get("review_status") not in PROTECTED_REVIEW_STATUSES:
            metadata["review_status"] = "review_required"
        record["migration_review_required"] = True
        record["migration_note"] = "Legacy coverage or collection ownership lacked a unique deterministic V0.4 mapping; human review is required."
    if sensitive or any(isinstance(word, dict) and isinstance(word.get("lexical_analysis"), dict) for word in record.get("words", [])):
        metadata["review_status"] = "review_required"
    record["schema_version"] = TARGET_SCHEMA_VERSION
    return record


def _already_repaired(record: dict[str, Any]) -> bool:
    return (
        record.get("schema_version") == TARGET_SCHEMA_VERSION
        and isinstance(record.get("migration_metadata"), dict)
        and record["migration_metadata"].get("fixture_repair_version") == REPAIR_VERSION
    )


def repair_record(record: dict[str, Any]) -> dict[str, Any]:
    """Repair one record while enforcing repaired-output provenance integrity.

    A successful return guarantees that the protected-provenance check
    passed, ``migration_metadata.repair_output_hash`` matches the returned
    content under ``_repair_output_hash()``, and the final record passes
    canonical V0.4 validation.  Already-repaired inputs are verified as-is:
    a missing or stale output hash fails closed and is never regenerated,
    because silently re-hashing would erase evidence of tampering.  The
    caller's dict is updated in place only after every check succeeds.
    """
    assert_fixture_repair_allowed(record)
    identifier = record.get("id")
    if _already_repaired(record):
        stored_hash = record["migration_metadata"].get(REPAIR_OUTPUT_HASH_FIELD)
        if stored_hash is None:
            raise ValueError(f"{identifier}: repaired output hash is required")
        if not isinstance(stored_hash, str) or stored_hash != _repair_output_hash(record):
            raise ValueError(f"{identifier}: repaired output hash mismatch")
        validate_canonical_record(record, f"{identifier}: repaired output")
        return record
    candidate = copy.deepcopy(record)
    repaired = _repair_record_unchecked(candidate)
    metadata = repaired.get("migration_metadata")
    if not isinstance(metadata, dict):
        raise ValueError(f"{identifier}: migration_metadata must be an object")
    metadata[REPAIR_OUTPUT_HASH_FIELD] = _repair_output_hash(repaired)
    validate_canonical_record(repaired, f"{identifier}: repaired output")
    record.clear()
    record.update(repaired)
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
    seen_input_ids: set[str] = set()
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if line.strip():
                record = json.loads(line)
                identifier = record.get("id")
                if isinstance(identifier, str):
                    if identifier in seen_input_ids:
                        raise ValueError(
                            f"input contains duplicate record id {identifier!r} at line {line_number}"
                        )
                    seen_input_ids.add(identifier)
                entry = manifest.get(identifier)
                if entry is None:
                    rows.append(record)
                    continue
                assert_fixture_repair_allowed(record)
                already_repaired = _already_repaired(record)
                if record.get("schema_version") != entry["source_version"] and not already_repaired:
                    raise ValueError(f"{record.get('id')}: manifest source_version mismatch")
                if already_repaired:
                    actual_hash = _repair_output_hash(record)
                    stored_hash = record.get("migration_metadata", {}).get(REPAIR_OUTPUT_HASH_FIELD)
                    expected_hash = entry.get(REPAIR_OUTPUT_HASH_FIELD)
                    if stored_hash is None and expected_hash is None:
                        raise ValueError(f"{record.get('id')}: repaired output hash is required")
                    if stored_hash is not None and (not isinstance(stored_hash, str) or stored_hash != actual_hash):
                        raise ValueError(f"{record.get('id')}: repaired output hash mismatch")
                    if expected_hash is not None and expected_hash != actual_hash:
                        raise ValueError(f"{record.get('id')}: manifest repaired output hash mismatch")
                    rows.append(record)
                    continue
                expected_hash = entry.get("source_hash")
                if expected_hash:
                    actual_hash = _canonical_hash(record)
                    if actual_hash != expected_hash:
                        raise ValueError(f"{record.get('id')}: source hash mismatch")
                before = _canonical_json(record)
                repaired = repair_record(record)
                repaired.setdefault("migration_metadata", {})[REPAIR_OUTPUT_HASH_FIELD] = _repair_output_hash(repaired)
                expected_output_hash = entry.get(REPAIR_OUTPUT_HASH_FIELD)
                if expected_output_hash is not None and expected_output_hash != repaired["migration_metadata"][REPAIR_OUTPUT_HASH_FIELD]:
                    raise ValueError(f"{record.get('id')}: manifest repaired output hash mismatch")
                after = _canonical_json(repaired)
                changed = changed or before != after
                rows.append(repaired)
    unknown = set(manifest) - {str(row.get("id")) for row in rows}
    if unknown:
        raise ValueError(f"manifest IDs missing from input: {sorted(unknown)}")
    for row_number, row in enumerate(rows, 1):
        must_validate = changed or str(row.get("id")) in manifest
        if must_validate:
            validate_canonical_record(row, f"{path}:{row_number}")
    must_write = changed
    if must_write:
        with path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(_canonical_json(row) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    arguments = parser.parse_args()
    for path in arguments.paths:
        repair_file(path, arguments.manifest)
