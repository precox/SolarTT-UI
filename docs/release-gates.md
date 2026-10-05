# v0.1 acceptance gates

- [ ] Official client compatibility: selected CLI and Android versions recorded.
- [x] Revoke A closes every TLS/TCP/UDP session; B's long streams survive.
- [x] Mixed principals cannot share one managed H2 transport.
- [x] Empty users reject VPN access, including `_check`.
- [x] All devices and directions share one quota; partial writes and races cannot multiply it.
- [x] UDP whole-packet admission, drop refund and resource cleanup.
- [x] Credential rotation and expiry stop the intended sessions.
- [x] Quota survives crashes; uncertainty is bounded and documented.
- [x] Calendar periods, manual resets, limit changes and timezone behavior tested.
- [x] Private destinations, metadata, local/own IPs and DNS results denied.
- [x] Panel login, rate limits, CSRF, XSS, secret exports and UDS permissions tested.
- [ ] Database migrations, backup and restore tested.
- [ ] Fresh VM install/upgrade/uninstall preserves unrelated services.
- [x] CA verification, SNI passthrough, cover HTTP and TLS renewal tested.
- [ ] Measured CPU/RSS, TCP throughput, UDP loss and disk sync costs.
- [ ] CI, dependency licenses, checksums and reproducible upstream pin recorded.

Unchecked gates are not implemented or verified guarantees. This file is updated
with concrete test commands and results, not with anticipated outcomes.

Automated results: [verification record](verification.md). Checked transport and
policy gates refer to isolated tests on the runner; they do not claim Android,
ACME or production-node acceptance. Database checks cover schema-1 initialization,
future-schema refusal and verified restore; cross-version migrations remain open.
