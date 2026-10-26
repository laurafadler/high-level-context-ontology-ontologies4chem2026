"""
Creating transfers: a chemical entity changes place - either at an interface (phase to
phase, or phase to interface occupation in adsorption/desorption) or at a device port
(a port crossing).

Lives in helpers/ rather than in creation/phase_functions.py so that both
creation/reaction_functions.py (transfers for interface reactions) and
creation/phase_functions.py itself (port crossings, ordinary interface transfers) can use
it without creating a circular import - the same pattern as helpers/process_variables.py
(see its module docstring).

Transfers are modelled completely at series level, as potential events; linking occurrence
and time (experiment level only) is left to the callers (see creation/phase_functions.py),
not done here.

The import from creation/chemical_entity_functions.py (is_molecule,
get_or_create_phase_molecule, fixed_chemical_entity_id) creates no circular import despite
pointing from helpers/ to creation/: chemical_entity_functions.py itself imports nothing
from creation/phase_functions.py or from this module. It is needed in
_ensure_species_in_destination_phase, to resolve a transferred species afresh for the
DESTINATION phase instead of carrying over a phase-specific molecule instance of the
source phase unchanged.
"""

from helpers.entities import add_entity, find_entity, inherited_value, ref_id
from helpers.properties import set_property, check_type
from helpers.identifiers import claim_id, get_display_label, key_name, make_owned_id, slugify
from helpers.ontology_functions import find_entity_in_ontology, find_individuals_of_class, shorten_id
from helpers.process_variables import add_phase_process_variable, get_series_entity
from creation.chemical_entity_functions import is_molecule, get_or_create_phase_molecule, fixed_chemical_entity_id


def transfer_types(namespace_collection):
    """The cpo:TransferType individuals from the ontology, including subclasses:
    cpo:PhaseTransition is a subclass of it, so melting and friends hang off there and
    still belong in the same list.

    This used to be a list in the code with a note saying "must match the ontology" -
    exactly the kind of note that stops being true at some point.
    """
    return find_individuals_of_class("cpo:TransferType", namespace_collection, include_subclasses=True)


# The counterparts for the reverse direction stand in the ontology, at the
# cpo:TransferType individuals themselves (cpo:hasReverseTransferType) - not here in the code.
# The same pattern as hlo:determinedByTaskClass at the evidence/reference type individuals,
# which helpers/evidence_reference.py::_ask_and_link_determination_task already reads this
# way: the assignment belongs to the meaning of the individual, not to the generator, and
# then does not drift apart when somebody adds a type.


def reverse_transfer_type(transfer_type: str, namespace_collection: dict) -> str:
    """The type of the same event in the opposite direction, read from
    cpo:hasReverseTransferType on the individual in the ontology.

    Returns the type unchanged when no counterpart is recorded there. That is not an error
    but the statement "has none": a cpo:PortCrossing is crossed as a port crossing in both
    directions, and the direction lives solely in removesFromPhase/addsToPhase.
    """
    type_info = find_entity_in_ontology(transfer_type, namespace_collection)
    reverse_ref = type_info.get("hasReverseTransferType") if type_info else None
    if isinstance(reverse_ref, list):
        # owl:SymmetricProperty is declared, but is not evaluated without inference - the ontology
        # states both directions separately, so exactly one per individual.
        reverse_ref = reverse_ref[0]
    if not reverse_ref:
        return transfer_type
    return shorten_id(reverse_ref["@id"] if isinstance(reverse_ref, dict) else reverse_ref, namespace_collection)



def _ensure_species_in_destination_phase(destination_phase: dict, species_id: str, scope: str, nr: int, namespace_collection: dict, datagraph: dict, chemical_entity_library: dict):
    """Attach the transferred species to the destination phase through dcterms:hasPart.

    NOT species_id unchanged: if species_id is already a phase-specific molecule instance
    of ANOTHER phase, that would break the basic assumption of the molecule model - an
    instance belongs to exactly one phase, and its concentration only holds there.

    Instead species_id is resolved through fixed_chemical_entity_id to the phase-independent
    fixed library entry, and then resolved again with get_or_create_phase_molecule for THIS
    destination phase (creating an instance of its own where needed, exactly as
    _attach_species does for the regular composition).

    Ions, radicals and other chemical entities that are not a chebi:Molecule have no
    phase-specific instance and are referenced unchanged by their fixed ID (see is_molecule).
    """
    fixed_entity_id = fixed_chemical_entity_id(species_id, datagraph)
    fixed_entity = find_entity(chemical_entity_library, fixed_entity_id)

    if fixed_entity is not None and is_molecule(fixed_entity):
        series_destination_phase = get_series_entity(destination_phase, datagraph)
        resolved_id = get_or_create_phase_molecule(fixed_entity_id, destination_phase, scope, nr, namespace_collection, datagraph, chemical_entity_library, series_destination_phase)
    else:
        resolved_id = fixed_entity_id

    parts = destination_phase.get("dcterms:hasPart", [])
    parts = parts if isinstance(parts, list) else [parts]
    existing_ids = [p.get("@id") if isinstance(p, dict) else p for p in parts if p]
    if resolved_id not in existing_ids:
        set_property(destination_phase, "dcterms:hasPart", {"@id": resolved_id}, namespace_collection, True)


