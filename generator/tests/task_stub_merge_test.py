"""
Test for the safeguard used when merging task placeholders
(creation/task_functions.py: _stub_is_compatible / _absorb_stub).

Background: every value receives its task as a placeholder as soon as it is recorded
(helpers/evidence_reference.py: ensure_determination_task_stub), several placeholders arise
whenever ONE activity determined several values - a GC measurement yields five
concentrations. They are merged in the tasks stage, but only where the placeholder does not
contradict the task being described. This test checks exactly that condition, because in a
normal pipeline run it often does not come up at all (there is then only one placeholder per
class) and so could break unnoticed.

Runs without the pipeline and without an answer file, against the ontology alone.

Run from the repository root:
    PYTHONPATH=. python generator/tests/task_stub_merge_test.py
"""
# Runs from generator/tests/ - the generator has to be on the search path.
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from helpers.ontology_functions import initialize_ontologies
import creation.task_functions as tf


def run():
    namespace_collection = initialize_ontologies()

    series_task = {
        "@id": "#T", "@type": ["cpo:MeasurementTask", "hlo:SeriesSpecific"],
        "schema:name": "GC run",
        "cpo:usedEquipment": [{"@id": "#gc001"}],
        "cpo:determines": [{"@id": "#V0"}],
    }
    experiment_task = {"@id": "#T_ExperimentSpecific_1", "@type": ["cpo:MeasurementTask", "hlo:ExperimentSpecific"]}

    cases = [
        # (description, task, placeholder, expected compatible?)
        ("bare placeholder (normal case)", series_task,
         {"@id": "#S1", "@type": ["cpo:MeasurementTask", "hlo:SeriesSpecific"], "cpo:determines": [{"@id": "#V1"}]}, True),
        ("same equipment", series_task,
         {"@id": "#S2", "@type": ["cpo:MeasurementTask", "hlo:SeriesSpecific"], "cpo:usedEquipment": [{"@id": "#gc001"}]}, True),
        ("other equipment", series_task,
         {"@id": "#S3", "@type": ["cpo:MeasurementTask", "hlo:SeriesSpecific"], "cpo:usedEquipment": [{"@id": "#balance001"}]}, False),
        ("another task class", series_task,
         {"@id": "#S4", "@type": ["cpo:ObservationTask", "hlo:SeriesSpecific"]}, False),
        # Would be lost silently: _absorb_stub takes over only the links to values.
        ("placeholder with a function of its own", series_task,
         {"@id": "#S5", "@type": ["cpo:MeasurementTask", "hlo:SeriesSpecific"], "cpo:realizesFunction": {"@id": "cpo:Mixing"}}, False),
        ("another level", series_task,
         {"@id": "#S6_ExperimentSpecific_1", "@type": ["cpo:MeasurementTask", "hlo:ExperimentSpecific"]}, False),
        ("anderes Experiment", experiment_task,
         {"@id": "#S7_ExperimentSpecific_2", "@type": ["cpo:MeasurementTask", "hlo:ExperimentSpecific"]}, False),
        ("gleiches Experiment", experiment_task,
         {"@id": "#S8_ExperimentSpecific_1", "@type": ["cpo:MeasurementTask", "hlo:ExperimentSpecific"]}, True),
    ]

    ok = True
    print("=== _stub_is_compatible ===")
    for label, task, stub, expected in cases:
        actual = tf._stub_is_compatible(stub, task, namespace_collection)
        if actual != expected:
            ok = False
        print(f"  {label:34s} -> {'compatible' if actual else 'refused':11s} [{'OK' if actual == expected else 'FALSCH'}]")

    # The actual merging: values move along in both directions, the placeholder
    # disappears from the to-do list.
    print("\n=== _absorb_stub ===")
    value = {"@id": "#V1", "@type": ["cpo:ProcessVariable", "hlo:SeriesSpecific", "hlo:Evidence"],
             "cpo:hasDeterminationTask": {"@id": "#S1"}}
    task = dict(series_task)
    task["cpo:determines"] = [{"@id": "#V0"}]
    stub = {"@id": "#S1", "@type": ["cpo:MeasurementTask", "hlo:SeriesSpecific"], "cpo:determines": [{"@id": "#V1"}]}
    datagraph = {"@graph": [value, task]}
    todo_list = [stub]

    tf._absorb_stub(task, stub, namespace_collection, datagraph, todo_list)

    checks = [
        ("value now hangs at the task", [v["@id"] for v in task["cpo:determines"]] == ["#V0", "#V1"]),
        ("inverse direction moved", value["cpo:hasDeterminationTask"] == {"@id": "#T"}),
        ("placeholder removed from the to-do list", todo_list == []),
    ]
    for label, passed in checks:
        if not passed:
            ok = False
        print(f"  {label:34s} [{'OK' if passed else 'WRONG'}]")

    # A swallowed placeholder ceases to exist - its template must not point at it afterwards.
    # Without that a series task kept an hlo:hasSpecialization pointing at an entity that never got
    # into the graph: noticed when the three GC measurements were merged into one, where
    # it then pointed at six experiment tasks, of which only two existed.
    print("\n=== _absorb_stub: the template no longer points at the swallowed stub ===")
    template = {"@id": "#Series", "@type": ["cpo:MeasurementTask", "hlo:SeriesSpecific"],
                "hlo:hasSpecialization": [{"@id": "#Exp1"}, {"@id": "#Exp2"}]}
    keeper = {"@id": "#Exp1", "@type": ["cpo:MeasurementTask", "hlo:ExperimentSpecific"],
              "hlo:specializationOf": {"@id": "#Series"}}
    swallowed = {"@id": "#Exp2", "@type": ["cpo:MeasurementTask", "hlo:ExperimentSpecific"],
                 "hlo:specializationOf": {"@id": "#Series"}, "cpo:determines": [{"@id": "#V2"}]}
    datagraph = {"@graph": [template, keeper]}
    todo_list = [swallowed]

    tf._absorb_stub(keeper, swallowed, namespace_collection, datagraph, todo_list)

    remaining = [ref["@id"] for ref in tf.as_list(template.get("hlo:hasSpecialization"))]
    checks = [
        ("the template points only at #Exp1", remaining == ["#Exp1"]),
        ("the value moved along", [v["@id"] for v in keeper.get("cpo:determines", [])] == ["#V2"]),
    ]
    for label, passed in checks:
        if not passed:
            ok = False
        print(f"  {label:34s} [{'OK' if passed else 'WRONG'}]")

    print("\nRESULT:", "OK" if ok else "FAILED")
    return ok


if __name__ == "__main__":
    raise SystemExit(0 if run() else 1)
