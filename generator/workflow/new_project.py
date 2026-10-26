"""
Start a new series: the project folder, an empty answer file and a skeleton of the setup sheet - and,
with an ELN export, its core files. Step 0 of docs/new_series_guide.md.

Writes only into the new folder projects/<crate_identifier>/ and stops if it exists already. Nothing is
answered for anyone: the sheet holds the required fields, empty, and every other section as a
comment; check_sheet.py then names what is still missing.

    projects/<crate_identifier>/
      input/additional_files_for_crate/   files of the whole series (the ELN export lands here - it is
                                          a file of the crate, as in the other projects)
      input/lab_data_for_crate/           lab files, one subfolder per experiment ending in exp<n>
      core/                               core files of the ELN records (only with --eln)
      curation/                           PubChem answers, library scripts of this series
      answers.txt                         only the header line: a new crate starts from it
      setup.yaml                          the skeleton of the setup sheet

Usage (from the repository root):
    python generator/workflow/new_project.py <crate_identifier> --eln <export.eln> [--by "<name>"]
    python generator/workflow/new_project.py <crate_identifier> --experiments <n> [--by "<name>"]
    python generator/workflow/new_project.py <crate_identifier>

The last form only creates the folder and the skeleton: the ELN export can be put into
input/additional_files_for_crate/ afterwards, the number of experiments goes into the sheet. An ELN
without a profile yet (interfaces/eln/profiles) is copied into the project all the same, without core files.

Examples:
    python generator/workflow/new_project.py pba_synthesis --experiments 2 --by "Laura Fadler"
    
    python generator/workflow/new_project.py <crate_identifier> --eln <path/to/export.eln> --by "Laura Fadler"

<crate_identifier> is the identifier of the crate: letters, digits, "_" and "-", stored in lower case
(e.g. hydrogenation_rdy_2026_09). --by names the person who fills in the sheet; it goes into the
source lines the skeleton writes (rule 2.10) - without it they stay empty to fill in.
"""
import argparse
import shutil
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import path_definitions  # noqa: E402
from helpers.identifiers import crate_identifier  # noqa: E402
from helpers.user_io import FORMAT_HEADER  # noqa: E402

SHEET_FORMAT = "setup-sheet-v1"


def _quoted(text: str) -> str:
    """A YAML string in double quotes."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def sheet_text(identifier: str, by: str, eln_file: str = None, core_files: list = (), experiments: int = None) -> str:
    """The skeleton of the setup sheet: required fields empty, everything else as a comment."""
    today = date.today().isoformat()
    by_part = f" ({by}, {today})" if by else ""
    source = _quoted(f"C: entered by {by} ({today})") if by else '""'
    short_name_source = _quoted(f"C: identifier chosen for the crate{by_part}") if by else '""'

    if core_files:
        records = "\n".join(f"    - {path}" for path in core_files)
        experiments_block = (
            "  eln_records:                                 # one core file per experiment, in the order of the experiments -\n"
            "                                               # delete the records of the export that are no experiment of this series\n"
            f"{records}\n")
    elif eln_file:
        # There is no profile for this ELN yet: the export lies in the project already, the core files come later.
        experiments_block = (
            "  eln_records: []                              # no profile for this ELN yet - once there is one:\n"
            f"                                               # python generator/workflow/eln_to_core.py projects/{identifier}/input/additional_files_for_crate/{eln_file} --out projects/{identifier}/core\n")
    else:
        experiments_block = (
            f"  conducted_experiments: {'' if experiments is None else experiments}"
            "                     # experiments conducted so far - or, with an ELN: eln_records: [core/<file>.json, ...]\n"
            "  eln_records:                                 # 'none' if the series has no ELN record\n")

    files_block = ""
    if eln_file:
        files_block = (
            "\nfiles:                                         # every file of the series; 'from' is the task that produced it ('' none)\n"
            f"  - name: {eln_file}\n"
            "    from: ''\n"
            f"    source: {_quoted('C: the export of the ELN records the crate is built from, part of the crate' + by_part)}\n")

    return f"""format: {SHEET_FORMAT}

# Setup sheet of the series {identifier}, started with generator/workflow/new_project.py on {today}.
# It holds what only a person knows about the series; the generator asks everything else.
# Walk-through: docs/new_series_guide.md. Every field and its meaning: generator/interfaces/eln/README.md
# ("Setup sheet, version 1"); a complete example: projects/amidation_ai4green_ai4_001/setup.yaml.
#
# Check the sheet at any time (it names what is still missing):
#     python generator/interfaces/eln/check_sheet.py projects/{identifier}/setup.yaml
#
# Every answer needs a source (rule 2.10): 'source' at the top holds for everything that names none of
# its own; an entry can have its own 'source' (one text, or one per field). Codes: E/X from the ELN
# (structured field / free text, quoted), R rule, L looked up, C curated (who, when), D invented for a
# demonstration. Names of people, devices, substances and reactions are those of the libraries.

