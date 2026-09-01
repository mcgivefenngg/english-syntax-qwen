# Evaluation benchmark

The V0.2-migrated held-out source is [`../benchmark_v1.jsonl`](../benchmark_v1.jsonl). It contains exactly 50 canonical records: the ten `legacy_baseline` sentences used during environment bring-up and forty newly authored lexical/surface forms. Migration changes only the schema representation (`schema_version`, node kinds, clause/phrase fields, external POS mappings, and canonical-analysis key); it does not re-review or rewrite the linguistic gold. All records use `split: "benchmark"`; the legacy ten are identified by `source_type: "legacy_baseline"`.

Benchmark records are evaluation-only. Do not copy them, their simple noun substitutions, or their obvious paraphrases into `data/gold`, `data/reviewed`, `data/splits`, or `data/generated`. Run `scripts/check_contamination.py` against every such path before publishing. Store generated evaluation results under `eval/benchmark/results/`; result files are ignored by Git.

Each line is canonical gold, not an SFT conversation. The `canonical_analysis` field, established framework alternatives, rejected analyses, contrast groups, and (where applicable) error-diagnosis rubric are available to an evaluator or renderer.
