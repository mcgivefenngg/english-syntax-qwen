from __future__ import annotations

import copy
import itertools
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from scripts.coverage_resolution import (
    CoverageResolutionError,
    CoverageState,
    ScoringEligibility,
    resolve_coverage,
    resolve_scoring_eligibility,
)
from scripts.canonical_schema import canonical_schema_issues
from scripts.data_common import read_jsonl
from scripts.validate_dataset import coverage_allows_score, validate_record


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = read_jsonl(ROOT / "data" / "gold" / "fixtures.jsonl")[0][1]
DIMENSION = "np_internal_constituency"


def declaration(
    scope: dict[str, Any],
    completeness: str,
    omission: str = "none",
    evidence: str | None = "present",
    dimension: str = DIMENSION,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "dimension": dimension,
        "scope": scope,
        "completeness": completeness,
        "omission": omission,
    }
    if evidence is not None:
        entry["evidence"] = evidence
    return entry


def with_dimensions(*entries: dict[str, Any]) -> dict[str, Any]:
    record = copy.deepcopy(FIXTURE)
    record["annotation_scope"]["dimensions"] = list(entries)
    return record


def add_overlap_target(record: dict[str, Any]) -> None:
    record["constituents"].append({
        "id": "mid",
        "span": {"start": 1, "end": 4},
        "function": "test_target",
        "node_kind": "phrase",
        "phrase_category": "NP",
    })


