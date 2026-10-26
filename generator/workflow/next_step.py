"""
The next step of a series, in one command (the way through the sheet as simple as possible). After the sheet has its fields (devices, materials, tasks ...), call it again and again:

    python generator/workflow/next_step.py projects/<crate_identifier>

Each call
1. checks the sheet (check_sheet.py) - a missing field or a name that points at nothing stops here, with
   the list; questions written by an earlier call and not yet answered do not stop it, they are counted;
2. builds the crate in a throwaway copy (isolated_run.py, an exploratory run: unknown questions get a
   stand-in, nothing in the project changes) from the sheet alone - the stored answers are left out
   (answer_driver.py --from-sheet), since one of them would hide a change of the sheet; a completed
   series is opened again in the copy first;
3. when the run stops on something that is not a question (a start time, a time of a device's use ...),
   shows the reason and where in the sheet it is settled;
4. otherwise writes the questions nobody answered into the sheet (open_questions.py --write-sheet: empty
   values under 'values', other questions under 'open') and says how many;
5. says what comes next: answer and call again - or, when nothing new is open, declare the rest unknown
   (close_sheet.py) and build the crate for real from the sheet, as it was explored, with the exact commands.

Only the sheet is written (step 4, appended); the scripts it calls stay as they are. Libraries must be
committed for the real run (rule 2.4); this command warns when they are not.

Usage (from the repository root):
    python generator/workflow/next_step.py projects/<crate_identifier> [--keep]

--keep keeps the throwaway copy (its run log, crate and answer file) and prints where it is.
"""
import argparse
import json
import re
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "generator"))

from interfaces.eln.check_sheet import SheetCheck  # noqa: E402
from workflow.open_questions import _place, _thing, write_sheet  # noqa: E402

# Sections whose empty entries are questions still to be answered (not: a broken sheet).
QUESTION_SECTIONS = ("open", "values", "occurrences")

# Stops that are no question: how to recognize them and where they are settled in the sheet.
HINTS = [
    (r"Experimental procedure needs a value for start_time",
     "The start of each experiment is required (rule 5.6). In the sheet: a task 'Experimental procedure' with\n"
     "    times: {1: {start: \"...\", kind: assumed}, 2: {...}}. Its other times (end, duration) then come into\n"
     "    the sheet as empty values; close_sheet.py declares unknown what stays empty."),
    (r"usage history of (\S+) holds (\S+), but neither its end nor its start has a value",
     "Every use of a device must be placed in time (rule 5.3). If the entry named is a task of this series: give\n"
     "    it a time under 'values' (at: task:<name>, quantity: start_time, value or lower/upper, kind: assumed)\n"
     "    and declare its other times under 'unknown'. If it is a commissioning in the library: give that task\n"
     "    an end there (as projects/chemotion_example/curation/archive/add_commissioning_time.py did)."),
    (r"This transfer is missing and must not be created here any more",
     "A reaction at an interface names a transfer that the interface does not have - usually the answer to\n"
     "    'Which type of transfer moves ...' or 'Which phase ... is involved'. Answer those keys under 'open'\n"
     "    (a reactant: Adsorption from the fluid phase, a product: Desorption into it)."),
    (r"uncommitted",
     "Commit the libraries first (rule 2.4)."),
]


def _project(argument: str) -> Path:
    path = Path(argument)
    if not path.is_absolute():
        path = (Path.cwd() / path) if (Path.cwd() / path).exists() else ROOT / "projects" / argument
    if not (path / "setup.yaml").exists():
        sys.exit(f"No setup sheet in {path} - give the project folder, e.g. projects/<crate_identifier>.")
    return path.resolve()


