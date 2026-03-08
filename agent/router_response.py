from pydantic import BaseModel, field_validator, ConfigDict
from langchain_core.language_models import BaseChatModel


class RouterStructuredResponse(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    output: str
    model: BaseChatModel
    status_code: int

    @field_validator("output")
    @classmethod
    def output_must_not_be_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:   
            raise ValueError("output must not be empty or whitespace")
        return v
    
    @field_validator("output")
    @classmethod
    def output_in_given_list(cls, v: str) -> str:
        allowed_outputs = ["success", "error", "warning"]
        if v not in allowed_outputs:
            raise ValueError(f"output must be one of {allowed_outputs} for agents using RouterStructuredResponse")
        return v
