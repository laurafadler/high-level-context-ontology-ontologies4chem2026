"""
Writes the overview as Markdown: docs/property_overview/README.md (legend, index, gaps in numbers) and one file
per family of classes, with one table per class and its gaps below it.
"""
from collections import Counter, defaultdict

from common import LEVELS

STATUS_TEXT = {"required": "**req**", "recommended": "rec", "banned": "ban", "asked": "ask", "library": "*lib*",
               "derived": "*drv*", "": "–"}
GAP_TITLES = {
    "unsupplied": "Nothing supplies it",
    "short": "Short in the data",
    "unchecked_required": "Required field, no shape",
    "strictness": "Shape stricter than the field",
    "unused_field": "Field without data",
    "not_on_sheet": "Asked, not on the sheet",
    "unchecked": "Optional field, no shape",
}
GAP_DOCS = {
    "unsupplied": "a shape asks for it on this level, no entry field, sheet field, question or check gives it, and not every entity has it",
    "short": "a shape asks for it and something gives it, but not every entity has it",
    "unchecked_required": "an entry or sheet field requires it, but no shape and no check asks for it",
    "strictness": "a shape requires it (Violation), but the field that gives it is optional",
    "unused_field": "an entry or sheet field gives it, but no entity of the class has it on this level",
    "not_on_sheet": "the generator asks for it on the series or experiment level, but no field of the sheet gives it",
    "unchecked": "an optional entry or sheet field gives it, no shape and no check asks for it",
}
MAX_LIST = 3


def anchor(cls: str) -> str:
    return cls.replace(":", "").lower()


def short_label(label: str) -> str:
    for prefix, code in (("entry ", "E "), ("sheet ", "S "), ("question ", "G "), ("check ", "C ")):
        if label.startswith(prefix):
            return code + label[len(prefix):]
    return label


def listed(items, limit=MAX_LIST):
    items = list(dict.fromkeys(items))
    if len(items) <= limit:
        return ", ".join(items)
    return ", ".join(items[:limit]) + f" +{len(items) - limit}"


def cell_text(cell, own_class):
    parts = [STATUS_TEXT[cell["status"]]]
    shapes = []
    for demand in cell["shapes"]:
        text = demand["source"]
        if demand["conditions"] or demand["alternatives"]:
            text += "†"
        if demand["kind"] == "ban":
            text = "✕" + text
        shapes.append(text)
    if shapes:
        parts.append(("↑ " if cell["chain"] else "") + listed(shapes))
    fields = [short_label(s["label"]) + ("!" if s["need"] == "required" else "") for s in cell["entrys"] + cell["sheets"]]
    if fields:
        parts.append(listed(fields))
    questions = sorted({short_label(s["label"]) for s in cell["questions"]})
    if questions:
        parts.append(listed(questions, 2))
    checks = sorted({short_label(s["label"]) for s in cell["checks"]})
    if checks:
        parts.append(listed(checks, 1))
    if cell["total"] or (cell["shapes"] and cell.get("class_total")):
        parts.append(f"{cell['count']}/{cell['total']}")
    return " · ".join(parts).replace("|", "\\|")


def row_label(row):
    key = row["key"].replace("|", "\\|")
    return f"`{key}`"


def table_markdown(overview, cls):
    table = overview.tables[cls]
    totals = table["totals"]
    rows = overview.shown_rows(cls)
    lines = ["| Property | " + " | ".join(f"{level} ({totals[level]})" for level in LEVELS) + " |",
             "|---|" + "---|" * len(LEVELS)]
    for row in rows:
        lines.append(f"| {row_label(row)} | " + " | ".join(cell_text(row["cells"][level], cls) for level in LEVELS) + " |")
    return lines, rows


