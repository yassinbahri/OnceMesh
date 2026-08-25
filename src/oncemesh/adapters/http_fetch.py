"""Reference implementation of the http.fetch/v1 action profile."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping
from urllib.parse import SplitResult, urlsplit, urlunsplit

from ..canonical import canonical_json


@dataclass(frozen=True)
class FetchResponse:
    status: int
    final_url: str
    headers: Mapping[str, str]
    body: bytes


Transport = Callable[[str, str, bool, int], FetchResponse]


def normalize_https_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme.lower() != "https":
        raise ValueError("http.fetch/v1 permits HTTPS URLs only")
    if not parsed.hostname or parsed.username is not None or parsed.password is not None:
        raise ValueError("URL must contain a host and no user information")
    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError("URL port is invalid") from error
    host = parsed.hostname.encode("idna").decode("ascii").lower()
    if ":" in host:
        host = f"[{host}]"
    netloc = host if port in (None, 443) else f"{host}:{port}"
    normalized = SplitResult("https", netloc, parsed.path or "/", parsed.query, "")
    return urlunsplit(normalized)


def build_http_fetch_action(
    url: str,
    *,
    accept: str = "*/*",
    follow_redirects: bool = True,
    max_bytes: int = 10_000_000,
    vary: dict | None = None,
) -> dict:
    if not accept:
        raise ValueError("accept must not be empty")
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
        raise ValueError("max_bytes must be a positive integer")
    return {
        "spec_version": "oncemesh.action/v0",
        "operation": {"name": "http.fetch", "version": "1"},
        "inputs": {"url": normalize_https_url(url), "method": "GET", "accept": accept},
        "executor": {
            "name": "oncemesh.http",
            "version": "1",
            "config": {"follow_redirects": follow_redirects, "max_bytes": max_bytes},
        },
        "output_schema": "oncemesh.http/response-v1",
        "vary": dict(vary or {}),
    }


def response_to_artifacts(action: dict, response: FetchResponse) -> dict[str, tuple[bytes, str]]:
    if action.get("operation") != {"name": "http.fetch", "version": "1"}:
        raise ValueError("action is not an http.fetch/v1 action")
    config = action["executor"]["config"]
    if response.status != 200:
        raise ValueError(f"http.fetch/v1 caches only status 200, received {response.status}")
    if len(response.body) > config["max_bytes"]:
        raise ValueError("response exceeds max_bytes")
    headers = {key.lower(): value for key, value in response.headers.items()}
    media_type = headers.get("content-type", "application/octet-stream")
    metadata = {
        "status": response.status,
        "final_url": normalize_https_url(response.final_url),
        "etag": headers.get("etag"),
        "last_modified": headers.get("last-modified"),
        "content_type": headers.get("content-type"),
    }
    return {
        "body": (bytes(response.body), media_type),
        "metadata": (canonical_json(metadata), "application/json"),
    }


def execute_http_fetch(action: dict, transport: Transport) -> dict[str, tuple[bytes, str]]:
    if action.get("operation") != {"name": "http.fetch", "version": "1"}:
        raise ValueError("action is not an http.fetch/v1 action")
    inputs = action["inputs"]
    config = action["executor"]["config"]
    response = transport(
        inputs["url"],
        inputs["accept"],
        config["follow_redirects"],
        config["max_bytes"],
    )
    return response_to_artifacts(action, response)
