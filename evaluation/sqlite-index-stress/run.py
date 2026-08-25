from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import multiprocessing
import os
from pathlib import Path
import random
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from oncemesh import (  # noqa: E402
    ExecutionCacheBridge,
    FilesystemActiveKeyIndex,
    FilesystemStore,
    IndexedRuntimeCacheAdapter,
    RuntimeCacheAdapter,
    SQLiteActiveKeyIndex,
    derive_authorization_partition,
)
from oncemesh.integrations.codecs import JsonValueCodec  # noqa: E402


NAMESPACE = ("sqlite-extreme", "shared")
PARTITION = derive_authorization_partition(
    "sqlite-stress-tenant", ["stress:sqlite"], b"q" * 32
)


def index_for(kind: str, path: str):
    if kind == "sqlite":
        return SQLiteActiveKeyIndex(path, busy_timeout=120)
    if kind == "json":
        return FilesystemActiveKeyIndex(path, lock_timeout=120)
    raise ValueError(f"unknown index kind: {kind}")


def adapter_for(root: str, index_path: str) -> IndexedRuntimeCacheAdapter[dict]:
    store = FilesystemStore(root, "sqlite-stress-store")
    bridge = ExecutionCacheBridge(
        runtime="sqlite-stress-kv",
        serializer="sqlite-stress.json/v1",
        authorization_partition=PARTITION,
        stores=[store],
        publish_to=store,
        producer="sqlite-stress-runtime",
    )
    return IndexedRuntimeCacheAdapter(
        RuntimeCacheAdapter(bridge, JsonValueCodec("sqlite-stress.json/v1")),
        SQLiteActiveKeyIndex(index_path, busy_timeout=120),
    )


def contention_worker(kind: str, path: str, iterations: int) -> None:
    index = index_for(kind, path)
    for _ in range(iterations):
        index.publish_and_activate(NAMESPACE, "hot-key", lambda *_: None)


def mixed_worker(path: str, worker: int, iterations: int) -> None:
    index = SQLiteActiveKeyIndex(path, busy_timeout=120)
    randomizer = random.Random(0x51A17E + worker)
    for _ in range(iterations):
        key = f"key-{randomizer.randrange(256):03d}"
        choice = randomizer.randrange(100)
        if choice < 30:
            index.publish_and_activate(NAMESPACE, key, lambda *_: None)
        elif choice < 80:
            index.active_revision(NAMESPACE, key)
        elif choice < 95:
            index.delete(NAMESPACE, key)
        else:
            index.clear_namespace(NAMESPACE)


def crash_writer(root: str, path: str) -> None:
    adapter = adapter_for(root, path)
    encoded = adapter.adapter.codec.encode({"version": "orphan"})

    def publish_then_exit(generation: int, publication_id: str) -> None:
        adapter.adapter.bridge.set(
            {
                adapter._core_key(NAMESPACE, "crash-key", generation, publication_id): (
                    encoded,
                    None,
                )
            }
        )
        os._exit(73)

    adapter.index.publish_and_activate(NAMESPACE, "crash-key", publish_then_exit)


def held_writer(path: str, entered, release) -> None:
    index = SQLiteActiveKeyIndex(path, busy_timeout=30)

    def hold(*_: object) -> None:
        entered.set()
        if not release.wait(10):
            raise TimeoutError("reader test did not release writer")

    index.publish_and_activate(NAMESPACE, "wal-key", hold)


def run_processes(context, target, arguments: list[tuple], timeout: float = 240) -> float:
    started = time.perf_counter()
    processes = [context.Process(target=target, args=args) for args in arguments]
    try:
        for process in processes:
            process.start()
        deadline = time.monotonic() + timeout
        for process in processes:
            process.join(max(0.0, deadline - time.monotonic()))
        alive = [process for process in processes if process.is_alive()]
        if alive:
            raise AssertionError(f"{len(alive)} workers exceeded {timeout} seconds")
        failures = [process.exitcode for process in processes if process.exitcode != 0]
        if failures:
            raise AssertionError(f"worker exits were {failures}")
    finally:
        for process in processes:
            if process.is_alive():
                process.kill()
        for process in processes:
            process.join()
    return time.perf_counter() - started


