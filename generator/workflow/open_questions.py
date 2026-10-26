"""
The open questions of an exploratory run, readable: grouped by the thing they
are about, in the order of the sheet, with the place in the setup sheet that answers them -
instead of the answer keys in the driver report.

An exploratory run builds the crate as far as the answer file, the setup sheet and the core files
go; every question nobody could answer gets a stand-in and is listed in the report
(generator/workflow/answer_driver.py --on-unknown log --report <file>). This script reads that list.

With --write-sheet the open questions go into the setup sheet, section "open", each with its key,
the thing it is about, the question, its options and an empty answer - for a person, an agent or a
script to fill in. One place per fact: a question about values ("for which
quantities ...", or a field of a value) becomes an empty value in the section "values" instead -
one per quantity offered, to fill in or delete; its follow-up questions are then answered from it
in one go. A question the sheet has a field of its own for is not written at all; check_sheet.py
names that field when it is empty. The adapter then answers these keys from the sheet (interfaces/eln/adapter.py).
"answer:" without a value is still open (check_sheet.py reports it); "answer: ''" is empty on
purpose (none). A key the section has already is not added again. Answering one question can open
others (a "Yes" brings its follow-up questions) - the next exploratory run shows them.

Usage (from the repository root):
    python generator/workflow/isolated_run.py --answers <empty file> --out %TEMP%/cr_x \\
        -- --setup projects/<crate_identifier>/setup.yaml --on-unknown log --report <report.json>
    python generator/workflow/open_questions.py <report.json> [--write-sheet projects/<crate_identifier>/setup.yaml]
"""
import argparse
import json
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from interfaces.eln.sheet_text import append_to_section  # noqa: E402
from interfaces.eln.adapter import (OCCURRENCES, THING, SetupAdapter, SPECIES_CONCENTRATION_KEY, VALUE_LIST_KEY,  # noqa: E402
                                    VALUE_FIELD_KEY)

SECTION_HEADER = ("open:                                          # open questions of the exploratory run (open_questions.py --write-sheet):\n"
                  "                                               # fill in answer - left empty = still open, '' = none on purpose\n")
_OPTIONS = re.compile(r"\[([^\[\]]*)\](?:\s*\(([^()]*)\))?\s*$")

# Where in the sheet a thing is answered - by the segment of the key.
SHEET_PLACE = {
    "material": "materials (or uncontained_streams) / {name}",
    "phase": "phases / {name}",
    "species": "species {name}",
    "device": "devices / {name}",
    "task": "tasks / {name}",
    "reaction": "reactions / {name}",
    "participant": "participant {name}",
    "environment": "room {name}",
    "phase_interface": "interface {name} (derived)",
    "phase_pair_interface": "interface {name} (derived)",
    "transfer": "transfer {name} (derived)",
}
# What the generator creates itself - no thing of the sheet.
GENERATED_TASKS = {"procedure": "Experimental procedure", "planning": "Planning the series",
                   "establishing": "Establishing the values", "preparation": "Preparation",
                   "main_operation": "Main operation", "workup": "Work-up"}


def _thing(key: str) -> tuple:
    """(experiment number or None, [(level, name), ...]) of the thing a key asks about."""
    segments = key.split("/")[:-1]
    experiment = None
    parts = []
    for segment in segments:
        level, _, name = segment.partition(":")
        if level == "series":
            continue
        if level == "experiment":
            experiment = name
            continue
        if level == "task" and name in GENERATED_TASKS:
            name = GENERATED_TASKS[name]
        elif level == "task" and name.startswith("for-"):
            name = f"(task determining {name[4:].split('_Evidence_')[0].split('_Reference_')[0]})"
        elif level == "task":
            # In the key with underscores, in the sheet with spaces.
            name = name.replace("_", " ")
        parts.append((level, name))
    return experiment, parts


def _place(parts: list) -> str:
    if not parts:
        return "series / setup"
    return " / ".join(SHEET_PLACE.get(level, f"{level} {{name}}").format(name=name) for level, name in parts)


