"""B04 record-global canonical consistency tests.

Tests for H2 Aggregate Repair R3:
- B04-A: duplicate canonical clause wrappers
- B04-B: multiple root clauses
- B04-C: sentence_type / root-construction contradiction
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
    """Ensure record has complete coverage declarations for core dimensions."""
    result = copy.deepcopy(record)
    result["annotation_scope"]["coverage"] = "complete_constituency"
    core_dimensions = ["phrase_constituency", "syntactic_function", "clause_ontology", "clause_structure"]
    for dim in core_dimensions:
        result = with_declaration(result, declaration(dim, {"kind": "record"}))
    return result


class B04ADuplicateWrapperTests(unittest.TestCase):
    """B04-A: duplicate canonical clause wrappers."""

    def test_duplicate_wrapper_validator_reproduction(self) -> None:
        """Exact validator reproduction is schema-valid but semantic-invalid."""
        record = copy.deepcopy(FIXTURE)
        record = make_complete_record(record)
        clause_id = record["clauses"][0]["id"]
        wrapper_a = {
            "id": "wrapper_a",
            "node_kind": "clause",
            "clause_ref": clause_id,
            "span": {"start": 0, "end": 5},
            "function": "complement",
            "realization": {
                "clause_ref": clause_id,
                "relation": "same_span_alias",
            },
            "span_relation": "same_span_alias",
        }
        wrapper_b = {
            "id": "wrapper_b",
            "node_kind": "clause",
            "clause_ref": clause_id,
            "span": {"start": 0, "end": 5},
            "function": "complement",
            "realization": {
                "clause_ref": clause_id,
                "relation": "same_span_alias",
            },
            "span_relation": "same_span_alias",
        }
        record["constituents"].extend([wrapper_a, wrapper_b])
        errors = validate_record(record, "duplicate-wrapper")
        self.assertTrue(any("duplicate canonical wrappers" in error for error in errors))

    def test_shared_consistency_contract_identifies_duplicates(self) -> None:
        """Both duplicate wrapper IDs are identified by shared consistency contract."""
        record = copy.deepcopy(FIXTURE)
        clause_id = record["clauses"][0]["id"]
        wrapper_a = {
            "id": "wrapper_a",
            "node_kind": "clause",
            "clause_ref": clause_id,
            "span": {"start": 0, "end": 5},
            "function": "complement",
            "realization": {"clause_ref": clause_id, "relation": "same_span_alias"},
        }
        wrapper_b = {
            "id": "wrapper_b",
            "node_kind": "clause",
            "clause_ref": clause_id,
            "span": {"start": 0, "end": 5},
            "function": "complement",
            "realization": {"clause_ref": clause_id, "relation": "same_span_alias"},
        }
        record["constituents"].extend([wrapper_a, wrapper_b])
        issues = canonical_record_consistency_issues(record)
        duplicate_issues = [i for i in issues if i.code == "duplicate_clause_wrapper"]
        self.assertEqual(len(duplicate_issues), 1)
        self.assertIn("wrapper_a", duplicate_issues[0].affected_targets)
        self.assertIn("wrapper_b", duplicate_issues[0].affected_targets)

    def test_phrase_constituency_target_query_not_positive(self) -> None:
        """phrase_constituency target query for each conflicting wrapper not positive."""
        record = copy.deepcopy(FIXTURE)
        record = make_complete_record(record)
        clause_id = record["clauses"][0]["id"]
        wrapper_a = {
            "id": "wrapper_a",
            "node_kind": "clause",
            "clause_ref": clause_id,
            "span": {"start": 0, "end": 5},
            "function": "complement",
            "realization": {"clause_ref": clause_id, "relation": "same_span_alias"},
        }
        wrapper_b = {
            "id": "wrapper_b",
            "node_kind": "clause",
            "clause_ref": clause_id,
            "span": {"start": 0, "end": 5},
            "function": "complement",
            "realization": {"clause_ref": clause_id, "relation": "same_span_alias"},
        }
        record["constituents"].extend([wrapper_a, wrapper_b])
        payload_a = authoritative_payload(record, "phrase_constituency", "wrapper_a")
        payload_b = authoritative_payload(record, "phrase_constituency", "wrapper_b")
        self.assertNotEqual(payload_a.state, AuthoritativePayloadState.PRESENT)
        self.assertNotEqual(payload_b.state, AuthoritativePayloadState.PRESENT)

    def test_syntactic_function_target_query_not_positive(self) -> None:
        """syntactic_function target query for each conflicting wrapper not positive."""
        record = copy.deepcopy(FIXTURE)
        record = make_complete_record(record)
        clause_id = record["clauses"][0]["id"]
        wrapper_a = {
            "id": "wrapper_a",
            "node_kind": "clause",
            "clause_ref": clause_id,
            "span": {"start": 0, "end": 5},
            "function": "complement",
            "realization": {"clause_ref": clause_id, "relation": "same_span_alias"},
        }
        wrapper_b = {
            "id": "wrapper_b",
            "node_kind": "clause",
            "clause_ref": clause_id,
            "span": {"start": 0, "end": 5},
            "function": "complement",
            "realization": {"clause_ref": clause_id, "relation": "same_span_alias"},
        }
        record["constituents"].extend([wrapper_a, wrapper_b])
        payload_a = authoritative_payload(record, "syntactic_function", "wrapper_a")
        payload_b = authoritative_payload(record, "syntactic_function", "wrapper_b")
        self.assertNotEqual(payload_a.state, AuthoritativePayloadState.PRESENT)
        self.assertNotEqual(payload_b.state, AuthoritativePayloadState.PRESENT)

    def test_record_complete_payload_not_fully_resolved(self) -> None:
        """Record COMPLETE payload: resolved sibling > 0, missing > 0, fully_resolved=False."""
        record = copy.deepcopy(FIXTURE)
        record = make_complete_record(record)
        clause_id = record["clauses"][0]["id"]
        wrapper_a = {
            "id": "wrapper_a",
            "node_kind": "clause",
            "clause_ref": clause_id,
            "span": {"start": 0, "end": 5},
            "function": "complement",
            "realization": {"clause_ref": clause_id, "relation": "same_span_alias"},
        }
        wrapper_b = {
            "id": "wrapper_b",
            "node_kind": "clause",
            "clause_ref": clause_id,
            "span": {"start": 0, "end": 5},
            "function": "complement",
            "realization": {"clause_ref": clause_id, "relation": "same_span_alias"},
        }
        record["constituents"].extend([wrapper_a, wrapper_b])
        payload = authoritative_payload(record, "phrase_constituency")
        self.assertGreater(payload.resolved_count, 0)
        self.assertGreater(payload.missing_count, 0)
        self.assertFalse(payload.fully_resolved)

    def test_scoring_false(self) -> None:
        """Scoring false for duplicate wrapper conflict."""
        record = copy.deepcopy(FIXTURE)
        record = make_complete_record(record)
        clause_id = record["clauses"][0]["id"]
        wrapper_a = {
            "id": "wrapper_a",
            "node_kind": "clause",
            "clause_ref": clause_id,
            "span": {"start": 0, "end": 5},
            "function": "complement",
            "realization": {"clause_ref": clause_id, "relation": "same_span_alias"},
        }
        wrapper_b = {
            "id": "wrapper_b",
            "node_kind": "clause",
            "clause_ref": clause_id,
            "span": {"start": 0, "end": 5},
            "function": "complement",
            "realization": {"clause_ref": clause_id, "relation": "same_span_alias"},
        }
        record["constituents"].extend([wrapper_a, wrapper_b])
        decision = resolve_scoring_eligibility(record, "phrase_constituency")
        self.assertFalse(decision.scoreable)

    def test_linguistic_projection_does_not_emit_both(self) -> None:
        """True linguistic_projection() does not emit both conflicting wrappers as positive gold."""
        record = copy.deepcopy(FIXTURE)
        record = make_complete_record(record)
        clause_id = record["clauses"][0]["id"]
        wrapper_a = {
            "id": "wrapper_a",
            "node_kind": "clause",
            "clause_ref": clause_id,
            "span": {"start": 0, "end": 5},
            "function": "complement",
            "realization": {"clause_ref": clause_id, "relation": "same_span_alias"},
        }
        wrapper_b = {
            "id": "wrapper_b",
            "node_kind": "clause",
            "clause_ref": clause_id,
            "span": {"start": 0, "end": 5},
            "function": "complement",
            "realization": {"clause_ref": clause_id, "relation": "same_span_alias"},
        }
        record["constituents"].extend([wrapper_a, wrapper_b])
        projection = linguistic_projection(record)
        projected_constituents = {c["id"]: c for c in projection.get("constituents", [])}
        self.assertNotIn("wrapper_a", projected_constituents)
        self.assertNotIn("wrapper_b", projected_constituents)

    def test_valid_unrelated_constituent_still_projects(self) -> None:
        """Valid unrelated constituent still projects."""
        record = copy.deepcopy(FIXTURE)
        clause_id = record["clauses"][0]["id"]
        wrapper_a = {
            "id": "wrapper_a",
            "node_kind": "clause",
            "clause_ref": clause_id,
            "span": {"start": 0, "end": 5},
            "function": "complement",
            "realization": {"clause_ref": clause_id, "relation": "same_span_alias"},
        }
        wrapper_b = {
            "id": "wrapper_b",
            "node_kind": "clause",
            "clause_ref": clause_id,
            "span": {"start": 0, "end": 5},
            "function": "complement",
            "realization": {"clause_ref": clause_id, "relation": "same_span_alias"},
        }
        record["constituents"].extend([wrapper_a, wrapper_b])
        projection = linguistic_projection(record)
        projected_constituents = {c["id"]: c for c in projection.get("constituents", [])}
        self.assertIn("subj", projected_constituents)
        self.assertIn("obj", projected_constituents)

    def test_conflicting_wrapper_shell_is_identity_only(self) -> None:
        """If conflicting wrapper is referenced by valid relation, shell is identity-only."""
        record = copy.deepcopy(FIXTURE)
        record = make_complete_record(record)
        clause_id = record["clauses"][0]["id"]
        wrapper_a = {
            "id": "wrapper_a",
            "node_kind": "clause",
            "clause_ref": clause_id,
            "span": {"start": 0, "end": 5},
            "function": "complement",
            "realization": {"clause_ref": clause_id, "relation": "same_span_alias"},
        }
        wrapper_b = {
            "id": "wrapper_b",
            "node_kind": "clause",
            "clause_ref": clause_id,
            "span": {"start": 0, "end": 5},
            "function": "complement",
            "realization": {"clause_ref": clause_id, "relation": "same_span_alias"},
        }
        record["constituents"].extend([wrapper_a, wrapper_b])
        record["dependencies"] = [{
            "head": "w0",
            "dependent": "wrapper_a",
            "relation": "dep",
        }]
        projection = linguistic_projection(record)
        projected_constituents = {c["id"]: c for c in projection.get("constituents", [])}
        if "wrapper_a" in projected_constituents:
            shell = projected_constituents["wrapper_a"]
            self.assertEqual(shell.get("node_kind"), "clause")
            self.assertNotIn("function", shell)
            self.assertNotIn("phrase_category", shell)

    def test_valid_non_conflicting_wrapper_control_remains_positive(self) -> None:
        """Valid non-conflicting wrapper control remains positive."""
        record = copy.deepcopy(FIXTURE)
        record = make_complete_record(record)
        clause_id = record["clauses"][0]["id"]
        valid_wrapper = {
            "id": "valid_wrapper",
            "node_kind": "clause",
            "clause_ref": clause_id,
            "span": {"start": 0, "end": 5},
            "function": "adjunct",
            "realization": {"clause_ref": clause_id, "relation": "same_span_alias"},
        }
        record["constituents"].append(valid_wrapper)
        payload = authoritative_payload(record, "phrase_constituency", "valid_wrapper")
        self.assertEqual(payload.state, AuthoritativePayloadState.PRESENT)
        self.assertTrue(payload.fully_resolved)


class B04BMultipleRootTests(unittest.TestCase):
    """B04-B: multiple root clauses."""

    def test_multiple_root_validator_reproduction(self) -> None:
        """Exact validator reproduction with c0+c1 roots."""
        record = copy.deepcopy(FIXTURE)
        record = make_complete_record(record)
        c1 = copy.deepcopy(record["clauses"][0])
        c1["id"] = "c1"
        c1["integration"] = ["root"]
        record["clauses"].append(c1)
        errors = validate_record(record, "multiple-roots")
        self.assertTrue(any("exactly one root clause" in error for error in errors))

    def test_shared_consistency_identifies_both_roots(self) -> None:
        """Shared consistency issue identifies both root targets."""
        record = copy.deepcopy(FIXTURE)
        c1 = copy.deepcopy(record["clauses"][0])
        c1["id"] = "c1"
        c1["integration"] = ["root"]
        record["clauses"].append(c1)
        issues = canonical_record_consistency_issues(record)
        root_issues = [i for i in issues if i.code == "multiple_root_clauses"]
        self.assertEqual(len(root_issues), 1)
        self.assertIn("c0", root_issues[0].affected_targets)
        self.assertIn("c1", root_issues[0].affected_targets)

    def test_clause_structure_not_fully_resolved(self) -> None:
        """clause_structure record payload not fully resolved."""
        record = copy.deepcopy(FIXTURE)
        record = make_complete_record(record)
        c1 = copy.deepcopy(record["clauses"][0])
        c1["id"] = "c1"
        c1["integration"] = ["root"]
        record["clauses"].append(c1)
        payload = authoritative_payload(record, "clause_structure")
        self.assertFalse(payload.fully_resolved)

    def test_clause_ontology_not_fully_resolved(self) -> None:
        """clause_ontology behavior follows registry ownership consistently."""
        record = copy.deepcopy(FIXTURE)
        record = make_complete_record(record)
        c1 = copy.deepcopy(record["clauses"][0])
        c1["id"] = "c1"
        c1["integration"] = ["root"]
        record["clauses"].append(c1)
        payload = authoritative_payload(record, "clause_ontology")
        self.assertFalse(payload.fully_resolved)

    def test_scoring_false(self) -> None:
        """Scoring false for multiple root conflict."""
        record = copy.deepcopy(FIXTURE)
        record = make_complete_record(record)
        c1 = copy.deepcopy(record["clauses"][0])
        c1["id"] = "c1"
        c1["integration"] = ["root"]
        record["clauses"].append(c1)
        decision = resolve_scoring_eligibility(record, "clause_structure")
        self.assertFalse(decision.scoreable)

    def test_target_query_c0_not_clean_positive(self) -> None:
        """Target query c0 not clean positive."""
        record = copy.deepcopy(FIXTURE)
        record = make_complete_record(record)
        c1 = copy.deepcopy(record["clauses"][0])
        c1["id"] = "c1"
        c1["integration"] = ["root"]
        record["clauses"].append(c1)
        payload = authoritative_payload(record, "clause_structure", "c0")
        self.assertNotEqual(payload.state, AuthoritativePayloadState.PRESENT)

    def test_target_query_c1_not_clean_positive(self) -> None:
        """Target query c1 not clean positive."""
        record = copy.deepcopy(FIXTURE)
        record = make_complete_record(record)
        c1 = copy.deepcopy(record["clauses"][0])
        c1["id"] = "c1"
        c1["integration"] = ["root"]
        record["clauses"].append(c1)
        payload = authoritative_payload(record, "clause_structure", "c1")
        self.assertNotEqual(payload.state, AuthoritativePayloadState.PRESENT)

    def test_unrelated_non_root_clause_control_remains_positive(self) -> None:
        """Unrelated non-root clause control remains positive."""
        record = copy.deepcopy(FIXTURE)
        c1 = copy.deepcopy(record["clauses"][0])
        c1["id"] = "c1"
        c1["integration"] = ["root"]
        c2 = copy.deepcopy(record["clauses"][0])
        c2["id"] = "c2"
        c2["integration"] = ["subordinate"]
        record["clauses"].extend([c1, c2])
        payload = authoritative_payload(record, "clause_structure", "c2")
        self.assertEqual(payload.state, AuthoritativePayloadState.PRESENT)
        self.assertTrue(payload.fully_resolved)

    def test_linguistic_projection_never_emits_two_roots(self) -> None:
        """linguistic_projection() never emits two positive canonical roots."""
        record = copy.deepcopy(FIXTURE)
        record = make_complete_record(record)
        c1 = copy.deepcopy(record["clauses"][0])
        c1["id"] = "c1"
        c1["integration"] = ["root"]
        record["clauses"].append(c1)
        projection = linguistic_projection(record)
        projected_clauses = projection.get("clauses", [])
        root_clauses = [c for c in projected_clauses if "root" in c.get("integration", [])]
        self.assertLessEqual(len(root_clauses), 1)

    def test_valid_unrelated_dimension_remains_projectable(self) -> None:
        """Valid unrelated dimension, e.g. dependency, remains independently projectable."""
        record = copy.deepcopy(FIXTURE)
        c1 = copy.deepcopy(record["clauses"][0])
        c1["id"] = "c1"
        c1["integration"] = ["root"]
        record["clauses"].append(c1)
        record["dependencies"] = [{"head": "w0", "dependent": "w1", "relation": "dep"}]
        record["annotation_scope"]["dimensions"] = [
            entry for entry in record["annotation_scope"]["dimensions"]
            if entry.get("dimension") != "dependencies"
        ] + [declaration("dependencies", {"kind": "record"})]
        projection = linguistic_projection(record)
        self.assertIn("dependencies", projection)
        self.assertGreater(len(projection["dependencies"]), 0)


class B04CMoodContradictionTests(unittest.TestCase):
    """B04-C: sentence_type / root-construction contradiction."""

    def test_mood_contradiction_validator_reproduction(self) -> None:
        """sentence_type=interrogative + declarative root reproduces validator INVALID."""
        record = copy.deepcopy(FIXTURE)
        record = make_complete_record(record)
        record["sentence_type"] = "interrogative"
        record["clauses"][0]["clause_construction"] = "declarative"
        errors = validate_record(record, "mood-contradiction")
        self.assertTrue(any("sentence_type is derived from the root clause" in error for error in errors))

    def test_root_target_participates_in_consistency_issue(self) -> None:
        """Root target participates in consistency issue."""
        record = copy.deepcopy(FIXTURE)
        record["sentence_type"] = "interrogative"
        record["clauses"][0]["clause_construction"] = "declarative"
        issues = canonical_record_consistency_issues(record)
        mood_issues = [i for i in issues if i.code == "sentence_type_root_construction_contradiction"]
        self.assertEqual(len(mood_issues), 1)
        self.assertIn("c0", mood_issues[0].affected_targets)

    def test_affected_clause_payload_not_fully_resolved(self) -> None:
        """Affected clause payload not fully resolved."""
        record = copy.deepcopy(FIXTURE)
        record = make_complete_record(record)
        record["sentence_type"] = "interrogative"
        record["clauses"][0]["clause_construction"] = "declarative"
        payload = authoritative_payload(record, "clause_structure", "c0")
        self.assertFalse(payload.fully_resolved)

    def test_scoring_false(self) -> None:
        """Scoring false for mood contradiction."""
        record = copy.deepcopy(FIXTURE)
        record = make_complete_record(record)
        record["sentence_type"] = "interrogative"
        record["clauses"][0]["clause_construction"] = "declarative"
        decision = resolve_scoring_eligibility(record, "clause_structure")
        self.assertFalse(decision.scoreable)

    def test_renderer_does_not_emit_contradictory_pair(self) -> None:
        """Renderer does not emit contradictory sentence type + root construction pair."""
        record = copy.deepcopy(FIXTURE)
        record = make_complete_record(record)
        record["sentence_type"] = "interrogative"
        record["clauses"][0]["clause_construction"] = "declarative"
        projection = linguistic_projection(record)
        if "sentence_type" in projection and "clauses" in projection:
            root_clauses = [c for c in projection["clauses"] if "root" in c.get("integration", [])]
            if root_clauses:
                root_construction = root_clauses[0].get("clause_construction")
                if root_construction in {"declarative", "interrogative", "exclamative"}:
                    self.assertEqual(projection["sentence_type"], root_construction)

    def test_unrelated_valid_dimensions_remain_available(self) -> None:
        """Unrelated valid dimensions remain available."""
        record = copy.deepcopy(FIXTURE)
        record = make_complete_record(record)
        record["sentence_type"] = "interrogative"
        record["clauses"][0]["clause_construction"] = "declarative"
        payload = authoritative_payload(record, "lexical_category")
        self.assertEqual(payload.state, AuthoritativePayloadState.PRESENT)
        self.assertTrue(payload.fully_resolved)

    def test_matching_control_declarative_declarative(self) -> None:
        """Matching control: declarative + declarative remains valid."""
        record = copy.deepcopy(FIXTURE)
        record = make_complete_record(record)
        record["sentence_type"] = "declarative"
        record["clauses"][0]["clause_construction"] = "declarative"
        issues = canonical_record_consistency_issues(record)
        mood_issues = [i for i in issues if i.code == "sentence_type_root_construction_contradiction"]
        self.assertEqual(len(mood_issues), 0)

    def test_matching_control_interrogative_interrogative(self) -> None:
        """Matching control: interrogative + interrogative remains valid."""
        record = copy.deepcopy(FIXTURE)
        record = make_complete_record(record)
        record["sentence_type"] = "interrogative"
        record["clauses"][0]["clause_construction"] = "interrogative"
        issues = canonical_record_consistency_issues(record)
        mood_issues = [i for i in issues if i.code == "sentence_type_root_construction_contradiction"]
        self.assertEqual(len(mood_issues), 0)


class B04CrossCombinationTests(unittest.TestCase):
    """Cross-combination test."""

    def test_combined_conflicts_dimension_aware(self) -> None:
        """Duplicate wrapper + multiple root + valid dependency: dimension-aware."""
        record = copy.deepcopy(FIXTURE)
        record = make_complete_record(record)
        clause_id = record["clauses"][0]["id"]
        wrapper_a = {
            "id": "wrapper_a",
            "node_kind": "clause",
            "clause_ref": clause_id,
            "span": {"start": 0, "end": 5},
            "function": "complement",
            "realization": {"clause_ref": clause_id, "relation": "same_span_alias"},
        }
        wrapper_b = {
            "id": "wrapper_b",
            "node_kind": "clause",
            "clause_ref": clause_id,
            "span": {"start": 0, "end": 5},
            "function": "complement",
            "realization": {"clause_ref": clause_id, "relation": "same_span_alias"},
        }
        record["constituents"].extend([wrapper_a, wrapper_b])
        c1 = copy.deepcopy(record["clauses"][0])
        c1["id"] = "c1"
        c1["integration"] = ["root"]
        record["clauses"].append(c1)
        record["dependencies"] = [{"head": "w0", "dependent": "w1", "relation": "dep"}]
        phrase_payload = authoritative_payload(record, "phrase_constituency", "wrapper_a")
        self.assertNotEqual(phrase_payload.state, AuthoritativePayloadState.PRESENT)
        clause_payload = authoritative_payload(record, "clause_structure", "c0")
        self.assertNotEqual(clause_payload.state, AuthoritativePayloadState.PRESENT)
        dep_payload = authoritative_payload(record, "dependencies")
        self.assertEqual(dep_payload.state, AuthoritativePayloadState.PRESENT)
        self.assertTrue(dep_payload.fully_resolved)


class B04ValidatorParityTests(unittest.TestCase):
    """Validator parity test."""

    def test_helper_and_validator_agree_on_duplicate_wrapper(self) -> None:
        """Helper says issue -> validator emits corresponding error."""
        record = copy.deepcopy(FIXTURE)
        clause_id = record["clauses"][0]["id"]
        wrapper_a = {
            "id": "wrapper_a",
            "node_kind": "clause",
            "clause_ref": clause_id,
            "span": {"start": 0, "end": 5},
            "function": "complement",
            "realization": {"clause_ref": clause_id, "relation": "same_span_alias"},
        }
        wrapper_b = {
            "id": "wrapper_b",
            "node_kind": "clause",
            "clause_ref": clause_id,
            "span": {"start": 0, "end": 5},
            "function": "complement",
            "realization": {"clause_ref": clause_id, "relation": "same_span_alias"},
        }
        record["constituents"].extend([wrapper_a, wrapper_b])
        issues = canonical_record_consistency_issues(record)
        duplicate_issues = [i for i in issues if i.code == "duplicate_clause_wrapper"]
        errors = validate_record(record, "parity-test")
        if duplicate_issues:
            self.assertTrue(any("duplicate canonical wrappers" in error for error in errors))

    def test_helper_and_validator_agree_on_multiple_roots(self) -> None:
        """Helper says issue -> validator emits corresponding error."""
        record = copy.deepcopy(FIXTURE)
        c1 = copy.deepcopy(record["clauses"][0])
        c1["id"] = "c1"
        c1["integration"] = ["root"]
        record["clauses"].append(c1)
        issues = canonical_record_consistency_issues(record)
        root_issues = [i for i in issues if i.code == "multiple_root_clauses"]
        errors = validate_record(record, "parity-test")
        if root_issues:
            self.assertTrue(any("exactly one root clause" in error for error in errors))

    def test_helper_and_validator_agree_on_mood_contradiction(self) -> None:
        """Helper says issue -> validator emits corresponding error."""
        record = copy.deepcopy(FIXTURE)
        record["sentence_type"] = "interrogative"
        record["clauses"][0]["clause_construction"] = "declarative"
        issues = canonical_record_consistency_issues(record)
        mood_issues = [i for i in issues if i.code == "sentence_type_root_construction_contradiction"]
        errors = validate_record(record, "parity-test")
        if mood_issues:
            self.assertTrue(any("sentence_type is derived from the root clause" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
