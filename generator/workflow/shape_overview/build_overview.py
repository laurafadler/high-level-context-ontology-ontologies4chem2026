"""
Builds an HTML overview of the context requirements from the SHACL shapes.

Usage:
    python build_overview.py ContextRequirementShapes.ttl HigherLevelOntology.rdf -o shape_overview.html

From the repository root:
    python generator/workflow/shape_overview/build_overview.py shapes/ContextRequirementShapes.ttl ontologies/HigherLevelOntology.rdf -o docs/shape_overview.html

All given files are loaded into one common graph. Needed are:
  - the shapes (paths, conditions, severity, messages)
  - rdfs:label, rdfs:comment and schema:description of the requirements (they stand in the ontology)

Context level, category and number are read from the requirement name,
e.g. "Molecule_Structure_Substance_R1" -> Molecule, [Structure, Substance], R1. The kind
(Existence, Surroundings, Assignment; rule 7.16) comes from the subclass of
hlo:ContextRequirement in the ontology; within context level and category it is sorted by it.

The script collects a simple dictionary per requirement and writes the list as JSON
into overview_template.html. The display itself happens entirely in the template (JavaScript).
"""

import argparse
import html
import json
import re
from datetime import date
from pathlib import Path

from rdflib import Graph, Namespace, URIRef, Literal, RDF, RDFS
from rdflib.collection import Collection

SH = Namespace("http://www.w3.org/ns/shacl#")
HLO = Namespace("http://www.semanticweb.org/lf576/ontologies/2026/7/HigherLevelOntology#")
QUDT = Namespace("http://qudt.org/schema/qudt/")
SCHEMA = Namespace("http://schema.org/")

TEMPLATE = Path(__file__).parent / "overview_template.html"

graph = Graph()  # filled in main()


# ---------------------------------------------------------------------------
# Small helper functions
# ---------------------------------------------------------------------------

def short(node):
    """IRI -> 'cpo:hasForm', Literal -> 'true'."""
    if isinstance(node, Literal):
        return str(node)
    try:
        return graph.namespace_manager.normalizeUri(node)
    except Exception:
        return str(node)


def local(node):
    """IRI -> 'hasForm' (without prefix)."""
    return short(node).split(":")[-1]


def value(node, predicate):
    return graph.value(node, predicate)


def values(node, predicate):
    return list(graph.objects(node, predicate))


def rdf_list(node):
    return list(Collection(graph, node))


def is_rdf_list(node):
    return node == RDF.nil or (node, RDF.first, None) in graph


def to_int(node):
    return int(node) if node is not None else None


# ---------------------------------------------------------------------------
# Paths
#
# A path is split into "rows". Every row is a list of steps:
#   {"props": ["cpo:contains"], "repeat": None, "node": None}
# "props" has several entries if one of several properties is allowed at this
# point. "node" is the node AFTER the step: None = empty box
# (not checked), otherwise {"name": ..., "extra": [...]}.
# Large alternatives (whole partial paths) become several rows.
# ---------------------------------------------------------------------------

def step(props, repeat=None):
    return {"props": props, "repeat": repeat, "node": None}


def expand_path(path):
    """SHACL path -> list of rows."""
    if isinstance(path, URIRef):
        return [[step([short(path)])]]

    if is_rdf_list(path):  # sequence
        rows = [[]]
        for part in rdf_list(path):
            rows = [row + part_row for row in rows for part_row in expand_path(part)]
        return rows

    alternatives = value(path, SH.alternativePath)
    if alternatives is not None:
        options = rdf_list(alternatives)
        if all(isinstance(o, URIRef) for o in options):
            return [[step([short(o) for o in options])]]  # stacked in one step
        return [row for o in options for row in expand_path(o)]  # rows of their own

    for predicate, label in [(SH.zeroOrMorePath, "0 or more ×"),
                             (SH.oneOrMorePath, "1 or more ×"),
                             (SH.zeroOrOnePath, "optional")]:
        inner = value(path, predicate)
        if inner is not None:
            # A repeated sequence, or a repeated choice between partial paths, is ONE step that is repeated as a
            # whole (the way back over the transfers: one transfer back or one level up) - spread over
            # several boxes it would read as if every property were repeated on its own.
            options = rdf_list(value(inner, SH.alternativePath)) if value(inner, SH.alternativePath) is not None else [inner]
            if is_rdf_list(inner) or not all(isinstance(o, URIRef) for o in options):
                return [[step([compact(o) for o in options], label)]]
            rows = expand_path(inner)
            for row in rows:
                for s in row:
                    s["repeat"] = label
            return rows

    inner = value(path, SH.inversePath)
    if inner is not None:
        return [[step([f"^{short(inner)}"])]]  # shown as "←" (followed backwards)

    return [[step(["?"])]]


