"""Shared fail-closed helpers for V0.4 migration and fixture repair."""

from __future__ import annotations

import copy
from typing import Any

try:
    from collection_contract import collection_item_in_scope, normalize_collection_item, validate_coverage_target
    from dimension_registry import DIMENSION_REGISTRY, dimension_spec
    from authoritative_payload import (
        authoritative_payload,
        authoritative_payload_items,
        construction_typed_relation_types,
        typed_analysis_relation_entries,
        typed_argument_owner_dimensions,
        typed_relation_owner_dimensions,
    )
except ImportError:
    from scripts.collection_contract import collection_item_in_scope, normalize_collection_item, validate_coverage_target
    from scripts.dimension_registry import DIMENSION_REGISTRY, dimension_spec
    from scripts.authoritative_payload import (
        authoritative_payload,
        authoritative_payload_items,
        construction_typed_relation_types,
        typed_analysis_relation_entries,
        typed_argument_owner_dimensions,
        typed_relation_owner_dimensions,
    )


_COMPLETENESS = {"complete", "partial", "unannotated", "omitted", "out_of_scope"}
_OMISSIONS = {"none", "intentional", "not_applicable"}
_EVIDENCE = {"present", "empty", "unannotated"}
_EXCLUDED_COMPLETENESS = {"unannotated", "omitted", "out_of_scope"}
_COLLECTION_COVERAGE_DIMENSIONS = {"dependencies", "semantic_roles", "lexical_valency"}
_COVERAGE_FIELDS = ("dimension", "scope", "completeness", "omission", "evidence", "notes")
_NESTED_CONSTRUCTION_CONTAINERS = {
    "typed_relation": "relations",
    "typed_arguments": "arguments",
    "typed_entity": "entities",
}


