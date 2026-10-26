"""
The inventory of the Chemotion example (05.10.2026, Laura Fadler): the containers the wood and the
methanol of the two experiments came from, after the inventory records of the export (table Chemical,
rule P-CH10) and the free text of the records.

- chemical entity library: HDPE (informal entry, as polypropylene);
- device library: two container templates - an HDPE container 1 L (the stock is kept "in a sealed HDPE
  container") and a glass bottle 1 L (Sigma-Aldrich 646377-1L) - copied from the glass bottle 250 mL with
  new dimensions, the HDPE one with its own body material and density;
- organization library: cabinet B3 of room B1-09 (the inventory of LCJ-28) and a solvent cabinet for the
  bottles the export places at '#01-10'; the vendors Norske Skog and Sigma-Aldrich;
- inventory library: the spruce wood stock SPRUCE-2025-03 (sample LCJ-28; LCJ-R5 takes "5g aliquot from
  SPRUCE-2025-03 stock"), the NREL-characterized batch BM-SPRUCE-NREL-01 (LCJ-R8) and a methanol bottle,
  each with its content, lot or catalogue number, amount, expiry and receipt.

Times: the export records no delivery. A receipt is stamped with an upper bound - the creation of the
stock's sample in Chemotion (LCJ-28, LCJ-159); the methanol bottles were entered after LCJ-R5, so their
receipt is taken before LCJ-R5 (Laura Fadler: the bottle existed earlier) - all assumed.

Reads and writes the libraries through load_jsonld/save_jsonld (rule 2.14). Runs once; stops if an entry
exists already. Uses the helpers of add_library_entries.py (copying a template, its geometry).

Usage (from the repository root):
    python projects/chemotion_example/curation/add_inventory.py
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from add_library_entries import (LIB, ROOT, add, append_determines, as_list, by_id, clone_family, cup_geometry,  # noqa: E402
                                 ref, task, task_times, template_ids, value)
from helpers.file_handling import load_jsonld, save_jsonld  # noqa: E402

STAMP = "2026-10-06T00:30:00Z"
BY = "suggested by Claude Code on 05.10.2026 for the Chemotion example, not yet confirmed"
CONFIRMED = "decided by Laura Fadler on 05.10.2026 for the Chemotion example"
LAB = "lab:NTU_CongjianLin_Lab"
CAB_B3, CAB_SOLV = "lab:NTU_CongjianLin_Lab_Cabinet_B3", "lab:NTU_CongjianLin_Lab_Solvent_Cabinet"
RECORD_R5, RECORD_R8 = "reaction:Record_Chemotion_LCJ-R5", "reaction:Record_Chemotion_LCJ-R8"
HDPE_DENSITY_TASK = "task:looking_up_hdpe_density"
ASSUMING = "task:assuming_chemotion_inventory_receipts"


# ---------------------------------------------------------------------------------------------
# HDPE
# ---------------------------------------------------------------------------------------------
def chemical_entries():
    return [{"@id": "chem:HDPE", "@type": ["chebi:ChemicalEntity", "hlo:Fixed"], "schema:name": "High-density polyethylene (HDPE)",
             "cpo:isInert": True,
             "rdfs:comment": ("Informal entry, not a single chemical species - HDPE is a polymer with a distribution of chain lengths. "
                              "Same reasoning as chem:ChemicalEntity_0003 (Polypropylene): carried as a chemical entity so a device body "
                              "phase can list what it is made of, without CAS/SMILES/InChI/molar mass."),
             "schema:comment": ("From the ELN (Chemotion, inventory of sample LCJ-28: 'Keep dry. Store in sealed HDPE container.'); the "
                                f"container added as a template ({CONFIRMED}).")}]


# ---------------------------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------------------------
def container_templates(graph):
    old = "glass_bottle_250mL"
    # HDPE container 1 L
    hdpe = clone_family(graph, template_ids(graph, old), [(old, "hdpe_container_1L"), ("Glass bottle 250 mL", "HDPE container 1 L"),
                                                           ("glass bottle 250 ml", "hdpe container 1 l")])
    e = by_id(hdpe)
    density = e["material:hdpe_container_1L_Body_SolidPhase_Density_Reference_1"]
    density["qudt:value"] = {"@value": "950", "@type": "xsd:decimal"}
    density["hlo:hasSource"] = "en.wikipedia.org/wiki/High-density_polyethylene (0.93-0.97 g/cm3)."
    density["rdfs:comment"] = "Generic HDPE (~950 kg/m3) - not measured."
    density["cpo:hasDeterminationTask"] = ref(HDPE_DENSITY_TASK)
    v_hdpe = cup_geometry(hdpe, "hdpe_container_1L", 0.11, 0.13, 0.002, "a 1 L HDPE container approximated as a plastic cup.")
    phase = e["material:hdpe_container_1L_Body_SolidPhase"]
    phase["dcterms:hasPart"] = ref("chem:HDPE")
    phase["cpo:hasSolidStructure"] = ref("cpo:SemiCrystalline")
    e["material:hdpe_container_1L_Body"]["rdfs:comment"] = "Generic HDPE - the inventory of LCJ-28 says 'sealed HDPE container'; the grade is not known."
    device = e["device:hdpe_container_1L"]
    device.pop("cpo:hasManufacturer", None)
    device["schema:name"] = "HDPE container 1 L (template)"
    device["rdfs:comment"] = ("TEMPLATE of a container kind: the containers of the inventory of this kind specialize it and take over its "
                              "form, body and opening. Approximated as a plain HDPE cup with a lid opening. The Chemotion inventory of "
                              f"sample LCJ-28 says 'Store in sealed HDPE container' ({CONFIRMED}); 1 L (inner {v_hdpe * 1e3:.2f} L) for "
                              f"500 g of wood pellets and the dimensions {BY}. Copied from device:glass_bottle_250mL with new dimensions "
                              "and body.")
    e["device:hdpe_container_1L_Form"]["rdfs:comment"] = ("Plastic cup: an assumed body of 110 mm across and 130 mm tall and an assumed "
                                                         "2 mm wall; the inner dimensions and both volumes follow from them.")
    e["task:assuming_hdpe_container_1L_dimensions"]["schema:description"] = "Assumed dimensions of a 1 L HDPE container - not measured."
    # Glass bottle 1 L
    glass = clone_family(graph, template_ids(graph, old), [(old, "glass_bottle_1L"), ("Glass bottle 250 mL", "Glass bottle 1 L"),
                                                            ("glass bottle 250 ml", "glass bottle 1 l")])
    g = by_id(glass)
    v_glass = cup_geometry(glass, "glass_bottle_1L", 0.09, 0.2, 0.004, "a 1 L reagent bottle approximated as a glass cup.")
    bottle = g["device:glass_bottle_1L"]
    bottle.pop("cpo:hasManufacturer", None)
    bottle["schema:name"] = "Glass bottle 1 L (template)"
    bottle["rdfs:comment"] = ("TEMPLATE of a container kind: a 1 L reagent bottle, as Sigma-Aldrich 646377-1L (the inventory of LCJ-44, "
                              f"LCJ-45). Approximated as a plain glass cup - the neck is left out (inner {v_glass * 1e3:.2f} L); dimensions "
                              f"{BY}. Copied from device:glass_bottle_250mL with new dimensions.")
    g["device:glass_bottle_1L_Form"]["rdfs:comment"] = ("Glass cup: an assumed body of 90 mm across and 200 mm tall and an assumed 4 mm "
                                                       "wall; the inner dimensions and both volumes follow from them.")
    g["task:assuming_glass_bottle_1L_dimensions"]["schema:description"] = "Assumed dimensions of a 1 L reagent bottle - not measured."
    # The HDPE density is determined by a task of its own, not by the glass research the copy attached itself to.
    hdpe_density = "material:hdpe_container_1L_Body_SolidPhase_Density_Reference_1"
    for t in graph:
        if hdpe_density in [i.get("@id") for i in as_list(t.get("cpo:determines")) if isinstance(i, dict)]:
            t["cpo:determines"] = [i for i in as_list(t["cpo:determines"]) if i.get("@id") != hdpe_density]
    lookup = task(HDPE_DENSITY_TASK, "cpo:LiteratureLookupTask", "Looking up the density of HDPE",
                  "HDPE is about 950 kg/m3 (930-970 kg/m3 depending on grade). Recorded as 950 kg/m3.", [hdpe_density])
    return hdpe + glass + [lookup] + task_times(HDPE_DENSITY_TASK, "task:assuming_device_library_task_times")


# ---------------------------------------------------------------------------------------------
# Cabinets and suppliers
# ---------------------------------------------------------------------------------------------
def organization_entries():
    return [
        {"@id": CAB_B3, "@type": ["cpo:StorageCabinet", "hlo:Fixed"], "schema:name": "Cabinet B3, room B1-09",
         "rdfs:comment": "The cabinet of the spruce wood stock of the Chemotion collection.",
         "schema:comment": "From the ELN (Chemotion, inventory of sample LCJ-28): host_cabinet 'B3', host_room 'B1-09'; sample location 'Cabinet B3, Shelf 1'.",
         "cpo:locatedInsideOf": ref(LAB)},
        {"@id": CAB_SOLV, "@type": ["cpo:StorageCabinet", "hlo:Fixed"], "schema:name": "Solvent cabinet, lab of Congjian Lin ('#01-10')",
         "rdfs:comment": ("Where the methanol bottles of the Chemotion collection are kept. The export gives only '#01-10' (host_building "
                          f"and sample location of LCJ-44, LCJ-45) - taken as a cabinet in the lab ({BY})."),
         "cpo:locatedInsideOf": ref(LAB)},
        {"@id": "organization:NorskeSkog", "@type": ["org:Organization", "hlo:Fixed"], "schema:name": "Norske Skog",
         "rdfs:comment": "Supplier of the spruce wood pellets of the Chemotion collection - 'Norske Skog (via SCCB)': passed on by the group SCCB.",
         "schema:comment": "From the ELN (Chemotion, inventory of sample LCJ-28): vendor 'Norske Skog (via SCCB)'."},
        {"@id": "organization:SigmaAldrich", "@type": ["org:Organization", "hlo:Fixed"], "schema:name": "Sigma-Aldrich",
         "schema:comment": "From the ELN (Chemotion, inventory of samples LCJ-44, LCJ-45): vendor 'Sigma-Aldrich'."},
    ]


# ---------------------------------------------------------------------------------------------
# Containers
# ---------------------------------------------------------------------------------------------
def container(cid, name, template, cabinet, comment, origin, content_name, phase_kind, species, lot=None, sku=None,
              manufacturer=None, amount=None, expiry=None, receipt=None, records=()):
    """A container of the inventory with its content, as device:bottle_adiponitrile_01 - values only where known."""
    content, phase = f"material:{cid}_Content", f"material:{cid}_Content_Phase"
    receiving = f"task:receiving_{cid}"
    entries = [{"@id": f"device:{cid}", "@type": ["cpo:ChemicalContainer", "hlo:Fixed"], "schema:name": name,
                "rdfs:comment": (f"One container of the inventory, of the kind device:{template} (form, body and opening come from there). "
                                 + comment),
                "schema:comment": origin, "hlo:specializationOf": ref(f"device:{template}"), "cpo:locatedInsideOf": ref(cabinet),
                "cpo:containsMaterial": ref(content), "cpo:hasDeliveryTime": ref(f"{receiving}_EndTime"),
                "cpo:hasUsageHistory": [ref(receiving)], "cpo:lastUsedPurpose": ref(receiving), "cpo:lastUsedTime": ref(f"{receiving}_EndTime"),
                "schema:subjectOf": [ref(r) for r in records]}]
    c = {"@id": content, "@type": ["cpo:MaterialVolume", "hlo:Fixed"], "schema:name": content_name,
         "rdfs:comment": "The content of the container as delivered; what experiments drew from it stands in their crates.",
         "cpo:materialContainedIn": ref(f"device:{cid}"), "cpo:fillsForm": ref(f"device:{template}_Cavity"), "dcterms:hasPart": ref(phase),
         "cpo:hasMass": ref(f"{content}_Mass"), "cpo:hasVolume": ref(f"{content}_Volume")}
    if lot:
        c["cpo:hasLotNumber"] = lot
    if sku:
        c["schema:sku"] = sku
    if manufacturer:
        c["cpo:hasManufacturer"] = ref(manufacturer)
    entries.append(c)
    for q, unit, kind in (("Mass", "unit:KiloGM", "quantitykind:Mass"), ("Volume", "unit:L", "quantitykind:Volume")):
        known = amount if amount and amount[0] == q else None
        if known:
            entries += value(f"{content}_{q}", "cpo:ProcessVariable", known[1], unit, "hlo:Literature",
                             f"Amount at delivery, as the inventory record gives it ({known[2]}).", "task:reading_chemotion_inventory", kind)
            by_id(entries)[f"{content}_{q}_Reference_1"]["hlo:hasSource"] = known[2]
        else:
            entries.append({"@id": f"{content}_{q}", "@type": ["cpo:ProcessVariable", "hlo:Fixed", "hlo:Actual"], "qudt:hasQuantityKind": ref(kind)})
    if expiry:
        c["cpo:hasExpiryTime"] = ref(f"{content}_ExpiryTime")
        entries += [{"@id": f"{content}_ExpiryTime", "@type": ["time:Instant", "hlo:Fixed", "hlo:Actual"], "hlo:hasReference": ref(f"{content}_ExpiryTime_Reference_1")},
                    {"@id": f"{content}_ExpiryTime_Reference_1", "@type": ["time:Instant", "hlo:Reference"], "hlo:hasReferenceType": ref("hlo:Literature"),
                     "hlo:hasSource": expiry[1], "rdfs:comment": "Expiry date of the content, as the inventory record gives it.",
                     "rdf:value": {"@value": expiry[0], "@type": "xsd:dateTime"}, "cpo:hasDeterminationTask": ref("task:reading_chemotion_inventory")}]
    molecules = []
    for chem, label in species:
        mid = f"{phase}_{chem.split(':')[1]}"
        molecules.append(ref(mid))
        entries.append({"@id": mid, "@type": ["chebi:ChemicalEntity", "hlo:Fixed"] + (["chebi:Molecule"] if chem == "chem:Methanol" else []),
                        "schema:name": label, "hlo:specializationOf": ref(chem), "dcterms:isPartOf": ref(phase)})
    occurrence = f"{phase}_Occurrence"
    entries += [
        {"@id": phase, "@type": [phase_kind, "hlo:Fixed"], "schema:name": f"{content_name} ({'solid' if 'Solid' in phase_kind else 'liquid'})",
         "dcterms:isPartOf": ref(content), "cpo:canCreateEnergyField": False, "cpo:hasDispersionState": ref("cpo:Continuous"),
         "cpo:hasMass": ref(f"{content}_Mass"), "cpo:hasVolume": ref(f"{content}_Volume"), "dcterms:hasPart": molecules,
         "cpo:fillsForm": ref(f"device:{template}_Cavity"), "cpo:hasOccurrence": ref(occurrence)}
        | ({"cpo:hasSolidStructure": ref("cpo:SemiCrystalline")} if "Solid" in phase_kind else {}),
        {"@id": occurrence, "@type": ["cpo:Occurrence", "hlo:Fixed"],
         "rdfs:comment": "The content in the lab: from its receipt until it is used up or disposed of (end unknown until then).",
         "cpo:hasOccurrenceStatus": ref(f"{occurrence}_Status"), "cpo:hasStartTime": ref(f"{receiving}_EndTime"),
         "cpo:hasEndTime": ref(f"{occurrence}_EndTime"), "cpo:hasDuration": ref(f"{occurrence}_Duration")},
        {"@id": f"{occurrence}_Status", "@type": ["cpo:OccurrenceStatus", "hlo:Fixed", "hlo:Actual"], "hlo:hasReference": ref(f"{occurrence}_Status_Reference_1")},
        {"@id": f"{occurrence}_Status_Reference_1", "@type": ["cpo:OccurrenceStatus", "hlo:Reference"], "hlo:hasReferenceType": ref("hlo:Assumed"),
         "hlo:isReferenceOf": ref(f"{occurrence}_Status"), "rdfs:comment": "The content was in the lab - assumed from the inventory record.",
         "cpo:hasOccurrenceValue": ref("cpo:Occurred"), "cpo:hasDeterminationTask": ref(ASSUMING)},
        {"@id": f"{occurrence}_EndTime", "@type": ["time:Instant", "hlo:Fixed", "hlo:Actual"]},
        {"@id": f"{occurrence}_Duration", "@type": ["time:Duration", "hlo:Fixed", "hlo:Actual"]},
        {"@id": receiving, "@type": ["cpo:CommissioningTask", "hlo:Fixed"], "schema:name": f"Receiving {name[0].lower() + name[1:]}",
         "schema:description": "The content came into the lab; when exactly is not recorded.",
         "cpo:hasStartTime": ref(f"{receiving}_StartTime"), "cpo:hasEndTime": ref(f"{receiving}_EndTime"),
         "cpo:hasDuration": ref(f"{receiving}_Duration"), "cpo:usedEquipment": [ref(f"device:{cid}")]},
        {"@id": f"{receiving}_StartTime", "@type": ["time:Instant", "hlo:Fixed", "hlo:Actual"]},
        {"@id": f"{receiving}_EndTime", "@type": ["time:Instant", "hlo:Fixed", "hlo:Actual"], "hlo:hasReference": ref(f"{receiving}_EndTime_Reference_1")},
        {"@id": f"{receiving}_EndTime_Reference_1", "@type": ["time:Instant", "hlo:Reference"], "hlo:hasReferenceType": ref("hlo:Assumed"),
         "rdfs:comment": receipt[1], "rdf:value": {"@value": receipt[0], "@type": "xsd:dateTime"}, "cpo:hasDeterminationTask": ref(ASSUMING)},
        {"@id": f"{receiving}_Duration", "@type": ["time:Duration", "hlo:Fixed", "hlo:Actual"]},
    ]
    return entries


def inventory_entries():
    stock = container(
        "spruce_wood_stock_SPRUCE-2025-03", "Spruce wood stock SPRUCE-2025-03", "hdpe_container_1L", CAB_B3,
        "The stock of air-dried, knife-milled spruce wood pellets (Picea abies) of the Chemotion collection, sample LCJ-28; LCJ-R5 takes "
        "'5g aliquot from SPRUCE-2025-03 stock' from it.",
        "From the ELN (Chemotion, inventory of sample LCJ-28: vendor 'Norske Skog (via SCCB)', order_number 'SPRUCE-2025-03', amount 500000 "
        "mg, cabinet B3, room B1-09, expiration 2028-03-01; sample description 'Lot SPRUCE-2025-03'). order_number read as the lot - the "
        f"sample description calls it so ({BY}).",
        "Spruce wood pellets, lot SPRUCE-2025-03", "cpo:SolidPhase", [("chem:Cellulose", "Cellulose"), ("chem:Lignin", "Lignin")],
        lot="SPRUCE-2025-03", manufacturer="organization:NorskeSkog", amount=("Mass", "0.5", "Chemotion inventory of sample LCJ-28: 500000 mg"),
        expiry=("2028-03-01T00:00:00Z", "Chemotion inventory of sample LCJ-28: expiration_date 2028-03-01"),
        receipt=("2026-04-17T05:20:53Z", "Not recorded when the stock came into the lab. Stamped with the creation of its sample LCJ-28 in "
                 f"Chemotion (2026-04-17T05:20:53Z) - an upper bound ({BY})."), records=(RECORD_R5,))
    batch = container(
        "spruce_wood_batch_BM-SPRUCE-NREL-01", "Spruce wood batch BM-SPRUCE-NREL-01", "hdpe_container_1L", CAB_B3,
        "The NREL-characterized batch of spruce wood pellets LCJ-R8 is run with (sample LCJ-159). It has no inventory record; the kind of "
        f"container and the cabinet are taken as those of the other stock ({BY}).",
        "From the ELN (Chemotion LCJ-R8: description 'RCF of the NREL-characterized spruce wood pellet batch (BM-SPRUCE-NREL-01)', setup "
        "notes 'the NREL-characterized spruce wood pellet sample (BM-SPRUCE-NREL-01)'); the batch name read as the lot "
        f"({BY}). Amount and supplier not known.",
        "Spruce wood pellets, batch BM-SPRUCE-NREL-01", "cpo:SolidPhase", [("chem:Cellulose", "Cellulose"), ("chem:Lignin", "Lignin")],
        lot="BM-SPRUCE-NREL-01",
        receipt=("2026-08-06T08:12:25Z", "Not recorded when the batch came into the lab. Stamped with the creation of its sample LCJ-159 in "
                 f"Chemotion (2026-08-06T08:12:25Z) - an upper bound ({BY})."), records=(RECORD_R8,))
    methanol = container(
        "methanol_bottle_646377_01", "Methanol bottle no. 1 (Sigma-Aldrich 646377)", "glass_bottle_1L", CAB_SOLV,
        "The methanol of the RCF runs. The Chemotion collection has two methanol entries of this article (LCJ-44, LCJ-45, both 1 L); taken as "
        f"one bottle ({BY}).",
        "From the ELN (Chemotion, inventory of samples LCJ-44, LCJ-45: vendor 'Sigma-Aldrich', order_number '646377-1L', amount 1 l, "
        "status 'available'). order_number read as the catalogue number - article 646377, pack size 1 L - not as a lot; the lot is not "
        f"known ({BY}).",
        "Methanol (Sigma-Aldrich 646377)", "cpo:LiquidPhase", [("chem:Methanol", "Methanol")],
        sku="646377-1L", manufacturer="organization:SigmaAldrich", amount=("Volume", "1", "Chemotion inventory of samples LCJ-44, LCJ-45: 1 l"),
        receipt=("2026-04-16T16:00:00Z", "Not recorded when the bottle came into the lab; its inventory samples were entered on 2026-06-05, "
                 "after LCJ-R5. The bottle was there before (Laura Fadler, 05.10.2026): stamped with the start of the day of LCJ-R5 "
                 "(17.04.2026 00:00 in Singapore) - an upper bound."), records=(RECORD_R5, RECORD_R8))
    tasks = [task("task:reading_chemotion_inventory", "cpo:LiteratureLookupTask", "Reading the inventory of the Chemotion export",
                  "Amounts and expiry dates of the containers, taken from the inventory records (table Chemical) of the Chemotion collection "
                  "export by projects/chemotion_example/curation/add_inventory.py (05.10.2026)."),
             task(ASSUMING, "cpo:AssumptionTask", "Assuming the receipts of the Chemotion inventory",
                  "The export records no delivery of the stocks and the bottle: the receipts are stamped with upper bounds, and the contents "
                  "are taken to have been in the lab.")]
    detail_ids = [e["@id"] for e in stock + batch + methanol]
    by_task = {"task:reading_chemotion_inventory": [], ASSUMING: []}
    for e in stock + batch + methanol:
        t = (e.get("cpo:hasDeterminationTask") or {}).get("@id")
        if t in by_task:
            by_task[t].append(e["@id"])
    for t in tasks:
        t["cpo:determines"] = [ref(i) for i in by_task[t["@id"]]]
        t["cpo:performedBy"] = [ref("person:LauraFadler")]
    times = task_times("task:reading_chemotion_inventory", "task:assuming_device_library_task_times") + task_times(ASSUMING, "task:assuming_device_library_task_times")
    return stock + batch + methanol + tasks + times, [f"{t}_StartTime_Reference_1" for t in by_task]


def main():
    path = LIB / "chemical_entity_library.jsonld"
    data = load_jsonld(path)
    add(data["@graph"], chemical_entries())
    save_jsonld(data, path)

    path = LIB / "organization_library.jsonld"
    data = load_jsonld(path)
    add(data["@graph"], organization_entries())
    save_jsonld(data, path)

    path = LIB / "device_library.jsonld"
    data = load_jsonld(path)
    add(data["@graph"], container_templates(data["@graph"]))
    append_determines(data["@graph"], "task:assuming_device_library_task_times", [f"{HDPE_DENSITY_TASK}_StartTime_Reference_1"])
    save_jsonld(data, path)

    path = LIB / "inventory_library.jsonld"
    data = load_jsonld(path)
    entries, stamps = inventory_entries()
    add(data["@graph"], entries)
    save_jsonld(data, path)
    # The start times of the two inventory tasks are determined by the assumption of the Device Library (one library, two files).
    path = LIB / "device_library.jsonld"
    data = load_jsonld(path)
    append_determines(data["@graph"], "task:assuming_device_library_task_times", stamps)
    save_jsonld(data, path)
    print("Inventory entries added.")


if __name__ == "__main__":
    main()
