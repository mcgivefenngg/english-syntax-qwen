#!/usr/bin/env python3
"""Detect deterministic lexical and construction-frame leakage from a held-out benchmark."""

from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path

try:
    from data_common import construction_signature, extract_texts, iter_jsonl_paths, lexical_overlap, levenshtein, normalized_text, read_jsonl, sentence_from_record, skeleton, tokens
except ImportError:
    from scripts.data_common import construction_signature, extract_texts, iter_jsonl_paths, lexical_overlap, levenshtein, normalized_text, read_jsonl, sentence_from_record, skeleton, tokens


def compare(benchmark: str, candidate: str) -> list[str]:
    reasons: list[str] = []
    benchmark_normalized, candidate_normalized = normalized_text(benchmark), normalized_text(candidate)
    if benchmark == candidate:
        reasons.append("exact sentence match")
    if benchmark_normalized == candidate_normalized:
        reasons.append("normalized sentence match")
    if benchmark_normalized and benchmark_normalized in candidate_normalized:
        reasons.append("benchmark sentence embedded in candidate text")
    overlap = lexical_overlap(benchmark, candidate)
    sequence_ratio = difflib.SequenceMatcher(None, benchmark_normalized, candidate_normalized).ratio()
    distance = levenshtein(tokens(benchmark), tokens(candidate))
    token_count = max(len(tokens(benchmark)), len(tokens(candidate)), 1)
    if overlap >= 0.80 and sequence_ratio >= 0.82:
        reasons.append(f"high lexical/sequence overlap ({overlap:.2f}/{sequence_ratio:.2f})")
    if distance <= max(1, round(token_count * 0.12)) and sequence_ratio >= 0.72:
        reasons.append(f"near duplicate (token edit distance {distance})")
    if skeleton(benchmark) == skeleton(candidate) and distance <= 4 and overlap >= 0.60:
        reasons.append("simple lexical substitution/paraphrase skeleton")
    return reasons


def _signature_key(record: dict) -> tuple | None:
    signature = construction_signature(record)
    if not isinstance(signature, dict):
        return None
    if not isinstance(signature.get("argument_pattern"), list) or not isinstance(signature.get("function_pattern"), list):
        return None
    return (
        signature.get("predicate_lemma"), signature.get("construction_type"),
        tuple(signature.get("argument_pattern", [])), tuple(signature.get("function_pattern", [])),
    )


def check_contamination(benchmark_path: Path, dataset_paths: list[Path]) -> list[str]:
    benchmark_rows = read_jsonl(benchmark_path)
    benchmark_sentences = [(line, sentence_from_record(record), record.get("id", f"line-{line}"), _signature_key(record)) for line, record in benchmark_rows]
    findings: list[str] = []
    for requested_path in dataset_paths:
        if not requested_path.exists():
            findings.append(f"{requested_path}: input path does not exist")
    for path in iter_jsonl_paths(dataset_paths):
        for line, record in read_jsonl(path):
            candidate_texts = extract_texts(record)
            candidate_sentence = sentence_from_record(record)
            if candidate_sentence:
                candidate_texts = [candidate_sentence] + [text for text in candidate_texts if text != candidate_sentence]
            if not candidate_texts:
                continue
            candidate_signature = _signature_key(record)
            for benchmark_line, benchmark_sentence, benchmark_id, benchmark_signature in benchmark_sentences:
                if not benchmark_sentence:
                    continue
                if candidate_signature is not None and candidate_signature == benchmark_signature and normalized_text(candidate_sentence or "") != normalized_text(benchmark_sentence):
                    findings.append(f"{path}:{line} conflicts with benchmark {benchmark_id} (line {benchmark_line}): construction signature match ({candidate_signature[0]} / {candidate_signature[1]})")
                    break
                for candidate_text in candidate_texts:
                    reasons = compare(benchmark_sentence, candidate_text)
                    if reasons:
                        findings.append(f"{path}:{line} conflicts with benchmark {benchmark_id} (line {benchmark_line}): {'; '.join(reasons)}")
                        break
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path, help="training, validation, or generated JSONL files/directories")
    parser.add_argument("--benchmark", type=Path, default=Path("eval/benchmark_v1.jsonl"))
    arguments = parser.parse_args()
    if not arguments.benchmark.exists():
        print(f"Benchmark not found: {arguments.benchmark}", file=sys.stderr)
        return 2
    try:
        findings = check_contamination(arguments.benchmark, arguments.paths)
    except ValueError as error:
        print(f"Contamination check failed: {error}", file=sys.stderr)
        return 1
    if findings:
        print("Contamination detected:", file=sys.stderr)
        print("\n".join(f"- {finding}" for finding in findings), file=sys.stderr)
        return 1
    print("No benchmark contamination detected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
