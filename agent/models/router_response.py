from typing import Literal

from pydantic import BaseModel, field_validator


class RouterStructuredResponse(BaseModel):
    route: Literal["collections", "web", "hybrid", "direct", "clarify"]
    reason: str
    status_code: int = 200

    @field_validator("reason")
    @classmethod
    def reason_must_not_be_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("reason must not be empty or whitespace")
        return v
