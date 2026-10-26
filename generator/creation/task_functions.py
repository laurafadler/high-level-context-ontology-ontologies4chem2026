"""
Everything needed to create tasks (cpo:Task and its subclasses:
MeasurementTask/ObservationTask/CalculationTask/AssumptionTask/LiteratureLookupTask, all
DeterminationTask; PlanningTask/SettingTask/ControlTask, all SpecificationTask;
TransferTask, OperationTask).

A task is something an agent carries out - reactions and transfers are NOT tasks.

Flow
----
Tasks do not come into being here for the first time. Every value puts its task onto the
todo list as a placeholder as soon as it is recorded (helpers/evidence_reference.py:
ensure_determination_task_stub) - without a question, because each of the eight evidence and
reference types has a task class through hlo:determinedByTaskClass. The placeholder carries
exactly what is settled at that point: the task class and the link to the value in both
directions (cpo:determines/cpo:hasDeterminationTask).

The same pattern as for phases (creation/material_functions.py: create_phase_placeholder ->
creation/phase_functions.py: complete_phases_from_todo): the levels come into being while
recording, the questions come later. The placeholder of the SERIES is the core of it - the
procedure is the same across the series - and an experiment value hangs off a specialization
of it.

complete_all_tasks then works through, in order:

1. hlo:SeriesSpecific: complete every placeholder (name, description, equipment, the
   mandatory entries of its class). Before a placeholder becomes a task of its own it is
   asked whether an already described task determined its value too
   (_offer_existing_task_for_stub) - that is where ONE activity that determined several
   values comes together; only tasks that contradict the placeholder in nothing are offered
   (_stub_is_compatible). Then the series tasks that no value triggered: the sections of the
   procedure, cleaning, waiting.
2. Per experiment: specialize every series task (specialize_task_for_experiment). An
   experiment placeholder that already exists is picked up rather than created anew;
   equipment is remapped onto the experiment-specific device instances. After that come the
   placeholders without a series template, and tasks that occur only in this experiment.
3. Sorting (sort_tasks): which task is part of which, asked ONCE, from above, when every
   task exists - per grouping task a list of its parts, at series level or, where the
   experiments differ, per experiment.
4. What hangs off the structure: cpo:isProcedureOf for whatever sits at the top, the
   function (a pure grouping task gets none), the experiment times and start offsets.
5. The placeholders step 4 created - the evidence of the times - described and placed one
   by one (_place_late_task).

A fixed task library (along the lines of reaction_library) is deliberately NOT implemented
yet. The function signatures here still follow the same pattern as reaction_functions.py, so
that a fixed level could be added later without a rebuild.

cpo:isProcedureOf/hasProcedure is set ONLY on top-level tasks (series template <->
ExperimentalSeries, experiment task <-> SingleExperiment) - subtasks are reachable through
dcterms:hasPart/isPartOf and are not linked directly.

The experiment number of an entity is derived pragmatically from the ID in several places
(_experiment_number_from_id): every experiment-specific ID generated in this project ends in
"_ExperimentSpecific_<nr>" (see helpers/identifiers.py generate_id/generate_id_from_name). A
foreign entity reused by hand may not follow that convention - it then simply does not turn
up in the candidate list, which is only a convenience anyway, rather than being assigned
wrongly.
"""

from helpers.entities import add_entity, find_entity, inherited_value, ask_entity_choice, ask_entity_list, find_entities_by_type, ref_id, as_list, value_label, registered_library
from helpers.properties import set_property, check_type
from helpers.identifiers import (generate_name, get_display_label, claim_id, make_root_id, make_specialization_id,
                                 make_owned_id, level_key, key_name, name_list, strip_crate_prefix)
from helpers.time_occurrence import add_time_entities, add_start_offset
from helpers.profile_variables import create_profile_variable
from creation.material_functions import ask_name, ask_optional_name, get_device_experiment_number
from creation.phase_functions import devices_only_for_dropped
from helpers.user_io import ask_user, ask_user_list, question_path, SAME_OPTIONS
from helpers.todo_functions import delete_todo_entity, add_todo_item
from helpers.library_functions import get_id_list
from helpers.ontology_functions import find_individuals_of_class, find_subclasses, find_superclasses, find_entity_in_ontology, shorten_id
from helpers.evidence_reference import evidence_types, reference_types, reattach_orphan_task_stubs


# cpo:DeterminationTask and cpo:SpecificationTask only group and are deliberately not
# selectable (see the module docstring) - they have to be named here one by one, because OWL
# knows no "abstract": from the class hierarchy alone they cannot be told apart from cpo:Task,
# which groups as well but is very much selectable ("a task that is none of the more special
# kinds"). Everything else comes from the ontology - a new task subclass is thus offered at
# once, without a change of the code.
GROUPING_TASK_CLASSES = ("cpo:DeterminationTask", "cpo:SpecificationTask")


def task_types(namespace_collection):
    """The task classes that can be instantiated directly: every subclass of cpo:Task
    (including cpo:Task itself), without the pure grouping classes."""
    return find_subclasses("cpo:Task", namespace_collection, exclude=GROUPING_TASK_CLASSES)

def free_task_types(namespace_collection):
    """The task classes offered for a task created freely (from a name list, not from a
    value): every instantiable class, the determination classes included (rule 4.11).

    A determination task normally comes from a value - every recorded value puts its own
    placeholder on the todo list (helpers/evidence_reference.py: ensure_determination_task_stub),
    and a task of the sheet that names its values (determines) is merged with that placeholder.
    A task created freely is the rest: an observation of something that is no quantity of the
    crate (the colour of a powder - sosa:hasFeatureOfInterest names the phase, the description
    what was seen; _ask_observed), or a measurement whose quantity is not recorded.
    """
    return list(task_types(namespace_collection))


def task_type_to_value_type(namespace_collection):
    """Task class -> the hlo:EvidenceType/hlo:ReferenceType value it determines.

    Built from the ontology, as the inverse of hlo:determinedByTaskClass on the evidence and
    reference type individuals (cpo:CalculationTask <- hlo:Calculated). This mapping used to
    sit here as a dict with a note saying it really ought to come from the ontology - which
    is what it does now. hlo:Literature gained an entry automatically as soon as the ontology
    gave it a task class.
    """
    mapping = {}
    for value_type in evidence_types(namespace_collection) + reference_types(namespace_collection):
        info = find_entity_in_ontology(value_type, namespace_collection)
        task_class_ref = info.get("determinedByTaskClass") if info else None
        if isinstance(task_class_ref, list):
            task_class_ref = task_class_ref[0]
        if task_class_ref:
            task_class = task_class_ref["@id"] if isinstance(task_class_ref, dict) else task_class_ref
            mapping[shorten_id(task_class, namespace_collection)] = value_type
    return mapping

# A CalculationTask needs at least one input value - without an input there is nothing to
# calculate (see _link_input_values). All others can have one optionally (see
# _link_optional_input_values): a ControlTask, say, that uses a planned profile as its input.
#
# The AssumptionTask is not in the required list: an assumption often rests on what did NOT
# happen ("nothing of the product was weighed in, so nothing was there at the start") or on the
# modelling itself - there is no value one could point to, and a requirement would force one to
# invent one. The reason is carried by the required description (ask_user(..., required=True)
# in create_task), not by the input.
MANDATORY_INPUT_TASK_TYPES = ("cpo:CalculationTask",)
OPTIONAL_INPUT_TASK_TYPES = ("cpo:AssumptionTask", "cpo:PlanningTask", "cpo:SettingTask", "cpo:ControlTask")

def functions(namespace_collection):
    """The cpo:Function individuals from the ontology (mixing, cooling, washing, ...)."""
    return find_individuals_of_class("cpo:Function", namespace_collection)


def _function_facts(namespace_collection) -> dict:
    """id -> {broader} for every function, read once per call site.

    Kept as a plain dict rather than a cached global: the ontology is loaded once at start-up
    anyway, and a cache that silently survives an ontology reload would be a trap.
    """
    facts = {}
    for function_id in functions(namespace_collection):
        info = find_entity_in_ontology(function_id, namespace_collection) or {}
        broader = [shorten_id(ref_id(b), namespace_collection) for b in as_list(info.get("hasBroaderFunction"))]
        facts[function_id] = {"broader": broader}
    return facts


def _narrower_closure(branch_roots, facts: dict) -> list:
    """Every function at or below the given branch roots, the roots included.

    Walks hasBroaderFunction downwards. The property allows a poly-hierarchy and could in
    principle be cyclic if someone mis-declares it - hence the visited set rather than plain
    recursion.
    """
    wanted = set(branch_roots)
    changed = True
    while changed:
        changed = False
        for function_id, fact in facts.items():
            if function_id not in wanted and any(b in wanted for b in fact["broader"]):
                wanted.add(function_id)
                changed = True
    return sorted(wanted)


def offered_functions(task_type: str, namespace_collection) -> list:
    """The functions worth offering for a task of this class.

    The branches come from cpo:offersFunction in the ontology, declared once on cpo:Task as
    the default and narrowed on the classes where there is a reason to (a transfer task moves
    material, a control task holds a state). A class without a declaration inherits its
    superclass's, so a NEW task class works at once.

    Every function of a branch can be chosen, its top-level function included - that is the
    answer when only the kind of operation is known ("it was separated"). Where a class's
    branches hold exactly one function, its purpose follows from the class and nothing is
    asked (_link_functions).
    """
    facts = _function_facts(namespace_collection)

    seen = set()
    pending = [task_type]
    branch_roots = []
    while pending:
        class_id = pending.pop(0)
        if class_id in seen:
            continue
        seen.add(class_id)
        info = find_entity_in_ontology(class_id, namespace_collection) or {}
        declared = [shorten_id(ref_id(b), namespace_collection) for b in as_list(info.get("offersFunction"))]
        if declared:
            branch_roots.extend(declared)
            continue
        pending.extend(find_superclasses(class_id, namespace_collection))

    if not branch_roots:
        # No declaration all the way up to cpo:Task: rather offer everything than nothing.
        print(f"[{task_type}] No cpo:offersFunction declared anywhere above this class - offering every function.")
        branch_roots = [f for f, fact in facts.items() if not fact["broader"]]

    return _narrower_closure(branch_roots, facts)


# ---------------------------------------------------------------------------
# Candidate lists: evidence/reference values, transfers/reactions, devices -
# each filtered to the current scope/the current experiment.
# ---------------------------------------------------------------------------

def _experiment_number_from_id(entity_id: str):
    parts = entity_id.split("_")
    if len(parts) >= 2 and parts[-2] == "ExperimentSpecific" and parts[-1].isdigit():
        return int(parts[-1])
    return None


def _matches_scope_and_experiment(entity: dict, scope: str, nr: int) -> bool:
    types = as_list(entity.get("@type"))
    if scope not in types:
        return False
    if scope != "hlo:ExperimentSpecific":
        return True
    return _experiment_number_from_id(entity["@id"]) == nr


def _devices_for_scope(datagraph: dict, namespace_collection: dict, scope: str, nr: int) -> list:
    devices = find_entities_by_type(datagraph, "cpo:Device", namespace_collection, include_subclasses=True)
    result = []
    for device in devices:
        types = as_list(device.get("@type"))
        if scope not in types:
            continue
        if scope != "hlo:ExperimentSpecific" or get_device_experiment_number(device, datagraph) == nr:
            result.append(device)
    return result


def _is_task(entity: dict, namespace_collection: dict) -> bool:
    types = as_list(entity.get("@type"))
    return any(t in task_types(namespace_collection) or t in GROUPING_TASK_CLASSES for t in types)


def _task_class_of(task: dict, namespace_collection: dict):
    for t in as_list(task.get("@type")):
        if t in task_types(namespace_collection) or t in GROUPING_TASK_CLASSES:
            return t
    return None


def task_stubs(todo_list: list, scope: str, nr, namespace_collection: dict) -> list:
    """The task placeholders of this scope and experiment that are not yet completed,
    sorted by @id.

    They are created in helpers/evidence_reference.py (ensure_determination_task_stub) as
    soon as a value receives its evidence or reference type - in whatever order the values
    happen to be recorded, which follows the order of every list in the answer file. The
    order here decides which placeholder a task that covers SEVERAL values is described from,
    and so its @id and question key (the "Reading the times" task grows out of the first
    open time placeholder). Sorted, that is always the same placeholder, however the lists
    are ordered (step 7, counter-check P3).
    """
    return sorted(
        (item for item in todo_list
         if _is_task(item, namespace_collection) and _matches_scope_and_experiment(item, scope, nr)),
        key=lambda item: item["@id"]
    )


# ---------------------------------------------------------------------------
# Question-path keys for tasks
# ---------------------------------------------------------------------------

def _cause_of(task: dict, pools) -> str:
    """The value this task exists because of - directly, or one level down.

    A SERIES template usually carries no cpo:determines of its own: the values sit at
    experiment level, and the template is only their anchor. Its cause is therefore the value
    of its first specialization. Without that step every series task - the majority - would
    fall back to its own ID and the scheme would buy almost nothing.
    """
    for value_ref in as_list(task.get("cpo:determines")):
        return ref_id(value_ref)
    for spec_ref in as_list(task.get("hlo:hasSpecialization")):
        spec = None
        for pool in pools:
            spec = find_entity(pool, ref_id(spec_ref))
            if spec is not None:
                break
        if spec is None:
            continue
        for value_ref in as_list(spec.get("cpo:determines")):
            return ref_id(value_ref)
    return ""


