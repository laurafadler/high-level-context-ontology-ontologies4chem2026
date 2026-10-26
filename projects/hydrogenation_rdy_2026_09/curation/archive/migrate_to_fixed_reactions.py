"""
Moves the sheet and the answer file of the hydrogenation from the reaction templates to the fixed
reactions (05.10.2026; curation/fixed_reactions.py made them). The mapping comes from the reaction
library itself: every fixed reaction, elementary reaction, participant, mechanism and occupation
state names its template with hlo:specializationOf.

- IDs are replaced as whole IDs: "StoichiometricReaction_0001" -> "Hydrogenation_Adiponitrile_Pt"
  (also in crate IDs built from it, "..._SeriesSpecific"), but not inside an ID that merely contains
  it ("PartialOrder_ElementaryReaction_0001_0001" keeps its name - the partial orders are the
  template's values, shared).
- Names are replaced where they stand as names: "Hydrogenation Reaction" -> the fixed reaction's
  name, "First hydrogen addition to RDY" -> "... to Adiponitrile".
- The species placeholders are no longer asked: their entries go (sheet: open section; answer
  file: their blocks). An occupation state placeholder becomes "occupation_state:<fixed state>".

Writes nothing without --write; then it writes the files given (default: the series' setup.yaml
and answers.txt). Meant for a copy first (isolated run), then the project.

Usage (from the repository root):
    python projects/hydrogenation_rdy_2026_09/curation/migrate_to_fixed_reactions.py [--write] [FILE ...]
"""
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "generator"))
import path_definitions  # noqa: E402
from helpers.file_handling import load_jsonld  # noqa: E402

SERIES = ROOT / "projects" / "hydrogenation_rdy_2026_09"
PREFIX = "Adiponitrile_Pt"
FIXED = ("reaction:Hydrogenation_Adiponitrile_Pt", "reaction:Dimerisation1_Adiponitrile_Pt",
         "reaction:Dimerisation2_Adiponitrile_Pt")


def local(entity_id):
    return entity_id.split(":", 1)[-1]


def mappings():
    """(ID map, name map, dropped placeholder IDs, occupation state map) from the reaction library."""
    graph = load_jsonld(path_definitions.REACTION_LIBRARY_PATH)["@graph"]
    by_id = {e["@id"]: e for e in graph}
    ids, names, occupation = {}, {}, {}
    for entity in graph:
        parent = (entity.get("hlo:specializationOf") or {}).get("@id")
        if not parent or not (entity["@id"].startswith(("reaction:Hydrogenation_", "reaction:Dimerisation1_",
                                                         "reaction:Dimerisation2_")) or local(entity["@id"]).startswith(PREFIX)):
            continue
        if parent.startswith("placeholder:"):
            occupation[local(parent)] = local(entity["@id"])
            continue
        ids[local(parent)] = local(entity["@id"])
        old_name, new_name = by_id[parent].get("schema:name"), entity.get("schema:name")
        if old_name and new_name and old_name != new_name:
            names[old_name] = new_name
    # The mechanisms: template actual -> actual of the fixed reaction.
    for fixed in FIXED:
        template = by_id[by_id[fixed]["hlo:specializationOf"]["@id"]]
        old = local(template["cpo:describedByReactionMechanism"]["@id"])
        ids[old] = local(by_id[fixed]["cpo:describedByReactionMechanism"]["@id"])
    species = [local(e["@id"]) for e in graph if e["@id"].startswith("placeholder:")
               and "cpo:OccupationState" not in e.get("@type", []) and not e["@id"].startswith("placeholder:PBA_")]
    return ids, names, species, occupation


def migrate(text, ids, names, species, occupation):
    counts = {}

    def sub(pattern, replacement, text, label):
        new, n = re.subn(pattern, replacement, text)
        if n:
            counts[label] = counts.get(label, 0) + n
        return new

    # 1. Entries of the substance placeholders: blocks of the answer file, entries in the open section of the sheet.
    for name in species:
        # Anchored at the start of the line and without ambiguous repetition (otherwise exponential backtracking):
        # answer file: key, indented comment lines, one answer line, empty line.
        text = sub(rf"(?m)^key: series:1/placeholder:{re.escape(name)}/[^\n]*\n(?:[ \t][^\n]*\n)*[^\n]*\n\n?", "", text,
                   "answer blocks of species placeholders")
        # Sheet: an entry of the open section with its fields indented by four spaces.
        text = sub(rf"(?m)^  - key: series:1/placeholder:{re.escape(name)}/[^\n]*\n(?:    [^\n]*\n)*", "", text,
                   "open entries of species placeholders")
    # 2. Assignment placeholders -> fixed assignment states.
    for old, new in occupation.items():
        text = sub(rf"placeholder:{re.escape(old)}(?![A-Za-z0-9])", f"occupation_state:{new}", text, "occupation states")
        text = sub(rf"about: placeholder {re.escape(old)}\b", f"about: occupation_state {new}", text, "occupation states")
    # 3. IDs as whole IDs, in one pass over the words (13 MB of text): a word that starts with an
    #    old ID (the whole ID or followed by "_..."), gets the new one - the longest that fits.
    def replace_word(match):
        word = match.group(0)
        parts = word.split("_")
        for n in range(len(parts), 0, -1):
            head = "_".join(parts[:n])
            if head in ids:
                counts["IDs"] = counts.get("IDs", 0) + 1
                return ids[head] + word[len(head):]
        return word
    text = re.sub(r"[A-Za-z0-9_]+", replace_word, text)
    # Then the names.
    for old in sorted(names, key=len, reverse=True):
        text = sub(rf"(?<![\w-]){re.escape(old)}(?![\w-])", names[old], text, "names")
    return text, counts


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="*", type=Path, default=[SERIES / "setup.yaml", SERIES / "answers.txt"])
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    ids, names, species, occupation = mappings()
    print(f"mapping: {len(ids)} IDs, {len(names)} names, {len(species)} species placeholders dropped, "
          f"{len(occupation)} occupation states")
    for path in args.files:
        raw = path.read_bytes()
        newline = "\r\n" if b"\r\n" in raw else "\n"
        text, counts = migrate(raw.decode("utf-8").replace("\r\n", "\n"), ids, names, species, occupation)
        print(f"{path.name}: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
        if args.write:
            path.write_bytes(text.replace("\n", newline).encode("utf-8"))
    if not args.write:
        print("(nothing written - --write to apply)")


if __name__ == "__main__":
    main()
