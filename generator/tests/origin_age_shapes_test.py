"""
Counter-check (rule 7.14) for the origin and age requirements of the inventory (rule 7.17):
Phase_Time_R1 (the arrival of a
container content - since when it is in the lab), Phase_Time_R2 (a known origin of every other phase), Phase_Time_R4-R7 (opening, expiry, arrival and containers upstream over the
transfers - assignments), Phase_Information_R2 (lot), Phase_Information_R4/R5 (lots and origin tasks
upstream - assignments) and the assignments of the molecules (Molecule_Time_R1-R4,
Molecule_Information_R5/R6), which find what their phase finds.

Builds the data graph of the hydrogenation crate the way generator/workflow/run_shacl.py does
(crate, libraries, ontologies), damages it in memory one case at a time and validates only these
shapes - each case expects exactly the listed focus nodes. The assignments never report; for them
the cases check what the context links find from one phase (helpers/context_links.py's walker).
Writes nothing.

Run from the repository root (about a minute):
    python generator/tests/origin_age_shapes_test.py [--crate PATH]
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import path_definitions  # noqa: E402
import pyshacl  # noqa: E402
from rdflib import Graph, Literal, Namespace, RDF, URIRef  # noqa: E402
from workflow.run_shacl import build_data_graph  # noqa: E402

SH = Namespace("http://www.w3.org/ns/shacl#")
HLO = Namespace("http://www.semanticweb.org/lf576/ontologies/2026/7/HigherLevelOntology#")
CPO = Namespace("http://www.semanticweb.org/lf576/ontologies/2026/7/ChemicalProcessOntology#")
TIME = Namespace("http://www.w3.org/2006/time#")
DCTERMS = Namespace("http://purl.org/dc/terms/")
CHEBI = Namespace("http://purl.obolibrary.org/obo/chebi.owl#")
REQUIREMENTS = ("Phase_Time_R1", "Phase_Time_R5", "Phase_Time_R6", "Phase_Information_R2")
BOTTLE = "bottle_adiponitrile_01"


def shapes_of(requirements) -> Graph:
    """The main shapes of the requirements with everything they reach (their node shapes, lists)."""
    full = Graph()
    full.parse(str(path_definitions.CONTEXT_SHAPES), format="turtle")
    out = Graph()
    pending = [HLO[f"{r}_MainShape"] for r in requirements]
    seen = set()
    while pending:
        node = pending.pop()
        if node in seen:
            continue
        seen.add(node)
        for p, o in full.predicate_objects(node):
            out.add((node, p, o))
            if not isinstance(o, Literal):
                pending.append(o)
    return out


def one(graph, suffix):
    """The IRI that ends with suffix (exactly one)."""
    # No part of a name may stand before it ("receiving_bottle_..." ends in "bottle_..." too).
    hits = {s for s in graph.subjects() if isinstance(s, URIRef) and str(s).endswith(suffix)
            and not (str(s)[:-len(suffix)][-1:].isalnum() or str(s)[:-len(suffix)].endswith("_"))}
    assert len(hits) == 1, (suffix, hits)
    return hits.pop()


def reported(data, shapes):
    _, results, _ = pyshacl.validate(data, shacl_graph=shapes, inference="none", advanced=True)
    out = set()
    for result in results.subjects(RDF.type, SH.ValidationResult):
        shape = results.value(result, SH.sourceShape)
        requirement = str(shape).split("#")[-1].replace("_MainShape", "")
        focus = str(results.value(result, SH.focusNode)).rsplit("/", 1)[-1]
        out.add((requirement, focus))
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--crate", default=str(path_definitions.crate_path("hydrogenation_rdy_2026_09")))
    args = parser.parse_args()
    base = build_data_graph(Path(args.crate), [])
    shapes = shapes_of(REQUIREMENTS)

    lib_phase = one(base, f"material:{BOTTLE}_Content_Phase".split(":")[1])
    lib_occ = one(base, f"{BOTTLE}_Content_Phase_Occurrence")
    lib_material = one(base, f"material:{BOTTLE}_Content".split(":")[1])
    lib_bottle = one(base, f"device:{BOTTLE}".split(":")[1])
    series_phase = one(base, f"{BOTTLE}_Content_Phase_SeriesSpecific")
    exp1_phase = one(base, f"{BOTTLE}_Content_Phase_ExperimentSpecific_1")
    phases = {f"{BOTTLE}_Content_Phase_SeriesSpecific", f"{BOTTLE}_Content_Phase_ExperimentSpecific_1",
              f"{BOTTLE}_Content_Phase_ExperimentSpecific_2"}

    def no_occurrence(g):
        g.remove((lib_phase, CPO.hasOccurrence, None))

    def own_occurrence_of_experiment(g):
        no_occurrence(g)
        occ, start = URIRef(str(exp1_phase) + "_TestOccurrence"), URIRef(str(exp1_phase) + "_TestStart")
        g.add((exp1_phase, CPO.hasOccurrence, occ))
        g.add((occ, RDF.type, CPO.Occurrence))
        g.add((occ, RDF.type, HLO.ExperimentSpecific))
        g.add((occ, CPO.hasStartTime, start))
        g.add((start, RDF.type, TIME.Instant))

    def filled_in_experiment(g):
        no_occurrence(g)
        transfer = URIRef(str(exp1_phase) + "_TestFilling")
        g.add((transfer, RDF.type, CPO.Transfer))
        g.add((transfer, CPO.hasTransferType, CPO.PortCrossing))
        g.add((transfer, CPO.addsToPhase, exp1_phase))

    def no_start(g):
        g.remove((lib_occ, CPO.hasStartTime, None))

    def no_lot(g):
        g.remove((lib_material, CPO.hasLotNumber, None))

    def no_opening_no_expiry(g):
        g.remove((lib_bottle, CPO.hasOpeningTime, None))
        g.remove((lib_material, CPO.hasExpiryTime, None))

    r2 = {("Phase_Time_R1", p) for p in phases}
    cases = [
        ("undamaged", lambda g: None, set()),
        ("library content without occurrence", no_occurrence, r2),
        ("only an occurrence of the experiment", own_occurrence_of_experiment, r2),
        ("filled through the opening in experiment 1 - no exception, it still needs its arrival", filled_in_experiment, r2),
        ("occurrence without a start", no_start, r2),
        ("no lot", no_lot, {("Phase_Information_R2", p) for p in phases}),
        ("no opening, no expiry (assignments)", no_opening_no_expiry, set()),
    ]
    failures = 0
    for name, damage, expected in cases:
        g = Graph()
        g += base
        damage(g)
        got = reported(g, shapes)
        ok = got == expected
        failures += not ok
        print(f"{'OK  ' if ok else 'FAIL'} {name}: {len(got)} report(s)")
        if not ok:
            print(f"     expected {sorted(expected)}\n     got      {sorted(got)}")
    failures += upstream_cases(base)
    failures += origin_cases(base, no_occurrence)
    print("ALL OK" if not failures else f"{failures} FAILED")
    sys.exit(1 if failures else 0)


def origin_cases(base, no_occurrence) -> int:
    """Phase_Time_R2 (existence): every phase outside a chemical container - except device bodies and the
    surroundings - reaches at least one origin, an occurrence at a Fixed entry (the contents of
    containers are excluded - Phase_Time_R1 asks for their arrival - and the start time is not asked for).
    Undamaged, nothing reports: hydrogen comes from a gas cylinder and the cooling water from the
    deionised water supply of the lab, whose water is always there like the room air. Without the arrival of the
    adiponitrile bottle its feed reports - not the content itself (R1 does), not the reactor phases, which reach the
    other bottles (one origin is enough); an arrival without a start time is still an origin; without the
    cylinder's arrival, the hydrogen line; without the permanent occurrence of the water, the content of the water
    line (a pipe, no chemical container) and the cooling water."""
    shapes = shapes_of(("Phase_Time_R2",))
    levels = ("SeriesSpecific", "ExperimentSpecific_1", "ExperimentSpecific_2")

    def reports(*names):
        return {("Phase_Time_R2", f"{name}_{lv}") for name in names for lv in levels}

    def no_start(g):
        g.remove((one(g, f"{BOTTLE}_Content_Phase_Occurrence"), CPO.hasStartTime, None))

    def no_cylinder(g):
        g.remove((one(g, "h2_cylinder_01_Content_Phase"), CPO.hasOccurrence, None))

    def no_water(g):
        g.remove((one(g, "L109_DI_water_supply_Content_Phase"), CPO.hasOccurrence, None))

    failures = 0
    for name, damage, expected in (
            ("R2: every phase reaches an origin", lambda g: None, set()),
            ("R2: without the arrival of one bottle, its feed reports - the content itself not (R1 does)", no_occurrence,
             reports("Phase_RDY_Add_Phase")),
            ("R2: an arrival without a start time is still an origin", no_start, set()),
            ("R2: without the arrival of the gas cylinder, the hydrogen line reports", no_cylinder,
             reports("Phase_Sparger_Inlet_Phase", "Phase_Sparger_Phase")),
            ("R2: without the permanent occurrence of the water supply, the cooling water reports", no_water,
             reports("L109_DI_water_supply_Content_Phase", "Phase_CoolingFluid_Inlet_Phase", "Phase_CoolingFluid_Phase",
                     "Phase_CoolingFluid_Outlet_Phase"))):
        g = Graph()
        g += base
        damage(g)
        got = reported(g, shapes)
        ok = got == expected
        failures += not ok
        print(f"{'OK  ' if ok else 'FAIL'} {name}: {len(got)} report(s)")
        if not ok:
            print(f"     missing {sorted(expected - got)}\n     extra   {sorted(got - expected)}")
    return failures


def upstream_cases(base) -> int:
    """Layer 2 (Phase_Time_R4-R7, assignments): they never report, so what counts is what the
    context links find - asked of helpers/context_links.py's own walker."""
    from helpers.context_links import _Walker
    full = Graph()
    full.parse(str(path_definitions.CONTEXT_SHAPES), format="turtle")

    def found(g, requirement, phase_suffix):
        walker = _Walker(full, g)
        ends = set()
        walker.ends(HLO[f"{requirement}_MainShape"], one(g, phase_suffix), ends)
        return {str(e).rsplit("/", 1)[-1].rsplit(":", 1)[-1] for e in ends}

    # The containers the reactor phase can come from: the three bottles and the gas cylinder.
    CONTAINERS = ("bottle_adiponitrile_01", "bottle_platinum_01", "bottle_isopropanol_70_01", "h2_cylinder_01")
    bottles = {f"{c}_ExperimentSpecific_1" for c in CONTAINERS}
    occurrences = {f"{c}_Content_Phase_Occurrence" for c in CONTAINERS}
    feed = "Phase_RDY_Add_Phase_ExperimentSpecific_1"
    crossing = next(t for t in base.subjects(CPO.addsToPhase, one(base, feed)))

    def cut_feed(g):
        g.remove((crossing, None, None))

    def prepared_in_library(g):
        # As if the content of the isopropanol bottle had been prepared in the store from the platinum bottle:
        # a Fixed transfer in the library (inventory_entries.prepared_container).
        transfer = URIRef(str(one(g, "bottle_isopropanol_70_01_Content_Phase")) + "_from_test")
        g.add((transfer, RDF.type, CPO.Transfer))
        g.add((transfer, RDF.type, HLO.Fixed))
        g.add((transfer, CPO.hasTransferType, CPO.PortCrossing))
        g.add((transfer, CPO.removesFromPhase, one(g, "bottle_platinum_01_Content_Phase")))
        g.add((transfer, CPO.addsToPhase, one(g, "bottle_isopropanol_70_01_Content_Phase")))

    liquid_feed = "Phase_LiquidVessel_Add_Phase_ExperimentSpecific_1"
    reactor = "Phase_LiquidVessel_Phase_ExperimentSpecific_1"

    def no_lot_platinum(g):
        g.remove((one(g, "bottle_platinum_01_Content"), CPO.hasLotNumber, None))

    def experiment_task_at_start(g):
        # A task of the experiment that ends when an occurrence of the experiment starts (no Fixed),
        # and an occurrence that ends when the content of the bottle arrives (no task).
        occurrence, start = URIRef(str(one(g, feed)) + "_TestOccurrence"), URIRef(str(one(g, feed)) + "_TestStart")
        g.add((one(g, feed), CPO.hasOccurrence, occurrence))
        g.add((occurrence, RDF.type, CPO.Occurrence))
        g.add((occurrence, CPO.hasStartTime, start))
        task = URIRef(str(one(g, feed)) + "_TestTask")
        g.add((task, RDF.type, CPO.OperationTask))
        g.add((task, CPO.hasEndTime, start))
        arrival = g.value(one(g, f"{BOTTLE}_Content_Phase_Occurrence"), CPO.hasStartTime)
        g.add((one(g, "bottle_platinum_01_Content_Phase_Occurrence"), CPO.hasEndTime, arrival))

    cases = [
        ("R7: the feed reaches its own bottle only", lambda g: None, "Phase_Time_R7", feed, {f"{BOTTLE}_ExperimentSpecific_1"}),
        ("R7: the reactor liquid reaches every container, not the reactor", lambda g: None, "Phase_Time_R7",
         "Phase_LiquidVessel_Phase_ExperimentSpecific_1", bottles),
        ("R4: the reactor liquid reaches the arrival of every content", lambda g: None, "Phase_Time_R4",
         "Phase_LiquidVessel_Phase_ExperimentSpecific_1", occurrences),
        ("R5: the content phase itself (zero steps) reaches its opening", lambda g: None, "Phase_Time_R5",
         f"{BOTTLE}_Content_Phase_ExperimentSpecific_1", {f"{BOTTLE}_OpeningTime"}),
        ("R7: no transfer out of the bottle - the feed reaches nothing", cut_feed, "Phase_Time_R7", feed, set()),
        ("R4: the liquid feed reaches only its own bottle", lambda g: None, "Phase_Time_R4", liquid_feed,
         {"bottle_isopropanol_70_01_Content_Phase_Occurrence"}),
        ("R4: prepared in the library from another bottle - the feed reaches both", prepared_in_library,
         "Phase_Time_R4", liquid_feed,
         {"bottle_isopropanol_70_01_Content_Phase_Occurrence", "bottle_platinum_01_Content_Phase_Occurrence"}),
        ("R5: ... and the opening of the source bottle", prepared_in_library, "Phase_Time_R5", liquid_feed,
         {"bottle_isopropanol_70_01_OpeningTime", "bottle_platinum_01_OpeningTime"}),
        # Expiry or retest (CPO 1.29): the platinum bottle has only a retest date.
        ("R6: the reactor liquid reaches the expiry or re-test time of every bottle", lambda g: None, "Phase_Time_R6",
         reactor, {"bottle_adiponitrile_01_Content_ExpiryTime", "bottle_isopropanol_70_01_Content_ExpiryTime",
                   "bottle_platinum_01_Content_RetestTime"}),
        # Lot and origin task (Phase_Information_R4/R5): the material with the lot, the receiving task.
        ("Information R4: the reactor liquid reaches the lot of every bottle", lambda g: None, "Phase_Information_R4",
         reactor, {f"{c}_Content" for c in CONTAINERS}),
        ("Information R4: a bottle without a lot drops out", no_lot_platinum, "Phase_Information_R4",
         reactor, {f"{c}_Content" for c in CONTAINERS if c != "bottle_platinum_01"}),
        ("Information R5: the reactor liquid reaches every receiving task", lambda g: None, "Phase_Information_R5",
         reactor, {f"receiving_{c}" for c in CONTAINERS}),
        ("Information R5: prepared in the library - the feed reaches both receiving tasks", prepared_in_library,
         "Phase_Information_R5", liquid_feed, {"receiving_bottle_isopropanol_70_01", "receiving_bottle_platinum_01"}),
        ("Information R5: a task of the experiment ending at an occurrence start drops out", experiment_task_at_start,
         "Phase_Information_R5", feed, {f"receiving_{BOTTLE}"}),
        # Molecules: one step up to the phase, then its way - the same ends as the phase.
        ("Molecule Time R1-R4 and Information R6/R7: as their phase", lambda g: None, "MOLECULE", reactor, set()),
    ]
    failures = 0
    for name, damage, requirement, phase, expected in cases:
        g = Graph()
        g += base
        damage(g)
        if requirement == "MOLECULE":
            failures += molecule_cases(g, found, phase, name)
            continue
        got = found(g, requirement, phase)
        # The room air has a permanent library occurrence and reaches the reactor via the gas space.
        got.discard("L109_Air_GasPhase_Occurrence")
        ok = got == expected
        failures += not ok
        print(f"{'OK  ' if ok else 'FAIL'} {name}")
        if not ok:
            print(f"     expected {sorted(expected)}\n     got      {sorted(got)}")
    return failures


