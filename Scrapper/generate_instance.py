from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from time import sleep

import pandas as pd
import requests

from utilities.caliente_scrapper import CalienteSession
from utilities.pinnacle_scrapper import PinnacleSession
from utilities.playdoit_scrapper import PlaydoitSession


MAX_ATTEMPTS = 3
BOOKMAKERS = [
    ("cal", "Caliente link", CalienteSession),
    ("pn", "Pinnacle link", PinnacleSession),
    ("pd", "Playdoit link", PlaydoitSession),
]


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
    if not isinstance(value, pd.Series):
        raise TypeError("scraper must return a pandas Series")

    metadata_columns = [
        f"{prefix}_match",
        f"{prefix}_Bookmarker",
        f"{prefix}_timestamp_utc",
    ]
    odds = value.drop(labels=metadata_columns, errors="ignore")
    missing_odds = odds[odds.isna()].index.tolist()

    if missing_odds:
        return {
            "value": value,
            "status": "partial",
            "error": "Missing odds: " + ", ".join(missing_odds),
        }
    return {"value": value, "status": "ok", "error": ""}


def _scrape_with_retries(session, prefix, link_column, link_row):
    link = link_row[link_column]
    if pd.isna(link) or not str(link).strip():
        return {
            "value": None,
            "status": "missing_link",
            "error": "No event link available",
        }

    link = str(link).strip()
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return _result_from_value(prefix, session.scrape(link))
        except Exception as error:
            should_retry = (
                attempt < MAX_ATTEMPTS and _is_transient_error(error)
            )
            print(
                f"Attempt {attempt}/{MAX_ATTEMPTS} failed for "
                f"{link_row['match']} from {link_column}: {error}"
            )
            if not should_retry:
                return {
                    "value": None,
                    "status": "failed",
                    "error": f"{type(error).__name__}: {_error_text(error)}",
                }
            sleep(2 ** (attempt - 1))

    raise RuntimeError("unreachable retry state")


def _open_session(session_factory, link_column):
    """Open a bookmaker session, retrying only transient startup failures."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        session = session_factory()
        try:
            return session.__enter__()
        except Exception as error:
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
    session = None
    try:
        session = _open_session(session_factory, link_column)
        for row_index, link_row in links.iterrows():
            results[row_index] = _scrape_with_retries(
                session,
                prefix,
                link_column,
                link_row,
            )
    except Exception as error:
        session_error = f"{type(error).__name__}: {_error_text(error)}"
        print(f"Could not run the {link_column} batch: {session_error}")
        for row_index, link_row in links.iterrows():
            if row_index in results:
                continue
            link = link_row[link_column]
            if pd.isna(link) or not str(link).strip():
                results[row_index] = {
                    "value": None,
                    "status": "missing_link",
                    "error": "No event link available",
                }
            else:
                results[row_index] = {
                    "value": None,
                    "status": "failed",
                    "error": f"Session failure: {session_error}",
                }
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
            results[row_index] = {
                "value": None,
                "status": "missing_link",
                "error": "No event link available",
            }
        else:
            results[row_index] = {
                "value": None,
                "status": "failed",
                "error": error_text,
            }
    return results


def _run_batches(links):
    batch_results = {}
    with ThreadPoolExecutor(max_workers=len(BOOKMAKERS)) as executor:
        futures = {
            executor.submit(
                _scrape_bookmaker_batch,
                links,
                prefix,
                link_column,
                session_factory,
            ): (prefix, link_column)
            for prefix, link_column, session_factory in BOOKMAKERS
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

        for prefix, _, _ in BOOKMAKERS:
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
                    pd.Series({"match": match_name}),
                    match_result,
                    pd.Series(scrape_details),
                ]
            )
        )
    return pd.DataFrame(rows)


def _utc_timestamp(value):
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def _select_scheduled_links(links, schedules, run_time=None):
    required_link_columns = {"match", "start_time"}
    required_schedule_columns = {
        "match",
        "start_time",
        "scheduled_time",
    }
    if not required_link_columns.issubset(links.columns):
        raise ValueError("links must contain 'match' and 'start_time' columns")
    if not required_schedule_columns.issubset(schedules.columns):
        raise ValueError(
            "schedules must contain 'match', 'start_time', and "
            "'scheduled_time' columns"
        )

    if run_time is None:
        run_time = pd.Timestamp.now(tz="UTC")
    else:
        run_time = _utc_timestamp(run_time)
    run_minute = run_time.floor("min")

    scheduled_times = pd.to_datetime(
        schedules["scheduled_time"],
        errors="coerce",
        utc=True,
    )
    invalid_scheduled_times = (
        schedules["scheduled_time"].notna() & scheduled_times.isna()
    )
    if invalid_scheduled_times.any():
        raise ValueError("scheduled_time contains invalid datetime values")

    due = schedules.loc[
        scheduled_times.dt.floor("min") == run_minute,
        ["match", "start_time"],
    ].copy()
    if due.empty:
        return links.iloc[0:0].copy()

    due["start_time"] = pd.to_datetime(
        due["start_time"],
        errors="coerce",
        utc=True,
    )
    if due["start_time"].isna().any():
        raise ValueError("schedule start_time contains invalid datetime values")
    due_keys = set(due.itertuples(index=False, name=None))

    link_start_times = pd.to_datetime(
        links["start_time"],
        errors="coerce",
        utc=True,
    )
    invalid_link_start_times = links["start_time"].notna() & link_start_times.isna()
    if invalid_link_start_times.any():
        raise ValueError("links start_time contains invalid datetime values")

    selected = links.loc[
        [
            (match_name, start_time) in due_keys
            for match_name, start_time in zip(
                links["match"],
                link_start_times,
            )
        ]
    ].copy()
    return selected


def generate_instance(
    links_path="links.csv",
    schedule_path="schedules.csv",
    output_path=None,
    run_time=None,
):
    links = pd.read_csv(links_path)
    schedules = pd.read_csv(schedule_path)
    scheduled_links = _select_scheduled_links(
        links,
        schedules,
        run_time=run_time,
    )
    if scheduled_links.empty:
        run_minute = _utc_timestamp(
            run_time if run_time is not None else pd.Timestamp.now(tz="UTC")
        ).floor("min")
        print(f"No matches scheduled for {run_minute.isoformat()}")
        return pd.DataFrame()

    print(f"Scraping {len(scheduled_links)} scheduled match(es)")
    batch_results = _run_batches(scheduled_links)
    dataframe = _build_dataframe(scheduled_links, batch_results)

    if output_path is None:
        timestamp = datetime.now().strftime("%d-%m-%Y %H-%M-%S")
        output_path = f"instance-{timestamp}.csv"
    dataframe.to_csv(output_path, index=False)
    return dataframe


if __name__ == "__main__":
    generate_instance()
