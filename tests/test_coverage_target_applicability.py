from __future__ import annotations

import copy
import unittest
from pathlib import Path
from typing import Any

from scripts.authoritative_payload import AuthoritativePayloadState, authoritative_payload
from scripts.collection_contract import validate_coverage_target
from scripts.coverage_resolution import CoverageResolutionError, CoverageState, resolve_coverage, resolve_scoring_eligibility
from scripts.data_common import read_jsonl
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


def record_with(dimension: str, entry: dict[str, Any]) -> dict[str, Any]:
    record = copy.deepcopy(FIXTURE)
    record["annotation_scope"]["dimensions"] = [entry]
    return record


class CoverageTargetApplicabilityTests(unittest.TestCase):
    def assert_rejected(self, record: dict[str, Any], dimension: str, target: str) -> None:
        with self.assertRaises(CoverageResolutionError):
            resolve_coverage(record, dimension, target)
        decision = resolve_scoring_eligibility(record, dimension, target)
        self.assertFalse(decision.scoreable)
        self.assertIsNone(decision.coverage_state)

    def test_lexical_category_word_target_is_valid(self) -> None:
        record = record_with("lexical_category", declaration("lexical_category", {"kind": "record"}))
        self.assertEqual(validate_record(record, "lexical-word"), [])
        self.assertIs(resolve_coverage(record, "lexical_category", "w2"), CoverageState.COMPLETE)

    def test_lexical_category_phrase_target_is_rejected(self) -> None:
        record = record_with("lexical_category", declaration("lexical_category", {"kind": "record"}))
        self.assert_rejected(record, "lexical_category", "obj")

    def test_lexical_category_clause_target_is_rejected(self) -> None:
        record = record_with("lexical_category", declaration("lexical_category", {"kind": "record"}))
        self.assert_rejected(record, "lexical_category", "c0")

    def test_dependencies_record_target_is_valid(self) -> None:
        record = record_with("dependencies", declaration("dependencies", {"kind": "record"}))
        record["dependencies"] = [{"relation": "selected", "head": "w2", "dependent": "obj"}]
        self.assertIs(resolve_coverage(record, "dependencies"), CoverageState.COMPLETE)
        self.assertIs(resolve_coverage(record, "dependencies", {"kind": "record"}), CoverageState.COMPLETE)

    def test_dependencies_endpoint_target_is_rejected(self) -> None:
        record = record_with("dependencies", declaration("dependencies", {"kind": "record"}))
        record["dependencies"] = [{"relation": "selected", "head": "w2", "dependent": "obj"}]
        for target in ("obj", "w2"):
            with self.subTest(target=target):
                self.assert_rejected(record, "dependencies", target)

    def test_authoritative_payload_rejects_record_only_node_target(self) -> None:
        record = record_with("dependencies", declaration("dependencies", {"kind": "record"}))
        record["dependencies"] = [{"relation": "selected", "head": "w2", "dependent": "obj"}]
        payload = authoritative_payload(record, "dependencies", "obj")
        self.assertIs(payload.state, AuthoritativePayloadState.ABSENT)

    def test_semantic_roles_record_target_is_valid(self) -> None:
        record = record_with("semantic_roles", declaration("semantic_roles", {"kind": "record"}))
        record["semantic_roles"] = [{"constituent": "obj", "role": "Theme", "predicate": "catalogue"}]
        self.assertIs(resolve_coverage(record, "semantic_roles"), CoverageState.COMPLETE)

    def test_semantic_roles_predicate_and_argument_targets_are_rejected(self) -> None:
        record = record_with("semantic_roles", declaration("semantic_roles", {"kind": "record"}))
        record["semantic_roles"] = [{"constituent": "obj", "role": "Theme", "predicate": "catalogue"}]
        for target in ("obj", "w2"):
            with self.subTest(target=target):
                self.assert_rejected(record, "semantic_roles", target)

    def test_construction_relations_node_target_is_rejected(self) -> None:
        record = record_with("construction_relations", declaration("construction_relations", {"kind": "record"}))
        record["construction_type"] = "transitive"
        self.assert_rejected(record, "construction_relations", "obj")

    def test_clause_ontology_clause_target_is_valid(self) -> None:
        record = record_with("clause_ontology", declaration("clause_ontology", {"kind": "record"}))
        self.assertEqual(validate_record(record, "clause-target"), [])
        self.assertIs(resolve_coverage(record, "clause_ontology", "c0"), CoverageState.COMPLETE)

    def test_clause_ontology_word_target_is_rejected(self) -> None:
        record = record_with("clause_ontology", declaration("clause_ontology", {"kind": "record"}))
        self.assert_rejected(record, "clause_ontology", "w2")

    def test_np_internal_constituency_valid_np_target_is_valid(self) -> None:
        record = record_with("np_internal_constituency", declaration("np_internal_constituency", {"kind": "record"}))
        self.assertIs(resolve_coverage(record, "np_internal_constituency", "subj"), CoverageState.COMPLETE)

    def test_np_internal_constituency_word_target_is_rejected(self) -> None:
        record = record_with("np_internal_constituency", declaration("np_internal_constituency", {"kind": "record"}))
        self.assert_rejected(record, "np_internal_constituency", "w1")

    def test_validator_rejects_non_np_internal_node_scope(self) -> None:
        record = record_with(
            "np_internal_constituency",
            declaration("np_internal_constituency", {"kind": "node", "node": "vp"}),
        )
        record["constituents"].append({
            "id": "vp",
            "span": {"start": 0, "end": 5},
            "function": "predicator",
            "node_kind": "phrase",
            "phrase_category": "VP",
        })
        errors = validate_record(record, "non-np-scope")
        self.assertTrue(any("applicable NP phrase owner" in error for error in errors))
        with self.assertRaises(CoverageResolutionError):
            resolve_coverage(record, "np_internal_constituency", "vp")

    def test_lexical_valency_actual_lexical_head_target_is_valid(self) -> None:
        record = record_with("lexical_valency", declaration("lexical_valency", {"kind": "node", "node": "w2"}))
        record["lexical_valency"] = [{"predicate": "catalogue", "frame": "transitive", "selected_complements": ["obj"]}]
        self.assertIs(resolve_coverage(record, "lexical_valency", "w2"), CoverageState.COMPLETE)

    def test_lexical_valency_selected_complement_target_is_rejected(self) -> None:
        record = record_with("lexical_valency", declaration("lexical_valency", {"kind": "record"}))
        record["lexical_valency"] = [{"predicate": "catalogue", "frame": "transitive", "selected_complements": ["obj"]}]
        self.assert_rejected(record, "lexical_valency", "obj")

    def test_lexical_valency_unrelated_word_target_is_rejected(self) -> None:
        record = record_with("lexical_valency", declaration("lexical_valency", {"kind": "record"}))
        record["lexical_valency"] = [{"predicate": "catalogue", "frame": "transitive", "selected_complements": ["obj"]}]
        self.assert_rejected(record, "lexical_valency", "w1")

    def test_validator_rejects_lexical_valency_nonowner_word_scope(self) -> None:
        record = record_with(
            "lexical_valency",
            declaration("lexical_valency", {"kind": "node", "node": "w1"}),
        )
        record["lexical_valency"] = [{"predicate": "catalogue", "frame": "transitive", "selected_complements": ["obj"]}]
        errors = validate_record(record, "nonowner-valency-scope")
        self.assertTrue(any("does not own an applicable lexical-valency item" in error for error in errors))
        with self.assertRaises(CoverageResolutionError):
            resolve_coverage(record, "lexical_valency", "w1")

    def test_duplicate_lemma_or_form_owner_ambiguity_fails_closed(self) -> None:
        for field, reference in (("lemma", "catalogue"), ("form", "catalogued")):
            with self.subTest(field=field):
                record = record_with("lexical_valency", declaration("lexical_valency", {"kind": "record"}))
                record["words"][4][field] = reference
                record["lexical_valency"] = [{"predicate": reference, "frame": "transitive", "selected_complements": ["obj"]}]
                validation = validate_coverage_target(record, "lexical_valency", "w2")
                self.assertFalse(validation.valid)
                self.assertEqual(validation.target_kind, "ambiguous_owner")
                self.assert_rejected(record, "lexical_valency", "w2")

    def test_record_lexical_valency_does_not_score_arbitrary_nonowner_word(self) -> None:
        record = record_with("lexical_valency", declaration("lexical_valency", {"kind": "record"}))
        record["lexical_valency"] = [{"predicate": "catalogue", "frame": "transitive", "selected_complements": ["obj"]}]
        self.assert_rejected(record, "lexical_valency", "w1")

    def test_record_lexical_valency_is_inherited_by_valid_owner_word(self) -> None:
        record = record_with("lexical_valency", declaration("lexical_valency", {"kind": "record"}))
        record["lexical_valency"] = [{"predicate": "catalogue", "frame": "transitive", "selected_complements": ["obj"]}]
        self.assertIs(resolve_coverage(record, "lexical_valency", "w2"), CoverageState.COMPLETE)

    def test_invalid_target_cannot_become_partial_covered(self) -> None:
        record = record_with(
            "lexical_category",
            declaration("lexical_category", {"kind": "record"}, completeness="partial"),
        )
        self.assert_rejected(record, "lexical_category", "obj")

    def test_declaration_order_does_not_change_target_applicability(self) -> None:
        entries = [
            declaration("lexical_valency", {"kind": "record"}, completeness="unannotated", omission="intentional", evidence="unannotated"),
            declaration("lexical_valency", {"kind": "node", "node": "w2"}),
        ]
        record = copy.deepcopy(FIXTURE)
        record["lexical_valency"] = [{"predicate": "catalogue", "frame": "transitive", "selected_complements": ["obj"]}]
        states: set[CoverageState] = set()
        invalid_kinds: set[str] = set()
        for ordered_entries in (entries, list(reversed(entries))):
            record["annotation_scope"]["dimensions"] = ordered_entries
            states.add(resolve_coverage(record, "lexical_valency", "w2"))
            validation = validate_coverage_target(record, "lexical_valency", "w1")
            invalid_kinds.add(validation.target_kind)
            self.assert_rejected(record, "lexical_valency", "w1")
        self.assertEqual(states, {CoverageState.COMPLETE})
        self.assertEqual(invalid_kinds, {"wrong_owner"})


