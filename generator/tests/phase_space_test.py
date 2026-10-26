"""
Counter-check (rule 7.14) for the Phase Space requirements:
- Phase_Space_R1 and R3 exclude Fixed phases (rule 7.7): a library phase without a volume, or with an interface
  without an area, does not report - a phase in use does;
- hlo:Phase_SameMaterial_Interface_Shape (data quality): undamaged nothing; a phase of a
  material with several phases whose pair interfaces are taken away reports;
- Phase_Space_R2: the one collecting path collects for every phase what the four former paths per form class did;
- Phase_Space_R6 (interfaces of a phase): the reactor liquid links its PhaseInterface and all its pair interfaces, a
  stream phase without interfaces links nothing, and the assignment reports nothing;
- hlo:Device_RoomAir_Contact_Shape (data quality; the generator creates the contact): it reports
  exactly the devices standing directly in the room air without a contact to it - computed apart from the shape -
  and a balance whose contacts are taken away.

Hydrogenation crate (crate, libraries, ontologies, as generator/workflow/run_shacl.py builds it); validates only
these shapes. Writes nothing.

Run from the repository root (well under a minute):
    python generator/tests/phase_space_test.py [--crate PATH]
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
from helpers.context_links import _Walker  # noqa: E402

SH = Namespace("http://www.w3.org/ns/shacl#")
HLO = Namespace("http://www.semanticweb.org/lf576/ontologies/2026/7/HigherLevelOntology#")
CPO = Namespace("http://www.semanticweb.org/lf576/ontologies/2026/7/ChemicalProcessOntology#")
DCTERMS = Namespace("http://purl.org/dc/terms/")
LIBRARY_PHASE = "vessel001_Body_SolidPhase"                       # Fixed, the glass of the vessel in the library
PHASE_IN_USE = "Phase_LiquidVessel_Phase_SeriesSpecific"         # the reactor liquid of the series
REACTOR_LIQUID = "Phase_LiquidVessel_Phase_ExperimentSpecific_1"
STREAM_PHASE = "Phase_RDY_Add_Phase_ExperimentSpecific_1"        # a stream between devices: touches nothing
FORM_DIMENSIONS = {"Cuboid": "cpo:hasLength cpo:hasWidth cpo:hasHeight cpo:hasOuterVolume",
                   "SolidCylinder": "cpo:hasDiameter cpo:hasHeight cpo:hasOuterVolume",
                   "Spherical": "cpo:hasDiameter cpo:hasOuterVolume",
                   "Annulus": "cpo:hasInnerDiameter cpo:hasOuterDiameter cpo:hasHeight cpo:hasOuterVolume"}


def shapes_of(full, main) -> Graph:
    """A shape with everything it reaches."""
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
    context = Graph()
    context.parse(str(path_definitions.CONTEXT_SHAPES), format="turtle")
    quality = Graph()
    quality.parse(str(path_definitions.DATA_QUALITY_SHAPES), format="turtle")
    failures = 0

    def check(name, got, expected):
        nonlocal failures
        ok = got == expected
        failures += not ok
        print(f"{'OK  ' if ok else 'FAIL'} {name}")
        if not ok:
            print(f"     expected {sorted(map(str, expected))[:6]}\n     got      {sorted(map(str, got))[:6]}")

    def reports(g, shapes):
        _, results, _ = pyshacl.validate(g, shacl_graph=shapes, inference="none", advanced=True)
        return set(results.objects(None, SH.focusNode))

    def copy(g):
        out = Graph()
        out += g
        return out

    library_phase, phase = one(base, LIBRARY_PHASE), one(base, PHASE_IN_USE)
    assert (library_phase, RDF.type, HLO.Fixed) in base and (phase, RDF.type, HLO.Fixed) not in base

    # ---- Phase_Space_R1: volume
    r1 = shapes_of(context, HLO.Phase_Space_R1_MainShape)
    check("R1: undamaged, nothing reports", reports(base, r1), set())
    g = copy(base)
    g.remove((library_phase, CPO.hasVolume, None))
    g.remove((phase, CPO.hasVolume, None))
    check("R1: both without a volume - only the phase in use reports", reports(g, r1), {phase})

    # ---- Phase_Space_R3: total interfacial area
    r3 = shapes_of(context, HLO.Phase_Space_R3_MainShape)
    check("R3: undamaged, nothing reports", reports(base, r3), set())
    g = copy(base)
    library_interface = URIRef(str(library_phase) + "_TestInterface")
    g.add((library_interface, RDF.type, CPO.PhaseInterface))
    g.add((library_phase, CPO.hasPhaseInterface, library_interface))
    for interface in base.objects(phase, CPO.hasPhaseInterface):
        g.remove((interface, CPO.hasArea, None))
    check("R3: interfaces without an area - only the phase in use reports", reports(g, r3), {phase})

    # ---- data quality: the phases of one material border on each other
    same = shapes_of(quality, HLO.Phase_SameMaterial_Interface_Shape)
    others = {q for m in base.objects(phase, DCTERMS.isPartOf) for q in base.objects(m, DCTERMS.hasPart)} - {phase}
    assert others, "the reactor liquid shares its material"
    check("data quality: undamaged, nothing reports", reports(base, same), set())
    g = copy(base)
    g.remove((phase, CPO.isSeparatedByInterface, None))
    check("data quality: the reactor liquid without its pair interfaces reports", reports(g, same), {phase})

    # ---- Phase_Space_R2: one collecting path = the four former ones
    sg = ShapesGraph(context)
    info = [p for p in context.objects(HLO.Phase_Space_R2_CuboidShape, SH.property) if (p, SH.severity, SH.Info) in context]
    assert len(info) == 1, "one collecting path at the first form shape"
    new_path = next(context.objects(info[0], SH.path))
    former = Graph()
    for cls, dims in FORM_DIMENSIONS.items():
        former.parse(format="turtle", data=f"""
            @prefix sh: <http://www.w3.org/ns/shacl#> . @prefix hlo: <{HLO}> . @prefix cpo: <{CPO}> .
            hlo:Former_{cls} sh:path ( [ sh:alternativePath ( cpo:definesForm cpo:fillsForm ) ]
                [ sh:alternativePath ( {dims} ) ] [ sh:zeroOrMorePath hlo:specializationOf ] ) .""")
    former_sg = ShapesGraph(former)
    former_paths = [next(former.objects(HLO[f"Former_{cls}"], SH.path)) for cls in FORM_DIMENSIONS]
    phase_classes = {CPO.Phase} | set(base.transitive_subjects(RDFS.subClassOf, CPO.Phase))
    phases = sorted(p for c in phase_classes for p in base.subjects(RDF.type, c) if p in own)
    differ = {p for p in phases if value_nodes_from_path(sg, p, new_path, base)
              != set().union(*(value_nodes_from_path(former_sg, p, fp, base) for fp in former_paths))}
    check(f"R2: for each of the {len(phases)} phases the one collecting path = the four former ones", differ, set())

    # ---- Phase_Space_R6: interfaces of a phase
    liquid, stream = one(base, REACTOR_LIQUID), one(base, STREAM_PHASE)

    def linked(focus):
        ends = set()
        _Walker(context, base).ends(HLO.Phase_Space_R6_MainShape, focus, ends)
        return ends

    expected = set(base.objects(liquid, CPO.hasPhaseInterface)) | set(base.objects(liquid, CPO.isSeparatedByInterface))
    check("R6: the reactor liquid has interfaces", len(expected) > 1, True)
    check("R6: it links its PhaseInterface and every pair interface", linked(liquid), expected)
    check("R6: a stream phase without interfaces links nothing", linked(stream), set())
    check("R6: the assignment reports nothing", reports(base, shapes_of(context, HLO.Phase_Space_R6_MainShape)), set())

    # ---- data quality: a device standing directly in the room air borders on it (generator)
    air = shapes_of(quality, HLO.Device_RoomAir_Contact_Shape)

    def missing_air_contact(g):
        """Computed apart from the shape: devices of the crate with a body, standing in an Environment, none of whose
        body phases has a pair interface partner in an Environment."""
        out = set()
        for device in set(g.subjects(CPO.madeOfMaterial, None)):
            if device not in own or (device, RDF.type, HLO.Fixed) in g:
                continue
            if not any((place, RDF.type, CPO.Environment) in g for place in g.objects(device, CPO.locatedInsideOf)):
                continue
            partners = {q for m in g.objects(device, CPO.madeOfMaterial) for b in g.objects(m, DCTERMS.hasPart)
                        for i in g.objects(b, CPO.isSeparatedByInterface) for q in g.objects(i, CPO.separatesPhases)}
            if not any((m, RDF.type, CPO.Environment) in g for q in partners for m in g.objects(q, DCTERMS.isPartOf)):
                out.add(device)
        return out

    def air_reports(g):
        return {f for f in reports(g, air) if f in own}

    check("room air: the shape reports exactly the devices without the contact", air_reports(base), missing_air_contact(base))
    balance = one(base, "balance001_SeriesSpecific")
    g = copy(base)
    for body in [b for m in base.objects(balance, CPO.madeOfMaterial) for b in base.objects(m, DCTERMS.hasPart)]:
        g.remove((body, CPO.isSeparatedByInterface, None))
    check("room air: the balance without its contacts reports too", air_reports(g), missing_air_contact(base) | {balance})

    print("ALL OK" if not failures else f"{failures} FAILED")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
