# OnceMesh 0.1.0 hosted release validation

The final hardened public commit `8b5698c` passed the complete GitHub Actions CI
matrix and CodeQL analysis. Local and remote commit identities matched and the
working tree was clean at verification.

The 11 CI jobs covered Python 3.11–3.13 on Ubuntu and Windows, real adapters on
both operating systems, distribution building and clean installation, static
and dependency-security checks, and the Docker federation acceptance rehearsal.
They completed in 113 seconds of wall time because the jobs ran concurrently.
The longest individual job was the Windows real-adapter run at 108 seconds.

CodeQL completed in 63 seconds. Five findings closed after hardening file modes,
TLS minimums, evidence output, and diagnostic handling. One data-flow finding
was reviewed and documented as a false positive: the federation CLI emits
validated public documents and fixed-schema secret-free reports required by the
operator workflow. The Docker acceptance harness independently scans output and
artifacts for its exact ephemeral secrets. No code-scanning alert remained open
after review.

This closes the earlier release-candidate report's hosted-CI gate. It does not
close the real-organization or independent-federation evidence gates.
