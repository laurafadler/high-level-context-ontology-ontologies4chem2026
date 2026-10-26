"""
Test entries for the origin of hydrogen and cooling water (N25, 02.10.2026): a 10 L steel gas
cylinder of hydrogen 5.0 in a gas cabinet of Lab 109, and the deionised water supply of Lab 109.
Before, both came into the hydrogenation from an unnamed cpo:Source, and Phase_Time_R2 reported
them (no known origin). All values are invented test values, marked as such - decided with Laura
Fadler on 02.10.2026.

Writes into three libraries, each in its own format (since 05.10.2026 devices and contents apart):
- device library: the cylinder kind (helpers/inventory_entries.py: container_template, steel), the
  water supply (supply_pipe: a cpo:Pipe with an outlet), the cylinder h2_cylinder_01 with its
  opening, the task that assumes the state of the supply, and the task that stamps the start times
  of these entries;
- material library: the deionised water in the supply (a permanent occurrence, like the room air)
  and the content of the cylinder (lot, purity, certificate as a file, delivery), read off by
  task:reading_inventory_test_records;
- organization library: the gas cabinet.
Already run (02.10.2026) and written before the libraries were split into two files each (rule
2.14) - it reads the main files only; kept as the record of how the entries came about.
Stops without writing if any of the entries exists already. Commit the libraries afterwards (a run
refuses to start with uncommitted libraries).

Run from the repository root:
    python generator/tests/add_supply_test_entries.py   (where it stood; archived, not to be run again)
"""
import json
import sys
from pathlib import Path

# Ran from generator/tests/ - the generator had to be on the search path (archived: the path no longer fits).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import path_definitions  # noqa: E402
from helpers.inventory_entries import (STEEL_BODY, Entries, cabinet, container, container_template,  # noqa: E402
                                       ref, supply_pipe)

STAMP = "2026-10-02T18:00:00Z"
PERSON = "person:LauraFadler"
RECORDS_TASK = "task:reading_inventory_test_records"
CYLINDER_KIND, CYLINDER = "gas_cylinder_10L", "h2_cylinder_01"
SUPPLY = "L109_DI_water_supply"
GAS_CABINET = "lab:L109_GasCabinet"
LOT = "H2-260815-07"


class LibraryFile:
    """A library file read and written back in its own format (indent, line ends, final newline)."""

    def __init__(self, path: Path):
        self.path = path
        raw = path.read_bytes().decode("utf-8")
        self.data = json.loads(raw)
        self.newline = "\r\n" if "\r\n" in raw else "\n"
        for indent in (2, 1, 4):
            for final in ("", self.newline):
                if self._render(indent, final) == raw:
                    self.indent, self.final = indent, final
                    return
        sys.exit(f"{path.name}: cannot be written back unchanged - not touching it.")

    def _render(self, indent, final):
        return json.dumps(self.data, indent=indent, ensure_ascii=False).replace("\n", self.newline) + final

    def ids(self):
        return {e["@id"] for e in self.data["@graph"]}

    def find(self, entity_id):
        return next(e for e in self.data["@graph"] if e["@id"] == entity_id)

    def save(self):
        self.path.write_bytes(self._render(self.indent, self.final).encode("utf-8"))


