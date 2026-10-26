"""
Fixed reactions from reaction templates (rule 2.11): the template (hlo:Template) keeps
its placeholders; the fixed reaction names the concrete chemical entities and points at the
template with hlo:specializationOf, like a device exemplar at its template. A sheet then names the
fixed reaction (by its name or its ID), and the run resolves no placeholder.

What is made, per template:
- the reaction and its participants: every key of a template participant is copied (role,
  coefficient, partial order - the partial order is the template's own value, shared, not copied),
  the species replaced: a species placeholder by the entity assigned to it;
- for an occupation state placeholder (adsorbed species, free site) a FIXED occupation state of its
  own: what is adsorbed where is settled (occupiedBy, boundTo with their placeholders replaced, the
  sorption type), only the interface stays open - the generator asks it per series as before
  (creation/reaction_functions.py: _is_open_occupation_state);
- its mechanism, if it has one: a new Actual with a copy of each reference (source, type and
  determination task kept - the task determines the copy too, rule 4.1), whose elementary reactions
  are fixed in the same way. An elementary reaction shared by two mechanisms - in templates made
  together - stays one fixed elementary reaction.
Templates made together (one group, one set of assignments) share their occupation states and
elementary reactions. Before anything is written, the atoms and the charge of every stoichiometric
reaction must balance (formula_counts of check_library_consistency).

Library tool: writes only the reaction library, and only new entries. Project tools call
FixedReactions / make_fixed_reaction and save the library themselves (e.g.
pba_reactions.py next to this file; archived: projects/hydrogenation_rdy_2026_09/curation/archive/fixed_reactions.py).

Usage (from the repository root):
    python generator/workflow/library_prerun/fixed_reaction_from_template.py --spec <group.json>
    python generator/workflow/library_prerun/fixed_reaction_from_template.py --template reaction:<template> \
        --set placeholder:<a>=chem:<x> [--set ...] --id reaction:<new> --name "<name>" [--comment "<origin>"]

A group file: {"prefix": "<ID stem of occupation states and elementary reactions>", "comment": "...",
"assignments": {"placeholder:A": "chem:X", ...}, "reactions": [{"template": "reaction:T", "id": "reaction:F",
"name": "...", "description": "..." (optional)}, ...]}
"""
import argparse
import json
import re
import sys
from pathlib import Path

# Runs from generator/workflow/library_prerun/ - the generator has to be on the search path.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import path_definitions  # noqa: E402
from check_library_consistency import formula_counts  # noqa: E402
from helpers.file_handling import load_jsonld, save_jsonld  # noqa: E402


def ref(entity_id):
    return {"@id": entity_id}


def _ids(value):
    values = value if isinstance(value, list) else ([] if value is None else [value])
    return [v["@id"] if isinstance(v, dict) else v for v in values]


def _types(entity):
    return set(_ids((entity or {}).get("@type")))


class LibraryFile:
    """A library read as one document (main file and details, helpers/library_files.py) and written
    back split again, in the generator's own format (save_jsonld)."""

    def __init__(self, path: Path):
        self.path = path
        self.data = load_jsonld(path)

    @property
    def graph(self):
        return self.data["@graph"]

    def by_id(self):
        return {e["@id"]: e for e in self.graph if "@id" in e}

    def save(self):
        save_jsonld(self.data, self.path)


class TemplateError(ValueError):
    pass


def _slug(text):
    return "".join(w[:1].upper() + w[1:] for w in re.findall(r"[A-Za-z0-9]+", text))


