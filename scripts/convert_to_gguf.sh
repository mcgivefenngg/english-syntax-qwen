#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
    echo "Usage: $0 MERGED_HF_DIR OUTPUT_PREFIX [QUANT_TYPE]" >&2
    echo "Example: $0 outputs/merged outputs/qwen3.5-4b Q4_K_M" >&2
    exit 2
fi

merged_hf_dir="$1"
output_prefix="$2"
quant_type="${3:-Q4_K_M}"
project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
llama_dir="${project_root}/third_party/llama.cpp"
converter="${llama_dir}/convert_hf_to_gguf.py"
quantizer="${llama_dir}/build/bin/llama-quantize"
python_executable="${project_root}/.venv/bin/python"
bf16_gguf="${output_prefix}-bf16.gguf"
quantized_gguf="${output_prefix}-${quant_type}.gguf"

test -f "$converter"
test -x "$quantizer"
test -x "$python_executable"

"$python_executable" "$converter" "$merged_hf_dir" --outfile "$bf16_gguf" --outtype bf16
"$quantizer" "$bf16_gguf" "$quantized_gguf" "$quant_type"
echo "Wrote $quantized_gguf"
