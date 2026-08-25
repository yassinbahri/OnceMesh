# Adapter: PDF to text v1

Operation: `document.pdf-to-text`
Operation version: `1`

## Action identity

The action input contains the exact PDF byte digest, size, and media type. The
executor identity is `oncemesh.pypdf`; its version is the exact installed
`pypdf` version. Output from different parser versions cannot share an action
digest.

Executor configuration contains:

- `profile`: `layout-v1`;
- `max_pages`: positive integer;
- `max_output_bytes`: positive integer.

## Extraction profile

The `layout-v1` profile:

1. rejects encrypted PDFs;
2. rejects documents exceeding `max_pages` before page extraction;
3. extracts each page using pypdf layout mode;
4. converts CRLF and CR to LF;
5. removes trailing horizontal whitespace from every line;
6. removes leading and trailing blank lines from each page;
7. joins pages with LF, form-feed, LF (`\n\f\n`);
8. emits UTF-8 with exactly one trailing LF;
9. rejects output exceeding `max_output_bytes`.

The adapter performs text-layer extraction only. It does not run OCR, infer
reading order beyond the parser profile, reproduce page appearance, or claim
semantic equivalence with another PDF renderer.

## Output artifacts

- `text`: normalized UTF-8, media type `text/plain; charset=utf-8`;
- `metadata`: canonical JSON with page count, parser name, parser version, and
  extraction profile.

## Safety

Callers must bound input bytes before parsing and should run untrusted PDFs in a
resource-constrained worker. v1 page and output limits are correctness guards,
not a complete defense against malicious parser inputs.
