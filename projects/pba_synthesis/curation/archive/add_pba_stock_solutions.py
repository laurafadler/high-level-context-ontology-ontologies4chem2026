"""
The stock solutions of the series pba_synthesis (07.10.2026, Laura Fadler and Meng Kong, questions_meng_pba.md,
sections A-C): Chuyue Li made up every stock solution once - two of ferrocyanide, six of metal chlorides - and the
experiments drew from them (for a mixed experiment two metal solutions were mixed). So the hydrates were not
dissolved in the experiments: the dissolution belongs to the preparation of the stock solutions, which the
inventory describes (rule 2.15, as workflow/inventory_tool.py prepare). The crate starts from the solutions.

Written here (stops if any entry exists already; commit the libraries afterwards):
- three containers filled in the lab (device library) with their content and preparation (material library):
  - the nickel(II) chloride solution, from the preparation record 'NiCl2.6H2O 0.01M Li' (input/lab_data_for_crate/):
    7 April 2026, 13:39-13:50 (BST), Chuyue Li; 0.476 g of the hydrate from the Sigma-Aldrich bottle, lot
    0000540605, 200 mL of deionised water (CEB), shaken by hand; target 0.01 mol/L, calculated 0.0100 mol/L;
  - the potassium ferrocyanide and the manganese(II) chloride solution: made up the same way by Chuyue Li, but
    nothing of them is recorded - their preparation times are DUMMIES (the day of the nickel solution, right after
    it), amounts and labels not known;
- the hydrate bottles (B1): of polymer, not glass (Meng Kong: "probably") - template device:hdpe_container_1L,
  assumed, the size is not known; the nickel bottle gets its manufacturer and lot from the record;
- the deionised water line of Lab 208 (B2): confirmed by Meng Kong; its size, material and installation stay those
  of Lab 109 (assumed).

The preparation record dates '07/04/2026' are read day/month (UK), i.e. 7 April 2026. Its "calculated
concentration" of 0.00238 M is mass over volume in g/mL (0.476 g / 200 mL), not mol/L - not taken over.

Usage (from the repository root):
    python projects/pba_synthesis/curation/add_pba_stock_solutions.py
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "generator" / "workflow" / "library_prerun"))
sys.path.insert(0, str(ROOT / "generator"))
import path_definitions  # noqa: E402
from fixed_reaction_from_template import LibraryFile  # noqa: E402
from helpers.inventory_entries import Entries, ref  # noqa: E402
from helpers.library_functions import load_device_libraries  # noqa: E402
from workflow.inventory_tool import sort_into_history  # noqa: E402

STAMP = "2026-10-07T18:00:00Z"
ENTERED_BY = "person:LauraFadler"
PREPARER = "person:ChuyueLi"
CABINET = "lab:L208_Chemicals_Cabinet"
BOTTLE = "device:glass_bottle_250mL"
POLYMER = "device:hdpe_container_1L"
SUPPLY = "device:L208_DI_water_supply"
SUPPLY_PHASE = "material:L208_DI_water_supply_Content_Phase"
WATER = ("chem:Molecule_0003", "Water")
ASSUMING = "task:assuming_pba_stock_solutions"
DECIDED = "Laura Fadler and Meng Kong, 07.10.2026 (questions_meng_pba.md, sections A-C)"
DUMMY = "DUMMY (Claude Code, 07.10.2026; allowed for PBA by Laura Fadler, 06.10.2026) - ask Meng Kong"
RECORD = ("Reagent preparation record 'NiCl2.6H2O 0.01M Li' (template modular_reagent_preparation, designer and operator "
          "cl2114 = Chuyue Li), projects/pba_synthesis/input/lab_data_for_crate/NiCl2.6H2O 0.01M Li.jsonld")
ORIGIN = "Added by curation for the series pba_synthesis: not in the ELN - " + DECIDED + "."

# name, label, hydrate bottle, its content phase, species (chem, name); the nickel solution has its record.
SOLUTIONS = [
    ("stock_solution_nickel_chloride_01", "Nickel(II) chloride stock solution 0.01 M (NiCl2.6H2O 0.01M Li)",
     "device:bottle_nickel_chloride_hexahydrate_01",
     [WATER, ("chem:Nickel2PlusIon", "Nickel(II) ion"), ("chem:ChlorideIon", "Chloride ion")]),
    ("stock_solution_potassium_ferrocyanide_01", "Potassium ferrocyanide stock solution",
     "device:bottle_potassium_ferrocyanide_trihydrate_01",
     [WATER, ("chem:PotassiumIon", "Potassium ion"), ("chem:FerrocyanideIon", "Ferrocyanide ion")]),
    ("stock_solution_manganese_chloride_01", "Manganese(II) chloride stock solution",
     "device:bottle_manganese_chloride_tetrahydrate_01",
     [WATER, ("chem:Manganese2PlusIon", "Manganese(II) ion"), ("chem:ChlorideIon", "Chloride ion")]),
]
# Preparation times (UTC; BST = UTC+1 in April). Nickel: from the record. The other two: DUMMY - made up right
# after the nickel solution, each as long as it (11 min).
TIMES = {
    "stock_solution_nickel_chloride_01": ("2026-04-07T12:39:00Z", "2026-04-07T12:50:00Z"),
    "stock_solution_potassium_ferrocyanide_01": ("2026-04-07T12:50:00Z", "2026-04-07T13:01:00Z"),
    "stock_solution_manganese_chloride_01": ("2026-04-07T13:01:00Z", "2026-04-07T13:12:00Z"),
}
NI = "stock_solution_nickel_chloride_01"
WATER_M3 = 0.0002                # 200 mL, error 2 mL (50 mL graduated cylinder)
TARGET_MOL_PER_L = 0.01

lib = Entries("task:assuming_pba_stock_solution_entry_times", STAMP, ENTERED_BY, "the PBA stock solution entries")
assumed = []


def stock_solution(name, label, hydrate_bottle, species):
    recorded = name == NI
    d, material = f"device:{name}", f"material:{name}_Content"
    phase, task = f"{material}_Phase", f"task:preparing_{name}"
    hydrate_phase = f"material:{hydrate_bottle.split(':', 1)[1]}_Content_Phase"
    determined = []
    lib.add({"@id": d, "@type": ["cpo:ChemicalContainer", "hlo:Fixed"], "schema:name": label,
             "rdfs:comment": f"A stock solution made up in the lab by Chuyue Li, of the kind {BOTTLE} (form, glass and opening "
                             f"come from there) - the kind is assumed, as is its cabinet in Lab 208 ({DUMMY}). The "
                             f"preparation, its transfers from the hydrate bottle and the water line, and the content are "
                             f"described in the material library; every experiment that draws from it is an entry of its "
                             f"usage history.",
             "schema:comment": ORIGIN,
             "hlo:specializationOf": ref(BOTTLE), "cpo:locatedInsideOf": ref(CABINET),
             "cpo:containsMaterial": ref(material), "cpo:hasContainedMaterialHistory": [ref(material)],
             "cpo:hasUsageHistory": [ref(task)], "cpo:lastUsedPurpose": ref(task), "cpo:lastUsedTime": ref(f"{task}_EndTime")})
    with lib.side("material"):
        solid_transfer, water_transfer = f"{phase}_from_{hydrate_bottle.split(':', 1)[1]}", f"{phase}_from_L208_DI_water_supply"
        solid = {"@id": solid_transfer, "@type": ["cpo:Transfer", "hlo:Fixed"],
                 "schema:name": f"From {hydrate_bottle.split(':', 1)[1]} into {name}",
                 "cpo:hasTransferType": ref("cpo:PortCrossing"), "cpo:removesFromPhase": ref(hydrate_phase),
                 "cpo:addsToPhase": ref(phase), "cpo:isAimOf": ref(task)}
        water = {"@id": water_transfer, "@type": ["cpo:Transfer", "hlo:Fixed"], "schema:name": f"From L208_DI_water_supply into {name}",
                 "cpo:hasTransferType": ref("cpo:PortCrossing"), "cpo:removesFromPhase": ref(SUPPLY_PHASE),
                 "cpo:addsToPhase": ref(phase), "cpo:isAimOf": ref(task)}
        if recorded:
            # The mass weighed in (0.476 g) has no property of its own: the CPO knows only cpo:hasTransferredVolume
            # (ontology frozen until the submission) - it stands in the description and the calculation.
            water["cpo:hasTransferredVolume"] = ref(f"{water_transfer}_TransferredVolume")
            determined.append(lib.value(f"{water_transfer}_TransferredVolume", "quantitykind:Volume", "Evidence", WATER_M3,
                                        "unit:M3", "hlo:Measured",
                                        "Volume of deionised water (200 mL, error 2 mL), measured with a 50 mL graduated cylinder.",
                                        task, source=RECORD, owner=water_transfer))
        lib.add(solid)
        lib.add(water)

        description = ("Nickel(II) chloride hexahydrate weighed from its bottle into the stock bottle (0.476 g, measurement error "
                       "0.001 g; spatula, weighing boat, Fisher Scientific balance - model not recorded), 200 mL of deionised water "
                       "added and the bottle shaken by hand until everything had dissolved; in the safety cabinet of Lab L2.08 "
                       "(lab coat, glasses, gloves). From the preparation record." if recorded else
                       "Made up by Chuyue Li like the nickel(II) chloride solution: the hydrate weighed into the stock bottle, "
                       "deionised water added, shaken by hand until dissolved. Nothing of it is recorded - amounts, label and "
                       f"times are not known (the times are a {DUMMY}).")
        lib.add({"@id": task, "@type": ["cpo:OperationTask", "hlo:Fixed"], "schema:name": f"Preparing the {label[0].lower()}{label[1:]}",
                 "schema:description": description, "cpo:performedBy": [ref(PREPARER)],
                 "cpo:hasStartTime": ref(f"{task}_StartTime"), "cpo:hasEndTime": ref(f"{task}_EndTime"),
                 "cpo:hasDuration": ref(f"{task}_Duration"),
                 "cpo:usedEquipment": [ref(hydrate_bottle), ref(SUPPLY), ref(d)],
                 "cpo:realizesFunction": [ref("cpo:Dissolving"), ref("cpo:Mixing")],
                 "cpo:aimsAt": [ref(solid_transfer), ref(water_transfer)]})
        start, end = TIMES[name]
        if recorded:
            determined.append(lib.instant(f"{task}_StartTime", "Evidence", "hlo:Observed", start,
                                          "Start of the preparation, 07/04/2026 13:39 (BST) in the record.", task, source=RECORD))
            determined.append(lib.instant(f"{task}_EndTime", "Evidence", "hlo:Observed", end,
                                          "End of the preparation, 07/04/2026 13:50 (BST) in the record. The content exists from "
                                          "here on.", task, source=RECORD))
        else:
            assumed.append(lib.instant(f"{task}_StartTime", "Reference", "hlo:Assumed", start,
                                       f"Start of the preparation - {DUMMY}: taken as right after the nickel(II) chloride "
                                       f"solution, the only one with a record (Chuyue Li made every stock solution once, before "
                                       f"the experiments).", ASSUMING))
            assumed.append(lib.instant(f"{task}_EndTime", "Reference", "hlo:Assumed", end,
                                       f"End of the preparation - {DUMMY}: as long as the nickel(II) chloride solution (11 min). "
                                       f"The content exists from here on.", ASSUMING))
        lib.add({"@id": f"{task}_Duration", "@type": ["time:Duration", "hlo:Fixed", "hlo:Actual"]})

        lib.add({"@id": material, "@type": ["cpo:MaterialVolume", "hlo:Fixed"], "schema:name": label,
                 "rdfs:comment": "The stock solution as made up in the lab; what experiments drew from it stands in their crates.",
                 "cpo:materialContainedIn": ref(d), "cpo:fillsForm": ref(f"{BOTTLE}_Cavity"), "dcterms:hasPart": ref(phase),
                 "cpo:hasLotNumber": "NiCl2.6H2O 0.01M Li (label of the stock bottle)" if recorded else f"label not known - {DUMMY}",
                 "cpo:hasMass": ref(f"{material}_Mass"), "cpo:hasVolume": ref(f"{material}_Volume")})
        lib.add({"@id": f"{material}_Mass", "@type": ["cpo:ProcessVariable", "hlo:Fixed", "hlo:Actual"],
                 "qudt:hasQuantityKind": ref("quantitykind:Mass")})
        if recorded:
            determined.append(lib.value(f"{material}_Volume", "quantitykind:Volume", "Evidence", WATER_M3, "unit:M3", "hlo:Measured",
                                        "Volume of the solution made up (actual volume 200 mL in the record).", task, source=RECORD))
            lib.find(f"{material}_Volume")["hlo:hasReference"] = ref(f"{material}_Volume_Reference_1")
            lib.add({"@id": f"{material}_Volume_Reference_1", "@type": ["cpo:ProcessVariable", "hlo:Reference"],
                     "hlo:hasReferenceType": ref("hlo:Planned"), "hlo:hasSource": RECORD,
                     "rdfs:comment": "Target volume of the solution, 200 mL in the record.", "qudt:value": {"@value": "0.0002", "@type": "xsd:decimal"},
                     "qudt:hasUnit": ref("unit:M3"), "cpo:hasDeterminationTask": ref(task)})
            determined.append(f"{material}_Volume_Reference_1")
        else:
            lib.add({"@id": f"{material}_Volume", "@type": ["cpo:ProcessVariable", "hlo:Fixed", "hlo:Actual"],
                     "qudt:hasQuantityKind": ref("quantitykind:Volume")})

        species_ids = []
        for chem_id, species_name in species:
            species_id = f"{phase}_{chem_id.split(':', 1)[1]}"
            species_ids.append(species_id)
            entry = {"@id": species_id, "@type": ["chebi:Molecule", "chebi:ChemicalEntity", "hlo:Fixed"],
                     "schema:name": species_name, "hlo:specializationOf": ref(chem_id), "dcterms:isPartOf": ref(phase)}
            lib.add(entry)
            if recorded and chem_id == "chem:Nickel2PlusIon":
                entry["cpo:hasConcentration"] = ref(f"{species_id}_Concentration")
                planned = lib.value(f"{species_id}_Concentration", "quantitykind:AmountOfSubstanceConcentration", "Reference",
                                    TARGET_MOL_PER_L, "unit:MOL-PER-L", "hlo:Planned",
                                    "Target concentration of the solution, 0.01 M of nickel(II) chloride hexahydrate in the "
                                    "record - one nickel(II) ion per formula unit.", task, source=RECORD,
                                    kind_on_value=True, owner=species_id)
                determined.append(planned)
                calculated = f"{species_id}_Concentration_Evidence_1"
                calculation = "task:calculating_pba_nickel_stock_concentration"
                lib.find(f"{species_id}_Concentration")["hlo:hasEvidence"] = ref(calculated)
                lib.add({"@id": calculated, "@type": ["cpo:ProcessVariable", "hlo:Evidence"],
                         "qudt:hasQuantityKind": ref("quantitykind:AmountOfSubstanceConcentration"),
                         "hlo:hasEvidenceType": ref("hlo:Calculated"),
                         "rdfs:comment": "0.476 g / 237.69 g/mol / 0.200 L = 0.0100 mol/L. The record's own 'calculated "
                                         "concentration' of 0.00238 M is 0.476 g / 200 mL in g/mL, not mol/L - not taken over.",
                         "qudt:value": {"@value": "0.01001", "@type": "xsd:decimal"}, "qudt:hasUnit": ref("unit:MOL-PER-L"),
                         "cpo:hasDeterminationTask": ref(calculation)})
                with lib.side("material"):
                    lib.task(calculation, "cpo:CalculationTask", "Calculating the concentration of the nickel(II) chloride stock solution",
                             "Amount of nickel(II) ions from the mass weighed in and the molar mass of the hydrate (237.69 g/mol, "
                             "from the record), divided by the volume of the solution. The mass, 0.476 g, is read from "
                             "the record (no property of the ontology holds a mass weighed in).", determines=[calculated],
                             inputs=[f"{material}_Volume"])
        lib.add({"@id": phase, "@type": ["cpo:LiquidPhase", "hlo:Fixed"], "schema:name": f"{label} (liquid)",
                 "dcterms:isPartOf": ref(material), "cpo:canCreateEnergyField": False,
                 "cpo:hasDispersionState": ref("cpo:Continuous"), "cpo:hasMass": ref(f"{material}_Mass"),
                 "cpo:hasVolume": ref(f"{material}_Volume"), "dcterms:hasPart": [ref(s) for s in species_ids],
                 "cpo:fillsForm": ref(f"{BOTTLE}_Cavity")})

        # The content in the lab from the end of its preparation (N25, Phase_Time_R2).
        occurrence, status = f"{phase}_Occurrence", f"{phase}_Occurrence_Status"
        lib.find(phase)["cpo:hasOccurrence"] = ref(occurrence)
        lib.add({"@id": occurrence, "@type": ["cpo:Occurrence", "hlo:Fixed"],
                 "rdfs:comment": "The stock solution in the lab: from the end of its preparation until it is used up or "
                                 "disposed of (end unknown until then).",
                 "cpo:hasOccurrenceStatus": ref(status), "cpo:hasStartTime": ref(f"{task}_EndTime"),
                 "cpo:hasEndTime": ref(f"{occurrence}_EndTime"), "cpo:hasDuration": ref(f"{occurrence}_Duration")})
        role, member = ("Evidence", f"{status}_Evidence_1") if recorded else ("Reference", f"{status}_Reference_1")
        lib.add({"@id": status, "@type": ["cpo:OccurrenceStatus", "hlo:Fixed", "hlo:Actual"], f"hlo:has{role}": ref(member)})
        lib.add({"@id": member, "@type": ["cpo:OccurrenceStatus", f"hlo:{role}"],
                 f"hlo:has{role}Type": ref("hlo:Observed" if recorded else "hlo:Assumed"), f"hlo:is{role}Of": ref(status),
                 "rdfs:comment": ("Everything dissolved - Chuyue Li looked at the solution (" + DECIDED + ")." if recorded else
                                  "Made up before the experiments, which drew from it (" + DECIDED + ")."),
                 "cpo:hasOccurrenceValue": ref("cpo:Occurred"), "cpo:hasDeterminationTask": ref(task if recorded else ASSUMING)})
        (determined if recorded else assumed).append(member)
        for time_id, time_type in ((f"{occurrence}_EndTime", "time:Instant"), (f"{occurrence}_Duration", "time:Duration")):
            lib.add({"@id": time_id, "@type": [time_type, "hlo:Fixed", "hlo:Actual"]})
        lib.find(task)["cpo:determines"] = [ref(i) for i in determined]
    return task, hydrate_bottle


def update_hydrate_bottles(devices: dict, materials: dict):
    """B1: the hydrate bottles are of polymer (assumed); the nickel bottle's manufacturer and lot from the record."""
    for name in ("bottle_potassium_ferrocyanide_trihydrate_01", "bottle_nickel_chloride_hexahydrate_01",
                 "bottle_manganese_chloride_tetrahydrate_01"):
        device = devices[f"device:{name}"]
        device["hlo:specializationOf"] = ref(POLYMER)
        device["rdfs:comment"] = (f"One container of the inventory, of the kind {POLYMER} (form, polyethylene and opening come from "
                                  f"there) - of polymer, not glass (Meng Kong, 07.10.2026: 'probably'); the size and the cabinet "
                                  f"in Lab 208 are assumed ({DUMMY}). Its hydrate went into a stock solution (task:preparing_"
                                  f"stock_solution_...), from which the experiments drew.")
        content = materials[f"material:{name}_Content"]
        content["cpo:fillsForm"] = ref(f"{POLYMER}_Cavity")
        materials[f"material:{name}_Content_Phase"]["cpo:fillsForm"] = ref(f"{POLYMER}_Cavity")
        if name == "bottle_nickel_chloride_hexahydrate_01":
            content["cpo:hasLotNumber"] = "0000540605"
            content["cpo:hasManufacturer"] = ref("organization:SigmaAldrich")
            content["rdfs:comment"] = ("The content of the container as delivered; what was drawn from it stands in the "
                                       "preparation of the stock solution. Manufacturer and lot from the " + RECORD + ".")
            device["schema:comment"] = ("Added by curation for the series pba_synthesis (L10): not in the ELN; manufacturer and lot "
                                        "from the preparation record of the stock solution (" + DECIDED + "); kind of container "
                                        "assumed, receipt and place not known - " + DUMMY + ".")


