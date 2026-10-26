"""
Stand-alone, read-only check script for the library files (libraries/*.jsonld): finds dead
references (pointers to IDs that exist nowhere), IDs handed out twice, and - best effort -
entries that nothing references. Changes no files, a plain report on the console.

Also checks rule 4.1 (docs/rules_crate.md): no value on an Actual, every Evidence/Reference
has its determination task in both directions, and every ID follows the value scheme
<variable>_<Evidence|Reference>_<n>.

Also checks rule 6.6: no library entity carries a context link (hlo:describesContext,
hlo:contextDescribedBy) - the crate links its contexts from the shapes (helpers/context_links.py).

Also checks the balance of atoms and charge of every stoichiometric reaction, in the libraries and
- with the generic species resolved - in the crates (SeriesSpecific). A reaction whose species
have no molecular formula (Placeholder) is listed as not checkable, not as a problem.

Also checks rule 3b.2 in the crates: an interface between two phases without any transfer has an
inert phase - otherwise the generator forgot its potential transfers (two solids
exchange as well, cpo:SolidExchange).

Also checks the containers of the inventory: content, lot, an occurrence of the content
with a start - since when it is in the lab -, the delivery time as that start, cabinet and room.

Also checks that devices and contents stand apart - every device (also a
container of the inventory), template and body material in the device library, every content of a
device with what describes it in the material library -, and the contents of each device:
cpo:hasContainedMaterialHistory lists all, cpo:containsMaterial and cpo:materialContainedIn only the
current one (rule 2.15).

Also checks: every usage history of a device starts with a commissioning
(rule 5.5), every CAS number has a valid check digit (rule 2.8), and no crate has an ID of the old
form "#..." or a copied library entry other than the ontology snapshot (rules 1.2, 2.1).

Also checks the units and quantity kinds (libraries/units_and_quantity_kinds.json and the
quantity kinds the ontology names) against the QUDT version the ontology library names - see
helpers/qudt_check.py. That part downloads QUDT once into a local cache.

Errors of this kind currently go unnoticed, because main.py only reads the libraries and
never validates them (see the dead #Molecule_0009_Fixed reference in
reaction_library.jsonld, for example).

Execute (from the repository root): python generator/workflow/check_library_consistency.py
"""

import re
import sys
from pathlib import Path

# Runs from generator/workflow/ - the generator has to be on the search path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import path_definitions  # noqa: E402
from helpers.entities import collect_prefixes, as_list
from helpers.file_handling import load_jsonld, PROJECT_CONTEXT
from helpers.todo_functions import load_todo_list
from helpers.qudt_check import check_units_against_qudt
from interfaces.pubchem.pubchem_lookup import _cas_valid


LIBRARY_FILES = {
    "device_library.jsonld": path_definitions.DEVICE_LIBRARY_PATH,
    "material_library.jsonld": path_definitions.MATERIAL_LIBRARY_PATH,
    "people_library.jsonld": path_definitions.PEOPLE_LIBRARY_PATH,
    "organization_library.jsonld": path_definitions.ORGANIZATION_LIBRARY_PATH,
    "software_library.jsonld": path_definitions.SOFTWARE_LIBRARY_PATH,
    "reaction_library.jsonld": path_definitions.REACTION_LIBRARY_PATH,
    "chemical_entity_library.jsonld": path_definitions.CHEMICAL_ENTITY_LIBRARY_PATH,
    "assumption_library.jsonld": path_definitions.ASSUMPTION_LIBRARY_PATH,
    "ontology_library.jsonld": path_definitions.ONTOLOGY_LIBRARY_PATH,
}

# Namespace prefixes that point at an ontology/external vocabulary (classes, properties,
# QuantityKinds, units, ChEBI classes, ...) instead of at an entity in our own libraries/the
# data graph - the same prefixes stand in practically every @context block of the project
# (see libraries/*.jsonld). References with these prefixes are resolved by the ontology
# itself, not checked by this script. Under "chebi:" there is only real ChEBI vocabulary: every
# chemical entity of the libraries stands under "chem:" in the chemical_entity_library, so that
# references to it are checked.
VOCABULARY_PREFIXES = {
    "hlo", "cpo", "chebi", "qudt", "quantitykind", "unit",
    "xsd", "time", "rdf", "rdfs", "owl", "schema", "sosa", "dcterms",
}


def _entities(graph_data):
    """The @graph list out of a load_jsonld result - or the list itself, for the todo list,
    which has no @graph wrapper."""
    if isinstance(graph_data, dict):
        return graph_data.get("@graph", [])
    return graph_data


def _collect_references(value, found: list):
    """Walk recursively through a property value and collect every {'@id': ...} reference.

    A typed literal ({'@value': ..., '@type': ...}, see set_literal_property in
    helpers/properties.py) carries no '@id' and is therefore correctly skipped.
    """
    if isinstance(value, dict):
        if "@id" in value:
            found.append(value["@id"])
        else:
            for v in value.values():
                _collect_references(v, found)
    elif isinstance(value, list):
        for item in value:
            _collect_references(item, found)


def _is_checkable(ref_id: str) -> bool:
    """Check only references that are meant to point at one of our own library or data
    graph entities - IDs in the "#fragment" style, or with a prefix outside
    VOCABULARY_PREFIXES ("chem:", "device:", "person:", "organization:", ...).

    Plain string values such as "unit:SEC" (see helpers/evidence_reference.py) never turn up
    here anyway, because _collect_references only gathers dict values carrying an '@id'.
    """
    if ref_id.startswith("#"):
        return True
    prefix = ref_id.split(":", 1)[0] if ":" in ref_id else None
    return prefix is not None and prefix not in VOCABULARY_PREFIXES


