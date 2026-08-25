# Adapter catalog and expansion queue

## Implemented

| Runtime | Shape | Status | Evidence |
|---|---|---|---|
| Native Python | exact callable | reference | sync and async real calls |
| LangGraph | exact batch cache | reference | sync and async real graphs |
| LangChain | exact LLM cache | experimental | real fake-LLM invocation |
| LlamaIndex | indexed KV cache | experimental | real ingestion and KV contracts |

`reference` means the interface and safety behavior have broad negative tests.
`experimental` means the adapter passes its current real framework contract but
tracks an upstream interface that may still change.

## Expansion queue

The modular platform is intended to grow. Candidate adapters are grouped by the
kind of translation they are likely to need; every candidate still requires an
upstream API review and specification before implementation.

### Agent and RAG runtimes

- OpenAI Agents SDK
- AutoGen
- CrewAI
- Haystack
- Semantic Kernel
- DSPy
- Agno

### Workflow runtimes

- Prefect
- Dagster
- Temporal activities
- Airflow task results

### TypeScript runtimes

- LangGraph.js
- Vercel AI SDK
- Mastra
- custom Node.js workflows through the portable action protocol

### Interoperability surfaces

- MCP tool-result wrapper
- HTTP middleware for explicitly cacheable read-only tools
- command-line task wrapper
- serverless function wrapper

## Prioritization gate

An adapter moves from the queue when it has:

1. a stable native boundary with exact output-affecting inputs;
2. a safe portable codec or a deliberately private serializer;
3. an owner willing to track upstream releases;
4. a representative workload with measurable avoided work; and
5. no need to weaken OnceMesh partition, trust, freshness, or federation rules.

The queue is intentionally not a support claim. Registry entries are added only
when implementation and real-framework evidence exist.
