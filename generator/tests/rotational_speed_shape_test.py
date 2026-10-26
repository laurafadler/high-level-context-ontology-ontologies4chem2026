"""
Counter-check (rule 7.14) for Device_Energy_R4: a device whose library entry has
cpo:canRotate true needs its own rotational speed on every level. In the crates every device meets it - so it
was never seen to fire. Each case damages ONE entity of a copy of the hydrogenation crate (stirrer001 rotates)
and validates it against this requirement only, expecting exactly the listed change in the count against the
undamaged crate.

Writes the damaged copies to %TEMP%/cr/damaged_rotational_speed.

Run from the repository root:
    python generator/tests/rotational_speed_shape_test.py
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
from rdflib import RDF, BNode, Graph, Namespace  # noqa: E402
from workflow.run_shacl import build_data_graph  # noqa: E402

SH = Namespace("http://www.w3.org/ns/shacl#")
HLO = Namespace("http://www.semanticweb.org/lf576/ontologies/2026/7/HigherLevelOntology#")
REQUIREMENT = "Device_Energy_R4"

ALL_SHAPES = Graph()
ALL_SHAPES.parse(str(path_definitions.CONTEXT_SHAPES), format="turtle")
SHAPES = Graph()
for prefix, namespace in ALL_SHAPES.namespaces():
    SHAPES.bind(prefix, namespace)
todo = list(ALL_SHAPES.subjects(HLO.isShapeOfRequirement, HLO[REQUIREMENT]))
roots = set(todo)
seen = set()
while todo:
    node = todo.pop()
    if node in seen:
        continue
    seen.add(node)
    for p, o in ALL_SHAPES.predicate_objects(node):
        SHAPES.add((node, p, o))
        if isinstance(o, BNode) or (p == SH.qualifiedValueShape):
            todo.append(o)

CRATE = Path("projects/hydrogenation_rdy_2026_09/crate/ro-crate-metadata.json")
OUT = Path(os.environ["TEMP"]) / "cr" / "damaged_rotational_speed"
OUT.mkdir(parents=True, exist_ok=True)
P = "crate:hydrogenation_rdy_2026_09/"
data = json.load(open(CRATE, encoding="utf-8"))


def ent(d, i):
    return next(e for e in d["@graph"] if e["@id"] == P + i)


def drop_speed(level):
    def damage(d):
        del ent(d, f"stirrer001_{level}")["cpo:hasRotationalSpeed"]
    damage.__name__ = f"drop_speed_{level}"
    return damage


def speed_of_wrong_kind(d):
    # The speed points at an actual of another quantity kind - does not count (CoreShape).
    speed = ent(d, "stirrer001_ExperimentSpecific_1")["cpo:hasRotationalSpeed"]
    target = next(e for e in d["@graph"] if e["@id"] == speed["@id"])
    target["qudt:hasQuantityKind"] = {"@id": "quantitykind:Temperature"}


def speed_on_a_vessel(d):
    # A device without canRotate may have a speed or not - no message either way.
    ent(d, "vessel001_ExperimentSpecific_1")["cpo:hasRotationalSpeed"] = \
        ent(d, "stirrer001_ExperimentSpecific_1")["cpo:hasRotationalSpeed"]


CASES = [
    ("stirrer (experiment 1) without speed", drop_speed("ExperimentSpecific_1"), {REQUIREMENT: 1}),
    ("stirrer (series) without speed", drop_speed("SeriesSpecific"), {REQUIREMENT: 1}),
    ("speed with a wrong quantity kind", speed_of_wrong_kind, {REQUIREMENT: 1}),
    ("vessel without canRotate with a speed", speed_on_a_vessel, {}),
]


def counts(crate_path):
    _, results, _ = pyshacl.validate(build_data_graph(Path(crate_path), []), shacl_graph=SHAPES, inference="none",
                                     advanced=True, js=False)
    details = set(results.objects(None, SH.detail))
    out = Counter()
    for r in results.subjects(RDF.type, SH.ValidationResult):
        if r in details or results.value(r, SH.resultSeverity) == SH.Info:
            continue
        out[REQUIREMENT if results.value(r, SH.sourceShape) in roots else "(other)"] += 1
    return out


base = counts(CRATE)
print("undamaged:", dict(base))
ok = not base
for label, damage, expected in CASES:
    d = copy.deepcopy(data)
    damage(d)
    path = OUT / f"{getattr(damage, '__name__', 'case')}.jsonld"
    path.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    got = counts(path)
    diff = {k: got[k] - base[k] for k in set(got) | set(base) if got[k] != base[k]}
    passed = diff == expected
    ok &= passed
    print(f"  {label:38s} [{'OK' if passed else 'WRONG'}] {diff}")
print("RESULT:", "OK" if ok else "FAILED")
raise SystemExit(0 if ok else 1)
