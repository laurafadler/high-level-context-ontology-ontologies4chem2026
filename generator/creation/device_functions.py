"""
The devices of a series and its experiments.

create_all_devices asks which devices of the Device Library were used, adds the parts of composite
devices, and copies each device to the series and to every experiment (rule 3.1): ports, forms,
body material, energy fields, power input, rotational speed, mode of operation, the history times
of the library entry, and the content - taken over from the library for a container of the
inventory (rule 3.10), otherwise put on the to-do list and made by material_functions.py. An
exemplar of a template is copied with the parts of its template (rule 3.11). At the end the parts
of composite devices and the locations of devices inside other devices are linked on every level.
"""

from contextlib import nullcontext

from helpers.entities import find_entity, add_entity, as_list, ref_id, ref_ids, find_entities_by_type
from helpers.properties import set_property, set_location, check_type, get_type
from helpers.ontology_functions import check_existence, quantity_kind_of_property
from helpers.identifiers import (generate_id_from_library_id, generate_name, make_root_id, make_specialization_id,
                                 make_owned_id, claim_id, key_name, CRATE_NAMESPACE_PREFIX, crate_id,
                                 library_name_alias)
from helpers.library_functions import find_library_item
from helpers.todo_functions import add_todo_item, merge_todo_lists
from helpers.energy_fields import create_energy_field, ASKABLE_ENERGY_FIELD_TYPES
from helpers.value_sources import request_value_sources
from helpers.forms import own_forms
from creation.material_functions import ask_name, fixed_library_material, create_series_material_from_fixed, create_experiment_material_from_series
from helpers.user_io import ask_user, ask_user_list, question_path, SAME_OPTIONS, known_answer
from helpers.inventory_state import content_history
from helpers.series_statements import note_mode_not_known_yet


# Points in time from the history of the device: last serviced, last calibrated - both come from the
# library entry. "Last used" (cpo:lastUsedTime, cpo:lastUsedPurpose) hangs on the time of the experiment
# and is set after the task stage (creation/device_usage_functions.py: record_device_usage, rule 5.2).
HISTORY_TIME_PROPERTIES = ("cpo:lastServicedTime", "cpo:lastCalibratedTime")


def add_reference_stub(target_id: str, type_name: str, comment: str, datagraph: dict, namespace_collection: dict):
    """A type stub for an entity the crate only points to and that is not described in it - a task or a
    moment of an earlier crate, or a placeholder of the device library named by a bare fragment id.
    It asserts the type, nothing else, so that the crate on its own satisfies the requirements that ask
    for the class (Device_Information_R3, Device_Time_R1/R2); in a store holding every crate it says
    what the earlier crate says anyway. Nothing is added when the entity is in this crate already."""
    if find_entity(datagraph, target_id) is not None:
        return None
    stub = {"@id": target_id, "@type": [check_type(type_name, namespace_collection)]}
    set_property(stub, "rdfs:comment", comment, namespace_collection)
    add_entity(datagraph, stub)
    return stub


def copy_history_times(device: dict, twin_device: dict, device_library: dict, datagraph: dict, namespace_collection: dict, scope: str, series_device: dict = None):
    """Point a crate device at the history timestamps of its library entry (cpo:lastServicedTime,
    cpo:lastCalibratedTime).

    These are not quantities of the device but REFERENCES to a moment that already exists - the
    end of a service or a calibration in the library. No own Actual is created
    (rules 3.2 and 5.2). A moment in an earlier crate gets a type stub here
    (add_reference_stub). The last use is set later, by time (record_device_usage).
    """
    for property_name in HISTORY_TIME_PROPERTIES:
        reference = twin_device.get(property_name)
        if not reference:
            continue

        # check_existence raises for a property that is in no loaded ontology (that is how the
        # project catches typos) - here this is caught instead of stopping the whole run.
        try:
            check_existence(property_name, namespace_collection, "property")
        except ValueError:
            print(f"[{scope}] Note: {property_name} is not declared in the ontology yet - "
                  f"the value recorded in the device library is not linked.")
            continue

        parent_id = ref_id(reference)
        if series_device is not None and series_device.get(property_name):
            parent_id = ref_id(series_device[property_name])
        elif not parent_id.startswith(f"{CRATE_NAMESPACE_PREFIX}:") and find_entity(device_library, parent_id) is None:
            # A reference into the crate of an earlier run (crate:...) is intended; one into the
            # library that does not resolve there is an error of the library.
            print(f"[{scope}] Warning: {twin_device['@id']} points to {parent_id} via {property_name}, "
                  f"but that entity is not in the device library - skipping.")
            continue
        set_property(device, property_name, {"@id": parent_id}, namespace_collection)
        # A point in time in an earlier crate is not described here, only its type is named - like
        # the task at lastUsedPurpose. A point in time of the library is present when validating.
        if parent_id.startswith(f"{CRATE_NAMESPACE_PREFIX}:") and not parent_id.startswith(crate_id("")):
            add_reference_stub(parent_id, "time:Instant",
                               "Cross-crate reference: this moment lies in an earlier crate, it is not described "
                               "here. Only its type is asserted, so that the history of a device can be followed "
                               "from this crate.", datagraph, namespace_collection)


