from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from scripts.check_contamination import check_contamination, compare
from scripts.data_common import read_jsonl
from scripts.render_sft import render_record
from scripts.validate_dataset import validate_record, validate_files


ROOT = Path(__file__).resolve().parents[1]
BENCHMARK = ROOT / "eval" / "benchmark_v1.jsonl"
GOLD = ROOT / "data" / "gold" / "fixtures.jsonl"


class DataPipelineTests(unittest.TestCase):
    def test_gold_fixture_schema_validation(self) -> None:
        records = read_jsonl(GOLD)
        self.assertEqual(len(records), 2)
        for line, record in records:
            self.assertEqual(validate_record(record, f"fixture:{line}"), [])

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
            {"id": "w3", "form": "the", "lemma": "the", "node_kind": "word", "lexical_category": "determiner", "external_pos_tags": [{"tagset": "PTB", "tag": "DT"}]},
            {"id": "w4", "form": "archivist", "lemma": "archivist", "node_kind": "word", "lexical_category": "noun", "external_pos_tags": [{"tagset": "PTB", "tag": "NN"}]},
            {"id": "w5", "form": "catalogued", "lemma": "catalogue", "node_kind": "word", "lexical_category": "verb", "external_pos_tags": [{"tagset": "PTB", "tag": "VBD"}]},
            {"id": "w6", "form": "the", "lemma": "the", "node_kind": "word", "lexical_category": "determiner", "external_pos_tags": [{"tagset": "PTB", "tag": "DT"}]},
            {"id": "w7", "form": "map", "lemma": "map", "node_kind": "word", "lexical_category": "noun", "external_pos_tags": [{"tagset": "PTB", "tag": "NN"}]},
            {"id": "w8", "form": ".", "lemma": ".", "node_kind": "word", "lexical_category": "punctuation", "external_pos_tags": [{"tagset": "PTB", "tag": "."}]},
        ]
        record["clauses"].append({"id": "c1", "node_kind": "clause", "span": {"start": 0, "end": 2}, "clause_category": "infinitival_clause", "finiteness": "non-finite", "function": "supplementary_adverbial", "predicand": {"kind": "overt_constituent", "target": "subj"}})
        record["constituents"].append({"id": "inf", "node_kind": "clause", "clause_ref": "c1", "span": {"start": 0, "end": 2}, "function": "supplementary_adverbial"})
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

    def test_alternative_analysis_requires_framework(self) -> None:
        record = copy.deepcopy(read_jsonl(GOLD)[0][1])
        record["alternative_analyses"] = [{"label": "small-clause", "claims": ["the object and predicate form a small clause"], "analysis_type": "small_clause", "construction_type": "object_predication", "status": "established"}]
        self.assertTrue(any("framework" in error for error in validate_record(record, "bad-alternative")))
        record["alternative_analyses"][0]["framework"] = "modern_descriptive"
        self.assertEqual(validate_record(record, "good-alternative"), [])

    def test_ambiguity_status_requires_calibrated_readings(self) -> None:
        record = copy.deepcopy(read_jsonl(GOLD)[0][1])
        record["ambiguity"] = {"status": "genuinely_ambiguous", "analyses": [{"id": "vp", "structural_claims": ["VP attachment"], "interpretation": "instrument"}]}
        self.assertTrue(any("two structural analyses" in error for error in validate_record(record, "bad-ambiguity")))
        record["ambiguity"]["analyses"].append({"id": "np", "structural_claims": ["NP attachment"], "interpretation": "man-associated"})
        self.assertEqual(validate_record(record, "good-ambiguity"), [])

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

    def test_benchmark_isolated_from_gold_splits(self) -> None:
        benchmark_rows = read_jsonl(BENCHMARK)
        self.assertEqual(len(benchmark_rows), 50)
        self.assertEqual(sum(record["source_type"] == "legacy_baseline" for _, record in benchmark_rows), 10)
        self.assertTrue(all(record["split"] == "benchmark" for _, record in benchmark_rows))
        benchmark_ids = {record["id"] for _, record in read_jsonl(BENCHMARK)}
        gold_ids = {record["id"] for _, record in read_jsonl(GOLD)}
        self.assertTrue(benchmark_ids.isdisjoint(gold_ids))
        self.assertEqual(validate_files([GOLD], BENCHMARK), [])
        self.assertTrue(validate_files([ROOT / "data" / "does-not-exist.jsonl"], BENCHMARK))

    def test_rendered_split_files_are_disjoint(self) -> None:
        train_ids = {record["id"] for _, record in read_jsonl(ROOT / "data" / "splits" / "train_fixture.jsonl")}
        validation_ids = {record["id"] for _, record in read_jsonl(ROOT / "data" / "splits" / "validation_fixture.jsonl")}
        self.assertTrue(train_ids.isdisjoint(validation_ids))
        self.assertEqual(validate_files([ROOT / "data" / "splits"], BENCHMARK), [])


if __name__ == "__main__":
    unittest.main()
