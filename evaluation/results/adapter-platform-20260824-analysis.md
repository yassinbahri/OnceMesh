# M6 open adapter platform analysis — 2026-08-24

## Outcome

M6 passed. OnceMesh now exposes a modular integration platform rather than a
collection of independent cache implementations. Native Python, LangGraph,
LangChain, and LlamaIndex are registered built-ins, while ordinary `oncemesh`
imports remain free of optional framework imports.

The repeatable platform evaluation passed 8/8 checks. It exercised a real
LangGraph cached node, a real LangChain fake LLM through the global cache API,
and a real LlamaIndex `IngestionCache`, in addition to native Python and both
shared conformance profiles.

## Organization and reuse

- `integrations/base.py` owns typed sync/async runtime behavior.
- `integrations/codecs.py` owns reusable safe JSON handling.
- `integrations/index.py` owns active enumeration, overwrite generations,
  delete, re-add, clear, memory persistence, and atomic filesystem persistence.
- Framework modules translate only native interfaces and never access OnceMesh
  stores or reuse policy directly.
- `integrations/registry.py` exposes four built-ins without importing their
  frameworks and supports opt-in third-party entry points.
- Existing `oncemesh.langgraph`, `oncemesh.python_runtime`, and
  `oncemesh.runtime_adapter` imports remain behavior-free compatibility aliases.

## Adapter safety evidence

Indexed tests prove overwrite, enumerate, delete, re-add, narrow collection
clear, and filesystem reopen behavior. Every overwrite or delete advances a
generation so an older immutable result cannot reappear. Publication and index
activation are separate; failures remain fail-closed.

LangChain serialization admits only plain `Generation` and AI-message
`ChatGeneration` values and uses an explicit deserialization allowlist with
environment-secret loading disabled. LlamaIndex values use the shared safe JSON
codec. Generic framework values remain barred from federation-import stores by
the core bridge.

## Contributor experience

The repository includes a capability table, package map, detailed authoring
guide, runnable minimal adapter template, individual and aggregate dependency
extras, registry metadata, third-party entry-point discovery, and reusable exact
and indexed CI probes. A new adapter should contain native translation rather
than copies of storage or policy functions.

## Regression evidence

- Python 3.12 with all adapter extras: 161 tests passed.
- Python 3.14 with no optional frameworks: 161 tests passed with nine
  framework-only tests skipped, while core discovery remained functional.
- Independent Node.js conformance: 29 checks passed.
- Docker federation rehearsal: all 20 checks passed.

## Limits

The filesystem active-key index coordinates threads inside one Python process;
cross-process locking and transactional coupling to result publication remain
future work. LangChain's serialization API is beta and the adapter pins a
bounded major version plus a deliberately narrow allowlist. More adapters can
now be added without changing the core, but each still requires real-framework
compatibility and maintenance ownership.