def task_question_key(task: dict, datagraph: dict = None, todo_list: list = None, local_todo_list: list = None) -> str:
    """The question-path segment of a task - a key that does NOT depend on how many tasks
    came before it.

    This used to be stable_index("task", <@id>), a running number handed out in order of
    first access. That made every answer key positional: inserting a single task anywhere
    shifted the keys of every task created after it, and with them 2673 of the 5830 answers
    in the file. Three separate migrations in one session were the result.

    The key is taken from the CAUSE instead. A placeholder exists because of a value
    (cpo:determines, see _cause_of), and that value's ID comes from the material and phase
    structure, which barely moves - adding a task somewhere else does not touch it at all.
    Only where there is no such cause - a task created freely, the overall procedure - does
    the key fall back to the task's own ID, which still shifts if a task of the SAME class is
    inserted before it, but not when any task anywhere is.

    The level suffix is stripped on purpose: template and performance share one key, and the
    level is already in the path (series:1/experiment:2/...). Two experiments therefore use
    the same key, which is exactly right - they sit under different experiment segments.

    Must stay free of "/" (path separator) and whitespace (the answer file splits keys on
    it); both hold for generated IDs.
    """
    shell = SHELL_TASKS.get(task.get("schema:name"))
    if shell is not None:
        return shell[1]

    pools = [pool for pool in (datagraph, todo_list, local_todo_list) if pool is not None]
    cause = _cause_of(task, pools)
    # The cause WITH its level, without the experiment number (5.1): the experiment stands in the
    # path before it, the level does not - so a series value and an experiment value of the same
    # variable can never fall on the same key. Without a cause, the name of the task.
    if cause:
        return "for-" + level_key(cause)
    return key_name(task.get("@id", ""))


# Properties that say nothing about "is this the same activity?" when two tasks are
# compared: the identity itself, the links to values (exactly those are to be merged),
# the links of levels/structure and the times (they only stand on the experiment level
# and differ there per task).
_IGNORED_WHEN_COMPARING = {
    "@id", "@type", "schema:name",
    "cpo:determines", "cpo:generatedMediaObject",
    "hlo:specializationOf", "hlo:hasSpecialization",
    "dcterms:hasPart", "dcterms:isPartOf",
    "cpo:isProcedureOf",
    "cpo:hasStartTime", "cpo:hasEndTime", "cpo:hasDuration",
}


def _stub_is_compatible(stub: dict, task: dict, namespace_collection: dict) -> bool:
    """Safeguard for merging: a stub may only be absorbed into the task being described
    when it contradicts it in NOTHING - the same task class and, for every property both
    carry, the same value.

    A stub that already carries a different device or a different function, say, therefore
    does not even appear in the list of choices.
    """
    if _task_class_of(stub, namespace_collection) != _task_class_of(task, namespace_collection):
        return False
    # Level and experiment have to agree - @type is in _IGNORED_WHEN_COMPARING,
    # otherwise this check would be the only one to slip through.
    task_scope = "hlo:ExperimentSpecific" if "hlo:ExperimentSpecific" in as_list(task.get("@type")) else "hlo:SeriesSpecific"
    if not _matches_scope_and_experiment(stub, task_scope, _experiment_number_from_id(task["@id"])):
        return False
    # What is checked is what the STUB carries: each of its statements must be in the task
    # in the same way. The other way round is harmless - a task that already has a name,
    # device and function from the questions before may swallow a bare stub (that is the
    # normal case, a stub carries only its class and its links to values). A stub with a
    # statement of its own, however, is refused: _absorb_stub takes over only the links to
    # values, its statement would otherwise be lost silently.
    for prop in set(stub) - _IGNORED_WHEN_COMPARING:
        if task.get(prop) != stub.get(prop):
            return False
    return True


# The answer with which a placeholder explicitly gets NO existing task and thus becomes
# a task of its own - like STANDS_ON_ITS_OWN, as an option instead of a yes/no preface.
NOT_COVERED_YET = "No - this is a task of its own"


def _offer_existing_task_for_stub(stub: dict, scope: str, nr, namespace_collection: dict, datagraph: dict, todo_list: list):
    """Before a placeholder becomes a task of its own, ask whether an already described task
    covers it. Returns that task, or None.

    The ONE place where several values come together in one task - at series level, per
    experiment and for the leftovers alike - not a second question for the same decision from
    the other side while a task is described.

    Asking in this direction works at exactly the point where it can be answered: the
    existing tasks have names by now, whereas a placeholder at the moment of its creation
    carries nothing anyone could recognise. The candidates are filtered by the same
    _stub_is_compatible as the other direction, so nothing is offered that would contradict
    the task.
    """
    candidates = [
        entity for entity in datagraph.get("@graph", [])
        if _is_task(entity, namespace_collection) and entity["@id"] != stub["@id"]
        and _stub_is_compatible(stub, entity, namespace_collection)
    ]
    if not candidates:
        return None

    choice = ask_entity_choice(
        f"[{scope}] Which task determined {_stub_label(stub, datagraph, todo_list)}?",
        candidates, extra_options=[NOT_COVERED_YET], label_fn=get_display_label, question_id="covered_by_existing"
    )
    if choice == NOT_COVERED_YET:
        return None

    task = find_entity(datagraph, choice)
    if task is None:
        return None
    _absorb_stub(task, stub, namespace_collection, datagraph, todo_list)
    print(f"[{scope}] Placeholder {stub['@id']} was absorbed into {get_display_label(task)}.")
    return task


def _stub_label(stub: dict, datagraph: dict, todo_list: list) -> str:
    """A stub has no name yet, so it is described by what it already carries: the values it
    determined and the files it produced.

    Deliberately WITHOUT the placeholder's own @id, which used to stand in front. That ID is
    not stable within a run - see helpers/entities.py: value_label - and an answer recorded
    against it stops matching as soon as the numbering shifts. What the placeholder covers
    identifies it just as well and does not move.
    """
    parts = []
    values = [value_label(ref_id(v), datagraph, todo_list) for v in as_list(stub.get("cpo:determines"))]
    if not values:
        # A series placeholder determines nothing itself - its values hang at the experiment
        # placeholders below it; they say what it is about.
        for spec_ref in as_list(stub.get("hlo:hasSpecialization")):
            spec = find_entity(todo_list, ref_id(spec_ref)) or find_entity(datagraph, ref_id(spec_ref))
            if spec is not None and spec.get("cpo:determines"):
                values = [value_label(ref_id(v), datagraph, todo_list) for v in as_list(spec["cpo:determines"])]
                break
    if values:
        parts.append(f"determines {', '.join(values)}")
    files = [value_label(ref_id(v), datagraph, todo_list) for v in as_list(stub.get("cpo:generatedMediaObject"))]
    if files:
        parts.append(f"generated {', '.join(files)}")
    return "; ".join(parts) if parts else stub["@id"]


def _absorb_stub(task: dict, stub: dict, namespace_collection: dict, datagraph: dict, todo_list: list):
    """Absorb a task placeholder into `task`: its links to values move onto `task` in both
    directions, its experiment specializations are re-hung onto `task` (they are picked up
    later while specializing, see _experiment_stubs_for), and afterwards the stub disappears
    from the todo list.
    """
    for value_ref in as_list(stub.get("cpo:determines")):
        value_id = ref_id(value_ref)
        set_property(task, "cpo:determines", {"@id": value_id}, namespace_collection, True)
        value = find_entity(datagraph, value_id) or find_entity(todo_list, value_id)
        if value is not None:
            set_property(value, "cpo:hasDeterminationTask", task, namespace_collection)

    for media_ref in as_list(stub.get("cpo:generatedMediaObject")):
        media_id = ref_id(media_ref)
        set_property(task, "cpo:generatedMediaObject", {"@id": media_id}, namespace_collection, True)
        media_object = find_entity(datagraph, media_id) or find_entity(todo_list, media_id)
        if media_object is not None:
            set_property(media_object, "cpo:generatedBy", task, namespace_collection)

    for spec_ref in as_list(stub.get("hlo:hasSpecialization")):
        spec = find_entity(todo_list, ref_id(spec_ref)) or find_entity(datagraph, ref_id(spec_ref))
        if spec is None:
            continue
        set_property(spec, "hlo:specializationOf", task, namespace_collection)
        set_property(task, "hlo:hasSpecialization", spec, namespace_collection, True)

    # Once merged into `task` the placeholder ceases to exist - so its template must not
    # point at it any more. Without this step the series task keeps an hlo:hasSpecialization
    # pointing at an entity that never gets into the graph. Noticed when the three GC
    # measurements were merged into one: the remaining series task then pointed at six
    # experiment tasks, of which only two existed (four dead references).
    template_id = ref_id(stub.get("hlo:specializationOf"))
    template = None
    if template_id and template_id != task["@id"]:
        template = find_entity(datagraph, template_id) or find_entity(todo_list, template_id)
    if template is not None:
        remaining = [ref for ref in as_list(template.get("hlo:hasSpecialization")) if ref_id(ref) != stub["@id"]]
        if remaining:
            template["hlo:hasSpecialization"] = remaining
        else:
            template.pop("hlo:hasSpecialization", None)

    delete_todo_entity(todo_list, stub)



# An assumption is no activity at the apparatus: nobody carried it out in the lab, it is
# a judgement about the data ("none of it was weighed in, so nothing was there at the start").
#
# What this list controls is therefore NOT the question "does it belong in the procedure?" -
# the assumptions hang as subtasks in the section "Establishing the values", together with the
# calculations and what was read off the lab journal. cpo:isProcedureOf stands only at
# top-level tasks anyway, a subtask does not need it. Nor does it control the times: every
# task gets a start, an end, a duration and - as a subtask - a start offset (rule 4.6).
#
# All that remains: where an assumption is left without a parent task after all, it hangs
# free instead of standing as a step next to the procedure. (The assumptions the generator
# makes itself are no tasks of the crate but entries of the Assumption Library.)
#
# Deliberately NO collective task over all assumptions: the question "which values are only
# assumed?" is answered by hlo:Assumed and cpo:AssumptionTask by themselves, and a common
# task would have to share one reason among quite different assumptions - exactly what the
# required description is meant to prevent.
TASK_CLASSES_OUTSIDE_THE_PROCEDURE = ("cpo:AssumptionTask",)


def _belongs_in_procedure(task: dict, namespace_collection: dict) -> bool:
    """Whether this task is a step of the procedure and therefore gets cpo:isProcedureOf.
    It does not decide about times - every task gets all of them."""
    return _task_class_of(task, namespace_collection) not in TASK_CLASSES_OUTSIDE_THE_PROCEDURE


def _experiment_id_for(series_task: dict, nr: int, task_type: str, datagraph: dict, reserved: list) -> str:
    """The ID of the experiment performance of a series template, keeping the template's
    number: #Task_0004_SeriesSpecific -> #Task_0004_ExperimentSpecific_2.

    Without this the experiment level allocated a fresh running number, and because the
    procedure is created LAST at series level (it is one of the extra tasks) but specialized
    FIRST per experiment (it is the only top-level task), the numbers came out shifted
    against each other: #Task_0001 was "Charging the reactor" in the series and
    "ExperimentalProcedure" in the experiment. Every other task type kept its number, so the
    shift looked like a mistake in the data rather than in the generator.

    Falls back to a fresh number if that ID is somehow taken already - generate_id counts up
    past everything in use, so inherited numbers claimed earlier simply get skipped.
    """
    series_id = series_task.get("@id", "")
    return claim_id(make_specialization_id(series_id, nr), datagraph, reserved)


def _experiment_stubs_for(series_task: dict, nr: int, datagraph: dict, todo_list: list) -> list:
    """The experiment placeholders of this series task that are still open, for experiment
    nr.

    More than one occurs when two stubs were merged at series level - their experiment stubs
    then both hang off the same series task. The first by @id becomes the experiment task, the
    rest are merged into it (sorted for the same reason as task_stubs).
    """
    stubs = []
    for spec_ref in as_list(series_task.get("hlo:hasSpecialization")):
        candidate = find_entity(todo_list, ref_id(spec_ref))
        if candidate is not None and candidate["@id"].endswith(f"_ExperimentSpecific_{nr}"):
            stubs.append(candidate)
    return sorted(stubs, key=lambda stub: stub["@id"])


def _find_value_roles_for_input(datagraph: dict, scope: str, nr: int) -> list:
    """Any evidence OR reference entities of this scope and experiment - the candidates for
    cpo:hasInputValue (CalculationTask). No hasDeterminationTask filter: an input value has
    typically been determined by another task already."""
    result = []
    for entity in datagraph.get("@graph", []):
        types = as_list(entity.get("@type"))
        if not ({"hlo:Evidence", "hlo:Reference"} & set(types)):
            continue
        if _matches_scope_and_experiment(entity, scope, nr):
            result.append(entity)
    return result


