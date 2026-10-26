"""
Rename a crate: give an open series a new identifier (short name).

    python generator/workflow/rename_crate.py OLD NEW [--answers FILE]

A crate is not renamed in place - its identifier is in every @id (crate:<crate_identifier>/...), in the
library entries that point into it and in the name of its answer file. Renaming therefore means
building the crate again under the new name (rule 7a.7):

1. Checks: OLD is an open crate (output/OLD/), NEW is free (no crate, no archived crate, no usage
   commits in the device library), the libraries are committed, the answer file exists
   (default answers/OLD_answers.txt).
2. A new answer file answers/NEW_answers.txt: the old one with the answer to
   setup/series_short_name changed to NEW, nothing else.
3. The libraries: every reference crate:OLD/... becomes crate:NEW/... (the usage history of the
   devices, lastUsedTime, lastUsedPurpose). Committed, because a run starts only from committed
   libraries - and it has to come BEFORE the run: the run reads the usage history and takes the
   crate's own entries out of it by their identifier (rule 5.4).
4. The crate is built under NEW (generator/workflow/answer_driver.py, every question from the answer file; an
   unknown question stops it).
5. The new crate is compared with the old one, OLD replaced by NEW: they have to be identical
   apart from the library commits the crate records (schema:version of its library list).
6. Only then the old crate folder and the old answer file are deleted. The script does not
   commit the crate - it prints the git command for that.

Stops on the first problem and says what is already done. Crates of later series that point
into OLD (their lastUsedTime) are listed at the end: they need a run of their own.

Run from the repository root. Works in an isolated copy too (generator/workflow/isolated_run.py --out):
there nothing is committed, as everywhere in a copy.
"""
import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

GENERATOR = Path(__file__).resolve().parent.parent
PROJECT = GENERATOR.parent
sys.path.insert(0, str(GENERATOR))

import path_definitions  # noqa: E402
from helpers.identifiers import crate_identifier  # noqa: E402
from helpers.git_functions import ensure_libraries_committed, commit_library_changes, is_isolated_copy, file_before_commits_mentioning  # noqa: E402
from workflow.compare_crates import load  # noqa: E402

SHORT_NAME_KEY = "setup/series_short_name"
# What may change in the rebuild: the state of the libraries the crate was built against - the
# renaming itself is a new library commit.
ALLOWED_CHANGES = {"schema:version"}


def _fail(message: str):
    sys.exit(f"\n[rename] STOPPED: {message}")


def _check(old: str, new: str, answers: Path):
    if old == new:
        _fail("old and new identifier are the same.")
    try:
        crate_identifier(new)
    except ValueError as error:
        _fail(f"'{new}' is not a valid identifier: {error}")
    if not path_definitions.crate_path(old).exists():
        archived = path_definitions.archived_crate_folder(old).exists()
        _fail(f"there is no open crate {old}" + (" - it is archived (completed); an archived series is not rebuilt." if archived else "."))
    if path_definitions.crate_folder(new).exists() or path_definitions.archived_crate_folder(new).exists():
        _fail(f"a crate {new} exists already.")
    from creation.device_usage_functions import _commit_mention
    if any(file_before_commits_mentioning(path, _commit_mention(new)) is not None
           for path in path_definitions.DEVICE_LIBRARY_PATHS):
        _fail(f"the device or material library already records usage under {new} - pick another identifier.")
    if not answers.exists():
        _fail(f"answer file not found: {answers} (pass it with --answers).")
    if path_definitions.answer_file_path(new).exists():
        _fail(f"{path_definitions.answer_file_path(new)} exists already.")
    ensure_libraries_committed()


def _write_new_answer_file(answers: Path, old: str, new: str) -> Path:
    raw = answers.read_bytes()
    newline = "\r\n" if b"\r\n" in raw else "\n"
    lines = raw.decode("utf-8").replace("\r\n", "\n").split("\n")
    index = next((i for i, line in enumerate(lines) if line.strip() == f"key: {SHORT_NAME_KEY}"), None)
    if index is None:
        _fail(f"{answers} has no answer for {SHORT_NAME_KEY}.")
    answer_index = index + 1
    while answer_index < len(lines) and lines[answer_index].lstrip().startswith("//"):
        answer_index += 1
    if lines[answer_index].strip() != old:
        _fail(f"{answers} answers {SHORT_NAME_KEY} with '{lines[answer_index].strip()}', not '{old}'.")
    lines[answer_index] = new
    target = path_definitions.answer_file_path(new)
    target.write_bytes(newline.join(lines).encode("utf-8"))
    print(f"[rename] New answer file {target.relative_to(PROJECT)} ({SHORT_NAME_KEY}: {new}).")
    return target


def _rename_in_libraries(old: str, new: str) -> int:
    old_prefix, new_prefix = f"crate:{old}/".encode("utf-8"), f"crate:{new}/".encode("utf-8")
    total = 0
    for library in sorted(path_definitions.LIBRARY_FOLDER.glob("*.jsonld")):
        raw = library.read_bytes()
        # Only the prefix is replaced. If the identifier stands anywhere else, it is unclear what it
        # means there - then rather stop than guess.
        if raw.count(old.encode("utf-8")) != raw.count(old_prefix):
            _fail(f"{library.name} mentions {old} outside a crate:{old}/ reference - check it by hand.")
        count = raw.count(old_prefix)
        if count:
            library.write_bytes(raw.replace(old_prefix, new_prefix))
            print(f"[rename] {library.name}: {count} reference(s) crate:{old}/... -> crate:{new}/...")
            total += count
    if total and commit_library_changes(f"Rename crate {old} to {new}: references in the libraries"):
        print("[rename] Libraries committed.")
    return total


