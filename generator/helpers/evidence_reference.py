

from contextlib import contextmanager
from datetime import datetime

from helpers.user_io import ask_user, question_path
from helpers.entities import add_entity, find_entity, find_entities_by_type_interactive, ref_id, as_list, value_label, registered_library
from helpers.properties import set_property, set_literal_property, check_type
from helpers.identifiers import claim_id, make_member_id, make_root_id, make_specialization_id, level_key
from helpers.todo_functions import add_todo_item
from helpers.ontology_functions import find_entity_in_ontology, find_individuals_of_class, shorten_id
from creation.media_object_functions import create_time_instant, pick_column_for_series_variable
from helpers.profile_variables import create_scalar_variable, create_profile_variable, units_for_quantity_kind, NO_UNIT_OPTION, fixed_unit_for_quantity_kind, ask_unit, fraction_value_hint, fraction_answer_type
from helpers.units import DURATION_UNITS


# ---------------------------------------------------------------------------
# hlo:EvidenceType/hlo:ReferenceType individuals (hlo:Measured/Observed/
# Calculated, hlo:Planned/Controlled/Set/Assumed) - each carries in the ontology
# hlo:determinedByTaskClass, which points at the matching cpo:Task subclass
# (see ensure_determination_task_stub below).
# ---------------------------------------------------------------------------
def evidence_types(namespace_collection):
    """The hlo:EvidenceType individuals from the ontology - not maintained in code."""
    return find_individuals_of_class("hlo:EvidenceType", namespace_collection)


def reference_types(namespace_collection):
    """The hlo:ReferenceType individuals from the ontology. This used to be a list in the
    code, and that is exactly what drifted apart: hlo:Literature existed in the ontology but
    was not entered here, and so could not be chosen."""
    return find_individuals_of_class("hlo:ReferenceType", namespace_collection)

# "unit:" is declared as xmlns:unit in the ChemicalProcessOntology (http://qudt.org/vocab/unit/,
# right next to quantitykind:) - a "unit:xxx" value is therefore stored by set_property as a
# {"@id": ...} link, not as a plain string. Libraries and crate use qudt:hasUnit with an IRI value
# throughout (rule 4.3). DURATION_UNITS and the table of units are in
# generator/config/units_and_quantity_kinds.json (helpers/units.py, rule 4.5).

# NOTE: cpo:Occurrence, cpo:hasOccurrenceValue, cpo:Occurred, cpo:NotOccurred
# still have to be added to the ontology.
def occurrence_values(namespace_collection):
    """The cpo:OccurrenceValue individuals from the ontology (cpo:Occurred/cpo:NotOccurred)."""
    return find_individuals_of_class("cpo:OccurrenceValue", namespace_collection)


# The value of an occurrence status is settled before its evidence or
# reference is asked: "how often? (0 = did not occur)" said it
# (helpers/time_occurrence.py: record_occurrences). Then it is not asked again.
_occurrence_value_preset = []


@contextmanager
def occurrence_value_preset(value: str):
    """Within the block, the value of an occurrence status (cpo:Occurred/cpo:NotOccurred) is
    taken as given instead of being asked for its evidence or reference."""
    _occurrence_value_preset.append(value)
    try:
        yield
    finally:
        _occurrence_value_preset.pop()

# Bounds instead of exact values (see hlo:hasLowerBound/hasUpperBound in the ontology):
# hold only for Scalar and time:Instant - Series/Profile/Duration/Occurrence stay exact.
VALUE_EXACTNESS_QUESTION = "Is this an exact value or only a limit?"
VALUE_EXACTNESS_OPTIONS = ["Exact value", "Lower bound", "Upper bound", "Lower and upper bound"]


# Almost all questions in this module are asked from SHARED code both for
# add_evidence and for add_reference (e.g. _ask_bounds) - and add_evidence/
# add_reference are called for the same quantity directly one after the other,
# i.e. under the same question path (see helpers/process_variables.py). Without
# a distinction the two calls would make the same key.
# Instead of touching every caller (with question_path("evidence"/"reference")
# around each of the many calls of add_evidence/add_reference in the whole
# project), a "role_word" ("evidence"/"reference") is therefore built into the
# question_id as a prefix - determined once at the root (add_evidence/
# add_reference) and handed on from there.


def _ask_and_set_value_role_type(entity: dict, role: str, namespace_collection: dict) -> str:
    """Ask for and set hlo:hasEvidenceType (role="hlo:Evidence") or
    hlo:hasReferenceType (role="hlo:Reference") on `entity`.

    Called wherever an evidence or reference entity is completed (reused, freshly
    resolved, or as a todo placeholder), together with the @type multi-typing (see the
    callers).

    Returns the chosen answer ("hlo:Measured", for example); every caller passes it
    straight on to ensure_determination_task_stub, which looks up the task class from it
    (see there).
    """
    if role == "hlo:Evidence":
        answer = ask_user("Of what evidence type is this?", evidence_types(namespace_collection), question_id="evidence_type")
        set_property(entity, "hlo:hasEvidenceType", {"@id": answer}, namespace_collection)
    else:
        answer = ask_user("Of what reference type is this?", reference_types(namespace_collection), question_id="reference_type")
        set_property(entity, "hlo:hasReferenceType", {"@id": answer}, namespace_collection)
        # The source stands at the reference (rule 4.1). Asked for planned and literature values - the other types (assumed, set, controlled) have no document they come
        # from. Empty: no source known.
        if answer in SOURCED_REFERENCE_TYPES:
            source = ask_user(f"Where does this {answer.split(":")[-1].lower()} value come from - a document, a DOI, a URL "
                              f"(leave empty if not known)?", question_id="reference_source")
            if source.strip():
                set_property(entity, "hlo:hasSource", source.strip(), namespace_collection)
    return answer


# Reference types whose source is asked (_ask_and_set_value_role_type).
SOURCED_REFERENCE_TYPES = ("hlo:Planned", "hlo:Literature")


def _ask_bounds(scope: str, role_word: str, label: str, value_hint: str = "", quantity_kind: str = None):
    """Ask whether a value is exact or only known as a lower/upper bound (point 9: bounds
    instead of exact values).

    Returns (is_exact, lower, upper). With is_exact=True, lower and upper are always None;
    otherwise at least one of the two holds a value. Empty input counts as None, and open
    and closed bounds are not distinguished.

    For a fraction (quantity_kind, see FRACTION_QUANTITY_KINDS in
    helpers/profile_variables.py) the bounds are checked like a plain value: percentages
    converted, the range 0..1 enforced.
    """
    value_hint = value_hint + fraction_value_hint(quantity_kind)
    answer_type = fraction_answer_type(quantity_kind)
    exactness = ask_user(f"[{scope}] {VALUE_EXACTNESS_QUESTION}", VALUE_EXACTNESS_OPTIONS, question_id=f"{role_word}_exactness")
    if exactness == "Exact value":
        return True, None, None

    lower = upper = None
    if exactness in ("Lower bound", "Lower and upper bound"):
        answer = ask_user(f"[{scope}] Lower bound for the {role_word} of {label}{value_hint}?", answer_type=answer_type, question_id=f"{role_word}_lower_bound")
        lower = answer.strip() or None
    if exactness in ("Upper bound", "Lower and upper bound"):
        answer = ask_user(f"[{scope}] Upper bound for the {role_word} of {label}{value_hint}?", answer_type=answer_type, question_id=f"{role_word}_upper_bound")
        upper = answer.strip() or None
    return False, lower, upper


