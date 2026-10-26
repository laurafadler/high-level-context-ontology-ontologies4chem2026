"""
The cabinets of the three PBA stock solutions: each is taken to stand with the salt it was made from (Meng Kong only
said where the salts are kept, 14.10.2026). Laura Fadler takes this assumption on 15.10.2026 - the texts of the stock
bottles and of task:assuming_pba_stock_solutions name her; nothing else changes.

The entry tools cannot change an existing entry. Runs once; commit the libraries afterwards.

Usage (from the repository root):
    python projects/pba_synthesis/curation/stock_solution_cabinets_20261015.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "generator" / "workflow" / "library_prerun"))
sys.path.insert(0, str(ROOT / "generator"))
import path_definitions  # noqa: E402
from fixed_reaction_from_template import LibraryFile  # noqa: E402

WHO = "Laura Fadler, 15.10.2026"
SOLUTIONS = ("stock_solution_potassium_ferrocyanide_01", "stock_solution_nickel_chloride_01", "stock_solution_manganese_nitrate_01")


def replace(entity, key, old, new):
    if old not in entity[key]:
        raise SystemExit(f"{entity['@id']}: text not found - already run? {old!r}")
    entity[key] = entity[key].replace(old, new)


def main():
    devices = LibraryFile(path_definitions.DEVICE_LIBRARY_PATH)
    d = devices.by_id()
    for name in SOLUTIONS:
        replace(d[f"device:{name}"], "rdfs:comment", "like its salt - are assumed", f"like its salt - are assumed ({WHO})")
    replace(d["task:assuming_pba_stock_solutions"], "schema:description", "their cabinets (with their salt)",
            f"their cabinets (with their salt - {WHO})")
    devices.save()
    print("written: device library - commit the libraries")


if __name__ == "__main__":
    main()
