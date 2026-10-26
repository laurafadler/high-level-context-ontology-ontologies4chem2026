"""
Run the pipeline in a throwaway copy of the project, so that nothing in the project itself
changes - not the crate, not the answer file, not the to-do list, not the chemical entity
library (a run writes all four).

Every path in the project hangs off path_definitions.BASE_FOLDER, the folder of that file,
so a copy runs completely on its own. The copy gets the marker file that
workflow/answer_driver.py insists on, and the driver is started inside it.

Run from the repository root:
    python generator/workflow/isolated_run.py [--answers projects/<crate_identifier>/answers.txt] [--out DIR]
                                 [-- <arguments for generator/workflow/answer_driver.py>]

Examples:
    # Reference run: the answer file as it is, any unknown question stops the run
    python generator/workflow/isolated_run.py

    # Which questions does a change bring up? Keep going and list them.
    python generator/workflow/isolated_run.py -- --on-unknown log --rules my_rules.json

    # A completed series: open it again in the copy first (workflow/reopen_crate.py)
    python generator/workflow/isolated_run.py --reopen <crate_identifier> --answers <empty file> \
        -- --setup projects/<crate_identifier>/setup.yaml --on-unknown log --report <report.json>

Without --out the copy lands in a fresh temporary folder. The script prints where the crate,
the answer file after the run, the log and the driver report are. Compare two crates with
generator/workflow/compare_crates.py.
"""
import argparse
import os
import shutil
import subprocess
import time
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
GENERATOR = PROJECT / "generator"
ISOLATED_MARKER = ".isolated_copy"

# What need not go into the copy: leftovers, bytecode, and the copy itself, if --out lies in
# the project.
_PATTERNS = shutil.ignore_patterns("__pycache__", ".git", "*.pyc", ISOLATED_MARKER, ".venv", ".claude", "archive", "docs")


def _ignored(folder, names):
    """What copytree leaves out: the patterns above, and the input/ folder of every project - that
    one is copied with its time stamps (_copy_inputs)."""
    ignored = set(_PATTERNS(folder, names))
    if Path(folder).parent.name == "projects" and "input" in names:
        ignored.add("input")
    return ignored


def _copy_inputs(copy: Path):
    """Copy projects/*/input/ keeping the creation time of every file: the crate records it
    (st_ctime, get_file_metadata.py), and shutil sets a new one on Windows."""
    for source in sorted((PROJECT / "projects").glob("*/input")):
        target = copy / source.relative_to(PROJECT)
        if sys.platform == "win32":
            # robocopy reports success with exit codes 0-7 (1 = files copied), an error from 8 on.
            result = subprocess.run(["robocopy", str(source), str(target), "/E", "/COPY:DAT", "/DCOPY:DAT",
                                     "/XD", "__pycache__", "/NFL", "/NDL", "/NJH", "/NJS", "/NP"],
                                    capture_output=True, text=True)
            if result.returncode >= 8:
                sys.exit(f"robocopy {source} failed ({result.returncode}): {result.stdout}{result.stderr}")
        else:
            shutil.copytree(source, target)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--answers", default=None,
                        help="answer file to start from (relative to the project, or absolute); "
                             "default: projects/<crate_identifier>/answers.txt of the only open crate")
    parser.add_argument("--out", help="folder for the copy (must not exist yet); default: a new temp folder")
    parser.add_argument("--reopen", action="append", default=[], metavar="CRATE_IDENTIFIER",
                        help="open this completed series again in the copy before the run (workflow/reopen_crate.py); "
                             "may be given more than once")
    parser.add_argument("driver_args", nargs=argparse.REMAINDER,
                        help="everything after '--' is passed on to workflow/answer_driver.py")
    args = parser.parse_args()

    if args.answers is None:
        # The answer file is named like its crate (path_definitions.answer_file_path).
        sys.path.insert(0, str(GENERATOR))
        import path_definitions
        answers = path_definitions.default_answer_file()
    else:
        answers = Path(args.answers)
    if not answers.is_absolute():
        answers = PROJECT / answers
    if not answers.exists():
        sys.exit(f"Answer file not found: {answers}")

    if args.out:
        copy = Path(args.out).resolve()
        if copy.exists():
            sys.exit(f"{copy} exists already - pick a new folder, a run must not mix with an old one.")
        if PROJECT in copy.parents:
            sys.exit(f"{copy} lies inside the project - the next copy would copy it along.")
    else:
        copy = Path(tempfile.mkdtemp(prefix="crate_run_")) / "repo"

    shutil.copytree(PROJECT, copy, ignore=_ignored)
    _copy_inputs(copy)
    (copy / ISOLATED_MARKER).write_text(f"copy of {PROJECT}\n", encoding="utf-8")
    if args.reopen:
        # In the copy, never in the project: take the usage out of the libraries, delete crate_completed/
        # (without a commit - commit_library_changes writes nothing in a copy).
        reopened = subprocess.run([sys.executable, "generator/workflow/reopen_crate.py", *args.reopen], cwd=copy,
                                  env=dict(os.environ, PYTHONPATH=str(copy / "generator"), PYTHONIOENCODING="utf-8"))
        if reopened.returncode != 0:
            sys.exit("Reopening failed - see above.")
    # The crates copied along stay: a run that continues an open series compares itself with its
    # state so far. So that a stopped run does not pass as "identical", only a crate this run wrote
    # is named below.
    started = time.time()

    # The answer file of the copy is the one the run continues. If it comes from outside the
    # project, it is copied in - the original is never written.
    try:
        answers_in_copy = copy / answers.resolve().relative_to(PROJECT)
    except ValueError:
        answers_in_copy = copy / "projects" / "_from_outside" / answers.name
        answers_in_copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(answers, answers_in_copy)

    driver_args = [a for a in args.driver_args if a != "--"]
    # Relative paths (e.g. --rules my_rules.json) refer to the folder isolated_run was started
    # from, not to the copy.
    for flag in ("--rules", "--setup"):
        if flag in driver_args:
            i = driver_args.index(flag) + 1
            driver_args[i] = str(Path(driver_args[i]).resolve())

    env = dict(os.environ, ANSWER_FILE=str(answers_in_copy), PYTHONPATH=str(copy / "generator"), PYTHONIOENCODING="utf-8")
    env.pop("STRICT_ANSWERS", None)
    log_path = copy / "run.log"
    print(f"Running in {copy} ...")
    with open(log_path, "w", encoding="utf-8") as log:
        result = subprocess.run([sys.executable, "generator/workflow/answer_driver.py", *driver_args],
                                cwd=copy, env=env, stdout=log, stderr=subprocess.STDOUT)

    # The summary of the driver stands at the end of the log.
    lines = log_path.read_text(encoding="utf-8").splitlines()
    start = max((i for i, line in enumerate(lines) if line.startswith("=== answer driver ===")), default=None)
    print("\n".join(lines[start:] if start is not None else lines[-25:]))
    print(f"\ncopy:          {copy}")
    written = [path for path in (copy / "projects").rglob("ro-crate-metadata.json") if path.stat().st_mtime >= started]
    print(f"crate:         {written[0] if written else '(none written by this run)'}")
    print(f"answer file:   {answers_in_copy}")
    print(f"log:           {log_path}")
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