def add_rotational_speed(device: dict, twin_device: dict, scope: str, nr, namespace_collection: dict, datagraph: dict,
                         todo_list: list, local_todo_list: list, evidence_known_cache: dict = None,
                         series_device: dict = None, series_actual_id: str = None) -> str | None:
    """The rotational speed of a device whose library entry has cpo:canRotate true (rule 4.10):
    an Actual cpo:hasRotationalSpeed on the series and every experiment, its values asked through the
    device's lists like any other quantity. Returns the ID of the Actual (None without canRotate).

    A set profile (ramp up, hold, ramp down) is the reference of this actual - type Set,
    kind "Profile" (helpers/evidence_reference.py), determined by a SettingTask; the task that
    executes it (Stirring) points at it with cpo:executesProfile. The speed does not belong at
    cpo:hasPowerInput: the power input is a different quantity (quantitykind:ElectricPower), which
    is related to the speed but is mostly unknown. Whoever knows both connects them
    via hlo:isCoupledWith.
    local_todo_list: the caller passes the global list (value_todo_list in create_series_device).
    """
    if not twin_device.get("cpo:canRotate"):
        return None
    rotational_speed = {
        "@id": claim_id(make_owned_id("RotationalSpeed", device["@id"]), datagraph, todo_list),
        "@type": [check_type("cpo:ProcessVariable", namespace_collection), scope, "hlo:Actual"],
    }
    set_property(rotational_speed, "qudt:hasQuantityKind",
                 quantity_kind_of_property("cpo:hasRotationalSpeed", namespace_collection), namespace_collection)
    # A question_path segment of its own as for the power input (see create_series_device).
    if series_device is None:
        request_value_sources(
            rotational_speed, device, scope, nr, namespace_collection, datagraph, todo_list, local_todo_list,
            quantity="rotational_speed", segment="rotational_speed",
            offer_at_series=evidence_known_cache is not None,
            gate_key=(device["@id"], "cpo:hasRotationalSpeed") if evidence_known_cache is not None else None,
            evidence_known_cache=evidence_known_cache,
        )
    else:
        request_value_sources(
            rotational_speed, device, scope, nr, namespace_collection, datagraph, todo_list, local_todo_list,
            quantity="rotational_speed", segment="rotational_speed",
            gate_key=(series_device["@id"], "cpo:hasRotationalSpeed") if evidence_known_cache is not None else None,
            evidence_known_cache=evidence_known_cache,
        )
    set_property(device, "cpo:hasRotationalSpeed", rotational_speed, namespace_collection)
    set_property(rotational_speed, "cpo:isRotationalSpeedOf", device, namespace_collection)
    if series_actual_id:
        series_actual = find_entity(datagraph, series_actual_id)
        set_property(rotational_speed, "hlo:specializationOf", series_actual, namespace_collection)
        set_property(series_actual, "hlo:hasSpecialization", rotational_speed, namespace_collection, True)
    add_entity(datagraph, rotational_speed)
    return rotational_speed["@id"]


def add_power_input(device: dict, twin_device: dict, scope: str, nr, namespace_collection: dict, datagraph: dict,
                    todo_list: list, local_todo_list: list, evidence_known_cache: dict = None,
                    series_device: dict = None, series_actual_id: str = None) -> str | None:
    """The power input of a device whose library entry has cpo:canReceivePower true (Device_Energy_R3):
    an Actual cpo:hasPowerInput with QuantityKind ElectricPower on the series and every experiment, its
    values asked through the device's lists like any other quantity. Returns the ID of the Actual (None
    without canReceivePower). Built like add_rotational_speed.

    A question_path segment of its own, "power_input" - otherwise these questions would make the same
    key as e.g. the energy field of the same device (helpers/energy_fields.py: create_energy_field). On
    the experiment level nothing is asked when "No" was cached on the series level for "do we know this
    per experiment" (helpers/process_variables.py).
    local_todo_list: the caller passes the global list (value_todo_list in create_series_device).
    """
    if not twin_device.get("cpo:canReceivePower"):
        return None
    power_input = {
        "@id": claim_id(make_owned_id("PowerInput", device["@id"]), datagraph, todo_list),
        "@type": [check_type("cpo:ProcessVariable", namespace_collection), scope, "hlo:Actual"],
    }
    set_property(power_input, "qudt:hasQuantityKind",
                 quantity_kind_of_property("cpo:hasPowerInput", namespace_collection), namespace_collection)
    if series_device is None:
        request_value_sources(
            power_input, device, scope, nr, namespace_collection, datagraph, todo_list, local_todo_list,
            quantity="power_input", segment="power_input",
            offer_at_series=evidence_known_cache is not None,
            gate_key=(device["@id"], "cpo:hasPowerInput") if evidence_known_cache is not None else None,
            evidence_known_cache=evidence_known_cache,
        )
    else:
        request_value_sources(
            power_input, device, scope, nr, namespace_collection, datagraph, todo_list, local_todo_list,
            quantity="power_input", segment="power_input",
            gate_key=(series_device["@id"], "cpo:hasPowerInput") if evidence_known_cache is not None else None,
            evidence_known_cache=evidence_known_cache,
        )
    set_property(device, "cpo:hasPowerInput", power_input, namespace_collection)
    set_property(power_input, "cpo:isPowerInputOf", device, namespace_collection)
    if series_actual_id:
        series_actual = find_entity(datagraph, series_actual_id)
        set_property(power_input, "hlo:specializationOf", series_actual, namespace_collection)
        set_property(series_actual, "hlo:hasSpecialization", power_input, namespace_collection, True)
    add_entity(datagraph, power_input)
    return power_input["@id"]


# The third answer to "which material does the device contain": its cavity holds only the gas around it.
NOTHING_BUT_SURROUNDING_GAS = "Nothing but the gas around it"


def device_has_cavity(twin_device: dict, device_library: dict) -> bool:
    """Whether the library device can hold material: one of the forms it defines has a cavity
    (cpo:hasCavityForm - a cup, a tube, an annular shell, a closed hollow cylinder). That decides
    whether its contents are asked for (rule 3a.10)."""
    for form_id in ref_ids(twin_device.get("cpo:definesForm")):
        form = find_entity(device_library, form_id)
        if form is not None and form.get("cpo:hasCavityForm"):
            return True
    return False


def _with_cavities(forms: dict, datagraph: dict, device_library: dict) -> dict:
    """The form copies of a device (form one level up -> own copy, as own_forms returns them),
    together with their cavities - so that a content from the library, which fills the cavity of
    its template, fills the cavity copy of this device instead of making a form of its own."""
    shared = dict(forms)
    for parent_id, copy in forms.items():
        parent = find_entity(datagraph, parent_id) or find_entity(device_library, parent_id)
        parent_cavity, own_cavity = (ref_id(parent.get("cpo:hasCavityForm")) if parent else None), ref_id(copy.get("cpo:hasCavityForm"))
        if parent_cavity and own_cavity:
            shared[parent_cavity] = find_entity(datagraph, own_cavity)
    return shared