def _all_port_crossing_transfers_for_scope(datagraph: dict, scope: str, nr: int) -> list:
    result = []
    for entity in datagraph.get("@graph", []):
        if "cpo:Transfer" not in (entity.get("@type") or []):
            continue
        transfer_type = ref_id(inherited_value(entity, "cpo:hasTransferType", datagraph))   # rule 3.6
        if transfer_type != "cpo:PortCrossing":
            continue
        if _matches_scope_and_experiment(entity, scope, nr):
            result.append(entity)
    return result


def _all_transfers_and_reactions_for_scope(datagraph: dict, scope: str, nr: int) -> list:
    result = []
    for entity in datagraph.get("@graph", []):
        types = as_list(entity.get("@type"))
        if not ({"cpo:Transfer", "cpo:StoichiometricReaction", "cpo:LumpedReaction"} & set(types)):
            continue
        if _matches_scope_and_experiment(entity, scope, nr):
            result.append(entity)
    return result


# ---------------------------------------------------------------------------
# Single, reused blocks of questions/links (used alike by create_task and
# specialize_task_for_experiment)
# ---------------------------------------------------------------------------

def _ask_used_equipment(task: dict, task_label: str, scope: str, nr: int, namespace_collection: dict, datagraph: dict):
    """cpo:usedEquipment - the devices, as one list (step 7, group C)."""
    candidates = _devices_for_scope(datagraph, namespace_collection, scope, nr)
    if not candidates:
        return
    for device_id in ask_entity_list(f"[{scope}] Which pieces of equipment/devices did {task_label} use?",
                                     candidates, label_fn=get_display_label, question_id="equipment"):
        if scope == "hlo:ExperimentSpecific" and device_id in devices_only_for_dropped(nr):
            continue    # its every stream in this experiment was left out (rule 3.13) - not used here
        device = find_entity(datagraph, device_id)
        set_property(task, "cpo:usedEquipment", device, namespace_collection, True)
        set_property(device, "cpo:usedInTask", task, namespace_collection, True)


def _remap_used_equipment(series_task: dict, task: dict, nr: int, namespace_collection: dict, datagraph: dict):
    """Experiment level: map the series equipment by position onto the matching experiment
    device instances (as get_experiment_port does for ports). A device whose every stream in
    this experiment was left out (rule 3.13, drop_empty_experiment_phases - a stock bottle of a
    substance the experiment does not contain) is not equipment here, so it is not recorded as
    used in this experiment either."""
    refs = series_task.get("cpo:usedEquipment", [])
    refs = refs if isinstance(refs, list) else [refs]
    for ref in refs:
        series_device_id = ref.get("@id") if isinstance(ref, dict) else ref
        series_device = find_entity(datagraph, series_device_id)
        if series_device is None:
            continue
        specializations = series_device.get("hlo:hasSpecialization", [])
        specializations = specializations if isinstance(specializations, list) else [specializations]
        if nr > len(specializations):
            continue
        experiment_device = find_entity(datagraph, specializations[nr - 1]["@id"])
        if experiment_device is None or experiment_device["@id"] in devices_only_for_dropped(nr):
            continue
        set_property(task, "cpo:usedEquipment", experiment_device, namespace_collection, True)
        set_property(experiment_device, "cpo:usedInTask", task, namespace_collection, True)


# ---------------------------------------------------------------------------
# cpo:performedBy
# ---------------------------------------------------------------------------
# Four rules which together make every kind of task carry
# the same statement in every crate:
#
# WHICH CLASS. Every task class except the generic cpo:Task is asked. In this project the
#   generic class is exactly the class of the sections ("Experimental procedure",
#   "Working up", the collective tasks of the libraries): it holds other tasks together and
#   does nothing itself for which a performer could be given - who did the section stands at
#   its parts. Deliberately tied to the CLASS and not to the content (e.g. via
#   _is_pure_grouping_task): otherwise it would depend on the single case whether a
#   measurement carries a performer or not.
#
# WHICH LEVEL. A series task is a template, not an execution. It carries a performer only
#   if it was the same person in ALL experiments; if not, the performer stands at the
#   experiment tasks and the template stays empty. Exactly one of the two levels carries the
#   statement, never both - otherwise the same statement would stand twice in the crate, and
#   if they differed it could not be decided which holds.
#   Exception cpo:PlanningTask: the planning of the series is an activity of its own with its
#   own times (see _wants_series_times), not a mere template. It always carries a performer of
#   its own, and the question about the experiments comes in addition.
#
# NO PERSON. "Logging the temperature" or "Controlling the pressure" is done by the device,
#   not by a human. Then cpo:performedBy is NOT set AT ALL - a property that points at
#   nobody is worse than none. What did it stands in cpo:usedEquipment.
#
# INHERITANCE only along hlo:specializationOf (an experiment task without a statement of its
#   own -> its series template), NOT along dcterms:hasPart: a section never carries anything
#   a subtask could inherit.
#
# This drops the old rule "a task without performedBy = performed by the cpo:hasExperimenter
# of the series". It was the reason why 0 of 89 tasks carried a statement and the chain still
# ended in nothing: the default experimenter stood only in the library. Not every task without
# a statement was done by the experimenter - some were done by nobody.
#
# The person is NOT copied into the crate. find_library_item returns the entity from
# libraries/people_library.jsonld, set_property keeps only its @id - so the crate points at
# the library and does not pull it in - as for all library entries (rule 2.1; read via
# helpers/entities.py: resolve).

# The answer with which the question ends without a person.
NOT_PERFORMED_BY_A_PERSON = "Nobody - equipment did this on its own"

# How the series level decided, so that the experiment level knows what to do:
# series task @id -> "series" (the template carries the statement, the experiment inherits),
# "per_experiment" (every experiment is asked on its own) or "none" (nobody).
# The table has to outlive the series loop of complete_all_tasks, because the experiment
# loop only runs afterwards; it must not hang at the series task itself, that ended up in
# the crate. complete_all_tasks resets it at the start.
_performed_by_mode = {}


def _class_gets_performed_by(task_type: str) -> bool:
    """Whether this task class carries a cpo:performedBy at all - see the block above."""
    return task_type != "cpo:Task"


def _ask_performers(task_label: str, scope: str, namespace_collection: dict, people_library: dict) -> list:
    """Ask for one or more people from the people library - at least one, as one list.

    A task can have been carried out by several people (two pairs of hands on one charging
    step). The answer names them all at once (helpers/user_io.py: ask_user_list) instead of
    an "anyone else?" loop with a running number in the question path.
    """
    prefix = "person:"
    options = get_id_list(people_library, prefix, "schema:Person")
    names = ask_user_list(f"[{scope}] Who performed {task_label}?", options, question_id="performers", required=True)
    performers = []
    for name in names:
        person = find_entity(people_library, f"{prefix}{name}")
        if person is None:
            raise RuntimeError(
                f"No entry for {name} in libraries/people_library.jsonld "
                f"(task: {task_label}) - the crate would point at nothing."
            )
        performers.append(person)
    return performers


def _ask_used_software(task: dict, task_label: str, scope: str, namespace_collection: dict):
    """cpo:usedSoftware - the software a task was carried out with (a calculation, a control
    program, a tool that filled in values), as one list from the software library. Only this
    direction: the library entry is not changed in a run (rule 2.2), like the people of
    cpo:performedBy. Asked only when the library holds any software."""
    prefix = "software:"
    software_library = registered_library("software_library")
    options = get_id_list(software_library, prefix)
    if not options:
        return
    for name in ask_user_list(f"[{scope}] Which software did {task_label} use?", options, question_id="software"):
        software = find_entity(software_library, f"{prefix}{name}")
        set_property(task, "cpo:usedSoftware", software, namespace_collection, True)


def _set_performers(task: dict, performers: list, namespace_collection: dict):
    for person in performers:
        set_property(task, "cpo:performedBy", person, namespace_collection, True)


def _ask_performed_by(task: dict, task_type: str, task_label: str, scope: str,
                      namespace_collection: dict, people_library: dict):
    """cpo:performedBy at series level (and for experiment tasks without a template) - see
    the block above for the rules."""
    if not _class_gets_performed_by(task_type):
        return

    if scope != "hlo:SeriesSpecific":
        # A task that occurs only in this experiment and has no template: there is nothing to
        # compare, so ask directly. The experiment tasks WITH a template do not run through here
        # but through _ask_performed_by_for_experiment.
        answer = ask_user(f"[{scope}] Was {task_label} performed by a person?",
                          ["Yes", NOT_PERFORMED_BY_A_PERSON], question_id="performed_by_scope")
        if answer == "Yes":
            _set_performers(task, _ask_performers(task_label, scope, namespace_collection, people_library),
                            namespace_collection)
        return

    if task_type == "cpo:PlanningTask":
        # The exception: the planning of the series really took place, so it always carries its
        # own performer - whoever planned the single runs.
        _set_performers(task, _ask_performers(task_label, scope, namespace_collection, people_library),
                        namespace_collection)
        answer = ask_user(
            f"[{scope}] Was the planning of each individual experiment done by the same person(s)?",
            ["Yes", "No - it differs between experiments"], question_id="performed_by_scope")
        _performed_by_mode[task["@id"]] = "series" if answer == "Yes" else "per_experiment"
        return

    answer = ask_user(
        f"[{scope}] Was {task_label} performed by the same person(s) in every experiment?",
        ["Yes", "No - it differs between experiments", NOT_PERFORMED_BY_A_PERSON],
        question_id="performed_by_scope")
    if answer == NOT_PERFORMED_BY_A_PERSON:
        _performed_by_mode[task["@id"]] = "none"
        return
    if answer == "Yes":
        _set_performers(task, _ask_performers(task_label, scope, namespace_collection, people_library),
                        namespace_collection)
        _performed_by_mode[task["@id"]] = "series"
        return
    # Different: the template stays empty, every experiment is asked on its own.
    _performed_by_mode[task["@id"]] = "per_experiment"


def _ask_performed_by_for_experiment(task: dict, series_task: dict, task_type: str, task_label: str,
                                     scope: str, namespace_collection: dict, people_library: dict):
    """The experiment-level half of the rule: only asked where the series template said the
    performer differs between experiments. Where it said "the same everywhere", the template
    carries the entry and this task inherits it through hlo:specializationOf - deliberately
    NOT copied down, so the statement stands in exactly one place."""
    if not _class_gets_performed_by(task_type):
        return
    if _performed_by_mode.get(series_task["@id"]) != "per_experiment":
        return
    _set_performers(task, _ask_performers(task_label, scope, namespace_collection, people_library),
                    namespace_collection)


def _link_input_values(task: dict, task_label: str, scope: str, nr: int, namespace_collection: dict, datagraph: dict):
    """CalculationTask: cpo:hasInputValue onto any evidence or reference values of this scope and
    experiment - at least one in an experiment, optional in the series template."""
    candidates = _find_value_roles_for_input(datagraph, scope, nr)
    if not candidates:
        print(f"[{scope}] Warning: no Evidence/Reference values found yet for {task_label}'s mandatory cpo:hasInputValue link - skipping.")
        return

    # The calculation happens in the experiment; the series template names only input values that
    # exist on the series level - often none (the yield of the amidation), so the input is not
    # required there.
    in_experiment = scope == "hlo:ExperimentSpecific"
    for target_id in ask_entity_list(f"[{scope}] Which values does {task_label} use as input?", candidates,
                                     label_fn=get_display_label, question_id="input_values", required=in_experiment):
        set_property(task, "cpo:hasInputValue", find_entity(datagraph, target_id), namespace_collection, True)


def _link_optional_input_values(task: dict, task_label: str, scope: str, nr: int, namespace_collection: dict, datagraph: dict):
    """PlanningTask/SettingTask/ControlTask (optional; see the hasInputValue comment in the
    ontology - a control task using a planned profile as its input, for example):
    cpo:hasInputValue onto any evidence or reference values of this scope and experiment."""
    candidates = _find_value_roles_for_input(datagraph, scope, nr)
    if not candidates:
        return

    for target_id in ask_entity_list(f"[{scope}] Which values does {task_label} use as input (e.g. a planned profile)?", candidates,
                                     label_fn=get_display_label, question_id="input_values"):
        set_property(task, "cpo:hasInputValue", find_entity(datagraph, target_id), namespace_collection, True)


def _link_aims_at(task: dict, task_label: str, scope: str, namespace_collection: dict, datagraph: dict, candidates: list, mandatory: bool):
    """cpo:aimsAt/isAimOf: the event - a transfer or a stoichiometric reaction - the task is
    meant to bring about.

    Mandatory for a TransferTask (at least one, with only port-crossing transfers as
    candidates, see the caller), optional for every other kind of task (with transfers or
    reactions as candidates).
    """
    if not candidates:
        if mandatory:
            print(f"[{scope}] Warning: no matching PortCrossing Transfer found yet for {task_label}'s mandatory cpo:aimsAt link - skipping.")
        return

    if mandatory:
        prompt = f"[{scope}] Which PortCrossing Transfers does {task_label} aim at?"
    else:
        prompt = f"[{scope}] Which specific Transfers or Reactions does {task_label} aim at?"
    for target_id in ask_entity_list(prompt, candidates, label_fn=get_display_label, question_id="aims_at", required=mandatory):
        target = find_entity(datagraph, target_id)
        set_property(task, "cpo:aimsAt", target, namespace_collection, True)
        set_property(target, "cpo:isAimOf", task, namespace_collection, True)


