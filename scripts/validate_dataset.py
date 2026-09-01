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
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover - exercised by the CLI failure path
    Draft202012Validator = None

try:
    from data_common import (
        ALTERNATIVE_CONSTRUCTION_WHITELIST, AMBIGUITY_STATUSES, CAPABILITY_TAGS,
        CLAUSE_CATEGORIES, DIFFICULTIES, FRAMEWORKS, LEXICAL_CATEGORIES,
        PHRASE_CATEGORIES, SCHEMA_VERSIONS, SEMANTIC_ROLES, SENTENCE_CLASSIFICATION_LABELS, SENTENCE_TYPES,
        SOURCE_TYPES, SPLITS, construction_signature, iter_jsonl_paths, normalized_text,
        normalized_surface_tokens, read_jsonl, sentence_from_record, sentence_word_alignment,
    )
except ImportError:
    from scripts.data_common import (
        ALTERNATIVE_CONSTRUCTION_WHITELIST, AMBIGUITY_STATUSES, CAPABILITY_TAGS,
        CLAUSE_CATEGORIES, DIFFICULTIES, FRAMEWORKS, LEXICAL_CATEGORIES,
        PHRASE_CATEGORIES, SCHEMA_VERSIONS, SEMANTIC_ROLES, SENTENCE_CLASSIFICATION_LABELS, SENTENCE_TYPES,
        SOURCE_TYPES, SPLITS, construction_signature, iter_jsonl_paths, normalized_text,
        normalized_surface_tokens, read_jsonl, sentence_from_record, sentence_word_alignment,
    )


REQUIRED = {
    "schema_version", "id", "sentence", "capability_tags", "difficulty", "source_type",
    "framework", "sentence_type", "clauses", "constituents", "words", "dependencies",
    "explanation", "split",
}
ANALYSIS_LEVELS = {"lexical_category", "phrase_category", "syntactic_function", "clause_structure", "framework", "semantic_role", "span", "none"}
REVIEW_STATUSES = {"schema_migrated", "structurally_validated", "review_required", "linguistically_reviewed", "canonical_gold"}
REVIEWER_TYPES = {"automated_structural", "independent_linguistic", "human_annotation", "mixed"}


@lru_cache(maxsize=4)
def _schema_validator(schema_path_value: str | None = None) -> Any:
    if Draft202012Validator is None:
        raise RuntimeError("jsonschema dependency is required for canonical validation")
    schema_path = Path(schema_path_value) if schema_path_value else Path(__file__).resolve().parents[1] / "schemas" / "gold_annotation.schema.json"
    with schema_path.open(encoding="utf-8") as handle:
        schema_document = json.load(handle)
    validator = Draft202012Validator(schema_document)
    validator.check_schema(schema_document)
    return validator


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
    try:
        validator = _schema_validator(str(schema_path) if schema_path else None)
    except (OSError, json.JSONDecodeError, RuntimeError, TypeError) as error:
        _error(errors, location, f"schema engine unavailable: {error}")
        return
    record_id = record.get("id", "<missing-id>")
    for schema_error in sorted(validator.iter_errors(record), key=lambda item: list(item.path)):
        _error(errors, f"{location} record {record_id!r}{_schema_path(schema_error.path)}", f"schema validation failed: {schema_error.message}")


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


def _is_v2(record: dict[str, Any]) -> bool:
    return record.get("schema_version") == "0.2"


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
    elif _known(metadata.get("review_status"), {"linguistically_reviewed", "canonical_gold"}) and metadata.get("reviewer_type") == "automated_structural":
        _error(errors, f"{location}.review_metadata", "linguistic/canonical status requires a human or mixed reviewer type")
    if not isinstance(metadata.get("migration_version"), str) or not metadata["migration_version"]:
        _error(errors, f"{location}.review_metadata", "migration_version must be a non-empty string")
    if "review_date" in metadata and (not isinstance(metadata["review_date"], str) or not metadata["review_date"]):
        _error(errors, f"{location}.review_metadata", "review_date must be a non-empty string when supplied")


