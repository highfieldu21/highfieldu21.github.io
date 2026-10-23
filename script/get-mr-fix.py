#!/usr/bin/env python3
"""
Python equivalent of the Apps Script myFixtureData(fDate, tDate).

It POSTs a date range to the Munster Rugby SportLoMo fixtures page, pulls the
data-* attributes out of each fixture row, and writes the Highfield games to
data/fixtures.json in the format the website expects.

Usage:
    pip install requests
    python update_fixtures.py --from 01/09/2026 --to 22/10/2026
    python update_fixtures.py                      # defaults to the futuee
    python update_fixtures.py --all                # keep every club's games, not just Highfield
"""
import argparse
import os
import sys

from datetime import datetime, timedelta
from pathlib import Path

from rugby_util import (
    DEFAULT_TO,
    dump_json,
    fetch_html,
    format_date,
    get_attr,
    get_grade,
    get_opposition,
    strip_html_entities,
    write_text,
)

URL = "https://munsterrugby.sportlomo.com/fixtures/"
CLUB = "Highfield RFC"
OUTPUT = Path("data/fixtures.json")

ROW_SPLIT = '<ul class="column-seven table-body"'


def parse_fixtures(page):
    """Returns one dict per fixture row (same fields the script collected)."""
    rows = page.split(ROW_SPLIT)[1:]  # first chunk is the page header, as in the original loop starting at 1
    fixtures = []
    for row in rows:
        home = strip_html_entities(get_attr(row, "hometeam"))
        away = strip_html_entities(get_attr(row, "awayteam"))
        competition =  strip_html_entities(get_attr(row, "compname"))
        if CLUB in home:
            flag = "Home"
        elif CLUB in away:
            flag = "Away"
        else:
            flag = "-"
        fixtures.append({
            "Date": format_date(get_attr(row, "date")),            
            "Opposition": get_opposition(home, away, "highfield"),
            "Referee": get_attr(row, "referee"),
            "Competition": competition,
            "Ground": strip_html_entities(get_attr(row, "venue")),
            "Loc": flag,
            "Grade": get_grade(competition),
        })
    return fixtures

def main():
    today = datetime.today()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--from", dest="from_date", default=(today - timedelta(days=2)).strftime("%d-%m-%Y"),
                   help="start date dd/mm/yyyy (default: 2 days ago)")

    p.add_argument("--to", dest="to_date",
                        default=os.environ.get("TO_DATE") or DEFAULT_TO,
                        help="End date DD-MM-YYYY")
        
    p.add_argument("--all", action="store_true", help="include games that don't involve " + CLUB)
    p.add_argument("--allow-empty", action="store_true",
                   help="write the file even if zero fixtures were found")
    p.add_argument("--out", default=str(OUTPUT), help="output file (default: data/fixtures.json)")
    args = p.parse_args()
    print (args.from_date, args.to_date)

    fixtures = parse_fixtures(fetch_html(URL, args.from_date, args.to_date))
    print(f"Found {len(fixtures)} fixtures between {args.from_date} and {args.to_date}")
    if not args.all:
        fixtures = [f for f in fixtures if f["Loc"] != "-"]

    if not fixtures and not args.allow_empty:
        print("ERROR: no fixtures found; not overwriting existing data. "
          "Use --allow-empty if this is expected.", file=sys.stderr)
        return 1

    output = fixtures
    write_text(args.out, dump_json(output))
    print(f"Wrote {args.out}")
    return 0




if __name__ == "__main__":
    sys.exit(main())
