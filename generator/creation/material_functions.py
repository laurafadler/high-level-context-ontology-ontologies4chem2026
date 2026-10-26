"""
The materials of a series and its experiments (cpo:Stream, cpo:MaterialVolume) and the placeholders of
their phases.

Three ways a material comes about: from a library entry (a body material, the room air, the content of a
container - create_series_material_from_fixed and its experiment counterpart), from the to-do list (the
content a device was given in device_functions.py), or from the list of additional materials asked in
create_all_materials. Each gets its phases (as placeholders on the to-do list, completed in
phase_functions.py), its form (it fills the cavity of its device, or defines an IndeterminateForm), the
ports of a stream and its quantities (volume or flow rate, temperature and pressure of the material as a
whole).
"""

from helpers.entities import add_entity, ask_entity_choice, ask_entity_list, find_entities_by_type, find_entity, resolve, is_library_entity, ref_id, ref_ids, as_list
from helpers.properties import set_property, check_type, get_type
from helpers.identifiers import (generate_id_from_name, generate_name, get_display_label, short_local_name,
                                 make_root_id, make_library_based_id, make_specialization_id, make_owned_id,
                                 claim_id, key_name, name_list, aliased_name)
from helpers.todo_functions import add_todo_item, find_todo_items_by_type, delete_todo_entity
from helpers.process_variables import add_phase_process_variable
from helpers.forms import own_forms, form_ref
from helpers.volume_checks import check_material_volume_against_device
from helpers.user_io import ask_user, question_path


# ---------------------------------------------------------------------------
# Derive a material from a Fixed library entity (environment of a room, body
# material of a device, ...) - Fixed (MaterialVolume with phase(s)+species, lives
# in some library, e.g. organization_library/device_library) -> SeriesSpecific ->
# ExperimentSpecific, structurally identical to the usual Fixed/Series/Experiment
# pattern of the project. Callers add their own link afterwards (e.g.
# cpo:locatedInsideOf for an environment, cpo:madeOfMaterial for the body material
# of a device) - see environment_functions.py/device_functions.py.
# ---------------------------------------------------------------------------

def fixed_library_material(fixed_id: str, library: dict):
    """The fixed MaterialVolume entry of a library (a device's body material, a room's air).
    It stays in the library: the crate links to it (hlo:specializationOf), and its phases,
    species and values are read through helpers/entities.py: resolve."""
    return find_entity(library, fixed_id)


def create_series_material_from_fixed(fixed_material: dict, namespace_collection: dict, datagraph: dict, todo_list: list, local_todo_list: list, material_type_id: str = "cpo:MaterialVolume", context_label: str = "Material", evidence_known_cache: dict = None, stable_index_level: str = "material", library: dict = None, shared_forms: dict = None):
    """The series-specific counterpart of a fixed material entity - name, phases and
    species carried over structurally, the remaining properties through the ordinary
    fill_material_properties.

    Used both for environments (creation/environment_functions.py) and for device body
    materials (creation/device_functions.py, cpo:madeOfMaterial).

    stable_index_level names the level of this entity in the question path. A device body
    material stays with the default "material" - structurally it really is a material, the
    glass of a reactor for instance - while an environment uses "environment"
    (environment_functions.py passes that explicitly): a room is NOT a material, and the two
    should not share a namespace in the question path.
    """
    material_type = check_type(material_type_id, namespace_collection)
    # Named after the library entry it specializes ("material:vessel001_Body" ->
    # ".../vessel001_Body_SeriesSpecific"), not after a counter.
    entity_id = claim_id(make_library_based_id(fixed_material["@id"], "hlo:SeriesSpecific"),
                             datagraph, todo_list, local_todo_list, what=f"The {context_label.lower()} from {fixed_material['@id']}")
    material = {"@id": entity_id, "@type": [material_type, "hlo:SeriesSpecific"]}

    # The body of an exemplar is named after it, as its ID is (aliased_name).
    material_name = aliased_name(fixed_material.get("schema:name")) or generate_name(entity_id)
    set_property(material, "schema:name", material_name, namespace_collection)

    print(f"\n=== Now describing {context_label} \"{material_name}\" ({entity_id}, hlo:SeriesSpecific) ===")

    set_property(material, "hlo:specializationOf", fixed_material, namespace_collection)
    # No inverse direction at the library entry: the library is not changed (rule 2.2).
    if not is_library_entity(fixed_material):
        set_property(fixed_material, "hlo:hasSpecialization", material, namespace_collection, True)

    with question_path(stable_index_level, key_name(entity_id)):
        # Forms of its own on this level (helpers/forms.py) - for a device body those of its device
        # (shared_forms), for everything else, such as the room air, a copy of its own whose
        # dimensions are offered in the list of the material (rule 4.2). Hence in the question path of the material.
        own_forms(material, fixed_material, "hlo:SeriesSpecific", 1, namespace_collection, datagraph, library, shared_forms, offer={"todo_list": todo_list, "local_todo_list": local_todo_list,
                                       "evidence_known_cache": evidence_known_cache})

        fixed_phase_ids = ref_ids(fixed_material.get("dcterms:hasPart"))
        add_experiment_phases_from_series(material, fixed_phase_ids, "hlo:SeriesSpecific", 1, namespace_collection, datagraph, todo_list, local_todo_list)

        fill_material_properties(material, "MaterialVolume", "hlo:SeriesSpecific", 1, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache=evidence_known_cache)

    add_entity(datagraph, material)
    return material


