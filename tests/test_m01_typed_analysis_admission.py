"""H2-M01: typed authority must admit its analysis without unrelated coverage.

The historical canonical A6 partial-present case lost its sole dependency
until lexical coverage was added. The alternative case lost its dependency
without construction coverage. Keep both reproductions independent of B05/B06
helpers, and ensure admission follows their envelope and ownership gates.
"""
import copy
import unittest

from scripts.authoritative_payload import AuthoritativePayloadState, authoritative_payload
from scripts.canonical_schema import canonical_schema_issues
from scripts.coverage_resolution import CoverageState, resolve_coverage, resolve_scoring_eligibility
from scripts.render_sft import linguistic_projection
from scripts.validate_dataset import validate_record
from tests.test_authoritative_payload import FIXTURE, declaration, typed_relation


CONSTRUCTION_FIELDS = (
    "construction_type", "construction_signature", "heads", "complements",
    "adjuncts", "fusion_relations",
)


def admission_record(kind="dependency", completeness="partial", alternative=False):
    record = copy.deepcopy(FIXTURE)
    owner = "dependencies" if kind == "dependency" else "construction_relations"
    record["annotation_scope"] = {
        "coverage": "task_focused_partial",
        "dimensions": [declaration(owner, {"kind": "record"}, completeness)],
    }
    record["dependencies"] = []
    for field in CONSTRUCTION_FIELDS:
        record.pop(field, None)
    typed = {
        "kind": "record_level_analysis", "framework": "cgel_inspired",
        "status": "established", "relations": [typed_relation(kind)],
    }
    record["canonical_analysis"]["typed_analysis"] = typed
    record.pop("alternative_analyses", None)
    if alternative:
        record["alternative_analyses"] = [{
            "id": "alt-m01", "framework": "cgel_inspired", "status": "established",
            "linked_constituent_ids": ["obj"],
            "linked_clause_refs": [record["clauses"][0]["id"]],
            "linked_relation_ids": [typed["relations"][0]["id"]],
            "typed_analysis": copy.deepcopy(typed),
        }]
        typed["relations"] = []
    return record


def projected_relations(projection, alternative=False):
    analyses = (projection.get("alternative_analyses", []) if alternative
                else [projection.get("canonical_analysis", {})])
    return [relation for analysis in analyses
            for relation in analysis.get("typed_analysis", {}).get("relations", [])]


