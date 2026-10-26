"""
Building blocks for library entries that come from an ELN record (library pre-run): a
chemical entity from its PubChem record, the ELN record itself, a person.

Where an entry comes from:
- the same thing in another system -> schema:identifier, a schema:PropertyValue with the system
  (propertyID), the local ID (value) and a URL;
- a record that describes or uses the thing -> schema:subjectOf on the thing, schema:about back on
  the record (always as a pair, rule 4a.3).
Never hlo:hasSource - that is the literature source of a reference.

Values follow rule 4.1 like every library value (helpers/inventory_entries.py: Entries).
"""
from helpers.inventory_entries import Entries, ref


def identifier(entity_id: str, system: str, value: str, url: str = None) -> dict:
    """A schema:PropertyValue naming the same thing in another system. Its ID has its own prefix
    (identifier:JoeDavies_AI4Green): the prefix of a library (person:, chem:) names only what the
    library is about, and a question offering its entries would offer the identifier too."""
    local = "".join(c if c.isalnum() else "_" for c in system)
    entry = {"@id": f"identifier:{entity_id.split(':', 1)[-1]}_{local}", "@type": ["schema:PropertyValue"],
             "schema:propertyID": system, "schema:value": value}
    if url:
        entry["schema:url"] = url
    return entry


def eln_record(record_id: str, system: str, local_id: str, name: str, file_name: str, about: list) -> dict:
    """The ELN record an entry was taken from, as a schema:Dataset. It names what it is about
    (schema:about); every entry names it back (schema:subjectOf)."""
    return {"@id": record_id, "@type": ["schema:Dataset"], "schema:name": name,
            "schema:identifier": f"{system} {local_id}",
            "rdfs:comment": f"Record {local_id} of the ELN {system}, exported as {file_name}. The library entries it is about "
                            f"were imported from it (schema:about / schema:subjectOf).",
            "schema:about": [ref(i) for i in about]}


def chemical_entity(lib: Entries, chem_id: str, pubchem: dict, eln_name: str, eln_smiles: str, record_id: str,
                    lookup_task_id: str, origin: str, cas: str = None, note: str = None) -> list:
    """A molecule of the chemical entity library from its PubChem record: name, SMILES, InChI,
    InChIKey, molecular formula, PubChem CID, CAS; the molar mass as an Actual with a reference to
    PubChem (Literature), determined by lookup_task_id. Returns the values lookup_task_id determines.

    origin opens the comment: where the entry comes from, who entered it and when (the entry tool
    writes it, workflow/library_entries/entry_types.py). A substance of an ELN record passes the
    record as record_id and gets schema:subjectOf; one that is in no record passes record_id=None."""
    cid = str(pubchem["CID"])
    url = f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}"
    entry = {"@id": chem_id, "@type": ["chebi:ChemicalEntity", "chebi:Molecule", "hlo:Fixed"],
             "schema:name": pubchem.get("Title") or eln_name}
    if cas:
        entry["cpo:hasCAS"] = cas
    else:
        entry["cpo:hasNoCASNumber"] = True
    entry.update({"cpo:hasSMILES": pubchem["ConnectivitySMILES"], "cpo:hasInChI": pubchem["InChI"],
                  "cpo:hasMolecularFormula": pubchem["MolecularFormula"], "cpo:hasInChIKey": pubchem["InChIKey"],
                  "cpo:hasPubChemCID": cid})
    comment = f"{origin} Identifiers and molar mass from PubChem, looked up by the SMILES {eln_smiles}: {url}."
    entry["schema:comment"] = comment + (f" {note}" if note else "")
    entry["cpo:hasMolarMass"] = ref(f"{chem_id}_MolarMass")
    if record_id:
        entry["schema:subjectOf"] = ref(record_id)
    lib.add(entry)
    molar_mass = lib.value(f"{chem_id}_MolarMass", "quantitykind:MolarMass", "Reference", float(pubchem["MolecularWeight"]),
                           "unit:GM-PER-MOL", "hlo:Literature",
                           f"Molecular weight given by PubChem (CID {cid}), computed there from the molecular formula "
                           f"{pubchem['MolecularFormula']}.", lookup_task_id, source=url)
    # A molar mass is a constant of the substance (cpo:Parameter, rule 3.7), not a ProcessVariable.
    for item in lib.items[-2:]:
        item["@type"] = ["cpo:Parameter" if t == "cpo:ProcessVariable" else t for t in item["@type"]]
    return [molar_mass]
