"""
The GL45 caps of the K1 Start on their bottles (Laura Fadler, 08.10.2026; rule 3b.4):

- each cap names its two ports as its own (tube port, vent port), each a specialization of the port of the template;
  the vent port of cap no. 1 opens into bottle no. 1, that of cap no. 2 into bottle no. 2 - so that the air the pump
  lets in while it draws off the solution crosses the vent port into the headspace (a port crossing), instead of only
  meeting it at the interface headspace / room air (which stays: the bottle is open while it is filled);
- each bottle names its opening as its own port (a specialization of the opening of the template), so that the cap
  can sit at it: cpo:locatedAt the opening of its bottle, instead of standing in Lab 208 on its own - its room is
  that of the bottle.

An exemplar takes over the ports of its template unless it names its own (creation/device_functions.py,
resolve_exemplar); the crate IDs of the ports stay the same. Which cap sits on which bottle is part of the set-up of
the K1 Start, as the suction tubes open into the bottles (port:k1_tube_A_suction_inlet). The entry tools (rule 2.16)
have no type for the ports of a piece. The openings stay without a form: CPO 1.0 has no form of an opening.

Run after the caps were written as cups (labware_20261008_0951.yaml); the first run (07.10.2026 evening, ring caps)
named only the ports of the caps. Usage (from the repository root), then commit the libraries:
    python projects/pba_synthesis/curation/add_pba_cap_ports.py
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "generator" / "workflow" / "library_prerun"))
sys.path.insert(0, str(ROOT / "generator"))
import path_definitions  # noqa: E402
from fixed_reaction_from_template import LibraryFile  # noqa: E402

TEMPLATE = "gl45_cap_two_ports"
BOTTLE_TEMPLATE = "glass_bottle_500mL"
CAPS = {"01": f"{BOTTLE_TEMPLATE}_01", "02": f"{BOTTLE_TEMPLATE}_02"}
GIVEN = "Laura Fadler, 08.10.2026 (questions_meng_pba.md, N4)"


def port(pid, of, template_port, comment, opens_into=None):
    entity = {"@id": pid, "@type": ["cpo:DeviceOpening", "hlo:Fixed"], "cpo:isPortOf": {"@id": of},
              "hlo:specializationOf": {"@id": template_port}, "rdfs:comment": comment}
    if opens_into:
        entity["cpo:opensInto"] = {"@id": opens_into}
    return entity


def main():
    devices = LibraryFile(path_definitions.DEVICE_LIBRARY_PATH)
    e = devices.by_id()
    if f"port:{TEMPLATE}_01_vent_port" in e:
        sys.exit("The caps have their own ports already - nothing written.")
    for nr, bottle_local in CAPS.items():
        cap, bottle = e[f"device:{TEMPLATE}_{nr}"], e[f"device:{bottle_local}"]
        opening = f"port:{bottle_local}_opening"
        if opening not in e:
            devices.graph.append(port(opening, bottle["@id"], f"port:{BOTTLE_TEMPLATE}_opening",
                                      f"The neck of bottle no. {int(nr)}; its cap sits on it ({GIVEN})."))
            bottle["cpo:hasPort"] = [{"@id": opening}]
        ports = []
        for name, comment, opens_into in (
                ("tube_port", f"The suction tube of the bottle is led through it ({GIVEN}).", None),
                ("vent_port", f"Left open: room air flows through it into the headspace of bottle no. {int(nr)} while the pump "
                              f"draws off the solution ({GIVEN}).", bottle["@id"])):
            devices.graph.append(port(f"port:{TEMPLATE}_{nr}_{name}", cap["@id"], f"port:{TEMPLATE}_{name}", comment, opens_into))
            ports.append({"@id": f"port:{TEMPLATE}_{nr}_{name}"})
        cap["cpo:hasPort"] = ports
        cap.pop("cpo:locatedInsideOf", None)
        cap["cpo:locatedAt"] = {"@id": opening}
        cap["rdfs:comment"] = (f"One piece of the kind device:{TEMPLATE} (form and polypropylene come from there). It sits on "
                               f"bottle no. {int(nr)} (cpo:locatedAt its opening), and its two openings are its own, since the "
                               f"vent port opens into that bottle ({GIVEN}). Its cavity takes in the neck of the bottle, which "
                               f"the bottle model leaves out (rule 3b.4).")
    devices.save()
    print("2 caps on their bottles: their own tube and vent port, the vent port opening into the bottle; 2 bottle openings")


if __name__ == "__main__":
    main()
