from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from scripts.data_common import read_jsonl
from scripts.migrate_v021 import migrate
from scripts.render_sft import render_record
from scripts.train_sft import validate_training_input
from scripts.validate_dataset import coverage_allows_score, validate_record


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = read_jsonl(ROOT / "data" / "gold" / "fixtures.jsonl")[0][1]


class OntologyV031Tests(unittest.TestCase):
    def test_determinative_category_and_determiner_function(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["constituents"].append({"id": "det", "span": {"start": 0, "end": 1}, "node_kind": "phrase", "phrase_category": "DetP", "function": "determiner"})
        self.assertEqual(validate_record(record, "det"), [])
        record["words"][0]["lexical_category"] = "determiner"
        self.assertTrue(any("lexical category" in error for error in validate_record(record, "det")))

    def test_unresolved_candidates_are_framework_attributed_and_not_gold(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["words"][0]["lexical_category"] = None
        record["words"][0]["lexical_analysis"] = {"status": "unresolved", "review_required": True, "candidates": [{"lexical_category": "pronoun", "framework": "cgel_inspired"}, {"lexical_category": "subordinator", "framework": "traditional_pedagogical"}]}
        record["review_metadata"]["review_status"] = "review_required"
        self.assertEqual(validate_record(record, "uncertain"), [])
        record["review_metadata"]["review_status"] = "canonical_gold"
        self.assertTrue(any("cannot be canonical_gold" in error for error in validate_record(record, "uncertain")))

    def test_clause_construction_and_integration_are_composable(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["sentence_type"] = "interrogative"
        record["clauses"][0]["clause_construction"] = "interrogative"
        self.assertEqual(validate_record(record, "root-interrogative"), [])
        record["clauses"].append({"id": "c1", "node_kind": "clause", "span": {"start": 0, "end": 2}, "finiteness": "finite", "clause_construction": "coordinate", "integration": ["subordinate", "coordinate_member"]})
        record["clauses"].append({"id": "c2", "node_kind": "clause", "span": {"start": 0, "end": 2}, "finiteness": "finite", "clause_construction": "relative", "integration": ["supplementary"]})
        record["constituents"].append({"id": "r", "node_kind": "clause", "clause_ref": "c2", "span": {"start": 0, "end": 2}, "function": "relative_modifier", "realization": {"clause_ref": "c2", "relation": "same_span_alias"}})
        self.assertEqual(validate_record(record, "composable"), [])

    def test_clause_realization_is_single_source_of_truth(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["constituents"].append({"id": "c", "node_kind": "clause", "clause_ref": "c0", "span": {"start": 0, "end": 5}, "function": "complement"})
        self.assertTrue(any("realization" in error for error in validate_record(record, "realization")))

    def test_scoped_coverage_distinguishes_empty_and_unannotated(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["annotation_scope"]["dimensions"] = [
            {"dimension": "tokens", "scope": {"kind": "record"}, "completeness": "complete", "omission": "none", "evidence": "present"},
            {"dimension": "lexical_category", "scope": {"kind": "record"}, "completeness": "complete", "omission": "none", "evidence": "present"},
            {"dimension": "phrase_constituency", "scope": {"kind": "record"}, "completeness": "partial", "omission": "none", "evidence": "present"},
            {"dimension": "syntactic_function", "scope": {"kind": "record"}, "completeness": "partial", "omission": "none", "evidence": "present"},
            {"dimension": "clause_ontology", "scope": {"kind": "record"}, "completeness": "partial", "omission": "none", "evidence": "present"},
            {"dimension": "np_internal_constituency", "scope": {"kind": "node", "node": "subj"}, "completeness": "complete", "omission": "none", "evidence": "present"},
            {"dimension": "dependencies", "scope": {"kind": "record"}, "completeness": "complete", "omission": "none", "evidence": "empty"},
        ]
        record["dependencies"] = []
        record["annotation_scope"]["annotated_dimensions"] = ["np_internal_constituency", "dependencies"]
        record["annotation_scope"]["intentionally_omitted"] = []
        self.assertEqual(validate_record(record, "coverage"), [])
        self.assertTrue(coverage_allows_score(record, "np_internal_constituency", "subj"))
        record["annotation_scope"]["dimensions"].append({"dimension": "dependencies", "scope": {"kind": "record"}, "completeness": "partial", "omission": "intentional", "evidence": "unannotated"})
        self.assertTrue(any("same dimension + scope" in error for error in validate_record(record, "coverage-conflict")))

    def test_complete_constituency_requires_structure(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["constituents"] = []
        record["annotation_scope"] = {"coverage": "complete_constituency", "dimensions": [{"dimension": d, "scope": {"kind": "record"}, "completeness": "complete", "omission": "none"} for d in ("tokens", "lexical_category", "phrase_constituency", "clause_ontology", "syntactic_function")]}
        self.assertTrue(any("actual constituent structure" in error for error in validate_record(record, "complete")))

    def test_capability_without_required_coverage_is_rejected(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["capability_tags"] = ["semantic_roles"]
        record["annotation_scope"]["dimensions"] = [{"dimension": "semantic_roles", "scope": {"kind": "record"}, "completeness": "partial", "omission": "intentional", "evidence": "unannotated"}]
        self.assertEqual(validate_record(record, "capability-mismatch"), [])

    def test_migration_version_gate_and_idempotence(self) -> None:
        record = {"schema_version": "0.2", "id": "legacy", "words": [], "clauses": [{"id": "c", "span": {"start": 0, "end": 1}, "node_kind": "clause", "finiteness": "finite", "clause_category": "finite_clause", "function": "main"}], "constituents": [], "dependencies": []}
        migrate(record)
        self.assertEqual(record["schema_version"], "0.4")
        self.assertTrue(record["migration_review_required"])
        self.assertEqual(record["clauses"][0]["legacy_clause_category"], "finite_clause")
        self.assertEqual(record["clauses"][0]["legacy_function"], "main")
        once = copy.deepcopy(record)
        migrate(record)
        self.assertEqual(record, once)
        higher = {"schema_version": "0.4", "review_metadata": {"review_status": "canonical_gold", "reviewer_type": "human_annotation", "migration_version": "x", "review_date": "d", "provenance": "p"}}
        before = copy.deepcopy(higher)
        migrate(higher)
        self.assertEqual(higher, before)
        source_review = copy.deepcopy(record)
        source_review["schema_version"] = "0.2"
        source_review["review_metadata"] = {"review_status": "review_required", "reviewer_type": "human_annotation", "migration_version": "old", "review_date": "2020-01-01", "provenance": "annotator"}
        before_metadata = copy.deepcopy(source_review["review_metadata"])
        migrate(source_review)
        self.assertEqual(source_review["review_metadata"], before_metadata)

    def test_migration_does_not_infer_from_surface_markers(self) -> None:
        record = {
            "schema_version": "0.2",
            "id": "surface-only",
            "words": [
                {"id": "w0", "form": "If", "lemma": "if", "lexical_category": "subordinator"},
                {"id": "w1", "form": "for", "lemma": "for", "lexical_category": "preposition"},
                {"id": "w2", "form": "to", "lemma": "to", "lexical_category": "subordinator"},
            ],
            "clauses": [{"id": "c", "span": {"start": 0, "end": 3}, "finiteness": "finite"}],
            "constituents": [],
            "dependencies": [],
        }
        migrate(record)
        clause = record["clauses"][0]
        self.assertEqual(clause["clause_construction"], "unresolved")
        self.assertEqual(clause["integration"], ["unresolved"])
        self.assertNotIn("marker_ids", clause)
        self.assertEqual([word["lexical_category"] for word in record["words"]], ["subordinator", "preposition", "subordinator"])

    def test_migration_maps_only_tagged_legacy_pos(self) -> None:
        record = {
            "schema_version": "0.2",
            "id": "legacy-pos",
            "words": [
                {"id": "w0", "form": "x", "lemma": "x", "lexical_category": "noun", "pos": "NN", "pos_tagset": "PTB"},
                {"id": "w1", "form": "y", "lemma": "y", "lexical_category": "noun", "pos": "N", "external_pos_tags": [{"tagset": "UD", "tag": "NOUN"}]},
            ],
            "clauses": [],
            "constituents": [],
            "dependencies": [],
        }
        migrate(record)
        self.assertEqual(record["words"][0]["external_pos_tags"], [{"tagset": "PTB", "tag": "NN"}])
        self.assertEqual(record["words"][1]["legacy_pos"], "N")
        self.assertEqual(record["review_metadata"]["review_status"], "review_required")

    def test_migration_adds_typed_clause_realization(self) -> None:
        record = {
            "schema_version": "0.2",
            "id": "legacy-wrapper",
            "words": [],
            "clauses": [{"id": "c", "span": {"start": 0, "end": 2}, "finiteness": "finite", "clause_category": "relative_clause"}],
            "constituents": [{"id": "wrap", "node_kind": "clause", "clause_ref": "c", "span": {"start": 0, "end": 2}, "function": "relative_modifier"}],
            "dependencies": [],
        }
        migrate(record)
        self.assertEqual(record["constituents"][0]["realization"], {"clause_ref": "c", "relation": "same_span_alias"})

    def test_complete_region_scoring_respects_target_span(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["annotation_scope"]["dimensions"] = [{
            "dimension": "np_internal_constituency",
            "scope": {"kind": "region", "start": 0, "end": 2},
            "completeness": "complete",
            "omission": "none",
            "evidence": "present",
        }]
        self.assertTrue(coverage_allows_score(record, "np_internal_constituency", "subj"))
        self.assertFalse(coverage_allows_score(record, "np_internal_constituency", "obj"))

    def test_renderer_sidecar_and_training_gate(self) -> None:
        fixture = copy.deepcopy(FIXTURE)
        fixture["migration_review_required"] = True
        fixture["migration_note"] = "review"
        rendered = render_record(fixture)
        payload = json.loads(rendered["messages"][2]["content"])
        self.assertNotIn("review_metadata", payload)
        self.assertNotIn("migration_review_required", payload)
        self.assertIn("review_metadata", rendered["governance_sidecar"])
        self.assertTrue(rendered["governance_sidecar"]["migration_review_required"])
        path = ROOT / "data" / "splits" / "train_fixture.jsonl"
        self.assertTrue(any("not approved" in error for error in validate_training_input([path])))
        benchmark = ROOT / "eval" / "benchmark_v1.jsonl"
        self.assertTrue(any("benchmark split" in error for error in validate_training_input([benchmark])))
        self.assertTrue(validate_training_input([path], development_mode=True) == [])


if __name__ == "__main__":
    unittest.main()
