"""
Counter-test of generator/interfaces/eln/sheet_names.py: how the setup sheet names
transfers and interfaces, and how the adapter matches them against the generator's names.

Run from the repository root:
    python generator/tests/sheet_names_test.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from interfaces.eln.sheet_names import (experiments_of, id_forms_of_place, interface_forms, place_matches,  # noqa: E402
                                        transfer_matches)

LABEL = "Hydrogen-PortCrossing-from-Sparger_Inlet_Phase-to-Sparger_Phase"
HYPHEN = "6-Iminocapronitrile-PortCrossing-from-LiquidVessel_Phase-to-Sample_Transfer_Phase"
INTERFACE = "PhasePairInterface_Phase_GasVessel_Phase_L109_Air_GasPhase"

cases = [
    ("readable transfer", transfer_matches("Hydrogen from Sparger_Inlet_Phase to Sparger_Phase", LABEL), True),
    ("full generator name", transfer_matches(LABEL, LABEL), True),
    ("other direction is another transfer", transfer_matches("Hydrogen from Sparger_Phase to Sparger_Inlet_Phase", LABEL), False),
    ("other species", transfer_matches("Water from Sparger_Inlet_Phase to Sparger_Phase", LABEL), False),
    ("species with a hyphen", transfer_matches("6-Iminocapronitrile from LiquidVessel_Phase to Sample_Transfer_Phase", HYPHEN), True),
    ("species written with a comma", transfer_matches("N,N-Dimethylformamide from DMF_Phase to Liquid_Phase",
                                                       "NN-Dimethylformamide-PortCrossing-from-DMF_Phase-to-Liquid_Phase"), True),
    # Two transfers of different types between the same phases: the readable name fits both - the
    # adapter then does not answer (exactly one hit is required), the exploratory run shows the question.
    ("readable name fits both types", sum(transfer_matches("Ammonia from LiquidVessel_Phase to Catalyst_Phase", label) for label in (
        "Ammonia-Adsorption-from-LiquidVessel_Phase-to-Catalyst_Phase",
        "Ammonia-Solidification-from-LiquidVessel_Phase-to-Catalyst_Phase")), 2),
    ("interface 'A / B' with a phase of the room", INTERFACE.lower().replace("_", "") in interface_forms("GasVessel_Phase / L109_Air_GasPhase"), True),
    ("interface in the other order", place_matches("L109_Air_GasPhase / GasVessel_Phase", INTERFACE), True),
    ("interface by its full name", place_matches(INTERFACE, INTERFACE), True),
    ("port", place_matches("vessel001_opening", "vessel001_opening"), True),
    ("another port", place_matches("vessel001_opening", "vessel001_lid_sampling_port"), False),
    ("interface in an ID", INTERFACE.lower() in id_forms_of_place("GasVessel_Phase / L109_Air_GasPhase"), True),
    ("experiment all", experiments_of("all", 2), [1, 2]),
    ("experiment missing = all", experiments_of(None, 3), [1, 2, 3]),
    ("experiment list", experiments_of([2], 2), [2]),
]
ok = True
for name, got, wanted in cases:
    good = got == wanted
    ok &= good
    print(f"{'ok ' if good else 'FAIL'} {name:44} {got!r}")
print("ALL OK" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
