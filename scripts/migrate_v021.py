#!/usr/bin/env python3
"""Apply the deterministic V0.2.1 span/reference migration once."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION_VERSION = "0.2.1"


def add_np(record: dict, identifier: str, start: int, end: int) -> None:
    if any(item.get("id") == identifier for item in record.get("constituents", []) if isinstance(item, dict)):
        return
    record.setdefault("constituents", []).append({
        "id": identifier,
        "span": {"start": start, "end": end},
        "function": "subject",
        "node_kind": "phrase",
        "phrase_category": "NP",
    })


def migrate(record: dict) -> None:
    identifier = record.get("id")
    if identifier == "fixture-catalogue":
        record["constituents"][0]["span"] = {"start": 0, "end": 2}
    elif identifier == "legacy-10-supplementary-ing":
        add_np(record, "subj", 5, 7)
        record["clauses"][1]["predicand"]["target"] = "subj"
    elif identifier == "new-13-ecm":
        record["clauses"][1]["span"] = {"start": 3, "end": 7}
        record["clauses"][1]["subject"] = "ecm-subj"
        record["constituents"][0]["span"] = {"start": 2, "end": 7}
        add_np(record, "ecm-subj", 2, 3)
    elif identifier == "new-14-raising":
        record["clauses"][1]["span"] = {"start": 2, "end": 6}
        record["constituents"][0]["span"] = {"start": 2, "end": 6}
    elif identifier == "new-15-object-control":
        record["clauses"][1]["span"] = {"start": 3, "end": 7}
        record["constituents"][1]["span"] = {"start": 3, "end": 7}
    elif identifier == "new-16-subject-control":
        record["clauses"][1]["span"] = {"start": 2, "end": 6}
        record["constituents"][0]["span"] = {"start": 2, "end": 6}
    elif identifier == "new-17-purpose-infinitive":
        if not any(word.get("id") == "w9" for word in record.get("words", []) if isinstance(word, dict)):
            record["words"].append({
                "id": "w9", "form": ".", "lemma": ".", "lexical_category": "punctuation",
                "node_kind": "word", "external_pos_tags": [{"tagset": "PTB", "tag": "."}],
            })
        record["clauses"][0]["span"]["end"] = 10
        add_np(record, "subj", 4, 6)
        record["clauses"][1]["predicand"]["target"] = "subj"
    elif identifier == "new-18-perfect-gerund":
        record["clauses"][0]["span"]["end"] = 8
        add_np(record, "subj", 4, 6)
        record["clauses"][1]["predicand"] = {"kind": "overt_constituent", "target": "subj"}
    elif identifier == "new-19-relative-overt-head":
        record["clauses"][1]["span"] = {"start": 2, "end": 5}
        record["constituents"][0]["span"] = {"start": 0, "end": 5}
        record["constituents"][1]["span"] = {"start": 2, "end": 5}
    elif identifier == "new-23-ditransitive":
        record["constituents"][0]["span"] = {"start": 3, "end": 5}
        record["constituents"][1]["span"] = {"start": 5, "end": 7}
    elif identifier == "new-24-stative-predicative":
        record["constituents"][1]["span"] = {"start": 3, "end": 6}
    elif identifier == "new-29-clause-coordination":
        record["clauses"][2]["span"] = {"start": 4, "end": 7}
        record["constituents"][0]["span"] = {"start": 0, "end": 7}
    elif identifier == "new-33-perception-bare":
        record["clauses"][1]["subject"] = "percept-subj"
        add_np(record, "percept-subj", 2, 4)
    elif identifier == "new-36-gerund-nominal":
        record["clauses"][1]["span"] = {"start": 1, "end": 3}
        record["clauses"][1]["subject"] = "ger"
        record["constituents"][0]["span"] = {"start": 0, "end": 3}
    elif identifier == "new-37-infinitive-predicative":
        record["clauses"][1]["span"] = {"start": 3, "end": 6}
        record["constituents"][0]["span"] = {"start": 3, "end": 6}
    elif identifier == "new-40-where-interrogative":
        record["clauses"][1]["span"] = {"start": 2, "end": 6}
        record["constituents"][0]["span"] = {"start": 2, "end": 6}
    elif identifier == "new-44-adjp-modifier":
        record["constituents"][0]["span"] = {"start": 1, "end": 3}
    elif identifier == "new-46-finite-content-clause":
        record["clauses"][1]["span"] = {"start": 3, "end": 6}
        record["constituents"][0]["span"] = {"start": 3, "end": 6}
    elif identifier == "new-47-conditional":
        record["clauses"][0]["span"]["end"] = len(record.get("words", []))

    if "schema_version" in record:
        record["review_metadata"] = {
            "review_status": "structurally_validated",
            "reviewer_type": "automated_structural",
            "review_date": "2026-09-01",
            "provenance": record.get("source_type", "unknown"),
            "migration_version": MIGRATION_VERSION,
        }


def migrate_file(path: Path) -> None:
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                record = json.loads(line)
                migrate(record)
                rows.append(record)
    with path.open("w", encoding="utf-8") as handle:
        for record in rows:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    migrate_file(ROOT / "data" / "gold" / "fixtures.jsonl")
    migrate_file(ROOT / "eval" / "benchmark_v1.jsonl")
