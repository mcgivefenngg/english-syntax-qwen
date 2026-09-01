#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
llama_dir="${project_root}/third_party/llama.cpp"

test -d "$llama_dir"
command -v cmake >/dev/null
command -v ninja >/dev/null
command -v nvcc >/dev/null

cmake -S "$llama_dir" -B "$llama_dir/build" -G Ninja \
  -DGGML_CUDA=ON \
  -DGGML_NATIVE=ON \
  -DCMAKE_CUDA_ARCHITECTURES=120 \
  -DCMAKE_BUILD_TYPE=Release
cmake --build "$llama_dir/build" --config Release --parallel

test -x "$llama_dir/build/bin/llama-cli"
test -x "$llama_dir/build/bin/llama-quantize"
echo "llama.cpp CUDA build completed"