def compact(path):
    """A partial path on one line, with prefixes and inverse steps, e.g. '^cpo:addsToPhase / cpo:removesFromPhase'."""
    if isinstance(path, URIRef):
        return short(path)
    if is_rdf_list(path):
        return " / ".join(compact(p) for p in rdf_list(path))
    if value(path, SH.alternativePath) is not None:
        return "(" + " | ".join(compact(p) for p in rdf_list(value(path, SH.alternativePath))) + ")"
    for predicate, sign in ((SH.zeroOrMorePath, "*"), (SH.oneOrMorePath, "+"), (SH.zeroOrOnePath, "?")):
        if value(path, predicate) is not None:
            return compact(value(path, predicate)) + sign
    if value(path, SH.inversePath) is not None:
        return "^" + compact(value(path, SH.inversePath))
    return "?"


def path_text(path):
    """Short text form of a path for labels, e.g. 'hasForm / (hasHeight | hasInnerHeight)'."""
    if isinstance(path, URIRef):
        return local(path)
    if is_rdf_list(path):
        return " / ".join(path_text(p) for p in rdf_list(path))
    alternatives = value(path, SH.alternativePath)
    if alternatives is not None:
        return "(" + " | ".join(path_text(p) for p in rdf_list(alternatives)) + ")"
    if value(path, SH.zeroOrMorePath) is not None:
        return path_text(value(path, SH.zeroOrMorePath)) + "*"
    if value(path, SH.oneOrMorePath) is not None:
        return path_text(value(path, SH.oneOrMorePath)) + "+"
    if value(path, SH.inversePath) is not None:
        return "^" + path_text(value(path, SH.inversePath))
    return "?"


def tag_path_text(path):
    """Like path_text, but without the leading 'specializationOf* /' (inheritance only, distracts)."""
    return path_text(path).removeprefix("specializationOf* / ")


def attach_end(rows, node, continuation=None):
    """Puts the end node at every row and appends a continuing path if there is one."""
    result = []
    for row in rows:
        row = [dict(s) for s in row]
        if row:
            row[-1]["node"] = node
        if continuation:
            for cont_row in continuation:
                result.append(row + cont_row)
        else:
            result.append(row)
    return result


# ---------------------------------------------------------------------------
# What is expected at the end of a path
# ---------------------------------------------------------------------------

