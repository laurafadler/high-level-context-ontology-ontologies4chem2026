"""
Look substances up on PubChem and keep the answers in a file. Only looks up and writes
that file - it never writes a library. A library entry is made afterwards, either from this
file by a library tool or by hand.

For every substance, given as NAME=SMILES: PubChem CID, title, IUPAC name, molecular formula,
molecular weight, connectivity SMILES, InChI, InChIKey and the CAS-like numbers among the
synonyms (cas_candidates - choosing one is left to a person). A substance PubChem does not
know is written with "found": false and nothing else; nothing is guessed.

Usage (from the repository root):
    python generator/interfaces/pubchem/pubchem_lookup.py --out <file.json> "HOAt=On1nnc2cccnc21" "Tetramethylurea=CN(C)C(=O)N(C)C"
"""
import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
PROPERTIES = "Title,IUPACName,MolecularFormula,MolecularWeight,ConnectivitySMILES,InChI,InChIKey"
CAS_PATTERN = re.compile(r"^\d{2,7}-\d\d-\d$")


def _get(url: str, data: dict = None):
    body = urllib.parse.urlencode(data).encode() if data else None
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=body), timeout=30) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise
    finally:
        # PubChem allows at most 5 requests per second.
        time.sleep(0.3)


def _cas_valid(number: str) -> bool:
    """The check digit of a CAS number (last digit = weighted sum of the others mod 10)."""
    digits = number.replace("-", "")
    return sum(int(d) * (i + 1) for i, d in enumerate(reversed(digits[:-1]))) % 10 == int(digits[-1])


def look_up(name: str, smiles: str) -> dict:
    row = {"name": name, "query_smiles": smiles, "looked_up": date.today().isoformat()}
    answer = _get(f"{BASE}/compound/smiles/property/{PROPERTIES}/JSON", {"smiles": smiles})
    found = (answer or {}).get("PropertyTable", {}).get("Properties", [])
    # CID 0 means at PubChem: structure valid, but no compound in the database.
    found = [p for p in found if p.get("CID")]
    if not found:
        row["found"] = False
        return row
    if len(found) > 1:
        row["other_cids"] = [p["CID"] for p in found[1:]]
    row.update({"found": True, **found[0]})
    synonyms = _get(f"{BASE}/compound/cid/{row['CID']}/synonyms/JSON") or {}
    names = (synonyms.get("InformationList", {}).get("Information") or [{}])[0].get("Synonym", [])
    row["cas_candidates"] = [n for n in names if CAS_PATTERN.match(n) and _cas_valid(n)]
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("substances", nargs="+", help="NAME=SMILES")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    rows = []
    for item in args.substances:
        name, separator, smiles = item.partition("=")
        if not separator or not smiles:
            sys.exit(f"'{item}' is not NAME=SMILES.")
        row = look_up(name.strip(), smiles.strip())
        rows.append(row)
        if row["found"]:
            print(f"{row['name']}: CID {row['CID']}, {row['MolecularFormula']}, {row['InChIKey']}, CAS {row['cas_candidates']}")
        else:
            print(f"{row['name']}: not found on PubChem")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes((json.dumps(rows, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))
    print(f"-> {args.out}")


if __name__ == "__main__":
    main()
