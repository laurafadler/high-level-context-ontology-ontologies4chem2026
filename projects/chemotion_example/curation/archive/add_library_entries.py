"""
Library entries for the Chemotion example (Congjian Lin's collection export, reactions LCJ-R5 and
LCJ-R8: reductive catalytic fractionation (RCF) of spruce wood), written on 05.10.2026 by Claude Code -
everything except the reaction itself. Every entry says where it comes from (rule 2.10):

- chemical entity library: methanol, palladium and 4-propylguaiacol (PubChem answers in
  curation/pubchem/rcf_substances.json) with molar mass and the lookup task; spruce wood, cellulose and
  activated carbon as informal entries without a structure (like chem:FusedQuartz). Hydrogen exists.
- reaction library: the two Chemotion records as datasets (as reaction:Record_eLabFTW_7849).
- people library: Congjian Lin; organization library: his memberships (University of Cambridge, CEB,
  and the new organization NTU), a site of NTU and his lab (copied from the SVT lab - assumed size,
  textbook air).
- device library: a stainless steel autoclave 100 mL (template copied from the gas cylinder 10 L,
  dimensions assumed), a filter funnel (template copied from the beaker 1 L, dimensions assumed), a
  rotary evaporator (template written here, a box), one exemplar of each in Lin's lab, and their
  commissioning; the hydrogen supply line of the lab (copied from the compressed air supply of Lab 208).

Decided by Laura Fadler on 05.10.2026: Lin belongs to Cambridge (CEB) and NTU; the autoclave is taken
as 100 mL; a filter and a rotary evaporator are added; the hydrogen comes from a gas line of the lab -
not from a cylinder of the inventory, whose lot, cabinet and delivery nobody knows. Everything else is
suggested by Claude Code and not yet confirmed (BY).

Reads and writes the libraries through load_jsonld/save_jsonld (main file and details, rule 2.14);
the people library, which save_jsonld does not write back unchanged, by inserting text. Runs once;
stops if an entry exists already.

Usage (from the repository root):
    python projects/chemotion_example/curation/add_library_entries.py
"""
import copy
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "generator"))
from helpers.file_handling import load_jsonld, save_jsonld  # noqa: E402

LIB = ROOT / "libraries"
PUBCHEM = ROOT / "projects/chemotion_example/curation/pubchem/rcf_substances.json"
STAMP = "2026-10-05T21:00:00Z"
RECORD_R5, RECORD_R8 = "reaction:Record_Chemotion_LCJ-R5", "reaction:Record_Chemotion_LCJ-R8"
EXPORT = "Chemotion collection export d4bbc7cc-bd12-4ff2-85ba-71233b395b31.zip"
BY = "suggested by Claude Code on 05.10.2026 for the Chemotion example, not yet confirmed"
CONFIRMED = "suggested by Claude Code, confirmed by Laura Fadler on 05.10.2026 for the Chemotion example"
LAB = "lab:NTU_CongjianLin_Lab"
PERSON = "person:CongjianLin"


def ref(i):
    return {"@id": i}


def as_list(v):
    return v if isinstance(v, list) else ([] if v is None else [v])


def add(graph, entries):
    ids = {e["@id"] for e in graph}
    for e in entries:
        assert e["@id"] not in ids, f"{e['@id']} exists already"
        graph.append(e)
        ids.add(e["@id"])


def by_id(graph):
    return {e["@id"]: e for e in graph}


def append_determines(graph, task_id, new_ids):
    task = by_id(graph)[task_id]
    task["cpo:determines"] = as_list(task.get("cpo:determines")) + [ref(i) for i in new_ids]


def task_times(task_id, assumption_task):
    """Start (assumed: stamped when written down), end and duration of a library task."""
    return [
        {"@id": f"{task_id}_StartTime", "@type": ["time:Instant", "hlo:Fixed", "hlo:Actual"],
         "hlo:hasReference": ref(f"{task_id}_StartTime_Reference_1")},
        {"@id": f"{task_id}_StartTime_Reference_1", "@type": ["time:Instant", "hlo:Reference"],
         "hlo:hasReferenceType": ref("hlo:Assumed"),
         "rdfs:comment": f"No record of when this was done. Stamped with the moment the entries were written down ({STAMP}) - an upper bound, not the moment it happened.",
         "rdf:value": {"@value": STAMP, "@type": "xsd:dateTime"},
         "cpo:hasDeterminationTask": ref(assumption_task)},
        {"@id": f"{task_id}_EndTime", "@type": ["time:Instant", "hlo:Fixed", "hlo:Actual"]},
        {"@id": f"{task_id}_Duration", "@type": ["time:Duration", "hlo:Fixed", "hlo:Actual"]},
    ]


def task(task_id, task_type, name, description, determines=(), performers=("person:LauraFadler",)):
    entry = {"@id": task_id, "@type": [task_type, "hlo:Fixed"], "schema:name": name, "schema:description": description,
             "cpo:hasStartTime": ref(f"{task_id}_StartTime"), "cpo:hasEndTime": ref(f"{task_id}_EndTime"),
             "cpo:hasDuration": ref(f"{task_id}_Duration")}
    if performers:
        entry["cpo:performedBy"] = [ref(p) for p in performers]
    if determines:
        entry["cpo:determines"] = [ref(i) for i in determines]
    return entry


