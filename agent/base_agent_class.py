from langchain_ollama import ChatOllama
from langchain.agents import create_agent
from langchain_core.tools import tool
from agent.tools import create_search_tools, create_utils_tools
from vectorstore.client_manager import ClientManager
from agent.router_chain_class import RouterChain
from agent.models.router_response import RouterStructuredResponse
from agent.prompt_loader import load_prompt
from pathlib import Path


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
        prompts: object = None,
        router_prompt: str | None = None,
        router_chain: RouterChain | None = None,
    ):
        self.model_name = model_name
        self.model = model
        self.persist_dir = persist_dir
        self.tools_list = tools_list
        self.memory = memory
        self.prompts = prompts
        self.working_dir = working_dir
        self.cm = cm
        self.router_prompt = router_prompt or self._default_router_prompt()
        self.router_chain = router_chain

        self._setup_model()
        if self.tools_list is None:
            self.tools_list = self._setup_tools()
        if self.router_chain is None:
            self.router_chain = RouterChain(
                prompt=self.router_prompt,
                model_type=self.model_name,
            )

    def _setup_model(self):
        self.model = ChatOllama(model=self.model_name)

    def _setup_tools(self) -> list:
        if self.cm is None:
            self.cm = ClientManager(persist_dir=self.persist_dir)
        search_tools = create_search_tools(self.cm)
        utils_tools = create_utils_tools()
        return list(search_tools) + list(utils_tools)

    def _default_router_prompt(self) -> str:
        return load_prompt("router_prompt.md")

    def _build_react_prompt(self, routing: RouterStructuredResponse) -> str:
        prompt = load_prompt("react_prompt.md")
        route_specific = {
            "collections": "Prefer local collections first. Use web only if collections are empty or clearly insufficient.",
            "web": "Prioritize web search for freshness. Use collections only as optional background.",
            "hybrid": "Use collections first, then web search to validate or refresh facts.",
            "direct": "Answer directly without tools unless confidence is low.",
            "clarify": "Ask one precise clarifying question before using any tools.",
        }
        guidance = route_specific.get(routing.route, route_specific["hybrid"])
        return prompt.format(route=routing.route, reason=routing.reason, guidance=guidance)

    def create_agent(self, routing: RouterStructuredResponse | None = None):
        if self.model is None:
            self._setup_model()
        routing = routing or RouterStructuredResponse(route="hybrid", reason="Default fallback route")
        return create_agent(
            model=self.model,
            tools=self.tools_list,
            system_prompt=self._build_react_prompt(routing),
        )

    def invoke(self, user_input: str, history: list[dict[str, str]] | None = None) -> dict:
        messages = history[:] if history else []
        messages.append({"role": "user", "content": user_input})

        routing = self.router_chain.invoke({"messages": messages})
        react_agent = self.create_agent(routing=routing)
        result = react_agent.invoke({"messages": messages})

        return {
            "routing": routing.model_dump(),
            "result": result,
        }
