"""Authenticated, bounded HTTP transport for the federation experiment."""

from __future__ import annotations

import base64
from collections import defaultdict, deque
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
import secrets
import ssl
import threading
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from .canonical import DIGEST_PATTERN, canonical_json, digest_bytes
from .federation import FederationBundle, PublicPeerCatalog
from .receipt import SIGNATURE_PATTERN, SIGNATURE_PROFILE

FEDERATION_REQUEST_DOMAIN = b"OnceMesh federation HTTP request v1\x00"
EMPTY_BODY_DIGEST = digest_bytes(b"")
NONCE_PATTERN = re.compile(r"^[0-9a-f]{32}$")
BUNDLE_PATH_PATTERN = re.compile(r"^/v0/bundles/(sha256:[0-9a-f]{64})$")
REQUEST_PATH_PATTERN = re.compile(r"^/v0/(?:availability|bundles/sha256:[0-9a-f]{64})$")
AUTH_HEADERS = {
    "peer_id": "OnceMesh-Peer-ID",
    "timestamp": "OnceMesh-Timestamp",
    "nonce": "OnceMesh-Nonce",
    "key_id": "OnceMesh-Key-ID",
    "signature": "OnceMesh-Signature",
}


def _exact_keys(value: Any, expected: set[str], label: str) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError(f"invalid {label} fields")


