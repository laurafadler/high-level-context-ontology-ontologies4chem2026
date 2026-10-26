"""
Counter-check (rule 7.14) for devices that hold several contents one after the other (rule 2.15): the bottle of adiponitrile of the hydrogenation is disposed of and filled again in the
inventory (workflow/inventory_tool.py dispose / prepare with "container"), and the hydrogenation is
built again in a throwaway copy each time (generator/workflow/isolated_run.py):

The content a series draws from is chosen by the start of its first experiment (read ahead from the
answer file, creation/device_functions.py: _library_contents):

1. refilled after the experiments: the old content is chosen, the run completes, the crate is the
   reference crate (only the library snapshot differs); the consistency check finds nothing new;
2. refilled before the experiments: the new content is chosen (its quantities are new questions, only
   logged), the run completes;
3. refilled between the two experiments: the old content is chosen (there at the first start), and the
   run stops - the second experiment draws from it after it ended (the limit of rule 2.15);
4. filling the bottle while it still holds its content: the inventory tool refuses.
A device with one content asks nothing (the reference run in abort mode).

Run from the repository root (several minutes; writes copies under %TEMP%/cr/content_history/<time>):
    python generator/tests/content_history_test.py
"""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(os.environ["TEMP"]) / "cr" / "content_history" / time.strftime("%Y%m%d_%H%M%S")
BOTTLE = "device:bottle_adiponitrile_01"
OLD = "material:bottle_adiponitrile_01_Content"
NEW = "material:adiponitrile_refill_01_Content"
KEY = "series:1/device:bottle_adiponitrile_01/library_content"
CRATE = Path("projects") / "hydrogenation_rdy_2026_09" / "crate" / "ro-crate-metadata.json"
failures = 0


def check(ok, label, detail=""):
    global failures
    failures += not ok
    print(f"{'ok  ' if ok else 'FAIL'} {label}" + (f" - {detail}" if detail and not ok else ""))


def rules(name: str, answer: str | None) -> Path:
    path = OUT / f"r_{name}.json"
    path.write_text(json.dumps([{"key": KEY, "answer": answer, "override": True}] if answer else []), encoding="utf-8")
    return path


def _status(copy: Path) -> str:
    report = copy / "driver_report.json"
    return json.loads(report.read_text(encoding="utf-8")).get("status") if report.exists() else "no report"


def copy_of_project(name: str) -> Path:
    """A fresh copy (isolated_run, plain run of the committed state)."""
    copy = OUT / name
    subprocess.run([sys.executable, "generator/workflow/isolated_run.py", "--answers", "projects/hydrogenation_rdy_2026_09/answers.txt", "--out", str(copy)], cwd=ROOT,
                   env=dict(os.environ, ALLOW_EARLIER_CHANGES="1"), capture_output=True, text=True)
    return copy


def run(copy: Path, rule_file: Path, *extra) -> tuple:
    answers = copy / "projects" / "hydrogenation_rdy_2026_09" / "answers.txt"
    env = dict(os.environ, ALLOW_EARLIER_CHANGES="1", ANSWER_FILE=str(answers), PYTHONPATH=str(copy / "generator"),
               PYTHONIOENCODING="utf-8")
    result = subprocess.run([sys.executable, "generator/workflow/answer_driver.py", "--rules", str(rule_file), *extra],
                            cwd=copy, env=env, capture_output=True, text=True)
    log = copy / "run.log"
    return _status(copy), (log.read_text(encoding="utf-8", errors="replace") if log.exists() else "") + result.stdout + result.stderr


def tool(copy: Path, *args, check_ok=True):
    return subprocess.run([sys.executable, "generator/workflow/inventory_tool.py", *args], cwd=copy,
                          capture_output=True, text=True, check=check_ok)


def refill(copy: Path, disposed: str, filled: str):
    """Dispose of the adiponitrile at `disposed`, fill the bottle again at `filled` (from the
    isopropanol bottle - a test, not chemistry)."""
    tool(copy, "dispose", BOTTLE, "--start", disposed, "--end", disposed.replace(":00:00Z", ":05:00Z"),
         "--description", "Test: emptied before refilling.", "--person", "person:LauraFadler")
    spec = {"name": "adiponitrile_refill_01", "container": BOTTLE, "cavity": "device:glass_bottle_250mL_Cavity",
            "person": "person:LauraFadler",
            "content": {"label": "Adiponitrile, refilled (test)", "state": "solid", "lot": "REFILL-01", "solid_structure": "cpo:Crystalline",
                        "species": [["chem:Molecule_0008", "Adiponitrile", 1.0]]},
            "sources": [{"container": "device:bottle_isopropanol_70_01", "phase": "material:bottle_isopropanol_70_01_Content_Phase"}],
            "preparation": {"name": "Refilling the adiponitrile bottle (test)", "description": "Test entry.",
                            "functions": ["cpo:Charging"], "start": filled, "end": filled.replace(":00:00Z", ":20:00Z")}}
    spec_path = copy / "refill_spec.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    tool(copy, "prepare", str(spec_path))