def describe_node(shape):
    """
    Describes what a node must fulfil (sh:class, sh:in, QuantityKind, ...).
    Returns (node, continuation). continuation are further path rows,
    in case the shape itself still checks properties (e.g. MemberShape, Device_Time_R2).
    """
    names, extra, continuation = [], [], []

    classes = values(shape, SH["class"])
    if HLO.Actual in classes:
        extra.append("Actual")
        classes.remove(HLO.Actual)
    names += [local(c) for c in classes]

    for datatype in values(shape, SH.datatype):
        names.append(short(datatype))
    for fixed_value in values(shape, SH.hasValue):
        names.append(local(fixed_value) if isinstance(fixed_value, URIRef) else str(fixed_value))
    for in_list in values(shape, SH["in"]):
        names.append("one of " + ", ".join(local(x) for x in rdf_list(in_list)))
    for pattern in values(shape, SH.pattern):
        extra.append(f"pattern {pattern}")
    for negated in values(shape, SH["not"]):
        for c in values(negated, SH["class"]):
            extra.append(f"not {local(c)}")
        # sh:not [ sh:path p ; sh:maxCount 0 ]: the value has p (Phase_Information_R4: a lot) - written as a negation
        # so that the context links end at the value (rule 6.3), shown as what it asks for.
        negated_path = value(negated, SH.path)
        if negated_path is not None and to_int(value(negated, SH.maxCount)) == 0:
            extra.append(f"with {compact(negated_path)}")
        # sh:not [ sh:or ( classes and conditions ) ]: "none of these" (Phase_Time_R2: not a body, an environment
        # or the content of a chemical container) - otherwise the value would show as "any value".
        for or_list in values(negated, SH["or"]):
            alternatives = [local(values(b, SH["class"])[0]) if values(b, SH["class"]) and not values(b, SH.property)
                            else condition_text(b) for b in rdf_list(or_list)]
            extra.append("not (" + " or ".join(alternatives) + ")")

    # sh:or of plain classes -> "CuboidForm or CylindricalForm"
    # sh:or with conditions/demands (MemberShape) -> as above on requirement level
    for or_list in values(shape, SH["or"]):
        branches = rdf_list(or_list)
        if all(values(b, SH["class"]) and not values(b, SH.property) for b in branches):
            names.append(" or ".join(local(values(b, SH["class"])[0]) for b in branches))
        else:
            parts = split_or(branches)
            extra += [f"✕ {e['text']}" for e in parts["exemptions"]]
            extra += [f"only if {c['text']}" for c in parts["conditions"]]
            for demand in parts["demands"]:
                continuation += demand["rows"]

    for prop in values(shape, SH.property):
        path = value(prop, SH.path)
        if path == QUDT.hasQuantityKind:
            for v in values(prop, SH.hasValue):
                extra.append(f"QuantityKind {local(v)}")
            for in_list in values(prop, SH["in"]):
                extra.append("QuantityKind: " + ", ".join(local(x) for x in rdf_list(in_list)))
        else:
            continuation += demand_rows(prop)

    # Without a class or similar: take a short feature as the name ("not Fixed", "each value")
    if names:
        name = " & ".join(names)
    elif extra and extra[0].startswith(("not ", "each value")):
        name = extra.pop(0)
    else:
        name = "any value"
    return {"name": name, "extra": extra}, continuation


def demand_rows(prop):
    """Property shape -> path rows including the end node."""
    rows = expand_path(value(prop, SH.path))

    value_shape = value(prop, SH.qualifiedValueShape) or value(prop, SH.node)
    if value_shape is not None:
        node, continuation = describe_node(value_shape)
        if value(prop, SH.node) is not None:
            # sh:node checks every single value
            if node["name"] == "any value":
                node["name"] = "each value"
            else:
                node["extra"].insert(0, "each value")
    else:
        node, continuation = describe_node(prop)
    return attach_end(rows, node, continuation)


def amount_text(prop):
    minimum = to_int(value(prop, SH.minCount)) or to_int(value(prop, SH.qualifiedMinCount))
    maximum = to_int(value(prop, SH.maxCount))
    if value(prop, SH.node) is not None:
        return "every value is checked"
    if minimum and maximum == minimum:
        return f"exactly {minimum}"
    if minimum:
        return f"at least {minimum}"
    if maximum:
        return f"at most {maximum}"
    return "no minimum, collected only"


# ---------------------------------------------------------------------------
# Split sh:or into exceptions, conditions and demands
#
#   [ sh:class hlo:Fixed ]                         -> exception  "✕ Fixed library entries"
#   [ sh:property [ ... sh:hasValue true ] ]       -> exception  "✕ isCompositeDevice = true"
#   [ sh:not [ ... ] ]                             -> condition  "only if <condition>"
#   [ sh:property [ ... minCount ... ] ]           -> demand (path)
#   [ sh:and ( [sh:class X] [sh:property ...] ) ]  -> demand only for X
# ---------------------------------------------------------------------------