def value(value_id, kind, number, unit, reference_type, comment, determined_by, quantity_kind=None, evidence=False):
    """An Actual with one Reference (or, evidence=True, one calculated Evidence)."""
    part = "Evidence" if evidence else "Reference"
    actual = {"@id": value_id, "@type": [kind, "hlo:Fixed", "hlo:Actual"], f"hlo:has{part}": ref(f"{value_id}_{part}_1")}
    if quantity_kind:
        actual["qudt:hasQuantityKind"] = ref(quantity_kind)
    detail = {"@id": f"{value_id}_{part}_1", "@type": [kind, f"hlo:{part}"],
              ("hlo:hasEvidenceType" if evidence else "hlo:hasReferenceType"): ref(reference_type),
              "rdfs:comment": comment, "qudt:value": {"@value": fmt(number), "@type": "xsd:decimal"},
              "qudt:hasUnit": ref(unit), "cpo:hasDeterminationTask": ref(determined_by)}
    return [actual, detail]


def fmt(x):
    return x if isinstance(x, str) else f"{x:.6g}"


def clone(entries, replacements):
    out = []
    for e in entries:
        text = json.dumps(e, ensure_ascii=False)
        for old, new in replacements:
            text = text.replace(old, new)
        out.append(json.loads(text))
    return out


def clone_family(graph, old_ids, replacements):
    """Copies of the entries old_ids (with the replacements); tasks outside that also determined an
    old value now determine its copy as well (looked-up densities, the library's task times)."""
    old = [e for e in graph if e["@id"] in old_ids]
    new = clone(old, replacements)
    for t in graph:
        if t["@id"] in old_ids:
            continue
        added = []
        for i in as_list(t.get("cpo:determines")):
            if isinstance(i, dict) and i.get("@id") in old_ids:
                new_id = i["@id"]
                for a, b in replacements:
                    new_id = new_id.replace(a, b)
                added.append(new_id)
        if added:
            t["cpo:determines"] = as_list(t["cpo:determines"]) + [ref(i) for i in added]
    for e in new:
        if e["@id"].endswith("_StartTime_Reference_1") and "rdf:value" in e:
            e["rdf:value"] = {"@value": STAMP, "@type": "xsd:dateTime"}
            e["rdfs:comment"] = f"No record of when this was done. Stamped with the moment the entries were written down ({STAMP}) - an upper bound, not the moment it happened."
    return new


# ---------------------------------------------------------------------------------------------
# Substances
# ---------------------------------------------------------------------------------------------
LOOKUP_TASK = "task:looking_up_chemotion_rcf_substances"
SUBSTANCES = {
    # Name in the PubChem file -> (ID, name in the entry, origin, datasets)
    "Methanol": ("chem:Methanol", "Methanol",
                 "Imported on 05.10.2026 from the Chemotion records LCJ-R5 and LCJ-R8, where it is called 'MeOH' in the free text "
                 "(description, conditions, the segment 'Reaction Details'); the records give no structure.", [RECORD_R5, RECORD_R8]),
    "Palladium": ("chem:Palladium", "Palladium",
                  "Imported on 05.10.2026 from the Chemotion records LCJ-R5 and LCJ-R8, where the catalyst is called '5 wt% Pd/C' in the "
                  "free text; the records give no structure. The palladium of the catalyst; its support is chem:ActivatedCarbon.",
                  [RECORD_R5, RECORD_R8]),
    "4-Propylguaiacol": ("chem:Propylguaiacol", "4-Propylguaiacol",
                         "From the ELN (Chemotion LCJ-R8): the product sample LCJ-162 '4-Propylguaiacol' with its molecule "
                         "(2-methoxy-4-propylphenol, InChIKey PXIKRTCSSLJURC-UHFFFAOYSA-N, SMILES CCCc1ccc(c(c1)OC)O). In LCJ-R5 the main "
                         "product of the liquid phase ('guaiacyl-type monophenol', sample LCJ-36) without a structure.", [RECORD_R8, RECORD_R5]),
}