def create_experiment_material_from_series(series_material: dict, nr: int, namespace_collection: dict, datagraph: dict, todo_list: list, local_todo_list: list, material_type_id: str = "cpo:MaterialVolume", context_label: str = "Material", evidence_known_cache: dict = None, stable_index_level: str = "material", library: dict = None, shared_forms: dict = None):
    """Like create_series_material_from_fixed, one level further down (series ->
    experiment). For stable_index_level see there."""
    material_type = check_type(material_type_id, namespace_collection)
    entity_id = claim_id(make_specialization_id(series_material["@id"], nr),
                             datagraph, todo_list, local_todo_list)
    material = {"@id": entity_id, "@type": [material_type, "hlo:ExperimentSpecific"]}

    material_name = series_material.get("schema:name") or generate_name(entity_id)
    set_property(material, "schema:name", material_name, namespace_collection)

    print(f"\n=== Now describing {context_label} \"{material_name}\" ({entity_id}, hlo:ExperimentSpecific, Experiment {nr}) ===")

    set_property(material, "hlo:specializationOf", series_material, namespace_collection)
    set_property(series_material, "hlo:hasSpecialization", material, namespace_collection, True)

    # The same key as the SeriesSpecific counterpart: key_name is the same on both levels.
    with question_path(stable_index_level, key_name(entity_id)):
        own_forms(material, series_material, "hlo:ExperimentSpecific", nr, namespace_collection, datagraph, library, shared_forms, offer={"todo_list": todo_list, "local_todo_list": local_todo_list,
                                       "evidence_known_cache": evidence_known_cache})
        series_phase_ids = ref_ids(series_material.get("dcterms:hasPart"))
        add_experiment_phases_from_series(material, series_phase_ids, "hlo:ExperimentSpecific", nr, namespace_collection, datagraph, todo_list, local_todo_list)

        fill_material_properties(material, "MaterialVolume", "hlo:ExperimentSpecific", nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache=evidence_known_cache)

    add_entity(datagraph, material)
    return material


# ---------------------------------------------------------------------------
# Phases (minimal, written directly onto the to-do list)
# ---------------------------------------------------------------------------

# The state of matter is modelled directly as a phase subclass (not as a property of its own) -
# these classes are subclasses of cpo:Phase in the ontology.
STATE_OF_MATTER_TO_PHASE_CLASS = {
    "Solid": "cpo:SolidPhase",
    "Liquid": "cpo:LiquidPhase",
    "Gaseous": "cpo:GasPhase",
}
PHASE_STATE_CLASSES = tuple(STATE_OF_MATTER_TO_PHASE_CLASS.values())


def get_phase_state_class(phase: dict):
    """Return a phase's state-of-matter subclass (SolidPhase/LiquidPhase/GasPhase), if
    it has one."""
    types = as_list(phase.get("@type"))
    for entity_type in types:
        if entity_type in PHASE_STATE_CLASSES:
            return entity_type
    return None


def ask_name(scope: str, context_hint: str, *, question_id: str = "name") -> str:
    """Ask for the name of a newly created entity whose ID is built from it (rule 1.1).

    Mandatory: the name IS the entity's key - in its ID (helpers/identifiers.py:
    make_root_id) and in the question path. An automatic name would have to be made up from
    something else, and the only thing there is would be a running number.
    """
    return ask_user(f"[{scope}] What would you like to name this {context_hint}?", question_id=question_id, required=True).strip()


def ask_optional_name(scope: str, context_hint: str, default_id: str, *, question_id: str = "name") -> str:
    """Optionally ask for a name for a newly created entity. Leaving it empty takes a name
    generated automatically from the ID, as for devices (see generate_name).

    context_hint briefly says which entity this is about ("Liquid phase of Reactor Feed",
    for example), so that the question is unambiguous even before a name exists.

    question_id defaults to "name", since every caller asks exactly once per already unique
    question path (material, phase, reaction, task, ...). Only where that does not hold can
    a caller pass a different question_id explicitly.
    """
    custom_name = ask_user(f"[{scope}] What would you like to name this {context_hint}? (leave empty for an automatic name)", question_id=question_id)
    return custom_name.strip() if custom_name.strip() else generate_name(default_id)


def create_phase_placeholder(material: dict, scope: str, state_class: str, nr: int, namespace_collection: dict, datagraph: dict, todo_list: list, local_todo_list: list, phase_name: str):
    """Create a minimal phase entity whose state of matter is set directly as its @type
    (cpo:LiquidPhase rather than cpo:Phase - that is enough, since
    LiquidPhase/SolidPhase/GasPhase are already subclasses of cpo:Phase) and put it onto the
    todo list.

    The remaining properties of the phase are added later, while the todo list is worked
    through.
    """
    check_type(state_class, namespace_collection)
    experiment_number = nr if scope == "hlo:ExperimentSpecific" else None

    # The ID is made from the name that came with the list of phases already (add_phases).
    phase_id = claim_id(make_root_id("Phase", phase_name, scope, experiment_number),
                            datagraph, todo_list, local_todo_list, what=f"The phase '{phase_name}'")

    phase = {
        "@id": phase_id,
        "@type": [state_class, scope]
    }
    set_property(phase, "schema:name", phase_name, namespace_collection)

    set_property(phase, "dcterms:isPartOf", material, namespace_collection)
    set_property(material, "dcterms:hasPart", phase, namespace_collection, True)

    add_todo_item(local_todo_list, phase)
    return phase