def _validate_analysis(item: Any, location: str, errors: list[str], alternative: bool = False) -> None:
    if not isinstance(item, dict) or not item.get("label") or not isinstance(item.get("claims"), list) or not item.get("claims") or any(not isinstance(claim, str) or not claim for claim in item.get("claims", [])):
        _error(errors, location, "analysis requires a non-empty label and claims list")
        return
    if alternative:
        if not _known(item.get("framework"), FRAMEWORKS):
            _error(errors, location, "alternative analysis must name a known framework")
        if item.get("status") != "established":
            _error(errors, location, "alternative analysis status must be 'established'")
        analysis_type = item.get("analysis_type")
        if analysis_type == "small_clause":
            construction = item.get("construction_type")
            if not _known(construction, ALTERNATIVE_CONSTRUCTION_WHITELIST["small_clause"]):
                _error(errors, location, "small-clause alternatives require an approved construction-specific whitelist entry")


def _validate_predicand(value: Any, location: str, ids: set[str], objects: dict[str, dict[str, Any]], version: str, errors: list[str]) -> None:
    if value is None:
        return
    if isinstance(value, str):
        if version == "0.2":
            _error(errors, location, "V0.2 predicand must be a structured object")
        elif value not in ids:
            _error(errors, location, "predicand must reference a known ID")
        return
    if not isinstance(value, dict) or not _known(value.get("kind"), {"overt_constituent", "implicit_control", "discourse_inferred", "generic", "indeterminate"}):
        _error(errors, location, "predicand kind is invalid")
        return
    target = value.get("target")
    if value["kind"] in {"overt_constituent", "implicit_control"}:
        if not isinstance(target, str) or target not in ids:
            _error(errors, location, "overt_constituent and implicit_control predicands require a known target")
        elif value["kind"] == "overt_constituent":
            target_object = objects.get(target)
            if not target_object or target_object.get("node_kind") != "phrase" or target_object.get("phrase_category") != "NP":
                _error(errors, location, "overt_constituent predicands must target an NP constituent, not a word or determiner")
    elif target is not None and (not isinstance(target, str) or target not in ids):
        _error(errors, location, "predicand target must reference a known ID when supplied")


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
                        if payload.get("id") != record.get("id"):
                            _error(errors, f"{location}.messages[2].content.id", "assistant payload id must match rendered record id")
                        errors.extend(validate_record(payload, f"{location}.messages[2].content", schema_path))
        return errors
    _validate_json_schema(record, location, errors, schema_path)
    missing = REQUIRED - record.keys()
    for field in sorted(missing):
        _error(errors, location, f"missing required field {field!r}")
    if missing:
        return errors
    _validate_review_metadata(record, location, errors)
    version = record["schema_version"]
    if version not in SCHEMA_VERSIONS:
        _error(errors, location, "schema_version must be '0.1' or '0.2'")
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
        alternatives = framework.get("alternatives", [])
        if not isinstance(alternatives, list):
            _error(errors, location, "framework.alternatives must be an array")
        else:
            for index, item in enumerate(alternatives):
                if not isinstance(item, dict) or not _known(item.get("framework"), FRAMEWORKS) or item.get("status") != "established" or not item.get("analysis"):
                    _error(errors, f"{location}.framework.alternatives[{index}]", "framework alternative must name an established framework and analysis")
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
        for field in ("id", "form", "lemma", "lexical_category"):
            if not isinstance(word.get(field), str) or not word[field]:
                _error(errors, word_location, f"{field} must be a non-empty string")
        if _is_v2(record) and word.get("node_kind") != "word":
            _error(errors, word_location, "V0.2 words must have node_kind='word'")
        word_id = word.get("id")
        if isinstance(word_id, str):
            if word_id in word_ids:
                _error(errors, word_location, f"duplicate word id {word_id!r}")
            word_ids.add(word_id)
        if not _known(word.get("lexical_category"), LEXICAL_CATEGORIES):
            _error(errors, word_location, "unknown lexical_category")
        tags_for_word = word.get("external_pos_tags")
        if tags_for_word is not None:
            if not isinstance(tags_for_word, list):
                _error(errors, word_location, "external_pos_tags must be an array")
            else:
                for tag_index, tag in enumerate(tags_for_word):
                    if not isinstance(tag, dict) or not isinstance(tag.get("tagset"), str) or not tag["tagset"] or not isinstance(tag.get("tag"), str) or not tag["tag"]:
                        _error(errors, f"{word_location}.external_pos_tags[{tag_index}]", "external POS tags require tagset and tag")
        if _is_v2(record) and "pos" in word and "pos_tagset" not in word and not tags_for_word:
            _error(errors, word_location, "legacy pos requires pos_tagset; use external_pos_tags with an explicit tagset")
        if _is_v2(record) and "pedagogical_terms" in word:
            _error(errors, word_location, "V0.2 pedagogical terms belong in framework-qualified pedagogical_aliases")

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
            required = ("id", "span", "function") if field_name == "constituents" else ("id", "span", "function", "finiteness")
            for field in required:
                if field not in item:
                    _error(errors, item_location, f"missing {field}")
            span = item.get("span", {})
            if not isinstance(span, dict) or not isinstance(span.get("start"), int) or not isinstance(span.get("end"), int) or span.get("start", -1) < 0 or span.get("end", 0) <= span.get("start", 0) or span.get("end", 0) > max_token:
                _error(errors, item_location, "span must be a valid half-open token span")
            elif isinstance(words[span["end"] - 1], dict) and words[span["end"] - 1].get("lexical_category") == "punctuation":
                is_main_clause = field_name == "clauses" and item.get("clause_category") == "main_clause"
                if not is_main_clause:
                    _error(errors, item_location, "only main_clause spans may terminate at a punctuation token")
            if not isinstance(item.get("function"), str) or not item.get("function"):
                _error(errors, item_location, "function must be a non-empty string")
            if field_name == "constituents":
                constituent_category = item.get("phrase_category") or item.get("category")
                if _is_v2(record):
                    if item.get("node_kind") not in {"phrase", "clause", "word"}:
                        _error(errors, item_location, "V0.2 constituents require node_kind phrase, clause, or word")
                    if item.get("node_kind") == "phrase":
                        if not _known(item.get("phrase_category"), PHRASE_CATEGORIES):
                            _error(errors, item_location, "phrase nodes require a valid phrase category in phrase_category; Clause is not a phrase category")
                        if item.get("phrase_category") == "word":
                            _error(errors, item_location, "word category requires node_kind='word', not a phrase node")
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
                    elif item.get("node_kind") == "word" and any(key in item for key in ("phrase_category", "category", "clause_ref")):
                        _error(errors, item_location, "word nodes must use the words collection, not phrase/clause category fields")
                elif not _known(item.get("category"), PHRASE_CATEGORIES | {"Clause"}):
                    _error(errors, item_location, "unknown phrase category")
                if constituent_category == "PP" and item.get("function") == "AdvP":
                    _error(errors, item_location, "PP is a phrase category; AdvP is not a syntactic function")
                if _is_v2(record) and "role" in item:
                    _error(errors, item_location, "V0.2 semantic roles belong in semantic_roles, not constituent.role")
                if "head" in item and item.get("head") is not None:
                    _require_ref_kind(item.get("head"), objects, {"word"}, f"{item_location}.head", errors, "constituent.head")
                if "parent" in item and item.get("parent") is not None:
                    _require_ref_kind(item.get("parent"), objects, {"phrase", "clause"}, f"{item_location}.parent", errors, "constituent.parent")
            else:
                category = item.get("clause_category") or item.get("category")
                if _is_v2(record):
                    if item.get("node_kind") != "clause":
                        _error(errors, item_location, "V0.2 clause entries require node_kind='clause'")
                    if not _known(item.get("clause_category"), CLAUSE_CATEGORIES):
                        _error(errors, item_location, "V0.2 clauses require clause_category")
                    if "category" in item:
                        _error(errors, item_location, "V0.2 clauses must use clause_category; category is a V0.1 compatibility field")
                elif not _known(category, CLAUSE_CATEGORIES):
                    _error(errors, item_location, "unknown clause category")
                if not _known(item.get("finiteness"), {"finite", "non-finite"}):
                    _error(errors, item_location, "finiteness must be finite or non-finite")
                if item.get("finiteness") == "finite" and isinstance(category, str) and category in {"nonfinite_clause", "gerund_participial_clause", "infinitival_clause"}:
                    _error(errors, item_location, "non-finite clause category cannot be marked finite")
                for ref_field in ("subject", "head"):
                    if ref_field in item and not _valid_ref(item.get(ref_field), all_ids):
                        _error(errors, item_location, f"{ref_field} must reference a known ID")
                if item.get("subject") is not None:
                    subject_id = item.get("subject")
                    subject_kind = _ref_kind(subject_id, objects)
                    subject_object = objects.get(subject_id) if isinstance(subject_id, str) else None
                    if subject_kind not in {"word", "phrase", "clause"}:
                        _error(errors, f"{item_location}.subject", "clause.subject must reference a word, phrase, or clause")
                    elif subject_kind == "word" and subject_object.get("lexical_category") not in {"noun", "pronoun"}:
                        _error(errors, f"{item_location}.subject", "clause.subject word reference must be nominal, not a marker/verb/punctuation")
                    elif subject_kind == "phrase" and subject_object.get("phrase_category") != "NP":
                        _error(errors, f"{item_location}.subject", "clause.subject phrase reference must be an NP")
                _validate_predicand(item.get("predicand"), f"{item_location}.predicand", all_ids, objects, version, errors)

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
    if "canonical_analysis" in record:
        _validate_analysis(record["canonical_analysis"], f"{location}.canonical_analysis", errors)
        analyses.append(record["canonical_analysis"])
    if "preferred_analysis" in record:
        _validate_analysis(record["preferred_analysis"], f"{location}.preferred_analysis", errors)
        analyses.append(record["preferred_analysis"])
    if not analyses:
        _error(errors, location, "record requires canonical_analysis or preferred_analysis")
    if len(analyses) == 2 and analyses[0] != analyses[1]:
        _error(errors, location, "canonical_analysis and preferred_analysis disagree; keep one source of truth")
    for field_name in ("framework_alternatives", "alternative_analyses"):
        values = record.get(field_name, [])
        if not isinstance(values, list):
            _error(errors, location, f"{field_name} must be an array")
        else:
            for index, item in enumerate(values):
                _validate_analysis(item, f"{location}.{field_name}[{index}]", errors, alternative=True)
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
        elif isinstance(role_item.get("predicate"), str) and role_item.get("predicate") in all_ids:
            predicate_id = role_item.get("predicate")
            _require_ref_kind(predicate_id, objects, {"word"}, f"{location}.semantic_roles[{index}].predicate", errors, "semantic role predicate")
            predicate_object = objects.get(predicate_id, {})
            if predicate_object.get("lexical_category") not in {"verb", "auxiliary", "modal"}:
                _error(errors, f"{location}.semantic_roles[{index}].predicate", "semantic role predicate word must be verbal")

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
            if status == "unambiguous" and len(ambiguity_analyses) > 1:
                _error(errors, location, "unambiguous records cannot list competing analyses")
            preferred_id = ambiguity.get("preferred_analysis")
            ambiguity_ids = {
                item.get("id") for item in ambiguity_analyses
                if isinstance(item, dict) and isinstance(item.get("id"), str)
            }
            if status == "multiple_established_analyses_with_preferred_reading" and (len(ambiguity_analyses) < 2 or not isinstance(preferred_id, str) or preferred_id not in ambiguity_ids):
                _error(errors, location, "multiple established analyses require two analyses and a preferred_analysis id")
            for index, item in enumerate(ambiguity_analyses):
                if not isinstance(item, dict) or not item.get("id") or not isinstance(item.get("structural_claims"), list) or not item.get("interpretation"):
                    _error(errors, f"{location}.ambiguity.analyses[{index}]", "ambiguity analysis requires id, structural_claims, and interpretation")
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
            valency_predicates = {
                item.get("predicate") for item in record["lexical_valency"]
                if isinstance(item, dict) and isinstance(item.get("predicate"), str)
            }
            if signature["predicate_lemma"] not in valency_predicates:
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
            elif metadata.get("review_status") == "canonical_gold":
                errors.append(f"{benchmark_path}:{benchmark_line} record {benchmark_record.get('id')!r}: benchmark cannot claim canonical_gold before independent linguistic review")
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
    parser.add_argument("--schema", type=Path, default=Path("schemas/gold_annotation.schema.json"), help="JSON Schema document to require alongside semantic checks")
    parser.add_argument("--expected-split", choices=tuple(SPLITS), help="require every canonical input record to use this split")
    arguments = parser.parse_args()
    try:
        with arguments.schema.open(encoding="utf-8") as schema_handle:
            schema_document = json.load(schema_handle)
        if schema_document.get("$id") != "https://english-syntax-tutor.local/schema/gold-annotation-0.2.json":
            raise ValueError("unexpected gold schema $id")
    except (OSError, json.JSONDecodeError, ValueError, AttributeError) as error:
        print(f"Schema check failed: {error}", file=sys.stderr)
        return 1
    paths = arguments.paths or [Path("data/gold"), Path("data/reviewed")]
    errors = validate_files(paths, arguments.benchmark, arguments.schema)
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
