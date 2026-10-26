"""
Stand-alone, read-only check script for the project's ContextRequirement conventions:
compares ontologies/HigherLevelOntology.rdf against shapes/ContextRequirementShapes.ttl and
checks a number of conventions both files are meant to follow. Changes no files - a plain
report on the console, with exit code 1 when at least one problem was found and 0 otherwise,
so it can be used in a CI check.

Run:
    python generator/workflow/check_context_requirements_consistency.py

What is checked:
1. Every requirement referenced in the shapes through hlo:isShapeOfRequirement exists as an
   hlo:ContextRequirement in the ontology, and the other way round (every ContextRequirement
   has at least one shape).
2. hlo:requirementOf (requirement -> context aspect) and hlo:hasRequirement (context aspect
   -> requirement) are symmetric to each other.
3. hlo:hasSpecialization appears in no sh:path - paths may only run "upwards", i.e. through
   hlo:specializationOf, never "downwards", because otherwise the value of one experiment
   would wrongly satisfy the requirement of another.
4. Every ContextRequirement has an rdfs:label and an English schema:description
   (xml:lang="en").
5. Every ContextRequirement ID follows the scheme <level>_<aspect>_R<n>, where <aspect> may
   consist of several aspect names run together (Molecule_Structure_Substance_R1,
   for example).
6. Every property shape (an sh:property blank node) carries its OWN, explicit sh:severity -
   not only the enclosing NodeShape. SHACL does not inherit severity from the NodeShape to a
   free-standing property shape; without its own, it falls back to the SHACL default
   sh:Violation. sh:Info is expressly allowed for the deliberately non-binding
   ContextPathShape collection paths
   (Molecule_Energy_R2/Device_Energy_R6/Phase_Energy_R5), not only sh:Warning.
7. The collection paths in Device_Energy_R6_ContextPathShape,
   Phase_Energy_R5_ContextPathShape and Molecule_Energy_R2_ContextPathShape climb up over
   exactly PARENT_PROPERTIES and go down over exactly CHILD_PROPERTIES
   (helpers/energy_fields.py, the master lists), each as a repeated alternative of its own -
   never both in one. After cpo:hasEnergyField the only step allowed is the chain of the field
   (hlo:specializationOf). Neither the lists nor the paths may go against a location
   (no sh:inversePath, no location property in CHILD_PROPERTIES): from the Fixed room such a
   step would reach the devices of every level. The way down from the ambient air into the
   devices of the room is cpo:isLocationOf, which the generator sets within the crate on one
   level only (helpers/properties.py: set_location).
8. Every sh:Info property shape - a collection path, such as the path along the Actual
   chain that every requirement for an Actual carries - hangs DIRECTLY off a top-level shape
   and has no sh:minCount/sh:qualifiedMinCount. A property shape without a minimum count is
   always satisfied; inside sh:or it would silently satisfy the whole requirement, and with
   a minimum count it would no longer only collect.
9. For each context object (cpo:Device, cpo:Phase) and each form class that states restrictions in the
   ChemicalProcessOntology, the shapes require exactly those properties - dimensions, aspect ratios and,
   for devices, the cavity; a phase's own form is never hollow. Every
   form shape starts at its context object (rule 7.11): sh:targetClass is the device or
   phase, one property shape follows the prescribed path to its forms, and its node shape excludes every
   other class (for phases also forms not defined by a phase or a material) before it demands.
   hlo:targetFormClass/hlo:targetFormDefinedBy name class and context object and must match.
10. shacl/QuantityKindShapes.ttl is up to date: exactly what generator/workflow/generate_quantity_kind_shapes.py
    would write from the current cpo:valueHasQuantityKind annotations. The file is generated,
    never edited by hand; an out-of-date file checks old kinds without any message saying so.
11. Every sh:or puts its exclusions first and ends with at least one demand (rule 7.7). An
    exclusion is read off its form - [ sh:class hlo:Fixed ], an sh:not, or a condition with
    sh:hasValue (helpers/context_links.py: is_exclusion). The context links rely on it: when an
    exclusion applies, the requirement does not apply and links nothing.
12. Every requirement is typed with exactly one of the three kinds of rule 7.16 - hlo:ExistenceRequirement,
    hlo:SurroundingsRequirement, hlo:AssignmentRequirement - and the kind matches what its shapes
    contain: a demand (a property shape that is neither sh:Info nor qualifiedMinCount 0, or an
    sh:or/sh:and/sh:node on the shape itself) makes an existence requirement, a property shape with
    sh:qualifiedMinCount 0 an assignment, only sh:Info collection paths a surroundings requirement.
    A requirement that mixes demand and assignment is reported as well.
"""

