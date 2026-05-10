from langchain_ollama import ChatOllama
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, trim_messages
from langchain_core.tools import tool
from agent.tools import create_search_tools, create_utils_tools
from agent.prompt_loader import load_prompt
from vectorstore.client_manager import ClientManager
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4


class BaseAgent:
    def __init__(
        self,
        model_name: str = "bielik-minitron-7B-v3.0-instruct:Q6_K",
        model: ChatOllama | None = None,
        working_dir: Path = Path("./"),
        persist_dir: str | None = "./chroma_data",
        tools_list: list[tool] = None,
        cm: ClientManager = None,
        memory: object = None,
        prompt: str | None = None,
        max_history_messages: int = 24,
    ):
        self.model_name = model_name
        self.model = model
        self.persist_dir = persist_dir
        self.tools_list = tools_list
        self.memory = memory
        self.prompt = prompt
        self.working_dir = working_dir
        self.cm = cm
        self.max_history_messages = max_history_messages

        self._setup_model()
        if self.tools_list is None:
            self.tools_list = self._setup_tools()

    def _setup_model(self):
        self.model = ChatOllama(model=self.model_name)

    def _setup_tools(self) -> list:
        if self.cm is None:
            self.cm = ClientManager(persist_dir=self.persist_dir)
        search_tools = create_search_tools(self.cm)
        utils_tools = create_utils_tools()
        return list(search_tools) + list(utils_tools)

    def _default_prompt(self) -> str:
        return load_prompt("agent_prompt.md")

    def create_agent(self, prompt: str | None = None) -> object:
        if self.model is None:
            self._setup_model()

        system_prompt = prompt or self.prompt or self._default_prompt()
        self.prompt = system_prompt

        return create_agent(
            model=self.model,
            tools=self.tools_list,
            system_prompt=system_prompt,
        )

    def _message_from_history_item(self, message: dict[str, str] | BaseMessage) -> BaseMessage | None:
        if isinstance(message, BaseMessage):
            return message

        if not isinstance(message, dict):
            return None

        role = message.get("role")
        content = message.get("content")
        if not isinstance(content, str):
            return None

        content = content.strip()
        if not content:
            return None

        if role == "user":
            return HumanMessage(content=content)
        if role == "assistant":
            return AIMessage(content=content)
        if role == "system":
            return SystemMessage(content=content)

        return None

    def _prepare_messages(self, user_input: str, history: list[dict[str, str] | BaseMessage] | None) -> list[BaseMessage]:
        if not history:
            return [HumanMessage(content=user_input)]

        messages: list[BaseMessage] = []
        for message in history:
            langchain_message = self._message_from_history_item(message)
            if langchain_message is not None:
                messages.append(langchain_message)

        messages = trim_messages(
            messages,
            max_tokens=self.max_history_messages,
            token_counter=len,
            strategy="last",
            include_system=True,
            start_on="human",
        )
        messages.append(HumanMessage(content=user_input))
        return messages

    def _extract_answer(self, result: dict[str, Any]) -> str:
        for message in reversed(result.get("messages", [])):
            content = getattr(message, "content", None)
            message_type = getattr(message, "type", None)

            if content is None and isinstance(message, dict):
                if message.get("role") != "assistant":
                    continue
                content = message.get("content")
            elif message_type != "ai":
                continue

            if isinstance(content, str) and content.strip():
                return content.strip()

            if isinstance(content, list):
                parts = [
                    item.get("text", "") if isinstance(item, dict) else item
                    for item in content
                    if isinstance(item, (str, dict))
                ]
                answer = "\n".join(part.strip() for part in parts if part and part.strip())
                if answer:
                    return answer

        return ""

    def invoke(self, user_input: str, history: list[dict[str, str] | BaseMessage] | None = None) -> dict:
        user_input = user_input.strip()
        if not user_input:
            raise ValueError("user_input must not be empty")

        started_at = perf_counter()
        run_id = str(uuid4())
        messages = self._prepare_messages(user_input, history)

        agent = self.create_agent()
        result = agent.invoke(
            {"messages": messages},
            config={
                "run_name": "base_agent_invoke",
                "metadata": {
                    "run_id": run_id,
                    "model": self.model_name,
                    "history_messages": len(messages) - 1,
                },
            },
        )

        return {
            "run_id": run_id,
            "answer": self._extract_answer(result),
            "result": result,
            "messages": messages,
            "elapsed_seconds": round(perf_counter() - started_at, 3),
        }
