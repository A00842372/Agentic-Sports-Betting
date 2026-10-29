# Final Lubuntu validation checklist — all tickets

Published spec: [#14 — Final Lubuntu validation for all PostgreSQL migration tickets](https://github.com/A00842372/Agentic-Sports-Betting/issues/14)
(`ready-for-agent`). Implementation coverage is #1–#13; #14 is the final gate.

## Current execution evidence

See [the 2026-10-29 local execution report](validation/2026-10-29-local.md)
for the implementation at `d0213dd` plus the ticket #14 working-tree additions.
It records local coverage added since the audit, every remaining A/B/C
case, and environmental blockers. The original snapshot below is historical:
backup and history-input test files and the #12/#13 launcher/guide now exist.
The final deployment gate remains incomplete; local command stand-ins are not
database, graphical-session, timer, or VPN evidence.

## Purpose and timing

Finish the implementation tickets first. Then use this inventory and its
companion final-validation spec to verify the complete system on Lubuntu.
This is a final validation gate, not a request to pause implementation or proof
that closed issues have already passed deployment checks.

Include every check that could not be completed here, including existing skipped
tests, tests not yet written, and real desktop, PostgreSQL, network and recovery
checks. A test that has not been written is not an executed test or a unittest
skip. Missing local-only coverage is identified separately from checks requiring
the target environment.

## Audit snapshot

- Audit date: 2026-10-29. Repository baseline: `5c8dde6`.
- Fresh execution: **44 discovered tests: 20 passed, 24 skipped, 0 failures,
  0 errors**. All 24 skips report `TEST_DATABASE_URL is required`.
- PostgreSQL server/client tools, the psycopg driver, and a configured test
  database were unavailable here. Real PostgreSQL tests can run on any suitable
  PostgreSQL host; Lubuntu is specifically needed for the target desktop/systemd
  deployment checks, not for the database assertions themselves.
- The GitHub issue-list response obtained during this audit listed #2–#8 as
  closed and #1, #9–#13 as open. Subsequent API refresh attempts failed. Recheck
  all issue states and acceptance criteria before final execution, including
  tickets added or changed after this snapshot.
- Ticket #11 currently has draft backup commands, units and a runbook in the
  working tree. There are no backup test files. Ticket #8 has no dedicated
  history/permission test file. Do not interpret their absence as passing tests.
- The backup timer calendar parsed successfully. `systemd-analyze verify`
  exited 1 with sandbox socket-permission errors; it is **not a passed check**.
- No Python type checker is configured or installed. Syntax checks are not
  type checking and do not establish database or deployment correctness.

## Every ticket's verification obligations

Issue links use this repository's GitHub issue tracker.

| Ticket | State in audit | What final validation must establish |
| --- | --- | --- |
| [#1 — PostgreSQL storage on Lubuntu](https://github.com/A00842372/Agentic-Sports-Betting/issues/1) | Open parent | Complete discovery → scheduling → collection → history, operational access, login-only scraping, outage recovery and restore proof. |
| [#2 — Persist discovered matches and bookmaker listings](https://github.com/A00842372/Agentic-Sports-Betting/issues/2) | Closed | PostgreSQL source evidence, shared stable IDs, confident rediscovery, doubtful-match separation/review, no operational CSV dependency. |
| [#3 — Store schedules and select due matches by ID](https://github.com/A00842372/Agentic-Sports-Betting/issues/3) | Closed | Current-minute selection and current URLs by stable match ID; unchanged cadence; historical slots preserved after rescheduling. |
| [#4 — Store scraper runs and bookmaker outcomes](https://github.com/A00842372/Agentic-Sports-Betting/issues/4) | Closed | Durable runs before bookmaker IO; typed complete/partial/failed/missing-link outcomes; all odds fields and distinct UTC timestamps. |
| [#5 — Preserve retries and repeated launches](https://github.com/A00842372/Agentic-Sports-Betting/issues/5) | Closed | Every retry and actual launch remains distinct, including unchanged odds; upgrade preserves existing records. |
| [#6 — Record missed scheduled slots](https://github.com/A00842372/Agentic-Sports-Betting/issues/6) | Closed | Genuine unrun slots become missed; no fabricated odds; attempted/incomplete runs are excluded; rollover and rescheduling remain correct. |
| [#7 — Queue and replay results during outages](https://github.com/A00842372/Agentic-Sports-Betting/issues/7) | Closed | PostgreSQL outage and process restart preserve queued registrations/results; replay is transactional and idempotent without collapsing real attempts. |
| [#8 — Provide read-only match history](https://github.com/A00842372/Agentic-Sports-Betting/issues/8) | Closed | History filtering/order/precision/completeness; actual read-only grants; model access without CSV or calculation changes. |
| [#9 — Run the minute check in a Lubuntu desktop session](https://github.com/A00842372/Agentic-Sports-Betting/issues/9) | Open integration gate | Real graphical login, headed browsers, minute ticks, logout/SSH exclusion, missed slots, logs and unchanged discovery cadence. |
| [#10 — Connect through a private VPN](https://github.com/A00842372/Agentic-Sports-Betting/issues/10) | Open | Real modeling-device access from outside the LAN, read-only queries, denied writes, and restricted PostgreSQL network exposure. |
| [#11 — Back up and restore collection history](https://github.com/A00842372/Agentic-Sports-Betting/issues/11) | Current draft | Scheduled full archive, failure-safe publication, isolated restore with original IDs/times, and executable recovery instructions. |
| [#12 — Graphical Lubuntu minute timer](https://github.com/A00842372/Agentic-Sports-Betting/issues/12) | Open implementation | Valid delivered scripts/units, session guard, display import, serialization, no backfilled activations, real login-only operation. |
| [#13 — Lubuntu timer installation and operations](https://github.com/A00842372/Agentic-Sports-Betting/issues/13) | Open documentation | Every guide command works against the delivered launcher; logs, disable/uninstall and all smoke outcomes match #9. |

Closed status is implementation bookkeeping, not evidence that these obligations
were executed. The 24 exact skips below cover only part of this table.

## Environment and execution order

1. Refresh the final code commit, all issues and acceptance criteria after the
   implementation phase. Keep this inventory's baseline for comparison.
2. Prepare a Linux virtual environment and an **expendable PostgreSQL test
   database**, separate from collected production history. The existing tests
   create/drop random schemas and create functions/triggers in those schemas.
   Use a test role allowed to perform those operations.
3. Install the existing suite's dependencies: pandas, requests, and the driver
   in `Scrapper/requirements-postgres.txt`. Real browser checks additionally
   require Playwright/Chromium, Linux-compatible profiles, network access and an
   active local graphical session.
4. Configure `TEST_DATABASE_URL` outside source control. Use separate disposable
   roles/admin access for permission and restore tests. Restore verification
   additionally requires PostgreSQL client tools and permission to create a
   fresh verification database.
5. Run all existing tests with **zero unexpected skips**. Add and run the missing
   coverage specified below, through the existing public interfaces.
6. Run the target systemd/desktop checks. Run controlled restart/outage tests
   only against an expendable PostgreSQL instance, not the collection service.
7. Test private-VPN access from the actual modeling machine, including outside
   the server LAN. Finish with a real backup/restore/recovery rehearsal.
8. Record evidence for every case. A missing environment or unfinished feature
   is `BLOCKED`, not `PASS`. Fix failures and rerun affected cases plus the final
   suite before declaring the validation gate complete.

### Existing suite commands

From the repository root, activate the Linux environment and install dependencies:

```sh
. Scrapper/.venv/bin/activate
python -m pip install pandas requests -r Scrapper/requirements-postgres.txt
```

Set `TEST_DATABASE_URL` to the prepared **test** database, using external
credentials. Run discovery with a guard that treats remaining skips as an
incomplete validation:

```sh
PYTHONDONTWRITEBYTECODE=1 python - <<'PY'
import unittest
suite = unittest.defaultTestLoader.discover('Scrapper/tests')
result = unittest.TextTestRunner(verbosity=2).run(suite)
for case, reason in result.skipped:
    print('UNRESOLVED SKIP:', case.id(), reason)
raise SystemExit(0 if result.wasSuccessful() and not result.skipped else 1)
PY
```

For a focused rerun, replace `TEST_ID` with an exact dotted ID from the table:

```sh
PYTHONPATH=Scrapper:Scrapper/tests PYTHONDONTWRITEBYTECODE=1 \
  python -m unittest -v TEST_ID
```

The controlled schedule times in existing tests are intentional. Keep their
explicit injected UTC times; investigate a real-clock dependency if a future
execution fails instead of blindly changing fixtures to today's date.

## A. Existing tests skipped here — all 24

Every entry is currently `PENDING EXECUTION` on PostgreSQL. The dotted identifiers
are exact discovered test IDs. Checkboxes require a recorded passing run.

| Case | Related ticket | Existing test ID | Required observable outcome |
| --- | --- | --- | --- |
| [ ] A01 | #2 | `test_discovery_storage.DiscoveryStorageTests.test_missing_kickoff_is_preserved_for_review` | Missing kickoff remains stored and flagged for review. |
| [ ] A02 | #2 | `test_discovery_storage.DiscoveryStorageTests.test_rediscovery_updates_evidence_and_keeps_match_id` | Renamed/rescheduled source evidence keeps its match ID. |
| [ ] A03 | #2 | `test_discovery_storage.DiscoveryStorageTests.test_single_time_candidate_with_unrelated_teams_is_reviewable` | A sole nearby kickoff candidate with unrelated teams remains separate and reviewable. |
| [ ] A04 | #2 | `test_discovery_storage.DiscoveryStorageTests.test_three_confident_listings_share_one_persisted_match_id` | Three confident bookmaker listings persist under one stable match ID. |
| [ ] A05 | #4 | `test_run_storage.PersistedRunTests.test_discovery_to_scrape_stores_typed_outcomes_without_csv` | Discovery-to-scrape persistence preserves typed odds, source/actual times and IDs without CSV IO. |
| [ ] A06 | #5 | `test_run_storage.PersistedRunTests.test_existing_outcomes_survive_retry_schema_upgrade` | The retry-schema upgrade preserves existing IDs, statuses and times and assigns legacy attempt order 1. |
| [ ] A07 | #6 | `test_run_storage.PersistedRunTests.test_failed_and_incomplete_runs_are_not_missed_slots` | Failed and incomplete actual runs are distinguished from unrun missed slots. |
| [ ] A08 | #4, #6 | `test_run_storage.PersistedRunTests.test_no_due_work_creates_no_run` | A no-due-work check creates no scraper run. |
| [ ] A09 | #7 | `test_run_storage.PersistedRunTests.test_outage_after_collection_replays_retries_and_partial_results` | Queued failures, retries, partial prices and missing-link outcomes replay with original times. |
| [ ] A10 | #7 | `test_run_storage.PersistedRunTests.test_outage_after_selection_collects_and_replay_corrects_provisional_missed_slot` | Registration outage retains selected work; replay preserves IDs and corrects a provisional missed marker. |
| [ ] A11 | #7 | `test_run_storage.PersistedRunTests.test_outage_before_due_selection_opens_no_sessions_and_later_records_gaps` | An outage before selection opens no browsers; recovery records gaps without synthetic observations. |
| [ ] A12 | #4 | `test_run_storage.PersistedRunTests.test_partial_failure_and_missing_link_are_persisted_explicitly` | Partial, failed and missing-link outcomes persist explicit status/error/null gaps. |
| [ ] A13 | #7 | `test_run_storage.PersistedRunTests.test_replay_after_lost_commit_acknowledgement_preserves_each_original_record_once` | Ambiguous commit replay preserves exactly one copy of each original record, including numeric odds and completion times. |
| [ ] A14 | #6 | `test_run_storage.PersistedRunTests.test_rescheduling_preserves_elapsed_gaps_and_excludes_cancelled_slots` | Rescheduling retains elapsed gaps while cancelled future slots are excluded from missed history. |
| [ ] A15 | #6 | `test_run_storage.PersistedRunTests.test_resume_records_missed_slots_without_fabricating_runs` | Resume with no current work records missed slots idempotently, with no synthetic runs, attempts or odds. |
| [ ] A16 | #6 | `test_run_storage.PersistedRunTests.test_resume_scrapes_only_current_minute_and_preserves_actual_start_time` | Resume collects only current-minute work and preserves actual start time separately from intended time. |
| [ ] A17 | #5 | `test_run_storage.PersistedRunTests.test_retry_history_keeps_ids_order_errors_and_final_odds` | Failed retries and final readings retain distinct UUIDs, retry order, errors, actual times and final odds. |
| [ ] A18 | #4 | `test_run_storage.PersistedRunTests.test_run_is_visible_to_another_connection_before_bookmaker_io` | Run registration is committed and visible before bookmaker IO begins. |
| [ ] A19 | #6 | `test_run_storage.PersistedRunTests.test_run_registration_failure_rolls_back_missed_slot_reconciliation` | Failed registration rolls back the surrounding reconciliation transaction. |
| [ ] A20 | #5 | `test_run_storage.PersistedRunTests.test_unchanged_reading_is_stored_again_in_a_distinct_run` | Repeated launches of the same slot retain distinct runs and outcomes even when odds are unchanged. |
| [ ] A21 | #3 | `test_scheduled_work.ScheduledWorkTests.test_discovery_makes_all_current_links_due_by_stable_match_id` | Due selection joins current links by stored match ID and selects only the requested minute. |
| [ ] A22 | #3 | `test_scheduled_work.ScheduledWorkTests.test_kickoff_seconds_change_does_not_select_two_slots_in_one_minute` | A kickoff-seconds change does not launch two active slots in the same minute. |
| [ ] A23 | #3 | `test_scheduled_work.ScheduledWorkTests.test_rescheduling_replaces_future_work_and_preserves_elapsed_slots` | Future work changes while elapsed slot IDs, times and evidence remain intact. |
| [ ] A24 | #3 | `test_scheduled_work.ScheduledWorkTests.test_unchanged_rediscovery_keeps_slot_identity` | Unchanged rediscovery preserves slot and match UUIDs. |

## B. Additional coverage to implement and execute after implementation

These are missing tests or unexecuted integration scenarios, **not additional
unittest skips**. Prefer the existing discovery-to-collection-to-history
workflow with controlled bookmaker responses and real PostgreSQL. Mock only
external systems when needed; do not test private helper calls or exact SQL text.

| Case | Tickets | Required check | Environment |
| --- | --- | --- | --- |
| [ ] B01 | #1–#8 | One controlled end-to-end workflow persists discovery/schedules, collects all bookmakers, and reads the same match through the public model history API with no operational CSV input/output. | PostgreSQL |
| [ ] B02 | #4, #8 | Verify all 30 odds fields against independent known prices, PostgreSQL numeric values/Decimal precision and explicit nulls, including invalid/missing source values. | PostgreSQL |
| [ ] B03 | #5, #8 | Query persisted startup retries, scrape retries, exhausted retries, final successes and unchanged readings; each original attempt has its own identity, time, order and error. | PostgreSQL |
| [ ] B04 | #5, #6 | Run genuinely overlapping launches of the same minute; retain both runs and all actual outcomes. Exercise minute rollover so selected/registered work is not falsely missed. | PostgreSQL, controlled concurrent workflow |
| [ ] B05 | #7, #8 | Restart a process with full queued registration and completion payloads; read recovered original IDs, statuses, UTC times and exact prices through the public history API. | PostgreSQL plus real local queue/processes |
| [ ] B06 | #8 | Full history contains every repeated launch/retry, unchanged/partial/failed/missing-link outcome, missed slot and incomplete run, in deterministic time order. No synthetic bookmaker rows or forward-filled odds. | PostgreSQL |
| [ ] B07 | #8 | Single and combined bookmaker/status/time filters; inclusive start and exclusive end; UTC conversion for aware/naive bounds; source time is distinct from actual observation time. Missed/incomplete filter semantics match the API contract. | PostgreSQL |
| [ ] B08 | #8 | Valid unknown match IDs return an empty result with stable columns; numeric/null/time types remain usable; historical slot kickoff and stored source names survive rediscovery changes. | PostgreSQL |
| [ ] B09 | #8 | Invalid IDs, names, statuses, bounds and reversed ranges fail before database work; absence of model credentials never falls back to writer credentials. | Missing local-only coverage; no Lubuntu requirement |
| [ ] B10 | #8 | Execute the delivered reader-role setup in an isolated database. A real reader login can query history and cannot insert/update/delete/truncate or change scraper schema, including after requesting a read-write transaction. | PostgreSQL, disposable roles/admin |
| [ ] B11 | #8 | Future tables created by the configured scraper owner receive intended reader SELECT privileges without write grants; schema/search-path and per-machine credentials work as documented. | PostgreSQL, disposable roles/admin |
| [ ] B12 | #11 | Successful full backup publishes a private complete bundle with a valid table of contents/checksum; earlier artifacts remain unchanged. No table exclusions or credentials in logs/manifests. | Missing command-boundary tests plus real PostgreSQL |
| [ ] B13 | #11 | Failed dump/archive check/file write/publication yields failure without publishing a partial successful artifact or damaging an earlier backup. | Missing command/filesystem tests; controlled responses can run locally |
| [ ] B14 | #11 | Corrupt checksum or missing known-match oracle fails verification before creating a database; unknown/empty match cannot be presented as successful history verification. | Missing command tests plus PostgreSQL oracle capture |
| [ ] B15 | #11 | Failed database creation never drops an existing database. Restore/query/history mismatch failures clean up only the newly created target; intentional keep behavior and cleanup failure are reported accurately. | Missing command tests plus isolated PostgreSQL |
| [ ] B16 | #11 | Full real dump → fresh isolated restore → public history query preserves reference IDs, scheduled/actual/source/completion timestamps, statuses, gaps and exact prices. Concurrent additional observations do not invalidate immutable reference rows. | PostgreSQL server/client tools, CREATEDB test role |
| [ ] B17 | #11 | Independently confirm restored catalog/listings/schedules/runs/attempts/odds/missed-slot tables are present, and source database history is untouched. Reapply model grants and prove write rejection on the restored database. | PostgreSQL, disposable roles/admin |
| [ ] B18 | #12 | Delivered session-check/direct runner skip before Python when no usable display, no active local graphical session, stale display after logout, or SSH-only login. Valid local session executes the existing CLI once and propagates failures. | Command-boundary coverage where possible; real Lubuntu required for final proof |
| [ ] B19 | #12, #13 | Syntax/unit/calendar checks pass for the final delivered files; installer and every documented start/stop/status/log/uninstall command match actual installed names and behavior. | Local static checks where possible; target verification still required |

B09 and the controlled-command portions of B12–B15 were deferred/missing, not
blocked by Lubuntu itself. Build those tests as part of final validation if they
have not been added during the remaining implementation work. Do not count a
controlled-command test as proof that a real database restored successfully.

## C. Real Lubuntu and cross-device checks unavailable here

Run these **after their owning implementations exist**. In particular, the
minute launcher/guide from #12/#13 are not delivered in the audit baseline;
do not invent commands or claim their runtime checks were already skipped by
the existing suite. #9 remains the owning desktop integration gate.

| Case | Tickets | Action and required evidence |
| --- | --- | --- |
| [ ] C01 | #1, #8 | With no desktop user logged in, PostgreSQL remains a system service and the model reader can query stored history with its real credentials. |
| [ ] C02 | #9, #12 | Install the delivered user timer/autostart in a local Lubuntu graphical login. Observe at least two consecutive minute ticks, the expected current-minute CLI, and journal timestamps. A tick without due work need not create a run. |
| [ ] C03 | #4, #8, #9, #12 | Choose real due samples and prove headed Pinnacle and Playdoit launch with Linux profiles and imported display credentials. Capture actual database outcomes and history; preserve current browser mode and URLs. |
| [ ] C04 | #9, #12 | Before login, after graphical logout and during SSH-only login, observe no scraping. A stale imported DISPLAY must not bypass the actual logind guard. Keep user lingering disabled. |
| [ ] C05 | #6, #9, #12 | Pause through due slots, log back in, and prove missed slots have original intended times and no synthetic odds; new runs have actual current times. Timer activations are not replayed as on-time scrapes. |
| [ ] C06 | #3, #9, #12, #13 | Check that discovery retains its existing independent cadence; the minute timer does not invoke discovery. Repeated service activations are serialized, failures reach journald, and guide disable/uninstall steps work. |
| [ ] C07 | #7, #8 | On a disposable PostgreSQL instance, exercise actual connection loss/restart after selection, during registration, and after remote commit. Restart the scraper and compare recovered history. Separately verify pre-selection outage becomes a genuine gap. Never stop the production server for this test. |
| [ ] C08 | #8, #10 | From the real modeling machine on the LAN and then outside it, connect through the private VPN, query the known match, and demonstrate denied writes with the dedicated reader role. |
| [ ] C09 | #10 | Verify actual listening addresses, host authentication and firewall rules permit intended VPN/local paths and do not expose PostgreSQL directly to the public internet. Record both-machine setup without secrets. |
| [ ] C10 | #11 | Validate and install the final backup service/timer. Observe a successful scheduled artifact, backup during desktop logout, and the documented catch-up behavior after downtime. Record actual timer/journal output. |
| [ ] C11 | #11 | Restore a real completed artifact into a fresh isolated database and run the known history comparison. Record archive checksum, generated database name, comparison count, cleanup result and unaffected source history. |
| [ ] C12 | #1, #7, #8, #11 | Rehearse recovery instructions on an isolated replacement: restore database/roles/grants, query as the model reader, deny writes, and account for the separate undelivered queue and credentials. Only queue records whose original slots exist can replay; do not remap identities or invent missing catalog history. |
| [ ] C13 | #13 | Follow the guide without relying on conversation context. Each graphical login, logout, SSH-only, headed-browser, missed-slot and discovery-cadence step has an observed expected result. Record that #9's real gate, rather than documentation review, verified runtime behavior. |

Known backup static commands (delivered in the current working tree):

```sh
systemd-analyze verify \
  Scrapper/systemd/agentic-history-backup.service \
  Scrapper/systemd/agentic-history-backup.timer
systemd-analyze calendar '*-*-* 03:15:00'
```

Use the final #11 runbook for real backup/restore commands and the final #13
guide for minute-launcher commands. Recheck final filenames after implementation;
this inventory does not authorize pretending absent scripts were installed.

## Evidence and completion

For each A/B/C case, record:

- Case ID, owning ticket(s), final commit, UTC execution date and host.
- OS/PostgreSQL/Python/browser versions relevant to the check.
- The sanitized command and fixture/sample IDs, expected and observed result.
- Exit code, test summary, journal excerpts, and database/history evidence.
- PASS, FAIL, BLOCKED or NOT WRITTEN; reason and linked follow-up if unresolved.

Do not include passwords, connection strings containing secrets, or browser
authentication material. Keep test schemas/databases and roles isolated, and
record cleanup of only resources created by the test.

Final completion requires: all 24 existing skips resolved by execution; missing
coverage implemented/passed; every applicable target/cross-device check passed;
no unexplained failures or skipped requirements; and an evidence summary linked
to the final validation issue. Reconcile any newly added tickets/tests against
this inventory before declaring the whole system validated. Do not reopen or
close earlier implementation issues automatically merely to update this list.
