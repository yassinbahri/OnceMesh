# Public reference operator deployment

This directory packages the provider-neutral deployment profile defined by
[`public-reference-operator-v0`](../../spec/public-reference-operator-v0.md).
It is intentionally a single hardened origin, not a complete cloud platform.
DNS, managed TLS, secret custody, backups, alerts, firewalling, patching, and an
independent receiver remain operator responsibilities.

The service distributes only reviewed immutable public publications to
explicitly enrolled, signed requester identities. It does not execute prompts,
models, tools, uploads, or arbitrary network requests.

## Capacity and storage

The origin is a signed static-result distributor, not an inference server. A
2026-08-25 Windows Docker pilot with one tiny canary used about 31 MiB of memory,
0.02% idle CPU, a 57 MB image, and 15 KB of runtime/publication files. Treat
these as a measured development baseline rather than a capacity guarantee.

One vCPU and 1 GB RAM is enough for a low-traffic canary; 2 vCPU and 2 GB RAM
gives more useful operating-system, TLS, Docker, and monitoring headroom. The
reference Compose profile caps the origin at one CPU and 512 MiB and deliberately
runs one replica because replay and rate-limit state is process-local.

Storage and egress, rather than compute, scale with the catalog. Publication
artifacts are base64url-embedded in reviewed JSON packages, so the serving copy
is approximately `1.34 × unique artifact bytes`, plus small manifests and
receipts. Retaining the producer's original source adds roughly another `1 ×`.
The image, bounded container logs, certificates, configuration, and backup must
also fit. As planning examples:

| Unique public artifacts | Serving packages | With retained source | Practical disk floor |
| ---: | ---: | ---: | ---: |
| 100 MB | about 134 MB | about 234 MB | 5 GB |
| 1 GB | about 1.34 GB | about 2.34 GB | 10 GB |
| 10 GB | about 13.4 GB | about 23.4 GB | 40 GB |

Each response is still bounded by `max_response_bytes` (50 MB in the template),
so a larger catalog consists of many bounded results. Measure network transfer
and disk growth under the intended requester count before raising concurrency,
rate, or response limits.

## Keep a useful test catalog available

Keep one stable, synthetic, redistributable canary action permanently documented
so every new receiver can request the exact same action and compare expected
digests. Refresh its signed result before `fresh_until`, but do not silently
change the action, executor identity, or expected content.

Run publication as a separate scheduled producer job, never inside the public
origin:

1. select only synthetic, public-domain, or clearly redistributable inputs;
2. run deterministic, version-pinned adapters in an isolated producer;
3. scan outputs and metadata for personal, secret, licensed, or tenant data;
4. obtain affirmative human publication review;
5. package signed immutable publications into a new staging directory;
6. run preflight and an authenticated receiver probe against staging;
7. atomically promote the reviewed manifest/publication set and restart the
   single origin; and
8. retain a bounded rollback set and remove withdrawn packages after the
   documented retention window.

A daily producer check and a weekly or pre-expiry canary refresh is sufficient
for an initial mesh. Prefer a small, dependable catalog over an unbounded live
feed. The public origin has no upload or administration API by design, so new
data becomes visible only after reviewed files are promoted and the origin is
restarted.

## Host layout

Create two directories outside the repository and outside the Docker build
context:

```text
operator-public/
├── origin.json
├── identities/
│   ├── availability.identity.json
│   └── receipt.identity.json
├── publications/
│   └── reviewed-publication.json
└── tls/
    └── fullchain.pem

operator-secrets/
├── availability.seed
└── tls-private-key.pem
```

`operator-public` is mounted read-only at `/operator`. The two secret files are
mounted individually through Docker secrets. The receipt private seed is not
needed by the serving process and MUST remain in the producer's separate secret
custody.

## Prepare the operator

1. Provision a patched Linux host with a stable DNS name. Keep TCP 8443 closed
   while preparing it.
2. Install Docker Engine with the Compose plugin. Configure host firewalling,
   log retention, time synchronization, backup, and alerts.
3. Generate new availability and receipt identities with
   `oncemesh-federation keygen`. Do not reuse repository test identities.
4. Produce a deterministic public result with `publish_signed_result`, using
   the receipt seed in the producer environment, then package it with
   `oncemesh-federation package-publication` after legal and content review.
5. Enroll at least one independently operated receiver request identity and
   verify its fingerprint out of band.
6. Copy `origin.json.template` to `operator-public/origin.json`, replace every
   placeholder, and point publications at files below `/operator/publications`.
7. Place the managed certificate chain in `operator-public/tls/fullchain.pem`
   and its private key in `operator-secrets/tls-private-key.pem`.

Before starting a network listener, load the availability seed into the named
environment variable and run the existing network-free preflight against the
same manifest. Preflight MUST pass without changing a limit or trust decision.

## Render before starting

Set absolute host paths. The default bind address is loopback so an incomplete
deployment cannot become public accidentally:

```powershell
$env:ONCEMESH_PUBLIC_ROOT = "C:\oncemesh\operator-public"
$env:ONCEMESH_SECRET_ROOT = "C:\oncemesh\operator-secrets"
docker compose -f deploy/public-operator/compose.yaml config
```

On the Linux host, use its environment or supervisor to set the same variables.
Pin `ONCEMESH_PYTHON_IMAGE` or `ONCEMESH_IMAGE` to a reviewed immutable digest
for a real deployment.

## Start a local or staging listener

Build and start while still bound to loopback:

```powershell
docker compose -f deploy/public-operator/compose.yaml up --build -d
```

Verify an unauthenticated request returns `401` without catalog data. Then run a
fully authenticated receiver probe and compare every digest. Only after local
preflight and the hardened-container checks pass should a staging operator set
`ONCEMESH_BIND_ADDRESS=0.0.0.0` and open the firewall for the intended port.

The GitHub Pages monitor checks `/v0/availability` every 30 minutes and treats
the expected `401` as reachable. It does not authenticate or validate results.

## Stop, withdraw, and revoke

- Stop distribution immediately with `docker compose ... down`.
- Revoke a requester by writing a new manifest without that requester and
  restarting the origin.
- Withdraw a result with `oncemesh-federation withdraw-publication`, deploy the
  new write-once manifest, and restart.
- Rotate an exposed availability or receipt key, verify the new fingerprint out
  of band, and update receiver and directory metadata explicitly.
- Mark the public directory entry `suspended` during unresolved security or
  integrity incidents.

An origin cannot remotely delete bytes already imported by a receiver. Receiver
retention and lease expiry remain receiver policy.

## Promotion checklist

Do not register the endpoint until gates G0 and G1 in the operator specification
pass. Do not call it independently proven until a separate receiver completes
G3. After registration, collect at least 20 directory-controlled observations
before proposing `observed` status, and complete the seven-day G5 canary before
making an ongoing availability claim.
