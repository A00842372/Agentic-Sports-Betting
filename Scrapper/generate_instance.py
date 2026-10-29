from concurrent.futures import ThreadPoolExecutor, as_completed
import os
from time import sleep
from uuid import uuid4

import pandas as pd
import requests

from utilities.scheduled_work import select_due_work, utc_timestamp
from utilities.run_storage import (
    normalize_reading, prepare_collection, prepare_runs, reconcile_missed_slots,
    start_runs, store_collection,
)
from utilities.outcome_queue import OutcomeQueue


MAX_ATTEMPTS = 3
BOOKMAKERS = [
    ("cal", "Caliente link"),
    ("pn", "Pinnacle link"),
    ("pd", "Playdoit link"),
]


def _default_session_factories():
    from utilities.caliente_scrapper import CalienteSession
    from utilities.pinnacle_scrapper import PinnacleSession
    from utilities.playdoit_scrapper import PlaydoitSession

    return {"cal": CalienteSession, "pn": PinnacleSession, "pd": PlaydoitSession}


def _error_text(error):
    return " ".join(str(error).split())


def _is_transient_error(error):
    """Return whether another attempt can reasonably succeed."""
    if isinstance(
        error,
        (
            TimeoutError,
            requests.Timeout,
            requests.ConnectionError,
        ),
    ):
        return True

    if isinstance(error, requests.HTTPError):
        status_code = getattr(error.response, "status_code", None)
        return status_code == 429 or (
            status_code is not None and status_code >= 500
        )

    error_type = type(error)
    if (
        error_type.__name__ == "TimeoutError"
        and error_type.__module__.startswith("playwright")
    ):
        return True

    message = _error_text(error).casefold()
    transient_browser_messages = (
        "net::err_",
        "navigation timeout",
        "temporarily unavailable",
    )
    return any(text in message for text in transient_browser_messages)


def _result_from_value(prefix, value):
    return {"value": value, **normalize_reading(prefix, value)}


def _missing_link_result():
    return _with_attempt_history({
        "value": None,
        "status": "missing_link",
        "error": "No event link available",
        "attempted_at": utc_timestamp(),
    }, [])


def _scrape_with_retries(session, prefix, link_column, link_row, attempts):
    link = link_row[link_column]
    if pd.isna(link) or not str(link).strip():
        return _missing_link_result()

    link = str(link).strip()
    for attempt in range(1, MAX_ATTEMPTS + 1):
        attempted_at = utc_timestamp()
        try:
            result = {**_result_from_value(prefix, session.scrape(link)),
                      "attempted_at": attempted_at}
        except Exception as error:
            should_retry = (
                attempt < MAX_ATTEMPTS and _is_transient_error(error)
            )
            print(
                f"Attempt {attempt}/{MAX_ATTEMPTS} failed for "
                f"{link_row['match']} from {link_column}: {error}"
            )
            result = {
                "value": None,
                "status": "failed",
                "error": f"{type(error).__name__}: {_error_text(error)}",
                "attempted_at": attempted_at,
            }
            _record_attempt(attempts, result)
            if not should_retry:
                return {**result, "attempts": attempts}
            sleep(2 ** (attempt - 1))
        else:
            _record_attempt(attempts, result)
            return {**result, "attempts": attempts}

    raise RuntimeError("unreachable retry state")


def _record_attempt(attempts, result):
    result.update(id=uuid4(), attempt_number=len(attempts) + 1)
    attempts.append(result)


def _with_attempt_history(result, attempts):
    _record_attempt(attempts, result)
    return {**result, "attempts": attempts}


