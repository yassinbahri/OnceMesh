# Python documentation controlled substitution analysis

## Safety outcome

The policy-controlled pilot performed 100 application-visible substitutions.
Every operation found an integrity-checked candidate, received HTTP 304 from the
authoritative source, wrote a validation record, and returned the cached body.
No full GET was issued by the substitution path.

The separate live rollback check set `ONCEMESH_DISABLE_SUBSTITUTION=1`. Both
operations bypassed lookup and conditional validation and executed full GETs.

## Economic outcome

The substitution run spent:

- 4.629 seconds reading and validating local candidates;
- 15.003 seconds on conditional network requests;
- 19.631 seconds combined;
- 11,936,650 cached bytes returned without response-body transfer.

The preceding shadow run measured 14.487 seconds for the corresponding 100 full
GETs. Under these conditions, conditional substitution was approximately 5.144
seconds slower. It saved bandwidth but did not save latency.

## Decision

The correctness and rollback mechanisms passed, but this workload does not
justify enabling conditional HTTP substitution for latency alone. Keep the
feature policy-gated and disabled by default. The next economic experiment
should target expensive deterministic downstream work such as document parsing,
OCR, structured extraction, or embeddings, where one validated source can avoid
substantially more computation than the validation round trip costs.
