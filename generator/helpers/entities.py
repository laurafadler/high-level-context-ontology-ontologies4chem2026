"""Central helpers for working with entities in a JSON-LD graph.

Holds the primitives that nearly every other module needs: normalising
JSON-LD property values (:func:`ref_id`, :func:`as_list`, :func:`ref_ids`),
finding and adding entities, and walking the hlo:specializationOf chain.
"""

import os
import re
import logging

from helpers.ontology_functions import get_all_subclasses
from helpers.user_io import ask_user, ask_user_list
from helpers.identifiers import get_display_label

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Collecting namespace prefixes
# ---------------------------------------------------------------------------
# A CURIE is "prefix:local" - the prefix in front, behind it a rest without spaces
# and without quotes. A "#fragment", a "./" and an absolute IRI have no prefix and
# thus drop out by themselves.
_CURIE = re.compile(r"^([A-Za-z][A-Za-z0-9_]*):[^\s\"]+$")

# Schemes that look like a prefix but are none.
_NOT_A_PREFIX = {"http", "https", "urn", "mailto", "file"}


def collect_prefixes(node, found: set = None) -> set:
    """Every namespace prefix a JSON-LD structure uses - as a property name, as an @type,
    or as the @id it points at - at any nesting depth.

    All three positions have to be walked, because they carry different vocabularies:
    "cpo" turns up as a property name, "chebi" as a type, and "unit"/"quantitykind"
    ONLY ever as the @id of a value. Reading property names and types alone therefore
    leaves the QUDT vocabularies invisible (see creation/ontology_snapshot_functions.py).

    Typed literals ({"@value": ..., "@type": "xsd:decimal"}) are walked like anything
    else; their "xsd" is a real prefix and the caller decides whether to keep it.
    """
    if found is None:
        found = set()

    if isinstance(node, list):
        for item in node:
            collect_prefixes(item, found)
        return found

    if not isinstance(node, dict):
        return found

    for key, value in node.items():
        if not key.startswith("@"):
            _note_prefix(key, found)
        if key in ("@id", "@type"):
            for item in (value if isinstance(value, list) else [value]):
                _note_prefix(item, found)
        collect_prefixes(value, found)

    return found


def _note_prefix(text, found: set) -> None:
    """Add the prefix of text to found, if text is a CURIE and not an absolute IRI."""
    match = _CURIE.match(text) if isinstance(text, str) else None
    if match and match.group(1) not in _NOT_A_PREFIX:
        found.add(match.group(1))


# ---------------------------------------------------------------------------
# Normalizing JSON-LD property values
# ---------------------------------------------------------------------------
# A property value can occur in the crate in three forms: as a reference dict
# {"@id": ...}, as a bare ID string, or - for multi-valued properties - as a list
# of both. Whoever wants to evaluate the value has to resolve that each time.
# These three functions are therefore the only place where that happens.


def ref_id(value):
    """The @id of a property value that may be an {"@id": ...} dict or a plain string."""
    return value.get("@id") if isinstance(value, dict) else value


def as_list(value) -> list:
    """Normalise a property value (missing / single / list) into a list."""
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def ref_ids(value) -> list:
    """Like :func:`ref_id`, but for single- or multi-valued properties.

    Empty entries are dropped, so the result holds real IDs only.
    """
    return [ref_id(v) for v in as_list(value) if v]


def ask_entity_choice(prompt: str, entities: list, extra_options: list = None, label_fn=get_display_label, *, question_id):
    """Ask the user to pick one entity out of `entities`.

    Shows label_fn(entity) as the option (default: get_display_label, i.e. the name
    rather than the raw @id) but returns the @id of the chosen entity.

    extra_options are additional, non-entity options (for example "None of these -
    try again"); they are appended unchanged and returned unchanged when picked.

    question_id is MANDATORY (see helpers/user_io.py) and is assigned by each caller
    separately, because ask_entity_choice is called from many places with different
    prompts.
    """
    labels = [label_fn(e) for e in entities]
    answer = ask_user(prompt, labels + list(extra_options or []), question_id=question_id)
    for entity, label in zip(entities, labels):
        if label == answer:
            return entity["@id"]
    return answer