def create_series_device(datagraph: dict, device_library: dict, x: int, namespace_collection: dict, todo_list: list, twin_device: dict = None, evidence_known_cache: dict = None):
    scope = "hlo:SeriesSpecific"

    # Write an empty local to-do list
    local_todo_list = []
    # Values registered directly under the question path of the device (power input, speed,
    # form dimensions) are asked only when this path is left (helpers/value_sources.py) - by then
    # create_all_devices has already taken over the local list, and a task stub on it (the task of a
    # value with a type) would be lost. They therefore register their stubs right away on the global
    # list; there a later experiment also finds the series template. Energy field, body material and
    # content have paths of their own and are asked before - they stay with the local list.
    value_todo_list = todo_list
    information_for_experimental_scope = {}

    ### -----------------------------------------------------------------------------------------
    ### Basic Information: Type and ID
    ### -----------------------------------------------------------------------------------------

    # Find the type by matching with an item of the device library - not asked when twin_device is
    # settled already (create_all_devices passes it, also for the parts of a composite device).
    if twin_device is None:
        twin_device = find_library_item(device_library, "device:", f"Which ID in the Device Library corresponds to the device number {x}?", question_id="select_from_library", entity_type="cpo:Device", namespace_collection=namespace_collection)

    device_type = get_type(twin_device)

    # Derive the ID from the library entry (e.g. "device:reactor001" -> "crate:<identifier>/reactor001_SeriesSpecific"),
    # so that the ID shows directly which library device is behind it.
    entity_id = generate_id_from_library_id(twin_device["@id"], scope)

    device = {
            "@id": entity_id,
            "@type": [device_type, scope]
        }

    # The link to the library entry right away, as for material and phase (material_functions.py):
    # everything made at the device afterwards finds its counterpart one level higher via the chain,
    # instead of having it handed through.
    set_property(device, "hlo:specializationOf", twin_device, namespace_collection)

    ### -----------------------------------------------------------------------------------------
    ### Further Information: Everything else
    ### -----------------------------------------------------------------------------------------

    # Name -----------------------------------------------------------------------------------------
    name = generate_name(entity_id)
    set_property(device, "schema:name", name, namespace_collection)

    # Description -----------------------------------------------------------------------------------------
    description = f"This is the device entity for device {key_name(entity_id)}, which is a {device_type}."
    set_property(device, "schema:description", description, namespace_collection)

    # Ports: all ports of the device on this level, linked with the device.
    device = create_deviceport(device, scope, twin_device, namespace_collection, datagraph, todo_list, device_library)

    # Contained Material -----------------------------------------------------------------------------------------
    # If the content is in the library already (a container of the store, cpo:ChemicalContainer), it is
    # taken over below like the body material, and nothing is asked (rule 3.10).
    library_contents = _library_contents(twin_device, device_library, name, datagraph)
    if device_has_cavity(twin_device, device_library) and not library_contents:
        # The device is able to hold material - what does it hold in the process at hand?
        # The kind of material (Stream or MaterialVolume) stands once at the series: it belongs to the
        # setup, and everything attached to it (phases, interfaces, transfers, feeds) is created at the
        # series and only specialized in the experiment (rule 3.1). Another material is another setup -
        # a series of its own (rule 7c.2).
        information_for_experimental_scope["sameTypeOfContainedMaterial"] = True
        # A cavity can also hold nothing of its own (the GL45 cap, a cup upside down on its
        # bottle): then only the gas around it is in it - the headspace of the bottle, the room air - and no material
        # is made. "Nothing" would exclude that gas, hence the wording. Whether a device holds something is a
        # question of its use, so it is asked per crate, not stated in the library.
        answer_contained_material = ask_user(f"Which type of material, other than the gas around it, does {name} contain in this process?",
                                             ["cpo:Stream", "cpo:MaterialVolume", NOTHING_BUT_SURROUNDING_GAS], question_id="contained_material_type")
    if device_has_cavity(twin_device, device_library) and not library_contents and answer_contained_material != NOTHING_BUT_SURROUNDING_GAS:
        todo_item_type = check_type(answer_contained_material, namespace_collection)
        # The ID uses the same scheme as the "additional materials" of material_functions.py, so that
        # two streams are named alike, whoever made them.
        # Ask the name here already (with the device as context) instead of only later in the
        # collected creation of materials (create_material_from_todo), where the relation to the
        # device would no longer be visible ("this Stream" instead of "this Stream contained in
        # {name}"). The entity itself (phases, volume/flowrate, ports, ...) is still made there,
        # see material_functions.py.
        # The name comes before the ID, because the ID is made from it (rule 1.1).
        contained_material_type_short = answer_contained_material.split(":", 1)[-1]
        contained_material_name = ask_name(scope, f"{contained_material_type_short} contained in {name}")
        todo_item_id = claim_id(make_root_id("Material", contained_material_name, scope),
                                    datagraph, todo_list, local_todo_list, what=f"The material '{contained_material_name}'")
        information_for_experimental_scope["series_TypeOfContainedMaterial_todo"] = todo_item_type
        information_for_experimental_scope["series_ContainedMaterial_id"] = todo_item_id

        todo_item = {
            "@id": todo_item_id,
            "@type": [todo_item_type, scope]
        }
        set_property(todo_item, "schema:name", contained_material_name, namespace_collection)

        set_property(todo_item, "cpo:materialContainedIn", device, namespace_collection)

        add_todo_item(local_todo_list, todo_item)
        set_property(device, "cpo:containsMaterial", todo_item, namespace_collection)

    # EnergyField -----------------------------------------------------------------------------------------
    # An energy field of its own: if the device can create one (library: cpo:canCreateEnergyField or a
    # field stored there), it gets one - whether it also occurred in an experiment is said by its
    # occurrence (helpers/energy_fields.py: create_energy_field, rule 3.1a). The type comes from the
    # library field; it is asked only if the library names none.
    library_fields = [find_entity(device_library, ref_id(ref)) for ref in as_list(twin_device.get("cpo:hasEnergyField"))]
    library_fields = [field for field in library_fields if field is not None]
    if twin_device.get("cpo:canCreateEnergyField") or library_fields:
        field_types = []
        for library_field in library_fields:
            field_type = ref_id(library_field.get("cpo:hasEnergyFieldType"))
            field_types.append(field_type)
            create_energy_field(device, field_type, scope, 1, namespace_collection, datagraph, todo_list,
                                local_todo_list, evidence_known_cache, library_field=library_field, library=device_library)
        if not library_fields:
            # As a list: a device can create several fields, one per type.
            for field_type in ask_user_list(f"Which types of energy field can {device['@id']} generate? (The general gravity is not included here.)",
                                            list(ASKABLE_ENERGY_FIELD_TYPES.values()), question_id="energy_field_types", required=True):
                field_types.append(field_type)
                create_energy_field(device, field_type, scope, 1, namespace_collection, datagraph, todo_list,
                                    local_todo_list, evidence_known_cache)
        information_for_experimental_scope["energy_field_types"] = field_types

    # Last used: after the task stage, by time (creation/device_usage_functions.py).

    # Points in time from the history of the device ------------------------------------------------------------------
    copy_history_times(device, twin_device, device_library, datagraph, namespace_collection, scope)

    # PowerInput -----------------------------------------------------------------------------------------
    information_for_experimental_scope["series_power_input_id"] = add_power_input(
        device, twin_device, scope, 1, namespace_collection, datagraph, todo_list, value_todo_list,
        evidence_known_cache=evidence_known_cache)

    # RotationalSpeed -----------------------------------------------------------------------------------------
    information_for_experimental_scope["series_rotational_speed_id"] = add_rotational_speed(
        device, twin_device, scope, 1, namespace_collection, datagraph, todo_list, value_todo_list,
        evidence_known_cache=evidence_known_cache)

    # Location: set for all devices together at the end of create_all_devices (devices inside other
    # devices) and by create_all_environments (devices standing in a room).

    # Mode of Operation -----------------------------------------------------------------------------------------
    if twin_device.get("cpo:supportsOperatingMode"):
        # The operation mode is a concept, not a quantity: cpo:hasModeOfOperation points directly at an
        # individual (cpo:Batch, cpo:FedBatch, cpo:Flow), chosen from the list of the library
        # (cpo:supportsOperatingMode). No actual of its own per level (rule 3.6).
        # If it is the same in every experiment, it stands once at the series and the experiments read
        # it via the chain; otherwise it stands at every experiment, and the series carries all modes
        # used (create_experiment_device).
        sameOperationMode_answer = ask_user(f"Is the {device['@id']} operated in the same mode for every experiment?", SAME_OPTIONS, question_id="same_operation_mode_across_experiments")
        # "Not known yet" like "No": the mode is asked per experiment. When the series is completed it
        # is decided whether it belongs at the series (helpers/series_statements.py).
        information_for_experimental_scope["sameOperationMode"] = sameOperationMode_answer == "Yes"
        if sameOperationMode_answer == "Not known yet":
            note_mode_not_known_yet(device)

        if information_for_experimental_scope["sameOperationMode"]:
            possible_modes = [mode["@id"] for mode in twin_device.get("cpo:supportsOperatingMode", [])]
            mode_answer = ask_user(f"In which mode is {device['schema:name']} operated in this series?", possible_modes, question_id="operation_mode")
            set_property(device, "cpo:hasModeOfOperation", {"@id": mode_answer}, namespace_collection)

    # Temperature/pressure are not asked at the device itself but at the phases of its body material
    # (cpo:madeOfMaterial, see below), through the normal mechanism of phase process variables
    # (complete_phase in phase_functions.py).

    # Device material (cpo:madeOfMaterial) ---------------------------------------------------------------------------
    # The material this device (part) consists of (e.g. the glass body of a vessel, the
    # stainless steel of a stirrer) - stored in the library already as an ordinary Fixed
    # MaterialVolume with phase(s)/species (see device_library.jsonld), copied here
    # unconditionally and specialized (not only on request) - only then can the existing
    # interface machinery (create_interfaces_for_phases) capture interfaces to this material
    # (temperature, transfers, occupation states, ... need real datagraph entities).
    # cpo:madeOfMaterial may carry several values: a body can consist of several LAYERS of the
    # same wall (enamelled steel vessel, coated stirrer). A detachable part with a geometry of
    # its own (lid, glass box), however, is a device of its own under dcterms:hasPart, not a
    # second body material.
    # Forms of the device of its own on this level, with actuals of their own for every
    # dimension (helpers/forms.py). The body material shares them, as in the library (rule 3a.11).
    # The dimensions are offered in the list of the device, although the library knows them (rule 4.2).
    device_forms = own_forms(device, twin_device, scope, 1, namespace_collection, datagraph, device_library, offer={"todo_list": todo_list, "local_todo_list": value_todo_list,
                                    "evidence_known_cache": evidence_known_cache})

    for fixed_material_id in ref_ids(twin_device.get("cpo:madeOfMaterial")):
        fixed_device_material = fixed_library_material(fixed_material_id, device_library)
        if fixed_device_material:
            series_device_material = create_series_material_from_fixed(
                fixed_device_material, namespace_collection, datagraph, todo_list, local_todo_list,
                material_type_id="cpo:BodyMaterial", context_label=f"Body material of {name}", evidence_known_cache=evidence_known_cache,
                stable_index_level="body_material", library=device_library, shared_forms=device_forms
            )
            set_property(device, "cpo:madeOfMaterial", series_device_material, namespace_collection, True)
            # Inverse direction: without it a phase of the body would not get to its device and thus
            # not into its surroundings (collecting paths of energy fields).
            set_property(series_device_material, "cpo:isBodyMaterialOf", device, namespace_collection, True)
            information_for_experimental_scope.setdefault("series_device_material_ids", []).append(series_device_material["@id"])

    # Content from the library (rule 3.10): lot, manufacturer, purity and initial amount
    # belong to the bottle, not to the experiment. Copied and specialized like the room air; it fills
    # the cavity copy of THIS device.
    for fixed_content in library_contents:
        series_content = create_series_material_from_fixed(
            fixed_content, namespace_collection, datagraph, todo_list, local_todo_list,
            material_type_id="cpo:MaterialVolume", context_label=f"Content of {name}", evidence_known_cache=evidence_known_cache,
            library=device_library, shared_forms=_with_cavities(device_forms, datagraph, device_library)
        )
        set_property(device, "cpo:containsMaterial", series_content, namespace_collection)
        set_property(series_content, "cpo:materialContainedIn", device, namespace_collection)
        information_for_experimental_scope.setdefault("series_library_content_ids", []).append(series_content["@id"])

    ### -----------------------------------------------------------------------------------------
    ### Add to datagraph
    ### -----------------------------------------------------------------------------------------

    add_entity(datagraph, device)

    return device, twin_device, local_todo_list, information_for_experimental_scope


