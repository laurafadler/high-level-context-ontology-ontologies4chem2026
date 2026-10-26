"""
The overview itself: per class one table - rows are properties (or the paths a shape asks for), columns the
four levels - and per class the gaps, where the sources do not fit together.

A cell holds
  status   "required"    a shape with severity Violation, a required field or a check asks for it
           "recommended" a shape with severity Warning asks for it
           "banned"      a shape or check forbids it (sh:maxCount 0)
           "asked"       a question of the generator or an optional field of the entry schema or sheet gives it
           "library"     Template/Fixed: it stands in the library, but nothing above asks for it (written by an
                         entry tool, by a generator run - usage history, lastUsedTime, content ends - or by a
                         curation script; each entry says where it comes from in its comment)
           "derived"     Series/Experiment: it is in the crate, but nothing asks for it - the generator makes it
           ""            nothing
  shapes, fields, questions, checks: where that comes from
  count, total: how many entities of the class on the level have it (data of libraries and crates)
  chain: the demand is met through hlo:specializationOf (a level higher up)

Rows of a superclass hold for its subclasses too; the shapes and sources of a superclass count for a
subclass. The table of a subclass shows only its additions: rows a
shape or source names for exactly this class, and properties that occur only at this class within its parent.
"""
from collections import defaultdict

from common import LEVELS, CHAIN
from evaluate import Evaluator

ACTUAL = "hlo:Actual"
STATUS_ORDER = ["required", "recommended", "banned", "asked", "library", "derived", ""]