def _value_id(variable: dict, role: str, scope: str, nr) -> str:
    """Content-based ID of the next evidence/reference value of a variable (4.2):
    "#Volume_Material_Sample_In_Vial_Reference_1_ExperimentSpecific_1". The number counts
    only the values this variable already has in this role - a value added elsewhere never
    moves it."""
    prop = "hlo:hasEvidence" if role == "hlo:Evidence" else "hlo:hasReference"
    role_word = "Evidence" if role == "hlo:Evidence" else "Reference"
    experiment_number = nr if scope == "hlo:ExperimentSpecific" else None
    return make_member_id(variable["@id"], role_word, len(as_list(variable.get(prop))) + 1, scope, experiment_number)


def _create_bounded_scalar_variable(scope: str, nr: int, namespace_collection: dict, datagraph: dict, global_todo_list: list, local_todo_list: list, lower, upper, label: str, unit_options: list = None, unit: str = None, *, question_id_prefix: str, entity_id: str):
    """Like create_scalar_variable (helpers/profile_variables.py), but with hlo:hasLowerBound/hasUpperBound instead of qudt:value."""
    scalar_type = check_type("cpo:ScalarVariable", namespace_collection)
    experiment_number = nr if scope == "hlo:ExperimentSpecific" else None
    scalar_id = claim_id(entity_id, datagraph, global_todo_list, local_todo_list)
    scalar = {"@id": scalar_id, "@type": [scalar_type, scope]}
    if lower is not None:
        set_literal_property(scalar, "hlo:hasLowerBound", lower, "xsd:decimal", namespace_collection)
    if upper is not None:
        set_literal_property(scalar, "hlo:hasUpperBound", upper, "xsd:decimal", namespace_collection)

    # Both bounds stand in the same unit - one unit per value, as for the plain
    # scalar. The same switch as in create_scalar_variable: a fixed unit
    # (fraction -> UNITLESS) or asked. As {"@id": ...}, the reason is given there.
    unit_answer = unit if unit is not None else ask_unit(label, scope, unit_options, question_id_prefix)
    if unit_answer and unit_answer != NO_UNIT_OPTION:
        set_property(scalar, "qudt:hasUnit", {"@id": unit_answer}, namespace_collection)

    add_entity(datagraph, scalar)
    return scalar


def _create_bounded_time_instant(scope: str, namespace_collection: dict, datagraph: dict, todo_list: list, lower, upper, entity_id: str):
    """Like create_time_instant (creation/media_object_functions.py), but with hlo:hasLowerBound/hasUpperBound instead of rdf:value."""
    time_type = check_type("time:Instant", namespace_collection)
    entity_id = claim_id(entity_id, datagraph, todo_list)
    # Without hlo:Actual: the point in time is the value of an evidence/reference (see there).
    instant = {"@id": entity_id, "@type": [time_type, scope]}
    if lower is not None:
        set_literal_property(instant, "hlo:hasLowerBound", lower, "xsd:dateTime", namespace_collection)
    if upper is not None:
        set_literal_property(instant, "hlo:hasUpperBound", upper, "xsd:dateTime", namespace_collection)
    add_entity(datagraph, instant)
    return instant


def _parse_bound_value(raw):
    """Try to parse raw (a string or a JSON-LD literal dict) as a number or an ISO
    timestamp, for the bounds warning check (see _warn_if_outside_existing_bounds).
    Returns None when both fail."""
    if raw is None:
        return None
    if isinstance(raw, dict):
        raw = raw.get("@value")
    try:
        return float(raw)
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _warn_if_outside_existing_bounds(resolved_entity: dict, type_answer: str, variable: dict, datagraph: dict):
    """Point 9 (bounds instead of exact values): when a new planned, set or controlled
    value falls outside the bounds already known through hlo:hasEvidence of the same Actual
    (variable), only warn - nothing is blocked and no entity is changed.
    """
    if type_answer not in ("hlo:Planned", "hlo:Set", "hlo:Controlled"):
        return

    new_value = _parse_bound_value(resolved_entity.get("qudt:value") or resolved_entity.get("rdf:value"))
    if new_value is None:
        return

    existing_ref = variable.get("hlo:hasEvidence")
    existing_id = existing_ref.get("@id") if isinstance(existing_ref, dict) else existing_ref
    existing = find_entity(datagraph, existing_id) if existing_id else None
    if existing is None:
        return

    lower = _parse_bound_value(existing.get("hlo:hasLowerBound"))
    upper = _parse_bound_value(existing.get("hlo:hasUpperBound"))
    if lower is None and upper is None:
        return

    try:
        outside = (lower is not None and new_value < lower) or (upper is not None and new_value > upper)
    except TypeError:
        return

    if outside:
        bounds_text = f"{lower if lower is not None else '?'}-{upper if upper is not None else '?'}"
        print(f"Warning: the planned value ({new_value}) for {variable['@id']} lies outside the observed limits ({bounds_text}).")


def _ask_value_unit(quantity_kind: str, scope: str, question_id_prefix: str):
    """The unit of this one evidence/reference value.

    It is asked for EVERY value, and the answer is stored only at the value itself -
    not at the actual quantity. That costs one question per value, but it is the
    only way that needs no assumptions: evidence and reference of the same quantity
    can be in different units (measured in degrees Celsius, prescribed
    in kelvin), and evidence/reference entities are - unlike the actuals -
    deliberately NOT linked between the levels via hlo:specializationOf. So there is
    no path at all along which a unit could be inherited without something
    being claimed.

    The choice follows from the quantity kind of the value (see
    SCALAR_UNITS_BY_QUANTITY_KIND in helpers/units.py) - that of the actual if its property allows
    exactly one, otherwise the one chosen for this value (rule 4.4). If the table does not
    know it, the quantity kind is asked (see ask_unit there).

    Exception profile: a cpo:ProfileVariable is itself an evidence/reference entity
    and hands its unit down to its steps. That does not contradict the rule - the
    steps are parts of the same value, not values of their own.
    """
    return units_for_quantity_kind(quantity_kind)


