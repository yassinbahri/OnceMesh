# OnceMesh Community Directory

This directory is the canonical curated catalog of public OnceMesh federation
operators. It begins empty: the project will not invent an endpoint or describe
a local simulation as a public mesh.

A listing helps users discover an operator. It is not an endorsement, trust
grant, availability guarantee, or permission to reuse results. Users must
independently review the operator, verify key fingerprints out of band, and add
any trust configuration locally.

## Submit a mesh

Use the **Public mesh registration** issue form. A maintainer will create or
review the matching profile change. Operators must provide:

- a stable peer ID, public display name, description, and HTTPS website;
- an externally reachable HTTPS federation base endpoint;
- supported protocol identifiers, operations, and regions;
- availability and receipt public identity documents;
- an explicit declaration that the endpoint exports only affirmatively reviewed
  `public` results; and
- an operator contact through the issue without including credentials or private
  keys.

Optional statistics must follow `spec/public-mesh-directory-v0.md`. Operator
statistics remain labeled `operator-reported`; only a future directory-controlled
probe may label statistics `directory-observed` or move an entry to `observed`.

## Review and removal

CI validates structure, semantic invariants, ordering, and duplicate identities.
Maintainers review classification and operator claims but do not certify result
quality. Entries may be marked `suspended` for unsafe behavior, material
misrepresentation, abuse, or repeated unavailability, and `retired` at the
operator's request.

Report vulnerabilities privately under `SECURITY.md`. Never place private keys,
credentials, tenant information, payloads, action digests, or per-request logs in
an issue or directory entry.
