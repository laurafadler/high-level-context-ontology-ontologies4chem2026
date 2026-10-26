"""
Scalar and profile process variables - the two remaining subclasses of
cpo:ProcessVariable next to SeriesVariable (see creation/media_object_functions.py for
series). Called from helpers/evidence_reference.py to resolve a "no, does not exist yet"
answer in add_evidence/add_reference right away, instead of only writing an empty
placeholder onto the todo list.

cpo:ProfileVariable -> dcterms:hasPart -> cpo:ProfileStep (a TransitionStep or a
HoldStep), each with hasSequenceNumber (xsd:integer, the order) and optionally
cpo:hasDuration. A HoldStep points through holdValue at one ScalarVariable; a
TransitionStep points through startValue/endValue/changeRate at one each.

question_id_prefix is MANDATORY on every public function here (see helpers/user_io.py):
create_scalar_variable is called up to three times in a row within a SINGLE profile step
(start/end/change_rate), and create_profile_variable/create_scalar_variable are used both
directly (see creation/task_functions.py) and through evidence_reference.py (with an
"evidence_"/"reference_" prefix) - a hard-coded question_id would collide in both cases.
"""

from decimal import Decimal, InvalidOperation

from helpers.entities import add_entity
from helpers.properties import set_property, set_literal_property, check_type
from helpers.identifiers import claim_id, make_member_id, make_derived_id
from helpers.user_io import ask_user, question_path
from helpers.units import SCALAR_UNITS_BY_QUANTITY_KIND, DIMENSIONLESS_QUANTITY_KINDS, FRACTION_QUANTITY_KINDS, CHANGE_RATE_QUANTITY_KIND, DURATION_UNITS


# The units per quantity kind, the dimensionless quantity kinds and the fractions with their
# percent additions stand in generator/config/units_and_quantity_kinds.json (loaded by
# helpers/units.py, rule 4.5): the unit hangs at EVERY value, UNITLESS only at the value and
# never at the hlo:Actual, the crate always holds the fraction and never the percentage (rule 4.3).


def fraction_value_hint(quantity_kind):
    """The addition to a value question for a fraction, or "" for any other quantity kind."""
    if quantity_kind not in FRACTION_QUANTITY_KINDS:
        return ""
    word, suffixes = FRACTION_QUANTITY_KINDS[quantity_kind]
    # A fraction without an addition of its own (DimensionlessRatio: yield, conversion) knows only "%".
    accepted = "'25 %'" if suffixes[0] == "%" else f"'25 {suffixes[0]}' or '25 %'"
    return f" (as a {word} between 0 and 1 - 25 {suffixes[0]} is 0.25; {accepted} is converted)"


def fraction_answer_type(quantity_kind):
    """An answer_type for ask_user that turns a fraction answer into its decimal string -
    percentages converted, the range 0..1 enforced - or None for any other quantity kind.

    Raises ValueError on an invalid answer, which ask_user treats like any other
    unconvertible answer: asked again interactively, a stored answer is discarded (or the run
    aborts under --strict). An empty answer stays empty ("no value")."""
    if quantity_kind not in FRACTION_QUANTITY_KINDS:
        return None
    word, own_suffixes = FRACTION_QUANTITY_KINDS[quantity_kind]
    all_suffixes = sorted({s for _, suffixes in FRACTION_QUANTITY_KINDS.values() for s in suffixes} | {"%"}, key=len, reverse=True)

    def convert(raw):
        text = str(raw).strip()
        if not text:
            return ""
        compact = text.replace(" ", "").lower()
        suffix = next((s for s in all_suffixes if compact.endswith(s)), None)
        if suffix is not None and suffix != "%" and suffix not in own_suffixes:
            print(f"'{text}' is given as {suffix}, but this value is a {word} - convert it first, or enter it as a plain fraction.")
            raise ValueError(text)
        number = compact[:-len(suffix)] if suffix else compact
        try:
            value = Decimal(number)
        except InvalidOperation:
            raise ValueError(text)
        if not value.is_finite():
            raise ValueError(text)
        if suffix:
            value = value / 100
        if not Decimal(0) <= value <= Decimal(1):
            print(f"'{text}' is not a {word} between 0 and 1 - a percentage needs its % sign (e.g. '25 %').")
            raise ValueError(text)
        return format(value.normalize(), "f")

    # ask_user names the name in its error message ("Please enter a valid ...").
    convert.__name__ = f"{word} between 0 and 1 (or a percentage such as '25 {own_suffixes[0]}')"
    return convert

