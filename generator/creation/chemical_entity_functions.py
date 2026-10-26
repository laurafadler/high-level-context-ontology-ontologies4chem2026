"""
The one place to pick a chemical entity or describe a new one, so that phase composition,
transfers, occupation states and reaction participants all do it the same way.

The library entry of a chemical entity (name plus CAS/SMILES/InChI/molecular
formula/isRadioactive, as far as known) lives exclusively in the chemical_entity_library
(see CHEMICAL_ENTITY_LIBRARY_PATH in path_definitions.py; loaded in main.py and only read,
as reaction_library.jsonld) as an hlo:Fixed entity. These context-independent facts of
identity are never copied onto more specific instances.

For a chebi:Molecule there is, however, a series/experiment specialization, and one PER PHASE the molecule occurs in, not merely one per series or
experiment: concentration and partial molar volume depend on the phase and cannot be
attached unambiguously without an instance of their own per phase. See
get_or_create_phase_molecule further down, called from
creation/phase_functions.py::add_phase_composition, since that is where the
dcterms:hasPart link from a phase to its chemical species is made. Ions, radicals and other
chebi:ChemicalEntity that are not a chebi:Molecule are referenced unchanged by their
fixed ID (see is_molecule).

By default, modelling stops at the molecule level (name plus CAS/SMILES/InChI as far as
known). Breaking a molecule down into sub-molecules or atoms through dcterms:hasPart is
purely optional and only offered on request, not asked for by default: SMILES and InChI
already encode the full atomic structure compactly, and an atom-by-atom breakdown is only
worth it when there is a concrete modelling reason - referencing a particular bond in a
reaction mechanism, for example.

"""

from helpers.entities import add_entity, ask_entity_choice, find_entity, resolve, is_library_entity, ref_id, as_list
from helpers.properties import set_property, check_type
from helpers.identifiers import generate_id_from_name, get_display_label, short_local_name
from helpers.user_io import ask_user, question_path


CHEMICAL_ENTITY_SCOPE = "hlo:Fixed"
MOLECULE_TYPE = "chebi:Molecule"

# New entries in the chemical_entity_library are made only with the entry tool (type "substance",
# docs/how_to_library_entries.md; rule 2.16), never here: the crate run and fill_reaction_library.py
# only read the library (rule 2.2). If a chemical is missing, the question stops with a pointer to that.
STOP_OPTION = "Stop - it is not in the library yet"


class MissingLibraryEntryError(RuntimeError):
    """A chemical entity the crate needs is not in the chemical entity library."""


def _missing_entry(context_hint: str):
    raise MissingLibraryEntryError(
        f"The {context_hint} is not in the chemical entity library. Add it first with the entry tool "
        "(python generator/workflow/library_entries/create_library_entry.py substance, see "
        "docs/how_to_library_entries.md), commit the library, and run again.")


# Searchable identifier -> the property it is searched by in the library.
IDENTIFIER_FIELDS = {
    "Name": "schema:name",
    "CAS number": "cpo:hasCAS",
    "SMILES": "cpo:hasSMILES",
    "InChI": "cpo:hasInChI",
    "PubChem CID": "cpo:hasPubChemCID",
    # Appended at the end: the keys are the options of the search question as well.
    "InChIKey": "cpo:hasInChIKey",
}


def _all_chemical_entities(chemical_entity_library: dict, exclude_types: list = None) -> list:
    exclude_types = exclude_types or []
    return [
        e for e in chemical_entity_library.get("@graph", [])
        if "chebi:ChemicalEntity" in (e.get("@type") or [])
        and not any(t in (e.get("@type") or []) for t in exclude_types)
    ]


def _entity_label(entity: dict) -> str:
    label = get_display_label(entity)
    extras = []
    if entity.get("cpo:hasCAS"):
        extras.append(f"CAS {entity['cpo:hasCAS']}")
    if entity.get("cpo:hasMolecularFormula"):
        extras.append(entity["cpo:hasMolecularFormula"])
    if entity.get("cpo:hasSMILES"):
        extras.append(f"SMILES {entity['cpo:hasSMILES']}")
    if extras:
        label += " (" + ", ".join(extras) + ")"
    return label


def search_chemical_entities_by_name(chemical_entity_library: dict, name: str, exclude_types: list = None) -> list:
    """The entities a name finds - exact matches first, see _search_chemical_entities. Used
    where a name from a list stands for the entity (phase composition)."""
    return _search_chemical_entities(chemical_entity_library, IDENTIFIER_FIELDS["Name"], name, exclude_types)