import re
import sys
from pathlib import Path

from rdflib import Graph, Namespace, RDF, RDFS, OWL, BNode
from rdflib.collection import Collection

# Runs from generator/workflow/ - the generator has to be on the search path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import path_definitions  # noqa: E402
from helpers.energy_fields import PARENT_PROPERTIES, CHILD_PROPERTIES  # noqa: E402
from workflow.generate_quantity_kind_shapes import out_of_date_message  # noqa: E402
from workflow.generate_function_shapes import out_of_date_message as functions_out_of_date_message  # noqa: E402
from helpers.context_links import is_exclusion  # noqa: E402

HLO = Namespace("http://www.semanticweb.org/lf576/ontologies/2026/7/HigherLevelOntology#")
SH = Namespace("http://www.w3.org/ns/shacl#")
# http, not https: that is how the ontology declares it and how RO-Crate 1.3 asks for it.
# With https the script found not a single description.
SCHEMA = Namespace("http://schema.org/")

# <Level>_<Aspect(s)>_R<n>, where level/aspect are one CamelCase word each, with any number of
# aspect names joined together (e.g. Molecule_Structure_Substance_R1).
ID_PATTERN = re.compile(r"^[A-Z][A-Za-z]*(_[A-Z][A-Za-z]*)+_R\d+$")

# The three kinds of a requirement (rule 7.16), check 12.
REQUIREMENT_KINDS = (HLO.ExistenceRequirement, HLO.SurroundingsRequirement, HLO.AssignmentRequirement)

CONTEXT_PATH_SHAPES = [
    "Device_Energy_R6_ContextPathShape",
    "Phase_Energy_R5_ContextPathShape",
    "Molecule_Energy_R2_ContextPathShape",
]


def load_graphs():
    ontology = Graph()
    ontology.parse(str(path_definitions.HLO_ONTOLOGY))

    shapes = Graph()
    shapes.parse(str(path_definitions.CONTEXT_SHAPES), format="turtle")

    return ontology, shapes


def check_requirements_both_ways(ontology, shapes, problems):
    req_in_shapes = {req for _, req in shapes.subject_objects(HLO.isShapeOfRequirement)}
    # Without a reasoner: instances of the superclass and of its subclasses (the three kinds, check 12).
    requirement_classes = set(ontology.transitive_subjects(RDFS.subClassOf, HLO.ContextRequirement))
    req_in_ontology = {req for cls in requirement_classes for req in ontology.subjects(RDF.type, cls)}

    for req in sorted(req_in_shapes - req_in_ontology, key=str):
        problems.append(f"Requirement referenced in the shapes, but not declared as hlo:ContextRequirement in the ontology: {req}")
    for req in sorted(req_in_ontology - req_in_shapes, key=str):
        problems.append(f"ContextRequirement declared in the ontology, but referenced by no shape (hlo:isShapeOfRequirement): {req}")

    return req_in_ontology


def check_requirement_of_symmetry(ontology, problems):
    for req, aspect in ontology.subject_objects(HLO.requirementOf):
        if (aspect, HLO.hasRequirement, req) not in ontology:
            problems.append(f"requirementOf without a symmetric hasRequirement: {req} -> {aspect}")
    for aspect, req in ontology.subject_objects(HLO.hasRequirement):
        if (req, HLO.requirementOf, aspect) not in ontology:
            problems.append(f"hasRequirement without a symmetric requirementOf: {aspect} -> {req}")


