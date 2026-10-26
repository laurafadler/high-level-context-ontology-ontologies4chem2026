"""
Coverage report of an answer file: how many answers come from where (rule 2.10).

Counts the code of every "// source: <code>: <text>" line (E ELN structured, X extracted from free
text, R fixed translation rule, L looked up, C curated, D invented for the demonstration, M
missing); an answer without such a line counts as "?" (unknown - typed in, or older than the
source lines). Answers are also split into empty and non-empty, because an empty answer ("nothing
known") says less than a value.

Run from the repository root:
    python generator/workflow/answer_coverage.py projects/<crate_identifier>/answers.txt [--list CODE]

--list CODE prints the keys with that code ("?" for the unknown ones).
--strict ends with exit code 1 if an answer has no source line (rule 2.10) - for a
crate built from a setup sheet every answer has one.
"""
import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

CODES = {"E": "ELN, structured", "X": "ELN, extracted from free text", "R": "fixed translation rule",
         "L": "looked up", "C": "curated", "D": "invented for the demonstration", "M": "missing",
         "?": "no source line"}


def read_entries(path: Path) -> list:
    """(key, code, source text, answer) per entry, in file order - read with the generator's own reader."""
    import os
    os.environ["ANSWER_FILE"] = str(path)
    import helpers.user_io as uio
    uio._load_answer_file()
    entries = []
    for key in uio._answer_order:
        entry = uio._answer_entries[key]
        source = next((line[len(uio.SOURCE_PREFIX):] for line in entry["comments"]
                       if line.startswith(uio.SOURCE_PREFIX)), None)
        code = source.split(":", 1)[0].strip() if source else "?"
        entries.append((key, code, source, entry["answer"]))
    return entries


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("answer_file")
    parser.add_argument("--list", metavar="CODE", help="list the keys with this source code")
    parser.add_argument("--strict", action="store_true", help="exit code 1 if an answer has no source line (rule 2.10)")
    args = parser.parse_args()

    entries = read_entries(Path(args.answer_file).resolve())
    total = Counter(code for _, code, _, _ in entries)
    filled = Counter(code for _, code, _, answer in entries if answer.strip())
    print(f"{args.answer_file}: {len(entries)} answers\n")
    print(f"{'code':<5}{'meaning':<34}{'answers':>8}{'share':>8}{'non-empty':>11}")
    for code in list(CODES) + sorted(set(total) - set(CODES)):
        if total[code]:
            print(f"{code:<5}{CODES.get(code, '(unknown code)'):<34}{total[code]:>8}"
                  f"{total[code] / len(entries):>8.0%}{filled[code]:>11}")
    if args.list:
        print(f"\nkeys with code {args.list}:")
        for key, code, source, answer in entries:
            if code == args.list:
                print(f"  {key} = {answer or '<empty>'}" + (f"   [{source}]" if source else ""))
    if args.strict and total["?"]:
        print(f"\n{total['?']} answer(s) without a source line (rule 2.10) - list them with --list '?'")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
