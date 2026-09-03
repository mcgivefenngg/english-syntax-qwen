# English Syntax Tutor V0.2 Theory Policy

> V0.4 note: [`ontology_v0.4.md`](ontology_v0.4.md) is authoritative for the
> canonical framework boundary, clause dimensions, coverage contract, and
> token/span convention. The V0.2 decisions below remain historical guidance
> where V0.4 does not supersede them.

Status: authoritative for V0.2 annotation and data validation. The canonical framework is **CGEL-inspired modern descriptive English syntax**. “Inspired” is intentional: records may compare traditional pedagogical grammar, Universal Dependencies (UD), Penn Treebank (PTB), generative terminology, or another established modern analysis when the framework is named. A framework alternative never silently changes the canonical analysis.

## Cross-cutting invariants

* Category, syntactic function, semantic role, lexical category, and external POS tags are separate dimensions.
* `lexical_category` is the canonical word-level category. `external_pos_tags` is an array of `{tagset, tag}` mappings. The V0.1 `pos` field is accepted only as a compatibility field and must carry `pos_tagset` when retained.
* `node_kind` distinguishes `word`, `phrase`, and `clause`. A phrase uses `phrase_category`; a clause uses `clause_category`, `finiteness`, and `function`. A clause is a constituent, but is not a phrase category.
* Spans remain zero-based, half-open token intervals. References always use stable IDs.
* Validators check references and schema invariants, not the ultimate truth of a defensible linguistic analysis.

## Decision 1 — Infinitival *to*

**Issue.** POS inventories disagree about the infinitival marker.

**Adopted policy.** In the canonical `cgel_inspired` analysis, infinitival *to* has lexical category `subordinator`. Record UD/PTB or another external tag separately, for example `external_pos_tags: [{"tagset": "UD_UPOS", "tag": "PART"}]`; a learner-facing “infinitive marker” label belongs in a framework-qualified `pedagogical_aliases` entry.

**Rationale.** Subordinator, `PART`, infinitive marker, and auxiliary-like analyses answer different framework questions and must not compete in one unqualified POS field.

**Canonical representation.** `words[].lexical_category` is the theoretical category; `words[].external_pos_tags[]` carries tagset-qualified mappings.

**Allowed alternatives.** A named traditional framework may call *to* an infinitive marker. A named generative or other established framework may use an auxiliary-like analysis when documented.

**Prohibited conflations.** Do not overwrite `lexical_category` with `PART`, do not treat a bare `pos` string as a second canonical truth, and do not infer an auxiliary merely from a tagset label.

**Schema implications.** V0.2 words use `lexical_category`; external tags require both `tagset` and `tag`. Legacy `pos` is migration-only.

## Decision 2 — Clause as constituent

**Issue.** Earlier records used `category: "Clause"` inside phrase constituents.

**Adopted policy.** Clause is a constituent category but not a Phrase Category. Use `node_kind: "clause"` with `clause_category`, `finiteness`, and `function`; use `node_kind: "phrase"` with `phrase_category` for phrases. A clause-valued constituent reference uses `clause_ref` rather than assigning `Clause` as a phrase category.

**Rationale.** Non-finite clauses have clause structure even without a finite verb, and category/function must remain orthogonal.

**Canonical representation.** `Having completed the checklist` is a `gerund_participial` clause with `finiteness: non-finite`; its function may be `supplementary_adverbial` or another function at the relevant layer.

**Allowed alternatives.** A traditional source may say “participial phrase” or “infinitive phrase”, but that wording is recorded as a framework-labeled alternative.

**Prohibited conflations.** An adverbial function never licenses `AdvP`; no “no finite verb, therefore no clause” inference is permitted.

**Schema implications.** V0.2 clause and phrase nodes carry distinct fields; validator rejects `Clause` as a V0.2 phrase category and checks clause references.

## Decision 3 — Fused relatives

**Issue.** Fused relatives were represented as one constituent with ambiguous function strings.

**Adopted policy.** Use an explicit `fusion_relations` object for fused relatives. It identifies the fused element, the whole external constituent, the relative clause, the fused nominal/relative functions, and (when available) the dependency.

**Rationale.** `What he said surprised everyone` is a fused-relative construction; `I wonder what he said` is an embedded interrogative. The distinction is structural, not a stylistic choice.

**Canonical representation.** The whole fused-relative NP can be `function: subject`; the relation records `fused_functions: ["nominal", "relativized"]` and links `relative_clause` and `fused_element` by ID.

**Allowed alternatives.** “Free/nominal relative clause” is an established traditional label when explicitly marked. An interrogative analysis is allowed only for an interrogative construction, not as a synonym for a fused relative.

**Prohibited conflations.** Do not use a single vague `noun clause` label for both constructions or duplicate the same span with contradictory functions.

**Schema implications.** `fusion_relations` has required ID references and at least two fused functions; validator checks every reference.

## Decision 4 — Predicands

