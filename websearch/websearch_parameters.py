from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, Field


def normalize_duckduckgo_time(value: Any) -> str | None:
    """Normalize supported DDG windows and drop malformed model arguments."""
    if value is None:
        return None
    if not isinstance(value, str):
        return None

    aliases = {
        "d": "d",
        "day": "d",
        "1d": "d",
        "w": "w",
        "week": "w",
        "1w": "w",
        "m": "m",
        "month": "m",
        "1m": "m",
        "y": "y",
        "year": "y",
        "1y": "y",
    }
    return aliases.get(value.strip().lower())


DuckDuckGoTime = Annotated[
    Literal["d", "w", "m", "y"] | None,
    BeforeValidator(normalize_duckduckgo_time),
]


class WebSearchParameters(BaseModel):
    """Parameters for web search operations."""

    query: str = Field(..., min_length=1, description="The search query string.")
    max_results: int = Field(
        15,
        ge=1,
        le=50,
        description="Maximum number of DuckDuckGo candidates to retrieve.",
    )
    top_k: int = Field(
        5,
        ge=1,
        le=20,
        description="Maximum number of ranked results to return.",
    )

    # Optional parameters for DuckDuckGo search
    region: str = Field(
        "wt-wt",
        description="DuckDuckGo region code (for example 'pl-pl' or 'wt-wt').",
    )
    safesearch: Literal["strict", "moderate", "off"] = Field(
        "off",
        description="DuckDuckGo safe-search setting.",
    )
    time: DuckDuckGoTime = Field(
        None,
        description=(
            "DuckDuckGo result-age window: 'd' for the last day, 'w' for the "
            "last week, 'm' for the last month, or 'y' for the last year. "
            "Use null for no age filter; do not pass a date, current time, "
            "timestamp, or filter object."
        ),
    )
    source: Literal["text", "news"] = Field(
        "text",
        description="DuckDuckGo result source.",
    )
    semantic_dedup_threshold: float | None = Field(
        0.96,
        ge=-1.0,
        le=1.0,
        description="Cosine threshold for semantic duplicate removal; null disables it.",
    )
    embedding_weight: float = Field(
        0.8,
        ge=0.0,
        le=1.0,
        description="Embedding-similarity share in the hybrid score.",
    )
