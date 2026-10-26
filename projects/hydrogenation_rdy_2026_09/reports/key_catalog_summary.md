# Key catalogue – summary

Answer file: `projects/hydrogenation_rdy_2026_09/answers.txt`. Written by `generator/workflow/key_catalog.py`; details in `key_catalog_patterns.csv` and `key_catalog_call_sites.csv`.

- **4358 keys** in the answer file, falling into **337 key patterns** (the same question at different places of the experiment).
- **189 call sites** in the code ask a question; 128 of them were asked for this crate, 61 were not.

## Answers

| Answer | Keys | Share |
|---|---:|---:|
| empty | 2936 | 67 % |
| No | 218 | 5 % |
| Yes | 78 | 2 % |
| other | 1126 | 26 % |

## By category

| Category | Patterns | Keys | empty | No | Yes | other |
|---|---:|---:|---:|---:|---:|---:|
| which quantities have a value? | 85 | 2659 | 2531 | 0 | 0 | 128 |
| values | 143 | 631 | 42 | 195 | 11 | 383 |
| setup of the apparatus | 50 | 451 | 95 | 6 | 13 | 337 |
| tasks | 23 | 285 | 85 | 9 | 36 | 155 |
| library selection | 17 | 173 | 68 | 0 | 0 | 105 |
| files | 5 | 117 | 104 | 6 | 2 | 5 |
| other | 5 | 28 | 10 | 0 | 8 | 10 |
| same in all experiments? | 4 | 9 | 0 | 1 | 8 | 0 |
| setup | 5 | 5 | 1 | 1 | 0 | 3 |

## By answer kind

| Answer kind | Keys |
|---|---:|
| list from options | 3055 |
| one of options | 974 |
| text, parsed by name_list | 115 |
| free text | 101 |
| text, parsed by fraction_answer_type(quantity_kind) | 41 |
| text, parsed by _at_least_zero | 36 |
| open | 31 |
| via ask_entity_list | 2 |
| number (int) | 1 |
| text, parsed by planned_number | 1 |
| text, parsed by crate_identifier | 1 |

## Checks

- Patterns without a matching call site: 0
- Patterns in category "other" (not yet sorted in CATEGORIES): `empties`, `same_solvent_across_experiments`, `solvents`, `absent_species`, `eln_record`