# hlo:hasSpecialization is deliberately excluded for a Fixed entity: by convention it points
# FORWARD there at a series/experiment ID that is made only in the actual main.py run
# (deterministically from the same name, see generate_id/generate_id_from_name) - that is
# intended, not a dead reference. hlo:specializationOf (the inverse direction), however,
# points at something that MUST exist already, and is therefore checked as usual.
SKIPPED_PROPERTIES = {"hlo:hasSpecialization"}


def _undeclared_prefixes(data: dict) -> list:
    """Prefixes a library uses without declaring them in its own @context.

    Such a prefix is NOT a typo that shows - for every RDF parser it stays
    an opaque IRI, and the entity it points at is thus a different one
    from the same entity in a file that declares the prefix properly - a phase then has two
    hasPart members through its two versions, one of them without a type. This check catches
    that at once.
    """
    used = collect_prefixes(data.get("@graph", []))
    return sorted(used - set(data.get("@context", {})))


def _namespace_disagreements(libraries: dict) -> list:
    """Prefixes whose namespace does not have the same value everywhere.

    Three tables are compared that must say the same:

      - PROJECT_CONTEXT (libraries/project_context.jsonld) - the @context of the crate made,
      - the @context block of every single library file,
      - cpo:hasNamespace in libraries/ontology_library.jsonld - i.e. what the ontology
        snapshot CLAIMS about the vocabulary.

    That nobody compared them was the cause of two wrong entries: the snapshot
    documented schema: as https://schema.org/, while the crate resolves via the
    RO-Crate 1.3 context to http://schema.org/ (measured: 781 triples under http,
    0 under https), and org: as https://www.w3.org/ns/org#, although the W3C specification
    itself uses http. A wrong namespace otherwise shows nowhere - it makes
    no error, it makes a different statement.

    Returns a list of (prefix, {namespace: [sources]}).
    """
    seen = {}

    def note(prefix, namespace, source):
        if isinstance(namespace, str):
            seen.setdefault(prefix, {}).setdefault(namespace, []).append(source)

    for prefix, namespace in PROJECT_CONTEXT.items():
        note(prefix, namespace, "PROJECT_CONTEXT")

    for name, data in libraries.items():
        for prefix, namespace in (data.get("@context") or {}).items():
            note(prefix, namespace, f"{name} @context")

    for entity in _entities(libraries.get("ontology_library.jsonld", {})):
        prefix = entity.get("cpo:hasOntologyPrefix")
        if prefix:
            note(prefix, entity.get("cpo:hasNamespace"), f"{entity['@id']} cpo:hasNamespace")

    return [(prefix, namespaces) for prefix, namespaces in sorted(seen.items()) if len(namespaces) > 1]


def _ref_ids(value) -> list:
    """The @id strings of a property value (single reference or list of references)."""
    values = value if isinstance(value, list) else [value]
    return [v["@id"] for v in values if isinstance(v, dict) and "@id" in v]


def _types(entity: dict) -> list:
    return as_list(entity.get("@type"))


_LEVEL_SUFFIX = re.compile(r"_(Fixed|SeriesSpecific|ExperimentSpecific(_[0-9]+)?)$")


def _rule_4_1_problems(libraries: dict) -> dict:
    """Rule 4.1 (docs/rules_crate.md) in the libraries: every value sits on an Evidence or a
    Reference, never on the Actual, and every Evidence/Reference has its determination task,
    linked in both directions, and hangs at exactly one variable (hlo:hasEvidence /
    hlo:hasReference). Its ID follows the value scheme <variable>_<Evidence|Reference>_<n>, a
    level suffix of the variable moved to the end (make_member_id in helpers/identifiers.py).

    Returns {problem kind: [(library, entity id, detail), ...]}; every list empty means no finding.
    """
    # The check for dead references does not catch a value without a task - a MISSING task is no
    # reference it could see.
    entities = {}
    for name, data in libraries.items():
        for entity in _entities(data):
            if entity.get("@id"):
                entities[entity["@id"]] = (name, entity)

    problems = {
        "value on an Actual": [],
        "without cpo:hasDeterminationTask": [],
        "determination task missing": [],
        "task does not name the value in cpo:determines": [],
        "value does not name the task in cpo:hasDeterminationTask": [],
        "without hlo:hasEvidenceType/hlo:hasReferenceType": [],
        "not attached to exactly one variable": [],
        "ID does not follow <variable>_<Evidence|Reference>_<n>": [],
    }

    # Who owns a value? The variable that holds it in hlo:hasEvidence/hlo:hasReference - its ID
    # is formed from that too, as in the crate - not from the type, so that the ID does not change
    # with a correction of the type.
    owners = {}
    for owner_id, (_, owner) in entities.items():
        for prop, role in (("hlo:hasEvidence", "Evidence"), ("hlo:hasReference", "Reference")):
            for value_id in _ref_ids(owner.get(prop)):
                owners.setdefault(value_id, []).append((owner_id, role))
    for entity_id, (name, entity) in entities.items():
        types = _types(entity)

        if "hlo:Actual" in types and "qudt:value" in entity:
            problems["value on an Actual"].append((name, entity_id, ""))

        # Inverse direction: every task that names a library value must stand there too.
        # Targets outside the libraries are checked by the section "Dangling references".
        for value_id in _ref_ids(entity.get("cpo:determines")):
            if value_id in entities and entity_id not in _ref_ids(entities[value_id][1].get("cpo:hasDeterminationTask")):
                problems["value does not name the task in cpo:hasDeterminationTask"].append((entities[value_id][0], value_id, entity_id))

        if "hlo:Evidence" not in types and "hlo:Reference" not in types:
            continue

        task_ids = _ref_ids(entity.get("cpo:hasDeterminationTask"))
        if not task_ids:
            problems["without cpo:hasDeterminationTask"].append((name, entity_id, ""))
        for task_id in task_ids:
            if task_id not in entities:
                problems["determination task missing"].append((name, entity_id, task_id))
            elif entity_id not in _ref_ids(entities[task_id][1].get("cpo:determines")):
                problems["task does not name the value in cpo:determines"].append((name, entity_id, task_id))

        kinds = _ref_ids(entity.get("hlo:hasEvidenceType")) + _ref_ids(entity.get("hlo:hasReferenceType"))
        if not kinds:
            problems["without hlo:hasEvidenceType/hlo:hasReferenceType"].append((name, entity_id, ""))

        found = owners.get(entity_id, [])
        if len(found) != 1:
            problems["not attached to exactly one variable"].append((name, entity_id, ", ".join(o for o, _ in found)))
            continue
        owner_id, role = found[0]
        level = _LEVEL_SUFFIX.search(owner_id)
        base, level_suffix = (owner_id[:level.start()], level.group(0)) if level else (owner_id, "")
        if not re.fullmatch(re.escape(base) + f"_{role}_[1-9][0-9]*" + re.escape(level_suffix), entity_id):
            problems["ID does not follow <variable>_<Evidence|Reference>_<n>"].append(
                (name, entity_id, f"expected {base}_{role}_<n>{level_suffix}"))

    return problems


