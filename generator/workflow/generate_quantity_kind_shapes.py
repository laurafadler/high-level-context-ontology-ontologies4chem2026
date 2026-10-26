"""
Write shacl/QuantityKindShapes.ttl: the checks of rule 4.4 (quantity kinds of values) as plain
SHACL Core, one shape per property, generated from the ontology.

Which quantity kinds the values of a property may have is stated once, in the ontology
(cpo:valueHasQuantityKind on the property, inherited by its sub-properties: cpo:hasInnerHeight
takes Height from cpo:hasHeight, the nearest annotation wins). SHACL Core cannot read an OWL
annotation at validation time, and GraphDB runs SHACL Core (no SHACL-SPARQL), so the checks are
written out per property - by this script, never by hand: the ontology stays the only place where
the kinds are stated.

For every property P with allowed kinds:
  one kind K       every value of P has qudt:hasQuantityKind K                      (Violation)
  several kinds    every evidence and reference of a value of P has one of them    (Violation)
                   every value of P that is not an hlo:Actual has one of them      (Violation)
                   an hlo:Actual value of P has none - which one would be a         (Warning)
                   statement nobody made
An Actual without evidence and reference is fine: it says "this quantity exists".

Run from the repository root after changing a cpo:valueHasQuantityKind annotation:
    python generator/workflow/generate_quantity_kind_shapes.py            write the file
    python generator/workflow/generate_quantity_kind_shapes.py --check    exit 1 if the file is out of date
"""
import argparse
import sys
from pathlib import Path

from rdflib import Graph, Namespace, RDFS

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import path_definitions  # noqa: E402

CPO = Namespace("http://www.semanticweb.org/lf576/ontologies/2026/7/ChemicalProcessOntology#")
OUT = path_definitions.QUANTITY_KIND_SHAPES


def local(iri) -> str:
    return str(iri).rsplit("#", 1)[-1].rsplit("/", 1)[-1]


def allowed_kinds(ontology: Graph) -> dict:
    """property -> sorted allowed kinds (full IRIs), the nearest annotation up the
    rdfs:subPropertyOf chain winning, as helpers/ontology_functions.py: quantity_kinds_of_property."""
    # The full IRI, not only the local name: most kinds come from QUDT, but not all
    # (cpo:ReactionRate stands in the project's own ontology).
    annotated = {}
    for prop, kind in ontology.subject_objects(CPO.valueHasQuantityKind):
        annotated.setdefault(prop, set()).add(str(kind))
    result = {}
    candidates = set(annotated)
    for prop in list(annotated):
        candidates |= set(ontology.transitive_subjects(RDFS.subPropertyOf, prop))
    for prop in candidates:
        level, seen = [prop], set()
        while level:
            found = [p for p in level if p in annotated]
            if found:
                result[prop] = sorted(set().union(*(annotated[p] for p in found)))
                break
            seen |= set(level)
            level = [s for p in level for s in ontology.objects(p, RDFS.subPropertyOf) if s not in seen]
    return dict(sorted(result.items(), key=lambda item: local(item[0])))


