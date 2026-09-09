"""B04 R3a record consistency completion tests.

Tests for H2 Aggregate Repair R3a:
- R3a-A: vp_complementation duplicate-wrapper parity
- R3a-B: zero-root record-level consistency accounting
- R3a-C: sentence_type contradiction scalar safety
"""

from __future__ import annotations

import copy
import unittest
from pathlib import Path
from typing import Any

from scripts.authoritative_payload import (
    AuthoritativePayloadState,
    authoritative_payload,
)
from scripts.canonical_record_contract import (
    CanonicalConsistencyIssue,
    canonical_record_consistency_issues,
    targets_in_consistency_conflict,
    dimensions_affected_by_consistency_issues,
    fields_in_consistency_conflict,
    target_conflicted_for_dimension,
    record_level_consistency_failures,
    canonical_target_consistency_status,
)
from scripts.coverage_resolution import resolve_scoring_eligibility
from scripts.data_common import read_jsonl
from scripts.render_sft import linguistic_projection
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


def with_declaration(record: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(record)
    result["annotation_scope"]["dimensions"] = [
        existing
        for existing in result["annotation_scope"]["dimensions"]
        if existing.get("dimension") != entry["dimension"]
    ] + [entry]
    return result


def make_complete_record(record: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(record)
    result["annotation_scope"]["coverage"] = "complete_constituency"
    core_dimensions = [
        "phrase_constituency", "syntactic_function",
        "clause_ontology", "clause_structure", "vp_complementation",
    ]
    for dim in core_dimensions:
        result = with_declaration(result, declaration(dim, {"kind": "record"}))
    return result


def _make_duplicate_wrappers(clause_id: str) -> list[dict[str, Any]]:
    return [
        {
            "id": "wrapper_a",
            "node_kind": "clause",
            "clause_ref": clause_id,
            "span": {"start": 0, "end": 5},
            "function": "complement",
            "realization": {"clause_ref": clause_id, "relation": "same_span_alias"},
            "span_relation": "same_span_alias",
        },
        {
            "id": "wrapper_b",
            "node_kind": "clause",
            "clause_ref": clause_id,
            "span": {"start": 0, "end": 5},
            "function": "complement",
            "realization": {"clause_ref": clause_id, "relation": "same_span_alias"},
            "span_relation": "same_span_alias",
        },
    ]


class R3aAVpComplementationTests(unittest.TestCase):
    """R3a-A: vp_complementation duplicate-wrapper parity."""

    def _make_record_with_duplicate_complement_wrappers(self) -> dict[str, Any]:
        record = copy.deepcopy(FIXTURE)
        record = make_complete_record(record)
        clause_id = record["clauses"][0]["id"]
        record["constituents"].extend(_make_duplicate_wrappers(clause_id))
        return record

    def test_vp_payload_not_fully_resolved(self) -> None:
        record = self._make_record_with_duplicate_complement_wrappers()
        payload = authoritative_payload(record, "vp_complementation")
        self.assertGreater(payload.missing_count, 0)
        self.assertFalse(payload.fully_resolved)

    def test_vp_scoring_false(self) -> None:
        record = self._make_record_with_duplicate_complement_wrappers()
        decision = resolve_scoring_eligibility(record, "vp_complementation")
        self.assertFalse(decision.scoreable)

    def test_target_wrapper_a_not_clean(self) -> None:
        record = self._make_record_with_duplicate_complement_wrappers()
        payload = authoritative_payload(record, "vp_complementation", "wrapper_a")
        self.assertNotEqual(payload.state, AuthoritativePayloadState.PRESENT)

    def test_target_wrapper_b_not_clean(self) -> None:
        record = self._make_record_with_duplicate_complement_wrappers()
        payload = authoritative_payload(record, "vp_complementation", "wrapper_b")
        self.assertNotEqual(payload.state, AuthoritativePayloadState.PRESENT)

    def test_valid_sibling_remains_positive(self) -> None:
        record = self._make_record_with_duplicate_complement_wrappers()
        obj_constituent = {
            "id": "obj_comp",
            "node_kind": "phrase",
            "phrase_category": "NP",
            "span": {"start": 3, "end": 5},
            "function": "selected_complement",
        }
        record["constituents"].append(obj_constituent)
        payload = authoritative_payload(record, "vp_complementation", "obj_comp")
        self.assertEqual(payload.state, AuthoritativePayloadState.PRESENT)
        self.assertTrue(payload.fully_resolved)


class R3aBZeroRootTests(unittest.TestCase):
    """R3a-B: zero-root record-level consistency accounting."""

    def _make_zero_root_record(self) -> dict[str, Any]:
        record = copy.deepcopy(FIXTURE)
        record = make_complete_record(record)
        record["clauses"][0]["integration"] = ["subordinate"]
        return record

    def test_zero_root_validator_reproduction(self) -> None:
        record = self._make_zero_root_record()
        errors = validate_record(record, "zero-root")
        self.assertTrue(any("exactly one root clause" in error for error in errors))

    def test_shared_issue_record_level(self) -> None:
        record = self._make_zero_root_record()
        issues = canonical_record_consistency_issues(record)
        root_issues = [i for i in issues if i.code == "multiple_root_clauses"]
        self.assertEqual(len(root_issues), 1)
        self.assertTrue(root_issues[0].record_level)
        self.assertEqual(len(root_issues[0].affected_targets), 0)

    def test_clause_structure_record_payload_missing(self) -> None:
        record = self._make_zero_root_record()
        payload = authoritative_payload(record, "clause_structure")
        self.assertGreater(payload.missing_count, 0)
        self.assertFalse(payload.fully_resolved)

    def test_clause_ontology_record_payload_missing(self) -> None:
        record = self._make_zero_root_record()
        payload = authoritative_payload(record, "clause_ontology")
        self.assertGreater(payload.missing_count, 0)
        self.assertFalse(payload.fully_resolved)

    def test_both_scoring_false(self) -> None:
        record = self._make_zero_root_record()
        decision_cs = resolve_scoring_eligibility(record, "clause_structure")
        decision_co = resolve_scoring_eligibility(record, "clause_ontology")
        self.assertFalse(decision_cs.scoreable)
        self.assertFalse(decision_co.scoreable)

    def test_locally_valid_non_root_clause_target_isolation(self) -> None:
        record = self._make_zero_root_record()
        payload = authoritative_payload(record, "clause_structure", "c0")
        self.assertEqual(payload.state, AuthoritativePayloadState.PRESENT)
        self.assertTrue(payload.fully_resolved)


class R3aCMoodScalarTests(unittest.TestCase):
    """R3a-C: sentence_type contradiction scalar safety."""

    def _make_contradictory_record(self) -> dict[str, Any]:
        record = copy.deepcopy(FIXTURE)
        record = make_complete_record(record)
        record["sentence_type"] = "interrogative"
        record["clauses"][0]["clause_construction"] = "declarative"
        return record

    def test_contradictory_sentence_type_absent_from_projection(self) -> None:
        record = self._make_contradictory_record()
        projection = linguistic_projection(record)
        self.assertNotIn("sentence_type", projection)

    def test_conflicted_root_positive_clause_absent(self) -> None:
        record = self._make_contradictory_record()
        projection = linguistic_projection(record)
        projected_clauses = {c["id"]: c for c in projection.get("clauses", [])}
        if "c0" in projected_clauses:
            clause = projected_clauses["c0"]
            if "root" in clause.get("integration", []):
                self.fail("conflicted root clause should not be projected as positive")

    def test_declarative_declarative_control_projects_sentence_type(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record = make_complete_record(record)
        record["sentence_type"] = "declarative"
        record["clauses"][0]["clause_construction"] = "declarative"
        projection = linguistic_projection(record)
        self.assertIn("sentence_type", projection)
        self.assertEqual(projection["sentence_type"], "declarative")

    def test_interrogative_interrogative_control_projects_sentence_type(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record = make_complete_record(record)
        record["sentence_type"] = "interrogative"
        record["clauses"][0]["clause_construction"] = "interrogative"
        projection = linguistic_projection(record)
        self.assertIn("sentence_type", projection)
        self.assertEqual(projection["sentence_type"], "interrogative")

    def test_unrelated_dimension_remains_projectable(self) -> None:
        record = self._make_contradictory_record()
        payload = authoritative_payload(record, "lexical_category")
        self.assertEqual(payload.state, AuthoritativePayloadState.PRESENT)
        self.assertTrue(payload.fully_resolved)


class R3aSharedHelperTests(unittest.TestCase):
    """Tests for new shared helpers."""

    def test_fields_in_consistency_conflict_mood(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["sentence_type"] = "interrogative"
        record["clauses"][0]["clause_construction"] = "declarative"
        fields = fields_in_consistency_conflict(record)
        self.assertIn("sentence_type", fields)

    def test_target_conflicted_for_dimension(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["sentence_type"] = "interrogative"
        record["clauses"][0]["clause_construction"] = "declarative"
        self.assertTrue(target_conflicted_for_dimension(record, "clause_structure", "c0"))
        self.assertFalse(target_conflicted_for_dimension(record, "phrase_constituency", "c0"))

    def test_record_level_consistency_failures(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["clauses"][0]["integration"] = ["subordinate"]
        failures = record_level_consistency_failures(record, "clause_structure")
        self.assertGreater(len(failures), 0)
        self.assertTrue(all(f.record_level for f in failures))

    def test_canonical_target_consistency_status(self) -> None:
        record = copy.deepcopy(FIXTURE)
        clause_id = record["clauses"][0]["id"]
        record["constituents"].extend(_make_duplicate_wrappers(clause_id))
        self.assertEqual(canonical_target_consistency_status(record, "phrase_constituency", "wrapper_a"), "conflicted")
        self.assertEqual(canonical_target_consistency_status(record, "phrase_constituency", "subj"), "clean")


class R3aRegressionTests(unittest.TestCase):
    """Regression tests to ensure R1/R2/R3 remain green."""

    def test_two_root_r3_tests_remain_green(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record = make_complete_record(record)
        c1 = copy.deepcopy(record["clauses"][0])
        c1["id"] = "c1"
        c1["integration"] = ["root"]
        record["clauses"].append(c1)
        payload = authoritative_payload(record, "clause_structure")
        self.assertFalse(payload.fully_resolved)
        decision = resolve_scoring_eligibility(record, "clause_structure")
        self.assertFalse(decision.scoreable)

    def test_duplicate_wrapper_phrase_function_r3_tests_remain_green(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record = make_complete_record(record)
        clause_id = record["clauses"][0]["id"]
        record["constituents"].extend(_make_duplicate_wrappers(clause_id))
        payload_a = authoritative_payload(record, "phrase_constituency", "wrapper_a")
        self.assertNotEqual(payload_a.state, AuthoritativePayloadState.PRESENT)
        payload_b = authoritative_payload(record, "syntactic_function", "wrapper_b")
        self.assertNotEqual(payload_b.state, AuthoritativePayloadState.PRESENT)

    def test_r2a_identity_only_shell_remains_green(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record = make_complete_record(record)
        clause_id = record["clauses"][0]["id"]
        record["constituents"].extend(_make_duplicate_wrappers(clause_id))
        record["dependencies"] = [{"head": "w0", "dependent": "wrapper_a", "relation": "dep"}]
        projection = linguistic_projection(record)
        projected_constituents = {c["id"]: c for c in projection.get("constituents", [])}
        if "wrapper_a" in projected_constituents:
            shell = projected_constituents["wrapper_a"]
            self.assertEqual(shell.get("node_kind"), "clause")
            self.assertNotIn("function", shell)
            self.assertNotIn("phrase_category", shell)

    def test_r1_typed_scope_regressions_remain_green(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record = make_complete_record(record)
        record["dependencies"] = [{"head": "w0", "dependent": "w1", "relation": "dep"}]
        record = with_declaration(record, declaration("dependencies", {"kind": "record"}))
        payload = authoritative_payload(record, "dependencies")
        self.assertEqual(payload.state, AuthoritativePayloadState.PRESENT)


if __name__ == "__main__":
    unittest.main()
