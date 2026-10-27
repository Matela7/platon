from pydantic import BaseModel, ConfigDict

from platon.agent.models.agent_config import AgentConfig
from platon.agent.models.agent_orchestrator_config import AgentOrchestratorConfig


class RuntimeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    orchestrator_config: AgentOrchestratorConfig
    agent_config: AgentConfig
