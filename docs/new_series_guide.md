# From a series to an RO-Crate: step by step

How to describe a new experimental series as a crate, from an ELN export or from nothing. The details of every field are in `generator/interfaces/eln/README.md`; a complete
example of a sheet is `projects/amidation_ai4green_ai4_001/setup.yaml`.

All commands run from the repository root. They are written for Git Bash; in PowerShell an
environment variable is set first: `ANSWER_FILE=x python ...` becomes `$env:ANSWER_FILE="x"; python ...`.

## The idea in one picture

```
ELN export (.eln) --> core files --+
                                   +--> adapter --> answer file --> generator --> crate --> SHACL
person ----------> setup sheet ----+                  (whatever nobody said: asked)
```

- The **setup sheet** (`setup.yaml`) holds what only a person knows: devices, what is in them, the
  procedure, the values and how they are known. Every answer carries its source (rule 2.10).
- The **libraries** (`libraries/`) hold the fixed things the sheet points to by name: people, devices,
  substances, reactions. They must exist before the sheet can name them.
- The **answer file** (`answers.txt`) is written by the run: every question of the generator with its
  answer and source. A new series starts from an empty one.
- Paths are never configured: everything follows from the identifier of the series
  (`series.short_name`), and `generator/path_definitions.py` puts it under `projects/<identifier>/`.

## Step 0 - Start the project

Choose an identifier: lower-case letters, digits, `_` and `-`, e.g. `esterification_ab_2026_10`. It
becomes part of every ID in the crate; changing it later needs `generator/workflow/rename_crate.py`.

```
# with an ELN export
python generator/workflow/new_project.py <identifier> --eln <path/to/export.eln> --by "<your name>"

# without an ELN: how many experiments were conducted so far
python generator/workflow/new_project.py <identifier> --experiments <n> --by "<your name>"

# only the folder and the skeleton - put the export into input/additional_files_for_crate/ later
python generator/workflow/new_project.py <identifier>
```

This creates `projects/<identifier>/` with:

| | |
|---|---|
| `input/additional_files_for_crate/` | files of the whole series (SOPs, risk assessments); the ELN export is copied here - it is a file of the crate |
| `input/lab_data_for_crate/` | lab files, one subfolder per experiment whose name ends in `exp<n>` (`lab_data_for_crate_exp1`) |
| `core/` | with `--eln`: one core file per ELN record (what the record says, in neutral JSON) |
| `curation/` | PubChem answers and library scripts of this series |
| `answers.txt` | only the header line |
| `setup.yaml` | the skeleton of the sheet: required fields empty, the other sections as commented examples |

With an export that holds several records, the sheet lists all of them under `series.eln_records`:
keep only those that are experiments of this series, in their order. Copy lab files with their time
stamps (the crate records the creation date of each file): on Windows
`robocopy <from> <to> /E /COPY:DAT /DCOPY:DAT`.

`input/` is not versioned (`.gitignore`) - the data may be large or confidential.

## Step 1 - Libraries

Everything the sheet names must be in the libraries first; `check_sheet.py` reports a name that points
at nothing. Usually needed for a new series:

| What | Library | How |
|---|---|---|
| people (planned, performed) | `people_library.jsonld` | entry file of type `person` (below) |
| organisations (university, manufacturer) | `organization_library.jsonld` | entry file of type `organization` |
| lab, site, cabinet | `organization_library.jsonld` | entry files of type `laboratory`, `site`, `cabinet` |
| delivered containers of chemicals | `device_library.jsonld`, `material_library.jsonld` | entry file of type `container` |
| labware (beaker, tube, cap) and simple devices (balance, stand) | `device_library.jsonld` | entry files of type `labware` (template and exemplars) and `device` |
| devices with parts and ports (a reactor) | `device_library.jsonld` | a template (`hlo:Template`) and the exemplar used; copy a similar template and adapt it |
| containers filled in the lab (stock solutions) | `device_library.jsonld`, `material_library.jsonld` | entry file of type `prepared_container` |
| substances | `chemical_entity_library.jsonld` | entry file of type `substance` (looked up on PubChem by SMILES) |
| the reaction | `reaction_library.jsonld` | participants with roles and coefficients; the balance is checked |
| the ELN record | `reaction_library.jsonld` | the record as a dataset, as `reaction:Record_eLabFTW_7849` |

```
# PubChem: one NAME=SMILES per substance; writes a file, never a library
python generator/interfaces/pubchem/pubchem_lookup.py --out projects/<identifier>/curation/pubchem/substances.json "Ethanol=CCO" ...
```

People, organisations, sites, laboratories, cabinets, substances, containers (delivered or filled in the lab), labware
and simple devices are entered with entry files (`docs/how_to_library_entries.md`):

```
python generator/workflow/library_entries/create_library_entry.py person --project <identifier>
#   fill in projects/<identifier>/curation/library_entries/person_<date>_<time>.yaml, then
python generator/workflow/library_entries/finish_library_entry.py <file> [--write]
```

What no entry type covers (a device with parts and ports of its own, a reaction) is easiest written by a small
script in `curation/` (examples, archived: `projects/chemotion_example/curation/archive/add_library_entries.py`,
`projects/pba_synthesis/curation/archive/add_k1_system.py`) - an AI coding assistant such as Claude Code can write
it from the list of things above; once it has run, it goes into `curation/archive/` (rule 2.16). Each entry says where it comes from. Then check and **commit the libraries**: a
real run refuses uncommitted libraries, so that the commit of a crate records which libraries it used.

