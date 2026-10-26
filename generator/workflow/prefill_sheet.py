"""
Pre-fill a setup sheet with the values of its ELN core files.

The sheet names its core files (series.eln_records) and says where things are (materials, uncontained_streams,
reactions); this script places the values of the core files there (interfaces/eln/sheet_values.py)
and appends them to the section "values" at the end of the sheet - with their ELN source, and
without a reading ("kind": measured, planned ...), which only a person can give.

It only ever appends to the section (interfaces/eln/sheet_text.py); nothing in the sheet is
rewritten, so its comments stay as they are:
- a value the section has already (same place, substance, experiment, quantity) is left alone. If
  the ELN now says something else, that is reported - and so is a value somebody overwrote in the
  sheet on purpose (its source no longer starts with "E:"), which is kept.
- substances of the core files that have no place in the sheet, or no entry in the Chemical
  Entity Library, are reported: they need an uncontained stream or material in the sheet, or a library entry first
  (library pre-run).

Usage (from the repository root):
    python generator/workflow/prefill_sheet.py projects/<crate_identifier>/setup.yaml [--dry-run]
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "generator"))

from interfaces.eln.adapter import SetupAdapter  # noqa: E402
from interfaces.eln.sheet_values import eln_entries  # noqa: E402
from interfaces.eln.sheet_text import append_to_section  # noqa: E402

SECTION_HEADER = ("values:                                        # values: pre-filled from the ELN (prefill_sheet.py) and by hand;\n"
                  "                                               # kind (measured, planned ...) is set by a person\n")


def _norm(text) -> str:
    return "".join(c for c in str(text or "").lower() if c.isalnum())


def identity(entry: dict) -> tuple:
    return (_norm(entry.get("at")), _norm(entry.get("of")), str(entry.get("experiment")), _norm(entry.get("quantity")))


def shown(entry: dict) -> dict:
    """An entry in the order of the sheet; "kind" stays visible, empty."""
    result = {key: entry[key] for key in ("at", "of", "experiment", "quantity", "value", "unit") if key in entry}
    result["kind"] = entry.get("kind")
    for key in ("exact", "group", "source"):
        if key in entry:
            result[key] = entry[key]
    return result


def prefill(sheet_path: Path, dry_run: bool = False) -> dict:
    sheet_path = Path(sheet_path)
    adapter = SetupAdapter(sheet_path, ROOT)
    entries, unplaced = eln_entries(adapter)
    existing = {identity(e): e for e in adapter.sheet.get("values") or []}
    new, changed, overwritten = [], [], []
    for entry in entries:
        old = existing.get(identity(entry))
        if old is None:
            new.append(entry)
            continue
        # A unit the ELN does not name and a person added is no deviation.
        same = old.get("value") == entry.get("value") and (not entry.get("unit") or _norm(old.get("unit")) == _norm(entry.get("unit")))
        source = (old.get("source") or {}).get("value", "") if isinstance(old.get("source"), dict) else str(old.get("source") or "")
        where = f"{entry['at']}{' / ' + entry['of'] if entry.get('of') else ''} / {entry['quantity']} (experiment {entry['experiment']})"
        if not str(source).startswith("E:"):
            overwritten.append(f"{where}: sheet {old.get('value')} {old.get('unit') or ''} (kept, source {source!r}), "
                               f"ELN {entry.get('value')} {entry.get('unit') or ''}")
        elif not same:
            changed.append(f"{where}: sheet {old.get('value')} {old.get('unit') or ''}, ELN now {entry.get('value')} {entry.get('unit') or ''}")

    if not dry_run:
        append_to_section(sheet_path, "values", SECTION_HEADER, [shown(entry) for entry in new])
    return {"new": new, "changed": changed, "overwritten": overwritten, "unplaced": unplaced}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("sheet", type=Path)
    parser.add_argument("--dry-run", action="store_true", help="only report, write nothing")
    args = parser.parse_args()
    result = prefill(args.sheet, args.dry_run)
    print(f"{'Would add' if args.dry_run else 'Added'} {len(result['new'])} value(s) to {args.sheet}.")
    for title, key in (("The ELN says something else now (sheet unchanged)", "changed"),
                       ("Overwritten in the sheet, kept", "overwritten"),
                       ("Substances without a place in the sheet or the library", "unplaced")):
        if result[key]:
            print(f"\n{title} ({len(result[key])}):")
            for line in result[key]:
                print(f"  - {line}")
    return 1 if result["changed"] or result["unplaced"] else 0


if __name__ == "__main__":
    sys.exit(main())
