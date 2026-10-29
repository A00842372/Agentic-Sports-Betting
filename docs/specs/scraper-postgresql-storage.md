# PostgreSQL storage for scraper discovery and odds history

## Problem Statement

The scraper currently writes discovered match links, scraping schedules, and timestamped instance snapshots to CSV files on the scraping device. The operator wants all scraping to run on a Lubuntu machine and wants to run models from another machine, including while away from the server's local network. CSV files make cross-device access and historical queries awkward. The current instance output also combines three bookmakers into one wide row and has no persistent match ID or run ID. Repeated readings, unchanged odds, failures, and missed scheduled slots must remain visible because each says something about what was observed or attempted.

## Solution

Run all discovery and scheduled scraping, alongside one PostgreSQL database, on the Lubuntu machine. Discovery saves sporting events, bookmaker listings and links, and scraping schedules there. Scheduled scraping reads its work from PostgreSQL and records each run and each bookmaker scrape attempt, including retries, partial results, failures, and readings whose odds have not changed. Every event has one stable internal match ID across bookmakers and across later rediscovery, including a changed kickoff time or display name. Uncertain event matches remain separate and are marked for review.

The modeling machine connects directly to PostgreSQL with read-only credentials through a private VPN, both on the local network and while away. A model-facing query layer retrieves the full history for a match ID. A once-per-minute Linux user timer replaces the Windows launcher without changing scraping or discovery cadence; scraping is allowed to pause while no desktop user session is active. The scraper uses a durable local queue if PostgreSQL becomes unavailable after work has been selected, and replays queued records without losing or collapsing attempts. Missed schedule slots are recorded as missed after collection resumes; later odds are never presented as observations from the missed time.

## User Stories

1. As a scraper operator, I want discovery to save events in PostgreSQL, so that both devices use the same event catalog.
2. As a scraper operator, I want discovery to save bookmaker event links in PostgreSQL, so that scheduled scraping does not depend on a local CSV file.
3. As a scraper operator, I want scraping schedules saved in PostgreSQL, so that due work survives process restarts.
4. As an analyst, I want one stable match ID for a sporting event, so that I can query its full history with one identifier.
5. As an analyst, I want listings from Caliente, Pinnacle, and Playdoit linked to the same match ID when they are confidently the same event, so that their odds can be compared.
6. As an analyst, I want a rescheduled or renamed event to keep its match ID, so that its history does not split across records.
7. As an analyst, I want doubtful event matches kept separate and flagged, so that unrelated events are not silently combined.
8. As a reviewer, I want to see the source listings and reason for a doubtful match, so that I can investigate it later.
9. As a scraper operator, I want scheduled work to select events by match ID, so that name or kickoff text changes do not break the join between discovery and scraping.
10. As an analyst, I want each actual bookmaker scrape attempt recorded with its time and status, so that I can distinguish observations from gaps and errors.
11. As an analyst, I want retries recorded separately, so that I can see what happened before a successful or final failed reading.
12. As an analyst, I want successful readings saved even when all odds equal the previous reading, so that I know the bookmaker was checked again.
13. As an analyst, I want partial readings retained with their missing fields identified, so that usable odds are not discarded or mistaken for complete data.
14. As an analyst, I want failures and missing bookmaker links represented explicitly, so that the absence of odds has a reason.
15. As an analyst, I want simultaneous bookmaker attempts associated with a scraper run, so that I can compare what was collected together.
16. As an analyst, I want separate run IDs and actual timestamps when the same scheduled minute is launched twice, so that neither run overwrites the other.
17. As an analyst, I want missed scheduled slots recorded with their intended time, so that I can distinguish missed collection from unchanged odds.
18. As an analyst, I want a late run's actual timestamp preserved, so that it is never misrepresented as the missed slot's odds.
19. As a scraper operator, I want completed data queued locally during a database outage, so that transient database failures do not erase attempts.
20. As a scraper operator, I want queued data replayed without creating duplicate copies of the same attempt, so that recovery preserves accurate history.
21. As an analyst, I want to query observations for one match ID in time order, so that I can inspect the match's odds history.
22. As an analyst, I want to filter a match's history by bookmaker, status, and time, so that I can build model inputs and diagnose missing data.
23. As a model operator, I want a read-only PostgreSQL account for the modeling device, so that the device can analyze data without changing scraper records.
24. As a scraper operator, I want the database hosted on the Lubuntu scraping machine, so that collection and authoritative storage run together.
25. As an analyst, I want all observations, unchanged readings, failures, and missed slots retained, so that later analysis can use the complete collection history.
26. As a scraper operator, I want a Linux user timer to check for due work every minute while I am logged in, so that the existing collection cadence continues after the storage change.
27. As a scraper operator, I want clear setup instructions for database configuration and credentials, so that both devices can be configured without putting secrets in source code.
28. As a scraper operator, I want match discovery's existing cadence preserved, so that moving storage does not change when links and schedules are refreshed.
29. As a scraper operator, I want the current headed Playwright sessions to work in my Lubuntu desktop session, so that the existing bookmaker scraping behavior survives the move.
30. As a scraper operator, I want scraping to pause when no desktop user session is active, so that the server does not need unattended browser execution before login.
31. As an analyst, I want missed scheduled slots identified after the server restarts or the user logs back in, so that a collection gap is distinguishable from a successful reading.
32. As an analyst, I want to reach the database from outside the server's local network through a private VPN, so that I can analyze history while away.
33. As a model operator, I want a read-only history query interface keyed by match ID, so that model inputs no longer depend on local CSV files.
34. As a scraper operator, I want PostgreSQL to remain available independently of the desktop login state, so that stored history can still be queried while scraping is paused.
35. As a scraper operator, I want database backups and a documented restore path, so that long-term collection history can be recovered after server failure.

