# Open grammar/theory questions for human review

The V0.4 representation and validator boundaries are in
[`ontology_v0.4.md`](ontology_v0.4.md). A schema correction is not a
linguistic adjudication: records can be structurally valid while remaining
`review_required`.

## Resolved representation decisions

1. **Infinitival `to` POS.** The canonical `lexical_category` is `subordinator`; UD/PTB and pedagogical labels are tagset-qualified mappings or framework-marked aliases.
2. **Clause as constituent.** `node_kind` separates clause and phrase; `Clause` is not a phrase category.
3. **Predicands.** Use structured predicand kinds and do not invent overt matrix references for discourse-inferred cases.
4. **PP attachment ambiguity.** Use calibrated ambiguity statuses and record the established structures and interpretations required by the applicable status.
5. **Gerund-participial terminology.** The canonical modern label is gerund-participial; traditional labels are framework-marked aliases.
6. **Lexical-substitution contamination.** Retain lexical checks and add conservative, auditable construction signatures.
7. **Pedagogical terminology.** Keep canonical analysis, the single `alternative_analyses[]` channel, and learner aliases in separate layers. Historical alternative fields are display/provenance metadata only.

## Additional current representation decisions

8. **Sentence type versus clause ontology.** Clause mood and optional `simple`/`compound`/`complex` pedagogical classification do not constrain non-finite or subordinate clauses.
9. **POS versus lexical category.** Canonical lexical category and tagset-qualified external POS mappings are separate fields.

## Still open

These questions have representation support but no final linguistic
adjudication. Their benchmark records must remain `review_required` until
independent review.

10. **Fused relatives.** The representation uses explicit `fusion_relations`,
    but the final fused-relative structural ontology remains open; existing
    fixture wording is not adjudicated gold.
11. **Small clauses and secondary predication.** Alternative records may be
    construction-specific and framework-attributed, but final adjudication is
    deferred.
12. **Semantic-role inventory.** The existing controlled vocabulary is retained
    as a serialization extension, but the final semantic-role taxonomy and
    scoring policy remain open.

## V0.4 representation decisions (not linguistic resolutions)

13. **Clause integration representation.** The schema separates `finiteness`,
    `clause_form`, `clause_construction`, and composable `integration` relations.
    This is a serialization decision; it does not resolve construction theory.

14. **Individual construction adjudication.** Perception constructions, control,
    raising/ECM, small clauses, relative `that`, for-to `for`, copular `be`,
    fused relatives, semantic-role inventory, and ambiguity scoring remain
    linguistic questions. Structural validation deliberately does not choose
    among competing theories; records whose boundaries or reference types
    cannot be fixed mechanically remain `review_required`.
15. **Clause heads under coordination.** V0.4 permits a clause `head` to reference a word, phrase, or clause but does not choose a coordination head theory. A future release may standardize a relation-specific convention.
16. **Lexical classification edge cases.** The final canonical categories of relative `that`, `for`, and copular `be` remain open; external tagsets and framework-qualified alternatives must be used meanwhile.
17. **Partial-annotation scoring.** V0.4 defines the scoped coverage contract, but weighting and adjudication of task-focused dimensions in an ambiguity scorer require a later evaluation design.
