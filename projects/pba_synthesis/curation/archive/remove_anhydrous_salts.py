"""
Remove the nine anhydrous salts of the PBA series from the chemical entity library (07.10.2026, released by
Laura Fadler on 06.10.2026): K4[Fe(CN)6], K3[Fe(CN)6], KCl and the six metal(II) chlorides, added by
add_pba_chemistry.py on 05.10.2026. Since the chemistry became net-ionic (add_pba_ions.py, cbf37c6) no
reaction, library entry or sheet uses them - the salts are weighed in as hydrates, in solution the ions count.

Removes each salt with its molar mass and the reference of it, takes the references out of
task:looking_up_pba_substances (which keeps the one of nickel hexacyanoferrate(II)) and says so in its
description. Runs once (stops when the salts are gone). Commit the library afterwards.

Usage (from the repository root):
    python projects/pba_synthesis/curation/remove_anhydrous_salts.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "generator" / "workflow" / "library_prerun"))
sys.path.insert(0, str(ROOT / "generator"))
import path_definitions  # noqa: E402
from fixed_reaction_from_template import LibraryFile  # noqa: E402

SALTS = ["PotassiumFerrocyanide", "PotassiumFerricyanide", "PotassiumChloride", "ManganeseIIChloride", "IronIIChloride",
         "CobaltIIChloride", "NickelIIChloride", "CopperIIChloride", "ZincChloride"]
OWN = re.compile(r"^chem:(%s)(_MolarMass(_Reference_1)?)?$" % "|".join(SALTS))
LOOKUP = "task:looking_up_pba_substances"
NOTE = (" The nine anhydrous salts (hexacyanoferrates, metal chlorides, potassium chloride) were removed on 07.10.2026 "
        "(projects/pba_synthesis/curation/remove_anhydrous_salts.py): unused since the chemistry became net-ionic - "
        "the salts are weighed in as hydrates.")


def main():
    library = LibraryFile(path_definitions.CHEMICAL_ENTITY_LIBRARY_PATH)
    gone = {e["@id"] for e in library.graph if OWN.match(e["@id"])}
    if not gone:
        print("chemical entity library: the anhydrous salts are gone already - nothing to do")
        return
    assert len(gone) == 3 * len(SALTS), sorted(gone)
    library.graph[:] = [e for e in library.graph if e["@id"] not in gone]
    task = library.by_id()[LOOKUP]
    task["cpo:determines"] = [d for d in task["cpo:determines"] if d["@id"] not in gone]
    task["schema:description"] += NOTE
    library.save()
    print(f"chemical entity library: -{len(gone)}")


if __name__ == "__main__":
    main()
