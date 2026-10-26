"""
The potassium ferrocyanide stock solution of the series pba_synthesis gets its label and its target concentration
(07.10.2026): Meng Kong's synthesis record template "ferro ni2+ co2+ zn2+.csv" (Data Dictionary/inbox, another
experiment of the project) names the stock reagent for reagent A "Ferrocyanide 0.05M Li"; Chuyue Li made each stock
solution once, so it is taken as the one of this series (Laura Fadler, 07.10.2026; to be confirmed by Meng Kong).
The notes of 12.03.2026 (K1-Li-Data/NOTE.xlsx) give 0.05 M for the ferrocyanide as well. Its preparation times
stay dummies. Commit the libraries afterwards.

Usage (from the repository root):
    python projects/pba_synthesis/curation/update_pba_ferrocyanide_stock.py
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "generator" / "workflow" / "library_prerun"))
sys.path.insert(0, str(ROOT / "generator"))
import path_definitions  # noqa: E402
from fixed_reaction_from_template import LibraryFile  # noqa: E402

NAME = "stock_solution_potassium_ferrocyanide_01"
LABEL = "Ferrocyanide 0.05M Li"
SOURCE = ("Synthesis record template 'ferro ni2+ co2+ zn2+.csv' of Meng Kong (Li-K1-PBA, Data Dictionary/inbox): stock "
          "reagent ID for reagent A 'Ferrocyanide 0.05M Li'; notes of 12.03.2026 (K1-Li-Data/NOTE.xlsx): 'Sample A (0.05M) "
          "ferrocyanide'")
TASK = f"task:preparing_{NAME}"


def main():
    devices = LibraryFile(path_definitions.DEVICE_LIBRARY_PATH)
    materials = LibraryFile(path_definitions.MATERIAL_LIBRARY_PATH)
    d, m = devices.by_id(), materials.by_id()
    material, phase = f"material:{NAME}_Content", f"material:{NAME}_Content_Phase"
    species = f"{phase}_FerrocyanideIon"
    if m[species].get("cpo:hasConcentration"):
        sys.exit("The ferrocyanide stock has its concentration already - nothing written.")
    d[f"device:{NAME}"]["schema:name"] = f"Potassium ferrocyanide stock solution 0.05 M ({LABEL})"
    m[material]["schema:name"] = f"Potassium ferrocyanide stock solution 0.05 M ({LABEL})"
    m[material]["cpo:hasLotNumber"] = f"{LABEL} (label of the stock bottle, from Meng Kong's records - to be confirmed)"
    m[phase]["schema:name"] = f"Potassium ferrocyanide stock solution 0.05 M ({LABEL}) (liquid)"
    concentration = f"{species}_Concentration"
    m[species]["cpo:hasConcentration"] = {"@id": concentration}
    materials.graph.append({"@id": concentration, "@type": ["cpo:ProcessVariable", "hlo:Fixed", "hlo:Actual"],
                            "cpo:isProcessVariableOf": {"@id": species}, "hlo:hasReference": {"@id": f"{concentration}_Reference_1"}})
    materials.graph.append({"@id": f"{concentration}_Reference_1", "@type": ["cpo:ProcessVariable", "hlo:Reference"],
                            "qudt:hasQuantityKind": {"@id": "quantitykind:AmountOfSubstanceConcentration"},
                            "hlo:hasReferenceType": {"@id": "hlo:Planned"}, "hlo:hasSource": SOURCE,
                            "rdfs:comment": "Target concentration of the stock solution, 0.05 M of potassium ferrocyanide - one "
                                            "ferrocyanide ion per formula unit (Laura Fadler, 07.10.2026: taken from Meng Kong's "
                                            "records; to be confirmed by Meng Kong).",
                            "qudt:value": {"@value": "0.05", "@type": "xsd:decimal"}, "qudt:hasUnit": {"@id": "unit:MOL-PER-L"},
                            "cpo:hasDeterminationTask": {"@id": TASK}})
    task = m[TASK]
    task["cpo:determines"] = task.get("cpo:determines", []) + [{"@id": f"{concentration}_Reference_1"}]
    devices.save()
    materials.save()
    print("ferrocyanide stock: label and 0.05 mol/L planned")


if __name__ == "__main__":
    main()
