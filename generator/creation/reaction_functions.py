"""
Everything needed to create reactions (StoichiometricReaction, LumpedReaction,
ElementaryReaction), reaction participants and reaction mechanisms.

A LumpedReaction (rule 2.11) is an overall reaction between materials that are not
single species (wood, lignin oil, pulp): it goes through the same three levels as a
stoichiometric one, but its participants have no stoichiometric coefficient (none is asked -
there is none, which is not the same as unknown) and it has no mechanism. At an interface the
direction of a participant follows from its role instead of the sign of the coefficient
(LUMPED_CONSUMED_ROLES, LUMPED_FORMED_ROLES).

The three-level Fixed/SeriesSpecific/ExperimentSpecific pattern as for devices and
environments - with the difference that the fixed level does NOT end up in the generated
crate here, but in a libraries/reaction_library.jsonld of its own that is reusable across
several crate runs (see REACTION_LIBRARY_PATH in path_definitions.py), along the lines of
device_library.jsonld. And exactly as there, creating a crate does NOT change the library:
complete_all_reactions only reads reaction_library, and main.py does not save it back.
New fixed reactions are created exclusively through a separate library tool that reuses
create_fixed_reaction/ask_reaction_participants (see their docstrings) - those functions
stay in this module although complete_all_reactions does not call them.
- hlo:Fixed (lives ONLY in the reaction library, NEVER in the datagraph): the reaction as a
  reusable "recipe" - name, description (the reaction equation), participants. A participant
  can be in one of three states (see create_reaction_participant): a fixed species
  (dcterms:hasPart points at an entry of the chemical_entity_library), a PLACEHOLDER
  (dcterms:hasPart points at an cpo:Placeholder node in the library itself), or completely
  open (dcterms:hasPart is missing and is settled only at series level). Optionally several
  candidate reaction mechanisms. No phase, no interface, no rate - none of that exists at
  this level yet.
- hlo:SeriesSpecific: specializes a fixed reaction (see
  specialize_reaction_participant_for_series). Depending on the fixed state, the concrete
  species per participant is carried over directly, resolved through resolve_placeholder, or
  searched for and created freely. The role is inherited one to one; coefficient and partial
  order are carried over where they are set on the fixed participant and asked for afresh
  otherwise. Added afresh here: occursInPhase/occursAtInterface (pointing at series phases,
  which only exist from here on) and hasReactionRate (an Actual process variable, as
  everywhere else in the project).

PLACEHOLDERS (cpo:Placeholder, see resolve_placeholder/new_resolution_cache):
A fixed reaction is a generic template - "RDY + 4 H2 -> RDEt" holds for a whole class of
molecules. Where the concrete species is only settled per series, the participant points at a
placeholder node of its own rather than at a molecule. What matters is the identity of that
node: RDY occurs in the overall reaction and in several elementary reactions of its
mechanism, and all of those participants have to become the same species. Every placeholder
is therefore asked about exactly ONCE per crate run (resolution_cache, created in
complete_all_reactions and passed through the whole specialization) - and across reactions,
because the RDEt the hydrogenation produces is the same RDEt the dimerisations consume.
Candidates for a placeholder hang off the placeholder node (cpo:hasPotentialCandidate), not
off the individual participant; otherwise they would have to be repeated at every occurrence
and kept in step.

A placeholder can also stand for a cpo:OccupationState - an adsorbed species, or a free site
on a catalyst surface. That is a different case from a species placeholder: WHAT is adsorbed
is already settled in the template (occupiedBy/boundTo/hasSorptionType), and what is open is
only the context, i.e. cpo:belongsToInterface, since phases and interfaces only exist from
series level on. A FREE site is an occupation state without cpo:occupiedBy, and hence without
a sorption type - nothing is adsorbed.

An elementary reaction can belong to SEVERAL mechanisms (the RDEt adsorption belongs to both
dimerisation mechanisms). It is then specialized or copied only once and the second mechanism
links the same entity - it is the same reaction, and it does not know what happens before or
after it (see specialize_elementary_reactions_for_series).
- hlo:ExperimentSpecific: the participants of a stoichiometric reaction get an experiment
  counterpart (copy_reaction_participants, rule 3.9), as holders of what differs
  from run to run - yield, conversion, selectivity (add_reaction_outcomes) and a partial order
  known for one experiment; species and roles are not asked again. Participants of elementary
  reactions stay at series level. Further occursInPhase/occursAtInterface (mapped onto the matching
  experiment phase or interface), hasReactionRate (fresh per experiment, including the
  evidence/reference shortcut) and the involvesTransfer links (mapped onto the experiment
  transfers that already exist, see copy_reaction_transfers) are set. Whether a
  stoichiometric reaction actually takes place in an experiment is recorded through
  cpo:hasOccurrence (add_occurrence, see helpers/time_occurrence.py); elementary reactions do
  not get that, since they are hypotheses within reference mechanisms rather than events in
  their own right.

Interface reactions (with occursAtInterface set) are additionally linked to transfers
(cpo:involvesTransfer/cpo:isInvolvedIn, see link_reaction_transfers): every participant that
is not an occupation state gets a transfer at the same interface, reused where possible (see
get_or_create_transfer). Bulk reactions (occursInPhase) need no transfers - nothing changes
place there.

ReactionParticipant -> ChemicalEntity/OccupationState runs through dcterms:hasPart, the same
property with which phases express their composition (see add_phase_composition in
phase_functions.py); no property of its own is needed.

ReactionMechanism: the mechanism that actually runs is usually not known for certain, so
every reaction gets - where wanted - an hlo:Actual anchor WITHOUT content
(create_actual_reaction_mechanism_placeholder), onto which any number of mechanisms that can
actually be described (one's own hypothesis or one from the literature, each with its
elementary reactions) are hung as an hlo:Reference (hlo:hasReference/hlo:isReferenceOf) - see
ask_reaction_mechanism. That holds for the FIRST mechanism too, not only for "alternative"
ones.
"""

from helpers.entities import add_entity, find_entity, ask_entity_choice, ask_entity_list, resolve_inherited, inherited_value, ref_id, ref_ids, is_library_entity, as_list
from helpers.properties import set_property, set_literal_property, check_type
from helpers.ontology_functions import find_individuals_of_class, quantity_kind_of_property
from helpers.identifiers import (generate_id, generate_library_id, generate_name, get_display_label, short_local_name,
                                 claim_id, make_library_based_id, make_specialization_id, make_member_id, make_owned_id, key_name,
                                 name_list, slugify)
from helpers.transfer_functions import transfer_types, get_or_create_transfer, reverse_transfer_type
from helpers.time_occurrence import add_occurrence
from creation.material_functions import ask_optional_name, PHASE_STATE_CLASSES
from helpers.evidence_reference import reference_types
from creation.phase_functions import absent_species, species_label, get_series_entity, phase_matches_experiment, add_phase_process_variable, phase_label, interface_label, get_interface_phases, create_occupation_state_entity, sorption_types
from creation.chemical_entity_functions import ask_chemical_entity
from helpers.user_io import ask_user, ask_user_list, question_path


def chemical_roles(namespace_collection):
    """The cpo:ChemicalRole individuals from the ontology, not a list in the code. cpo:Solvent is
    deprecated and not offered: the solvent is stated at the phase (cpo:hasSolvent,
    creation/phase_functions.py: add_phase_solvents; rule 3.12)."""
    return find_individuals_of_class("cpo:ChemicalRole", namespace_collection)


def reversibility_values(namespace_collection):
    """The cpo:Reversibility individuals from the ontology (reversible/irreversible)."""
    return find_individuals_of_class("cpo:Reversibility", namespace_collection)

NEW_PLACEHOLDER_OPTION = "It's new / not in the library yet"
NEW_OCCUPATION_STATE_OPTION = "None of these - describe a new one"


def _new_entity_id(base_name, scope: str, container: dict, todo_list: list, experiment_number: int = None) -> str:
    """hlo:Fixed entities live permanently in the reaction library and therefore get a
    CURIE ("reaction:ElementaryReaction_0001", see generate_library_id); everything else
    comes into being during a crate run and keeps the bare "#fragment".

    An ID thus shows whether it is a stable library entry or something produced by this
    particular run.
    """
    if scope == "hlo:Fixed":
        return generate_library_id("reaction", base_name, container)
    return generate_id(base_name, container, todo_list, scope, experiment_number)


# ---------------------------------------------------------------------------
# Helpers: find candidates for species/phases/interfaces of a scope
# ---------------------------------------------------------------------------

def _is_placeholder(entity) -> bool:
    """A placeholder stands for an entity deliberately left open at hlo:Fixed level and
    settled only at hlo:SeriesSpecific level - see the module docstring and cpo:Placeholder
    in HigherLevelOntology.rdf."""
    return bool(entity) and "cpo:Placeholder" in (entity.get("@type") or [])


def _is_open_occupation_state(entity) -> bool:
    """A fixed occupation state of a fixed reaction (rule 2.11): what is adsorbed
    where is settled (cpo:occupiedBy, cpo:boundTo), only the interface is open - it is the series'
    context, not chemistry. Handled exactly like an occupation state placeholder."""
    types = (entity or {}).get("@type") or []
    return "cpo:OccupationState" in types and not _is_placeholder(entity) and not entity.get("cpo:belongsToInterface")


def _all_occupation_states(datagraph: dict, scope: str) -> list:
    """Placeholders are filtered out: in a crate's datagraph they never occur anyway, but at
    hlo:Fixed level the "datagraph" is the reaction library, and there the placeholder
    occupation states should not be offered as finished species - that is what the separate
    "Placeholder" branch in create_reaction_participant is for.
    """
    return [
        e for e in datagraph.get("@graph", [])
        if "cpo:OccupationState" in (e.get("@type") or []) and scope in (e.get("@type") or [])
        and not _is_placeholder(e)
    ]


def _ask_species_or_occupation_state(scope: str, context_hint: str, namespace_collection: dict, chemical_entity_library: dict, datagraph: dict, *, question_id: str) -> str:
    """Candidates: the occupation states of this scope (for adsorptions) as a shortlist,
    otherwise search or creation in the chemical_entity_library (see
    chemical_entity_functions.py).

    A generic placeholder molecule at hlo:Fixed level ("RDY", say) is simply a chemical
    entity without CAS/SMILES/InChI - no special case needed.
    """
    occupation_states = [(e["@id"], get_display_label(e)) for e in _all_occupation_states(datagraph, scope)]
    return ask_chemical_entity(scope, context_hint, namespace_collection, chemical_entity_library, extra_candidates=occupation_states, question_id=question_id)


def _all_phases_for_scope(datagraph: dict, scope: str, nr: int) -> list:
    result = []
    for entity in datagraph.get("@graph", []):
        types = as_list(entity.get("@type"))
        if scope not in types or not any(t in PHASE_STATE_CLASSES for t in types):
            continue
        if phase_matches_experiment(entity, scope, nr, datagraph):
            result.append(entity)
    return result


def _all_interfaces_for_scope(datagraph: dict, scope: str, nr: int) -> list:
    result = []
    for entity in datagraph.get("@graph", []):
        types = as_list(entity.get("@type"))
        if scope not in types or not any(t in ("cpo:PhaseInterface", "cpo:PhasePairInterface") for t in types):
            continue
        if scope != "hlo:ExperimentSpecific":
            result.append(entity)
            continue
        phases = get_interface_phases(entity, datagraph)
        if any(phase_matches_experiment(p, scope, nr, datagraph) for p in phases):
            result.append(entity)
    return result