## Implementation Decisions

- Run all scrapers and one PostgreSQL database on the Lubuntu machine, with related tables rather than a database per bookmaker. PostgreSQL runs as a system service; scraper jobs run in the user's desktop session.
- Replace CSV as the operational storage for match discovery, bookmaker links, schedules, and instance observations. Existing test CSV files need no import.
- Assign an internal match ID to each sporting event. Use it as the join key through discovery, scheduling, scraping, and analysis. Keep source bookmaker identifiers, links, names, and kickoff information as evidence for reconciliation.
- Preserve a match ID across a confident rediscovery even if displayed names or kickoff time change. Do not merge doubtful listings. Store them separately with a review marker and enough source context to investigate.
- Revisit the current event matching rule that accepts a sole kickoff-time candidate without checking team similarity. Its result must not automatically create a confident cross-bookmaker merge.
- Represent matches, bookmaker listings and links, scheduled slots, scraper runs, and individual bookmaker attempts as related records. A run records its actual start time and intended scheduled slot. An attempt records bookmaker, actual attempt time, retry order, status, error when applicable, and odds when available.
- Preserve every actual attempt, including retries and repeated launches for the same scheduled minute. Use stable run and attempt identifiers so queue replay can be idempotent while distinct real attempts remain distinct.
- Retain successful, partial, failed, and missing-link outcomes. Preserve the existing odds fields as queryable values with numeric types where appropriate and explicit nulls for unavailable values; do not make a single opaque CSV-shaped text payload the only source of odds.
- Record missed scheduled slots separately from scrape attempts. Detect slots that passed without a run and mark them missed. Do not generate a synthetic odds observation for a missed slot.
- Keep timestamps in UTC and distinguish scheduled time, run time, individual attempt time, and bookmaker-provided scrape time where available.
- Keep the current discovery and scraping cadence. A later discovery or kickoff change must update future scheduled work without changing historical slots or observations.
- Make PostgreSQL the authoritative store. If it is unavailable when a scrape completes, write the records to a durable local queue and replay them after recovery. Queue replay must preserve original timestamps, statuses, and IDs. If due work cannot be selected during an outage, later reconciliation records the missed slot rather than fabricating a scrape.
- Allow direct read-only SQL access from the modeling machine over a private VPN, including from outside the server's local network. Restrict PostgreSQL listening, host authentication, and firewall access to intended network paths and roles. Do not expose PostgreSQL directly to the public internet. Configure credentials outside source control.
- Provide the model with a read-only query layer that selects history by match ID and can filter by bookmaker, time, and status. Keep model calculations unchanged.
- Use pandas where it helps transform scraper results, but do not require `DataFrame.to_sql()` as the persistence interface. Choose a PostgreSQL write path that supports related records, transactions, and idempotent queue replay.
- Replace the Windows minute-based launcher with a Linux user timer that checks for due work every minute only during an active graphical desktop session. Do not enable user lingering or let an SSH-only login start scraping. Do not replay missed timer invocations as if they ran on time; reconcile passed scheduled slots as missed. Preserve the existing discovery cadence.
- Keep headed Playwright behavior initially and verify that a user-timer launch inherits access to the Lubuntu desktop display and browser profiles. A change to headless operation is not required for this migration.
- Document PostgreSQL setup, private VPN connectivity, per-machine credentials, Linux timer operation, logs, backups, and restore verification.

