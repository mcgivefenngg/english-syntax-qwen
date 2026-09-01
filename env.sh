#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PATH="$HOME/.local/bin:$PATH"
export ENGLISH_SYNTAX_QWEN_ROOT="$project_root"
export HF_HOME="${HOME}/.cache/huggingface"
export HF_HUB_CACHE="${HF_HOME}/hub"
export HF_DATASETS_CACHE="${HF_HOME}/datasets"
export XDG_CACHE_HOME="${HOME}/.cache"
export TMPDIR="${HOME}/.cache/tmp"
export LLAMA_CPP_DIR="${project_root}/third_party/llama.cpp"
export TOKENIZERS_PARALLELISM=false

cuda_root="${CUDA_HOME:-/usr/local/cuda-12.8}"
if [[ ! -x "${cuda_root}/bin/nvcc" && -x /usr/local/cuda/bin/nvcc ]]; then
    cuda_root="/usr/local/cuda"
fi
if [[ -x "${cuda_root}/bin/nvcc" ]]; then
    export CUDA_HOME="$cuda_root"
    export PATH="${CUDA_HOME}/bin:${PATH}"
fi

mkdir -p "$HF_HOME" "$HF_HUB_CACHE" "$HF_DATASETS_CACHE" "$TMPDIR"