# Choice when the QuantityKind of the quantity is not known (e.g. a profile that hangs at a
# task instead of at a ProcessVariable) - then it is asked, instead of leaving the value
# without a unit or allowing free text.
NO_UNIT_OPTION = "No unit / not applicable"


def units_for_quantity_kind(quantity_kind):
    """The choice of units for a QuantityKind, or None if there is none."""
    return SCALAR_UNITS_BY_QUANTITY_KIND.get(quantity_kind)


def change_rate_unit_options(quantity_kind, unit):
    """The unit choice for the change rate of a ramp step in a profile of this quantity kind
    and unit, or None when it does not follow from them - then ask_unit asks for the kind of
    the rate first.

    Without a known quantity kind, the kind is looked up from the profile's unit; it counts
    only when all kinds offering that unit lead to the same rate kind
    (change_rate_quantity_kinds in generator/config/units_and_quantity_kinds.json)."""
    if quantity_kind:
        profile_kinds = {quantity_kind}
    else:
        profile_kinds = {kind for kind, options in SCALAR_UNITS_BY_QUANTITY_KIND.items() if unit and unit in options}
    rate_kinds = {CHANGE_RATE_QUANTITY_KIND[kind] for kind in profile_kinds if kind in CHANGE_RATE_QUANTITY_KIND}
    if len(rate_kinds) != 1:
        return None
    return SCALAR_UNITS_BY_QUANTITY_KIND[rate_kinds.pop()]


def fixed_unit_for_quantity_kind(quantity_kind):
    """The unit that follows from the quantity kind alone, or None when it has to be asked
    for. Only dimensionless kinds have one - see DIMENSIONLESS_QUANTITY_KINDS."""
    return "unit:UNITLESS" if quantity_kind in DIMENSIONLESS_QUANTITY_KINDS else None


def _inherited(series_entity: dict, property_name: str):
    """Get the value of a property from the series template (as a CURIE), or None."""
    if not series_entity:
        return None
    value = series_entity.get(property_name)
    if isinstance(value, list):
        value = value[0] if value else None
    if isinstance(value, dict):
        return value.get("@id")
    return value


def ask_unit(label: str, scope: str, unit_options, question_id_prefix: str):
    """Asks for the unit of a value. If the choice is not known already, the quantity
    kind is asked first - so the answer stays a QUDT unit and does not become
    free text ("C" instead of unit:DEG_C)."""
    if not unit_options:
        kinds = sorted(SCALAR_UNITS_BY_QUANTITY_KIND) + [NO_UNIT_OPTION]
        kind = ask_user(f"[{scope}] What kind of quantity is {label}?", kinds, question_id=f"{question_id_prefix}_quantity_kind")
        if kind == NO_UNIT_OPTION:
            return None
        unit_options = SCALAR_UNITS_BY_QUANTITY_KIND[kind]

    return ask_user(f"[{scope}] Unit of {label}?", list(unit_options) + [NO_UNIT_OPTION], question_id=f"{question_id_prefix}_unit")