def _check(sheet: Path) -> tuple:
    """(errors, still open): the findings of check_sheet.py, split - an empty entry of 'open', 'values' or
    'occurrences' is a question still to answer, everything else stops."""
    findings = SheetCheck(sheet).run()
    errors, still_open = [], []
    for kind, where, text in findings:
        if kind == "warning":
            continue
        section = where.strip(" /").split(" / ")[0]
        (still_open if kind == "missing" and section in QUESTION_SECTIONS else errors).append((kind, where, text))
    return errors, still_open


def _libraries_committed() -> bool:
    result = subprocess.run(["git", "status", "--porcelain", "--", "libraries"], cwd=ROOT, capture_output=True, text=True)
    return result.returncode == 0 and not result.stdout.strip()


def _remove(path: Path) -> bool:
    """Remove a file or folder of an earlier call - also read-only files the copy brought along."""
    def writable_again(function, name, _error):
        os.chmod(name, stat.S_IWRITE)
        function(name)
    try:
        if path.is_dir():
            shutil.rmtree(path, onexc=writable_again)
        elif path.exists():
            path.unlink()
        return True
    except OSError:
        return False


def _run(project: Path, out: Path) -> dict:
    """The exploratory run in a throwaway copy; its report."""
    if not _remove(out):
        # A file of the old copy is still locked (OneDrive, an open program): a new folder.
        out = Path(tempfile.mkdtemp(prefix=f"{out.name}_", dir=out.parent)) / "copy"
    report = out.parent / f"{out.name}_report.json"
    log = out.parent / f"{out.name}.log"
    _remove(report), _remove(log)
    rel = project.relative_to(ROOT).as_posix()
    # A completed series is opened again in the copy.
    reopen = ["--reopen", project.name] if (project / "crate_completed").exists() else []
    # From the sheet alone: a stored answer would cover a gap or a change of the sheet - a value the sheet
    # names since the last run would stay unknown, and the questions it brings would only come in the real run.
    command = [sys.executable, str(ROOT / "generator" / "workflow" / "isolated_run.py"), "--answers", f"{rel}/answers.txt",
               *reopen, "--out", str(out), "--", "--setup", f"{rel}/setup.yaml", "--from-sheet", "--on-unknown", "log",
               "--report", str(report)]
    with open(log, "w", encoding="utf-8") as handle:
        subprocess.run(command, cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT)
    if not report.exists():
        tail = log.read_text(encoding="utf-8", errors="replace").splitlines()[-15:]
        sys.exit("The exploratory run did not get going:\n  " + "\n  ".join(tail))
    return json.loads(report.read_text(encoding="utf-8")) | {"_log": str(log), "_copy": str(out)}


def _explain_stop(status: str):
    message = status.removeprefix("stopped:").strip()
    print("The run stopped on something that is not a question:\n")
    print("  " + "\n  ".join(message.splitlines()))
    for pattern, hint in HINTS:
        if re.search(pattern, message):
            print(f"\n  What to do: {hint}")
            break
    else:
        print("\n  The run log of the copy (--keep) shows where it happened.")


