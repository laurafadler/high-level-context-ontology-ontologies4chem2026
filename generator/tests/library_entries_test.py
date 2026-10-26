"""
Test of the library entry tools: generator/workflow/library_entries/create_library_entry.py and
finish_library_entry.py, run as a person would run them - in a throwaway copy of the repository (generator,
libraries, ontologies, cache; marked as an isolated copy), so the real libraries are never touched.

Cases:
- person naming an organization that does not exist: a follow-up file for it, exit 2, nothing written;
- the organization written, then the person: people library only grows by the new block (the rest byte for
  byte), membership both ways (org:memberOf / org:hasMember), consistency check without new findings;
- a written file again: refused; a wrong ORCID and a missing required field: exit 1, nothing written;
- counter-check substances: the six substances of the eLabFTW record 7849 are taken out of the copy and made again
  from their PubChem answers (generator/tests/data/fdca_cl2_substances.json, no network): a name starting with
  a digit needs an ID; hydrogen chloride (13 CAS-like numbers) gets a question under 'open'; once answered, the
  entries are written and agree with the curated ones in everything that comes from PubChem and the choices
  (name, CAS, SMILES, InChI, InChIKey, formula, CID, molar mass, ELN record) - comments and IDs of tasks differ;
- a substance the library has already (same InChIKey): exit 1;
- container: a solid without its structure, a date without an hour, a unit that is no unit of a mass - each reported,
  nothing written; then a container written: the container in the Device Library, content, phase and receipt in the
  Material Library, every property the PBA stock container (projects/pba_synthesis/curation/archive/add_pba_stock.py) has, each
  value by the task its kind says (read or assumed);
- a cabinet in an unknown laboratory at an unknown site: the follow-up files down the chain, then written up again;
  the laboratory has every entity and property of Lab 208, its volume from mixed units, the site its gravitational
  field, and the links back (org:hasSite, cpo:hasRoom);
- labware: measured dimensions of a template, exemplars of a single-use item and a lid with both a wall and an opening
  diameter are refused; a tube (a cup with a cavity), a cap with two openings (a ring without a cavity), a screw cap with a
  wall (a cup upside down), a septum (a solid disc) and a further piece of
  the beaker template of the library are written;
- device: a balance (sosa:Sensor, body volume from its mass, model) and a stand (cylinder, counted as solid);
- prepared_container: an unknown function is refused; a solution from a hydrate bottle and the water line is written -
  its usage history starts with a commissioning (rule 5.5), then the preparation, which stands in the histories of both
  sources; a volume and a concentration known in two ways carry both (measured and planned, planned and calculated).

Run from the repository root (takes two to three minutes - every finish runs the library consistency check twice):
    python generator/tests/library_entries_test.py
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
TOOLS = Path("generator/workflow/library_entries")
FDCA_PUBCHEM = ROOT / "generator/tests/data/fdca_cl2_substances.json"  # PubChem answers, kept here for the test
RECORD = "reaction:Record_eLabFTW_7849"
FDCA = {  # ID in the library -> (name, SMILES, called, CAS or None to be asked)
    "chem:FurandicarboxylicAcid": ("2,5-Furandicarboxylic acid", "OC(=O)c1ccc(o1)C(=O)O", "FDCA", None),
    "chem:ThionylChloride": ("Thionyl chloride", "O=S(Cl)Cl", "SOCl2", None),
    "chem:FurandicarbonylDichloride": ("2,5-Furandicarbonyl dichloride", "ClC(=O)c1ccc(o1)C(=O)Cl", "FDCA-Cl2", None),
    "chem:HydrogenChloride": ("Hydrogen chloride", "Cl", "hcl", None),
    "chem:SulfurDioxide": ("Sulfur dioxide", "O=S=O", "so2", "7446-09-5"),
    "chem:Hexane": ("Hexane", "CCCCCC", "hexane", "110-54-3"),
}
COMPARED = ("schema:name", "cpo:hasCAS", "cpo:hasSMILES", "cpo:hasInChI", "cpo:hasInChIKey", "cpo:hasMolecularFormula",
            "cpo:hasPubChemCID", "schema:subjectOf")

results = []


def check(label, good, detail=""):
    results.append(good)
    print(f"{'ok ' if good else 'FAIL'} {label}" + (f"\n     {detail}" if detail and not good else ""))


def run(copy: Path, *args) -> tuple:
    done = subprocess.run([sys.executable, *map(str, args)], cwd=copy, capture_output=True, text=True, encoding="utf-8")
    return done.returncode, done.stdout + done.stderr


def create(copy: Path, entry_type: str) -> Path:
    code, out = run(copy, TOOLS / "create_library_entry.py", entry_type, "--project", "demo")
    return Path(out.split("Template written: ", 1)[1].splitlines()[0].strip())


def fill(path: Path, head: dict, entries: list):
    """Fill a template as a person would: the head fields and the entries (the template's comments go - the tool
    reads YAML)."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data.update(head)
    data["entries"] = entries
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def library(copy: Path, name: str) -> dict:
    sys.path.insert(0, str(copy / "generator"))
    from helpers.library_files import read_library
    sys.path.pop(0)
    path = copy / "libraries" / name
    graph = read_library(path)["@graph"] if (copy / "libraries/details" / name.replace(".jsonld", "_details.jsonld")).exists() \
        else json.loads(path.read_text(encoding="utf-8"))["@graph"]
    return {e["@id"]: e for e in graph if "@id" in e}


