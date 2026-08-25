# Two-process TLS federation pilot analysis — 2026-08-24

The federation origin and receiver now run as separate operating-system
processes. The origin loaded one reviewed public publication, authenticated the
configured receiver, and served signed availability and the immutable bundle
over TLS. The receiver used a pinned test CA, applied its independently expressed
trust and size policy, preserved every digest, and wrote a canonical evidence
record to a new file.

Private Ed25519 seeds were injected through separate environment variables. The
strict manifests and resulting evidence contain neither seed, request signature,
nonce, authentication header, nor artifact bytes. Startup fails for a non-public
publication or a public-key identifier mismatch. Receiver configuration rejects
plain HTTP and existing evidence paths. The TLS client rejects an untrusted
certificate.

The origin additionally bounds concurrent request processing, per-peer requests
inside a sliding time window, replay-state entries, response bytes, and request
age. These in-process controls are suitable for a controlled pilot; clustered
deployments require shared state or equivalent enforcement at a hardened edge.

This is the last locally reproducible step toward the M3 gate. It deliberately
uses one machine, one operator, and an ephemeral self-signed test CA. Therefore
it does not count as independently administered evidence. The remaining work is
operational: two owners must supply their own hosts, managed TLS, public keys,
private-key custody, reviewed policies, and sign-off using the included commands
and acceptance checklist.
