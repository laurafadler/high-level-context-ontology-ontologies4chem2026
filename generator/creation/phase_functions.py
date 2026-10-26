"""
Everything needed to complete phase entities.

Phases are already written onto the todo list as placeholders while the materials are
created (see creation/material_functions.py: create_phase_placeholder). This module works
through those placeholders and adds the remaining properties (process variables,
composition, dispersion state, ...), exactly as create_material_from_todo does for
materials. Afterwards the interfaces between the phases are created as well.

As for materials and devices there are two levels (SeriesSpecific/ExperimentSpecific):
structural matters - which chemical species, which dispersion state - are carried over from
the series counterpart rather than asked again, while process variables (volume,
temperature, ...) are created afresh at both levels, with evidence and references only at
experiment level. The same as everywhere else in the project.
"""

from helpers.entities import add_entity, find_entity, resolve, inherited_value, ask_entity_choice, ask_entity_list, find_entities_by_type, ref_id, ref_ids, as_list
from helpers.properties import set_property, set_literal_property, check_type
from helpers.ontology_functions import find_individuals_of_class, quantity_kinds_of_property
from helpers.identifiers import claim_id, make_owned_id, make_member_id, generate_id_from_name, get_display_label, short_local_name, key_name, name_list, slugify, LIST_SEPARATOR
from helpers.evidence_reference import link_automatic_assumption
from helpers.todo_functions import delete_todo_entity
from helpers.process_variables import get_series_entity, add_phase_process_variable, add_specializing_actual
from helpers.value_sources import request_value_sources
from helpers.energy_fields import create_energy_field, ASKABLE_ENERGY_FIELD_TYPES
from helpers.forms import build_form, form_classes, form_class_of, form_ref
from helpers.ontology_functions import required_properties_of_class
from helpers.time_occurrence import add_occurrence
from helpers.transfer_functions import create_transfer_at_interface, get_or_create_transfer, transfer_name, transfer_name_of
from creation.material_functions import get_device_experiment_number, get_phase_state_class
from creation.chemical_entity_functions import ask_chemical_entity, is_molecule, get_or_create_phase_molecule, fixed_chemical_entity_id, search_chemical_entities_by_name
from helpers.user_io import ask_user, ask_user_list, question_path, match_option, SAME_OPTIONS
from helpers.series_statements import note_solvents_per_experiment


# ---------------------------------------------------------------------------
# Helpers: find the series counterpart and the experiment number of a phase
# ---------------------------------------------------------------------------
# get_series_entity is now generic in helpers/process_variables.py (also needed
# by material_functions.py for Stream/MaterialVolume) - only re-imported here, so
# that existing "from creation.phase_functions import get_series_entity" imports
# (e.g. reaction_functions.py) keep working unchanged.

_STABLE_INDEX_LEVEL_BY_TYPE = {
    "cpo:Environment": "environment",
    "cpo:BodyMaterial": "body_material",
}


def _stable_index_level_for_material(material_id: str, datagraph: dict) -> str:
    """Environments and device body materials (see environment_functions.py and
    device_functions.py) run under levels of their own ("environment"/"body_material")
    rather than under "material" (see stable_index_level in
    material_functions.py::create_series_material_from_fixed).

    A room is not a material in this count, and a device body material changes for a
    different reason (devices added or removed) than a freely recorded material (substances
    added or removed) - otherwise two independent causes would share one counter. Phases
    inherit this level from their material, so that "body_material:N/phase:M/..." stays
    untouched by the global material counter.
    """
    material = find_entity(datagraph, material_id) if material_id else None
    types = as_list(material.get("@type")) if material else []
    for type_name, level in _STABLE_INDEX_LEVEL_BY_TYPE.items():
        if type_name in types:
            return level
    return "material"


def get_material_experiment_number(material: dict, datagraph: dict):
    """Determine the experiment number of an experiment-specific material - either through
    its own hlo:specializationOf (see create_experiment_material) or through the device it is
    held in (device-driven contained materials, see material_todo_item_matches_experiment).

    The ID says it first (..._ExperimentSpecific_<n>): the position in the series entity's
    hlo:hasSpecialization is not the experiment once an experiment has dropped its
    specialization (drop_empty_experiment_phases).
    """
    parts = material.get("@id", "").rsplit("_ExperimentSpecific_", 1)
    if len(parts) == 2 and parts[1].isdigit():
        return int(parts[1])
    series_ref = material.get("hlo:specializationOf")
    series_id = series_ref.get("@id") if isinstance(series_ref, dict) else series_ref
    series_material = find_entity(datagraph, series_id) if series_id else None

    if series_material:
        specializations = series_material.get("hlo:hasSpecialization", [])
        if isinstance(specializations, dict):
            specializations = [specializations]
        for index, spec in enumerate(specializations):
            if spec.get("@id") == material.get("@id"):
                return index + 1

    device_ref = material.get("cpo:materialContainedIn")
    device_id = device_ref.get("@id") if isinstance(device_ref, dict) else device_ref
    device = find_entity(datagraph, device_id) if device_id else None
    if device:
        return get_device_experiment_number(device, datagraph)

    return None


def phase_matches_experiment(phase: dict, scope: str, nr: int, datagraph: dict) -> bool:
    """As material_todo_item_matches_experiment: without this check, working through
    experiment 1 would also process the phases of experiment 2 and so on, because they all
    carry the same scope "hlo:ExperimentSpecific".
    """
    if scope != "hlo:ExperimentSpecific":
        return True

    material_ref = phase.get("dcterms:isPartOf")
    material_id = material_ref.get("@id") if isinstance(material_ref, dict) else material_ref
    material = find_entity(datagraph, material_id) if material_id else None
    if not material:
        return True

    return get_material_experiment_number(material, datagraph) == nr


# ---------------------------------------------------------------------------
# Evidence/reference shortcut: ask once per series whether anything is known
# about it at all, instead of asking for evidence/reference in every experiment.
# See helpers/process_variables.py (add_phase_process_variable, imported here)
# for the implementation - it lives there so that material_functions.py can use
# it as well.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Composition: hasPart ChemicalEntity + hasConcentration ProcessVariable
# ---------------------------------------------------------------------------

# Concentration values are not optional - every molecule species gets an actual
# value (only evidence/reference for it are optional, see add_evidence/
# add_reference). Whether it is a fraction of the whole or an absolute amount is
# said by the chosen QuantityKind alone - one property (cpo:hasConcentration) is
# enough for that, a second one (the former cpo:hasComposition) was not needed.
# "MolarConcentration" does not exist in QUDT - the right name is
# AmountOfSubstanceConcentration.
# The choice is the quantity kinds the ontology allows for cpo:hasConcentration
# (cpo:valueHasQuantityKind, rule 4.4) - not a list here in the code.


def _fixed_phase_molecule_id(species_ref, datagraph: dict):
    """The species reference, IF it points at a molecule instance that a Fixed phase brings
    along itself - otherwise None.

    Such an instance exists where a library records not only which species a phase consists
    of but also how much of each: the lab air in organization_library.jsonld carries
    environment:L109_Air_Molecule_0005 with a fixed mass fraction, rather than pointing at
    the bare chem:Molecule_0005. Recognisable by the combination hlo:Fixed plus its own
    hlo:specializationOf - a bare library entry has neither (and is not in the datagraph at
    all, since molecules are referenced, not copied).
    """
    species_id = species_ref.get("@id") if isinstance(species_ref, dict) else species_ref
    instance = resolve(datagraph, species_id)
    if instance is None:
        return None
    if "hlo:Fixed" not in as_list(instance.get("@type")) or "hlo:specializationOf" not in instance:
        return None
    return species_id


def _resolve_species_by_name(species_name: str, scope: str, namespace_collection: dict, chemical_entity_library: dict, what: str) -> str:
    """The chemical entity a name from a species list stands for. A name that hits exactly
    one entity in the library is resolved without a question; otherwise the usual search runs
    under "new_species:<name>" (ask_chemical_entity)."""
    matches = search_chemical_entities_by_name(chemical_entity_library, species_name, exclude_types=["cpo:ActiveSite"])
    if len(matches) == 1:
        return matches[0]["@id"]
    with question_path("new_species", slugify(species_name)):
        return ask_chemical_entity(scope, what, namespace_collection, chemical_entity_library, exclude_types=["cpo:ActiveSite"], question_id="select_species")


def _attach_species(phase: dict, species_ref, scope: str, nr: int, namespace_collection: dict, datagraph: dict, chemical_entity_library: dict, series_phase: dict):
    """Attach a chemical species to a phase through dcterms:hasPart.

    For a chebi:Molecule it is not the fixed library entry that is linked directly, but the
    molecule instance belonging to this phase (see get_or_create_phase_molecule). Ions,
    radicals and other chemical entities that are not molecules stay referenced unchanged by
    their fixed ID - they get no series or experiment instances.
    """
    fixed_entity_id = fixed_chemical_entity_id(species_ref, datagraph)
    fixed_entity = find_entity(chemical_entity_library, fixed_entity_id)

    if fixed_entity is not None and is_molecule(fixed_entity):
        resolved_id = get_or_create_phase_molecule(
            fixed_entity_id, phase, scope, nr, namespace_collection, datagraph, chemical_entity_library,
            series_phase, fixed_instance_id=_fixed_phase_molecule_id(species_ref, datagraph))
    else:
        resolved_id = fixed_entity_id

    set_property(phase, "dcterms:hasPart", {"@id": resolved_id}, namespace_collection, True)


def _add_single_species_concentration(molecule_instance_id: str, scope: str, nr: int, namespace_collection: dict, datagraph: dict, todo_list: list, local_todo_list: list):
    """Create an explicit concentration value even for the ONLY species of a phase
    (cpo:hasConcentration, quantitykind:MoleFraction, value 1).

    RDF assumes an open world: a single hasPart does not formally mean "only this species"
    but merely "we know of no others". Without this explicit value that would stay tacit.

    The value itself was not measured; it follows purely from no other species being known -
    which is why it carries hlo:hasReferenceType hlo:Assumed rather than one of the other
    reference types. Its determination task is the entry of the assumption library
    (task:assuming_single_species_phase_is_pure), named directly by the value. Runs entirely
    without a question; the user answers nothing for it.

    At experiment level the new composition is also linked to the series composition through
    hlo:specializationOf, as everywhere else in the project - found through the
    specializationOf chain of the molecule instance itself (see get_or_create_phase_molecule),
    with no cache structure of its own as in the multi-species variant in
    add_phase_composition. There the cache is keyed on the fixed entry, because several
    species per phase have to be kept apart; here there is only the one per phase.
    """
    molecule_instance = find_entity(datagraph, molecule_instance_id)
    experiment_number = nr if scope == "hlo:ExperimentSpecific" else None

    composition_type = check_type("cpo:ProcessVariable", namespace_collection)
    composition_id = generate_id_from_name(f"Concentration_{short_local_name(molecule_instance_id)}", scope, experiment_number)
    composition = {"@id": composition_id, "@type": [composition_type, scope, "hlo:Actual"]}
    # The quantity kind at the value, not at the actual (rule 4.4, cpo:hasConcentration allows several).
    set_property(composition, "cpo:isProcessVariableOf", molecule_instance, namespace_collection)
    set_property(molecule_instance, "cpo:hasConcentration", composition, namespace_collection)

    if scope == "hlo:ExperimentSpecific":
        series_molecule = get_series_entity(molecule_instance, datagraph)
        series_composition_ref = series_molecule.get("cpo:hasConcentration") if series_molecule else None
        series_composition_id = series_composition_ref.get("@id") if isinstance(series_composition_ref, dict) else series_composition_ref
        series_composition = find_entity(datagraph, series_composition_id) if series_composition_id else None
        if series_composition:
            set_property(composition, "hlo:specializationOf", series_composition, namespace_collection)
            set_property(series_composition, "hlo:hasSpecialization", composition, namespace_collection, True)

    scalar_type = check_type("cpo:ScalarVariable", namespace_collection)
    # The first reference of the concentration, named like every other value: <Variable>_Reference_<n>
    # (make_member_id, rule 1.6 - the type is in hasReferenceType).
    scalar_id = make_member_id(composition_id, "Reference", len(ref_ids(composition.get("hlo:hasReference"))) + 1, scope, experiment_number)
    scalar = {"@id": scalar_id, "@type": [scalar_type, scope, "hlo:Reference"]}
    set_literal_property(scalar, "qudt:value", "1", "xsd:decimal", namespace_collection)
    set_property(scalar, "qudt:hasQuantityKind", "quantitykind:MoleFraction", namespace_collection)
    # A fraction has no unit - UNITLESS at the value, not at the actual (see
    # DIMENSIONLESS_QUANTITY_KINDS in helpers/units.py).
    set_property(scalar, "qudt:hasUnit", {"@id": "unit:UNITLESS"}, namespace_collection)
    set_property(scalar, "hlo:hasReferenceType", {"@id": "hlo:Assumed"}, namespace_collection)
    set_property(scalar, "hlo:isReferenceOf", composition, namespace_collection)
    set_property(composition, "hlo:hasReference", scalar, namespace_collection)
    add_entity(datagraph, scalar)
    # This value has its task too - the assumption is a fixed entry of the Assumption Library,
    # and the value names it directly, on every level; the library does not name it back
    # (rule 4.1, exception).
    link_automatic_assumption(scalar, namespace_collection)

    add_entity(datagraph, composition)


# Per experiment the chemical entities of the series that do NOT occur in it (fixed library IDs, rule 3.13).
# Set once for the series (ask_absent_species): a combinatorial series uses different
# substances per experiment (MnCl2 and the Mn/Ni product only in experiment 2). Lives for one run.
_ABSENT_SPECIES = {}


def absent_species(nr) -> set:
    """The fixed IDs of the chemical entities that do not occur in experiment nr (empty: all of the series)."""
    return _ABSENT_SPECIES.get(nr, set())


def ask_absent_species(series_phases: list, nr: int, number_experiments: int, datagraph: dict, chemical_entity_library: dict):
    """Which chemical entities of the series do not occur in experiment nr - asked once per experiment, only in a
    series with more than one experiment. Such a substance is left out of the experiment's phases (except the
    contents and bodies the library describes - a bottle of MnCl2 still holds it), and with it its transfers,
    port crossings, occupations, and the reactions it takes part in (rule 3.13)."""
    if number_experiments < 2:
        return
    fixed_ids = []
    for phase in series_phases:
        for species_ref in as_list(phase.get("dcterms:hasPart")):
            fixed_id = fixed_chemical_entity_id(species_ref, datagraph)
            if fixed_id and fixed_id not in fixed_ids and find_entity(chemical_entity_library, fixed_id) is not None:
                fixed_ids.append(fixed_id)
    if not fixed_ids:
        return
    entities = sorted((find_entity(chemical_entity_library, f) for f in fixed_ids), key=get_display_label)
    chosen = ask_entity_list(
        f"[hlo:ExperimentSpecific] Which chemical species of the series do NOT occur in Experiment {nr}? They are left "
        f"out of its phases, transfers and reactions (leave empty if all occur)",
        entities, label_fn=get_display_label, question_id="absent_species")
    _ABSENT_SPECIES[nr] = set(chosen)
    if chosen:
        print(f"[hlo:ExperimentSpecific] Not in Experiment {nr}: "
              f"{', '.join(get_display_label(find_entity(chemical_entity_library, c)) for c in chosen)}.")


# Per experiment the devices whose only part in it were streams left out by drop_empty_experiment_phases.
_DEVICES_ONLY_FOR_DROPPED = {}


def devices_only_for_dropped(nr) -> set:
    """The experiment-level IDs of the devices whose every stream in experiment nr was left out (a stock bottle of a
    substance that does not occur in it)."""
    return _DEVICES_ONLY_FOR_DROPPED.get(nr, set())


# References that do not make an entity part of what is dropped: the series entity names its specializations, a
# context names what it describes - both lose the reference, neither keeps the entity alive.
_LINKS_NOT_OWNING = {"hlo:hasSpecialization", "hlo:contextDescribedBy"}
# Links from a dropped entity to things that live on without it (its series counterpart, its material, ports).
_LINKS_NOT_OWNED = {"hlo:specializationOf", "dcterms:isPartOf", "cpo:flowsFrom", "cpo:flowsTo"}


def drop_empty_experiment_phases(phases: list, nr: int, datagraph: dict, todo_list: list, local_todo_list: list) -> list:
    """Leave out of experiment nr every phase that species_per_experiment has emptied, and every material left
    without a phase (rule 3.13): the series phase holds a substance that does
    not occur in this experiment, and nothing else - the experiment then has no such phase at all, rather than an
    empty one (Phase_Substance_R1). It runs before the interfaces of the experiment are created, so neither
    interfaces nor transfers nor port crossings come into being for what is dropped.

    Dropped with them: what only they own (values, times, form), the references to them (the series entity's
    hlo:hasSpecialization, the contexts, the ports' streams), their items of the to-do lists. The series keeps them -
    it describes what the series can contain. A device whose every stream of this experiment was dropped, and which
    holds nothing but its library content, is noted (devices_only_for_dropped): the tasks leave it out of their
    equipment in this experiment, so it is not recorded as used there.

    The questions about such a material at the experiment level have been asked before this (materials come before
    phases, and only the phases know their species): their answers stay in the answer file, unused. Asking
    absent_species before the materials would need the series compositions first - the order of the whole run
    (docs/things_to_implement_after_me.md)."""
    if not absent_species(nr):
        return phases
    graph = datagraph.get("@graph", [])
    by_id = {e["@id"]: e for e in graph}

    def emptied(phase):
        if "hlo:ExperimentSpecific" not in as_list(phase.get("@type")) or as_list(phase.get("dcterms:hasPart")):
            return False
        if _described_by_library(phase, datagraph):
            return False
        series = get_series_entity(phase, datagraph)
        return bool(series and as_list(series.get("dcterms:hasPart")))

    dropped_phases = {p["@id"] for p in phases if p is not None and emptied(p)}
    if not dropped_phases:
        return phases
    dropped = set(dropped_phases)
    materials = {ref_id(by_id[p].get("dcterms:isPartOf")) for p in dropped_phases}
    for material_id in materials:
        material = by_id.get(material_id)
        if material is not None and set(ref_ids(material.get("dcterms:hasPart"))) <= dropped_phases:
            dropped.add(material_id)

    # Who refers to whom (crate entities only), to find what nothing else holds on to.
    incoming = {}
    for entity in graph:
        for prop, value in entity.items():
            if prop.startswith("@") or prop in _LINKS_NOT_OWNING:
                continue
            for target in _refs_in(value):
                incoming.setdefault(target, set()).add(entity["@id"])
    suffix = f"_ExperimentSpecific_{nr}"
    frontier = list(dropped)
    while frontier:
        entity = by_id.get(frontier.pop())
        for prop, value in (entity or {}).items():
            if prop.startswith("@") or prop in _LINKS_NOT_OWNED:
                continue
            for target in _refs_in(value):
                if target in dropped or target not in by_id or not target.endswith(suffix):
                    continue
                if incoming.get(target, set()) <= dropped:
                    dropped.add(target)
                    frontier.append(target)

    # Ports that lose a stream - their devices are checked below.
    ports = {ref_id(by_id[m].get(p)) for m in dropped if m in by_id for p in ("cpo:flowsFrom", "cpo:flowsTo")} - {None}

    graph[:] = [e for e in graph if e["@id"] not in dropped]      # in place: others hold the list
    for entity in graph:
        for prop in [p for p in entity if not p.startswith("@")]:
            kept = _without_refs(entity[prop], dropped)
            if kept is None:
                del entity[prop]
            else:
                entity[prop] = kept
    for todo in (todo_list, local_todo_list):
        todo[:] = [item for item in todo if item.get("@id") not in dropped]

    for port_id in ports:
        port = find_entity(datagraph, port_id)
        device = find_entity(datagraph, ref_id(port.get("cpo:isPortOf"))) if port else None
        if device is not None and not _still_takes_part(device, datagraph):
            _DEVICES_ONLY_FOR_DROPPED.setdefault(nr, set()).add(device["@id"])

    names = sorted(by_id[d].get("schema:name", d) for d in dropped if d in materials or d in dropped_phases)
    print(f"[hlo:ExperimentSpecific] Experiment {nr}: left out as empty (species_per_experiment) - {', '.join(names)} "
          f"({len(dropped)} entities).")
    if devices_only_for_dropped(nr):
        print(f"[hlo:ExperimentSpecific] Experiment {nr}: no part left for {', '.join(sorted(devices_only_for_dropped(nr)))}.")
    return [p for p in phases if p is None or p["@id"] not in dropped]


def _refs_in(value):
    """The @ids a property value points to."""
    for item in as_list(value):
        if isinstance(item, dict) and "@id" in item:
            yield item["@id"]


def _without_refs(value, dropped: set):
    """The value without its references to dropped entities; None when nothing is left."""
    if isinstance(value, list):
        kept = [v for v in value if not (isinstance(v, dict) and v.get("@id") in dropped)]
        return kept or None
    if isinstance(value, dict) and value.get("@id") in dropped:
        return None
    return value


def _still_takes_part(device: dict, datagraph: dict) -> bool:
    """Whether a device (or one of its parts) still has a stream at a port, or holds a material of the experiment
    (more than the content its library entry describes - a stock bottle holds its chemical either way)."""
    stack, seen = [device["@id"]], set()
    while stack:
        current = find_entity(datagraph, stack.pop())
        if current is None or current["@id"] in seen:
            continue
        seen.add(current["@id"])
        for port in (find_entity(datagraph, p) for p in ref_ids(current.get("cpo:hasPort"))):
            if port is not None and (port.get("cpo:hasIngoingStream") or port.get("cpo:hasOutgoingStream")):
                return True
        for material in (find_entity(datagraph, m) for m in ref_ids(current.get("cpo:containsMaterial"))):
            if material is not None and not _described_by_library(material, datagraph):
                return True
        stack.extend(ref_ids(current.get("dcterms:hasPart")))
    return False