def snapshot(copy: Path) -> dict:
    return {p.relative_to(copy).as_posix(): p.read_bytes() for p in (copy / "libraries").rglob("*.jsonld")}


with tempfile.TemporaryDirectory() as tmp:
    copy = Path(tmp) / "repo"
    for part in ("generator", "libraries", "ontologies", "cache"):
        if (ROOT / part).exists():
            shutil.copytree(ROOT / part, copy / part, ignore=shutil.ignore_patterns("__pycache__"))
    (copy / "projects/demo").mkdir(parents=True)
    # The crates: the usage histories in the libraries point at their tasks, and a preparation is sorted in by time.
    for crate in list((ROOT / "projects").glob("*/crate/ro-crate-metadata.json")) + \
            list((ROOT / "projects").glob("*/crate_completed/ro-crate-metadata.json")):
        target = copy / crate.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(crate, target)
    (copy / ".isolated_copy").write_text(f"copy of {ROOT}", encoding="utf-8")
    head = {"entered_by": "Laura Fadler", "source": "Test entry of library_entries_test.py."}

    # --- person with an unknown organization -------------------------------------------------------------
    start = snapshot(copy)
    person = create(copy, "person")
    fill(person, head, [{"name": "Ada Example", "given_name": "Ada", "family_name": "Example", "orcid": "0000-0002-1825-0097",
                         "member_of": ["CEB", "Example Labs Ltd"]}])
    code, out = run(copy, TOOLS / "finish_library_entry.py", person, "--write")
    follow = sorted(person.parent.glob("organization_*.yaml"))
    check("unknown organization: exit 2, a follow-up file, nothing written",
          code == 2 and len(follow) == 1 and snapshot(copy) == start, out)
    follow_data = yaml.safe_load(follow[0].read_text(encoding="utf-8")) if follow else {}
    check("the follow-up file names the organization and who enters it",
          follow_data.get("entries", [{}])[0].get("name") == "Example Labs Ltd" and follow_data.get("entered_by") == "Laura Fadler")

    # --- the organization, then the person ---------------------------------------------------------------
    fill(follow[0], head, [{"name": "Example Labs Ltd", "url": "https://example.org/labs"}])
    code, out = run(copy, TOOLS / "finish_library_entry.py", follow[0])
    check("organization, dry run: exit 0, nothing written", code == 0 and snapshot(copy) == start, out)
    code, out = run(copy, TOOLS / "finish_library_entry.py", follow[0], "--write")
    check("organization written", code == 0 and "organization:ExampleLabsLtd" in library(copy, "organization_library.jsonld"), out)
    people_before = (copy / "libraries/people_library.jsonld").read_bytes()
    code, out = run(copy, TOOLS / "finish_library_entry.py", person, "--write")
    people_after = (copy / "libraries/people_library.jsonld").read_bytes()
    organizations = library(copy, "organization_library.jsonld")
    entry = library(copy, "people_library.jsonld").get("person:AdaExample", {})
    check("person written, consistency check without new findings", code == 0 and "nothing new" in out, out)
    cut = people_before.rstrip().rfind(b"}", 0, people_before.rstrip().rfind(b"]"))
    check("people library: only the new block added", people_after.startswith(people_before[:cut + 1])
          and people_after.endswith(people_before[cut + 1:]))
    check("membership both ways",
          {m["@id"] for m in entry.get("org:memberOf", [])} == {"organization:CEB", "organization:ExampleLabsLtd"}
          and {"@id": "person:AdaExample"} in organizations["organization:CEB"]["org:hasMember"]
          and {"@id": "person:AdaExample"} in organizations["organization:ExampleLabsLtd"]["org:hasMember"])
    code, out = run(copy, TOOLS / "finish_library_entry.py", person, "--write")
    check("a written file again: refused", code == 1 and "Written already" in out, out)

    # --- wrong entries ---------------------------------------------------------------------------------------
    state = snapshot(copy)
    wrong = create(copy, "person")
    fill(wrong, head, [{"name": "Bea Example", "given_name": "Bea", "orcid": "0000-0002-1825-0098"}])
    code, out = run(copy, TOOLS / "finish_library_entry.py", wrong, "--write")
    check("wrong ORCID check character and missing family_name: exit 1, nothing written",
          code == 1 and "check character" in out and "family_name" in out and snapshot(copy) == state, out)

    # --- substances: counter-check with the eLabFTW 7849 substances -----------------------------------------
    chemicals = copy / "libraries/chemical_entity_library.jsonld"
    sys.path.insert(0, str(copy / "generator"))
    from helpers.file_handling import load_jsonld, save_jsonld
    sys.path.pop(0)
    curated = library(copy, "chemical_entity_library.jsonld")
    data = load_jsonld(chemicals)
    gone = {i for c in FDCA for i in (c, f"{c}_MolarMass", f"{c}_MolarMass_Reference_1")}
    data["@graph"] = [e for e in data["@graph"] if e.get("@id") not in gone]
    for entity in data["@graph"]:      # the curated lookup task no longer determines what was taken out
        if isinstance(entity.get("cpo:determines"), list):
            entity["cpo:determines"] = [r for r in entity["cpo:determines"] if r.get("@id") not in gone]
    save_jsonld(data, chemicals)
    state = snapshot(copy)
    substances = create(copy, "substance")
    shutil.copy(FDCA_PUBCHEM, substances.with_name(f"{substances.stem}_pubchem.json"))
    fill(substances, head, [{"name": name, "smiles": smiles, "called": called, "eln_record": RECORD, **({"cas": cas} if cas else {})}
                            for name, smiles, called, cas in FDCA.values()])
    code, out = run(copy, TOOLS / "finish_library_entry.py", substances)
    check("a name starting with a digit needs an ID", code == 1 and "entries[1].id" in out and "entries[3].id" in out, out)
    data = yaml.safe_load(substances.read_text(encoding="utf-8"))
    data["entries"][0]["id"] = "chem:FurandicarboxylicAcid"
    data["entries"][2]["id"] = "chem:FurandicarbonylDichloride"
    substances.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    code, out = run(copy, TOOLS / "finish_library_entry.py", substances)
    asked = yaml.safe_load(substances.read_text(encoding="utf-8")).get("open") or []
    check("hydrogen chloride: a question under 'open', exit 2, nothing written",
          code == 2 and [(q["entry"], q["field"]) for q in asked] == [(4, "cas")] and "7647-01-0" in asked[0]["options"]
          and snapshot(copy) == state, out)
    code, out = run(copy, TOOLS / "finish_library_entry.py", substances)
    check("asked again: the question is not repeated", code == 2 and
          len(yaml.safe_load(substances.read_text(encoding="utf-8"))["open"]) == 1, out)
    data = yaml.safe_load(substances.read_text(encoding="utf-8"))
    data["entries"][3]["cas"] = "7647-01-0"
    substances.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    code, out = run(copy, TOOLS / "finish_library_entry.py", substances, "--write")
    made = library(copy, "chemical_entity_library.jsonld")
    check("substances written, consistency check without new findings", code == 0 and "nothing new" in out, out)
    for chem_id in FDCA:
        old, new = curated[chem_id], made.get(chem_id, {})
        differing = [k for k in COMPARED if old.get(k) != new.get(k)]
        old_mass = curated[f"{chem_id}_MolarMass_Reference_1"]["qudt:value"]
        new_mass = made.get(f"{chem_id}_MolarMass_Reference_1", {}).get("qudt:value")
        check(f"{chem_id} agrees with the curated entry", not differing and old_mass == new_mass,
              f"differs in {differing}, molar mass {old_mass} / {new_mass}")
    # the lookup task this file made - not one a real library entry brought already (PBA: sulfuric acid)
    task = next((e for i, e in made.items() if i.startswith("task:looking_up_substance_") and i not in curated), {})
    times = made["task:assuming_chemical_entity_library_task_times"]
    check("one lookup task determines the six molar masses; its start is stamped by the library's assumption task",
          len(task.get("cpo:determines", [])) == 6
          and {"@id": f"{task.get('@id')}_StartTime_Reference_1"} in times["cpo:determines"])

    again = create(copy, "substance")
    shutil.copy(FDCA_PUBCHEM, again.with_name(f"{again.stem}_pubchem.json"))
    fill(again, head, [{"name": "Thionyl chloride again", "smiles": "O=S(Cl)Cl"}])
    code, out = run(copy, TOOLS / "finish_library_entry.py", again)
    check("a substance the library has already: exit 1", code == 1 and "has this substance already" in out, out)

    # --- container: compared with a container of the PBA stock (add_pba_stock.py) ------------------------------
    pba = "device:bottle_nickel_chloride_hexahydrate_01"
    bottle = {"name": "Nickel(II) chloride hexahydrate bottle no. 2", "template": "device:glass_bottle_250mL",
              "cabinet": "lab:L208_Chemicals_Cabinet",
              "delivered": {"value": "2025-06-02T09:30:00Z", "kind": "literature", "source": "delivery note 4711"},
              "opened": {"value": "2025-06-10T08:00:00Z", "kind": "observed", "source": "date written on the label"},
              "received_by": "Meng Kong",
              "content": {"label": "Nickel(II) chloride hexahydrate, lot MKCL1234", "state": "solid", "solid_structure": "crystalline",
                          "lot": "MKCL1234", "sku": "N6136-100G", "manufacturer": "Sigma-Aldrich",
                          "mass": {"value": 0.1, "unit": "KiloGM", "kind": "literature", "source": "label"},
                          "expires": {"value": "2030-06-01T00:00:00Z", "kind": "literature", "source": "label"},
                          "species": [{"substance": "Nickel(II) chloride hexahydrate",
                                       "fraction": {"value": 0.98, "kind": "assumed", "source": "usual grade, no certificate"}}]}}
    wrong = create(copy, "container")
    broken = json.loads(json.dumps(bottle))
    broken["delivered"]["value"] = "2025-06-02"
    broken["content"]["mass"]["unit"] = "LB_X"
    del broken["content"]["solid_structure"]
    fill(wrong, head, [broken])
    state = snapshot(copy)
    code, out = run(copy, TOOLS / "finish_library_entry.py", wrong, "--write")
    check("container: a solid without structure is reported, nothing written",
          code == 1 and "solid_structure" in out and snapshot(copy) == state, out)
    del broken["content"]["mass"]
    broken["content"]["solid_structure"] = "crystalline"
    fill(wrong, head, [broken])
    code, out = run(copy, TOOLS / "finish_library_entry.py", wrong)
    check("container: a date without an hour is reported", code == 1 and "delivered.value" in out, out)
    broken["delivered"]["value"] = "2025-06-02T09:30:00Z"
    broken["content"]["mass"] = {"value": 1, "unit": "LB_X", "kind": "measured", "source": "balance"}
    fill(wrong, head, [broken])
    code, out = run(copy, TOOLS / "finish_library_entry.py", wrong)
    check("container: a unit that is no unit of a mass is reported", code == 1 and "content.mass.unit" in out, out)

    containers = create(copy, "container")
    fill(containers, head, [bottle])
    code, out = run(copy, TOOLS / "finish_library_entry.py", containers, "--write")
    check("container written, consistency check (inventory, devices and contents apart) without new findings",
          code == 0 and "nothing new" in out, out)
    devices, materials = library(copy, "device_library.jsonld"), library(copy, "material_library.jsonld")
    new = "device:nickel_ii_chloride_hexahydrate_bottle_no_2"
    content_id = "material:nickel_ii_chloride_hexahydrate_bottle_no_2_Content"
    phase_id = f"{content_id}_Phase"
    check("container in the Device Library, content, phase and receipt in the Material Library",
          new in devices and all(i in materials for i in (content_id, phase_id, "task:receiving_nickel_ii_chloride_hexahydrate_bottle_no_2")))
    pba_content = pba.replace("device:", "material:") + "_Content"
    for label, ours, theirs in (("container", devices.get(new, {}), devices[pba]),
                                ("content", materials.get(content_id, {}), materials[pba_content]),
                                ("phase", materials.get(phase_id, {}), materials[f"{pba_content}_Phase"])):
        missing = set(theirs) - set(ours)
        check(f"{label}: every property of the PBA stock container is there", not missing, f"missing {sorted(missing)}")
    fraction = materials.get(f"{phase_id}_NickelIIChlorideHexahydrate_Concentration_Reference_1", {})
    delivery = materials.get("task:receiving_nickel_ii_chloride_hexahydrate_bottle_no_2_EndTime_Reference_1", {})
    check("values: assumed purity by the assuming task, delivery (literature, with source) by the reading task",
          fraction.get("hlo:hasReferenceType") == {"@id": "hlo:Assumed"}
          and fraction.get("cpo:hasDeterminationTask", {}).get("@id", "").startswith("task:assuming_container_")
          and delivery.get("hlo:hasSource") == "delivery note 4711"
          and delivery.get("cpo:hasDeterminationTask", {}).get("@id", "").startswith("task:reading_container_"))

    guessed = create(copy, "container")
    fill(guessed, head, [dict(bottle, name="Cobalt test bottle", opened=None,
                              delivered={"value": "2025-06-02T09:30:00Z", "kind": "assumed", "source": "not known"},
                              content=dict(bottle["content"], mass=None, expires=None,
                                           species=[{"substance": "Nickel(II) chloride hexahydrate"}]))])
    code, out = run(copy, TOOLS / "finish_library_entry.py", guessed, "--write")
    materials, devices = library(copy, "material_library.jsonld"), library(copy, "device_library.jsonld")
    status = materials.get("material:cobalt_test_bottle_Content_Phase_Occurrence_Status", {})
    check("container with an assumed delivery: its content's occurrence assumed too, no reading task",
          code == 0 and status.get("hlo:hasReference") == {"@id": "material:cobalt_test_bottle_Content_Phase_Occurrence_Status_Reference_1"}
          and "hlo:hasEvidence" not in status
          and materials.get("material:cobalt_test_bottle_Content_Phase_Occurrence_Status_Reference_1", {}).get("hlo:hasReferenceType")
          == {"@id": "hlo:Assumed"}
          and not any(i.startswith(f"task:reading_{guessed.stem}") for i in devices), out)

    # --- cabinet -> laboratory -> site: follow-ups down the chain, then written up again; compared with Lab 208 -------
    cabinet = create(copy, "cabinet")
    fill(cabinet, head, [{"name": "Acids cabinet, Lab 3.14", "room": "Lab 3.14"}])
    code, out = run(copy, TOOLS / "finish_library_entry.py", cabinet)
    rooms = sorted(cabinet.parent.glob("laboratory_*.yaml"))
    check("cabinet in an unknown laboratory: a laboratory file is started", code == 2 and len(rooms) == 1, out)
    assumed = {"unit": "M", "kind": "assumed", "source": "typical room, not measured"}
    fill(rooms[0], head, [{"name": "Lab 3.14", "site": "Example Campus", "width": {"value": 6, **assumed},
                           "length": {"value": 800, **assumed, "unit": "CentiM"}, "height": {"value": 3, **assumed}}])
    code, out = run(copy, TOOLS / "finish_library_entry.py", rooms[0])
    sites = sorted(cabinet.parent.glob("site_*.yaml"))
    check("laboratory at an unknown site: a site file is started", code == 2 and len(sites) == 1, out)
    fill(sites[0], head, [{"name": "Example Campus", "organization": "CEB"}])
    written = [run(copy, TOOLS / "finish_library_entry.py", path, "--write") for path in (sites[0], rooms[0], cabinet)]
    check("site, laboratory and cabinet written, consistency check without new findings",
          all(code == 0 and "nothing new" in out for code, out in written), "\n".join(out for _, out in written))
    places = library(copy, "organization_library.jsonld")

    def family(local):
        return {i.replace(local, "X"): set(e) - {"@id"} for i, e in places.items() if local in i and "Cabinet" not in i}

    old, new = family("L208"), family("Lab314")
    missing = {k: sorted(old[k] - new.get(k, set()) - {"rdfs:comment", "dcterms:isPartOf"}) for k in old}
    check("laboratory: every entity and property of Lab 208 is there (but its comment and the old shared volume task)",
          not any(missing.values()), str({k: v for k, v in missing.items() if v}))
    mass = places.get("environment:Lab314_Air_Mass_Evidence_1", {}).get("qudt:value", {}).get("@value")
    check("laboratory: volume from the dimensions in m (6 m x 800 cm x 3 m = 144 m3), air mass 172.8 kg",
          places.get("lab:Lab314_Volume_Evidence_1", {}).get("qudt:value", {}).get("@value") == "144" and mass == "172.8", mass)
    check("site: gravitational field like site:CEB_PFD, the organization names the site, the site the room",
          set(places["site:CEB_PFD"]) - {"rdfs:comment"} <= set(places.get("site:ExampleCampus", {}))
          and {"@id": "site:ExampleCampus"} in places["organization:CEB"]["org:hasSite"]
          and {"@id": "lab:Lab314"} in places["site:ExampleCampus"].get("cpo:hasRoom", [])
          and places.get("lab:AcidsCabinetLab314", {}).get("cpo:locatedInsideOf") == {"@id": "lab:Lab314"})

    # --- labware, device, prepared_container ----------------------------------------------------------------------
    def value(number, unit=None, kind="assumed", source="test value"):
        return {"value": number, "kind": kind, "source": source, **({"unit": unit} if unit else {})}

    when = "2025-06-16T08:00:00Z"
    tube = {"name": "Falcon tube 50 mL", "device_class": "vessel", "body": "polypropylene", "manufacturer": "ExampleCorp",
            "outer_diameter": value(29, "MilliM", "literature", "catalogue"), "outer_height": value(115, "MilliM", "literature", "catalogue"),
            "wall": value(1, "MilliM"), "exemplars": [{"name": "Falcon tube 50 mL no. 1", "location": "lab:L208", "commissioned": value(when)}]}
    wrong = create(copy, "labware")
    fill(wrong, head, [dict(tube, wall=value(1, "MilliM", "measured", "calliper")),
                       dict(tube, name="Pipette tip", single_use=True),
                       dict(tube, name="Wrong cap", device_class="lid", inner_diameter=value(20, "MilliM"))])
    state = snapshot(copy)
    code, out = run(copy, TOOLS / "finish_library_entry.py", wrong, "--write")
    check("labware: measured template dimensions and exemplars of a single-use item are refused",
          code == 1 and "entries[1].wall.kind" in out and "entries[2].exemplars" in out and snapshot(copy) == state, out)
    check("labware: a lid is a ring (diameter of its opening) or a cup upside down (wall) - not both",
          "entries[3].inner_diameter" in out and "entries[3].wall" not in out, out)
    labware = create(copy, "labware")
    fill(labware, head, [tube,
                         {"name": "GL45 cap with two openings", "device_class": "lid", "body": "polypropylene",
                          "outer_diameter": value(54, "MilliM"), "outer_height": value(25, "MilliM"), "inner_diameter": value(45, "MilliM"),
                          "openings": [{"name": "tube_port", "note": "takes the tube"}, {"name": "vent", "note": "left open"}],
                          "exemplars": [{"name": "GL45 cap no. 1", "location": "lab:L208", "commissioned": value(when)}]},
                         {"name": "Screw cap cup", "device_class": "lid", "body": "polypropylene",
                          "outer_diameter": value(55, "MilliM"), "outer_height": value(25, "MilliM"), "wall": value(2.5, "MilliM"),
                          "openings": [{"name": "tube_port", "note": "takes the tube"}, {"name": "vent_port", "note": "left open"}]},
                         {"name": "Septum disc", "device_class": "septum", "body": "ptfe", "single_use": True, "stock_location": "lab:L208",
                          "outer_diameter": value(9, "MilliM"), "outer_height": value(1.5, "MilliM")},
                         {"name": "Second beaker", "template": "device:beaker_1L",
                          "exemplars": [{"name": "Beaker 1 L test piece", "id": "device:beaker_1L_test_01", "location": "lab:L208",
                                         "commissioned": value(when)}]}])
    code, out = run(copy, TOOLS / "finish_library_entry.py", labware, "--write")
    devices = library(copy, "device_library.jsonld")
    check("labware written, consistency check without new findings", code == 0 and "nothing new" in out, out)
    cap = devices.get("device:gl45_cap_with_two_openings", {})
    check("labware: template, exemplar with its commissioning, two openings, a piece of an existing template",
          {"hlo:Template", "cpo:Vessel"} <= set(devices.get("device:falcon_tube_50_ml", {}).get("@type", []))
          and devices.get("device:falcon_tube_50_ml_no_1", {}).get("hlo:specializationOf") == {"@id": "device:falcon_tube_50_ml"}
          and "cpo:CommissioningTask" in devices.get("task:commissioning_falcon_tube_50_ml_no_1", {}).get("@type", [])
          and len(cap.get("cpo:hasPort", [])) == 2 and "cpo:Lid" in cap.get("@type", [])
          and devices.get("device:gl45_cap_with_two_openings_Form", {}).get("@type") == "cpo:AnnulusForm"
          and "cpo:hasCavityForm" not in devices.get("device:gl45_cap_with_two_openings_Form", {})
          and "cpo:Lid" in devices.get("device:screw_cap_cup", {}).get("@type", [])
          and devices.get("device:screw_cap_cup_Form", {}).get("@type") == devices.get("device:falcon_tube_50_ml_Form", {}).get("@type")
          and "cpo:hasCavityForm" in devices.get("device:screw_cap_cup_Form", {})
          and len(devices.get("device:screw_cap_cup", {}).get("cpo:hasPort", [])) == 2
          and devices.get("device:septum_disc_Form", {}).get("@type") == "cpo:SolidCylinderForm"
          and devices.get("device:beaker_1L_test_01", {}).get("hlo:specializationOf") == {"@id": "device:beaker_1L"}
          and devices.get("device:falcon_tube_50_ml_OuterDiameter_Reference_1", {}).get("hlo:hasSource") == "catalogue")

    gadgets = create(copy, "device")
    fill(gadgets, head, [
        {"name": "Precision balance", "device_class": "sensor", "shape": "cuboid", "length": value(0.35, "M"), "width": value(0.22, "M"),
         "height": value(0.32, "M"), "body": "steel", "mass": value(5.5, "KiloGM"), "location": "lab:L208", "commissioned": value(when),
         "model": "assumed", "powered": True, "note": "Readability 0.001 g."},
        {"name": "Clamp stand", "device_class": "device", "shape": "cylinder", "diameter": value(12, "MilliM"),
         "height": value(600, "MilliM"), "body": "steel", "location": "lab:L208", "commissioned": value(when)}])
    code, out = run(copy, TOOLS / "finish_library_entry.py", gadgets, "--write")
    devices = library(copy, "device_library.jsonld")
    balance = devices.get("device:precision_balance", {})
    body_volume = devices.get("material:precision_balance_Body_SolidPhase_Volume_Evidence_1", {}).get("qudt:value", {}).get("@value")
    stand_mass = devices.get("material:clamp_stand_Body_SolidPhase_Mass_Evidence_1", {}).get("qudt:value", {}).get("@value")
    check("device written: balance as sosa:Sensor with model, body volume from its mass (5.5 kg / 8000 kg/m3); stand solid",
          code == 0 and "nothing new" in out and "sosa:Sensor" in balance.get("@type", []) and balance.get("schema:model") == "assumed"
          and body_volume == "0.0006875" and stand_mass is not None and abs(float(stand_mass) - 3.14159265 / 4 * 0.012 ** 2 * 0.6 * 8000) < 1e-6,
          f"{out}\n{body_volume} {stand_mass}")

    solution = {"name": "Dilute nickel test solution", "template": "device:glass_bottle_250mL", "cabinet": "lab:L208_Chemicals_Cabinet",
                "start": value("2026-05-01T09:00:00Z", None, "observed", "lab notebook"),
                "end": value("2026-05-01T09:20:00Z", None, "observed", "lab notebook"), "prepared_by": "Chuyue Li",
                "preparation": {"name": "Preparing the dilute nickel test solution", "description": "Test.",
                                "functions": ["cpo:Dissolving", "Mixing"]},
                "sources": [{"container": "device:bottle_nickel_chloride_hexahydrate_01", "note": "0.5 g weighed in"},
                            {"container": "device:L208_DI_water_supply",
                             "volume": [value(0.0002, "M3", "measured", "cylinder"), value(0.2, "L", "planned", "recipe")]}],
                "content": {"label": "Ni test solution", "state": "liquid", "volume": value(0.2, "L", "measured", "cylinder"),
                            "species": [{"substance": "Water"},
                                        {"substance": "chem:Nickel2PlusIon",
                                         "concentration": [value(0.01, "MOL-PER-L", "planned", "recipe"),
                                                           value(0.01001, "MOL-PER-L", "calculated", "0.5 g / 237.69 g/mol / 0.2 L")]}]}}
    wrong = create(copy, "prepared_container")
    fill(wrong, head, [dict(solution, preparation=dict(solution["preparation"], functions=["cpo:Brewing"]))])
    code, out = run(copy, TOOLS / "finish_library_entry.py", wrong)
    check("prepared_container: an unknown function is refused", code == 1 and "cpo:Brewing" in out, out)
    prepared = create(copy, "prepared_container")
    fill(prepared, head, [solution])
    code, out = run(copy, TOOLS / "finish_library_entry.py", prepared, "--write")
    devices, materials = library(copy, "device_library.jsonld"), library(copy, "material_library.jsonld")
    task = "task:preparing_dilute_nickel_test_solution"
    concentration = materials.get("material:dilute_nickel_test_solution_Content_Phase_Nickel2PlusIon_Concentration", {})
    volume = materials.get("material:dilute_nickel_test_solution_Content_Phase_from_L208_DI_water_supply_TransferredVolume", {})
    check("prepared_container written, consistency check without new findings", code == 0 and "nothing new" in out, out)
    check("prepared_container: history commissioning then preparation; the preparation in the histories of both sources",
          devices.get("device:dilute_nickel_test_solution", {}).get("cpo:hasUsageHistory")
          == [{"@id": "task:commissioning_dilute_nickel_test_solution"}, {"@id": task}]
          and all({"@id": task} in devices[s].get("cpo:hasUsageHistory", [])
                  for s in ("device:bottle_nickel_chloride_hexahydrate_01", "device:L208_DI_water_supply")))
    check("prepared_container: values known two ways carry both; performer and functions of the preparation",
          concentration.get("hlo:hasReference") and concentration.get("hlo:hasEvidence") and volume.get("hlo:hasEvidence")
          and volume.get("hlo:hasReference")
          and materials.get(task, {}).get("cpo:performedBy") == [{"@id": "person:ChuyueLi"}]
          and materials.get(task, {}).get("cpo:realizesFunction") == [{"@id": "cpo:Dissolving"}, {"@id": "cpo:Mixing"}])

print("ALL OK" if all(results) else "SOME FAILED")
sys.exit(0 if all(results) else 1)
