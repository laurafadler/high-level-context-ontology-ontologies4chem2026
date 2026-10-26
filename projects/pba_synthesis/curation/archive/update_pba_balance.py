"""
The balance of the nickel(II) chloride stock solution is a Fisherbrand PAS214C (08.10.2026, named by Laura Fadler and
Meng Kong, questions_meng_pba_outcomes.md, N21): an analytical balance, 210 g, readability 0.0001 g, internal
calibration - not recorded at the time ('Fisher Scientific scale' in the preparation record). Its data sheet is not
available any more; size and mass are taken from the similar current model Fisherbrand FAS224 (cat. no. 15927500,
220 g, 0.0001 g): 317 x 201 x 303 mm (depth x width x height) from its product page, net weight 4.5 kg from the
Fisherbrand brochure - assumed. The record's measurement error of 0.001 g stays as documented (it may be wrong).

The entry tools cannot change an existing entry (device_20261007_2239.yaml wrote it) - the type 'device' would need
an update mode; until then this script. It changes device:balance_L208 in place, so that its usage history (the
preparation of the nickel(II) chloride solution) stays: model, name and texts; length, width, height and mass as
references of a new assumption task; the outer volume calculated anew. Runs once. Commit the libraries afterwards.

Usage (from the repository root):
    python projects/pba_synthesis/curation/update_pba_balance.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "generator" / "workflow" / "library_prerun"))
sys.path.insert(0, str(ROOT / "generator"))
import path_definitions  # noqa: E402
from fixed_reaction_from_template import LibraryFile  # noqa: E402

B = "balance_L208"
STAMP = "2026-10-08T18:00:00Z"
TASK = "task:assuming_balance_L208_from_FAS224"
OLD_TASK = "task:assuming_device_20261007_2239"
TIMES_TASK = "task:assuming_device_library_task_times"
DECIDED = "Laura Fadler and Meng Kong, 08.10.2026 (questions_meng_pba_outcomes.md, N21)"
PAGE = "https://www.fishersci.co.uk/shop/products/analytical-precision-balances-10/15927500"
BROCHURE = "https://assets.fishersci.com/TFS-Assets/CCG/EU/Fisherbrand/brochures/13377_NPI_Balances_EN.pdf"
SIMILAR = (f"taken from the similar current model Fisherbrand FAS224 (cat. no. 15927500, 220 g, readability 0.0001 g) - the "
           f"data of the PAS214C are not available ({DECIDED})")
# reference ID -> new value, comment
VALUES = {
    f"device:{B}_Length_Reference_1": ("0.317", f"Length (depth) of the device, 317 mm: {SIMILAR}; product page {PAGE}."),
    f"device:{B}_Width_Reference_1": ("0.201", f"Width of the device, 201 mm: {SIMILAR}; product page {PAGE}."),
    f"device:{B}_Height_Reference_1": ("0.303", f"Height of the device with its draft shield, 303 mm: {SIMILAR}; product page {PAGE}."),
    f"material:{B}_Body_SolidPhase_Mass_Reference_1": ("4.5", f"Mass of the device, net weight 4.5 kg: {SIMILAR}; Fisherbrand "
                                                              f"brochure 'Analytical and Precision Balances', {BROCHURE}."),
}
ENVELOPE = 0.317 * 0.201 * 0.303
ENVELOPE_TEXT = f"0.317 m x 0.201 m x 0.303 m = {ENVELOPE:.9g} m3."
MODEL = ("Fisherbrand PAS214C - analytical balance, 210 g, readability 0.0001 g, internal calibration; named by "
         f"{DECIDED}, not recorded at the time")
COMMENT = ("'Fisher Scientific scale' in the preparation record of the nickel(II) chloride stock solution (Chuyue Li). The "
           f"model, a Fisherbrand PAS214C (readability 0.0001 g), was named by {DECIDED} - not confirmed by a record. The "
           "record's measurement error of 0.001 g is kept as documented; it may be wrong. Size and mass are those of the "
           "similar current model Fisherbrand FAS224 (assumed).")


def main():
    devices = LibraryFile(path_definitions.DEVICE_LIBRARY_PATH)
    materials = LibraryFile(path_definitions.MATERIAL_LIBRARY_PATH)
    by_id = {**devices.by_id(), **materials.by_id()}
    if TASK in by_id:
        print(f"{TASK} exists already - nothing to do")
        return
    device = by_id[f"device:{B}"]
    device["schema:name"] = "Analytical balance (Lab 208)"
    device["schema:model"] = MODEL
    device["rdfs:comment"] = COMMENT
    device["schema:comment"] += (f" Model, size and mass changed on 08.10.2026 ({DECIDED}) by "
                                 "projects/pba_synthesis/curation/update_pba_balance.py.")
    by_id[f"task:commissioning_{B}"]["schema:name"] = "Commissioning Analytical balance (Lab 208)"

    for ref_id, (value, comment) in VALUES.items():
        ref = by_id[ref_id]
        ref["qudt:value"] = {"@value": value, "@type": "xsd:decimal"}
        ref["rdfs:comment"] = comment
        ref["cpo:hasDeterminationTask"] = {"@id": TASK}
    old = by_id[OLD_TASK]
    old["cpo:determines"] = [r for r in old["cpo:determines"] if r["@id"] not in VALUES]

    volume = by_id[f"device:{B}_OuterVolume_Evidence_1"]
    volume["qudt:value"] = {"@value": f"{ENVELOPE:.9g}", "@type": "xsd:decimal"}
    volume["rdfs:comment"] = ENVELOPE_TEXT
    by_id[f"task:calculating_{B}_OuterVolume"]["schema:description"] = ENVELOPE_TEXT
    body = f"From the mass (4.5 kg) and the steel density (8000 kg/m3): 0.0005625 m3 - not the envelope ({ENVELOPE:.9g} m3), the device is not solid steel."
    by_id[f"material:{B}_Body_SolidPhase_Volume_Evidence_1"]["rdfs:comment"] = body
    by_id[f"task:calculating_{B}_Body_SolidPhase_Volume"]["schema:description"] = body

    preparation = by_id["task:preparing_stock_solution_nickel_chloride_01"]
    preparation["schema:description"] = preparation["schema:description"].replace(
        "Fisher Scientific balance - model not recorded",
        f"Fisher Scientific balance - not recorded, a Fisherbrand PAS214C according to {DECIDED}")

    start = f"{TASK}_StartTime"
    devices.graph.extend([
        {"@id": TASK, "@type": ["cpo:AssumptionTask", "hlo:Fixed"],
         "schema:name": "Assuming the size and mass of the balance from a similar model",
         "schema:description": ("The balance is a Fisherbrand PAS214C, whose data sheet is not available. Its length, width, "
                                "height and mass are taken from the similar current model Fisherbrand FAS224 (cat. no. "
                                f"15927500): product page {PAGE}, brochure {BROCHURE} - {DECIDED}."),
         "cpo:performedBy": [{"@id": "person:LauraFadler"}, {"@id": "person:MengKong"}],
         "cpo:hasStartTime": {"@id": start}, "cpo:hasEndTime": {"@id": f"{TASK}_EndTime"},
         "cpo:hasDuration": {"@id": f"{TASK}_Duration"},
         "cpo:determines": [{"@id": r} for r in VALUES]},
        {"@id": start, "@type": ["time:Instant", "hlo:Fixed", "hlo:Actual"], "hlo:hasReference": {"@id": f"{start}_Reference_1"}},
        {"@id": f"{start}_Reference_1", "@type": ["time:Instant", "hlo:Reference"], "hlo:hasReferenceType": {"@id": "hlo:Assumed"},
         "rdfs:comment": (f"No record of when this was done. Stamped with the moment the values were written down ({STAMP}) - "
                          "an upper bound, not the moment it happened."),
         "rdf:value": {"@value": STAMP, "@type": "xsd:dateTime"}, "cpo:hasDeterminationTask": {"@id": TIMES_TASK}},
        {"@id": f"{TASK}_EndTime", "@type": ["time:Instant", "hlo:Fixed", "hlo:Actual"]},
        {"@id": f"{TASK}_Duration", "@type": ["time:Duration", "hlo:Fixed", "hlo:Actual"]},
    ])
    by_id[TIMES_TASK]["cpo:determines"].append({"@id": f"{start}_Reference_1"})
    devices.save()
    materials.save()
    print(f"device:{B} changed; {TASK} added")


if __name__ == "__main__":
    main()
