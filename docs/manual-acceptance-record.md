# Manual acceptance record — blank template

Status: NOT_PERFORMED. Do not mark PASS based only on CI or kit creation.

| Input | Recorded value |
| --- | --- |
| PR / behavior requiring human review | |
| Candidate version / source commit / package SHA256 | |
| Baseline version / source commit / package SHA256 | |
| Exact CI run / alpha.1 and alpha.5 reports / kit SHA256 | |
| Sanitized environment label / OS / architecture | |
| Owner / tester / agreed window / deletion deadline | |
| Official client / Android / OS / browser versions | |
| Test network labels | |
| Private backup/key evidence reference (no secrets) | |

| Check | Expected behavior | Actual result/evidence | PASS / FAIL / DEFER + reason |
| --- | --- | --- | --- |
| Alpha.5 baseline with synthetic A/B and real spend | | | |
| Candidate upgrade: accounts, policies, quotas, profiles retained | | | |
| Changed panel flow on desktop/mobile | | | |
| Changed agent behavior and failure path | | | |
| Client reconnect, DNS and trusted TLS | | | |
| Quota/revoke A while B's established streams survive | | | |
| Reviewed backup/recovery boundary | | | |
| Synthetic credentials revoked / isolated VM and DNS removed | | | |

Owner decision: ACCEPT / REJECT / DEFER, date and reasons:

Known limits and follow-up:

Publication authorization (separate):

Production rollout authorization/window (separate; none implied):

Do not include profiles, addresses, keys, QR secrets, raw diagnostic logs or mail
contents. Link to private evidence by a sanitized internal reference only.
