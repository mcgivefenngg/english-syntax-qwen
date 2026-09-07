from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from typing import Any

from scripts.authoritative_payload import (
    AuthoritativePayloadState,
    authoritative_payload,
    authoritative_payload_items,
    authoritative_payload_state,
)
from scripts.data_common import read_jsonl
from scripts.coverage_resolution import resolve_scoring_eligibility
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


def unresolved_lexical_analysis() -> dict[str, Any]:
    return {
        "status": "unresolved",
        "review_required": True,
        "candidates": [
            {
                "category": "pronoun",
                "category_namespace": "project_canonical",
            },
            {
                "category": "subordinator",
                "category_namespace": "traditional_pedagogical",
            },
        ],
    }


def lexical_node_record(*word_ids: str) -> dict[str, Any]:
    record = copy.deepcopy(FIXTURE)
    record["annotation_scope"]["dimensions"] = [
        entry
        for entry in record["annotation_scope"]["dimensions"]
        if entry.get("dimension") != "lexical_category"
    ] + [
        declaration("lexical_category", {"kind": "node", "node": word_id})
        for word_id in word_ids
    ]
    return record


def typed_relation(relation_type: str) -> dict[str, Any]:
    return {
        "id": f"rel-{relation_type}",
        "type": relation_type,
        "arity": "binary",
        "source": {"namespace": "word", "id": "w1"},
        "target": {"namespace": "constituent", "id": "obj"},
    }


