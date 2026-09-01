# Capability taxonomy (V0.2)

Tags are intentionally finite and stable. Apply the smallest set that describes what a learner must reason about; do not add a tag for every construction name.

| Tag | Definition | Typical evidence |
| --- | --- | --- |
| `basic_constituency` | Nested spans and constituency boundaries | NP/VP/Clause bracketing |
| `clause_structure` | Clause boundaries, embedding, and clause relations | finite content clause; coordination |
| `pos` | Word-level lexical category/POS | noun vs determiner vs auxiliary |
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

Tags are not ordered and are not scores. Benchmark coverage is audited by `tests/test_data_pipeline.py` and should be revisited whenever the taxonomy changes.
