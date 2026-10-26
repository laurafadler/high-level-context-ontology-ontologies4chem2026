"""
Shared helpers for time (hasStartTime/hasEndTime/hasDuration) and occurrence
(cpo:hasOccurrence) - used by transfers, reactions and tasks, in each case only at
hlo:ExperimentSpecific level (at series level these are potential events or templates
without a time or an occurrence).

Follows exactly the Actual/Reference/Evidence pattern of
helpers/process_variables.py (add_phase_process_variable): an empty "hlo:Actual" entity
is created and linked, while the value itself (when known) hangs off an evidence and/or
reference entity, never off the Actual. No reasoner: every link is set explicitly in
both directions.
"""

from helpers.entities import add_entity, find_entity, ref_id, ref_ids, as_list, resolve, library_holders
from helpers.properties import set_property, check_type
from helpers.identifiers import generate_id_from_name, short_local_name, get_display_label
from helpers.evidence_reference import add_evidence, add_reference, occurrence_value_preset
from helpers.value_sources import request_value_sources
from helpers.user_io import question_path, ask_user


def add_time_entities(entity: dict, scope: str, nr: int, namespace_collection: dict, datagraph: dict, todo_list: list, local_todo_list: list, evidence_known_cache: dict = None, property_names=None, allow_series: bool = False, on: dict = None, id_base: str = None, register: bool = True,
                      required: tuple = ()):
    """Create cpo:hasStartTime/cpo:hasEndTime (each a time:Instant) and
    cpo:hasDuration (a time:Duration) where they do not exist yet - at
    hlo:ExperimentSpecific level only.

    Each of the three is asked about separately; recording two of them is enough, the
    third is NOT calculated automatically.

    property_names limits which of the three are asked for; None means all of them. No caller
    limits them at the moment: every task gets all three (rule 4.6), assumptions
    included - an unknown end or duration is an empty hlo:Actual, not a missing property.

    Each of the three gets its own question_path segment
    ("start_time"/"end_time"/"duration") - otherwise the generic
    add_evidence/add_reference questions (see helpers/evidence_reference.py) would
    produce the same key for all three.

    on: the entity the times belong to, when it is not the exemplar itself - the occurrence of a
    phenomenon or a phase (add_occurrence). The IDs and the questions stay
    those of the exemplar (entity): the times of a transfer are asked in its lists as before.

    id_base: the name the IDs of the times are built from - by default the exemplar's; a further
    occurrence (add_numbered_occurrence) passes its own, so that its times do not collide with
    those of the first.

    register=False creates the times without offering them in the value lists of the exemplar:
    the times of an occurrence are asked where its occurrences are (record_occurrences).

    required: the properties that need a value (helpers/value_sources.py) - the start of the
    experimental procedure (creation/task_functions.py: _required_times).
    """
    target = on if on is not None else entity
    if id_base is None:
        id_base = short_local_name(entity["@id"])
    # allow_series: a series entity is otherwise always a template - the same procedure across
    # the whole series -, and a template has no point in time. The planning of the series is the
    # exception: it really took place once (see creation/task_functions.py:
    # _wants_series_times).
    if scope != "hlo:ExperimentSpecific" and not allow_series:
        return

    time_properties = [
        ("cpo:hasStartTime", "time:Instant", "start time", "start_time"),
        ("cpo:hasEndTime", "time:Instant", "end time", "end_time"),
        ("cpo:hasDuration", "time:Duration", "duration", "duration"),
    ]

    for property_name, time_class, label, path_segment in time_properties:
        if property_name in target:
            continue
        if property_names is not None and property_name not in property_names:
            continue

        time_type = check_type(time_class, namespace_collection)
        # Without the "has" of the property name: the ID describes the entity ("...StartTime..."),
        # not the relation to it - add_phase_process_variable does the same for all other quantities.
        base_name = property_name.split(":", 1)[-1]
        if base_name.startswith("has"):
            base_name = base_name[3:]
        time_id = generate_id_from_name(f"{id_base}_{base_name}", scope, nr)
        time_entity = {"@id": time_id, "@type": [time_type, scope, "hlo:Actual"]}
        set_property(target, property_name, time_entity, namespace_collection)
        add_entity(datagraph, time_entity)

        # Evidence/reference per list of the exemplar (helpers/value_sources.py), in the old segment.
        if not register:
            continue
        request_value_sources(
            time_entity, entity, scope, nr, namespace_collection, datagraph, todo_list, local_todo_list,
            quantity=path_segment, segment=path_segment, evidence_types=[time_class], reference_types=[time_class],
            required=property_name in required,
        )


