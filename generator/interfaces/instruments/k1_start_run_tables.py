"""
The run tables of K1 Start logs (Accelerated Materials flow reactor; written for the series pba_synthesis).

The control software writes one CSV per reaction run: four lines of run data (reaction ID, operator, reagent
names), a blank line, then the table (elapsed time, air mass flow rate, pump set points, pump pressures, air
temperature, status). The crate reads a table only with its header in the first row (rule 4a.1), so this tool
writes the table alone next to the log, as <log>_run_table.csv - the log itself stays as it is and is a file of
the crate too. A log holding several runs gives one table per run, <log>_run<n>_table.csv (a run begins with the
status 'Reaction started'): the log of experiment 2 of pba_synthesis holds two complete 120 s runs.

Nothing is changed in the rows: same columns, same headings (the pump set points say L/min but are mL/min - the
sheet gives the unit).

Usage (from the repository root), with the logs of a series:
    python generator/interfaces/instruments/k1_start_run_tables.py <log.csv> [<log.csv> ...]
e.g. for pba_synthesis:
    python generator/interfaces/instruments/k1_start_run_tables.py \\
        "projects/pba_synthesis/input/lab_data_for_crate/lab_data_for_crate_exp1/ferro+ni2+.csv" \\
        "projects/pba_synthesis/input/lab_data_for_crate/lab_data_for_crate_exp2/ferro-ni2-mn2.csv"
"""
import argparse
import csv
from pathlib import Path

HEADER_START = "Elapsed Reaction Time"


def runs(path: Path):
    """The header of the table and its rows per run - a run begins with the status 'Reaction started'."""
    rows = list(csv.reader(path.open(encoding="utf-8-sig", newline="")))
    start = next(i for i, row in enumerate(rows) if row and row[0].startswith(HEADER_START))
    header, tables = rows[start], []
    for row in rows[start + 1:]:
        if not row or not any(row):
            continue
        if not tables or (tables[-1] and row[-1].startswith("Reaction started")):
            tables.append([])           # the next run begins
        tables[-1].append(row)
    return header, tables


def write_run_tables(log: Path) -> list:
    """Writes the table of each run of a log next to it; returns the files written."""
    header, tables = runs(log)
    names = [log.stem + "_run_table.csv"] if len(tables) == 1 else \
        [f"{log.stem}_run{n}_table.csv" for n in range(1, len(tables) + 1)]
    written = []
    for table, out_name in zip(tables, names):
        out = log.with_name(out_name)
        with out.open("w", encoding="utf-8", newline="") as handle:
            csv.writer(handle).writerows([header] + table)
        print(f"{out}: {len(table)} rows, {table[0][0]} s to {table[-1][0]} s")
        written.append(out)
    return written


def main():
    parser = argparse.ArgumentParser(description="Writes the run tables of K1 Start logs next to the logs.")
    parser.add_argument("logs", nargs="+", help="the CSV logs of the K1 Start control software")
    for log in parser.parse_args().logs:
        write_run_tables(Path(log))


if __name__ == "__main__":
    main()
