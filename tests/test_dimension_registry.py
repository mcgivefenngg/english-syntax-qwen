from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from typing import Any

from scripts.coverage_resolution import CoverageResolutionError, CoverageState, resolve_coverage
from scripts.data_common import ANNOTATED_DIMENSIONS, read_jsonl
from scripts.dimension_registry import CAPABILITY_DIMENSIONS, DIMENSION_REGISTRY, PROJECTION_FIELD_DIMENSIONS
from scripts.render_sft import DIMENSION_FIELDS, DIMENSION_PROPERTY_MAP, linguistic_projection
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


def record_with(*entries: dict[str, Any]) -> dict[str, Any]:
    record = copy.deepcopy(FIXTURE)
    record["annotation_scope"]["dimensions"] = list(entries)
    return record


class DimensionRegistryTests(unittest.TestCase):
    def test_registry_is_the_shared_dimension_surface(self) -> None:
        registry_names = set(DIMENSION_REGISTRY)
        schema = json.loads((ROOT / "schemas" / "gold_annotation.schema.json").read_text())
        schema_names = set(schema["$defs"]["coverageDimension"]["properties"]["dimension"]["enum"])
        self.assertEqual(ANNOTATED_DIMENSIONS, registry_names)
        self.assertEqual(schema_names, registry_names)
        self.assertEqual(set(DIMENSION_FIELDS), registry_names)
        self.assertEqual(set(DIMENSION_PROPERTY_MAP), registry_names)
        self.assertTrue(all(
            dimension in registry_names
            for dimensions in CAPABILITY_DIMENSIONS.values()
            for dimension in dimensions
        ))
        self.assertTrue(all(
            dimension in registry_names
            for dimensions in PROJECTION_FIELD_DIMENSIONS.values()
            for dimension in dimensions
        ))

    def test_every_registry_dimension_is_accepted_by_validator_and_resolver(self) -> None:
        empty_collections = {"dependencies", "semantic_roles", "lexical_valency"}
        for dimension, spec in DIMENSION_REGISTRY.items():
            with self.subTest(dimension=dimension):
                evidence = "empty" if dimension in empty_collections else "present"
                record = record_with(declaration(dimension, {"kind": "record"}, evidence=evidence))
                if dimension in empty_collections:
                    record[dimension] = []
                if dimension == "vp_complementation":
                    record["lexical_valency"] = [{"predicate": "catalogue", "frame": "transitive", "selected_complements": []}]
                if dimension == "construction_relations":
                    record["construction_type"] = "transitive"
                self.assertEqual(validate_record(record, f"registry:{dimension}"), [])
                expected = CoverageState.CONFIRMED_EMPTY if evidence == "empty" else CoverageState.COMPLETE
                self.assertIs(resolve_coverage(record, dimension), expected)
                self.assertTrue(spec.allowed_scope_kinds)

    def test_unknown_dimension_is_rejected_by_validator_resolver_and_renderer(self) -> None:
        record = record_with(declaration("unknown_dimension", {"kind": "record"}))
        errors = validate_record(record, "unknown-dimension")
        self.assertTrue(any("unknown coverage dimension" in error for error in errors))
        self.assertTrue(any("schema validation failed" in error for error in errors))
        with self.assertRaises(CoverageResolutionError):
            resolve_coverage(record, "unknown_dimension")
        payload = linguistic_projection(record)
        self.assertEqual(set(payload), {"sentence"})
        self.assertNotIn("unknown_dimension", DIMENSION_FIELDS)

    def test_renderer_does_not_recognize_noncanonical_ambiguity_dimension(self) -> None:
        record = record_with(declaration("ambiguity", {"kind": "record"}))
        record["ambiguity"] = {
            "status": "genuinely_ambiguous",
            "analyses": [
                {"id": "one", "structural_claims": ["one"], "interpretation": "one"},
                {"id": "two", "structural_claims": ["two"], "interpretation": "two"},
            ],
        }
        self.assertNotIn("ambiguity", linguistic_projection(record))
        self.assertTrue(any("unknown coverage dimension" in error for error in validate_record(record, "ambiguity-dimension")))

    def test_dependencies_node_and_region_scopes_are_rejected(self) -> None:
        for scope in ({"kind": "node", "node": "w2"}, {"kind": "region", "start": 0, "end": 1}):
            with self.subTest(scope=scope):
                record = record_with(declaration("dependencies", scope))
                self.assertTrue(any("dependencies" in error and "scope" in error for error in validate_record(record, "dependency-scope")))
                with self.assertRaises(CoverageResolutionError):
                    resolve_coverage(record, "dependencies")

    def test_semantic_roles_node_and_region_scopes_are_rejected(self) -> None:
        for scope in ({"kind": "node", "node": "obj"}, {"kind": "region", "start": 0, "end": 2}):
            with self.subTest(scope=scope):
                record = record_with(declaration("semantic_roles", scope))
                self.assertTrue(any("semantic_roles" in error and "scope" in error for error in validate_record(record, "role-scope")))
                with self.assertRaises(CoverageResolutionError):
                    resolve_coverage(record, "semantic_roles")

    def test_lexical_valency_allows_lexical_head_word_scope(self) -> None:
        record = record_with(declaration("lexical_valency", {"kind": "node", "node": "w2"}))
        record["lexical_valency"] = [{"predicate": "catalogue", "frame": "transitive", "selected_complements": []}]
        self.assertEqual(validate_record(record, "valency-head"), [])
        self.assertIs(resolve_coverage(record, "lexical_valency", "w2"), CoverageState.COMPLETE)

    def test_lexical_valency_rejects_constituent_ownership_scope(self) -> None:
        record = record_with(declaration("lexical_valency", {"kind": "node", "node": "obj"}))
        record["lexical_valency"] = [{"predicate": "catalogue", "frame": "transitive", "selected_complements": ["obj"]}]
        errors = validate_record(record, "valency-complement")
        self.assertTrue(any("lexical_valency" in error and "word" in error for error in errors))
        with self.assertRaises(CoverageResolutionError):
            resolve_coverage(record, "lexical_valency", "obj")

    def test_scalar_dimension_rejects_confirmed_empty_evidence(self) -> None:
        for dimension in ("lexical_category", "syntactic_function", "framework_mapping"):
            with self.subTest(dimension=dimension):
                record = record_with(declaration(dimension, {"kind": "record"}, evidence="empty"))
                self.assertTrue(any("does not support evidence='empty'" in error for error in validate_record(record, "scalar-empty")))
                with self.assertRaises(CoverageResolutionError):
                    resolve_coverage(record, dimension)

    def test_record_collection_confirmed_empty_is_supported(self) -> None:
        for dimension in ("dependencies", "semantic_roles", "lexical_valency"):
            with self.subTest(dimension=dimension):
                record = record_with(declaration(dimension, {"kind": "record"}, evidence="empty"))
                record[dimension] = []
                self.assertEqual(validate_record(record, f"{dimension}-empty"), [])
                self.assertIs(resolve_coverage(record, dimension), CoverageState.CONFIRMED_EMPTY)

    def test_scoped_confirmed_empty_is_rejected(self) -> None:
        record = record_with(declaration("phrase_constituency", {"kind": "node", "node": "subj"}, evidence="empty"))
        self.assertTrue(any("confirmed-empty" in error for error in validate_record(record, "scoped-empty")))
        with self.assertRaises(CoverageResolutionError):
            resolve_coverage(record, "phrase_constituency", "subj")

    def test_undefined_record_partial_present_is_rejected(self) -> None:
        record = record_with(declaration("vp_complementation", {"kind": "record"}, completeness="partial"))
        self.assertTrue(any("no identifiable target representation" in error for error in validate_record(record, "partial-record")))
        with self.assertRaises(CoverageResolutionError):
            resolve_coverage(record, "vp_complementation")

    def test_targeted_partial_scope_remains_allowed(self) -> None:
        record = record_with(declaration("phrase_constituency", {"kind": "node", "node": "subj"}, completeness="partial"))
        self.assertEqual(validate_record(record, "partial-node"), [])
        self.assertIs(resolve_coverage(record, "phrase_constituency", "subj"), CoverageState.PARTIAL_COVERED)

    def test_declaration_order_does_not_change_registry_resolution(self) -> None:
        entries = [
            declaration("phrase_constituency", {"kind": "record"}, completeness="partial"),
            declaration("phrase_constituency", {"kind": "node", "node": "subj"}, completeness="complete"),
        ]
        forward = record_with(*entries)
        reverse = record_with(*reversed(entries))
        self.assertIs(resolve_coverage(forward, "phrase_constituency", "subj"), CoverageState.COMPLETE)
        self.assertIs(resolve_coverage(reverse, "phrase_constituency", "subj"), CoverageState.COMPLETE)


if __name__ == "__main__":
    unittest.main()
