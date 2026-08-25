# OnceMesh economic evidence profile v0

Status: draft

## 1. Purpose

This profile defines how OnceMesh performance and cost claims are calculated and
reported. It prevents projected savings from being presented as measured
savings and keeps avoided execution separate from cache lookup, validation,
storage, transfer, and operating cost.

## 2. Evidence classes

Every economic statement **MUST** identify one of these classes:

- **Measured**: derived from recorded execution, lookup, validation, byte, or
  invoiced-cost observations from a named evaluation.
- **Projected from measurements**: applies a stated workload volume or price to
  measured rates or durations. The workload and price assumptions **MUST** be
  shown.
- **Illustrative scenario**: uses hypothetical inputs only. It **MUST NOT** be
  described as an observed OnceMesh saving.

Zero configured cost means “not measured”; it does not prove that an operation
is free.

## 3. Required quantities

For a projection window:

- `N` is the number of requests;
- `e` is the fraction eligible for exact reuse;
- `h` is the exact-hit rate among eligible requests;
- `Ce` is the ordinary execution cost per request;
- `Cr` is the lookup, validation, storage, and transfer cost per reused result;
- `F` is the fixed OnceMesh operating cost for the window;
- `Te` is ordinary execution time per request; and
- `Tr` is lookup and validation time per reused result.

The model is:

```text
exact hits             = N × e × h
baseline cost          = N × Ce
projected cost         = (N - exact hits) × Ce + exact hits × Cr + F
net cost saved         = exact hits × (Ce - Cr) - F
net time saved         = exact hits × (Te - Tr)
execution work avoided = exact hits × Te
```

Negative net savings **MUST** remain visible. Values must not be floored to zero
when reporting economics.

## 4. Claim boundaries

- A candidate hit is not a saving until admissibility and artifact integrity
  pass.
- Shadow-mode time is a verified opportunity, not application-visible latency.
- Dollar savings require operator-supplied prices or invoices.
- LLM token cost may be counted only when the exact request identity includes
  every output-affecting model, parameter, tool, context, and authorization
  input required by the operation contract.
- Semantic similarity, nondeterministic equivalence, and speculative reuse are
  outside this model.
- Capacity savings and latency savings must be reported separately; parallel
  execution means avoided compute time is not necessarily wall-clock time.

## 5. Minimum report

An economic report **MUST** name its evidence class and evaluation or assumption
set. It **MUST** include request volume, eligibility, hit rate, ordinary cost,
reuse cost, fixed cost, ordinary time, reuse time, net cost saved, net time
saved, and known exclusions.