def _described_by_library(phase: dict, datagraph: dict) -> bool:
    """Whether the phase (or the series phase it specializes) comes from a library entry - the content of a
    bottle, a body, the room air: what it holds is a fact of the thing, not of the experiment."""
    current, seen = phase, set()
    while current is not None and current["@id"] not in seen:
        if "hlo:Fixed" in as_list(current.get("@type")):
            return True
        seen.add(current["@id"])
        current = resolve(datagraph, ref_id(current.get("hlo:specializationOf"))) if current.get("hlo:specializationOf") else None
    return False


def keeps_species(species_ref, nr, phases: list, datagraph: dict) -> bool:
    """Whether a transfer or occupation of this species is taken over into experiment nr: always, unless the
    species does not occur in it (absent_species) - then only where it is still in all of its phases there (a
    bottle of the library holds it whether it was used or not, rule 3.13)."""
    fixed_id = fixed_chemical_entity_id(species_ref, datagraph)
    if fixed_id not in absent_species(nr):
        return True
    present = [p for p in phases if p is not None]
    return bool(present) and all(fixed_id in {fixed_chemical_entity_id(s, datagraph) for s in as_list(p.get("dcterms:hasPart"))}
                                 for p in present)


def add_phase_composition(phase: dict, scope: str, nr: int, namespace_collection: dict, datagraph: dict, chemical_entity_library: dict, todo_list: list, local_todo_list: list, composition_kind_cache: dict = None, evidence_known_cache: dict = None, skip_additional_species: bool = False):
    """Ask for the chemical species the phase consists of (dcterms:hasPart ->
    ChemicalEntity) and create an actual concentration value for every species that is a
    chebi:Molecule (cpo:hasConcentration, always the same property - see
    the allowed kinds of cpo:hasConcentration; whether this is a fraction or an absolute amount is
    expressed by the quantity kind alone).

    Where the phase consists of a single species, this is NOT asked about. RDF assumes an
    open world: a single hasPart does not formally mean "only this species" but merely "we
    know of no others". Instead a concentration of 1 (MoleFraction) with hlo:hasReferenceType
    hlo:Assumed is created automatically (see _add_single_species_concentration below),
    without asking the user. Ions, radicals and other chemical entities that are not
    molecules get NO concentration value - there is no phase-specific instance for them to
    hang it on (see _attach_species).

    The concentration value does not hang off the phase but off the phase-specific molecule
    instance of the respective species (see get_or_create_phase_molecule);
    cpo:isProcessVariableOf accordingly points at that instance rather than at the phase.

    Which quantity kind is used per species is a structural decision - how do we want to give
    the composition at all? - and is therefore asked about only once at series level, like
    the state of matter and the dispersion state, and passed on to the corresponding
    experiment phases through composition_kind_cache (which also stores the @id of the series
    composition for that purpose) instead of being asked again for every experiment. The
    experiment composition taken over is additionally linked to its series composition through
    hlo:specializationOf, exactly as in add_phase_process_variable. evidence_known_cache
    allows the same evidence/reference shortcut as there.

    Both caches are keyed on the fixed library entry of the species rather than on the current
    molecule instance, because the instance ID differs between series and experiment level -
    each level has its own - while the fixed entry stays the same across both.

    Which species occur at all is inherited with differing strictness, depending on which
    boundary we are at:

    - Fixed -> series: the series phase takes over the species of its fixed counterpart where
      there is one, but may add further species (water in addition to the otherwise fixed room
      air of O2/N2, say, when a series involves evaporation). That keeps the fixed level
      uncluttered - a species not present there never slips automatically into every series.
    - Series -> experiment: the experiment phase ALWAYS takes over the complete species list
      of its series phase one to one, with no way to add further ones. Where a species really
      does not occur in a particular experiment, that is expressed through a composition value
      of (nearly) 0 rather than by leaving the species out.

    (The fixed level for materials and phases does not exist yet - without a fixed counterpart
    the series level behaves as before and asks everything from scratch.)

    Which species exist at all (name, CAS/SMILES/InChI) is managed centrally through
    ask_chemical_entity (see chemical_entity_functions.py) - chosen from, or created in, the
    chemical_entity_library.

    Where a species is a chebi:Molecule, the dcterms:hasPart on this phase does NOT hang off
    the fixed library entry directly but off the molecule instance belonging to exactly this
    phase and its scope (see get_or_create_phase_molecule in chemical_entity_functions.py) -
    which is what allows concentration and partial molar volume to be attached unambiguously
    per phase later. Ions, radicals and other chemical entities that are not molecules stay
    referenced unchanged by their fixed ID (see _attach_species).
    """
    # get_series_entity simply returns the counterpart linked by hlo:specializationOf,
    # whatever the scope - for a SeriesSpecific phase that would be (once there is one)
    # its Fixed phase, for an ExperimentSpecific phase its series phase.
    parent_phase = get_series_entity(phase, datagraph)

    parent_species = parent_phase.get("dcterms:hasPart") if parent_phase else None
    if "dcterms:hasPart" not in phase and parent_species:
        # Chemical species are structural -> taken over from the counterpart above.
        species_list = parent_species if isinstance(parent_species, list) else [parent_species]
        if scope == "hlo:ExperimentSpecific" and not _described_by_library(phase, datagraph):
            # A substance that does not occur in this experiment is left out (rule 3.13).
            species_list = [s for s in species_list if fixed_chemical_entity_id(s, datagraph) not in absent_species(nr)]
        for species_ref in species_list:
            _attach_species(phase, species_ref, scope, nr, namespace_collection, datagraph, chemical_entity_library, parent_phase)

    # Adding further species: always possible on the series level (also when inherited
    # from Fixed), on the experiment level only when there was no inherited species
    # list at all (see the docstring above). Exception: body material phases
    # (skip_additional_species, see complete_phase) - their composition (glass,
    # stainless steel, ...) is fixed for good by the Fixed entity, so nobody is asked
    # for further species.
    if not skip_additional_species and (scope == "hlo:SeriesSpecific" or "dcterms:hasPart" not in phase):
        inherited_species_ids = _species_in_phase(phase)
        already_note = ""
        if inherited_species_ids:
            inherited_names = ", ".join(species_label(sid, chemical_entity_library, datagraph) for sid in inherited_species_ids)
            already_note = f" (already includes {inherited_names})"

        # The species as one list of names instead of "another one?" with a counter (step 7,
        # group A). A name that hits exactly one entity of the library is resolved by that;
        # only otherwise the usual search runs - under "new_species:<name>", not under
        # "species", so that it does not coincide with the concentration questions per species.
        names = ask_user(
            f"[{scope}] Which further chemical species does {phase_label(phase)}{already_note} contain? "
            f"Their names as in the chemical entity library, separated by ';' (leave empty if none)",
            answer_type=name_list, question_id="species_names"
        )
        for species_name in names:
            species_id = _resolve_species_by_name(species_name, scope, namespace_collection, chemical_entity_library,
                                                  f"chemical species '{species_name}' in {phase_label(phase)}")
            _attach_species(phase, {"@id": species_id}, scope, nr, namespace_collection, datagraph, chemical_entity_library, parent_phase)

    # For the rest of this function (reuse of the QuantityKind, specializationOf of the
    # composition values) series_phase stays limited to the real series phase as before -
    # the Fixed->Series behaviour above concerns only the species list itself, not yet the
    # composition values.
    series_phase = parent_phase if scope == "hlo:ExperimentSpecific" else None

    # Composition values are asked afresh on both levels (like volume/temperature),
    # because the actual fractions can differ per experiment. If the phase consists of
    # a single species only, NOTHING is asked (see _add_single_species_concentration -
    # value 1/hlo:Assumed instead of a question). Only once a second species is added
    # is the composition asked for all species of the phase.
    species_entries = phase.get("dcterms:hasPart", [])
    species_entries = species_entries if isinstance(species_entries, list) else [species_entries]

    if len(species_entries) < 2:
        # A single species here only means "one so far": a transfer can still bring a second
        # one into the phase. The assumption "pure, concentration 1" is therefore only made in
        # top_up_phase_concentrations, once the composition after the transfers is settled.
        return

    for species_ref in species_entries:
        with question_path("species", _species_key(species_ref, datagraph, chemical_entity_library)):
            _add_species_concentration(
                phase, species_ref, scope, nr, namespace_collection, datagraph, chemical_entity_library,
                todo_list, local_todo_list, series_phase, composition_kind_cache, evidence_known_cache
            )


def _species_key(species_ref, datagraph: dict, chemical_entity_library: dict) -> str:
    """Question-path key of a species in a phase: its library name (step 7,
    group B) - not its position in dcterms:hasPart, which moved whenever a species was
    added in front of it."""
    fixed_entity_id = fixed_chemical_entity_id(species_ref, datagraph)
    fixed_entity = find_entity(chemical_entity_library, fixed_entity_id)
    return slugify(get_display_label(fixed_entity)) if fixed_entity else key_name(fixed_entity_id)


def _add_species_concentration(phase: dict, species_ref, scope: str, nr: int, namespace_collection: dict, datagraph: dict, chemical_entity_library: dict, todo_list: list, local_todo_list: list, series_phase: dict, composition_kind_cache: dict = None, evidence_known_cache: dict = None):
    """Create the concentration value for ONE species of a multi-component phase - linked to
    the series counterpart on the experiment level, offered in the species list (the quantity
    kind is asked for each value, rule 4.4), plus
    evidence/reference.

    Split out of add_phase_composition because top_up_phase_concentrations needs the same
    logic after the fact, for species that only entered the phase through a transfer.

    The caller sets the question_path segment ("species", _species_key(...)), so that both
    callers ask about the same species under the same key.
    """
    molecule_instance_id = species_ref.get("@id") if isinstance(species_ref, dict) else species_ref

    # Only a chebi:Molecule gets a concentration value - ions, radicals and other
    # ChemicalEntities have no phase-specific exemplar it could hang on
    # (see _attach_species/is_molecule) and are left alone here.
    fixed_entity_id = fixed_chemical_entity_id(species_ref, datagraph)
    fixed_entity = find_entity(chemical_entity_library, fixed_entity_id)
    if fixed_entity is None or not is_molecule(fixed_entity):
        return

    molecule_instance = find_entity(datagraph, molecule_instance_id)

    # Evidence/reference per list (helpers/value_sources.py). The concentration has always been
    # asked without a segment of its own, directly in the segment of its species - it stays there,
    # and on the series level it only knows "known in the experiments?", no value for the whole
    # series. The quantity kind is asked at the single value (rule 4.4), not beforehand: the
    # concentration is ONE entry in the list of the species.
    if scope == "hlo:SeriesSpecific":
        gate_key = (phase["@id"], f"composition:{fixed_entity_id}")
    else:
        gate_key = (series_phase["@id"], f"composition:{fixed_entity_id}") if series_phase else None

    def _offer(composition: dict):
        request_value_sources(
            composition, molecule_instance, scope, nr, namespace_collection, datagraph, todo_list, local_todo_list,
            quantity="concentration", offer_at_series=False,
            gate_key=gate_key if evidence_known_cache is not None else None,
            evidence_known_cache=evidence_known_cache,
            quantity_kind_options=quantity_kinds_of_property("cpo:hasConcentration", namespace_collection),
        )

    # If the exemplar above carries a FIXED concentration value from the library (room air:
    # mass fraction of oxygen and nitrogen), the series level gets an empty actual of its own that
    # specializes it (helpers/process_variables.py: add_specializing_actual), and offers it all the
    # same like any concentration (rule 4.2). The experiment level then takes the normal
    # way below and specializes the series. Mass and amount of substance of the species are not
    # affected - they depend on the size of the room, not on the composition.
    parent_molecule = get_series_entity(molecule_instance, datagraph)
    inherited_ref = parent_molecule.get("cpo:hasConcentration") if parent_molecule else None
    inherited = resolve(datagraph, ref_id(inherited_ref)) if inherited_ref else None
    if inherited is not None and "hlo:Fixed" in (inherited.get("@type") or []):
        own_id = generate_id_from_name(f"Concentration_{short_local_name(molecule_instance_id)}", scope,
                                       nr if scope == "hlo:ExperimentSpecific" else None)
        composition = add_specializing_actual(molecule_instance, "cpo:hasConcentration", inherited, own_id, scope, nr,
                                              namespace_collection, datagraph)
        if composition_kind_cache is not None:
            composition_kind_cache[(phase["@id"], fixed_entity_id)] = {"composition_id": own_id}
        _offer(composition)
        _add_species_amounts(molecule_instance, scope, nr, namespace_collection, datagraph,
                             todo_list, local_todo_list, evidence_known_cache)
        return

    # The series concentration of the same species, which the experiment specializes.
    cached = None
    if composition_kind_cache is not None and series_phase is not None:
        cached = composition_kind_cache.get((series_phase["@id"], fixed_entity_id))

    composition_type = check_type("cpo:ProcessVariable", namespace_collection)
    experiment_number = nr if scope == "hlo:ExperimentSpecific" else None
    composition_id = generate_id_from_name(
        f"Concentration_{short_local_name(molecule_instance_id)}", scope, experiment_number
    )

    composition = {
        "@id": composition_id,
        "@type": [composition_type, scope, "hlo:Actual"]
    }
    # No quantity kind at the actual: cpo:hasConcentration allows several, the kind stands at
    # each value (rule 4.4).
    set_property(composition, "cpo:isProcessVariableOf", molecule_instance, namespace_collection)
    set_property(molecule_instance, "cpo:hasConcentration", composition, namespace_collection)

    if cached is not None:
        # Linked with the series composition, just like the other PVs (see
        # add_phase_process_variable) - every experiment composition still remains an
        # entity of its own, created afresh, with its own evidence/reference values.
        series_composition = find_entity(datagraph, cached["composition_id"])
        if series_composition:
            set_property(composition, "hlo:specializationOf", series_composition, namespace_collection)
            set_property(series_composition, "hlo:hasSpecialization", composition, namespace_collection, True)
    elif composition_kind_cache is not None and scope == "hlo:SeriesSpecific":
        composition_kind_cache[(phase["@id"], fixed_entity_id)] = {"composition_id": composition_id}

    _offer(composition)

    add_entity(datagraph, composition)

    _add_species_amounts(molecule_instance, scope, nr, namespace_collection, datagraph,
                         todo_list, local_todo_list, evidence_known_cache)


def _add_species_amounts(molecule_instance: dict, scope: str, nr: int, namespace_collection: dict, datagraph: dict, todo_list: list, local_todo_list: list, evidence_known_cache: dict = None):
    """Mass and amount of substance of ONE species in ONE phase.

    Both are time-dependent and usually unknown - they are offered all the same, because that
    is exactly what an analysis delivers (the mass of a substance at the start and at the
    end), and because the molar mass from the library allows further calculation from them.
    The same mechanics as for every other quantity: without a value it costs two "no" at
    series level and nothing at all after that (see ask_evidence_known_at_series_level).

    Split out of _add_species_concentration so that a species whose concentration is taken
    over from a Fixed library value reaches the same two quantities - they are independent of
    the composition (they depend on how much of the phase there is).

    Context Molecule/Space (Molecule_Space_R3/R4): how much
    of the species there is in its phase says where it is, not what it is - like the
    concentration. A pure phase goes through _add_pure_species_amounts instead.
    """
    for property_name in ("cpo:hasMass", "cpo:hasAmountOfSubstance"):
        add_phase_process_variable(
            molecule_instance, property_name, scope, nr,
            namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache
        )


def _add_pure_species_amounts(phase: dict, molecule_instance: dict, scope: str, nr: int, namespace_collection: dict, datagraph: dict, todo_list: list, local_todo_list: list, evidence_known_cache: dict = None):
    """Mass and amount of substance of the ONLY species of a pure phase.

    The mass of the species is the mass of the phase: the molecule points at the very Actual of
    the phase (cpo:hasMass) - the same pattern as a cavity sharing the Actuals of its hollow
    form. The amount of substance is the
    molecule's own Actual, since the phase has none (Molecule_Space_R3/R4)."""
    phase_mass = find_entity(datagraph, ref_id(phase.get("cpo:hasMass")))
    if phase_mass is not None and "cpo:hasMass" not in molecule_instance:
        set_property(molecule_instance, "cpo:hasMass", phase_mass, namespace_collection)
    add_phase_process_variable(
        molecule_instance, "cpo:hasAmountOfSubstance", scope, nr,
        namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache
    )


def top_up_phase_concentrations(phases: list, scope: str, nr: int, namespace_collection: dict, datagraph: dict, chemical_entity_library: dict, todo_list: list, local_todo_list: list, evidence_known_cache: dict = None, composition_kind_cache: dict = None, solvent_cache: dict = None):
    """Add the concentrations for species that only entered a phase AFTER the phases were
    completed - namely through the cpo:addsToPhase of a transfer (see
    helpers/transfer_functions.py::_ensure_species_in_destination_phase).

    Also the place where a phase with a single species is declared pure (concentration
    1, hlo:Assumed, _add_single_species_concentration) - only here, once the transfers have
    run, is it known that no second species came in - earlier, a transfer adding a species
    afterwards would leave the first one at an assumed 1 beside a second one.

    Background: complete_all_phases asks about all phases first and creates the interfaces
    and their transfers afterwards. A desorption into the liquid phase therefore enters its
    product after the composition of that phase has already been asked about. Without this
    follow-up the series phase would be left with molecules that have no
    cpo:hasConcentration - which is exactly what Molecule_Space_R2 reports - while the
    experiment copies do get one, because they see the grown species list from the start.

    That a species only arrives through a potential transfer does not mean it is there from
    the beginning: the value may be 0. That is precisely the purpose of the
    evidence/reference layer - the concentration of RDEt at the start is demonstrably 0,
    without the species having to disappear from the phase.

    The question path is the same as in complete_phases_from_todo/add_phase_composition:
    species:<name>, whichever of the two asks.
    """
    phases_by_material = {}
    for phase in phases:
        material_ref = phase.get("dcterms:isPartOf")
        material_id = material_ref.get("@id") if isinstance(material_ref, dict) else material_ref
        phases_by_material.setdefault(material_id, []).append(phase)

    for material_id, material_phases in phases_by_material.items():
        stable_level = _stable_index_level_for_material(material_id, datagraph)
        with question_path(stable_level, key_name(material_id)):
            for phase in material_phases:
                # Fields of radioactive species that only a transfer brought into the phase (water
                # that evaporates into the gas phase): complete_phase did not know them yet. Without
                # this call the species would get its field only in the experiment - without a template
                # at the series (rule 7c.1). Does nothing where the field exists.
                with question_path("phase", key_name(phase["@id"])):
                    add_molecule_energy_fields(phase, scope, nr, namespace_collection, datagraph, chemical_entity_library, todo_list, local_todo_list, evidence_known_cache)
                species_entries = phase.get("dcterms:hasPart", [])
                species_entries = species_entries if isinstance(species_entries, list) else [species_entries]
                if len(species_entries) == 1:
                    # Now the composition is settled: if it stays at one species, the phase is
                    # pure (concentration 1, hlo:Assumed) - see add_phase_composition.
                    species_ref = species_entries[0]
                    molecule_instance_id = species_ref.get("@id") if isinstance(species_ref, dict) else species_ref
                    molecule_instance = find_entity(datagraph, molecule_instance_id)
                    fixed_entity = find_entity(chemical_entity_library, fixed_chemical_entity_id(species_ref, datagraph))
                    if (fixed_entity is not None and is_molecule(fixed_entity) and molecule_instance is not None
                            and "cpo:hasConcentration" not in molecule_instance):
                        _add_single_species_concentration(molecule_instance_id, scope, nr, namespace_collection, datagraph, todo_list, local_todo_list)
                    if fixed_entity is not None and is_molecule(fixed_entity) and molecule_instance is not None:
                        # Question path as for the amounts in the multi-species case (_add_species_amounts).
                        with question_path("phase", key_name(phase["@id"])), \
                                question_path("species", _species_key(species_ref, datagraph, chemical_entity_library)):
                            _add_pure_species_amounts(phase, molecule_instance, scope, nr, namespace_collection, datagraph,
                                                      todo_list, local_todo_list, evidence_known_cache)
                    continue
                if len(species_entries) < 2:
                    continue

                series_phase = get_series_entity(phase, datagraph) if scope == "hlo:ExperimentSpecific" else None
                with question_path("phase", key_name(phase["@id"])):
                    # Only here is it certain that the phase is a mixture (the same place at which a phase
                    # with one species becomes pure) - so only here the question about the solvent, before
                    # the concentrations.
                    if solvent_cache is not None:
                        add_phase_solvents(phase, species_entries, scope, namespace_collection, datagraph,
                                           chemical_entity_library, solvent_cache)
                    for species_ref in species_entries:
                        molecule_instance_id = species_ref.get("@id") if isinstance(species_ref, dict) else species_ref
                        molecule_instance = find_entity(datagraph, molecule_instance_id)
                        if molecule_instance is None or "cpo:hasConcentration" in molecule_instance:
                            continue
                        with question_path("species", _species_key(species_ref, datagraph, chemical_entity_library)):
                            _add_species_concentration(
                                phase, species_ref, scope, nr, namespace_collection, datagraph, chemical_entity_library,
                                todo_list, local_todo_list, series_phase, composition_kind_cache, evidence_known_cache
                            )


# ---------------------------------------------------------------------------
# Solvents: cpo:hasSolvent (rule 3.12)
# ---------------------------------------------------------------------------

