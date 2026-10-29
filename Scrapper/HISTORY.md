# Model history access

`Scrapper.match_history.read_match_history()` reads PostgreSQL history for one
stable match UUID. It performs no schema creation, queue replay, or collection.
The modeling machine needs Python, pandas, the PostgreSQL driver, and access to
the repository:

```sh
python3 -m pip install pandas -r Scrapper/requirements-postgres.txt
```

Set `MODEL_DATABASE_URL` outside source control to the model reader's PostgreSQL
connection string. The reader never falls back to the scraper's `DATABASE_URL`.
Calls can pass `database_url=` explicitly for controlled environments.

From the repository root, or with the repository on Python's import path:

```python
from Scrapper.match_history import read_match_history

history = read_match_history(
    "11111111-1111-1111-1111-111111111111",  # replace with matches.id
    bookmaker="caliente",
    status="ok",
    start_time="2026-11-01T17:00:00Z",
    end_time="2026-11-01T18:00:00Z",
)
home_win = history.loc[history["field"] == "HT", ["attempted_at", "value"]]
```

The returned pandas DataFrame contains one row per attempt and odds field.
`value` retains PostgreSQL `NUMERIC` as Python `Decimal`; unavailable prices are
`None`. It includes match ID and current name, slot ID and original scheduled
time/kickoff, run ID/start/completion, outcome ID, bookmaker, retry order, actual
attempt time, source time/name/URL, status, error, and missing field names.
Repeated launches, unchanged readings, and every retry remain separate.

Without filters, history also includes one row for each missed slot and each
run that has no outcomes yet. These have status `missed` or `incomplete`, null
outcome ID, bookmaker, odds field, and value. A missed slot has its recorded
`detected_at`; it has no invented run or attempt. Incomplete runs retain their
real run ID and start time. Statuses `ok`, `partial`, `failed`, and `missing_link`
describe actual bookmaker outcomes.

`history_time` is actual attempt time for bookmaker outcomes, actual start time
for incomplete runs, and intended scheduled time for missed slots. Results are
ordered by this time with deterministic identity/field tie breakers. Time
filters use `start_time <= history_time < end_time`; omitted bounds are open.
Naive bounds are interpreted as UTC and returned timestamps are converted to
UTC. Source timestamps never substitute for actual observation times.

Bookmaker names are `caliente`, `pinnacle`, or `playdoit`. Filters are optional
and combined. A bookmaker filter excludes missed/incomplete records because
they have no bookmaker; query gaps without that filter. Valid unknown match IDs
return an empty DataFrame with the same columns. Invalid IDs, filters, or time
ranges raise `ValueError` before connecting.

## Reader role setup

First run discovery and one minute check with the scraper role to initialize
the existing tables. Then run this once as an administrator for a new login,
substituting the real database, schema, and table-creating scraper role:

```sh
psql "$ADMIN_DATABASE_URL" \
  -v reader_role=model_reader \
  -v database_name=sports_betting \
  -v history_schema=public \
  -v scraper_owner=scraper \
  -f Scrapper/sql/create_history_reader.sql
```

In an administrator psql session, set its password interactively with
`\password model_reader`. Configure the modeling machine's credentials outside
the repository. The script grants CONNECT, schema USAGE, and SELECT on the
history tables. Default SELECT privileges cover future tables created by the
specified scraper owner in that schema. They apply to that table-creating role,
not automatically to every role that can use the schema.
See PostgreSQL's [GRANT](https://www.postgresql.org/docs/current/sql-grant.html)
and [default privileges](https://www.postgresql.org/docs/current/sql-alterdefaultprivileges.html).

The new login owns no scraper objects and receives no write grants or role
memberships. Its default transactions are read-only. The Python connection
helper, `connect_history()`, also sets read-only transactions before yielding
the connection. PostgreSQL table privileges deny changes to scraper records
even if the transaction default is overridden. Read-only transaction behavior
is described in [SET TRANSACTION](https://www.postgresql.org/docs/current/sql-set-transaction.html).

The query assumes the scraper tables already exist and reports PostgreSQL
errors if the database is unavailable or uninitialized. It never initializes
them using model credentials. Private VPN connectivity and server network
configuration are handled by ticket #10.
