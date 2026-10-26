"""
Reads an .eln archive (ELN File Format of the ELN Consortium: a zipped RO-Crate) the same way for
every ELN - the part all exports share. What is particular to one ELN (the chemistry of AI4Green,
the free fields of an eLabFTW instance) is left to its profile (interfaces/eln/profiles/).

Nothing here knows the answer keys of the generator (.eln reader -> ELN profile -> core file
-> adapter).
"""
import html
import json
import re
import zipfile
from pathlib import Path


def as_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def ref_id(value):
    return value.get("@id") if isinstance(value, dict) else value


def html_to_text(text: str) -> str:
    """Plain text of an HTML fragment - tags out, entities resolved, whitespace tidied."""
    if not text:
        return ""
    text = re.sub(r"<(br|/p|/h\d|/li|/tr)\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return "\n".join(" ".join(line.split()) for line in text.splitlines() if line.strip())


class ElnArchive:
    """One .eln file: its RO-Crate graph and its files."""

    def __init__(self, path):
        self.path = Path(path)
        self.zip = zipfile.ZipFile(self.path)
        metadata = [n for n in self.zip.namelist() if n.endswith("ro-crate-metadata.json")]
        if len(metadata) != 1:
            raise ValueError(f"{self.path.name}: expected one ro-crate-metadata.json, found {len(metadata)}.")
        self.metadata_name = metadata[0]
        self.root_folder = metadata[0][: -len("ro-crate-metadata.json")]
        self.graph = json.loads(self.zip.read(self.metadata_name))["@graph"]
        self.by_id = {entity["@id"]: entity for entity in self.graph}

    # --- who exported --------------------------------------------------------------------

    def producer(self) -> dict:
        """The software that wrote the export: from the CreateAction of the crate, else sdPublisher."""
        for entity in self.graph:
            if "CreateAction" in as_list(entity.get("@type")):
                instrument = entity.get("instrument")
                instrument = self.by_id.get(ref_id(instrument), instrument) if instrument else None
                if isinstance(instrument, dict) and instrument.get("name"):
                    return {"name": instrument.get("name"), "version": instrument.get("version")}
        descriptor = self.by_id.get("ro-crate-metadata.json", {})
        publisher = descriptor.get("sdPublisher")
        publisher = self.by_id.get(ref_id(publisher), publisher) if publisher else None
        if isinstance(publisher, dict):
            return {"name": publisher.get("name"), "version": descriptor.get("version")}
        return {"name": None, "version": None}

    # --- content -------------------------------------------------------------------------

    def get(self, value):
        return self.by_id.get(ref_id(value)) if value is not None else None

    def records(self) -> list:
        """The records of the export: the datasets the root dataset lists (an experiment, a reaction)."""
        root = self.by_id.get("./", {})
        return [self.by_id[ref_id(part)] for part in as_list(root.get("hasPart"))
                if ref_id(part) in self.by_id and "Dataset" in as_list(self.by_id[ref_id(part)].get("@type"))]

    def person(self, value) -> dict:
        entity = self.get(value) or {}
        return {"local_id": ref_id(value), "given_name": entity.get("givenName"), "family_name": entity.get("familyName"),
                "email": entity.get("email"), "orcid": entity.get("identifier") if "orcid" in str(entity.get("identifier", "")) else None}

    def files(self, record) -> list:
        found = []
        for part in as_list(record.get("hasPart")):
            entity = self.get(part)
            if entity is not None and "File" in as_list(entity.get("@type")):
                found.append({"path": entity["@id"], "name": entity.get("name") or Path(entity["@id"]).name,
                              "encoding_format": entity.get("encodingFormat"), "size": entity.get("contentSize"),
                              "sha256": entity.get("sha256")})
        return found

    def comments(self, record) -> list:
        found = []
        for comment in as_list(record.get("comment")):
            entity = self.get(comment) or {}
            author = entity.get("author")
            found.append({"text": html_to_text(entity.get("text", "")), "time": entity.get("dateCreated"),
                          "author": self.person(author) if author else None})
        return found

    def steps(self, record) -> list:
        """HowToSteps of a record, in order, with their text (HowToDirection) and status."""
        found = []
        for step in as_list(record.get("step")):
            entity = self.get(step) or {}
            direction = self.get(entity.get("itemListElement")) or {}
            found.append({"position": entity.get("position"), "text": html_to_text(direction.get("text", "")),
                          "status": entity.get("creativeWorkStatus"), "time": entity.get("temporal")})
        return sorted(found, key=lambda s: (s["position"] is None, s["position"]))

    def properties(self, record) -> list:
        """The free fields of a record (schema:PropertyValue in variableMeasured)."""
        found = []
        for value in as_list(record.get("variableMeasured")):
            entity = self.get(value) or {}
            found.append({"name": entity.get("propertyID"), "value": entity.get("value"), "unit": entity.get("unitText"),
                          "kind": entity.get("valueReference")})
        return found

    def read_file(self, path_in_crate: str) -> bytes:
        name = self.root_folder + path_in_crate.removeprefix("./")
        return self.zip.read(name)
