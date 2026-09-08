"""H2 Repair A6: record-level partial-present target semantics.

A record declaration ``scope=record completeness=partial omission=none
evidence=present`` claims an explicitly annotated positive subset identified
through the registry's ``partial_present_target_source``. Absence outside the
subset stays unknown, never negative gold.
"""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from typing import Any

from scripts.coverage_resolution import (
    CoverageResolutionError,
    CoverageState,
    resolve_coverage,
    resolve_scoring_eligibility,
)
from scripts.data_common import read_jsonl
from scripts.dimension_registry import DIMENSION_REGISTRY
from scripts.render_sft import linguistic_projection
from scripts.validate_dataset import validate_record


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = read_jsonl(ROOT / "data" / "gold" / "fixtures.jsonl")[0][1]


def declaration(
    dimension: str,
    scope: dict[str, Any],
    completeness: str = "partial",
    omission: str = "none",
    evidence: str | None = "present",
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


def record_with(*entries: dict[str, Any]) -> dict[str, Any]:
    record = copy.deepcopy(FIXTURE)
    record["annotation_scope"]["dimensions"] = list(entries)
    return record


DEPENDENCY = {"relation": "nmod", "head": "w2", "dependent": "subj"}
MALFORMED_DEPENDENCY = {"relation": "nmod", "head": "ghost", "dependent": "subj"}
ROLE = {"constituent": "obj", "role": "Theme", "predicate": "w2"}
VALENCY = {"predicate": "catalogue", "frame": "transitive", "selected_complements": ["obj"]}


def unresolved_lexical_analysis() -> dict[str, Any]:
    return {
        "status": "unresolved",
        "review_required": True,
        "candidates": [{"category": "noun", "category_namespace": "project_canonical"}],
    }


class PartialPresentTargetSourceContractTests(unittest.TestCase):
    def test_registry_declares_the_executable_target_source_classification(self) -> None:
        actual: dict[str | None, set[str]] = {}
        for name, spec in DIMENSION_REGISTRY.items():
            actual.setdefault(spec.partial_present_target_source, set()).add(name)
        self.assertEqual(actual, {
            "item_ids": {
                "tokens", "lexical_category", "phrase_constituency", "constituency",
                "np_internal_constituency", "clause_ontology", "clause_structure", "syntactic_function",
            },
            "predicate_ids": {"lexical_valency"},
            "record": {"dependencies", "semantic_roles", "framework_mapping", "construction_relations"},
            None: {"vp_complementation"},
        })


class ItemIdsPartialPresentTests(unittest.TestCase):
    def test_resolved_item_target_becomes_partial_covered(self) -> None:
        record = record_with(declaration("lexical_category", {"kind": "record"}))
        self.assertEqual(validate_record(record, "lexical-partial"), [])
        self.assertIs(resolve_coverage(record, "lexical_category", "w0"), CoverageState.PARTIAL_COVERED)
        decision = resolve_scoring_eligibility(record, "lexical_category", "w0")
        self.assertTrue(decision.scoreable)
        self.assertIs(decision.coverage_state, CoverageState.PARTIAL_COVERED)

    def test_applicable_item_without_resolved_payload_stays_uncovered(self) -> None:
        record = record_with(declaration("lexical_category", {"kind": "record"}))
        record["words"][5]["lexical_category"] = None
        self.assertIs(resolve_coverage(record, "lexical_category", "w5"), CoverageState.PARTIAL_UNCOVERED)
        decision = resolve_scoring_eligibility(record, "lexical_category", "w5")
        self.assertFalse(decision.scoreable)
        self.assertIs(decision.coverage_state, CoverageState.PARTIAL_UNCOVERED)

    def test_unresolved_only_item_is_not_a_positive_partial_target(self) -> None:
        record = record_with(declaration("lexical_category", {"kind": "record"}))
        word = record["words"][0]
        word["lexical_analysis"] = unresolved_lexical_analysis()
        self.assertIs(resolve_coverage(record, "lexical_category", "w0"), CoverageState.PARTIAL_UNCOVERED)
        self.assertFalse(resolve_scoring_eligibility(record, "lexical_category", "w0").scoreable)

    def test_record_target_does_not_become_whole_record_positive(self) -> None:
        record = record_with(declaration("lexical_category", {"kind": "record"}))
        self.assertIs(resolve_coverage(record, "lexical_category", "w0"), CoverageState.PARTIAL_COVERED)
        self.assertIs(resolve_coverage(record, "lexical_category"), CoverageState.PARTIAL_UNCOVERED)
        self.assertIs(resolve_coverage(record, "lexical_category", {"kind": "record"}), CoverageState.PARTIAL_UNCOVERED)

    def test_tokens_record_partial_resolves_derived_word_target(self) -> None:
        record = record_with(declaration("tokens", {"kind": "record"}))
        self.assertIs(resolve_coverage(record, "tokens", "w0"), CoverageState.PARTIAL_COVERED)
        self.assertIs(resolve_coverage(record, "tokens"), CoverageState.PARTIAL_UNCOVERED)

    def test_node_scoped_tokens_declaration_remains_invalid(self) -> None:
        record = record_with(declaration("tokens", {"kind": "node", "node": "w0"}))
        errors = validate_record(record, "tokens-node-declaration")
        self.assertTrue(any("tokens" in error and "does not support node scope" in error for error in errors))
        with self.assertRaises(CoverageResolutionError):
            resolve_coverage(record, "tokens", "w0")

    def test_more_specific_declarations_keep_precedence(self) -> None:
        record = record_with(
            declaration("lexical_category", {"kind": "record"}),
            declaration("lexical_category", {"kind": "node", "node": "w0"}, "complete"),
        )
        self.assertIs(resolve_coverage(record, "lexical_category", "w0"), CoverageState.COMPLETE)
        self.assertIs(resolve_coverage(record, "lexical_category", "w1"), CoverageState.PARTIAL_COVERED)

    def test_record_partial_does_not_override_containing_region_omission(self) -> None:
        record = record_with(
            declaration("phrase_constituency", {"kind": "record"}),
            declaration("phrase_constituency", {"kind": "region", "start": 3, "end": 4}, "omitted", "intentional", "unannotated"),
        )
        record["constituents"].append({"id": "obj-det", "node_kind": "phrase", "span": {"start": 3, "end": 4}, "parent": "obj", "function": "determiner"})
        self.assertIs(resolve_coverage(record, "phrase_constituency", "obj-det"), CoverageState.OMITTED)
        self.assertFalse(resolve_scoring_eligibility(record, "phrase_constituency", "obj-det").scoreable)
        self.assertIs(resolve_coverage(record, "phrase_constituency", "subj"), CoverageState.PARTIAL_COVERED)

    def test_record_declaration_cannot_override_target_ownership(self) -> None:
        record = record_with(declaration("syntactic_function", {"kind": "record"}))
        with self.assertRaises(CoverageResolutionError):
            resolve_coverage(record, "syntactic_function", "c0")
        decision = resolve_scoring_eligibility(record, "syntactic_function", "c0")
        self.assertFalse(decision.scoreable)
        self.assertIsNone(decision.coverage_state)


class PredicateIdsPartialPresentTests(unittest.TestCase):
    def test_represented_predicate_becomes_partial_covered(self) -> None:
        record = record_with(declaration("lexical_valency", {"kind": "record"}))
        record["lexical_valency"] = [VALENCY]
        self.assertIs(resolve_coverage(record, "lexical_valency", "w2"), CoverageState.PARTIAL_COVERED)
        self.assertTrue(resolve_scoring_eligibility(record, "lexical_valency", "w2").scoreable)

    def test_unrepresented_lexical_head_is_not_positive(self) -> None:
        record = record_with(declaration("lexical_valency", {"kind": "record"}))
        record["lexical_valency"] = [VALENCY]
        decision = resolve_scoring_eligibility(record, "lexical_valency", "w1")
        self.assertFalse(decision.scoreable)
        self.assertIsNone(decision.coverage_state)
        self.assertIs(resolve_coverage(record, "lexical_valency"), CoverageState.PARTIAL_UNCOVERED)


class RecordPartialPresentTests(unittest.TestCase):
    def test_dependencies_record_partial_present_resolves_record_target(self) -> None:
        record = record_with(declaration("dependencies", {"kind": "record"}))
        record["dependencies"] = [DEPENDENCY]
        self.assertEqual(validate_record(record, "dependencies-partial"), [])
        self.assertIs(resolve_coverage(record, "dependencies"), CoverageState.PARTIAL_COVERED)
        self.assertTrue(resolve_scoring_eligibility(record, "dependencies").scoreable)

    def test_semantic_roles_record_partial_present_resolves_record_target(self) -> None:
        record = record_with(declaration("semantic_roles", {"kind": "record"}))
        record["semantic_roles"] = [ROLE]
        self.assertEqual(validate_record(record, "roles-partial"), [])
        self.assertIs(resolve_coverage(record, "semantic_roles"), CoverageState.PARTIAL_COVERED)

    def test_framework_mapping_record_partial_present_resolves_record_target(self) -> None:
        record = record_with(declaration("framework_mapping", {"kind": "record"}))
        self.assertEqual(validate_record(record, "framework-partial"), [])
        self.assertIs(resolve_coverage(record, "framework_mapping"), CoverageState.PARTIAL_COVERED)

    def test_partial_covered_is_not_complete(self) -> None:
        record = record_with(declaration("framework_mapping", {"kind": "record"}))
        state = resolve_coverage(record, "framework_mapping")
        self.assertIs(state, CoverageState.PARTIAL_COVERED)
        self.assertNotEqual(state, CoverageState.COMPLETE)

    def test_record_source_dimensions_still_reject_node_targets(self) -> None:
        record = record_with(declaration("dependencies", {"kind": "record"}))
        record["dependencies"] = [DEPENDENCY]
        with self.assertRaises(CoverageResolutionError):
            resolve_coverage(record, "dependencies", "w2")

    def test_unsupported_dimension_stays_fail_closed(self) -> None:
        record = record_with(declaration("vp_complementation", {"kind": "record"}))
        record["lexical_valency"] = [VALENCY]
        errors = validate_record(record, "vp-partial")
        self.assertTrue(any("no identifiable target representation" in error for error in errors))
        with self.assertRaises(CoverageResolutionError):
            resolve_coverage(record, "vp_complementation")


class PartialPresentProjectionTests(unittest.TestCase):
    def test_gold_fixture_no_longer_projects_sentence_only(self) -> None:
        projection = linguistic_projection(FIXTURE)
        self.assertTrue(set(projection) >= {"sentence", "words", "clauses", "constituents", "framework"})

    def test_record_partial_tokens_emit_covered_form_and_lemma(self) -> None:
        projection = linguistic_projection(FIXTURE)
        words = {word["id"]: word for word in projection["words"]}
        self.assertEqual(words["w1"]["form"], "archivist")
        self.assertEqual(words["w1"]["lemma"], "archivist")

    def test_record_partial_lexical_category_emits_covered_categories(self) -> None:
        projection = linguistic_projection(FIXTURE)
        words = {word["id"]: word for word in projection["words"]}
        self.assertEqual(words["w2"]["lexical_category"], "verb")
        self.assertEqual(words["w2"]["external_pos_tags"], [{"tagset": "PTB", "tag": "VBD"}])

    def test_record_partial_phrase_clause_function_emit_positive_nodes(self) -> None:
        projection = linguistic_projection(FIXTURE)
        constituents = {item["id"]: item for item in projection["constituents"]}
        self.assertEqual(constituents["subj"]["phrase_category"], "NP")
        self.assertEqual(constituents["subj"]["function"], "subject")
        clauses = {item["id"]: item for item in projection["clauses"]}
        self.assertEqual(clauses["c0"]["finiteness"], "finite")
        self.assertEqual(clauses["c0"]["clause_construction"], "declarative")

    def test_record_partial_framework_emits_owned_scalar(self) -> None:
        projection = linguistic_projection(FIXTURE)
        self.assertEqual(projection["framework"], {"preferred": "cgel_inspired"})

    def test_record_partial_unannotated_sentence_type_does_not_infer(self) -> None:
        projection = linguistic_projection(FIXTURE)
        self.assertNotIn("sentence_type", projection)
        self.assertNotIn("explanation", projection)

    def test_record_only_partial_dependency_collection_emits_positive_items(self) -> None:
        record = record_with(declaration("dependencies", {"kind": "record"}))
        record["dependencies"] = [DEPENDENCY]
        projection = linguistic_projection(record)
        self.assertEqual(projection["dependencies"], [DEPENDENCY])

    def test_partial_collection_does_not_emit_negative_or_empty_supervision(self) -> None:
        record = record_with(declaration("dependencies", {"kind": "record"}))
        record["dependencies"] = [DEPENDENCY, MALFORMED_DEPENDENCY]
        projection = linguistic_projection(record)
        self.assertEqual(projection["dependencies"], [DEPENDENCY])
        self.assertNotEqual(projection["dependencies"], [])
        self.assertNotIn("ghost", json.dumps(projection))

    def test_partial_present_is_not_confirmed_empty(self) -> None:
        record = record_with(declaration("dependencies", {"kind": "record"}))
        record["dependencies"] = [DEPENDENCY]
        self.assertIs(resolve_coverage(record, "dependencies"), CoverageState.PARTIAL_COVERED)
        self.assertEqual(linguistic_projection(record)["dependencies"], [DEPENDENCY])

    def test_partial_dependency_reference_shell_remains_valid(self) -> None:
        record = record_with(declaration("dependencies", {"kind": "record"}))
        record["dependencies"] = [DEPENDENCY]
        projection = linguistic_projection(record)
        constituents = {item["id"]: item for item in projection.get("constituents", [])}
        self.assertEqual(constituents["subj"], {"id": "subj", "node_kind": "phrase", "span": {"start": 0, "end": 2}})

    def test_unresolved_only_content_does_not_leak(self) -> None:
        projection = linguistic_projection(FIXTURE)
        serialized = json.dumps(projection)
        self.assertNotIn("unresolved", serialized)
        self.assertNotIn("notes", serialized)
        typed = projection.get("canonical_analysis", {}).get("typed_analysis", {})
        self.assertNotIn("status", typed)

    def test_partial_valency_projection_emits_only_represented_predicates(self) -> None:
        record = record_with(declaration("lexical_valency", {"kind": "record"}))
        record["lexical_valency"] = [VALENCY]
        projection = linguistic_projection(record)
        self.assertEqual(projection["lexical_valency"], [{"predicate": "w2", "frame": "transitive", "selected_complements": ["obj"]}])


if __name__ == "__main__":
    unittest.main()
