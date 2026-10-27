"""
Builds the class maps (docs/class_maps.html): one mind map per class, the way the classes were sketched on
paper before the generator was written. In the middle the class with its comment from the ontology and its
subclasses in brackets; around it one box per class it points at, with the properties that point there; the
quantities and the plain values each in a box of their own.

What goes into a map comes from the property overview (generator/workflow/property_overview/, its modules are
reused here):
  - which classes:  the root classes of the families in overview_config.yaml; subclasses get no map of their
                    own, they stand in brackets at their parent
  - which properties: the rows of the class's table; a path row (a / b / c) counts for a, an alternative
                    (a | b) for a and for b, a leading ^ is dropped; class_maps.hidden_properties are left out
  - how strongly:   per level the strongest status of its rows - required and recommended stay, asked, library
                    and derived become optional; the page draws the strongest level as the line style
  - pointing at:    the classes of the values in the data (not hlo: if there is another, the most specific one,
                    then its family root), else rdfs:range; without either it is a plain value ("Attributes")
  - "only <Sub>":   from the model only - the rdfs:domain of the property is a subclass, or a shape asks for it
                    only at a subclass (never from where it happens to occur in the data)

Usage (from the repository root):
    python generator/workflow/class_maps/build_class_maps.py           write docs/class_maps.html
    python generator/workflow/class_maps/build_class_maps.py --check   only say whether it is up to date

Reads only; run on demand, like the property overview.
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "property_overview"))

from common import ROOT, LEVELS, ClassTree, as_list  # noqa: E402
from data import Data  # noqa: E402
from shapes import ShapeReader  # noqa: E402
from sources import Sources, load_config  # noqa: E402
from model import Overview  # noqa: E402

HTML = ROOT / "docs" / "class_maps.html"
TEMPLATE = HERE / "class_maps_template.html"

# Status of a cell of the property overview -> status on the map ("banned" and "" stay empty).
MAP_STATUS = {"required": "required", "recommended": "recommended",
              "asked": "optional", "library": "optional", "derived": "optional"}
RANK = {"required": 3, "recommended": 2, "optional": 1, "": 0}


def split_top(text: str, sep: str) -> list:
    """Splits at sep outside of brackets: 'a / (b / c | d)' -> ['a', '(b / c | d)']."""
    parts, depth, start, i = [], 0, 0, 0
    while i < len(text):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
        elif depth == 0 and text.startswith(sep, i):
            parts.append(text[start:i].strip())
            i += len(sep)
            start = i
            continue
        i += 1
    parts.append(text[start:].strip())
    return parts


def row_properties(key: str) -> list:
    """The properties a row of the table counts for: 'a / b' -> [a]; '(a | b) / c' -> [a, b]; '^a' -> [a].
    A leading step that may be left out ('(a | b)* / c') does not count, the row counts for c."""
    steps = split_top(key, " / ")
    while len(steps) > 1 and steps[0].endswith(("*", "?")):
        steps = steps[1:]
    first = steps[0].rstrip("*+?")
    if first.startswith("(") and first.endswith(")"):
        return [p for alternative in split_top(first[1:-1], " | ") for p in row_properties(alternative)]
    return [first.lstrip("^")]


class ClassMaps:
    def __init__(self, overview, config):
        self.overview, self.tree, self.data = overview, overview.tree, overview.data
        settings = config["class_maps"]
        self.hidden = set(settings["hidden_properties"])
        self.quantity_classes = set(settings["quantity_classes"])
        self.start = settings["start"]
        self.families = [{"title": f["title"], "classes": [c for c in f["classes"] if c in overview.classes]}
                         for f in config["families"]]
        self.roots = [c for f in self.families for c in f["classes"]]

    def root_of(self, cls: str) -> str:
        """The nearest family root above the class (the class itself if it is one), else the class."""
        roots = [r for r in self.roots if self.tree.is_a(cls, r)]
        if not roots:
            return cls
        return max(sorted(roots), key=lambda r: len(self.tree.ancestors(r)))

    # -- what a property points at ------------------------------------------------------------

    def value_class(self, value_id: str):
        """The class a value is shown under: not hlo: if it has another class, the most specific one, as its
        family root. None for a value without a known class."""
        classes = self.data.classes.get(value_id, set())
        candidates = [c for c in classes if not c.startswith("hlo:")] or [c for c in classes if c in self.roots]
        if not candidates:
            return None
        most_specific = sorted(candidates, key=lambda c: (-len(self.tree.ancestors(c)), c))[0]
        return self.root_of(most_specific)

    def target(self, prop: str, entities: list):
        """(class the property points at or None, all classes it points at, whether it has plain values).
        The most frequent class of the values wins."""
        found, literal = Counter(), False
        for entity_id in entities:
            for value in as_list(self.data.entities[entity_id].get(prop)):
                if isinstance(value, dict) and "@id" in value:
                    cls = self.value_class(value["@id"])
                    if cls:
                        found[cls] += 1
                elif value not in (None, "", {}):
                    literal = True
        if found:
            return sorted(found, key=lambda c: (-found[c], c))[0], set(found), literal
        if not literal:
            ranges = sorted(r for r in self.tree.ranges.get(prop, ()) if r)
            if ranges:
                return self.root_of(ranges[0]), {self.root_of(ranges[0])}, False
        return None, set(), literal

    # -- "only <Subclass>" --------------------------------------------------------------------

    def only(self, prop: str, cls: str, subs: list):
        """(subclasses the property holds for alone, "domain" / "shape"), or ([], "") - from the model only."""
        if not subs:
            return [], ""
        below = lambda c: [s for s in subs if self.tree.is_a(c, s)]  # noqa: E731
        domains = self.tree.domains.get(prop, set())
        if domains and None not in domains and all(below(d) for d in domains):
            return sorted({s for d in domains for s in below(d)}), "domain"
        # A shape at a subclass, and nothing - shape, field, question or check - at the class or above it.
        at_sub, at_class = set(), False
        for demand in self.overview.shapes.demands:
            if prop in row_properties(demand["row"]):
                at_sub |= set(below(demand["class"]))
                at_class |= self.tree.is_a(cls, demand["class"])
        for source in self.overview.sources.items:
            if prop in row_properties(source["row"]):
                at_class |= self.tree.is_a(cls, source["class"])
        if at_sub and not at_class:
            return sorted(at_sub), "shape"
        return [], ""

    # -- one map ------------------------------------------------------------------------------

    def class_map(self, cls: str) -> dict:
        subs = self.overview.subclasses(cls)
        entities = sorted({e for ids in self.data.members.get(cls, {}).values() for e in ids})
        levels, alternatives = {}, []
        for row in self.overview.tables[cls]["rows"]:
            props = [p for p in row_properties(row["key"]) if p not in self.hidden]
            for prop in props:
                strongest = levels.setdefault(prop, dict.fromkeys(LEVELS, ""))
                for level in LEVELS:
                    status = MAP_STATUS.get(row["cells"][level]["status"], "")
                    if RANK[status] > RANK[strongest[level]]:
                        strongest[level] = status
            if len(props) > 1:
                alternatives.append(props)
        props = {}
        for prop in sorted(levels):
            target, targets, literal = self.target(prop, entities)
            only, only_from = self.only(prop, cls, subs)
            # A quantity: one the overview knows, or all its values are quantities (cpo:determines, whose values
            # are also points in time and statuses, is a branch to cpo:ProcessVariable instead).
            quantity = prop in self.overview.quantity_props or bool(targets) and targets <= self.quantity_classes
            props[prop] = {"levels": levels[prop], "target": target, "literal": literal, "quantity": quantity,
                           "only": only, "only_from": only_from}
        # Named in one alternative together with a quantity (cpo:hasDropletSizeDistribution): a quantity too.
        for group in alternatives:
            if any(props[p]["quantity"] for p in group):
                for p in group:
                    if props[p]["target"] is None and not props[p]["literal"]:
                        props[p]["quantity"] = True
        for entry in props.values():
            del entry["literal"]
        return {"comment": self.comment(cls), "subclasses": subs,
                "sub_comments": {s: self.comment(s) for s in subs}, "props": props}

    def comment(self, cls: str) -> str:
        return " ".join((self.tree.labels.get(cls) or "").split())

    def page_data(self) -> dict:
        return {cls: self.class_map(cls) for cls in self.roots}


def build() -> str:
    """The text of docs/class_maps.html."""
    config = load_config()
    tree = ClassTree()
    overview = Overview(tree, Data(tree), ShapeReader(), Sources(config, tree), config)
    maps = ClassMaps(overview, config)

    def js(value):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")

    families = [f for f in maps.families if f["classes"]]
    return (TEMPLATE.read_text(encoding="utf-8")
            .replace("__DATA__", js(maps.page_data()))
            .replace("__FAMILIES__", js(families))
            .replace("__START__", js(maps.start)))


def main():
    parser = argparse.ArgumentParser(description="Build the class maps (docs/class_maps.html).")
    parser.add_argument("--check", action="store_true", help="only report whether the page is up to date")
    args = parser.parse_args()
    text = build()
    changed = not HTML.exists() or HTML.read_text(encoding="utf-8") != text
    if args.check:
        if changed:
            print(f"out of date: {HTML.relative_to(ROOT).as_posix()}")
            sys.exit(1)
        print("class maps up to date")
        return
    HTML.write_text(text, encoding="utf-8", newline="\n")
    print(f"{HTML.relative_to(ROOT).as_posix()}" + (" (changed)" if changed else " (unchanged)"))


if __name__ == "__main__":
    main()
