# OnceMesh specifications

`action-v0.md` is the first protocol draft. The `v0` label means it can change
in incompatible ways while the safety model is validated. Any such change must
also update the conformance vectors.

Normative terms **MUST**, **MUST NOT**, **SHOULD**, **SHOULD NOT**, and **MAY**
are interpreted as described by RFC 2119 and RFC 8174.

## Design goals

- A cache hit is explainable.
- Incorrect reuse is treated as more costly than recomputation.
- Storage and transport are replaceable.
- Trust, freshness, and identity are separate decisions.
- Private information is never required in a public action description.

## Supporting profiles

- [`derived-result-lineage-v0.md`](derived-result-lineage-v0.md) defines exact
  upstream result lineage, bounded cascading admissibility, and immutable early
  invalidation records.
- [`economic-evidence-v0.md`](economic-evidence-v0.md) defines measured,
  projected, and illustrative savings claims and their required formulas.
- [`public-mesh-directory-v0.md`](public-mesh-directory-v0.md) defines curated,
  non-authoritative public peer discovery and aggregate statistics.
- [`public-mesh-status-v0.md`](public-mesh-status-v0.md) defines bounded,
  independently initiated reachability observations for the Pages directory.
- [`public-reference-operator-v0.md`](public-reference-operator-v0.md) defines
  the bounded deployment and evidence gates for the first OnceMesh-operated
  public federation origin.