def _ask_executes_profile(task: dict, task_label: str, scope: str, nr: int, namespace_collection: dict, datagraph: dict, todo_list: list, local_todo_list: list):
    """OperationTask (optional): cpo:executesProfile, e.g. the rpm profile of a stirrer."""
    answer = ask_user(f"[{scope}] Does {task_label} execute a specific profile (e.g. a temperature/rpm ramp)?", ["Yes", "No"], question_id="executes_profile")
    if answer != "Yes":
        return

    # First offer the profiles that exist on this level already: the reference profiles of the
    # actuals (speed of a stirrer, temperature of a content - type Set, rule 4.10; the
    # value lists of the devices are asked before the tasks). The set profile of the stirrer is
    # exactly what a stirring task executes; creating a new one would make a second, unconnected
    # copy of the same specification.
    existing = [
        entity for entity in datagraph.get("@graph", [])
        if "cpo:ProfileVariable" in as_list(entity.get("@type")) and _matches_scope_and_experiment(entity, scope, nr)
    ]
    profile = None
    if existing:
        choice = ask_entity_choice(
            f"[{scope}] Which profile does {task_label} execute?",
            existing, extra_options=["Describe a new profile"], label_fn=get_display_label, question_id="which_profile"
        )
        if choice != "Describe a new profile":
            profile = find_entity(datagraph, choice)

    if profile is None:
        profile = create_profile_variable(task_label, scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, question_id_prefix="profile",
                                          entity_id=make_owned_id("Profile", task["@id"]))
    if profile is not None:
        set_property(task, "cpo:executesProfile", profile, namespace_collection)


def _ask_acts_on(task: dict, task_label: str, scope: str, nr: int, namespace_collection: dict, datagraph: dict):
    """OperationTask (optional, multi-valued): cpo:actsOn - what is being heated, stirred or
    cleaned (a device or a MaterialRepresentation)."""
    devices = _devices_for_scope(datagraph, namespace_collection, scope, nr)
    materials = [m for m in find_entities_by_type(datagraph, "cpo:MaterialRepresentation", namespace_collection, include_subclasses=True) if _matches_scope_and_experiment(m, scope, nr)]
    candidates = devices + materials
    if not candidates:
        return
    for target_id in ask_entity_list(f"[{scope}] Which devices or materials does {task_label} act on?", candidates,
                                     label_fn=get_display_label, question_id="acts_on"):
        set_property(task, "cpo:actsOn", find_entity(datagraph, target_id), namespace_collection, True)


def _ask_generated_media_object(task: dict, task_label: str, scope: str, namespace_collection: dict, datagraph: dict):
    """Optional, all task types: cpo:generatedMediaObject, e.g. a photo of an ObservationTask."""
    candidates = find_entities_by_type(datagraph, "schema:MediaObject", namespace_collection, include_subclasses=True)
    if not candidates:
        return
    # A placeholder from the media objects already brings its file (see
    # helpers/evidence_reference.py: ask_task_for_media_object) - the question is about further ones.
    for media_object_id in ask_entity_list(f"[{scope}] Which (further) media objects (files/images/videos) did {task_label} generate?",
                                           candidates, label_fn=get_display_label, question_id="generated_media_objects"):
        media_object = find_entity(datagraph, media_object_id)
        set_property(task, "cpo:generatedMediaObject", media_object, namespace_collection, True)
        # Set the inverse direction too, as everywhere in the project - no reasoner runs that would
        # add the inverse property. Single-valued: a file is made once.
        set_property(media_object, "cpo:generatedBy", task, namespace_collection)


# ---------------------------------------------------------------------------
# Task - hlo:SeriesSpecific (template) or stand-alone hlo:ExperimentSpecific
# tasks that are not derived from a series template (see
# complete_all_tasks)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# The shell: tasks that exist in every crate of this kind
# ---------------------------------------------------------------------------
#
# The shell exists from the start, so there is always a parent task to offer, and the order in
# which tasks are described does not matter - built by hand in the right order, a task made
# after the sections would hang outside the procedure.
#
# The three are NOT to be treated alike:
#   - The procedure is purely structural. It claims nothing but "this experiment had a
#     course" and therefore cannot be wrong.
#   - The planning always exists as well: without planning, SOP and risk assessment the
#     series would not have been allowed to run. The anchor may stay empty and get the
#     documents later. It is also the only series task with REAL times - it is not a
#     template but an activity that took place once (see _wants_series_times).
#   - "Establishing the values" also always exists and hangs firmly under the procedure
#     (sort_tasks), also when empty: an empty shell is the smaller price than a structure that
#     looks different from crate to crate. (The generator's own assumptions do not stand in it
#     but in the Assumption Library - helpers/evidence_reference.py: LIBRARY_ASSUMPTIONS.)
PROCEDURE_TASK_NAME = "Experimental procedure"
PLANNING_TASK_NAME = "Planning the series"
ESTABLISHING_TASK_NAME = "Establishing the values"
# Three further fixed shells structure the procedure (rule 7c.5a), like the
# sections of XDL (Prep, Reaction, Workup): preparation, main operation, work-up. They always exist,
# even empty - like "Establishing the values". Their names are fixed and do not follow rule 1.7. The
# main operation is deliberately not called "Reaction": it claims no reaction; the task that brings a
# reaction about hangs in it and carries ReactingChemicals (rule 4.9). The three have no function of
# their own, they inherit those of their parts. Purification as a fourth section:
# things_to_implement_after_me.md.
PREPARATION_TASK_NAME = "Preparation"
MAIN_OPERATION_TASK_NAME = "Main operation"
WORK_UP_TASK_NAME = "Work-up"
PROCEDURE_SECTION_NAMES = (PREPARATION_TASK_NAME, MAIN_OPERATION_TASK_NAME, WORK_UP_TASK_NAME)

# Fixed question-path keys. The shell has no cause a key could hang on (see
# task_question_key) - so it gets a named one instead of one derived from the @id, which
# would shift as soon as a task of the same class comes before it.
SHELL_TASKS = {
    PROCEDURE_TASK_NAME: ("cpo:Task", "procedure"),
    PLANNING_TASK_NAME: ("cpo:PlanningTask", "planning"),
    ESTABLISHING_TASK_NAME: ("cpo:Task", "establishing"),
    PREPARATION_TASK_NAME: ("cpo:Task", "preparation"),
    MAIN_OPERATION_TASK_NAME: ("cpo:Task", "main_operation"),
    WORK_UP_TASK_NAME: ("cpo:Task", "workup"),
}

# The procedure never gets a function: its cpo:usedEquipment is already only the collection
# of what the parts use, and its purposes are the union of the purposes of its parts. A
# statement of its own would be either redundant or arbitrary.
TASK_NAMES_WITHOUT_FUNCTION = (PROCEDURE_TASK_NAME,)

SHELL_TASK_DESCRIPTIONS = {
    PROCEDURE_TASK_NAME: "One run of this series, from start to finish - the frame that every step of the procedure hangs in.",
    PLANNING_TASK_NAME: "Working out how the series is to be run, before any of it happens: what is charged, under which conditions it runs, how long, and what has to be watched out for. Carries the SOP and the risk assessment.",
    ESTABLISHING_TASK_NAME: "Working out the values that nobody read off the apparatus: what was concluded from other values, what was watched rather than measured, and what had to be assumed because nothing was recorded.",
    PREPARATION_TASK_NAME: "Everything done before the main operation starts: charging, setting up, closing the apparatus.",
    MAIN_OPERATION_TASK_NAME: "The main part of the run - for a reaction, the time during which it takes place, with what is done meanwhile (stirring, heating, cooling, feeding).",
    WORK_UP_TASK_NAME: "Everything done after the main operation: sampling, emptying, separating, washing, concentrating, purifying, analysing.",
}


def _find_shell_task(name: str, scope: str, datagraph: dict, todo_list: list, local_todo_list: list):
    """Find a shell task again - on the todo list while it is still a placeholder, in the
    graph once the tasks stage has described it."""
    for pool in (datagraph.get("@graph", []), todo_list or [], local_todo_list or []):
        for entity in pool:
            if entity.get("schema:name") == name and scope in as_list(entity.get("@type")):
                return entity
    return None


def ensure_shell_task(name: str, namespace_collection: dict, datagraph: dict, todo_list: list, local_todo_list: list):
    """Put one of the shell tasks onto the todo list if it is not there yet, and return it.

    A placeholder rather than a finished task, so that the tasks stage describes it like
    everything else - that is what keeps the SOP question at the planning task and the
    equipment question at the procedure. Name and description are carried from the start:
    they make it findable again and keep the boilerplate out of the questionnaire.
    """
    task_class, _ = SHELL_TASKS[name]
    task_class = check_type(task_class, namespace_collection)
    existing = _find_shell_task(name, "hlo:SeriesSpecific", datagraph, todo_list, local_todo_list)
    if existing is not None:
        return existing

    task_id = claim_id(make_root_id("Task", name, "hlo:SeriesSpecific"),
                           datagraph, todo_list, local_todo_list)
    task = {"@id": task_id, "@type": [task_class, "hlo:SeriesSpecific"]}
    set_property(task, "schema:name", name, namespace_collection)
    set_property(task, "schema:description", SHELL_TASK_DESCRIPTIONS[name], namespace_collection)
    add_todo_item(local_todo_list, task)
    return task


def ensure_base_shell(namespace_collection: dict, datagraph: dict, todo_list: list, local_todo_list: list):
    """The shell tasks, created before anything is described - they exist in every crate."""
    ensure_shell_task(PROCEDURE_TASK_NAME, namespace_collection, datagraph, todo_list, local_todo_list)
    ensure_shell_task(PLANNING_TASK_NAME, namespace_collection, datagraph, todo_list, local_todo_list)
    ensure_shell_task(ESTABLISHING_TASK_NAME, namespace_collection, datagraph, todo_list, local_todo_list)
    for name in PROCEDURE_SECTION_NAMES:
        ensure_shell_task(name, namespace_collection, datagraph, todo_list, local_todo_list)


# ---------------------------------------------------------------------------
# Sorting in: which task is part of which
# ---------------------------------------------------------------------------
#
# ONE place, at the very end, when all tasks and the shell are described: per summarizing task
# a list of its parts. Asked from above and from below while describing, the same assignment
# would come from two sides, and which side came first would depend on the order of the tasks.
#
# What only comes into being AFTER the sorting - the task that read off the start offsets,
# since a start offset exists only once the parent task is settled - is placed on its own
# (_place_late_task): if it determines only times, automatically under "Establishing the
# values", otherwise with a question.

# The tasks of the shell, which always summarize - they need not be named.
GROUPING_SHELL_NAMES = (PROCEDURE_TASK_NAME, *PROCEDURE_SECTION_NAMES, ESTABLISHING_TASK_NAME)

# The tasks that stand at the top on purpose: they hang directly at the experiment
# (cpo:isProcedureOf), not in another task. Anything else left without a parent task at the
# end is reported.
TOP_LEVEL_TASK_NAMES = (PROCEDURE_TASK_NAME, PLANNING_TASK_NAME)

# The answer with which a task explicitly gets NO parent task. It stands as an option of its
# own instead of opening the question with yes/no: so the answer file says that the question
# was answered, not merely that nothing was chosen.
STANDS_ON_ITS_OWN = "It stands on its own"

TIME_VALUE_TYPES = ("time:Instant", "time:Duration")


def _is_shell(task: dict, name: str) -> bool:
    """Whether task is this shell task, at series level or as its performance - recognised
    by the @id, not by schema:name, which the name question could have changed."""
    shell_id = make_root_id("Task", name, "hlo:SeriesSpecific")
    return task.get("@id") == shell_id or ref_id(task.get("hlo:specializationOf")) == shell_id


def _required_times(task: dict, scope: str) -> tuple:
    """The times a task must have a value for: the start of the experimental procedure in an
    experiment (rule 5.6). The usage history of the devices is ordered by it (rule 5.3) - without it, a
    run cannot say which use of a device came before this experiment."""
    if scope == "hlo:ExperimentSpecific" and _is_shell(task, PROCEDURE_TASK_NAME):
        return ("cpo:hasStartTime",)
    return ()


def _tasks_of(datagraph: dict, scope: str, nr, namespace_collection: dict) -> list:
    """The tasks of this scope (and experiment) in the graph, in graph order."""
    return [entity for entity in datagraph.get("@graph", [])
            if _is_task(entity, namespace_collection) and _matches_scope_and_experiment(entity, scope, nr)]


def _set_part(parent: dict, child: dict, namespace_collection: dict):
    set_property(parent, "dcterms:hasPart", child, namespace_collection, True)
    set_property(child, "dcterms:isPartOf", parent, namespace_collection)


def _ancestor_ids(task: dict, datagraph: dict) -> set:
    """The IDs of every task above this one - offering any of those as its part would
    create a cycle."""
    collected, current = set(), task
    while current is not None and "dcterms:isPartOf" in current:
        parent_id = ref_id(current["dcterms:isPartOf"])
        if parent_id in collected:
            break
        collected.add(parent_id)
        current = find_entity(datagraph, parent_id)
    return collected


