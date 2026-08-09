from __future__ import annotations

from langchain_community.utilities import DuckDuckGoSearchAPIWrapper

from pydantic import BaseModel, Field

class WebSearchParameters(BaseModel):
    """Parameters for web search operations."""

    query: str = Field(..., description="The search query string.")
    max_results: int = Field(50, ge=1, le=100, description="Maximum number of search results to return.")

    # Optional parameters for DuckDuckGo search
    region: str | None = Field(None, description="Region code for the search (e.g., 'us-en').")
    safesearch: str | None = Field(None, description="Safe search setting (e.g., 'strict', 'moderate', 'off').")
    time: str | None = Field(None, description="Time filter for search results (e.g., 'd', 'w', 'm', 'y').")
    source: str | None = Field(None, description="Source type for search results (e.g., 'text', 'news', 'images').")
