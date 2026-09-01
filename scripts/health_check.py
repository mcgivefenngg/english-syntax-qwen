#!/usr/bin/env python3
"""Run strict environment checks for CUDA training and llama.cpp."""

from __future__ import annotations

import importlib
import importlib.metadata
import os
import shutil
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAMES = (
    "torch",
    "torchvision",
    "transformers",
    "datasets",
    "trl",
    "peft",
    "accelerate",
    "safetensors",
    "tensorboard",
    "bitsandbytes",
    "triton",
    "unsloth",
    "unsloth_zoo",
)
PACKAGE_DISTRIBUTIONS = {
    "huggingface_hub": "huggingface-hub",
    "unsloth_zoo": "unsloth-zoo",
}


def run_command(command: list[str]) -> tuple[int, str]:
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    output = (completed.stdout + completed.stderr).strip()
    return completed.returncode, output


def print_package_versions() -> None:
    print("Package versions:")
    for package_name in PACKAGE_NAMES:
        try:
            distribution_name = PACKAGE_DISTRIBUTIONS.get(package_name, package_name)
            version = importlib.metadata.version(distribution_name)
            print(f"  {package_name}: {version}")
        except Exception as error:
            print(f"  {package_name}: IMPORT FAILED: {error}")


def check_torch_cuda() -> bool:
    try:
        import torch
    except Exception as error:
        print(f"[FAIL] torch import: {error}")
        return False

    print(f"Python: {sys.version.split()[0]}")
    print(f"PyTorch CUDA runtime: {torch.version.cuda}")
    print(f"torch.cuda.is_available(): {torch.cuda.is_available()}")
    if not torch.cuda.is_available():
        print("[FAIL] CUDA is unavailable; refusing CPU fallback.")
        return False

    device_index = torch.cuda.current_device()
    device_name = torch.cuda.get_device_name(device_index)
    capability = torch.cuda.get_device_capability(device_index)
    print(f"CUDA device: {device_name}")
    print(f"CUDA capability: {capability[0]}.{capability[1]}")
    if capability < (12, 0):
        print("[WARN] Device capability is below Blackwell sm_120.")

    bf16_supported = torch.cuda.is_bf16_supported()
    print(f"torch.cuda.is_bf16_supported(): {bf16_supported}")
    if not bf16_supported:
        print("[FAIL] BF16 is not supported by the active CUDA device.")
        return False

    try:
        left = torch.randn((1024, 1024), device="cuda", dtype=torch.bfloat16)
        right = torch.randn((1024, 1024), device="cuda", dtype=torch.bfloat16)
        product = left @ right
        allocation = torch.empty((256 * 1024 * 1024,), device="cuda", dtype=torch.uint8)
        torch.cuda.synchronize()
        allocated_mib = torch.cuda.memory_allocated() / 1024**2
        reserved_mib = torch.cuda.memory_reserved() / 1024**2
        print(f"BF16 tensor operation: {product.shape} {product.dtype}")
        print(f"CUDA allocation: allocated={allocated_mib:.1f} MiB reserved={reserved_mib:.1f} MiB")
        del left, right, product, allocation
        torch.cuda.empty_cache()
    except Exception as error:
        print(f"[FAIL] CUDA/BF16 tensor operation: {error}")
        return False

    print("[PASS] PyTorch CUDA, BF16, tensor operation, and allocation")
    return True


def check_triton_cuda() -> bool:
    try:
        import torch
        import triton
        import triton.language as tl
    except Exception as error:
        print(f"[FAIL] Triton import: {error}")
        return False

    if not torch.cuda.is_available():
        print("[FAIL] Triton CUDA test skipped because CUDA is unavailable")
        return False

    @triton.jit
    def add_kernel(
        input_ptr,
        output_ptr,
        element_count,
        block_size: tl.constexpr,
    ):
        program_id = tl.program_id(axis=0)
        offsets = program_id * block_size + tl.arange(0, block_size)
        mask = offsets < element_count
        values = tl.load(input_ptr + offsets, mask=mask)
        tl.store(output_ptr + offsets, values + 1, mask=mask)

    try:
        element_count = 16384
        input_tensor = torch.zeros(element_count, device="cuda", dtype=torch.float32)
        output_tensor = torch.empty_like(input_tensor)
        grid = (triton.cdiv(element_count, 1024),)
        add_kernel[grid](input_tensor, output_tensor, element_count, block_size=1024)
        torch.cuda.synchronize()
        if not torch.all(output_tensor == 1):
            print("[FAIL] Triton CUDA kernel produced an incorrect result")
            return False
        del input_tensor, output_tensor
        torch.cuda.empty_cache()
    except Exception as error:
        print(f"[FAIL] Triton CUDA kernel: {error}")
        return False

    print(f"Triton runtime: {triton.__version__}")
    print("[PASS] Triton CUDA kernel")
    return True


