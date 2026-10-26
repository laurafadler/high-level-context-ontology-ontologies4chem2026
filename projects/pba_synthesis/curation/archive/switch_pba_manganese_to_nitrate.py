"""
Manganese(II) nitrate instead of manganese(II) chloride in the PBA series (08.10.2026, Laura Fadler and Meng Kong,
questions_meng_pba_outcomes.md, N16): the manganese salt of 10 April 2026 is not recorded; the only one the files name
is Mn(NO3)2 (the run log of 12.03.2026, input/0312/Mn2+ferro.csv). The nitrate is taken, its tetrahydrate assumed.
The substance and the nitrate ion were entered before (curation/library_entries/substance_20261008_1741.yaml).

Changes, in all libraries (main files and details):
- IDs: bottle_manganese_chloride_tetrahydrate_01 -> bottle_manganese_nitrate_tetrahydrate_01,
  stock_solution_manganese_chloride_01 -> stock_solution_manganese_nitrate_01,
  ManganeseIIChlorideTetrahydrate -> ManganeseIINitrateTetrahydrate (species, dissolution reaction) - their commissioning,
  preparation and usage histories stay as they are;
- the chloride ion of the manganese stock solution and of its dissolution becomes the nitrate ion (2 NO3-);
- chem:ManganeseIIChlorideTetrahydrate goes, with its molar mass and the reference of it (taken out of
  task:looking_up_pba_ions_and_hydrates, which says so);
- names and texts say nitrate; every changed entry says why.
Runs once (stops when nothing is left to change). Commit the libraries afterwards.

Usage (from the repository root):
    python projects/pba_synthesis/curation/switch_pba_manganese_to_nitrate.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "generator" / "workflow" / "library_prerun"))
sys.path.insert(0, str(ROOT / "generator"))
import path_definitions  # noqa: E402
from fixed_reaction_from_template import LibraryFile  # noqa: E402

RENAMES = [("bottle_manganese_chloride_tetrahydrate_01", "bottle_manganese_nitrate_tetrahydrate_01"),
           ("stock_solution_manganese_chloride_01", "stock_solution_manganese_nitrate_01"),
           ("ManganeseIIChlorideTetrahydrate", "ManganeseIINitrateTetrahydrate")]
OLD_SALT = "chem:ManganeseIIChlorideTetrahydrate"
GONE = {OLD_SALT, f"{OLD_SALT}_MolarMass", f"{OLD_SALT}_MolarMass_Reference_1"}
LOOKUP = "task:looking_up_pba_ions_and_hydrates"
# The chloride ion where it came from the manganese salt -> the nitrate ion (IDs after the renames above).
IONS = {"material:stock_solution_manganese_nitrate_01_Content_Phase_ChlorideIon":
        "material:stock_solution_manganese_nitrate_01_Content_Phase_NitrateIon",
        "reaction:Dissolution_ManganeseIINitrateTetrahydrate_Participant_ChlorideIon":
        "reaction:Dissolution_ManganeseIINitrateTetrahydrate_Participant_NitrateIon"}
TEXTS = [("MnCl2*4H2O > Mn2+ + 2 Cl- + 4 H2O", "Mn(NO3)2*4H2O > Mn2+ + 2 NO3- + 4 H2O"),
         ("manganese(II) chloride", "manganese(II) nitrate"), ("Manganese(II) chloride", "Manganese(II) nitrate")]
WHY = ("Manganese(II) nitrate instead of the chloride since 08.10.2026 (projects/pba_synthesis/curation/"
       "switch_pba_manganese_to_nitrate.py): the salt of 10 April 2026 is not recorded, the only one the files name is "
       "Mn(NO3)2 (run log of 12.03.2026); the tetrahydrate is assumed - Laura Fadler and Meng Kong, 08.10.2026 "
       "(questions_meng_pba_outcomes.md, N16).")
PRODUCT = "chem:NickelManganeseHexacyanoferrateII"
LIBRARIES = [path_definitions.CHEMICAL_ENTITY_LIBRARY_PATH, path_definitions.REACTION_LIBRARY_PATH,
             path_definitions.DEVICE_LIBRARY_PATH, path_definitions.MATERIAL_LIBRARY_PATH]


def renamed(value):
    """Every string inside value with the renames applied (IDs, references and texts alike)."""
    if isinstance(value, str):
        for old, new in RENAMES:
            value = value.replace(old, new)
        return IONS.get(value, value)
    if isinstance(value, list):
        return [renamed(v) for v in value]
    if isinstance(value, dict):
        return {k: renamed(v) for k, v in value.items()}
    return value


def note(entity, text):
    key = "schema:comment" if "schema:comment" in entity else "rdfs:comment"
    entity[key] = (entity.get(key, "") + " " + text).strip()


def main():
    files = [LibraryFile(path) for path in LIBRARIES]
    if not any(re.search(r"manganese_chloride|ManganeseIIChloride", str(f.graph)) for f in files):
        print("nothing to change - manganese(II) chloride is gone already")
        return
    changed = 0
    for library in files:
        kept = []
        for entity in library.graph:
            if entity.get("@id") in GONE:
                changed += 1
                continue
            if entity.get("@id") == LOOKUP:
                determines = entity.get("cpo:determines", [])
                entity["cpo:determines"] = [r for r in determines if r.get("@id") not in GONE]
                entity["schema:description"] += (" Manganese(II) chloride tetrahydrate was removed on 08.10.2026 with its "
                                                 "molar mass: " + WHY)
            new = renamed(entity)
            touched = new != entity
            own = new["@id"] != entity["@id"]      # a renamed entry - not one that only points at one
            for old_text, new_text in TEXTS:
                for key in ("schema:name", "schema:description", "schema:comment", "rdfs:comment"):
                    if isinstance(new.get(key), str) and own:
                        new[key] = new[key].replace(old_text, new_text)
            if new["@id"] in IONS.values():
                chem_key = "hlo:specializationOf" if "hlo:specializationOf" in new else "dcterms:hasPart"
                new[chem_key] = {"@id": "chem:NitrateIon"}
                if "schema:name" in new:
                    new["schema:name"] = "Nitrate ion"
            if new["@id"] == PRODUCT:
                new["schema:comment"] = new["schema:comment"].replace(
                    "nickel(II) and manganese(II) chloride", "nickel(II) chloride and manganese(II) nitrate")
                touched = own = True
            if own and new["@id"].split(":", 1)[0] in ("device", "material", "reaction", "chem") and (
                    "schema:comment" in new or "rdfs:comment" in new):
                note(new, WHY)
            changed += touched
            kept.append(new)
        library.graph[:] = kept
    left = [str(p.name) for p, f in zip(LIBRARIES, files) if re.search(r"manganese_chloride|ManganeseIIChloride", str(f.graph))]
    if left:
        sys.exit(f"still named in {left} - nothing written")
    for library in files:
        library.save()
    print(f"{changed} entries changed or removed")


if __name__ == "__main__":
    main()
