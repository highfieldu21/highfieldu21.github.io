#!/usr/bin/env python3
"""
Download the fixture feed from sportsmanager.ie and save it as data/fixtures_ail.json
in the same shape as the other fixture files.

Only these fields are written, one record per fixture:

    Date        <- fixtureDate (Unix timestamp), shown as 24/10/2026
    Opposition  <- awayTeam when Highfield is at home, homeTeam when away
    Referee     <- officials.referee
    Competition <- competitionName
    Ground      <- venue
    Loc         <- "Home" if homeTeam contains Highfield, otherwise "Away"
    Grade       <- always "Senior"

Usage:
    python script/get-ail-fix.py
    python script/get-ail-fix.py --from 2026-09-01 --to 2027-04-30
    python script/get-ail-fix.py --url "https://sportsmanager.ie/dataFeed/index.php?..."   # exact URL
    python script/get-ail-fix.py --dry-run          # show the result, write nothing

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
OUTPUT = "data/fixtures_ail.json"

CLUB = "Highfield"      # matched anywhere in the team name, ignoring capitals
GRADE = "Senior"        # every fixture in this feed gets this grade

# Say honestly who is asking, so the feed's owner can see what is calling it.
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:153.0) Gecko/20100101 Firefox/153.0"


def build_params(from_date, to_date, user_id, competition_id):
    return {
        "feedType": "fixture",
        "type": "fixtures",
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


def convert(records):
    """Turn feed records into the output shape. Returns (fixtures, notes about anything odd)."""
    fixtures = []
    missing = Counter()
    neither = 0
    club = CLUB.lower()

    for r in records:
        home = as_text(r.get("homeTeam"))
        away = as_text(r.get("awayTeam"))
        loc = "Home" if club in home.lower() else "Away"
        if loc == "Away" and club not in away.lower():
            neither += 1

        fixture = {
            "Date": timestamp_to_date(r.get("fixtureDate")),
            "Opposition": away if loc == "Home" else home,
            "Referee": get_referee(r),
            "Competition": as_text(r.get("competitionName")),
            "Ground": as_text(r.get("venue")),
            "Loc": loc,
            "Grade": GRADE,
        }
        for field, source in (("Date", "fixtureDate"), ("Opposition", "homeTeam/awayTeam"),
                              ("Referee", "officials.referee"), ("Competition", "competitionName"),
                              ("Ground", "venue")):
            if not fixture[field]:
                missing[source] += 1
        fixtures.append(fixture)

    notes = [f"{n} fixture(s) have no value for {source}" for source, n in missing.items()]
    if neither:
        notes.append(f"{neither} fixture(s) don't involve {CLUB} at all - they are marked Away, "
                     f"with the home team as the opposition")
    return fixtures, notes


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--from", dest="from_date", default=DEFAULT_FROM, help="start date YYYY-MM-DD")
    p.add_argument("--to", dest="to_date", default=DEFAULT_TO, help="end date YYYY-MM-DD")
    p.add_argument("--user-id", default=USER_ID)
    p.add_argument("--competition-id", default=COMPETITION_ID)
    p.add_argument("--url", help="use this exact URL instead of building one (ignores the options above)")
    p.add_argument("--out", default=OUTPUT, help="output file (default: %(default)s)")
    p.add_argument("--allow-empty", action="store_true", help="write the file even if there are no fixtures")
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

    fixtures, notes = convert(records)
    for note in notes:
        print(f"NOTE: {note}")
    print(f"Converted {len(fixtures)} fixture(s)")

    if not fixtures and not args.allow_empty:
        print("ERROR: no fixtures to write; not overwriting existing data. "
              "Use --allow-empty if this is expected.", file=sys.stderr)
        return 1

    text = dump_json(fixtures)
    if args.dry_run:
        print(text[:1500])
        return 0

    write_text(args.out, text)
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