class TypedAnalysisAdmissionTests(unittest.TestCase):
    def assert_valid(self, record, location):
        self.assertEqual(canonical_schema_issues(record), [])
        self.assertEqual(validate_record(record, location), [])

    def assert_authority(self, record, owner, kind, coverage):
        payload = authoritative_payload(record, owner)
        self.assertIs(payload.state, AuthoritativePayloadState.PRESENT)
        self.assertEqual(payload.resolved_count, 1)
        self.assertEqual(payload.missing_count, 0)
        self.assertEqual(payload.unresolved_count, 0)
        self.assertTrue(payload.fully_resolved)
        self.assertIn("rel-" + kind, payload.resolved_ids)
        self.assertIs(resolve_coverage(record, owner), coverage)
        self.assertTrue(resolve_scoring_eligibility(record, owner).scoreable)

    def assert_unannotated(self, record, owner):
        self.assertIs(resolve_coverage(record, owner), CoverageState.UNANNOTATED)
        self.assertFalse(resolve_scoring_eligibility(record, owner).scoreable)

    def assert_retained(self, record, kind, alternative=False):
        self.assertEqual(record["dependencies"], [])
        projection = linguistic_projection(record)
        self.assertFalse(projection.get("dependencies"))
        self.assertEqual(projected_relations(projection, alternative), [typed_relation(kind)])
        if alternative:
            self.assertEqual([entry["id"] for entry in projection["alternative_analyses"]], ["alt-m01"])
        return projection

    def assert_no_analysis_shells(self, record):
        projection = linguistic_projection(record)
        for field in ("canonical_analysis", "preferred_analysis", "alternative_analyses"):
            self.assertNotIn(field, projection)

    def test_original_canonical_partial_dependency(self):
        record = admission_record()
        self.assertEqual(record["annotation_scope"]["dimensions"], [
            declaration("dependencies", {"kind": "record"}, "partial", "none", "present"),
        ])
        self.assert_valid(record, "m01-canonical-partial")
        self.assert_authority(record, "dependencies", "dependency", CoverageState.PARTIAL_COVERED)
        self.assert_retained(record, "dependency")

    def test_unrelated_lexical_coverage_invariance(self):
        baseline = admission_record()
        lexical = copy.deepcopy(baseline)
        lexical["annotation_scope"]["dimensions"].append(
            declaration("lexical_category", {"kind": "record"}))
        projections = []
        for record in (baseline, lexical):
            self.assert_valid(record, "m01-lexical-invariance")
            self.assert_authority(record, "dependencies", "dependency", CoverageState.PARTIAL_COVERED)
            projections.append(self.assert_retained(record, "dependency"))
        self.assertEqual(projected_relations(projections[0]), projected_relations(projections[1]))

    def test_construction_partial_without_independent_scalars(self):
        record = admission_record("construction")
        self.assertEqual(record["annotation_scope"]["dimensions"], [
            declaration("construction_relations", {"kind": "record"}, "partial", "none", "present"),
        ])
        for field in CONSTRUCTION_FIELDS:
            self.assertNotIn(field, record)
        self.assert_valid(record, "m01-construction-partial")
        self.assert_authority(record, "construction_relations", "construction", CoverageState.PARTIAL_COVERED)
        self.assert_retained(record, "construction")

    def test_original_alternative_dependency_without_construction_coverage(self):
        record = admission_record(completeness="complete", alternative=True)
        self.assertEqual(record["annotation_scope"]["dimensions"], [
            declaration("dependencies", {"kind": "record"}),
        ])
        self.assertEqual(record["canonical_analysis"]["typed_analysis"]["relations"], [])
        self.assert_valid(record, "m01-alternative-dependency")
        self.assert_authority(record, "dependencies", "dependency", CoverageState.COMPLETE)
        self.assert_unannotated(record, "construction_relations")
        self.assert_retained(record, "dependency", alternative=True)

    def test_alternative_construction_control(self):
        record = admission_record("construction", "complete", alternative=True)
        self.assert_valid(record, "m01-alternative-construction")
        self.assert_authority(record, "construction_relations", "construction", CoverageState.COMPLETE)
        self.assert_unannotated(record, "dependencies")
        self.assert_retained(record, "construction", alternative=True)

    def test_canonical_owner_negative_with_lexical_coverage(self):
        record = admission_record()
        record["annotation_scope"]["dimensions"] = [declaration("lexical_category", {"kind": "record"})]
        self.assert_valid(record, "m01-canonical-owner-negative")
        self.assert_unannotated(record, "dependencies")
        projection = linguistic_projection(record)
        self.assertTrue(any("lexical_category" in word for word in projection["words"]))
        self.assertEqual(projected_relations(projection), [])

    def test_alternative_owner_negative_with_construction_coverage(self):
        record = admission_record(completeness="complete", alternative=True)
        record["annotation_scope"]["dimensions"] = [declaration("construction_relations", {"kind": "record"})]
        record["construction_type"] = "transitive"
        self.assert_valid(record, "m01-alternative-owner-negative")
        self.assert_unannotated(record, "dependencies")
        projection = linguistic_projection(record)
        self.assertEqual(projection["construction_type"], "transitive")
        self.assertEqual(projected_relations(projection, alternative=True), [])

    def test_b05_nonpositive_alternative_envelopes_do_not_admit(self):
        for case in ("unresolved", "review_required", "status-mismatched", "framework-mismatched"):
            with self.subTest(case=case):
                record = admission_record(completeness="complete", alternative=True)
                alternative = record["alternative_analyses"][0]
                if case in ("unresolved", "review_required"):
                    alternative["status"] = case
                    alternative["typed_analysis"]["status"] = case
                elif case == "status-mismatched":
                    alternative["status"] = "unresolved"
                else:
                    alternative["framework"] = "universal_dependencies"
                self.assertEqual(canonical_schema_issues(record), [])
                self.assertTrue(validate_record(record, "m01-envelope-negative"))
                self.assertFalse(authoritative_payload(record, "dependencies").fully_resolved)
                self.assertFalse(resolve_scoring_eligibility(record, "dependencies").scoreable)
                self.assert_no_analysis_shells(record)

    def test_b06_rejected_relations_cannot_admit_empty_analysis(self):
        for alternative in (False, True):
            for case in ("dangling", "invalid-arity", "duplicate-id", "unowned-extension", "unresolved"):
                with self.subTest(alternative=alternative, case=case):
                    record = admission_record(alternative=alternative)
                    analysis = record["alternative_analyses"][0] if alternative else record["canonical_analysis"]
                    typed = analysis["typed_analysis"]
                    relation = typed["relations"][0]
                    if case == "dangling":
                        relation["target"] = "analysis:missing"
                    elif case == "invalid-arity":
                        relation["arity"] = "invalid"
                    elif case == "duplicate-id":
                        typed["relations"].append(copy.deepcopy(relation))
                    elif case == "unowned-extension":
                        relation["type"] = "pedagogical:object"
                    else:
                        typed["status"] = "unresolved"
                        if alternative:
                            analysis["status"] = "unresolved"
                    self.assertTrue(validate_record(record, "m01-rejected-relation"))
                    self.assertNotIn(relation["id"], authoritative_payload(record, "dependencies").resolved_ids)
                    self.assertFalse(resolve_scoring_eligibility(record, "dependencies").scoreable)
                    self.assert_no_analysis_shells(record)

    def test_established_envelope_alone_does_not_admit_empty_analysis(self):
        for alternative in (False, True):
            with self.subTest(alternative=alternative):
                record = admission_record(alternative=alternative)
                record["annotation_scope"]["dimensions"] = [declaration(
                    "dependencies", {"kind": "record"}, "partial", "intentional", "unannotated",
                )]
                analysis = record["alternative_analyses"][0] if alternative else record["canonical_analysis"]
                analysis["typed_analysis"]["relations"] = []
                analysis.pop("linked_relation_ids", None)
                self.assert_valid(record, "m01-empty-analysis")
                self.assert_no_analysis_shells(record)


if __name__ == "__main__":
    unittest.main()