def _search_chemical_entities(chemical_entity_library: dict, field: str, query: str, exclude_types: list = None) -> list:
    """Search the library for an identifier. EXACT matches take precedence: when the input
    matches a value exactly (one of the names, for multi-valued names), only those are
    returned; otherwise the search falls back to substring matching.

    Without that precedence, every new entry whose name contains an older one would make the
    search for the older one ambiguous: with two catalyst sites with "Platinum" in their name
    in the library, "Platinum" would return three hits instead of one. The substring search
    stays as the fallback, so that a fragment can still be entered when the full name is not
    known.
    """
    query = query.strip().lower()
    if not query:
        return []

    candidates = [e for e in _all_chemical_entities(chemical_entity_library, exclude_types) if e.get(field)]

    def values_of(entity):
        value = entity[field]
        values = value if isinstance(value, list) else [value]
        return [str(v).strip().lower() for v in values]

    exact = [e for e in candidates if query in values_of(e)]
    if exact:
        return exact

    return [e for e in candidates if query in str(e[field]).lower()]


def ask_chemical_entity(caller_scope: str, context_hint: str, namespace_collection: dict, chemical_entity_library: dict, extra_candidates: list = None, exclude_types: list = None, *, question_id: str) -> str:
    """Pick a chemical entity - either from extra_candidates (a context-dependent shortlist,
    such as species already present in a phase, or existing occupation states), or by
    searching the chemical_entity_library by name/CAS/SMILES/InChI depending on which
    identifier the person knows. An entity that is not in the library stops the question
    (MissingLibraryEntryError) - it is added with the entry tool first.

    context_hint is a short piece of text for the prompts ("participant of Hydrogenation",
    for instance).

    extra_candidates is a list of (id, label) tuples so that the caller supplies the display
    labels: candidates may come from the chemical_entity_library or, as occupation states
    do, from the datagraph - ask_chemical_entity itself only knows the
    chemical_entity_library.

    exclude_types excludes types from the search. That is needed for cpo:ActiveSite: by the ontology a catalyst site IS a chebi:ChemicalEntity
    - it could not be otherwise, since cpo:boundTo and cpo:occupiedBy have exactly that
    range - but it is not a species that occurs in a phase, gets transferred, or adsorbs
    anywhere. Callers asking for those therefore pass exclude_types=["cpo:ActiveSite"] and
    are not offered the sites.

    Where a site is precisely what is wanted - cpo:boundTo on an occupation state, or
    resolving a "cat site" placeholder - the parameter stays empty.

    question_id is MANDATORY (see helpers/user_io.py); every caller assigns its own, since
    this function is called from many different places.
    """
    if extra_candidates:
        candidate_labels = [label for _, label in extra_candidates]
        choice_label = ask_user(
            f"[{caller_scope}] Which entity is the {context_hint}?",
            candidate_labels + ["Something else (search the chemical entity library)"],
            question_id=f"{question_id}_quick_pick"
        )
        if choice_label != "Something else (search the chemical entity library)":
            return next(cid for cid, label in extra_candidates if label == choice_label)

    i = 0
    while True:
        i += 1
        with question_path(f"{question_id}_search", i):
            search_choice = ask_user(
                f"[{caller_scope}] Which identifier do you know for the {context_hint}?",
                list(IDENTIFIER_FIELDS.keys()),
                question_id="identifier_field"
            )
            field = IDENTIFIER_FIELDS[search_choice]
            query = ask_user(f"[{caller_scope}] {search_choice} of the {context_hint}?", question_id="identifier_value")
            matches = _search_chemical_entities(chemical_entity_library, field, query, exclude_types)

            if not matches:
                retry = ask_user(
                    f"[{caller_scope}] No entity found with {search_choice} matching '{query}'. "
                    f"Try a different identifier?",
                    ["Try a different identifier", STOP_OPTION],
                    question_id="not_found_retry_or_create"
                )
                if retry == STOP_OPTION:
                    _missing_entry(context_hint)
                continue

            if len(matches) == 1:
                return matches[0]["@id"]

            pick = ask_entity_choice(
                f"[{caller_scope}] Which one is the {context_hint}?",
                matches,
                extra_options=["None of these - try again"],
                label_fn=_entity_label,
                question_id="pick_match"
            )
            if pick != "None of these - try again":
                return pick