CONTEXT_LINK_PROPERTIES = ("hlo:describesContext", "hlo:contextDescribedBy")


def _layer_problems(libraries: dict) -> dict:
    """Rule 3.8a in the libraries: the layers of a device wall. A device defines its body form,
    the layers hang at that form through cpo:hasLayerForm (never at a part), each cpo:LayerForm
    carries its thickness and its coverage; a body material of several phases has exactly one
    core that fills the body form, every other phase fills one of the layer forms, no phase
    defines a form of its own; cpo:hasInnerLayer names a phase of that material.

    Returns {problem kind: [(library, entity id, detail), ...]}; every list empty means no finding.
    """
    entities = {}
    for name, data in libraries.items():
        for entity in _entities(data):
            if entity.get("@id"):
                entities[entity["@id"]] = (name, entity)

    problems = {
        "layer form not reached from a device's body form": [],
        "cpo:hasLayerForm on a form no device defines": [],
        "layer form without thickness": [],
        "layer form without coverage": [],
        "layer phase defines a form of its own": [],
        "not exactly one phase fills the body form": [],
        "phase fills no layer form of its device": [],
        "cpo:hasInnerLayer is not a phase of the material": [],
    }
    body_forms = {}      # body form -> device
    for entity_id, (name, entity) in entities.items():
        for form_id in _ref_ids(entity.get("cpo:definesForm")):
            if entity_id.startswith("device:"):
                body_forms[form_id] = entity_id
    reached = set()
    for entity_id, (name, entity) in entities.items():
        layers = _ref_ids(entity.get("cpo:hasLayerForm"))
        if layers and entity_id not in body_forms:
            problems["cpo:hasLayerForm on a form no device defines"].append((name, entity_id, ""))
        reached.update(layers)
    for entity_id, (name, entity) in entities.items():
        if "cpo:LayerForm" not in _types(entity):
            continue
        if entity_id not in reached:
            problems["layer form not reached from a device's body form"].append((name, entity_id, ""))
        if not entity.get("cpo:hasWallThickness"):
            problems["layer form without thickness"].append((name, entity_id, ""))
        if not entity.get("cpo:hasLayerCoverage"):
            problems["layer form without coverage"].append((name, entity_id, ""))

    for entity_id, (name, entity) in entities.items():
        if "cpo:BodyMaterial" not in _types(entity):
            continue
        phases = _ref_ids(entity.get("dcterms:hasPart"))
        inner = _ref_ids(entity.get("cpo:hasInnerLayer"))
        for inner_id in inner:
            if inner_id not in phases:
                problems["cpo:hasInnerLayer is not a phase of the material"].append((name, entity_id, inner_id))
        if len(phases) < 2:
            continue
        device_id = next(iter(_ref_ids(entity.get("cpo:isBodyMaterialOf"))), None)
        device = entities.get(device_id, (None, {}))[1]
        device_forms = _ref_ids(device.get("cpo:definesForm"))
        layer_forms = {layer for form_id in device_forms
                       for layer in _ref_ids(entities.get(form_id, (None, {}))[1].get("cpo:hasLayerForm"))}
        cores = []
        for phase_id in phases:
            phase = entities.get(phase_id, (None, {}))[1]
            if phase.get("cpo:definesForm"):
                problems["layer phase defines a form of its own"].append((name, phase_id, ""))
            fills = _ref_ids(phase.get("cpo:fillsForm"))
            if any(f in device_forms for f in fills):
                cores.append(phase_id)
            elif not any(f in layer_forms for f in fills):
                problems["phase fills no layer form of its device"].append((name, phase_id, ", ".join(fills) or "fills nothing"))
        if len(cores) != 1:
            problems["not exactly one phase fills the body form"].append((name, entity_id, f"{len(cores)} found"))
    return problems


def _context_links(libraries: dict) -> list:
    """(library, entity ID, property) for every context link in a library (rule 6.6) - also in
    nested objects."""
    found = []

    def visit(node, owner, name):
        if isinstance(node, dict):
            owner = node.get("@id", owner)
            for prop in CONTEXT_LINK_PROPERTIES:
                if prop in node:
                    found.append((name, owner, prop))
            for value in node.values():
                visit(value, owner, name)
        elif isinstance(node, list):
            for value in node:
                visit(value, owner, name)

    for name, data in libraries.items():
        visit(data.get("@graph", []), None, name)
    return found


_FORMULA = re.compile(r"((?:[A-Z][a-z]?\d*)+)([+-]\d*)?")


