"""
eLabFTW profile: everything is in the RO-Crate graph. Records are experiments and resources
(genre), with a body text in HTML, ordered steps (HowToStep), comments, files and free fields
(PropertyValue). Free fields are named differently in every instance - which of them mean
something for us is a mapping table per instance (FIELD_MAP), empty for the demo export.
"""
from interfaces.eln.core import new_core, quantity
from interfaces.eln.reader import html_to_text, as_list

# eLabFTW field name -> (core field, property). To be maintained per instance; the demo has no chemistry fields.
FIELD_MAP = {}


def matches(archive) -> bool:
    return (archive.producer().get("name") or "").lower().startswith("elabftw")


def to_core(archive, record) -> dict:
    producer = archive.producer()
    core = new_core("eLabFTW", producer.get("version"), archive.path.name, record.get("identifier") or record["@id"],
                    record.get("url"))
    status = record.get("creativeWorkStatus")
    core["experiment"] = {
        "title": record.get("name"),
        "status": status,
        # The list of status words is set, not given by the ELN (rule P-EL2). Without a status
        # (Lennard's export, eLabFTW 6.0.5) it is open whether the experiment is completed - None.
        "completed": status.lower() in ("success", "completed", "finished") if status else None,
        # eLabFTW 6 writes under "status" the state of the entry (Normal, Archived, Deleted), not the
        # status of the experiment - checked against Lennard's export, whose own JSON output has "state: 1".
        "entry_state": record.get("status"),
        "entry_created": record.get("dateCreated"),
        "entry_modified": record.get("dateModified"),
        # With "temporal" eLabFTW has the date of the experiment itself - unlike AI4Green.
        "experiment_date": record.get("temporal"),
        "description_text": html_to_text(record.get("text", "")),
        "keywords": [k.strip() for k in (record.get("keywords") or "").split(",") if k.strip()],
        "genre": record.get("genre"),
    }
    if record.get("author"):
        person = archive.person(record["author"])
        person["role"] = "author"
        core["people"].append(person)

    core["procedure"] = {"text": core["experiment"]["description_text"], "steps": archive.steps(record)}
    core["notes"] = archive.comments(record)
    core["files"] = archive.files(record)

    unmapped = []
    for field in archive.properties(record):
        if field["name"] == "elabftw_metadata":
            continue
        target = FIELD_MAP.get(field["name"])
        if target:
            section, prop = target
            core[section].append({"property": prop, "value": quantity(field["value"], field["unit"]), "text": field["name"]})
        else:
            unmapped.append(field)
    mentions = [archive.get(m) for m in as_list(record.get("mentions"))]
    core["unmapped"] = {"free_fields": unmapped,
                        "linked_records": [{"id": m.get("@id"), "name": m.get("name")} for m in mentions if m]}
    return core
