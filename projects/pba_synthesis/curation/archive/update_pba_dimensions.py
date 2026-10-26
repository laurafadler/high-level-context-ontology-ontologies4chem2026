"""
Two dimensions of the series pba_synthesis corrected (questions_meng_pba.md, G6 and G9; Laura Fadler and Meng Kong,
07.10.2026), with every value calculated from them:

- the six tubes of the K1 Start are about 50 cm long, not 1 m (G6) - length, inner and outer volume, the volume
  and the mass of the PTFE body; diameters unchanged (still assumed);
- Lab 208 is about 3 m high, 8 m long and 15 m wide (G9, estimated by Meng Kong and Laura Fadler) - instead of the
  size copied from Lab 108; room volume, air volume and air mass follow.

Both stay assumed values (hlo:Assumed): estimates, not measured. Commit the libraries afterwards.

Usage (from the repository root):
    python projects/pba_synthesis/curation/update_pba_dimensions.py
"""
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "generator" / "workflow" / "library_prerun"))
sys.path.insert(0, str(ROOT / "generator"))
import path_definitions  # noqa: E402
from fixed_reaction_from_template import LibraryFile  # noqa: E402

TUBES = ["k1_tube_air_supply", "k1_tube_air_feed", "k1_tube_A_suction", "k1_tube_A_feed", "k1_tube_B_suction", "k1_tube_B_feed"]
LENGTH = 0.5
WIDTH, ROOM_LENGTH, HEIGHT = 15.0, 8.0, 3.0
GIVEN = "Laura Fadler and Meng Kong, 07.10.2026 (questions_meng_pba.md, {})"


def dec(value):
    return {"@value": f"{value:.12g}", "@type": "xsd:decimal"}


def number(entity):
    return float(entity["qudt:value"]["@value"])


def tubes(e):
    for name in TUBES:
        od = number(e[f"device:{name}_OuterDiameter_Reference_1"])
        idia = number(e[f"device:{name}_InnerDiameter_Reference_1"])
        mass_old = e[f"material:{name}_Body_SolidPhase_Mass_Evidence_1"]
        density = float(mass_old["rdfs:comment"].split(" x ")[1].split(" kg/m3")[0])
        inner, outer = math.pi / 4 * idia ** 2 * LENGTH, math.pi / 4 * od ** 2 * LENGTH
        body, mass = outer - inner, (outer - inner) * density
        height = e[f"device:{name}_Height_Reference_1"]
        assert number(height) == 1.0, name
        height["qudt:value"] = dec(LENGTH)
        height["rdfs:comment"] = (f"Length, {LENGTH * 1000:g} mm - about 50 cm, estimated by " + GIVEN.format("G6")
                                  + "; not measured.")
        for key, value, d in (("InnerVolume", inner, idia), ("OuterVolume", outer, od)):
            ev = e[f"device:{name}_{key}_Evidence_1"]
            ev["qudt:value"] = dec(value)
            ev["rdfs:comment"] = f"pi/4 x ({d:g} m)^2 x {LENGTH:g} m = {value:.6g} m3."
        bv = e[f"material:{name}_Body_SolidPhase_Volume_Evidence_1"]
        bv["qudt:value"] = dec(body)
        bv["rdfs:comment"] = f"Outer volume minus inner volume: {outer:.6g} m3 - {inner:.6g} m3 = {body:.6g} m3."
        mass_old["qudt:value"] = dec(mass)
        mass_old["rdfs:comment"] = f"{body:.6g} m3 x {density:g} kg/m3 = {mass:.6g} kg."
        form = e[f"device:{name}_Form"]
        form["rdfs:comment"] = form["rdfs:comment"].replace("1000 mm long", f"{LENGTH * 1000:g} mm long")
        device = e[f"device:{name}"]
        assert "; 1 m long." in device["rdfs:comment"], name
        device["rdfs:comment"] = device["rdfs:comment"].replace(
            "; 1 m long. Material, size and length assumed (agreed with Laura Fadler, 05.10.2026).",
            f"; about 50 cm long ({GIVEN.format('G6')}). Material and size assumed (agreed with Laura Fadler, 05.10.2026).")


def room(o):
    for key, value, word in (("Width", WIDTH, "width"), ("Length", ROOM_LENGTH, "length"), ("Height", HEIGHT, "ceiling height")):
        ref = o[f"lab:L208_{key}_Reference_1"]
        ref["qudt:value"] = dec(value)
        ref["rdfs:comment"] = f"Estimated {word} of Lab 208, {value:g} m - estimated by {GIVEN.format('G9')}; not measured."
    volume = WIDTH * ROOM_LENGTH * HEIGHT
    v = o["lab:L208_Volume_Evidence_1"]
    v["qudt:value"] = dec(volume)
    v["rdfs:comment"] = v["rdfs:comment"].replace("4 m * 5 m * 2.5 m = 50 m3", f"{WIDTH:g} m * {ROOM_LENGTH:g} m * {HEIGHT:g} m = {volume:g} m3")
    air = o["environment:L208_Air_Volume_Evidence_1"]
    air["qudt:value"] = dec(volume)
    air["rdfs:comment"] = (air["rdfs:comment"].replace("(4 m * 5 m * 2.5 m = 50 m3, see lab:L208_Form)",
                                                       f"({WIDTH:g} m * {ROOM_LENGTH:g} m * {HEIGHT:g} m = {volume:g} m3, see lab:L208_Form)")
                           .replace("Assumed room dimensions, not measured.", "Room dimensions estimated, not measured."))
    density = number(o["environment:L208_Air_Density_Reference_1"])
    mass = o["environment:L208_Air_Mass_Evidence_1"]
    mass["qudt:value"] = dec(volume * density)
    mass["rdfs:comment"] = (f"Calculated from the room air volume ({volume:g} m3) and the assumed air density ({density:g} kg/m3): "
                            f"{volume:g} * {density:g} = {volume * density:g} kg. Recalculate if either input changes.")
    lab = o["lab:L208"]
    lab["rdfs:comment"] = ("Lab 208 of the CEB building, where the K1 Start stands (Laura Fadler, 05.10.2026). Its size is estimated "
                           f"({GIVEN.format('G9')}); its air is textbook air, as copied from Lab 108.")


def main():
    devices = LibraryFile(path_definitions.DEVICE_LIBRARY_PATH)
    organization = LibraryFile(path_definitions.ORGANIZATION_LIBRARY_PATH)
    e = devices.by_id()
    if number(e["device:k1_tube_A_suction_Height_Reference_1"]) == LENGTH:
        sys.exit("The tubes are 0.5 m already - nothing written.")
    tubes(e)
    room(organization.by_id())
    devices.save()
    organization.save()
    print("6 tubes: 0.5 m; Lab 208: 15 m x 8 m x 3 m")


if __name__ == "__main__":
    main()
