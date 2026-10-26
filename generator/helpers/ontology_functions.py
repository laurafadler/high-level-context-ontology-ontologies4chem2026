"""
Defines all the function related to working with ontologies
"""

import path_definitions

from pathlib import Path

try:
    from rdflib import Graph, RDF, RDFS, OWL, URIRef, Literal
except ImportError:
    Graph = None


# Load an ontology and keep it as an rdf graph

def load_ontology(path: Path):
    """Load the ontology as an rdflib.Graph, or None if something goes wrong."""

    # If the Graph function is not available because rdflib is not installed
    if Graph is None:
        print("Note: rdflib is not installed (pip install rdflib). "
              "The ontology checks are skipped.")
        return None

    # If the given path to the ontology file does not exist
    if not path.exists():
        print(f"Note: ontology file '{path}' not found.")
        return None

    graph = Graph()
    graph.parse(path)

    # Because the default namespaces are not recognized with a prefix
    graph.bind(
        "hlo",
        "http://www.semanticweb.org/lf576/ontologies/2026/7/HigherLevelOntology#"
    )

    graph.bind(
        "cpo",
        "http://www.semanticweb.org/lf576/ontologies/2026/7/ChemicalProcessOntology#"
    )

    # rdflib brings its own defaults for common prefixes, and they win against what the
    # ontology file declares itself: if the prefix is taken already, rdflib gives the
    # namespace of the document a substitute name ("schema1"). The code then looks under
    # "schema" and ends up somewhere else - check_existence/check_type fail for every ID
    # under this prefix.
    #
    # rdflib 7.6.0 binds "schema" to https://schema.org/. The project uses
    # http throughout (see libraries/project_context.jsonld): the RO-Crate 1.3 specification
    # explicitly asks for it ("make sure any referenced @id to schema.org terms starts with
    # http:// rather than https://"), and the official JSON-LD context of schema.org binds to
    # http itself. Without this line the run fails at once with "Property or class could not
    # be found: schema:description".
    #
    # ONLY schema: needs this. "org" follows the spelling of the W3C specification (http), which
    # is rdflib's default.
    graph.bind("schema", "http://schema.org/", override=True, replace=True)


    return graph


def _local_name(uri) -> str:
    # returns only the name (i.e. the last part of a URI)
    text = str(uri)
    if "#" in text:
        return text.split("#")[-1]
    return text.rstrip("/").split("/")[-1]


def get_types(graph, uri) -> list[str]:
    """Return the local names of all rdf:type classes of an IRI (of an individual)."""

    # If no graph is passed:
    if graph is None:
        return []

    # Convert the given uri into a uri_ref
    uri_ref = uri if isinstance(uri, URIRef) else URIRef(uri)

    # Return all local names of the types of the individual looked for
    return [_local_name(t) for t in graph.objects(uri_ref, RDF.type)]


def add_namespaces(namespace_collection, ontology):

    current_namespaces = dict(ontology.namespaces())

    for prefix, namespace in current_namespaces.items():

        if prefix not in namespace_collection:
            namespace_collection[prefix] = {
                "namespace": str(namespace),
                "graphs": []
            }

        if ontology not in namespace_collection[prefix]["graphs"]:
            namespace_collection[prefix]["graphs"].append(ontology)

    return


def initialize_ontologies():

    # load all ontology graphs
    hlo_graph = load_ontology(path_definitions.HLO_ONTOLOGY)
    cpo_graph = load_ontology(path_definitions.CPO_ONTOLOGY)


    # make a list of all ontology graphs
    ontology_list = [
        hlo_graph,
        cpo_graph
    ]

    # Create namespace collection
    namespace_collection = {}


    # Go through every ontology and add its namespaces to the list
    for o in ontology_list:
        add_namespaces(namespace_collection, o)

    return namespace_collection


def check_existence(compact_id: str, namespace_collection: dict, looked_for: str):
    full_id = extend_id(compact_id, namespace_collection)
    uri = URIRef(full_id)

    # search the graphs in which the prefix occurs
    prefix = get_prefix(compact_id)

    # give me the list of the potential graphs in which this prefix is used

    potential_graphs = namespace_collection[prefix]["graphs"]


    for graph in potential_graphs:
        if looked_for == "class":
            if (
                    (uri, RDF.type, OWL.Class) in graph
                    or (uri, RDF.type, RDFS.Class) in graph
                    # If the URI is used by any device as a class
                    or (None, RDF.type, uri) in graph
            ):
                return True


        elif looked_for == "property":
            if (
                    (uri, RDF.type, OWL.ObjectProperty) in graph
                    or (uri, RDF.type, OWL.DatatypeProperty) in graph
                    or (uri, RDF.type, RDF.Property) in graph
                    # If at least one triple uses the property as its predicate
                    or next(graph.triples((None, uri, None)), None) is not None
            ):
                return True

        else:
            raise ValueError(
                f"Invalid lookup type: {looked_for}. "
                f"Expected 'property' or 'class'."
            )

    else:

        raise ValueError(f"Property or class could not be found: {compact_id}. Check for spelling errors")


