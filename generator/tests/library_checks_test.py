"""
Counter-check (rule 7.14) for three checks of generator/workflow/check_library_consistency.py: usage histories start with a commissioning (rule 5.5), CAS check digits (rule 2.8), IDs in
the crates (rules 1.2, 2.1). Each case damages ONE entry of an in-memory copy of the libraries or of the
amidation crate and expects exactly one more finding; the undamaged data has none. Writes nothing.

Run from the repository root:
    python generator/tests/library_checks_test.py
"""
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from helpers.file_handling import load_jsonld  # noqa: E402
from workflow.check_library_consistency import (LIBRARY_FILES, _cas_problems, _crate_id_problems,  # noqa: E402
                                                _device_classes, _entities, _types, _usage_history_problems)

LIBRARIES = {name: load_jsonld(path) for name, path in LIBRARY_FILES.items()}
CRATE = {"amidation": load_jsonld(Path("projects/amidation_ai4green_ai4_001/crate_completed/ro-crate-metadata.json"))}


def entity(libraries, entity_id):
    return next(e for data in libraries.values() for e in _entities(data) if e.get("@id") == entity_id)


def drop_history(libs):
    del entity(libs, "device:flask_50mL_01")["cpo:hasUsageHistory"]


def history_without_commissioning(libs):
    flask = entity(libs, "device:flask_50mL_01")
    flask["cpo:hasUsageHistory"] = flask["cpo:hasUsageHistory"][1:] or [{"@id": "crate:x/Task_y"}]


def template_without_history(libs):
    # A template has no use - no message.
    entity(libs, "device:round_bottom_flask_50mL").pop("cpo:hasUsageHistory", None)


def wrong_check_digit(libs):
    entity(libs, "chem:Molecule_0014")["cpo:hasCAS"] = "65-85-1"


def wrong_format(libs):
    entity(libs, "chem:Molecule_0015")["cpo:hasCAS"] = "75047"


def hash_id(crates):
    crates["amidation"]["@graph"].append({"@id": "#CleaningProcedure", "@type": "cpo:Task"})


def copied_library_entry(crates):
    crates["amidation"]["@graph"].append({"@id": "chem:Molecule_0014", "@type": "chebi:Molecule"})


def snapshot_entry(crates):
    # The ontology snapshot stands in the crate on purpose - no message.
    crates["amidation"]["@graph"].append({"@id": "ontology:cpo", "@type": "schema:Dataset"})


ok = True


def check(label, got, wanted):
    global ok
    good = got == wanted
    ok &= good
    print(f"  {label:40s} [{'OK' if good else 'WRONG'}] {got}")


devices = _device_classes()
checked = [e["@id"] for data in LIBRARIES.values() for e in _entities(data) if set(_types(e)) & devices]
check("devices found in the libraries (> 20)", len(checked) > 20, True)
base = (len(_usage_history_problems(LIBRARIES)), len(_cas_problems(LIBRARIES)), len(_crate_id_problems(LIBRARIES, CRATE)))
check("undamaged: no finding", base, (0, 0, 0))
for label, damage, function in [
    ("device without a usage history", drop_history, _usage_history_problems),
    ("history not starting with a commissioning", history_without_commissioning, _usage_history_problems),
    ("template without a history", template_without_history, _usage_history_problems),
    ("CAS with a wrong check digit", wrong_check_digit, _cas_problems),
    ("CAS in a wrong format", wrong_format, _cas_problems),
]:
    libs = copy.deepcopy(LIBRARIES)
    damage(libs)
    wanted = 0 if damage is template_without_history else 1
    check(label, len(function(libs)), wanted)
for label, damage, wanted in [("an ID of the form #...", hash_id, 1), ("a copied library entry", copied_library_entry, 1),
                              ("an entry of the ontology snapshot", snapshot_entry, 0)]:
    crates = copy.deepcopy(CRATE)
    damage(crates)
    check(label, len(_crate_id_problems(LIBRARIES, crates)), wanted)
print("RESULT:", "OK" if ok else "FAILED")
raise SystemExit(0 if ok else 1)
