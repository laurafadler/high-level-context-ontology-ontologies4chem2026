"""
Turn every record of an ELN export into a core file (interfaces/eln/core.py). Reads only; writes the
core files, nothing else. An export is an .eln file or the collection export of Chemotion (a .zip with
export.json, read without unpacking). Default target: for an export in a project
(projects/<crate_identifier>/input/eln/) the project's core/ folder, otherwise core_files/ next to the export.

Usage (from the repository root):
    python generator/workflow/eln_to_core.py projects/<crate_identifier>/input/eln/<export>.eln [--out <folder>]
    python generator/workflow/eln_to_core.py projects/<crate_identifier>/input/eln/<chemotion export>.zip [--out <folder>]
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from interfaces.eln.core import write  # noqa: E402
from interfaces.eln.profiles import open_export, profile_for  # noqa: E402


def convert(eln: Path, out: Path) -> list:
    """Write one core file per record of the export into out; the paths written, in record order."""
    archive = open_export(eln)
    profile = profile_for(archive)
    paths = []
    for record in archive.records():
        core = profile.to_core(archive, record)
        path = write(core, out)
        print(f"{core['source']['system']} {core['source']['record_id']}: {core['experiment'].get('title')!r} -> {path}")
        paths.append(Path(path))
    return paths


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("eln", type=Path)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    folder = args.eln.resolve().parent
    in_project = folder.name == "eln" and folder.parent.name == "input"
    out = args.out or (folder.parent.parent / "core" if in_project else folder / "core_files")
    convert(args.eln, out)


if __name__ == "__main__":
    main()
