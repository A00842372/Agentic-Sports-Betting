# Collection backups and restore verification

Ticket #11 supplies a daily PostgreSQL backup and an isolated restore check.
These are system services on the Lubuntu scraping machine, independent of the
desktop login and the minute scraping timer. Database collection cadence is
unchanged. Deployment and a real restore must be verified on the target machine;
repository checks alone do not establish recoverability.

## Artifact and credentials

`Scrapper/backup_history.py backup` runs a full database
[`pg_dump --format=custom`](https://www.postgresql.org/docs/current/app-pgdump.html).
It includes matches, source listings, schedules, runs, attempts, numeric odds,
missed slots, and future database tables. It does not filter tables. The archive
does not include cluster-wide login definitions, passwords, or the SQLite queue
of results not yet delivered to PostgreSQL. Preserve the queue separately during
host recovery; ticket #7 documents its path and replay behavior.

Each backup is a private directory containing `database.dump` and `manifest.json`
with a SHA-256 checksum, creation time, and optional known-match reference.
The command checks the archive's table of contents, flushes its files, then
publishes the directory by atomic rename. Failed commands leave existing backups
untouched and never publish a partial backup. Process or machine termination can
leave a hidden `.incomplete-*` directory; it is not a completed backup. No
retention or deletion policy is applied. Keep another copy on storage independent
of the Lubuntu host using the operator's existing backup process.

Use PostgreSQL client tools compatible with the source server (`pg_dump`,
`pg_restore`, `createdb`, `dropdb`) and the scraper's Linux virtual environment,
including pandas and `psycopg` from `Scrapper/requirements-postgres.txt`.

Use libpq services in `/etc/agentic-sports-betting/pg_service.conf`, for example:

```ini
[agentic-backup]
host=localhost
port=5432
dbname=sports_betting
user=history_backup
connect_timeout=5
options=-c search_path=public

[agentic-restore-check]
host=localhost
port=5432
dbname=postgres
user=history_restore_check
connect_timeout=5
options=-c search_path=public
```

Substitute actual database and schema names. Both services must use the same
history schema search path. Store passwords in a separate libpq password file,
`/etc/agentic-sports-betting/backup.pgpass`, owned by the OS account
`agentic-backup` with mode `0600`. The restore-check entry must cover generated
`agentic_restore_*` database names (a wildcard database field can be used).
No password belongs in a command argument, checked-in file, or systemd unit.
See PostgreSQL's [service files](https://www.postgresql.org/docs/current/libpq-pgservice.html)
and [password files](https://www.postgresql.org/docs/current/libpq-pgpass.html).

As the database administrator, give the backup login CONNECT, schema USAGE,
SELECT on all application tables and sequences, and matching default privileges
for the role that creates future tables. It needs no write privileges. For a
database using the `public` schema and `scraper` as its object-creating role:

```sql
CREATE ROLE history_backup LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
GRANT CONNECT ON DATABASE sports_betting TO history_backup;
GRANT USAGE ON SCHEMA public TO history_backup;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO history_backup;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO history_backup;
ALTER DEFAULT PRIVILEGES FOR ROLE scraper IN SCHEMA public
    GRANT SELECT ON TABLES TO history_backup;
ALTER DEFAULT PRIVILEGES FOR ROLE scraper IN SCHEMA public
    GRANT SELECT ON SEQUENCES TO history_backup;
CREATE ROLE history_restore_check LOGIN NOSUPERUSER CREATEDB NOCREATEROLE;
GRANT CONNECT ON DATABASE postgres TO history_restore_check;
```

Set both passwords using administrator psql's interactive `\password` command.
If this database contains other schemas, grant backup read access to those too;
a full dump must not silently omit them. The restore-check login creates and owns
temporary verification databases; it needs no access to production history.

## Install and inspect the daily backup

Create or use a dedicated Linux system account named `agentic-backup`. Give it
read/execute access to the deployed repository and Linux virtual environment.
Install the two units from `Scrapper/systemd/` into `/etc/systemd/system/`.
The units use a system service, never user lingering or graphical autostart.

Create `/etc/agentic-sports-betting/backup.env` outside the repository:

```ini
BACKUP_PYTHON=/opt/agentic-sports-betting/Scrapper/.venv/bin/python
BACKUP_REPOSITORY=/opt/agentic-sports-betting
BACKUP_SERVICE=agentic-backup
BACKUP_MATCH_ID=11111111-1111-1111-1111-111111111111
PGSERVICEFILE=/etc/agentic-sports-betting/pg_service.conf
PGPASSFILE=/etc/agentic-sports-betting/backup.pgpass
```

Replace the match ID with a real `matches.id` that already has bookmaker
outcomes. The scheduled backup captures its immutable observations as a restore
oracle. An unknown match or a match without observations fails visibly. For an
initial database with no observations, a manual backup can omit `--match-id`;
it still archives the database but cannot pass the match-history proof.

```sh
sudo install -m 0644 Scrapper/systemd/agentic-history-backup.service /etc/systemd/system/
sudo install -m 0644 Scrapper/systemd/agentic-history-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start agentic-history-backup.service
sudo journalctl -u agentic-history-backup.service --since today
sudo systemctl enable --now agentic-history-backup.timer
sudo systemctl list-timers agentic-history-backup.timer
```

The timer runs daily at 03:15 in the server's local timezone. `Persistent=true`
requests one catch-up backup after downtime; it does not backfill scrape work.
Systemd serializes this service's activations. Artifacts live under
`/var/lib/agentic-history-backups/`, created mode `0700` and owned by
`agentic-backup`. Output and Python/PostgreSQL errors remain in the system journal;
a failed dump, archive check, credential lookup, or file write gives a failed job.

To disable future backups, run
`sudo systemctl disable --now agentic-history-backup.timer`. This does not remove
artifacts or interrupt a backup already running. To uninstall, disable the timer,
wait for the service to finish, remove its two installed unit files, and run
`sudo systemctl daemon-reload`. Preserve the backup directory and credentials.

## Verify a real restore

Run the command as the backup OS account with `PGSERVICEFILE` and `PGPASSFILE`
set as above, using the Linux virtual environment:

```sh
python3 Scrapper/backup_history.py verify \
  /var/lib/agentic-history-backups/history-REPLACE-WITH-ARTIFACT \
  --restore-service agentic-restore-check
```

The verifier checks the checksum before connecting, creates a new database from
`template0` with a generated `agentic_restore_<UUID>` name, and restores with
`pg_restore --exit-on-error --no-owner --no-privileges`. It calls ticket #8's
read-only match-history interface and compares every captured outcome/odds-field
row, including match/slot/run/attempt IDs, intended and actual UTC times, statuses,
errors, missing fields and exact numeric prices. Current display names, provisional
missed markers, and incomplete runs are excluded from the oracle because they
can change during collection. The database archive still contains them.
Observations collected after the oracle was captured are allowed as extra rows.

Only a successful comparison prints `Verified ... history rows`. The command
drops only the database it successfully created, including after a restore or
comparison failure. An existing database is never an accepted target. The
optional `--keep-database` retains the generated database for inspection,
including on failure. A failed cleanup is reported; use the printed database name
to investigate rather than deleting any other database.

On Lubuntu, record the artifact path/checksum, command exit status, matched row
count, printed scratch database name, and journal timestamps. Confirm a backup
actually runs on schedule and after a logged-out period, and run this restore
check before declaring #11 deployment verification complete. These checks have
not been executed merely by installing the repository files.

## Recover after server failure

1. Reinstall compatible PostgreSQL/client tools, recreate the scraper and model
   roles, and restore their external credentials. Database dumps do not recreate
   cluster roles. Keep collection stopped during recovery.
2. Copy a complete backup bundle from independent storage and run the verifier
   above. Resolve a checksum, restore, or history mismatch before cutover.
3. As an administrator, create a new recovery database owned by the scraper role
   using `template0`. Restore `database.dump` into that fresh database with
   `pg_restore --exit-on-error --no-owner --no-privileges --role=scraper`, using
   administrator libpq credentials for the connection. Do not restore over a
   running collection database.
4. Reapply schema USAGE, SELECT grants and default privileges for the existing
   model reader as described in [HISTORY.md](../Scrapper/HISTORY.md). Reapply the
   backup login's grants as well. If the model role already exists, apply grants
   without rerunning `CREATE ROLE`.
5. Query the known match using model credentials, verify the original IDs and
   timestamps, and confirm writes are denied. Point the scraper and model's
   external connection configuration at the recovered database only after these
   checks pass. Preserve any undelivered SQLite queue and replay it against the
   recovered original slots before resuming normal collection.

Backups represent their PostgreSQL snapshot time; observations never backed up
or delivered to that database require the independently preserved local queue.
