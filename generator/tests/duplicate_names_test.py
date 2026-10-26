"""
No two entities of one level of a crate share a name.

A question offers entities by their name; two of the same name in one list make an answer fit both - the run
stops (helpers/user_io.py: _match_option), and the person cannot say which one was meant. Found at two bottles of
one template: their bodies, phases and interfaces were named after the template ("Body material of
glass_bottle_250mL" three times in the hydrogenation) - after the exemplar
(helpers/identifiers.py: aliased_name).

A level is the end of the ID (_SeriesSpecific, _ExperimentSpecific_<n>). Not counted: the chemical entities in
a phase (chebi:ChemicalEntity) - they carry the name of their substance in every phase and are told apart by
the phase they are part of.

Run from the repository root (after building the crates):
    python generator/tests/duplicate_names_test.py [<crate file> ...]
Without arguments: every crate under projects/. Exit code 1 if a name is used twice on one level.
"""
import glob
import json
import re
import sys
from collections import defaultdict

LEVEL = re.compile(r"_(SeriesSpecific|ExperimentSpecific_\d+)$")


def duplicates(path: str) -> dict:
    graph = json.load(open(path, encoding="utf-8"))["@graph"]
    named = defaultdict(list)
    for entity in graph:
        name, types = entity.get("schema:name"), entity.get("@type") or []
        level = LEVEL.search(entity.get("@id", ""))
        if not isinstance(name, str) or not level or "chebi:ChemicalEntity" in (types if isinstance(types, list) else [types]):
            continue
        named[(name, level.group(1))].append(entity["@id"].rsplit("/", 1)[-1])
    return {key: ids for key, ids in named.items() if len(ids) > 1}


def main() -> int:
    paths = sys.argv[1:] or sorted(glob.glob("projects/*/crate*/ro-crate-metadata.json"))
    ok = True
    for path in paths:
        found = duplicates(path)
        ok &= not found
        print(f"{'ok  ' if not found else 'FAIL'} {path}: {len(found)} name(s) used twice on one level")
        for (name, level), ids in list(found.items())[:10]:
            print(f"       {name!r} ({level}): {', '.join(ids)}")
    print("ALL OK" if ok else "DUPLICATE NAMES")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