def create_scalar_variable(label: str, scope: str, nr: int, namespace_collection: dict, datagraph: dict, global_todo_list: list, local_todo_list: list, unit_options: list = None, unit: str = None, quantity_kind: str = None, *, question_id_prefix: str, entity_id: str):
    """Ask for a plain number (int/double) and create a cpo:ScalarVariable.

    Returns None when no value was given. unit_options is optional (by default no unit
    question is asked); when it is passed - for hasVolume, say, see
    helpers/volume_checks.py - the unit is asked for as well and qudt:hasUnit is set (as
    for time:Duration, see DURATION_UNITS in helpers/units.py).

    quantity_kind is only used to check the answer: for a fraction the question says so,
    a percentage is converted and the range 0..1 enforced (see FRACTION_QUANTITY_KINDS).
    The unit is still decided by unit/unit_options alone.

    entity_id is the content-based ID of the value (helpers/identifiers.py), built by the
    caller from what the value belongs to.
    """
    value_answer = ask_user(f"[{scope}] Value of {label} (int or double){fraction_value_hint(quantity_kind)}?", answer_type=fraction_answer_type(quantity_kind), question_id=f"{question_id_prefix}_value")
    if not value_answer.strip():
        return None

    scalar_type = check_type("cpo:ScalarVariable", namespace_collection)
    experiment_number = nr if scope == "hlo:ExperimentSpecific" else None
    scalar_id = claim_id(entity_id, datagraph, global_todo_list, local_todo_list)
    scalar = {"@id": scalar_id, "@type": [scalar_type, scope]}
    set_literal_property(scalar, "qudt:value", value_answer.strip(), "xsd:decimal", namespace_collection)

    # unit: a unit settled already (e.g. that of the profile this value belongs to) -
    # then it is not asked again.
    unit_answer = unit if unit is not None else ask_unit(label, scope, unit_options, question_id_prefix)
    if unit_answer and unit_answer != NO_UNIT_OPTION:
        # Explicitly as {"@id": ...}, not as a CURIE string: set_property turns a string into a
        # link only if the property itself is declared in a loaded ontology - qudt:hasUnit is not
        # (the QUDT schema file is not loaded). Without that the unit ends up in the crate as the
        # literal "unit:L" instead of as a link to the QUDT unit, while the library values kept by
        # hand correctly carry {"@id": "unit:M3"} - the same error was in all four places of units.
        set_property(scalar, "qudt:hasUnit", {"@id": unit_answer}, namespace_collection)

    add_entity(datagraph, scalar)
    return scalar


# Unit words of a duration (the units themselves: DURATION_UNITS in helpers/units.py).
_DURATION_WORDS = {"s": "unit:SEC", "sec": "unit:SEC", "second": "unit:SEC", "seconds": "unit:SEC",
                   "min": "unit:MIN", "minute": "unit:MIN", "minutes": "unit:MIN",
                   "h": "unit:HR", "hr": "unit:HR", "hour": "unit:HR", "hours": "unit:HR"}


def _parse_duration(answer: str):
    """'12 h' -> ("12", "unit:HR"); a unit may also be named as in QUDT (HR, unit:HR)."""
    parts = answer.strip().split()
    if len(parts) == 2:
        word = parts[1].lower().removeprefix("unit:")
        unit = _DURATION_WORDS.get(word) or next((u for u in DURATION_UNITS if u.lower() == f"unit:{word}"), None)
        try:
            Decimal(parts[0])
        except InvalidOperation:
            unit = None
        if unit:
            return parts[0], unit
    raise ValueError(f"The duration of a profile step '{answer}' is not '<number> <unit>' (s, min, h).")


