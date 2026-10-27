"""
Test of generator/workflow/class_maps (docs/class_maps.html):

1. row_properties on made-up row keys: a path counts for its first property, alternatives for each, a leading ^
   is dropped, a leading step that may be left out does not count.
2. The real build: it runs (and writes docs/class_maps.html if it was out of date), --check passes right after
   it, and the data in the page hold what the rules say - cpo:Phase with its three subclasses,
   cpo:hasSolidStructure only for SolidPhase, no hidden property, every target that has a map of its own named
   by that map's class (so that the page links it).

Run from the repository root:
    python generator/tests/class_maps_test.py
"""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "generator" / "workflow" / "class_maps" / "build_class_maps.py"
sys.path.insert(0, str(SCRIPT.parent))

from build_class_maps import HTML, row_properties  # noqa: E402
from sources import load_config  # noqa: E402
from common import ClassTree  # noqa: E402

ok = True


def check(name, got, expected):
    global ok
    good = got == expected
    ok &= good
    print(f"{'ok  ' if good else 'FAIL'} {name:52} {got}" + ("" if good else f" (expected {expected})"))


# 1. Row keys
check("path counts for its first property", row_properties("cpo:madeOfMaterial / dcterms:hasPart"), ["cpo:madeOfMaterial"])
check("alternatives count for each", row_properties("(cpo:location | cpo:locatedAt)"), ["cpo:location", "cpo:locatedAt"])
check("leading ^ dropped", row_properties("(^cpo:definesForm | ^cpo:hasEnvelopeForm)"), ["cpo:definesForm", "cpo:hasEnvelopeForm"])
check("step that may be left out does not count",
      row_properties("(^cpo:addsToPhase / cpo:removesFromPhase | hlo:specializationOf)* / cpo:hasOccurrence"),
      ["cpo:hasOccurrence"])
check("sequence inside an alternative", row_properties("(cpo:a / cpo:b | cpo:c) / cpo:d"), ["cpo:a", "cpo:c"])

# 2. The real build
build = subprocess.run([sys.executable, str(SCRIPT)], cwd=ROOT, capture_output=True, text=True)
check("build runs", build.returncode, 0)
again = subprocess.run([sys.executable, str(SCRIPT), "--check"], cwd=ROOT, capture_output=True, text=True)
check("--check passes after the build", (again.returncode, again.stdout.strip()), (0, "class maps up to date"))

text = HTML.read_text(encoding="utf-8")
data = json.loads(re.search(r"^const DATA = (.*);$", text, re.M).group(1))
config = load_config()
roots = [c for f in config["families"] for c in f["classes"]]
check("a map for every family root", sorted(set(roots) - set(data)), [])
check("cpo:Phase subclasses", data["cpo:Phase"]["subclasses"], ["cpo:GasPhase", "cpo:LiquidPhase", "cpo:SolidPhase"])
solid = data["cpo:Phase"]["props"].get("cpo:hasSolidStructure", {})
check("cpo:hasSolidStructure only SolidPhase", (solid.get("only"), solid.get("only_from")), (["cpo:SolidPhase"], "domain"))
hidden = set(config["class_maps"]["hidden_properties"])
check("no hidden property", sorted({p for m in data.values() for p in m["props"] if p in hidden}), [])
# A target under a family root must be named by that root (the class with a map), not by a subclass of it.
tree = ClassTree()
unlinked = sorted({e["target"] for m in data.values() for e in m["props"].values()
                   if e["target"] and e["target"] not in data and any(tree.is_a(e["target"], r) for r in roots)})
check("every target with a map of its own is linked", unlinked, [])
check("only-chips name subclasses of the map", sorted({(c, p) for c, m in data.items() for p, e in m["props"].items()
                                                       if set(e["only"]) - set(m["subclasses"])}), [])

print("ALL OK" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