```
python generator/workflow/check_library_consistency.py
python generator/workflow/check_context_requirements_consistency.py
```

## Step 2 - Fill in the sheet

Open `projects/<identifier>/setup.yaml` and fill in, top to bottom:

1. `source` - who entered the sheet, and when (set by `--by`).
2. `series` - `description`, `completed` (no further experiment?), `planned_experiments`.
3. `people` - `creator` (planned) and `experimenter` (performed), names as in the People Library.
4. `devices` - the device exemplars used.
5. `materials` - what is in each device: phases, their state, species, solvents.
6. `uncontained_streams` - what goes in or out on a way that lies in no device (one per added substance, usually
   `from: outside`); a stream through a device (a jacket, a tube) is a material with `kind: stream`.
7. `reactions` - the reaction of the library; `[]` says no reaction takes place.
8. `tasks` - the procedure: each task with `type`, `part_of` (Preparation, Main operation, Work-up),
   `equipment`, `functions`, `performers`, `aims_at`, `description`; the start of `Experimental
   procedure` is required.
9. `values` - every known value with `kind` (measured, calculated, observed, planned, assumed, set,
   literature ...) and the task that determined it. With an ELN, pre-fill them first:

```
python generator/workflow/prefill_sheet.py projects/<identifier>/setup.yaml
```

10. `none` - what explicitly does not exist (no samples, no further values ...). A category missing
    here is asked later, never assumed.

Check as often as you like:

```
python generator/interfaces/eln/check_sheet.py projects/<identifier>/setup.yaml
```

YAML pitfalls: a name with a comma inside a `[...]` list needs quotes (`["2,5-Furandicarboxylic acid"]`);
indentation is with spaces. Write each source out: YAML anchors (`&name` ... `*name`) that reach from one
entry into another break `close_sheet.py`, which reads the entries one by one.

## Step 3 - The next step, again and again

Once the sheet has its fields, one command does the rest of the loop - call it, answer, call it again:

```
python generator/workflow/next_step.py projects/<identifier>
```

Each call checks the sheet (`check_sheet.py`), builds the crate in a throwaway copy from the sheet alone (an
exploratory run - nothing in the project changes; the stored answers are left out, since one of them would
hide a change of the sheet) and writes every question nobody answered into the sheet: under `open`
(fill in `answer` and its `source`; `''` = none on purpose) or as empty entries under `values`. It ends
with what to do next:

- **questions written** - answer what you know, call it again (answers can bring follow-up questions);
- **a stop that is not a question** - e.g. the start of an experiment or the time of a device's use is
  missing (rule 5.6): it says what is missing and where in the sheet it is settled;
- **a question the sheet cannot hold** - the sheet names something in a form the adapter does not read
  (a unit symbol, a name): it shows the question and its key;
- **nothing new** - declare the rest unknown (Step 4), then call it again;
- **nothing open** - build the crate for real (Step 5).

This is the step where an AI coding assistant helps most: paste a group of open questions and ask what
fits. The two commands it runs can also be called by hand (`isolated_run.py ... --on-unknown log
--from-sheet --report report.json`, then `open_questions.py report.json --write-sheet ...`).

## Step 4 - Declare the rest unknown

When everything that is known is in the sheet:

```
python generator/workflow/close_sheet.py projects/<identifier>/setup.yaml --by "<your name>"
```

Empty values move to the section `unknown`, open list questions get `''` - with name and date. A
question that needs a real answer stays open; `next_step.py` names it. Then call `next_step.py` again.

## Step 5 - The real run

```
ANSWER_FILE=projects/<identifier>/answers.txt python generator/workflow/answer_driver.py --in-place \
    --setup projects/<identifier>/setup.yaml --from-sheet
```

It writes `crate/ro-crate-metadata.json`, the answer file and the usage history of the devices in the
libraries, and commits them. A question still unanswered stops the run and names its key. With
`--from-sheet` it builds what step 3 explored: every answer from the sheet, the answer file written anew.
Without it a stored answer wins over the sheet - a value the sheet names since the last run would stay
unknown.

## Step 6 - Checks

```
python generator/workflow/run_shacl.py --crate projects/<identifier>/crate/ro-crate-metadata.json
python generator/workflow/answer_coverage.py projects/<identifier>/answers.txt
python generator/workflow/coverage_report.py projects/<identifier>
```

The SHACL report (`reports/`) names context that is still missing; the coverage report shows where the
answers came from (ELN, rule, by hand ...).

## Good to know

- While the new series is open (`completed: false`), there are several open crates (the hydrogenation and the
  PBA series are open too): tools without `--crate` then ask which one is meant.
- A completed series is read only (`crate_completed/`); `generator/workflow/reopen_crate.py` opens it again.
- Building all crates anew (after a change of the generator, the libraries or the ontologies): first the open
  series (step 5), then `reopen_crate.py` for the completed ones and build them - reopening takes their usage
  out of the libraries until they are built again, and an open series built in between would miss it
  (`rules_crate.md`, 5.7).
- A change of the sheet after the real run: change the sheet, run step 3 once to see the effect, then
  step 5 again. If the change alters what the crate already records, both stop and list the changes; when
  they are intended, set `ALLOW_EARLIER_CHANGES=1` for both (`rules_crate.md`, 7b).
