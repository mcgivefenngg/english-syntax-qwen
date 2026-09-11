from __future__ import annotations

from collections import Counter
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


def fusion_relation_issues(
    record: dict[str, Any], value: Any, *, id_occurrences: dict[str, int] | None = None,
) -> tuple[str, ...]:
    if not isinstance(value, dict):
        return ("fusion relation must be an object",)
    objects = {}
    for field in ("words", "constituents", "clauses"):
        values = record.get(field)
        if isinstance(values, list):
            objects.update((item["id"], item) for item in values if isinstance(item, dict) and isinstance(item.get("id"), str))
    clauses = record.get("clauses")
    clause_ids = {item["id"] for item in clauses if isinstance(item, dict) and isinstance(item.get("id"), str)} if isinstance(clauses, list) else set()
    if id_occurrences is None:
        items = record.get("fusion_relations")
        id_occurrences = Counter(item["id"] for item in items if isinstance(item, dict) and isinstance(item.get("id"), str)) if isinstance(items, list) else {}
    issues = []
    if not isinstance(value.get("id"), str) or not value["id"] or value.get("type") != "fused_relative":
        issues.append("fusion relation requires id and fused_relative type")
    if isinstance(value.get("id"), str) and id_occurrences.get(value["id"], 0) > 1:
        issues.append("duplicate fusion relation id")
    functions = value.get("fused_functions")
    if not isinstance(functions, list) or len(functions) < 2 or not all(isinstance(function, str) and function for function in functions):
        issues.append("fusion fused_functions requires at least two non-empty strings")
    for field, kinds in (("fused_element", {"word"}), ("whole_constituent", {"phrase", "clause"})):
        reference = value.get(field)
        if not isinstance(reference, str) or reference not in objects:
            issues.append(f"{field} must reference a known ID")
        elif objects[reference].get("node_kind") not in kinds:
            issues.append(f"fusion.{field} must reference {', '.join(sorted(kinds))}; got {reference!r} ({objects[reference].get('node_kind') or 'unknown'})")
    if not isinstance(value.get("relative_clause"), str) or value["relative_clause"] not in clause_ids:
        issues.append("relative_clause must reference a known clause")
    dependency = value.get("dependency")
    if dependency is not None:
        if not isinstance(dependency, dict) or not dependency.get("relation") or any(not isinstance(dependency.get(field), str) or dependency[field] not in objects for field in ("head", "dependent")):
            issues.append("fusion dependency must reference known IDs")
        else:
            for field in ("head", "dependent"):
                if objects[dependency[field]].get("node_kind") not in {"word", "phrase", "clause"}:
                    issues.append(f"fusion dependency {field} must reference clause, phrase, word")
    return tuple(issues)


def fusion_relation_status(record: dict[str, Any], value: Any, *, id_occurrences: dict[str, int] | None = None) -> str:
    return "resolved" if not fusion_relation_issues(record, value, id_occurrences=id_occurrences) else "missing"