def _walk_path_nodes(graph, node, seen=None):
    """Return, recursively, every IRI occurring anywhere in an sh:path structure (RDF
    collections, sh:alternativePath/sh:zeroOrMorePath/sh:oneOrMorePath blank nodes)."""
    if seen is None:
        seen = set()
    if node in seen:
        return
    seen.add(node)

    if isinstance(node, Graph.__mro__[0]):  # never true, placeholder to keep linters quiet
        return

    from rdflib import URIRef, BNode

    if isinstance(node, URIRef):
        yield node
        return
    if not isinstance(node, BNode):
        return

    # RDF collection (sequence path)?
    if (node, RDF.first, None) in graph:
        for item in Collection(graph, node):
            yield from _walk_path_nodes(graph, item, seen)
        return

    for pred in (SH.alternativePath, SH.zeroOrMorePath, SH.oneOrMorePath, SH.zeroOrOnePath, SH.inversePath):
        for value in graph.objects(node, pred):
            yield from _walk_path_nodes(graph, value, seen)


def check_no_has_specialization_in_paths(shapes, problems):
    for _, path_node in shapes.subject_objects(SH.path):
        for iri in _walk_path_nodes(shapes, path_node):
            if iri == HLO.hasSpecialization:
                problems.append(f"hlo:hasSpecialization found in an sh:path (a path may only run upwards): start node {path_node}")


def _or_shapes_walked(shapes):
    """Every shape with an sh:or that helpers/context_links.py evaluates: reachable from a requirement's
    shape through the value shapes of its property shapes, sh:node and the members of sh:or/sh:and -
    never inside an sh:not, where conditions stand (a class alternative, for example)."""
    found, todo, seen = [], list(shapes.subjects(HLO.isShapeOfRequirement, None)), set()
    while todo:
        shape = todo.pop()
        if shape in seen:
            continue
        seen.add(shape)
        for property_shape in shapes.objects(shape, SH.property):
            todo += list(shapes.objects(property_shape, SH.qualifiedValueShape))
            todo += list(shapes.objects(property_shape, SH.node))
        todo += list(shapes.objects(shape, SH.node))
        for logic in (SH["or"], SH["and"]):
            for members in shapes.objects(shape, logic):
                todo += list(Collection(shapes, members))
                if logic == SH["or"]:
                    found.append((shape, members))
    return found


def check_or_exclusions_first(shapes, problems):
    for shape, members in _or_shapes_walked(shapes):
        kinds = [is_exclusion(shapes, branch) for branch in Collection(shapes, members)]
        name = shapes.qname(shape) if not isinstance(shape, BNode) else _owning_shape(shapes, shape)
        if not kinds or kinds[-1] or not kinds[0] or kinds != sorted(kinds, reverse=True):
            order = ", ".join("Ausschluss" if k else "Forderung" for k in kinds)
            problems.append(f"sh:or in {name}: first the exclusions, then the demands (rule 7.7), "
                            f"found: {order} (check 11)")


def _owning_shape(shapes, node, seen=None):
    """The named shape a blank node belongs to, for the message."""
    seen = seen or set()
    while isinstance(node, BNode) and node not in seen:
        seen.add(node)
        parents = list(shapes.subjects(None, node))
        if not parents:
            break
        node = parents[0]
    return shapes.qname(node) if not isinstance(node, BNode) else str(node)


def check_labels_and_descriptions(ontology, requirements, problems):
    for req in sorted(requirements, key=str):
        label = ontology.value(req, RDFS.label)
        if label is None:
            problems.append(f"Requirement without rdfs:label: {req}")

        descriptions = list(ontology.objects(req, SCHEMA.description))
        english = [d for d in descriptions if getattr(d, "language", None) == "en"]
        if not english:
            problems.append(f"Requirement without an English schema:description (xml:lang=\"en\"): {req}")


def check_id_pattern(requirements, problems):
    for req in sorted(requirements, key=str):
        local_name = str(req).rsplit("#", 1)[-1]
        if not ID_PATTERN.match(local_name):
            problems.append(f"ID does not follow the scheme <Level>_<Aspect(s)>_R<n>: {local_name}")