class CoverageResolutionTests(unittest.TestCase):
    def test_valid_canonical_record_resolves_exact_node_and_record_scope(self) -> None:
        record = with_dimensions(
            declaration({"kind": "record"}, "complete", dimension="lexical_category"),
            declaration({"kind": "node", "node": "w0"}, "complete", dimension="lexical_category"),
        )
        self.assertIs(resolve_coverage(record, "lexical_category", "w0"), CoverageState.COMPLETE)
        self.assertIs(resolve_coverage(record, "lexical_category"), CoverageState.COMPLETE)

    def test_schema_invalid_canonical_mutations_fail_closed_at_public_apis(self) -> None:
        mutations = {
            "invalid split": lambda record: record.__setitem__("split", "not-a-split"),
            "invalid difficulty": lambda record: record.__setitem__("difficulty", "not-a-difficulty"),
            "invalid source_type": lambda record: record.__setitem__("source_type", "not-a-source-type"),
            "invalid sentence_type": lambda record: record.__setitem__("sentence_type", "not-a-sentence-type"),
            "malformed framework": lambda record: record.__setitem__("framework", []),
            "invalid capability_tags": lambda record: record.__setitem__("capability_tags", ["not-a-tag"]),
            "empty capability_tags": lambda record: record.__setitem__("capability_tags", []),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                record = with_dimensions(
                    declaration(
                        {"kind": "node", "node": "w0"},
                        "complete",
                        dimension="lexical_category",
                    )
                )
                mutate(record)
                self.assertTrue(canonical_schema_issues(record))
                with self.assertRaises(CoverageResolutionError):
                    resolve_coverage(record, "lexical_category", "w0")
                decision = resolve_scoring_eligibility(record, "lexical_category", "w0")
                self.assertFalse(decision.scoreable)
                self.assertIsNone(decision.coverage_state)

    def test_canonical_schema_admission_fail_closed_for_record_level_mutations(self) -> None:
        mutations = {
            "missing annotation scope coverage": lambda record: record["annotation_scope"].pop("coverage"),
            "invalid annotation scope coverage": lambda record: record["annotation_scope"].__setitem__("coverage", "bogus"),
            "malformed annotation scope dimension": lambda record: record["annotation_scope"]["dimensions"].append(None),
            "invalid canonical record id": lambda record: record.__setitem__("id", "not a valid id!"),
            "missing required canonical field": lambda record: record.pop("dependencies"),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                record = with_dimensions(declaration({"kind": "node", "node": "w0"}, "complete", dimension="lexical_category"))
                mutate(record)
                with self.assertRaises(CoverageResolutionError):
                    resolve_coverage(record, "lexical_category", "w0")
                decision = resolve_scoring_eligibility(record, "lexical_category", "w0")
                self.assertFalse(decision.scoreable)
                self.assertIsNone(decision.coverage_state)

    def test_record_scope_only_resolves_deterministically(self) -> None:
        record = with_dimensions(declaration({"kind": "record"}, "complete"))
        self.assertIs(resolve_coverage(record, DIMENSION, "subj"), CoverageState.COMPLETE)
        self.assertIs(resolve_coverage(record, DIMENSION), CoverageState.COMPLETE)

    def test_node_scope_overrides_record_scope(self) -> None:
        record = with_dimensions(
            declaration({"kind": "record"}, "complete"),
            declaration({"kind": "node", "node": "subj"}, "partial"),
        )
        self.assertIs(resolve_coverage(record, DIMENSION, "subj"), CoverageState.PARTIAL_COVERED)

    def test_narrower_region_overrides_broader_containing_region(self) -> None:
        record = with_dimensions(
            declaration({"kind": "region", "start": 0, "end": 5}, "partial"),
            declaration({"kind": "region", "start": 0, "end": 2}, "complete"),
        )
        self.assertIs(resolve_coverage(record, DIMENSION, "subj"), CoverageState.COMPLETE)

    def test_exact_node_scope_overrides_containing_region(self) -> None:
        record = with_dimensions(
            declaration({"kind": "record"}, "unannotated", "intentional", "unannotated"),
            declaration({"kind": "region", "start": 0, "end": 5}, "partial"),
            declaration({"kind": "node", "node": "subj"}, "complete"),
        )
        self.assertIs(resolve_coverage(record, DIMENSION, "subj"), CoverageState.COMPLETE)

    def test_region_scope_resolves_word_target_from_token_position(self) -> None:
        record = with_dimensions(
            declaration({"kind": "region", "start": 0, "end": 2}, "complete", dimension="phrase_constituency")
        )
        self.assertIs(resolve_coverage(record, "phrase_constituency", "subj"), CoverageState.COMPLETE)
        self.assertIs(resolve_coverage(record, "phrase_constituency", "obj"), CoverageState.UNANNOTATED)

    def test_phrase_target_uses_canonical_span_for_region_membership(self) -> None:
        record = with_dimensions(
            declaration({"kind": "region", "start": 0, "end": 2}, "complete", dimension="phrase_constituency"),
        )
        self.assertIs(resolve_coverage(record, "phrase_constituency", "subj"), CoverageState.COMPLETE)

    def test_conflicting_extra_word_span_cannot_change_region_membership(self) -> None:
        record = with_dimensions(
            declaration({"kind": "region", "start": 0, "end": 2}, "complete", dimension="phrase_constituency"),
            declaration({"kind": "region", "start": 3, "end": 5}, "complete", dimension="phrase_constituency"),
        )
        record["words"][0]["span"] = {"start": 3, "end": 5}
        self.assertIs(resolve_coverage(record, "phrase_constituency", "subj"), CoverageState.COMPLETE)

    def test_unknown_node_target_does_not_inherit_record_complete(self) -> None:
        record = with_dimensions(declaration({"kind": "record"}, "complete"))
        with self.assertRaises(CoverageResolutionError):
            resolve_coverage(record, DIMENSION, "ghost")

    def test_unknown_node_target_is_not_scoreable(self) -> None:
        record = with_dimensions(declaration({"kind": "record"}, "complete"))
        decision = resolve_scoring_eligibility(record, DIMENSION, "ghost")
        self.assertFalse(decision.scoreable)
        self.assertIsNone(decision.coverage_state)

    def test_unknown_target_under_record_confirmed_empty_is_not_scoreable(self) -> None:
        record = with_dimensions(
            declaration({"kind": "record"}, "complete", evidence="empty", dimension="dependencies"),
        )
        decision = resolve_scoring_eligibility(record, "dependencies", "ghost")
        self.assertFalse(decision.scoreable)
        self.assertIsNone(decision.coverage_state)

    def test_malformed_target_reference_fails_closed(self) -> None:
        record = with_dimensions(declaration({"kind": "record"}, "complete"))
        with self.assertRaises(CoverageResolutionError):
            resolve_coverage(record, DIMENSION, {"node": "subj"})
        decision = resolve_scoring_eligibility(record, DIMENSION, {"node": "subj"})
        self.assertFalse(decision.scoreable)
        self.assertIsNone(decision.coverage_state)

    def test_unmappable_known_node_fails_closed(self) -> None:
        record = with_dimensions(declaration({"kind": "record"}, "complete"))
        record["constituents"][0]["span"] = {"start": 0}
        with self.assertRaises(CoverageResolutionError):
            resolve_coverage(record, DIMENSION, "subj")
        decision = resolve_scoring_eligibility(record, DIMENSION, "subj")
        self.assertFalse(decision.scoreable)
        self.assertIsNone(decision.coverage_state)

    def test_known_node_inherits_applicable_record_coverage(self) -> None:
        record = with_dimensions(declaration({"kind": "record"}, "complete"))
        self.assertIs(resolve_coverage(record, DIMENSION, "subj"), CoverageState.COMPLETE)

    def test_explicit_record_target_resolves_record_coverage(self) -> None:
        record = with_dimensions(declaration({"kind": "record"}, "complete"))
        record_target: str | None = None
        self.assertIs(resolve_coverage(record, DIMENSION, record_target), CoverageState.COMPLETE)

    def test_identical_exact_duplicate_is_rejected(self) -> None:
        entry = declaration({"kind": "node", "node": "subj"}, "complete")
        record = with_dimensions(entry, copy.deepcopy(entry))
        self.assertTrue(any(
            "duplicate dimension + scope" in error
            for error in validate_record(record, "duplicate")
        ))
        with self.assertRaises(CoverageResolutionError):
            resolve_coverage(record, DIMENSION, "subj")
        decision = resolve_scoring_eligibility(record, DIMENSION, "subj")
        self.assertFalse(decision.scoreable)
        self.assertIsNone(decision.coverage_state)

    def test_contradictory_exact_duplicate_is_rejected(self) -> None:
        record = with_dimensions(
            declaration({"kind": "node", "node": "subj"}, "complete"),
            declaration({"kind": "node", "node": "subj"}, "omitted", "intentional", "unannotated"),
        )
        self.assertTrue(any(
            "same dimension + scope cannot have contradictory" in error
            for error in validate_record(record, "contradictory-duplicate")
        ))
        with self.assertRaises(CoverageResolutionError):
            resolve_coverage(record, DIMENSION, "subj")
        decision = resolve_scoring_eligibility(record, DIMENSION, "subj")
        self.assertFalse(decision.scoreable)
        self.assertIsNone(decision.coverage_state)

    def test_contradictory_overlapping_peer_regions_are_rejected(self) -> None:
        record = with_dimensions(
            declaration({"kind": "region", "start": 0, "end": 4}, "complete"),
            declaration({"kind": "region", "start": 1, "end": 5}, "omitted", "intentional", "unannotated"),
        )
        self.assertTrue(any(
            "overlapping peer regions have contradictory" in error
            for error in validate_record(record, "peer-conflict")
        ))
        with self.assertRaises(CoverageResolutionError):
            resolve_coverage(record, DIMENSION, "subj")
        decision = resolve_scoring_eligibility(record, DIMENSION, "subj")
        self.assertFalse(decision.scoreable)
        self.assertIsNone(decision.coverage_state)

    def test_identical_overlapping_peer_regions_resolve_consistently(self) -> None:
        entries = (
            declaration({"kind": "region", "start": 0, "end": 4}, "complete"),
            declaration({"kind": "region", "start": 1, "end": 5}, "complete"),
        )
        record = with_dimensions(*entries)
        add_overlap_target(record)
        self.assertEqual(validate_record(record, "identical-peers"), [])
        self.assertIs(resolve_coverage(record, DIMENSION, "mid"), CoverageState.COMPLETE)
        record["annotation_scope"]["dimensions"].reverse()
        self.assertIs(resolve_coverage(record, DIMENSION, "mid"), CoverageState.COMPLETE)

    def test_declaration_order_reversal_gives_same_result(self) -> None:
        entries = [
            declaration({"kind": "region", "start": 0, "end": 5}, "partial"),
            declaration({"kind": "region", "start": 0, "end": 2}, "omitted", "intentional", "unannotated"),
            declaration({"kind": "node", "node": "subj"}, "partial"),
        ]
        forward = with_dimensions(*entries)
        reverse = with_dimensions(*reversed(entries))
        self.assertIs(resolve_coverage(forward, DIMENSION, "subj"), CoverageState.PARTIAL_COVERED)
        self.assertIs(resolve_coverage(reverse, DIMENSION, "subj"), CoverageState.PARTIAL_COVERED)

    def test_declaration_permutations_give_same_result(self) -> None:
        entries = [
            declaration({"kind": "region", "start": 0, "end": 5}, "partial"),
            declaration({"kind": "region", "start": 0, "end": 2}, "omitted", "intentional", "unannotated"),
            declaration({"kind": "node", "node": "subj"}, "partial"),
        ]
        states = {
            resolve_coverage(with_dimensions(*permutation), DIMENSION, "subj")
            for permutation in itertools.permutations(entries)
        }
        self.assertEqual(states, {CoverageState.PARTIAL_COVERED})

    def test_authoritative_payload_in_omitted_node_scope_fails_closed(self) -> None:
        record = with_dimensions(
            declaration({"kind": "node", "node": "subj"}, "complete"),
            declaration({"kind": "node", "node": "obj"}, "omitted", "intentional", "unannotated"),
        )
        self.assertTrue(any(
            "np_internal_constituency" in error and "unannotated/omitted" in error
            for error in validate_record(record, "subject-object")
        ))
        with self.assertRaises(CoverageResolutionError):
            resolve_coverage(record, DIMENSION, "subj")
        decision = resolve_scoring_eligibility(record, DIMENSION, "subj")
        self.assertFalse(decision.scoreable)
        self.assertIsNone(decision.coverage_state)

    def test_record_partial_and_node_complete_works(self) -> None:
        record = with_dimensions(
            declaration({"kind": "record"}, "partial"),
            declaration({"kind": "node", "node": "subj"}, "complete"),
        )
        self.assertEqual(validate_record(record, "partial-node"), [])
        self.assertIs(resolve_coverage(record, DIMENSION, "subj"), CoverageState.COMPLETE)

    def test_record_partial_does_not_complete_uncovered_target(self) -> None:
        record = with_dimensions(declaration({"kind": "record"}, "partial"))
        self.assertIs(resolve_coverage(record, DIMENSION, "obj"), CoverageState.PARTIAL_UNCOVERED)
        self.assertFalse(coverage_allows_score(record, DIMENSION, "obj"))

    def test_scoring_eligibility_state_matrix(self) -> None:
        cases = (
            (declaration({"kind": "record"}, "complete"), None, CoverageState.COMPLETE, True),
            (declaration({"kind": "record"}, "complete", evidence="empty", dimension="dependencies"), None, CoverageState.CONFIRMED_EMPTY, True),
            (declaration({"kind": "node", "node": "subj"}, "partial"), "subj", CoverageState.PARTIAL_COVERED, True),
            (declaration({"kind": "record"}, "partial"), "obj", CoverageState.PARTIAL_UNCOVERED, False),
            (declaration({"kind": "record"}, "omitted", "intentional", "unannotated", "dependencies"), None, CoverageState.OMITTED, False),
            (declaration({"kind": "record"}, "unannotated", "intentional", "unannotated", "dependencies"), None, CoverageState.UNANNOTATED, False),
            (declaration({"kind": "record"}, "out_of_scope", "not_applicable", "unannotated", "dependencies"), None, CoverageState.OUT_OF_SCOPE, False),
        )
        for entry, target, state, scoreable in cases:
            with self.subTest(state=state):
                record = with_dimensions(entry)
                decision = resolve_scoring_eligibility(record, entry["dimension"], target)
                self.assertIs(decision.coverage_state, state)
                self.assertIs(decision.state, state)
                self.assertEqual(decision.scoreable, scoreable)
                self.assertTrue(decision.reason)

    def test_subject_and_object_have_independent_scoring_eligibility(self) -> None:
        record = with_dimensions(
            declaration({"kind": "node", "node": "subj"}, "complete"),
        )
        subject = resolve_scoring_eligibility(record, DIMENSION, "subj")
        object_ = resolve_scoring_eligibility(record, DIMENSION, "obj")
        self.assertTrue(subject.scoreable)
        self.assertIs(subject.coverage_state, CoverageState.COMPLETE)
        self.assertFalse(object_.scoreable)
        self.assertIs(object_.coverage_state, CoverageState.UNANNOTATED)

    def test_node_specific_partial_coverage_only_scores_that_target(self) -> None:
        record = with_dimensions(
            declaration({"kind": "node", "node": "subj"}, "partial"),
        )
        covered = resolve_scoring_eligibility(record, DIMENSION, "subj")
        uncovered = resolve_scoring_eligibility(record, DIMENSION, "obj")
        self.assertTrue(covered.scoreable)
        self.assertIs(covered.coverage_state, CoverageState.PARTIAL_COVERED)
        self.assertFalse(uncovered.scoreable)
        self.assertIs(uncovered.coverage_state, CoverageState.UNANNOTATED)

    def test_coverage_allows_score_delegates_to_authoritative_decision(self) -> None:
        decision = ScoringEligibility(
            scoreable=True,
            coverage_state=CoverageState.OMITTED,
            reason="test decision",
        )
        record = with_dimensions(declaration({"kind": "record"}, "omitted", "intentional", "unannotated"))
        with patch("scripts.validate_dataset.resolve_scoring_eligibility", return_value=decision) as resolver:
            self.assertTrue(coverage_allows_score(record, DIMENSION, "subj"))
        resolver.assert_called_once_with(record, DIMENSION, "subj")

    def test_scoring_eligibility_is_declaration_order_independent(self) -> None:
        entries = [
            declaration({"kind": "region", "start": 0, "end": 5}, "partial"),
            declaration({"kind": "region", "start": 0, "end": 2}, "omitted", "intentional", "unannotated"),
            declaration({"kind": "node", "node": "subj"}, "partial"),
        ]
        decisions = {
            resolve_scoring_eligibility(with_dimensions(*permutation), DIMENSION, "subj")
            for permutation in itertools.permutations(entries)
        }
        self.assertEqual(
            {(decision.scoreable, decision.coverage_state) for decision in decisions},
            {(True, CoverageState.PARTIAL_COVERED)},
        )

    def test_invalid_node_scope_reference_is_rejected(self) -> None:
        record = with_dimensions(
            declaration({"kind": "node", "node": "missing"}, "complete")
        )
        self.assertTrue(any(
            "node coverage scope must reference a known node" in error
            for error in validate_record(record, "invalid-node")
        ))

    def test_invalid_region_bounds_are_rejected(self) -> None:
        record = with_dimensions(
            declaration({"kind": "region", "start": 0, "end": 7}, "complete")
        )
        self.assertTrue(any(
            "region coverage scope must be a valid non-empty span" in error
            for error in validate_record(record, "invalid-region")
        ))

    def test_impossible_scope_declaration_is_rejected(self) -> None:
        record = with_dimensions(
            declaration({"kind": "record", "node": "subj"}, "complete")
        )
        self.assertTrue(any(
            "record coverage scope cannot include node or region fields" in error
            for error in validate_record(record, "impossible-scope")
        ))

    def test_resolver_exposes_all_controlled_states(self) -> None:
        cases = (
            (declaration({"kind": "record"}, "complete"), None, CoverageState.COMPLETE),
            (declaration({"kind": "node", "node": "subj"}, "partial"), "subj", CoverageState.PARTIAL_COVERED),
            (declaration({"kind": "record"}, "partial"), "subj", CoverageState.PARTIAL_UNCOVERED),
            (declaration({"kind": "record"}, "omitted", "intentional", "unannotated", "dependencies"), None, CoverageState.OMITTED),
            (declaration({"kind": "record"}, "unannotated", "intentional", "unannotated", "dependencies"), None, CoverageState.UNANNOTATED),
            (declaration({"kind": "record"}, "out_of_scope", "not_applicable", "unannotated", "dependencies"), None, CoverageState.OUT_OF_SCOPE),
            (declaration({"kind": "record"}, "complete", evidence="empty", dimension="dependencies"), None, CoverageState.CONFIRMED_EMPTY),
        )
        for entry, target, expected in cases:
            with self.subTest(expected=expected):
                record = with_dimensions(entry)
                self.assertIs(resolve_coverage(record, entry["dimension"], target), expected)

    def assert_invalid_coverage(
        self,
        record: dict[str, Any],
        dimension: str,
        target: str | None = None,
        message: str | None = None,
    ) -> None:
        errors = validate_record(record, "invalid-coverage")
        if message is not None:
            self.assertTrue(any(message in error for error in errors), errors)
        else:
            self.assertTrue(errors)
        with self.assertRaises(CoverageResolutionError):
            resolve_coverage(record, dimension, target)
        decision = resolve_scoring_eligibility(record, dimension, target)
        self.assertFalse(decision.scoreable)
        self.assertIsNone(decision.coverage_state)

    def test_present_with_empty_dependencies_fails_closed(self) -> None:
        record = with_dimensions(declaration({"kind": "record"}, "complete", dimension="dependencies"))
        record["dependencies"] = []
        self.assert_invalid_coverage(record, "dependencies", message="evidence='present'")

    def test_empty_with_non_empty_dependencies_fails_closed(self) -> None:
        record = with_dimensions(declaration({"kind": "record"}, "complete", evidence="empty", dimension="dependencies"))
        record["dependencies"] = [{"relation": "selected", "head": "w2", "dependent": "obj"}]
        self.assert_invalid_coverage(record, "dependencies", message="evidence='empty'")

    def test_partial_unannotated_without_omission_fails_closed(self) -> None:
        record = with_dimensions(declaration({"kind": "record"}, "partial", evidence="unannotated"))
        self.assert_invalid_coverage(record, DIMENSION, message="unannotated evidence")

    def test_missing_required_evidence_fails_closed(self) -> None:
        record = with_dimensions(declaration({"kind": "record"}, "complete", evidence=None))
        self.assert_invalid_coverage(record, DIMENSION, message="explicit evidence")

    def test_confirmed_empty_with_owned_typed_payload_fails_closed(self) -> None:
        record = with_dimensions(declaration({"kind": "record"}, "complete", evidence="empty", dimension="dependencies"))
        record["canonical_analysis"]["typed_analysis"]["status"] = "established"
        record["canonical_analysis"]["typed_analysis"]["relations"] = [{
            "id": "rel-dependency",
            "type": "dependency",
            "arity": "binary",
            "source": {"namespace": "word", "id": "w2"},
            "target": {"namespace": "constituent", "id": "obj"},
        }]
        self.assert_invalid_coverage(record, "dependencies", message="evidence='empty'")

    def test_present_with_absent_authoritative_payload_fails_closed(self) -> None:
        record = with_dimensions(declaration({"kind": "record"}, "complete", dimension="vp_complementation"))
        record.pop("lexical_valency", None)
        self.assert_invalid_coverage(record, "vp_complementation", message="resolved authoritative")

    def test_present_with_unresolved_only_lexical_category_fails_closed(self) -> None:
        record = with_dimensions(declaration({"kind": "record"}, "complete", dimension="lexical_category"))
        for word in record["words"]:
            word["lexical_category"] = None
            word["lexical_analysis"] = {
                "status": "unresolved",
                "review_required": True,
                "candidates": [{"category": "noun", "category_namespace": "project_canonical"}],
            }
        self.assert_invalid_coverage(record, "lexical_category", message="resolved authoritative")

    def test_malformed_exact_phrase_span_fails_closed(self) -> None:
        record = with_dimensions(declaration({"kind": "node", "node": "subj"}, "complete"))
        record["constituents"][0]["span"] = {"start": "0", "end": 2}
        self.assert_invalid_coverage(record, DIMENSION, "subj", message="span")

    def test_missing_exact_phrase_span_fails_closed(self) -> None:
        record = with_dimensions(declaration({"kind": "node", "node": "subj"}, "complete"))
        record["constituents"][0].pop("span")
        self.assert_invalid_coverage(record, DIMENSION, "subj", message="span")

    def test_out_of_bounds_exact_phrase_span_fails_closed(self) -> None:
        record = with_dimensions(declaration({"kind": "node", "node": "subj"}, "complete"))
        record["constituents"][0]["span"] = {"start": 0, "end": 99}
        self.assert_invalid_coverage(record, DIMENSION, "subj", message="span")

    def test_duplicate_canonical_object_ids_fail_closed(self) -> None:
        record = with_dimensions(declaration({"kind": "node", "node": "subj"}, "complete"))
        record["constituents"].append(copy.deepcopy(record["constituents"][0]))
        self.assert_invalid_coverage(record, DIMENSION, "subj", message="duplicate")


if __name__ == "__main__":
    unittest.main()
