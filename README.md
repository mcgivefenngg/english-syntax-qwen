# English Syntax Tutor — Qwen3.5-4B

This repository is a clean, reproducible WSL2 workspace for fine-tuning Qwen3.5-4B as an English Syntax Tutor:

```text
Qwen3.5-4B
  -> BF16 LoRA / SFT
  -> merged 16-bit Hugging Face safetensors
  -> GGUF
  -> Q4_K_S / Q4_K_M
  -> LM Studio / PocketPal validation
```

The environment setup does not download Qwen model weights and does not start training. Model downloads happen only when `scripts/train_sft.py` or another explicit model-loading command is run.

## Current target environment

The initial probe found:

- Ubuntu `24.04.4 LTS` on WSL2 kernel `6.18.33.2-microsoft-standard-WSL2`.
- Python `3.12.3` is the system interpreter. Python 3.12 is selected for this project because the official Unsloth Blackwell guide uses Python 3.12 and the current Ubuntu 24.04 archive does not provide a separate Python 3.11 runtime in this environment.
- The project, virtual environment, Hugging Face cache, datasets, outputs, and checkpoints must remain under the Linux filesystem. Do not use `/mnt/c` for them.
- NVIDIA Linux display drivers are intentionally not installed. WSL uses the Windows host NVIDIA driver through `/dev/dxg`.

Run the GPU checks below in a normal Ubuntu WSL terminal, not a restricted Codex sandbox:

```bash
cd ~/projects/english-syntax-qwen
source env.sh
nvidia-smi
test -e /dev/dxg
```

The expected GPU is an RTX 5070 Ti with 16 GiB VRAM and Blackwell compute capability `12.0`.

## Version decisions

The pins below were selected on 2026-09-01 after checking the official Unsloth Blackwell guide, the official Qwen3.5 model card/configuration, PyTorch's CUDA wheel index, and package metadata:

| Component | Pin | Reason |
| --- | --- | --- |
| Python | `3.12` | Official Unsloth Blackwell guide uses 3.12; native Ubuntu 24.04 runtime |
| PyTorch | `2.11.0+cu128` | CUDA 12.8 wheel; newest stable release allowed by Unsloth `torch<2.12` |
| torchvision | `0.26.0+cu128` | Matching PyTorch 2.11.0 CUDA wheel |
| Triton | `3.6.0` | Exact Triton dependency of PyTorch 2.11.0; above Unsloth Blackwell minimum |
| Unsloth | `2026.8.22` | Current stable PyPI package at setup time |
| Unsloth Zoo | `2026.8.16` | Required by Unsloth 2026.8.22 |
| Transformers | `5.5.0` | Highest version allowed by Unsloth 2026.8.22 and supports Qwen3.5 |
| Datasets | `4.3.0` | Highest version allowed by Unsloth 2026.8.22 |
| TRL | `0.24.0` | Highest version allowed by Unsloth 2026.8.22 |
| PEFT | `0.20.0` | Current compatible release; satisfies Unsloth `>=0.18.0` |
| Accelerate | `1.14.0` | Current compatible release |
| bitsandbytes | `0.50.2` | Current CUDA/Blackwell-compatible release for optional 8-bit optimizer |
| qwen-vl-utils | `0.0.14` | Qwen3.5 multimodal preprocessing dependency |
| TensorBoard | `2.21.0` | Training log viewer |

The lock file records all transitive versions and hashes. `xformers` is not requested directly; native PyTorch SDPA is used to avoid an unnecessary source build on WSL. Unsloth's dependency resolver may still select a compatible `xformers` wheel if required by the published package metadata.

## One-time system prerequisites

The Codex sandbox cannot use `sudo`. Run this block once in a normal Ubuntu WSL terminal:

```bash
sudo apt-get update
sudo apt-get install -y build-essential cmake ninja-build pkg-config curl python3.12-dev
```

Building `llama.cpp` with `GGML_CUDA=ON` also needs a CUDA compiler. The PyTorch wheel supplies CUDA runtime libraries but not `nvcc`. Install only the toolkit package matching CUDA 12.8; do not install `nvidia-driver`, `cuda`, or a Linux display driver:

```bash
cd ~/projects/english-syntax-qwen
bash scripts/install_cuda_toolkit.sh
```

The installer uses the official NVIDIA WSL repository and also installs `python3.12-dev`, which is needed by Unsloth's local CUDA/Python helper. The URL is kept inside the script so it cannot be split into a separate shell command when copied.

