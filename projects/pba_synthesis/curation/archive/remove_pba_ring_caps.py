"""
The GL45 caps of the K1 Start taken out of the device library as rings (labware_20261007_cap.yaml, and their own
ports of add_pba_cap_ports.py), so that they can be written again as cups upside down (Laura Fadler, 08.10.2026:
a screw cap is one object, a cup whose cavity takes in the neck of its bottle - rule 3b.4). The same IDs come back
with the new entry; every link to a removed entity is taken out as well. Run reopen_crate.py pba_synthesis first.

Usage (from the repository root), then commit the libraries:
    python projects/pba_synthesis/curation/remove_pba_ring_caps.py
"""
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "generator" / "workflow" / "library_prerun"))
sys.path.insert(0, str(ROOT / "generator"))
import path_definitions  # noqa: E402
from fixed_reaction_from_template import LibraryFile  # noqa: E402

ENTRY = HERE / "library_entries" / "labware_20261007_cap.yaml"
OWN_PORTS = [f"port:gl45_cap_two_ports_{nr}_{name}" for nr in ("01", "02") for name in ("tube_port", "vent_port")]


def strip(value, removed):
    """The value without references to removed entities (None when nothing is left)."""
    if isinstance(value, list):
        kept = [v for v in (strip(v, removed) for v in value) if v is not None]
        return kept or None
    if isinstance(value, dict) and set(value) == {"@id"}:
        return None if value["@id"] in removed else value
    return value


def main():
    entry = yaml.safe_load(ENTRY.read_text(encoding="utf-8"))
    removed = {i for block in entry.get("written") or [] for i in block["entries"]} | set(OWN_PORTS)
    devices = LibraryFile(path_definitions.DEVICE_LIBRARY_PATH)
    present = {e["@id"] for e in devices.graph} & removed
    if "device:gl45_cap_two_ports" not in present:
        sys.exit("The ring caps are gone already - nothing written.")
    links = 0
    kept = []
    for e in devices.graph:
        if e.get("@id") in removed:
            continue
        for key in list(e):
            if key in ("@id", "@type"):
                continue
            new = strip(e[key], removed)
            if new != e[key]:
                links += 1
                if new is None:
                    del e[key]
                else:
                    e[key] = new
        kept.append(e)
    devices.data["@graph"] = kept
    devices.save()
    print(f"{len(present)} entities of the ring caps taken out, {links} links to them")


if __name__ == "__main__":
    main()
