"""
Energy fields for devices, phases, molecules and org:Site.

Every field has exactly one source (cpo:hasEnergyField/cpo:isEnergyFieldOf). Device, phase and
molecule fields follow the usual series/experiment pattern (see create_energy_field, along the
lines of helpers/process_variables.py). A field of a library entry (a device that creates one, a
radioactive substance) is entered in the library; the generator never writes into a library.

The gravitational field of an org:Site is NOT created by the code: it is maintained by
hand in organization_library.jsonld before a crate is built. Reading it is not the code's
job either - the collection paths of the shapes climb to it (Device_Energy_R6,
Phase_Energy_R5, Molecule_Energy_R2).
"""

from helpers.entities import add_entity, find_entity, ref_id, as_list
from helpers.properties import set_property, check_type
from helpers.identifiers import generate_id_from_name, short_local_name
from helpers.ontology_functions import find_entity_in_ontology
from helpers.process_variables import get_series_entity, add_phase_process_variable
from helpers.user_io import question_path
from helpers.time_occurrence import add_occurrence


# Answer options -> individual in the ontology. "gravitational" is deliberately not askable
# (see ASKABLE_ENERGY_FIELD_TYPES): the general gravitational field hangs at the site, is
# kept by hand in organization_library.jsonld (see the module docstring) and is not asked as
# a field "created by a device/a phase itself".
ENERGY_FIELD_TYPE_OPTIONS = {
    "gravitational": "cpo:GravitationalField",
    "electric": "cpo:ElectricField",
    "magnetic": "cpo:MagneticField",
    "electromagnetic": "cpo:ElectromagneticField",
    "ionizing radiation": "cpo:IonizingRadiation",
}
ASKABLE_ENERGY_FIELD_TYPES = {k: v for k, v in ENERGY_FIELD_TYPE_OPTIONS.items() if k != "gravitational"}

ENERGY_FIELD_TYPE_QUESTION = "Which type of energy field is it?"

# Quantity kind per type of field, for the fields the code creates itself (create_energy_field) -
# the gravitational field of a site is kept by hand (see the module docstring) and therefore
# deliberately does not appear here. The field strength is created like every other
# ProcessVariable only with its QuantityKind (see add_phase_process_variable); the number comes
# through the usual evidence/reference question. The table stands in
# generator/config/units_and_quantity_kinds.json.
from helpers.units import ENERGY_FIELD_QUANTITY_KIND


def find_entity_anywhere(entity_id: str, *graphs):
    """Like find_entity, but searches several graphs one after another.

    Needed because devices and phases live in the datagraph while their room, laboratory
    or site only exists in the libraries (device_library/organization_library) - see
    environment_functions.py: resolve_device_room for the same problem when looking up a
    room.
    """
    for graph in graphs:
        if graph is None:
            continue
        entity = find_entity(graph, entity_id)
        if entity is not None:
            return entity
    return None


def get_own_energy_field(entity: dict, field_type_local_name: str, *graphs):
    """Return the field of the requested type that hangs directly off the entity (found in
    one of the graphs passed in), otherwise None.

    field_type_local_name is the local name without a prefix ("GravitationalField", for
    example) - compared with endswith so that it works both with "cpo:X" and with the full
    IRI.
    """
    for field_ref in as_list(entity.get("cpo:hasEnergyField")):
        field = find_entity_anywhere(ref_id(field_ref), *graphs)
        if field is None:
            continue
        field_type = ref_id(field.get("cpo:hasEnergyFieldType")) or ""
        if field_type.endswith(field_type_local_name):
            return field
    return None


# ---------------------------------------------------------------------------
# Device/phase: SeriesSpecific/ExperimentSpecific field (like every other ProcessVariable)
# ---------------------------------------------------------------------------

