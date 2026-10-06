# Backup, restore and upgrade

All paths in these examples are operator inputs. The panel never executes these
commands. Run data operations as the owner of the agent database, normally
solartt-agent, using private directories (0700).

## Backup

```sh
sudo -u solartt-agent mkdir -m 0700 /var/lib/solartt/backups
sudo -u solartt-agent solartt-admin backup /var/lib/solartt/policy.sqlite /var/lib/solartt/backups/snapshot-01.sqlite
```

The SQLite backup API includes committed WAL transactions and verifies integrity.
A snapshot can be made while the agent runs. Destination files must be new;
existing files are never overwritten. Back up the matching encryption key,
configuration, certificate renewal configuration and build provenance separately,
using private storage. The database contains labels and encrypted credentials;
treat the entire snapshot as sensitive.

Live snapshots retain durable byte charges, including not-yet-finalized leases.
After restore their unknown portion is conservatively charged. To minimize this
uncertainty for an upgrade backup, stop the agent cleanly first, then snapshot.
A known unused pool is refunded only after all its write permits and transports
have been destroyed. A forced kill cannot provide that proof.

## Restore

Stop the old agent. Restore into a **new** database path:

```sh
sudo -u solartt-agent solartt-admin restore /var/lib/solartt/backups/snapshot-01.sqlite /var/lib/solartt/encryption.key /var/lib/solartt/restored.sqlite
sudo -u solartt-agent solartt-admin check /var/lib/solartt/restored.sqlite /var/lib/solartt/encryption.key UTC
```

Use the snapshot's configured timezone for the check. Restore validates schema,
integrity and credential decryption before publishing the new file. A wrong key,
unsupported schema or existing destination fails. Update the stopped agent's
configuration to the new path, then start it and verify policy revision, users,
export and access. The old database remains available for investigation.

Restoring an older snapshot also restores its older quota balances and access
policies. Traffic since that snapshot cannot be reconstructed from it. Reconcile
those changes before granting access. Backups do not promise recovery of an
arbitrary SQLite corruption or storage device failure.

## Upgrade

1. Record build.json, policy revision, timezone and service account UIDs.
2. Stop the agent and panel; make a clean backup and preserve the data key.
3. Review the changelog and supported schema versions. This alpha supports
   schema 2 and upgrades verified schema-1 data transactionally. Preserve a
   pre-upgrade schema-1 snapshot for rollback; an alpha.1 binary refuses schema 2.
4. Inspect and install the new package. It preserves configuration and data and
   does not start services automatically.
5. Start the agent and panel explicitly. Verify TLS, profile export, quota
   balances and individual session revocation before enabling users.

If validation fails, keep services stopped and restore a compatible snapshot to
a new path. Never run two agents against one database; an exclusive process lock
rejects that configuration. Backups are the exception: a read-only SQLite snapshot
utility may coexist with the running agent.

`check` validates a staging copy and does not migrate its source. `restore` can
upgrade an old snapshot in staging before publishing a new schema-2 database.
Use optional standalone retention settings for custom storage limits. See
[storage, retry retention and migration semantics](storage-and-audit.md).

For a downgrade candidate, `rollback SNAPSHOT CURRENT_DB KEY TIMEZONE NEW_DB`
requires the current agent to be stopped and refuses changed policy/quota data.
It preserves the snapshot schema, rather than migrating the candidate. Preserve
the current database and verify compatibility with the old binary before switching.
See [the isolated pilot and rollback boundary](isolated-pilot.md).