def _create_resolved_value_entity(evidence_type_answer: str, variable: dict, entity: dict, scope: str, nr: int, namespace_collection: dict, datagraph: dict, global_todo_list: list, local_todo_list: list, role: str, quantity_kind: str = None):
    """Try to resolve the "no, does not exist yet" answer completely, instead of only
    writing an empty placeholder onto the todo list as used to happen every time:

    - cpo:ProcessVariable, scalar: a plain value (see create_scalar_variable).
    - cpo:ProcessVariable, series: a link to a column already recorded (see
      creation/media_object_functions.py) - only meaningful at experiment level, since
      measurement data is experiment-specific.
    - cpo:ProcessVariable, profile: any number of transition and hold steps (see
      helpers/profile_variables.py).
    - time:Instant: a timestamp with rdf:value (or bounds) - the value of the evidence or
      reference itself, not an hlo:Actual (the file dates are Actuals, see create_time_instant).
    - time:Duration: a value plus a unit (qudt:hasUnit) - for add_time_entities (see
      helpers/time_occurrence.py).
    - cpo:Occurrence: occurred or did not occur - for add_occurrence (see
      helpers/time_occurrence.py).

    All other types (cpo:ReactionMechanism, for instance) still fall back to the old
    placeholder mechanism (see the callers).

    Returns the finished entity, already written into the datagraph, or None when this case
    cannot (yet) be resolved directly - because the user gave no value, for example.

    quantity_kind: the kind of THIS value where the property allows several (a flow rate
    given as a mass flow rate); None takes the kind of the variable.
    """
    label = f"{variable['@id']} (belonging to {entity['@id']})"
    # "evidence" or "reference" - makes clear in the questions below that we are
    # describing the evidence/reference VALUE of `label`, not `label` itself.
    # Serves at the same time as the question_id prefix (see the module docstring above).
    role_word = "evidence" if role == "hlo:Evidence" else "reference"
    # The content-based ID of the value: n-th value of this role at this variable.
    value_id = _value_id(variable, role, scope, nr)

    if evidence_type_answer == "cpo:ProcessVariable":
        variable_kind = ask_user(
            f"[{scope}] Is the {role_word} value for {label} a single value (Scalar), a recorded time series "
            f"(Series), or a profile (Profile, e.g. a set temperature ramp)?",
            ["Scalar", "Series", "Profile"],
            question_id=f"{role_word}_variable_kind"
        )
        # For fractions the unit is settled (unit:UNITLESS) and not asked;
        # None means "does not follow from the quantity kind", not "unitless" (see
        # DIMENSIONLESS_QUANTITY_KINDS in helpers/units.py).
        quantity_kind = quantity_kind or ref_id(variable.get("qudt:hasQuantityKind"))
        fixed_unit = fixed_unit_for_quantity_kind(quantity_kind)

        if variable_kind == "Scalar":
            is_exact, lower, upper = _ask_bounds(scope, role_word, label, quantity_kind=quantity_kind)
            if is_exact:
                return create_scalar_variable(label, scope, nr, namespace_collection, datagraph, global_todo_list, local_todo_list, unit=fixed_unit, unit_options=_ask_value_unit(quantity_kind, scope, role_word), quantity_kind=quantity_kind, question_id_prefix=f"{role_word}_scalar", entity_id=value_id)
            if lower is None and upper is None:
                return None
            return _create_bounded_scalar_variable(scope, nr, namespace_collection, datagraph, global_todo_list, local_todo_list, lower, upper, label, unit=fixed_unit, unit_options=_ask_value_unit(quantity_kind, scope, role_word), question_id_prefix=f"{role_word}_bounds", entity_id=value_id)

        if variable_kind == "Series":
            if scope != "hlo:ExperimentSpecific":
                return None
            series_type = check_type("cpo:SeriesVariable", namespace_collection)
            series_id = claim_id(value_id,
                                     datagraph, global_todo_list, local_todo_list)
            series = {"@id": series_id, "@type": [series_type, scope]}
            if not pick_column_for_series_variable(series, label, scope, nr, namespace_collection, datagraph, question_id_prefix=f"{role_word}_series"):
                return None
            add_entity(datagraph, series)
            return series

        if variable_kind == "Profile":
            # The profile gets the unit once and hands it down to its steps
            # (see _ask_value_unit, paragraph "Exception profile").
            return create_profile_variable(label, scope, nr, namespace_collection, datagraph, global_todo_list, local_todo_list, unit=fixed_unit, unit_options=_ask_value_unit(quantity_kind, scope, role_word), variable_quantity_kind=quantity_kind, question_id_prefix=f"{role_word}_profile", entity_id=value_id)

        return None

    if evidence_type_answer == "time:Instant":
        is_exact, lower, upper = _ask_bounds(scope, role_word, label, value_hint=" (ISO date/time, e.g. 2026-09-28T10:00:00Z)")
        if is_exact:
            value_answer = ask_user(f"[{scope}] Timestamp for the {role_word} of {label} (ISO date/time, e.g. 2026-09-28T10:00:00Z)?", question_id=f"{role_word}_timestamp")
            if not value_answer.strip():
                return None
            instant = create_time_instant(value_answer.strip(), scope, namespace_collection, datagraph, global_todo_list + local_todo_list, entity_id=value_id)
            # The point in time here is the value of an evidence/reference, not an actual - only the
            # date of a file stands as an actual with a value of its own (rule 4.1, Actual_NoValue_Shape).
            instant["@type"] = [t for t in instant["@type"] if t != "hlo:Actual"]
            return instant
        if lower is None and upper is None:
            return None
        return _create_bounded_time_instant(scope, namespace_collection, datagraph, global_todo_list + local_todo_list, lower, upper, entity_id=value_id)

    if evidence_type_answer == "time:Duration":
        value_answer = ask_user(f"[{scope}] Duration value for the {role_word} of {label} (number, leave empty if unknown)?", question_id=f"{role_word}_duration_value")
        if not value_answer.strip():
            return None
        unit_answer = ask_user(f"[{scope}] Unit of that duration?", DURATION_UNITS, question_id=f"{role_word}_duration_unit")
        duration_type = check_type("time:Duration", namespace_collection)
        duration_id = claim_id(value_id,
                                   datagraph, global_todo_list, local_todo_list)
        duration = {"@id": duration_id, "@type": [duration_type, scope]}
        set_literal_property(duration, "rdf:value", value_answer.strip(), "xsd:decimal", namespace_collection)
        set_property(duration, "qudt:hasUnit", {"@id": unit_answer}, namespace_collection)
        add_entity(datagraph, duration)
        return duration

    if evidence_type_answer == "cpo:OccurrenceStatus":
        if _occurrence_value_preset:
            value_answer = _occurrence_value_preset[-1]
        else:
            value_answer = ask_user(f"[{scope}] Did the {role_word} for {label} occur?", occurrence_values(namespace_collection), question_id=f"{role_word}_occurred")
        occurrence_type = check_type("cpo:OccurrenceStatus", namespace_collection)
        occurrence_id = claim_id(value_id,
                                     datagraph, global_todo_list, local_todo_list)
        occurrence = {"@id": occurrence_id, "@type": [occurrence_type, scope]}
        set_property(occurrence, "cpo:hasOccurrenceValue", {"@id": value_answer}, namespace_collection)
        add_entity(datagraph, occurrence)
        return occurrence

    return None



def _mark_value_quantity_kind(value_entity: dict, quantity_kind: str, namespace_collection: dict):
    """Write the chosen quantity kind onto a value (rule 4.4): where the property allows
    several kinds, the Actual carries none and each value says in which kind it is given.
    A value that already states a kind keeps it."""
    if quantity_kind and value_entity is not None and not value_entity.get("qudt:hasQuantityKind"):
        set_property(value_entity, "qudt:hasQuantityKind", quantity_kind, namespace_collection)


def _resolve_quantity_kind(entity: dict, datagraph: dict):
    """The quantity kind of a process-variable-like entity - directly when present,
    otherwise through the linked Actual entity.

    The second path is for a pure reference or evidence entity without a quantity kind of
    its own; see the parameter pattern in device_library.jsonld, where only the Actual
    carries qudt:hasQuantityKind and its _Reference_1 does not.
    """
    if entity.get("qudt:hasQuantityKind"):
        return entity["qudt:hasQuantityKind"]
    for candidate in datagraph.get("@graph", []):
        for prop in ("hlo:hasEvidence", "hlo:hasReference"):
            ref = candidate.get(prop)
            ref_id = ref.get("@id") if isinstance(ref, dict) else ref
            if ref_id == entity["@id"]:
                return candidate.get("qudt:hasQuantityKind")
    return None