def create_experiment_device(datagraph: dict, device_library: dict, x: int, namespace_collection: dict, todo_list: list, experiment_number: int, series_device: dict, twin_device: dict, information_for_experimental_scope: dict, evidence_known_cache: dict = None):
    scope = "hlo:ExperimentSpecific"

    # Write an empty local to-do list
    local_todo_list = []
    # Values registered directly under the question path of the device (power input, speed,
    # form dimensions) are asked only when this path is left (helpers/value_sources.py) - by then
    # create_all_devices has already taken over the local list, and a task stub on it (the task of a
    # value with a type) would be lost. They therefore register their stubs right away on the global
    # list; there a later experiment also finds the series template. Energy field, body material and
    # content have paths of their own and are asked before - they stay with the local list.
    value_todo_list = todo_list

    ### -----------------------------------------------------------------------------------------
    ### Basic Information: Type and ID
    ### -----------------------------------------------------------------------------------------

    device_type = get_type(twin_device)

    # Derive the ID from the library entry (e.g. "device:reactor001" -> "crate:<identifier>/reactor001_ExperimentSpecific_2"),
    # so that the ID shows directly which library device and which experiment are behind it.
    entity_id = generate_id_from_library_id(twin_device["@id"], scope, experiment_number)

    device = {
            "@id": entity_id,
            "@type": [device_type, scope]
        }

    # The link to the series counterpart right away, as for material and phase: the energy field and
    # everything else made at the device afterwards finds its series via the chain.
    set_property(device, "hlo:specializationOf", series_device, namespace_collection)
    set_property(series_device, "hlo:hasSpecialization", device, namespace_collection, True)

    ### -----------------------------------------------------------------------------------------
    ### Further Information: Everything else
    ### -----------------------------------------------------------------------------------------

    # Name -----------------------------------------------------------------------------------------
    name = generate_name(entity_id)
    set_property(device, "schema:name", name, namespace_collection)

    # Description -----------------------------------------------------------------------------------------
    description = f"This is the device entity for device {key_name(entity_id)}, which is a {device_type}, which was used in Experiment {experiment_number}"
    set_property(device, "schema:description", description, namespace_collection)

    # Ports: all ports of the device on this level, each specializing its series port.
    device = create_deviceport(device, scope, twin_device, namespace_collection, datagraph, todo_list, device_library, experiment_number, series_device)

    # Contained Material -----------------------------------------------------------------------------------------
    # A content from the library is made further below (series_library_content_ids), not here.
    if device_has_cavity(twin_device, device_library) and "series_ContainedMaterial_id" in information_for_experimental_scope:
        # The kind stands at the series (see create_series_device), the experiment takes it over.
        answer_contained_material = information_for_experimental_scope["series_TypeOfContainedMaterial_todo"]
        todo_item_type = check_type(answer_contained_material, namespace_collection)

        # The experiment version carries the local name of its series template, so that the
        # experiment can be seen directly in the ID.
        todo_item_id = claim_id(
            make_specialization_id(information_for_experimental_scope["series_ContainedMaterial_id"], experiment_number),
            datagraph, todo_list)

        series_todo_item_id = information_for_experimental_scope["series_ContainedMaterial_id"]

        todo_item = {
            "@id": todo_item_id,
            "@type": [todo_item_type, scope]
        }

        set_property(todo_item, "cpo:materialContainedIn", device, namespace_collection)
        set_property(device, "cpo:containsMaterial", todo_item, namespace_collection)

        # Link between series and experiment material.
        series_todo_item = find_entity(todo_list, series_todo_item_id)
        set_property(todo_item, "hlo:specializationOf", series_todo_item, namespace_collection)
        set_property(series_todo_item, "hlo:hasSpecialization", todo_item, namespace_collection, True)

        add_todo_item(local_todo_list, todo_item)

    # EnergyField -----------------------------------------------------------------------------------------
    for field_type in information_for_experimental_scope.get("energy_field_types", []):
        create_energy_field(
            device, field_type, scope, experiment_number,
            namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache
        )

    # Last used: after the task stage, by time (creation/device_usage_functions.py) - only then is
    # it settled when this experiment started.

    # Points in time from the history of the device ------------------------------------------------------------------
    copy_history_times(device, twin_device, device_library, datagraph, namespace_collection, scope,
                       series_device=series_device)

    # PowerInput -----------------------------------------------------------------------------------------
    add_power_input(device, twin_device, scope, experiment_number, namespace_collection, datagraph, todo_list,
                    value_todo_list, evidence_known_cache=evidence_known_cache, series_device=series_device,
                    series_actual_id=information_for_experimental_scope.get("series_power_input_id"))

    # RotationalSpeed -----------------------------------------------------------------------------------------
    add_rotational_speed(device, twin_device, scope, experiment_number, namespace_collection, datagraph, todo_list,
                         value_todo_list, evidence_known_cache=evidence_known_cache, series_device=series_device,
                         series_actual_id=information_for_experimental_scope.get("series_rotational_speed_id"))

    # Mode of Operation -----------------------------------------------------------------------------------------
    if twin_device.get("cpo:supportsOperatingMode") and not information_for_experimental_scope.get("sameOperationMode", True):
        # Different per experiment: the mode stands here, and the series collects all modes used
        # (see create_series_device).
        possible_modes = [mode["@id"] for mode in twin_device.get("cpo:supportsOperatingMode", [])]
        mode_answer = ask_user(f"In which mode is {device["schema:name"]} operated in Experiment {experiment_number}?", possible_modes, question_id="operation_mode")
        set_property(device, "cpo:hasModeOfOperation", {"@id": mode_answer}, namespace_collection)
        set_property(series_device, "cpo:hasModeOfOperation", {"@id": mode_answer}, namespace_collection, True)

    # Device material (cpo:madeOfMaterial) ---------------------------------------------------------------------------
    # One layer per pass, see the loop on the series level further above.
    device_forms = own_forms(device, series_device, scope, experiment_number, namespace_collection, datagraph, device_library, offer={"todo_list": todo_list, "local_todo_list": value_todo_list,
                                    "evidence_known_cache": evidence_known_cache})

    for series_device_material_id in information_for_experimental_scope.get("series_device_material_ids", []):
        series_device_material = find_entity(datagraph, series_device_material_id)
        if series_device_material:
            experiment_device_material = create_experiment_material_from_series(
                series_device_material, experiment_number, namespace_collection, datagraph, todo_list, local_todo_list,
                material_type_id="cpo:BodyMaterial", context_label=f"Body material of {name}", evidence_known_cache=evidence_known_cache,
                stable_index_level="body_material", library=device_library, shared_forms=device_forms
            )
            set_property(device, "cpo:madeOfMaterial", experiment_device_material, namespace_collection, True)
            # Inverse direction: see create_series_device.
            set_property(experiment_device_material, "cpo:isBodyMaterialOf", device, namespace_collection, True)

    # Content from the library, one level lower (see create_series_device).
    for series_content_id in information_for_experimental_scope.get("series_library_content_ids", []):
        series_content = find_entity(datagraph, series_content_id)
        if series_content:
            experiment_content = create_experiment_material_from_series(
                series_content, experiment_number, namespace_collection, datagraph, todo_list, local_todo_list,
                material_type_id="cpo:MaterialVolume", context_label=f"Content of {name}", evidence_known_cache=evidence_known_cache,
                library=device_library, shared_forms=_with_cavities(device_forms, datagraph, device_library)
            )
            set_property(device, "cpo:containsMaterial", experiment_content, namespace_collection)
            set_property(experiment_content, "cpo:materialContainedIn", device, namespace_collection)

    ### -----------------------------------------------------------------------------------------
    ### Add to datagraph
    ### -----------------------------------------------------------------------------------------

    add_entity(datagraph, device)

    return device, local_todo_list


