"""
Counter-check (rule 7.14) for the Molecule requirements:
- the formats of the identifiers and notations of a chemical entity are checked by hlo:ChemicalEntity_Format_Shape
  in shapes/DataQualityShapes.ttl (rule 2.8), no longer by the requirements: undamaged it reports nothing; with one
  wrong value each (CAS number, PubChem CID, InChIKey, InChI, SMILES, formula) at six library entries it reports
  exactly those six, each at its own property, and the requirements Molecule_Information_R2/R3/R4,
  Molecule_Structure_R2, Molecule_Structure_Substance_R1 and Molecule_Substance_R2 report nothing more than before - they ask only that a
  value exists. With the CAS number of water removed, Molecule_Information_R2 reports water and every molecule that
  reads it through the chain, the format shape nothing;
- Molecule_Energy_R1 excludes Fixed molecules (rule 7.7): with water radioactive and no field anywhere, the water
  molecules in use report, the library entries of water do not; one with a field of its own stops reporting;
- the value shape of Molecule_Information_R1 names the class (chebi:Molecule, hlo:Fixed): undamaged nothing reports;
  a molecule whose chain ends at a Fixed entry that is no molecule reports.

Hydrogenation crate (crate, libraries, ontologies, as generator/workflow/run_shacl.py builds it); validates only the
shapes concerned. Writes nothing.

Run from the repository root (about a minute):
    python generator/tests/molecule_requirements_test.py [--crate PATH]
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import path_definitions  # noqa: E402
import pyshacl  # noqa: E402
from rdflib import Graph, Literal, Namespace, RDF, RDFS, URIRef  # noqa: E402
from workflow.run_shacl import build_data_graph  # noqa: E402

SH = Namespace("http://www.w3.org/ns/shacl#")
HLO = Namespace("http://www.semanticweb.org/lf576/ontologies/2026/7/HigherLevelOntology#")
CPO = Namespace("http://www.semanticweb.org/lf576/ontologies/2026/7/ChemicalProcessOntology#")
CHEBI = Namespace("http://purl.obolibrary.org/obo/chebi.owl#")
WATER = "/chemical_entity/Molecule_0003"
# Requirements that ask only for the value (the format is a data quality shape).
EXISTENCE = ["Molecule_Information_R2", "Molecule_Information_R3", "Molecule_Information_R4", "Molecule_Structure_R2",
             "Molecule_Structure_Substance_R1", "Molecule_Substance_R2"]


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
    hits = {s for s in graph.subjects() if isinstance(s, URIRef) and str(s).endswith(suffix)}
    assert len(hits) == 1, (suffix, hits)
    return hits.pop()


def results(g, shapes) -> set:
    """(focus node, result path) of every result."""
    _, report, _ = pyshacl.validate(g, shacl_graph=shapes, inference="none", advanced=True)
    return {(report.value(r, SH.focusNode), report.value(r, SH.resultPath))
            for r in report.subjects(RDF.type, SH.ValidationResult)}


def focus(g, shapes) -> set:
    return {f for f, _ in results(g, shapes)}


def copy(g) -> Graph:
    out = Graph()
    out += g
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--crate", default=str(path_definitions.crate_path("hydrogenation_rdy_2026_09")))
    args = parser.parse_args()
    base = build_data_graph(Path(args.crate), [], set())
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

    molecule_classes = {CHEBI.Molecule} | set(base.transitive_subjects(RDFS.subClassOf, CHEBI.Molecule))
    molecules = {m for c in molecule_classes for m in base.subjects(RDF.type, c)}
    fixed = {m for m in molecules if (m, RDF.type, HLO.Fixed) in base}

    # ---- formats
    fmt = shapes_of(quality, HLO.ChemicalEntity_Format_Shape)
    existence = Graph()
    for req in EXISTENCE:
        existence += shapes_of(context, HLO[f"{req}_MainShape"])
    check("format: undamaged, nothing reports", results(base, fmt), set())
    before = focus(base, existence)
    damages = [(CPO.hasCAS, Literal("7732185")), (CPO.hasPubChemCID, Literal("0962")),
               (CPO.hasInChIKey, Literal("xlyofnoqvpjjnp-uhfffaoysa-n")), (CPO.hasInChI, Literal("1S/H2O/h1H2")),
               (CPO.hasSMILES, Literal(5)), (CPO.hasMolecularFormula, Literal(18))]
    damaged, expected = copy(base), set()
    entries = sorted(m for m in fixed if all((m, p, None) in base for p, _ in damages))
    for entry, (prop, value) in zip(entries, damages):
        damaged.remove((entry, prop, None))
        damaged.add((entry, prop, value))
        expected.add((entry, prop))
    check("format: one wrong value each at six entries - reported at exactly those, each at its property",
          results(damaged, fmt), expected)
    check("format: ... the existence requirements report nothing more", focus(damaged, existence), before)

    water = one(base, WATER)
    readers = {m for m in molecules if water in set(base.transitive_objects(m, HLO.specializationOf))}
    no_cas = copy(base)
    no_cas.remove((water, CPO.hasCAS, None))
    r2 = shapes_of(context, HLO.Molecule_Information_R2_MainShape)
    check("Molecule_Information_R2: water without CAS - water and every molecule reading it report",
          focus(no_cas, r2) - focus(base, r2), readers)
    check("format: ... a missing value is no format finding", results(no_cas, fmt), set())

    # ---- Molecule_Energy_R1
    e1 = shapes_of(context, HLO.Molecule_Energy_R1_MainShape)
    radioactive = copy(base)
    radioactive.add((water, CPO.isRadioactive, Literal(True)))
    water_in_use = readers - fixed
    assert water_in_use and readers & fixed, "the crate has water in use and library records of water"
    assert not any((m, CPO.hasEnergyField, None) in base for m in readers)
    check("Molecule_Energy_R1: undamaged, nothing reports", focus(base, e1), set())
    check("Molecule_Energy_R1: water radioactive - the water molecules in use report, the library entries not",
          focus(radioactive, e1), water_in_use)
    first = sorted(water_in_use)[0]
    radioactive.add((first, CPO.hasEnergyField, URIRef(str(first) + "_TestField")))
    radioactive.add((URIRef(str(first) + "_TestField"), RDF.type, CPO.EnergyField))
    check("Molecule_Energy_R1: ... one with a field of its own does not", focus(radioactive, e1), water_in_use - {first})

    # ---- Molecule_Information_R1
    r3 = shapes_of(context, HLO.Molecule_Information_R1_MainShape)
    check("Molecule_Information_R1: undamaged, nothing reports", focus(base, r3), set())
    other = copy(base)
    some_fixed_phase = next(p for p in base.subjects(RDF.type, HLO.Fixed)
                            if (p, RDF.type, CPO.GasPhase) in base or (p, RDF.type, CPO.LiquidPhase) in base)
    target = sorted(m for m in water_in_use if (None, HLO.specializationOf, m) not in base)[0]   # nobody reads through it
    other.remove((target, HLO.specializationOf, None))
    other.add((target, HLO.specializationOf, some_fixed_phase))
    check("Molecule_Information_R1: chain ending at a Fixed entry that is no molecule - reports",
          focus(other, r3), {target})

    print("all green" if not failures else f"{failures} FAILED")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
