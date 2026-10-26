"""
The reaction of the Chemotion example, written on 05.10.2026 by Claude Code: the reductive catalytic
fractionation (RCF) of spruce wood as a cpo:LumpedReaction (class added the same day, Laura Fadler) -
lignin and lignin oil are no single species, so there is no balanced equation and no coefficient.

The "lignin-first" picture (variant C, decided by Laura Fadler on 05.10.2026): the wood is a solid of
cellulose and lignin; the lignin dissolves into the methanol and is broken down at the catalyst, the
cellulose stays behind as the pulp - it is not formed by the reaction and so is no participant. A first
version (spruce wood as substrate, cellulose as product) could not be placed at an interface: a solid
reactant converted at its own surface has no one-sided transfer.

Participants (roles by curation, suggested by Claude Code and confirmed by Laura Fadler on 05.10.2026):
lignin (Substrate), hydrogen (Reagent), palladium and activated carbon (Catalyst - the metal and its
support), 4-propylguaiacol (Product). Methanol is the solvent: that is said by the setup sheet, not by
the library (rule 3.12). The two Chemotion records name the reaction as their subject. Also adds
chem:Lignin, an informal entry like chem:Cellulose.

Reads and writes the libraries through load_jsonld/save_jsonld (rule 2.14). Runs once; stops if the
reaction or the lignin exists already.

Usage (from the repository root):
    python projects/chemotion_example/curation/add_rcf_reaction.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "generator"))
from helpers.file_handling import load_jsonld, save_jsonld  # noqa: E402

PATH = ROOT / "libraries" / "reaction_library.jsonld"
CHEMICALS = ROOT / "libraries" / "chemical_entity_library.jsonld"
REACTION = "reaction:RCF_SpruceWood"
RECORDS = ("reaction:Record_Chemotion_LCJ-R5", "reaction:Record_Chemotion_LCJ-R8")
BY = "suggested by Claude Code, confirmed by Laura Fadler on 05.10.2026 for the Chemotion example"
PARTICIPANTS = [
    # (short name, substance, role, note)
    ("Lignin", "chem:Lignin", "cpo:Substrate",
     "Not named in the ELN as a substance: the lignin of the starting material (Chemotion LCJ-R5, LCJ-R8: spruce wood), which "
     "the records' products come from ('lignin-derived liquid product', 'G-unit depolymerisation'). Role Substrate by curation: "
     "its skeleton ends up in the phenolic products"),
    ("Hydrogen", "chem:Molecule_0001", "cpo:Reagent",
     "From the ELN (Chemotion LCJ-R5, LCJ-R8): '50 bar H2' in the free text and the atmosphere 'h2' of the segment 'Reaction "
     "Details'. Role Reagent by curation: consumed in the hydrogenolysis of the lignin"),
    ("Palladium", "chem:Palladium", "cpo:Catalyst",
     "From the ELN (Chemotion LCJ-R5, LCJ-R8): '5 wt% Pd/C catalyst' in the free text - the metal of the catalyst"),
    ("ActivatedCarbon", "chem:ActivatedCarbon", "cpo:Catalyst",
     "From the ELN (Chemotion LCJ-R5, LCJ-R8): '5 wt% Pd/C catalyst' in the free text - the support of the catalyst, taken as "
     "activated carbon. Role Catalyst by curation: the ontology has no role of its own for a support"),
    ("Propylguaiacol", "chem:Propylguaiacol", "cpo:Product",
     "From the ELN (Chemotion LCJ-R8: product '4-Propylguaiacol'; LCJ-R5: product LCJ-R5-A, 'Guaiacyl-type monophenol' of the "
     "liquid phase) - the main monomer of the lignin oil; the other monomers and oligomers are not named"),
]
LIGNIN = {
    "@id": "chem:Lignin", "@type": ["chebi:ChemicalEntity", "hlo:Fixed"], "schema:name": "Lignin",
    "rdfs:comment": ("Informal entry, not a single chemical species - lignin is a cross-linked aromatic polymer of varying "
                     "composition (in softwood mostly guaiacyl units). Carried as a chemical entity so a phase can list what it "
                     "consists of, without CAS/SMILES/InChI/molar mass."),
    "schema:comment": ("Added by curation; not in the ELN as a substance: the Chemotion records LCJ-R5 and LCJ-R8 speak of a "
                       "'lignin-derived liquid product' and 'G-unit depolymerisation' of spruce wood - the lignin of the wood "
                       f"is the substrate of the RCF ({BY})."),
    "schema:subjectOf": [{"@id": r} for r in RECORDS]}


def ref(i):
    return {"@id": i}


def main():
    data = load_jsonld(PATH)
    graph = data["@graph"]
    by_id = {e["@id"]: e for e in graph}
    assert REACTION not in by_id, f"{REACTION} exists already"
    participants = [f"{REACTION}_Participant_{short}" for short, *_ in PARTICIPANTS]
    graph.append({
        "@id": REACTION, "@type": ["cpo:LumpedReaction", "hlo:Fixed"],
        "schema:name": "Reductive catalytic fractionation of spruce wood",
        "schema:description": "Lignin (of spruce wood, dissolved in methanol) + H2 (Pd/C) > lignin oil (mainly 4-propylguaiacol); the cellulose stays behind as pulp",
        "schema:comment": ("The reaction of the Chemotion records LCJ-R5 and LCJ-R8 ('Reductive Catalytic Fractionation (RCF) of spruce "
                           "wood pellets'; reaction class 'biomass_fractionation' in the segment 'Reaction Details'). A lumped reaction: "
                           "lignin and lignin oil are no single species, so there is no balanced equation and no stoichiometric "
                           "coefficient. In the 'lignin-first' picture the lignin of the wood dissolves and is broken down at the "
                           "catalyst; the cellulose pulp the records list as a second product is what stays behind, not a product of "
                           f"the reaction. Participants and roles written by curation ({BY}). No RInChI: the one of the records is "
                           "empty (no structures)."),
        "cpo:hasParticipant": [ref(p) for p in participants],
        "schema:subjectOf": [ref(r) for r in RECORDS]})
    for (short, substance, role, note), participant in zip(PARTICIPANTS, participants):
        graph.append({"@id": participant, "@type": ["cpo:ReactionParticipant", "hlo:Fixed"],
                      "dcterms:hasPart": ref(substance), "cpo:hasChemicalRole": ref(role),
                      "cpo:participatesIn": ref(REACTION), "schema:comment": f"{note} ({BY})."})
    for record in RECORDS:
        about = by_id[record].get("schema:about") or []
        by_id[record]["schema:about"] = (about if isinstance(about, list) else [about]) + [ref(REACTION)]
    save_jsonld(data, PATH)

    chemicals = load_jsonld(CHEMICALS)
    assert not any(e.get("@id") == LIGNIN["@id"] for e in chemicals["@graph"]), "chem:Lignin exists already"
    chemicals["@graph"].append(LIGNIN)
    save_jsonld(chemicals, CHEMICALS)
    print(f"{REACTION} and {LIGNIN['@id']} added.")


if __name__ == "__main__":
    main()
