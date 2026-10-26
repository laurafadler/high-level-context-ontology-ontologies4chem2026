"""
What is known about the occurrences of phases, phase pair interfaces, transfers, reactions and
energy fields - asked in one place per experiment, once everything that can occur exists
(rule 3.1c).

Every one of them gets one occurrence per experiment when it is created
(helpers/time_occurrence.py: add_occurrence), with status and times unknown. Here each
experiment asks, per kind, which of them anything is known about - transfers first by the place
they happen at (interface or port), then by the transfers there - and for each one chosen how
many times it happened, 0 meaning it did not occur (record_occurrences). An empty list says
nothing is known; nothing is added then.
"""

from helpers.entities import as_list, ref_id
from helpers.identifiers import short_local_name
from helpers.time_occurrence import record_occurrences
from helpers.transfer_functions import transfer_name_of
from helpers.user_io import ask_user, ask_user_list, question_path

SCOPE = "hlo:ExperimentSpecific"


def _kind(entity: dict):
    """Which list an entity with an occurrence belongs to - read off its types."""
    types = [t.split(":", 1)[-1] for t in as_list(entity.get("@type"))]
    if "EnergyField" in types:
        return "energy_field"
    if "Transfer" in types:
        return "transfer"
    if "PhasePairInterface" in types:
        return "interface"
    if any(t.endswith("Reaction") for t in types):
        return "reaction"
    if any(t.endswith("Phase") for t in types):
        return "phase"
    raise ValueError(f"{entity['@id']} has an occurrence but is no phase, interface, transfer, reaction or energy field.")


def _in_experiment(entity: dict, nr: int) -> bool:
    return SCOPE in as_list(entity.get("@type")) and entity["@id"].endswith(f"_ExperimentSpecific_{nr}")


def _by_label(entities: list, label_fn, what: str) -> dict:
    labels = {label_fn(e): e for e in entities}
    if len(labels) != len(entities):
        raise ValueError(f"Two {what} share a name - the list could not tell them apart.")
    return labels


def _at_least_zero(text) -> int:
    value = int(str(text).strip())
    if value < 0:
        raise ValueError("0 or more")
    return value


_at_least_zero.__name__ = "whole number, 0 (did not occur) or more"


def _ask_count_and_record(entity: dict, label: str, nr: int, namespace_collection: dict, datagraph: dict, todo_list: list, local_todo_list: list):
    count = ask_user(f"[{SCOPE}] How many times did {label} occur in experiment {nr}? (0 = it did not occur)",
                     answer_type=_at_least_zero, question_id="number_of_occurrences")
    record_occurrences(entity, count, SCOPE, nr, namespace_collection, datagraph, todo_list, local_todo_list)


def _ask_simple_kind(kind: str, word: str, question_id: str, entities: list, nr: int, namespace_collection: dict, datagraph: dict, todo_list: list, local_todo_list: list):
    """Phases, reactions, energy fields: one list, then the count for each one chosen."""
    by_label = _by_label(entities, lambda e: short_local_name(e["@id"]), word)
    chosen = ask_user_list(
        f"[{SCOPE}] Which {word} do we know anything about - whether or how often they occurred in experiment {nr}? "
        f"Leave empty if nothing is known.", list(by_label), question_id=question_id)
    for label in chosen:
        with question_path(kind, label):
            _ask_count_and_record(by_label[label], label, nr, namespace_collection, datagraph, todo_list, local_todo_list)


def _ask_transfers(transfers: list, nr: int, namespace_collection: dict, datagraph: dict, chemical_entity_library: dict, todo_list: list, local_todo_list: list):
    """Transfers: first the places (interfaces and ports) anything is known about, then the
    transfers there, then the count for each."""
    by_place = {}
    for transfer in transfers:
        place = ref_id(transfer.get("cpo:occursAtInterface")) or ref_id(transfer.get("cpo:occursAtPort"))
        if place is None:
            raise ValueError(f"{transfer['@id']} has neither an interface nor a port.")
        by_place.setdefault(short_local_name(place), []).append(transfer)
    places = ask_user_list(
        f"[{SCOPE}] At which interfaces or ports do we know anything about whether transfers occurred in experiment {nr}? "
        f"Leave empty if nothing is known.", list(by_place), question_id="transfer_places")
    for place in places:
        with question_path("place", place):
            by_name = _by_label(by_place[place], lambda e: transfer_name_of(e, datagraph, chemical_entity_library), f"transfers at {place}")
            chosen = ask_user_list(f"[{SCOPE}] Which transfers at {place} do we know anything about in experiment {nr}?",
                                   list(by_name), question_id="transfers", required=True)
            for name in chosen:
                with question_path("transfer", name):
                    _ask_count_and_record(by_name[name], name, nr, namespace_collection, datagraph, todo_list, local_todo_list)


def ask_occurrences(namespace_collection: dict, datagraph: dict, chemical_entity_library: dict, todo_list: list, number_experiments: int) -> list:
    """Ask per experiment what is known about the occurrences, and record it."""
    local_todo_list = []
    with_occurrence = [e for e in datagraph.get("@graph", []) if "cpo:hasOccurrence" in e]
    for nr in range(1, number_experiments + 1):
        by_kind = {"phase": [], "interface": [], "transfer": [], "reaction": [], "energy_field": []}
        for entity in with_occurrence:
            if _in_experiment(entity, nr):
                by_kind[_kind(entity)].append(entity)
        with question_path("experiment", nr), question_path("occurrences"):
            if by_kind["phase"]:
                _ask_simple_kind("phase", "phases", "phases", by_kind["phase"], nr, namespace_collection, datagraph, todo_list, local_todo_list)
            # Whether and when two phases touched (lid off, cap off).
            if by_kind["interface"]:
                _ask_simple_kind("interface", "phase interfaces", "interfaces", by_kind["interface"], nr, namespace_collection, datagraph, todo_list, local_todo_list)
            if by_kind["transfer"]:
                _ask_transfers(by_kind["transfer"], nr, namespace_collection, datagraph, chemical_entity_library, todo_list, local_todo_list)
            if by_kind["reaction"]:
                _ask_simple_kind("reaction", "reactions", "reactions", by_kind["reaction"], nr, namespace_collection, datagraph, todo_list, local_todo_list)
            if by_kind["energy_field"]:
                _ask_simple_kind("energy_field", "energy fields", "energy_fields", by_kind["energy_field"], nr, namespace_collection, datagraph, todo_list, local_todo_list)
    return local_todo_list
