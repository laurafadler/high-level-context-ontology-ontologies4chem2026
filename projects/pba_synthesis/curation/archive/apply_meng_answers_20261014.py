"""
Meng Kong's answers of 14.10.2026 to the remaining PBA questions (given by Laura Fadler the same day) in the libraries:

- Stock solutions: only the concentration was taken down - the ferrocyanide one, 0.05 M, is confirmed; weighed-in
  amounts, volumes, labels and times were not tracked, the times stay assumed ("make assumptions about when they were
  made"). The manganese(II) nitrate solution has the concentration of the nickel(II) chloride one for the 1:1 ratio,
  not recorded - entered as an assumption, 0.01 mol/L of manganese(II) ions.
- The stock solutions were kept in larger bottles, "likely 500 ml", for several runs: the three stock bottles become
  exemplars of device:glass_bottle_500mL instead of device:glass_bottle_250mL (glass stays assumed).
- The salts: supplier, lot and receipt were not tracked - the assumptions stay, no longer marked as dummies to be
  asked. Metal chlorides and nitrates are kept in one cabinet of Lab L2.08 (lab:L208_Chemicals_Cabinet), ferrocyanide
  and ferricyanide in another (lab:L208_Cyanoferrate_Cabinet, entered with the entry tool from
  library_entries/cabinet_20261014_1828.yaml). The stock solutions are taken to stand with their salt (assumed).
- The deionised water of Lab 208: nothing more known (the technician could be asked) - the assumption stays.

The entry tools cannot change an existing entry. Runs once; commit the libraries afterwards.

Usage (from the repository root):
    python projects/pba_synthesis/curation/apply_meng_answers_20261014.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "generator" / "workflow" / "library_prerun"))
sys.path.insert(0, str(ROOT / "generator"))
import path_definitions  # noqa: E402
from fixed_reaction_from_template import LibraryFile  # noqa: E402

MENG = "Meng Kong, 14.10.2026"
DUMMY = "DUMMY (Claude Code, 07.10.2026; allowed for PBA by Laura Fadler, 06.10.2026) - ask Meng Kong"
METAL_CABINET, CYANO_CABINET = "lab:L208_Chemicals_Cabinet", "lab:L208_Cyanoferrate_Cabinet"
SALTS = {"bottle_potassium_ferrocyanide_trihydrate_01": CYANO_CABINET,
         "bottle_nickel_chloride_hexahydrate_01": METAL_CABINET,
         "bottle_manganese_nitrate_tetrahydrate_01": METAL_CABINET}
SOLUTIONS = {"stock_solution_potassium_ferrocyanide_01": CYANO_CABINET,
             "stock_solution_nickel_chloride_01": METAL_CABINET,
             "stock_solution_manganese_nitrate_01": METAL_CABINET}
CABINET_WORDS = {METAL_CABINET: "the cabinet for metal chlorides and nitrates", CYANO_CABINET: "the cabinet for ferrocyanide and ferricyanide"}
MN = "material:stock_solution_manganese_nitrate_01_Content_Phase_Manganese2PlusIon"


def ref(entity_id):
    return {"@id": entity_id}


def replace(entity, key, old, new):
    text = entity[key]
    if old not in text:
        raise SystemExit(f"{entity['@id']} {key}: text not found - {old[:70]!r}")
    entity[key] = text.replace(old, new)


def main():
    devices = LibraryFile(path_definitions.DEVICE_LIBRARY_PATH)
    materials = LibraryFile(path_definitions.MATERIAL_LIBRARY_PATH)
    organizations = LibraryFile(path_definitions.ORGANIZATION_LIBRARY_PATH)
    d, m, o = devices.by_id(), materials.by_id(), organizations.by_id()
    if CYANO_CABINET not in o:
        raise SystemExit(f"{CYANO_CABINET} is missing - write library_entries/cabinet_20261014_1828.yaml first.")
    if f"{MN}_Concentration" in m:
        raise SystemExit("Already run - the manganese(II) concentration exists.")

    # The salts: their cabinet, the dummies become assumptions.
    for name, cabinet in SALTS.items():
        device = d[f"device:{name}"]
        device["cpo:locatedInsideOf"] = ref(cabinet)
        replace(device, "rdfs:comment", f"the size and the cabinet in Lab 208 are assumed ({DUMMY})",
                f"the size is assumed, not recorded ({MENG}); it stands in {CABINET_WORDS[cabinet]} of Lab 208 ({MENG})")
        comment = device["schema:comment"]
        for old, new in ((f"container kind, place, lot and receipt not known - {DUMMY}",
                          f"container kind, lot and receipt not recorded and assumed ({MENG}); the cabinet given by {MENG}"),
                         (f"kind of container assumed, receipt and place not known - {DUMMY}",
                          f"kind of container and receipt not recorded and assumed ({MENG}); the cabinet given by {MENG}")):
            comment = comment.replace(old, new)
        device["schema:comment"] = comment
        for part in ("StartTime", "EndTime"):
            replace(m[f"task:receiving_{name}_{part}_Reference_1"], "rdfs:comment", DUMMY, f"not recorded, assumed ({MENG})")
        replace(m[f"task:receiving_{name}"], "schema:description", "(dummy times)", f"(assumed times - not recorded, {MENG})")
        content = m[f"material:{name}_Content"]
        if DUMMY in content.get("cpo:hasLotNumber", ""):
            content["cpo:hasLotNumber"] = f"not recorded ({MENG})"
    replace(d["task:assuming_pba_stock_entries"], "schema:description",
            f"Nothing is recorded yet of the containers the three hydrates are weighed from: their kind, place, lot and receipt are dummy values until Meng Kong gives the real ones - {DUMMY}.",
            f"Nothing is recorded of the containers the three hydrates are weighed from: their kind, lot and receipt are not tracked ({MENG}) and assumed; their cabinets are given by {MENG}.")
    cabinet = o[METAL_CABINET]
    cabinet["rdfs:comment"] = (f"Where the metal chlorides and nitrates of the PBA series are kept - ferrocyanide and ferricyanide "
                               f"stand in {CYANO_CABINET} ({MENG}).")
    replace(cabinet, "schema:comment", f"container kind, place, lot and receipt not known - {DUMMY}",
            f"what is kept here given by {MENG}")

    # The stock solutions: 500 mL bottles, the cabinet of their salt.
    for name, cabinet in SOLUTIONS.items():
        device = d[f"device:{name}"]
        device["hlo:specializationOf"] = ref("device:glass_bottle_500mL")
        device["cpo:locatedInsideOf"] = ref(cabinet)
        replace(device, "rdfs:comment",
                f"of the kind device:glass_bottle_250mL (form, glass and opening come from there) - the kind is assumed, as is its cabinet in Lab 208 ({DUMMY})",
                f"of the kind device:glass_bottle_500mL (form, glass and opening come from there) - the stock solutions were kept in larger "
                f"bottles, likely 500 mL, for several runs ({MENG}); glass and the cabinet - {CABINET_WORDS[cabinet]}, like its salt - are assumed")
        for entity in (m[f"material:{name}_Content"], m[f"material:{name}_Content_Phase"]):
            entity["cpo:fillsForm"] = ref("device:glass_bottle_500mL_Cavity")
    replace(d["task:assuming_pba_stock_solutions"], "schema:description",
            f"Of the three stock solutions only the nickel(II) chloride one has a preparation record. The kind of their bottles, their cabinet and the preparation of the other two are assumed - {DUMMY}.",
            "Of the three stock solutions only the nickel(II) chloride one has a preparation record; of the ferrocyanide one only "
            f"the concentration was taken down ({MENG}). Assumed: their bottles (glass; 500 mL, 'likely' - {MENG}), their cabinets "
            "(with their salt), the preparation times of the other two (made at the same time as the nickel one - Meng Kong, "
            f"08.10.2026) and the concentration of the manganese(II) nitrate one (that of the nickel one, for the 1:1 ratio - {MENG}).")

    # Ferrocyanide: the concentration confirmed, the rest not tracked.
    ferro = "stock_solution_potassium_ferrocyanide_01"
    replace(m[f"material:{ferro}_Content_Phase_FerrocyanideIon_Concentration_Reference_1"], "rdfs:comment",
            "(Laura Fadler, 07.10.2026: taken from Meng Kong's records; to be confirmed by Meng Kong)",
            f"(taken from Meng Kong's records by Laura Fadler, 07.10.2026; confirmed by {MENG}: only the concentration was taken down)")
    m[f"material:{ferro}_Content"]["cpo:hasLotNumber"] = (
        "Ferrocyanide 0.05M Li (the stock reagent ID in Meng Kong's synthesis record template; what the bottle itself says is "
        f"not recorded - {MENG})")
    for name, what in ((ferro, f"Only the concentration was taken down ({MENG}); amounts, label and times were not tracked"),
                       ("stock_solution_manganese_nitrate_01", f"Nothing of it was tracked ({MENG}) - amounts, concentration, label and times")):
        replace(m[f"task:preparing_{name}"], "schema:description",
                "Nothing of it is recorded - amounts, label and times are not known (the times are assumed: nothing of it is in the "
                "files, so it was made at the same time as the other stock solutions (Meng Kong, 08.10.2026, N17)).",
                f"{what}; the times are assumed: made at the same time as the other stock solutions (Meng Kong, 08.10.2026).")
        for part in ("StartTime", "EndTime"):
            replace(m[f"task:preparing_{name}_{part}_Reference_1"], "rdfs:comment", "(Meng Kong, 08.10.2026, N17)",
                    f"(Meng Kong, 08.10.2026; {MENG}: make assumptions about when they were made)")
    m["material:stock_solution_manganese_nitrate_01_Content"]["cpo:hasLotNumber"] = f"label not recorded ({MENG})"

    # Manganese(II) nitrate: the concentration of the nickel(II) chloride solution, assumed.
    reference = f"{MN}_Concentration_Reference_1"
    m[MN]["cpo:hasConcentration"] = ref(f"{MN}_Concentration")
    materials.graph.extend([
        {"@id": f"{MN}_Concentration", "@type": ["cpo:ProcessVariable", "hlo:Fixed", "hlo:Actual"],
         "cpo:isProcessVariableOf": ref(MN), "hlo:hasReference": ref(reference)},
        {"@id": reference, "@type": ["cpo:ProcessVariable", "hlo:Reference"],
         "qudt:hasQuantityKind": ref("quantitykind:AmountOfSubstanceConcentration"), "hlo:hasReferenceType": ref("hlo:Assumed"),
         "rdfs:comment": ("Concentration of the stock solution, 0.01 M of manganese(II) nitrate - one manganese(II) ion per formula "
                          "unit: not recorded, assumed to be that of the nickel(II) chloride solution for the 1:1 ratio of the two "
                          f"metals ({MENG}: 'put it as an assumption')."),
         "qudt:value": {"@value": "0.01", "@type": "xsd:decimal"}, "qudt:hasUnit": ref("unit:MOL-PER-L"),
         "cpo:hasDeterminationTask": ref("task:assuming_pba_stock_solutions")}])
    d["task:assuming_pba_stock_solutions"]["cpo:determines"].append(ref(reference))

    # The water line of Lab 208: nothing more known.
    water = d["device:L208_DI_water_supply"]
    replace(water, "rdfs:comment", f"({DUMMY})", f"(nothing more known - {MENG}; the technician of the lab could be asked)")
    replace(water, "schema:comment", f"are assumed - {DUMMY}", f"are assumed (nothing more known - {MENG})")
    replace(d["task:assuming_L208_DI_water_supply"], "schema:description", DUMMY,
            f"Nothing more is known of the line ({MENG}; the technician of the lab could be asked).")

    for library in (devices, materials, organizations):
        library.save()
    print("written: device, material and organization library - commit the libraries")


if __name__ == "__main__":
    main()
