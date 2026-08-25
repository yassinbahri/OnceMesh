# OnceMesh 0.1.0 release-candidate analysis

The M9 implementation and local acceptance gates pass. The package is ready to
be placed under hosted CI and released as an alpha once repository and package
registry authority exist.

## Local evidence

- Both the full and dependency-light runs passed 183 Python tests; the latter
  reported nine expected skips for optional framework packages.
- Branch-aware source coverage is 77%, above the enforced 75% floor; uncovered
  lines and branches remain visible in CI.
- Static analysis and repository hygiene checks pass. The audit scanned 272
  repository files, parsed 81 JSON/JSONL and 8 YAML documents, and resolved 35
  local documentation links.
- A clean environment containing all adapters and development tools resolved 123
  third-party packages with no known vulnerabilities after upgrading pip to the
  fixed `26.2.1` release used by the release procedure.
- The independent Node implementation passed 29 protocol checks.
- Real-framework evaluations passed 9 adapter-platform, 6 runtime-adapter, and
  8 framework-neutral bridge checks.
- The isolated Docker rehearsal passed all 20 checks and destroyed its ephemeral
  test secrets. Its report remains explicitly simulated and non-independent.
- All three organization-pilot schemas validate both their templates and
  runtime-generated report objects.
- The wheel and source distribution pass metadata rendering, version alignment,
  forbidden-content scanning, and clean-install checks. The clean environment
  imported the public version and SQLite backend and invoked all three CLIs.

The final audit found and fixed one previously untested defect: conditional
substitution reporting computed its gate but returned no document. A regression
test now verifies the schema-shaped result and promotion decision.

## What this does not prove

This evidence does not claim a PyPI publication, a hosted CI run, production
economics, or independent federation. Those outcomes need external systems and
operators. The pilot reporter exits unsuccessfully for synthetic or incomplete
evidence, and the Docker report cannot satisfy the independent-operator gate.

## Release decision

The local `0.1.0` alpha release candidate is accepted. M9 code preparation is
complete. The next work is operational: host the repository, configure trusted
publishing, run the real organization measurement window, and arrange the
two-operator federation pilot defined by the existing handoff package.