def add_phase_solvents(phase: dict, species_entries: list, scope: str, namespace_collection: dict, datagraph: dict,
                       chemical_entity_library: dict, solvent_cache: dict):
    """Ask which species of a liquid mixture act as its solvent, and link them with cpo:hasSolvent
    (rule 3.12).

    Only for a liquid phase with at least two species - a pure liquid has no solvent - and only
    once its species list is final (top_up_phase_concentrations, after the transfers). The values
    are the phase's own species records of the same level, which dcterms:hasPart names as well
    (rule 3.1: structural links point to the copies of their own level). Several values for a
    mixture; an empty answer means not known, and nothing is inferred.

    Whether the solvent is the same in every experiment is asked at the series (rule 7c.3): Yes
    asks the solvents once there, and every experiment phase names its own records of the same
    species without a question; No and "Not known yet" ask per experiment, and the series names
    every solvent used only when it is completed (helpers/series_statements.py,
    hoist_on_completion - before that another experiment could still add one, rule 7c.6).
    solvent_cache holds the series answer per series phase for the experiments of this run.

    The libraries never name a solvent, not even for the content of a bottle: whether a mixture
    serves as solvent is decided by its use in a series, so it is asked in every crate.
    """
    if get_phase_state_class(phase) != "cpo:LiquidPhase" or "cpo:hasSolvent" in phase:
        return
    by_label = {}
    for species_ref in species_entries:
        fixed_entity_id = fixed_chemical_entity_id(species_ref, datagraph)
        fixed_entity = find_entity(chemical_entity_library, fixed_entity_id)
        by_label[get_display_label(fixed_entity) if fixed_entity else key_name(fixed_entity_id)] = ref_id(species_ref)

    if scope == "hlo:SeriesSpecific":
        same = ask_user(f"[{scope}] Is the solvent of {phase_label(phase)} the same in every experiment?", SAME_OPTIONS,
                        question_id="same_solvent_across_experiments")
        solvent_cache[phase["@id"]] = same
        if same != "Yes":
            note_solvents_per_experiment(phase)
            return
    else:
        series_phase = get_series_entity(phase, datagraph)
        if series_phase is not None and solvent_cache.get(series_phase["@id"]) == "Yes":
            # The same substances as at the series, but the own exemplars of this level; an ion without
            # exemplars of its own stands on every level with its library ID.
            series_solvents = set(ref_ids(series_phase.get("cpo:hasSolvent")))
            for species_id in by_label.values():
                species = find_entity(datagraph, species_id)
                parent = ref_id(species.get("hlo:specializationOf")) if species and species.get("hlo:specializationOf") else None
                if parent in series_solvents or species_id in series_solvents:
                    set_property(phase, "cpo:hasSolvent", {"@id": species_id}, namespace_collection, True)
            return

    chosen = ask_user_list(
        f"[{scope}] Which species of {phase_label(phase)} act as its solvent? Several for a solvent mixture",
        list(by_label), question_id="solvents")
    for label in chosen:
        set_property(phase, "cpo:hasSolvent", {"@id": by_label[label]}, namespace_collection, True)


# ---------------------------------------------------------------------------
# Dispersion state: hasDispersionState (+ hasDispersedPhaseSizeDistribution)
# ---------------------------------------------------------------------------

# Which subproperty of hasDispersedPhaseSizeDistribution is used follows automatically
# from the state of matter of the dispersed phase itself (solid -> particles,
# liquid -> droplets, gaseous -> bubbles).
DISPERSED_SIZE_DISTRIBUTION_PROPERTY = {
    "cpo:SolidPhase": "cpo:hasParticleSizeDistribution",
    "cpo:LiquidPhase": "cpo:hasDropletSizeDistribution",
    "cpo:GasPhase": "cpo:hasBubbleSizeDistribution",
}


def add_dispersion_state(phase: dict, scope: str, nr: int, namespace_collection: dict, datagraph: dict, todo_list: list, local_todo_list: list, evidence_known_cache: dict = None):
    """By the ontology cpo:hasDispersionState points directly at cpo:Continuous or
    cpo:Dispersed, without a wrapper entity.

    Where the phase is dispersed, the size distribution process variable matching its state
    of matter is created as well (see DISPERSED_SIZE_DISTRIBUTION_PROPERTY).
    """
    if "cpo:hasDispersionState" in phase:
        return

    # Structural (usually does not change between experiments, nor between Fixed and
    # series) -> taken over from the counterpart above instead of asked. Independent of
    # the scope, so that this also works for a Fixed phase (e.g. the glass of a device
    # body, see device_library.jsonld) already on the SeriesSpecific level, not only
    # SeriesSpecific -> ExperimentSpecific. Rule 3.6: the state stands once,
    # where it is first said; a level below reads it through hlo:specializationOf and does not repeat it.
    series_phase = get_series_entity(phase, datagraph)
    inherited = ref_id(inherited_value(series_phase, "cpo:hasDispersionState", datagraph)) if series_phase else None

    if inherited:
        dispersion_value = inherited
    else:
        dispersion_value = ask_user(f"[{scope}] Is {phase_label(phase)} a continuous or a dispersed phase?", ["cpo:Continuous", "cpo:Dispersed"], question_id="dispersion_state")
        set_property(phase, "cpo:hasDispersionState", {"@id": dispersion_value}, namespace_collection)

    if dispersion_value == "cpo:Dispersed":
        distribution_property = DISPERSED_SIZE_DISTRIBUTION_PROPERTY.get(
            get_phase_state_class(phase), "cpo:hasDispersedPhaseSizeDistribution"
        )
        add_phase_process_variable(
            phase, distribution_property, scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache
        )


# ---------------------------------------------------------------------------
# Energy field: permanent magnet, ferrofluid, charged powder, plasma, ...
# ---------------------------------------------------------------------------

def add_phase_energy_field(phase: dict, scope: str, nr: int, namespace_collection: dict, datagraph: dict, todo_list: list, local_todo_list: list, evidence_known_cache: dict = None):
    """Ask which types of energy field a phase can create on its own - a permanent magnet, a
    ferrofluid, a charged powder, a plasma - as one list, empty for none, mirroring the
    question for devices (see device_functions.py). Creates one field per type and returns
    them.

    Where the phase has a fixed counterpart (the body material of a device, see
    device_library.jsonld), the question is only asked when
    cpo:canCreateEnergyField=true is recorded there; where the flag is missing or false, as
    it currently is for every body material, nothing is asked at all. Without a fixed
    counterpart the question is always asked, as before.

    In either case only once, at series level: at experiment level this is carried over
    structurally from the series counterpart rather than asked again.

    Where the question is put to the user for a phase without a fixed counterpart, the answer is
    also written onto the phase as cpo:canCreateEnergyField (true when the list names a type) - no
    extra question, just the answer kept; where the fixed counterpart says it, the flag stays there
    (rule 3.6). Without the
    flag, Phase_Energy_R4 cannot tell whether there is deliberately no field or whether it
    was forgotten. In the branches that do not ask at all, it is not set either: on the
    experiment level and for a body material phase the
    specializationOf path of the shape supplies the flag of the predecessor, a second entry would only be
    a copy that can drift apart.
    """
    # Several fields per phase, one per type (see create_energy_field).
    if scope == "hlo:ExperimentSpecific":
        series_phase = get_series_entity(phase, datagraph)
        if series_phase is None:
            return []
        field_types = []
        for series_field_ref in as_list(series_phase.get("cpo:hasEnergyField")):
            series_field = find_entity(datagraph, ref_id(series_field_ref))
            if series_field is not None and ref_id(series_field.get("cpo:hasEnergyFieldType")):
                field_types.append(ref_id(series_field.get("cpo:hasEnergyFieldType")))
    else:
        fixed_phase = get_series_entity(phase, datagraph)
        if fixed_phase is not None and "hlo:Fixed" in fixed_phase.get("@type", []) and not fixed_phase.get("cpo:canCreateEnergyField"):
            return []

        # The capability, not the occurrence: whether the field occurred in an experiment is said by
        # its occurrence (create_energy_field). A list, empty for "none", as for the device.
        field_types = ask_user_list(f"[{scope}] Which types of energy field can {phase_label(phase)} generate on its own (e.g. a magnet, a charged powder, a plasma)?",
                                    list(ASKABLE_ENERGY_FIELD_TYPES.values()), question_id="energy_field_types")
        # The flag stands once, where it is first said (rule 3.6, hlo:Literal_Once_CanCreateEnergyField_Shape):
        # where the library entry of the phase already says it, the series phase reads it through
        # hlo:specializationOf and does not repeat it - as for devices, which never write it into the crate.
        if fixed_phase is None or "hlo:Fixed" not in fixed_phase.get("@type", []):
            set_property(phase, "cpo:canCreateEnergyField", bool(field_types), namespace_collection)

    fields = [create_energy_field(phase, field_type, scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache)
              for field_type in field_types]
    return [field for field in fields if field is not None]


def add_molecule_energy_fields(phase: dict, scope: str, nr: int, namespace_collection: dict, datagraph: dict, chemical_entity_library: dict, todo_list: list, local_todo_list: list, evidence_known_cache: dict = None):
    """Give every molecule of the phase whose library entry is radioactive
    (cpo:isRadioactive = true) its own ionizing radiation field on this level, specializing
    the field of the library entry (see add_ionizing_radiation_field) - the same pattern as
    the fields of devices and phases. Nothing is asked for the field itself; its strength and
    occurrence get their usual value lists (create_energy_field)."""
    # Exemplars have levels (Molecule_Energy_R1 asks for the field directly at the exemplar, rule 7.1).
    for species_ref in as_list(phase.get("dcterms:hasPart")):
        molecule = find_entity(datagraph, ref_id(species_ref))
        if molecule is None:
            continue
        fixed_entity = find_entity(chemical_entity_library, fixed_chemical_entity_id(species_ref, datagraph))
        if fixed_entity is None or fixed_entity.get("cpo:isRadioactive") not in (True, "true"):
            continue

        library_fields = [find_entity(chemical_entity_library, ref_id(ref)) for ref in as_list(fixed_entity.get("cpo:hasEnergyField"))]
        library_fields = [field for field in library_fields if field is not None]
        with question_path("species", _species_key(species_ref, datagraph, chemical_entity_library)):
            if not library_fields:
                create_energy_field(molecule, "cpo:IonizingRadiation", scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache)
            for library_field in library_fields:
                create_energy_field(molecule, ref_id(library_field.get("cpo:hasEnergyFieldType")), scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache,
                                    library_field=library_field if scope == "hlo:SeriesSpecific" else None, library=chemical_entity_library)


# ---------------------------------------------------------------------------
# Form: every phase gets one of its own
# ---------------------------------------------------------------------------

def _reaches_fixed(phase: dict, datagraph: dict) -> bool:
    """Whether the phase reaches an hlo:Fixed entity up the hlo:specializationOf chain.

    True for the body material phases of a device and for the air of a room - everything that
    comes out of a library rather than out of this experiment. The whole chain matters, not the
    first step: an experiment phase reaches its Fixed counterpart only through its series phase.
    """
    seen = set()
    current = phase
    while current is not None and current["@id"] not in seen:
        if "hlo:Fixed" in as_list(current.get("@type")):
            return True
        seen.add(current["@id"])
        current = resolve(datagraph, ref_id(current.get("hlo:specializationOf")))
    return False


def _is_dispersed(phase: dict, datagraph: dict) -> bool:
    """Whether the phase is dispersed (cpo:hasDispersionState cpo:Dispersed), read up the
    hlo:specializationOf chain - the state is recorded where it is asked."""
    seen, current = set(), phase
    while current is not None and current["@id"] not in seen:
        if ref_id(current.get("cpo:hasDispersionState")) == "cpo:Dispersed":
            return True
        seen.add(current["@id"])
        current = resolve(datagraph, ref_id(current.get("hlo:specializationOf"))) if current.get("hlo:specializationOf") else None
    return False


# Dimensions of a cavity that a phase does NOT share: its height (the filling level is a quantity
# of its own), its volumes (the volume of the phase is that of its form) and the aspect ratios.
_NOT_SHARED_WITH_CAVITY = ("cpo:hasHeight", "cpo:hasOuterVolume", "cpo:hasInnerVolume")


def _cavity_filled_by(phase: dict, datagraph: dict):
    """The cavity form a phase fills, or None.

    A continuous gas or liquid phase in a device takes the shape of the device's cavity on its
    own level - the liquid in a vessel, the gas above it, the coolant in the gap of a jacket.
    A solid phase keeps its own shape, a dispersed one (bubbles, particles) has no single shape
    at all, and a phase outside a device has no cavity to fill.
    """
    types = as_list(phase.get("@type"))
    if not any(t in types for t in ("cpo:GasPhase", "cpo:LiquidPhase")) or _is_dispersed(phase, datagraph):
        return None
    material = find_entity(datagraph, ref_id(phase.get("dcterms:isPartOf")))
    device = find_entity(datagraph, ref_id(material.get("cpo:materialContainedIn"))) if material else None
    device_form = find_entity(datagraph, ref_id(device.get("cpo:definesForm"))) if device else None
    return find_entity(datagraph, ref_id(device_form.get("cpo:hasCavityForm"))) if device_form else None


def _build_asked_phase_form(phase: dict, scope: str, nr: int, namespace_collection: dict, datagraph: dict):
    """The form of a phase whose shape cannot be derived from a device: its class is asked once,
    at series level (a required choice among the form classes), and the experiments take it
    over. Every dimension is the phase's own; only its volume is the phase's hasVolume."""
    parent_phase = get_series_entity(phase, datagraph)
    parent_form = find_entity(datagraph, ref_id(form_ref(parent_phase))) if parent_phase else None
    parent_class = form_class_of(parent_form) if parent_form else None
    if scope == "hlo:ExperimentSpecific" and parent_class:
        form_class = parent_class
    else:
        form_class = ask_user(
            f"[{scope}] Which shape does {phase_label(phase)} have? It cannot be derived from a device "
            f"(a solid phase, or a phase not held by a device) - the class decides which dimensions it gets.",
            form_classes(namespace_collection, hollow=False), question_id="form_class")
    shared = {}
    volume = find_entity(datagraph, ref_id(phase.get("cpo:hasVolume")))
    if volume is not None:
        shared["cpo:hasOuterVolume"] = volume
    experiment_number = nr if scope == "hlo:ExperimentSpecific" else None
    return build_form(phase, "cpo:definesForm", form_class, scope, nr, namespace_collection, datagraph, form_id=generate_id_from_name(f"Form_{short_local_name(phase['@id'])}", scope, experiment_number),
                      shared=shared, parent_form=parent_form)


def _build_phase_form_from_cavity(phase: dict, cavity: dict, scope: str, nr: int, namespace_collection: dict, datagraph: dict):
    """The form of a phase that fills a cavity: of the cavity's class, sharing its cross-section
    (the diameter of the vessel is the diameter of the liquid in it - the same Actual, by
    definition) and taking the phase's own volume as the volume of its form. The height - the
    fill level - and the aspect ratio are the phase's own, empty until a value is recorded."""
    cavity_class = form_class_of(cavity)
    shared = {}
    for property_name, _ in required_properties_of_class(cavity_class, namespace_collection):
        if property_name in cavity and property_name not in _NOT_SHARED_WITH_CAVITY and not property_name.endswith("Ratio"):
            shared[property_name] = find_entity(datagraph, ref_id(cavity[property_name]))
    volume = find_entity(datagraph, ref_id(phase.get("cpo:hasVolume")))
    if volume is not None:
        shared["cpo:hasOuterVolume"] = volume
    parent_phase = get_series_entity(phase, datagraph)
    parent_form = find_entity(datagraph, ref_id(form_ref(parent_phase))) if parent_phase else None
    experiment_number = nr if scope == "hlo:ExperimentSpecific" else None
    return build_form(phase, "cpo:definesForm", cavity_class, scope, nr, namespace_collection, datagraph, form_id=generate_id_from_name(f"Form_{short_local_name(phase['@id'])}", scope, experiment_number),
                      shared=shared, parent_form=parent_form)


def add_solid_structure(phase: dict, scope: str, namespace_collection: dict, datagraph: dict):
    """Ask for the internal structure of a solid phase (cpo:hasSolidStructure: crystalline,
    amorphous, semi-crystalline) - a term, asked once at series level and read by the
    experiments through hlo:specializationOf (rule 2). The body material of a device brings it
    from the library."""
    if "cpo:SolidPhase" not in as_list(phase.get("@type")) or scope != "hlo:SeriesSpecific":
        return None
    if _reaches_fixed(phase, datagraph) or "cpo:hasSolidStructure" in phase:
        return None
    answer = ask_user(f"[{scope}] What is the internal structure of {phase_label(phase)}?",
                      ["cpo:Crystalline", "cpo:Amorphous", "cpo:SemiCrystalline"], question_id="solid_structure")
    set_property(phase, "cpo:hasSolidStructure", {"@id": answer}, namespace_collection)
    return answer


def _material_form_indeterminate(phase: dict, datagraph: dict) -> bool:
    """Whether the material of the phase defines a cpo:IndeterminateForm on this level - a stream
    between devices, whose region no device in the model bounds (creation/material_functions.py).
    Its phases cannot know more about the shape than their material."""
    material = resolve(datagraph, ref_id(phase.get("dcterms:isPartOf")))
    form = resolve(datagraph, ref_id(material.get("cpo:definesForm"))) if material else None
    return form is not None and "cpo:IndeterminateForm" in as_list(form.get("@type"))


def _siblings(phase: dict, material: dict, datagraph: dict) -> list:
    """The phases of the material, the phase itself included - which during its completion is not in
    the datagraph yet (only at the end of complete_phase). A sibling that cannot be resolved stays
    in the list as None."""
    return [phase if sibling_id == phase["@id"] else resolve(datagraph, sibling_id)
            for sibling_id in ref_ids(material.get("dcterms:hasPart"))]


def _dispersed_in_other_phase(phase: dict, datagraph: dict) -> bool:
    """Whether the phase is dispersed IN something: dispersed, and its material has a continuous
    phase it can be distributed in. Only such a phase has no region of its own (its form is a
    cpo:IndeterminateForm). A
    dispersed phase alone in its material (a powder in a stream) is in nothing; it takes up the
    material's region like any single phase."""
    if not _is_dispersed(phase, datagraph):
        return False
    material = resolve(datagraph, ref_id(phase.get("dcterms:isPartOf")))
    if material is None:
        return True
    # A phase that cannot be resolved counts as continuous, to be on the safe side.
    return any(s is None or (s["@id"] != phase["@id"] and not _is_dispersed(s, datagraph))
               for s in _siblings(phase, material, datagraph))


def _material_filled_alone(phase: dict, datagraph: dict):
    """The material of the phase if the phase takes up the material's region alone - else None.

    The material is the sum of its phases and fills the region it sits in (the cavity of its device,
    the form of its device for a body, the room for the room air). A phase alone in it fills that
    region too. Another gas above a liquid is a phase of the same material (the head space of a
    vial), so "alone" really means the material holds nothing else. Phases dispersed in another
    phase of the material do not count - they have no region of their own; a dispersed phase that
    is the material's only phase counts, it is in nothing (_dispersed_in_other_phase)."""
    material = resolve(datagraph, ref_id(phase.get("dcterms:isPartOf")))
    if material is None:
        return None
    # Another phase that cannot be resolved is counted along, to be on the safe side - when in
    # doubt, a form of its own rather than a wrongly shared one.
    counted = [s for s in _siblings(phase, material, datagraph)
               if s is None or s["@id"] == phase["@id"] or not _dispersed_in_other_phase(s, datagraph)]
    return material if [s and s["@id"] for s in counted] == [phase["@id"]] else None


def _share_material_volume(phase: dict, namespace_collection: dict, datagraph: dict, before: bool):
    """A phase that fills its material alone and the material have ONE volume - the same Actual on
    every level, as in the library (a device body and its phase, the room air and its phase).
    before=True, before the phase gets a volume: a volume the material already has becomes the
    phase's. before=False, after: a material without a volume takes the phase's (the body, whose
    volume the library states on the phase).

    Not for a dispersed phase, even alone in its material: its volume is the volume of its
    particles, bubbles or droplets, the material's the volume of the region they are spread over
    (a powder bed's bulk volume) - two quantities (rule 3a.6)."""
    if _is_dispersed(phase, datagraph):
        return
    material = _material_filled_alone(phase, datagraph)
    if material is None:
        return
    if before and "cpo:hasVolume" in material and "cpo:hasVolume" not in phase:
        set_property(phase, "cpo:hasVolume", material["cpo:hasVolume"], namespace_collection)
    elif not before and "cpo:hasVolume" in phase and "cpo:hasVolume" not in material:
        set_property(material, "cpo:hasVolume", phase["cpo:hasVolume"], namespace_collection)


def _form_copy_on_level(parent_form_id: str, scope: str, nr: int, datagraph: dict):
    """The copy of a form one level up on this level - the form of this scope (and experiment)
    that specializes it. The device made it when it copied its forms (helpers/forms.py:
    own_form)."""
    for entity in datagraph.get("@graph", []):
        if ref_id(entity.get("hlo:specializationOf")) != parent_form_id or scope not in as_list(entity.get("@type")):
            continue
        if scope == "hlo:ExperimentSpecific" and not entity["@id"].endswith(f"_ExperimentSpecific_{nr}"):
            continue
        return entity
    return None


def _is_layer_of_body(phase: dict, datagraph: dict) -> bool:
    """Whether the phase is one layer of a device body - a phase of a body material beside
    others (rule 3.8a). Only then does it get a cpo:LayerForm; a phase beside others in a stream
    between devices keeps its cpo:IndeterminateForm."""
    material = resolve(datagraph, ref_id(phase.get("dcterms:isPartOf")))
    return material is not None and "cpo:BodyMaterial" in as_list(material.get("@type"))


