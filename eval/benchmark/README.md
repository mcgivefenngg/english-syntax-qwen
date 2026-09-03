# Evaluation benchmark

The V0.4 held-out source is [`../benchmark_v1.jsonl`](../benchmark_v1.jsonl). It contains exactly 50 records: the ten `legacy_baseline` sentences used during environment bring-up and forty newly authored lexical/surface forms. Wire migration and any separate fixture repair preserve existing claims; framework-sensitive items remain `review_required` rather than guessed. All records use `schema_version: "0.4"`, `split: "benchmark"`, and automated review metadata; none is a claim of canonical linguistic gold or training approval. Schema/structural validation passing is therefore not a claim that the preferred syntax is linguistically correct.

Benchmark records are evaluation-only. Do not copy them, their simple noun substitutions, or their obvious paraphrases into `data/gold`, `data/reviewed`, `data/splits`, or `data/generated`. Run `scripts/check_contamination.py` against every such path before publishing. Store generated evaluation results under `eval/benchmark/results/`; result files are ignored by Git.

Each line is a canonical-format evaluation record, not an SFT conversation. The `canonical_analysis` field, established framework alternatives, rejected analyses, contrast groups, and (where applicable) error-diagnosis rubric are available to an evaluator or renderer, subject to the review-status gate above.
