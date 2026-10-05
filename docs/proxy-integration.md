# HAProxy integration and half-close containment

Use the reviewed [example](../examples/haproxy.cfg) as input to an operator-owned
configuration change. The package includes it as documentation; installing SolarTT
does not replace, restart or reload HAProxy, Caddy or another VPN service.

## TLS and PROXY boundaries

Route the managed hostname to the agent's loopback TLS listener with **no PROXY
header**. TrustTunnel terminates TLS itself; its transport peer is the local
proxy, so peer IP is not a user identity. Route the existing website hostname(s)
to Caddy separately, using `send-proxy-v2` only if its listener is configured to
parse that protocol before TLS. Keep every backend and metrics listener private.

Caddy's listener wrappers must put `proxy_protocol` before `tls`; allow only the
actual HAProxy peer, typically `127.0.0.1/32`, and reject untrusted PROXY sources.
`trusted_proxies` for HTTP headers is a different setting. PROXY metadata can be
applied before those HTTP matchers, so a broad listener allowlist is unsafe.
See [Caddy's listener-wrapper documentation](https://caddyserver.com/docs/caddyfile/options#proxy_protocol).

The panel requires its own reviewed HTTPS reverse-proxy route and canonical
`public_origin`; do not forward that hostname into the VPN backend. Preserve
existing HTTP/ACME routes and the site's certificate management.

## Half-close timeouts

Keep the long normal VPN inactivity timeouts and set both directives in the
effective defaults used by these routes:

```haproxy
timeout connect 5s
timeout client 24h
timeout server 24h
timeout client-fin 30s
timeout server-fin 30s
```

FIN timeouts apply to inactivity after one direction is shut down; they are
not a 30-second lifetime limit for an ordinary open VPN connection. Without
them, half-closed sessions can inherit long timeouts and consume the shared
frontend connection budget. Agent socket caps do not contain unrelated Caddy
connections in that budget. Raising `maxconn` does not remove this mechanism.
See [HAProxy 2.8 timeout reference](https://docs.haproxy.org/2.8/configuration.html#4.2-timeout%20client-fin).

Validate the complete merged configuration and check effective frontend/backend
overrides before applying it. Graceful reload may retain old workers and their
old sessions/timeouts; recovery from an existing accumulation is an operator
decision with session interruption considered explicitly. This project does not
perform proxy recovery or restore production host bundles.

## Isolated regression

Package CI uses a pinned official Caddy and two private fixture HAProxy processes:

- A control without FIN directives must retain four half-closed TCP sessions.
- With client/server FIN set to **1 second**, two client-initiated and two
  server-initiated half-closes must disappear from the proxy's backend counters.
- An authenticated H2 transport stays alive, including an idle interval longer
  than the shortened FIN clock, and continues returning successful checks.
- The actual Caddy TLS route echoes the original loopback client address carried
  by PROXY v2; an immediate peer outside its allowlist cannot inject that metadata.
- The TrustTunnel route accepts ordinary TLS/H2 and rejects a prefixed PROXY header.

The one-second clock is a bounded regression for timeout behavior, not a fresh
production observation of FIN30s. Holding backends deliberately reproduce the
socket condition; the separate Caddy check verifies the real protocol boundary.
No test determines traffic intent or proves a censorship cause.

`dist/proxy-regression.json` records outcomes. The official test Caddy is not
redistributed or installed as a host service, and it need not match an operator's
custom Caddy build. Check that build separately before deployment.
