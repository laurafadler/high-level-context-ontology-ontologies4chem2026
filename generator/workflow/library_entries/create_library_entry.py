"""
Write the empty template of a library entry: one file per type, with every field the type can
have - the required ones open, the optional ones commented out. Fill it in, then check and write it with
finish_library_entry.py. The fields come from entry_schema.yaml.

The file lands in projects/<crate_identifier>/curation/library_entries/ (with --project), or in --out. It stays
there after it was written, as the record of who entered what.

Usage (from the repository root):
    python generator/workflow/library_entries/create_library_entry.py person --project pba_synthesis
    python generator/workflow/library_entries/create_library_entry.py substance --out <folder>
    python generator/workflow/library_entries/create_library_entry.py --list
"""
import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import path_definitions  # noqa: E402
from entry_file import entry_types, load_schema, template_text  # noqa: E402

FOLDER_NAME = "library_entries"


def entry_folder(project: str = None, out: str = None) -> Path:
    if out:
        return Path(out)
    folder = path_definitions.BASE_FOLDER / "projects" / project
    if not folder.is_dir():
        raise SystemExit(f"No project {project} under projects/")
    return folder / "curation" / FOLDER_NAME


def create(entry_type: str, folder: Path, prefill: dict = None, head: dict = None) -> Path:
    """Write the template into folder; returns its path (a new name per minute and type, never overwritten)."""
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"{entry_type}_{datetime.now().strftime('%Y%m%d_%H%M')}"
    path, k = folder / f"{stem}.yaml", 1
    while path.exists():
        k += 1
        path = folder / f"{stem}_{k}.yaml"
    path.write_text(template_text(entry_type, prefill, head), encoding="utf-8", newline="\n")
    return path


def main():
    parser = argparse.ArgumentParser(description="Write the empty template of a library entry.")
    parser.add_argument("type", nargs="?", help="the type of entry: " + ", ".join(entry_types()))
    where = parser.add_mutually_exclusive_group()
    where.add_argument("--project", help="crate identifier: the file goes to projects/<it>/curation/library_entries/")
    where.add_argument("--out", help="folder for the file, when it belongs to no project")
    parser.add_argument("--list", action="store_true", help="list the types and what they are for")
    args = parser.parse_args()

    schema = load_schema()
    if args.list or not args.type:
        for name, spec in schema["types"].items():
            print(f"{name:14} -> libraries/{spec['library']}\n{'':14}    {' '.join(str(spec['doc']).split())}")
        return
    if args.type not in schema["types"]:
        raise SystemExit(f"Unknown type '{args.type}' - known: {', '.join(schema['types'])}")
    if not (args.project or args.out):
        raise SystemExit("Say where the file goes: --project <crate_identifier> or --out <folder>")
    path = create(args.type, entry_folder(args.project, args.out))
    print(f"Template written: {path}")
    print(f"Fill it in, then: python generator/workflow/library_entries/finish_library_entry.py \"{path}\"")


if __name__ == "__main__":
    main()
