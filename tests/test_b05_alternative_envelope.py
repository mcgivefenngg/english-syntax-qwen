"""Public-path regressions for alternative envelope authority (H2-B05)."""
import copy
import json
import unittest

from tests.test_authoritative_payload import FIXTURE, declaration, with_declaration, typed_relation
from scripts.authoritative_payload import authoritative_payload, authoritative_payload_items, AuthoritativePayloadState
from scripts.canonical_schema import canonical_schema_issues
from scripts.coverage_resolution import CoverageResolutionError, resolve_coverage, resolve_scoring_eligibility
from scripts.render_sft import linguistic_projection, governance_sidecar
from scripts.validate_dataset import validate_record


def record_with_alternative(outer="established", inner="established", framework="cgel_inspired", relation_type="construction"):
    record = with_declaration(FIXTURE, declaration("construction_relations", {"kind": "record"}))
    record["construction_type"] = "transitive"
    record["canonical_analysis"]["typed_analysis"]["status"] = "descriptive"
    record["alternative_analyses"] = [{
        "id": "alt-b05", "framework": framework, "status": outer,
        "linked_constituent_ids": ["obj"],
        "linked_clause_refs": ["c1"],
        "linked_relation_ids": ["rel-" + relation_type],
        "typed_analysis": {
            "kind": "construction", "framework": "cgel_inspired", "status": inner,
            "relations": [typed_relation(relation_type)],
        },
    }]
    # Use actual fixture clause references.
    record["alternative_analyses"][0]["linked_clause_refs"] = [record["clauses"][0]["id"]]
    return record