def _filter_existing_candidates(candidates: list, variable: dict, scope: str, nr: int, found_type: str, datagraph: dict, exclude_actual: bool = False, quantity_kind: str = None) -> list:
    """Narrow the list of candidates for an already existing evidence or reference entity,
    instead of offering the user every entity of that type in the whole datagraph:

    - never the variable itself.
    - only entities from the same scope (series stays among series, experiment among
      experiment) and, at experiment level, from the same experiment (recognisable by the
      "_{nr}" ending of the ID, see generate_id).
    - for process-variable candidates, automatically only those with the same quantity kind
      as the variable (only other temperatures as evidence for a temperature, say), so a
      wrong pick does not have to be spotted by hand.
    - exclude_actual (only add_reference, see there): by the ontology, hasReference must
      never point at another hlo:Actual entity, only at a pure reference such as a profile
      or an estimate. Two Actuals that physically influence each other are connected
      through hlo:isCoupledWith instead (see link_phase_couplings).
    - at series level, fixed-level candidates count as well (no
      hlo:SeriesSpecific/hlo:ExperimentSpecific in the @type - an assumption entered by hand
      in a library, such as lab:L109_Width_Reference_1). That way a series variable
      can reuse a value already described in the library as its reference instead of
      duplicating it. At experiment level this does NOT apply: there the value is inherited
      structurally from the series counterpart (see add_phase_process_variable).
    """
    def _matches_scope(c):
        if scope in c.get("@type", []):
            return True
        if scope == "hlo:SeriesSpecific":
            return not ({"hlo:SeriesSpecific", "hlo:ExperimentSpecific"} & set(c.get("@type", [])))
        return False

    candidates = [c for c in candidates if c["@id"] != variable["@id"] and _matches_scope(c)]

    if scope == "hlo:ExperimentSpecific" and nr is not None:
        suffix = f"_{nr}"
        candidates = [c for c in candidates if c.get("@id", "").endswith(suffix)]

    # The quantity kind of the value: the chosen one, otherwise that of the actual (rule 4.4).
    wanted_kind = quantity_kind or ref_id(variable.get("qudt:hasQuantityKind"))
    if found_type == "cpo:ProcessVariable" and wanted_kind:
        candidates = [c for c in candidates if ref_id(_resolve_quantity_kind(c, datagraph)) == wanted_kind]

    if exclude_actual:
        candidates = [c for c in candidates if "hlo:Actual" not in c.get("@type", [])]

    return candidates


# ---------------------------------------------------------------------------
# Determination task stubs: EVERY evidence/reference gets a task
# ---------------------------------------------------------------------------
#
# Here used to stand _ask_and_link_determination_task: an optional question
# ("Do you want to describe how ... was obtained?") that on "Yes" wrote a finished
# task into the datagraph at once. That had two problems. First, "No" was possible -
# a value without a task was thus a legal final state, although EACH of the eight
# evidence/reference types has a task class via hlo:determinedByTaskClass
# (3 EvidenceType + 5 ReferenceType individuals, all with a task class). Second,
# it produced a torso: at the time of the question neither transfers nor
# reactions exist (cpo:aimsAt), and the user is thinking about a measured value,
# not about a procedure - the task stayed nameless, without equipment, without
# times and without a connection to the series.
#
# Instead a placeholder is put on the to-do list here without any question, just
# as for the phases (see creation/material_functions.py: create_phase_placeholder /
# add_experiment_phases_from_series). Everything settled at this point is in it:
# the task class (from the evidence/reference type) and the link to the value in
# both directions (cpo:determines / cpo:hasDeterminationTask). The rest is asked
# later in creation/task_functions.py, where transfers, reactions and everything
# else exist.
#
# Levels as for the phases: the placeholder of the SERIES is the core (the procedure
# is the same across the series), an experiment value hangs at a specialization of it.
# A value on the series level hangs directly at the series task.


def _find_in_graph_or_todo(entity_id: str, datagraph: dict, *item_lists):
    """Like find_entity, but also searches the todo lists: both the values (the
    placeholder branch below) and the task stubs themselves live only there until they are
    completed, and not yet in the datagraph.
    """
    entity = find_entity(datagraph, entity_id)
    if entity is not None:
        return entity
    for items in item_lists:
        if not items:
            continue
        entity = find_entity(items, entity_id)
        if entity is not None:
            return entity
    return None


def task_class_for_value_type(type_answer: str, namespace_collection: dict):
    """hlo:Measured -> cpo:MeasurementTask, through hlo:determinedByTaskClass in the
    ontology.

    Not maintained in code: a new task class takes effect immediately (see
    creation/task_functions.py: task_type_to_value_type, the inverse of this).
    """
    type_info = find_entity_in_ontology(type_answer, namespace_collection)
    task_class_ref = type_info.get("determinedByTaskClass") if type_info else None
    if isinstance(task_class_ref, list):
        task_class_ref = task_class_ref[0]
    if not task_class_ref:
        return None
    return shorten_id(ref_id(task_class_ref), namespace_collection)


def _series_anchor(value_entity: dict, scope: str, datagraph: dict, *item_lists):
    """The series-level Actual that this value's family of tasks hangs off: for a series
    value the Actual itself, for an experiment value its series counterpart through
    hlo:specializationOf.

    Returns None when there is no series counterpart, in which case the task stays purely
    experiment-specific. That does not occur in the current crate - every experiment value
    hangs off an Actual that has a series counterpart.
    """
    owner_id = ref_id(value_entity.get("hlo:isEvidenceOf") or value_entity.get("hlo:isReferenceOf"))
    owner = _find_in_graph_or_todo(owner_id, datagraph, *item_lists) if owner_id else None
    if owner is None:
        return None
    if scope != "hlo:ExperimentSpecific":
        return owner
    series_id = ref_id(owner.get("hlo:specializationOf"))
    return _find_in_graph_or_todo(series_id, datagraph, *item_lists) if series_id else None


def _find_series_stubs(anchor: dict, task_class: str, datagraph: dict, *item_lists):
    """Find the series task that already exists for (anchor, task_class) - purely
    structurally, through the links, without any cache in the module.

    That keeps working when an existing crate is picked up again in a later run: a cache
    would be empty after the restart and would create a second task for the same value.

    Only templates of experiment values count: an experiment specialization of the anchor
    carries a value whose task knows its series template through hlo:specializationOf. The
    task of a value of the series itself is never a template - it determined that value, not
    the experiments' ones.
    """
    def task_of_value(value_ref):
        value = _find_in_graph_or_todo(ref_id(value_ref), datagraph, *item_lists)
        if value is None:
            return None
        task_id = ref_id(value.get("cpo:hasDeterminationTask"))
        task = _find_in_graph_or_todo(task_id, datagraph, *item_lists) if task_id else None
        if task is None or task_class not in as_list(task.get("@type")):
            return None
        return task

    # The task of a series value of its own does not count as a template here (rule 4.1). If
    # series and experiment each had an assumption for the same quantity (series: 1.5 mL according
    # to the plan, experiment: 1 mL, that is how the vial is usually filled), the experiment value
    # hung at the specialization of the series assumption and inherited its name and reason. In
    # the hydrogenation crate that never happened (no series values of its own with a placeholder task).
    found = {}

    for spec_ref in as_list(anchor.get("hlo:hasSpecialization")):
        specialization = _find_in_graph_or_todo(ref_id(spec_ref), datagraph, *item_lists)
        if specialization is None:
            continue
        for prop in ("hlo:hasEvidence", "hlo:hasReference"):
            for value_ref in as_list(specialization.get(prop)):
                task = task_of_value(value_ref)
                if task is None:
                    continue
                series_id = ref_id(task.get("hlo:specializationOf"))
                series_stub = _find_in_graph_or_todo(series_id, datagraph, *item_lists) if series_id else None
                if series_stub is not None:
                    found[series_stub["@id"]] = series_stub

    # Sorted by ID: the counters in the IDs are padded to four digits, so the order is stable
    # and matches the order of creation.
    return [found[key] for key in sorted(found)]


