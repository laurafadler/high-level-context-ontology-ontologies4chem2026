"""
The real data: every library and every crate, read as one graph (the IDs are unique across them), each
entity with its classes and its level - and what properties it carries.

Level of an entity:
  - hlo:Template, hlo:Fixed, hlo:SeriesSpecific, hlo:ExperimentSpecific in its @type (a template is also
    hlo:Fixed - it counts as a template);
  - otherwise the ID ending _SeriesSpecific / _ExperimentSpecific_<n>;
  - otherwise in a library the level of the entries that point at it (a form or a reference of a template
    belongs to the template level), Fixed if none has one;
  - otherwise in a crate: the series (cpo:ExperimentalSeries) and what describes the whole crate (root
    dataset, links to the libraries) count as Series, a cpo:SingleExperiment as Experiment.
The ontology snapshot a crate carries is a copy of the Ontology Library and is counted once.
"""
import json
import re
from collections import defaultdict

from common import LEVELS, LEVEL_TYPES, as_list, types_of, path_definitions
from helpers.library_files import read_library

SKIP_KEYS = {"@id", "@type", "@context"}


def _crate_paths():
    return sorted(path_definitions.PROJECTS_FOLDER.glob(f"*/crate*/{path_definitions.CRATE_FILE_NAME}"))


def _library_paths():
    return sorted(path_definitions.LIBRARY_FOLDER.glob("*.jsonld"))


def _level_from_type_or_id(entity: dict):
    found = [LEVEL_TYPES[t] for t in types_of(entity) if t in LEVEL_TYPES]
    if "Template" in found:
        return "Template"
    if found:
        return found[0]
    entity_id = entity.get("@id", "")
    if re.search(r"_SeriesSpecific(_|$)", entity_id):
        return "Series"
    if re.search(r"_ExperimentSpecific(_\d+)?$", entity_id):
        return "Experiment"
    return None


def ref_ids(value) -> list:
    return [v["@id"] for v in as_list(value) if isinstance(v, dict) and "@id" in v]


def present(value) -> bool:
    """A property counts as there when it has at least one value that is not empty."""
    for v in as_list(value):
        if isinstance(v, dict):
            if v.get("@id") or v.get("@value") not in (None, ""):
                return True
        elif v not in (None, ""):
            return True
    return False


