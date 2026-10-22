#!/usr/bin/env python3
"""
Python equivalent of the Apps Script myFixtureData(fDate, tDate).

It POSTs a date range to the Munster Rugby SportLoMo fixtures page, pulls the
data-* attributes out of each fixture row, and writes the Highfield games to
data/results.json in the format the website expects.

Usage:
    pip install requests
    python update_fixtures.py --from 01/09/2026 --to 22/10/2026
    python update_fixtures.py                      # defaults to the futuee
    python update_fixtures.py --all                # keep every club's games, not just Highfield
"""
import argparse
import html
import json
import re
import os
import sys

from datetime import datetime, timedelta
from pathlib import Path

import requests


DEFAULT_TO = "31-05-2027"

URL = "https://munsterrugby.sportlomo.com/fixtures/"
CLUB = "Highfield RFC"
OUTPUT = Path("data/fixtures.json")

# Competition text -> Grade shown on the website. Edit to suit; first match wins.

GRADE_EXCEPTIONS = [
    ("dennehy cup", "J2"),
    ("junior 2", "J2"),
    ("seconds", "J1"),
    ("senior clubs league", "J1"),
    ("senior challenge", "Senior"),
]

ROW_SPLIT = '<ul class="column-seven table-body"'


def strip_html_entities(text):
    """Equivalent of stripHtmlEntities(): decode things like &amp; and &#39;."""
    return html.unescape(text or "").strip()


def attr(row, name):
    """Equivalent of row.match(/data-<name>="(.*?)"/mi)[1]; empty string if missing."""
    m = re.search(rf'data-{name}="(.*?)"', row, re.I | re.S)
    return m.group(1) if m else ""


def fetch_html(from_date, to_date):
    form = {"fdate": from_date, "tdate": to_date, "sort": "date", "btn": ""}
    resp = requests.post(
        URL,
        data=form,  # sent as application/x-www-form-urlencoded, like the original
        headers={"User-Agent": "Mozilla/5.0 (compatible;  Google-Apps-Script)"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.text


def parse_fixtures(page):
    """Returns one dict per fixture row (same fields the script collected)."""
    rows = page.split(ROW_SPLIT)[1:]  # first chunk is the page header, as in the original loop starting at 1
    fixtures = []
    for row in rows:
        home = strip_html_entities(attr(row, "hometeam"))
        away = strip_html_entities(attr(row, "awayteam"))
        if CLUB in home:
            flag = "Home"
        elif CLUB in away:
            flag = "Away"
        else:
            flag = "-"
        fixtures.append({
            "date": attr(row, "date"),
            "home": home,
            "away": away,
            "referee": attr(row, "referee"),
            "competition": strip_html_entities(attr(row, "compname")),
            "venue": strip_html_entities(attr(row, "venue")),
            "flag": flag,
        })
    return fixtures


def normalise_date(raw):
    """Return dd/mm/yyyy, which is what the website expects."""
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(raw.strip(), fmt).strftime("%d/%m/%Y")
        except ValueError:
            continue
    return raw  # unknown format: leave untouched so nothing is lost

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


def to_result_row(f):
    opposition = f["away"] if f["flag"] == "Home" else f["home"] if f["flag"] == "Away" else f"{f['home']} v {f['away']}"
    return {
        "Date": normalise_date(f["date"]),
        "Opposition": opposition,
        "Loc": f["flag"],
        "Competition": f["competition"],
        "Ground": f["venue"],
        "Grade": get_grade(f["competition"]),        
        "Referee": f["referee"],        
    }


def key(r):
    return (r["Date"], r["Opposition"], r["Competition"])


def sort_key(r):
    try:
        return datetime.strptime(r["Date"], "%d/%m/%Y")
    except ValueError:
        return datetime.min


def main():
    today = datetime.today()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--from", dest="from_date", default=(today - timedelta(days=2)).strftime("%d-%m-%Y"),
                   help="start date dd/mm/yyyy (default: 2 days ago)")

    p.add_argument("--to", dest="to_date",
                        default=os.environ.get("TO_DATE") or DEFAULT_TO,
                        help="End date DD-MM-YYYY")
        
    p.add_argument("--all", action="store_true", help="include games that don't involve " + CLUB)
    p.add_argument("--out", default=str(OUTPUT), help="output file (default: data/fixtures.json)")
    args = p.parse_args()
    print (args.from_date, args.to_date)

    fixtures = parse_fixtures(fetch_html(args.from_date, args.to_date))
    print(f"Found {len(fixtures)} fixtures between {args.from_date} and {args.to_date}")
    if not args.all:
        fixtures = [f for f in fixtures if f["flag"] != "-"]

    if not fixtures and not args.allow_empty:
        print("ERROR: no fixtures found; not overwriting existing data. "
          "Use --allow-empty if this is expected.", file=sys.stderr)
        return 1

    output = fixtures
    text = json.dumps(output, indent=2, ensure_ascii=False) + "\n"    
    
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"Wrote {args.out}")
    return 0




if __name__ == "__main__":
    main()
