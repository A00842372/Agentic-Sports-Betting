# Discovery storage

Install the PostgreSQL driver in the scraper's Python environment:

```sh
python3 -m pip install -r Scrapper/requirements-postgres.txt
```

Set `DATABASE_URL` outside source control to a PostgreSQL connection string for
the scraper role, then run `python3 match_discovery.py` from `Scrapper/`.
The role needs permission to create the initial tables and index in its schema.
Discovery creates `matches`, `bookmaker_listings`, and `scheduled_slots` transactionally and stores
all three bookmakers' source evidence, including listings not linked to Caliente.
It generates future scrape slots using the existing cadence. Rediscovery retains
unchanged slot IDs, cancels superseded future slots, and preserves elapsed slots
with their original intended kickoff and scheduled timestamp. Source evidence
and schedules commit together; a failure rolls back both.

The minute scraper also uses `DATABASE_URL`. Run `python3 generate_instance.py`
from `Scrapper/` after discovery has initialized the database. It selects only
active slots for the current UTC minute and current kickoff, joins current links
by match ID, and leaves missing bookmaker links null. Neither command reads or
writes `links.csv`, `schedules.csv`, or instance CSV files. The minute scraper
returns an in-memory summary and persists its results in PostgreSQL.

On the first minute check, the scraper creates `scraper_runs`, `bookmaker_outcomes`,
and `outcome_odds`. It durably records a distinct run UUID, intended slot ID,
and actual UTC `started_at` before opening bookmaker sessions. Registration
normally commits in PostgreSQL; a local registration payload survives an outage
after work selection. Each bookmaker attempt
has its own UUID, actual `attempted_at`, source timestamp where available,
source name and URL, status (`ok`, `partial`, `failed`, or `missing_link`), and
error details and a one-based `attempt_number` within its run and bookmaker.
Bookmaker initialization failures are recorded as failed attempts;
absent links are recorded without opening a session for those listings.

`outcome_odds` stores the existing 30 odds fields as named rows with PostgreSQL
`NUMERIC` values. Every outcome includes every field, using SQL `NULL` for
unavailable or invalid prices. `bookmaker_outcomes.missing_fields` identifies
these gaps. Usable prices in a partial reading are retained. Invalid source
timestamps produce a null source timestamp and an error detail while preserving
the odds; the actual outcome time is recorded independently.

All attempts from one collection launch and its `completed_at` timestamps commit
together. Completed collections first commit to a local SQLite queue. A
PostgreSQL write failure leaves the previously committed runs incomplete
(`completed_at IS NULL`) until replay delivers their results. A process
interruption before collection completes can also leave an incomplete run.

Every failed retry is retained before a successful or final failed reading,
including transient session startup failures. Startup failures apply only to
listings with links; missing links produce one `missing_link` outcome. Startup
and scrape attempts share one increasing attempt order per run and bookmaker.
The existing retry limit and backoff remain unchanged. The returned in-memory
summary still shows the final outcome for each bookmaker. IDs are assigned
during collection and reused when storing attempts. Repeated launches for the
same slot, including unchanged successful readings, receive distinct run and
attempt IDs; there is no uniqueness constraint on the scheduled slot in
`scraper_runs`.

The first minute check upgrades an existing ticket #4 database transactionally by
adding `attempt_number` and a unique index on `(run_id, bookmaker, attempt_number)`.
Existing outcomes keep their IDs, times, and odds and receive attempt number 1.

The durable queue defaults to
`$XDG_STATE_HOME/agentic-sports-betting/outcomes.sqlite3`, or
`~/.local/state/agentic-sports-betting/outcomes.sqlite3` when `XDG_STATE_HOME` is
unset. Set `SCRAPER_QUEUE_PATH` to choose a persistent local file; controlled
calls can pass `generate_instance(queue_path=...)`. Keep the same path across
invocations. SQLite uses Python's standard library and needs no extra driver.
Queue storage errors propagate so a collection is never reported as safely
queued when its local write failed.