Verify the prerequisite from the normal WSL terminal:

```bash
nvcc --version
nvidia-smi
ls -l /dev/dxg
```

If the NVIDIA repository already exists, skip the keyring download and install the toolkit package directly. No Linux NVIDIA driver should appear in `dpkg -l`.

## Create or rebuild the Python environment

`uv` is installed as a user-level binary at `~/.local/bin/uv`. Start a new shell or ensure it is on `PATH`:

```bash
export PATH="$HOME/.local/bin:$PATH"
cd ~/projects/english-syntax-qwen
source env.sh
uv sync --locked
```

To install `uv` from scratch as a user-level tool, run the official installer without `sudo`:

```bash
curl --proto '=https' --tlsv1.2 -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
```

If the lock file is intentionally regenerated after changing a direct pin:

```bash
uv lock
uv sync --locked
```

The environment lives at `.venv` under the Linux project directory. Confirm its interpreter and package versions:

```bash
uv run python --version
uv run python -c 'import torch; print(torch.__version__, torch.version.cuda)'
```

## Health check

Run this only after `uv sync --locked`, and run the final GPU result in a normal Ubuntu WSL terminal:

```bash
cd ~/projects/english-syntax-qwen
source env.sh
uv run python scripts/health_check.py
```

The check deliberately fails when CUDA is unavailable. It does not silently fall back to CPU. It verifies `nvidia-smi`, the absence of Linux NVIDIA driver packages, `torch.cuda.is_available()`, device name, CUDA runtime, BF16 support, a BF16 CUDA matrix multiplication, a 256 MiB CUDA allocation, an actual Triton CUDA kernel, Unsloth import, and the `llama-cli`/`llama-quantize` binaries.

The CUDA toolkit check reports `nvcc` separately from the PyTorch CUDA runtime. A CUDA-enabled `llama.cpp` build requires the compiler; the PyTorch wheel alone does not provide it. The final GPU health check must be run from an ordinary Ubuntu WSL terminal. A restricted Codex sandbox may report `/dev/dxg`, NVML, or the `llama-cli` CUDA runtime as unavailable even when the WSL installation is healthy.

## llama.cpp CUDA build

The source tree is pinned to commit/tag `b10731` from the `ggml-org/llama.cpp` repository. This rolling release was the repository's current tagged release at setup time; the exact commit is recorded in `third_party/llama.cpp/.git` and should be preserved for reproducibility.

Clone and build after the one-time prerequisites are present:

```bash
cd ~/projects/english-syntax-qwen
git clone --branch b10731 --depth 1 https://github.com/ggml-org/llama.cpp.git third_party/llama.cpp
cd third_party/llama.cpp
cmake -S . -B build -G Ninja \
  -DGGML_CUDA=ON \
  -DGGML_NATIVE=ON \
  -DCMAKE_CUDA_ARCHITECTURES=120 \
  -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release --parallel
cd ../..
```

The equivalent reproducible wrapper is `scripts/build_llama.sh`; it refuses to run if `cmake`, `ninja`, or `nvcc` is missing.

Validate the binaries:

```bash
third_party/llama.cpp/build/bin/llama-cli --version
third_party/llama.cpp/build/bin/llama-quantize --help
```

The build is CUDA-enabled but no large model or inference benchmark is required during environment setup.

The completed setup used CUDA toolkit `12.8`, `nvcc 12.8.93`, GCC `13.3.0`, CMake `3.28.3`, and Ninja `1.11.1`. The build configured `GGML_CUDA=ON` for Blackwell architecture `120` and produced both required binaries. The build environment did not include NCCL, so multi-GPU/NCCL features are not part of this single-GPU project. OpenSSL was also unavailable during the build; that only disables optional network download support in llama.cpp and does not affect local GGUF conversion or inference.

## Final WSL verification

The authoritative checks were run in an ordinary Ubuntu WSL shell on 2026-09-01, after installing `cuda-toolkit-12-8` and `python3.12-dev`:

