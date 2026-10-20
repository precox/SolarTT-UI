# Managed H2 listener timeout

An operator's long-flow control received EOF about 600 seconds after opening
its TCP/UDP CONNECT streams, although those streams were still carrying data.
The listener timeout applies to waiting for a **new request**. DATA on existing
streams does not satisfy that wait. Managed tunnel shutdown then aborts its
request tasks, so the idle-listener timer was also terminating active pipes.

The development fix reaps completed managed request tasks on listener timeout.
If an existing request task remains, it continues listening; otherwise the empty
transport expires. TCP and UDP pipes retain their own idle timeouts. The outer
managed cancellation path still aborts and joins tasks on quota, expiry or revoke.
Unmanaged behavior, configuration defaults and public protocol fields are unchanged.

## Reproduction and acceptance

Native builds run only on disposable GitHub-hosted runners:

```sh
python3 scripts/prepare_upstream.py
python3 scripts/check_managed_listener_timeout.py
cargo test --locked -p solartt-agent --test transport -- --test-threads=1
```

The new fixture reduces the listener timeout to one second. Limited and unlimited
A/B accounts keep their original TLS sessions and TCP/UDP streams across multiple
listener deadlines without auxiliary health requests, reconnects or new CONNECTs.
Revoking A must close A and preserve B's original streams. Separate cases require
empty transports and transports with only completed health requests to expire.

The before/after script removes only the fix, requires the compiled regression
to fail, restores the exact source in a `finally` block and requires it to pass.
`dist/listener-timeout-regression.json` records source hashes and the accelerated
scope. A passing report is CI evidence, not a production deployment or a claim
about network availability.

The manual phone test's first control segment ended at the timeout. Its helper
then revoked both temporary accounts, invalidating that recovery attempt. The
helper was corrected; an explicitly separate segment used periodic `_check`
requests to finish the phone tests. That workaround is not the server fix and
does not establish continuity between the two segments. Production rollout of
this change remains a separate operator action after CI and review.