def check(checks: list[dict], name: str, started: float, **details: object) -> None:
    checks.append(
        {
            "name": name,
            "passed": True,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            **details,
        }
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    context = multiprocessing.get_context("spawn")
    checks: list[dict] = []

    with tempfile.TemporaryDirectory(prefix="oncemesh-sqlite-extreme-") as directory:
        workspace = Path(directory)
        workers, iterations = 8, 500
        comparison_operations = workers * iterations
        durations: dict[str, float] = {}
        for kind, suffix in (("json", "json"), ("sqlite", "sqlite3")):
            path = workspace / f"comparison.{suffix}"
            started = time.perf_counter()
            durations[kind] = run_processes(
                context,
                contention_worker,
                [(kind, str(path), iterations)] * workers,
            )
            index = index_for(kind, str(path))
            generation = index.generation(NAMESPACE, "hot-key")
            if generation != comparison_operations - 1:
                raise AssertionError(f"{kind} lost a hot-key commit: {generation}")
            check(
                checks,
                f"{kind}_same_key_4000",
                started,
                operations=comparison_operations,
                generation=generation,
                worker_seconds=round(durations[kind], 3),
            )
        speedup = durations["json"] / durations["sqlite"]
        if speedup < 1.25:
            raise AssertionError(f"SQLite speedup was not material: {speedup:.3f}x")
        checks.append(
            {
                "name": "sqlite_materially_outperforms_json",
                "passed": True,
                "speedup": round(speedup, 3),
                "minimum_speedup": 1.25,
            }
        )

        mixed_path = workspace / "mixed.sqlite3"
        started = time.perf_counter()
        mixed_workers, mixed_iterations = 16, 1000
        mixed_seconds = run_processes(
            context,
            mixed_worker,
            [
                (str(mixed_path), worker, mixed_iterations)
                for worker in range(mixed_workers)
            ],
        )
        mixed_index = SQLiteActiveKeyIndex(mixed_path)
        if mixed_index.integrity_check() != "ok":
            raise AssertionError("SQLite integrity check failed after mixed workload")
        active = mixed_index.active_keys(NAMESPACE)
        check(
            checks,
            "sqlite_mixed_16000",
            started,
            operations=mixed_workers * mixed_iterations,
            processes=mixed_workers,
            active_keys=len(active),
            integrity_check="ok",
            worker_seconds=round(mixed_seconds, 3),
        )

        wal_path = workspace / "wal-readers.sqlite3"
        wal_index = SQLiteActiveKeyIndex(wal_path)
        wal_index.publish_and_activate(NAMESPACE, "wal-key", lambda *_: None)
        old_revision = wal_index.active_revision(NAMESPACE, "wal-key")
        entered, release = context.Event(), context.Event()
        writer = context.Process(target=held_writer, args=(str(wal_path), entered, release))
        writer.start()
        if not entered.wait(10):
            raise AssertionError("held WAL writer did not enter publication")
        started = time.perf_counter()
        observed = wal_index.active_revision(NAMESPACE, "wal-key")
        reader_seconds = time.perf_counter() - started
        release.set()
        writer.join(10)
        if writer.exitcode != 0 or observed != old_revision or reader_seconds > 1:
            raise AssertionError("WAL reader did not observe the prior committed revision")
        check(
            checks,
            "wal_reader_during_writer",
            started,
            reader_seconds=round(reader_seconds, 6),
            prior_revision_visible=True,
        )

        crash_root = workspace / "crash-store"
        crash_path = workspace / "crash.sqlite3"
        crash_adapter = adapter_for(str(crash_root), str(crash_path))
        crash_adapter.put(NAMESPACE, "crash-key", {"version": "committed"}, ttl=None)
        old_revision = crash_adapter.index.active_revision(NAMESPACE, "crash-key")
        started = time.perf_counter()
        process = context.Process(target=crash_writer, args=(str(crash_root), str(crash_path)))
        process.start()
        process.join(60)
        if process.exitcode != 73:
            raise AssertionError(f"crash writer exited with {process.exitcode}")
        reopened = adapter_for(str(crash_root), str(crash_path))
        if reopened.index.active_revision(NAMESPACE, "crash-key") != old_revision:
            raise AssertionError("crashed SQLite writer changed the committed revision")
        if reopened.get(NAMESPACE, "crash-key") != {"version": "committed"}:
            raise AssertionError("crashed SQLite writer hid the committed value")
        reopened.put(NAMESPACE, "crash-key", {"version": "after-crash"}, ttl=None)
        if reopened.get(NAMESPACE, "crash-key") != {"version": "after-crash"}:
            raise AssertionError("SQLite orphan became visible after retry")
        if reopened.index.integrity_check() != "ok":
            raise AssertionError("SQLite integrity failed after crash recovery")
        check(
            checks,
            "sqlite_forced_exit_recovery",
            started,
            exit_code=73,
            prior_commit_preserved=True,
            orphan_unreachable=True,
            integrity_check="ok",
        )

    report = {
        "schema": "oncemesh.sqlite-index-stress-report/v0",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "platform": sys.platform,
        "python": sys.version.split()[0],
        "profile": "extreme",
        "passed": all(item["passed"] for item in checks),
        "sqlite_operations": comparison_operations + mixed_workers * mixed_iterations,
        "comparison_operations_per_backend": comparison_operations,
        "checks": checks,
    }
    output = args.output or ROOT / "evaluation" / "results" / "sqlite-index-stress-20260824.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
