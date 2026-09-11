"""B06: registry relation ownership authorizes the public linguistic projection."""
import copy
import unittest
from dataclasses import replace
from unittest.mock import patch

from scripts import dimension_registry as registry
from scripts.authoritative_payload import authoritative_payload
from scripts.canonical_schema import canonical_schema_issues
from scripts.coverage_resolution import CoverageState, resolve_coverage, resolve_scoring_eligibility
from scripts.render_sft import linguistic_projection
from scripts.typed_relation_contract import (
    TypedRelationValidationContext, validate_typed_relation_structure, valid_analysis_entity_ids,
)
from scripts.validate_dataset import validate_record, _validate_rendered_references
from tests.test_authoritative_payload import FIXTURE, declaration

OWNERS = ('vp_complementation', 'construction_relations', 'dependencies')
TYPES = ('selection', 'construction', 'dependency', 'pedagogical:object')


def relation(kind, target='constituent:obj'):
    return dict(id=kind.replace(':', '-') + '1', type=kind, arity='binary',
                source='word:w2', target=target)


def record_with(owners, kinds=('selection',), *, entities=False):
    record = copy.deepcopy(FIXTURE)
    record['annotation_scope']['dimensions'] = [declaration(owner, {'kind': 'record'}) for owner in owners]
    record['construction_type'] = 'transitive'
    typed = record['canonical_analysis']['typed_analysis']
    typed['status'] = 'established'
    typed['relations'] = [relation(kind, 'analysis:e' + str(i) if entities else 'constituent:obj')
                          for i, kind in enumerate(kinds)]
    if entities:
        typed['entities'] = [dict(id='e' + str(i), kind='argument') for i in range(len(kinds))]
    return record


def projected_typed(record):
    return linguistic_projection(record).get('canonical_analysis', {}).get('typed_analysis', {})


