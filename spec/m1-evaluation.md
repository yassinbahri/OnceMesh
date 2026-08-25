# M1 organization evaluation profile

Status: draft

M1 evaluates whether OnceMesh can find useful, safe reuse opportunities before
allowing it to substitute results in an application.

## Shadow mode

Shadow mode performs an ordinary OnceMesh lookup and then always executes the
original operation. The application's returned value **MUST** come from the
execution, never from the candidate artifact.

When a candidate exists, the evaluator compares exact artifact names, media
types, and bytes. It records whether the candidate would have produced the same
observable result. A mismatch is evidence against the current action or
freshness model and **MUST NOT** be counted as savings.

Shadow mode may publish the newly executed result to the configured local or
organization store when publication is explicitly enabled.

## Required event fields

Each evaluation event contains:

- action digest and operation name;
- mode (`shadow` in M1);
- candidate hit and selected tier;
- candidate rejection reasons;
- whether candidate artifacts exactly matched execution;
- execution duration;
- reusable artifact bytes;
- estimated cost and net time savings, counted only for matching candidates.
  Net time savings subtract measured lookup and artifact-validation time from
  measured execution time.

Events must not contain action inputs, artifact contents, credentials, or
authorization partition values.

## M1 success criteria

An evaluation report must distinguish:

- lookup hit rate;
- verified shadow-match rate;
- candidate mismatch rate;
- rejection counts by reason;
- verified estimated cost and time saved;
- bytes transferred or reused.

Promotion to substitution requires zero unexplained mismatches for each enabled
operation profile during an agreed evaluation window. This is necessary but not
sufficient: authorization, rollback, and operational readiness remain required.