def ask_entity_list(prompt: str, entities: list, label_fn=get_display_label, *, question_id, required=False) -> list:
    """Like ask_entity_choice, but several at once as one list (helpers/user_io.py:
    ask_user_list). Returns the @ids of the chosen entities."""
    labels = [label_fn(e) for e in entities]
    chosen = ask_user_list(prompt, labels, question_id=question_id, required=required)
    by_label = {label: entity["@id"] for entity, label in zip(entities, labels)}
    return [by_label[label] for label in chosen]


def add_entity(datagraph: dict, entity: dict) -> bool:
    """Append an entity to the crate's @graph if its @id isn't already present.

    Returns True if the entity was added, False if an entity with the same
    @id already existed (and nothing was changed).
    """
    graph = datagraph.setdefault("@graph", [])
    existing_ids = {e["@id"] for e in graph}
    if entity["@id"] in existing_ids:
        logger.debug("Entity with @id %s already exists, skipping.", entity["@id"])
        return False
    graph.append(entity)

    # Optional: write to the output file right after every entity, so that the state of the
    # graph can be read along live (e.g. in VS Code with auto-reload).
    # OFF BY DEFAULT. That was a crutch from the time when a run never got to the end and one
    # would otherwise have seen nothing at all - since main.py runs through reliably and
    # saves at the end, it is only expensive: a complete dump of the crate, by now over 1 MB,
    # per entity, i.e. with over 2000 entities over 2000 times per run. In the OneDrive folder,
    # in addition, the sync service went at the file in between and the run stopped with
    # "OSError: [Errno 22]" (save_jsonld therefore writes atomically by now and retries
    # briefly, see there).
    #
    # To switch it on again: set LIVE_CRATE=1 in the environment.
    #
    # Local import, because file_handling.py itself imports from entities.py
    # (avoiding a cycle).
    if os.environ.get("LIVE_CRATE", "").strip().lower() not in ("", "0", "false"):
        from helpers.file_handling import save_jsonld
        import path_definitions
        from helpers.identifiers import current_crate_identifier
        save_jsonld(datagraph, path_definitions.crate_path(current_crate_identifier() or "unnamed"))

    return True


def resolve_inherited(entity: dict, property_name: str, *graphs):
    """Return the value of property_name on `entity`, or, when it is missing there,
    the value of the next entity up the hlo:specializationOf chain
    (experiment -> series -> fixed).

    The project deliberately records a value only once, and as far up the chain as
    possible: what already sits in a library (the partial orders from the publication,
    the stoichiometric coefficient of a fixed reaction) is NOT repeated further down.
    Whoever needs the value walks up. Phase_Structure_R1 makes the same move in SHACL
    with [sh:zeroOrMorePath hlo:specializationOf].

    "graphs" are the places to search - the datagraph first, then the libraries: a fixed
    ReactionParticipant lives in the reaction library, which is never copied into the
    crate, and so would not be reachable through the datagraph alone.
    """
    seen = set()
    current = entity
    while current is not None and current.get("@id") not in seen:
        seen.add(current.get("@id"))
        if property_name in current:
            return current[property_name]
        parent_ref = current.get("hlo:specializationOf")
        if isinstance(parent_ref, list):
            parent_ref = parent_ref[0] if parent_ref else None
        parent_id = parent_ref.get("@id") if isinstance(parent_ref, dict) else parent_ref
        if not parent_id:
            return None
        current = next((found for g in graphs if g is not None and (found := find_entity(g, parent_id)) is not None), None)
    return None


def inherited_value(entity: dict, property_name: str, datagraph: dict):
    """As resolve_inherited, but every step up goes through resolve - the datagraph, then the registered
    libraries - so that a Fixed entry at the top of the chain is reached without naming its library. For the
    literals and terms that stand only once, where they are first said (rule 3.6)."""
    seen = set()
    current = entity
    while current is not None and current.get("@id") not in seen:
        seen.add(current.get("@id"))
        if property_name in current:
            return current[property_name]
        parents = as_list(current.get("hlo:specializationOf"))
        current = resolve(datagraph, ref_id(parents[0])) if parents else None
    return None


