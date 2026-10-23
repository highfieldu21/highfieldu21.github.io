#!/usr/bin/env python3
"""
Merge result files from several sources into the single file the website reads.

The two inputs are never changed:

    data/results.json       (Munster Rugby)   +
    data/results_ail.json   (sportsmanager.ie AIL)
        -> merge-results.py -> data/results-all.json

Rules
  * Files are read in priority order. The first source's values win.
  * Two records are the same game when they have the same Date and the same
    opposition (ignoring RFC/FC, capital letters, punctuation - see ALIASES).
  * For a matching game, any field the first source left empty is filled in
    from the later source, and any extra fields (e.g. KickOff) are added.
  * Games found in only one source are kept as they are.
  * Munster Rugby results often have a blank Score and Result, so the AIL
    values fill those in.
  * A missing input file is skipped with a warning. If nothing at all is
    loaded, or the result is empty, the existing output file is left alone.

Usage:
    python script/merge-results.py
    python script/merge-results.py --inputs data/a.json data/b.json --out data/results-all.json
"""
import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from rugby_util import dump_json, write_text

DEFAULT_INPUTS = ["data/results.json", "data/results_ail.json"]   # priority order
DEFAULT_OUT = "data/results-all.json"

# Different spellings of the same club -> one name (lower case). Add more as you meet them.
ALIASES = {
    "ucc": "university college cork",
    "cork con": "cork constitution",
}


def norm_team(name) -> str:
    """Reduce a team name to a comparable form: 'Garryowen FC' == 'garryowen'."""
    s = re.sub(r"[^\w\s]", " ", str(name or "").lower())
    s = re.sub(r"\b(1st|first)\s+xv\b", " ", s)
    second = bool(re.search(r"\b2nd\s+xv\b|\bseconds\b", s))   # a 2nd XV is a different team
    s = re.sub(r"\b2nd\s+xv\b|\bseconds\b", " ", s)
    s = re.sub(r"\b(rfc|fc|rugby|football|club|rfu)\b", " ", s)
    s = " ".join(s.split())
    s = ALIASES.get(s, s)
    return f"{s} 2nd" if second else s


def game_key(rec) -> tuple:
    return (str(rec.get("Date", "")).strip(), norm_team(rec.get("Opposition")))


def date_sort_key(rec):
    try:
        return datetime.strptime(str(rec.get("Date", "")).strip(), "%d/%m/%Y")
    except ValueError:
        return datetime.max


def is_empty(value) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def load(path: Path):
    """Return a list of records, or None if the file is missing or unusable."""
    if not path.exists():
        print(f"WARNING: {path} not found - skipping", file=sys.stderr)
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"WARNING: could not read {path}: {exc} - skipping", file=sys.stderr)
        return None
    if not isinstance(data, list):
        print(f"WARNING: {path} is not a JSON list - skipping", file=sys.stderr)
        return None
    return [r for r in data if isinstance(r, dict)]


def merge(sources):
    """sources: list of (name, records) in priority order. Returns (records, stats, warnings)."""
    merged = {}          # key -> record
    origin = {}          # key -> set of source names
    stats = {"merged_duplicates": 0}

    for name, records in sources:
        for rec in records:
            key = game_key(rec)
            if key not in merged:
                merged[key] = dict(rec)
                origin[key] = {name}
                continue
            base = merged[key]
            for field, value in rec.items():
                if field not in base or (is_empty(base[field]) and not is_empty(value)):
                    base[field] = value
            if name not in origin[key]:
                stats["merged_duplicates"] += 1
            origin[key].add(name)

    # Advisory only: same date and grade from different sources but different opposition names.
    warnings = []
    groups = {}
    for key, rec in merged.items():
        grade = str(rec.get("Grade", "")).strip()
        if grade:
            groups.setdefault((rec.get("Date"), grade), []).append(key)
    for (date, grade), keys in groups.items():
        for i in range(len(keys)):
            for j in range(i + 1, len(keys)):
                if origin[keys[i]].isdisjoint(origin[keys[j]]):
                    a, b = merged[keys[i]], merged[keys[j]]
                    warnings.append(
                        f"{date} {grade}: '{a.get('Opposition')}' and '{b.get('Opposition')}' "
                        f"come from different sources - same game? If so add an ALIASES entry."
                    )

    out = sorted(merged.values(), key=date_sort_key)
    return out, stats, warnings


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--inputs", nargs="+", default=DEFAULT_INPUTS,
                   help="result files in priority order (default: %(default)s)")
    p.add_argument("--out", default=DEFAULT_OUT, help="output file (default: %(default)s)")
    args = p.parse_args()

    sources = []
    for path in args.inputs:
        recs = load(Path(path))
        if recs is not None:
            print(f"Loaded {len(recs):>3} results from {path}")
            sources.append((Path(path).name, recs))

    if not sources:
        print("ERROR: no input files could be read; not overwriting existing data.", file=sys.stderr)
        return 1

    merged, stats, warnings = merge(sources)
    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)

    if not merged:
        print("ERROR: merged result is empty; not overwriting existing data.", file=sys.stderr)
        return 1

    write_text(args.out, dump_json(merged))
    print(f"Merged {stats['merged_duplicates']} duplicate game(s); wrote {len(merged)} results to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
