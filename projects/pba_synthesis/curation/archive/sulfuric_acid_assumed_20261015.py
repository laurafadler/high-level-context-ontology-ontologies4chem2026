"""
The bottle of dilute sulfuric acid the K1 Start is rinsed with: its kind, content, lot and receipt were placeholders
to be asked of Meng Kong. Laura Fadler decides on 15.10.2026 not to ask and takes them as assumptions - the texts of
the bottle, its content and its receipt name her instead of "DUMMY - ask Meng Kong"; no value changes. The entry file
the bottle came from (library_entries/container_20261007_2243.yaml) is changed the same way.

The entry tools cannot change an existing entry. Runs once; commit the libraries afterwards.

Usage (from the repository root):
    python projects/pba_synthesis/curation/sulfuric_acid_assumed_20261015.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "generator" / "workflow" / "library_prerun"))
sys.path.insert(0, str(ROOT / "generator"))
import path_definitions  # noqa: E402
from fixed_reaction_from_template import LibraryFile  # noqa: E402

WHO = "Laura Fadler, 15.10.2026"
BOTTLE = "bottle_sulfuric_acid_dilute_01"
ENTRY_FILE = ROOT / "projects" / "pba_synthesis" / "curation" / "library_entries" / "container_20261007_2243.yaml"
DUMMY = "DUMMIES (Claude Code, 07.10.2026; allowed for PBA by Laura Fadler, 06.10.2026) - ask Meng Kong"
NOTE_OLD = "are not known - kept as a container of the inventory until Meng Kong says."
NOTE_NEW = f"are not known - kept as a container of the inventory, assumed ({WHO}, not asked of Meng Kong)."
TEXTS = [  # (old, new) for the entry file; the library holds the same sentences
    (f"the container, its content and its receipt are {DUMMY}.", f"the container, its content and its receipt are assumed ({WHO})."),
    ("DUMMY - not known; taken like the hydrate bottles", f"not recorded, assumed ({WHO}); taken like the hydrate bottles"),
    ("not known - DUMMY (Claude Code, 07.10.2026) - ask Meng Kong", f"not recorded ({WHO})"),
    (NOTE_OLD, NOTE_NEW),
]


def replace(entity, key, old, new):
    if old not in entity.get(key, ""):
        raise SystemExit(f"{entity['@id']} {key}: text not found - already run? {old[:60]!r}")
    entity[key] = entity[key].replace(old, new)


def main():
    devices = LibraryFile(path_definitions.DEVICE_LIBRARY_PATH)
    materials = LibraryFile(path_definitions.MATERIAL_LIBRARY_PATH)
    d, m = devices.by_id(), materials.by_id()
    bottle = d[f"device:{BOTTLE}"]
    replace(bottle, "rdfs:comment", NOTE_OLD, NOTE_NEW)
    replace(bottle, "schema:comment", *TEXTS[0])
    replace(m[f"task:receiving_{BOTTLE}_EndTime_Reference_1"], "rdfs:comment", *TEXTS[1])
    replace(m[f"material:{BOTTLE}_Content"], "cpo:hasLotNumber", *TEXTS[2])

    raw = ENTRY_FILE.read_bytes().decode("utf-8")
    for old, new in TEXTS:
        if raw.count(old) != 1:
            raise SystemExit(f"{ENTRY_FILE.name}: {old[:60]!r} found {raw.count(old)} times")
        raw = raw.replace(old, new)
    devices.save()
    materials.save()
    ENTRY_FILE.write_bytes(raw.encode("utf-8"))
    print("written: device and material library, the entry file - commit the libraries")


if __name__ == "__main__":
    main()
