"""
Counter-check (rule 7.14) for two shapes of shapes/DataQualityShapes.ttl:
hlo:Task_Times_Experiment_Shape / hlo:Task_Times_Library_Shape (rule 4.6) and hlo:Persons_EachLevel_Shape
(rule 7c.4). Each case damages ONE entity of a copy of the amidation crate (small, so the check is quick),
validates it against the Data Quality shapes only, and expects exactly the listed change in the counts per
shape against the undamaged crate - as generator/tests/rule_4_1_shapes_test.py does.

Writes the damaged copies to %TEMP%/cr/damaged_times.

Run from the repository root:
    python generator/tests/task_times_persons_shapes_test.py
"""
import copy
import json
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import path_definitions  # noqa: E402
import pyshacl  # noqa: E402
from rdflib import RDF, Graph, Namespace  # noqa: E402
from workflow.run_shacl import OTHER_CRATE_STAND_INS, build_data_graph, build_shape_to_requirement  # noqa: E402

SH = Namespace("http://www.w3.org/ns/shacl#")
SHAPES = Graph()
SHAPES.parse(str(path_definitions.DATA_QUALITY_SHAPES), format="turtle")
SHAPE_NAMES = build_shape_to_requirement(SHAPES)

CRATE = Path("projects/amidation_ai4green_ai4_001/crate_completed/ro-crate-metadata.json")
OUT = Path(os.environ["TEMP"]) / "cr" / "damaged_times"
OUT.mkdir(parents=True, exist_ok=True)
P = "crate:amidation_ai4green_ai4_001/"
data = json.load(open(CRATE, encoding="utf-8"))
EXP = "hlo:Task_Times_Experiment_Shape"
LIB = "hlo:Task_Times_Library_Shape"
PERSONS = "hlo:Persons_EachLevel_Shape"


def ent(d, i):
    return next(e for e in d["@graph"] if e["@id"] == P + i)


def drop(i, prop):
    def damage(d):
        del ent(d, i)[prop]
    damage.__name__ = f"drop_{prop.split(':')[-1]}_{i[:30]}"
    return damage


def add_library_task(types, with_times):
    def damage(d):
        task = {"@id": "task:counter_test_library_task", "@type": types}
        if with_times:
            for prop in ("cpo:hasStartTime", "cpo:hasEndTime", "cpo:hasDuration"):
                task[prop] = {"@id": f"task:counter_test_library_task_{prop.split(':')[-1]}"}
        d["@graph"].append(task)
    damage.__name__ = "library_task_" + "_".join(t.split(":")[-1] for t in types) + ("_with_times" if with_times else "")
    return damage


CASES = [
    ("experiment task without start", drop("Task_Mixing_at_room_temperature_ExperimentSpecific_1", "cpo:hasStartTime"), {EXP: 1}),
    ("experiment task without duration", drop("Task_Experimental_procedure_ExperimentSpecific_1", "cpo:hasDuration"), {EXP: 1}),
    ("subtask without start offset", drop("Task_Preparation_ExperimentSpecific_1", "cpo:hasStartOffset"), {EXP: 1}),
    ("series template without times", drop("Task_Planning_the_series_SeriesSpecific", "cpo:hasStartTime"), {}),
    ("library task without times", add_library_task(["cpo:AssumptionTask", "hlo:Fixed"], False), {LIB: 1}),
    ("library task with times", add_library_task(["cpo:AssumptionTask", "hlo:Fixed"], True), {}),
    ("library template without times", add_library_task(["cpo:Task", "hlo:Fixed", "hlo:Template"], False), {}),
    ("experiment without creator", drop("SingleExperiment_1", "cpo:hasCreator"), {PERSONS: 1}),
    ("series without experimenter", drop("ExperimentalSeries", "cpo:hasExperimenter"), {PERSONS: 1}),
]


def counts(crate_path):
    _, results, _ = pyshacl.validate(build_data_graph(Path(crate_path), []), shacl_graph=SHAPES, inference="none",
                                     advanced=True, js=False)
    details = set(results.objects(None, SH.detail))
    # Results at the stand-ins of other crates' nodes are not counted (run_shacl.py).
    return Counter(SHAPE_NAMES.get(results.value(r, SH.sourceShape), "(unassigned)")
                   for r in results.subjects(RDF.type, SH.ValidationResult)
                   if r not in details and results.value(r, SH.focusNode) not in OTHER_CRATE_STAND_INS)


base = counts(CRATE)
print("undamaged:", dict(base))
ok = not any(base[k] for k in (EXP, LIB, PERSONS))
for label, damage, expected in CASES:
    d = copy.deepcopy(data)
    damage(d)
    path = OUT / f"{damage.__name__}.jsonld"
    path.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    got = counts(path)
    diff = {k: got[k] - base[k] for k in set(got) | set(base) if got[k] != base[k]}
    passed = diff == expected
    ok &= passed
    print(f"  {label:30s} [{'OK' if passed else 'WRONG'}] {diff}")
print("RESULT:", "OK" if ok else "FAILED")
raise SystemExit(0 if ok else 1)
