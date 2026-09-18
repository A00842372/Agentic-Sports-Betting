import re
import unicodedata
from difflib import SequenceMatcher

import pandas as pd

from utilities.caliente_links import caliente_links
from utilities.pinnacle_links import pinnacle_links
from utilities.playdoit_links import playdoit_links
from utilities.schedule import schedule


def _normalize_team(team):
    team = unicodedata.normalize("NFKD", str(team))
    team = "".join(
        character
        for character in team
        if not unicodedata.combining(character)
    )
    return " ".join(re.findall(r"[a-z0-9]+", team.casefold()))


def _split_match(match):
    home_team, separator, away_team = str(match).partition("-vs-")
    if not separator:
        raise ValueError(f"Invalid match format: {match}")
    return _normalize_team(home_team), _normalize_team(away_team)


def _team_similarity(left_team, right_team):
    left_tokens = set(left_team.split())
    right_tokens = set(right_team.split())
    if not left_tokens or not right_tokens:
        return 0.0

    shared_tokens = left_tokens & right_tokens
    containment_score = len(shared_tokens) / min(
        len(left_tokens), len(right_tokens)
    )
    sequence_score = SequenceMatcher(None, left_team, right_team).ratio()
    sorted_token_score = SequenceMatcher(
        None,
        " ".join(sorted(left_tokens)),
        " ".join(sorted(right_tokens)),
    ).ratio()
    return 100 * max(containment_score, sequence_score, sorted_token_score)


def match_similarity(left_match, right_match):
    """Return a 0-100 similarity score while preserving home/away order."""
    left_home, left_away = _split_match(left_match)
    right_home, right_away = _split_match(right_match)
    return (
        _team_similarity(left_home, right_home)
        + _team_similarity(left_away, right_away)
    ) / 2


def add_bookmaker_links(
    base,
    bookmaker,
    link_column,
    tolerance=pd.Timedelta(minutes=5),
    minimum_similarity=45,
    ambiguity_margin=10,
):
    """Attach one-to-one bookmaker links using kickoff time and name similarity."""
    result = base.reset_index(drop=True).copy()
    available = bookmaker.reset_index(drop=True).copy()

    required_base_columns = {"match", "start_time"}
    required_bookmaker_columns = required_base_columns | {link_column}
    if not required_base_columns.issubset(result.columns):
        raise ValueError("base must contain match and start_time columns")
    if not required_bookmaker_columns.issubset(available.columns):
        raise ValueError(
            f"bookmaker must contain match, start_time, and {link_column} columns"
        )

    result["start_time"] = pd.to_datetime(
        result["start_time"], errors="coerce", utc=True
    )
    available["start_time"] = pd.to_datetime(
        available["start_time"], errors="coerce", utc=True
    )
    result[link_column] = pd.NA

    for result_index, base_match in result.iterrows():
        time_differences = (
            available["start_time"] - base_match["start_time"]
        ).abs()
        candidates = available[time_differences <= tolerance]
        if candidates.empty:
            continue

        if len(candidates) == 1:
            best_index = candidates.index[0]
        else:
            scores = candidates["match"].map(
                lambda candidate: match_similarity(
                    base_match["match"], candidate
                )
            ).sort_values(ascending=False)
            best_score = scores.iloc[0]
            second_best_score = scores.iloc[1]
            if (
                best_score < minimum_similarity
                or best_score - second_best_score < ambiguity_margin
            ):
                continue
            best_index = scores.index[0]

        result.at[result_index, link_column] = available.at[
            best_index, link_column
        ]
        available = available.drop(index=best_index)

    return result


pinnacle_urls = [
    "https://www.pinnacle.com/es/soccer/germany-bundesliga/matchups/#all",
    "https://www.pinnacle.com/es/soccer/spain-la-liga/matchups/#all",
    "https://www.pinnacle.com/es/soccer/france-ligue-1/matchups/#all",
    "https://www.pinnacle.com/es/soccer/england-premier-league/matchups/#all",
    "https://www.pinnacle.com/es/soccer/italy-serie-a/matchups/#all",
    "https://www.pinnacle.com/es/soccer/brazil-serie-a/matchups/#all",
    "https://www.pinnacle.com/es/soccer/mexico-liga-mx/matchups/#all",
]
caliente_urls = [
    "https://sports.caliente.mx/es_MX/Bundesliga-1",
    "https://sports.caliente.mx/es_MX/La-Liga",
    "https://sports.caliente.mx/es_MX/Ligue-1",
    "https://sports.caliente.mx/es_MX/Premier-League",
    "https://sports.caliente.mx/es_MX/Serie-A",
    "https://sports.caliente.mx/es_MX/t/2400790/Brasil-Serie-A",
    "https://sports.caliente.mx/es_MX/Liga-MX",
]
playdoit_urls = [
    "https://www.playdoit.mx/#page=championship&championshipIds=2950&periodType=0",
    "https://www.playdoit.mx/#page=championship&championshipIds=2941&periodType=0",
    "https://www.playdoit.mx/#page=championship&championshipIds=2943&periodType=0",
    "https://www.playdoit.mx/#page=championship&championshipIds=2936&periodType=0",
    "https://www.playdoit.mx/#page=championship&championshipIds=2942&periodType=0",
    "https://www.playdoit.mx/#page=championship&championshipIds=11318",
    "https://www.playdoit.mx/#page=championship&championshipIds=10009",
]

links = []

for index in range(7):
    caliente = caliente_links(caliente_urls[index])
    pinnacle = pinnacle_links(pinnacle_urls[index])
    playdoit = playdoit_links(playdoit_urls[index])

    matches = add_bookmaker_links(caliente, pinnacle, "Pinnacle link")
    matches = add_bookmaker_links(matches, playdoit, "Playdoit link")

    links.append(matches)


# Export the combined match links and scraping schedules as CSV files.
links_dataframe = pd.concat(links, ignore_index=True)
schedules_dataframe = schedule(links_dataframe)

links_dataframe.to_csv("links.csv", index=False)
schedules_dataframe.to_csv("schedules.csv", index=False)
