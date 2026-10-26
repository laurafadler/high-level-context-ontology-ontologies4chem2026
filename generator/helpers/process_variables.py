"""
Generic helper for "Actual" process variables (volume, temperature, flowrate, interface
area, occupation extent, ...) - the same pattern everywhere a quantity is recorded at
series level and then again, with its own evidence/reference values, at experiment level.

Originally part of creation/phase_functions.py (for phases and interfaces). It lives in
helpers so that creation/material_functions.py (stream hasFlowrate, MaterialVolume
hasVolume) can use it too, without creating a circular import between the two creation
modules.
"""

from helpers.entities import add_entity, find_entity, resolve, ref_id
from helpers.properties import set_property, check_type
from helpers.identifiers import generate_id, generate_id_from_name, short_local_name
from helpers.user_io import ask_user
from helpers.value_sources import request_value_sources
from helpers.ontology_functions import quantity_kinds_of_property


def get_series_entity(entity: dict, datagraph: dict):
    """Find the entity one level up that this one specializes, if there is one - for an
    experiment-specific entity its series counterpart, for a series-specific entity its
    fixed counterpart.

    Works for phases just as for interfaces, ports or process variables, as long as
    hlo:specializationOf is set. PhaseInterfaces and PhasePairInterfaces have carried that
    link since get_or_create_phase_interface/create_phase_pair_interface
    (creation/phase_functions.py).

    hlo:specializationOf is deliberately expected to be SINGLE-VALUED here: the crate keeps
    a chain (experiment -> series -> fixed), not parallel edges to several levels. A
    multi-valued entry is therefore a bug at whichever place set it, and is reported loudly
    instead of quietly turning into None - the same way get_interface_phases reports an
    unknown interface type. Precisely this silent case meant for a long time that there was
    not a single experiment-specific port-crossing transfer: the experiment ports pointed at
    their library port and at their series counterpart at the same time, the list went
    unchecked into find_entity, and create_port_crossing_transfers skipped every port as a
    result (see creation/device_functions.py, port creation).

    The context aspects (helpers/context_functions.py) deliberately carry two such edges -
    they are never looked up from here. Should that ever happen, this message is meant to
    appear so that someone decides which of the two is meant.
    """
    series_ref = entity.get("hlo:specializationOf")
    if isinstance(series_ref, list):
        if len(series_ref) != 1:
            raise ValueError(
                f"get_series_entity: '{entity.get('@id')}' has a multi-valued "
                f"hlo:specializationOf ({series_ref}) - exactly one counterpart is expected "
                f"one level higher (experiment -> series -> Fixed). The place that "
                f"set it has to decide on one level."
            )
        series_ref = series_ref[0]
    series_id = series_ref.get("@id") if isinstance(series_ref, dict) else series_ref
    return resolve(datagraph, series_id) if series_id else None


def ask_evidence_known_at_series_level(evidence_known_cache, cache_key, label: str, scope: str):
    """Q2 of the uniform series pattern (see ask_add_evidence_at_series_level for Q1).

    Asks once, at hlo:SeriesSpecific level, whether there is any evidence or reference for
    'label' across the individual experiments at all, and remembers the answer in
    evidence_known_cache[cache_key]. On "No" the evidence/reference questions are skipped
    for this quantity in every experiment (see _series_evidence_known); on "Yes" nothing
    changes and each experiment is asked separately as before.
    """
    if evidence_known_cache is None or scope != "hlo:SeriesSpecific":
        return
    known_answer = ask_user(
        f"Do we know anything (evidence or reference) about {label} in the individual experiments?",
        ["Yes", "No"],
        question_id="know_evidence_per_experiment"
    )
    evidence_known_cache[cache_key] = (known_answer == "Yes")


def ask_add_evidence_at_series_level(evidence_known_cache, label: str, scope: str) -> bool:
    """Q1 of the uniform series pattern: asks, at hlo:SeriesSpecific level, whether to
    attach evidence or a reference for 'label' already at series level (an assumption such
    as "always about 20 degC, 1 bar", for instance).

    Returns False when evidence_known_cache is None or the scope is not SeriesSpecific, in
    which case things stay as before and only the experiment level is asked. Complements
    ask_evidence_known_at_series_level (Q2, "do we know this per experiment") - together
    the two form the pattern used alike for devices, phases and materials.
    """
    if evidence_known_cache is None or scope != "hlo:SeriesSpecific":
        return False
    return ask_user(
        f"[{scope}] Do you want to add evidence/reference for {label} already at series level?",
        ["Yes", "No"],
        question_id="add_evidence_at_series_level"
    ) == "Yes"


