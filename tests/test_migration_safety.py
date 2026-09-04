from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from scripts.data_common import read_jsonl
from scripts.migrate_v021 import migrate, migrate_file
from scripts.repair_v031_data import repair_file, repair_record
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
            "dimensions": [declaration("lexical_valency", {"kind": "node", "node": "w2"})],
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
            "dimensions": [declaration("lexical_valency", {"kind": "node", "node": "w2"})],
        }
        migrate(migrated)
        self.assertEqual(migrated["lexical_valency"][0]["predicate"], "w2")
        self.assertEqual(validate_record(migrated, "unique-migration-safety"), [])

        repaired = copy.deepcopy(FIXTURE)
        repaired["lexical_valency"] = [VALENCY]
        repaired["annotation_scope"] = {
            "coverage": "task_focused_partial",
            "dimensions": [declaration("lexical_valency", {"kind": "node", "node": "w2"})],
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

    def test_declaration_order_does_not_change_migration_result(self) -> None:
        entries = [
            declaration("dependencies", {"kind": "record"}),
            declaration("lexical_valency", {"kind": "node", "node": "w2"}),
        ]
        forward = self.legacy_record()
        reverse = copy.deepcopy(forward)
        for record in (forward, reverse):
            record["dependencies"] = [DEPENDENCY]
            record["lexical_valency"] = [VALENCY]
            record["annotation_scope"] = {"coverage": "task_focused_partial", "dimensions": entries}
        reverse["annotation_scope"]["dimensions"] = list(reversed(entries))
        migrate(forward)
        migrate(reverse)
        self.assertEqual(forward, reverse)
        self.assertEqual(validate_record(forward, "order-forward-safety"), [])
        self.assertEqual(validate_record(reverse, "order-reverse-safety"), [])


if __name__ == "__main__":
    unittest.main()
