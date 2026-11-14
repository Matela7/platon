from pydantic import Field

from platon.agent.models.agent_config import AgentConfig
from platon.agent.models.agent_orchestrator_config import AgentOrchestratorConfig
from platon.backend.schemas.runtime_config import RuntimeConfig


INITIALIZE_OPENAPI_EXAMPLE = {
    "orchestrator_config": {
        "base_url": "http://localhost:11434",
        "persist_dir": "./chroma_data",
        "working_dir": "C:/Users/miche/platon",
        "sqlite_path": None,
    },
    "agent_config": {
        "model_name": "gemma4:26b-a4b-it-qat",
        "model_temperature": 0.0,
        "system_prompt": "react_prompt.md",
        "max_history_messages": 24,
        "max_tool_output_chars": 20000,
        "keep_alive": "30m",
        "num_ctx": 16384,
        "reasoning": False,
        "debug": True,
        "research_tool_limit": 6,
        "coding_tool_limit": 15,
        "database_tool_limit": 8,
        "execution_timeout_seconds": 120,
        "backend_root": "C:/Users/miche/platon/.platon/agent",
        "skills": ["/skills/"],
        "memory": ["/memory/AGENTS.md"],
    },
    "thread_id": None,
}


class InitializeRuntime(RuntimeConfig):
    orchestrator_config: AgentOrchestratorConfig = Field(default_factory=AgentOrchestratorConfig)
    agent_config: AgentConfig = Field(default_factory=AgentConfig)
    thread_id: str | None = Field(default=None, min_length=1, max_length=200)
