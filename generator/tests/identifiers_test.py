"""Test for the content-based IDs (helpers/identifiers.py: slugify, make_*_id, split_id,
claim_id).

What matters is what the concept promises: an ID is built from what an entity IS and never
counts; the same thing always gets the same ID; two things that would share one are an
error rather than a quiet "_2"; and a crate prefix added later changes nothing but the
prefix. It runs without the pipeline.

Run from the repository root:
    PYTHONPATH=. python generator/tests/identifiers_test.py
"""
# Runs from generator/tests/ - the generator has to be on the search path.
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import helpers.identifiers as ids

SERIES = "hlo:SeriesSpecific"
EXPERIMENT = "hlo:ExperimentSpecific"


def run():
    ok = True

    def check(label, passed):
        nonlocal ok
        if not passed:
            ok = False
        print(f"  {label:62s} [{'OK' if passed else 'WRONG'}]")

    def raises(label, error, call):
        try:
            call()
        except error:
            check(label, True)
            return
        except Exception as exc:  # noqa: BLE001
            print(f"      unexpected: {type(exc).__name__}: {exc}")
        check(label, False)

    print("=== slugify: a name becomes the name part of an ID ===")
    check("spaces become _", ids.slugify("Sample In Vial") == "Sample_In_Vial")
    check("existing _ stay", ids.slugify("Sample_In_Vial") == "Sample_In_Vial")
    check("umlauts and sharp s are transliterated", ids.slugify("Wärmeträger Größe") == "Waermetraeger_Groesse")
    check("accents fall back to the base letter", ids.slugify("Café") == "Cafe")
    check("special characters are dropped (/, :, #, %, brackets)", ids.slugify("H2 / N2: 50% (v#1)") == "H2_N2_50_v1")
    check("hyphen and digits stay", ids.slugify("RDY-Add 2") == "RDY-Add_2")
    check("the dot stays (file names)", ids.slugify("hydrogenation_data_exp1.xlsx") == "hydrogenation_data_exp1.xlsx")
    check("dots at the edges are dropped", ids.slugify(".hidden.") == "hidden")
    check("repeated and leading/trailing _ are cleaned", ids.slugify("  __a  _ b__ ") == "a_b")
    check("upper/lower case is kept", ids.slugify("GasVessel_Phase") == "GasVessel_Phase")
    raises("a name without letters/digits is an error", ValueError, lambda: ids.slugify(" %/# "))

    print("=== roots with names ===")
    check("material, series level",
          ids.make_root_id("Material", "Sample In Vial", SERIES) == "#Material_Sample_In_Vial_SeriesSpecific")
    check("Material, Experiment 2",
          ids.make_root_id("Material", "Sample In Vial", EXPERIMENT, 2) == "#Material_Sample_In_Vial_ExperimentSpecific_2")
    check("same name, other kind -> other ID (Water)",
          ids.make_root_id("Material", "Water", SERIES) != ids.make_root_id("Phase", "Water", SERIES))
    check("the same name always gives the same ID",
          ids.make_root_id("Task", "GC analysis", SERIES) == ids.make_root_id("Task", "GC analysis", SERIES))
    raises("an unknown kind is an error", ValueError, lambda: ids.make_root_id("Stream", "x", SERIES))

    print("=== levels ===")
    raises("experiment level without a number is an error", ValueError,
           lambda: ids.make_root_id("Material", "x", EXPERIMENT))
    raises("series level with a number is an error", ValueError,
           lambda: ids.make_root_id("Material", "x", SERIES, 1))
    raises("an unknown scope is an error", ValueError,
           lambda: ids.make_root_id("Material", "x", "hlo:Fixed"))
    check("without a scope there is no ending", ids.make_root_id("File", "data.xlsx") == "#File_data.xlsx")

    print("=== from the library, derived, members ===")
    check("library-based like generate_id_from_library_id",
          ids.make_library_based_id("device:vessel001", SERIES)
          == ids.generate_id_from_library_id("device:vessel001", SERIES) == "#vessel001_SeriesSpecific")
    check("the experiment version takes over the local name of the template",
          ids.make_specialization_id("#Material_Sample_In_Vial_SeriesSpecific", 2)
          == "#Material_Sample_In_Vial_ExperimentSpecific_2")
    raises("the version of a non-series ID is an error", ValueError,
           lambda: ids.make_specialization_id("#Material_X_ExperimentSpecific_1", 2))
    phase = ids.make_root_id("Phase", "Sample Phase", EXPERIMENT, 1)
    volume = ids.make_derived_id("Volume", phase, EXPERIMENT, 1)
    check("derived: role in front, owner without level",
          volume == "#Volume_Phase_Sample_Phase_ExperimentSpecific_1")
    check("on the level of the owner (experiment)",
          ids.make_owned_id("PowerInput", "#reactor001_ExperimentSpecific_2") == "#PowerInput_reactor001_ExperimentSpecific_2")
    check("on the level of the owner (series)",
          ids.make_owned_id("Source", "#Material_A_SeriesSpecific") == "#Source_Material_A_SeriesSpecific")
    check("derived from a library ID",
          ids.make_derived_id("Form", "device:vessel001", SERIES) == "#Form_vessel001_SeriesSpecific")
    reference = ids.make_member_id(volume, "Reference", 1, EXPERIMENT, 1)
    check("member: owner, role, number",
          reference == "#Volume_Phase_Sample_Phase_Reference_1_ExperimentSpecific_1")
    check("the number counts for the first one too (never only on duplicates)", reference.endswith("_Reference_1_ExperimentSpecific_1"))
    raises("member number 0 is an error", ValueError, lambda: ids.make_member_id(volume, "Reference", 0, EXPERIMENT, 1))
    raises("member number True is an error", ValueError, lambda: ids.make_member_id(volume, "Reference", True, EXPERIMENT, 1))

    print("=== zerlegen ===")
    check("split_id Experiment", ids.split_id(reference) == ("Volume_Phase_Sample_Phase_Reference_1", "ExperimentSpecific", 1))
    check("split_id Series", ids.split_id("#vessel001_SeriesSpecific") == ("vessel001", "SeriesSpecific", None))
    check("split_id Library-CURIE", ids.split_id("device:vessel001") == ("vessel001", None, None))
    # Transfer IDs of today carry the level twice - only the last one is cut off.
    legacy = "#Transfer_vessel001_opening_SeriesSpecific_0004_SeriesSpecific"
    check("only the LAST level ending is cut off",
          ids.local_name(legacy) == "Transfer_vessel001_opening_SeriesSpecific_0004")
    check("local_name agrees with short_local_name (current IDs)",
          all(ids.local_name(i) == ids.short_local_name(i) for i in (
              legacy, "#Stream_0003_ExperimentSpecific_2", "#SolidPhase_0013_SeriesSpecific",
              "reaction:ElementaryReaction_0001")))
    check("level_key: level yes, experiment number no",
          ids.level_key(reference) == "Volume_Phase_Sample_Phase_Reference_1_ExperimentSpecific")
    check("level_key: series and experiment differ",
          ids.level_key(ids.make_member_id(volume, "Reference", 1, SERIES)) != ids.level_key(reference))
    raises("level_key without a level is an error", ValueError, lambda: ids.level_key("device:vessel001"))

    print("=== key_name: the segment in the question path ===")
    check("without kind prefix and level", ids.key_name("#Material_Sample_In_Vial_ExperimentSpecific_1") == "Sample_In_Vial")
    check("series and experiment the same",
          ids.key_name("#Phase_A_SeriesSpecific") == ids.key_name("#Phase_A_ExperimentSpecific_2") == "A")
    check("library-based stays", ids.key_name("#vessel001_Body_SeriesSpecific") == "vessel001_Body")
    check("a pair of phases the same in both orders",
          ids.key_name(frozenset({"#Phase_B_SeriesSpecific", "#Phase_A_SeriesSpecific"})) == "A+B")
    check("no slash, no space",
          not any(c in ids.key_name("#Material_Sample_In_Vial_SeriesSpecific") for c in "/ "))

    print("=== claim_id: Doppelungen ===")
    graph = {"@graph": [{"@id": "#Material_Sample_In_Vial_SeriesSpecific"}]}
    todo = [{"@id": "#Phase_Sample_Phase_SeriesSpecific"}]
    check("a free ID is returned",
          ids.claim_id("#Material_Other_SeriesSpecific", graph, todo) == "#Material_Other_SeriesSpecific")
    raises("the same ID in the data graph -> error", ids.DuplicateIdError,
           lambda: ids.claim_id("#Material_Sample_In_Vial_SeriesSpecific", graph, todo))
    raises("the same ID in the to-do list -> error", ids.DuplicateIdError,
           lambda: ids.claim_id("#Phase_Sample_Phase_SeriesSpecific", graph, todo))
    raises("only upper/lower case different -> error", ids.DuplicateIdError,
           lambda: ids.claim_id(ids.make_root_id("Material", "sample in vial", SERIES), graph, todo))
    raises("spelled differently, the same slug -> error", ids.DuplicateIdError,
           lambda: ids.claim_id(ids.make_root_id("Material", "Sample   In Vial!", SERIES), graph))
    try:
        ids.claim_id("#Material_Sample_In_Vial_SeriesSpecific", graph, what="The material 'Sample In Vial'")
    except ids.DuplicateIdError as exc:
        check("the message names what to change", str(exc).startswith("The material 'Sample In Vial'"))

    print("=== translate_id: derived IDs follow their root ===")
    roots = {"#Stream_0001_SeriesSpecific": "#Material_A_SeriesSpecific",
             "#Stream_0001_ExperimentSpecific_2": "#Material_A_ExperimentSpecific_2",
             "#Stream_0011_SeriesSpecific": "#Material_B_SeriesSpecific"}
    check("the root itself", ids.translate_id("#Stream_0001_SeriesSpecific", roots) == "#Material_A_SeriesSpecific")
    check("derived, the same level",
          ids.translate_id("#Flowrate_Stream_0001_SeriesSpecific", roots) == "#Flowrate_Material_A_SeriesSpecific")
    check("derived, experiment 2 takes the experiment root",
          ids.translate_id("#Flowrate_Stream_0001_ExperimentSpecific_2", roots) == "#Flowrate_Material_A_ExperimentSpecific_2")
    check("without a root of this level the ID stays",
          ids.translate_id("#Flowrate_Stream_0001_ExperimentSpecific_1", roots) == "#Flowrate_Stream_0001_ExperimentSpecific_1")
    check("Stream_0001 does not hit Stream_0011 (word boundaries)",
          ids.translate_id("#Flowrate_Stream_0011_SeriesSpecific", roots) == "#Flowrate_Material_B_SeriesSpecific")
    check("two roots in one ID",
          ids.translate_id("#Pair_Stream_0001_Stream_0011_SeriesSpecific", roots) == "#Pair_Material_A_Material_B_SeriesSpecific")
    check("a library ID stays", ids.translate_id("device:vessel001", roots) == "device:vessel001")
    check("a series ID with a number (times of a series task) follows the series root",
          ids.translate_id("#Stream_0001_StartTime_SeriesSpecific_1", roots) == "#Material_A_StartTime_SeriesSpecific_1")
    reverse = {v: k for k, v in roots.items()}
    check("rueckwaerts",
          ids.translate_id("#Flowrate_Material_A_SeriesSpecific", reverse) == "#Flowrate_Stream_0001_SeriesSpecific")

    print("=== crate prefix added later (section 6) ===")
    original = ids.CRATE_ID_PREFIX
    try:
        ids.CRATE_ID_PREFIX = "crate:hydrogenation/"
        phase_p = ids.make_root_id("Phase", "Sample Phase", EXPERIMENT, 1)
        volume_p = ids.make_derived_id("Volume", phase_p, EXPERIMENT, 1)
        check("the root gets only the prefix",
              phase_p == "crate:hydrogenation/Phase_Sample_Phase_ExperimentSpecific_1")
        check("derived ID: prefix once, local name unchanged",
              volume_p == "crate:hydrogenation/Volume_Phase_Sample_Phase_ExperimentSpecific_1")
        check("the same local name as without the prefix", ids.local_name(volume_p) == ids.local_name(volume))
    finally:
        ids.CRATE_ID_PREFIX = original

    # Template and exemplar: if the name of the exemplar starts with that of the template, the
    # exemplar is still named after itself only once.
    with ids.library_name_alias("device:three_neck_flask_100mL", "device:three_neck_flask_100mL_01"):
        check("exemplar with the name of the template at the start: no double _01",
              ids.generate_id_from_library_id("device:three_neck_flask_100mL_01") == "#three_neck_flask_100mL_01")
        check("a part of the template is named after the exemplar",
              ids.generate_id_from_library_id("port:three_neck_flask_100mL_opening") == "#three_neck_flask_100mL_01_opening")
    with ids.library_name_alias("device:bottle_template", "device:bottle_RDY"):
        check("a part of the template is named after the exemplar (bottle)",
              ids.generate_id_from_library_id("port:bottle_template_opening") == "#bottle_RDY_opening")

    # The names of the parts too: two bottles of one template, parts of different names.
    with ids.library_name_alias("device:glass_bottle_500mL", "device:glass_bottle_500mL_02"):
        check("the name of a template part is named after the exemplar",
              ids.aliased_name("Body material of glass_bottle_500mL") == "Body material of glass_bottle_500mL_02")
        check("... also in a phase name",
              ids.aliased_name("glass_bottle_500mL Body") == "glass_bottle_500mL_02 Body")
        check("a name already naming the exemplar stays",
              ids.aliased_name("glass_bottle_500mL_02 Body") == "glass_bottle_500mL_02 Body")
        check("another device with the template's name as a prefix stays",
              ids.aliased_name("glass_bottle_500mL-x Body") == "glass_bottle_500mL-x Body")
    check("without an alias nothing changes",
          ids.aliased_name("Body material of glass_bottle_500mL") == "Body material of glass_bottle_500mL")

    print(f"\n{'ALL TESTS OK' if ok else 'ERRORS - see WRONG above'}")
    return ok


if __name__ == "__main__":
    raise SystemExit(0 if run() else 1)
