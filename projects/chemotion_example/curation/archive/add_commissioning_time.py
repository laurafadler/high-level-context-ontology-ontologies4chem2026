"""
A time for the commissioning of Congjian Lin's RCF setup (autoclave, filter funnel, rotary evaporator;
05.10.2026): without one the run stops - a usage history must be ordered in time (N26). When the setup
was put into service is not known; the end of its commissioning is stamped with the start of the day
the first record was created (LCJ-R5, 17.04.2026 00:00 in Singapore) - an upper bound, as for the flask
of the eLabFTW case study (projects/fdca_cl2_elabftw_7849/curation/add_flask_commissioning.py). The
start stays empty.

Runs once after add_library_entries.py; stops if the entries exist already. Reads and writes the device
library through load_jsonld/save_jsonld (rule 2.14).

Usage (from the repository root):
    python projects/chemotion_example/curation/add_commissioning_time.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "generator"))
from helpers.file_handling import load_jsonld, save_jsonld  # noqa: E402

PATH = ROOT / "libraries" / "device_library.jsonld"
TASK = "task:commissioning_congjian_lin_rcf_setup"
ASSUMING = "task:assuming_congjian_lin_rcf_setup_commissioning"
STAMP = "2026-10-05T23:00:00Z"
UPPER = "2026-04-16T16:00:00Z"
BY = "suggested by Claude Code on 05.10.2026 for the Chemotion example, not yet confirmed"


def ref(i):
    return {"@id": i}


def main():
    data = load_jsonld(PATH)
    graph = data["@graph"]
    by_id = {e["@id"]: e for e in graph}
    assert ASSUMING not in by_id, f"{ASSUMING} exists already"
    end = by_id[f"{TASK}_EndTime"]
    assert "hlo:hasReference" not in end and "hlo:hasEvidence" not in end, "the commissioning has an end already"
    end["hlo:hasReference"] = ref(f"{TASK}_EndTime_Reference_1")
    graph += [
        {"@id": f"{TASK}_EndTime_Reference_1", "@type": ["time:Instant", "hlo:Reference"],
         "hlo:hasReferenceType": ref("hlo:Assumed"),
         "rdfs:comment": ("Not known when the setup was put into service. Stamped with the start of the day the first Chemotion record "
                          f"of the series was created (LCJ-R5, 17.04.2026 00:00 in Singapore) - an upper bound, not the moment it happened ({BY})."),
         "rdf:value": {"@value": UPPER, "@type": "xsd:dateTime"},
         "cpo:hasDeterminationTask": ref(ASSUMING)},
        {"@id": ASSUMING, "@type": ["cpo:AssumptionTask", "hlo:Fixed"],
         "schema:name": "Assuming when the RCF setup of Congjian Lin was put into service",
         "schema:description": ("The autoclave, filter funnel and rotary evaporator of the Chemotion records LCJ-R5 and LCJ-R8 have no "
                                "records. They were in service before the first experiment, so the end of their commissioning is "
                                "stamped with the start of the day of the first record - an upper bound."),
         "cpo:performedBy": [ref("person:LauraFadler")],
         "cpo:hasStartTime": ref(f"{ASSUMING}_StartTime"), "cpo:hasEndTime": ref(f"{ASSUMING}_EndTime"),
         "cpo:hasDuration": ref(f"{ASSUMING}_Duration"),
         "cpo:determines": [ref(f"{TASK}_EndTime_Reference_1")]},
        {"@id": f"{ASSUMING}_StartTime", "@type": ["time:Instant", "hlo:Fixed", "hlo:Actual"],
         "hlo:hasReference": ref(f"{ASSUMING}_StartTime_Reference_1")},
        {"@id": f"{ASSUMING}_StartTime_Reference_1", "@type": ["time:Instant", "hlo:Reference"],
         "hlo:hasReferenceType": ref("hlo:Assumed"),
         "rdfs:comment": f"No record of when this was done. Stamped with the moment the entries were written down ({STAMP}) - an upper bound, not the moment it happened.",
         "rdf:value": {"@value": STAMP, "@type": "xsd:dateTime"},
         "cpo:hasDeterminationTask": ref("task:assuming_device_library_task_times")},
        {"@id": f"{ASSUMING}_EndTime", "@type": ["time:Instant", "hlo:Fixed", "hlo:Actual"]},
        {"@id": f"{ASSUMING}_Duration", "@type": ["time:Duration", "hlo:Fixed", "hlo:Actual"]},
    ]
    times_task = by_id["task:assuming_device_library_task_times"]
    determines = times_task.get("cpo:determines")
    times_task["cpo:determines"] = (determines if isinstance(determines, list) else [determines]) + [ref(f"{ASSUMING}_StartTime_Reference_1")]
    save_jsonld(data, PATH)
    print("Commissioning time of the RCF setup added.")


if __name__ == "__main__":
    main()
