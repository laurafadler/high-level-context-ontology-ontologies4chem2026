"""
Which questions of a crate a setup sheet can answer.

The adapter (interfaces/eln/adapter.py) is the mapping: its table of key patterns is exactly what a
sheet answers. For every key pattern of an answer file this tool looks for the adapter pattern that
matches it - no second, hand-kept table that could drift apart. A pattern no adapter pattern
matches is either derived by the generator (interfaces, transfers, occurrences) or a
gap of the sheet format. A pattern answered only by "none" (the sheet can deny it, not give it)
is counted on its own - and as a gap where the answer file holds content there (the sheet could
not have said it).

Usage (from the repository root):
    python generator/workflow/sheet_coverage.py projects/<crate_identifier>/answers.txt [--sheet projects/<x>/setup.yaml] [--out report.md]
--sheet: any valid setup sheet - it is only needed to build the adapter (default: the amidation's).
"""
import argparse
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "generator"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from key_catalog import read_answer_file, key_pattern  # noqa: E402
from interfaces.eln.adapter import SetupAdapter  # noqa: E402

DEFAULT_SHEET = ROOT / "projects" / "amidation_ai4green_ai4_001" / "setup.yaml"

# What the generator derives from the setup - no thing of its own in the sheet.
DERIVED = {"phase_interface", "phase_pair_interface", "cross_material_interface", "transfer", "transferred",
           "transfer_follow_up", "port_crossing", "occurrences", "interface", "place", "participant_transfer",
           "occupation_state", "type"}
# Answers that can only say "none" (the sheet denies, but supplies no content).
NONE_ONLY = ("_none_list", "_gate", "_no_other_value", "_no_profile")


def _thing(pattern: str) -> str:
    levels = [segment.split(":")[0] for segment in pattern.split("/")[:-1] if ":" in segment]
    levels = [level for level in levels if level not in ("series", "experiment")]
    return levels[-1] if levels else "(series)"


def _derived(pattern: str) -> bool:
    levels = {segment.split(":")[0] for segment in pattern.split("/")[:-1]}
    return bool(levels & DERIVED)


def _class_of_key(key: str, answer: str, adapter) -> tuple:
    """(class, handler name) of one key - the adapter pattern that answers it at run time."""
    handler = next((h for regex, h in adapter._handlers if regex.fullmatch(key)), None)
    name = getattr(handler, "__qualname__", "").replace("SetupAdapter.", "") if handler else ""
    content = bool((answer or "").strip()) and answer.strip().lower() != "no"
    # Exact name: "_gate" is also contained in "_gate_series_values", which supplies values.
    if handler and name.split(".")[0] not in NONE_ONLY:
        return "sheet", name
    if handler:
        return ("content missing" if content else "none only"), name
    return ("derived" if _derived(key_pattern(key)) else "gap"), ""


def classify(answer_path: Path, sheet_path: Path) -> list:
    """One row per (key pattern, class): a pattern can fall into several classes - a list of
    values is answered from the ELN at one phase and denied at another."""
    adapter = SetupAdapter(sheet_path, ROOT)
    rows = {}
    for entry in read_answer_file(answer_path):
        pattern = key_pattern(entry["key"])
        cls, handler = _class_of_key(entry["key"], entry["answer"], adapter)
        row = rows.setdefault((pattern, cls), {"pattern": pattern, "class": cls, "handler": handler, "keys": 0,
                                               "with_content": 0, "thing": _thing(pattern),
                                               "question": (entry["comments"] or [""])[0]})
        row["keys"] += 1
        row["with_content"] += bool((entry["answer"] or "").strip()) and entry["answer"].strip().lower() != "no"
    return list(rows.values())


def render(rows: list, answer_path: Path) -> str:
    classes = ("sheet", "none only", "content missing", "derived", "gap")
    lines = [f"# Sheet coverage - {answer_path.as_posix()}", "",
             "| Class | Patterns | Keys |", "|---|---:|---:|"]
    for cls in classes:
        hit = [r for r in rows if r["class"] == cls]
        lines.append(f"| {cls} | {len(hit)} | {sum(r['keys'] for r in hit)} |")
    lines += ["", "## By thing", "", "| Thing | " + " | ".join(classes) + " |", "|---|" + "---:|" * len(classes)]
    by_thing = defaultdict(lambda: defaultdict(int))
    for r in rows:
        by_thing[r["thing"]][r["class"]] += r["keys"]
    for thing, counts in sorted(by_thing.items(), key=lambda x: -sum(x[1].values())):
        lines.append(f"| {thing} | " + " | ".join(str(counts.get(c, 0)) for c in classes) + " |")
    lines += ["", "## Gaps - asked by the generator, no field in the sheet yet", ""]
    for r in sorted((r for r in rows if r["class"] == "gap"), key=lambda r: (r["thing"], r["pattern"])):
        lines.append(f"- `{r['pattern']}` ({r['keys']}) - {r['question'][:140]}")
    lines += ["", "## Content missing - the sheet can only deny it, but the answer file says something", ""]
    for r in sorted((r for r in rows if r["class"] == "content missing"), key=lambda r: (r["thing"], r["pattern"])):
        lines.append(f"- `{r['pattern']}` ({r['with_content']} of {r['keys']}) - {r['question'][:140]}")
    lines += ["", "## None only - the sheet can deny it, not give it", ""]
    for r in sorted((r for r in rows if r["class"] == "none only"), key=lambda r: (r["thing"], r["pattern"])):
        lines.append(f"- `{r['pattern']}` ({r['keys']})")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("answers", type=Path)
    parser.add_argument("--sheet", type=Path, default=DEFAULT_SHEET)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    text = render(classify(args.answers, args.sheet), args.answers)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"written to {args.out}")
    else:
        print(text)


if __name__ == "__main__":
    main()
