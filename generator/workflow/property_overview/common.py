"""
What every part of the property overview needs: the prefixes, the four levels, the class tree of the
ontologies and a small reader for SHACL paths that can also walk them in the data.

The overview speaks in CURIEs as the libraries and crates do (cpo:Device, hlo:specializationOf); IRIs of
the ontologies and shapes are turned into them with the prefix table of the project.
"""
import sys
from pathlib import Path

from rdflib import Graph, URIRef, Literal, RDF, RDFS, OWL
from rdflib.collection import Collection

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "generator"))
import path_definitions  # noqa: E402
from helpers.file_handling import PROJECT_CONTEXT  # noqa: E402

SH = "http://www.w3.org/ns/shacl#"

# The four levels, in the order of the columns (rule 3: template, library, series, experiment).
LEVELS = ["Template", "Fixed", "Series", "Experiment"]
LEVEL_TYPES = {"hlo:Template": "Template", "hlo:Fixed": "Fixed",
               "hlo:SeriesSpecific": "Series", "hlo:ExperimentSpecific": "Experiment"}

# Prefixes: the project's, and a few the shapes and ontologies use besides (schema.org also under https).
PREFIXES = dict(PROJECT_CONTEXT)
PREFIXES.update({"sh": SH, "owl": "http://www.w3.org/2002/07/owl#", "schema_https": "https://schema.org/"})
_BY_LENGTH = sorted(PREFIXES.items(), key=lambda item: -len(item[1]))


def curie(node) -> str:
    """IRI -> 'cpo:Device'; a literal -> its text; unknown IRIs stay whole."""
    if isinstance(node, Literal):
        return str(node)
    text = str(node)
    for prefix, namespace in _BY_LENGTH:
        if text.startswith(namespace):
            return ("schema" if prefix == "schema_https" else prefix) + ":" + text[len(namespace):]
    return text


def as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def types_of(entity: dict) -> list:
    return as_list(entity.get("@type"))


# ---------------------------------------------------------------------------
# Class tree
# ---------------------------------------------------------------------------

class ClassTree:
    """rdfs:subClassOf of the CPO and the HLO, as CURIEs. Classes the ontologies do not know (plain
    RO-Crate types such as Dataset) have no parents."""

    def __init__(self):
        graph = Graph()
        graph.parse(str(path_definitions.CPO_ONTOLOGY))
        graph.parse(str(path_definitions.HLO_ONTOLOGY))
        self.parents = {}
        self.labels = {}
        for sub, sup in graph.subject_objects(RDFS.subClassOf):
            if isinstance(sub, URIRef) and isinstance(sup, URIRef):
                self.parents.setdefault(curie(sub), set()).add(curie(sup))
        for cls in graph.subjects(RDF.type, OWL.Class):
            if isinstance(cls, URIRef):
                self.parents.setdefault(curie(cls), set())
                comment = graph.value(cls, RDFS.comment)
                if comment is not None and not str(comment).lstrip().startswith("#"):
                    self.labels[curie(cls)] = str(comment)
        self._ancestors = {}
        # Individuals of the ontologies (cpo:Batch a cpo:ModeOfOperation): the shapes check their class too.
        classes = set(self.parents)
        self.individual_types = {}
        for individual, cls in graph.subject_objects(RDF.type):
            if isinstance(individual, URIRef) and curie(cls) in classes:
                self.individual_types.setdefault(curie(individual), set()).add(curie(cls))
        # Properties of the ontologies, for turning a quantity name of the generator into its property.
        self.properties = set()
        for kind in (OWL.ObjectProperty, OWL.DatatypeProperty, OWL.AnnotationProperty, RDF.Property):
            for prop in graph.subjects(RDF.type, kind):
                if isinstance(prop, URIRef):
                    self.properties.add(curie(prop))
        # rdfs:domain and rdfs:range of the properties (for the class maps): sets of CURIEs, None for a class
        # expression (owl:unionOf ...) that is not a named class.
        self.domains, self.ranges = {}, {}
        for predicate, found in ((RDFS.domain, self.domains), (RDFS.range, self.ranges)):
            for prop, cls in graph.subject_objects(predicate):
                if isinstance(prop, URIRef):
                    found.setdefault(curie(prop), set()).add(curie(cls) if isinstance(cls, URIRef) else None)

    def ancestors(self, cls: str) -> set:
        """The class itself and all its superclasses."""
        if cls not in self._ancestors:
            found, todo = {cls}, [cls]
            while todo:
                for parent in self.parents.get(todo.pop(), ()):
                    if parent not in found:
                        found.add(parent)
                        todo.append(parent)
            self._ancestors[cls] = found
        return self._ancestors[cls]

    def is_a(self, cls: str, other: str) -> bool:
        return other in self.ancestors(cls)

    def direct_parents(self, cls: str) -> set:
        return set(self.parents.get(cls, ()))


