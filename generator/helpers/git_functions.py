"""
Git state of the libraries: checked at the start of a run, committed at its end, and read
for the library snapshot of the crate.

A crate only links to library entries, it does not copy them (rule
2.1). A link is only as good as the library state it points at, and the libraries
change - after every run the usage history of the devices moves on. The crate therefore
records, per library file, the commit that holds the state it was built against. That
needs two guarantees, and this module gives them:

- At the start the libraries have no uncommitted changes (otherwise the state the run reads
  exists in no commit).
- At the end the run commits what it changed in the libraries itself, before the crate is
  written - so the recorded commit contains every entry the crate points at.

Only libraries/ is ever committed, only locally, never pushed.

In an isolated copy (generator/workflow/isolated_run.py) there is no repository. The copy's marker file
names the project it was copied from; commits are then looked up there, read-only, and only
recorded where the file in the copy is exactly the committed state. Nothing is ever
committed from a copy.
"""

import subprocess
from pathlib import Path

import path_definitions

ISOLATED_MARKER = ".isolated_copy"
_MARKER_PREFIX = "copy of "


class DirtyLibrariesError(RuntimeError):
    """The libraries have uncommitted changes at the start of a run."""


def _git(args: list, cwd: Path) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed in {cwd}: {result.stderr.strip()}")
    return result.stdout.strip()


def _source_project() -> Path | None:
    """The project an isolated copy was made from, or None when this is not a copy."""
    marker = path_definitions.BASE_FOLDER / ISOLATED_MARKER
    if not marker.exists():
        return None
    text = marker.read_text(encoding="utf-8").strip()
    return Path(text[len(_MARKER_PREFIX):]) if text.startswith(_MARKER_PREFIX) else None


def is_isolated_copy() -> bool:
    return (path_definitions.BASE_FOLDER / ISOLATED_MARKER).exists()


def _relative_library_path(path: Path) -> str:
    return path.resolve().relative_to(path_definitions.BASE_FOLDER.resolve()).as_posix()


# What a run commits asks for: the libraries and the settings of the generator (units,
# prefix table).
def _committed_folders() -> list:
    return [_relative_library_path(path_definitions.LIBRARY_FOLDER), _relative_library_path(path_definitions.CONFIG_FOLDER)]


def ensure_libraries_committed():
    """Stop the run when libraries/ or generator/config/ has uncommitted changes - the state the
    run would read would then exist in no commit, and the crate could not say which one it used."""
    if is_isolated_copy():
        return
    status = _git(["status", "--porcelain", "--", *_committed_folders()], path_definitions.BASE_FOLDER)
    if status:
        raise DirtyLibrariesError(
            "The libraries have uncommitted changes:\n" + status + "\n"
            "Commit them first - the crate records which library state it was built against, "
            "and that state has to exist in a commit."
        )


def commit_library_changes(message: str) -> bool:
    """Commit everything the run changed under libraries/ (and only that). Returns whether
    there was anything to commit."""
    if is_isolated_copy():
        return False
    library_folder = _relative_library_path(path_definitions.LIBRARY_FOLDER)
    if not _git(["status", "--porcelain", "--", library_folder], path_definitions.BASE_FOLDER):
        return False
    _git(["add", "--", library_folder], path_definitions.BASE_FOLDER)
    # status also reports a file that differs only in its line endings (LF on disk, save_jsonld
    # writes CRLF); after the add nothing is staged then, and commit stops with "nothing to
    # commit". What matters is what is really staged.
    if not _git(["diff", "--cached", "--name-only", "--", library_folder], path_definitions.BASE_FOLDER):
        return False
    # With paths given, git commits only these paths - whatever else is staged right now stays
    # untouched and does not end up in this commit.
    _git(["commit", "-m", message, "--", library_folder], path_definitions.BASE_FOLDER)
    return True


def file_before_commits_mentioning(path: Path, text: str) -> str | None:
    """The content of a file as it was before the FIRST commit whose message contains text -
    or None when no such commit exists (or there is no repository to ask).

    Used to read the libraries as they were before a crate wrote into them: a crate built a
    second time must see the state before its first run, not its own earlier entries.
    """
    source = _source_project()
    project = source if source is not None else path_definitions.BASE_FOLDER
    relative = _relative_library_path(path)
    try:
        # A library file can have been moved or renamed. --follow knows the path of the time for every commit, from the root
        # of the repository - but not together with --grep: then the renaming commit is missing, and
        # git does not follow the old path. Hence separately: the history of the file, the commits
        # with the text, and the intersection.
        history = [line.strip() for line in
                   _git(["log", "--follow", "--format=%H", "--name-only", "--", relative], project).splitlines()
                   if line.strip()]
        path_at = dict(zip(history[0::2], history[1::2]))
        mentioning = _git(["log", "--format=%H", "--fixed-strings", f"--grep={text}"], project).splitlines()
        commits = [commit for commit in mentioning if commit in path_at]
        if not commits:
            return None
        # git log lists the newest first - the first commit of this crate stands at the bottom.
        return _git(["show", f"{commits[-1]}^:{path_at[commits[-1]]}"], project)
    except RuntimeError:
        return None


def last_commit_of(path: Path) -> tuple[str, str] | None:
    """(commit hash, commit date in ISO 8601) of the last commit that changed this file - the
    commit that holds the file as it is now. None when that cannot be said: no repository,
    the file is not committed, or (in an isolated copy) the copy differs from the commit.

    The last commit of the FILE rather than HEAD: it names the same state, but does not move
    with every unrelated commit, so two runs against the same libraries record the same.
    """
    source = _source_project()
    project = source if source is not None else path_definitions.BASE_FOLDER
    relative = _relative_library_path(path)
    try:
        line = _git(["log", "-1", "--format=%H %cI", "--", relative], project)
        if not line:
            return None
        if source is not None:
            # In the copy the commit holds only if the file there is exactly the committed one.
            # hash-object with --path applies the same filters (line endings) as a commit.
            # "./" before the path: without it git computes "<commit>:<path>" from the root of the
            # repository, not from the current folder.
            copy_blob = _git(["hash-object", f"--path={relative}", str(path.resolve())], project)
            committed_blob = _git(["rev-parse", f"{line.split(' ', 1)[0]}:./{relative}"], project)
            if copy_blob != committed_blob:
                return None
        elif _git(["status", "--porcelain", "--", relative], project):
            return None
    except RuntimeError:
        return None
    commit, date = line.split(" ", 1)
    return commit, date