def _format_time(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_time(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("timestamp must be UTC RFC 3339")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(timezone.utc)


def _signature_value(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode_signature(value: str) -> bytes:
    if not isinstance(value, str) or not SIGNATURE_PATTERN.fullmatch(value):
        raise ValueError("request signature is not canonical base64url")
    decoded = base64.b64decode(value + "==", altchars=b"-_", validate=True)
    if len(decoded) != 64 or _signature_value(decoded) != value:
        raise ValueError("request signature must encode 64 bytes")
    return decoded


def validate_federation_request(request: dict[str, Any]) -> None:
    _exact_keys(
        request,
        {"spec_version", "peer_id", "timestamp", "nonce", "method", "path", "body_digest"},
        "federation request",
    )
    if request["spec_version"] != "oncemesh.federation-request/v0":
        raise ValueError("unsupported federation request version")
    if not isinstance(request["peer_id"], str) or not request["peer_id"]:
        raise ValueError("request peer_id must be a non-empty string")
    _parse_time(request["timestamp"])
    if not isinstance(request["nonce"], str) or not NONCE_PATTERN.fullmatch(request["nonce"]):
        raise ValueError("request nonce is invalid")
    if request["method"] != "GET":
        raise ValueError("unsupported federation request method")
    if not isinstance(request["path"], str) or not REQUEST_PATH_PATTERN.fullmatch(request["path"]):
        raise ValueError("unsupported federation request path")
    if request["body_digest"] != EMPTY_BODY_DIGEST:
        raise ValueError("federation GET body digest must be empty")
    canonical_json(request)


def federation_request_signing_input(request: dict[str, Any]) -> bytes:
    validate_federation_request(request)
    return FEDERATION_REQUEST_DOMAIN + canonical_json(request)


def sign_federation_request(request: dict[str, Any], private_seed: bytes) -> dict[str, str]:
    if not isinstance(private_seed, bytes) or len(private_seed) != 32:
        raise ValueError("request private seed must contain exactly 32 bytes")
    signer = Ed25519PrivateKey.from_private_bytes(private_seed)
    public_key = signer.public_key().public_bytes_raw()
    return {
        "profile": SIGNATURE_PROFILE,
        "key_id": digest_bytes(public_key),
        "value": _signature_value(signer.sign(federation_request_signing_input(request))),
    }


def verify_federation_request(
    request: dict[str, Any], signature: Mapping[str, str], public_key: bytes
) -> bool:
    try:
        _exact_keys(dict(signature), {"profile", "key_id", "value"}, "request signature")
        if signature["profile"] != SIGNATURE_PROFILE:
            return False
        if not isinstance(public_key, bytes) or len(public_key) != 32:
            return False
        if signature["key_id"] != digest_bytes(public_key):
            return False
        Ed25519PublicKey.from_public_bytes(public_key).verify(
            _decode_signature(signature["value"]), federation_request_signing_input(request)
        )
    except (InvalidSignature, KeyError, TypeError, ValueError):
        return False
    return True


@dataclass(frozen=True)
class FederationRequesterConfig:
    peer_id: str
    public_key: bytes

    def __post_init__(self) -> None:
        if (
            not isinstance(self.peer_id, str) or not self.peer_id
            or not isinstance(self.public_key, bytes) or len(self.public_key) != 32
        ):
            raise ValueError("requester peer identity and 32-byte public key are required")
        object.__setattr__(self, "public_key", bytes(self.public_key))


class FederationRequestAuthenticator:
    """Verifies configured requesters and remembers nonces within a bounded window."""

    def __init__(
        self,
        requesters: Mapping[str, bytes],
        *,
        max_age_seconds: int = 60,
        max_future_clock_skew_seconds: int = 5,
        max_remembered_nonces: int = 10_000,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(max_age_seconds, int) or isinstance(max_age_seconds, bool) or not 1 <= max_age_seconds <= 3600:
            raise ValueError("max_age_seconds is outside the supported range")
        if not isinstance(max_future_clock_skew_seconds, int) or isinstance(max_future_clock_skew_seconds, bool) or not 0 <= max_future_clock_skew_seconds <= 300:
            raise ValueError("max_future_clock_skew_seconds is outside the supported range")
        if not isinstance(max_remembered_nonces, int) or isinstance(max_remembered_nonces, bool) or not 1 <= max_remembered_nonces <= 1_000_000:
            raise ValueError("max_remembered_nonces is outside the supported range")
        checked: dict[str, bytes] = {}
        for peer_id, public_key in requesters.items():
            config = FederationRequesterConfig(peer_id, public_key)
            checked[config.peer_id] = config.public_key
        if not checked:
            raise ValueError("at least one configured requester is required")
        self._requesters = checked
        self.max_age_seconds = max_age_seconds
        self.max_future_clock_skew_seconds = max_future_clock_skew_seconds
        self.max_remembered_nonces = max_remembered_nonces
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._nonces: dict[tuple[str, str], datetime] = {}
        self._lock = threading.Lock()

    def authenticate(self, method: str, path: str, headers: Any) -> bool:
        return self.authenticate_peer(method, path, headers) is not None

    def authenticate_peer(self, method: str, path: str, headers: Any) -> str | None:
        try:
            values: dict[str, str] = {}
            for field, header in AUTH_HEADERS.items():
                all_values = headers.get_all(header)
                if all_values is None or len(all_values) != 1:
                    return None
                values[field] = all_values[0]
            request = {
                "spec_version": "oncemesh.federation-request/v0",
                "peer_id": values["peer_id"],
                "timestamp": values["timestamp"],
                "nonce": values["nonce"],
                "method": method,
                "path": path,
                "body_digest": EMPTY_BODY_DIGEST,
            }
            public_key = self._requesters.get(request["peer_id"])
            signature = {
                "profile": SIGNATURE_PROFILE,
                "key_id": values["key_id"],
                "value": values["signature"],
            }
            if public_key is None or not verify_federation_request(request, signature, public_key):
                return None
            observed_at = self._clock().astimezone(timezone.utc)
            signed_at = _parse_time(request["timestamp"])
            if signed_at < observed_at - timedelta(seconds=self.max_age_seconds):
                return None
            if signed_at > observed_at + timedelta(seconds=self.max_future_clock_skew_seconds):
                return None
            nonce_key = (request["peer_id"], request["nonce"])
            with self._lock:
                self._nonces = {
                    key: expires for key, expires in self._nonces.items() if expires > observed_at
                }
                if nonce_key in self._nonces or len(self._nonces) >= self.max_remembered_nonces:
                    return None
                self._nonces[nonce_key] = observed_at + timedelta(seconds=self.max_age_seconds)
            return request["peer_id"]
        except (AttributeError, KeyError, TypeError, ValueError):
            return None


class FederationRequestRateLimiter:
    """Bounded per-peer sliding-window request limiter for the pilot server."""

    def __init__(
        self,
        max_requests: int,
        window_seconds: int,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if isinstance(max_requests, bool) or not isinstance(max_requests, int) or not 1 <= max_requests <= 1_000_000:
            raise ValueError("max_requests is outside the supported range")
        if isinstance(window_seconds, bool) or not isinstance(window_seconds, int) or not 1 <= window_seconds <= 3600:
            raise ValueError("window_seconds is outside the supported range")
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._requests: dict[str, deque[datetime]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, peer_id: str) -> bool:
        observed_at = self._clock().astimezone(timezone.utc)
        boundary = observed_at - timedelta(seconds=self.window_seconds)
        with self._lock:
            events = self._requests[peer_id]
            while events and events[0] <= boundary:
                events.popleft()
            if len(events) >= self.max_requests:
                return False
            events.append(observed_at)
            return True


def _bundle_document(bundle: FederationBundle) -> dict[str, Any]:
    return {
        "spec_version": "oncemesh.federation-bundle/v0",
        "manifest": deepcopy(bundle.manifest),
        "receipt": deepcopy(bundle.receipt),
        "artifacts": {
            name: base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")
            for name, data in bundle.artifacts.items()
        },
    }


class FederationHTTPServer:
    """Threaded reference server suitable for tests and controlled pilots."""

    def __init__(
        self,
        catalog: PublicPeerCatalog,
        authenticator: FederationRequestAuthenticator,
        *,
        host: str = "127.0.0.1",
        port: int = 0,
        max_response_bytes: int = 50_000_000,
        clock: Callable[[], datetime] | None = None,
        tls_context: ssl.SSLContext | None = None,
        max_concurrent_requests: int = 32,
        rate_limiter: FederationRequestRateLimiter | None = None,
    ) -> None:
        if not isinstance(max_response_bytes, int) or isinstance(max_response_bytes, bool) or not 1024 <= max_response_bytes <= 1_000_000_000:
            raise ValueError("max_response_bytes is outside the supported range")
        if isinstance(max_concurrent_requests, bool) or not isinstance(max_concurrent_requests, int) or not 1 <= max_concurrent_requests <= 10_000:
            raise ValueError("max_concurrent_requests is outside the supported range")
        selected_clock = clock or (lambda: datetime.now(timezone.utc))
        request_slots = threading.BoundedSemaphore(max_concurrent_requests)

        class Handler(BaseHTTPRequestHandler):
            def _status(self, status: int) -> None:
                self.send_response(status)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def _json(self, value: dict[str, Any]) -> None:
                encoded = canonical_json(value)
                if len(encoded) > max_response_bytes:
                    self._status(413)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def do_GET(self) -> None:  # noqa: N802
                if not request_slots.acquire(blocking=False):
                    self._status(503)
                    return
                try:
                    requester = authenticator.authenticate_peer("GET", self.path, self.headers)
                    if requester is None:
                        self._status(401)
                        return
                    if rate_limiter is not None and not rate_limiter.allow(requester):
                        self._status(429)
                        return
                    if self.path == "/v0/availability":
                        self._json(catalog.availability(selected_clock()))
                        return
                    match = BUNDLE_PATH_PATTERN.fullmatch(self.path)
                    if match is None:
                        self._status(404)
                        return
                    bundle = catalog.fetch_bundle(match.group(1))
                    if bundle is None:
                        self._status(404)
                        return
                    self._json(_bundle_document(bundle))
                finally:
                    request_slots.release()

            def do_POST(self) -> None:  # noqa: N802
                self._status(405)

            def log_message(self, format: str, *args: Any) -> None:
                return

        self._server = ThreadingHTTPServer((host, port), Handler)
        self._server.daemon_threads = True
        if tls_context is not None:
            tls_context.minimum_version = ssl.TLSVersion.TLSv1_2
            self._server.socket = tls_context.wrap_socket(self._server.socket, server_side=True)
        self._scheme = "https" if tls_context is not None else "http"
        self._thread: threading.Thread | None = None

    @property
    def address(self) -> tuple[str, int]:
        host, port = self._server.server_address[:2]
        return str(host), int(port)

    @property
    def base_url(self) -> str:
        host, port = self.address
        return f"{self._scheme}://{host}:{port}"

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("federation HTTP server is already started")
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def close(self) -> None:
        if self._thread is not None:
            self._server.shutdown()
            self._thread.join(timeout=5)
            self._thread = None
        self._server.server_close()

    def __enter__(self) -> FederationHTTPServer:
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


def _strict_json(raw: bytes) -> Any:
    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)


def _decode_blob(value: str) -> bytes:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]*", value):
        raise ValueError("artifact is not base64url")
    if len(value) % 4 == 1:
        raise ValueError("artifact base64url length is invalid")
    decoded = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    if base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii") != value:
        raise ValueError("artifact base64url is not canonical")
    return decoded


class HttpFederationPeer:
    """FederationPeer client using signed GET requests and bounded responses."""

    def __init__(
        self,
        base_url: str,
        requester_peer_id: str,
        request_private_seed: bytes,
        *,
        timeout_seconds: float = 5.0,
        max_availability_response_bytes: int = 1_000_000,
        max_bundle_response_bytes: int = 50_000_000,
        allow_insecure_loopback: bool = False,
        clock: Callable[[], datetime] | None = None,
        nonce_factory: Callable[[], str] | None = None,
        tls_context: ssl.SSLContext | None = None,
    ) -> None:
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError("base_url must contain only an HTTP(S) origin")
        if parsed.scheme == "http" and not (
            allow_insecure_loopback and parsed.hostname in {"127.0.0.1", "::1", "localhost"}
        ):
            raise ValueError("plain HTTP is permitted only for explicitly enabled loopback tests")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("base_url must not contain user information")
        if tls_context is not None and parsed.scheme != "https":
            raise ValueError("a TLS context requires an HTTPS base_url")
        if not isinstance(requester_peer_id, str) or not requester_peer_id:
            raise ValueError("requester_peer_id must not be empty")
        if not isinstance(request_private_seed, bytes) or len(request_private_seed) != 32:
            raise ValueError("request private seed must contain exactly 32 bytes")
        if not isinstance(timeout_seconds, (int, float)) or isinstance(timeout_seconds, bool) or not 0 < timeout_seconds <= 60:
            raise ValueError("timeout_seconds is outside the supported range")
        for value, label in (
            (max_availability_response_bytes, "max_availability_response_bytes"),
            (max_bundle_response_bytes, "max_bundle_response_bytes"),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 1_000_000_000:
                raise ValueError(f"{label} is outside the supported range")
        self.base_url = base_url.rstrip("/")
        self.requester_peer_id = requester_peer_id
        self._seed = bytes(request_private_seed)
        self.timeout_seconds = float(timeout_seconds)
        self.max_availability_response_bytes = max_availability_response_bytes
        self.max_bundle_response_bytes = max_bundle_response_bytes
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._nonce_factory = nonce_factory or (lambda: secrets.token_hex(16))
        handlers: list[Any] = [_NoRedirect()]
        if tls_context is not None:
            handlers.append(HTTPSHandler(context=tls_context))
        self._opener = build_opener(*handlers)

    def _get(self, path: str, maximum: int, now: datetime | None = None) -> Any:
        timestamp = (now or self._clock()).astimezone(timezone.utc)
        request_object = {
            "spec_version": "oncemesh.federation-request/v0",
            "peer_id": self.requester_peer_id,
            "timestamp": _format_time(timestamp),
            "nonce": self._nonce_factory(),
            "method": "GET",
            "path": path,
            "body_digest": EMPTY_BODY_DIGEST,
        }
        signature = sign_federation_request(request_object, self._seed)
        headers = {
            AUTH_HEADERS["peer_id"]: request_object["peer_id"],
            AUTH_HEADERS["timestamp"]: request_object["timestamp"],
            AUTH_HEADERS["nonce"]: request_object["nonce"],
            AUTH_HEADERS["key_id"]: signature["key_id"],
            AUTH_HEADERS["signature"]: signature["value"],
            "Accept": "application/json",
        }
        request = Request(self.base_url + path, headers=headers, method="GET")
        with self._opener.open(request, timeout=self.timeout_seconds) as response:
            if response.status != 200:
                raise ValueError("federation response status is not successful")
            if response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
                raise ValueError("federation response content type is invalid")
            if response.headers.get("Content-Encoding"):
                raise ValueError("compressed federation responses are unsupported")
            declared = response.headers.get("Content-Length")
            if declared is not None and (not declared.isdigit() or int(declared) > maximum):
                raise ValueError("federation response exceeds byte limit")
            raw = response.read(maximum + 1)
            if len(raw) > maximum:
                raise ValueError("federation response exceeds byte limit")
        return _strict_json(raw)

    def availability(self, now: datetime | None = None) -> dict[str, Any]:
        try:
            value = self._get("/v0/availability", self.max_availability_response_bytes, now)
            if not isinstance(value, dict):
                raise ValueError("availability response must be an object")
            return value
        except HTTPError as error:
            error.close()
            raise ValueError("federation availability request failed") from error
        except (URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("federation availability request failed") from error

    def fetch_bundle(self, result_digest: str) -> FederationBundle | None:
        if not isinstance(result_digest, str) or not DIGEST_PATTERN.fullmatch(result_digest):
            return None
        try:
            value = self._get(f"/v0/bundles/{result_digest}", self.max_bundle_response_bytes)
            _exact_keys(value, {"spec_version", "manifest", "receipt", "artifacts"}, "federation bundle")
            if value["spec_version"] != "oncemesh.federation-bundle/v0":
                raise ValueError("unsupported federation bundle version")
            if not isinstance(value["manifest"], dict) or not isinstance(value["receipt"], dict) or not isinstance(value["artifacts"], dict):
                raise ValueError("federation bundle members are invalid")
            artifacts = {name: _decode_blob(encoded) for name, encoded in value["artifacts"].items()}
            if any(not isinstance(name, str) or not name for name in artifacts):
                raise ValueError("federation artifact names are invalid")
            return FederationBundle(value["manifest"], value["receipt"], artifacts)
        except HTTPError as error:
            error.close()
            return None
        except (URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
            return None