# ---------------------------------------------------------------------------
# SHACL paths
#
# A path becomes a small tuple tree:
#   ("p", "cpo:hasForm")       one property
#   ("inv", path)              sh:inversePath
#   ("seq", [paths])           a sequence (RDF list)
#   ("alt", [paths])           sh:alternativePath
#   ("star", path)             sh:zeroOrMorePath
#   ("plus", path)             sh:oneOrMorePath
#   ("opt", path)              sh:zeroOrOnePath
# ---------------------------------------------------------------------------

def read_path(graph: Graph, node):
    if isinstance(node, URIRef):
        return ("p", curie(node))
    if node == RDF.nil or (node, RDF.first, None) in graph:
        return ("seq", [read_path(graph, part) for part in Collection(graph, node)])
    for predicate, kind in (("alternativePath", "alt"), ("zeroOrMorePath", "star"),
                            ("oneOrMorePath", "plus"), ("zeroOrOnePath", "opt"), ("inversePath", "inv")):
        inner = graph.value(node, URIRef(SH + predicate))
        if inner is not None:
            if kind == "alt":
                return ("alt", [read_path(graph, part) for part in Collection(graph, inner)])
            return (kind, read_path(graph, inner))
    return ("p", "?")


def flatten(path):
    """A sequence inside a sequence is one sequence."""
    if path[0] == "seq":
        parts = []
        for part in path[1]:
            part = flatten(part)
            parts += part[1] if part[0] == "seq" else [part]
        return parts[0] if len(parts) == 1 else ("seq", parts)
    if path[0] == "alt":
        return ("alt", [flatten(p) for p in path[1]])
    if path[0] in ("star", "plus", "opt", "inv"):
        return (path[0], flatten(path[1]))
    return path


CHAIN = ("star", ("p", "hlo:specializationOf"))


def split_chain(path):
    """(True, rest) if the path starts with [ sh:zeroOrMorePath hlo:specializationOf ] - the thing may
    stand one level higher and is read through the chain (rule 3.6) - otherwise (False, path)."""
    path = flatten(path)
    if path == CHAIN:
        return True, None
    if path[0] == "seq" and path[1][0] == CHAIN:
        rest = path[1][1:]
        return True, (rest[0] if len(rest) == 1 else ("seq", rest))
    return False, path


def path_text(path) -> str:
    """Short text: 'cpo:madeOfMaterial / dcterms:hasPart / cpo:hasTemperature', '^cpo:isRoomOf'."""
    if path is None:
        return ""
    kind = path[0]
    if kind == "p":
        return path[1]
    if kind == "inv":
        return "^" + path_text(path[1])
    if kind == "seq":
        return " / ".join(path_text(p) for p in path[1])
    if kind == "alt":
        return "(" + " | ".join(path_text(p) for p in path[1]) + ")"
    inner = path_text(path[1])
    if path[1][0] == "seq":
        inner = f"({inner})"
    return inner + {"star": "*", "plus": "+", "opt": "?"}[kind]


def first_property(path) -> str:
    """The property a path starts with, as the row of the class it starts at ('^org:hasSite' for an
    inverse one); a path that starts with alternatives keeps them together."""
    path = flatten(path)
    if path[0] == "seq":
        return first_property(path[1][0])
    return path_text(path)
