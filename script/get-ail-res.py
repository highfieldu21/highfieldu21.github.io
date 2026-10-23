#!/usr/bin/env python3
"""
Download the results feed from sportsmanager.ie and save it as data/results_ail.json
in the same shape as the other results file.

Only Highfield games are kept. Only these fields are written, one record per result:

    Date        <- fixtureDate (Unix timestamp), shown as 24/10/2026
    Opposition  <- awayTeam when Highfield is at home, homeTeam when away
    Referee     <- officials.Referee
    Competition <- competitionName
    Loc         <- "Home" if homeTeam contains Highfield, "Away" if awayTeam does
    Grade       <- always "Senior"
    Result      <- homeResult when Loc is Home, awayResult when Loc is Away, shown as Win / Loss / Draw
    Score       <- homeScore and awayScore joined, e.g. "57:29" (home first, as in the feed).
                   The feed gives "57;8" (points;league points), so only the part before ";" is used.

Usage:
    python script/get-ail-res.py
    python script/get-ail-res.py --from 2026-09-01 --to 2027-04-30
    python script/get-ail-res.py --url "https://sportsmanager.ie/dataFeed/index.php?..."   # exact URL
    python script/get-ail-res.py --dry-run          # show the result, write nothing

Dates for --from / --to are YYYY-MM-DD (the feed's format, unlike the DD-MM-YYYY the other scripts use).
"""
import argparse
import sys
from collections import Counter

import requests

from rugby_util import dump_json, timestamp_to_date, write_text

BASE_URL = "https://sportsmanager.ie/dataFeed/index.php"
DEFAULT_FROM = "2026-09-01"
DEFAULT_TO = "2027-04-30"
USER_ID = "7533"
COMPETITION_ID = "215685"
OUTPUT = "data/results_ail.json"

CLUB = "Highfield"      # matched anywhere in the team name, ignoring capitals
GRADE = "Senior"        # every result in this feed gets this grade

# Say honestly who is asking, so the feed's owner can see what is calling it.
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:153.0) Gecko/20100101 Firefox/153.0"


def build_params(from_date, to_date, user_id, competition_id):
    return {
        "feedType": "fixture",
        "type": "results",
        "user_id": user_id,
        "date_from": from_date,
        "date_to": to_date,
        "sort": "date",
        "competition_id": competition_id,
    }


def fetch_json(url, params=None):
    """GET the feed and return the parsed JSON. Raises on HTTP errors or non-JSON replies."""
    resp = requests.get(
        url,
        params=params,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=30,
    )
    resp.raise_for_status()
    try:
        return resp.json()
    except ValueError:
        start = resp.text[:200].replace("\n", " ")
        raise ValueError(f"response was not JSON (it starts: {start!r})")


def describe(data) -> str:
    if isinstance(data, list):
        return f"a list of {len(data)} item(s)"
    if isinstance(data, dict):
        keys = ", ".join(list(data)[:8])
        return f"an object with keys: {keys}"
    return f"a {type(data).__name__}"


def as_text(value) -> str:
    """Plain text from a feed value. Handles strings, numbers and {"name": ...} style objects."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        for key in ("name", "fullName", "displayName", "teamName", "clubName", "title"):
            if as_text(value.get(key)):
                return as_text(value[key])
        names = " ".join(as_text(value.get(k)) for k in ("firstName", "lastName")).strip()
        return names
    if isinstance(value, list):
        return ", ".join(t for t in (as_text(v) for v in value) if t)
    return ""


def find_records(data):
    """Return the list of fixture objects, wherever the feed keeps it (top level or inside a wrapper)."""
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        for value in data.values():
            if isinstance(value, list) and any(isinstance(r, dict) and "fixtureDate" in r for r in value):
                return [r for r in value if isinstance(r, dict)]
        for value in data.values():                      # one level deeper
            found = find_records(value) if isinstance(value, dict) else None
            if found:
                return found
    return None


def get_referee(record) -> str:
    officials = record.get("officials")
    if isinstance(officials, dict):
        return as_text(officials.get("Referee"))
    return ""


RESULT_WORDS = {"win": "Win", "lose": "Loss", "loss": "Loss", "draw": "Draw"}


def points(value) -> str:
    """'57;8' -> '57'. The feed's score is 'points;league points'; only the match points are wanted."""
    return as_text(value).split(";")[0].strip()