def formula_counts(formula: str):
    """Atoms and charge ("charge") of a molecular formula such as C6H16N+ or F6P-; None when the
    text is not a plain formula."""
    match = _FORMULA.fullmatch(formula or "")
    if not match:
        return None
    counts = {}
    for element, number in re.findall(r"([A-Z][a-z]?)(\d*)", match.group(1)):
        counts[element] = counts.get(element, 0) + int(number or 1)
    if match.group(2):
        sign, number = match.group(2)[0], match.group(2)[1:]
        counts["charge"] = (1 if sign == "+" else -1) * int(number or 1)
    return counts


def _reaction_balance(libraries: dict, crates: dict):
    """Atoms and charge of every stoichiometric reaction: in the libraries (Fixed) and, where the
    generic species are resolved, in the crates (SeriesSpecific; the ExperimentSpecific ones repeat
    them). A participant's coefficient is inherited along hlo:specializationOf, its species is
    followed along hlo:specializationOf to the entry with cpo:hasMolecularFormula. Returns
    (unbalanced, not checkable) - a reaction with a Placeholder or a species without formula
    cannot be checked, which is expected for a generic reaction template. A cpo:LumpedReaction
    has no equation by definition: it is reported only if a participant
    carries a stoichiometric coefficient after all."""
    by_id = {e["@id"]: e for data in list(libraries.values()) + list(crates.values())
             for e in _entities(data) if "@id" in e}

    def along(entity_id, prop):
        seen = set()
        while entity_id in by_id and entity_id not in seen:
            seen.add(entity_id)
            entity = by_id[entity_id]
            if prop in entity:
                return entity[prop], entity_id
            parents = _ref_ids(entity.get("hlo:specializationOf"))
            entity_id = parents[0] if parents else None
        return None, entity_id

    unbalanced, unchecked = [], []
    sources = [(name, data) for name, data in {**libraries, **crates}.items()]
    for source_name, data in sources:
        for reaction in _entities(data):
            types = _types(reaction)
            if "cpo:LumpedReaction" in types and ({"hlo:Fixed", "hlo:SeriesSpecific"} & set(types)):
                # No equation, so nothing to balance - but a coefficient would be a contradiction.
                with_coefficient = [p for p in _ref_ids(reaction.get("cpo:hasParticipant"))
                                    if along(p, "cpo:hasStoichiometricCoefficient")[0] is not None]
                if with_coefficient:
                    unbalanced.append(f"{source_name}: {reaction['@id']} ({reaction.get('schema:name', '')}) - a lumped "
                                      f"reaction with stoichiometric coefficients: {', '.join(with_coefficient)}")
                continue
            if "cpo:StoichiometricReaction" not in types or not ({"hlo:Fixed", "hlo:SeriesSpecific"} & set(types)):
                continue
            total, missing = {}, []
            for participant_id in _ref_ids(reaction.get("cpo:hasParticipant")):
                coefficient, _ = along(participant_id, "cpo:hasStoichiometricCoefficient")
                species = (_ref_ids(by_id.get(participant_id, {}).get("dcterms:hasPart")) or [None])[0]
                formula, owner = along(species, "cpo:hasMolecularFormula")
                counts = formula_counts(formula) if formula else None
                if coefficient is None or counts is None:
                    missing.append(species if coefficient is not None else f"{participant_id} (no coefficient)")
                    continue
                for element, number in counts.items():
                    total[element] = total.get(element, 0) + float(coefficient) * number
            label = f"{source_name}: {reaction['@id']} ({reaction.get('schema:name', '')})"
            if missing:
                unchecked.append(f"{label} - no molecular formula for {', '.join(str(m) for m in missing)}")
                continue
            off = {element: round(number, 6) for element, number in total.items() if abs(number) > 1e-9}
            if off:
                unbalanced.append(f"{label} - left over (negative = missing on the product side): {off}")
    return unbalanced, unchecked


def _solvent_problems(sources: dict) -> list:
    """Rule 3.12: cpo:hasSolvent names one of the phase's own species - every value is also a
    dcterms:hasPart of the same phase - and only a liquid phase has a solvent. Checked in the
    libraries and in the crates (the generator writes both properties; a hand-made library entry
    could forget one). Returns [(source, phase id, detail), ...]."""
    problems = []
    for name, data in sources.items():
        for entity in _entities(data):
            solvents = _ref_ids(entity.get("cpo:hasSolvent"))
            if not solvents:
                continue
            if "cpo:LiquidPhase" not in _types(entity):
                problems.append((name, entity.get("@id"), "not a cpo:LiquidPhase"))
            missing = [s for s in solvents if s not in _ref_ids(entity.get("dcterms:hasPart"))]
            if missing:
                problems.append((name, entity.get("@id"), "not a dcterms:hasPart of the phase: " + ", ".join(missing)))
    return problems