def create_deviceport(device: dict, scope: str, twin_device: dict, namespace_collection: dict, datagraph: dict, todo_list: list, device_library: dict, experiment_number: int = None, series_device: dict = None):

    # series_device is passed only for ExperimentSpecific devices - then we can link every
    # new port with its SeriesSpecific counterpart (the same position in cpo:hasPort, since
    # the series and the experiment device run through the same port list of twin_device).
    is_experiment = series_device is not None
    series_ports = series_device.get("cpo:hasPort", []) if series_device else []
    if isinstance(series_ports, dict):
        series_ports = [series_ports]

    if twin_device.get("cpo:hasPort"):
        ports = twin_device.get("cpo:hasPort", [])
        # With exactly one port the library holds a single {"@id": ...} instead of a list
        # (e.g. device:vessel001) - without this normalization enumerate() would iterate over
        # the dict KEYS (i.e. "@id" as the value of p), which leads to a broken ID such as
        # "#@id_SeriesSpecific".
        if isinstance(ports, dict):
            ports = [ports]

        for index, p in enumerate(ports):
            # If p is only a reference ({"@id": ...}), look up the full entity in the library to know
            # its role (inlet/outlet). If p is the full entity already, use it directly.

            if isinstance(p, str):
                port_ref_id = p
            else:
                port_ref_id = p.get("@id")

            library_port = find_entity(device_library, port_ref_id)

            if library_port is None:
                # If the reference is not found, or p was the full entity already
                library_port = p if isinstance(p, dict) else {}

            port_type = get_type(library_port)
            if port_type is None:
                port_type = check_type("cpo:DevicePort", namespace_collection)

            # Derive the ID from the library port (e.g. "port:sparger001_inlet" ->
            # "crate:<identifier>/sparger001_inlet_SeriesSpecific"), so that the origin is directly visible.
            port_id = generate_id_from_library_id(port_ref_id, scope, experiment_number)

            port = {
                "@id": port_id,
                "@type": [port_type, scope]
            }

            set_property(device, "cpo:hasPort", port, namespace_collection, True)
            set_property(port, "cpo:isPortOf", device, namespace_collection)

            # Link EXACTLY ONE level higher - on the series level the fixed library port, on the
            # experiment level only the SeriesSpecific counterpart, which in turn points at the library
            # port. That is the same pattern as for the device itself (see "Connection to the library
            # device" above): experiment -> series -> Fixed, one chain instead of two parallel edges.
            # A port with two values of hlo:specializationOf would not be found by get_series_entity,
            # and create_port_crossing_transfers would silently skip it on the experiment level.
            series_port = None
            if is_experiment and index < len(series_ports):
                series_port = find_entity(datagraph, series_ports[index]["@id"])

            if series_port is not None:
                set_property(port, "hlo:specializationOf", series_port, namespace_collection)
                set_property(series_port, "hlo:hasSpecialization", port, namespace_collection, True)
            else:
                # Series level - and as a fallback an experiment port whose series counterpart
                # exceptionally cannot be found: then rather the link to the library port than
                # none at all.
                set_property(port, "hlo:specializationOf", {"@id": port_ref_id}, namespace_collection)

            add_entity(datagraph, port)

    return device


