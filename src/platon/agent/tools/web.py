from __future__ import annotations

from typing import Annotated, Any

from langchain_core.tools import BaseTool, tool
from pydantic import Field

from platon.agent.tools.common import configure_error_handling
from platon.agent.tools.errors import ToolError
from platon.app_logging import log_call
from platon.websearch.websearch_parameters import DuckDuckGoTime, WebSearchParameters


def create_web_search_tools() -> tuple[BaseTool, ...]:
    """Create ranked DuckDuckGo discovery tools for public-web research."""

    @tool
    @log_call
    def search_web(
        query: str,
        max_results: int = 15,
        top_k: int = 5,
        region: str = "wt-wt",
        time: Annotated[
            DuckDuckGoTime,
            Field(
                description=(
                    "DuckDuckGo result-age window: 'd' for the last day, 'w' "
                    "for the last week, 'm' for the last month, or 'y' for the "
                    "last year. Pass null for no age filter. This is not a "
                    "date, current time, timestamp, or filter object."
                )
            ),
        ] = None,
        source: str = "text",
    ) -> dict[str, Any]:
        """Search DuckDuckGo and return deduplicated, relevance-ranked public results."""
        try:
            from platon.websearch.websearch_module import WebSearch

            parameters = WebSearchParameters(
                query=query,
                max_results=max_results,
                top_k=top_k,
                region=region,
                time=time,
                source=source,
            )
            return {"query": query, "results": WebSearch(parameters).search()}
        except Exception as exc:
            raise ToolError.from_exception(
                "search_web",
                f"searching the web for '{query}'",
                exc,
            ) from exc

    return (configure_error_handling(search_web),)
