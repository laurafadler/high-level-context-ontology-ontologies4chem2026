"""
Usage history of the devices: which procedure a device was last used in, and when.

Ordered by time, not by the order in which crates were built (rules 5.2-5.4): otherwise a crate
built later would turn up as the last use before an earlier one. So:

- The history in the library is kept sorted by time: a new use is sorted in where it belongs -
  usually at the end, and only then does cpo:lastUsedTime change. Every entry has a moment: the
  end of its task, or its start where the end is not known; it is looked up only where needed,
  walking from the end of the history. The start of every experimental procedure is required (creation/task_functions.py:
  _required_times); a library task (the commissioning, rule 5.5) has its own times. An entry
  without any moment stops the run - it cannot be placed (nothing is assumed silently; an
  assumption is a reference of type Assumed).
- "Last used" of a device in the crate is the latest entry that lies before the start of the
  experiment - for the series level before the start of experiment 1. cpo:lastUsedPurpose points
  at that task, cpo:lastUsedTime at its end (rule 5.2: a reference to a moment
  that exists, no own Actual). Entries of this crate count like any other: experiment 2 finds
  experiment 1 if it came before.
- Into the device library (every device, also a container of the chemical inventory), after the
  task stage: the procedures of this crate are sorted into
  cpo:hasUsageHistory by time, and cpo:lastUsedTime (and cpo:lastUsedPurpose, where the entry
  has one) point at the latest entry. Both are links into the crate (crate:<identifier>/...),
  not copies. A procedure already in the history is not added again, so building
  a crate again changes nothing.

Which procedure a device was used in is read from the content, not from a name: the
procedure of the experiment (cpo:hasProcedure) whose part tree (dcterms:hasPart) holds a task
that uses the device (cpo:usedInTask).
"""

from datetime import datetime, timezone

import path_definitions
from helpers.entities import find_entity, as_list, ref_id, ref_ids, ask_entity_list
from helpers.file_handling import load_jsonld, save_jsonld
from helpers.git_functions import commit_library_changes
from helpers.library_functions import load_device_libraries
from helpers.inventory_state import (content_end, set_content_end, clear_content_end, content_history,
                                     occurrence_of_content, crate_library_content, release_content, restore_content)
from helpers.identifiers import get_display_label, CRATE_NAMESPACE_PREFIX, current_crate_identifier
from helpers.user_io import question_path
from helpers.properties import set_property


def _commit_mention(identifier: str) -> str:
    # Stands in every commit message this crate leaves in the libraries - that is how
    # helpers/crate_continuation.py recognizes that an identifier was used already.
    return f"crate {identifier}"


def _own_prefix(identifier: str) -> str:
    return f"{CRATE_NAMESPACE_PREFIX}:{identifier}/"


class _Moments:
    """Finds tasks and the moments of their times wherever they are described: in this crate, in
    the device library, or in the crate an earlier use was recorded in (open or completed)."""

    def __init__(self, datagraph: dict, device_library: dict):
        self.graphs = [datagraph, device_library]
        self.crates = {}

    def _other_crate(self, entity_id: str) -> dict:
        other = entity_id[len(CRATE_NAMESPACE_PREFIX) + 1:].split("/", 1)[0]
        if other not in self.crates:
            self.crates[other] = {"@graph": []}
            for path in (path_definitions.crate_path(other),
                         path_definitions.archived_crate_folder(other) / path_definitions.CRATE_FILE_NAME):
                if path.exists():
                    self.crates[other] = load_jsonld(path)
                    break
        return self.crates[other]

    def find(self, entity_id: str) -> dict | None:
        # An entry of another crate first there: in this crate it has at most a type stub without
        # times (add_reference_stub), as soon as a device points at it.
        own = _own_prefix(current_crate_identifier() or "")
        if entity_id.startswith(f"{CRATE_NAMESPACE_PREFIX}:") and not entity_id.startswith(own):
            entity = find_entity(self._other_crate(entity_id), entity_id)
            if entity is not None:
                return entity
        for graph in self.graphs:
            entity = find_entity(graph, entity_id)
            if entity is not None:
                return entity
        if entity_id.startswith(f"{CRATE_NAMESPACE_PREFIX}:"):
            return find_entity(self._other_crate(entity_id), entity_id)
        return None

    def value(self, instant_id: str | None) -> datetime | None:
        """The moment of a time:Instant - from its evidence, else its reference (rdf:value)."""
        instant = self.find(instant_id) if instant_id else None
        if instant is None:
            return None
        for source_id in ref_ids(instant.get("hlo:hasEvidence")) + ref_ids(instant.get("hlo:hasReference")):
            source = self.find(source_id) or {}
            raw = source.get("rdf:value")
            raw = raw.get("@value") if isinstance(raw, dict) else raw
            if not raw:
                continue
            moment = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            # Without a time zone (such as from an ELN export) UTC holds - only times with a zone are compared.
            return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
        return None

    def of_task(self, task_id: str) -> datetime | None:
        """When a task of a history took place: its end, or its start where the end is not known."""
        task = self.find(task_id) or {}
        return self.value(ref_id(task.get("cpo:hasEndTime"))) or self.value(ref_id(task.get("cpo:hasStartTime")))