def _container_problems(libraries: dict) -> list:
    """The containers of the inventory (cpo:ChemicalContainer, not a template): a content that
    points back to its
    container; a lot (cpo:hasLotNumber, Phase_Information_R2); a content phase with an occurrence
    whose start has a value - since when the content exists in the lab (Phase_Time_R1); a
    delivery time, where stated, that is the same time:Instant as that start; a cabinet the
    container stands in, and a room the cabinet stands in. Opening and expiry are optional
    (Phase_Time_R5/R6). Returns [(library, container id, detail), ...]."""
    by_id = {e.get("@id"): e for data in libraries.values() for e in _entities(data)}

    def has_value(instant_id):
        instant = by_id.get(instant_id) or {}
        return bool(instant.get("hlo:hasEvidence") or instant.get("hlo:hasReference"))

    problems = []
    for name, data in libraries.items():
        for container in _entities(data):
            types = _types(container)
            if "cpo:ChemicalContainer" not in types or "hlo:Template" in types:
                continue
            cid = container.get("@id")
            # Every content the container ever had (rule 2.15) - an empty container has no current
            # one; whether only the current one points back is checked by _content_history_problems.
            history = _ref_ids(container.get("cpo:hasContainedMaterialHistory")) or _ref_ids(container.get("cpo:containsMaterial"))
            materials = [by_id.get(m) for m in history]
            if not materials or None in materials:
                problems.append((name, cid, "no content (cpo:hasContainedMaterialHistory) in the libraries"))
                continue
            starts = []
            for material in materials:
                if not material.get("cpo:hasLotNumber"):
                    problems.append((name, cid, f"{material['@id']} has no lot (cpo:hasLotNumber)"))
                for phase_id in _ref_ids(material.get("dcterms:hasPart")):
                    for occurrence_id in _ref_ids((by_id.get(phase_id) or {}).get("cpo:hasOccurrence")):
                        starts += _ref_ids((by_id.get(occurrence_id) or {}).get("cpo:hasStartTime"))
            if not starts:
                problems.append((name, cid, "no content phase with an occurrence and a start time - since when is the content in the lab?"))
            elif not any(has_value(s) for s in starts):
                problems.append((name, cid, "the start of the content's occurrence has no evidence or reference"))
            for delivery in _ref_ids(container.get("cpo:hasDeliveryTime")):
                if delivery not in starts[:1]:
                    problems.append((name, cid, f"delivery time {delivery} is not the start of the first content's occurrence"))
            for prop in ("cpo:hasOpeningTime", "cpo:hasDeliveryTime"):
                for instant in _ref_ids(container.get(prop)):
                    if not has_value(instant):
                        problems.append((name, cid, f"{prop} {instant} has no evidence or reference"))
            cabinets = [by_id.get(c) for c in _ref_ids(container.get("cpo:locatedInsideOf"))]
            if not cabinets or None in cabinets:
                problems.append((name, cid, "not located inside a cabinet of the libraries"))
            elif not all(_ref_ids(c.get("cpo:locatedInsideOf")) for c in cabinets):
                problems.append((name, cid, "its cabinet is not located inside a room"))
    return problems


_STATES = ("cpo:SolidPhase", "cpo:LiquidPhase", "cpo:GasPhase")


def _interfaces_without_transfers(libraries: dict, crates: dict) -> list:
    """Rule 3b.2: a series interface between two phases without any potential transfer must be one
    the model leaves out - one of the phases inert (only species with cpo:isInert in the Chemical
    Entity Library). Two solids are not left out (cpo:SolidExchange). Anything else
    means the generator forgot its transfers. The state and the species are followed along
    hlo:specializationOf. Returns [(crate, interface, detail), ...]."""
    by_id = {e["@id"]: e for data in list(libraries.values()) + list(crates.values())
             for e in _entities(data) if "@id" in e}

    def chain(entity_id):
        seen = set()
        while entity_id in by_id and entity_id not in seen:
            seen.add(entity_id)
            yield by_id[entity_id]
            parents = _ref_ids(by_id[entity_id].get("hlo:specializationOf"))
            entity_id = parents[0] if parents else None

    def state(phase_id):
        return next((t for entity in chain(phase_id) for t in _types(entity) if t in _STATES), None)

    def inert(phase_id):
        species = _ref_ids(by_id.get(phase_id, {}).get("dcterms:hasPart"))
        return bool(species) and all(any(e.get("cpo:isInert") in (True, "true") for e in chain(s)) for s in species)

    problems = []
    for name, data in crates.items():
        entities = _entities(data)
        with_transfers = {ref for e in entities if "cpo:Transfer" in _types(e) for ref in _ref_ids(e.get("cpo:occursAtInterface"))}
        for interface in entities:
            types = _types(interface)
            if "cpo:PhasePairInterface" not in types or "hlo:SeriesSpecific" not in types or interface["@id"] in with_transfers:
                continue
            phases = _ref_ids(interface.get("cpo:separatesPhases"))
            states = [state(p) for p in phases]
            if any(inert(p) for p in phases):
                continue
            problems.append((name, interface["@id"], "states " + " / ".join(str(s) for s in states) + ", no inert phase"))
    return problems


def _device_classes() -> set:
    """cpo:Device and all its subclasses in the CPO, as "cpo:<name>"."""
    import rdflib
    graph = rdflib.Graph()
    graph.parse(str(path_definitions.CPO_ONTOLOGY))
    namespace = rdflib.Namespace(PROJECT_CONTEXT["cpo"])
    found, todo = {rdflib.URIRef(namespace + "Device")}, [rdflib.URIRef(namespace + "Device")]
    while todo:
        for sub in graph.subjects(rdflib.RDFS.subClassOf, todo.pop()):
            if isinstance(sub, rdflib.URIRef) and sub not in found:
                found.add(sub)
                todo.append(sub)
    return {"cpo:" + str(c)[len(namespace):] for c in found if str(c).startswith(str(namespace))}


def _joint_problems(libraries: dict) -> list:
    """cpo:isConnectedTo: two joined ports name each other - the generator reads
    the property on the port it is at, without a reasoner - and belong to two different devices.
    Returns [(library, id, detail)]."""
    by_id = {e.get("@id"): e for data in libraries.values() for e in _entities(data)}
    problems = []
    for name, data in libraries.items():
        for entity in _entities(data):
            for other_id in _ref_ids(entity.get("cpo:isConnectedTo")):
                other = by_id.get(other_id)
                if other is None:
                    continue    # reported already by the check for dead references
                if entity.get("@id") not in _ref_ids(other.get("cpo:isConnectedTo")):
                    problems.append((name, entity.get("@id"), f"{other_id} does not name it back (cpo:isConnectedTo)"))
                if _ref_ids(entity.get("cpo:isPortOf")) == _ref_ids(other.get("cpo:isPortOf")):
                    problems.append((name, entity.get("@id"), f"joined to {other_id} of the same device"))
    return problems


