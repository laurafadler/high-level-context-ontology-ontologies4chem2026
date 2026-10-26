"""
The K1 Start flow reactor system of Lab 208 (Accelerated Materials) for the series pba_synthesis -
library entries written on 05.10.2026 by Claude Code, structure and assumptions agreed with Laura
Fadler in the same session. Every entry says where it comes from:

- Accelerated Materials, K1 Technical Data Sheet V20260220 (dimensions and limits of the K1-2T
  reactor, the dosing module of the K1 Start: two pumps, one mass flow controller, three pressure
  sensors);
- patent US11724241B2 (N. Jose, A. Lapkin, Cambridge Enterprise; the technology the K1 is built on):
  three coaxial quartz capillaries with a 50 mm mixing zone - taken as an assumption for the
  inside of the reactor, which nobody has seen;
- the FLOM UI-32 / UI-22 and Sensirion SFC5500 data sheets (pumps and mass flow controller);
- Laura Fadler (05.10.2026): Lab 208, commissioning mid-2025, never used, no calibration records,
  pressure sensors in the pumps and in the mass flow controller, compressed air from the lab
  supply, 500 mL bottles and a 1 L beaker, a plastic housing.

Writes into four libraries, each in its own format (stops if any entry exists already):
- chemical entity library: fused quartz, aluminium and PEEK (informal entries like glass and steel);
- organization library: Accelerated Materials, FLOM, Sensirion; Lab 208 (copied from Lab 108 -
  assumed size, textbook air);
- device library: the reactor (composite: housing, capillaries T1-T3, outlet tip), two pumps with
  their heads and pressure sensors, the mass flow controller with its flow channel and pressure
  sensor, the compressed air supply of Lab 208, six tubes joined to the ports (cpo:isConnectedTo), a 500 mL bottle and a 1 L beaker as templates with their exemplars,
  the commissioning of the system and the tasks behind every value.
The classes cpo:Pump, cpo:MassFlowMeter, cpo:MassFlowController and the property cpo:isConnectedTo
are added to the CPO by hand (same day). Commit the libraries afterwards (a run refuses to start with uncommitted libraries).

Usage (from the repository root):
    python projects/pba_synthesis/curation/add_k1_system.py

Changed on 06.10.2026 by restructure_k1_reactor.py (capillaries T2 and T3 in sections, an inlet of
the outlet tip, k1_tube_air_reactor renamed k1_tube_air_feed): this script records the entries as
written on 05.10.2026.
"""
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "generator"))
import path_definitions  # noqa: E402
from helpers.inventory_entries import (GLASS_BODY, STEEL_BODY, Entries, container_template, ref,  # noqa: E402
                                       supply_pipe)

STAMP = "2026-10-05T18:00:00Z"
PERSON = "person:LauraFadler"
LAB = "lab:L208"
ASSUME = "task:assuming_k1_system_dimensions"
LOOKUP = "task:looking_up_k1_system_data"
GEOMETRY = "task:calculating_k1_system_geometry"
COMMISSIONING = "task:commissioning_k1_system"
ASSUME_COMMISSIONING = "task:assuming_k1_system_commissioning"
AM, FLOM, SENSIRION = "organization:AcceleratedMaterials", "organization:FLOM", "organization:Sensirion"

ORIGIN = ("Added by curation; not in the ELN ({sources}) - suggested by Claude Code, confirmed by Laura Fadler on "
          "05.10.2026 for the series pba_synthesis.")
SHEET = "Accelerated Materials, K1 Technical Data Sheet V20260220"
PATENT = ("Patent US11724241B2, 'Constant shear continuous reactor device' (N. Jose, A. Lapkin; Cambridge Enterprise), "
          "example annular microreactor; patents.google.com/patent/US11724241B2")
FLOM_SHEET = ("FLOM, Intelligent Pump UI-32 series (flom.co.jp/eng/product/oem_ui32.html) and UI-22-110P "
              "(glsciencesinc.com/linear-drive-pulse-control-intelligent-pump-peek-10-ml-min-20-mpa)")
SFC_SHEET = "Sensirion, Datasheet SFC5500 mass flow controller and SFM5500 mass flow meter (sensirion.com/resource/datasheet/sfc5500_sfm5500)"

# Materials of construction: like GLASS_BODY/STEEL_BODY in the helper - substance, density with look-up task and source, structure.
QUARTZ_BODY = {"entity": "chem:FusedQuartz", "density": 2200, "density_task": "task:looking_up_fused_quartz_density",
               "source": "Heraeus, fused silica properties; en.wikipedia.org/wiki/Fused_quartz.",
               "density_comment": "Fused quartz, 2200 kg/m3 - the material of the capillaries is assumed, not known.",
               "comment": "Fused quartz, as in the patent the K1 is built on - assumed, nobody has seen the capillaries.",
               "structure": "cpo:Amorphous", "word": "quartz"}
PTFE_BODY = {"entity": "chem:ChemicalEntity_0004", "density": 2200, "density_task": "task:looking_up_ptfe_density",
             "source": "MakeItFrom.com, polytetrafluoroethylene (PTFE); en.wikipedia.org/wiki/Polytetrafluoroethylene.",
             "density_comment": "Generic PTFE (2150-2200 kg/m3), recorded as 2200 kg/m3 - not measured.",
             "comment": "PTFE tubing - assumed, the usual material of such lines (agreed with Laura Fadler, 05.10.2026).",
             "structure": "cpo:Crystalline", "word": "PTFE"}
PP_BODY = {"entity": "chem:ChemicalEntity_0003", "density": 900, "density_task": "task:looking_up_polypropylene_density",
           "source": "Polypropylene homopolymer, 895-920 kg/m3 (en.wikipedia.org/wiki/Polypropylene).",
           "density_comment": "Generic polypropylene, the same value as for the syringe and the vial cap - not measured.",
           "comment": ("Polypropylene - assumed: the housing is a plastic box (Laura Fadler, 05.10.2026), and PP is the one of "
                       "the data sheet's wetted materials (ETFE, PEEK, PP, quartz) such a box is usually made of."),
           "structure": "cpo:Crystalline", "word": "polypropylene"}
ALU_BODY = {"entity": "chem:Aluminium", "density": 2700, "density_task": "task:looking_up_aluminium_density",
            "source": "Aluminium alloys 2660-2810 kg/m3; en.wikipedia.org/wiki/Aluminium_alloy.",
            "density_comment": "Generic aluminium alloy, 2700 kg/m3 - not measured.",
            "comment": "Aluminium body, as the SFC5500 data sheet gives it (wetted part: body).",
            "structure": "cpo:Crystalline", "word": "aluminium"}
