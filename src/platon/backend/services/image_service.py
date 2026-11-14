"""Access images generated in the active agent backend."""

from datetime import datetime, timezone
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from platon.backend.schemas.image import ImageDeletion, ImageFilename, ImageRecord

_filename_adapter = TypeAdapter(ImageFilename)


class ImageService:
    """List, retrieve and delete generated PNG files under one backend root.

    Args:
        backend_root: Root directory used by the active agent.
    """

    def __init__(self, backend_root: str | Path):
        self.image_dir = (Path(backend_root).expanduser() / "images").resolve()

    def list_images(self) -> list[ImageRecord]:
        """List files created by the image generator.

        Returns:
            Image metadata sorted by modification time, newest first.
        """
        if not self.image_dir.exists():
            return []
        images = []
        for path in self.image_dir.iterdir():
            try:
                filename = _filename_adapter.validate_python(path.name)
            except ValidationError:
                continue
            if path.is_symlink() or not path.is_file():
                continue
            try:
                stat = path.stat()
            except FileNotFoundError:
                continue
            images.append(ImageRecord(filename=filename, size_bytes=stat.st_size,
                                      modified_at=datetime.fromtimestamp(stat.st_mtime, timezone.utc)))
        return sorted(images, key=lambda image: image.modified_at, reverse=True)

    def get_image(self, filename: str) -> Path:
        """Resolve a generated image without accepting paths or symlinks.

        Args:
            filename: Generated PNG filename.

        Returns:
            Path to the existing image.

        Raises:
            ValueError: If the filename does not match the generated format.
            FileNotFoundError: If the image is missing or is a symlink.
        """
        filename = _filename_adapter.validate_python(filename)
        path = self.image_dir / filename
        if path.is_symlink() or not path.is_file():
            raise FileNotFoundError(f"Image not found: {filename}")
        return path

    def delete_image(self, filename: str) -> ImageDeletion:
        """Remove one generated image.

        Args:
            filename: Generated PNG filename.

        Returns:
            Filename and successful deletion status.

        Raises:
            ValueError: If the filename does not match the generated format.
            FileNotFoundError: If the image is missing or is a symlink.
        """
        self.get_image(filename).unlink()
        return ImageDeletion(filename=filename)
