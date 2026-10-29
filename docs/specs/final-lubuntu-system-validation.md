## Problem Statement

The operator needs to finish implementing the PostgreSQL/Lubuntu migration and
then verify the entire system once the target environment is available. Earlier
tickets were implemented and closed while real PostgreSQL, desktop, network or
recovery checks could not run. A green local test summary with skips, a closed
issue, or a static review does not prove that deployed collection works or that
history can be recovered after failure.

The current audit found 24 existing automated tests skipped because no test
database was configured, plus missing history/permission and backup verification
coverage. Future timer and VPN deployment checks also cannot be completed in the
current environment. The operator needs one complete validation backlog rather
than reconstructing those omissions from conversation history.

## Solution

After the remaining implementation deliverables are ready, run one final
validation campaign on Lubuntu and the actual modeling machine. Re-run existing
tests against real PostgreSQL, add missing behavioral coverage, and execute the
desktop, timer, VPN, backup and recovery checks that require the deployed setup.
Use a companion Markdown inventory to track every check, its owning ticket,
prerequisites, expected result and execution evidence. Resolve failures and
unexplained skips before declaring the system validated.

This spec covers every ticket in the migration, including closed tickets. It is
a final validation gate and does not hold up implementation while Lubuntu is
being prepared. Runtime integration issues do not have to be closed before this
campaign starts; this campaign can supply the evidence their gates require.

## User Stories

1. As an operator, I want to finish the implementation deliverables before running final deployment validation, so that environment limitations do not interrupt development.
2. As an operator, I want one inventory covering all migration tickets, so that no deferred check is lost between conversations.
3. As an operator, I want closed implementation tickets audited too, so that closure is not mistaken for proof of deployment correctness.
4. As a maintainer, I want every existing skipped test listed by its exact identifier and reason, so that I can execute it without guessing what was omitted.
5. As a maintainer, I want tests not yet written distinguished from actual skips, so that missing coverage cannot appear as a successful run.
6. As an operator, I want prerequisites grouped by database, desktop and cross-device environment, so that I can prepare the right resources once.
7. As an analyst, I want discovery evidence and confident match reconciliation verified in PostgreSQL, so that cross-bookmaker comparisons use the correct event.
8. As an analyst, I want doubtful matches and missing kickoff evidence verified as reviewable, so that uncertainty is not silently merged away.
9. As an operator, I want persisted schedules and due selection verified by stable match ID, so that renamed or rescheduled events remain collectable.
10. As an analyst, I want elapsed slots and original timestamps preserved after rescheduling, so that historical observations remain interpretable.
11. As an analyst, I want all numeric odds fields and explicit null gaps verified, so that model inputs preserve usable prices and missingness.
12. As an operator, I want run registration verified before bookmaker IO, so that launched collection is durably identifiable.
13. As an analyst, I want startup retries, scrape retries and repeated launches verified as distinct records, so that actual attempts are never collapsed.
14. As an analyst, I want unchanged readings retained and queryable, so that repeated checks are distinguishable from missed collection.
15. As an operator, I want missed-slot reconciliation tested after pauses and at minute rollover, so that real launches are not falsely marked missed.
16. As an analyst, I want missed slots to contain no synthetic odds, so that later readings cannot masquerade as earlier observations.
17. As an operator, I want real database outages and scraper restarts tested, so that durable queue recovery is established beyond controlled error responses.
18. As an analyst, I want replay after uncertain commits to preserve original identities and timestamps once, so that recovery does not duplicate history.
19. As a model operator, I want the public history interface tested for complete history, filters, ordering and precision, so that model data access is reliable without CSV files.
20. As a model operator, I want real reader credentials denied writes even when transaction defaults are overridden, so that database privileges protect scraper records.
21. As an operator, I want actual graphical login and headed-browser launches verified, so that the timer can use the Lubuntu desktop and Linux profiles.
22. As an operator, I want pre-login, logout, stale-display and SSH-only cases verified, so that absent graphical sessions cannot start scraping.
23. As an operator, I want minute activations, serialization, logs and independent discovery cadence verified, so that the launcher preserves intended operation.
24. As a model operator, I want history access tested from the LAN and outside it through the private VPN, so that remote analysis works without public PostgreSQL exposure.
25. As an operator, I want daily backups tested during logout and downtime recovery, so that history protection does not depend on desktop activity.
26. As an operator, I want failed backup and restore operations tested without damaging existing data, so that recovery tooling fails safely.
27. As an analyst, I want a real isolated restore to return the original match, run and attempt history, so that backup artifacts prove recoverability.
28. As an operator, I want roles, grants, credentials and undelivered queue handling included in a recovery rehearsal, so that a restored database is usable after host failure.
29. As an operator, I want installation and operations instructions exercised against delivered files, so that the runbooks can be followed without conversation context.
30. As a maintainer, I want sanitized evidence and explicit PASS, FAIL, BLOCKED or NOT WRITTEN outcomes, so that validation status is reviewable and honest.
31. As a maintainer, I want newly added tickets and tests reconciled before sign-off, so that this audit snapshot cannot silently omit later work.

