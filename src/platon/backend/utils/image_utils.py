"""Utilities for handling, validating, and persisting chat images."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence
import urllib.error
import urllib.request
from uuid import uuid4

from fastapi import HTTPException, UploadFile

from platon.app_logging import LOGGER

ALLOWED_IMAGE_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
}
MAX_IMAGE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_IMAGES_PER_TURN = 4


def check_model_multimodal(base_url: str, model_name: str) -> bool:
    """Check if the given Ollama model supports vision/multimodal input.

    Queries the Ollama ``/api/show`` endpoint. If the model specifies a vision
    projector or multimodal capabilities, returns True.
    Defaults to True on connection or parsing errors so as not to block valid runs.
    """
    if not model_name:
        return False

    url = f"{base_url.rstrip('/')}/api/show"
    payload = json.dumps({"name": model_name}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            if resp.status != 200:
                return True
            data = json.loads(resp.read().decode("utf-8"))

        # Check details, modelfile, or architecture for multimodal/vision indicators
        details = data.get("details", {}) or {}
        families = [str(f).lower() for f in details.get("families", []) or []]
        family = str(details.get("family", "")).lower()

        # Check vision-related indicators
        vision_indicators = {"clip", "mllama", "vision", "minicpm-v", "llava", "qwen2-vl", "paligemma"}
        if any(v in family for v in vision_indicators) or any(
            any(v in f for v in vision_indicators) for f in families
        ):
            return True

        # Check modelfile / template / parameters for projector
        modelfile = str(data.get("modelfile", "")).lower()
        if "projector" in modelfile or "vision" in modelfile:
            return True

        model_info = data.get("model_info", {}) or {}
        for key in model_info:
            if "vision" in key.lower() or "clip" in key.lower():
                return True

        # Common known multimodal models by name prefix/substring
        name_lower = model_name.lower()
        multimodal_names = (
            "llava",
            "bakllava",
            "gemma4",
            "minicpm",
            "moondream",
            "qwen-vl",
            "qwen2-vl",
            "qwen2.5-vl",
            "llama3.2-vision",
            "vision",
        )
        if any(keyword in name_lower for keyword in multimodal_names):
            return True

        # If model architecture specifically declares only text, it's not multimodal
        arch = str(model_info.get("general.architecture", "")).lower()
        if arch in {"llama", "qwen2", "gemma2", "mistral", "phi3", "starcoder2"}:
            return False

        return True
    except Exception as exc:
        LOGGER.warning("Could not verify model multimodality (%s): %s", model_name, exc)
        return True


def save_chat_images(
    files: Sequence[UploadFile],
    backend_root: Path,
) -> list[Path]:
    """Validate and persist uploaded images to the sent_images directory."""
    if len(files) > MAX_IMAGES_PER_TURN:
        raise HTTPException(
            status_code=422,
            detail=f"Maksymalnie można przesłać {MAX_IMAGES_PER_TURN} zdjęcia na raz.",
        )

    target_dir = backend_root / "sent_images"
    target_dir.mkdir(parents=True, exist_ok=True)
    saved_paths: list[Path] = []

    for file in files:
        content_type = file.content_type or ""
        if content_type not in ALLOWED_IMAGE_TYPES:
            raise HTTPException(
                status_code=422,
                detail=f"Nieobsługiwany format pliku '{file.filename}'. Dozwolone formaty: JPEG, PNG, GIF, WEBP.",
            )

        data = file.file.read()
        if not data:
            raise HTTPException(
                status_code=422,
                detail=f"Plik '{file.filename}' jest pusty.",
            )
        if len(data) > MAX_IMAGE_SIZE_BYTES:
            raise HTTPException(
                status_code=422,
                detail=f"Plik '{file.filename}' przekracza dopuszczalny limit 10 MB.",
            )

        ext = Path(file.filename or "image.png").suffix.lower()
        if ext not in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
            ext = ".png"

        target_file = target_dir / f"{uuid4().hex}{ext}"
        target_file.write_bytes(data)
        saved_paths.append(target_file)

    return saved_paths
