"""
Cross-check of the setup adapter (interfaces/eln/adapter.py): does a change to it give different answers?

The adapter of an earlier commit and the adapter as it is now are both asked every question of the
answer files of the projects - the questions with their options are read from the answer files
themselves - and the answers and sources are compared. A difference is either intended (the change
was meant to answer that question differently) or a regression - for instance series input values a
change leaves unanswered.

The earlier state (generator, libraries, ontologies) is taken out of git into a temporary folder; each
side runs in its own process, since both import the same module names.

Usage (from the repository root):
    python generator/workflow/adapter_crosscheck.py <commit> [<crate_identifier> ...]
Without projects: every project with a setup sheet. Exit code 1 if anything differs.

Note: both adapters read the sheets as they are now - an earlier adapter stops on a field or `none`
category it does not know yet (a sheet already using what the change brought). The check is meant for a
change to the adapter with the sheets unchanged. Questions only one generator asks are not compared.
"""
import argparse
import json
import re
import subprocess
import sys
import tarfile
import tempfile
from io import BytesIO
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent


def ask_all(generator: Path, base: Path, sheet: Path, answers: Path) -> dict:
    """Inner mode: ask the adapter of `generator` every question of `answers`; {key: [answer, source]}."""
    sys.path.insert(0, str(generator))
    from interfaces.eln.adapter import SetupAdapter
    adapter = SetupAdapter(sheet, base)
    lines = answers.read_text(encoding="utf-8").splitlines()
    result, i = {}, 0
    while i < len(lines):
        if not lines[i].startswith("key:"):
            i += 1
            continue
        key, prompt = lines[i][4:].strip(), ""
        i += 1
        while i < len(lines) and lines[i].startswith("    // "):
            if not lines[i].startswith("    // source:"):
                prompt = lines[i][7:]
            i += 1
        found = re.search(r"\[([^\[\]]*)\](?:\s*\([^()]*\))?\s*$", re.sub(r"^\[hlo:\w+\]\s*", "", prompt))
        options = [o.strip() for o in found.group(1).split(",")] if found else None
        try:
            answer = adapter(key=key, prompt=prompt, options=options, answer_type=str, required=False, stored=None)
        except Exception as error:  # noqa: BLE001 - every exception is a finding
            answer = ("ERROR", repr(error))
        result[key] = list(answer) if answer else None
    return result


def _side(generator: Path, base: Path, sheet: Path, answers: Path) -> dict:
    out = subprocess.run([sys.executable, __file__, "--ask", str(generator), str(base), str(sheet), str(answers)],
                         capture_output=True, text=True, encoding="utf-8", cwd=base,
                         env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
    if out.returncode != 0:
        raise SystemExit(f"adapter of {generator} failed:\n{out.stderr[-2000:]}")
    return json.loads(out.stdout.splitlines()[-1])


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--ask":
        print(json.dumps(ask_all(*(Path(a) for a in sys.argv[2:6])), ensure_ascii=False))
        return 0
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("commit", help="the earlier state, e.g. HEAD~3 or a commit hash")
    parser.add_argument("projects", nargs="*", help="identifiers (projects/<crate_identifier>/); default: all with a setup sheet")
    args = parser.parse_args()
    projects = args.projects or sorted(p.parent.name for p in (BASE / "projects").glob("*/setup.yaml"))
    differences = 0
    with tempfile.TemporaryDirectory(prefix="adapter_crosscheck_") as tmp:
        old = Path(tmp)
        archive = subprocess.run(["git", "archive", args.commit, "generator", "libraries", "ontologies"],
                                 cwd=BASE, capture_output=True, check=True).stdout
        tarfile.open(fileobj=BytesIO(archive)).extractall(old, filter="data")
        for project in projects:
            folder = BASE / "projects" / project
            sheet, answers = folder / "setup.yaml", folder / "answers.txt"
            if not (sheet.exists() and answers.exists()):
                print(f"{project}: no setup sheet or answer file - skipped")
                continue
            before = _side(old / "generator", BASE, sheet, answers)
            after = _side(BASE / "generator", BASE, sheet, answers)
            changed = [k for k in before if before[k] != after.get(k)]
            differences += len(changed)
            print(f"{project}: {len(before)} questions, {len(changed)} with a different answer or source")
            for key in changed[:20]:
                print(f"    {key}\n      before: {before[key]}\n      now:    {after.get(key)}")
            if len(changed) > 20:
                print(f"    ... and {len(changed) - 20} more")
    return 1 if differences else 0


if __name__ == "__main__":
    sys.exit(main())
