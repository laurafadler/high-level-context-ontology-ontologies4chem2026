"""
Links every entity of the crate to the context aspects it describes - generated once, at the end
of a run, from the Context Requirement shapes (docs/rules_crate.md, section 6).

The links are a directory the crate brings along: whoever has only the crate can read at a
context aspect (e.g. ExperimentSpecificDeviceEnergy_Exp1) what belongs to it, without the shapes.
They say nothing new - they follow from shapes and data at any time - and are therefore never
written by hand anywhere else in the generator.

For each requirement (shacl/ContextRequirementShapes.ttl) and each of its focus nodes in the
crate, the existence paths are followed (rule 6.3):
- sh:property of the shape and of the value shapes (sh:qualifiedValueShape, sh:node) - their
  paths continue the path from the value;
- a branch of sh:or/sh:xone, and a shape named by sh:node, only when the node conforms to it; a
  value only when it conforms to its value shape. When an exclusion branch of an sh:or applies
  (rule 7.7: the requirement does not apply to this node), none of its branches is followed.
  Whether a node conforms is asked of pyshacl itself (Shape.validate with the node as focus) -
  the conditions of a requirement are not rebuilt;
- not: sh:Info property shapes (the collecting paths) and sh:not (exclusion conditions).
Every entity at the end of such a path is linked (rule 6.4) - not a value on the way, at which the
requirement still demands something (the form on the way to its dimensions) -, with the context of the focus node's
level (6.5): both directions for an entity of this crate, only the context side
(hlo:contextDescribedBy) for an entity of a library or of an earlier crate (6.6). Literals and
terms of ontologies and vocabularies are left out. Level and aspect come from hlo:requirementOf.

The value nodes of a path are pyshacl's own (value_nodes_from_path, step by step for a sequence,
as pyshacl does it), kept per path and node: the molecules of one phase go the same way from their
phase on, and so do requirements whose paths end alike (Molecule_Time_R2 and Phase_Time_R5).

pyshacl is pinned in dependencies.txt: Shape.validate, value_nodes_from_path and
ShapesGraph.lookup_shape_from_node are internal functions of pyshacl.
"""

import json
from pathlib import Path

from rdflib import RDF, Graph, Namespace, URIRef
from rdflib.collection import Collection
from pyshacl.helper.expression_helper import value_nodes_from_path
from pyshacl.pytypes import SHACLExecutor
from pyshacl.shapes_graph import ShapesGraph

import path_definitions
from helpers.file_handling import PROJECT_CONTEXT
from helpers.identifiers import CRATE_NAMESPACE_PREFIX, crate_id, split_id

SH = Namespace("http://www.w3.org/ns/shacl#")
HLO = Namespace("http://www.semanticweb.org/lf576/ontologies/2026/7/HigherLevelOntology#")

DESCRIBES = "hlo:describesContext"
DESCRIBED_BY = "hlo:contextDescribedBy"


class ContextLinkError(RuntimeError):
    """The context links cannot be generated as the rules say."""


def _prefixes() -> dict:
    return {prefix: iri for prefix, iri in PROJECT_CONTEXT.items() if isinstance(iri, str)}


def _expand(entity_id: str, prefixes: dict, base: str) -> str:
    """The full IRI of a compact ID, as JSON-LD resolves it with the crate's own prefix table."""
    if entity_id.startswith("#"):
        return base + entity_id
    prefix, _, local = entity_id.partition(":")
    if prefix in prefixes and not local.startswith("//"):
        return prefixes[prefix] + local
    return entity_id


def _compact(iri: str, prefixes: dict) -> str:
    """The compact ID of an IRI, with the longest matching namespace of the prefix table."""
    best = None
    for prefix, namespace in prefixes.items():
        if iri.startswith(namespace) and (best is None or len(namespace) > len(prefixes[best])):
            best = prefix
    return f"{best}:{iri[len(prefixes[best]):]}" if best else iri


def _parse_file(path: Path) -> Graph:
    # Pass the text, not the path: rdflib would otherwise take "C:\..." for a URL with the
    # scheme "c" (as in generator/workflow/run_shacl.py). publicID as there, so that IRIs resolve alike.
    graph = Graph()
    resolved = path.resolve()
    graph.parse(data=resolved.read_text(encoding="utf-8"), format="json-ld" if path.suffix == ".jsonld" else "xml",
                publicID=resolved.as_uri())
    return graph