def _print_own_fields(keys: list):
    """The questions a field of the sheet answers, by the entry they belong to - such a field is optional,
    so check_sheet.py does not name it; written here instead of under 'open' (one place per fact)."""
    groups = {}
    for key in keys:
        experiment, parts = _thing(key)
        place = _place(parts) + (f" (experiment {experiment})" if experiment else "")
        groups.setdefault(place, []).append(key.rsplit("/", 1)[-1])
    print(f"   {len(keys)} question(s) belong to a field of the sheet - add the field to that entry ([] or '' for")
    print("   none; 'none: task_details' says it for every task at once):")
    for place, fields in groups.items():
        print(f"     {place}: {', '.join(dict.fromkeys(fields))}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("project", help="the project folder, projects/<crate_identifier>")
    parser.add_argument("--keep", action="store_true", help="keep the throwaway copy and print where it is")
    args = parser.parse_args()
    project = _project(args.project)
    sheet = project / "setup.yaml"
    rel = project.relative_to(ROOT).as_posix()

    # 1. The sheet
    errors, still_open = _check(sheet)
    if errors:
        print(f"1. The sheet: {len(errors)} thing(s) to settle first (check_sheet.py):\n")
        for kind, where, text in errors:
            print(f"  [{kind}] {where.strip(' /')}\n      {text}")
        print(f"\nSettle them in {rel}/setup.yaml, then call this again.")
        return 1
    print(f"1. The sheet: fine" + (f" - {len(still_open)} question(s) written earlier still unanswered." if still_open else "."))
    if not _libraries_committed():
        print("   Note: libraries/ has uncommitted changes - commit them before the real run (rule 2.4).")

    # 2. Exploratory run
    completed = (project / "crate_completed").exists()
    print("2. Exploratory run in a throwaway copy, from the sheet alone" + (" - the series is completed: reopened there"
          if completed else "") + " ...", flush=True)
    out = Path(tempfile.gettempdir()) / f"ns_{project.name}"
    report = _run(project, out)
    status = report.get("status", "")
    stand_ins = report.get("stand_ins", [])

    # 3. Stop without a question
    if not status.startswith("completed") and "Unknown question" not in status:
        print()
        _explain_stop(status)
        print(f"\n   ({len(stand_ins)} question(s) were open up to that point - they are written once the run gets through.)")
        if args.keep:
            print(f"   Copy: {report['_copy']}\n   Log:  {report['_log']}")
        return 1

    # 4. Questions into the sheet
    if stand_ins:
        questions, skeletons, own = write_sheet(stand_ins, sheet)
        print(f"   {len(stand_ins)} question(s) nobody answered.")
        print(f"3. Written to {rel}/setup.yaml: {questions} new question(s) under 'open', {skeletons} new empty "
              f"value(s) or statement(s) under 'values' / 'occurrences'.")
        if own:
            _print_own_fields(own)
    else:
        questions = skeletons = 0
        print("   Every question was answered.")
    if args.keep:
        print(f"   Copy: {report['_copy']}\n   Log:  {report['_log']}")

    # 5. What next
    print("\nNext:")
    if not stand_ins:
        print("  Nothing is open. Build the crate for real from the sheet, as it was explored (commit the libraries first;")
        print("  the answer file is written anew):")
        if completed:
            print("    # the series is completed: open it again first (takes its usage out of the libraries, commits that)")
            print(f"    python generator/workflow/reopen_crate.py {project.name}")
        print(f"    ANSWER_FILE={rel}/answers.txt python generator/workflow/answer_driver.py --in-place --setup {rel}/setup.yaml --from-sheet")
    elif questions or skeletons:
        print(f"  Answer what you know in {rel}/setup.yaml - under 'open' an answer and its source ('' = none on")
        print("  purpose), under 'values' a value or delete the entry - then call this again:")
        print(f"    python generator/workflow/next_step.py {rel}")
    elif _check(sheet)[1]:
        print("  Nothing new came up: what is still open is already in the sheet. Answer what you know, then")
        print("  declare the rest unknown (with your name) and call this again:")
        print(f'    python generator/workflow/close_sheet.py {rel}/setup.yaml --by "<your name>"')
        print(f"    python generator/workflow/next_step.py {rel}")
    else:
        # The sheet has nothing open any more, and still questions remain: the sheet names the thing, but
        # in a form the adapter does not read (a unit symbol, a name) - the question shows which.
        print(f"  The sheet has nothing open, yet {len(stand_ins)} question(s) stay unanswered - the sheet names the")
        print("  thing in a form the adapter does not read (a unit symbol, a name). The questions:")
        for stand_in in stand_ins[:20]:
            options = f"  [{', '.join(stand_in['options'])}]" if stand_in.get("options") else ""
            print(f"    - {stand_in.get('prompt', '').strip()}{options}")
            print(f"      key: {stand_in['key']}")
        print(f"  Correct the entry in {rel}/setup.yaml (or answer the key under 'open'), then call this again.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
