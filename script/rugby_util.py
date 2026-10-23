"""
Shared helpers for the Munster Rugby (SportLoMo) scripts:
    get-mr-fix.py  (fixtures)
    get-mr-res.py  (results)
"""
import html
import json
import os
import re
from datetime import datetime

import requests

# End date used when --to / TO_DATE is not supplied (DD-MM-YYYY)
DEFAULT_TO = "31-05-2027"

# Some sites reject the default python-requests User-Agent
USER_AGENT = "Mozilla/5.0 (compatible;  Google-Apps-Script)"


# ---------------------------------------------------------------- fetching ---

def fetch_html(url: str, from_date: str, to_date: str) -> str:
    """POST the date-range form the Apps Script posted and return the page HTML."""
    form_data = {
        "fdate": from_date,
        "tdate": to_date,
        "sort": "date",
        "btn": "",
    }
    # requests sends a dict via data= as application/x-www-form-urlencoded
    response = requests.post(url, data=form_data, headers={"User-Agent": USER_AGENT}, timeout=30)
    response.raise_for_status()
    return response.text


# ----------------------------------------------------------------- parsing ---

def strip_html_entities(text) -> str:
    """Decode entities such as &amp; and &#39; into plain characters; trims whitespace."""
    return html.unescape(text or "").strip()


def get_attr(row: str, name: str) -> str:
    """Equivalent of row.match(/data-<name>="(.*?)"/mi)[1]; '' if missing."""
    m = re.search(rf'data-{name}="(.*?)"', row, re.IGNORECASE | re.DOTALL)
    return m.group(1) if m else ""


def format_date(value: str) -> str:
    """'01 Oct 2026' -> '01/10/2026'. Returns the original text if it can't be parsed."""
    value = value.strip()
    for fmt in ("%d %b %Y", "%d %B %Y"):   # 'Oct' and 'October'
        try:
            return datetime.strptime(value, fmt).strftime("%d/%m/%Y")
        except ValueError:
            continue
    return value


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


# ------------------------------------------------------------------ grades ---

# Checked in order, first match wins. Matching is case-insensitive.
GRADE_EXCEPTIONS = [
    ("dennehy cup", "J2"),
    ("junior 2", "J2"),
    ("seconds", "J1"),
    ("senior clubs league", "J1"),
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


# ------------------------------------------------------------------ output ---

def dump_json(records) -> str:
    """Pretty-printed JSON text with a trailing newline.

    No timestamp on purpose: identical data => identical file => no commit.
    """
    return json.dumps(records, indent=2, ensure_ascii=False) + "\n"


def write_text(path, text: str) -> None:
    """Write text to `path`, creating the folder if needed."""
    path = str(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
