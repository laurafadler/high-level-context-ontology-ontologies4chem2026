"""
Entry point of the crate builder.

Creates an empty RO-Crate datagraph, walks through the creation steps in a
fixed order (see below), and writes the finished crate to projects/<identifier>/crate/.

Usually started through generator/workflow/answer_driver.py (see README.md). Directly, from this
directory, with an answer file to replay instead of typing every answer (see the module docstring
in helpers/user_io.py):
    ANSWER_FILE=../projects/<identifier>/answers.txt python main.py
"""

import logging
from datetime import datetime, timezone

import path_definitions
from helpers.file_handling import load_jsonld, save_jsonld, empty_datagraph, ensure_root_entities, verify_context_completeness, add_key_terms
from helpers.entities import register_library, check_libraries_unchanged
from helpers.library_functions import load_device_libraries
from helpers.crate_continuation import check_earlier_content_kept, keep_creation_date, archive_if_completed
from helpers.series_statements import check_series_contradictions, hoist_on_completion
from helpers.user_io import question_path, report_unused_answer_keys
from helpers.ontology_functions import initialize_ontologies
from helpers.context_functions import create_all_contexts
from helpers.context_links import link_contexts_from_shapes
from helpers.todo_functions import merge_todo_lists, save_todo_list
from creation.experiment_functions import create_process
from creation.occurrence_functions import ask_occurrences
from creation.device_functions import create_all_devices
from creation.material_functions import create_all_materials
from creation.environment_functions import create_all_environments
from creation.phase_functions import complete_all_phases
from creation.reaction_functions import complete_all_reactions
from creation.task_functions import complete_all_tasks
from creation.media_object_functions import create_all_media_objects
from creation.ontology_snapshot_functions import create_ontology_snapshot
from creation.root_node_functions import link_root_parts, finish_root_dataset, name_unnamed_entities
from creation.library_snapshot_functions import create_library_snapshot
from creation.device_usage_functions import record_device_usage, ask_emptied_containers
from helpers.git_functions import ensure_libraries_committed, commit_library_changes
from helpers.identifiers import current_crate_identifier
from helpers.value_sources import flush_all_value_sources


