"""
Ontology snapshot: records, at the end of a crate run, which ontologies and vocabularies
were actually used (prefix, namespace, version, last access, link to the ontology file).

The entries are copied as cpo:Ontology entities out of libraries/ontology_library.jsonld
(see copy_library_subtree in helpers/library_functions.py) and collected under ONE snapshot
entity, which is what the RO-Crate root dataset ("./") lists.

Not one by one at the root: the root's dcterms:hasPart is meant to say where the crate starts,
and a list in which four starting points drown between forty vocabularies says nothing (see
creation/root_node_functions.py). The snapshot is one starting point, and what it collects
is exactly the question "which vocabularies does this crate speak".

usedVersion and lastAccessDate cannot be determined automatically (they may stay the same
across several runs and need not match the newest version), so they are read wholesale
from the library rather than asked for. The library has to be maintained by hand (see
libraries/ontology_library.jsonld).

Runs deliberately AT THE VERY END (see main.py, after every other creation step): only
then can it be said reliably which prefixes actually occur in the finished datagraph.
"""

from helpers.entities import find_entity, add_entity, collect_prefixes
from helpers.properties import set_property
from helpers.identifiers import crate_id
from helpers.library_functions import copy_library_subtree


# Pure syntax/serialization vocabularies - they carry no meaning for the process
# described and are therefore never documented in the snapshot.
_EXCLUDED_PREFIXES = {"xml", "rdf", "rdfs", "owl", "xsd"}

# Behind this namespace lie the own IDs of this project (chem:, device:, material:,
# task:, ...), no vocabulary: there is no ontology there that could be cited in a version.
# So they do not belong in the snapshot.
#
# The distinction is needed because _collect_used_prefixes also reads @id values (see
# there): without it every run would report a dozen "no entry for prefix X" - a number
# nobody reads, and the message would be worthless as a signal.
_LOCAL_NAMESPACE = "https://example.org/"


def _local_prefixes(datagraph: dict) -> set:
    """The prefixes of this crate's own ID namespaces, read off its @context."""
    context = datagraph.get("@context", [])
    table = next((part for part in context if isinstance(part, dict)), {}) if isinstance(context, list) else context
    return {prefix for prefix, namespace in table.items()
            if isinstance(namespace, str) and namespace.startswith(_LOCAL_NAMESPACE)}


def _collect_used_prefixes(datagraph: dict) -> set:
    """The vocabulary prefixes the finished crate actually speaks.

    collect_prefixes does the walking (property names, @type and @id, at any depth - see
    helpers/entities.py); what is left here is the two subtractions that make the result
    a list of VOCABULARIES rather than a list of prefixes: the pure syntax vocabularies,
    and this crate's own ID namespaces.

    Only these end up in the snapshot, rather than everything namespace_collection saw
    while loading the ontologies.
    """
    return collect_prefixes(datagraph.get("@graph", [])) - _EXCLUDED_PREFIXES - _local_prefixes(datagraph)


# Local name instead of a finished ID: the prefix of the crate is settled only once the run has started.
SNAPSHOT_LOCAL_NAME = "OntologySnapshot"
SNAPSHOT_NAME = "Ontology snapshot"
SNAPSHOT_DESCRIPTION = ("The ontologies and vocabularies this crate actually speaks, with the version and "
                        "access date they were read at. Collected at the end of the run from the prefixes "
                        "that occur in the finished crate.")


def _ensure_snapshot_entity(namespace_collection: dict, datagraph: dict, root: dict) -> dict:
    """The one entity the root lists instead of every single ontology."""
    snapshot = find_entity(datagraph, crate_id(SNAPSHOT_LOCAL_NAME))
    if snapshot is None:
        snapshot = {"@id": crate_id(SNAPSHOT_LOCAL_NAME), "@type": "Dataset"}
        set_property(snapshot, "schema:name", SNAPSHOT_NAME, namespace_collection)
        set_property(snapshot, "schema:description", SNAPSHOT_DESCRIPTION, namespace_collection)
        add_entity(datagraph, snapshot)
    set_property(root, "dcterms:hasPart", snapshot, namespace_collection, True)
    return snapshot


def create_ontology_snapshot(namespace_collection: dict, datagraph: dict, ontology_library: dict):
    root = find_entity(datagraph, "./")
    if root is None:
        return

    snapshot = _ensure_snapshot_entity(namespace_collection, datagraph, root)

    # Until a pass finds nothing new, not only once: copy_library_subtree enters the ontology
    # entities INTO the datagraph, and they use prefixes themselves (time: at the
    # lastAccessDate, cpo: at the file). A single collection before copying would miss a
    # prefix that only a library entry brings along. In practice this converges after the
    # second pass - time: and cpo: occur everywhere anyway.
    handled = set()
    while True:
        prefixes = _collect_used_prefixes(datagraph) - handled
        if not prefixes:
            break

        for prefix in sorted(prefixes):
            handled.add(prefix)
            ontology_id = f"ontology:{prefix}"

            if find_entity(ontology_library, ontology_id) is None:
                print(f"[Ontology Snapshot] No entry for prefix '{prefix}' in the ontology library - skipping (add it to libraries/ontology_library.jsonld if this should be documented).")
                continue

            # Into the crate itself: the snapshot records the state at the time of creation.
            copy_library_subtree(ontology_id, ontology_library, datagraph)
            ontology_entity = find_entity(datagraph, ontology_id)
            set_property(snapshot, "dcterms:hasPart", ontology_entity, namespace_collection, True)
