"""
Coverage report of a crate: where its answers come from, by topic.

Reads the answer file of a project (projects/<crate_identifier>/answers.txt) - every answer carries a source
line "// source: <code>: <text>" (rule 2.10) - and writes projects/<crate_identifier>/reports/coverage.md:

- answers by source: from the ELN (E structured, X extracted from free text), a fixed translation
  rule (R), looked up (L), a "none" default (an answer that only says "nothing else is known" because
  the sheet says so for a whole category - counted on its own, otherwise the ELN looks better than
  it is), by hand (C curated, D other answers invented for the demonstration), missing (M), and
  answers without a source line (older than rule 2.10 - typed in by hand);
- the same by topic: series and people, materials and substances, values, tasks, devices, files,
  reactions, room, derived things (interfaces, transfers, occurrences, ports).

An empty answer says less than a value, so every count also gives how many have content.

No crate is built for this: an ELN record alone does not even give a crate its frame (devices,
room, the vessels the materials are in, the time of the experiment); a run with only its answers
fills the gaps with stand-ins and builds things that are not there.

Usage (from the repository root):
    python generator/workflow/coverage_report.py [projects/<crate_identifier> ...]
Without arguments: every project with an answer file. With several projects the overview is
printed side by side.
"""
import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "generator"))
sys.path.insert(0, str(ROOT / "generator" / "workflow"))

from key_catalog import read_answer_file  # noqa: E402
from sheet_coverage import DERIVED  # noqa: E402

# The columns of the report: source -> heading, in this order.
SOURCES = {
    "eln": "ELN",
    "rule": "rule",
    "lookup": "looked up",
    "none": "'none' default",
    "hand": "by hand",
    "missing": "missing",
    "unmarked": "no source line",
}
SOURCE_DOC = {
    "eln": "from the ELN record: structured (E) or extracted from its free text (X)",
    "rule": "a fixed translation rule, mostly turning an ELN entry into the crate's terms (R)",
    "lookup": "looked up in a database (L)",
    "none": "only 'nothing else is known' - a default the sheet sets for a whole category, no knowledge",
    "hand": "curated (C) or invented for the demonstration (D) by a person",
    "missing": "nobody knew it (M)",
    "unmarked": "no source line - answers older than rule 2.10, typed in by hand",
}
TOPICS = ("series and people", "materials and substances", "values", "tasks", "devices", "files",
          "reactions", "room", "derived", "other")
_VALUE_QUESTION = re.compile(r"quantities_(with_(evidence|reference)|known_per_experiment)|(evidence|reference)_[a-z_]+"
                             r"|have_another_(evidence|reference)")
_LEVEL_TOPIC = {
    "material": "materials and substances", "phase": "materials and substances", "species": "materials and substances",
    "task": "tasks", "device": "devices", "profile_step": "devices",
    "media_object": "files", "reaction": "reactions", "participant": "reactions", "elementary_reaction": "reactions",
    "placeholder": "reactions", "environment": "room",
}


def source_of(entry: dict) -> tuple:
    """(source class, the source text) of an answer file entry."""
    line = next((c[len("source: "):] for c in entry["comments"] if c.startswith("source: ")), None)
    if line is None:
        return "unmarked", ""
    code = line.split(":", 1)[0].strip()
    if "(none: " in line:
        return "none", line
    return {"E": "eln", "X": "eln", "R": "rule", "L": "lookup", "C": "hand", "D": "hand", "M": "missing"}.get(code, "unmarked"), line


def topic_of(key: str) -> str:
    """The topic of a question, from its key."""
    segments = key.split("/")
    levels = [s.split(":")[0] for s in segments[:-1] if ":" in s]
    plain = {s for s in segments[:-1] if ":" not in s}
    if (set(levels) | plain) & DERIVED:
        return "derived"
    if _VALUE_QUESTION.fullmatch(segments[-1]) and "task" not in levels[-1:]:
        return "values"
    levels = [level for level in levels if level not in ("series", "experiment")]
    if "environment" in levels:
        # The room air and its phase belong to the room, not to the materials of the setup.
        return "room"
    if not levels:
        return "series and people" if key.startswith(("setup/", "series:1/series_", "series:1/same_")) or "/" not in key \
            else _series_topic(segments[-1])
    return _LEVEL_TOPIC.get(levels[-1], "other")


