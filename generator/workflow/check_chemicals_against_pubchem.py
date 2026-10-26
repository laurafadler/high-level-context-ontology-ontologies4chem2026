"""
Read-only check of the Chemical Entity Library against PubChem: for every entry with
cpo:hasPubChemCID, compare InChIKey, InChI, molecular formula, molar mass, SMILES and CAS number
with what PubChem holds for that CID, and report the differences - so that a CID which belongs
to an entry with wrong data (or the other way round) is noticed. Changes no files except the cache.

What counts as what:
- MISMATCH: InChIKey, InChI or formula (element counts and charge) differ, the molar mass differs
  by more than 0.01 g/mol, or the CAS number is not among the CAS numbers PubChem lists for the CID.
- NOTE: the SMILES is written differently while the InChIKey agrees (same structure, other
  notation), the name differs from PubChem's title, an entry with cpo:hasNoCASNumber for which
  PubChem lists CAS numbers, and an entry with cpo:hasNoPubChemCID whose InChIKey PubChem knows.

PubChem's answers are kept in cache/pubchem/ (not versioned), so the report can be repeated
without network; --refresh asks PubChem again.

Execute (from the repository root): python generator/workflow/check_chemicals_against_pubchem.py [--refresh]
"""

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

# Runs from generator/workflow/ - the generator has to be on the search path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import path_definitions  # noqa: E402
from interfaces.pubchem.pubchem_lookup import BASE, CAS_PATTERN, _cas_valid, _get  # noqa: E402

PROPERTIES = "Title,MolecularFormula,MolecularWeight,SMILES,ConnectivitySMILES,InChI,InChIKey"
CACHE = path_definitions.EXTERNAL_VOCABULARY_CACHE.parent / "pubchem"
MASS_TOLERANCE = 0.01  # g/mol

ELEMENT = re.compile(r"([A-Z][a-z]?)(\d*)")
# Charge at the end of the molecular formula: "-", "2+", "+2", "-1" ...
CHARGE = re.compile(r"(\d*)([+-])(\d*)$")


def parse_formula(formula: str):
    """Element counts and charge of a molecular formula, independent of the order of the elements."""
    formula = formula.strip()
    charge = 0
    match = CHARGE.search(formula)
    if match:
        size = int(match.group(1) or match.group(3) or 1)
        charge = size if match.group(2) == "+" else -size
        formula = formula[:match.start()]
    counts = {}
    position = 0
    for element in ELEMENT.finditer(formula):
        if element.start() != position:
            return None
        counts[element.group(1)] = counts.get(element.group(1), 0) + int(element.group(2) or 1)
        position = element.end()
    if position != len(formula):
        return None
    return counts, charge


