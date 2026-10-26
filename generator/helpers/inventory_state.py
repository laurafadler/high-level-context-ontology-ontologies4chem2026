"""
The state of a content of the chemical inventory (rule 7.17): its acquisition occurrence and
when it ended - used up or disposed of. Shared by the inventory tool (workflow/inventory_tool.py)
and the run (an experiment that empties a container, creation/device_usage_functions.py).

The end of a content is the cpo:hasEndTime of its acquisition occurrence: the same time:Instant as
the end of the task that used it up or disposed of it (rule 7.17). Until then it points at an empty
Actual of its own (<occurrence>_EndTime), which is put back when the end is taken out again.

A device of the library can hold several contents one after the other (rule 2.15):
cpo:hasContainedMaterialHistory lists them all, cpo:containsMaterial and cpo:materialContainedIn only
the current one. When a content ends, its device no longer contains it (release_content); when the
end is taken out again, it is put back (restore_content) - at its old place in both entries, so that
the files are byte for byte what they were.
"""
from helpers.entities import find_entity, as_list, ref_id, ref_ids


def content_history(device: dict) -> list:
    """Every content a library device has held, in the order filled in (the current one last, unless
    it ended). A device written before the history existed names only its current content."""
    return ref_ids(device.get("cpo:hasContainedMaterialHistory")) or ref_ids(device.get("cpo:containsMaterial"))


def occurrence_of_content(material_id: str, view: dict) -> dict | None:
    """The acquisition occurrence of a content: the Fixed occurrence of a phase of it (None if there is none)."""
    material = find_entity(view, material_id) or {}
    for phase_id in ref_ids(material.get("dcterms:hasPart")):
        phase = find_entity(view, phase_id) or {}
        for occurrence_id in ref_ids(phase.get("cpo:hasOccurrence")):
            occurrence = find_entity(view, occurrence_id)
            if occurrence is not None and "hlo:Fixed" in as_list(occurrence.get("@type")):
                return occurrence
    return None


def content_occurrence_of(container: dict, view: dict) -> dict | None:
    """The acquisition occurrence of a container's current content (None if it is empty or the
    content has none)."""
    for material_id in ref_ids(container.get("cpo:containsMaterial")):
        occurrence = occurrence_of_content(material_id, view)
        if occurrence is not None:
            return occurrence
    return None


def crate_library_content(device: dict, datagraph: dict, history: list) -> str | None:
    """Which content of its library twin a device of the crate drew from: its content in the crate
    goes back through hlo:specializationOf (experiment -> series -> library) to one of history."""
    for content_id in ref_ids(device.get("cpo:containsMaterial")):
        seen = set()
        while content_id and content_id not in seen:
            if content_id in history:
                return content_id
            seen.add(content_id)
            content_id = ref_id((find_entity(datagraph, content_id) or {}).get("hlo:specializationOf"))
    return None


def _placeholder_id(occurrence: dict) -> str:
    return f"{occurrence['@id']}_EndTime"


def content_end(occurrence: dict) -> str | None:
    """The instant the content ended at, or None while it exists (the end is the empty placeholder)."""
    end = ref_id(occurrence.get("cpo:hasEndTime"))
    return None if end in (None, _placeholder_id(occurrence)) else end


def _document_of(entity_id: str, documents: dict) -> dict | None:
    for document in documents.values():
        if find_entity(document, entity_id) is not None:
            return document
    return None


def set_content_end(occurrence: dict, instant_id: str, view: dict, documents: dict):
    """Let the content end at instant_id: the occurrence points at it, the empty placeholder goes."""
    placeholder = _placeholder_id(occurrence)
    if ref_id(occurrence.get("cpo:hasEndTime")) == placeholder:
        for graph in [document["@graph"] for document in documents.values()] + [view["@graph"]]:
            graph[:] = [e for e in graph if e.get("@id") != placeholder]
    occurrence["cpo:hasEndTime"] = {"@id": instant_id}


def clear_content_end(occurrence: dict, view: dict, documents: dict):
    """Take an end out again (a crate built anew, rule 5.4): back to the empty placeholder."""
    placeholder = _placeholder_id(occurrence)
    occurrence["cpo:hasEndTime"] = {"@id": placeholder}
    if find_entity(view, placeholder) is None:
        entity = {"@id": placeholder, "@type": ["time:Instant", "hlo:Fixed", "hlo:Actual"]}
        document = _document_of(occurrence["@id"], documents)
        graph = document["@graph"]
        # Back in its place (as content_occurrence creates it: before the duration), so that the file
        # is byte for byte the old one after taking it out.
        ids = [e.get("@id") for e in graph]
        duration = f"{occurrence['@id']}_Duration"
        position = ids.index(duration) if duration in ids else ids.index(occurrence["@id"]) + 1
        graph.insert(position, entity)
        view["@graph"].append(entity)


def _insert_before(entity: dict, key: str, value, before: str):
    """Put key into entity right before the key 'before' (at the end if there is none) - in place,
    so that the dict keeps its identity in the view and in its document."""
    items = [(k, v) for k, v in entity.items() if k != key]
    position = next((i for i, (k, _) in enumerate(items) if k == before), len(items))
    items.insert(position, (key, value))
    entity.clear()
    entity.update(items)


def release_content(device: dict, material: dict):
    """The content ended: the device no longer contains it, and it no longer says where it is
    (rule 2.15). It stays in the device's history."""
    if material["@id"] in ref_ids(device.get("cpo:containsMaterial")):
        device.pop("cpo:containsMaterial")
    if device["@id"] in ref_ids(material.get("cpo:materialContainedIn")):
        material.pop("cpo:materialContainedIn")


def restore_content(device: dict, material: dict):
    """The end of the content was taken out again: if it is the last of the history and the device
    holds nothing else, it is the current content again - both links back at their places (as the
    helpers in helpers/inventory_entries.py write them: before the history, before the form)."""
    history = content_history(device)
    if device.get("cpo:containsMaterial") or not history or history[-1] != material["@id"]:
        return
    _insert_before(device, "cpo:containsMaterial", {"@id": material["@id"]}, "cpo:hasContainedMaterialHistory")
    if "cpo:materialContainedIn" not in material:
        _insert_before(material, "cpo:materialContainedIn", {"@id": device["@id"]}, "cpo:fillsForm")


def fill_content(device: dict, material_id: str):
    """A new content goes into the device (a preparation into a container that is there already):
    it becomes the current content and the last of the history."""
    history = content_history(device)
    _insert_before(device, "cpo:hasContainedMaterialHistory", [{"@id": i} for i in history + [material_id]],
                   "cpo:hasUsageHistory")
    _insert_before(device, "cpo:containsMaterial", {"@id": material_id}, "cpo:hasContainedMaterialHistory")
