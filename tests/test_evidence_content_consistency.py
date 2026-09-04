from __future__ import annotations

import copy
import unittest
from pathlib import Path
from typing import Any

from scripts.coverage_resolution import CoverageResolutionError, CoverageState, resolve_coverage
from scripts.data_common import read_jsonl
from scripts.migrate_v021 import migrate
from scripts.render_sft import linguistic_projection
from scripts.repair_v031_data import repair_record
from scripts.validate_dataset import validate_record


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = read_jsonl(ROOT / "data" / "gold" / "fixtures.jsonl")[0][1]


def declaration(
    dimension: str,
    scope: dict[str, Any],
    completeness: str = "complete",
    omission: str = "none",
    evidence: str = "present",
) -> dict[str, Any]:
    return {
        "dimension": dimension,
        "scope": scope,
        "completeness": completeness,
        "omission": omission,
        "evidence": evidence,
    }


def record_with(
    dimension: str,
    entry: dict[str, Any],
    values: list[dict[str, Any]],
) -> dict[str, Any]:
    record = copy.deepcopy(FIXTURE)
    record[dimension] = values
    record["annotation_scope"]["dimensions"] = [
        existing
        for existing in record["annotation_scope"]["dimensions"]
        if existing.get("dimension") != dimension
    ] + [entry]
    return record


DEPENDENCY = {"relation": "selected", "head": "w2", "dependent": "obj"}
ROLE = {"constituent": "obj", "role": "Theme", "predicate": "w2"}
VALENCY = {"predicate": "catalogue", "frame": "transitive", "selected_complements": ["obj"]}


