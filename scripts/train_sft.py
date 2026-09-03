#!/usr/bin/env python3
"""Train a BF16 LoRA adapter for text-only English syntax tutoring."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from data_common import read_jsonl
except ImportError:
    from scripts.data_common import read_jsonl
try:
    from render_sft import render_assistant
except ImportError:
    from scripts.render_sft import render_assistant


APPROVED_REVIEW_STATUSES = {"approved_for_training", "canonical_gold"}
BLOCKED_REVIEW_STATUSES = {"schema_migrated", "review_required", "structurally_validated"}


def _unresolved_content(record: dict) -> list[str]:
    findings: list[str] = []
    for index, word in enumerate(record.get("words", []) if isinstance(record.get("words"), list) else []):
        if isinstance(word, dict) and isinstance(word.get("lexical_analysis"), dict) and word["lexical_analysis"].get("status") == "unresolved":
            findings.append(f"words[{index}].lexical_analysis")
    for index, clause in enumerate(record.get("clauses", []) if isinstance(record.get("clauses"), list) else []):
        if not isinstance(clause, dict):
            continue
        if clause.get("clause_construction") == "unresolved" or "unresolved" in (clause.get("integration") or []):
            findings.append(f"clauses[{index}]")
        if clause.get("finiteness") == "unspecified":
            findings.append(f"clauses[{index}].finiteness")
    analyses = []
    for field in ("canonical_analysis", "preferred_analysis"):
        if isinstance(record.get(field), dict):
            analyses.append((field, record[field]))
    for field in ("alternative_analyses",):
        for index, analysis in enumerate(record.get(field, []) if isinstance(record.get(field), list) else []):
            if isinstance(analysis, dict):
                analyses.append((f"{field}[{index}]", analysis))
    for path, analysis in analyses:
        typed = analysis.get("typed_analysis")
        if isinstance(typed, dict) and typed.get("status") in {"unresolved", "review_required"}:
            findings.append(f"{path}.typed_analysis")
    if record.get("migration_review_required") is True:
        findings.append("migration_review_required")
    if isinstance(record.get("migration_metadata"), dict) and record["migration_metadata"].get("review_required") is True:
        findings.append("migration_metadata.review_required")
    metadata = record.get("review_metadata") if isinstance(record.get("review_metadata"), dict) else {}
    if metadata.get("review_status") == "canonical_gold":
        required = {"tokens", "lexical_category", "phrase_constituency", "clause_ontology", "syntactic_function"}
        complete = {
            entry.get("dimension") for entry in (record.get("annotation_scope", {}).get("dimensions", []) if isinstance(record.get("annotation_scope"), dict) else [])
            if isinstance(entry, dict)
            and entry.get("omission") == "none"
            and entry.get("completeness") == "complete"
            and isinstance(entry.get("scope"), dict)
            and entry["scope"].get("kind") == "record"
        }
        findings.extend(f"coverage.{dimension}" for dimension in sorted(required - complete))
    return findings


def _omitted_fields(record: dict) -> set[str]:
    fields = set()
    scope = record.get("annotation_scope") if isinstance(record.get("annotation_scope"), dict) else {}
    mapping = {"dependencies": "dependencies", "semantic_roles": "semantic_roles", "lexical_valency": "lexical_valency", "clause_ontology": "clauses", "clause_structure": "clauses", "phrase_constituency": "constituents", "constituency": "constituents", "np_internal_constituency": "constituents", "syntactic_function": "constituents", "framework_mapping": "framework", "construction_relations": "construction_signature"}
    declared = set()
    for entry in scope.get("dimensions", []) if isinstance(scope, dict) else []:
        if not isinstance(entry, dict):
            continue
        dimension = entry.get("dimension")
        declared.add(dimension)
        if (entry.get("omission") in {"intentional", "not_applicable"} or entry.get("completeness") in {"unannotated", "omitted", "out_of_scope"}) and entry.get("scope", {}).get("kind") == "record" and dimension in mapping:
            fields.add(mapping[dimension])
    declared_fields = {mapping.get(dimension) for dimension in declared}
    fields.update(mapping[dimension] for dimension in mapping if dimension not in declared and mapping[dimension] not in declared_fields)
    return fields


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-name", default="Qwen/Qwen3.5-4B")
    parser.add_argument("--train-file", type=Path, default=Path("data/splits/train.jsonl"))
    parser.add_argument("--eval-file", type=Path, default=Path("data/splits/eval.jsonl"))
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/qwen3.5-4b-english-syntax-lora"))
    parser.add_argument("--max-seq-length", type=int, default=4096)
    parser.add_argument("--per-device-train-batch-size", type=int, default=1)
    parser.add_argument("--gradient-accumulation-steps", type=int, default=8)
    parser.add_argument("--num-train-epochs", type=float, default=1.0)
    parser.add_argument("--learning-rate", type=float, default=2e-4)
    parser.add_argument("--seed", type=int, default=3407)
    parser.add_argument("--development-mode", action="store_true", help="explicit debug mode; permits unreviewed/non-training records")
    return parser.parse_args()


def _canonical_from_rendered(record: dict) -> tuple[dict, dict]:
    sidecar = record.get("governance_sidecar") if isinstance(record.get("governance_sidecar"), dict) else {}
    try:
        payload = json.loads(record["messages"][-1]["content"])
    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
        payload = {}
    canonical = dict(payload) if isinstance(payload, dict) else {}
    canonical["id"] = record.get("id")
    return canonical, sidecar


def validate_training_input(paths: list[Path], *, development_mode: bool = False) -> list[str]:
    """Return deterministic training-gate errors without importing ML stacks."""
    errors: list[str] = []
    for path in paths:
        try:
            rows = read_jsonl(path)
        except (OSError, ValueError) as error:
            errors.append(f"{path}: cannot read training input: {error}")
            continue
        for line, record in rows:
            canonical = record
            governance = record
            if "messages" in record:
                canonical, sidecar = _canonical_from_rendered(record)
                governance = dict(sidecar)
                governance.setdefault("split", record.get("split"))
                if isinstance(sidecar, dict):
                    canonical.setdefault("schema_version", sidecar.get("schema_version"))
                    canonical.setdefault("annotation_scope", sidecar.get("annotation_scope"))
                if governance.get("schema_version") not in {None, "0.4"} and not development_mode:
                    errors.append(f"{path}:{line}: rendered target does not identify V0.4")
            metadata = governance.get("review_metadata")
            status = metadata.get("review_status") if isinstance(metadata, dict) else governance.get("review_status")
            reviewer_type = metadata.get("reviewer_type") if isinstance(metadata, dict) else None
            split = governance.get("split")
            if split == "benchmark" and not development_mode:
                errors.append(f"{path}:{line}: benchmark split is never accepted by the normal training path")
            if status in BLOCKED_REVIEW_STATUSES and not development_mode:
                errors.append(f"{path}:{line}: review status {status!r} is not approved for training")
            if status not in APPROVED_REVIEW_STATUSES and not development_mode:
                errors.append(f"{path}:{line}: training requires explicit approved_for_training or canonical_gold status")
            if status in APPROVED_REVIEW_STATUSES and reviewer_type not in {"independent_linguistic", "human_annotation", "mixed"} and not development_mode:
                errors.append(f"{path}:{line}: approved training status requires human or independent linguistic review")
            if not development_mode:
                if "messages" in record and "content_flags" not in governance:
                    errors.append(f"{path}:{line}: rendered target is missing the governance content_flags snapshot")
                if canonical.get("schema_version") != "0.4":
                    errors.append(f"{path}:{line}: normal training requires canonical schema_version='0.4'")
                unresolved = _unresolved_content(canonical)
                if isinstance(governance.get("content_flags"), list):
                    unresolved.extend(
                        str(flag) for flag in governance["content_flags"]
                        if isinstance(flag, str) and flag not in unresolved
                    )
                if unresolved:
                    errors.append(f"{path}:{line}: unresolved linguistic content is not eligible for normal SFT ({', '.join(unresolved)})")
                payload = canonical
                if "messages" in record:
                    try:
                        payload = json.loads(record["messages"][-1]["content"])
                    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
                        payload = {}
                else:
                    try:
                        payload = json.loads(render_assistant(canonical))
                    except (TypeError, ValueError, json.JSONDecodeError):
                        payload = {}
                if isinstance(payload, dict):
                    leaked = _omitted_fields(canonical) & set(payload)
                    if leaked:
                        errors.append(f"{path}:{line}: omitted/unannotated dimensions appear in assistant target: {sorted(leaked)}")
                    for index, word in enumerate(payload.get("words", []) if isinstance(payload.get("words"), list) else []):
                        if isinstance(word, dict) and (word.get("lexical_category") is None or "lexical_analysis" in word):
                            errors.append(f"{path}:{line}: unresolved lexical payload is not eligible for normal SFT (words[{index}])")
                    for index, clause in enumerate(payload.get("clauses", []) if isinstance(payload.get("clauses"), list) else []):
                        if isinstance(clause, dict) and (clause.get("clause_construction") == "unresolved" or "unresolved" in (clause.get("integration") or [])):
                            errors.append(f"{path}:{line}: unresolved clause payload is not eligible for normal SFT (clauses[{index}])")
    return errors


def require_cuda() -> None:
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required; refusing to start a CPU fallback training run")
    if not torch.cuda.is_bf16_supported():
        raise RuntimeError("BF16 is required for this training configuration")


def main() -> None:
    arguments = parse_args()
    gate_errors = validate_training_input([arguments.train_file] + ([arguments.eval_file] if arguments.eval_file.exists() else []), development_mode=arguments.development_mode)
    if gate_errors:
        raise RuntimeError("Training gate refused input:\n" + "\n".join(f"- {error}" for error in gate_errors))
    import unsloth
    import torch
    from datasets import load_dataset
    from transformers import set_seed
    from trl import SFTConfig, SFTTrainer
    from unsloth import FastVisionModel
    from unsloth.trainer import UnslothVisionDataCollator
    require_cuda()
    set_seed(arguments.seed)

    data_files = {"train": str(arguments.train_file)}
    if arguments.eval_file.exists():
        data_files["eval"] = str(arguments.eval_file)
    dataset = load_dataset("json", data_files=data_files)

    model, tokenizer = FastVisionModel.from_pretrained(
        model_name=arguments.model_name,
        load_in_4bit=False,
        use_gradient_checkpointing="unsloth",
    )
    model = FastVisionModel.get_peft_model(
        model,
        finetune_vision_layers=False,
        finetune_language_layers=True,
        finetune_attention_modules=True,
        finetune_mlp_modules=True,
        r=16,
        lora_alpha=16,
        lora_dropout=0,
        bias="none",
        random_state=arguments.seed,
        use_rslora=False,
        loftq_config=None,
    )
    FastVisionModel.for_training(model)

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        data_collator=UnslothVisionDataCollator(model, tokenizer),
        train_dataset=dataset["train"],
        eval_dataset=dataset.get("eval"),
        args=SFTConfig(
            per_device_train_batch_size=arguments.per_device_train_batch_size,
            per_device_eval_batch_size=1,
            gradient_accumulation_steps=arguments.gradient_accumulation_steps,
            num_train_epochs=arguments.num_train_epochs,
            learning_rate=arguments.learning_rate,
            warmup_ratio=0.03,
            logging_steps=1,
            save_steps=100,
            eval_steps=100,
            eval_strategy="steps" if "eval" in dataset else "no",
            optim="adamw_8bit",
            weight_decay=0.001,
            lr_scheduler_type="linear",
            seed=arguments.seed,
            output_dir=str(arguments.output_dir),
            report_to="tensorboard",
            bf16=True,
            fp16=False,
            tf32=True,
            remove_unused_columns=False,
            dataset_text_field="",
            dataset_kwargs={"skip_prepare_dataset": True},
            max_length=arguments.max_seq_length,
        ),
    )
    trainer.train()
    trainer.save_model(str(arguments.output_dir))
    tokenizer.save_pretrained(str(arguments.output_dir))


if __name__ == "__main__":
    main()
