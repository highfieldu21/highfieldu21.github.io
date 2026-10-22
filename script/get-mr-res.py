#!/usr/bin/env python3
"""
Fetch Munster Rugby results from munsterrugby.sportlomo.com and save as JSON.

Python port of the Apps Script function myResultData(fDate, tDate).

Usage:
    python scripts/fetch_results.py
    python scripts/fetch_results.py --from 01-09-2026 --to 30-09-2026
    python scripts/fetch_results.py --html-file sample.html   # offline test

Dates are DD-MM-YYYY, exactly as the Apps Script sent them. They can also be
set with the FROM_DATE / TO_DATE environment variables.
"""

import argparse
import html
import json
import os
import re
import sys

import requests
from datetime import datetime

URL = "https://munsterrugby.sportlomo.com/results/"
# ROW_SPLIT = '<ul class="column-six table-body resul"'
ROW_SPLIT = re.compile(r'(?=<ul[^>]*class="[^"]*\btable-body\b[^"]*\bresul\b)', re.IGNORECASE)

# Defaults copied from the original Apps Script (hardcoded there)
DEFAULT_FROM = "01-09-2026"
#DEFAULT_TO = "21-10-2026"

DROP_COLUMNS = ["home_team", "away_team", "home_score", "away_score"]

def fetch_html(from_date: str, to_date: str) -> str:
    """POST the same form the Apps Script posted and return the page HTML."""
    response = None

    form_data = {
        "fdate": from_date,
        "tdate": to_date,
        "sort": "date",
        "btn": "",
    }

    headers = {
        # Some sites reject the default python-requests User-Agent
        "User-Agent": "Mozilla/5.0 (compatible;  Google-Apps-Script)",
    }
    # requests sends a dict via data= as application/x-www-form-urlencoded
    response = requests.post(URL, data=form_data, headers=headers, timeout=30)

    response.raise_for_status()
    return response.text

def format_date(value: str) -> str:
    """'01 Oct 2026' -> '01/10/2026'. Returns the original text if it can't be parsed."""
    value = value.strip()
    for fmt in ("%d %b %Y", "%d %B %Y"):   # 'Oct' and 'October'
        try:
            return datetime.strptime(value, fmt).strftime("%d/%m/%Y")
        except ValueError:
            continue
    return value

def get_attr(row: str, name: str) -> str:
    """Equivalent of row.match(/data-<name>="(.*?)"/mi)[1]; '' if missing."""
    m = re.search(rf'data-{name}="(.*?)"', row, re.IGNORECASE | re.MULTILINE)
    return m.group(1) if m else ""


def get_score(txt_score: str) -> str:
    """Port of the Apps Script getScore().

    '' -> '-'
    '22 (3T)' -> '22'
    """
    if txt_score == "":
        return "-"

    # Same regex as the original: a digit, then anything up to the first "("
    m = re.search(r"([0-9].*?)\(", txt_score, re.IGNORECASE | re.MULTILINE)
    if m:
        return m.group(1).strip()

    # No "(" in the value (e.g. just "22"): return it as-is rather than crashing
    return txt_score.strip()

def _to_int(value):
    """Return an int if the value is numeric, otherwise None."""
    try:
        return int(str(value).strip())
    except ValueError:
        return None

def strip_html_entities(value: str) -> str:
    """Decode entities such as &amp; and &#39; into plain characters."""
    return html.unescape(value)

def get_venue(home_team: str, team: str) -> str:
    """Return 'Home' if home_team contains `team` (case-insensitive), else 'Away'."""
    return "Home" if team.lower() in home_team.lower() else "Away"

def get_opposition(home_team: str, away_team: str, team: str) -> str:
    """Return the team that is not `team` (case-insensitive substring match).

    Returns '' if neither side contains `team`.
    """
    needle = team.lower()
    if needle in home_team.lower():
        return away_team
    if needle in away_team.lower():
        return home_team
    return ""

def get_winner(home_team: str, away_team: str, home_score, away_score) -> str:
    """Win / Loss / Draw from `team`'s point of view.

    Returns '' if either score isn't a number (conceded, postponed, unplayed).
    """
    team = "Highfield"
    h, a = _to_int(home_score), _to_int(away_score)
    if h is None or a is None:
        return ""
    if h == a:
        return "Draw"

    winning_team = home_team if h > a else away_team
    return "Win" if team.lower() in winning_team.lower() else "Loss"

# Checked in order, first match wins. Matching is case-insensitive.
GRADE_EXCEPTIONS = [
    ("dennehy cup", "J2"),
    ("junior 2", "J2"),
    ("seconds", "J1"),
    ("senior challenge", "Senior"),
]

AGE_GRADE = re.compile(r"\bU\d+(?:\.\d+)?\b", re.IGNORECASE)


