# Local image generation

The supervisor's `generate_image` tool runs a local `stable-diffusion.cpp` CUDA build. It saves PNG files in `<backend_root>/images` (by default `.platon/agent/images`) and includes the file path in the existing tool artifact and execution report. It does not add an image viewer or file-serving endpoint.

For a new Windows CUDA installation, run `python setup_image_generation.py` manually. It downloads pinned versions, verifies SHA-256 hashes, and preserves existing files. Use `--skip-lora` to omit Z-Real, or `--backend-root PATH` to choose the agent root. Downloads require several gigabytes of disk space and an internet connection. The setup does not start image generation or Ollama.

Put these files in `<backend_root>/model-lora`:

| File | Source |
| --- | --- |
| `sd-cli.exe` and its required DLLs | [stable-diffusion.cpp releases](https://github.com/leejet/stable-diffusion.cpp/releases), Windows CUDA build and CUDA runtime archive |
| `z-image-turbo-Q5_K_M.gguf` | [Unsloth Z-Image-Turbo GGUF](https://huggingface.co/unsloth/Z-Image-Turbo-GGUF/tree/main) |
| `Qwen3-4B-Instruct-2507-Q4_K_M.gguf` | [Unsloth Qwen3 4B GGUF](https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF/tree/main) |
| `ae.safetensors` | [Z-Image Turbo VAE](https://huggingface.co/Comfy-Org/z_image_turbo/tree/main/split_files/vae) |
| `Z-Real-v1.0.safetensors` (optional) | [Z-Real v1.0](https://civitai.com/models/2198097/z-real?modelVersionId=2474931) |

Alternatively, set `PLATON_SD_CLI` to the full path of `sd-cli.exe`. With the default `realism=None`, the tool applies Z-Real if installed and otherwise uses the base model. Set `realism=true` to require it, or `realism=false` to disable it. Its default weight is 1.0. Finish downloads under a temporary filename before placing them in this directory.

The tool defaults to 1024 × 1024 and 9 steps. `width` and `height` accept 256–1536 pixels in multiples of 64; `steps` accepts 1–20; `seed=-1` selects a random seed, while a nonnegative seed makes runs reproducible under the same settings. `lora_strength` accepts 0–2 when Z-Real is enabled, and `vae_tiling=true` reduces decoder memory usage. The tool uses CPU offload and flash attention and times out after 15 minutes. Larger sizes may fail or run slowly depending on available memory. The model, text encoder, LoRA and working buffers require system RAM as well as VRAM. Ollama and image generation share the GPU. The CUDA executable and weights are separate downloads, not Python dependencies; no extra packages are needed in `pyproject.toml` for the subprocess integration.