def _determination_index(value_entity: dict, task_class: str, datagraph: dict, *item_lists) -> int:
    """The how-manyth value of this quantity (1-based) that is determined by a task of this
    class.

    Purpose: ONE value per quantity and task class is the normal case - a temperature, measured
    once. If a SECOND one comes along, that was a second determination: the sample at the start
    and the sample at the end of the experiment are two operations with two points in time, even if
    both concern the same mass of the same phase. Through this index each of the
    two gets its own task family, without anybody having to be asked.

    Counted at the actual of the value, not at the series anchor: the first value in
    experiment 2 is again the first of its quantity and therefore belongs to the same
    series template as the first one from experiment 1.

    If two values do belong to the same activity, the task stage merges them again
    (_absorb_stub) - starting separately and being able to merge is the
    safe way round; the other way round the separation could not be made up for.
    """
    owner_id = ref_id(value_entity.get("hlo:isEvidenceOf") or value_entity.get("hlo:isReferenceOf"))
    owner = _find_in_graph_or_todo(owner_id, datagraph, *item_lists) if owner_id else None
    if owner is None:
        return 1

    # Only the values BEFORE this one in the list of the quantity are counted. The order in
    # hasEvidence/hasReference is the order of creation, so the index is stable - also when
    # work is done later: reattach_orphan_task_stubs runs when ALL values have long had an
    # (orphaned) task, and "how many have one already" would have been the same number for
    # every value there. Both values would then have got the same template - exactly the error
    # that threw the sample at the start and the one at the end together again.
    count = 0
    for prop in ("hlo:hasEvidence", "hlo:hasReference"):
        for value_ref in as_list(owner.get(prop)):
            if ref_id(value_ref) == value_entity["@id"]:
                return count + 1
            other = _find_in_graph_or_todo(ref_id(value_ref), datagraph, *item_lists)
            if other is None:
                continue
            task_id = ref_id(other.get("cpo:hasDeterminationTask"))
            task = _find_in_graph_or_todo(task_id, datagraph, *item_lists) if task_id else None
            if task is not None and task_class in as_list(task.get("@type")):
                count += 1
    return count + 1


def _new_task_stub(task_class: str, scope: str, nr, namespace_collection: dict, datagraph: dict, global_todo_list: list, local_todo_list: list,
                   *, cause_id: str = None, name: str = None, series_stub: dict = None) -> dict:
    """A task placeholder with a content-based ID (helpers/identifiers.py) - exactly one of:

    - cause_id: the value (or file) it exists for -> "#Task_for_<cause>_<cause level>_<level>".
      The level of the cause stays in, always: a series value and an experiment value of the
      same variable share their local name, and their tasks must not (5.1).
    - name: a fixed name (the automatic assumption) -> "#Task_<name>_<level>".
    - series_stub: the experiment counterpart of a series placeholder -> its local name.
    """
    experiment_number = nr if scope == "hlo:ExperimentSpecific" else None
    if series_stub is not None:
        new_id = make_specialization_id(series_stub["@id"], nr)
    elif cause_id is not None:
        new_id = make_root_id("Task", f"for_{level_key(cause_id)}", scope, experiment_number)
    else:
        new_id = make_root_id("Task", name, scope, experiment_number)
    task_id = claim_id(new_id, datagraph, global_todo_list, local_todo_list)
    return {"@id": task_id, "@type": [task_class, scope]}


def reattach_orphan_task_stubs(todo_list: list, datagraph: dict, namespace_collection: dict) -> int:
    """Pull experiment placeholders that have no series template under one after the
    fact - creating the template when there is none yet.

    Needed because not every module has set hlo:specializationOf on the Actual by the time
    the evidence/reference questions run: helpers/process_variables.py
    (add_phase_process_variable) links beforehand, creation/device_functions.py (power
    input) only afterwards. In the second case ensure_determination_task_stub finds no
    series counterpart and creates a free-standing experiment placeholder.

    Rather than rebuilding every call site to use the same order - and hoping it stays that
    way - this is collected here at the start of the tasks stage, where all links are
    complete.

    Returns the number of placeholders that were attached.
    """
    reattached = 0
    for stub in list(todo_list):
        types = as_list(stub.get("@type"))
        if "hlo:ExperimentSpecific" not in types or "hlo:specializationOf" in stub:
            continue
        task_class = next((t for t in types if t not in ("hlo:ExperimentSpecific",)), None)
        if task_class is None or not stub.get("cpo:determines"):
            continue

        for value_ref in as_list(stub.get("cpo:determines")):
            value = _find_in_graph_or_todo(ref_id(value_ref), datagraph, todo_list)
            if value is None:
                continue
            anchor = _series_anchor(value, "hlo:ExperimentSpecific", datagraph, todo_list)
            if anchor is None:
                continue
            index = _determination_index(value, task_class, datagraph, todo_list)
            series_stubs = _find_series_stubs(anchor, task_class, datagraph, todo_list)
            series_stub = series_stubs[index - 1] if index <= len(series_stubs) else None
            if series_stub is None:
                series_stub = _new_task_stub(task_class, "hlo:SeriesSpecific", None, namespace_collection, datagraph, todo_list, None,
                                             cause_id=value["@id"])
                add_todo_item(todo_list, series_stub)
            set_property(stub, "hlo:specializationOf", series_stub, namespace_collection)
            set_property(series_stub, "hlo:hasSpecialization", stub, namespace_collection, True)
            reattached += 1
            break
    return reattached


# The assumptions the generator makes itself instead of asking stand as fixed cpo:AssumptionTask
# entries in libraries/assumption_library.jsonld (name, reason, who settled it). A value in the
# crate names the entry directly in cpo:hasDeterminationTask, the library does not name it back
# (rule 4.1, exception for library tasks; rule 2.2). The assumptions that determine no value
# (inert phases: no potential transfers) stand there as well, without a reference at the
# interface: they set the scope of the model, not a value; the crate names the library in the
# library snapshot (rule 2.3).
LIBRARY_ASSUMPTIONS = {
    "pure_phase": "task:assuming_single_species_phase_is_pure",
}


def link_automatic_assumption(value_entity: dict, namespace_collection: dict, kind: str = "pure_phase") -> str:
    """Name the library entry of an assumption the generator makes itself as the determination
    task of value_entity - one way only, the library is not changed (rule 4.1, exception)."""
    task_id = LIBRARY_ASSUMPTIONS[kind]
    if find_entity(registered_library("assumption_library"), task_id) is None:
        raise RuntimeError(f"{task_id} is not in the assumption library (libraries/assumption_library.jsonld).")
    set_property(value_entity, "cpo:hasDeterminationTask", {"@id": task_id}, namespace_collection)
    return task_id