def chemical_entries():
    rows = {r["name"]: r for r in json.loads(PUBCHEM.read_text(encoding="utf-8"))}
    entries, determined = [], []
    for name, (cid_id, label, origin, records) in SUBSTANCES.items():
        row = rows[name]
        cas = row["cas_candidates"][0]
        url = f"https://pubchem.ncbi.nlm.nih.gov/compound/{row['CID']}"
        comment = (f"{origin} Structure (SMILES {row['query_smiles']}) written by curation ({BY}); identifiers and molar mass from "
                   f"PubChem, looked up by that SMILES: {url}.")
        if len(row["cas_candidates"]) > 1:
            comment += f" PubChem lists {len(row['cas_candidates'])} CAS-like numbers; {cas}, the first, is the usual one ({BY})."
        entries.append({
            "@id": cid_id, "@type": ["chebi:ChemicalEntity", "chebi:Molecule", "hlo:Fixed"],
            "schema:name": label, "cpo:hasCAS": cas, "cpo:hasSMILES": row["ConnectivitySMILES"], "cpo:hasInChI": row["InChI"],
            "cpo:hasMolecularFormula": row["MolecularFormula"], "cpo:hasInChIKey": row["InChIKey"],
            "cpo:hasPubChemCID": str(row["CID"]), "schema:comment": comment,
            "cpo:hasMolarMass": ref(f"{cid_id}_MolarMass"), "schema:subjectOf": [ref(r) for r in records]})
        entries.append({"@id": f"{cid_id}_MolarMass", "@type": ["cpo:Parameter", "hlo:Fixed", "hlo:Actual"],
                        "qudt:hasQuantityKind": ref("quantitykind:MolarMass"),
                        "hlo:hasReference": ref(f"{cid_id}_MolarMass_Reference_1")})
        entries.append({"@id": f"{cid_id}_MolarMass_Reference_1", "@type": ["cpo:Parameter", "hlo:Reference"],
                        "hlo:hasReferenceType": ref("hlo:Literature"), "hlo:hasSource": url,
                        "rdfs:comment": f"Molecular weight given by PubChem (CID {row['CID']}), computed there from the molecular formula {row['MolecularFormula']}.",
                        "qudt:value": {"@value": row["MolecularWeight"], "@type": "xsd:decimal"},
                        "qudt:hasUnit": ref("unit:GM-PER-MOL"), "cpo:hasDeterminationTask": ref(LOOKUP_TASK)})
        determined.append(f"{cid_id}_MolarMass_Reference_1")
    entries.append(task(LOOKUP_TASK, "cpo:LiteratureLookupTask", "Looking up the substances of the Chemotion records LCJ-R5 and LCJ-R8 on PubChem",
                        "Identifiers, molecular formula and molecular weight of methanol, palladium and 4-propylguaiacol, looked up on "
                        "PubChem by SMILES written by curation - the records name methanol and the catalyst only in their free text; query run "
                        "by Claude Code with generator/interfaces/pubchem/pubchem_lookup.py on 05.10.2026.", determined))
    entries += task_times(LOOKUP_TASK, "task:assuming_chemical_entity_library_task_times")

    informal = [
        ("chem:SpruceWood", "Spruce wood (Picea abies)",
         "Informal entry, not a single chemical species - wood is a lignocellulosic material (cellulose, hemicellulose, lignin, "
         "extractives). Carried as a chemical entity so a phase can list what it consists of, without CAS/SMILES/InChI/molar mass.",
         "From the ELN (Chemotion LCJ-R5, LCJ-R8): the starting material samples 'Spruce Wood — RCF Feed' (LCJ-35-1, 'aliquot from "
         "SPRUCE-2025-03 stock') and 'Spruce Wood Pellets — Raw Biomass' (LCJ-159, 'Air-dried, knife-milled Picea abies' in its "
         "parent LCJ-28), samples without a structure. The batches are not library entries.", [RECORD_R5, RECORD_R8]),
        ("chem:Cellulose", "Cellulose",
         "Informal entry, not a single chemical species - cellulose is a polymer of glucose of no fixed chain length. Carried as a "
         "chemical entity so a phase can list what it consists of, without CAS/SMILES/InChI/molar mass.",
         "From the ELN (Chemotion LCJ-R5): the product sample LCJ-37 'LCJ-R5-B', described as 'Carbohydrate-enriched solid residue ... "
         "Cellulose and residual hemicellulose', a sample without a structure. The hemicellulose is not an entry of its own "
         f"({BY}).", [RECORD_R5]),
        ("chem:ActivatedCarbon", "Activated carbon",
         "Informal entry, not a single chemical species - activated carbon is a porous, mostly amorphous carbon. Carried as a "
         "chemical entity so a phase can list what it consists of (here the support of the catalyst), without "
         "CAS/SMILES/InChI/molar mass.",
         f"Added by curation; not in the ELN as a substance: the records LCJ-R5 and LCJ-R8 name the catalyst '5 wt% Pd/C' in the free "
         f"text, and the carbon of a Pd/C catalyst is usually activated carbon ({BY}).", [RECORD_R5, RECORD_R8]),
    ]
    for cid_id, label, nature, origin, records in informal:
        entries.append({"@id": cid_id, "@type": ["chebi:ChemicalEntity", "hlo:Fixed"], "schema:name": label,
                        "rdfs:comment": nature, "schema:comment": origin,
                        "schema:subjectOf": [ref(r) for r in records]})
    return entries


# ---------------------------------------------------------------------------------------------
# Datasets (Reaction Library) - the reaction itself follows later
# ---------------------------------------------------------------------------------------------
def record_entries():
    common = (f"Exported by Congjian Lin as a Chemotion collection export ({EXPORT}) and given to Laura Fadler as an example on "
              "05.10.2026; the export names no version of Chemotion and no user, only the user's UUID "
              "(bf96e4ac-a80d-4544-89f2-51f67653771f). The same user created the analysis datasets, which name 'Congjian Lin' as their "
              f"creator - the creator of the record is taken from there ({BY}). The library entries it is about were imported from it "
              "(schema:about / schema:subjectOf).")
    return [
        {"@id": RECORD_R5, "@type": ["schema:Dataset"],
         "schema:name": "RCF of Spruce Wood Pellets (Chemotion reaction LCJ-R5)",
         "schema:identifier": "Chemotion LCJ-R5 (63a1c4a3-3564-46ea-8c51-1ae7f16e81cf)",
         "schema:creator": ref(PERSON),
         "rdfs:comment": ("Reaction LCJ-R5 of the collection 'Experiment', status 'done'. " + common +
                          " Its temperature field says 151 °C, its description text 200 °C - read as a copy of LCJ-R4 whose field was "
                          "changed and whose text was not (Laura Fadler, 05.10.2026)."),
         "schema:about": [ref("chem:SpruceWood"), ref("chem:Methanol"), ref("chem:Palladium"), ref("chem:ActivatedCarbon"),
                          ref("chem:Molecule_0001"), ref("chem:Propylguaiacol"), ref("chem:Cellulose")]},
        {"@id": RECORD_R8, "@type": ["schema:Dataset"],
         "schema:name": "RCF of Spruce Wood Pellets (NREL-characterized batch) (Chemotion reaction LCJ-R8)",
         "schema:identifier": "Chemotion LCJ-R8 (a92d59ea-b290-46b1-ad3b-f766908e35de)",
         "schema:creator": ref(PERSON),
         "rdfs:comment": "Reaction LCJ-R8 of the collection 'Experiment', without a status. " + common,
         "schema:about": [ref("chem:SpruceWood"), ref("chem:Methanol"), ref("chem:Palladium"), ref("chem:ActivatedCarbon"),
                          ref("chem:Molecule_0001"), ref("chem:Propylguaiacol")]},
    ]