source: {source}

series:
  short_name: {identifier}
  planned_experiments:                         # experiments planned in total; empty = not known
  completed: false                             # true when no further experiment will follow
{experiments_block}  description:                                 # what the series is about; empty = built from the ELN records, or asked
  source:
    short_name: {short_name_source}

people:                                        # names as in libraries/people_library.jsonld
  creator: []                                  # who planned the series
  experimenter: []                             # who performed the experiments

# none:                                        # what explicitly does not exist or is not known - a category
#   categories: []                             # missing here is asked (README: table of the categories)
#   source: ""

devices: []                                    # IDs of libraries/device_library.jsonld (an exemplar, e.g. three_neck_flask_100mL_01)

materials:                                     # the content of the devices, e.g.
#  - name: Reaction_Mixture
#    content_of: <device>
#    phases:
#      - {{name: Liquid_Phase, state: liquid, species: [<substance>, ...], dispersion: continuous, solvents: [<substance>]}}

# uncontained_streams:                         # what goes in or out through no device, e.g. one per added substance
#  - name: <Substance>_Charge
#    from: outside
#    to: <device>
#    phases:
#      - {{name: <Substance>_Phase, state: liquid, species: [<substance>], dispersion: continuous}}

# reactions: [<name in libraries/reaction_library.jsonld>]     # [] = no reaction of the library takes place

tasks:                                         # the procedure, e.g.
#  - name: Adding <substance>
#    type: transfer                            # measurement, calculation, operation, observation, transfer, ... or task
#    part_of: Preparation                      # Preparation, Main operation, Work-up (always there)
#    equipment: []
#    functions: [Charging]
#    performers: [<person>]
#    aims_at: ["<substance> from <phase> to <phase>"]
#    description: ...
#  - name: Experimental procedure              # built by the generator; its start is required
#    times: {{start: "YYYY-MM-DDTHH:MM:SS+01:00", kind: measured}}
{files_block}
# values: one entry per known value - pre-filled from the ELN with
#     python generator/workflow/prefill_sheet.py projects/{identifier}/setup.yaml
# and by hand, e.g. {{at: <material>/<phase>, of: <substance>, experiment: 1, quantity: mass, value: 1.5,
# unit: g, kind: measured, exact: true, determined_by: <task>}}
values: []
"""


def create(identifier: str, eln: Path = None, experiments: int = None, by: str = None) -> Path:
    """Create the project folder of a new series; its path."""
    identifier = crate_identifier(identifier)
    folder = path_definitions.project_folder(identifier)
    if folder.exists():
        raise SystemExit(f"{folder} exists already - a new series needs a new identifier.")
    series_files = path_definitions.series_files_folder(identifier)
    series_files.mkdir(parents=True)
    path_definitions.experiment_files_folder(identifier).mkdir(parents=True)
    (folder / "curation").mkdir()

    eln_file, core_files = None, []
    if eln is not None:
        # Only here: the ELN reader is needed only with an export.
        from workflow.eln_to_core import convert
        target = series_files / eln.name
        shutil.copy2(eln, target)
        core_folder = folder / "core"
        eln_file = eln.name
        try:
            core_files = [path.relative_to(folder).as_posix() for path in convert(target, core_folder)]
        except ValueError as error:
            # No profile for this ELN (interfaces/eln/profiles): the project is made all the same, without core files.
            print(f"No core files: {error} The export is in the project; write a profile, then run eln_to_core.py.")

    path_definitions.answer_file_path(identifier).write_text(FORMAT_HEADER + "\n", encoding="utf-8")
    path_definitions.setup_sheet_path(identifier).write_text(
        sheet_text(identifier, by, eln_file, core_files, experiments), encoding="utf-8")
    return folder


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("identifier", help="identifier of the new crate, e.g. hydrogenation_rdy_2026_09")
    start = parser.add_mutually_exclusive_group()
    start.add_argument("--eln", type=Path, help="the ELN export (.eln) the series comes from")
    start.add_argument("--experiments", type=int, help="without an ELN: how many experiments were conducted so far")
    parser.add_argument("--by", help="who fills in the sheet - for the source lines of the skeleton")
    args = parser.parse_args()
    if args.eln is not None and not args.eln.is_file():
        sys.exit(f"ELN export not found: {args.eln}")
    try:
        folder = create(args.identifier, args.eln, args.experiments, args.by)
    except ValueError as error:
        sys.exit(str(error))
    root = path_definitions.BASE_FOLDER
    print(f"\nNew series in {folder.relative_to(root).as_posix()}/. Next (docs/new_series_guide.md):")
    print("  1. people, devices, substances, reaction into the libraries (step 2 of the guide)")
    print(f"  2. fill in projects/{folder.name}/setup.yaml and check it:")
    print(f"     python generator/interfaces/eln/check_sheet.py projects/{folder.name}/setup.yaml")


if __name__ == "__main__":
    main()
