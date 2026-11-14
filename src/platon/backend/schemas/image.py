"""Validation and response models for generated images."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

IMAGE_FILENAME_PATTERN = r"^[0-9a-f]{32}\.png$"
ImageFilename = Annotated[str, StringConstraints(min_length=36, max_length=36, pattern=IMAGE_FILENAME_PATTERN)]


class ImageRecord(BaseModel):
    """Metadata of a generated image.

    Attributes:
        filename: Generated PNG filename.
        size_bytes: File size in bytes.
        modified_at: Last modification time in UTC.
    """

    filename: ImageFilename
    size_bytes: int = Field(ge=0)
    modified_at: datetime


class ImageDeletion(BaseModel):
    """Result of deleting a generated image.

    Attributes:
        filename: Filename that was removed.
        deleted: Whether deletion succeeded.
    """

    filename: ImageFilename
    deleted: Literal[True] = True


class ImageListResponse(BaseModel):
    """Successful response containing generated image metadata."""

    status: Literal["success"] = "success"
    data: list[ImageRecord]


class ImageDeleteResponse(BaseModel):
    """Successful response containing a deletion result."""

    status: Literal["success"] = "success"
    data: ImageDeletion
