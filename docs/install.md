# Installation of development builds

Supported packaging target: **Ubuntu 24.04, Linux x86_64, systemd**. Other
Linux distributions and older glibc versions have not been verified. These
instructions prepare an isolated pilot; never replace an existing VPN endpoint
until the release gates and a separate rollout review are complete.

## Package

Download the CI development artifact, check SHA256SUMS, then inspect the package:

```sh
sha256sum -c SHA256SUMS
dpkg-deb --info solartt-ui_0.1.0~alpha1_amd64.deb
dpkg-deb --contents solartt-ui_0.1.0~alpha1_amd64.deb
sudo dpkg -i solartt-ui_0.1.0~alpha1_amd64.deb
```

The package creates dedicated service accounts and directories. It does not
start services, bind public ports, change HAProxy/Caddy or alter firewall rules.
The checksum file protects against accidental corruption; it is not a signed
release or a guarantee of authenticity.

## Configuration

Copy examples from `/usr/share/doc/solartt-ui/examples/` to `/etc/solartt/`.
Set files to root:solartt-control 0640. Review all addresses and port conflicts.
The endpoint and metrics must bind loopback; expose the endpoint through a
reviewed TLS passthrough proxy. Keep panel HTTPS on a separate admin hostname.
Its reverse proxy must preserve the browser Host header. Do not expose the
Unix socket, metrics or the panel's HTTP port directly to the internet.

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