def _expand_composite_devices(selected_twin_devices: list, device_library: dict) -> list:
    """Pull in the parts of composite devices automatically.

    Composite devices (cpo:isCompositeDevice = true) list their parts in the device
    library under dcterms:hasPart (a reactor -> vessel/jacket/stirrer/sparger, for
    example). Rather than making the user keep that in mind while counting and choosing
    devices, the parts are added here automatically - recursively, in case a part has
    parts of its own - in the order composite first, then parts.
    """
    expanded = []
    seen_ids = set()

    def add(twin_device):
        if twin_device["@id"] in seen_ids:
            return
        seen_ids.add(twin_device["@id"])
        expanded.append(twin_device)
        for part_ref in as_list(twin_device.get("dcterms:hasPart")):
            part_id = part_ref["@id"] if isinstance(part_ref, dict) else part_ref
            part_device = find_entity(device_library, part_id)
            if part_device:
                add(part_device)

    for twin_device in selected_twin_devices:
        add(twin_device)

    return expanded


def _link_composite_device_parts(all_twin_devices: list, series_devices_by_id: dict, experiment_devices_by_id: dict, number_experiments: int, namespace_collection: dict):
    """Set dcterms:hasPart/dcterms:isPartOf between a composite device and its parts
    (added automatically by _expand_composite_devices) - at series level and at every
    experiment level."""
    for twin_device in all_twin_devices:
        composite_id = twin_device["@id"]
        for part_ref in as_list(twin_device.get("dcterms:hasPart")):
            part_id = part_ref["@id"] if isinstance(part_ref, dict) else part_ref
            if part_id not in series_devices_by_id:
                continue

            composite_series = series_devices_by_id[composite_id]
            part_series = series_devices_by_id[part_id]
            set_property(composite_series, "dcterms:hasPart", part_series, namespace_collection, True)
            set_property(part_series, "dcterms:isPartOf", composite_series, namespace_collection)

            for e in range(number_experiments):
                nr = e + 1
                composite_experiment = experiment_devices_by_id[composite_id][nr]
                part_experiment = experiment_devices_by_id[part_id][nr]
                set_property(composite_experiment, "dcterms:hasPart", part_experiment, namespace_collection, True)
                set_property(part_experiment, "dcterms:isPartOf", composite_experiment, namespace_collection)


LOCATION_PROPERTIES = ("cpo:location", "cpo:locatedAt", "cpo:locatedInsideOf")


