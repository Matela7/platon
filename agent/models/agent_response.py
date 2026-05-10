from pydantic import BaseModel, field_validator, ConfigDict
from langchain_core.language_models import BaseChatModel

class AgentStructuredResponse(BaseModel):
    answer: str
    source: list[str | None] = None
    model: BaseChatModel

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @field_validator("answer")
    @classmethod
    def answer_must_not_be_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("answer must not be empty or whitespace")
        return v
    