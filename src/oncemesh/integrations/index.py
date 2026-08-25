"""Mutable active-key metadata layered over immutable OnceMesh cache objects."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from threading import RLock
from typing import Any, Callable, Generic, Protocol, TypeVar
from uuid import uuid4

from ..canonical import canonical_json, digest_bytes
from ..coordination import CoordinationTimeoutError, ProcessFileLock
from ..execution_cache import ExecutionCacheKey
from .base import RuntimeCacheAdapter


ValueT = TypeVar("ValueT")
NativeKey = tuple[tuple[str, ...], str]
IndexEntry = tuple[int, bool, str | None]


def _validate_native(namespace: tuple[str, ...], key: str) -> None:
    if not isinstance(namespace, tuple) or any(
        not isinstance(part, str) or not part for part in namespace
    ):
        raise ValueError("namespace must be a tuple of non-empty strings")
    if not isinstance(key, str) or not key:
        raise ValueError("native key must be a non-empty string")


class ActiveKeyIndex(Protocol):
    def generation(self, namespace: tuple[str, ...], key: str) -> int: ...
    def is_active(self, namespace: tuple[str, ...], key: str) -> bool: ...
    def active_revision(
        self, namespace: tuple[str, ...], key: str
    ) -> tuple[int, str | None] | None: ...
    def prepare_put(self, namespace: tuple[str, ...], key: str) -> int: ...
    def activate(self, namespace: tuple[str, ...], key: str) -> None: ...
    def publish_and_activate(
        self,
        namespace: tuple[str, ...],
        key: str,
        publisher: Callable[[int, str], None],
    ) -> int: ...
    def delete(self, namespace: tuple[str, ...], key: str) -> bool: ...
    def active_keys(self, namespace: tuple[str, ...]) -> tuple[str, ...]: ...
    def clear_namespace(self, namespace: tuple[str, ...]) -> int: ...
    def clear_all(self) -> int: ...


class MemoryActiveKeyIndex:
    def __init__(self) -> None:
        self._entries: dict[NativeKey, IndexEntry] = {}
        self._lock = RLock()

    def generation(self, namespace: tuple[str, ...], key: str) -> int:
        _validate_native(namespace, key)
        with self._lock:
            return self._entries.get((namespace, key), (0, False, None))[0]

    def is_active(self, namespace: tuple[str, ...], key: str) -> bool:
        _validate_native(namespace, key)
        with self._lock:
            return self._entries.get((namespace, key), (0, False, None))[1]

    def active_revision(
        self, namespace: tuple[str, ...], key: str
    ) -> tuple[int, str | None] | None:
        _validate_native(namespace, key)
        with self._lock:
            generation, active, publication_id = self._entries.get(
                (namespace, key), (0, False, None)
            )
            return (generation, publication_id) if active else None

    def prepare_put(self, namespace: tuple[str, ...], key: str) -> int:
        _validate_native(namespace, key)
        with self._lock:
            generation, active, _ = self._entries.get((namespace, key), (0, False, None))
            if active:
                generation += 1
            self._entries[(namespace, key)] = (generation, False, None)
            return generation

    def activate(self, namespace: tuple[str, ...], key: str) -> None:
        _validate_native(namespace, key)
        with self._lock:
            generation, _, publication_id = self._entries.get(
                (namespace, key), (0, False, None)
            )
            self._entries[(namespace, key)] = (generation, True, publication_id)

    def publish_and_activate(
        self,
        namespace: tuple[str, ...],
        key: str,
        publisher: Callable[[int, str], None],
    ) -> int:
        _validate_native(namespace, key)
        with self._lock:
            generation, active, _ = self._entries.get((namespace, key), (0, False, None))
            generation += int(active)
            publication_id = uuid4().hex
            publisher(generation, publication_id)
            self._entries[(namespace, key)] = (generation, True, publication_id)
            return generation

    def delete(self, namespace: tuple[str, ...], key: str) -> bool:
        _validate_native(namespace, key)
        with self._lock:
            generation, active, _ = self._entries.get((namespace, key), (0, False, None))
            if not active:
                return False
            self._entries[(namespace, key)] = (generation + 1, False, None)
            return True

    def active_keys(self, namespace: tuple[str, ...]) -> tuple[str, ...]:
        if not isinstance(namespace, tuple):
            raise ValueError("namespace must be a tuple")
        with self._lock:
            return tuple(sorted(key for (ns, key), (_, active, _) in self._entries.items() if ns == namespace and active))

    def clear_namespace(self, namespace: tuple[str, ...]) -> int:
        if not isinstance(namespace, tuple):
            raise ValueError("namespace must be a tuple")
        with self._lock:
            changed = 0
            for native, (generation, active, _) in list(self._entries.items()):
                if native[0] == namespace and active:
                    self._entries[native] = (generation + 1, False, None)
                    changed += 1
            return changed

    def clear_all(self) -> int:
        with self._lock:
            changed = 0
            for native, (generation, active, _) in list(self._entries.items()):
                if active:
                    self._entries[native] = (generation + 1, False, None)
                    changed += 1
            return changed


class FilesystemActiveKeyIndex:
    """Atomic cross-process active-key index with transactional publication."""

    def __init__(self, path: str | Path, *, lock_timeout: float = 30.0) -> None:
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_path = Path(f"{self.path}.lock")
        self.lock_timeout = lock_timeout

    def _locked(self) -> ProcessFileLock:
        return ProcessFileLock(self.lock_path, timeout=self.lock_timeout)

    def _read(self) -> dict[NativeKey, IndexEntry]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ValueError("active-key index is unreadable") from error
        if not isinstance(value, dict) or set(value) != {"version", "entries"} or value["version"] not in (1, 2) or not isinstance(value["entries"], list):
            raise ValueError("active-key index is invalid")
        version = value["version"]
        entries: dict[NativeKey, IndexEntry] = {}
        for item in value["entries"]:
            expected = {"namespace", "key", "generation", "active"}
            if version == 2:
                expected.add("publication_id")
            if not isinstance(item, dict) or set(item) != expected:
                raise ValueError("active-key index entry is invalid")
            if not isinstance(item["namespace"], list):
                raise ValueError("active-key index namespace is invalid")
            namespace = tuple(item["namespace"])
            key = item["key"]
            _validate_native(namespace, key)
            generation = item["generation"]
            active = item["active"]
            publication_id = item.get("publication_id")
            if isinstance(generation, bool) or not isinstance(generation, int) or generation < 0 or not isinstance(active, bool):
                raise ValueError("active-key index entry state is invalid")
            if publication_id is not None and (
                not isinstance(publication_id, str)
                or len(publication_id) != 32
                or any(character not in "0123456789abcdef" for character in publication_id)
            ):
                raise ValueError("active-key index publication id is invalid")
            native = (namespace, key)
            if native in entries:
                raise ValueError("active-key index contains a duplicate key")
            entries[native] = (generation, active, publication_id)
        return entries

    def _write(self, entries: dict[NativeKey, IndexEntry]) -> None:
        value = {
            "version": 2,
            "entries": [
                {"namespace": list(namespace), "key": key, "generation": generation, "active": active, "publication_id": publication_id}
                for (namespace, key), (generation, active, publication_id) in sorted(entries.items())
            ],
        }
        data = canonical_json(value)
        handle, temporary_name = tempfile.mkstemp(prefix=".oncemesh-index-", dir=self.path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(handle, "wb") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def _mutate(self, operation: Any) -> Any:
        with self._locked():
            entries = self._read()
            result = operation(entries)
            self._write(entries)
            return result

    def generation(self, namespace: tuple[str, ...], key: str) -> int:
        _validate_native(namespace, key)
        with self._locked():
            return self._read().get((namespace, key), (0, False, None))[0]

    def is_active(self, namespace: tuple[str, ...], key: str) -> bool:
        _validate_native(namespace, key)
        with self._locked():
            return self._read().get((namespace, key), (0, False, None))[1]

    def active_revision(
        self, namespace: tuple[str, ...], key: str
    ) -> tuple[int, str | None] | None:
        _validate_native(namespace, key)
        with self._locked():
            generation, active, publication_id = self._read().get(
                (namespace, key), (0, False, None)
            )
            return (generation, publication_id) if active else None

    def prepare_put(self, namespace: tuple[str, ...], key: str) -> int:
        _validate_native(namespace, key)
        def operation(entries: dict[NativeKey, IndexEntry]) -> int:
            generation, active, _ = entries.get((namespace, key), (0, False, None))
            generation += int(active)
            entries[(namespace, key)] = (generation, False, None)
            return generation
        return self._mutate(operation)

    def activate(self, namespace: tuple[str, ...], key: str) -> None:
        _validate_native(namespace, key)
        def operation(entries: dict[NativeKey, IndexEntry]) -> None:
            generation, _, publication_id = entries.get((namespace, key), (0, False, None))
            entries[(namespace, key)] = (generation, True, publication_id)
        self._mutate(operation)

    def publish_and_activate(
        self,
        namespace: tuple[str, ...],
        key: str,
        publisher: Callable[[int, str], None],
    ) -> int:
        _validate_native(namespace, key)
        with self._locked():
            entries = self._read()
            generation, active, _ = entries.get((namespace, key), (0, False, None))
            generation += int(active)
            publication_id = uuid4().hex
            publisher(generation, publication_id)
            entries[(namespace, key)] = (generation, True, publication_id)
            self._write(entries)
            return generation

    def delete(self, namespace: tuple[str, ...], key: str) -> bool:
        _validate_native(namespace, key)
        def operation(entries: dict[NativeKey, IndexEntry]) -> bool:
            generation, active, _ = entries.get((namespace, key), (0, False, None))
            if not active:
                return False
            entries[(namespace, key)] = (generation + 1, False, None)
            return True
        return self._mutate(operation)

    def active_keys(self, namespace: tuple[str, ...]) -> tuple[str, ...]:
        with self._locked():
            entries = self._read()
            return tuple(sorted(key for (ns, key), (_, active, _) in entries.items() if ns == namespace and active))

    def clear_namespace(self, namespace: tuple[str, ...]) -> int:
        def operation(entries: dict[NativeKey, IndexEntry]) -> int:
            changed = 0
            for native, (generation, active, _) in list(entries.items()):
                if native[0] == namespace and active:
                    entries[native] = (generation + 1, False, None)
                    changed += 1
            return changed
        return self._mutate(operation)

    def clear_all(self) -> int:
        def operation(entries: dict[NativeKey, IndexEntry]) -> int:
            changed = 0
            for native, (generation, active, _) in list(entries.items()):
                if active:
                    entries[native] = (generation + 1, False, None)
                    changed += 1
            return changed
        return self._mutate(operation)


class SQLiteActiveKeyIndex:
    """WAL-backed cross-process active-key index for contended local use."""

    SCHEMA_VERSION = 1

    def __init__(
        self,
        path: str | Path,
        *,
        busy_timeout: float = 30.0,
        synchronous: str = "NORMAL",
    ) -> None:
        if busy_timeout < 0:
            raise ValueError("SQLite busy timeout must be non-negative")
        if synchronous not in ("NORMAL", "FULL"):
            raise ValueError("SQLite synchronous mode must be NORMAL or FULL")
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.busy_timeout = float(busy_timeout)
        self.synchronous = synchronous
        self._initialize()

    @staticmethod
    def _namespace(namespace: tuple[str, ...]) -> str:
        if not isinstance(namespace, tuple) or any(
            not isinstance(part, str) or not part for part in namespace
        ):
            raise ValueError("namespace must be a tuple of non-empty strings")
        return canonical_json(list(namespace)).decode("utf-8")

    @staticmethod
    def _translate_locked(error: sqlite3.OperationalError) -> None:
        code = getattr(error, "sqlite_errorcode", 0) & 0xFF
        if code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED) or "locked" in str(error).lower():
            raise CoordinationTimeoutError("timed out acquiring SQLite index transaction") from error
        raise error

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            timeout=self.busy_timeout,
            isolation_level=None,
        )
        connection.execute(f"PRAGMA busy_timeout = {round(self.busy_timeout * 1000)}")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA synchronous = {self.synchronous}")
        return connection

    def _initialize(self) -> None:
        connection = self._connect()
        try:
            mode = connection.execute("PRAGMA journal_mode = WAL").fetchone()
            if mode is None or str(mode[0]).lower() != "wal":
                raise RuntimeError("SQLite active-key index could not enable WAL mode")
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version not in (0, self.SCHEMA_VERSION):
                raise ValueError(f"unsupported SQLite active-key index version: {version}")
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS active_keys (
                    namespace TEXT NOT NULL,
                    native_key TEXT NOT NULL,
                    generation INTEGER NOT NULL CHECK (generation >= 0),
                    active INTEGER NOT NULL CHECK (active IN (0, 1)),
                    publication_id TEXT NULL CHECK (
                        publication_id IS NULL OR (
                            length(publication_id) = 32
                            AND publication_id NOT GLOB '*[^0-9a-f]*'
                        )
                    ),
                    PRIMARY KEY (namespace, native_key)
                ) WITHOUT ROWID
                """
            )
            connection.execute(f"PRAGMA user_version = {self.SCHEMA_VERSION}")
            connection.commit()
        except sqlite3.OperationalError as error:
            if connection.in_transaction:
                connection.rollback()
            self._translate_locked(error)
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def _transaction(self, operation: Callable[[sqlite3.Connection], Any]) -> Any:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            result = operation(connection)
            connection.commit()
            return result
        except sqlite3.OperationalError as error:
            if connection.in_transaction:
                connection.rollback()
            self._translate_locked(error)
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _upsert(
        connection: sqlite3.Connection,
        namespace: str,
        key: str,
        generation: int,
        active: bool,
        publication_id: str | None,
    ) -> None:
        connection.execute(
            """
            INSERT INTO active_keys
                (namespace, native_key, generation, active, publication_id)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(namespace, native_key) DO UPDATE SET
                generation = excluded.generation,
                active = excluded.active,
                publication_id = excluded.publication_id
            """,
            (namespace, key, generation, int(active), publication_id),
        )

    def _entry(
        self, connection: sqlite3.Connection, namespace: str, key: str
    ) -> IndexEntry:
        row = connection.execute(
            """
            SELECT generation, active, publication_id
            FROM active_keys WHERE namespace = ? AND native_key = ?
            """,
            (namespace, key),
        ).fetchone()
        if row is None:
            return 0, False, None
        return int(row[0]), bool(row[1]), row[2]

    def generation(self, namespace: tuple[str, ...], key: str) -> int:
        _validate_native(namespace, key)
        connection = self._connect()
        try:
            return self._entry(connection, self._namespace(namespace), key)[0]
        finally:
            connection.close()

    def is_active(self, namespace: tuple[str, ...], key: str) -> bool:
        _validate_native(namespace, key)
        connection = self._connect()
        try:
            return self._entry(connection, self._namespace(namespace), key)[1]
        finally:
            connection.close()

    def active_revision(
        self, namespace: tuple[str, ...], key: str
    ) -> tuple[int, str | None] | None:
        _validate_native(namespace, key)
        connection = self._connect()
        try:
            generation, active, publication_id = self._entry(
                connection, self._namespace(namespace), key
            )
            return (generation, publication_id) if active else None
        finally:
            connection.close()

    def prepare_put(self, namespace: tuple[str, ...], key: str) -> int:
        _validate_native(namespace, key)
        encoded_namespace = self._namespace(namespace)

        def operation(connection: sqlite3.Connection) -> int:
            generation, active, _ = self._entry(connection, encoded_namespace, key)
            generation += int(active)
            self._upsert(connection, encoded_namespace, key, generation, False, None)
            return generation

        return self._transaction(operation)

    def activate(self, namespace: tuple[str, ...], key: str) -> None:
        _validate_native(namespace, key)
        encoded_namespace = self._namespace(namespace)

        def operation(connection: sqlite3.Connection) -> None:
            generation, _, publication_id = self._entry(connection, encoded_namespace, key)
            self._upsert(connection, encoded_namespace, key, generation, True, publication_id)

        self._transaction(operation)

    def publish_and_activate(
        self,
        namespace: tuple[str, ...],
        key: str,
        publisher: Callable[[int, str], None],
    ) -> int:
        _validate_native(namespace, key)
        encoded_namespace = self._namespace(namespace)

        def operation(connection: sqlite3.Connection) -> int:
            generation, active, _ = self._entry(connection, encoded_namespace, key)
            generation += int(active)
            publication_id = uuid4().hex
            publisher(generation, publication_id)
            self._upsert(
                connection,
                encoded_namespace,
                key,
                generation,
                True,
                publication_id,
            )
            return generation

        return self._transaction(operation)

    def delete(self, namespace: tuple[str, ...], key: str) -> bool:
        _validate_native(namespace, key)
        encoded_namespace = self._namespace(namespace)

        def operation(connection: sqlite3.Connection) -> bool:
            generation, active, _ = self._entry(connection, encoded_namespace, key)
            if not active:
                return False
            self._upsert(connection, encoded_namespace, key, generation + 1, False, None)
            return True

        return self._transaction(operation)

    def active_keys(self, namespace: tuple[str, ...]) -> tuple[str, ...]:
        encoded_namespace = self._namespace(namespace)
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT native_key FROM active_keys
                WHERE namespace = ? AND active = 1 ORDER BY native_key
                """,
                (encoded_namespace,),
            )
            return tuple(row[0] for row in rows)
        finally:
            connection.close()

    def clear_namespace(self, namespace: tuple[str, ...]) -> int:
        encoded_namespace = self._namespace(namespace)

        def operation(connection: sqlite3.Connection) -> int:
            cursor = connection.execute(
                """
                UPDATE active_keys
                SET generation = generation + 1, active = 0, publication_id = NULL
                WHERE namespace = ? AND active = 1
                """,
                (encoded_namespace,),
            )
            return cursor.rowcount

        return self._transaction(operation)

    def clear_all(self) -> int:
        def operation(connection: sqlite3.Connection) -> int:
            cursor = connection.execute(
                """
                UPDATE active_keys
                SET generation = generation + 1, active = 0, publication_id = NULL
                WHERE active = 1
                """
            )
            return cursor.rowcount

        return self._transaction(operation)

    def import_filesystem(
        self, source: FilesystemActiveKeyIndex, *, replace: bool = False
    ) -> int:
        if not isinstance(source, FilesystemActiveKeyIndex):
            raise TypeError("source must be a FilesystemActiveKeyIndex")
        with source._locked():
            entries = source._read()

        def operation(connection: sqlite3.Connection) -> int:
            destination_count = int(
                connection.execute("SELECT count(*) FROM active_keys").fetchone()[0]
            )
            if destination_count and not replace:
                raise ValueError("SQLite active-key index destination is not empty")
            if replace:
                connection.execute("DELETE FROM active_keys")
            for (namespace, key), (generation, active, publication_id) in entries.items():
                self._upsert(
                    connection,
                    self._namespace(namespace),
                    key,
                    generation,
                    active,
                    publication_id,
                )
            return len(entries)

        return self._transaction(operation)

    def integrity_check(self) -> str:
        connection = self._connect()
        try:
            return str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        finally:
            connection.close()


class IndexedRuntimeCacheAdapter(Generic[ValueT]):
    """Reusable mutable KV behavior over an immutable runtime adapter."""

    def __init__(self, adapter: RuntimeCacheAdapter[ValueT], index: ActiveKeyIndex) -> None:
        self.adapter = adapter
        self.index = index
        self._lock = RLock()

    def _core_key(
        self,
        namespace: tuple[str, ...],
        key: str,
        generation: int,
        publication_id: str | None,
    ) -> ExecutionCacheKey:
        _validate_native(namespace, key)
        identity: dict[str, object] = {"native_key": key, "generation": generation}
        if publication_id is not None:
            identity["publication_id"] = publication_id
        opaque_key = digest_bytes(canonical_json(identity))
        return ExecutionCacheKey(namespace, opaque_key)

    def put(self, namespace: tuple[str, ...], key: str, value: ValueT, *, ttl: int | None) -> None:
        encoded = self.adapter.codec.encode(value)
        if ttl is not None and (isinstance(ttl, bool) or not isinstance(ttl, int)):
            raise ValueError("TTL must be an integer number of seconds or null")
        if not self.adapter.bridge.enabled or (ttl is not None and ttl <= 0):
            return
        with self._lock:
            self.index.publish_and_activate(
                namespace,
                key,
                lambda generation, publication_id: self.adapter.bridge.set(
                    {self._core_key(namespace, key, generation, publication_id): (encoded, ttl)}
                ),
            )

    def get(self, namespace: tuple[str, ...], key: str) -> ValueT | None:
        with self._lock:
            revision = self.index.active_revision(namespace, key)
            if revision is None:
                return None
            core_key = self._core_key(namespace, key, *revision)
            values = self.adapter.get((core_key,))
            return values.get(core_key)

    def get_all(self, namespace: tuple[str, ...]) -> dict[str, ValueT]:
        with self._lock:
            values: dict[str, ValueT] = {}
            for key in self.index.active_keys(namespace):
                value = self.get(namespace, key)
                if value is not None:
                    values[key] = value
            return values

    def delete(self, namespace: tuple[str, ...], key: str) -> bool:
        with self._lock:
            return self.index.delete(namespace, key)

    def clear(self, namespace: tuple[str, ...] | None = None) -> int:
        with self._lock:
            if namespace is None:
                return self.index.clear_all()
            return self.index.clear_namespace(namespace)

    async def aput(
        self, namespace: tuple[str, ...], key: str, value: ValueT, *, ttl: int | None
    ) -> None:
        await asyncio.to_thread(self.put, namespace, key, value, ttl=ttl)

    async def aget(self, namespace: tuple[str, ...], key: str) -> ValueT | None:
        return await asyncio.to_thread(self.get, namespace, key)

    async def aget_all(self, namespace: tuple[str, ...]) -> dict[str, ValueT]:
        return await asyncio.to_thread(self.get_all, namespace)

    async def adelete(self, namespace: tuple[str, ...], key: str) -> bool:
        return await asyncio.to_thread(self.delete, namespace, key)

    async def aclear(self, namespace: tuple[str, ...] | None = None) -> int:
        return await asyncio.to_thread(self.clear, namespace)
