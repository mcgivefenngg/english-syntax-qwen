import copy
import unittest

from scripts.authoritative_payload import authoritative_payload, authoritative_payload_items
from scripts.canonical_schema import canonical_schema_issues
from scripts.coverage_resolution import resolve_scoring_eligibility
from scripts.render_sft import linguistic_projection
from scripts.validate_dataset import validate_record
from tests.test_authoritative_payload import FIXTURE, declaration


class B07FusionRelationsTests(unittest.TestCase):
    def base(self, completeness="complete"):
        record = copy.deepcopy(FIXTURE)
        record["annotation_scope"]["dimensions"] = [
            declaration("construction_relations", {"kind": "record"}, completeness=completeness),
        ]
        record["fusion_relations"] = [{
            "id": "f1", "type": "fused_relative", "fused_element": "w0",
            "whole_constituent": "obj", "relative_clause": "c0",
            "fused_functions": ["head", "relative"],
        }]
        return record

    def assert_parity(self, record, statuses, *, schema_valid=True):
        before = copy.deepcopy(record)
        if schema_valid:
            self.assertEqual(canonical_schema_issues(record), [])
        errors = validate_record(record, "b07-fusion")
        self.assertEqual(bool(errors), "missing" in statuses, errors)
        payload = authoritative_payload(record, "construction_relations")
        items = [item for item in authoritative_payload_items(record, "construction_relations") if item.field == "fusion_relations"]
        self.assertEqual([item.status for item in items], statuses)
        expected = []
        for index, status in enumerate(statuses):
            self.assertEqual(f"fusion_relations[{index}]" in payload.resolved_ids, status == "resolved")
            if status == "resolved":
                value = copy.deepcopy(record["fusion_relations"][index])
                value.pop("id")
                expected.append(value)
        self.assertEqual(payload.fully_resolved, "missing" not in statuses)
        if "missing" in statuses:
            self.assertGreater(payload.missing_count, 0)
            if record["annotation_scope"]["dimensions"][0]["completeness"] == "complete":
                self.assertFalse(resolve_scoring_eligibility(record, "construction_relations").scoreable)
        if "resolved" in statuses:
            self.assertGreater(payload.resolved_count, 0)
        projection = linguistic_projection(record)
        self.assertEqual(projection.get("fusion_relations", []), expected)
        self.assertEqual(record, before)
        return projection

    def test_valid_control(self):
        for whole in ("obj", "c0"):
            record = self.base()
            record["fusion_relations"][0]["whole_constituent"] = whole
            self.assert_parity(record, ["resolved"])

    def test_semantic_invalidity_complete_and_partial(self):
        for completeness in ("complete", "partial"):
            for field, value in (
                ("fused_element", "obj"), ("whole_constituent", "w0"),
                ("relative_clause", "ghost"), ("relative_clause", "obj"),
                ("dependency", {"head": "ghost", "dependent": "obj", "relation": "head"}),
                ("dependency", {"head": "w0", "dependent": "ghost", "relation": "head"}),
                ("dependency", {"head": "w0", "dependent": "obj", "relation": ""}),
            ):
                with self.subTest(completeness=completeness, field=field, value=value):
                    record = self.base(completeness)
                    record["fusion_relations"][0][field] = value
                    projection = self.assert_parity(record, ["missing"])
                    empty = copy.deepcopy(record)
                    empty.pop("fusion_relations")
                    self.assertEqual(projection, linguistic_projection(empty))

    def test_valid_nested_dependency(self):
        for head in ("w0", "obj", "c0"):
            for dependent in ("w1", "subj", "c0"):
                record = self.base()
                record["fusion_relations"][0]["dependency"] = {"head": head, "dependent": dependent, "relation": "head"}
                self.assert_parity(record, ["resolved"])

    def test_duplicate_ids(self):
        record = self.base()
        record["fusion_relations"].append(copy.deepcopy(record["fusion_relations"][0]))
        self.assert_parity(record, ["missing", "missing"])

    def test_valid_sibling_isolation(self):
        for completeness in ("complete", "partial"):
            record = self.base(completeness)
            invalid = copy.deepcopy(record["fusion_relations"][0])
            invalid.update(id="f2", fused_element="obj")
            record["fusion_relations"].append(invalid)
            self.assert_parity(record, ["resolved", "missing"])

    def test_duplicate_conflict_isolation(self):
        record = self.base()
        duplicate = copy.deepcopy(record["fusion_relations"][0])
        duplicate["id"] = "dup"
        record["fusion_relations"].extend([duplicate, copy.deepcopy(duplicate)])
        self.assert_parity(record, ["resolved", "missing", "missing"])

    def test_partial_valid(self):
        self.assert_parity(self.base("partial"), ["resolved"])

    def test_malformed_items(self):
        for value in (None, "fusion", {}, {"dependency": []}):
            record = self.base()
            record["fusion_relations"] = [value]
            self.assert_parity(record, ["missing"], schema_valid=False)

    def test_malformed_nested_dependency(self):
        for dependency in ([], "dependency", {"head": "w0", "dependent": "obj"}):
            record = self.base()
            record["fusion_relations"][0]["dependency"] = dependency
            self.assert_parity(record, ["missing"], schema_valid=False)


if __name__ == "__main__":
    unittest.main()