def confirm_water_line(devices: dict):
    """B2: Lab 208 has this line (Meng Kong); only its size, material and installation are assumed."""
    line = devices[SUPPLY]
    line["rdfs:comment"] = ("The deionised water line of Lab 208, from the building supply to its outlet in the room - the last "
                            "stretch of it as a device. The stock solutions of the PBA series were made up with its water (Meng "
                            "Kong, 07.10.2026; supplier 'CEB' in the preparation record). Size, material and installation "
                            f"assumed like for device:L109_DI_water_supply ({DUMMY}).")
    line["schema:comment"] = ("Added by curation for the series pba_synthesis (L10): not in the ELN; the line is confirmed by "
                              "Meng Kong (07.10.2026), its size, material and installation are assumed - " + DUMMY + ".")


def main():
    devices = LibraryFile(path_definitions.DEVICE_LIBRARY_PATH)
    materials = LibraryFile(path_definitions.MATERIAL_LIBRARY_PATH)
    if f"device:{NI}" in devices.by_id():
        sys.exit(f"Already in the libraries: device:{NI} - nothing written.")
    preparations = [stock_solution(*args) for args in SOLUTIONS]
    lib.task(ASSUMING, "cpo:AssumptionTask", "Assuming the stock solutions of the PBA series",
             "Of the three stock solutions only the nickel(II) chloride one has a preparation record. The kind of their "
             "bottles, their cabinet and the preparation of the other two are assumed - " + DUMMY + ".", determines=assumed)
    lib.times_task("Assuming when the PBA stock solution entries were worked out",
                   f"The assumption and calculation tasks behind the PBA stock solution entries were not recorded with a "
                   f"time. Their start times are stamped with the moment the entries were written ({STAMP}) - an upper bound. "
                   f"This task's own start time is among them.")
    device_items, material_items = lib.split()
    existing = set(devices.by_id()) | set(materials.by_id())
    clash = [e["@id"] for e in device_items + material_items if e["@id"] in existing]
    if clash:
        sys.exit(f"Already in the libraries: {clash[0]} - nothing written.")
    devices.graph.extend(device_items)
    materials.graph.extend(material_items)
    device_ids, material_ids = devices.by_id(), materials.by_id()
    update_hydrate_bottles(device_ids, material_ids)
    confirm_water_line(device_ids)
    # The preparation into the usage history of its sources, by time (rule 5.4).
    devices.save()
    materials.save()
    view, _ = load_device_libraries()
    devices, materials = LibraryFile(path_definitions.DEVICE_LIBRARY_PATH), LibraryFile(path_definitions.MATERIAL_LIBRARY_PATH)
    device_ids = devices.by_id()
    for task, hydrate_bottle in preparations:
        for source in (hydrate_bottle, SUPPLY):
            sort_into_history(device_ids[source], task, view)
    devices.save()
    print(f"device library: +{len(device_items)}, material library: +{len(material_items)}; "
          f"3 hydrate bottles and the water line changed")


if __name__ == "__main__":
    main()