def add_phases(material: dict, scope: str, nr: int, namespace_collection: dict, datagraph: dict, todo_list: list, local_todo_list: list) -> list:
    """Ask, for each state of matter separately, which phases of that state the material
    consists of - by name, as a list (helpers/identifiers.py: name_list). The number of
    phases is the length of the list; each name becomes the phase's ID and its key in the
    question path (rule 1.4): a count and then each name in turn would put a running number into
    the path, and a phase inserted in the middle would inherit its neighbour's answers.
    """
    phase_ids = []
    label = get_display_label(material)
    for state_label, state_class in STATE_OF_MATTER_TO_PHASE_CLASS.items():
        names = ask_user(
            f"[{scope}] Which {state_label} phases does {label} consist of? Their names, separated by ';' (leave empty if none)",
            answer_type=name_list, question_id=f"{state_label.lower()}_phase_names"
        )
        for phase_name in names:
            phase = create_phase_placeholder(material, scope, state_class, nr, namespace_collection, datagraph, todo_list, local_todo_list, phase_name)
            phase_ids.append(phase["@id"])

    return phase_ids


def _find_fixed_ancestor_name(entity: dict, datagraph: dict, todo_list: list, local_todo_list: list, max_hops: int = 5):
    """Walk up the hlo:specializationOf chain, however many levels deep it goes (fixed ->
    series -> experiment, for example), and return the unchanged schema:name of the first
    hlo:Fixed entity found along the way - or None when the chain does not lead to a fixed
    entity.

    max_hops bounds the search, in case specializationOf should form a cycle for whatever
    reason.
    """
    current = entity
    for _ in range(max_hops):
        if current is None:
            return None
        if "hlo:Fixed" in as_list(current.get("@type")):
            return current.get("schema:name")
        parent_ref = current.get("hlo:specializationOf")
        parent_id = parent_ref.get("@id") if isinstance(parent_ref, dict) else parent_ref
        if not parent_id:
            return None
        current = (
            resolve(datagraph, parent_id)
            or find_entity(todo_list, parent_id)
            or find_entity(local_todo_list, parent_id)
        )
    return None


def add_experiment_phases_from_series(material: dict, series_phase_ids: list, scope: str, nr: int, namespace_collection: dict, datagraph: dict, todo_list: list, local_todo_list: list):
    for series_phase_id in series_phase_ids:
        # Series phases land only in local_todo_list (see create_phase_placeholder) and are
        # merged into todo_list only at the very end of create_all_materials - when the
        # experiment phases are processed (still in the same run) it must be searched there too,
        # otherwise series_phase is always None and specializationOf/hasSpecialization is never set.
        series_phase = (
            resolve(datagraph, series_phase_id)
            or find_entity(todo_list, series_phase_id)
            or find_entity(local_todo_list, series_phase_id)
        )

        # Take over the state of matter from the series counterpart instead of asking again -
        # it should always be there, since series_phase itself was created via
        # create_phase_placeholder and always gets a state class there.
        state_class = get_phase_state_class(series_phase) if series_phase else None
        phase_type = state_class or check_type("cpo:Phase", namespace_collection)
        experiment_number = nr if scope == "hlo:ExperimentSpecific" else None
        # The phase is named after what it specializes: a Fixed phase from the library after
        # its library entry, a series phase after its local name.
        if series_phase is None:
            raise ValueError(f"Phase {series_phase_id} to be specialized for {material['@id']} was not found.")
        if scope == "hlo:ExperimentSpecific" and "hlo:SeriesSpecific" in series_phase.get("@type", []):
            new_id = make_specialization_id(series_phase_id, nr)
        else:
            new_id = make_library_based_id(series_phase_id, scope, experiment_number)
        phase_id = claim_id(new_id, datagraph, todo_list, local_todo_list)

        phase = {
            "@id": phase_id,
            "@type": [phase_type, scope]
        }

        # Take over the name structurally instead of asking again (like the state of matter) -
        # only if the parent (Fixed or series, depending on the caller) has no name at all is one
        # generated from the ID. If the specializationOf chain (however many levels deep) leads to
        # a real Fixed entity (e.g. "vessel001 Body", see device_library.jsonld), its unchanged
        # name is taken and the current scope appended (as for library-based devices/ports, see
        # generate_id_from_library_id) - otherwise the phase would not show that it is only a
        # specialization, instead of being the Fixed phase itself. Important: take the ORIGINAL
        # name of the Fixed entity for that (_find_fixed_ancestor_name), not the name of the
        # series phase that already has "SeriesSpecific" - otherwise Series -> Experiment would
        # append a second suffix instead of replacing it. If the name comes instead from a normal
        # (not Fixed-derived) SeriesSpecific phase of a freely named material, it stays
        # unchanged - that is already the display name chosen by the user there.
        fixed_name = _find_fixed_ancestor_name(series_phase, datagraph, todo_list, local_todo_list) if series_phase else None
        # The phase of an exemplar's body is named after the exemplar, not the template.
        fixed_name = aliased_name(fixed_name)
        if fixed_name:
            scope_suffix = f"ExperimentSpecific {nr}" if scope == "hlo:ExperimentSpecific" else "SeriesSpecific"
            phase_name = f"{fixed_name} {scope_suffix}"
        else:
            phase_name = (series_phase.get("schema:name") if series_phase else None) or generate_name(phase_id)
        set_property(phase, "schema:name", phase_name, namespace_collection)

        set_property(phase, "dcterms:isPartOf", material, namespace_collection)
        set_property(material, "dcterms:hasPart", phase, namespace_collection, True)

        if series_phase:
            set_property(phase, "hlo:specializationOf", series_phase, namespace_collection)
            # Inverse direction only at an entity of the crate - the library is not changed (rule 2.2).
            if not is_library_entity(series_phase):
                set_property(series_phase, "hlo:hasSpecialization", phase, namespace_collection, True)

        add_todo_item(local_todo_list, phase)


