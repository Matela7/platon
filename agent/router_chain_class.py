from agent.models.router_response import RouterStructuredResponse
from langchain_ollama import ChatOllama
from agent.prompt_loader import load_prompt


class RouterChain:
    def __init__(self, prompt: str, model_type: str = "bielik-minitron-7B-v3.0-instruct:Q6_K"):
        self.model_type = model_type
        self.prompt = prompt or load_prompt("router_prompt.md")
        self._model = ChatOllama(
            model=self.model_type,
            temperature=0.0,
        )
        self._structured_model = self._model.with_structured_output(RouterStructuredResponse)

    def invoke(self, input_data: dict[str, list[dict[str, str]]]) -> RouterStructuredResponse:
        messages = input_data.get("messages", [])
        user_text = "\n".join(
            m.get("content", "")
            for m in messages
            if isinstance(m, dict) and m.get("role") == "user"
        ).strip()
        router_response = self._structured_model.invoke(
            [
                ("system", self.prompt),
                ("human", user_text or str(input_data)),
            ]
        )
        return router_response