def condition_text(shape):
    """Short text for an exception or condition."""
    classes = values(shape, SH["class"])
    if classes and not values(shape, SH.property):
        return "Fixed library entries" if classes[0] == HLO.Fixed else local(classes[0])

    prop = value(shape, SH.property)
    path = tag_path_text(value(prop, SH.path))
    fixed_value = value(prop, SH.hasValue)
    if fixed_value is not None:
        return f"{path} = {local(fixed_value) if isinstance(fixed_value, URIRef) else fixed_value}"

    value_shape = value(prop, SH.qualifiedValueShape)
    if value_shape is not None:
        node, _ = describe_node(value_shape)
        count = to_int(value(prop, SH.qualifiedMinCount))
        return f"{path}: at least {count} {node['name']}" if count and count > 1 else f"{path}: {node['name']}"

    classes = values(prop, SH["class"])
    if classes:
        return f"{path}: {local(classes[0])}"
    return f"{path} exists"


def condition_rows(shape):
    """Path rows of a condition (for the expandable details), empty if there is no path."""
    prop = value(shape, SH.property)
    if prop is None:
        return []
    fixed_value = value(prop, SH.hasValue)
    if fixed_value is not None:
        return attach_end(expand_path(value(prop, SH.path)),
                          {"name": local(fixed_value) if isinstance(fixed_value, URIRef) else str(fixed_value), "extra": []})
    return demand_rows(prop)


def split_or(branches):
    parts = {"exemptions": [], "conditions": [], "demands": []}

    for branch in branches:
        and_list = value(branch, SH["and"])
        negated = value(branch, SH["not"])
        prop = value(branch, SH.property)
        node_shape = value(branch, SH.node)

        if node_shape is not None and prop is None and and_list is None and negated is None:
            # [ sh:node X_Demand ] (form shapes): the demands stand in the named node shape
            for p in values(node_shape, SH.property):
                parts["demands"].append({"scope": None, "rows": demand_rows(p), "amount": amount_text(p)})
        elif and_list is not None and any(
                value(p, SH.path) == HLO.specializationOf
                and any(HLO.Template in values(q, SH["class"]) for q in values(p, SH.qualifiedValueShape))
                for i in rdf_list(and_list) for p in values(i, SH.property)):
            # [ sh:and ( [ sh:class hlo:Fixed ] "specializes a hlo:Template" ) ]: an exclusion (rule 3.11,
            # helpers/context_links.py: is_exclusion) - the library exemplar takes over from its template
            parts["exemptions"].append({"text": "library exemplars of a template", "rows": []})
        elif and_list is not None:
            items = rdf_list(and_list)
            scope = [condition_text(i) for i in items if not values(i, SH.property)]
            for item in items:
                for p in values(item, SH.property):
                    parts["demands"].append({"scope": " & ".join(scope) or None,
                                             "rows": demand_rows(p), "amount": amount_text(p)})
        elif negated is not None:
            parts["conditions"].append({"text": condition_text(negated), "rows": condition_rows(negated)})
        elif prop is None:
            parts["exemptions"].append({"text": condition_text(branch), "rows": []})
        elif value(prop, SH.hasValue) is not None and value(prop, SH.minCount) is None:
            parts["exemptions"].append({"text": condition_text(branch), "rows": condition_rows(branch)})
        else:
            parts["demands"].append({"scope": None, "rows": demand_rows(prop), "amount": amount_text(prop)})

    return parts


# ---------------------------------------------------------------------------
# One requirement
# ---------------------------------------------------------------------------

def severity_of(shape):
    severity = value(shape, SH.severity)
    if severity is None:
        for prop in values(shape, SH.property):
            severity = severity or value(prop, SH.severity)
    return local(severity) if severity else "Violation"


def messages_of(shape):
    texts = [str(m) for m in values(shape, SH.message)]
    for prop in values(shape, SH.property):
        texts += [str(m) for m in values(prop, SH.message)]
    return texts