# ---------------------------------------------------------------------------
# Molecule instances per phase (hlo:SeriesSpecific / hlo:ExperimentSpecific)
# ---------------------------------------------------------------------------
#
# Unlike other chebi:ChemicalEntity (ions, radicals, ...), a chebi:Molecule needs an
# exemplar of its own per phase it occurs in, SeriesSpecific and (per experiment)
# ExperimentSpecific - linked via hlo:specializationOf to the exemplar above
# (SeriesSpecific -> Fixed, ExperimentSpecific -> SeriesSpecific), just as for devices
# (see creation/device_functions.py). The facts of identity that do not depend on the
# context (cpo:hasInChI, cpo:hasCAS, cpo:hasSMILES, cpo:hasMolecularFormula,
# cpo:isRadioactive) stay exclusively at the Fixed entry - whoever needs them for a
# specific exemplar has to follow the hlo:specializationOf chain zero or more times
# (sh:zeroOrMorePath), just as for the device shapes Device_Structure_R1/
# Device_Substance_R1 (the flag cpo:isCompositeDevice).
#
# get_or_create_phase_molecule is called exclusively from
# creation/phase_functions.py::add_phase_composition, since it is decided there for every
# phase which chemical species it contains.


def is_molecule(entity: dict) -> bool:
    """Check whether a chemical entity (from the chemical_entity_library) is a chebi:Molecule."""
    type_list = as_list(entity.get("@type"))
    return MOLECULE_TYPE in type_list


def fixed_chemical_entity_id(species_ref, datagraph: dict) -> str:
    """Return the fixed ID of the chemical entity behind species_ref.

    Either directly, when species_ref already points at the fixed library entry, or - when
    it points at a series- or experiment-specific molecule instance instead (see
    get_or_create_phase_molecule) - through that instance's hlo:specializationOf chain,
    walking up until an ID is found that is no longer an instance in the datagraph. The
    fixed library entry lives only in the chemical_entity_library, never in the datagraph.

    Needed both for series -> experiment inheritance (add_phase_composition) and when a
    transfer has to resolve an already phase-specific molecule instance afresh for ANOTHER
    (destination) phase (see
    helpers/transfer_functions.py::_ensure_species_in_destination_phase) - a single
    hlo:specializationOf step is not enough for that.

    Deliberately placed here rather than in creation/phase_functions.py, so that
    helpers/transfer_functions.py can import it without creating a circular import with
    creation/phase_functions.py, which in turn imports helpers/transfer_functions.py.
    """
    species_id = species_ref.get("@id") if isinstance(species_ref, dict) else species_ref
    visited = set()
    while species_id not in visited:
        visited.add(species_id)
        instance = resolve(datagraph, species_id)
        if instance is None:
            return species_id
        specialization_ref = instance.get("hlo:specializationOf")
        if specialization_ref is None:
            return species_id
        species_id = specialization_ref.get("@id") if isinstance(specialization_ref, dict) else specialization_ref
    return species_id


def _molecule_instance_id(fixed_entity_id: str, phase: dict, scope: str, experiment_number: int = None) -> str:
    """The ID of a phase-specific molecule instance, built from the local name of the fixed
    entry and the local name of the phase (mirroring the composition ID in
    phase_functions.py::add_phase_composition).

    That way the same molecule in two different phases automatically gets two different
    instances, without anyone having to keep a count.
    """
    molecule_local_name = fixed_entity_id.split(":", 1)[-1]
    phase_local_name = short_local_name(phase["@id"])
    return generate_id_from_name(f"{molecule_local_name}_{phase_local_name}", scope, experiment_number)


def _add_partial_molar_volume(molecule_instance: dict, scope: str, nr: int, namespace_collection: dict, datagraph: dict):
    """Create an empty Actual process variable for cpo:hasPartialMolarVolume on a
    (non-fixed) molecule instance (see Molecule_Space_R5).

    Only the existence of the entity is ensured; no value and no quantity kind are asked for
    (QUDT has no PartialMolarVolume, and the property itself is already unambiguous).
    Evidence and references can be added later, exactly as for the other process variables.
    """
    experiment_number = nr if scope == "hlo:ExperimentSpecific" else None
    volume_id = generate_id_from_name(f"PartialMolarVolume_{short_local_name(molecule_instance['@id'])}", scope, experiment_number)

    volume_type = check_type("cpo:ProcessVariable", namespace_collection)
    volume = {"@id": volume_id, "@type": [volume_type, scope, "hlo:Actual"]}
    set_property(volume, "cpo:isProcessVariableOf", molecule_instance, namespace_collection)
    set_property(molecule_instance, "cpo:hasPartialMolarVolume", volume, namespace_collection)
    # Chained across the levels like every other actual (rule 3.3): the experiment actual
    # specializes that of its series molecule, so that the collecting path of Molecule_Space_R5
    # finds both. The series actual specializes nothing - the library knows no partial molar volume, it depends on
    # the phase.
    if scope == "hlo:ExperimentSpecific":
        series_molecule = find_entity(datagraph, ref_id(molecule_instance.get("hlo:specializationOf")))
        series_volume = find_entity(datagraph, ref_id(series_molecule.get("cpo:hasPartialMolarVolume"))) if series_molecule else None
        if series_volume is not None:
            set_property(volume, "hlo:specializationOf", series_volume, namespace_collection)
            set_property(series_volume, "hlo:hasSpecialization", volume, namespace_collection, True)
    add_entity(datagraph, volume)


