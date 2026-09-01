# Open grammar/theory questions for human review

The V0.1 questions listed below were formally resolved for V0.2. The authoritative decisions, representations, and validator boundaries are in [`theory_policy_v0.2.md`](theory_policy_v0.2.md).

## Resolved in V0.2

1. **Infinitival `to` POS.** Resolved by Decision 1 and Decision 12: canonical `lexical_category` is `subordinator`; UD/PTB and pedagogical labels are tagged mappings or aliases.
2. **Clause as constituent.** Resolved by Decision 2: `node_kind` separates clause and phrase; clauses use `clause_category`, while `Clause` is not a phrase category.
3. **Fused relatives.** Resolved by Decision 3: use explicit `fusion_relations` and distinguish fused relatives from embedded interrogatives.
4. **Predicands.** Resolved by Decision 4: use structured predicand kinds and do not invent overt matrix references for discourse-inferred cases.
5. **PP attachment ambiguity.** Resolved by Decision 5: use calibrated ambiguity statuses and reward both established structures and interpretations.
6. **Gerund-participial terminology.** Resolved by Decision 6: canonical modern label is gerund-participial; traditional labels are framework-marked aliases.
7. **Small clauses and secondary predication.** Resolved by Decision 7: alternatives are construction-specific and whitelist-bound.
8. **Semantic-role inventory.** Resolved by Decision 8: use the optional controlled vocabulary documented there, with `OTHER` and `UNSPECIFIED`.
9. **Lexical-substitution contamination.** Resolved by Decision 9: retain lexical checks and add conservative, auditable construction signatures.
10. **Pedagogical terminology.** Resolved by Decision 10: keep canonical analysis, framework alternatives, and learner aliases in separate layers.

## Additional V0.2 decisions

11. **Sentence type versus clause ontology.** Resolved by Decision 11: clause mood and optional `simple`/`compound`/`complex` pedagogical classification do not constrain non-finite or subordinate clauses.
12. **POS versus lexical category.** Resolved by Decision 12: canonical lexical category and tagset-qualified external POS mappings are separate fields.

## New questions

13. **Clause ontology dimensions (HIGH PRIORITY).** `clause_category` currently mixes clause status (main), finiteness (finite/non-finite), construction type (relative/interrogative/gerund-participial/infinitival), and discourse function (supplementary). The current release does not infer one dimension from another and does not add new records that depend on the mixed enum. Migration inventory: all records contain `clauses[].clause_category`; records using `relative_clause`, `interrogative_clause`, `gerund_participial_clause`, or `infinitival_clause` will need a schema migration when dimensions are separated. This release preserves their existing analyses for later human ontology review.

14. **Individual construction adjudication.** Perception constructions, control/raising/ECM, small clauses, relative `that`, fused relatives, semantic-role inventory, and ambiguity scoring remain linguistic questions. Structural validation deliberately does not choose among competing theories; records whose boundaries or reference types cannot be fixed mechanically remain candidates for independent review.
