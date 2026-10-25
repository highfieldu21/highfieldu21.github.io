#!/usr/bin/env python3
"""
Download the league table from sportsmanager.ie and save only its "leaguetable" section
as data/table_ail.json (every team in the table, in the feed's order).

Only these fields are written, one record per team:

    team, club_logo, played, gameswon, gamesdraw, gameslost,
    pointsfor, pointsagainst, pointsdifference, points

Usage:
    python script/get-ail-table.py
    python script/get-ail-table.py --url "https://sportsmanager.ie/dataFeed/index.php?..."   # exact URL
    python script/get-ail-table.py --dry-run          # show the result, write nothing
"""
import argparse
import json
import sys

import requests

from rugby_util import dump_json, write_text

BASE_URL = "https://sportsmanager.ie/dataFeed/index.php"
USER_ID = "7533"
COMPETITION_ID = "215685"
OUTPUT = "data/table_ail.json"

SECTION = "leaguetable"     # the part of the feed that is kept (capitals and underscores ignored)
FIELDS = ["team", "club_logo", "played", "gameswon", "gamesdraw", "gameslost",
          "pointsfor", "pointsagainst", "pointsdifference", "points"]

# The feed spells some of these differently (gamesWon, gameLost, pointsFor ...). Capitals are
# ignored when matching; the extra names below cover the spellings that differ in more than case.
FEED_NAMES = {"gameslost": ["gameslost", "gamelost"]}

# Say honestly who is asking, so the feed's owner can see what is calling it.
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:153.0) Gecko/20100101 Firefox/153.0"


def build_params(user_id, competition_id):
    return {
        "feedType": "fixture",
        "type": "league_table",
        "user_id": user_id,
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


def squash(name) -> str:
    return str(name).replace("_", "").replace(" ", "").lower()


def find_section(data, name=SECTION):
    """Find the value stored under the 'leaguetable' key, at the top level or nested inside."""
    if isinstance(data, dict):
        for key, value in data.items():
            if squash(key) == name:
                return value
        for value in data.values():
            found = find_section(value, name)
            if found is not None:
                return found
    elif isinstance(data, list):
        for item in data:
            found = find_section(item, name)
            if found is not None:
                return found
    return None


def find_rows(section):
    """The team rows inside the section: a list of objects with a 'team', however it is grouped."""
    if isinstance(section, list):
        if any(isinstance(r, dict) and "team" in r for r in section):
            return [r for r in section if isinstance(r, dict)]
        rows = []
        for item in section:
            rows += find_rows(item)
        return rows
    if isinstance(section, dict):
        if "team" in section:
            return [section]
        rows = []
        for value in section.values():            # e.g. one list per pool, or rows keyed by position
            rows += find_rows(value)
        return rows
    return []


def clean(value):
    if value is None:
        return ""
    return value.strip() if isinstance(value, str) else value


def pick(row, field):
    """The row's value for `field`, matching the feed's key whatever its capitalisation."""
    lowered = {str(k).lower(): v for k, v in row.items()}
    for name in FEED_NAMES.get(field, [field]):
        if name in lowered:
            return clean(lowered[name])
    return ""


def convert(rows):
    """Keep only the wanted fields. Returns (table, notes about anything odd)."""
    table = [{field: pick(row, field) for field in FIELDS} for row in rows]
    notes = []
    for field in FIELDS:
        n = sum(1 for t in table if t[field] == "")
        if n:
            notes.append(f"{n} row(s) have no value for {field}")
    if notes and rows:
        notes.append(f"the first row's fields are: {', '.join(rows[0])[:300]}")
    return table, notes


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--user-id", default=USER_ID)
    p.add_argument("--competition-id", default=COMPETITION_ID)
    p.add_argument("--url", help="use this exact URL instead of building one (ignores the options above)")
    p.add_argument("--out", default=OUTPUT, help="output file (default: %(default)s)")
    p.add_argument("--allow-empty", action="store_true", help="write the file even if the table is empty")
    p.add_argument("--dry-run", action="store_true", help="print a preview instead of writing the file")
    args = p.parse_args()

    if args.url:
        url, params = args.url, None
    else:
        url = BASE_URL
        params = build_params(args.user_id, args.competition_id)

    try:
        data = fetch_json(url, params)
    except requests.RequestException as exc:
        print(f"ERROR: request failed: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"ERROR: {exc}; not overwriting existing data.", file=sys.stderr)
        return 1

    print(f"Feed returned {describe(data)}")

    section = find_section(data)
    if section is None:
        print(f"ERROR: no '{SECTION}' section in the feed; not overwriting existing data.", file=sys.stderr)
        return 1

    table, notes = convert(find_rows(section))
    for note in notes:
        print(f"NOTE: {note}")
    print(f"Found {len(table)} team(s) in the table")

    if not table and not args.allow_empty:
        print(f"ERROR: the '{SECTION}' section has no teams; not overwriting existing data. "
              "Use --allow-empty if this is expected.", file=sys.stderr)
        return 1

    text = dump_json(table)
    if args.dry_run:
        print(text[:1500])
        return 0

    write_text(args.out, text)
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