def add_start_offset(task: dict, scope: str, nr: int, namespace_collection: dict, datagraph: dict, todo_list: list, local_todo_list: list, evidence_known_cache: dict = None):
    """Create cpo:hasStartOffset (a time:Duration) for a sub-task - at
    hlo:ExperimentSpecific level only.

    According to the ontology the offset is relative to the PARENT task ("when the main task starts at a
    certain time, the subtask can have a start offset of 5min"). Exactly for that reason it is given to
    only a task with dcterms:isPartOf: a top-level task has nothing it would be relative
    to. That is the same kind of structural condition as for the couplings - no
    matter of judgement.

    It does not replace the absolute times but complements them: add_time_entities still creates
    start, end and duration for every task. The offset is needed where
    there is no absolute time at all - the data files of the hydrogenation count minutes
    from the start of the procedure (0 to 152 or 311), a date stands nowhere.

    Called AFTER the linking (see creation/task_functions.py): when it is created, a
    subtask does not know yet that it is one - dcterms:isPartOf is set only by the
    parent, when the description of the subtask is finished already.
    """
    if scope != "hlo:ExperimentSpecific" or "cpo:hasStartOffset" in task:
        return
    if "dcterms:isPartOf" not in task:
        return

    duration_class = "time:Duration"
    time_type = check_type(duration_class, namespace_collection)
    offset_id = generate_id_from_name(f"{short_local_name(task['@id'])}_StartOffset", scope, nr)
    offset = {"@id": offset_id, "@type": [time_type, scope, "hlo:Actual"]}
    set_property(task, "cpo:hasStartOffset", offset, namespace_collection)
    add_entity(datagraph, offset)

    request_value_sources(
        offset, task, scope, nr, namespace_collection, datagraph, todo_list, local_todo_list,
        quantity="start_offset", segment="start_offset", evidence_types=[duration_class], reference_types=[duration_class],
    )


def _is_container_content(phase: dict, datagraph: dict) -> bool:
    """Whether this phase belongs to a material held in a chemical container (cpo:ChemicalContainer) -
    now (cpo:materialContainedIn) or before it was used up (the container's history, rule 2.15)."""
    for material_id in ref_ids(phase.get("dcterms:isPartOf")):
        material = resolve(datagraph, material_id) or {}
        containers = [resolve(datagraph, i) or {} for i in ref_ids(material.get("cpo:materialContainedIn"))]
        if any("cpo:ChemicalContainer" in as_list(c.get("@type")) for c in containers + library_holders(material_id)):
            return True
    return False


def has_permanent_occurrence(entity: dict, datagraph: dict) -> bool:
    """Whether a library entry that this entity specializes (hlo:specializationOf, any number of
    steps) already carries an occurrence - something that is always there, like the room air or
    the gravitational field of the site. Such an entity gets no occurrence of its own.

    Not the content of a container (rule 7.17): the occurrence of its library entry
    is its acquisition - in the lab from delivery or production until used up -, a different
    happening from whether and when the content existed in an experiment, which the experiment
    records itself."""
    # A permanent occurrence stands once at the Fixed entry. On the series and experiment level it
    # can neither be missing nor occur several times; an occurrence of its own there would only
    # have a status "unknown", which would contradict the library. It is read via the chain, like
    # concepts and flags (rule 7.2).
    seen = set()
    pending = ref_ids(entity.get("hlo:specializationOf"))
    while pending:
        current_id = pending.pop()
        if current_id in seen:
            continue
        seen.add(current_id)
        current = resolve(datagraph, current_id)
        if current is None:
            continue
        if "hlo:Fixed" in as_list(current.get("@type")) and current.get("cpo:hasOccurrence"):
            return not _is_container_content(current, datagraph)
        pending.extend(ref_ids(current.get("hlo:specializationOf")))
    return False


def add_occurrence(entity: dict, scope: str, nr: int, namespace_collection: dict, datagraph: dict, todo_list: list, local_todo_list: list, evidence_known_cache: dict = None):
    """The first occurrence of a phenomenon or a phase on the experiment level, with its status and
    its times - created where it does not exist yet - and returned (None at series level).

    An occurrence is a THING, one
    happening of the entity (cpo:Occurrence, no hlo:Actual); an entity that happens more than once
    has several. On it hang its status - an Actual (cpo:OccurrenceStatus) whose evidence and/or
    reference carry cpo:hasOccurrenceValue (cpo:Occurred/cpo:NotOccurred), so that it is said how
    one knows; no evidence and no reference means: not known whether it happened - and its
    times (start, end, duration). Nothing is asked here: whether and how often it happened, and
    what is known about each occurrence, is asked in one place once everything that can occur
    exists (creation/occurrence_functions.py, record_occurrences).

    Nothing is created for an entity whose library entry already carries a permanent occurrence
    (has_permanent_occurrence): the room air is always there.

    The status has the ID ..._Occurrence, the times have theirs; the occurrence itself is
    numbered (..._Occurrence_1).
    """
    if scope != "hlo:ExperimentSpecific":
        return None
    if has_permanent_occurrence(entity, datagraph):
        return None

    existing = entity.get("cpo:hasOccurrence")
    if existing:
        existing_id = existing[0]["@id"] if isinstance(existing, list) else existing.get("@id")
        return find_entity(datagraph, existing_id)

    base = short_local_name(entity["@id"])
    occurrence = {"@id": generate_id_from_name(f"{base}_Occurrence_1", scope, nr),
                  "@type": [check_type("cpo:Occurrence", namespace_collection), scope]}
    status = {"@id": generate_id_from_name(f"{base}_Occurrence", scope, nr),
              "@type": [check_type("cpo:OccurrenceStatus", namespace_collection), scope, "hlo:Actual"]}
    set_property(entity, "cpo:hasOccurrence", occurrence, namespace_collection)
    set_property(occurrence, "cpo:hasOccurrenceStatus", status, namespace_collection)
    add_entity(datagraph, occurrence)
    add_entity(datagraph, status)
    add_time_entities(entity, scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache,
                      on=occurrence, register=False)
    return occurrence