def add_phase_form(phase: dict, scope: str, nr: int, namespace_collection: dict, datagraph: dict,
                   todo_list: list, local_todo_list: list, evidence_known_cache: dict = None):
    """Give every phase a Form and say where its shape comes from.

    A form describes a region of space. Phase_Structure_R1 asks every phase that is not dispersed
    for one: the form of the region it takes up, which is a form of its own (cpo:definesForm) where
    the phase sets the boundary itself, or the form of its material (cpo:fillsForm) where it takes
    up exactly the material's region (rule
    3a). One rule for every material:

    - The only phase of a material that is not dispersed fills the form of its material
      (_material_filled_alone): the cavity of its device (the coolant in a jacket, a stream in a
      pipe - a device the stream runs through counts as full), the form of the device for a body,
      the room for the room air, the cpo:IndeterminateForm of a stream between devices.
    - Several phases each define a form of their own: a continuous gas or liquid phase in a device
      takes the class of the device's cavity, shares its cross-section and has its own height - the
      fill level - offered in the phase's value lists (_build_phase_form_from_cavity); a phase
      outside a device (a coated body, a two-phase stream between devices) defines a
      cpo:IndeterminateForm, since there is no geometry for its part; any other phase (a solid one
      in a device) a form whose class is asked for (_build_asked_phase_form).
    - A phase dispersed in another phase of its material defines a cpo:IndeterminateForm: it has
      no single region, what is known
      about its shape is its size distribution (Phase_Structure_R4). Alone in its material it is in
      nothing and fills the material's form like any single phase.

    Across the levels the own forms are linked through hlo:specializationOf/hlo:hasSpecialization,
    exactly as the process variables are. Beyond that it is asked like any other value
    (the uniform series pattern of add_phase_process_variable): Q1 - attach evidence/reference
    already on the series level? Q2 - do we know anything about it in the single experiments? Not
    asked where the phase fills the form of its material: the form is described there.
    """
    if form_ref(phase):
        return None
    # A phase dispersed in another phase (bubbles, particles) has no single region - what is known
    # of its shape is said by the size distribution (Phase_Structure_R4). It defines a
    # cpo:IndeterminateForm, a statement rather than a gap; linked through the levels like the
    # indeterminate form of a stream. Only if the
    # other phase exists: alone in its material it fills the form of the material like any single phase.
    if _dispersed_in_other_phase(phase, datagraph):
        parent_phase = get_series_entity(phase, datagraph)
        parent_form = resolve(datagraph, ref_id(parent_phase.get("cpo:definesForm"))) if parent_phase and parent_phase.get("cpo:definesForm") else None
        return build_form(phase, "cpo:definesForm", "cpo:IndeterminateForm", scope, nr, namespace_collection, datagraph,
                          parent_form=parent_form)

    # Alone in the material: the same form as the material (rule 3a.2, A). A cavity that a material
    # with one phase fills is full; if it is not, the gas space above it belongs to it as a second
    # phase (rule 3a.5).
    material = _material_filled_alone(phase, datagraph)
    region = ref_id(form_ref(material)) if material else None
    if region is not None:
        set_property(phase, "cpo:fillsForm", {"@id": region}, namespace_collection)
        return None

    # Several phases: each its own form (rule B).
    cavity = _cavity_filled_by(phase, datagraph)
    if cavity is not None:
        # Gas or liquid in a device: class and cross-section of the cavity, a height of its own.
        form = _build_phase_form_from_cavity(phase, cavity, scope, nr, namespace_collection, datagraph)
    elif _reaches_fixed(phase, datagraph) or _material_form_indeterminate(phase, datagraph):
        # A part of a body material or of a stream between devices: there is no geometry for that.
        parent_phase = get_series_entity(phase, datagraph)
        # resolve instead of find_entity: on the series level the form lies one level higher, in the
        # library (the layer of a body material), not in the crate.
        parent_form = resolve(datagraph, ref_id(parent_phase.get("cpo:definesForm"))) if parent_phase and parent_phase.get("cpo:definesForm") else None
        if not _is_layer_of_body(phase, datagraph):
            return build_form(phase, "cpo:definesForm", "cpo:IndeterminateForm", scope, nr, namespace_collection, datagraph,
                              parent_form=parent_form)
        # A layer of a body material (rule 3.8a): the forms are set by the device (its body form and,
        # at it, cpo:hasLayerForm), the phases only fill them - the core the body form, a coating its
        # layer form. Which one, the library says; the crate fills the same form on its level and asks
        # nothing. Without that statement the phase stays without a form and Phase_Structure_R1
        # reports the gap.
        parent_fill = ref_id(parent_phase.get("cpo:fillsForm")) if parent_phase else None
        own_copy = _form_copy_on_level(parent_fill, scope, nr, datagraph) if parent_fill else None
        if own_copy is None:
            print(f"[{scope}] {get_display_label(phase)} is a layer of a device body, but the form it fills is not found "
                  "on this level - no form given; check the library entry (cpo:fillsForm of the layer phase).")
            return None
        set_property(phase, "cpo:fillsForm", own_copy, namespace_collection)
        return None
    else:
        # If the form cannot be derived (a solid phase in a device), it is asked - required:
        # without a class there would be no dimensions either.
        form = _build_asked_phase_form(phase, scope, nr, namespace_collection, datagraph)

    _offer_phase_form_dimensions(form, phase, scope, nr, namespace_collection, datagraph, todo_list,
                                 local_todo_list, evidence_known_cache)
    return _offer_phase_form_values(form, phase, scope, nr, namespace_collection, datagraph, todo_list,
                                    local_todo_list, evidence_known_cache)


def _offer_phase_form_dimensions(form: dict, phase: dict, scope: str, nr: int, namespace_collection: dict,
                                 datagraph: dict, todo_list: list, local_todo_list: list, evidence_known_cache: dict = None):
    """Offer the dimensions the phase's form carries itself - the fill height of a phase in a
    vessel, every dimension of an asked form - in the value lists of the phase, so that a
    measured or assumed value can be recorded like any other quantity. Shared dimensions (the
    cavity's cross-section, recorded with the device) and the volume (the phase's own, offered
    already) are not offered again, nor the aspect ratios."""
    parent_phase = get_series_entity(phase, datagraph)
    offered = []
    for property_name, value in list(form.items()):
        if not property_name.startswith("cpo:has") or property_name.endswith("Ratio") or property_name == "cpo:hasCavityForm":
            continue
        actual = find_entity(datagraph, ref_id(value))
        if actual is None or ref_id(actual.get("cpo:isProcessVariableOf")) != form["@id"]:
            continue
        # "height", "inner_diameter", ... - the name in the lists and the segment of the questions.
        base = property_name.split(":", 1)[-1][3:]
        name = "".join("_" + c.lower() if c.isupper() else c for c in base).lstrip("_")
        if scope == "hlo:SeriesSpecific":
            gate_key = (phase["@id"], f"cpo:definesForm/{property_name}")
        else:
            gate_key = (parent_phase["@id"], f"cpo:definesForm/{property_name}") if parent_phase else None
        request_value_sources(
            actual, phase, scope, nr, namespace_collection, datagraph, todo_list, local_todo_list,
            quantity=name, segment=name,
            offer_at_series=evidence_known_cache is not None,
            gate_key=gate_key if evidence_known_cache is not None else None,
            evidence_known_cache=evidence_known_cache,
        )
        offered.append(actual)
    return offered


def _offer_phase_form_values(form: dict, phase: dict, scope: str, nr: int, namespace_collection: dict, datagraph: dict,
                             todo_list: list, local_todo_list: list, evidence_known_cache: dict = None):
    """Offer the form of a phase in the value lists of the phase, like any other quantity."""
    if _reaches_fixed(phase, datagraph):
        return form

    # The uniform series pattern, as in add_phase_process_variable. Evidence/reference per list
    # of the exemplar (helpers/value_sources.py), in the old segment "form". The only type that
    # fits is cpo:Form - what supports or prescribes a phase form is again a form, not a
    # ProcessVariable and not a time.
    parent_phase = get_series_entity(phase, datagraph)
    form_types = ["cpo:Form"]
    if scope == "hlo:SeriesSpecific":
        gate_key = (phase["@id"], "cpo:definesForm")
    else:
        gate_key = (parent_phase["@id"], "cpo:definesForm") if parent_phase else None
    request_value_sources(
        form, phase, scope, nr, namespace_collection, datagraph, todo_list, local_todo_list,
        quantity="form", segment="form",
        offer_at_series=evidence_known_cache is not None,
        gate_key=gate_key if evidence_known_cache is not None else None,
        evidence_known_cache=evidence_known_cache, evidence_types=form_types, reference_types=form_types,
    )

    return form


# ---------------------------------------------------------------------------
# Working through one phase completely
# ---------------------------------------------------------------------------

def _phase_belongs_to_body_material(phase: dict, datagraph: dict) -> bool:
    """Check whether the phase is part of a cpo:BodyMaterial MaterialVolume - the material a
    device is made of, the glass of a vessel for instance (see device_functions.py,
    cpo:madeOfMaterial).
    """
    material_ref = phase.get("dcterms:isPartOf")
    material_id = material_ref.get("@id") if isinstance(material_ref, dict) else material_ref
    material = find_entity(datagraph, material_id) if material_id else None
    if not material:
        return False
    material_types = as_list(material.get("@type"))
    return "cpo:BodyMaterial" in material_types


def complete_phase(phase: dict, scope: str, nr: int, namespace_collection: dict, datagraph: dict, chemical_entity_library: dict, todo_list: list, local_todo_list: list, evidence_known_cache: dict = None, composition_kind_cache: dict = None):
    """Add all remaining properties to a placeholder phase (from the todo list, see
    create_phase_placeholder) and then write it into the datagraph - as
    create_material_from_todo does for materials.
    """
    state_class = get_phase_state_class(phase)
    state_label = state_class.split(":", 1)[-1] if state_class else "Phase"
    print(f"\n=== Now describing {state_label} \"{get_display_label(phase)}\" ({phase['@id']}, {scope}) ===")

    is_body_phase = _phase_belongs_to_body_material(phase, datagraph)

    # Body material phases (device body, e.g. glass/stainless steel): which species occur is
    # fixed for good by the Fixed entity (no question about further species, see
    # add_phase_composition/skip_additional_species) - dispersion state/energy field/
    # mass/density are likewise taken over automatically instead of asked, as far as the
    # Fixed entity has them (see add_dispersion_state/add_phase_energy_field and the
    # generic Fixed shortcut in add_phase_process_variable).
    add_phase_composition(phase, scope, nr, namespace_collection, datagraph, chemical_entity_library, todo_list, local_todo_list, composition_kind_cache, evidence_known_cache, skip_additional_species=is_body_phase)
    add_dispersion_state(phase, scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache)
    add_solid_structure(phase, scope, namespace_collection, datagraph)
    add_phase_energy_field(phase, scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache)
    add_molecule_energy_fields(phase, scope, nr, namespace_collection, datagraph, chemical_entity_library, todo_list, local_todo_list, evidence_known_cache)

    # The volume on every level, also for the phases of a device body: every quantity of an
    # exemplar exists as an actual of its own (rule 3.2). For the body it inherits the value of the
    # library, nothing is asked (add_specializing_actual in helpers/process_variables.py).
    # A phase that fills its material alone has its volume - the same actual (rule 3a.6).
    _share_material_volume(phase, namespace_collection, datagraph, before=True)
    add_phase_process_variable(phase, "cpo:hasVolume", scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache)
    _share_material_volume(phase, namespace_collection, datagraph, before=False)
    # The form after the volume: if the phase fills a cavity, its volume is the
    # volume of its form - the same actual.
    add_phase_form(phase, scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache)
    add_phase_process_variable(phase, "cpo:hasTemperature", scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache)
    add_phase_process_variable(phase, "cpo:hasPressure", scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache)
    # Mass and density hang on the category Substance, not on Energy/Space (Phase_Substance_R2 and
    # R3): mass says nothing about the phase's energetic state, only about the amount of substance
    # present.
    add_phase_process_variable(phase, "cpo:hasMass", scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache)
    add_phase_process_variable(phase, "cpo:hasDensity", scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache)
    # Phase_Information_R1 (not derivable - entropy does not follow by calculation from the
    # quantities already asked without a full thermodynamic model). Holds for body material phases
    # too, unlike hasVolume above: the requirement has no is_body_phase exception (only Fixed is
    # excluded).
    add_phase_process_variable(phase, "cpo:hasEntropy", scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache)

    # Whether and when the phase existed in this experiment (rule 3.1b): the series creates
    # all possible phases (rule 7c.1), the occurrence says whether there was one, its times when
    # (Phase_Time_R3). Only on the experiment level, as for transfers and reactions.
    # Occurrence with status and times; it is asked only in creation/occurrence_functions.py.
    add_occurrence(phase, scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache)

    add_entity(datagraph, phase)
    delete_todo_entity(todo_list, phase)
    return phase


def complete_phases_from_todo(scope: str, nr: int, namespace_collection: dict, datagraph: dict, chemical_entity_library: dict, todo_list: list, local_todo_list: list, evidence_known_cache: dict = None, composition_kind_cache: dict = None) -> list:
    """Work through every phase placeholder of a scope and experiment.

    A phase is recognised by its @type (SolidPhase/LiquidPhase/GasPhase, see
    get_phase_state_class), since "cpo:Phase" itself is not carried redundantly in the
    @type. For orientation, the complete entity of each MaterialRepresentation is printed
    once before its phases are asked about.
    """
    phase_items = [
        p for p in todo_list
        if scope in p.get("@type", []) and get_phase_state_class(p) is not None and phase_matches_experiment(p, scope, nr, datagraph)
    ]

    phases_by_material = {}
    for phase in phase_items:
        material_ref = phase.get("dcterms:isPartOf")
        material_id = material_ref.get("@id") if isinstance(material_ref, dict) else material_ref
        phases_by_material.setdefault(material_id, []).append(phase)

    completed = []
    for material_id, material_phases in phases_by_material.items():
        material = find_entity(datagraph, material_id) if material_id else None
        print(f"\n--- Phases of {material_id} ({scope}) ---")
        if material:
            print(material)

        # The same number/level as when the material or environment was created (see stable_index
        # in material_functions.py/environment_functions.py) - the entity was certainly registered
        # there before this later completion of the phases runs (see main.py:
        # create_all_materials/create_all_environments run before complete_all_phases).
        stable_level = _stable_index_level_for_material(material_id, datagraph)
        with question_path(stable_level, key_name(material_id)):
            for phase in material_phases:
                with question_path("phase", key_name(phase["@id"])):
                    completed.append(complete_phase(phase, scope, nr, namespace_collection, datagraph, chemical_entity_library, todo_list, local_todo_list, evidence_known_cache, composition_kind_cache))
    return completed


# ---------------------------------------------------------------------------
# Transfers: a chemical entity moves at a PhasePairInterface from one phase into
# the other (a phase change such as melting/vaporization when the same substance is
# concerned, or dissolution/solidification/absorption when a species passes into
# another phase, or adsorption/desorption at the occupation of the interface itself).
# Asked only at PhasePairInterfaces (not at the aggregating PhaseInterface), since a
# transfer needs a definite source and/or destination phase. TRANSFER_TYPES and the
# creation of the transfers themselves are in helpers/transfer_functions.py (also
# used by creation/reaction_functions.py).
# ---------------------------------------------------------------------------


def phase_label(phase: dict) -> str:
    """Label for questions about a phase: the state of matter, kept as a hint about what
    kind of phase this is, plus the name instead of the raw ID - 'SolidPhase "Reactant
    Pellet"' rather than 'SolidPhase #SolidPhase_0001_...'.
    """
    state_class = get_phase_state_class(phase)
    state_label = state_class.split(":", 1)[-1] if state_class else "Phase"
    return f'{state_label} "{get_display_label(phase)}"'


def interface_label(interface: dict) -> str:
    """Label for questions about an interface: the type (PhaseInterface or
    PhasePairInterface) plus the name instead of the raw ID.

    The name is built automatically from the names of the phases involved when the interface
    is created (see get_or_create_phase_interface/create_phase_pair_interface).
    """
    type_list = as_list(interface.get("@type"))
    interface_type = next((t.split(":", 1)[-1] for t in type_list if t in ("cpo:PhaseInterface", "cpo:PhasePairInterface")), "Interface")
    return f'{interface_type} "{get_display_label(interface)}"'


def _species_in_phase(phase: dict) -> list:
    parts = phase.get("dcterms:hasPart", [])
    parts = parts if isinstance(parts, list) else [parts]
    return [p.get("@id") if isinstance(p, dict) else p for p in parts if p]


def species_label(species_id: str, chemical_entity_library: dict, datagraph: dict = None) -> str:
    """Human-readable label for a chemical species ID - the one label function for species
    (phases and reactions).

    Most species IDs point straight at the fixed library entry, but a chebi:Molecule points
    at its phase-specific series or experiment instance in the datagraph instead (see
    get_or_create_phase_molecule), which is why the datagraph is searched first.
    """
    entity = (find_entity(datagraph, species_id) if datagraph else None) or find_entity(chemical_entity_library, species_id) or {"@id": species_id}
    return get_display_label(entity)


def _phase_is_inert(phase: dict, datagraph: dict, chemical_entity_library: dict) -> bool:
    """Whether the phase consists only of chemical entities whose library entry is inert
    (cpo:isInert = true: glass, stainless steel, PTFE). A phase without any known entity is not."""
    species = ref_ids(phase.get("dcterms:hasPart"))
    if not species:
        return False
    for species_id in species:
        fixed = find_entity(chemical_entity_library, fixed_chemical_entity_id({"@id": species_id}, datagraph))
        if fixed is None or fixed.get("cpo:isInert") not in (True, "true"):
            return False
    return True


# Which substances (Fixed IDs) stood in the two phases of a series PhasePairInterface when its
# transfers were asked ({pair_interface_id: set}). Lives for one run (rule 7a.1).
_SPECIES_WHEN_DESCRIBED = {}


def _species_of(phase: dict, datagraph: dict) -> set:
    """The fixed chemical entities of a phase (its molecule instances resolved to the library)."""
    return {fixed_chemical_entity_id(ref, datagraph) for ref in as_list(phase.get("dcterms:hasPart")) if ref}


# The possible transfers per pair of states of matter (rule 3b.2): every pair
# of types holds for every substance of both phases, in both directions. The generator interprets
# no physics - whether a substance really evaporates or dissolves under the conditions is not for
# it to decide, but for the occurrence in the experiment. Per entry: (type, source, destination)
# with "a"/"b" for the two phases in the order of the key, None for the occupation of the interface
# (adsorption ends there, desorption starts there). Two solids exchange as well (cpo:SolidExchange);
# an inert wall stays excluded (rule 3b.3).
_TRANSFER_RULES = {
    ("cpo:SolidPhase", "cpo:SolidPhase"): [
        ("cpo:SolidExchange", "a", "b"), ("cpo:SolidExchange", "b", "a")],
    ("cpo:SolidPhase", "cpo:LiquidPhase"): [
        ("cpo:Adsorption", "b", None), ("cpo:Desorption", None, "b"),
        ("cpo:Dissolution", "a", "b"), ("cpo:Solidification", "b", "a"),
        ("cpo:Melting", "a", "b"), ("cpo:Freezing", "b", "a")],
    ("cpo:SolidPhase", "cpo:GasPhase"): [
        ("cpo:Adsorption", "b", None), ("cpo:Desorption", None, "b"),
        ("cpo:Sublimation", "a", "b"), ("cpo:Deposition", "b", "a")],
    ("cpo:LiquidPhase", "cpo:GasPhase"): [
        ("cpo:Absorption", "b", "a"), ("cpo:Degassing", "a", "b"),
        ("cpo:Vaporization", "a", "b"), ("cpo:Condensation", "b", "a")],
    ("cpo:LiquidPhase", "cpo:LiquidPhase"): [
        ("cpo:LiquidExchange", "a", "b"), ("cpo:LiquidExchange", "b", "a")],
    ("cpo:GasPhase", "cpo:GasPhase"): [
        ("cpo:GasExchange", "a", "b"), ("cpo:GasExchange", "b", "a")],
}
# Two phases of the same state, exactly one of them dispersed (bubbles, droplets, particles): besides the
# exchange, the dispersed one can merge into the continuous one and back - a is the dispersed one. For
# every state, and in addition to the exchange, not instead of it: a substance can pass between the two
# without the droplets or particles merging.
_DISPERSED_RULES = [("cpo:Coalescence", "a", "b"), ("cpo:Dispersion", "b", "a")]
_STATE_ORDER = ("cpo:SolidPhase", "cpo:LiquidPhase", "cpo:GasPhase")


def _state_of(phase: dict, datagraph: dict):
    """The state-of-matter class of a phase, read up the hlo:specializationOf chain."""
    seen, current = set(), phase
    while current is not None and current["@id"] not in seen:
        state = get_phase_state_class(current)
        if state:
            return state
        seen.add(current["@id"])
        current = resolve(datagraph, ref_id(current.get("hlo:specializationOf"))) if current.get("hlo:specializationOf") else None
    return None


def potential_transfers(species_ids, phase_a: dict, phase_b: dict, datagraph: dict) -> list:
    """The potential transfers across the interface of two phases, from the rule table
    (_TRANSFER_RULES): for every species, every type the two states allow, in both directions -
    as (species_id, type, source phase, destination phase), source or destination None for the
    interface occupation. Nothing is asked: which of them happen is the occurrence in the
    experiments. Empty for a phase without known state."""
    state_a, state_b = _state_of(phase_a, datagraph), _state_of(phase_b, datagraph)
    if state_a not in _STATE_ORDER or state_b not in _STATE_ORDER:
        return []
    first, second = (phase_a, phase_b) if _STATE_ORDER.index(state_a) <= _STATE_ORDER.index(state_b) else (phase_b, phase_a)
    key = (_state_of(first, datagraph), _state_of(second, datagraph))
    rules = list(_TRANSFER_RULES.get(key, []))
    if key[0] == key[1] and _is_dispersed(first, datagraph) != _is_dispersed(second, datagraph):
        if not _is_dispersed(first, datagraph):
            first, second = second, first
        rules += _DISPERSED_RULES
    phases = {"a": first, "b": second, None: None}
    return [(species_id, transfer_type, phases[source], phases[destination])
            for species_id in sorted(species_ids)
            for transfer_type, source, destination in rules]