def _cached(name: str, url: str, refresh: bool):
    """PubChem's answer to url, from cache/pubchem/<name>.json unless refresh is set."""
    path = CACHE / f"{name}.json"
    if path.exists() and not refresh:
        return json.loads(path.read_text(encoding="utf-8"))["answer"]
    answer = _get(url)
    CACHE.mkdir(parents=True, exist_ok=True)
    record = {"url": url, "fetched": date.today().isoformat(), "answer": answer}
    path.write_bytes((json.dumps(record, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))
    return answer


def pubchem_record(cid: str, refresh: bool):
    """Properties and CAS numbers PubChem holds for a CID, or None if PubChem does not know it."""
    answer = _cached(f"cid_{cid}_properties", f"{BASE}/compound/cid/{cid}/property/{PROPERTIES}/JSON", refresh)
    found = (answer or {}).get("PropertyTable", {}).get("Properties", [])
    if not found:
        return None
    record = dict(found[0])
    synonyms = _cached(f"cid_{cid}_synonyms", f"{BASE}/compound/cid/{cid}/synonyms/JSON", refresh) or {}
    names = (synonyms.get("InformationList", {}).get("Information") or [{}])[0].get("Synonym", [])
    record["cas"] = [n for n in names if CAS_PATTERN.match(n) and _cas_valid(n)]
    return record


def cids_for_inchikey(inchikey: str, refresh: bool):
    answer = _cached(f"inchikey_{inchikey}", f"{BASE}/compound/inchikey/{inchikey}/cids/JSON", refresh)
    return [str(c) for c in (answer or {}).get("IdentifierList", {}).get("CID", []) if c]


def _id(value):
    return value.get("@id") if isinstance(value, dict) else value


def _as_list(value):
    return value if isinstance(value, list) else [value]


def molar_masses(entry: dict, graph: dict):
    """The molar-mass values of an entry (its Evidence and Reference), in g/mol."""
    actual = graph.get(_id(entry.get("cpo:hasMolarMass")))
    if not actual:
        return []
    values = []
    for key in ("hlo:hasEvidence", "hlo:hasReference"):
        for link in _as_list(actual.get(key, [])):
            value = graph.get(_id(link), {})
            unit = _id(value.get("qudt:hasUnit"))
            number = value.get("qudt:value")
            if number is None:
                continue
            number = float(number.get("@value") if isinstance(number, dict) else number)
            if unit == "unit:KiloGM-PER-MOL":
                number *= 1000
            elif unit != "unit:GM-PER-MOL":
                values.append((value["@id"], None, unit))
                continue
            values.append((value["@id"], number, unit))
    return values


def check_entry(entry: dict, graph: dict, refresh: bool):
    """Mismatches and notes for one library entry with a PubChem CID."""
    mismatches, notes = [], []
    cid = str(entry["cpo:hasPubChemCID"])
    record = pubchem_record(cid, refresh)
    if record is None:
        return [f"PubChem does not know CID {cid}"], notes

    key = entry.get("cpo:hasInChIKey")
    if key != record.get("InChIKey"):
        mismatches.append(f"InChIKey: library {key}, PubChem {record.get('InChIKey')}")
    inchi = entry.get("cpo:hasInChI")
    if inchi != record.get("InChI"):
        mismatches.append(f"InChI: library {inchi}, PubChem {record.get('InChI')}")

    formula = entry.get("cpo:hasMolecularFormula")
    ours, theirs = parse_formula(formula or ""), parse_formula(record.get("MolecularFormula", ""))
    if ours is None:
        mismatches.append(f"formula: library {formula!r} cannot be read")
    elif ours != theirs:
        mismatches.append(f"formula: library {formula}, PubChem {record.get('MolecularFormula')}")

    pubchem_mass = float(record["MolecularWeight"])
    masses = molar_masses(entry, graph)
    if not masses:
        notes.append(f"no molar-mass value in the library (PubChem {pubchem_mass} g/mol)")
    for value_id, number, unit in masses:
        if number is None:
            notes.append(f"molar mass {value_id} in {unit} - not compared")
        elif abs(number - pubchem_mass) > MASS_TOLERANCE:
            mismatches.append(f"molar mass {value_id}: library {number} g/mol, PubChem {pubchem_mass} g/mol")

    smiles = entry.get("cpo:hasSMILES")
    if smiles not in (record.get("SMILES"), record.get("ConnectivitySMILES")):
        # Without RDKit we compare SMILES only as text; the structure is decided by the InChIKey.
        text = f"SMILES written differently: library {smiles}, PubChem {record.get('SMILES')}"
        if key == record.get("InChIKey"):
            notes.append(text + " (InChIKey agrees)")
        else:
            mismatches.append(text)

    cas = entry.get("cpo:hasCAS")
    if cas and cas not in record["cas"]:
        mismatches.append(f"CAS {cas} is not among PubChem's CAS numbers for CID {cid}: {record['cas']}")
    if not cas and entry.get("cpo:hasNoCASNumber") and record["cas"]:
        notes.append(f"marked as having no CAS number, PubChem lists {record['cas']}")

    names = [n.lower() for n in _as_list(entry.get("schema:name", []))]
    if record.get("Title", "").lower() not in names:
        notes.append(f"name {entry.get('schema:name')}, PubChem title {record.get('Title')!r}")
    return mismatches, notes


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--refresh", action="store_true", help="ask PubChem again instead of using the cache")
    args = parser.parse_args()

    from helpers.library_files import read_library
    library = read_library(path_definitions.CHEMICAL_ENTITY_LIBRARY_PATH)
    graph = {entry["@id"]: entry for entry in library["@graph"]}
    entries = [e for e in graph.values() if "chebi:ChemicalEntity" in _as_list(e.get("@type", []))]

    print(f"Chemical Entity Library against PubChem ({len(entries)} chemical entities)\n")
    total_mismatches = 0
    without = []
    for entry in entries:
        label = f"{entry['@id']} ({', '.join(_as_list(entry.get('schema:name', '?')))})"
        if "cpo:hasPubChemCID" not in entry:
            key = entry.get("cpo:hasInChIKey")
            if entry.get("cpo:hasNoPubChemCID") and key:
                cids = cids_for_inchikey(key, args.refresh)
                if cids:
                    print(f"NOTE      {label}: marked as having no CID, PubChem knows InChIKey {key} as CID {', '.join(cids)}")
                    continue
            without.append(label)
            continue
        mismatches, notes = check_entry(entry, graph, args.refresh)
        total_mismatches += len(mismatches)
        status = "MISMATCH" if mismatches else "ok"
        print(f"{status:9} {label}, CID {entry['cpo:hasPubChemCID']}")
        for line in mismatches:
            print(f"            ! {line}")
        for line in notes:
            print(f"            - {line}")

    print(f"\nNot compared (no CID): {len(without)}")
    for label in without:
        print(f"            {label}")
    print(f"\n{total_mismatches} mismatch(es). PubChem answers cached in {CACHE}.")
    sys.exit(1 if total_mismatches else 0)


if __name__ == "__main__":
    main()