PEEK_BODY = {"entity": "chem:PEEK", "density": 1300, "density_task": "task:looking_up_peek_density",
             "source": "PEEK, 1300-1320 kg/m3 (en.wikipedia.org/wiki/Polyether_ether_ketone).",
             "density_comment": "Generic unfilled PEEK, 1300 kg/m3 - not measured.",
             "comment": "PEEK pump head - read from the model number (P), as for the UI-22-110P; assumed.",
             "structure": "cpo:Crystalline", "word": "PEEK"}
STEEL = dict(STEEL_BODY, comment="Generic stainless steel, as for the other steel devices of the library - assumed, not "
                                 "verified against the actual part.")

lib = Entries("task:assuming_k1_system_entry_times", STAMP, PERSON, "the K1 system entries")
determined = {}          # task -> the values it determines
calculations = []        # parts of GEOMETRY
k1_devices = []          # everything the commissioning uses


def note(task, member):
    determined.setdefault(task, []).append(member)
    return member


def given(actual_id, kind, value, unit, value_type, comment, task, source=None):
    return note(task, lib.value(actual_id, kind, "Reference", value, unit, value_type, comment, task, source=source))


def calc(key, name, text, actual_id, kind, value, unit, inputs):
    task_id = f"task:calculating_{key}"
    member = lib.value(actual_id, kind, "Evidence", value, unit, "hlo:Calculated", text, task_id)
    lib.task(task_id, "cpo:CalculationTask", name, text, determines=[member], inputs=inputs, part_of=GEOMETRY)
    calculations.append(task_id)
    return member


def empty(actual_id, kind):
    lib.add({"@id": actual_id, "@type": ["cpo:ProcessVariable", "hlo:Fixed", "hlo:Actual"],
             "qudt:hasQuantityKind": ref(kind)})


def mm(x):
    return f"{x * 1000:g} mm"


def g(x):
    return f"{x:.6g}"


# ---------------------------------------------------------------------------------------------
# Forms and bodies
# ---------------------------------------------------------------------------------------------
def cuboid(name, form, base, dims, value_type, task, comment, form_comment, source=None):
    """A cuboid form with length, width and height given (value_type, task) and the outer volume
    calculated; base is the ID stem of the values (device:x_ or device:x_Envelope)."""
    length, width, height = dims
    ids = [given(f"{base}{key}", f"quantitykind:{key}", value, "unit:M", value_type, f"{key}, {mm(value)}. {comment}", task,
                 source=source)
           for key, value in (("Length", length), ("Width", width), ("Height", height))]
    volume = length * width * height
    calc(f"{name}_OuterVolume", "Box from its three edges", f"{length:g} m x {width:g} m x {height:g} m = {g(volume)} m3.",
         f"{base}OuterVolume", "quantitykind:Volume", volume, "unit:M3", ids)
    lib.add({"@id": form, "@type": "cpo:CuboidForm", "rdfs:comment": form_comment,
             "cpo:hasLength": ref(f"{base}Length"), "cpo:hasWidth": ref(f"{base}Width"), "cpo:hasHeight": ref(f"{base}Height"),
             "cpo:hasOuterVolume": ref(f"{base}OuterVolume"),
             "cpo:hasWidthToLengthRatio": ref(f"{form}_WidthToLengthRatio"),
             "cpo:hasHeightToLengthRatio": ref(f"{form}_HeightToLengthRatio")})
    empty(f"{form}_WidthToLengthRatio", "quantitykind:LengthRatio")
    empty(f"{form}_HeightToLengthRatio", "quantitykind:LengthRatio")
    return volume


def cylinder(name, diameter, height, comment):
    """A solid cylinder (a small sensor): diameter and height assumed, outer volume calculated."""
    d, form = f"device:{name}", f"device:{name}_Form"
    ids = [given(f"{d}_Diameter", "quantitykind:Diameter", diameter, "unit:M", "hlo:Assumed",
                 f"Assumed diameter of the sensor, {mm(diameter)}. {comment}", ASSUME),
           given(f"{d}_Height", "quantitykind:Height", height, "unit:M", "hlo:Assumed",
                 f"Assumed length of the sensor, {mm(height)}. {comment}", ASSUME)]
    volume = math.pi / 4 * diameter ** 2 * height
    calc(f"{name}_OuterVolume", "Cylinder from its diameter and length",
         f"pi/4 x ({diameter:g} m)^2 x {height:g} m = {g(volume)} m3.", f"{d}_OuterVolume", "quantitykind:Volume", volume,
         "unit:M3", ids)
    lib.add({"@id": form, "@type": "cpo:SolidCylinderForm", "cpo:hasDiameter": ref(f"{d}_Diameter"),
             "cpo:hasHeight": ref(f"{d}_Height"), "cpo:hasOuterVolume": ref(f"{d}_OuterVolume"),
             "cpo:hasHeightToDiameterRatio": ref(f"{form}_HeightToDiameterRatio")})
    empty(f"{form}_HeightToDiameterRatio", "quantitykind:LengthRatio")
    return volume


