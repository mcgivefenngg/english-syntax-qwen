#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

echo "== Unit tests =="
python3 -m unittest discover -s tests -p 'test_*.py'

echo "== Compile =="
python3 -m compileall -q scripts tests

echo "== Canonical gold validation =="
python3 scripts/validate_dataset.py data/gold --no-benchmark

echo "== Git diff check =="
git diff --check

echo "PRE-FLIGHT PASS"