def add_experiment_ports_from_series(material: dict, series_material: dict, nr: int, namespace_collection: dict, datagraph: dict, todo_list: list):
    """For an experiment-specific stream that specializes a series stream, carry over its
    flowsFrom/flowsTo automatically (see get_experiment_port) instead of asking the user for
    the port again.
    """
    for prop, is_source in [("cpo:flowsFrom", True), ("cpo:flowsTo", False)]:
        if prop in material or prop not in series_material:
            continue

        series_port_ref = series_material[prop]
        series_port_id = series_port_ref.get("@id") if isinstance(series_port_ref, dict) else series_port_ref
        series_port = find_entity(datagraph, series_port_id)
        if not series_port:
            continue

        experiment_port = get_experiment_port(series_port, is_source, material, nr, namespace_collection, datagraph, todo_list)
        if experiment_port:
            set_property(material, prop, experiment_port, namespace_collection)

def get_device_experiment_number(device: dict, datagraph: dict):
    """Work out which experiment an experiment-specific device belongs to.

    There is no property for this. Instead it relies on hlo:hasSpecialization on the series
    device always being filled in experiment order (1, 2, 3, ...; see create_all_devices), so
    the device's position in that list, plus one, is its experiment number.

    Returns None when this cannot be determined.
    """
    series_ref = device.get("hlo:specializationOf")
    series_id = series_ref.get("@id") if isinstance(series_ref, dict) else series_ref
    series_device = find_entity(datagraph, series_id) if series_id else None
    if not series_device:
        return None

    specializations = series_device.get("hlo:hasSpecialization", [])
    if isinstance(specializations, dict):
        specializations = [specializations]

    for index, spec in enumerate(specializations):
        if spec.get("@id") == device.get("@id"):
            return index + 1

    return None


def port_matches_experiment(port: dict, scope: str, nr: int, datagraph: dict) -> bool:
    """At experiment scope, only a port from the same experiment (nr) may appear as a
    candidate - otherwise a port from experiment 1 could be picked by mistake for a stream
    from experiment 2.
    """
    if scope != "hlo:ExperimentSpecific":
        return True

    device_ref = port.get("cpo:isPortOf")
    device_id = device_ref.get("@id") if isinstance(device_ref, dict) else device_ref
    device = find_entity(datagraph, device_id) if device_id else None
    if not device:
        return True

    return get_device_experiment_number(device, datagraph) == nr


def ask_for_port(question: str, device_port_type: str, boundary_type: str, stream: dict, is_source: bool, scope: str, nr: int, namespace_collection: dict, datagraph: dict, todo_list: list, *, question_id: str):

    candidates = [
        c for c in find_entities_by_type(datagraph, device_port_type, namespace_collection, include_subclasses=True)
        if scope in c.get("@type", []) and port_matches_experiment(c, scope, nr, datagraph)
    ]

    candidate_ids = [c["@id"] for c in candidates]
    boundary_label = "New Source outside of the system" if is_source else "New Sink outside of the system"
    options = candidate_ids + [boundary_label]

    chosen = ask_user(question, options, question_id=question_id)

    if chosen == boundary_label:
        return create_boundary_port(boundary_type, stream, is_source, scope, nr, namespace_collection, datagraph, todo_list)

    return {"@id": chosen}


def get_experiment_port(series_port: dict, is_source: bool, stream: dict, nr: int, namespace_collection: dict, datagraph: dict, todo_list: list):
    """Automatically take the port matching a series port for experiment nr, without asking
    the user again:

    - When the series port belongs to a device, the port at the same position in that
      device's experiment counterpart is used (the order in cpo:hasPort is identical for the
      series and the experiment device, see create_deviceport).
    - When the series port lies outside a device (a source or sink), a new boundary port
      entity is created for this experiment.

    Returns None when no counterpart can be found, in which case the question is asked as
    usual.
    """
    device_ref = series_port.get("cpo:isPortOf")

    if device_ref is None:
        boundary_type = "cpo:Source" if is_source else "cpo:Sink"
        return create_boundary_port(boundary_type, stream, is_source, "hlo:ExperimentSpecific", nr, namespace_collection, datagraph, todo_list)

    device_id = device_ref.get("@id") if isinstance(device_ref, dict) else device_ref
    series_device = find_entity(datagraph, device_id)
    if series_device is None:
        return None

    series_ports = series_device.get("cpo:hasPort", [])
    if isinstance(series_ports, dict):
        series_ports = [series_ports]
    port_index = next((i for i, p in enumerate(series_ports) if p.get("@id") == series_port["@id"]), None)
    if port_index is None:
        return None

    experiment_devices = series_device.get("hlo:hasSpecialization", [])
    if isinstance(experiment_devices, dict):
        experiment_devices = [experiment_devices]
    if nr > len(experiment_devices):
        return None

    experiment_device = find_entity(datagraph, experiment_devices[nr - 1]["@id"])
    if experiment_device is None:
        return None

    experiment_ports = experiment_device.get("cpo:hasPort", [])
    if isinstance(experiment_ports, dict):
        experiment_ports = [experiment_ports]
    if port_index >= len(experiment_ports):
        return None

    return {"@id": experiment_ports[port_index]["@id"]}





def create_boundary_port(role_type: str, stream: dict, is_source: bool, scope: str, nr: int, namespace_collection: dict, datagraph: dict, todo_list: list):
    """Create a new source or sink entity for a stream that enters (source) or leaves
    (sink) the system under study.

    These ports belong to no device and are created afresh per stream. The inverse link
    (hasOutgoingStream/hasIngoingStream) is set centrally in fill_material_properties
    through link_stream_to_port().
    """
    port_type = check_type(role_type, namespace_collection)
    experiment_number = nr if scope == "hlo:ExperimentSpecific" else None
    # Source or sink of THIS stream (helpers/identifiers.py) - the stream has one of each.
    port_id = claim_id(make_owned_id(role_type.split(":", 1)[-1], stream["@id"]),
                           datagraph, todo_list)

    port = {
        "@id": port_id,
        "@type": [port_type, scope]
    }

    add_entity(datagraph, port)
    return port


