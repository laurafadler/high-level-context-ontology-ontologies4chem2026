"""
Catalogue of the answer-file keys: which questions the generator can ask, which it actually
asked for a crate, and what kind of answer each one takes.

Two sources, combined:

1. The code. Every ask_user()/ask_user_list() call site, read with ast: its question_id, file,
   line, function, whether it offers options, its answer type and whether an answer is
   required. This lists questions a given crate never reaches, too.
2. An answer file. After a run it holds every key that was asked, with the question text
   (and its level tag [hlo:...]) as a comment line and the answer. Each key is turned into a
   pattern: a segment "level:<name>" becomes "level:<name>", "experiment:2" becomes
   "experiment:<n>", so all phases, materials, experiments ... asking the same question fall
   into one row.

Nothing here runs the generator or changes anything; it only reads code and answer file.

Output (default in reports/):
    key_catalog_patterns.csv   one row per key pattern: count, answer kind, how the answers
                               split (empty / No / Yes / other), an example, the call site(s),
                               a category
    key_catalog_call_sites.csv one row per call site, with how often it was asked
    key_catalog_summary.md     the numbers per category and answer kind, for reading

Usage:
    python generator/workflow/key_catalog.py [--answers projects/<crate_identifier>/answers.txt] [--out reports]
"""
import argparse
import ast
import csv
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ANSWERS = ROOT / "projects" / "hydrogenation_rdy_2026_09" / "answers.txt"
# Relative to generator/.
GENERATOR = ROOT / "generator"
SCANNED = ["main.py", "workflow/library_prerun/fill_reaction_library.py", "creation", "helpers", "get_additional_information"]
ASK_FUNCTIONS = {"ask_user", "ask_user_list"}

FORMAT_HEADER = "# answer-file-format: keyed-v2"
COMMENT_PREFIX = "    // "
EMPTY_ANSWER_MARKER = "<empty>"

# Which questions ask for what. Maintained by hand; a new question_id lands in "other" and
# shows in the summary.
CATEGORIES = {
    "setup": {
        "series_short_name", "number_of_conducted_experiments",
        "number_of_planned_experiments", "series_completed", "series_description",
    },
    "library selection": {
        "devices", "reactions", "series_creator", "series_experimenter", "performers", "equipment",
        "software", "identifier_field", "identifier_value", "species_quick_pick",
        "bound_to_quick_pick", "occupied_by_quick_pick",
    },
    "same in all experiments?": {
        "same_creator_for_all_experiments", "same_experimenter_for_all_experiments",
        "same_operation_mode_across_experiments", "same_parts_in_all_experiments",
    },
    "setup of the apparatus": {
        "contained_material_type", "material_type", "gaseous_phase_names", "liquid_phase_names",
        "solid_phase_names", "species_names", "phases", "interfaces", "transfers", "transfer_types",
        "transfer_type", "adds_to_phase", "removes_from_phase", "transferred_species",
        "flows_from_port", "flows_to_port", "location_kind", "location_interface",
        "dispersion_state", "occupation_state", "occupation_state_names", "is_free_site",
        "has_bound_to", "sorption_type", "solid_structure", "parts", "form_class",
        "energy_field_types", "measured_ambient_fields", "cross_material_pairs",
        "additional_material_names", "sample_materials", "is_sample_of", "opens_into_phase",
        "transfer_places", "target_interface", "device_side_phase", "phase", "operation_mode",
        "occurs_in_series", "number_of_occurrences", "status_source", "feature_of_interest",
    },
    "which quantities have a value?": {
        "quantities_with_reference", "quantities_with_evidence", "quantities_known_per_experiment",
        "covered_by_existing",
    },
    "values": {
        "evidence_exists", "evidence_type", "evidence_value_type", "evidence_variable_kind",
        "evidence_scalar_value", "evidence_scalar_unit", "evidence_exactness", "evidence_timestamp",
        "evidence_duration_value", "evidence_duration_unit", "evidence_series_column",
        "have_another_evidence", "reference_exists", "reference_type", "reference_value_type",
        "reference_variable_kind", "reference_scalar_value", "reference_scalar_unit", "reference_timestamp",
        "reference_exactness", "reference_source", "have_another_reference", "input_values", "which_profile",
        # Profiles as the value of an evidence or reference.
        *(f"{role}_profile_{field}" for role in ("evidence", "reference") for field in (
            "unit", "quantity_kind", "step_kind", "step_duration", "start_value_value", "end_value_value",
            "hold_value_value", "change_rate_value", "add_another_step")),
    },
    "tasks": {
        "name", "description", "task_type", "functions", "aims_at", "acts_on", "observed", "performed_by_scope",
        "executes_profile", "extra_task_names", "grouping_tasks", "which_task", "time_sources",
        "time_source_specification", "add_another",
    },
    "files": {"reference_column_header", "generated_media_objects", "generated_by_task"},
}
CATEGORY_OF = {qid: cat for cat, qids in CATEGORIES.items() for qid in qids}


