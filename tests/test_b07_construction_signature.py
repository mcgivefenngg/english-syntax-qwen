import copy
import unittest
from tests.test_authoritative_payload import FIXTURE, declaration
from scripts.canonical_schema import canonical_schema_issues
from scripts.validate_dataset import validate_record
from scripts.authoritative_payload import authoritative_payload
from scripts.render_sft import linguistic_projection
from scripts.coverage_resolution import resolve_scoring_eligibility

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

if __name__=='__main__': unittest.main()