# ---------------------------------------------------------------------------------------------
# Person (insert text - the People Library cannot be rewritten without loss)
# ---------------------------------------------------------------------------------------------
PERSON_ENTRY = {
    "@id": PERSON, "@type": ["schema:Person", "hlo:Fixed"],
    "schema:name": "Congjian Lin", "schema:givenName": "Congjian", "schema:familyName": "Lin", "schema:honorificPrefix": "Dr",
    "org:memberOf": [ref("organization:UniversityOfCambridge"), ref("organization:CEB"), ref("organization:NTU")],
    "schema:description": ("Exported the Chemotion collection with the RCF reactions LCJ-R1 to LCJ-R9 and gave it to Laura Fadler as an "
                           "example (05.10.2026); named as creator of its analysis datasets. No ORCID in the export. Memberships of "
                           "the University of Cambridge (CEB) and of NTU given by Laura Fadler on 05.10.2026.")}


def add_person():
    path = LIB / "people_library.jsonld"
    # Read as bytes: read_text would turn CRLF into LF and rewrite the whole file.
    text = path.read_bytes().decode("utf-8")
    assert PERSON not in text
    newline = "\r\n" if "\r\n" in text else "\n"
    block = "\n".join(" " * 6 + line for line in json.dumps(PERSON_ENTRY, indent=2, ensure_ascii=False).splitlines())
    end = text.rstrip().rfind("]")
    last = text.rfind("}", 0, end)
    text = text[:last + 1] + "," + newline + block.replace("\n", newline) + text[last + 1:]
    json.loads(text)
    path.write_text(text, encoding="utf-8", newline="")


# ---------------------------------------------------------------------------------------------
# Organisation, site, laboratory (copy of the SVT laboratory)
# ---------------------------------------------------------------------------------------------
LAB_NOTE = (f"Added on 05.10.2026 for the Chemotion example (Congjian Lin's reactions LCJ-R5, LCJ-R8): which room, its size and its "
            "air are not known. At NTU because the entries of the export were made between 01:54 and 06:51 UTC - working hours in "
            f"Singapore, not in Cambridge. Copied from the entries of the SVT lab - assumed size, textbook air ({BY}).")


def organization_entries(graph):
    old_ids = {e["@id"] for e in graph if "RWTH_AVT" in e["@id"] or "AVT_SVT_Lab" in e["@id"]}
    new = clone_family(graph, old_ids, [("RWTH_AVT", "NTU"), ("AVT_SVT_Lab", "NTU_CongjianLin_Lab"),
                                        ("SVT lab", "Lab of Congjian Lin")])
    entries = by_id(new)
    site = entries["site:NTU"]
    site["schema:name"] = "Nanyang Technological University, Singapore (building not known)"
    site["rdfs:comment"] = "Site of the lab of Congjian Lin. Gravity copied from the RWTH site (standard gravity). " + LAB_NOTE
    lab = entries[LAB]
    lab["schema:name"] = "Lab of Congjian Lin (NTU, room not known)"
    lab["rdfs:comment"] = LAB_NOTE
    leftovers = [e["@id"] for e in new if "Lennard" in json.dumps(e) or "eLabFTW" in json.dumps(e)]
    assert not leftovers, f"copied text still names the eLabFTW case: {leftovers}"
    ntu = {"@id": "organization:NTU", "@type": ["org:Organization", "hlo:Fixed"], "schema:name": "Nanyang Technological University (NTU)",
           "org:hasMember": [ref(PERSON)], "org:hasSite": ref("site:NTU"),
           "schema:comment": "Added by curation; not in the ELN - Congjian Lin's membership given by Laura Fadler on 05.10.2026."}
    rooms = by_id(graph)["task:assuming_room_dimensions"]
    rooms["schema:description"] = rooms["schema:description"].rstrip(".)") + ", the lab of Congjian Lin at NTU added on 05.10.2026)."
    for org in ("organization:UniversityOfCambridge", "organization:CEB"):
        entry = by_id(graph)[org]
        entry["org:hasMember"] = as_list(entry.get("org:hasMember")) + [ref(PERSON)]
    return [ntu] + new


# ---------------------------------------------------------------------------------------------
# Devices
# ---------------------------------------------------------------------------------------------
def cup_geometry(entries, name, od, h, wall, why):
    """Sets the assumed outer dimensions and wall of a copied cup template and works out the rest."""
    e = by_id(entries)
    p, m = f"device:{name}", f"material:{name}_Body_SolidPhase"
    rho = float(e[f"{m}_Density_Reference_1"]["qudt:value"]["@value"])
    inner_d, inner_h = od - 2 * wall, h - wall
    v_in = math.pi / 4 * inner_d ** 2 * inner_h
    v_out = math.pi / 4 * od ** 2 * h
    v_body = v_out - v_in
    mass = v_body * rho

    def setv(i, number, comment):
        e[i]["qudt:value"] = {"@value": fmt(number), "@type": "xsd:decimal"}
        e[i]["rdfs:comment"] = comment

    def calc(suffix, text):
        e[f"task:calculating_{name}_{suffix}"]["schema:description"] = text

    setv(f"{p}_OuterDiameter_Reference_1", od, f"Assumed outer diameter of the body, {od * 1000:g} mm - {why} Not measured.")
    setv(f"{p}_OuterHeight_Reference_1", h, f"Assumed outer height of the body, {h * 1000:g} mm. Not measured.")
    setv(f"{p}_WallThickness_Reference_1", wall, f"Assumed wall and bottom thickness, {wall * 1000:g} mm; the inner dimensions follow from it.")
    text = f"{fmt(od)} m - 2 x {fmt(wall)} m = {fmt(inner_d)} m."
    setv(f"{p}_InnerDiameter_Evidence_1", inner_d, text + " Assumed geometry, not measured."), calc("InnerDiameter", text)
    text = f"{fmt(h)} m - {fmt(wall)} m = {fmt(inner_h)} m."
    setv(f"{p}_InnerHeight_Evidence_1", inner_h, text + " Assumed geometry, not measured."), calc("InnerHeight", text)
    text = f"pi/4 x ({fmt(inner_d)} m)^2 x {fmt(inner_h)} m = {fmt(v_in)} m3."
    setv(f"{p}_InnerVolume_Evidence_1", v_in, text + " Assumed geometry, not measured."), calc("InnerVolume", text)
    text = f"pi/4 x ({fmt(od)} m)^2 x {fmt(h)} m = {fmt(v_out)} m3."
    setv(f"{p}_OuterVolume_Evidence_1", v_out, text + " Assumed geometry, not measured."), calc("OuterVolume", text)
    text = f"Outer volume minus inner volume: {fmt(v_out)} m3 - {fmt(v_in)} m3 = {fmt(v_body)} m3."
    setv(f"{m}_Volume_Evidence_1", v_body, text + " Assumed geometry, not measured."), calc("Body_SolidPhase_Volume", text)
    text = f"{fmt(v_body)} m3 x {fmt(rho)} kg/m3 = {fmt(mass)} kg."
    setv(f"{m}_Mass_Evidence_1", mass, text + " Assumed geometry, not measured."), calc("Body_SolidPhase_Mass", text)
    for i, entry in e.items():
        if "qudt:value" in entry and "Ratio" in i:
            raise SystemExit(f"ratio with a value in the template: {i} - not scaled")
    return v_in


