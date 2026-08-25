# Execution cache bridge v0

Status: implemented reference profile for M4.

## Purpose

Provide one framework-neutral bridge between agent or workflow runtimes and the
OnceMesh exact-action cache. Framework integrations are thin translations into
this contract; they do not define independent identity, trust, or freshness
rules.

LangGraph is the first compatibility adapter and acceptance workload. It is not
the boundary of the feature. Later adapters may cover LlamaIndex, Haystack,
custom Python or TypeScript runners, and workflow engines without changing the
core bridge.

## Core contract

An execution cache key contains:

- `runtime`: a stable runtime family name;
- `namespace`: an ordered array of non-empty strings;
- `key`: the runtime's exact cache key;
- `serializer`: a stable identifier for the value codec; and
- `authorization_partition`: an opaque
  `oncemesh.authorization-partition/v1` token.

The bridge exposes batch `get`, `set`, and `clear` operations. A set operation
also supplies typed serialized bytes and a TTL in seconds or `null`. Adapters
own conversion between native runtime values and typed bytes.

## Exact action identity

Each execution key maps to an `oncemesh.action/v0` action with:

- operation `framework.execution-cache`, version `1`;
- runtime, namespace, and exact runtime key as inputs;
- executor `oncemesh.execution-cache-bridge`, version `0`;
- serializer identifier and clear epochs in executor config;
- output schema `oncemesh.execution-cache-value/v1`; and
- the opaque authorization partition in `vary`.

Different runtimes, namespace ordering, keys, serializers, partitions, or clear
epochs MUST produce different action digests. Raw tenant, user, thread, and
project identifiers MUST NOT be placed in the action.

## Value envelope and trust boundary

The core stores a length-delimited binary envelope containing a UTF-8 type tag
and payload bytes as one immutable
`application/vnd.oncemesh.execution-cache-value-v1` artifact. The envelope MUST
be validated before an adapter receives the bytes.

OnceMesh verifies action identity, producer trust, expiry, artifact size, and
artifact digest before returning an envelope. The bridge only reads explicitly
configured local or organization stores. Generic framework cache values MUST
NOT be imported from or exported to public federation.

The core never deserializes runtime values. Serializer safety and compatibility
are adapter and application policy.

## Freshness and clearing

- A positive TTL becomes the result manifest's `fresh_until` timestamp.
- A null TTL publishes without expiry and is permitted only inside this private
  bridge profile.
- Zero or negative TTL entries are not published.
- Expired entries are misses and their payloads are not returned.

OnceMesh objects remain immutable. Clearing rotates identity epochs:

- clearing all keys rotates the bridge-wide epoch;
- clearing named namespaces rotates each exact namespace epoch.

Old objects become unreachable but remain available for later garbage
collection. Filesystem epochs are written atomically under the cross-process
local-filesystem lock defined by `cross-process-transactions-v0.md`.

## Adapter requirements

An adapter MUST:

1. preserve runtime namespace ordering and exact keys;
2. declare a stable runtime and serializer identifier;
3. serialize only on set and deserialize only after a verified hit;
4. contain corrupt, expired, untrusted, missing, or undecodable entries as
   misses on get;
5. implement both sync and async forms when its host runtime requires them; and
6. expose a disable control that returns misses and ignores writes without
   deleting stored objects.

## LangGraph adapter profile

The first adapter implements LangGraph `BaseCache` over full keys of
`((namespace_segment, ...), key)` and preserves each framework-provided TTL.
It stores the configured LangGraph serializer's `(type_tag, bytes)` pair in the
core envelope. It performs no peer discovery or network lookup.

## Acceptance criteria

1. Core tests prove exact identity, TTL, clear, disable, corruption handling,
   and cross-partition isolation without importing any agent framework.
2. A real LangGraph graph executes a deterministic node once and reuses its
   exact result on the second invocation.
3. LangGraph sync and async cache methods behave equivalently.
4. No raw partition identity or serialized payload appears in action manifests.
5. Adding another adapter requires translation code, not a new cache policy or
   storage implementation.
6. Existing Python, Node, and Docker evidence suites remain green.