def _analysis_referenced_entity_ids(relations: Any) -> set[str]:
    """Collect analysis-namespace entity ids referenced by the given relations."""
    referenced: set[str] = set()
    if not isinstance(relations, list):
        return referenced
    for relation in relations:
        if not isinstance(relation, dict):
            continue
        for key in ("source", "target"):
            reference = relation.get(key)
            if isinstance(reference, str) and ":" in reference:
                namespace, identifier = reference.split(":", 1)
            elif isinstance(reference, dict):
                namespace, identifier = reference.get("namespace"), reference.get("id")
            else:
                continue
            if namespace == "analysis" and isinstance(identifier, str) and identifier:
                referenced.add(identifier)
    return referenced


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
        protected_paths: set[tuple[str | int, ...]] = set()
        uncovered_by_field: dict[str, list[Any]] = {}
        shared_ownership_review = False

        def entry_covered(item: Any) -> bool:
            return any(
                entry.get("scope", {}).get("kind") == "record"
                and entry.get("omission") == "none"
                and entry.get("completeness") not in _EXCLUDED_COMPLETENESS
                and entry.get("evidence") == "present"
                and item.status == "resolved"
                for entry in construction_entries
                if isinstance(entry.get("scope"), dict)
            )

        positive_record_dimensions: set[str] = set()
        positive_scoped_dimensions: set[str] = set()
        for entry in dimensions:
            scope = entry.get("scope")
            if not isinstance(scope, dict):
                continue
            if (
                entry.get("omission") == "none"
                and entry.get("completeness") not in _EXCLUDED_COMPLETENESS
                and entry.get("evidence") == "present"
            ):
                if scope.get("kind") == "record":
                    positive_record_dimensions.add(entry.get("dimension"))
                elif scope.get("kind") in {"node", "region"}:
                    positive_scoped_dimensions.add(entry.get("dimension"))

        def owner_protection(owners: Any) -> str | None:
            if not owners:
                return None
            if owners & positive_record_dimensions:
                return "clean"
            if owners & positive_scoped_dimensions:
                return "review"
            return None

        covered_entity_refs: dict[tuple[str | int, ...], set[str]] = {}
        for item in construction_items:
            if item.field == "typed_entity":
                continue
            if entry_covered(item):
                covered_paths.add(item.path)
                if item.field == "typed_relation" and isinstance(item.value, dict) and len(item.path) >= 2:
                    covered_entity_refs.setdefault(item.path[:-2], set()).update(
                        _analysis_referenced_entity_ids([item.value])
                    )
                continue
            if item.field == "typed_arguments":
                protection = owner_protection(typed_argument_owner_dimensions(item.value))
                if protection == "clean" and item.status == "resolved":
                    protected_paths.add(item.path)
                    continue
                if protection is not None:
                    protected_paths.add(item.path)
                    shared_ownership_review = True
                    continue
            uncovered_by_field.setdefault(item.field, []).append(item.value)
            review_required = True

        entity_reference_states: dict[tuple[str | int, ...], dict[str, str]] = {}
        construction_relation_types = construction_typed_relation_types()
        for analysis_path, relation in typed_analysis_relation_entries(record):
            if relation.get("type") in construction_relation_types:
                continue
            references = _analysis_referenced_entity_ids([relation])
            if not references:
                continue
            protection = owner_protection(typed_relation_owner_dimensions(relation.get("type")))
            # Fail closed: the referencing relation survives construction
            # quarantine, so removing its target entity would create a dangling
            # canonical reference. Coverage from the owning dimension is still
            # required for clean protection; otherwise preserve with review.
            state = "clean" if protection == "clean" else "review"
            bucket = entity_reference_states.setdefault(analysis_path, {})
            for reference in references:
                if bucket.get(reference) != "clean":
                    bucket[reference] = state
        for item in construction_items:
            if item.field != "typed_entity":
                continue
            if entry_covered(item):
                covered_paths.add(item.path)
                continue
            analysis_path = item.path[:-2] if len(item.path) >= 2 and item.path[-2] == "entities" else item.path[:-1]
            if isinstance(item.value, dict) and item.value.get("id") in covered_entity_refs.get(analysis_path, set()):
                covered_paths.add(item.path)
                continue
            reference = item.value.get("id") if isinstance(item.value, dict) else None
            state = entity_reference_states.get(analysis_path, {}).get(reference) if isinstance(reference, str) else None
            if state == "clean":
                protected_paths.add(item.path)
                continue
            if state == "review":
                protected_paths.add(item.path)
                shared_ownership_review = True
                continue
            uncovered_by_field.setdefault(item.field, []).append(item.value)
            review_required = True
        if shared_ownership_review:
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
            if item.field not in {"typed_relation", "typed_arguments", "typed_entity"}
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

        nested_groups: dict[tuple[str | int, ...], tuple[tuple[str | int, ...], str, list[Any]]] = {}
        for item in construction_items:
            container_key = _NESTED_CONSTRUCTION_CONTAINERS.get(item.field)
            if container_key is None:
                continue
            if len(item.path) >= 2 and item.path[-2] == container_key:
                analysis_path = item.path[:-2]
            elif len(item.path) >= 1 and item.path[-1] == container_key:
                analysis_path = item.path[:-1]
            else:
                continue
            group = nested_groups.setdefault(analysis_path + (container_key,), (analysis_path, container_key, []))
            group[2].append(item)
        for analysis_path, container_key, values in nested_groups.values():
            parent: Any = record
            try:
                for key in analysis_path:
                    parent = parent[key]
            except (IndexError, KeyError, TypeError):
                continue
            if not isinstance(parent, dict):
                continue
            current = parent.get(container_key)
            uncovered_paths = {
                item.path for item in values
                if item.path not in covered_paths and item.path not in protected_paths
            }
            whole_container_path = analysis_path + (container_key,)
            if any(item.path == whole_container_path for item in values):
                if whole_container_path in uncovered_paths:
                    parent.pop(container_key, None)
                continue
            if isinstance(current, list):
                retained = [
                    value for index, value in enumerate(current)
                    if analysis_path + (container_key, index) not in uncovered_paths
                ]
                if retained or container_key != "arguments":
                    parent[container_key] = retained
                else:
                    parent.pop(container_key, None)
            elif isinstance(current, dict):
                retained = {
                    key: value for key, value in current.items()
                    if analysis_path + (container_key, key) not in uncovered_paths
                }
                if retained:
                    parent[container_key] = retained
                else:
                    parent.pop(container_key, None)
            elif uncovered_paths:
                parent.pop(container_key, None)
    return review_required


def validate_canonical_record(record: dict[str, Any], location: str) -> None:
    try:
        from validate_dataset import validate_record
    except ImportError:
        from scripts.validate_dataset import validate_record
    errors = validate_record(record, location)
    if errors:
        raise ValueError(f"{location}: canonical V0.4 validation failed: {'; '.join(errors)}")
