# Third-party sources

`llama.cpp` is cloned locally for the CUDA build but is intentionally ignored by the parent Git repository. The pinned source is tag `b10731`, commit `0eadefebd3f8f92a86d634a0e5b8fffc9dc792c0`.

Recreate it with:

```bash
git clone --branch b10731 --depth 1 https://github.com/ggml-org/llama.cpp.git llama.cpp
```