# Libraries a run resolves against. A crate links library entries, it does not copy them
# (rule 2.1); what the run has to read of them (body material of a device, room air, their
# values, the Fixed entry at the end of a specializationOf chain) it fetches explicitly with
# resolve. find_entity searches only in the graph it is given. The register replaces the
# former library view at the datagraph, which found only what had been "seeded" before.
#
# Deliberately a register at module level and not a key at the datagraph: so it can never be
# saved with the crate. A run is a process (main.py).
_LIBRARIES = {}        # name -> library dict, exactly the object the run works with
_LIBRARY_INDEX = {}    # @id -> entity across all libraries
_LIBRARY_STATE = {}    # name -> {@id: JSON of the entity when registered} for the write protection
_CONTENT_HOLDERS = {}  # @id of a content -> devices of the libraries that ever held it (rule 2.15)


def _entity_state(entity: dict) -> str:
    import json
    return json.dumps(entity, sort_keys=True, ensure_ascii=False)


def _rebuild_library_index():
    _LIBRARY_INDEX.clear()
    _CONTENT_HOLDERS.clear()
    for library in _LIBRARIES.values():
        for entity in library.get("@graph", []):
            _LIBRARY_INDEX.setdefault(entity.get("@id"), entity)
            for content_id in ref_ids(entity.get("cpo:hasContainedMaterialHistory")):
                _CONTENT_HOLDERS.setdefault(content_id, []).append(entity)


def library_holders(content_id: str) -> list:
    """The devices of the registered libraries that have held this content (cpo:hasContainedMaterialHistory,
    rule 2.15) - also when it has been used up meanwhile and does not name its device any more."""
    return list(_CONTENT_HOLDERS.get(content_id, []))


def register_library(name: str, library: dict):
    """Make a library resolvable in this run (see resolve). Registering a name again replaces
    that library - used when the run switches to another state of it.
    Its state now is what check_libraries_unchanged compares."""
    _LIBRARIES[name] = library
    _LIBRARY_STATE[name] = {entity.get("@id"): _entity_state(entity) for entity in library.get("@graph", [])}
    _rebuild_library_index()


def registered_library(name: str) -> dict:
    """The library registered under this name, or an empty one - for questions that offer its
    entries without the library being passed down (the software library for cpo:usedSoftware)."""
    return _LIBRARIES.get(name, {"@graph": []})


def resolve(datagraph, entity_id: str):
    """The entity with this @id in datagraph, or else in one of the registered libraries.

    For every place that may legitimately land on a library entry - a Fixed entry at the end
    of a specializationOf chain, the body material of a device. Places that only mean the
    crate use find_entity.
    """
    if not entity_id:
        return None
    found = find_entity(datagraph, entity_id)
    if found is not None:
        return found
    found = _LIBRARY_INDEX.get(entity_id)
    if found is None and _LIBRARIES:
        # A library can grow during the run (a new chemical, "create new") - index once more.
        _rebuild_library_index()
        found = _LIBRARY_INDEX.get(entity_id)
    return found


def is_library_entity(entity: dict) -> bool:
    """Whether entity is an entry of a registered library - the very object, not a crate
    entity with the same data. A run never writes to such an entry (rule 2.2): no
    hlo:hasSpecialization back to the crate, no context."""
    if not entity or not _LIBRARIES:
        return False
    entity_id = entity.get("@id")
    if entity_id not in _LIBRARY_INDEX:
        _rebuild_library_index()
    return _LIBRARY_INDEX.get(entity_id) is entity


# Rule 2.2 without exception: a run changes nothing at the registered libraries. The use of
# the devices (usageHistory, lastUsedTime) is written by record_device_usage into a freshly
# loaded version of the Device Library, not into the registered one; the run creates no new
# chemicals.


class LibraryChangedError(RuntimeError):
    """A run changed a library entry it may only read (rule 2.2)."""


def check_libraries_unchanged():
    """Stop the run when a registered library differs in any way from its state at
    registration (rule 2.2)."""
    import json
    problems = []
    for name, library in _LIBRARIES.items():
        before = _LIBRARY_STATE[name]
        now = {entity.get("@id"): entity for entity in library.get("@graph", [])}
        for entity_id in before.keys() - now.keys():
            problems.append(f"{name}: {entity_id} was removed")
        for entity_id, entity in now.items():
            if entity_id not in before:
                problems.append(f"{name}: {entity_id} was added")
                continue
            if _entity_state(entity) == before[entity_id]:
                continue
            old = json.loads(before[entity_id])
            changed = {key for key in old.keys() | entity.keys() if old.get(key) != entity.get(key)}
            problems.append(f"{name}: {entity_id} changed ({', '.join(sorted(changed))})")
    if problems:
        raise LibraryChangedError("The run changed library entries it may only read (rule 2.2):\n  " + "\n  ".join(problems))


