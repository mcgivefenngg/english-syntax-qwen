#!/usr/bin/env python3
"""Validate canonical English Syntax Tutor JSONL data.

The validator checks deterministic data-contract invariants. It deliberately does
not try to decide whether a linguist's preferred analysis is theoretically true.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    from data_common import (
        ALTERNATIVE_CONSTRUCTION_WHITELIST, AMBIGUITY_STATUSES, CAPABILITY_TAGS,
        CLAUSE_CATEGORIES, DIFFICULTIES, FRAMEWORKS, LEXICAL_CATEGORIES,
        PHRASE_CATEGORIES, SCHEMA_VERSIONS, SEMANTIC_ROLES, SENTENCE_CLASSIFICATION_LABELS, SENTENCE_TYPES,
        SOURCE_TYPES, SPLITS, construction_signature, iter_jsonl_paths, normalized_text,
        read_jsonl, sentence_from_record,
    )
except ImportError:
    from scripts.data_common import (
        ALTERNATIVE_CONSTRUCTION_WHITELIST, AMBIGUITY_STATUSES, CAPABILITY_TAGS,
        CLAUSE_CATEGORIES, DIFFICULTIES, FRAMEWORKS, LEXICAL_CATEGORIES,
        PHRASE_CATEGORIES, SCHEMA_VERSIONS, SEMANTIC_ROLES, SENTENCE_CLASSIFICATION_LABELS, SENTENCE_TYPES,
        SOURCE_TYPES, SPLITS, construction_signature, iter_jsonl_paths, normalized_text,
        read_jsonl, sentence_from_record,
    )


REQUIRED = {
    "schema_version", "id", "sentence", "capability_tags", "difficulty", "source_type",
    "framework", "sentence_type", "clauses", "constituents", "words", "dependencies",
    "explanation", "split",
}
ANALYSIS_LEVELS = {"lexical_category", "phrase_category", "syntactic_function", "clause_structure", "framework", "semantic_role", "span", "none"}


def _error(errors: list[str], location: str, message: str) -> None:
    errors.append(f"{location}: {message}")


def _is_v2(record: dict[str, Any]) -> bool:
    return record.get("schema_version") == "0.2"


def _valid_ref(value: Any, ids: set[str]) -> bool:
    return value is None or (isinstance(value, str) and value in ids)


def _validate_analysis(item: Any, location: str, errors: list[str], alternative: bool = False) -> None:
    if not isinstance(item, dict) or not item.get("label") or not isinstance(item.get("claims"), list) or not item.get("claims") or any(not isinstance(claim, str) or not claim for claim in item.get("claims", [])):
        _error(errors, location, "analysis requires a non-empty label and claims list")
        return
    if alternative:
        if item.get("framework") not in FRAMEWORKS:
            _error(errors, location, "alternative analysis must name a known framework")
        if item.get("status") != "established":
            _error(errors, location, "alternative analysis status must be 'established'")
        analysis_type = item.get("analysis_type")
        if analysis_type == "small_clause":
            construction = item.get("construction_type")
            if construction not in ALTERNATIVE_CONSTRUCTION_WHITELIST["small_clause"]:
                _error(errors, location, "small-clause alternatives require an approved construction-specific whitelist entry")


def _validate_predicand(value: Any, location: str, ids: set[str], version: str, errors: list[str]) -> None:
    if value is None:
        return
    if isinstance(value, str):
        if version == "0.2":
            _error(errors, location, "V0.2 predicand must be a structured object")
        elif value not in ids:
            _error(errors, location, "predicand must reference a known ID")
        return
    if not isinstance(value, dict) or value.get("kind") not in {"overt_constituent", "implicit_control", "discourse_inferred", "generic", "indeterminate"}:
        _error(errors, location, "predicand kind is invalid")
        return
    target = value.get("target")
    if value["kind"] in {"overt_constituent", "implicit_control"}:
        if not isinstance(target, str) or target not in ids:
            _error(errors, location, "overt_constituent and implicit_control predicands require a known target")
    elif target is not None and target not in ids:
        _error(errors, location, "predicand target must reference a known ID when supplied")


def validate_record(record: dict[str, Any], location: str) -> list[str]:
    errors: list[str] = []
    if "messages" in record and "schema_version" not in record:
        messages = record.get("messages")
        if not isinstance(record.get("id"), str) or not record["id"]:
            _error(errors, location, "rendered record id must be a non-empty string")
        if not isinstance(messages, list) or [message.get("role") for message in messages if isinstance(message, dict)] != ["system", "user", "assistant"]:
            _error(errors, location, "rendered messages must contain system, user, assistant in order")
        else:
            for index, message in enumerate(messages):
                if not isinstance(message.get("content"), str) or not message["content"]:
                    _error(errors, f"{location}.messages[{index}]", "message content must be a non-empty string")
        return errors
    missing = REQUIRED - record.keys()
    for field in sorted(missing):
        _error(errors, location, f"missing required field {field!r}")
    if missing:
        return errors
    version = record["schema_version"]
    if version not in SCHEMA_VERSIONS:
        _error(errors, location, "schema_version must be '0.1' or '0.2'")
    if not isinstance(record["id"], str) or not record["id"]:
        _error(errors, location, "id must be a non-empty string")
    if not isinstance(record["sentence"], str) or not record["sentence"].strip():
        _error(errors, location, "sentence must be a non-empty string")
    tags = record["capability_tags"]
    if not isinstance(tags, list) or not tags or any(tag not in CAPABILITY_TAGS for tag in tags):
        _error(errors, location, "capability_tags must contain only known, non-empty tags")
    if isinstance(tags, list) and all(isinstance(tag, str) for tag in tags) and len(tags) != len(set(tags)):
        _error(errors, location, "capability_tags must be unique")
    if record["difficulty"] not in DIFFICULTIES:
        _error(errors, location, f"invalid difficulty {record['difficulty']!r}")
    if record["source_type"] not in SOURCE_TYPES:
        _error(errors, location, f"invalid source_type {record['source_type']!r}")
    framework = record["framework"]
    if not isinstance(framework, dict) or framework.get("preferred") not in FRAMEWORKS:
        _error(errors, location, "framework.preferred must be a known framework")
    else:
        alternatives = framework.get("alternatives", [])
        if not isinstance(alternatives, list):
            _error(errors, location, "framework.alternatives must be an array")
        else:
            for index, item in enumerate(alternatives):
                if not isinstance(item, dict) or item.get("framework") not in FRAMEWORKS or item.get("status") != "established" or not item.get("analysis"):
                    _error(errors, f"{location}.framework.alternatives[{index}]", "framework alternative must name an established framework and analysis")
    if record["sentence_type"] not in SENTENCE_TYPES:
        _error(errors, location, f"invalid sentence_type {record['sentence_type']!r}")
    metadata = record.get("sentence_type_metadata")
    if metadata is not None and (not isinstance(metadata, dict) or not isinstance(metadata.get("scheme"), str) or not metadata["scheme"]):
        _error(errors, location, "sentence_type_metadata.scheme must be a non-empty string")
    classification = record.get("sentence_classification")
    if classification is not None and (not isinstance(classification, dict) or classification.get("label") not in SENTENCE_CLASSIFICATION_LABELS or not isinstance(classification.get("scheme"), str) or not classification["scheme"]):
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
        if word.get("id") in word_ids:
            _error(errors, word_location, f"duplicate word id {word.get('id')!r}")
        word_ids.add(word.get("id"))
        if word.get("lexical_category") not in LEXICAL_CATEGORIES:
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
            if not isinstance(item.get("function"), str) or not item.get("function"):
                _error(errors, item_location, "function must be a non-empty string")
            if field_name == "constituents":
                constituent_category = item.get("phrase_category") or item.get("category")
                if _is_v2(record):
                    if item.get("node_kind") not in {"phrase", "clause", "word"}:
                        _error(errors, item_location, "V0.2 constituents require node_kind phrase, clause, or word")
                    if item.get("node_kind") == "phrase":
                        if item.get("phrase_category") not in PHRASE_CATEGORIES:
                            _error(errors, item_location, "phrase nodes require a valid phrase category in phrase_category; Clause is not a phrase category")
                        if item.get("phrase_category") == "word":
                            _error(errors, item_location, "word category requires node_kind='word', not a phrase node")
                        if "category" in item:
                            _error(errors, item_location, "V0.2 phrase nodes must use phrase_category; category is a V0.1 compatibility field")
                    elif item.get("node_kind") == "clause":
                        if item.get("clause_ref") not in {clause.get("id") for clause in clause_items if isinstance(clause, dict)}:
                            _error(errors, item_location, "clause node must reference a known clause with clause_ref")
                        if item.get("phrase_category") is not None or item.get("category") is not None:
                            _error(errors, item_location, "clause nodes must use clause_ref, not phrase/category")
                    elif item.get("node_kind") == "word" and any(key in item for key in ("phrase_category", "category", "clause_ref")):
                        _error(errors, item_location, "word nodes must use the words collection, not phrase/clause category fields")
                elif item.get("category") not in PHRASE_CATEGORIES | {"Clause"}:
                    _error(errors, item_location, "unknown phrase category")
                if constituent_category == "PP" and item.get("function") == "AdvP":
                    _error(errors, item_location, "PP is a phrase category; AdvP is not a syntactic function")
                if constituent_category == "AdvP" and item.get("function") in {"selected_locative_complement", "predicative_complement"}:
                    _error(errors, item_location, "AdvP cannot be used to disguise a selected PP complement")
                if _is_v2(record) and "role" in item:
                    _error(errors, item_location, "V0.2 semantic roles belong in semantic_roles, not constituent.role")
            else:
                category = item.get("clause_category") or item.get("category")
                if _is_v2(record):
                    if item.get("node_kind") != "clause":
                        _error(errors, item_location, "V0.2 clause entries require node_kind='clause'")
                    if item.get("clause_category") not in CLAUSE_CATEGORIES:
                        _error(errors, item_location, "V0.2 clauses require clause_category")
                    if "category" in item:
                        _error(errors, item_location, "V0.2 clauses must use clause_category; category is a V0.1 compatibility field")
                elif category not in CLAUSE_CATEGORIES:
                    _error(errors, item_location, "unknown clause category")
                if item.get("finiteness") not in {"finite", "non-finite"}:
                    _error(errors, item_location, "finiteness must be finite or non-finite")
                if item.get("finiteness") == "finite" and category in {"nonfinite_clause", "gerund_participial_clause", "infinitival_clause"}:
                    _error(errors, item_location, "non-finite clause category cannot be marked finite")
                for ref_field in ("subject", "head"):
                    if ref_field in item and not _valid_ref(item.get(ref_field), all_ids):
                        _error(errors, item_location, f"{ref_field} must reference a known ID")
                _validate_predicand(item.get("predicand"), f"{item_location}.predicand", all_ids, version, errors)

    dependencies = record["dependencies"] if isinstance(record["dependencies"], list) else []
    if not isinstance(record["dependencies"], list):
        _error(errors, location, "dependencies must be a list")
    for index, dependency in enumerate(dependencies):
        if not isinstance(dependency, dict) or not dependency.get("relation") or dependency.get("head") not in all_ids or dependency.get("dependent") not in all_ids:
            _error(errors, f"{location}.dependencies[{index}]", "dependency must reference known IDs")
    for field_name in ("complements", "adjuncts"):
        values = record.get(field_name)
        if values is not None and (not isinstance(values, list) or any(value not in ids for value in values)):
            _error(errors, location, f"{field_name} must be a list of constituent/clause IDs")
    heads = record.get("heads")
    if heads is not None and (not isinstance(heads, list) or any(not isinstance(item, dict) or item.get("head") not in all_ids or item.get("dependent") not in all_ids for item in heads)):
        _error(errors, location, "heads must contain references to known IDs")

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
        if not isinstance(role_item, dict) or role_item.get("constituent") not in ids or role_item.get("role") not in SEMANTIC_ROLES:
            _error(errors, f"{location}.semantic_roles[{index}]", "semantic role must reference a constituent and use the controlled vocabulary")

    fusion_items = record.get("fusion_relations", [])
    if fusion_items is not None:
        if not isinstance(fusion_items, list):
            _error(errors, location, "fusion_relations must be an array")
        else:
            fusion_ids: set[str] = set()
            clause_ids = {clause.get("id") for clause in clause_items if isinstance(clause, dict)}
            for index, fusion in enumerate(fusion_items):
                fusion_location = f"{location}.fusion_relations[{index}]"
                if not isinstance(fusion, dict):
                    _error(errors, fusion_location, "fusion relation must be an object")
                    continue
                if fusion.get("id") in fusion_ids:
                    _error(errors, fusion_location, "duplicate fusion relation id")
                fusion_ids.add(fusion.get("id"))
                for field in ("fused_element", "whole_constituent"):
                    if fusion.get(field) not in all_ids:
                        _error(errors, fusion_location, f"{field} must reference a known ID")
                if fusion.get("relative_clause") not in clause_ids:
                    _error(errors, fusion_location, "relative_clause must reference a known clause")
                dependency = fusion.get("dependency")
                if dependency is not None and (not isinstance(dependency, dict) or dependency.get("head") not in all_ids or dependency.get("dependent") not in all_ids or not dependency.get("relation")):
                    _error(errors, fusion_location, "fusion dependency must reference known IDs")

    ambiguity = record.get("ambiguity")
    if ambiguity is not None:
        if not isinstance(ambiguity, dict) or ambiguity.get("status") not in AMBIGUITY_STATUSES or not isinstance(ambiguity.get("analyses"), list):
            _error(errors, location, "ambiguity requires a known status and analyses array")
        else:
            status = ambiguity["status"]
            ambiguity_analyses = ambiguity["analyses"]
            if status == "genuinely_ambiguous" and len(ambiguity_analyses) < 2:
                _error(errors, location, "genuinely_ambiguous requires at least two structural analyses")
            if status == "unambiguous" and len(ambiguity_analyses) > 1:
                _error(errors, location, "unambiguous records cannot list competing analyses")
            preferred_id = ambiguity.get("preferred_analysis")
            if status == "multiple_established_analyses_with_preferred_reading" and (len(ambiguity_analyses) < 2 or preferred_id not in {item.get("id") for item in ambiguity_analyses if isinstance(item, dict)}):
                _error(errors, location, "multiple established analyses require two analyses and a preferred_analysis id")
            for index, item in enumerate(ambiguity_analyses):
                if not isinstance(item, dict) or not item.get("id") or not isinstance(item.get("structural_claims"), list) or not item.get("interpretation"):
                    _error(errors, f"{location}.ambiguity.analyses[{index}]", "ambiguity analysis requires id, structural_claims, and interpretation")

    signature = record.get("construction_signature")
    if signature is not None:
        if not isinstance(signature, dict) or not all(isinstance(signature.get(field), str) and signature[field] for field in ("predicate_lemma", "construction_type")) or not isinstance(signature.get("argument_pattern"), list) or not isinstance(signature.get("function_pattern"), list) or not signature["argument_pattern"] or not signature["function_pattern"]:
            _error(errors, location, "construction_signature requires predicate_lemma, construction_type, argument_pattern, and function_pattern")
        elif len(signature["argument_pattern"]) != len(signature["function_pattern"]):
            _error(errors, location, "construction_signature argument_pattern and function_pattern must have equal lengths")
        elif record.get("construction_type") is not None and record.get("construction_type") != signature["construction_type"]:
            _error(errors, location, "construction_signature construction_type must agree with construction_type")
        elif isinstance(record.get("lexical_valency"), list) and record["lexical_valency"] and signature["predicate_lemma"] not in {item.get("predicate") for item in record["lexical_valency"] if isinstance(item, dict)}:
            _error(errors, location, "construction_signature predicate_lemma must agree with lexical_valency")

    if not isinstance(record["explanation"], str) or not record["explanation"].strip():
        _error(errors, location, "explanation must be non-empty")
    if record["split"] not in SPLITS:
        _error(errors, location, f"invalid split {record['split']!r}")
    diagnosis = record.get("error_diagnosis")
    if diagnosis is not None:
        if not isinstance(diagnosis, dict) or not diagnosis.get("student_analysis") or not isinstance(diagnosis.get("diagnoses"), list):
            _error(errors, location, "error_diagnosis requires student_analysis and diagnoses")
        else:
            for index, item in enumerate(diagnosis["diagnoses"]):
                if not isinstance(item, dict) or item.get("verdict") not in {"error", "acceptable_alternative", "correct"} or item.get("error_level") not in ANALYSIS_LEVELS or not item.get("claim") or not item.get("correct_analysis") or not item.get("why"):
                    _error(errors, f"{location}.error_diagnosis.diagnoses[{index}]", "malformed diagnosis")
    return errors


def _signature_key(record: dict[str, Any]) -> tuple[Any, ...] | None:
    signature = construction_signature(record)
    if not isinstance(signature, dict):
        return None
    if not isinstance(signature.get("argument_pattern"), list) or not isinstance(signature.get("function_pattern"), list):
        return None
    return (
        signature.get("predicate_lemma"), signature.get("construction_type"),
        tuple(signature.get("argument_pattern", [])), tuple(signature.get("function_pattern", [])),
    )


def validate_files(paths: list[Path], benchmark_path: Path | None = None) -> list[str]:
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
            errors.extend(validate_record(record, f"{path}:{line_number}"))
    seen_ids: dict[str, str] = {}
    seen_sentences: dict[str, str] = {}
    for path, line_number, record in all_records:
        location = f"{path}:{line_number}"
        identifier = record.get("id")
        if identifier in seen_ids:
            errors.append(f"{location}: duplicate id {identifier!r}; first seen at {seen_ids[identifier]}")
        else:
            seen_ids[identifier] = location
        sentence = record.get("sentence")
        if isinstance(sentence, str):
            key = normalized_text(sentence)
            if key in seen_sentences:
                errors.append(f"{location}: duplicate normalized sentence; first seen at {seen_sentences[key]}")
            else:
                seen_sentences[key] = location
    if benchmark_path and benchmark_path.exists():
        try:
            benchmark_rows = read_jsonl(benchmark_path)
        except ValueError as error:
            errors.append(str(error))
            benchmark_rows = []
        benchmark_ids = {row.get("id") for _, row in benchmark_rows}
        benchmark_sentences = {normalized_text(row.get("sentence", "")) for _, row in benchmark_rows if isinstance(row.get("sentence"), str)}
        benchmark_signatures = {_signature_key(row): (line, row.get("id")) for line, row in benchmark_rows if _signature_key(row) is not None}
        for benchmark_line, benchmark_record in benchmark_rows:
            if benchmark_record.get("split") != "benchmark":
                errors.append(f"{benchmark_path}:{benchmark_line}: benchmark records must use split='benchmark'")
        for path, line_number, record in all_records:
            if record.get("split") in {"train", "validation"} and record.get("id") in benchmark_ids:
                errors.append(f"{path}:{line_number}: benchmark id leaks into {record.get('split')}")
            if record.get("split") in {"train", "validation"} and record.get("source_type") == "legacy_baseline":
                errors.append(f"{path}:{line_number}: legacy_baseline is benchmark-only")
            candidate_sentence = sentence_from_record(record) or ""
            if record.get("split") in {"train", "validation"} and normalized_text(candidate_sentence) in benchmark_sentences:
                errors.append(f"{path}:{line_number}: benchmark sentence leaks into {record.get('split')}")
            key = _signature_key(record)
            if record.get("split") in {"train", "validation"} and key in benchmark_signatures and normalized_text(candidate_sentence) not in benchmark_sentences:
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
    errors = validate_files(paths, arguments.benchmark)
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
