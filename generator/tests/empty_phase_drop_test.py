"""Test for leaving empty phases out of an experiment (creation/phase_functions.py:
drop_empty_experiment_phases, rule 3.13).

A small crate by hand: a stream that carries only a substance absent from experiment 1, one that carries something
else, both in two experiments. After the drop, experiment 1 has no such stream and no phase of it, nothing that only
they owned, no reference to them; experiment 2 is untouched and still counts as experiment 2; the stock bottle the
stream came from is noted as taking no part in experiment 1. It runs without the pipeline.

Run from the repository root:
    PYTHONPATH=. python generator/tests/empty_phase_drop_test.py
"""
# Runs from generator/tests/ - the generator has to be on the search path.
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import creation.phase_functions as pf

S, E = "hlo:SeriesSpecific", "hlo:ExperimentSpecific"


def ref(i):
    return {"@id": i}


def build():
    g = []

    def add(i, types, **props):
        g.append({"@id": i, "@type": types, **props})

    for name, species in (("Mn", "chem:MnSalt"), ("Ni", "chem:NiSalt")):
        add(f"Material_{name}_SeriesSpecific", ["cpo:Stream", S],
            **{"hlo:hasSpecialization": [ref(f"Material_{name}_ExperimentSpecific_1"), ref(f"Material_{name}_ExperimentSpecific_2")],
               "dcterms:hasPart": [ref(f"Phase_{name}_SeriesSpecific")]})
        add(f"Phase_{name}_SeriesSpecific", ["cpo:SolidPhase", S],
            **{"dcterms:hasPart": [ref(species)], "dcterms:isPartOf": ref(f"Material_{name}_SeriesSpecific"),
               "hlo:hasSpecialization": [ref(f"Phase_{name}_ExperimentSpecific_1"), ref(f"Phase_{name}_ExperimentSpecific_2")]})
        for n in (1, 2):
            empty = name == "Mn" and n == 1
            add(f"Material_{name}_ExperimentSpecific_{n}", ["cpo:Stream", E],
                **{"hlo:specializationOf": ref(f"Material_{name}_SeriesSpecific"),
                   "dcterms:hasPart": [ref(f"Phase_{name}_ExperimentSpecific_{n}")],
                   "cpo:flowsFrom": ref(f"bottle_{name}_opening_ExperimentSpecific_{n}"),
                   "cpo:hasFlowrate": ref(f"Flowrate_{name}_ExperimentSpecific_{n}")})
            add(f"Phase_{name}_ExperimentSpecific_{n}", ["cpo:SolidPhase", E],
                **{"hlo:specializationOf": ref(f"Phase_{name}_SeriesSpecific"),
                   "dcterms:isPartOf": ref(f"Material_{name}_ExperimentSpecific_{n}"),
                   "cpo:hasMass": ref(f"Mass_{name}_ExperimentSpecific_{n}"),
                   **({} if empty else {"dcterms:hasPart": [ref(species)]})})
            add(f"Flowrate_{name}_ExperimentSpecific_{n}", ["cpo:ProcessVariable", E])
            add(f"Mass_{name}_ExperimentSpecific_{n}", ["cpo:ProcessVariable", E])
            add(f"bottle_{name}_ExperimentSpecific_{n}", ["cpo:ChemicalContainer", E],
                **{"cpo:hasPort": [ref(f"bottle_{name}_opening_ExperimentSpecific_{n}")]})
            add(f"bottle_{name}_opening_ExperimentSpecific_{n}", ["cpo:DeviceOpening", E],
                **{"cpo:isPortOf": ref(f"bottle_{name}_ExperimentSpecific_{n}"),
                   "cpo:hasOutgoingStream": [ref(f"Material_{name}_ExperimentSpecific_{n}")]})
    add("Context_Exp1", ["hlo:Context", E],
        **{"hlo:contextDescribedBy": [ref("Mass_Mn_ExperimentSpecific_1"), ref("Mass_Ni_ExperimentSpecific_1")]})
    return {"@graph": g}


def run():
    ok = True

    def check(label, passed):
        nonlocal ok
        if not passed:
            ok = False
        print(f"  {label:66s} [{'OK' if passed else 'WRONG'}]")

    datagraph = build()
    ids = lambda: {e["@id"] for e in datagraph["@graph"]}  # noqa: E731
    by = lambda i: next(e for e in datagraph["@graph"] if e["@id"] == i)  # noqa: E731
    phases_1 = [by("Phase_Mn_ExperimentSpecific_1"), by("Phase_Ni_ExperimentSpecific_1")]
    todo = [{"@id": "Phase_Mn_ExperimentSpecific_1"}, {"@id": "Phase_Ni_ExperimentSpecific_1"}, {"@id": "Phase_Mn_ExperimentSpecific_2"}]
    local = [{"@id": "Mass_Mn_ExperimentSpecific_1"}]

    pf._ABSENT_SPECIES.clear()
    pf._DEVICES_ONLY_FOR_DROPPED.clear()
    check("nothing absent: nothing dropped", pf.drop_empty_experiment_phases(phases_1, 1, datagraph, todo, local) == phases_1
          and len(ids()) == len(build()["@graph"]))

    pf._ABSENT_SPECIES[1] = {"chem:MnSalt"}
    kept = pf.drop_empty_experiment_phases(phases_1, 1, datagraph, todo, local)
    gone = {"Material_Mn_ExperimentSpecific_1", "Phase_Mn_ExperimentSpecific_1", "Flowrate_Mn_ExperimentSpecific_1",
            "Mass_Mn_ExperimentSpecific_1"}
    check("the empty phase, its stream and what they own are gone", not (gone & ids()))
    check("the returned phases are the remaining ones", [p["@id"] for p in kept] == ["Phase_Ni_ExperimentSpecific_1"])
    check("the series keeps stream and phase", {"Material_Mn_SeriesSpecific", "Phase_Mn_SeriesSpecific"} <= ids())
    check("the series stream names only experiment 2",
          by("Material_Mn_SeriesSpecific")["hlo:hasSpecialization"] == [ref("Material_Mn_ExperimentSpecific_2")])
    check("the port has no stream any more", "cpo:hasOutgoingStream" not in by("bottle_Mn_opening_ExperimentSpecific_1"))
    check("the context lost only the dropped value",
          by("Context_Exp1")["hlo:contextDescribedBy"] == [ref("Mass_Ni_ExperimentSpecific_1")])
    check("the to-do lists lost the dropped items",
          [t["@id"] for t in todo] == ["Phase_Ni_ExperimentSpecific_1", "Phase_Mn_ExperimentSpecific_2"] and local == [])
    check("experiment 2 untouched", {"Material_Mn_ExperimentSpecific_2", "Phase_Mn_ExperimentSpecific_2",
                                     "Mass_Mn_ExperimentSpecific_2"} <= ids())
    check("experiment 2 still counts as experiment 2 (from its ID)",
          pf.get_material_experiment_number(by("Material_Mn_ExperimentSpecific_2"), datagraph) == 2)
    check("the stock bottle takes no part in experiment 1",
          pf.devices_only_for_dropped(1) == {"bottle_Mn_ExperimentSpecific_1"})
    check("the other bottle is not noted", "bottle_Ni_ExperimentSpecific_1" not in pf.devices_only_for_dropped(1))

    print("ALL OK" if ok else "FAILED")
    return ok


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