def _is_single_use(twin: dict) -> bool:
    return any(value is True for value in as_list(twin.get("cpo:isSingleUse")))


def _library_twin_id(device: dict, datagraph: dict) -> str | None:
    """The library entry a crate device specializes, up the hlo:specializationOf chain. None for an
    entity that specializes several things at once (a context aspect) - no device does."""
    seen = set()
    current = device
    while current is not None and current["@id"] not in seen:
        seen.add(current["@id"])
        parents = ref_ids(current.get("hlo:specializationOf"))
        if len(parents) != 1:
            return None
        parent = parents[0]
        if not parent.startswith(_own_prefix(current_crate_identifier() or "")):
            return parent
        current = find_entity(datagraph, parent)
    return None


def _task_tree(task_id: str, datagraph: dict) -> set:
    found, stack = {task_id}, [task_id]
    while stack:
        task = find_entity(datagraph, stack.pop())
        for part in ref_ids((task or {}).get("dcterms:hasPart")):
            if part not in found:
                found.add(part)
                stack.append(part)
    return found


def _usage_procedure(device: dict, experiment: dict, datagraph: dict) -> dict | None:
    """The procedure of the experiment in which the device was used, or None."""
    tasks = set(ref_ids(device.get("cpo:usedInTask")))
    found = [ref for ref in ref_ids(experiment.get("cpo:hasProcedure")) if tasks & _task_tree(ref, datagraph)]
    if len(found) > 1:
        print(f"[usage history] {device['@id']} is used in more than one procedure of {experiment['@id']} - taking {found[0]}.")
    return find_entity(datagraph, found[0]) if found else None


def _experiment_devices(experiment_number: int, datagraph: dict) -> list:
    """The experiment-level devices of one experiment: the entities that carry usage (cpo:usedInTask)
    and specialize a library device."""
    suffix = f"_ExperimentSpecific_{experiment_number}"
    return [entity for entity in datagraph.get("@graph", [])
            if entity.get("@id", "").endswith(suffix) and "cpo:usedInTask" in entity
            and "hlo:ExperimentSpecific" in as_list(entity.get("@type"))
            and _library_twin_id(entity, datagraph) is not None]


def _experiment_number(entity_id: str) -> int | None:
    """The experiment an experiment-level ID belongs to (..._ExperimentSpecific_2 -> 2)."""
    tail = entity_id.rsplit("_ExperimentSpecific_", 1)
    return int(tail[1]) if len(tail) == 2 and tail[1].isdigit() else None


def _experiment_start(experiment: dict, datagraph: dict, moments: _Moments) -> datetime:
    """The start of the experimental procedure of an experiment - required (rule 5.6)."""
    from creation.task_functions import PROCEDURE_TASK_NAME, _is_shell
    for procedure_id in ref_ids(experiment.get("cpo:hasProcedure")):
        procedure = find_entity(datagraph, procedure_id)
        if procedure is not None and _is_shell(procedure, PROCEDURE_TASK_NAME):
            start = moments.value(ref_id(procedure.get("cpo:hasStartTime")))
            if start is not None:
                return start
    raise RuntimeError(f"{experiment['@id']}: the start of its experimental procedure has no value - "
                       "it is required, the usage history of the devices is ordered by it (rule 5.6).")


def _moment(twin_id: str, entry_id: str, moments: _Moments) -> datetime:
    """When an entry of a history took place. An entry without a moment stops the run."""
    moment = moments.of_task(entry_id)
    if moment is None:
        raise RuntimeError(
            f"The usage history of {twin_id} holds {entry_id}, but neither its end nor its start has a "
            "value, so it cannot be placed in time (rule 5.3). Give that task a time - in its own crate, or "
            "as a reference of type Assumed - then run again.")
    return moment


