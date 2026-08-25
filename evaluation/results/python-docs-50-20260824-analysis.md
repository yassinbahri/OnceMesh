# Python documentation 50-page evaluation analysis

## Outcome

The two-pass shadow evaluation completed all 200 operation executions. The
second pass produced 100 admissible candidates, and every candidate matched the
newly executed artifacts exactly. There were no candidate rejections or
mismatches.

## Measured result

| Measure | Overall | HTTP fetch | HTML to Markdown |
|---|---:|---:|---:|
| Evaluations | 200 | 100 | 100 |
| Candidate hits | 100 | 50 | 50 |
| Candidate match rate | 100% | 100% | 100% |
| Mismatches | 0 | 0 | 0 |
| Reusable bytes | 7,638,485 | 5,968,325 | 1,670,160 |
| Net verified time saving | 13.382 s | 6.879 s | 6.504 s |

Lookup and artifact validation consumed 4.558 seconds across all evaluations.
The measured net saving already subtracts lookup time from matching execution
time.

## Interpretation

This validates exact identity, persistent storage, artifact integrity, shadow
comparison, and reporting at a useful corpus size. It does not yet validate
long-term freshness or organization-specific economics: both passes ran in one
evaluation window, the source was public documentation, and fetch cost was zero.

The next evidence experiment should repeat this corpus after source changes or
expiry and should run an organization-owned operation with a measurable API or
compute cost.