def main():
    devices = LibraryFile(path_definitions.DEVICE_LIBRARY_PATH)
    inventory = LibraryFile(path_definitions.MATERIAL_LIBRARY_PATH)
    organization = LibraryFile(path_definitions.ORGANIZATION_LIBRARY_PATH)
    planned = {f"device:{CYLINDER_KIND}", f"device:{SUPPLY}", f"device:{CYLINDER}", GAS_CABINET}
    existing = planned & (devices.ids() | inventory.ids() | organization.ids())
    if existing:
        sys.exit(f"Already in the libraries: {sorted(existing)} - nothing written.")

    lib = Entries("task:assuming_supply_entry_times", STAMP, PERSON, "the gas cylinder and water supply entries")
    kind = container_template(
        lib, CYLINDER_KIND, "Steel gas cylinder 10 L", 0.140, 0.82, 0.0057, "organization:ExampleCorp", body_kind=STEEL_BODY,
        comment="TEMPLATE of a gas cylinder kind, not one identifiable cylinder: the cylinders of the inventory that are of this "
                "kind specialize it (hlo:specializationOf) and take over its form, body and opening - the opening is the valve "
                "outlet. Approximated as a plain steel cup (the shoulder and the valve are left out); 10 L water capacity, "
                "200 bar. Test entry (02.10.2026).")
    determined, supply_density = supply_pipe(
        lib, SUPPLY, "Deionised water supply of Lab 109", "lab:L109", 0.015, 0.001, 1.0, "organization:ExampleCorp", STEEL_BODY,
        "Deionised water", [("chem:Molecule_0003", "Water")], ("2020-01-06T08:00:00Z", "2020-01-06T16:00:00Z"),
        "task:assuming_L109_DI_water_supply",
        "The deionised water line of Lab 109, from the building supply to its outlet in the room - the last stretch of it "
        "as a device. The cooling water of the reactor jacket is taken from here. Test entry (02.10.2026).")
    lib.task("task:assuming_L109_DI_water_supply", "cpo:AssumptionTask", "Assuming the state of the deionised water supply of Lab 109",
             "The line is taken as always filled with deionised water (pure water, no other species - decided by Laura Fadler, "
             "02.10.2026), and as installed with the lab; there is no record of when.", determines=determined)
    lib.times_task("Assuming when the gas cylinder and water supply entries were worked out",
                   f"None of the tasks behind these test entries was recorded with a time. Their start times are stamped "
                   f"with the moment the entries were written ({STAMP}) - an upper bound, not the moment the work happened. "
                   f"This task's own start time is among them.")
    steel_task = devices.find(STEEL_BODY["density_task"])
    steel_task["cpo:determines"] = steel_task["cpo:determines"] + [ref(kind["density_reference"]), ref(supply_density)]
    device_items, material_items = lib.split()
    devices.data["@graph"].extend(device_items)
    inventory.data["@graph"].extend(material_items)

    stock = Entries("task:unused", STAMP, PERSON)
    content = {"label": "Hydrogen 5.0", "state": "gas", "lot": LOT, "sku": "H2-50-10L", "manufacturer": "organization:ExampleCorp",
               "mass_kg": 0.16, "species": [("chem:Molecule_0001", "Hydrogen", 0.99999)],
               "certificate": f"Certificate of analysis, lot {LOT} (test entry)",
               "certificate_file": f"document:certificate_of_analysis_{LOT}",
               "delivered": ("2026-09-01T09:00:00Z", "2026-09-01T09:20:00Z"), "opened": "2026-09-07T10:00:00Z"}
    read = container(stock, CYLINDER, "Hydrogen cylinder 01", kind["device"], kind["cavity"], GAS_CABINET, content, RECORDS_TASK,
                     entered="02.10.2026", body_word="steel")
    certificate = next(e for e in stock.items if e["@id"] == content["certificate_file"])
    certificate["schema:name"] = f"Certificate of analysis, lot {LOT}"
    certificate["rdfs:comment"] = (f"The certificate of analysis of the hydrogen lot {LOT} in device:{CYLINDER}. Test entry "
                                   f"(02.10.2026): no file is stored - a real entry names it with schema:contentUrl.")
    records = inventory.find(RECORDS_TASK)
    records["cpo:determines"] = records["cpo:determines"] + [ref(i) for i in read]
    old = "of the three test bottles, read off their labels"
    assert old in records["schema:description"], records["schema:description"]
    records["schema:description"] = records["schema:description"].replace(
        old, "of the three test bottles and the hydrogen cylinder (added 02.10.2026), read off their labels")
    device_items, material_items = stock.split()
    devices.data["@graph"].extend(device_items)
    inventory.data["@graph"].extend(material_items)

    organization.data["@graph"].append(cabinet(GAS_CABINET, "Gas cabinet, Lab 109", "lab:L109",
                                               "Ventilated cabinet for the gas cylinders of Lab 109. Test entry (02.10.2026)."))

    for library in (devices, inventory, organization):
        library.save()
    print(f"device and material library: +{len(lib.items) + len(stock.items)}, organization library: +1")


if __name__ == "__main__":
    main()