# The stream ends at device ports resolved on the series level ({(port_id, stream_id, stream_phase_id):
# (source_phase_id, destination_phase_id, end_key)}), for follow_up_transfers. Lives for one run.
_SERIES_PORT_ENDS = {}


def follow_up_transfers(series_pair_interfaces: dict, series_transfers: dict, series_port_crossings: dict,
                        namespace_collection: dict, datagraph: dict, chemical_entity_library: dict, todo_list: list,
                        local_todo_list: list, evidence_known_cache: dict = None):
    """Series level, after all interfaces and port crossings: follow the species that entered a
    phase through a transfer AFTER its interfaces and ports had been described - O2 from the room
    air in the headspace of an open vessel, which may then be absorbed by the liquid, leave with
    the sample and reach the vial. Alternates between the two until no species arrives anywhere:

    - pair interfaces (_follow_up_pair_interfaces): the potential transfers of exactly the new
      species, from the rule table;
    - ports (_follow_up_ports): not asked - whatever crosses a port crosses as a whole phase, so
      every species of that phase gets its port crossing, and with it arrives on the other side.

    The new transfers go into series_transfers and series_port_crossings, so the experiments
    carry them over like all others. Nothing here is specific to one setup: interfaces, ports and
    species come from the structure of the crate.
    """
    while True:
        asked = _follow_up_pair_interfaces(series_pair_interfaces, series_transfers, namespace_collection, datagraph,
                                           chemical_entity_library, todo_list, local_todo_list, evidence_known_cache)
        crossed = _follow_up_ports(series_port_crossings, namespace_collection, datagraph, chemical_entity_library,
                                   todo_list, local_todo_list, evidence_known_cache)
        if not (asked or crossed):
            return


def _follow_up_pair_interfaces(series_pair_interfaces: dict, series_transfers: dict, namespace_collection: dict,
                               datagraph: dict, chemical_entity_library: dict, todo_list: list, local_todo_list: list,
                               evidence_known_cache: dict = None) -> bool:
    """One pass over the series pair interfaces: every species that came into one of the two
    phases after the interface was described gets its potential transfers there (rule table,
    potential_transfers). Returns whether any interface got new species."""
    asked_any = False
    for pair_identity, pair_interface in list(series_pair_interfaces.items()):
        described = _SPECIES_WHEN_DESCRIBED.get(pair_interface["@id"])
        if described is None:
            continue
        phase_a, phase_b = (find_entity(datagraph, phase_id) for phase_id in sorted(pair_identity))
        if phase_a is None or phase_b is None:
            continue
        present = _species_of(phase_a, datagraph) | _species_of(phase_b, datagraph)
        new_species = present - described
        if not new_species:
            continue
        _SPECIES_WHEN_DESCRIBED[pair_interface["@id"]] = described | new_species
        if (_phase_is_inert(phase_a, datagraph, chemical_entity_library)
                or _phase_is_inert(phase_b, datagraph, chemical_entity_library)):
            continue
        asked_any = True
        planned = potential_transfers(new_species, phase_a, phase_b, datagraph)
        with question_path("transfer_follow_up"), question_path("phase_pair_interface", key_name(pair_identity)):
            for species_id, transfer_type, source_phase, destination_phase in planned:
                name = transfer_name(transfer_type, species_id, ref_id(source_phase), ref_id(destination_phase), datagraph, chemical_entity_library)
                with question_path("transfer", name):
                    transfer = create_transfer_at_interface(pair_interface, species_id, transfer_type, "hlo:SeriesSpecific", 1,
                                                            namespace_collection, datagraph, chemical_entity_library, todo_list,
                                                            local_todo_list, source_phase, destination_phase, evidence_known_cache)
                series_transfers.setdefault(pair_interface["@id"], []).append(transfer)
    return asked_any


def _follow_up_ports(series_port_crossings: dict, namespace_collection: dict, datagraph: dict,
                     chemical_entity_library: dict, todo_list: list, local_todo_list: list,
                     evidence_known_cache: dict = None) -> bool:
    """One pass over the series stream ends at device ports: every species of the phase that
    crosses the port (the device phase for a stream drawn off, the stream phase for one running
    in) gets its port crossing, if it has none yet - the same rule create_port_crossing_transfers
    applies to the stream from the start. Nothing is asked; the question path is the one the
    crossing would have had anyway. Returns whether a crossing was added."""
    added = {}
    for end_id, (source_id, destination_id, end_key) in _SERIES_PORT_ENDS.items():
        port_id, stream_id, _phase_id = end_id
        port, stream = find_entity(datagraph, port_id), find_entity(datagraph, stream_id)
        source_phase, destination_phase = find_entity(datagraph, source_id), find_entity(datagraph, destination_id)
        if None in (port, stream, source_phase, destination_phase):
            continue
        existing = series_port_crossings.setdefault(end_id, [])
        covered = {fixed_chemical_entity_id(transfer.get("cpo:transfersChemicalEntity"), datagraph) for transfer in existing}
        for species_ref in as_list(source_phase.get("dcterms:hasPart")):
            species_id = ref_id(species_ref)
            fixed_id = fixed_chemical_entity_id(species_ref, datagraph)
            if not species_id or fixed_id in covered:
                continue
            with question_path("port_crossing", end_key):
                with question_path("transfer", transfer_name("cpo:PortCrossing", species_id, source_id, destination_id, datagraph, chemical_entity_library)):
                    transfer = get_or_create_transfer(
                        port, "port", species_id, "cpo:PortCrossing", "hlo:SeriesSpecific", 1, namespace_collection, datagraph,
                        chemical_entity_library, todo_list, local_todo_list,
                        source_phase=source_phase, destination_phase=destination_phase, evidence_known_cache=evidence_known_cache
                    )
            existing.append(transfer)
            covered.add(fixed_id)
            added.setdefault(end_id, []).append(transfer)
    if added:
        # Couple the flowrates of the same species at both ends of a stream, as on the first
        # creation (couplings set twice are dropped, set_property checks that).
        link_stream_end_couplings(series_port_crossings, namespace_collection, datagraph)
    return bool(added)


def handle_transfers_for_pair_interface(pair_interface: dict, phase_a: dict, phase_b: dict, scope: str, nr: int, namespace_collection: dict, datagraph: dict, chemical_entity_library: dict, todo_list: list, local_todo_list: list, evidence_known_cache: dict = None, series_pair_interface: dict = None, series_transfers: dict = None):
    """At series level: create the potential transfers between the two phases at this
    PhasePairInterface from the rule table (potential_transfers) - every species of both
    phases, every type their states allow, both directions. Nothing is asked.

    For adsorption and desorption only removesFromPhase or addsToPhase is set; the other end
    is the interface occupation, not a phase.

    At experiment level nothing is asked again: the transfers of the series counterpart are
    carried over one to one (series_transfers, a {series_pair_interface_id: [transfer]} cache
    living across the whole run). Only flowrate, occurrence and time are asked for afresh per
    experiment.
    """
    if scope == "hlo:SeriesSpecific" and (_phase_is_inert(phase_a, datagraph, chemical_entity_library)
                                         or _phase_is_inert(phase_b, datagraph, chemical_entity_library)):
        # An inert phase (glass, stainless steel, PTFE: cpo:isInert at the substance in the library)
        # exchanges nothing - there are no potential transfers, nothing is asked (rule 3b.3). The
        # note is the reason; without it the questions would come back.
        if series_transfers is not None:
            series_transfers[pair_interface["@id"]] = []
        _SPECIES_WHEN_DESCRIBED[pair_interface["@id"]] = _species_of(phase_a, datagraph) | _species_of(phase_b, datagraph)
        return []
    if scope == "hlo:SeriesSpecific":
        # The potential transfers come from the rule table (potential_transfers, rule 3b.2): every
        # substance of both phases, every type the two states of matter allow, in both directions.
        # Nothing is asked any more - which of them takes place is said by the occurrence in the
        # experiment. Every transfer stands under its name (helpers/transfer_functions.py:
        # transfer_name), as before.
        species = _species_of(phase_a, datagraph) | _species_of(phase_b, datagraph)
        planned = potential_transfers(species, phase_a, phase_b, datagraph)
        # Whatever comes into one of the phases later through a transfer gets its transfers here
        # afterwards (follow_up_transfers).
        _SPECIES_WHEN_DESCRIBED[pair_interface["@id"]] = species

        transfers = []
        for species_id, transfer_type, source_phase, destination_phase in planned:
            name = transfer_name(transfer_type, species_id, ref_id(source_phase), ref_id(destination_phase), datagraph, chemical_entity_library)
            with question_path("transfer", name):
                transfers.append(create_transfer_at_interface(pair_interface, species_id, transfer_type, scope, nr, namespace_collection, datagraph, chemical_entity_library, todo_list, local_todo_list, source_phase, destination_phase, evidence_known_cache))

        if series_transfers is not None:
            series_transfers[pair_interface["@id"]] = transfers
        return transfers

    if series_transfers is None or series_pair_interface is None:
        return []

    phase_a_series = get_series_entity(phase_a, datagraph)
    phase_b_series = get_series_entity(phase_b, datagraph)

    def _map_series_phase(series_ref):
        series_id = series_ref.get("@id") if isinstance(series_ref, dict) else series_ref
        if series_id is None:
            return None
        if phase_a_series and phase_a_series["@id"] == series_id:
            return phase_a
        if phase_b_series and phase_b_series["@id"] == series_id:
            return phase_b
        return None

    experiment_transfers = []
    for series_transfer in series_transfers.get(series_pair_interface["@id"], []):
      with question_path("transfer", transfer_name_of(series_transfer, datagraph, chemical_entity_library)):
        source_phase = _map_series_phase(series_transfer.get("cpo:removesFromPhase"))
        destination_phase = _map_series_phase(series_transfer.get("cpo:addsToPhase"))
        if source_phase is None and destination_phase is None:
            continue

        species_ref = series_transfer.get("cpo:transfersChemicalEntity")
        species_id = species_ref.get("@id") if isinstance(species_ref, dict) else species_ref
        if not keeps_species(species_id, nr, [source_phase, destination_phase], datagraph):
            continue        # the substance does not occur in this experiment (rule 3.13)
        transfer_type_ref = series_transfer.get("cpo:hasTransferType")
        transfer_type = transfer_type_ref.get("@id") if isinstance(transfer_type_ref, dict) else transfer_type_ref

        transfer = create_transfer_at_interface(pair_interface, species_id, transfer_type, scope, nr, namespace_collection, datagraph, chemical_entity_library, todo_list, local_todo_list, source_phase, destination_phase, evidence_known_cache, series_transfer=series_transfer)
        add_occurrence(transfer, scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache)
        experiment_transfers.append(transfer)

    return experiment_transfers


# ---------------------------------------------------------------------------
# Interfaces between phases
# ---------------------------------------------------------------------------

def _specialize_fixed_pair_interface(pair_interface: dict, phase_a: dict, phase_b: dict, namespace_collection: dict, datagraph: dict):
    """On series level: if the library already separates the fixed counterparts of the two phases
    by an interface (the two layers of a coated body), the new pair interface
    specializes it - the same chain as for the phases themselves. Only this direction; the
    library entry is not changed (rule 2.2)."""
    fixed_a, fixed_b = get_series_entity(phase_a, datagraph), get_series_entity(phase_b, datagraph)
    if not fixed_a or not fixed_b:
        return
    shared = set(ref_ids(fixed_a.get("cpo:isSeparatedByInterface"))) & set(ref_ids(fixed_b.get("cpo:isSeparatedByInterface")))
    for interface_id in sorted(shared):
        fixed_interface = resolve(datagraph, interface_id)
        if fixed_interface is not None and "cpo:PhasePairInterface" in as_list(fixed_interface.get("@type")):
            set_property(pair_interface, "hlo:specializationOf", {"@id": interface_id}, namespace_collection)
            return


def create_phase_pair_interface(phase_a: dict, phase_b: dict, phase_interface_a: dict, phase_interface_b: dict, scope: str, nr: int, namespace_collection: dict, datagraph: dict, chemical_entity_library: dict, todo_list: list, local_todo_list: list, evidence_known_cache: dict = None, series_pair_interfaces: dict = None, series_transfers: dict = None):
    """Create a PhasePairInterface between exactly two phases (separatesPhases,
    qualifiedCardinality 2 by the ontology) and hang it as a dcterms:hasPart into the
    aggregating PhaseInterface of each of the two phases.

    series_pair_interfaces is a {frozenset({series_phase_a_id, series_phase_b_id}):
    PhasePairInterface} cache living across the whole complete_all_phases() run: at series
    level the pair interface just created is entered there, and at experiment level the
    matching series pair interface is looked up there (through the series counterparts of the
    two phases) and linked through hlo:specializationOf/hlo:hasSpecialization - exactly as for
    the phases themselves.

    series_transfers is passed straight on to handle_transfers_for_pair_interface (see
    there).
    """
    pair_type = check_type("cpo:PhasePairInterface", namespace_collection)
    experiment_number = nr if scope == "hlo:ExperimentSpecific" else None
    pair_id = generate_id_from_name(
        f"PhasePairInterface_{short_local_name(phase_a['@id'])}_{short_local_name(phase_b['@id'])}",
        scope, experiment_number
    )

    pair_interface = {
        "@id": pair_id,
        "@type": [pair_type, scope]
    }
    set_property(pair_interface, "schema:name", f"{get_display_label(phase_a)} / {get_display_label(phase_b)} Interface", namespace_collection)
    set_property(pair_interface, "cpo:separatesPhases", phase_a, namespace_collection, True)
    set_property(pair_interface, "cpo:separatesPhases", phase_b, namespace_collection, True)
    set_property(phase_a, "cpo:isSeparatedByInterface", pair_interface, namespace_collection, True)
    set_property(phase_b, "cpo:isSeparatedByInterface", pair_interface, namespace_collection, True)

    for phase_interface in (phase_interface_a, phase_interface_b):
        set_property(phase_interface, "dcterms:hasPart", pair_interface, namespace_collection, True)
        set_property(pair_interface, "dcterms:isPartOf", phase_interface, namespace_collection, True)

    # Two phases with a common interface influence each other - temperature and pressure are
    # therefore coupled directly here instead of asked (see link_phase_couplings).
    link_phase_couplings(phase_a, phase_b, namespace_collection, datagraph)

    series_pair_interface = None
    if scope == "hlo:ExperimentSpecific" and series_pair_interfaces is not None:
        series_phase_a = get_series_entity(phase_a, datagraph)
        series_phase_b = get_series_entity(phase_b, datagraph)
        if series_phase_a and series_phase_b:
            series_pair_interface = series_pair_interfaces.get(frozenset({series_phase_a["@id"], series_phase_b["@id"]}))
            if series_pair_interface:
                set_property(pair_interface, "hlo:specializationOf", series_pair_interface, namespace_collection)
                set_property(series_pair_interface, "hlo:hasSpecialization", pair_interface, namespace_collection, True)
    elif scope == "hlo:SeriesSpecific" and series_pair_interfaces is not None:
        series_pair_interfaces[frozenset({phase_a["@id"], phase_b["@id"]})] = pair_interface
    if scope == "hlo:SeriesSpecific":
        _specialize_fixed_pair_interface(pair_interface, phase_a, phase_b, namespace_collection, datagraph)

    # Area of THIS pair interface (Phase_Space_R4) - the same helper, the same properties and the
    # same series evidence gate as for the aggregating PhaseInterface (see
    # get_or_create_phase_interface above, cpo:hasArea/quantitykind:Area). No question_path segment
    # of its own needed: runs under the "phase_pair_interface:N" segment of the callers that is
    # already active (see create_interfaces_for_material_phases/add_cross_material_interfaces
    # below) - the label text comes (as for the aggregating counterpart) automatically from pair_id,
    # which already holds both short names of the phases (see above), so that the question stays
    # distinguishable from the total area of the single PhaseInterface.
    # Header line as for phases and tasks (AP9): from here on the questions belong to this interface.
    print(f"\n=== Now describing Phase Pair Interface \"{get_display_label(pair_interface)}\" ({pair_id}, {scope}{f', Experiment {nr}' if experiment_number else ''}) ===")
    add_phase_process_variable(pair_interface, "cpo:hasArea", scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache)

    handle_transfers_for_pair_interface(pair_interface, phase_a, phase_b, scope, nr, namespace_collection, datagraph, chemical_entity_library, todo_list, local_todo_list, evidence_known_cache, series_pair_interface, series_transfers)

    # Whether and when the two phases touched (rule 3.1b): a contact can come and
    # go while both phases are there - the gas space of a vessel and the room air only while the lid
    # is off. The coupling (isCoupledWith) remains the statement that the quantities can influence
    # each other; when that applies is said by this occurrence. Only on the experiment level, asked
    # in creation/occurrence_functions.py.
    add_occurrence(pair_interface, scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache)

    # Unlike phases, a PhasePairInterface is already completely built here (nothing is
    # added later) - so it goes straight into the datagraph, not onto the to-do list
    # (otherwise the entity would never end up in the finished RO-Crate, only its PVs,
    # which would point via cpo:isProcessVariableOf at an entity that does not exist).
    add_entity(datagraph, pair_interface)
    return pair_interface


def get_or_create_phase_interface(phase: dict, phase_interfaces: dict, scope: str, nr: int, namespace_collection: dict, datagraph: dict, todo_list: list, local_todo_list: list, evidence_known_cache: dict = None, series_phase_interfaces: dict = None):
    """Return the aggregating PhaseInterface of a phase - the entire boundary surface of
    that one phase, isPhaseInterfaceOf qualifiedCardinality 1 by the ontology - creating it
    where it does not exist yet.

    phase_interfaces is a plain {phase_id: PhaseInterface} cache, so that only a single
    PhaseInterface comes into being per phase however many PhasePairInterfaces are added
    later. For the series call it is the same instance as series_phase_interfaces (see
    create_interfaces_for_phases); at experiment level it is a fresh cache valid for that one
    experiment only. series_phase_interfaces is only read here, to link the new experiment
    PhaseInterface to its series counterpart through hlo:specializationOf.
    """
    if phase["@id"] in phase_interfaces:
        return phase_interfaces[phase["@id"]]

    interface_type = check_type("cpo:PhaseInterface", namespace_collection)
    experiment_number = nr if scope == "hlo:ExperimentSpecific" else None
    interface_id = generate_id_from_name(f"PhaseInterface_{short_local_name(phase['@id'])}", scope, experiment_number)

    phase_interface = {
        "@id": interface_id,
        "@type": [interface_type, scope]
    }
    set_property(phase_interface, "schema:name", f"{get_display_label(phase)} Interface", namespace_collection)
    # no reasoner: set both directions explicitly (as in create_phase_pair_interface)
    set_property(phase_interface, "cpo:isPhaseInterfaceOf", phase, namespace_collection)
    set_property(phase, "cpo:hasPhaseInterface", phase_interface, namespace_collection)

    if scope == "hlo:ExperimentSpecific" and series_phase_interfaces is not None:
        series_phase = get_series_entity(phase, datagraph)
        series_interface = series_phase_interfaces.get(series_phase["@id"]) if series_phase else None
        if series_interface:
            set_property(phase_interface, "hlo:specializationOf", series_interface, namespace_collection)
            set_property(series_interface, "hlo:hasSpecialization", phase_interface, namespace_collection, True)

    # A segment of its own per phase (via its @id, not via an ambient loop position -
    # get_or_create_phase_interface is called from several different places that are not wrapped
    # per phase themselves, see create_interfaces_for_material_phases/
    # add_cross_material_interfaces): otherwise the hasArea questions of several PhaseInterfaces
    # would share the same key. Directly under the level (under=): created from an interface
    # between materials, the question otherwise stood under the pair that came first
    # (counter-check P4).
    # Header line as for phases and tasks (AP9).
    print(f"\n=== Now describing Phase Interface \"{get_display_label(phase_interface)}\" ({interface_id}, {scope}{f', Experiment {nr}' if experiment_number else ''}) ===")
    with question_path("phase_interface", key_name(phase["@id"]), under=("series", "experiment")):
        add_phase_process_variable(phase_interface, "cpo:hasArea", scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache)

    # As for the PhasePairInterface: already completely built -> straight into the datagraph.
    add_entity(datagraph, phase_interface)
    phase_interfaces[phase["@id"]] = phase_interface
    return phase_interface


def create_interfaces_for_material_phases(phases: list, phase_interfaces: dict, scope: str, nr: int, namespace_collection: dict, datagraph: dict, chemical_entity_library: dict, todo_list: list, local_todo_list: list, evidence_known_cache: dict = None, series_phase_interfaces: dict = None, series_pair_interfaces: dict = None, series_transfers: dict = None):
    """Create a PhasePairInterface automatically, without asking, for every pair of phases
    within the SAME MaterialRepresentation - the assumption being that phases in the same
    material always touch each other.
    """
    for i in range(len(phases)):
        for j in range(i + 1, len(phases)):
            phase_a, phase_b = phases[i], phases[j]
            interface_a = get_or_create_phase_interface(phase_a, phase_interfaces, scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache, series_phase_interfaces)
            interface_b = get_or_create_phase_interface(phase_b, phase_interfaces, scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache, series_phase_interfaces)
            # A segment of its own per pair of phases (via the @ids, not via the (i,j) loop
            # position - see get_or_create_phase_interface above): otherwise the transfer
            # questions (handle_transfers_for_pair_interface) of several PhasePairInterfaces
            # within the same material would share the same key.
            pair_identity = frozenset({phase_a["@id"], phase_b["@id"]})
            with question_path("phase_pair_interface", key_name(pair_identity)):
                create_phase_pair_interface(phase_a, phase_b, interface_a, interface_b, scope, nr, namespace_collection, datagraph, chemical_entity_library, todo_list, local_todo_list, evidence_known_cache, series_pair_interfaces, series_transfers)


