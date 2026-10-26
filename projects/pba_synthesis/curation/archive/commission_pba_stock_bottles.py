"""
Rule 5.5 for the three PBA stock solutions (07.10.2026, found by the N7 session): a usage history starts with a
commissioning. add_pba_stock_solutions.py started them with the preparation; here the empty bottle is taken into use
first - not recorded, taken as the moment its preparation started (as the library entry type prepared_container does).
The assumed times belong to task:assuming_pba_stock_solutions. Commit the libraries afterwards.

Usage (from the repository root):
    python projects/pba_synthesis/curation/commission_pba_stock_bottles.py
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "generator" / "workflow" / "library_prerun"))
sys.path.insert(0, str(ROOT / "generator"))
import path_definitions  # noqa: E402
from fixed_reaction_from_template import LibraryFile  # noqa: E402

NAMES = ["stock_solution_potassium_ferrocyanide_01", "stock_solution_nickel_chloride_01", "stock_solution_manganese_chloride_01"]
ASSUMING = "task:assuming_pba_stock_solutions"


def ref(i):
    return {"@id": i}


def main():
    devices = LibraryFile(path_definitions.DEVICE_LIBRARY_PATH)
    materials = LibraryFile(path_definitions.MATERIAL_LIBRARY_PATH)
    d, m = devices.by_id(), materials.by_id()
    added = []
    for name in NAMES:
        device = d[f"device:{name}"]
        task = f"task:commissioning_{name}"
        if task in d:
            sys.exit(f"{task} exists already - nothing written.")
        preparation = f"task:preparing_{name}"
        start_instant = m[f"{preparation}_StartTime"]
        member = m[(start_instant.get("hlo:hasEvidence") or start_instant.get("hlo:hasReference"))["@id"]]
        when = member["rdf:value"]["@value"]
        devices.graph.append({"@id": task, "@type": ["cpo:CommissioningTask", "hlo:Fixed"], "schema:name": f"Commissioning {device['schema:name']}",
                              "schema:description": "The empty stock bottle taken into use in the lab - not recorded, taken as the moment its preparation started.",
                              "cpo:hasStartTime": ref(f"{task}_StartTime"), "cpo:hasEndTime": ref(f"{task}_EndTime"),
                              "cpo:hasDuration": ref(f"{task}_Duration"), "cpo:usedEquipment": [ref(f"device:{name}")]})
        for key, text in (("StartTime", "Start"), ("EndTime", "End")):
            instant = f"{task}_{key}"
            devices.graph.append({"@id": instant, "@type": ["time:Instant", "hlo:Fixed", "hlo:Actual"], "hlo:hasReference": ref(f"{instant}_Reference_1")})
            devices.graph.append({"@id": f"{instant}_Reference_1", "@type": ["time:Instant", "hlo:Reference"],
                                  "hlo:hasReferenceType": ref("hlo:Assumed"),
                                  "rdfs:comment": f"{text} of the commissioning - not recorded: the empty container taken into use when its preparation started (rule 5.5).",
                                  "rdf:value": {"@value": when, "@type": "xsd:dateTime"}, "cpo:hasDeterminationTask": ref(ASSUMING)})
            added.append(f"{instant}_Reference_1")
        devices.graph.append({"@id": f"{task}_Duration", "@type": ["time:Duration", "hlo:Fixed", "hlo:Actual"]})
        history = device.get("cpo:hasUsageHistory", [])
        device["cpo:hasUsageHistory"] = [ref(task)] + [h for h in history if h["@id"] != task]
    assuming = d[ASSUMING]
    assuming["cpo:determines"] = assuming.get("cpo:determines", []) + [ref(i) for i in added]
    devices.save()
    print(f"3 stock bottles commissioned before their preparation ({len(added)} assumed times)")


if __name__ == "__main__":
    main()
