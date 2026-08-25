# RFC PDF evaluation corpus provenance

The `rfc-pdf-10` workload contains ten published RFC PDF URLs from the RFC Editor.
The documents cover QUIC, HTTP, QPACK, TCP, and `robots.txt`, providing a mix of
document lengths, tables, code-like blocks, and pagination.

The RFC Editor download page states that RFCs are offered in PDF format. Its reuse
guidance states that RFCs are freely available to download, copy, publish, display,
and distribute under the IETF Trust license, while modifications are restricted.
The evaluation stores exact source bytes and derived text only in the local cache;
it does not modify or republish the documents.

Sources:

- https://www.rfc-editor.org/retrieve/
- https://www.rfc-editor.org/how-can-i-use-rfcs/