**Issue.** Supplementive clauses may have an overt, controlled, discourse-inferred, generic, or indeterminate predicand.

**Adopted policy.** Encode `clauses[].predicand` as `{kind, target, basis?, note?}`. `kind` is one of `overt_constituent`, `implicit_control`, `discourse_inferred`, `generic`, or `indeterminate`.

**Rationale.** A schema should preserve uncertainty instead of inventing a matrix NP for a discourse-inferred supplement.

**Canonical representation.** In `Having completed the checklist, the crew started the engines`, use `{"kind":"overt_constituent","target":"crew"}` (with the actual stable ID). A discourse-inferred predicand uses a null target and an evidential note.

**Allowed alternatives.** An annotator may record a controlled or inferred relation with its basis; no extra theoretical subject is needed.

**Prohibited conflations.** Do not force every supplement to control an overt matrix NP and do not use a semantic role as a predicand reference.

**Schema implications.** V0.2 structured predicands are reference-checked; V0.1 string predicands remain readable for migration.

## Decision 5 — Ambiguity and PP attachment

**Issue.** PP attachment alternatives need a calibrated benchmark policy.

**Adopted policy.** Set `ambiguity.status` to `unambiguous`, `genuinely_ambiguous`, or `multiple_established_analyses_with_preferred_reading`. List structural analyses and interpretations for competing readings.

**Rationale.** `I saw the man with a telescope` supports VP/instrument and NP/man-associated readings. A merely imaginable marked reading is not enough to label a sentence ambiguous.

**Canonical representation.** A genuinely ambiguous record lists both attachment structures, both interpretations, and (where context warrants) a preferred reading. Benchmark scoring rewards ambiguity recognition, both structures, both interpretations, and calibrated preference.

**Allowed alternatives.** Multiple established analyses may be listed when they are genuinely supported and the preferred reading is explicit.

**Prohibited conflations.** Do not call every PP ambiguous, and do not treat a semantic Location role as proof of adjunct attachment.

**Schema implications.** The validator requires two analyses for `genuinely_ambiguous`; a preferred analysis ID is required for the multiple-analysis status.

## Decision 6 — Gerund-participial terminology

**Issue.** Traditional and modern labels differ for *-ing* clauses.

**Adopted policy.** Canonical labels are lexical category `verb`, form `gerund-participle`/`gerund_participial`, and (where needed) clause category `gerund_participial_clause`.

**Rationale.** The form and category generalize across perception, supplementive, and complement constructions without treating “gerund” as a universal category.

**Canonical representation.** `I saw him leaving` has a gerund-participial clause complement; `flying` in `afraid of flying` is a verb in a non-finite clause.

**Allowed alternatives.** A traditional framework may use “present participle”, “gerund”, or “participial phrase” when explicitly named.

**Prohibited conflations.** Traditional terminology cannot be written into the canonical category field and cannot erase non-finite clause status.

**Schema implications.** `gerund_participial_clause` is a clause category; learner terms use `pedagogical_aliases`.

## Decision 7 — Small clauses and secondary predication

**Issue.** “Small clause” is sometimes over-generated as a universal alternative.

**Adopted policy.** Use a construction-specific whitelist. A `small_clause` alternative must name an established framework, `status: established`, `analysis_type: small_clause`, and an approved `construction_type` such as `object_predication`, `resultative`, or `caused_state`.

**Rationale.** `I consider him intelligent` may support a small-clause analysis; an arbitrary NP + predicate sequence does not automatically do so.

**Canonical representation.** Record object, predicative complement, and secondary-predication relations in the canonical construction analysis; attach a whitelisted alternative only where its construction licenses it.

**Allowed alternatives.** ECM, control, secondary predication, object complement, and small clause are separately named analyses tied to their construction and framework.

**Prohibited conflations.** Never permit a global “NP + predicate = small clause” rule.

**Schema implications.** Alternative analyses require framework metadata; validator enforces the whitelist for explicit small-clause alternatives.

## Decision 8 — Semantic roles

**Issue.** Open role strings make evaluation inconsistent, but roles are not syntax.

**Adopted policy.** Use an optional controlled vocabulary: `Agent`, `Patient`, `Theme`, `Experiencer`, `Stimulus`, `Recipient`, `Beneficiary`, `Location`, `Goal`, `Source`, `Instrument`, `Cause`, `Possessor`, `Attribute`, `Result`, `State`, `Support`, `Time`, `Purpose`, `Proposition`, `Addressee`, `Classification`, `Temporal/Aspectual`, `OTHER`, and `UNSPECIFIED`.

**Rationale.** The inventory is small enough for deterministic checks while allowing an explicit escape hatch.

**Canonical representation.** `semantic_roles` points to a constituent ID and stores the role independently of its syntactic function.

**Allowed alternatives.** A source may use `OTHER` or `UNSPECIFIED` with a note; framework-specific role labels can be described in the explanation.