def extend_id(compact_id: str, namespace_collection: dict):
    # If we enter a full id already:
    if compact_id.startswith("http://") or compact_id.startswith("https://"):
            return compact_id


    # If we have a real compact id:
    if ":" in compact_id:

        prefix, local = compact_id.split(":", 1)
        if prefix in namespace_collection:
            namespace = namespace_collection[prefix]["namespace"]
            full_id = f"{namespace}{local}"
            return full_id
    print(f"Extend ID did not work. This is the current namespace_collection: {namespace_collection}")
    raise ValueError(f"Invalid ID format: {compact_id}. Prefix {prefix} might be unknown.")


def shorten_id(full_id, namespace_collection: dict):

    # First convert the URIRef into a string
    if isinstance(full_id, URIRef):
        full_id = str(full_id)

    # In case there is a compact ID already
    if ":" in full_id and not full_id.startswith(("http://", "https://")):
        return full_id

    # In case it is a complete URI
    if full_id.startswith(("http://", "https://")):


        # Go through all namespaces and look for a match
        for prefix, data in namespace_collection.items():


            if full_id.startswith(data["namespace"]):
                local = full_id[len(data["namespace"]):]
                return f"{prefix}:{local}"

        # No matching namespace found
        return full_id

    return full_id


# Results of find_individuals_of_class for the duration of a run. The loaded ontologies do
# not change during a run, but the query runs over all triples of the graphs concerned -
# and every choice question calls it again.
_individuals_cache = {}


def find_individuals_of_class(class_id: str, namespace_collection: dict, include_subclasses: bool = False) -> list:
    """All individuals of a class, as compact IDs, sorted alphabetically.

    Meant to replace the choice lists that used to sit in the generator
    (EVIDENCE_TYPES, SORPTION_TYPES, TRANSFER_TYPES, ...). Such lists are ontology
    knowledge: whoever adds an individual there wants it offered straight away and should
    not have to add it in a second place in the code. That is exactly how hlo:ReferenceType
    drifted apart - hlo:Literature existed in the ontology but could not be chosen for
    months.

    include_subclasses=True also picks up the individuals of the subclasses. Needed for
    cpo:TransferType: cpo:PhaseTransition is a subclass of it, so melting and friends hang
    off the subclass but belong in the same list.

    As in check_existence and find_entity_in_ontology, only the graphs in which the class
    prefix occurs are searched. Classes that appear as an rdf:type themselves (OWL punning)
    are filtered out: what is wanted here are individuals, not subclasses. So are deprecated
    individuals (owl:deprecated true, e.g. cpo:Solvent): they stay in the ontology so that
    older crates remain readable, but they are not offered.
    """
    cache_key = (class_id, include_subclasses)
    if cache_key in _individuals_cache:
        return list(_individuals_cache[cache_key])

    class_ids = []
    if include_subclasses:
        get_all_subclasses(class_id, namespace_collection, class_ids)
    else:
        class_ids = [class_id]

    found = set()
    for current in class_ids:
        prefix = get_prefix(current)
        if prefix not in namespace_collection:
            continue
        uri = URIRef(extend_id(current, namespace_collection))
        for graph in namespace_collection[prefix]["graphs"]:
            for subject in graph.subjects(RDF.type, uri):
                if (subject, RDF.type, OWL.Class) in graph:
                    continue
                if any(str(value).lower() == "true" for value in graph.objects(subject, OWL.deprecated)):
                    continue
                found.add(shorten_id(str(subject), namespace_collection))

    result = sorted(found)
    _individuals_cache[cache_key] = result
    return list(result)


# Results of find_subclasses for the duration of a run, for the same reason as
# _individuals_cache. Without the cache most of the run time (666 of 700 seconds, measured on the
# hydrogenation crate) went into get_all_subclasses - _is_task (creation/task_functions.py) asks task_types for
# every type of every entity, about 1.1 million times, and each time the hierarchy ran
# through the graphs anew.
_subclasses_cache = {}


