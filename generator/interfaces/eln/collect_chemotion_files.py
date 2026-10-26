"""
The files of a Chemotion series as files of the crate (the ELN export and every file of the records go
into the crate):

- the export itself (the ZIP) -> input/additional_files_for_crate/ (a file of the whole series);
- per experiment the attachments of its record (core file, "files": the analyses of the reaction and of
  its samples) and the reaction scheme the export draws for it (images/reactions/<hash>.svg)
  -> input/lab_data_for_crate/lab_data_for_crate_exp<n>/.

The experiments are the core files under series.eln_records of the sheet, in their order; each core file names
the export it was read from (source.file), which lies in input/eln/. Read straight from the ZIP (rule P-CH1:
unpacked, the image names exceed the length of a path). An attachment keeps the name it had in Chemotion; the
scheme is named after its record (LCJ-R5_reaction_scheme.svg), its path in the export is printed. Existing files
are left alone.

Usage (from the repository root):
    python generator/interfaces/eln/collect_chemotion_files.py projects/<crate_identifier>
"""
import argparse
import json
import shutil
import zipfile
from pathlib import Path

import yaml


def write_once(project: Path, target: Path, data: bytes):
    if target.exists():
        print(f"  exists: {target.relative_to(project)}")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    print(f"  written: {target.relative_to(project)}")


def collect(project: Path):
    sheet = yaml.safe_load((project / "setup.yaml").read_text(encoding="utf-8"))
    records = sheet["series"]["eln_records"]
    cores = [json.loads((project / record).read_text(encoding="utf-8")) for record in records]
    exports = {core["source"]["file"] for core in cores}
    for export_name in sorted(exports):
        export = project / "input" / "eln" / export_name
        series = project / "input" / "additional_files_for_crate" / export_name
        if not series.exists():
            series.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(export, series)
            print(f"  written: {series.relative_to(project)}")
        with zipfile.ZipFile(export) as archive:
            reactions = json.loads(archive.read("export.json"))["Reaction"]
            for nr, core in enumerate(cores, start=1):
                if core["source"]["file"] != export_name:
                    continue
                folder = project / "input" / "lab_data_for_crate" / f"lab_data_for_crate_exp{nr}"
                print(f"experiment {nr} ({core['source']['record_id']}):")
                for item in core["files"]:
                    write_once(project, folder / item["name"], archive.read(item["path"]))
                svg = reactions[core["source"]["record_uuid"]].get("reaction_svg_file")
                if svg:
                    print(f"  scheme from images/reactions/{svg}")
                    write_once(project, folder / f"{core['source']['record_id']}_reaction_scheme.svg",
                               archive.read(f"images/reactions/{svg}"))


def main():
    parser = argparse.ArgumentParser(description="Copies the export and the files of the records of a Chemotion series into its input/.")
    parser.add_argument("project", help="the project folder, projects/<crate_identifier>")
    collect(Path(parser.parse_args().project))


if __name__ == "__main__":
    main()
