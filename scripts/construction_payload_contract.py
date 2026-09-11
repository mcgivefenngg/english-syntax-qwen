from __future__ import annotations

from typing import Any

try:
    from collection_contract import normalize_predicate_reference
except ImportError:
    from scripts.collection_contract import normalize_predicate_reference


def _record_ids(record: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for field in ("words", "clauses", "constituents"):
        values = record.get(field)
        if isinstance(values, list):
            ids.update(item["id"] for item in values if isinstance(item, dict) and isinstance(item.get("id"), str))
    return ids


def construction_signature_issues(record: dict[str, Any], value: Any) -> tuple[str, ...]:
    if not isinstance(value, dict) or not all(isinstance(value.get(f), str) and value[f] for f in ("predicate_lemma", "construction_type")) or not all(isinstance(value.get(f), list) and value[f] and all(isinstance(x, str) and x for x in value[f]) for f in ("argument_pattern", "function_pattern")):
        return ("required",)
    if len(value["argument_pattern"]) != len(value["function_pattern"]):
        return ("length",)
    if any(item in _record_ids(record) for item in value["argument_pattern"] + value["function_pattern"]):
        return ("stable_descriptors",)
    if record.get("construction_type") is not None and record.get("construction_type") != value["construction_type"]:
        return ("construction_type",)
    valency = record.get("lexical_valency")
    if isinstance(valency, list) and valency:
        predicate = normalize_predicate_reference(record, value["predicate_lemma"])
        predicates = {normalize_predicate_reference(record, item.get("predicate")) for item in valency if isinstance(item, dict)}
        if predicate is None or predicate not in predicates:
            return ("predicate",)
    return ()


def construction_signature_status(record: dict[str, Any], value: Any) -> str:
    return "resolved" if not construction_signature_issues(record, value) else "missing"