def tube(name, outer, inner, length, value_type, task, comment, source=None):
    """A tube form with a cavity, as for the water supply: outer and inner diameter and length
    given, the wall and both volumes calculated. Returns (outer volume, inner volume) and the
    evidence IDs of both."""
    d, form, cavity = f"device:{name}", f"device:{name}_Form", f"device:{name}_Cavity"
    od = given(f"{d}_OuterDiameter", "quantitykind:Diameter", outer, "unit:M", value_type, f"Outer diameter, {mm(outer)}. {comment}",
               task, source)
    idm = given(f"{d}_InnerDiameter", "quantitykind:Diameter", inner, "unit:M", value_type, f"Inner diameter, {mm(inner)}. {comment}",
                task, source)
    ln = given(f"{d}_Height", "quantitykind:Height", length, "unit:M", value_type, f"Length, {mm(length)}. {comment}", task, source)
    wall = (outer - inner) / 2
    v_in = math.pi / 4 * inner ** 2 * length
    v_out = math.pi / 4 * outer ** 2 * length
    calc(f"{name}_WallThickness", "Half the difference of the diameters", f"({outer:g} m - {inner:g} m) / 2 = {g(wall)} m.",
         f"{d}_WallThickness", "quantitykind:Thickness", wall, "unit:M", [od, idm])
    e_in = calc(f"{name}_InnerVolume", "Cylinder from the inner diameter and the length",
                f"pi/4 x ({inner:g} m)^2 x {length:g} m = {g(v_in)} m3.", f"{d}_InnerVolume", "quantitykind:Volume", v_in,
                "unit:M3", [idm, ln])
    e_out = calc(f"{name}_OuterVolume", "Cylinder from the outer diameter and the length",
                 f"pi/4 x ({outer:g} m)^2 x {length:g} m = {g(v_out)} m3.", f"{d}_OuterVolume", "quantitykind:Volume", v_out,
                 "unit:M3", [od, ln])
    lib.add({"@id": form, "@type": "cpo:TubeForm",
             "rdfs:comment": f"Tube of {mm(outer)} outer and {mm(inner)} inner diameter, {mm(length)} long; the wall and both "
                             f"volumes follow from them.",
             "cpo:hasWallThickness": ref(f"{d}_WallThickness"), "cpo:hasInnerDiameter": ref(f"{d}_InnerDiameter"),
             "cpo:hasOuterDiameter": ref(f"{d}_OuterDiameter"), "cpo:hasInnerVolume": ref(f"{d}_InnerVolume"),
             "cpo:hasOuterVolume": ref(f"{d}_OuterVolume"), "cpo:hasHeight": ref(f"{d}_Height"),
             "cpo:hasCavityForm": ref(cavity), "cpo:hasHeightToDiameterRatio": ref(f"{form}_HeightToDiameterRatio"),
             "cpo:hasDiameterRatio": ref(f"{form}_DiameterRatio")})
    lib.add({"@id": cavity, "@type": "cpo:SolidCylinderForm",
             "rdfs:comment": "The space the tube holds its content in. No numbers of its own: every parameter is the one the "
                             "tube uses in the opposite role (see cpo:hasCavityForm), as for device:sparger001_Cavity.",
             "cpo:hasDiameter": ref(f"{d}_InnerDiameter"), "cpo:hasHeight": ref(f"{d}_Height"),
             "cpo:hasOuterVolume": ref(f"{d}_InnerVolume"),
             "cpo:hasHeightToDiameterRatio": ref(f"{cavity}_HeightToDiameterRatio")})
    for ratio in (f"{form}_HeightToDiameterRatio", f"{form}_DiameterRatio", f"{cavity}_HeightToDiameterRatio"):
        empty(ratio, "quantitykind:LengthRatio")
    return v_out, v_in, e_out, e_in


def body(name, spec, volume_from=None, mass=None, mass_comment=None, mass_type="hlo:Assumed", mass_task=ASSUME,
         mass_source=None, bounding=None):
    """Body material and its solid phase. Either the volume is outer minus inner volume
    (volume_from = (v_out, v_in, evidence out, evidence in)) and the mass follows from the density,
    or the mass is given and the volume follows from it - a housing is not solid."""
    d, phase = f"device:{name}", f"material:{name}_Body_SolidPhase"
    word, rho = spec["word"], spec["density"]
    density = note(spec["density_task"], lib.value(f"{phase}_Density", "quantitykind:Density", "Reference", rho,
                                                    "unit:KiloGM-PER-M3", "hlo:Literature", spec["density_comment"],
                                                    spec["density_task"], source=spec["source"]))
    if volume_from:
        v_out, v_in, e_out, e_in = volume_from
        volume = v_out - v_in
        e_vol = calc(f"{name}_Body_SolidPhase_Volume", f"{word.capitalize()} of the wall",
                     f"Outer volume minus inner volume: {g(v_out)} m3 - {g(v_in)} m3 = {g(volume)} m3.",
                     f"{phase}_Volume", "quantitykind:Volume", volume, "unit:M3", [e_out, e_in])
        calc(f"{name}_Body_SolidPhase_Mass", f"{word.capitalize()} volume times {word} density",
             f"{g(volume)} m3 x {rho} kg/m3 = {g(volume * rho)} kg.", f"{phase}_Mass", "quantitykind:Mass", volume * rho,
             "unit:KiloGM", [e_vol, density])
    else:
        m = given(f"{phase}_Mass", "quantitykind:Mass", mass, "unit:KiloGM", mass_type, mass_comment, mass_task, mass_source)
        volume = mass / rho
        text = f"From the mass ({mass:g} kg) and the {word} density ({rho} kg/m3): {mass:g} / {rho} = {g(volume)} m3."
        if bounding:
            text += f" Deliberately NOT the bounding box ({g(bounding)} m3) - the housing is not solid {word}."
        calc(f"{name}_Body_SolidPhase_Volume", f"Mass over {word} density", text, f"{phase}_Volume", "quantitykind:Volume",
             volume, "unit:M3", [m, density])
    lib.add({"@id": f"material:{name}_Body", "@type": ["cpo:BodyMaterial", "hlo:Fixed"], "schema:name": f"Body material of {name}",
             "rdfs:comment": spec["comment"], "cpo:hasVolume": ref(f"{phase}_Volume"), "cpo:fillsForm": ref(f"{d}_Form"),
             "dcterms:hasPart": ref(phase), "cpo:isBodyMaterialOf": ref(d)})
    lib.add({"@id": phase, "@type": ["cpo:SolidPhase", "hlo:Fixed"], "schema:name": f"{name} Body",
             "dcterms:isPartOf": ref(f"material:{name}_Body"), "cpo:canCreateEnergyField": False,
             "cpo:hasDispersionState": ref("cpo:Continuous"), "cpo:hasDensity": ref(f"{phase}_Density"),
             "cpo:hasVolume": ref(f"{phase}_Volume"), "cpo:hasMass": ref(f"{phase}_Mass"),
             "dcterms:hasPart": ref(spec["entity"]), "cpo:fillsForm": ref(f"{d}_Form"),
             "cpo:hasSolidStructure": ref(spec["structure"])})


def port(name, kind, device, comment=None, opens_into=None):
    entry = {"@id": f"port:{name}", "@type": [kind, "hlo:Fixed"], "cpo:isPortOf": ref(device)}
    if comment:
        entry["rdfs:comment"] = comment
    if opens_into:
        entry["cpo:opensInto"] = ref(opens_into)
    lib.add(entry)
    return ref(f"port:{name}")


