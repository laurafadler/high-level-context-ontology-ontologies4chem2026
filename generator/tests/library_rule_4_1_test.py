"""
Counter-check (rule 7.14) for the rule 4.1 check in check_library_consistency.py
(_rule_4_1_problems): each case damages ONE entry in an in-memory copy of the real libraries
and expects exactly that entry to be reported under exactly the expected problem kind.

A check that reports nothing proves nothing on its own - it may simply not look.

Reads the libraries, changes no files.

Run from the repository root:
    PYTHONPATH=. python generator/tests/library_rule_4_1_test.py
"""
import copy

# Runs from generator/tests/ - the generator has to be on the search path.
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from workflow.check_library_consistency import LIBRARY_FILES, _entities, _ref_ids, _rule_4_1_problems
from helpers.file_handling import load_jsonld

# An assumed value with a task in the Device Library serves as the test object; the task names it in
# cpo:determines, it hangs as the first reference at its variable (as of).
VALUE_ID = "device:vessel001_InnerDiameter_Reference_1"
OWNER_ID = "device:vessel001_InnerDiameter"
OTHER_VARIABLE_ID = "device:vessel001_InnerHeight"


def _find(libraries: dict, entity_id: str) -> dict:
    for data in libraries.values():
        for entity in _entities(data):
            if entity.get("@id") == entity_id:
                return entity
    raise KeyError(entity_id)


def _drop_task(libraries):
    del _find(libraries, VALUE_ID)["cpo:hasDeterminationTask"]


def _point_to_missing_task(libraries):
    _find(libraries, VALUE_ID)["cpo:hasDeterminationTask"] = {"@id": "task:does_not_exist"}


def _drop_from_determines(libraries):
    task = _find(libraries, _ref_ids(_find(libraries, VALUE_ID)["cpo:hasDeterminationTask"])[0])
    task["cpo:determines"] = [ref for ref in task["cpo:determines"] if ref["@id"] != VALUE_ID]


def _task_names_foreign_value(libraries):
    # The task of another value names VALUE_ID in addition - but the value does not point back.
    task = _find(libraries, "task:looking_up_soda_lime_glass_density")
    task["cpo:determines"] = task["cpo:determines"] + [{"@id": VALUE_ID}]


def _detach(libraries):
    owner = _find(libraries, OWNER_ID)
    del owner["hlo:hasReference"]


def _moved_to_other_variable(libraries):
    # The value now hangs at another variable - but its ID still names the old one.
    _detach(libraries)
    other = _find(libraries, OTHER_VARIABLE_ID)
    other["hlo:hasReference"] = [{"@id": ref} for ref in _ref_ids(other.get("hlo:hasReference"))] + [{"@id": VALUE_ID}]


def _drop_type(libraries):
    del _find(libraries, VALUE_ID)["hlo:hasReferenceType"]


def _value_on_actual(libraries):
    _find(libraries, VALUE_ID)["@type"] = ["cpo:ProcessVariable", "hlo:Actual"]


CASES = [
    # (description, damage, expected messages)
    # If the reference at the value is missing, the inverse is broken too: the task still names it.
    ("task missing at the value", _drop_task, {"without cpo:hasDeterminationTask",
                                        "value does not name the task in cpo:hasDeterminationTask"}),
    ("task does not exist", _point_to_missing_task, {"determination task missing",
                                                      "value does not name the task in cpo:hasDeterminationTask"}),
    ("task does not name the value", _drop_from_determines, {"task does not name the value in cpo:determines"}),
    ("value does not name the task", _task_names_foreign_value, {"value does not name the task in cpo:hasDeterminationTask"}),
    ("value at no variable", _detach, {"not attached to exactly one variable"}),
    ("ID names another variable", _moved_to_other_variable, {"ID does not follow <variable>_<Evidence|Reference>_<n>"}),
    ("type missing", _drop_type, {"without hlo:hasEvidenceType/hlo:hasReferenceType"}),
    ("value at the actual", _value_on_actual, {"value on an Actual"}),
]


def _rows(problems: dict) -> set:
    return {(kind, entity_id, detail) for kind, rows in problems.items() for _, entity_id, detail in rows}


def run():
    libraries = {name: load_jsonld(path) for name, path in LIBRARY_FILES.items()}
    baseline = _rows(_rule_4_1_problems(libraries))
    print(f"Messages in the unchanged state: {len(baseline)}")

    ok = True
    for label, damage, expected_kinds in CASES:
        broken = copy.deepcopy(libraries)
        damage(broken)
        new = _rows(_rule_4_1_problems(broken)) - baseline
        # Exactly the expected messages about the test object, and nothing else besides.
        passed = {kind for kind, _, _ in new} == expected_kinds and all(entity_id == VALUE_ID for _, entity_id, _ in new)
        if not passed:
            ok = False
        print(f"  {label:28s} [{'OK' if passed else 'WRONG'}]" + ("" if passed else f"  new: {sorted(new)}"))

    print("\nRESULT:", "OK" if ok else "FAILED")
    return ok


if __name__ == "__main__":
    raise SystemExit(0 if run() else 1)
