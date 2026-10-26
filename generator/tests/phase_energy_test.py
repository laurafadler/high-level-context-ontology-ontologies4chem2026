"""
Counter-check (rule 7.14) for the Phase Energy requirements:
- Phase_Energy_R3 (flow rate of a phase in a stream) excludes Fixed phases like R1/R2: with the flow rate of its
  stream removed, a stream phase reports - typed Fixed, it does not;
- Phase_Energy_R8/R9 collect the values coupled with the phase's own temperature or pressure (hlo:isCoupledWith)
  instead of going over the pair interfaces. For every phase of the crate the coupled values are those of the phases
  it shares a pair interface with, without its own (the generator couples every pair interface,
  link_phase_couplings) - the comparison that shows the new path hits the same as the old one; with the couplings
  of one phase's temperature removed, R8 collects nothing for it;
- Phase_Energy_R4 excludes Fixed phases (also): a library phase that can create a field but has none does
  not report, its copies in use, which read the flag through the chain, do.
- a stream that no device contains climbs over its ends (cpo:flowsFrom, cpo:flowsTo in PARENT_PROPERTIES, also
 , rule 7.10): every phase of such a stream (Phase_Energy_R5) and every molecule in it (Molecule_Energy_R2)
  collects at least the fields of the devices at the ends of the stream (Device_Energy_R6), so it is no longer blind;
  with the ends of one stream removed, its phases and molecules collect nothing.

Hydrogenation crate (crate, libraries, ontologies, as generator/workflow/run_shacl.py builds it); validates only
the shape of R3, evaluates the paths of R8/R9 with pyshacl's own path evaluation. Writes nothing.

Run from the repository root (well under a minute):
    python generator/tests/phase_energy_test.py [--crate PATH]
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import path_definitions  # noqa: E402
import pyshacl  # noqa: E402
from pyshacl.helper.expression_helper import value_nodes_from_path  # noqa: E402
from pyshacl.shapes_graph import ShapesGraph  # noqa: E402
from rdflib import Graph, Literal, Namespace, RDF, RDFS, URIRef  # noqa: E402
from workflow.run_shacl import build_data_graph  # noqa: E402

SH = Namespace("http://www.w3.org/ns/shacl#")
HLO = Namespace("http://www.semanticweb.org/lf576/ontologies/2026/7/HigherLevelOntology#")
CPO = Namespace("http://www.semanticweb.org/lf576/ontologies/2026/7/ChemicalProcessOntology#")
DCTERMS = Namespace("http://purl.org/dc/terms/")
STREAM_PHASE = "Phase_RDY_Add_Phase_SeriesSpecific"
REACTOR_LIQUID = "Phase_LiquidVessel_Phase_ExperimentSpecific_1"


def shapes_of(full, main) -> Graph:
    """A main shape with everything it reaches."""
    out, pending, seen = Graph(), [main], set()
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
    failures = 0

    def check(name, got, expected):
        nonlocal failures
        ok = got == expected
        failures += not ok
        print(f"{'OK  ' if ok else 'FAIL'} {name}")
        if not ok:
            print(f"     expected {sorted(map(str, expected))[:6]}\n     got      {sorted(map(str, got))[:6]}")

    # ---- Phase_Energy_R3
    r3 = shapes_of(full, HLO.Phase_Energy_R3_MainShape)

    def r3_reports(g):
        _, results, _ = pyshacl.validate(g, shacl_graph=r3, inference="none", advanced=True)
        return {f for f in results.objects(None, SH.focusNode) if f in own}

    phase = one(base, STREAM_PHASE)
    stream = base.value(phase, DCTERMS.isPartOf)
    assert (stream, RDF.type, CPO.Stream) in base, stream
    undamaged = r3_reports(base)

    no_flowrate = Graph()
    no_flowrate += base
    no_flowrate.remove((stream, CPO.hasFlowrate, None))
    fixed = Graph()
    fixed += no_flowrate
    fixed.add((phase, RDF.type, HLO.Fixed))
    in_stream = {p for p in base.subjects(DCTERMS.isPartOf, stream) if p in own}   # every phase of the stream
    check("R3: undamaged, the stream phase does not report", phase in undamaged, False)
    check("R3: its stream without a flow rate - the phases of the stream report", r3_reports(no_flowrate),
          undamaged | in_stream)
    check("R3: ... the one typed Fixed is excluded", r3_reports(fixed), undamaged | (in_stream - {phase}))

    # ---- Phase_Energy_R8/R9
    sg = ShapesGraph(full)
    phase_classes = {CPO.Phase} | set(base.transitive_subjects(RDFS.subClassOf, CPO.Phase))
    phases = sorted(p for c in phase_classes for p in base.subjects(RDF.type, c)
                    if p in own and (p, RDF.type, HLO.Fixed) not in base)

    def collected(g, req, focus):
        prop = next(full.objects(HLO[f"{req}_ContextPathShape"], SH.property))
        return value_nodes_from_path(sg, focus, next(full.objects(prop, SH.path)), g)

    def over_interfaces(g, focus, quantity):
        """What the way over the pair interfaces reaches, without the phase's own value - with the chain."""
        own_values = set(g.objects(focus, quantity))
        partners = {v for i in g.objects(focus, CPO.isSeparatedByInterface) for q in g.objects(i, CPO.separatesPhases)
                    for v in g.objects(q, quantity)} - own_values
        return {u for v in partners for u in g.transitive_objects(v, HLO.specializationOf)}

    for req, quantity in (("Phase_Energy_R8", CPO.hasTemperature), ("Phase_Energy_R9", CPO.hasPressure)):
        wrong = {p for p in phases if collected(base, req, p) != over_interfaces(base, p, quantity)}
        check(f"{req}: for each of the {len(phases)} phases the coupled values = the values over the interfaces "
              f"without its own", wrong, set())

    liquid = one(base, REACTOR_LIQUID)
    check("R8: the reactor liquid collects something", bool(collected(base, "Phase_Energy_R8", liquid)), True)
    uncoupled = Graph()
    uncoupled += base
    for temperature in base.objects(liquid, CPO.hasTemperature):
        uncoupled.remove((temperature, HLO.isCoupledWith, None))
        uncoupled.remove((None, HLO.isCoupledWith, temperature))
    check("R8: its temperature uncoupled - it collects nothing", collected(uncoupled, "Phase_Energy_R8", liquid), set())

    # ---- Phase_Energy_R4 (Fixed excluded): the glass of the vessel in the library can create a
    # field, but has none - the library phase does not report, its copies in use (which read the flag) do
    r4 = shapes_of(full, HLO.Phase_Energy_R4_MainShape)

    def r4_reports(g):
        _, results, _ = pyshacl.validate(g, shacl_graph=r4, inference="none", advanced=True)
        return set(results.objects(None, SH.focusNode))

    library_body = one(base, "vessel001_Body_SolidPhase")
    assert (library_body, RDF.type, HLO.Fixed) in base
    in_use = {p for p in phases if library_body in set(base.transitive_objects(p, HLO.specializationOf)) - {p}}
    flagged = Graph()
    flagged += base
    flagged.remove((library_body, CPO.canCreateEnergyField, None))
    flagged.add((library_body, CPO.canCreateEnergyField, Literal(True)))
    check("R4: undamaged, nothing reports", r4_reports(base), set())
    check(f"R4: the library glass can create a field - its {len(in_use)} copies in use report, the library phase not",
          r4_reports(flagged), in_use)

    # ---- streams that no device contains climb over their ends (Phase_Energy_R5, Molecule_Energy_R2)
    def fields(g, req, focus, suffix="ContextPathShape"):
        prop = next(full.objects(HLO[f"{req}_{suffix}"], SH.property))
        return value_nodes_from_path(sg, focus, next(full.objects(prop, SH.path)), g)

    loose = sorted(s for s in base.subjects(RDF.type, CPO.Stream)
                   if s in own and (s, RDF.type, HLO.Fixed) not in base and (s, CPO.materialContainedIn, None) not in base)
    assert loose, "the crate has streams that no device contains"

    def end_devices(stream):
        return {d for prop in (CPO.flowsFrom, CPO.flowsTo) for port in base.objects(stream, prop)
                for d in base.objects(port, CPO.isPortOf)}

    blind, short_of_devices, molecules_short = set(), set(), set()
    for stream in loose:
        device_fields = set().union(*(fields(base, "Device_Energy_R6", d) for d in end_devices(stream)))
        for phase in base.objects(stream, DCTERMS.hasPart):
            got = fields(base, "Phase_Energy_R5", phase)
            blind |= {phase} if not got else set()
            short_of_devices |= {phase} if not device_fields <= got else set()
            for molecule in base.objects(phase, DCTERMS.hasPart):
                if not device_fields <= fields(base, "Molecule_Energy_R2", molecule):
                    molecules_short.add(molecule)
    check(f"R5: no phase of the {len(loose)} streams that no device contains is blind", blind, set())
    check("R5: ... each collects at least the fields of the devices at the ends of its stream", short_of_devices, set())
    check("Molecule_Energy_R2: ... and so does every molecule in them", molecules_short, set())
    cut = Graph()
    cut += base
    stream = loose[0]
    cut.remove((stream, CPO.flowsFrom, None))
    cut.remove((stream, CPO.flowsTo, None))
    stream_phases = set(base.objects(stream, DCTERMS.hasPart))
    check("R5: the ends of one stream removed - its phases collect nothing",
          {p for p in stream_phases if fields(cut, "Phase_Energy_R5", p)}, set())
    check("Molecule_Energy_R2: ... nor its molecules",
          {m for p in stream_phases for m in base.objects(p, DCTERMS.hasPart) if fields(cut, "Molecule_Energy_R2", m)}, set())

    print("ALL OK" if not failures else f"{failures} FAILED")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
