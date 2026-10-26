"""
The K1 reactor in sections (L9 of pba_synthesis, decided by Laura Fadler on 06.10.2026) - changes
the entries add_k1_system.py wrote into the device library on 05.10.2026:

- Capillaries T2 and T3 become composite devices of two sections each. Every section is a quartz
  tube of its own with inlet, outlet and cavity, so that it holds a stream of its own:
  T2 around T1 (liquid A only) and the T2 contact zone (liquid A with the air core, after T1 ends);
  T3 around T2 (liquid B only) and the T3 mixing zone (both liquids and the air, after T2 ends - the
  50 mm reaction length of the data sheet). Only in the mixing zone do the reactions take place.
- T1 opens into the contact zone of T2, the contact zone into the mixing zone of T3. The mixing zone
  is connected to a new inlet of the outlet tip; the vent stays a side inlet of its own, not on the
  way of the product.
- The tube from the mass flow controller to T1 is renamed k1_tube_air_reactor -> k1_tube_air_feed,
  like the feed tubes of the pumps ("reactor" read like the reactor's outlet).

The patent gives no length for the contact zone (only that T2 ends downstream of T1 or with it):
10 mm is assumed. The sections reuse the helpers of add_k1_system.py; the old entries of T2 and T3
(devices, ports, forms, values, bodies, calculations) are removed, their links taken over.

Run once, from the repository root (stops if the sections exist already); commit the library
afterwards:
    python projects/pba_synthesis/curation/restructure_k1_reactor.py
"""
import importlib.util
import json
import sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location("add_k1_system", Path(__file__).resolve().parent / "add_k1_system.py")
k1 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(k1)          # puts generator/ on sys.path

import path_definitions  # noqa: E402
from helpers.file_handling import load_jsonld, save_jsonld  # noqa: E402
from helpers.inventory_entries import Entries, ref  # noqa: E402

STAMP = "2026-10-06T15:00:00Z"
ASSUME = "task:assuming_k1_reactor_sections"
TIMES = "task:assuming_k1_reactor_sections_entry_times"
R = k1.R
TIP = f"{R}_outlet_tip"
OLD_AIR, NEW_AIR = "k1_tube_air_reactor", "k1_tube_air_feed"
k1.ORIGIN = ("Added by curation; not in the ELN ({sources}) - suggested by Claude Code, confirmed by Laura Fadler on "
             "06.10.2026 for the series pba_synthesis.")
k1.lib = Entries(TIMES, STAMP, k1.PERSON, "the section entries of the K1 reactor")

DIAMETERS = {key: (inner, outer) for key, inner, outer, *_ in k1.CAPILLARIES}
# capillary -> (section, length, what is in it, comment); upstream section first. All capillaries are 100 mm long
# (patent), so the two sections of one add up to it.
SECTIONS = {
    "T2": [("around_T1", k1.CAP_LENGTH - 0.010, "liquid 1 (Reagent A) alone, in the ring between T1 and T2",
            "From the Reagent A connection to where T1 ends inside T2."),
           ("contact_zone", 0.010, "liquid 1 as a film on the wall with the air core in the middle - no reaction",
            "From the end of T1 to the end of T2: the air leaving T1 meets liquid 1 and forces it into a thin film (the "
            "patent's liquid film forming section). Its length is assumed: the patent gives none, only that T2 ends "
            "downstream of T1 or with it - taken as 10 mm, twenty times the inner diameter of T2.")],
    "T3": [("around_T2", k1.CAP_LENGTH - 0.050, "liquid 2 (Reagent B) alone, in the ring between T2 and T3",
            "From the Reagent B connection to where T2 ends inside T3."),
           ("mixing_zone", 0.050, "both liquids and the air core - the two films meet, the PBA precipitates",
            "From the end of T2 to the end of T3: the mixing zone, 50 mm long - the reaction length of the data sheet "
            "(about 39 uL with the air core), as in the patent's example.")],
}
INNER = {"T2": "T1", "T3": "T2"}        # the capillary that runs inside the first section
LIQUID = {"T2": 1, "T3": 2}
joints = []                              # (port, port): cpo:isConnectedTo on both sides


