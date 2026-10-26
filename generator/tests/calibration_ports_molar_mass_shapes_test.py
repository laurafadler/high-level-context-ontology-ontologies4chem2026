"""
Counter-check (rule 7.14) for three context requirements: Device_Time_R3
(last calibrated time), Device_Structure_R5 (ports, an assignment) and Molecule_Substance_R3 (molar mass).
Each case damages ONE entity of a copy of the hydrogenation crate (it has calibrated devices, ports and
molecules) and validates it against these three shapes only - the whole set takes minutes per run - expecting
exactly the listed change in the counts per requirement against the undamaged crate.

Writes the damaged copies to %TEMP%/cr/damaged_calibration_ports_molar_mass.

Run from the repository root:
    python generator/tests/calibration_ports_molar_mass_shapes_test.py
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
REQUIREMENTS = ["Device_Time_R3", "Device_Structure_R5", "Molecule_Substance_R3"]

ALL_SHAPES = Graph()
ALL_SHAPES.parse(str(path_definitions.CONTEXT_SHAPES), format="turtle")
SHAPES = Graph()
for prefix, namespace in ALL_SHAPES.namespaces():
    SHAPES.bind(prefix, namespace)
todo = [s for r in REQUIREMENTS for s in ALL_SHAPES.subjects(HLO.isShapeOfRequirement, HLO[r])]
roots = {s: r for r in REQUIREMENTS for s in ALL_SHAPES.subjects(HLO.isShapeOfRequirement, HLO[r])}
seen = set()
while todo:
    node = todo.pop()
    if node in seen:
        continue
    seen.add(node)
    for p, o in ALL_SHAPES.predicate_objects(node):
        SHAPES.add((node, p, o))
        if isinstance(o, BNode):
            todo.append(o)

CRATE = Path("projects/hydrogenation_rdy_2026_09/crate/ro-crate-metadata.json")
OUT = Path(os.environ["TEMP"]) / "cr" / "damaged_calibration_ports_molar_mass"
OUT.mkdir(parents=True, exist_ok=True)
P = "crate:hydrogenation_rdy_2026_09/"
data = json.load(open(CRATE, encoding="utf-8"))


def ent(d, i):
    return next(e for e in d["@graph"] if e["@id"] == P + i)


def drop(i, prop):
    def damage(d):
        del ent(d, i)[prop]
    damage.__name__ = f"drop_{prop.split(':')[-1]}"
    return damage


def first_molecule(d):
    return next(e for e in d["@graph"] if "chebi:Molecule" in (e["@type"] if isinstance(e["@type"], list) else [e["@type"]])
                and e["@id"].endswith("ExperimentSpecific_1") and e.get("hlo:specializationOf"))


def molecule_off_chain(d):
    # Without the chain the molecule reaches neither its library entry nor thus the molar mass.
    del first_molecule(d)["hlo:specializationOf"]


def molar_mass_on_the_record(d):
    # A molar mass of its own at the experiment molecule fulfils the demand as well (zero steps of the chain).
    m = first_molecule(d)
    del m["hlo:specializationOf"]
    m["cpo:hasMolarMass"] = {"@id": "chem:Molecule_0001_MolarMass"}


CASES = [
    ("sensor without lastCalibratedTime", drop("tempsensor001_ExperimentSpecific_1", "cpo:lastCalibratedTime"), {"Device_Time_R3": 1}),
    ("device without ports (assignment)", drop("vessel001_SeriesSpecific", "cpo:hasPort"), {}),
    ("molecule without chain", molecule_off_chain, {"Molecule_Substance_R3": 1}),
    ("molar mass at the molecule itself", molar_mass_on_the_record, {}),
]


def counts(crate_path):
    _, results, _ = pyshacl.validate(build_data_graph(Path(crate_path), []), shacl_graph=SHAPES, inference="none",
                                     advanced=True, js=False)
    details = set(results.objects(None, SH.detail))
    out = Counter()
    for r in results.subjects(RDF.type, SH.ValidationResult):
        if r in details:
            continue
        source = results.value(r, SH.sourceShape)
        out[roots.get(source) or next((roots[s] for s in roots if (s, SH.property, source) in SHAPES), "(other)")] += 1
    return out


base = counts(CRATE)
print("undamaged:", dict(base))
ok = not base
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