def _placement_problems(libraries: dict) -> list:
    """Devices and contents apart: the material library holds no device, port, template or
    body material; the device library no content of a device (a material a device names with
    cpo:containsMaterial or cpo:hasContainedMaterialHistory, or that names its device with
    cpo:materialContainedIn) and no part of one (dcterms:isPartOf, e.g. its phase).
    Returns [(library, id, detail)]."""
    devices = _device_classes()
    contents = set()
    for data in libraries.values():
        for entity in _entities(data):
            if set(_types(entity)) & devices:
                contents.update(_ref_ids(entity.get("cpo:containsMaterial")))
                contents.update(_ref_ids(entity.get("cpo:hasContainedMaterialHistory")))
            elif entity.get("cpo:materialContainedIn") and "cpo:BodyMaterial" not in _types(entity):
                contents.add(entity.get("@id"))
    problems = []
    for entity in _entities(libraries.get("material_library.jsonld", {})):
        types = set(_types(entity))
        if types & devices or entity.get("@id", "").startswith(("device:", "port:")):
            problems.append(("material_library.jsonld", entity.get("@id"), "a device or port - belongs in the device library"))
        elif types & {"hlo:Template", "cpo:BodyMaterial"}:
            problems.append(("material_library.jsonld", entity.get("@id"), "a template or body material - belongs in the device library"))
    for entity in _entities(libraries.get("device_library.jsonld", {})):
        if entity.get("@id") in contents:
            problems.append(("device_library.jsonld", entity.get("@id"), "the content of a device - belongs in the material library"))
        elif set(_ref_ids(entity.get("dcterms:isPartOf"))) & contents:
            problems.append(("device_library.jsonld", entity.get("@id"), "part of the content of a device - belongs in the material library"))
    return problems


def _content_history_problems(libraries: dict) -> list:
    """The contents of a device: a device with a content lists every content it has held in
    cpo:hasContainedMaterialHistory; cpo:containsMaterial is the last of them - the one in it now - or
    none (empty); only the current content points back (cpo:materialContainedIn), an earlier one no
    longer says where it was. Returns [(library, id, detail)]."""
    by_id = {e.get("@id"): e for data in libraries.values() for e in _entities(data)}
    devices = _device_classes()

    def occurrence(content_id):
        for phase_id in _ref_ids((by_id.get(content_id) or {}).get("dcterms:hasPart")):
            for occurrence_id in _ref_ids((by_id.get(phase_id) or {}).get("cpo:hasOccurrence")):
                found = by_id.get(occurrence_id)
                if found is not None and "hlo:Fixed" in _types(found):
                    return found
        return None

    def moment(instant_id):
        # The value of a point in time (evidence, otherwise reference) as text - ISO times compare as text.
        instant = by_id.get(instant_id) or {}
        for source_id in _ref_ids(instant.get("hlo:hasEvidence")) + _ref_ids(instant.get("hlo:hasReference")):
            raw = (by_id.get(source_id) or {}).get("rdf:value")
            raw = raw.get("@value") if isinstance(raw, dict) else raw
            if raw:
                return str(raw)
        return None

    def ended(found):
        end = _ref_ids(found.get("cpo:hasEndTime")) if found else []
        return end and end[0] != f"{found['@id']}_EndTime"

    problems = []
    for name, data in libraries.items():
        for entity in _entities(data):
            if not set(_types(entity)) & devices:
                continue
            did = entity.get("@id")
            current = _ref_ids(entity.get("cpo:containsMaterial"))
            history = _ref_ids(entity.get("cpo:hasContainedMaterialHistory"))
            if not current and not history:
                continue
            if current and not history:
                problems.append((name, did, "a content but no cpo:hasContainedMaterialHistory"))
                continue
            if len(current) > 1:
                problems.append((name, did, f"more than one current content: {', '.join(current)}"))
            if current and current[-1] != history[-1]:
                problems.append((name, did, f"the current content {current[-1]} is not the last of the history"))
            for content_id in history:
                content = by_id.get(content_id)
                if content is None:
                    continue    # reported already by the check for dead references
                points_back = did in _ref_ids(content.get("cpo:materialContainedIn"))
                if content_id in current and not points_back:
                    problems.append((name, did, f"{content_id} does not point back (cpo:materialContainedIn)"))
                elif content_id not in current and points_back:
                    problems.append((name, did, f"{content_id} is no longer in it but still points back (cpo:materialContainedIn)"))
            # One after the other: every earlier content has ended before the next comes; the current one has not.
            for content_id in current:
                if ended(occurrence(content_id)):
                    problems.append((name, did, f"the current content {content_id} has ended - the device should no longer contain it"))
            for earlier, later in zip(history, history[1:]):
                before, after = occurrence(earlier), occurrence(later)
                if before is None or after is None:
                    continue
                if not ended(before):
                    problems.append((name, did, f"{earlier} has not ended, but {later} came after it"))
                    continue
                end, start = moment(_ref_ids(before.get("cpo:hasEndTime"))[0]), moment((_ref_ids(after.get("cpo:hasStartTime")) or [None])[0])
                if end and start and start < end:
                    problems.append((name, did, f"{later} came in ({start}) before {earlier} ended ({end})"))
    return problems


def _usage_history_problems(libraries: dict) -> list:
    """Rule 5.5: a device of the libraries (an exemplar, not a template) has a usage history whose first
    entry is a cpo:CommissioningTask - unpacking, setting up, delivering. Single-use templates and their
    specimens have none (cpo:isSingleUse, read through hlo:specializationOf). Returns [(library, id, detail)]."""
    by_id = {e.get("@id"): e for data in libraries.values() for e in _entities(data)}
    devices = _device_classes()

    def single_use(entity):
        seen = set()
        while entity and entity.get("@id") not in seen:
            seen.add(entity.get("@id"))
            if entity.get("cpo:isSingleUse") in (True, "true"):
                return True
            parents = _ref_ids(entity.get("hlo:specializationOf"))
            entity = by_id.get(parents[0]) if parents else None
        return False

    problems = []
    for name, data in libraries.items():
        for entity in _entities(data):
            types = _types(entity)
            if not set(types) & devices or "hlo:Template" in types or single_use(entity):
                continue
            history = _ref_ids(entity.get("cpo:hasUsageHistory"))
            if not history:
                problems.append((name, entity.get("@id"), "no usage history (cpo:hasUsageHistory)"))
            elif "cpo:CommissioningTask" not in _types(by_id.get(history[0]) or {}):
                problems.append((name, entity.get("@id"), f"the first entry {history[0]} is no cpo:CommissioningTask"))
    return problems