class AuthoritativePayloadContractTests(unittest.TestCase):
    def test_valid_lexical_scalar_without_unresolved_analysis_remains_resolved(self) -> None:
        record = lexical_node_record("w0")
        payload = authoritative_payload(record, "lexical_category", "w0")
        self.assertIs(payload.state, AuthoritativePayloadState.PRESENT)
        self.assertTrue(payload.fully_resolved)

    def test_null_lexical_scalar_with_unresolved_analysis_remains_unresolved(self) -> None:
        record = lexical_node_record("w0")
        word = record["words"][0]
        word["lexical_category"] = None
        word["lexical_analysis"] = unresolved_lexical_analysis()
        payload = authoritative_payload(record, "lexical_category", "w0")
        self.assertIs(payload.state, AuthoritativePayloadState.UNRESOLVED_ONLY)
        self.assertFalse(payload.fully_resolved)

    def test_unresolved_lexical_analysis_overrides_stale_scalar(self) -> None:
        record = lexical_node_record("w0")
        record["words"][0]["lexical_analysis"] = unresolved_lexical_analysis()
        payload = authoritative_payload(record, "lexical_category", "w0")
        self.assertIs(payload.state, AuthoritativePayloadState.UNRESOLVED_ONLY)
        self.assertFalse(payload.has_resolved_content)
        self.assertFalse(payload.fully_resolved)

        errors = validate_record(record, "stale-lexical-category")
        self.assertTrue(any("cannot retain a canonical lexical_category" in error for error in errors))

    def test_stale_scalar_is_not_fully_resolved_or_scoreable(self) -> None:
        record = lexical_node_record("w0")
        record["words"][0]["lexical_analysis"] = unresolved_lexical_analysis()
        decision = resolve_scoring_eligibility(record, "lexical_category", "w0")
        self.assertFalse(decision.scoreable)
        self.assertIsNone(decision.coverage_state)

    def test_default_projection_omits_stale_lexical_category(self) -> None:
        record = lexical_node_record("w0")
        record["words"][0]["lexical_analysis"] = unresolved_lexical_analysis()
        projection = linguistic_projection(record)
        self.assertNotIn("w0", {word["id"] for word in projection.get("words", [])})
        self.assertNotIn("determinative", json.dumps(projection, ensure_ascii=False))

    def test_unrelated_lexical_word_remains_resolved(self) -> None:
        record = lexical_node_record("w0", "w1")
        record["words"][0]["lexical_analysis"] = unresolved_lexical_analysis()
        payload = authoritative_payload(record, "lexical_category", "w1")
        self.assertIs(payload.state, AuthoritativePayloadState.PRESENT)
        self.assertTrue(payload.fully_resolved)

    def test_resolved_lexical_categories_satisfy_present_coverage(self) -> None:
        payload = authoritative_payload(FIXTURE, "lexical_category")
        self.assertIs(payload.state, AuthoritativePayloadState.PRESENT)
        self.assertTrue(payload.fully_resolved)
        self.assertEqual(validate_record(FIXTURE, "resolved-lexical"), [])

    def test_unresolved_only_lexical_candidates_do_not_satisfy_present(self) -> None:
        record = copy.deepcopy(FIXTURE)
        for word in record["words"]:
            word["lexical_category"] = None
            word["lexical_analysis"] = unresolved_lexical_analysis()
        payload = authoritative_payload(record, "lexical_category")
        self.assertIs(payload.state, AuthoritativePayloadState.UNRESOLVED_ONLY)
        self.assertFalse(payload.has_resolved_content)
        errors = validate_record(record, "unresolved-lexical")
        self.assertTrue(any("lexical_category" in error and "resolved authoritative" in error for error in errors))

    def test_lexical_category_target_uses_only_target_resolvedness(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["words"][0]["lexical_category"] = None
        record["words"][0]["lexical_analysis"] = unresolved_lexical_analysis()
        resolved = authoritative_payload(record, "lexical_category", "w1")
        unresolved = authoritative_payload(record, "lexical_category", "w0")
        self.assertIs(resolved.state, AuthoritativePayloadState.PRESENT)
        self.assertTrue(resolved.fully_resolved)
        self.assertIs(unresolved.state, AuthoritativePayloadState.UNRESOLVED_ONLY)
        self.assertFalse(unresolved.fully_resolved)

    def test_np_internal_constituency_present_with_applicable_structure(self) -> None:
        record = with_declaration(record=FIXTURE, entry=declaration("np_internal_constituency", {"kind": "node", "node": "subj"}))
        payload = authoritative_payload(record, "np_internal_constituency", "subj")
        self.assertIs(payload.state, AuthoritativePayloadState.PRESENT)
        self.assertEqual(validate_record(record, "np-structure"), [])

    def test_np_internal_constituency_present_without_structure_is_rejected(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["constituents"] = []
        record = with_declaration(record, declaration("np_internal_constituency", {"kind": "record"}))
        payload = authoritative_payload(record, "np_internal_constituency")
        self.assertIs(payload.state, AuthoritativePayloadState.ABSENT)
        errors = validate_record(record, "np-no-structure")
        self.assertTrue(any("np_internal_constituency" in error and "resolved authoritative" in error for error in errors))

    def test_phrase_constituency_does_not_require_function_dimension(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["annotation_scope"]["dimensions"] = [
            entry
            for entry in record["annotation_scope"]["dimensions"]
            if entry.get("dimension") != "syntactic_function"
        ]
        payload = authoritative_payload(record, "phrase_constituency")
        self.assertIs(payload.state, AuthoritativePayloadState.PRESENT)
        self.assertEqual(validate_record(record, "phrase-without-function-coverage"), [])

    def test_vp_complementation_present_with_authoritative_valency(self) -> None:
        record = with_declaration(record=FIXTURE, entry=declaration("vp_complementation", {"kind": "record"}))
        record["lexical_valency"] = [{"predicate": "catalogue", "frame": "transitive", "selected_complements": ["obj"]}]
        payload = authoritative_payload(record, "vp_complementation")
        self.assertIs(payload.state, AuthoritativePayloadState.PRESENT)
        self.assertEqual(validate_record(record, "vp-with-valency"), [])

    def test_vp_complementation_present_without_payload_is_rejected(self) -> None:
        record = with_declaration(record=FIXTURE, entry=declaration("vp_complementation", {"kind": "record"}))
        record.pop("lexical_valency", None)
        payload = authoritative_payload(record, "vp_complementation")
        self.assertIs(payload.state, AuthoritativePayloadState.ABSENT)
        errors = validate_record(record, "vp-no-payload")
        self.assertTrue(any("vp_complementation" in error and "resolved authoritative" in error for error in errors))

    def test_syntactic_function_present_requires_applicable_function_content(self) -> None:
        present = authoritative_payload(FIXTURE, "syntactic_function")
        self.assertIs(present.state, AuthoritativePayloadState.PRESENT)
        record = copy.deepcopy(FIXTURE)
        record["constituents"] = []
        record = with_declaration(record, declaration("syntactic_function", {"kind": "record"}))
        absent = authoritative_payload(record, "syntactic_function")
        self.assertIs(absent.state, AuthoritativePayloadState.ABSENT)
        errors = validate_record(record, "function-no-payload")
        self.assertTrue(any("syntactic_function" in error and "resolved authoritative" in error for error in errors))

    def test_construction_relations_present_without_payload_is_rejected(self) -> None:
        record = with_declaration(record=FIXTURE, entry=declaration("construction_relations", {"kind": "record"}))
        record["canonical_analysis"]["typed_analysis"]["relations"] = []
        for field in ("construction_type", "construction_tags", "construction_signature", "heads", "complements", "adjuncts", "fusion_relations"):
            record.pop(field, None)
        payload = authoritative_payload(record, "construction_relations")
        self.assertIs(payload.state, AuthoritativePayloadState.ABSENT)
        errors = validate_record(record, "construction-no-payload")
        self.assertTrue(any("construction_relations" in error and "resolved authoritative" in error for error in errors))

    def test_valid_construction_payload_satisfies_present(self) -> None:
        record = with_declaration(record=FIXTURE, entry=declaration("construction_relations", {"kind": "record"}))
        record["construction_type"] = "transitive"
        payload = authoritative_payload(record, "construction_relations")
        self.assertIs(payload.state, AuthoritativePayloadState.PRESENT)
        self.assertEqual(validate_record(record, "construction-payload"), [])

    def test_construction_payload_enumeration_follows_registry_surfaces(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["construction_signature"] = {
            "predicate_lemma": "catalogue",
            "construction_type": "transitive",
            "argument_pattern": ["NP"],
            "function_pattern": ["object"],
        }
        record["construction_type"] = "transitive"
        record["construction_tags"] = ["transitive"]
        record["heads"] = [{"head": "w2", "dependent": "obj", "relation": "selects"}]
        record["fusion_relations"] = [{
            "id": "fusion",
            "type": "fused_relative",
            "fused_element": "w2",
            "whole_constituent": "subj",
            "relative_clause": "c0",
            "fused_functions": ["nominal", "relativized"],
        }]
        record["canonical_analysis"]["typed_analysis"]["status"] = "established"
        record["canonical_analysis"]["typed_analysis"]["relations"] = [typed_relation("construction")]
        items = authoritative_payload_items(record, "construction_relations")
        self.assertEqual(
            {item.field for item in items},
            {"construction_signature", "construction_type", "construction_tags", "heads", "fusion_relations", "typed_relation"},
        )
        self.assertTrue(all(item.status == "resolved" for item in items))

    def test_semantic_role_without_predicate_is_resolved_payload(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["semantic_roles"] = [{"constituent": "obj", "role": "Theme"}]
        record = with_declaration(record, declaration("semantic_roles", {"kind": "record"}))
        payload = authoritative_payload(record, "semantic_roles")
        self.assertIs(payload.state, AuthoritativePayloadState.PRESENT)
        self.assertTrue(payload.fully_resolved)
        self.assertEqual(validate_record(record, "optional-predicate"), [])

    def test_typed_construction_relation_belongs_to_construction_dimension(self) -> None:
        record = with_declaration(record=FIXTURE, entry=declaration("construction_relations", {"kind": "record"}))
        record = with_declaration(record, declaration("dependencies", {"kind": "record"}, evidence="empty"))
        record["canonical_analysis"]["typed_analysis"]["status"] = "established"
        record["canonical_analysis"]["typed_analysis"]["relations"] = [typed_relation("construction")]
        self.assertIs(authoritative_payload_state(record, "construction_relations"), AuthoritativePayloadState.PRESENT)
        self.assertIs(authoritative_payload_state(record, "dependencies"), AuthoritativePayloadState.CONFIRMED_EMPTY)
        self.assertEqual(validate_record(record, "construction-owner"), [])

    def test_typed_dependency_relation_belongs_only_to_dependencies(self) -> None:
        record = with_declaration(record=FIXTURE, entry=declaration("dependencies", {"kind": "record"}))
        record["canonical_analysis"]["typed_analysis"]["status"] = "established"
        record["canonical_analysis"]["typed_analysis"]["relations"] = [typed_relation("dependency")]
        self.assertIs(authoritative_payload_state(record, "dependencies"), AuthoritativePayloadState.PRESENT)
        self.assertIs(authoritative_payload_state(record, "construction_relations"), AuthoritativePayloadState.ABSENT)
        self.assertEqual(validate_record(record, "dependency-owner"), [])

    def test_confirmed_empty_dependencies_conflict_with_owned_typed_relation(self) -> None:
        record = with_declaration(record=FIXTURE, entry=declaration("dependencies", {"kind": "record"}, evidence="empty"))
        record["canonical_analysis"]["typed_analysis"]["status"] = "established"
        record["canonical_analysis"]["typed_analysis"]["relations"] = [typed_relation("dependency")]
        errors = validate_record(record, "dependency-empty-typed")
        self.assertTrue(any("dependencies" in error and "evidence='empty'" in error for error in errors))

    def test_unannotated_owned_payload_is_rejected(self) -> None:
        record = with_declaration(
            record=FIXTURE,
            entry=declaration("lexical_category", {"kind": "record"}, "unannotated", "intentional", "unannotated"),
        )
        errors = validate_record(record, "lexical-unannotated-payload")
        self.assertTrue(any("lexical_category" in error and "unannotated/omitted" in error for error in errors))

    def test_payload_state_is_declaration_order_independent(self) -> None:
        entries = [
            declaration("construction_relations", {"kind": "record"}),
            declaration("dependencies", {"kind": "record"}, evidence="empty"),
        ]
        record = copy.deepcopy(FIXTURE)
        record["construction_type"] = "transitive"
        record["annotation_scope"]["dimensions"] = entries
        forward = authoritative_payload(record, "construction_relations")
        reverse_record = copy.deepcopy(record)
        reverse_record["annotation_scope"]["dimensions"] = list(reversed(entries))
        reverse = authoritative_payload(reverse_record, "construction_relations")
        self.assertEqual(forward, reverse)
        self.assertIs(authoritative_payload_state(reverse_record, "dependencies"), AuthoritativePayloadState.CONFIRMED_EMPTY)


if __name__ == "__main__":
    unittest.main()
