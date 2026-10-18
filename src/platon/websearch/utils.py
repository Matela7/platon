from __future__ import annotations

import re
from typing import Any, Sequence
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import numpy as np


_TRACKING_PARAMETERS = {"fbclid", "gclid"}


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Return cosine similarity, including safe handling of zero vectors."""
    vector_a = np.asarray(a, dtype=float)
    vector_b = np.asarray(b, dtype=float)
    denominator = np.linalg.norm(vector_a) * np.linalg.norm(vector_b)
    if denominator == 0:
        return 0.0
    return float(np.dot(vector_a, vector_b) / denominator)


def result_to_text(result: dict[str, Any]) -> str:
    """Build the text representation embedded for a search result."""
    title = str(result.get("title") or "").strip()
    snippet = str(result.get("snippet") or "").strip()
    return f"Title: {title}\nContent: {snippet}"


def canonicalize_url(url: str) -> str:
    """Normalize a result URL and remove common tracking parameters."""
    parsed = urlsplit(url.strip())
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]

    port = f":{parsed.port}" if parsed.port else ""
    query = urlencode(
        [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if not key.lower().startswith("utm_")
            and key.lower() not in _TRACKING_PARAMETERS
        ]
    )
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit((parsed.scheme.lower(), f"{host}{port}", path, query, ""))


def _deduplicate_exact(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the first result for each normalized URL or repeated content."""
    unique_results: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    seen_content: set[str] = set()

    for position, raw_result in enumerate(results):
        result = dict(raw_result)
        link = str(result.get("link") or result.get("url") or "").strip()
        normalized_url = canonicalize_url(link) if link else ""
        content_key = re.sub(r"\s+", " ", result_to_text(result)).casefold()

        if normalized_url and normalized_url in seen_urls:
            continue
        if content_key and content_key in seen_content:
            continue

        if normalized_url:
            seen_urls.add(normalized_url)
        if content_key:
            seen_content.add(content_key)
        result["original_position"] = position
        unique_results.append(result)

    return unique_results


def semantic_deduplicate(
    results: list[dict[str, Any]],
    vectors: Sequence[Sequence[float]],
    threshold: float,
) -> tuple[list[dict[str, Any]], list[Sequence[float]]]:
    """Remove results whose content embedding duplicates an earlier result."""
    unique_results: list[dict[str, Any]] = []
    unique_vectors: list[Sequence[float]] = []

    for result, vector in zip(results, vectors, strict=True):
        is_duplicate = any(
            cosine_similarity(vector, existing_vector) >= threshold
            for existing_vector in unique_vectors
        )
        if not is_duplicate:
            unique_results.append(result)
            unique_vectors.append(vector)

    return unique_results, unique_vectors
