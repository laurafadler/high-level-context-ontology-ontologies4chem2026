"""
The experimental series and its experiments - the first entities of every crate.

create_process asks the setup questions (short name of the series, number of conducted and planned
experiments, completed or not), decides whether a new series starts or an open one is continued
(helpers/crate_continuation.py), and creates the series with one cpo:SingleExperiment per conducted
experiment: name, description, creators and experimenters (rules 7c.3, 7c.4) and the ELN record that
describes each experiment (rule 4a.5). A single experiment is a series with one experiment.
"""

from helpers.entities import add_entity, find_entity
from helpers.identifiers import crate_id, crate_identifier, set_crate_identifier
from helpers.properties import set_property, check_type
from helpers.library_functions import get_id_list
from helpers.user_io import ask_user, ask_user_list, question_path, SAME_OPTIONS
from helpers.crate_continuation import start_crate


def ask_people(people_library: dict, prompt: str, question_id: str) -> list:
    """One or more people of the library, asked as one list (like the performers of a task)."""
    names = ask_user_list(prompt, get_id_list(people_library, "person:", "schema:Person"), question_id=question_id, required=True)
    people = []
    for name in names:
        person = find_entity(people_library, f"person:{name}")
        if person is None:
            raise RuntimeError(f"No entry for {name} in libraries/people_library.jsonld - the crate would point at nothing.")
        people.append(person)
    return people


NO_ELN_RECORD = "No ELN record"


def ask_eln_record(reaction_library: dict, x: int):
    """The record of an ELN that describes Experiment x - an entry (schema:Dataset) of the Reaction
    Library - or None when there is none."""
    records = get_id_list(reaction_library or {}, "reaction:", "schema:Dataset")
    answer = ask_user(f"Which ELN record describes Experiment {x}? (The records are entries of the Reaction Library.)",
                      records + [NO_ELN_RECORD], question_id="eln_record", required=True)
    if answer == NO_ELN_RECORD:
        return None
    record = find_entity(reaction_library, f"reaction:{answer}")
    if record is None:
        raise RuntimeError(f"No entry for {answer} in libraries/reaction_library.jsonld - the crate would point at nothing.")
    return record


def planned_number(text):
    """The planned number of experiments: a positive whole number, or None when the answer is
    empty (not known). Used as answer_type of ask_user."""
    text = str(text).strip()
    if not text:
        return None
    number = int(text)
    if number < 1:
        raise ValueError(f"{number} is not a planned number of experiments")
    return number


planned_number.__name__ = "whole number, or empty if not known"


def create_series(datagraph: dict, people_library: dict, x: int, namespace_collection: dict, todo_list, short_name: str,
                  planned: int = None, completed: bool = False, reaction_library: dict = None):
    entity_type = check_type("cpo:ExperimentalSeries", namespace_collection)
    # A crate contains exactly one series - its ID needs no number; which series it is is said
    # by the prefix of the crate (the identifier from the short name).
    entity_id = crate_id("ExperimentalSeries")

    series = {
            "@id": entity_id,
            "@type": entity_type,
        }

    # People (rule 7c.4): the series always has its creators; whether the experiments have the same ones
    # is only a shortcut of the input - every experiment always gets its people itself. The
    # experimenters of the series are all who performed its experiments.
    creators = ask_people(people_library, "Who created (planned) the experimental series?", "series_creator")
    same_creator = ask_user("Were all experiments of the series created (planned) by the same person(s) as the series?",
                            SAME_OPTIONS, question_id="same_creator_for_all_experiments") == "Yes"
    same_experimenter = ask_user("Were all experiments of the series performed by the same person(s)?",
                                 SAME_OPTIONS, question_id="same_experimenter_for_all_experiments") == "Yes"
    series_experimenters = ask_people(people_library, "Who performed the experiments of the series?", "series_experimenter") if same_experimenter else None

    set_property(series, "schema:name", short_name, namespace_collection)
    # Asked, not a placeholder; empty: no description.
    description = ask_user("Please describe the experimental series - what is done, with what aim, and where its record "
                           "comes from (leave empty to skip)?", question_id="series_description")
    if description.strip():
        set_property(series, "schema:description", description.strip(), namespace_collection)
    for creator in creators:
        set_property(series, "cpo:hasCreator", creator, namespace_collection, True)
    # The series as a project: the planned number (missing if unknown) and whether it is completed.
    # How many experiments have been performed is not stated separately - they are its parts.
    if planned is not None:
        set_property(series, "cpo:hasNumberOfPlannedExperiments", planned, namespace_collection)
    set_property(series, "cpo:isCompleted", completed, namespace_collection)

    add_entity(datagraph, series)

    experimenters = []
    for i in range(x):
        with question_path("experiment", i + 1):
            for person in create_experiment(datagraph, series, i+1, people_library, namespace_collection, todo_list,
                                            creators if same_creator else None, series_experimenters,
                                            reaction_library=reaction_library):
                if person not in experimenters:
                    experimenters.append(person)
    for person in experimenters:
        set_property(series, "cpo:hasExperimenter", person, namespace_collection, True)

    return


