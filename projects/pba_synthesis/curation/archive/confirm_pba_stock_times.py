"""
The preparation times of the ferrocyanide and the manganese(II) nitrate stock solution (08.10.2026, Meng Kong, given by
Laura Fadler, questions_meng_pba_outcomes.md, N17): nothing of them is in the files, so they are taken to have been made
at the same time as the other stock solutions - as the DUMMY times of 07.10.2026 already say (7 April 2026, right after
the nickel(II) chloride solution). The times stay; their texts no longer call them a dummy but an assumption with its
reason. The other dummies of these entries (kind of bottle, cabinet, label) are not answered by N17 and stay.

The entry tools cannot change an existing entry (type 'prepared_container' would need an update mode). Runs once.
Commit the libraries afterwards.

Usage (from the repository root):
    python projects/pba_synthesis/curation/confirm_pba_stock_times.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "generator" / "workflow" / "library_prerun"))
sys.path.insert(0, str(ROOT / "generator"))
import path_definitions  # noqa: E402
from fixed_reaction_from_template import LibraryFile  # noqa: E402

DUMMY = "DUMMY (Claude Code, 07.10.2026; allowed for PBA by Laura Fadler, 06.10.2026) - ask Meng Kong"
WHY = "assumed: nothing of it is in the files, so it was made at the same time as the other stock solutions (Meng Kong, 08.10.2026, N17)"
SOLUTIONS = ("stock_solution_potassium_ferrocyanide_01", "stock_solution_manganese_nitrate_01")


def main():
    materials = LibraryFile(path_definitions.MATERIAL_LIBRARY_PATH)
    by_id = materials.by_id()
    changed = 0
    for name in SOLUTIONS:
        task = f"task:preparing_{name}"
        texts = [(by_id[task], "schema:description", f"(the times are a {DUMMY})", f"(the times are {WHY})"),
                 (by_id[f"{task}_StartTime_Reference_1"], "rdfs:comment", f"Start of the preparation - {DUMMY}: taken as right after",
                  f"Start of the preparation - {WHY}: taken as right after"),
                 (by_id[f"{task}_EndTime_Reference_1"], "rdfs:comment", f"End of the preparation - {DUMMY}: as long as",
                  f"End of the preparation - {WHY}: as long as")]
        for entity, key, old, new in texts:
            if old in entity[key]:
                entity[key] = entity[key].replace(old, new)
                changed += 1
    if not changed:
        print("nothing to change - the times are confirmed already")
        return
    assert changed == 6, changed
    materials.save()
    print(f"{changed} texts changed")


if __name__ == "__main__":
    main()
