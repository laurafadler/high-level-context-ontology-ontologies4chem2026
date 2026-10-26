"""
Fixed PBA formation reactions from the templates: for every
metal combination given, the reaction "PBA formation, ferrocyanide, Mn + Ni" with the concrete
metal ions and product, made with
fixed_reaction_from_template.py (next to this file) from the template for that many
metals (reaction:PBA_<Ferro|Ferri>cyanide_<N>Metals). The sheet then names the reaction by its ID.

The product is looked up by its molecular formula in the Chemical Entity Library; if there is none,
it is created: idealized formula (no potassium, water or vacancies, the metals equimolar - the real
composition is only known after characterization), SMILES of its ions, molar mass summed with the
IUPAC 2021 standard atomic weights, no CAS number, not looked up on PubChem. The metals are sorted
by atomic number, so "Ni+Mn" and "Mn+Ni" are the same reaction. Existing reactions are left alone.

Net-ionic: the templates (add_pba_ions.py) take the hexacyanoferrate ion and the metal(II) ions;
potassium and chloride are spectator ions (the comment of each reaction names who decided it).

A tool of the generator, not a curation script of the project: the series will need it again for its
further metal combinations.

Usage (from the repository root):
    python generator/workflow/library_prerun/pba_reactions.py ferrocyanide Ni Ni+Mn [Co+Ni+Zn ...]
    python generator/workflow/library_prerun/pba_reactions.py ferricyanide Cu
"""
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "generator" / "workflow" / "library_prerun"))
sys.path.insert(0, str(ROOT / "generator"))
import path_definitions  # noqa: E402
from fixed_reaction_from_template import LibraryFile, TemplateError, make_fixed_reaction, ref  # noqa: E402

TODAY = date.today().isoformat()
BY = f"made with generator/workflow/library_prerun/pba_reactions.py on {TODAY}"
METALS = {  # symbol -> (atomic number, name, metal(II) ion, atomic mass IUPAC 2021)
    "Mn": (25, "Manganese", "chem:Manganese2PlusIon", 54.938),
    "Fe": (26, "Iron", "chem:Iron2PlusIon", 55.845),
    "Co": (27, "Cobalt", "chem:Cobalt2PlusIon", 58.933),
    "Ni": (28, "Nickel", "chem:Nickel2PlusIon", 58.693),
    "Cu": (29, "Copper", "chem:Copper2PlusIon", 63.546),
    "Zn": (30, "Zinc", "chem:Zinc2PlusIon", 65.38),
}
WEIGHTS = {"C": 12.011, "N": 14.007, "Fe": 55.845, **{s: m[3] for s, m in METALS.items()}}
SOURCES = {"ferrocyanide": ("Ferrocyanide", "ferrocyanide", "[Fe(CN)6]4-", "II", 2),
           "ferricyanide": ("Ferricyanide", "ferricyanide", "[Fe(CN)6]3-", "III", 3)}
COUNT_WORD = {1: "OneMetal", 2: "TwoMetals", 3: "ThreeMetals", 4: "FourMetals", 5: "FiveMetals", 6: "SixMetals"}
CALC = "task:calculating_molar_masses"


def hill(counts):
    """Molecular formula in Hill order (C first, then alphabetical; no H here)."""
    order = ["C"] + sorted(e for e in counts if e != "C")
    return "".join(f"{e}{counts[e] if counts[e] > 1 else ''}" for e in order)


def product_entries(chemicals_by_id, source, metals, k, c):
    """The product of this combination: the existing entry with the same formula, or a new one.
    Returns (ID, new entries, ID of a new molar mass evidence or None)."""
    key, source_name, _, oxidation, iron_charge = SOURCES[source]
    counts = {"C": 6 * k, "N": 6 * k, "Fe": k}
    for metal in metals:
        counts[metal] = counts.get(metal, 0) + c
    formula = hill(counts)
    for entity in chemicals_by_id.values():
        if entity.get("cpo:hasMolecularFormula") == formula:
            return entity["@id"], [], None
    names = [METALS[m][1] for m in metals]
    product_id = f"chem:{''.join(names)}Hexacyanoferrate{oxidation}"
    label = " ".join([names[0]] + [n.lower() for n in names[1:]]) + f" hexacyanoferrate({oxidation})"
    ions = ["[C-]#N"] * (6 * k) + [f"[Fe+{iron_charge}]"] * k + [f"[{m}+2]" for m in metals for _ in range(c)]
    mass = sum(WEIGHTS[e] * n for e, n in counts.items())
    sum_text = " + ".join(f"{n} x {WEIGHTS[e]}" if n > 1 else f"{WEIGHTS[e]}" for e, n in counts.items())
    mix = "" if len(metals) == 1 else ", the metals taken as equimolar"
    entries = [
        {"@id": product_id, "@type": ["chebi:ChemicalEntity", "chebi:Molecule", "hlo:Fixed"], "schema:name": label,
         "cpo:hasNoCASNumber": True, "cpo:hasSMILES": ".".join(ions), "cpo:hasMolecularFormula": formula,
         "schema:comment": (f"PBA product of the {' and '.join(n.lower() for n in names)}(II) ion{'s' if len(names) > 1 else ''} with the {source_name} ion. Idealized "
                            f"composition: no potassium, water or vacancies in the lattice{mix} - the real composition of the "
                            f"precipitate is only known after its characterization (Laura Fadler, 05.10.2026). Added by curation "
                            f"for the PBA series ({BY}); formula and SMILES written by that tool, not looked up on PubChem."),
         "cpo:hasMolarMass": ref(f"{product_id}_MolarMass")},
        {"@id": f"{product_id}_MolarMass", "@type": ["cpo:Parameter", "hlo:Fixed", "hlo:Actual"],
         "qudt:hasQuantityKind": ref("quantitykind:MolarMass"), "hlo:hasEvidence": ref(f"{product_id}_MolarMass_Evidence_1")},
        {"@id": f"{product_id}_MolarMass_Evidence_1", "@type": ["cpo:Parameter", "hlo:Evidence"],
         "hlo:hasEvidenceType": ref("hlo:Calculated"),
         "rdfs:comment": (f"Summed from the molecular formula {formula} with the IUPAC 2021 standard atomic weights: "
                          f"{sum_text} = {mass:.3f} g/mol. Not measured - recompute if cpo:hasMolecularFormula changes."),
         "qudt:value": {"@value": f"{mass:.3f}", "@type": "xsd:decimal"}, "qudt:hasUnit": ref("unit:GM-PER-MOL"),
         "cpo:hasDeterminationTask": ref(CALC)}]
    return product_id, entries, f"{product_id}_MolarMass_Evidence_1"


