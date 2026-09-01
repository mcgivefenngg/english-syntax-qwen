#!/usr/bin/env python3
"""Render canonical gold annotations into configurable chat SFT JSONL."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    from data_common import read_jsonl
except ImportError:
    from scripts.data_common import read_jsonl

DEFAULT_SYSTEM = "You are English Syntax Tutor. Distinguish lexical category, phrase category, syntactic function, semantic role, and framework-specific terminology."


def render_user(record: dict[str, Any]) -> str:
    if record.get("error_diagnosis"):
        return f"Diagnose the following proposed syntax analysis.\nSentence: {record['sentence']}\nProposed analysis: {record['error_diagnosis']['student_analysis']}"
    return f"Analyze the syntax of this sentence and explain the important constructions.\nSentence: {record['sentence']}"


def render_assistant(record: dict[str, Any]) -> str:
    canonical = record.get("canonical_analysis", record.get("preferred_analysis"))
    payload: dict[str, Any] = {
        "canonical_analysis": canonical,
        "clauses": record.get("clauses", []),
        "constituents": record.get("constituents", []),
        "explanation": record["explanation"],
    }
    for key in ("framework_alternatives", "alternative_analyses", "pedagogical_aliases", "fusion_relations", "ambiguity", "construction_signature", "rejected_analyses", "error_diagnosis"):
        if key in record:
            payload[key] = record[key]
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def render_record(record: dict[str, Any], system_prompt: str = DEFAULT_SYSTEM) -> dict[str, Any]:
    return {
        "id": record["id"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": render_user(record)},
            {"role": "assistant", "content": render_assistant(record)},
        ],
    }


def render_files(input_paths: list[Path], output_path: Path, system_prompt: str = DEFAULT_SYSTEM, split: str | None = None) -> int:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with output_path.open("w", encoding="utf-8") as output:
        for input_path in input_paths:
            for line_number, record in read_jsonl(input_path):
                if split is not None and record.get("split") != split:
                    continue
                try:
                    rendered = render_record(record, system_prompt)
                except KeyError as error:
                    raise ValueError(f"{input_path}:{line_number}: cannot render missing field {error.args[0]!r}") from error
                output.write(json.dumps(rendered, ensure_ascii=False) + "\n")
                count += 1
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path, help="canonical JSONL files")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--system-prompt", default=DEFAULT_SYSTEM)
    parser.add_argument("--split", choices=("train", "validation", "benchmark"), help="render only records assigned to this split")
    arguments = parser.parse_args()
    try:
        count = render_files(arguments.inputs, arguments.output, arguments.system_prompt, arguments.split)
    except (OSError, ValueError) as error:
        print(f"Rendering failed: {error}", file=sys.stderr)
        return 1
    print(f"Rendered {count} example(s) to {arguments.output}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
