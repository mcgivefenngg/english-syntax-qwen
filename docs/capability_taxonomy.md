# Capability taxonomy (V0.4)

Tags are intentionally finite and stable. `capability_tags` describe what a learner must reason about; they do not assert that the sentence contains the named construction. Apply the smallest set that describes the task. If structural presence must be asserted, use the separate `construction_tags` field.

| Tag | Definition | Typical evidence |
| --- | --- | --- |
| `basic_constituency` | Nested spans and constituency boundaries | NP/VP/Clause bracketing |
| `clause_structure` | Clause boundaries, embedding, and clause relations | finite content clause; coordination |
| `pos` | Word-level lexical category/POS | noun vs determinative vs auxiliary |
| `phrase_category` | Category of a phrase (not a clause) | PP, AdjP, NP |
| `syntactic_function` | Function in a larger unit | subject, object, adjunct |
| `complement_adjunct` | Selection versus optional modification | selected locative PP |
| `lexical_valency` | Predicate frame and licensed dependents | put NP PP; persuade NP to-clause |
| `relative_clause` | Relative modifying an overt antecedent | the book that I read |
| `fused_relative` | Fused head/relative construction | what she bought |
| `interrogative_clause` | Open or subordinate interrogative | wonder what she bought |
| `nonfinite_clause` | Clause lacking finite morphology | to leave; having left |
| `gerund_participial` | -ing clause with gerund-participial form | leaving early |
| `infinitival` | to-infinitival or bare infinitival clause | to leave; leave |
| `control` | Matrix predicate controls understood subject | want him to leave |
| `raising` | NP raises from lower subject position | seem to leave |
| `ecm` | Matrix predicate licenses case across a clause | expect him to leave |
| `perception_construction` | See/hear/feel plus bare or -ing clause | saw him leave/leaving |
| `secondary_predication` | Depictive/predicative relation beyond main predicate | arrived exhausted |
| `predicative_complement` | Subject/object predicative complement | found it useful |
| `pp_attachment` | PP attachment and scope | saw the man with a telescope |
| `ambiguity` | More than one established structural reading | attachment or coordination |
| `coordination` | Coordinate structures and relations | A and B; clause coordination |
| `semantic_roles` | Participant/circumstance roles, separate from function | Agent, Theme, Location |
| `framework_distinction` | Explicit comparison of mature frameworks | CGEL vs pedagogical label |
| `error_diagnosis` | Diagnosis of a proposed analysis | level, verdict, correction |

Tags are not ordered and are not scores. A tag is not construction-presence
evidence: use `construction_tags` for presence and
`annotation_scope.dimensions` for the dimensions that a scorer may evaluate.
Benchmark coverage is audited by the ontology regression tests and should be
revisited whenever the taxonomy changes.