def _experiment_stub_of(series_stub: dict, task_class: str, nr, namespace_collection: dict, datagraph: dict, global_todo_list: list, local_todo_list: list) -> dict:
    """The experiment specialization of a series placeholder for experiment nr - reuse an existing one, otherwise create it."""
    for spec_ref in as_list(series_stub.get("hlo:hasSpecialization")):
        candidate = _find_in_graph_or_todo(ref_id(spec_ref), datagraph, global_todo_list, local_todo_list)
        if candidate is not None and candidate["@id"].endswith(f"_ExperimentSpecific_{nr}"):
            return candidate

    task = _new_task_stub(task_class, "hlo:ExperimentSpecific", nr, namespace_collection, datagraph, global_todo_list, local_todo_list,
                          series_stub=series_stub)
    set_property(task, "hlo:specializationOf", series_stub, namespace_collection)
    set_property(series_stub, "hlo:hasSpecialization", task, namespace_collection, True)
    add_todo_item(local_todo_list if local_todo_list is not None else global_todo_list, task)
    return task


def _existing_series_tasks(datagraph: dict, *item_lists) -> list:
    """Every series task and placeholder that exists so far - the choices for "which task was that?"."""
    result = []
    seen = set()
    for source in (list(datagraph.get("@graph", [])),) + item_lists:
        for entity in (source or []):
            types = as_list(entity.get("@type"))
            if "hlo:SeriesSpecific" not in types or entity["@id"] in seen:
                continue
            if not any(t.endswith("Task") for t in types):
                continue
            seen.add(entity["@id"])
            result.append(entity)
    return result


def _task_choice_label(task: dict, *sources) -> str:
    """A placeholder has no name yet, so it is described by what it already carries.

    Same rule as creation/task_functions.py: _stub_label, and through the same helper: what
    a placeholder covers is named by the VALUE, not by the placeholder's @id, because that
    ID is reused within a run (see helpers/entities.py: value_label).

    A task that already HAS a name keeps its @id in brackets - two tasks may well be called
    the same, and by then the ID is the ID of a described task rather than of a placeholder.
    """
    shown_id = task["@id"]
    name = task.get("schema:name")
    if name:
        return f"{name} ({shown_id})"
    covered = [value_label(ref_id(v), *sources)
               for v in as_list(task.get("cpo:determines")) + as_list(task.get("cpo:generatedMediaObject"))]
    return f"{shown_id} (for {', '.join(covered)})" if covered else shown_id


def ask_task_for_media_object(media_object: dict, scope: str, nr, namespace_collection: dict, datagraph: dict, todo_list: list, local_todo_list: list = None):
    """Ask, for a file, image or video, which task produced it, and create a task
    placeholder for it as is done for values (cpo:generatedMediaObject and the reverse
    direction cpo:generatedBy).

    This lets the overall procedure grow out of the files uploaded at the start, instead of
    being invented in the tasks stage: the raw data file of a measurement brings its
    MeasurementTask with it, the lab journal its ExperimentalProcedure.

    Unlike with values there is no Actual here through which the series template could be
    found structurally - files differ per experiment and do not specialize one another. So
    the question is asked: one of the existing series tasks, or a new one? The template
    always sits at series level and the file hangs off its experiment specialization - the
    same split across levels as for values.
    """
    # Local import: creation/task_functions.py imports this module, an import at
    # module level would be circular.
    from creation.task_functions import task_types

    label = media_object.get("schema:name") or media_object["@id"]
    if ask_user(f"[{scope}] Was {label} generated by a task (e.g. the measurement that recorded it, or the procedure it documents)?", ["Yes", "No"], question_id="generated_by_task") != "Yes":
        return None

    target_list = local_todo_list if local_todo_list is not None else todo_list

    series_task = None
    candidates = _existing_series_tasks(datagraph, todo_list, local_todo_list)
    if candidates:
        labels = [_task_choice_label(t, datagraph, todo_list, local_todo_list) for t in candidates]
        choice = ask_user(f"[{scope}] Which task generated {label}?", labels + ["Describe a new task"], question_id="which_task")
        for candidate, candidate_label in zip(candidates, labels):
            if candidate_label == choice:
                series_task = candidate
                break

    if series_task is None:
        # The series template is named after THIS file (cause_id) - even if later experiments
        # use it too. Hence Task_for_File_exp1_..._ExperimentSpecific_2: intended, see rule 7b.
        task_class = check_type(ask_user(f"[{scope}] What type of task generated {label}?", task_types(namespace_collection), question_id="task_type"), namespace_collection)
        series_task = _new_task_stub(task_class, "hlo:SeriesSpecific", None, namespace_collection, datagraph, todo_list, local_todo_list,
                                     cause_id=media_object["@id"])
        add_todo_item(target_list, series_task)

    task = series_task
    if scope == "hlo:ExperimentSpecific":
        task_class = next((t for t in as_list(series_task.get("@type")) if t != "hlo:SeriesSpecific"), None)
        task = _experiment_stub_of(series_task, task_class, nr, namespace_collection, datagraph, todo_list, local_todo_list)

    set_property(task, "cpo:generatedMediaObject", media_object, namespace_collection, True)
    set_property(media_object, "cpo:generatedBy", task, namespace_collection)
    return task


def ensure_determination_task_stub(value_entity: dict, type_answer: str, scope: str, nr, namespace_collection: dict, datagraph: dict, global_todo_list: list, local_todo_list: list):
    """Create the task placeholder (or placeholders) for a fully typed evidence or
    reference entity and link them in both directions. Asks NO question.

    Called wherever a value receives its evidence or reference type (a reused entity, a
    freshly resolved one, a placeholder on the todo list), so that there is no path on which
    a value comes into being without a task.

    Returns the task the value hangs off (experiment or series level).
    """
    task_class = task_class_for_value_type(type_answer, namespace_collection)
    if task_class is None:
        # Cannot occur with the current ontology (all eight types have a task class) -
        # stays as a hint, in case somebody adds a type without
        # hlo:determinedByTaskClass.
        print(f"[{scope}] No task class configured for {type_answer} (hlo:determinedByTaskClass) - no determination task created.")
        return None
    check_type(task_class, namespace_collection)

    anchor = _series_anchor(value_entity, scope, datagraph, global_todo_list, local_todo_list)

    if anchor is None or scope != "hlo:ExperimentSpecific":
        # No series counterpart, or a value of the series itself: the task stays alone on the
        # level of the value. A series value is never a template for the experiments (see
        # _find_series_stubs) and takes over none of their templates either.
        task = _new_task_stub(task_class, scope, nr, namespace_collection, datagraph, global_todo_list, local_todo_list,
                              cause_id=value_entity["@id"])
        add_todo_item(local_todo_list, task)
    else:
        index = _determination_index(value_entity, task_class, datagraph, global_todo_list, local_todo_list)
        series_stubs = _find_series_stubs(anchor, task_class, datagraph, global_todo_list, local_todo_list)

        if index <= len(series_stubs):
            series_stub = series_stubs[index - 1]
        else:
            series_stub = _new_task_stub(task_class, "hlo:SeriesSpecific", None, namespace_collection, datagraph, global_todo_list, local_todo_list,
                                         cause_id=value_entity["@id"])
            add_todo_item(local_todo_list, series_stub)

        task = series_stub
        if scope == "hlo:ExperimentSpecific":
            task = _experiment_stub_of(series_stub, task_class, nr, namespace_collection, datagraph, global_todo_list, local_todo_list)

    set_property(task, "cpo:determines", value_entity, namespace_collection, True)
    set_property(value_entity, "cpo:hasDeterminationTask", task, namespace_collection)
    return task


