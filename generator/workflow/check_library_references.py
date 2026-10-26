"""
Library pre-run, step 1: check an answer file against the libraries WITHOUT running the
generator.

The crate run only reads the libraries; a chemical it cannot find stops it
(creation/chemical_entity_functions.py: MissingLibraryEntryError), and a device, person or
reaction that is not there fails the same way. This tool finds all of them at once, in seconds,
with the key that asks for each:

- chemical entities: every search (.../identifier_field + .../identifier_value), run with the
  same search as the crate run;
- devices: the list series:1/devices;
- people: creator and experimenter of series and experiments, the creator of a file, the
  performers of a task (answers match like in the run: case and spaces do not count);
- reactions: the list fixed/reactions;
- software: the software that generated a file;
- and, as a note only, the authors of the files in the data folders that are no person of the
  library (the run then asks for the creator).

Run from the repository root:
    python generator/workflow/check_library_references.py [projects/<crate_identifier>/answers.txt]
Exit code 1 when anything is missing.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from workflow.answer_file import parse  # noqa: E402

import path_definitions  # noqa: E402
from helpers.file_handling import load_jsonld  # noqa: E402
from helpers.identifiers import LIST_SEPARATOR, get_display_label  # noqa: E402
from helpers.library_functions import get_id_list, load_device_libraries  # noqa: E402
from helpers.user_io import _match_option  # noqa: E402
from creation.chemical_entity_functions import IDENTIFIER_FIELDS, _search_chemical_entities  # noqa: E402
from creation.reaction_functions import _all_fixed_reactions  # noqa: E402
from creation.task_functions import NOT_PERFORMED_BY_A_PERSON  # noqa: E402
from creation.media_object_functions import person_by_author  # noqa: E402
from get_additional_information.get_file_metadata import collect_folder_metadata  # noqa: E402

PERSON_LEAVES = {"series_creator", "series_experimenter", "creator", "experimenter", "creator_person", "performers"}


def _items(answer: str) -> list:
    return [item.strip() for item in answer.split(LIST_SEPARATOR) if item.strip()]


def check(answer_path: Path) -> tuple:
    """(missing, notes): lists of (what, key, detail)."""
    entries = parse(answer_path.read_text(encoding="utf-8"))
    answers = {key: answer for key, _, answer in entries}
    chemicals = load_jsonld(path_definitions.CHEMICAL_ENTITY_LIBRARY_PATH)
    devices, _ = load_device_libraries()   # devices and containers of the chemical store
    people = load_jsonld(path_definitions.PEOPLE_LIBRARY_PATH)
    reactions = load_jsonld(path_definitions.REACTION_LIBRARY_PATH)
    software = load_jsonld(path_definitions.SOFTWARE_LIBRARY_PATH)

    person_options = get_id_list(people, "person:", "schema:Person")
    software_options = get_id_list(software, "software:")
    reaction_labels = [get_display_label(entity) for entity in _all_fixed_reactions(reactions)]
    missing, notes = [], []

    for key, answer in answers.items():
        leaf = key.rsplit("/", 1)[-1]

        if leaf == "identifier_field":
            value_key = key[:-len("identifier_field")] + "identifier_value"
            field_label = answer.strip()
            if field_label not in IDENTIFIER_FIELDS:
                missing.append(("chemical entity", key, f"answer '{field_label}' asks for a new entity - the crate run does not create any"))
                continue
            query = answers.get(value_key, "").strip()
            if not _search_chemical_entities(chemicals, IDENTIFIER_FIELDS[field_label], query):
                missing.append(("chemical entity", value_key, f"no entry with {field_label} '{query}'"))

        elif key == "series:1/devices":
            for name in _items(answer):
                if not any(e.get("@id") == f"device:{name}" for e in devices.get("@graph", [])):
                    missing.append(("device", key, f"device:{name}"))

        elif leaf in PERSON_LEAVES:
            for name in _items(answer):
                if name == NOT_PERFORMED_BY_A_PERSON:
                    continue
                if _match_option(name, person_options) is None:
                    missing.append(("person", key, name))

        elif leaf == "creator_software":
            for name in _items(answer):
                if _match_option(name, software_options) is None:
                    missing.append(("software", key, name))

        elif key == "fixed/reactions":
            for name in _items(answer):
                if _match_option(name, reaction_labels) is None:
                    missing.append(("reaction", key, name))

    # the series of this answer file (projects/<identifier>/answers.txt); otherwise the only open crate
    folder = answer_path.resolve().parent
    if folder.parent == path_definitions.PROJECTS_FOLDER.resolve():
        identifier = folder.name
    else:
        identifier = path_definitions.identifier_of_crate(path_definitions.default_crate_path())
    for folder in (path_definitions.series_files_folder(identifier), path_definitions.experiment_files_folder(identifier)):
        if not Path(folder).is_dir():
            notes.append(("data folder", str(folder), "does not exist"))
            continue
        rows, _ = collect_folder_metadata(folder)
        for row in rows:
            if not person_by_author(row["Author"], people):
                notes.append(("file author", f"{row['Folder'] or '.'}/{row['File Name']}",
                              f"author '{row['Author']}' is no person of the library - the run asks for the creator"))
    return missing, notes


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("answers", nargs="?", default=None,
                        help="default: projects/<crate_identifier>/answers.txt of the only open crate")
    args = parser.parse_args()
    if args.answers is None:
        import path_definitions
        args.answers = path_definitions.default_answer_file()
    missing, notes = check(Path(args.answers))

    if missing:
        print(f"Missing in the libraries ({len(missing)}):")
        for what, key, detail in missing:
            print(f"  [{what}] {detail}\n      asked at {key}")
    else:
        print("Nothing missing in the libraries.")
    if notes:
        print(f"\nNotes ({len(notes)}):")
        for what, where, detail in notes:
            print(f"  [{what}] {where}: {detail}")
    sys.exit(1 if missing else 0)


if __name__ == "__main__":
    main()