def link_stream_to_port(material: dict, port_ref, is_source: bool, namespace_collection: dict, datagraph: dict, todo_list: list):
    """Set the property inverse to cpo:flowsFrom/cpo:flowsTo on the port:
    cpo:hasOutgoingStream when the port is the source (flowsFrom), cpo:hasIngoingStream when
    it is the destination (flowsTo).

    Works for newly created boundary ports just as for existing device ports or ports carried
    over automatically from the series counterpart.
    """
    port_id = port_ref.get("@id") if isinstance(port_ref, dict) else port_ref
    port = find_entity(datagraph, port_id) or find_entity(todo_list, port_id)
    if port is None:
        return

    prop = "cpo:hasOutgoingStream" if is_source else "cpo:hasIngoingStream"
    set_property(port, prop, material, namespace_collection, True)



# ---------------------------------------------------------------------------
# Common properties of Stream and MaterialVolume
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# sosa:isSampleOf - a material that stands in for another
# ---------------------------------------------------------------------------



def _specialization_for_experiment(entity: dict, nr: int, datagraph: dict):
    """The experiment version of a series entity, via hlo:hasSpecialization."""
    for ref in ref_ids(entity.get("hlo:hasSpecialization")):
        if ref.endswith(f"_ExperimentSpecific_{nr}"):
            found = find_entity(datagraph, ref)
            if found is not None:
                return found
    return None


def link_experiment_samples(nr: int, namespace_collection: dict, datagraph: dict):
    """sosa:isSampleOf at experiment level: every experiment material whose series template
    is a sample points at the experiment counterpart of what the template stands for - as
    _remap_used_equipment does for devices on tasks.

    Runs once all materials of the experiment exist: a sample created before the material it
    stands for would otherwise find no counterpart yet and lose the link.
    """
    scope = "hlo:ExperimentSpecific"
    for material in list(datagraph.get("@graph", [])):
        if scope not in (material.get("@type") or []) or not material["@id"].endswith(f"_ExperimentSpecific_{nr}"):
            continue
        series_material = find_entity(datagraph, (material.get("hlo:specializationOf") or {}).get("@id", ""))             if isinstance(material.get("hlo:specializationOf"), dict) else None
        series_target_id = ref_ids((series_material or {}).get("sosa:isSampleOf"))
        if not series_target_id:
            continue
        series_target = find_entity(datagraph, series_target_id[0])
        target = _specialization_for_experiment(series_target, nr, datagraph) if series_target else None
        if target is None:
            print(f"[{scope}] {get_display_label(material)} is a sample, but the material it stands for has no counterpart in experiment {nr} - skipping.")
            continue
        set_property(material, "sosa:isSampleOf", target, namespace_collection)
        set_property(target, "sosa:hasSample", material, namespace_collection, True)


def ask_sample_materials(namespace_collection: dict, datagraph: dict):
    """sosa:isSampleOf at series level: which materials stand in for another one - asked
    ONCE, when every series material exists, as a list.

    Asked per material while creating it, the first one created would never be asked, and
    which one that is would depend on the order of the device list. Only cpo:MaterialVolumes
    take part: a stream is a flow and a body material the wall of a device, neither stands in
    for anything.
    """
    scope = "hlo:SeriesSpecific"
    candidates = [
        entity for entity in datagraph.get("@graph", [])
        if "cpo:MaterialVolume" in (entity.get("@type") or [])
        and scope in (entity.get("@type") or [])
        and "cpo:BodyMaterial" not in (entity.get("@type") or [])
    ]
    if len(candidates) < 2:
        return
    sample_ids = ask_entity_list(
        f"[{scope}] Which of these materials are samples taken from another material, and stand in for it? Separated by ';' (leave empty if none)",
        candidates, question_id="sample_materials"
    )
    for sample_id in sample_ids:
        sample = find_entity(datagraph, sample_id)
        level = "environment" if "cpo:Environment" in (sample.get("@type") or []) else "material"
        with question_path(level, key_name(sample_id)):
            target_id = ask_entity_choice(
                f"[{scope}] Which material is {get_display_label(sample)} a sample of?",
                [c for c in candidates if c["@id"] != sample_id], label_fn=get_display_label, question_id="is_sample_of"
            )
        target = find_entity(datagraph, target_id)
        set_property(sample, "sosa:isSampleOf", target, namespace_collection)
        set_property(target, "sosa:hasSample", sample, namespace_collection, True)


def _counterpart_has_own_volume(material: dict, datagraph: dict) -> bool:
    """Whether the counterpart one level up (the library entry for a series material) has a
    volume that none of its phases shares - a body of several layers. A body of one phase shares
    its volume with that phase and gets it through the phase (_share_material_volume)."""
    from helpers.process_variables import get_series_entity
    counterpart = get_series_entity(material, datagraph)
    if counterpart is None or not counterpart.get("cpo:hasVolume"):
        return False
    volume_id = ref_id(counterpart.get("cpo:hasVolume"))
    for phase_id in ref_ids(counterpart.get("dcterms:hasPart")):
        phase = resolve(datagraph, phase_id)
        if phase is not None and ref_id(phase.get("cpo:hasVolume")) == volume_id:
            return False
    return True


