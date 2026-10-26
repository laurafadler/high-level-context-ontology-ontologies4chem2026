# Key catalogue – summary

Answer file: `projects/amidation_ai4green_ai4_001/answers.txt`. Written by `generator/workflow/key_catalog.py`; details in `key_catalog_patterns.csv` and `key_catalog_call_sites.csv`.

- **842 keys** in the answer file, falling into **198 key patterns** (the same question at different places of the experiment).
- **189 call sites** in the code ask a question; 92 of them were asked for this crate, 97 were not.

## Answers

| Answer | Keys | Share |
|---|---:|---:|
| empty | 542 | 64 % |
| No | 41 | 5 % |
| Yes | 22 | 3 % |
| other | 237 | 28 % |

## By category

| Category | Patterns | Keys | empty | No | Yes | other |
|---|---:|---:|---:|---:|---:|---:|
| which quantities have a value? | 57 | 405 | 368 | 0 | 0 | 37 |
| values | 72 | 131 | 15 | 30 | 0 | 86 |
| tasks | 18 | 104 | 43 | 10 | 11 | 40 |
| setup of the apparatus | 23 | 99 | 50 | 0 | 1 | 48 |
| library selection | 11 | 50 | 32 | 0 | 0 | 18 |
| files | 3 | 34 | 32 | 1 | 0 | 1 |
| same in all experiments? | 3 | 8 | 0 | 0 | 8 | 0 |
| other | 6 | 6 | 1 | 0 | 1 | 4 |
| setup | 5 | 5 | 1 | 0 | 1 | 3 |

## By answer kind

| Answer kind | Keys |
|---|---:|
| list from options | 554 |
| one of options | 183 |
| text, parsed by name_list | 53 |
| free text | 30 |
| text, parsed by fraction_answer_type(quantity_kind) | 13 |
| open | 6 |
| number (int) | 1 |
| text, parsed by planned_number | 1 |
| text, parsed by crate_identifier | 1 |

## Checks

- Patterns without a matching call site: 0
- Patterns in category "other" (not yet sorted in CATEGORIES): `eln_record`, `empties`, `same_solvent_across_experiments`, `solvents`, `creator_kind`, `location_phase`
