# Instrument files

Tools that turn the files of a lab instrument into files the crate can read (rule 4a.1: a table with its header in
the first row). The original file stays as it is and is a file of the crate too; the derived one lies next to it and
the sheet says how it was made.

| Tool | Instrument | Writes |
|---|---|---|
| `k1_start_run_tables.py` | K1 Start flow reactor (Accelerated Materials), CSV log of the control software | the table of each run, `<log>_run_table.csv` or `<log>_run<n>_table.csv` |

```
python generator/interfaces/instruments/k1_start_run_tables.py <log.csv> [<log.csv> ...]
```