def _descendant_ids(task: dict, datagraph: dict) -> set:
    """The IDs of task and of every subtask hanging beneath it, recursively."""
    collected = {task["@id"]}
    for part_ref in as_list(task.get("dcterms:hasPart")):
        part = find_entity(datagraph, ref_id(part_ref))
        if part is not None and part["@id"] not in collected:
            collected |= _descendant_ids(part, datagraph)
    return collected


def _part_candidates(group: dict, scope: str, nr, datagraph: dict, namespace_collection: dict) -> list:
    """What can still become a part of group: tasks of the same level without a parent,
    except group itself and whatever sits above it."""
    blocked = {group["@id"]} | _ancestor_ids(group, datagraph)
    return [task for task in _tasks_of(datagraph, scope, nr, namespace_collection)
            if "dcterms:isPartOf" not in task and task["@id"] not in blocked]


def _specialization_in(series_task: dict, nr: int, datagraph: dict):
    """The performance of a series task in experiment nr, or None."""
    for spec_ref in as_list(series_task.get("hlo:hasSpecialization")):
        spec_id = ref_id(spec_ref)
        if _experiment_number_from_id(spec_id) == nr:
            return find_entity(datagraph, spec_id)
    return None


def sort_tasks(namespace_collection: dict, datagraph: dict, number_experiments: int, question_keys: dict):
    """Which task is part of which - asked once, from above, when every task exists.

    Per grouping task first whether it holds the same sub-tasks in every experiment. If so,
    one list at series level, and the experiments follow it one-to-one. If not, one list per
    experiment - that is where the tasks go that exist in a single experiment only - and the
    series template gets the parts that ALL experiments share, once the series is completed (while
    it is open, a further experiment could still shrink that set). A performance may hold more
    parts than its template.

    question_keys maps a task @id to the question-path key it was described under, so the
    sorting questions stand next to the task's other answers.
    """
    series_scope, experiment_scope = "hlo:SeriesSpecific", "hlo:ExperimentSpecific"

    # What is settled by definition, without a question: preparation, main operation, work-up and
    # "Establishing the values" are sections of the procedure.
    for scope, nr in [(series_scope, None)] + [(experiment_scope, n) for n in range(1, number_experiments + 1)]:
        tasks_here = _tasks_of(datagraph, scope, nr, namespace_collection)
        procedure = next((t for t in tasks_here if _is_shell(t, PROCEDURE_TASK_NAME)), None)
        if procedure is None:
            continue
        for name in (*PROCEDURE_SECTION_NAMES, ESTABLISHING_TASK_NAME):
            section = next((t for t in tasks_here if _is_shell(t, name)), None)
            if section is not None and "dcterms:isPartOf" not in section:
                _set_part(procedure, section, namespace_collection)

    series_tasks = _tasks_of(datagraph, series_scope, None, namespace_collection)
    shells = [task for name in GROUPING_SHELL_NAMES for task in series_tasks if _is_shell(task, name)]
    others = [task for task in series_tasks if task not in shells]

    shell_note = f" (besides {', '.join(get_display_label(s) for s in shells)})" if shells else ""
    further = ask_entity_list(
        f"[{series_scope}] Which further tasks hold other tasks as their parts{shell_note}? Separated by ';' (leave empty if none)",
        others, question_id="grouping_tasks"
    )
    groups = shells + [find_entity(datagraph, task_id) for task_id in further]
    experiments = range(1, number_experiments + 1)

    for group in groups:
        label = get_display_label(group)
        key = question_keys.get(group["@id"]) or task_question_key(group, datagraph)
        with question_path("task", key):
            same = True
            if number_experiments > 0:
                same = ask_user(f"[{series_scope}] Does {label} hold the same sub-tasks in every experiment?",
                                SAME_OPTIONS, question_id="same_parts_in_all_experiments") == "Yes"
            if same:
                part_ids = ask_entity_list(f"[{series_scope}] Which tasks are part of {label}? Separated by ';'",
                                           _part_candidates(group, series_scope, None, datagraph, namespace_collection),
                                           question_id="parts")
                for part_id in part_ids:
                    part = find_entity(datagraph, part_id)
                    _set_part(group, part, namespace_collection)
                    for nr in experiments:
                        group_spec, part_spec = _specialization_in(group, nr, datagraph), _specialization_in(part, nr, datagraph)
                        if group_spec is not None and part_spec is not None:
                            _set_part(group_spec, part_spec, namespace_collection)
                        else:
                            print(f"[Tasks] {get_display_label(part)} has no counterpart inside {label} in experiment {nr}.")
        if same:
            continue

        chosen_per_experiment = {}
        for nr in experiments:
            group_spec = _specialization_in(group, nr, datagraph)
            if group_spec is None:
                print(f"[Tasks] {label} does not exist in experiment {nr} - nothing to sort into it there.")
                continue
            with question_path("experiment", nr), question_path("task", key):
                part_ids = ask_entity_list(f"[{experiment_scope}] Which tasks are part of {label} in Experiment {nr}? Separated by ';'",
                                           _part_candidates(group_spec, experiment_scope, nr, datagraph, namespace_collection),
                                           question_id="parts")
            for part_id in part_ids:
                _set_part(group_spec, find_entity(datagraph, part_id), namespace_collection)
            chosen_per_experiment[nr] = part_ids

        # The template gets what is in it in EVERY experiment - it describes what they have in
        # common, what belongs to one experiment stands only at the experiment version. Only when
        # the series is completed: as long as it is open, a further experiment can still make the
        # intersection smaller, and a template loses no part (8).
        if not _series_completed(datagraph):
            continue
        first = chosen_per_experiment.get(1, [])
        for part_id in first:
            template_id = ref_id(find_entity(datagraph, part_id).get("hlo:specializationOf"))
            template = find_entity(datagraph, template_id) if template_id else None
            if template is None or "dcterms:isPartOf" in template:
                continue
            if all(ref_id(_specialization_in(template, nr, datagraph) or {"@id": ""}) in chosen_per_experiment.get(nr, [])
                   for nr in experiments):
                _set_part(group, template, namespace_collection)


def _series_completed(datagraph: dict) -> bool:
    series = [e for e in datagraph.get("@graph", []) if "cpo:ExperimentalSeries" in as_list(e.get("@type"))]
    return bool(series) and series[0].get("cpo:isCompleted") is True


def _determines_only_times(task: dict, datagraph: dict, pools) -> bool:
    """Whether everything this task determined is a time - a start, an end, a duration or a
    start offset. That is what the task reading the times off the log does."""
    values = [ref_id(v) for v in as_list(task.get("cpo:determines"))]
    if not values:
        return False
    for value_id in values:
        value = find_entity(datagraph, value_id)
        for pool in pools:
            if value is None:
                value = find_entity(pool, value_id)
        if value is None or not any(t in TIME_VALUE_TYPES for t in as_list(value.get("@type"))):
            return False
    return True


def _establishing_task_for(scope: str, nr, datagraph: dict):
    """The "Establishing the values" shell of this level, or None if the crate has none."""
    for task in datagraph.get("@graph", []):
        if _is_shell(task, ESTABLISHING_TASK_NAME) and _matches_scope_and_experiment(task, scope, nr):
            return task
    return None


def _place_late_task(task: dict, scope: str, nr, owner: dict, namespace_collection: dict, datagraph: dict,
                     todo_list: list, local_todo_list: list, evidence_known_cache: dict = None):
    """Put a task that only came into being AFTER the sorting into the structure.

    That is, in practice, the task that read the times off the log: a start offset only
    exists once a task's parent is known, and its evidence creates that task. A task that
    determines nothing but times goes under "Establishing the values" without a question;
    anything else is asked for - once, for this task, keyed by the task itself.
    """
    if "dcterms:isPartOf" not in task:
        establishing = _establishing_task_for(scope, nr, datagraph)
        if establishing is not None and _determines_only_times(task, datagraph, [todo_list, local_todo_list]):
            _set_part(establishing, task, namespace_collection)
            print(f"[{scope}] {get_display_label(task)} only determines times - placed under {get_display_label(establishing)}.")
        else:
            candidates = [candidate for candidate in _tasks_of(datagraph, scope, nr, namespace_collection)
                          if candidate["@id"] not in _descendant_ids(task, datagraph)]
            if candidates:
                choice = ask_entity_choice(
                    f"[{scope}] Which task is {get_display_label(task)} part of?",
                    candidates, extra_options=[STANDS_ON_ITS_OWN], label_fn=get_display_label, question_id="parent_task"
                )
                if choice != STANDS_ON_ITS_OWN:
                    parent = find_entity(datagraph, choice)
                    if parent is not None:
                        _set_part(parent, task, namespace_collection)
        # Only now is it a subtask - see add_start_offset.
        if "dcterms:isPartOf" in task:
            add_start_offset(task, scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache)

    if owner is not None and "dcterms:isPartOf" not in task and _belongs_in_procedure(task, namespace_collection):
        _set_procedure(task, owner, namespace_collection)


def _set_procedure(task: dict, owner: dict, namespace_collection: dict):
    set_property(task, "cpo:isProcedureOf", owner, namespace_collection)
    set_property(owner, "cpo:hasProcedure", task, namespace_collection, True)


def _report_unplaced(datagraph: dict, namespace_collection: dict):
    """Every task of this crate should end up somewhere. Name the ones that did not. Tasks
    taken over from the libraries (how a library value was worked out) have no level and
    are not part of this procedure - they are left out."""
    unplaced = [task for task in datagraph.get("@graph", [])
                if _is_task(task, namespace_collection) and "dcterms:isPartOf" not in task
                and ({"hlo:SeriesSpecific", "hlo:ExperimentSpecific"} & set(as_list(task.get("@type"))))
                and not any(_is_shell(task, name) for name in TOP_LEVEL_TASK_NAMES)]
    # The template of an open series gets its place only when the series is completed (rule 7c.5) -
    # if all its executions are placed, nothing is missing, it is only waiting.
    waiting = [task for task in unplaced
               if "hlo:SeriesSpecific" in as_list(task.get("@type")) and not _series_completed(datagraph)
               and as_list(task.get("hlo:hasSpecialization"))
               and all("dcterms:isPartOf" in (find_entity(datagraph, ref_id(s)) or {})
                       for s in as_list(task.get("hlo:hasSpecialization")))]
    unplaced = [task for task in unplaced if task not in waiting]
    if waiting:
        print(f"[Tasks] {len(waiting)} series template(s) wait for the series to be completed (rule 7c.5), "
              f"every experiment has them in place: {', '.join(get_display_label(t) for t in waiting)}")
    if unplaced:
        print(f"[Tasks] Warning: {len(unplaced)} task(s) are not part of any other task: "
              f"{', '.join(f'{get_display_label(t)} ({t['@id']})' for t in unplaced)}")


def _wants_series_times(task: dict, scope: str, namespace_collection: dict) -> bool:
    """Whether this task gets times at SERIES level too.

    Only the planning task does. Everywhere else a series entity is a template - the same
    procedure across the whole series - and a template has no single point in time, which is
    why add_time_entities asks at experiment level only. The planning of the series, though,
    happened once, at a definite moment; the experiment-level performances may carry the same
    time or a later one, where an individual run was only planned shortly before it.
    """
    if scope != "hlo:SeriesSpecific":
        return False
    return _task_class_of(task, namespace_collection) == "cpo:PlanningTask"




# What a task can carry of its OWN besides its parts. If it has none of it, it is a mere
# grouping: "Working up" summarizes analyses and withdrawals, but does nothing itself for
# which a purpose could be given.
OWN_CONTENT_PROPERTIES = ("cpo:aimsAt", "cpo:usedEquipment", "cpo:usedSoftware", "cpo:determines",
                          "cpo:hasInputValue", "cpo:executesProfile", "cpo:actsOn",
                          "cpo:generatedMediaObject")


def _is_pure_grouping_task(task: dict) -> bool:
    """Whether this task only holds others together."""
    if "dcterms:hasPart" not in task:
        return False
    return not any(prop in task for prop in OWN_CONTENT_PROPERTIES)


# How a section inherits its functions (rule 4.9): everything its parts do, as a union - not
# only what they agree on. An intersection would fail: a single "Putting on the lid"
# (Assembling) would leave "Charging the reactor" without Charging. This holds for EVERY task
# with parts, also for one that does something itself (Running the hydrogenation: ReactingChemicals
# as a purpose of its own, plus Mixing, Cooling, ... from the parts) - otherwise it would be the one
# exception for no reason.


