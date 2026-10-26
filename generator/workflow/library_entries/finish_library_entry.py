"""
Check a filled-in library entry file and write it into the libraries - for the library what
next_step.py is for the setup sheet.

One run:
1. checks the file against entry_schema.yaml (required fields, allowed values, formats, unknown fields);
2. looks up what it names: entered_by, organizations, ELN records. Something that does not exist and has a type
   of its own (an organization, a person) gets an entry file of that type, pre-filled with the name - finish that
   one first, then this one again;
3. prepares the entries (a substance: its PubChem record, kept next to the file). What a person has to decide
   (which CAS number) is written as a question under 'open' in the file;
4. builds the entries in memory and runs the library consistency check on that state: only when it reports
   nothing new is anything written;
5. with --write (and committed libraries), writes the libraries - main file and details - and records under
   'written' in the file what went in. Commit the libraries afterwards.

Without --write nothing is written: the run says what would be added.

Exit code: 0 done (or ready to write), 1 something is wrong, 2 the file needs an answer or another entry first.

Usage (from the repository root):
    python generator/workflow/library_entries/finish_library_entry.py projects/<id>/curation/library_entries/<file>.yaml
    python generator/workflow/library_entries/finish_library_entry.py <file>.yaml --write
"""
import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import path_definitions  # noqa: E402
from helpers.git_functions import DirtyLibrariesError, ensure_libraries_committed  # noqa: E402
from create_library_entry import create  # noqa: E402
from entry_file import EntryFile, empty  # noqa: E402
from entry_types import TYPES  # noqa: E402
from library_set import IdTaken, LibrarySet, new_findings  # noqa: E402

DONE, WRONG, WAITING = 0, 1, 2


class Job:
    """One run over one file: the file, the libraries, and what came up."""

    def __init__(self, entry_file: EntryFile, libraries: LibrarySet):
        self.file = entry_file
        self.path = entry_file.path
        self.libraries = libraries
        self.stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.problems, self.questions, self.follow_ups, self.notes = [], [], [], []
        self.person = None
        try:
            self.relative_path = self.path.resolve().relative_to(path_definitions.BASE_FOLDER.resolve()).as_posix()
        except ValueError:
            self.relative_path = self.path.name

    def numbered(self):
        return list(enumerate(self.file.entries, start=1))

    # What came up
    def problem(self, place, text):
        self.problems.append((place, text))

    def note(self, place, text):
        self.notes.append((place, text))

    def question(self, n, field, text, options=()):
        question = {"entry": n, "field": field, "question": text}
        if options:
            question["options"] = list(options)
        self.questions.append(question)

    def reference(self, kind: str, text, place: str):
        """The ID of the entry of this kind that text names; an unknown one becomes a follow-up (a type with a
        template) or a problem."""
        entity_id, why = self.libraries.resolve(kind, text)
        if entity_id:
            return entity_id
        if kind in TYPES and why.startswith("no "):
            self.follow_ups.append((kind, str(text), place))
        else:
            self.problem(place, why)
        return None

    # Texts
    def date(self) -> str:
        """The day of the run as the texts of the libraries write it."""
        return f"{self.stamp[8:10]}.{self.stamp[5:7]}.{self.stamp[:4]}"

    def by(self) -> str:
        return f"{self.person_name()}, {self.date()}"

    def person_name(self) -> str:
        entity = self.libraries.find(self.person)[1] if self.person else None
        return (entity or {}).get("schema:name", self.person or "?")

    def origin(self, note=None) -> str:
        """The sentence every entry carries: its note, where the information comes from, how it was entered."""
        parts = [str(note).strip()] if not empty(note) else []
        parts.append(str(self.file.data["source"]).strip().rstrip(".") + ".")
        parts.append(f"Entered by {self.person_name()} on {self.date()} with "
                     f"generator/workflow/library_entries/finish_library_entry.py from {self.relative_path}.")
        return " ".join(parts)


def _report(title, rows):
    if rows:
        print(f"\n{title} ({len(rows)}):")
        for place, text in rows:
            print(f"  {place}: {text}")