# ---------------------------------------------------------------------------
# 1. Call sites in the code
# ---------------------------------------------------------------------------

def _render(node, source: str) -> str:
    """Source text of an argument; f-strings keep their {placeholders}."""
    return ast.get_source_segment(source, node) or ""


def _question_id_pattern(node, source: str) -> str:
    """The question_id as a pattern: a constant as it is, an f-string with '*' for every
    placeholder, anything else (a variable) as '<expr>'."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value if isinstance(v, ast.Constant) else "*" for v in node.values)
    return f"<{_render(node, source)}>"


def _wrappers(trees) -> dict:
    """Functions that take a question_id and hand it on (ask_people, ask_name, ...):
    name -> (position of the question_id parameter or None, its default or None).
    ask_user itself is one of them."""
    wrappers = {}
    for tree in trees:
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            positional = node.args.posonlyargs + node.args.args
            names = [a.arg for a in positional]
            if "question_id" in names:
                index = names.index("question_id")
                offset = len(positional) - len(node.args.defaults)
                default = node.args.defaults[index - offset] if index >= offset else None
                wrappers[node.name] = (index, default)
            else:
                kwonly = [a.arg for a in node.args.kwonlyargs]
                if "question_id" in kwonly:
                    wrappers[node.name] = (None, node.args.kw_defaults[kwonly.index("question_id")])
    return wrappers


def scan_call_sites() -> list:
    sites = []
    files = []
    for entry in SCANNED:
        path = GENERATOR / entry
        files += [path] if path.is_file() else sorted(path.rglob("*.py"))
    parsed = [(path, path.read_text(encoding="utf-8")) for path in files]
    parsed = [(path, source, ast.parse(source)) for path, source in parsed]
    wrappers = _wrappers(tree for _, _, tree in parsed)
    for path, source, tree in parsed:
        parents = {}
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                parents[child] = parent
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", None)
            if name not in wrappers:
                continue
            kwargs = {k.arg: k.value for k in node.keywords if k.arg}
            position, default = wrappers[name]
            if "question_id" not in kwargs and position is not None and len(node.args) > position:
                kwargs["question_id"] = node.args[position]
            if "question_id" not in kwargs and default is not None:
                kwargs["question_id"] = default   # the helper asks with its default
            if "question_id" not in kwargs:
                continue   # a call without an ID of its own
            if isinstance(kwargs["question_id"], ast.Name):
                continue   # only hands on the ID of its caller - counted at the caller
            function = parents.get(node)
            while function is not None and not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                function = parents.get(function)
            has_options = (len(node.args) > 1 and not (isinstance(node.args[1], ast.Constant) and node.args[1].value is None)) \
                or ("options" in kwargs and not (isinstance(kwargs["options"], ast.Constant) and kwargs["options"].value is None))
            answer_type = _render(kwargs["answer_type"], source) if "answer_type" in kwargs else (
                _render(node.args[2], source) if len(node.args) > 2 else "")
            if name not in ASK_FUNCTIONS:
                kind = f"via {name}"
            elif name == "ask_user_list":
                kind = "list from options"
            elif has_options:
                kind = "one of options"
            elif answer_type in ("int", "float"):
                kind = f"number ({answer_type})"
            elif answer_type:
                kind = f"text, parsed by {answer_type}"
            else:
                kind = "free text"
            sites.append({
                "question_id": _question_id_pattern(kwargs["question_id"], source),
                "file": path.relative_to(ROOT).as_posix(),
                "line": node.lineno,
                "function": function.name if function is not None else "<module>",
                "call": name,
                "answer_kind_in_code": kind,
                "required": _render(kwargs["required"], source) if "required" in kwargs else "False",
                "prompt": " ".join(_render(node.args[0], source).split())[:160] if node.args else "",
            })
    return sites


def site_matches(site_qid: str, qid: str) -> bool:
    if site_qid.startswith("<"):
        return False
    return re.fullmatch(re.escape(site_qid).replace(r"\*", ".*"), qid) is not None


def sites_for(qid: str, sites: list) -> list:
    """The call sites that ask this question_id: the ones naming it exactly, otherwise the
    f-string patterns that fit it best (longest fixed text - "*_variable_kind" before "*_kind")."""
    exact = [s for s in sites if s["question_id"] == qid]
    if exact:
        return exact
    fitting = [s for s in sites if site_matches(s["question_id"], qid)]
    if not fitting:
        return []
    best = max(len(s["question_id"].replace("*", "")) for s in fitting)
    return [s for s in fitting if len(s["question_id"].replace("*", "")) == best]


# ---------------------------------------------------------------------------
# 2. Answer file
# ---------------------------------------------------------------------------

def read_answer_file(path: Path) -> list:
    """Entries of a keyed-v2 answer file in file order: {key, comments, answer}."""
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != FORMAT_HEADER:
        raise SystemExit(f"{path} is not a keyed-v2 answer file (first line must be {FORMAT_HEADER!r}).")
    entries, current = [], None
    for line in lines[1:]:
        if line.startswith("key:"):
            current = {"key": line[len("key:"):].strip(), "comments": [], "answer": None}
            entries.append(current)
        elif current is None or not line.strip():
            if current is not None and current["answer"] is not None:
                current = None
        elif line.startswith(COMMENT_PREFIX) and current["answer"] is None:
            current["comments"].append(line[len(COMMENT_PREFIX):])
        elif current["answer"] is None:
            answer = line[1:] if line.startswith(" ") else line   # escape rule of user_io
            current["answer"] = "" if answer == EMPTY_ANSWER_MARKER else answer
    return entries


def key_pattern(key: str) -> str:
    """series:1/experiment:2/material:Material_In_Vessel/volume/have_reference
       -> series:1/experiment:<n>/material:<name>/volume/have_reference"""
    parts = key.split("/")
    out = []
    for segment in parts[:-1]:
        level, sep, value = segment.partition(":")
        if not sep or level == "series":
            out.append(segment)
        else:
            out.append(f"{level}:<n>" if value.isdigit() else f"{level}:<name>")
    return "/".join(out + parts[-1:])


LEVEL_TAG = re.compile(r"^\[(hlo:\w+)\]\s*")
OPTIONS = re.compile(r"\[([^\[\]]*)\](?:\s*\(([^()]*)\))?\s*$")


def answer_kind_from_text(question: str) -> str:
    match = OPTIONS.search(question)
    if not match:
        return "open"
    hint = match.group(2) or ""
    return "list from options" if "several" in hint or "separated" in hint else "one of options"


def answer_class(answer: str) -> str:
    text = (answer or "").strip()
    if not text:
        return "empty"
    if text.lower() == "no":
        return "No"
    if text.lower() == "yes":
        return "Yes"
    return "other"


# ---------------------------------------------------------------------------
# Merging and writing
# ---------------------------------------------------------------------------

def build(answer_path: Path, out_dir: Path):
    sites = scan_call_sites()
    entries = read_answer_file(answer_path)

    rows = {}
    for entry in entries:
        pattern = key_pattern(entry["key"])
        qid = entry["key"].rsplit("/", 1)[-1]
        question = entry["comments"][0] if entry["comments"] else ""
        tag = LEVEL_TAG.match(question)
        row = rows.setdefault(pattern, {
            "pattern": pattern, "question_id": qid, "category": CATEGORY_OF.get(qid, "other"),
            "level": tag.group(1) if tag else "", "answer_kind": answer_kind_from_text(question),
            "count": 0, "empty": 0, "No": 0, "Yes": 0, "other": 0,
            "example_key": entry["key"], "example_question": LEVEL_TAG.sub("", question),
            "example_answer": None,
        })
        row["count"] += 1
        cls = answer_class(entry["answer"])
        row[cls] += 1
        if row["example_answer"] is None and cls == "other":
            row["example_answer"], row["example_key"] = entry["answer"], entry["key"]
    for row in rows.values():
        if row["example_answer"] is None:
            row["example_answer"] = ""
        # Exact question_id before f-string patterns: "*_name" would otherwise also hit "series_short_name".
        matching = sites_for(row["question_id"], sites)
        row["call_sites"] = "; ".join(f"{s['file']}:{s['line']}" for s in matching)
        if row["answer_kind"] == "open" and matching:
            kinds = {s["answer_kind_in_code"] for s in matching}
            row["answer_kind"] = kinds.pop() if len(kinds) == 1 else "open"

    asked = Counter(e["key"].rsplit("/", 1)[-1] for e in entries)
    for site in sites:
        site["asked_in_answer_file"] = sum(n for qid, n in asked.items() if site in sites_for(qid, sites))

    out_dir.mkdir(parents=True, exist_ok=True)
    pattern_rows = sorted(rows.values(), key=lambda r: (r["category"], -r["count"], r["pattern"]))
    fields = ["category", "pattern", "question_id", "level", "answer_kind", "count", "empty", "No", "Yes",
              "other", "example_key", "example_question", "example_answer", "call_sites"]
    with open(out_dir / "key_catalog_patterns.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows({k: r[k] for k in fields} for r in pattern_rows)
    site_fields = ["question_id", "asked_in_answer_file", "answer_kind_in_code", "required", "call", "file",
                   "line", "function", "prompt"]
    with open(out_dir / "key_catalog_call_sites.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=site_fields)
        writer.writeheader()
        writer.writerows({k: s[k] for k in site_fields} for s in sorted(sites, key=lambda s: (s["file"], s["line"])))

    write_summary(out_dir / "key_catalog_summary.md", answer_path, entries, pattern_rows, sites)
    return entries, pattern_rows, sites


def write_summary(path: Path, answer_path: Path, entries, pattern_rows, sites):
    total = len(entries)
    by_class = Counter(answer_class(e["answer"]) for e in entries)
    by_cat = defaultdict(Counter)
    for r in pattern_rows:
        for k in ("count", "empty", "No", "Yes", "other"):
            by_cat[r["category"]][k] += r[k]
        by_cat[r["category"]]["patterns"] += 1
    by_kind = Counter()
    for r in pattern_rows:
        by_kind[r["answer_kind"]] += r["count"]
    unasked = [s for s in sites if not s["asked_in_answer_file"]]
    unmatched = [r for r in pattern_rows if not r["call_sites"]]

    def pct(n):
        return f"{100 * n / total:.0f} %" if total else "-"

    lines = [
        "# Key catalogue – summary",
        "",
        f"Answer file: `{answer_path.relative_to(ROOT).as_posix()}`. Written by `generator/workflow/key_catalog.py`; "
        "details in `key_catalog_patterns.csv` and `key_catalog_call_sites.csv`.",
        "",
        f"- **{total} keys** in the answer file, falling into **{len(pattern_rows)} key patterns** "
        f"(the same question at different places of the experiment).",
        f"- **{len(sites)} call sites** in the code ask a question; "
        f"{len(sites) - len(unasked)} of them were asked for this crate, {len(unasked)} were not.",
        "",
        "## Answers",
        "",
        "| Answer | Keys | Share |",
        "|---|---:|---:|",
    ] + [f"| {c} | {by_class[c]} | {pct(by_class[c])} |" for c in ("empty", "No", "Yes", "other")] + [
        "",
        "## By category",
        "",
        "| Category | Patterns | Keys | empty | No | Yes | other |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ] + [
        f"| {cat} | {c['patterns']} | {c['count']} | {c['empty']} | {c['No']} | {c['Yes']} | {c['other']} |"
        for cat, c in sorted(by_cat.items(), key=lambda kv: -kv[1]["count"])
    ] + [
        "",
        "## By answer kind",
        "",
        "| Answer kind | Keys |",
        "|---|---:|",
    ] + [f"| {k} | {n} |" for k, n in by_kind.most_common()] + [
        "",
        "## Checks",
        "",
        f"- Patterns without a matching call site: {len(unmatched)}"
        + ("" if not unmatched else " – " + ", ".join(f"`{r['question_id']}`" for r in unmatched)),
        f"- Patterns in category \"other\" (not yet sorted in CATEGORIES): "
        + (", ".join(f"`{r['question_id']}`" for r in pattern_rows if r["category"] == "other") or "none"),
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--answers", type=Path, default=DEFAULT_ANSWERS)
    parser.add_argument("--out", type=Path, default=ROOT / "projects" / "hydrogenation_rdy_2026_09" / "reports")
    args = parser.parse_args()
    entries, pattern_rows, sites = build(args.answers.resolve(), args.out.resolve())
    print(f"{len(entries)} keys, {len(pattern_rows)} patterns, {len(sites)} call sites -> {args.out}")


if __name__ == "__main__":
    main()
