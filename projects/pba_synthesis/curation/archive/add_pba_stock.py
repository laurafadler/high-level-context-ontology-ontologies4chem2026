"""
Where the substances of the series pba_synthesis come from (L10, 07.10.2026): the three hydrates in
containers of the inventory, and the deionised water supply of Lab 208. With them every substance of the
two solutions stems from a known container or line of the libraries (rule 3.10) - no stream from
'outside' any more, and the origin of the solutions is known (Phase_Time_R7, L6).

NOTHING HERE IS KNOWN YET from the lab: manufacturer, product number, lot, size and kind of the containers,
receipt, storage place and water quality are still to be asked of Meng Kong (to-do list, "Meng fragen", part A).
Laura Fadler, 06.10.2026: a missing PBA statement may be a dummy value or an assumption, marked as such.
So every value written here is an hlo:Assumed reference of the task task:assuming_pba_stock_entries, and every
comment says DUMMY where a value is made up; the lot is a text that says it is not known. Replace them with
Meng's answers (a later curation script; this one records the dummy state).

Writes (stops if any entry exists already; commit the libraries afterwards - a run refuses uncommitted ones):
- device library: three containers of the kind device:glass_bottle_250mL (assumed - the kind is not known),
  in a chemicals cabinet of Lab 208 (assumed - no storage place is known); the deionised water supply of Lab 208 (helpers/inventory_entries.py:
  supply_pipe, as device:L109_DI_water_supply); the tasks behind the values and the task that stamps their
  start times;
- material library: the content of each container (one solid phase of the hydrate, lot, receipt, its
  occurrence in the lab) and the water in the supply;
- organization library: the chemicals cabinet of Lab 208 (assumed).

Usage (from the repository root):
    python projects/pba_synthesis/curation/add_pba_stock.py
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "generator" / "workflow" / "library_prerun"))
sys.path.insert(0, str(ROOT / "generator"))
import path_definitions  # noqa: E402
from fixed_reaction_from_template import LibraryFile  # noqa: E402
from helpers.inventory_entries import STEEL_BODY, Entries, cabinet, ref, supply_pipe  # noqa: E402

STAMP = "2026-10-07T00:30:00Z"
PERSON = "person:LauraFadler"
LAB = "lab:L208"
CABINET = "lab:L208_Chemicals_Cabinet"
TEMPLATE = "device:glass_bottle_250mL"
ASSUMING = "task:assuming_pba_stock_entries"
SUPPLY = "L208_DI_water_supply"
SUPPLY_TASK = f"task:assuming_{SUPPLY}"
# DUMMY receipt: before the K1 Start was commissioned (mid-2025), so before every experiment of the series.
RECEIVED = ("2025-06-02T09:00:00Z", "2025-06-02T09:30:00Z")
DUMMY = "DUMMY (Claude Code, 07.10.2026; allowed for PBA by Laura Fadler, 06.10.2026) - ask Meng Kong"
ORIGIN = ("Added by curation for the series pba_synthesis (L10): not in the ELN; container kind, place, lot and receipt "
          "not known - " + DUMMY + ".")

# (name, label, chem id, species name)
HYDRATES = [
    ("bottle_potassium_ferrocyanide_trihydrate_01", "Potassium ferrocyanide trihydrate bottle no. 1",
     "chem:PotassiumFerrocyanideTrihydrate", "Potassium ferrocyanide trihydrate"),
    ("bottle_nickel_chloride_hexahydrate_01", "Nickel(II) chloride hexahydrate bottle no. 1",
     "chem:NickelIIChlorideHexahydrate", "Nickel(II) chloride hexahydrate"),
    ("bottle_manganese_chloride_tetrahydrate_01", "Manganese(II) chloride tetrahydrate bottle no. 1",
     "chem:ManganeseIIChlorideTetrahydrate", "Manganese(II) chloride tetrahydrate"),
]

lib = Entries("task:assuming_pba_stock_entry_times", STAMP, PERSON, "the PBA stock entries")
assumed = []


def container(name, label, chem_id, species_name):
    """One container of the inventory with its hydrate - as helpers/inventory_entries.py: container, but
    every value an assumption (nothing is known yet), and only what the shapes need: lot, receipt and the
    occurrence of the content. Mass, volume and purity stay empty Actuals."""
    d = f"device:{name}"
    material, phase = f"material:{name}_Content", f"material:{name}_Content_Phase"
    receiving = f"task:receiving_{name}"
    occurrence = f"{phase}_Occurrence"
    status = f"{occurrence}_Status"
    lib.add({"@id": d, "@type": ["cpo:ChemicalContainer", "hlo:Fixed"], "schema:name": label,
             "rdfs:comment": f"One container of the inventory, of the kind {TEMPLATE} (form, glass and opening come from "
                             f"there) - the kind is assumed, as is its cabinet in Lab 208 ({DUMMY}). Every experiment that "
                             f"draws from it is an entry of its usage history; what was drawn stands in that experiment's crate.",
             "schema:comment": ORIGIN,
             "hlo:specializationOf": ref(TEMPLATE), "cpo:locatedInsideOf": ref(CABINET),
             "cpo:containsMaterial": ref(material), "cpo:hasContainedMaterialHistory": [ref(material)],
             "cpo:hasDeliveryTime": ref(f"{receiving}_EndTime"), "cpo:hasUsageHistory": [ref(receiving)],
             # Never used yet: it was last "used" at the delivery (rule 5.5).
             "cpo:lastUsedPurpose": ref(receiving), "cpo:lastUsedTime": ref(f"{receiving}_EndTime")})
    with lib.side("material"):
        lib.add({"@id": receiving, "@type": ["cpo:CommissioningTask", "hlo:Fixed"], "schema:name": f"Receiving {label[0].lower()}{label[1:]}",
                 "schema:description": "The container came into the lab; when is not known (dummy times).",
                 "cpo:hasStartTime": ref(f"{receiving}_StartTime"),
                 "cpo:hasEndTime": ref(f"{receiving}_EndTime"), "cpo:hasDuration": ref(f"{receiving}_Duration"),
                 "cpo:usedEquipment": [ref(d)]})
        start, end = RECEIVED
        assumed.append(lib.instant(f"{receiving}_StartTime", "Reference", "hlo:Assumed", start,
                                   f"Start of the receipt - {DUMMY}.", ASSUMING))
        assumed.append(lib.instant(f"{receiving}_EndTime", "Reference", "hlo:Assumed", end,
                                   f"Receipt of the container, its delivery time - {DUMMY}. Taken before the commissioning "
                                   f"of the K1 Start (mid-2025), so before every experiment.", ASSUMING))
        lib.add({"@id": f"{receiving}_Duration", "@type": ["time:Duration", "hlo:Fixed", "hlo:Actual"]})
        lib.add({"@id": material, "@type": ["cpo:MaterialVolume", "hlo:Fixed"], "schema:name": f"{species_name} (stock)",
                 "rdfs:comment": "The content of the container as delivered; what experiments drew from it stands in their crates.",
                 "cpo:materialContainedIn": ref(d), "cpo:fillsForm": ref(f"{TEMPLATE}_Cavity"), "dcterms:hasPart": ref(phase),
                 "cpo:hasLotNumber": f"not known - {DUMMY}",
                 "cpo:hasMass": ref(f"{material}_Mass"), "cpo:hasVolume": ref(f"{material}_Volume")})
        for quantity, kind in (("Mass", "quantitykind:Mass"), ("Volume", "quantitykind:Volume")):
            lib.add({"@id": f"{material}_{quantity}", "@type": ["cpo:ProcessVariable", "hlo:Fixed", "hlo:Actual"],
                     "qudt:hasQuantityKind": ref(kind)})
        species_id = f"{phase}_{chem_id.split(':', 1)[1]}"
        lib.add({"@id": species_id, "@type": ["chebi:Molecule", "chebi:ChemicalEntity", "hlo:Fixed"],
                 "schema:name": species_name, "hlo:specializationOf": ref(chem_id), "dcterms:isPartOf": ref(phase)})
        lib.add({"@id": phase, "@type": ["cpo:SolidPhase", "hlo:Fixed"], "schema:name": f"{species_name} (solid)",
                 "dcterms:isPartOf": ref(material), "cpo:canCreateEnergyField": False,
                 "cpo:hasDispersionState": ref("cpo:Continuous"), "cpo:hasMass": ref(f"{material}_Mass"),
                 "cpo:hasVolume": ref(f"{material}_Volume"), "dcterms:hasPart": [ref(species_id)],
                 "cpo:fillsForm": ref(f"{TEMPLATE}_Cavity"), "cpo:hasSolidStructure": ref("cpo:Crystalline"),
                 "cpo:hasOccurrence": ref(occurrence)})
        # The occurrence of the content in the lab (N25, Phase_Time_R2), from its receipt - as content_occurrence,
        # but its status assumed, not observed.
        lib.add({"@id": occurrence, "@type": ["cpo:Occurrence", "hlo:Fixed"],
                 "rdfs:comment": "The content in the lab: from its receipt until it is used up or disposed of (end unknown "
                                 "until then).",
                 "cpo:hasOccurrenceStatus": ref(status), "cpo:hasStartTime": ref(f"{receiving}_EndTime"),
                 "cpo:hasEndTime": ref(f"{occurrence}_EndTime"), "cpo:hasDuration": ref(f"{occurrence}_Duration")})
        lib.add({"@id": status, "@type": ["cpo:OccurrenceStatus", "hlo:Fixed", "hlo:Actual"],
                 "hlo:hasReference": ref(f"{status}_Reference_1")})
        lib.add({"@id": f"{status}_Reference_1", "@type": ["cpo:OccurrenceStatus", "hlo:Reference"],
                 "hlo:hasReferenceType": ref("hlo:Assumed"), "hlo:isReferenceOf": ref(status),
                 "rdfs:comment": "The hydrate was in the lab - the experiments weighed it in (Laura Fadler and Meng Kong, "
                                 "06.10.2026: supplied and weighed in as the hydrate).",
                 "cpo:hasOccurrenceValue": ref("cpo:Occurred"), "cpo:hasDeterminationTask": ref(ASSUMING)})
        assumed.append(f"{status}_Reference_1")
        for time_id, time_type in ((f"{occurrence}_EndTime", "time:Instant"), (f"{occurrence}_Duration", "time:Duration")):
            lib.add({"@id": time_id, "@type": [time_type, "hlo:Fixed", "hlo:Actual"]})


def water_supply():
    values, density = supply_pipe(
        lib, SUPPLY, "Deionised water supply of Lab 208", LAB, 0.015, 0.001, 1.0, "organization:ExampleCorp", STEEL_BODY,
        "Deionised water", [("chem:Molecule_0003", "Water")], ("2020-01-06T08:00:00Z", "2020-01-06T16:00:00Z"), SUPPLY_TASK,
        "The deionised water line of Lab 208, from the building supply to its outlet in the room - the last stretch of it as "
        "a device. The water of the PBA solutions is taken from here. Whether Lab 208 has such a line, and its water "
        f"quality, are not known - {DUMMY}. Size, material and installation assumed like for device:L109_DI_water_supply.")
    lib.find(f"device:{SUPPLY}")["schema:comment"] = ORIGIN
    lib.task(SUPPLY_TASK, "cpo:AssumptionTask", "Assuming the state of the deionised water supply of Lab 208",
             "The line is taken as always filled with deionised water (pure water, no other species, as in Lab 109), and as "
             f"installed with the lab; there is no record of when. {DUMMY}.", determines=values)
    return density


def main():
    devices = LibraryFile(path_definitions.DEVICE_LIBRARY_PATH)
    materials = LibraryFile(path_definitions.MATERIAL_LIBRARY_PATH)
    organization = LibraryFile(path_definitions.ORGANIZATION_LIBRARY_PATH)
    if CABINET in organization.by_id():
        sys.exit(f"Already in the libraries: {CABINET} - nothing written.")
    for args in HYDRATES:
        container(*args)
    density = water_supply()
    lib.task(ASSUMING, "cpo:AssumptionTask", "Assuming the stock containers of the PBA series",
             "Nothing is recorded yet of the containers the three hydrates are weighed from: their kind, place, lot and receipt "
             f"are dummy values until Meng Kong gives the real ones - {DUMMY}.", determines=assumed)
    lib.times_task("Assuming when the PBA stock entries were worked out",
                   f"None of the tasks behind the PBA stock entries was recorded with a time. Their start times are stamped with "
                   f"the moment the entries were written ({STAMP}) - an upper bound, not the moment the work happened. This "
                   f"task's own start time is among them.")

    device_items, material_items = lib.split()
    existing = {e["@id"] for e in devices.graph} | {e["@id"] for e in materials.graph}
    clash = [e["@id"] for e in device_items + material_items if e["@id"] in existing]
    if clash:
        sys.exit(f"Already in the libraries: {clash[0]} - nothing written.")
    steel = devices.by_id()[STEEL_BODY["density_task"]]
    steel["cpo:determines"] = steel["cpo:determines"] + [ref(density)]
    devices.graph.extend(device_items)
    materials.graph.extend(material_items)
    store = cabinet(CABINET, "Chemicals cabinet, Lab 208", LAB,
                    f"Where the hydrates of the PBA series are kept - assumed, the storage place is not known ({DUMMY}).")
    store["schema:comment"] = ORIGIN
    organization.graph.append(store)
    devices.save()
    materials.save()
    organization.save()
    print(f"device library: +{len(device_items)}, material library: +{len(material_items)}, organization library: +1")


if __name__ == "__main__":
    main()
