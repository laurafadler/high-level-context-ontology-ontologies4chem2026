"""
What the shapes demand, per class and property: every property shape with sh:minCount or
sh:qualifiedMinCount of at least 1 becomes a demand of the class it is checked at, with its severity
(Violation = required, Warning = recommended), the requirement it belongs to and the levels it leaves out.

Read from the four shape files (ContextRequirementShapes, DataQualityShapes, FunctionShapes,
QuantityKindShapes). How a shape is read:
  - sh:targetClass names the class; a property shape's path is the row - with a leading
    [ sh:zeroOrMorePath hlo:specializationOf ] taken off: such a demand is met through the chain, by a
    level higher up (rule 3.6), marked "via chain";
  - sh:or: a branch [ sh:class hlo:Fixed ] leaves out the Fixed level (and the template level, a template
    is hlo:Fixed too), [ sh:class hlo:Template ] the template level; a branch with sh:hasValue and no
    minimum is an exception ("unless ..."); [ sh:not ... ] is a condition ("only if ..."); [ sh:not
    [ sh:class X ] ] means the rest is about values of class X - the demands then belong to X, reached
    from the target class (this is how the form shapes ask for the dimensions of a form); several
    demanding branches are alternatives ("one of");
  - a branch or an sh:and with sh:class hlo:SeriesSpecific / hlo:ExperimentSpecific holds on that level only;
  - sh:node and sh:qualifiedValueShape with properties of their own continue the path;
  - sh:maxCount 0 is a ban; sh:in, sh:hasValue, sh:pattern, sh:datatype, sh:class without a minimum are
    constraints on the values (shown as notes, not as a status);
  - sh:Info (collecting paths, rule 3 of ContextRequirementShapes.ttl) and assignments
    (sh:qualifiedMinCount 0, rule 7) demand nothing and are left out;
  - sh:targetSubjectsOf P (formats, quantity kinds) is a note on the property P wherever it stands.
"""
from rdflib import Graph, URIRef
from rdflib.collection import Collection

from common import (SH, LEVELS, LEVEL_TYPES, curie, read_path, flatten, split_chain, path_text,
                    first_property, path_definitions)

HLO = "http://www.semanticweb.org/lf576/ontologies/2026/7/HigherLevelOntology#"

SHAPE_FILES = {
    "CR": path_definitions.CONTEXT_SHAPES,
    "DQ": path_definitions.DATA_QUALITY_SHAPES,
    "FN": path_definitions.FUNCTION_SHAPES,
    "QK": path_definitions.QUANTITY_KIND_SHAPES,
}


def class_levels(cls: str) -> set:
    """The levels a level class stands for: hlo:Fixed covers the templates too (hlo:Template is a
    subclass of hlo:Fixed)."""
    return {"hlo:Fixed": {"Template", "Fixed"}, "hlo:Template": {"Template"},
            "hlo:SeriesSpecific": {"Series"}, "hlo:ExperimentSpecific": {"Experiment"}}.get(cls, set())


def first_props(path) -> list:
    """The properties a path can start with: 'cpo:location', 'cpo:locatedAt', 'cpo:locatedInsideOf' for
    (cpo:location | cpo:locatedAt | cpo:locatedInsideOf) / ..."""
    if path[0] == "seq":
        return first_props(path[1][0])
    if path[0] == "alt":
        return [p for part in path[1] for p in first_props(part)]
    if path[0] == "p":
        return [path[1]]
    return []


def sh(name):
    return URIRef(SH + name)