def transfer_name(transfer_type: str, species_id: str, source_phase_id: str, destination_phase_id: str,
                  datagraph: dict, chemical_entity_library: dict) -> str:
    """What a transfer is, written out: species, type and direction (step 7,
    group B) - the name part of its ID and its question-path key.

        "Hydrogen-Adsorption-from-LiquidVessel_Phase"
        "Hydrogen-Desorption-to-LiquidVessel_Phase"
        "Hydrogen-Absorption-from-GasVessel_Phase-to-LiquidVessel_Phase"

    The species by its library name, the phases by their key (without level, so a series
    transfer and its experiment performances share the name). Unique at one place, because
    two transfers of the same species, type and direction at one place are the same transfer
    (see _find_existing_transfer).
    """
    fixed_species_id = fixed_chemical_entity_id(species_id, datagraph)
    species_entity = find_entity(chemical_entity_library, fixed_species_id) if chemical_entity_library else None
    species = slugify(get_display_label(species_entity)) if species_entity else key_name(fixed_species_id)
    name = f"{species}-{transfer_type.split(':', 1)[-1]}"
    if source_phase_id:
        name += f"-from-{key_name(source_phase_id)}"
    if destination_phase_id:
        name += f"-to-{key_name(destination_phase_id)}"
    return name


def transfer_name_of(transfer: dict, datagraph: dict, chemical_entity_library: dict) -> str:
    """transfer_name, read off an existing transfer."""
    return transfer_name(ref_id(inherited_value(transfer, "cpo:hasTransferType", datagraph)), ref_id(transfer.get("cpo:transfersChemicalEntity")),
                         ref_id(transfer.get("cpo:removesFromPhase")), ref_id(transfer.get("cpo:addsToPhase")),
                         datagraph, chemical_entity_library)


def _new_transfer_entity(transfer_type: str, scope: str, location: dict, name: str, namespace_collection: dict, datagraph: dict, todo_list: list, series_transfer: dict = None):
    """The transfer entity itself. Its ID is its name at its place (make_owned_id): it lives
    where the interface or port lives, series or experiment."""
    transfer_type_class = check_type("cpo:Transfer", namespace_collection)
    transfer_id = claim_id(make_owned_id(f"Transfer_{name}", location["@id"]), datagraph, todo_list, what=f"The transfer '{name}'")

    transfer = {"@id": transfer_id, "@type": [transfer_type_class, scope]}
    # Rule 3.6: the type stands once, at the transfer that is not a performance of
    # another; an experiment transfer reads it from its series transfer through hlo:specializationOf.
    if series_transfer is None:
        set_property(transfer, "cpo:hasTransferType", {"@id": transfer_type}, namespace_collection)

    if series_transfer is not None:
        set_property(transfer, "hlo:specializationOf", series_transfer, namespace_collection)
        set_property(series_transfer, "hlo:hasSpecialization", transfer, namespace_collection, True)

    return transfer


def _set_transfer_direction_and_species(transfer: dict, species_id: str, source_phase: dict, destination_phase: dict, scope: str, nr: int, namespace_collection: dict, datagraph: dict, chemical_entity_library: dict, adds_species: bool = True):
    """Set the direction of a transfer and the chemical entity it moves.

    removesFromPhase and addsToPhase are independently optional (at least one of the two
    has to be set): adsorption has only removesFromPhase, for instance, because the
    destination is the interface occupation rather than a phase, and desorption has only
    addsToPhase.

    cpo:transfersChemicalEntity describes the chemical entity as such, not a phase-specific
    instance, and therefore points at the fixed library entry (resolved through
    fixed_chemical_entity_id) whether species_id is already a fixed entry or a
    phase-specific molecule instance. The phase-specific instances stay separate -
    dcterms:hasPart on the respective phase, resolved through
    _ensure_species_in_destination_phase - only with adds_species (port crossings, see
    create_transfer_at_interface for why interface transfers do not).
    """
    if source_phase is None and destination_phase is None:
        raise ValueError("A transfer needs at least source_phase or destination_phase.")

    fixed_species_id = fixed_chemical_entity_id(species_id, datagraph)
    set_property(transfer, "cpo:transfersChemicalEntity", {"@id": fixed_species_id}, namespace_collection)
    if source_phase is not None:
        set_property(transfer, "cpo:removesFromPhase", source_phase, namespace_collection)
    if destination_phase is not None:
        set_property(transfer, "cpo:addsToPhase", destination_phase, namespace_collection)
        if adds_species:
            _ensure_species_in_destination_phase(destination_phase, species_id, scope, nr, namespace_collection, datagraph, chemical_entity_library)