def _question(stand_in: dict) -> str:
    prompt = re.sub(r"^\[hlo:\w+\]\s*", "", stand_in["prompt"]).strip()
    # Shorten long lists of options - the list stands in the report.
    match = re.search(r"\[([^\[\]]*)\](\s*\(.*\))?\s*$", prompt)
    if match and match.group(1).count(",") >= 6:
        options = [o.strip() for o in match.group(1).split(",")]
        prompt = prompt[:match.start()].rstrip() + f" [{', '.join(options[:5])}, ... {len(options)} options]"
    return prompt


def sheet_entry(stand_in: dict) -> dict:
    """An open question as an entry of the section "open" of the sheet."""
    experiment, parts = _thing(stand_in["key"])
    prompt = re.sub(r"^\[hlo:\w+\]\s*", "", stand_in["prompt"]).strip()
    entry = {"key": stand_in["key"], "about": _place(parts) + (f" (experiment {experiment})" if experiment else "")}
    options = stand_in.get("options")
    match = _OPTIONS.search(prompt)
    if match and match.group(1).strip():
        options = options or [o.strip() for o in match.group(1).split(",")]
        prompt = prompt[:match.start()].rstrip()
        if not match.group(2) and "separated by ';'" in prompt:
            # The list hint stands before the options ("Each as 'phase + phase', separated by ';' (leave empty
            # if none) [...]", cross_material_pairs) - a list all the same.
            entry["several"] = True
            if "leave empty" not in prompt:
                entry["required"] = True
        elif match.group(2) and ("several" in match.group(2) or "separated" in match.group(2)):
            entry["several"] = True
            if "leave empty" not in match.group(2):
                # A list that must name at least one (ask_user_list, required): '' is no answer, close_sheet.py
                # leaves it open (crossing_stream_phases).
                entry["required"] = True
    entry["question"] = prompt
    if options:
        entry["options"] = [str(o).split(":", 1)[-1] if str(o).startswith(("unit:", "cpo:", "hlo:")) else str(o) for o in options]
    entry["answer"] = None
    entry["source"] = None
    return entry


VALUES_HEADER = ("values:                                        # values: pre-filled from the ELN (prefill_sheet.py), as an empty scaffold\n"
                 "                                               # (open_questions.py) and by hand; kind (measured, planned ...) is set by a person\n")


def _skeletons(stand_in: dict, adapter, present: set) -> list:
    """Empty values for a question about values: per quantity offered (a list) or for the quantity
    asked about (a field of a value); at series level for every experiment when the list asks what
    is known in them."""
    match = VALUE_LIST_KEY.fullmatch(stand_in["key"]) or VALUE_FIELD_KEY.fullmatch(stand_in["key"])
    concentration = match is None
    if concentration:
        # The concentration of a species: asked at the species itself, without "concentration/".
        match = SPECIES_CONCENTRATION_KEY.fullmatch(stand_in["key"])
    at, of = adapter.sheet_at(match.group("path"))
    if concentration:
        quantities = ["concentration"]
    elif "quantity" in match.groupdict():
        quantities = [match.group("quantity")]
    else:
        prompt = re.sub(r"^\[hlo:\w+\]\s*", "", stand_in["prompt"])
        found = _OPTIONS.search(prompt)
        quantities = [o.strip() for o in found.group(1).split(",")] if found else []
    if match.group("exp"):
        experiments = [int(match.group("exp"))]
    elif stand_in["key"].endswith("known_per_experiment"):
        experiments = list(range(1, adapter.experiment_count + 1))
    else:
        experiments = [None]
    entries = []
    for quantity in quantities:
        for experiment in experiments:
            identity = (_norm(at), _norm(of), str(experiment or ""), _norm(quantity))
            if identity in present:
                continue
            present.add(identity)
            entry = {"at": at}
            if of:
                entry["of"] = of
            if experiment:
                entry["experiment"] = experiment
            entry.update({"quantity": quantity, "value": None, "unit": None, "kind": None, "determined_by": None, "source": None})
            if quantity == "concentration":
                # Mass, mole or volume fraction ... - the generator asks for the kind otherwise.
                entry = {**{k: v for k, v in entry.items() if k != "source"}, "quantity_kind": None, "source": None}
            entries.append(entry)
    return entries