def get_grade(competition: str) -> str:
    """Derive a grade from the competition name.

    'Boys Clubs U14 Friendly'  -> 'U14'
    'South - Dennehy Cup'      -> 'J2'
    anything else unmatched    -> ''
    """
    name = competition.lower()

    for text, grade in GRADE_EXCEPTIONS:
        if text in name:
            return grade

    m = AGE_GRADE.search(competition)
    return m.group(0).upper() if m else ""

def parse_results(page_html: str) -> list:
    rows = ROW_SPLIT.split(page_html)[1:]  # first chunk is everything before row 1
    results = []

    for row in rows:
        home_team = get_attr(row, "hometeam")
        away_team = get_attr(row, "awayteam")
        home_score = get_score(get_attr(row, "homescore"))
        away_score = get_score(get_attr(row, "awayscore"))
        winner =  get_winner(home_team, away_team, home_score, away_score)
        competition = strip_html_entities(get_attr(row, "compname"))

        results.append(
            {
                "Date":  format_date(get_attr(row, "date")),
                "Competition": competition,
                "Result": winner,
                "Loc" : get_venue(home_team, "Highfield"),
                "Opposition" : get_opposition(home_team, away_team, "Highfield"),
                "Grade": get_grade(competition),
                "Score": f"{home_score}:{away_score}",
                "Referee": get_attr(row, "referee"),
                "home_team": home_team,
                "away_team": away_team,
                "home_score": home_score,
                "away_score": away_score,
            }
        )

    return results

def drop_columns(results: list, columns: list) -> list:
    """Return the records with the given keys removed (missing keys are ignored)."""
    drop = set(columns)
    return [{k: v for k, v in r.items() if k not in drop} for r in results]

def filter_by_team(results: list, team: str) -> list:
    """Keep only records where home_team or away_team contains `team` (case-insensitive)."""
    if not team:
        return results
    needle = team.lower()
    return [
        r for r in results
        if needle in r["home_team"].lower() or needle in r["away_team"].lower()
    ]

def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch Munster Rugby results to JSON")
    parser.add_argument("--from", dest="from_date",
                        default=os.environ.get("FROM_DATE") or DEFAULT_FROM,
                        help="Start date DD-MM-YYYY")
    parser.add_argument("--to", dest="to_date",
                        default=os.environ.get("TO_DATE") or DEFAULT_TO,
                        help="End date DD-MM-YYYY")
    parser.add_argument("--out", default="data/results.json", help="Output JSON path")
    parser.add_argument("--html-file", help="Parse a local HTML file instead of fetching")
    parser.add_argument("--allow-empty", action="store_true",
                        help="Write the file even if zero results were found")
    parser.add_argument("--debug", action="store_true",
                        help="Print request/response diagnostics")
    parser.add_argument("--save-html", help="Save the raw HTML response to this path")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print a preview instead of writing the file")
    parser.add_argument("--team", default=os.environ.get("TEAM_FILTER") or "Highfield",
                        help='Only keep matches where home or away team contains this text '
                             '(case-insensitive). Use --team "" to keep everything.')    
    args = parser.parse_args()

    if args.html_file:
        with open(args.html_file, encoding="utf-8") as f:
            page_html = f.read()
    else:
        try:
            page_html = fetch_html(args.from_date, args.to_date)
        except requests.RequestException as exc:
            print(f"ERROR: request failed: {exc}", file=sys.stderr)
            return 1

    if args.save_html:
        os.makedirs(os.path.dirname(args.save_html) or ".", exist_ok=True)
        with open(args.save_html, "w", encoding="utf-8") as f:
            f.write(page_html)

    if args.debug:
        print(f"[debug] html length: {len(page_html)}")
        print(f"[debug] 'data-hometeam' occurrences: {page_html.lower().count('data-hometeam')}")
        print(f"[debug] 'table-body' occurrences: {page_html.count('table-body')}")
        print(f"[debug] first 300 chars: {page_html[:300]!r}")

    results = parse_results(page_html)
    total_parsed = len(results)
    results = filter_by_team(results, args.team)
    print(f"Parsed {total_parsed} result(s); {len(results)} match '{args.team}'")
#    print(f"Parsed {len(results)} result(s) for {args.from_date} to {args.to_date}")

    results = drop_columns(results, DROP_COLUMNS)

    if not results and not args.allow_empty:
        print("ERROR: no results found; not overwriting existing data. "
              "Use --allow-empty if this is expected.", file=sys.stderr)
        return 1

    # No timestamp on purpose: identical data => identical file => no commit.
    #output = {
    #    "from": args.from_date,
    #    "to": args.to_date,
    #    "count": len(results),
    #    "results": results,
    #}
    output = results
    text = json.dumps(output, indent=2, ensure_ascii=False) + "\n"

    if args.dry_run:
        print(text[:1000])
        return 0

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
