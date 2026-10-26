"""
The lab of Congjian Lin after the inventory of the Chemotion export (05.10.2026, Laura Fadler: overwrite
the places with the new information). The inventory records (table Chemical, P-CH10) name where the
collection's chemicals are kept: building S1, room B1-09, cabinet B3, group SCCB - the spruce wood stock
SPRUCE-2025-03 (sample LCJ-28); the methanol bottles name '#01-10' only. Until now the lab was a
placeholder ('room not known').

Changes only the names and comments of the site and the lab written by archive/add_library_entries.py; IDs,
size and air stay. Reads and writes the organization library through load_jsonld/save_jsonld (rule 2.14).

Usage (from the repository root):
    python projects/chemotion_example/curation/update_lab_location.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "generator"))
from helpers.file_handling import load_jsonld, save_jsonld  # noqa: E402

PATH = ROOT / "libraries" / "organization_library.jsonld"
SOURCE = ("From the ELN (Chemotion, inventory of sample LCJ-28, the spruce wood stock SPRUCE-2025-03): host_building 'S1', "
          "host_room 'B1-09', host_cabinet 'B3', host_group 'SCCB'; sample location 'Cabinet B3, Shelf 1'. The methanol "
          "bottles of the collection (LCJ-44, LCJ-45) name only '#01-10'. That the experiments ran in this room is assumed "
          "(suggested by Claude Code, places confirmed by Laura Fadler on 05.10.2026).")


def main():
    data = load_jsonld(PATH)
    by_id = {e["@id"]: e for e in data["@graph"]}
    lab, site = by_id["lab:NTU_CongjianLin_Lab"], by_id["site:NTU"]
    assert "room not known" in lab["schema:name"], "already updated"
    lab["schema:name"] = "Room B1-09, building S1 (NTU) - lab of Congjian Lin"
    lab["rdfs:comment"] = ("The lab of Congjian Lin (group SCCB), where the RCF of the Chemotion records LCJ-R5 and LCJ-R8 is taken to "
                           "have run. Its size and air are not known: copied from the entries of the SVT lab - assumed size, "
                           "textbook air (suggested by Claude Code, not yet confirmed). " + SOURCE)
    site["schema:name"] = "Nanyang Technological University, Singapore"
    site["rdfs:comment"] = ("Site of the lab of Congjian Lin; the inventory of the Chemotion export names building S1 there. Gravity "
                            "copied from the RWTH site (standard gravity). " + SOURCE)
    save_jsonld(data, PATH)
    print("Lab and site updated.")


if __name__ == "__main__":
    main()