def _ask_duration(scope: str, nr: int, namespace_collection: dict, datagraph: dict, global_todo_list: list, local_todo_list: list, question_id_prefix: str, entity_id: str):
    """The duration a profile step was set to (time:Duration): a number and a unit, like every other
    duration (helpers/evidence_reference.py) - a plain value of the step, no hlo:Actual: the profile
    is itself a reference, and its steps carry plain values (cpo:ProfileStep). Returns None when no
    duration was given.

    The duration is a value with a unit, not a text on an hlo:Actual (rule 4.1, Actual_NoValue_Shape).
    """
    duration_answer = ask_user(f"[{scope}] Duration of this step (e.g. '10 min', leave empty if unknown)?", question_id=f"{question_id_prefix}_step_duration")
    if not duration_answer.strip():
        return None
    number, unit = _parse_duration(duration_answer)

    duration_type = check_type("time:Duration", namespace_collection)
    duration_id = claim_id(entity_id, datagraph, global_todo_list, local_todo_list)
    duration = {"@id": duration_id, "@type": [duration_type, scope]}
    set_literal_property(duration, "rdf:value", number, "xsd:decimal", namespace_collection)
    set_property(duration, "qudt:hasUnit", {"@id": unit}, namespace_collection)

    add_entity(datagraph, duration)
    return duration


def _create_profile_step(profile: dict, sequence_number: int, scope: str, nr: int, namespace_collection: dict, datagraph: dict, global_todo_list: list, local_todo_list: list, question_id_prefix: str, unit: str = None, quantity_kind: str = None):
    step_kind = ask_user(f"[{scope}] Is profile step {sequence_number} a Transition (ramp between two values) or a Hold (constant value)?", ["Transition", "Hold"], question_id=f"{question_id_prefix}_step_kind")
    step_type_id = "cpo:TransitionStep" if step_kind == "Transition" else "cpo:HoldStep"
    step_type = check_type(step_type_id, namespace_collection)
    experiment_number = nr if scope == "hlo:ExperimentSpecific" else None
    # A step is the n-th member of its profile, its values hang at the step
    # (helpers/identifiers.py) - no running number across all profiles.
    step_id = claim_id(make_member_id(profile["@id"], "Step", sequence_number, scope, experiment_number),
                           datagraph, global_todo_list, local_todo_list)
    step = {"@id": step_id, "@type": [step_type, scope]}

    def _step_value_id(role):
        return make_derived_id(role, step_id, scope, experiment_number)

    set_literal_property(step, "cpo:hasSequenceNumber", sequence_number, "xsd:integer", namespace_collection)

    duration = _ask_duration(scope, nr, namespace_collection, datagraph, global_todo_list, local_todo_list, question_id_prefix, entity_id=_step_value_id("Duration"))
    if duration is not None:
        set_property(step, "cpo:hasDuration", duration, namespace_collection)

    if step_kind == "Hold":
        hold_value = create_scalar_variable(f"the hold value of step {sequence_number}", scope, nr, namespace_collection, datagraph, global_todo_list, local_todo_list, unit=unit, quantity_kind=quantity_kind, question_id_prefix=f"{question_id_prefix}_hold_value", entity_id=_step_value_id("HoldValue"))
        if hold_value is not None:
            set_property(step, "cpo:holdValue", hold_value, namespace_collection)
    else:
        start_value = create_scalar_variable(f"the start value of step {sequence_number}", scope, nr, namespace_collection, datagraph, global_todo_list, local_todo_list, unit=unit, quantity_kind=quantity_kind, question_id_prefix=f"{question_id_prefix}_start_value", entity_id=_step_value_id("StartValue"))
        if start_value is not None:
            set_property(step, "cpo:startValue", start_value, namespace_collection)
        end_value = create_scalar_variable(f"the end value of step {sequence_number}", scope, nr, namespace_collection, datagraph, global_todo_list, local_todo_list, unit=unit, quantity_kind=quantity_kind, question_id_prefix=f"{question_id_prefix}_end_value", entity_id=_step_value_id("EndValue"))
        if end_value is not None:
            set_property(step, "cpo:endValue", end_value, namespace_collection)
        # Without quantity_kind: a rate is no fraction, not even in a profile of a fraction.
        # The rate is profile quantity per time and therefore has a unit of its own (K/min for a
        # temperature ramp), not that of the profile - it is asked.
        change_rate = create_scalar_variable(f"the change rate of step {sequence_number}", scope, nr, namespace_collection, datagraph, global_todo_list, local_todo_list, unit_options=change_rate_unit_options(quantity_kind, unit), question_id_prefix=f"{question_id_prefix}_change_rate", entity_id=_step_value_id("ChangeRate"))
        if change_rate is not None:
            set_property(step, "cpo:changeRate", change_rate, namespace_collection)

    set_property(step, "dcterms:isPartOf", profile, namespace_collection)
    set_property(profile, "dcterms:hasPart", step, namespace_collection, True)

    add_entity(datagraph, step)
    return step


