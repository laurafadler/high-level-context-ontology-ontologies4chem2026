"""
Everything needed to create Environment entities - the surroundings, i.e. the room air a
device sits in - as a MaterialVolume.

Structurally an environment is an ordinary MaterialVolume (with phases, a composition,
...) and is therefore completed entirely through the existing functions in
material_functions.py and phase_functions.py. This module only handles the extra third
level (Fixed) that ordinary materials do not have:

    Fixed (an entry in libraries/organization_library.jsonld, located inside a room or
    laboratory) -> SeriesSpecific (once per series, for the room actually used) ->
    ExperimentSpecific (once per experiment)

Which room is used is NOT asked for but derived automatically from the devices already
created: every device points, through cpo:locatedInsideOf (directly, or transitively
through cpo:location/dcterms:isPartOf), at a room. That is purely static library
information (see device_library.jsonld), not a question at runtime.
"""

from helpers.entities import find_entity, ref_id, as_list
from helpers.properties import set_property, set_location
from helpers.identifiers import get_display_label, key_name
from creation.material_functions import fixed_library_material, create_series_material_from_fixed, create_experiment_material_from_series
from helpers.energy_fields import create_energy_field, get_own_energy_field, ENERGY_FIELD_TYPE_OPTIONS
from helpers.user_io import question_path, ask_user_list


ROOM_TYPES = ("cpo:Room", "cpo:Laboratory")


def _is_room(entity: dict) -> bool:
    types = as_list(entity.get("@type"))
    return any(t in ROOM_TYPES for t in types)


# ---------------------------------------------------------------------------
# Find the room of a device (purely from the static library data)
# ---------------------------------------------------------------------------

def resolve_device_room(device_id: str, device_library: dict, organization_library: dict, max_depth: int = 8):
    """Starting from a device library ID, follow the
    cpo:locatedInsideOf/cpo:location/dcterms:isPartOf chain through the static library data
    until a room or laboratory entity from the organization library is reached - for
    example stirrer001 -location-> vessel001 -isPartOf-> reactor001 -locatedInsideOf->
    lab:L109.

    Returns None when no room is recorded.
    """
    current_id = device_id
    visited = set()

    for _ in range(max_depth):
        if current_id in visited:
            return None
        visited.add(current_id)

        room_entity = find_entity(organization_library, current_id)
        if room_entity and _is_room(room_entity):
            return room_entity

        # Between device and room there can be a place of the Organization Library that is no room -
        # the cabinet a bottle of the store stands in (cpo:StorageCabinet).
        device_entity = find_entity(device_library, current_id) or find_entity(organization_library, current_id)
        if not device_entity:
            return None

        # A device that sits at a port of another (a cap on the opening of its bottle, cpo:locatedAt)
        # stands where that device stands: on to the port, from the port to its device.
        next_ref = (
            device_entity.get("cpo:locatedInsideOf")
            or device_entity.get("cpo:location")
            or device_entity.get("cpo:locatedAt")
            or device_entity.get("cpo:isPortOf")
            or device_entity.get("dcterms:isPartOf")
        )
        if not next_ref:
            return None
        current_id = ref_id(next_ref)

    return None


def get_used_rooms(datagraph: dict, device_library: dict, organization_library: dict) -> list:
    """Find every room that holds at least one device created in this series, using
    resolve_device_room."""
    rooms_by_id = {}

    for entity in datagraph.get("@graph", []):
        types = as_list(entity.get("@type"))
        if "hlo:SeriesSpecific" not in types:
            continue

        twin_id = ref_id(entity.get("hlo:specializationOf"))
        if not twin_id or not twin_id.startswith("device:"):
            continue

        room = resolve_device_room(twin_id, device_library, organization_library)
        if room:
            rooms_by_id[room["@id"]] = room

    return list(rooms_by_id.values())


# ---------------------------------------------------------------------------
# Take the Fixed environment of a room over once from the library into the datagraph
# ---------------------------------------------------------------------------

