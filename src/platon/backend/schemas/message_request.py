from pydantic import BaseModel, ConfigDict, Field, field_validator


class MessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1)
    document_ids: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("document_ids")
    @classmethod
    def valid_document_ids(cls, values: list[str]) -> list[str]:
        if any(not value.strip() or len(value) > 128 for value in values):
            raise ValueError("Document IDs must be nonempty and at most 128 characters.")
        if len(values) != len(set(values)):
            raise ValueError("Document IDs must be unique.")
        return values

    @field_validator("message")
    @classmethod
    def nonempty_message(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Message cannot be empty.")
        return value