def _ask_value_quantity_kind(quantity_kind: str, quantity_kind_options: list, value_type: str, role_word: str,
                             variable: dict, scope: str):
    """The quantity kind of ONE value (rule 4.4, asked at the value): given by the
    caller, the only option, or asked from the options the variable's property allows - a flow
    rate given as a mass flow rate, a concentration as a mole fraction. Asked only for a process
    variable; None when there is nothing to choose."""
    if quantity_kind or not quantity_kind_options or value_type != "cpo:ProcessVariable":
        return quantity_kind
    if len(quantity_kind_options) == 1:
        return quantity_kind_options[0]
    return ask_user(f"[{scope}] In which quantity kind is this {role_word} value for {variable['@id']} given?",
                    list(quantity_kind_options), question_id=f"{role_word}_quantity_kind")


def add_evidence(variable: dict, entity: dict, scope: str, namespace_collection: dict, datagraph: dict, global_todo_list: list, local_todo_list, possible_evidence_types: list = None, nr: int = None, confirmed: bool = False, quantity_kind: str = None, quantity_kind_options: list = None):
    """Ask for and attach the evidence of a value.

    possible_evidence_types is optional (default: ProcessVariable/Time, as everywhere else
    in the project) and lets callers allow other types as evidence - ReactionMechanism, for
    instance, to record competing mechanisms from different sources as a reference.

    nr is the experiment number (only relevant for scope hlo:ExperimentSpecific). It is
    needed for series process variables, to find the media object columns already recorded
    for this experiment (see creation/media_object_functions.py).

    quantity_kind: the kind this value is given in, where it is fixed by the caller (the
    field strength of a field type). quantity_kind_options: the kinds the variable's property
    allows where there are several (rule 4.4) - then the kind is asked for each value. Either
    way it decides the unit choice and is written onto the value.
    """
    if possible_evidence_types is None:
        possible_evidence_types = ["cpo:ProcessVariable", "cpo:Time"]
    # The kind per value (_ask_value_quantity_kind): every pass determines its own.
    outer_quantity_kind = quantity_kind

    def _one_round():
        """A single value - the former body, unchanged.

        hlo:hasEvidence/hasReference are set MULTI-VALUED here: a quantity can
        carry several values (sample at the start and at the end), and single-valued the
        second would have silently overwritten the first. The inverse direction (isEvidenceOf) stays
        single-valued - a value belongs to exactly one quantity.
        """

        exists = ask_user("Does the entity that is used as the evidence already exist?", ["Yes", "No"], question_id="evidence_exists")
        evidence_type_answer = ask_user("Of what type is the evidence?", possible_evidence_types, question_id="evidence_value_type")
        quantity_kind = _ask_value_quantity_kind(outer_quantity_kind, quantity_kind_options, evidence_type_answer,
                                                 "evidence", variable, scope)

        if exists == "Yes":
            # we only have to make the connection, i.e. find the entity:
            # find all entities of the type evidence_type_answer


            potential_entities, final_evidence_type = find_entities_by_type_interactive(
                datagraph, evidence_type_answer, namespace_collection, possible_evidence_types, True,
                question_id_prefix="evidence_lookup"
            )
            if potential_entities is not None:
                potential_entities = _filter_existing_candidates(potential_entities, variable, scope, nr, final_evidence_type, datagraph,
                                                                 quantity_kind=quantity_kind)
            exists = "Yes" if potential_entities else "No"

            if potential_entities:
                potential_entities_string = [
                    c["@id"]
                    for c in potential_entities
                ]

                evidence_entity_id = ask_user("Which of the following entities is the one that is the evidence in this case?", potential_entities_string, question_id="select_existing_evidence")

                evidence_entity = find_entity(datagraph, evidence_entity_id)
                _mark_value_quantity_kind(evidence_entity, quantity_kind, namespace_collection)

                set_property(evidence_entity, "hlo:isEvidenceOf", variable, namespace_collection)
                set_property(variable, "hlo:hasEvidence", evidence_entity, namespace_collection, True)
                set_property(evidence_entity, "@type", "hlo:Evidence", namespace_collection, True)
                type_answer = _ask_and_set_value_role_type(evidence_entity, "hlo:Evidence", namespace_collection)
                ensure_determination_task_stub(evidence_entity, type_answer, scope, nr, namespace_collection, datagraph, global_todo_list, local_todo_list)



        if exists == "No":

            # First try to resolve the answer completely right away (scalar value,
            # series column link, time stamp) instead of just writing an empty
            # placeholder onto the to-do list - see _create_resolved_value_entity above.
            resolved_entity = _create_resolved_value_entity(
                evidence_type_answer, variable, entity, scope, nr, namespace_collection, datagraph, global_todo_list, local_todo_list, "hlo:Evidence",
                quantity_kind=quantity_kind
            )
            if resolved_entity is not None:
                _mark_value_quantity_kind(resolved_entity, quantity_kind, namespace_collection)
                set_property(resolved_entity, "@type", "hlo:Evidence", namespace_collection, True)
                type_answer = _ask_and_set_value_role_type(resolved_entity, "hlo:Evidence", namespace_collection)
                set_property(resolved_entity, "hlo:isEvidenceOf", variable, namespace_collection)
                set_property(variable, "hlo:hasEvidence", resolved_entity, namespace_collection, True)
                ensure_determination_task_stub(resolved_entity, type_answer, scope, nr, namespace_collection, datagraph, global_todo_list, local_todo_list)
                return

            # Fallback (profiles, and all other possible_evidence_types): as before
            # only an empty placeholder on the to-do list.
            todo_item_type = check_type(evidence_type_answer, namespace_collection)

            # What differs are the kinds, the rest should be the same.
            # NOTE: local_todo_list has to be part of the uniqueness check, otherwise
            # several placeholders of the same run get the same ID (global_todo_list is
            # merged only at the very end of the run, local items stand only here until then).
            todo_item_id = claim_id(_value_id(variable, "hlo:Evidence", scope, nr),
                                        datagraph, global_todo_list, local_todo_list)

            todo_item = {
                "@id": todo_item_id,
                "@type": [todo_item_type, scope]
            }

            _mark_value_quantity_kind(todo_item, quantity_kind, namespace_collection)
            set_property(todo_item, "@type", "hlo:Evidence", namespace_collection, True)
            type_answer = _ask_and_set_value_role_type(todo_item, "hlo:Evidence", namespace_collection)
            set_property(todo_item, "hlo:isEvidenceOf", variable, namespace_collection)
            set_property(variable, "hlo:hasEvidence", todo_item, namespace_collection, True)

            add_todo_item(local_todo_list, todo_item)
            # Only AFTER add_todo_item: ensure_determination_task_stub finds the series task
            # structurally via the links of the value, which must be findable for that (it
            # is not in the datagraph yet).
            ensure_determination_task_stub(todo_item, type_answer, scope, nr, namespace_collection, datagraph, global_todo_list, local_todo_list)

    # Several values per quantity: the sample at the start and the one at the end of an
    # experiment are two measurements of the same quantity, and a repeated determination
    # occurs too. The FIRST value keeps its existing question keys; every further one hangs
    # under a segment of its own ("evidence:2", "evidence:3", ...), so that the existing
    # answers stay valid. Every value gets its own task family via _determination_index.
    round_number = 0
    while True:
        round_number += 1
        if round_number == 1:
            # confirmed: the question is already answered - in the list of an exemplar
            # (helpers/value_sources.py), which only names what there is a value for.
            if not confirmed and ask_user(f"[{scope}] Do you have direct measurement or observation evidence for {variable['@id']} (belonging to {entity['@id']})?", ["Yes", "No"], question_id="have_evidence") != "Yes":
                return
            _one_round()
        else:
            with question_path("evidence", round_number):
                if ask_user(f"[{scope}] Is there ANOTHER measured or observed value for {variable['@id']} (a second determination, e.g. a sample at the start and one at the end)?", ["Yes", "No"], question_id="have_another_evidence") != "Yes":
                    return
                _one_round()
