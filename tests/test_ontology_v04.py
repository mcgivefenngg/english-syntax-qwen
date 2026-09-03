from __future__ import annotations

import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.data_common import read_jsonl
from scripts.migrate_v021 import migrate
from scripts.render_sft import linguistic_projection, render_record
from scripts.repair_v031_data import repair_file
from scripts.train_sft import validate_training_input
from scripts.validate_dataset import coverage_allows_score, validate_record


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = read_jsonl(ROOT / "data" / "gold" / "fixtures.jsonl")[0][1]


class OntologyV04Tests(unittest.TestCase):
    def test_contract_identity_and_legacy_rejection(self) -> None:
        schema = json.loads((ROOT / "schemas" / "gold_annotation.schema.json").read_text())
        rendered = json.loads((ROOT / "schemas" / "rendered_sft_target.schema.json").read_text())
        self.assertEqual(schema["$id"], "https://english-syntax-tutor.local/schema/gold-annotation-0.4.json")
        self.assertEqual(rendered["$id"], "https://english-syntax-tutor.local/schema/rendered-sft-target-0.4.json")
        old = copy.deepcopy(FIXTURE)
        old["schema_version"] = "0.3"
        self.assertTrue(any("schema_version" in error for error in validate_record(old, "legacy")))

    def test_real_v02_fixture_migrates_to_v04(self) -> None:
        output = subprocess.check_output(["git", "show", "v0.2.1:data/gold/fixtures.jsonl"], cwd=ROOT, text=True)
        source = json.loads(output.splitlines()[0])
        self.assertEqual(source["schema_version"], "0.2")
        migrate(source)
        self.assertEqual(source["schema_version"], "0.4")
        self.assertEqual(validate_record(source, "migrated"), [])

    def test_v04_migration_is_exact_noop_and_unknown_rejected(self) -> None:
        record = copy.deepcopy(FIXTURE)
        before = copy.deepcopy(record)
        self.assertIs(migrate(record), record)
        self.assertEqual(record, before)
        with self.assertRaises(ValueError):
            migrate({"schema_version": "0.2.1"})

    def test_legacy_alternative_migration_stays_review_required(self) -> None:
        record = {"schema_version": "0.2", "id": "legacy-alt", "framework": {"preferred": "cgel_inspired", "alternatives": [{"framework": "traditional_pedagogical", "status": "established", "analysis": "legacy prose"}]}, "words": [], "clauses": [], "constituents": [], "dependencies": []}
        migrate(record)
        alternative = record["alternative_analyses"][0]
        self.assertEqual(alternative["status"], "review_required")
        self.assertEqual(alternative["typed_analysis"]["status"], "review_required")
        self.assertTrue(record.get("migration_review_required"))
        self.assertNotIn("alternatives", record["framework"])
        self.assertNotIn("framework_alternatives", record)

    def test_fixture_repairs_require_manifest_and_reject_approved(self) -> None:
        record = copy.deepcopy(FIXTURE)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "records.jsonl"
            manifest = Path(directory) / "manifest.json"
            path.write_text(json.dumps(record) + "\n")
            with self.assertRaises(ValueError):
                repair_file(path)
            manifest.write_text(json.dumps({"records": [{"id": record["id"], "source_version": "0.4"}]}))
            repair_file(path, manifest)
            once = path.read_text()
            repair_file(path, manifest)
            self.assertEqual(path.read_text(), once)
            approved = json.loads(once)
            approved["review_metadata"]["review_status"] = "approved_for_training"
            path.write_text(json.dumps(approved) + "\n")
            with self.assertRaises(ValueError):
                repair_file(path, manifest)

    def test_geometry_never_guesses_shared_subject(self) -> None:
        record = {"schema_version": "0.2", "id": "geometry", "words": [], "clauses": [{"id": "c", "span": {"start": 0, "end": 2}, "finiteness": "finite"}], "constituents": [{"id": "w", "node_kind": "clause", "clause_ref": "c", "span": {"start": 1, "end": 3}, "function": "adjunct"}], "dependencies": []}
        migrate(record)
        self.assertEqual(record["constituents"][0]["realization"]["relation"], "other")
        self.assertTrue(record.get("migration_review_required"))

    def test_free_text_only_analysis_is_not_authoritative(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["canonical_analysis"].pop("typed_analysis")
        self.assertTrue(any("typed_analysis" in error for error in validate_record(record, "prose-only")))

    def test_lexical_candidate_requires_namespace_and_keeps_pos_separate(self) -> None:
        record = copy.deepcopy(FIXTURE)
        word = record["words"][0]
        word["lexical_category"] = None
        word["lexical_analysis"] = {"status": "unresolved", "review_required": True, "candidates": [{"category": "pronoun"}]}
        self.assertTrue(any("namespace" in error for error in validate_record(record, "candidate")))
        word["lexical_analysis"]["candidates"][0]["category_namespace"] = "project_canonical"
        word["external_pos_tags"] = [{"tagset": "UD", "tag": "PRON"}]
        self.assertEqual(validate_record(record, "candidate"), [])

    def test_sentence_mood_and_integration_single_truth(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["sentence_type"] = "interrogative"
        self.assertTrue(any("contradict" in error for error in validate_record(record, "mood")))
        record["clauses"][0]["integration"] = ["root", "unresolved"]
        self.assertTrue(any("mix unresolved" in error for error in validate_record(record, "integration")))

    def test_conflicting_clause_wrappers_require_alternative(self) -> None:
        record = copy.deepcopy(FIXTURE)
        for identifier, function in (("a", "complement"), ("b", "adjunct")):
            record["constituents"].append({"id": identifier, "node_kind": "clause", "clause_ref": "c0", "span": {"start": 0, "end": 5}, "function": function, "realization": {"clause_ref": "c0", "relation": "same_span_alias"}})
        self.assertTrue(any("conflicting canonical wrapper" in error for error in validate_record(record, "wrappers")))
        record["ambiguity"] = {"status": "genuinely_ambiguous", "analyses": [{"id": "a", "structural_claims": [], "interpretation": "one", "wrapper_ids": ["a"]}, {"id": "b", "structural_claims": [], "interpretation": "two", "wrapper_ids": ["b"]}]}
        self.assertFalse(any("conflicting canonical wrapper" in error for error in validate_record(record, "wrappers-alt")))

    def test_scoped_coverage_and_scoring(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["annotation_scope"]["dimensions"] = [
            {"dimension": "np_internal_constituency", "scope": {"kind": "node", "node": "subj"}, "completeness": "complete", "omission": "none", "evidence": "present"},
            {"dimension": "np_internal_constituency", "scope": {"kind": "node", "node": "obj"}, "completeness": "omitted", "omission": "intentional", "evidence": "unannotated"},
            {"dimension": "semantic_roles", "scope": {"kind": "record"}, "completeness": "partial", "omission": "intentional", "evidence": "unannotated"},
            {"dimension": "dependencies", "scope": {"kind": "record"}, "completeness": "complete", "omission": "none", "evidence": "empty"},
        ]
        record["dependencies"] = []
        self.assertEqual(validate_record(record, "scoped"), [])
        self.assertTrue(coverage_allows_score(record, "np_internal_constituency", "subj"))
        self.assertFalse(coverage_allows_score(record, "np_internal_constituency", "obj"))
        record["annotation_scope"]["dimensions"][0]["completeness"] = "partial"
        self.assertTrue(coverage_allows_score(record, "np_internal_constituency", "subj"))
        record["annotation_scope"]["dimensions"].append(
            {"dimension": "np_internal_constituency", "scope": {"kind": "node", "node": "obj"}, "completeness": "omitted", "omission": "intentional", "evidence": "unannotated"}
        )
        self.assertFalse(coverage_allows_score(record, "np_internal_constituency", "obj"))
        record["annotation_scope"]["dimensions"] = [
            {"dimension": "semantic_roles", "scope": {"kind": "record"}, "completeness": "partial", "omission": "none", "evidence": "present"}
        ]
        self.assertFalse(coverage_allows_score(record, "semantic_roles", "obj"))

    def test_renderer_distinguishes_empty_from_unannotated_and_allowlists(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["annotation_scope"]["dimensions"] = [
            {"dimension": "clause_ontology", "scope": {"kind": "record"}, "completeness": "complete", "omission": "none", "evidence": "present"},
            {"dimension": "dependencies", "scope": {"kind": "record"}, "completeness": "partial", "omission": "intentional", "evidence": "unannotated"},
            {"dimension": "semantic_roles", "scope": {"kind": "record"}, "completeness": "partial", "omission": "intentional", "evidence": "unannotated"},
        ]
        record["dependencies"] = []
        record["semantic_roles"] = []
        record["future_governance"] = {"secret": True}
        record["clauses"][0]["adjudication_notes"] = "secret"
        record["canonical_analysis"]["typed_analysis"]["status"] = "review_required"
        payload = linguistic_projection(record)
        self.assertNotIn("dependencies", payload)
        self.assertNotIn("semantic_roles", payload)
        self.assertNotIn("future_governance", payload)
        self.assertNotIn("adjudication_notes", payload["clauses"][0])
        self.assertNotIn("status", payload["canonical_analysis"]["typed_analysis"])
        dependency_scope = next(
            entry for entry in record["annotation_scope"]["dimensions"]
            if entry["dimension"] == "dependencies"
        )
        dependency_scope["completeness"] = "complete"
        dependency_scope["omission"] = "none"
        dependency_scope["evidence"] = "empty"
        self.assertEqual(linguistic_projection(record)["dependencies"], [])

    def test_renderer_requires_explicit_mode_for_lexical_candidates(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["annotation_scope"]["dimensions"] = [
            {"dimension": "tokens", "scope": {"kind": "record"}, "completeness": "complete", "omission": "none", "evidence": "present"},
            {"dimension": "lexical_category", "scope": {"kind": "record"}, "completeness": "complete", "omission": "none", "evidence": "present"},
        ]
        record["words"][0]["lexical_category"] = None
        record["words"][0]["lexical_analysis"] = {
            "status": "unresolved",
            "review_required": True,
            "candidates": [{"category": "pronoun", "category_namespace": "project_canonical", "status": "unresolved"}],
        }
        record["ambiguity"] = {
            "status": "genuinely_ambiguous",
            "analyses": [{"id": "a", "structural_claims": ["one"], "interpretation": "one"}, {"id": "b", "structural_claims": ["two"], "interpretation": "two"}],
        }
        record["annotation_scope"]["dimensions"].append(
            {"dimension": "ambiguity", "scope": {"kind": "record"}, "completeness": "complete", "omission": "none", "evidence": "present"}
        )
        default = linguistic_projection(record)
        self.assertNotIn("lexical_analysis", default["words"][0])
        self.assertEqual(default["ambiguity"]["status"], "genuinely_ambiguous")
        candidate_mode = linguistic_projection(record, rendering_mode="learner_facing")
        self.assertIn("lexical_analysis", candidate_mode["words"][0])
        self.assertNotIn("status", candidate_mode["words"][0]["lexical_analysis"])
        self.assertNotIn("status", candidate_mode["words"][0]["lexical_analysis"]["candidates"][0])
        with self.assertRaises(ValueError):
            linguistic_projection(record, rendering_mode="governance")

    def test_rendered_validator_rejects_nested_governance_leak(self) -> None:
        fixture = copy.deepcopy(FIXTURE)
        fixture["annotation_scope"]["dimensions"] = [
            {"dimension": "clause_ontology", "scope": {"kind": "record"}, "completeness": "complete", "omission": "none", "evidence": "present"},
        ]
        rendered = render_record(fixture)
        payload = json.loads(rendered["messages"][2]["content"])
        payload["clauses"][0]["review_required"] = True
        rendered["messages"][2]["content"] = json.dumps(payload)
        self.assertTrue(any("governance-only" in error for error in validate_record(rendered, "rendered-leak")))

    def _approved(self) -> dict:
        record = copy.deepcopy(FIXTURE)
        record["review_metadata"].update(review_status="approved_for_training", reviewer_type="human_annotation")
        record["canonical_analysis"]["typed_analysis"]["status"] = "established"
        return record

    def test_training_approval_content_gate(self) -> None:
        record = self._approved()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.jsonl"
            path.write_text(json.dumps(record) + "\n")
            self.assertEqual(validate_training_input([path]), [])
            record["review_metadata"]["review_status"] = "linguistically_reviewed"
            path.write_text(json.dumps(record) + "\n")
            self.assertTrue(validate_training_input([path]))
            record["review_metadata"]["review_status"] = "approved_for_training"
            record["words"][0]["lexical_category"] = None
            record["words"][0]["lexical_analysis"] = {"status": "unresolved", "review_required": True, "candidates": [{"category": "pronoun", "category_namespace": "project_canonical"}]}
            path.write_text(json.dumps(record) + "\n")
            self.assertTrue(any("unresolved" in error for error in validate_training_input([path])))
            record["split"] = "benchmark"
            path.write_text(json.dumps(record) + "\n")
            self.assertTrue(any("benchmark" in error for error in validate_training_input([path])))

    def test_rendered_approved_target_uses_content_snapshot(self) -> None:
        record = self._approved()
        record["canonical_analysis"]["typed_analysis"]["status"] = "review_required"
        rendered = render_record(record)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rendered.jsonl"
            path.write_text(json.dumps(rendered) + "\n")
            self.assertTrue(any("unresolved linguistic content" in error for error in validate_training_input([path])))

    def test_canonical_gold_invariant_and_established_alternative(self) -> None:
        record = self._approved()
        record["review_metadata"]["review_status"] = "canonical_gold"
        record["words"][0]["lexical_category"] = None
        record["words"][0]["lexical_analysis"] = {"status": "unresolved", "review_required": True, "candidates": [{"category": "pronoun", "category_namespace": "project_canonical"}]}
        self.assertTrue(any("canonical_gold" in error for error in validate_record(record, "canonical")))
        record = self._approved()
        record["review_metadata"]["review_status"] = "canonical_gold"
        record["clauses"][0]["finiteness"] = "unspecified"
        self.assertTrue(any("canonical_gold" in error for error in validate_record(record, "canonical-finiteness")))
        record = self._approved()
        record["alternative_analyses"] = [{"id": "modern-alt", "label": "established", "claims": ["external framework reading"], "framework": "modern_descriptive", "status": "established", "typed_analysis": {"kind": "alternative", "framework": "modern_descriptive", "status": "established"}}]
        self.assertEqual(validate_record(record, "alternative"), [])

    def test_validator_does_not_adjudicate_construction_geometry(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["words"][0]["lexical_category"] = "noun"
        record["clauses"].append({"id": "c1", "node_kind": "clause", "span": {"start": 0, "end": 2}, "finiteness": "nonfinite", "clause_form": "to_infinitival", "clause_construction": "other", "integration": ["subordinate"], "predicand": {"kind": "overt_constituent", "target": "w0"}})
        self.assertFalse(any("overt 'to'" in error or "predicand" in error and "NP" in error for error in validate_record(record, "construction-policy")))
        record["semantic_roles"] = [{"constituent": "obj", "role": "Theme", "predicate": "w0"}]
        self.assertFalse(any("must be verbal" in error for error in validate_record(record, "construction-policy-role")))

    def _typed_relation_record(self) -> dict:
        record = copy.deepcopy(FIXTURE)
        record["canonical_analysis"]["typed_analysis"]["relations"] = [{
            "id": "rel-1",
            "type": "dependency",
            "arity": "binary",
            "source": {"namespace": "word", "id": "w1"},
            "target": {"namespace": "constituent", "id": "obj"},
        }]
        return record

    def test_typed_relations_require_structured_non_dangling_references(self) -> None:
        for relation, expected in (({}, "typed relation"), ("not-an-object", "typed relation")):
            record = copy.deepcopy(FIXTURE)
            record["canonical_analysis"]["typed_analysis"]["relations"] = [relation]
            self.assertTrue(any(expected in error for error in validate_record(record, "typed-shape")))
        for field in ("source", "target"):
            record = self._typed_relation_record()
            record["canonical_analysis"]["typed_analysis"]["relations"][0][field] = {"namespace": "constituent", "id": "missing"}
            self.assertTrue(any(f"dangling typed constituent reference" in error for error in validate_record(record, f"typed-{field}")))

    def test_typed_relation_ids_and_authority_layer_are_deterministic(self) -> None:
        record = self._typed_relation_record()
        record["canonical_analysis"]["typed_analysis"]["relations"].append(copy.deepcopy(record["canonical_analysis"]["typed_analysis"]["relations"][0]))
        self.assertTrue(any("duplicate typed relation id" in error for error in validate_record(record, "typed-duplicate")))
        record = self._typed_relation_record()
        record["alternative_analyses"] = [{"id": "alt-rel", "framework": "modern_descriptive", "status": "established", "typed_analysis": {"kind": "alternative", "framework": "modern_descriptive", "status": "established", "relations": [copy.deepcopy(record["canonical_analysis"]["typed_analysis"]["relations"][0])]}}]
        self.assertTrue(any("unique within the record" in error for error in validate_record(record, "typed-cross-analysis-duplicate")))
        record = copy.deepcopy(FIXTURE)
        record["canonical_analysis"]["typed_analysis"]["relations"] = [{
            "id": "rel-function",
            "type": "function",
            "arity": "binary",
            "source": {"namespace": "constituent", "id": "obj"},
            "target": {"namespace": "clause", "id": "c0"},
        }]
        self.assertTrue(any("canonical scalar" in error for error in validate_record(record, "typed-authority")))
        record = self._typed_relation_record()
        record["dependencies"] = [{"relation": "canonical", "head": "w1", "dependent": "obj"}]
        self.assertTrue(any("duplicates the canonical dependencies layer" in error for error in validate_record(record, "typed-dependency-authority")))
        record = self._typed_relation_record()
        relation = record["canonical_analysis"]["typed_analysis"]["relations"][0]
        relation["arity"] = "binary"
        relation.pop("target")
        self.assertTrue(any("requires target" in error for error in validate_record(record, "typed-binary")))
        record = self._typed_relation_record()
        relation = record["canonical_analysis"]["typed_analysis"]["relations"][0]
        relation["arity"] = "unary"
        self.assertTrue(any("cannot carry target" in error for error in validate_record(record, "typed-unary")))
        relation["target"] = None
        self.assertTrue(any("cannot carry target" in error for error in validate_record(record, "typed-unary-null-target")))
        relation["type"] = "project:property"
        relation.pop("target")
        self.assertEqual(validate_record(record, "typed-unary-valid"), [])
        record = self._typed_relation_record()
        relation = record["canonical_analysis"]["typed_analysis"]["relations"][0]
        relation.pop("arity")
        self.assertTrue(any("requires explicit arity" in error for error in validate_record(record, "typed-missing-arity")))
        relation.pop("target")
        self.assertTrue(any("requires explicit arity" in error for error in validate_record(record, "typed-missing-arity-no-target")))

    def test_extension_relation_requires_namespace_or_framework(self) -> None:
        record = self._typed_relation_record()
        relation = record["canonical_analysis"]["typed_analysis"]["relations"][0]
        relation["type"] = "future_relation"
        self.assertTrue(any("extension relation" in error for error in validate_record(record, "extension")))
        relation["type"] = "project:future_relation"
        self.assertEqual(validate_record(record, "extension-qualified"), [])
        relation["type"] = "framework_relation"
        self.assertTrue(any("framework_relation requires" in error for error in validate_record(record, "framework-relation")))
        relation["framework"] = "modern_descriptive"
        self.assertEqual(validate_record(record, "framework-relation-attributed"), [])
        relation.pop("framework")
        relation["type"] = "project:future_relation"
        relation["source"] = "word:w1"
        relation["target"] = "constituent:obj"
        self.assertEqual(validate_record(record, "extension-qualified-string-ref"), [])

    def test_alternative_authority_has_one_channel_and_stable_unique_ids(self) -> None:
        record = copy.deepcopy(FIXTURE)
        legacy = {"framework": "modern_descriptive", "status": "established", "analysis": "legacy"}
        record["framework"]["alternatives"] = [legacy]
        errors = validate_record(record, "alt-legacy")
        self.assertTrue(any("legacy/non-authoritative channel" in error for error in errors))
        self.assertTrue(any("schema validation failed" in error for error in errors))
        record = copy.deepcopy(FIXTURE)
        record["framework_alternatives"] = []
        errors = validate_record(record, "alt-parallel")
        self.assertTrue(any("framework_alternatives" in error for error in errors))
        self.assertTrue(any("schema validation failed" in error for error in errors))
        record["framework"]["alternatives"] = [legacy]
        record["legacy_alternative_metadata"] = [legacy]
        framework_scope = next(entry for entry in record["annotation_scope"]["dimensions"] if entry["dimension"] == "framework_mapping")
        framework_scope.update(completeness="complete", omission="none", evidence="present")
        projection = linguistic_projection(record)
        self.assertNotIn("framework_alternatives", projection)
        self.assertNotIn("legacy_alternative_metadata", projection)
        self.assertNotIn("alternatives", projection["framework"])
        alternative = {"id": "alt-1", "framework": "modern_descriptive", "status": "established", "claims": ["alternative"], "typed_analysis": {"kind": "alternative", "framework": "modern_descriptive", "status": "established"}}
        record = copy.deepcopy(FIXTURE)
        record["alternative_analyses"] = [copy.deepcopy(alternative), {**copy.deepcopy(alternative), "id": "alt-2"}]
        self.assertTrue(any("duplicate equivalent" in error for error in validate_record(record, "alt-equivalent")))
        record["alternative_analyses"][1]["id"] = "alt-1"
        self.assertTrue(any("duplicate alternative id" in error for error in validate_record(record, "alt-id")))

    def test_ambiguity_linkage_scopes_wrapper_conflict_suppression(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["constituents"].extend([
            {"id": "wrap-a", "node_kind": "clause", "clause_ref": "c0", "span": {"start": 0, "end": 5}, "function": "complement", "realization": {"clause_ref": "c0", "relation": "same_span_alias"}},
            {"id": "wrap-b", "node_kind": "clause", "clause_ref": "c0", "span": {"start": 0, "end": 5}, "function": "adjunct", "realization": {"clause_ref": "c0", "relation": "same_span_alias"}},
        ])
        record["ambiguity"] = {"status": "genuinely_ambiguous", "analyses": [{"id": "unrelated", "structural_claims": ["other"], "interpretation": "other", "constituent_ids": ["subj"]}, {"id": "unrelated-2", "structural_claims": ["other"], "interpretation": "other", "constituent_ids": ["subj"]}]}
        self.assertTrue(any("conflicting canonical wrapper" in error for error in validate_record(record, "ambiguity-unrelated")))
        record["ambiguity"]["analyses"] = [{"id": "linked-a", "structural_claims": ["one"], "interpretation": "one", "wrapper_ids": ["wrap-a"]}, {"id": "linked-b", "structural_claims": ["two"], "interpretation": "two", "wrapper_ids": ["wrap-b"]}]
        self.assertFalse(any("conflicting canonical wrapper" in error for error in validate_record(record, "ambiguity-linked")))
        record["ambiguity"]["analyses"][1].pop("wrapper_ids")
        self.assertTrue(any("conflicting canonical wrapper" in error for error in validate_record(record, "ambiguity-partial-link")))
        record["ambiguity"]["analyses"][1]["wrapper_ids"] = ["wrap-b"]
        relation = {"id": "wrap-relation", "type": "attachment", "arity": "binary", "source": {"namespace": "constituent", "id": "wrap-a"}, "target": {"namespace": "constituent", "id": "wrap-b"}}
        record["canonical_analysis"]["typed_analysis"]["relations"] = [relation]
        record["ambiguity"]["analyses"] = [{"id": "relation-a", "structural_claims": ["one"], "interpretation": "one", "relation_ids": ["wrap-relation"]}, {"id": "relation-b", "structural_claims": ["two"], "interpretation": "two", "relation_ids": ["wrap-relation"]}]
        self.assertFalse(any("conflicting canonical wrapper" in error for error in validate_record(record, "ambiguity-relation-linked")))
        record["ambiguity"] = {"status": "unambiguous", "analyses": [{"id": "only", "structural_claims": ["one"], "interpretation": "one", "clause_refs": ["c0"]}]}
        self.assertTrue(any("conflicting canonical wrapper" in error for error in validate_record(record, "ambiguity-unambiguous")))
        record["ambiguity"] = {"status": "genuinely_ambiguous", "analyses": [{"id": "relevant", "structural_claims": ["one"], "interpretation": "one", "clause_refs": ["c0"]}, {"id": "filler", "structural_claims": ["two"], "interpretation": "two", "constituent_ids": ["subj"]}]}
        self.assertTrue(any("conflicting canonical wrapper" in error for error in validate_record(record, "ambiguity-one-relevant-analysis")))
        record["alternative_analyses"] = [{"id": "wrap-a", "framework": "modern_descriptive", "status": "established", "typed_analysis": {"kind": "alternative", "framework": "modern_descriptive", "status": "established"}}]
        record["ambiguity"] = {"status": "genuinely_ambiguous", "analyses": [{"id": "collision-a", "structural_claims": ["one"], "interpretation": "one", "alternative_ids": ["wrap-a"]}, {"id": "collision-b", "structural_claims": ["two"], "interpretation": "two", "constituent_ids": ["subj"]}]}
        self.assertTrue(any("conflicting canonical wrapper" in error for error in validate_record(record, "ambiguity-id-namespace")))

    def test_clause_realization_cardinality_and_parent_integrity(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["constituents"].append({"id": "same-span", "node_kind": "clause", "clause_ref": "c0", "span": {"start": 0, "end": 5}, "function": "complement", "realization": {"clause_ref": "c0", "relation": "same_span_alias"}})
        record["constituents"].append({"id": "same-span-2", "node_kind": "clause", "clause_ref": "c0", "span": {"start": 0, "end": 5}, "function": "adjunct", "realization": {"clause_ref": "c0", "relation": "same_span_alias"}})
        self.assertTrue(any("conflicting canonical wrapper" in error for error in validate_record(record, "realization-same-span")))
        record = copy.deepcopy(FIXTURE)
        record["constituents"].append({"id": "wide", "node_kind": "clause", "clause_ref": "c0", "span": {"start": 0, "end": 5}, "function": "complement", "realization": {"clause_ref": "c0", "relation": "same_span_alias"}})
        record["constituents"].append({"id": "narrow", "node_kind": "clause", "clause_ref": "c0", "span": {"start": 1, "end": 4}, "function": "adjunct", "realization": {"clause_ref": "c0", "relation": "same_span_alias"}})
        self.assertTrue(any("incompatible unlinked multi-span" in error for error in validate_record(record, "realization-multi-span")))
        record = copy.deepcopy(FIXTURE)
        record["clauses"][0]["integration_parent"] = "missing-clause"
        self.assertTrue(any("integration_parent" in error for error in validate_record(record, "realization-parent")))

    def test_established_alternative_linkage_is_clause_local(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["clauses"].append({
            "id": "c1",
            "node_kind": "clause",
            "span": {"start": 0, "end": 2},
            "finiteness": "finite",
            "clause_construction": "content",
            "integration": ["subordinate"],
            "integration_parent": "c0",
        })
        for clause_ref, prefix, end in (("c0", "c0-wrap", 5), ("c1", "c1-wrap", 2)):
            record["constituents"].extend([
                {"id": f"{prefix}-a", "node_kind": "clause", "clause_ref": clause_ref, "span": {"start": 0, "end": end}, "function": "complement", "realization": {"clause_ref": clause_ref, "relation": "same_span_alias"}},
                {"id": f"{prefix}-b", "node_kind": "clause", "clause_ref": clause_ref, "span": {"start": 0, "end": end}, "function": "adjunct", "realization": {"clause_ref": clause_ref, "relation": "same_span_alias"}},
            ])
        record["alternative_analyses"] = [{
            "id": "alt-c0",
            "framework": "modern_descriptive",
            "status": "established",
            "typed_analysis": {"kind": "alternative", "framework": "modern_descriptive", "status": "established"},
            "linked_clause_refs": ["c0"],
        }]
        errors = validate_record(record, "established-local")
        self.assertFalse(any("('c0', '', '')" in error and "conflicting canonical wrapper" in error for error in errors))
        self.assertTrue(any("('c1', '', '')" in error and "conflicting canonical wrapper" in error for error in errors))
        record["alternative_analyses"] = []
        record["ambiguity"] = {"status": "genuinely_ambiguous", "analyses": [
            {"id": "c0-a", "structural_claims": ["one"], "interpretation": "one", "wrapper_ids": ["c0-wrap-a"]},
            {"id": "c0-b", "structural_claims": ["two"], "interpretation": "two", "wrapper_ids": ["c0-wrap-b"]},
        ]}
        errors = validate_record(record, "ambiguity-clause-local")
        self.assertFalse(any("('c0', '', '')" in error and "conflicting canonical wrapper" in error for error in errors))
        self.assertTrue(any("('c1', '', '')" in error and "conflicting canonical wrapper" in error for error in errors))

    def test_established_and_unresolved_alternatives_remain_explicit(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["alternative_analyses"] = [{"id": "established-alt", "framework": "modern_descriptive", "status": "established", "learner_explanation": "Other framework", "typed_analysis": {"kind": "alternative", "framework": "modern_descriptive", "status": "established"}}]
        self.assertEqual(validate_record(record, "established-alt"), [])
        record["alternative_analyses"] = [{"id": "unresolved-alt", "framework": "modern_descriptive", "status": "unresolved", "claims": ["prose candidate"], "typed_analysis": {"kind": "candidate", "framework": "modern_descriptive", "status": "unresolved"}}]
        self.assertEqual(validate_record(record, "unresolved-alt"), [])
        record["canonical_analysis"].pop("typed_analysis")
        self.assertTrue(any("typed_analysis" in error for error in validate_record(record, "prose-no-authority")))


if __name__ == "__main__":
    unittest.main()