def _build_data_graph(datagraph: dict, base: str):
    """Crate, libraries and ontologies in one graph - what generator/workflow/run_shacl.py validates.

    The crate is read with its own prefix table only (libraries/project_context.jsonld, which
    also declares schema, rdf and rdfs), without the RO-Crate context URL: that would be fetched
    from the internet in every run. Terms of the RO-Crate context without a prefix (about,
    conformsTo, dateCreated, ... at the root and the descriptor) are therefore not seen here."""
    data = Graph()
    crate_document = {"@context": PROJECT_CONTEXT, "@graph": datagraph.get("@graph", [])}
    data.parse(data=json.dumps(crate_document, ensure_ascii=False), format="json-ld", publicID=base)
    library_subjects = set()
    from helpers.library_files import library_files
    for path in library_files():
        library = _parse_file(path)
        library_subjects |= {s for s in library.subjects() if isinstance(s, URIRef)}
        data += library
    for path in (path_definitions.HLO_ONTOLOGY, path_definitions.CPO_ONTOLOGY):
        data += _parse_file(path)
    return data, library_subjects


def _aspects_of_requirements() -> dict:
    """requirement IRI -> local names of its context aspects ("DeviceEnergy", ...)."""
    ontology = _parse_file(path_definitions.HLO_ONTOLOGY)
    aspects = {}
    for requirement, aspect in ontology.subject_objects(HLO.requirementOf):
        aspects.setdefault(requirement, []).append(str(aspect).split("#", 1)[1])
    return aspects


def is_exclusion(shapes: Graph, branch) -> bool:
    """Whether a branch of an sh:or is an exclusion ("does not apply here") rather than a demand,
    read off its form as rule 7.7 writes it: [ sh:class hlo:Fixed ], an sh:not, or a condition on a
    flag or term (a property shape with sh:hasValue, also inside the members of an sh:and).
    check_context_requirements_consistency.py makes sure every sh:or puts its exclusions first and
    ends with a demand.

    Also a template and a library exemplar of one
    (rule 3.11): [ sh:class hlo:Template ], and - also
    inside an sh:and, next to [ sh:class hlo:Fixed ] - a property shape on hlo:specializationOf whose
    qualified value shape is [ sh:class hlo:Template ]: an exemplar takes over what its template
    states, the template itself is checked."""
    if any((branch, SH["class"], cls) in shapes for cls in (HLO.Fixed, HLO.Template)) or (branch, SH["not"], None) in shapes:
        return True
    members = [branch]
    for member_list in shapes.objects(branch, SH["and"]):
        members += list(Collection(shapes, member_list))
    for member in members:
        for property_shape in shapes.objects(member, SH.property):
            if (property_shape, SH.path, HLO.specializationOf) in shapes and any(
                    (qualified, SH["class"], HLO.Template) in shapes
                    for qualified in shapes.objects(property_shape, SH.qualifiedValueShape)):
                return True
    return any((property_shape, SH.hasValue, None) in shapes
               for member in members for property_shape in shapes.objects(member, SH.property))


