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
    construction_typed_relation_types,
    typed_analysis_relation_entries,
    typed_argument_owner_dimensions,
    typed_relation_owner_dimensions,
)
from scripts.canonical_schema import canonical_schema_issues
from scripts.data_common import read_jsonl
from scripts.coverage_resolution import CoverageState, resolve_scoring_eligibility
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
        self.assertEqual(typed_relation_owner_dimensions("construction"), frozenset())
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
        self.assertIn("emb", projected_constituents)
        self.assertNotIn("phrase_category", projected_constituents["emb"])
        self.assertNotIn("span_relation", projected_constituents["emb"])

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


if __name__ == "__main__":
    unittest.main()