def check_property_shape_severity(shapes, problems):
    """Check only those sh:property constraints that hang DIRECTLY off a top-level shape -
    a shape assigned to a requirement through hlo:isShapeOfRequirement, i.e. a MainShape or
    ContextPathShape.

    sh:property blank nodes that sit as an alternative INSIDE sh:or/sh:not, or that belong to
    a helper shape referenced only through sh:qualifiedValueShape/sh:node (CoreShape,
    MemberShape), are deliberately NOT checked: they are never reported on their own with
    their own severity, and only count towards the conformance check of the construction
    enclosing them.
    """
    top_shapes = {shape for shape, _ in shapes.subject_objects(HLO.isShapeOfRequirement)}

    checked = set()
    for shape in top_shapes:
        for prop in shapes.objects(shape, SH.property):
            if prop in checked:
                continue
            checked.add(prop)
            severities = list(shapes.objects(prop, SH.severity))
            if not severities:
                problems.append(f"Property shape at {shapes.qname(shape)} without an sh:severity of its own (falls back to sh:Violation otherwise): {prop}")
            elif not any(s in (SH.Warning, SH.Info) for s in severities):
                problems.append(f"Property shape at {shapes.qname(shape)} with an unexpected sh:severity (neither Warning nor Info): {prop} -> {severities}")


def _repeated_alternatives(graph, node, found, seen=None):
    """Collect, recursively, the IRI set of every sh:zeroOrMorePath over an
    sh:alternativePath (or over a single IRI) inside an sh:path structure."""
    from rdflib import URIRef, BNode

    if seen is None:
        seen = set()
    if node in seen or not isinstance(node, BNode):
        return
    seen.add(node)

    if (node, RDF.first, None) in graph:
        for item in Collection(graph, node):
            _repeated_alternatives(graph, item, found, seen)
        return

    for inner in graph.objects(node, SH.zeroOrMorePath):
        if isinstance(inner, URIRef):
            found.append({inner})
            continue
        options = list(graph.objects(inner, SH.alternativePath))
        if options:
            found.append({o for o in Collection(graph, options[0]) if isinstance(o, URIRef)})
    for pred in (SH.alternativePath, SH.zeroOrMorePath, SH.oneOrMorePath, SH.zeroOrOnePath, SH.inversePath):
        for value in graph.objects(node, pred):
            _repeated_alternatives(graph, value, found, seen)


def _inverse_paths(graph, node, seen=None):
    """Yield every sh:inversePath node inside an sh:path structure."""
    from rdflib import BNode

    if seen is None:
        seen = set()
    if node in seen or not isinstance(node, BNode):
        return
    seen.add(node)
    if (node, SH.inversePath, None) in graph:
        yield node
    if (node, RDF.first, None) in graph:
        for item in Collection(graph, node):
            yield from _inverse_paths(graph, item, seen)
        return
    for pred in (SH.alternativePath, SH.zeroOrMorePath, SH.oneOrMorePath, SH.zeroOrOnePath, SH.inversePath):
        for value in graph.objects(node, pred):
            yield from _inverse_paths(graph, value, seen)


def check_context_path_shapes_vs_parent_properties(shapes, problems):
    expand = shapes.namespace_manager.expand_curie
    parents = {expand(name) for name in PARENT_PROPERTIES}
    children = {expand(name) for name in CHILD_PROPERTIES}
    field_chain = {expand("hlo:specializationOf")}
    # cpo:hasEnergyField is the terminal property (the target), not a climbing property.
    terminal = {expand("cpo:hasEnergyField")}

    for shape_name in CONTEXT_PATH_SHAPES:
        shape = HLO[shape_name]
        used, groups = set(), []
        for prop in shapes.objects(shape, SH.property):
            for path_node in shapes.objects(prop, SH.path):
                used |= set(_walk_path_nodes(shapes, path_node))
                _repeated_alternatives(shapes, path_node, groups)

        extra = used - parents - children - field_chain - terminal
        if extra:
            problems.append(f"{shape_name} uses properties that are neither in PARENT_PROPERTIES nor in CHILD_PROPERTIES: {sorted(shapes.qname(i) for i in extra)}")

        for wanted, name in ((parents, "PARENT_PROPERTIES"), (children, "CHILD_PROPERTIES")):
            if wanted not in groups:
                problems.append(f"{shape_name}: no repeated path exactly over {name} (list and path differ)")
        for prop in shapes.objects(shape, SH.property):
            for path_node in shapes.objects(prop, SH.path):
                if any(True for _ in _inverse_paths(shapes, path_node)):
                    problems.append(f"{shape_name}: sh:inversePath in the path - a way against the direction of a link can lead out of the own setup")
        location = {expand(name) for name in ("cpo:location", "cpo:locatedAt", "cpo:locatedInsideOf", "cpo:isRoomOf")}
        if children & location:
            problems.append(f"{shape_name}: CHILD_PROPERTIES contains a location link {sorted(shapes.qname(i) for i in children & location)} - the descent would then run into every device of the room")
        for group in groups:
            if group not in (parents, children, field_chain):
                problems.append(f"{shape_name}: repeated path over {sorted(shapes.qname(i) for i in group)} - neither exactly {{PARENT_PROPERTIES}} nor exactly {{CHILD_PROPERTIES}} nor the chain of the field (up and down mixed?)")


