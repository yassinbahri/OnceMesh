# Runtime adapter SDK v0

Status: implemented reference profile for M5.

## Purpose

Make framework integrations small and consistent by separating three concerns:

1. the execution-cache bridge owns exact identity, partitioning, trust,
   freshness, immutable storage, clearing, and disable behavior;
2. a value codec owns conversion between runtime values and inert typed bytes;
3. a runtime adapter owns translation of native keys, batches, and execution
   calls into the shared SDK.

No adapter may redefine core admissibility policy.

## Value codec contract

A codec declares one stable, non-empty `serializer_id` and implements:

- `encode(value) -> EncodedExecutionValue`; and
- `decode(encoded) -> value`.

The codec identifier MUST equal the serializer identifier bound into its bridge.
A mismatch fails during adapter construction. Codec errors on lookup are cache
misses. Codec errors while publishing are returned to the caller and MUST NOT
publish a result.

## Shared runtime adapter

The SDK exposes sync and async operations for:

- exact single and batch lookup;
- exact single and batch publication with TTL;
- lookup-or-execute; and
- clear and live disable through the underlying bridge.

Lookup-or-execute MUST return an admissible exact hit without invoking the
operation. On a miss it invokes the supplied operation once, publishes only a
successful return value, and returns that value. Exceptions are never cached.

The returned outcome distinguishes a cache hit from execution even when the
runtime value is `null`.

## Native Python JSON profile

The first framework-independent facade uses serializer identifier
`oncemesh.python-json/v1`. It accepts JSON objects, arrays, strings, integers,
finite floating-point values, booleans, and null. Object keys MUST be strings.
Encoding uses sorted keys, compact separators, UTF-8, and rejects NaN and
infinity. Decoding MUST consume exactly one JSON value and reject non-object
top-level payloads only when the caller requests an object-specific profile.

This profile does not automatically derive cache keys from Python arguments.
The caller MUST supply an exact key that includes every input and configuration
field capable of changing the output. A convenience wrapper may accept a key
function, but MUST NOT fall back to `repr`, pickle, object identity, or a
semantic similarity key.

## Framework adapters

LangGraph uses a codec backed by its configured cache serializer and delegates
batch get/set behavior to the shared SDK. Native Python uses the JSON codec and
shared lookup-or-execute behavior. Future adapters follow the same pattern.

Frameworks requiring mutable enumeration or per-key deletion need a separately
specified active-key index. They MUST NOT infer enumeration from immutable CAS
objects or silently make namespace clearing broader than the host contract.

## Acceptance criteria

1. Native Python sync and async operations each execute once over two exact
   calls and preserve falsey or null cached values.
2. Failed operations and failed encodes do not publish.
3. Serializer mismatches fail at construction.
4. LangGraph continues passing real sync and async graph tests after delegation
   to the shared SDK.
5. Adapter tests cover disable, TTL, clear, partition isolation, and malformed
   encoded values through common behavior.
6. Existing protocol, Node, and Docker suites remain green.