# The overall reactions a crate can choose from the library - elementary reactions belong to a mechanism.
OVERALL_REACTION_CLASSES = ("cpo:StoichiometricReaction", "cpo:LumpedReaction")
# Direction of a participant of a LumpedReaction at an interface: from its role, since there is no coefficient.
LUMPED_CONSUMED_ROLES = {"cpo:Reactant", "cpo:Substrate", "cpo:Reagent"}
LUMPED_FORMED_ROLES = {"cpo:Product", "cpo:Byproduct"}


def overall_reaction_class(entity: dict):
    """cpo:StoichiometricReaction or cpo:LumpedReaction - the class of an overall reaction, None otherwise."""
    types = as_list(entity.get("@type"))
    return next((c for c in OVERALL_REACTION_CLASSES if c in types), None)


def is_lumped(reaction: dict) -> bool:
    return overall_reaction_class(reaction) == "cpo:LumpedReaction"


def _all_fixed_reactions(reaction_library: dict) -> list:
    return [
        e for e in reaction_library.get("@graph", [])
        if overall_reaction_class(e) and "hlo:Fixed" in (e.get("@type") or [])
    ]


def _find_experiment_counterpart(series_id: str, scope: str, nr: int, datagraph: dict):
    """Among the phases and interfaces of THIS experiment (not just any), find the one
    whose hlo:specializationOf points at series_id.

    Uses the same nr-filtered candidate lists as ask_reaction_location; otherwise - since
    hlo:ExperimentSpecific is the same scope string for every experiment - the phase or
    interface of ANOTHER experiment would be found by mistake.
    """
    candidates = _all_phases_for_scope(datagraph, scope, nr) + _all_interfaces_for_scope(datagraph, scope, nr)
    for entity in candidates:
        series_entity = get_series_entity(entity, datagraph)
        if series_entity and series_entity["@id"] == series_id:
            return entity["@id"]
    return None


# ---------------------------------------------------------------------------
# Resolving placeholders (cpo:Placeholder) of the Reaction Library
# ---------------------------------------------------------------------------

def new_resolution_cache() -> dict:
    """The cache that holds a whole crate run together - created in complete_all_reactions
    and passed from there through the entire series specialization:

    - "placeholders": fixed placeholder @id -> resolved @id. Every placeholder is thereby
      asked about EXACTLY ONCE per crate and inserted identically everywhere - across the
      overall reaction, the elementary reactions, and even across several reactions. That is
      precisely the point of placeholders: the RDEt the hydrogenation produces is the same
      RDEt the dimerisations consume.
    - "elementary"/"elementary_experiment": the fixed or series @id of an elementary
      reaction -> the entity already created. An elementary reaction can belong to SEVERAL
      mechanisms (the RDEt adsorption belongs to both dimerisation mechanisms); it is then
      created only once and the second mechanism links the same entity rather than producing
      a copy - it is the same reaction after all, and it does not know what happens before or
      after it.
    """
    return {"placeholders": {}, "elementary": {}, "elementary_experiment": {}}


def _all_placeholders(reaction_library: dict) -> list:
    return [e for e in reaction_library.get("@graph", []) if _is_placeholder(e)]


def _resolve_species_reference(species_id, scope: str, nr: int, namespace_collection: dict, datagraph: dict, reaction_library: dict, chemical_entity_library: dict, todo_list: list, local_todo_list: list, resolution_cache: dict, evidence_known_cache: dict = None):
    """A reference that is either already a concrete entity - returned unchanged - or a
    placeholder, in which case it is resolved through resolve_placeholder."""
    if species_id is None:
        return None
    candidate = find_entity(reaction_library, species_id)
    if _is_placeholder(candidate):
        return resolve_placeholder(candidate, scope, nr, namespace_collection, datagraph, reaction_library, chemical_entity_library, todo_list, local_todo_list, resolution_cache, evidence_known_cache)
    return species_id


def _resolve_occupation_state_placeholder(fixed_placeholder: dict, label: str, scope: str, nr: int, namespace_collection: dict, datagraph: dict, reaction_library: dict, chemical_entity_library: dict, todo_list: list, local_todo_list: list, resolution_cache: dict, evidence_known_cache: dict = None):
    """An occupation state placeholder is a different case from a species placeholder: WHAT
    is adsorbed is already settled in the template (cpo:occupiedBy, cpo:boundTo,
    cpo:hasSorptionType) - what is open is only the context, i.e. at which interface this
    happens. cpo:belongsToInterface is therefore missing at fixed level and is set exactly
    here.

    An occupation state already described in the crate is reused rather than written into the
    graph a second time (complete_all_phases runs before the reactions, see main.py). Only
    those whose occupiedBy and boundTo match what the template describes here are offered -
    otherwise "H on the catalyst" could be equated with "RDEt on the catalyst" by accident,
    merely because both appear in the same list.
    """
    # A free site has no cpo:occupiedBy - and consequently no SorptionType either,
    # because nothing is adsorbed (see create_occupation_state_entity).
    occupied_by_id = _resolve_species_reference(ref_id(fixed_placeholder.get("cpo:occupiedBy")), scope, nr, namespace_collection, datagraph, reaction_library, chemical_entity_library, todo_list, local_todo_list, resolution_cache, evidence_known_cache)
    bound_to_id = _resolve_species_reference(ref_id(fixed_placeholder.get("cpo:boundTo")), scope, nr, namespace_collection, datagraph, reaction_library, chemical_entity_library, todo_list, local_todo_list, resolution_cache, evidence_known_cache)
    sorption_type = ref_id(fixed_placeholder.get("cpo:hasSorptionType")) if occupied_by_id else None

    matching = [
        e for e in _all_occupation_states(datagraph, scope)
        if ref_id(e.get("cpo:occupiedBy")) == occupied_by_id and ref_id(e.get("cpo:boundTo")) == bound_to_id
    ]
    if matching:
        chosen_id = ask_entity_choice(
            f"[{scope}] Which occupation state already in this series is \"{label}\"?",
            matching, extra_options=[NEW_OCCUPATION_STATE_OPTION], question_id="occupation_state"
        )
        if chosen_id != NEW_OCCUPATION_STATE_OPTION:
            return chosen_id

    interface_id = ask_entity_choice(
        f"[{scope}] At which interface does \"{label}\" sit?",
        _all_interfaces_for_scope(datagraph, scope, nr), label_fn=interface_label, question_id="interface"
    )
    interface = find_entity(datagraph, interface_id)

    # The name from the template ("cat-H", "cat(X)") makes the graph and above all the
    # choice list above readable - and it is the ID of the occupation.
    occupation_state = create_occupation_state_entity(
        interface, label, occupied_by_id, bound_to_id, sorption_type,
        scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache
    )
    return occupation_state["@id"]


def resolve_placeholder(fixed_placeholder: dict, scope: str, nr: int, namespace_collection: dict, datagraph: dict, reaction_library: dict, chemical_entity_library: dict, todo_list: list, local_todo_list: list, resolution_cache: dict, evidence_known_cache: dict = None) -> str:
    """Resolve a placeholder from the reaction library, which is only read, to a concrete
    entity in the datagraph - once per crate run, after that from resolution_cache (see
    new_resolution_cache).

    The question path is deliberately RESET to "series:1/placeholder:N" rather than hanging
    under the participant currently being processed: which participant triggers a placeholder
    first depends on the order in the library and would shift with every change there. This
    way "RDY" gets its key once and keeps it (see helpers/user_io.py).
    """
    placeholder_id = fixed_placeholder["@id"]
    if placeholder_id in resolution_cache["placeholders"]:
        return resolution_cache["placeholders"][placeholder_id]

    label = get_display_label(fixed_placeholder)

    # A fixed occupation state (no placeholder) has a segment of its own in the key.
    segment = "placeholder" if _is_placeholder(fixed_placeholder) else "occupation_state"
    with question_path("series", 1, reset=True), question_path(segment, key_name(placeholder_id)):
        print(f"\n=== Resolving {segment.replace('_', ' ')} \"{label}\" for this series ===")
        description = fixed_placeholder.get("schema:description")
        if description:
            print(f"    {description}")

        if "cpo:OccupationState" in (fixed_placeholder.get("@type") or []):
            resolved = _resolve_occupation_state_placeholder(fixed_placeholder, label, scope, nr, namespace_collection, datagraph, reaction_library, chemical_entity_library, todo_list, local_todo_list, resolution_cache, evidence_known_cache)
        else:
            candidates = [(cid, species_label(cid, chemical_entity_library)) for cid in ref_ids(fixed_placeholder.get("cpo:hasPotentialCandidate"))]
            resolved = ask_chemical_entity(
                scope, f"concrete species behind the placeholder \"{label}\"",
                namespace_collection, chemical_entity_library, extra_candidates=candidates, question_id="species"
            )

    resolution_cache["placeholders"][placeholder_id] = resolved
    return resolved


# ---------------------------------------------------------------------------
# Creating placeholders on the hlo:Fixed level (Reaction Library script)
# ---------------------------------------------------------------------------

def _ask_species_or_placeholder(scope: str, context_hint: str, namespace_collection: dict, reaction_library: dict, chemical_entity_library: dict, *, question_id: str) -> str:
    """For the innards of an occupation state placeholder (occupiedBy/boundTo): offers the
    placeholders already in the library as a shortlist, otherwise the ordinary search in the
    chemical_entity_library.

    A NEW placeholder is not created here - for that, create the inner placeholder ("cat site
    (H)") first and the outer one ("cat-H") afterwards.
    """
    candidates = [(e["@id"], get_display_label(e)) for e in _all_placeholders(reaction_library)]
    return ask_chemical_entity(scope, context_hint, namespace_collection, chemical_entity_library, extra_candidates=candidates, question_id=question_id)


def create_placeholder(scope: str, namespace_collection: dict, reaction_library: dict, chemical_entity_library: dict, todo_list: list) -> str:
    """Create a new placeholder in the reaction library (see resolve_placeholder for the
    other side)."""
    kind = ask_user(
        f"[{scope}] Does this placeholder stand for a chemical species, or for an occupation state "
        f"(something adsorbed on or bound to a surface - a free site counts too)?",
        ["Chemical species", "Occupation state"], question_id="placeholder_kind"
    )
    name = ask_user(f"[{scope}] Short name for this placeholder (e.g. 'RDY', 'cat-H')?", question_id="placeholder_name")
    description = ask_user(f"[{scope}] What does {name} stand for (e.g. which kind of molecule it can become)?", question_id="placeholder_description")

    base_type = "chebi:ChemicalEntity" if kind == "Chemical species" else "cpo:OccupationState"
    id_token = "".join(c for c in name if c.isalnum() or c == "_") or "Placeholder"
    placeholder_id = generate_library_id("placeholder", id_token, reaction_library)
    placeholder = {"@id": placeholder_id, "@type": [check_type(base_type, namespace_collection), "cpo:Placeholder", scope], "schema:name": name}
    if description.strip():
        set_property(placeholder, "schema:description", description.strip(), namespace_collection)

    if kind == "Chemical species":
        # A list instead of "another one?" with a counter (rule 1.4): the name is the key of the
        # candidate, a further candidate shifts no stored answer.
        candidate_names = ask_user(
            f"[{scope}] Which candidate species could {name} turn out to be? Name them, separated by ';' (leave empty for none)",
            answer_type=name_list, question_id="candidate_names")
        for candidate_name in candidate_names:
            with question_path("candidate", slugify(candidate_name)):
                candidate_id = ask_chemical_entity(scope, f"candidate \"{candidate_name}\" for the placeholder \"{name}\"", namespace_collection, chemical_entity_library, question_id="select")
                set_property(placeholder, "cpo:hasPotentialCandidate", {"@id": candidate_id}, namespace_collection, True)
    else:
        # A free site is an OccupationState without cpo:occupiedBy - and then needs no
        # SorptionType either. cpo:belongsToInterface stays open in any case, that is the
        # actual placeholder part (see resolve_placeholder).
        free_site = ask_user(f"[{scope}] Is {name} a free (unoccupied) site?", ["Yes", "No"], question_id="is_free_site")
        if free_site == "No":
            with question_path("occupied_by"):
                occupied_by_id = _ask_species_or_placeholder(scope, f"entity occupying {name}", namespace_collection, reaction_library, chemical_entity_library, question_id="entity")
            set_property(placeholder, "cpo:occupiedBy", {"@id": occupied_by_id}, namespace_collection)
            sorption_type = ask_user(f"[{scope}] Which type of sorption holds {name} in place?", sorption_types(namespace_collection), question_id="sorption_type")
            set_property(placeholder, "cpo:hasSorptionType", {"@id": sorption_type}, namespace_collection)

        bound = ask_user(f"[{scope}] Does {name} sit on a specific site, group or material?", ["Yes", "No"], question_id="has_bound_to")
        if bound == "Yes":
            with question_path("bound_to"):
                bound_to_id = _ask_species_or_placeholder(scope, f"site/group that {name} sits on", namespace_collection, reaction_library, chemical_entity_library, question_id="entity")
            set_property(placeholder, "cpo:boundTo", {"@id": bound_to_id}, namespace_collection)

    add_entity(reaction_library, placeholder)
    return placeholder_id