def main():
    if len(sys.argv) < 3 or sys.argv[1].lower() not in SOURCES:
        sys.exit(__doc__)
    source = sys.argv[1].lower()
    key, source_name, source_formula, _, _ = SOURCES[source]
    chemicals = LibraryFile(path_definitions.CHEMICAL_ENTITY_LIBRARY_PATH)
    reactions = LibraryFile(path_definitions.REACTION_LIBRARY_PATH)
    new_chemicals, new_reactions, new_masses = [], [], []

    for combination in sys.argv[2:]:
        metals = combination.replace(" ", "").split("+")
        unknown = [m for m in metals if m not in METALS]
        if unknown or len(set(metals)) != len(metals) or not 1 <= len(metals) <= 6:
            sys.exit(f"Nothing written: '{combination}' - metals out of {', '.join(METALS)}, each once, 1 to 6.")
        metals = sorted(metals, key=lambda m: METALS[m][0])
        reaction_id = f"reaction:PBA_{key}_{'_'.join(metals)}"
        reactions_by_id = reactions.by_id()
        if reaction_id in reactions_by_id:
            print(f"{reaction_id} exists already - left alone.")
            continue
        template_id = f"reaction:PBA_{key}_{COUNT_WORD[len(metals)]}"
        template = reactions_by_id[template_id]
        coefficient = {p.rsplit("_Participant_", 1)[-1]: -reactions_by_id[p]["cpo:hasStoichiometricCoefficient"]
                       for p in [r["@id"] for r in template["cpo:hasParticipant"]]}
        k, c = int(coefficient["Hexacyanoferrate"]), int(coefficient["MetalIon_1"])
        chemicals_by_id = chemicals.by_id()
        product_id, product, mass = product_entries(chemicals_by_id, source, metals, k, c)
        chemicals_by_id.update({e["@id"]: e for e in product})
        assignments = {f"placeholder:PBA_MetalIon_{i}": METALS[m][2] for i, m in enumerate(metals, 1)}
        assignments[f"placeholder:PBA_{key}_{COUNT_WORD[len(metals)]}_Product"] = product_id
        left = " + ".join([f"{k} {source_formula}" if k > 1 else source_formula]
                          + [f"{c} {m}2+" if c > 1 else f"{m}2+" for m in metals])
        product_formula = "".join(f"{m}{c if c > 1 else ''}" for m in metals) + f"[Fe(CN)6]{k if k > 1 else ''}"
        name = f"PBA formation, {source_name}, {' + '.join(metals)}"
        try:
            entries = make_fixed_reaction(
                reactions_by_id, chemicals_by_id, template_id, assignments, reaction_id, name,
                comment=(f"Co-precipitation of the Prussian blue analogue {product_formula} from the {source_name} ion and "
                         f"the {' and '.join(METALS[m][1].lower() for m in metals)}(II) ion{'s' if len(metals) > 1 else ''} "
                         f"in water, net-ionic (potassium and chloride are spectator ions) - the template {template_id} "
                         f"with its placeholders replaced ({BY}; decided by Laura Fadler, 05.10.2026, net-ionic by Laura "
                         f"Fadler and Meng Kong, 06.10.2026). Idealized product; a net balance, not a mechanism."),
                description=f"{left} > {product_formula}")
        except TemplateError as error:
            sys.exit(f"Nothing written: {error}")
        chemicals.graph.extend(product)
        reactions.graph.extend(entries)
        new_chemicals += product
        new_reactions.append((reaction_id, name))
        if mass:
            new_masses.append(mass)

    if new_masses:
        calc = next(e for e in chemicals.graph if e["@id"] == CALC)
        calc["cpo:determines"] = calc["cpo:determines"] + [ref(m) for m in new_masses]
    if new_chemicals:
        chemicals.save()
    if new_reactions:
        reactions.save()
    for reaction_id, name in new_reactions:
        print(f"{reaction_id}  ({name})")
    print(f"reaction library: +{len(new_reactions)} reactions, chemical entity library: +{len(new_masses)} products")


if __name__ == "__main__":
    main()
