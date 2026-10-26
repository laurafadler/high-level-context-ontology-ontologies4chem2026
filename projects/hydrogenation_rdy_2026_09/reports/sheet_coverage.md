# Sheet coverage - projects/hydrogenation_rdy_2026_09/answers.txt

| Class | Patterns | Keys |
|---|---:|---:|
| sheet | 329 | 4320 |
| none only | 7 | 31 |
| content missing | 3 | 7 |
| derived | 0 | 0 |
| gap | 0 | 0 |

## By thing

| Thing | sheet | none only | content missing | derived | gap |
|---|---:|---:|---:|---:|---:|
| transfer | 1347 | 0 | 0 | 0 | 0 |
| task | 935 | 8 | 6 | 0 | 0 |
| species | 343 | 0 | 0 | 0 | 0 |
| phase | 229 | 22 | 0 | 0 | 0 |
| material | 238 | 0 | 0 | 0 | 0 |
| occurrence | 228 | 0 | 0 | 0 | 0 |
| phase_pair_interface | 207 | 0 | 0 | 0 | 0 |
| phase_interface | 144 | 0 | 0 | 0 | 0 |
| device | 94 | 0 | 0 | 0 | 0 |
| participant | 84 | 0 | 0 | 0 | 0 |
| evidence | 82 | 0 | 0 | 0 | 0 |
| occupation_state | 76 | 0 | 0 | 0 | 0 |
| elementary_reaction | 60 | 0 | 0 | 0 | 0 |
| participant_transfer | 54 | 0 | 0 | 0 | 0 |
| profile_step | 51 | 0 | 0 | 0 | 0 |
| (series) | 29 | 0 | 1 | 0 | 0 |
| reference | 29 | 0 | 0 | 0 | 0 |
| reaction | 22 | 0 | 0 | 0 | 0 |
| bound_to_search | 16 | 0 | 0 | 0 | 0 |
| media_object | 12 | 0 | 0 | 0 | 0 |
| occupied_by_search | 12 | 0 | 0 | 0 | 0 |
| place | 12 | 0 | 0 | 0 | 0 |
| port_crossing | 9 | 0 | 0 | 0 | 0 |
| environment | 3 | 1 | 0 | 0 | 0 |
| interface | 4 | 0 | 0 | 0 | 0 |

## Gaps - asked by the generator, no field in the sheet yet


## Content missing - the sheet can only deny it, but the answer file says something

- `series:1/cross_material_pairs` (1 of 1) - [hlo:SeriesSpecific] Which further Phase Interfaces between phases of different materials have not been recorded yet? Each as 'phase + phase
- `series:1/experiment:<n>/task:<name>/acts_on` (4 of 4) - [hlo:ExperimentSpecific] Which devices or materials does Putting on the lid act on? [reactor001 ExperimentSpecific 1, vessel001 ExperimentSp
- `series:1/task:<name>/acts_on` (2 of 2) - [hlo:SeriesSpecific] Which devices or materials does Putting on the lid act on? [reactor001 SeriesSpecific, vessel001 SeriesSpecific, jacket

## None only - the sheet can deny it, not give it

- `series:1/environment:<name>/measured_ambient_fields` (1)
- `series:1/environment:<name>/phase:<name>/species_names` (1)
- `series:1/material:<name>/phase:<name>/energy_field_types` (21)
- `series:1/experiment:<n>/task:<name>/acts_on` (4)
- `series:1/task:<name>/acts_on` (2)
- `series:1/task:<name>/quantities_with_evidence` (1)
- `series:1/task:<name>/quantities_with_reference` (1)
