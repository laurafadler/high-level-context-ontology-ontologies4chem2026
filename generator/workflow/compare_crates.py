"""
Compare two crates by meaning, not by text: entity by entity (matched on @id), property by
property, references included.

"It runs through" is no check - a run can end with exit code 0 and still have produced an
incomplete crate. This is the check behind every refactoring of the generator: make a
reference run, change the code, run again, compare.

What is ignored:
- dateCreated / dateModified / datePublished (they change on every run),
- the order of values in a list (JSON-LD values are sets; a different creation order is not a
  different statement).

With --id-map the IDs of the FIRST crate are renamed before comparing: a JSON object
{"#old_id": "#new_id", ...}, or a driver report of generator/workflow/answer_driver.py (its
"id_migration"). That is the comparison for a change that renames entities on purpose
(content-based IDs): after the renaming, the crates must
be identical.

The map only needs to name the ROOTS. An ID built from a root's local name - a flowrate, a
volume, an interface ("#Flowrate_Stream_0001_SeriesSpecific") - is renamed along with it:
wherever the old local name of a root appears in an ID of the same level, it is replaced by
the new one.

Run from the repository root:
    PYTHONPATH=. python generator/workflow/compare_crates.py OLD.jsonld NEW.jsonld [--id-map map.json] [--show 20]

Exit code 0 if the crates are identical, 1 otherwise.
"""
import argparse
import collections
import json
import sys
from pathlib import Path

# Runs from generator/workflow/ - the generator has to be on the search path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from helpers.identifiers import translate_id  # noqa: E402

IGNORED_PROPERTIES = {"dateCreated", "dateModified", "datePublished",
                      "schema:dateCreated", "schema:dateModified", "schema:datePublished"}


def expand_id_map(root_map, all_ids):
    """Extend a map of root IDs to every ID built from a root's local name - the same
    translation the generator uses in the other direction (helpers/identifiers.py:
    translate_id)."""
    expanded = {}
    for entity_id in all_ids:
        renamed = translate_id(entity_id, root_map)
        if renamed != entity_id:
            expanded[entity_id] = renamed
    return expanded


def read_id_map(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data["id_migration"] if isinstance(data, dict) and "id_migration" in data else data


def _rename(value, id_map):
    """Apply the ID map to every @id in a value, recursively."""
    if isinstance(value, dict):
        return {k: (id_map.get(v, v) if k == "@id" else _rename(v, id_map)) for k, v in value.items()}
    if isinstance(value, list):
        return [_rename(v, id_map) for v in value]
    return value


def _canonical(value):
    """A comparable form: lists sorted by their canonical JSON, a single-element list the same
    as its element (both mean one value)."""
    if isinstance(value, dict):
        return {k: _canonical(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        items = [_canonical(v) for v in value]
        if len(items) == 1:
            return items[0]
        return sorted(items, key=lambda v: json.dumps(v, sort_keys=True, ensure_ascii=False))
    return value


def load(path, id_map=None):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if id_map:
        id_map = expand_id_map(id_map, [e["@id"] for e in data.get("@graph", [])])
    entities = {}
    for entity in data.get("@graph", []):
        entity = {k: v for k, v in entity.items() if k not in IGNORED_PROPERTIES}
        if id_map:
            entity = _rename(entity, id_map)
        entity_id = entity["@id"]
        if entity_id in entities:
            raise ValueError(f"{path}: @id {entity_id} occurs twice")
        entities[entity_id] = _canonical(entity)
    return data.get("@context"), entities


def compare(old_path, new_path, id_map=None, show=20):
    old_context, old = load(old_path, id_map)
    new_context, new = load(new_path)

    only_old = sorted(set(old) - set(new))
    only_new = sorted(set(new) - set(old))
    changed = sorted(i for i in set(old) & set(new) if old[i] != new[i])

    print(f"entities:        {len(old)} -> {len(new)}")
    print(f"only in first:   {len(only_old)}")
    print(f"only in second:  {len(only_new)}")
    print(f"changed:         {len(changed)}")
    print(f"@context:        {'identical' if old_context == new_context else 'DIFFERENT'}")

    if only_old:
        print(f"\n--- only in first (up to {show}) ---")
        for entity_id in only_old[:show]:
            print(f"  {entity_id}")
    if only_new:
        print(f"\n--- only in second (up to {show}) ---")
        for entity_id in only_new[:show]:
            print(f"  {entity_id}")
    if changed:
        # Grouped by changed properties: 42 entities with the same change are one statement, not 42.
        groups = collections.defaultdict(list)
        for entity_id in changed:
            props = tuple(sorted(p for p in set(old[entity_id]) | set(new[entity_id])
                                 if old[entity_id].get(p) != new[entity_id].get(p)))
            groups[props].append(entity_id)
        print(f"\n--- changed, grouped by property ({len(groups)} groups) ---")
        for props, ids in sorted(groups.items(), key=lambda item: -len(item[1])):
            print(f"  {len(ids):4}x  {', '.join(props)}")
            example = ids[0]
            for prop in props[:3]:
                print(f"         e.g. {example}  {prop}:")
                print(f"              first:  {json.dumps(old[example].get(prop), ensure_ascii=False)[:160]}")
                print(f"              second: {json.dumps(new[example].get(prop), ensure_ascii=False)[:160]}")

    identical = not (only_old or only_new or changed) and old_context == new_context
    print(f"\n{'IDENTICAL' if identical else 'DIFFERENT'}")
    return identical


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("first")
    parser.add_argument("second")
    parser.add_argument("--id-map", help="JSON object {old @id: new @id}, applied to the first crate")
    parser.add_argument("--show", type=int, default=20, help="how many IDs to list per section")
    args = parser.parse_args()
    id_map = read_id_map(args.id_map) if args.id_map else None
    sys.exit(0 if compare(args.first, args.second, id_map, args.show) else 1)


if __name__ == "__main__":
    main()