def template_ids(graph, name):
    """The entries of a cup template (device, port, form, values, body material, tasks) - not its exemplars."""
    return {e["@id"] for e in graph if name in e["@id"] and not e["@id"].startswith((f"device:{name}_0", f"task:commissioning_{name}_0"))}


def autoclave_entries(graph):
    old, new_name = "gas_cylinder_10L", "stainless_autoclave_100mL"
    new = clone_family(graph, template_ids(graph, old), [(old, new_name), ("gas cylinder 10 l", "stainless steel autoclave 100 ml"),
                                                          ("Steel gas cylinder 10 L", "Stainless steel autoclave 100 mL")])
    e = by_id(new)
    v_in = cup_geometry(new, new_name, 0.061, 0.071, 0.008,
                        "a 100 mL autoclave approximated as a steel cup (inner 45 mm across, 63 mm deep).")
    device = e[f"device:{new_name}"]
    device["@type"] = ["cpo:Vessel", "hlo:Fixed", "hlo:Template"]
    device.pop("cpo:hasManufacturer", None)
    device["schema:name"] = "Stainless steel autoclave 100 mL (template)"
    device["rdfs:comment"] = (
        "TEMPLATE of a batch autoclave kind: the autoclaves of a lab specialize it and take over form, steel and opening. Approximated as "
        "a plain stainless steel cup with one opening, closed by its lid during the run - lid, seal, gauge and valves are left out. The "
        "Chemotion records LCJ-R5 and LCJ-R8 name the reactor only as 'stainless_autoclave' (segment 'Reaction Details'); its size is "
        f"not given - 100 mL assumed ({CONFIRMED}; inner volume {v_in * 1e6:.0f} mL), dimensions and wall {BY}. Copied from "
        "device:gas_cylinder_10L with new dimensions.")
    device["schema:comment"] = f"Added by curation; the type from the ELN (Chemotion LCJ-R5, LCJ-R8: 'stainless_autoclave'), size assumed ({CONFIRMED})."
    e[f"device:{new_name}_Form"]["rdfs:comment"] = (
        "Steel cup of the vessel kind: an assumed body of 61 mm across and 71 mm tall and an assumed 8 mm wall (a pressure vessel for "
        "50 bar); the inner dimensions and both volumes follow from them.")
    e[f"material:{new_name}_Body"]["rdfs:comment"] = "Generic stainless steel - the records say 'stainless_autoclave'; the grade is not known."
    e[f"port:{new_name}_opening"]["rdfs:comment"] = "The opening of the autoclave, closed by its lid during the run."
    e[f"task:assuming_{new_name}_dimensions"]["schema:description"] = (
        "Assumed outer dimensions of a 100 mL autoclave and a wall for 50 bar - the autoclave was not measured, its size not recorded.")
    e[f"task:assuming_{new_name}_dimensions"]["schema:name"] = "Assuming the dimensions of the stainless steel autoclave 100 mL"
    return new


def filter_entries(graph):
    old, new_name = "beaker_1L", "filter_funnel_100mL"
    new = clone_family(graph, template_ids(graph, old), [(old, new_name), ("Beaker 1 L", "Filter funnel 100 mL"),
                                                          ("beaker 1 l", "filter funnel 100 ml"), ("1 L beaker", "100 mL filter funnel")])
    e = by_id(new)
    cup_geometry(new, new_name, 0.065, 0.06, 0.003, "a glass filter funnel approximated as a glass cup.")
    device = e[f"device:{new_name}"]
    device["@type"] = ["cpo:Device", "hlo:Fixed", "hlo:Template"]
    device.pop("cpo:hasManufacturer", None)
    device["schema:name"] = "Filter funnel 100 mL (template)"
    device["rdfs:comment"] = (
        "TEMPLATE of a filter funnel kind. Recorded as a plain cpo:Device - the ontology has no filter class. Approximated as a glass "
        "cup with one opening; the filter medium and the outlet are left out. The Chemotion records LCJ-R5 and LCJ-R8 say only "
        "'filtration' (segment 'Reaction Details': product separation method; LCJ-R5: 'Filter to separate solid cellulose pulp', "
        f"LCJ-R8: 'catalyst removed by filtration'); what was used is not recorded - a filter added ({CONFIRMED}), kind, size and "
        f"dimensions {BY}. Copied from device:beaker_1L with new dimensions.")
    device["schema:comment"] = f"Added by curation; the ELN says only 'filtration' (Chemotion LCJ-R5, LCJ-R8) ({CONFIRMED})."
    e[f"device:{new_name}_Form"]["rdfs:comment"] = (
        "Glass cup: an assumed body of 65 mm across and 60 mm tall and an assumed 3 mm wall; the inner dimensions and both volumes "
        "follow from them.")
    e[f"task:assuming_{new_name}_dimensions"]["schema:description"] = "Assumed dimensions of a small glass filter funnel - not measured."
    e[f"task:assuming_{new_name}_dimensions"]["schema:name"] = "Assuming the dimensions of the filter funnel 100 mL"
    return new


