from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.check_contamination import check_contamination, compare
from scripts.data_common import read_jsonl
from scripts.migrate_v021 import migrate
from scripts.render_sft import render_assistant, render_record
from scripts.validate_dataset import validate_record, validate_files


ROOT = Path(__file__).resolve().parents[1]
BENCHMARK = ROOT / "eval" / "benchmark_v1.jsonl"
GOLD = ROOT / "data" / "gold" / "fixtures.jsonl"


class DataPipelineTests(unittest.TestCase):
    def test_v03_clause_dimensions_are_orthogonal_and_composable(self) -> None:
        records = {record["id"]: record for _, record in read_jsonl(BENCHMARK)}
        relative = records["legacy-05-relative-approaching"]["clauses"][1]
        self.assertEqual((relative["finiteness"], relative["clause_construction"]), ("finite", "other"))
        infinitival = copy.deepcopy(records["new-17-purpose-infinitive"])
        infinitival["clauses"][1]["clause_construction"] = "interrogative"
        infinitival["clauses"][1]["integration"] = ["subordinate"]
        self.assertEqual(validate_record(infinitival, "orthogonal"), [])
        supplementary_relative = copy.deepcopy(records["legacy-05-relative-approaching"])
        supplementary_relative["clauses"][1]["integration"] = ["supplementary"]
        self.assertEqual(validate_record(supplementary_relative, "supplementary-relative"), [])
        supplementary = records["new-18-perfect-gerund"]["clauses"][1]
        self.assertEqual((supplementary["finiteness"], supplementary["clause_form"], supplementary["integration"]), ("nonfinite", "gerund_participial", ["subordinate"]))

    def test_v03_clause_is_not_phrase_and_legacy_enum_is_rejected(self) -> None:
        record = copy.deepcopy(read_jsonl(GOLD)[0][1])
        record["clauses"][0]["clause_category"] = "main_clause"
        self.assertTrue(any("legacy clause" in error for error in validate_record(record, "legacy-clause")))
        record = copy.deepcopy(read_jsonl(GOLD)[0][1])
        record["constituents"][0]["node_kind"] = "phrase"
        record["constituents"][0]["phrase_category"] = "Clause"
        self.assertTrue(any("phrase category" in error for error in validate_record(record, "clause-phrase")))

    def test_v03_partial_coverage_and_capability_semantics(self) -> None:
        record = copy.deepcopy(read_jsonl(GOLD)[0][1])
        record["capability_tags"].append("fused_relative")
        self.assertEqual(validate_record(record, "capability-only"), [])
        record.pop("annotation_scope")
        self.assertTrue(any("annotation_scope" in error for error in validate_record(record, "missing-coverage")))

    def test_v03_marker_and_terminal_punctuation_conventions(self) -> None:
        record = copy.deepcopy(next(value for _, value in read_jsonl(BENCHMARK) if value["id"] == "new-46-finite-content-clause"))
        record["clauses"][1]["span"] = {"start": 4, "end": 6}
        self.assertTrue(any("marker must lie inside clause span" in error for error in validate_record(record, "marker-span")))
        record = copy.deepcopy(read_jsonl(GOLD)[0][1])
        record["clauses"][0]["span"]["end"] = len(record["words"])
        self.assertTrue(any("sentence-final punctuation" in error for error in validate_record(record, "root-punctuation")))

    def test_v03_framework_attribution_and_migration(self) -> None:
        record = copy.deepcopy(read_jsonl(GOLD)[0][1])
        record["framework"]["preferred"] = "UD"
        self.assertTrue(any("framework.preferred" in error for error in validate_record(record, "noncanonical-framework")))
        record["framework"]["preferred"] = "cgel_inspired"
        record["canonical_analysis"]["framework"] = "not-a-framework"
        self.assertTrue(any("framework attribution" in error for error in validate_record(record, "bad-framework")))
        record["canonical_analysis"].pop("framework")
        record["canonical_analysis"]["analysis_type"] = "small_clause"
        record["canonical_analysis"].pop("typed_analysis")
        self.assertTrue(any("typed_analysis" in error for error in validate_record(record, "unattributed-analysis")))
        record["canonical_analysis"].pop("analysis_type")
        legacy = copy.deepcopy(record)
        legacy["schema_version"] = "0.2"
        legacy["clauses"][0].pop("integration")
        legacy["clauses"][0].pop("clause_construction")
        legacy["clauses"][0]["clause_category"] = "main_clause"
        migrate(legacy)
        self.assertEqual(legacy["schema_version"], "0.4")
        self.assertEqual(legacy["clauses"][0]["clause_construction"], "unresolved")
        self.assertTrue(legacy["migration_review_required"])
        self.assertEqual(validate_record(legacy, "migrated"), [])
        migrated_once = copy.deepcopy(legacy)
        migrate(legacy)
        self.assertEqual(legacy, migrated_once)
    def test_gold_fixture_schema_validation(self) -> None:
        records = read_jsonl(GOLD)
        self.assertEqual(len(records), 2)
        for line, record in records:
            self.assertEqual(validate_record(record, f"fixture:{line}"), [])

    def test_json_schema_required_and_additional_properties_are_executed(self) -> None:
        record = copy.deepcopy(read_jsonl(GOLD)[0][1])
        record.pop("sentence")
        errors = validate_record(record, "schema-required")
        self.assertTrue(any("schema validation failed" in error and "sentence" in error and record["id"] in error for error in errors))

        record = copy.deepcopy(read_jsonl(GOLD)[0][1])
        record["sentence_classification"] = {"scheme": "demo", "label": "simple", "unexpected": True}
        errors = validate_record(record, "schema-additional")
        self.assertTrue(any("additional properties" in error.lower() for error in errors))

    def test_sentence_word_alignment_and_span_boundaries_are_deterministic(self) -> None:
        record = copy.deepcopy(read_jsonl(GOLD)[0][1])
        record["sentence"] = "The archivist catalogued the map!"
        self.assertTrue(any("token alignment mismatch" in error for error in validate_record(record, "alignment")))
        record = copy.deepcopy(read_jsonl(GOLD)[0][1])
        record["constituents"][0]["span"] = {"start": 4, "end": 2}
        self.assertTrue(any("half-open token span" in error for error in validate_record(record, "span")))
        record = copy.deepcopy(read_jsonl(GOLD)[0][1])
        record["constituents"][0]["span"] = {"start": 0, "end": 6}
        self.assertTrue(any("structural spans must exclude sentence-final punctuation" in error for error in validate_record(record, "punctuation-span")))

    def test_validator_rejects_category_function_confusion(self) -> None:
        record = copy.deepcopy(read_jsonl(GOLD)[0][1])
        record["constituents"][0]["phrase_category"] = "PP"
        record["constituents"][0]["function"] = "AdvP"
        self.assertTrue(validate_record(record, "bad"))

    def test_clause_is_not_a_phrase_category(self) -> None:
        record = copy.deepcopy(read_jsonl(GOLD)[0][1])
        record["constituents"][0]["phrase_category"] = "Clause"
        self.assertTrue(any("phrase category" in error for error in validate_record(record, "bad-clause")))

    def test_nonfinite_clause_is_legal_in_declarative_sentence(self) -> None:
        record = copy.deepcopy(read_jsonl(GOLD)[0][1])
        record["sentence"] = "To leave, the archivist catalogued the map."
        record["sentence_type"] = "declarative"
        record["sentence_classification"] = {"scheme": "traditional_pedagogical", "label": "simple"}
        record["words"] = [
            {"id": "w0", "form": "To", "lemma": "to", "node_kind": "word", "lexical_category": "subordinator", "external_pos_tags": [{"tagset": "UD_UPOS", "tag": "PART"}]},
            {"id": "w1", "form": "leave", "lemma": "leave", "node_kind": "word", "lexical_category": "verb", "external_pos_tags": [{"tagset": "PTB", "tag": "VB"}]},
            {"id": "w2", "form": ",", "lemma": ",", "node_kind": "word", "lexical_category": "punctuation", "external_pos_tags": [{"tagset": "PTB", "tag": ","}]},
            {"id": "w3", "form": "the", "lemma": "the", "node_kind": "word", "lexical_category": "determinative", "external_pos_tags": [{"tagset": "PTB", "tag": "DT"}]},
            {"id": "w4", "form": "archivist", "lemma": "archivist", "node_kind": "word", "lexical_category": "noun", "external_pos_tags": [{"tagset": "PTB", "tag": "NN"}]},
            {"id": "w5", "form": "catalogued", "lemma": "catalogue", "node_kind": "word", "lexical_category": "verb", "external_pos_tags": [{"tagset": "PTB", "tag": "VBD"}]},
            {"id": "w6", "form": "the", "lemma": "the", "node_kind": "word", "lexical_category": "determinative", "external_pos_tags": [{"tagset": "PTB", "tag": "DT"}]},
            {"id": "w7", "form": "map", "lemma": "map", "node_kind": "word", "lexical_category": "noun", "external_pos_tags": [{"tagset": "PTB", "tag": "NN"}]},
            {"id": "w8", "form": ".", "lemma": ".", "node_kind": "word", "lexical_category": "punctuation", "external_pos_tags": [{"tagset": "PTB", "tag": "."}]},
        ]
        record["clauses"].append({"id": "c1", "node_kind": "clause", "span": {"start": 0, "end": 2}, "clause_form": "to_infinitival", "finiteness": "nonfinite", "integration": ["supplementary"], "clause_construction": "other", "predicand": {"kind": "overt_constituent", "target": "subj"}})
        record["constituents"].append({"id": "inf", "node_kind": "clause", "clause_ref": "c1", "span": {"start": 0, "end": 2}, "function": "supplementary_adverbial", "realization": {"clause_ref": "c1", "relation": "same_span_alias"}})
        self.assertEqual(validate_record(record, "nonfinite"), [])

    def test_external_pos_tag_requires_tagset(self) -> None:
        record = copy.deepcopy(read_jsonl(GOLD)[0][1])
        record["words"][0]["external_pos_tags"] = [{"tag": "DT"}]
        self.assertTrue(any("tagset" in error for error in validate_record(record, "bad-tag")))

    def test_predicand_and_fusion_references_are_checked(self) -> None:
        record = copy.deepcopy(read_jsonl(GOLD)[0][1])
        record["clauses"][0]["predicand"] = {"kind": "overt_constituent", "target": "missing"}
        self.assertTrue(any("predicand" in error for error in validate_record(record, "bad-predicand")))
        record = copy.deepcopy(read_jsonl(GOLD)[0][1])
        record["fusion_relations"] = [{"id": "fusion", "type": "fused_relative", "fused_element": "missing", "whole_constituent": "subj", "relative_clause": "c0", "fused_functions": ["nominal", "relativized"]}]
        self.assertTrue(any("fusion" in error for error in validate_record(record, "bad-fusion")))

    def test_existing_ids_must_have_the_declared_reference_type(self) -> None:
        record = copy.deepcopy(next(value for _, value in read_jsonl(BENCHMARK) if value["id"] == "new-33-perception-bare"))
        record["clauses"][1]["subject"] = "w2"
        self.assertTrue(any("clause.subject" in error for error in validate_record(record, "wrong-subject-type")))
        record = copy.deepcopy(next(value for _, value in read_jsonl(BENCHMARK) if value["id"] == "new-17-purpose-infinitive"))
        record["clauses"][1]["predicand"]["target"] = "w4"
        self.assertFalse(any("overt_constituent predicands must target an NP" in error for error in validate_record(record, "wrong-predicand-type")))
        record = copy.deepcopy(next(value for _, value in read_jsonl(BENCHMARK) if value["id"] == "legacy-07-put-complement"))
        record["lexical_valency"][0]["selected_complements"] = ["w0"]
        self.assertTrue(any("selected complement" in error and "not a word" in error for error in validate_record(record, "wrong-valency-type")))
        record = copy.deepcopy(next(value for _, value in read_jsonl(BENCHMARK) if value["id"] == "legacy-07-put-complement"))
        record["semantic_roles"][0]["predicate"] = "pp"
        self.assertTrue(any("semantic role predicate" in error for error in validate_record(record, "wrong-role-predicate-type")))

    def test_selected_locative_advp_is_not_blanket_rejected(self) -> None:
        record = copy.deepcopy(read_jsonl(GOLD)[0][1])
        record["constituents"].append({"id": "loc", "span": {"start": 3, "end": 4}, "function": "selected_locative_complement", "node_kind": "phrase", "phrase_category": "AdvP"})
        self.assertEqual(validate_record(record, "advp-locative"), [])

    def test_alternative_analysis_requires_framework(self) -> None:
        record = copy.deepcopy(read_jsonl(GOLD)[0][1])
        record["alternative_analyses"] = [{"id": "small-clause-alt", "label": "small-clause", "claims": ["the object and predicate form a small clause"], "analysis_type": "small_clause", "construction_type": "object_predication", "status": "established", "typed_analysis": {"kind": "alternative", "framework": "modern_descriptive", "status": "established"}}]
        self.assertTrue(any("framework" in error for error in validate_record(record, "bad-alternative")))
        record["alternative_analyses"][0]["framework"] = "modern_descriptive"
        self.assertEqual(validate_record(record, "good-alternative"), [])

    def test_ambiguity_status_requires_calibrated_readings(self) -> None:
        record = copy.deepcopy(read_jsonl(GOLD)[0][1])
        record["ambiguity"] = {"status": "genuinely_ambiguous", "analyses": [{"id": "vp", "structural_claims": ["VP attachment"], "interpretation": "instrument"}]}
        self.assertTrue(any("two structural analyses" in error for error in validate_record(record, "bad-ambiguity")))
        record["ambiguity"]["analyses"].append({"id": "np", "structural_claims": ["NP attachment"], "interpretation": "man-associated", "constituent_ids": ["obj"]})
        record["ambiguity"]["analyses"][0]["constituent_ids"] = ["obj"]
        self.assertEqual(validate_record(record, "good-ambiguity"), [])
        record["ambiguity"]["analyses"][0]["attachment"] = "w0"
        self.assertTrue(any("ambiguity attachment" in error for error in validate_record(record, "bad-ambiguity-attachment")))

    def test_semantic_role_does_not_override_function(self) -> None:
        record = copy.deepcopy(read_jsonl(GOLD)[0][1])
        record["semantic_roles"] = [{"constituent": "obj", "role": "Location", "predicate": "catalogue"}]
        self.assertEqual(validate_record(record, "role-function"), [])

    def test_validator_reports_malformed_container_without_traceback(self) -> None:
        record = copy.deepcopy(read_jsonl(GOLD)[0][1])
        record["clauses"] = None
        record["constituents"] = None
        record["dependencies"] = None
        record["framework"]["alternatives"] = {"not": "an array"}
        errors = validate_record(record, "malformed")
        self.assertGreaterEqual(len(errors), 4)

    def test_renderer_emits_three_chat_roles(self) -> None:
        rendered = render_record(read_jsonl(GOLD)[1][1])
        self.assertEqual([message["role"] for message in rendered["messages"]], ["system", "user", "assistant"])
        self.assertIn("Proposed analysis", rendered["messages"][1]["content"])
        self.assertIsInstance(json.loads(rendered["messages"][2]["content"]), dict)

    def test_renderer_suppresses_record_partial_uncovered_targets(self) -> None:
        record = next(value for _, value in read_jsonl(BENCHMARK) if value["id"] == "legacy-07-put-complement")
        payload = json.loads(render_assistant(record))
        self.assertEqual(set(payload), {"sentence"})
        self.assertNotIn("review_metadata", payload)

    def test_malformed_rendered_assistant_json_fails(self) -> None:
        rendered = render_record(read_jsonl(GOLD)[0][1])
        rendered["messages"][2]["content"] = "{not-json"
        self.assertTrue(any("assistant content must be valid JSON" in error for error in validate_record(rendered, "rendered-malformed")))

    def test_contamination_exact_and_near_duplicate(self) -> None:
        self.assertIn("exact sentence match", compare("She put the book on the table.", "She put the book on the table."))
        self.assertIn("normalized sentence match", compare("She put the book on the table.", "SHE PUT THE BOOK ON THE TABLE!"))
        self.assertTrue(compare("She put the book on the table.", "She put the vase on the table."))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "train.jsonl"
            path.write_text(json.dumps({"messages": [{"role": "system", "content": "x"}, {"role": "user", "content": "Sentence: She put the vase on the table."}, {"role": "assistant", "content": "y"}]}) + "\n", encoding="utf-8")
            self.assertTrue(check_contamination(BENCHMARK, [path]))

    def test_construction_level_contamination_and_predicate_control(self) -> None:
        benchmark = next(record for _, record in read_jsonl(BENCHMARK) if record["id"] == "legacy-07-put-complement")
        candidate = copy.deepcopy(benchmark)
        candidate["id"] = "candidate-put-substitution"
        candidate["sentence"] = "She put the luggage in the compartment."
        candidate["split"] = "train"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "candidate.jsonl"
            path.write_text(json.dumps(candidate) + "\n", encoding="utf-8")
            findings = check_contamination(BENCHMARK, [path])
            self.assertTrue(any("construction signature" in finding for finding in findings))
        candidate["sentence"] = "She placed the luggage in the compartment."
        candidate["words"][1]["form"] = "placed"
        candidate["words"][1]["lemma"] = "place"
        candidate["lexical_valency"][0]["predicate"] = "place"
        candidate["construction_signature"]["predicate_lemma"] = "place"
        candidate["construction_signature"]["construction_type"] = "place_locative"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "candidate.jsonl"
            path.write_text(json.dumps(candidate) + "\n", encoding="utf-8")
            self.assertFalse(any("construction signature" in finding for finding in check_contamination(BENCHMARK, [path])))
        self.assertNotIn("simple lexical substitution/paraphrase skeleton", compare("She put the book on the table.", "She placed the luggage on the table."))

    def test_construction_signature_does_not_depend_on_local_ids(self) -> None:
        base = copy.deepcopy(next(value for _, value in read_jsonl(BENCHMARK) if value["id"] == "legacy-07-put-complement"))
        base["construction_signature"]["argument_pattern"] = ["obj", "pp"]
        base["construction_signature"]["function_pattern"] = ["object", "selected_locative_complement"]
        renamed = copy.deepcopy(base)
        renamed["constituents"][0]["id"] = "location"
        renamed["lexical_valency"][0]["selected_complements"] = ["location"]
        renamed["construction_signature"]["argument_pattern"] = ["obj", "location"]
        from scripts.validate_dataset import _signature_key
        self.assertEqual(_signature_key(base), _signature_key(renamed))

    def test_benchmark_isolated_from_gold_splits(self) -> None:
        benchmark_rows = read_jsonl(BENCHMARK)
        self.assertEqual(len(benchmark_rows), 50)
        self.assertEqual(sum(record["source_type"] == "legacy_baseline" for _, record in benchmark_rows), 10)
        self.assertTrue(all(record["split"] == "benchmark" for _, record in benchmark_rows))
        benchmark_ids = {record["id"] for _, record in read_jsonl(BENCHMARK)}
        gold_ids = {record["id"] for _, record in read_jsonl(GOLD)}
        self.assertTrue(benchmark_ids.isdisjoint(gold_ids))
        errors = validate_files([GOLD], BENCHMARK)
        self.assertEqual(len(errors), 1)
        self.assertIn("construction_relations", errors[0])
        self.assertIn("resolved authoritative payload", errors[0])
        self.assertTrue(validate_files([ROOT / "data" / "does-not-exist.jsonl"], BENCHMARK))

    def test_benchmark_records_use_full_validation_and_review_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "benchmark.jsonl"
            rows = [value for _, value in read_jsonl(BENCHMARK)]
            rows[0]["words"][0]["form"] = "BROKEN"
            path.write_text("\n".join(json.dumps(value) for value in rows) + "\n", encoding="utf-8")
            errors = validate_files([GOLD], path)
            self.assertTrue(any("token alignment mismatch" in error for error in errors))
            rows = [value for _, value in read_jsonl(BENCHMARK)]
            rows[0]["review_metadata"]["review_status"] = "canonical_gold"
            path.write_text("\n".join(json.dumps(value) for value in rows) + "\n", encoding="utf-8")
            errors = validate_files([GOLD], path)
            self.assertTrue(any("evaluation-only" in error for error in errors))

    def test_structural_failure_returns_nonzero_cli_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "broken.jsonl"
            record = copy.deepcopy(read_jsonl(GOLD)[0][1])
            record["words"][0]["form"] = "BROKEN"
            path.write_text(json.dumps(record) + "\n", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "scripts/validate_dataset.py", str(path), "--benchmark", str(BENCHMARK)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("token alignment mismatch", result.stderr)

    def test_gold_only_cli_can_skip_benchmark(self) -> None:
        result = subprocess.run(
            [sys.executable, "scripts/validate_dataset.py", str(GOLD), "--no-benchmark"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Dataset validation passed", result.stdout)

    def test_rendered_split_files_are_disjoint(self) -> None:
        train_ids = {record["id"] for _, record in read_jsonl(ROOT / "data" / "splits" / "train_fixture.jsonl")}
        validation_ids = {record["id"] for _, record in read_jsonl(ROOT / "data" / "splits" / "validation_fixture.jsonl")}
        self.assertTrue(train_ids.isdisjoint(validation_ids))
        errors = validate_files([ROOT / "data" / "splits"], BENCHMARK)
        self.assertEqual(len(errors), 1)
        self.assertIn("construction_relations", errors[0])
        self.assertIn("resolved authoritative payload", errors[0])


if __name__ == "__main__":
    unittest.main()
