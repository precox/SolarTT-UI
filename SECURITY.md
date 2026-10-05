# Security

SolarTT-UI is pre-release software. No supported stable version exists yet.
Do not report vulnerabilities with credentials or exploitable details in public
issues. Until GitHub private vulnerability reporting is enabled by the owner,
contact the repository owner through an existing private channel.

Trust boundary: the host administrator and root are trusted. The panel does not
execute shell commands, edit firewall rules or access arbitrary files. The agent
control socket and encryption key are restricted OS resources. VPN profile exports
are secrets and must not be logged, cached or sent to external QR services.