def rotavap_entries():
    """A rotary evaporator as a box of steel, written here (no template of the kind in the library)."""
    name, h, w, l, mass = "rotary_evaporator", 0.6, 0.5, 0.4, 15.0
    p, m = f"device:{name}", f"material:{name}_Body"
    sp = f"{m}_SolidPhase"
    assume, outer, body = f"task:assuming_{name}_dimensions", f"task:calculating_{name}_OuterVolume", f"task:calculating_{name}_Body_SolidPhase_Volume"
    v_out, v_body = h * w * l, mass / 8000
    entries = [
        {"@id": p, "@type": ["cpo:Device", "hlo:Fixed", "hlo:Template"], "schema:name": "Rotary evaporator (template)",
         "rdfs:comment": ("TEMPLATE of a rotary evaporator kind. Recorded as a plain cpo:Device - the ontology has no evaporator class; "
                          "approximated as a box of steel, without ports (flask, condenser and bath are left out). The Chemotion record "
                          "LCJ-R5 says 'Evaporate MeOH to recover liquid phenolic fraction', LCJ-R8 'solvent evaporated' (segment "
                          f"'Reaction Details', work-up notes); with what is not recorded - a rotary evaporator added ({CONFIRMED}), "
                          f"its dimensions and mass {BY}."),
         "schema:comment": f"Added by curation; the ELN says only that the methanol was evaporated (Chemotion LCJ-R5, LCJ-R8) ({CONFIRMED}).",
         "cpo:isCompositeDevice": False, "cpo:canReceivePower": True,
         "cpo:madeOfMaterial": ref(m), "cpo:definesForm": ref(f"{p}_Form"), "cpo:hasEnvelopeForm": ref(f"{p}_Form")},
        {"@id": f"{p}_Form", "@type": "cpo:CuboidForm",
         "rdfs:comment": "Box around the evaporator: assumed 0.5 m x 0.4 m x 0.6 m.",
         "cpo:hasHeight": ref(f"{p}_Height"), "cpo:hasWidth": ref(f"{p}_Width"), "cpo:hasLength": ref(f"{p}_Length"),
         "cpo:hasOuterVolume": ref(f"{p}_OuterVolume"), "cpo:hasWidthToLengthRatio": ref(f"{p}_Form_WidthToLengthRatio"),
         "cpo:hasHeightToLengthRatio": ref(f"{p}_Form_HeightToLengthRatio")},
        {"@id": f"{p}_Form_WidthToLengthRatio", "@type": ["cpo:ProcessVariable", "hlo:Fixed", "hlo:Actual"], "qudt:hasQuantityKind": ref("quantitykind:LengthRatio")},
        {"@id": f"{p}_Form_HeightToLengthRatio", "@type": ["cpo:ProcessVariable", "hlo:Fixed", "hlo:Actual"], "qudt:hasQuantityKind": ref("quantitykind:LengthRatio")},
        {"@id": m, "@type": ["cpo:BodyMaterial", "hlo:Fixed"], "schema:name": f"Body material of {name}",
         "rdfs:comment": "Assumption: generic stainless steel, not verified against the actual instrument (glass, plastics and metal in fact).",
         "cpo:hasVolume": ref(f"{sp}_Volume"), "cpo:fillsForm": ref(f"{p}_Form"), "dcterms:hasPart": ref(sp), "cpo:isBodyMaterialOf": ref(p)},
        {"@id": sp, "@type": ["cpo:SolidPhase", "hlo:Fixed"], "schema:name": f"{name} Body", "dcterms:isPartOf": ref(m),
         "cpo:canCreateEnergyField": False, "cpo:hasDispersionState": ref("cpo:Continuous"),
         "cpo:hasDensity": ref(f"{sp}_Density"), "cpo:hasVolume": ref(f"{sp}_Volume"), "cpo:hasMass": ref(f"{sp}_Mass"),
         "dcterms:hasPart": ref("chem:ChemicalEntity_0002"), "cpo:fillsForm": ref(f"{p}_Form"), "cpo:hasSolidStructure": ref("cpo:Crystalline")},
    ]
    for dim, number in (("Height", h), ("Width", w), ("Length", l)):
        entries += value(f"{p}_{dim}", "cpo:ProcessVariable", number, "unit:M", "hlo:Assumed",
                         f"Assumed {dim.lower()} of the box around a bench rotary evaporator, not measured.", assume, f"quantitykind:{dim}")
    entries += value(f"{p}_OuterVolume", "cpo:ProcessVariable", v_out, "unit:M3", "hlo:Calculated",
                     f"Box from the assumed dimensions: {w} m * {l} m * {h} m = {fmt(v_out)} m3.", outer, "quantitykind:Volume", evidence=True)
    entries += value(f"{sp}_Density", "cpo:ProcessVariable", 8000, "unit:KiloGM-PER-M3", "hlo:Literature",
                     "Generic stainless steel (~8000 kg/m3), same assumption as for the other devices.",
                     "task:looking_up_stainless_steel_density", "quantitykind:Density")
    by = by_id(entries)
    by[f"{sp}_Density_Reference_1"]["hlo:hasSource"] = "MakeItFrom.com, AISI 304 (S30400) stainless steel; en.wikipedia.org/wiki/Stainless_steel."
    entries += value(f"{sp}_Mass", "cpo:ProcessVariable", mass, "unit:KiloGM", "hlo:Assumed",
                     "Assumed mass of a bench rotary evaporator - not weighed.", assume, "quantitykind:Mass")
    entries += value(f"{sp}_Volume", "cpo:ProcessVariable", v_body, "unit:M3", "hlo:Calculated",
                     f"From the assumed mass ({mass:g} kg) and the steel density: {mass:g} / 8000 = {fmt(v_body)} m3.", body,
                     "quantitykind:Volume", evidence=True)
    entries.append(task(assume, "cpo:AssumptionTask", "Assuming the dimensions and mass of the rotary evaporator",
                        "Assumed box and mass of a bench rotary evaporator - the instrument was not measured, not even named.",
                        [f"{p}_{d}_Reference_1" for d in ("Height", "Width", "Length")] + [f"{sp}_Mass_Reference_1"]))
    entries.append(task(outer, "cpo:CalculationTask", "Box from the assumed dimensions",
                        f"Box from the assumed dimensions: {w} m * {l} m * {h} m = {fmt(v_out)} m3.", [f"{p}_OuterVolume_Evidence_1"]))
    entries.append(task(body, "cpo:CalculationTask", "Assumed mass over steel density",
                        f"From the assumed mass ({mass:g} kg) and the steel density: {mass:g} / 8000 = {fmt(v_body)} m3.",
                        [f"{sp}_Volume_Evidence_1"]))
    for t in (assume, outer, body):
        entries += task_times(t, "task:assuming_device_library_task_times")
    return entries


