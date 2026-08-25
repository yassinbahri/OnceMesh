# Simulated M3 federation acceptance analysis — 2026-08-24

The complete technical M3 acceptance sequence passed inside three isolated Linux
containers: an org-a origin, an org-b receiver, and an untrusted peer. All roles
ran as a non-root UID with read-only root filesystems, dropped Linux capabilities,
private temporary directories, and distinct Docker secret mounts. The internal
bridge network exposed no origin port to the host.

The origin packaged one explicitly reviewed public result inside its sandbox and
served it over TLS using an ephemeral private test CA. The configured receiver
verified the certificate and all three trust layers—request identity, signed
availability, and production receipt—then imported the result into a durable
leased cache. Action, result, and 31-byte artifact digests were identical across
the boundary.

An independently keyed but unregistered container was denied before receiving
catalog data. The origin then created a write-once manifest with an empty catalog
and restarted. A new receiver probe reported `not_available`, while the first
import remained present during its unexpired 30-second local lease. At the real
recorded expiry boundary, pruning removed the cache entry, receipt reference, and
unreferenced blob.

The harness scanned all non-secret mounts, command output, and service logs for
four encoded test seeds and the authentication signature header name. It found
zero matches. Docker containers and their private network were removed, and the
ephemeral CA, TLS key, and Ed25519 seeds were deleted from the host temporary
directory. The code image remains reusable and contains no generated secrets.

This is high-fidelity simulated evidence, not organizational evidence. One host
operator retained ultimate control over all containers, secrets, and policy
inputs; TLS used a test CA; and origin replay/rate state was process-local. The
report correctly records `environment_kind: simulated` and
`administrative_independence: false`, so M3 remains open until two real operators
repeat the acceptance sequence.