def ask_placeholder(scope: str, namespace_collection: dict, reaction_library: dict, chemical_entity_library: dict, todo_list: list, *, question_id: str) -> str:
    """Pick an existing placeholder from the library, or create a new one."""
    existing = _all_placeholders(reaction_library)
    if existing:
        chosen_id = ask_entity_choice(
            f"[{scope}] Which placeholder stands in for this participant?",
            existing, extra_options=[NEW_PLACEHOLDER_OPTION], question_id=question_id
        )
        if chosen_id != NEW_PLACEHOLDER_OPTION:
            return chosen_id
    return create_placeholder(scope, namespace_collection, reaction_library, chemical_entity_library, todo_list)


# ---------------------------------------------------------------------------
# ReactionParticipant - hlo:Fixed (generic) and hlo:SeriesSpecific (free,
# not derived from a Fixed reaction - e.g. in case somebody wants to start
# directly on the series level after all)
# ---------------------------------------------------------------------------

def _ask_fixed_partial_order(participant: dict, target_graph: dict, namespace_collection: dict):
    """The partial order of a fixed participant (reaction library script) - as a process
    variable with a reference, not as a bare number.

    Why this needs its own approach instead of add_phase_process_variable: that function builds
    the series and experiment Actuals of a crate and offers them in the value lists; at fixed
    level the value and its reference are asked right here. The value gets no context - a
    library entity never carries one (rule 6.6).

    Empty input means unknown: nothing is created here then, and the value is added later at
    series level as an empty Actual process variable (see
    specialize_reaction_participants_for_series).
    """
    value = ask_user(
        "[hlo:Fixed] Partial reaction order of this participant in the rate law (leave empty if unknown)?",
        question_id="partial_order"
    )
    if not value.strip():
        return

    reference_type = ask_user("[hlo:Fixed] Where does that partial order come from?", reference_types(namespace_collection), question_id="partial_order_reference_type")
    source = ask_user("[hlo:Fixed] Source for that partial order (DOI, URL, ... - leave empty if none)?", question_id="partial_order_source")

    base = short_local_name(participant["@id"]).replace("ReactionParticipant_", "", 1)
    pv_id = f"reaction:PartialOrder_{base}"
    # Value IDs: <variable>_<role>_<n> as make_member_id in the crate (rule 1.6) - the type
    # stands in hlo:hasReferenceType.
    reference_id = f"{pv_id}_Reference_1"

    reference = {"@id": reference_id, "@type": [check_type("cpo:ProcessVariable", namespace_collection), "hlo:Reference"]}
    set_property(reference, "hlo:hasReferenceType", {"@id": reference_type}, namespace_collection)
    if source.strip():
        set_property(reference, "hlo:hasSource", source.strip(), namespace_collection)
    set_literal_property(reference, "qudt:value", float(value.strip()), "xsd:decimal", namespace_collection)
    set_property(reference, "qudt:hasUnit", {"@id": "unit:UNITLESS"}, namespace_collection)
    add_entity(target_graph, reference)

    process_variable = {"@id": pv_id, "@type": [check_type("cpo:ProcessVariable", namespace_collection), "hlo:Actual"]}
    set_property(process_variable, "qudt:hasQuantityKind", quantity_kind_of_property("cpo:hasPartialOrder", namespace_collection), namespace_collection)
    set_property(process_variable, "hlo:hasReference", reference, namespace_collection)
    add_entity(target_graph, process_variable)

    set_property(participant, "cpo:hasPartialOrder", process_variable, namespace_collection)


def create_reaction_participant(reaction: dict, scope: str, nr: int, namespace_collection: dict, datagraph: dict, chemical_entity_library: dict, todo_list: list, local_todo_list: list, evidence_known_cache: dict = None):
    """At hlo:Fixed level (the reaction library script) a participant's species may still be
    undetermined - three degrees: a fixed entity (dcterms:hasPart, as before), a list of
    possible candidates (cpo:hasPotentialCandidate, "any molecule with a triple bond" for
    instance), or completely open (neither, settled only at series level, see
    specialize_reaction_participant_for_series).

    At series and experiment level - free-standing participants not derived from a fixed
    reaction - a concrete species is always asked for, as before.
    """
    participant_type = check_type("cpo:ReactionParticipant", namespace_collection)
    experiment_number = nr if scope == "hlo:ExperimentSpecific" else None
    participant_id = _new_entity_id(f"ReactionParticipant_{short_local_name(reaction['@id'])}", scope, datagraph, todo_list, experiment_number)
    if scope != "hlo:Fixed":
        # n-th participant of this reaction (helpers/identifiers.py), not a running number.
        existing = reaction.get("cpo:hasParticipant") or []
        existing = existing if isinstance(existing, list) else [existing]
        participant_id = claim_id(make_member_id(reaction["@id"], "Participant", len(existing) + 1, scope, experiment_number), datagraph, todo_list, local_todo_list)
    participant = {"@id": participant_id, "@type": [participant_type, scope]}

    species_id = None
    if scope == "hlo:Fixed":
        species_kind = ask_user(
            f"[{scope}] Is the species for this participant of {get_display_label(reaction)} already a fixed "
            f"entity, a placeholder that is only resolved per series, or still completely open?",
            ["Fixed entity", "Placeholder", "Completely open"],
            question_id="species_kind"
        )
        if species_kind == "Fixed entity":
            species_id = _ask_species_or_occupation_state(
                scope, f"participant of {get_display_label(reaction)}", namespace_collection, chemical_entity_library, datagraph, question_id="species"
            )
            set_property(participant, "dcterms:hasPart", {"@id": species_id}, namespace_collection)
        elif species_kind == "Placeholder":
            # "datagraph" IS the reaction_library on this level (see create_fixed_reaction), the
            # placeholders live there. The list of candidates hangs at the placeholder, not at the
            # participant: the same placeholder occurs dozens of times in a template and would
            # otherwise have to be repeated everywhere and kept in step.
            species_id = ask_placeholder(scope, namespace_collection, datagraph, chemical_entity_library, todo_list, question_id="placeholder")
            set_property(participant, "dcterms:hasPart", {"@id": species_id}, namespace_collection)
        # "Completely open": nothing to set - neither dcterms:hasPart nor hasPotentialCandidate.
    else:
        species_id = _ask_species_or_occupation_state(
            scope, f"participant of {get_display_label(reaction)}", namespace_collection, chemical_entity_library, datagraph, question_id="species"
        )
        set_property(participant, "dcterms:hasPart", {"@id": species_id}, namespace_collection)

    participant_label = species_id or "this participant"

    # Allow more than one role (e.g. for reversible reactions, where forward/backward mostly
    # mean different roles - "Substrate" in one direction, "Product" in the other).
    # Asked as one list, at least one (rule 1.4).
    for role in ask_user_list(f"[{scope}] Which chemical roles does {participant_label} have in {get_display_label(reaction)}?",
                              chemical_roles(namespace_collection), question_id="roles", required=True):
        set_property(participant, "cpo:hasChemicalRole", {"@id": role}, namespace_collection, True)

    # A LumpedReaction has no coefficients - not asked, because there is none.
    if not is_lumped(reaction):
        coefficient_answer = ask_user(f"[{scope}] Stoichiometric coefficient of {participant_label} (negative for reactants, positive for products; leave empty if unknown)?", question_id="stoichiometric_coefficient")
        if coefficient_answer.strip():
            set_property(participant, "cpo:hasStoichiometricCoefficient", float(coefficient_answer.strip()), namespace_collection)

    # The partial order is - unlike the coefficient - no stipulation but an empirically
    # determined quantity: it is fitted from measured data and depends on the regime. It
    # therefore goes through the same actual/evidence/reference level as every other measured
    # number of the project (and like cpo:hasReactionRate at the reaction itself), instead of
    # hanging at the participant as a bare number. Unknown then means: an empty actual PV
    # without evidence/reference - the place is marked, the value is missing.
    # Context Molecule/Substance: it is a statement about exactly the species of this
    # participant. Dimensionless, because an exponent has no unit.
    if scope == "hlo:Fixed":
        _ask_fixed_partial_order(participant, datagraph, namespace_collection)
    else:
        add_phase_process_variable(participant, "cpo:hasPartialOrder", scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache)
        add_reaction_outcomes(participant, reaction, scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache)

    set_property(participant, "cpo:participatesIn", reaction, namespace_collection)
    set_property(reaction, "cpo:hasParticipant", participant, namespace_collection, True)

    add_entity(datagraph, participant)
    return participant


def ask_reaction_participants(reaction: dict, scope: str, nr: int, namespace_collection: dict, datagraph: dict, chemical_entity_library: dict, todo_list: list, local_todo_list: list, evidence_known_cache: dict = None):
    """The participants of a reaction as one list of names (rule 1.4) - the name only keys the
    questions about that participant (question path participant:<name>); what the participant
    IS (species, placeholder, open) is asked for each one."""
    participant_names = ask_user(
        f"[{scope}] Which participants does {get_display_label(reaction)} have? Name them, separated by ';' "
        f"(the species or placeholder, e.g. 'RDY; H2; RDEt')",
        answer_type=name_list, question_id="participant_names")
    for participant_name in participant_names:
        with question_path("participant", slugify(participant_name)):
            create_reaction_participant(reaction, scope, nr, namespace_collection, datagraph, chemical_entity_library, todo_list, local_todo_list, evidence_known_cache)


# ---------------------------------------------------------------------------
# ReactionParticipant - hlo:Fixed -> hlo:SeriesSpecific: the concrete species
# is asked afresh (that is the whole point of the generic Fixed level),
# role/coefficient/partial order are inherited unchanged.
# ---------------------------------------------------------------------------

