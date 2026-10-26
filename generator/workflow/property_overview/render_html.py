"""
The overview as one HTML page (docs/property_overview.html): the same tables and gaps as the Markdown files,
with filters by family, level, status and gaps, and a search. The data stand as JSON in the page; the display
is done by the script of overview_template.html.
"""
import json
from pathlib import Path

from common import LEVELS
from render_markdown import GAP_TITLES, GAP_DOCS, family_classes, gap_line, short_label

TEMPLATE = Path(__file__).resolve().parent / "overview_template.html"


def _cell(cell):
    return {
        "s": cell["status"],
        "sh": [{"id": d["source"], "c": bool(d["conditions"] or d["alternatives"]), "b": d["kind"] == "ban"}
               for d in cell["shapes"]],
        "ch": cell["chain"],
        "f": [[short_label(s["label"]), s["need"] == "required"] for s in cell["entrys"] + cell["sheets"]],
        "q": sorted({short_label(s["label"]) for s in cell["questions"]}),
        "k": sorted({short_label(s["label"]) for s in cell["checks"]}),
        "n": cell["count"],
        "t": cell["total"],
        "show": bool(cell["total"] or (cell["shapes"] and cell.get("class_total"))),
    }


def _conditions(row, cls):
    found = []
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
                found.append(f"{demand['source']} – " + "; ".join(text))
    return list(dict.fromkeys(found + row["notes"]))


def page_data(overview, families, generated_from):
    classes = []
    for family in families:
        for cls in family_classes(overview, family["id"]):
            table = overview.tables[cls]
            comment = overview.tree.labels.get(cls) or ""
            classes.append({
                "id": cls,
                "family": family["id"],
                "parent": overview.parent_in_overview(cls),
                "subs": overview.subclasses(cls),
                "totals": table["totals"],
                "comment": comment.strip().splitlines()[0][:400] if comment.strip() else "",
                "rows": [{"key": r["key"], "cells": {level: _cell(r["cells"][level]) for level in LEVELS},
                          "notes": _conditions(r, cls)} for r in overview.shown_rows(cls)],
                "gaps": [{"type": g["type"], "level": g["level"], "row": g["row"], "text": gap_line(g)}
                         for g in overview.gaps[cls]],
            })
    return {
        "levels": LEVELS,
        "families": [{"id": f["id"], "title": f["title"], "doc": f.get("doc", "")} for f in families
                     if any(c["family"] == f["id"] for c in classes)],
        "gapTypes": [{"id": k, "title": v, "doc": GAP_DOCS[k]} for k, v in GAP_TITLES.items()],
        "classes": classes,
        "generatedFrom": generated_from,
    }


def overview_body(overview, families, generated_from):
    """The page without <html>/<head>/<body>: the template with the data filled in (also what an artifact
    publishes - it brings its own skeleton)."""
    data = json.dumps(page_data(overview, families, generated_from), ensure_ascii=False, separators=(",", ":"))
    return TEMPLATE.read_text(encoding="utf-8").replace("/*DATA*/null", data.replace("</", "<\\/"))


def overview_html(overview, families, generated_from):
    return ("<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">\n"
            + overview_body(overview, families, generated_from) + "\n</html>\n")
