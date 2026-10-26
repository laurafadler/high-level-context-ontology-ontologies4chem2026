"""
Counter-check (rule 7.14) for the Phase Structure requirements and the phase form shapes: every one excludes Fixed (library) phases (rule 7.7), a phase dispersed in another phase needs no
exemption any more (the generator gives it a cpo:IndeterminateForm), Phase_Structure_R2 has one collecting path.

For each requirement the expected reports are computed apart from the shape, over every phase of the data graph
(crate and libraries, with the exclusion), and compared with what pyshacl reports - undamaged and after damaging a
library phase and a phase in use:
- R1 form: a library phase without its form does not report, a phase in use does;
- R4 size distribution: a library phase made dispersed does not report, its copies in use do (they read the
  dispersion state through the chain and have no size distribution of their own);
- R3 aggregate state: a library phase and a phase in use typed only cpo:Phase - only the one in use reports;
- R5 internal structure: a library glass without its structure does not report, its copies in use do (they read it
  through the chain);
- the form shapes (Phase_Space_R2, Phase_Structure_R2): a form defined by a library phase, without dimensions and
  ratios, does not report; the reactor liquid without the height and the height-to-diameter ratio of its form does;
- R2: the one collecting path collects for every phase what the three former paths per form class did.

Hydrogenation crate (crate, libraries, ontologies, as generator/workflow/run_shacl.py builds it). Writes nothing.
Run from the repository root (about a minute):
    python generator/tests/phase_structure_test.py [--crate PATH]
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
LIBRARY_GLASS = "vessel001_Body_SolidPhase"                  # Fixed: the glass of the vessel in the library
REACTOR_LIQUID = "Phase_LiquidVessel_Phase_SeriesSpecific"   # defines a solid cylinder form (class of the cavity)
STATES = (CPO.GasPhase, CPO.LiquidPhase, CPO.SolidPhase)
SIZE = (CPO.hasDispersedPhaseSizeDistribution, CPO.hasBubbleSizeDistribution, CPO.hasDropletSizeDistribution,
        CPO.hasParticleSizeDistribution)
FORMER_R2 = {"Cuboid": "cpo:hasWidthToLengthRatio cpo:hasHeightToLengthRatio",
             "SolidCylinder": "cpo:hasHeightToDiameterRatio",
             "Annulus": "cpo:hasHeightToDiameterRatio cpo:hasDiameterRatio"}


def shapes_of(full, mains) -> Graph:
    out, pending, seen = Graph(), list(mains), set()
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
    hits = {s for s in graph.subjects() if isinstance(s, URIRef) and str(s).endswith(suffix)
            and not (str(s)[:-len(suffix)][-1:].isalnum() or str(s)[:-len(suffix)].endswith("_"))}
    assert len(hits) == 1, (suffix, hits)
    return hits.pop()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--crate", default=str(path_definitions.crate_path("hydrogenation_rdy_2026_09")))
    args = parser.parse_args()
    base = build_data_graph(Path(args.crate), [])
    full = Graph()
    full.parse(str(path_definitions.CONTEXT_SHAPES), format="turtle")
    failures = 0

    def check(name, got, expected):
        nonlocal failures
        ok = got == expected
        failures += not ok
        print(f"{'OK  ' if ok else 'FAIL'} {name}")
        if not ok:
            print(f"     missing {sorted(map(str, expected - got))[:4]}\n     extra   {sorted(map(str, got - expected))[:4]}")

    def reports(g, mains):
        _, results, _ = pyshacl.validate(g, shacl_graph=shapes_of(full, mains), inference="none", advanced=True)
        return set(results.objects(None, SH.focusNode))

    def copy(g):
        out = Graph()
        out += g
        return out

    phase_classes = {CPO.Phase} | set(base.transitive_subjects(RDFS.subClassOf, CPO.Phase))

    def phases(g):
        return {p for c in phase_classes for p in g.subjects(RDF.type, c)}

    def in_use(g, p):
        return (p, RDF.type, HLO.Fixed) not in g

    def chain(g, p):
        return set(g.transitive_objects(p, HLO.specializationOf))

    expected = {
        "R1": lambda g: {p for p in phases(g) if in_use(g, p)
                         and not any(True for _ in g.objects(p, CPO.definesForm)) and not any(True for _ in g.objects(p, CPO.fillsForm))},
        "R4": lambda g: {p for p in phases(g) if in_use(g, p)
                         and any((u, CPO.hasDispersionState, CPO.Dispersed) in g for u in chain(g, p))
                         and not any(True for prop in SIZE for _ in g.objects(p, prop))},
        "R3": lambda g: {p for p in phases(g) if in_use(g, p) and not any((p, RDF.type, s) in g for s in STATES)},
        "R5": lambda g: {p for p in phases(g) if in_use(g, p) and (p, RDF.type, CPO.SolidPhase) in g
                         and not any(True for u in chain(g, p) for _ in g.objects(u, CPO.hasSolidStructure))},
    }
    mains = {f"R{n}": [HLO[f"Phase_Structure_R{n}_MainShape"]] for n in (1, 3, 4, 5)}

    glass, liquid = one(base, LIBRARY_GLASS), one(base, REACTOR_LIQUID)
    assert (glass, RDF.type, HLO.Fixed) in base and (liquid, RDF.type, HLO.Fixed) not in base
    copies = {p for p in phases(base) if glass in chain(base, p) - {p}}

    # R1
    g = copy(base)
    g.remove((glass, CPO.fillsForm, None))
    g.remove((liquid, CPO.definesForm, None))
    check("R1: undamaged - the phases in use without a form report", reports(base, mains["R1"]), expected["R1"](base))
    check("R1: the library glass and the reactor liquid without a form - only the liquid in addition",
          reports(g, mains["R1"]), expected["R1"](g))
    check("R1: ... and the liquid is among them, the glass not", (liquid in expected["R1"](g), glass in expected["R1"](g)), (True, False))
    # R4
    g = copy(base)
    g.remove((glass, CPO.hasDispersionState, None))
    g.add((glass, CPO.hasDispersionState, CPO.Dispersed))
    check("R4: undamaged", reports(base, mains["R4"]), expected["R4"](base))
    check(f"R4: the library glass made dispersed - its {len(copies)} copies in use report, the glass not",
          reports(g, mains["R4"]), expected["R4"](base) | copies)
    # R3
    g = copy(base)
    for node in (glass, liquid):
        for state in STATES:
            g.remove((node, RDF.type, state))
        g.add((node, RDF.type, CPO.Phase))
    check("R3: undamaged, nothing reports", reports(base, mains["R3"]), set())
    check("R3: both typed only cpo:Phase - only the liquid reports", reports(g, mains["R3"]), {liquid})
    # R5
    g = copy(base)
    g.remove((glass, CPO.hasSolidStructure, None))
    check("R5: undamaged, nothing reports", reports(base, mains["R5"]), set())
    check(f"R5: the library glass without its structure - its {len(copies)} copies in use report, the glass not",
          reports(g, mains["R5"]), copies)

    # form shapes
    space = [HLO[f"Phase_Space_R2_{c}Shape"] for c in ("Cuboid", "SolidCylinder", "Spherical", "Annulus")]
    ratios = [HLO[f"Phase_Structure_R2_{c}Shape"] for c in ("Cuboid", "SolidCylinder", "Annulus")]
    form = next(base.objects(liquid, CPO.definesForm))
    assert (form, RDF.type, CPO.SolidCylinderForm) in base, "the reactor liquid defines a solid cylinder form"
    g = copy(base)
    library_form = URIRef(str(glass) + "_TestForm")
    g.add((library_form, RDF.type, CPO.SolidCylinderForm))
    g.add((glass, CPO.definesForm, library_form))
    g.remove((form, CPO.hasHeight, None))
    g.remove((form, CPO.hasHeightToDiameterRatio, None))
    for label, shape_list in (("Space R2", space), ("Structure R2", ratios)):
        check(f"{label}: undamaged, nothing reports", reports(base, shape_list), set())
        check(f"{label}: a library form without values does not report, the reactor liquid does", reports(g, shape_list), {liquid})

    # R2: one collecting path = the three former ones
    sg = ShapesGraph(full)
    info = [p for p in full.objects(HLO.Phase_Structure_R2_CuboidShape, SH.property) if (p, SH.severity, SH.Info) in full]
    assert len(info) == 1
    new_path = next(full.objects(info[0], SH.path))
    former = Graph()
    for cls, ratio in FORMER_R2.items():
        # as the former paths stood: one ratio as a plain property, several as an alternative
        step = ratio if " " not in ratio else f"[ sh:alternativePath ( {ratio} ) ]"
        former.parse(format="turtle", data=f"""
            @prefix sh: <http://www.w3.org/ns/shacl#> . @prefix hlo: <{HLO}> . @prefix cpo: <{CPO}> .
            hlo:Former_{cls} sh:path ( [ sh:alternativePath ( cpo:definesForm cpo:fillsForm ) ] {step}
                [ sh:zeroOrMorePath hlo:specializationOf ] ) .""")
    fsg = ShapesGraph(former)
    paths = [next(former.objects(HLO[f"Former_{c}"], SH.path)) for c in FORMER_R2]
    differ = {p for p in phases(base) if in_use(base, p) and value_nodes_from_path(sg, p, new_path, base)
              != set().union(*(value_nodes_from_path(fsg, p, fp, base) for fp in paths))}
    check("R2: for every phase in use the one collecting path = the three former ones", differ, set())

    print("ALL OK" if not failures else f"{failures} FAILED")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
