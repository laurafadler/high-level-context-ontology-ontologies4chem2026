"""
Counter-check (rule 7.14) for the rules turned into shapes on (shapes/DataQualityShapes.ttl, section
"Rules as shapes"): hlo:Name_Shape, hlo:Content_Current_Shape, hlo:Content_OneDevice_Shape, hlo:Port_Joint_Shape,
hlo:Literal_LibraryOnly_Shape, two hlo:Literal_Once_*_Shape, hlo:Procedure_Start_Shape, hlo:Stream_Ends_Shape, hlo:Phase_Dispersion_Shape,
hlo:Series_Completed_Shape, hlo:File_GeneratedBy_Shape. Each case damages ONE entity of a copy of the
hydrogenation crate, validates it against shapes/DataQualityShapes.ttl and expects exactly the listed change in
the counts per shape against the undamaged crate - the way generator/tests/rule_4_1_shapes_test.py does.

Writes the damaged copies to %TEMP%/cr/damaged_rules.

Run from the repository root:
    python generator/tests/rules_as_shapes_test.py
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
OUT = Path(os.environ["TEMP"]) / "cr" / "damaged_rules"
OUT.mkdir(parents=True, exist_ok=True)
data = json.load(open(CRATE, encoding="utf-8"))


def types(e):
    t = e.get("@type", [])
    return t if isinstance(t, list) else [t]


def ids(v):
    return [x["@id"] for x in (v if isinstance(v, list) else [v]) if isinstance(x, dict)]


def first(d, test):
    return next(e for e in d["@graph"] if test(e))


def by_id(d, i):
    return first(d, lambda e: e.get("@id") == i)


def series(e):
    return "hlo:SeriesSpecific" in types(e)


def drop_name(d):
    del first(d, lambda e: series(e) and "cpo:Task" in types(e) and "schema:name" in e)["schema:name"]


def held_device(d):
    return first(d, lambda e: series(e) and "cpo:containsMaterial" in e)


def second_content(d):
    # A content more that does not name the device back: too many, and not both ways.
    device = held_device(d)
    other = first(d, lambda e: series(e) and "cpo:MaterialVolume" in types(e)
                  and e["@id"] not in ids(device["cpo:containsMaterial"]))
    device["cpo:containsMaterial"] = [{"@id": i} for i in ids(device["cpo:containsMaterial"])] + [{"@id": other["@id"]}]


def content_does_not_point_back(d):
    content = by_id(d, ids(held_device(d)["cpo:containsMaterial"])[0])
    del content["cpo:materialContainedIn"]


def content_in_two_devices(d):
    # The content names a second device - that device does not hold it either.
    device = held_device(d)
    content = by_id(d, ids(device["cpo:containsMaterial"])[0])
    other = first(d, lambda e: series(e) and "cpo:Pipe" in types(e))
    content["cpo:materialContainedIn"] = [{"@id": device["@id"]}, {"@id": other["@id"]}]


def joint_one_way(d):
    port = first(d, lambda e: series(e) and "cpo:isPortOf" in e)
    port["cpo:isConnectedTo"] = {"@id": "port:vessel001_opening"}


def cas_on_series_species(d):
    first(d, lambda e: series(e) and "chebi:ChemicalEntity" in types(e))["cpo:hasCAS"] = "7782-44-7"


def radioactive_series_species(d):
    first(d, lambda e: series(e) and "chebi:ChemicalEntity" in types(e))["cpo:isRadioactive"] = True


def lot_on_series_content(d):
    first(d, lambda e: series(e) and "cpo:MaterialVolume" in types(e))["cpo:hasLotNumber"] = "TEST-LOT"


def _below_a_series_node_with(d, prop):
    # An experiment node whose series counterpart carries the term - it must not repeat it.
    said = {e["@id"] for e in d["@graph"] if series(e) and prop in e}
    node = first(d, lambda e: "hlo:ExperimentSpecific" in types(e) and set(ids(e.get("hlo:specializationOf"))) & said)
    node[prop] = by_id(d, ids(node["hlo:specializationOf"])[0])[prop]


def solid_structure_repeated(d):
    _below_a_series_node_with(d, "cpo:hasSolidStructure")


def field_flag_repeated(d):
    _below_a_series_node_with(d, "cpo:canCreateEnergyField")


def experiment_without_procedure(d):
    del first(d, lambda e: "cpo:SingleExperiment" in types(e))["cpo:hasProcedure"]


def stream_without_end(d):
    del first(d, lambda e: series(e) and "cpo:Stream" in types(e))["cpo:flowsTo"]


def phase_two_dispersion_states(d):
    # Every phase of the crates has its dispersion state (through the chain at the latest), so the minimum
    # cannot be damaged alone without others; a second value breaks the maximum.
    phase = first(d, lambda e: series(e) and "cpo:hasDispersionState" in e and not isinstance(e["cpo:hasDispersionState"], list))
    phase["cpo:hasDispersionState"] = [phase["cpo:hasDispersionState"], {"@id": "cpo:Dispersed"}]


def series_not_completed(d):
    del first(d, lambda e: "cpo:ExperimentalSeries" in types(e))["cpo:isCompleted"]


def file_without_task(d):
    del first(d, lambda e: "hlo:ExperimentSpecific" in types(e) and "cpo:generatedBy" in e
              and any(t in ("cpo:File", "cpo:Image", "cpo:Video") for t in types(e)))["cpo:generatedBy"]


CASES = [
    ("crate entity without a name", drop_name, {"hlo:Name_Shape": 1}),
    ("a second content", second_content, {"hlo:Content_Current_Shape": 2}),
    ("content does not point back", content_does_not_point_back, {"hlo:Content_Current_Shape": 1}),
    ("content in two devices", content_in_two_devices, {"hlo:Content_OneDevice_Shape": 1, "hlo:Content_Current_Shape": 1}),
    ("joint one way", joint_one_way, {"hlo:Port_Joint_Shape": 1}),
    ("CAS on a series species", cas_on_series_species, {"hlo:Literal_LibraryOnly_Shape": 1}),
    # Further literals of the library and two terms said once.
    ("radioactive flag on a series species", radioactive_series_species, {"hlo:Literal_LibraryOnly_Shape": 1}),
    ("lot number on a series content", lot_on_series_content, {"hlo:Literal_LibraryOnly_Shape": 1}),
    ("solid structure repeated below", solid_structure_repeated, {"hlo:Literal_Once_SolidStructure_Shape": 1}),
    ("field flag repeated below", field_flag_repeated, {"hlo:Literal_Once_CanCreateEnergyField_Shape": 1}),
    ("experiment without procedure", experiment_without_procedure, {"hlo:Procedure_Start_Shape": 1}),
    ("stream without its end", stream_without_end, {"hlo:Stream_Ends_Shape": 1}),
    ("phase with two dispersion states", phase_two_dispersion_states, {"hlo:Phase_Dispersion_Shape": 1}),
    ("series without completed", series_not_completed, {"hlo:Series_Completed_Shape": 1}),
    ("file without its task", file_without_task, {"hlo:File_GeneratedBy_Shape": 1}),
]


def counts(crate_path):
    """Results per shape on the nodes of the crate file, counted as generator/workflow/run_shacl.py counts them (the
    type stubs it adds for nodes of other crates are no nodes of this crate)."""
    own = set()
    _, results, _ = pyshacl.validate(build_data_graph(Path(crate_path), [], own), shacl_graph=SHAPES, inference="none",
                                     advanced=True, js=False)
    details = set(results.objects(None, SH.detail))
    return Counter(SHAPE_NAMES.get(results.value(r, SH.sourceShape), "(unassigned)")
                   for r in results.subjects(RDF.type, SH.ValidationResult)
                   if r not in details and results.value(r, SH.focusNode) in own)


NEW = {name for _, _, expected in CASES for name in expected}
base = counts(CRATE)
print("undamaged:", {k: v for k, v in base.items() if k in NEW} or "no result of the new shapes")
ok = not any(k in NEW for k in base)
for label, damage, expected in CASES:
    d = copy.deepcopy(data)
    damage(d)
    path = OUT / f"{damage.__name__}.jsonld"
    path.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    got = counts(path)
    diff = {k: got[k] - base[k] for k in set(got) | set(base) if got[k] != base[k]}
    passed = diff == expected
    ok &= passed
    print(f"  {label:32s} [{'OK' if passed else 'WRONG'}] {diff}")
print("RESULT:", "OK" if ok else "FAILED")
raise SystemExit(0 if ok else 1)