def _start_follow_ups(job: Job) -> list:
    """An entry file per missing thing - unless an unwritten one for the same name lies in the folder already."""
    folder = job.path.parent
    started = []
    for kind, name, place in job.follow_ups:
        existing = None
        for other in sorted(folder.glob(f"{kind}_*.yaml")):
            try:
                data = EntryFile(other)
            except Exception:
                continue
            if not data.data.get("written") and any(str(e.get("name")) == name for e in data.entries):
                existing = other
                break
        path = existing or create(kind, folder, prefill={"name": name}, head={"entered_by": job.file.data.get("entered_by")})
        started.append((place, f"'{name}' is not in the library - {'its entry file is' if existing else 'started'}: {path}"))
    return started


def finish(path: Path, write: bool = False) -> int:
    entry_file = EntryFile(path)
    print(f"=== {path} ===")
    if entry_file.data.get("written"):
        print("Written already (section 'written') - nothing to do. A further entry needs a new file.")
        return WRONG
    findings = entry_file.check()
    if findings:
        for kind, place, text in findings:
            print(f"  {kind}: {place}{(' - ' + text) if text else ''}")
        return WRONG

    libraries = LibrarySet()
    job = Job(entry_file, libraries)
    job.person = job.reference("person", entry_file.data["entered_by"], "entered_by")
    entry_type = TYPES[entry_file.type]()
    entry_type.prepare(job)

    _report("Notes", job.notes)
    if job.problems:
        _report("Problems", job.problems)
        return WRONG
    if job.follow_ups:
        _report("Needed first", _start_follow_ups(job))
        print("\nFinish those files first, then run this one again.")
        return WAITING
    if job.questions:
        new = entry_file.ask(job.questions)
        print(f"\nQuestions ({len(job.questions)}{', new under open: ' + str(len(new)) if new else ', under open'}):")
        for question in job.questions:
            print(f"  entries[{question['entry']}].{question['field']}: {question['question']}"
                  + (f"\n    options: {', '.join(question['options'])}" if question.get("options") else ""))
        return WAITING

    before = libraries.consistency(current=False)
    try:
        entry_type.build(job)
    except (IdTaken, ValueError, RuntimeError) as error:
        # RuntimeError: e.g. a usage history the preparation cannot be sorted into (a task without a time).
        print(f"\nProblem - nothing is written: {error}")
        return WRONG
    blocking, information = new_findings(before, libraries.consistency())
    print("\nWould be added:" if not write else "\nAdded:")
    for name, entities in libraries.new.items():
        if entities:
            print(f"  {name}: {len(entities)} entities - " + ", ".join(e["@id"] for e in entities[:8])
                  + (" ..." if len(entities) > 8 else ""))
    for name in sorted(libraries.changed):
        print(f"  {name}: links back on existing entries")
    for section, lines in information.items():
        print(f"  ({section}: {', '.join(lines)} - new entries are unreferenced until a crate uses them)")
    if blocking:
        print("\nThe library consistency check reports something new - nothing is written:")
        for section, lines in blocking.items():
            print(f"  {section}:")
            for line in lines:
                print(f"    {line}")
        return WRONG
    print("Library consistency check: nothing new.")
    if not write:
        print("\nDry run - nothing written. Write with --write.")
        return DONE

    try:
        ensure_libraries_committed()
    except DirtyLibrariesError as error:
        print(f"\n{error}")
        return WRONG
    files = libraries.write()
    entry_file.record_written({"at": job.stamp, "by": job.person,
                               "entries": [e["@id"] for name in libraries.new for e in libraries.new[name]][:200],
                               "libraries": [f.name for f in files]})
    print("\nWritten: " + ", ".join(f.name for f in files))
    print("Commit the libraries (and this file), e.g.:\n  git add libraries " + f'"{job.relative_path}"'
          + f' && git commit -m "Library entries: {entry_file.type} from {path.name}"')
    return DONE


def main():
    parser = argparse.ArgumentParser(description="Check a library entry file and write it into the libraries.")
    parser.add_argument("file", help="the entry file (made by create_library_entry.py)")
    parser.add_argument("--write", action="store_true", help="write into the libraries (otherwise a dry run)")
    args = parser.parse_args()
    sys.exit(finish(Path(args.file), args.write))


if __name__ == "__main__":
    main()
