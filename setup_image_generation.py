"""Install the Windows CUDA image generator and its model files for Platon.

Run manually with ``python setup_image_generation.py``. Existing files are
verified and retained; downloads are staged until their SHA-256 is verified.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import os
import shutil
import sys
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Download:
    """A pinned source and checksum for a local installation file."""

    name: str
    url: str
    sha256: str


RELEASE = "https://github.com/leejet/stable-diffusion.cpp/releases/download/master-1031-c6dfa9d"
DOWNLOADS = (
    Download("sd-cuda.zip", f"{RELEASE}/sd-master-c6dfa9d-bin-win-cuda12-x64.zip", "b1754e73934f4e1c1cc61d6228ebff44624c8a528a9ab850ad07d5179a3dbbac"),
    Download("cudart.zip", f"{RELEASE}/cudart-sd-bin-win-cu12-x64.zip", "fe20366827d357c00797eebb58244dddab7fd9a348d70090c3871004c320f38d"),
    Download("z-image-turbo-Q5_K_M.gguf", "https://huggingface.co/unsloth/Z-Image-Turbo-GGUF/resolve/b40f712c569ecfff42f2307dcc43399ae1d71318/z-image-turbo-Q5_K_M.gguf", "53b6f401c922192403e362e342d84e80b39703a4debd93a45191b4dcee9a1bff"),
    Download("Qwen3-4B-Instruct-2507-Q4_K_M.gguf", "https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF/resolve/a06e946bb6b655725eafa393f4a9745d460374c9/Qwen3-4B-Instruct-2507-Q4_K_M.gguf", "3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597"),
    Download("ae.safetensors", "https://huggingface.co/Comfy-Org/z_image_turbo/resolve/6fc90a3b1b653e935a0d175e260736de25b84df5/split_files/vae/ae.safetensors", "afc8e28272cd15db3919bacdb6918ce9c1ed22e96cb12c4d5ed0fba823529e38"),
    Download("Z-Real-v1.0.safetensors", "https://civitai.com/api/download/models/2474931?fileId=2363398", "924bb750f20e1b8465f6017198caad337be622620507ce37eb527c7817d1fa39"),
)


def checksum(path: Path) -> str:
    """Return the SHA-256 digest without loading a whole model into memory.

    Args:
        path: Local file to verify.

    Returns:
        The lower-case hexadecimal SHA-256 digest.
    """
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download(item: Download, directory: Path) -> Path:
    """Download and verify one file, preserving existing completed files.

    Args:
        item: Pinned URL and expected checksum.
        directory: Directory for the completed file and temporary download.

    Returns:
        Path to the verified file.

    Raises:
        RuntimeError: If an existing file differs or a download fails validation.
    """
    target = directory / item.name
    if target.exists():
        if checksum(target) != item.sha256:
            raise RuntimeError(f"Existing file has an unexpected checksum: {target}")
        print(f"Verified: {target}")
        return target
    partial = target.with_name(target.name + ".part")
    offset = partial.stat().st_size if partial.exists() else 0
    if offset and checksum(partial) == item.sha256:
        os.replace(partial, target)
        print(f"Verified completed download: {target}")
        return target
    for attempt in range(5):
        offset = partial.stat().st_size if partial.exists() else 0
        headers = {"User-Agent": "Platon-image-setup/1.0"}
        if offset:
            headers["Range"] = f"bytes={offset}-"
        print(f"Downloading {item.name} (resume offset: {offset} bytes)...", flush=True)
        request = urllib.request.Request(item.url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                if response.status == 206:
                    content_range = response.headers.get("Content-Range", "")
                    if not content_range.startswith(f"bytes {offset}-"):
                        raise RuntimeError(f"Unexpected download range for {item.name}: {content_range}")
                    mode = "ab"
                else:
                    mode = "wb"  # Server ignored Range: restart rather than append corrupt data.
                expected_bytes = response.headers.get("Content-Length")
                with partial.open(mode) as stream:
                    before = stream.tell()
                    shutil.copyfileobj(response, stream, length=1024 * 1024)
                    received = stream.tell() - before
                if expected_bytes is not None and received != int(expected_bytes):
                    raise OSError(f"Incomplete download: received {received} of {expected_bytes} bytes")
            if checksum(partial) != item.sha256:
                raise RuntimeError(f"Checksum mismatch for {partial}; download kept for inspection.")
            os.replace(partial, target)
            return target
        except (OSError, urllib.error.URLError, http.client.IncompleteRead) as exc:
            if attempt == 4:
                raise RuntimeError(f"Download failed after 5 attempts: {item.name}: {exc}") from exc
            print(f"Download interrupted: {exc}. Retrying...", file=sys.stderr, flush=True)
            time.sleep(min(2 ** attempt, 10))
    raise RuntimeError(f"Download failed: {item.name}")


def install_archive(archive: Path, destination: Path) -> None:
    """Install the flat release archive without replacing different files.

    Args:
        archive: Verified ZIP file from the pinned release.
        destination: Directory for the executable and DLLs.

    Raises:
        RuntimeError: If an archive entry is unsafe or conflicts with a file.
    """
    with zipfile.ZipFile(archive) as source:
        entries = [entry for entry in source.infolist() if not entry.is_dir()]
        if any(Path(entry.filename).name != entry.filename or "\\" in entry.filename for entry in entries):
            raise RuntimeError(f"Unexpected path in archive: {archive}")
        # Check every conflict before extracting any entry.
        for entry in entries:
            target = destination / entry.filename
            if target.exists():
                digest = hashlib.sha256()
                with source.open(entry) as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(block)
                if checksum(target) != digest.hexdigest():
                    raise RuntimeError(f"Refusing to overwrite a different file: {target}")
        for entry in entries:
            target = destination / entry.filename
            if not target.exists():
                with source.open(entry) as src, target.open("xb") as dst:
                    shutil.copyfileobj(src, dst)


def main() -> int:
    """Parse arguments and install the explicitly requested image components.

    Returns:
        Zero on success and one on installation or verification failure.
    """
    parser = argparse.ArgumentParser(description="Set up local Z-Image-Turbo on Windows with CUDA.")
    parser.add_argument("--backend-root", type=Path, default=Path.cwd() / ".platon" / "agent")
    parser.add_argument("--skip-lora", action="store_true", help="Do not download optional Z-Real.")
    args = parser.parse_args()
    if sys.platform != "win32":
        print("This setup currently supports the Windows CUDA build only.", file=sys.stderr)
        return 1
    model_dir = args.backend_root.expanduser().resolve() / "model-lora"
    try:
        model_dir.mkdir(parents=True, exist_ok=True)
        for item in DOWNLOADS:
            if args.skip_lora and item.name == "Z-Real-v1.0.safetensors":
                continue
            path = download(item, model_dir)
            if path.suffix == ".zip":
                install_archive(path, model_dir)
        print(f"Image generation files are installed in {model_dir}.")
        return 0
    except (OSError, urllib.error.URLError, zipfile.BadZipFile, RuntimeError) as exc:
        print(f"Setup failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
