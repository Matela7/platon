from pydantic import Field

from platon.agent.models.agent_config import AgentConfig
from platon.agent.models.agent_orchestrator_config import AgentOrchestratorConfig
from platon.backend.schemas.runtime_config import RuntimeConfig


class InitializeRuntime(RuntimeConfig):
    orchestrator_config: AgentOrchestratorConfig = Field(default_factory=AgentOrchestratorConfig)
    agent_config: AgentConfig = Field(default_factory=AgentConfig)
    thread_id: str | None = Field(default=None, min_length=1, max_length=200)