def _build(new_answers: Path, new: str):
    env = dict(os.environ, ANSWER_FILE=str(new_answers), PYTHONPATH=str(GENERATOR), PYTHONIOENCODING="utf-8")
    env.pop("ALLOW_EARLIER_CHANGES", None)
    report = Path(tempfile.gettempdir()) / f"rename_crate_{new}_report.json"
    command = [sys.executable, str(GENERATOR / "workflow" / "answer_driver.py"), "--report", str(report)]
    if not is_isolated_copy():
        command.append("--in-place")
    log = Path(tempfile.gettempdir()) / f"rename_crate_{new}.log"
    print(f"[rename] Building the crate {new} (log: {log}) ...")
    with open(log, "w", encoding="utf-8") as handle:
        result = subprocess.run(command, cwd=PROJECT, env=env, stdout=handle, stderr=subprocess.STDOUT)
    status = json.loads(report.read_text(encoding="utf-8")).get("status") if report.exists() else None
    if result.returncode != 0 or status != "completed":
        _fail(f"the run did not complete ({status}); see {log}. The libraries are already renamed "
              f"(undo with git revert), the old crate is untouched.")


def _compare(old: str, new: str) -> bool:
    old_text = path_definitions.crate_path(old).read_text(encoding="utf-8").replace(old, new)
    with tempfile.NamedTemporaryFile("w", suffix=".jsonld", delete=False, encoding="utf-8") as handle:
        handle.write(old_text)
        renamed_old = Path(handle.name)
    try:
        old_context, before = load(renamed_old)
        new_context, after = load(path_definitions.crate_path(new))
    finally:
        renamed_old.unlink()
    problems = []
    if old_context != new_context:
        problems.append("@context differs")
    for entity_id in sorted(set(before) | set(after)):
        if entity_id not in after:
            problems.append(f"missing in the new crate: {entity_id}")
        elif entity_id not in before:
            problems.append(f"new in the new crate: {entity_id}")
        else:
            changed = {p for p in set(before[entity_id]) | set(after[entity_id])
                       if before[entity_id].get(p) != after[entity_id].get(p)}
            if changed - ALLOWED_CHANGES:
                problems.append(f"changed: {entity_id} ({', '.join(sorted(changed))})")
    if problems:
        print(f"[rename] The new crate differs from the old one beyond the name ({len(problems)}):")
        for problem in problems[:20]:
            print(f"  {problem}")
        return False
    print(f"[rename] The new crate is the old one under the new name ({len(after)} entities).")
    return True


def _remove_tree(path: Path):
    # On Windows copied folders (OneDrive) sometimes carry the read-only flag; rmtree then fails at
    # the empty folder. Remove the flag and try again.
    def retry(function, target, _error):
        os.chmod(target, stat.S_IWRITE)
        function(target)
    shutil.rmtree(path, onexc=retry)


def _crates_pointing_into(old: str) -> list:
    others = path_definitions.open_crate_paths() + path_definitions.archived_crate_paths()
    return [p for p in others if f"crate:{old}/" in p.read_text(encoding="utf-8")]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("old", help="current identifier (the folder name in projects/)")
    parser.add_argument("new", help="new identifier")
    parser.add_argument("--answers", help="answer file of the old crate (default: projects/OLD/answers.txt)")
    args = parser.parse_args()
    # An identifier with capital letters is written in lower case (helpers/identifiers.py: crate_identifier).
    args.old, args.new = args.old.lower(), args.new.lower()

    old_answers = Path(args.answers).resolve() if args.answers else path_definitions.answer_file_path(args.old)
    _check(args.old, args.new, old_answers)

    new_answers = _write_new_answer_file(old_answers, args.old, args.new)
    _rename_in_libraries(args.old, args.new)
    _build(new_answers, args.new)
    if not _compare(args.old, args.new):
        _fail(f"kept both crates (projects/{args.old}/ and projects/{args.new}/) and both answer files for a look. "
              "The libraries are already renamed (undo with git revert).")

    _remove_tree(path_definitions.crate_folder(args.old))
    old_answers.unlink()
    # Whatever else lies in the project folder (input/, core/, curation/, setup.yaml, reports/) moves along.
    old_project, new_project = path_definitions.project_folder(args.old), path_definitions.project_folder(args.new)
    for item in sorted(old_project.iterdir()):
        if not (new_project / item.name).exists():
            shutil.move(str(item), str(new_project / item.name))
    if not any(old_project.iterdir()):
        old_project.rmdir()
    print(f"[rename] Deleted the old crate and answer file; moved the rest of projects/{args.old}/ to projects/{args.new}/.")

    stale = _crates_pointing_into(args.old)
    if stale:
        print("[rename] These crates still point into the old identifier and need a run of their own:")
        for path in stale:
            print(f"  {path.relative_to(PROJECT)}")

    if not is_isolated_copy():
        print("\nCommit the renamed crate with:\n"
              f"  git add -A projects/{args.old} projects/{args.new} libraries\n"
              f"  git commit -m \"Crate {args.old} renamed to {args.new}\"")


if __name__ == "__main__":
    main()