def _norm(text) -> str:
    return "".join(c for c in str(text or "").lower() if c.isalnum())


# Occurrences and times: an open list becomes an empty entry in "occurrences" (about
# which things is anything known?) or empty values in "values" (the times of a task or of an occurrence).
OCCURRENCES_HEADER = ("occurrences:                                   # what is known about occurrences: per statement the things,\n"
                      "                                               # how often, how it is known (kind) and which task established it\n")
OCCURRENCE_LIST = re.compile(OCCURRENCES + r"(?P<list>phases|interfaces|reactions|energy_fields|transfer_places)")
OCCURRENCE_TRANSFERS = re.compile(OCCURRENCES + r"place:(?P<place>[^/]+)/transfers")
TASK_TIME_LIST = re.compile(r"series:1/experiment:(?P<exp>\d+)/task:(?P<task>[^/]+)/quantities_with_(?:evidence|reference)")
OCCURRENCE_TIME_LIST = re.compile(OCCURRENCES + THING + r"/occurrence:(?P<k>\d+)/quantities_with_(?:evidence|reference)")


def _offered(stand_in: dict) -> list:
    prompt = re.sub(r"^\[hlo:\w+\]\s*", "", stand_in["prompt"])
    found = _OPTIONS.search(prompt)
    return stand_in.get("options") or ([o.strip() for o in found.group(1).split(",")] if found else [])


def _occurrence_skeleton(stand_in: dict, present: set) -> list:
    """An empty statement for an open list "which ... do we know anything about": the things the
    generator offered under "offered", to move into the list."""
    found = OCCURRENCE_LIST.fullmatch(stand_in["key"]) or OCCURRENCE_TRANSFERS.fullmatch(stand_in["key"])
    nr = int(found.group("exp"))
    # null = still open (not "[]" - that would mean: nothing known; only a person says that).
    if "place" in found.groupdict() and found.group("place"):
        field, things = "transfers", {found.group("place"): None}
    elif found.group("list") == "transfer_places":
        field, things = "transfers", None
    else:
        field, things = found.group("list"), None
    identity = (field, str(found.groupdict().get("place") or ""), nr)
    if identity in present:
        return []
    present.add(identity)
    return [{field: things, "experiment": nr, "count": None, "kind": None, "determined_by": None,
             "offered": _offered(stand_in), "source": None}]


def _time_skeletons(stand_in: dict, adapter, present: set) -> list:
    """Empty time values for an open list of the times of a task or of an occurrence."""
    key = stand_in["key"]
    task = TASK_TIME_LIST.fullmatch(key)
    entries = []
    named = set()
    if task:
        name, entry = adapter._sheet_task(task.group("task"))
        base = {"at": f"task:{entry['name'] if entry else name}", "experiment": int(task.group("exp"))}
        # Not again what the sheet names already - also in 'times' at the task (the start of the
        # experimental procedure) or under 'unknown'.
        named = adapter.task_times_named(key) or set()
    else:
        found = OCCURRENCE_TIME_LIST.fullmatch(key)
        kind = "transfer" if found.group("transfer") else found.group("simple")
        base = {"at": f"{kind}:{found.group('transfer') or found.group('label')}"}
        if found.group("place"):
            base["place"] = found.group("place")
        base.update({"occurrence": int(found.group("k")), "experiment": int(found.group("exp"))})
    for quantity in _offered(stand_in):
        identity = (_norm(base["at"]), _norm(base.get("place")), str(base.get("occurrence") or ""),
                    str(base["experiment"]), _norm(quantity))
        if identity in present or _norm(quantity) in named:
            continue
        present.add(identity)
        entries.append(dict(base, quantity=quantity, value=None, unit=None, kind=None, determined_by=None, source=None))
    return entries


