"""
Chemotion profile: Chemotion's own collection export - a ZIP with export.json, schema.json,
attachments/ and images/, not an .eln file (example: Congjian Lin). export.json holds
the tables of the Chemotion database (Reaction, Sample, Molecule, Container, Attachment,
Labimotion::Segment ...), each a dict by UUID. A record is a reaction: one experiment. The
substances of a reaction are the samples of its link tables (ReactionsStartingMaterialSample ...);
analyses hang as containers on the samples and the reaction, their files under attachments/.

The ZIP is read as it is, not unpacked: unpacked on Windows, the names under images/ (structure
pictures, up to 149 characters) exceed the length of a path, and nothing there is needed.
"""
import json

import zipfile
from pathlib import Path

from interfaces.eln.core import new_core, quantity

SCHEMA_ID = "https://www.chemotion.net/schema.json"

# Link table -> role, as the word of the ELN (rule P-AI2 holds accordingly: no translation).
ROLES = (("ReactionsStartingMaterialSample", "starting material"), ("ReactionsReactantSample", "reactant"),
         ("ReactionsSolventSample", "solvent"), ("ReactionsPurificationSolventSample", "purification solvent"),
         ("ReactionsProductSample", "product"))

# Statuses the user interface of Chemotion offers (Planned, Running, Done, Analyses Pending,
# Successful, Not Successful) - not from the export: there status is free text, the schema names no values.
# Which of them means "completed" is set here (P-CH3). "Analyses pending" stays open (None):
# the lab work is finished, the evaluation not.
COMPLETED_STATUS = {"done", "successful", "not successful"}
OPEN_STATUS = {"planned", "running"}

# Unit of an amount -> quantity in the core (mass, volume, amount); only the dimension, nothing converted.
DIMENSIONS = {"g": "mass", "mg": "mass", "µg": "mass", "ug": "mass", "kg": "mass",
              "l": "volume", "ml": "volume", "µl": "volume", "ul": "volume",
              "mol": "amount", "mmol": "amount", "µmol": "amount", "umol": "amount"}


def is_export(path) -> bool:
    """A Chemotion collection export: a ZIP with export.json and the Chemotion schema.json at its root."""
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            if not {"export.json", "schema.json"} <= names:
                return False
            return json.loads(archive.read("schema.json")).get("$id") == SCHEMA_ID
    except (zipfile.BadZipFile, OSError, ValueError):
        return False


class ChemotionExport:
    """One collection export: its tables and its files."""

    def __init__(self, path):
        self.path = Path(path)
        self.zip = zipfile.ZipFile(self.path)
        self.data = json.loads(self.zip.read("export.json"))
        self.names = set(self.zip.namelist())

    def producer(self) -> dict:
        # The export names no version of Chemotion.
        return {"name": "Chemotion", "version": None}

    def table(self, name) -> dict:
        return self.data.get(name) or {}

    def records(self) -> list:
        """The reactions of the export, oldest first, each with its UUID under "_id"."""
        reactions = [dict(reaction, _id=uuid) for uuid, reaction in self.table("Reaction").items()
                     if not reaction.get("deleted_at")]
        return sorted(reactions, key=lambda r: r.get("created_at") or "")

    def read_file(self, path_in_zip: str) -> bytes:
        return self.zip.read(path_in_zip)

    def attachment_path(self, attachment) -> str | None:
        """Where the file of an attachment lies in the ZIP: attachments/<identifier>.<extension>."""
        suffix = Path(attachment.get("filename") or "").suffix
        path = f"attachments/{attachment.get('identifier')}{suffix}"
        return path if path in self.names else None


def matches(archive) -> bool:
    return isinstance(archive, ChemotionExport)


