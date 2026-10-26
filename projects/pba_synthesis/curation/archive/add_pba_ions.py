"""
Ionic chemistry of the Prussian blue analogue (PBA) series pba_synthesis - library entries written on
06.10.2026 by Claude Code; decided by Laura Fadler and Meng Kong in the same session:

- The salts are supplied and weighed in as hydrates (K4[Fe(CN)6]*3H2O, NiCl2*6H2O, MnCl2*4H2O). Dissolving
  one releases its ions and its water of crystallization at once - one reaction per hydrate
  ("Dissolution of ..."), meant to take place at the interface between the solid salt and the water
  (the hydrate leaves the solid, the ions and the water enter the liquid).
- In solution the PBA forms from the ions: net-ionic reactions, e.g. 2 Ni2+ + [Fe(CN)6]4- > Ni2[Fe(CN)6];
  potassium and chloride stay in solution as spectator ions.

Writes:
- chemical entity library: the ions K+, Cl-, Mn2+, Fe2+, Co2+, Ni2+, Cu2+, Zn2+, [Fe(CN)6]4-, [Fe(CN)6]3-
  and the three hydrates weighed in so far; identifiers and molar masses from PubChem
  (curation/pubchem/pba_ions_hydrates.json, looked up by SMILES on 06.10.2026; for two the record that
  carries the CAS number was found by name, and the CAS number of the ferrocyanide ion is not on PubChem);
- reaction library: the three dissolutions, and twelve net-ionic TEMPLATES - one metal and mixtures of
  two to six, each with ferrocyanide and with ferricyanide, coefficients from the charge balance. The
  metal ions are placeholders shared by all templates (metal 1 to 6), each template has its own product
  placeholder. The fixed reactions of a series are made from them with curation/pba_reactions.py.

The templates written on 05.10.2026 by add_pba_chemistry.py (from potassium hexacyanoferrate and the
metal chlorides, with KCl as by-product) and the two fixed reactions made from them are taken out of the
reaction library and kept in curation/archive/ (see the README there). The new templates and fixed
reactions use the same IDs (reaction:PBA_Ferrocyanide_OneMetal, reaction:PBA_Ferrocyanide_Ni, ...) - no
crate was built with the old ones. The anhydrous salts stay in the chemical entity library.

Each step runs once (skipped when its entries exist). The libraries are read and written as main file and
details together (rule 2.14, LibraryFile of fixed_reaction_from_template.py).

Usage (from the repository root):
    python projects/pba_synthesis/curation/add_pba_ions.py
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "generator" / "workflow" / "library_prerun"))
sys.path.insert(0, str(ROOT / "generator"))
import path_definitions  # noqa: E402
from add_pba_chemistry import COUNT_WORD, IDEAL, PRODUCT_CANDIDATES, coefficients  # noqa: E402
from fixed_reaction_from_template import LibraryFile, ref  # noqa: E402

PUBCHEM = HERE / "pubchem" / "pba_ions_hydrates.json"
ARCHIVE = HERE / "archive" / "reaction_library_pba_chloride_templates_20261005.jsonld"
STAMP = "2026-10-06T14:00:00Z"
PERSON = "person:LauraFadler"
LOOKUP = "task:looking_up_pba_ions_and_hydrates"
TIMES = "task:assuming_chemical_entity_library_task_times"
BY = "suggested by Claude Code, decided by Laura Fadler and Meng Kong on 06.10.2026 for the series pba_synthesis"
WEIGHED = "Supplied and weighed in as this hydrate (Meng Kong, 06.10.2026)."


# ---------------------------------------------------------------------------------------------
# Substances
# ---------------------------------------------------------------------------------------------
# Name in the PubChem file -> (ID, name in the entry, CAS, CID with the CAS number if not the SMILES hit, note)
IONS = {
    "Potassium ion": ("chem:PotassiumIon", "Potassium ion", "24203-36-9", None,
                      "K+, from potassium hexacyanoferrate; a spectator ion in the PBA precipitation."),
    "Chloride ion": ("chem:ChlorideIon", "Chloride ion", "16887-00-6", None,
                     "Cl-, from the metal(II) chlorides; a spectator ion in the PBA precipitation."),
    "Manganese(II) ion": ("chem:Manganese2PlusIon", "Manganese(II) ion", "16397-91-4", None,
                          "Mn2+, one of the six metal ions of the PBA series."),
    "Iron(II) ion": ("chem:Iron2PlusIon", "Iron(II) ion", "15438-31-0", None,
                     "Fe2+, one of the six metal ions of the PBA series."),
    "Cobalt(II) ion": ("chem:Cobalt2PlusIon", "Cobalt(II) ion", "22541-53-3", None,
                       "Co2+, one of the six metal ions of the PBA series."),
    "Nickel(II) ion": ("chem:Nickel2PlusIon", "Nickel(II) ion", "14701-22-5", None,
                       "Ni2+, one of the six metal ions of the PBA series."),
    "Copper(II) ion": ("chem:Copper2PlusIon", "Copper(II) ion", "15158-11-9", None,
                       "Cu2+, one of the six metal ions of the PBA series."),
    "Zinc ion": ("chem:Zinc2PlusIon", "Zinc ion", "23713-49-7", None,
                 "Zn2+, one of the six metal ions of the PBA series."),
    "Ferrocyanide ion": ("chem:FerrocyanideIon", "Ferrocyanide ion", "13408-63-4", None,
                         "Hexacyanoferrate(II), [Fe(CN)6]4- - the anion of potassium ferrocyanide (reagent A)."),
    "Ferricyanide ion": ("chem:FerricyanideIon", "Ferricyanide ion", "13408-62-3", 439210,
                         "Hexacyanoferrate(III), [Fe(CN)6]3- - the anion of potassium ferricyanide."),
    "Potassium ferrocyanide trihydrate": ("chem:PotassiumFerrocyanideTrihydrate", "Potassium ferrocyanide trihydrate",
                                          "14459-95-1", None, "K4[Fe(CN)6]*3H2O - reagent A. " + WEIGHED),
    "Nickel(II) chloride hexahydrate": ("chem:NickelIIChlorideHexahydrate", "Nickel(II) chloride hexahydrate",
                                        "7791-20-0", 24645, "NiCl2*6H2O - reagent B. " + WEIGHED),
    "Manganese(II) chloride tetrahydrate": ("chem:ManganeseIIChlorideTetrahydrate", "Manganese(II) chloride tetrahydrate",
                                            "13446-34-9", None, "MnCl2*4H2O - reagent B. " + WEIGHED),
}
# Records found by name for the CAS number; same InChIKey as the SMILES hit.
NAME_RECORDS = {439210: ("Ferricyanide", "YAGKRVSRTSUGEY-UHFFFAOYSA-N"),
                24645: ("Nickel chloride hexahydrate", "LAIZPRYFQUWUBN-UHFFFAOYSA-L")}
CAS_NOT_ON_PUBCHEM = {"chem:FerrocyanideIon": "en.wikipedia.org/wiki/Ferrocyanide (CASNo, marked as checked by CAS)"}


def chemical_entries():
    rows = {r["name"]: r for r in json.loads(PUBCHEM.read_text(encoding="utf-8"))}
    entries, looked_up = [], []
    for name, (entity_id, label, cas, cid_override, note) in IONS.items():
        row = rows[name]
        cid = cid_override or row["CID"]
        if cid_override:
            assert NAME_RECORDS[cid_override][1] == row["InChIKey"], name
        url = f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}"
        comment = (f"{note} Added by curation for the PBA series pba_synthesis ({BY}); not in an ELN. Identifiers and molar "
                   f"mass from PubChem, looked up by the SMILES {row['query_smiles']}: {url}.")
        if cid_override:
            comment += (f" The SMILES lookup found CID {row['CID']} without a CAS number; CID {cid} is the same compound "
                        f"(same InChIKey), found by name, and carries it.")
        if entity_id in CAS_NOT_ON_PUBCHEM:
            comment += f" PubChem lists no CAS number for this record; {cas} from {CAS_NOT_ON_PUBCHEM[entity_id]}."
        elif len(row.get("cas_candidates", [])) > 1:
            assert row["cas_candidates"][0] == cas, name
            comment += f" PubChem lists {len(row['cas_candidates'])} CAS-like numbers; {cas} is the first, the one of the compound itself."
        entries.append({
            "@id": entity_id, "@type": ["chebi:ChemicalEntity", "chebi:Molecule", "hlo:Fixed"], "schema:name": label,
            "cpo:hasCAS": cas, "cpo:hasSMILES": row["ConnectivitySMILES"], "cpo:hasInChI": row["InChI"],
            "cpo:hasMolecularFormula": row["MolecularFormula"], "cpo:hasInChIKey": row["InChIKey"],
            "cpo:hasPubChemCID": str(cid), "schema:comment": comment, "cpo:hasMolarMass": ref(f"{entity_id}_MolarMass")})
        entries.append({"@id": f"{entity_id}_MolarMass", "@type": ["cpo:Parameter", "hlo:Fixed", "hlo:Actual"],
                        "qudt:hasQuantityKind": ref("quantitykind:MolarMass"),
                        "hlo:hasReference": ref(f"{entity_id}_MolarMass_Reference_1")})
        entries.append({"@id": f"{entity_id}_MolarMass_Reference_1", "@type": ["cpo:Parameter", "hlo:Reference"],
                        "hlo:hasReferenceType": ref("hlo:Literature"), "hlo:hasSource": url,
                        "rdfs:comment": f"Molecular weight given by PubChem (CID {cid}), computed there from the molecular formula {row['MolecularFormula']}.",
                        "qudt:value": {"@value": row["MolecularWeight"], "@type": "xsd:decimal"},
                        "qudt:hasUnit": ref("unit:GM-PER-MOL"), "cpo:hasDeterminationTask": ref(LOOKUP)})
        looked_up.append(f"{entity_id}_MolarMass_Reference_1")

    entries.append({
        "@id": LOOKUP, "@type": ["cpo:LiteratureLookupTask", "hlo:Fixed"],
        "schema:name": "Looking up the ions and hydrates of the PBA series on PubChem",
        "schema:description": ("Identifiers, molecular formula and molecular weight of the ions of the PBA series and of the "
                               "hydrates weighed in, looked up on PubChem by SMILES written by curation "
                               "(generator/interfaces/pubchem/pubchem_lookup.py, run by Claude Code on 06.10.2026); for two "
                               "the record with the CAS number found by name, for the ferrocyanide ion the CAS number from "
                               "Wikipedia."),
        "cpo:performedBy": [ref(PERSON)], "cpo:hasStartTime": ref(f"{LOOKUP}_StartTime"),
        "cpo:hasEndTime": ref(f"{LOOKUP}_EndTime"), "cpo:hasDuration": ref(f"{LOOKUP}_Duration"),
        "cpo:determines": [ref(i) for i in looked_up]})
    entries += [
        {"@id": f"{LOOKUP}_StartTime", "@type": ["time:Instant", "hlo:Fixed", "hlo:Actual"],
         "hlo:hasReference": ref(f"{LOOKUP}_StartTime_Reference_1")},
        {"@id": f"{LOOKUP}_StartTime_Reference_1", "@type": ["time:Instant", "hlo:Reference"],
         "hlo:hasReferenceType": ref("hlo:Assumed"),
         "rdfs:comment": f"No record of when this was done. Stamped with the moment the entries were written down ({STAMP}) - an upper bound, not the moment it happened.",
         "rdf:value": {"@value": STAMP, "@type": "xsd:dateTime"},
         "cpo:hasDeterminationTask": ref(TIMES)},
        {"@id": f"{LOOKUP}_EndTime", "@type": ["time:Instant", "hlo:Fixed", "hlo:Actual"]},
        {"@id": f"{LOOKUP}_Duration", "@type": ["time:Duration", "hlo:Fixed", "hlo:Actual"]}]
    return entries


# ---------------------------------------------------------------------------------------------
# Reactions
# ---------------------------------------------------------------------------------------------
WATER = "chem:Molecule_0003"
# Hydrate -> (ID stem, name, equation, [(short, species, coefficient)] of the products)
DISSOLUTIONS = {
    "chem:PotassiumFerrocyanideTrihydrate": (
        "PotassiumFerrocyanideTrihydrate", "potassium ferrocyanide trihydrate",
        "K4[Fe(CN)6]*3H2O > 4 K+ + [Fe(CN)6]4- + 3 H2O",
        [("PotassiumIon", "chem:PotassiumIon", 4.0), ("FerrocyanideIon", "chem:FerrocyanideIon", 1.0), ("Water", WATER, 3.0)]),
    "chem:NickelIIChlorideHexahydrate": (
        "NickelIIChlorideHexahydrate", "nickel(II) chloride hexahydrate", "NiCl2*6H2O > Ni2+ + 2 Cl- + 6 H2O",
        [("NickelIon", "chem:Nickel2PlusIon", 1.0), ("ChlorideIon", "chem:ChlorideIon", 2.0), ("Water", WATER, 6.0)]),
    "chem:ManganeseIIChlorideTetrahydrate": (
        "ManganeseIIChlorideTetrahydrate", "manganese(II) chloride tetrahydrate", "MnCl2*4H2O > Mn2+ + 2 Cl- + 4 H2O",
        [("ManganeseIon", "chem:Manganese2PlusIon", 1.0), ("ChlorideIon", "chem:ChlorideIon", 2.0), ("Water", WATER, 4.0)]),
}


def participant(reaction, short, species, role, coefficient):
    return {"@id": f"{reaction}_Participant_{short}", "@type": ["cpo:ReactionParticipant", "hlo:Fixed"],
            "dcterms:hasPart": ref(species), "cpo:hasChemicalRole": ref(role),
            "cpo:hasStoichiometricCoefficient": coefficient, "cpo:participatesIn": ref(reaction)}


def dissolution_entries():
    entries = []
    for hydrate, (stem, name, equation, products) in DISSOLUTIONS.items():
        reaction = f"reaction:Dissolution_{stem}"
        parts = [participant(reaction, "Hydrate", hydrate, "cpo:Reactant", -1.0)]
        parts += [participant(reaction, short, species, "cpo:Product", c) for short, species, c in products]
        entries.append({
            "@id": reaction, "@type": ["cpo:StoichiometricReaction", "hlo:Fixed"],
            "schema:name": f"Dissolution of {name}",
            "schema:description": equation,
            "schema:comment": (f"Dissolving the {name} weighed in releases its ions and its water of crystallization at once. "
                               f"Meant to take place at the interface between the solid salt and the water (at_interface in "
                               f"the sheet): the hydrate leaves the solid, the ions and the water enter the liquid. In "
                               f"solution the ions count, not the salt (net-ionic PBA reactions). A net balance, not a "
                               f"mechanism. Added by curation ({BY})."),
            "cpo:hasParticipant": [ref(p["@id"]) for p in parts]})
        entries += parts
    return entries


METAL_IONS = ["chem:Manganese2PlusIon", "chem:Iron2PlusIon", "chem:Cobalt2PlusIon", "chem:Nickel2PlusIon",
              "chem:Copper2PlusIon", "chem:Zinc2PlusIon"]
METAL = "placeholder:PBA_MetalIon_{n}"
MAX_METALS = 6
SOURCES = {"Ferrocyanide": ("chem:FerrocyanideIon", "[Fe(CN)6]4-", "ferrocyanide", 4),
           "Ferricyanide": ("chem:FerricyanideIon", "[Fe(CN)6]3-", "ferricyanide", 3)}


def formula(count, c, k):
    return "".join(f"(M{i}){c if c > 1 else ''}" for i in range(1, count + 1)) + f"[Fe(CN)6]{k if k > 1 else ''}"


def template_entries():
    entries = []
    for n in range(1, MAX_METALS + 1):
        entries.append({
            "@id": METAL.format(n=n), "@type": ["chebi:ChemicalEntity", "cpo:Placeholder", "hlo:Fixed"],
            "schema:name": f"M2+ (metal {n})",
            "schema:description": (f"Metal {n} of a Prussian blue analogue: a transition metal(II) ion. Shared by all PBA "
                                   "templates - resolved once per series, so metal 1 of the one-metal template is metal 1 of "
                                   "the mixtures as well."),
            "cpo:hasPotentialCandidate": [ref(c) for c in METAL_IONS]})
    for source, count in [(s, n) for s in SOURCES for n in range(1, MAX_METALS + 1)]:
        source_id, source_formula, source_name, charge = SOURCES[source]
        k_coef, m_coef, _ = coefficients(charge, count)
        product_formula = formula(count, m_coef, k_coef)
        name = f"PBA_{source}_{COUNT_WORD[count]}"
        product = f"placeholder:{name}_Product"
        mix = "" if count == 1 else f" ({count} metals in equal amounts)"
        entries.append({
            "@id": product, "@type": ["chebi:ChemicalEntity", "cpo:Placeholder", "hlo:Fixed"],
            "schema:name": f"PBA {product_formula}",
            "schema:description": (f"Product of the template reaction:{name}: the Prussian blue analogue {product_formula}{mix} from "
                                   f"the {source_name} ion. " + IDEAL.format(mix="" if count == 1 else ", the metals equimolar")
                                   + " Resolved once per series."),
            **({"cpo:hasPotentialCandidate": [ref(c) for c in PRODUCT_CANDIDATES[(source, count)]]}
               if (source, count) in PRODUCT_CANDIDATES else {})})
        reaction = f"reaction:{name}"
        parts = [participant(reaction, "Hexacyanoferrate", source_id, "cpo:Reactant", -float(k_coef))]
        parts += [participant(reaction, f"MetalIon_{i}", METAL.format(n=i), "cpo:Reactant", -float(m_coef))
                  for i in range(1, count + 1)]
        parts.append(participant(reaction, "Product", product, "cpo:Product", 1.0))
        left = " + ".join([f"{k_coef} {source_formula}" if k_coef > 1 else source_formula] +
                          [f"{m_coef} M2+ (metal {i})" if m_coef > 1 else f"M2+ (metal {i})" for i in range(1, count + 1)])
        entries.append({
            "@id": reaction, "@type": ["cpo:StoichiometricReaction", "hlo:Fixed", "hlo:Template"],
            "schema:name": f"PBA formation, {source_name}, {count} metal{'s' if count > 1 else ''} (template)",
            "schema:description": f"{left} > {product_formula}",
            "schema:comment": (f"TEMPLATE of the co-precipitation of a Prussian blue analogue from the {source_name} ion and "
                               f"{'one metal(II) ion' if count == 1 else f'{count} metal(II) ions in equal amounts'} in water, "
                               f"net-ionic: potassium and chloride stay in solution as spectator ions. The metal ions and the "
                               f"product are placeholders; the fixed reactions of the concrete metals specialize the template "
                               f"(hlo:specializationOf; made with curation/pba_reactions.py), and a sheet names those. "
                               + IDEAL.format(mix="" if count == 1 else ", the metals equimolar")
                               + f" A net balance, not a mechanism. Added by curation for the series pba_synthesis ({BY}); "
                               f"replaces the template of the same ID from the salts (05.10.2026, kept in "
                               f"projects/pba_synthesis/curation/archive/)."),
            "cpo:hasParticipant": [ref(p["@id"]) for p in parts]})
        entries += parts
    return entries


def is_old_pba(entry_id):
    return entry_id.startswith(("reaction:PBA_", "placeholder:PBA_"))


def archive_old_reactions(reactions):
    """Moves the PBA entries of 05.10.2026 out of the reaction library into the archive file."""
    old = [e for e in reactions.graph if is_old_pba(e["@id"])]
    ARCHIVE.parent.mkdir(exist_ok=True)
    ARCHIVE.write_text(json.dumps({"@context": reactions.data["@context"], "@graph": old}, indent=1, ensure_ascii=False) + "\n",
                       encoding="utf-8")
    reactions.data["@graph"] = [e for e in reactions.graph if not is_old_pba(e["@id"])]
    return len(old)


# ---------------------------------------------------------------------------------------------
def extend(library, entries):
    ids = set(library.by_id())
    clash = [e["@id"] for e in entries if e["@id"] in ids]
    if clash:
        sys.exit(f"{library.path.name}: {clash[0]} exists already - nothing written.")
    library.graph.extend(entries)


def main():
    chemicals = LibraryFile(path_definitions.CHEMICAL_ENTITY_LIBRARY_PATH)
    reactions = LibraryFile(path_definitions.REACTION_LIBRARY_PATH)
    if any(e["@id"] == LOOKUP for e in chemicals.graph):
        print("chemical entity library: entries exist already - skipped")
    else:
        new_chemicals = chemical_entries()
        extend(chemicals, new_chemicals)
        times = chemicals.by_id()[TIMES]
        times["cpo:determines"] = times["cpo:determines"] + [ref(f"{LOOKUP}_StartTime_Reference_1")]
        chemicals.save()
        print(f"chemical entity library: +{len(new_chemicals)}")
    if ARCHIVE.exists():
        print("reaction library: archived and rewritten already - skipped")
        return
    archived = archive_old_reactions(reactions)
    new_reactions = dissolution_entries() + template_entries()
    extend(reactions, new_reactions)
    reactions.save()
    print(f"reaction library: -{archived} archived to {ARCHIVE.relative_to(ROOT)}, +{len(new_reactions)}")


if __name__ == "__main__":
    main()
