# English Syntax Tutor V0.2 annotation guidelines

The authoritative theory decisions are in [`theory_policy_v0.2.md`](theory_policy_v0.2.md). This document retains the practical V0.1 examples while describing the V0.2 migration fields.

This document defines the machine-readable canonical layer and its review-status boundary. Annotators record an analysis; they do not write a conversational answer. Structural validation does not confer independent linguistic review or `canonical_gold` status. The renderer can later choose a prompt and response style without changing the canonical data.

## Annotation unit

Each JSONL object is one sentence-level example. Token spans use zero-based, half-open indices (`start` inclusive, `end` exclusive) into `words`. Every span must be contiguous and within the token list. Words and punctuation are both tokens: punctuation is emitted as its own `words` item (for example `.` or `,`) and punctuation spacing is normalized only for sentence/token alignment. Main-clause spans may cover sentence-final punctuation; phrase and embedded-clause boundaries should not be extended merely to absorb punctuation. The validator compares the sentence surface-token sequence with `words[].form` exactly (case-insensitively), so a missing or extra punctuation token is a structural error. A `clause` is a clause because of its clause structure, not because it contains a finite verb: non-finite clauses are valid clauses.

### Why this shape

The schema uses stable IDs and spans so nested constituency and cross-clause relations can be checked without reparsing text. Orthogonal fields prevent a semantic observation from overwriting a category or function label. Preferred, alternative, and rejected analyses are separate so a framework comparison is explicit and auditable. Optional valency, role, contrast, and diagnosis blocks keep simple examples small while allowing expert cases to carry the required evidence. `additionalProperties` is intentionally open for future controlled extensions; new fields still need a guideline and validator rule before they become project conventions.

The required top-level fields are `schema_version`, `id`, `sentence`, `capability_tags`, `difficulty`, `source_type`, `framework`, `sentence_type`, `clauses`, `constituents`, `words`, `dependencies`, one of `canonical_analysis` or the V0.1 compatibility field `preferred_analysis`, `explanation`, and `split`. Optional fields capture valency, semantic roles, contrasts, construction signatures, predicands, fusion relations, ambiguity, alternatives, rejected analyses, pedagogical aliases, and error diagnosis.

Use optional `heads`, `complements`, and `adjuncts` lists when a compact index is useful; their values point to constituent/clause IDs. The detailed category/function evidence still belongs on each constituent, so these convenience lists never replace the analysis.

`sentence_type` records clause mood. If a lesson also uses traditional `simple`/`compound`/`complex` labels, put the label and its scheme in `sentence_classification`; neither classification layer limits the `clauses` array.

## Four kinds of labels

Keep these dimensions independent in every annotation:

* **Lexical category** is the word-level class: noun, verb, adjective, adverb, preposition, determiner, pronoun, coordinator, subordinator, auxiliary, modal, particle, numeral, interjection, or punctuation. The `words[].lexical_category` field records it; V0.2 external mappings belong in `words[].external_pos_tags` as `{tagset, tag}` objects. `words[].pos` is V0.1 compatibility only.
* **Phrase category** is the category of a phrase constituent: `NP`, `VP`, `PP`, `AdjP`, `AdvP`, and so on. It is recorded in `constituents[].phrase_category` when `node_kind: "phrase"`.
* **Clause category** is recorded in `clauses[].clause_category` when `node_kind: "clause"`; a clause-valued constituent uses `clause_ref`, not phrase category `Clause`.
* **Syntactic function** is the job performed in a larger construction: subject, object, selected complement, adjunct, predicative complement, relative modifier, etc. It is recorded in `constituents[].function` and `clauses[].function`.
* **Semantic role** is a participant or circumstance interpretation (Agent, Theme, Location, Experiencer, and similar). It belongs only in `semantic_roles` and never substitutes for a syntactic function.

Thus a PP functioning as an adverbial remains `phrase_category: "PP"`; it is never relabelled `AdvP`. Conversely, an AdvP is not made a PP merely because it expresses location.

## Preferred analyses and alternatives

`framework.preferred` identifies the framework used for the default analysis. Use `cgel_inspired` for the project's modern descriptive default (`CGEL` remains a V0.1 compatibility spelling), `traditional_pedagogical` for an explicitly traditional lesson, `modern_descriptive` for a non-CGEL modern analysis, and `mixed` only when the example deliberately compares frameworks. Mature alternatives go in `framework.alternatives` and `alternative_analyses`; they must be marked `status: "established"` and described. Do not invent an alternative just to appear comprehensive. `rejected_analyses` is for common or tempting analyses that are wrong for the stated framework, with a reason.