def create_energy_field(source: dict, field_type: str, scope: str, nr: int,
                         namespace_collection: dict, datagraph: dict, todo_list: list, local_todo_list: list,
                         evidence_known_cache: dict = None, library_field: dict = None, library: dict = None):
    """Create the energy field a device or phase can generate - on series and on experiment
    level (the caller decides through scope/nr).

    The field is a thing, like a form (rule 3.1): no hlo:Actual of its own.
    Being able to generate a field does not mean generating it in this experiment - that is a
    phenomenon, recorded like a transfer or a reaction: an Occurrence plus start time, end time
    and duration (experiment level only, as there). The measurable quantity is the field
    strength, an ordinary Actual. All of them stand in the question path segment
    "energy_field", so the field asks its own lists (helpers/value_sources.py).

    library_field: the field the library entry of the source declares (a manufacturer's
    specification, e.g. the drive magnet of a stirrer plate) - the series field specializes it,
    like every series thing its library entry; library is where it and its strength live.
    Whether the source can generate a field, and of which types, is settled by the caller.

    A source can carry several fields, one per type (a stirrer plate with a magnetic and an
    electric field); a second call for a type the source already has does nothing.
    """
    type_local_name = field_type.split(":", 1)[-1]
    # One per type, not one per source: the type therefore also stands in the
    # ID and in the question path, otherwise two fields of one source would share their answers.
    if get_own_energy_field(source, type_local_name, datagraph) is not None:
        return None

    energy_field_type = check_type("cpo:EnergyField", namespace_collection)
    experiment_number = nr if scope == "hlo:ExperimentSpecific" else None
    energy_field_id = generate_id_from_name(f"EnergyField_{short_local_name(source['@id'])}_{type_local_name}", scope, experiment_number)

    energy_field = {"@id": energy_field_id, "@type": [energy_field_type, scope]}

    set_property(energy_field, "cpo:isEnergyFieldOf", source, namespace_collection)
    set_property(source, "cpo:hasEnergyField", energy_field, namespace_collection, True)

    field_type_individual = find_entity_in_ontology(field_type, namespace_collection)
    set_property(energy_field, "cpo:hasEnergyFieldType", field_type_individual, namespace_collection)

    # specializationOf BEFORE add_phase_process_variable: its get_series_entity search finds the
    # field one level higher through it - and for a library field its field strength, which is
    # then inherited as an empty actual of its own (add_specializing_actual). The library field
    # and its strength stay in the library; they are found via resolve.
    if scope == "hlo:ExperimentSpecific":
        series_source = get_series_entity(source, datagraph)
        series_field = get_own_energy_field(series_source, type_local_name, datagraph) if series_source else None
        if series_field:
            set_property(energy_field, "hlo:specializationOf", series_field, namespace_collection)
            set_property(series_field, "hlo:hasSpecialization", energy_field, namespace_collection, True)
    elif library_field is not None:
        set_property(energy_field, "hlo:specializationOf", library_field, namespace_collection)

    with question_path("energy_field", type_local_name):
        quantity_kind = ENERGY_FIELD_QUANTITY_KIND[field_type]
        add_phase_process_variable(
            energy_field, "cpo:hasFieldStrength", scope, nr, namespace_collection, datagraph, todo_list, local_todo_list,
            evidence_known_cache, quantity_kinds=[quantity_kind]
        )
        # Whether the field occurred in this experiment, and when - as for transfers and reactions.
        add_occurrence(energy_field, scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache)

    add_entity(datagraph, energy_field)
    return energy_field


# ---------------------------------------------------------------------------
# Ascent and descent of the collecting paths (master lists for the shapes)
# ---------------------------------------------------------------------------

