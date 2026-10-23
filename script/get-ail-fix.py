#!/usr/bin/env python3
"""
Download the fixture feed from sportsmanager.ie and save the JSON it returns.

No conversion and no merging: the response is saved as received (just
pretty-printed so changes show up cleanly in git) to data/fixtures_ail.json,
so you can look at it before deciding what to do with it.

Usage:
    python script/get-ail-fix.py
    python script/get-ail-fix.py --from 2026-09-01 --to 2027-04-30
    python script/get-ail-fix.py --url "https://sportsmanager.ie/dataFeed/index.php?..."   # exact URL
    python script/get-ail-fix.py --dry-run          # show what came back, write nothing

Dates are YYYY-MM-DD (the feed's format, unlike the DD-MM-YYYY the other scripts use).
"""
import argparse
import sys

import requests

from rugby_util import dump_json, write_text

BASE_URL = "https://sportsmanager.ie/dataFeed/index.php"
DEFAULT_FROM = "2026-09-01"
DEFAULT_TO = "2027-04-30"
USER_ID = "7533"
COMPETITION_ID = "215685"
OUTPUT = "data/fixtures_ail.json"

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


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--from", dest="from_date", default=DEFAULT_FROM, help="start date YYYY-MM-DD")
    p.add_argument("--to", dest="to_date", default=DEFAULT_TO, help="end date YYYY-MM-DD")
    p.add_argument("--user-id", default=USER_ID)
    p.add_argument("--competition-id", default=COMPETITION_ID)
    p.add_argument("--url", help="use this exact URL instead of building one (ignores the options above)")
    p.add_argument("--out", default=OUTPUT, help="output file (default: %(default)s)")
    p.add_argument("--allow-empty", action="store_true", help="write the file even if the feed returned nothing")
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

    if not data and not args.allow_empty:
        print("ERROR: the feed returned nothing; not overwriting existing data. "
              "Use --allow-empty if this is expected.", file=sys.stderr)
        return 1

    text = dump_json(data)
    if args.dry_run:
        print(text[:1500])
        return 0

    write_text(args.out, text)
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
