"""Shared fail-closed helpers for V0.4 migration and fixture repair."""

from __future__ import annotations

import copy
from typing import Any

try:
    from collection_contract import collection_item_in_scope, normalize_collection_item, validate_coverage_target
    from dimension_registry import DIMENSION_REGISTRY, dimension_spec
    from authoritative_payload import authoritative_payload, authoritative_payload_items
except ImportError:
    from scripts.collection_contract import collection_item_in_scope, normalize_collection_item, validate_coverage_target
    from scripts.dimension_registry import DIMENSION_REGISTRY, dimension_spec
    from scripts.authoritative_payload import authoritative_payload, authoritative_payload_items


_COMPLETENESS = {"complete", "partial", "unannotated", "omitted", "out_of_scope"}
_OMISSIONS = {"none", "intentional", "not_applicable"}
_EVIDENCE = {"present", "empty", "unannotated"}
_EXCLUDED_COMPLETENESS = {"unannotated", "omitted", "out_of_scope"}
_COLLECTION_COVERAGE_DIMENSIONS = {"dependencies", "semantic_roles", "lexical_valency"}
_COVERAGE_FIELDS = ("dimension", "scope", "completeness", "omission", "evidence", "notes")


def preserve_legacy(record: dict[str, Any], key: str, value: Any) -> None:
    if value is None or value == [] or value == {}:
        return
    legacy = record.get("legacy_annotations")
    if not isinstance(legacy, dict):
        legacy = {"previous": copy.deepcopy(legacy)} if legacy is not None else {}
        record["legacy_annotations"] = legacy
    previous = legacy.get(key)
    if previous is None:
        legacy[key] = copy.deepcopy(value)
    elif isinstance(previous, list) and isinstance(value, list):
        previous.extend(copy.deepcopy(value))
    else:
        legacy[key] = [copy.deepcopy(previous), copy.deepcopy(value)]


def coverage_entry_sort_key(entry: dict[str, Any]) -> tuple[Any, ...]:
    scope = entry.get("scope") if isinstance(entry.get("scope"), dict) else {}
    return (
        str(entry.get("dimension", "")),
        str(scope.get("kind", "")),
        str(scope.get("node", "")),
        str(scope.get("start", "")),
        str(scope.get("end", "")),
        str(entry.get("completeness", "")),
        str(entry.get("omission", "")),
        str(entry.get("evidence", "")),
    )


def sort_coverage_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(entries, key=coverage_entry_sort_key)


def retain_migrated_coverage_entry(entry: dict[str, Any]) -> bool:
    """Keep unresolved collection declarations explicit for quarantine."""
    return not (
        entry.get("completeness") == "unannotated"
        and entry.get("dimension") not in _COLLECTION_COVERAGE_DIMENSIONS
    )