class AlternativeEnvelopeTests(unittest.TestCase):
    def check_case(self, outer, inner, framework, expected):
        record = record_with_alternative(outer, inner, framework)
        self.assertFalse(canonical_schema_issues(record))
        errors = validate_record(record, "b05")
        mismatch = outer != inner or framework != "cgel_inspired"
        if mismatch:
            field = "status" if outer != inner else "framework"
            self.assertTrue(any(f"alternative {field} must agree with typed_analysis.{field}" in e for e in errors), errors)
        elif expected == "resolved":
            self.assertEqual(errors, [])
        else:
            self.assertFalse(any("alternative" in e for e in errors), errors)
        items = authoritative_payload_items(record, "construction_relations")
        relation = next(i for i in items if i.identifier == "rel-construction")
        self.assertEqual(relation.status, expected)
        payload = authoritative_payload(record, "construction_relations")
        self.assertEqual(payload.state, AuthoritativePayloadState.PRESENT)
        self.assertGreater(payload.resolved_count, 0)
        self.assertEqual(payload.fully_resolved, expected == "resolved")
        self.assertEqual(resolve_scoring_eligibility(record, "construction_relations").scoreable, expected == "resolved")
        if expected == "resolved":
            self.assertIsNotNone(resolve_coverage(record, "construction_relations"))
        else:
            with self.assertRaises(CoverageResolutionError):
                resolve_coverage(record, "construction_relations")
        if expected == "missing":
            self.assertGreater(payload.missing_count, 0)
            self.assertEqual(payload.unresolved_count, 0)
        if expected == "unresolved":
            self.assertGreater(payload.unresolved_count, 0)
            self.assertEqual(payload.missing_count, 0)
        projection = linguistic_projection(record)
        self.assertEqual(projection.get("construction_type"), "transitive")
        self.assertEqual(bool(projection.get("alternative_analyses")), expected == "resolved")
        if expected != "resolved":
            self.assertNotIn("rel-construction", json.dumps(projection))
        flags = governance_sidecar(record)["content_flags"]
        if outer in {"unresolved", "review_required"}:
            self.assertEqual(flags, ["alternative_analyses[0]"])
        elif inner in {"unresolved", "review_required"}:
            self.assertEqual(flags, ["alternative_analyses[0].typed_analysis"])
        else:
            self.assertEqual(flags, [])
        return record

    def test_status_mismatch(self):
        for outer in ("unresolved", "review_required"):
            with self.subTest(outer=outer):
                self.check_case(outer, "established", "cgel_inspired", "missing")

    def test_framework_mismatch(self):
        self.check_case("established", "established", "universal_dependencies", "missing")

    def test_reverse_status_mismatch(self):
        for inner in ("unresolved", "review_required"):
            with self.subTest(inner=inner):
                self.check_case("established", inner, "cgel_inspired", "missing")

    def test_coherent_nonpositive(self):
        for status in ("unresolved", "review_required"):
            with self.subTest(status=status):
                record = self.check_case(status, status, "cgel_inspired", "unresolved")
                del record["construction_type"]
                self.assertEqual(authoritative_payload(record, "construction_relations").state, AuthoritativePayloadState.UNRESOLVED_ONLY)

    def test_established_control(self):
        self.check_case("established", "established", "cgel_inspired", "resolved")

    def test_sibling_isolation(self):
        record = record_with_alternative()
        bad = copy.deepcopy(record["alternative_analyses"][0])
        bad["id"] = "alt-bad"
        bad["status"] = "unresolved"
        bad["typed_analysis"]["relations"][0]["id"] = "rel-bad"
        bad["linked_relation_ids"] = ["rel-bad"]
        record["alternative_analyses"].append(bad)
        projection = linguistic_projection(record)
        self.assertEqual([a["id"] for a in projection["alternative_analyses"]], ["alt-b05"])
        self.assertNotIn("rel-bad", json.dumps(projection))

    def test_cross_dimension_selection(self):
        record = record_with_alternative("unresolved", relation_type="selection")
        record = with_declaration(record, declaration("vp_complementation", {"kind": "record"}))
        valid = copy.deepcopy(record["alternative_analyses"][0])
        valid["id"] = "alt-valid-selection"
        valid["status"] = "established"
        valid["typed_analysis"]["relations"][0]["id"] = "rel-valid-selection"
        valid["linked_relation_ids"] = ["rel-valid-selection"]
        record["alternative_analyses"].append(valid)
        before = copy.deepcopy(record)
        before["alternative_analyses"] = [valid]
        baseline = authoritative_payload(before, "vp_complementation")
        payload = authoritative_payload(record, "vp_complementation")
        self.assertIn("rel-valid-selection", baseline.resolved_ids)
        self.assertIn("rel-valid-selection", payload.resolved_ids)
        self.assertNotIn("rel-selection", payload.resolved_ids)
        self.assertEqual(payload.resolved_count, baseline.resolved_count)
        self.assertGreater(payload.missing_count, baseline.missing_count)
        self.assertFalse(payload.fully_resolved)
        self.assertFalse(resolve_scoring_eligibility(record, "vp_complementation").scoreable)
        self.assertNotIn("rel-selection", json.dumps(linguistic_projection(record)))

    def test_entities_arguments_and_structural_precedence(self):
        for status, expected in (("established", "missing"), ("unresolved", "unresolved")):
            record = record_with_alternative("unresolved", status)
            typed = record["alternative_analyses"][0]["typed_analysis"]
            typed["entities"] = [{"id": "entity-b05", "kind": "construction"}]
            typed["arguments"] = {"custom": {"kind": "construction", "status": "established"}}
            items = authoritative_payload_items(record, "construction_relations")
            self.assertTrue(any(i.field == "typed_entity" for i in items))
            self.assertTrue(any(i.field == "typed_arguments" for i in items))
            self.assertTrue(all(i.status == expected for i in items if i.path[0] == "alternative_analyses"))
            typed["relations"][0]["target"] = "analysis:unknown"
            relation = next(i for i in authoritative_payload_items(record, "construction_relations") if i.field == "typed_relation")
            self.assertEqual(relation.status, "missing")

    def test_nonpositive_is_never_confirmed_empty(self):
        for inner in ("established", "unresolved", "review_required"):
            record = record_with_alternative("unresolved", inner)
            del record["construction_type"]
            record = with_declaration(record, declaration(
                "construction_relations", {"kind": "record"}, evidence="empty",
            ))
            payload = authoritative_payload(record, "construction_relations")
            self.assertNotEqual(payload.state, AuthoritativePayloadState.CONFIRMED_EMPTY)
            self.assertFalse(resolve_scoring_eligibility(record, "construction_relations").scoreable)
