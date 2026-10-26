"""Rules for N20: NH3 moves wherever H2 moves (user, 29.09.2026) - except at the
catalyst interfaces: there only desorption into the liquid phase at the reaction interface."""
import json
import sys
from pathlib import Path

answers_path, out = Path(sys.argv[1]), Path(sys.argv[2])
entries, key = {}, None
lines = answers_path.read_text(encoding="utf-8").splitlines()
i = 0
while i < len(lines):
    line = lines[i]
    if line.startswith("key:"):
        key = line[4:].strip()
        i += 1
        while i < len(lines) and lines[i].startswith("    // "):
            i += 1
        entries[key] = lines[i] if i < len(lines) else ""
    i += 1

rules = []
CATALYST = "Catalyst_Phase"
for k, v in entries.items():
    if not k.endswith("/transferred_species"):
        continue
    names = [n.strip() for n in v.split(";") if n.strip()]
    if "Hydrogen" not in names or "Ammonia" in names:
        continue
    base = k[: -len("/transferred_species")]
    interface = base.rsplit("/", 1)[-1]
    if CATALYST in interface and interface != "phase_pair_interface:Catalyst_Phase+LiquidVessel_Phase":
        continue
    rules.append({"key": k, "answer": "; ".join(names + ["Ammonia"]), "override": True})
    if interface == "phase_pair_interface:Catalyst_Phase+LiquidVessel_Phase":
        rules.append({"key": f"{base}/transferred:Ammonia/transfer_types", "answer": "cpo:Desorption"})
        rules.append({"key": f"{base}/transferred:Ammonia/type:Desorption/adds_to_phase",
                      "answer": 'LiquidPhase "LiquidVessel_Phase"'})
        continue
    # Like hydrogen: the same transfer types and directions.
    prefix = f"{base}/transferred:Hydrogen/"
    for hk, hv in entries.items():
        if hk.startswith(prefix):
            rules.append({"key": f"{base}/transferred:Ammonia/" + hk[len(prefix):], "answer": hv})

# Reactions: NH3 desorbs at the reaction interface into the liquid phase.
for r in ("0002", "0003"):
    p = f"series:1/reaction:StoichiometricReaction_{r}/participant_transfer:StoichiometricReaction_{r}_Participant_Ammonia"
    rules.append({"key": f"{p}/phase", "answer": 'LiquidPhase "LiquidVessel_Phase"'})
    rules.append({"key": f"{p}/transfer_type", "answer": "Desorption"})
# Nothing measured: all amount gates around NH3 empty.
rules.append({"key": "series:1/*Ammonia*/quantities_*", "answer": ""})
out.write_text(json.dumps(rules, indent=1, ensure_ascii=False), encoding="utf-8")
print(len(rules), "rules;", sum(1 for r in rules if r.get("override")), "overrides:")
for r in rules:
    if r.get("override"):
        print("  ", r["key"])