def inventory_sections(copy: Path) -> list:
    """The three sections of the consistency check about containers and contents, with what they report."""
    report = subprocess.run([sys.executable, "generator/workflow/check_library_consistency.py"], cwd=copy,
                            capture_output=True, text=True).stdout
    sections, current = [], None
    for line in report.splitlines():
        if line.startswith(("Devices and contents apart", "Contents of devices", "Containers of the inventory")):
            current = [line]
            sections.append(current)
        elif current is not None and line.startswith("  "):
            current.append(line.strip())
        else:
            current = None
    return sections


def library_entity(copy: Path, entity_id: str) -> dict:
    sys.path.insert(0, str(copy / "generator"))
    from helpers.library_files import read_library
    for name in ("device_library.jsonld", "material_library.jsonld"):
        for entity in read_library(copy / "libraries" / name)["@graph"]:
            if entity["@id"] == entity_id:
                return entity
    return {}


def main():
    OUT.mkdir(parents=True, exist_ok=True)

    reference = copy_of_project("reference")
    check(_status(reference) == "completed", "one content: the run asks nothing new (abort mode)", _status(reference))

    # 1. Refilled after the experiments.
    after = copy_of_project("after")
    refill(after, "2026-10-01T10:00:00Z", "2026-10-01T11:00:00Z")
    bottle = library_entity(after, BOTTLE)
    check([r["@id"] for r in bottle.get("cpo:hasContainedMaterialHistory", [])] == [OLD, NEW]
          and bottle.get("cpo:containsMaterial", {}).get("@id") == NEW,
          "refilled: history old + new, current the new one", json.dumps(bottle.get("cpo:hasContainedMaterialHistory")))
    check("cpo:materialContainedIn" not in library_entity(after, OLD), "... the old content no longer says where it is")
    # Compared with the libraries before refilling: what is reported there already does not belong to this test.
    before_refill, after_refill = inventory_sections(reference), inventory_sections(after)
    check(len(after_refill) == 3 and after_refill == before_refill,
          "... the consistency check finds nothing new", f"before {before_refill} after {after_refill}")
    status, log = run(after, rules("none", None))
    check(status == "completed" and "[content]" in log and f"{OLD} - the content it held" in log,
          "refilled after the experiments: the old content is chosen, the run completes", status)
    compared = subprocess.run([sys.executable, "generator/workflow/compare_crates.py", str(reference / CRATE), str(after / CRATE)],
                              cwd=ROOT, env=dict(os.environ, PYTHONPATH=str(ROOT / "generator")), capture_output=True, text=True).stdout
    groups = re.findall(r"^\s+\d+x\s+(\S+)", compared, flags=re.M)
    only_versions = "IDENTICAL" in compared or ("only in first:   0" in compared and "only in second:  0" in compared
                                                and set(groups) == {"schema:version"})
    check(only_versions, "... the crate is the reference crate (at most library versions differ)", compared[-1500:])
    # 2. Refilled before the experiments: the new content. Its amounts are new questions - only logged.
    before = copy_of_project("before")
    refill(before, "2026-09-13T10:00:00Z", "2026-09-13T11:00:00Z")
    status, log = run(before, rules("none", None), "--on-unknown", "log")
    check(status == "completed" and f"{NEW} - the content it held" in log and "draws from it again" not in log,
          "refilled before the experiments: the new content is chosen, the run completes", status)

    # 3. Refilled between the experiments (14.09. 13:00 and 15.09. 09:00, +01:00): the limit of rule 2.15.
    between = copy_of_project("between")
    refill(between, "2026-09-14T18:00:00Z", "2026-09-14T19:00:00Z")
    status, log = run(between, rules("none", None))
    check(status != "completed" and "draws from it again" in log,
          "refilled between the experiments: the old content is chosen, the run stops at experiment 2", status)

    # 4. Filling while something is still in it.
    full = OUT / "full_spec.json"
    full.write_text(json.dumps({"name": "x_01", "container": "device:bottle_platinum_01", "cavity": "device:glass_bottle_250mL_Cavity",
                                "person": "person:LauraFadler", "content": {"label": "x", "state": "solid", "solid_structure": "cpo:Crystalline", "lot": "x", "species": []},
                                "sources": [], "preparation": {"name": "x", "description": "x", "functions": [],
                                                               "start": "2026-10-01T11:00:00Z", "end": "2026-10-01T11:20:00Z"}}),
                    encoding="utf-8")
    result = tool(reference, "prepare", str(full), check_ok=False)
    check(result.returncode != 0 and "still holds" in (result.stdout + result.stderr), "filling a bottle that still holds its content: refused",
          result.stdout + result.stderr)

    print("ALL OK" if not failures else f"{failures} FAILED")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