## Testing Decisions

- Test observable workflow outcomes rather than private helper calls or exact SQL statements. The principal seam is the discovery-to-scheduled-scrape-to-read-only-history-query workflow, using controlled bookmaker responses and an isolated PostgreSQL database.
- Verify that discovery gives three confident bookmaker listings one match ID and that rediscovery with changed names or kickoff preserves it.
- Verify that a doubtful match remains separate and reviewable, including the case where there is only one candidate within the current five-minute window.
- Verify that scheduling and due-work selection use stored match IDs and that missed slots are recorded without fabricated odds.
- Verify that a run records every bookmaker attempt and retry, including unchanged odds, partial results, failures, missing links, and a repeated launch of the same minute.
- Verify that observations remain queryable by match ID, time, bookmaker, and status from a read-only connection.
- Verify that a simulated database outage queues completed attempts and that replay stores each original attempt once without changing its timestamp.
- Verify that discovery and scraping no longer require the three CSV data flows to operate.
- Verify that the Linux user timer checks due work once per minute in a logged-in desktop session, can launch headed browsers, and stops collection when no user session is active. Treat this as a deployment smoke test rather than mocking desktop internals in the workflow test.
- Verify read-only access over the private VPN from the modeling machine and denial of writes, with no public PostgreSQL exposure. Treat this as a deployment connectivity check.
- Verify that a backup can be restored into an isolated database and still serves match history.
- The repository currently has no tracked automated test suite for this pipeline. Existing functions with injectable time are useful prior art for deterministic scheduling tests; the new workflow test is the primary integration seam.

## Out of Scope

- Importing or reconciling existing CSV files; they contain only test runs.
- Exposing PostgreSQL directly to the public internet or building an HTTP API for remote access.
- A user interface for match review. Doubtful cases must be stored with enough context for later manual review.
- An automatic retention or deletion policy; the full history is retained.
- Changing the bookmakers or the model's analytical logic beyond replacing its data access path.
- Running scraping before desktop login or after logout, and changing the existing discovery or scraping cadence.
- Changing the existing headed browser behavior solely to make unattended scraping possible.

## Further Notes

- The current instance output is one wide row per match with bookmaker-prefixed odds and status fields. It does not include a match ID, discovery kickoff, scheduled minute, source links, or run ID.
- The current launcher runs every minute while the Windows user is logged in. A missed minute is presently skipped, and repeated launches in the same minute have no persisted identity. The Lubuntu replacement must preserve the login-dependent behavior.
- The repository has no root domain glossary or ADRs yet; use the established terms in this spec until those documents exist.
