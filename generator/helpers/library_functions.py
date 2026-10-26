"""
Defining all the definitions needed to work with the libraries
"""

import path_definitions
from helpers.entities import find_entity, add_entity, find_entities_by_type, as_list, ref_ids
from helpers.file_handling import load_jsonld
from helpers.user_io import ask_user


def load_device_libraries() -> tuple:
    """The device library and the material library (rule 2.15) as one library to read the devices
    and their contents from - a device of the one names its content in the other (cpo:containsMaterial,
    cpo:hasContainedMaterialHistory). The view holds the very entity
    dicts of both files, so a change made through it lands in the file its entity comes from.
    Returns (view, {path: document}); whoever writes saves each document to its path."""
    documents = {path: load_jsonld(path) for path in path_definitions.DEVICE_LIBRARY_PATHS}
    view = {"@context": documents[path_definitions.DEVICE_LIBRARY_PATH].get("@context", {}),
            "@graph": [entity for document in documents.values() for entity in document.get("@graph", [])]}
    return view, documents







def get_id_list(library: dict, prefix: str = None, entity_type: str = None):
    """The IDs of a library (without the prefix, if one is given); with entity_type only the
    entities that carry that type themselves (no subclasses)."""
    id_list = []

    for entity in library.get("@graph", []):
        entity_id = entity.get("@id", "")
        if entity_type is not None and entity_type not in as_list(entity.get("@type")):
            continue

        if prefix is not None:
            if entity_id.startswith(prefix):
                entity_name = entity_id.removeprefix(prefix)
                id_list.append(entity_name)
        else:
            id_list.append(entity_id)

    return id_list








# Properties through which copy_library_subtree copies further part entities recursively -
# besides the plain hierarchy of parts (hasPart) also everything that a Fixed value stored by
# hand in a library (e.g. a volume of an environment or device material phase, or the
# lastAccessDate/ontologyFile of an ontology entry - see
# creation/ontology_snapshot_functions.py) needs in further entities to be resolvable in the
# crate (the ProcessVariable/time instant/file itself and its evidence/reference entity).
# cpo:hasDeterminationTask belongs to it because the library values have tasks (rule 4.1): a
# value copied into the crate brings its reason along, otherwise the crate holds a reference
# to a task that does not exist there. dcterms:isPartOf pulls the collective task along,
# cpo:hasInputValue the values it was calculated from - without them the calculation could
# not be traced in the crate.
# cpo:hasStartTime, cpo:hasEndTime and cpo:hasDuration: without them a task copied into the crate
# points at a time entity that does not exist there - the same case as cpo:hasDeterminationTask
# (every task carries all three times, rule 4.6). The time entities of the HISTORY OF A DEVICE
# (cpo:lastUsedTime and siblings) do not get into the crate through this, but through
# creation/device_functions.py; they are therefore deliberately not in this list.
LIBRARY_SUBTREE_PROPS = ("dcterms:hasPart", "dcterms:isPartOf", "cpo:hasVolume", "cpo:hasMass",
                         "cpo:hasDensity", "cpo:hasConcentration",
                         "hlo:hasEvidence", "hlo:hasReference",
                         "cpo:hasDeterminationTask", "cpo:hasInputValue",
                         "cpo:hasStartTime", "cpo:hasEndTime", "cpo:hasDuration",
                         "cpo:ontologyFile", "cpo:lastAccessDate")


def copy_library_subtree(entity_id: str, library: dict, datagraph: dict, visited: set = None):
    """Copy a Fixed entity and every part reachable through LIBRARY_SUBTREE_PROPS into the
    crate - only for what has to record the state at the time of creation (the ontology
    snapshot, creation/ontology_snapshot_functions.py). Everything else in a library is
    linked, not copied, and read through helpers/entities.py: resolve.
    """
    if visited is None:
        visited = set()
    if entity_id in visited:
        return
    visited.add(entity_id)

    entity = find_entity(library, entity_id) or find_entity(datagraph, entity_id)
    if entity is None:
        return

    add_entity(datagraph, entity)

    for prop in LIBRARY_SUBTREE_PROPS:
        for part_id in ref_ids(entity.get(prop)):
            copy_library_subtree(part_id, library, datagraph, visited)


def find_library_item(library: dict, prefix: str, question: str, *, question_id: str, entity_type: str = None, namespace_collection: dict = None):
    """Let the user pick an entry from a library.

    question_id is MANDATORY (see helpers/user_io.py) and is assigned by each caller
    separately, because find_library_item is called from many places with different
    prompts (creator, experimenter, device selection, ...).

    entity_type (optional, only effective together with namespace_collection) narrows
    the choice to entities of that type including its subclasses. Without the filter
    everything carrying the prefix is offered - in the device library that means, next
    to the six devices, also their forms, masses, timestamps and evidence entities
    (device:vessel001_Form, device:vessel001_InnerVolume_Reference_1, ...), well over a
    hundred entries in which the actual devices are lost. Without namespace_collection,
    entity_type is compared with the entity's own types (the people library: only
    schema:Person, not an identifier that happens to carry the prefix).
    """

    if entity_type and namespace_collection:
        candidates = find_entities_by_type(library, entity_type, namespace_collection, include_subclasses=True)
        existing_items = [e["@id"].removeprefix(prefix) for e in candidates if e.get("@id", "").startswith(prefix)]
    else:
        existing_items = get_id_list(library, prefix, entity_type)
    answer = ask_user(question, existing_items, question_id=question_id)
    item_id = f"{prefix}{answer}"
    item = find_entity(library, item_id)

    return item