class RegistryTypedRelationRenderingTests(unittest.TestCase):
    def assert_projection(self, record, expected):
        projection = linguistic_projection(record)
        typed = projection.get('canonical_analysis', {}).get('typed_analysis', {})
        relations = typed.get('relations', [])
        self.assertEqual({r['type'] for r in relations}, set(expected))
        self.assertEqual(len(relations), len(expected))
        errors = []
        _validate_rendered_references(projection, 'b06', errors)
        self.assertEqual(errors, [])
        return typed

    def test_original_reproduction(self):
        record = record_with(('construction_relations',))
        self.assertEqual(canonical_schema_issues(record), [])
        self.assertEqual(validate_record(record, 'b06-original'), [])
        self.assertIs(resolve_coverage(record, 'vp_complementation'), CoverageState.UNANNOTATED)
        self.assertIs(resolve_coverage(record, 'construction_relations'), CoverageState.COMPLETE)
        self.assertFalse(resolve_scoring_eligibility(record, 'vp_complementation').scoreable)
        self.assertTrue(resolve_scoring_eligibility(record, 'construction_relations').scoreable)
        self.assertEqual(linguistic_projection(record)['construction_type'], 'transitive')
        self.assert_projection(record, ())
        # The collector describes raw payload existence; scoring supplies coverage authorization.
        self.assertIn('selection1', authoritative_payload(record, 'vp_complementation').resolved_ids)
        self.assertNotIn('selection1', authoritative_payload(record, 'construction_relations').resolved_ids)

    def test_reverse_selection_and_both_covered(self):
        for owners in (('vp_complementation',), OWNERS[:2]):
            with self.subTest(owners=owners):
                record = record_with(owners)
                self.assertEqual(validate_record(record, 'b06-reverse'), [])
                typed = self.assert_projection(record, ('selection',))
                self.assertEqual(typed['relations'][0], relation('selection'))

    def test_dependency_and_construction_owner_matrix(self):
        for kind in ('dependency', 'construction'):
            for owner in OWNERS:
                with self.subTest(kind=kind, owner=owner):
                    record = record_with((owner,), (kind,))
                    expected = (kind,) if owner in registry.typed_relation_owner_dimensions(kind) else ()
                    self.assert_projection(record, expected)

    def test_extension_is_structurally_resolved_but_unowned(self):
        for entities in (False, True):
            record = record_with(('construction_relations',), ('pedagogical:object',), entities=entities)
            typed = record['canonical_analysis']['typed_analysis']
            self.assertEqual(validate_typed_relation_structure(
                typed['relations'][0], typed, record,
                context=TypedRelationValidationContext(valid_analysis_entity_ids=valid_analysis_entity_ids(typed)),
            ), 'resolved')
            self.assertEqual(canonical_schema_issues(record), [])
            self.assertEqual(validate_record(record, 'b06-extension'), [])
            self.assertEqual(registry.typed_relation_owner_dimensions('pedagogical:object'), frozenset())
            projected = self.assert_projection(record, ())
            self.assertNotIn('entities', projected)
            self.assertNotIn('constituents', linguistic_projection(record))
            for owner in OWNERS:
                self.assertNotIn('pedagogical-object1', authoritative_payload(record, owner).resolved_ids)

    def test_mixed_relations_and_analysis_local_entities(self):
        for entities in (False, True):
            for owners in [(owner,) for owner in OWNERS] + [OWNERS]:
                with self.subTest(entities=entities, owners=owners):
                    record = record_with(owners, TYPES, entities=entities)
                    expected = {kind for kind in TYPES if registry.typed_relation_owner_dimensions(kind).intersection(owners)}
                    typed = self.assert_projection(record, expected)
                    if entities:
                        self.assertEqual({e['id'] for e in typed['entities']},
                                         {'e' + str(i) for i, kind in enumerate(TYPES) if kind in expected})

    def test_registry_collector_renderer_parity_for_every_registered_type(self):
        relation_types = {kind for spec in registry.DIMENSION_REGISTRY.values()
                          for payload in spec.payloads if payload.field == 'typed_relation'
                          for kind in payload.relation_types}
        for kind in relation_types:
            expected_owners = {name for name, spec in registry.DIMENSION_REGISTRY.items()
                               for payload in spec.payloads
                               if payload.field == 'typed_relation' and kind in payload.relation_types}
            self.assertEqual(registry.typed_relation_owner_dimensions(kind), expected_owners)
            for owner in OWNERS:
                with self.subTest(kind=kind, owner=owner):
                    record = record_with((owner,), (kind,))
                    rel = record['canonical_analysis']['typed_analysis']['relations'][0]
                    rel['framework'] = 'cgel_inspired'
                    structural = validate_typed_relation_structure(rel, record['canonical_analysis']['typed_analysis'], record)
                    expected = owner in expected_owners and structural == 'resolved'
                    payload = authoritative_payload(record, owner)
                    self.assertEqual(rel['id'] in payload.resolved_ids, expected)
                    self.assert_projection(record, (kind,) if expected else ())

    def test_multi_owner_registry_requires_only_one_authorized_owner(self):
        spec = registry.DIMENSION_REGISTRY['construction_relations']
        spec = replace(spec, payloads=tuple(
            replace(p, relation_types=p.relation_types | {'selection'}) if p.field == 'typed_relation' else p
            for p in spec.payloads))
        dimensions = dict(registry.DIMENSION_REGISTRY, construction_relations=spec)
        with patch.object(registry, 'DIMENSION_REGISTRY', dimensions):
            self.assertEqual(registry.typed_relation_owner_dimensions('selection'), set(OWNERS[:2]))
            for owners in (('construction_relations',), ('vp_complementation',), OWNERS[:2]):
                self.assert_projection(record_with(owners), ('selection',))

    def test_argument_ownership_uses_live_property_sets(self):
        arguments = [{'target': 'constituent:obj'}, {'id': 'arg1', 'kind': 'argument', 'target': 'constituent:obj'}]
        for owner in OWNERS:
            for shape in ('list', 'object', 'mapping'):
                record = record_with((owner,), TYPES)
                value = arguments if shape == 'list' else arguments[1] if shape == 'object' else {'first': arguments[0], 'second': arguments[1]}
                record['canonical_analysis']['typed_analysis']['arguments'] = copy.deepcopy(value)
                typed = projected_typed(record)
                expected = [a for a in arguments if owner in registry.typed_argument_owner_dimensions(a)]
                if shape == 'list':
                    self.assertEqual(typed.get('arguments', []), expected)
                elif shape == 'object':
                    self.assertEqual(typed.get('arguments'), arguments[1] if arguments[1] in expected else None)
                else:
                    self.assertEqual(typed.get('arguments', {}), {k: a for k, a in value.items() if a in expected})

    def test_special_properties_remain_independently_filtered(self):
        for covered in (False, True):
            record = record_with(('vp_complementation',))
            typed = record['canonical_analysis']['typed_analysis']
            typed['arguments'] = {'target': 'constituent:obj', 'role': 'Theme', 'function': 'object', 'category': 'NP'}
            if covered:
                record['annotation_scope']['dimensions'] += [declaration(d, {'kind': 'record'})
                    for d in ('semantic_roles', 'syntactic_function', 'phrase_constituency')]
                record['semantic_roles'] = [{'constituent': 'obj', 'role': 'Theme', 'predicate': 'w2'}]
            projected = self.assert_projection(record, ('selection',))
            self.assertFalse({'role', 'function', 'category'}.intersection(projected['relations'][0]))
            for item in (projected['arguments'],):
                for prop in ('role', 'function', 'category'):
                    self.assertEqual(prop in item, covered or prop == 'function')
        record = record_with(('syntactic_function',), ('pedagogical:object',))
        record['canonical_analysis']['typed_analysis']['relations'][0]['function'] = 'object'
        self.assert_projection(record, ())

    def test_alternative_envelope_and_owner_both_required(self):
        for status in ('established', 'unresolved', 'invalid'):
            for owner in OWNERS[:2]:
                record = record_with((owner,))
                typed = record['canonical_analysis']['typed_analysis']
                record['alternative_analyses'] = [{'id': 'alt-b06', 'framework': 'cgel_inspired',
                    'status': status, 'typed_analysis': copy.deepcopy(typed)}]
                if status == 'unresolved':
                    record['alternative_analyses'][0]['typed_analysis']['status'] = status
                typed['relations'] = []
                alternatives = linguistic_projection(record).get('alternative_analyses', [])
                relations = [r for a in alternatives for r in a.get('typed_analysis', {}).get('relations', [])]
                self.assertEqual(len(relations), int(status == 'established' and owner == 'vp_complementation'))

    def test_structural_rejections_before_owner_routing(self):
        for mutation in ('dangling', 'target', 'arity', 'duplicate', 'duplicate_entity', 'preferred_dependency'):
            record = record_with(OWNERS)
            typed = record['canonical_analysis']['typed_analysis']
            rel = typed['relations'][0]
            if mutation == 'dangling':
                rel['target'] = 'analysis:missing'
            elif mutation == 'target':
                del rel['target']
            elif mutation == 'arity':
                rel['arity'] = 'invalid'
            elif mutation == 'duplicate':
                typed['relations'].append(copy.deepcopy(rel))
            elif mutation == 'duplicate_entity':
                typed['entities'] = [dict(id='e1', kind='argument')] * 2
                rel['target'] = 'analysis:e1'
            else:
                dep = {'head': 'w2', 'dependent': 'w1', 'relation': 'dep'}
                record['dependencies'] = [dep]
                rel.update(type='dependency', source='word:' + dep['head'], target='word:' + dep['dependent'])
            self.assert_projection(record, ())

    def test_scoped_selection_coverage(self):
        record = record_with(())
        record['annotation_scope']['dimensions'] = [declaration('vp_complementation', {'kind': 'node', 'node': 'obj'})]
        self.assert_projection(record, ('selection',))

    def test_canonical_reference_does_not_retain_same_named_entity(self):
        record = record_with(('vp_complementation',))
        record['canonical_analysis']['typed_analysis']['entities'] = [{'id': 'obj', 'kind': 'argument'}]
        self.assertNotIn('entities', self.assert_projection(record, ('selection',)))

    def test_a6_partial_present_and_a2_no_invented_empty(self):
        record = record_with(('dependencies',), ('dependency',))
        record['annotation_scope']['dimensions'][0]['completeness'] = 'partial'
        self.assertIs(resolve_coverage(record, 'dependencies'), CoverageState.PARTIAL_COVERED)
        self.assert_projection(record, ('dependency',))
        record = record_with(('construction_relations',), ('pedagogical:object',))
        for owner in ('vp_complementation', 'dependencies'):
            self.assertIs(resolve_coverage(record, owner), CoverageState.UNANNOTATED)
            self.assertFalse(resolve_scoring_eligibility(record, owner).scoreable)


if __name__ == '__main__':
    unittest.main()
