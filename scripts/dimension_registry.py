"""Canonical V0.4 annotation-dimension and payload ownership registry."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


SCOPE_KINDS = frozenset({"record", "node", "region"})
EVIDENCE_MODES = frozenset({"present", "empty", "unannotated"})
NODE_KINDS = frozenset({"word", "phrase", "clause"})


@dataclass(frozen=True)
class PayloadSpec:
    """A canonical field/property projection owned by a dimension."""

    field: str
    properties: frozenset[str] = frozenset()
    relation_types: frozenset[str] = frozenset()


@dataclass(frozen=True)
class DimensionSpec:
    """Machine-relevant coverage and payload capabilities for one dimension."""

    name: str
    allowed_scope_kinds: frozenset[str]
    allowed_node_kinds: frozenset[str]
    allowed_evidence_modes: frozenset[str]
    confirmed_empty_scope_kinds: frozenset[str]
    partial_scope_kinds: frozenset[str]
    partial_present_target_source: str | None
    payload_family: str
    collection_like: bool
    payloads: tuple[PayloadSpec, ...]
    requires_payload_field: bool = True
    content_field: str | None = None
    target_fields: tuple[str, ...] = ()
    target_lemma_field: str | None = None
    target_owner: str | None = None

    @property
    def fields(self) -> frozenset[str]:
        return frozenset(payload.field for payload in self.payloads)

    @property
    def primary_field(self) -> str | None:
        return self.payloads[0].field if self.payloads else None

    @property
    def property_map(self) -> Mapping[str, frozenset[str]]:
        return MappingProxyType({payload.field: payload.properties for payload in self.payloads})

    def allows_scope(self, scope_kind: str) -> bool:
        return scope_kind in self.allowed_scope_kinds

    def allows_node(self, node_kind: str) -> bool:
        return node_kind in self.allowed_node_kinds

    def allows_partial(self, scope_kind: str) -> bool:
        return scope_kind in self.partial_scope_kinds

    def allows_confirmed_empty(self, scope_kind: str) -> bool:
        return scope_kind in self.confirmed_empty_scope_kinds


def _payload(
    field: str,
    *properties: str,
    relation_types: set[str] | frozenset[str] = frozenset(),
) -> PayloadSpec:
    return PayloadSpec(field, frozenset(properties), frozenset(relation_types))


def _spec(
    name: str,
    *,
    scopes: set[str],
    nodes: set[str] | None = None,
    evidence: set[str],
    empty_scopes: set[str],
    partial_scopes: set[str] | None = None,
    partial_present_target_source: str | None,
    payload_family: str,
    collection_like: bool,
    payloads: tuple[PayloadSpec, ...],
    requires_payload_field: bool = True,
    content_field: str | None = None,
    target_fields: tuple[str, ...] = (),
    target_lemma_field: str | None = None,
    target_owner: str | None = None,
) -> DimensionSpec:
    return DimensionSpec(
        name=name,
        allowed_scope_kinds=frozenset(scopes),
        allowed_node_kinds=frozenset(nodes or set()),
        allowed_evidence_modes=frozenset(evidence),
        confirmed_empty_scope_kinds=frozenset(empty_scopes),
        partial_scope_kinds=frozenset(partial_scopes if partial_scopes is not None else scopes),
        partial_present_target_source=partial_present_target_source,
        payload_family=payload_family,
        collection_like=collection_like,
        payloads=payloads,
        requires_payload_field=requires_payload_field,
        content_field=content_field,
        target_fields=target_fields,
        target_lemma_field=target_lemma_field,
        target_owner=target_owner,
    )


_DIMENSIONS = {
    "tokens": _spec(
        "tokens", scopes={"record"}, evidence={"present", "unannotated"}, empty_scopes=set(),
        partial_present_target_source="item_ids", payload_family="word_collection", collection_like=True,
        payloads=(_payload("words", "id", "node_kind", "form", "lemma"),), target_fields=("id",),
    ),
    "lexical_category": _spec(
        "lexical_category", scopes={"record", "node"}, nodes={"word"},
        evidence={"present", "unannotated"}, empty_scopes=set(),
        partial_present_target_source="item_ids", payload_family="word_scalar_properties", collection_like=False,
        payloads=(
            _payload("words", "lexical_category", "external_pos_tags"),
            _payload("typed_arguments", "category"),
            _payload("typed_relation", "category"),
        ), target_fields=("id",), target_owner="canonical_word",
    ),
    "phrase_constituency": _spec(
        "phrase_constituency", scopes={"record", "node", "region"}, nodes={"phrase", "clause"},
        evidence={"present", "empty", "unannotated"}, empty_scopes={"record"},
        partial_present_target_source="item_ids", payload_family="constituent_collection", collection_like=True,
        payloads=(
            _payload("constituents", "id", "node_kind", "span", "phrase_category", "head", "parent", "relation_label", "span_relation"),
            _payload("typed_arguments", "category"),
            _payload("typed_relation", "category"),
        ), content_field="constituents", target_fields=("id",),
    ),
    "constituency": _spec(
        "constituency", scopes={"record", "node", "region"}, nodes={"phrase", "clause"},
        evidence={"present", "empty", "unannotated"}, empty_scopes={"record"},
        partial_present_target_source="item_ids", payload_family="constituent_collection", collection_like=True,
        payloads=(
            _payload("constituents", "id", "node_kind", "span", "phrase_category", "head", "parent", "relation_label", "span_relation"),
            _payload("typed_arguments", "category"),
            _payload("typed_relation", "category"),
        ), content_field="constituents", target_fields=("id",),
    ),
    "np_internal_constituency": _spec(
        "np_internal_constituency", scopes={"record", "node", "region"}, nodes={"phrase"},
        evidence={"present", "unannotated"}, empty_scopes=set(),
        partial_present_target_source="item_ids", payload_family="constituent_collection", collection_like=True,
        payloads=(
            _payload("constituents", "id", "node_kind", "span", "phrase_category", "head", "parent", "relation_label", "span_relation"),
            _payload("typed_arguments", "category"),
            _payload("typed_relation", "category"),
        ), target_fields=("id",), target_owner="np_phrase",
    ),
    "clause_ontology": _spec(
        "clause_ontology", scopes={"record", "node"}, nodes={"clause"},
        evidence={"present", "empty", "unannotated"}, empty_scopes={"record"},
        partial_present_target_source="item_ids", payload_family="clause_collection", collection_like=True,
        payloads=(_payload("clauses", "id", "node_kind", "span", "finiteness", "clause_form", "clause_construction", "integration", "subject", "predicand", "head", "marker_ids", "integration_parent"),), content_field="clauses", target_fields=("id",), target_owner="canonical_clause",
    ),
    "clause_structure": _spec(
        "clause_structure", scopes={"record", "node"}, nodes={"clause"},
        evidence={"present", "empty", "unannotated"}, empty_scopes={"record"},
        partial_present_target_source="item_ids", payload_family="clause_collection", collection_like=True,
        payloads=(_payload("clauses", "id", "node_kind", "span", "finiteness", "clause_form", "clause_construction", "integration", "subject", "predicand", "head", "marker_ids", "integration_parent"),), content_field="clauses", target_fields=("id",), target_owner="canonical_clause",
    ),
    "syntactic_function": _spec(
        "syntactic_function", scopes={"record", "node", "region"}, nodes=set(NODE_KINDS),
        evidence={"present", "unannotated"}, empty_scopes=set(),
        partial_present_target_source="item_ids", payload_family="node_scalar_properties", collection_like=False,
        payloads=(
            _payload("constituents", "id", "node_kind", "span", "function", "clause_ref", "realization"),
            _payload("words", "id", "node_kind", "syntactic_function"),
            _payload("typed_arguments", "function"),
            _payload("typed_relation", "function"),
            _payload("complements", "value"),
            _payload("adjuncts", "value"),
        ), target_fields=("id",),
    ),
    "vp_complementation": _spec(
        "vp_complementation", scopes={"record", "node", "region"}, nodes={"phrase", "clause"},
        evidence={"present", "unannotated"}, empty_scopes=set(),
        partial_present_target_source=None, payload_family="complementation_collection", collection_like=True,
        payloads=(
            _payload("constituents", "id", "node_kind", "span", "function", "clause_ref", "realization", "head", "parent"),
            _payload("lexical_valency", "predicate", "frame", "selected_complements"),
            _payload("typed_arguments", "target", "source", "head", "dependent", "relation", "span", "clause_ref", "constituent_ref", "word_ref", "predicate", "value", "label"),
            _payload("typed_relation", "target", "source", "head", "dependent", "relation", "span", "clause_ref", "constituent_ref", "word_ref", "predicate", "value", "label", relation_types={"selection"}),
            _payload("complements", "value"),
            _payload("adjuncts", "value"),
        ), target_fields=("id",),
    ),
    "dependencies": _spec(
        "dependencies", scopes={"record"}, evidence={"present", "empty", "unannotated"}, empty_scopes={"record"},
        partial_present_target_source="record", payload_family="dependency_collection", collection_like=True,
        payloads=(
            _payload("dependencies", "relation", "head", "dependent"),
            _payload("typed_analysis", "kind", "framework", "arguments", "entities", "relations"),
            _payload("typed_arguments", "id", "kind", "type", "target", "source", "head", "dependent", "relation", "span", "clause_ref", "constituent_ref", "word_ref", "predicate", "value", "label"),
            _payload("typed_entity", "id", "kind"),
            _payload("typed_relation", "id", "kind", "type", "arity", "source", "target", "namespace", "framework", "head", "dependent", "relation", relation_types={"dependency"}),
        ), content_field="dependencies", target_fields=("head", "dependent"),
    ),
    "semantic_roles": _spec(
        "semantic_roles", scopes={"record"}, evidence={"present", "empty", "unannotated"}, empty_scopes={"record"},
        partial_present_target_source="record", payload_family="semantic_role_collection", collection_like=True,
        payloads=(
            _payload("semantic_roles", "constituent", "role", "predicate"),
            _payload("typed_arguments", "role"),
            _payload("typed_relation", "role"),
        ), content_field="semantic_roles", target_fields=("constituent", "predicate"), target_lemma_field="predicate",
    ),
    "lexical_valency": _spec(
        "lexical_valency", scopes={"record", "node"}, nodes={"word"},
        evidence={"present", "empty", "unannotated"}, empty_scopes={"record"},
        partial_present_target_source="predicate_ids", payload_family="valency_collection", collection_like=True,
        payloads=(_payload("lexical_valency", "predicate", "frame", "selected_complements"),), content_field="lexical_valency", target_fields=("predicate",), target_lemma_field="predicate", target_owner="lexical_head_word",
    ),
    "framework_mapping": _spec(
        "framework_mapping", scopes={"record"}, evidence={"present", "unannotated"}, empty_scopes=set(),
        partial_present_target_source="record", payload_family="framework_scalar", collection_like=False,
        payloads=(_payload("framework", "preferred", "notes"),),
    ),
    "construction_relations": _spec(
        "construction_relations", scopes={"record"}, evidence={"present", "unannotated"}, empty_scopes=set(),
        partial_present_target_source="record", payload_family="construction_relation_collection", collection_like=True, requires_payload_field=False,
        payloads=(
            _payload("construction_signature", "predicate_lemma", "construction_type", "argument_pattern", "function_pattern"),
            _payload("construction_type", "value"),
            _payload("construction_tags", "value"),
            _payload("heads", "head", "dependent", "relation"),
            _payload("complements"),
            _payload("adjuncts"),
            _payload("fusion_relations", "id", "type", "fused_element", "whole_constituent", "relative_clause", "fused_functions", "external_function", "dependency"),
            _payload("typed_analysis", "kind", "framework", "arguments", "entities", "relations"),
            _payload("typed_arguments", "id", "kind", "type", "target", "source", "head", "dependent", "relation", "span", "clause_ref", "constituent_ref", "word_ref", "predicate", "value", "label"),
            _payload("typed_entity", "id", "kind"),
            _payload("typed_relation", "id", "kind", "type", "arity", "source", "target", "namespace", "framework", "head", "dependent", "relation", relation_types={
                "attachment", "construction", "control", "coreference", "cross_node", "framework_relation",
                "predication", "raising", "realization_link",
            }),
        ),
    ),
}


DIMENSION_REGISTRY: Mapping[str, DimensionSpec] = MappingProxyType(_DIMENSIONS)
CANONICAL_DIMENSIONS = frozenset(DIMENSION_REGISTRY)


CAPABILITY_DIMENSIONS: Mapping[str, frozenset[str]] = MappingProxyType({
    "basic_constituency": frozenset({"phrase_constituency", "constituency"}),
    "phrase_category": frozenset({"phrase_constituency", "constituency"}),
    "pos": frozenset({"lexical_category"}),
    "syntactic_function": frozenset({"syntactic_function"}),
    "complement_adjunct": frozenset({"syntactic_function", "vp_complementation"}),
    "lexical_valency": frozenset({"lexical_valency", "vp_complementation"}),
    "clause_structure": frozenset({"clause_ontology", "clause_structure"}),
    "relative_clause": frozenset({"clause_ontology", "clause_structure"}),
    "interrogative_clause": frozenset({"clause_ontology", "clause_structure"}),
    "nonfinite_clause": frozenset({"clause_ontology", "clause_structure"}),
    "gerund_participial": frozenset({"clause_ontology", "clause_structure"}),
    "infinitival": frozenset({"clause_ontology", "clause_structure"}),
    "semantic_roles": frozenset({"semantic_roles"}),
    "framework_distinction": frozenset({"framework_mapping"}),
    "coordination": frozenset({"construction_relations", "clause_ontology"}),
    "fused_relative": frozenset({"construction_relations", "clause_ontology"}),
    "control": frozenset({"clause_ontology", "lexical_valency", "vp_complementation"}),
    "raising": frozenset({"clause_ontology", "lexical_valency", "vp_complementation"}),
    "ecm": frozenset({"clause_ontology", "lexical_valency", "vp_complementation"}),
    "perception_construction": frozenset({"clause_ontology", "lexical_valency", "vp_complementation"}),
    "predicative_complement": frozenset({"syntactic_function", "lexical_valency", "vp_complementation"}),
    "pp_attachment": frozenset({"phrase_constituency", "syntactic_function"}),
    "ambiguity": frozenset({"phrase_constituency", "clause_ontology", "construction_relations"}),
    "error_diagnosis": frozenset({"syntactic_function", "clause_ontology", "framework_mapping"}),
})


PROJECTION_FIELD_DIMENSIONS: Mapping[str, tuple[str, ...]] = MappingProxyType({
    "framework": ("framework_mapping",),
    "sentence_type": ("clause_structure", "clause_ontology"),
    "sentence_type_metadata": ("clause_structure", "clause_ontology"),
    "sentence_classification": ("clause_structure", "clause_ontology"),
    "construction_type": ("construction_relations",),
    "construction_signature": ("construction_relations",),
    "construction_tags": ("construction_relations",),
    "pedagogical_aliases": ("framework_mapping",),
    "fusion_relations": ("construction_relations",),
    "explanation": ("clause_structure", "phrase_constituency", "syntactic_function"),
    "rationale": ("clause_structure", "phrase_constituency", "syntactic_function"),
})


def dimension_spec(dimension: object) -> DimensionSpec | None:
    if not isinstance(dimension, str):
        return None
    return DIMENSION_REGISTRY.get(dimension)


def projection_field_dimensions(field: str) -> tuple[str, ...]:
    return PROJECTION_FIELD_DIMENSIONS.get(field, ())


def projection_property_dimensions(field: str, property_name: str) -> tuple[str, ...]:
    """Return the canonical dimensions that own one projected property."""
    return tuple(
        dimension
        for dimension, spec in DIMENSION_REGISTRY.items()
        if property_name in spec.property_map.get(field, frozenset())
    )
