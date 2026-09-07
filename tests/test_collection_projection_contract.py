from __future__ import annotations

import copy
import unittest
from pathlib import Path
from typing import Any

from scripts.collection_contract import normalize_predicate_reference
from scripts.coverage_resolution import CoverageResolutionError, CoverageState, resolve_coverage, resolve_scoring_eligibility
from scripts.data_common import read_jsonl
from scripts.render_sft import linguistic_projection, render_record
from scripts.validate_dataset import coverage_allows_score, validate_record


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


def record_with(
    dimension: str,
    entry: dict[str, Any],
    values: list[dict[str, Any]],
) -> dict[str, Any]:
    record = copy.deepcopy(FIXTURE)
    record[dimension] = copy.deepcopy(values)
    record["annotation_scope"]["dimensions"] = [entry]
    return record


DEPENDENCY = {"relation": "selected", "head": "w2", "dependent": "obj"}
ROLE = {"constituent": "obj", "role": "Theme", "predicate": "catalogue"}
VALENCY = {"predicate": "catalogue", "frame": "transitive", "selected_complements": ["obj"]}


class CollectionProjectionContractTests(unittest.TestCase):
    def test_dependencies_present_scores_and_renders_all_references(self) -> None:
        record = record_with("dependencies", declaration("dependencies", {"kind": "record"}), [DEPENDENCY])
        self.assertTrue(coverage_allows_score(record, "dependencies"))
        self.assertEqual(linguistic_projection(record)["dependencies"], [DEPENDENCY])
        self.assertEqual(validate_record(record, "dependencies-present"), [])

    def test_dependencies_confirmed_empty_scores_and_renders_empty_list(self) -> None:
        record = record_with("dependencies", declaration("dependencies", {"kind": "record"}, evidence="empty"), [])
        self.assertTrue(coverage_allows_score(record, "dependencies"))
        self.assertEqual(linguistic_projection(record)["dependencies"], [])

    def test_dependencies_unannotated_is_not_scoreable_or_rendered(self) -> None:
        record = record_with(
            "dependencies",
            declaration("dependencies", {"kind": "record"}, "unannotated", "intentional", "unannotated"),
            [],
        )
        self.assertFalse(coverage_allows_score(record, "dependencies"))
        self.assertNotIn("dependencies", linguistic_projection(record))

    def test_dependencies_scope_and_references_have_separate_contracts(self) -> None:
        record = record_with("dependencies", declaration("dependencies", {"kind": "node", "node": "w2"}), [DEPENDENCY])
        self.assertTrue(any("dependencies" in error and "scope" in error for error in validate_record(record, "dependency-scope")))
        with self.assertRaises(CoverageResolutionError):
            resolve_coverage(record, "dependencies")

        record = record_with("dependencies", declaration("dependencies", {"kind": "record"}), [{"relation": "selected", "head": "missing", "dependent": "obj"}])
        self.assertTrue(any("dependency must reference known IDs" in error for error in validate_record(record, "dependency-reference")))

        record = record_with("dependencies", declaration("dependencies", {"kind": "record"}), [DEPENDENCY])
        record["annotation_scope"]["dimensions"].append(
            declaration("syntactic_function", {"kind": "node", "node": "obj"})
        )
        self.assertEqual(validate_record(record, "dependency-owner-isolation"), [])
        self.assertEqual(linguistic_projection(record)["dependencies"], [DEPENDENCY])

    def test_semantic_roles_present_and_empty_follow_record_scope(self) -> None:
        present = record_with("semantic_roles", declaration("semantic_roles", {"kind": "record"}), [ROLE])
        self.assertTrue(coverage_allows_score(present, "semantic_roles"))
        self.assertEqual(linguistic_projection(present)["semantic_roles"], [{"constituent": "obj", "role": "Theme", "predicate": "w2"}])
        self.assertEqual(validate_record(present, "roles-present"), [])

        empty = record_with("semantic_roles", declaration("semantic_roles", {"kind": "record"}, evidence="empty"), [])
        self.assertTrue(coverage_allows_score(empty, "semantic_roles"))
        self.assertEqual(linguistic_projection(empty)["semantic_roles"], [])

    def test_semantic_role_node_and_region_scopes_are_rejected(self) -> None:
        for scope in ({"kind": "node", "node": "obj"}, {"kind": "region", "start": 0, "end": 2}):
            with self.subTest(scope=scope):
                record = record_with("semantic_roles", declaration("semantic_roles", scope), [ROLE])
                self.assertTrue(any("semantic_roles" in error and "scope" in error for error in validate_record(record, "role-scope")))
                with self.assertRaises(CoverageResolutionError):
                    resolve_coverage(record, "semantic_roles")

    def test_predicate_lemma_normalization_is_unique_and_explicit(self) -> None:
        record = record_with("semantic_roles", declaration("semantic_roles", {"kind": "record"}), [ROLE])
        self.assertEqual(normalize_predicate_reference(record, "catalogue"), "w2")
        explicit = copy.deepcopy(record)
        explicit["semantic_roles"][0]["predicate"] = "w2"
        self.assertEqual(validate_record(explicit, "role-explicit-id"), [])
        rendered = render_record(record)
        self.assertEqual(validate_record(rendered, "roles-rendered"), [])

        record["words"][4]["lemma"] = "catalogue"
        self.assertIsNone(normalize_predicate_reference(record, "catalogue"))
        self.assertTrue(any("multiple word IDs" in error for error in validate_record(record, "role-ambiguous")))
        self.assertNotIn("semantic_roles", linguistic_projection(record))

    def test_valency_is_owned_by_lexical_head_not_selected_complement(self) -> None:
        head_scoped = record_with(
            "lexical_valency",
            declaration("lexical_valency", {"kind": "node", "node": "w2"}),
            [VALENCY],
        )
        self.assertTrue(coverage_allows_score(head_scoped, "lexical_valency", "w2"))
        self.assertEqual(linguistic_projection(head_scoped)["lexical_valency"], [{"predicate": "w2", "frame": "transitive", "selected_complements": ["obj"]}])

        record_scoped = record_with(
            "lexical_valency",
            declaration("lexical_valency", {"kind": "record"}, "partial"),
            [VALENCY],
        )
        self.assertFalse(coverage_allows_score(record_scoped, "lexical_valency", "obj"))
        self.assertNotIn("lexical_valency", linguistic_projection(record_scoped))

    def test_covered_valency_keeps_selected_complements_when_not_covered(self) -> None:
        record = record_with(
            "lexical_valency",
            declaration("lexical_valency", {"kind": "node", "node": "w2"}),
            [VALENCY],
        )
        record["annotation_scope"]["dimensions"].append(
            declaration("syntactic_function", {"kind": "node", "node": "obj"}, "omitted", "intentional", "unannotated")
        )
        projection = linguistic_projection(record)
        self.assertEqual(projection["lexical_valency"][0]["selected_complements"], ["obj"])

    def test_ambiguous_valency_head_fails_closed(self) -> None:
        record = record_with(
            "lexical_valency",
            declaration("lexical_valency", {"kind": "node", "node": "w2"}),
            [VALENCY],
        )
        record["words"][4]["lemma"] = "catalogue"
        self.assertTrue(any("multiple word IDs" in error for error in validate_record(record, "valency-ambiguous")))
        self.assertNotIn("lexical_valency", linguistic_projection(record))

    def test_valency_projection_is_declaration_order_independent(self) -> None:
        entries = [
            declaration("lexical_valency", {"kind": "record"}, "unannotated", "intentional", "unannotated"),
            declaration("lexical_valency", {"kind": "node", "node": "w2"}),
        ]
        forward = record_with("lexical_valency", entries[0], [VALENCY])
        reverse = copy.deepcopy(forward)
        forward["annotation_scope"]["dimensions"] = entries
        reverse["annotation_scope"]["dimensions"] = list(reversed(entries))
        self.assertEqual(linguistic_projection(forward), linguistic_projection(reverse))
        self.assertEqual(linguistic_projection(forward)["lexical_valency"][0]["predicate"], "w2")

    def test_confirmed_empty_record_scope_does_not_hide_more_specific_valency(self) -> None:
        record = record_with(
            "lexical_valency",
            declaration("lexical_valency", {"kind": "record"}, evidence="empty"),
            [VALENCY],
        )
        record["annotation_scope"]["dimensions"].append(
            declaration("lexical_valency", {"kind": "node", "node": "w2"})
        )
        self.assertEqual(validate_record(record, "valency-layered"), [])
        self.assertIs(resolve_coverage(record, "lexical_valency"), CoverageState.CONFIRMED_EMPTY)
        self.assertIs(resolve_coverage(record, "lexical_valency", "w2"), CoverageState.COMPLETE)
        self.assertEqual(linguistic_projection(record)["lexical_valency"][0]["predicate"], "w2")

    def test_collection_presence_tracks_scoring_authority(self) -> None:
        cases = (
            ("dependencies", declaration("dependencies", {"kind": "record"}), [DEPENDENCY], None, True, True),
            ("dependencies", declaration("dependencies", {"kind": "record"}, evidence="empty"), [], None, True, True),
            ("dependencies", declaration("dependencies", {"kind": "record"}, "unannotated", "intentional", "unannotated"), [], None, False, False),
            ("semantic_roles", declaration("semantic_roles", {"kind": "record"}), [ROLE], None, True, True),
            ("semantic_roles", declaration("semantic_roles", {"kind": "record"}, evidence="empty"), [], None, True, True),
            ("semantic_roles", declaration("semantic_roles", {"kind": "record"}, "unannotated", "intentional", "unannotated"), [], None, False, False),
            ("lexical_valency", declaration("lexical_valency", {"kind": "node", "node": "w2"}), [VALENCY], "w2", True, True),
            ("lexical_valency", declaration("lexical_valency", {"kind": "record"}, evidence="empty"), [], None, True, True),
            ("lexical_valency", declaration("lexical_valency", {"kind": "record"}, "unannotated", "intentional", "unannotated"), [], None, False, False),
        )
        for dimension, entry, values, target, scoreable, rendered in cases:
            with self.subTest(dimension=dimension, target=target):
                record = record_with(dimension, entry, values)
                decision = resolve_scoring_eligibility(record, dimension, target)
                self.assertEqual(decision.scoreable, scoreable)
                self.assertEqual(dimension in linguistic_projection(record), rendered)

    def test_uncovered_collection_items_are_not_projected(self) -> None:
        record = record_with(
            "lexical_valency",
            declaration("lexical_valency", {"kind": "record"}, "partial"),
            [VALENCY],
        )
        decision = resolve_scoring_eligibility(record, "lexical_valency", "w2")
        self.assertFalse(decision.scoreable)
        self.assertIs(decision.coverage_state, CoverageState.PARTIAL_UNCOVERED)
        self.assertNotIn("lexical_valency", linguistic_projection(record))

    def test_confirmed_empty_is_only_allowed_at_registry_supported_scope(self) -> None:
        for dimension, node in (("dependencies", "w2"), ("semantic_roles", "obj"), ("lexical_valency", "w2")):
            with self.subTest(dimension=dimension):
                record = record_with(dimension, declaration(dimension, {"kind": "node", "node": node}, evidence="empty"), [])
                self.assertTrue(any(dimension in error and "scope" in error for error in validate_record(record, "unsupported-empty")))
                with self.assertRaises(CoverageResolutionError):
                    resolve_coverage(record, dimension, node)


if __name__ == "__main__":
    unittest.main()
