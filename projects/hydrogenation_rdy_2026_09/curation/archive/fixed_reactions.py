"""
Fixed reactions of the hydrogenation (05.10.2026, decided by Laura Fadler - one concept for every
crate, rule 2.11): the three reactions of the hydrogenation with their placeholders become
templates (hlo:Template; their elementary reactions too), and three fixed reactions with the
species of this series specialize them - with their mechanisms, fixed elementary reactions and
fixed occupation states (the interface of an occupation state is still asked per series).

The species are those the answer file of the series gave the placeholders (series:1/placeholder:…,
as of 05.10.2026): RDY adiponitrile, RYE 6-iminocapronitrile, RYA 6-aminocapronitrile, REA
6-iminohexylamine, RDEt hexamethylenediamine, Dimer1/Dimer2, catalyst platinum with its H- and
X-type active sites. Made with generator/workflow/library_prerun/fixed_reaction_from_template.py.

The sheet and the answer file of the series still name the templates until they are migrated
(migrate_to_fixed_reactions.py) - the crate is rebuilt from them afterwards.

Usage (from the repository root):
    python projects/hydrogenation_rdy_2026_09/curation/fixed_reactions.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "generator" / "workflow" / "library_prerun"))
sys.path.insert(0, str(ROOT / "generator"))
import path_definitions  # noqa: E402
from fixed_reaction_from_template import LibraryFile, TemplateError, write_group  # noqa: E402

TEMPLATES = ["reaction:StoichiometricReaction_0001", "reaction:StoichiometricReaction_0002",
             "reaction:StoichiometricReaction_0003"]
SPEC = {
    "prefix": "Adiponitrile_Pt",
    "comment": ("The template with the species of the hydrogenation series hydrogenation_rdy_2026_09 (adiponitrile on "
                "platinum), as its answer file resolved the placeholders - made by Claude Code with "
                "fixed_reaction_from_template.py on 05.10.2026 (one concept for every crate, decided by Laura Fadler)."),
    "assignments": {
        "placeholder:RDY": "chem:Molecule_0008",            # Adiponitrile
        "placeholder:RYE": "chem:Molecule_0009",            # 6-Iminocapronitrile
        "placeholder:RYA": "chem:Molecule_0010",            # 6-Aminocapronitrile
        "placeholder:REA": "chem:Molecule_0011",            # 6-Iminohexylamine
        "placeholder:RDEt": "chem:Molecule_0007",           # Hexamethylenediamine
        "placeholder:Dimer1": "chem:Molecule_0012",
        "placeholder:Dimer2": "chem:Molecule_0013",
        "placeholder:Catalyst": "chem:Molecule_0002",       # Platinum
        "placeholder:CatalystSiteH": "chem:ActiveSite_0001",
        "placeholder:CatalystSiteX": "chem:ActiveSite_0002",
    },
    "reactions": [
        {"template": "reaction:StoichiometricReaction_0001", "id": "reaction:Hydrogenation_Adiponitrile_Pt",
         "name": "Hydrogenation of adiponitrile to hexamethylenediamine on platinum"},
        {"template": "reaction:StoichiometricReaction_0002", "id": "reaction:Dimerisation1_Adiponitrile_Pt",
         "name": "Dimerisation of 6-iminocapronitrile with hexamethylenediamine on platinum"},
        {"template": "reaction:StoichiometricReaction_0003", "id": "reaction:Dimerisation2_Adiponitrile_Pt",
         "name": "Dimerisation of 6-iminohexylamine with hexamethylenediamine on platinum"},
    ],
}


def mark_templates():
    """The three reactions and the elementary reactions of their mechanisms carry hlo:Template."""
    library = LibraryFile(path_definitions.REACTION_LIBRARY_PATH)
    by_id = library.by_id()
    marked = []
    for reaction_id in TEMPLATES:
        ids = [reaction_id]
        mechanism = by_id[by_id[reaction_id]["cpo:describedByReactionMechanism"]["@id"]]
        for reference in mechanism["hlo:hasReference"]:
            ids += [e["@id"] for e in by_id[reference["@id"]]["cpo:containsElementaryReaction"]]
        for entity_id in ids:
            types = by_id[entity_id]["@type"]
            if "hlo:Template" not in types:
                types.append("hlo:Template")
                marked.append(entity_id)
    library.save()
    return marked


def main():
    marked = mark_templates()
    print(f"marked as templates: {len(marked)}")
    try:
        made = write_group(SPEC)
    except TemplateError as error:
        sys.exit(f"Nothing written: {error}")
    print("fixed reactions added (balanced): " + ", ".join(made))


if __name__ == "__main__":
    main()