class FixedReactions:
    """Makes fixed reactions from templates of the reaction library (reactions, chemicals: ID ->
    entity of the two libraries; assignments: species placeholder ID -> chemical entity ID).
    After make(): entries - the new entities; determines - determination task -> new references."""

    def __init__(self, reactions: dict, chemicals: dict, assignments: dict, prefix: str, comment: str):
        self.reactions, self.chemicals, self.assignments = reactions, chemicals, dict(assignments)
        self.prefix, self.comment = prefix, comment
        self.entries, self.determines, self._made, self._used = [], {}, {}, set()

    # --- Substances --------------------------------------------------------------------------
    def _label(self, entity_id):
        entity = self.chemicals.get(entity_id) or self.reactions.get(entity_id) or {}
        name = entity.get("schema:name", entity_id)
        return name[0] if isinstance(name, list) else name

    def _rename(self, text):
        """A template text with the names of its species placeholders replaced (RDY -> Adiponitrile) - not
        inside the names of occupation states (cat(H), cat-H stay)."""
        for placeholder, entity in self.assignments.items():
            name = (self.reactions.get(placeholder) or {}).get("schema:name")
            if name and text:
                text = re.sub(rf"(?<![\w-]){re.escape(name)}(?![\w(-])", self._label(entity), text)
        return text

    def species(self, species_id):
        entity = self.reactions.get(species_id) or self.chemicals.get(species_id)
        if entity is not None and "cpo:Placeholder" in _types(entity):
            if "cpo:OccupationState" in _types(entity):
                return self._occupation_state(species_id, entity)
            if species_id not in self.assignments:
                raise TemplateError(f"no entity given for the placeholder {species_id}")
            self._used.add(species_id)
            species_id = self.assignments[species_id]
        if species_id not in self.chemicals and species_id not in self.reactions:
            raise TemplateError(f"{species_id} is neither in the Chemical Entity nor in the Reaction Library")
        return species_id

    def _new_id(self, wanted):
        new_id, n = wanted, 2
        while new_id in self.reactions or new_id in self._made.values():
            new_id, n = f"{wanted}_{n}", n + 1
        return new_id

    def _occupation_state(self, placeholder_id, placeholder):
        if placeholder_id in self._made:
            return self._made[placeholder_id]
        new_id = self._new_id(f"reaction:{self.prefix}_{placeholder_id.split(':', 1)[-1]}")
        self._made[placeholder_id] = new_id
        entry = {"@id": new_id, "@type": ["cpo:OccupationState", "hlo:Fixed"],
                 "schema:name": placeholder.get("schema:name"),
                 "schema:description": (self._rename(placeholder.get("schema:description", "")) + " Fixed occupation state of "
                                        f"the template {placeholder_id}: what is adsorbed where is settled, the interface is "
                                        "set per series.").strip(),
                 "hlo:specializationOf": ref(placeholder_id)}
        for key in ("cpo:occupiedBy", "cpo:boundTo"):
            if placeholder.get(key):
                entry[key] = ref(self.species(_ids(placeholder[key])[0]))
        if placeholder.get("cpo:hasSorptionType"):
            entry["cpo:hasSorptionType"] = placeholder["cpo:hasSorptionType"]
        self.entries.append(entry)
        return new_id

    # --- Reactions ----------------------------------------------------------------------------
    def _participants(self, template, reaction_id):
        participants = []
        for participant_id in _ids(template.get("cpo:hasParticipant")):
            participant = self.reactions[participant_id]
            short = participant_id.rsplit("_Participant_", 1)[-1] if "_Participant_" in participant_id \
                else participant_id.rsplit("_", 1)[-1]
            copy = {k: v for k, v in participant.items() if k not in ("@id", "cpo:participatesIn", "dcterms:hasPart")}
            copy.update({"@id": f"{reaction_id}_Participant_{short}",
                         "dcterms:hasPart": ref(self.species(_ids(participant["dcterms:hasPart"])[0])),
                         "cpo:participatesIn": ref(reaction_id), "hlo:specializationOf": ref(participant_id)})
            participants.append(copy)
        return participants

    def _balance(self, reaction_id, participants):
        total = {}
        for participant in participants:
            species = _ids(participant["dcterms:hasPart"])[0]
            counts = formula_counts((self.chemicals.get(species) or {}).get("cpo:hasMolecularFormula"))
            if counts is None:
                raise TemplateError(f"{species} has no molecular formula - the balance of {reaction_id} cannot be checked")
            for element, number in counts.items():
                total[element] = total.get(element, 0) + float(participant["cpo:hasStoichiometricCoefficient"]) * number
        off = {element: round(number, 6) for element, number in total.items() if abs(number) > 1e-9}
        if off:
            raise TemplateError(f"{reaction_id} does not balance (negative = missing on the product side): {off}")

    def _reaction(self, template_id, reaction_id, name, description, comment):
        template = self.reactions[template_id]
        participants = self._participants(template, reaction_id)
        types = [t for t in _ids(template.get("@type")) if t != "hlo:Template"]
        entry = {k: v for k, v in template.items() if k not in ("@id", "@type", "schema:name", "schema:description",
                                                                "schema:comment", "cpo:hasParticipant",
                                                                "cpo:describedByReactionMechanism")}
        entry.update({"@id": reaction_id, "@type": types, "schema:name": name,
                      "schema:description": description if description is not None else self._rename(template.get("schema:description", "")),
                      "schema:comment": comment, "hlo:specializationOf": ref(template_id),
                      "cpo:hasParticipant": [ref(p["@id"]) for p in participants]})
        if template.get("cpo:describedByReactionMechanism"):
            entry["cpo:describedByReactionMechanism"] = ref(self._mechanism(_ids(template["cpo:describedByReactionMechanism"])[0], reaction_id))
        self.entries += [entry] + participants
        return entry, participants

    def _mechanism(self, actual_id, reaction_id):
        actual = self.reactions[actual_id]
        new_actual = f"{reaction_id}_Mechanism"
        references = []
        for n, reference_id in enumerate(_ids(actual.get("hlo:hasReference")), 1):
            reference = self.reactions[reference_id]
            copy = {k: v for k, v in reference.items() if k not in ("@id", "hlo:isReferenceOf", "cpo:describesStoichiometricReaction",
                                                                    "cpo:containsElementaryReaction")}
            copy.update({"@id": f"{new_actual}_Reference_{n}", "hlo:isReferenceOf": ref(new_actual),
                         "cpo:describesStoichiometricReaction": ref(reaction_id),
                         "cpo:containsElementaryReaction": [ref(self._elementary(e)) for e in _ids(reference.get("cpo:containsElementaryReaction"))]})
            for task in _ids(reference.get("cpo:hasDeterminationTask")):
                self.determines.setdefault(task, []).append(copy["@id"])
            references.append(copy)
        self.entries.append({"@id": new_actual, "@type": _ids(actual.get("@type")),
                             "schema:name": f"Reaction mechanism of {reaction_id.split(':', 1)[-1]}",
                             "cpo:describesStoichiometricReaction": ref(reaction_id),
                             "hlo:hasReference": [ref(r["@id"]) for r in references]})
        self.entries += references
        return new_actual

    def _elementary(self, template_id):
        if template_id in self._made:
            return self._made[template_id]
        template = self.reactions[template_id]
        name = self._rename(template.get("schema:name", template_id))
        reaction_id = self._new_id(f"reaction:{self.prefix}_{_slug(name)}")
        self._made[template_id] = reaction_id
        self._reaction(template_id, reaction_id, name, None,
                       f"Elementary reaction of the template {template_id}, its placeholders replaced. {self.comment}")
        return reaction_id

    def make(self, template_id, reaction_id, name, description=None):
        template = self.reactions.get(template_id)
        if template is None or "cpo:StoichiometricReaction" not in _types(template):
            raise TemplateError(f"{template_id} is no stoichiometric reaction of the Reaction Library")
        if "hlo:Template" not in _types(template):
            raise TemplateError(f"{template_id} is no template (hlo:Template)")
        if reaction_id in self.reactions:
            raise TemplateError(f"{reaction_id} exists already")
        _, participants = self._reaction(template_id, reaction_id, name, description, self.comment)
        self._balance(reaction_id, participants)

    def check_assignments(self):
        unused = set(self.assignments) - self._used
        if unused:
            raise TemplateError(f"placeholders that occur in none of the templates: {', '.join(sorted(unused))}")


