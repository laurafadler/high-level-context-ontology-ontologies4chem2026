# Library entries

Adding something to the libraries without writing JSON-LD or a curation script (rule 2.16). The same loop
as the setup sheet: a template, filled in by a person, checked, written.

```
python generator/workflow/library_entries/create_library_entry.py --list
python generator/workflow/library_entries/create_library_entry.py person --project <crate_identifier>
#   -> projects/<crate_identifier>/curation/library_entries/person_<date>_<time>.yaml  (or --out <folder>)
#   fill it in: required fields are open, optional ones commented out - remove the '# ' to use one
python generator/workflow/library_entries/finish_library_entry.py <file>            # check, nothing written
python generator/workflow/library_entries/finish_library_entry.py <file> --write    # write the libraries
git add libraries <file> && git commit -m "..."                                     # by hand
```

`finish_library_entry.py`:

- checks the file against `entry_schema.yaml` (required fields, formats - CAS and ORCID with their check digits,
  rule 2.8 -, unknown fields);
- looks up what the file names (who enters it, organizations, ELN records) by ID or name. Something missing that
  has a type of its own gets an entry file of that type, pre-filled with the name (exit 2): finish that first;
- asks what only a person can decide (which of several CAS numbers) under `open:` in the file (exit 2);
- builds the entries in memory and runs `workflow/check_library_consistency.py` on that state - written is only
  what adds no new finding (a new entry is listed as unreferenced; that does not count);
- with `--write`, and only with committed libraries, writes main file and details (rule 2.14) and records under
  `written:` in the file what went in. A written file is not written again.

## Types

| Type | Library | Becomes |
|---|---|---|
| `person` | people | `schema:Person` with name, given/family name, ORCID, e-mail, memberships (the organization gets `org:hasMember`), identifiers in other systems |
| `organization` | organization | `org:Organization` with name, URL, parent unit (the parent gets `org:hasUnit`) |
| `container` | device + material | a container of the inventory as delivered (`cpo:ChemicalContainer`, an exemplar of a template, in a cabinet) and its content - lot, SKU, manufacturer, mass, volume, expiry and re-test date, species with mass fractions; the receipt starts its usage history (rule 5.5) and the occurrence of the content; values read off the records by one task of the file, assumed ones by another, both stamped by `task:assuming_device_library_task_times` |
| `site` | organization | `org:Site` with its gravitational field (standard gravity, `task:looking_up_standard_gravity`) and a permanent occurrence; the organization gets `org:hasSite` |
| `laboratory` | organization | `cpo:Laboratory` with its cuboid form (dimensions as value blocks, volume calculated), the room air as the other rooms have it (dry-air density and composition from the shared lookup tasks, 20 degC / 1 atm assumed unless given, mass calculated, permanent occurrence); the site gets `cpo:hasRoom` |
| `cabinet` | organization | `cpo:StorageCabinet` in a laboratory |
| `labware` | device | a template of labware without a content - a vessel or bottle as a cup with its cavity (`helpers/inventory_entries.py: container_template`), a lid as a ring around its opening (`cpo:AnnulusForm`, as `device:vial_cap_template`), a septum as a solid disc (as `device:vial_septum_template`) - neither of the two has a cavity, so no crate asks for its content; body, one or more openings; dimensions as value blocks, catalogue or assumed and its exemplars, each with its place and a commissioning; or, with `template`, only further pieces of a template of the library |
| `device` | device | a simple device without a content (as `device:balance001`): envelope (box or cylinder), body (volume from the mass, or solid), place, manufacturer, model, commissioning |
| `prepared_container` | device + material | a container filled in the lab (as `inventory_tool.py prepare`): commissioning of the empty container (rule 5.5), the preparation with one transfer from the content of each source, the content with species and concentrations; the preparation is sorted into the usage histories of the sources. Values measured, observed or planned in the preparation are determined by it |
| `substance` | chemical entity | a molecule from its PubChem record (looked up by SMILES, kept as `<file>_pubchem.json` next to the file): identifiers, molar mass as a `cpo:Parameter` with a Literature reference, one lookup task per file (rule 4.1), its start stamped by `task:assuming_chemical_entity_library_task_times`; an ELN record named gets `schema:about` back |

The fields of each type are in `entry_schema.yaml`, derived by hand from the shapes, the generator and the
consistency check (`basis:` of each type). Every entry carries in its comment the `source` of the file and how it
was entered.

A step-by-step guide for users: `docs/how_to_library_entries.md`.

Not made here: devices with parts or ports of their own (the K1 reactor - see the building blocks in
`helpers/inventory_entries.py` and `projects/pba_synthesis/curation/archive/add_k1_system.py`), reactions (`library_prerun/fixed_reaction_from_template.py`),
substances PubChem does not know.

## Adding a type

A block under `types:` in `entry_schema.yaml` and a class in `entry_types.py` with `prepare` (IDs, what names point
at, questions) and `build` (the entities, in memory, through `LibrarySet.add` and `LibrarySet.link` for the other
direction of a link). Values with an evidence or reference and their task: `helpers/inventory_entries.py: Entries`.

Test: `python generator/tests/library_entries_test.py` (in a throwaway copy, about a minute).
