"""
Builds the overview "properties per class and level": for every class, what
it has to have, should have or can have on each level - Template, Fixed (library), Series, Experiment - according
to the shapes, the library entry schema, the setup sheet, the questions of the generator and the consistency
check of the libraries, next to how often the real data have it; and where these sources do not fit together.

Output (docs/property_overview/):
    README.md          legend, index of the families, the gaps in numbers, what could not be assigned
    <family>.md        one table per class (rows: properties, columns: levels) and its gaps
    ../property_overview.html   the same data as one page with filters (written by render_html.py)

Usage (from the repository root):
    python generator/workflow/property_overview/build_property_overview.py           write the files
    python generator/workflow/property_overview/build_property_overview.py --check   only say whether they are up to date

Reads only; run on demand (no rule to run it after every change). What the sources
do not say themselves (families, which class an entry type or sheet module describes, which property a question
asks for, what the checks of check_library_consistency.py ask for) stands in overview_config.yaml.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import ROOT, ClassTree  # noqa: E402
from data import Data  # noqa: E402
from shapes import ShapeReader  # noqa: E402
from sources import Sources, load_config  # noqa: E402
from model import Overview  # noqa: E402
from render_markdown import family_markdown, readme_markdown  # noqa: E402
from render_html import overview_html  # noqa: E402

OUT = ROOT / "docs" / "property_overview"
HTML = ROOT / "docs" / "property_overview.html"


def build() -> dict:
    """{path: text} of every file of the overview."""
    config = load_config()
    tree = ClassTree()
    data = Data(tree)
    shapes = ShapeReader()
    sources = Sources(config, tree)
    overview = Overview(tree, data, shapes, sources, config)
    families = list(config["families"])
    if any(overview.family_of[c] == "other" for c in overview.classes):
        families.append({"id": "other", "title": "Other classes", "doc": "Classes no family of overview_config.yaml reaches.", "classes": []})
    crates = sum(1 for s in data.sources if s.startswith("projects/"))
    generated_from = f"the libraries and the {crates} crates of the working tree, the four shape files, both schemas and the answer files of all projects"
    files = {OUT / "README.md": readme_markdown(overview, families, generated_from)}
    for family in families:
        if any(overview.family_of[c] == family["id"] for c in overview.classes):
            files[OUT / f"{family['id']}.md"] = family_markdown(overview, family)
    files[HTML] = overview_html(overview, families, generated_from)
    return files


def main():
    parser = argparse.ArgumentParser(description="Build the overview of the properties per class and level.")
    parser.add_argument("--check", action="store_true", help="only report whether the files are up to date")
    args = parser.parse_args()
    files = build()
    stale = [p for p, text in files.items() if not p.exists() or p.read_text(encoding="utf-8") != text]
    extra = [p for p in OUT.glob("*.md") if p not in files] if OUT.exists() else []
    if args.check:
        if stale or extra:
            for p in stale:
                print(f"out of date: {p.relative_to(ROOT).as_posix()}")
            for p in extra:
                print(f"no longer generated: {p.relative_to(ROOT).as_posix()}")
            sys.exit(1)
        print("property overview up to date")
        return
    OUT.mkdir(parents=True, exist_ok=True)
    for p in extra:
        p.unlink()
    for p, text in files.items():
        p.write_text(text, encoding="utf-8", newline="\n")
    print(f"{len(files)} files -> {OUT.relative_to(ROOT).as_posix()}/ and {HTML.relative_to(ROOT).as_posix()}"
          + (f" ({len(stale)} changed)" if stale else " (unchanged)"))


if __name__ == "__main__":
    main()
