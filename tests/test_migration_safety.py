from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from scripts.data_common import read_jsonl
from scripts.migrate_v021 import migrate, migrate_file
from scripts.repair_v031_data import (
    REPAIR_VERSION,
    _repair_output_hash,
    repair_file,
    repair_record,
)
from scripts.validate_dataset import validate_record


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = read_jsonl(ROOT / "data" / "gold" / "fixtures.jsonl")[0][1]
DEPENDENCY = {"relation": "selected", "head": "w2", "dependent": "obj"}
ROLE = {"constituent": "obj", "role": "Theme", "predicate": "catalogue"}
VALENCY = {"predicate": "catalogue", "frame": "transitive", "selected_complements": ["obj"]}


def declaration(
    dimension: str,
    scope: dict[str, Any],
    completeness: str = "partial",
    omission: str = "none",
    evidence: str | None = None,
) -> dict[str, Any]:
    entry = {
        "dimension": dimension,
        "scope": scope,
        "completeness": completeness,
        "omission": omission,
    }
    if evidence is not None:
        entry["evidence"] = evidence
    return entry


class MigrationSafetyTests(unittest.TestCase):
    def legacy_record(self) -> dict[str, Any]:
        record = copy.deepcopy(FIXTURE)
        record["schema_version"] = "0.2"
        record.pop("migration_metadata", None)
        record.pop("legacy_annotation_scope", None)
        return record

    def migrate_with(self, entries: list[dict[str, Any]]) -> dict[str, Any]:
        record = self.legacy_record()
        record["annotation_scope"] = {"coverage": "task_focused_partial", "dimensions": entries}
        migrate(record)
        self.assertEqual(validate_record(record, "migrated-safety"), [])
        return record

    def test_global_dependency_content_does_not_create_scoped_present(self) -> None:
        record = self.legacy_record()
        record["dependencies"] = [DEPENDENCY]
        record["annotation_scope"] = {
            "coverage": "task_focused_partial",
            "dimensions": [declaration("dependencies", {"kind": "node", "node": "obj"})],
        }
        migrate(record)
        entry = next(item for item in record["annotation_scope"]["dimensions"] if item["dimension"] == "dependencies")
        self.assertEqual(entry["evidence"], "unannotated")
        self.assertNotEqual(entry["evidence"], "present")
        self.assertEqual(record["dependencies"], [])
        self.assertTrue(record["migration_review_required"])
        self.assertEqual(validate_record(record, "dependency-scope-safety"), [])

    def test_unsupported_dependency_node_and_region_scopes_require_review(self) -> None:
        for scope in ({"kind": "node", "node": "w2"}, {"kind": "region", "start": 0, "end": 2}):
            with self.subTest(scope=scope):
                record = self.legacy_record()
                record["dependencies"] = [DEPENDENCY]
                record["annotation_scope"] = {
                    "coverage": "task_focused_partial",
                    "dimensions": [declaration("dependencies", scope)],
                }
                migrate(record)
                entry = next(item for item in record["annotation_scope"]["dimensions"] if item["dimension"] == "dependencies")
                self.assertEqual((entry["scope"], entry["evidence"]), ({"kind": "record"}, "unannotated"))
                self.assertTrue(record["migration_review_required"])
                self.assertEqual(validate_record(record, "dependency-unsupported-scope"), [])

    def test_semantic_role_global_content_does_not_imply_scoped_ownership(self) -> None:
        record = self.legacy_record()
        record["semantic_roles"] = [ROLE]
        record["annotation_scope"] = {
            "coverage": "task_focused_partial",
            "dimensions": [declaration("semantic_roles", {"kind": "node", "node": "obj"})],
        }
        migrate(record)
        entry = next(item for item in record["annotation_scope"]["dimensions"] if item["dimension"] == "semantic_roles")
        self.assertEqual(entry["evidence"], "unannotated")
        self.assertEqual(record["semantic_roles"], [])
        self.assertIn("semantic_roles_unscoped", record["legacy_annotations"])
        self.assertEqual(validate_record(record, "role-scope-safety"), [])

    def test_lexical_valency_node_evidence_follows_deterministic_head(self) -> None:
        record = self.legacy_record()
        record["lexical_valency"] = [VALENCY]
        record["annotation_scope"] = {
            "coverage": "task_focused_partial",
            "dimensions": [declaration("lexical_valency", {"kind": "node", "node": "w2"}, evidence="present")],
        }
        migrate(record)
        entry = next(item for item in record["annotation_scope"]["dimensions"] if item["dimension"] == "lexical_valency")
        self.assertEqual(entry["evidence"], "present")
        self.assertEqual(record["lexical_valency"][0]["predicate"], "w2")
        self.assertEqual(validate_record(record, "valency-head-safety"), [])

    def test_selected_complement_does_not_grant_lexical_valency_ownership(self) -> None:
        record = self.legacy_record()
        record["lexical_valency"] = [VALENCY]
        record["annotation_scope"] = {
            "coverage": "task_focused_partial",
            "dimensions": [declaration("lexical_valency", {"kind": "node", "node": "w4"})],
        }
        migrate(record)
        entry = next(item for item in record["annotation_scope"]["dimensions"] if item["dimension"] == "lexical_valency")
        self.assertEqual(entry["evidence"], "unannotated")
        self.assertEqual(record["lexical_valency"], [])
        self.assertEqual(validate_record(record, "valency-complement-safety"), [])

    def test_missing_or_empty_collection_is_not_confirmed_empty(self) -> None:
        for missing in (True, False):
            with self.subTest(missing=missing):
                record = self.legacy_record()
                if missing:
                    record.pop("dependencies")
                else:
                    record["dependencies"] = []
                migrate(record)
                entry = next(item for item in record["annotation_scope"]["dimensions"] if item["dimension"] == "dependencies")
                self.assertEqual(entry["evidence"], "unannotated")
                self.assertNotEqual(entry["evidence"], "empty")
                self.assertEqual(validate_record(record, "missing-empty-safety"), [])

    def test_capability_tag_is_not_confirmed_empty(self) -> None:
        record = self.legacy_record()
        record["capability_tags"] = ["semantic_roles"]
        record.pop("semantic_roles", None)
        record.pop("annotation_scope", None)
        migrate(record)
        entry = next(item for item in record["annotation_scope"]["dimensions"] if item["dimension"] == "semantic_roles")
        self.assertEqual(entry["evidence"], "unannotated")
        self.assertNotEqual(entry["evidence"], "empty")
        self.assertEqual(validate_record(record, "capability-empty-safety"), [])

    def test_missing_evidence_does_not_use_global_collection_presence(self) -> None:
        cases = (
            ("dependencies", DEPENDENCY),
            ("semantic_roles", ROLE),
            ("lexical_valency", VALENCY),
        )
        for dimension, item in cases:
            with self.subTest(dimension=dimension):
                record = self.legacy_record()
                record[dimension] = [item]
                record["annotation_scope"] = {
                    "coverage": "task_focused_partial",
                    "dimensions": [declaration(dimension, {"kind": "record"})],
                }
                migrate(record)
                entry = next(item for item in record["annotation_scope"]["dimensions"] if item["dimension"] == dimension)
                self.assertEqual((entry["completeness"], entry["evidence"]), ("unannotated", "unannotated"))
                self.assertEqual(record[dimension], [])
                self.assertTrue(record["migration_review_required"])
                self.assertEqual(validate_record(record, f"missing-evidence-{dimension}"), [])

    def test_record_partial_dependency_missing_evidence_remains_unresolved(self) -> None:
        record = self.legacy_record()
        record["dependencies"] = [DEPENDENCY]
        record["annotation_scope"] = {
            "coverage": "task_focused_partial",
            "dimensions": [declaration("dependencies", {"kind": "record"}, completeness="partial")],
        }
        migrate(record)
        entry = next(item for item in record["annotation_scope"]["dimensions"] if item["dimension"] == "dependencies")
        self.assertEqual((entry["completeness"], entry["omission"], entry["evidence"]), ("unannotated", "intentional", "unannotated"))
        self.assertEqual(record["dependencies"], [])
        self.assertEqual(validate_record(record, "partial-missing-evidence"), [])

    def test_capability_tag_and_nonempty_collection_do_not_create_present(self) -> None:
        record = self.legacy_record()
        record["capability_tags"] = ["semantic_roles"]
        record["semantic_roles"] = [ROLE]
        record.pop("annotation_scope", None)
        migrate(record)
        entry = next(item for item in record["annotation_scope"]["dimensions"] if item["dimension"] == "semantic_roles")
        self.assertEqual(entry["evidence"], "unannotated")
        self.assertEqual(record["semantic_roles"], [])
        self.assertIn("semantic_roles_unscoped", record["legacy_annotations"])
        self.assertEqual(validate_record(record, "capability-content-safety"), [])

    def test_semantic_role_without_optional_predicate_is_preserved(self) -> None:
        for transform in (migrate, repair_record):
            with self.subTest(transform=transform.__name__):
                record = self.legacy_record() if transform is migrate else copy.deepcopy(FIXTURE)
                record["semantic_roles"] = [{"constituent": "obj", "role": "Theme"}]
                record["annotation_scope"] = {
                    "coverage": "task_focused_partial",
                    "dimensions": [declaration("semantic_roles", {"kind": "record"}, evidence="present")],
                }
                transform(record)
                self.assertEqual(record["semantic_roles"], [{"constituent": "obj", "role": "Theme"}])
                self.assertEqual(validate_record(record, f"optional-role-{transform.__name__}"), [])

    def test_semantic_role_predicate_unique_lemma_or_form_normalizes(self) -> None:
        for field, reference in (("lemma", "catalogue"), ("form", "catalogued")):
            for transform in (migrate, repair_record):
                with self.subTest(field=field, transform=transform.__name__):
                    record = self.legacy_record() if transform is migrate else copy.deepcopy(FIXTURE)
                    record["semantic_roles"] = [{"constituent": "obj", "role": "Theme", "predicate": reference}]
                    record["annotation_scope"] = {
                        "coverage": "task_focused_partial",
                        "dimensions": [declaration("semantic_roles", {"kind": "record"}, evidence="present")],
                    }
                    transform(record)
                    self.assertEqual(record["semantic_roles"][0]["predicate"], "w2")
                    self.assertEqual(validate_record(record, f"unique-role-{transform.__name__}"), [])

    def test_semantic_role_duplicate_lemma_or_form_remains_unresolved(self) -> None:
        for field, reference in (("lemma", "catalogue"), ("form", "catalogued")):
            for transform in (migrate, repair_record):
                with self.subTest(field=field, transform=transform.__name__):
                    record = self.legacy_record() if transform is migrate else copy.deepcopy(FIXTURE)
                    record["words"][4][field] = reference
                    if field == "form":
                        record["sentence"] = "The archivist catalogued the catalogued."
                    record["semantic_roles"] = [{"constituent": "obj", "role": "Theme", "predicate": reference}]
                    record["annotation_scope"] = {
                        "coverage": "task_focused_partial",
                        "dimensions": [declaration("semantic_roles", {"kind": "record"}, evidence="present")],
                    }
                    transform(record)
                    self.assertEqual(record["semantic_roles"], [])
                    self.assertIn("semantic_roles_unresolved_references", record["legacy_annotations"])
                    self.assertTrue(record["migration_review_required"])
                    self.assertEqual(validate_record(record, f"ambiguous-role-{transform.__name__}"), [])

    def _construction_record(self, transform: Any, field: str, value: Any, evidence: str | None = None) -> dict[str, Any]:
        record = self.legacy_record() if transform is migrate else copy.deepcopy(FIXTURE)
        record[field] = copy.deepcopy(value)
        if evidence is not None:
            record["annotation_scope"] = {
                "coverage": "task_focused_partial",
                "dimensions": [declaration("construction_relations", {"kind": "record"}, evidence=evidence)],
            }
        return record

    def test_uncovered_construction_payload_is_quarantined_across_migration_and_repair(self) -> None:
        payloads = (
            ("construction_signature", {"predicate_lemma": "catalogue", "construction_type": "transitive", "argument_pattern": ["NP"], "function_pattern": ["object"]}),
            ("construction_type", "transitive"),
            ("construction_tags", ["transitive"]),
            ("heads", [{"head": "w2", "dependent": "obj", "relation": "selects"}]),
            ("fusion_relations", [{"id": "fusion", "type": "fused_relative", "fused_element": "w2", "whole_constituent": "subj", "relative_clause": "c0", "fused_functions": ["nominal", "relativized"]}]),
        )
        for field, value in payloads:
            for transform in (migrate, repair_record):
                with self.subTest(field=field, transform=transform.__name__):
                    record = self._construction_record(transform, field, value)
                    transform(record)
                    if isinstance(value, list):
                        self.assertEqual(record[field], [])
                    else:
                        self.assertNotIn(field, record)
                    self.assertIn(f"{field}_unscoped", record["legacy_annotations"])
                    self.assertTrue(record["migration_review_required"])
                    self.assertEqual(validate_record(record, f"construction-{field}"), [])

    def test_uncovered_typed_construction_relation_is_quarantined(self) -> None:
        relation = {
            "id": "rel-construction",
            "type": "construction",
            "arity": "binary",
            "source": {"namespace": "word", "id": "w2"},
            "target": {"namespace": "constituent", "id": "obj"},
        }
        for transform in (migrate, repair_record):
            with self.subTest(transform=transform.__name__):
                record = self.legacy_record() if transform is migrate else copy.deepcopy(FIXTURE)
                record["canonical_analysis"]["typed_analysis"]["status"] = "established"
                record["canonical_analysis"]["typed_analysis"]["relations"] = [relation]
                transform(record)
                self.assertEqual(record["canonical_analysis"]["typed_analysis"]["relations"], [])
                self.assertEqual(record["legacy_annotations"]["typed_relation_unscoped"], [relation])
                self.assertTrue(record["migration_review_required"])
                self.assertEqual(validate_record(record, f"typed-construction-{transform.__name__}"), [])

    def test_unannotated_construction_declaration_does_not_retain_payload(self) -> None:
        for completeness, omission, evidence in (("unannotated", "intentional", "unannotated"), ("omitted", "intentional", "unannotated")):
            for transform in (migrate, repair_record):
                with self.subTest(completeness=completeness, transform=transform.__name__):
                    record = self._construction_record(transform, "construction_type", "transitive")
                    record["annotation_scope"] = {
                        "coverage": "task_focused_partial",
                        "dimensions": [declaration("construction_relations", {"kind": "record"}, completeness, omission, evidence)],
                    }
                    transform(record)
                    self.assertNotIn("construction_type", record)
                    self.assertIn("construction_type_unscoped", record["legacy_annotations"])
                    self.assertEqual(validate_record(record, f"uncovered-construction-{transform.__name__}"), [])

    def test_valid_covered_construction_payload_is_preserved(self) -> None:
        for transform in (migrate, repair_record):
            with self.subTest(transform=transform.__name__):
                record = self._construction_record(transform, "construction_type", "transitive", evidence="present")
                transform(record)
                self.assertEqual(record["construction_type"], "transitive")
                self.assertNotIn("construction_type_unscoped", record.get("legacy_annotations", {}))
                self.assertEqual(validate_record(record, f"covered-construction-{transform.__name__}"), [])

    def test_uncovered_nested_construction_arguments_and_entities_are_quarantined(self) -> None:
        argument = {"kind": "subject", "target": "subj"}
        entity = {"id": "e1", "kind": "clause"}
        for transform in (migrate, repair_record):
            with self.subTest(transform=transform.__name__):
                record = self.legacy_record() if transform is migrate else copy.deepcopy(FIXTURE)
                typed = record["canonical_analysis"]["typed_analysis"]
                typed["status"] = "established"
                typed["arguments"] = {"a1": copy.deepcopy(argument)}
                typed["entities"] = [copy.deepcopy(entity)]
                transform(record)
                typed = record["canonical_analysis"]["typed_analysis"]
                self.assertNotIn("arguments", typed)
                self.assertEqual(typed["entities"], [])
                self.assertEqual(record["legacy_annotations"]["typed_arguments_unscoped"], [argument])
                self.assertEqual(record["legacy_annotations"]["typed_entity_unscoped"], [entity])
                self.assertTrue(record["migration_review_required"])
                self.assertEqual(validate_record(record, f"nested-quarantine-{transform.__name__}"), [])

    def test_covered_nested_construction_arguments_and_entities_are_preserved(self) -> None:
        argument = {"id": "a1", "kind": "subject", "target": "subj"}
        entity = {"id": "e1", "kind": "clause"}
        for transform in (migrate, repair_record):
            with self.subTest(transform=transform.__name__):
                record = self._construction_record(transform, "construction_type", "transitive", evidence="present")
                typed = record["canonical_analysis"]["typed_analysis"]
                typed["status"] = "established"
                typed["arguments"] = {"a1": copy.deepcopy(argument)}
                typed["entities"] = [copy.deepcopy(entity)]
                transform(record)
                typed = record["canonical_analysis"]["typed_analysis"]
                self.assertEqual(typed["arguments"], {"a1": argument})
                self.assertEqual(typed["entities"], [entity])
                self.assertNotIn("typed_arguments_unscoped", record.get("legacy_annotations", {}))
                self.assertNotIn("typed_entity_unscoped", record.get("legacy_annotations", {}))
                self.assertEqual(validate_record(record, f"nested-covered-{transform.__name__}"), [])

    def test_mixed_status_nested_items_are_quarantined_itemwise(self) -> None:
        covered_relation = {
            "id": "rel-covered",
            "type": "construction",
            "arity": "binary",
            "source": {"namespace": "word", "id": "w2"},
            "target": {"namespace": "constituent", "id": "obj"},
        }
        uncovered_relation = {
            "id": "rel-uncovered",
            "type": "construction",
            "arity": "binary",
            "status": "unresolved",
            "source": {"namespace": "word", "id": "w2"},
            "target": {"namespace": "constituent", "id": "subj"},
        }
        uncovered_argument = {"id": "a2", "kind": "object", "status": "unresolved", "target": "obj"}
        for transform in (migrate, repair_record):
            with self.subTest(transform=transform.__name__):
                record = self._construction_record(transform, "construction_type", "transitive", evidence="present")
                typed = record["canonical_analysis"]["typed_analysis"]
                typed["status"] = "established"
                typed["relations"] = [copy.deepcopy(covered_relation), copy.deepcopy(uncovered_relation)]
                typed["arguments"] = {
                    "a1": {"id": "a1", "kind": "subject", "target": "subj"},
                    "a2": copy.deepcopy(uncovered_argument),
                }
                transform(record)
                typed = record["canonical_analysis"]["typed_analysis"]
                self.assertEqual(typed["relations"], [covered_relation])
                self.assertEqual(typed["arguments"], {"a1": {"id": "a1", "kind": "subject", "target": "subj"}})
                self.assertEqual(record["legacy_annotations"]["typed_relation_unscoped"], [uncovered_relation])
                self.assertEqual(record["legacy_annotations"]["typed_arguments_unscoped"], [uncovered_argument])
                self.assertTrue(record["migration_review_required"])
                self.assertEqual(validate_record(record, f"nested-mixed-{transform.__name__}"), [])

    def test_entity_referenced_by_non_construction_relation_is_not_quarantined(self) -> None:
        entity = {"id": "e1", "kind": "understood_subject"}
        relation = {
            "id": "rel-dependency",
            "type": "dependency",
            "arity": "binary",
            "status": "established",
            "source": "word:w2",
            "target": "analysis:e1",
        }
        for transform in (migrate, repair_record):
            with self.subTest(transform=transform.__name__):
                record = self.legacy_record() if transform is migrate else copy.deepcopy(FIXTURE)
                dependency_entry = next(
                    entry for entry in record["annotation_scope"]["dimensions"]
                    if entry["dimension"] == "dependencies"
                )
                dependency_entry["completeness"] = "partial"
                dependency_entry["omission"] = "none"
                dependency_entry["evidence"] = "present"
                typed = record["canonical_analysis"]["typed_analysis"]
                typed["status"] = "unresolved"
                typed["relations"] = [copy.deepcopy(relation)]
                typed["entities"] = [copy.deepcopy(entity)]
                transform(record)
                typed = record["canonical_analysis"]["typed_analysis"]
                self.assertEqual(typed["entities"], [entity])
                self.assertEqual(typed["relations"], [relation])
                self.assertNotIn("typed_entity_unscoped", record.get("legacy_annotations", {}))
                self.assertEqual(validate_record(record, f"entity-guard-{transform.__name__}"), [])

    def test_unresolved_entity_referenced_by_covered_relation_is_preserved(self) -> None:
        entity = {"id": "e1", "kind": "clause"}
        relation = {
            "id": "rel-covered",
            "type": "construction",
            "arity": "binary",
            "status": "established",
            "source": {"namespace": "word", "id": "w2"},
            "target": {"namespace": "analysis", "id": "e1"},
        }
        for transform in (migrate, repair_record):
            with self.subTest(transform=transform.__name__):
                record = self._construction_record(transform, "construction_type", "transitive", evidence="present")
                typed = record["canonical_analysis"]["typed_analysis"]
                typed["status"] = "unresolved"
                typed["relations"] = [copy.deepcopy(relation)]
                typed["entities"] = [copy.deepcopy(entity)]
                transform(record)
                typed = record["canonical_analysis"]["typed_analysis"]
                self.assertEqual(typed["relations"], [relation])
                self.assertEqual(typed["entities"], [entity])
                self.assertNotIn("typed_entity_unscoped", record.get("legacy_annotations", {}))
                self.assertEqual(validate_record(record, f"covered-entity-ref-{transform.__name__}"), [])

    def test_uncovered_nested_payload_in_alternative_analysis_is_quarantined(self) -> None:
        argument = {"kind": "subject", "target": "subj"}
        entity = {"id": "e1", "kind": "clause"}
        for transform in (migrate, repair_record):
            with self.subTest(transform=transform.__name__):
                record = self.legacy_record() if transform is migrate else copy.deepcopy(FIXTURE)
                record["alternative_analyses"] = [{
                    "id": "alt-1",
                    "framework": "CGEL",
                    "status": "established",
                    "typed_analysis": {
                        "kind": "record_level_analysis",
                        "framework": "CGEL",
                        "status": "established",
                        "arguments": {"a1": copy.deepcopy(argument)},
                        "entities": [copy.deepcopy(entity)],
                    },
                }]
                transform(record)
                typed = record["alternative_analyses"][0]["typed_analysis"]
                self.assertNotIn("arguments", typed)
                self.assertEqual(typed["entities"], [])
                self.assertIn("typed_arguments_unscoped", record["legacy_annotations"])
                self.assertIn("typed_entity_unscoped", record["legacy_annotations"])
                self.assertTrue(record["migration_review_required"])
                self.assertEqual(validate_record(record, f"alt-nested-{transform.__name__}"), [])

    def _shared_ownership_record(self, transform: Any) -> dict[str, Any]:
        record = self.legacy_record() if transform is migrate else copy.deepcopy(FIXTURE)
        record["dependencies"] = [copy.deepcopy(DEPENDENCY)]
        dependency_entry = next(
            entry for entry in record["annotation_scope"]["dimensions"]
            if entry["dimension"] == "dependencies"
        )
        dependency_entry["completeness"] = "partial"
        dependency_entry["omission"] = "none"
        dependency_entry["evidence"] = "present"
        return record

    def test_dependency_owned_argument_with_covered_dependencies_is_preserved(self) -> None:
        argument = {"id": "a1", "kind": "subject", "target": "subj"}
        for transform in (migrate, repair_record):
            with self.subTest(transform=transform.__name__):
                record = self._shared_ownership_record(transform)
                typed = record["canonical_analysis"]["typed_analysis"]
                typed["status"] = "established"
                typed["arguments"] = {"a1": copy.deepcopy(argument)}
                transform(record)
                typed = record["canonical_analysis"]["typed_analysis"]
                self.assertEqual(typed.get("arguments"), {"a1": argument})
                self.assertNotIn("typed_arguments_unscoped", record.get("legacy_annotations", {}))
                self.assertNotIn("migration_review_required", record)
                construction_entry = next(
                    (entry for entry in record["annotation_scope"]["dimensions"]
                     if entry["dimension"] == "construction_relations"),
                    None,
                )
                self.assertTrue(
                    construction_entry is None
                    or construction_entry["evidence"] != "present"
                )
                self.assertEqual(validate_record(record, f"shared-argument-{transform.__name__}"), [])

    def test_dependency_shaped_argument_without_dependencies_coverage_is_quarantined(self) -> None:
        argument = {"id": "a1", "kind": "subject", "target": "subj"}
        for completeness, omission in (("unannotated", "intentional"), ("omitted", "intentional")):
            for transform in (migrate, repair_record):
                with self.subTest(completeness=completeness, transform=transform.__name__):
                    record = self._shared_ownership_record(transform)
                    dependency_entry = next(
                        entry for entry in record["annotation_scope"]["dimensions"]
                        if entry["dimension"] == "dependencies"
                    )
                    dependency_entry["completeness"] = completeness
                    dependency_entry["omission"] = omission
                    dependency_entry["evidence"] = "unannotated"
                    record["dependencies"] = []
                    typed = record["canonical_analysis"]["typed_analysis"]
                    typed["status"] = "established"
                    typed["arguments"] = {"a1": copy.deepcopy(argument)}
                    transform(record)
                    typed = record["canonical_analysis"]["typed_analysis"]
                    self.assertNotIn("arguments", typed)
                    self.assertEqual(record["legacy_annotations"]["typed_arguments_unscoped"], [argument])
                    self.assertTrue(record["migration_review_required"])
                    self.assertEqual(validate_record(record, f"uncovered-shared-argument-{transform.__name__}"), [])

    def test_entity_referenced_by_covered_dependency_relation_is_cleanly_preserved(self) -> None:
        entity = {"id": "e1", "kind": "understood_subject"}
        relation = {
            "id": "rel-dependency",
            "type": "dependency",
            "arity": "binary",
            "status": "established",
            "source": "word:w2",
            "target": "analysis:e1",
        }
        for transform in (migrate, repair_record):
            with self.subTest(transform=transform.__name__):
                record = self._shared_ownership_record(transform)
                typed = record["canonical_analysis"]["typed_analysis"]
                typed["status"] = "established"
                typed["relations"] = [copy.deepcopy(relation)]
                typed["entities"] = [copy.deepcopy(entity)]
                transform(record)
                typed = record["canonical_analysis"]["typed_analysis"]
                self.assertEqual(typed["entities"], [entity])
                self.assertEqual(typed["relations"], [relation])
                self.assertNotIn("typed_entity_unscoped", record.get("legacy_annotations", {}))
                self.assertNotIn("migration_review_required", record)
                self.assertEqual(validate_record(record, f"covered-entity-protection-{transform.__name__}"), [])

    def test_relation_existence_alone_does_not_cleanly_protect_entity(self) -> None:
        entity = {"id": "e1", "kind": "understood_subject"}
        relation = {
            "id": "rel-extension",
            "type": "pedagogical:object",
            "arity": "binary",
            "status": "established",
            "source": "word:w2",
            "target": "analysis:e1",
        }
        for transform in (migrate, repair_record):
            with self.subTest(transform=transform.__name__):
                record = self.legacy_record() if transform is migrate else copy.deepcopy(FIXTURE)
                typed = record["canonical_analysis"]["typed_analysis"]
                typed["status"] = "established"
                typed["relations"] = [copy.deepcopy(relation)]
                typed["entities"] = [copy.deepcopy(entity)]
                transform(record)
                typed = record["canonical_analysis"]["typed_analysis"]
                self.assertEqual(typed["entities"], [entity])
                self.assertTrue(record["migration_review_required"])
                self.assertNotIn("construction_relations", [
                    entry["dimension"] for entry in record["annotation_scope"]["dimensions"]
                    if entry.get("evidence") == "present"
                ])
                self.assertEqual(validate_record(record, f"unowned-entity-reference-{transform.__name__}"), [])

    def test_mixed_shared_and_construction_only_nested_items_split_by_ownership(self) -> None:
        dependency_argument = {"id": "a_dep", "relation": "obj", "head": "w2", "dependent": "obj"}
        construction_only_argument = {"role": "Agent"}
        referenced_entity = {"id": "e_dep", "kind": "understood_subject"}
        unreferenced_entity = {"id": "e_cons", "kind": "clause"}
        relation = {
            "id": "rel-dependency",
            "type": "dependency",
            "arity": "binary",
            "status": "established",
            "source": "word:w2",
            "target": "analysis:e_dep",
        }
        for transform in (migrate, repair_record):
            with self.subTest(transform=transform.__name__):
                record = self._shared_ownership_record(transform)
                typed = record["canonical_analysis"]["typed_analysis"]
                typed["status"] = "established"
                typed["arguments"] = {
                    "a_dep": copy.deepcopy(dependency_argument),
                    "a_cons": copy.deepcopy(construction_only_argument),
                }
                typed["entities"] = [copy.deepcopy(referenced_entity), copy.deepcopy(unreferenced_entity)]
                typed["relations"] = [copy.deepcopy(relation)]
                transform(record)
                typed = record["canonical_analysis"]["typed_analysis"]
                self.assertEqual(typed.get("arguments"), {"a_dep": dependency_argument})
                self.assertEqual(typed.get("entities"), [referenced_entity])
                self.assertEqual(typed.get("relations"), [relation])
                self.assertEqual(record["legacy_annotations"]["typed_arguments_unscoped"], [construction_only_argument])
                self.assertEqual(record["legacy_annotations"]["typed_entity_unscoped"], [unreferenced_entity])
                self.assertTrue(record["migration_review_required"])
                self.assertEqual(validate_record(record, f"mixed-ownership-{transform.__name__}"), [])

    def test_cross_analysis_relation_reference_does_not_protect_entity(self) -> None:
        entity = {"id": "e1", "kind": "clause"}
        relation = {
            "id": "rel-dependency",
            "type": "dependency",
            "arity": "binary",
            "status": "established",
            "source": "word:w2",
            "target": "analysis:e1",
        }
        for transform in (migrate, repair_record):
            with self.subTest(transform=transform.__name__):
                record = self._shared_ownership_record(transform)
                canonical_typed = record["canonical_analysis"]["typed_analysis"]
                canonical_typed["status"] = "established"
                canonical_typed["entities"] = [copy.deepcopy(entity)]
                record["alternative_analyses"] = [{
                    "id": "alt-1",
                    "framework": "CGEL",
                    "status": "established",
                    "typed_analysis": {
                        "kind": "record_level_analysis",
                        "framework": "CGEL",
                        "status": "established",
                        "relations": [copy.deepcopy(relation)],
                        "entities": [copy.deepcopy(entity)],
                    },
                }]
                transform(record)
                canonical_typed = record["canonical_analysis"]["typed_analysis"]
                alternative_typed = record["alternative_analyses"][0]["typed_analysis"]
                self.assertEqual(canonical_typed["entities"], [])
                self.assertEqual(alternative_typed["entities"], [entity])
                self.assertEqual(alternative_typed["relations"], [relation])
                self.assertEqual(record["legacy_annotations"]["typed_entity_unscoped"], [entity])
                self.assertTrue(record["migration_review_required"])
                self.assertEqual(validate_record(record, f"cross-analysis-{transform.__name__}"), [])

    def test_migration_downgrades_complete_intentional_unannotated(self) -> None:
        record = self.migrate_with([
            declaration("dependencies", {"kind": "record"}, "complete", "intentional", "unannotated"),
        ])
        entry = next(item for item in record["annotation_scope"]["dimensions"] if item["dimension"] == "dependencies")
        self.assertEqual((entry["completeness"], entry["omission"], entry["evidence"]), ("unannotated", "intentional", "unannotated"))

    def test_repair_does_not_create_partial_intentional_present(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["dependencies"] = [DEPENDENCY]
        record["annotation_scope"] = {"coverage": "task_focused_partial", "annotated_dimensions": [], "intentionally_omitted": []}
        repaired = repair_record(record)
        entry = next(item for item in repaired["annotation_scope"]["dimensions"] if item["dimension"] == "dependencies")
        self.assertEqual((entry["completeness"], entry["omission"], entry["evidence"]), ("unannotated", "intentional", "unannotated"))
        self.assertEqual(repaired["dependencies"], [])
        self.assertTrue(repaired["migration_review_required"])
        self.assertEqual(validate_record(repaired, "repair-present-safety"), [])

    def test_direct_repair_rejects_protected_provenance_without_mutation(self) -> None:
        for status in ("linguistically_reviewed", "approved_for_training", "canonical_gold"):
            with self.subTest(status=status):
                record = copy.deepcopy(FIXTURE)
                record["review_metadata"]["review_status"] = status
                before = copy.deepcopy(record)
                with self.assertRaises(ValueError):
                    repair_record(record)
                self.assertEqual(record, before)

    def repaired_fixture(self) -> dict[str, Any]:
        record = copy.deepcopy(FIXTURE)
        repair_record(record)
        return record

    def test_direct_repair_protects_reviewed_already_repaired_records(self) -> None:
        for status in ("linguistically_reviewed", "approved_for_training", "canonical_gold"):
            with self.subTest(status=status):
                record = self.repaired_fixture()
                record["review_metadata"]["review_status"] = status
                before = copy.deepcopy(record)
                with self.assertRaises(ValueError):
                    repair_record(record)
                self.assertEqual(record, before)

    def test_first_direct_repair_writes_trusted_output_hash(self) -> None:
        record = copy.deepcopy(FIXTURE)
        before = copy.deepcopy(record)
        result = repair_record(record)
        self.assertIs(result, record)
        self.assertNotEqual(record, before)
        self.assertEqual(result["migration_metadata"]["fixture_repair_version"], REPAIR_VERSION)
        self.assertEqual(result["migration_metadata"]["repair_output_hash"], _repair_output_hash(result))
        self.assertEqual(validate_record(result, "first-direct-repair"), [])

    def test_direct_repair_replaces_untrusted_hash_on_fresh_input(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["migration_metadata"]["repair_output_hash"] = "0" * 64
        result = repair_record(record)
        self.assertNotEqual(result["migration_metadata"]["repair_output_hash"], "0" * 64)
        self.assertEqual(result["migration_metadata"]["repair_output_hash"], _repair_output_hash(result))
        self.assertEqual(validate_record(result, "fresh-stale-hash"), [])

    def test_direct_repair_of_canonical_invalid_fresh_input_fails_without_mutation(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["sentence"] = ""
        before = copy.deepcopy(record)
        with self.assertRaisesRegex(ValueError, "canonical V0.4 validation failed"):
            repair_record(record)
        self.assertEqual(record, before)

    def test_already_repaired_direct_noop_with_valid_hash_succeeds(self) -> None:
        record = self.repaired_fixture()
        before = copy.deepcopy(record)
        result = repair_record(record)
        self.assertIs(result, record)
        self.assertEqual(record, before)
        self.assertEqual(record["migration_metadata"]["repair_output_hash"], _repair_output_hash(record))
        self.assertEqual(validate_record(record, "already-repaired-noop"), [])

    def test_already_repaired_direct_rejects_missing_output_hash(self) -> None:
        record = self.repaired_fixture()
        del record["migration_metadata"]["repair_output_hash"]
        before = copy.deepcopy(record)
        with self.assertRaisesRegex(ValueError, "repaired output hash is required"):
            repair_record(record)
        self.assertEqual(record, before)

    def test_already_repaired_direct_rejects_stale_output_hash(self) -> None:
        record = self.repaired_fixture()
        record["migration_metadata"]["repair_output_hash"] = _repair_output_hash({"tampered": True})
        before = copy.deepcopy(record)
        with self.assertRaisesRegex(ValueError, "repaired output hash mismatch"):
            repair_record(record)
        self.assertEqual(record, before)

    def test_already_repaired_direct_rejects_tampered_content_with_stale_hash(self) -> None:
        record = self.repaired_fixture()
        stored_hash = record["migration_metadata"]["repair_output_hash"]
        record["sentence"] = "Tampered sentence."
        with self.assertRaisesRegex(ValueError, "repaired output hash mismatch"):
            repair_record(record)
        self.assertEqual(record["migration_metadata"]["repair_output_hash"], stored_hash)

    def test_already_repaired_direct_rejects_canonical_invalid_with_matching_hash(self) -> None:
        record = self.repaired_fixture()
        record["sentence"] = ""
        record["migration_metadata"]["repair_output_hash"] = _repair_output_hash(record)
        before = copy.deepcopy(record)
        with self.assertRaisesRegex(ValueError, "canonical V0.4 validation failed"):
            repair_record(record)
        self.assertEqual(record, before)

    def test_repaired_output_hash_is_stable_and_repeat_safe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "records.jsonl"
            manifest = Path(directory) / "manifest.json"
            path.write_text(json.dumps(copy.deepcopy(FIXTURE)) + "\n")
            manifest.write_text(json.dumps({"records": [{"id": FIXTURE["id"], "source_version": "0.4"}]}))

            repair_file(path, manifest)
            once = path.read_bytes()
            repaired = json.loads(once)
            self.assertEqual(
                repaired["migration_metadata"]["repair_output_hash"],
                _repair_output_hash(repaired),
            )

            repair_file(path, manifest)
            self.assertEqual(path.read_bytes(), once)
            repair_file(path, manifest)
            self.assertEqual(path.read_bytes(), once)

    def test_tampered_repaired_record_fails_before_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "records.jsonl"
            manifest = Path(directory) / "manifest.json"
            path.write_text(json.dumps(copy.deepcopy(FIXTURE)) + "\n")
            manifest.write_text(json.dumps({"records": [{"id": FIXTURE["id"], "source_version": "0.4"}]}))
            repair_file(path, manifest)
            tampered = json.loads(path.read_text())
            tampered["sentence"] = "Tampered."
            path.write_text(json.dumps(tampered) + "\n")
            before = path.read_bytes()

            with self.assertRaises(ValueError):
                repair_file(path, manifest)
            self.assertEqual(path.read_bytes(), before)

    def test_already_repaired_output_is_validated_even_with_matching_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "records.jsonl"
            manifest = Path(directory) / "manifest.json"
            path.write_text(json.dumps(copy.deepcopy(FIXTURE)) + "\n")
            manifest.write_text(json.dumps({"records": [{"id": FIXTURE["id"], "source_version": "0.4"}]}))
            repair_file(path, manifest)
            invalid = json.loads(path.read_text())
            invalid["sentence"] = ""
            invalid["migration_metadata"]["repair_output_hash"] = _repair_output_hash(invalid)
            path.write_text(json.dumps(invalid) + "\n")
            before = path.read_bytes()

            with self.assertRaisesRegex(ValueError, "canonical V0.4 validation failed"):
                repair_file(path, manifest)
            self.assertEqual(path.read_bytes(), before)

    def test_changed_repair_validates_non_targeted_rows_before_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "records.jsonl"
            manifest = Path(directory) / "manifest.json"
            target = copy.deepcopy(FIXTURE)
            unrelated = copy.deepcopy(FIXTURE)
            unrelated["id"] = "unrelated"
            unrelated["sentence"] = ""
            path.write_text(json.dumps(target) + "\n" + json.dumps(unrelated) + "\n")
            manifest.write_text(json.dumps({"records": [{"id": target["id"], "source_version": "0.4"}]}))
            before = path.read_bytes()

            with self.assertRaisesRegex(ValueError, "canonical V0.4 validation failed"):
                repair_file(path, manifest)
            self.assertEqual(path.read_bytes(), before)

    def test_duplicate_manifest_covered_input_ids_are_rejected(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["id"] = "duplicate-id"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "records.jsonl"
            manifest = Path(directory) / "manifest.json"
            path.write_text(json.dumps(record) + "\n" + json.dumps(record) + "\n")
            manifest.write_text(json.dumps({"records": [{"id": "duplicate-id", "source_version": "0.4"}]}))
            before = path.read_bytes()
            with self.assertRaisesRegex(ValueError, "duplicate record id 'duplicate-id'"):
                repair_file(path, manifest)
            self.assertEqual(path.read_bytes(), before)

    def test_one_manifest_entry_cannot_authorize_two_input_rows(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["id"] = "duplicate-id"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "records.jsonl"
            manifest = Path(directory) / "manifest.json"
            path.write_text(json.dumps(record) + "\n" + json.dumps(record) + "\n")
            manifest.write_text(json.dumps({"records": [{"id": "duplicate-id", "source_version": "0.4"}]}))
            before = path.read_bytes()
            with self.assertRaises(ValueError):
                repair_file(path, manifest)
            self.assertEqual(path.read_bytes(), before)
            rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
            self.assertTrue(all("repair_output_hash" not in row.get("migration_metadata", {}) for row in rows))

    def test_duplicate_input_ids_outside_manifest_are_rejected(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["id"] = "duplicate-id"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "records.jsonl"
            manifest = Path(directory) / "manifest.json"
            path.write_text(json.dumps(record) + "\n" + json.dumps(record) + "\n")
            manifest.write_text(json.dumps({"records": []}))
            before = path.read_bytes()
            with self.assertRaisesRegex(ValueError, "duplicate record id 'duplicate-id'"):
                repair_file(path, manifest)
            self.assertEqual(path.read_bytes(), before)

    def test_duplicate_already_repaired_input_rows_are_rejected(self) -> None:
        record = copy.deepcopy(FIXTURE)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "records.jsonl"
            manifest = Path(directory) / "manifest.json"
            path.write_text(json.dumps(record) + "\n")
            manifest.write_text(json.dumps({"records": [{"id": record["id"], "source_version": "0.4"}]}))
            repair_file(path, manifest)
            repaired_line = path.read_text()
            path.write_text(repaired_line + repaired_line)
            before = path.read_bytes()
            with self.assertRaisesRegex(ValueError, f"duplicate record id {record['id']!r}"):
                repair_file(path, manifest)
            self.assertEqual(path.read_bytes(), before)

    def test_unique_multi_row_input_still_repairs(self) -> None:
        first = copy.deepcopy(FIXTURE)
        second = copy.deepcopy(FIXTURE)
        second["id"] = "fixture-second"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "records.jsonl"
            manifest = Path(directory) / "manifest.json"
            path.write_text(json.dumps(first) + "\n" + json.dumps(second) + "\n")
            manifest.write_text(json.dumps({"records": [
                {"id": first["id"], "source_version": "0.4"},
                {"id": second["id"], "source_version": "0.4"},
            ]}))
            repair_file(path, manifest)
            rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
            self.assertEqual([row["id"] for row in rows], [first["id"], second["id"]])
            for row in rows:
                self.assertEqual(row["migration_metadata"]["fixture_repair_version"], "0.4.0")
                self.assertIn("repair_output_hash", row["migration_metadata"])

    def test_duplicate_manifest_ids_rejection_is_unchanged(self) -> None:
        record = copy.deepcopy(FIXTURE)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "records.jsonl"
            manifest = Path(directory) / "manifest.json"
            path.write_text(json.dumps(record) + "\n")
            manifest.write_text(json.dumps({"records": [
                {"id": record["id"], "source_version": "0.4"},
                {"id": record["id"], "source_version": "0.4"},
            ]}))
            before = path.read_bytes()
            with self.assertRaisesRegex(ValueError, "repair manifest contains duplicate id"):
                repair_file(path, manifest)
            self.assertEqual(path.read_bytes(), before)

    def test_manifest_ids_missing_from_input_rejection_is_unchanged(self) -> None:
        record = copy.deepcopy(FIXTURE)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "records.jsonl"
            manifest = Path(directory) / "manifest.json"
            path.write_text(json.dumps(record) + "\n")
            manifest.write_text(json.dumps({"records": [
                {"id": record["id"], "source_version": "0.4"},
                {"id": "absent-record", "source_version": "0.4"},
            ]}))
            before = path.read_bytes()
            with self.assertRaisesRegex(ValueError, r"manifest IDs missing from input: \['absent-record'\]"):
                repair_file(path, manifest)
            self.assertEqual(path.read_bytes(), before)

    def test_ambiguous_duplicate_lemma_or_form_does_not_choose_first_or_last(self) -> None:
        cases = (("lemma", "catalogue"), ("form", "catalogued"))
        for field, reference in cases:
            with self.subTest(field=field):
                record = self.legacy_record()
                record["words"][4][field] = reference
                if field == "form":
                    record["sentence"] = "The archivist catalogued the catalogued."
                record["lexical_valency"] = [{**VALENCY, "predicate": reference}]
                record["annotation_scope"] = {
                    "coverage": "task_focused_partial",
                    "dimensions": [declaration("lexical_valency", {"kind": "record"})],
                }
                migrate(record)
                self.assertEqual(record["lexical_valency"], [])
                self.assertIn("lexical_valency_unresolved_references", record["legacy_annotations"])
                self.assertTrue(record["migration_review_required"])
                self.assertEqual(validate_record(record, "ambiguous-reference-safety"), [])

                repaired = copy.deepcopy(FIXTURE)
                repaired["words"][4][field] = reference
                if field == "form":
                    repaired["sentence"] = "The archivist catalogued the catalogued."
                repaired["lexical_valency"] = [{**VALENCY, "predicate": reference}]
                repaired["annotation_scope"] = {
                    "coverage": "task_focused_partial",
                    "dimensions": [declaration("lexical_valency", {"kind": "record"})],
                }
                repair_record(repaired)
                self.assertEqual(repaired["lexical_valency"], [])
                self.assertIn("lexical_valency_unresolved_references", repaired["legacy_annotations"])
                self.assertTrue(repaired["migration_review_required"])
                self.assertEqual(validate_record(repaired, "ambiguous-repair-safety"), [])

    def test_unique_lexical_mapping_is_supported_by_migration_and_repair(self) -> None:
        migrated = self.legacy_record()
        migrated["lexical_valency"] = [VALENCY]
        migrated["annotation_scope"] = {
            "coverage": "task_focused_partial",
            "dimensions": [declaration("lexical_valency", {"kind": "node", "node": "w2"}, evidence="present")],
        }
        migrate(migrated)
        self.assertEqual(migrated["lexical_valency"][0]["predicate"], "w2")
        self.assertEqual(validate_record(migrated, "unique-migration-safety"), [])

        repaired = copy.deepcopy(FIXTURE)
        repaired["lexical_valency"] = [VALENCY]
        repaired["annotation_scope"] = {
            "coverage": "task_focused_partial",
            "dimensions": [declaration("lexical_valency", {"kind": "node", "node": "w2"}, evidence="present")],
        }
        repair_record(repaired)
        self.assertEqual(repaired["lexical_valency"][0]["predicate"], "w2")
        self.assertEqual(validate_record(repaired, "unique-repair-safety"), [])

    def test_file_transforms_validate_before_write(self) -> None:
        record = self.legacy_record()
        record["sentence"] = ""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "records.jsonl"
            path.write_text(json.dumps(record) + "\n")
            before = path.read_text()
            with self.assertRaises(ValueError):
                migrate_file(path)
            self.assertEqual(path.read_text(), before)

            record = copy.deepcopy(FIXTURE)
            record["sentence"] = ""
            path.write_text(json.dumps(record) + "\n")
            manifest = Path(directory) / "manifest.json"
            manifest.write_text(json.dumps({"records": [{"id": record["id"], "source_version": "0.4"}]}))
            before = path.read_text()
            with self.assertRaises(ValueError):
                repair_file(path, manifest)
            self.assertEqual(path.read_text(), before)

    def test_construction_quarantine_writes_only_valid_canonical_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "records.jsonl"
            migrated = self.legacy_record()
            migrated["construction_type"] = "transitive"
            path.write_text(json.dumps(migrated) + "\n")
            migrate_file(path)
            migrated_output = json.loads(path.read_text().splitlines()[0])
            self.assertNotIn("construction_type", migrated_output)
            self.assertEqual(validate_record(migrated_output, "quarantine-migrated-output"), [])

            repaired = copy.deepcopy(FIXTURE)
            repaired["construction_type"] = "transitive"
            path.write_text(json.dumps(repaired) + "\n")
            manifest = Path(directory) / "manifest.json"
            manifest.write_text(json.dumps({"records": [{"id": repaired["id"], "source_version": "0.4"}]}))
            repair_file(path, manifest)
            repaired_output = json.loads(path.read_text().splitlines()[0])
            self.assertNotIn("construction_type", repaired_output)
            self.assertEqual(validate_record(repaired_output, "quarantine-repaired-output"), [])

    def test_declaration_order_does_not_change_migration_result(self) -> None:
        entries = [
            declaration("dependencies", {"kind": "record"}),
            declaration("lexical_valency", {"kind": "node", "node": "w2"}, evidence="present"),
            declaration("construction_relations", {"kind": "record"}, evidence="present"),
        ]
        forward = self.legacy_record()
        reverse = copy.deepcopy(forward)
        for record in (forward, reverse):
            record["dependencies"] = [DEPENDENCY]
            record["lexical_valency"] = [VALENCY]
            record["construction_type"] = "transitive"
            record["annotation_scope"] = {"coverage": "task_focused_partial", "dimensions": entries}
        reverse["annotation_scope"]["dimensions"] = list(reversed(entries))
        migrate(forward)
        migrate(reverse)
        self.assertEqual(forward, reverse)
        self.assertEqual(validate_record(forward, "order-forward-safety"), [])
        self.assertEqual(validate_record(reverse, "order-reverse-safety"), [])


if __name__ == "__main__":
    unittest.main()
