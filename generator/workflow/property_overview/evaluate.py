"""
A small SHACL evaluator on the data as JSON - only what the shapes of this project use (sh:class, sh:property
with path, sh:minCount, sh:maxCount, sh:hasValue, sh:in, sh:node, sh:qualifiedValueShape, sh:or, sh:and,
sh:not). It decides, per entity, whether a demand of the overview applies (its exemptions and conditions) and
whether it is met (one of its alternatives), so that "k of n" counts only the entities a shape is about.

Not a replacement for pyshacl (workflow/run_shacl.py stays the check): sh:pattern, sh:datatype, sh:equals and
the like are taken as met.
"""
from rdflib import URIRef
from rdflib.collection import Collection

from common import SH, curie, read_path, CHAIN


def sh(name):
    return URIRef(SH + name)


class Evaluator:
    def __init__(self, data, graph):
        self.data, self.graph = data, graph
        self._cache = {}
        self._paths = {}

    def v(self, node, name):
        return self.graph.value(node, sh(name))

    def vs(self, node, name):
        return list(self.graph.objects(node, sh(name)))

    def path(self, node):
        if node not in self._paths:
            self._paths[node] = read_path(self.graph, node)
        return self._paths[node]

    @staticmethod
    def same(value, expected) -> bool:
        if isinstance(value, tuple):
            return str(value[1]).lower() == str(expected).lower()
        return value == expected

    def conforms(self, node, focus) -> bool:
        key = (node, focus)
        if key in self._cache:
            return self._cache[key]
        self._cache[key] = True        # against cycles
        result = self._conforms(node, focus)
        self._cache[key] = result
        return result

    def _conforms(self, node, focus) -> bool:
        for cls in self.vs(node, "class"):
            if not self.data.has_class(focus, curie(cls)):
                return False
        for value in self.vs(node, "hasValue"):
            if not self.same(focus, curie(value)):
                return False
        for in_list in self.vs(node, "in"):
            if not any(self.same(focus, curie(x)) for x in Collection(self.graph, in_list)):
                return False
        if self.v(node, "path") is not None and not self.property_conforms(node, focus):
            return False
        for prop in self.vs(node, "property"):
            if not self.property_conforms(prop, focus):
                return False
        for inner in self.vs(node, "node"):
            if not self.conforms(inner, focus):
                return False
        for inner in self.vs(node, "not"):
            if self.conforms(inner, focus):
                return False
        for and_list in self.vs(node, "and"):
            if not all(self.conforms(item, focus) for item in Collection(self.graph, and_list)):
                return False
        for or_list in self.vs(node, "or"):
            if not any(self.conforms(item, focus) for item in Collection(self.graph, or_list)):
                return False
        return True

    def property_conforms(self, prop, focus) -> bool:
        values = self.data.step(self.path(self.v(prop, "path")), {focus}) if isinstance(focus, str) else set()
        minimum = self.v(prop, "minCount")
        if minimum is not None and len(values) < int(minimum):
            return False
        maximum = self.v(prop, "maxCount")
        if maximum is not None and len(values) > int(maximum):
            return False
        for value in self.vs(prop, "hasValue"):
            if not any(self.same(v, curie(value)) for v in values):
                return False
        for cls in self.vs(prop, "class"):
            if not all(self.data.has_class(v, curie(cls)) for v in values):
                return False
        for in_list in self.vs(prop, "in"):
            allowed = [curie(x) for x in Collection(self.graph, in_list)]
            if not all(any(self.same(v, a) for a in allowed) for v in values):
                return False
        for inner in self.vs(prop, "node"):
            if not all(self.conforms(inner, v) for v in values):
                return False
        qualified = self.v(prop, "qualifiedValueShape")
        if qualified is not None:
            count = sum(1 for v in values if self.conforms(qualified, v))
            q_min = self.v(prop, "qualifiedMinCount")
            q_max = self.v(prop, "qualifiedMaxCount")
            if q_min is not None and count < int(q_min):
                return False
            if q_max is not None and count > int(q_max):
                return False
        return True

    # -- demands of the overview ---------------------------------------------------------------

    def _at(self, prefix, entity):
        return self.data.step(prefix, {entity}) if prefix is not None else {entity}

    def focus_entities(self, demand, level) -> list:
        """The entities of the demand's class on the level - for a demand reached from another class (the
        dimensions of a form, asked from the device), only those reached from it."""
        members = self.data.members.get(demand["class"], {}).get(level, [])
        if demand["via_class"] is None:
            return list(members)
        key = ("via", demand["via_class"], level, str(demand["via_path"]))
        if key not in self._cache:
            starts = set(self.data.members.get(demand["via_class"], {}).get(level, []))
            self._cache[key] = self.data.step(demand["via_path"], starts) if demand["via_path"] is not None else starts
        reached = self._cache[key]
        return [m for m in members if m in reached]

    def applies(self, demand, entity) -> bool:
        if demand["each"] is not None and not self._at(demand["each"], entity):
            return False      # sh:node: no value, nothing to check
        for node, expected, prefix in demand["guards"]:
            nodes = self._at(prefix, entity)
            if not nodes:
                continue      # nothing there to check - the guard says nothing
            if isinstance(node, tuple):
                holds = any(self.data.has_class(n, node[1]) for n in nodes)
            else:
                holds = any(self.conforms(node, n) for n in nodes)
            if holds != expected:
                return False
        return True

    def met(self, demand, entity) -> bool:
        if demand["branches"]:
            for node, prefix in demand["branches"]:
                if any(self.conforms(node, n) for n in self._at(prefix, entity)):
                    return True
            return False
        if demand.get("prop_node") is not None:
            return any(self.property_conforms(demand["prop_node"], n) for n in self._at(demand["prefix"], entity))
        path = ("seq", [CHAIN, demand["path"]]) if demand["chain"] else demand["path"]
        values = self.data.step(path, {entity})
        if demand["kind"] == "ban":
            return not values
        if demand["end_classes"]:
            values = {v for v in values if all(self.data.has_class(v, c) for c in demand["end_classes"])}
        return len(values) >= max(demand["min"], 1)