def fixed_environment_of_room(room: dict, organization_library: dict):
    """The fixed environment of a room (environment MaterialVolume -locatedInsideOf-> room;
    environment -hasPart-> phase -hasPart-> species) as it stands in the organization library -
    or None when the room has no environment recorded. It stays in the library (see
    fixed_library_material), the same pattern as for a device's body material, see
    device_functions.py.
    """
    # The room air points at its room, not the room at its air (rule 7.9): places do not point
    # downwards, the air is no component of the room but stands in it - like the room air of every
    # level in the crate. The library room air is thus reachable only via hlo:specializationOf, not
    # by descending from the room.
    for entity in organization_library.get("@graph", []):
        types = as_list(entity.get("@type"))
        if "cpo:Environment" in types and ref_id(entity.get("cpo:locatedInsideOf")) == room["@id"]:
            return fixed_library_material(entity["@id"], organization_library)
    return None


# ---------------------------------------------------------------------------
# Create the SeriesSpecific/ExperimentSpecific environment
# ---------------------------------------------------------------------------

def create_series_environment(fixed_environment: dict, room: dict, namespace_collection: dict, datagraph: dict, todo_list: list, local_todo_list: list, evidence_known_cache: dict = None, library: dict = None):
    """Create the series-specific environment of a room.

    The fixed-to-series core - carrying over name, phases and species, and filling the
    remaining properties through fill_material_properties - runs in
    create_series_material_from_fixed (see material_functions.py). All that is added here
    is the environment-specific placement (cpo:locatedInsideOf -> room).
    """
    material = create_series_material_from_fixed(
        fixed_environment, namespace_collection, datagraph, todo_list, local_todo_list,
        material_type_id="cpo:Environment", context_label="Environment", evidence_known_cache=evidence_known_cache,
        stable_index_level="environment", library=library
    )
    set_property(material, "cpo:locatedInsideOf", room, namespace_collection)
    return material


def create_experiment_environment(series_environment: dict, nr: int, namespace_collection: dict, datagraph: dict, todo_list: list, local_todo_list: list, evidence_known_cache: dict = None):
    """Like create_series_environment, one level further down (series -> experiment)."""
    material = create_experiment_material_from_series(
        series_environment, nr, namespace_collection, datagraph, todo_list, local_todo_list,
        material_type_id="cpo:Environment", context_label="Environment", evidence_known_cache=evidence_known_cache,
        stable_index_level="environment"
    )
    if "cpo:locatedInsideOf" in series_environment:
        set_property(material, "cpo:locatedInsideOf", series_environment["cpo:locatedInsideOf"], namespace_collection)
    return material


# ---------------------------------------------------------------------------
# Measured ambient fields: at the room air of the level in question
# ---------------------------------------------------------------------------

def add_measured_ambient_fields(environment: dict, room: dict, scope: str, nr: int, field_types, namespace_collection: dict, datagraph: dict, todo_list: list, local_todo_list: list, evidence_known_cache: dict, organization_library: dict) -> list:
    """Create the ambient energy fields measured during the series on the ambient air of this
    level. At series level the types are asked for (a list, empty for none); at experiment
    level the series' choice is passed in as field_types and nothing is asked.

    Where the site already carries a field of that type (the gravitational field), the series
    field specializes it, and its strength is taken over as an empty Actual whose value comes
    through the usual value lists. There is no link to the room or the site: that stands on
    the Fixed field. Returns the field types.
    """
    # Boundary: places have no levels. An ambient field that was measured, however, has a state
    # per experiment - so it hangs at the room air of the level, which exists already, and not
    # at a room or site copied specially.
    with question_path("environment", key_name(environment["@id"])):
        if field_types is None:
            field_types = ask_user_list(
                f"[{scope}] Which ambient energy fields were measured in {get_display_label(room)} during this series or its experiments? "
                f"(Only measured ones - the gravity of the site is recorded in the library anyway.)",
                list(ENERGY_FIELD_TYPE_OPTIONS.values()), question_id="measured_ambient_fields")

        site = find_entity(organization_library, ref_id(room.get("cpo:isRoomOf")))
        for field_type in field_types:
            library_field = None
            if scope == "hlo:SeriesSpecific" and site is not None:
                library_field = get_own_energy_field(site, field_type.split(":", 1)[-1], organization_library)
            # Context level like the other quantities of the room air (temperature, pressure): phase.
            create_energy_field(environment, field_type, scope, nr, namespace_collection, datagraph, todo_list,
                                local_todo_list, evidence_known_cache, library_field=library_field, library=organization_library)
    return field_types


