"""
Counter-test of generator/workflow/property_overview:

1. The small SHACL evaluator (evaluate.py) on made-up data: an exemption with sh:hasValue, a level that is left
   out ([ sh:class hlo:Template ]), alternatives in sh:or, and sh:node that has nothing to check without a value -
   each case must count the entities the shape applies to and those that meet it as SHACL does.
2. The real sources: every entry type, sheet module, question and quantity name is assigned
   (overview_config.yaml), every class lands in a family, and every field of the sheet has a property:.

Run from the repository root:
    python generator/tests/property_overview_test.py
"""
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "workflow" / "property_overview"))

import yaml  # noqa: E402
from rdflib import Graph  # noqa: E402

from common import ClassTree  # noqa: E402
from data import Data  # noqa: E402
from shapes import ShapeReader  # noqa: E402
from evaluate import Evaluator  # noqa: E402
from sources import Sources, load_config, SHEET_SCHEMA  # noqa: E402
from model import Overview  # noqa: E402

SHAPES = """
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix hlo: <http://www.semanticweb.org/lf576/ontologies/2026/7/HigherLevelOntology#> .
@prefix cpo: <http://www.semanticweb.org/lf576/ontologies/2026/7/ChemicalProcessOntology#> .
hlo:T_R1 a sh:NodeShape ; sh:targetClass cpo:Device ; sh:severity sh:Warning ;
    sh:or ( [ sh:property [ sh:path cpo:isCompositeDevice ; sh:hasValue true ] ]
            [ sh:class hlo:Template ]
            [ sh:property [ sh:path cpo:definesForm ; sh:minCount 1 ] ] ) .
hlo:T_R2 a sh:NodeShape ; sh:targetClass cpo:Device ;
    sh:or ( [ sh:property [ sh:path cpo:lastUsedPurpose ; sh:minCount 1 ] ]
            [ sh:property [ sh:path cpo:hasUsageHistory ; sh:minCount 1 ] ] ) .
hlo:T_R3 a sh:NodeShape ; sh:targetClass cpo:Device ;
    sh:property [ sh:path cpo:hasPort ; sh:node hlo:T_R3_Port ] .
hlo:T_R3_Port a sh:NodeShape ; sh:property [ sh:path cpo:isPortOf ; sh:minCount 1 ] .
"""

ENTITIES = [
    {"@id": "d:composite", "@type": ["cpo:Device", "hlo:Fixed"], "cpo:isCompositeDevice": True},
    {"@id": "d:template", "@type": ["cpo:Vessel", "hlo:Fixed", "hlo:Template"]},
    {"@id": "d:with_form", "@type": ["cpo:Device", "hlo:Fixed"], "cpo:definesForm": {"@id": "f:1"},
     "cpo:hasUsageHistory": [{"@id": "t:1"}], "cpo:hasPort": {"@id": "p:1"}},
    {"@id": "d:without", "@type": ["cpo:Device", "hlo:Fixed"], "cpo:hasPort": {"@id": "p:2"}},
    {"@id": "p:1", "@type": ["cpo:DeviceOpening", "hlo:Fixed"], "cpo:isPortOf": {"@id": "d:with_form"}},
    {"@id": "p:2", "@type": ["cpo:DeviceOpening", "hlo:Fixed"]},
]


class FakeData(Data):
    """Data of the made-up entities above instead of the libraries and crates."""

    def __init__(self, tree, entities):
        self.tree = tree
        self.entities = {e["@id"]: e for e in entities}
        self.origin = {i: "test" for i in self.entities}
        self.level = {}
        for entity_id, entity in self.entities.items():
            types = entity["@type"]
            self.level[entity_id] = "Template" if "hlo:Template" in types else "Fixed"
        self.reverse = defaultdict(lambda: defaultdict(set))
        self.sources = []
        self._index()


ok = True


def check(name, got, expected):
    global ok
    good = got == expected
    ok &= good
    print(f"{'ok  ' if good else 'FAIL'} {name:44} {got}" + ("" if good else f" (expected {expected})"))


tree = ClassTree()
data = FakeData(tree, ENTITIES)
reader = ShapeReader.__new__(ShapeReader)
reader.graph = Graph()
reader.graph.parse(data=SHAPES, format="turtle")
reader.file_of = {s: "CR" for s in reader.graph.subjects()}
reader.demands, reader.property_notes = [], {}
reader.requirements = {s: str(s).split("#")[-1].replace("_MainShape", "") for s in reader.graph.subjects() if "T_R" in str(s)}
reader._read()
evaluator = Evaluator(data, reader.graph)


def counts(source, row):
    demand = next(d for d in reader.demands if d["source"] == source and d["row"] == row)
    applies = [e for e in evaluator.focus_entities(demand, "Fixed") if evaluator.applies(demand, e)]
    met = [e for e in applies if evaluator.met(demand, e)]
    return sorted(demand["levels"]), len(applies), len(met)


# T_R1: the composite device is exempt (sh:hasValue), the template level is left out.
check("exemption by sh:hasValue, template left out", counts("T_R1", "cpo:definesForm"), (["Experiment", "Fixed", "Series"], 2, 1))
# T_R2: either property is enough - d:with_form has the usage history, the two others have neither.
check("alternatives in sh:or", counts("T_R2", "cpo:lastUsedPurpose")[1:], (3, 1))
# T_R3: sh:node holds for every port there is - a device without a port has nothing to check.
check("sh:node only where there is a value", counts("T_R3", "cpo:hasPort / cpo:isPortOf")[1:], (2, 1))

# The real sources
config = load_config()
data = Data(tree)
shapes = ShapeReader()
sources = Sources(config, tree)
overview = Overview(tree, data, shapes, sources, config)
known_unmapped = {"entry field": {"labware.openings.name", "substance.called"}}
unmapped = {k: set(v) - known_unmapped.get(k, set()) for k, v in sources.unmapped.items()}
check("everything assigned in overview_config.yaml", {k: sorted(v) for k, v in unmapped.items() if v}, {})
check("every class in a family", [c for c in overview.classes if overview.family_of[c] == "other"], [])
schema = yaml.safe_load(SHEET_SCHEMA.read_text(encoding="utf-8"))
missing = [f"{m}.{f}" for m, body in schema.items() if isinstance(body, dict) and "fields" in body
           for f, spec in body["fields"].items() if "property" not in spec]
check("every sheet field has a property:", missing, [])

print("ALL OK" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
