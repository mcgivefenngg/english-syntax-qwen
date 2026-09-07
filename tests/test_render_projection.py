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
    def test_clause_ontology_alone_does_not_emit_unrelated_constituents(self) -> None:
        record = record_with(declaration("clause_ontology", {"kind": "record"}))
        payload = linguistic_projection(record)
        self.assertIn("clauses", payload)
        self.assertNotIn("constituents", payload)

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
        for constituent in record["constituents"]:
            constituent.pop("phrase_category", None)
        constituents = linguistic_projection(record)["constituents"]
        self.assertEqual(constituents, [{"id": "obj", "node_kind": "phrase", "span": {"start": 3, "end": 5}, "function": "object"}])

    def test_subject_internal_structure_is_kept_object_internal_is_omitted(self) -> None:
        record = record_with(
            declaration("np_internal_constituency", {"kind": "node", "node": "subj"}),
            declaration("syntactic_function", {"kind": "node", "node": "obj"}),
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
        record["constituents"][1].pop("phrase_category", None)
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
        record["canonical_analysis"]["typed_analysis"]["status"] = "established"
        payload = linguistic_projection(record)
        self.assertEqual(payload["words"], [{"id": "w1", "node_kind": "word"}])
        self.assertEqual(payload["constituents"], [{"id": "obj", "node_kind": "phrase", "span": {"start": 3, "end": 5}}])

    def test_clause_valued_constituent_shell_stays_in_constituents(self) -> None:
        record = record_with(declaration("construction_relations", {"kind": "record"}))
        record["constituents"].append({
            "id": "emb", "node_kind": "clause", "clause_ref": "c0", "span": {"start": 3, "end": 5},
            "function": "complement",
        })
        record["canonical_analysis"]["typed_analysis"]["relations"] = [{
            "id": "rel-1", "type": "cross_node", "arity": "binary",
            "source": {"namespace": "word", "id": "w1"},
            "target": {"namespace": "constituent", "id": "emb"},
        }]
        record["canonical_analysis"]["typed_analysis"]["status"] = "established"
        payload = linguistic_projection(record)
        self.assertEqual([item["id"] for item in payload["constituents"]], ["emb"])
        self.assertNotIn("emb", {item["id"] for item in payload.get("clauses", [])})

    def test_true_clause_shell_stays_in_clauses(self) -> None:
        record = record_with(declaration("construction_relations", {"kind": "record"}))
        record["canonical_analysis"]["typed_analysis"]["relations"] = [{
            "id": "rel-1", "type": "cross_node", "arity": "binary",
            "source": {"namespace": "word", "id": "w1"},
            "target": {"namespace": "clause", "id": "c0"},
        }]
        record["canonical_analysis"]["typed_analysis"]["status"] = "established"
        payload = linguistic_projection(record)
        self.assertEqual(payload["clauses"], [{"id": "c0", "node_kind": "clause", "span": {"start": 0, "end": 5}}])
        self.assertNotIn("c0", {item["id"] for item in payload.get("constituents", [])})

    def test_typed_relation_does_not_leak_omitted_node_properties(self) -> None:
        record = record_with(declaration("construction_relations", {"kind": "record"}))
        record["canonical_analysis"]["typed_analysis"]["relations"] = [{
            "id": "rel-1", "type": "cross_node", "arity": "binary",
            "source": {"namespace": "word", "id": "w1"},
            "target": {"namespace": "constituent", "id": "obj"},
        }]
        record["canonical_analysis"]["typed_analysis"]["status"] = "established"
        node = linguistic_projection(record)["constituents"][0]
        self.assertNotIn("phrase_category", node)
        self.assertNotIn("function", node)
        self.assertNotIn("head", node)

    def test_tokens_only_coverage_does_not_expose_typed_argument_properties(self) -> None:
        record = record_with(declaration("tokens", {"kind": "record"}))
        record["canonical_analysis"]["typed_analysis"]["arguments"] = [{
            "id": "arg-1", "kind": "argument", "target": "constituent:obj",
            "role": "Theme", "function": "object", "category": "NP",
        }]
        payload = linguistic_projection(record)
        typed = payload.get("canonical_analysis", {}).get("typed_analysis", {})
        self.assertNotIn("arguments", typed)
        self.assertNotIn("role", json.dumps(payload))
        self.assertNotIn("function", json.dumps(payload))
        self.assertNotIn("category", json.dumps(payload))
        self.assertNotIn("constituent:obj", json.dumps(payload))

    def test_covered_typed_relation_retains_only_authorized_semantic_properties(self) -> None:
        record = record_with(
            declaration("construction_relations", {"kind": "record"}),
            declaration("semantic_roles", {"kind": "record"}),
            declaration("syntactic_function", {"kind": "node", "node": "obj"}),
        )
        record["canonical_analysis"]["typed_analysis"]["relations"] = [{
            "id": "rel-1", "type": "cross_node", "arity": "binary",
            "source": {"namespace": "word", "id": "w1"},
            "target": {"namespace": "constituent", "id": "obj"},
        }]
        record["canonical_analysis"]["typed_analysis"]["status"] = "established"
        record["semantic_roles"] = [{"constituent": "obj", "role": "Theme", "predicate": "w2"}]
        relation = linguistic_projection(record)["canonical_analysis"]["typed_analysis"]["relations"][0]
        self.assertEqual(relation["type"], "cross_node")
        self.assertEqual(relation["arity"], "binary")
        self.assertNotIn("role", relation)
        self.assertNotIn("function", relation)
        self.assertNotIn("category", relation)

    def test_typed_relation_is_absent_under_empty_or_unannotated_owner(self) -> None:
        for entry in (
            declaration("dependencies", {"kind": "record"}, evidence="empty"),
            declaration("dependencies", {"kind": "record"}, "unannotated", "intentional", "unannotated"),
        ):
            with self.subTest(entry=entry):
                record = record_with(entry)
                record["canonical_analysis"]["typed_analysis"]["relations"] = [{
                    "id": "rel-1", "type": "dependency", "arity": "binary",
                    "source": {"namespace": "word", "id": "w1"},
                    "target": {"namespace": "constituent", "id": "obj"},
                }]
                payload = linguistic_projection(record)
                typed = payload.get("canonical_analysis", {}).get("typed_analysis", {})
                self.assertNotIn("relations", typed)

    def test_complements_filter_omitted_target(self) -> None:
        record = record_with(
            declaration("syntactic_function", {"kind": "node", "node": "obj"}),
        )
        record["complements"] = ["obj", "subj"]
        payload = linguistic_projection(record)
        self.assertEqual(payload["complements"], ["obj"])

    def test_adjuncts_filter_omitted_target(self) -> None:
        record = record_with(
            declaration("vp_complementation", {"kind": "node", "node": "obj"}),
        )
        record["adjuncts"] = ["obj", "ghost"]
        payload = linguistic_projection(record)
        self.assertEqual(payload["adjuncts"], ["obj"])

    def test_convenience_list_filtering_has_no_dangling_references(self) -> None:
        record = record_with(
            declaration("syntactic_function", {"kind": "node", "node": "obj"}),
            declaration("syntactic_function", {"kind": "node", "node": "subj"}, "omitted", "intentional", "unannotated"),
        )
        record["complements"] = ["obj", "subj"]
        record["adjuncts"] = ["obj", "subj"]
        self.assertEqual(validate_record(render_record(record), "convenience-rendered"), [])

    def test_unrelated_region_coverage_does_not_authorize_another_node(self) -> None:
        record = record_with(
            declaration("np_internal_constituency", {"kind": "node", "node": "subj"}),
            declaration("syntactic_function", {"kind": "region", "start": 0, "end": 2}),
        )
        record["constituents"].append({
            "id": "obj-det", "node_kind": "phrase", "span": {"start": 3, "end": 4},
            "parent": "obj", "function": "determiner", "phrase_category": "DetP",
        })
        payload = linguistic_projection(record)
        self.assertNotIn("obj-det", {item["id"] for item in payload.get("constituents", [])})

    def test_construction_signature_does_not_leak_through_unrelated_dimension(self) -> None:
        record = record_with(
            declaration("vp_complementation", {"kind": "record"}),
            declaration("construction_relations", {"kind": "record"}, "unannotated", "intentional", "unannotated"),
        )
        record["construction_type"] = "transitive"
        record["construction_tags"] = ["transitive"]
        record["construction_signature"] = {
            "predicate_lemma": "catalogue", "construction_type": "transitive",
            "argument_pattern": ["Subject", "Object"], "function_pattern": ["subject", "object"],
        }
        payload = linguistic_projection(record)
        self.assertNotIn("construction_type", payload)
        self.assertNotIn("construction_tags", payload)
        self.assertNotIn("construction_signature", payload)

    def test_construction_type_and_tags_follow_construction_relation_authority(self) -> None:
        record = record_with(declaration("construction_relations", {"kind": "record"}))
        record["construction_type"] = "transitive"
        record["construction_tags"] = ["transitive"]
        payload = linguistic_projection(record)
        self.assertEqual(payload["construction_type"], "transitive")
        self.assertEqual(payload["construction_tags"], ["transitive"])

    def test_declaration_order_does_not_change_projection(self) -> None:
        entries = [
            declaration("phrase_constituency", {"kind": "node", "node": "subj"}),
            declaration("phrase_constituency", {"kind": "node", "node": "obj"}, "omitted", "intentional", "unannotated"),
            declaration("syntactic_function", {"kind": "record"}),
        ]
        record = record_with(*entries)
        record["constituents"][1].pop("phrase_category", None)
        reverse = record_with(*reversed(entries))
        reverse["constituents"][1].pop("phrase_category", None)
        self.assertEqual(linguistic_projection(record), linguistic_projection(reverse))

    def test_rendered_projection_has_no_dangling_references(self) -> None:
        record = record_with(declaration("dependencies", {"kind": "record"}))
        record["dependencies"] = [{"relation": "selected", "head": "w2", "dependent": "obj"}]
        self.assertEqual(validate_record(render_record(record), "rendered"), [])

    def test_minimal_shell_does_not_restore_uncovered_truth_for_validation(self) -> None:
        record = record_with(declaration("construction_relations", {"kind": "record"}))
        record["canonical_analysis"]["typed_analysis"]["relations"] = [{
            "id": "rel-1", "type": "cross_node", "arity": "binary",
            "source": {"namespace": "word", "id": "w1"},
            "target": {"namespace": "constituent", "id": "obj"},
        }]
        record["canonical_analysis"]["typed_analysis"]["status"] = "established"
        rendered = render_record(record)
        self.assertEqual(validate_record(rendered, "minimal-shell-rendered"), [])
        node = json.loads(rendered["messages"][2]["content"])["constituents"][0]
        self.assertEqual(set(node), {"id", "node_kind", "span"})

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
            declaration("syntactic_function", {"kind": "node", "node": "obj"}),
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
