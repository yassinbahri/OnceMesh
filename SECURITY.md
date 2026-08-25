# Security policy

## Supported versions

Before the first stable release, only the newest `0.x` release receives security
fixes. Protocol compatibility and migration impact will be documented separately
from package compatibility.

## Reporting a vulnerability

Do not open a public issue containing an exploit, credential, private key,
customer payload, or tenant identifier. Use the repository host's private
security-advisory channel. If no private channel is configured, contact the
maintainer through a private channel listed by the repository owner before
sharing details.

Include the affected version, component, reproduction conditions, impact, and
whether credentials or real organization data were involved. Do not test against
systems or peers you do not own or have explicit permission to assess.

## Security boundaries

- A valid signature proves key possession and object binding, not semantic truth.
- Generic runtime cache values are private and cannot use federation stores.
- Federation exports require explicit public classification and local policy.
- Imported objects are not transitively re-exportable.
- Operators remain responsible for key custody, TLS, filesystem permissions,
  retention, monitoring, dependency updates, and incident response.
- Local reference backends are not a substitute for deployment-specific access
  control or secret management.