def specialize_reaction_participant_for_series(fixed_participant: dict, reaction: dict, namespace_collection: dict, datagraph: dict, reaction_library: dict, chemical_entity_library: dict, todo_list: list, local_todo_list: list, resolution_cache: dict, evidence_known_cache: dict = None):
    """fixed_participant lives in the reaction library, which is ONLY read and never changed
    - creating a crate does not touch the library, see the module docstring. The reaction
    and the participant are written into the datagraph.

    Four cases, depending on what the fixed participant settles about the species (see
    create_reaction_participant):

    - dcterms:hasPart points at a fixed entity -> carried over directly, no question.
    - dcterms:hasPart points at an cpo:Placeholder -> resolved through resolve_placeholder.
      That happens only ONCE per placeholder per crate run; every further participant
      pointing at the same placeholder gets the same entity without another question (see
      new_resolution_cache).
    - cpo:hasPotentialCandidate on the participant itself rather than on the placeholder ->
      offer a choice from the list, falling back to a free search or creation.
    - none of those (completely open) -> free search or creation.
    """
    scope = "hlo:SeriesSpecific"
    participant_type = check_type("cpo:ReactionParticipant", namespace_collection)
    participant_id = claim_id(make_library_based_id(fixed_participant["@id"], scope), datagraph, todo_list, local_todo_list)
    participant = {"@id": participant_id, "@type": [participant_type, scope]}

    role_refs = fixed_participant.get("cpo:hasChemicalRole")
    role_refs = role_refs if isinstance(role_refs, list) else ([role_refs] if role_refs else [])
    role_ids = [r.get("@id") if isinstance(r, dict) else r for r in role_refs if r]
    role_label = "/".join(r.split(":", 1)[-1] for r in role_ids) or "?"
    context_hint = f"concrete species (role: {role_label}) of \"{get_display_label(reaction)}\" in this series"

    if "dcterms:hasPart" in fixed_participant:
        fixed_species_id = ref_id(fixed_participant["dcterms:hasPart"])
        fixed_species = find_entity(reaction_library, fixed_species_id)
        if _is_placeholder(fixed_species) or _is_open_occupation_state(fixed_species):
            species_id = resolve_placeholder(fixed_species, scope, 1, namespace_collection, datagraph, reaction_library, chemical_entity_library, todo_list, local_todo_list, resolution_cache, evidence_known_cache)
        else:
            species_id = fixed_species_id
    elif "cpo:hasPotentialCandidate" in fixed_participant:
        candidate_refs = fixed_participant["cpo:hasPotentialCandidate"]
        candidate_refs = candidate_refs if isinstance(candidate_refs, list) else [candidate_refs]
        candidate_ids = [c.get("@id") if isinstance(c, dict) else c for c in candidate_refs if c]
        candidates = [(cid, species_label(cid, chemical_entity_library)) for cid in candidate_ids]
        species_id = ask_chemical_entity(scope, context_hint, namespace_collection, chemical_entity_library, extra_candidates=candidates, question_id="species")
    else:
        species_id = _ask_species_or_occupation_state(scope, context_hint, namespace_collection, chemical_entity_library, datagraph, question_id="species")

    set_property(participant, "dcterms:hasPart", {"@id": species_id}, namespace_collection)

    # The roles stand at the Fixed participant and are not repeated here (rule 3.6) - read through
    # hlo:specializationOf, as the coefficient below.

    # The coefficient is a stipulation of the reaction equation, not a measurement - a bare
    # number at the participant. If it stands at the Fixed participant already, it is NOT
    # repeated here: it holds unchanged for every series and every experiment, and whoever needs
    # it goes up via hlo:specializationOf (helpers/entities.py::resolve_inherited).
    # Only if the library leaves it open - e.g. because it depends on the chosen reagent - is it
    # asked here, and then it belongs exactly on this level.
    if "cpo:hasStoichiometricCoefficient" not in fixed_participant and not is_lumped(reaction):
        answer = ask_user(
            f"[{scope}] Stoichiometric coefficient of {species_id} (negative for reactants, positive for products; leave empty if unknown)?",
            question_id="stoichiometric_coefficient"
        )
        if answer.strip():
            set_property(participant, "cpo:hasStoichiometricCoefficient", float(answer.strip()), namespace_collection)

    # specializationOf MUST come before add_phase_process_variable: the function looks for the
    # Fixed counterpart via get_series_entity, to take over a value stored there instead of
    # asking again (see helpers/process_variables.py).
    set_property(participant, "hlo:specializationOf", fixed_participant, namespace_collection)

    # The partial order, however, is empirical - see create_reaction_participant.
    #
    # If it stands at the Fixed participant already (as a ProcessVariable in the reaction_library,
    # with an hlo:Literature reference and a DOI), it is DELIBERATELY NOT repeated here: the value
    # stands once, and whoever looks for it goes up via hlo:specializationOf until finding one -
    # experiment -> series -> Fixed. Phase_Structure_R1 uses the same pattern with
    # [sh:zeroOrMorePath hlo:specializationOf] for the form. Copying the value onto the series
    # level as well would mean keeping the same number in two places.
    #
    # Only if the library yields nothing is an empty actual PV of its own made here: it marks
    # the place where the statement belongs, as soon as somebody determines it.
    if "cpo:hasPartialOrder" not in fixed_participant:
        add_phase_process_variable(participant, "cpo:hasPartialOrder", scope, 1, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache)

    add_reaction_outcomes(participant, reaction, scope, 1, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache)

    set_property(participant, "cpo:participatesIn", reaction, namespace_collection)
    set_property(reaction, "cpo:hasParticipant", participant, namespace_collection, True)

    add_entity(datagraph, participant)
    return participant


# ---------------------------------------------------------------------------
# Yield, conversion, selectivity (rule 3.9): statements about the reaction in a series or an
# experiment, at the participant they refer to - the conversion at what is consumed, yield and
# selectivity at what is formed. Only at participants of an overall reaction (stoichiometric
# or lumped - there on a mass basis): elementary reactions are hypotheses in
# reference mechanisms (module docstring). Never at the Fixed participant of the Reaction
# Library - the library knows no series. Empty actuals like every other quantity; values come
# through the lists (measured, calculated, from the ELN).
# ---------------------------------------------------------------------------

OUTCOME_PROPERTIES_BY_ROLE = {
    "cpo:Reactant": ("cpo:hasConversion",),
    "cpo:Substrate": ("cpo:hasConversion",),
    "cpo:Reagent": ("cpo:hasConversion",),
    "cpo:Product": ("cpo:hasYield", "cpo:hasSelectivity"),
    "cpo:Byproduct": ("cpo:hasYield", "cpo:hasSelectivity"),
}


def add_reaction_outcomes(participant: dict, reaction: dict, scope: str, nr: int, namespace_collection: dict, datagraph: dict, todo_list: list, local_todo_list: list, evidence_known_cache: dict = None):
    """Give a participant of an overall reaction (stoichiometric or lumped) the empty Actuals its
    roles call for (OUTCOME_PROPERTIES_BY_ROLE). The roles are read up the hlo:specializationOf
    chain - an experiment participant does not repeat them (rule 3.6)."""
    if not overall_reaction_class(reaction):
        return
    roles = ref_ids(inherited_value(participant, "cpo:hasChemicalRole", datagraph))
    wanted = []
    for role in roles:
        for property_name in OUTCOME_PROPERTIES_BY_ROLE.get(role, ()):
            if property_name not in wanted:
                wanted.append(property_name)
    for property_name in wanted:
        add_phase_process_variable(participant, property_name, scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache)


def copy_reaction_participants(series_reaction: dict, experiment_reaction: dict, scope: str, nr: int, namespace_collection: dict, datagraph: dict, todo_list: list, local_todo_list: list, evidence_known_cache: dict = None):
    """Experiment level of the participants of a stoichiometric reaction (rule 3.9):
    each series participant gets an experiment counterpart that specializes it, because
    yield, conversion and selectivity - and a partial order known for one experiment - differ
    from run to run and need a holder there. Species and roles are not asked again: the
    species is the same entity, the roles are read up the chain (rule 3.6). Keyed like the
    series participant (participant:<name of the fixed participant>), one level down."""
    participant_type = check_type("cpo:ReactionParticipant", namespace_collection)
    for series_participant_id in ref_ids(series_reaction.get("cpo:hasParticipant")):
        series_participant = find_entity(datagraph, series_participant_id)
        if series_participant is None:
            continue
        key = ref_id(series_participant.get("hlo:specializationOf")) or series_participant_id
        with question_path("participant", key_name(key)):
            participant_id = claim_id(make_specialization_id(series_participant_id, nr), datagraph, todo_list, local_todo_list)
            participant = {"@id": participant_id, "@type": [participant_type, scope]}
            if "dcterms:hasPart" in series_participant:
                set_property(participant, "dcterms:hasPart", series_participant["dcterms:hasPart"], namespace_collection)
            set_property(participant, "hlo:specializationOf", series_participant, namespace_collection)
            set_property(series_participant, "hlo:hasSpecialization", participant, namespace_collection, True)

            add_phase_process_variable(participant, "cpo:hasPartialOrder", scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache)
            add_reaction_outcomes(participant, experiment_reaction, scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache)

            set_property(participant, "cpo:participatesIn", experiment_reaction, namespace_collection)
            set_property(experiment_reaction, "cpo:hasParticipant", participant, namespace_collection, True)
            add_entity(datagraph, participant)


def specialize_reaction_participants_for_series(fixed_reaction: dict, reaction: dict, namespace_collection: dict, datagraph: dict, reaction_library: dict, chemical_entity_library: dict, todo_list: list, local_todo_list: list, resolution_cache: dict, evidence_known_cache: dict = None):
    parts = fixed_reaction.get("cpo:hasParticipant", [])
    parts = parts if isinstance(parts, list) else [parts]
    for ref in parts:
      fixed_id = ref.get("@id") if isinstance(ref, dict) else ref
      with question_path("participant", key_name(fixed_id)):
        fixed_participant = find_entity(reaction_library, fixed_id)
        if fixed_participant:
            specialize_reaction_participant_for_series(fixed_participant, reaction, namespace_collection, datagraph, reaction_library, chemical_entity_library, todo_list, local_todo_list, resolution_cache, evidence_known_cache)


# ---------------------------------------------------------------------------
# Place of the reaction: occursInPhase (bulk) or occursAtInterface (surface) -
# exists only from SeriesSpecific on (Fixed reactions have no phases/interfaces).
# ---------------------------------------------------------------------------

def ask_reaction_location(reaction: dict, scope: str, nr: int, namespace_collection: dict, datagraph: dict):
    kind = ask_user(
        f"[{scope}] Does {get_display_label(reaction)} happen in the bulk of a single phase, or at an interface between phases?",
        ["Bulk (single phase)", "Surface (at an interface)"],
        question_id="location_kind"
    )
    if kind.startswith("Bulk"):
        phase_id = ask_entity_choice(
            f"[{scope}] Which phase does {get_display_label(reaction)} occur in?",
            _all_phases_for_scope(datagraph, scope, nr),
            label_fn=phase_label,
            question_id="location_phase"
        )
        set_property(reaction, "cpo:occursInPhase", {"@id": phase_id}, namespace_collection)
    else:
        interface_id = ask_entity_choice(
            f"[{scope}] Which interface does {get_display_label(reaction)} occur at?",
            _all_interfaces_for_scope(datagraph, scope, nr),
            label_fn=interface_label,
            question_id="location_interface"
        )
        set_property(reaction, "cpo:occursAtInterface", {"@id": interface_id}, namespace_collection)


def copy_reaction_location(series_reaction: dict, experiment_reaction: dict, scope: str, nr: int, datagraph: dict, namespace_collection: dict):
    """Experiment level: carry over the location of the series counterpart - the phase or
    interface is mapped onto the matching experiment entity."""
    for prop in ("cpo:occursInPhase", "cpo:occursAtInterface"):
        series_ref = series_reaction.get(prop)
        if not series_ref:
            continue
        series_id = series_ref.get("@id") if isinstance(series_ref, dict) else series_ref
        target_id = _find_experiment_counterpart(series_id, scope, nr, datagraph)
        if target_id:
            set_property(experiment_reaction, prop, {"@id": target_id}, namespace_collection)
        return