def name_of(key, section):
    return f"{R}_capillary_{key}_{section}"


def envelope(name, outer, length):
    """The space a capillary made of sections takes up: a solid cylinder of its outer diameter and
    full length (a composite device has no form of its own, but an envelope - Device_Space_R7)."""
    form = f"device:{name}_Envelope"
    ids = [k1.given(f"{form}Diameter", "quantitykind:Diameter", outer, "unit:M", "hlo:Assumed",
                    f"Outer diameter of the capillary, {k1.mm(outer)} - from the patent's example reactor.", ASSUME,
                    source=k1.PATENT),
           k1.given(f"{form}Height", "quantitykind:Height", length, "unit:M", "hlo:Assumed",
                    f"Length of the capillary, {k1.mm(length)} - from the patent's example reactor.", ASSUME,
                    source=k1.PATENT)]
    volume = 3.141592653589793 / 4 * outer ** 2 * length
    k1.calc(f"{name}_EnvelopeOuterVolume", "Cylinder from the outer diameter and the length",
            f"pi/4 x ({outer:g} m)^2 x {length:g} m = {k1.g(volume)} m3.", f"{form}OuterVolume", "quantitykind:Volume",
            volume, "unit:M3", ids)
    k1.lib.add({"@id": form, "@type": "cpo:SolidCylinderForm",
                "rdfs:comment": "Envelope of the whole capillary - the space it takes up, its bore included. Its sections "
                                "carry the tube forms.",
                "cpo:hasDiameter": ref(f"{form}Diameter"), "cpo:hasHeight": ref(f"{form}Height"),
                "cpo:hasOuterVolume": ref(f"{form}OuterVolume"),
                "cpo:hasHeightToDiameterRatio": ref(f"{form}_HeightToDiameterRatio")})
    k1.empty(f"{form}_HeightToDiameterRatio", "quantitykind:LengthRatio")
    return ref(form)