def find_subclasses(root_class: str, namespace_collection: dict, include_root: bool = True, exclude: tuple = ()) -> list:
    """The subclasses of a class as compact IDs, sorted alphabetically.

    The counterpart of find_individuals_of_class for choice lists whose entries are
    CLASSES (cpo:File/Image/Video, the task classes). A thin wrapper around
    get_all_subclasses that also sorts and allows filtering.

    include_root=False leaves the root itself out - for schema:MediaObject, say, which only
    groups and is never instantiated directly. For cpo:Task the root is a valid choice ("a
    task that is none of the more specific kinds") and stays in.

    exclude removes pure grouping classes that are neither root nor leaf. They have to be
    named explicitly, unfortunately: OWL has no notion of "abstract", and from the hierarchy
    alone cpo:DeterminationTask (only groups) cannot be told apart from cpo:Task (groups AND
    is selectable).
    """
    cache_key = (root_class, include_root, tuple(exclude))
    if cache_key in _subclasses_cache:
        return list(_subclasses_cache[cache_key])
    subclasses = []
    get_all_subclasses(root_class, namespace_collection, subclasses)
    dropped = set(exclude) | (set() if include_root else {root_class})
    result = sorted(c for c in subclasses if c not in dropped)
    _subclasses_cache[cache_key] = result
    return list(result)


def find_superclasses(class_id: str, namespace_collection: dict) -> list:
    """The direct superclasses of a class as compact IDs.

    The counterpart of get_all_subclasses, used where a property is declared once high up in
    the hierarchy and inherited downwards - cpo:offersFunction on cpo:Task, for instance
    (see creation/task_functions.py: offered_functions). Only NAMED superclasses are
    returned; an anonymous rdfs:subClassOf (a restriction) carries no ID to follow.
    """
    prefix = get_prefix(class_id)
    if prefix not in namespace_collection:
        return []

    uri = URIRef(extend_id(class_id, namespace_collection))
    superclasses = []
    for graph in namespace_collection[prefix]["graphs"]:
        for parent_uri in graph.objects(uri, RDFS.subClassOf):
            if not isinstance(parent_uri, URIRef):
                # Anonymous restriction - has no ID that could be followed.
                continue
            parent_id = shorten_id(parent_uri, namespace_collection)
            if parent_id not in superclasses:
                superclasses.append(parent_id)
    return superclasses


def find_entity_in_ontology(compact_id, namespace_collection):
    full_id = extend_id(compact_id, namespace_collection)
    uri = URIRef(full_id)

    # search the graphs in which the prefix occurs
    prefix = get_prefix(compact_id)
    if prefix not in namespace_collection:
        return None

    # give me the list of the potential graphs in which this prefix is used

    potential_graphs = namespace_collection[prefix]["graphs"]

    # Merge ALL graphs, do not take the first one the URI occurs in.
    # An entity can be described across several files: cpo:Task stands with 40 triples in the
    # Chemical Process Ontology and with 2 in the Higher Level Ontology (there only as a range).
    # Whoever takes the first hit gets, depending on the loading order, the two-triple version
    # and never sees the actual declaration (cpo:offersFunction at cpo:Task, for instance).

    entity = {"@id": str(uri)}
    types = []
    found = False

    for graph in potential_graphs:
        if next(graph.triples((uri, None, None)), None) is None:
            continue
        found = True

        for graph_type in get_types(graph, uri):
            if graph_type not in types:
                types.append(graph_type)

        for predicate, obj in graph.predicate_objects(uri):
            if predicate == RDF.type:
                continue

            key = _local_name(predicate)
            value = str(obj) if isinstance(obj, Literal) else {"@id": str(obj)}

            if key not in entity:
                entity[key] = value
            elif isinstance(entity[key], list):
                if value not in entity[key]:
                    entity[key].append(value)
            elif entity[key] != value:
                entity[key] = [entity[key], value]

    if not found:
        return None
    if types:
        # Sorted by @id as before: @type stands right after the ID.
        entity = {"@id": entity.pop("@id"), "@type": types, **entity}
    return entity


_REQUIRED_PROPERTIES_OF_CLASS = {}


def required_properties_of_class(class_id: str, namespace_collection: dict) -> list:
    """The properties a class requires through its restrictions in the ontology
    (owl:Restriction with owl:onProperty and owl:someValuesFrom), inherited ones included, as
    [(property, value class)] in compact form - e.g. for cpo:CupForm
    [("cpo:hasInnerDiameter", "cpo:ProcessVariable"), ..., ("cpo:hasCavityForm", "cpo:SolidCylinderForm")].

    What a form of a class needs is stated there once; the
    form builder (helpers/forms.py: build_form) and the shapes read the same statement.
    """
    if class_id in _REQUIRED_PROPERTIES_OF_CLASS:
        return list(_REQUIRED_PROPERTIES_OF_CLASS[class_id])
    prefix = get_prefix(class_id)
    graphs = namespace_collection.get(prefix, {}).get("graphs", [])
    found, level, seen = [], [URIRef(extend_id(class_id, namespace_collection))], set()
    while level:
        next_level = []
        for uri in level:
            if uri in seen:
                continue
            seen.add(uri)
            for graph in graphs:
                for parent in graph.objects(uri, RDFS.subClassOf):
                    prop = graph.value(parent, OWL.onProperty)
                    if prop is None:
                        if isinstance(parent, URIRef):
                            next_level.append(parent)
                        continue
                    target = graph.value(parent, OWL.someValuesFrom)
                    entry = (shorten_id(prop, namespace_collection), shorten_id(target, namespace_collection) if target is not None else None)
                    if entry not in found:
                        found.append(entry)
        level = next_level
    _REQUIRED_PROPERTIES_OF_CLASS[class_id] = found
    return list(found)