def _cas_problems(libraries: dict) -> list:
    """Rule 2.8: a CAS number in its standard format with a valid check digit (hlo:ChemicalEntity_Format_Shape
    checks the format alone). Returns [(library, id, number)]."""
    problems = []
    for name, data in libraries.items():
        for entity in _entities(data):
            numbers = entity.get("cpo:hasCAS")
            for number in (numbers if isinstance(numbers, list) else [numbers]):
                if number is None:
                    continue
                if not re.fullmatch(r"\d{2,7}-\d{2}-\d", str(number)) or not _cas_valid(str(number)):
                    problems.append((name, entity.get("@id"), str(number)))
    return problems


def _crate_id_problems(libraries: dict, crates: dict) -> list:
    """Rules 1.2 and 2.1: a crate has no ID of the old form "#..." (all are crate:<crate_identifier>/...), and it
    links the libraries instead of copying them - the only library entries in a crate are those of the
    ontology snapshot (ontology:). Returns [(crate, id, detail)]."""
    library_prefixes = {e["@id"].split(":", 1)[0] for data in libraries.values() for e in _entities(data)
                        if ":" in e.get("@id", "")} - {"ontology", "crate"}
    problems = []
    for name, data in crates.items():
        for entity in _entities(data):
            entity_id = entity.get("@id", "")
            if entity_id.startswith("#"):
                problems.append((name, entity_id, "an ID of the old form (rule 1.2)"))
            elif ":" in entity_id and entity_id.split(":", 1)[0] in library_prefixes:
                problems.append((name, entity_id, "a library entry copied into the crate (rule 2.1)"))
    return problems


def _entity_references(entity: dict) -> list:
    refs = []
    for prop, value in entity.items():
        if prop == "@id" or prop in SKIPPED_PROPERTIES:
            continue
        _collect_references(value, refs)
    return refs