def notes_markdown(overview, cls, rows):
    """Conditions of the shapes named for this class, and the constraints on the values."""
    lines = []
    for row in rows:
        conditions = []
        for level in LEVELS:
            for demand in row["cells"][level]["shapes"]:
                if demand["class"] != cls:
                    continue
                text = []
                if demand["via"]:
                    text.append(demand["via"])
                if demand["alternatives"]:
                    text.append("one of: " + demand["alternatives"])
                text += demand["conditions"]
                if text:
                    conditions.append(f"{demand['source']} – " + "; ".join(text))
        conditions = list(dict.fromkeys(conditions))
        notes = row["notes"]
        if conditions or notes:
            lines.append(f"- {row_label(row)}: " + " · ".join(conditions + notes).replace("|", "\\|"))
    return lines


def gap_line(gap):
    row = f"`{gap['row']}`".replace("|", "\\|")
    level = gap["level"]
    if gap["type"] in ("unsupplied", "short"):
        text = f"{listed(gap['shapes'])} ask for {row} on the {level} level"
        if gap["type"] == "short":
            text += f", given by {listed([short_label(g) for g in gap['given']])}"
        else:
            text += ", nothing gives it"
        what = "keep to it" if gap["ban"] else "have it"
        text += f"; {gap['count']} of the {gap['total']} it applies to {what}"
        if gap["alternatives"]:
            text += " (or an alternative)"
        if gap["missing_in"]:
            text += " – missing in " + ", ".join(f"{name} {n}" for name, n in gap["missing_in"][:4])
            if len(gap["missing_in"]) > 4:
                text += f" +{len(gap['missing_in']) - 4} classes"
        return text
    if gap["type"] in ("unchecked_required", "unchecked"):
        return f"{listed([short_label(f) for f in gap['fields']])} give {row} ({level}), no shape or check asks for it"
    if gap["type"] == "strictness":
        return f"{listed(gap['shapes'])} require {row} ({level}), {listed([short_label(f) for f in gap['fields']])} leave it optional"
    if gap["type"] == "unused_field":
        return f"{listed([short_label(f) for f in gap['fields']])} give {row}, but none of the {gap['total']} on the {level} level has it"
    if gap["type"] == "not_on_sheet":
        return f"the generator asks {listed([short_label(q) for q in gap['questions']], 2)} for {row} ({level}); no sheet field gives it"
    return str(gap)


def gaps_markdown(gaps):
    lines = []
    by_type = defaultdict(list)
    for gap in gaps:
        by_type[gap["type"]].append(gap)
    for kind in GAP_TITLES:
        if kind not in by_type:
            continue
        if kind == "unchecked":
            rows = sorted({f"`{g['row']}`".replace("|", "\\|") for g in by_type[kind]})
            lines.append(f"- *{GAP_TITLES[kind]}*: " + ", ".join(rows))
            continue
        for gap in by_type[kind]:
            lines.append(f"- **{GAP_TITLES[kind]}**: {gap_line(gap)}")
    return lines


def class_section(overview, cls):
    table = overview.tables[cls]
    parent = overview.parent_in_overview(cls)
    lines = [f'<a id="{anchor(cls)}"></a>', f"### {cls}", ""]
    comment = overview.tree.labels.get(cls)
    if comment:
        lines += [f"> {comment.strip().splitlines()[0][:400]}", ""]
    facts = []
    if parent:
        facts.append(f"subclass of [{parent}](#{anchor(parent)}) – shows only its additions; the rows of "
                     f"{parent} hold here too")
    subs = overview.subclasses(cls)
    if subs:
        facts.append("subclasses: " + ", ".join(f"[{s}](#{anchor(s)})" for s in subs))
    if facts:
        lines += ["; ".join(facts) + ".", ""]
    table_lines, rows = table_markdown(overview, cls)
    if rows:
        lines += table_lines
    else:
        lines.append("No rows of its own.")
    notes = notes_markdown(overview, cls, rows)
    if notes:
        lines += ["", "Conditions and constraints:", ""] + notes
    gaps = overview.gaps[cls]
    if gaps:
        lines += ["", "Gaps:", ""] + gaps_markdown(gaps)
    lines.append("")
    return lines


