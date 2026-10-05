# v0.1 acceptance gates

- [ ] Official client compatibility: selected CLI and Android versions recorded.
- [ ] Revoke A closes every TLS/TCP/UDP session; B's long streams survive.
- [ ] Mixed principals cannot share one managed H2 transport.
- [ ] Empty users reject VPN access, including `_check`.
- [ ] All devices and directions share one quota; partial writes and races cannot multiply it.
- [ ] UDP whole-packet admission, drop refund and resource cleanup.
- [ ] Credential rotation and expiry stop the intended sessions.
- [ ] Quota survives crashes; uncertainty is bounded and documented.
- [ ] Calendar periods, manual resets, limit changes and timezone behavior tested.
- [ ] Private destinations, metadata, local/own IPs and DNS results denied.
- [ ] Panel login, rate limits, CSRF, XSS, secret exports and UDS permissions tested.
- [ ] Database migrations, backup and restore tested.
- [ ] Fresh VM install/upgrade/uninstall preserves unrelated services.
- [ ] CA verification, SNI passthrough, cover HTTP and TLS renewal tested.
- [ ] Measured CPU/RSS, TCP throughput, UDP loss and disk sync costs.
- [ ] CI, dependency licenses, checksums and reproducible upstream pin recorded.

Unchecked gates are not implemented or verified guarantees. This file is updated
with concrete test commands and results, not with anticipated outcomes.