def sections():
    """The four sections and the two capillaries made of them; returns the IDs of the new ports
    the old links are moved to."""
    for key, parts in SECTIONS.items():
        inner_d, outer_d = DIAMETERS[key]
        made_of = []
        for index, (section, length, what, where) in enumerate(parts):
            name = name_of(key, section)
            first = index == 0
            label = "Reagent A" if key == "T2" else "Reagent B"
            inlet = k1.port(f"{name}_inlet", "cpo:DeviceInlet", f"device:{name}",
                            f"The data sheet's '{label}' connection: liquid {LIQUID[key]} enters capillary {key} here."
                            if first else
                            f"Where the section before it ends: the same quartz tube goes on, no joint - only the "
                            f"capillary {INNER[key]} inside ends here.")
            if first:
                outlet = k1.port(f"{name}_outlet", "cpo:DeviceOutlet", f"device:{name}",
                                 f"Where capillary {INNER[key]} ends inside {key}: the same quartz tube goes on as its next "
                                 "section, no joint.")
                joints.append((outlet["@id"], f"port:{name_of(key, parts[1][0])}_inlet"))
            elif key == "T2":
                outlet = k1.port(f"{name}_outlet", "cpo:DeviceOutlet", f"device:{name}",
                                 "The open end of capillary T2, inside T3 - what leaves it enters the mixing zone directly.",
                                 opens_into=f"device:{name_of('T3', 'mixing_zone')}")
            else:
                outlet = k1.port(f"{name}_outlet", "cpo:DeviceOutlet", f"device:{name}",
                                 "The end of the mixing zone, joined to the inlet of the outlet tip - assumed: how T3 meets "
                                 "the tip is not known.")
                joints.append((outlet["@id"], f"port:{TIP}_inlet"))
            ring = 3.141592653589793 / 4 * (inner_d ** 2 - DIAMETERS[INNER[key]][1] ** 2) * length if first else None
            k1.device(name, ["cpo:Pipe"], f"Capillary {key} of the K1 Start reactor, {section.replace('_', ' ')}",
                      f"Section of capillary {key}: {what}. {where} Its cavity is the full bore of {key}"
                      + (f"; capillary {INNER[key]} runs inside it, so the liquid has only the ring between the two (about "
                         f"{ring * 1e9:.3g} uL of the {3.141592653589793 / 4 * inner_d ** 2 * length * 1e9:.3g} uL)."
                         if first else ".")
                      + " Dimensions and material from the patent the K1 is built on - assumed, the commercial K1 may differ.",
                      f"{k1.SHEET}; {k1.PATENT}", False, k1.AM, ports=(inlet, outlet), part_of=f"device:{R}_capillary_{key}",
                      located_at=f"device:{R}_housing")
            geometry = k1.tube(name, outer_d, inner_d, length, "hlo:Assumed", ASSUME,
                               "Diameters from the patent's example reactor (precision quartz capillaries), length of the "
                               "section assumed - not measured.", source=k1.PATENT)
            k1.body(name, k1.QUARTZ_BODY, volume_from=geometry)
            made_of.append(ref(f"device:{name}"))
        k1.device(f"{R}_capillary_{key}", ["cpo:Pipe"], f"Capillary {key} of the K1 Start reactor",
                  f"Capillary {key} of the coaxial arrangement, one quartz tube of {k1.mm(k1.CAP_LENGTH)} (patent), taken as "
                  f"two sections so that each holds a stream of its own: {parts[0][0].replace('_', ' ')} and "
                  f"{parts[1][0].replace('_', ' ')}. Form, body and ports are those of the sections. Assumed from the patent "
                  "the K1 is built on - the commercial K1 may differ.",
                  f"{k1.SHEET}; {k1.PATENT}", False, k1.AM, composite=True, form=False, part_of=f"device:{R}",
                  located_at=f"device:{R}_housing",
                  extra={"dcterms:hasPart": made_of, "cpo:hasEnvelopeForm": envelope(f"{R}_capillary_{key}", outer_d,
                                                                                      k1.CAP_LENGTH)})
    tip_inlet = k1.port(f"{TIP}_inlet", "cpo:DeviceInlet", f"device:{TIP}",
                        "Where the mixing zone of T3 ends in the tip: the product enters the tip here - assumed, how T3 "
                        "meets the tip is not known.")
    return tip_inlet


def scrub(entity, gone):
    """Remove every reference to an entry that is gone (a single one: the key; in a list: the item)."""
    for key in list(entity):
        value = entity[key]
        if isinstance(value, dict) and value.get("@id") in gone:
            del entity[key]
        elif isinstance(value, list):
            kept = [v for v in value if not (isinstance(v, dict) and v.get("@id") in gone)]
            if len(kept) != len(value):
                entity[key] = kept


def append(entity, key, refs):
    current = entity.get(key, [])
    entity[key] = (current if isinstance(current, list) else [current]) + refs


