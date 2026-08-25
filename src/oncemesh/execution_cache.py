"""Framework-neutral exact execution cache bridge."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
from threading import RLock
from typing import Callable, Iterable, Mapping, Protocol

from .authorization import validate_authorization_partition
from .cache import Policy, publish_result, reuse
from .canonical import canonical_json
from .coordination import ProcessFileLock
from .store import Store, StoreReadError


VALUE_MEDIA_TYPE = "application/vnd.oncemesh.execution-cache-value-v1"
MAX_TYPE_TAG_BYTES = 1024


@dataclass(frozen=True)
class ExecutionCacheKey:
    """One exact framework or workflow-runtime cache key."""

    namespace: tuple[str, ...]
    key: str

    def __post_init__(self) -> None:
        if not isinstance(self.namespace, tuple) or any(
            not isinstance(part, str) or not part for part in self.namespace
        ):
            raise ValueError("namespace must be a tuple of non-empty strings")
        if not isinstance(self.key, str) or not self.key:
            raise ValueError("key must be a non-empty string")


@dataclass(frozen=True)
class EncodedExecutionValue:
    """Serializer-owned type tag and inert payload bytes."""

    type_tag: str
    payload: bytes

    def __post_init__(self) -> None:
        _validate_type_tag(self.type_tag)
        if not isinstance(self.payload, bytes):
            raise ValueError("payload must be bytes")


class EpochRegistry(Protocol):
    def epochs(self, namespace: tuple[str, ...]) -> tuple[int, int]: ...

    def rotate_all(self) -> None: ...

    def rotate_namespaces(self, namespaces: Iterable[tuple[str, ...]]) -> None: ...


class MemoryEpochRegistry:
    """Single-process clear epochs for memory-backed trials."""

    def __init__(self) -> None:
        self._global = 0
        self._namespaces: dict[tuple[str, ...], int] = {}
        self._lock = RLock()

    def epochs(self, namespace: tuple[str, ...]) -> tuple[int, int]:
        with self._lock:
            return self._global, self._namespaces.get(namespace, 0)

    def rotate_all(self) -> None:
        with self._lock:
            self._global += 1

    def rotate_namespaces(self, namespaces: Iterable[tuple[str, ...]]) -> None:
        with self._lock:
            for namespace in namespaces:
                _validate_namespace(namespace)
                self._namespaces[namespace] = self._namespaces.get(namespace, 0) + 1


class FilesystemEpochRegistry:
    """Atomically persisted cross-process epoch registry."""

    def __init__(self, path: str | Path, *, lock_timeout: float = 30.0) -> None:
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_path = Path(f"{self.path}.lock")
        self.lock_timeout = lock_timeout

    def _locked(self) -> ProcessFileLock:
        return ProcessFileLock(self.lock_path, timeout=self.lock_timeout)

    def _read(self) -> dict:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"version": 1, "global": 0, "namespaces": []}
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ValueError("execution cache epoch registry is unreadable") from error
        if (
            not isinstance(value, dict)
            or set(value) != {"version", "global", "namespaces"}
            or value["version"] != 1
            or isinstance(value["global"], bool)
            or not isinstance(value["global"], int)
            or value["global"] < 0
            or not isinstance(value["namespaces"], list)
        ):
            raise ValueError("execution cache epoch registry is invalid")
        for entry in value["namespaces"]:
            if (
                not isinstance(entry, dict)
                or set(entry) != {"namespace", "epoch"}
                or not isinstance(entry["namespace"], list)
                or isinstance(entry["epoch"], bool)
                or not isinstance(entry["epoch"], int)
                or entry["epoch"] < 0
            ):
                raise ValueError("execution cache namespace epoch is invalid")
            _validate_namespace(tuple(entry["namespace"]))
        return value

    def _write(self, value: dict) -> None:
        data = canonical_json(value)
        handle, temporary_name = tempfile.mkstemp(prefix=".oncemesh-epochs-", dir=self.path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(handle, "wb") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def epochs(self, namespace: tuple[str, ...]) -> tuple[int, int]:
        _validate_namespace(namespace)
        with self._locked():
            value = self._read()
            by_namespace = {
                tuple(item["namespace"]): item["epoch"] for item in value["namespaces"]
            }
            return value["global"], by_namespace.get(namespace, 0)

    def rotate_all(self) -> None:
        with self._locked():
            value = self._read()
            value["global"] += 1
            self._write(value)

    def rotate_namespaces(self, namespaces: Iterable[tuple[str, ...]]) -> None:
        checked = list(namespaces)
        for namespace in checked:
            _validate_namespace(namespace)
        with self._locked():
            value = self._read()
            by_namespace = {
                tuple(item["namespace"]): item["epoch"] for item in value["namespaces"]
            }
            for namespace in checked:
                by_namespace[namespace] = by_namespace.get(namespace, 0) + 1
            value["namespaces"] = [
                {"namespace": list(namespace), "epoch": epoch}
                for namespace, epoch in sorted(by_namespace.items())
            ]
            self._write(value)


def _validate_namespace(namespace: tuple[str, ...]) -> None:
    if not isinstance(namespace, tuple) or any(
        not isinstance(part, str) or not part for part in namespace
    ):
        raise ValueError("namespace must be a tuple of non-empty strings")


def _validate_type_tag(type_tag: str) -> bytes:
    if not isinstance(type_tag, str) or not type_tag:
        raise ValueError("type tag must be a non-empty string")
    encoded = type_tag.encode("utf-8")
    if len(encoded) > MAX_TYPE_TAG_BYTES or "\x00" in type_tag:
        raise ValueError("type tag is invalid")
    return encoded


def pack_execution_value(value: EncodedExecutionValue) -> bytes:
    tag = _validate_type_tag(value.type_tag)
    return len(tag).to_bytes(4, "big") + tag + value.payload


def unpack_execution_value(data: bytes) -> EncodedExecutionValue:
    if not isinstance(data, bytes) or len(data) < 5:
        raise ValueError("execution cache value envelope is truncated")
    tag_size = int.from_bytes(data[:4], "big")
    if tag_size < 1 or tag_size > MAX_TYPE_TAG_BYTES or len(data) < 4 + tag_size:
        raise ValueError("execution cache value envelope has an invalid type tag length")
    try:
        tag = data[4 : 4 + tag_size].decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("execution cache value type tag is not UTF-8") from error
    return EncodedExecutionValue(tag, data[4 + tag_size :])


class ExecutionCacheBridge:
    """Exact, private cache operations shared by runtime-specific adapters."""

    def __init__(
        self,
        *,
        runtime: str,
        serializer: str,
        authorization_partition: str,
        stores: Iterable[Store],
        publish_to: Store,
        producer: str,
        epochs: EpochRegistry | None = None,
        clock: Callable[[], datetime] | None = None,
        enabled: bool = True,
    ) -> None:
        if not isinstance(runtime, str) or not runtime:
            raise ValueError("runtime must be a non-empty string")
        if not isinstance(serializer, str) or not serializer:
            raise ValueError("serializer must be a non-empty string")
        validate_authorization_partition(authorization_partition)
        if not isinstance(producer, str) or not producer:
            raise ValueError("producer must be a non-empty string")
        selected_stores = tuple(stores)
        if not selected_stores:
            raise ValueError("at least one execution cache read store is required")
        if any(getattr(store, "federation_import_only", False) for store in (*selected_stores, publish_to)):
            raise ValueError("generic execution cache values cannot use a federation store")
        self.runtime = runtime
        self.serializer = serializer
        self.authorization_partition = authorization_partition
        self.stores = selected_stores
        self.publish_to = publish_to
        self.producer = producer
        self.epochs = epochs or MemoryEpochRegistry()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.enabled = enabled

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)

    def action_for(self, key: ExecutionCacheKey) -> dict:
        global_epoch, namespace_epoch = self.epochs.epochs(key.namespace)
        return {
            "spec_version": "oncemesh.action/v0",
            "operation": {"name": "framework.execution-cache", "version": "1"},
            "inputs": {
                "runtime": self.runtime,
                "namespace": list(key.namespace),
                "key": key.key,
            },
            "executor": {
                "name": "oncemesh.execution-cache-bridge",
                "version": "0",
                "config": {
                    "serializer": self.serializer,
                    "global_epoch": global_epoch,
                    "namespace_epoch": namespace_epoch,
                },
            },
            "output_schema": "oncemesh.execution-cache-value/v1",
            "vary": {"authorization_partition": self.authorization_partition},
        }

    def get(self, keys: Iterable[ExecutionCacheKey]) -> dict[ExecutionCacheKey, EncodedExecutionValue]:
        if not self.enabled:
            return {}
        now = self._now()
        results: dict[ExecutionCacheKey, EncodedExecutionValue] = {}
        for key in keys:
            try:
                outcome = reuse(
                    self.action_for(key),
                    self.stores,
                    Policy(
                        now=now,
                        trusted_producers=frozenset({self.producer}),
                        permit_no_expiry=True,
                    ),
                )
            except StoreReadError:
                continue
            if not outcome.hit:
                continue
            try:
                if set(outcome.artifacts) != {"value"}:
                    continue
                descriptor = outcome.manifest["artifacts"][0] if outcome.manifest else {}
                if descriptor.get("name") != "value" or descriptor.get("media_type") != VALUE_MEDIA_TYPE:
                    continue
                results[key] = unpack_execution_value(outcome.artifacts["value"])
            except (KeyError, TypeError, ValueError):
                continue
        return results

    def set(
        self,
        pairs: Mapping[ExecutionCacheKey, tuple[EncodedExecutionValue, int | None]],
    ) -> None:
        if not self.enabled:
            return
        now = self._now()
        for key, (value, ttl) in pairs.items():
            if ttl is not None and (
                isinstance(ttl, bool) or not isinstance(ttl, int)
            ):
                raise ValueError("TTL must be an integer number of seconds or null")
            if ttl is not None and ttl <= 0:
                continue
            publish_result(
                self.publish_to,
                self.action_for(key),
                {"value": (pack_execution_value(value), VALUE_MEDIA_TYPE)},
                producer=self.producer,
                produced_at=now,
                fresh_until=now + timedelta(seconds=ttl) if ttl is not None else None,
            )

    def clear(self, namespaces: Iterable[tuple[str, ...]] | None = None) -> None:
        if namespaces is None:
            self.epochs.rotate_all()
        else:
            self.epochs.rotate_namespaces(namespaces)

    def _now(self) -> datetime:
        now = self.clock()
        if not isinstance(now, datetime) or now.tzinfo is None:
            raise ValueError("execution cache clock must return a timezone-aware datetime")
        return now.astimezone(timezone.utc)
