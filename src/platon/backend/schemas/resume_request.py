from typing import Any

from pydantic import BaseModel, ConfigDict


class ResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decisions: dict[str, Any]
