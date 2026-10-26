# How to add something to the libraries

A person, an organization, a substance or a delivered container of chemicals - without writing JSON-LD or a
script. The tools are in `generator/workflow/library_entries/` (details in its README). All
commands run from the repository root.

## The loop

```
1. create   python generator/workflow/library_entries/create_library_entry.py <type> --project <crate_identifier>
2. fill in  the file it names, in an editor
3. check    python generator/workflow/library_entries/finish_library_entry.py <file>
4. write    python generator/workflow/library_entries/finish_library_entry.py <file> --write
5. commit   git add libraries <file> && git commit -m "Library entries: ..."
```

Repeat 2 and 3 until step 3 ends with `Library consistency check: nothing new.` and `Dry run - nothing written.`
Nothing touches a library before step 4, and step 4 only runs on committed libraries.

`create_library_entry.py --list` shows the types:

| Type | For | Library |
|---|---|---|
| `person` | someone who plans, performs or enters something | people (membership also in organization) |
| `organization` | a university, a department, a manufacturer | organization |
| `substance` | a chemical PubChem knows (looked up by its SMILES) | chemical entity |
| `container` | a bottle, can or gas cylinder as it was delivered, with its content | device and material |
| `site` | a building or campus (gets its gravitational field) | organization |
| `laboratory` | a room at a site, with its size and air | organization |
| `cabinet` | a cabinet in a laboratory | organization |
| `labware` | a kind of labware (beaker, tube, cap) and its pieces in the lab - or more pieces of a kind the library has | device |
| `device` | a simple device without a content (balance, bench, stand) | device |
| `prepared_container` | a container filled in the lab (a stock solution) with its preparation | device and material |

Without a project, `--out <folder>` puts the file elsewhere. The file stays after it was written - it is the record
of who entered what, and when.

## Filling in the file

The template lists every field the type can have:

```yaml
entries:
  - name:                 # (required) full name as it is written - e.g. Meng Kong
    given_name:           # (required) e.g. Meng
    family_name:          # (required) e.g. Kong
    # orcid:              # the plain identifier, no https://orcid.org/ - e.g. 0000-0001-7621-0889
    # member_of: []       # organizations the person belongs to ...
```

- Fields without `#` are required; fill them in after the colon.
- An optional field is commented out. To use it, remove the `# ` in front of it (in VS Code: select the lines and
  press `Ctrl+/`) - also the `# ` of the lines of a block under it.
- More entries of the same type: copy the block from `- name:` and fill it in again. One file is one sitting:
  everything in it shares one task (who entered it, when) - six substances looked up together belong in one file.
- `entered_by` is you (your name or `person:<ID>`), `source` says where the information comes from in one sentence:
  `Given by Meng Kong on 07.10.2026.`, `Read off the bottles in cabinet B3 on 08.10.2026.` It goes into the comment of
  every entry.
- Names of other entries (an organization, a template, a cabinet, a substance) may be written as the ID
  (`organization:CEB`) or as the name (`Sigma-Aldrich`).

### Values

A value - the mass of a delivered bottle, the delivery time - is a small block, as in the setup sheet:

```yaml
    delivered:
      value: 2025-06-02T09:30:00Z       # a time: date, hour, zone (Z = UTC)
      kind: literature                  # measured | observed | literature | assumed
      source: delivery note 4711        # where it was read - or, if assumed, why
    content:
      mass:
        value: 0.1
        unit: KiloGM                    # a QUDT unit: KiloGM, GM, MilliGM; L, MilliL ...
        kind: literature
        source: label
```

| kind | when | becomes |
|---|---|---|
| `measured` | weighed, read off an instrument | Evidence, Measured |
| `observed` | written down by someone (the opening date on the label) | Evidence, Observed |
| `literature` | printed by the manufacturer: label, certificate, delivery note | Reference, Literature (source as `hlo:hasSource`) |
| `assumed` | not known - a value taken for it | Reference, Assumed (source = the reason) |

An optional value that is not known is left out (commented): the library then says that the quantity exists and its
value is unknown. Only the day known? Write a time and say so in `source` (`... the hour is not known, 12:00 taken`).

## What step 3 may answer

| Message | Meaning | What to do |
|---|---|---|
| `missing: entries[1].given_name` | a required field is empty | fill it in |
| `not allowed: ... has a wrong CAS check digit` | a typo in a CAS number or ORCID | correct it |
| `unknown field` | a field the type does not have (often a typo) | correct or remove it |
| `Needed first: 'Example Labs' is not in the library - started: .../organization_....yaml` | the file names something that does not exist yet; an entry file for it was made, with the name filled in | finish that file first (steps 2-5), then run this one again |
| `Questions ... under open` | something only you can decide, e.g. which of several CAS numbers PubChem lists | answer in the field of the entry (the options are listed under `open:` at the end of the file) and run again |
| `Problems: ... exists already` | the library has this already (same ID, or for a substance the same InChIKey) | use the existing entry, or give another `id` |
| `Notes: PubChem writes it ...` | information - PubChem writes the SMILES another way | check the CID once if a tautomer, isomer or salt is possible |
| `The library consistency check reports something new` | the new entries would break a rule of the libraries | nothing was written; read the finding, correct the file |

Exit codes: 0 ready (or written), 1 something is wrong, 2 the file waits for an answer or another entry.

## Example: a delivered bottle

```
python generator/workflow/library_entries/create_library_entry.py container --project pba_synthesis
```

filled in:

```yaml
format: library-entry-v1
type: container
entered_by: Laura Fadler
source: Read off the bottle and its delivery note by Meng Kong, 08.10.2026.
entries:
  - name: Nickel(II) chloride hexahydrate bottle no. 2
    template: device:glass_bottle_250mL
    cabinet: lab:L208_Chemicals_Cabinet
    delivered:
      value: 2025-06-02T09:30:00Z
      kind: literature
      source: delivery note 4711
    content:
      label: Nickel(II) chloride hexahydrate, lot MKCL1234
      state: solid
      solid_structure: crystalline
      lot: MKCL1234
      species:
        - substance: Nickel(II) chloride hexahydrate
          fraction:
            value: 0.98
            kind: literature
            source: certificate of analysis of lot MKCL1234
      manufacturer: Sigma-Aldrich
      mass:
        value: 0.1
        unit: KiloGM
        kind: literature
        source: label
    received_by: Meng Kong
```

Step 3 then lists what would be added - the container in the Device Library; its content, phase, species and the
receipt in the Material Library; the task that read the records and the task that assumed what they do not say - and
ends with `nothing new`. Step 4 writes it; the bottle can then be named in a setup sheet like any other device.

## What is not made here

Devices with parts or ports of their own (a reactor), reactions
(`generator/workflow/library_prerun/fixed_reaction_from_template.py`), filling a container that is there already
(`generator/workflow/inventory_tool.py prepare`), substances PubChem does not know. A small curation script in
`projects/<identifier>/curation/` is still the way for those (step 1 of `docs/new_series_guide.md`).