def main():
    libraries = {name: load_jsonld(path) for name, path in LIBRARY_FILES.items()}

    # Load the data graph of the last main.py run in addition - ONLY to know which IDs exist
    # there already (in case a library exceptionally points there); it is NOT checked for
    # outgoing references itself (task: "runs over all library files").
    # All crates, open and completed, with their to-do lists (projects/<crate_identifier>/).
    datagraph_sources = {}
    for crate in path_definitions.open_crate_paths() + path_definitions.archived_crate_paths():
        name = crate.relative_to(path_definitions.BASE_FOLDER).as_posix()
        datagraph_sources[name] = load_jsonld(crate)
        todo = crate.parent / path_definitions.TODO_FILE_NAME
        if todo.exists():
            datagraph_sources[todo.relative_to(path_definitions.BASE_FOLDER).as_posix()] = load_todo_list(todo)

    # 1) Where does every @id occur as an entity of its own?
    # For the existence check the data graph counts too (libraries may point there). For the
    # duplicate check it does NOT: main.py copies every Fixed entity used from the libraries
    # into the data graph when it creates the crate (see main.py, e.g. create_all_devices) -
    # that is an intended takeover, not a real double assignment.
    id_sources = {}
    library_id_sources = {}
    for source_name, data in {**libraries, **datagraph_sources}.items():
        for entity in _entities(data):
            entity_id = entity.get("@id")
            if entity_id:
                id_sources.setdefault(entity_id, []).append(source_name)
                if source_name in libraries:
                    library_id_sources.setdefault(entity_id, []).append(source_name)

    # 2) Dead references: collect outgoing references ONLY from the library files.
    dangling = []
    referenced_ids = set()
    for source_name, data in libraries.items():
        for entity in _entities(data):
            for ref_id in _entity_references(entity):
                if not _is_checkable(ref_id):
                    continue
                referenced_ids.add(ref_id)
                if ref_id not in id_sources:
                    dangling.append((source_name, entity.get("@id"), ref_id))

    # References from the data graph count for the "unreferenced" check (best effort, see the
    # task "if easily possible") - a Fixed library entry is typically used/linked only in the
    # data graph, not already within the static libraries themselves.
    for data in datagraph_sources.values():
        for entity in _entities(data):
            for ref_id in _entity_references(entity):
                if _is_checkable(ref_id):
                    referenced_ids.add(ref_id)

    # 3) IDs assigned twice: the same @id as an entity of its own more than once - ONLY within
    # the library files themselves (in the same or in different files).
    duplicates = {entity_id: sources for entity_id, sources in library_id_sources.items() if len(sources) > 1}

    # 4) Unreferenced library entries (best effort - see the note in the report below).
    unreferenced = [
        entity_id
        for data in libraries.values()
        for entity in _entities(data)
        if (entity_id := entity.get("@id")) and entity_id not in referenced_ids
    ]

    print("=== Library consistency check ===")
    print(f"Checked libraries: {', '.join(libraries)}")
    print(f"Data graph sources used for existence checks: {', '.join(datagraph_sources) or '(none found)'}")

    undeclared = {
        name: missing
        for name, data in libraries.items()
        if (missing := _undeclared_prefixes(data))
    }
    print(f"\nUndeclared prefixes ({sum(len(v) for v in undeclared.values())}):")
    for name, missing in undeclared.items():
        print(f"  {name}: {', '.join(missing)} - used in the file, missing from its own @context")
    if not undeclared:
        print("  none")

    disagreements = _namespace_disagreements(libraries)
    print(f"\nNamespace disagreements ({len(disagreements)}):")
    for prefix, namespaces in disagreements:
        print(f"  {prefix}:")
        for namespace, sources in sorted(namespaces.items()):
            print(f"    {namespace}  <- {', '.join(sources)}")
    if not disagreements:
        print("  none")

    print(f"\nDangling references ({len(dangling)}):")
    for source_name, entity_id, ref_id in dangling:
        print(f"  {source_name}: {entity_id} -> {ref_id} (target does not exist in any library or data graph source)")
    if not dangling:
        print("  none")

    print(f"\nDuplicate IDs ({len(duplicates)}):")
    for entity_id, sources in duplicates.items():
        print(f"  {entity_id} defined {len(sources)} times: {', '.join(sources)}")
    if not duplicates:
        print("  none")

    rule_4_1 = _rule_4_1_problems(libraries)
    print(f"\nValues, Evidence/Reference and determination tasks - rule 4.1 ({sum(len(v) for v in rule_4_1.values())}):")
    for kind, rows in rule_4_1.items():
        for source_name, entity_id, detail in rows:
            print(f"  {kind}: {source_name}: {entity_id}" + (f" ({detail})" if detail else ""))
    if not any(rule_4_1.values()):
        print("  none")

    layers = _layer_problems(libraries)
    print(f"\nLayers of device walls - rule 3.8a ({sum(len(v) for v in layers.values())}):")
    for kind, rows in layers.items():
        for source_name, entity_id, detail in rows:
            print(f"  {kind}: {source_name}: {entity_id}" + (f" ({detail})" if detail else ""))
    if not any(layers.values()):
        print("  none")

    context_links = _context_links(libraries)
    print()
    print(f"Context links in libraries - rule 6.6 ({len(context_links)}):")
    for source_name, entity_id, prop in context_links:
        print(f"  {source_name}: {entity_id} carries {prop}")
    if not context_links:
        print("  none")

    crates = {name: data for name, data in datagraph_sources.items() if name.endswith(path_definitions.CRATE_FILE_NAME)}
    unbalanced, unchecked = _reaction_balance(libraries, crates)
    print(f"\nBalance of stoichiometric reactions, atoms and charge ({len(unbalanced)}):")
    for line in unchecked:
        print(f"  (not checkable: {line})")
    for line in unbalanced:
        print(f"  UNBALANCED: {line}")
    if not unbalanced:
        print("  none")

    solvent_problems = _solvent_problems({**libraries, **crates})
    print(f"\nSolvents of phases - rule 3.12 ({len(solvent_problems)}):")
    for source_name, entity_id, detail in solvent_problems:
        print(f"  {source_name}: {entity_id} ({detail})")
    if not solvent_problems:
        print("  none")

    container_problems = _container_problems(libraries)
    print(f"\nContainers of the inventory - lot, since when, cabinet ({len(container_problems)}):")
    for source_name, entity_id, detail in container_problems:
        print(f"  {source_name}: {entity_id} ({detail})")
    if not container_problems:
        print("  none")

    lonely = _interfaces_without_transfers(libraries, crates)
    print(f"\nInterfaces without transfers and without an inert phase - rule 3b.2 ({len(lonely)}):")
    for source_name, entity_id, detail in lonely:
        print(f"  {source_name}: {entity_id} ({detail})")
    if not lonely:
        print("  none")

    placement = _placement_problems(libraries)
    print(f"\nDevices and contents apart - device and material library ({len(placement)}):")
    for source_name, entity_id, detail in placement:
        print(f"  {source_name}: {entity_id} ({detail})")
    if not placement:
        print("  none")

    content_histories = _content_history_problems(libraries)
    print(f"\nContents of devices - current one and history ({len(content_histories)}):")
    for source_name, entity_id, detail in content_histories:
        print(f"  {source_name}: {entity_id} ({detail})")
    if not content_histories:
        print("  none")

    histories = _usage_history_problems(libraries)
    print(f"\nUsage histories start with a commissioning - rule 5.5 ({len(histories)}):")
    for source_name, entity_id, detail in histories:
        print(f"  {source_name}: {entity_id} ({detail})")
    if not histories:
        print("  none")

    joints = _joint_problems(libraries)
    print(f"\nJoined ports name each other - cpo:isConnectedTo ({len(joints)}):")
    for source_name, entity_id, detail in joints:
        print(f"  {source_name}: {entity_id} ({detail})")
    if not joints:
        print("  none")

    cas = _cas_problems(libraries)
    print(f"\nCAS numbers with a wrong format or check digit - rule 2.8 ({len(cas)}):")
    for source_name, entity_id, number in cas:
        print(f"  {source_name}: {entity_id} ({number})")
    if not cas:
        print("  none")

    crate_ids = _crate_id_problems(libraries, crates)
    print(f"\nIDs in the crates - rules 1.2, 2.1 ({len(crate_ids)}):")
    for source_name, entity_id, detail in crate_ids:
        print(f"  {source_name}: {entity_id} ({detail})")
    if not crate_ids:
        print("  none")

    print(f"\nUnreferenced library entries ({len(unreferenced)}):")
    print("  (best effort - many of these are expected: a Fixed-level entity is often only")
    print("   referenced once it's actually used in a real experiment run, i.e. from the")
    print("   generated data graph, not from within the static libraries themselves.)")
    for entity_id in unreferenced:
        print(f"  {entity_id}")

    qudt_problems, qudt_notes = check_units_against_qudt()
    print(f"\nUnits and quantity kinds against QUDT ({len(qudt_problems)}):")
    for note in qudt_notes:
        print(f"  ({note})")
    for problem in qudt_problems:
        print(f"  {problem}")
    if not qudt_problems:
        print("  none")


if __name__ == "__main__":
    main()
