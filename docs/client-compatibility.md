# Client compatibility checks

The endpoint and official client have separate version pins:
`upstream/pin.json` and `upstream/client-pin.json`. The compatibility fixture uses
CLI 1.1.7 in unprivileged SOCKS mode with certificate verification enabled. It
connects through an HAProxy SNI frontend to the installed SolarTT agent and makes
one small HTTPS request to example.com. Only the fixture address and trust root
are substituted into the endpoint fields exported by SolarTT. DNS resolution for
that request is performed by curl on the runner. Native H2 tests separately
exercise both TCP and UDP payload forwarding.

The CLI archive is downloaded only for CI and is not redistributed in SolarTT
packages. Its release SHA-256 is checked before extraction. This records archive
identity; it is not a claim of a signed SolarTT release.

## Android acceptance on a separately approved pilot

### Manual server setup

The panel's **Connection profile** dialog starts with **Manual setup · Android**.
In the Android app, choose **Servers → Add server** and enter the matching fields.
Each Copy button copies one decoded value, without TOML quotes or escape syntax:

| Android field | Panel value / action |
| --- | --- |
| Server name | Device name (a local display label) |
| Address | Exported endpoint address, including port |
| Domain name from server certificate | Exported certificate hostname |
| Custom SNI | Exported SNI |
| Username / Password | Separate credential fields; password starts hidden |
| Protocol | HTTP/2 |
| Routing profile | Default profile |
| DNS server addresses | Copy the full field, one address per line |
| Client Random | Leave blank for current SolarTT exports |
| Self-signed certificate | Leave empty; do not import a certificate |
| Allow IPv6 connections via the server | Follow the displayed switch value; current exports disable it |

Tap **Add** in the app. The instructions are derived from the same audited export
as the TOML/link, with certificate verification enabled. Unknown trust or protocol
settings fail closed rather than producing misleading manual instructions.
**Other export formats** contains link/QR and TOML for compatible clients; this
does not imply that a particular Android build supports imports. If clipboard
access is denied, select the field and copy manually. Password visibility is an
explicit action. Closing the dialog clears its secret fields; a copied value
remains in the device clipboard until the device/user clears it.

### Acceptance steps

An existing Android connection to an unmodified TrustTunnel endpoint does not
verify compatibility with the managed SolarTT build. Record the actual app
version, Android version, network/operator, endpoint build and test time.

1. On the separately approved fixture, issue two users, A and B, with separate
   credentials. Add A's server manually using the panel's fields. Use HTTP/2 and
   disable IPv6 for v0.1. Import link/QR only if the tested app supports it.
   The endpoint address, certificate hostname and SNI must match the reviewed
   pilot configuration. Keep certificate verification enabled.
2. Verify normal sites and Telegram and record the external IPv4. Check DNS and
   IPv6 behavior separately; a successful connection indicator alone is
   insufficient. Do not put profiles, passwords or unredacted app logs in issues.
3. Establish long-lived traffic for B on another client. Revoke A's credential:
   A's TCP/UDP forwarding must stop and its TLS session must close. B's stream
   must continue. The Android VPN icon is not a reliable cleanup acknowledgement;
   the app may attempt to reconnect.
4. Issue A a new credential, test rotation, then expiry. Verify old credentials
   fail and the intended transports close without interrupting B.
5. Give A a small shared quota and use two A credentials/devices simultaneously.
   Confirm the combined bidirectional payload consumes one period allowance and
   stops at the limit. Header/transport overhead and hosting-provider counters
   are outside the payload quota definition.
6. Reset A's quota, reconnect, then check calendar scheduling and balances after
   a clean restart and a separate isolated crash-recovery test. Unknown delivery
   may remain conservatively charged as documented in the architecture.

Repeat the relevant connectivity checks on Wi-Fi and mobile networks. Report
observable outcomes and measurement limits; connection failure alone does not
identify a censorship mechanism or prove a TSPU hypothesis. ACME renewal and
proxy coexistence require the reviewed pilot's separate operational checks.
