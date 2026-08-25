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
    CoordinationTimeoutError,
    ExecutionCacheBridge,
    FilesystemActiveKeyIndex,
    FilesystemEpochRegistry,
    FilesystemStore,
    IndexedRuntimeCacheAdapter,
    ProcessFileLock,
    RuntimeCacheAdapter,
    derive_authorization_partition,
)
from oncemesh.integrations.codecs import JsonValueCodec  # noqa: E402


NAMESPACE = ("extreme", "shared")
PARTITION = derive_authorization_partition("stress-tenant", ["stress:cache"], b"s" * 32)


def make_adapter(root: str, index_path: str) -> IndexedRuntimeCacheAdapter[dict]:
    store = FilesystemStore(root, "stress-store")
    bridge = ExecutionCacheBridge(
        runtime="stress-kv",
        serializer="stress.json/v1",
        authorization_partition=PARTITION,
        stores=[store],
        publish_to=store,
        producer="stress-runtime",
    )
    return IndexedRuntimeCacheAdapter(
        RuntimeCacheAdapter(bridge, JsonValueCodec("stress.json/v1")),
        FilesystemActiveKeyIndex(index_path, lock_timeout=120),
    )


def epoch_worker(path: str, iterations: int) -> None:
    registry = FilesystemEpochRegistry(path, lock_timeout=120)
    for _ in range(iterations):
        registry.rotate_all()
        registry.rotate_namespaces([NAMESPACE])


def overwrite_worker(root: str, index_path: str, worker: int, iterations: int) -> None:
    adapter = make_adapter(root, index_path)
    for sequence in range(iterations):
        adapter.put(
            NAMESPACE,
            "hot-key",
            {"worker": worker, "sequence": sequence, "kind": "overwrite"},
            ttl=None,
        )


def mixed_worker(root: str, index_path: str, worker: int, iterations: int) -> None:
    adapter = make_adapter(root, index_path)
    randomizer = random.Random(0xC0FFEE + worker)
    for sequence in range(iterations):
        key = f"key-{randomizer.randrange(128):03d}"
        choice = randomizer.randrange(100)
        if choice < 20:
            adapter.put(
                NAMESPACE,
                key,
                {"worker": worker, "sequence": sequence, "key": key, "kind": "mixed"},
                ttl=None,
            )
        elif choice < 80:
            value = adapter.get(NAMESPACE, key)
            if value is not None and not isinstance(value, dict):
                raise AssertionError("mixed read returned a non-object")
        elif choice < 95:
            adapter.delete(NAMESPACE, key)
        else:
            adapter.clear(NAMESPACE)


def lock_holder(path: str, ready: multiprocessing.synchronize.Event) -> None:
    with ProcessFileLock(path, timeout=10):
        ready.set()
        time.sleep(1.0)


def crash_writer(root: str, index_path: str) -> None:
    adapter = make_adapter(root, index_path)
    encoded = adapter.adapter.codec.encode({"version": "orphan"})

    def publish_then_die(generation: int, publication_id: str) -> None:
        adapter.adapter.bridge.set(
            {
                adapter._core_key(NAMESPACE, "crash-key", generation, publication_id): (
                    encoded,
                    None,
                )
            }
        )
        os._exit(73)

    adapter.index.publish_and_activate(NAMESPACE, "crash-key", publish_then_die)


def run_processes(context: multiprocessing.context.BaseContext, target: object, arguments: list[tuple]) -> float:
    started = time.perf_counter()
    processes = [context.Process(target=target, args=args) for args in arguments]
    try:
        for process in processes:
            process.start()
        deadline = time.monotonic() + 360
        for process in processes:
            process.join(max(0.0, deadline - time.monotonic()))
        alive = [process for process in processes if process.is_alive()]
        if alive:
            raise AssertionError(f"{len(alive)} workers exceeded 360 seconds: {target}")
        failures = [process.exitcode for process in processes if process.exitcode != 0]
        if failures:
            raise AssertionError(f"workers exited unsuccessfully {failures}: {target}")
    finally:
        for process in processes:
            if process.is_alive():
                process.kill()
        for process in processes:
            process.join()
    return time.perf_counter() - started