def target_of(shape):
    """What a shape targets: its sh:targetClass - also for a form shape, which starts at its context
    object (rule 7.11); its form class is only the scope of its block (form_scope_of)."""
    return local(value(shape, SH.targetClass))


def form_scope_of(shape):
    """The block title of a form shape (see hlo:targetFormClass): the form class it checks, e.g. "CupForm"."""
    form_class = value(shape, HLO.targetFormClass)
    return local(form_class) if form_class is not None else target_of(shape)


def build_requirement(requirement, shapes):
    name = local(requirement)
    parts = name.split("_")

    # The shape with sh:targetClass is the "main" shape; CoreShapes etc. hang at it
    mains = sorted((s for s in shapes if value(s, SH.targetClass) is not None or value(s, HLO.targetFormClass) is not None), key=local)
    main = mains[0]
    is_collection = local(main).endswith("ContextPathShape")

    # Several main shapes (the forms: one shape per form class, e.g. R2 for
    # solid cylinder, tube, cup, ...): per class a block "For <class>:" with its demands, the
    # collecting paths of all classes together.
    if len(mains) > 1 and not is_collection:
        demands, collected, exemptions = [], [], []
        for shape in mains:
            props = values(shape, SH.property)
            info = [p for p in props if value(p, SH.severity) == SH.Info]
            rows = [row for p in props if p not in info for row in demand_rows(p)]
            # Form shapes: the demands stand in the node shape in the second branch
            # of the sh:or, the first branch is the role condition. The phase form
            # shapes exclude Fixed phases (rule 7.7): the property for the forms stands in the sh:or after
            # [ sh:class hlo:Fixed ] - the property gives the rows, the branch without one the exemption.
            for or_list in values(shape, SH["or"]):
                for branch in rdf_list(or_list):
                    for node in values(branch, SH.node):
                        rows += [row for p in values(node, SH.property) for row in demand_rows(p)]
                    for p in values(branch, SH.property):
                        rows += demand_rows(p)
                    if not values(branch, SH.property) and not values(branch, SH.node):
                        text = condition_text(branch)
                        if text not in [e["text"] for e in exemptions]:
                            exemptions.append({"text": text, "rows": []})
            # Every row is one dimension or ratio the form class needs - all of them are required, not one of them
            demands.append({"scope": form_scope_of(shape), "rows": rows, "rowMode": "all", "amount": "at least 1 each"})
            collected += [demand_rows(p) for p in info]
        label = value(requirement, RDFS.label)
        comment = value(requirement, RDFS.comment)
        return {
            "id": name, "level": parts[0], "categories": parts[1:-1], "number": parts[-1],
            "title": str(label).split(" - ", 1)[-1] if label else name,
            "statement": str(comment) if comment else "",
            "description": description_parts(requirement),
            "target": " / ".join(sorted({target_of(s) for s in mains})),
            "severity": severity_of(main), "kind": "requirement",
            "exemptions": exemptions, "conditions": [], "demands": demands, "demandMode": "all",
            "collected": collected,
            "shapes": sorted(local(s) for s in shapes),
            "messages": [m for s in shapes for m in messages_of(s)],
        }

    # A collecting path along the actual chain (sh:Info, without minCount) stands next to the demand in
    # the same MainShape - it demands nothing and is therefore shown separately. In a
    # ContextPathShape, on the other hand, the info path is the requirement itself.
    properties = values(main, SH.property)
    collected = [] if is_collection else [p for p in properties if value(p, SH.severity) == SH.Info]
    demanded = [p for p in properties if p not in collected]

    or_list = value(main, SH["or"])
    if or_list is not None:
        split = split_or(rdf_list(or_list))
        demand_mode = "any"
    else:
        split = {"exemptions": [], "conditions": [], "demands": [
            {"scope": None, "rows": demand_rows(p), "amount": amount_text(p)}
            for p in demanded]}
        demand_mode = "all"

    label = value(requirement, RDFS.label)
    title = str(label).split(" - ", 1)[-1] if label else name
    comment = value(requirement, RDFS.comment)

    return {
        "id": name,
        "level": parts[0],
        "categories": parts[1:-1],
        "number": parts[-1],
        "title": title,
        "statement": str(comment) if comment else "",
        "description": description_parts(requirement),
        "target": target_of(main),
        "severity": severity_of(main),
        "kind": "collection" if is_collection else "requirement",
        "exemptions": split["exemptions"],
        "conditions": split["conditions"],
        "demands": split["demands"],
        "demandMode": demand_mode,
        "collected": [demand_rows(p) for p in collected],
        "shapes": sorted(local(s) for s in shapes),
        "messages": [m for s in shapes for m in messages_of(s)],
    }