COMMISSIONING = "task:commissioning_congjian_lin_rcf_setup"
EXEMPLARS = {
    "device:stainless_autoclave_100mL_01": ("cpo:Vessel", "device:stainless_autoclave_100mL", "Stainless steel autoclave 100 mL no. 1 (Lab of Congjian Lin)",
                                            "The autoclave of the Chemotion records LCJ-R5 and LCJ-R8 ('stainless_autoclave'), of the kind "
                                            "device:stainless_autoclave_100mL. Which autoclave it was is not known."),
    "device:filter_funnel_100mL_01": ("cpo:Device", "device:filter_funnel_100mL", "Filter funnel 100 mL no. 1 (Lab of Congjian Lin)",
                                      "The filter of the work-up of LCJ-R5 and LCJ-R8 ('filtration'), of the kind device:filter_funnel_100mL."),
    "device:rotary_evaporator_01": ("cpo:Device", "device:rotary_evaporator", "Rotary evaporator no. 1 (Lab of Congjian Lin)",
                                    "The evaporator of the work-up of LCJ-R5 and LCJ-R8 ('Evaporate MeOH'), of the kind device:rotary_evaporator."),
}


def exemplar_entries():
    entries = []
    for device_id, (kind, template, name, comment) in EXEMPLARS.items():
        entries.append({"@id": device_id, "@type": [kind, "hlo:Fixed"], "schema:name": name,
                        "rdfs:comment": f"{comment} ({BY}).",
                        "schema:comment": f"Added by curation; not in the ELN as a device ({CONFIRMED}).",
                        "hlo:specializationOf": ref(template), "cpo:locatedInsideOf": ref(LAB),
                        "cpo:hasUsageHistory": [ref(COMMISSIONING)], "cpo:lastUsedPurpose": ref(COMMISSIONING),
                        "cpo:lastUsedTime": ref(f"{COMMISSIONING}_EndTime")})
    entries.append({"@id": COMMISSIONING, "@type": ["cpo:CommissioningTask", "hlo:Fixed"],
                    "schema:name": "Commissioning of the RCF setup of Congjian Lin",
                    "schema:description": (f"Autoclave, filter funnel and rotary evaporator were put into service before "
                                           f"the experiments of LCJ-R5 and LCJ-R8; when and by whom is not known ({BY})."),
                    "cpo:hasStartTime": ref(f"{COMMISSIONING}_StartTime"), "cpo:hasEndTime": ref(f"{COMMISSIONING}_EndTime"),
                    "cpo:hasDuration": ref(f"{COMMISSIONING}_Duration"),
                    "cpo:usedEquipment": [ref(i) for i in EXEMPLARS]})
    # Times unknown: empty actuals, no assumption - neither the date of the experiment nor the commissioning is known.
    entries += [{"@id": f"{COMMISSIONING}_StartTime", "@type": ["time:Instant", "hlo:Fixed", "hlo:Actual"]},
                {"@id": f"{COMMISSIONING}_EndTime", "@type": ["time:Instant", "hlo:Fixed", "hlo:Actual"]},
                {"@id": f"{COMMISSIONING}_Duration", "@type": ["time:Duration", "hlo:Fixed", "hlo:Actual"]}]
    return entries


# ---------------------------------------------------------------------------------------------
# Hydrogen line of the laboratory (copy of the compressed air line of Lab 208)
# ---------------------------------------------------------------------------------------------
H2_OLD, H2_NEW = "L208_compressed_air_supply", "NTU_CongjianLin_Lab_H2_supply"


