"""
Counter-test of generator/workflow/open_questions.py --write-sheet: open questions about
the values of a library device's content become empty values whose "at" check_sheet.py accepts - the
content with its own path (device:D/material:C, material:C/phase:P), not under the device and not
without its prefixes.

The hydrogenation's sheet is copied next to itself without the entries about the hydrogen cylinder's
content; the open questions of a run are put to write_sheet, the new entries are compared with the
form written by hand, and the copy has to pass check_sheet.py. The copy is removed afterwards.

Run from the repository root:
    python generator/tests/open_questions_write_test.py
"""
import subprocess
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from workflow.open_questions import write_sheet  # noqa: E402

src = Path("projects/hydrogenation_rdy_2026_09/setup.yaml")
copy = src.parent / "_open_questions_test.yaml"
CONTENT = "h2_cylinder_01_Content"
data = yaml.safe_load(src.read_text(encoding="utf-8"))
data["unknown"] = [u for u in data.get("unknown") or [] if CONTENT not in str(u.get("at"))]
data["values"] = [v for v in data.get("values") or [] if CONTENT not in str(v.get("at"))]


class _Indented(yaml.SafeDumper):
    # Lists indented as in the sheet ("  - at: ...") - that way append_to_section appends in the right place.
    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow, False)


copy.write_text(yaml.dump(data, Dumper=_Indented, allow_unicode=True, sort_keys=False, width=200), encoding="utf-8")

stand_ins = [
    {"key": f"series:1/device:h2_cylinder_01/material:{CONTENT}/quantities_with_evidence",
     "prompt": "For which quantities of the content is there evidence? [volume] (several, separated by ;)"},
    {"key": f"series:1/material:{CONTENT}/phase:{CONTENT}_Phase/quantities_with_evidence",
     "prompt": "For which quantities of the phase is there evidence? [temperature, pressure] (several, separated by ;)"},
]
wanted = {f"device:h2_cylinder_01/material:{CONTENT}": {"volume"},
          f"material:{CONTENT}/phase:{CONTENT}_Phase": {"temperature", "pressure"}}
ok = True
try:
    write_sheet(stand_ins, copy)
    written = yaml.safe_load(copy.read_text(encoding="utf-8"))
    found = {}
    for value in written.get("values") or []:
        if CONTENT in str(value.get("at")) or value.get("at") == "h2_cylinder_01":
            found.setdefault(value["at"], set()).add(value["quantity"])
    for at, quantities in wanted.items():
        good = found.get(at) == quantities
        ok &= good
        print(f"{'ok ' if good else 'FAIL'} {at:70} {sorted(found.get(at, []))}")
    stray = set(found) - set(wanted)
    ok &= not stray
    print(f"{'ok ' if not stray else 'FAIL'} {'no value under another place':70} {sorted(stray)}")
    # The empty values are open - check_sheet.py reports them, but not their place.
    r = subprocess.run([sys.executable, "generator/interfaces/eln/check_sheet.py", str(copy)],
                       capture_output=True, text=True, encoding="utf-8")
    bad_place = [line.strip() for line in r.stdout.splitlines() if CONTENT in line and "value" not in line.lower()]
    ok &= not bad_place
    print(f"{'ok ' if not bad_place else 'FAIL'} {'check_sheet.py knows the places':70} {bad_place[:2]}")
finally:
    copy.unlink()

# A list question whose hint stands before the options (cross_material_pairs): the
# entry has to say "several", or check_sheet.py takes an answer with one pair for an option that does not exist.
from workflow.open_questions import sheet_entry  # noqa: E402
entry = sheet_entry({"key": "series:1/cross_material_pairs", "prompt":
                     "[hlo:SeriesSpecific] Which further Phase Interfaces between phases of different materials have not been "
                     "recorded yet? Each as 'phase + phase', separated by ';' (leave empty if none) [GasPhase \"A\", GasPhase \"B\"]"})
good = entry.get("several") is True and not entry.get("required")
ok &= good
print(f"{'ok ' if good else 'FAIL'} {'list hint before the options: several, not required':70} {entry.get('several')}")
# The times of a task that only a value's determined_by brings into the crate: the generator asks them at a
# placeholder (task:for-<value>), the sheet holds them at the sheet task the value names. The PBA sheet is
# copied without the 'unknown' entries of 'Assuming the manganese(II) concentration'; the open list of its
# times becomes empty values at that task.
pba = Path("projects/pba_synthesis/setup.yaml")
pba_copy = pba.parent / "_open_questions_test.yaml"
TASK = "Assuming the manganese(II) concentration"
text = pba.read_text(encoding="utf-8")
lines = text.split("\n")
kept, skip = [], False
for line in lines:
    if line.startswith("  - "):
        skip = line == f"  - at: task:{TASK}"
    if not skip:
        kept.append(line)
removed = len(lines) - len(kept)
pba_copy.write_text("\n".join(kept), encoding="utf-8")
placeholder = "for-Concentration_Manganese2PlusIon_Phase_Manganese_Pour_Phase_Reference_1_ExperimentSpecific"
try:
    write_sheet([{"key": f"series:1/experiment:1/task:{placeholder}/quantities_with_evidence",
                  "prompt": f"[hlo:ExperimentSpecific] For which quantities of {TASK} is there direct measurement or "
                            "observation evidence? [start_time, end_time, duration] (several separated by ';', leave empty for none)"}],
                pba_copy)
    written = yaml.safe_load(pba_copy.read_text(encoding="utf-8"))
    found = {(v.get("experiment"), v.get("quantity")) for v in written.get("values") or []
             if v.get("at") == f"task:{TASK}" and v.get("value") is None}
    good = removed > 0 and found == {(1, "start_time"), (1, "end_time"), (1, "duration")}
    ok &= good
    print(f"{'ok ' if good else 'FAIL'} {'times of a placeholder task: empty values at the sheet task':70} {sorted(found)}")
finally:
    pba_copy.unlink()

print("ALL OK" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
