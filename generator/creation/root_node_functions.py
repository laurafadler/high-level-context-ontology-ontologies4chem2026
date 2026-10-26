"""Link the RO-Crate root dataset ("./") to the entities the crate starts from.

A crate is supposed to describe itself: walking it from "./" has to reach the series, the
experiments, the devices and every task, not only the snapshots - without needing an ID to
start from.

Deliberately NOT a list of everything. Two starting points are enough, because the rest
hangs off them:

  - the cpo:ExperimentalSeries        -> experiments -> procedures -> tasks -> equipment,
                                         phases, transfers, values
  - the files (schema:MediaObject)    -> RO-Crate convention: the data of a crate are parts
                                         of its root dataset

The context aspects are no starting point and no part of the data: a context stands beside the
things that describe it (hlo:contextDescribedBy) and is reached from them; one that nothing
describes yet may stand on its own.

Anything else reachable only through these is left alone: adding it would turn hasPart from
"where the crate starts" into "everything in the crate", which says nothing.

ro-crate-metadata.json stays out on purpose - by RO-Crate convention the descriptor points
AT the root dataset (schema:about), it is not a part of it.
"""

from helpers.entities import find_entity, as_list
from helpers.properties import set_property
from helpers.ontology_functions import find_subclasses


def _is_of_type(entity: dict, type_name: str) -> bool:
    return type_name in as_list(entity.get("@type"))


def link_root_parts(namespace_collection: dict, datagraph: dict):
    """Hang the crate's starting points into the root dataset's dcterms:hasPart.

    Idempotent: set_property with multi=True does not add an entry twice.
    """
    root = find_entity(datagraph, "./")
    if root is None:
        print("[Root] No root dataset './' in the crate - skipping.")
        return

    # The file classes come from the ontology (cpo:File, cpo:Image, ...), not from a list
    # here - a new subclass of schema:MediaObject is thus included at once.
    file_types = set(find_subclasses("schema:MediaObject", namespace_collection)) | {"schema:MediaObject"}

    starting_points = []
    for entity in datagraph.get("@graph", []):
        if _is_of_type(entity, "cpo:ExperimentalSeries") or any(_is_of_type(entity, ft) for ft in file_types):
            starting_points.append(entity)

    for entity in starting_points:
        set_property(root, "dcterms:hasPart", entity, namespace_collection, True)

    print(f"[Root] {len(starting_points)} starting point(s) linked into './'.")


def name_unnamed_entities(datagraph: dict, identifier: str) -> int:
    """Give every entity of this crate that has no schema:name one read off its ID (generate_name) - RO-Crate
    recommends a name for every entity (rule 1.4). Done once, just before saving, and not where
    the entity is created: the generator asks for a name, or takes the one of the series template, only where
    none is set yet (creation/material_functions.py, task_functions.py) - a name set on creation would change
    those questions. The label the questions show is the same either way (get_display_label falls back to
    generate_name). Entities of libraries or other crates are left alone; no rdfs:label besides schema:name.
    Returns the number of names given."""
    from helpers.identifiers import generate_name
    own = f"crate:{identifier}/"
    given = 0
    for entity in datagraph.get("@graph", []):
        if str(entity.get("@id", "")).startswith(own) and not entity.get("schema:name"):
            entity["schema:name"] = generate_name(entity["@id"])
            given += 1
    return given


def finish_root_dataset(datagraph: dict, now: str):
    """What RO-Crate asks of the root dataset ("./"), set just before saving (rule 4a.3): name and
    description - those of the series -, datePublished (this run) and its parts under hasPart, the
    schema.org property of the RO-Crate context.

    Inside the crate the parts stay dcterms:hasPart (a device and its parts, a snapshot and its
    files): schema:hasPart is narrower (a CreativeWork's parts) and does not fit a device. Only the
    root uses the RO-Crate property, so that RO-Crate tools find the parts.
    The licence is still open (docs/things_to_implement_after_me.md) - left out rather than guessed."""
    root = find_entity(datagraph, "./")
    if root is None:
        return
    parts = as_list(root.pop("dcterms:hasPart", None)) + as_list(root.get("hasPart"))
    unique = []
    for part in parts:
        if part not in unique:
            unique.append(part)
    if unique:
        root["hasPart"] = unique
    series = next((e for e in datagraph.get("@graph", []) if _is_of_type(e, "cpo:ExperimentalSeries")), None)
    if series is not None:
        name = series.get("schema:name")
        description = series.get("schema:description")
        if name:
            root["name"] = name
        if description:
            root["description"] = description
    root["datePublished"] = now
