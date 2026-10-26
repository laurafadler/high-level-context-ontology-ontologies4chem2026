"""
Counter-check (rule 7.14) for the rule 4.1 shapes in shapes/DataQualityShapes.ttl
(hlo:Actual_NoValue_Shape, hlo:Value_Variable_Shape, hlo:Value_Type_Shape,
hlo:Value_DeterminationTask_Shape, hlo:Value_TaskBothWays_Shape): each case damages ONE entity of
a copy of the hydrogenation crate, validates it against shapes/DataQualityShapes.ttl and expects exactly
the listed change in the counts per shape against the undamaged crate.

Includes the three exceptions of rule 4.1: a reaction mechanism reads type and task through
hlo:specializationOf (and no other value may), the creation/modification date of a file may
carry rdf:value on its Actual (and no other Actual, and no qudt:value there), and a value whose
tasks are all library tasks needs no back link (and only then).

Writes the damaged copies to %TEMP%/cr/damaged. Validates in this process with the data graph of
generator/workflow/run_shacl.py and only the Data Quality shapes, counted the way run_shacl.py counts
(a full run_shacl.py per case takes minutes and writes reports/shacl_baseline.txt). The rule 4.1 shapes and the unit shape
are all there; a damage that also changed a context requirement would no longer show here.

Run from the repository root:
    python generator/tests/rule_4_1_shapes_test.py
"""
import copy
import json
import os
import sys
from collections import Counter
from pathlib import Path

# Runs from generator/tests/ - the generator has to be on the search path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import path_definitions  # noqa: E402
import pyshacl  # noqa: E402
from rdflib import RDF, Graph, Namespace  # noqa: E402
from workflow.run_shacl import build_data_graph, build_shape_to_requirement  # noqa: E402

SH = Namespace("http://www.w3.org/ns/shacl#")
SHAPES = Graph()
SHAPES.parse(str(path_definitions.DATA_QUALITY_SHAPES), format="turtle")
SHAPE_NAMES = build_shape_to_requirement(SHAPES)

CRATE = Path("projects/hydrogenation_rdy_2026_09/crate/ro-crate-metadata.json")
OUT = Path(os.environ["TEMP"]) / "cr" / "damaged"
OUT.mkdir(parents=True, exist_ok=True)
P = "crate:hydrogenation_rdy_2026_09/"
data = json.load(open(CRATE, encoding="utf-8"))


def ent(d, i):
    return next(e for e in d["@graph"] if e["@id"] == P + i)


def ids(v):
    return [x["@id"] for x in (v if isinstance(v, list) else [v]) if isinstance(x, dict)]


EVIDENCE = "Mass_Phase_RDY_Phase_Evidence_1_ExperimentSpecific_1"
REFERENCE = "Volume_Material_Sample_In_Vial_Reference_1_ExperimentSpecific_1"
MECHANISM = "Hydrogenation_Adiponitrile_Pt_Mechanism_Reference_1_ExperimentSpecific_1"


def drop_task(d):
    del ent(d, EVIDENCE)["cpo:hasDeterminationTask"]


def drop_from_determines(d):
    v = ent(d, EVIDENCE)
    task = next(e for e in d["@graph"] if e["@id"] == ids(v["cpo:hasDeterminationTask"])[0])
    task["cpo:determines"] = [x for x in task["cpo:determines"] if x["@id"] != v["@id"]] if isinstance(task["cpo:determines"], list) else []


def drop_type(d):
    del ent(d, REFERENCE)["hlo:hasReferenceType"]


def detach(d):
    owner = ent(d, "Volume_Material_Sample_In_Vial_ExperimentSpecific_1")
    del owner["hlo:hasReference"]


def value_on_actual(d):
    ent(d, "Volume_Material_Sample_In_Vial_ExperimentSpecific_1")["qudt:value"] = {"@value": "1", "@type": "xsd:decimal"}


def rdf_value_on_other_actual(d):
    ent(d, "Volume_Material_Sample_In_Vial_ExperimentSpecific_1")["rdf:value"] = {"@value": "2026-09-16T11:43:56+01:00", "@type": "xsd:dateTime"}


