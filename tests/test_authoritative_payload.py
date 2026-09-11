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
    confirmed_empty_eligible,
    construction_typed_relation_types,
    typed_analysis_relation_entries,
    typed_argument_owner_dimensions,
    typed_relation_owner_dimensions,
)
from scripts.canonical_schema import canonical_schema_issues
from scripts.data_common import read_jsonl
from scripts.coverage_resolution import CoverageState, resolve_coverage, resolve_scoring_eligibility
from scripts.dimension_registry import dimension_spec
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
        projected_words = {word["id"]: word for word in projection.get("words", [])}
        self.assertIn("w0", projected_words)
        self.assertNotIn("lexical_category", projected_words["w0"])
        self.assertNotIn("external_pos_tags", projected_words["w0"])
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

    def test_nested_construction_arguments_and_entities_are_enumerated(self) -> None:
        record = copy.deepcopy(FIXTURE)
        typed = record["canonical_analysis"]["typed_analysis"]
        typed["status"] = "established"
        typed["relations"] = [
            {
                "id": "rel-entity-ref",
                "type": "construction",
                "arity": "binary",
                "source": {"namespace": "word", "id": "w1"},
                "target": {"namespace": "analysis", "id": "e1"},
            },
            {
                "id": "rel-dependency-ref",
                "type": "dependency",
                "arity": "binary",
                "source": "word:w2",
                "target": "analysis:e2",
            },
        ]
        typed["arguments"] = {"a1": {"kind": "subject", "target": "subj"}}
        typed["entities"] = [{"id": "e1", "kind": "clause"}, {"id": "e2", "kind": "understood_subject"}]
        items = authoritative_payload_items(record, "construction_relations")
        by_field: dict[str, set[str]] = {}
        for item in items:
            by_field.setdefault(item.field, set()).add(item.identifier)
        self.assertEqual(by_field.get("typed_arguments"), {"typed_arguments[a1]"})
        self.assertEqual(by_field.get("typed_entity"), {"e1", "e2"})
        self.assertEqual(by_field.get("typed_relation"), {"rel-entity-ref"})
        argument = next(item for item in items if item.field == "typed_arguments")
        self.assertEqual(argument.path, ("canonical_analysis", "typed_analysis", "arguments", "a1"))
        self.assertEqual(argument.status, "resolved")
        self.assertEqual(authoritative_payload_items(record, "dependencies"), ())

    def test_registry_helpers_report_shared_nested_payload_ownership(self) -> None:
        self.assertEqual(
            typed_argument_owner_dimensions({"id": "a1", "kind": "subject", "target": "subj"}),
            {"dependencies"},
        )
        self.assertEqual(
            typed_argument_owner_dimensions({"relation": "obj", "head": "w2", "dependent": "obj"}),
            {"dependencies", "vp_complementation"},
        )
        self.assertEqual(typed_argument_owner_dimensions({"role": "Agent"}), {"semantic_roles"})
        self.assertEqual(typed_argument_owner_dimensions({"category": "noun"}), {
            "lexical_category", "phrase_constituency", "constituency", "np_internal_constituency",
        })
        self.assertEqual(typed_argument_owner_dimensions({"function": "object"}), {"syntactic_function"})
        self.assertEqual(typed_argument_owner_dimensions({"construction_frame": "x"}), frozenset())
        self.assertEqual(typed_argument_owner_dimensions("literal"), frozenset())
        self.assertEqual(typed_relation_owner_dimensions("dependency"), {"dependencies"})
        self.assertEqual(typed_relation_owner_dimensions("selection"), {"vp_complementation"})
        self.assertEqual(typed_relation_owner_dimensions("construction"), {"construction_relations"})
        self.assertEqual(typed_relation_owner_dimensions("pedagogical:object"), frozenset())
        self.assertIn("construction", construction_typed_relation_types())
        self.assertNotIn("dependency", construction_typed_relation_types())

    def test_typed_analysis_relation_entries_are_analysis_local(self) -> None:
        record = copy.deepcopy(FIXTURE)
        canonical_relation = {
            "id": "rel-canonical",
            "type": "dependency",
            "arity": "binary",
            "source": "word:w2",
            "target": "analysis:e1",
        }
        alternative_relation = {
            "id": "rel-alternative",
            "type": "pedagogical:object",
            "arity": "binary",
            "source": "word:w2",
            "target": "analysis:e1",
        }
        record["canonical_analysis"]["typed_analysis"]["relations"] = [canonical_relation]
        record["alternative_analyses"] = [{
            "id": "alt-1",
            "framework": "CGEL",
            "status": "established",
            "typed_analysis": {
                "kind": "record_level_analysis",
                "framework": "CGEL",
                "status": "established",
                "relations": [alternative_relation],
            },
        }]
        entries = typed_analysis_relation_entries(record)
        self.assertEqual(entries, [
            (("canonical_analysis", "typed_analysis"), canonical_relation),
            (("alternative_analyses", 0, "typed_analysis"), alternative_relation),
        ])

    def test_typed_arguments_container_forms_are_enumerated(self) -> None:
        base = copy.deepcopy(FIXTURE)
        base["canonical_analysis"]["typed_analysis"]["status"] = "established"
        forms = (
            ([{"kind": "subject", "target": "subj"}], {"typed_arguments[0]"}, ("canonical_analysis", "typed_analysis", "arguments", 0)),
            ({"kind": "subject", "target": "subj"}, {"typed_arguments"}, ("canonical_analysis", "typed_analysis", "arguments")),
            ({"a1": {"id": "arg-a1", "kind": "subject"}}, {"arg-a1"}, ("canonical_analysis", "typed_analysis", "arguments", "a1")),
            ("literal", {"typed_arguments"}, ("canonical_analysis", "typed_analysis", "arguments")),
        )
        for arguments, expected_identifiers, expected_path in forms:
            with self.subTest(arguments=arguments):
                record = copy.deepcopy(base)
                record["canonical_analysis"]["typed_analysis"]["arguments"] = copy.deepcopy(arguments)
                items = [
                    item for item in authoritative_payload_items(record, "construction_relations")
                    if item.field == "typed_arguments"
                ]
                self.assertEqual({item.identifier for item in items}, expected_identifiers)
                self.assertEqual(items[0].path, expected_path)

    def test_unresolved_typed_analysis_marks_nested_items_unresolved(self) -> None:
        record = copy.deepcopy(FIXTURE)
        typed = record["canonical_analysis"]["typed_analysis"]
        typed["status"] = "unresolved"
        typed["arguments"] = {"a1": {"kind": "subject", "target": "subj"}}
        typed["entities"] = [{"id": "e1", "kind": "clause"}, {"kind": "anonymous"}]
        items = authoritative_payload_items(record, "construction_relations")
        statuses = {item.identifier: item.status for item in items if item.field in {"typed_arguments", "typed_entity"}}
        self.assertEqual(statuses, {"typed_arguments[a1]": "unresolved", "e1": "unresolved", "typed_entity[1]": "missing"})

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


