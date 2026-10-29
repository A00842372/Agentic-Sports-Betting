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
writes `links.csv` or `schedules.csv`. The minute scraper still writes instance
CSV output until run persistence is implemented in #4; those rows now include
`match_id`, `slot_id`, and `scheduled_time`.

For controlled-time checks, `persist_listings(..., now=...)` and
`run_discovery(..., now=...)` accept the discovery time, and
`select_due_work(connection, run_time=...)` and
`generate_instance(run_time=...)` accept the minute-check time. Naive timestamps
are interpreted as UTC; aware timestamps are converted to UTC. Selection does
not backfill earlier minutes. Missed-slot reconciliation belongs to #6.

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