def find_entity(target_graph, entity_id: str):
    """
    Return the entity with the given @id, or None if not found.
    Works with a graph-dict (e.g. datagraph, {"@graph": [...]})
    as well as with a plain list of entities (e.g. todo_list).
    Only the given graph is searched - for library entries see resolve.
    """
    entities = target_graph if isinstance(target_graph, list) else target_graph.get("@graph", [])

    for entity in entities:
        if entity.get("@id") == entity_id:
            return entity
    return None


def value_label(value_id: str, *sources) -> str:
    """Readable and, above all, STABLE name for a recorded value in a question.

    Stable is the point. A task placeholder's @id is not: generate_id hands out the first
    free number in the graph and the todo list, so a number that falls free - a placeholder
    that was absorbed into another task - is handed out again. #MeasurementTask_0021 and
    #MeasurementTask_0003 named the same thing in two runs that differed by two merged
    tasks, and the answer recorded against the first no longer matched the second. A value's
    own @id does not move like that: it is created in the value stage and stays.

    Readable comes from the entity the value belongs to (hlo:isEvidenceOf/isReferenceOf):
    "Mass Molecule 0007 LiquidPhase 0002 ExperimentSpecific 1" says WHAT was determined,
    where "#ScalarVariable_0008_ExperimentSpecific_1" says nothing. The ID stays in
    brackets, because two values of the same quantity have to stay distinguishable and the
    text alone would not do it.

    sources are searched in order and may be graph-dicts or plain lists (see find_entity).
    """
    def look_up(entity_id):
        for source in sources:
            if source is None:
                continue
            found = find_entity(source, entity_id)
            if found is not None:
                return found
        return None

    value = look_up(value_id)
    if value is None:
        return value_id

    owner_id = ref_id(value.get("hlo:isEvidenceOf") or value.get("hlo:isReferenceOf"))
    owner = look_up(owner_id) if owner_id else None
    described = get_display_label(owner if owner is not None else value)
    return f"{described} ({value_id})"


def find_entities_by_type(target_graph: dict, entity_type: str, namespace_collection: dict, include_subclasses: bool = False):
    """Pure lookup, NO user interaction. Returns a list, which may be empty."""

    if include_subclasses:
        subclass_list = []
        valid_types = get_all_subclasses(entity_type, namespace_collection, subclass_list)
    else:
        valid_types = {entity_type}

    matching_entities = []

    for entity in target_graph.get("@graph", []):
        types = as_list(entity.get("@type"))

        if any(t in valid_types for t in types):
            matching_entities.append(entity)

    return matching_entities


def find_entities_by_type_interactive(target_graph: dict, entity_type: str, namespace_collection: dict, possible_types, include_subclasses: bool = False, *, question_id_prefix: str):
    """Wrapper with user interaction: on an empty result, offers retry or placeholder.

    Returns (entities_or_None, the type actually used).

    question_id_prefix is MANDATORY (see helpers/user_io.py) and is assigned by each
    caller separately, because this function is called from several different places
    (evidence/reference resolution, input value selection, ...).
    """

    from helpers.user_io import question_path

    i = 0
    while True:
        matching_entities = find_entities_by_type(target_graph, entity_type, namespace_collection, include_subclasses)
        if matching_entities:
            return matching_entities, entity_type

        i += 1
        print(f"There is no entity of type {entity_type} in the datagraph yet. Choose again.")
        with question_path("retry", i):
            answer = ask_user(
                f"The entity type you selected: {entity_type} does not yet exist in the datagraph. "
                f"Do you want to choose another type or create a placeholder entity with the type {entity_type}?",
                ["Retry", "Placeholder"],
                question_id=f"{question_id_prefix}_retry_or_placeholder"
            )

            if answer != "Retry":
                return None, entity_type
            entity_type = ask_user("Of what type is the evidence?", possible_types, question_id=f"{question_id_prefix}_retry_type")