def qudt_value_on_file_date(d):
    # The exception holds only for rdf:value - a unit with it, so that only the new shape fires.
    e = ent(d, "DateCreated_File_SOP_hydrogenation_dummy.docx_SeriesSpecific")
    e["qudt:value"] = {"@value": "1", "@type": "xsd:decimal"}
    e["qudt:hasUnit"] = {"@id": "unit:SEC"}


def mechanism_chain_broken(d):
    # Without the chain the experiment mechanism reaches neither type nor task.
    del ent(d, MECHANISM)["hlo:specializationOf"]


def chain_not_for_other_values(d):
    # An ordinary value without a task must not rescue itself via specializationOf.
    v = ent(d, REFERENCE)
    task_id = ids(v.pop("cpo:hasDeterminationTask"))[0]
    task = next(e for e in d["@graph"] if e["@id"] == task_id)
    task["cpo:determines"] = [x for x in (task["cpo:determines"] if isinstance(task["cpo:determines"], list) else [task["cpo:determines"]]) if x["@id"] != v["@id"]]
    v["hlo:specializationOf"] = {"@id": "device:vessel001_InnerDiameter_Reference_1"}


LIBRARY_TASK = "task:assuming_single_species_phase_is_pure"


def library_task_one_way(d):
    # The exception: a value names only a library task that does not know it.
    v = ent(d, EVIDENCE)
    drop_from_determines(d)
    v["cpo:hasDeterminationTask"] = {"@id": LIBRARY_TASK}


def library_and_crate_task(d):
    # The exception holds only if ALL tasks of the value are library tasks: a crate task with it that
    # does not name it is reported.
    v = ent(d, EVIDENCE)
    drop_from_determines(d)
    v["cpo:hasDeterminationTask"] = [v["cpo:hasDeterminationTask"], {"@id": LIBRARY_TASK}]


CASES = [
    ("task missing at the value", drop_task, {"hlo:Value_DeterminationTask_Shape": 1, "hlo:Value_TaskBothWays_Shape": 1}),
    ("task does not name the value", drop_from_determines, {"hlo:Value_TaskBothWays_Shape": 1}),
    ("library task without the inverse", library_task_one_way, {}),
    ("library and crate task mixed", library_and_crate_task, {"hlo:Value_TaskBothWays_Shape": 1}),
    ("type missing", drop_type, {"hlo:Value_Type_Shape": 1}),
    ("value at no variable", detach, {"hlo:Value_Variable_Shape": 1}),
    # The value put in has no unit - the existing unit shape reports too.
    ("value at the actual", value_on_actual, {"hlo:Actual_NoValue_Shape": 1, "hlo:Value_Unit_Shape": 1}),
    ("rdf:value at another actual", rdf_value_on_other_actual, {"hlo:Actual_NoValue_Shape": 1}),
    ("qudt:value at the file date", qudt_value_on_file_date, {"hlo:Actual_NoValue_Shape": 1}),
    ("mechanism without chain", mechanism_chain_broken, {"hlo:Value_Type_Shape": 1, "hlo:Value_DeterminationTask_Shape": 1}),
    ("chain only for mechanisms", chain_not_for_other_values, {"hlo:Value_DeterminationTask_Shape": 1}),
]


def counts(crate_path):
    """Results per shape, counted as generator/workflow/run_shacl.py counts them (an inner result
    under sh:detail is the reason of an outer one and does not count)."""
    _, results, _ = pyshacl.validate(build_data_graph(Path(crate_path), []), shacl_graph=SHAPES, inference="none",
                                     advanced=True, js=False)
    details = set(results.objects(None, SH.detail))
    return Counter(SHAPE_NAMES.get(results.value(r, SH.sourceShape), "(unzugeordnet)")
                   for r in results.subjects(RDF.type, SH.ValidationResult) if r not in details)


base = counts(CRATE)
print("undamaged:", dict(base))
ok = True
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