def create_transfer_at_interface(interface: dict, species_id: str, transfer_type: str, scope: str, nr: int, namespace_collection: dict, datagraph: dict, chemical_entity_library: dict, todo_list: list, local_todo_list: list, source_phase: dict = None, destination_phase: dict = None, evidence_known_cache: dict = None, series_transfer: dict = None):
    """Create a transfer whose location is an interface (cpo:occursAtInterface).

    The transfer does NOT put its species into the destination phase: it is a
    potential transfer from the rule table, and a potential transfer that fills the phase on the
    other side would start the next potential transfers from there - isopropanol "solidifying"
    into the platinum and then "subliming" from it. dcterms:hasPart of a phase is its stated
    composition (everything that can occur in it); whoever knows that the transfer happened
    names the species in the composition of the destination phase.
    """
    name = transfer_name(transfer_type, species_id, ref_id(source_phase), ref_id(destination_phase), datagraph, chemical_entity_library)
    transfer = _new_transfer_entity(transfer_type, scope, interface, name, namespace_collection, datagraph, todo_list, series_transfer)
    set_property(transfer, "cpo:occursAtInterface", interface, namespace_collection)
    set_property(interface, "cpo:hasTransfer", transfer, namespace_collection, True)
    _set_transfer_direction_and_species(transfer, species_id, source_phase, destination_phase, scope, nr, namespace_collection, datagraph, chemical_entity_library,
                                        adds_species=False)

    add_phase_process_variable(transfer, "cpo:hasFlowrate", scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache)

    add_entity(datagraph, transfer)
    return transfer


def create_transfer_at_port(port: dict, species_id: str, transfer_type: str, scope: str, nr: int, namespace_collection: dict, datagraph: dict, chemical_entity_library: dict, todo_list: list, local_todo_list: list, source_phase: dict = None, destination_phase: dict = None, evidence_known_cache: dict = None, series_transfer: dict = None):
    """Create a transfer whose location is a port (cpo:occursAtPort, for
    cpo:PortCrossing).

    Every transfer gets its OWN flowrate, not the one of the stream, for two reasons.
    First, every species of the stream phase crosses the port as a transfer of its own - in
    a solvent mixture water and isopropanol shared one single
    quantitykind:MolarFlowRate, which differs per species. Second, the same
    stream hangs at two ports (inlet and outlet), and that the same goes through
    there is an assumption, not an identity.

    Instead, like is coupled with like, and not here,
    but when both stream ends are finished (see link_stream_end_couplings in
    creation/phase_functions.py).
    """
    name = transfer_name(transfer_type, species_id, ref_id(source_phase), ref_id(destination_phase), datagraph, chemical_entity_library)
    transfer = _new_transfer_entity(transfer_type, scope, port, name, namespace_collection, datagraph, todo_list, series_transfer)
    _set_transfer_direction_and_species(transfer, species_id, source_phase, destination_phase, scope, nr, namespace_collection, datagraph, chemical_entity_library)

    add_phase_process_variable(transfer, "cpo:hasFlowrate", scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache)

    # Cumulative amount that has crossed this port so far - unlike the flowrate above,
    # which is a rate. Only at PortCrossings: a phase change at an interface is balanced
    # through the composition of the phases involved, an addition from outside, however, is
    # often measured directly (in the hydrogenation the column "H2 used", a summed-up volume
    # at 293 K and 101300 Pa).
    add_phase_process_variable(transfer, "cpo:hasTransferredVolume", scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache)

    # Deliberately the last step: cpo:occursAtPort was missing from the ontology for a long time
    # (added by now), and with a check_existence error at least direction, species and amounts
    # are set and can be inspected in case of an error.
    set_property(transfer, "cpo:occursAtPort", port, namespace_collection)

    add_entity(datagraph, transfer)
    return transfer