# Molecule assignment -> assignment of the phase, whose way it follows from dcterms:isPartOf on.
MOLECULE_MIRRORS = {"Molecule_Time_R2": "Phase_Time_R5", "Molecule_Time_R3": "Phase_Time_R6",
                    "Molecule_Time_R1": "Phase_Time_R4", "Molecule_Time_R4": "Phase_Time_R7",
                    "Molecule_Information_R5": "Phase_Information_R4",
                    "Molecule_Information_R6": "Phase_Information_R5"}


def molecule_cases(g, found, phase_suffix, name) -> int:
    """Every molecule of the phase finds, per requirement, exactly what its phase finds - and that is
    not nothing."""
    phase = one(g, phase_suffix)
    molecules = [m for m in g.subjects(DCTERMS.isPartOf, phase) if (m, RDF.type, CHEBI.Molecule) in g]
    failures = 0
    for molecule_requirement, phase_requirement in MOLECULE_MIRRORS.items():
        expected = found(g, phase_requirement, phase_suffix)
        wrong = [m for m in molecules
                 if found(g, molecule_requirement, str(m).rsplit("/", 1)[-1]) != expected]
        ok = bool(molecules) and bool(expected) and not wrong
        failures += not ok
        print(f"{'OK  ' if ok else 'FAIL'} {molecule_requirement} = {phase_requirement} for {len(molecules)} molecules of the reactor liquid")
        if not ok:
            print(f"     expected {sorted(expected)}, differing {[str(m) for m in wrong][:3]}")
    return failures


if __name__ == "__main__":
    main()
