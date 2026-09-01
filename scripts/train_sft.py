#!/usr/bin/env python3
"""Train a BF16 LoRA adapter for text-only English syntax tutoring."""

from __future__ import annotations

import argparse
from pathlib import Path

import unsloth
import torch
from datasets import load_dataset
from transformers import set_seed
from trl import SFTConfig, SFTTrainer
from unsloth import FastVisionModel
from unsloth.trainer import UnslothVisionDataCollator


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
    return parser.parse_args()


def require_cuda() -> None:
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required; refusing to start a CPU fallback training run")
    if not torch.cuda.is_bf16_supported():
        raise RuntimeError("BF16 is required for this training configuration")


def main() -> None:
    arguments = parse_args()
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