def family_classes(overview, family_id):
    """The classes of a family in tree order: each class followed by its subclasses."""
    members = [c for c in overview.classes if overview.family_of[c] == family_id]
    ordered = []

    def visit(cls):
        ordered.append(cls)
        for sub in overview.subclasses(cls):
            if sub in members and sub not in ordered:
                visit(sub)
    for cls in members:
        parent = overview.parent_in_overview(cls)
        if parent is None or parent not in members:
            visit(cls)
    return ordered + [c for c in members if c not in ordered]


def family_markdown(overview, family):
    classes = family_classes(overview, family["id"])
    lines = [f"# {family['title']}", "", family.get("doc", ""), "",
             "Generated by `generator/workflow/property_overview/build_property_overview.py` – do not edit by hand. "
             "Legend and sources: [README](README.md).", "", "Classes: " +
             ", ".join(f"[{c}](#{anchor(c)})" for c in classes), ""]
    for cls in classes:
        lines += class_section(overview, cls)
    return "\n".join(lines)


def readme_markdown(overview, families, generated_from):
    data, sources = overview.data, overview.sources
    gap_counts = Counter(g["type"] for c in overview.classes for g in overview.gaps[c])
    lines = [
        "# Properties per class and level",
        "",
        "What every class has to have, should have or can have on each level – **Template, Fixed (library), Series, "
        "Experiment** – and where that is said: the shapes, the library entry schema, the setup sheet, the questions "
        "of the generator and the consistency check of the libraries; next to it how often the real data have it. "
        "Where the sources do not fit together, the class lists a gap.",
        "",
        "Generated on demand by `python generator/workflow/property_overview/build_property_overview.py` – for "
        "instance before writing, or after larger changes of the shapes, the schemas, the libraries or the crates; "
        "`--check` says whether these files are out of date. Do not edit by hand.",
        "",
        f"Built from: {generated_from}.",
        "",
        "## Legend",
        "",
        "A cell: `status · shapes · fields · questions · checks · count`.",
        "",
        "| Status | Meaning |",
        "|---|---|",
        "| **req** | required: a shape with severity Violation, a required entry or sheet field, or a check of the libraries asks for it |",
        "| rec | recommended: a shape with severity Warning asks for it |",
        "| ban | banned: a shape forbids it (`sh:maxCount 0`) |",
        "| ask | asked: the generator asks for it, or an optional field of the entry schema or the sheet gives it |",
        "| *lib* | read from the libraries (Template, Fixed): it stands in the library, but nothing above asks for it – written by an entry tool, by a generator run (usage history, `lastUsedTime`, content ends) or by a curation script; each entry names its source in its comment |",
        "| *drv* | derived (Series, Experiment): it is in the crate, but nothing above asks for it – the generator makes it |",
        "| – | nothing |",
        "",
        "| Mark | Meaning |",
        "|---|---|",
        "| `Device_Space_R2` | a context requirement (ContextRequirementShapes.ttl); other names are shapes of DataQualityShapes.ttl / FunctionShapes.ttl |",
        "| ↑ | met through the chain (`hlo:specializationOf`): it may stand one level higher (rule 3.6) – the count follows the chain |",
        "| † | the shape has conditions or alternatives – listed under the table |",
        "| ✕ | the shape forbids it |",
        "| `E type.field` | a field of the library entry schema (`entry_schema.yaml`); `!` = required |",
        "| `S module.field` | a field of the setup sheet (`sheet_schema.yaml`); `!` = required |",
        "| `G question_id` | a question of the generator, from the answer files of all projects |",
        "| `C …` | a check of `check_library_consistency.py` (assigned by hand, `overview_config.yaml`) |",
        "| `k/n` | k of the n entities of the class on this level have it (libraries and crates together) |",
        "",
        "Rows are properties – or the paths a shape asks for (`cpo:madeOfMaterial / dcterms:hasPart / cpo:hasTemperature`). "
        "A subclass shows only its additions: the rows a shape or source names for exactly this class and the "
        "properties only it has within its parent; the rows of the parent hold for it too, and its gaps are listed "
        "at the parent with the classes they lie in.",
        "",
        "Levels of the data: `hlo:Template`, `hlo:Fixed`, `hlo:SeriesSpecific`, `hlo:ExperimentSpecific` in the type, "
        "otherwise the ID ending; library entries without a level take that of what points at them; the series and the "
        "entities that describe the whole crate count as Series.",
        "",
        "## Families",
        "",
        "| Family | Classes | Gaps (without optional fields) |",
        "|---|---|---|",
    ]
    for family in families:
        classes = [c for c in overview.classes if overview.family_of[c] == family["id"]]
        if not classes:
            continue
        gaps = sum(1 for c in classes for g in overview.gaps[c] if g["type"] != "unchecked")
        lines.append(f"| [{family['title']}]({family['id']}.md) | " +
                     ", ".join(f"[{c}]({family['id']}.md#{anchor(c)})" for c in family_classes(overview, family["id"])) +
                     f" | {gaps} |")
    lines += ["", "## Gaps", "",
              "What the comparison of the sources shows (per class in the family files, under its table):", "",
              "| Gap | Meaning | Number |", "|---|---|---|"]
    for kind, title in GAP_TITLES.items():
        lines.append(f"| {title} | {GAP_DOCS[kind]} | {gap_counts.get(kind, 0)} |")
    lines += ["", "### Asked for by a shape, but nothing gives it", "",
              "The gaps of the kind *Nothing supplies it*, by family – a shape asks for something on a level, no "
              "person is asked for it and the generator does not always make it (k/n: of the entities the shape "
              "applies to; **bold**: severity Violation):", ""]
    for family in families:
        found = []
        for cls in family_classes(overview, family["id"]):
            for gap in overview.gaps[cls]:
                if gap["type"] == "unsupplied":
                    text = (f"[{cls}]({family['id']}.md#{anchor(cls)}) `{gap['row']}` ({gap['level']}, "
                            f"{gap['count']}/{gap['total']})").replace("|", "\\|")
                    found.append(f"**{text}**" if gap["severity"] == "Violation" else text)
        if found:
            lines.append(f"- **{family['title']}**: " + "; ".join(found))
    lines += ["", "## Not assigned", "",
              "What the script could not place – a field without `property:`, a question without an entry in "
              "`overview_config.yaml`:", ""]
    unmapped = {k: sorted(set(v)) for k, v in sources.unmapped.items() if v}
    if unmapped:
        for kind, items in sorted(unmapped.items()):
            lines.append(f"- {kind}: " + ", ".join(f"`{i}`" for i in items))
    else:
        lines.append("- nothing")
    others = [c for c in overview.classes if overview.family_of[c] == "other"]
    if others:
        lines.append("- classes outside the families: " + ", ".join(f"`{c}`" for c in others))
    if sources.unanswered_keys:
        lines += ["", "## Questions the setup sheet does not answer", "",
                  f"Keys of the answer files that none of the {sources.sheet_patterns} key patterns of the adapter "
                  "(`interfaces/eln/adapter.py`) matches - they are answered in the answer file or in the section "
                  "`open` of the sheet:", ""]
        for qid, keys in sorted(sources.unanswered_keys.items()):
            shown = sorted(keys)
            lines.append(f"- `{qid}`: " + ", ".join(f"`{k}`" for k in shown[:3]) + (f" +{len(shown) - 3}" if len(shown) > 3 else ""))
    lines += ["", "## Sources read", ""]
    lines.append(f"- Shapes: {len(overview.shapes.demands)} demands and constraints from ContextRequirementShapes.ttl, "
                 "DataQualityShapes.ttl, FunctionShapes.ttl, QuantityKindShapes.ttl")
    kinds = Counter(s["kind"] for s in sources.items)
    lines.append(f"- Library entry schema: {kinds['entry']} rows; setup sheet: {kinds['sheet']} rows "
                 f"(+ the quantity of a value); questions: {sources.question_keys} keys of the answer files → "
                 f"{kinds['question']} rows; checks: {kinds['check']}")
    lines.append(f"- Data: {len(data.entities)} entities from " + ", ".join(f"`{s}`" for s in data.sources))
    lines.append("")
    return "\n".join(lines)