def _open_session(session_factory, link_column, record_failure):
    """Open a bookmaker session, retrying only transient startup failures."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        attempted_at = utc_timestamp()
        try:
            session = session_factory()
            return session.__enter__()
        except Exception as error:
            record_failure(error, attempted_at)
            should_retry = (
                attempt < MAX_ATTEMPTS and _is_transient_error(error)
            )
            print(
                f"Attempt {attempt}/{MAX_ATTEMPTS} failed while opening "
                f"the {link_column} session: {error}"
            )
            if not should_retry:
                raise
            sleep(2 ** (attempt - 1))

    raise RuntimeError("unreachable session retry state")


def _scrape_bookmaker_batch(links, prefix, link_column, session_factory):
    """Scrape one bookmaker sequentially through one reusable session."""
    results = {}
    histories = {row_index: [] for row_index in links.index}
    session = None

    def record_session_failure(error, attempted_at):
        for row_index in links.index:
            if row_index not in results:
                _record_attempt(histories[row_index], {
                    "value": None,
                    "status": "failed",
                    "error": f"Session failure: {type(error).__name__}: {_error_text(error)}",
                    "attempted_at": attempted_at,
                })

    try:
        for row_index, link_row in links.iterrows():
            link = link_row[link_column]
            if pd.isna(link) or not str(link).strip():
                results[row_index] = _missing_link_result()
        if len(results) == len(links):
            return prefix, results
        session = _open_session(session_factory, link_column, record_session_failure)
        for row_index, link_row in links.iterrows():
            if row_index in results:
                continue
            results[row_index] = _scrape_with_retries(
                session,
                prefix,
                link_column,
                link_row,
                histories[row_index],
            )
    except Exception as error:
        session_error = f"{type(error).__name__}: {_error_text(error)}"
        print(f"Could not run the {link_column} batch: {session_error}")
        for row_index, link_row in links.iterrows():
            if row_index in results:
                continue
            link = link_row[link_column]
            if pd.isna(link) or not str(link).strip():
                results[row_index] = _missing_link_result()
            else:
                attempts = histories[row_index]
                if not attempts:
                    _record_attempt(attempts, {
                        "value": None,
                        "status": "failed",
                        "error": f"Session failure: {session_error}",
                        "attempted_at": utc_timestamp(),
                    })
                results[row_index] = {**attempts[-1], "attempts": attempts}
    finally:
        if session is not None:
            try:
                session.__exit__(None, None, None)
            except Exception as error:
                print(
                    f"Could not close the {link_column} session cleanly: "
                    f"{error}"
                )
    return prefix, results


def _failed_batch(links, link_column, error):
    error_text = f"Worker failure: {type(error).__name__}: {_error_text(error)}"
    results = {}
    for row_index, link_row in links.iterrows():
        link = link_row[link_column]
        if pd.isna(link) or not str(link).strip():
            results[row_index] = _missing_link_result()
        else:
            results[row_index] = _with_attempt_history({
                "value": None,
                "status": "failed",
                "error": error_text,
                "attempted_at": utc_timestamp(),
            }, [])
    return results


def collect_bookmaker_outcomes(links, session_factories):
    """Collect timestamped final results through the bookmaker session boundary."""
    batch_results = {}
    with ThreadPoolExecutor(max_workers=len(BOOKMAKERS)) as executor:
        futures = {
            executor.submit(
                _scrape_bookmaker_batch,
                links,
                prefix,
                link_column,
                session_factories[prefix],
            ): (prefix, link_column)
            for prefix, link_column in BOOKMAKERS
        }
        for future in as_completed(futures):
            prefix, link_column = futures[future]
            try:
                returned_prefix, results = future.result()
                batch_results[returned_prefix] = results
            except Exception as error:
                print(f"The {link_column} worker failed: {error}")
                batch_results[prefix] = _failed_batch(
                    links,
                    link_column,
                    error,
                )
    return batch_results


def _build_dataframe(links, batch_results):
    rows = []
    for row_index, link_row in links.iterrows():
        match_values = []
        scrape_details = {}

        for prefix, _ in BOOKMAKERS:
            result = batch_results[prefix][row_index]
            if result["value"] is not None:
                match_values.append(result["value"])
            scrape_details[f"{prefix}_status"] = result["status"]
            scrape_details[f"{prefix}_error"] = result["error"]

        match_name = link_row["match"]
        if match_values:
            match_result = pd.concat(match_values)
            match_name = match_result.get("cal_match", match_name)
            match_result = match_result.drop(
                labels=["cal_match", "pn_match", "pd_match"],
                errors="ignore",
            )
        else:
            match_result = pd.Series(dtype="object")

        rows.append(
            pd.concat(
                [
                    pd.Series({
                        "match": match_name,
                        "match_id": link_row["match_id"],
                        "slot_id": link_row["slot_id"],
                        "scheduled_time": link_row["scheduled_time"],
                        "run_id": link_row["run_id"],
                        "started_at": link_row["started_at"],
                    }),
                    match_result,
                    pd.Series(scrape_details),
                ]
            )
        )
    return pd.DataFrame(rows)


def _replay_outcomes(queue, database_url):
    import psycopg

    def write_collection(collection):
        with psycopg.connect(database_url, autocommit=True) as connection:
            store_collection(connection, collection)

    try:
        count = queue.replay(write_collection)
    except psycopg.Error as error:
        print(f"Results remain queued at {queue.path}: {type(error).__name__}: {_error_text(error)}")
        return False
    if count:
        print(f"Persisted {count} queued collection(s)")
    return True


def generate_instance(
    run_time=None,
    database_url=None,
    session_factories=None,
    queue_path=None,
):
    """Collect due work and durably deliver completed results to PostgreSQL."""
    database_url = database_url or os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("Set DATABASE_URL for PostgreSQL due-work selection")

    import psycopg

    queue = OutcomeQueue(queue_path)
    _replay_outcomes(queue, database_url)
    run_time = utc_timestamp(run_time)
    runs = None
    try:
        with psycopg.connect(database_url, autocommit=True) as connection:
            # Serialize normal minute checks through registration, retaining
            # local identities if PostgreSQL fails after selection succeeds.
            with connection.transaction():
                missed_count = reconcile_missed_slots(connection, run_time=run_time)
                scheduled_links = select_due_work(connection, run_time=run_time)
                if not scheduled_links.empty:
                    if session_factories is None:
                        session_factories = _default_session_factories()
                    if set(session_factories) != {prefix for prefix, _ in BOOKMAKERS}:
                        raise ValueError("Provide session factories for cal, pn, and pd")
                    runs = prepare_runs(scheduled_links)
                    queue.enqueue(prepare_collection(runs))
                    start_runs(connection, runs)
            if missed_count:
                print(f"Recorded {missed_count} missed scheduled slot(s)")
    except (psycopg.OperationalError, psycopg.InterfaceError) as error:
        if runs is None:
            raise
        print(f"Run registration queued at {queue.path}: {type(error).__name__}: {_error_text(error)}")
    if runs is None:
        print(f"No matches scheduled for {run_time.floor('min').isoformat()}")
        return pd.DataFrame()
    print(f"Scraping {len(runs)} scheduled match(es)")
    batch_results = collect_bookmaker_outcomes(runs, session_factories)
    queue.enqueue(prepare_collection(runs, batch_results))
    persisted = _replay_outcomes(queue, database_url)
    summary = _build_dataframe(runs, batch_results)
    summary.attrs["storage_status"] = "persisted" if persisted else "queued"
    return summary


if __name__ == "__main__":
    generate_instance()