def fill_material_properties(material: dict, material_type: str, scope: str, nr: int, namespace_collection: dict, datagraph: dict, todo_list: list, local_todo_list: list, info: dict = None, evidence_known_cache: dict = None, device_library: dict = None):
    """Asks/adds all properties that are relevant to Stream and MaterialVolume in common or
    specifically. material_type is "Stream" or "MaterialVolume" (without prefix)."""
    if info is None:
        info = {}

    # Phases -----------------------------------------------------------------------------------
    if "dcterms:hasPart" not in material:
        phase_ids = add_phases(material, scope, nr, namespace_collection, datagraph, todo_list, local_todo_list)
        info["series_phase_ids"] = phase_ids

    # Form ------------------------------------------------------------------------------------
    # A material in a device takes up its cavity: it shares the cavity form that hangs at the
    # form of the device on THE SAME level (cpo:definesForm / cpo:hasCavityForm, created in
    # helpers/forms.py) - no new survey, the same entity, as the body shares the form of its
    # device. For the jacket that is the annular gap between the shells, for the vessel the
    # cylinder inside. If the form has no cavity (a solid body), it stays with the form of the
    # device.
    # Materials without a device (streams between devices, room air, ...) get nothing here,
    # there is no derivable form for them.
    if "cpo:definesForm" not in material and "cpo:fillsForm" not in material:
        device = find_entity(datagraph, ref_id(material.get("cpo:materialContainedIn")))
        device_form = find_entity(datagraph, ref_id(device.get("cpo:definesForm"))) if device else None
        if device_form is not None:
            # The material only fills the region the device sets (rule 3a.1).
            inherited_form = device_form.get("cpo:hasCavityForm") or device.get("cpo:definesForm")
            set_property(material, "cpo:fillsForm", inherited_form, namespace_collection)

    # If a MaterialRepresentation is left without a reachable form after that, it defines a
    # cpo:IndeterminateForm: without dimensions, without evidence/reference. That concerns only
    # the streams that hang at no device - boundary streams across the system boundary and
    # connections between two devices. That they HAVE a form is undisputed; it cannot be stated,
    # because the data model has no concept of geometry for pipes and connections - once lines
    # are devices, the stream fills their cavity like the content of a vessel. An
    # IndeterminateForm, not an empty cpo:Form: "cannot be determined" is a statement, a form
    # without a class would look like a gap. Every level has its own form (rule 3a.4), so that the
    # phase of the experiment has a form of its level to fill; the form of the experiment
    # specializes that of the series.
    if not form_ref(material):
        form_type = check_type("cpo:IndeterminateForm", namespace_collection)
        experiment_number = nr if scope == "hlo:ExperimentSpecific" else None
        form_id = generate_id_from_name(f"Form_{short_local_name(material['@id'])}", scope, experiment_number)
        # An actual like every other form of an exemplar.
        placeholder_form = {"@id": form_id, "@type": [form_type, scope, "hlo:Actual"]}
        parent_material = resolve(datagraph, ref_id(material.get("hlo:specializationOf")))
        parent_form = find_entity(datagraph, ref_id(form_ref(parent_material))) if parent_material else None
        if parent_form is not None:
            set_property(placeholder_form, "hlo:specializationOf", parent_form, namespace_collection)
            set_property(parent_form, "hlo:hasSpecialization", placeholder_form, namespace_collection, True)
        set_property(material, "cpo:definesForm", placeholder_form, namespace_collection)
        add_entity(datagraph, placeholder_form)

    # Stream-specific: flowsFrom / flowsTo / hasFlowrate --------------------------------------
    if material_type == "Stream":

        if "cpo:flowsFrom" not in material:
            source = ask_for_port(
                f"[{scope}] From which Port does {material['@id']} flow away from (flowsFrom)?",
                "cpo:DevicePort",   # add "cpo:DeviceOpening" as soon as the class exists in the ontology
                "cpo:Source", material, True, scope, nr, namespace_collection, datagraph, todo_list,
                question_id="flows_from_port"
            )
            set_property(material, "cpo:flowsFrom", source, namespace_collection)

        if "cpo:flowsTo" not in material:
            sink = ask_for_port(
                f"[{scope}] To which Port does {material['@id']} flow towards (flowsTo)?",
                "cpo:DevicePort",   # add "cpo:DeviceOpening" as soon as the class exists in the ontology
                "cpo:Sink", material, False, scope, nr, namespace_collection, datagraph, todo_list,
                question_id="flows_to_port"
            )
            set_property(material, "cpo:flowsTo", sink, namespace_collection)

        # Set the inverse property on the port in question - whether the port was just chosen/
        # created or taken over from the series counterpart above.
        link_stream_to_port(material, material["cpo:flowsFrom"], True, namespace_collection, datagraph, todo_list)
        link_stream_to_port(material, material["cpo:flowsTo"], False, namespace_collection, datagraph, todo_list)

        # As for phase/interface process variables (see add_phase_process_variable):
        # evidence_known_cache allows the "do we know this for all experiments" shortcut on the
        # series level, instead of asking for evidence/reference in every experiment.
        add_phase_process_variable(material, "cpo:hasFlowrate", scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache)










    # MaterialVolume-specific: hasVolume -------------------------------------------------------
    # BodyMaterial (the material a device consists of, e.g. glass) excluded: its volume is not
    # asked but is to be resolved (like cpo:hasInnerVolume, see Device_Space_R1) via
    # hlo:specializationOf from the Fixed library entity, as soon as it is stored there.
    is_body_material = "cpo:BodyMaterial" in material.get("@type", [])
    if is_body_material and _counterpart_has_own_volume(material, datagraph):
        # A body material of several layers (phases) has a volume of its own that no phase shares
        # (rule 3a.6); the library names it, the exemplar specializes it. With one phase, material
        # and phase share a volume (_share_material_volume) - there everything stays as it was.
        add_phase_process_variable(material, "cpo:hasVolume", scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache)
    if material_type == "MaterialVolume" and not is_body_material:
        add_phase_process_variable(material, "cpo:hasVolume", scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache)

        # Item 8 (upper bound of the volume): relevant only for device-driven contained materials
        # (cpo:materialContainedIn set, see device_functions.py) - for other MaterialVolumes
        # (additional materials, environment, ...) check_material_volume_against_device is already
        # a no-op through the missing cpo:materialContainedIn.
        if device_library is not None:
            check_material_volume_against_device(material, datagraph, device_library)

    # State of the material as a whole: temperature and pressure, at every material on every
    # level. A different statement from that of the phases - here stand setpoints, controlled
    # variables and measurements that cannot be assigned to any phase. With a single-phase
    # material every value belongs at the phase: the quantities exist, but are not offered in
    # the list of the material (rule 3.8).
    single_phase = len(ref_ids(material.get("dcterms:hasPart"))) <= 1
    for property_name in ("cpo:hasTemperature", "cpo:hasPressure"):
        add_phase_process_variable(material, property_name, scope, nr, namespace_collection,
                                   datagraph, todo_list, local_todo_list, evidence_known_cache,
                                   offer_values=not single_phase)


    return info

