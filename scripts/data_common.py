"""Shared deterministic helpers for the annotation and rendering pipelines."""

from __future__ import annotations

import json
import re
import string
import unicodedata
from pathlib import Path
from typing import Any, Iterable


CAPABILITY_TAGS = {
    "basic_constituency", "clause_structure", "pos", "phrase_category", "syntactic_function",
    "complement_adjunct", "lexical_valency", "relative_clause", "fused_relative",
    "interrogative_clause", "nonfinite_clause", "gerund_participial", "infinitival",
    "control", "raising", "ecm", "perception_construction", "secondary_predication",
    "predicative_complement", "pp_attachment", "ambiguity", "coordination",
    "semantic_roles", "framework_distinction", "error_diagnosis",
}
FRAMEWORKS = {
    "cgel_inspired", "CGEL", "traditional_pedagogical", "modern_descriptive",
    "universal_dependencies", "UD", "penn_treebank", "PTB", "generative", "generative_grammar", "other_established", "mixed",
}
CANONICAL_FRAMEWORK = "cgel_inspired"
SPLITS = {"train", "validation", "benchmark"}
SCHEMA_VERSIONS = {"0.1", "0.2", "0.4"}
CANONICAL_SCHEMA_VERSION = "0.4"
LEGACY_SCHEMA_VERSIONS = {"0.1", "0.2", "0.3"}
LEXICAL_CATEGORIES = {
    "noun", "verb", "adjective", "adverb", "preposition", "determinative", "pronoun",
    "coordinator", "subordinator", "auxiliary", "modal", "particle", "numeral",
    "interjection", "punctuation",
}
PHRASE_CATEGORIES = {"NP", "VP", "PP", "AdjP", "AdvP", "DetP", "CoordP", "ComparativeP", "marker", "word"}
FUNCTIONS = {
    "subject", "object", "indirect_object", "predicative_complement", "subject_predicative_complement",
    "object_predicative_complement", "selected_locative_complement", "selected_complement",
    "complement", "adjunct", "adverbial", "supplementary_adverbial", "relative_modifier",
    "determiner", "marker", "coordinate", "extraposed_subject", "predicand", "head",
}
DIFFICULTIES = {"foundation", "intermediate", "advanced", "expert"}
SENTENCE_TYPES = {"declarative", "interrogative", "exclamative", "imperative", "fragment"}
SENTENCE_CLASSIFICATION_LABELS = {"simple", "compound", "complex"}
SOURCE_TYPES = {"authored", "legacy_baseline", "minimal_pair", "contrast_set", "error_diagnosis", "adapted_public_domain"}
SEMANTIC_ROLES = {
    "Agent", "Patient", "Theme", "Experiencer", "Stimulus", "Recipient", "Beneficiary",
    "Location", "Goal", "Source", "Instrument", "Cause", "Possessor", "Attribute",
    "Result", "State", "Support", "Time", "Purpose", "Proposition", "Addressee",
    "Classification", "Temporal/Aspectual", "OTHER", "UNSPECIFIED",
}
CLAUSE_CONSTRUCTIONS = {
    "declarative", "interrogative", "relative", "exclamative", "content",
    "conditional", "comparative", "coordinate", "other", "unresolved",
}
# Backwards-compatible import name used by older tooling. New V0.4 records
# use clause_construction rather than clause_type.
CLAUSE_TYPES = CLAUSE_CONSTRUCTIONS | {"matrix", "declarative_content"}
# Retained only so the V0.1/V0.2 reader can report legacy records during migration.
CLAUSE_CATEGORIES = {
    "main_clause", "finite_clause", "nonfinite_clause", "relative_clause", "interrogative_clause",
    "gerund_participial_clause", "infinitival_clause", "comparative_clause", "supplementary_clause",
}
CLAUSE_INTEGRATIONS = {"root", "subordinate", "supplementary", "coordinate_member", "unresolved"}
CLAUSE_STATUSES = CLAUSE_INTEGRATIONS | {"supplement"}
CLAUSE_FINITE_VALUES = {"finite", "nonfinite", "verbless", "unspecified"}
CLAUSE_FORMS = {"to_infinitival", "bare_infinitival", "gerund_participial", "past_participial", "unspecified"}
ANNOTATION_COVERAGES = {"complete_constituency", "task_focused_partial"}
ANNOTATED_DIMENSIONS = {
    "tokens", "lexical_category", "phrase_constituency", "constituency", "clause_ontology", "clause_structure",
    "syntactic_function", "vp_complementation", "np_internal_constituency", "dependencies", "semantic_roles",
    "lexical_valency", "framework_mapping", "construction_relations",
}
NODE_KINDS = {"word", "phrase", "clause"}
AMBIGUITY_STATUSES = {
    "unambiguous", "genuinely_ambiguous", "multiple_established_analyses_with_preferred_reading",
}