def add_specializing_actual(entity: dict, property_name: str, parent_value: dict, value_id: str, scope: str, nr: int,
                        namespace_collection: dict, datagraph: dict) -> dict:
    """The entity's own Actual for a quantity whose value is known one level up (in the end
    from a library): an empty hlo:Actual that specializes the value above it.

    The Actual says "this quantity exists at this exemplar" (rule
    2.1); its value stays where it was determined, in the library, and is reached through
    hlo:specializationOf. Nothing is asked here; whether evidence or a reference is offered for
    it on this level (as for any other quantity) is up to the caller.
    """
    quantity_kind = None
    current = parent_value
    seen = set()
    while current is not None and quantity_kind is None and current.get("@id") not in seen:
        seen.add(current.get("@id"))
        quantity_kind = current.get("qudt:hasQuantityKind")
        parent = current.get("hlo:specializationOf")
        parent_id = parent.get("@id") if isinstance(parent, dict) else parent
        current = resolve(datagraph, parent_id) if parent_id else None

    value = {"@id": value_id, "@type": [check_type("cpo:ProcessVariable", namespace_collection), scope, "hlo:Actual"]}
    if quantity_kind is not None:
        set_property(value, "qudt:hasQuantityKind", quantity_kind, namespace_collection)
    set_property(value, "cpo:isProcessVariableOf", entity, namespace_collection)
    set_property(value, "hlo:specializationOf", parent_value, namespace_collection)
    # The inverse direction only at an entity of the crate - a library value is not changed.
    if "hlo:Fixed" not in (parent_value.get("@type") or []):
        set_property(parent_value, "hlo:hasSpecialization", value, namespace_collection, True)
    set_property(entity, property_name, value, namespace_collection)
    add_entity(datagraph, value)
    return value