def device(name, types, label, comment, origin, power, manufacturer=None, ports=(), composite=False, form=True,
           location=None, part_of=None, located_at=None, extra=None):
    """A Fixed device of the K1 system, in service since the commissioning (its first and only use)."""
    d = f"device:{name}"
    entry = {"@id": d, "@type": list(types) + ["hlo:Fixed"], "schema:name": label, "rdfs:comment": comment,
             "schema:comment": ORIGIN.format(sources=origin), "cpo:isCompositeDevice": composite, "cpo:canReceivePower": power}
    if manufacturer:
        entry["cpo:hasManufacturer"] = ref(manufacturer)
    if location:
        entry["cpo:locatedInsideOf"] = ref(location)
    if located_at:
        entry["cpo:location"] = ref(located_at)
    if part_of:
        entry["dcterms:isPartOf"] = ref(part_of)
    if ports:
        entry["cpo:hasPort"] = list(ports) if len(ports) > 1 else ports[0]
    if form:
        entry.update({"cpo:madeOfMaterial": ref(f"material:{name}_Body"), "cpo:definesForm": ref(f"{d}_Form"),
                      "cpo:hasEnvelopeForm": ref(f"{d}_Form")})
    entry.update(extra or {})
    entry.update({"cpo:hasUsageHistory": [ref(COMMISSIONING)], "cpo:lastUsedPurpose": ref(COMMISSIONING),
                  "cpo:lastUsedTime": ref(f"{COMMISSIONING}_EndTime")})
    lib.add(entry)
    k1_devices.append(d)
    return entry


# ---------------------------------------------------------------------------------------------
# Reactor: housing, capillaries T1-T3, outlet tip
# ---------------------------------------------------------------------------------------------
R = "k1_reactor_001"
CAPILLARIES = [  # (identifier, inner, outer diameter, what goes in, connection in the data sheet)
    ("T1", 0.00030, 0.00040, "the compressed air", "Compressed Air"),
    ("T2", 0.00050, 0.00070, "liquid 1", "Reagent A"),
    ("T3", 0.00100, 0.00120, "liquid 2", "Reagent B"),
]
CAP_LENGTH = 0.100
TIP = (0.003175, 0.00175, 0.050)      # 1/8" outer, 0.028" wall, 50 mm long
HOUSING_MASS = 0.195


def reactor():
    parts = [f"{R}_housing"] + [f"{R}_capillary_{t}" for t, *_ in CAPILLARIES] + [f"{R}_outlet_tip"]
    device(R, ["cpo:Reactor"], "K1 Start reactor (K1-2T annular microreactor, Lab 208)",
           "Annular microreactor K1-2T of the K1 Start system by Accelerated Materials: two reagents, compressed air; a "
           "high-velocity air core forces the liquids into thin films on the walls of three coaxial capillaries (T1 air, T2 "
           "liquid 1, T3 liquid 2 and the mixing zone), where they mix and react. Composite: housing, the three capillaries "
           "and the outlet tip; the pumps and the mass flow controller are attached by tubes, not parts of it. Data sheet "
           "limits: at most 20 mL/min liquid in total, 5 L/min air, 7 bar; minimum micromixing time 0.5 ms, shear rate up to "
           "1e6 1/s; reaction length 50 mm (the mixing zone in T3 after the end of T2, about 39 uL with the air core). The "
           "five ports of the data sheet sit on the parts they lead into: Compressed Air on T1, Reagent A on T2, Reagent B on "
           "T3, Vent and Outlet on the outlet tip.",
           f"{SHEET}; {PATENT}", False, AM, composite=True, form=False, location=LAB,
           extra={"dcterms:hasPart": [ref(f"device:{p}") for p in parts], "cpo:hasEnvelopeForm": ref(f"device:{R}_Envelope"),
                  "cpo:supportsOperatingMode": [ref("cpo:Flow")]})
    cuboid(f"{R}_Envelope", f"device:{R}_Envelope", f"device:{R}_Envelope", (0.215, 0.058, 0.026), "hlo:Literature", LOOKUP,
           "Dimensions of the K1-2T as the data sheet gives them (21.5 x 5.8 x 2.6 cm).",
           "Bounding box of the reactor as the data sheet gives it; the fittings and the outlet tip stick out of it. Not "
           "derivable from the parts: the capillaries sit inside the housing.", source=SHEET)

    housing = f"{R}_housing"
    device(housing, ["cpo:Device"], "Housing of the K1 Start reactor",
           "The white box that holds the capillaries and their fittings in coaxial alignment. Nothing flows through it "
           "itself; the streams are in the capillaries.", SHEET, False, AM, part_of=f"device:{R}", located_at=f"device:{R}")
    bounding = cuboid(housing, f"device:{housing}_Form", f"device:{housing}_", (0.215, 0.058, 0.026), "hlo:Assumed", ASSUME,
                      "Assumed equal to the data sheet dimensions of the reactor - the housing is what one sees of it.",
                      "Box of the housing, assumed as large as the reactor's data sheet dimensions.")
    body(housing, PP_BODY, mass=HOUSING_MASS, bounding=bounding,
         mass_comment=("Assumed mass of the housing with its fittings, 0.195 kg: the data sheet gives 200 g for the whole "
                       "reactor; the steel outlet tip (about 2 g) and the quartz capillaries (well below 1 g) taken off and "
                       "rounded."), mass_source=SHEET)

    previous = None
    for key, inner, outer, what, label in reversed(CAPILLARIES):
        name = f"{R}_capillary_{key}"
        inlet = port(f"{name}_inlet", "cpo:DeviceInlet", f"device:{name}",
                     f"The data sheet's '{label}' connection: {what} enters capillary {key} here.")
        # T1 ends in T2, T2 in T3 (coaxial): their outlet sits in the next tube like that of the sparger in the vessel.
        outlet = port(f"{name}_outlet", "cpo:DeviceOutlet", f"device:{name}",
                      "The open end of the capillary, inside the next one - what leaves it enters that one's content directly."
                      if key != "T3" else
                      "The end of the mixing zone, inside the outlet tip - assumed: how T3 meets the tip is not known.",
                      opens_into=previous or f"device:{R}_outlet_tip")
        device(name, ["cpo:Pipe"], f"Capillary {key} of the K1 Start reactor",
               f"Capillary {key} of the coaxial arrangement: {what} flows in it"
               + (", around capillary T1" if key == "T2" else ", around capillary T2; its last 50 mm after the end of T2 are "
                  "the mixing zone (reaction length of the data sheet)" if key == "T3" else "")
               + ". Dimensions and material from the patent the K1 is built on - assumed, the commercial K1 may differ.",
               f"{SHEET}; {PATENT}", False, AM, ports=(inlet, outlet), part_of=f"device:{R}", located_at=f"device:{housing}")
        geometry = tube(name, outer, inner, CAP_LENGTH, "hlo:Assumed", ASSUME,
                        "From the patent's example reactor (precision quartz capillaries); not measured - assumed for the K1.",
                        source=PATENT)
        body(name, QUARTZ_BODY, volume_from=geometry)
        previous = f"device:{name}"

    tip = f"{R}_outlet_tip"
    vent = port(f"{tip}_vent", "cpo:DeviceInlet", f"device:{tip}",
                "The data sheet's 'Vent' line: for quenching, cleaning the tip, or as a vent port. Where it joins the flow path "
                "is not known; placed at the tip, which it serves.")
    outlet = port(f"{tip}_outlet", "cpo:DeviceOutlet", f"device:{tip}",
                  "The data sheet's 'Outlet': the product drips from the end of the tip into the collection beaker below it.",
                  opens_into="device:beaker_1L_01")
    device(tip, ["cpo:Pipe"], "Outlet tip of the K1 Start reactor",
           "The steel tube that sticks out of the bottom of the housing; the product leaves the reactor through it.",
           f"{SHEET} (photographs)", False, AM, ports=(vent, outlet), part_of=f"device:{R}", located_at=f"device:{housing}")
    outer, inner, length = TIP
    geometry = tube(tip, outer, inner, length, "hlo:Assumed", ASSUME,
                    "Assumed from the photographs of the data sheet (a 1/8 inch steel tube, 0.028 inch wall, about 5 cm long); "
                    "stainless steel confirmed as an assumption by Laura Fadler, 05.10.2026.")
    body(tip, STEEL, volume_from=geometry)