def main():
    path = path_definitions.DEVICE_LIBRARY_PATH
    library = load_jsonld(path)
    graph = library["@graph"]
    by_id = {e["@id"]: e for e in graph}
    if f"device:{name_of('T3', 'mixing_zone')}" in by_id:
        sys.exit("The sections exist already - nothing written.")

    tip_inlet = sections()
    k1.lib.task(ASSUME, "cpo:AssumptionTask", "Assuming the sections of the K1 reactor's capillaries",
                "Capillaries T2 and T3 are each taken as two sections, split where the capillary inside them ends. The "
                "mixing zone in T3 is the data sheet's reaction length of 50 mm; the contact zone in T2 is assumed 10 mm, "
                "the patent gives no length. Diameters as in the patent's example. Agreed with Laura Fadler, 06.10.2026.",
                determines=k1.determined.pop(ASSUME))
    k1.lib.times_task("Assuming when the K1 reactor section entries were worked out",
                      f"None of the tasks behind the section entries was recorded with a time. Their start times are "
                      f"stamped with the moment the entries were written ({STAMP}) - an upper bound. This task's own start "
                      f"time is among them.")
    new = k1.lib.items
    new_ids = {e["@id"] for e in new}

    # Old T2/T3 entries out; links to IDs that come back (the two capillaries) stay.
    old = [e for e in graph if f"{R}_capillary_T2" in e["@id"] or f"{R}_capillary_T3" in e["@id"]]
    position = graph.index(old[0])
    gone = {e["@id"] for e in old} - new_ids
    clash = (new_ids - {e["@id"] for e in old}) & set(by_id)
    if clash:
        sys.exit(f"Already in the library: {sorted(clash)} - nothing written.")
    graph[:] = [e for e in graph if e not in old]
    for entity in graph:
        scrub(entity, gone)
    graph[position:position] = new
    by_id = {e["@id"]: e for e in graph}

    # Links of the neighbours: tubes to the first sections, T1 into the contact zone, the tip's new inlet.
    for tube, key in (("k1_tube_A_feed", "T2"), ("k1_tube_B_feed", "T3")):
        joints.append((f"port:{tube}_outlet", f"port:{name_of(key, SECTIONS[key][0][0])}_inlet"))
    for a, b in joints:
        for this, other in ((a, b), (b, a)):
            by_id[this]["cpo:isConnectedTo"] = ref(other)
    by_id[f"port:{R}_capillary_T1_outlet"]["cpo:opensInto"] = ref(f"device:{name_of('T2', 'contact_zone')}")
    by_id[f"port:{R}_capillary_T1_outlet"]["rdfs:comment"] = (
        "The open end of capillary T1, inside T2 - what leaves it enters the contact zone of T2 directly.")
    tip = by_id[f"device:{TIP}"]
    tip["cpo:hasPort"] = [tip_inlet] + [p for p in tip["cpo:hasPort"]]
    by_id[f"port:{TIP}_vent"]["rdfs:comment"] = (
        "The data sheet's 'Vent' line: a side inlet of the tip for quenching, cleaning it, or venting - not on the way of "
        "the product, which enters through the tip's inlet. Where exactly it joins the tip is not known.")
    reactor = by_id[f"device:{R}"]
    old_text = ("The five ports of the data sheet sit on the parts they lead into: Compressed Air on T1, Reagent A on T2, "
                "Reagent B on T3, Vent and Outlet on the outlet tip.")
    assert old_text in reactor["rdfs:comment"], "reactor comment changed - check by hand"
    reactor["rdfs:comment"] = reactor["rdfs:comment"].replace(
        old_text, "T2 and T3 are each taken as two sections - where the capillary inside still runs, and after it ends - so "
        "that each holds a stream of its own; the reactions take place only in the mixing zone of T3. The five ports of the "
        "data sheet sit on the parts they lead into: Compressed Air on T1, Reagent A and Reagent B on the first sections of "
        "T2 and T3, Vent and Outlet on the outlet tip (which has an inlet from the mixing zone as well).")

    # Tasks of 05.10.2026 that the new values belong to as well.
    for task_id, members in k1.determined.items():
        append(by_id[task_id], "cpo:determines", [ref(i) for i in members])
    append(by_id[k1.GEOMETRY], "dcterms:hasPart", [ref(t) for t in k1.calculations])
    append(by_id[k1.COMMISSIONING], "cpo:usedEquipment",
           [ref(d) for d in k1.k1_devices if d not in {u["@id"] for u in by_id[k1.COMMISSIONING]["cpo:usedEquipment"]}])

    # The air tube to T1 is named like the feed tubes of the pumps.
    text = json.dumps(library, ensure_ascii=False)
    renamed = text.count(OLD_AIR)
    library = json.loads(text.replace(OLD_AIR, NEW_AIR))

    save_jsonld(library, path)
    print(f"device library: -{len(old)} entries of T2/T3, +{len(new)} (four sections, two capillaries, tip inlet, "
          f"{len(k1.calculations)} calculations, tasks); {renamed} mentions of {OLD_AIR} -> {NEW_AIR}")


if __name__ == "__main__":
    main()