def _last_before(twin_id: str, history: list, start: datetime, moments: _Moments) -> str | None:
    """The latest entry of a history (sorted by time) before start - walked from the end, so that
    the usual case, an experiment after every recorded use, reads one entry only."""
    for entry_id in reversed(history):
        if _moment(twin_id, entry_id, moments) < start:
            return entry_id
    return None


def _sort_in(twin_id: str, history: list, entry_id: str, moments: _Moments) -> list:
    """The history with entry_id sorted in by time - usually appended at the end."""
    if entry_id in history:
        return history
    moment = _moment(twin_id, entry_id, moments)
    position = len(history)
    while position > 0 and _moment(twin_id, history[position - 1], moments) > moment:
        position -= 1
    return history[:position] + [entry_id] + history[position:]


def record_device_usage(namespace_collection: dict, datagraph: dict, number_experiments: int, emptied: dict = None):
    """Point every device of the crate at its last use before the series or experiment, and sort
    the procedures of this crate into the usage history of the device library (one commit). The
    contents this crate used up (emptied, from ask_emptied_containers) end in the material library."""
    from creation.device_functions import add_reference_stub
    identifier = current_crate_identifier()
    # The library is read freshly from disk: the current file is written, not the version the
    # run read (rule 2.2). Devices and containers of the chemical store in one view (rule 2.15); every
    # file is written back on its own.
    device_library, documents = load_device_libraries()
    moments = _Moments(datagraph, device_library)
    experiments = {number: find_entity(datagraph, _experiment_id(datagraph, number))
                   for number in range(1, number_experiments + 1)}
    starts = {number: _experiment_start(experiment, datagraph, moments)
              for number, experiment in experiments.items() if experiment is not None}

    # The procedures of this crate in which a library device was used (not single-use items).
    own_uses = {}
    used_in = {}   # library device -> experiments it was used in
    for number, experiment in experiments.items():
        if experiment is None:
            continue
        for device in _experiment_devices(number, datagraph):
            twin_id = _library_twin_id(device, datagraph)
            twin = find_entity(device_library, twin_id)
            if twin is None or _is_single_use(twin):
                continue
            procedure = _usage_procedure(device, experiment, datagraph)
            if procedure is None:
                print(f"[usage history] No procedure of {experiment['@id']} uses {device['@id']} - nothing recorded.")
                continue
            own_uses.setdefault(twin_id, []).append(procedure["@id"])
            used_in.setdefault(twin_id, set()).add(number)

    # The history of the library is sorted by time; the procedures of this crate are filed in.
    histories = {}
    for twin in device_library.get("@graph", []):
        history = ref_ids(twin.get("cpo:hasUsageHistory"))
        for entry_id in own_uses.get(twin["@id"], []):
            history = _sort_in(twin["@id"], history, entry_id, moments)
        if history:
            histories[twin["@id"]] = history

    # In the crate: every device whose library entry has a history - the series before experiment 1,
    # every experiment before its start.
    for device in datagraph.get("@graph", []):
        types = as_list(device.get("@type"))
        if "hlo:SeriesSpecific" not in types and "hlo:ExperimentSpecific" not in types:
            continue
        twin_id = _library_twin_id(device, datagraph)
        if twin_id not in histories:
            continue
        number = _experiment_number(device["@id"]) if "hlo:ExperimentSpecific" in types else 1
        start = starts.get(number)
        if start is None:
            continue
        entry = _last_before(twin_id, histories[twin_id], start, moments)
        if entry is None:
            print(f"[usage history] Warning: {device['@id']} has no use recorded before {start.isoformat()} - "
                  f"the history of {twin_id} starts later (rule 5.5: the commissioning comes first).")
            continue
        set_property(device, "cpo:lastUsedPurpose", {"@id": entry}, namespace_collection)
        end_time = ref_id((moments.find(entry) or {}).get("cpo:hasEndTime"))
        if end_time:
            set_property(device, "cpo:lastUsedTime", {"@id": end_time}, namespace_collection)
        # A task or a point in time of an earlier crate is not described here, only its type is named
        # (rule 3.2a) - a task of the library is present when validating.
        if entry.startswith(f"{CRATE_NAMESPACE_PREFIX}:") and not entry.startswith(_own_prefix(identifier)):
            add_reference_stub(entry, "cpo:Task",
                               "Cross-crate reference: this task was carried out in an earlier crate, it is not "
                               "described here. Only its type is asserted, so that the usage history of a device "
                               "can be followed from this crate.", datagraph, namespace_collection)
            if end_time:
                add_reference_stub(end_time, "time:Instant",
                                   "Cross-crate reference: this moment lies in an earlier crate, it is not described "
                                   "here. Only its type is asserted, so that the history of a device can be followed "
                                   "from this crate.", datagraph, namespace_collection)

    # In the library: write back the history with the entries filed in, and the pointer to the last
    # entry - it changes only if something was appended. A repeated run writes nothing.
    for twin_id in own_uses:
        twin = find_entity(device_library, twin_id)
        ordered = histories[twin_id]
        latest = ordered[-1]
        twin["cpo:hasUsageHistory"] = [{"@id": entry} for entry in ordered]
        end_time = ref_id((moments.find(latest) or {}).get("cpo:hasEndTime"))
        if end_time:
            twin["cpo:lastUsedTime"] = {"@id": end_time}
        if "cpo:lastUsedPurpose" in twin:
            twin["cpo:lastUsedPurpose"] = {"@id": latest}

    # Contents of the chemical store this crate used up (rule 7.17) - checks before writing.
    _settle_content_ends(identifier, device_library, documents, emptied or {}, used_in, starts, moments, datagraph)

    for path, document in documents.items():
        save_jsonld(document, path)
    if commit_library_changes(f"Usage history of {_commit_mention(identifier)}"):
        print(f"[usage history] Usage of crate {identifier} committed to the device and material libraries.")