# ---------------------------------------------------------------------------
# Devices in the room: location at the room air of the same level
# ---------------------------------------------------------------------------

LOCATION_PROPERTIES = ("cpo:location", "cpo:locatedAt", "cpo:locatedInsideOf")


def place_devices_in_environment(room: dict, series_environment: dict, experiment_environments: dict, datagraph: dict, device_library: dict, organization_library: dict, namespace_collection: dict):
    """Point every series and experiment device that stands in this room - and not in another
    device of the crate - at the ambient air of its own level (cpo:locatedInsideOf), the
    same property the library uses for the room itself.

    Devices inside other devices already got their location in create_all_devices, pointing
    at the device of the same level they sit in; they are left alone here.
    """
    # Boundary (Device_Space_R2, rule 1): exemplars have levels, places do not. The room exists
    # only as a Fixed entry, the room air on every level - through it the collecting path of a
    # device also reaches what was measured in the surroundings on its level, and from it
    # (cpo:locatedInsideOf) the room and the site.
    for device in datagraph.get("@graph", []):
        types = as_list(device.get("@type"))
        if "hlo:SeriesSpecific" not in types:
            continue
        twin_id = ref_id(device.get("hlo:specializationOf"))
        if not twin_id or not twin_id.startswith("device:"):
            continue
        if any(device.get(p) for p in LOCATION_PROPERTIES):
            continue
        located_room = resolve_device_room(twin_id, device_library, organization_library)
        if located_room is None or located_room["@id"] != room["@id"]:
            continue

        set_location(device, "cpo:locatedInsideOf", series_environment, namespace_collection)
        # hlo:hasSpecialization is in the order of the experiments (see
        # get_device_experiment_number in material_functions.py).
        for index, experiment_ref in enumerate(as_list(device.get("hlo:hasSpecialization"))):
            experiment_device = find_entity(datagraph, ref_id(experiment_ref))
            experiment_environment = experiment_environments.get(index + 1)
            if experiment_device is not None and experiment_environment is not None:
                set_location(experiment_device, "cpo:locatedInsideOf", experiment_environment, namespace_collection)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def create_all_environments(namespace_collection: dict, datagraph: dict, todo_list: list, device_library: dict, organization_library: dict, number_experiments: int) -> list:
    """Create one series-specific and one experiment-specific environment for every room
    actually used (see get_used_rooms).

    Which room that is follows automatically from the devices already created; nothing has
    to be chosen. Rooms without a fixed environment on record are skipped, with an
    informational message rather than an error.
    """
    local_todo_list = []

    rooms = get_used_rooms(datagraph, device_library, organization_library)
    if not rooms:
        return local_todo_list

    # Lives for the whole run: the same "do we know this per experiment" shortcut as for
    # devices/phases/materials (see helpers/process_variables.py) - without it, e.g. the
    # volume of the room air would be asked in every experiment.
    evidence_known_cache = {}

    for room in rooms:
        fixed_environment = fixed_environment_of_room(room, organization_library)
        if fixed_environment is None:
            print(f"[Environment] {get_display_label(room)} has no Fixed environment recorded in the library - skipping.")
            continue

        print(f"\n--- Environment of {get_display_label(room)} ---")
        series_environment = create_series_environment(fixed_environment, room, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache, organization_library)
        measured_field_types = add_measured_ambient_fields(series_environment, room, "hlo:SeriesSpecific", 1, None, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache, organization_library)

        experiment_environments = {}
        for e in range(number_experiments):
            nr = e + 1
            with question_path("experiment", nr):
                experiment_environments[nr] = create_experiment_environment(series_environment, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache)
                add_measured_ambient_fields(experiment_environments[nr], room, "hlo:ExperimentSpecific", nr, measured_field_types, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache, organization_library)

        place_devices_in_environment(room, series_environment, experiment_environments, datagraph, device_library, organization_library, namespace_collection)

    return local_todo_list
