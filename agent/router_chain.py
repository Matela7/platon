from agent.router_response import RouterStructuredResponse
from langchain_google_genai import ChatGoogleGenerativeAI

class RouterChain:
    def __init__(self, prompt: str, model_type: str = "gemini-flash-lite-latest"):
        self.model_type = model_type
        self.prompt = prompt
        self._model = ChatGoogleGenerativeAI(
            model=self.model_type,
            temperature=0.0,
        )

    def invoke(self, input_data: dict[str, list[dict[str, str]]]) -> RouterStructuredResponse:
        result = self._model.invoke(self.prompt + str(input_data))
        return RouterStructuredResponse(
            output=result.content,
            model=self._model,
            status_code=200,
        )