## Implementation Decisions

- Use one final validation campaign spanning the parent migration and tickets #2 through #13, including all closed implementation tickets and the remaining integration/operations work.
- Preserve the existing implementation sequence. This new validation gate does not add blockers to unfinished implementation tickets or require runtime integration gates to be closed before their own checks can execute.
- Maintain a companion Markdown inventory with the exact current skips, ticket-to-requirement mapping, missing coverage, deployment checks, prerequisites, execution instructions and an evidence template.
- Preserve the audit baseline: repository commit 5c8dde6, 44 discovered tests, 20 passed, 24 skipped, no failures or errors. Treat those numbers as a snapshot; final counts may grow as missing tests are implemented.
- Distinguish existing skipped automated tests, missing automated coverage, unexecuted deployment checks and local checks that already passed. Do not relabel an absent test or unfinished feature as a unittest skip.
- Prefer the existing public discovery-to-scheduled-collection-to-read-only-history workflow as the principal test boundary. Exercise queue recovery and isolated restoration through their public interfaces. Use actual desktop/network operations for behavior that cannot be proven through the database workflow.
- Execute database mutations, role provisioning, outage simulation and restoration only in expendable test resources. Keep source collection history and the production server untouched.
- Validate unchanged domain contracts: stable match and slot identities, distinct real run/attempt identities, actual UTC times, queryable numeric odds, explicit gaps, no fabricated observations, current-minute collection and unchanged cadence.
- Use real PostgreSQL grants for the reader privilege checks. Requesting read-only transactions alone is insufficient evidence that model credentials cannot modify scraper records.
- Validate backup publication and failure behavior, full archive scope, isolated restore identity/time comparisons, and recovery of access grants. Track cluster credentials and the undelivered local queue separately from database archive contents.
- Keep target-only and cross-device cases blocked until their owning deliverables and environments exist; do not invent launcher commands, substitute mocks for deployment proof, or mark documentation review as a successful smoke test.
- Record final commit, execution date, relevant versions, case IDs, sanitized commands/results, database/history evidence, journal excerpts and resource cleanup. Track failures and remaining blockers explicitly.
- Refresh the complete issue list and changed acceptance criteria before execution and sign-off. Do not automatically reopen or close the original implementation issues while preparing this spec.

## Testing Decisions

