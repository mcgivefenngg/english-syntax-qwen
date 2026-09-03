from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from typing import Any

from scripts.data_common import read_jsonl
from scripts.render_sft import linguistic_projection, render_record
from scripts.validate_dataset import validate_record


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = read_jsonl(ROOT / "data" / "gold" / "fixtures.jsonl")[0][1]


def declaration(dimension: str, scope: dict[str, Any], completeness: str = "complete", omission: str = "none", evidence: str = "present") -> dict[str, Any]:
    return {"dimension": dimension, "scope": scope, "completeness": completeness, "omission": omission, "evidence": evidence}


def record_with(*entries: dict[str, Any]) -> dict[str, Any]:
    record = copy.deepcopy(FIXTURE)
    record["annotation_scope"]["dimensions"] = list(entries)
    return record


class CoverageAwareProjectionTests(unittest.TestCase):
    def test_covered_constituency_survives_omitted_function(self) -> None:
        record = record_with(
            declaration("phrase_constituency", {"kind": "record"}),
            declaration("syntactic_function", {"kind": "record"}, "omitted", "intentional", "unannotated"),
        )
        constituents = linguistic_projection(record)["constituents"]
        self.assertTrue(constituents)
        self.assertTrue(all("phrase_category" in item for item in constituents))
        self.assertTrue(all("function" not in item for item in constituents))

    def test_covered_function_survives_omitted_phrase_detail(self) -> None:
        record = record_with(
            declaration("syntactic_function", {"kind": "node", "node": "obj"}),
            declaration("phrase_constituency", {"kind": "record"}, "omitted", "intentional", "unannotated"),
        )
        constituents = linguistic_projection(record)["constituents"]
        self.assertEqual(constituents, [{"id": "obj", "node_kind": "phrase", "span": {"start": 3, "end": 5}, "function": "object"}])

    def test_subject_internal_structure_is_kept_object_internal_is_omitted(self) -> None:
        record = record_with(
            declaration("np_internal_constituency", {"kind": "node", "node": "subj"}),
            declaration("np_internal_constituency", {"kind": "node", "node": "obj"}, "omitted", "intentional", "unannotated"),
            declaration("syntactic_function", {"kind": "record"}),
        )
        record["constituents"].extend([
            {"id": "subj-det", "node_kind": "phrase", "phrase_category": "DetP", "span": {"start": 0, "end": 1}, "parent": "subj", "function": "determiner"},
            {"id": "obj-det", "node_kind": "phrase", "phrase_category": "DetP", "span": {"start": 3, "end": 4}, "parent": "obj", "function": "determiner"},
        ])
        by_id = {item["id"]: item for item in linguistic_projection(record)["constituents"]}
        self.assertIn("subj-det", by_id)
        self.assertNotIn("obj-det", by_id)
        self.assertIn("obj", by_id)
        self.assertNotIn("phrase_category", by_id["obj"])

    def test_unannotated_semantic_roles_are_absent(self) -> None:
        record = record_with(declaration("semantic_roles", {"kind": "record"}, "unannotated", "intentional", "unannotated"))
        self.assertNotIn("semantic_roles", linguistic_projection(record))

    def test_confirmed_empty_dependencies_are_retained(self) -> None:
        record = record_with(declaration("dependencies", {"kind": "record"}, evidence="empty"))
        record["dependencies"] = []
        self.assertEqual(linguistic_projection(record)["dependencies"], [])

    def test_omitted_dependencies_are_not_rendered_as_empty(self) -> None:
        record = record_with(declaration("dependencies", {"kind": "record"}, "omitted", "intentional", "unannotated"))
        record["dependencies"] = []
        self.assertNotIn("dependencies", linguistic_projection(record))

    def test_partial_covered_node_renders_only_covered_subset(self) -> None:
        record = record_with(
            declaration("phrase_constituency", {"kind": "node", "node": "subj"}, "partial"),
            declaration("phrase_constituency", {"kind": "node", "node": "obj"}, "omitted", "intentional", "unannotated"),
        )
        self.assertEqual([item["id"] for item in linguistic_projection(record)["constituents"]], ["subj"])

    def test_partial_uncovered_target_does_not_leak(self) -> None:
        record = record_with(declaration("phrase_constituency", {"kind": "record"}, "partial"))
        self.assertNotIn("constituents", linguistic_projection(record))

    def test_typed_relation_retains_minimal_reference_shell(self) -> None:
        record = record_with(declaration("construction_relations", {"kind": "record"}))
        record["canonical_analysis"]["typed_analysis"]["relations"] = [{
            "id": "rel-1", "type": "cross_node", "arity": "binary",
            "source": {"namespace": "word", "id": "w1"},
            "target": {"namespace": "constituent", "id": "obj"},
        }]
        payload = linguistic_projection(record)
        self.assertEqual(payload["words"], [{"id": "w1", "node_kind": "word"}])
        self.assertEqual(payload["constituents"], [{"id": "obj", "node_kind": "phrase", "span": {"start": 3, "end": 5}}])

    def test_typed_relation_does_not_leak_omitted_node_properties(self) -> None:
        record = record_with(declaration("construction_relations", {"kind": "record"}))
        record["canonical_analysis"]["typed_analysis"]["relations"] = [{
            "id": "rel-1", "type": "cross_node", "arity": "binary",
            "source": {"namespace": "word", "id": "w1"},
            "target": {"namespace": "constituent", "id": "obj"},
        }]
        node = linguistic_projection(record)["constituents"][0]
        self.assertNotIn("phrase_category", node)
        self.assertNotIn("function", node)
        self.assertNotIn("head", node)

    def test_declaration_order_does_not_change_projection(self) -> None:
        entries = [
            declaration("phrase_constituency", {"kind": "node", "node": "subj"}),
            declaration("phrase_constituency", {"kind": "node", "node": "obj"}, "omitted", "intentional", "unannotated"),
            declaration("syntactic_function", {"kind": "record"}),
        ]
        self.assertEqual(linguistic_projection(record_with(*entries)), linguistic_projection(record_with(*reversed(entries))))

    def test_rendered_projection_has_no_dangling_references(self) -> None:
        record = record_with(declaration("dependencies", {"kind": "record"}))
        record["dependencies"] = [{"relation": "selected", "head": "w2", "dependent": "obj"}]
        self.assertEqual(validate_record(render_record(record), "rendered"), [])

    def test_governance_and_adjudication_fields_are_absent(self) -> None:
        record = record_with(declaration("construction_relations", {"kind": "record"}))
        record["migration_note"] = "internal"
        record["clauses"][0]["adjudication_notes"] = "internal"
        record["canonical_analysis"]["typed_analysis"]["notes"] = "internal"
        payload = linguistic_projection(record)
        self.assertNotIn("migration_note", payload)
        self.assertNotIn("adjudication_notes", json.dumps(payload))
        self.assertNotIn("notes", payload.get("canonical_analysis", {}).get("typed_analysis", {}))

    def test_exact_end_to_end_scenario(self) -> None:
        record = record_with(
            declaration("clause_structure", {"kind": "record"}),
            declaration("vp_complementation", {"kind": "record"}),
            declaration("np_internal_constituency", {"kind": "node", "node": "subj"}),
            declaration("np_internal_constituency", {"kind": "node", "node": "obj"}, "omitted", "intentional", "unannotated"),
            declaration("semantic_roles", {"kind": "record"}, "unannotated", "intentional", "unannotated"),
            declaration("dependencies", {"kind": "record"}, evidence="empty"),
        )
        record["dependencies"] = []
        payload = linguistic_projection(record)
        self.assertIn("clauses", payload)
        self.assertIn("constituents", payload)
        self.assertEqual(payload["dependencies"], [])
        self.assertNotIn("semantic_roles", payload)
        by_id = {item["id"]: item for item in payload["constituents"]}
        self.assertIn("phrase_category", by_id["subj"])
        self.assertIn("obj", by_id)
        self.assertNotIn("phrase_category", by_id["obj"])


if __name__ == "__main__":
    unittest.main()
