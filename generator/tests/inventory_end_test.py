"""
Counter-check (rule 7.14) for contents used up in a run (rule 7.17,
creation/device_usage_functions.py: ask_emptied_containers, _settle_content_ends). Each case is a
real run of the hydrogenation in a throwaway copy (generator/workflow/isolated_run.py), with the
"empties" answer of Adding the solid RDY overridden:

1. used up in experiment 1 - experiment 2 draws from the bottle again: the run stops, nothing written;
2. used up in experiment 2: the content's acquisition occurrence ends with the end of that task;
   a second run in the same copy changes nothing (idempotent); a third run without the mark puts
   the empty end back and the bottle contains its content again - material and device library are
   again byte for byte what they were;
3. disposed of in the inventory (workflow/inventory_tool.py dispose) before the experiments: the
   run stops.

Run from the repository root (a few minutes; writes copies under %TEMP%/cr/inventory_end/<time>):
    python generator/tests/inventory_end_test.py
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "generator"))    # helpers.library_files (libraries in two files)
# A fresh folder per run: old copies cannot always be deleted on Windows, and isolated_run
# refuses to copy into an existing folder.
OUT = Path(os.environ["TEMP"]) / "cr" / "inventory_end" / time.strftime("%Y%m%d_%H%M%S")
KEY = "series:1/experiment:{}/task:Adding_the_solid_RDY/empties"
OPTION = "bottle adiponitrile 01 ExperimentSpecific {}"
OCCURRENCE = "material:bottle_adiponitrile_01_Content_Phase_Occurrence"
failures = 0


def check(ok, label, detail=""):
    global failures
    failures += not ok
    print(f"{'ok  ' if ok else 'FAIL'} {label}" + (f" - {detail}" if detail and not ok else ""))


def rules(path: Path, experiment_one: str, experiment_two: str) -> Path:
    path.write_text(json.dumps([{"key": KEY.format(1), "answer": experiment_one, "override": True},
                                {"key": KEY.format(2), "answer": experiment_two, "override": True}]), encoding="utf-8")
    return path


def isolated(name: str, rule_file: Path, before=None) -> tuple:
    """A fresh copy; `before(copy)` runs in it first. Returns (copy, exit code, log text)."""
    copy = OUT / name
    env = dict(os.environ, ALLOW_EARLIER_CHANGES="1")
    if before is None:
        result = subprocess.run([sys.executable, "generator/workflow/isolated_run.py", "--answers", "projects/hydrogenation_rdy_2026_09/answers.txt", "--out", str(copy), "--",
                                 "--rules", str(rule_file)], cwd=ROOT, env=env, capture_output=True, text=True)
        return copy, _driver_status(copy), (copy / "run.log").read_text(encoding="utf-8", errors="replace") + result.stdout
    # First create the copy (a run without settings), then prepare it and start the driver in it.
    subprocess.run([sys.executable, "generator/workflow/isolated_run.py", "--answers", "projects/hydrogenation_rdy_2026_09/answers.txt", "--out", str(copy)], cwd=ROOT, env=env,
                   capture_output=True, text=True)
    before(copy)
    return rerun(copy, rule_file)


def rerun(copy: Path, rule_file: Path) -> tuple:
    answers = copy / "projects" / "hydrogenation_rdy_2026_09" / "answers.txt"
    env = dict(os.environ, ALLOW_EARLIER_CHANGES="1", ANSWER_FILE=str(answers), PYTHONPATH=str(copy / "generator"),
               PYTHONIOENCODING="utf-8")
    result = subprocess.run([sys.executable, "generator/workflow/answer_driver.py", "--rules", str(rule_file)],
                            cwd=copy, env=env, capture_output=True, text=True)
    return copy, _driver_status(copy), result.stdout + result.stderr


def _driver_status(copy: Path) -> str:
    report = copy / "driver_report.json"
    return json.loads(report.read_text(encoding="utf-8")).get("status") if report.exists() else "no report"


def _library(copy: Path) -> dict:
    """The material library of the copy (the contents), main
    file and details joined."""
    from helpers.library_files import read_library
    return read_library(copy / "libraries" / "material_library.jsonld")


def _library_bytes(root: Path) -> bytes:
    """Both files of the material and of the device library, to see whether a run wrote anything - the
    end of a content in the one (rule 2.15) the current content of the bottle in the
    other."""
    from helpers.library_files import details_path
    found = b""
    for name in ("material_library.jsonld", "device_library.jsonld"):
        path = root / "libraries" / name
        found += path.read_bytes() + (details_path(path).read_bytes() if details_path(path).exists() else b"")
    return found


def occurrence_end(copy: Path):
    graph = _library(copy)["@graph"]
    occurrence = next(e for e in graph if e["@id"] == OCCURRENCE)
    return occurrence.get("cpo:hasEndTime", {}).get("@id"), {e["@id"] for e in graph}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    original = _library_bytes(ROOT)

    # 1. Used up in experiment 1, experiment 2 draws from it again.
    copy, status, log = isolated("exp1", rules(OUT / "r_exp1.json", OPTION.format(1), ""))
    check(status != "completed" and "draws from it again" in log, "used up in experiment 1, drawn from in 2: the run stops",
          f"status {status}")
    check(_library_bytes(copy) == original, "... and nothing is written")

    # 2. Used up in experiment 2.
    copy, status, log = isolated("exp2", rules(OUT / "r_exp2.json", "", OPTION.format(2)))
    end, ids = occurrence_end(copy)
    check(status == "completed", "used up in experiment 2: the run completes", f"status {status}")
    check(bool(end) and end.startswith("crate:hydrogenation_rdy_2026_09/Task_Adding_the_solid_RDY") and end.endswith("ExperimentSpecific_2"),
          "... the content ends with the end of Adding the solid RDY in experiment 2", f"end {end}")
    check(f"{OCCURRENCE}_EndTime" not in ids, "... the empty end is gone")
    from helpers.library_files import read_library
    bottle = next(e for e in read_library(copy / "libraries" / "device_library.jsonld")["@graph"]
                  if e["@id"] == "device:bottle_adiponitrile_01")
    content = next(e for e in _library(copy)["@graph"] if e["@id"] == "material:bottle_adiponitrile_01_Content")
    check("cpo:containsMaterial" not in bottle and "cpo:materialContainedIn" not in content
          and bottle.get("cpo:hasContainedMaterialHistory") == [{"@id": "material:bottle_adiponitrile_01_Content"}],
          "... the bottle no longer contains it, it stays in the history (rule 2.15)")
    after_first = _library_bytes(copy)
    _, status, _ = rerun(copy, OUT / "r_exp2.json")
    check(status == "completed" and _library_bytes(copy) == after_first,
          "... a second run changes nothing")
    _, status, _ = rerun(copy, rules(OUT / "r_none.json", "", ""))
    check(status == "completed" and _library_bytes(copy) == original,
          "... without the mark material and device library are as before")

    # 3. Disposed of in the store before the experiments took place.
    def dispose(copy):
        subprocess.run([sys.executable, "generator/workflow/inventory_tool.py", "dispose", "device:bottle_adiponitrile_01",
                        "--start", "2026-09-13T10:00:00Z", "--end", "2026-09-13T10:05:00Z", "--description", "Test.",
                        "--person", "person:LauraFadler"],
                       cwd=copy, capture_output=True, text=True, check=True)
    _, status, log = isolated("disposed", rules(OUT / "r_none.json", "", ""), before=dispose)
    check(status != "completed" and "ended on 2026-09-13" in log, "disposed of before the experiments: the run stops",
          f"status {status}")

    print("ALL OK" if not failures else f"{failures} FAILED")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
