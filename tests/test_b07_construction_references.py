import copy
import unittest

from scripts.authoritative_payload import authoritative_payload, authoritative_payload_items
from scripts.canonical_schema import canonical_schema_issues
from scripts.coverage_resolution import CoverageResolutionError, CoverageState, resolve_coverage, resolve_scoring_eligibility
from scripts.render_sft import linguistic_projection
from scripts.validate_dataset import validate_record
from tests.test_authoritative_payload import FIXTURE, declaration


class B07ConstructionReferencesTests(unittest.TestCase):
    def base(self, completeness="complete"):
        record = copy.deepcopy(FIXTURE)
        record["annotation_scope"]["dimensions"] = [
            declaration("construction_relations", {"kind": "record"}, completeness=completeness),
        ]
        return record

    def assert_parity(self, record, expected_statuses, *, schema_valid=True):
        before = copy.deepcopy(record)
        if schema_valid:
            self.assertEqual(canonical_schema_issues(record), [])
        invalid = any("missing" in statuses for statuses in expected_statuses.values())
        errors = validate_record(record, "b07-references")
        self.assertEqual(bool(errors), invalid, errors)
        payload = authoritative_payload(record, "construction_relations")
        items = authoritative_payload_items(record, "construction_relations")
        projection = linguistic_projection(record)
        retained = copy.deepcopy(record)
        for field, statuses in expected_statuses.items():
            self.assertEqual([item.status for item in items if item.field == field], statuses)
            expected = []
            for index, status in enumerate(statuses):
                self.assertEqual(f"{field}[{index}]" in payload.resolved_ids, status == "resolved")
                if status == "resolved":
                    expected.append(record[field][index])
            self.assertEqual(projection.get(field, []), expected)
            if expected:
                retained[field] = expected
            else:
                retained.pop(field)
            if "missing" in statuses and field in {"complements", "adjuncts"}:
                self.assertTrue(any(f"{field} must be a list of constituent/clause IDs" in error for error in errors), errors)
        self.assertEqual(projection, linguistic_projection(retained))
        self.assertEqual(payload.fully_resolved, not invalid)
        try:
            state = resolve_coverage(record, "construction_relations")
        except CoverageResolutionError:
            self.assertTrue(invalid)
            state = None
        self.assertNotEqual(state, CoverageState.CONFIRMED_EMPTY)
        if invalid:
            self.assertGreater(payload.missing_count, 0)
            if record["annotation_scope"]["dimensions"][0]["completeness"] == "complete":
                self.assertFalse(resolve_scoring_eligibility(record, "construction_relations").scoreable)
        if any("resolved" in statuses for statuses in expected_statuses.values()):
            self.assertGreater(payload.resolved_count, 0)
        if not invalid:
            expected_state = CoverageState.COMPLETE if record["annotation_scope"]["dimensions"][0]["completeness"] == "complete" else CoverageState.PARTIAL_COVERED
            self.assertEqual(state, expected_state)
        self.assertEqual(record, before)
        return projection

    def test_valid_heads(self):
        for head in ("w0", "obj", "c0"):
            for dependent in ("w1", "subj", "c0"):
                with self.subTest(head=head, dependent=dependent):
                    record = self.base()
                    record["heads"] = [{"head": head, "dependent": dependent, "relation": "head"}]
                    self.assert_parity(record, {"heads": ["resolved"]})

    def test_dangling_heads_and_siblings(self):
        for completeness in ("complete", "partial"):
            for endpoint in ("head", "dependent"):
                for mixed in (False, True):
                    with self.subTest(completeness=completeness, endpoint=endpoint, mixed=mixed):
                        record = self.base(completeness)
                        valid = {"head": "w0", "dependent": "obj", "relation": "head"}
                        invalid = {"head": "w1", "dependent": "subj", "relation": "head", endpoint: "ghost"}
                        record["heads"] = ([valid] if mixed else []) + [invalid]
                        self.assert_parity(record, {"heads": (["resolved"] if mixed else []) + ["missing"]})

    def test_valid_complements_and_adjuncts(self):
        for field in ("complements", "adjuncts"):
            for reference in ("obj", "c0"):
                for completeness in ("complete", "partial"):
                    with self.subTest(field=field, reference=reference, completeness=completeness):
                        record = self.base(completeness)
                        record[field] = [reference]
                        self.assert_parity(record, {field: ["resolved"]})

    def test_wrong_kind_unknown_and_siblings(self):
        for field in ("complements", "adjuncts"):
            for reference in ("w0", "ghost"):
                for completeness in ("complete", "partial"):
                    for mixed in (False, True):
                        with self.subTest(field=field, reference=reference, completeness=completeness, mixed=mixed):
                            record = self.base(completeness)
                            record[field] = (["obj"] if mixed else []) + [reference]
                            self.assert_parity(record, {field: (["resolved"] if mixed else []) + ["missing"]})

    def test_cross_field_isolation(self):
        for completeness in ("complete", "partial"):
            record = self.base(completeness)
            record.update(construction_type="transitive", heads=[{"head": "w0", "dependent": "obj"}], complements=["w1"], adjuncts=["subj"])
            projection = self.assert_parity(record, {"heads": ["resolved"], "complements": ["missing"], "adjuncts": ["resolved"]})
            self.assertEqual(projection["construction_type"], "transitive")
            self.assertIn("construction_type", authoritative_payload(record, "construction_relations").resolved_ids)

    def test_head_reference_kind(self):
        for endpoint in ("head", "dependent"):
            record = self.base()
            record["words"][0]["node_kind"] = "invalid"
            record["heads"] = [{"head": "obj", "dependent": "subj", endpoint: "w0"}]
            self.assert_parity(record, {"heads": ["missing"]}, schema_valid=False)

    def test_malformed_items(self):
        for field in ("heads", "complements", "adjuncts"):
            for value in (None, {}, [], 1):
                with self.subTest(field=field, value=value):
                    record = self.base()
                    record[field] = [value]
                    self.assert_parity(record, {field: ["missing"]}, schema_valid=False)


if __name__ == "__main__":
    unittest.main()
