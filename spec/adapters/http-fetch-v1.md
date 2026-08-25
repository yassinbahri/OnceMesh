# Adapter: HTTP fetch v1

Operation: `http.fetch`
Operation version: `1`

This adapter models a read-only HTTP GET. It does not model browser execution,
cookies, authentication flows, or requests with side effects.

## Action identity

The action inputs contain:

- normalized absolute URL;
- method, which must be `GET`;
- exact `Accept` header value.

Executor configuration contains `follow_redirects` and `max_bytes`.

The URL profile lowercases the scheme and host, removes the fragment, removes
the default HTTPS port, and uses `/` for an empty path. Query order and escaping
are preserved because changing them can change server behavior. v1 permits
HTTPS only.

Any identity, authorization, locale, region, cookie state, or additional header
that can affect output must be represented by the adapter profile or an opaque
partition in `vary`. Raw secrets and cookies must not appear in the action.

## Output

- `body`: exact response bytes and response media type;
- `metadata`: canonical JSON containing status, final URL, ETag, Last-Modified,
  and Content-Type when available.

Only status 200 is cacheable in v1. The configured byte limit applies to the
received body. The host application remains responsible for DNS, private-network
and egress policy; the reference adapter requires an injected transport so it
cannot bypass that policy accidentally.