class InventoryContentError(RuntimeError):
    """A content of the inventory is drawn from after it was used up or disposed of."""


def _inventory_content(device: dict, datagraph: dict, view: dict):
    """(library container id, the acquisition occurrence of the content this crate drew from) for a
    crate device whose library entry is a container of the inventory with a content; else
    (None, None). The content is the one the crate's copy specializes - with several contents in the
    history of the container not necessarily the current one (rule 2.15)."""
    twin_id = _library_twin_id(device, datagraph)
    twin = find_entity(view, twin_id) if twin_id else None
    if twin is None or "cpo:ChemicalContainer" not in as_list(twin.get("@type")):
        return None, None
    drawn = crate_library_content(device, datagraph, content_history(twin))
    occurrence = occurrence_of_content(drawn, view) if drawn else None
    return (twin_id, occurrence) if occurrence is not None else (None, None)


def _drawn_contents(datagraph: dict, view: dict) -> dict:
    """{library container id: the library content this crate drew from} - read off the crate's
    devices (every level names the same one)."""
    drawn = {}
    for device in datagraph.get("@graph", []):
        types = as_list(device.get("@type"))
        if "hlo:SeriesSpecific" not in types and "hlo:ExperimentSpecific" not in types:
            continue
        twin_id = _library_twin_id(device, datagraph)
        twin = find_entity(view, twin_id) if twin_id else None
        if twin is None or "cpo:ChemicalContainer" not in as_list(twin.get("@type")):
            continue
        content_id = crate_library_content(device, datagraph, content_history(twin))
        if content_id:
            drawn[twin_id] = content_id
    return drawn


def ask_emptied_containers(datagraph: dict, number_experiments: int) -> dict:
    """Which task used up or disposed of the content of a container of the inventory (rule 7.17):
    asked for every task of an experiment that uses such a container
    (series:1/experiment:<n>/task:<key>/empties; the setup sheet says it with "empties" at the task).
    Returns {library container id: (experiment number, crate task id)}."""
    from creation.task_functions import task_question_key
    view, _ = load_device_libraries()
    emptied = {}
    for number in range(1, number_experiments + 1):
        suffix = f"_ExperimentSpecific_{number}"
        tasks = sorted((e for e in datagraph.get("@graph", []) if e.get("@id", "").endswith(suffix) and "cpo:usedEquipment" in e),
                       key=lambda e: e["@id"])
        with question_path("experiment", number):
            for task in tasks:
                containers = [device for device in (find_entity(datagraph, i) for i in ref_ids(task.get("cpo:usedEquipment")))
                              if device is not None and _inventory_content(device, datagraph, view)[0]]
                if not containers:
                    continue
                with question_path("task", task_question_key(task, datagraph)):
                    chosen = ask_entity_list(
                        f"[hlo:ExperimentSpecific] Did {get_display_label(task)} use up or dispose of the content of any of "
                        f"these containers in experiment {number}? Leave empty if not.",
                        containers, question_id="empties")
                for device_id in chosen:
                    twin_id = _inventory_content(find_entity(datagraph, device_id), datagraph, view)[0]
                    if twin_id in emptied:
                        raise InventoryContentError(
                            f"The content of {twin_id} is marked as used up twice - by {emptied[twin_id][1]} and by "
                            f"{task['@id']}. Fix the 'empties' mark.")
                    emptied[twin_id] = (number, task["@id"])
    return emptied


