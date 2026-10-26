"""
"Everything still empty is unknown" - the last step before building.

Nothing is declared unknown in advance. Everything known goes into the sheet
first - by hand, with a script or an agent - and only then does a person say that the rest really
is unknown. This script writes that statement at every field it concerns, with who said it and
when, instead of once for the whole sheet:

- the empty values of the section "values" (no value, column or bounds, no kind) leave it and go,
  per place and experiment, to the section "unknown" - "none: [density, mass, ...]" ("values"
  shows what is known, "unknown" what is explicitly not - so that one still sees
  where something might have been forgotten);
- an open question of the section "open" without an answer gets "answer: ''" (none) - but only
  where "none" is a valid answer (a list); a question that needs a real answer (one of the
  options) is left open and reported.

Only these entries change; everything else in the sheet stays as it is, character for character.

Usage (from the repository root):
    python generator/workflow/close_sheet.py projects/<crate_identifier>/setup.yaml --by "Laura Fadler" [--dry-run]
"""
import argparse
import re
import sys
from datetime import date
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from helpers.safe_write import write_atomic  # noqa: E402
from interfaces.eln.sheet_text import append_to_section, render_entries  # noqa: E402

UNKNOWN_HEADER = ("unknown:                                       # explicitly unknown (close_sheet.py), per place and experiment;\n"
                  "                                               # if something is known after all: strike the quantity here, enter the value under values\n")
_ENTRY = re.compile(r"^  - .*?(?=^  - |^\S|\Z)", flags=re.MULTILINE | re.DOTALL)


def _section(text: str, name: str):
    """(start, end) of a top-level section of the sheet text, or None."""
    start = re.search(rf"^{name}:", text, flags=re.MULTILINE)
    if start is None:
        return None
    following = re.search(r"^[A-Za-z_]+:", text[start.end():], flags=re.MULTILINE)
    return start.start(), (start.end() + following.start()) if following else len(text)


def _closed_entries(text: str, name: str, close) -> tuple:
    """The text with every entry of the section passed through close(entry text, parsed entry)."""
    span = _section(text, name)
    if span is None:
        return text, 0
    body = text[span[0]:span[1]]
    changed = 0

    def replace(match):
        nonlocal changed
        block = match.group(0)
        entry = (yaml.safe_load("\n".join(line[2:] if line.startswith("  ") else line for line in block.splitlines())) or [None])[0]
        new = close(block, entry) if isinstance(entry, dict) else block
        changed += new != block
        return new

    body = _ENTRY.sub(replace, body)
    return text[:span[0]] + body + text[span[1]:], changed


def close(sheet: Path, by: str, dry_run: bool = False) -> dict:
    text = sheet.read_text(encoding="utf-8")
    statement = f"C: nothing more is known - stated by {by} on {date.today().strftime('%d.%m.%Y')}"
    still_open = []
    unknown = {}            # (at, of, place, occurrence, experiment) -> [quantity, ...]

    def close_value(block, entry):
        if entry.get("kind") is not None or any(entry.get(k) is not None for k in ("value", "column", "lower", "upper")):
            return block
        unknown.setdefault((entry.get("at"), entry.get("of"), entry.get("place"), entry.get("occurrence"),
                            entry.get("experiment")), []).append(entry.get("quantity"))
        return ""

    def close_occurrence(block, entry):
        # An open scaffold (null, from open_questions.py) becomes "nothing known" ([]) - with name and date.
        fields = ("phases", "interfaces", "reactions", "energy_fields", "transfers")
        if not any(field in entry and (entry[field] is None or (isinstance(entry[field], dict) and None in entry[field].values()))
                   for field in fields):
            return block
        closed = {}
        for field in fields:
            if field in entry:
                value = entry[field]
                closed[field] = [] if value is None else ({p: v for p, v in value.items() if v is not None}
                                                          if isinstance(value, dict) else value)
        closed["experiment"] = entry.get("experiment")
        closed["source"] = statement
        return render_entries([closed])

    def close_question(block, entry):
        if entry.get("answer") is not None:
            return block
        if not entry.get("several") or entry.get("required"):
            still_open.append(f"{entry.get('about', '')}: {entry.get('question', entry.get('key'))}")
            return block
        block = re.sub(r"^    answer: null$", "    answer: ''", block, count=1, flags=re.MULTILINE)
        return re.sub(r"^    source: null$", f"    source: '{statement}'", block, count=1, flags=re.MULTILINE)

    text, values = _closed_entries(text, "values", close_value)
    text, _occurrences = _closed_entries(text, "occurrences", close_occurrence)
    text, questions = _closed_entries(text, "open", close_question)
    grouped = []
    for (at, of, place, occurrence, experiment), quantities in unknown.items():
        item = {"at": at}
        if of:
            item["of"] = of
        if place:
            item["place"] = place
        if occurrence:
            item["occurrence"] = occurrence
        if experiment:
            item["experiment"] = experiment
        item.update({"none": quantities, "source": statement})
        grouped.append(item)
    if not dry_run:
        write_atomic(sheet, text.encode("utf-8"))
        append_to_section(sheet, "unknown", UNKNOWN_HEADER, grouped)
    return {"values": values, "places": len(grouped), "questions": questions, "still_open": still_open}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("sheet", type=Path)
    parser.add_argument("--by", required=True, help="who states that the rest is unknown")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = close(args.sheet, args.by, args.dry_run)
    print(f"{'Would move' if args.dry_run else 'Moved'} {result['values']} empty value(s) to 'unknown' ({result['places']} "
          f"place(s)), {result['questions']} open question(s) answered with none.")
    if result["still_open"]:
        print(f"\nStill open - they need an answer, 'none' is not one of their options ({len(result['still_open'])}):")
        for line in result["still_open"]:
            print(f"  - {line}")
    return 1 if result["still_open"] else 0


if __name__ == "__main__":
    sys.exit(main())