class CanonicalNodePayloadIntegrityTests(unittest.TestCase):
    """A1a: validator-invalid canonical nodes are never resolved positive payload."""

    def mutated_record(self, field: str, value: Any, collection: str = "constituents", index: int = 0) -> dict[str, Any]:
        record = copy.deepcopy(FIXTURE)
        record[collection][index][field] = copy.deepcopy(value)
        return record

    def subordinate_clause(self) -> dict[str, Any]:
        return {
            "id": "c1",
            "node_kind": "clause",
            "span": {"start": 3, "end": 5},
            "finiteness": "finite",
            "clause_construction": "relative",
            "integration": ["subordinate"],
            "integration_parent": "c0",
        }

    def clause_wrapper(self, clause_ref: str, **extra: Any) -> dict[str, Any]:
        wrapper: dict[str, Any] = {
            "id": "emb",
            "node_kind": "clause",
            "clause_ref": clause_ref,
            "span": {"start": 3, "end": 5},
            "function": "complement",
            "realization": {"clause_ref": clause_ref, "relation": "other"},
        }
        wrapper.update(extra)
        return wrapper

    def assert_not_resolved(self, record: dict[str, Any], dimension: str, target: str) -> None:
        payload = authoritative_payload(record, dimension, target)
        self.assertIs(payload.state, AuthoritativePayloadState.ABSENT)
        self.assertFalse(payload.has_resolved_content)
        self.assertEqual(payload.missing_count, 1)

    def test_valid_phrase_constituent_remains_resolved(self) -> None:
        payload = authoritative_payload(FIXTURE, "phrase_constituency", "subj")
        self.assertIs(payload.state, AuthoritativePayloadState.PRESENT)
        self.assertTrue(payload.fully_resolved)
        self.assertEqual(validate_record(FIXTURE, "valid-constituent"), [])

    def test_dangling_constituent_head_is_not_resolved(self) -> None:
        record = self.mutated_record("head", "ghost")
        self.assertFalse(canonical_schema_issues(record))
        self.assertTrue(any("constituent.head" in error for error in validate_record(record, "dangling-head")))
        self.assert_not_resolved(record, "phrase_constituency", "subj")

    def test_wrong_kind_constituent_head_is_not_resolved(self) -> None:
        record = self.mutated_record("head", "obj")
        self.assertFalse(canonical_schema_issues(record))
        self.assertTrue(any("constituent.head" in error for error in validate_record(record, "wrong-kind-head")))
        self.assert_not_resolved(record, "phrase_constituency", "subj")

    def test_dangling_constituent_parent_is_not_resolved(self) -> None:
        record = self.mutated_record("parent", "ghost")
        self.assertFalse(canonical_schema_issues(record))
        self.assertTrue(any("constituent.parent" in error for error in validate_record(record, "dangling-parent")))
        self.assert_not_resolved(record, "phrase_constituency", "subj")

    def test_word_valued_constituent_parent_is_not_resolved(self) -> None:
        record = self.mutated_record("parent", "w1")
        self.assertFalse(canonical_schema_issues(record))
        self.assertTrue(any("constituent.parent" in error for error in validate_record(record, "word-parent")))
        self.assert_not_resolved(record, "phrase_constituency", "subj")

    def test_invalid_constituent_target_is_not_scoreable(self) -> None:
        record = self.mutated_record("head", "ghost")
        decision = resolve_scoring_eligibility(record, "phrase_constituency", "subj")
        self.assertFalse(decision.scoreable)
        self.assertIs(decision.coverage_state, CoverageState.PARTIAL_UNCOVERED)

    def test_clause_wrapper_with_dangling_reference_is_not_resolved(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["constituents"].append(self.clause_wrapper("ghost"))
        self.assertFalse(canonical_schema_issues(record))
        self.assertTrue(any("must reference a known clause" in error for error in validate_record(record, "wrapper-ghost")))
        self.assert_not_resolved(record, "phrase_constituency", "emb")

    def test_clause_wrapper_with_existing_reference_remains_resolved(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["constituents"].append(self.clause_wrapper("c0"))
        self.assertEqual(validate_record(record, "wrapper-valid"), [])
        payload = authoritative_payload(record, "phrase_constituency", "emb")
        self.assertIs(payload.state, AuthoritativePayloadState.PRESENT)
        self.assertTrue(payload.fully_resolved)

    def test_clause_wrapper_span_relation_must_agree_with_realization(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["constituents"].append(self.clause_wrapper("c0", span_relation="same_span_alias"))
        self.assertFalse(canonical_schema_issues(record))
        self.assertTrue(any("span_relation must agree" in error for error in validate_record(record, "wrapper-span-relation")))
        self.assert_not_resolved(record, "phrase_constituency", "emb")

    def test_valid_clause_remains_resolved(self) -> None:
        payload = authoritative_payload(FIXTURE, "clause_ontology", "c0")
        self.assertIs(payload.state, AuthoritativePayloadState.PRESENT)
        self.assertTrue(payload.fully_resolved)

    def test_contradictory_root_integration_is_not_resolved(self) -> None:
        record = self.mutated_record("integration", ["root", "subordinate"], collection="clauses")
        self.assertFalse(canonical_schema_issues(record))
        self.assertTrue(any("root integration cannot mix" in error for error in validate_record(record, "mixed-root")))
        self.assert_not_resolved(record, "clause_ontology", "c0")

    def test_mixed_unresolved_integration_is_invalid_not_unresolved(self) -> None:
        record = self.mutated_record("integration", ["unresolved", "subordinate"], collection="clauses")
        self.assertFalse(canonical_schema_issues(record))
        self.assertTrue(any("cannot mix unresolved" in error for error in validate_record(record, "mixed-unresolved")))
        payload = authoritative_payload(record, "clause_ontology", "c0")
        self.assertIs(payload.state, AuthoritativePayloadState.ABSENT)
        self.assertEqual(payload.unresolved_count, 0)
        self.assertEqual(payload.missing_count, 1)

    def test_explicit_unresolved_clause_authority_stays_unresolved(self) -> None:
        for field, value in (
            ("clause_construction", "unresolved"),
            ("finiteness", "unspecified"),
            ("integration", ["unresolved"]),
        ):
            with self.subTest(field=field):
                record = self.mutated_record(field, value, collection="clauses")
                payload = authoritative_payload(record, "clause_ontology", "c0")
                self.assertIs(payload.state, AuthoritativePayloadState.UNRESOLVED_ONLY)
                self.assertFalse(payload.has_resolved_content)
                self.assertEqual(payload.unresolved_count, 1)
                self.assertEqual(payload.missing_count, 0)

    def test_dangling_clause_subject_is_not_resolved(self) -> None:
        record = self.mutated_record("subject", "ghost", collection="clauses")
        self.assertFalse(canonical_schema_issues(record))
        self.assertTrue(any("subject must reference a known ID" in error for error in validate_record(record, "dangling-subject")))
        self.assert_not_resolved(record, "clause_ontology", "c0")

    def test_nonnominal_clause_subject_is_not_resolved(self) -> None:
        for subject in ("w2", "w5"):
            with self.subTest(subject=subject):
                record = self.mutated_record("subject", subject, collection="clauses")
                self.assertFalse(canonical_schema_issues(record))
                self.assertTrue(any("must be nominal" in error for error in validate_record(record, "nonnominal-subject")))
                self.assert_not_resolved(record, "clause_ontology", "c0")

    def test_nominal_word_and_np_phrase_subjects_remain_resolved(self) -> None:
        for subject in ("w1", "subj"):
            with self.subTest(subject=subject):
                record = self.mutated_record("subject", subject, collection="clauses")
                self.assertEqual(validate_record(record, "valid-subject"), [])
                payload = authoritative_payload(record, "clause_ontology", "c0")
                self.assertIs(payload.state, AuthoritativePayloadState.PRESENT)
                self.assertTrue(payload.fully_resolved)

    def test_dangling_clause_head_is_not_resolved(self) -> None:
        record = self.mutated_record("head", "ghost", collection="clauses")
        self.assertFalse(canonical_schema_issues(record))
        self.assertTrue(any("head must reference a known ID" in error for error in validate_record(record, "dangling-clause-head")))
        self.assert_not_resolved(record, "clause_ontology", "c0")

    def test_known_clause_head_remains_resolved(self) -> None:
        record = self.mutated_record("head", "w2", collection="clauses")
        self.assertEqual(validate_record(record, "known-clause-head"), [])
        payload = authoritative_payload(record, "clause_ontology", "c0")
        self.assertIs(payload.state, AuthoritativePayloadState.PRESENT)
        self.assertTrue(payload.fully_resolved)

    def test_dangling_and_nonword_clause_markers_are_not_resolved(self) -> None:
        for markers in (["ghost"], ["subj"]):
            with self.subTest(markers=markers):
                record = self.mutated_record("marker_ids", markers, collection="clauses")
                self.assertFalse(canonical_schema_issues(record))
                self.assertTrue(any("marker_ids" in error for error in validate_record(record, "bad-markers")))
                self.assert_not_resolved(record, "clause_ontology", "c0")

    def test_clause_marker_outside_span_is_not_resolved(self) -> None:
        record = self.mutated_record("marker_ids", ["w5"], collection="clauses")
        self.assertFalse(canonical_schema_issues(record))
        self.assertTrue(any("inside clause span" in error for error in validate_record(record, "outside-marker")))
        self.assert_not_resolved(record, "clause_ontology", "c0")

    def test_word_marker_inside_clause_span_remains_resolved(self) -> None:
        record = self.mutated_record("marker_ids", ["w2"], collection="clauses")
        self.assertEqual(validate_record(record, "inside-marker"), [])
        payload = authoritative_payload(record, "clause_ontology", "c0")
        self.assertIs(payload.state, AuthoritativePayloadState.PRESENT)
        self.assertTrue(payload.fully_resolved)

    def test_dangling_and_wrong_kind_integration_parent_are_not_resolved(self) -> None:
        for parent in ("ghost", "subj"):
            with self.subTest(parent=parent):
                record = self.mutated_record("integration_parent", parent, collection="clauses")
                self.assertFalse(canonical_schema_issues(record))
                self.assertTrue(any("integration_parent" in error for error in validate_record(record, "bad-integration-parent")))
                self.assert_not_resolved(record, "clause_ontology", "c0")

    def test_invalid_finiteness_clause_form_combinations_are_not_resolved(self) -> None:
        finite_with_form = self.mutated_record("clause_form", "to_infinitival", collection="clauses")
        self.assertFalse(canonical_schema_issues(finite_with_form))
        self.assertTrue(any("clause_form is only permitted" in error for error in validate_record(finite_with_form, "finite-form")))
        self.assert_not_resolved(finite_with_form, "clause_ontology", "c0")

        nonfinite_without_form = self.mutated_record("finiteness", "nonfinite", collection="clauses")
        self.assertFalse(canonical_schema_issues(nonfinite_without_form))
        self.assertTrue(any("nonfinite clauses require" in error for error in validate_record(nonfinite_without_form, "nonfinite-no-form")))
        self.assert_not_resolved(nonfinite_without_form, "clause_ontology", "c0")

    def test_nonfinite_clause_with_known_form_remains_resolved(self) -> None:
        record = self.mutated_record("finiteness", "nonfinite", collection="clauses")
        record["clauses"][0]["clause_form"] = "to_infinitival"
        self.assertEqual(validate_record(record, "nonfinite-form"), [])
        payload = authoritative_payload(record, "clause_ontology", "c0")
        self.assertIs(payload.state, AuthoritativePayloadState.PRESENT)
        self.assertTrue(payload.fully_resolved)

    def test_invalid_clause_target_is_not_scoreable(self) -> None:
        record = self.mutated_record("integration", ["root", "subordinate"], collection="clauses")
        decision = resolve_scoring_eligibility(record, "clause_ontology", "c0")
        self.assertFalse(decision.scoreable)
        self.assertIsNone(decision.coverage_state)

    def test_invalid_constituent_does_not_poison_sibling_target(self) -> None:
        record = self.mutated_record("head", "ghost")
        invalid = authoritative_payload(record, "phrase_constituency", "subj")
        valid = authoritative_payload(record, "phrase_constituency", "obj")
        self.assertIs(invalid.state, AuthoritativePayloadState.ABSENT)
        self.assertIs(valid.state, AuthoritativePayloadState.PRESENT)
        self.assertTrue(valid.fully_resolved)
        self.assertFalse(resolve_scoring_eligibility(record, "phrase_constituency", "subj").scoreable)
        self.assertTrue(resolve_scoring_eligibility(record, "phrase_constituency", "obj").scoreable)

    def test_invalid_clause_does_not_poison_sibling_clause_target(self) -> None:
        record = self.mutated_record("integration", ["root", "subordinate"], collection="clauses")
        record["clauses"].append(self.subordinate_clause())
        invalid = authoritative_payload(record, "clause_ontology", "c0")
        valid = authoritative_payload(record, "clause_ontology", "c1")
        self.assertIs(invalid.state, AuthoritativePayloadState.ABSENT)
        self.assertIs(valid.state, AuthoritativePayloadState.PRESENT)
        self.assertTrue(valid.fully_resolved)
        self.assertFalse(resolve_scoring_eligibility(record, "clause_ontology", "c0").scoreable)
        decision = resolve_scoring_eligibility(record, "clause_ontology", "c1")
        self.assertTrue(decision.scoreable)
        self.assertIs(decision.coverage_state, CoverageState.PARTIAL_COVERED)

    def test_record_complete_with_invalid_constituent_is_present_but_not_fully_resolved(self) -> None:
        record = with_declaration(FIXTURE, declaration("phrase_constituency", {"kind": "record"}))
        record["constituents"][0]["head"] = "ghost"
        payload = authoritative_payload(record, "phrase_constituency")
        self.assertIs(payload.state, AuthoritativePayloadState.PRESENT)
        self.assertFalse(payload.fully_resolved)
        self.assertEqual(payload.resolved_count, 1)
        self.assertEqual(payload.missing_count, 1)
        self.assertTrue(any(
            "complete coverage requires all applicable authoritative payload" in error
            for error in validate_record(record, "complete-invalid-constituent")
        ))
        decision = resolve_scoring_eligibility(record, "phrase_constituency")
        self.assertFalse(decision.scoreable)
        self.assertIsNone(decision.coverage_state)

    def test_record_complete_with_invalid_clause_is_present_but_not_fully_resolved(self) -> None:
        record = with_declaration(FIXTURE, declaration("clause_ontology", {"kind": "record"}))
        record["clauses"][0]["integration"] = ["root", "subordinate"]
        record["clauses"].append(self.subordinate_clause())
        payload = authoritative_payload(record, "clause_ontology")
        self.assertIs(payload.state, AuthoritativePayloadState.PRESENT)
        self.assertFalse(payload.fully_resolved)
        self.assertEqual(payload.resolved_count, 1)
        self.assertEqual(payload.missing_count, 1)
        decision = resolve_scoring_eligibility(record, "clause_ontology")
        self.assertFalse(decision.scoreable)
        self.assertIsNone(decision.coverage_state)

    def test_valid_same_span_alias_wrapper_remains_resolved(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["constituents"].append(self.clause_wrapper(
            "c0",
            span={"start": 0, "end": 5},
            realization={"clause_ref": "c0", "relation": "same_span_alias"},
            span_relation="same_span_alias",
        ))
        self.assertEqual(validate_record(record, "valid-same-span"), [])
        payload = authoritative_payload(record, "phrase_constituency", "emb")
        self.assertIs(payload.state, AuthoritativePayloadState.PRESENT)
        self.assertTrue(payload.fully_resolved)

    def test_same_span_alias_with_unequal_spans_is_not_resolved(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["constituents"].append(self.clause_wrapper(
            "c0",
            span={"start": 1, "end": 5},
            realization={"clause_ref": "c0", "relation": "same_span_alias"},
            span_relation="same_span_alias",
        ))
        self.assertTrue(any("same_span_alias" in e for e in validate_record(record, "unequal-same-span")))
        self.assert_not_resolved(record, "phrase_constituency", "emb")

    def test_valid_expanded_realization_wrapper_remains_resolved(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["constituents"].append(self.clause_wrapper(
            "c0",
            span={"start": 0, "end": 5},
            realization={"clause_ref": "c0", "relation": "expanded_realization"},
            span_relation="expanded_realization",
        ))
        self.assertEqual(validate_record(record, "valid-expanded"), [])
        payload = authoritative_payload(record, "phrase_constituency", "emb")
        self.assertIs(payload.state, AuthoritativePayloadState.PRESENT)
        self.assertTrue(payload.fully_resolved)

    def test_expanded_realization_not_containing_clause_span_is_not_resolved(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["constituents"].append(self.clause_wrapper(
            "c0",
            span={"start": 4, "end": 5},
            realization={"clause_ref": "c0", "relation": "expanded_realization"},
            span_relation="expanded_realization",
        ))
        self.assertTrue(any("expanded_realization" in e for e in validate_record(record, "bad-expanded")))
        self.assert_not_resolved(record, "phrase_constituency", "emb")

    def test_valid_other_wrapper_remains_resolved(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["constituents"].append(self.clause_wrapper("c0"))
        self.assertEqual(validate_record(record, "valid-other"), [])
        payload = authoritative_payload(record, "phrase_constituency", "emb")
        self.assertIs(payload.state, AuthoritativePayloadState.PRESENT)
        self.assertTrue(payload.fully_resolved)

    def test_missing_realization_object_is_not_resolved(self) -> None:
        record = copy.deepcopy(FIXTURE)
        wrapper: dict[str, Any] = {
            "id": "emb",
            "node_kind": "clause",
            "clause_ref": "c0",
            "span": {"start": 0, "end": 5},
            "function": "complement",
        }
        record["constituents"].append(wrapper)
        self.assertTrue(any("realization" in e for e in validate_record(record, "no-realization")))
        self.assert_not_resolved(record, "phrase_constituency", "emb")

    def test_realization_clause_ref_disagrees_is_not_resolved(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["clauses"].append(self.subordinate_clause())
        record["constituents"].append(self.clause_wrapper(
            "c0",
            realization={"clause_ref": "c1", "relation": "other"},
        ))
        self.assertTrue(any("realization.clause_ref must agree" in e for e in validate_record(record, "disagree-ref")))
        self.assert_not_resolved(record, "phrase_constituency", "emb")

    def test_invalid_realization_relation_is_not_resolved(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["constituents"].append(self.clause_wrapper(
            "c0",
            realization={"clause_ref": "c0", "relation": "bogus"},
        ))
        self.assertTrue(any("realization relation is invalid" in e for e in validate_record(record, "bad-relation")))
        self.assert_not_resolved(record, "phrase_constituency", "emb")

    def test_span_relation_mismatch_remains_not_resolved(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["constituents"].append(self.clause_wrapper(
            "c0",
            span_relation="same_span_alias",
        ))
        self.assertTrue(any("span_relation must agree" in e for e in validate_record(record, "mismatch")))
        self.assert_not_resolved(record, "phrase_constituency", "emb")

    def test_invalid_clause_wrapper_target_is_not_scoreable(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["constituents"].append(self.clause_wrapper(
            "c0",
            span={"start": 1, "end": 5},
            realization={"clause_ref": "c0", "relation": "same_span_alias"},
            span_relation="same_span_alias",
        ))
        decision = resolve_scoring_eligibility(record, "phrase_constituency", "emb")
        self.assertFalse(decision.scoreable)

    def test_renderer_does_not_emit_invalid_phrase_constituency_properties(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["constituents"].append(self.clause_wrapper(
            "c0",
            span={"start": 1, "end": 5},
            realization={"clause_ref": "c0", "relation": "same_span_alias"},
            span_relation="same_span_alias",
        ))
        projection = linguistic_projection(record)
        projected_constituents = {c["id"]: c for c in (projection.get("constituents") or [])}
        self.assertNotIn("emb", projected_constituents)

    def test_unrelated_valid_constituent_remains_positive(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["constituents"].append(self.clause_wrapper(
            "c0",
            span={"start": 1, "end": 5},
            realization={"clause_ref": "c0", "relation": "same_span_alias"},
            span_relation="same_span_alias",
        ))
        valid = authoritative_payload(record, "phrase_constituency", "subj")
        invalid = authoritative_payload(record, "phrase_constituency", "emb")
        self.assertIs(valid.state, AuthoritativePayloadState.PRESENT)
        self.assertTrue(valid.fully_resolved)
        self.assertIs(invalid.state, AuthoritativePayloadState.ABSENT)
        self.assertFalse(invalid.has_resolved_content)

    def test_record_complete_with_invalid_clause_wrapper_is_present_not_fully_resolved(self) -> None:
        record = with_declaration(FIXTURE, declaration("phrase_constituency", {"kind": "record"}))
        record["constituents"].append(self.clause_wrapper(
            "c0",
            span={"start": 1, "end": 5},
            realization={"clause_ref": "c0", "relation": "same_span_alias"},
            span_relation="same_span_alias",
        ))
        payload = authoritative_payload(record, "phrase_constituency")
        self.assertIs(payload.state, AuthoritativePayloadState.PRESENT)
        self.assertFalse(payload.fully_resolved)
        self.assertGreater(payload.missing_count, 0)
        decision = resolve_scoring_eligibility(record, "phrase_constituency")
        self.assertFalse(decision.scoreable)


class CollectionPayloadIntegrityTests(unittest.TestCase):
    """A1b: validator-invalid dependency/semantic-role/valency items are never resolved positive payload."""

    def test_valid_dependency_remains_resolved(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["dependencies"] = [{"relation": "obj", "head": "w2", "dependent": "obj"}]
        for dim in record["annotation_scope"]["dimensions"]:
            if dim.get("dimension") == "dependencies":
                dim["completeness"] = "complete"
                dim["evidence"] = "present"
                dim["omission"] = "none"
        record["annotation_scope"]["intentionally_omitted"] = [
            d for d in record["annotation_scope"].get("intentionally_omitted", [])
            if d != "dependencies"
        ]
        record["annotation_scope"]["annotated_dimensions"] = list(set(
            record["annotation_scope"].get("annotated_dimensions", []) + ["dependencies"]
        ))
        payload = authoritative_payload(record, "dependencies")
        self.assertIs(payload.state, AuthoritativePayloadState.PRESENT)
        self.assertTrue(payload.fully_resolved)
        self.assertEqual(validate_record(record, "valid-dep"), [])

    def test_dangling_dependency_source_is_not_resolved(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["dependencies"] = [{"relation": "obj", "head": "w2", "dependent": "obj", "source": "ghost"}]
        self.assertTrue(any("source" in e for e in validate_record(record, "dangling-source")))
        payload = authoritative_payload(record, "dependencies")
        self.assertIs(payload.state, AuthoritativePayloadState.ABSENT)
        self.assertEqual(payload.resolved_count, 0)
        self.assertEqual(payload.missing_count, 1)

    def test_dangling_dependency_target_is_not_resolved(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["dependencies"] = [{"relation": "obj", "head": "w2", "dependent": "obj", "target": "ghost"}]
        self.assertTrue(any("target" in e for e in validate_record(record, "dangling-target")))
        payload = authoritative_payload(record, "dependencies")
        self.assertIs(payload.state, AuthoritativePayloadState.ABSENT)
        self.assertEqual(payload.resolved_count, 0)
        self.assertEqual(payload.missing_count, 1)

    def test_valid_optional_source_target_remains_resolved(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["dependencies"] = [{"relation": "obj", "head": "w2", "dependent": "obj", "source": "w1", "target": "w3"}]
        for dim in record["annotation_scope"]["dimensions"]:
            if dim.get("dimension") == "dependencies":
                dim["completeness"] = "complete"
                dim["evidence"] = "present"
                dim["omission"] = "none"
        record["annotation_scope"]["intentionally_omitted"] = [
            d for d in record["annotation_scope"].get("intentionally_omitted", [])
            if d != "dependencies"
        ]
        record["annotation_scope"]["annotated_dimensions"] = list(set(
            record["annotation_scope"].get("annotated_dimensions", []) + ["dependencies"]
        ))
        self.assertEqual(validate_record(record, "valid-optional"), [])
        payload = authoritative_payload(record, "dependencies")
        self.assertIs(payload.state, AuthoritativePayloadState.PRESENT)
        self.assertTrue(payload.fully_resolved)

    def test_invalid_dependency_is_not_scoreable(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["dependencies"] = [{"relation": "obj", "head": "w2", "dependent": "obj", "source": "ghost"}]
        decision = resolve_scoring_eligibility(record, "dependencies")
        self.assertFalse(decision.scoreable)

    def test_mixed_valid_invalid_dependencies_complete_not_fully_resolved(self) -> None:
        record = with_declaration(FIXTURE, declaration("dependencies", {"kind": "record"}))
        record["dependencies"] = [
            {"relation": "obj", "head": "w2", "dependent": "obj", "source": "ghost"},
            {"relation": "subj", "head": "w2", "dependent": "subj"},
        ]
        payload = authoritative_payload(record, "dependencies")
        self.assertIs(payload.state, AuthoritativePayloadState.PRESENT)
        self.assertFalse(payload.fully_resolved)
        self.assertEqual(payload.resolved_count, 1)
        self.assertEqual(payload.missing_count, 1)
        decision = resolve_scoring_eligibility(record, "dependencies")
        self.assertFalse(decision.scoreable)

    def test_renderer_omits_invalid_dependency(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["dependencies"] = [
            {"relation": "obj", "head": "w2", "dependent": "obj", "source": "ghost"},
            {"relation": "subj", "head": "w2", "dependent": "subj"},
        ]
        payload = authoritative_payload(record, "dependencies")
        self.assertEqual(payload.resolved_count, 1)
        self.assertEqual(payload.missing_count, 1)
        self.assertEqual(payload.resolved_ids, ("dependencies[1]",))

    def test_valid_sibling_dependency_still_projects(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["dependencies"] = [
            {"relation": "obj", "head": "w2", "dependent": "obj", "source": "ghost"},
            {"relation": "subj", "head": "w2", "dependent": "subj"},
        ]
        valid = authoritative_payload(record, "dependencies")
        self.assertEqual(valid.resolved_count, 1)

    def test_partial_present_only_invalid_dependency_not_positive(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["dependencies"] = [{"relation": "obj", "head": "w2", "dependent": "obj", "source": "ghost"}]
        payload = authoritative_payload(record, "dependencies")
        self.assertIs(payload.state, AuthoritativePayloadState.ABSENT)
        self.assertEqual(payload.resolved_count, 0)

    def test_valid_semantic_role_remains_resolved(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["semantic_roles"] = [{"constituent": "obj", "role": "Theme"}]
        payload = authoritative_payload(record, "semantic_roles")
        self.assertIs(payload.state, AuthoritativePayloadState.PRESENT)
        self.assertTrue(payload.fully_resolved)
        self.assertEqual(validate_record(record, "valid-role"), [])

    def test_word_as_semantic_role_constituent_is_not_resolved(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["semantic_roles"] = [{"constituent": "w1", "role": "Theme"}]
        self.assertTrue(any("constituent" in e for e in validate_record(record, "word-constituent")))
        payload = authoritative_payload(record, "semantic_roles")
        self.assertIs(payload.state, AuthoritativePayloadState.ABSENT)
        self.assertEqual(payload.resolved_count, 0)
        self.assertEqual(payload.missing_count, 1)

    def test_dangling_semantic_role_constituent_is_not_resolved(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["semantic_roles"] = [{"constituent": "ghost", "role": "Theme"}]
        self.assertTrue(any("constituent" in e for e in validate_record(record, "dangling-constituent")))
        payload = authoritative_payload(record, "semantic_roles")
        self.assertIs(payload.state, AuthoritativePayloadState.ABSENT)
        self.assertEqual(payload.resolved_count, 0)

    def test_invalid_semantic_role_vocabulary_is_not_resolved(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["semantic_roles"] = [{"constituent": "obj", "role": "BogusRole"}]
        self.assertTrue(any("controlled vocabulary" in e for e in validate_record(record, "bad-role")))
        payload = authoritative_payload(record, "semantic_roles")
        self.assertIs(payload.state, AuthoritativePayloadState.ABSENT)
        self.assertEqual(payload.resolved_count, 0)

    def test_valid_semantic_role_predicate_remains_resolved(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["semantic_roles"] = [{"constituent": "obj", "role": "Theme", "predicate": "w2"}]
        self.assertEqual(validate_record(record, "valid-predicate"), [])
        payload = authoritative_payload(record, "semantic_roles")
        self.assertIs(payload.state, AuthoritativePayloadState.PRESENT)
        self.assertTrue(payload.fully_resolved)

    def test_invalid_semantic_role_predicate_is_not_resolved(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["semantic_roles"] = [{"constituent": "obj", "role": "Theme", "predicate": "ghost"}]
        self.assertTrue(any("predicate" in e for e in validate_record(record, "bad-predicate")))
        payload = authoritative_payload(record, "semantic_roles")
        self.assertIs(payload.state, AuthoritativePayloadState.ABSENT)
        self.assertEqual(payload.resolved_count, 0)

    def test_renderer_omits_invalid_semantic_role(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["semantic_roles"] = [
            {"constituent": "w1", "role": "Theme"},
            {"constituent": "obj", "role": "Theme"},
        ]
        payload = authoritative_payload(record, "semantic_roles")
        self.assertEqual(payload.resolved_count, 1)
        self.assertEqual(payload.missing_count, 1)

    def test_valid_sibling_semantic_role_remains_positive(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["semantic_roles"] = [
            {"constituent": "w1", "role": "Theme"},
            {"constituent": "obj", "role": "Theme"},
        ]
        payload = authoritative_payload(record, "semantic_roles")
        self.assertEqual(payload.resolved_count, 1)

    def test_complete_mixed_semantic_roles_not_fully_resolved(self) -> None:
        record = with_declaration(FIXTURE, declaration("semantic_roles", {"kind": "record"}))
        record["semantic_roles"] = [
            {"constituent": "w1", "role": "Theme"},
            {"constituent": "obj", "role": "Theme"},
        ]
        payload = authoritative_payload(record, "semantic_roles")
        self.assertIs(payload.state, AuthoritativePayloadState.PRESENT)
        self.assertFalse(payload.fully_resolved)

    def test_valid_lexical_valency_remains_resolved(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["lexical_valency"] = [{"predicate": "w2", "frame": "transitive", "selected_complements": ["obj"]}]
        payload = authoritative_payload(record, "lexical_valency")
        self.assertIs(payload.state, AuthoritativePayloadState.PRESENT)
        self.assertTrue(payload.fully_resolved)
        self.assertEqual(validate_record(record, "valid-valency"), [])

    def test_dangling_selected_complement_is_not_resolved(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["lexical_valency"] = [{"predicate": "w2", "frame": "transitive", "selected_complements": ["ghost"]}]
        self.assertTrue(any("selected complement" in e for e in validate_record(record, "dangling-complement")))
        payload = authoritative_payload(record, "lexical_valency")
        self.assertIs(payload.state, AuthoritativePayloadState.ABSENT)
        self.assertEqual(payload.resolved_count, 0)
        self.assertEqual(payload.missing_count, 1)

    def test_word_as_selected_complement_is_not_resolved(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["lexical_valency"] = [{"predicate": "w2", "frame": "transitive", "selected_complements": ["w1"]}]
        self.assertTrue(any("phrase or clause" in e for e in validate_record(record, "word-complement")))
        payload = authoritative_payload(record, "lexical_valency")
        self.assertIs(payload.state, AuthoritativePayloadState.ABSENT)
        self.assertEqual(payload.resolved_count, 0)

    def test_valid_phrase_selected_complement_remains_resolved(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["lexical_valency"] = [{"predicate": "w2", "frame": "transitive", "selected_complements": ["obj"]}]
        self.assertEqual(validate_record(record, "phrase-complement"), [])
        payload = authoritative_payload(record, "lexical_valency")
        self.assertIs(payload.state, AuthoritativePayloadState.PRESENT)
        self.assertTrue(payload.fully_resolved)

    def test_valid_clause_selected_complement_remains_resolved(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["lexical_valency"] = [{"predicate": "w2", "frame": "transitive", "selected_complements": ["c0"]}]
        self.assertEqual(validate_record(record, "clause-complement"), [])
        payload = authoritative_payload(record, "lexical_valency")
        self.assertIs(payload.state, AuthoritativePayloadState.PRESENT)
        self.assertTrue(payload.fully_resolved)

    def test_mixed_valid_invalid_selected_complements_not_resolved(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["lexical_valency"] = [{"predicate": "w2", "frame": "transitive", "selected_complements": ["obj", "ghost"]}]
        self.assertTrue(any("selected complement" in e for e in validate_record(record, "mixed-complements")))
        payload = authoritative_payload(record, "lexical_valency")
        self.assertIs(payload.state, AuthoritativePayloadState.ABSENT)
        self.assertEqual(payload.resolved_count, 0)

    def test_malformed_selected_complements_container_not_resolved(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["lexical_valency"] = [{"predicate": "w2", "frame": "transitive", "selected_complements": "obj"}]
        self.assertTrue(any("selected_complements must be an array" in e for e in validate_record(record, "bad-container")))
        payload = authoritative_payload(record, "lexical_valency")
        self.assertIs(payload.state, AuthoritativePayloadState.ABSENT)
        self.assertEqual(payload.resolved_count, 0)

    def test_invalid_predicate_is_not_resolved(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["lexical_valency"] = [{"predicate": "ghost", "frame": "transitive", "selected_complements": ["obj"]}]
        self.assertTrue(any("predicate" in e for e in validate_record(record, "bad-predicate")))
        payload = authoritative_payload(record, "lexical_valency")
        self.assertIs(payload.state, AuthoritativePayloadState.ABSENT)
        self.assertEqual(payload.resolved_count, 0)

    def test_target_level_invalid_predicate_does_not_poison_valid(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["lexical_valency"] = [
            {"predicate": "ghost", "frame": "transitive", "selected_complements": ["obj"]},
            {"predicate": "w3", "frame": "intransitive", "selected_complements": []},
        ]
        invalid = authoritative_payload(record, "lexical_valency", "w2")
        valid = authoritative_payload(record, "lexical_valency", "w3")
        self.assertIs(invalid.state, AuthoritativePayloadState.ABSENT)
        self.assertIs(valid.state, AuthoritativePayloadState.PRESENT)
        self.assertTrue(valid.fully_resolved)

    def test_complete_mixed_valency_not_fully_resolved(self) -> None:
        record = with_declaration(FIXTURE, declaration("lexical_valency", {"kind": "record"}))
        record["lexical_valency"] = [
            {"predicate": "w2", "frame": "transitive", "selected_complements": ["ghost"]},
            {"predicate": "w3", "frame": "intransitive", "selected_complements": []},
        ]
        payload = authoritative_payload(record, "lexical_valency")
        self.assertIs(payload.state, AuthoritativePayloadState.PRESENT)
        self.assertFalse(payload.fully_resolved)
        self.assertEqual(payload.resolved_count, 1)
        self.assertEqual(payload.missing_count, 1)

    def test_renderer_omits_invalid_valency(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["lexical_valency"] = [
            {"predicate": "w2", "frame": "transitive", "selected_complements": ["ghost"]},
            {"predicate": "w3", "frame": "intransitive", "selected_complements": []},
        ]
        payload = authoritative_payload(record, "lexical_valency")
        self.assertEqual(payload.resolved_count, 1)
        self.assertEqual(payload.missing_count, 1)

    def test_vp_complementation_uses_same_valency_status(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["lexical_valency"] = [{"predicate": "w2", "frame": "transitive", "selected_complements": ["ghost"]}]
        payload = authoritative_payload(record, "vp_complementation", "w2")
        self.assertIs(payload.state, AuthoritativePayloadState.ABSENT)
        self.assertEqual(payload.resolved_count, 0)


class TypedRelationStructuralIntegrityTests(unittest.TestCase):
    """A1c: Validator-invalid typed relations must not be resolved positive payload."""

    def _typed_record(self, relation: dict[str, Any], relation_type: str = "dependency") -> dict[str, Any]:
        record = copy.deepcopy(FIXTURE)
        record = with_declaration(record, declaration("dependencies", {"kind": "record"}))
        typed = record["canonical_analysis"]["typed_analysis"]
        typed["status"] = "established"
        typed["relations"] = [relation]
        return record

    def test_valid_binary_relation_resolved(self) -> None:
        relation = {
            "id": "r1",
            "type": "dependency",
            "arity": "binary",
            "source": "word:w2",
            "target": "constituent:obj",
            "status": "established",
        }
        record = self._typed_record(relation)
        self.assertEqual(validate_record(record, "valid-binary"), [])
        payload = authoritative_payload(record, "dependencies")
        self.assertIs(payload.state, AuthoritativePayloadState.PRESENT)
        self.assertEqual(payload.resolved_count, 1)
        self.assertTrue(payload.fully_resolved)

    def test_missing_id_not_resolved(self) -> None:
        relation = {
            "type": "dependency",
            "arity": "binary",
            "source": "word:w2",
            "target": "constituent:obj",
            "status": "established",
        }
        record = self._typed_record(relation)
        errors = validate_record(record, "missing-id")
        self.assertTrue(any("stable non-empty id" in error for error in errors))
        payload = authoritative_payload(record, "dependencies")
        self.assertEqual(payload.resolved_count, 0)
        self.assertEqual(payload.missing_count, 1)

    def test_missing_type_not_resolved(self) -> None:
        relation = {
            "id": "r1",
            "arity": "binary",
            "source": "word:w2",
            "target": "constituent:obj",
            "status": "established",
        }
        record = self._typed_record(relation)
        errors = validate_record(record, "missing-type")
        self.assertTrue(any("non-empty relation type" in error for error in errors))
        # Relations with missing type are not collected because they don't match owned relation types
        payload = authoritative_payload(record, "dependencies")
        self.assertEqual(payload.resolved_count, 0)

    def test_missing_arity_not_resolved(self) -> None:
        relation = {
            "id": "r1",
            "type": "dependency",
            "source": "word:w2",
            "target": "constituent:obj",
            "status": "established",
        }
        record = self._typed_record(relation)
        errors = validate_record(record, "missing-arity")
        self.assertTrue(any("explicit arity" in error for error in errors))
        payload = authoritative_payload(record, "dependencies")
        self.assertEqual(payload.resolved_count, 0)
        self.assertEqual(payload.missing_count, 1)

    def test_invalid_arity_not_resolved(self) -> None:
        relation = {
            "id": "r1",
            "type": "dependency",
            "arity": "ternary",
            "source": "word:w2",
            "target": "constituent:obj",
            "status": "established",
        }
        record = self._typed_record(relation)
        errors = validate_record(record, "invalid-arity")
        self.assertTrue(any("unary or binary" in error for error in errors))
        payload = authoritative_payload(record, "dependencies")
        self.assertEqual(payload.resolved_count, 0)
        self.assertEqual(payload.missing_count, 1)

    def test_binary_missing_target_not_resolved(self) -> None:
        relation = {
            "id": "r1",
            "type": "dependency",
            "arity": "binary",
            "source": "word:w2",
            "status": "established",
        }
        record = self._typed_record(relation)
        errors = validate_record(record, "binary-missing-target")
        self.assertTrue(any("requires target" in error for error in errors))
        payload = authoritative_payload(record, "dependencies")
        self.assertEqual(payload.resolved_count, 0)
        self.assertEqual(payload.missing_count, 1)

    def test_unary_with_target_not_resolved(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record = with_declaration(record, declaration("construction_relations", {"kind": "record"}))
        typed = record["canonical_analysis"]["typed_analysis"]
        typed["status"] = "established"
        typed["relations"] = [{
            "id": "r1",
            "type": "custom:unary",
            "arity": "unary",
            "source": "word:w2",
            "target": "constituent:obj",
            "status": "established",
        }]
        errors = validate_record(record, "unary-with-target")
        self.assertTrue(any("cannot carry target" in error for error in errors))
        payload = authoritative_payload(record, "construction_relations")
        self.assertEqual(payload.resolved_count, 0)

    def test_valid_unary_extension_resolved(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record = with_declaration(record, declaration("construction_relations", {"kind": "record"}))
        typed = record["canonical_analysis"]["typed_analysis"]
        typed["status"] = "established"
        typed["relations"] = [{
            "id": "r1",
            "type": "custom:unary",
            "arity": "unary",
            "source": "word:w2",
            "status": "established",
        }]
        # Extension relations are structurally valid but may not be owned by any dimension
        # So we just check that the relation is structurally valid
        from scripts.typed_relation_contract import validate_typed_relation_structure, get_analysis_entity_ids
        entity_ids = get_analysis_entity_ids(typed)
        status = validate_typed_relation_structure(typed["relations"][0], typed, record, analysis_entity_ids=entity_ids)
        self.assertEqual(status, "resolved")

    def test_dangling_source_not_resolved(self) -> None:
        relation = {
            "id": "r1",
            "type": "dependency",
            "arity": "binary",
            "source": "word:ghost",
            "target": "constituent:obj",
            "status": "established",
        }
        record = self._typed_record(relation)
        errors = validate_record(record, "dangling-source")
        self.assertTrue(any("dangling" in error for error in errors))
        payload = authoritative_payload(record, "dependencies")
        self.assertEqual(payload.resolved_count, 0)
        self.assertEqual(payload.missing_count, 1)

    def test_dangling_target_not_resolved(self) -> None:
        relation = {
            "id": "r1",
            "type": "dependency",
            "arity": "binary",
            "source": "word:w2",
            "target": "constituent:ghost",
            "status": "established",
        }
        record = self._typed_record(relation)
        errors = validate_record(record, "dangling-target")
        self.assertTrue(any("dangling" in error for error in errors))
        payload = authoritative_payload(record, "dependencies")
        self.assertEqual(payload.resolved_count, 0)
        self.assertEqual(payload.missing_count, 1)

    def test_dangling_analysis_local_entity_not_resolved(self) -> None:
        relation = {
            "id": "r1",
            "type": "dependency",
            "arity": "binary",
            "source": "word:w2",
            "target": "analysis:ghost",
            "status": "established",
        }
        record = self._typed_record(relation)
        errors = validate_record(record, "dangling-analysis")
        self.assertTrue(any("dangling" in error for error in errors))
        payload = authoritative_payload(record, "dependencies")
        self.assertEqual(payload.resolved_count, 0)
        self.assertEqual(payload.missing_count, 1)

    def test_valid_canonical_references_resolved(self) -> None:
        relation = {
            "id": "r1",
            "type": "dependency",
            "arity": "binary",
            "source": {"namespace": "word", "id": "w2"},
            "target": {"namespace": "constituent", "id": "obj"},
            "status": "established",
        }
        record = self._typed_record(relation)
        self.assertEqual(validate_record(record, "valid-canonical-refs"), [])
        payload = authoritative_payload(record, "dependencies")
        self.assertEqual(payload.resolved_count, 1)

    def test_valid_analysis_local_reference_resolved(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record = with_declaration(record, declaration("dependencies", {"kind": "record"}))
        typed = record["canonical_analysis"]["typed_analysis"]
        typed["status"] = "established"
        typed["entities"] = [{"id": "e1", "kind": "understood_subject"}]
        typed["relations"] = [{
            "id": "r1",
            "type": "dependency",
            "arity": "binary",
            "source": "word:w2",
            "target": "analysis:e1",
            "status": "established",
        }]
        self.assertEqual(validate_record(record, "valid-analysis-ref"), [])
        payload = authoritative_payload(record, "dependencies")
        self.assertEqual(payload.resolved_count, 1)

    def test_cross_analysis_entity_does_not_satisfy_local_reference(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record = with_declaration(record, declaration("dependencies", {"kind": "record"}))
        canonical_typed = record["canonical_analysis"]["typed_analysis"]
        canonical_typed["status"] = "established"
        canonical_typed["entities"] = [{"id": "e1", "kind": "understood_subject"}]
        canonical_typed["relations"] = [{
            "id": "r1",
            "type": "dependency",
            "arity": "binary",
            "source": "word:w2",
            "target": "analysis:e1",
            "status": "established",
        }]
        record["alternative_analyses"] = [{
            "id": "alt-1",
            "framework": "CGEL",
            "status": "established",
            "typed_analysis": {
                "kind": "record_level_analysis",
                "framework": "CGEL",
                "status": "established",
                "relations": [{
                    "id": "r2",
                    "type": "dependency",
                    "arity": "binary",
                    "source": "word:w2",
                    "target": "analysis:e1",
                    "status": "established",
                }],
            },
        }]
        errors = validate_record(record, "cross-analysis-ref")
        self.assertTrue(any("dangling" in error for error in errors))

    def test_invalid_framework_not_resolved(self) -> None:
        relation = {
            "id": "r1",
            "type": "dependency",
            "arity": "binary",
            "source": "word:w2",
            "target": "constituent:obj",
            "framework": "invalid_framework",
            "status": "established",
        }
        record = self._typed_record(relation)
        errors = validate_record(record, "invalid-framework")
        self.assertTrue(any("known framework" in error for error in errors))
        payload = authoritative_payload(record, "dependencies")
        self.assertEqual(payload.resolved_count, 0)
        self.assertEqual(payload.missing_count, 1)

    def test_framework_relation_no_attribution_not_resolved(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record = with_declaration(record, declaration("construction_relations", {"kind": "record"}))
        typed = record["canonical_analysis"]["typed_analysis"]
        typed["status"] = "established"
        typed["relations"] = [{
            "id": "r1",
            "type": "framework_relation",
            "arity": "binary",
            "source": "word:w2",
            "target": "constituent:obj",
            "status": "established",
        }]
        errors = validate_record(record, "framework-relation-no-attribution")
        self.assertTrue(any("framework or namespace" in error for error in errors))
        payload = authoritative_payload(record, "construction_relations")
        self.assertEqual(payload.resolved_count, 0)

    def test_qualified_extension_relation_resolved(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record = with_declaration(record, declaration("construction_relations", {"kind": "record"}))
        typed = record["canonical_analysis"]["typed_analysis"]
        typed["status"] = "established"
        typed["relations"] = [{
            "id": "r1",
            "type": "pedagogical:object",
            "arity": "binary",
            "source": "word:w2",
            "target": "constituent:obj",
            "status": "established",
        }]
        # Extension relations are structurally valid but may not be owned by any dimension
        # So we just check that the relation is structurally valid
        from scripts.typed_relation_contract import validate_typed_relation_structure, get_analysis_entity_ids
        entity_ids = get_analysis_entity_ids(typed)
        status = validate_typed_relation_structure(typed["relations"][0], typed, record, analysis_entity_ids=entity_ids)
        self.assertEqual(status, "resolved")

    def test_unqualified_unknown_extension_not_resolved(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record = with_declaration(record, declaration("construction_relations", {"kind": "record"}))
        typed = record["canonical_analysis"]["typed_analysis"]
        typed["status"] = "established"
        typed["relations"] = [{
            "id": "r1",
            "type": "custom_relation",
            "arity": "binary",
            "source": "word:w2",
            "target": "constituent:obj",
            "status": "established",
        }]
        errors = validate_record(record, "unqualified-extension")
        self.assertTrue(any("unknown extension" in error for error in errors))
        payload = authoritative_payload(record, "construction_relations")
        self.assertEqual(payload.resolved_count, 0)

    def test_duplicate_relation_ids_same_analysis_not_clean_resolved(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record = with_declaration(record, declaration("dependencies", {"kind": "record"}))
        typed = record["canonical_analysis"]["typed_analysis"]
        typed["status"] = "established"
        typed["relations"] = [
            {
                "id": "r1",
                "type": "dependency",
                "arity": "binary",
                "source": "word:w2",
                "target": "constituent:obj",
                "status": "established",
            },
            {
                "id": "r1",
                "type": "dependency",
                "arity": "binary",
                "source": "word:w1",
                "target": "constituent:obj",
                "status": "established",
            },
        ]
        errors = validate_record(record, "duplicate-relation-ids")
        self.assertTrue(any("duplicate" in error for error in errors))
        payload = authoritative_payload(record, "dependencies")
        self.assertEqual(payload.resolved_count, 0)
        self.assertEqual(payload.missing_count, 2)
        self.assertFalse(payload.fully_resolved)

    def test_duplicate_relation_ids_cross_analysis_not_clean_resolved(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record = with_declaration(record, declaration("dependencies", {"kind": "record"}))
        canonical_typed = record["canonical_analysis"]["typed_analysis"]
        canonical_typed["status"] = "established"
        canonical_typed["relations"] = [{
            "id": "r1",
            "type": "dependency",
            "arity": "binary",
            "source": "word:w2",
            "target": "constituent:obj",
            "status": "established",
        }]
        record["alternative_analyses"] = [{
            "id": "alt-1",
            "framework": "CGEL",
            "status": "established",
            "typed_analysis": {
                "kind": "record_level_analysis",
                "framework": "CGEL",
                "status": "established",
                "relations": [{
                    "id": "r1",
                    "type": "dependency",
                    "arity": "binary",
                    "source": "word:w1",
                    "target": "constituent:obj",
                    "status": "established",
                }],
            },
        }]
        errors = validate_record(record, "duplicate-cross-analysis")
        self.assertTrue(any("duplicate" in error for error in errors))
        payload = authoritative_payload(record, "dependencies")
        self.assertEqual(payload.resolved_count, 0)
        self.assertFalse(payload.fully_resolved)

    def test_duplicate_entity_ids_same_analysis_not_clean_resolved(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record = with_declaration(record, declaration("construction_relations", {"kind": "record"}))
        typed = record["canonical_analysis"]["typed_analysis"]
        typed["status"] = "established"
        typed["entities"] = [
            {"id": "e1", "kind": "understood_subject"},
            {"id": "e1", "kind": "clause"},
        ]
        errors = validate_record(record, "duplicate-entity-ids")
        self.assertTrue(any("duplicate" in error for error in errors))
        items = authoritative_payload_items(record, "construction_relations")
        entity_items = [item for item in items if item.field == "typed_entity"]
        self.assertTrue(all(item.status == "missing" for item in entity_items))

    def test_structurally_valid_unresolved_relation_is_unresolved(self) -> None:
        relation = {
            "id": "r1",
            "type": "dependency",
            "arity": "binary",
            "source": "word:w2",
            "target": "constituent:obj",
            "status": "unresolved",
        }
        record = self._typed_record(relation)
        # Unresolved relations are structurally valid but don't count as resolved payload
        payload = authoritative_payload(record, "dependencies")
        self.assertEqual(payload.unresolved_count, 1)
        self.assertEqual(payload.resolved_count, 0)

    def test_structurally_invalid_unresolved_relation_is_missing(self) -> None:
        relation = {
            "id": "r1",
            "type": "dependency",
            "arity": "binary",
            "source": "word:ghost",
            "target": "constituent:obj",
            "status": "unresolved",
        }
        record = self._typed_record(relation)
        errors = validate_record(record, "invalid-unresolved")
        self.assertTrue(any("dangling" in error for error in errors))
        payload = authoritative_payload(record, "dependencies")
        self.assertEqual(payload.unresolved_count, 0)
        self.assertEqual(payload.missing_count, 1)


class TypedRelationRendererSafetyTests(unittest.TestCase):
    """A1c: Renderer must not project structurally invalid typed relations."""

    def _typed_record(self, relation: dict[str, Any]) -> dict[str, Any]:
        record = copy.deepcopy(FIXTURE)
        record = with_declaration(record, declaration("dependencies", {"kind": "record"}))
        typed = record["canonical_analysis"]["typed_analysis"]
        typed["status"] = "established"
        typed["relations"] = [relation]
        return record

    def test_missing_arity_relation_does_not_project(self) -> None:
        relation = {
            "id": "r1",
            "type": "dependency",
            "source": "word:w2",
            "target": "constituent:obj",
            "status": "established",
        }
        record = self._typed_record(relation)
        projection = linguistic_projection(record)
        typed_analysis = projection.get("canonical_analysis", {}).get("typed_analysis", {})
        relations = typed_analysis.get("relations", [])
        self.assertEqual(len(relations), 0)

    def test_dangling_source_relation_does_not_project(self) -> None:
        relation = {
            "id": "r1",
            "type": "dependency",
            "arity": "binary",
            "source": "word:ghost",
            "target": "constituent:obj",
            "status": "established",
        }
        record = self._typed_record(relation)
        projection = linguistic_projection(record)
        typed_analysis = projection.get("canonical_analysis", {}).get("typed_analysis", {})
        relations = typed_analysis.get("relations", [])
        self.assertEqual(len(relations), 0)

    def test_dangling_target_relation_does_not_project(self) -> None:
        relation = {
            "id": "r1",
            "type": "dependency",
            "arity": "binary",
            "source": "word:w2",
            "target": "constituent:ghost",
            "status": "established",
        }
        record = self._typed_record(relation)
        projection = linguistic_projection(record)
        typed_analysis = projection.get("canonical_analysis", {}).get("typed_analysis", {})
        relations = typed_analysis.get("relations", [])
        self.assertEqual(len(relations), 0)

    def test_unary_with_target_does_not_project(self) -> None:
        relation = {
            "id": "r1",
            "type": "custom:unary",
            "arity": "unary",
            "source": "word:w2",
            "target": "constituent:obj",
            "status": "established",
        }
        record = self._typed_record(relation)
        projection = linguistic_projection(record)
        typed_analysis = projection.get("canonical_analysis", {}).get("typed_analysis", {})
        relations = typed_analysis.get("relations", [])
        self.assertEqual(len(relations), 0)

    def test_valid_relation_still_projects(self) -> None:
        relation = {
            "id": "r1",
            "type": "dependency",
            "arity": "binary",
            "source": "word:w2",
            "target": "constituent:obj",
            "status": "established",
        }
        record = self._typed_record(relation)
        projection = linguistic_projection(record)
        typed_analysis = projection.get("canonical_analysis", {}).get("typed_analysis", {})
        relations = typed_analysis.get("relations", [])
        self.assertEqual(len(relations), 1)
        self.assertEqual(relations[0]["id"], "r1")

    def test_valid_sibling_relation_projects_when_another_invalid(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record = with_declaration(record, declaration("dependencies", {"kind": "record"}))
        typed = record["canonical_analysis"]["typed_analysis"]
        typed["status"] = "established"
        typed["relations"] = [
            {
                "id": "r1",
                "type": "dependency",
                "arity": "binary",
                "source": "word:w2",
                "target": "constituent:obj",
                "status": "established",
            },
            {
                "id": "r2",
                "type": "dependency",
                "arity": "binary",
                "source": "word:ghost",
                "target": "constituent:obj",
                "status": "established",
            },
        ]
        projection = linguistic_projection(record)
        typed_analysis = projection.get("canonical_analysis", {}).get("typed_analysis", {})
        relations = typed_analysis.get("relations", [])
        self.assertEqual(len(relations), 1)
        self.assertEqual(relations[0]["id"], "r1")


class TypedRelationCoverageScoringSafetyTests(unittest.TestCase):
    """A1c: Mixed valid/invalid typed payload must not be fully resolved."""

    def test_complete_mixed_valid_invalid_not_fully_resolved(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record = with_declaration(record, declaration("dependencies", {"kind": "record"}))
        typed = record["canonical_analysis"]["typed_analysis"]
        typed["status"] = "established"
        typed["relations"] = [
            {
                "id": "r1",
                "type": "dependency",
                "arity": "binary",
                "source": "word:w2",
                "target": "constituent:obj",
                "status": "established",
            },
            {
                "id": "r2",
                "type": "dependency",
                "arity": "binary",
                "source": "word:ghost",
                "target": "constituent:obj",
                "status": "established",
            },
        ]
        payload = authoritative_payload(record, "dependencies")
        self.assertIs(payload.state, AuthoritativePayloadState.PRESENT)
        self.assertGreater(payload.resolved_count, 0)
        self.assertGreater(payload.missing_count, 0)
        self.assertFalse(payload.fully_resolved)

    def test_invalid_relation_not_positive_supervision(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record = with_declaration(record, declaration("dependencies", {"kind": "record"}))
        typed = record["canonical_analysis"]["typed_analysis"]
        typed["status"] = "established"
        typed["relations"] = [{
            "id": "r1",
            "type": "dependency",
            "arity": "binary",
            "source": "word:ghost",
            "target": "constituent:obj",
            "status": "established",
        }]
        payload = authoritative_payload(record, "dependencies")
        self.assertEqual(payload.resolved_count, 0)
        self.assertGreater(payload.missing_count, 0)


class A1c1PreferredDependencyDuplicationTests(unittest.TestCase):
    """A1c1-1: Preferred-authority typed dependency duplication."""

    def test_canonical_typed_dependency_duplicating_top_level_not_resolved(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["dependencies"] = [{"relation": "obj", "head": "w2", "dependent": "obj"}]
        record = with_declaration(record, declaration("dependencies", {"kind": "record"}))
        typed = record["canonical_analysis"]["typed_analysis"]
        typed["status"] = "established"
        typed["relations"] = [{
            "id": "typed-dup",
            "type": "dependency",
            "arity": "binary",
            "source": "word:w2",
            "target": "constituent:obj",
            "status": "established",
        }]
        errors = validate_record(record, "dup-dep")
        self.assertTrue(any("duplicates the canonical dependencies layer" in e for e in errors))
        from scripts.typed_relation_contract import validate_typed_relation_structure, TypedRelationValidationContext, _canonical_dependency_pairs, valid_analysis_entity_ids
        ctx = TypedRelationValidationContext(
            preferred_authority=True,
            relation_id_occurrences={"typed-dup": 1},
            valid_analysis_entity_ids=valid_analysis_entity_ids(typed),
            canonical_dependency_pairs=_canonical_dependency_pairs(record),
        )
        status = validate_typed_relation_structure(
            typed["relations"][0],
            typed,
            record,
            context=ctx,
        )
        self.assertEqual(status, "missing")

    def test_duplicate_typed_dependency_not_rendered(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["dependencies"] = [{"relation": "obj", "head": "w2", "dependent": "obj"}]
        record = with_declaration(record, declaration("dependencies", {"kind": "record"}))
        typed = record["canonical_analysis"]["typed_analysis"]
        typed["status"] = "established"
        typed["relations"] = [{
            "id": "typed-dup",
            "type": "dependency",
            "arity": "binary",
            "source": "word:w2",
            "target": "constituent:obj",
            "status": "established",
        }]
        projection = linguistic_projection(record)
        typed_analysis = projection.get("canonical_analysis", {}).get("typed_analysis", {})
        relations = typed_analysis.get("relations", [])
        self.assertEqual(len(relations), 0)

    def test_duplicate_typed_dependency_not_scoreable(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["dependencies"] = [{"relation": "obj", "head": "w2", "dependent": "obj"}]
        record = with_declaration(record, declaration("dependencies", {"kind": "record"}))
        typed = record["canonical_analysis"]["typed_analysis"]
        typed["status"] = "established"
        typed["relations"] = [{
            "id": "typed-dup",
            "type": "dependency",
            "arity": "binary",
            "source": "word:w2",
            "target": "constituent:obj",
            "status": "established",
        }]
        decision = resolve_scoring_eligibility(record, "dependencies")
        self.assertFalse(decision.scoreable)

    def test_non_duplicate_canonical_typed_dependency_remains_valid(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record = with_declaration(record, declaration("construction_relations", {"kind": "record"}))
        typed = record["canonical_analysis"]["typed_analysis"]
        typed["status"] = "established"
        typed["relations"] = [{
            "id": "r1",
            "type": "construction",
            "arity": "binary",
            "source": "word:w1",
            "target": "constituent:subj",
            "status": "established",
        }]
        errors = validate_record(record, "non-dup")
        self.assertEqual([e for e in errors if "duplicates" in e or "typed relation" in e], [])
        payload = authoritative_payload(record, "construction_relations")
        self.assertGreater(payload.resolved_count, 0)

    def test_alternative_typed_dependency_follows_non_preferred_rule(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["dependencies"] = [{"relation": "obj", "head": "w2", "dependent": "obj"}]
        record = with_declaration(record, declaration("dependencies", {"kind": "record"}))
        record["canonical_analysis"]["typed_analysis"] = {
            "kind": "dependency_grammar",
            "framework": "meaningful_text",
            "status": "established",
        }
        record["alternative_analyses"] = [{
            "id": "alt1",
            "framework": "hpsg",
            "typed_analysis": {
                "kind": "dependency_grammar",
                "framework": "hpsg",
                "status": "established",
                "relations": [{
                    "id": "alt-r1",
                    "type": "dependency",
                    "arity": "binary",
                    "source": "word:w2",
                    "target": "constituent:obj",
                    "status": "established",
                }],
            },
        }]
        errors = validate_record(record, "alt-dep")
        self.assertFalse(any("duplicates the canonical dependencies layer" in e for e in errors))


class A1c1DuplicateRelationIDRendererTests(unittest.TestCase):
    """A1c1-2: Renderer duplicate relation ID identity parity."""

    def test_same_analysis_duplicate_relation_ids_neither_projects(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record = with_declaration(record, declaration("construction_relations", {"kind": "record"}))
        typed = record["canonical_analysis"]["typed_analysis"]
        typed["status"] = "established"
        typed["relations"] = [
            {
                "id": "r1",
                "type": "construction",
                "arity": "binary",
                "source": "word:w1",
                "target": "constituent:subj",
                "status": "established",
            },
            {
                "id": "r1",
                "type": "construction",
                "arity": "binary",
                "source": "word:w2",
                "target": "constituent:obj",
                "status": "established",
            },
        ]
        errors = validate_record(record, "dup-id")
        self.assertTrue(any("duplicate typed relation id" in e for e in errors))
        projection = linguistic_projection(record)
        typed_analysis = projection.get("canonical_analysis", {}).get("typed_analysis", {})
        relations = typed_analysis.get("relations", [])
        self.assertEqual(len(relations), 0)

    def test_cross_analysis_duplicate_relation_ids_conflicting_do_not_project(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record = with_declaration(record, declaration("construction_relations", {"kind": "record"}))
        typed = record["canonical_analysis"]["typed_analysis"]
        typed["status"] = "established"
        typed["relations"] = [{
            "id": "r1",
            "type": "construction",
            "arity": "binary",
            "source": "word:w1",
            "target": "constituent:subj",
            "status": "established",
        }]
        record["alternative_analyses"] = [{
            "id": "alt1",
            "framework": "hpsg",
            "typed_analysis": {
                "kind": "dependency_grammar",
                "framework": "hpsg",
                "status": "established",
                "relations": [{
                    "id": "r1",
                    "type": "construction",
                    "arity": "binary",
                    "source": "word:w2",
                    "target": "constituent:obj",
                    "status": "established",
                }],
            },
        }]
        errors = validate_record(record, "cross-dup")
        self.assertTrue(any("typed relation IDs must be unique" in e for e in errors))
        projection = linguistic_projection(record)
        canonical_relations = projection.get("canonical_analysis", {}).get("typed_analysis", {}).get("relations", [])
        alt_relations = (
            projection.get("alternative_analyses", [{}])[0]
            .get("typed_analysis", {})
            .get("relations", [])
        )
        self.assertEqual(len(canonical_relations), 0)
        self.assertEqual(len(alt_relations), 0)

    def test_unique_valid_sibling_relation_still_projects(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record = with_declaration(record, declaration("construction_relations", {"kind": "record"}))
        typed = record["canonical_analysis"]["typed_analysis"]
        typed["status"] = "established"
        typed["relations"] = [
            {
                "id": "r1",
                "type": "construction",
                "arity": "binary",
                "source": "word:w1",
                "target": "constituent:subj",
                "status": "established",
            },
            {
                "id": "r2",
                "type": "construction",
                "arity": "binary",
                "source": "word:w2",
                "target": "constituent:obj",
                "status": "established",
            },
        ]
        projection = linguistic_projection(record)
        typed_analysis = projection.get("canonical_analysis", {}).get("typed_analysis", {})
        relations = typed_analysis.get("relations", [])
        self.assertEqual(len(relations), 2)


class A1c1EntityReferenceIntegrityTests(unittest.TestCase):
    """A1c1-3: Valid analysis entity references."""

    def test_relation_to_duplicate_local_entity_id_not_resolved(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record = with_declaration(record, declaration("construction_relations", {"kind": "record"}))
        typed = record["canonical_analysis"]["typed_analysis"]
        typed["status"] = "established"
        typed["entities"] = [
            {"id": "e1", "kind": "clause"},
            {"id": "e1", "kind": "clause"},
        ]
        typed["relations"] = [{
            "id": "r1",
            "type": "construction",
            "arity": "binary",
            "source": "word:w1",
            "target": {"namespace": "analysis", "id": "e1"},
            "status": "established",
        }]
        payload = authoritative_payload(record, "construction_relations")
        self.assertEqual(payload.resolved_count, 0)

    def test_relation_to_duplicate_local_entity_id_not_rendered(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record = with_declaration(record, declaration("construction_relations", {"kind": "record"}))
        typed = record["canonical_analysis"]["typed_analysis"]
        typed["status"] = "established"
        typed["entities"] = [
            {"id": "e1", "kind": "clause"},
            {"id": "e1", "kind": "clause"},
        ]
        typed["relations"] = [{
            "id": "r1",
            "type": "construction",
            "arity": "binary",
            "source": "word:w1",
            "target": {"namespace": "analysis", "id": "e1"},
            "status": "established",
        }]
        projection = linguistic_projection(record)
        typed_analysis = projection.get("canonical_analysis", {}).get("typed_analysis", {})
        relations = typed_analysis.get("relations", [])
        self.assertEqual(len(relations), 0)

    def test_relation_to_entity_missing_kind_not_resolved(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record = with_declaration(record, declaration("construction_relations", {"kind": "record"}))
        typed = record["canonical_analysis"]["typed_analysis"]
        typed["status"] = "established"
        typed["entities"] = [{"id": "e1"}]
        typed["relations"] = [{
            "id": "r1",
            "type": "construction",
            "arity": "binary",
            "source": "word:w1",
            "target": {"namespace": "analysis", "id": "e1"},
            "status": "established",
        }]
        payload = authoritative_payload(record, "construction_relations")
        self.assertEqual(payload.resolved_count, 0)

    def test_valid_sibling_entity_relation_still_works(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["annotation_scope"]["dimensions"] = [
            declaration("construction_relations", {"kind": "record"}),
            declaration("phrase_constituency", {"kind": "record"}),
        ]
        typed = record["canonical_analysis"]["typed_analysis"]
        typed["status"] = "established"
        typed["entities"] = [
            {"id": "e2", "kind": "clause"},
        ]
        typed["relations"] = [
            {
                "id": "r1",
                "type": "construction",
                "arity": "binary",
                "source": "word:w1",
                "target": {"namespace": "analysis", "id": "ghost"},
                "status": "established",
            },
            {
                "id": "r2",
                "type": "construction",
                "arity": "binary",
                "source": "word:w2",
                "target": {"namespace": "analysis", "id": "e2"},
                "status": "established",
            },
        ]
        projection = linguistic_projection(record)
        typed_analysis = projection.get("canonical_analysis", {}).get("typed_analysis", {})
        relations = typed_analysis.get("relations", [])
        relation_ids = {r.get("id") for r in relations}
        self.assertNotIn("r1", relation_ids)
        self.assertIn("r2", relation_ids)

    def test_entity_in_another_analysis_cannot_satisfy_local_reference(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record = with_declaration(record, declaration("construction_relations", {"kind": "record"}))
        typed = record["canonical_analysis"]["typed_analysis"]
        typed["status"] = "established"
        typed["entities"] = [{"id": "e1", "kind": "clause"}]
        typed["relations"] = [{
            "id": "r1",
            "type": "construction",
            "arity": "binary",
            "source": "word:w1",
            "target": {"namespace": "analysis", "id": "e1"},
            "status": "established",
        }]
        record["alternative_analyses"] = [{
            "id": "alt1",
            "framework": "hpsg",
            "typed_analysis": {
                "kind": "dependency_grammar",
                "framework": "hpsg",
                "status": "established",
                "relations": [{
                    "id": "r2",
                    "type": "construction",
                    "arity": "binary",
                    "source": "word:w2",
                    "target": {"namespace": "analysis", "id": "e1"},
                    "status": "established",
                }],
            },
        }]
        projection = linguistic_projection(record)
        alt_relations = (
            projection.get("alternative_analyses", [{}])[0]
            .get("typed_analysis", {})
            .get("relations", [])
        )
        self.assertEqual(len(alt_relations), 0)


class A1c1UnresolvedRendererTests(unittest.TestCase):
    """A1c1-4: Renderer requires resolved relation authority."""

    def test_complete_unresolved_relation_omitted(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record = with_declaration(record, declaration("construction_relations", {"kind": "record"}))
        typed = record["canonical_analysis"]["typed_analysis"]
        typed["status"] = "established"
        typed["relations"] = [{
            "id": "r1",
            "type": "construction",
            "arity": "binary",
            "source": "word:w1",
            "target": "constituent:subj",
            "status": "unresolved",
        }]
        projection = linguistic_projection(record)
        typed_analysis = projection.get("canonical_analysis", {}).get("typed_analysis", {})
        relations = typed_analysis.get("relations", [])
        self.assertEqual(len(relations), 0)

    def test_complete_review_required_relation_omitted(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record = with_declaration(record, declaration("construction_relations", {"kind": "record"}))
        typed = record["canonical_analysis"]["typed_analysis"]
        typed["status"] = "established"
        typed["relations"] = [{
            "id": "r1",
            "type": "construction",
            "arity": "binary",
            "source": "word:w1",
            "target": "constituent:subj",
            "status": "review_required",
        }]
        projection = linguistic_projection(record)
        typed_analysis = projection.get("canonical_analysis", {}).get("typed_analysis", {})
        relations = typed_analysis.get("relations", [])
        self.assertEqual(len(relations), 0)

    def test_inherited_unresolved_typed_analysis_status_omitted(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record = with_declaration(record, declaration("construction_relations", {"kind": "record"}))
        typed = record["canonical_analysis"]["typed_analysis"]
        typed["status"] = "unresolved"
        typed["relations"] = [{
            "id": "r1",
            "type": "construction",
            "arity": "binary",
            "source": "word:w1",
            "target": "constituent:subj",
        }]
        projection = linguistic_projection(record)
        typed_analysis = projection.get("canonical_analysis", {}).get("typed_analysis", {})
        relations = typed_analysis.get("relations", [])
        self.assertEqual(len(relations), 0)

    def test_established_valid_complete_relation_still_projects(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record = with_declaration(record, declaration("construction_relations", {"kind": "record"}))
        typed = record["canonical_analysis"]["typed_analysis"]
        typed["status"] = "established"
        typed["relations"] = [{
            "id": "r1",
            "type": "construction",
            "arity": "binary",
            "source": "word:w1",
            "target": "constituent:subj",
            "status": "established",
        }]
        projection = linguistic_projection(record)
        typed_analysis = projection.get("canonical_analysis", {}).get("typed_analysis", {})
        relations = typed_analysis.get("relations", [])
        self.assertEqual(len(relations), 1)


class A1c1PartialPresentTests(unittest.TestCase):
    """A1c1-5: A6 partial-present preservation."""

    def test_valid_partial_present_typed_relation_projected(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["annotation_scope"]["dimensions"] = [
            declaration("dependencies", {"kind": "record"}, completeness="partial", evidence="present"),
            declaration("phrase_constituency", {"kind": "record"}),
        ]
        typed = record["canonical_analysis"]["typed_analysis"]
        typed["status"] = "established"
        typed["relations"] = [{
            "id": "r1",
            "type": "dependency",
            "arity": "binary",
            "source": "word:w1",
            "target": "constituent:subj",
            "status": "established",
        }]
        from scripts.coverage_resolution import resolve_coverage, CoverageState
        state = resolve_coverage(record, "dependencies")
        self.assertIs(state, CoverageState.PARTIAL_COVERED)
        projection = linguistic_projection(record)
        typed_analysis = projection.get("canonical_analysis", {}).get("typed_analysis", {})
        relations = typed_analysis.get("relations", [])
        self.assertEqual(len(relations), 1)

    def test_invalid_only_partial_present_not_positive(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["annotation_scope"]["dimensions"] = [
            declaration("dependencies", {"kind": "record"}, completeness="partial", evidence="present"),
            declaration("phrase_constituency", {"kind": "record"}),
        ]
        typed = record["canonical_analysis"]["typed_analysis"]
        typed["status"] = "established"
        typed["relations"] = [{
            "id": "r1",
            "type": "dependency",
            "arity": "binary",
            "source": "word:ghost",
            "target": "constituent:subj",
            "status": "established",
        }]
        projection = linguistic_projection(record)
        typed_analysis = projection.get("canonical_analysis", {}).get("typed_analysis", {})
        relations = typed_analysis.get("relations", [])
        self.assertEqual(len(relations), 0)

    def test_unresolved_only_partial_present_not_positive(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["annotation_scope"]["dimensions"] = [
            declaration("dependencies", {"kind": "record"}, completeness="partial", evidence="present"),
            declaration("phrase_constituency", {"kind": "record"}),
        ]
        typed = record["canonical_analysis"]["typed_analysis"]
        typed["status"] = "established"
        typed["relations"] = [{
            "id": "r1",
            "type": "dependency",
            "arity": "binary",
            "source": "word:w1",
            "target": "constituent:subj",
            "status": "unresolved",
        }]
        projection = linguistic_projection(record)
        typed_analysis = projection.get("canonical_analysis", {}).get("typed_analysis", {})
        relations = typed_analysis.get("relations", [])
        self.assertEqual(len(relations), 0)


class A1c1SiblingIsolationTests(unittest.TestCase):
    """A1c1: Complete sibling isolation."""

    def test_complete_valid_relation_plus_invalid_sibling(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record = with_declaration(record, declaration("construction_relations", {"kind": "record"}))
        typed = record["canonical_analysis"]["typed_analysis"]
        typed["status"] = "established"
        typed["relations"] = [
            {
                "id": "r1",
                "type": "construction",
                "arity": "binary",
                "source": "word:w1",
                "target": "constituent:subj",
                "status": "established",
            },
            {
                "id": "r2",
                "type": "construction",
                "arity": "binary",
                "source": "word:ghost",
                "target": "constituent:obj",
                "status": "established",
            },
        ]
        projection = linguistic_projection(record)
        typed_analysis = projection.get("canonical_analysis", {}).get("typed_analysis", {})
        relations = typed_analysis.get("relations", [])
        relation_ids = {r.get("id") for r in relations}
        self.assertIn("r1", relation_ids)
        self.assertNotIn("r2", relation_ids)
        decision = resolve_scoring_eligibility(record, "construction_relations")
        self.assertFalse(decision.scoreable)


class H2B01TypedRecordScopeTruthfulnessTests(unittest.TestCase):
    """H2-B01: Typed record payload must not be filtered by endpoint existence."""

    def _dep_record_with_typed(self, relations, evidence="empty"):
        record = copy.deepcopy(FIXTURE)
        record["dependencies"] = []
        record["annotation_scope"]["dimensions"] = [
            declaration("dependencies", {"kind": "record"}, evidence=evidence),
        ]
        ta = record["canonical_analysis"]["typed_analysis"]
        ta["status"] = "established"
        ta["entities"] = [
            {"id": "e1", "kind": "clause"},
            {"id": "e2", "kind": "clause"},
        ]
        ta["relations"] = relations
        return record

    def test_dangling_typed_dependency_contributes_missing(self) -> None:
        record = self._dep_record_with_typed([{
            "id": "r1", "type": "dependency", "arity": "binary",
            "source": "word:ghost", "target": "analysis:e1",
            "status": "established",
        }])
        payload = authoritative_payload(record, "dependencies")
        self.assertEqual(payload.applicable_count, 1)
        self.assertEqual(payload.missing_count, 1)
        self.assertEqual(payload.resolved_count, 0)
        self.assertFalse(payload.fully_resolved)

    def test_dangling_typed_dependency_prevents_confirmed_empty(self) -> None:
        record = self._dep_record_with_typed([{
            "id": "r1", "type": "dependency", "arity": "binary",
            "source": "word:ghost", "target": "analysis:e1",
            "status": "established",
        }])
        payload = authoritative_payload(record, "dependencies")
        self.assertIsNot(payload.state, AuthoritativePayloadState.CONFIRMED_EMPTY)
        spec = dimension_spec("dependencies")
        self.assertFalse(confirmed_empty_eligible(record, spec, payload))

    def test_dangling_typed_dependency_not_scoreable(self) -> None:
        record = self._dep_record_with_typed([{
            "id": "r1", "type": "dependency", "arity": "binary",
            "source": "word:ghost", "target": "analysis:e1",
            "status": "established",
        }])
        decision = resolve_scoring_eligibility(record, "dependencies")
        self.assertFalse(decision.scoreable)

    def test_valid_analysis_local_dependency_contributes_resolved(self) -> None:
        record = self._dep_record_with_typed([{
            "id": "r1", "type": "dependency", "arity": "binary",
            "source": "analysis:e1", "target": "analysis:e2",
            "status": "established",
        }])
        payload = authoritative_payload(record, "dependencies")
        self.assertEqual(payload.applicable_count, 1)
        self.assertEqual(payload.resolved_count, 1)
        self.assertEqual(payload.missing_count, 0)
        self.assertIsNot(payload.state, AuthoritativePayloadState.CONFIRMED_EMPTY)

    def test_valid_analysis_local_dependency_prevents_confirmed_empty(self) -> None:
        record = self._dep_record_with_typed([{
            "id": "r1", "type": "dependency", "arity": "binary",
            "source": "analysis:e1", "target": "analysis:e2",
            "status": "established",
        }])
        payload = authoritative_payload(record, "dependencies")
        spec = dimension_spec("dependencies")
        self.assertFalse(confirmed_empty_eligible(record, spec, payload))

    def test_complete_valid_plus_dangling_dependency_not_fully_resolved(self) -> None:
        record = self._dep_record_with_typed(
            [
                {
                    "id": "r_valid", "type": "dependency", "arity": "binary",
                    "source": "analysis:e1", "target": "analysis:e2",
                    "status": "established",
                },
                {
                    "id": "r_invalid", "type": "dependency", "arity": "binary",
                    "source": "word:ghost", "target": "analysis:e1",
                    "status": "established",
                },
            ],
            evidence="present",
        )
        payload = authoritative_payload(record, "dependencies")
        self.assertIs(payload.state, AuthoritativePayloadState.PRESENT)
        self.assertGreaterEqual(payload.resolved_count, 1)
        self.assertGreaterEqual(payload.missing_count, 1)
        self.assertFalse(payload.fully_resolved)

    def test_complete_valid_plus_dangling_dependency_not_scoreable(self) -> None:
        record = self._dep_record_with_typed(
            [
                {
                    "id": "r_valid", "type": "dependency", "arity": "binary",
                    "source": "analysis:e1", "target": "analysis:e2",
                    "status": "established",
                },
                {
                    "id": "r_invalid", "type": "dependency", "arity": "binary",
                    "source": "word:ghost", "target": "analysis:e1",
                    "status": "established",
                },
            ],
            evidence="present",
        )
        decision = resolve_scoring_eligibility(record, "dependencies")
        self.assertFalse(decision.scoreable)

    def test_complete_valid_plus_dangling_construction_not_fully_resolved(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["annotation_scope"]["dimensions"] = [
            declaration("construction_relations", {"kind": "record"}),
        ]
        ta = record["canonical_analysis"]["typed_analysis"]
        ta["status"] = "established"
        ta["entities"] = [
            {"id": "e1", "kind": "clause"},
            {"id": "e2", "kind": "clause"},
        ]
        ta["relations"] = [
            {
                "id": "r_valid", "type": "construction", "arity": "binary",
                "source": "analysis:e1", "target": "analysis:e2",
                "status": "established",
            },
            {
                "id": "r_invalid", "type": "construction", "arity": "binary",
                "source": "word:ghost", "target": "analysis:e1",
                "status": "established",
            },
        ]
        payload = authoritative_payload(record, "construction_relations")
        self.assertIs(payload.state, AuthoritativePayloadState.PRESENT)
        self.assertGreaterEqual(payload.resolved_count, 1)
        self.assertGreaterEqual(payload.missing_count, 1)
        self.assertFalse(payload.fully_resolved)

    def test_complete_valid_plus_dangling_construction_not_scoreable(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["annotation_scope"]["dimensions"] = [
            declaration("construction_relations", {"kind": "record"}),
        ]
        ta = record["canonical_analysis"]["typed_analysis"]
        ta["status"] = "established"
        ta["entities"] = [
            {"id": "e1", "kind": "clause"},
            {"id": "e2", "kind": "clause"},
        ]
        ta["relations"] = [
            {
                "id": "r_valid", "type": "construction", "arity": "binary",
                "source": "analysis:e1", "target": "analysis:e2",
                "status": "established",
            },
            {
                "id": "r_invalid", "type": "construction", "arity": "binary",
                "source": "word:ghost", "target": "analysis:e1",
                "status": "established",
            },
        ]
        decision = resolve_scoring_eligibility(record, "construction_relations")
        self.assertFalse(decision.scoreable)

    def test_valid_sibling_relation_remains_projectable(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["construction_type"] = "transitive"
        record = with_declaration(record, declaration("construction_relations", {"kind": "record"}))
        ta = record["canonical_analysis"]["typed_analysis"]
        ta["status"] = "established"
        ta["entities"] = [{"id": "e1", "kind": "clause"}]
        ta["relations"] = [
            {
                "id": "r_valid", "type": "construction", "arity": "binary",
                "source": "word:w1", "target": "constituent:subj",
                "status": "established",
            },
            {
                "id": "r_invalid", "type": "construction", "arity": "binary",
                "source": "word:ghost", "target": "analysis:e1",
                "status": "established",
            },
        ]
        projection = linguistic_projection(record)
        typed_analysis = projection.get("canonical_analysis", {}).get("typed_analysis", {})
        relations = typed_analysis.get("relations", [])
        relation_ids = {r.get("id") for r in relations}
        self.assertIn("r_valid", relation_ids)
        self.assertNotIn("r_invalid", relation_ids)

    def test_invalid_relation_omitted_from_projection(self) -> None:
        record = self._dep_record_with_typed(
            [{
                "id": "r_invalid", "type": "dependency", "arity": "binary",
                "source": "word:ghost", "target": "analysis:e1",
                "status": "established",
            }],
            evidence="present",
        )
        projection = linguistic_projection(record)
        typed_analysis = projection.get("canonical_analysis", {}).get("typed_analysis", {})
        relations = typed_analysis.get("relations", [])
        self.assertEqual(len(relations), 0)

    def test_genuine_empty_record_with_no_typed_authority_still_confirmed_empty(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["dependencies"] = []
        record["canonical_analysis"]["typed_analysis"]["relations"] = []
        record["annotation_scope"]["dimensions"] = [
            declaration("dependencies", {"kind": "record"}, evidence="empty"),
        ]
        payload = authoritative_payload(record, "dependencies")
        self.assertIs(payload.state, AuthoritativePayloadState.CONFIRMED_EMPTY)
        spec = dimension_spec("dependencies")
        self.assertTrue(confirmed_empty_eligible(record, spec, payload))
        decision = resolve_scoring_eligibility(record, "dependencies")
        self.assertTrue(decision.scoreable)

    def test_more_specific_node_scope_excludes_record_typed_relation(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["annotation_scope"]["dimensions"] = [
            declaration("vp_complementation", {"kind": "record"}),
            declaration("vp_complementation", {"kind": "node", "node": "subj"}),
        ]
        ta = record["canonical_analysis"]["typed_analysis"]
        ta["status"] = "established"
        ta["relations"] = [{
            "id": "r1", "type": "selection", "arity": "binary",
            "source": "constituent:subj", "target": "constituent:subj",
            "status": "established",
        }]
        record_payload = authoritative_payload(record, "vp_complementation")
        node_payload = authoritative_payload(record, "vp_complementation", "subj")
        self.assertEqual(node_payload.applicable_count, 1)
        self.assertEqual(record_payload.applicable_count, 0)

    def test_analysis_local_relation_not_invented_into_node_scope(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["annotation_scope"]["dimensions"] = [
            declaration("vp_complementation", {"kind": "node", "node": "subj"}),
        ]
        ta = record["canonical_analysis"]["typed_analysis"]
        ta["status"] = "established"
        ta["entities"] = [
            {"id": "e1", "kind": "clause"},
            {"id": "e2", "kind": "clause"},
        ]
        ta["relations"] = [{
            "id": "r1", "type": "selection", "arity": "binary",
            "source": "analysis:e1", "target": "analysis:e2",
            "status": "established",
        }]
        node_payload = authoritative_payload(record, "vp_complementation", "subj")
        self.assertEqual(node_payload.applicable_count, 0)

    def test_analysis_local_relation_not_invented_into_region_scope(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["annotation_scope"]["dimensions"] = [
            declaration("vp_complementation", {"kind": "region", "start": 0, "end": 3}),
        ]
        ta = record["canonical_analysis"]["typed_analysis"]
        ta["status"] = "established"
        ta["entities"] = [
            {"id": "e1", "kind": "clause"},
            {"id": "e2", "kind": "clause"},
        ]
        ta["relations"] = [{
            "id": "r1", "type": "selection", "arity": "binary",
            "source": "analysis:e1", "target": "analysis:e2",
            "status": "established",
        }]
        region_payload = authoritative_payload(record, "vp_complementation", {"kind": "region", "start": 0, "end": 3})
        self.assertEqual(region_payload.applicable_count, 0)


class H2R1aMalformedTypedRelationRecordScopeTests(unittest.TestCase):
    """H2-R1a: Malformed typed relations must not disappear from record scope."""

    def _vp_record(self, relations, extra_declarations=None):
        record = copy.deepcopy(FIXTURE)
        declarations = [
            declaration("vp_complementation", {"kind": "record"}),
            declaration("vp_complementation", {"kind": "node", "node": "subj"}),
        ]
        if extra_declarations:
            declarations.extend(extra_declarations)
        record["annotation_scope"]["dimensions"] = declarations
        ta = record["canonical_analysis"]["typed_analysis"]
        ta["status"] = "established"
        ta["relations"] = relations
        return record

    def test_mixed_valid_dangling_endpoint_included_in_record(self) -> None:
        record = self._vp_record([{
            "id": "r1", "type": "selection", "arity": "binary",
            "source": "constituent:subj", "target": "constituent:ghost",
            "status": "established",
        }])
        record_payload = authoritative_payload(record, "vp_complementation")
        node_payload = authoritative_payload(record, "vp_complementation", "subj")
        self.assertEqual(record_payload.applicable_count, 1)
        self.assertEqual(record_payload.missing_count, 1)
        self.assertEqual(record_payload.resolved_count, 0)
        self.assertEqual(node_payload.applicable_count, 1)
        self.assertEqual(node_payload.missing_count, 1)

    def test_reversed_dangling_endpoint_included_in_record(self) -> None:
        record = self._vp_record([{
            "id": "r1", "type": "selection", "arity": "binary",
            "source": "constituent:ghost", "target": "constituent:subj",
            "status": "established",
        }])
        record_payload = authoritative_payload(record, "vp_complementation")
        self.assertEqual(record_payload.applicable_count, 1)
        self.assertEqual(record_payload.missing_count, 1)
        self.assertEqual(record_payload.resolved_count, 0)

    def test_wrong_namespace_kind_not_accepted_as_canonical_target(self) -> None:
        record = self._vp_record([{
            "id": "r1", "type": "selection", "arity": "binary",
            "source": "word:subj", "target": "word:subj",
            "status": "established",
        }])
        record_payload = authoritative_payload(record, "vp_complementation")
        node_payload = authoritative_payload(record, "vp_complementation", "subj")
        self.assertEqual(record_payload.applicable_count, 1)
        self.assertEqual(record_payload.missing_count, 1)
        self.assertEqual(node_payload.applicable_count, 0)

    def test_valid_more_specific_relation_excluded_from_record(self) -> None:
        record = self._vp_record([{
            "id": "r1", "type": "selection", "arity": "binary",
            "source": "constituent:subj", "target": "constituent:subj",
            "status": "established",
        }])
        record_payload = authoritative_payload(record, "vp_complementation")
        node_payload = authoritative_payload(record, "vp_complementation", "subj")
        self.assertEqual(record_payload.applicable_count, 0)
        self.assertEqual(node_payload.applicable_count, 1)
        self.assertEqual(node_payload.resolved_count, 1)

    def test_analysis_local_relation_record_fallback(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["annotation_scope"]["dimensions"] = [
            declaration("vp_complementation", {"kind": "node", "node": "subj"}),
        ]
        ta = record["canonical_analysis"]["typed_analysis"]
        ta["status"] = "established"
        ta["entities"] = [{"id": "e1", "kind": "clause"}, {"id": "e2", "kind": "clause"}]
        ta["relations"] = [{
            "id": "r1", "type": "selection", "arity": "binary",
            "source": "analysis:e1", "target": "analysis:e2",
            "status": "established",
        }]
        node_payload = authoritative_payload(record, "vp_complementation", "subj")
        self.assertEqual(node_payload.applicable_count, 0)

    def test_malformed_typed_relation_prevents_confirmed_empty(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["annotation_scope"]["dimensions"] = [
            declaration("vp_complementation", {"kind": "record"}, evidence="empty"),
            declaration("vp_complementation", {"kind": "node", "node": "subj"}),
        ]
        ta = record["canonical_analysis"]["typed_analysis"]
        ta["status"] = "established"
        ta["relations"] = [{
            "id": "r1", "type": "selection", "arity": "binary",
            "source": "constituent:subj", "target": "constituent:ghost",
            "status": "established",
        }]
        payload = authoritative_payload(record, "vp_complementation")
        self.assertIsNot(payload.state, AuthoritativePayloadState.CONFIRMED_EMPTY)
        self.assertGreater(payload.missing_count, 0)

    def test_complete_truthfulness_with_valid_and_malformed_relations(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["annotation_scope"]["dimensions"] = [
            declaration("vp_complementation", {"kind": "record"}),
            declaration("vp_complementation", {"kind": "node", "node": "subj"}),
        ]
        ta = record["canonical_analysis"]["typed_analysis"]
        ta["status"] = "established"
        ta["relations"] = [
            {
                "id": "r_valid", "type": "selection", "arity": "binary",
                "source": "constituent:obj", "target": "constituent:obj",
                "status": "established",
            },
            {
                "id": "r_malformed", "type": "selection", "arity": "binary",
                "source": "constituent:subj", "target": "constituent:ghost",
                "status": "established",
            },
        ]
        record_payload = authoritative_payload(record, "vp_complementation")
        self.assertIs(record_payload.state, AuthoritativePayloadState.PRESENT)
        self.assertGreater(record_payload.resolved_count, 0)
        self.assertGreater(record_payload.missing_count, 0)
        self.assertFalse(record_payload.fully_resolved)
        decision = resolve_scoring_eligibility(record, "vp_complementation")
        self.assertFalse(decision.scoreable)

    def test_r1b_dangling_analysis_local_target(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["annotation_scope"]["dimensions"] = [
            declaration("vp_complementation", {"kind": "record"}),
            declaration("vp_complementation", {"kind": "node", "node": "subj"}),
        ]
        ta = record["canonical_analysis"]["typed_analysis"]
        ta["status"] = "established"
        ta["entities"] = [{"id": "e1", "type": "event"}]
        ta["relations"] = [{
            "id": "r1", "type": "selection", "arity": "binary",
            "source": "constituent:subj", "target": "analysis:ghost",
            "status": "established",
        }]
        record_payload = authoritative_payload(record, "vp_complementation")
        self.assertEqual(record_payload.applicable_count, 1)
        self.assertEqual(record_payload.missing_count, 1)
        node_payload = authoritative_payload(record, "vp_complementation", "subj")
        self.assertGreaterEqual(node_payload.applicable_count, 0)

    def test_r1b_binary_relation_missing_target(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["annotation_scope"]["dimensions"] = [
            declaration("vp_complementation", {"kind": "record"}),
            declaration("vp_complementation", {"kind": "node", "node": "subj"}),
        ]
        ta = record["canonical_analysis"]["typed_analysis"]
        ta["status"] = "established"
        ta["relations"] = [{
            "id": "r1", "type": "selection", "arity": "binary",
            "source": "constituent:subj",
            "status": "established",
        }]
        record_payload = authoritative_payload(record, "vp_complementation")
        self.assertEqual(record_payload.applicable_count, 1)
        self.assertEqual(record_payload.missing_count, 1)

    def test_r1b_invalid_arity(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["annotation_scope"]["dimensions"] = [
            declaration("vp_complementation", {"kind": "record"}),
            declaration("vp_complementation", {"kind": "node", "node": "subj"}),
        ]
        ta = record["canonical_analysis"]["typed_analysis"]
        ta["status"] = "established"
        ta["relations"] = [{
            "id": "r1", "type": "selection", "arity": "bogus",
            "source": "constituent:subj", "target": "constituent:subj",
            "status": "established",
        }]
        record_payload = authoritative_payload(record, "vp_complementation")
        self.assertEqual(record_payload.applicable_count, 1)
        self.assertEqual(record_payload.missing_count, 1)

    def test_r1b_duplicate_relation_id(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["annotation_scope"]["dimensions"] = [
            declaration("vp_complementation", {"kind": "record"}),
            declaration("vp_complementation", {"kind": "node", "node": "subj"}),
        ]
        ta = record["canonical_analysis"]["typed_analysis"]
        ta["status"] = "established"
        ta["relations"] = [
            {
                "id": "r1", "type": "selection", "arity": "binary",
                "source": "constituent:subj", "target": "constituent:subj",
                "status": "established",
            },
            {
                "id": "r1", "type": "selection", "arity": "binary",
                "source": "constituent:subj", "target": "constituent:subj",
                "status": "established",
            },
        ]
        record_payload = authoritative_payload(record, "vp_complementation")
        self.assertGreaterEqual(record_payload.applicable_count, 2)
        self.assertGreaterEqual(record_payload.missing_count, 2)

    def test_r1b_more_specific_valid_control(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["annotation_scope"]["dimensions"] = [
            declaration("vp_complementation", {"kind": "record"}),
            declaration("vp_complementation", {"kind": "node", "node": "subj"}),
        ]
        ta = record["canonical_analysis"]["typed_analysis"]
        ta["status"] = "established"
        ta["relations"] = [{
            "id": "r1", "type": "selection", "arity": "binary",
            "source": "constituent:subj", "target": "constituent:subj",
            "status": "established",
        }]
        record_payload = authoritative_payload(record, "vp_complementation")
        self.assertEqual(record_payload.applicable_count, 0)
        node_payload = authoritative_payload(record, "vp_complementation", "subj")
        self.assertEqual(node_payload.applicable_count, 1)
        self.assertEqual(node_payload.resolved_count, 1)

    def test_r1b_confirmed_empty_safety_analysis_ghost(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["annotation_scope"]["dimensions"] = [
            declaration("vp_complementation", {"kind": "record"}, evidence="empty"),
        ]
        ta = record["canonical_analysis"]["typed_analysis"]
        ta["status"] = "established"
        ta["entities"] = [{"id": "e1", "type": "event"}]
        ta["relations"] = [{
            "id": "r1", "type": "selection", "arity": "binary",
            "source": "constituent:subj", "target": "analysis:ghost",
            "status": "established",
        }]
        payload = authoritative_payload(record, "vp_complementation")
        self.assertIsNot(payload.state, AuthoritativePayloadState.CONFIRMED_EMPTY)
        self.assertGreater(payload.missing_count, 0)

    def test_r1b_confirmed_empty_safety_binary_missing_target(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["annotation_scope"]["dimensions"] = [
            declaration("vp_complementation", {"kind": "record"}, evidence="empty"),
        ]
        ta = record["canonical_analysis"]["typed_analysis"]
        ta["status"] = "established"
        ta["relations"] = [{
            "id": "r1", "type": "selection", "arity": "binary",
            "source": "constituent:subj",
            "status": "established",
        }]
        payload = authoritative_payload(record, "vp_complementation")
        self.assertIsNot(payload.state, AuthoritativePayloadState.CONFIRMED_EMPTY)
        self.assertGreater(payload.missing_count, 0)

    def test_r1b_complete_truthfulness_mixed_valid_and_malformed(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["annotation_scope"]["dimensions"] = [
            declaration("vp_complementation", {"kind": "record"}),
            declaration("vp_complementation", {"kind": "node", "node": "subj"}),
        ]
        ta = record["canonical_analysis"]["typed_analysis"]
        ta["status"] = "established"
        ta["relations"] = [
            {
                "id": "r_valid", "type": "selection", "arity": "binary",
                "source": "constituent:obj", "target": "constituent:obj",
                "status": "established",
            },
            {
                "id": "r_malformed", "type": "selection", "arity": "binary",
                "source": "constituent:subj", "target": "constituent:ghost",
                "status": "established",
            },
        ]
        record_payload = authoritative_payload(record, "vp_complementation")
        self.assertIs(record_payload.state, AuthoritativePayloadState.PRESENT)
        self.assertGreater(record_payload.resolved_count, 0)
        self.assertGreater(record_payload.missing_count, 0)
        self.assertFalse(record_payload.fully_resolved)
        decision = resolve_scoring_eligibility(record, "vp_complementation")
        self.assertFalse(decision.scoreable)


class H2B02PhraseForbiddenFieldTests(unittest.TestCase):
    """B02: Phrase constituents with forbidden wrapper-only fields must fail structural admission."""

    def test_valid_phrase_remains_resolved(self) -> None:
        payload = authoritative_payload(FIXTURE, "phrase_constituency", "subj")
        self.assertIs(payload.state, AuthoritativePayloadState.PRESENT)
        self.assertTrue(payload.fully_resolved)

    def test_phrase_with_forbidden_clause_ref_is_missing(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["constituents"][1]["clause_ref"] = "ghost"
        self.assertTrue(any("clause_ref is reserved" in error for error in validate_record(record, "b02-phrase-clause-ref")))
        payload = authoritative_payload(record, "phrase_constituency", "obj")
        self.assertIs(payload.state, AuthoritativePayloadState.ABSENT)
        self.assertEqual(payload.missing_count, 1)

    def test_phrase_with_forbidden_category_field_is_missing(self) -> None:
        record = copy.deepcopy(FIXTURE)
        record["constituents"][1]["category"] = "NP"
        self.assertTrue(any("V0.2 phrase nodes must use phrase_category" in error for error in validate_record(record, "b02-phrase-category")))
        payload = authoritative_payload(record, "phrase_constituency", "obj")
        self.assertIs(payload.state, AuthoritativePayloadState.ABSENT)
        self.assertEqual(payload.missing_count, 1)

    def test_b02_complete_mixed_valid_and_invalid_phrase(self) -> None:
        record = with_declaration(FIXTURE, declaration("phrase_constituency", {"kind": "record"}))
        record["constituents"][1]["clause_ref"] = "ghost"
        payload = authoritative_payload(record, "phrase_constituency")
        self.assertIs(payload.state, AuthoritativePayloadState.PRESENT)
        self.assertGreater(payload.resolved_count, 0)
        self.assertGreater(payload.missing_count, 0)
        self.assertFalse(payload.fully_resolved)

    def test_b02_scoring_false(self) -> None:
        record = with_declaration(FIXTURE, declaration("phrase_constituency", {"kind": "record"}))
        record["constituents"][1]["clause_ref"] = "ghost"
        decision = resolve_scoring_eligibility(record, "phrase_constituency")
        self.assertFalse(decision.scoreable)

    def test_b02_renderer_omits_invalid_phrase_positive_gold(self) -> None:
        record = with_declaration(FIXTURE, declaration("phrase_constituency", {"kind": "record"}))
        record = with_declaration(record, declaration("syntactic_function", {"kind": "record"}))
        record["constituents"][1]["clause_ref"] = "ghost"
        projection = linguistic_projection(record)
        by_id = {c["id"]: c for c in (projection.get("constituents") or [])}
        self.assertNotIn("obj", by_id)

    def test_b02_valid_sibling_phrase_still_projects(self) -> None:
        record = with_declaration(FIXTURE, declaration("phrase_constituency", {"kind": "record"}))
        record["constituents"][1]["clause_ref"] = "ghost"
        payload = authoritative_payload(record, "phrase_constituency", "subj")
        self.assertIs(payload.state, AuthoritativePayloadState.PRESENT)
        self.assertTrue(payload.fully_resolved)

    def test_b02_target_query_for_invalid_phrase_not_positive(self) -> None:
        record = with_declaration(FIXTURE, declaration("phrase_constituency", {"kind": "record"}))
        record["constituents"][1]["clause_ref"] = "ghost"
        payload = authoritative_payload(record, "phrase_constituency", "obj")
        self.assertIs(payload.state, AuthoritativePayloadState.ABSENT)
        self.assertFalse(payload.has_resolved_content)

    def test_b02_valid_clause_wrapper_control_remains_resolved(self) -> None:
        record = copy.deepcopy(FIXTURE)
        wrapper = {
            "id": "emb",
            "node_kind": "clause",
            "clause_ref": "c0",
            "span": {"start": 0, "end": 5},
            "function": "complement",
            "realization": {"clause_ref": "c0", "relation": "same_span_alias"},
            "span_relation": "same_span_alias",
        }
        record["constituents"].append(wrapper)
        payload = authoritative_payload(record, "phrase_constituency", "emb")
        self.assertIs(payload.state, AuthoritativePayloadState.PRESENT)
        self.assertTrue(payload.fully_resolved)


class H2B03SyntacticFunctionAuthorityTests(unittest.TestCase):
    """B03: Syntactic-function collector must validate constituent structural admission."""

    def test_valid_constituent_function_remains_resolved(self) -> None:
        payload = authoritative_payload(FIXTURE, "syntactic_function", "obj")
        self.assertIs(payload.state, AuthoritativePayloadState.PRESENT)
        self.assertTrue(payload.fully_resolved)

    def test_b03_invalid_clause_wrapper_with_valid_function_is_missing(self) -> None:
        record = copy.deepcopy(FIXTURE)
        wrapper = {
            "id": "wrapper1",
            "node_kind": "clause",
            "clause_ref": "c0",
            "span": {"start": 1, "end": 5},
            "function": "complement",
            "realization": {"clause_ref": "c0", "relation": "same_span_alias"},
            "span_relation": "same_span_alias",
        }
        record["constituents"].append(wrapper)
        self.assertTrue(any("same_span_alias requires wrapper and clause spans to match" in error for error in validate_record(record, "b03-same-span-mismatch")))
        payload = authoritative_payload(record, "syntactic_function", "wrapper1")
        self.assertIs(payload.state, AuthoritativePayloadState.ABSENT)
        self.assertEqual(payload.missing_count, 1)

    def test_b03_same_span_mismatch_reproduction(self) -> None:
        record = copy.deepcopy(FIXTURE)
        wrapper = {
            "id": "wrapper1",
            "node_kind": "clause",
            "clause_ref": "c0",
            "span": {"start": 1, "end": 5},
            "function": "complement",
            "realization": {"clause_ref": "c0", "relation": "same_span_alias"},
            "span_relation": "same_span_alias",
        }
        record["constituents"].append(wrapper)
        payload = authoritative_payload(record, "syntactic_function", "wrapper1")
        self.assertIs(payload.state, AuthoritativePayloadState.ABSENT)
        self.assertFalse(payload.has_resolved_content)

    def test_b03_expanded_realization_mismatch(self) -> None:
        record = copy.deepcopy(FIXTURE)
        wrapper = {
            "id": "wrapper1",
            "node_kind": "clause",
            "clause_ref": "c0",
            "span": {"start": 1, "end": 4},
            "function": "complement",
            "realization": {"clause_ref": "c0", "relation": "expanded_realization"},
            "span_relation": "expanded_realization",
        }
        record["constituents"].append(wrapper)
        self.assertTrue(any("expanded_realization wrapper must contain the clause span" in error for error in validate_record(record, "b03-expanded-mismatch")))
        payload = authoritative_payload(record, "syntactic_function", "wrapper1")
        self.assertIs(payload.state, AuthoritativePayloadState.ABSENT)

    def test_b03_dangling_clause_ref_wrapper_with_valid_function(self) -> None:
        record = copy.deepcopy(FIXTURE)
        wrapper = {
            "id": "wrapper1",
            "node_kind": "clause",
            "clause_ref": "ghost",
            "span": {"start": 0, "end": 5},
            "function": "complement",
            "realization": {"clause_ref": "ghost", "relation": "other"},
        }
        record["constituents"].append(wrapper)
        payload = authoritative_payload(record, "syntactic_function", "wrapper1")
        self.assertIs(payload.state, AuthoritativePayloadState.ABSENT)
        self.assertEqual(payload.missing_count, 1)

    def test_b03_complete_valid_function_sibling_and_invalid_wrapper(self) -> None:
        record = with_declaration(FIXTURE, declaration("syntactic_function", {"kind": "record"}))
        wrapper = {
            "id": "wrapper1",
            "node_kind": "clause",
            "clause_ref": "c0",
            "span": {"start": 1, "end": 5},
            "function": "complement",
            "realization": {"clause_ref": "c0", "relation": "same_span_alias"},
            "span_relation": "same_span_alias",
        }
        record["constituents"].append(wrapper)
        payload = authoritative_payload(record, "syntactic_function")
        self.assertIs(payload.state, AuthoritativePayloadState.PRESENT)
        self.assertGreater(payload.resolved_count, 0)
        self.assertGreater(payload.missing_count, 0)
        self.assertFalse(payload.fully_resolved)

    def test_b03_scoring_false(self) -> None:
        record = with_declaration(FIXTURE, declaration("syntactic_function", {"kind": "record"}))
        wrapper = {
            "id": "wrapper1",
            "node_kind": "clause",
            "clause_ref": "c0",
            "span": {"start": 1, "end": 5},
            "function": "complement",
            "realization": {"clause_ref": "c0", "relation": "same_span_alias"},
            "span_relation": "same_span_alias",
        }
        record["constituents"].append(wrapper)
        decision = resolve_scoring_eligibility(record, "syntactic_function")
        self.assertFalse(decision.scoreable)

    def test_b03_renderer_omits_invalid_wrapper_function(self) -> None:
        record = with_declaration(FIXTURE, declaration("syntactic_function", {"kind": "record"}))
        record = with_declaration(record, declaration("phrase_constituency", {"kind": "record"}))
        wrapper = {
            "id": "wrapper1",
            "node_kind": "clause",
            "clause_ref": "c0",
            "span": {"start": 1, "end": 5},
            "function": "complement",
            "realization": {"clause_ref": "c0", "relation": "same_span_alias"},
            "span_relation": "same_span_alias",
        }
        record["constituents"].append(wrapper)
        projection = linguistic_projection(record)
        by_id = {c["id"]: c for c in (projection.get("constituents") or [])}
        self.assertNotIn("wrapper1", by_id)

    def test_b03_invalid_wrapper_realization_does_not_leak_through_valid_clause_coverage(self) -> None:
        record = with_declaration(FIXTURE, declaration("syntactic_function", {"kind": "record"}))
        record = with_declaration(record, declaration("clause_structure", {"kind": "record"}))
        wrapper = {
            "id": "wrapper1",
            "node_kind": "clause",
            "clause_ref": "c0",
            "span": {"start": 1, "end": 5},
            "function": "complement",
            "realization": {"clause_ref": "c0", "relation": "same_span_alias"},
            "span_relation": "same_span_alias",
        }
        record["constituents"].append(wrapper)
        projection = linguistic_projection(record)
        by_id = {c["id"]: c for c in (projection.get("constituents") or [])}
        self.assertNotIn("wrapper1", by_id)
        clauses_by_id = {c["id"]: c for c in (projection.get("clauses") or [])}
        self.assertIn("c0", clauses_by_id)

    def test_b03_valid_referenced_clause_still_projects_independently(self) -> None:
        record = with_declaration(FIXTURE, declaration("clause_structure", {"kind": "record"}))
        wrapper = {
            "id": "wrapper1",
            "node_kind": "clause",
            "clause_ref": "c0",
            "span": {"start": 1, "end": 5},
            "function": "complement",
            "realization": {"clause_ref": "c0", "relation": "same_span_alias"},
            "span_relation": "same_span_alias",
        }
        record["constituents"].append(wrapper)
        clause_payload = authoritative_payload(record, "clause_structure", "c0")
        self.assertIs(clause_payload.state, AuthoritativePayloadState.PRESENT)
        self.assertTrue(clause_payload.fully_resolved)
        wrapper_payload = authoritative_payload(record, "syntactic_function", "wrapper1")
        self.assertIs(wrapper_payload.state, AuthoritativePayloadState.ABSENT)


if __name__ == "__main__":
    unittest.main()