def _used_location_holder(twin_device: dict, series_devices_by_id: dict, device_library: dict):
    """Follow the location of a library device through the device library until a device that
    is used in this crate is reached. Returns (property, library id of that device, library id of
    the port it sits at or None), or None when the chain leaves the device library first - the
    device then stands in a room, and its location is set together with the environment (see
    environment_functions.py). A device can sit at a port of another (cpo:locatedAt, a cap on the
    opening of its bottle): then the holder is the device of that port."""
    current, seen = twin_device, set()
    while current is not None and current["@id"] not in seen:
        seen.add(current["@id"])
        for property_name in LOCATION_PROPERTIES:
            target_id = ref_id(current.get(property_name))
            if not target_id:
                continue
            port = find_entity(device_library, target_id)
            port_device_id = ref_id(port.get("cpo:isPortOf")) if port and port.get("cpo:isPortOf") else None
            if port_device_id and port_device_id in series_devices_by_id:
                # The device itself at the port: located at the port; a device it stands in: at the port's device.
                return (property_name, port_device_id, target_id) if current is twin_device else ("cpo:location", port_device_id, None)
            if port_device_id:
                # A port of a device that is not used here: on from that device.
                current = find_entity(device_library, port_device_id)
                break
            if target_id in series_devices_by_id:
                return property_name, target_id, None
            # A device of the library that does not occur in this crate: go on up to the one it
            # stands in itself (a stirrer in the vessel of a reactor that is not used).
            current = find_entity(device_library, target_id)
            break
        else:
            return None
    return None


def _port_copy(device: dict, library_port_id: str, datagraph: dict):
    """The port of a device of the crate that specializes the given port one level up (the library port for a
    series device, the series port for an experiment device), or None."""
    for port_ref in as_list(device.get("cpo:hasPort")):
        port = find_entity(datagraph, ref_id(port_ref))
        if port is not None and ref_id(port.get("hlo:specializationOf")) == library_port_id:
            return port
    return None


def _link_device_locations(all_twin_devices: list, series_devices_by_id: dict, experiment_devices_by_id: dict, number_experiments: int, namespace_collection: dict, device_library: dict, datagraph: dict):
    """Give every series and experiment device its own location, pointing at the device of the
    same level it sits in (the stirrer of the series in the vessel of the series) - the same
    property the library entry uses. Devices standing in a room get their location later,
    pointing at the ambient air of their level (create_all_environments)."""
    # Location per level (rule 7.1, Device_Space_R2): a structural link like definesForm, not a
    # concept. Read through the chain from the Fixed entry, an experiment of yesterday would see where
    # the device stands TODAY.
    for twin_device in all_twin_devices:
        holder = _used_location_holder(twin_device, series_devices_by_id, device_library)
        if holder is None:
            continue
        property_name, holder_id, port_id = holder
        if port_id is None:
            set_location(series_devices_by_id[twin_device["@id"]], property_name, series_devices_by_id[holder_id], namespace_collection)
            for e in range(number_experiments):
                nr = e + 1
                set_location(experiment_devices_by_id[twin_device["@id"]][nr], property_name, experiment_devices_by_id[holder_id][nr], namespace_collection)
            continue
        # At a port (a cap on the opening of its bottle): the port of the same level.
        series_port = _port_copy(series_devices_by_id[holder_id], port_id, datagraph)
        if series_port is None:
            raise ValueError(f"{twin_device['@id']} sits at {port_id}, which {holder_id} has no copy of in this crate.")
        set_location(series_devices_by_id[twin_device["@id"]], property_name, series_port, namespace_collection)
        for e in range(number_experiments):
            nr = e + 1
            experiment_port = _port_copy(experiment_devices_by_id[holder_id][nr], series_port["@id"], datagraph)
            if experiment_port is None:
                raise ValueError(f"{twin_device['@id']} sits at {port_id}, which has no copy in experiment {nr}.")
            set_location(experiment_devices_by_id[twin_device["@id"]][nr], property_name, experiment_port, namespace_collection)


# Template and exemplar (rule 3.11): a library device can specialize another Fixed device -
# bottle no. 13 the template "glass bottle 250 mL". The exemplar takes over from the template
# what it does not say itself (form, body, ports, flags); what only the exemplar can say never
# comes from the template: its history, its location, its content and its times.
_EXEMPLAR_ONLY = {
    "@id", "@type", "hlo:specializationOf", "hlo:hasSpecialization", "schema:name", "rdfs:comment",
    "cpo:hasUsageHistory", "cpo:lastUsedTime", "cpo:lastUsedPurpose", "cpo:hasCalibrationHistory",
    "cpo:lastCalibratedTime", "cpo:hasServiceHistory", "cpo:lastServicedTime",
    "cpo:location", "cpo:locatedAt", "cpo:locatedInsideOf",
    "cpo:containsMaterial", "cpo:hasContainedMaterialHistory", "cpo:hasDeliveryTime", "cpo:hasOpeningTime",
}


# Where the start of an experiment stands in the answer file (measured value or assumption) - the
# same keys under which the tasks ask for it later (creation/task_functions.py).
_START_KEYS = ("series:1/experiment:{nr}/task:procedure/start_time/evidence_timestamp",
               "series:1/experiment:{nr}/task:procedure/start_time/reference_timestamp")


def _experiment_starts(datagraph: dict) -> list:
    """The starts of the experiments as far as they are known before they are asked - read ahead from
    the answer file or the sheet (helpers/user_io.py: known_answer). The devices are made before the
    tasks, whose times these are."""
    from datetime import datetime, timezone
    number = len(find_entities_by_type(datagraph, "cpo:SingleExperiment", None))
    starts = []
    for nr in range(1, number + 1):
        for key in _START_KEYS:
            raw = known_answer(key.format(nr=nr))
            if not raw:
                continue
            try:
                moment = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                continue
            starts.append(moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc))
            break
    return starts


def _there_at(content: dict, moment, datagraph: dict, device_library: dict) -> bool:
    """Whether a library content was in its device at that moment: its receipt began before and it
    had not ended before (rule 7.17). An end whose moment is not known counts as not ended."""
    from creation.device_usage_functions import _Moments
    from helpers.inventory_state import occurrence_of_content, content_end
    occurrence = occurrence_of_content(content["@id"], device_library)
    if occurrence is None:
        return False
    moments = _Moments(datagraph, device_library)
    since = moments.value(ref_id(occurrence.get("cpo:hasStartTime")))
    end = content_end(occurrence)
    until = moments.value(end) if end else None
    return since is not None and since <= moment and (until is None or until > moment)


