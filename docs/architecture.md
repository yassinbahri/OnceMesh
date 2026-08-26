# Architecture and trust model

OnceMesh sits beside an agent or workflow runtime. It does not guess that two
requests are similar. An adapter constructs an exact action document containing
the operation, all output-affecting inputs, executor version and configuration,
output schema, and declared variation dimensions. Canonical JSON gives that
document one content digest.

## Exact reuse path

```mermaid
flowchart LR
    A[Agent or workflow call] --> B[Thin runtime adapter]
    B --> C[Exact action document]
    C --> D[Canonical action digest]
    D --> E[Lookup in permitted tiers]
    E --> F{Candidate found?}
    F -- No --> K[Execute original operation]
    F -- Yes --> G[Verify partition, policy, freshness, receipt and artifacts]
    G --> H{Admissible?}
    H -- No, with reason --> K
    H -- Yes --> I[Return exact stored artifacts]
    K --> J[Return newly computed result]
    K --> L[Optional immutable publication]
```

The important boundary is the admissibility decision. Finding bytes by digest
is insufficient: authorization partition, allowed storage tier, producer trust,
freshness, receipt requirements, key status, and artifact integrity are checked
before substitution. A failed check returns a reason and falls back to ordinary
execution.

## Derived-result admissibility

```mermaid
flowchart LR
    S[Mutable source] --> A[Exact result A]
    A -->|result digest + artifact digest| B[Derived result B]
    V[Trusted validation] --> A
    X[Trusted invalidation] --> A
    Q[Lookup B] --> C{B and every upstream result admissible?}
    B --> C
    A --> C
    C -- Yes --> H[Reuse B]
    C -- No --> M[Miss and execute]
```

Result v1 commits to exact upstream result-manifest digests. Lookup recursively
checks those results under the same freshness, producer-trust, invalidation, and
artifact-integrity policy. Traversal is bounded and local. It never deletes an
immutable object and federation v0 never fetches dependencies transitively.

## Shared core and modular adapters

```mermaid
flowchart TB
    subgraph Frameworks[Framework-facing integrations]
        P[Native Python]
        LG[LangGraph]
        LC[LangChain]
        LI[LlamaIndex]
        X[Contributor adapter]
    end

    subgraph Core[One reusable OnceMesh core]
        SDK[Adapter SDK and codecs]
        ID[Identity and canonicalization]
        POL[Policy and authorization]
        REC[Receipts and validation]
        BR[Execution-cache bridge]
    end

    subgraph Backends[Replaceable storage and indexing]
        MEM[Memory]
        JSON[Filesystem JSON reference]
        SQL[SQLite / WAL]
        ORG[Organization store]
        FED[Explicit federation peer]
    end

    P --> SDK
    LG --> SDK
    LC --> SDK
    LI --> SDK
    X --> SDK
    SDK --> ID
    SDK --> POL
    SDK --> REC
    SDK --> BR
    BR --> MEM
    BR --> JSON
    BR --> SQL
    POL --> ORG
    POL --> FED
```

Framework integrations translate native calls and values; they do not re-create
identity, policy, storage, transaction, or trust logic. New adapters implement
the documented SDK contract and can reuse the same conformance probes.

## Federation trust boundary

```mermaid
sequenceDiagram
    participant R as Receiver operator
    participant C as OnceMesh receiver
    participant O as Configured origin
    participant S as Receiver cache

    R->>C: Configure peer, public keys and limits
    C->>O: HTTPS request with signed peer identity, timestamp and nonce
    O->>O: Check requester, replay window, rate and response limits
    O-->>C: Signed public availability or exact bundle
    C->>C: Verify signature, trust, freshness, digest and public classification
    alt every check passes
        C->>S: Import immutable bundle with bounded lease
    else any check fails
        C-->>R: Deny with an auditable reason
    end
```

Federation is explicit, public-only, non-transitive, and fail-closed. A valid
signature authenticates a claim; it does not prove semantic correctness. The
receiver retains its own policy authority.

The public directory is outside this trust path. It helps a user locate and
compare operators, but it never inserts a peer, imports a key, probes an
endpoint, or changes receiver policy.

The GitHub Pages observatory renders the reviewed registry together with a
separate ephemeral status snapshot produced by scheduled Actions. Browser
clients read only the deployed static files and never contact mesh endpoints.
The monitor has no federation credentials and no write path to the registry.

## Evidence and promotion ladder

```mermaid
flowchart LR
    A[Code release<br/>CI, packages, security, conformance] -->|passed| B[Controlled organization pilot<br/>real workload and rollback drills]
    B -->|requires measured evidence| C[Independent federation pilot<br/>separate operators and key custody]
    C -->|requires operational proof| D[Production decision]
```

The first gate is passed for `0.1.0`. Tooling exists for the next two gates, but
local Docker and synthetic organization data cannot satisfy them.

## Further reading

- [`action-v0.md`](../spec/action-v0.md) defines exact action identity.
- [`derived-result-lineage-v0.md`](../spec/derived-result-lineage-v0.md) defines
  cascading admissibility and immutable invalidation.
- [`execution-cache-bridge-v0.md`](../spec/execution-cache-bridge-v0.md) defines
  the framework-neutral bridge.
- [`runtime-adapter-sdk-v0.md`](../spec/runtime-adapter-sdk-v0.md) defines the
  contributor contract.
- [`federation-http-transport-v0.md`](../spec/federation-http-transport-v0.md)
  defines authenticated transport and bounds.
- [`performance-and-economics.md`](performance-and-economics.md) explains the
  measured performance and economic model.