def inherit_group_functions(datagraph: dict, namespace_collection: dict) -> int:
    """Give every task with parts the functions of its parts, in addition to its own.

    Runs at the very end, because a task does not know its parts while it is being described.
    "Charging the reactor" thus realizes Charging, Assembling (putting on the lid) and
    Determining (weighing in); "Establishing the values" realizes Determining and RecordingData;
    "Running the hydrogenation" keeps the ReactingChemicals it was asked for and adds what its parts do.
    A part with parts of its own is settled first, so everything below it counts.

    Returns how many tasks were given a function they did not have.
    """
    settled = {}

    def functions_of(task: dict) -> set:
        if task["@id"] in settled:
            return settled[task["@id"]]
        own = {ref_id(f) for f in as_list(task.get("cpo:realizesFunction"))}
        settled[task["@id"]] = own  # protection against cycles in dcterms:hasPart
        inherited = set()
        for part_ref in as_list(task.get("dcterms:hasPart")):
            part = find_entity(datagraph, ref_id(part_ref))
            if part is not None:
                inherited |= functions_of(part)
        settled[task["@id"]] = own | inherited
        return settled[task["@id"]]

    filled = 0
    for entity in datagraph.get("@graph", []):
        if not _is_task(entity, namespace_collection) or "dcterms:hasPart" not in entity:
            continue
        if entity.get("schema:name") in TASK_NAMES_WITHOUT_FUNCTION:
            continue
        own = {ref_id(f) for f in as_list(entity.get("cpo:realizesFunction"))}
        added = functions_of(entity) - own
        for function_id in sorted(added):
            set_property(entity, "cpo:realizesFunction", {"@id": function_id}, namespace_collection, True)
        if added:
            filled += 1
    return filled


def _link_functions(task: dict, task_type: str, task_label: str, scope: str, namespace_collection: dict,
                    datagraph: dict, todo_list: list = None, local_todo_list: list = None):
    """cpo:realizesFunction: what the task is meant to achieve, independently of how it was
    done. Stirring and shaking both realize cpo:Mixing.

    Mandatory, and deliberately without an escape hatch. If nothing on the list fits, that is
    a finding about the LIST - then the list gets an entry and the run is repeated. An
    "other" option would swallow exactly the cases it is supposed to surface and leave tasks
    without a function that nobody ever finds again.

    Three things keep the question answerable:
      - the choice is narrowed to the branches the task's class declares (offered_functions),
      - where that leaves exactly one function, the purpose follows from the class and is set
        without asking (a determination task: Determining; a sampling task: Sampling),
      - a task that only groups others is asked for its OWN purpose only, beyond what its
        parts do, and may have none (the parts' functions come along at the end,
        inherit_group_functions).

    Multi-valued: a task can serve more than one purpose, and then one alone would not be the
    whole truth.
    """
    if task.get("schema:name") in TASK_NAMES_WITHOUT_FUNCTION:
        return

    offered = offered_functions(task_type, namespace_collection)
    if not offered:
        print(f"[{scope}] No function is offered for {task_type} - check cpo:offersFunction in the ontology.")
        return

    if task.get("schema:name") in PROCEDURE_SECTION_NAMES:
        # Preparation, main operation, work-up have no purpose of their own, only that of their parts
        # (rule 7c.5a): an empty main operation thus claims nothing. ReactingChemicals is carried by the task
        # in it that brings the reaction about (rule 4.9).
        return

    if (task.get("schema:name") == ESTABLISHING_TASK_NAME and "dcterms:hasPart" not in task
            and not any(prop in task for prop in OWN_CONTENT_PROPERTIES)):
        # An EMPTY "Establishing the values" - no parts and nothing of its own (e.g. the series
        # template when the parts differ per experiment) - gets no function, like the procedure:
        # its purposes are those of its parts, and an empty section does nothing. If it carries
        # something of its own without parts (devices, determined values ...), it does something
        # itself and is asked like every task.
        return

    if len(offered) == 1:
        # The purpose follows from the class (determining, sampling, planning, recording, calibrating) -
        # a question with a single answer would be none.
        set_property(task, "cpo:realizesFunction", {"@id": offered[0]}, namespace_collection, True)
        print(f"[{scope}] Function of {task_label} follows from its class {task_type}: {offered[0].split(':', 1)[-1]}.")
        return

    if _is_pure_grouping_task(task):
        if task.get("schema:name") == ESTABLISHING_TASK_NAME:
            # The section of the determinations has no purpose besides that of its parts.
            return
        # A section does nothing of its own, it summarizes - but it can have a purpose none of its
        # parts has: "Reacting at room temperature" summarizes the stirring and still is the
        # reaction (ReactingChemicals sits at the task that spans the reaction time). Not asked,
        # the ReactingChemicals of the sheet would be lost.
        for function_id in ask_user_list(f"[{scope}] Which functions does {task_label} realize itself, beyond what its parts do?",
                                         sorted(offered), question_id="functions"):
            set_property(task, "cpo:realizesFunction", {"@id": function_id}, namespace_collection, True)
        return

    # One list of all functions offered instead of "another one?" with a stepwise choice: the
    # answer names the functions themselves (step 7, group C). A user interface can still show
    # the choice as a tree - the same list is stored.
    for function_id in ask_user_list(f"[{scope}] Which functions does {task_label} realize?", sorted(offered),
                                     question_id="functions", required=True):
        set_property(task, "cpo:realizesFunction", {"@id": function_id}, namespace_collection, True)


# The classes for which the question about the sample makes sense at all: they establish a
# value of something physical. A calculation or an assumption works on numbers, not on
# material - for them the question would be meaningless.
TASK_CLASSES_WORKING_ON_MATTER = ("cpo:MeasurementTask", "cpo:ObservationTask")

NOT_ON_A_SAMPLE = "No - it worked on the material itself"


def _samples_in_scope(datagraph: dict, scope: str, nr) -> list:
    """The materials that stand in for another one according to sosa:isSampleOf."""
    return [
        entity for entity in datagraph.get("@graph", [])
        if entity.get("sosa:isSampleOf")
        and _matches_scope_and_experiment(entity, scope, nr)
    ]


def _ask_feature_of_interest(task: dict, task_type: str, task_label: str, scope: str, nr, namespace_collection: dict, datagraph: dict):
    """sosa:hasFeatureOfInterest: what the task worked on, when that was not the batch
    itself but a sample drawn from it.

    This closes the gap the GC analysis had: it determines masses in the reactor,
    but what was handled was a sample. cpo:determines says WHICH VALUE a task established;
    this edge says ON WHAT it did so. Only both together are the whole
    statement.

    The question only comes if there is a sample in the crate at all - a material with
    sosa:isSampleOf, see creation/material_functions.py. A crate without sampling thus gets
    not a single additional question, and where there is one, it stands only at the
    classes that work on material.

    Asked only on the series level; the experiment version gets the edge to ITS sample
    (see _remap_feature_of_interest) - every experiment draws its own.
    """
    if task_type not in TASK_CLASSES_WORKING_ON_MATTER:
        return
    samples = _samples_in_scope(datagraph, scope, nr)
    if not samples:
        return

    choice = ask_entity_choice(
        f"[{scope}] Did {task_label} work on a sample rather than on the material itself?",
        samples, extra_options=[NOT_ON_A_SAMPLE], label_fn=get_display_label, question_id="feature_of_interest"
    )
    if choice == NOT_ON_A_SAMPLE:
        return
    sample = find_entity(datagraph, choice)
    if sample is not None:
        set_property(task, "sosa:hasFeatureOfInterest", sample, namespace_collection)


def _ask_observed(task: dict, task_type: str, task_label: str, scope: str, nr, namespace_collection: dict, datagraph: dict):
    """cpo:ObservationTask: what was observed - phases, materials (also streams) and devices
    (sosa:hasFeatureOfInterest, rule 4.11). Also when the observation gives no number (a
    colour, an appearance; the result then stands in the description of the task). As for the sample,
    cpo:determines says WHICH value the task established, this edge ON WHAT. Asked on the series level and
    rewritten in the experiment (_remap_feature_of_interest); a task that exists only in the experiment asks there."""
    if task_type != "cpo:ObservationTask":
        return
    candidates = [e for e in find_entities_by_type(datagraph, "cpo:Phase", namespace_collection, include_subclasses=True)
                  if _matches_scope_and_experiment(e, scope, nr)]
    candidates += [e for e in find_entities_by_type(datagraph, "cpo:MaterialRepresentation", namespace_collection, include_subclasses=True)
                   if _matches_scope_and_experiment(e, scope, nr) and e not in candidates]
    candidates += [d for d in _devices_for_scope(datagraph, namespace_collection, scope, nr) if d not in candidates]
    if not candidates:
        return
    for thing_id in ask_entity_list(f"[{scope}] Which phases, materials or devices did {task_label} observe (leave empty for none)?",
                                    candidates, label_fn=get_display_label, question_id="observed"):
        _add_feature_of_interest(task, find_entity(datagraph, thing_id), namespace_collection)


def _add_feature_of_interest(task: dict, thing: dict, namespace_collection: dict):
    """The first statement as a single value (as before for the sample), only a second one makes a list."""
    set_property(task, "sosa:hasFeatureOfInterest", thing, namespace_collection, bool(task.get("sosa:hasFeatureOfInterest")))


def _remap_feature_of_interest(series_task: dict, task: dict, nr: int, namespace_collection: dict, datagraph: dict):
    """Rewrite the sample (or observed phase) of the series template to that of THIS experiment -
    the same pattern as _remap_used_equipment for devices: the template says THAT work was done on
    a sample, the experiment says on which. Every one, not only the first (an observation can
    look at several phases)."""
    for series_id in [ref_id(v) for v in as_list(series_task.get("sosa:hasFeatureOfInterest"))]:
        series_thing = find_entity(datagraph, series_id)
        if series_thing is None:
            continue
        counterparts = [find_entity(datagraph, ref_id(ref)) for ref in as_list(series_thing.get("hlo:hasSpecialization"))
                        if ref_id(ref).endswith(f"_ExperimentSpecific_{nr}")]
        counterparts = [c for c in counterparts if c is not None]
        if counterparts:
            _add_feature_of_interest(task, counterparts[0], namespace_collection)
        else:
            print(f"[hlo:ExperimentSpecific] {get_display_label(series_thing)} has no counterpart in experiment {nr} - sosa:hasFeatureOfInterest not set.")


# Where a time comes from decides its accuracy (5b). Asked only for tasks that READ
# times - a planned duration (PlanningTask) or an assumed one (AssumptionTask) has no
# clock. The list is deliberately coarse; whoever wants to say more precisely which clock
# says so in the detail. No ";" in the options: it separates the answers of a list.
TIME_READING_TASK_TYPES = ("cpo:MeasurementTask", "cpo:ObservationTask")
TIME_SOURCES = [
    "Wristwatch", "Mobile phone", "Wall clock", "Computer clock", "Instrument clock",
    "Stopwatch or timer", "Data logger or control software", "File timestamp",
    "Camera or video timestamp", "Handwritten record (lab journal, run log)",
    "Printed document (report, certificate, delivery note)", "Estimated (no clock)", "Other",
]
TIME_VALUE_TYPES = ("time:Instant", "time:Duration")


def _determines_times(task: dict, datagraph: dict, todo_list: list, local_todo_list: list) -> bool:
    """Whether the task determines at least one time value (a moment or a duration)."""
    pools = [pool for pool in (datagraph, todo_list, local_todo_list) if pool is not None]
    for value_id in (ref_id(v) for v in as_list(task.get("cpo:determines"))):
        value = next((found for found in (find_entity(pool, value_id) for pool in pools) if found is not None), None)
        if value is not None and any(t in TIME_VALUE_TYPES for t in as_list(value.get("@type"))):
            return True
    return False


def _ask_time_source(task: dict, task_type: str, task_label: str, scope: str, namespace_collection: dict,
                     datagraph: dict, todo_list: list, local_todo_list: list) -> str:
    """For a task that reads times off something: where from (a fixed list, several allowed)
    and, optionally, which one exactly. Returns the sentence the description starts with, or
    "" for any other task or an empty answer.

    Text, not properties: the list says what KIND of clock, the specification which one
    (whose phone, which room, which computer) - that detail differs every time. Linking real
    clocks as devices of the library is left for later (docs/things_to_implement_after_me.md).
    """
    if task_type not in TIME_READING_TASK_TYPES or not _determines_times(task, datagraph, todo_list, local_todo_list):
        return ""
    sources = ask_user_list(f"[{scope}] Where were the times of {task_label} read off?", TIME_SOURCES,
                            question_id="time_sources")
    if not sources:
        return ""
    specification = ask_user(
        f"[{scope}] Please specify the source(s) of the times of {task_label} - whose phone or watch, which clock "
        f"in which room, which computer or software" + (" (required for 'Other')" if "Other" in sources else " (optional, leave empty to skip)") + "?",
        question_id="time_source_specification", required="Other" in sources).strip()
    sentence = f"Source of the times: {', '.join(sources)}."
    if specification:
        sentence = f"{sentence[:-1]} - {specification.rstrip('.')}."
    return sentence


