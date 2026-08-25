# Python documentation conditional revalidation analysis

The warmed 50-page corpus was revalidated twice, producing 100 conditional
requests. Every server response was HTTP 304. Shadow mode then performed 100
full requests, and every candidate matched the full artifacts exactly.

## Result

- Conditional attempts: 100
- HTTP 304 responses: 100
- Exact full-response matches: 100
- Mismatches: 0
- Immutable validation records written: 100
- Candidate bytes validated: 11,936,650
- Conditional-request time: 12.881 seconds
- Full-request execution time: 14.487 seconds
- Net potential HTTP time saving: 2.228 seconds

The correctness signal is strong for this corpus. The latency advantage is
modest because an HTTPS conditional request still incurs network round trips.
The larger prospective value is avoiding response transfer and downstream
parsing, extraction, embedding, or other computation after a 304 response.

The result supports design review for conditional reuse of `http.fetch/1`. It
does not support unconditional URL-cache substitution, and it does not yet show
the behavior of a live 200 response after source content changes.