def create_contained_material_interfaces(phases: list, phase_interfaces: dict, scope: str, nr: int, namespace_collection: dict, datagraph: dict, chemical_entity_library: dict, todo_list: list, local_todo_list: list, evidence_known_cache: dict = None, series_phase_interfaces: dict = None, series_pair_interfaces: dict = None, series_transfers: dict = None):
    """Create a PhasePairInterface automatically, without asking, between every body phase
    and every contained phase, for each device that has both a body material
    (cpo:madeOfMaterial) AND a contained material (cpo:containsMaterial) - the wall touches what it
    encloses, and that needs no question.

    The same assumption one level up from create_interfaces_for_material_phases, where phases
    within the same material touch.

    What is left for add_cross_material_interfaces afterwards is exactly what does NOT follow
    from the structure: device against device, device against room air, and internals such as
    stirrers that carry no cpo:containsMaterial at all.

    Runs at both levels without any series bookkeeping: every experiment has its own device
    with its own contains/madeOfMaterial (see creation/device_functions.py), so the
    assignment follows afresh from the graph at each level - unlike the cross-material pairs
    that are asked for and have to be passed on through series_cross_material_pairs.
    """
    phases_by_material = {}
    for phase in phases:
        material_ref = phase.get("dcterms:isPartOf")
        material_id = material_ref.get("@id") if isinstance(material_ref, dict) else material_ref
        phases_by_material.setdefault(material_id, []).append(phase)

    # Snapshot of the entity list: create_phase_pair_interface appends new entities to
    # @graph, which we would otherwise stumble over in the middle of our own loop.
    for entity in list(datagraph.get("@graph", [])):
        contained_ref = entity.get("cpo:containsMaterial")
        body_refs = entity.get("cpo:madeOfMaterial")
        if not contained_ref or not body_refs:
            continue

        contained_id = contained_ref.get("@id") if isinstance(contained_ref, dict) else contained_ref
        contained_phases = phases_by_material.get(contained_id, [])
        if not contained_phases:
            # A device of another scope (series vs. experiment) or a material that has no
            # phases (yet) - neither is an error, there is just nothing to do here.
            continue

        if isinstance(body_refs, dict):
            body_refs = [body_refs]
        for body_ref in body_refs:
            body_id = body_ref.get("@id") if isinstance(body_ref, dict) else body_ref
            for body_phase in _phases_facing_contents(phases_by_material.get(body_id, []), body_id, datagraph):
                for contained_phase in contained_phases:
                    interface_a = get_or_create_phase_interface(body_phase, phase_interfaces, scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache, series_phase_interfaces)
                    interface_b = get_or_create_phase_interface(contained_phase, phase_interfaces, scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache, series_phase_interfaces)
                    # The same key scheme as for the other three callers of
                    # create_phase_pair_interface (see create_interfaces_for_material_phases).
                    pair_identity = frozenset({body_phase["@id"], contained_phase["@id"]})
                    with question_path("phase_pair_interface", key_name(pair_identity)):
                        create_phase_pair_interface(body_phase, contained_phase, interface_a, interface_b, scope, nr, namespace_collection, datagraph, chemical_entity_library, todo_list, local_todo_list, evidence_known_cache, series_pair_interfaces, series_transfers)


def _fixed_counterpart(entity_id: str, datagraph: dict):
    """Follow hlo:specializationOf up to the library entry (or the topmost entity there is)."""
    entity = resolve(datagraph, entity_id)
    seen = set()
    while entity is not None and entity.get("hlo:specializationOf") and entity["@id"] not in seen:
        seen.add(entity["@id"])
        parent = get_series_entity(entity, datagraph)
        if parent is None:
            break
        entity = parent
    return entity


def _phases_facing_contents(body_phases: list, body_id: str, datagraph: dict) -> list:
    """The phases of a body material that touch what the device holds. A wall of several layers
    names its inner layer in the library (cpo:hasInnerLayer on the body material, rule 3.8a):
    only the phase that specializes that layer touches the contents. Without the property -
    a body of one phase - every phase does."""
    fixed_body = _fixed_counterpart(body_id, datagraph)
    inner_ids = set(ref_ids(fixed_body.get("cpo:hasInnerLayer"))) if fixed_body else set()
    if not inner_ids:
        return body_phases
    # If the inner layer covers only part, the content also touches the layer below -
    # then as without the statement: all phases (careful, but never wrong).
    for inner_id in inner_ids:
        inner = resolve(datagraph, inner_id)
        layer_form = resolve(datagraph, ref_id(inner.get("cpo:fillsForm"))) if inner and inner.get("cpo:fillsForm") else None
        if layer_form is not None and ref_id(layer_form.get("cpo:hasLayerCoverage")) == "cpo:PartialCoverage":
            return body_phases
    facing = []
    for phase in body_phases:
        fixed_phase = _fixed_counterpart(phase["@id"], datagraph)
        if fixed_phase is not None and fixed_phase["@id"] in inner_ids:
            facing.append(phase)
    return facing


def _phases_already_paired_with(phase: dict, datagraph: dict) -> set:
    """The @ids of every phase that already shares a PhasePairInterface with this phase -
    through cpo:isSeparatedByInterface (phase -> interface, set in
    create_phase_pair_interface) and back again through cpo:separatesPhases.

    The phase itself is included, which is exactly right for the only caller
    (add_cross_material_interfaces).
    """
    paired_ids = set()
    interface_refs = phase.get("cpo:isSeparatedByInterface", [])
    if isinstance(interface_refs, dict):
        interface_refs = [interface_refs]
    for interface_ref in interface_refs:
        interface_id = interface_ref.get("@id") if isinstance(interface_ref, dict) else interface_ref
        interface = find_entity(datagraph, interface_id) if interface_id else None
        if interface is None:
            continue
        phase_refs = interface.get("cpo:separatesPhases", [])
        if isinstance(phase_refs, dict):
            phase_refs = [phase_refs]
        for phase_ref in phase_refs:
            paired_ids.add(phase_ref.get("@id") if isinstance(phase_ref, dict) else phase_ref)
    return paired_ids


def _phase_pair_list(phases: list):
    """answer_type for a list of phase pairs "phase + phase; phase + phase" (see
    create_cross_material_interfaces). Returns [(phase_a_id, phase_b_id), ...] in the order
    given; each side is matched against the phase labels like a single choice."""
    labels = [phase_label(p) for p in phases]
    ids = {label: p["@id"] for label, p in zip(labels, phases)}

    def parse(text):
        pairs = []
        for item in str(text).split(LIST_SEPARATOR):
            item = item.strip()
            if not item:
                continue
            sides = [side.strip() for side in item.split("+")]
            if len(sides) != 2:
                raise ValueError(f"'{item}' is not of the form 'phase + phase'")
            matched = [match_option(side, labels) for side in sides]
            if None in matched:
                raise ValueError(f"'{item}' names a phase that is not one of the options")
            if matched[0] == matched[1]:
                raise ValueError(f"'{item}' pairs a phase with itself")
            pair = (ids[matched[0]], ids[matched[1]])
            if frozenset(pair) in {frozenset(p) for p in pairs}:
                raise ValueError(f"'{item}' is named twice")
            pairs.append(pair)
        return pairs

    parse.__name__ = f"list of 'phase + phase', separated by '{LIST_SEPARATOR}'"
    return parse


def _room_air_contacts(phases: list, datagraph: dict) -> list:
    """(body phase, room air phase) for every device that stands directly in the room air - cpo:locatedInsideOf
    an Environment of this level -, with the phases of its body that face outwards (rule 3b.1: every device
    standing in the air borders on the room air). Those are the body phases that do
    not touch the contents (see _phases_facing_contents), and every phase of a body of one phase. A device without
    a body of its own - a line whose content comes from a nameless source - has nothing that could border on the
    air; a device mounted on another one (a jacket, a sensor in a lid) is located at that device and stays a
    question (add_cross_material_interfaces)."""
    phases_by_material = {}
    for phase in phases:
        phases_by_material.setdefault(ref_id(phase.get("dcterms:isPartOf")), []).append(phase)
    pairs = []
    for entity in list(datagraph.get("@graph", [])):
        body_ids = ref_ids(entity.get("cpo:madeOfMaterial"))
        if not body_ids:
            continue
        for place_id in ref_ids(entity.get("cpo:locatedInsideOf")):
            place = find_entity(datagraph, place_id)
            if place is None or "cpo:Environment" not in as_list(place.get("@type")):
                continue
            for body_id in body_ids:
                body_phases = phases_by_material.get(body_id, [])
                inner = _phases_facing_contents(body_phases, body_id, datagraph)
                outer = [p for p in body_phases if p not in inner] or body_phases
                pairs += [(body_phase, air_phase) for body_phase in outer for air_phase in phases_by_material.get(place_id, [])]
    return pairs


def add_cross_material_interfaces(phases: list, phase_interfaces: dict, scope: str, nr: int, namespace_collection: dict, datagraph: dict, chemical_entity_library: dict, todo_list: list, local_todo_list: list, evidence_known_cache: dict = None, series_phase_interfaces: dict = None, series_pair_interfaces: dict = None, series_transfers: dict = None, series_cross_material_pairs: list = None):
    """Interfaces between phases of DIFFERENT MaterialRepresentations - a phase in a stream
    touching a phase in a MaterialVolume, for instance. This cannot be recognised
    automatically and is therefore asked about once, at series level; every pair chosen also
    lands in series_cross_material_pairs.

    At experiment level nothing is asked again: for every pair remembered at series level,
    the matching pair of the current experiment phases is connected automatically - exactly
    as for the interfaces recognised automatically within a material (see
    create_interfaces_for_material_phases).

    Stream phases are expressly among the choices here: a stream touches the wall it runs
    through (coolant in the jacket against the jacket wall, gas in the sparger against the
    sparger wall), and the heat coupling runs over precisely this PhasePairInterface
    (hlo:isCoupledWith, see link_phase_couplings). Mass transfer at the ends of a stream is a
    different matter and has been handled earlier by create_port_crossing_transfers, as a
    port-crossing transfer rather than an interface - the two do not exclude each other.

    Everything that already follows from the structure has been created by this point
    (create_interfaces_for_material_phases, create_contained_material_interfaces); what is
    left here are only the contacts that appear nowhere in the graph.

    Pairs already connected are filtered out of the choice (see _phases_already_paired_with),
    so that a pair is not created a second time by accident - above all two phases of the same
    material, which create_interfaces_for_material_phases has already connected
    automatically.

    The contact of every device standing directly in the room air is created here first, without asking (_room_air_contacts, rule 3b.1) - under the same
    question path as an asked pair, so that the answers recorded for such pairs still fit, and
    remembered for the experiments like an asked one. An answer that names such a pair is skipped
    as already connected.
    """
    if len(phases) < 2:
        return

    if scope == "hlo:SeriesSpecific":
        phases_by_id = {p["@id"]: p for p in phases}

        for phase_a, phase_b in _room_air_contacts(phases, datagraph):
            if phase_b["@id"] in _phases_already_paired_with(phase_a, datagraph):
                continue
            with question_path("cross_material_interface", key_name(frozenset({phase_a["@id"], phase_b["@id"]}))):
                interface_a = get_or_create_phase_interface(phase_a, phase_interfaces, scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache, series_phase_interfaces)
                interface_b = get_or_create_phase_interface(phase_b, phase_interfaces, scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache, series_phase_interfaces)
                pair_identity = frozenset({phase_a["@id"], phase_b["@id"]})
                with question_path("phase_pair_interface", key_name(pair_identity)):
                    create_phase_pair_interface(phase_a, phase_b, interface_a, interface_b, scope, nr, namespace_collection, datagraph, chemical_entity_library, todo_list, local_todo_list, evidence_known_cache, series_pair_interfaces, series_transfers)
            if series_cross_material_pairs is not None:
                series_cross_material_pairs.append((phase_a["@id"], phase_b["@id"]))

        # The pairs as one list "phase A + phase B" instead of "another one?" with a counter
        # (step 7, group A); every pair then stands under its name. Labels instead of raw
        # @ids (phase_label, as in every other question about phases).
        pairs = ask_user(
            f"[{scope}] Which further Phase Interfaces between phases of different materials have not been recorded yet? "
            f"Each as 'phase + phase', separated by ';' (leave empty if none) [{', '.join(phase_label(p) for p in phases)}]",
            answer_type=_phase_pair_list(phases), question_id="cross_material_pairs"
        )
        for phase_a_id, phase_b_id in pairs:
            phase_a, phase_b = phases_by_id[phase_a_id], phases_by_id[phase_b_id]
            if phase_b_id in _phases_already_paired_with(phase_a, datagraph):
                print(f"[interfaces] {phase_label(phase_a)} and {phase_label(phase_b)} are already connected - nothing to add here.")
                continue
            with question_path("cross_material_interface", key_name(frozenset({phase_a_id, phase_b_id}))):
                interface_a = get_or_create_phase_interface(phase_a, phase_interfaces, scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache, series_phase_interfaces)
                interface_b = get_or_create_phase_interface(phase_b, phase_interfaces, scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache, series_phase_interfaces)
                # A "phase_pair_interface:N" segment of its own, as for the other two callers of
                # create_phase_pair_interface (create_interfaces_for_material_phases, the
                # ExperimentSpecific branch below) - exactly one pair interface per
                # cross_material_interface:i iteration (break before the create call if "No"),
                # so no risk of collisions within the segment, only consistency with the key
                # scheme that is the same everywhere else.
                pair_identity = frozenset({phase_a["@id"], phase_b["@id"]})
                with question_path("phase_pair_interface", key_name(pair_identity)):
                    create_phase_pair_interface(phase_a, phase_b, interface_a, interface_b, scope, nr, namespace_collection, datagraph, chemical_entity_library, todo_list, local_todo_list, evidence_known_cache, series_pair_interfaces, series_transfers)

                if series_cross_material_pairs is not None:
                    series_cross_material_pairs.append((phase_a_id, phase_b_id))
        return

    # ExperimentSpecific: no question - every pair asked on the series level is carried
    # over automatically to the current (experiment) phases.
    if not series_cross_material_pairs:
        return

    phases_by_series_id = {}
    for phase in phases:
        series_phase = get_series_entity(phase, datagraph)
        if series_phase:
            phases_by_series_id[series_phase["@id"]] = phase

    for series_phase_a_id, series_phase_b_id in series_cross_material_pairs:
        phase_a = phases_by_series_id.get(series_phase_a_id)
        phase_b = phases_by_series_id.get(series_phase_b_id)
        if not phase_a or not phase_b:
            continue

        interface_a = get_or_create_phase_interface(phase_a, phase_interfaces, scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache, series_phase_interfaces)
        interface_b = get_or_create_phase_interface(phase_b, phase_interfaces, scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache, series_phase_interfaces)
        # See create_interfaces_for_material_phases - the same safeguard for the
        # cross-material case replayed automatically on the ExperimentSpecific level.
        pair_identity = frozenset({phase_a["@id"], phase_b["@id"]})
        with question_path("phase_pair_interface", key_name(pair_identity)):
            create_phase_pair_interface(phase_a, phase_b, interface_a, interface_b, scope, nr, namespace_collection, datagraph, chemical_entity_library, todo_list, local_todo_list, evidence_known_cache, series_pair_interfaces, series_transfers)


# ---------------------------------------------------------------------------
# PortCrossing: a stream end that hangs at a cpo:DevicePort transfers material
# between the stream phase and the phase that sits in the device at this port.
# At cpo:Source/cpo:Sink (the system boundary) no transfer is made - that follows
# purely structurally from Source/Sink not being DevicePorts. Replaces the former
# cross-material interfaces between stream phases, which were informally misused
# (see the filter in create_interfaces_for_phases).
# ---------------------------------------------------------------------------

def _stream_of_phase(phase: dict, datagraph: dict):
    """Return the stream entity this phase belongs to, or None."""
    material_ref = phase.get("dcterms:isPartOf")
    material_id = material_ref.get("@id") if isinstance(material_ref, dict) else material_ref
    material = find_entity(datagraph, material_id) if material_id else None
    if material is not None and "cpo:Stream" in (material.get("@type") or []):
        return material
    return None


def _resolve_device_side_phase(port: dict, phases_by_id: dict, scope: str, datagraph: dict):
    """Determine the phase on the device side of a DevicePort for a port-crossing transfer,
    through cpo:isPortOf -> cpo:containsMaterial -> dcterms:hasPart.

    Where exactly one phase is found it is used automatically; where there are several or
    none, the user is asked, with "no port crossing at this end" as a way out.
    """
    device_ref = port.get("cpo:isPortOf")
    device_id = device_ref.get("@id") if isinstance(device_ref, dict) else device_ref
    device = find_entity(datagraph, device_id) if device_id else None

    candidate_phases = []
    if device is not None:
        material_ref = device.get("cpo:containsMaterial")
        material_id = material_ref.get("@id") if isinstance(material_ref, dict) else material_ref
        material = find_entity(datagraph, material_id) if material_id else None
        if material is not None:
            part_refs = material.get("dcterms:hasPart", [])
            part_refs = part_refs if isinstance(part_refs, list) else [part_refs]
            for part_ref in part_refs:
                part_id = part_ref.get("@id") if isinstance(part_ref, dict) else part_ref
                phase = phases_by_id.get(part_id)
                if phase is not None:
                    candidate_phases.append(phase)

    if len(candidate_phases) == 1:
        return candidate_phases[0]

    skip_option = "No device-side phase (skip this PortCrossing)"
    device_label = get_display_label(device) if device else port["@id"]
    if candidate_phases:
        chosen = ask_entity_choice(
            f"[{scope}] Which phase inside {device_label} is on the other side of port {get_display_label(port)}?",
            candidate_phases, extra_options=[skip_option], label_fn=phase_label, question_id="device_side_phase"
        )
    else:
        chosen = ask_entity_choice(
            f"[{scope}] {device_label} has no automatically resolvable contained phase at port {get_display_label(port)}. Which phase is on the device side of this port crossing?",
            list(phases_by_id.values()), extra_options=[skip_option], label_fn=phase_label, question_id="device_side_phase"
        )
    if chosen == skip_option:
        return None
    return phases_by_id.get(chosen)


def _port_opens_into(port: dict, datagraph: dict):
    """The library device whose content the port discharges into (cpo:opensInto, read up the
    hlo:specializationOf chain), or None for a port that leads into a line."""
    seen, current = set(), port
    while current is not None and current["@id"] not in seen:
        if current.get("cpo:opensInto"):
            return ref_id(current["cpo:opensInto"])
        seen.add(current["@id"])
        current = resolve(datagraph, ref_id(current.get("hlo:specializationOf"))) if current.get("hlo:specializationOf") else None
    return None


def _port_connected_to(port: dict, datagraph: dict):
    """The library port this port is joined to (cpo:isConnectedTo, rule 3a.9; read up the
    hlo:specializationOf chain like cpo:opensInto), or None."""
    seen, current = set(), port
    while current is not None and current["@id"] not in seen:
        if current.get("cpo:isConnectedTo"):
            return ref_id(current["cpo:isConnectedTo"])
        seen.add(current["@id"])
        current = resolve(datagraph, ref_id(current.get("hlo:specializationOf"))) if current.get("hlo:specializationOf") else None
    return None


def _reaches(entity, target: str, datagraph: dict) -> bool:
    """Whether entity is target or specializes it (up the hlo:specializationOf chain)."""
    seen = set()
    while entity is not None and entity["@id"] not in seen:
        if entity["@id"] == target:
            return True
        seen.add(entity["@id"])
        entity = resolve(datagraph, ref_id(entity.get("hlo:specializationOf"))) if entity.get("hlo:specializationOf") else None
    return False


def _phase_in_content_of(device_id: str, port: dict, phases: list, scope: str, datagraph: dict):
    """The phase of the content of device_id (a library device) that a port opening into it leads
    to - asked among the phases of the materials the device holds on this level."""
    candidates = []
    for phase in phases:
        material = resolve(datagraph, ref_id(phase.get("dcterms:isPartOf")))
        device = resolve(datagraph, ref_id(material.get("cpo:materialContainedIn"))) if material else None
        if device is not None and _reaches(device, device_id, datagraph):
            candidates.append(phase)
    if not candidates:
        print(f"[{scope}] {get_display_label(port)} opens into {device_id}, which holds no phase on this level - no crossing.")
        return None
    # "None": a phase of a stream with several that has no counterpart behind the port - the air core of the
    # outlet over a beaker without a gas phase of its own; as at device_side_phase.
    skip_option = "No phase (skip this PortCrossing)"
    chosen = ask_entity_choice(
        f"[{scope}] {get_display_label(port)} opens into the content of {device_id}. Which phase does it lead into?",
        candidates, extra_options=[skip_option], label_fn=phase_label, question_id="opens_into_phase"
    )
    return next((p for p in candidates if p["@id"] == chosen), None)


# Per series stream with several phases: the series phases that cross at its ends (rule 3b.2) - the
# experiments take them over instead of being asked again. Lives for one run.
_SERIES_CROSSING_PHASES = {}