def create_task(scope: str, nr: int, namespace_collection: dict, datagraph: dict, chemical_entity_library: dict, people_library: dict, todo_list: list, local_todo_list: list, evidence_known_cache: dict = None, stub: dict = None, name: str = None, settle_later: bool = False):
    """Describe a task - either a placeholder from the todo list (stub, the normal case: it
    already brings its task class and the values it determined, see
    helpers/evidence_reference.py) or a freely created task (stub=None, in which case the
    class is asked for). A free task brings its name when it comes from a list of further
    tasks (complete_all_tasks).

    The structure is NOT asked here - which task is part of which is settled in one place,
    once every task exists (sort_tasks). With settle_later the questions that depend on it
    wait as well: the function (a pure grouping task gets none) and the experiment times
    (see _settle_experiment_times). Without it - a task that only comes into being after
    the sorting - they are asked right away, as before.
    """
    if stub is not None:
        task = stub
        task_type = _task_class_of(task, namespace_collection)
        # Taken off the to-do list before the questions run: the own stub must not appear in any
        # choice that is asked during the description.
        delete_todo_entity(todo_list, task)
        delete_todo_entity(local_todo_list, task)
    else:
        task_type = check_type(ask_user(f"[{scope}] What type of Task is this?", free_task_types(namespace_collection), question_id="task_type"), namespace_collection)
        experiment_number = nr if scope == "hlo:ExperimentSpecific" else None
        # First the name, then the ID from the name (4.3) - required, because it is the ID (D2).
        # The question about the name stands below for both ways, here it is brought forward.
        free_task_name = name if name is not None else ask_name(scope, "Task")
        task_id = claim_id(make_root_id("Task", free_task_name, scope, experiment_number),
                               datagraph, todo_list, local_todo_list, what=f"The task '{free_task_name}'")
        task = {"@id": task_id, "@type": [task_type, scope]}

    # Straight into the graph, before any questions: generate_id sees only the datagraph
    # and the to-do list, and a task can have a subtask OF THE SAME type (_ask_subtasks
    # calls create_task again). If the task were only stored at the end, the subtask would
    # get the same ID - and add_entity then silently discards the parent that comes later
    # (see helpers/entities.py: same @id -> return False), while all references to it point
    # at nothing. The graph holds a reference to the same dict, so the following
    # set_property calls still land in the graph.
    add_entity(datagraph, task)

    determined = [ref_id(v) for v in as_list(task.get("cpo:determines"))]
    if determined:
        # Without this hint the user would not know, when naming it, which activity is meant -
        # the placeholder comes from a value, not from a question.
        print(f"\n[{scope}] This task was created for the following value(s): {', '.join(determined)}")

    # A task that already brings its name - a shell, an automatic assumption of the generator -
    # is not asked for it: the name is its ID, and another answer would only make it
    # unrecognizable.
    if stub is None:
        name = free_task_name
    elif stub.get("schema:name"):
        name = stub["schema:name"]
    else:
        name = ask_optional_name(scope, "Task", task["@id"])
    set_property(task, "schema:name", name, namespace_collection)
    print(f"\n=== Now describing Task \"{name}\" ({task['@id']}, {scope}) ===")

    # The description is REQUIRED for an assumption (required=True, the question is repeated
    # until something is there): WHAT is assumed stands in cpo:determines - WHY it may be
    # assumed is a different reason every time and cannot be recorded in a standard way.
    # Without this sentence an assumption cannot be checked later, and a wrong one cannot be
    # recognized as wrong. Exactly for that reason cpo:hasInputValue can be optional: not every
    # assumption is derived from another VALUE.
    mandatory_description = task_type == "cpo:AssumptionTask"
    if mandatory_description:
        description_hint = " (required: what is assumed, and why it may be assumed)"
    elif task_type == "cpo:CalculationTask":
        description_hint = " (what was done and how - include the formula/method used)"
    else:
        description_hint = " (optional, leave empty to skip)"
    time_source = _ask_time_source(task, task_type, name, scope, namespace_collection, datagraph, todo_list, local_todo_list)
    description = ask_user(f"[{scope}] Please describe {name}{description_hint}?",
                           question_id="description", required=mandatory_description)
    # The time source stands as the first sentence of the description, not in a property of
    # its own: which clock, whose phone, which room cannot sensibly be captured as properties
    # (rule 4.7).
    description = " ".join(part for part in (time_source, description.strip()) if part)
    if description:
        set_property(task, "schema:description", description, namespace_collection)


    _ask_used_equipment(task, name, scope, nr, namespace_collection, datagraph)
    _ask_used_software(task, name, scope, namespace_collection)
    _ask_performed_by(task, task_type, name, scope, namespace_collection, people_library)

    _ask_feature_of_interest(task, task_type, name, scope, nr, namespace_collection, datagraph)
    _ask_observed(task, task_type, name, scope, nr, namespace_collection, datagraph)

    if task_type in MANDATORY_INPUT_TASK_TYPES:
        _link_input_values(task, name, scope, nr, namespace_collection, datagraph)
    elif task_type in OPTIONAL_INPUT_TASK_TYPES:
        _link_optional_input_values(task, name, scope, nr, namespace_collection, datagraph)

    if task_type == "cpo:TransferTask":
        _link_aims_at(task, name, scope, namespace_collection, datagraph, _all_port_crossing_transfers_for_scope(datagraph, scope, nr), mandatory=True)
    else:
        _link_aims_at(task, name, scope, namespace_collection, datagraph, _all_transfers_and_reactions_for_scope(datagraph, scope, nr), mandatory=False)

    if task_type == "cpo:OperationTask":
        _ask_executes_profile(task, name, scope, nr, namespace_collection, datagraph, todo_list, local_todo_list)
        _ask_acts_on(task, name, scope, nr, namespace_collection, datagraph)

    _ask_generated_media_object(task, name, scope, namespace_collection, datagraph)

    if settle_later:
        # Function and times hang on the structure, and that is settled only after the sorting
        # (see complete_all_tasks): whether the task only summarizes decides the function
        # question, and the evidence of the times is to be made in the same order as the start
        # offsets, which do not work without a parent task.
        if _wants_series_times(task, scope, namespace_collection):
            add_time_entities(task, scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache,
                              allow_series=True)
        return task

    _link_functions(task, task_type, name, scope, namespace_collection, datagraph, todo_list, local_todo_list)

    if scope == "hlo:ExperimentSpecific" or _wants_series_times(task, scope, namespace_collection):
        add_time_entities(task, scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache,
                          allow_series=True, required=_required_times(task, scope))

    return task


# ---------------------------------------------------------------------------
# Task - hlo:SeriesSpecific -> hlo:ExperimentSpecific (specializes a
# series template, recursively over its subtasks)
# ---------------------------------------------------------------------------

def specialize_task_for_experiment(series_task: dict, nr: int, namespace_collection: dict, datagraph: dict, chemical_entity_library: dict, people_library: dict, todo_list: list, local_todo_list: list, evidence_known_cache: dict = None):
    """Create the experiment-level performance of ONE series template.

    Where a placeholder for this experiment already exists - because an experiment value
    created the task, see helpers/evidence_reference.py - it is used and the cpo:determines
    links it brings along are kept; otherwise the task is created here. Name and equipment
    come from the template, and only the experiment-specific entries are asked for (aimsAt,
    actsOn, ...). Structure, function and times follow after the sorting (complete_all_tasks).
    """
    scope = "hlo:ExperimentSpecific"
    series_task_type = _task_class_of(series_task, namespace_collection)
    task_type = check_type(series_task_type, namespace_collection)

    stubs = _experiment_stubs_for(series_task, nr, datagraph, todo_list)
    if stubs:
        task = stubs[0]
        delete_todo_entity(todo_list, task)
        delete_todo_entity(local_todo_list, task)
        # There are several stubs for the same experiment when two placeholders were merged
        # on the series level - then their experiment placeholders belong together as well.
        for extra in stubs[1:]:
            _absorb_stub(task, extra, namespace_collection, datagraph, todo_list)
    else:
        task_id = _experiment_id_for(series_task, nr, task_type, datagraph, todo_list + local_todo_list)
        task = {"@id": task_id, "@type": [task_type, scope]}

    add_entity(datagraph, task)  # early, see the comment in create_task

    name = series_task.get("schema:name") or generate_name(task["@id"])
    set_property(task, "schema:name", name, namespace_collection)
    print(f"\n=== Now describing Task \"{name}\" ({task['@id']}, {scope}, Experiment {nr}) ===")

    set_property(task, "hlo:specializationOf", series_task, namespace_collection)
    set_property(series_task, "hlo:hasSpecialization", task, namespace_collection, True)

    if "schema:description" in series_task:
        set_property(task, "schema:description", series_task["schema:description"], namespace_collection)

    _remap_used_equipment(series_task, task, nr, namespace_collection, datagraph)
    # Software is a library entry, the same on both levels - taken over like the
    # description, not asked again.
    for software_ref in as_list(series_task.get("cpo:usedSoftware")):
        set_property(task, "cpo:usedSoftware", software_ref, namespace_collection, True)
    _remap_feature_of_interest(series_task, task, nr, namespace_collection, datagraph)

    # cpo:performedBy is DELIBERATELY not handed down: if the template carries a statement,
    # it is precisely because it holds for all experiments - the experiment task inherits it
    # via hlo:specializationOf. It is asked here only where the template said that it differs
    # between the experiments (see the block at _ask_performed_by).
    _ask_performed_by_for_experiment(task, series_task, task_type, name, scope, namespace_collection, people_library)

    if task_type in MANDATORY_INPUT_TASK_TYPES:
        _link_input_values(task, name, scope, nr, namespace_collection, datagraph)
    elif task_type in OPTIONAL_INPUT_TASK_TYPES:
        _link_optional_input_values(task, name, scope, nr, namespace_collection, datagraph)

    if task_type == "cpo:TransferTask":
        _link_aims_at(task, name, scope, namespace_collection, datagraph, _all_port_crossing_transfers_for_scope(datagraph, scope, nr), mandatory=True)
    else:
        _link_aims_at(task, name, scope, namespace_collection, datagraph, _all_transfers_and_reactions_for_scope(datagraph, scope, nr), mandatory=False)

    if task_type == "cpo:OperationTask":
        _ask_executes_profile(task, name, scope, nr, namespace_collection, datagraph, todo_list, local_todo_list)
        _ask_acts_on(task, name, scope, nr, namespace_collection, datagraph)

    _ask_generated_media_object(task, name, scope, namespace_collection, datagraph)

    # No subtasks, no times, no function: the structure only comes into being with the
    # sorting (sort_tasks), and what hangs on it comes afterwards
    # (_settle_functions, _settle_experiment_times).
    return task


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


# How often the loop of latecomers starts anew at most. Every round describes a task that
# can itself have times again - and every recorded time creates a new placeholder. Whoever
# records times endlessly there goes round in circles; then the loop stops and says what
# is left open.
MAX_LEFTOVER_ROUNDS = 5


def _promote_local_stubs(todo_list: list, local_todo_list: list, namespace_collection: dict) -> int:
    """Move placeholders from the local into the global to-do list.

    All stages of the generator collect newly made placeholders in a local list,
    which main.py merges into the global one at the end of the stage. For the task stage that
    is too late: what comes into being while a task is described - above all the placeholders
    of its own times, since a start offset and a duration are recorded values too - would
    not be seen by any loop of this stage any more. It would stay on the to-do list, while the
    value in the crate would point via cpo:hasDeterminationTask at an ID that never exists there.
    """
    moved = 0
    for item in list(local_todo_list):
        if not _is_task(item, namespace_collection):
            continue
        local_todo_list.remove(item)
        if find_entity(todo_list, item["@id"]) is None:
            todo_list.append(item)
        moved += 1
    return moved


def _complete_leftover_stubs(scope: str, nr, namespace_collection: dict, datagraph: dict, chemical_entity_library: dict,
                             people_library: dict, todo_list: list, local_todo_list: list, evidence_known_cache: dict, owner: dict = None):
    """Work through the placeholders that came into being only AFTER the sorting - above all
    the evidence of the times and start offsets.

    Deliberately the same loop as for all other placeholders: every one is described
    on its own. Whether several of them are really the same activity - all start offsets
    and durations of an experiment come, for instance, from the same source, the clock or the
    lab journal -, is decided by the user per placeholder via _offer_existing_task_for_stub
    and not by this code. An automatic rule (say "everything of one
    task class belongs together") would be guessed, not recorded.

    Unlike the loops above this one does not work on a snapshot, but
    asks for the list anew after every task - describing one creates new
    placeholders all the time. Every one is placed on its own (_place_late_task): the sorting
    has already run at this point.
    """
    # Passes instead of single rounds: every pass works through all open placeholders, and each
    # of them asks itself whether a task described already covers it. Limited is the number of
    # passes - new placeholders only come into being when a new task gets times.
    for _ in range(MAX_LEFTOVER_ROUNDS):
        _promote_local_stubs(todo_list, local_todo_list, namespace_collection)
        open_stubs = task_stubs(todo_list, scope, nr, namespace_collection)
        if not open_stubs:
            return

        for stub in open_stubs:
            if find_entity(todo_list, stub["@id"]) is None:
                continue
            with question_path("task", task_question_key(stub, datagraph, todo_list, local_todo_list)):
                if _offer_existing_task_for_stub(stub, scope, nr, namespace_collection, datagraph, todo_list) is not None:
                    continue
                task = create_task(scope, nr, namespace_collection, datagraph, chemical_entity_library,
                                   people_library, todo_list, local_todo_list, evidence_known_cache, stub=stub)
                _place_late_task(task, scope, nr, owner, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache)

    _promote_local_stubs(todo_list, local_todo_list, namespace_collection)
    still_open = [stub["@id"] for stub in task_stubs(todo_list, scope, nr, namespace_collection)]
    if still_open:
        print(f"[{scope}] Warning: after {MAX_LEFTOVER_ROUNDS} rounds these placeholders are still open: "
              f"{', '.join(still_open)}. Each round recorded new times, which created new placeholders.")