**Prohibited conflations.** A semantic Location does not determine Adjunct. `on the table` may be a selected locative Complement after `put`.

**Schema implications.** Validator checks role vocabulary and references only; it does not infer or override syntactic functions.

## Decision 9 — Construction-level contamination

**Issue.** Exact-string checks miss lexical substitutions that preserve a benchmark frame.

**Adopted policy.** Keep exact, normalized, overlap, edit-distance, and skeleton checks. In addition, records may carry an auditable `construction_signature` with `predicate_lemma`, `construction_type`, `argument_pattern`, and `function_pattern`. A matching signature on a train/validation record is a conservative contamination finding, even when nominal fillers differ.

**Rationale.** `She put the luggage in the compartment` preserves the held-out `PUT + Subject + Object + Locative Complement` frame from `She put the book on the table`. `place` is a different predicate lemma and is not rejected solely for structural similarity.

**Canonical representation.** Signatures are explicit where reviewed; for V0.1 records the checker may derive a signature from a single lexical-valency frame and marks the source as derived.

**Allowed alternatives.** A reviewer may clear a flagged match only with an auditable construction distinction; no embedding index or ML detector is introduced.

**Prohibited conflations.** Do not treat all same-shape sentences as contaminated and do not rely on exact sentence equality alone.

**Schema implications.** Signature fields are machine-readable and validator/checker reports identify the benchmark ID and signature components.

## Decision 10 — Pedagogical terminology

**Issue.** Learner-friendly labels are useful but can blur canonical syntax.

**Adopted policy.** Store canonical analysis, framework alternatives, and pedagogical aliases in separate layers. Aliases name their framework and (when useful) the field or span they describe.

**Rationale.** Learners can encounter “gerund”, “动名词”, or “obligatory locative Adverbial” without changing the gold analysis.

**Canonical representation.** `canonical_analysis` (with `preferred_analysis` as a V0.1 compatibility alias) is authoritative; V0.4 `alternative_analyses[]` is the sole authoritative alternative channel and each entry is framework/status/typed-analysis qualified; `pedagogical_aliases` is learner-facing. The former `framework.alternatives` and `framework_alternatives` fields are legacy display/provenance only and are rejected in canonical V0.4 records.

**Allowed alternatives.** Traditional labels may be exposed when marked `traditional_pedagogical`.

**Prohibited conflations.** Never write an alias into `lexical_category`, `phrase_category`, `clause_category`, or canonical `function`.

**Schema implications.** Alternative analyses require framework metadata and aliases require `framework: traditional_pedagogical`; differing canonical and legacy preferred objects are rejected.

## Decision 11 — Sentence type versus clause ontology

**Issue.** Pedagogical sentence labels are often misused to infer clause structure.

**Adopted policy.** `sentence_type` records clause mood (`declarative`, `interrogative`, `exclamative`, `imperative`, `fragment`). Optional `sentence_type_metadata` records the scheme/framework, and `sentence_classification` can carry a pedagogical `simple`/`compound`/`complex` label with its scheme. Neither field constrains the clause inventory.

**Rationale.** A declarative/simple sentence may contain a non-finite clause; sentence classification and clause ontology answer different questions.

**Canonical representation.** `To reduce noise, the operator closed the hatch` remains declarative while containing a non-finite infinitival supplementary clause.

**Allowed alternatives.** Traditional “simple/compound/complex” labels may be recorded in metadata as a classification scheme.

**Prohibited conflations.** Never infer “simple sentence, therefore no subordinate/non-finite clause.”

**Schema implications.** Validator intentionally has no rule that forbids non-finite clauses under any `sentence_type` or pedagogical sentence classification.

## Decision 12 — POS versus lexical category

**Issue.** V0.1 `pos` and `lexical_category` could become two unqualified truth fields.

**Adopted policy.** `lexical_category` is the canonical theoretical category. `external_pos_tags` is the only general mapping field and every mapping names its tagset. `pos` remains only for explicit V0.1 migration.

**Rationale.** UD, PTB, pedagogical grammar, and CGEL-inspired categories are not one inventory with interchangeable values.

**Canonical representation.** For infinitival *to*: `lexical_category: subordinator`, `external_pos_tags: [{"tagset":"UD_UPOS","tag":"PART"}]`, and (optionally) a traditional alias.

**Allowed alternatives.** Any established tagset can be added as another tagged mapping; it cannot replace the canonical category.

**Prohibited conflations.** No parallel unqualified `POS` truth field and no missing tagset metadata.

**Schema implications.** V0.2 fixtures use `node_kind` and `external_pos_tags`; the validator rejects a V0.2 legacy `pos` without `pos_tagset` and checks tagset/tag pairs.

## Review boundary

This policy does not re-review the 50 held-out benchmark analyses. Benchmark records remain evaluation-only and are changed only as needed for schema compatibility. Questions requiring a new theoretical decision must be added to `docs/open_questions.md` rather than guessed by the pipeline.
