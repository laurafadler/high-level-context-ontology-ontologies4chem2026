"""
Provides functions for loading and saving JSON-LD files and ensuring
the required root entities exist in the RO-Crate.
"""



import json
from pathlib import Path
from datetime import datetime, timezone

import path_definitions
from helpers.entities import find_entity, add_entity, collect_prefixes
from helpers.library_files import is_split, read_library, split_library
from helpers.properties import set_property
from helpers.safe_write import write_atomic

# Context on which the RO-Crate is based
RO_CRATE_CONTEXT_URL = "https://w3id.org/ro/crate/1.3/context"

# The PROFILE the crate follows - NOT the same as the context above. The RO-Crate 1.3
# specification explicitly asks for the specification URI in the metadata descriptor
# ("The URI SHOULD start with https://w3id.org/ro/crate/"), not the context file:
# conformsTo says by which specification the crate is built, the context only how this
# one document resolves its prefixes.
#
# The URI cannot be retrieved (404) - that is right: it is an identifier for the profile,
# not a download link. The context URL below is a file and therefore loads.
RO_CRATE_PROFILE_URL = "https://w3id.org/ro/crate/1.3"


def _load_project_context() -> dict:
    """The project's prefix table, read from libraries/project_context.jsonld.

    It lives in a data file rather than in this module so that adding a namespace is a data
    change like any other library edit, not a code change - and so that the table sits next
    to the ontology library it has to agree with.

    Deliberately NOT part of ontology_library.jsonld: that one documents VOCABULARIES, each
    with a version and an access date, and its own notes record the decision that the local
    ID namespaces (chem:, device:, task:, ...) do not belong there. This table needs both.

    Read directly rather than through load_jsonld below: this runs at import time, and the
    file is a plain JSON-LD context document with no @graph. A missing or broken file is
    fatal on purpose - an empty table would produce a crate in which nothing resolves, and
    that failure is far harder to spot afterwards than a stack trace here.
    """
    try:
        with open(path_definitions.PROJECT_CONTEXT_PATH, "r", encoding="utf-8") as f:
            table = json.load(f).get("@context")
    except (OSError, ValueError) as error:
        raise RuntimeError(
            f"The prefix table {path_definitions.PROJECT_CONTEXT_PATH} cannot be "
            f"read: {error}. Without it every prefixed ID in the crate would be meaningless."
        ) from error

    if not isinstance(table, dict) or not table:
        raise RuntimeError(
            f"{path_definitions.PROJECT_CONTEXT_PATH} contains no @context object."
        )
    return table


# The project's own prefix table - the same prefixes every libraries/*.jsonld file already
# defines inline on its own (see e.g. libraries/chemical_entity_library.jsonld). The
# RO-Crate 1.3 context alone does NOT define cpo:/hlo:/dcterms:/chebi:/qudt:/quantitykind:/
# chem:/... (not even when retrieved online) - without this table all property/type/ID values
# prefixed in this way stay unresolved, technically meaningless strings in
# ro-crate-metadata.json for every JSON-LD processor (GraphDB too) instead of real IRIs.
#
# The content stands in libraries/project_context.jsonld, with the detailed reason there. A
# missing prefix is silent: without xsd the datatype of every typed literal stays a relative
# IRI, and SHACL cannot report that - a literal WITHOUT a datatype IS xsd:string in RDF
# (verify_context_completeness below makes it loud).
PROJECT_CONTEXT = _load_project_context()

# @context as an array [RO-Crate URL, prefix table] - that is how JSON-LD combines both: the
# RO-Crate conventions (schema:, About/CreativeWork/Dataset, ...) AND the project's own
# prefixes. conformsTo (see ensure_root_entities) still refers only to the plain RO-Crate URL,
# not to this combined array - conformsTo references a profile, not the context of this
# particular document.
DEFAULT_CONTEXT = [RO_CRATE_CONTEXT_URL, PROJECT_CONTEXT]



# Every prefix of the crate stands in PROJECT_CONTEXT, also schema, rdf and rdfs, which the
# RO-Crate 1.3 context brings along as well: helpers/context_links.py reads the crate with this
# table alone. The RO-Crate context does not bring xsd, dcterms, owl, time, sosa or qudt.


def verify_context_completeness(datagraph: dict) -> list:
    """Check that every prefix the finished crate uses is declared in its own @context.

    The @context is written ONCE, before anything is in the graph (see load_jsonld below),
    and is a hand-maintained table. Nothing compares it against what the crate ends up
    containing - so a prefix that is missing from the table does not fail, it just stays an
    unresolvable relative IRI that no reader can follow. That is silent: the file is still
    valid JSON-LD, the entity is still there, it simply means nothing any more.

    Without this check a missing prefix ("xsd", the datatype of every typed literal) is only
    noticed by parsing the finished crate with rdflib. This check makes it loud.

    Deliberately read off the datagraph rather than off PROJECT_CONTEXT: when a run
    continues an EXISTING crate instead of starting a fresh one, the @context comes from the
    file on disk, and a prefix added to PROJECT_CONTEXT later never reaches it. That case
    would otherwise stay invisible.

    Returns the undeclared prefixes; empty means everything resolves.
    """
    context = datagraph.get("@context", [])
    parts = context if isinstance(context, list) else [context]
    declared = set()
    for part in parts:
        if isinstance(part, dict):
            declared |= set(part)

    used = collect_prefixes(datagraph.get("@graph", []))
    return sorted(used - declared)