class _Walker:
    """Follows the existence paths of one shapes graph through one data graph."""

    def __init__(self, shapes: Graph, data: Graph):
        self.shapes = shapes
        self.data = data
        self.shapes_graph = ShapesGraph(shapes)
        _ = self.shapes_graph.shapes   # builds the cache, also for the anonymous shapes in sh:or
        self.executor = SHACLExecutor()
        self._conforms = {}
        self._values = {}
        self._signatures = {}

    def shape(self, node):
        return self.shapes_graph.lookup_shape_from_node(node)

    def signature(self, path):
        """The form of a SHACL path as a tuple - two paths written alike get the same one, whatever
        their blank nodes."""
        if path not in self._signatures:
            if isinstance(path, URIRef):
                form = path
            elif self.shapes.value(path, RDF.first) is not None:
                form = ("sequence",) + tuple(self.signature(step) for step in Collection(self.shapes, path))
            else:
                form = tuple((str(p), self.signature(o)) for p, o in sorted(self.shapes.predicate_objects(path)))
            self._signatures[path] = form
        return self._signatures[path]

    def values(self, path, node) -> set:
        """The value nodes of path from node. A sequence is followed step by step, as pyshacl does
        (value_nodes_from_path): the first step, then the rest from each node it reaches - and the
        rest is kept per node, so that every way through the data is gone only once. Everything
        else (inverse, alternative, zero-or-more ...) is evaluated by pyshacl."""
        key = (self.signature(path), node)
        if key not in self._values:
            first = self.shapes.value(path, RDF.first)
            if first is None:
                result = value_nodes_from_path(self.shapes_graph, node, path, self.data)
            else:
                rest = self.shapes.value(path, RDF.rest)
                result = self.values(first, node)
                if rest != RDF.nil:
                    result = set().union(*(self.values(rest, step) for step in result))
            self._values[key] = result
        return self._values[key]

    def conforms(self, shape_node, node) -> bool:
        key = (shape_node, node)
        if key not in self._conforms:
            self._conforms[key] = self.shape(shape_node).validate(self.executor, self.data, focus=[node])[0]
        return self._conforms[key]

    def demands(self, shape_node, seen=frozenset()) -> bool:
        """Whether a shape requires something of its node: a property shape with sh:minCount or
        sh:qualifiedMinCount of at least 1, here or in its sh:or/sh:and/sh:xone members, sh:node
        shapes and value shapes - not inside sh:not, where only conditions stand."""
        if shape_node in seen:
            return False
        seen = seen | {shape_node}
        for property_shape in self.shapes.objects(shape_node, SH.property):
            for key in (SH.minCount, SH.qualifiedMinCount):
                count = self.shapes.value(property_shape, key)
                if count is not None and int(count) >= 1:
                    return True
            for key in (SH.qualifiedValueShape, SH.node):
                if any(self.demands(child, seen) for child in self.shapes.objects(property_shape, key)):
                    return True
        for logic in (SH["or"], SH["and"], SH.xone):
            for members in self.shapes.objects(shape_node, logic):
                if any(self.demands(member, seen) for member in Collection(self.shapes, members)):
                    return True
        return any(self.demands(child, seen) for child in self.shapes.objects(shape_node, SH.node))

    def ends(self, shape_node, node, found: set):
        """Collect in found every node at the end of an existence path of shape_node from node."""
        for property_shape in self.shapes.objects(shape_node, SH.property):
            if self.shapes.value(property_shape, SH.severity) == SH.Info:
                continue
            value_shapes = list(self.shapes.objects(property_shape, SH.qualifiedValueShape)) + \
                list(self.shapes.objects(property_shape, SH.node))
            # If the value shape still asks for something at the value, it is an intermediate link (the
            # form on the way to its dimensions, the interface to its area) and is not linked - only what
            # is asked for at the end (rule 6.4). A mere check of class or quantity kind asks for nothing.
            intermediate = any(self.demands(value_shape) for value_shape in value_shapes)
            for value in self.values(self.shapes.value(property_shape, SH.path), node):
                if value_shapes and not all(self.conforms(value_shape, value) for value_shape in value_shapes):
                    continue
                if not intermediate:
                    found.add(value)
                for value_shape in value_shapes:
                    self.ends(value_shape, value, found)
        for logic in (SH["or"], SH.xone):
            for members in self.shapes.objects(shape_node, logic):
                branches = list(Collection(self.shapes, members))
                # If an exclusion applies ("does not apply here", rule 7.7), the requirement does not hold for
                # this node - then a branch of demands that the node happens to satisfy links nothing either
                # (the mass of a device form under Phase_Space_R2).
                if any(is_exclusion(self.shapes, b) and self.conforms(b, node) for b in branches):
                    continue
                for member in branches:
                    if self.conforms(member, node):
                        self.ends(member, node, found)
        for members in self.shapes.objects(shape_node, SH["and"]):
            for member in Collection(self.shapes, members):
                self.ends(member, node, found)
        for member in self.shapes.objects(shape_node, SH.node):
            if self.conforms(member, node):
                self.ends(member, node, found)


