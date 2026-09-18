"""Build an odds-scraping schedule from match start times."""

from datetime import timedelta

import pandas as pd


def schedule(dataframe, now=None):
    """Return one future scraping-schedule row per match and scheduled time.

    ``dataframe`` must contain ``match`` and ``start_time`` columns. Start times
    are converted to UTC; timezone-naive values are treated as UTC. The cadence
    remains dense near kickoff and progressively wider farther from kickoff.
    ``now`` is injectable to make schedule generation deterministic in tests.
    """
    if not isinstance(dataframe, pd.DataFrame):
        raise TypeError("dataframe must be a pandas DataFrame")
    required_columns = {"match", "start_time"}
    if not required_columns.issubset(dataframe.columns):
        raise ValueError("dataframe must contain 'match' and 'start_time' columns")

    start_times = pd.to_datetime(
        dataframe["start_time"], errors="coerce", utc=True
    )
    invalid_start_times = dataframe["start_time"].notna() & start_times.isna()
    if invalid_start_times.any():
        raise ValueError(
            "start_time contains values that cannot be parsed as datetimes"
        )

    if now is None:
        now = pd.Timestamp.now(tz="UTC")
    else:
        now = pd.Timestamp(now)
        if now.tzinfo is None:
            now = now.tz_localize("UTC")
        else:
            now = now.tz_convert("UTC")

    schedule_rows = []

    for match_name, start_time in zip(dataframe["match"], start_times):
        if pd.isna(start_time):
            continue
        time_until_start = start_time - now
        if time_until_start < timedelta(minutes=1):
            continue

        offset = timedelta(minutes=1)
        while offset <= time_until_start:
            schedule_rows.append(
                {
                    "match": match_name,
                    "start_time": start_time,
                    "scheduled_time": start_time - offset,
                }
            )

            if offset < timedelta(minutes=15):
                offset += timedelta(minutes=1)
            elif offset < timedelta(hours=2):
                offset += timedelta(minutes=5)
            elif offset < timedelta(hours=12):
                offset += timedelta(minutes=30)
            elif offset < timedelta(hours=24):
                offset += timedelta(hours=1)
            elif offset < timedelta(hours=48):
                offset += timedelta(hours=2)
            else:
                offset += timedelta(hours=4)

    result = pd.DataFrame(
        schedule_rows,
        columns=["match", "start_time", "scheduled_time"],
    )
    if result.empty:
        return result.astype(
            {
                "match": "object",
                "start_time": "datetime64[ns, UTC]",
                "scheduled_time": "datetime64[ns, UTC]",
            }
        )
    return (
        result.drop_duplicates()
        .sort_values(["scheduled_time", "start_time", "match"])
        .reset_index(drop=True)
    )
