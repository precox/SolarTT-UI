# Install v0.1.0-alpha.3

Supported packaging target: **Ubuntu 24.04, Linux x86_64, systemd**. Other
Linux distributions and older glibc versions have not been verified. These
instructions prepare an isolated pilot; never replace an existing VPN endpoint
until the release gates and a separate rollout review are complete.

See [runtime requirements and sizing](system-requirements.md). A lightly loaded
2-GiB node is a planning target for a small pilot; the earlier 4-GiB VM proposal
provides headroom and is not a panel requirement. Measured minimum requirements
and sustained concurrent-user capacity remain open.

## Package

Use an empty directory and download the matching assets from the
[first alpha release](https://github.com/precox/SolarTT-UI/releases/tag/v0.1.0-alpha.3).
The deb is the supported installation method; the binary tar has identical file
payloads but does not perform service account setup. The source archive is for
reconstruction, not a runtime installer. On a minimal Ubuntu system:

```sh
sudo apt-get update
sudo apt-get install -y ca-certificates curl
curl -fLO https://github.com/precox/SolarTT-UI/releases/download/v0.1.0-alpha.3/SHA256SUMS
curl -fLO https://github.com/precox/SolarTT-UI/releases/download/v0.1.0-alpha.3/solartt-ui_0.1.0~alpha3_amd64.deb
# This verifies the selected download; other manifest entries are intentionally absent.
sha256sum --ignore-missing -c SHA256SUMS
sudo apt-get install ./solartt-ui_0.1.0~alpha3_amd64.deb
```

APT installs the declared runtime libraries; no Rust, compiler, CMake, Node or
Chromium is needed. If all release assets were downloaded, inspect them with:

```sh
sha256sum -c SHA256SUMS
dpkg-deb --info solartt-ui_0.1.0~alpha3_amd64.deb
dpkg-deb --contents solartt-ui_0.1.0~alpha3_amd64.deb
sudo apt-get install ./solartt-ui_0.1.0~alpha3_amd64.deb
```

Some minimized images configure dpkg to discard `/usr/share/doc`, including
package examples and license notices. Preserve SolarTT documentation in that
image policy (or extract it from the verified deb) before the configuration steps.
The minimal-runtime CI fixture explicitly preserves the shipped documentation;
it still has no compiler, Rust, Node or Chromium.

The package creates dedicated service accounts and directories. It does not
start services, bind public ports, change HAProxy/Caddy or alter firewall rules.
The checksum file protects against accidental corruption; it is not a signed
release or a guarantee of authenticity.

## Configuration

Copy the four configuration examples with explicit ownership:

```sh
for solartt_config in agent.toml endpoint.toml hosts.toml panel.toml; do
  sudo install -o root -g solartt-control -m 0640 "/usr/share/doc/solartt-ui/examples/$solartt_config" "/etc/solartt/$solartt_config"
done
```

Review all addresses and port conflicts with `sudo ss -ltnup`. Edit copies with
`sudoedit /etc/solartt/agent.toml /etc/solartt/hosts.toml` before starting anything.
Replace the example hostname/address and panel UID; never use documentation
addresses as working server endpoints.
The endpoint and metrics must bind loopback; expose the endpoint through a
reviewed TLS passthrough proxy. The packaged panel example uses
`listen = "127.0.0.1:18081"` and `public_origin = "http://127.0.0.1:18081"` for
private SSH access. Do not open this port in the firewall or publish an admin
hostname. Keep the Unix socket and metrics private too. An optional HTTPS admin
proxy is a separate operator-reviewed access-control decision, must preserve
Host, and requires a matching `public_origin`.

Use the actual panel UID in `agent.toml`:

```sh
id -u solartt-panel
```

Set `allowed_uids` to that value. This complements the socket's Unix group
permissions; adding a user to the group alone does not grant control access.
Set the profile's hostname to the TLS certificate name, and its address to
public IPv4:443. Add all public/NAT addresses of this node to `denied_addresses`.
Local interface addresses are also denied. Restart the agent after interface
address changes. Private, loopback, metadata and other non-global destinations
are denied by upstream; the cover origin is a trusted configuration exception.

Choose `period_timezone` before creating the database. It is fixed for that
database; changing the configuration later makes startup fail. Use `UTC` or an
IANA name such as `Europe/Moscow`. Monthly resets occur at the next local month
boundary; enabling the schedule does not reset the current balance immediately.

Generate the data key as the agent account:

```sh
sudo -u solartt-agent solartt-admin init-key /var/lib/solartt/encryption.key
```

Back up this key separately. Losing it makes encrypted VPN credentials
unrecoverable. Do not regenerate it when upgrading or restoring.

Create the panel password hash with `solartt-panel --init-admin
/var/lib/solartt-panel/admin.hash`, running as solartt-panel and supplying the
password through stdin. Use a private interactive terminal with echo disabled;
do not put passwords in shell arguments, history or an environment variable.
The password must be 12–1024 bytes. Replacing the hash requires a panel restart,
which also expires its in-memory administrator sessions.

In Bash, authenticate sudo before reading the password, then use a shell-local
variable and pipe (the variable is never exported):

```bash
sudo -v
IFS= read -r -s -p 'Panel password: ' solartt_admin_password
printf '\n'
printf '%s' "$solartt_admin_password" | sudo -n -u solartt-panel solartt-panel --init-admin /var/lib/solartt-panel/admin.hash
unset solartt_admin_password
```

Provision a DNS hostname, a valid certificate and an existing local HTTP cover
origin before enabling the public TLS route. The panel does not issue certificates
or supply a cover web server. `endpoint.toml` defaults to TLS `127.0.0.1:9443`,
cover `127.0.0.1:9080` and metrics `127.0.0.1:1987`; arrange a local HTTP site at
that cover address or choose an existing trusted local origin. A cover page is
ordinary fallback behavior, not evidence of resistance to active classification.

Install the CA certificate chain and private key named in `hosts.toml` into
`/etc/solartt/tls/`, owned root:solartt-agent, modes 0640. The panel cannot access
this directory. Use a valid publicly trusted certificate for actual clients.
Self-signed certificates belong to isolated tests with an explicit trust root.

Only after reviewing configuration and ports:

```sh
sudo systemctl start solartt-agent.service
sudo systemctl start solartt-panel.service
sudo systemctl status solartt-agent.service solartt-panel.service
```

Enable services at boot separately once the pilot checks pass. Empty users
reject VPN authentication; creating the first user is an administrator action.

## Private administrator access

From the administrator's machine, use an existing authorized SSH account:

```sh
ssh -N -L 127.0.0.1:18081:127.0.0.1:18081 YOUR_USER@YOUR_SERVER
```

Open exactly `http://127.0.0.1:18081` in the local browser. In Termius create a
**Local** forwarding rule: local bind `127.0.0.1`, local port `18081`, your SSH
host/account as Intermediate Host, destination `127.0.0.1`, destination port
`18081`. Keep the forwarding connection active. The configured browser Host and
Origin must match the panel's `public_origin`; changing just the local port can
make authentication fail. If the VPN prevents an SSH connection to its own
server, exclude the SSH app/server route in the client or use an already
authorized separate SSH entry point; do not make the panel public as a workaround.

Log in as `admin` with the password initialized above. Creating an administrator
does not issue a VPN account. Create a VPN user, set its profile limit, add a
device and follow [manual Android setup](client-compatibility.md). Each exported
profile is a secret. Never paste profiles into public issues.

## Certificate renewal

After replacing the certificate and key files atomically with correct ownership,
run `systemctl reload solartt-agent`. SIGHUP reloads the fixed TLS configuration
through TrustTunnel's reload API. Invalid material retains the previous working
TLS settings. This does not restart the endpoint or rotate user credentials.
Test the new certificate on a fresh connection and a pre-existing user's stream
before enabling an ACME hook. The HTTP/HTTPS challenge path belongs to the
surrounding proxy configuration and is not managed by the panel.

## Removal

`dpkg -r solartt-ui` stops only SolarTT services and removes package files.
Configuration, data, keys and service accounts are preserved, including on purge.
Delete retained data separately only after verifying backups. Package operations
do not edit unrelated VPN/proxy/SSH services.

## Resource containment

Packaged units cap agent memory at 512 MiB (soft pressure at 384 MiB), 128 tasks
and 4096 file descriptors; panel memory at 192 MiB (pressure at 128 MiB),
64 tasks and 1024 descriptors. Managed forwarding additionally limits inbound
TLS transports, outbound TCP/UDP sockets and UDP flows. These are containment
defaults, not a tested concurrent-user capacity. Reaching a memory cap can restart
the service and interrupt its sessions. Review systemd drop-ins after load tests
when adjusting deployment limits; retain service-local resource containment.

## Shared TLS proxy integration

Review [the proxy integration guide](proxy-integration.md) and packaged
`examples/haproxy.cfg` before integrating with an existing endpoint/site. The
managed VPN route receives plain TLS without PROXY headers; a reviewed Caddy
route may receive PROXY v2 with a restricted listener allowlist. Both effective
FIN timeouts must be explicit. The package never applies this example to a host.
