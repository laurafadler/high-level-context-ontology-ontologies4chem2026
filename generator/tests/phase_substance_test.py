"""
Counter-check (rule 7.14) for the Phase Substance requirements:
- Phase_Substance_R1 excludes Fixed phases (rule 7.7): a library phase without constituents does not report, a phase
  in use does;
- Phase_Substance_R4 is an assignment: it links the concentration, mass and amount of substance of every molecule of
  the reactor liquid (the mass and amount) and never reports - with the concentration of one molecule
  taken away, only Molecule_Space_R2 reports it, at the molecule (not the phase a second time); with its mass taken
  away, the mass is not linked and only Molecule_Space_R3 reports.

Hydrogenation crate (crate, libraries, ontologies, as generator/workflow/run_shacl.py builds it); validates only
these shapes. Writes nothing.

Run from the repository root (well under a minute):
    python generator/tests/phase_substance_test.py [--crate PATH]
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
CHEBI = Namespace("http://purl.obolibrary.org/obo/chebi.owl#")
DCTERMS = Namespace("http://purl.org/dc/terms/")
LIBRARY_GLASS = "vessel001_Body_SolidPhase"
REACTOR_LIQUID = "Phase_LiquidVessel_Phase_SeriesSpecific"


def shapes_of(full, main) -> Graph:
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
            print(f"     expected {sorted(map(str, expected))[:4]}\n     got      {sorted(map(str, got))[:4]}")

    def reports(g, main):
        _, results, _ = pyshacl.validate(g, shacl_graph=shapes_of(full, main), inference="none", advanced=True)
        return set(results.objects(None, SH.focusNode))

    def copy(g):
        out = Graph()
        out += g
        return out

    glass, liquid = one(base, LIBRARY_GLASS), one(base, REACTOR_LIQUID)
    assert (glass, RDF.type, HLO.Fixed) in base and (liquid, RDF.type, HLO.Fixed) not in base

    # R1
    check("R1: undamaged, nothing reports", reports(base, HLO.Phase_Substance_R1_MainShape), set())
    g = copy(base)
    g.remove((glass, DCTERMS.hasPart, None))
    g.remove((liquid, DCTERMS.hasPart, None))
    check("R1: both without constituents - only the phase in use reports", reports(g, HLO.Phase_Substance_R1_MainShape), {liquid})

    # R4 as an assignment
    molecule_classes = {CHEBI.Molecule} | set(base.transitive_subjects(RDFS.subClassOf, CHEBI.Molecule))
    molecules = [m for m in base.objects(liquid, DCTERMS.hasPart) if any(t in molecule_classes for t in base.objects(m, RDF.type))]
    quantities = {q for m in molecules for p in (CPO.hasConcentration, CPO.hasMass, CPO.hasAmountOfSubstance)
                  for q in base.objects(m, p)}
    assert len(quantities) == 3 * len(molecules), "every molecule has its own three actuals (the liquid is a mixture)"
    ends = set()
    _Walker(full, base).ends(HLO.Phase_Substance_R4_MainShape, liquid, ends)
    check(f"R4: the reactor liquid links concentration, mass and amount of its {len(molecules)} molecules", ends,
          quantities)
    check("R4: the assignment reports nothing", reports(base, HLO.Phase_Substance_R4_MainShape), set())
    g = copy(base)
    g.remove((molecules[0], CPO.hasConcentration, None))
    check("R4: a molecule without its concentration - the assignment still reports nothing",
          reports(g, HLO.Phase_Substance_R4_MainShape), set())
    check("Molecule_Space_R2: ... the gap is reported once, at the molecule",
          reports(g, HLO.Molecule_Space_R2_MainShape) - reports(base, HLO.Molecule_Space_R2_MainShape), {molecules[0]})
    g = copy(base)
    mass = next(base.objects(molecules[0], CPO.hasMass))
    g.remove((molecules[0], CPO.hasMass, None))
    ends = set()
    _Walker(full, g).ends(HLO.Phase_Substance_R4_MainShape, liquid, ends)
    check("R4: a molecule without its mass - the mass is no longer linked, the rest stays", ends, quantities - {mass})
    check("R4: ... the assignment still reports nothing", reports(g, HLO.Phase_Substance_R4_MainShape), set())
    check("Molecule_Space_R3: ... the gap is reported once, at the molecule",
          reports(g, HLO.Molecule_Space_R3_MainShape) - reports(base, HLO.Molecule_Space_R3_MainShape), {molecules[0]})

    print("ALL OK" if not failures else f"{failures} FAILED")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
