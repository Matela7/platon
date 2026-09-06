"""Compatibility imports for the former monolithic subagent module.

New code should import from :mod:`agent.agents` and :mod:`agent.adapters`.
"""

from agent.adapters import AgentToolAdapter, create_delegation_tools

__all__ = ["AgentToolAdapter", "create_delegation_tools"]
