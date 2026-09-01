#!/usr/bin/env bash
set -euo pipefail

keyring_path="/tmp/cuda-keyring_1.1-1_all.deb"
keyring_url="https://developer.download.nvidia.com/compute/cuda/repos/wsl-ubuntu/x86_64/cuda-keyring_1.1-1_all.deb"

if [[ ! -s "$keyring_path" ]]; then
    curl --fail --location --retry 3 --output "$keyring_path" "$keyring_url"
fi

sudo dpkg -i "$keyring_path"
sudo apt-get update
sudo apt-get install -y python3.12-dev cuda-toolkit-12-8

echo "CUDA toolkit and Python development headers installed"
