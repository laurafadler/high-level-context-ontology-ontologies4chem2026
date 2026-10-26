"""
The pressure regulator of the hydrogen supply (device:pressureregulator001) becomes a cpo:Valve instead of a plain
cpo:Device - it was entered before the ontology had the class (Laura Fadler, 15.10.2026). cpo:Valve is a subclass of
cpo:Device without restrictions of its own, so nothing else changes.

The entry tools cannot change an existing entry. Runs once; commit the libraries afterwards.

Usage (from the repository root):
    python projects/hydrogenation_rdy_2026_09/curation/pressure_regulator_as_valve_20261015.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "generator" / "workflow" / "library_prerun"))
sys.path.insert(0, str(ROOT / "generator"))
import path_definitions  # noqa: E402
from fixed_reaction_from_template import LibraryFile  # noqa: E402

DEVICE = "device:pressureregulator001"
OLD = "Recorded as a plain cpo:Device - it was entered before the ontology had cpo:Valve."
NEW = "A cpo:Valve (Laura Fadler, 15.10.2026; entered before the ontology had the class, as a plain cpo:Device)."


def main():
    devices = LibraryFile(path_definitions.DEVICE_LIBRARY_PATH)
    device = devices.by_id()[DEVICE]
    if device["@type"] != ["cpo:Device", "hlo:Fixed"] or OLD not in device["rdfs:comment"]:
        raise SystemExit(f"{DEVICE} is not as expected - already run? {device['@type']}")
    device["@type"] = ["cpo:Valve", "hlo:Fixed"]
    device["rdfs:comment"] = device["rdfs:comment"].replace(OLD, NEW)
    devices.save()
    print("written: device library - commit the libraries")


if __name__ == "__main__":
    main()