- Ubuntu `24.04.4 LTS`; kernel `6.18.33.2-microsoft-standard-WSL2`; `/dev/dxg` present.
- NVIDIA GeForce RTX 5070 Ti; driver `610.74`; `16303 MiB` total VRAM; NVIDIA-SMI CUDA UMD `13.3`.
- Python `3.12.3`; Git `2.43.0`; GCC `13.3.0`; CMake `3.28.3`; Ninja `1.11.1`; uv `0.12.8`.
- PyTorch `2.11.0+cu128`; CUDA runtime `12.8`; `torch.cuda.is_available()` and BF16 matrix operation pass; capability is `(12, 0)`.
- Triton `3.6.0` real CUDA kernel pass; Unsloth `2026.8.22` import pass; no Linux NVIDIA display-driver package detected.
- llama.cpp commit `0eadefebd3f8f92a86d634a0e5b8fffc9dc792c0`; `GGML_CUDA=ON`; `CMAKE_CUDA_ARCHITECTURES=120`; `llama-cli` and `llama-quantize` checks pass.
- Filesystem `/dev/sdd`: `1007G` total, `26G` used, `930G` available, `3%` used; `.venv` `7.7G`; llama.cpp source/build `430M`; HF cache `16K`; outputs `8.0K`.

There are no GPU or training blockers. The llama.cpp build omitted optional embedded UI assets because network access to Hugging Face was unavailable, and NCCL/OpenSSL were not present; neither affects the requested single-GPU local conversion and inference workflow. The Qwen3.5-4B weights were not downloaded and no fine-tuning was started.

## Data format and training

Put reviewed, held-out JSONL data in `data/splits/`. Each example follows the Qwen3.5/Unsloth conversation shape, with text-only content for this tutor:

```json
{"messages":[{"role":"user","content":[{"type":"text","text":"Explain the error in: She go to school yesterday."}]},{"role":"assistant","content":[{"type":"text","text":"The verb should agree with the past-time marker: She went to school yesterday."}]}]}
```

Start training explicitly only after the environment health check passes and data has been reviewed:

```bash
uv run python scripts/train_sft.py \
  --train-file data/splits/train.jsonl \
  --eval-file data/splits/eval.jsonl \
  --output-dir outputs/qwen3.5-4b-english-syntax-lora
```

The script uses `load_in_4bit=False`, `bf16=True`, language-only LoRA modules, Unsloth gradient checkpointing, and the official `UnslothVisionDataCollator`. Before importing model libraries it rejects `schema_migrated`, `review_required`, `structurally_validated`, and `benchmark` inputs; normal SFT requires explicit `approved_for_training` or `canonical_gold` approval under the current V0.4 content gate. `--development-mode` is an explicit debug escape hatch and is never the normal training path. It also refuses to start without CUDA/BF16. No training is run as part of environment setup.

## Merge, convert, and quantize

Merge the adapter into a 16-bit Hugging Face directory:

```bash
uv run python scripts/merge_lora.py \
  outputs/qwen3.5-4b-english-syntax-lora \
  outputs/qwen3.5-4b-english-syntax-merged
```

Convert and quantize after checking that the pinned `llama.cpp` converter supports the Qwen3.5 architecture in the installed source tree:

```bash
scripts/convert_to_gguf.sh \
  outputs/qwen3.5-4b-english-syntax-merged \
  outputs/qwen3.5-4b-english-syntax \
  Q4_K_S

scripts/convert_to_gguf.sh \
  outputs/qwen3.5-4b-english-syntax-merged \
  outputs/qwen3.5-4b-english-syntax \
  Q4_K_M
```

Qwen3.5 is a vision-language model. This project trains text-only conversations and disables vision-layer LoRA by default. Text-only LM Studio/PocketPal testing should be performed first. Image support may require an additional `mmproj` conversion artifact depending on the exact `llama.cpp` support in the pinned commit.

## English Syntax Tutor V0.4 data architecture

The data layer is intentionally separate from model and CUDA setup. Machine-readable canonical-format annotations live in JSONL under `data/gold/`; each record carries review metadata distinguishing schema migration/structural validation from independent linguistic review and explicit training approval. The normative V0.4 field contract is [`schemas/gold_annotation.schema.json`](schemas/gold_annotation.schema.json), with the foundational ontology in [`docs/ontology_v0.4.md`](docs/ontology_v0.4.md) and practical guidance in [`docs/annotation_guidelines.md`](docs/annotation_guidelines.md). Canonical records preserve lexical category, phrase category, syntactic function, semantic role, orthogonal clause dimensions, scoped coverage, heads, valency, framework, typed canonical analysis, established alternatives, rejected analyses, contrasts, and error diagnoses as separate fields.

