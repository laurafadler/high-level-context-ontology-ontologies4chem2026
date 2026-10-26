"""
Counter-check (rule 7.14) for the device form requirements: one downward path to the forms of a device, however
deep (Device_Space_R1 - one requirement for all form classes, the layer included -, Device_Structure_R3), the plain
Device_Structure_R1 (cpo:hasEnvelopeForm not below cpo:definesForm), the envelope as Device_Structure_R2, templates
(like every Fixed device) excluded from Device_Energy_R5, the assignments Device_Structure_R4 (forms of the device)
and Device_Substance_R4 (constituents of the body material), and two data quality checks: the cavity of a hollow
form (hlo:Cavity_*_Shape) and the body material that fills exactly the form of its device
(hlo:BodyMaterial_FillsForm_Shape).

Each case damages ONE entity of a copy of the hydrogenation crate (its stirrer has a blade as a part of its
form and an envelope of its own) and validates it against these shapes only, expecting exactly the listed
change in the counts of the watched requirements against the undamaged crate. The case of the missing form is
also run with RDFS inference: the envelope must not stand in for the form. The two assignments never report;
what they link is checked with the walker of helpers/context_links.py.

Writes the damaged copies to %TEMP%/cr/damaged_device_forms.

Run from the repository root:
    python generator/tests/device_forms_test.py
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
from helpers.context_links import _Walker  # noqa: E402
from workflow.run_shacl import build_data_graph  # noqa: E402

SH = Namespace("http://www.w3.org/ns/shacl#")
HLO = Namespace("http://www.semanticweb.org/lf576/ontologies/2026/7/HigherLevelOntology#")
CHEBI = Namespace("http://purl.obolibrary.org/obo/chebi.owl#")
REQUIREMENTS = ["Device_Space_R1", "Device_Structure_R2", "Device_Structure_R1", "Device_Structure_R3",
                "Device_Structure_R4", "Device_Energy_R5", "Device_Substance_R4"]
QUALITY = ["Cavity_SolidCylinder", "Cavity_Annulus", "BodyMaterial_FillsForm"]   # hlo:<name>_Shape in DataQualityShapes.ttl

ALL_SHAPES = Graph()
ALL_SHAPES.parse(str(path_definitions.CONTEXT_SHAPES), format="turtle")
ALL_SHAPES.parse(str(Path(path_definitions.CONTEXT_SHAPES).with_name("DataQualityShapes.ttl")), format="turtle")
SHAPES = Graph()
for prefix, namespace in ALL_SHAPES.namespaces():
    SHAPES.bind(prefix, namespace)
roots = {s: r for r in REQUIREMENTS for s in ALL_SHAPES.subjects(HLO.isShapeOfRequirement, HLO[r])}
roots.update({HLO[f"{q}_Shape"]: q for q in QUALITY})
todo, seen = list(roots), set()
while todo:
    node = todo.pop()
    if node in seen:
        continue
    seen.add(node)
    for p, o in ALL_SHAPES.predicate_objects(node):
        SHAPES.add((node, p, o))
        if isinstance(o, BNode) or (p == SH.node and o not in seen):
            todo.append(o)

CRATE = Path("projects/hydrogenation_rdy_2026_09/crate/ro-crate-metadata.json")
OUT = Path(os.environ["TEMP"]) / "cr" / "damaged_device_forms"
OUT.mkdir(parents=True, exist_ok=True)
P = "crate:hydrogenation_rdy_2026_09/"
data = json.load(open(CRATE, encoding="utf-8"))
STIRRER = "stirrer001_SeriesSpecific"
BLADE = "PartForm_Blade_stirrer001_SeriesSpecific"


def ent(d, i):
    return next(e for e in d["@graph"] if e["@id"] == P + i)


def blade_without_width(d):
    del ent(d, BLADE)["cpo:hasWidth"]


def coating_on_the_blade(d):
    # Two steps below the form of the stirrer (form -> part -> layer): the path of one step did not reach it.
    ent(d, BLADE)["cpo:hasLayerForm"] = {"@id": P + "LayerForm_Test"}
    d["@graph"].append({"@id": P + "LayerForm_Test", "@type": ["cpo:LayerForm", "hlo:SeriesSpecific"]})


def stirrer_without_form(d):
    # The envelope (a form of its own at the stirrer) stays; it must not stand in for the form.
    del ent(d, STIRRER)["cpo:definesForm"]


def vessel_without_cavity(d):
    # The cup of the vessel loses its cavity: a building error, reported by the data quality check.
    del ent(d, "Form_vessel001_SeriesSpecific")["cpo:hasCavityForm"]


def body_fills_the_envelope(d):
    # The body material of the stirrer fills its envelope instead of its form: a building error.
    body = ent(d, STIRRER)["cpo:madeOfMaterial"]
    body = body[0] if isinstance(body, list) else body
    material = next(e for e in d["@graph"] if e["@id"] == body["@id"])
    material["cpo:fillsForm"] = {"@id": P + "EnvelopeForm_" + STIRRER}


def device_with_field_flag(level):
    # level: "template", "fixed" (a library exemplar) or "series" (a device in use)
    def damage(d):
        types = {"template": ["cpo:Stirrer", "hlo:Fixed", "hlo:Template"], "fixed": ["cpo:Stirrer", "hlo:Fixed"],
                 "series": ["cpo:Stirrer", "hlo:SeriesSpecific"]}[level]
        d["@graph"].append({"@id": P + "FieldTest", "@type": types, "cpo:canCreateEnergyField": True})
    damage.__name__ = f"{level}_with_field_flag"
    return damage


CASES = [
    # (label, damage, watched requirements, expected change, also with RDFS)
    ("blade (a part) without width", blade_without_width, ["Device_Space_R1"], {"Device_Space_R1": 1}, False),
    ("coating on the blade, no thickness", coating_on_the_blade, ["Device_Space_R1"], {"Device_Space_R1": 1}, False),
    ("stirrer without form, envelope stays", stirrer_without_form, REQUIREMENTS, {"Device_Structure_R1": 1}, True),
    ("cup of the vessel without cavity", vessel_without_cavity, REQUIREMENTS + QUALITY, {"Cavity_SolidCylinder": 1}, False),
    # sh:equals reports each value found on one side only: the envelope (filled, not defined) and the form
    # (defined, not filled) - two results at the one stirrer.
    ("body material fills the envelope", body_fills_the_envelope, REQUIREMENTS + QUALITY, {"BodyMaterial_FillsForm": 2}, True),
    # Since every Fixed device is excluded from Device_Energy_R5, not only a template.
    ("template with canCreateEnergyField", device_with_field_flag("template"), ["Device_Energy_R5"], {}, False),
    ("same, a library exemplar (Fixed)", device_with_field_flag("fixed"), ["Device_Energy_R5"], {}, False),
    ("same, a device in use (control)", device_with_field_flag("series"), ["Device_Energy_R5"], {"Device_Energy_R5": 1}, False),
]


def counts(graph, inference="none"):
    _, results, _ = pyshacl.validate(graph, shacl_graph=SHAPES, inference=inference, advanced=True, js=False)
    details = set(results.objects(None, SH.detail))
    out = Counter()
    for r in results.subjects(RDF.type, SH.ValidationResult):
        if r in details:
            continue
        source = results.value(r, SH.sourceShape)
        out[roots.get(source) or next((roots[s] for s in roots if (s, SH.property, source) in SHAPES), "(other)")] += 1
    return out


base_graph = build_data_graph(CRATE, [])
base = {inf: counts(base_graph, inf) for inf in ("none", "rdfs")}
print("undamaged:", {inf: dict(c) for inf, c in base.items()})
ok = not base["none"] and not base["rdfs"]
for label, damage, watched, expected, with_rdfs in CASES:
    d = copy.deepcopy(data)
    damage(d)
    path = OUT / f"{damage.__name__}.jsonld"
    path.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    graph = build_data_graph(path, [])
    for inf in (("none", "rdfs") if with_rdfs else ("none",)):
        got = counts(graph, inf)
        diff = {k: got[k] - base[inf][k] for k in watched if got[k] != base[inf][k]}
        passed = diff == expected
        ok &= passed
        print(f"  {label:40s} {inf:5s} [{'OK' if passed else 'WRONG'}] {diff}")

# The assignments: what they link (rule 6.4) - the walker of the context links, on the undamaged crate.
walker = _Walker(SHAPES, base_graph)
stirrer = next(s for s in base_graph.subjects(RDF.type, None) if str(s).endswith("/" + STIRRER))
forms = set()
walker.ends(HLO.Device_Structure_R4_MainShape, stirrer, forms)
names = sorted(str(f).rsplit("/", 1)[-1] for f in forms)
expected_forms = sorted(["Form_" + STIRRER, "EnvelopeForm_" + STIRRER, BLADE])
passed = names == expected_forms
ok &= passed
print(f"  {'Structure_R4 links the forms of the stirrer':40s}       [{'OK' if passed else 'WRONG'}] {names}")
constituents = set()
walker.ends(HLO.Device_Substance_R4_MainShape, stirrer, constituents)
passed = bool(constituents) and all((c, RDF.type, CHEBI.ChemicalEntity) in base_graph or
                                    any(base_graph.triples((c, RDF.type, None))) for c in constituents)
ok &= passed
print(f"  {'Substance_R4 links the body constituents':40s}       [{'OK' if passed else 'WRONG'}] "
      f"{sorted(str(c).rsplit('/', 1)[-1] for c in constituents)}")
print("RESULT:", "OK" if ok else "FAILED")
raise SystemExit(0 if ok else 1)