def _record_objects(record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    objects: dict[str, dict[str, Any]] = {}
    for field in ("words", "constituents", "clauses"):
        values = record.get(field, [])
        if not isinstance(values, list):
            continue
        objects.update({
            value["id"]: value
            for value in values
            if isinstance(value, dict) and isinstance(value.get("id"), str) and value["id"]
        })
    return objects


def _scope_is_supported(record: dict[str, Any], dimension: str, scope: Any) -> bool:
    spec = dimension_spec(dimension)
    if spec is None or not isinstance(scope, dict):
        return False
    kind = scope.get("kind")
    if not isinstance(kind, str) or not spec.allows_scope(kind):
        return False
    if kind == "record":
        return set(scope) == {"kind"}
    if kind == "node":
        node = scope.get("node")
        objects = _record_objects(record)
        return (
            set(scope) == {"kind", "node"}
            and isinstance(node, str)
            and node in objects
            and isinstance(objects[node].get("node_kind"), str)
            and spec.allows_node(objects[node]["node_kind"])
            and validate_coverage_target(record, dimension, node).valid
        )
    words = record.get("words", [])
    start, end = scope.get("start"), scope.get("end")
    return (
        set(scope) == {"kind", "start", "end"}
        and type(start) is int
        and type(end) is int
        and start >= 0
        and end > start
        and isinstance(words, list)
        and end <= len(words)
    )


def _authoritative_payload_for_scope(
    record: dict[str, Any],
    dimension: str,
    scope: dict[str, Any],
) -> Any:
    target: str | dict[str, Any] | None
    if scope.get("kind") == "node":
        target = scope.get("node")
    elif scope.get("kind") == "region":
        target = scope
    else:
        target = None
    return authoritative_payload(record, dimension, target)


def _unannotated_entry(
    dimension: str,
    *,
    notes: str | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "dimension": dimension,
        "scope": {"kind": "record"},
        "completeness": "unannotated",
        "omission": "intentional",
        "evidence": "unannotated",
    }
    if notes:
        entry["notes"] = notes
    return entry


def canonicalize_coverage_entry(
    record: dict[str, Any],
    source: Any,
) -> tuple[dict[str, Any] | None, bool]:
    if not isinstance(source, dict):
        return None, True
    dimension = source.get("dimension")
    spec = dimension_spec(dimension)
    if spec is None:
        return None, True
    review_required = False
    if not _scope_is_supported(record, dimension, source.get("scope")):
        return _unannotated_entry(
            dimension,
            notes="Legacy scope is unsupported or has no deterministic owner; manual review is required.",
        ), True

    entry = {key: copy.deepcopy(source[key]) for key in _COVERAGE_FIELDS if key in source}
    entry["dimension"] = dimension
    entry["scope"] = copy.deepcopy(source["scope"])
    completeness = entry.get("completeness")
    omission = entry.get("omission")
    evidence = entry.get("evidence")
    invalid_evidence = False
    if completeness not in _COMPLETENESS:
        completeness = "unannotated"
        review_required = True
    if omission not in _OMISSIONS:
        omission = "none" if completeness not in _EXCLUDED_COMPLETENESS else "intentional"
        review_required = True
    if evidence not in _EVIDENCE and evidence is not None:
        evidence = None
        invalid_evidence = True
        review_required = True

    if completeness == "partial" and (
        not spec.allows_partial(entry["scope"]["kind"])
        or (
            entry["scope"]["kind"] == "record"
            and evidence == "present"
            and spec.partial_present_target_source is None
        )
    ):
        completeness = "unannotated"
        omission = "intentional"
        evidence = "unannotated"
        review_required = True

    if omission != "none" or completeness in _EXCLUDED_COMPLETENESS:
        if omission == "none":
            omission = "not_applicable" if completeness == "out_of_scope" else "intentional"
            review_required = True
        if evidence != "unannotated":
            review_required = True
        evidence = "unannotated"
        if completeness == "complete":
            completeness = "unannotated"
    elif evidence == "unannotated":
        omission = "intentional"
        if completeness == "complete":
            completeness = "unannotated"
    elif evidence == "empty":
        if completeness != "complete" or not spec.allows_confirmed_empty(entry["scope"]["kind"]):
            completeness = "unannotated"
            omission = "intentional"
            evidence = "unannotated"
            review_required = True
    elif evidence == "present":
        payload = _authoritative_payload_for_scope(record, dimension, entry["scope"])
        if not payload.has_resolved_content or (completeness == "complete" and not payload.fully_resolved):
            completeness = "unannotated"
            omission = "intentional"
            evidence = "unannotated"
            review_required = True
    else:
        completeness = "unannotated"
        omission = "intentional"
        evidence = "unannotated"
        review_required = True

    entry["completeness"] = completeness
    entry["omission"] = omission
    entry["evidence"] = evidence
    if not isinstance(entry.get("notes"), str):
        entry.pop("notes", None)
    return entry, review_required


def normalize_reference_collections(record: dict[str, Any]) -> bool:
    review_required = False
    for dimension, spec in DIMENSION_REGISTRY.items():
        if spec.target_lemma_field is None or spec.content_field is None:
            continue
        values = record.get(spec.content_field)
        if values is None:
            continue
        if not isinstance(values, list):
            preserve_legacy(record, f"{spec.content_field}_invalid", values)
            record[spec.content_field] = []
            review_required = True
            continue
        normalized: list[Any] = []
        unresolved: list[Any] = []
        for item in values:
            if not isinstance(item, dict):
                unresolved.append(item)
                continue
            if spec.target_lemma_field not in item:
                if spec.target_lemma_optional:
                    normalized.append(copy.deepcopy(item))
                else:
                    unresolved.append(item)
                continue
            mapped = normalize_collection_item(record, dimension, item)
            if mapped is None:
                unresolved.append(item)
            else:
                normalized.append(mapped)
        if unresolved:
            preserve_legacy(record, f"{spec.content_field}_unresolved_references", unresolved)
            review_required = True
        record[spec.content_field] = normalized
    return review_required


def quarantine_uncovered_collection_content(
    record: dict[str, Any],
    dimensions: list[dict[str, Any]],
) -> bool:
    review_required = False
    fields: dict[str, list[str]] = {}
    for dimension, spec in DIMENSION_REGISTRY.items():
        if dimension in {"dependencies", "semantic_roles", "lexical_valency"} and spec.content_field is not None:
            fields.setdefault(spec.content_field, []).append(dimension)
    for field, field_dimensions in fields.items():
        if not any(entry.get("dimension") in field_dimensions for entry in dimensions):
            continue
        values = record.get(field)
        if values is None:
            continue
        if not isinstance(values, list):
            preserve_legacy(record, f"{field}_invalid", values)
            record[field] = []
            review_required = True
            continue
        covered: list[Any] = []
        uncovered: list[Any] = []
        entries = [
            entry for entry in dimensions
            if entry.get("dimension") in field_dimensions
        ]
        for item in values:
            owned = any(
                entry.get("omission") == "none"
                and entry.get("completeness") not in _EXCLUDED_COMPLETENESS
                and entry.get("evidence") == "present"
                and collection_item_in_scope(record, entry["dimension"], item, entry.get("scope"))
                for entry in entries
            )
            (covered if owned else uncovered).append(item)
        if uncovered:
            preserve_legacy(record, f"{field}_unscoped", uncovered)
            record[field] = covered
            review_required = True
    construction_items = authoritative_payload_items(record, "construction_relations")
    if construction_items:
        construction_entries = [
            entry for entry in dimensions
            if entry.get("dimension") == "construction_relations"
        ]
        covered_paths: set[tuple[str | int, ...]] = set()
        uncovered_by_field: dict[str, list[Any]] = {}
        for item in construction_items:
            covered = any(
                entry.get("scope", {}).get("kind") == "record"
                and entry.get("omission") == "none"
                and entry.get("completeness") not in _EXCLUDED_COMPLETENESS
                and entry.get("evidence") == "present"
                and item.status == "resolved"
                for entry in construction_entries
                if isinstance(entry.get("scope"), dict)
            )
            if covered:
                covered_paths.add(item.path)
            else:
                uncovered_by_field.setdefault(item.field, []).append(item.value)
                review_required = True

        for field, values in uncovered_by_field.items():
            if field == "construction_tags" and len(values) == 1:
                original = values[0]
            elif field in {"construction_signature", "construction_type"} and len(values) == 1:
                original = values[0]
            else:
                original = values
            preserve_legacy(record, f"{field}_unscoped", original)

        top_level_fields = {
            item.field for item in construction_items
            if item.field != "typed_relation"
        }
        for field in top_level_fields:
            values = [item for item in construction_items if item.field == field]
            if not values:
                continue
            current = record.get(field)
            if field == "construction_tags":
                if any(item.path in covered_paths for item in values):
                    record[field] = values[0].value
                else:
                    record[field] = []
            elif isinstance(current, list):
                record[field] = [
                    item.value for item in values
                    if item.path in covered_paths
                ]
            elif any(item.path in covered_paths for item in values):
                record[field] = next(item.value for item in values if item.path in covered_paths)
            else:
                record.pop(field, None)

        relation_groups: dict[tuple[str | int, ...], list[Any]] = {}
        for item in construction_items:
            if item.field != "typed_relation":
                continue
            relation_groups.setdefault(item.path[:-2], []).append(item)
        for group_path, values in relation_groups.items():
            parent: Any = record
            try:
                for key in group_path:
                    parent = parent[key]
            except (IndexError, KeyError, TypeError):
                continue
            if not isinstance(parent, dict):
                continue
            relations = parent.get("relations")
            if isinstance(relations, list):
                parent["relations"] = [
                    relation for index, relation in enumerate(relations)
                    if not any(
                        item.path == group_path + ("relations", index)
                        and item.path not in covered_paths
                        for item in values
                    )
                ]
            elif any(item.path not in covered_paths for item in values):
                parent.pop("relations", None)
    return review_required


def validate_canonical_record(record: dict[str, Any], location: str) -> None:
    try:
        from validate_dataset import validate_record
    except ImportError:
        from scripts.validate_dataset import validate_record
    errors = validate_record(record, location)
    if errors:
        raise ValueError(f"{location}: canonical V0.4 validation failed: {'; '.join(errors)}")
