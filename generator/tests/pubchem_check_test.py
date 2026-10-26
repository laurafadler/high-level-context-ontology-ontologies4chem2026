"""Counter-checks for generator/workflow/check_chemicals_against_pubchem.py.

Takes real library entries, spoils one field at a time in memory and expects a mismatch; a
formula in another order or a SMILES in another notation must not be one. Uses only the
PubChem answers in cache/pubchem/ - run the check itself once before.

Run from the repository root:
    python generator/tests/pubchem_check_test.py
"""
# Runs from generator/tests/ - the generator has to be on the search path.
import copy
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "workflow"))
import path_definitions  # noqa: E402
import check_chemicals_against_pubchem as check  # noqa: E402


def run():
    ok = True

    def expect(label, entry_id, change, mismatch):
        nonlocal ok
        graph = copy.deepcopy(base)
        change(graph[entry_id], graph)
        mismatches, _ = check.check_entry(graph[entry_id], graph, refresh=False)
        passed = bool(mismatches) == mismatch
        if not passed:
            ok = False
        print(f"  {label:62s} [{'OK' if passed else 'WRONG'}]")
        if not passed:
            print(f"      messages: {mismatches}")

    def set_field(field, value):
        def change(entry, graph):
            entry[field] = value
        return change

    def set_mass(value):
        def change(entry, graph):
            actual = graph[entry["cpo:hasMolarMass"]["@id"]]
            graph[actual["hlo:hasEvidence"]["@id"]]["qudt:value"]["@value"] = value
        return change

    from helpers.library_files import read_library
    library = read_library(path_definitions.CHEMICAL_ENTITY_LIBRARY_PATH)
    base = {entry["@id"]: entry for entry in library["@graph"]}

    expect("unchanged: no deviation", "chem:Molecule_0008", lambda e, g: None, False)
    expect("InChIKey of another substance", "chem:Molecule_0008",
           set_field("cpo:hasInChIKey", "UFHFLCQGNIYNRP-UHFFFAOYSA-N"), True)
    expect("InChI verfaelscht", "chem:Molecule_0008", set_field("cpo:hasInChI", "InChI=1S/H2/h1H"), True)
    expect("formula with a wrong count", "chem:Molecule_0008", set_field("cpo:hasMolecularFormula", "C6H9N2"), True)
    expect("formula in another order is no deviation", "chem:Molecule_0008",
           set_field("cpo:hasMolecularFormula", "N2C6H8"), False)
    expect("charge forgotten (PF6 instead of PF6-)", "chem:Hexafluorophosphate",
           set_field("cpo:hasMolecularFormula", "PF6"), True)
    expect("charge written differently (F6P-1)", "chem:Hexafluorophosphate",
           set_field("cpo:hasMolecularFormula", "F6P-1"), False)
    expect("molar mass off by 1 g/mol", "chem:Molecule_0008", set_mass("109.14"), True)
    expect("CAS of another substance", "chem:Molecule_0008", set_field("cpo:hasCAS", "7732-18-5"), True)
    expect("SMILES written differently, the same substance", "chem:Molecule_0008",
           set_field("cpo:hasSMILES", "C(CC#N)CCC#N"), False)
    expect("SMILES and InChIKey of another substance", "chem:Molecule_0008",
           lambda e, g: e.update({"cpo:hasSMILES": "O", "cpo:hasInChIKey": "XLYOFNOQVPJJNP-UHFFFAOYSA-N"}), True)

    print(f"\n{'ALL TESTS OK' if ok else 'ERRORS - see WRONG above'}")
    return ok


if __name__ == "__main__":
    raise SystemExit(0 if run() else 1)