# ---------------------------------------------------------------------------
# Transfers for interface reactions: every participant of a reaction at an
# interface that is no OccupationState is linked with a transfer
# (cpo:involvesTransfer/cpo:isInvolvedIn) - bulk reactions (occursInPhase)
# need no transfers. Asked/resolved only on the SeriesSpecific level (the
# participants live there, see the module docstring); on the ExperimentSpecific
# level the links are mapped 1:1 onto the experiment transfers that exist already
# via copy_reaction_transfers (they are made automatically in phase_functions.py,
# see handle_transfers_for_pair_interface).
# ---------------------------------------------------------------------------

def _phase_species_ids(phase: dict) -> list:
    parts = phase.get("dcterms:hasPart", [])
    parts = parts if isinstance(parts, list) else [parts]
    return [p.get("@id") if isinstance(p, dict) else p for p in parts if p]


def link_reaction_transfers(reaction: dict, scope: str, nr: int, namespace_collection: dict, datagraph: dict, reaction_library: dict, chemical_entity_library: dict, todo_list: list, local_todo_list: list, evidence_known_cache: dict = None):
    """Link every non-occupation-state participant of an interface reaction to a transfer at
    the same interface.

    A negative coefficient means the participant leaves a phase (removesFromPhase), a
    positive one that it enters a phase (addsToPhase); where the coefficient is missing, the
    direction is asked for. The phase involved is chosen from the one or two phases of the
    interface, and is only asked about when it is not unambiguous - when the species is in
    neither or in both phases. For cpo:Reversible the reverse transfer, with the direction
    swapped, is linked as well. Matching transfers that already exist are reused through
    get_or_create_transfer rather than duplicated.
    """
    interface_ref = reaction.get("cpo:occursAtInterface")
    if not interface_ref:
        return

    interface_id = interface_ref.get("@id") if isinstance(interface_ref, dict) else interface_ref
    interface = find_entity(datagraph, interface_id)
    if interface is None:
        return

    interface_phases = get_interface_phases(interface, datagraph)
    is_reversible = ref_id(inherited_value(reaction, "cpo:hasReversibility", datagraph)) == "cpo:Reversible"   # rule 3.6
    non_port_crossing_types = [t for t in transfer_types(namespace_collection) if t != "cpo:PortCrossing"]

    participant_refs = reaction.get("cpo:hasParticipant", [])
    participant_refs = participant_refs if isinstance(participant_refs, list) else [participant_refs]

    for participant_ref in participant_refs:
      participant_id = participant_ref.get("@id") if isinstance(participant_ref, dict) else participant_ref
      with question_path("participant_transfer", key_name(participant_id)):
        participant = find_entity(datagraph, participant_id)
        if participant is None:
            continue

        species_ref = participant.get("dcterms:hasPart")
        species_id = species_ref.get("@id") if isinstance(species_ref, dict) else species_ref
        if species_id is None:
            continue

        species_entity = find_entity(datagraph, species_id)
        if species_entity and "cpo:OccupationState" in (species_entity.get("@type") or []):
            continue  # the place follows from cpo:belongsToInterface, no transfer needed.

        # Resolved via the chain instead of read directly: the coefficient usually stands only
        # at the Fixed participant in the reaction_library and is not copied down (see
        # specialize_reaction_participants_for_series).
        coefficient = resolve_inherited(participant, "cpo:hasStoichiometricCoefficient", datagraph, reaction_library)

        # LumpedReaction: no coefficient - the role says whether the substance is consumed or formed.
        # Neither (catalyst ...) means the same as coefficient 0: no transfer. Both: asked as before.
        if is_lumped(reaction):
            roles = set(ref_ids(resolve_inherited(participant, "cpo:hasChemicalRole", datagraph, reaction_library)))
            consumed, formed = bool(roles & LUMPED_CONSUMED_ROLES), bool(roles & LUMPED_FORMED_ROLES)
            if consumed != formed:
                coefficient = -1 if consumed else 1
            elif not consumed:
                coefficient = 0

        # In the convention of this model (negative = consumed, positive = formed) coefficient 0
        # explicitly means "neither" - the participant is there, but does not change its amount
        # and consequently does not change its place either. The typical case is the catalyst of
        # an overall reaction: it stands in it as a participant because the reaction does not run
        # without it, but does not appear in the equation itself. Without this check it would get
        # a transfer, and in the end the crate would hold a movement of platinum out of the liquid
        # phase - a statement nobody made.
        #
        # The coefficient is checked, not the role: that catches every participant that is not
        # consumed, not only those that happen to be called "Catalyst". If the coefficient is
        # missing entirely, the question further below remains - missing means unknown, not zero.
        if coefficient == 0:
            continue

        species_name = species_label(species_id, chemical_entity_library)

        if coefficient is None:
            direction = ask_user(
                f"[{scope}] Does {species_name} leave a phase (reactant-like) or enter a phase (product-like) at {interface_label(interface)}?",
                ["Leaves a phase (reactant-like)", "Enters a phase (product-like)"],
                question_id="direction"
            )
            is_reactant = direction.startswith("Leaves")
        else:
            is_reactant = coefficient < 0

        matches = [p for p in interface_phases if species_id in _phase_species_ids(p)]
        candidates = matches if matches else interface_phases
        phase = None
        if len(candidates) == 1:
            phase = candidates[0]
        elif candidates:
            phase_id = ask_entity_choice(
                f"[{scope}] Which phase at {interface_label(interface)} is involved for {species_name}?",
                candidates, label_fn=phase_label, question_id="phase"
            )
            phase = find_entity(datagraph, phase_id)

        source_phase = phase if is_reactant else None
        destination_phase = None if is_reactant else phase

        transfer_type = ask_user(f"[{scope}] Which type of transfer moves {species_name} at {interface_label(interface)}?", non_port_crossing_types, question_id="transfer_type")

        transfer = get_or_create_transfer(
            interface, "interface", species_id, transfer_type, scope, nr, namespace_collection, datagraph, chemical_entity_library, todo_list, local_todo_list,
            source_phase=source_phase, destination_phase=destination_phase, evidence_known_cache=evidence_known_cache, allow_create=False
        )
        set_property(reaction, "cpo:involvesTransfer", transfer, namespace_collection, True)
        set_property(transfer, "cpo:isInvolvedIn", reaction, namespace_collection, True)

        if is_reversible:
            # The counter-transfer gets the reverse type, not the same one with the phases swapped
            # (see reverse_transfer_type in helpers/transfer_functions.py). A segment of its own,
            # "reverse": without it the hasFlowrate question of this counter-transfer would share the
            # same key as that of the forward transfer above (both lie under the same
            # "participant_transfer:i").
            with question_path("reverse"):
                counter_transfer = get_or_create_transfer(
                    interface, "interface", species_id, reverse_transfer_type(transfer_type, namespace_collection), scope, nr, namespace_collection, datagraph, chemical_entity_library, todo_list, local_todo_list,
                    source_phase=destination_phase, destination_phase=source_phase, evidence_known_cache=evidence_known_cache, allow_create=False
                )
            set_property(reaction, "cpo:involvesTransfer", counter_transfer, namespace_collection, True)
            set_property(counter_transfer, "cpo:isInvolvedIn", reaction, namespace_collection, True)


def _all_transfers_for_scope(datagraph: dict, scope: str, nr: int) -> list:
    result = []
    for entity in datagraph.get("@graph", []):
        types = as_list(entity.get("@type"))
        if scope not in types or "cpo:Transfer" not in types:
            continue
        if scope != "hlo:ExperimentSpecific":
            result.append(entity)
            continue
        phase_ids = []
        for prop in ("cpo:removesFromPhase", "cpo:addsToPhase"):
            ref = entity.get(prop)
            if ref:
                phase_ids.append(ref.get("@id") if isinstance(ref, dict) else ref)
        phases = [find_entity(datagraph, pid) for pid in phase_ids]
        if any(p and phase_matches_experiment(p, scope, nr, datagraph) for p in phases):
            result.append(entity)
    return result


def _find_experiment_transfer_counterpart(series_id: str, scope: str, nr: int, datagraph: dict):
    """Like _find_experiment_counterpart, but for transfers instead of phases/interfaces."""
    for entity in _all_transfers_for_scope(datagraph, scope, nr):
        series_entity = get_series_entity(entity, datagraph)
        if series_entity and series_entity["@id"] == series_id:
            return entity["@id"]
    return None


def copy_reaction_transfers(series_reaction: dict, experiment_reaction: dict, scope: str, nr: int, datagraph: dict, namespace_collection: dict):
    """Experiment level: map the cpo:involvesTransfer links of the series counterpart onto
    the experiment transfers that already exist.

    Those arise automatically from the series transfers in phase_functions.py; here only the
    reaction link is brought along, and no new transfers are created.
    """
    transfer_refs = series_reaction.get("cpo:involvesTransfer", [])
    transfer_refs = transfer_refs if isinstance(transfer_refs, list) else [transfer_refs]
    for series_transfer_ref in transfer_refs:
        series_transfer_id = series_transfer_ref.get("@id") if isinstance(series_transfer_ref, dict) else series_transfer_ref
        target_id = _find_experiment_transfer_counterpart(series_transfer_id, scope, nr, datagraph)
        if not target_id:
            continue
        target = find_entity(datagraph, target_id)
        set_property(experiment_reaction, "cpo:involvesTransfer", target, namespace_collection, True)
        set_property(target, "cpo:isInvolvedIn", experiment_reaction, namespace_collection, True)


# ---------------------------------------------------------------------------
# Common core of StoichiometricReaction and ElementaryReaction on the
# SeriesSpecific/ExperimentSpecific level: place, hasReactionRate. (Name/
# description/participants run on the hlo:Fixed level or are specialized/
# copied from there - see above/below.)
# ---------------------------------------------------------------------------

# cpo:ReactionRate instead of quantitykind:ReactionRate: QUDT knows no general reaction
# rate. The IRI quantitykind:ReactionRate does not exist in any version of QUDT (404 on qudt.org). The three closest real terms all do not
# fit: CatalyticActivityConcentration has exactly the right dimension, but according to its
# own definition means enzyme activity per volume of the enzyme preparation; ExtentOfReaction
# is the amount of substance of a conversion, not a rate; SecondOrderReactionRateConstant is a
# constant. Hence a QuantityKind of its own in its own namespace - declared in the
# ChemicalProcessOntology, with the dimension vector qkdv:A1E0L-3I0M0H0T-1D0 (mol/(m3*s)) and
# unit:MOL-PER-M3-SEC as its unit.
def _ask_reaction_location_and_rate(reaction: dict, scope: str, nr: int, namespace_collection: dict, datagraph: dict, todo_list: list, local_todo_list: list, evidence_known_cache: dict = None):
    ask_reaction_location(reaction, scope, nr, namespace_collection, datagraph)
    add_phase_process_variable(reaction, "cpo:hasReactionRate", scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache)


def _copy_reaction_location_and_rate(series_reaction: dict, reaction: dict, scope: str, nr: int, namespace_collection: dict, datagraph: dict, todo_list: list, local_todo_list: list, evidence_known_cache: dict = None):
    copy_reaction_location(series_reaction, reaction, scope, nr, datagraph, namespace_collection)
    add_phase_process_variable(reaction, "cpo:hasReactionRate", scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache)


# ---------------------------------------------------------------------------
# ElementaryReaction (lives within a ReactionMechanism)
# ---------------------------------------------------------------------------

