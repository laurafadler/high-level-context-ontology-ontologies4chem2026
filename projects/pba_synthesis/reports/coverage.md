# Coverage - pba_synthesis

Where the 10095 answers of `projects/pba_synthesis/answers.txt` come from (source line of each answer, rule 2.10). In brackets: how many of them have content - an empty answer or a plain "No" says less than a value. Written by `generator/workflow/coverage_report.py`.

## By source

| Source | Answers | Share | With content |
|---|---:|---:|---:|
| rule | 48 | 0% | 29 |
| 'none' default | 361 | 4% | 0 |
| by hand | 9686 | 96% | 3349 |

## By topic

| Topic | rule | 'none' default | by hand | All |
|---|---:|---:|---:|---:|
| series and people | - | - | 12 (12) | 12 |
| materials and substances | - | 46 (0) | 322 (266) | 368 |
| values | 48 (29) | 1 (0) | 1227 (116) | 1276 |
| tasks | - | 164 (0) | 1097 (906) | 1261 |
| devices | - | - | 45 (45) | 45 |
| files | - | - | 19 (13) | 19 |
| reactions | - | - | 7 (7) | 7 |
| room | - | 2 (0) | - | 2 |
| derived | - | 148 (0) | 6952 (1979) | 7100 |
| other | - | - | 5 (5) | 5 |

## Sources

- **rule**: a fixed translation rule, mostly turning an ELN entry into the crate's terms (R)
- **'none' default**: only 'nothing else is known' - a default the sheet sets for a whole category, no knowledge
- **by hand**: curated (C) or invented for the demonstration (D) by a person

Topics follow the key of the question: a question about values ("for which quantities ...", a field of a value) counts as *values* wherever the value sits; *derived* are the things the generator works out itself (interfaces, transfers, occurrences, ports).