def check_info_collection_paths(shapes, problems):
    top_shapes = {shape for shape, _ in shapes.subject_objects(HLO.isShapeOfRequirement)}
    top_level_props = {prop for shape in top_shapes for prop in shapes.objects(shape, SH.property)}

    for prop in set(shapes.subjects(SH.severity, SH.Info)):
        if prop not in top_level_props:
            problems.append(f"sh:Info property shape does not hang directly at a requirement shape (e.g. inside sh:or, where it would always fulfil the requirement): {prop}")
        for count in (SH.minCount, SH.qualifiedMinCount):
            if (prop, count, None) in shapes:
                problems.append(f"sh:Info property shape with {shapes.qname(count)} - a collecting path must not ask for anything: {prop}")


def _path_text(graph, node):
    """An sh:path as text, for comparing a path with the one a rule prescribes."""
    from rdflib import URIRef
    if isinstance(node, URIRef):
        return graph.qname(node)
    if (node, RDF.first, None) in graph:
        return "(" + " ".join(_path_text(graph, item) for item in Collection(graph, node)) + ")"
    for pred, sign in ((SH.inversePath, "^"), (SH.zeroOrMorePath, "*"), (SH.oneOrMorePath, "+"), (SH.zeroOrOnePath, "?")):
        inner = graph.value(node, pred)
        if inner is not None:
            return f"{sign}{_path_text(graph, inner)}"
    alternatives = graph.value(node, SH.alternativePath)
    return "[" + "|".join(_path_text(graph, item) for item in Collection(graph, alternatives)) + "]"