def main():
    # First, before the first question: at the end the crate records which state of the libraries
    # it was built against - that state has to be in a commit (helpers/git_functions.py, rule 2.4).
    ensure_libraries_committed()

    # Every run builds the crate anew from the answer file, the libraries and the data folders; a
    # series is continued by the answer file growing by the new experiment. Where it lies is settled
    # only with the identifier.
    datagraph = empty_datagraph()

    # Checks whether the root entities exist and creates them if not.
    # Also, dateModified is adjusted with every new run.
    ensure_root_entities(datagraph)

    todo_list = []

    # Devices and their contents in one view: Device and Material Library (rule 2.15).
    device_library, _ = load_device_libraries()
    people_library = load_jsonld(path_definitions.PEOPLE_LIBRARY_PATH)
    organization_library = load_jsonld(path_definitions.ORGANIZATION_LIBRARY_PATH)
    software_library = load_jsonld(path_definitions.SOFTWARE_LIBRARY_PATH)
    reaction_library = load_jsonld(path_definitions.REACTION_LIBRARY_PATH)
    chemical_entity_library = load_jsonld(path_definitions.CHEMICAL_ENTITY_LIBRARY_PATH)
    ontology_library = load_jsonld(path_definitions.ONTOLOGY_LIBRARY_PATH)
    assumption_library = load_jsonld(path_definitions.ASSUMPTION_LIBRARY_PATH)

    # What the run reads from the libraries without copying it into the crate it finds via
    # helpers/entities.py: resolve. At the end it is checked that it changed nothing there.
    for name, library in (("device_library", device_library), ("people_library", people_library),
                          ("organization_library", organization_library), ("software_library", software_library),
                          ("reaction_library", reaction_library), ("chemical_entity_library", chemical_entity_library),
                          ("ontology_library", ontology_library), ("assumption_library", assumption_library)):
        register_library(name, library)

    namespace_collection = initialize_ontologies()

    # From here on (almost) every question hangs under the scope segment "series:1" (see
    # helpers/user_io.py: question_path) - by decision of the project a crate contains exactly
    # one ExperimentalSeries (several series -> several crates), hence a fixed index instead of a
    # counter. Exceptions that deliberately start their question path anew with reset=True: the
    # "setup" questions at the very start of create_process (short name, how many experiments?,
    # see creation/experiment_functions.py) and the choice of hlo:Fixed reactions in
    # complete_all_reactions.
    with question_path("series", 1):

        number_series, number_experiments = create_process(datagraph, people_library, namespace_collection, todo_list,
                                                          reaction_library=reaction_library)

        print(f"{number_series} Experimental Series was created with {number_experiments} Experiments")

        create_all_contexts(number_series, number_experiments, namespace_collection, datagraph)

        # Media objects (files/images/videos + their columns) deliberately run BEFORE devices/
        # materials/phases/reactions - the series evidence/reference questions asked there later
        # choose from the columns recorded here per experiment, instead of describing any
        # themselves (see creation/media_object_functions.py).
        create_all_media_objects(namespace_collection, datagraph, todo_list, number_experiments, people_library)

        todo_list = create_all_devices(datagraph, device_library, namespace_collection, todo_list, number_experiments)

        todo_list_from_material_creation = create_all_materials(namespace_collection, datagraph, todo_list, number_experiments, device_library)
        todo_list = merge_todo_lists(todo_list, todo_list_from_material_creation)

        # Environments (surroundings/room air) are created only after the devices, because they are
        # derived automatically from their locatedInsideOf chain - no question of their own.
        todo_list_from_environment_creation = create_all_environments(namespace_collection, datagraph, todo_list, device_library, organization_library, number_experiments)
        todo_list = merge_todo_lists(todo_list, todo_list_from_environment_creation)

        # chemical_entity_library is handed through (chemical entities live there, not in the crate -
        # see chemical_entity_functions.py) and only read: new chemicals are created by a library
        # tool, not by the crate run.
        todo_list_from_phase_creation = complete_all_phases(namespace_collection, datagraph, chemical_entity_library, todo_list, number_experiments)
        todo_list = merge_todo_lists(todo_list, todo_list_from_phase_creation)

        # Reactions only AFTER the phases/interfaces, because occursInPhase/occursAtInterface can
        # point at them. reaction_library is only read (Fixed reactions live there, not in the crate -
        # see reaction_functions.py) - unlike the other libraries it is NOT saved back, new Fixed
        # reactions are maintained through a separate script (fill_reaction_library.py).
        todo_list_from_reaction_creation = complete_all_reactions(namespace_collection, datagraph, reaction_library, chemical_entity_library, todo_list, number_experiments)
        todo_list = merge_todo_lists(todo_list, todo_list_from_reaction_creation)

        # Occurrences only when everything that can occur is created (phases, transfers, reactions,
        # fields) - and before the tasks, which can refer to their times and evidence.
        todo_list_from_occurrences = ask_occurrences(namespace_collection, datagraph, chemical_entity_library, todo_list, number_experiments)
        todo_list = merge_todo_lists(todo_list, todo_list_from_occurrences)

        # Tasks come last, because they can refer to devices/phases/interfaces/streams/
        # transfers/reactions/ProcessVariables (usedEquipment, aimsAt, determines/hasInputValue,
        # actsOn, ...).
        todo_list_from_task_creation = complete_all_tasks(namespace_collection, datagraph, chemical_entity_library, people_library, todo_list, number_experiments)
        todo_list = merge_todo_lists(todo_list, todo_list_from_task_creation)

        # Use of the devices only after the tasks: only now do the procedures they were used in and
        # their times exist - the lists of evidence are asked for that beforehand ("last used"
        # follows the start of the experiment, rule 5.2).
        flush_all_value_sources()
        # Which task used up or disposed of the content of a container (rule 7.17)?
        emptied = ask_emptied_containers(datagraph, number_experiments)
        record_device_usage(namespace_collection, datagraph, number_experiments, emptied)

    # Evidence/reference lists that are still open (helpers/value_sources.py) - otherwise they are
    # asked as soon as the question path of their exemplar is left; here the rest is caught.
    flush_all_value_sources()

    # Ontology snapshot at the very end - only now is it settled which ontologies/vocabularies
    # actually occur in the finished datagraph (see creation/ontology_snapshot_functions.py).
    # ontology_library is only read, not saved back (like reaction_library - see there).
    # The root node last: only now are series, files and context structure complete - before,
    # the list would be incomplete (see creation/root_node_functions.py).
    link_root_parts(namespace_collection, datagraph)

    create_ontology_snapshot(namespace_collection, datagraph, ontology_library)

    # Rule 2.2: a library entity is not changed in the run, without exception (the use of the
    # devices is written by record_device_usage into a freshly loaded version of its own). Before
    # saving, so that none of it gets onto disk.
    check_libraries_unchanged()

    # Commit the libraries BEFORE the crate, then the commit is settled that contains everything the
    # crate refers to - and only then can it be entered. The run itself writes only the use of the
    # devices (record_device_usage, committed per experiment); it creates no new chemicals
    # (creation/chemical_entity_functions.py), so the Chemical Entity Library is not saved.
    if commit_library_changes(f"Libraries after crate {current_crate_identifier()}"):
        print("[libraries] Changes committed.")
    create_library_snapshot(namespace_collection, datagraph)

    # Counter-check of the @context set at the very start: now it is settled which prefixes the
    # crate really uses, and only now can it be said whether the table knows them all. A missing
    # entry makes no error - it makes an IRI meaningless (see verify_context_completeness).
    undeclared = verify_context_completeness(datagraph)
    if undeclared:
        print(f"\n[@context] WARNING: {len(undeclared)} prefix(es) are used in the crate, "
              f"but not declared in the @context: {', '.join(undeclared)}")
        print("[@context] Every ID under these prefixes stays an unresolvable relative IRI. "
              f"Add them to {path_definitions.PROJECT_CONTEXT_PATH.name} and build again.")

    # Continuing a series: what the crate contained already stays as it was (only references to
    # something new are added); the date of creation is that of the first run
    # (helpers/crate_continuation.py). If the answer file contradicts itself (an answer that was
    # not asked because of "the same for all?"), the run stops before anything is saved
    # (helpers/series_statements.py).
    check_series_contradictions()
    # In the run that completes the series: "Not known yet" that turned out to be the same goes to the series.
    hoist_on_completion(datagraph)

    # Contexts only when nothing more is changed in the content (not even by hoist_on_completion):
    # they follow from the shapes and the finished crate, never by hand (rule 6).
    crate_path = path_definitions.crate_path(current_crate_identifier())
    link_contexts_from_shapes(datagraph, crate_path)

    # A name for every entity of the crate that has none (RO-Crate recommends it; rule 1.4).
    name_unnamed_entities(datagraph, current_crate_identifier())
    keep_creation_date(datagraph, datetime.now(timezone.utc).isoformat())
    finish_root_dataset(datagraph, datetime.now(timezone.utc).isoformat())
    check_earlier_content_kept(datagraph)

    # RO-Crate 1.3: every key a term of the @context (helpers/file_handling.py: add_key_terms).
    add_key_terms(datagraph)
    save_jsonld(datagraph, crate_path)
    # The to-do list is worked through in the run and is empty at the end, so it is not put next to the
    # crate. If something is left after all, it stands there, so that it is not lost silently.
    todo_path = crate_path.parent / path_definitions.TODO_FILE_NAME
    if todo_list:
        save_todo_list(todo_list, todo_path)
        print(f"\n[todo] WARNING: {len(todo_list)} item(s) left on the to-do list - written to {todo_path}.")
    elif todo_path.exists():
        todo_path.unlink()

    print(f"\nRO-Crate saved as: {crate_path}")
    # A completed series moves to the archive and is only read from then on.
    archive_if_completed(datagraph, current_crate_identifier())

    report_unused_answer_keys()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    main()