class Data:
    def __init__(self, tree):
        self.tree = tree
        self.entities = {}        # id -> entity
        self.level = {}           # id -> level
        self.origin = {}          # id -> "library:<file>" / "crate:<identifier>"
        self.reverse = defaultdict(lambda: defaultdict(set))   # prop -> target id -> subjects
        self.sources = []         # what was read, for the README
        self._read()
        self._index()

    # -- reading -------------------------------------------------------------------------------

    def _add(self, entity: dict, origin: str):
        entity_id = entity.get("@id")
        if not entity_id or entity_id in self.entities:
            return
        self.entities[entity_id] = entity
        self.origin[entity_id] = origin

    def _read(self):
        untagged = []
        for path in _library_paths():
            graph = read_library(path).get("@graph", [])
            self.sources.append(f"libraries/{path.name}" + (" (with its details)" if "details" not in path.name else ""))
            for entity in graph:
                self._add(entity, f"library:{path.stem}")
        for path in _crate_paths():
            identifier = path_definitions.identifier_of_crate(path)
            self.sources.append(path.relative_to(path_definitions.BASE_FOLDER).as_posix())
            for entity in json.load(open(path, encoding="utf-8")).get("@graph", []):
                if entity.get("@id", "").startswith("ontology:"):
                    continue      # the ontology snapshot, a copy of the Ontology Library
                self._add(entity, f"crate:{identifier}")
        for entity_id, entity in self.entities.items():
            level = _level_from_type_or_id(entity)
            if level is None and self.origin[entity_id].startswith("crate:"):
                level = "Experiment" if "cpo:SingleExperiment" in types_of(entity) else "Series"
            if level is None:
                untagged.append(entity_id)
            else:
                self.level[entity_id] = level
        # Library entries without a level of their own take the level of what points at them.
        referrers = defaultdict(set)
        for entity_id, entity in self.entities.items():
            for key, value in entity.items():
                if key not in SKIP_KEYS:
                    for target in ref_ids(value):
                        referrers[target].add(entity_id)
        for _ in range(4):
            for entity_id in untagged:
                if entity_id in self.level:
                    continue
                levels = {self.level.get(r) for r in referrers.get(entity_id, ())} - {None}
                if levels:
                    self.level[entity_id] = "Template" if levels == {"Template"} else "Fixed"
        for entity_id in untagged:
            self.level.setdefault(entity_id, "Fixed")

    def _index(self):
        self.classes = {}         # id -> set of classes incl. superclasses
        for entity_id, entity in self.entities.items():
            classes = set()
            for t in types_of(entity):
                if t not in LEVEL_TYPES:
                    classes |= self.tree.ancestors(t)
            classes -= set(LEVEL_TYPES) | {"hlo:Scope"}
            self.classes[entity_id] = classes
            for key, value in entity.items():
                if key not in SKIP_KEYS:
                    for target in ref_ids(value):
                        self.reverse[key][target].add(entity_id)
        self.members = defaultdict(lambda: defaultdict(list))  # class -> level -> ids
        for entity_id, classes in self.classes.items():
            for cls in classes:
                self.members[cls][self.level[entity_id]].append(entity_id)

    # -- counting ------------------------------------------------------------------------------

    def asserted_classes(self) -> set:
        """Classes some entity names in its @type (not only through a subclass)."""
        return {t for e in self.entities.values() for t in types_of(e) if t not in LEVEL_TYPES}

    def count(self, cls: str, level: str) -> int:
        return len(self.members.get(cls, {}).get(level, []))

    def property_counts(self, cls: str, level: str) -> dict:
        """prop -> number of entities of the class on the level that carry it (direct properties)."""
        counts = defaultdict(int)
        for entity_id in self.members.get(cls, {}).get(level, []):
            counts["@type"] += 1
            for key, value in self.entities[entity_id].items():
                if key not in SKIP_KEYS and present(value):
                    counts[key] += 1
        return dict(counts)

    def example(self, cls: str, level: str, prop: str):
        for entity_id in self.members.get(cls, {}).get(level, []):
            if present(self.entities[entity_id].get(prop)):
                return entity_id
        return None

    # -- walking a SHACL path ------------------------------------------------------------------

    def step(self, path, nodes: set) -> set:
        """The values the path reaches from the nodes (IDs; literals as ('lit', value))."""
        kind = path[0]
        if kind == "p" and path[1] in ("rdf:type", "@type"):
            return {t for node in nodes if isinstance(node, str) and node in self.entities
                    for t in types_of(self.entities[node])}
        if kind == "p":
            out = set()
            for node in nodes:
                entity = self.entities.get(node) if isinstance(node, str) else None
                if entity is None:
                    continue
                for v in as_list(entity.get(path[1])):
                    if isinstance(v, dict) and "@id" in v:
                        out.add(v["@id"])
                    elif isinstance(v, dict):
                        out.add(("lit", str(v.get("@value"))))
                    elif v not in (None, ""):
                        out.add(("lit", str(v)))
            return out
        if kind == "inv":
            inner = path[1]
            if inner[0] != "p":
                return set()
            return {s for node in nodes if isinstance(node, str) for s in self.reverse[inner[1]].get(node, ())}
        if kind == "seq":
            for part in path[1]:
                nodes = self.step(part, nodes)
            return nodes
        if kind == "alt":
            return set().union(*(self.step(p, nodes) for p in path[1]))
        if kind in ("star", "plus"):
            reached, frontier = (set(nodes) if kind == "star" else set()), set(nodes)
            for _ in range(10):
                frontier = self.step(path[1], frontier) - reached
                if not frontier:
                    break
                reached |= frontier
            return reached
        if kind == "opt":
            return set(nodes) | self.step(path[1], nodes)
        return set()

    def has_class(self, node, cls: str) -> bool:
        """Also the level classes: hlo:Fixed holds for a template too (hlo:Template is a subclass of hlo:Fixed)."""
        if not isinstance(node, str):
            return False
        if cls in LEVEL_TYPES:
            level = self.level.get(node)
            return level == LEVEL_TYPES[cls] or (cls == "hlo:Fixed" and level == "Template")
        if node in self.classes:
            return cls in self.classes[node]
        return any(self.tree.is_a(t, cls) for t in self.tree.individual_types.get(node, ()))

    def path_count(self, cls: str, level: str, path, end_classes=()) -> int:
        """Entities of the class on the level the path reaches something from (of the end classes, if given)."""
        found = 0
        for entity_id in self.members.get(cls, {}).get(level, []):
            values = self.step(path, {entity_id})
            if end_classes:
                values = {v for v in values if all(self.has_class(v, c) for c in end_classes)}
            if values:
                found += 1
        return found

