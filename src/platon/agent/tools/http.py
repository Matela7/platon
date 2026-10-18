from __future__ import annotations

import ipaddress
import socket
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from langchain_core.tools import BaseTool, tool

from platon.agent.tools.common import configure_error_handling, truncate_output
from platon.agent.tools.errors import ToolError
from platon.app_logging import log_call


def _validate_http_url(url: str, tool_name: str) -> str:
    """Allow only absolute public HTTP(S) destinations."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ToolError(
            tool_name,
            f"validating URL '{url}'",
            "Only absolute http:// and https:// URLs are supported.",
        )
    if parsed.username is not None or parsed.password is not None:
        raise ToolError(
            tool_name,
            f"validating URL '{url}'",
            "Credentials embedded in URLs are not supported.",
        )

    hostname = parsed.hostname
    if not hostname:
        raise ToolError(
            tool_name,
            f"validating URL '{url}'",
            "The URL must contain a hostname.",
        )

    try:
        addresses = {ipaddress.ip_address(hostname)}
    except ValueError:
        try:
            addresses = {
                ipaddress.ip_address(item[4][0])
                for item in socket.getaddrinfo(
                    hostname,
                    parsed.port or (443 if parsed.scheme == "https" else 80),
                    type=socket.SOCK_STREAM,
                )
            }
        except OSError as exc:
            raise ToolError.from_exception(
                tool_name,
                f"resolving hostname '{hostname}'",
                exc,
            ) from exc

    if not addresses or any(not address.is_global for address in addresses):
        raise ToolError(
            tool_name,
            f"validating URL '{url}'",
            "Private, loopback, link-local, and reserved destinations are blocked.",
        )
    return url


@log_call
def _request_text(
    method: str,
    url: str,
    *,
    data: dict[str, Any] | None = None,
    max_redirects: int = 3,
) -> str:
    """Perform a bounded request while validating every redirect destination."""
    current_url = url
    for redirect_count in range(max_redirects + 1):
        response = requests.request(
            method,
            current_url,
            json=data if method == "POST" else None,
            headers={
                "Accept": "text/html,application/json,text/plain;q=0.9,*/*;q=0.8",
                "User-Agent": "PlatonResearchAgent/1.0",
            },
            timeout=(5, 20),
            allow_redirects=False,
        )
        if not response.is_redirect:
            response.raise_for_status()
            return response.text or f"HTTP {response.status_code}: empty response body"

        location = response.headers.get("Location")
        if not location:
            response.raise_for_status()
            return response.text
        if method == "POST":
            raise ToolError(
                "http_post",
                f"following redirect from '{current_url}'",
                "POST redirects are not followed automatically.",
            )
        if redirect_count >= max_redirects:
            raise requests.TooManyRedirects(
                f"More than {max_redirects} redirects for {url}"
            )
        current_url = _validate_http_url(
            urljoin(current_url, location),
            "http_get",
        )

    raise requests.TooManyRedirects(f"More than {max_redirects} redirects for {url}")


def create_http_tools(max_output_chars: int = 20_000) -> tuple[BaseTool, ...]:
    """Create bounded public HTTP tools with readable failure messages."""

    @tool("http_get")
    @log_call
    def http_get(url: str) -> str:
        """Fetch an absolute HTTP(S) URL with a GET request."""
        try:
            validated_url = _validate_http_url(url, "http_get")
            return truncate_output(
                _request_text("GET", validated_url),
                max_output_chars,
            )
        except ToolError:
            raise
        except Exception as exc:
            raise ToolError.from_exception(
                "http_get",
                f"performing GET request to '{url}'",
                exc,
            ) from exc

    @tool("http_post")
    @log_call
    def http_post(url: str, data: dict[str, Any]) -> str:
        """Send JSON-compatible data to an absolute HTTP(S) URL with POST."""
        try:
            validated_url = _validate_http_url(url, "http_post")
            return truncate_output(
                _request_text("POST", validated_url, data=data),
                max_output_chars,
            )
        except ToolError:
            raise
        except Exception as exc:
            raise ToolError.from_exception(
                "http_post",
                f"performing POST request to '{url}'",
                exc,
            ) from exc

    return tuple(
        configure_error_handling(tool_instance)
        for tool_instance in (http_get, http_post)
    )