def _settle_content_ends(identifier: str, view: dict, documents: dict, emptied: dict, used_in: dict, starts: dict,
                         moments: _Moments, datagraph: dict):
    """The end of the contents this crate uses up (rule 7.17), written into the material library like
    the usage history: what this crate wrote before is taken out first, so building it again changes
    nothing (rule 5.4). Stops the run - before anything is written - when a content is drawn from after
    it ended."""
    own = _own_prefix(identifier)
    # Take out the own ends - at every content of the history, not only at the current one; a last
    # content open again in this way is the current one again (rule 2.15).
    for container in view.get("@graph", []):
        if "cpo:ChemicalContainer" not in as_list(container.get("@type")):
            continue
        for material_id in content_history(container):
            occurrence = occurrence_of_content(material_id, view)
            if occurrence is not None and (content_end(occurrence) or "").startswith(own):
                clear_content_end(occurrence, view, documents)
                restore_content(container, find_entity(view, material_id))

    def when(number):
        return starts[number].strftime("%Y-%m-%d %H:%M")

    drawn = _drawn_contents(datagraph, view)

    # The content the series draws from must have been there at the start of every experiment
    # (when rebuilding after a refill, for experiments documented afterwards).
    for twin_id, numbers in used_in.items():
        occurrence = occurrence_of_content(drawn[twin_id], view) if twin_id in drawn else None
        since = moments.value(ref_id(occurrence.get("cpo:hasStartTime"))) if occurrence is not None else None
        if since is None:
            continue
        early = sorted(n for n in numbers if n in starts and starts[n] < since)
        if early:
            raise InventoryContentError(
                f"The series draws from {drawn[twin_id]} in {twin_id}, which is there only since "
                f"{since.strftime('%Y-%m-%d %H:%M')}; experiment {early[0]} started before ({when(early[0])}). Choose the "
                f"content it held then (question 'library_content' of the device) or another container.")

    # Ended already (an earlier crate, the store tool): no experiment after it may draw from it.
    for twin_id, numbers in used_in.items():
        occurrence = occurrence_of_content(drawn[twin_id], view) if twin_id in drawn else None
        end = content_end(occurrence) if occurrence is not None else None
        if not end:
            continue
        moment = moments.value(end)
        if moment is None:
            print(f"[inventory] Warning: the content of {twin_id} ended at {end}, which has no value - "
                  f"whether this crate draws from it afterwards cannot be checked.")
            continue
        late = sorted(n for n in numbers if n in starts and starts[n] >= moment)
        if late:
            raise InventoryContentError(
                f"The content of {twin_id} ended on {moment.strftime('%Y-%m-%d %H:%M')} ({end}); experiment {late[0]} "
                f"(started {when(late[0])}) draws from it again. Fix the 'empties' mark, choose another container, "
                f"or enter its refill as a new content in the material library.")

    # Used up in this crate: no later experiment may still draw from it.
    for twin_id, (number, task_id) in sorted(emptied.items()):
        later = sorted(n for n in used_in.get(twin_id, ()) if n in starts and number in starts and starts[n] > starts[number])
        if later:
            raise InventoryContentError(
                f"The content of {twin_id} was used up by {task_id} in experiment {number} ({when(number)}); experiment "
                f"{later[0]} draws from it again. Fix the 'empties' mark, choose another container, or enter its "
                f"refill as a new content in the material library.")
        occurrence = occurrence_of_content(drawn[twin_id], view)
        if content_end(occurrence):
            raise InventoryContentError(
                f"The content of {twin_id} is marked as used up by {task_id} in experiment {number}, but it ended "
                f"already at {content_end(occurrence)}. Fix the 'empties' mark or the material library.")
        end_time = ref_id((find_entity(datagraph, task_id) or {}).get("cpo:hasEndTime"))
        set_content_end(occurrence, end_time, view, documents)
        # Used up: the container no longer contains it (rule 2.15), it stays in the history.
        release_content(find_entity(view, twin_id), find_entity(view, drawn[twin_id]))
        print(f"[inventory] The content of {twin_id} ends with {task_id} (experiment {number}).")


def _experiment_id(datagraph: dict, number: int) -> str | None:
    wanted = f"SingleExperiment_{number}"
    for entity in datagraph.get("@graph", []):
        if "cpo:SingleExperiment" in as_list(entity.get("@type")) and entity["@id"].endswith(wanted):
            return entity["@id"]
    return None
