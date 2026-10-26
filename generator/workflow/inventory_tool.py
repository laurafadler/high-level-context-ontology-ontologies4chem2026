"""
Writes into the chemical inventory:
the containers into the device library,
their contents and what happens to them into the material library (rule 2.15). What happens to a
container outside an experiment is entered here, not by a run (withdrawals outside experiments are
made by library tools).

    prepare SPEC.json   a container filled in the lab - preparation task, transfers from the source
                        containers, content with lot and acquisition (helpers/inventory_entries.py:
                        prepared_container); the preparation is sorted into the usage history of every
                        source container by time. With "container" in the spec (rule 2.15) a container
                        that is there already is filled again - only if its last content ended: the new
                        content becomes its current one and the last of its history.
    dispose CONTAINER   the content of a container is used up or disposed of outside an experiment:
                        a task task:disposing_<name>, whose end becomes the end of the content's
                        acquisition occurrence (helpers/inventory_state.py); the container no longer
                        contains it (it stays in its history).

Changes the files only; commit them yourself (a run refuses to start with uncommitted libraries).

Run from the repository root:
    python generator/workflow/inventory_tool.py prepare spec.json
    python generator/workflow/inventory_tool.py dispose device:stock_solution_01 --start 2026-10-05T09:00:00Z
        --end 2026-10-05T09:10:00Z --description "Poured into the solvent waste." --person person:<ID>
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import path_definitions  # noqa: E402
from creation.device_usage_functions import _Moments, _sort_in  # noqa: E402
from helpers.entities import find_entity, ref_ids  # noqa: E402
from helpers.file_handling import save_jsonld
from helpers.inventory_entries import Entries, prepared_container, ref  # noqa: E402
from helpers.inventory_state import (content_end, content_occurrence_of, fill_content, release_content,  # noqa: E402
                                     set_content_end)
from helpers.library_functions import load_device_libraries  # noqa: E402


def sort_into_history(container: dict, task_id: str, view: dict):
    """Sort a library task into the usage history of a library container by time; the pointers to
    the last use follow when it is the latest (rule 5.4)."""
    moments = _Moments({"@graph": []}, view)
    history = _sort_in(container["@id"], ref_ids(container.get("cpo:hasUsageHistory")), task_id, moments)
    container["cpo:hasUsageHistory"] = [ref(i) for i in history]
    if history[-1] == task_id:
        container["cpo:lastUsedPurpose"] = ref(task_id)
        container["cpo:lastUsedTime"] = ref(f"{task_id}_EndTime")


def prepare(spec_path: Path):
    """SPEC (JSON): {"name", "label", "template", "cavity", "cabinet", "person",
    "content": {"label", "state", "lot", "species": [[chem, name, fraction], ...], "solid_structure"?},
    "sources": [{"container", "phase", "volume_m3"?}, ...],
    "preparation": {"name", "description", "functions": [...], "start", "end"}}
    or, to fill a container that is there already (rule 2.15): "container": "device:..." and "cavity"
    (its cavity form) instead of "label", "template" and "cabinet"; "name" then names the content."""
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    view, documents = load_device_libraries()
    existing = None
    if spec.get("container"):
        existing = find_entity(view, spec["container"])
        if existing is None:
            raise SystemExit(f"{spec['container']} is not in the device library.")
        current = content_occurrence_of(existing, view)
        if existing.get("cpo:containsMaterial") and (current is None or not content_end(current)):
            raise SystemExit(f"{spec['container']} still holds {existing['cpo:containsMaterial']['@id']} - dispose of it "
                             f"first (dispose), then fill it again.")
        if find_entity(view, f"material:{spec['name']}_Content") is not None:
            raise SystemExit(f"material:{spec['name']}_Content exists already - choose another name for the content.")
    elif find_entity(view, f"device:{spec['name']}") is not None:
        raise SystemExit(f"device:{spec['name']} exists already.")
    lib = Entries(times_task_id="unused", stamp="unused", person=spec["person"])
    content = dict(spec["content"], species=[tuple(s) for s in spec["content"]["species"]])
    task_id = prepared_container(lib, spec["name"], spec.get("label"), spec.get("template"), spec["cavity"],
                                 spec.get("cabinet"), content, spec["sources"], spec["preparation"],
                                 container_id=spec.get("container"))
    device_items, material_items = lib.split()
    documents[path_definitions.DEVICE_LIBRARY_PATH]["@graph"].extend(device_items)
    documents[path_definitions.MATERIAL_LIBRARY_PATH]["@graph"].extend(material_items)
    view["@graph"].extend(lib.items)
    for source in spec["sources"]:
        container = find_entity(view, source["container"])
        if container is None:
            raise SystemExit(f"source container {source['container']} is not in the device library.")
        sort_into_history(container, task_id, view)
    if existing is not None:
        # The existing vessel gets the new content as the current and last one in the history (rule 2.15).
        fill_content(existing, f"material:{spec['name']}_Content")
        sort_into_history(existing, task_id, view)
    for path, document in documents.items():
        save_jsonld(document, path)
    target = spec.get("container") or f"device:{spec['name']}"
    print(f"[inventory] {len(lib.items)} entities for {target} written; preparation {task_id} "
          f"sorted into the usage history of {len(spec['sources'])} source container(s). Commit the libraries.")


def dispose(container_id: str, start: str, end: str, description: str, person: str):
    view, documents = load_device_libraries()
    container = find_entity(view, container_id)
    if container is None:
        raise SystemExit(f"{container_id} is not in the device library.")
    occurrence = content_occurrence_of(container, view)
    if occurrence is None:
        raise SystemExit(f"the content of {container_id} has no acquisition occurrence.")
    name = container_id.split(":", 1)[1]
    task_id = f"task:disposing_{name}"
    if find_entity(view, task_id) is not None:
        raise SystemExit(f"{task_id} exists already - the content was disposed of before.")
    lib = Entries(times_task_id="unused", stamp="unused", person=person)
    determined = [lib.instant(f"{task_id}_StartTime", "Evidence", "hlo:Observed", start, "Start of the disposal, from the lab notebook.", task_id),
                  lib.instant(f"{task_id}_EndTime", "Evidence", "hlo:Observed", end, "End of the disposal, from the lab notebook. The content no longer exists from here on.", task_id)]
    lib.add({"@id": f"{task_id}_Duration", "@type": ["time:Duration", "hlo:Fixed", "hlo:Actual"]})
    lib.items.insert(0, {"@id": task_id, "@type": ["cpo:OperationTask", "hlo:Fixed"], "schema:name": f"Disposing of the content of {name}",
                         "schema:description": description, "cpo:performedBy": [ref(person)],
                         "cpo:hasStartTime": ref(f"{task_id}_StartTime"), "cpo:hasEndTime": ref(f"{task_id}_EndTime"),
                         "cpo:hasDuration": ref(f"{task_id}_Duration"), "cpo:usedEquipment": [ref(container_id)],
                         "cpo:realizesFunction": [ref("cpo:Discharging")], "cpo:determines": [ref(i) for i in determined]})
    # Booking out concerns the content: Material Library.
    documents[path_definitions.MATERIAL_LIBRARY_PATH]["@graph"].extend(lib.items)
    view["@graph"].extend(lib.items)
    set_content_end(occurrence, f"{task_id}_EndTime", view, documents)
    # Booked out: the container no longer contains it, it stays in the history (rule 2.15).
    release_content(container, find_entity(view, container["cpo:containsMaterial"]["@id"]))
    sort_into_history(container, task_id, view)
    for path, document in documents.items():
        save_jsonld(document, path)
    print(f"[inventory] content of {container_id} ends with {task_id} ({end}). Commit the libraries.")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("spec", type=Path)
    d = sub.add_parser("dispose")
    d.add_argument("container")
    d.add_argument("--start", required=True)
    d.add_argument("--end", required=True)
    d.add_argument("--description", required=True)
    d.add_argument("--person", required=True, help="who disposed of it, as an ID of the People Library (person:...)")
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.spec)
    else:
        dispose(args.container, args.start, args.end, args.description, args.person)


if __name__ == "__main__":
    main()
