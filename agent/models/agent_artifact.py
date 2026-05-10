from pydantic import BaseModel, field_validator, ConfigDict
from pathlib import Path
from langchain_core.tools import tool

class AgentStructuredArtifact(BaseModel):
    artifact: Path
    tool_used: tool

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @field_validator("artifact")
    @classmethod
    def artifact_must_exist(cls, v: Path) -> Path:
        if not v.exists():
            raise ValueError(f"artifact path {v} does not exist")
        return v
    
    @field_validator("tool_used")
    @classmethod
    def tool_used_must_be_valid(cls, v: tool, values: dict) -> tool:
        if "tool_used" not in values:
            raise ValueError("tool_used must be provided when artifact is provided")
        return v
