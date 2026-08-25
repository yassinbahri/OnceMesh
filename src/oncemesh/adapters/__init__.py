"""Normative M1 adapter profiles."""

from .html_markdown import build_html_to_markdown_action, html_to_markdown_artifacts
from .http_fetch import (
    FetchResponse,
    build_http_fetch_action,
    execute_http_fetch,
    normalize_https_url,
    response_to_artifacts,
)
from .safe_http import SafeHTTPTransport
from .pdf_text import build_pdf_to_text_action, pdf_to_text_artifacts

__all__ = [
    "FetchResponse",
    "SafeHTTPTransport",
    "build_html_to_markdown_action",
    "build_http_fetch_action",
    "build_pdf_to_text_action",
    "execute_http_fetch",
    "html_to_markdown_artifacts",
    "normalize_https_url",
    "response_to_artifacts",
    "pdf_to_text_artifacts",
]
