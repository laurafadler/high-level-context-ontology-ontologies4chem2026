"""
The vent of the K1 Start is a port of the reactor housing, not of the outlet tip (08.10.2026, Meng Kong, given by Laura
Fadler, questions_meng_pba_outcomes.md, N19): it leaves the housing as a tube with a tube connector; where it is joined
inside and where it leads is not known. Taken to be a purge outlet against too high pressures; during the experiments
no air left through it - the air core leaves through the outlet tip with the liquid. So no stream of the crates uses it.

Removes port:k1_reactor_001_outlet_tip_vent (the data sheet's 'Vent' line, placed at the tip on 05.10.2026) and adds
port:k1_reactor_001_housing_vent. Runs once. Commit the library afterwards.

Usage (from the repository root):
    python projects/pba_synthesis/curation/move_k1_vent_to_housing.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "generator" / "workflow" / "library_prerun"))
sys.path.insert(0, str(ROOT / "generator"))
import path_definitions  # noqa: E402
from fixed_reaction_from_template import LibraryFile  # noqa: E402

OLD, NEW = "port:k1_reactor_001_outlet_tip_vent", "port:k1_reactor_001_housing_vent"
TIP, HOUSING = "device:k1_reactor_001_outlet_tip", "device:k1_reactor_001_housing"
DECIDED = "Meng Kong and Laura Fadler, 08.10.2026 (questions_meng_pba_outcomes.md, N19)"


def main():
    library = LibraryFile(path_definitions.DEVICE_LIBRARY_PATH)
    by_id = library.by_id()
    if NEW in by_id:
        print(f"{NEW} exists already - nothing to do")
        return
    library.graph[:] = [e for e in library.graph if e["@id"] != OLD]
    tip, housing = by_id[TIP], by_id[HOUSING]
    tip["cpo:hasPort"] = [p for p in tip["cpo:hasPort"] if p["@id"] != OLD]
    housing["cpo:hasPort"] = [{"@id": NEW}]
    housing["rdfs:comment"] = ("The white box that holds the capillaries and their fittings in coaxial alignment. Nothing flows "
                               "through it itself in the experiments; the streams are in the capillaries. Its vent leaves it as "
                               "a tube with a tube connector (" + DECIDED + ").")
    library.graph.append({
        "@id": NEW, "@type": ["cpo:DeviceOutlet", "hlo:Fixed"], "cpo:isPortOf": {"@id": HOUSING},
        "rdfs:comment": ("The data sheet's 'Vent' line: a port out of the reactor housing, not at the outlet tip - it leaves the "
                         "housing as a tube with a tube connector. Where it is joined inside and where it leads is not known. "
                         "Assumed to be a purge outlet, so that the pressure inside does not get too high; no air left through "
                         "it during the experiments, the air core leaves through the outlet tip (" + DECIDED + ")."),
        "schema:comment": ("Added by curation; not in the ELN (Accelerated Materials, K1 Technical Data Sheet V20260220: 'Vent') "
                           "- placed at the housing by " + DECIDED + "; until then a side inlet of the outlet tip "
                           "(port:k1_reactor_001_outlet_tip_vent, 05.10.2026), removed by "
                           "projects/pba_synthesis/curation/move_k1_vent_to_housing.py.")})
    library.save()
    print(f"{OLD} removed, {NEW} added")


if __name__ == "__main__":
    main()
