from __future__ import annotations

from pathlib import Path
from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, field_validator

class AgentStructuredArtifact(BaseModel):
    """Represents an artifact produced by a specific tool.

    Attributes:
        artifact: Existing path to the generated artifact.
        tool_used: Tool that produced the artifact.
    """

    artifact: Path
    tool_used: BaseTool

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @field_validator("artifact")
    @classmethod
    def artifact_must_exist(cls, v: Path) -> Path:
        """Ensure the artifact path exists on disk.

        Args:
            v: Artifact path.

        Returns:
            The same path when it exists.

        Raises:
            ValueError: If the artifact path does not exist.
        """
        if not v.exists():
            raise ValueError(f"artifact path {v} does not exist")
        return v