def add_numbered_occurrence(entity: dict, number: int, scope: str, nr: int, namespace_collection: dict, datagraph: dict, todo_list: list, local_todo_list: list):
    """Occurrence number `number` (2, 3, ...) of a phenomenon or a phase that happened more than
    once in an experiment - with its own status and times, like the first (add_occurrence).

    The IDs are numbered throughout (..._Occurrence_2, ..._Occurrence_2_Status,
    ..._Occurrence_2_StartTime); only the first (add_occurrence) has a status and times without a number.
    """
    base = f"{short_local_name(entity['@id'])}_Occurrence_{number}"
    occurrence = {"@id": generate_id_from_name(base, scope, nr),
                  "@type": [check_type("cpo:Occurrence", namespace_collection), scope]}
    if find_entity(datagraph, occurrence["@id"]) is not None:
        raise ValueError(f"{occurrence['@id']} exists already - occurrence {number} was asked twice.")
    status = {"@id": generate_id_from_name(f"{base}_Status", scope, nr),
              "@type": [check_type("cpo:OccurrenceStatus", namespace_collection), scope, "hlo:Actual"]}
    set_property(entity, "cpo:hasOccurrence", occurrence, namespace_collection, True)
    set_property(occurrence, "cpo:hasOccurrenceStatus", status, namespace_collection)
    add_entity(datagraph, occurrence)
    add_entity(datagraph, status)
    add_time_entities(occurrence, scope, nr, namespace_collection, datagraph, todo_list, local_todo_list,
                      on=occurrence, id_base=base, register=False)
    return occurrence


STATUS_SOURCES = ["evidence", "reference", "evidence and reference"]

OCCURRENCE_TIMES = (("cpo:hasStartTime", "start_time", "time:Instant"),
                    ("cpo:hasEndTime", "end_time", "time:Instant"),
                    ("cpo:hasDuration", "duration", "time:Duration"))


def record_occurrences(entity: dict, count: int, scope: str, nr: int, namespace_collection: dict, datagraph: dict, todo_list: list, local_todo_list: list):
    """What is known about the occurrences of one phenomenon or phase in an experiment: it
    happened `count` times, or not at all (count 0). Asked under the entity's segment of the
    occurrence questions (creation/occurrence_functions.py).

    count 0: the first occurrence gets the status NotOccurred, on an evidence and/or reference
    that says how one knows; its times stay empty Actuals. count n: occurrences 1..n, each with
    the status Occurred on its evidence and/or reference, and a value list of its own for its
    start, end and duration. The status value is set by the count, not asked again
    (occurrence_value_preset). Everything of occurrence k stands under the segment occurrence:k,
    the status under occurrence:k/status.
    """
    first = add_occurrence(entity, scope, nr, namespace_collection, datagraph, todo_list, local_todo_list)
    occurrences = [first] + [add_numbered_occurrence(entity, number, scope, nr, namespace_collection, datagraph, todo_list, local_todo_list)
                             for number in range(2, count + 1)]
    value = "cpo:Occurred" if count else "cpo:NotOccurred"
    label = get_display_label(entity)
    for number, occurrence in enumerate(occurrences, 1):
        with question_path("occurrence", number):
            status = find_entity(datagraph, ref_id(occurrence.get("cpo:hasOccurrenceStatus")))
            statement = f"occurrence {number} of {label} happened" if count else f"{label} did not occur"
            source = ask_user(f"[{scope}] Where does the statement come from that {statement} in experiment {nr}?",
                              STATUS_SOURCES, question_id="status_source")
            with question_path("status"), occurrence_value_preset(value):
                if "evidence" in source:
                    add_evidence(status, entity, scope, namespace_collection, datagraph, todo_list, local_todo_list,
                                 possible_evidence_types=["cpo:OccurrenceStatus"], nr=nr, confirmed=True)
                if "reference" in source:
                    add_reference(status, entity, scope, namespace_collection, datagraph, todo_list, local_todo_list,
                                  possible_reference_types=["cpo:OccurrenceStatus"], nr=nr, confirmed=True)
            if not count:
                continue
            # The times as a list of their own of this occurrence - asked as soon as occurrence:k is left.
            for property_name, quantity, time_class in OCCURRENCE_TIMES:
                time_entity = find_entity(datagraph, ref_id(occurrence.get(property_name)))
                request_value_sources(
                    time_entity, occurrence, scope, nr, namespace_collection, datagraph, todo_list, local_todo_list,
                    quantity=quantity, segment=quantity, evidence_types=[time_class], reference_types=[time_class],
                )
