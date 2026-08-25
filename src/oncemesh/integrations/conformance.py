"""Small reusable safety probes for adapter authors and CI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeVar

from ..execution_cache import ExecutionCacheKey
from .base import RuntimeCacheAdapter
from .index import IndexedRuntimeCacheAdapter


ValueT = TypeVar("ValueT")


@dataclass(frozen=True)
class AdapterConformanceCheck:
    name: str
    passed: bool


@dataclass(frozen=True)
class AdapterConformanceReport:
    profile: str
    checks: tuple[AdapterConformanceCheck, ...]

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)


def probe_exact_adapter(
    adapter: RuntimeCacheAdapter[ValueT],
    *,
    key: ExecutionCacheKey,
    value: ValueT,
    ttl: int | None = 60,
) -> AdapterConformanceReport:
    initial_miss = key not in adapter.get((key,))
    adapter.set({key: (value, ttl)})
    exact_hit = adapter.get((key,)).get(key) == value
    adapter.set_enabled(False)
    disabled_miss = key not in adapter.get((key,))
    adapter.set_enabled(True)
    retained_after_enable = adapter.get((key,)).get(key) == value
    adapter.clear((key.namespace,))
    clear_miss = key not in adapter.get((key,))
    return AdapterConformanceReport(
        "oncemesh.adapter-conformance/exact-v0",
        (
            AdapterConformanceCheck("initial_miss", initial_miss),
            AdapterConformanceCheck("exact_hit", exact_hit),
            AdapterConformanceCheck("disabled_miss", disabled_miss),
            AdapterConformanceCheck("retained_after_enable", retained_after_enable),
            AdapterConformanceCheck("clear_miss", clear_miss),
        ),
    )


def probe_indexed_adapter(
    adapter: IndexedRuntimeCacheAdapter[ValueT],
    *,
    namespace: tuple[str, ...],
    key: str,
    first: ValueT,
    second: ValueT,
    ttl: int | None = 60,
) -> AdapterConformanceReport:
    initial_miss = adapter.get(namespace, key) is None
    adapter.put(namespace, key, first, ttl=ttl)
    first_hit = adapter.get(namespace, key) == first
    adapter.put(namespace, key, second, ttl=ttl)
    overwrite_hit = adapter.get(namespace, key) == second
    enumerated = adapter.get_all(namespace).get(key) == second
    deleted = adapter.delete(namespace, key) and adapter.get(namespace, key) is None
    adapter.put(namespace, key, second, ttl=ttl)
    reput_hit = adapter.get(namespace, key) == second
    adapter.clear(namespace)
    clear_miss = adapter.get(namespace, key) is None
    return AdapterConformanceReport(
        "oncemesh.adapter-conformance/indexed-v0",
        (
            AdapterConformanceCheck("initial_miss", initial_miss),
            AdapterConformanceCheck("first_hit", first_hit),
            AdapterConformanceCheck("overwrite_hit", overwrite_hit),
            AdapterConformanceCheck("enumerated", enumerated),
            AdapterConformanceCheck("deleted", deleted),
            AdapterConformanceCheck("reput_hit", reput_hit),
            AdapterConformanceCheck("clear_miss", clear_miss),
        ),
    )