def get_or_create_phase_molecule(fixed_entity_id: str, phase: dict, scope: str, nr: int, namespace_collection: dict, datagraph: dict, chemical_entity_library: dict, series_phase: dict = None, fixed_instance_id: str = None) -> str:
    """Make sure the molecule instance belonging to this phase exists for the fixed
    molecule fixed_entity_id, and return its @id.

    At scope hlo:SeriesSpecific only the series instance is ensured, specializing the fixed
    entry. At scope hlo:ExperimentSpecific the series instance of the corresponding series
    phase (series_phase) is ensured first, and then the experiment instance that specializes
    it is created.

    series_phase is only needed at scope hlo:ExperimentSpecific: it is the series phase
    whose dcterms:hasPart entry the experiment phase is taking over (see get_series_entity
    in helpers/process_variables.py). Should it be missing - because the phase has no series
    counterpart, say - the experiment phase itself is used to build the ID of the series
    instance, so that a complete specializationOf chain still comes about.

    Every newly created molecule instance also gets the reverse direction
    dcterms:isPartOf to exactly the phase it stands for; the forward direction
    dcterms:hasPart from the phase to the molecule instance is set by _attach_species
    in phase_functions.py. As everywhere else in the project, hasPart/isPartOf is
    materialised in both directions (see create_phase_placeholder in
    material_functions.py, for example).
    """
    series_reference_phase = phase if scope == "hlo:SeriesSpecific" else (series_phase or phase)
    series_entity_id = _molecule_instance_id(fixed_entity_id, series_reference_phase, "hlo:SeriesSpecific")
    series_entity = find_entity(datagraph, series_entity_id)

    if series_entity is None:
        fixed_entity = find_entity(chemical_entity_library, fixed_entity_id)
        series_entity = {
            "@id": series_entity_id,
            "@type": [MOLECULE_TYPE, "chebi:ChemicalEntity", "hlo:SeriesSpecific"]
        }
        set_property(series_entity, "schema:name", get_display_label(fixed_entity), namespace_collection)
        # Normally the series exemplar specializes the bare library entry (chem:Molecule_0005).
        # If the Fixed phase brings an exemplar OF ITS OWN, however - like the room air in
        # organization_library.jsonld, where the mass fraction of oxygen is a fixed value -, it
        # specializes that one; only so does add_phase_composition find the fixed value via
        # hlo:specializationOf and take it over, instead of asking it anew per series.
        specialization_target = fixed_instance_id or fixed_entity_id
        set_property(series_entity, "hlo:specializationOf", {"@id": specialization_target}, namespace_collection)
        fixed_instance = resolve(datagraph, specialization_target)
        if fixed_instance is not None and not is_library_entity(fixed_instance):
            # The inverse direction only if the target stands in the crate - a library entry never
            # does (molecules are referenced, not copied; rule 2.2).
            set_property(fixed_instance, "hlo:hasSpecialization", series_entity, namespace_collection, True)
        set_property(series_entity, "dcterms:isPartOf", series_reference_phase, namespace_collection)
        add_entity(datagraph, series_entity)
        _add_partial_molar_volume(series_entity, "hlo:SeriesSpecific", nr, namespace_collection, datagraph)

    if scope == "hlo:SeriesSpecific":
        return series_entity_id

    experiment_entity_id = _molecule_instance_id(fixed_entity_id, phase, "hlo:ExperimentSpecific", nr)
    experiment_entity = find_entity(datagraph, experiment_entity_id)

    if experiment_entity is None:
        experiment_entity = {
            "@id": experiment_entity_id,
            "@type": [MOLECULE_TYPE, "chebi:ChemicalEntity", "hlo:ExperimentSpecific"]
        }
        set_property(experiment_entity, "schema:name", get_display_label(series_entity), namespace_collection)
        set_property(experiment_entity, "hlo:specializationOf", series_entity, namespace_collection)
        set_property(series_entity, "hlo:hasSpecialization", experiment_entity, namespace_collection, True)
        set_property(experiment_entity, "dcterms:isPartOf", phase, namespace_collection)
        add_entity(datagraph, experiment_entity)
        _add_partial_molar_volume(experiment_entity, "hlo:ExperimentSpecific", nr, namespace_collection, datagraph)

    return experiment_entity_id
