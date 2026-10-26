"""
Counter-check (rule 7.14) for Phase_Information_R3, the assignment of the library entry of a phase.
It replaces an existence requirement for the room air only (then numbered Phase_Information_R2), which linked the
library material
of the room air instead of its library phase (its value shape asked for more than a class, rule 6.4).

An assignment never reports, so what counts is what the context links find - asked of the walker of
helpers/context_links.py, on the hydrogenation crate (crate, libraries, ontologies, as run_shacl.py builds it):
- the room air, the body material of a device, the content of a bottle and of the water supply line each link
  exactly their library phase, from the series and from an experiment (one or more steps: the series phase in
  between is not Fixed and drops out); for the room air it is the phase of exactly the library material the
  former requirement linked;
- a process phase and the phase of a stream link nothing;
- every phase of the crate links at most one node, and only a Fixed phase;
- with the link of the series room air cut, the series and the experiments link nothing - and the shape still
  reports nothing (validated with pyshacl, undamaged and damaged).

Writes nothing. Run from the repository root (well under a minute):
    python generator/tests/phase_library_entry_test.py [--crate PATH]
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import path_definitions  # noqa: E402
import pyshacl  # noqa: E402
from rdflib import Graph, Literal, Namespace, RDF, RDFS, URIRef  # noqa: E402
from workflow.run_shacl import build_data_graph  # noqa: E402
from helpers.context_links import _Walker  # noqa: E402

SH = Namespace("http://www.w3.org/ns/shacl#")
HLO = Namespace("http://www.semanticweb.org/lf576/ontologies/2026/7/HigherLevelOntology#")
CPO = Namespace("http://www.semanticweb.org/lf576/ontologies/2026/7/ChemicalProcessOntology#")
DCTERMS = Namespace("http://purl.org/dc/terms/")
REQUIREMENT = "Phase_Information_R3"


def shapes_of(requirement) -> Graph:
    """The main shape of the requirement with everything it reaches."""
    full = Graph()
    full.parse(str(path_definitions.CONTEXT_SHAPES), format="turtle")
    out = Graph()
    pending, seen = [HLO[f"{requirement}_MainShape"]], set()
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
    """The IRI that ends with suffix (exactly one, and no longer name that merely ends alike)."""
    hits = {s for s in graph.subjects() if isinstance(s, URIRef) and str(s).endswith(suffix)
            and not (str(s)[:-len(suffix)][-1:].isalnum() or str(s)[:-len(suffix)].endswith("_"))}
    assert len(hits) == 1, (suffix, hits)
    return hits.pop()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--crate", default=str(path_definitions.crate_path("hydrogenation_rdy_2026_09")))
    args = parser.parse_args()
    own = set()
    base = build_data_graph(Path(args.crate), [], own)
    full = Graph()
    full.parse(str(path_definitions.CONTEXT_SHAPES), format="turtle")
    main_shape = HLO[f"{REQUIREMENT}_MainShape"]

    def found(g, phase):
        ends = set()
        _Walker(full, g).ends(main_shape, phase, ends)
        return ends

    failures = 0

    def check(name, got, expected):
        nonlocal failures
        ok = got == expected
        failures += not ok
        print(f"{'OK  ' if ok else 'FAIL'} {name}")
        if not ok:
            print(f"     expected {sorted(map(str, expected))}\n     got      {sorted(map(str, got))}")

    levels = ("SeriesSpecific", "ExperimentSpecific_1")
    for label, name in (("the room air", "L109_Air_GasPhase"), ("the body material of the vessel", "vessel001_Body_SolidPhase"),
                        ("the content of a bottle", "bottle_adiponitrile_01_Content_Phase"),
                        ("the content of the water supply line", "L109_DI_water_supply_Content_Phase")):
        library_phase = one(base, name)
        for level in levels:
            check(f"{label} ({level}) links its library phase", found(base, one(base, f"{name}_{level}")), {library_phase})

    library_air = one(base, "L109_Air_GasPhase")
    check("the room air: the library phase is part of the library material the former requirement linked",
          set(base.objects(library_air, DCTERMS.isPartOf)), {one(base, "L109_Air")})
    for label, name in (("a process phase", "Phase_LiquidVessel_Phase_ExperimentSpecific_1"),
                        ("the phase of a stream", "Phase_RDY_Add_Phase_ExperimentSpecific_1")):
        check(f"{label} links nothing", found(base, one(base, name)), set())

    # Every phase of the crate: at most one node, and only a Fixed phase.
    phase_classes = {CPO.Phase} | set(base.transitive_subjects(RDFS.subClassOf, CPO.Phase))
    phases = sorted(p for c in phase_classes for p in base.subjects(RDF.type, c)
                    if p in own and (p, RDF.type, HLO.Fixed) not in base)
    wrong = []
    for phase in phases:
        ends = found(base, phase)
        if len(ends) > 1 or any((e, RDF.type, HLO.Fixed) not in base
                                or not any(t in phase_classes for t in base.objects(e, RDF.type)) for e in ends):
            wrong.append(phase)
    check(f"each of the {len(phases)} phases of the crate links at most one Fixed phase", set(wrong), set())

    # Damaged: the series room air without its link to the library.
    damaged = Graph()
    damaged += base
    damaged.remove((one(base, "L109_Air_GasPhase_SeriesSpecific"), HLO.specializationOf, None))
    for level in levels + ("ExperimentSpecific_2",):
        check(f"link of the series room air cut - the room air ({level}) links nothing",
              found(damaged, one(base, f"L109_Air_GasPhase_{level}")), set())

    shapes = shapes_of(REQUIREMENT)
    for label, graph in (("undamaged", base), ("link cut", damaged)):
        _, results, _ = pyshacl.validate(graph, shacl_graph=shapes, inference="none", advanced=True)
        check(f"the assignment reports nothing ({label})", set(results.subjects(RDF.type, SH.ValidationResult)), set())

    print("ALL OK" if not failures else f"{failures} FAILED")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