def check_form_class_shapes(shapes, problems):
    """Check 9: per context object (cpo:Device, cpo:Phase) and form class the shapes ask for exactly the
    restrictions of the class. Every form shape starts from its context object (rule 7.11):
    sh:targetClass is the context object, a path leads to its forms, and per form a node shape of its own
    in the sh:or says "not this class" (for phases also "not defined by a phase or a material"),
    otherwise the demand (..._Demand). hlo:targetFormClass/hlo:targetFormDefinedBy name class
    and context object and have to fit."""
    cpo_graph = Graph()
    cpo_graph.parse(str(path_definitions.CPO_ONTOLOGY))
    CPO = Namespace("http://www.semanticweb.org/lf576/ontologies/2026/7/ChemicalProcessOntology#")
    # The path from the context object to its forms, and which classes the condition "not defined by ..."
    # must name: for devices none (the path leads only to their own forms - form and envelope form, and
    # every cavity, part and layer below them, however deep), for phases phase and material, because a
    # phase also fills the room form that the room air defines.
    form_paths = {
        CPO.Device: "([cpo:definesForm|cpo:hasEnvelopeForm] *[cpo:hasCavityForm|dcterms:hasPart|cpo:hasLayerForm])",
        CPO.Phase: "[cpo:definesForm|cpo:fillsForm]",
    }
    condition_classes = {CPO.Device: set(), CPO.Phase: {CPO.Phase, CPO.MaterialRepresentation}}

    def restricted(cls, seen=None):
        """Properties the class restricts, inherited ones included."""
        seen = seen or set()
        if cls in seen:
            return set()
        seen.add(cls)
        out = set()
        for parent in cpo_graph.objects(cls, RDFS.subClassOf):
            prop = cpo_graph.value(parent, OWL.onProperty)
            if prop is not None:
                out.add(prop)
            else:
                out |= restricted(parent, seen)
        return out

    def classes_in(node, seen=None):
        """Every sh:class below a node - through sh:property, sh:qualifiedValueShape, sh:not, sh:or."""
        seen = seen if seen is not None else set()
        if node in seen:
            return set()
        seen.add(node)
        found = set(shapes.objects(node, SH["class"]))
        for pred in (SH.property, SH.qualifiedValueShape, SH["not"]):
            for child in shapes.objects(node, pred):
                found |= classes_in(child, seen)
        for lst in shapes.objects(node, SH["or"]):
            for child in Collection(shapes, lst):
                found |= classes_in(child, seen)
        return found

    demanded = {}   # (context object, class) -> properties
    for shape in set(shapes.subjects(HLO.targetFormClass, None)):
        cls = shapes.value(shape, HLO.targetFormClass)
        definer = shapes.value(shape, HLO.targetFormDefinedBy)
        name = shapes.qname(shape)
        if definer not in form_paths:
            problems.append(f"{name}: hlo:targetFormDefinedBy {definer} is neither cpo:Device nor cpo:Phase")
            continue
        if shapes.value(shape, SH.targetClass) != definer:
            problems.append(f"{name}: sh:targetClass is not the context object of hlo:targetFormDefinedBy "
                            f"({shapes.qname(definer)}) - rule 7.11")
        demands = [ps for ps in shapes.objects(shape, SH.property) if shapes.value(ps, SH.severity) != SH.Info]
        # The phase form shapes exclude Fixed phases (rule 7.7): the property for the forms stands in
        # an sh:or after [ sh:class hlo:Fixed ].
        for lst in shapes.objects(shape, SH["or"]):
            demands += [ps for member in Collection(shapes, lst) for ps in shapes.objects(member, SH.property)]
        if len(demands) != 1:
            problems.append(f"{name}: expected exactly one property shape for the forms, found {len(demands)}")
            continue
        path_text = _path_text(shapes, shapes.value(demands[0], SH.path))
        if path_text != form_paths[definer]:
            problems.append(f"{name}: the path to the forms is {path_text}, expected {form_paths[definer]}")
        form_shape = shapes.value(demands[0], SH.node)
        branches = [b for lst in shapes.objects(form_shape, SH["or"]) for b in Collection(shapes, lst)] if form_shape else []
        class_exclusions, named = set(), set()
        for b in branches:
            for n in shapes.objects(b, SH["not"]):
                if (n, SH["class"], None) in shapes and (n, SH.property, None) not in shapes:
                    class_exclusions |= set(shapes.objects(n, SH["class"]))
                else:
                    named |= classes_in(n)
        if class_exclusions != {cls}:
            problems.append(f"{name}: the form shape excludes {sorted(shapes.qname(c) for c in class_exclusions)}, "
                            f"expected exactly {shapes.qname(cls)}")
        if named != condition_classes[definer]:
            problems.append(f"{name}: the condition in the sh:or names {sorted(shapes.qname(c) for c in named)}, "
                            f"expected for {shapes.qname(definer)}: {sorted(shapes.qname(c) for c in condition_classes[definer])}")
        props = demanded.setdefault((definer, cls), set())
        for b in branches:
            for node in shapes.objects(b, SH.node):
                for pr in shapes.objects(node, SH.property):
                    if (pr, SH.minCount, None) in shapes or (pr, SH.qualifiedMinCount, None) in shapes:
                        props.add(shapes.value(pr, SH.path))

    form_classes = set(cpo_graph.transitive_subjects(RDFS.subClassOf, CPO.Form)) - {CPO.Form}
    for definer in (CPO.Device, CPO.Phase):
        for cls in sorted(form_classes, key=str):
            wanted = restricted(cls)
            if definer == CPO.Phase and CPO.hasCavityForm in wanted:
                continue    # an own phase form is never hollow
            if definer == CPO.Phase and cls == CPO.LayerForm:
                continue    # a layer is set by the device, the layer phase only fills it (rule 3.8a)
            # The cavity of a hollow form is built by the generator and checked as data quality
            # (hlo:Cavity_*_Shape in DataQualityShapes.ttl), not by a context requirement.
            wanted = wanted - {CPO.hasCavityForm}
            if not wanted:
                continue
            got = demanded.get((definer, cls), set())
            label = f"{shapes.qname(cls)}, Kontext-Objekt {shapes.qname(definer)}"
            for prop in sorted(wanted - got, key=str):
                problems.append(f"{label}: the ontology asks for {shapes.qname(prop)}, no shape checks it")
            for prop in sorted(got - wanted, key=str):
                problems.append(f"{label}: a shape asks for {shapes.qname(prop)}, the class has no restriction for it")


