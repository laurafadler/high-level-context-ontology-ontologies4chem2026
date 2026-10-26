"""
Counter-check (rule 7.14) for hlo:Transfer_DroppedSpecies_Shape in shapes/DataQualityShapes.ttl (rule 3.13): an experiment transfer never moves a species at a phase that left it out
although its series phase lists it. Each case damages a copy of the amidation crate (small; its experiment
transfers are the five port crossings into the flask), validates it against the Data Quality shapes only, and
expects exactly the listed change in the counts per shape against the undamaged crate - as
generator/tests/task_times_persons_shapes_test.py does.

Writes the damaged copies to %TEMP%/cr/damaged_absent_species.

Run from the repository root:
    python generator/tests/absent_species_shape_test.py
"""
import copy
import json
import os
import sys
import time
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
OUT = Path(os.environ["TEMP"]) / "cr" / "damaged_absent_species"
OUT.mkdir(parents=True, exist_ok=True)
P = "crate:amidation_ai4green_ai4_001/"
data = json.load(open(CRATE, encoding="utf-8"))
DROPPED = "hlo:Transfer_DroppedSpecies_Shape"

# Benzoic acid (chem:Molecule_0014) comes out of its bottle into its own phase (the charge) and goes on through the
# flask opening into the liquid phase - two transfers at the phase of the charge.
TRANSFERS = ["Transfer_Benzoic_acid-PortCrossing-from-bottle_benzoic_acid_01_Content_Phase-to-Benzoic_Acid_Phase_bottle_benzoic_acid_01_opening_ExperimentSpecific_1",
             "Transfer_Benzoic_acid-PortCrossing-from-Benzoic_Acid_Phase-to-Liquid_Phase_flask_50mL_01_opening_ExperimentSpecific_1"]
LIQUID, BENZOIC = "Phase_Liquid_Phase", "Phase_Benzoic_Acid_Phase"


def ent(d, i):
    return next(e for e in d["@graph"] if e["@id"] == P + i)


def drop_species(phase, level):
    """Leave benzoic acid out of the phase on that level (only dcterms:hasPart, as the generator would)."""
    def damage(d):
        holder = ent(d, f"{phase}_{level}")
        holder["dcterms:hasPart"] = [h for h in holder["dcterms:hasPart"]
                                     if h["@id"] != f"{P}Molecule_0014_{phase}_{level}"]
    return damage


def drop_transfer(d):
    d["@graph"] = [e for e in d["@graph"] if e["@id"] not in {P + t for t in TRANSFERS}]


def combine(*damages):
    def damage(d):
        for step in damages:
            step(d)
    return damage


CASES = [
    ("dropped at destination", "dest", drop_species(LIQUID, "ExperimentSpecific_1"), {DROPPED: 1}),
    ("dropped at source", "src", drop_species(BENZOIC, "ExperimentSpecific_1"), {DROPPED: 2}),   # both transfers at the charge
    ("dropped at both", "both", combine(drop_species(LIQUID, "ExperimentSpecific_1"),
                                        drop_species(BENZOIC, "ExperimentSpecific_1")), {DROPPED: 3}),
    # What the generator does for a species absent from the experiment: phases and transfer left out.
    ("dropped with its transfer", "with_transfer", combine(drop_species(LIQUID, "ExperimentSpecific_1"),
                                                           drop_species(BENZOIC, "ExperimentSpecific_1"),
                                                           drop_transfer), {}),
    # Not this shape's business: the series phase does not list the species either.
    ("missing on series level too", "series_too", combine(drop_species(LIQUID, "ExperimentSpecific_1"),
                                                          drop_species(LIQUID, "SeriesSpecific")), {}),
]


def counts(crate_path):
    _, results, _ = pyshacl.validate(build_data_graph(Path(crate_path), []), shacl_graph=SHAPES, inference="none",
                                     advanced=True, js=False)
    details = set(results.objects(None, SH.detail))
    # Not counted: results at the stand-ins of other crates' nodes (run_shacl.py), and the repeated terms
    # of rule 3.6 that a crate built before still carries (Literal_Once_*) - neither is this shape's business.
    return Counter(name for r in results.subjects(RDF.type, SH.ValidationResult)
                   if r not in details and results.value(r, SH.focusNode) not in OTHER_CRATE_STAND_INS
                   and not (name := SHAPE_NAMES.get(results.value(r, SH.sourceShape), "(unassigned)")).startswith("hlo:Literal_Once"))


start = time.perf_counter()
base = counts(CRATE)
print(f"undamaged: {dict(base)} ({time.perf_counter() - start:.1f} s)")
ok = not base[DROPPED]
for label, name, damage, expected in CASES:
    d = copy.deepcopy(data)
    damage(d)
    path = OUT / f"{name}.jsonld"
    path.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    got = counts(path)
    diff = {k: got[k] - base[k] for k in set(got) | set(base) if got[k] != base[k]}
    passed = diff == expected
    ok &= passed
    print(f"  {label:30s} [{'OK' if passed else 'WRONG'}] {diff}")
print("RESULT:", "OK" if ok else "FAILED")
raise SystemExit(0 if ok else 1)
