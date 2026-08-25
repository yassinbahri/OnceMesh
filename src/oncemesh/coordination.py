"""Small cross-platform process coordination primitives."""

from __future__ import annotations

import os
from pathlib import Path
from threading import RLock
import time
from typing import BinaryIO


_THREAD_LOCKS: dict[Path, RLock] = {}
_THREAD_LOCKS_GUARD = RLock()


class CoordinationTimeoutError(TimeoutError):
    """Raised when a process coordination lock cannot be acquired in time."""


def _thread_lock(path: Path) -> RLock:
    with _THREAD_LOCKS_GUARD:
        return _THREAD_LOCKS.setdefault(path, RLock())


class ProcessFileLock:
    """Exclusive advisory lock released automatically if its process exits."""

    def __init__(
        self,
        path: str | Path,
        *,
        timeout: float = 30.0,
        poll_interval: float = 0.01,
    ) -> None:
        if timeout < 0 or poll_interval <= 0:
            raise ValueError("lock timeout must be non-negative and poll interval positive")
        self.path = Path(path).resolve()
        self.timeout = float(timeout)
        self.poll_interval = float(poll_interval)
        self._thread_lock = _thread_lock(self.path)
        self._handle: BinaryIO | None = None
        self._thread_acquired = False

    def __enter__(self) -> ProcessFileLock:
        started = time.monotonic()
        if not self._thread_lock.acquire(timeout=self.timeout):
            raise CoordinationTimeoutError(f"timed out acquiring coordination lock: {self.path}")
        self._thread_acquired = True
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._handle = self.path.open("a+b")
            if os.name == "nt":
                self._handle.seek(0, os.SEEK_END)
                if self._handle.tell() == 0:
                    self._handle.write(b"\0")
                    self._handle.flush()
            while True:
                try:
                    self._try_lock()
                    return self
                except (BlockingIOError, OSError):
                    if time.monotonic() - started >= self.timeout:
                        raise CoordinationTimeoutError(
                            f"timed out acquiring coordination lock: {self.path}"
                        ) from None
                    time.sleep(self.poll_interval)
        except BaseException:
            if self._handle is not None:
                self._handle.close()
                self._handle = None
            self._thread_lock.release()
            self._thread_acquired = False
            raise

    def _try_lock(self) -> None:
        assert self._handle is not None
        self._handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(self._handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        try:
            if self._handle is not None:
                self._handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        finally:
            if self._handle is not None:
                self._handle.close()
                self._handle = None
            if self._thread_acquired:
                self._thread_lock.release()
                self._thread_acquired = False