def _settle_functions(namespace_collection: dict, datagraph: dict, number_experiments: int, question_keys: dict,
                      todo_list: list, local_todo_list: list):
    """The function question, now that the structure stands (_link_functions asks a pure
    grouping task only for its own purpose beyond its parts, and only now is it known which
    those are).

    Series templates first; their performances take the function over, exactly as they take
    over name and description. Then the tasks that exist in one experiment only.
    """
    for task in _tasks_of(datagraph, "hlo:SeriesSpecific", None, namespace_collection):
        # Only the ones described here are asked; one created completely already still hands on its
        # function.
        if task["@id"] in question_keys:
            with question_path("task", question_keys[task["@id"]]):
                _link_functions(task, _task_class_of(task, namespace_collection), task.get("schema:name"), "hlo:SeriesSpecific",
                                namespace_collection, datagraph, todo_list, local_todo_list)
        if "cpo:realizesFunction" in task:
            for nr in range(1, number_experiments + 1):
                spec = _specialization_in(task, nr, datagraph)
                if spec is not None:
                    # A copy of its own per experiment: with the same list, what an experiment later inherits
                    # from its parts (inherit_group_functions) would also arrive at the series.
                    functions = task["cpo:realizesFunction"]
                    copied = [dict(f) for f in functions] if isinstance(functions, list) else dict(functions)
                    set_property(spec, "cpo:realizesFunction", copied, namespace_collection)

    for nr in range(1, number_experiments + 1):
        with question_path("experiment", nr):
            for task in _tasks_of(datagraph, "hlo:ExperimentSpecific", nr, namespace_collection):
                if "hlo:specializationOf" in task or task["@id"] not in question_keys:
                    continue
                with question_path("task", question_keys[task["@id"]]):
                    _link_functions(task, _task_class_of(task, namespace_collection), task.get("schema:name"), "hlo:ExperimentSpecific",
                                    namespace_collection, datagraph, todo_list, local_todo_list)


def _settle_experiment_times(nr: int, namespace_collection: dict, datagraph: dict, question_keys: dict,
                             todo_list: list, local_todo_list: list, evidence_known_cache: dict):
    """Times and start offsets of the tasks of experiment nr, now that every task knows its
    parent (a start offset is relative to it).

    Walked in the order the old recursive specialization used - through the series
    structure, a part before its parent, the part's offset right after its own times - so
    the evidence placeholders of the times arise in the same order as before. Which of them
    comes first decides which one the task reading the times grows out of, and with it that
    task's ID. After the series structure come the tasks of this experiment alone, in the
    order they were described.
    """
    scope = "hlo:ExperimentSpecific"
    done = set()

    # Times and offset of a task in ONE path block: their evidence is asked as lists of the
    # exemplar as soon as the block is left (helpers/value_sources.py). Two blocks one after
    # the other would give two lists under the same key.
    def settle(task, key, allow_series, times, offset):
        with question_path("task", key):
            if times:
                add_time_entities(task, scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache,
                                  allow_series=allow_series, required=_required_times(task, scope))
                done.add(task["@id"])
            if offset and "dcterms:isPartOf" in task:
                add_start_offset(task, scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache)

    # A part comes before its parent, its offset directly after its own times.
    def walk(series_task, as_part):
        for part_ref in as_list(series_task.get("dcterms:hasPart")):
            part = find_entity(datagraph, ref_id(part_ref))
            if part is not None:
                walk(part, as_part=True)
        spec = _specialization_in(series_task, nr, datagraph)
        if spec is not None:
            key = question_keys.get(series_task["@id"]) or task_question_key(series_task, datagraph)
            # Whether an offset is asked is decided by the experiment task itself, not by its template:
            # in an open series the template still stands free, while its execution is already part of
            # "Establishing the values" (see _series_completed).
            settle(spec, key, allow_series=False, times=spec["@id"] not in done, offset=as_part or "dcterms:isPartOf" in spec)

    for series_task in _tasks_of(datagraph, "hlo:SeriesSpecific", None, namespace_collection):
        if "dcterms:isPartOf" not in series_task:
            walk(series_task, as_part=False)

    for task in _tasks_of(datagraph, scope, nr, namespace_collection):
        if task["@id"] in done:
            continue
        key = question_keys.get(task["@id"]) or task_question_key(task, datagraph, todo_list, local_todo_list)
        settle(task, key, allow_series=True, times=True, offset=True)


def _born_from_files(series_task: dict) -> bool:
    """A series task that a file brought into being (helpers/evidence_reference.py: the placeholder is named
    after its file, Task_for_File_...) - it exists in an experiment only where a file or value names it."""
    return strip_crate_prefix(series_task["@id"]).rsplit("/", 1)[-1].startswith("Task_for_File_")


def complete_all_tasks(namespace_collection: dict, datagraph: dict, chemical_entity_library: dict, people_library: dict, todo_list: list, number_experiments: int) -> list:
    """Describe every task, then sort them into each other, then ask what hangs off the
    structure.

    1. Series: every placeholder from the todo list (every value received one while being
       recorded, see helpers/evidence_reference.py: ensure_determination_task_stub), then the
       further series tasks no value triggered (the sections, cleaning, ...).
    2. Per experiment: the performance of every series task, the placeholders without a
       series template, and the tasks of this experiment alone.
    3. Sorting (sort_tasks) - one place, from above, once every task exists.
    4. cpo:isProcedureOf for whatever sits at the top; the function question, which skips
       pure grouping tasks; the experiment times and start offsets.
    5. The placeholders that step 4 created (the evidence of the times) - described and
       placed one by one (_place_late_task).

    The question paths are keyed through task_question_key (see there) rather than a running
    loop counter, and they are FLAT: a task's answers stand under its own key, not under the
    chain of its parents - moving a task into another section does not move its answers.
    """
    local_todo_list = []
    evidence_known_cache = {}
    # The table holds only for this pass (see the block at _ask_performed_by).
    _performed_by_mode.clear()
    # The key under which every task was described - the later steps ask on under the same one.
    # Not computed again: a task created freely that took over values while it was described
    # would otherwise get another one (task_question_key).
    question_keys = {}

    series_entities = find_entities_by_type(datagraph, "cpo:ExperimentalSeries", namespace_collection)
    series_entity = series_entities[0] if series_entities else None
    # Order = order of creation (create_series/create_experiment append to @graph
    # one after the other) = experiment number.
    experiment_entities = find_entities_by_type(datagraph, "cpo:SingleExperiment", namespace_collection)

    # First tidy up the placeholders that could not find a series template yet when they were
    # recorded (see reattach_orphan_task_stubs) - after that the structure of the levels
    # stands, and the series loop below really sees all templates.
    reattached = reattach_orphan_task_stubs(todo_list, datagraph, namespace_collection)
    if reattached:
        print(f"[Tasks] {reattached} experiment task placeholder(s) were attached to a series template afterwards.")

    ensure_base_shell(namespace_collection, datagraph, todo_list, local_todo_list)
    _promote_local_stubs(todo_list, local_todo_list, namespace_collection)

    def describe(scope, nr, key, **kwargs):
        with question_path("task", key):
            task = create_task(scope, nr, namespace_collection, datagraph, chemical_entity_library, people_library,
                               todo_list, local_todo_list, evidence_known_cache, settle_later=True, **kwargs)
        question_keys[task["@id"]] = key
        return task

    print("\n--- Tasks: Series level ---")
    series_tasks = []
    # Copy of the stub list: todo_list shrinks while it is worked through (delete_todo_entity).
    for stub in list(task_stubs(todo_list, "hlo:SeriesSpecific", None, namespace_collection)):
        if find_entity(todo_list, stub["@id"]) is None:
            continue
        key = task_question_key(stub, datagraph, todo_list, local_todo_list)
        # Has a task described already determined this value too? The GC analysis measures three
        # masses in one run - the first placeholder becomes the task, the two others name it here.
        # The fixed order (task_stubs) makes clear which tasks exist at this point.
        with question_path("task", key):
            if _offer_existing_task_for_stub(stub, "hlo:SeriesSpecific", None, namespace_collection, datagraph, todo_list) is not None:
                continue
        series_tasks.append(describe("hlo:SeriesSpecific", 1, key, stub=stub))

    # As a list of names instead of "another one?" with a counter (helpers/identifiers.py: name_list):
    # every task then stands under "task:<name>", a new section shifts no other.
    extra_names = ask_user(
        "[hlo:SeriesSpecific] Which further tasks does this series have that no recorded value asked for (e.g. the sections of the procedure, cleaning, waiting)? Their names, separated by ';' (leave empty if none)",
        answer_type=name_list, question_id="extra_task_names"
    )
    for extra_name in extra_names:
        key = key_name(make_root_id("Task", extra_name, "hlo:SeriesSpecific"))
        series_tasks.append(describe("hlo:SeriesSpecific", 1, key, name=extra_name))

    for e in range(number_experiments):
        nr = e + 1
        with question_path("experiment", nr):
            print(f"\n--- Tasks: Experiment {nr} ---")
            # ALL series tasks, not only the ones described here: a task that already stands finished in
            # the graph would otherwise only come in through the recursion over the subtasks.
            for series_task in _tasks_of(datagraph, "hlo:SeriesSpecific", None, namespace_collection):
                # A task that came only from files existed only in the experiments whose files (or values)
                # name it - its placeholder is already there (rule 4a.4: the NMR only in one experiment).
                # Without it, it would be claimed in every experiment.
                if _born_from_files(series_task) and not _experiment_stubs_for(series_task, nr, datagraph, todo_list):
                    print(f"[Experiment {nr}] {get_display_label(series_task)} comes from files of other experiments only - not part of this one.")
                    continue
                key = question_keys.get(series_task["@id"]) or task_question_key(series_task, datagraph, todo_list, local_todo_list)
                with question_path("task", key):
                    spec = specialize_task_for_experiment(series_task, nr, namespace_collection, datagraph, chemical_entity_library,
                                                          people_library, todo_list, local_todo_list, evidence_known_cache)
                question_keys[spec["@id"]] = key

            # Placeholders without a series template: they only come into being when an experiment value
            # hangs at an actual without a series counterpart (see _series_anchor).
            for stub in list(task_stubs(todo_list, "hlo:ExperimentSpecific", nr, namespace_collection)):
                if find_entity(todo_list, stub["@id"]) is None:
                    continue
                key = task_question_key(stub, datagraph, todo_list, local_todo_list)
                with question_path("task", key):
                    # Often the activity that determined this value already has a task -
                    # the flow at the MFM and the evidence that gas flowed at the sparger at all
                    # are the same reading. Without the question this silently becomes a
                    # second task.
                    if _offer_existing_task_for_stub(stub, "hlo:ExperimentSpecific", nr, namespace_collection, datagraph, todo_list) is not None:
                        continue
                describe("hlo:ExperimentSpecific", nr, key, stub=stub)

            extra_names = ask_user(
                f"[hlo:ExperimentSpecific] Which additional tasks only occurred in Experiment {nr} (not part of the series template)? Their names, separated by ';' (leave empty if none)",
                answer_type=name_list, question_id="extra_task_names"
            )
            for extra_name in extra_names:
                describe("hlo:ExperimentSpecific", nr, key_name(make_root_id("Task", extra_name, "hlo:ExperimentSpecific", nr)), name=extra_name)

    print("\n--- Tasks: which task is part of which ---")
    sort_tasks(namespace_collection, datagraph, number_experiments, question_keys)

    if series_entity is not None:
        for task in _tasks_of(datagraph, "hlo:SeriesSpecific", None, namespace_collection):
            if "dcterms:isPartOf" not in task and _belongs_in_procedure(task, namespace_collection):
                _set_procedure(task, series_entity, namespace_collection)
    for nr in range(1, number_experiments + 1):
        experiment_entity = experiment_entities[nr - 1] if nr - 1 < len(experiment_entities) else None
        if experiment_entity is None:
            continue
        for task in _tasks_of(datagraph, "hlo:ExperimentSpecific", nr, namespace_collection):
            if "dcterms:isPartOf" not in task and _belongs_in_procedure(task, namespace_collection):
                _set_procedure(task, experiment_entity, namespace_collection)

    _settle_functions(namespace_collection, datagraph, number_experiments, question_keys, todo_list, local_todo_list)

    for nr in range(1, number_experiments + 1):
        with question_path("experiment", nr):
            _settle_experiment_times(nr, namespace_collection, datagraph, question_keys, todo_list, local_todo_list, evidence_known_cache)
            # Finally the latecomers: placeholders that came into being only while the times were
            # recorded.
            experiment_entity = experiment_entities[nr - 1] if nr - 1 < len(experiment_entities) else None
            _complete_leftover_stubs("hlo:ExperimentSpecific", nr, namespace_collection, datagraph, chemical_entity_library,
                                     people_library, todo_list, local_todo_list, evidence_known_cache, owner=experiment_entity)

    _report_unplaced(datagraph, namespace_collection)

    # At the very end: every task with parts inherits the purposes of its parts. Only now is the
    # structure settled, before that no task knows its parts.
    inherited = inherit_group_functions(datagraph, namespace_collection)
    if inherited:
        print(f"[Tasks] {inherited} task(s) with parts took over the function(s) of their parts.")

    return local_todo_list
