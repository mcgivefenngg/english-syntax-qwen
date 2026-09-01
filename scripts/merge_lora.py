#!/usr/bin/env python3
"""Merge a saved Unsloth LoRA adapter into a BF16 Hugging Face model."""

from __future__ import annotations

import argparse
from pathlib import Path

from unsloth import FastVisionModel


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("adapter_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    arguments = parser.parse_args()

    model, tokenizer = FastVisionModel.from_pretrained(
        model_name=str(arguments.adapter_dir),
        load_in_4bit=False,
    )
    model.save_pretrained_merged(
        str(arguments.output_dir),
        tokenizer,
        save_method="merged_16bit",
    )
    print(f"Merged BF16/16-bit Hugging Face model written to {arguments.output_dir}")


if __name__ == "__main__":
    main()