Each completed payload contains the original run and attempt UUIDs, UTC start,
attempt, source and completion times, status, error, links, missing fields, and
all numeric odds. Decimal prices are represented as exact strings in the queue
and restored as PostgreSQL `NUMERIC`; unavailable prices remain null. Queue
files contain no database connection strings. SQLite's
[`synchronous=EXTRA`](https://www.sqlite.org/pragma.html#pragma_synchronous)
setting provides durable local commits.

Each minute invocation replays pending registrations and collections before
checking new due work, even when nothing is due. Selection assigns stable run
IDs and queues their registration before trying to register them in PostgreSQL.
If registration or its commit acknowledgement fails because of a connection
outage, collection continues using these durable local run identities. An
interrupted collection can therefore replay as an incomplete run.
Collection uses the same run IDs and
queues its completed payload before attempting a fresh PostgreSQL connection.
PostgreSQL commits the whole payload before the queue acknowledges delivery.
If the remote commit succeeds but its acknowledgement is lost, the next replay
uses the same IDs and
[`ON CONFLICT`](https://www.postgresql.org/docs/current/sql-insert.html)
to keep one copy of each original record. Completion timestamps do not change
on replay. Distinct launches and retries keep their distinct IDs and records.
Failed delivery retains the payload and following collections for the next
invocation; it logs the failure and queue path. The returned summary's
`attrs["storage_status"]` is `persisted` or `queued`.

If PostgreSQL cannot select due work, the invocation fails before
opening browsers. No observations are invented; reconciliation records passed
slots after the database recovers. Replay requires the original discovery and
schedule records to remain in PostgreSQL.

For example, query home-win prices and gaps with:

```sql
SELECT s.match_id, s.scheduled_time, r.id AS run_id, r.started_at,
       o.bookmaker, o.attempt_number, o.attempted_at, o.source_timestamp,
       o.status, o.error, d.value AS home_win_price
FROM scheduled_slots s
JOIN scraper_runs r ON r.slot_id = s.id
JOIN bookmaker_outcomes o ON o.run_id = r.id
JOIN outcome_odds d ON d.outcome_id = o.id AND d.field = 'HT'
ORDER BY s.match_id, r.started_at, r.id, o.bookmaker, o.attempt_number;
```

For controlled-time checks, `persist_listings(..., now=...)` and
`run_discovery(..., now=...)` accept the discovery time, and
`select_due_work(connection, run_time=...)` and
`generate_instance(run_time=...)` accept the minute-check time. Naive timestamps
are interpreted as UTC; aware timestamps are converted to UTC. Selection does
not backfill earlier minutes.

Every minute check first reconciles missed slots, including when no current work
is due. `missed_slots` stores one record per elapsed, uncancelled slot without a
launched run, with its slot ID and actual UTC `detected_at`. Joining to
`scheduled_slots` preserves the original match ID, intended scheduled time, and
kickoff. Only minutes before the current UTC minute are considered elapsed;
a check at 17:46:30 can still scrape the 17:46 minute. Cancelled slots are
excluded. Slots with any recorded run, including a failed or incomplete run,
are attempted collections rather than missed collections.

After downtime or a desktop logout, the next invocation records the gaps and
scrapes only the currently due minute. It creates no run, bookmaker attempt, or
odds for a missed slot. Current runs retain their actual start and attempt
timestamps. Repeated checks preserve the first detection time and do not
duplicate missed records. Rediscovery does not erase elapsed gaps when kickoff
changes; future slots cancelled by rescheduling do not become missed records.
Reconciliation, due selection, and run registration share one transaction and
lock, so overlapping minute checks cannot mark selected work missed before its
run is registered during normal operation. The transaction commits before
bookmaker IO begins. If a selected run's registration was retained only locally
during an outage, another check can provisionally mark its slot missed. Replay
registers the real run and removes that false missed marker, preserving its
actual start time and observations. Gaps with no real run remain recorded.

Query missed collection alongside its intended time with:

```sql
SELECT s.match_id, s.id AS slot_id, s.scheduled_time, s.kickoff,
       'missed' AS status, m.detected_at
FROM missed_slots m
JOIN scheduled_slots s ON s.id = m.slot_id
ORDER BY s.match_id, s.scheduled_time;
```

`matches.id` is the stable internal UUID. A bookmaker event ID preserves that
identity across source name, URL slug, and kickoff changes. When a source URL has
no event ID, its full URL is the identity evidence; changed URLs that cannot be
confidently reconciled stay separate for review. In particular, same-bookmaker
candidates are never automatically merged on name and time alone.

Query `matches WHERE review_reason IS NOT NULL` and join `bookmaker_listings` on
`match_id` to inspect doubtful names, links, and kickoff evidence. Review reasons
include low name similarity, ambiguous candidates, changed source identity, and
missing kickoff. Rediscovery updates current listing evidence; it does not update
any observation records. No historical CSV import is performed.

Run the automated checks from the repository root:

```sh
python3 -m unittest discover -s Scrapper/tests -v
```

Set `TEST_DATABASE_URL` to an expendable PostgreSQL database to enable persistence
checks. They create and drop a randomly named schema for each test, requiring
schema creation privileges. Without it, persistence tests explicitly skip; a
successful run with skips does not verify PostgreSQL behavior.

`test_scheduled_work.py` covers discovery-to-due selection, current links after
renaming and rescheduling, preserved elapsed slots, unchanged slot identity,
kickoff changes within a minute, and the existing cadence boundaries.

`test_run_storage.py` verifies typed and partial readings, retries that recover,
exhausted retries, and session startup retries locally. With
`TEST_DATABASE_URL`, it also exercises discovery-to-scrape persistence with
controlled bookmaker sessions, no CSV access, actual run/attempt timestamps,
partial/failed/missing-link results, unchanged readings, complete retry history,
the upgrade from ticket #4, and committed run visibility before bookmaker IO.
It also covers missed-slot reconciliation after downtime with no due work,
repeated checks, collection within the current minute, failed and incomplete
runs, and cancellation and historical gaps after a kickoff change.
The outage tests cover replay of partial readings and retries, lost remote
commit acknowledgement without duplicate records or changed timestamps, and
database unavailability before work selection, an outage during run registration,
and correction of a provisional missed marker after replay. Each workflow uses its own
temporary queue file.
`test_outcome_queue.py` exercises real temporary SQLite storage locally,
including process exit after enqueue, reopening, failed delivery, ambiguous
remote commits, and preservation of original metadata and decimal prices.
`generate_instance(session_factories=...)`
accepts factories keyed by `cal`, `pn`, and `pd` for these controlled responses;
the default CLI retains the existing headed browser sessions.
