# Discovery storage

Install the PostgreSQL driver in the scraper's Python environment:

```sh
python3 -m pip install -r Scrapper/requirements-postgres.txt
```

Set `DATABASE_URL` outside source control to a PostgreSQL connection string for
the scraper role, then run `python3 match_discovery.py` from `Scrapper/`.
The role needs permission to create the initial tables and index in its schema.
Discovery creates `matches` and `bookmaker_listings` transactionally and stores
all three bookmakers' source evidence, including listings not linked to Caliente.
The existing CSV outputs remain available for the minute scraper until #3.

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