def create_elementary_reaction(mechanism: dict, scope: str, nr: int, namespace_collection: dict, datagraph: dict, chemical_entity_library: dict, todo_list: list, local_todo_list: list, evidence_known_cache: dict = None, include_location_and_rate: bool = True, name: str = None):
    reaction_type = check_type("cpo:ElementaryReaction", namespace_collection)
    experiment_number = nr if scope == "hlo:ExperimentSpecific" else None
    entity_id = _new_entity_id(reaction_type, scope, datagraph, todo_list, experiment_number)
    reaction = {"@id": entity_id, "@type": [reaction_type, scope]}

    if name is None:
        name = ask_optional_name(scope, "Elementary Reaction", entity_id)
    set_property(reaction, "schema:name", name, namespace_collection)
    print(f"\n=== Now describing Elementary Reaction \"{name}\" ({entity_id}, {scope}) ===")

    description = ask_user(f"[{scope}] Please describe {name} (e.g. the written reaction equation - additional notes welcome)?", question_id="description")
    set_property(reaction, "schema:description", description, namespace_collection)
    ask_reaction_participants(reaction, scope, nr, namespace_collection, datagraph, chemical_entity_library, todo_list, local_todo_list, evidence_known_cache)

    if include_location_and_rate:
        _ask_reaction_location_and_rate(reaction, scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache)

    reversibility = ask_user(f"[{scope}] Is {name} reversible or irreversible?", reversibility_values(namespace_collection), question_id="reversibility")
    set_property(reaction, "cpo:hasReversibility", {"@id": reversibility}, namespace_collection)

    set_property(mechanism, "cpo:containsElementaryReaction", reaction, namespace_collection, True)

    add_entity(datagraph, reaction)
    return reaction


def specialize_elementary_reaction_for_series(fixed_elem: dict, mechanism: dict, namespace_collection: dict, datagraph: dict, reaction_library: dict, chemical_entity_library: dict, todo_list: list, local_todo_list: list, resolution_cache: dict, evidence_known_cache: dict = None):
    scope = "hlo:SeriesSpecific"
    reaction_type = check_type("cpo:ElementaryReaction", namespace_collection)
    entity_id = claim_id(make_library_based_id(fixed_elem["@id"], scope), datagraph, todo_list, local_todo_list)
    reaction = {"@id": entity_id, "@type": [reaction_type, scope]}

    name = fixed_elem.get("schema:name") or generate_name(entity_id)
    set_property(reaction, "schema:name", name, namespace_collection)
    print(f"\n=== Now describing Elementary Reaction \"{name}\" ({entity_id}, {scope}) ===")

    set_property(reaction, "hlo:specializationOf", fixed_elem, namespace_collection)
    # Inverse direction only at an entity of the crate - the library is not changed (rule 2.2).
    if not is_library_entity(fixed_elem):
        set_property(fixed_elem, "hlo:hasSpecialization", reaction, namespace_collection, True)

    if "schema:description" in fixed_elem:
        set_property(reaction, "schema:description", fixed_elem["schema:description"], namespace_collection)

    specialize_reaction_participants_for_series(fixed_elem, reaction, namespace_collection, datagraph, reaction_library, chemical_entity_library, todo_list, local_todo_list, resolution_cache, evidence_known_cache)
    _ask_reaction_location_and_rate(reaction, scope, 1, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache)

    # The reversibility stands at the Fixed elementary reaction, not repeated here (rule 3.6).

    link_reaction_transfers(reaction, scope, 1, namespace_collection, datagraph, reaction_library, chemical_entity_library, todo_list, local_todo_list, evidence_known_cache)

    set_property(mechanism, "cpo:containsElementaryReaction", reaction, namespace_collection, True)

    add_entity(datagraph, reaction)
    return reaction


def copy_elementary_reaction(series_reaction: dict, mechanism: dict, scope: str, nr: int, namespace_collection: dict, datagraph: dict, todo_list: list, local_todo_list: list, evidence_known_cache: dict = None):
    reaction_type = check_type("cpo:ElementaryReaction", namespace_collection)
    entity_id = claim_id(make_specialization_id(series_reaction["@id"], nr), datagraph, todo_list, local_todo_list)
    reaction = {"@id": entity_id, "@type": [reaction_type, scope]}

    name = series_reaction.get("schema:name") or generate_name(entity_id)
    set_property(reaction, "schema:name", name, namespace_collection)
    print(f"\n=== Now describing Elementary Reaction \"{name}\" ({entity_id}, {scope}, Experiment {nr}) ===")

    set_property(reaction, "hlo:specializationOf", series_reaction, namespace_collection)
    set_property(series_reaction, "hlo:hasSpecialization", reaction, namespace_collection, True)

    if "schema:description" in series_reaction:
        set_property(reaction, "schema:description", series_reaction["schema:description"], namespace_collection)

    # Participants are NO LONGER copied per experiment - they are described sufficiently on
    # the series level already (see create_experiment_reaction). Only place/rate are specific
    # to the experiment.
    _copy_reaction_location_and_rate(series_reaction, reaction, scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache)

    # The reversibility is read through hlo:specializationOf, not repeated (rule 3.6).

    copy_reaction_transfers(series_reaction, reaction, scope, nr, datagraph, namespace_collection)

    set_property(mechanism, "cpo:containsElementaryReaction", reaction, namespace_collection, True)

    add_entity(datagraph, reaction)
    return reaction


def ask_elementary_reactions(mechanism: dict, scope: str, nr: int, namespace_collection: dict, datagraph: dict, chemical_entity_library: dict, todo_list: list, local_todo_list: list, evidence_known_cache: dict = None, include_location_and_rate: bool = True):
    """The elementary reactions of a mechanism as one list of names (rule 1.4); the name is
    the reaction's name and its question-path key."""
    reaction_names = ask_user(
        f"[{scope}] Which elementary reactions does {get_display_label(mechanism)} consist of? Name them, separated by ';'",
        answer_type=name_list, question_id="elementary_reaction_names")
    for reaction_name in reaction_names:
        with question_path("elementary_reaction", slugify(reaction_name)):
            create_elementary_reaction(mechanism, scope, nr, namespace_collection, datagraph, chemical_entity_library, todo_list, local_todo_list, evidence_known_cache, include_location_and_rate, name=reaction_name)


def specialize_elementary_reactions_for_series(fixed_mechanism: dict, mechanism: dict, namespace_collection: dict, datagraph: dict, reaction_library: dict, chemical_entity_library: dict, todo_list: list, local_todo_list: list, resolution_cache: dict, evidence_known_cache: dict = None):
    """The same fixed elementary reaction can belong to SEVERAL mechanisms (the RDEt
    adsorption belongs to both dimerisation mechanisms). It is then specialized only once and
    the second mechanism links the same entity - it is the same reaction after all, and it
    does not know what happens before or after it.
    """
    parts = fixed_mechanism.get("cpo:containsElementaryReaction", [])
    parts = parts if isinstance(parts, list) else [parts]
    for ref in parts:
        fixed_id = ref.get("@id") if isinstance(ref, dict) else ref
        already_specialized = resolution_cache["elementary"].get(fixed_id)
        if already_specialized is not None:
            set_property(mechanism, "cpo:containsElementaryReaction", already_specialized, namespace_collection, True)
            continue
        # Directly under the series, not under the mechanism: the same elementary reaction often
        # belongs to several mechanisms, it is asked only with the first - and which one that is
        # depends on the order of the reactions (counter-check P4).
        with question_path("elementary_reaction", key_name(fixed_id), under=("series", "experiment")):
            fixed_elem = find_entity(reaction_library, fixed_id)
            if fixed_elem:
                resolution_cache["elementary"][fixed_id] = specialize_elementary_reaction_for_series(fixed_elem, mechanism, namespace_collection, datagraph, reaction_library, chemical_entity_library, todo_list, local_todo_list, resolution_cache, evidence_known_cache)


def copy_elementary_reactions(series_mechanism: dict, mechanism: dict, scope: str, nr: int, namespace_collection: dict, datagraph: dict, todo_list: list, local_todo_list: list, resolution_cache: dict, evidence_known_cache: dict = None):
    """The experiment counterpart of specialize_elementary_reactions_for_series, with the
    same de-duplication: an elementary reaction shared by two mechanisms is copied only once
    per experiment.

    The cache key therefore contains the experiment number: every experiment needs its own
    copy, with its own location and its own rate, but within one experiment only one.
    """
    parts = series_mechanism.get("cpo:containsElementaryReaction", [])
    parts = parts if isinstance(parts, list) else [parts]
    for series_ref in parts:
        series_id = series_ref.get("@id") if isinstance(series_ref, dict) else series_ref
        already_copied = resolution_cache["elementary_experiment"].get((nr, series_id))
        if already_copied is not None:
            set_property(mechanism, "cpo:containsElementaryReaction", already_copied, namespace_collection, True)
            continue
        # A segment of its own per elementary reaction - without it the hasReactionRate questions
        # of all elementary reactions of a mechanism share the same key of the answer file
        # (see helpers/user_io.py).
        with question_path("elementary_reaction", key_name(series_id), under=("series", "experiment")):
            series_reaction = find_entity(datagraph, series_id)
            if series_reaction:
                resolution_cache["elementary_experiment"][(nr, series_id)] = copy_elementary_reaction(series_reaction, mechanism, scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache)


# ---------------------------------------------------------------------------
# ReactionMechanism
# ---------------------------------------------------------------------------

def create_actual_reaction_mechanism_placeholder(scope: str, namespace_collection: dict, container: dict, todo_list: list, reaction: dict):
    """A bare hlo:Actual reaction mechanism anchor WITHOUT content - no elementary
    reactions, no name prompt.

    The mechanism that actually runs is usually not known for certain; only the candidates
    and hypotheses that can actually be described are (see hlo:hasReference, filled by
    create_reference_reaction_mechanism).

    A reaction has at most one such anchor, so in the crate its ID comes from the reaction
    (".../ReactionMechanism_StoichiometricReaction_0002_SeriesSpecific"), not from a counter -
    a counter would depend on the order of the reactions (rule 1.1). In the reaction library
    the anchor keeps a library ID like every other entry there.
    """
    mechanism_type = check_type("cpo:ReactionMechanism", namespace_collection)
    if scope == "hlo:Fixed":
        mechanism_id = _new_entity_id(mechanism_type, scope, container, todo_list)
    else:
        mechanism_id = claim_id(make_owned_id("ReactionMechanism", reaction["@id"]), container, todo_list)
    mechanism = {"@id": mechanism_id, "@type": [mechanism_type, scope, "hlo:Actual"], "schema:name": generate_name(mechanism_id)}
    add_entity(container, mechanism)
    return mechanism


