"""
Test of generator/interfaces/eln/sheet_text.py append_to_section: entries appended to an
empty section ("occurrences: []") start on a line of their own - also when the section is the
last line of its block, where "\\s*" after "[]" would take the line break along and the sheet would
read "occurrences:  - phases: null", which is not YAML.

Cases: the empty section in the middle of the sheet, at its end, with a comment behind "[]", a
section that is missing, and one that has entries already. Each time the text has to load as YAML,
with the entries under the section and the rest of the sheet unchanged. Works on temporary copies.

Run from the repository root:
    python generator/tests/sheet_text_test.py
"""
import sys
import tempfile
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from interfaces.eln.sheet_text import append_to_section  # noqa: E402

ENTRIES = [{"phases": None, "experiment": 1, "count": None}]
HEADER = "occurrences:                # header\n"
CASES = {
    "empty, in the middle": "name: x\noccurrences: []\nvalues: []\n",
    "empty, at the end": "name: x\noccurrences: []\n",
    "empty, at the end without line break": "name: x\noccurrences: []",
    "empty, with a comment": "name: x\noccurrences: []          # what is known\nvalues: []\n",
    "empty, blank lines after": "name: x\noccurrences: []\n\n\nvalues: []\n",
    "missing": "name: x\nvalues: []\n",
    "with entries": "name: x\noccurrences:\n  - reactions: null\n    experiment: 2\nvalues: []\n",
}

ok = True
with tempfile.TemporaryDirectory() as tmp:
    for label, text in CASES.items():
        path = Path(tmp) / "setup.yaml"
        path.write_text(text, encoding="utf-8")
        append_to_section(path, "occurrences", HEADER, ENTRIES)
        written = path.read_text(encoding="utf-8")
        try:
            data = yaml.safe_load(written)
            before = yaml.safe_load(text)
            wanted = (before.get("occurrences") or []) + ENTRIES
            good = (data.get("occurrences") == wanted and data.get("name") == "x"
                    and data.get("values", "-") == before.get("values", "-"))
        except yaml.YAMLError as error:
            good, written = False, f"{written}\n{error}"
        if label == "empty, with a comment":
            good &= "# what is known" in written
        ok &= good
        print(f"{'ok ' if good else 'FAIL'} {label}")
        if not good:
            print("     " + written.replace("\n", "\n     "))
print("ALL OK" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