- Good tests assert observable results through public interfaces with independent known expectations. They do not assert private helper calls, exact SQL text or implementation-shaped mocks.
- Start by running all existing tests against an expendable PostgreSQL database. All 24 inventoried skips must receive actual outcomes; an otherwise green run with unresolved skips is incomplete.
- Discovery and schedule coverage must establish source evidence, confident and doubtful reconciliation, stable IDs across rediscovery, current links, exact due-minute selection, cadence boundaries and preservation of historical slots.
- Run/outcome coverage must establish registration visibility before IO; all numeric fields and null gaps; partial, failed and missing-link results; retry order and errors; repeated/unchanged readings; schema upgrades; incomplete runs; and absence of CSV dependencies.
- Missed-slot coverage must establish no invented odds or attempts, idempotent detection, attempted-run exclusion, current-minute eligibility, rescheduling behavior, transaction rollback and overlapping-launch/minute-rollover correctness.
- Outage coverage must include failures before selection, after selection/during registration, after collection and after an uncertain commit. Restart with durable queued data, then read recovered original records through the history interface. Use a disposable real instance for server connection-loss/restart checks.
- Add the missing history-interface cases: complete history including retries/gaps/incomplete runs, stable ordering, combined filters, half-open time ranges, UTC and numeric precision, unknown IDs, invalid inputs and dedicated model credential selection.
- Provision disposable reader roles and prove allowed queries and rejected changes, including after a read-write transaction is requested. Check intended SELECT access on future owner-created tables and restored databases.
- Add missing backup command/failure-path tests using real temporary storage and controlled external PostgreSQL command responses where appropriate. These can run locally and must not be counted as proof of a real restore.
- Perform a real full database backup and fresh isolated restore. Query known reference history and independently check restored application tables, original IDs/times/values, cleanup behavior and unchanged source history.
- Validate actual scheduled backup execution, logged-out operation, catch-up behavior, journal failures and the documented recovery procedure, including external credentials and retained queued results.
- On Lubuntu, validate final launcher scripts, units and calendar; graphical environment import; at least two minute activations; headed Pinnacle and Playdoit sessions; login/logout/SSH restrictions; stale display rejection; serialization; error propagation; and independent discovery cadence.
- Follow the final timer guide and backup runbook as written. Require observed expected outcomes for installation, logs, status, disable/uninstall and smoke steps; static documentation review is not runtime evidence.
- From the real modeling device on the LAN and outside it, verify private-VPN connectivity, model history access, write rejection and intended listening/authentication/firewall restrictions.
- Prior art is the existing PostgreSQL workflow suite, controlled bookmaker sessions, durable local queue tests, public history reader and isolated backup verifier. Extend those boundaries rather than inventing lower-level test APIs.
- Completion requires all inventoried existing skips resolved, missing coverage added and passed, all applicable deployment checks passed, sanitized evidence recorded, and no unexplained failed, skipped, blocked or unwritten requirement. Changes after the audit must be included before final sign-off.

## Out of Scope

- Running the final deployment campaign before the operator supplies Lubuntu, PostgreSQL and the modeling-device/VPN environment.
- Pausing unfinished implementation work until the validation environment is ready.
- Treating issue closure, a green result with skips, controlled command responses or static review as proof of deployment correctness.
- Changing model calculations, collection/discovery cadence, bookmaker behavior or the headed-browser requirement merely to make tests easier.
- Exposing PostgreSQL publicly, testing destructive failure modes against production, importing historical test CSVs, or introducing a retention policy.
- Automatically rewriting existing issue states or claiming outstanding runtime acceptance criteria are completed by publishing this spec.

## Further Notes

The companion inventory records 24 exact existing skips, 19 missing/additional
coverage groups and 13 target/cross-device check groups. Some missing tests can
be written and run locally; the inventory explicitly distinguishes them from
checks unavailable in the current environment.

The successful issue-list snapshot in this audit listed tickets #2–#8 as closed
and the parent plus #9–#13 as open. Later API refreshes failed. Closed tickets
were checked against the repository tests and implementation changes; refresh
tracker details again before the final campaign.

The current environment lacks PostgreSQL tools/server/driver and test database
configuration. Backup calendar parsing succeeded, but unit verification exited
with sandbox socket-permission errors. No real restore, reader-role deployment,
graphical smoke test or remote VPN test is established by this audit.

Publish this as a separate final-validation issue with the ready-for-agent label.
Implementation can continue now; execution of the environment-dependent cases
waits for the completed deliverables and operator's Lubuntu setup.

### Exact skipped automated tests — 24

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

### Missing and additional coverage — 19 groups

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

### Target and cross-device validation — 13 groups

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
