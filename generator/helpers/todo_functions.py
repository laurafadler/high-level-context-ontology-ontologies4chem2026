"""
Defines all the functions that are needed for working with the TODO list
"""

import json
from pathlib import Path
from helpers.safe_write import write_atomic
from helpers.entities import as_list


def load_todo_list(path: Path) -> list:
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def add_todo_item(todo_list: list, item: dict):
    # maybe one should check here whether the item exists in the list already
    # IMPORTANT: append only, never re-sort/insert - creation/material_functions.py
    # (add_phases) and creation/phase_functions.py (complete_phases_from_todo) both rely on the
    # same, unchanged order: the "phase_creation:N" number asked there and the "phase:N" number
    # given here later (when the phases are completed) mean the same phase only because this
    # list is never re-sorted. Sorting here would quietly assign stored answers of the answer
    # file to the wrong phase.
    todo_list.append(item)

    return


def delete_todo_entity(todo_list: list, entity: dict) -> bool:
    """Remove the entity with this @id from the todo list.

    Returns True if an entry was removed, False otherwise.
    """
    entity_id = entity.get("@id")
    for i, item in enumerate(todo_list):
        if item.get("@id") == entity_id:
            del todo_list[i]
            return True
    return False


# do I need to save the list at all? Ideally everything written into it is worked through and deleted at some point
def save_todo_list(todo_list: list, path: Path) -> None:
    write_atomic(path, json.dumps(todo_list, indent=2, ensure_ascii=False))

# ---------------------------------------------------------------------------
# Saving
# ---------------------------------------------------------------------------


def merge_todo_lists(todo_list: list, local_todo_list: list) -> list:
    # IMPORTANT: append only (extend), never re-sort - see the comment at add_todo_item.
    # Otherwise "phase_creation:N" (time of creation) and "phase:N" (later completion, see
    # complete_phases_from_todo) drift apart.
    todo_list.extend(local_todo_list)
    return todo_list


def find_todo_items_by_type(todo_list: list, entity_type: str) -> list:
    """
    Searches the to-do list for entries of a particular type.
    """
    matches = []
    for item in todo_list:
        types = as_list(item.get("@type"))
        if entity_type in types:
            matches.append(item)
    return matches