def create_reference_reaction_mechanism(actual_mechanism: dict, scope: str, nr: int, namespace_collection: dict, datagraph: dict, chemical_entity_library: dict, todo_list: list, local_todo_list: list, evidence_known_cache: dict = None, include_location_and_rate: bool = True, name: str = None):
    """A mechanism actually described with content (elementary reactions) - always an
    hlo:Reference of the actual_mechanism anchor, never hlo:Actual (see module docstring), with
    its reference type asked for and a source required."""
    mechanism_type = check_type("cpo:ReactionMechanism", namespace_collection)
    experiment_number = nr if scope == "hlo:ExperimentSpecific" else None
    # The n-th reference of the anchor, named like every other value: <anchor>_Reference_<n>
    # (rule 1.6). In the library without a level ending like all library IDs, in the crate via make_member_id.
    n = len(ref_ids(actual_mechanism.get("hlo:hasReference"))) + 1
    if scope == "hlo:Fixed":
        candidate = f"{actual_mechanism['@id']}_Reference_{n}"
    else:
        candidate = make_member_id(actual_mechanism["@id"], "Reference", n, scope, experiment_number)
    mechanism_id = claim_id(candidate, datagraph, todo_list, local_todo_list)
    mechanism = {"@id": mechanism_id, "@type": [mechanism_type, scope, "hlo:Reference"]}

    if name is None:
        name = ask_optional_name(scope, "Reaction Mechanism", mechanism_id)
    set_property(mechanism, "schema:name", name, namespace_collection)

    # The type is asked as for every reference, and a mechanism needs a source (rule 4.1).
    # Type and source stand only here; series and experiment read them via
    # hlo:specializationOf.
    reference_type = ask_user(f"[{scope}] Where does {name} come from?", reference_types(namespace_collection), question_id="reference_type")
    source = ""
    while not source.strip():
        source = ask_user(f"[{scope}] Source of {name} (DOI, URL, ...)?", question_id="source")
        if not source.strip():
            print("A reaction mechanism needs a source.")
    set_property(mechanism, "hlo:hasReferenceType", {"@id": reference_type}, namespace_collection)
    set_property(mechanism, "hlo:hasSource", source.strip(), namespace_collection)

    print(f"\n=== Now describing Reaction Mechanism \"{name}\" ({mechanism_id}, {scope}) ===")

    ask_elementary_reactions(mechanism, scope, nr, namespace_collection, datagraph, chemical_entity_library, todo_list, local_todo_list, evidence_known_cache, include_location_and_rate)

    add_entity(datagraph, mechanism)
    return mechanism


def ask_reaction_mechanism(reaction: dict, scope: str, nr: int, namespace_collection: dict, datagraph: dict, chemical_entity_library: dict, todo_list: list, local_todo_list: list, evidence_known_cache: dict = None, include_location_and_rate: bool = True):
    """Ask whether (at least) one reaction mechanism should be described for this
    stoichiometric reaction. Optional.

    Since it usually cannot be known for certain which mechanism actually runs, the described
    mechanism is NOT itself marked as hlo:Actual. Instead the reaction gets an empty
    hlo:Actual anchor (create_actual_reaction_mechanism_placeholder), and every mechanism
    actually described - one's own hypothesis, or one from the literature - hangs off it as
    an hlo:Reference (hlo:hasReference/hlo:isReferenceOf). That holds for the first mechanism
    too, not only for "alternative" ones.

    Called at hlo:Fixed level only; series and experiment specialize or copy the whole
    structure (anchor plus reference mechanisms) one to one, see
    specialize_reaction_mechanism_for_series and copy_reaction_mechanism.
    """
    answer = ask_user(f"[{scope}] Do you want to describe a Reaction Mechanism (elementary reactions) for {get_display_label(reaction)}?", ["Yes", "No"], question_id="want_mechanism")
    if answer == "No":
        return None

    actual_mechanism = create_actual_reaction_mechanism_placeholder(scope, namespace_collection, datagraph, todo_list, reaction)
    set_property(reaction, "cpo:describedByReactionMechanism", actual_mechanism, namespace_collection)
    set_property(actual_mechanism, "cpo:describesStoichiometricReaction", reaction, namespace_collection)

    # The candidate mechanisms as one list of names (rule 1.4); the name is the name of the
    # mechanism and its key in the question path.
    mechanism_names = ask_user(
        f"[{scope}] Which candidate Reaction Mechanisms (your own hypotheses, or ones found in the literature) do you "
        f"want to describe for {get_display_label(reaction)}? Name them, separated by ';'",
        answer_type=name_list, question_id="reference_mechanism_names")
    for mechanism_name in mechanism_names:
        with question_path("reference_mechanism", slugify(mechanism_name)):
            reference_mechanism = create_reference_reaction_mechanism(actual_mechanism, scope, nr, namespace_collection, datagraph, chemical_entity_library, todo_list, local_todo_list, evidence_known_cache, include_location_and_rate, name=mechanism_name)
            set_property(reference_mechanism, "cpo:describesStoichiometricReaction", reaction, namespace_collection)
            set_property(actual_mechanism, "hlo:hasReference", reference_mechanism, namespace_collection, True)
            set_property(reference_mechanism, "hlo:isReferenceOf", actual_mechanism, namespace_collection)

    return actual_mechanism


def specialize_reference_mechanism_for_series(fixed_ref_mechanism: dict, namespace_collection: dict, datagraph: dict, reaction_library: dict, chemical_entity_library: dict, todo_list: list, local_todo_list: list, resolution_cache: dict, evidence_known_cache: dict = None):
    """Specialize a single hlo:Reference mechanism of the fixed level - name inherited,
    elementary reactions specialized. Type, source and determination task stay on the library
    entry and are read through hlo:specializationOf."""
    scope = "hlo:SeriesSpecific"
    mechanism_type = check_type("cpo:ReactionMechanism", namespace_collection)
    mechanism_id = claim_id(make_library_based_id(fixed_ref_mechanism["@id"], scope), datagraph, todo_list, local_todo_list)
    name = fixed_ref_mechanism.get("schema:name") or generate_name(mechanism_id)
    mechanism = {"@id": mechanism_id, "@type": [mechanism_type, scope, "hlo:Reference"], "schema:name": name}

    # Deliberate exception from rule 4.1: the mechanism needs an entity of its own per level (its
    # elementary reactions get substances, places and rates), but in content it is the same as in
    # the library. Type, source and determination task therefore stand only there and are not
    # repeated per level (rule 3.6).

    print(f"\n=== Now describing Reaction Mechanism \"{name}\" ({mechanism_id}, {scope}) ===")

    set_property(mechanism, "hlo:specializationOf", fixed_ref_mechanism, namespace_collection)
    # Inverse direction only at an entity of the crate - the library is not changed (rule 2.2).
    if not is_library_entity(fixed_ref_mechanism):
        set_property(fixed_ref_mechanism, "hlo:hasSpecialization", mechanism, namespace_collection, True)

    specialize_elementary_reactions_for_series(fixed_ref_mechanism, mechanism, namespace_collection, datagraph, reaction_library, chemical_entity_library, todo_list, local_todo_list, resolution_cache, evidence_known_cache)

    add_entity(datagraph, mechanism)
    return mechanism


def specialize_reaction_mechanism_for_series(fixed_reaction: dict, reaction: dict, namespace_collection: dict, datagraph: dict, reaction_library: dict, chemical_entity_library: dict, todo_list: list, local_todo_list: list, resolution_cache: dict, evidence_known_cache: dict = None):
    """Series level: specialize the hlo:Actual anchor, where there is one, together with
    every hlo:Reference mechanism of the fixed reaction. No renewed question about whether
    one should exist at all."""
    fixed_actual_ref = fixed_reaction.get("cpo:describedByReactionMechanism")
    if not fixed_actual_ref:
        return None

    fixed_actual_id = fixed_actual_ref.get("@id") if isinstance(fixed_actual_ref, dict) else fixed_actual_ref
    fixed_actual = find_entity(reaction_library, fixed_actual_id)
    if not fixed_actual:
        return None

    scope = "hlo:SeriesSpecific"
    actual_mechanism = create_actual_reaction_mechanism_placeholder(scope, namespace_collection, datagraph, todo_list, reaction)
    set_property(actual_mechanism, "hlo:specializationOf", fixed_actual, namespace_collection)
    # Inverse direction only at an entity of the crate - the library is not changed (rule 2.2).
    if not is_library_entity(fixed_actual):
        set_property(fixed_actual, "hlo:hasSpecialization", actual_mechanism, namespace_collection, True)

    set_property(reaction, "cpo:describedByReactionMechanism", actual_mechanism, namespace_collection)
    set_property(actual_mechanism, "cpo:describesStoichiometricReaction", reaction, namespace_collection)

    fixed_references = fixed_actual.get("hlo:hasReference", [])
    fixed_references = fixed_references if isinstance(fixed_references, list) else [fixed_references]
    for fixed_ref in fixed_references:
      # A segment of its own per candidate mechanism, under its library key - otherwise two
      # mechanisms of the same reaction share the question keys of their elementary reactions
      # (see helpers/user_io.py).
      with question_path("reference_mechanism", key_name(ref_id(fixed_ref))):
        fixed_ref_id = ref_id(fixed_ref)
        fixed_ref_mechanism = find_entity(reaction_library, fixed_ref_id)
        if not fixed_ref_mechanism:
            continue
        reference_mechanism = specialize_reference_mechanism_for_series(fixed_ref_mechanism, namespace_collection, datagraph, reaction_library, chemical_entity_library, todo_list, local_todo_list, resolution_cache, evidence_known_cache)
        set_property(reference_mechanism, "cpo:describesStoichiometricReaction", reaction, namespace_collection)
        set_property(actual_mechanism, "hlo:hasReference", reference_mechanism, namespace_collection, True)
        set_property(reference_mechanism, "hlo:isReferenceOf", actual_mechanism, namespace_collection)

    return actual_mechanism


def copy_reference_mechanism(series_ref_mechanism: dict, scope: str, nr: int, namespace_collection: dict, datagraph: dict, todo_list: list, local_todo_list: list, resolution_cache: dict, evidence_known_cache: dict = None):
    """Experiment level: carry over a single hlo:Reference mechanism of the series
    counterpart one to one (phase mapping and the fresh rate run through
    copy_elementary_reactions)."""
    mechanism_type = check_type("cpo:ReactionMechanism", namespace_collection)
    mechanism_id = claim_id(make_specialization_id(series_ref_mechanism["@id"], nr), datagraph, todo_list, local_todo_list)
    name = series_ref_mechanism.get("schema:name") or generate_name(mechanism_id)
    mechanism = {"@id": mechanism_id, "@type": [mechanism_type, scope, "hlo:Reference"], "schema:name": name}
    # Do not repeat type and source - see specialize_reference_mechanism_for_series.

    print(f"\n=== Now describing Reaction Mechanism \"{name}\" ({mechanism_id}, {scope}, Experiment {nr}) ===")

    set_property(mechanism, "hlo:specializationOf", series_ref_mechanism, namespace_collection)
    set_property(series_ref_mechanism, "hlo:hasSpecialization", mechanism, namespace_collection, True)

    copy_elementary_reactions(series_ref_mechanism, mechanism, scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, resolution_cache, evidence_known_cache)

    add_entity(datagraph, mechanism)
    return mechanism


def copy_reaction_mechanism(series_reaction: dict, reaction: dict, scope: str, nr: int, namespace_collection: dict, datagraph: dict, todo_list: list, local_todo_list: list, resolution_cache: dict, evidence_known_cache: dict = None):
    """Experiment level: carry over the hlo:Actual anchor, where there is one, together with
    every hlo:Reference mechanism of the series counterpart, one to one and without a
    question."""
    series_actual_ref = series_reaction.get("cpo:describedByReactionMechanism")
    if not series_actual_ref:
        return None

    series_actual_id = series_actual_ref.get("@id") if isinstance(series_actual_ref, dict) else series_actual_ref
    series_actual = find_entity(datagraph, series_actual_id)
    if not series_actual:
        return None

    actual_mechanism = create_actual_reaction_mechanism_placeholder(scope, namespace_collection, datagraph, todo_list, reaction)
    set_property(actual_mechanism, "hlo:specializationOf", series_actual, namespace_collection)
    set_property(series_actual, "hlo:hasSpecialization", actual_mechanism, namespace_collection, True)

    set_property(reaction, "cpo:describedByReactionMechanism", actual_mechanism, namespace_collection)
    set_property(actual_mechanism, "cpo:describesStoichiometricReaction", reaction, namespace_collection)

    series_references = series_actual.get("hlo:hasReference", [])
    series_references = series_references if isinstance(series_references, list) else [series_references]
    for series_ref in series_references:
      with question_path("reference_mechanism", key_name(ref_id(series_ref))):
        series_ref_id = ref_id(series_ref)
        series_ref_mechanism = find_entity(datagraph, series_ref_id)
        if not series_ref_mechanism:
            continue
        reference_mechanism = copy_reference_mechanism(series_ref_mechanism, scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, resolution_cache, evidence_known_cache)
        set_property(reference_mechanism, "cpo:describesStoichiometricReaction", reaction, namespace_collection)
        set_property(actual_mechanism, "hlo:hasReference", reference_mechanism, namespace_collection, True)
        set_property(reference_mechanism, "hlo:isReferenceOf", actual_mechanism, namespace_collection)

    return actual_mechanism