def add_key_terms(datagraph: dict) -> int:
    """Declare every prefixed key the crate uses as a term of its own in the @context.

    RO-Crate 1.3 asks for the compacted form: every key of the metadata file a term of the context
    (check ro-crate-1.3_4.1 of the RO-Crate validator). JSON-LD itself is content with a prefix
    ("cpo:hasVolume" expands through "cpo"), so the crate meant the same before - only the keys were
    not terms. The terms are written in the short form {"@id": "cpo:hasVolume"}, read off the finished
    graph (only what is used, nothing kept by hand), into a copy of the prefix table - PROJECT_CONTEXT
    stays as it is. With real, published addresses this table becomes a context file of its own at
    that address (things_to_implement_after_me.md, "Real prefixes"). Returns the number of terms."""
    context = datagraph.get("@context", [])
    parts = list(context) if isinstance(context, list) else [context]
    index = next((i for i, part in enumerate(parts) if isinstance(part, dict)), None)
    if index is None:
        return 0
    table = {key: value for key, value in parts[index].items() if not (isinstance(value, dict) and value.get("@id") == key)}
    keys = sorted({key for entity in datagraph.get("@graph", []) for key in entity
                   if ":" in key and not key.startswith("@") and key.split(":", 1)[0] in table})
    for key in keys:
        table[key] = {"@id": key}
    parts[index] = table
    datagraph["@context"] = parts
    return len(keys)


def empty_datagraph() -> dict:
    """The empty skeleton of a crate: context and an empty graph."""
    return {"@context": DEFAULT_CONTEXT, "@graph": []}


def load_jsonld(path: Path, reset: bool = False) -> dict:
    # Input: path to the jsonld file we want to load
    # Output: Python dictionary (either the empty skeleton or what is in the file already and was read)

    # Checks whether the path exists (whether we have a ro-crate-metadata.json file already, for example), and if not, the empty skeleton with context and graph is created and returned as a dict
    # To read a file, reset has to be set to false
    if reset or not path.exists():
        return empty_datagraph()

    # A split library (main file + details/) is read as one document.
    if is_split(path):
        return read_library(path)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_jsonld(data: dict, path: Path) -> None:
    # Input: Python dictionary with the data to be written into the jsonld, and the path it is to be saved under
    # No output (the file it is saved in, but that is no classic output)

    # Write completely into a neighbouring file first, then move it into place with
    # os.replace (helpers/safe_write.py). os.replace is atomic: there is no moment in which the target file lies
    # half-written on disk.
    #
    # That is no luxury here. helpers/entities.py::add_entity calls this function after
    # EVERY newly created entity (so that the graph can be read along live), with over 2000
    # entities by now that is over 2000 times per run - and the project folder lies in
    # OneDrive. The sync service accesses the file while it is open, and then the next
    # open(path, "w") fails with "OSError: [Errno 22] Invalid argument". Unhandled, that would
    # tear the run apart in the middle and leave a half-written crate; so the writing is
    # repeated briefly, and what lies on disk is always a complete state.
    #
    # A split library goes back into its two files (helpers/library_files.py).
    for part_path, part in split_library(path, data):
        _write_json(part, part_path)


def _write_json(data: dict, path: Path) -> None:
    write_atomic(path, json.dumps(data, indent=2, ensure_ascii=False))


def ensure_root_entities(datagraph: dict) -> None:
    # Checks whether the two root entities (metadata descriptor and dataset) exist, and if not they are created

    # Take the current time
    now = datetime.now(timezone.utc).isoformat()

    # Find the CreativeWork entity
    if find_entity(datagraph, "ro-crate-metadata.json") is None:
        add_entity(datagraph, {
            "@id": "ro-crate-metadata.json",
            "@type": "CreativeWork",
            "conformsTo": {"@id": RO_CRATE_PROFILE_URL},
            "about": {"@id": "./"},
        })

    # Find the Dataset entity
    dataset = find_entity(datagraph, "./")

    if dataset is None:
        add_entity(datagraph, {
            "@id": "./",
            "@type": "Dataset",
            "dateCreated": now
        })
    else:
        # If the entity exists already, dateModified is added or overwritten with the current time
        set_property(dataset, "dateModified", now)
        # More properties are attached to this entity later, such as creator, hasPart etc., but for that the things have to be created or asked first.