def _context_id(focus_id: str, aspect: str) -> str:
    _, level, number = split_id(focus_id)
    if level == "SeriesSpecific":
        return crate_id(f"SeriesSpecific{aspect}_Series")
    if level == "ExperimentSpecific" and number is not None:
        return crate_id(f"ExperimentSpecific{aspect}_Exp{number}")
    raise ContextLinkError(f"{focus_id} is a focus node of a context requirement, but its level cannot be read from its ID.")


def link_contexts_from_shapes(datagraph: dict, crate_path: Path) -> dict:
    """Link every entity at the end of an existence path of a Context Requirement to the context
    aspect of the focus node's level (rules 6.1-6.6). Returns counts for the report.

    Called once, when the crate is complete. Nothing else in the generator writes these links -
    finding one already set stops the run, because it would not follow from the shapes."""
    entities = datagraph.get("@graph", [])
    already = [e["@id"] for e in entities if DESCRIBES in e or DESCRIBED_BY in e]
    if already:
        raise ContextLinkError(f"{len(already)} entities carry context links before they are generated from the shapes "
                               f"(e.g. {already[0]}) - context links are written only by helpers/context_links.py.")

    base = crate_path.resolve().as_uri()
    prefixes = _prefixes()
    crate_namespace = prefixes[CRATE_NAMESPACE_PREFIX]
    own_crate = _expand(crate_id(""), prefixes, base)
    by_iri = {_expand(e["@id"], prefixes, base): e for e in entities if "@id" in e}

    data, library_subjects = _build_data_graph(datagraph, base)
    shapes = Graph()
    shapes.parse(str(path_definitions.CONTEXT_SHAPES), format="turtle")
    walker = _Walker(shapes, data)
    aspects = _aspects_of_requirements()

    describes = {}      # crate entity -> its contexts
    described_by = {}   # context -> what describes it

    for main_shape, requirement in sorted(shapes.subject_objects(HLO.isShapeOfRequirement)):
        requirement_aspects = aspects.get(requirement)
        if not requirement_aspects:
            raise ContextLinkError(f"{requirement} has a shape, but no hlo:requirementOf in the ontology.")
        # str(): a URIRef has a different hash from the string with the same text.
        focus_nodes = sorted(n for n in walker.shape(main_shape).focus_nodes(data) if str(n) in by_iri)
        for focus in focus_nodes:
            found = set()
            walker.ends(main_shape, focus, found)
            for end in found:
                if not isinstance(end, URIRef):
                    continue
                end_iri = str(end)
                # Another crate counts as an earlier crate, even if this one carries a type stub for it
                # (add_reference_stub): nothing is written at it (rule 6.6).
                other_crate = end_iri.startswith(crate_namespace) and not end_iri.startswith(own_crate)
                if end_iri in by_iri and not other_crate:
                    target, in_crate = by_iri[end_iri]["@id"], True
                elif end in library_subjects or other_crate or end_iri.startswith(crate_namespace):
                    # Library or earlier crate: nothing is written there (rule 6.6).
                    target, in_crate = _compact(end_iri, prefixes), False
                else:
                    continue   # a term of an ontology or a vocabulary
                for aspect in requirement_aspects:
                    context_id = _context_id(by_iri[str(focus)]["@id"], aspect)
                    described_by.setdefault(context_id, set()).add(target)
                    if in_crate:
                        describes.setdefault(target, set()).add(context_id)

    by_id = {e["@id"]: e for e in entities if "@id" in e}
    outside = set()
    for context_id, targets in described_by.items():
        context = by_id.get(context_id)
        if context is None:
            raise ContextLinkError(f"Context aspect {context_id} is not in the crate (create_all_contexts).")
        context[DESCRIBED_BY] = [{"@id": target} for target in sorted(targets)]
        outside |= {target for target in targets if target not in describes}
    for target, context_ids in describes.items():
        links = [{"@id": context_id} for context_id in sorted(context_ids)]
        # One context as a single reference, several as a list - as before in the crate.
        by_id[target][DESCRIBES] = links[0] if len(links) == 1 else links

    summary = {"entities": len(describes), "contexts": len(described_by), "references_outside": len(outside)}
    print(f"[contexts] {summary['entities']} entities linked to {summary['contexts']} context aspects from the shapes; "
          f"{summary['references_outside']} entities of libraries or earlier crates listed at the context side only.")
    return summary