def _library_contents(twin_device: dict, device_library: dict, name: str, datagraph: dict) -> list:
    """The content a device of the library brings along (rules 3.10, 2.15): the one content of its
    history - also when it has been used up since, so that an older crate can be built again -, or,
    when the device has held several one after the other, the one that was in it when the first
    experiment started (rule 2.15). Only if that start is not known yet, or no content
    or more than one fits, the series is asked. record_device_usage checks the choice against the
    start of every experiment."""
    contents = [content for content in (fixed_library_material(content_id, device_library)
                                        for content_id in content_history(twin_device)) if content]
    if len(contents) <= 1:
        return contents
    starts = _experiment_starts(datagraph)
    if starts:
        fitting = [c for c in contents if _there_at(c, min(starts), datagraph, device_library)]
        if len(fitting) == 1:
            print(f"[content] {name}: {fitting[0]['@id']} - the content it held when the first experiment started "
                  f"({min(starts).isoformat()}).")
            return fitting
        print(f"[content] {name}: {len(fitting)} of its {len(contents)} contents were in it when the first experiment "
              f"started ({min(starts).isoformat()}) - asking.")
    described = "; ".join(f"{c['@id']} ({c.get('schema:name', '')}"
                          + (f", lot {c['cpo:hasLotNumber']}" if c.get("cpo:hasLotNumber") else "") + ")"
                          for c in contents)
    chosen = ask_user(f"[hlo:SeriesSpecific] {name} has held {len(contents)} contents, one after the other: {described}. "
                      f"Which one did this series draw from? (The run checks that it was there when each experiment started.)",
                      [c["@id"] for c in contents], question_id="library_content")
    return [c for c in contents if c["@id"] == chosen]


def library_template(library_device: dict, device_library: dict):
    """The Fixed device a library device specializes (its template), or None - the case of
    every device that is not an exemplar."""
    parent = find_entity(device_library, ref_id(library_device.get("hlo:specializationOf")))
    return parent if parent is not None and "hlo:Fixed" in as_list(parent.get("@type")) else None


def resolve_exemplar(library_device: dict, device_library: dict) -> dict:
    """The library device as the generator copies it: for an exemplar its own statements over
    those of its template (see _EXEMPLAR_ONLY); for any other device the entry itself."""
    template = library_template(library_device, device_library)
    if template is None:
        return library_device
    view = {k: v for k, v in resolve_exemplar(template, device_library).items() if k not in _EXEMPLAR_ONLY}
    view.update(library_device)
    return view


def create_all_devices(datagraph: dict, device_library: dict, namespace_collection: dict, todo_list: dict, number_experiments: int):
    # First choose all devices named by the user ... - a level of its own, "device_selection",
    # NOT "device": the index counted here (1..number_devices) does not match the index in the
    # later create_series_device/create_experiment_device loop below (which runs over
    # all_twin_devices INCLUDING composite parts added automatically, see
    # _expand_composite_devices) - the same number would mean another device in the two places.
    # As one list of library entries instead of a count + "which is number i?": every device then
    # stands under "device:<library entry>".
    # A template without cpo:isSingleUse (the glass bottle 250 mL) is never used itself, but through
    # its exemplars - it is not offered (rule 3.11). Single-use templates (vial,
    # syringe) are: every use is a fresh piece straight from them.
    library_devices = [e["@id"].removeprefix("device:") for e in find_entities_by_type(device_library, "cpo:Device", namespace_collection, include_subclasses=True)
                       if e.get("@id", "").startswith("device:")
                       and ("hlo:Template" not in as_list(e.get("@type")) or e.get("cpo:isSingleUse") is True)]
    chosen = ask_user_list(
        "Which devices from the Device Library were used? (Composite devices, e.g. a Reactor, automatically bring their parts "
        "like Vessel/Jacket/Stirrer along - do not name those separately)",
        library_devices, question_id="devices", required=True
    )
    selected_twin_devices = [find_entity(device_library, f"device:{name}") for name in chosen]

    # ... and then add the components of composite devices automatically.
    all_twin_devices = _expand_composite_devices(selected_twin_devices, device_library)

    series_devices_by_id = {}
    experiment_devices_by_id = {}

    # Lives for the whole run: remembers per (series device, property) the "do we know this for
    # the single experiments" shortcut of add_phase_process_variable/PowerInput/EnergyField
    # (see helpers/process_variables.py) - analogous to phase_functions.py/
    # material_functions.py.
    evidence_known_cache = {}

    for i, library_device in enumerate(all_twin_devices):
        # An exemplar is copied with the parts of its template, the copies are named after it
        # (helpers/identifiers.py: library_name_alias). For every other device nothing changes.
        template = library_template(library_device, device_library)
        twin_device = resolve_exemplar(library_device, device_library)
        alias = library_name_alias(template["@id"], library_device["@id"]) if template else nullcontext()
        with question_path("device", key_name(twin_device["@id"])), alias:

            series_device, twin_device, todo_list_from_series_device, information_for_experimental_scope = create_series_device(datagraph, device_library, i+1, namespace_collection, todo_list, twin_device, evidence_known_cache)

            # create_series_device collects what differs between series and experiments
            # (information_for_experimental_scope); create_experiment_device builds on it.
            series_devices_by_id[twin_device["@id"]] = series_device
            todo_list = merge_todo_lists(todo_list, todo_list_from_series_device)

            # Now the ExperimentSpecific devices
            experiment_devices_by_id[twin_device["@id"]] = {}
            for e in range(number_experiments):
                with question_path("experiment", e + 1):
                    experiment_device, todo_list_from_experiment_device = create_experiment_device(datagraph, device_library, i+1, namespace_collection, todo_list, e+1, series_device, twin_device, information_for_experimental_scope, evidence_known_cache)
                    todo_list = merge_todo_lists(todo_list, todo_list_from_experiment_device)
                    experiment_devices_by_id[twin_device["@id"]][e+1] = experiment_device

    _link_composite_device_parts(all_twin_devices, series_devices_by_id, experiment_devices_by_id, number_experiments, namespace_collection)
    _link_device_locations(all_twin_devices, series_devices_by_id, experiment_devices_by_id, number_experiments, namespace_collection, device_library, datagraph)

    return todo_list