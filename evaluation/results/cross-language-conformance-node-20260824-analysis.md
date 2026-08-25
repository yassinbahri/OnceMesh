# Node cross-language conformance analysis — 2026-08-24

The standalone Node.js v22.20.0 runner completed all 21 checks using only Node
built-in modules. It did not import, invoke, or shell out to the Python OnceMesh
implementation.

The runner reproduced canonical UTF-8 JSON and SHA-256 digests for the generic
Unicode vector, four action vectors spanning HTTP, HTML, and PDF operations, and
the source-validation vector. It rejected floating-point values, an unsafe
integer, and lone high and low Unicode surrogates before hashing.

For the receipt vector, Node independently reproduced the signed receipt digest
and raw-public-key identifier, reconstructed the domain-separated signing input,
verified the Ed25519 signature through its native cryptography API, and rejected
the same signature after producer metadata was changed.

Node also independently reproduced the domain-separated HMAC-SHA-256
authorization-partition token from the shared tenant, scope, subject, and key
vector.

The Python test suite invokes this runner as a subprocess when Node is available,
so vector drift or a language-specific behavior difference fails the ordinary
conformance test run.