def _stream_ends_at_device_ports(phases: list, phases_by_id: dict, scope: str, datagraph: dict, namespace_collection: dict) -> list:
    """A list of (stream, stream_phase, port, is_source, multiphase) for every stream end that hangs
    off a cpo:DevicePort - one per phase that crosses there.

    A stream with one phase: that phase. A stream with several (a suspension with a gas core: liquid,
    solid and gas flow together, pba_synthesis) - which of them cross at its ends, as a list: each
    crossing phase gets its own crossing with its own phase on the device side (rule 3b.2).
    multiphase says whether
    the stream had several phases - then the phase is part of the key of the stream end."""
    device_port_ids = {p["@id"] for p in find_entities_by_type(datagraph, "cpo:DevicePort", namespace_collection, include_subclasses=True)}

    phases_by_stream = {}
    for phase in phases:
        stream = _stream_of_phase(phase, datagraph)
        if stream is None:
            continue
        phases_by_stream.setdefault(stream["@id"], [stream, []])[1].append(phase)

    stream_ends = []
    for stream, stream_phases in phases_by_stream.values():
      with question_path("stream_port_ends", key_name(stream["@id"])):
        multiphase = len(stream_phases) > 1
        if not multiphase:
            crossing = stream_phases
        elif scope == "hlo:SeriesSpecific":
            chosen = ask_entity_list(
                f"[{scope}] {get_display_label(stream)} has several phases - which of them cross at its ends (its ports)? "
                f"Each gets its own PortCrossing transfers.",
                stream_phases, label_fn=phase_label, question_id="crossing_stream_phases", required=True
            )
            crossing = [phases_by_id[phase_id] for phase_id in chosen]
            _SERIES_CROSSING_PHASES[stream["@id"]] = {p["@id"] for p in crossing}
        else:
            # The experiment takes over the choice of the series (the phases specializing the chosen ones).
            series_stream = get_series_entity(stream, datagraph)
            chosen = _SERIES_CROSSING_PHASES.get(series_stream["@id"], set()) if series_stream else set()
            crossing = [p for p in stream_phases if (get_series_entity(p, datagraph) or {}).get("@id") in chosen]

        for stream_phase in crossing:
            for prop, is_source in (("cpo:flowsFrom", True), ("cpo:flowsTo", False)):
                port_ref = stream.get(prop)
                port_id = port_ref.get("@id") if isinstance(port_ref, dict) else port_ref
                port = find_entity(datagraph, port_id) if port_id else None
                if port is not None and port["@id"] in device_port_ids:
                    stream_ends.append((stream, stream_phase, port, is_source, multiphase))

    return stream_ends


def _stream_end_key(stream: dict, port: dict, stream_phase: dict = None, multiphase: bool = False) -> str:
    """Question-path key of a stream end: which stream at which port. Both are needed -
    several streams hang off one port, and one stream off two ports. For a stream with several
    crossing phases also which phase; a stream with one phase keeps its key."""
    key = f"{key_name(stream['@id'])}-{key_name(port['@id'])}"
    return f"{key}-{key_name(stream_phase['@id'])}" if multiphase and stream_phase else key


def _end_id(port: dict, stream: dict, stream_phase: dict) -> tuple:
    """The key of a stream end in the caches (series_port_crossings, _SERIES_PORT_ENDS): port, stream and
    the phase crossing there - one stream can have several crossing phases."""
    return (port["@id"], stream["@id"], stream_phase["@id"])


def create_port_crossing_transfers(phases: list, scope: str, nr: int, namespace_collection: dict, datagraph: dict, chemical_entity_library: dict, todo_list: list, local_todo_list: list, evidence_known_cache: dict = None, series_port_crossings: dict = None):
    """Create exactly one cpo:PortCrossing transfer for every stream end that hangs off a
    cpo:DevicePort.

    Every transfer gets its own cpo:hasFlowrate (a molar flow rate), separate from the
    stream's (a volume flow rate; see helpers/transfer_functions.py: create_transfer_at_port). At series level the device phase is
    resolved or asked for; at experiment level the assignment is carried over one to one from
    series_port_crossings and given an occurrence and a time in addition.

    Not every stream end at a device port is a crossing: where the stream carries the very
    phase the device contains, the stream lies inside the device and only begins or ends at
    that port. Such an end is skipped (see the check on stream_phase below).

    series_port_crossings is a {(series_port_id, series_stream_id, series_stream_phase_id): [transfer]}
    cache (with the phase: a stream can have several crossing phases). The key
    MUST contain port and stream: several streams often hang off one port - nine off vessel001_opening in
    this crate - and a stream end is only uniquely determined by port AND stream. With the
    port alone as the key, every further stream end would overwrite the entries of the
    previous ones, and the experiment level would reach for the transfers of the last one
    entered for all of them.
    """
    phases_by_id = {p["@id"]: p for p in phases}
    stream_ends = _stream_ends_at_device_ports(phases, phases_by_id, scope, datagraph, namespace_collection)

    if scope == "hlo:SeriesSpecific":
        created = {}
        for stream, stream_phase, port, is_source, multiphase in stream_ends:
          end_key = _stream_end_key(stream, port, stream_phase, multiphase)
          with question_path("port_crossing", end_key):
            device_phase = _resolve_device_side_phase(port, phases_by_id, scope, datagraph)
            if device_phase is None:
                continue

            if device_phase["@id"] == stream_phase["@id"] and _port_opens_into(port, datagraph):
                # The stream lies in the device, and the port opens into the content of ANOTHER
                # device (cpo:opensInto, rule 3b.6): the outlet of the sparger sits in the
                # vessel. Behind the port there is no further stream - the crossing goes directly
                # from the phase of the stream into a phase of that content (the bubbles), in the
                # direction of flow.
                device_phase = _phase_in_content_of(_port_opens_into(port, datagraph), port, phases, scope, datagraph)
                if device_phase is None:
                    continue
            elif device_phase["@id"] == stream_phase["@id"] and _port_connected_to(port, datagraph):
                # The stream lies in the device, and its port is screwed to the port of another device
                # (cpo:isConnectedTo, rule 3a.9): what goes out here comes in there. The crossing
                # goes from the phase of the one stream into the content of the other device - ONCE per
                # connection: if a stream ends on the other side (it reaches the counterpart port), the
                # end that lies ahead in the direction of flow creates it; the one behind (the stream
                # leaves its device here) only if there is none over there.
                joint = _port_connected_to(port, datagraph)
                if is_source and any(not other_is_source and other_stream is not stream and _reaches(other_port, joint, datagraph)
                                     for other_stream, _, other_port, other_is_source, _ in stream_ends):
                    continue
                joint_port = resolve(datagraph, joint)
                joint_device = ref_id(joint_port.get("cpo:isPortOf")) if joint_port else None
                device_phase = _phase_in_content_of(joint_device, port, phases, scope, datagraph) if joint_device else None
                if device_phase is None:
                    continue
            elif device_phase["@id"] == stream_phase["@id"]:
                # The stream CARRIES exactly the phase the device contains - so it lies
                # in the device and only starts/ends at this port. Nothing crosses a
                # boundary here, and a transfer would be from the phase into itself
                # (removesFromPhase == addsToPhase).
                #
                # This is exactly how it stood in the crate: the CoolingFluid_Stream phase is at
                # the same time the content of jacket001, the Sparger_Stream phase at the same
                # time the content of sparger001. Both streams hang with BOTH ends at device
                # ports, which gave four such self-transfers per level - with occurrence,
                # times and flowrate. The real crossing at the same port is another one: there
                # the inlet or outlet phase crosses (Jacket_Inlet_Phase -> CoolingFluid_Phase).
                print(f"[{scope}] {get_display_label(stream)} carries the phase that {get_display_label(port)}'s "
                      f"device already contains - the stream lies inside the device, so nothing crosses here.")
                continue

            # flowsFrom: the stream leaves the port -> material moves from the device into the stream.
            # flowsTo: the stream reaches the port -> material moves from the stream into the device.
            source_phase, destination_phase = (device_phase, stream_phase) if is_source else (stream_phase, device_phase)
            # For the follow-up (follow_up_transfers): which phase crosses the port here as a whole.
            _SERIES_PORT_ENDS[_end_id(port, stream, stream_phase)] = (source_phase["@id"], destination_phase["@id"], end_key)

            # The whole stream phase crosses the port, so automatically ONE transfer per
            # species it contains instead of a question - with several species (e.g. a
            # solvent mixture) they all cross the same port together, but each with its own
            # flowrate (see link_stream_end_couplings for the coupling of the two ends).
            # Every species gets its own question segment.
            port_transfers = []
            for species_id in _species_in_phase(stream_phase):
                with question_path("transfer", transfer_name("cpo:PortCrossing", species_id, ref_id(source_phase), ref_id(destination_phase), datagraph, chemical_entity_library)):
                    port_transfers.append(get_or_create_transfer(
                        port, "port", species_id, "cpo:PortCrossing", scope, nr, namespace_collection, datagraph, chemical_entity_library, todo_list, local_todo_list,
                        source_phase=source_phase, destination_phase=destination_phase, evidence_known_cache=evidence_known_cache
                    ))
            created[_end_id(port, stream, stream_phase)] = port_transfers

        link_stream_end_couplings(created, namespace_collection, datagraph)
        link_single_path_port_couplings(scope, nr, namespace_collection, datagraph)
        if series_port_crossings is not None:
            series_port_crossings.update(created)
        return [transfer for transfers in created.values() for transfer in transfers]

    if not series_port_crossings:
        return []

    created = []
    created_by_end = {}
    # question_path("port_crossing", N) as in the SeriesSpecific branch above: without this
    # segment the transfers of ALL ports share the same key
    # (".../transfer:1/occurrence/have_evidence" for every single port), and ask_user
    # stops with "was about to be asked a second time in this run". That was never
    # noticed because this branch did not run at all: get_series_entity returned None
    # for every experiment port (multi-valued hlo:specializationOf, see
    # creation/device_functions.py) and the loop above always broke off.
    for stream, stream_phase, port, is_source, multiphase in stream_ends:
      with question_path("port_crossing", _stream_end_key(stream, port, stream_phase, multiphase)):
        series_port = get_series_entity(port, datagraph)
        series_stream = get_series_entity(stream, datagraph)
        series_phase = get_series_entity(stream_phase, datagraph)
        if series_port is None or series_stream is None or series_phase is None:
            continue
        series_transfers_at_port = series_port_crossings.get(_end_id(series_port, series_stream, series_phase))
        if not series_transfers_at_port:
            continue

        for series_transfer in series_transfers_at_port:
          with question_path("transfer", transfer_name_of(series_transfer, datagraph, chemical_entity_library)):
            device_series_ref = series_transfer.get("cpo:removesFromPhase") if is_source else series_transfer.get("cpo:addsToPhase")
            device_series_id = device_series_ref.get("@id") if isinstance(device_series_ref, dict) else device_series_ref
            device_phase = next((p for p in phases if (get_series_entity(p, datagraph) or {}).get("@id") == device_series_id), None)
            if device_phase is None:
                continue

            source_phase, destination_phase = (device_phase, stream_phase) if is_source else (stream_phase, device_phase)

            species_ref = series_transfer.get("cpo:transfersChemicalEntity")
            species_id = species_ref.get("@id") if isinstance(species_ref, dict) else species_ref
            if not keeps_species(species_id, nr, [source_phase, destination_phase], datagraph):
                continue    # the substance does not occur in this experiment (rule 3.13)

            transfer = get_or_create_transfer(
                port, "port", species_id, "cpo:PortCrossing", scope, nr, namespace_collection, datagraph, chemical_entity_library, todo_list, local_todo_list,
                source_phase=source_phase, destination_phase=destination_phase, evidence_known_cache=evidence_known_cache, series_transfer=series_transfer
            )
            add_occurrence(transfer, scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache)
            created.append(transfer)
            created_by_end.setdefault(_end_id(port, stream, stream_phase), []).append(transfer)

    link_stream_end_couplings(created_by_end, namespace_collection, datagraph)
    link_single_path_port_couplings(scope, nr, namespace_collection, datagraph)
    return created


# ---------------------------------------------------------------------------
# OccupationState: a chemical entity occupies/binds to an interface
# (adsorption/binding) - either at the whole (aggregating) PhaseInterface of a
# phase, or only at a specific PhasePairInterface below it. Asked only on the
# SeriesSpecific level (structural: which species, bound to what, which
# SorptionType) and taken over 1:1 on the ExperimentSpecific level - only
# hasOccupationExtent (how much is covered) is asked afresh per experiment, just
# as for transfers/hasFlowrate. A free site (nothing adsorbed) is explicitly
# included, see ask_occupation_states_for_phase_interface.
# ---------------------------------------------------------------------------

def sorption_types(namespace_collection):
    """The cpo:SorptionType individuals from the ontology (chemisorption/physisorption)."""
    return find_individuals_of_class("cpo:SorptionType", namespace_collection)
# The choice is the quantity kinds the ontology allows for cpo:hasOccupationExtent (rule 4.4).
# quantitykind:AreaRatio, not AreaFraction: that one does not exist in QUDT.


def _get_pair_interfaces_of(phase_interface: dict, datagraph: dict) -> list:
    """The PhasePairInterfaces belonging to an aggregating PhaseInterface
    (dcterms:hasPart)."""
    parts = phase_interface.get("dcterms:hasPart", [])
    parts = parts if isinstance(parts, list) else [parts]
    result = []
    for part_ref in parts:
        part_id = part_ref.get("@id") if isinstance(part_ref, dict) else part_ref
        entity = find_entity(datagraph, part_id)
        if entity:
            result.append(entity)
    return result


def get_interface_phases(interface: dict, datagraph: dict) -> list:
    """Return the phases belonging to an interface, regardless of its type:

      - cpo:PhasePairInterface -> cpo:separatesPhases (two phases)
      - cpo:PhaseInterface     -> cpo:isPhaseInterfaceOf (one phase)

    occursAtInterface and isSeparatedByInterface deliberately stay generic on Interface in the
    ontology, since a reaction can take place at either kind of interface. Every place that
    wants to get from an interface of any type to its phase or phases therefore uses this one
    switch rather than one of its own.

    An unknown or missing type is a bug - a place still reading the old separatesPhases
    property directly, now narrowed to PhasePairInterface, for instance - and is reported
    loudly rather than answered with a silent empty result.
    """
    type_list = as_list(interface.get("@type"))
    if "cpo:PhasePairInterface" in type_list:
        phase_refs = interface.get("cpo:separatesPhases", [])
    elif "cpo:PhaseInterface" in type_list:
        phase_refs = interface.get("cpo:isPhaseInterfaceOf", [])
    else:
        raise ValueError(
            f"get_interface_phases: interface '{interface.get('@id')}' has neither "
            f"cpo:PhaseInterface nor cpo:PhasePairInterface as @type ({type_list}) - "
            f"phases cannot be resolved."
        )
    phase_refs = phase_refs if isinstance(phase_refs, list) else [phase_refs]
    result = []
    for phase_ref in phase_refs:
        phase_id = phase_ref.get("@id") if isinstance(phase_ref, dict) else phase_ref
        phase = find_entity(datagraph, phase_id)
        if phase:
            result.append(phase)
    return result


def _interface_species_candidates(interface: dict, datagraph: dict) -> list:
    """The species of every phase belonging to this interface - one for a PhaseInterface,
    two for a PhasePairInterface."""
    species = []
    for phase in get_interface_phases(interface, datagraph):
        for species_id in _species_in_phase(phase):
            if species_id not in species:
                species.append(species_id)
    return species


def _resolve_occupation_species_for_scope(species_ref_id, target_interface: dict, scope: str, nr: int, namespace_collection: dict, datagraph: dict, chemical_entity_library: dict):
    """Resolve a cpo:occupiedBy/cpo:boundTo reference for the scope of target_interface,
    instead of carrying it over unchanged from another scope (see
    replay_occupation_states_for_phase_interface).

    For a chebi:Molecule it is resolved through fixed_chemical_entity_id to the fixed library
    entry and then resolved afresh with get_or_create_phase_molecule for the phase of THIS
    scope belonging to the interface - exactly as for transfers (see
    helpers/transfer_functions.py::_ensure_species_in_destination_phase). Non-molecule species
    (ions, radicals, ...) stay referenced unchanged by their fixed ID; they have no
    phase-specific instance.

    Which phase is the right one is determined by which of the one or two phases of
    target_interface has a SERIES counterpart that actually contains the species passed in
    (dcterms:hasPart). That identifies unambiguously which phase the reference came from, even
    where target_interface, being a PhasePairInterface, connects two phases.
    """
    if species_ref_id is None:
        return None

    fixed_entity_id = fixed_chemical_entity_id(species_ref_id, datagraph)
    fixed_entity = find_entity(chemical_entity_library, fixed_entity_id)
    if fixed_entity is None or not is_molecule(fixed_entity):
        return fixed_entity_id

    for phase in get_interface_phases(target_interface, datagraph):
        series_phase = get_series_entity(phase, datagraph)
        if series_phase and species_ref_id in _species_in_phase(series_phase):
            return get_or_create_phase_molecule(fixed_entity_id, phase, scope, nr, namespace_collection, datagraph, chemical_entity_library, series_phase)

    # Should not occur structurally (the species comes from one of the two phases of
    # target_interface) - the Fixed ID as a fallback instead of a wrong instance.
    return fixed_entity_id


def create_occupation_state_entity(interface: dict, name: str, occupied_by_id: str, bound_to_id, sorption_type: str, scope: str, nr: int, namespace_collection: dict, datagraph: dict, todo_list: list, local_todo_list: list, evidence_known_cache: dict = None, series_occupation_state: dict = None):
    """occupied_by_id and sorption_type may be None: a FREE site is an OccupationState
    without a cpo:occupiedBy, and consequently without a sorption type either - nothing is
    adsorbed after all.

    The ontology therefore requires both only for occupied sites; see the general class
    axioms for cpo:OccupationState in ChemicalProcessOntology.rdf. This is needed by
    creation/reaction_functions.py, where a placeholder such as "cat(H)" from the reaction
    library is resolved to a real free site.

    The ID is the name at the interface ("#OccupationState_cat-H_<interface>_<level>") -
    it used to count per interface, so reordering the list of occupation states swapped
    their IDs (step 7). Two occupation states of one interface need different
    names; claim_id says so otherwise.
    """
    occ_type = check_type("cpo:OccupationState", namespace_collection)
    occ_id = claim_id(make_owned_id(f"OccupationState_{slugify(name)}", interface["@id"]), datagraph, todo_list, local_todo_list,
                      what=f"The occupation state '{name}'")

    occupation_state = {"@id": occ_id, "@type": [occ_type, scope]}
    set_property(occupation_state, "schema:name", name, namespace_collection)
    set_property(occupation_state, "cpo:belongsToInterface", interface, namespace_collection)
    set_property(interface, "cpo:hasOccupationState", occupation_state, namespace_collection, True)
    if occupied_by_id:
        set_property(occupation_state, "cpo:occupiedBy", {"@id": occupied_by_id}, namespace_collection)
    if bound_to_id:
        set_property(occupation_state, "cpo:boundTo", {"@id": bound_to_id}, namespace_collection)
    # The sorption type stands once, where it is first said; an experiment state reads it from its series state
    # (rule 3.6).
    if sorption_type and series_occupation_state is None:
        set_property(occupation_state, "cpo:hasSorptionType", {"@id": sorption_type}, namespace_collection)

    if series_occupation_state is not None:
        set_property(occupation_state, "hlo:specializationOf", series_occupation_state, namespace_collection)
        set_property(series_occupation_state, "hlo:hasSpecialization", occupation_state, namespace_collection, True)

    add_phase_process_variable(occupation_state, "cpo:hasOccupationExtent", scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache)

    add_entity(datagraph, occupation_state)
    return occupation_state


