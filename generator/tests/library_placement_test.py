"""
Counter-check (rule 7.14) for two sections of workflow/check_library_consistency.py (rule 2.15): "Devices and contents apart" (_placement_problems) and "Contents of devices - current
one and history" (_content_history_problems). Each fault is planted in memory in the libraries as
they are; each must be reported, the untouched libraries and a cleanly emptied bottle must not.
Writes nothing.

Run from the repository root (a few seconds):
    python generator/tests/library_placement_test.py
"""
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "workflow"))
import check_library_consistency as c  # noqa: E402
from helpers.file_handling import load_jsonld  # noqa: E402

BASE = {name: load_jsonld(path) for name, path in c.LIBRARY_FILES.items()}
ISOPROPANOL = "device:bottle_isopropanol_70_01"
ISOPROPANOL_CONTENT = "material:bottle_isopropanol_70_01_Content"
PLATINUM_CONTENT = "material:bottle_platinum_01_Content"


def find(libs, entity_id):
    for name, data in libs.items():
        for entity in data.get("@graph", []):
            if entity.get("@id") == entity_id:
                return name, entity
    raise KeyError(entity_id)


def move(entity_id, to):
    def mutate(libs):
        name, entity = find(libs, entity_id)
        libs[name]["@graph"].remove(entity)
        libs[to]["@graph"].append(entity)
    return mutate


def drop(entity_id, key):
    def mutate(libs):
        find(libs, entity_id)[1].pop(key)
    return mutate


def end_occurrence(content_id, instant_id):
    def mutate(libs):
        find(libs, f"{content_id}_Phase_Occurrence")[1]["cpo:hasEndTime"] = {"@id": instant_id}
    return mutate


def second_content(ended_at=None):
    """The isopropanol bottle held the platinum content after its own (a test): the platinum content
    is its current one; the isopropanol content ended at ended_at (or not at all)."""
    def mutate(libs):
        bottle = find(libs, ISOPROPANOL)[1]
        bottle["cpo:hasContainedMaterialHistory"] = [{"@id": ISOPROPANOL_CONTENT}, {"@id": PLATINUM_CONTENT}]
        bottle["cpo:containsMaterial"] = {"@id": PLATINUM_CONTENT}
        find(libs, PLATINUM_CONTENT)[1]["cpo:materialContainedIn"] = {"@id": ISOPROPANOL}
        find(libs, "device:bottle_platinum_01")[1].pop("cpo:containsMaterial")
        find(libs, "device:bottle_platinum_01")[1].pop("cpo:hasContainedMaterialHistory")
        find(libs, ISOPROPANOL_CONTENT)[1].pop("cpo:materialContainedIn")
        if ended_at:
            end_occurrence(ISOPROPANOL_CONTENT, ended_at)(libs)
    return mutate


def both(*mutations):
    def mutate(libs):
        for m in mutations:
            m(libs)
    return mutate


def main():
    failures = 0

    def run(label, mutate, placement, history, expect_text=None):
        nonlocal failures
        libs = copy.deepcopy(BASE)
        mutate(libs)
        p, h = c._placement_problems(libs), c._content_history_problems(libs)
        text = " ".join(str(row) for row in p + h)
        ok = (len(p) > 0) == placement and (len(h) > 0) == history and (expect_text is None or expect_text in text)
        failures += not ok
        print(f"{'ok  ' if ok else 'FAIL'} {label}: placement {len(p)}, history {len(h)}")
        for row in p + h:
            print("        ", row)

    run("untouched libraries", lambda libs: None, False, False)
    run("container in the material library", move("device:bottle_adiponitrile_01", "material_library.jsonld"), True, False)
    run("template in the material library", move("device:glass_bottle_250mL", "material_library.jsonld"), True, False)
    run("content back in the device library", move(PLATINUM_CONTENT, "device_library.jsonld"), True, False)
    run("phase of a supply content in the device library",
        move("material:L109_DI_water_supply_Content_Phase", "device_library.jsonld"), True, False)
    run("content without history", drop("device:h2_cylinder_01", "cpo:hasContainedMaterialHistory"), False, True)
    run("emptied, content still points back", drop(ISOPROPANOL, "cpo:containsMaterial"), False, True, "still points back")
    run("emptied cleanly", both(drop(ISOPROPANOL, "cpo:containsMaterial"), drop(ISOPROPANOL_CONTENT, "cpo:materialContainedIn")),
        False, False)
    # Stage 2: several contents one after the other.
    run("current content has ended", end_occurrence(ISOPROPANOL_CONTENT, "task:receiving_bottle_platinum_01_EndTime"),
        False, True, "has ended")
    run("second content while the first has not ended", second_content(), False, True, "has not ended")
    # End of the isopropanol lot = its expiry date (2027), the platinum content came in 2026: they overlap.
    run("second content came before the first ended",
        second_content(ended_at="material:bottle_isopropanol_70_01_Content_ExpiryTime"), False, True, "before")
    # The first content ends exactly when the second comes (the same time:Instant): no finding.
    run("second content after the first ended",
        second_content(ended_at="task:receiving_bottle_platinum_01_EndTime"), False, False)

    print("ALL OK" if not failures else f"{failures} FAILED")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