The held-out file [`eval/benchmark_v1.jsonl`](eval/benchmark_v1.jsonl) contains 50 examples: the 10 legacy baseline sentences plus 40 newly authored surface forms. Every benchmark record has `schema_version: "0.4"`, `split: "benchmark"`, structural review metadata, and no training approval or `canonical_gold` claim. `source_type: "legacy_baseline"` identifies only the legacy ten. Benchmark records are never copied to train, validation, reviewed, or synthetic seed data. The small rendered fixtures in `data/splits/*_fixture.jsonl` are deliberately different sentences and are not a training corpus.

Gold and SFT representations are different layers:

```text
data/gold/*.jsonl --(scripts/render_sft.py)--> data/splits/train.jsonl
                                          --> data/splits/validation.jsonl
```

Render a selected split with a replaceable system prompt:

```bash
.venv/bin/python scripts/render_sft.py data/gold/fixtures.jsonl \
  --split train --output data/splits/train.jsonl
.venv/bin/python scripts/render_sft.py data/gold/fixtures.jsonl \
  --split validation --output data/splits/validation.jsonl
```

The renderer emits standard `messages` with `system`, `user`, and `assistant` string content. By default the assistant contains only the canonical linguistic projection; record ID, split, review state, provenance, migration metadata, annotation scope, capability intent, and nested legacy fields live in a separate `governance_sidecar`. `--include-governance` is an explicit debug mode, while `--rendering-mode learner_facing` explicitly opts into learner-facing lexical candidates. Prompt and response styles can therefore change without leaking internal governance into supervision.

Run checks before publishing a split:

```bash
.venv/bin/python scripts/validate_dataset.py data/gold --benchmark eval/benchmark_v1.jsonl
.venv/bin/python scripts/check_contamination.py data/splits data/generated \
  --benchmark eval/benchmark_v1.jsonl
.venv/bin/python -m unittest discover -s tests -v
```

`validate_dataset.py` executes the Draft 2020-12 JSON Schema validator for every canonical and benchmark record, then performs deterministic token alignment, span/reference/type, ontology, coverage, metadata, and split-isolation checks. The benchmark is sent through the same full `validate_record` path; one structural failure returns non-zero. Rendered assistant content is required to be valid JSON and is validated as a V0.4 linguistic projection using [`schemas/rendered_sft_target.schema.json`](schemas/rendered_sft_target.schema.json). These guarantees are structural only: passing schema/structural validation is not equivalent to linguistic adjudication, training approval, or `canonical_gold` status. `check_contamination.py` adds exact, case/punctuation-normalized, embedded, lexical-overlap, sequence, token-edit-distance, simple lexical-substitution skeleton, and ID-independent construction-frame checks. See [`docs/ontology_v0.4.md`](docs/ontology_v0.4.md) for the foundational ontology, [`docs/capability_taxonomy.md`](docs/capability_taxonomy.md) for tag semantics, and [`docs/open_questions.md`](docs/open_questions.md) for questions reserved for future human review.

To add an example: create a canonical record in `data/gold/` (or an approved reviewed file), assign its real split, run both checks, review framework alternatives and spans, then render only the desired split. Do not put benchmark records in any generated seed or training path.

## Repository layout

```text
english-syntax-qwen/
├── README.md
├── pyproject.toml
├── uv.lock
├── env.sh
├── configs/
├── data/
│   ├── raw/
│   ├── generated/
│   ├── gold/
│   ├── reviewed/
│   └── splits/
├── eval/benchmark_v1.jsonl
├── eval/benchmark/
├── schemas/
├── docs/
├── scripts/
├── tests/
├── notebooks/
├── outputs/
└── experiments/
```

Model weights, safetensors, GGUF files, checkpoints, generated datasets, caches, and experiment results are ignored by Git. Commit `pyproject.toml`, `uv.lock`, scripts, configs, and documentation.

## Sources checked

- Unsloth Blackwell guide: `https://unsloth.ai/docs/blog/fine-tuning-llms-with-blackwell-rtx-50-series-and-unsloth.md`
- Unsloth Qwen3.5 notebook: `https://github.com/unslothai/notebooks/blob/main/nb/Qwen3_5_(4B)_Vision.ipynb`
- Qwen3.5-4B model card: `https://huggingface.co/Qwen/Qwen3.5-4B`
- PyTorch CUDA 12.8 wheel index: `https://download.pytorch.org/whl/cu128/`
- llama.cpp repository: `https://github.com/ggml-org/llama.cpp`