class SyntacticFunctionTargetOwnerTests(unittest.TestCase):
    def assert_rejected(self, record: dict[str, Any], target: str) -> None:
        with self.assertRaises(CoverageResolutionError):
            resolve_coverage(record, "syntactic_function", target)
        decision = resolve_scoring_eligibility(record, "syntactic_function", target)
        self.assertFalse(decision.scoreable)
        self.assertIsNone(decision.coverage_state)

    def record_with_record_coverage(self) -> dict[str, Any]:
        return record_with("syntactic_function", declaration("syntactic_function", {"kind": "record"}))

    def with_clause_valued_wrapper(self, record: dict[str, Any]) -> dict[str, Any]:
        record["constituents"].append({
            "id": "clause-wrapper",
            "node_kind": "clause",
            "clause_ref": "c0",
            "span": {"start": 0, "end": 5},
            "function": "complement",
            "realization": {"clause_ref": "c0", "relation": "same_span_alias"},
        })
        return record

    def test_canonical_root_clause_is_not_a_syntactic_function_target(self) -> None:
        validation = validate_coverage_target(FIXTURE, "syntactic_function", "c0")
        self.assertFalse(validation.valid)
        self.assertEqual(validation.target_kind, "wrong_owner")
        self.assert_rejected(self.record_with_record_coverage(), "c0")

    def test_nonroot_canonical_clause_is_not_a_syntactic_function_target(self) -> None:
        record = self.record_with_record_coverage()
        record["clauses"].append({
            "id": "c1",
            "span": {"start": 3, "end": 5},
            "node_kind": "clause",
            "finiteness": "finite",
            "clause_construction": "relative",
            "integration": ["subordinate"],
            "integration_parent": "c0",
        })
        validation = validate_coverage_target(record, "syntactic_function", "c1")
        self.assertFalse(validation.valid)
        self.assertEqual(validation.target_kind, "wrong_owner")
        self.assert_rejected(record, "c1")

    def test_clause_valued_constituent_wrapper_is_a_valid_syntactic_function_target(self) -> None:
        record = self.with_clause_valued_wrapper(self.record_with_record_coverage())
        self.assertEqual(validate_record(record, "wrapper-owner"), [])
        validation = validate_coverage_target(record, "syntactic_function", "clause-wrapper")
        self.assertTrue(validation.valid)
        self.assertEqual(validation.target_kind, "dimension_node")
        self.assertIs(resolve_coverage(record, "syntactic_function", "clause-wrapper"), CoverageState.COMPLETE)
        self.assertTrue(resolve_scoring_eligibility(record, "syntactic_function", "clause-wrapper").scoreable)

    def test_phrase_constituent_remains_a_valid_syntactic_function_target(self) -> None:
        record = self.record_with_record_coverage()
        self.assertTrue(validate_coverage_target(record, "syntactic_function", "obj").valid)
        self.assertIs(resolve_coverage(record, "syntactic_function", "obj"), CoverageState.COMPLETE)

    def test_word_target_syntactic_function_ownership_is_unchanged(self) -> None:
        record = self.record_with_record_coverage()
        validation = validate_coverage_target(record, "syntactic_function", "w2")
        self.assertTrue(validation.valid)
        self.assertEqual(validation.node_kind, "word")
        self.assertIs(resolve_coverage(record, "syntactic_function", "w2"), CoverageState.COMPLETE)

    def test_record_level_syntactic_function_coverage_does_not_make_canonical_clause_scoreable(self) -> None:
        self.assert_rejected(self.record_with_record_coverage(), "c0")
        self.assert_rejected(copy.deepcopy(FIXTURE), "c0")

    def test_node_level_declaration_on_canonical_clause_fails_closed(self) -> None:
        record = record_with("syntactic_function", declaration("syntactic_function", {"kind": "node", "node": "c0"}))
        errors = validate_record(record, "clause-function-scope")
        self.assertTrue(any("canonical clause" in error for error in errors))
        self.assert_rejected(record, "c0")

    def test_unknown_syntactic_function_target_kind_is_unchanged(self) -> None:
        validation = validate_coverage_target(FIXTURE, "syntactic_function", "nope")
        self.assertFalse(validation.valid)
        self.assertEqual(validation.target_kind, "unknown_target")

    def test_unwrapped_nonroot_clause_still_requires_wrapper_under_complete_coverage(self) -> None:
        record = self.record_with_record_coverage()
        record["clauses"].append({
            "id": "c1",
            "span": {"start": 3, "end": 5},
            "node_kind": "clause",
            "finiteness": "finite",
            "clause_construction": "relative",
            "integration": ["subordinate"],
            "integration_parent": "c0",
        })
        errors = validate_record(record, "unwrapped-clause")
        self.assertTrue(any("requires an external realization wrapper for clause 'c1'" in error for error in errors))
        record["constituents"].append({
            "id": "c1-wrapper",
            "node_kind": "clause",
            "clause_ref": "c1",
            "span": {"start": 3, "end": 5},
            "function": "relative_modifier",
            "realization": {"clause_ref": "c1", "relation": "same_span_alias"},
        })
        errors = validate_record(record, "wrapped-clause")
        self.assertFalse(any("requires an external realization wrapper" in error for error in errors))
        self.assertTrue(validate_coverage_target(record, "syntactic_function", "c1-wrapper").valid)


if __name__ == "__main__":
    unittest.main()
