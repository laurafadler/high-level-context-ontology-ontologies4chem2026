"""
Where the values of the ELN core files go in a setup sheet.

The sheet holds the values of the core files in its section "values", and the adapter reads only the
sheet. This module places the values of the core files as entries of that section; workflow/prefill_sheet.py writes them into the sheet.

An entry:
    at:         "<material>/<phase>" of the sheet, or the name of a reaction (its participant: "of")
    of:         a substance - in the phase ("amount of benzoic acid"), or the reaction participant
    experiment: the experiment it belongs to (the n-th core file)
    quantity:   as the generator names it (mass, volume, amountofsubstance, temperature, yield ...)
    value, unit as the ELN gives them; the reading (kind: measured, planned ...) is left to a person
    group:      the group of the ELN record it comes from (reaction_table, conditions, product_mass,
                yield, selectivity) - what a task's "determines" can name
    source:     {value: "E: <ELN> <record>, <field>", unit: "E: ... .unit"}
"""
import json
from pathlib import Path

# Values of a core file -> quantity in the sheet.
PHASE_QUANTITIES = {"mass": "mass", "volume": "volume"}      # at the phase of an uncontained stream
SPECIES_QUANTITIES = {"amount": "amountofsubstance"}         # at the substance in this phase
RESULT_QUANTITIES = {"yield": "yield", "selectivity": "selectivity"}   # at the reaction participant


def library_ids_of_record(core_path: Path, chemical_library: dict) -> dict:
    """ELN substance name -> Chemical Entity Library ID. Through the PubChem answers of the import
    (projects/<crate_identifier>/curation/pubchem/<record>.json next to core/, InChIKey per ELN name) - not by
    the name alone."""
    pubchem = core_path.parent.parent / "curation" / "pubchem" / core_path.name
    if not pubchem.exists():
        return {}
    by_key = {}
    for entity in chemical_library.get("@graph", []):
        if entity.get("cpo:hasInChIKey"):
            by_key.setdefault(entity["cpo:hasInChIKey"], []).append(entity["@id"])
    found = {}
    for answer in json.loads(pubchem.read_text(encoding="utf-8")):
        ids = by_key.get(answer.get("InChIKey"), [])
        if len(ids) == 1:
            found[answer["eln_name"]] = ids[0]
    return found


def _single_phase(adapter, species_id, kind):
    """(material name, phase name, species name in the sheet) of the one phase of a sheet entry of
    this kind (material or uncontained_stream) that holds the species; for an uncontained stream only a phase holding nothing
    else. None otherwise."""
    hits = []
    for phase in adapter.phases.values():
        if phase["_material"]["_kind"] != kind or species_id not in phase["_species_ids"]:
            continue
        if kind == "uncontained_stream" and len(phase["_species_ids"]) != 1:
            continue
        hits.append((phase["_material"]["name"], phase["name"], phase["_species_ids"][species_id]))
    return hits[0] if len(hits) == 1 else None


def _phase_of_reaction(adapter, reaction) -> tuple | None:
    hits = [(p["_material"]["name"], p["name"]) for p in adapter.phases.values()
            if str(p["name"]).lower() == str(reaction.get("in_phase") or "").lower()]
    return hits[0] if len(hits) == 1 else None


def eln_entries(adapter) -> tuple:
    """(entries, unplaced): the values of the core files as entries of the section "values", and
    the substances of the core files that have no place in the sheet (or no library entry)."""
    entries, unplaced = [], []
    for nr, (path, core) in enumerate(zip(adapter.core_paths, adapter.cores), start=1):
        label = f"ELN {core['source']['system']} {core['source']['record_id']}"
        library_ids = library_ids_of_record(path, adapter.chemical_library)

        def add(at, quantity, raw, group, field, of=None):
            entry = {"at": at}
            if of:
                entry["of"] = of
            entry.update({"experiment": nr, "quantity": quantity, "value": raw.get("value"), "unit": raw.get("unit"),
                          "group": group, "source": {"value": f"E: {label}, {field}"}})
            if raw.get("unit"):
                entry["source"]["unit"] = f"E: {label}, {field}.unit"
            entries.append(entry)

        for index, substance in enumerate(core.get("substances", [])):
            species_id = library_ids.get(substance.get("name"))
            if species_id is None:
                unplaced.append(f"{substance.get('name')}: no entry in the Chemical Entity Library (PubChem answers of the import)")
                continue
            field = f"substances[{index}]"
            if substance.get("role") == "product":
                place = _single_phase(adapter, species_id, "material")
                if place is None:
                    unplaced.append(f"{substance.get('name')}: no material of the sheet holds it (the product)")
                elif substance.get("mass"):
                    add(f"{place[0]}/{place[1]}", "mass", substance["mass"], "product_mass", f"{field}.mass")
                continue
            place = _single_phase(adapter, species_id, "uncontained_stream")
            if place is None:
                unplaced.append(f"{substance.get('name')}: no uncontained stream of the sheet holds it alone")
                continue
            for core_name, quantity in PHASE_QUANTITIES.items():
                if substance.get(core_name):
                    add(f"{place[0]}/{place[1]}", quantity, substance[core_name], "reaction_table", f"{field}.{core_name}")
            for core_name, quantity in SPECIES_QUANTITIES.items():
                if substance.get(core_name):
                    add(f"{place[0]}/{place[1]}", quantity, substance[core_name], "reaction_table", f"{field}.{core_name}",
                        of=place[2])
        # Conditions: the temperature at the phase the reaction runs in (according to the sheet).
        for index, condition in enumerate(core.get("conditions", [])):
            if condition.get("property") == "temperature" and isinstance(condition.get("value"), dict):
                for reaction in adapter.reactions:
                    place = _phase_of_reaction(adapter, reaction)
                    if place:
                        add(f"{place[0]}/{place[1]}", "temperature", condition["value"], "conditions",
                            f"conditions[{index}].value")
        # Results at the participant they refer to - not without a substance of reference (A12, rule 2.9).
        for index, result in enumerate(core.get("results", [])):
            if result.get("property") not in RESULT_QUANTITIES or not result.get("of") or not isinstance(result.get("value"), dict):
                continue
            species_id = library_ids.get(result["of"])
            names = {p["_species_ids"][species_id] for p in adapter.phases.values() if species_id in p["_species_ids"]}
            for reaction in adapter.reactions:
                if species_id and len(names) == 1 and adapter.participant_place(reaction["name"], species_id):
                    add(reaction["name"], RESULT_QUANTITIES[result["property"]], result["value"], result["property"],
                        f"results[{index}].value", of=names.pop())
                    break
    return entries, unplaced
