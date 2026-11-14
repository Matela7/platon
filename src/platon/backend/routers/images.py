"""Endpoints for locally generated images."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path
from fastapi.responses import FileResponse

from platon.app_logging import LOGGER
from platon.backend.schemas.image import ImageDeleteResponse, ImageFilename, ImageListResponse
from platon.backend.services.image_service import ImageService
from platon.backend.utils.agent_runtime import Runtime

router = APIRouter(prefix="/api/v1/images", tags=["images"])
Filename = Annotated[ImageFilename, Path(description="Generated image filename: 32 lowercase hexadecimal characters and .png.")]


def _images(service: Runtime) -> ImageService:
    """Create a service for the current runtime's image directory.

    Args:
        service: Active runtime containing the agent configuration.

    Returns:
        Image service rooted in the active agent backend.
    """
    return ImageService(service.get_config()["agent_config"]["backend_root"])


@router.get("", response_model=ImageListResponse)
def list_images(service: Runtime) -> ImageListResponse:
    """List images in the active runtime's backend directory.

    Args:
        service: Active agent runtime.

    Returns:
        Generated image metadata ordered from newest to oldest.
    """
    try:
        return ImageListResponse(data=_images(service).list_images())
    except Exception as exc:
        LOGGER.exception("Image listing failed")
        raise HTTPException(500, f"Could not list images: {exc}") from exc


@router.get("/{filename}", response_class=FileResponse)
def get_image(filename: Filename, service: Runtime, download: bool = False) -> FileResponse:
    """Display or download a generated image.

    Args:
        filename: Generated PNG filename.
        service: Active agent runtime.
        download: Send the PNG as an attachment when true.

    Returns:
        PNG response, displayed inline by default.

    Raises:
        HTTPException: If the image is missing or cannot be read.
    """
    try:
        path = _images(service).get_image(filename)
        return FileResponse(path, media_type="image/png", filename=path.name,
                            content_disposition_type="attachment" if download else "inline")
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:
        LOGGER.exception("Image retrieval failed")
        raise HTTPException(500, f"Could not retrieve image: {exc}") from exc


@router.delete("/{filename}", response_model=ImageDeleteResponse)
def delete_image(filename: Filename, service: Runtime) -> ImageDeleteResponse:
    """Delete one generated image from the active backend directory.

    Args:
        filename: Generated PNG filename.
        service: Active agent runtime.

    Returns:
        Filename and deletion status.

    Raises:
        HTTPException: If the image is missing or cannot be deleted.
    """
    try:
        return ImageDeleteResponse(data=_images(service).delete_image(filename))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:
        LOGGER.exception("Image deletion failed")
        raise HTTPException(500, f"Could not delete image: {exc}") from exc
