from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, ConfigDict, Field, field_validator

class AgentStructuredResponse(BaseModel):
    """Structured response returned by an agent invocation.

    Attributes:
        answer: Final assistant answer.
        source: Optional source labels used to build the answer.
        model: Chat model instance used to generate the answer.
    """

    answer: str
    source: list[str | None] = Field(default_factory=list)
    model: BaseChatModel

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @field_validator("answer")
    @classmethod
    def answer_must_not_be_empty(cls, v: str) -> str:
        """Validate that answer contains non-whitespace content.

        Args:
            v: Candidate answer value.

        Returns:
            Trimmed answer text.

        Raises:
            ValueError: If the answer is empty after trimming.
        """
        v = v.strip()
        if not v:
            raise ValueError("answer must not be empty or whitespace")
        return v
    