# ---------------------------------------------------------------------------
# StoichiometricReaction - hlo:Fixed
# ---------------------------------------------------------------------------

def create_fixed_reaction(namespace_collection: dict, reaction_library: dict, chemical_entity_library: dict, todo_list: list, local_todo_list: list, name: str = None):
    """Create a new fixed reaction directly in the reaction library - NOT in the datagraph
    of the current crate.

    todo_list and local_todo_list are still those of the current crate run; they are only
    needed here for the ID uniqueness check, since fixed reactions have no
    phase and no rate yet, and therefore no evidence or reference placeholders either.
    """
    scope = "hlo:Fixed"
    reaction_type = check_type("cpo:StoichiometricReaction", namespace_collection)
    entity_id = generate_library_id("reaction", reaction_type, reaction_library)
    reaction = {"@id": entity_id, "@type": [reaction_type, scope]}

    if name is None:
        name = ask_optional_name(scope, "Reaction", entity_id)
    set_property(reaction, "schema:name", name, namespace_collection)
    print(f"\n=== Now describing Reaction \"{name}\" ({entity_id}, {scope}) - will be saved to the reaction library ===")

    description = ask_user(
        f"[{scope}] Please describe {name} (e.g. the written reaction equation - if this is a generic reaction "
        f"pattern (like a hydrogenation applicable to a whole class of molecules), use placeholder names for the "
        f"generic molecules here too, like 'RDY + 4 H2 -> RDEt'; additional notes welcome)?",
        question_id="description"
    )
    set_property(reaction, "schema:description", description, namespace_collection)

    ask_reaction_participants(reaction, scope, None, namespace_collection, reaction_library, chemical_entity_library, todo_list, local_todo_list)
    ask_reaction_mechanism(reaction, scope, None, namespace_collection, reaction_library, chemical_entity_library, todo_list, local_todo_list, include_location_and_rate=False)

    add_entity(reaction_library, reaction)
    return reaction


# ---------------------------------------------------------------------------
# StoichiometricReaction - hlo:SeriesSpecific (specializes a Fixed reaction)
# ---------------------------------------------------------------------------

def create_series_reaction(fixed_reaction: dict, namespace_collection: dict, datagraph: dict, reaction_library: dict, chemical_entity_library: dict, todo_list: list, local_todo_list: list, resolution_cache: dict, evidence_known_cache: dict = None):
    """fixed_reaction lives in the reaction library - the new series reaction itself ends up
    in the datagraph."""
    scope = "hlo:SeriesSpecific"
    # The class of the fixed reaction - stoichiometric or lumped - holds on every level.
    reaction_type = check_type(overall_reaction_class(fixed_reaction) or "cpo:StoichiometricReaction", namespace_collection)
    entity_id = claim_id(make_library_based_id(fixed_reaction["@id"], scope), datagraph, todo_list, local_todo_list)
    reaction = {"@id": entity_id, "@type": [reaction_type, scope]}

    name = fixed_reaction.get("schema:name") or generate_name(entity_id)
    set_property(reaction, "schema:name", name, namespace_collection)
    print(f"\n=== Now describing Reaction \"{name}\" ({entity_id}, {scope}) ===")

    set_property(reaction, "hlo:specializationOf", fixed_reaction, namespace_collection)
    # Inverse direction only at an entity of the crate - the library is not changed (rule 2.2).
    if not is_library_entity(fixed_reaction):
        set_property(fixed_reaction, "hlo:hasSpecialization", reaction, namespace_collection, True)

    if "schema:description" in fixed_reaction:
        set_property(reaction, "schema:description", fixed_reaction["schema:description"], namespace_collection)

    specialize_reaction_participants_for_series(fixed_reaction, reaction, namespace_collection, datagraph, reaction_library, chemical_entity_library, todo_list, local_todo_list, resolution_cache, evidence_known_cache)
    _ask_reaction_location_and_rate(reaction, scope, 1, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache)
    link_reaction_transfers(reaction, scope, 1, namespace_collection, datagraph, reaction_library, chemical_entity_library, todo_list, local_todo_list, evidence_known_cache)
    specialize_reaction_mechanism_for_series(fixed_reaction, reaction, namespace_collection, datagraph, reaction_library, chemical_entity_library, todo_list, local_todo_list, resolution_cache, evidence_known_cache)

    add_entity(datagraph, reaction)
    return reaction


# ---------------------------------------------------------------------------
# StoichiometricReaction - hlo:ExperimentSpecific (takes over the series reaction 1:1)
# ---------------------------------------------------------------------------

def create_experiment_reaction(series_reaction: dict, nr: int, namespace_collection: dict, datagraph: dict, todo_list: list, local_todo_list: list, resolution_cache: dict, evidence_known_cache: dict = None):
    scope = "hlo:ExperimentSpecific"
    reaction_type = check_type(overall_reaction_class(series_reaction) or "cpo:StoichiometricReaction", namespace_collection)
    entity_id = claim_id(make_specialization_id(series_reaction["@id"], nr), datagraph, todo_list, local_todo_list)
    reaction = {"@id": entity_id, "@type": [reaction_type, scope]}

    name = series_reaction.get("schema:name") or generate_name(entity_id)
    set_property(reaction, "schema:name", name, namespace_collection)
    print(f"\n=== Now describing Reaction \"{name}\" ({entity_id}, {scope}, Experiment {nr}) ===")

    set_property(reaction, "hlo:specializationOf", series_reaction, namespace_collection)
    set_property(series_reaction, "hlo:hasSpecialization", reaction, namespace_collection, True)

    if "schema:description" in series_reaction:
        set_property(reaction, "schema:description", series_reaction["schema:description"], namespace_collection)

    # Participants get a counterpart per experiment (rule 3.9): yield, conversion
    # and selectivity differ per experiment (copy_reaction_participants). Species and roles are
    # not asked again. Place (mapped to the matching experiment phase/interface) and a fresh rate
    # are specific to the experiment as well.
    copy_reaction_participants(series_reaction, reaction, scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache)
    _copy_reaction_location_and_rate(series_reaction, reaction, scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache)
    copy_reaction_transfers(series_reaction, reaction, scope, nr, datagraph, namespace_collection)
    copy_reaction_mechanism(series_reaction, reaction, scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, resolution_cache, evidence_known_cache)

    # Whether the reaction actually takes place in this experiment is recorded via
    # cpo:hasOccurrence (only overall reactions - ElementaryReactions are hypotheses in
    # reference mechanisms, see the module docstring).
    add_occurrence(reaction, scope, nr, namespace_collection, datagraph, todo_list, local_todo_list, evidence_known_cache)

    add_entity(datagraph, reaction)
    return reaction


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def _absent_participants(series_reaction: dict, nr: int, datagraph: dict) -> list:
    """The fixed IDs of the participants of a series reaction that do not occur in experiment nr (absent_species)."""
    from creation.chemical_entity_functions import fixed_chemical_entity_id
    absent = absent_species(nr)
    missing = []
    for participant_id in ref_ids(series_reaction.get("cpo:hasParticipant")):
        participant = find_entity(datagraph, participant_id)
        for species_ref in as_list((participant or {}).get("dcterms:hasPart")):
            fixed_id = fixed_chemical_entity_id(species_ref, datagraph)
            if fixed_id in absent and fixed_id not in missing:
                missing.append(fixed_id)
    return missing


def complete_all_reactions(namespace_collection: dict, datagraph: dict, reaction_library: dict, chemical_entity_library: dict, todo_list: list, number_experiments: int) -> list:
    """First ask, at hlo:Fixed level, which of the reactions already held in the reaction
    library are relevant for this crate. The library itself is only read here and never
    changed - new fixed reactions are created separately through the reaction library script,
    see create_fixed_reaction.

    Then ask, at hlo:SeriesSpecific level, which of them actually occur in this series, with
    concrete species in place of the generic fixed placeholders, and create the
    hlo:ExperimentSpecific specializations for each automatically - without asking again,
    with only the location and hasReactionRate taken afresh.
    """
    local_todo_list = []
    evidence_known_cache = {}
    # ONE cache for the whole run of the crate, not per reaction: a placeholder that occurs in
    # several reactions has to become the same species everywhere (the RDEt of the
    # hydrogenation is the same RDEt the dimerisations consume).
    resolution_cache = new_resolution_cache()

    print("\n--- Reactions: Fixed level (reusable reaction library) ---")
    fixed_reactions = []
    existing = _all_fixed_reactions(reaction_library)
    if not existing:
        print("[hlo:Fixed] The reaction library is empty - no reactions to select from. Use the reaction library script to add some first.")
    else:
        # reset=True: the hlo:Fixed choice does NOT hang under "series:1", although it stands in
        # the middle of the otherwise "series:1"-wide flow of main.py (see there and
        # helpers/user_io.py: question_path). A list instead of "another one?" with a counter
        # (step 7, group B).
        with question_path("fixed", reset=True):
            chosen_ids = ask_entity_list("[hlo:Fixed] Which reactions from the library are relevant for this crate? Separated by ';' (leave empty if none)",
                                         existing, question_id="reactions")
        fixed_reactions = [find_entity(reaction_library, chosen_id) for chosen_id in chosen_ids]

    print("\n--- Reactions: Series level ---")
    # "reaction:<library key>" - the same key below in the experiment loop (series_reactions
    # carries it along), so that "reaction:X/reactionrate/..." means the same reaction in series
    # and experiment.
    series_reactions = []
    for fixed_reaction in fixed_reactions:
      reaction_index = key_name(fixed_reaction["@id"])
      with question_path("reaction", reaction_index):
        answer = ask_user(f"[hlo:SeriesSpecific] Does the reaction \"{get_display_label(fixed_reaction)}\" occur in this series?", ["Yes", "No"], question_id="occurs_in_series")
        if answer == "Yes":
            series_reaction = create_series_reaction(fixed_reaction, namespace_collection, datagraph, reaction_library, chemical_entity_library, todo_list, local_todo_list, resolution_cache, evidence_known_cache)
            series_reactions.append((reaction_index, series_reaction))

    for e in range(number_experiments):
        nr = e + 1
        with question_path("experiment", nr):
            print(f"\n--- Reactions: Experiment {nr} ---")
            for reaction_index, series_reaction in series_reactions:
                missing = _absent_participants(series_reaction, nr, datagraph)
                if missing:
                    # A participant does not occur in this experiment: neither does the reaction (rule 3.13).
                    print(f"[hlo:ExperimentSpecific] {get_display_label(series_reaction)} is left out of Experiment {nr}: "
                          f"{', '.join(missing)} not in it.")
                    continue
                with question_path("reaction", reaction_index):
                    create_experiment_reaction(series_reaction, nr, namespace_collection, datagraph, todo_list, local_todo_list, resolution_cache, evidence_known_cache)

    return local_todo_list