# ---------------------------------------------------------------------------------------------
# Dosing: pumps, mass flow controllers, pressure sensors
# ---------------------------------------------------------------------------------------------
PUMP_DIMS = (0.240, 0.105, 0.144)     # depth, width, height of the UI-22 (the UI-32 gives none)
PUMP_MASS = 5.6
PUMP_HEAD = (0.030, 0.004, 0.016)     # PEEK-Block, Kanal 4 mm x 16 mm (~0,2 mL)
MFC_CHANNEL = (0.006, 0.004, 0.100)   # Kanal 4 mm x 100 mm (~1,3 mL), 1 mm Wand
SENSOR = (0.010, 0.020, 0.010)        # diameter, length, mass of a built-in pressure transducer


def pressure_sensor(name, host, label, what):
    device(name, ["sosa:Sensor"], label,
           f"Pressure sensor {what} - one of the three of the K1 Start's dosing module (1 gas, 2 liquid, 0.1 bar accuracy). "
           "Where exactly it sits is assumed (Laura Fadler, 05.10.2026), its size and mass are assumed. No calibration records.",
           f"{SHEET}", True, part_of=f"device:{host}", located_at=f"device:{host}")
    cylinder(name, SENSOR[0], SENSOR[1], "A small built-in pressure transducer, not seen.")
    body(name, STEEL, mass=SENSOR[2], mass_comment="Assumed mass of a small built-in pressure transducer, 10 g - not weighed.")
    return ref(f"device:{name}")


def flow_part(name, host, label, comment, origin, manufacturer, spec, dims, size_comment, inlet_comment, outlet_comment):
    """The part of a pump or flow controller the medium runs through - a tube form with a cavity
    (its internal volume), so that a stream can lie in it and the chain bottle - tube - pump - tube -
    reactor has no gap. Inlet and outlet of the instrument sit on it."""
    inlet = port(f"{name}_inlet", "cpo:DeviceInlet", f"device:{name}", inlet_comment)
    outlet = port(f"{name}_outlet", "cpo:DeviceOutlet", f"device:{name}", outlet_comment)
    device(name, ["cpo:Device"], label, comment, origin, False, manufacturer, ports=(inlet, outlet),
           part_of=f"device:{host}", located_at=f"device:{host}")
    outer, inner, length = dims
    geometry = tube(name, outer, inner, length, "hlo:Assumed", ASSUME, size_comment)
    body(name, spec, volume_from=geometry)
    return ref(f"device:{name}")


def pumps():
    for key in ("A", "B"):
        name = f"k1_pump_{key}"
        sensor = pressure_sensor(f"{name}_pressure_sensor", name, f"Pressure sensor of pump {key} (K1 Start)",
                                 f"built into pump {key} (the UI-32 has one)")
        head = flow_part(
            f"{name}_head", name, f"Pump head of pump {key} (K1 Start)",
            "The PEEK pump head the liquid runs through: suction and delivery valves, the two plunger chambers and the "
            "channels between them, taken together as one channel of about 0.2 mL (the UI-22 moves 80 uL per stroke, two "
            "plungers). Its wall is part of the pump's housing as well - counted twice, a few grams against 5.6 kg.",
            FLOM_SHEET, FLOM, PEEK_BODY, PUMP_HEAD,
            "Assumed channel of 4 mm inner diameter and 16 mm length (about 0.2 mL internal volume) in a 30 mm PEEK block - "
            "not measured.", "Suction side of the pump head.", "Delivery side of the pump head.")
        device(name, ["cpo:Pump"], f"Pump {key} of the K1 Start (FLOM Intelligent Pump UI-32-110P)",
               f"Pump {key} of the K1 Start's dosing module (the data sheet's 'Pump {key}'): a FLOM Intelligent Pump UI-32-110P, "
               "dual-plunger, low pulsation, with a built-in pressure sensor; probably the PEEK pump head and the 0.001-9.999 "
               "mL/min range (read from the model number by analogy with the UI-22-110P). The K1 data sheet gives 10 bar for "
               "the Start's pumps. The liquid runs through its head (a part, with inlet and outlet); size and mass are those "
               "of the UI-22, assumed.", f"{SHEET}; {FLOM_SHEET}", True, FLOM, location=LAB,
               extra={"dcterms:hasPart": [head, sensor]})
        bounding = cuboid(name, f"device:{name}_Form", f"device:{name}_", PUMP_DIMS, "hlo:Assumed", ASSUME,
                          "Assumed from the UI-22 data sheet (240 mm deep, 105 mm wide, 144 mm high) - none given for the UI-32.",
                          "Box of the pump without protruding parts.", source=FLOM_SHEET)
        body(name, STEEL, mass=PUMP_MASS, bounding=bounding, mass_source=FLOM_SHEET,
             mass_comment="Assumed mass of the pump, 5.6 kg - the UI-22's, none given for the UI-32. All of it counted as steel.")