def read_jsonl(path: Path) -> list[tuple[int, dict[str, Any]]]:
    rows: list[tuple[int, dict[str, Any]]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"{path}:{line_number}: invalid JSON: {error.msg}") from error
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number}: JSON value must be an object")
            rows.append((line_number, value))
    return rows


def iter_jsonl_paths(paths: Iterable[Path]) -> list[Path]:
    expanded: list[Path] = []
    for path in paths:
        if path.is_dir():
            expanded.extend(sorted(path.rglob("*.jsonl")))
        elif path.exists():
            expanded.append(path)
    return expanded


def normalized_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    text = text.translate(str.maketrans({char: " " for char in string.punctuation}))
    text = "".join(" " if unicodedata.category(char).startswith("P") else char for char in text)
    return " ".join(text.split())


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+(?:['’][a-z0-9]+)?", normalized_text(text))


SURFACE_TOKEN_PATTERN = re.compile(r"\w+(?:['’]\w+)?|[^\w\s]", re.UNICODE)


def surface_tokens(text: str) -> list[str]:
    """Tokenize sentence text using the V0.4 surface convention.

    Words and punctuation are both tokens.  Apostrophes internal to a word
    remain part of that token; all other punctuation is a separate token.
    """
    return SURFACE_TOKEN_PATTERN.findall(unicodedata.normalize("NFKC", text))


def normalized_surface_tokens(text: str) -> list[str]:
    return [token.casefold() for token in surface_tokens(text)]


def sentence_word_alignment(record: dict[str, Any]) -> tuple[list[str], list[str]]:
    sentence = record.get("sentence")
    words = record.get("words")
    sentence_tokens = surface_tokens(sentence) if isinstance(sentence, str) else []
    word_tokens = [word.get("form", "") for word in words] if isinstance(words, list) and all(isinstance(word, dict) for word in words) else []
    return sentence_tokens, word_tokens


def extract_texts(record: dict[str, Any]) -> list[str]:
    """Return all user-visible text, supporting gold and rendered records."""
    values: list[str] = []
    if isinstance(record.get("sentence"), str):
        values.append(record["sentence"])
    messages = record.get("messages")
    if isinstance(messages, list):
        for message in messages:
            if not isinstance(message, dict):
                continue
            content = message.get("content")
            if isinstance(content, str):
                values.append(content)
            elif isinstance(content, list):
                values.extend(item.get("text", "") for item in content if isinstance(item, dict) and isinstance(item.get("text"), str))
    return values


def sentence_from_record(record: dict[str, Any]) -> str | None:
    if isinstance(record.get("sentence"), str):
        return record["sentence"]
    for text in extract_texts(record):
        match = re.search(r"(?:sentence|example)\s*:\s*(.+?)(?:\n|$)", text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def levenshtein(left: list[str], right: list[str]) -> int:
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for left_index, left_token in enumerate(left, 1):
        current = [left_index]
        for right_index, right_token in enumerate(right, 1):
            current.append(min(current[-1] + 1, previous[right_index] + 1, previous[right_index - 1] + (left_token != right_token)))
        previous = current
    return previous[-1]


def lexical_overlap(left: str, right: str) -> float:
    left_set, right_set = set(tokens(left)), set(tokens(right))
    if not left_set or not right_set:
        return 0.0
    return len(left_set & right_set) / len(left_set | right_set)


def skeleton(text: str) -> tuple[str, ...]:
    stopwords = {"a", "an", "the", "to", "of", "on", "in", "at", "by", "for", "with", "from", "that", "who", "which", "what", "he", "she", "him", "her", "it", "i", "we", "they", "was", "were", "is", "are", "be", "been", "being", "did", "do", "does", "and", "or", "but", "if", "as", "than"}
    return tuple(token if token in stopwords else "<LEX>" for token in tokens(text))


def construction_signature(record: dict[str, Any]) -> dict[str, Any] | None:
    """Return a construction signature independent of record-local IDs.

    Explicit signatures may use local constituent IDs for convenience.  Before
    contamination comparison those IDs are replaced with stable category and
    function descriptors, so renaming ``obj`` or ``pp`` cannot evade a match.
    """
    explicit = record.get("construction_signature")
    if isinstance(explicit, dict):
        signature = dict(explicit)
        objects: dict[str, dict[str, Any]] = {}
        for collection in (record.get("words", []), record.get("constituents", []), record.get("clauses", [])):
            if isinstance(collection, list):
                for item in collection:
                    if isinstance(item, dict) and isinstance(item.get("id"), str):
                        objects[item["id"]] = item

        def stable_value(value: Any, field: str) -> Any:
            if not isinstance(value, str) or value not in objects:
                return value
            item = objects[value]
            if item.get("node_kind") == "word":
                return f"word:{item.get('lexical_category', 'unknown')}"
            if item.get("node_kind") == "phrase":
                category = item.get("phrase_category", item.get("category", "unknown"))
                return f"phrase:{category}:{item.get('function', 'unspecified')}"
            clause_type = item.get("clause_construction", item.get("clause_type", item.get("clause_category", item.get("category", "unknown"))))
            return f"clause:{clause_type}:unspecified"

        for field in ("argument_pattern", "function_pattern"):
            values = signature.get(field)
            if isinstance(values, list):
                signature[field] = [stable_value(value, field) for value in values]
        return signature
    messages = record.get("messages")
    if isinstance(messages, list):
        for message in messages:
            if not isinstance(message, dict) or message.get("role") != "assistant" or not isinstance(message.get("content"), str):
                continue
            try:
                rendered = json.loads(message["content"])
            except json.JSONDecodeError:
                continue
            if isinstance(rendered, dict) and isinstance(rendered.get("construction_signature"), dict):
                return rendered["construction_signature"]
    valencies = record.get("lexical_valency")
    if not isinstance(valencies, list) or len(valencies) != 1 or not isinstance(valencies[0], dict):
        return None
    valency = valencies[0]
    predicate = valency.get("predicate")
    frame = valency.get("frame")
    selected = valency.get("selected_complements")
    if not all(isinstance(value, str) and value for value in (predicate, frame)) or not isinstance(selected, list):
        return None
    arguments = [value for value in selected if isinstance(value, str) and value]
    if not arguments:
        return None
    objects = {}
    for collection in (record.get("words", []), record.get("constituents", []), record.get("clauses", [])):
        if isinstance(collection, list):
            for item in collection:
                if isinstance(item, dict) and isinstance(item.get("id"), str):
                    objects[item["id"]] = item
    argument_pattern: list[str] = []
    function_pattern: list[str] = []
    for argument in arguments:
        item = objects.get(argument, {})
        if item.get("node_kind") == "phrase":
            argument_pattern.append(f"phrase:{item.get('phrase_category', 'unknown')}")
            function_pattern.append(str(item.get("function", "unspecified")))
        elif item.get("node_kind") == "clause":
            argument_pattern.append(f"clause:{item.get('clause_construction', item.get('clause_type', item.get('clause_category', 'unknown')))}")
            function_pattern.append(str(item.get("function", "unspecified")))
        else:
            argument_pattern.append("unknown")
            function_pattern.append("unknown")
    return {
        "predicate_lemma": predicate,
        "construction_type": record.get("construction_type") or frame,
        "argument_pattern": argument_pattern,
        "function_pattern": function_pattern,
        "source": "derived_from_legacy_lexical_valency",
    }