def create_profile_variable(label: str, scope: str, nr: int, namespace_collection: dict, datagraph: dict, global_todo_list: list, local_todo_list: list, unit_options: list = None, unit: str = None, series_profile: dict = None, variable_quantity_kind: str = None, *, question_id_prefix: str, entity_id: str):
    """Ask for any number of profile steps and create the cpo:ProfileVariable that
    references them through dcterms:hasPart.

    The order of entry is the hasSequenceNumber (see the module docstring - an ordered
    list would be more elegant, but hasSequenceNumber stays as a backup). Returns None
    when not a single step was described, in which case the caller falls back to the old
    placeholder mechanism.

    sequence_number is already a manual running counter (1-based) and is reused directly
    as the "profile_step" question_path segment, rather than introducing a second counter.

    variable_quantity_kind is the quantity kind of the process variable this profile
    belongs to, if known. It only serves to check the step values (fractions, see
    create_scalar_variable); what is written onto the profile is unchanged.
    """
    profile_type = check_type("cpo:ProfileVariable", namespace_collection)
    experiment_number = nr if scope == "hlo:ExperimentSpecific" else None
    profile_id = claim_id(entity_id, datagraph, global_todo_list, local_todo_list)
    profile = {"@id": profile_id, "@type": [profile_type, scope]}

    # QuantityKind and unit belong at the profile, not at every single step: they never change
    # within a profile. If the series template carries them already, they are not asked again -
    # the same pattern as for the evidence/reference questions (see
    # ask_add_evidence_at_series_level in helpers/process_variables.py).
    quantity_kind = _inherited(series_profile, "qudt:hasQuantityKind")
    # unit: given by the quantity (UNITLESS for fractions, see fixed_unit_for_quantity_kind above
    # and the call in _create_resolved_value_entity, helpers/evidence_reference.py) or inherited
    # from the series template - otherwise it is asked here once per profile.
    unit = unit or _inherited(series_profile, "qudt:hasUnit")
    if unit is None:
        if quantity_kind is None and not unit_options:
            kinds = sorted(SCALAR_UNITS_BY_QUANTITY_KIND) + [NO_UNIT_OPTION]
            answer = ask_user(f"[{scope}] What kind of quantity does the profile of {label} describe?", kinds, question_id=f"{question_id_prefix}_quantity_kind")
            quantity_kind = None if answer == NO_UNIT_OPTION else answer
        unit = ask_unit(f"the profile of {label}", scope, unit_options or units_for_quantity_kind(quantity_kind), question_id_prefix)
        if unit == NO_UNIT_OPTION:
            unit = None

    if quantity_kind:
        set_property(profile, "qudt:hasQuantityKind", quantity_kind, namespace_collection)
    if unit:
        set_property(profile, "qudt:hasUnit", {"@id": unit}, namespace_collection)

    sequence_number = 1
    while True:
        already_has = sequence_number > 1
        with question_path("profile_step", sequence_number):
            answer = ask_user(f"[{scope}] Add {'another' if already_has else 'a'} step to the profile of {label}?", ["Yes", "No"], question_id=f"{question_id_prefix}_add_another_step")
            if answer == "No":
                break
            _create_profile_step(profile, sequence_number, scope, nr, namespace_collection, datagraph, global_todo_list, local_todo_list, question_id_prefix, unit, variable_quantity_kind or quantity_kind)
        sequence_number += 1

    if sequence_number == 1:
        return None

    add_entity(datagraph, profile)
    return profile