class ShapeReader:
    def __init__(self):
        self.graph = Graph()
        self.file_of = {}
        for key, path in SHAPE_FILES.items():
            part = Graph()
            part.parse(str(path))
            for s in set(part.subjects()):
                self.file_of.setdefault(s, key)
            self.graph += part
        self.demands = []          # dicts, see _add
        self.property_notes = {}   # property -> [note]
        self.requirements = {}     # shape -> requirement id
        for shape, requirement in self.graph.subject_objects(URIRef(HLO + "isShapeOfRequirement")):
            self.requirements[shape] = curie(requirement).split(":")[-1]
        self._read()
        # The same order in every run (rdflib does not keep one).
        self.demands.sort(key=lambda d: (d["class"], d["row"], d["source"], d["kind"], d["severity"],
                                         sorted(d["levels"]), d["conditions"], d["alternatives"] or "",
                                         d["via"] or "", d["constraint"]))
        for notes in self.property_notes.values():
            notes.sort()

    # -- helpers -------------------------------------------------------------------------------

    def v(self, node, name):
        return self.graph.value(node, sh(name))

    def vs(self, node, name):
        return list(self.graph.objects(node, sh(name)))

    def items(self, node):
        return list(Collection(self.graph, node))

    def int_of(self, node, name):
        value = self.v(node, name)
        return int(value) if value is not None else None

    def severity(self, node, default):
        value = self.v(node, "severity")
        return curie(value).split(":")[-1] if value is not None else default

    def classes(self, node):
        return [curie(c) for c in self.vs(node, "class")]

    # -- reading -------------------------------------------------------------------------------

    def _read(self):
        for shape, target in sorted(self.graph.subject_objects(sh("targetClass")), key=lambda st: (str(st[0]), str(st[1]))):
            source = self.requirements.get(shape) or curie(shape).split(":")[-1]
            ctx = {"source": source, "file": self.file_of.get(shape, "?"),
                   "severity": self.severity(shape, "Violation"), "prefix": None, "via": None,
                   "excluded": set(), "only": None, "conditions": [], "alternatives": None,
                   "guards": [], "branches": None, "via_class": None, "via_path": None,
                   "each": None, "continuation": False,
                   "message": " ".join(str(m) for m in self.graph.objects(shape, sh("message")))}
            if ctx["file"] == "FN":
                self._function_constraint(shape, curie(target), ctx)
            else:
                self.walk_node(shape, curie(target), ctx)
        for shape, prop in sorted(self.graph.subject_objects(sh("targetSubjectsOf")), key=lambda sp: (str(sp[0]), str(sp[1]))):
            name = curie(shape).split(":")[-1]
            texts = []
            for p in sorted(self.vs(shape, "property"), key=str):
                texts.append(self.constraint_text(p) or path_text(read_path(self.graph, self.v(p, "path"))))
            if self.vs(shape, "or") or self.vs(shape, "not"):
                texts.append("conditions, see the shape")
            self.property_notes.setdefault(curie(prop), []).append(
                f"{self.file_of.get(shape, '?')} {name}" + (f": {'; '.join(t for t in texts if t)}" if any(texts) else ""))

    def _function_constraint(self, shape, focus, ctx):
        """FunctionShapes: a task without parts realizes only functions its class offers (rule 4.9) - a
        constraint on cpo:realizesFunction, not a demand."""
        allowed = [curie(x) for or_list in self.vs(shape, "or") for branch in self.items(or_list)
                   for in_list in self.vs(branch, "in") for x in self.items(in_list)]
        self._add(focus, ("p", "cpo:realizesFunction"), ctx, ctx["severity"], "constraint", 0, [],
                  "one of " + ", ".join(allowed) + " (unless the task has parts)", ctx["message"])

    def is_bare_class(self, node) -> bool:
        return bool(self.classes(node)) and not self.vs(node, "property") and not self.vs(node, "or") \
            and not self.vs(node, "node") and not self.vs(node, "not")

    def _function_constraint(self, shape, focus, ctx):
        """FunctionShapes: a task without parts realizes only functions its class offers (rule 4.9) - a
        constraint on cpo:realizesFunction, not a demand."""
        allowed = [curie(x) for or_list in self.vs(shape, "or") for branch in self.items(or_list)
                   for in_list in self.vs(branch, "in") for x in self.items(in_list)]
        self._add(focus, ("p", "cpo:realizesFunction"), ctx, ctx["severity"], "constraint", 0, [],
                  "one of " + ", ".join(allowed) + " (unless the task has parts)", ctx["message"])

    def is_bare_class(self, node) -> bool:
        return bool(self.classes(node)) and not self.vs(node, "property") and not self.vs(node, "or") \
            and not self.vs(node, "node") and not self.vs(node, "not")

    def walk_node(self, node, focus, ctx):
        ctx = dict(ctx, severity=self.severity(node, ctx["severity"]))
        for prop in self.vs(node, "property"):
            self.handle_property(prop, focus, ctx)
        # A node shape used as a property shape (FunctionShapes put [ sh:path ... ] into sh:or).
        if self.v(node, "path") is not None:
            self.handle_property(node, focus, ctx)
        for or_list in self.vs(node, "or"):
            self.handle_or(self.items(or_list), focus, ctx)
        for and_list in self.vs(node, "and"):
            items = self.items(and_list)
            # Bare classes in an sh:and say what the rest holds for: a level.
            for item in items:
                if self.is_bare_class(item):
                    levels = set().union(*(class_levels(c) for c in self.classes(item)))
                    if levels:
                        ctx = dict(ctx, only=(ctx["only"] or set(LEVELS)) & levels)
            for item in items:
                if not self.is_bare_class(item):
                    self.walk_node(item, focus, ctx)
        for inner in self.vs(node, "node"):
            self.walk_node(inner, focus, ctx)

    def full_path(self, ctx, path):
        prefix = ctx["prefix"]
        if prefix is None:
            return flatten(path)
        return flatten(("seq", [prefix, path]))

    def handle_property(self, prop, focus, ctx):
        path_node = self.v(prop, "path")
        if path_node is None:
            return
        severity = self.severity(prop, ctx["severity"])
        if severity == "Info":
            return
        own_path = read_path(self.graph, path_node)
        path = self.full_path(ctx, own_path)
        minimum = self.int_of(prop, "minCount") or self.int_of(prop, "qualifiedMinCount") or 0
        maximum = self.int_of(prop, "maxCount")
        qualified = self.v(prop, "qualifiedValueShape")
        end_classes = self.classes(prop) + (self.classes(qualified) if qualified is not None else [])
        message = " ".join(str(m) for m in self.graph.objects(prop, sh("message"))) or ctx["message"]
        constraint = self.constraint_text(prop) or (self.constraint_text(qualified) if qualified is not None else "")
        if minimum >= 1:
            self._add(focus, path, ctx, severity, "demand", minimum, end_classes, constraint, message, prop)
        elif maximum == 0:
            self._add(focus, path, ctx, severity, "ban", 0, [], "", message, prop)
        elif constraint and self.v(prop, "node") is None \
                and not (ctx["prefix"] is not None and own_path == ("p", "qudt:hasQuantityKind")):
            self._add(focus, path, ctx, severity, "constraint", 0, end_classes, constraint, message)
        # What the values must have themselves continues the path: sh:node holds for every value there is
        # (none: nothing to check), a qualified value shape is part of this demand (its gap is this one's).
        for inner in self.vs(prop, "node"):
            self.walk_node(inner, focus, dict(ctx, prefix=path, severity=severity, each=ctx["each"] or path))
        if qualified is not None and minimum >= 1:
            self.walk_node(qualified, focus, dict(ctx, prefix=path, severity=severity, continuation=True))

    def constraint_text(self, node):
        parts = []
        for in_list in self.vs(node, "in"):
            parts.append("one of " + ", ".join(curie(x) for x in self.items(in_list)))
        for value in self.vs(node, "hasValue"):
            parts.append(f"= {curie(value)}")
        for pattern in self.vs(node, "pattern"):
            parts.append(f"pattern {pattern}")
        for datatype in self.vs(node, "datatype"):
            parts.append(curie(datatype))
        for inner in self.vs(node, "property"):
            if curie(self.v(inner, "path") or "") == "qudt:hasQuantityKind":
                parts += ["quantity kind " + t for t in [self.constraint_text(inner)] if t]
        return "; ".join(sorted(parts))

    def condition_text(self, node):
        """Short text of a condition shape: 'cpo:isCompositeDevice = true', 'cpo:hasServiceHistory exists'.
        A dict {"prop": p} stands for a property shape used directly as a branch."""
        if isinstance(node, dict):
            props, classes, ors, nots = [node["prop"]], [], [], []
        else:
            props, classes = self.vs(node, "property"), self.classes(node)
            ors, nots = self.vs(node, "or"), self.vs(node, "not")
        texts = []
        if classes:
            texts.append(" or ".join(classes))
        for prop in props:
            chain, rest = split_chain(read_path(self.graph, self.v(prop, "path")))
            text = path_text(rest) or "hlo:specializationOf*"
            value = self.v(prop, "hasValue")
            qualified = self.v(prop, "qualifiedValueShape")
            if value is not None:
                texts.append(f"{text} = {curie(value)}")
            elif self.int_of(prop, "maxCount") == 0:
                texts.append(f"no {text}")
            elif qualified is not None:
                texts.append(f"{text} reaches {self.condition_text(qualified) or 'something'}")
            elif self.classes(prop):
                texts.append(f"{text}: {' or '.join(self.classes(prop))}")
            else:
                texts.append(f"{text} exists")
        for or_list in ors:
            texts.append("(" + " or ".join(self.condition_text(b) for b in self.items(or_list)) + ")")
        for inner in nots:
            texts.append("not " + self.condition_text(inner))
        return " and ".join(sorted(texts))

    def is_demand_prop(self, prop) -> bool:
        """A property shape that asks for something - not a test of what the focus is (a flag with
        sh:hasValue, a link to a template, a negation)."""
        if self.v(prop, "hasValue") is not None:
            return False
        if not ((self.int_of(prop, "minCount") or 0) >= 1 or (self.int_of(prop, "qualifiedMinCount") or 0) >= 1
                or self.int_of(prop, "maxCount") == 0):
            return False
        qualified = self.v(prop, "qualifiedValueShape")
        if qualified is not None and self.vs(qualified, "not") and not self.classes(qualified):
            return False
        return True

    def is_test_prop(self, prop) -> bool:
        """A property shape in an sh:and that only tests what the focus is: a flag, a link to a template."""
        qualified = self.v(prop, "qualifiedValueShape")
        return self.v(prop, "hasValue") is not None or not self.is_demand_prop(prop) or (
            qualified is not None and any(c in LEVEL_TYPES for c in self.classes(qualified)))

    def is_demand_item(self, node) -> bool:
        if self.v(node, "path") is not None:
            return self.is_demand_prop(node)
        if any(self.is_demand_prop(p) for p in self.vs(node, "property")):
            return True
        if self.vs(node, "node"):
            return True
        for or_list in self.vs(node, "or"):
            if any(self.is_demand_item(b) for b in self.items(or_list)):
                return True
        for and_list in self.vs(node, "and"):
            if any(self.is_demand_item(i) for i in self.items(and_list)):
                return True
        return False

    def handle_or(self, branches, focus, ctx):
        excluded, conditions, demanding = set(ctx["excluded"]), list(ctx["conditions"]), []
        refocus, only = None, ctx["only"]
        guards, prefix = list(ctx["guards"]), ctx["prefix"]
        for branch in branches:
            classes = self.classes(branch)
            props = self.vs(branch, "property")
            negated = self.vs(branch, "not")
            and_lists = self.vs(branch, "and")
            if self.v(branch, "path") is not None:
                if self.is_demand_prop(branch):
                    demanding.append(branch)
                else:
                    conditions.append("unless " + self.condition_text({"prop": branch}))
                    guards.append((branch, False, prefix))
            elif and_lists:
                items = [i for a in and_lists for i in self.items(a)]
                if any(self.is_demand_item(i) and not all(self.is_test_prop(p) for p in self.vs(i, "property") +
                                                           ([i] if self.v(i, "path") is not None else []))
                       or self.vs(i, "node") or self.vs(i, "or") for i in items):
                    demanding.append(branch)
                else:
                    scope = [self.condition_text(i) for i in items]
                    if "hlo:Fixed" in scope and any("hlo:Template" in s for s in scope):
                        conditions.append("Fixed: not for an exemplar of a template (it takes this over from the template)")
                    else:
                        conditions.append("unless " + " and ".join(scope))
                    guards.append((branch, False, prefix))
            elif self.is_bare_class(branch):
                for c in classes:
                    if class_levels(c):
                        excluded |= class_levels(c)
                    else:
                        conditions.append(f"not for {c}")
                        guards.append((branch, False, prefix))
            elif negated and not props and not classes:
                for inner in negated:
                    if self.is_bare_class(inner):
                        levels = set().union(*(class_levels(c) for c in self.classes(inner)))
                        if levels:
                            only = (only or set(LEVELS)) & levels
                        else:
                            refocus = self.classes(inner)[0]
                    else:
                        conditions.append("only if " + self.condition_text(inner))
                        guards.append((inner, True, prefix))
            elif self.vs(branch, "node") or any(self.is_demand_prop(p) for p in props) or self.vs(branch, "or"):
                demanding.append(branch)
            elif props:
                conditions.append("unless " + self.condition_text(branch))
                guards.append((branch, False, prefix))
        group = " | ".join(self._branch_text(b) for b in demanding) if len(demanding) > 1 else None
        branches = [(b, prefix) for b in demanding] if len(demanding) > 1 else ctx["branches"]
        for branch in demanding:
            branch_ctx = dict(ctx, excluded=excluded, conditions=conditions, only=only,
                              alternatives=group or ctx["alternatives"], guards=guards, branches=branches)
            target = focus
            if refocus is not None:
                via = path_text(ctx["prefix"]) if ctx["prefix"] is not None else None
                branch_ctx.update(prefix=None, via=f"from {focus}" + (f" via {via}" if via else ""),
                                  via_class=focus, via_path=ctx["prefix"])
                # From here on the shapes are evaluated at the value (the form): guards and branches
                # recorded so far stand at the class it was reached from and are left to the path.
                own = guards[len(ctx["guards"]):]
                branch_ctx.update(guards=[(n, e, None) for n, e, _ in own],
                                  branches=[(b, None) for b in demanding] if len(demanding) > 1 else None)
                target = refocus
            classes = self.classes(branch)
            levels = set().union(*(class_levels(c) for c in classes)) if classes else set()
            if levels:
                branch_ctx["only"] = (only or set(LEVELS)) & levels
            elif classes and refocus is None:
                target = classes[0]
                branch_ctx["via"] = branch_ctx["via"] or f"for {classes[0]} only"
                branch_ctx["guards"] = branch_ctx["guards"] + [(("class", focus), True, prefix)]
            if self.v(branch, "path") is not None:
                self.handle_property(branch, target, branch_ctx)
            else:
                self.walk_node(branch, target, branch_ctx)

    def _branch_text(self, branch):
        def texts_of(node):
            found = []
            props = self.vs(node, "property") + ([node] if self.v(node, "path") is not None else [])
            for p in props:
                if self.is_demand_prop(p):
                    rest = split_chain(read_path(self.graph, self.v(p, "path")))[1]
                    found.append(path_text(rest) if rest is not None else "hlo:specializationOf*")
            for a in self.vs(node, "and"):
                for item in self.items(a):
                    found += texts_of(item)
            for n in self.vs(node, "node"):
                found += texts_of(n)
            return found
        return " & ".join(dict.fromkeys(texts_of(branch))) or "?"

    def _add(self, focus, path, ctx, severity, kind, minimum, end_classes, constraint, message, prop=None):
        chain, rest = split_chain(path)
        if rest is None:
            return
        if rest == ("p", "rdf:type"):
            rest = ("p", "@type")     # the data say it with @type
        if rest[0] == "plus" and rest[1][0] == "p":
            rest = rest[1]            # one or more steps: for being there the same as one
        levels = set(ctx["only"]) if ctx["only"] else set(LEVELS)
        levels -= ctx["excluded"]
        self.demands.append({
            "class": focus,
            "row": path_text(rest) if rest[0] != "seq" else path_text(rest),
            "first": first_property(rest),
            "path": rest,
            "chain": chain,
            "severity": severity,
            "kind": kind,
            "min": minimum,
            "end_classes": [c for c in end_classes if c not in ("hlo:Actual",)] if kind == "demand" else [],
            "levels": levels,
            "conditions": list(dict.fromkeys(ctx["conditions"])),
            "alternatives": ctx["alternatives"],
            "via": ctx["via"],
            "source": ctx["source"],
            "file": ctx["file"],
            "guards": list(ctx["guards"]),
            "branches": ctx["branches"],
            "via_class": ctx["via_class"],
            "via_path": ctx["via_path"],
            "prefix": ctx["prefix"],
            "prop_node": prop,
            "first_props": first_props(rest),
            "each": ctx["each"],
            "continuation": ctx["continuation"],
            "constraint": constraint,
            "message": message,
        })


if __name__ == "__main__":
    reader = ShapeReader()
    for d in sorted(reader.demands, key=lambda d: (d["class"], d["row"])):
        print(d["class"], "|", d["row"], "|", d["kind"], d["severity"], d["source"], sorted(d["levels"]),
              "chain" if d["chain"] else "", d["via"] or "", d["conditions"], d["alternatives"] or "", d["constraint"])
    print(len(reader.demands), "demands")
    for p, notes in sorted(reader.property_notes.items()):
        print("NOTE", p, notes)