class EvidenceContentConsistencyTests(unittest.TestCase):
    def test_dependencies_present_non_empty_is_valid(self) -> None:
        record = record_with("dependencies", declaration("dependencies", {"kind": "record"}), [DEPENDENCY])
        self.assertEqual(validate_record(record, "dependencies-present"), [])

    def test_dependencies_present_empty_is_rejected(self) -> None:
        record = record_with("dependencies", declaration("dependencies", {"kind": "record"}), [])
        errors = validate_record(record, "dependencies-present-empty")
        self.assertTrue(any("evidence='present'" in error and "dependencies" in error for error in errors))

    def test_dependencies_empty_empty_is_valid(self) -> None:
        record = record_with(
            "dependencies",
            declaration("dependencies", {"kind": "record"}, evidence="empty"),
            [],
        )
        self.assertEqual(validate_record(record, "dependencies-empty"), [])

    def test_dependencies_empty_non_empty_is_rejected(self) -> None:
        record = record_with(
            "dependencies",
            declaration("dependencies", {"kind": "record"}, evidence="empty"),
            [DEPENDENCY],
        )
        errors = validate_record(record, "dependencies-empty-content")
        self.assertTrue(any("evidence='empty'" in error and "dependencies" in error for error in errors))

    def test_dependencies_unannotated_is_not_confirmed_empty(self) -> None:
        entry = declaration("dependencies", {"kind": "record"}, "partial", "intentional", "unannotated")
        record = record_with("dependencies", entry, [])
        self.assertEqual(validate_record(record, "dependencies-unannotated"), [])
        self.assertIs(resolve_coverage(record, "dependencies"), CoverageState.UNANNOTATED)

    def test_dependencies_unannotated_content_is_rejected(self) -> None:
        entry = declaration("dependencies", {"kind": "record"}, "partial", "intentional", "unannotated")
        record = record_with("dependencies", entry, [DEPENDENCY])
        errors = validate_record(record, "dependencies-unannotated-content")
        self.assertTrue(any("unannotated/omitted" in error and "dependencies" in error for error in errors))

    def test_semantic_roles_present_non_empty_is_valid(self) -> None:
        record = record_with("semantic_roles", declaration("semantic_roles", {"kind": "record"}), [ROLE])
        self.assertEqual(validate_record(record, "roles-present"), [])

    def test_semantic_roles_present_empty_is_rejected(self) -> None:
        record = record_with("semantic_roles", declaration("semantic_roles", {"kind": "record"}), [])
        errors = validate_record(record, "roles-present-empty")
        self.assertTrue(any("evidence='present'" in error and "semantic_roles" in error for error in errors))

    def test_semantic_roles_empty_empty_is_valid(self) -> None:
        record = record_with(
            "semantic_roles",
            declaration("semantic_roles", {"kind": "record"}, evidence="empty"),
            [],
        )
        self.assertEqual(validate_record(record, "roles-empty"), [])

    def test_semantic_roles_empty_non_empty_is_rejected(self) -> None:
        record = record_with(
            "semantic_roles",
            declaration("semantic_roles", {"kind": "record"}, evidence="empty"),
            [ROLE],
        )
        errors = validate_record(record, "roles-empty-content")
        self.assertTrue(any("evidence='empty'" in error and "semantic_roles" in error for error in errors))

    def test_semantic_roles_unannotated_is_omitted_from_projection(self) -> None:
        entry = declaration("semantic_roles", {"kind": "record"}, "partial", "intentional", "unannotated")
        record = record_with("semantic_roles", entry, [])
        self.assertNotIn("semantic_roles", linguistic_projection(record))

    def test_lexical_valency_present_empty_and_unannotated_consistency(self) -> None:
        present = record_with("lexical_valency", declaration("lexical_valency", {"kind": "record"}), [VALENCY])
        self.assertEqual(validate_record(present, "valency-present"), [])
        present_empty = record_with("lexical_valency", declaration("lexical_valency", {"kind": "record"}), [])
        self.assertTrue(any("evidence='present'" in error for error in validate_record(present_empty, "valency-present-empty")))
        confirmed_empty = record_with(
            "lexical_valency",
            declaration("lexical_valency", {"kind": "record"}, evidence="empty"),
            [],
        )
        self.assertEqual(validate_record(confirmed_empty, "valency-empty"), [])
        empty_with_content = record_with(
            "lexical_valency",
            declaration("lexical_valency", {"kind": "record"}, evidence="empty"),
            [VALENCY],
        )
        self.assertTrue(any("evidence='empty'" in error for error in validate_record(empty_with_content, "valency-empty-content")))
        unannotated = record_with(
            "lexical_valency",
            declaration("lexical_valency", {"kind": "record"}, "partial", "intentional", "unannotated"),
            [],
        )
        self.assertEqual(validate_record(unannotated, "valency-unannotated"), [])
        self.assertNotIn("lexical_valency", linguistic_projection(unannotated))

    def test_dependencies_nonrecord_scopes_are_rejected(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["dependencies"] = [{"relation": "selected", "head": "w2", "dependent": "subj"}]
        record["annotation_scope"]["dimensions"] = [
            declaration("dependencies", {"kind": "node", "node": "subj"}),
            declaration("dependencies", {"kind": "node", "node": "obj"}, evidence="empty"),
        ]
        errors = validate_record(record, "scoped-evidence")
        self.assertTrue(all("dependencies" in error and "scope" in error for error in errors))
        with self.assertRaises(CoverageResolutionError):
            resolve_coverage(record, "dependencies", "subj")

    def test_omitted_scope_is_not_confirmed_empty(self) -> None:
        entry = declaration("dependencies", {"kind": "record"}, "omitted", "intentional", "unannotated")
        record = record_with("dependencies", entry, [])
        self.assertEqual(validate_record(record, "omitted-scope"), [])
        self.assertIs(resolve_coverage(record, "dependencies", "obj"), CoverageState.OMITTED)

    def test_omitted_scope_content_is_rejected(self) -> None:
        entry = declaration("dependencies", {"kind": "record"}, "omitted", "intentional", "unannotated")
        record = record_with("dependencies", entry, [DEPENDENCY])
        errors = validate_record(record, "omitted-scope-content")
        self.assertTrue(any("unannotated/omitted" in error and "dependencies" in error for error in errors))

    def test_scope_declaration_order_does_not_change_interpretation(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["dependencies"] = [{"relation": "selected", "head": "w2", "dependent": "subj"}]
        entries = [
            declaration("dependencies", {"kind": "record"}),
            declaration("semantic_roles", {"kind": "record"}, "omitted", "intentional", "unannotated"),
        ]
        record["semantic_roles"] = []
        forward = copy.deepcopy(record)
        reverse = copy.deepcopy(record)
        forward["annotation_scope"]["dimensions"] = entries
        reverse["annotation_scope"]["dimensions"] = list(reversed(entries))
        self.assertEqual(validate_record(forward, "order-forward"), [])
        self.assertEqual(validate_record(reverse, "order-reverse"), [])
        self.assertEqual(linguistic_projection(forward), linguistic_projection(reverse))

    def test_renderer_outputs_confirmed_empty_collection(self) -> None:
        record = record_with(
            "dependencies",
            declaration("dependencies", {"kind": "record"}, evidence="empty"),
            [],
        )
        self.assertEqual(linguistic_projection(record)["dependencies"], [])

    def test_renderer_omits_unannotated_and_omitted_collections(self) -> None:
        for completeness in ("unannotated", "omitted"):
            with self.subTest(completeness=completeness):
                record = record_with(
                    "dependencies",
                    declaration("dependencies", {"kind": "record"}, completeness, "intentional", "unannotated"),
                    [],
                )
                self.assertNotIn("dependencies", linguistic_projection(record))

    def test_fixture_repair_preserves_unknown_empty_collections_as_unannotated(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["capability_tags"] = ["semantic_roles", "lexical_valency"]
        record.pop("semantic_roles", None)
        record.pop("lexical_valency", None)
        record["annotation_scope"] = {"coverage": "task_focused_partial", "annotated_dimensions": [], "intentionally_omitted": []}
        repair_record(record)
        entries = {
            entry["dimension"]: entry
            for entry in record["annotation_scope"]["dimensions"]
            if entry.get("dimension") in {"semantic_roles", "lexical_valency"}
        }
        self.assertEqual(
            {(entry.get("omission"), entry.get("evidence")) for entry in entries.values()},
            {("intentional", "unannotated")},
        )

    def test_migration_preserves_empty_collection_without_source_evidence(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["schema_version"] = "0.2"
        record["semantic_roles"] = []
        record["annotation_scope"] = {
            "coverage": "task_focused_partial",
            "dimensions": [{"dimension": "semantic_roles", "scope": {"kind": "record"}, "completeness": "partial", "omission": "none"}],
        }
        migrate(record)
        entry = record["annotation_scope"]["dimensions"][0]
        self.assertEqual((entry.get("omission"), entry.get("evidence")), ("intentional", "unannotated"))


if __name__ == "__main__":
    unittest.main()