# ---------------------------------------------------------------------------
# Working through the to-do list
# ---------------------------------------------------------------------------

def create_series_material(scope: str, nr: int, namespace_collection: dict, datagraph: dict, todo_list: list, local_todo_list: list, evidence_known_cache: dict = None, material_name: str = None):
    """Create the series-specific material named material_name (one entry of the list of
    additional materials, see create_all_materials). Every question about it - its type
    included - runs under "material:<name>" (helpers/identifiers.py: key_name)."""
    info = {}

    # The name comes from the list (create_all_materials), and from it the key - all questions
    # about this material, also the one about its type, stand under "material:<name>".
    with question_path("material", key_name(make_root_id("Material", material_name, scope))):
        return _describe_series_material(material_name, info, scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache)


def _describe_series_material(material_name: str, info: dict, scope: str, nr: int, namespace_collection: dict, datagraph: dict, todo_list: list, local_todo_list: list, evidence_known_cache: dict = None):
    # The kind stands once at the series - another material is another setup (see
    # create_series_device; rule 7c.2).
    info["sameType"] = True
    material_type_answer = ask_user("[hlo:SeriesSpecific] Is this additional material a Stream or a MaterialVolume?", ["cpo:Stream", "cpo:MaterialVolume"], question_id="material_type")
    info["materialType"] = material_type_answer

    material_type = check_type(material_type_answer, namespace_collection)

    # fill_material_properties expects the type without prefix ("Stream"/"MaterialVolume"),
    # but material_type_answer is needed with prefix ("cpo:Stream") for check_type.
    material_type_short = material_type_answer.split(":", 1)[-1]
    entity_id = claim_id(make_root_id("Material", material_name, scope),
                             datagraph, todo_list, local_todo_list, what=f"The material '{material_name}'")
    material = {"@id": entity_id, "@type": [material_type, scope]}
    set_property(material, "schema:name", material_name, namespace_collection)

    # Before all following questions, make clear which entity and which type it is about,
    # so that the questions after it (phases, ports, ...) can be assigned unambiguously.
    print(f"\n=== Now describing {material_type_short} \"{material_name}\" ({entity_id}, {scope}) ===")

    fill_material_properties(material, material_type_short, scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, info, evidence_known_cache)

    add_entity(datagraph, material)
    return material, info







def create_experiment_material(series_material: dict, info: dict, scope: str, nr: int, namespace_collection: dict, datagraph: dict, todo_list: list, local_todo_list: list, evidence_known_cache: dict = None):
    """Runs entirely under the same "material:N" number as its series counterpart (see
    stable_index). That number is already settled - it was assigned in
    create_series_material - and so is known here BEFORE the first question."""

    with question_path("material", key_name(series_material["@id"])):
        # The kind stands at the series, the experiment takes it over.
        material_type_answer = info["materialType"]

        material_type = check_type(material_type_answer, namespace_collection)
        # The experiment version carries the local name of its series template, even if it gets a
        # name of its own (with a changing type) - it is the same thing.
        entity_id = claim_id(make_specialization_id(series_material["@id"], nr),
                                 datagraph, todo_list, local_todo_list)
        material = {"@id": entity_id, "@type": [material_type, scope]}

        # fill_material_properties expects the type without prefix ("Stream"/"MaterialVolume")
        material_type_short = material_type_answer.split(":", 1)[-1]

        # Take over the name structurally from the series counterpart instead of asking again.
        material_name = series_material.get("schema:name") or generate_name(entity_id)
        set_property(material, "schema:name", material_name, namespace_collection)

        # Before all following questions, make clear which entity and which type it is about,
        # so that the questions after it (phases, ports, ...) can be assigned unambiguously.
        print(f"\n=== Now describing {material_type_short} \"{material_name}\" ({entity_id}, {scope}, Experiment {nr}) ===")

        # Link with the series counterpart right now (before fill_material_properties), so that
        # add_phase_process_variable (flowrate/volume) finds and links the series PV itself through
        # it (get_series_entity) - no manual linking afterwards needed any more.
        set_property(material, "hlo:specializationOf", series_material, namespace_collection)
        set_property(series_material, "hlo:hasSpecialization", material, namespace_collection, True)

        # Specialize the phases automatically, no question again
        if "series_phase_ids" in info:
            add_experiment_phases_from_series(material, info["series_phase_ids"], scope, nr, namespace_collection, datagraph, todo_list, local_todo_list)

        # Take over the ports (flowsFrom/flowsTo) automatically from the series counterpart, no question again
        if material_type_short == "Stream":
            add_experiment_ports_from_series(material, series_material, nr, namespace_collection, datagraph, todo_list)

        fill_material_properties(material, material_type_short, scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache=evidence_known_cache)

    add_entity(datagraph, material)
    return material