def result_word(value) -> str:
    """'win' -> 'Win', 'lose' -> 'Loss', 'draw' -> 'Draw' (what the website colours). Anything else is kept as is."""
    text = as_text(value)
    return RESULT_WORDS.get(text.lower(), text)


def convert(records):
    """Turn feed records into the output shape. Returns (results, notes about anything odd)."""
    results = []
    missing = Counter()
    skipped = 0
    club = CLUB.lower()

    for r in records:
        home = as_text(r.get("homeTeam"))
        away = as_text(r.get("awayTeam"))

        if club in home.lower():
            loc = "Home"
        elif club in away.lower():
            loc = "Away"
        else:
            skipped += 1                  # not a Highfield game: leave it out
            continue

        home_score = points(r.get("homeScore"))
        away_score = points(r.get("awayScore"))

        result = {
            "Date": timestamp_to_date(r.get("fixtureDate")),
            "Competition": as_text(r.get("competitionName")),
            "Grade": GRADE,
            "Referee": get_referee(r),
            "Opposition": away if loc == "Home" else home,
            "Loc": loc,
            "Result": result_word(r.get("homeResult" if loc == "Home" else "awayResult")),
            "Score": f"{home_score}:{away_score}" if (home_score and away_score) else "",
        }
        for field, source in (("Date", "fixtureDate"), ("Opposition", "homeTeam/awayTeam"),
                              ("Referee", "officials.Referee"), ("Competition", "competitionName"),
                              ("Result", "homeResult/awayResult"), ("Score", "homeScore/awayScore")):
            if not result[field]:
                missing[source] += 1
        results.append(result)

    notes = [f"{n} result(s) have no value for {source}" for source, n in missing.items()]
    if skipped:
        notes.append(f"{skipped} game(s) skipped because neither team is {CLUB}")
    return results, notes


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--from", dest="from_date", default=DEFAULT_FROM, help="start date YYYY-MM-DD")
    p.add_argument("--to", dest="to_date", default=DEFAULT_TO, help="end date YYYY-MM-DD")
    p.add_argument("--user-id", default=USER_ID)
    p.add_argument("--competition-id", default=COMPETITION_ID)
    p.add_argument("--url", help="use this exact URL instead of building one (ignores the options above)")
    p.add_argument("--out", default=OUTPUT, help="output file (default: %(default)s)")
    p.add_argument("--allow-empty", action="store_true", help="write the file even if there are no results")
    p.add_argument("--dry-run", action="store_true", help="print a preview instead of writing the file")
    args = p.parse_args()

    if args.url:
        url, params = args.url, None
    else:
        url = BASE_URL
        params = build_params(args.from_date, args.to_date, args.user_id, args.competition_id)

    try:
        data = fetch_json(url, params)
    except requests.RequestException as exc:
        print(f"ERROR: request failed: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"ERROR: {exc}; not overwriting existing data.", file=sys.stderr)
        return 1

    print(f"Feed returned {describe(data)}")

    records = find_records(data)
    if records is None:
        print("ERROR: could not find a list of fixtures (objects with a 'fixtureDate') in the feed; "
              "not overwriting existing data.", file=sys.stderr)
        return 1

    results, notes = convert(records)
    for note in notes:
        print(f"NOTE: {note}")
    print(f"Converted {len(results)} result(s)")

    if not results and not args.allow_empty:
        print("ERROR: no results to write; not overwriting existing data. "
              "Use --allow-empty if this is expected.", file=sys.stderr)
        return 1

    text = dump_json(results)
    if args.dry_run:
        print(text[:1500])
        return 0

    write_text(args.out, text)
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
