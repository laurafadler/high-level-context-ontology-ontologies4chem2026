"""
The core file: what one ELN record says, in our own neutral form. Plain JSON, not JSON-LD - an intermediate product. Its
fields are the union of what the example exports actually contain; everything a profile cannot
place goes to "unmapped", unchanged. The adapter translates a core file into answer keys; neither
the ELN nor its profile needs to know the keys.

    source        system, version, file, record id and URL
    experiment    title, status, completed, entry times, experiment date, text, keywords
    people        the people of the record (author first), with the local ID of the ELN
    reaction      name, reaction SMILES, the .rxn file if there is one
    substances    one entry per substance: role (reactant, reagent, solvent, catalyst, product),
                  name, SMILES, molar mass, mass / amount / volume with unit, equivalents,
                  the form it was delivered in, hazard codes
    conditions    temperature, mode (batch/flow), ... - value, unit, and the text they came from
    results       yield, conversion, selectivity - value as given, unit, the substance it refers to
    procedure     free text and ordered steps
    notes         comments and addenda with author and time
    files         the files of the record
    setup_sheet   the part only a person can say (which substance sits in which material and
                  phase of which device) - empty from the ELN; filled by a person
    unmapped      what the profile does not place
"""
import json
from pathlib import Path

CORE_VERSION = 1


def new_core(system, version, file_name, record_id, record_url=None) -> dict:
    return {
        "core_version": CORE_VERSION,
        "source": {"system": system, "version": version, "file": file_name, "record_id": record_id, "record_url": record_url},
        "experiment": {},
        "people": [],
        "reaction": {},
        "substances": [],
        "conditions": [],
        "results": [],
        "procedure": {"text": "", "steps": []},
        "notes": [],
        "files": [],
        "setup_sheet": None,
        "unmapped": {},
    }


def quantity(value, unit):
    """A value with its unit as the ELN gave it, or None when there is no number."""
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return {"value": value, "unit": unit, "not_a_number": True}
    return {"value": number, "unit": unit}


def write(core: dict, folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    source = core["source"]
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in f"{source['system']}_{source['record_id']}")
    path = folder / f"{safe}.json"
    path.write_text(json.dumps(core, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