def write_sheet(stand_ins: list, sheet: Path) -> tuple:
    """(open questions added, empty values added, keys with a field of their own)."""
    adapter = SetupAdapter(sheet, Path(__file__).resolve().parents[2])
    data = yaml.safe_load(sheet.read_text(encoding="utf-8")) or {}
    present = {str(e.get("key")) for e in data.get("open") or [] if isinstance(e, dict)}
    values_present = {(_norm(v.get("at")), _norm(v.get("of")), str(v.get("experiment") or ""), _norm(v.get("quantity")))
                      for v in data.get("values") or [] if isinstance(v, dict)}
    values_present |= {(_norm(u.get("at")), _norm(u.get("of")), str(u.get("experiment") or ""), _norm(quantity))
                       for u in data.get("unknown") or [] if isinstance(u, dict) for quantity in u.get("none") or []}
    questions, skeletons, own, statements, times = [], [], [], [], []
    occurrences_present = set()
    for statement in data.get("occurrences") or []:
        if isinstance(statement, dict):
            for field in ("phases", "interfaces", "reactions", "energy_fields", "transfers"):
                if field in statement:
                    places = statement[field] if field == "transfers" and isinstance(statement[field], dict) else {"": None}
                    for place in places or {"": None}:
                        occurrences_present.add((field, str(place), statement.get("experiment")))
    times_present = {(_norm(v.get("at")), _norm(v.get("place")), str(v.get("occurrence") or ""), str(v.get("experiment") or ""),
                      _norm(v.get("quantity"))) for v in data.get("values") or [] if isinstance(v, dict)}
    for stand_in in stand_ins:
        key = stand_in["key"]
        if OCCURRENCE_LIST.fullmatch(key) or OCCURRENCE_TRANSFERS.fullmatch(key):
            statements += _occurrence_skeleton(stand_in, occurrences_present)
        elif TASK_TIME_LIST.fullmatch(key) or OCCURRENCE_TIME_LIST.fullmatch(key):
            times += _time_skeletons(stand_in, adapter, times_present)
        elif VALUE_LIST_KEY.fullmatch(key) or VALUE_FIELD_KEY.fullmatch(key) or SPECIES_CONCENTRATION_KEY.fullmatch(key):
            skeletons += _skeletons(stand_in, adapter, values_present)
        elif adapter.own_field(key):
            own.append(key)
        elif key not in present:
            questions.append(sheet_entry(stand_in))
    append_to_section(sheet, "values", VALUES_HEADER, skeletons + times)
    append_to_section(sheet, "occurrences", OCCURRENCES_HEADER, statements)
    append_to_section(sheet, "open", SECTION_HEADER, questions)
    return len(questions), len(skeletons) + len(times) + len(statements), own


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("report", type=Path)
    parser.add_argument("--write-sheet", type=Path, help="append the open questions to this setup sheet (section 'open')")
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    stand_ins = report.get("stand_ins", [])
    print(f"Run: {report.get('status')}")
    if not stand_ins:
        print("No open questions - every question was answered.")
        return 0

    groups = {}
    for stand_in in stand_ins:
        experiment, parts = _thing(stand_in["key"])
        place = _place(parts) + (f"   (experiment {experiment})" if experiment else "")
        groups.setdefault(place, []).append(stand_in)

    print(f"Open questions: {len(stand_ins)} at {len(groups)} places\n")
    if args.write_sheet:
        questions, skeletons, own = write_sheet(stand_ins, args.write_sheet)
        print(f"Written to {args.write_sheet}: {questions} open question(s) (section 'open'), {skeletons} empty value(s) "
              f"or statement(s) (sections 'values', 'occurrences'). {len(own)} question(s) have a field of their own in the sheet - "
              f"check_sheet.py names it when it is empty:")
        for key in own:
            print(f"  - {key}")
        print()
    for place, items in groups.items():
        print(place)
        for stand_in in items:
            print(f"  - {_question(stand_in)}")
            print(f"      key: {stand_in['key']}")
        print()
    return 1


if __name__ == "__main__":
    sys.exit(main())