def create_experiment(datagraph: dict, series: dict, x: int, people_library: dict, namespace_collection: dict, todo_list: list, creators: list = None, experimenters: list = None,
                      reaction_library: dict = None):
    # Create an experiment of the series - a single experiment is a series with one experiment.
    entity_type = check_type("cpo:SingleExperiment", namespace_collection)
    # The experiment number is the identity here (experiment 1, experiment 2) - it stands for
    # the thing, not for the order in which the entity was made.
    entity_id = crate_id(f"SingleExperiment_{x}")

    experiment = {
            "@id": entity_id,
            "@type": entity_type,
        }

    name = f"Experiment {x}"
    set_property(experiment, "schema:name", name, namespace_collection)

    description = f"Experiment Nr {x} of the experimental series"
    set_property(experiment, "schema:description", description, namespace_collection)

    # People always stand at the experiment itself (rule 7c.4). Passed in if the series said "the same
    # for all", otherwise asked here.
    creators = creators if creators is not None else ask_people(people_library, f"Who created (planned) Experiment {x}?", "creator")
    experimenters = experimenters if experimenters is not None else ask_people(people_library, f"Who performed Experiment {x}?", "experimenter")
    for creator in creators:
        set_property(experiment, "cpo:hasCreator", creator, namespace_collection, True)
    for experimenter in experimenters:
        set_property(experiment, "cpo:hasExperimenter", experimenter, namespace_collection, True)

    # The ELN record that describes the experiment (rule 4a.5): like the library entries imported
    # from it, the experiment points at it with schema:subjectOf - that is how one gets from the crate to the ELN.
    record = ask_eln_record(reaction_library, x)
    if record is not None:
        set_property(experiment, "schema:subjectOf", record, namespace_collection, True)

    # cpo:hasSOP and cpo:hasRiskAssessment are not set (docs/things_to_implement_after_me.md).
    set_property(experiment, "dcterms:isPartOf", series, namespace_collection)
    set_property(series, "dcterms:hasPart", experiment, namespace_collection, True)

    # Added later by the entities themselves: hasProcedure, generatesMediaObject.
    add_entity(datagraph, experiment)

    return experimenters


def create_process(datagraph: dict, people_library: dict, namespace_collection: dict, todo_list: list, reaction_library: dict = None):
    # Always a series: ask how many experiments are part of it. A single experiment is a series
    # with one experiment, and that way the series can be continued later.

    # Ask the user - "setup" scope (see helpers/user_io.py): the only questions of the whole
    # run that stand BEFORE every scope (series/experiment/Fixed). reset=True, so that they do
    # NOT hang under "series:1", although create_process is already called by main.py within
    # this scope (see main.py).
    with question_path("setup", reset=True):
        # The short name first: it becomes the identifier in the prefix of EVERY crate ID
        # (crate:<crate_identifier>/...), so it must be settled before the first ID is made.
        short_name = ask_user("Short name of the experimental series? It becomes the identifier of this crate, e.g. hydrogenation_rdy_2026_09.", answer_type=crate_identifier, question_id="series_short_name")
        set_crate_identifier(short_name)
        # A new series or the continuation of an open one? Decided by the folders, before the first
        # ID is made (helpers/crate_continuation.py).
        start_crate(short_name)

        # Performed and planned separately: a crate is continued experiment by experiment. Only the
        # performed experiments are made.
        number_experiments = ask_user("How many experiments of the series have been conducted so far (they are all described in this crate)?",
                                      answer_type=int, question_id="number_of_conducted_experiments")
        planned = ask_user("How many experiments are planned for the series in total? Leave empty if that is not known.",
                           answer_type=planned_number, question_id="number_of_planned_experiments")
        if planned is not None and number_experiments > planned:
            raise ValueError(f"{number_experiments} experiments conducted, but only {planned} planned - "
                             "correct setup/number_of_conducted_experiments or setup/number_of_planned_experiments.")
        if planned is None:
            completed = ask_user("Is the series completed - will no further experiment be added?", ["Yes", "No"],
                                 question_id="series_completed") == "Yes"
        else:
            completed = number_experiments == planned

    # Create x experiments and a series - a crate contains exactly one series (main.py).
    number_series = 1
    create_series(datagraph, people_library, number_experiments, namespace_collection, todo_list, short_name,
                  planned=planned, completed=completed, reaction_library=reaction_library)

    return number_series, number_experiments

