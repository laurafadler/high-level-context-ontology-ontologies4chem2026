"""
Counter-test of generator/interfaces/eln/check_sheet.py: the amidation's setup sheet
has to pass, and every copy damaged in one way has to be reported (exit code 1). The copy is
written next to the sheet (its core files are named relative to it) and removed afterwards.

Run from the repository root:
    python generator/tests/sheet_check_test.py
"""
import copy
import subprocess
import sys
from pathlib import Path

import yaml

src = Path("projects/amidation_ai4green_ai4_001/setup.yaml")
base = yaml.safe_load(src.read_text(encoding="utf-8"))


def task(d, name):
    return next(t for t in d["tasks"] if t["name"] == name)


# A valid statement about an occurrence - the cases below damage it in one place each.
OCCURRENCE = {"reactions": ["Amidation of benzoic acid with ethylamine"],
              "transfers": {"flask_50mL_01_opening": ["Benzoic acid from Benzoic_Acid_Phase to Liquid_Phase"]},
              "experiment": "all", "count": 1, "kind": "observed", "determined_by": "Mixing at room temperature",
              "source": "D: counter-test"}


cases = {
 "solid without structure": lambda d: d["materials"][1]["phases"][0].pop("structure"),
 "typo in field": lambda d: d["materials"][0]["phases"][0].update({"dispersoin": "continuous"}),
 # An old name of the section uncontained_streams - not read.
 "old section feeds": lambda d: d.update({"feeds": d.pop("uncontained_streams")}),
 "unknown device": lambda d: d["devices"].append("flask_999"),
 "species typo": lambda d: d["materials"][0]["phases"][0]["species"].append("Benzoic acdi"),
 "procedure without times": lambda d: task(d, "Experimental procedure").pop("times"),
 "calculation without inputs": lambda d: task(d, "Calculating the yield").pop("inputs"),
 # Every function is selectable; a removed one is unknown.
 "removed function": lambda d: task(d, "Washing with aqueous sodium chloride").update({"functions": ["SeparatingByGravity"]}),
 # A function the class of the task does not offer (cpo:offersFunction).
 "function not offered": lambda d: task(d, "Mixing at room temperature").update({"functions": ["Mixing", "TransferringMaterial"]}),
 # Substances of only some experiments: a name of the library, numbers of the series' experiments.
 "species of unknown name": lambda d: d.update({"species_per_experiment": {"Benzoic acdi": [1]}}),
 "species in a 2nd experiment": lambda d: d.update({"species_per_experiment": {"Benzoic acid": [2]}}),
 "unknown person": lambda d: d["people"].update({"creator": ["Jane Doe"]}),
 "part_of unknown task": lambda d: task(d, "Mixing at room temperature").update({"part_of": "Reaction at RT"}),
 # A task the generator creates as determiner: the planning only of planned values (Chemotion).
 "planning determines a measurement": lambda d: next(v for v in d["values"] if v["kind"] == "measured").update(
     {"determined_by": "Planning the series"}),
 "work-up determines a value": lambda d: next(v for v in d["values"] if v["kind"] == "planned").update(
     {"determined_by": "Work-up"}),
 "value without reading": lambda d: next(v for v in d["values"] if v["quantity"] == "selectivity").pop("kind"),
 "number without unit": lambda d: next(v for v in d["values"] if v["quantity"] == "temperature").pop("unit"),
 "value at unknown place": lambda d: d["values"][0].update({"at": "Benzoic_Acid_Charge/Solid_Phase"}),
 "value of unknown substance": lambda d: next(v for v in d["values"] if v.get("of")).update({"of": "Benzoic acdi"}),
 "bad state": lambda d: d["uncontained_streams"][0]["phases"][0].update({"state": "powder"}),
 "source for unknown field": lambda d: task(d, "Calculating the yield")["source"].update({"inputz": "x"}),
 "input without a value": lambda d: task(d, "Calculating the selectivity").update({"inputs": ["Conversion NEthylbenzamide"]}),
 "input of an unknown value": lambda d: next(v for v in d["values"] if v["quantity"] == "yield").update({"kind": "none"}),
 "settings of unknown device": lambda d: d.update({"device_settings": [{"device": "flask_999", "operation_mode": "Batch"}]}),
 # A set profile is a value with "steps" (kind set), not device_settings.profiles.
 "profile setting gone": lambda d: d.update({"device_settings": [{"device": d["devices"][0], "profiles": []}]}),
 "profile step without kind": lambda d: d["values"].append({"at": "Reaction_Mixture/Liquid_Phase", "experiment": 1, "quantity": "temperature",
     "kind": "set", "unit": "DEG_C", "steps": [{"value": 20}], "determined_by": "Mixing at room temperature"}),
 "profile run by unknown task": lambda d: d["values"].append({"at": "Reaction_Mixture/Liquid_Phase", "experiment": 1, "quantity": "temperature",
     "kind": "set", "unit": "DEG_C", "steps": [{"kind": "hold", "value": 20}], "executed_by": ["Stiring"],
     "determined_by": "Mixing at room temperature"}),
 "file from unknown task": lambda d: d.update({"files": [{"name": "x.xlsx", "from": "Reaction at RT"}]}),
 "file without its source": lambda d: d.update({"files": [{"name": "x.xlsx"}]}),
 "sample of unknown material": lambda d: d["materials"][0].update({"sample_of": "Reaction Mix"}),
 # Occurrences and task times in the sheet
 "occurrence without count": lambda d: d.update({"occurrences": [dict(OCCURRENCE, count=None)]}),
 "occurrence of unknown kind": lambda d: d.update({"occurrences": [dict(OCCURRENCE, kind="seen")]}),
 "occurrence by unknown task": lambda d: d.update({"occurrences": [dict(OCCURRENCE, determined_by="Watching")]}),
 "transfer in a bad form": lambda d: d.update({"occurrences": [dict(OCCURRENCE, transfers={
     "flask_50mL_01_opening": ["benzoic acid into the flask"]})]}),
 "task time without unit": lambda d: d["values"].append({"at": "task:Mixing at room temperature", "experiment": 1,
                                                          "quantity": "duration", "value": 120, "kind": "measured"}),
}
r = subprocess.run([sys.executable, "generator/interfaces/eln/check_sheet.py", str(src)], capture_output=True, text=True, encoding="utf-8")
ok = r.returncode == 0
print(f"{'ok ' if ok else 'FAIL'} {'undamaged sheet passes':28} {r.stdout.strip()[:120]}")
# The sheet also passes with a valid statement about occurrences and a task time.
d = copy.deepcopy(base)
d["occurrences"] = [OCCURRENCE]
d["values"].append({"at": "task:Mixing at room temperature", "experiment": 1, "quantity": "duration", "value": 120,
                    "unit": "MIN", "kind": "measured", "determined_by": "Mixing at room temperature"})
