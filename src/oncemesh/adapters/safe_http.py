"""Allowlisted reference HTTPS transport for controlled evaluation runs."""

from __future__ import annotations

import ipaddress
import socket
import ssl
from collections.abc import Callable, Iterable
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener

from .http_fetch import FetchResponse, normalize_https_url

Resolver = Callable[[str, int], Iterable[str]]


def _system_resolver(host: str, port: int) -> Iterable[str]:
    return {
        entry[4][0]
        for entry in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    }


class _CheckedRedirects(HTTPRedirectHandler):
    def __init__(self, transport: "SafeHTTPTransport", enabled: bool) -> None:
        super().__init__()
        self.transport = transport
        self.enabled = enabled
        self.count = 0

    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        if not self.enabled:
            return None
        self.count += 1
        if self.count > self.transport.max_redirects:
            raise ValueError("redirect limit exceeded")
        normalized = self.transport.validate_target(new_url)
        return super().redirect_request(request, file_pointer, code, message, headers, normalized)


class SafeHTTPTransport:
    """HTTPS GET transport with narrow explicit authority and bounded reads."""

    def __init__(
        self,
        allowed_hosts: Iterable[str],
        *,
        timeout_seconds: float = 15.0,
        max_redirects: int = 3,
        resolver: Resolver | None = None,
    ) -> None:
        normalized_hosts = {
            host.encode("idna").decode("ascii").lower().rstrip(".")
            for host in allowed_hosts
        }
        if not normalized_hosts:
            raise ValueError("at least one allowed host is required")
        if timeout_seconds <= 0 or max_redirects < 0:
            raise ValueError("timeout must be positive and max_redirects non-negative")
        self.allowed_hosts = frozenset(normalized_hosts)
        self.timeout_seconds = timeout_seconds
        self.max_redirects = max_redirects
        self.resolver = resolver or _system_resolver

    def validate_target(self, url: str) -> str:
        normalized = normalize_https_url(url)
        from urllib.parse import urlsplit

        parsed = urlsplit(normalized)
        host = (parsed.hostname or "").encode("idna").decode("ascii").lower().rstrip(".")
        if host not in self.allowed_hosts:
            raise ValueError(f"host is not allowlisted: {host}")
        addresses = list(self.resolver(host, parsed.port or 443))
        if not addresses:
            raise ValueError("host did not resolve")
        for raw_address in addresses:
            address = ipaddress.ip_address(raw_address)
            if not address.is_global:
                raise ValueError(f"host resolves to a non-global address: {address}")
        return normalized

    def _request(
        self,
        url: str,
        accept: str,
        follow_redirects: bool,
        max_bytes: int,
        conditional_headers: dict[str, str] | None = None,
    ) -> FetchResponse:
        normalized = self.validate_target(url)
        redirect_handler = _CheckedRedirects(self, follow_redirects)
        context = ssl.create_default_context()
        opener = build_opener(ProxyHandler({}), HTTPSHandler(context=context), redirect_handler)
        headers = {"Accept": accept, "User-Agent": "OnceMesh-Evaluation/0"}
        headers.update(conditional_headers or {})
        request = Request(
            normalized,
            headers=headers,
            method="GET",
        )
        try:
            with opener.open(request, timeout=self.timeout_seconds) as response:
                body = response.read(max_bytes + 1)
                if len(body) > max_bytes:
                    raise ValueError("response exceeds max_bytes")
                return FetchResponse(
                    status=response.status,
                    final_url=response.geturl(),
                    headers=dict(response.headers.items()),
                    body=body,
                )
        except HTTPError as error:
            if error.code == 304:
                return FetchResponse(
                    status=304,
                    final_url=error.geturl(),
                    headers=dict(error.headers.items()),
                    body=b"",
                )
            raise ValueError(f"HTTP request failed with status {error.code}") from error

    def __call__(self, url: str, accept: str, follow_redirects: bool, max_bytes: int) -> FetchResponse:
        return self._request(url, accept, follow_redirects, max_bytes)

    def conditional_get(
        self,
        url: str,
        accept: str,
        follow_redirects: bool,
        max_bytes: int,
        *,
        etag: str | None,
        last_modified: str | None,
    ) -> FetchResponse:
        if etag is None and last_modified is None:
            raise ValueError("conditional GET requires an ETag or Last-Modified value")
        conditional_headers: dict[str, str] = {}
        for name, value in (("If-None-Match", etag), ("If-Modified-Since", last_modified)):
            if value is None:
                continue
            if not value or len(value) > 4096 or "\r" in value or "\n" in value:
                raise ValueError(f"invalid {name} value")
            conditional_headers[name] = value
        return self._request(
            url,
            accept,
            follow_redirects,
            max_bytes,
            conditional_headers,
        )