def mass_flow_controller():
    name = "k1_mfc"
    sensor = pressure_sensor(f"{name}_pressure_sensor", name, "Gas pressure sensor of the K1 Start",
                             "of the gas line, taken as part of the mass flow controller")
    channel = flow_part(
        f"{name}_flow_channel", name, "Flow channel of the mass flow controller (K1 Start)",
        "The channel the gas runs through, past the sensor chip and the control valve, taken as one straight channel of "
        "about 1.3 mL. Its wall is part of the controller's aluminium body as well - counted twice, a few grams.",
        SFC_SHEET, SENSIRION, ALU_BODY, MFC_CHANNEL,
        "Assumed channel of 4 mm inner diameter along the body (100 mm, about 1.3 mL internal volume), 1 mm wall - not "
        "measured.", "Gas inlet (6 mm push-in fitting).", "Gas outlet (6 mm push-in fitting).")
    device(name, ["cpo:MassFlowController"], "Mass flow controller of the K1 Start (Sensirion SFC5500)",
           "The compressed air of the K1 Start is dosed by a Sensirion SFC5500 (CMOSens thermal mass flow sensor with a "
           "control valve). Flow range assumed 5 slm, the reactor's maximum air flow - the SFC5500 comes in several ranges and "
           "the label was not read (the K1 data sheet gives 30 SLPM for the Start's MFC, apparently for other reactor "
           "versions). The gas runs through its flow channel (a part, with inlet and outlet).",
           f"{SHEET}; {SFC_SHEET}", True, SENSIRION, location=LAB, extra={"dcterms:hasPart": [channel, sensor]})
    bounding = cuboid(name, f"device:{name}_Form", f"device:{name}_", (0.115, 0.0246, 0.091), "hlo:Literature", LOOKUP,
                      "From the SFC5500 data sheet (115 x 24.6 x 91 mm).", "Box of the mass flow controller.", source=SFC_SHEET)
    body(name, ALU_BODY, mass=0.27, bounding=bounding, mass_type="hlo:Literature", mass_task=LOOKUP, mass_source=SFC_SHEET,
         mass_comment="Mass of the SFC5500 with 6 mm push-in fittings, 270 g (data sheet); all of it counted as aluminium.")


# ---------------------------------------------------------------------------------------------
# Compressed air, tubes, bottles, beaker
# ---------------------------------------------------------------------------------------------
TUBES = [  # (name, designation, outer, inner diameter, from (port or opensInto), to)
    ("k1_tube_air_supply", "compressed air supply of Lab 208 to the mass flow controller", 0.006, 0.004,
     "port:L208_compressed_air_supply_outlet", "port:k1_mfc_flow_channel_inlet"),
    ("k1_tube_air_reactor", "mass flow controller to the air inlet of the reactor (capillary T1)", 0.003175, 0.0016,
     "port:k1_mfc_flow_channel_outlet", f"port:{R}_capillary_T1_inlet"),
    ("k1_tube_A_suction", "bottle no. 1 to pump A", 0.0015875, 0.0008, "device:glass_bottle_500mL_01",
     "port:k1_pump_A_head_inlet"),
    ("k1_tube_A_feed", "pump A to the Reagent A inlet of the reactor (capillary T2)", 0.0015875, 0.0008,
     "port:k1_pump_A_head_outlet", f"port:{R}_capillary_T2_inlet"),
    ("k1_tube_B_suction", "bottle no. 2 to pump B", 0.0015875, 0.0008, "device:glass_bottle_500mL_02",
     "port:k1_pump_B_head_inlet"),
    ("k1_tube_B_feed", "pump B to the Reagent B inlet of the reactor (capillary T3)", 0.0015875, 0.0008,
     "port:k1_pump_B_head_outlet", f"port:{R}_capillary_T3_inlet"),
]
joints = []              # (port, port): screwed, cpo:isConnectedTo on both sides


def tubes():
    for name, what, outer, inner, start, end in TUBES:
        if start.startswith("device:"):
            inlet = port(f"{name}_inlet", "cpo:DeviceInlet", f"device:{name}",
                         "The open end of the tube, dipped into the bottle - it draws straight from the bottle's content.",
                         opens_into=start)
        else:
            inlet = port(f"{name}_inlet", "cpo:DeviceInlet", f"device:{name}", "Screwed onto the port it is connected to.")
            joints.append((inlet["@id"], start))
        outlet = port(f"{name}_outlet", "cpo:DeviceOutlet", f"device:{name}", "Screwed onto the port it is connected to.")
        joints.append((outlet["@id"], end))
        size = ("6 mm outer, 4 mm inner diameter, to fit the 6 mm push-in fittings of the mass flow controller" if outer == 0.006
                else "1/8 inch outer, 1.6 mm inner diameter - an air line of 0.8 mm would be far too narrow for 5 L/min"
                if outer == 0.003175 else "1/16 inch outer, 0.8 mm inner diameter, the usual size for such pumps")
        device(name, ["cpo:Pipe"], f"PTFE tube, {what} (K1 Start)",
               f"Tube from {what}: {size}; 1 m long. Material, size and length assumed (agreed with Laura Fadler, 05.10.2026). "
               "Its ends are joined to the ports of the devices (cpo:isConnectedTo; the suction end dips into the bottle, "
               "cpo:opensInto); the stream in it belongs to the crate.",
               "assumption, no source", False, ports=(inlet, outlet), location=LAB)
        geometry = tube(name, outer, inner, 1.0, "hlo:Assumed", ASSUME, "Assumed, not measured.")
        body(name, PTFE_BODY, volume_from=geometry)


def connect():
    """cpo:isConnectedTo on both ports of every joint (symmetric, read without a reasoner)."""
    for a, b in joints:
        for this, other in ((a, b), (b, a)):
            lib.find(this)["cpo:isConnectedTo"] = ref(other)


def air_supply():
    name = "L208_compressed_air_supply"
    task = f"task:assuming_{name}"
    values, density = supply_pipe(
        lib, name, "Compressed air supply of Lab 208", LAB, 0.012, 0.001, 1.0, "organization:ExampleCorp", STEEL,
        "Compressed air", [("chem:Molecule_0006", "Nitrogen"), ("chem:Molecule_0005", "Oxygen")],
        ("2020-01-06T08:00:00Z", "2020-01-06T16:00:00Z"), task,
        "The compressed air line of Lab 208, from the building supply to its outlet in the room - the last stretch of it "
        "as a device. The K1 Start takes its air from here (Laura Fadler, 05.10.2026). Size, material and installation "
        "assumed like for device:L109_DI_water_supply.", state="gas", medium="air")
    lib.find(f"device:{name}")["schema:comment"] = ORIGIN.format(sources="assumption, no source")
    note(STEEL["density_task"], density)
    lib.task(task, "cpo:AssumptionTask", "Assuming the state of the compressed air supply of Lab 208",
             "The line is taken as always filled with dry air (nitrogen and oxygen, the minor gases left out), and as "
             "installed with the lab like the deionised water supply of Lab 109; there is no record of when.", determines=values)


