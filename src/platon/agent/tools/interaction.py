from langchain_core.tools import tool
from langgraph.types import interrupt

from platon.app_logging import LOGGER


@tool
def ask_user(question: str) -> str:
    """Ask one focused question when missing information blocks a correct result."""
    LOGGER.info("Workflow awaiting user clarification")
    response = interrupt({"kind": "clarification", "question": question})
    return response["answer"]