valid = src.parent / "_counter_setup.yaml"
valid.write_text(yaml.safe_dump(d, allow_unicode=True, sort_keys=False), encoding="utf-8")
r = subprocess.run([sys.executable, "generator/interfaces/eln/check_sheet.py", str(valid)], capture_output=True, text=True, encoding="utf-8")
ok &= r.returncode == 0
print(f"{'ok ' if r.returncode == 0 else 'FAIL'} {'valid occurrence passes':28} {r.stdout.strip()[:150]}")
for name, damage in cases.items():
    d = copy.deepcopy(base); damage(d)
    out = src.parent / "_counter_setup.yaml"
    out.write_text(yaml.safe_dump(d, allow_unicode=True, sort_keys=False), encoding="utf-8")
    r = subprocess.run([sys.executable, "generator/interfaces/eln/check_sheet.py", str(out)], capture_output=True, text=True, encoding="utf-8")
    found = r.returncode == 1
    ok &= found
    print(f"{'ok ' if found else 'MISS'} {name:28} {' | '.join(l.strip() for l in r.stdout.strip().splitlines()[:4])[:150]}")
# Rule 1.7: a task name without a gerund is a warning - reported, but exit code 0.
d = copy.deepcopy(base)
task(d, "Mixing at room temperature")["name"] = "Mix at room temperature"
d["values"] = [v for v in d["values"] if v.get("determined_by") != "Mixing at room temperature"]
out.write_text(yaml.safe_dump(d, allow_unicode=True, sort_keys=False), encoding="utf-8")
r = subprocess.run([sys.executable, "generator/interfaces/eln/check_sheet.py", str(out)], capture_output=True, text=True, encoding="utf-8")
warned = "Warning (1)" in r.stdout and "Mix at room temperature" in r.stdout
ok &= warned
print(f"{'ok ' if warned else 'MISS'} {'task name without a gerund':28} exit {r.returncode} | {' | '.join(l.strip() for l in r.stdout.strip().splitlines()[-3:])[:150]}")
# Possible reactions: a fixed reaction of the library the sheet does not name, all of whose reactants
# stand in one phase, is suggested as a warning - not when its reactants occur only in different experiments.
REACTION = "Amidation of benzoic acid with ethylamine"
d = copy.deepcopy(base)
d["reactions"] = []
d["occurrences"] = [s for s in d.get("occurrences") or [] if REACTION not in str(s)]
out.write_text(yaml.safe_dump(d, allow_unicode=True, sort_keys=False), encoding="utf-8")
r = subprocess.run([sys.executable, "generator/interfaces/eln/check_sheet.py", str(out)], capture_output=True, text=True, encoding="utf-8")
suggested = "reactions (suggestion)" in r.stdout and REACTION in r.stdout
ok &= suggested
print(f"{'ok ' if suggested else 'MISS'} {'reaction not named':28} exit {r.returncode} | "
      f"{' | '.join(l.strip() for l in r.stdout.splitlines() if 'suggestion' in l)[:150]}")
d["species_per_experiment"] = {"Benzoic acid": [1], "Ethylamine": [2]}
out.write_text(yaml.safe_dump(d, allow_unicode=True, sort_keys=False), encoding="utf-8")
r = subprocess.run([sys.executable, "generator/interfaces/eln/check_sheet.py", str(out)], capture_output=True, text=True, encoding="utf-8")
apart = "reactions (suggestion)" not in r.stdout
ok &= apart
print(f"{'ok ' if apart else 'FAIL'} {'reactants never together':28} no suggestion")
out.unlink()
print("ALL OK" if ok else "SOME MISSED")
sys.exit(0 if ok else 1)