def make_fixed_reaction(reactions: dict, chemicals: dict, template_id: str, assignments: dict, reaction_id: str,
                        name: str, comment: str, description: str = None) -> list:
    """One fixed reaction without a mechanism (the PBA formations): its entries - reaction and
    participants. Raises TemplateError when something does not fit or it does not balance."""
    builder = FixedReactions(reactions, chemicals, assignments, reaction_id.split(":", 1)[-1], comment)
    builder.make(template_id, reaction_id, name, description)
    builder.check_assignments()
    if builder.determines:
        raise TemplateError(f"{template_id} has a mechanism - make it with FixedReactions, which also updates its tasks")
    return builder.entries


def write_group(spec: dict) -> list:
    """Make a group of fixed reactions (see the module docstring) and write the reaction library.
    Returns the IDs of the new stoichiometric reactions."""
    reactions = LibraryFile(path_definitions.REACTION_LIBRARY_PATH)
    chemicals = LibraryFile(path_definitions.CHEMICAL_ENTITY_LIBRARY_PATH)
    by_id = reactions.by_id()
    builder = FixedReactions(by_id, chemicals.by_id(), spec["assignments"], spec["prefix"], spec["comment"])
    for item in spec["reactions"]:
        builder.make(item["template"], item["id"], item["name"], item.get("description"))
    builder.check_assignments()
    for task, new in builder.determines.items():
        by_id[task]["cpo:determines"] = by_id[task].get("cpo:determines", []) + [ref(i) for i in new]
    reactions.graph.extend(builder.entries)
    reactions.save()
    return [item["id"] for item in spec["reactions"]]


def main():
    parser = argparse.ArgumentParser(description="Fixed reactions from reaction templates.")
    parser.add_argument("--spec", help="a group file (JSON, see the module docstring)")
    parser.add_argument("--template")
    parser.add_argument("--set", action="append", default=[], metavar="PLACEHOLDER=ENTITY")
    parser.add_argument("--id")
    parser.add_argument("--name")
    parser.add_argument("--comment", default="Made from its template with fixed_reaction_from_template.py.")
    args = parser.parse_args()
    if args.spec:
        spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    elif args.template and args.id and args.name:
        spec = {"prefix": args.id.split(":", 1)[-1], "comment": args.comment,
                "assignments": dict(item.split("=", 1) for item in args.set),
                "reactions": [{"template": args.template, "id": args.id, "name": args.name}]}
    else:
        sys.exit("Give --spec, or --template, --id and --name.")
    try:
        made = write_group(spec)
    except TemplateError as error:
        sys.exit(f"Nothing written: {error}")
    print("Added (balanced): " + ", ".join(made))


if __name__ == "__main__":
    main()