def ask_occupation_states_for_phase_interface(phase_interface: dict, namespace_collection: dict, datagraph: dict, chemical_entity_library: dict, todo_list: list, local_todo_list: list, nr: int, evidence_known_cache: dict = None, series_occupation_states: dict = None):
    """At series level only: ask whether, and how often, this aggregating PhaseInterface -
    or one of its PhasePairInterfaces - is occupied.

    Every answer also lands in series_occupation_states, as a (target_interface_id,
    OccupationState) pair, so that replay_occupation_states_for_phase_interface can find it
    again at experiment level.

    Both occupied AND free sites are recorded (is_free_site): a free site has no
    cpo:occupiedBy and no sorption type, but it does have a cpo:boundTo pointing at its kind
    of site. That makes it possible to describe the whole set of possible occupations of a
    surface BEFORE the reactions come up - the placeholder resolution in
    creation/reaction_functions.py::_resolve_occupation_state_placeholder then offers the
    occupations created here for reuse, instead of creating the same occupation a second
    time.
    """
    scope = "hlo:SeriesSpecific"
    pair_interfaces = _get_pair_interfaces_of(phase_interface, datagraph)
    occupation_states = []

    # The occupations as one list of their names instead of "another one?" with a counter
    # (step 7, group A). The name matters more here than for most entities: when the reaction
    # placeholders are resolved, the occupations that exist already are offered for reuse
    # (see creation/reaction_functions.py::_resolve_occupation_state_placeholder) and are told
    # apart only by their name.
    occupation_names = ask_user(
        f"[{scope}] Which occupation states (adsorption/binding) can {interface_label(phase_interface)} have? "
        f"Their names (e.g. 'cat-H', 'cat(X)'), separated by ';' (leave empty if none)",
        answer_type=name_list, question_id="occupation_state_names"
    )
    for occupation_name in occupation_names:
        with question_path("occupation_state", slugify(occupation_name)):
            target_interface = phase_interface
            if pair_interfaces:
                target_interface = ask_entity_choice(
                    f"[{scope}] Does this occupation happen across the whole interface, or only at a specific phase pairing?",
                    pair_interfaces,
                    extra_options=["Whole interface"],
                    label_fn=interface_label,
                    question_id="target_interface"
                )
                if target_interface == "Whole interface":
                    target_interface = phase_interface
                else:
                    target_interface = find_entity(datagraph, target_interface)

            candidate_ids = _interface_species_candidates(target_interface, datagraph)
            candidates = [(sid, species_label(sid, chemical_entity_library, datagraph)) for sid in candidate_ids]

            # A FREE site is an OccupationState without cpo:occupiedBy - and without a
            # SorptionType, because nothing is adsorbed (see create_occupation_state_entity
            # and the general class axioms of cpo:OccupationState). cpo:boundTo is asked all
            # the same: a free site, too, sits on a particular kind of site ("cat(H)" is a
            # free H site, not just any). The same distinction as in
            # creation/reaction_functions.py::create_placeholder - without it free sites
            # could only be created through the reaction placeholders, not already when the
            # interfaces are described.
            free_site = ask_user(f"[{scope}] Is this a free (unoccupied) site?", ["Yes", "No"], question_id="is_free_site")
            occupied_by_id = None
            if free_site == "No":
                occupied_by_id = ask_chemical_entity(scope, f"entity occupying {interface_label(target_interface)}", namespace_collection, chemical_entity_library, extra_candidates=candidates, exclude_types=["cpo:ActiveSite"], question_id="occupied_by")

            occupant_label = species_label(occupied_by_id, chemical_entity_library, datagraph) if occupied_by_id else "this free site"
            bound_to_answer = ask_user(f"[{scope}] Does {occupant_label} bind to a specific chemical entity or group (e.g. an active site)?", ["Yes", "No"], question_id="has_bound_to")
            bound_to_id = None
            if bound_to_answer == "Yes":
                bound_to_id = ask_chemical_entity(scope, f"entity/group that {occupant_label} binds to", namespace_collection, chemical_entity_library, extra_candidates=candidates, question_id="bound_to")

            sorption_type = None
            if occupied_by_id:
                sorption_type = ask_user(f"[{scope}] Which type of sorption is this?", sorption_types(namespace_collection), question_id="sorption_type")

            occupation_state = create_occupation_state_entity(
                target_interface, occupation_name, occupied_by_id, bound_to_id, sorption_type,
                scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache
            )
            occupation_states.append((target_interface["@id"], occupation_state))

    if series_occupation_states is not None:
        series_occupation_states[phase_interface["@id"]] = occupation_states

    return occupation_states


def replay_occupation_states_for_phase_interface(phase_interface: dict, scope: str, nr: int, namespace_collection: dict, datagraph: dict, chemical_entity_library: dict, todo_list: list, local_todo_list: list, evidence_known_cache: dict = None, series_occupation_states: dict = None):
    """The experiment-level counterpart of ask_occupation_states_for_phase_interface: carry
    over the occupation states asked about at series level one to one - the sorption type,
    and whether they hang off the whole interface or only off a particular pair of phases,
    determined through the position of that pair within the series PhaseInterface - without
    asking again.

    Only hasOccupationExtent is asked for afresh per experiment, including the
    evidence/reference shortcut (see add_phase_process_variable).

    cpo:occupiedBy and cpo:boundTo are NOT carried over unchanged from the series occupation
    state: a series molecule instance on an experiment entity would make the same jump across
    scopes as the original transfer bug (see helpers/transfer_functions.py). They are resolved
    afresh through _resolve_occupation_species_for_scope for THIS scope, and for the
    experiment phase belonging to the respective target_interface.
    """
    if not series_occupation_states:
        return []

    series_phase_interface = get_series_entity(phase_interface, datagraph)
    if not series_phase_interface:
        return []

    recorded = series_occupation_states.get(series_phase_interface["@id"], [])
    if not recorded:
        return []

    pair_interfaces = _get_pair_interfaces_of(phase_interface, datagraph)
    series_pair_interfaces_list = _get_pair_interfaces_of(series_phase_interface, datagraph)

    created = []
    for series_target_id, series_occupation_state in recorded:
        if series_target_id == series_phase_interface["@id"]:
            target_interface = phase_interface
        else:
            index = next((i for i, p in enumerate(series_pair_interfaces_list) if p["@id"] == series_target_id), None)
            if index is None or index >= len(pair_interfaces):
                continue
            target_interface = pair_interfaces[index]

        occupied_by_ref = series_occupation_state.get("cpo:occupiedBy")
        occupied_by_series_id = occupied_by_ref.get("@id") if isinstance(occupied_by_ref, dict) else occupied_by_ref
        if occupied_by_series_id and not keeps_species(occupied_by_series_id, nr, get_interface_phases(target_interface, datagraph), datagraph):
            continue        # the substance does not occur in this experiment (rule 3.13)
        occupied_by_id = _resolve_occupation_species_for_scope(occupied_by_series_id, target_interface, scope, nr, namespace_collection, datagraph, chemical_entity_library)

        bound_to_ref = series_occupation_state.get("cpo:boundTo")
        bound_to_series_id = bound_to_ref.get("@id") if isinstance(bound_to_ref, dict) else bound_to_ref
        bound_to_id = _resolve_occupation_species_for_scope(bound_to_series_id, target_interface, scope, nr, namespace_collection, datagraph, chemical_entity_library)

        sorption_ref = series_occupation_state.get("cpo:hasSorptionType")
        sorption_type = sorption_ref.get("@id") if isinstance(sorption_ref, dict) else sorption_ref


        # The name of the series counterpart is taken over (not asked again) - it describes
        # WHAT is occupied ("cat-H"), and that is the same on the experiment level.
        # A segment of its own as on the series level (ask_occupation_states_for_phase_interface) -
        # without it two occupations of the same interface would share their keys.
        with question_path("occupation_state", slugify(get_display_label(series_occupation_state))):
            occupation_state = create_occupation_state_entity(
                target_interface, get_display_label(series_occupation_state), occupied_by_id, bound_to_id, sorption_type,
                scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache,
                series_occupation_state=series_occupation_state
            )
        created.append((target_interface["@id"], occupation_state))

    return created


def handle_occupation_states_for_phase_interface(phase_interface: dict, scope: str, nr: int, namespace_collection: dict, datagraph: dict, chemical_entity_library: dict, todo_list: list, local_todo_list: list, evidence_known_cache: dict = None, series_occupation_states: dict = None):
    if scope == "hlo:SeriesSpecific":
        return ask_occupation_states_for_phase_interface(phase_interface, namespace_collection, datagraph, chemical_entity_library, todo_list, local_todo_list, nr, evidence_known_cache, series_occupation_states)
    return replay_occupation_states_for_phase_interface(phase_interface, scope, nr, namespace_collection, datagraph, chemical_entity_library, todo_list, local_todo_list, evidence_known_cache, series_occupation_states)


def create_interfaces_for_phases(phases: list, scope: str, nr: int, namespace_collection: dict, datagraph: dict, chemical_entity_library: dict, todo_list: list, local_todo_list: list, evidence_known_cache: dict = None, series_phase_interfaces: dict = None, series_pair_interfaces: dict = None, series_transfers: dict = None, series_cross_material_pairs: list = None, series_occupation_states: dict = None, series_port_crossings: dict = None):
    """Group the phases by their MaterialRepresentation and then create all interfaces.

    At series level the local phase_interfaces cache IS series_phase_interfaces - it is
    written directly for the later linking of the experiment interfaces. At experiment level
    every experiment gets a fresh cache of its own, since the IDs differ, while
    series_phase_interfaces and series_pair_interfaces are only read, for linking to the
    series interfaces.

    Order: first the two automatic steps (phases within the same material, then the body wall
    against the contained material through cpo:containsMaterial), then
    create_port_crossing_transfers for mass transfer at the stream ends, which goes through
    cpo:PortCrossing rather than through an interface, and then the cross-material question
    for everything that simply touches.

    Stream phases are among the choices in that question - a stream touches the wall it runs
    through, and without this PhasePairInterface there would be no place for the heat coupling
    between coolant and jacket wall (see link_phase_couplings).
    """
    if len(phases) < 2:
        return

    experiment_suffix = f", Experiment {nr}" if scope == "hlo:ExperimentSpecific" else ""
    print(f"\n--- Interfaces: {scope}{experiment_suffix} ---")

    phases_by_material = {}
    for phase in phases:
        material_ref = phase.get("dcterms:isPartOf")
        material_id = material_ref.get("@id") if isinstance(material_ref, dict) else material_ref
        phases_by_material.setdefault(material_id, []).append(phase)

    if scope == "hlo:SeriesSpecific" and series_phase_interfaces is not None:
        phase_interfaces = series_phase_interfaces
    else:
        phase_interfaces = {}  # {phase_id: PhaseInterface} - shared across all materials

    for material_phases in phases_by_material.values():
        create_interfaces_for_material_phases(material_phases, phase_interfaces, scope, nr, namespace_collection, datagraph, chemical_entity_library, todo_list, local_todo_list, evidence_known_cache, series_phase_interfaces, series_pair_interfaces, series_transfers)

    # Wall to content: follows from cpo:containsMaterial/cpo:madeOfMaterial, so it is
    # created instead of asked (see create_contained_material_interfaces).
    create_contained_material_interfaces(phases, phase_interfaces, scope, nr, namespace_collection, datagraph, chemical_entity_library, todo_list, local_todo_list, evidence_known_cache, series_phase_interfaces, series_pair_interfaces, series_transfers)

    # PortCrossings first: they deal with the mass transfer at the ends of the streams
    # (a function of their own, questions of their own). What is left for the
    # cross-material query afterwards is the wall contact - including that of the stream phases.
    create_port_crossing_transfers(phases, scope, nr, namespace_collection, datagraph, chemical_entity_library, todo_list, local_todo_list, evidence_known_cache, series_port_crossings)

    add_cross_material_interfaces(phases, phase_interfaces, scope, nr, namespace_collection, datagraph, chemical_entity_library, todo_list, local_todo_list, evidence_known_cache, series_phase_interfaces, series_pair_interfaces, series_transfers, series_cross_material_pairs)

    # OccupationStates only AFTER all PhaseInterfaces/PhasePairInterfaces of this scope are
    # finished (also the cross-material ones), so that every PhaseInterface already has its
    # complete dcterms:hasPart list of PhasePairInterfaces.
    #
    # "phase_interface:N" here via the same stable_index identity (phase_id) as in
    # get_or_create_phase_interface (see there) - the same PhaseInterface thus gets the
    # same number everywhere, and without this segment the "occupation_state:i" questions
    # (each starting at 1) of several different PhaseInterfaces would share the same key.
    for phase_id, phase_interface in phase_interfaces.items():
        with question_path("phase_interface", key_name(phase_id)):
            handle_occupation_states_for_phase_interface(phase_interface, scope, nr, namespace_collection, datagraph, chemical_entity_library, todo_list, local_todo_list, evidence_known_cache, series_occupation_states)


# ---------------------------------------------------------------------------
# Couplings between phases across a common interface (hlo:isCoupledWith)
# ---------------------------------------------------------------------------
# An isCoupledWith between two actual values only says "these two influence each
# other physically" (e.g. the temperature of two phases with a common interface) -
# unlike hasEvidence/hasReference this is not about where knowledge comes from. A
# transfer parameter such as a heat transfer coefficient belongs later at the
# interface itself (cpo:PhasePairInterface) - not implemented here yet, but the
# structure (one PhasePairInterface per pair of phases) leaves room for it.

COUPLING_CANDIDATE_PROPERTIES = ["cpo:hasTemperature", "cpo:hasPressure"]


def link_phase_couplings(phase_a: dict, phase_b: dict, namespace_collection: dict, datagraph: dict):
    """Connect the Actual quantities of two phases sharing a PhasePairInterface through
    hlo:isCoupledWith, without asking.

    Two phases that touch influence each other physically, and that - and no more - is what
    isCoupledWith says, by its rdfs:comment in the HigherLevelOntology: nothing about
    direction, nothing about the values themselves. So it is not asked: a question per pair and
    quantity would always be answered "yes". Should an interface ever have to be marked as deliberately uncoupled, it
    would come back at exactly this place.

    Called from create_phase_pair_interface, so it applies to every pair interface - whether
    it arose within a material, through cpo:containsMaterial, or by being asked for. It is set
    explicitly in both directions (as for hasEvidence/isEvidenceOf), so that queries work
    without a reasoner even though isCoupledWith is declared an owl:SymmetricProperty.

    A transfer parameter such as a heat transfer coefficient does not belong here but on the
    interface itself (cpo:PhasePairInterface) - not implemented yet, but the structure, one
    PhasePairInterface per pair of phases, leaves room for it.
    """
    for property_name in COUPLING_CANDIDATE_PROPERTIES:
        ref_a = phase_a.get(property_name)
        ref_b = phase_b.get(property_name)
        if not ref_a or not ref_b:
            continue

        variable_a = find_entity(datagraph, ref_a["@id"])
        variable_b = find_entity(datagraph, ref_b["@id"])
        if not variable_a or not variable_b:
            continue

        set_property(variable_a, "hlo:isCoupledWith", variable_b, namespace_collection, True)
        set_property(variable_b, "hlo:isCoupledWith", variable_a, namespace_collection, True)

def link_single_path_port_couplings(scope: str, nr: int, namespace_collection: dict, datagraph: dict):
    """Connect the volume flowrates of the two streams at a port that has exactly one
    ingoing and one outgoing stream, through hlo:isCoupledWith.

    The condition "exactly one in, exactly one out" is the structural reason: what goes in at
    this port also comes out there again, and if the one stream
    changes, the other changes. How much, the coupling explicitly does NOT say -
    friction, compression or heating can change the volume flow. A formula
    for it would later be a calculated value, not a coupling.

    At the vessel opening this condition is violated (four incoming, three outgoing
    streams): which inlet belongs to which outlet cannot be
    decided there. They do belong together, only not in pairs - so
    nothing is claimed there at all.

    The other conditions of the coupling rules hold as always:
    both values are hlo:Actual, the same quantity kind, the same level.
    """
    suffix = f"_ExperimentSpecific_{nr}" if scope == "hlo:ExperimentSpecific" else "_SeriesSpecific"

    for port in datagraph.get("@graph", []):
        types = as_list(port.get("@type"))
        if scope not in types or not port.get("@id", "").endswith(suffix):
            continue
        if not any(t in ("cpo:DeviceInlet", "cpo:DeviceOutlet", "cpo:DeviceOpening") for t in types):
            continue

        ingoing = as_list(port.get("cpo:hasIngoingStream"))
        outgoing = as_list(port.get("cpo:hasOutgoingStream"))
        if len(ingoing) != 1 or len(outgoing) != 1:
            continue

        stream_in = find_entity(datagraph, ref_id(ingoing[0]))
        stream_out = find_entity(datagraph, ref_id(outgoing[0]))
        if stream_in is None or stream_out is None:
            continue

        _couple_flowrates_of_same_kind(stream_in, stream_out, namespace_collection, datagraph)


def _couple_flowrates_of_same_kind(owner_a: dict, owner_b: dict, namespace_collection: dict, datagraph: dict):
    """Couple the flow rates of two owners through hlo:isCoupledWith.

    The Actuals carry no quantity kind (cpo:hasFlowrate allows several, rule 4.4): what is
    coupled is the flow rate as such, the same property at both owners. Whether two VALUES can
    be compared is decided by their own kinds. Should an Actual carry a kind after all, only
    equal kinds are coupled.
    """
    for variable_a in (find_entity(datagraph, value_id) for value_id in ref_ids(owner_a.get("cpo:hasFlowrate"))):
        for variable_b in (find_entity(datagraph, value_id) for value_id in ref_ids(owner_b.get("cpo:hasFlowrate"))):
            if variable_a is None or variable_b is None or variable_a["@id"] == variable_b["@id"]:
                continue
            if ref_id(variable_a.get("qudt:hasQuantityKind")) != ref_id(variable_b.get("qudt:hasQuantityKind")):
                continue
            set_property(variable_a, "hlo:isCoupledWith", variable_b, namespace_collection, True)
            set_property(variable_b, "hlo:isCoupledWith", variable_a, namespace_collection, True)


def link_stream_end_couplings(transfers_by_stream_end: dict, namespace_collection: dict, datagraph: dict):
    """Connect the flowrates of the same species at the two ends of one stream through
    hlo:isCoupledWith.

    Only things of the same kind are coupled: the flow of water at one end with
    the flow of water at the other - the same property at two transfers of the same
    species. Never the flow of the whole stream with that of a species: that is a different
    quantity. In which quantity kind the values stand, the values say themselves (rule 4.4).

    What must hold:
      1. both values are hlo:Actual (domain/range of isCoupledWith),
      2. the same qudt:hasQuantityKind,
      3. the same level (both series or both the same experiment),
      4. the same species at the two ends of the SAME stream.

    transfers_by_stream_end is the {(port_id, stream_id, stream_phase_id): [transfer]} cache of
    create_port_crossing_transfers. A stream with only one end at a DevicePort
    (the other at a Source/Sink) has nothing to couple and is skipped. A stream with several
    crossing phases couples per phase - the two ends of the same phase.
    """
    by_stream = {}
    for (_, stream_id, phase_id), transfers in transfers_by_stream_end.items():
        by_stream.setdefault((stream_id, phase_id), []).append(transfers)

    for ends in by_stream.values():
        if len(ends) != 2:
            continue
        first, second = ends
        for transfer_a in first:
            species_a = ref_id(transfer_a.get("cpo:transfersChemicalEntity"))
            for transfer_b in second:
                if ref_id(transfer_b.get("cpo:transfersChemicalEntity")) != species_a:
                    continue
                _couple_flowrates_of_same_kind(transfer_a, transfer_b, namespace_collection, datagraph)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def complete_all_phases(namespace_collection: dict, datagraph: dict, chemical_entity_library: dict, todo_list: list, number_experiments: int) -> list:
    local_todo_list = []

    # All five caches live only for the duration of this one run: evidence_known_cache
    # remembers per (series entity, property) whether we have to ask for evidence/reference
    # on the experiment level at all; composition_kind_cache remembers per (series phase,
    # species) the QuantityKind chosen once for the composition;
    # series_phase_interfaces/series_pair_interfaces remember the interfaces created on
    # the series level, so that the experiment interfaces find them again and link them via
    # hlo:specializationOf/hlo:hasSpecialization; series_transfers likewise remembers the
    # transfers asked at a series PhasePairInterface, so that they can be taken over 1:1 on
    # the experiment level; series_cross_material_pairs remembers which pairs of phases were
    # chosen on the series level as additional interfaces between different materials, so
    # that this question is not asked again on the experiment level but taken over
    # automatically; series_occupation_states likewise remembers the OccupationStates asked
    # at a series PhaseInterface (or one of its PhasePairInterfaces); series_port_crossings
    # likewise remembers the PortCrossing transfers asked/resolved at a series DevicePort.
    evidence_known_cache = {}
    composition_kind_cache = {}
    series_phase_interfaces = {}
    series_pair_interfaces = {}
    series_transfers = {}
    series_cross_material_pairs = []
    series_occupation_states = {}
    series_port_crossings = {}
    # Per series phase the answer to "the same solvent in every experiment?" (add_phase_solvents).
    solvent_cache = {}

    print("\n--- Phases: Series level ---")
    series_phases = complete_phases_from_todo("hlo:SeriesSpecific", 1, namespace_collection, datagraph, chemical_entity_library, todo_list, local_todo_list, evidence_known_cache, composition_kind_cache)
    create_interfaces_for_phases(series_phases, "hlo:SeriesSpecific", 1, namespace_collection, datagraph, chemical_entity_library, todo_list, local_todo_list, evidence_known_cache, series_phase_interfaces, series_pair_interfaces, series_transfers, series_cross_material_pairs, series_occupation_states, series_port_crossings)
    # Substances that a transfer brought into a phase only after an interface or a port was
    # described are followed up there - until no more come (rule 3b.2).
    follow_up_transfers(series_pair_interfaces, series_transfers, series_port_crossings, namespace_collection, datagraph,
                        chemical_entity_library, todo_list, local_todo_list, evidence_known_cache)
    # First the interfaces, then this follow-up: a transfer with cpo:addsToPhase enters its
    # species into the destination phase, whose composition was asked above already
    # (see top_up_phase_concentrations). Does nothing if no species was added.
    top_up_phase_concentrations(series_phases, "hlo:SeriesSpecific", 1, namespace_collection, datagraph, chemical_entity_library, todo_list, local_todo_list, evidence_known_cache, composition_kind_cache, solvent_cache)

    for e in range(number_experiments):
        nr = e + 1
        with question_path("experiment", nr):
            print(f"\n--- Phases: Experiment {nr} ---")
            ask_absent_species(series_phases, nr, number_experiments, datagraph, chemical_entity_library)
            experiment_phases = complete_phases_from_todo("hlo:ExperimentSpecific", nr, namespace_collection, datagraph, chemical_entity_library, todo_list, local_todo_list, evidence_known_cache, composition_kind_cache)
            experiment_phases = drop_empty_experiment_phases(experiment_phases, nr, datagraph, todo_list, local_todo_list)
            create_interfaces_for_phases(experiment_phases, "hlo:ExperimentSpecific", nr, namespace_collection, datagraph, chemical_entity_library, todo_list, local_todo_list, evidence_known_cache, series_phase_interfaces, series_pair_interfaces, series_transfers, series_cross_material_pairs, series_occupation_states, series_port_crossings)
            # On the experiment level usually an idle run: the series phases already carry their
            # species brought by transfers at this point, so the experiment copy inherits them as
            # soon as it is created. It stands here all the same so that both levels are treated
            # alike, in case a species is added only here after all.
            top_up_phase_concentrations(experiment_phases, "hlo:ExperimentSpecific", nr, namespace_collection, datagraph, chemical_entity_library, todo_list, local_todo_list, evidence_known_cache, composition_kind_cache, solvent_cache)

    return local_todo_list
