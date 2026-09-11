import copy
import unittest
from tests.test_authoritative_payload import FIXTURE, declaration
from scripts.canonical_schema import canonical_schema_issues
from scripts.validate_dataset import validate_record
from scripts.authoritative_payload import authoritative_payload, authoritative_payload_items
from scripts.collection_contract import normalize_predicate_reference
from scripts.construction_payload_contract import construction_signature_issues, construction_signature_status
from scripts.render_sft import linguistic_projection
from scripts.coverage_resolution import CoverageState, resolve_coverage, resolve_scoring_eligibility

class B07ConstructionSignatureTests(unittest.TestCase):
    def base(self):
        r=copy.deepcopy(FIXTURE); r['construction_type']='transitive'; r['construction_signature']={'predicate_lemma':'catalogue','construction_type':'transitive','argument_pattern':['NP'],'function_pattern':['object']}; r['annotation_scope']['dimensions']=[declaration('construction_relations', {'kind':'record'})]; return r
    def test_valid_and_local_id_patterns(self):
        r=self.base(); self.assertEqual(canonical_schema_issues(r),[]); self.assertEqual(validate_record(r,'b07'),[]); self.assertIn('construction_signature', linguistic_projection(r))
        for key in ('argument_pattern','function_pattern'):
            bad=copy.deepcopy(r); bad['construction_signature'][key]=['obj']; self.assertEqual(canonical_schema_issues(bad),[]); self.assertTrue(any('stable descriptors' in e for e in validate_record(bad,'b07'))); self.assertFalse(resolve_scoring_eligibility(bad,'construction_relations').scoreable); self.assertNotIn('construction_signature', linguistic_projection(bad))
    def test_mismatch_and_lexical_agreement(self):
        r=self.base(); r['construction_signature']['construction_type']='ditransitive'; self.assertTrue(validate_record(r,'b07')); self.assertNotIn('construction_signature', linguistic_projection(r)); self.assertEqual(r['construction_type'],'transitive')
        r=self.base(); r['lexical_valency']=[{'predicate':'w2','frame':'x'}]; r['construction_signature']['predicate_lemma']='other'; self.assertTrue(any('lexical_valency' in e for e in validate_record(r,'b07'))); self.assertNotIn('construction_signature', linguistic_projection(r))
    def test_authoritative_mixed_truthfulness(self):
        r=self.base(); r['construction_signature']['construction_type']='ditransitive'; p=authoritative_payload(r,'construction_relations'); self.assertIn('construction_type',p.resolved_ids); self.assertNotIn('construction_signature',p.resolved_ids); self.assertFalse(p.fully_resolved); self.assertNotIn('construction_signature',linguistic_projection(r))

    def test_valid_lexical_valency_agreement(self):
        record = self.base()
        record["lexical_valency"] = [{
            "predicate": "w2",
            "frame": "transitive",
            "selected_complements": ["obj"],
        }]
        signature = record["construction_signature"]
        self.assertEqual(signature["predicate_lemma"], "catalogue")
        self.assertEqual(normalize_predicate_reference(record, signature["predicate_lemma"]), "w2")
        self.assertEqual(normalize_predicate_reference(record, record["lexical_valency"][0]["predicate"]), "w2")
        self.assertEqual(canonical_schema_issues(record), [])
        self.assertEqual(validate_record(record, "b07-valid-valency"), [])
        self.assertIn("construction_signature", authoritative_payload(record, "construction_relations").resolved_ids)
        self.assertEqual(linguistic_projection(record)["construction_signature"], signature)

    def partial_record(self):
        record = self.base()
        record["annotation_scope"]["dimensions"] = [
            declaration(
                "construction_relations", {"kind": "record"},
                completeness="partial", evidence="present", omission="none",
            ),
        ]
        return record

    def test_partial_valid_signature(self):
        record = self.partial_record()
        self.assertEqual(canonical_schema_issues(record), [])
        self.assertEqual(validate_record(record, "b07-partial-valid"), [])
        self.assertIs(resolve_coverage(record, "construction_relations"), CoverageState.PARTIAL_COVERED)
        payload = authoritative_payload(record, "construction_relations")
        self.assertIn("construction_signature", payload.resolved_ids)
        self.assertTrue(payload.fully_resolved)
        items = authoritative_payload_items(record, "construction_relations")
        signature_items = [item for item in items if item.field == "construction_signature"]
        self.assertEqual([item.status for item in signature_items], ["resolved"])
        self.assertEqual(linguistic_projection(record)["construction_signature"], record["construction_signature"])

    def test_partial_invalid_signature_preserves_valid_sibling(self):
        for pattern in ("argument_pattern", "function_pattern"):
            with self.subTest(pattern=pattern):
                record = self.partial_record()
                self.assertIn("obj", {item["id"] for item in record["constituents"]})
                record["construction_signature"][pattern] = ["obj"]
                self.assertEqual(canonical_schema_issues(record), [])
                self.assertTrue(any(
                    "construction_signature patterns must use stable descriptors, not record-local IDs" in error
                    for error in validate_record(record, "b07-partial-invalid")
                ))
                self.assertIs(resolve_coverage(record, "construction_relations"), CoverageState.PARTIAL_COVERED)
                payload = authoritative_payload(record, "construction_relations")
                self.assertNotIn("construction_signature", payload.resolved_ids)
                self.assertIn("construction_type", payload.resolved_ids)
                self.assertGreater(payload.resolved_count, 0)
                self.assertGreater(payload.missing_count, 0)
                self.assertFalse(payload.fully_resolved)
                items = authoritative_payload_items(record, "construction_relations")
                signature_items = [item for item in items if item.field == "construction_signature"]
                self.assertEqual([item.status for item in signature_items], ["missing"])
                projection = linguistic_projection(record)
                self.assertNotIn("construction_signature", projection)
                self.assertEqual(projection["construction_type"], record["construction_type"])

    def test_shared_signature_contract_sanity(self):
        record = self.base()
        signature = record["construction_signature"]
        self.assertEqual(construction_signature_issues(record, signature), ())
        self.assertEqual(construction_signature_status(record, signature), "resolved")
        signature["argument_pattern"] = ["obj"]
        self.assertEqual(construction_signature_issues(record, signature), ("stable_descriptors",))
        self.assertEqual(construction_signature_status(record, signature), "missing")

if __name__=='__main__': unittest.main()