def add_phase_process_variable(entity: dict, property_name: str, scope: str, nr: int, namespace_collection: dict, datagraph: dict, todo_list: list, local_todo_list: list, evidence_known_cache: dict = None, offer_values: bool = True, quantity_kinds: list = None):
    """Create an "Actual" process variable for the given property, unless it exists
    already.

    "entity" may be a phase, an interface, an occupation state, a material
    (stream/MaterialVolume) or - for hasFieldStrength, see helpers/energy_fields.py - an
    energy field. Its contexts follow from the shapes at the end of the run
    (helpers/context_links.py).

    evidence_known_cache is optional. When it is passed, two questions are asked at series
    level (the uniform pattern, see ask_add_evidence_at_series_level and
    ask_evidence_known_at_series_level above): first whether to attach evidence or a
    reference at series level already, then whether it is known per experiment at all - on
    "No" the per-experiment question is skipped. This works the same for every kind of
    entity listed above, as soon as "entity" is linked at experiment level to its series
    counterpart through hlo:specializationOf (see get_series_entity).

    The experiment variable is also linked to the matching series variable through
    hlo:specializationOf/hlo:hasSpecialization, where the series entity already carries the
    same property. Each experiment variable still remains a separate, freshly created
    entity with its own evidence and reference values.

    The quantity kinds come from the ontology (cpo:valueHasQuantityKind on the property, see
    helpers/ontology_functions.py: quantity_kinds_of_property; rule 4.4). One allowed kind:
    the Actual carries it. Several (cpo:hasFlowrate, cpo:hasOccupationExtent,
    cpo:hasFieldStrength, cpo:hasConcentration): the Actual carries none, and the values do -
    the quantity is one entry in the lists, and the kind is asked for each value that is given
    (rule 4.4). quantity_kinds narrows the choice where it follows from elsewhere (the
    field type for a field strength).
    """
    # The quantity kinds are a statement of the model and stand at the property in the
    # ontology, not at every call. Checked early, so that a missing annotation shows at once
    # and not only when the quantity is created.
    allowed = quantity_kinds_of_property(property_name, namespace_collection)
    if not allowed:
        raise ValueError(f"{property_name} has no cpo:valueHasQuantityKind in the ontology - add one there.")
    if quantity_kinds is not None and not set(quantity_kinds) <= set(allowed):
        raise ValueError(f"{property_name} allows {', '.join(allowed)} in the ontology, but {', '.join(quantity_kinds)} was passed.")
    fixed_kind = allowed[0] if len(allowed) == 1 else None

    if property_name in entity:
        return None

    base_name = property_name.split(":", 1)[-1]
    if base_name.startswith("has"):
        base_name = base_name[3:]
    experiment_number = nr if scope == "hlo:ExperimentSpecific" else None

    parent_entity = get_series_entity(entity, datagraph)
    from_library = False
    if parent_entity and "hlo:Fixed" in parent_entity.get("@type", []) and parent_entity.get(property_name):
        # The Fixed counterpart knows this value already (e.g. the density of a device body
        # material from the Device Library): an empty actual of its own that specializes it
        # (add_specializing_actual). The value stays in the library. The quantity is offered in
        # the lists all the same like any other (rule 4.2): on this level there can be a
        # measurement or assumption in addition, and whether the experiments know anything about
        # it is said by the series.
        inherited_ref = parent_entity[property_name]
        inherited = resolve(datagraph, ref_id(inherited_ref))
        if inherited is None:
            set_property(entity, property_name, inherited_ref, namespace_collection)
            return None
        own_id = generate_id_from_name(f"{base_name}_{short_local_name(entity['@id'])}", scope, experiment_number)
        process_variable = add_specializing_actual(entity, property_name, inherited, own_id, scope, nr, namespace_collection,
                                                   datagraph)
        from_library = True
        series_entity = None
        series_pv = None
    else:
        pv_type = check_type("cpo:ProcessVariable", namespace_collection)
        pv_id = generate_id_from_name(f"{base_name}_{short_local_name(entity['@id'])}", scope, experiment_number)

        # Safety net against a silent double assignment: generate_id_from_name deliberately
        # appends no counter and relies on the name being unique already. If that is not so,
        # add_entity silently discards the second quantity and both entities point at the same
        # ProcessVariable - with the evidence, which then hangs at a discarded dict and does not
        # appear in the crate at all. That is exactly how the transfer flowrates were lost for a
        # long time (see short_local_name in helpers/identifiers.py).
        if find_entity(datagraph, pv_id) is not None:
            unique_id = generate_id(f"{base_name}_{short_local_name(entity['@id'])}", datagraph, todo_list + local_todo_list, scope, experiment_number)
            print(f"[{scope}] Note: {pv_id} already exists - using {unique_id} for {entity['@id']} instead.")
            pv_id = unique_id

        process_variable = {
            "@id": pv_id,
            "@type": [pv_type, scope, "hlo:Actual"]
        }
        # Only a settled quantity kind belongs at the actual; if the property allows several, any
        # here would be a statement nobody made (rule 4.4).
        if fixed_kind is not None:
            set_property(process_variable, "qudt:hasQuantityKind", fixed_kind, namespace_collection)
        set_property(process_variable, "cpo:isProcessVariableOf", entity, namespace_collection)
        set_property(entity, property_name, process_variable, namespace_collection)

        # Connect the levels: the experiment quantity specializes the series quantity of the same name.
        series_entity = get_series_entity(entity, datagraph) if scope == "hlo:ExperimentSpecific" else None
        series_pv = None
        if series_entity:
            series_pv_ref = series_entity.get(property_name)
            series_pv_id = series_pv_ref.get("@id") if isinstance(series_pv_ref, dict) else series_pv_ref
            series_pv = find_entity(datagraph, series_pv_id) if series_pv_id else None
            if series_pv:
                set_property(process_variable, "hlo:specializationOf", series_pv, namespace_collection)
                set_property(series_pv, "hlo:hasSpecialization", process_variable, namespace_collection, True)

    # Evidence/reference: the quantity only registers itself, the question is asked per list of its
    # exemplar (helpers/value_sources.py). The segment stays the old one ("temperature",
    # "pressure", ...), so that all further keys stay the same - otherwise the different
    # quantities of the same entity would have the same key.
    # The quantity kind is not settled beforehand (rule 4.4): the quantity
    # is ONE entry, and in which kind a value stands is asked at this value - among the kinds the
    # property allows or the caller prescribes (the field strength follows from the type of
    # field). One allowed kind is carried by the actual already. An empty prescription: no values.
    if scope == "hlo:SeriesSpecific":
        gate_key = (entity["@id"], property_name)
    else:
        gate_key = (series_entity["@id"], property_name) if series_entity else None
    options = list(quantity_kinds) if quantity_kinds is not None else list(allowed)
    request_value_sources(
        process_variable, entity, scope, nr, namespace_collection, datagraph, todo_list, local_todo_list,
        quantity=base_name.lower(), segment=base_name.lower(),
        offer_at_series=evidence_known_cache is not None,
        gate_key=gate_key if evidence_known_cache is not None else None,
        evidence_known_cache=evidence_known_cache, offered=offer_values and bool(options),
        quantity_kind=options[0] if fixed_kind is None and len(options) == 1 else None,
        quantity_kind_options=options if fixed_kind is None and len(options) > 1 else None,
    )

    # The actual inherited from the library was stored by add_specializing_actual already.
    if not from_library:
        add_entity(datagraph, process_variable)
    return process_variable
