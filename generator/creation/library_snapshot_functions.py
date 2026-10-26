"""
Library snapshot: records, at the end of a crate run, which libraries the crate points into
and in which committed state (rule 2.3).

The counterpart of the ontology snapshot (creation/ontology_snapshot_functions.py): the crate
links to library entries instead of copying them, so it has to say which version of each
library those links mean. One entry per library file, with the commit that holds the file
as it was used (helpers/git_functions.py: last_commit_of) and that commit's date. The list is
at the same time the answer to "what do I need next to this crate to follow every link?".

Only libraries the crate actually points into are listed: a library counts once any entity
of the crate refers to one of its entries, or the crate carries one of them itself. The
assumption library is the exception and always listed (ALWAYS_LISTED): its model assumptions
hold in every run, even where no value of the crate names them.
"""


import path_definitions
from helpers.entities import find_entity, add_entity
from helpers.git_functions import last_commit_of
from helpers.identifiers import crate_id
from helpers.properties import set_property, check_type

# The files that hold entries with IDs of their own. project_context.jsonld is left out on
# purpose: it is the table of prefixes, it stands complete as the @context in the crate itself.
LIBRARY_PATHS = (
    path_definitions.DEVICE_LIBRARY_PATH,
    path_definitions.MATERIAL_LIBRARY_PATH,
    path_definitions.PEOPLE_LIBRARY_PATH,
    path_definitions.ORGANIZATION_LIBRARY_PATH,
    path_definitions.SOFTWARE_LIBRARY_PATH,
    path_definitions.REACTION_LIBRARY_PATH,
    path_definitions.CHEMICAL_ENTITY_LIBRARY_PATH,
    path_definitions.ASSUMPTION_LIBRARY_PATH,
    path_definitions.ONTOLOGY_LIBRARY_PATH,
)

# The Assumption Library stands in the snapshot of EVERY crate, even if no entry of the crate
# points at it: its modelling assumptions (inert phases exchange nothing) hold in every run, but
# determine no value a reference could hang on. That way the crate names the state of the
# assumptions under which it was made.
ALWAYS_LISTED = (path_definitions.ASSUMPTION_LIBRARY_PATH,)

SNAPSHOT_LOCAL_NAME = "LibrarySnapshot"
SNAPSHOT_NAME = "Library snapshot"
SNAPSHOT_DESCRIPTION = ("The libraries this crate links into, each with the commit that holds the state the "
                        "crate was built against. The crate only links to library entries; to follow those "
                        "links, check out each library at the recorded commit.")


def _referenced_ids(datagraph: dict) -> set:
    """Every @id the crate carries or points at."""
    found = set()

    def walk(value):
        if isinstance(value, dict):
            if "@id" in value:
                found.add(value["@id"])
            for key, item in value.items():
                if key != "@id":
                    walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(datagraph.get("@graph", []))
    return found


def _library_ids(path) -> set:
    from helpers.library_files import read_library
    library = read_library(path)
    return {entity["@id"] for entity in library.get("@graph", []) if "@id" in entity}


def create_library_snapshot(namespace_collection: dict, datagraph: dict):
    root = find_entity(datagraph, "./")
    if root is None:
        return

    referenced = _referenced_ids(datagraph)
    used = [path for path in LIBRARY_PATHS if path in ALWAYS_LISTED or _library_ids(path) & referenced]

    snapshot = {"@id": crate_id(SNAPSHOT_LOCAL_NAME), "@type": "Dataset"}
    set_property(snapshot, "schema:name", SNAPSHOT_NAME, namespace_collection)
    set_property(snapshot, "schema:description", SNAPSHOT_DESCRIPTION, namespace_collection)

    # A split library (rule 2.14) stands in it with both files, each with its commit.
    from helpers.library_files import details_path, is_split
    files = []
    for path in used:
        files.append(path)
        if is_split(path) and details_path(path).exists():
            files.append(details_path(path))
    for path in files:
        relative = path.resolve().relative_to(path_definitions.BASE_FOLDER.resolve()).as_posix()
        entry = {"@id": crate_id(f"Library_{path.stem}"), "@type": [check_type("cpo:File", namespace_collection)]}
        set_property(entry, "schema:name", path.name, namespace_collection)
        set_property(entry, "cpo:hasStorageLocation", relative, namespace_collection)
        set_property(entry, "schema:encodingFormat", "application/ld+json", namespace_collection)

        commit = last_commit_of(path)
        if commit is None:
            print(f"[Library Snapshot] No commit holds {relative} as it is now - the entry is written without a version.")
        else:
            # schema:version and schema:dateModified directly, like dateCreated at the root node
            # (ensure_root_entities): set_property only knows properties of the loaded ontologies, and
            # cpo:usedVersion/cpo:lastAccessDate have the domain cpo:Ontology - at a library file they
            # would claim that it is an ontology.
            entry["schema:version"] = commit[0]
            entry["schema:dateModified"] = {"@value": commit[1], "@type": "xsd:dateTime"}

        add_entity(datagraph, entry)
        set_property(snapshot, "dcterms:hasPart", entry, namespace_collection, True)

    add_entity(datagraph, snapshot)
    set_property(root, "dcterms:hasPart", snapshot, namespace_collection, True)