def _series_topic(question: str) -> str:
    # Questions about the series itself: which devices, materials, tasks, reactions there are.
    for word, topic in (("device", "devices"), ("material", "materials and substances"), ("task", "tasks"),
                        ("reaction", "reactions"), ("sample", "materials and substances")):
        if word in question:
            return topic
    return "series and people"


def has_content(answer) -> bool:
    return bool((answer or "").strip()) and answer.strip().lower() != "no"


def count(answer_path: Path) -> dict:
    """{(topic, source): [answers, with content]} plus the totals under topic None."""
    counts = defaultdict(lambda: [0, 0])
    for entry in read_answer_file(answer_path):
        source, _text = source_of(entry)
        for topic in (topic_of(entry["key"]), None):
            counts[(topic, source)][0] += 1
            counts[(topic, source)][1] += has_content(entry["answer"])
    return counts


def _cell(counts, topic, source) -> str:
    n, filled = counts.get((topic, source), (0, 0))
    return f"{n} ({filled})" if n else "-"


def render(project: Path, counts: dict) -> str:
    total = sum(n for (topic, _s), (n, _f) in counts.items() if topic is None)
    used = [s for s in SOURCES if counts.get((None, s))]
    lines = [f"# Coverage - {project.name}", "",
             f"Where the {total} answers of `{(project / 'answers.txt').relative_to(ROOT).as_posix()}` come from "
             "(source line of each answer, rule 2.10). In brackets: how many of them have content - an empty "
             "answer or a plain \"No\" says less than a value. Written by `generator/workflow/coverage_report.py`.", "",
             "## By source", "", "| Source | Answers | Share | With content |", "|---|---:|---:|---:|"]
    for source in used:
        n, filled = counts[(None, source)]
        lines.append(f"| {SOURCES[source]} | {n} | {n / total:.0%} | {filled} |")
    lines += ["", "## By topic", "", "| Topic | " + " | ".join(SOURCES[s] for s in used) + " | All |",
              "|---|" + "---:|" * (len(used) + 1)]
    for topic in TOPICS:
        row = [_cell(counts, topic, s) for s in used]
        n = sum(counts.get((topic, s), (0, 0))[0] for s in used)
        if n:
            lines.append(f"| {topic} | " + " | ".join(row) + f" | {n} |")
    lines += ["", "## Sources", ""] + [f"- **{SOURCES[s]}**: {SOURCE_DOC[s]}" for s in used]
    lines += ["", "Topics follow the key of the question: a question about values (\"for which quantities ...\", "
              "a field of a value) counts as *values* wherever the value sits; *derived* are the things the "
              "generator works out itself (interfaces, transfers, occurrences, ports).", ""]
    return "\n".join(lines)


def overview(results: list) -> str:
    """The projects side by side: share of answers per source."""
    sources = [s for s in SOURCES if any(c.get((None, s)) for _p, c in results)]
    lines = ["| Project | " + " | ".join(SOURCES[s] for s in sources) + " | All |",
             "|---|" + "---:|" * (len(sources) + 1)]
    for project, counts in results:
        total = sum(counts.get((None, s), (0, 0))[0] for s in SOURCES)
        cells = [f"{counts.get((None, s), (0, 0))[0] / total:.0%}" if counts.get((None, s)) else "-" for s in sources]
        lines.append(f"| {project.name} | " + " | ".join(cells) + f" | {total} |")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("projects", nargs="*", type=Path)
    args = parser.parse_args()
    projects = [p.resolve() for p in args.projects] or sorted(p.parent for p in (ROOT / "projects").glob("*/answers.txt"))
    results = []
    for project in projects:
        answers = project / "answers.txt"
        if not answers.exists():
            sys.exit(f"{project}: no answers.txt")
        counts = count(answers)
        report = project / "reports" / "coverage.md"
        report.parent.mkdir(exist_ok=True)
        report.write_text(render(project, counts), encoding="utf-8")
        print(f"written: {report.relative_to(ROOT).as_posix()}")
        results.append((project, counts))
    print()
    print(overview(results))


if __name__ == "__main__":
    main()
