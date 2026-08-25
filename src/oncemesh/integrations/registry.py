"""Dependency-free metadata for built-in and third-party adapter discovery."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from importlib.metadata import entry_points
from typing import Any


@dataclass(frozen=True)
class AdapterDescriptor:
    name: str
    purpose: str
    module: str
    class_name: str
    extra: str | None
    maturity: str
    capabilities: tuple[str, ...]

    def __post_init__(self) -> None:
        for label, value in (
            ("name", self.name),
            ("purpose", self.purpose),
            ("module", self.module),
            ("class_name", self.class_name),
            ("maturity", self.maturity),
        ):
            if not isinstance(value, str) or not value:
                raise ValueError(f"adapter {label} must be a non-empty string")
        if self.extra is not None and (not isinstance(self.extra, str) or not self.extra):
            raise ValueError("adapter extra must be null or a non-empty string")
        if not self.capabilities or len(set(self.capabilities)) != len(self.capabilities):
            raise ValueError("adapter capabilities must be non-empty and unique")


_BUILTINS = (
    AdapterDescriptor(
        "python",
        "Explicit exact-key caching for custom Python agents and workflows.",
        "oncemesh.integrations.python",
        "OnceMeshPythonCache",
        None,
        "reference",
        ("sync", "async", "ttl", "json"),
    ),
    AdapterDescriptor(
        "langgraph",
        "LangGraph BaseCache integration for node and task results.",
        "oncemesh.integrations.langgraph",
        "OnceMeshLangGraphCache",
        "langgraph",
        "reference",
        ("sync", "async", "batch", "ttl", "clear"),
    ),
    AdapterDescriptor(
        "langchain",
        "LangChain LLM and chat-model BaseCache integration.",
        "oncemesh.integrations.langchain",
        "OnceMeshLangChainCache",
        "langchain",
        "experimental",
        ("sync", "async", "ttl", "clear"),
    ),
    AdapterDescriptor(
        "llamaindex",
        "LlamaIndex BaseKVStore and IngestionCache backend.",
        "oncemesh.integrations.llamaindex",
        "OnceMeshLlamaIndexKVStore",
        "llamaindex",
        "experimental",
        ("sync", "async", "batch", "enumerate", "delete", "clear"),
    ),
)


def builtin_adapters() -> tuple[AdapterDescriptor, ...]:
    return _BUILTINS


def get_adapter(name: str) -> AdapterDescriptor:
    for descriptor in _BUILTINS:
        if descriptor.name == name:
            return descriptor
    raise KeyError(f"unknown OnceMesh adapter: {name}")


def discover_adapters(*, include_plugins: bool = False) -> tuple[AdapterDescriptor, ...]:
    """Return built-ins and, on explicit request, installed third-party descriptors."""
    descriptors = list(_BUILTINS)
    if include_plugins:
        known = {descriptor.name for descriptor in descriptors}
        for entry_point in entry_points(group="oncemesh.adapters"):
            loaded = entry_point.load()
            descriptor = loaded() if callable(loaded) else loaded
            if not isinstance(descriptor, AdapterDescriptor):
                raise TypeError(
                    f"adapter entry point {entry_point.name!r} did not return AdapterDescriptor"
                )
            if descriptor.name in known:
                raise ValueError(f"duplicate OnceMesh adapter name: {descriptor.name}")
            known.add(descriptor.name)
            descriptors.append(descriptor)
    return tuple(descriptors)


def load_adapter_class(descriptor: AdapterDescriptor | str) -> type[Any]:
    """Import one selected adapter without making registry discovery eager."""
    selected = get_adapter(descriptor) if isinstance(descriptor, str) else descriptor
    module = import_module(selected.module)
    adapter_class = getattr(module, selected.class_name)
    if not isinstance(adapter_class, type):
        raise TypeError(f"registered adapter is not a class: {selected.name}")
    return adapter_class
