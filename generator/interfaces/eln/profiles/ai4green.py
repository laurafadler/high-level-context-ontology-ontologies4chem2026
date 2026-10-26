"""
AI4Green profile: the chemistry of a record is not in the RO-Crate graph but in a JSON file next to
it (<reaction id>.json), plus a .rxn file and an HTML table in the record's "text" with molar mass,
density and equivalents per substance.
"""
import json
import re

from interfaces.eln.core import new_core, quantity
from interfaces.eln.reader import html_to_text

ROLES = (("reactants", "reactant"), ("reagents", "reagent"), ("solvents", "solvent"), ("catalysts", "catalyst"),
         ("products", "product"))


def matches(archive) -> bool:
    return (archive.producer().get("name") or "").lower().startswith("ai4green")


def _table(text_html: str) -> dict:
    """The substance table in the record's HTML: name -> its columns. Reactants, reagents and
    solvents: molar mass, density, equivalents. Products have columns of their own: molar mass,
    theoretical yield, unreacted, product mass, % yield - the product mass here is the one obtained,
    while the JSON gives the theoretical one."""
    rows, in_products = {}, False
    for row in re.findall(r"<tr>(.*?)</tr>", text_html or "", flags=re.S):
        cells = [html_to_text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", row, flags=re.S)]
        if "Product" in cells:
            in_products = True
            continue
        if "Hazards" in cells:
            in_products = False
        if len(cells) >= 6 and cells[0].isdigit() and cells[1]:
            if in_products:
                rows[cells[1]] = {"molar_mass": cells[2], "theoretical_mass": cells[3], "unreacted_mass": cells[4],
                                  "product_mass": cells[5], "percent_yield": cells[6] if len(cells) > 6 else None}
            else:
                rows[cells[1]] = {"molar_mass": cells[2], "density": cells[3], "equivalents": cells[5]}
    return rows


def _reaction_smiles(text_html: str):
    match = re.search(r"Reaction Smiles:\s*([^<\s]+)", text_html or "")
    return match.group(1) if match else None


def to_core(archive, record) -> dict:
    files = archive.files(record)
    data_file = next((f for f in files if f["path"].endswith(".json")), None)
    data = json.loads(archive.read_file(data_file["path"])) if data_file else {}
    producer = archive.producer()
    record_id = data.get("reaction_id") or record["@id"].strip("./")
    core = new_core("AI4Green", producer.get("version"), archive.path.name, record_id)

    core["experiment"] = {
        "title": data.get("reaction_name") or record.get("name"),
        "status": data.get("reaction_completed"),
        "completed": data.get("reaction_completed") == "complete",
        "entry_created": data.get("time_of_creation") or record.get("dateCreated"),
        "entry_modified": data.get("time_of_last_update") or record.get("dateModified"),
        # AI4Green does not say when the experiment ran - only when the entry was made (finding 3.4).
        "experiment_date": None,
        "description_text": html_to_text(record.get("description", "")),
        "keywords": [],
        "workbook": data.get("creator_workbook"), "workgroup": data.get("creator_workgroup"),
    }

    author = record.get("author")
    if author:
        person = archive.person(author)
        person.update({"username": data.get("creator_username"), "role": "author"})
        core["people"].append(person)

    text_html = record.get("text", "")
    core["reaction"] = {"name": data.get("reaction_name"), "smiles": _reaction_smiles(text_html),
                        "rxn_file": next((f["path"] for f in files if f["path"].endswith(".rxn")), None)}

    table = _table(text_html)
    for key, role in ROLES:
        for item in data.get(key) or []:
            extra = table.get(item.get("name"), {})
            substance = {
                "role": role, "name": item.get("name"), "smiles": item.get("SMILES"),
                "molar_mass": quantity(extra.get("molar_mass"), "g/mol"),
                "mass": quantity(item.get("mass"), item.get("mass_unit")),
                "amount": quantity(item.get("amount"), item.get("amount_unit")),
                "volume": quantity(item.get("volume"), item.get("volume_unit")),
                "density": quantity(extra.get("density"), "g/mL"),
                "equivalents": quantity(extra.get("equivalents"), None),
                "delivered_as": item.get("physical_form"),
                "hazard_codes": item.get("h_codes") or item.get("hazard_codes"),
            }
            if role == "product":
                # For the product the JSON holds mass and amount of substance of the THEORETICAL yield;
                # what was obtained is what the table names as the product mass (here 100 mg instead of 122 mg).
                substance["theoretical_mass"] = substance["mass"]
                substance["theoretical_amount"] = substance.pop("amount")
                substance["mass"] = quantity(extra.get("product_mass"), "mg")
                substance["unreacted_limiting_reactant_mass"] = quantity(extra.get("unreacted_mass"), "mg")
                substance.pop("equivalents")
                substance.pop("density")
            core["substances"].append(substance)

    if data.get("temperature") not in (None, ""):
        # Without a unit in the export - the unit stays empty, nothing is assumed.
        core["conditions"].append({"property": "temperature", "value": quantity(data["temperature"], None),
                                   "text": "temperature (no unit in the export)"})
    if data.get("batch_or_flow"):
        core["conditions"].append({"property": "mode_of_operation", "value": data["batch_or_flow"], "text": "batch_or_flow"})
    if data.get("isolation_method"):
        core["conditions"].append({"property": "isolation_method", "value": data["isolation_method"], "text": "isolation_method"})

    products = [s["name"] for s in core["substances"] if s["role"] == "product"]
    # Yield and selectivity name no product in the export. With exactly one it is that one; with
    # several it stays empty instead of taking the first (rule P-AI5 of interfaces/eln/README.md).
    product = products[0] if len(products) == 1 else None
    # The conversion holds for the limiting reactant, but the export does not name it. It stays
    # empty instead of being inferred from the equivalents.
    limiting = None
    for prop, key, of in (("yield", "percent_yield", product),
                          ("conversion", "conversion", limiting),
                          ("selectivity", "selectivity", product)):
        if data.get(key) not in (None, ""):
            core["results"].append({"property": prop, "value": quantity(data[key], "%"), "of": of})

    core["procedure"] = {"text": data.get("experimental_writeup") or html_to_text(record.get("description", "")), "steps": []}
    for addendum in data.get("addenda") or []:
        core["notes"].append({"text": addendum.get("text"), "time": addendum.get("time_of_creation"),
                              "author": {"username": addendum.get("author")}})
    core["notes"] += archive.comments(record)
    # The parts of the export themselves (.json, .rxn) are no files of the experiment.
    core["files"] = [f for f in files if not f["path"].endswith((".json", ".rxn"))]

    core["unmapped"] = {key: data[key] for key in ("standard_protocols_used", "solvent_sustainability", "safety",
                                                   "element_sustainability", "catalyst_use", "catalyst_recovery",
                                                   "atom_economy", "mass_efficiency", "sustainability_data")
                        if key in data}
    return core
