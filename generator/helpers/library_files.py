"""
Libraries in two files: the main file holds what the library
is about - devices with their parts and ports, the contents of the material library, organizations,
sites and rooms, substances, reactions with their participants - and
libraries/details/<name>_details.jsonld everything that describes them: forms, body materials and contents, values with their evidence and references,
tasks and their times. One file to look things up in, one for the record behind them.

The two files are ONE library: read_library joins their graphs (main entries first), and
write_library splits a graph again by is_main_entry - also for entries a run or a library tool has
just added. Links between the files are ordinary @id references; nothing is copied. Every reader
goes through here (helpers/file_handling.py: load_jsonld/save_jsonld do it for every split
library), so the rest of the generator sees the same library as before.

Libraries that are not split (people, software, assumptions, ontologies) are single files as before.
"""
import json
from pathlib import Path

import path_definitions

DETAILS_FOLDER = path_definitions.LIBRARY_FOLDER / "details"

# Types that make up a value, a time or a task - always details.
VALUE_TYPES = {"hlo:Actual", "hlo:Evidence", "hlo:Reference", "cpo:ProcessVariable", "cpo:Parameter",
               "time:Instant", "time:Duration", "cpo:Task"}
ORGANIZATION_MAIN = {"org:Organization", "org:Site", "cpo:Laboratory", "cpo:StorageCabinet"}


def _types(entity) -> set:
    types = entity.get("@type")
    return set(types if isinstance(types, list) else [types] if types else [])


def is_detail(entity) -> bool:
    """A value, a time, a form or a task - in every split library a detail."""
    types = _types(entity)
    return bool(types & VALUE_TYPES) or any(t.endswith("Form") or t.endswith("Task") for t in types) \
        or entity.get("@id", "").startswith("task:")


def _device_main(entity) -> bool:
    return entity.get("@id", "").startswith(("device:", "port:")) and not is_detail(entity)


def _material_main(entity) -> bool:
    # What the Material Library is about: the contents themselves; phases, species, occurrences,
    # values, tasks and certificates describe them.
    return "cpo:MaterialVolume" in _types(entity) and not is_detail(entity)


def _organization_main(entity) -> bool:
    return bool(_types(entity) & ORGANIZATION_MAIN) and not is_detail(entity)


def _other_main(entity) -> bool:
    return not is_detail(entity)


# Name of the library file -> what belongs in the main file.
SPLIT = {
    "device_library.jsonld": _device_main,
    "material_library.jsonld": _material_main,
    "organization_library.jsonld": _organization_main,
    "chemical_entity_library.jsonld": _other_main,
    "reaction_library.jsonld": _other_main,
}


def is_split(path) -> bool:
    """A split library - also in a copy of the project (an isolated run, a test): the file name and
    a folder named like the libraries folder decide, not where the project lies."""
    path = Path(path)
    return path.name in SPLIT and path.parent.name == path_definitions.LIBRARY_FOLDER.name


def details_path(path) -> Path:
    path = Path(path)
    return path.parent / DETAILS_FOLDER.name / f"{path.stem}_details{path.suffix}"


def library_files() -> list:
    """Every file of every library - the main files and their details."""
    files = sorted(path_definitions.LIBRARY_FOLDER.glob("*.jsonld"))
    return files + sorted(DETAILS_FOLDER.glob("*.jsonld")) if DETAILS_FOLDER.exists() else files


def is_main_entry(path, entity) -> bool:
    return SPLIT[Path(path).name](entity)


def read_library(path) -> dict:
    """One library as one document: the graph of the main file, then that of its details."""
    path = Path(path)
    with open(path, "r", encoding="utf-8") as f:
        document = json.load(f)
    details = details_path(path)
    if is_split(path) and details.exists():
        with open(details, "r", encoding="utf-8") as f:
            document["@graph"] = document.get("@graph", []) + json.load(f).get("@graph", [])
    return document


def split_library(path, document: dict) -> list:
    """[(path, document)] to write: main entries to the library file, the rest to its details -
    each in the order it has in the joined graph, both with the library's @context."""
    if not is_split(path):
        return [(Path(path), document)]
    main, details = [], []
    for entity in document.get("@graph", []):
        (main if is_main_entry(path, entity) else details).append(entity)
    rest = {k: v for k, v in document.items() if k != "@graph"}
    return [(Path(path), {**rest, "@graph": main}), (details_path(path), {**rest, "@graph": details})]
