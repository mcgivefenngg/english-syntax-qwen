from __future__ import annotations

import copy
import unittest

from scripts.authoritative_payload import AuthoritativePayloadState, authoritative_payload
from scripts.canonical_schema import canonical_schema_issues
from scripts.coverage_resolution import (
    CoverageResolutionError,
    CoverageState,
    collection_item_coverage_state,
    resolve_coverage,
    resolve_scoring_eligibility,
)
from scripts.render_sft import linguistic_projection
from scripts.validate_dataset import validate_record
from tests.test_coverage_target_applicability import FIXTURE, declaration


DIMENSION = "phrase_constituency"


def scoped_record(invalid: bool = True) -> dict:
    record = copy.deepcopy(FIXTURE)
    record["annotation_scope"]["dimensions"] = [
        declaration(DIMENSION, {"kind": "node", "node": "subj"}),
        declaration(DIMENSION, {"kind": "node", "node": "obj"}, "partial"),
    ]
    if invalid:
        record["constituents"][1]["head"] = "ghost"
    return record


class ScopedTargetIsolationTests(unittest.TestCase):
    def assert_rejected(self, record: dict, target: str | dict | None, message: str) -> None:
        with self.assertRaisesRegex(CoverageResolutionError, message):
            resolve_coverage(record, DIMENSION, target)
        self.assertFalse(resolve_scoring_eligibility(record, DIMENSION, target).scoreable)

    def test_original_reproduction_and_order_invariance(self) -> None:
        projections = []
        for reverse in (False, True):
            with self.subTest(reverse=reverse):
                record = scoped_record()
                if reverse:
                    record["annotation_scope"]["dimensions"].reverse()
                self.assertEqual(canonical_schema_issues(record), [])
                payload = authoritative_payload(record, DIMENSION, "subj")
                self.assertIs(payload.state, AuthoritativePayloadState.PRESENT)
                self.assertEqual((payload.applicable_count, payload.resolved_count,
                                  payload.unresolved_count, payload.missing_count), (1, 1, 0, 0))
                self.assertTrue(payload.fully_resolved)
                bad_payload = authoritative_payload(record, DIMENSION, "obj")
                self.assertFalse(bad_payload.fully_resolved)
                self.assertEqual(bad_payload.missing_count, 1)
                self.assertIs(resolve_coverage(record, DIMENSION, "subj"), CoverageState.COMPLETE)
                self.assertTrue(resolve_scoring_eligibility(record, DIMENSION, "subj").scoreable)
                bad_index = 0 if reverse else 1
                self.assert_rejected(record, "obj", f"obj.*evidence='present'.*declaration index {bad_index}")
                errors = validate_record(record, "m03-original")
                self.assertTrue(any(
                    f"dimensions[{bad_index}]" in error and "obj" in error
                    and "evidence='present'" in error for error in errors
                ), errors)
                for target in (None, {"kind": "record"}):
                    self.assert_rejected(record, target, "obj.*evidence='present'")
                projection = linguistic_projection(record)
                projections.append(projection)
                projected = {item["id"]: item for item in projection.get("constituents", [])}
                for field in ("id", "node_kind", "span", "phrase_category"):
                    self.assertEqual(projected["subj"][field], record["constituents"][0][field])
                for field in ("phrase_category", "head", "parent", "children", "realization"):
                    self.assertNotIn(field, projected.get("obj", {}))
                self.assertIs(collection_item_coverage_state(
                    record, DIMENSION, record["constituents"][0]), CoverageState.COMPLETE)
                self.assertIsNone(collection_item_coverage_state(
                    record, DIMENSION, record["constituents"][1]))
        self.assertEqual(projections[0], projections[1])

    def test_valid_sibling_baseline(self) -> None:
        record = scoped_record(False)
        self.assertEqual(validate_record(record, "m03-valid"), [])
        self.assertIs(resolve_coverage(record, DIMENSION, "subj"), CoverageState.COMPLETE)
        self.assertIs(resolve_coverage(record, DIMENSION, "obj"), CoverageState.PARTIAL_COVERED)

    def test_non_containing_region_content_is_isolated(self) -> None:
        record = scoped_record()
        record["annotation_scope"]["dimensions"] = [
            declaration(DIMENSION, {"kind": "region", "start": 0, "end": 2}),
            declaration(DIMENSION, {"kind": "region", "start": 3, "end": 5}, "partial"),
        ]
        for reverse in (False, True):
            if reverse:
                record["annotation_scope"]["dimensions"].reverse()
            self.assertEqual(canonical_schema_issues(record), [])
            self.assertIs(resolve_coverage(record, DIMENSION, "subj"), CoverageState.COMPLETE)
            self.assert_rejected(record, "obj", "evidence='present'")

    def test_containing_region_remains_applicable_with_exact_node(self) -> None:
        record = scoped_record()
        record["annotation_scope"]["dimensions"].append(
            declaration(DIMENSION, {"kind": "region", "start": 0, "end": 5}))
        self.assert_rejected(record, "subj", "evidence='present'.*declaration index 2")

    def test_record_complete_content_remains_applicable(self) -> None:
        record = scoped_record()
        record["annotation_scope"]["dimensions"] = [
            record["annotation_scope"]["dimensions"][0],
            declaration(DIMENSION, {"kind": "record"}),
        ]
        for target in (None, "subj"):
            self.assert_rejected(record, target, "evidence='present'.*declaration index 1")

    def test_wrong_kind_declaration_remains_global(self) -> None:
        record = scoped_record(False)
        record["annotation_scope"]["dimensions"].append(
            declaration("clause_ontology", {"kind": "node", "node": "obj"}))
        self.assertEqual(canonical_schema_issues(record), [])
        self.assert_rejected(record, "subj", "node scope must reference clause.*declaration index 2")

    def test_duplicate_and_contradictory_exact_scope_remain_global(self) -> None:
        for completeness in ("partial", "complete"):
            record = scoped_record(False)
            duplicate = declaration(DIMENSION, {"kind": "node", "node": "obj"}, completeness)
            duplicate["notes"] = "distinct JSON object, same coverage identity"
            record["annotation_scope"]["dimensions"].append(duplicate)
            self.assertEqual(canonical_schema_issues(record), [])
            message = "duplicate dimension" if completeness == "partial" else "contradictory coverage"
            self.assert_rejected(record, "subj", message)

    def test_contradictory_peer_regions_remain_global(self) -> None:
        record = scoped_record(False)
        record["annotation_scope"]["dimensions"].extend([
            declaration(DIMENSION, {"kind": "region", "start": 2, "end": 4}),
            declaration(DIMENSION, {"kind": "region", "start": 3, "end": 5}, "partial"),
        ])
        self.assertEqual(canonical_schema_issues(record), [])
        self.assert_rejected(record, "subj", "overlapping peer regions")

    def test_schema_and_identity_errors_remain_global(self) -> None:
        record = scoped_record(False)
        record["split"] = "invalid"
        self.assert_rejected(record, "subj", "canonical schema")
        record = scoped_record(False)
        record["words"][1]["id"] = record["words"][0]["id"]
        self.assert_rejected(record, "subj", "duplicate canonical object id")

    def test_omitted_sibling_content_is_isolated(self) -> None:
        record = scoped_record(False)
        record["annotation_scope"]["dimensions"][1] = declaration(
            DIMENSION, {"kind": "node", "node": "obj"}, "omitted", "intentional", "unannotated")
        self.assertTrue(validate_record(record, "m03-omitted"))
        self.assertIs(resolve_coverage(record, DIMENSION, "subj"), CoverageState.COMPLETE)
        self.assert_rejected(record, "obj", "unannotated/omitted")


if __name__ == "__main__":
    unittest.main()