def glassware():
    bottle = container_template(
        lib, "glass_bottle_500mL", "Glass bottle 500 mL", 0.086, 0.130, 0.003, "organization:ExampleCorp", device_class="cpo:Vessel",
        comment="TEMPLATE of a 500 mL laboratory bottle (GL 45), not one identifiable bottle: the bottles of this kind "
                "specialize it (hlo:specializationOf) and take over its form, glass and opening. Approximated as a plain glass "
                "cup - the neck is left out; brim-full it holds about 600 mL.")
    beaker = container_template(
        lib, "beaker_1L", "Beaker 1 L", 0.105, 0.145, 0.002, "organization:ExampleCorp", device_class="cpo:Vessel",
        comment="TEMPLATE of a 1 L beaker (low form), not one identifiable beaker: the beakers of this kind specialize it "
                "(hlo:specializationOf) and take over its form, glass and opening. A plain glass cup.")
    for template in (bottle, beaker):
        note(GLASS_BODY["density_task"], template["density_reference"])
    for name, template, label, where in (
            ("glass_bottle_500mL_01", bottle, "Glass bottle 500 mL no. 1 (Lab 208)", "pump A draws from it"),
            ("glass_bottle_500mL_02", bottle, "Glass bottle 500 mL no. 2 (Lab 208)", "pump B draws from it"),
            ("beaker_1L_01", beaker, "Beaker 1 L no. 1 (Lab 208)", "the outlet tip of the K1 reactor drips into it")):
        lib.add({"@id": f"device:{name}", "@type": ["cpo:Vessel", "hlo:Fixed"], "schema:name": label,
                 "rdfs:comment": f"One piece of the kind {template['device']} at the K1 Start in Lab 208 - {where}.",
                 "schema:comment": ORIGIN.format(sources="assumption, no source"),
                 "hlo:specializationOf": ref(template["device"]), "cpo:locatedInsideOf": ref(LAB),
                 "cpo:hasUsageHistory": [ref(COMMISSIONING)], "cpo:lastUsedPurpose": ref(COMMISSIONING),
                 "cpo:lastUsedTime": ref(f"{COMMISSIONING}_EndTime")})
        k1_devices.append(f"device:{name}")


def commissioning():
    lib.add({"@id": COMMISSIONING, "@type": ["cpo:CommissioningTask", "hlo:Fixed"],
             "schema:name": "Commissioning of the K1 Start system in Lab 208",
             "schema:description": "The K1 Start was set up in Lab 208: reactor, pumps, mass flow controller, tubes, bottles "
                                   "and beaker. Its first use; it has not been used since (Laura Fadler, 05.10.2026). Who did "
                                   "it is not recorded.",
             "cpo:hasStartTime": ref(f"{COMMISSIONING}_StartTime"), "cpo:hasEndTime": ref(f"{COMMISSIONING}_EndTime"),
             "cpo:hasDuration": ref(f"{COMMISSIONING}_Duration"), "cpo:usedEquipment": [ref(d) for d in k1_devices]})
    times = [lib.instant(f"{COMMISSIONING}_{key}", "Reference", "hlo:Assumed", when,
                         f"{text} of the commissioning - assumed: 'somewhere in the middle of last year' (Laura Fadler, "
                         "05.10.2026), taken as a working day in mid-June 2025.", ASSUME_COMMISSIONING)
             for key, when, text in (("StartTime", "2025-06-16T08:00:00Z", "Start"), ("EndTime", "2025-06-16T16:00:00Z", "End"))]
    lib.add({"@id": f"{COMMISSIONING}_Duration", "@type": ["time:Duration", "hlo:Fixed", "hlo:Actual"]})
    lib.task(ASSUME_COMMISSIONING, "cpo:AssumptionTask", "Assuming when the K1 Start system was put into service",
             "There is no record of the commissioning. Laura Fadler (05.10.2026): somewhere in the middle of last year, never "
             "used since - taken as one working day in mid-June 2025.", determines=times)


def tasks():
    lib.task(ASSUME, "cpo:AssumptionTask", "Assuming the dimensions and masses of the K1 Start system",
             "Nobody has measured the K1 Start or seen inside its reactor. The capillaries are taken from the patent the K1 is "
             "built on, the housing from the data sheet, pumps from the UI-22 data sheet, tip, tubes and built-in sensors are "
             "typical sizes (agreed with Laura Fadler, 05.10.2026).", determines=determined.pop(ASSUME))
    lib.task(LOOKUP, "cpo:LiteratureLookupTask", "Looking up the K1 Start system in its data sheets",
             f"Reactor dimensions from {SHEET}; size and mass of the mass flow controller from {SFC_SHEET}. Read by Claude Code "
             "on 05.10.2026.", determines=determined.pop(LOOKUP))
    lib.task(GEOMETRY, "cpo:Task", "Working out the geometry of the K1 Start system",
             "Volumes, wall thicknesses and masses from the given or assumed dimensions. Holds the individual calculations "
             "together.", extra={"dcterms:hasPart": [ref(p) for p in calculations]})
    lib.find(GEOMETRY)["@type"] = ["cpo:Task", "hlo:Fixed"]
    del lib.find(GEOMETRY)["cpo:performedBy"]
    for spec, name, text in ((QUARTZ_BODY, "fused quartz", "Fused quartz (fused silica) is 2200 kg/m3."),
                             (PTFE_BODY, "PTFE", "PTFE is 2150-2200 kg/m3 depending on crystallinity. Recorded as 2200 kg/m3."),
                             (ALU_BODY, "aluminium", "Aluminium alloys are 2660-2810 kg/m3. Recorded as 2700 kg/m3."),
                             (PEEK_BODY, "PEEK", "Unfilled PEEK is 1300-1320 kg/m3. Recorded as 1300 kg/m3.")):
        lib.task(spec["density_task"], "cpo:LiteratureLookupTask", f"Looking up the density of {name}", text,
                 determines=determined.pop(spec["density_task"]))
    lib.times_task("Assuming when the K1 Start system entries were worked out",
                   f"None of the tasks behind the K1 Start entries was recorded with a time. Their start times are stamped with "
                   f"the moment the entries were written ({STAMP}) - an upper bound, not the moment the work happened. This "
                   f"task's own start time is among them.")