# Properties through which one gets one level "up" from a device/a phase/a molecule, all the
# way to the site: device -> device above it (cpo:location/dcterms:isPartOf) -> room air of the
# same level (cpo:locatedInsideOf) -> room (cpo:locatedInsideOf) -> site (cpo:isRoomOf). From a
# phase first to the material (dcterms:isPartOf) and from there to the device that contains it
# (cpo:materialContainedIn) or whose body it is (cpo:isBodyMaterialOf - otherwise a phase of the
# body would not get to its device).
#
# These lists are the MASTER lists: the collecting paths in Device_Energy_R6_ContextPathShape,
# Phase_Energy_R5_ContextPathShape and Molecule_Energy_R2_ContextPathShape
# (ContextRequirementShapes.ttl) mirror them exactly - every change here must be made there too
# (and vice versa), check_context_requirements_consistency.py compares both sides.
# There UP (PARENT_PROPERTIES) and DOWN (CHILD_PROPERTIES) stand as a sequence: first up any
# number of times, then from every node reached down any number of times (each
# sh:zeroOrMorePath over the alternative of all entries). This goes down from
# the room air into every device of the room (cpo:isLocationOf, see CHILD_PROPERTIES): every
# field in the room acts everywhere in it, how strongly is a value. It does not run across the
# levels, because the generator sets cpo:isLocationOf only in the crate and only between
# entities of the same level (helpers/properties.py: set_location) - the Fixed room never
# carries it. An sh:inversePath on cpo:location, however, would have run from the Fixed room
# into every level (check_context_requirements_consistency.py forbids it, check 7).
# - cpo:locatedAt is included (a declared subproperty of cpo:location).
# - cpo:locatedOutsideOf is DELIBERATELY NOT included: it was meant for "jacket outside the
#   vessel", is not actually used in any library and would fake a climbing path that exists
#   nowhere.
# - cpo:isRoomOf carries the last step room -> site. The gravitational field hangs there
#   (organization_library.jsonld), not at the room - without this step the ascent ends before it.
# - cpo:isContainedIn stays next to cpo:materialContainedIn: without inference SHACL does not
#   follow rdfs:subPropertyOf, a containment that only carries the general property would
#   otherwise not be climbed.
# - hlo:specializationOf is NOT part of it: the location stands on every level (Device_Space_R2),
#   the ascent stays on the level of the exemplar. The values of higher levels of a field are
#   collected by the path after cpo:hasEnergyField along the chain of the field.
# - cpo:flowsFrom and cpo:flowsTo: a stream that no device contains - between two devices, or from a
#   cpo:Source / into a cpo:Sink at one end - climbs over its ends to the ports and from there
#   (cpo:isPortOf) to their devices and into the room; every such stream touches at least one device of
#   the set-up (rule 7.10). A stream in a device reaches the same room through
#   cpo:materialContainedIn already; the steps go only from the stream to its ports, never back, so the
#   paths of devices and of the phases in a device do not change.
# NOTE: must be updated as soon as cpo:isContainedIn or cpo:location gets a new subproperty
# (currently: cpo:materialContainedIn and cpo:locatedAt, cpo:locatedInsideOf,
# cpo:locatedOutsideOf), and likewise for CHILD_PROPERTIES.
PARENT_PROPERTIES = [
    "cpo:locatedInsideOf",
    "cpo:locatedAt",
    "cpo:isPortOf",            # from the port a device sits at (cpo:locatedAt, a cap on its bottle) to its device
    "cpo:flowsFrom",           # from a stream that no device contains to the port it leaves ...
    "cpo:flowsTo",             # ... and to the one it enters, then over cpo:isPortOf to the device
    "cpo:location",
    "dcterms:isPartOf",
    "cpo:isContainedIn",
    "cpo:materialContainedIn",
    "cpo:isBodyMaterialOf",
    "cpo:isRoomOf",
]

# Properties through which one gets "down": device -> parts (dcterms:hasPart), content
# (cpo:containsMaterial) and body material (cpo:madeOfMaterial) -> their phases
# (dcterms:hasPart) -> molecules (dcterms:hasPart). That is how a reactor reaches the field of
# a radioactive molecule in its vessel. cpo:contains for the same reason as cpo:isContainedIn
# above. cpo:isLocationOf: from the room air to the devices in it and from a
# device to what stands in it - that is how the balance reaches the field of the stirrer, and a
# device that only stands IN another one (without being part of it) is reached as well.
CHILD_PROPERTIES = [
    "dcterms:hasPart",
    "cpo:contains",
    "cpo:containsMaterial",
    "cpo:madeOfMaterial",
    "cpo:isLocationOf",
]