def quill_to_text(value) -> str:
    """Plain text of a rich text field of Chemotion (Quill delta: {"ops": [{"insert": ...}]})."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return value.strip()
    if not isinstance(value, dict):
        return ""
    text = "".join(op.get("insert", "") for op in value.get("ops", []) if isinstance(op.get("insert"), str))
    return "\n".join(line.rstrip() for line in text.strip().splitlines())


def _given(value):
    """None for a value nobody entered in a field without null: Chemotion writes 0 there (P-CH5) - as a
    number (target amount, density, molarity) or as the text "0" (rf_value)."""
    return None if value in (None, "", 0, 0.0, "0", "0.0") else value


def _amounts(value, unit, prefix="", zero_is_empty=True) -> dict:
    """A Chemotion amount as mass, volume or amount (by its unit), with an optional prefix."""
    # The real amount can be null - there "not entered" means null, a 0 stays 0 (P-CH5).
    value = _given(value) if zero_is_empty else (None if value in (None, "") else value)
    if value is None:
        return {}
    dimension = DIMENSIONS.get((unit or "").lower(), "amount_unknown_dimension")
    return {f"{prefix}{dimension}": quantity(value, unit)}


def _segments(export, element_type, element_id, label) -> list:
    """The filled fields of the generic segments (Labimotion) of one element."""
    klasses = export.table("Labimotion::SegmentKlass")
    found = []
    for segment in export.table("Labimotion::Segment").values():
        if segment.get("element_type") != element_type or segment.get("element_id") != element_id or segment.get("deleted_at"):
            continue
        klass = (klasses.get(segment.get("segment_klass_id")) or {}).get("label")
        for layer_key, layer in ((segment.get("properties") or {}).get("layers") or {}).items():
            for field in layer.get("fields") or []:
                value = field.get("value")
                if value in (None, "", [], {}, False) or (isinstance(value, dict) and not any(value.values())):
                    continue
                found.append({"of": label, "segment": klass, "layer": layer.get("label") or layer_key,
                              "field": field.get("field"), "label": field.get("label"), "type": field.get("type"),
                              "value": value, "unit": field.get("value_system")})
    return found


def _containers(export):
    """(children by parent, owner by root): the container tree of the export."""
    children, owner = {}, {}
    for uuid, container in export.table("Container").items():
        if container.get("deleted_at"):
            continue
        if container.get("parent_id"):
            children.setdefault(container["parent_id"], []).append(uuid)
        if container.get("containable_type"):
            owner[(container["containable_type"], container["containable_id"])] = uuid
    return children, owner


def _files(export, element_type, element_id, label) -> list:
    """The files of the analyses of one element (reaction or sample): the attachments of its
    datasets, with the analysis they belong to."""
    containers = export.table("Container")
    children, owner = _containers(export)
    by_container = {}
    for attachment in export.table("Attachment").values():
        if attachment.get("attachable_type") == "Container" and not attachment.get("deleted_at"):
            by_container.setdefault(attachment.get("attachable_id"), []).append(attachment)

    found = []
    stack = [(owner.get((element_type, element_id)), None)]
    while stack:
        uuid, analysis = stack.pop()
        if uuid is None:
            continue
        container = containers.get(uuid) or {}
        if container.get("container_type") == "analysis":
            analysis = container
        for attachment in by_container.get(uuid, []):
            meta = (analysis or {}).get("extended_metadata") or {}
            described = (container.get("extended_metadata") or {}).get("general_description")
            try:
                creator = json.loads(described).get("creator") if described else None
            except (ValueError, AttributeError):
                creator = None
            found.append({"path": export.attachment_path(attachment), "name": attachment.get("filename"),
                          "encoding_format": attachment.get("content_type"), "size": attachment.get("filesize"),
                          "md5": attachment.get("checksum"), "created": attachment.get("created_at"),
                          "of": label, "analysis": (analysis or {}).get("name"), "analysis_kind": meta.get("kind"),
                          "analysis_status": meta.get("status"), "analysis_text": quill_to_text(meta.get("content")),
                          "dataset": container.get("name"),
                          # The name stands only here, as the creator of the dataset - the users themselves are missing from the export.
                          "dataset_creator": creator})
        stack.extend((child, analysis) for child in children.get(uuid, []))
    return sorted(found, key=lambda f: (f["of"] or "", f["analysis"] or "", f["name"] or ""))


def _inventory(export, sample_id) -> dict | None:
    """The inventory record (table Chemical, the tab 'Inventory' of a sample) of a sample or of the
    nearest sample it was split from (ancestry) - passed on as the ELN writes it (P-CH10)."""
    samples = export.table("Sample")
    chain = [sample_id] + list(reversed([a for a in ((samples.get(sample_id) or {}).get("ancestry") or "").split("/") if a]))
    by_sample = {c.get("sample_id"): c for c in export.table("Chemical").values() if not c.get("deleted_at")}
    for holder in chain:
        record = by_sample.get(holder)
        if record is None:
            continue
        data = (record.get("chemical_data") or [{}])[0]
        amount, volume = data.get("amount") or {}, data.get("volume") or {}
        temperature = data.get("storage_temperature") or {}
        place = {key: data.get(f"host_{key}") or None for key in ("building", "room", "cabinet", "group", "owner")}
        current = {key: data.get(f"current_{key}") or None for key in ("building", "room", "cabinet", "group")}
        return {
            "held_by": (samples.get(holder) or {}).get("short_label"),
            "vendor": data.get("vendor") or None,
            # The supplier-side number as Chemotion calls it: for a purchase the catalogue number, for an
            # own stock often the lot - what it is is decided by the curation (P-CH10).
            "order_number": data.get("order_number") or None,
            "amount": quantity(_given(amount.get("value")), amount.get("unit")),
            "volume": quantity(_given(volume.get("value")), volume.get("unit")),
            "status": data.get("status") or None,
            "stored_at": {k: v for k, v in place.items() if v} or None,
            "currently_at": {k: v for k, v in current.items() if v} or None,
            "ordered_date": data.get("ordered_date") or None,
            "expiration_date": data.get("expiration_date") or None,
            "storage_temperature": quantity(_given(temperature.get("value")), temperature.get("unit")),
            "disposal_info": data.get("disposal_info") or None,
            "important_notes": data.get("important_notes") or None,
            "price": data.get("price") or None,
            "cas": record.get("cas") or None,
            "unmapped": {k: v for k, v in data.items() if k not in {
                "vendor", "order_number", "amount", "volume", "status", "ordered_date", "expiration_date",
                "storage_temperature", "disposal_info", "important_notes", "price"}
                and not k.startswith(("host_", "current_")) and v not in (None, "", {}, [])} or None,
        }
    return None


def _substance(export, link, role) -> dict:
    sample = export.table("Sample").get(link["sample_id"]) or {}
    molecule = export.table("Molecule").get(sample.get("molecule_id")) or {}
    # A sample without a structure (decoupled, such as biomass) hangs at a placeholder molecule "DUMMY".
    structure = molecule.get("inchikey") not in (None, "", "DUMMY")
    parent = export.table("Sample").get((sample.get("ancestry") or "").split("/")[-1]) or {}
    substance = {
        "role": role,
        "name": sample.get("name") or (molecule.get("iupac_name") if structure else None),
        "sample_label": sample.get("short_label"),
        "sample_id": link["sample_id"],
        "split_from": parent.get("short_label"),
        "description": sample.get("description") or None,
        "external_label": sample.get("external_label") or None,
        "with_structure": structure,
        "iupac_name": molecule.get("iupac_name") if structure else None,
        "smiles": molecule.get("cano_smiles") if structure else None,
        "inchikey": molecule.get("inchikey") if structure else None,
        "molecular_formula": molecule.get("sum_formular") if structure else None,
        "molar_mass": quantity(molecule.get("molecular_weight"), "g/mol") if structure else None,
        "reference": link.get("reference"),
        "coefficient": link.get("coefficient"),
        "purity": sample.get("purity"),
        "density": quantity(_given(sample.get("density")), "g/mL"),
        "molarity": quantity(_given(sample.get("molarity_value")), sample.get("molarity_unit")),
    }
    # The CAS number the sample carries itself (xref), its storage location as free text and its
    # inventory - only where they exist (P-CH10).
    if (sample.get("xref") or {}).get("cas"):
        substance["cas"] = sample["xref"]["cas"]
    if sample.get("location"):
        substance["location_text"] = sample["location"]
    inventory = _inventory(export, link["sample_id"])
    if inventory:
        substance["inventory"] = inventory
    target = (sample.get("target_amount_value"), sample.get("target_amount_unit"))
    real = (sample.get("real_amount_value"), sample.get("real_amount_unit"))
    if role == "product":
        # For the product the target amount is the theoretical yield, the real amount the one obtained (P-CH4).
        substance.update(_amounts(*real, zero_is_empty=False))
        substance.update(_amounts(*target, prefix="theoretical_"))
    else:
        substance["equivalents"] = quantity(_given(link.get("equivalent")), None)
        substance.update(_amounts(*target))
        substance.update(_amounts(*real, prefix="real_", zero_is_empty=False))
    return substance


def to_core(archive, record) -> dict:
    export, reaction, uuid = archive, record, record["_id"]
    label = reaction.get("short_label") or uuid
    core = new_core("Chemotion", None, export.path.name, label)
    core["source"]["record_uuid"] = uuid

    status = reaction.get("status") or None
    collections = {link.get("collection_id") for link in export.table("CollectionsReaction").values()
                   if link.get("reaction_id") == uuid}
    core["experiment"] = {
        "title": reaction.get("name") or None,
        "status": status,
        "completed": (True if status.lower() in COMPLETED_STATUS else False if status.lower() in OPEN_STATUS else None)
                     if status else None,
        "entry_created": reaction.get("created_at"),
        "entry_modified": reaction.get("updated_at"),
        # Start and end of the experiment as Chemotion writes them (dd/mm/yyyy hh:mm:ss) - often empty (P-CH2).
        "experiment_date": reaction.get("timestamp_start") or None,
        "experiment_end": reaction.get("timestamp_stop") or None,
        "description_text": reaction.get("plain_text_description") or quill_to_text(reaction.get("description")),
        "keywords": [],
        "collections": sorted((export.table("Collection").get(c) or {}).get("label") for c in collections if c),
        "reaction_type": reaction.get("role") or None,
    }

    if reaction.get("created_by"):
        # Only the UUID of the user: the export contains no table of users (P-CH6).
        core["people"].append({"local_id": reaction["created_by"], "given_name": None, "family_name": None,
                               "email": None, "orcid": None, "role": "author"})

    core["reaction"] = {"name": reaction.get("name") or None, "smiles": None,
                        "rinchi": reaction.get("rinchi_string") or None,
                        "rinchi_long_key": reaction.get("rinchi_long_key") or None,
                        "rxno": reaction.get("rxno") or None}

    links = []
    for table, role in ROLES:
        for link in export.table(table).values():
            if link.get("reaction_id") == uuid and not link.get("deleted_at"):
                links.append((role, link))
    links.sort(key=lambda item: ([r for _, r in ROLES].index(item[0]), item[1].get("position") or 0))
    core["substances"] = [_substance(export, link, role) for role, link in links]

    temperature = reaction.get("temperature") or {}
    if temperature.get("userText") not in (None, ""):
        core["conditions"].append({"property": "temperature",
                                   "value": quantity(temperature["userText"], temperature.get("valueUnit")),
                                   "text": "temperature.userText"})
    if temperature.get("data"):
        core["conditions"].append({"property": "temperature_course", "value": temperature["data"],
                                   "unit": temperature.get("valueUnit"), "text": "temperature.data"})
    if reaction.get("duration") not in (None, ""):
        # The duration stands without a unit in the export - the unit stays empty (like P-AI4).
        core["conditions"].append({"property": "duration", "value": quantity(reaction["duration"], None),
                                   "text": "duration (no unit in the export)"})
    for field, prop in (("conditions", "conditions_text"), ("solvent", "solvent_text")):
        if reaction.get(field):
            core["conditions"].append({"property": prop, "value": reaction[field], "text": field})

    core["procedure"] = {"text": core["experiment"]["description_text"], "steps": []}
    observation = reaction.get("plain_text_observation") or quill_to_text(reaction.get("observation"))
    if observation:
        core["notes"].append({"text": observation, "time": None, "author": None, "kind": "observation"})

    core["files"] = _files(export, "Reaction", uuid, label)
    for substance in core["substances"]:
        core["files"] += _files(export, "Sample", substance["sample_id"], substance["sample_label"])

    segments = _segments(export, "Reaction", uuid, label)
    for substance in core["substances"]:
        segments += _segments(export, "Sample", substance["sample_id"], substance["sample_label"])
    unmapped = {"segments": segments}
    for field in ("purification", "dangerous_products", "tlc_solvents", "tlc_description", "rf_value", "variations",
                  "volume"):
        if _given(reaction.get(field)) not in (None, [], {}):
            unmapped[field] = reaction[field]
    if (reaction.get("vessel_size") or {}).get("amount"):
        unmapped["vessel_size"] = reaction["vessel_size"]
    if reaction.get("gaseous"):
        unmapped["gaseous"] = True
    core["unmapped"] = unmapped
    return core