def cavity_counterpart(property_name: str, namespace_collection: dict):
    """The property under which the cavity of a hollow form carries the same Actual
    (cpo:cavityCounterpart on the property, e.g. cpo:hasInnerDiameter -> cpo:hasDiameter), or
    None."""
    info = find_entity_in_ontology(property_name, namespace_collection) or {}
    value = info.get("cavityCounterpart")
    value = value[0] if isinstance(value, list) else value
    return shorten_id(value["@id"], namespace_collection) if isinstance(value, dict) else None


_QUANTITY_KINDS_OF_PROPERTY = {}


def quantity_kinds_of_property(property_name: str, namespace_collection: dict) -> list:
    """The quantity kinds the values of this property may have, as stated in the ontology
    through cpo:valueHasQuantityKind (compact, e.g. ["quantitykind:Temperature"]), sorted;
    [] when the property states none.

    One kind: every value has it. Several: the allowed ones, one of which each value has (a
    flow rate may be a volume, molar or mass flow rate) - chosen per value.

    Follows rdfs:subPropertyOf upwards: cpo:hasInnerHeight carries no annotation of its own
    and gets quantitykind:Height from cpo:hasHeight. The nearest annotation wins.
    """
    if property_name in _QUANTITY_KINDS_OF_PROPERTY:
        return list(_QUANTITY_KINDS_OF_PROPERTY[property_name])

    def _ids(value):
        values = value if isinstance(value, list) else [value] if value else []
        return [shorten_id(v["@id"], namespace_collection) for v in values if isinstance(v, dict) and "@id" in v]

    # Breadth-first search upwards: the nearest annotation wins, and a subproperty with an
    # annotation of its own covers that of the superproperty.
    kinds, level, seen = [], [property_name], set()
    while level and not kinds:
        next_level = []
        for current in level:
            if current in seen:
                continue
            seen.add(current)
            info = find_entity_in_ontology(current, namespace_collection) or {}
            kinds = sorted(_ids(info.get("valueHasQuantityKind")))
            if kinds:
                break
            next_level.extend(_ids(info.get("subPropertyOf")))
        level = next_level

    _QUANTITY_KINDS_OF_PROPERTY[property_name] = kinds
    return list(kinds)


def quantity_kind_of_property(property_name: str, namespace_collection: dict):
    """The one quantity kind of this property, or None when the ontology states none. For a
    property with several allowed kinds this is an error - the caller has to choose."""
    kinds = quantity_kinds_of_property(property_name, namespace_collection)
    if len(kinds) > 1:
        raise ValueError(f"{property_name} allows several quantity kinds ({', '.join(kinds)}) - choose one.")
    return kinds[0] if kinds else None


def get_all_subclasses(entity_type: str, namespace_collection: dict, subclass_list: list):
    if entity_type not in subclass_list:
        subclass_list.append(entity_type)

    uri = URIRef(extend_id(entity_type, namespace_collection))

    # look in which graphs the prefix of the class occurs and then search only those graphs

    # search the graphs in which the prefix occurs
    prefix = get_prefix(entity_type)

     # Check whether the prefix is known at all
    if prefix not in namespace_collection:
        return subclass_list

    # give me the list of the potential graphs in which this prefix is used

    potential_graphs = namespace_collection[prefix]["graphs"]


    for graph in potential_graphs:


        # If the uri corresponds to a class definition
        if (
                (uri, RDF.type, OWL.Class) in graph
                or (uri, RDF.type, RDFS.Class) in graph

        ):
            # check whether it has subclasses
            # Find all direct subclasses of this class
            for subclass_uri in graph.subjects(
                RDFS.subClassOf,
                uri
            ):
                # return the id of this subclass/write it into our collecting list
                subclass_id = shorten_id(subclass_uri, namespace_collection)

                # Only add if not present yet
                if subclass_id not in subclass_list:
                    subclass_list.append(subclass_id)

                # if yes, check again whether the subclass has further subclasses, and go down until no more subclasses are found
                # Search for further subclasses recursively
                deeper_subclasses = get_all_subclasses(subclass_id, namespace_collection, subclass_list)

                # Add the results
                for deeper_subclass in deeper_subclasses:
                    if deeper_subclass not in subclass_list:
                        subclass_list.append(deeper_subclass)

    return subclass_list


def get_prefix(string: str):
    result = string.split(":", 1)[0]
    return result