def shape_for(prop, kinds) -> str:
    name = local(prop)
    head = f"hlo:QuantityKind_{name}_Shape\n    a sh:NodeShape ;\n    sh:targetSubjectsOf cpo:{name} ;\n"
    if len(kinds) == 1:
        return head + f'''    sh:property [
        sh:path cpo:{name} ;
        sh:node [ sh:property [ sh:path qudt:hasQuantityKind ; sh:hasValue <{kinds[0]}> ] ] ;
        sh:severity sh:Violation ;
        sh:message "A value of cpo:{name} must have the quantity kind {local(kinds[0])} (cpo:valueHasQuantityKind) - it is missing or another one." ;
    ] .

'''
    listed = " ".join(f"<{k}>" for k in kinds)
    stated = ", ".join(local(k) for k in kinds)
    return head + f'''    sh:property [
        sh:path ( cpo:{name} [ sh:alternativePath ( hlo:hasEvidence hlo:hasReference ) ] ) ;
        sh:node [ sh:property [ sh:path qudt:hasQuantityKind ; sh:minCount 1 ; sh:in ( {listed} ) ] ] ;
        sh:severity sh:Violation ;
        sh:message "An evidence or reference of a value of cpo:{name} must state one of the quantity kinds the property allows ({stated}) - it is missing or another one." ;
    ] ;
    sh:property [
        sh:path cpo:{name} ;
        sh:node [ sh:or ( [ sh:class hlo:Actual ] [ sh:property [ sh:path qudt:hasQuantityKind ; sh:minCount 1 ; sh:in ( {listed} ) ] ] ) ] ;
        sh:severity sh:Violation ;
        sh:message "A direct value of cpo:{name} (not an hlo:Actual) must state one of the quantity kinds the property allows ({stated}) - it is missing or another one." ;
    ] ;
    sh:property [
        sh:path cpo:{name} ;
        sh:node [ sh:or ( [ sh:not [ sh:class hlo:Actual ] ] [ sh:property [ sh:path qudt:hasQuantityKind ; sh:maxCount 0 ] ] ) ] ;
        sh:severity sh:Warning ;
        sh:message "The Actual of cpo:{name} states a quantity kind although the property allows several ({stated}). The kind belongs on its evidence and reference values - on the Actual it is a statement nobody made (rule 4.4)." ;
    ] .

'''


def render(kinds_by_property: dict) -> str:
    out = ["""@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix hlo: <http://www.semanticweb.org/lf576/ontologies/2026/7/HigherLevelOntology#> .
@prefix cpo: <http://www.semanticweb.org/lf576/ontologies/2026/7/ChemicalProcessOntology#> .
@prefix qudt: <http://qudt.org/schema/qudt/> .
@prefix quantitykind: <http://qudt.org/vocab/quantitykind/> .

#################################################################
#
# Quantity kinds of values (rule 4.4) - GENERATED, do not edit by hand
#
#################################################################
#
# Generated by generator/workflow/generate_quantity_kind_shapes.py from cpo:valueHasQuantityKind in the
# ChemicalProcessOntology (with inherited subproperties). After a change there, run the script
# again; --check reports when this file is out of date. Plain SHACL Core, so that the check
# also runs in GraphDB, which does not run SHACL-SPARQL reliably.

"""]
    for prop, kinds in kinds_by_property.items():
        out.append(shape_for(prop, kinds))
    return "".join(out)


def out_of_date_message(ontology: Graph = None):
    """None if QuantityKindShapes.ttl is what this script would write from the current ontology,
    otherwise the message to show. Used by --check, check_context_requirements_consistency.py
    (check 10) and generator/workflow/run_shacl.py (which refuses to validate against an out-of-date file)."""
    if ontology is None:
        ontology = Graph().parse(str(path_definitions.CPO_ONTOLOGY))
    current = OUT.read_text(encoding="utf-8") if OUT.exists() else None
    if current == render(allowed_kinds(ontology)):
        return None
    return (f"{OUT.name} does not match cpo:valueHasQuantityKind in the ontology (out of date or "
            f"edited by hand) - run generator/workflow/generate_quantity_kind_shapes.py")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="only compare, exit 1 if the file is out of date")
    args = parser.parse_args()
    ontology = Graph().parse(str(path_definitions.CPO_ONTOLOGY))
    kinds = allowed_kinds(ontology)
    text = render(kinds)
    if args.check:
        message = out_of_date_message(ontology)
        if message:
            sys.exit(message)
        print(f"{OUT.name} is up to date ({len(kinds)} properties).")
        return
    OUT.write_text(text, encoding="utf-8", newline="\n")
    single = sum(1 for k in kinds.values() if len(k) == 1)
    print(f"{OUT.name}: {len(kinds)} properties ({single} with one kind, {len(kinds) - single} with several).")


if __name__ == "__main__":
    main()
