# Adapter: HTML to Markdown v1

Operation: `document.html-to-markdown`
Operation version: `1`

The input is a content descriptor for exact HTML bytes. The descriptor digest,
size, and media type are all included in the action.

The M1 reference executor accepts UTF-8 input. Other character encodings must be
converted to UTF-8 by an explicitly versioned preprocessing operation.

The M1 `readable-v1` profile is deliberately small and deterministic. It:

- ignores `script`, `style`, and `noscript` content;
- renders headings, paragraphs, line breaks, lists, emphasis, strong text,
  inline code, and links;
- collapses horizontal whitespace;
- separates blocks with one empty line;
- emits UTF-8 with one trailing newline.

It is an evaluation adapter rather than a general web-content extraction claim.
Changing rendering rules requires a new executor or profile version.
