# Coverage - chemotion_example

Where the 1887 answers of `projects/chemotion_example/answers.txt` come from (source line of each answer, rule 2.10). In brackets: how many of them have content - an empty answer or a plain "No" says less than a value. Written by `generator/workflow/coverage_report.py`.

## By source

| Source | Answers | Share | With content |
|---|---:|---:|---:|
| ELN | 269 | 14% | 193 |
| rule | 55 | 3% | 38 |
| 'none' default | 128 | 7% | 0 |
| by hand | 1434 | 76% | 344 |
| missing | 1 | 0% | 0 |

## By topic

| Topic | ELN | rule | 'none' default | by hand | missing | All |
|---|---:|---:|---:|---:|---:|---:|
| series and people | 3 (3) | 2 (0) | - | 7 (7) | 1 (0) | 13 |
| materials and substances | 30 (20) | 1 (0) | 16 (0) | 77 (61) | - | 124 |
| values | 52 (34) | 52 (38) | 2 (0) | 307 (31) | - | 413 |
| tasks | 97 (65) | - | 108 (0) | 353 (210) | - | 558 |
| devices | - | - | - | 7 (7) | - | 7 |
| files | 33 (33) | - | - | 14 (11) | - | 47 |
| reactions | 2 (2) | - | - | 2 (2) | - | 4 |
| room | - | - | 2 (0) | - | - | 2 |
| derived | 52 (36) | - | - | 666 (14) | - | 718 |
| other | - | - | - | 1 (1) | - | 1 |

## Sources

- **ELN**: from the ELN record: structured (E) or extracted from its free text (X)
- **rule**: a fixed translation rule, mostly turning an ELN entry into the crate's terms (R)
- **'none' default**: only 'nothing else is known' - a default the sheet sets for a whole category, no knowledge
- **by hand**: curated (C) or invented for the demonstration (D) by a person
- **missing**: nobody knew it (M)

Topics follow the key of the question: a question about values ("for which quantities ...", a field of a value) counts as *values* wherever the value sits; *derived* are the things the generator works out itself (interfaces, transfers, occurrences, ports).
