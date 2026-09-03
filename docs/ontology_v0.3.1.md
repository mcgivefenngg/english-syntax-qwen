# English Syntax Tutor V0.3.1 legacy foundational ontology

V0.3.1 was a superseded contract correction release. It does not add linguistic gold and
does not adjudicate relative **that**, for-to **for**, copular **be**, control,
raising, ECM, perception, small clauses, coordination heads, fused relatives,
or semantic-role theory.

## Lexical analysis

`words[].lexical_category` is the canonical lexical category. The category
`determinative` is distinct from the syntactic function `determiner`, which is
recorded on a constituent (or an explicitly typed word realization). A value
such as `determiner` in `lexical_category` is invalid; a value such as
`determinative` in a syntactic-function field is invalid. External POS tags are
always separate `{tagset, tag}` mappings.

An unresolved item has `lexical_category: null` and a `lexical_analysis` object:

```json
{
  "status": "unresolved",
  "review_required": true,
  "candidates": [
    {"lexical_category": "pronoun", "syntactic_function": "relative", "framework": "cgel_inspired"},
    {"lexical_category": "subordinator", "syntactic_function": "marker", "framework": "traditional_pedagogical"}
  ]
}
```

Every candidate names its framework. Candidate objects cannot contain external
POS mappings, and an unresolved item cannot be `canonical_gold`. Free-text
`canonical_analysis.claims` remains an explanation; a framework-sensitive
structural claim must also be represented by the typed `typed_analysis` object.

## Clause construction and integration

Clause-internal ontology is stored only on a clause node:

* `finiteness`: `finite`, `nonfinite`, `verbless`, or `unspecified`;
* optional `clause_form` for nonfinite clauses;
* `clause_construction`: `declarative`, `interrogative`, `relative`, `content`,
  `conditional`, `comparative`, `exclamative`, `coordinate`, `other`, or
  `unresolved`;
* `integration`: a unique list of `root`, `subordinate`, `supplementary`,
  `coordinate_member`, or `unresolved`.

Construction and integration are independent. A root interrogative is
`clause_construction: "interrogative", integration: ["root"]`; it is not
forced to be a matrix construction. A subordinate coordinate member can use
`["subordinate", "coordinate_member"]`. A supplementary relative can use
`clause_construction: "relative", integration: ["supplementary"]`.
`supplementary` is not the function `supplementary_adverbial`, and no clause
function is inferred from integration.

Clause nodes never carry an authoritative `function`. External realization is
owned by a clause-valued constituent:

```json
{
  "node_kind": "clause", "clause_ref": "c1", "function": "selected_complement",
  "span": {"start": 2, "end": 5},
  "realization": {"clause_ref": "c1", "relation": "same_span_alias"}
}
```

The relation is one of `same_span_alias`, `expanded_realization`,
`shared_subject_projection`, or `other`. Same-span aliases must have equal
spans; expanded realizations must contain the clause span. This prevents a
clause field and wrapper field from silently supplying two conflicting truths.
Legacy fields such as `legacy_function` may be retained as migration evidence,
but validators and renderers never treat them as clause-level function truth.

## Scoped partial coverage

`annotation_scope.coverage` is `task_focused_partial` or
`complete_constituency`. The `annotation_scope.dimensions` list gives each
dimension, scope (`record`, `node`, or `region`), completeness (`complete` or
`partial`), and omission (`none`, `intentional`, or `not_applicable`). Optional
`evidence` distinguishes `present`, genuinely `empty`, and `unannotated`.
The compatibility summaries `annotated_dimensions` and
`intentionally_omitted` may be retained but are not authoritative.

An empty dependency list with `evidence: "empty", omission: "none"` means the
annotated answer is genuinely empty. An unannotated dependency dimension uses
`evidence: "unannotated", omission: "intentional"`. A dimension cannot be
both annotated and omitted. Complete constituency requires actual constituent
structure. Capability tags express pedagogical/evaluation intent; the
validator requires a compatible annotated dimension but does not infer whether
the construction is present. Presence evidence belongs in `construction_tags`.
For an empty dependency list the validator requires one of these explicit
evidence states, so an empty list cannot silently stand for missing annotation.
Scorers can call `coverage_allows_score(record, dimension, target)` before
penalizing a missing node; a complete region only authorizes targets whose
spans lie inside that region.

## Migration guarantees

The superseded migrator accepted a release-labelled source. V0.4 instead
accepts only the real wire `schema_version: "0.2"`; V0.3, unknown,
and higher reviewed records are no-ops. Only direct mappings from explicit old
fields are applied. Function labels, first words, suffixes, keyword lists, and
surface forms never infer clause type/status/form or markers. Ambiguous values
become `unresolved` and `review_required`, with legacy evidence retained.
Fixture-specific repairs are in `scripts/repair_v031_data.py`, not the generic
migration. Re-running migration on V0.4 is an exact no-op and never overwrites
review status, reviewer, date, provenance, or migration notes. If an older
record already has a scoped annotation object it is preserved; a legacy
record-level scope is retained under `legacy_annotation_scope` when a new
scoped contract must be synthesized.

## SFT governance

`scripts/render_sft.py` emits a learner-facing linguistic projection by default.
Record ID, schema version, split, source/difficulty, capability intent, annotation scope,
provenance, migration metadata, and review metadata are stored in a separate
`governance_sidecar`, not in assistant supervision. Migration-only nested
fields such as `legacy_function` are likewise retained in the sidecar's
`legacy_annotations`. `--include-governance` is an explicit debug mode.
`scripts/train_sft.py` normally accepts only
`linguistically_reviewed` or `canonical_gold` records and always rejects the
`benchmark` split. `schema_migrated`, `review_required`, and
`structurally_validated` require explicit `--development-mode` and are never
the default training path.