def check_unsloth() -> bool:
    try:
        unsloth = importlib.import_module("unsloth")
        print(f"Unsloth import: {getattr(unsloth, '__version__', 'unknown')}")
        print("[PASS] Unsloth import")
        return True
    except Exception as error:
        print(f"[FAIL] Unsloth import: {error}")
        return False


def check_nvidia_smi() -> bool:
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        print("[FAIL] nvidia-smi was not found on PATH")
        return False
    return_code, output = run_command(
        [
            nvidia_smi,
            "--query-gpu=name,driver_version,memory.total,memory.free,memory.used",
            "--format=csv,noheader",
        ]
    )
    print(f"nvidia-smi: {output}")
    if return_code:
        print("[FAIL] nvidia-smi did not complete successfully")
        return False
    print("[PASS] nvidia-smi")
    return True


def check_cuda_toolkit() -> bool:
    nvcc_candidates = [shutil.which("nvcc")]
    cuda_home = os.environ.get("CUDA_HOME")
    if cuda_home:
        nvcc_candidates.append(str(Path(cuda_home) / "bin" / "nvcc"))
    nvcc_candidates.extend(
        [
            "/usr/local/cuda/bin/nvcc",
            "/usr/local/cuda-12.8/bin/nvcc",
        ]
    )
    nvcc = next(
        (candidate for candidate in nvcc_candidates if candidate and Path(candidate).is_file()),
        None,
    )
    if not nvcc:
        print("[FAIL] CUDA toolkit compiler nvcc was not found")
        return False
    return_code, output = run_command([nvcc, "--version"])
    print(f"nvcc: {output}")
    if return_code:
        print("[FAIL] nvcc --version did not complete successfully")
        return False
    print("[PASS] CUDA toolkit/compiler")
    return True


def check_no_linux_driver() -> bool:
    return_code, output = run_command(
        [
            "dpkg-query",
            "-W",
            "-f=${db:Status-Abbrev} ${binary:Package}\\n",
        ]
    )
    if return_code not in (0, 1):
        print(f"[WARN] Could not inspect dpkg driver packages: {output}")
        return True
    installed_driver_lines = [
        line
        for line in output.splitlines()
        if line.startswith("ii ")
        and any(
            package_marker in line
            for package_marker in ("nvidia-driver", "nvidia-dkms", "cuda-drivers")
        )
    ]
    if installed_driver_lines:
        print("[FAIL] Linux NVIDIA display/driver packages detected:")
        for line in installed_driver_lines:
            print(f"  {line}")
        return False
    print("[PASS] no Linux NVIDIA display driver package")
    return True


def check_llama_cpp() -> bool:
    binary_dir = PROJECT_ROOT / "third_party" / "llama.cpp" / "build" / "bin"
    cache_file = PROJECT_ROOT / "third_party" / "llama.cpp" / "build" / "CMakeCache.txt"
    binary_commands = {
        "llama-cli": ["--version"],
        "llama-quantize": ["--help"],
    }
    all_passed = True
    if not cache_file.exists():
        print(f"[FAIL] missing llama.cpp CMake cache: {cache_file}")
        all_passed = False
    else:
        cache_text = cache_file.read_text(encoding="utf-8")
        if "GGML_CUDA:BOOL=ON" not in cache_text:
            print("[FAIL] llama.cpp CMake cache does not enable GGML_CUDA")
            all_passed = False
        else:
            print("[PASS] llama.cpp CMake cache has GGML_CUDA=ON")
    for binary_name, arguments in binary_commands.items():
        binary_path = binary_dir / binary_name
        if not binary_path.exists():
            print(f"[FAIL] missing llama.cpp binary: {binary_path}")
            all_passed = False
            continue
        return_code, output = run_command([str(binary_path), *arguments])
        print(f"{binary_name}: {output}")
        quantizer_help_is_valid = (
            binary_name == "llama-quantize"
            and "allowed quantization types" in output
            and "Q4_K_S" in output
            and "Q4_K_M" in output
        )
        if return_code and not quantizer_help_is_valid:
            print(f"[FAIL] {binary_name} {' '.join(arguments)} failed")
            all_passed = False
        else:
            print(f"[PASS] {binary_name}")
    return all_passed


def main() -> int:
    print(f"Project root: {PROJECT_ROOT}")
    print(f"HF_HOME: {os.environ.get('HF_HOME', '<not set>')}")
    print_package_versions()
    checks = {
        "nvidia-smi": check_nvidia_smi(),
        "CUDA toolkit": check_cuda_toolkit(),
        "no Linux NVIDIA driver": check_no_linux_driver(),
        "torch CUDA": check_torch_cuda(),
        "Triton CUDA": check_triton_cuda(),
        "Unsloth": check_unsloth(),
        "llama.cpp": check_llama_cpp(),
    }
    print("Health summary:")
    for name, passed in checks.items():
        print(f"  {'PASS' if passed else 'FAIL'}: {name}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