def record(checks: list[dict], name: str, started: float, **details: object) -> None:
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
    total_operations = 0

    with tempfile.TemporaryDirectory(prefix="oncemesh-extreme-") as directory:
        workspace = Path(directory)

        epoch_path = workspace / "epochs.json"
        started = time.perf_counter()
        epoch_processes, epoch_iterations = 8, 100
        elapsed = run_processes(
            context,
            epoch_worker,
            [(str(epoch_path), epoch_iterations)] * epoch_processes,
        )
        expected_epochs = epoch_processes * epoch_iterations
        actual_epochs = FilesystemEpochRegistry(epoch_path).epochs(NAMESPACE)
        if actual_epochs != (expected_epochs, expected_epochs):
            raise AssertionError(f"lost epoch update: {actual_epochs}")
        total_operations += expected_epochs * 2
        record(checks, "exact_cross_process_epoch_rotations", started, processes=epoch_processes, operations=expected_epochs * 2, epochs=list(actual_epochs), worker_seconds=round(elapsed, 3))

        same_root = workspace / "same-store"
        same_index_path = workspace / "same-index.json"
        started = time.perf_counter()
        overwrite_processes, overwrite_iterations = 8, 125
        elapsed = run_processes(
            context,
            overwrite_worker,
            [
                (str(same_root), str(same_index_path), worker, overwrite_iterations)
                for worker in range(overwrite_processes)
            ],
        )
        overwrite_count = overwrite_processes * overwrite_iterations
        same_index = FilesystemActiveKeyIndex(same_index_path)
        same_adapter = make_adapter(str(same_root), str(same_index_path))
        final_hot = same_adapter.get(NAMESPACE, "hot-key")
        if same_index.generation(NAMESPACE, "hot-key") != overwrite_count - 1:
            raise AssertionError("same-key generation lost an overwrite")
        if not isinstance(final_hot, dict) or final_hot.get("kind") != "overwrite":
            raise AssertionError("same-key final value is invalid")
        total_operations += overwrite_count
        record(checks, "same_key_transaction_contention", started, processes=overwrite_processes, operations=overwrite_count, generation=overwrite_count - 1, worker_seconds=round(elapsed, 3))

        mixed_root = workspace / "mixed-store"
        mixed_index_path = workspace / "mixed-index.json"
        started = time.perf_counter()
        mixed_processes, mixed_iterations = 12, 750
        elapsed = run_processes(
            context,
            mixed_worker,
            [
                (str(mixed_root), str(mixed_index_path), worker, mixed_iterations)
                for worker in range(mixed_processes)
            ],
        )
        mixed_count = mixed_processes * mixed_iterations
        reopened = make_adapter(str(mixed_root), str(mixed_index_path))
        active_values = reopened.get_all(NAMESPACE)
        if any(not isinstance(value, dict) or value.get("key") != key for key, value in active_values.items()):
            raise AssertionError("reopened active values failed integrity checks")
        json_files = list(mixed_root.rglob("*.json")) + [mixed_index_path, epoch_path, same_index_path]
        for path in json_files:
            json.loads(path.read_text(encoding="utf-8"))
        temporary_files = [
            path for path in workspace.rglob("*")
            if path.is_file() and (path.name.startswith(".oncemesh-") or path.name.startswith(".oncemesh-index-") or path.name.startswith(".oncemesh-epochs-"))
        ]
        if temporary_files:
            raise AssertionError(f"temporary files survived: {temporary_files[:3]}")
        total_operations += mixed_count
        record(checks, "mixed_overwrite_read_delete_clear", started, processes=mixed_processes, operations=mixed_count, active_keys=len(active_values), parsed_json_files=len(json_files), worker_seconds=round(elapsed, 3))

        crash_root = workspace / "crash-store"
        crash_index_path = workspace / "crash-index.json"
        crash_adapter = make_adapter(str(crash_root), str(crash_index_path))
        crash_adapter.put(NAMESPACE, "crash-key", {"version": "committed"}, ttl=None)
        old_revision = crash_adapter.index.active_revision(NAMESPACE, "crash-key")
        started = time.perf_counter()
        process = context.Process(target=crash_writer, args=(str(crash_root), str(crash_index_path)))
        process.start()
        process.join(60)
        if process.exitcode != 73:
            raise AssertionError(f"crash writer exit was {process.exitcode}")
        reopened = make_adapter(str(crash_root), str(crash_index_path))
        if reopened.index.active_revision(NAMESPACE, "crash-key") != old_revision:
            raise AssertionError("crashed transaction changed the committed revision")
        if reopened.get(NAMESPACE, "crash-key") != {"version": "committed"}:
            raise AssertionError("crashed transaction hid the last committed value")
        reopened.put(NAMESPACE, "crash-key", {"version": "after-crash"}, ttl=None)
        if reopened.get(NAMESPACE, "crash-key") != {"version": "after-crash"}:
            raise AssertionError("orphan publication became visible after retry")
        record(checks, "forced_exit_between_publish_and_commit", started, exit_code=73, orphan_unreachable=True, post_crash_write=True)

        lock_path = workspace / "held.lock"
        ready = context.Event()
        holder = context.Process(target=lock_holder, args=(str(lock_path), ready))
        holder.start()
        if not ready.wait(10):
            raise AssertionError("lock holder did not start")
        started = time.perf_counter()
        try:
            with ProcessFileLock(lock_path, timeout=0.15):
                raise AssertionError("contended lock unexpectedly acquired")
        except CoordinationTimeoutError:
            pass
        holder.join(10)
        if holder.exitcode != 0:
            raise AssertionError("lock holder failed")
        with ProcessFileLock(lock_path, timeout=1):
            pass
        record(checks, "bounded_lock_timeout_and_recovery", started, timeout_observed=True, reacquired=True)

    report = {
        "schema": "oncemesh.adapter-stress-report/v0",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "profile": "extreme",
        "platform": sys.platform,
        "python": sys.version.split()[0],
        "passed": all(check["passed"] for check in checks),
        "total_operations": total_operations,
        "checks": checks,
    }
    output = args.output or ROOT / "evaluation" / "results" / "adapter-stress-20260824.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