# ---------------------------------------------------------------------------------------------
# Chemical Entity and Organization Library
# ---------------------------------------------------------------------------------------------
def chemical_entries():
    informal = ("Informal entry, not a single chemical species - {what}. Same reasoning as chem:ChemicalEntity_0001 (Glass): "
                "carried as a chemical entity so a device body phase can list what it is made of, without CAS/SMILES/InChI/"
                "molar mass. Added 2026-10-05 for {use}.")
    return [{"@id": "chem:FusedQuartz", "@type": ["chebi:ChemicalEntity", "hlo:Fixed"], "schema:name": "Fused quartz",
             "cpo:isInert": True,
             "rdfs:comment": informal.format(what="fused quartz is amorphous silicon dioxide, a glass",
                                             use="the capillaries of the K1 reactor"),
             "schema:comment": ORIGIN.format(sources=PATENT)},
            {"@id": "chem:Aluminium", "@type": ["chebi:ChemicalEntity", "hlo:Fixed"], "schema:name": "Aluminium",
             "cpo:isInert": True,
             "rdfs:comment": informal.format(what="the body of an instrument is an aluminium alloy, not the pure element",
                                             use="the body of the K1 Start's mass flow controller"),
             "schema:comment": ORIGIN.format(sources=SFC_SHEET)},
            {"@id": "chem:PEEK", "@type": ["chebi:ChemicalEntity", "hlo:Fixed"], "schema:name": "PEEK",
             "cpo:isInert": True,
             "rdfs:comment": informal.format(what="polyether ether ketone is a polymer",
                                             use="the pump heads of the K1 Start"),
             "schema:comment": ORIGIN.format(sources=FLOM_SHEET)}]


def organizations():
    return [{"@id": AM, "@type": ["org:Organization", "hlo:Fixed"], "schema:name": "Accelerated Materials",
             "schema:url": "https://www.acceleratedmaterials.co",
             "rdfs:comment": "Maker of the K-series annular flow reactors (K1, K10, K100) and the AMLearn software; based in the "
                             "UK. Contact: sales@acceleratedmaterials.co.uk.",
             "schema:comment": ORIGIN.format(sources=SHEET)},
            {"@id": FLOM, "@type": ["org:Organization", "hlo:Fixed"], "schema:name": "FLOM Corporation",
             "schema:url": "https://www.flom.co.jp/eng/", "rdfs:comment": "Japanese maker of HPLC and flow chemistry pumps "
                                                                         "(Intelligent Pump series).",
             "schema:comment": ORIGIN.format(sources=FLOM_SHEET)},
            {"@id": SENSIRION, "@type": ["org:Organization", "hlo:Fixed"], "schema:name": "Sensirion AG",
             "schema:url": "https://sensirion.com", "rdfs:comment": "Swiss maker of sensors and mass flow controllers (CMOSens "
                                                                    "technology, SFC5500 series).",
             "schema:comment": ORIGIN.format(sources=SFC_SHEET)}]


def clone(entries, replacements):
    out = []
    for entry in entries:
        text = json.dumps(entry, ensure_ascii=False)
        for old, new in replacements:
            text = text.replace(old, new)
        out.append(json.loads(text))
    return out


def lab_entries(graph):
    """Lab 208 copied from Lab 108 (assumed size, textbook air), as the SVT lab was on 03.10.2026; the
    shared tasks get the copied values and calculations added."""
    old = [e for e in graph if "L108" in e["@id"]]
    old_ids = {e["@id"] for e in old}
    new = clone(old, [("L108", "L208"), ("Lab 108", "Lab 208")])
    lab = next(e for e in new if e["@id"] == LAB)
    lab["rdfs:comment"] = ("Lab 208 of the CEB building, where the K1 Start stands (Laura Fadler, 05.10.2026). Its size and "
                           "air are not known: copied from the entries of Lab 108 - assumed size, textbook air.")
    lab["schema:comment"] = ORIGIN.format(sources="assumption, copied from Lab 108")
    for entry in graph:
        if entry["@id"] in old_ids:
            continue
        for key in ("cpo:determines", "dcterms:hasPart", "cpo:hasRoom"):
            values = entry.get(key)
            if isinstance(values, list) and any(v.get("@id") in old_ids for v in values if isinstance(v, dict)):
                entry[key] = values + [ref(v["@id"].replace("L108", "L208")) for v in values
                                       if isinstance(v, dict) and v.get("@id") in old_ids]
    rooms = next(e for e in graph if e["@id"] == "task:assuming_room_dimensions")
    rooms["schema:description"] = rooms["schema:description"].replace(
        "(the SVT lab of the AVT added on 03.10.2026)", "(the SVT lab of the AVT added on 03.10.2026, Lab 208 on 05.10.2026)")
    return new


# ---------------------------------------------------------------------------------------------
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

    @property
    def graph(self):
        return self.data["@graph"]

    def extend(self, entries):
        ids = {e["@id"] for e in self.graph}
        for entry in entries:
            if entry["@id"] in ids:
                sys.exit(f"{self.path.name}: {entry['@id']} exists already - nothing written.")
            ids.add(entry["@id"])
        self.graph.extend(entries)

    def save(self):
        self.path.write_bytes(self._render(self.indent, self.final).encode("utf-8"))


def main():
    devices = LibraryFile(path_definitions.DEVICE_LIBRARY_PATH)
    chemicals = LibraryFile(path_definitions.CHEMICAL_ENTITY_LIBRARY_PATH)
    organization = LibraryFile(path_definitions.ORGANIZATION_LIBRARY_PATH)

    reactor()
    pumps()
    mass_flow_controller()
    air_supply()
    tubes()
    glassware()
    connect()
    commissioning()
    tasks()
    # Existing look-up tasks (steel, glass, PP) determine the new densities as well.
    for entry in devices.graph:
        if entry["@id"] in determined:
            entry["cpo:determines"] = entry["cpo:determines"] + [ref(i) for i in determined.pop(entry["@id"])]
    assert not determined, f"tasks without an entry: {sorted(determined)}"

    devices.extend(lib.items)
    chemicals.extend(chemical_entries())
    organization.extend(organizations())
    organization.extend(lab_entries(organization.graph))
    for library in (devices, chemicals, organization):
        library.save()
    print(f"device library: +{len(lib.items)}, chemical entity library: +3, organization library: +3 organizations and Lab 208")


if __name__ == "__main__":
    main()
