"""H2-M02: preserve the canonical predicand wire contract in projection."""
import copy
import unittest

from scripts.authoritative_payload import AuthoritativePayloadState, authoritative_payload
from scripts.canonical_schema import canonical_schema_issues
from scripts.coverage_resolution import CoverageState, resolve_coverage, resolve_scoring_eligibility
from scripts.render_sft import LINGUISTIC_NESTED_FIELDS, _without_governance, linguistic_projection
from scripts.validate_dataset import _validate_rendered_references, validate_record
from tests.test_authoritative_payload import FIXTURE, declaration


def predicand_record(predicand, completeness="complete"):
    record = copy.deepcopy(FIXTURE)
    record["annotation_scope"] = {
        "coverage": "task_focused_partial",
        "dimensions": [declaration("clause_structure", {"kind": "record"}, completeness)],
    }
    record["clauses"][0]["predicand"] = copy.deepcopy(predicand)
    return record


class PredicandProjectionTests(unittest.TestCase):
    def assert_preserved(self, record, location="m02-overt"):
        before = copy.deepcopy(record)
        self.assertEqual(canonical_schema_issues(record), [])
        self.assertEqual(validate_record(record, location), [])
        projection = linguistic_projection(record)
        clause = next(item for item in projection["clauses"] if item["id"] == "c0")
        self.assertEqual(clause["predicand"], before["clauses"][0]["predicand"])
        errors = []
        _validate_rendered_references(projection, "m02-rendered", errors)
        self.assertEqual(errors, [])
        self.assertEqual(record, before)
        return projection

    def test_original_overt_constituent(self):
        record = predicand_record({"kind": "overt_constituent", "target": "subj"})
        payload = authoritative_payload(record, "clause_structure")
        self.assertIs(payload.state, AuthoritativePayloadState.PRESENT)
        self.assertEqual((payload.applicable_count, payload.resolved_count,
                          payload.unresolved_count, payload.missing_count), (1, 1, 0, 0))
        self.assertTrue(payload.fully_resolved)
        self.assertIs(resolve_coverage(record, "clause_structure"), CoverageState.COMPLETE)
        self.assertTrue(resolve_scoring_eligibility(record, "clause_structure").scoreable)
        self.assert_preserved(record)

    def test_basis_and_note(self):
        self.assert_preserved(predicand_record({
            "kind": "overt_constituent", "target": "subj",
            "basis": "explicit predicative relation", "note": "test note",
        }))

    def test_all_structured_kinds(self):
        for kind in ("overt_constituent", "implicit_control", "discourse_inferred", "generic", "indeterminate"):
            with self.subTest(kind=kind):
                predicand = {"kind": kind}
                if kind in {"overt_constituent", "implicit_control"}:
                    predicand["target"] = "subj"
                self.assert_preserved(predicand_record(predicand))

    def test_optional_supplied_target(self):
        self.assert_preserved(predicand_record({"kind": "discourse_inferred", "target": "subj"}))

    def test_string_and_null(self):
        for predicand in ("subj", None):
            with self.subTest(predicand=predicand):
                self.assert_preserved(predicand_record(predicand))

    def test_reference_shell(self):
        record = predicand_record({"kind": "overt_constituent", "target": "subj"})
        self.assertIs(resolve_coverage(record, "phrase_constituency", "subj"), CoverageState.UNANNOTATED)
        self.assertIs(resolve_coverage(record, "syntactic_function", "subj"), CoverageState.UNANNOTATED)
        baseline = linguistic_projection(predicand_record({"kind": "generic"}))
        self.assertNotIn("subj", [item["id"] for item in baseline.get("constituents", [])])
        projection = self.assert_preserved(record)
        shell = next(item for item in projection["constituents"] if item["id"] == "subj")
        source = next(item for item in record["constituents"] if item["id"] == "subj")
        self.assertEqual(shell, {key: source[key] for key in ("id", "node_kind", "span")})

    def test_invalid_controls(self):
        for predicand, message in (
            ({"kind": "overt_constituent", "target": "ghost"}, "require a known target"),
            ({"kind": "invalid-kind"}, "predicand kind is invalid"),
        ):
            with self.subTest(predicand=predicand):
                record = predicand_record(predicand)
                self.assertTrue(any(message in error for error in validate_record(record, "m02-invalid")))
                self.assertFalse(authoritative_payload(record, "clause_structure").fully_resolved)
                self.assertFalse(resolve_scoring_eligibility(record, "clause_structure").scoreable)
                self.assertEqual(_without_governance(predicand, "predicand"), predicand)

    def test_clause_siblings(self):
        record = predicand_record({"kind": "overt_constituent", "target": "subj"})
        record["clauses"][0].update(subject="subj", head="w2", marker_ids=[], integration_parent=None)
        projection = self.assert_preserved(record)
        clause = next(item for item in projection["clauses"] if item["id"] == "c0")
        for key in ("id", "node_kind", "span", "finiteness", "clause_construction", "integration",
                    "subject", "predicand", "head", "marker_ids", "integration_parent"):
            self.assertEqual(clause[key], record["clauses"][0][key])

    def test_partial_covered_clause(self):
        record = predicand_record({"kind": "overt_constituent", "target": "subj"}, "partial")
        self.assertIs(resolve_coverage(record, "clause_structure", "c0"), CoverageState.PARTIAL_COVERED)
        self.assertTrue(resolve_scoring_eligibility(record, "clause_structure", "c0").scoreable)
        self.assert_preserved(record)

    def test_recursive_context_and_explicit_allowlist(self):
        predicand = {"kind": "overt_constituent", "target": "subj", "basis": "explicit", "note": "test note"}
        self.assertEqual(LINGUISTIC_NESTED_FIELDS["predicand"], set(predicand))
        self.assertTrue(set(predicand).isdisjoint(LINGUISTIC_NESTED_FIELDS["clause"]))
        clause = predicand_record(predicand)["clauses"][0]
        self.assertEqual(_without_governance([clause], "clauses")[0]["predicand"], predicand)
        extra = dict(predicand, status="established", review_required=True, framework="cgel_inspired",
                     role="Theme", function="subject", category="NP")
        self.assertEqual(_without_governance(extra, "predicand"), predicand)

    def test_typed_note_stripping_and_target_unchanged(self):
        for context in ("typed_analysis", "typed_relation"):
            with self.subTest(context=context):
                self.assertEqual(_without_governance({"note": "governance", "notes": "governance"}, context), {})
        target = {"namespace": "constituent", "id": "subj"}
        self.assertEqual(_without_governance({"target": target}, "typed_relation"), {"target": target})


if __name__ == "__main__":
    unittest.main()
