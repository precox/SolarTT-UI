# Audited exports and bounded storage — alpha.2

## Profile export

The control API records `profile_export_prepared` before returning a secret-bearing
profile, or `profile_export_denied` when preparation fails. The event contains
timestamp, policy revision, user/profile IDs, request ID and the Unix peer UID.
UID comes from the kernel peer-credential check; JSON cannot supply or override it.
The panel service UID identifies the control caller in this single-admin release;
it is not a per-web-user identity. Imported legacy entries and internal maintenance
can have an unknown caller UID.

Passwords, usernames, deep links, TOML, QR images and authorization headers are not
audit fields. If the audit transaction fails, no profile is returned. Preparation
does not prove network delivery: the caller can disconnect after the durable event.
Retries may prepare another profile and record another event. Local copy/download
of an already exported browser profile is not a new server export.

Exports serialize with policy mutations and credential rotation. The browser still
clears profile/QR data when the dialog closes and uses no external QR service.
Audit events do not advance the policy revision or consume traffic allowance.

## Retention defaults

The agent accepts an optional host-owned `[retention]` section. Example values are
in `examples/agent.toml`; standalone values for host utilities are in
`examples/retention.toml`.

| Data | Default |
| --- | --- |
| Audit | At most 10,000 most recent entries; age cleanup after 90 days |
| Mutation retry receipts | At most 4,096 most recent operations; maximum replay age 7 days |
| Historical quota periods | 256 per user; never deleted by retention |
| SQLite data pages | Maximum 64 MiB |
| WAL admission threshold | 16 MiB |

Count cleanup runs inside each new mutation/export audit transaction. Age cleanup
also runs at startup and every 60 seconds; physical audit expiry can lag that
interval or a storage failure. Receipt replay checks age before accepting a stored
result. Configuration is validated and cannot disable limits with zero values.

Audit/receipt cleanup and the new operation commit together. A failed transaction
does not partially delete receipts or publish policy changes. Audit sequence IDs
do not repeat after deletion. Free SQLite pages are reused; cleanup does not promise
that an existing database file shrinks. No online VACUUM is performed.

### Retry contract

Always use a unique request ID for a new operation. A network retry must keep the
original ID, body and `expected_revision`. Stored receipts support exact replay
within the count/age window; conflicting bodies still fail. After pruning, a
durable revision floor rejects stale unknown retries with `request_expired`.
Other recent revision conflicts also refuse mutation. The browser never silently
refreshes the revision and repeats a failed mutation.

Retention does not reserve every request ID forever. Deliberately reusing a pruned
ID with a fresh current revision is a new operation and is outside the retry
contract. Inspect current policy before issuing another operation after expiry.

### Quota history

Retention never deletes ledger entries. Reusing an old period restores its old
charge, not fresh allowance. When the period cap is reached, selecting an existing
period remains possible; creating a new period fails with `period_limit`. The
operator can increase reviewed host limits. The cap also applies to automatic
rollover; a failed rollover cannot mint a new allowance and is reported as pending.

Historical entries already above a reduced cap are preserved; no additional
period can be created. Migration must have room to materialize the current period
if a legacy database never wrote a ledger entry for it. Review limits before upgrade.

## Storage pressure and failure

New quota leases must commit before forwarding their bytes. If SQLite reports
full storage, an uncommitted lease never becomes available. Mutation/audit failure
does not publish a new policy or profile. Failed counter checkpoints cannot refund
an uncertain durable lease after restart. Already durably charged leases can still
be spent; a disk error is not a promise to recall queued network bytes.

SQLite's page limit prevents new logical data pages beyond the configured size.
WAL auto-checkpoints normally contain journal growth. If the WAL reaches its
threshold, admission attempts a checkpoint; a reader that pins the WAL causes new
writes to fail until released. A single transaction/migration can overshoot this
threshold, so it is not a filesystem quota. Backups, logs and other host services
remain outside these limits. Keep separate host disk monitoring.

The panel shows retained entry counts and the last storage-write failure. This
flag describes the most recent write attempt; a later successful write clears it
and is not a guarantee that every subsequent write will succeed. Maintenance
failures also produce generic operational diagnostics without profile contents.

## Schema 1 → 2

Alpha.2 creates schema 2. It validates the data key, timezone and credential
decryption of active credentials before migrating an existing schema-1 database. Migration, current
ledger initialization and retention changes use one transaction. Failure rolls
the transaction back. Future schemas are refused before schema changes.

Stop services and preserve a clean schema-1 snapshot plus its matching key before
upgrading. An alpha.1 binary cannot open schema 2; rollback requires the old binary
and a compatible pre-upgrade snapshot. Account for traffic/policy changes made
after that snapshot before restoring access. No in-place downgrade is provided.

`solartt-admin check` validates a private staging copy and leaves its source schema
unchanged. `restore` upgrades only its staging copy and publishes a validated
schema-2 database into a new path. For non-default limits, pass a standalone
retention TOML as the optional final argument to `check` or `restore`.

Tests generate real `SQLITE_FULL` using page limits and private fixture tables;
they do not fill the host filesystem. They cover rejected exports/grants,
transactional rollback, conservative restart, pinned readers, retained quota
history, exact/expired retries and schema migration. Actual device I/O failures,
power loss, filesystem exhaustion and distinct-version VM upgrade remain separate
operational acceptance gates.

SQLite references: [transaction error handling](https://www.sqlite.org/lang_transaction.html),
[page limits](https://www.sqlite.org/pragma.html#pragma_max_page_count),
[non-reused audit sequence IDs](https://www.sqlite.org/autoinc.html).