def h2_supply_entries(graph):
    old_ids = {e["@id"] for e in graph if H2_OLD in e["@id"]}
    new = clone_family(graph, old_ids, [(H2_OLD, H2_NEW), ("compressed air supply of lab 208", "hydrogen supply of the lab of Congjian Lin"),
                                        ("Compressed air supply of Lab 208", "Hydrogen supply of the lab of Congjian Lin"),
                                        ("lab:L208", LAB)])
    # The time stamps of the copy are determined by the assumption of the Device Library, not by that of the K1 system.
    for t in graph:
        if t["@id"] == "task:assuming_k1_system_entry_times":
            t["cpo:determines"] = [i for i in as_list(t["cpo:determines"]) if H2_NEW not in i["@id"]]
    moved = []
    for e in new:
        if e.get("cpo:hasDeterminationTask") == ref("task:assuming_k1_system_entry_times"):
            e["cpo:hasDeterminationTask"] = ref("task:assuming_device_library_task_times")
            moved.append(e["@id"])
    append_determines(graph, "task:assuming_device_library_task_times", moved)
    # Content: hydrogen instead of air.
    new = [e for e in new if not e["@id"].endswith(("_Content_Phase_Molecule_0005", "_Content_Phase_Molecule_0006"))]
    e = by_id(new)
    m = f"material:{H2_NEW}_Content"
    e[f"{m}_Phase"]["dcterms:hasPart"] = [ref(f"{m}_Phase_Molecule_0001")]
    e[f"{m}_Phase"]["schema:name"] = "Hydrogen (gas)"
    e[m]["schema:name"] = "Hydrogen"
    e[m]["rdfs:comment"] = "The hydrogen standing in the line. It is always there: a stream from the outlet takes from it. Its grade is not known."
    new.append({"@id": f"{m}_Phase_Molecule_0001", "@type": ["chebi:Molecule", "chebi:ChemicalEntity", "hlo:Fixed"], "schema:name": "Hydrogen",
                "hlo:specializationOf": ref("chem:Molecule_0001"), "dcterms:isPartOf": ref(f"{m}_Phase")})
    e[f"{m}_Phase_Occurrence"]["rdfs:comment"] = e[f"{m}_Phase_Occurrence"]["rdfs:comment"].replace("The air of the line", "The hydrogen of the line")
    e[f"{m}_Phase_OccurrenceStatus_Reference_1"]["rdfs:comment"] = "The line is always filled with hydrogen - an assumption about the lab, not an observation during an experiment."
    e[f"port:{H2_NEW}_outlet"].pop("cpo:isConnectedTo", None)
    device = e[f"device:{H2_NEW}"]
    device.pop("cpo:hasManufacturer", None)
    device["rdfs:comment"] = (
        "The hydrogen line of the lab of Congjian Lin, from the supply to its outlet in the room - the last stretch of it as a device. "
        "The Chemotion records LCJ-R5 and LCJ-R8 name the gas supply 'h2_cylinder' (segment 'Reaction Details'); taken as a gas line of "
        "the lab instead of a cylinder of the inventory, whose lot, cabinet and delivery are not known (Laura Fadler, 05.10.2026). Size, "
        f"material and installation assumed like for device:{H2_OLD} ({BY}).")
    device["schema:comment"] = f"Added by curation; the ELN says 'h2_cylinder' (Chemotion LCJ-R5, LCJ-R8) - modelled as a gas line ({CONFIRMED})."
    e[f"task:assuming_{H2_NEW}"]["schema:description"] = (
        "The line is taken as always filled with hydrogen (grade not known), and as installed with the lab like the compressed air "
        "supply of Lab 208; there is no record of when.")
    e[f"task:assuming_{H2_NEW}"]["schema:name"] = "Assuming the state of the hydrogen supply of the lab of Congjian Lin"
    e[f"task:commissioning_{H2_NEW}"]["schema:description"] = "The line was installed with the lab; no record of when. Its first use."
    e[f"device:{H2_NEW}_Cavity"]["rdfs:comment"] = e[f"device:{H2_NEW}_Cavity"]["rdfs:comment"].replace("holds its air in", "holds its hydrogen in")
    leftovers = [x["@id"] for x in new if "K1" in json.dumps(x) or "its air" in json.dumps(x) or "dry air" in json.dumps(x)]
    assert not leftovers, f"copied text still speaks of the compressed air: {leftovers}"
    return new


def main():
    path = LIB / "chemical_entity_library.jsonld"
    data = load_jsonld(path)
    add(data["@graph"], chemical_entries())
    append_determines(data["@graph"], "task:assuming_chemical_entity_library_task_times", [f"{LOOKUP_TASK}_StartTime_Reference_1"])
    save_jsonld(data, path)

    path = LIB / "reaction_library.jsonld"
    data = load_jsonld(path)
    add(data["@graph"], record_entries())
    save_jsonld(data, path)

    path = LIB / "organization_library.jsonld"
    data = load_jsonld(path)
    add(data["@graph"], organization_entries(data["@graph"]))
    save_jsonld(data, path)

    path = LIB / "device_library.jsonld"
    data = load_jsonld(path)
    graph = data["@graph"]
    new = autoclave_entries(graph) + filter_entries(graph) + rotavap_entries() + exemplar_entries() + h2_supply_entries(graph)
    add(graph, new)
    rotavap_times = [f"task:{t}_StartTime_Reference_1" for t in
                     ("assuming_rotary_evaporator_dimensions", "calculating_rotary_evaporator_OuterVolume",
                      "calculating_rotary_evaporator_Body_SolidPhase_Volume")]
    append_determines(graph, "task:assuming_device_library_task_times", rotavap_times)
    append_determines(graph, "task:looking_up_stainless_steel_density", ["material:rotary_evaporator_Body_SolidPhase_Density_Reference_1"])
    save_jsonld(data, path)

    add_person()
    print("Library entries added.")


if __name__ == "__main__":
    main()