## Complement vs adjunct

Use lexical selection and constructional licensing, not a question test alone. In **She put the book on the table**, `on the table` is `phrase_category: "PP"`, `function: "selected_locative_complement"`: *put* licenses a location and the complement is normally obligatory. It is acceptable to record the traditional label “obligatory locative Adverbial” as an established alternative, but it must not be treated unconditionally as an ordinary optional adjunct. A PP in **She read the book on the table** is normally an adjunct (with an attachment ambiguity if context permits).

## Non-finite clauses

Annotate **Having completed the checklist, the crew started the engines** as a `gerund_participial_clause` with `finiteness: "non-finite"`, function `supplementary_adverbial`, and understood subject/predicand `the crew`. The modern analysis calls it a non-finite perfect gerund-participial clause. A traditional source may call it a “participial phrase”; record that as an established alternative, never as a reason to deny clause status (“no finite verb, therefore not a clause”). The same policy applies to infinitival clauses: **To reduce noise, the operator closed the hatch** has a non-finite infinitival clause.

## Relatives and interrogatives

**What he said surprised everyone** is a CGEL-style fused-relative construction (a fused-relative NP): the `what` element fuses the nominal and relativized functions. Traditional grammar may call it a nominal/free relative clause. **I wonder what he said** is an embedded interrogative construction, not a fused relative; its clause functions as the complement of *wonder*. Relative clauses modifying an overt head (for example, **the report that we filed**) must be distinguished from both.

## Perception, control, raising, and ECM

Record the embedded clause and understood-subject relation explicitly.

* **I saw him leave the building** contains a bare infinitival complement; *him* is the understood subject of *leave*. The traditional “Object + Object Complement” analysis is an established alternative where relevant.
* **I saw him leaving the building** contains a gerund-participial complement, with the same understood-subject relation.
* **I want him to finish** is object control: *him* is object of *want* and understood subject of the infinitival clause. **I persuaded him to finish** is also control, but with a different lexical frame.
* **He seems to understand** is raising: *he* is not a semantic argument of *seem* and is raised from the infinitival subject position. **I expect him to finish** is ECM (exceptional case marking), not subject control.

Do not collapse these constructions because all contain `to` or an NP plus a non-finite verb.

## Predication, attachment, and coordination

Distinguish subject and object predicative complements from ordinary objects or adjuncts: **The committee found the proposal impractical** has an object-predicative complement `impractical`. Record secondary predication when an adjunct predicates of an NP, as in **The children arrived exhausted**. For PPs, annotate plausible attachment alternatives only when the syntax genuinely supports them; state a preferred reading and the evidence. Coordination should represent conjuncts and coordinator relations, not treat the coordinator as a head NP.

## Minimal pairs and error diagnosis

Use the same `contrast_group` for minimal pairs or a larger contrast set. Keep all members in the same source family but assign their actual `split`; a benchmark member is never copied to train or validation.

An `error_diagnosis` object stores the student's/model's claim and one or more diagnoses. Each diagnosis states `verdict` (`error`, `acceptable_alternative`, or `correct`), `error_level`, `correct_analysis`, and `why`. An analysis can therefore be wrong at the phrase-category level while its semantic-role observation is true, or be an acceptable framework difference rather than an error. For **on the table is an optional adverbial** with *put*, diagnose the syntactic-function error: location is a semantic role, while *put* selects a locative complement.

## Review checklist

Before accepting an example, check token spans, unique IDs, lexical/phrase/function separation, finiteness, node kinds, external POS tagsets, head/dependency/predicand/fusion references, framework status, ambiguity calibration, construction signatures, review metadata, and split. Use `review_status: "review_required"` when a structural boundary cannot be repaired without a linguistic decision. Run `.venv/bin/python scripts/validate_dataset.py <files> --benchmark eval/benchmark_v1.jsonl` and `.venv/bin/python scripts/check_contamination.py <train-or-generated-files> --benchmark eval/benchmark_v1.jsonl` before publishing. The validator executes the Draft 2020-12 JSON Schema engine, checks sentence/words alignment and reference types, and sends every benchmark row through the same full record validation. Rendered assistant content is parsed as JSON and validated as a complete canonical target. These are machine-structural guarantees, not linguistic adjudication; a structurally valid benchmark record is not automatically `canonical_gold`. V0.1 records remain readable for migration; new records should use `schema_version: "0.2"`, `canonical_analysis`, `node_kind`, `phrase_category`/`clause_category`, and `external_pos_tags`.