class Overview:
    def __init__(self, tree, data, shapes, sources, config):
        self.tree, self.data, self.shapes, self.sources, self.config = tree, data, shapes, sources, config
        self.evaluator = Evaluator(data, shapes.graph)
        self._applicable = {}
        self.skip = set(config.get("skip_classes", []))
        self._collect_classes()
        self._assign_families()
        self._index_sources()
        self.tables = {cls: self._table(cls) for cls in self.classes}
        self.gaps = {cls: self._gaps(cls) for cls in self.classes}

    # -- classes and families ------------------------------------------------------------------

    def _collect_classes(self):
        found = set(self.data.asserted_classes())
        found |= {d["class"] for d in self.shapes.demands}
        found |= {s["class"] for s in self.sources.items}
        roots = {c for f in self.config["families"] for c in f["classes"]}
        # Superclasses up to a family root, so that the tree is complete.
        for cls in list(found):
            for ancestor in sorted(self.tree.ancestors(cls)):
                if any(self.tree.is_a(ancestor, root) for root in roots):
                    found.add(ancestor)
        self.classes = sorted(c for c in found if c not in self.skip)

    def _assign_families(self):
        self.family_of = {}
        families = self.config["families"]
        for cls in self.classes:
            best = None
            for family in families:
                for root in family["classes"]:
                    if self.tree.is_a(cls, root):
                        # The most specific root wins (cpo:Device before nothing; ChemicalContainer under Device).
                        depth = len(self.tree.ancestors(root))
                        if best is None or depth > best[1]:
                            best = (family["id"], depth)
            self.family_of[cls] = best[0] if best else "other"

    def parent_in_overview(self, cls):
        """The nearest superclass that has a table of its own."""
        candidates = [a for a in self.tree.ancestors(cls) - {cls} if a in self.tables_or_classes()]
        if not candidates:
            return None
        return max(sorted(candidates), key=lambda a: len(self.tree.ancestors(a)))

    def tables_or_classes(self):
        return set(self.classes)

    def subclasses(self, cls):
        return sorted(c for c in self.classes if c != cls and self.parent_in_overview(c) == cls)

    # -- sources -------------------------------------------------------------------------------

    def _index_sources(self):
        self.demands_by_class = defaultdict(list)
        for demand in self.shapes.demands:
            self.demands_by_class[demand["class"]].append(demand)
        self.sources_by_class = defaultdict(list)
        for source in self.sources.items:
            self.sources_by_class[source["class"]].append(source)
        # Properties whose values are quantities - what a value of the sheet can give: nearly all their values
        # are process variables (cpo:ProcessVariable), or they are the times of a task or an occurrence.
        variable, other = defaultdict(int), defaultdict(int)
        for entity in self.data.entities.values():
            for key, value in entity.items():
                if key.startswith("@"):
                    continue
                for v in (value if isinstance(value, list) else [value]):
                    if isinstance(v, dict) and "@id" in v:
                        if "cpo:ProcessVariable" in self.data.classes.get(v["@id"], ()):
                            variable[key] += 1
                        else:
                            other[key] += 1
        self.quantity_props = {k for k, n in variable.items() if k.startswith("cpo:has") and n >= 9 * other.get(k, 0)}
        self.quantity_props |= {"cpo:hasStartTime", "cpo:hasEndTime", "cpo:hasDuration"}
        self.quantity_props -= {"cpo:hasInputValue"}     # points at quantities, is none itself
        self.quantity_places = self.config["sheet"]["quantity_places"]

    def inherited(self, by_class, cls):
        found = []
        for ancestor in sorted(self.tree.ancestors(cls)):
            found += by_class.get(ancestor, [])
        return found

    # -- one table -----------------------------------------------------------------------------

    def _table(self, cls):
        counts = {level: self.data.property_counts(cls, level) for level in LEVELS}
        totals = {level: self.data.count(cls, level) for level in LEVELS}
        rows = {}

        def row(key):
            if key not in rows:
                rows[key] = {"key": key, "first": first_property_of(key), "own": False, "path": None,
                             "cells": {level: new_cell(totals[level]) for level in LEVELS}, "notes": []}
            return rows[key]

        # Data
        for level in LEVELS:
            for prop, n in counts[level].items():
                r = row(prop)
                r["cells"][level]["count"] = n
        # Shapes (own and inherited)
        for demand in self.inherited(self.demands_by_class, cls):
            r = row(demand["row"])
            if demand["class"] == cls:
                r["own"] = True
            if r["path"] is None and demand["path"] is not None and demand["path"][0] != "p":
                r["path"] = (demand["path"], demand["chain"], demand["end_classes"])
            for level in LEVELS:
                if level not in demand["levels"]:
                    continue
                cell = r["cells"][level]
                cell["shapes"].append(demand)
                if demand["chain"]:
                    cell["chain"] = True
            if demand["constraint"]:
                note = f"{demand['source']}: {demand['constraint']}"
                if note not in r["notes"]:
                    r["notes"].append(note)
        # Sources (own and inherited)
        for source in self.inherited(self.sources_by_class, cls):
            r = row(source["row"])
            if source["class"] == cls:
                r["own"] = True
            for level in source["levels"]:
                r["cells"][level][source["kind"] + "s"].append(source)
        # The quantity of a value of the sheet: every quantity property of a place.
        if any(self.tree.is_a(cls, place) for place in self.quantity_places):
            for key, r in rows.items():
                if key in self.quantity_props:
                    for field in self.sources.quantity_fields:
                        for level in field["levels"]:
                            r["cells"][level]["sheets"].append({"label": field["label"], "need": field["need"],
                                                                "kind": "sheet", "note": field["note"], "class": cls, "quantity": True})
        # Counts: on a level where a shape asks for the row, only the entities the shape applies to (its
        # exemptions and conditions, evaluate.py); a row that is a path, or met through the chain, is followed
        # in the data.
        for key, r in rows.items():
            for level in LEVELS:
                cell = r["cells"][level]
                if not totals[level]:
                    continue
                demands = [d for d in cell["shapes"] if d["kind"] in ("demand", "ban")]
                members = self.data.members.get(cls, {}).get(level, [])
                if demands:
                    entities = set()
                    for demand in demands:
                        entities |= self.applicable(demand, level)
                    entities &= set(members)      # a subclass counts only its own entities
                else:
                    entities = members
                cell["total"] = len(entities)
                cell["class_total"] = totals[level]
                cell["count"] = sum(1 for e in entities if self.has_row(r, e, cell["chain"]))
        # Property-wide notes of the shapes (formats, quantity kinds).
        for key, r in rows.items():
            for note in self.shapes.property_notes.get(key, []):
                if note not in r["notes"]:
                    r["notes"].append(note)
        for r in rows.values():
            for level in LEVELS:
                finish_cell(r["cells"][level], level)
        return {"class": cls, "totals": totals,
                "rows": sorted(rows.values(), key=lambda r: (r["first"].lstrip("^(").lower(), r["key"]))}

    def shown_rows(self, cls):
        """The rows the table of the class shows: all for a class without a parent in the overview,
        otherwise its own rows and the properties that occur only at it within its parent."""
        table = self.tables[cls]
        parent = self.parent_in_overview(cls)
        if parent is None:
            return table["rows"]
        parent_rows = {r["key"]: r for r in self.tables[parent]["rows"]}
        shown = []
        for r in table["rows"]:
            if r["own"] or r["key"] not in parent_rows:
                shown.append(r)
                continue
            mine = sum(c["count"] for c in r["cells"].values())
            theirs = sum(c["count"] for c in parent_rows[r["key"]]["cells"].values())
            parent_total = sum(self.tables[parent]["totals"].values())
            my_total = sum(table["totals"].values())
            if mine and mine == theirs and my_total < parent_total:
                shown.append(r)
        return shown

    # -- evaluating a demand ------------------------------------------------------------------

    def applicable(self, demand, level) -> set:
        """The entities of the demand's class on the level it applies to (its exemptions and conditions hold)."""
        key = (id(demand), level)
        if key not in self._applicable:
            self._applicable[key] = {e for e in self.evaluator.focus_entities(demand, level)
                                     if self.evaluator.applies(demand, e)}
        return self._applicable[key]

    def met(self, demand, level) -> set:
        key = (id(demand), level, "met")
        if key not in self._applicable:
            self._applicable[key] = {e for e in self.applicable(demand, level) if self.evaluator.met(demand, e)}
        return self._applicable[key]

    def has_row(self, r, entity, chain) -> bool:
        if r["path"] is not None:
            path, path_chain, end = r["path"]
            values = self.data.step(("seq", [CHAIN, path]) if path_chain else path, {entity})
            if end:
                values = {v for v in values if all(self.data.has_class(v, c) for c in end)}
            return bool(values)
        if r["key"] == "@type":
            return True
        if chain:
            return bool(self.data.step(("seq", [CHAIN, ("p", r["key"])]), {entity}))
        value = self.data.entities[entity].get(r["key"])
        return value not in (None, "", [])

    # -- gaps ----------------------------------------------------------------------------------

    def _gaps(self, cls):
        """Where the sources of one class do not fit together. Only demands and sources named for this
        class itself are judged here (inherited ones are judged at their own class, with the data of all
        its subclasses), so that a gap is reported once."""
        table = self.tables[cls]
        gaps = []
        # A field for a property counts as asked for by a shape too when the shape's path starts with it
        # among alternatives ((cpo:location | cpo:locatedAt | cpo:locatedInsideOf)).
        covering = defaultdict(list)
        for r in table["rows"]:
            for level in LEVELS:
                for demand in r["cells"][level]["shapes"]:
                    if demand["path"] is not None and [r["key"]] != demand.get("first_props", []):
                        for prop in demand.get("first_props", []):
                            covering[(prop, level)].append(demand)
        for r in table["rows"]:
            chain_gap = False      # a demand met through the chain is reported once, at the highest level
            for level in LEVELS:
                cell = r["cells"][level]
                total = table["totals"][level]
                if not total:
                    continue      # no entity of the class on this level - nothing to compare
                own_shapes = [d for d in cell["shapes"] if d["class"] == cls and d["kind"] in ("demand", "ban")
                              and not d["continuation"]]
                fields = [s for s in cell["entrys"] + cell["sheets"] if s.get("class") == cls and not s.get("quantity")
                          and s["need"] != "derived"]
                given = cell["entrys"] + cell["sheets"] + cell["questions"]
                checks = cell["checks"]
                chained = bool(own_shapes) and all(d["chain"] for d in own_shapes)
                if chained:
                    # Met through the chain: what gives it on a higher level gives it here too.
                    given = [s for c in r["cells"].values() for s in c["entrys"] + c["sheets"] + c["questions"]]
                if chained and chain_gap:
                    own_shapes = []
                by_source = defaultdict(list)
                for demand in own_shapes:
                    by_source[demand["source"]].append(demand)
                for source, demands in sorted(by_source.items()):
                    applicable = set().union(*(self.applicable(d, level) for d in demands))
                    met = set().union(*(self.met(d, level) for d in demands))
                    if applicable and len(met) < len(applicable):
                        chain_gap = chain_gap or chained
                        gaps.append({"type": "short" if given else "unsupplied", "row": r["key"], "level": level,
                                     "count": len(met), "total": len(applicable), "of": total,
                                     "alternatives": any(d["alternatives"] for d in demands),
                                     "ban": all(d["kind"] == "ban" for d in demands),
                                     "severity": "Violation" if any(d["severity"] == "Violation" for d in demands) else "Warning",
                                     "shapes": [source],
                                     "given": sorted({s["label"] for s in given}),
                                     "missing_in": self._missing_in(applicable - met)})
                shapes_here = cell["shapes"] + covering.get((r["key"], level), [])
                if fields and not shapes_here and not checks:
                    required = [s for s in fields if s["need"] == "required"]
                    gaps.append({"type": "unchecked_required" if required else "unchecked", "row": r["key"],
                                 "level": level, "fields": sorted({s["label"] for s in fields})})
                if fields and cell["shapes"]:
                    violation = any(d["severity"] == "Violation" and d["kind"] == "demand" and not d["alternatives"]
                                    for d in cell["shapes"])
                    required = any(s["need"] in ("required", "conditional") for s in fields)
                    if violation and not required and not cell["chain"] and not cell["questions"]:
                        gaps.append({"type": "strictness", "row": r["key"], "level": level,
                                     "fields": sorted({s["label"] for s in fields}),
                                     "shapes": sorted({d["source"] for d in cell["shapes"]})})
                # Read through the chain counts (a literal of the series, rule 3.6).
                if fields and total and r["path"] is None \
                        and not any(self.has_row(r, e, True) for e in self.data.members.get(cls, {}).get(level, [])):
                    gaps.append({"type": "unused_field", "row": r["key"], "level": level, "total": total,
                                 "fields": sorted({s["label"] for s in fields})})
                questions = [s for s in cell["questions"] if s["class"] == cls and not s.get("by_sheet")]
                if level in ("Series", "Experiment") and questions and not cell["sheets"]:
                    gaps.append({"type": "not_on_sheet", "row": r["key"], "level": level,
                                 "questions": sorted({s["label"] for s in questions})})
        return gaps

    def _missing_in(self, entities):
        """Which asserted classes the entities that lack it have - for a superclass, where the gap lies."""
        missing = defaultdict(int)
        for entity_id in entities:
            types = self.data.entities[entity_id].get("@type")
            types = [t for t in (types if isinstance(types, list) else [types]) if t and not t.startswith("hlo:")]
            missing[", ".join(types) or "?"] += 1
        return sorted(missing.items(), key=lambda kv: (-kv[1], kv[0]))


def first_property_of(key):
    return key.split(" / ")[0]


def new_cell(total):
    return {"count": 0, "total": total, "shapes": [], "entrys": [], "sheets": [], "questions": [], "checks": [],
            "chain": False, "status": ""}


def finish_cell(cell, level):
    demands = [d for d in cell["shapes"] if d["kind"] == "demand"]
    bans = [d for d in cell["shapes"] if d["kind"] == "ban"] + [c for c in cell["checks"] if c["need"] == "ban"]
    required_fields = [s for s in cell["entrys"] + cell["sheets"] if s["need"] == "required"]
    required_checks = [c for c in cell["checks"] if c["need"] == "required"]
    if any(d["severity"] == "Violation" for d in demands) or required_fields or required_checks:
        cell["status"] = "required"
    elif demands:
        cell["status"] = "recommended"
    elif bans:
        cell["status"] = "banned"
    elif [s for s in cell["entrys"] + cell["sheets"] + cell["questions"] if s["need"] != "derived"]:
        cell["status"] = "asked"
    elif cell["count"] or cell["entrys"]:
        cell["status"] = "library" if level in ("Template", "Fixed") else "derived"
    else:
        cell["status"] = ""
