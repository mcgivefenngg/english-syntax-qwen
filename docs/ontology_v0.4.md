# English Syntax Tutor V0.4 Foundational Contract

V0.4 is a breaking wire-contract correction. It is not a continuation of the
V0.3/V0.3.1 wire identity: canonical records use `schema_version: "0.4"`, the
gold schema id ends in `gold-annotation-0.4.json`, and rendered targets use a
separate `rendered-sft-target-0.4.json` identity. The frozen V0.3 artifact is
kept only as `gold_annotation_v03_legacy.schema.json`.

## Authority

Machine-authoritative linguistic claims live in typed structures: words and
lexical candidates, clause ontology, constituents, relations, valency,
framework-qualified alternatives, and typed analyses. `claims`, `explanation`,
and `rationale` are explanatory projections. A prose-only assertion does not
become benchmark or training truth; the relevant dimension remains unresolved
or not approved. `typed_analysis.relations` is a closed structural contract:
each relation has a stable id, an explicit `arity` (`unary` or `binary`), a
controlled or explicitly namespace-qualified type, a namespaced source
reference (`{"namespace": "word", "id": "w1"}` or `word:w1`), and a target
exactly when binary. Unary relations cannot carry a target. Word,
constituent, clause, and analysis-local references cannot dangle. Typed
relations express cross-node, construction, dependency, or framework-specific
facts; they do not restate canonical scalar fields such as constituent
function, phrase category, lexical category, or clause construction.

Authority ownership is deliberately single-layered. Lexical categories and
external POS mappings belong to the lexical layer; finiteness, construction,
integration, and parentage belong to the clause layer; phrase category,
external function, and clause realization belong to the constituent layer;
typed relations belong to the relation layer only for cross-node or
framework-qualified facts. Deterministic contradiction checks compare facts
only within their preferred authority layer and never adjudicate English
grammar from prose.

Lexical uncertainty is explicit. A candidate has a category plus a namespace
(`category_namespace` or an established `framework`), and may carry a status.
External POS mappings are a separate `external_pos_tags` layer. Items such as
relative *that*, *for*, and copular *be* may remain unresolved without a fake
project-canonical category.

## Clause axes and realization

Clause construction and integration are orthogonal typed axes. `integration`
must not mix `unresolved` with a resolved relation, and the root clause is the
single source for declarative/interrogative/exclamative mood. `sentence_type`
is a derived/pedagogical projection and cannot contradict the root construction.

Clause-valued constituents carry the external syntactic function through an
explicit realization (`same_span_alias`, `expanded_realization`, or `other`).
Within the preferred canonical context and realization layer, one
`clause_ref` may not have duplicate or incompatible peer wrappers. A
`context`/`layer` on the realization is the explicit distinction for a
legitimate second realization; otherwise a wrapper conflict must be linked to
the exact alternative or ambiguity that authorizes it. `integration_parent`,
when present, references a clause ID. Multiple mature analyses must be
represented by explicit, linked alternatives; an unrelated ambiguity object
does not suppress a wrapper conflict.

`alternative_analyses[]` is the only authoritative alternative channel. Each
entry has a stable alternative ID, a framework, a status (`established`,
`unresolved`, or `review_required`), and a typed analysis, with optional
learner-facing explanation and explicit wrapper/constituent/clause/relation
links. `framework.alternatives` and `framework_alternatives` are rejected as
parallel V0.4 authority channels. Historical prose can be retained as
`legacy_alternative_metadata`, but it is display/provenance evidence only.

No construction-level adjudication is implied for ECM, control, raising,
perception, small clauses, secondary predication, fused relatives,
coordination, or semantic-role taxonomies.

## Scoped coverage and scoring

Coverage keys are `(dimension, scope)`, where scope identifies a record, node,
or token region. The same dimension can be complete for one node and
intentionally omitted for another. The same dimension+scope cannot have
contradictory declarations. `complete` is normally scoreable; `partial` is
scoreable only for its explicitly named covered node/region; `unannotated`,
`omitted`, and `out_of_scope` completeness (or an intentional omission) is not
scoreable. An annotated empty list is
evidence of a confirmed empty set, not the same as an unannotated field.

## Rendering and governance

The default renderer projects an explicit linguistic-field allowlist. It
honors coverage: omitted/unannotated dimensions are absent from the assistant
payload, while annotated empty dimensions remain present. Governance metadata
(`review_metadata`, migration flags, ids, split, provenance, and future
governance fields) stays in `governance_sidecar` and is not rendered as target
supervision. The default rendering mode omits unresolved lexical candidate
analyses; `--rendering-mode learner_facing` is the explicit opt-in when
candidate/framework alternatives are themselves the learner-facing task. The
sidecar also records a content-review snapshot so a rendered target cannot hide
unresolved source content from the training gate.

## Review, approval, and canonical gold

Structural/migration state, linguistic review, and training approval are
separate lifecycle concepts. `linguistically_reviewed` alone does not authorize
normal SFT. Normal SFT accepts only explicit `approved_for_training` or
`canonical_gold`, with content-aware checks on the actual rendered projection.
Benchmark, migration-review, unresolved typed/lexical/clause content, and
coverage/payload mismatches are rejected. `canonical_gold` is a content
invariant: no unresolved candidate, unresolved clause/typed analysis,
migration-review flag, or incomplete record-level required canonical dimension may remain.
Established framework alternatives are allowed and are not equivalent to
unresolved adjudication.

## Migration guarantees

The generic migrator maps the real source wire version `0.2` to `0.4`.
`v0.2.1` is recorded only as release provenance; it is never treated as a
schema version. V0.4 input is an exact no-op. Unknown source versions are
rejected. Structural fields are mapped only when their source meaning is
unique; geometry never infers `shared_subject_projection`, and ambiguous
relations become `other` plus review requirement. Existing review metadata is
not overwritten. Fixture-specific repairs require a strict manifest of exact
record ids/source versions (and optional hashes), reject reviewed/approved
records, and are repeat-safe.

## Open questions

Construction-level linguistic adjudication remains intentionally open:
relative *that*, for-to clauses, copular *be*, perception, control, raising,
ECM, small clauses, secondary predication, fused relatives, ambiguity scoring,
coordination heads, and semantic-role taxonomy. V0.4 stabilizes the contract
for later human adjudication; it does not claim those analyses are finished.
