"""Generate images locally using stable-diffusion.cpp."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from time import monotonic
from typing import Annotated
from uuid import uuid4

from langchain_core.tools import BaseTool, tool
from pydantic import Field

from platon.agent.cancellation import RunStopped, current_stop_event
from platon.agent.tools.common import configure_error_handling
from platon.agent.tools.errors import ToolError
from platon.app_logging import LOGGER


def create_image_tool(backend_root: Path, timeout_seconds: int = 900) -> BaseTool:
    """Create a local Z-Image-Turbo generator.

    Args:
        backend_root: Root of the agent's local files.
        timeout_seconds: Maximum time allowed for one generation.

    Returns:
        A tool that saves a PNG and reports its path as an artifact.
    """
    root = Path(backend_root).expanduser().resolve()
    models = root / "model-lora"
    executable = Path(os.environ.get("PLATON_SD_CLI", str(models / "sd-cli.exe"))).expanduser()
    diffusion = models / "z-image-turbo-Q5_K_M.gguf"
    encoder = models / "Qwen3-4B-Instruct-2507-Q4_K_M.gguf"
    vae = models / "ae.safetensors"
    lora = models / "Z-Real-v1.0.safetensors"

    @tool("generate_image", response_format="content_and_artifact")
    def generate_image(
        prompt: Annotated[str, Field(description="Detailed visual description, preferably in English; preserve requested text and details.")],
        width: Annotated[int, Field(ge=256, le=1536, multiple_of=64, description="Image width in pixels, a multiple of 64 between 256 and 1536.")] = 1024,
        height: Annotated[int, Field(ge=256, le=1536, multiple_of=64, description="Image height in pixels, a multiple of 64 between 256 and 1536.")] = 1024,
        realism: Annotated[bool | None, Field(description="True requires Z-Real LoRA; false disables it; null uses it only if installed.")] = None,
        steps: Annotated[int, Field(ge=1, le=20, description="Denoising steps; default 9 is suitable for Z-Image-Turbo.")] = 9,
        seed: Annotated[int, Field(ge=-1, le=2147483647, description="Seed for reproducible generation; -1 selects a random seed.")] = -1,
        lora_strength: Annotated[float, Field(ge=0, le=2, description="Z-Real LoRA strength when enabled; default 1.0.")] = 1.0,
        vae_tiling: Annotated[bool, Field(description="Use tiled VAE decoding to reduce GPU memory use for larger images.")] = False,
    ) -> tuple[str, dict]:
        """Generate one image locally using Z-Image-Turbo and save it as PNG.

        Use this tool when the user asks to create an image. Choose width and
        height for the requested orientation. The optional Z-Real LoRA can be
        enabled for realism or disabled for illustrations and other styles.
        Return the saved path; do not claim an image exists if generation fails.

        Args:
            prompt: Description of the image to generate, preferably in English.
            width: Image width in pixels, from 256 to 1536 in multiples of 64.
            height: Image height in pixels, from 256 to 1536 in multiples of 64.
            realism: True requires Z-Real; false disables it; None uses it if available.
            steps: Number of denoising steps, from 1 to 20.
            seed: Seed from 0 to 2147483647, or -1 for a random seed.
            lora_strength: Strength of the Z-Real adapter when enabled, from 0 to 2.
            vae_tiling: Reduce memory usage during VAE decoding by using tiles.

        Returns:
            A message and a structured artifact containing the generated file path.

        Raises:
            ToolError: If required files are missing or generation fails.
        """
        output = root / "images" / f"{uuid4().hex}.png"
        try:
            if not prompt.strip():
                raise ValueError("Image prompt cannot be empty.")
            use_z_real = lora.is_file() if realism is None else realism
            required = [executable, diffusion, encoder, vae, *([lora] if use_z_real else [])]
            missing = [str(path) for path in required if not path.is_file()]
            if missing:
                raise FileNotFoundError("Missing image generation files: " + ", ".join(missing))
            output.parent.mkdir(parents=True, exist_ok=True)
            image_prompt = prompt.strip()
            if use_z_real:
                image_prompt = f"z-realism, {image_prompt} <lora:Z-Real-v1.0:{lora_strength}>"
            command = [
                str(executable), "--diffusion-model", str(diffusion), "--llm", str(encoder),
                "--vae", str(vae), "-p", image_prompt, "-o", str(output),
                "-W", str(width), "-H", str(height), "--steps", str(steps), "--seed", str(seed), "--cfg-scale", "1.0",
                "--offload-to-cpu", "--flash-attn", "auto,diffusion=on",
            ]
            if use_z_real:
                command.extend(["--lora-model-dir", str(models)])
            if vae_tiling:
                command.append("--vae-tiling")
            stop = current_stop_event()
            if stop is not None and stop.is_set():
                raise RunStopped()
            with tempfile.TemporaryFile() as logs:
                process = subprocess.Popen(
                    command, stdout=logs, stderr=subprocess.STDOUT,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                deadline = monotonic() + timeout_seconds
                try:
                    while process.poll() is None:
                        if stop is not None and stop.is_set():
                            raise RunStopped()
                        if monotonic() >= deadline:
                            raise TimeoutError(f"Image generation exceeded {timeout_seconds} seconds.")
                        try:
                            process.wait(timeout=0.2)
                        except subprocess.TimeoutExpired:
                            pass
                except BaseException:
                    if process.poll() is None:
                        process.kill()
                        process.wait()
                    raise
                if process.returncode:
                    logs.seek(0, os.SEEK_END)
                    logs.seek(max(0, logs.tell() - 4000))
                    LOGGER.error("Image generator output: %s", logs.read().decode("utf-8", errors="replace"))
                    raise RuntimeError(f"Image generator exited with code {process.returncode}; see server logs.")
            with output.open("rb") as stream:
                if stream.read(8) != b"\x89PNG\r\n\x1a\n":
                    raise ValueError("The generator did not produce a valid PNG header.")
            artifact = {"status": "completed", "path": str(output), "media_type": "image/png",
                        "width": width, "height": height, "steps": steps, "seed": seed,
                        "lora": "Z-Real-v1.0" if use_z_real else None,
                        "lora_strength": lora_strength if use_z_real else None, "vae_tiling": vae_tiling}
            return f"Image saved to {output}", artifact
        except RunStopped:
            output.unlink(missing_ok=True)
            raise
        except Exception as exc:
            output.unlink(missing_ok=True)
            LOGGER.exception("Local image generation failed")
            raise ToolError.from_exception("generate_image", "generating a local image", exc) from exc

    return configure_error_handling(generate_image)