def _kind_from_shapes(shapes, requirement):
    """The kind of a requirement as its shapes show it (rule 7.16), or a list of the kinds found when they mix."""
    found = set()
    for shape in shapes.subjects(HLO.isShapeOfRequirement, requirement):
        if any((shape, logic, None) in shapes for logic in (SH["or"], SH["and"], SH.node)):
            found.add(HLO.ExistenceRequirement)
        for prop in shapes.objects(shape, SH.property):
            if shapes.value(prop, SH.severity) == SH.Info:
                continue    # collecting path: belongs to every kind, decides nothing
            count = shapes.value(prop, SH.qualifiedMinCount)
            if count is not None and int(count) == 0:
                found.add(HLO.AssignmentRequirement)
            else:
                found.add(HLO.ExistenceRequirement)
    if not found:
        return HLO.SurroundingsRequirement
    return found.pop() if len(found) == 1 else sorted(found)


def check_requirement_kinds(ontology, shapes, requirements, problems):
    """Check 12: every requirement has exactly one of the three kinds, and it fits its shapes."""
    # The kind stands in the HLO so that it can be read without the shapes; it is not copied by
    # hand without a check (rule 7.6), hence the comparison with what the shape does.
    def local(iri):
        return str(iri).rsplit("#", 1)[-1]

    for req in sorted(requirements, key=str):
        declared = [cls for cls in REQUIREMENT_KINDS if (req, RDF.type, cls) in ontology]
        if len(declared) != 1:
            problems.append(f"{local(req)}: expected exactly one kind (Existence/Surroundings/AssignmentRequirement), "
                            f"given {[local(c) for c in declared]} (check 12)")
            continue
        from_shapes = _kind_from_shapes(shapes, req)
        if isinstance(from_shapes, list):
            problems.append(f"{local(req)}: the shapes mix {[local(c) for c in from_shapes]} - a "
                            f"requirement has exactly one kind (rule 7.16, check 12)")
        elif from_shapes != declared[0]:
            problems.append(f"{local(req)}: given {local(declared[0])}, the shapes show "
                            f"{local(from_shapes)} (check 12)")


def check_quantity_kind_shapes_up_to_date(problems):
    """Check 10: shapes/QuantityKindShapes.ttl and shapes/FunctionShapes.ttl are what their
    generators would write from the current CPO."""
    # The file is generated, not maintained - if it is out of date, SHACL silently checks against
    # old quantity kinds, without any message pointing to it.
    message = out_of_date_message()
    if message:
        problems.append(message)
    # Likewise shapes/FunctionShapes.ttl against cpo:offersFunction (rule 4.9).
    message = functions_out_of_date_message()
    if message:
        problems.append(message)


def main():
    ontology, shapes = load_graphs()
    problems = []

    requirements = check_requirements_both_ways(ontology, shapes, problems)
    check_requirement_of_symmetry(ontology, problems)
    check_no_has_specialization_in_paths(shapes, problems)
    check_or_exclusions_first(shapes, problems)
    check_labels_and_descriptions(ontology, requirements, problems)
    check_id_pattern(requirements, problems)
    check_property_shape_severity(shapes, problems)
    check_context_path_shapes_vs_parent_properties(shapes, problems)
    check_info_collection_paths(shapes, problems)
    check_form_class_shapes(shapes, problems)
    check_quantity_kind_shapes_up_to_date(problems)
    check_requirement_kinds(ontology, shapes, requirements, problems)

    print("=== ContextRequirement consistency check ===")
    print(f"Requirements in total: {len(requirements)}")
    print(f"\nProblems ({len(problems)}):")
    for problem in problems:
        print(f"  - {problem}")
    if not problems:
        print("  none")

    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