def create_material_from_todo(item: dict, scope: str, nr: int, namespace_collection: dict, datagraph: dict, todo_list: list, local_todo_list: list, evidence_known_cache: dict = None, device_library: dict = None):

    material_type = get_type(item)
    material_type_short = material_type.split(":", 1)[-1]

    # If this (device-driven) ExperimentSpecific material is already linked via
    # hlo:specializationOf with a SeriesSpecific material (see
    # device_functions.create_experiment_device), we take over its phases, (for streams)
    # ports and name automatically, instead of asking everything again.
    series_material = None
    if scope == "hlo:ExperimentSpecific":
        series_ref = item.get("hlo:specializationOf")
        series_id = series_ref.get("@id") if isinstance(series_ref, dict) else series_ref
        series_material = find_entity(datagraph, series_id) if series_id else None

    with question_path("material", key_name(item["@id"])):
        # For device-driven contained materials the name is asked by now already when the
        # device is created (see device_functions.py), with the device in the prompt - so
        # here it is only taken over, not asked again.
        if series_material and series_material.get("schema:name"):
            material_name = series_material["schema:name"]
        elif item.get("schema:name"):
            material_name = item["schema:name"]
        else:
            material_name = ask_name(scope, material_type_short)
        set_property(item, "schema:name", material_name, namespace_collection)

        # Before all following questions, make clear which entity and which type it is about,
        # so that the questions after it (phases, ports, ...) can be assigned unambiguously.
        print(f"\n=== Now describing {material_type_short} \"{material_name}\" ({item['@id']}, {scope}, from device creation) ===")

        if series_material:
            if "dcterms:hasPart" not in item and series_material.get("dcterms:hasPart"):
                series_phase_ids = [p["@id"] for p in series_material["dcterms:hasPart"]]
                add_experiment_phases_from_series(item, series_phase_ids, scope, nr, namespace_collection, datagraph, todo_list, local_todo_list)

            if material_type_short == "Stream":
                add_experiment_ports_from_series(item, series_material, nr, namespace_collection, datagraph, todo_list)

        fill_material_properties(item, material_type_short, scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache=evidence_known_cache, device_library=device_library)

    add_entity(datagraph, item)
    delete_todo_entity(todo_list, item)

    return item




def material_todo_item_matches_experiment(item: dict, scope: str, nr: int, datagraph: dict) -> bool:
    """A device-driven contained-material item (stream or MaterialVolume) carries no
    experiment number of its own, only the scope "hlo:ExperimentSpecific", which is the same
    for every experiment.

    Without this check, working through experiment 1 would also process the material of
    experiment 2 and every further one, because they all carry the same scope. The actual
    experiment number is therefore determined through the device the material is held in
    (cpo:materialContainedIn).
    """
    if scope != "hlo:ExperimentSpecific":
        return True

    device_ref = item.get("cpo:materialContainedIn")
    device_id = device_ref.get("@id") if isinstance(device_ref, dict) else device_ref
    device = find_entity(datagraph, device_id) if device_id else None
    if not device:
        return True

    return get_device_experiment_number(device, datagraph) == nr


def create_materials_from_todo(scope: str, nr: int, namespace_collection: dict, datagraph: dict, todo_list: list, local_todo_list: list, evidence_known_cache: dict = None, device_library: dict = None):
    stream_items = [
        i for i in find_todo_items_by_type(todo_list, "cpo:Stream")
        if scope in i.get("@type", []) and material_todo_item_matches_experiment(i, scope, nr, datagraph)
    ]
    volume_items = [
        i for i in find_todo_items_by_type(todo_list, "cpo:MaterialVolume")
        if scope in i.get("@type", []) and material_todo_item_matches_experiment(i, scope, nr, datagraph)
    ]

    created = []
    for item in stream_items + volume_items:
        create_material_from_todo(item, scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache, device_library)
        created.append(item)
    return created




# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def create_all_materials(namespace_collection: dict, datagraph: dict, todo_list: list, number_experiments: int, device_library: dict = None):

    local_todo_list = []
    series_scope = "hlo:SeriesSpecific"

    # Lives for the whole run: remembers per (series material, property) the
    # "do we know this for all experiments" shortcut of add_phase_process_variable
    # (see helpers/process_variables.py), so that hasFlowrate/hasVolume do not ask for
    # evidence/reference in every experiment when that was denied on the series level
    # already.
    evidence_known_cache = {}

    print("\n--- Materials: Series level ---")
    create_materials_from_todo(series_scope, 1, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache, device_library)

    series_materials = []  # list of (material, info) pairs
    # As a list of names instead of "another one?" with a counter - see name_list in
    # helpers/identifiers.py: a new material is one name more, not a shift.
    names = ask_user(
        "[hlo:SeriesSpecific] Which additional materials (Streams or MaterialVolumes) have not been recorded yet? Their names, separated by ';' (leave empty if none)",
        answer_type=name_list, question_id="additional_material_names"
    )
    for material_name in names:
        material, info = create_series_material(series_scope, 1, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache, material_name=material_name)
        series_materials.append((material, info))

    # Only now, when all series materials are there - before the experiments, which inherit
    # the statement (link_experiment_samples).
    ask_sample_materials(namespace_collection, datagraph)

    experiment_scope = "hlo:ExperimentSpecific"
    for e in range(number_experiments):
        nr = e + 1
        with question_path("experiment", nr):
            print(f"\n--- Materials: Experiment {nr} ---")
            create_materials_from_todo(experiment_scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache, device_library)

            for series_material, info in series_materials:
                create_experiment_material(series_material, info, experiment_scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache)

            link_experiment_samples(nr, namespace_collection, datagraph)

    return local_todo_list
