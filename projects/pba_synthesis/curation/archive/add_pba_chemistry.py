"""
Chemistry of the Prussian blue analogue (PBA) series pba_synthesis - library entries written on
05.10.2026 by Claude Code; structure decided by Laura Fadler in the same session:

- chemical entity library: potassium ferrocyanide and ferricyanide, potassium chloride, the six
  transition metal(II) chlorides tested (Mn, Fe, Co, Ni, Cu, Zn), and the PBA products the series
  needs so far - Ni2[Fe(CN)6] (experiment 1) and NiMn[Fe(CN)6] (experiment 2). Identifiers and molar
  masses from PubChem (curation/pubchem/pba_substances.json, looked up by SMILES; for four salts the
  record PubChem keeps the CAS number under was found by name), NiMn[Fe(CN)6] is not on PubChem.
- reaction library: twelve TEMPLATES - one metal and mixtures of two to six; each with ferrocyanide
  and with ferricyanide, coefficients from the charge balance. The metal chlorides are placeholders
  shared by all templates (metal 1 to 6), each template has its own product placeholder; a series resolves them once
  (Ni and Mn in pba_synthesis). The PBA formulas are idealized - no potassium, water or vacancies in
  the lattice, equimolar metals in a mixture; the real composition is only known after
  characterization (Laura Fadler, 05.10.2026).

Since 06.10.2026 the reaction templates written here are archived (curation/archive/) and replaced by
net-ionic ones (add_pba_ions.py); the substances stay. The script reads and writes only the main files of
the libraries, so it must not be run again (rule 2.14).

Each library is written once (skipped when its entries exist - the reaction library was rebuilt on
05.10.2026 for up to six metals); stops if a single entry exists already. Each library is written back
in its own format.

Usage (from the repository root):
    python projects/pba_synthesis/curation/add_pba_chemistry.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
LIB = ROOT / "libraries"
PUBCHEM = Path(__file__).resolve().parent / "pubchem" / "pba_substances.json"
STAMP = "2026-10-05T21:00:00Z"
PERSON = "person:LauraFadler"
LOOKUP = "task:looking_up_pba_substances"
CALC = "task:calculating_molar_masses"
BY = "suggested by Claude Code, confirmed by Laura Fadler on 05.10.2026 for the series pba_synthesis"
IDEAL = ("Idealized composition: no potassium, water or vacancies in the lattice{mix} - the real composition of the "
         "precipitate is only known after its characterization (Laura Fadler, 05.10.2026).")


def ref(i):
    return {"@id": i}


# ---------------------------------------------------------------------------------------------
# Substances
# ---------------------------------------------------------------------------------------------
SALTS = {
    # Name in the PubChem file -> (ID, name in the entry, CID/CAS differing from the SMILES hit, note)
    "Potassium ferrocyanide": ("chem:PotassiumFerrocyanide", "Potassium ferrocyanide", (9605257, "13943-58-3"),
                               "Potassium hexacyanoferrate(II), K4[Fe(CN)6] - reagent A; usually weighed in as the trihydrate, "
                               "in solution the anhydrous salt counts."),
    "Potassium ferricyanide": ("chem:PotassiumFerricyanide", "Potassium ferricyanide", (26250, "13746-66-2"),
                               "Potassium hexacyanoferrate(III), K3[Fe(CN)6] - reagent A of the ferricyanide templates."),
    "Potassium chloride": ("chem:PotassiumChloride", "Potassium chloride", (None, "7447-40-7"),
                           "By-product of every PBA precipitation from potassium hexacyanoferrate and a metal chloride."),
    "Manganese(II) chloride": ("chem:ManganeseIIChloride", "Manganese(II) chloride", (None, "7773-01-5"),
                               "Reagent B (one of the six metal chlorides tested); usually weighed in as a hydrate."),
    "Iron(II) chloride": ("chem:IronIIChloride", "Iron(II) chloride", (None, "7758-94-3"),
                          "Reagent B (one of the six metal chlorides tested); usually weighed in as a hydrate."),
    "Cobalt(II) chloride": ("chem:CobaltIIChloride", "Cobalt(II) chloride", (3032536, "7646-79-9"),
                            "Reagent B (one of the six metal chlorides tested); usually weighed in as a hydrate."),
    "Nickel(II) chloride": ("chem:NickelIIChloride", "Nickel(II) chloride", (None, "7718-54-9"),
                            "Reagent B (one of the six metal chlorides tested); usually weighed in as a hydrate."),
    "Copper(II) chloride": ("chem:CopperIIChloride", "Copper(II) chloride", (None, "7447-39-4"),
                            "Reagent B (one of the six metal chlorides tested); usually weighed in as a hydrate."),
    "Zinc chloride": ("chem:ZincChloride", "Zinc chloride", (None, "7646-85-7"),
                      "Reagent B (one of the six metal chlorides tested)."),
    "Nickel hexacyanoferrate(II)": ("chem:NickelHexacyanoferrateII", "Nickel hexacyanoferrate(II)", (None, None),
                                    "PBA product of nickel(II) chloride and potassium ferrocyanide, Ni2[Fe(CN)6]. "
                                    + IDEAL.format(mix="")),
}
# For these four the SMILES search found a dataset without a CAS number; the one with CAS came via the name
# (same InChIKey or the same compound). MnCl2: PubChem gives no CAS number for CID 24480.
NAME_RECORDS = {9605257: ("Potassium Ferrocyanide", "XOGGUFAVLNCTRS-UHFFFAOYSA-N"),
                26250: ("Potassium ferricyanide", "BYGOPQKDHGXNCD-UHFFFAOYSA-N"),
                3032536: ("Cobalt chloride (cocl2)", "GVPFVAHMJGGAJG-UHFFFAOYSA-L")}
MNCL2_CAS_SOURCE = "Sigma-Aldrich, manganese(II) chloride, anhydrous (CAS 7773-01-5); en.wikipedia.org/wiki/Manganese(II)_chloride"

NIMN = ("chem:NickelManganeseHexacyanoferrateII", "Nickel manganese hexacyanoferrate(II)", "C6FeMnN6Ni",
        "[C-]#N.[C-]#N.[C-]#N.[C-]#N.[C-]#N.[C-]#N.[Fe+2].[Ni+2].[Mn+2]",
        # IUPAC 2021: C 12.011, N 14.007, Fe 55.845, Mn 54.938, Ni 58.693
        "6 x 12.011 + 55.845 + 54.938 + 6 x 14.007 + 58.693 = 325.584", 325.584)


def chemical_entries():
    rows = {r["name"]: r for r in json.loads(PUBCHEM.read_text(encoding="utf-8"))}
    entries, looked_up = [], []
    for name, (cid_id, label, (cid_override, cas), note) in SALTS.items():
        row = rows[name]
        cid = cid_override or row["CID"]
        if cid_override:
            title, key = NAME_RECORDS[cid_override]
            assert key == row["InChIKey"], name
        url = f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}"
        comment = (f"{note} Added by curation for the PBA series pba_synthesis ({BY}); not in an ELN. Identifiers and molar "
                   f"mass from PubChem, looked up by the SMILES {row['query_smiles']}: {url}.")
        if cid_override:
            comment += (f" The SMILES lookup found CID {row['CID']} without a CAS number; CID {cid} is the same compound "
                        f"(same InChIKey), found by name, and carries it.")
        entry = {"@id": cid_id, "@type": ["chebi:ChemicalEntity", "chebi:Molecule", "hlo:Fixed"], "schema:name": label}
        if cas:
            entry["cpo:hasCAS"] = cas
            if cid_id == "chem:ManganeseIIChloride":
                comment += f" PubChem lists no CAS number for this record; {cas} from {MNCL2_CAS_SOURCE}."
            elif len(row.get("cas_candidates", [])) > 1:
                comment += f" PubChem lists {len(row['cas_candidates'])} CAS-like numbers; {cas} is the one of the anhydrous salt."
        else:
            entry["cpo:hasNoCASNumber"] = True
            comment += " PubChem lists no CAS number for this idealized composition."
        entry.update({"cpo:hasSMILES": row["ConnectivitySMILES"], "cpo:hasInChI": row["InChI"],
                      "cpo:hasMolecularFormula": row["MolecularFormula"], "cpo:hasInChIKey": row["InChIKey"],
                      "cpo:hasPubChemCID": str(cid), "schema:comment": comment, "cpo:hasMolarMass": ref(f"{cid_id}_MolarMass")})
        entries.append(entry)
        entries.append({"@id": f"{cid_id}_MolarMass", "@type": ["cpo:Parameter", "hlo:Fixed", "hlo:Actual"],
                        "qudt:hasQuantityKind": ref("quantitykind:MolarMass"),
                        "hlo:hasReference": ref(f"{cid_id}_MolarMass_Reference_1")})
        entries.append({"@id": f"{cid_id}_MolarMass_Reference_1", "@type": ["cpo:Parameter", "hlo:Reference"],
                        "hlo:hasReferenceType": ref("hlo:Literature"), "hlo:hasSource": url,
                        "rdfs:comment": f"Molecular weight given by PubChem (CID {cid}), computed there from the molecular formula {row['MolecularFormula']}.",
                        "qudt:value": {"@value": row["MolecularWeight"], "@type": "xsd:decimal"},
                        "qudt:hasUnit": ref("unit:GM-PER-MOL"), "cpo:hasDeterminationTask": ref(LOOKUP)})
        looked_up.append(f"{cid_id}_MolarMass_Reference_1")

    nimn_id, label, formula, smiles, sum_text, mass = NIMN
    entries.append({
        "@id": nimn_id, "@type": ["chebi:ChemicalEntity", "chebi:Molecule", "hlo:Fixed"], "schema:name": label,
        "cpo:hasNoCASNumber": True, "cpo:hasSMILES": smiles, "cpo:hasMolecularFormula": formula,
        "schema:comment": ("PBA product of nickel(II) and manganese(II) chloride with potassium ferrocyanide, NiMn[Fe(CN)6]. "
                           + IDEAL.format(mix=", and the two metals taken as equimolar") + f" Added by curation for the PBA "
                           f"series pba_synthesis ({BY}); not on PubChem (looked up by the SMILES {smiles}), so no CAS, InChI "
                           f"or CID; formula and SMILES written by curation."),
        "cpo:hasMolarMass": ref(f"{nimn_id}_MolarMass")})
    entries.append({"@id": f"{nimn_id}_MolarMass", "@type": ["cpo:Parameter", "hlo:Fixed", "hlo:Actual"],
                    "qudt:hasQuantityKind": ref("quantitykind:MolarMass"), "hlo:hasEvidence": ref(f"{nimn_id}_MolarMass_Evidence_1")})
    entries.append({"@id": f"{nimn_id}_MolarMass_Evidence_1", "@type": ["cpo:Parameter", "hlo:Evidence"],
                    "hlo:hasEvidenceType": ref("hlo:Calculated"),
                    "rdfs:comment": (f"Summed from the molecular formula {formula} with the IUPAC 2021 standard atomic weights: "
                                     f"{sum_text} g/mol. Not measured - recompute if cpo:hasMolecularFormula changes."),
                    "qudt:value": {"@value": f"{mass}", "@type": "xsd:decimal"}, "qudt:hasUnit": ref("unit:GM-PER-MOL"),
                    "cpo:hasDeterminationTask": ref(CALC)})

    entries.append({
        "@id": LOOKUP, "@type": ["cpo:LiteratureLookupTask", "hlo:Fixed"],
        "schema:name": "Looking up the substances of the PBA series on PubChem",
        "schema:description": ("Identifiers, molecular formula and molecular weight of the hexacyanoferrates, the metal chlorides, "
                               "potassium chloride and nickel hexacyanoferrate(II), looked up on PubChem by SMILES written by "
                               "curation (generator/interfaces/pubchem/pubchem_lookup.py, run by Claude Code on 05.10.2026); "
                               "for four salts the record with the CAS number found by name."),
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
         "cpo:hasDeterminationTask": ref("task:assuming_chemical_entity_library_task_times")},
        {"@id": f"{LOOKUP}_EndTime", "@type": ["time:Instant", "hlo:Fixed", "hlo:Actual"]},
        {"@id": f"{LOOKUP}_Duration", "@type": ["time:Duration", "hlo:Fixed", "hlo:Actual"]}]
    return entries


# ---------------------------------------------------------------------------------------------
# Templates of the reactions
# ---------------------------------------------------------------------------------------------
CHLORIDES = [i for i, *_ in SALTS.values() if i.endswith("Chloride") and i != "chem:PotassiumChloride"]
METAL = "placeholder:PBA_MetalChloride_{n}"
COUNT_WORD = {1: "OneMetal", 2: "TwoMetals", 3: "ThreeMetals", 4: "FourMetals", 5: "FiveMetals", 6: "SixMetals"}
MAX_METALS = 6
SOURCES = {"Ferrocyanide": ("chem:PotassiumFerrocyanide", "K4[Fe(CN)6]", "potassium ferrocyanide", 4),
           "Ferricyanide": ("chem:PotassiumFerricyanide", "K3[Fe(CN)6]", "potassium ferricyanide", 3)}


def coefficients(charge, count):
    """Smallest whole coefficients for k hexacyanoferrate ions of this charge and count metal(II)
    chlorides, c of each (equimolar): k x charge = 2 x count x c; potassium chloride k x charge."""
    k = 1
    while (k * charge) % (2 * count):
        k += 1
    return k, k * charge // (2 * count), k * charge


def formula(count, c, k):
    return "".join(f"(M{i}){c if c > 1 else ''}" for i in range(1, count + 1)) + f"[Fe(CN)6]{k if k > 1 else ''}"


# Products used so far as candidates of their placeholders.
PRODUCT_CANDIDATES = {("Ferrocyanide", 1): ["chem:NickelHexacyanoferrateII"],
                      ("Ferrocyanide", 2): ["chem:NickelManganeseHexacyanoferrateII"]}


def reaction_entries():
    entries = []
    for n in range(1, MAX_METALS + 1):
        entries.append({
            "@id": METAL.format(n=n), "@type": ["chebi:ChemicalEntity", "cpo:Placeholder", "hlo:Fixed"],
            "schema:name": f"MCl2 (metal {n})",
            "schema:description": (f"Metal {n} of a Prussian blue analogue: a transition metal(II) chloride. Shared by all PBA "
                                   "templates - resolved once per series, so metal 1 of the one-metal template is metal 1 of "
                                   "the mixtures as well."),
            "cpo:hasPotentialCandidate": [ref(c) for c in CHLORIDES]})
    for source, count in [(s, n) for s in SOURCES for n in range(1, MAX_METALS + 1)]:
        source_id, source_formula, source_name, charge = SOURCES[source]
        k_coef, m_coef, kcl = coefficients(charge, count)
        product_formula = formula(count, m_coef, k_coef)
        name = f"PBA_{source}_{COUNT_WORD[count]}"
        product = f"placeholder:{name}_Product"
        mix = "" if count == 1 else f" ({count} metals in equal amounts)"
        entries.append({
            "@id": product, "@type": ["chebi:ChemicalEntity", "cpo:Placeholder", "hlo:Fixed"],
            "schema:name": f"PBA {product_formula}",
            "schema:description": (f"Product of the template reaction:{name}: the Prussian blue analogue {product_formula}{mix} from "
                                   f"{source_name}. " + IDEAL.format(mix="" if count == 1 else ", the metals equimolar")
                                   + " Resolved once per series."),
            **({"cpo:hasPotentialCandidate": [ref(c) for c in PRODUCT_CANDIDATES[(source, count)]]}
               if (source, count) in PRODUCT_CANDIDATES else {})})
        metals = [METAL.format(n=i) for i in range(1, count + 1)]
        participants = [("Hexacyanoferrate", source_id, "cpo:Reactant", -float(k_coef))]
        participants += [(f"MetalChloride_{i}", m, "cpo:Reactant", -float(m_coef)) for i, m in enumerate(metals, 1)]
        participants += [("Product", product, "cpo:Product", 1.0), ("PotassiumChloride", "chem:PotassiumChloride", "cpo:Byproduct", float(kcl))]
        left = " + ".join([f"{k_coef} {source_formula}" if k_coef > 1 else source_formula] +
                          [f"{m_coef} MCl2 (metal {i})" if m_coef > 1 else f"MCl2 (metal {i})" for i in range(1, count + 1)])
        reaction = f"reaction:{name}"
        entries.append({
            "@id": reaction, "@type": ["cpo:StoichiometricReaction", "hlo:Fixed", "hlo:Template"],
            "schema:name": f"PBA formation, {source_name}, {count} metal{'s' if count > 1 else ''} (template)",
            "schema:description": f"{left} > {product_formula} + {kcl} KCl",
            "schema:comment": (f"TEMPLATE of the co-precipitation of a Prussian blue analogue from {source_name} and "
                               f"{'one metal(II) chloride' if count == 1 else f'a mixture of {count} metal(II) chlorides in equal amounts'} "
                               f"in water. The metal chlorides and the product are placeholders; the fixed reactions of the "
                               f"concrete metals specialize the template (hlo:specializationOf; made with "
                               f"curation/pba_reactions.py), and a sheet names those. "
                               + IDEAL.format(mix="" if count == 1 else ", the metals equimolar")
                               + f" A net balance, not a mechanism. Added by curation for the series pba_synthesis ({BY})."),
            "cpo:hasParticipant": [ref(f"{reaction}_Participant_{short}") for short, *_ in participants]})
        for short, species, role, coefficient in participants:
            entries.append({
                "@id": f"{reaction}_Participant_{short}", "@type": ["cpo:ReactionParticipant", "hlo:Fixed"],
                "dcterms:hasPart": ref(species), "cpo:hasChemicalRole": ref(role),
                "cpo:hasStoichiometricCoefficient": coefficient, "cpo:participatesIn": ref(reaction)})
    return entries


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

    def find(self, entity_id):
        return next(e for e in self.graph if e["@id"] == entity_id)

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
    chemicals = LibraryFile(LIB / "chemical_entity_library.jsonld")
    reactions = LibraryFile(LIB / "reaction_library.jsonld")
    if any(e["@id"] == LOOKUP for e in chemicals.graph):
        print("chemical entity library: entries exist already - skipped")
    else:
        new_chemicals = chemical_entries()
        chemicals.extend(new_chemicals)
        times = chemicals.find("task:assuming_chemical_entity_library_task_times")
        times["cpo:determines"] = times["cpo:determines"] + [ref(f"{LOOKUP}_StartTime_Reference_1")]
        calc = chemicals.find(CALC)
        calc["cpo:determines"] = calc["cpo:determines"] + [ref(f"{NIMN[0]}_MolarMass_Evidence_1")]
        chemicals.save()
        print(f"chemical entity library: +{len(new_chemicals)}")
    new_reactions = reaction_entries()
    reactions.extend(new_reactions)
    reactions.save()
    print(f"reaction library: +{len(new_reactions)}")


if __name__ == "__main__":
    main()