def add_reference(variable: dict, entity: dict, scope: str, namespace_collection: dict, datagraph: dict, global_todo_list: list, local_todo_list, possible_reference_types: list = None, nr: int = None, confirmed: bool = False, quantity_kind: str = None, quantity_kind_options: list = None):
    """possible_reference_types is optional - see add_evidence. nr, quantity_kind and
    quantity_kind_options: see add_evidence."""
    if possible_reference_types is None:
        possible_reference_types = ["cpo:ProcessVariable", "cpo:Time"]
    # The kind per value (_ask_value_quantity_kind): every pass determines its own.
    outer_quantity_kind = quantity_kind

    def _one_round():
        """A single value - the former body, unchanged."""

        exists = ask_user("Does the entity that is used as the reference already exist?", ["Yes", "No"], question_id="reference_exists")
        reference_type_answer = ask_user("Of what type is the reference?", possible_reference_types, question_id="reference_value_type")
        quantity_kind = _ask_value_quantity_kind(outer_quantity_kind, quantity_kind_options, reference_type_answer,
                                                 "reference", variable, scope)

        if exists == "Yes":
            # we only have to make the connection, i.e. find the entity:
            # find all entities of the type reference_type_answer
            potential_entities, final_reference_type = find_entities_by_type_interactive(
                datagraph, reference_type_answer, namespace_collection, possible_reference_types, True,
                question_id_prefix="reference_lookup"
            )
            if potential_entities is not None:
                # exclude_actual=True: hasReference must never point at another actual entity
                # (see _filter_existing_candidates) - an actual that exists already and is
                # physically coupled belongs to isCoupledWith, not here.
                potential_entities = _filter_existing_candidates(potential_entities, variable, scope, nr, final_reference_type, datagraph, exclude_actual=True,
                                                                 quantity_kind=quantity_kind)
            exists = "Yes" if potential_entities else "No"

            if potential_entities:
                potential_entities_string = [
                    c["@id"]
                    for c in potential_entities
                ]

                reference_entity_id = ask_user("Which of the following entities is the one that is the reference in this case?", potential_entities_string, question_id="select_existing_reference")

                reference_entity = find_entity(datagraph, reference_entity_id)
                _mark_value_quantity_kind(reference_entity, quantity_kind, namespace_collection)

                set_property(reference_entity, "hlo:isReferenceOf", variable, namespace_collection)
                set_property(variable, "hlo:hasReference", reference_entity, namespace_collection, True)
                set_property(reference_entity, "@type", "hlo:Reference", namespace_collection, True)
                type_answer = _ask_and_set_value_role_type(reference_entity, "hlo:Reference", namespace_collection)
                _warn_if_outside_existing_bounds(reference_entity, type_answer, variable, datagraph)
                ensure_determination_task_stub(reference_entity, type_answer, scope, nr, namespace_collection, datagraph, global_todo_list, local_todo_list)




        if exists == "No":

            # First try to resolve the answer completely right away (scalar value,
            # series column link, time stamp) - see add_evidence/
            # _create_resolved_value_entity above.
            resolved_entity = _create_resolved_value_entity(
                reference_type_answer, variable, entity, scope, nr, namespace_collection, datagraph, global_todo_list, local_todo_list, "hlo:Reference",
                quantity_kind=quantity_kind
            )
            if resolved_entity is not None:
                _mark_value_quantity_kind(resolved_entity, quantity_kind, namespace_collection)
                set_property(resolved_entity, "@type", "hlo:Reference", namespace_collection, True)
                type_answer = _ask_and_set_value_role_type(resolved_entity, "hlo:Reference", namespace_collection)
                _warn_if_outside_existing_bounds(resolved_entity, type_answer, variable, datagraph)
                set_property(resolved_entity, "hlo:isReferenceOf", variable, namespace_collection)
                set_property(variable, "hlo:hasReference", resolved_entity, namespace_collection, True)
                ensure_determination_task_stub(resolved_entity, type_answer, scope, nr, namespace_collection, datagraph, global_todo_list, local_todo_list)
                return

            # Fallback (profiles, and all other possible_reference_types): as before
            # only an empty placeholder on the to-do list.
            # we add the variable as a reference, but it is defined elsewhere; first it goes onto the to-do list
            todo_item_type = check_type(reference_type_answer, namespace_collection)

            # What differs are the kinds, the rest should be the same.
            # NOTE: local_todo_list has to be part of the uniqueness check, otherwise
            # several placeholders of the same run get the same ID (global_todo_list is
            # merged only at the very end of the run, local items stand only here until then).
            todo_item_id = claim_id(_value_id(variable, "hlo:Reference", scope, nr),
                                        datagraph, global_todo_list, local_todo_list)

            todo_item = {
                "@id": todo_item_id,
                "@type": [todo_item_type, scope]
            }

            _mark_value_quantity_kind(todo_item, quantity_kind, namespace_collection)
            set_property(todo_item, "@type", "hlo:Reference", namespace_collection, True)
            type_answer = _ask_and_set_value_role_type(todo_item, "hlo:Reference", namespace_collection)
            set_property(todo_item, "hlo:isReferenceOf", variable, namespace_collection)
            set_property(variable, "hlo:hasReference", todo_item, namespace_collection, True)

            add_todo_item(local_todo_list, todo_item)
            # see the comment in the evidence branch: only after add_todo_item.
            ensure_determination_task_stub(todo_item, type_answer, scope, nr, namespace_collection, datagraph, global_todo_list, local_todo_list)

    # Several values per quantity: the sample at the start and the one at the end of an
    # experiment are two measurements of the same quantity, and a repeated determination
    # occurs too. The FIRST value keeps its existing question keys; every further one hangs
    # under a segment of its own ("reference:2", "reference:3", ...), so that the existing
    # answers stay valid. Every value gets its own task family via _determination_index.
    round_number = 0
    while True:
        round_number += 1
        if round_number == 1:
            if not confirmed and ask_user(f"[{scope}] Do you have a reference or external value for {variable['@id']} (belonging to {entity['@id']})?", ["Yes", "No"], question_id="have_reference") != "Yes":
                return
            _one_round()
        else:
            with question_path("reference", round_number):
                if ask_user(f"[{scope}] Is there ANOTHER reference or external value for {variable['@id']} (a second specification, e.g. a setpoint that was changed during the run)?", ["Yes", "No"], question_id="have_another_reference") != "Yes":
                    return
                _one_round()