def _find_existing_transfer(location: dict, location_kind: str, transfer_type: str, fixed_species_id: str, source_phase: dict, destination_phase: dict, datagraph: dict):
    """Look for an existing transfer at this location with the same type, the same
    chemical entity AND the same direction (removesFromPhase/addsToPhase).

    The direction has to be part of the comparison: otherwise, in a reversible reaction,
    the reverse transfer (same type and species, swapped direction) would wrongly be taken
    for the already existing forward transfer.

    fixed_species_id is already resolved to the fixed library entry (see
    get_or_create_transfer): cpo:transfersChemicalEntity always carries a fixed ID, never a
    phase-specific instance
    (see _set_transfer_direction_and_species).
    """
    if location_kind == "interface":
        refs = location.get("cpo:hasTransfer", [])
        refs = refs if isinstance(refs, list) else [refs]
        candidate_ids = [ref_id(r) for r in refs if r]
        candidates = [find_entity(datagraph, cid) for cid in candidate_ids]
    else:
        # According to the ontology cpo:hasTransfer is declared only for interfaces, not for
        # ports - hence a direct scan here instead of an inverse property.
        candidates = [
            e for e in datagraph.get("@graph", [])
            if "cpo:Transfer" in (e.get("@type") or [])
            and ref_id(e.get("cpo:occursAtPort")) == location.get("@id")
        ]

    wanted_source_id = source_phase.get("@id") if source_phase is not None else None
    wanted_destination_id = destination_phase.get("@id") if destination_phase is not None else None

    for candidate in candidates:
        if candidate is None:
            continue
        candidate_type = ref_id(inherited_value(candidate, "cpo:hasTransferType", datagraph))
        candidate_species = ref_id(candidate.get("cpo:transfersChemicalEntity"))
        candidate_source = ref_id(candidate.get("cpo:removesFromPhase"))
        candidate_destination = ref_id(candidate.get("cpo:addsToPhase"))
        if (candidate_type == transfer_type and candidate_species == fixed_species_id
                and candidate_source == wanted_source_id and candidate_destination == wanted_destination_id):
            return candidate
    return None


def get_or_create_transfer(location: dict, location_kind: str, species_id: str, transfer_type: str, scope: str, nr: int, namespace_collection: dict, datagraph: dict, chemical_entity_library: dict, todo_list: list, local_todo_list: list, source_phase: dict = None, destination_phase: dict = None, evidence_known_cache: dict = None, series_transfer: dict = None, allow_create: bool = True):
    """Look for an existing transfer at this location (location_kind "interface" or
    "port") with the same transfer_type, the same chemical entity AND the same direction,
    and create a new one only where needed.

    Used by reaction creation (several participants or reactions may reference the same
    transfer) and for port crossings. species_id is resolved to the fixed library entry for
    the comparison (see _find_existing_transfer) - cpo:transfersChemicalEntity always
    carries a fixed ID (see _set_transfer_direction_and_species).

    allow_create=False makes the function search ONLY: when it finds nothing, it aborts
    with a message describing the missing transfer. Used by reaction creation
    (creation/reaction_functions.py::link_reaction_transfers), for a concrete reason:
    main.py first creates all phases with their interfaces and transfers - the experiment
    transfers arise there as a replay of the series transfers - and runs the reactions
    afterwards. A transfer that only comes into being there misses that replay and exists
    at series level alone; copy_reaction_transfers then finds no counterpart at experiment
    level and quietly drops the cpo:involvesTransfer link. That is exactly how a single
    missing reverse H2 transfer produced 70 instead of 72 experiment transfers, without an
    error message.
    """
    fixed_species_id = fixed_chemical_entity_id(species_id, datagraph)
    existing = _find_existing_transfer(location, location_kind, transfer_type, fixed_species_id, source_phase, destination_phase, datagraph)
    if existing is not None:
        return existing

    if not allow_create:
        # See allow_create in the docstring: a transfer newly created here would have no
        # ExperimentSpecific counterpart and the error would stay invisible. Rather fail loudly
        # and say which transfer is missing.
        direction = []
        if source_phase is not None:
            direction.append(f"removesFromPhase {source_phase.get('schema:name') or source_phase.get('@id')}")
        if destination_phase is not None:
            direction.append(f"addsToPhase {destination_phase.get('schema:name') or destination_phase.get('@id')}")
        raise ValueError(
            f"This transfer is missing and must not be created here any more:\n"
            f"    place:     {location.get('schema:name') or location.get('@id')}\n"
            f"    type:      {transfer_type}\n"
            f"    species:   {fixed_species_id}\n"
            f"    direction: {', '.join(direction) or '(none)'}\n"
            f"Transfers have to be declared when the interfaces are described "
            f"(creation/phase_functions.py::handle_transfers_for_pair_interface), not only "
            f"with the reactions - otherwise it is made only on the SeriesSpecific level and the "
            f"experiment reactions are silently left without cpo:involvesTransfer."
        )

    if location_kind == "interface":
        return create_transfer_at_interface(location, species_id, transfer_type, scope, nr, namespace_collection, datagraph, chemical_entity_library, todo_list, local_todo_list, source_phase, destination_phase, evidence_known_cache, series_transfer)
    return create_transfer_at_port(location, species_id, transfer_type, scope, nr, namespace_collection, datagraph, chemical_entity_library, todo_list, local_todo_list, source_phase, destination_phase, evidence_known_cache, series_transfer)
