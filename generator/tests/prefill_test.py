"""
Test of generator/workflow/prefill_sheet.py on copies of the amidation's sheet,
written next to it (its core files are named relative to it) and removed afterwards:

1. a sheet without values gets all values of the ELN record, each with its ELN source and an empty
   reading - and check_sheet.py then reports exactly those readings as missing;
2. a second run adds nothing;
3. a value the ELN no longer agrees with is reported and left as it is;
4. a value overwritten in the sheet on purpose (its source no longer "E:") is kept and reported.

Run from the repository root:
    python generator/tests/prefill_test.py
"""
import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "generator" / "workflow"))

from prefill_sheet import prefill  # noqa: E402

SHEET = ROOT / "projects" / "amidation_ai4green_ai4_001" / "setup.yaml"
COPY = SHEET.parent / "_prefill_test_setup.yaml"


def without_values(text: str) -> str:
    return text[:re.search(r"^values:", text, flags=re.MULTILINE).start()].rstrip() + "\n"


def check(name, ok, detail=""):
    print(f"{'ok ' if ok else 'FAIL'} {name:46} {detail}")
    return ok


def main():
    text = SHEET.read_text(encoding="utf-8")
    full = yaml.safe_load(text)["values"]
    ok = True
    try:
        COPY.write_text(without_values(text), encoding="utf-8")
        first = prefill(COPY)
        added = yaml.safe_load(COPY.read_text(encoding="utf-8"))["values"]
        ok &= check("1. all ELN values added", len(first["new"]) == len(full) == len(added), f"{len(added)} of {len(full)}")
        ok &= check("   each with its ELN source, no reading",
                    all(v["source"]["value"].startswith("E:") and v.get("kind") is None for v in added))
        result = subprocess.run([sys.executable, "generator/interfaces/eln/check_sheet.py", str(COPY)],
                                capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
        missing = re.findall(r"/ kind\n", result.stdout)
        ok &= check("   check_sheet reports the readings missing", len(missing) == len(full), f"{len(missing)}")
        ok &= check("2. a second run adds nothing", not prefill(COPY)["new"])

        changed = COPY.read_text(encoding="utf-8").replace("value: 81.86", "value: 80.0", 1)
        COPY.write_text(changed, encoding="utf-8")
        report = prefill(COPY)
        ok &= check("3. a value the ELN disagrees with is reported", len(report["changed"]) == 1 and not report["new"],
                    report["changed"][0][:70] if report["changed"] else "")

        overwritten = changed.replace("value: 'E: ELN AI4Green AI4-001, results[0].value'",
                                      "value: 'C: corrects the ELN value 81.86 (test)'", 1)
        COPY.write_text(overwritten, encoding="utf-8")
        report = prefill(COPY)
        ok &= check("4. an overwritten value is kept and reported",
                    len(report["overwritten"]) == 1 and not report["changed"] and "value: 80.0" in COPY.read_text(encoding="utf-8"))
    finally:
        COPY.unlink(missing_ok=True)
    print("ALL OK" if ok else "SOME FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