# The parts every schema:description of a requirement is built from, in this order:
# "Question: ...? Applies to: ... Checks|Collects|Assigns: ... Reports: ... Not here: ..."
DESCRIPTION_LABELS = re.compile(r"(?:^|(?<=[.?]) )(Question|Applies to|Checks|Collects|Assigns|Reports|Not here): ")


def description_parts(requirement):
    """schema:description -> [[label, text], ...]; [] if the requirement has none."""
    description = value(requirement, SCHEMA.description)
    if description is None:
        return []
    pieces = DESCRIPTION_LABELS.split(str(description))
    parts = [["", pieces[0].strip()]] if pieces[0].strip() else []
    parts += [[label, text.strip()] for label, text in zip(pieces[1::2], pieces[2::2])]
    return parts


def number_key(req):
    """Sorting: R2 before R10."""
    return int(req["number"].lstrip("R") or 0)


# The three kinds of a requirement (rule 7.16), shown in this order per group.
KIND_ORDER = ["Existence", "Surroundings", "Assignment"]


def requirement_kind(requirement):
    """'Existence', 'Surroundings' or 'Assignment' - the subclass of hlo:ContextRequirement the requirement
    is typed with in the ontology; '' if it has none (check 12 of check_context_requirements_consistency.py)."""
    for cls in graph.objects(requirement, RDF.type):
        if (cls, RDFS.subClassOf, HLO.ContextRequirement) in graph:
            return local(cls).removesuffix("Requirement")
    return ""


def main():
    parser = argparse.ArgumentParser(description="Build the HTML overview of the context requirement shapes.")
    parser.add_argument("inputs", nargs="+", help="Shapes file and ontology files (Turtle or RDF/XML)")
    parser.add_argument("-o", "--output", default="shape_overview.html", help="Output HTML file")
    args = parser.parse_args()

    for path in args.inputs:
        graph.parse(path)

    # Group shapes by requirement
    shapes_by_requirement = {}
    for shape, requirement in graph.subject_objects(HLO.isShapeOfRequirement):
        shapes_by_requirement.setdefault(requirement, []).append(shape)

    requirements = []
    for requirement, shapes in shapes_by_requirement.items():
        entry = build_requirement(requirement, shapes)
        entry["requirementKind"] = requirement_kind(requirement)
        requirements.append(entry)

    # Within context level and category by kind (rule 7.16), then by number; without a kind at the end
    def kind_key(r):
        return KIND_ORDER.index(r["requirementKind"]) if r["requirementKind"] in KIND_ORDER else len(KIND_ORDER)
    requirements.sort(key=lambda r: (r["level"], r["categories"][0], kind_key(r), number_key(r)))

    data = json.dumps(requirements, indent=1, ensure_ascii=False).replace("</", "<\\/")
    sources = " and ".join(Path(p).name for p in args.inputs)
    stamp = html.escape(f"Generated from {sources} on {date.today():%d %B %Y}.")
    page = TEMPLATE.read_text(encoding="utf-8").replace("/*DATA*/[]", data).replace("<!--STAMP-->", stamp)
    Path(args.output).write_text(page, encoding="utf-8")
    print(f"{len(requirements)} requirements -> {args.output}")


if __name__ == "__main__":
    main()
