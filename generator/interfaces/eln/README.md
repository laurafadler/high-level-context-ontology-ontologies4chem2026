# ELN import

From an ELN export to the answers of the crate generator.

```
ELN (.eln) --> reader + profile --> core file --+
                                                +--> adapter --> answer keys --> generator
person -------------------------> setup sheet --+       nothing to say --> the generator asks
```

| Part | File | Knows |
|---|---|---|
| reader | `reader.py` | the `.eln` format (a zipped RO-Crate); Chemotion's own collection export is read by its profile |
| profile | `profiles/<eln>.py` | where one ELN keeps what; nothing is inferred (rule 2.9) |
| core file | `core.py`, written to `projects/<crate_identifier>/core/` | what one ELN record says, in neutral JSON |
| setup sheet | `projects/<crate_identifier>/setup.yaml` | what only a person knows: devices, which substance is in which material and phase, uncontained streams, reactions, tasks, people |
| adapter | `adapter.py` | the answer keys - the only part that does |

## Running it

From the repository root:

A new series is started with `generator/workflow/new_project.py` (project folder, core files, skeleton
of the sheet); the whole way, step by step: `docs/new_series_guide.md`.

```
# core file from an export (projects/<crate_identifier>/input/eln/ -> projects/<crate_identifier>/core/)
python generator/workflow/eln_to_core.py projects/<crate_identifier>/input/eln/<export>.eln
# the same for a Chemotion collection export (a .zip with export.json - read without unpacking)
python generator/workflow/eln_to_core.py projects/<crate_identifier>/input/eln/<export>.zip

# crate in an isolated copy, adapter first, the rest from a rules file or asked
python generator/workflow/isolated_run.py --answers <empty answer file> -- --setup projects/<crate_identifier>/setup.yaml [--rules r.json]

# where the answers came from
python generator/workflow/answer_coverage.py projects/<crate_identifier>/answers.txt [--list R]
# the files of a Chemotion series into input/ (the export, per experiment the attachments of its record and the
# reaction scheme), after the sheet names the core files under eln_records
python generator/interfaces/eln/collect_chemotion_files.py projects/<crate_identifier>
```

A series without lab files needs the two empty folders `input/additional_files_for_crate/` and
`input/lab_data_for_crate/` in its project (the generator stops on a missing folder, so that a
wrong path does not quietly mean "no files").

A new crate needs an answer file that holds only the line `# answer-file-format: keyed-v2`.

## Where an answer comes from (rule 2.10)

Every answer the adapter gives is written into the answer file with a second comment line:

```
key: series:1/experiment:1/material:Ethylamine_Charge/phase:Ethylamine_Phase/mass/reference_scalar_unit
    // Unit of #Mass_Phase_Ethylamine_Phase_ExperimentSpecific_1 (...)? [MilliGM, GM, KiloGM, No unit / not applicable]
    // source: R: A8 - Unit symbols of the ELN are written as QUDT units (...) ELN: 'mg' (ELN AI4Green AI4-001, substances[1].mass.unit)
MilliGM
```

| Code | Meaning |
|---|---|
| E | from the ELN, structured field (the source names the field of the core file) |
| X | from the ELN, extracted from free text (the source quotes it) |
| R | a fixed translation rule - one of the adapter rules below |
| L | looked up in an external source (PubChem, ...) |
| C | curated: a decision or addition from expert knowledge (who suggested it, who confirmed it) |
| D | invented for the demonstration |
| M | missing - left empty, or asked |

An answer without a source line (typed in) counts as unknown. Answers
from the setup sheet carry the sheet's `source`, or the entry's own (a text for all its fields, or
a table per field).

## Adapter rules

All rules of the import (adapter, profiles, sheet) are listed in `docs/rules_crate.md`, section 9,
with a pointer back here; their wording is this README.

A rule may only say what follows from the matter itself - never what one merely supposes.
Everything else is said by the setup sheet, with its own source, or asked.
The same texts as `RULES` in `adapter.py` (`python -m interfaces.eln.adapter --rules` from `generator/` prints them).
A new rule gets the next free number; a withdrawn rule leaves its number unused.

| Rule | Text |
|---|---|
| A1 | An ELN record becomes an experiment of the series; how many experiments the series has, the setup sheet says. |
| A3 | In a series with one experiment, everything is the same in all experiments. |
| A8 | Unit symbols of the ELN are written as QUDT units (mg -> MilliGM, mmol -> MilliMOL, mL -> MilliL, g -> GM); a percentage is passed on as '<number> %', which the generator stores as a fraction. Without a symbol there is no unit. |
| A9 | A number taken from the ELN is a new value (not one that exists in the crate already) and a single scalar process variable (not a time series). |
| A12 | A result of an ELN record (yield, selectivity) belongs to the reaction participant it names ('of'); a result that names no substance is left out. |
| A14 | A substance the setup sheet does not name under species_per_experiment occurs in every experiment in which its phases occur - the species lists of the sheet hold for the whole series. |
| A15 | The content of a container or a supply line of the libraries is described by the Material Library: its phases hold no species beyond the ones entered there. |
| ~~A13~~ | Withdrawn: the assumptions the generator makes itself are entries of `libraries/assumption_library.jsonld` with their own text, not tasks of the crate. |

Withdrawn because they supposed something (now in the setup sheet, or asked):

| Rule | Was | Now |
|---|---|---|
| A2 | number of experiments = number of ELN records | the sheet lists one record per experiment (`series.eln_records`) |
| A4 | not mentioned = nothing (empty lists, no further value, no profile) | only what the sheet explicitly denies (`none`) - a person may know what the ELN does not say |
| A5 | a phase without a dispersion is continuous | `dispersion` in the sheet, else asked |
| A6 | the reaction table and conditions of AI4Green are planned | `kind` of each value in the sheet |
| A7 | the product mass of AI4Green is measured | `kind` of each value in the sheet |
| A10 | tasks performed by the experimenter, the planning by the creator | `performers` at the task in the sheet, else asked |
| A11 | a planned value is determined by the planning | `determines` at the task in the sheet |

The author of an ELN record is the creator of the record (`schema:creator` of the record in the
Reaction Library), not the creator or experimenter of the series.

Experiment n is `schema:subjectOf` the n-th record of `series.eln_records` (A1; rule 4a.5 in
`docs/rules_crate.md`): the adapter answers `series:1/experiment:<n>/eln_record` with the Reaction
Library entry whose `schema:identifier` is "<System> <record_id>" (Chemotion adds the UUID in brackets).
Without `eln_records` it gives no answer - "No ELN record" is said by a person, once for the series:
`eln_records: none` in the series block (with `conducted_experiments`).

## Profile rules

A profile says where one ELN keeps what (rule 2.9); it passes values on as the ELN writes them and
infers nothing. What lands in the core file counts as E (structured field) in the source line. The
rules below are what a profile decides beyond copying a field. Code:
`profiles/<eln>.py`. A profile translates no roles: the ELN role (`reactant`, `reagent` ...) reaches the
core file as the ELN's word, and the `cpo:ChemicalRole` of a reaction participant is curated in the
Reaction Library.

**AI4Green** (`profiles/ai4green.py`)

| Rule | Text |
|---|---|
| P-AI1 | The chemistry of a record is read from its JSON file (`<reaction id>.json`); molar mass, density and equivalents from the substance table in the record's HTML text. |
| P-AI2 | The role of a substance is the list it stands in (reactants, reagents, solvents, catalysts, products) and is passed on as the ELN's word. It is not translated into a `cpo:ChemicalRole`: the roles in the Reaction Library are curated (C). |
| P-AI3 | For the product, mass and amount in the JSON are those of the theoretical yield (`theoretical_mass`, `theoretical_amount`); the mass obtained is the column "Product Mass (mg)" of the table, the unreacted mass of the limiting reactant the column "Unreacted (mg)". |
| P-AI4 | A unit is taken from the JSON field or the column heading (Density (g/mL), ... (mg)); molar mass in g/mol (heading "Mol.Wt", no unit given - the usual unit of a molar mass). The temperature of the JSON has no unit and stays without one; the heading "Temp ℃" of the sustainability table is not read, because its place in the HTML is not reliable - the unit comes from the setup sheet or is asked. |
| P-AI5 | Yield and selectivity refer to the product when the record has exactly one; with several, to none (A12 leaves them out). Conversion refers to the limiting reactant, which the export does not name - it is left without a substance. |
| P-AI6 | AI4Green does not say when the experiment ran, only when the entry was created and changed - the experiment date stays empty. |
| P-AI7 | A record is completed when `reaction_completed` is `complete`. |
| P-AI8 | The `.json` and `.rxn` files of the export are parts of the export, not files of the experiment. |
| P-AI9 | Addenda become notes with their author; the sustainability and safety fields are kept under `unmapped`. |

**eLabFTW** (`profiles/elabftw.py`)

| Rule | Text |
|---|---|
| P-EL1 | Everything is read from the RO-Crate graph; `temporal` is the date of the experiment. |
| P-EL2 | A record is completed when its status (`creativeWorkStatus`) is success, completed or finished - a list set in the profile, not given by the ELN. Without a status it is open whether it is completed (`completed: null`). Checked against a real export (Lennard Schulte, eLabFTW 6.0.5): its records have no status; the field `status` ("Normal") is the state of the entry (normal, archived, deleted), kept as `entry_state`, not read as a status. |
| P-EL3 | Free fields count only through the mapping table of the instance (`FIELD_MAP`, empty for the demo export); all others, and the linked records, are kept under `unmapped`. |
| P-EL4 | The steps of a record are its `HowToStep`s, in their order; keywords are split at commas. |
| P-EL5 | Symbols typed with the Symbol font of a word processor reach the export as private-use characters (U+F06D for µ, U+F0B0 for °, Lennard's export) and are passed on unchanged; a person reads them in the setup sheet. |

**Chemotion** (`profiles/chemotion.py`; example: collection export of Congjian Lin)

| Rule | Text |
|---|---|
| P-CH1 | Chemotion's collection export is no `.eln` file but a ZIP with `export.json` (the database tables by UUID), `schema.json`, `attachments/` and `images/`. It is read from the ZIP, not unpacked: unpacked on Windows, the names under `images/` exceed the length of a path, and nothing there is needed. A record is a reaction (one experiment); its record ID is its short label (`LCJ-R5`), the UUID is kept as `record_uuid`. |
| P-CH2 | The experiment date is `timestamp_start` (end: `timestamp_stop`); `created_at` is only the date of the entry. Both were empty in the example - then the start is asked. |
| P-CH3 | A record is completed when its status is done, successful or not successful; not completed when planned or running; with analyses pending (the lab work is done, the analysis not) or without a status it is open whether it is completed (`completed: null`). The list is set in the profile from the choices of Chemotion's user interface - the export does not give them: `status` is free text there, and `schema.json` names no values. |
| P-CH4 | The substances are the samples of the link tables of the reaction; the role is the table's word (starting material, reactant, solvent, purification solvent, product), not translated. An amount goes to mass, volume or amount by its unit. The target amount is the amount of the reaction table (`mass` ...), the real amount is kept as `real_mass` ...; for a product the real amount is the amount obtained (`mass`), the target amount the theoretical one (`theoretical_mass`, as P-AI3). |
| P-CH5 | Fields that cannot be null in `schema.json` - target amount, density, molarity - and the Rf value hold 0 when nobody filled them in; 0 there is passed on as empty (a real 0 cannot be told apart, and is meaningless there). The real amount can be null - empty is null there, and a 0 is passed on as 0 (the product of R8 in the example: 0.0 g). To check against fuller Chemotion exports (`docs/things_to_implement_after_me.md`). |
| P-CH6 | The export holds no users, only their UUIDs: the author of a record stays without a name. A name appears only as the creator of an analysis dataset (`files[].dataset_creator`) and is not taken as a person of the record. |
| P-CH7 | A sample without a structure (decoupled, e.g. biomass) hangs on a placeholder molecule (InChIKey `DUMMY`): it gets no SMILES or InChIKey, its name is the name of the sample. |
| P-CH8 | The files of a record are the attachments of the analyses of the reaction and of its samples, each with the sample, the analysis and its kind (CHMO) it belongs to. |
| P-CH9 | The temperature is `temperature.userText` with `valueUnit`; the duration has no unit in the export and stays without one (as P-AI4); the free texts `conditions` and `solvent` are passed on as text conditions. The generic segments (Labimotion) are instance-specific forms and, like the free fields of eLabFTW (P-EL3), kept under `unmapped` - only their filled fields. |
| P-CH10 | The inventory of a sample (table `Chemical`, the tab 'Inventory') is passed on with its substance - the record of the sample itself or of the nearest sample it was split from (`ancestry`), as `inventory`: vendor, `order_number`, amount, status, where it is stored (`host_*`) and currently is (`current_*`), dates, storage temperature, notes; the rest of the record under `inventory.unmapped`. Also the CAS number the sample carries (`xref`) and its location text - only where the sample has them. `order_number` keeps the ELN's word: Chemotion uses it for a vendor's catalogue number (Sigma-Aldrich '646377-1L') and for an own stock's lot ('SPRUCE-2025-03') alike - which it is, the curation of the inventory decides per entry, not the profile. |

## Setup sheet, version 1

Check a sheet without running the generator: `python
generator/interfaces/eln/check_sheet.py projects/<crate_identifier>/setup.yaml` - missing fields, names
that point at nothing, values not allowed, unknown fields, against `sheet_schema.yaml`; as warnings also
fixed reactions of the Reaction Library the sheet does not name although all their reactants stand in one
of its phases - a suggestion only, nothing goes into the crate by itself. What only
the generator can decide shows an exploratory run - from the sheet alone (`answer_driver.py --from-sheet`,
as `next_step.py` does it): the adapter answers only keys the answer file does not hold, so a stored answer
would hide a change of the sheet, and the questions the change brings would come up only in the real run
(a value with `determined_by`: the times of that task). Its open questions, readable and grouped by the
place in the sheet: `python generator/workflow/open_questions.py <report.json>`. With
`--write-sheet projects/<crate_identifier>/setup.yaml` they go into the sheet's section `open` - key, thing,
question, options, an empty `answer` and its `source` - for a person, an agent or a script to fill in;
the adapter answers these keys first. `answer:` without a value is still open, `answer: ''` empty on
purpose. Answering can open follow-up questions: repeat until an exploratory run has none.
The sheet is only ever appended to (`interfaces/eln/sheet_text.py`), never rewritten.
A question about values becomes empty values in `values` instead (one per quantity offered); a
place the generator derives (room air, wall material, interface, transfer) is named by its path
(`at: environment:L109_Air/phase:L109_Air_GasPhase`). `kind: none` at a value: nothing is known
of it. A question the sheet has a field of its own for is not written to `open` - the times of a
task only when the task is an entry of `tasks` (or a built-in one); the times of a task that a value names
with `determined_by` are asked at its placeholder (`task:for-<value>`) and written as empty values at that
task. An `input` of a calculation must be
a value of the sheet (`check_sheet.py` reports it otherwise).

Smaller fields of their own:
- `device_settings`: per device its `operation_mode` (for the series, or `{1: Batch, 2: Flow}`), and `content` - the
  content of the Material Library the series drew from, when the device has held several one after the other and the
  start of the first experiment does not decide (question `library_content`, rule 2.15).
- A set profile is a value
  like any other, with `steps` instead of `value` - `kind: transition` with `from`/`to` or `kind: hold`
  with `value`, optional `duration`, `change_rate` - usually `kind: set` and the task that set it under
  `determined_by` (a SettingTask, e.g. "Setting the stirring speed"); `executed_by: [Stirring]` names the
  tasks that run it (`cpo:executesProfile`). The stirring speed is the quantity `rotational_speed` of a
  device whose library entry has `cpo:canRotate true`; a value of a device in one experiment stands at
  `at: device:<name>/experiment:<n>`. Once the sheet has a profile, a task no profile names executes none.
- `experiments` at a task: the experiments it occurred in, e.g. `[2]` - a task of only some experiments
  (question `extra_task_names` of each experiment; `none: experiment_tasks` answers only when no task has the field).
  The section it is part of needs `varies: [parts]`, so that its parts are asked per experiment.
- `files`: every file of the series with `from` - the task that produced it (every file has one, an assumed one
  if need be, rule 4a.2) - and a data file's `reference_column`; `type` (File, Image, Video) and `creator` (a
  person of the People Library, `''` none or not known). A task that exists because of
  its file (transcribing the masses into a spreadsheet) has `created_from_file: true`; the generator creates it from
  the first file naming it.
- At a stream: `to_phase` / `from_phase` - the phase inside the device at that end, which a port
  crossing enters or leaves (questions `device_side_phase`, `opens_into_phase`); `crossing_phases` - of a stream of
  several phases the ones that cross at its ends (`crossing_stream_phases`).
- At a reaction: `transfers` - per participant at the interface the phase it leaves or enters and
  the kind of transfer (`{participant: Hydrogen, phase: Liquid_Phase, type: Adsorption}`); `elementary` - per
  elementary reaction of its mechanism where it takes place (`in_phase` / `at_interface`) and its `transfers`.
- At an occurrence statement: `document` - the DOI of a planned or literature statement.
- `sample_of` at a material, `on_sample` at a task (`''` the material itself), `form` at a solid phase
  no device holds (`SolidCylinderForm`).
- `species_per_experiment`: a substance that occurs only in some experiments, once for the
  whole series - `{Manganese(II) chloride: [2], Nickel hexacyanoferrate(II): [1], source: "..."}`. The species
  lists of the phases name everything the series can contain; in an experiment a substance not listed for it is
  left out of every phase (except contents and bodies of the libraries), with its transfers, port crossings,
  occupations and the reactions it takes part in. Not named: in every experiment (A14).

Occurrences and times:
- `occurrences`: one entry per statement - these things occurred so often in these experiments, known so
  (`kind`), found out by this task (`determined_by`, a task of `tasks`):

  ```yaml
  occurrences:
    - transfers:
        vessel001_opening: [Adiponitrile from RDY_Add_Phase to RDY_Phase]
      experiment: all          # the experiments the sheet names at the time of the run; or 1, or [1, 2]
      count: 1                 # 0: it did not occur
      kind: observed
      determined_by: Watching the material go in and out
    - interfaces: [GasVessel_Phase / L109_Air_GasPhase]
      ...
    - phases: []               # nothing is known about any phase
  ```

  A transfer is written `<species> from <phase> to <phase>` (or by the generator's full name, which also
  holds the type), an interface `A / B`, a reaction by its name in the Reaction Library. Whoever names a
  kind names every thing of that kind anything is known about; a kind without an entry is asked (`none:
  occurrences` still says nothing is known at all). A readable name that fits two transfers at one place
  (two types between the same phases) gets no answer - the exploratory run shows the question, and the
  full name settles it. Code: `interfaces/eln/sheet_names.py`; checked by `check_sheet.py`.
- Times are values: a time of a task `at: task:<name>`, a time of an occurrence `at: <kind>:<thing>`
  with `occurrence: <k>` (and `place:` for a transfer); `quantity` `start_time`, `end_time`, `duration`,
  or for a task also `start_offset`; with `kind`, `determined_by` and `experiment` like any value. What is
  not known of them stands in `unknown` (`at: <task>`, or the thing with `occurrence`). The short form
  `times: {start, end, kind}` at a task stays valid.
- `time_source` at a task that reads times (rule 4.7): `[Wall clock, Handwritten record (lab journal, run
  log)]`, the clock itself in `time_source_detail`; `software` and `aims_at` at a task (`[]` none).
- A transfer in `aims_at` may be written readably, `<species> from <phase> to <phase>`, as in `occurrences`;
  `reactions: []` says that no reaction of the library is relevant (otherwise asked).
- A reaction is named by its name in the Reaction Library or by its ID (`PBA_Ferrocyanide_Ni`,
  with or without `reaction:`); the adapter answers the generator with the library's name. A fixed reaction is made
  from a template (`hlo:Template`, with placeholders) by `generator/workflow/library_prerun/fixed_reaction_from_template.py`.
- `open_questions.py --write-sheet` writes an open list of occurrences as an entry with `null` (still
  open - not `[]`, which says nothing is known) and the things offered under `offered`, open times as
  empty values; `close_sheet.py` turns what is still `null` into `[]`, with name and date.

When everything known is in the sheet: `python generator/workflow/close_sheet.py
projects/<crate_identifier>/setup.yaml --by "<name>"` states that the rest is unknown, with name and date:
the empty values move, per place and experiment, to the section `unknown` (`none: [density, mass,
...]` - "values" shows what is known, "unknown" what is explicitly not, so one still sees where
something may have been forgotten); every open list question gets `answer: ''`; a question that
needs a real answer stays open. Nothing is declared unknown in advance -
`none: further_values` still works, but is not the recommended way.

Further fields of the sheet:

- `source` at the top and per entry (see above).
- `people: {creator: [...], experimenter: [...]}` - names as in the People Library; empty = asked.
- `values` - the last section: every known value as an entry `{at, of, experiment, quantity,
  value, unit, kind, exact, group, source}`. `at`
  is `<material>/<phase>` or the name of a reaction (its participant in `of`); `of` a substance in
  that phase; `kind` how to read it - measured, calculated, observed (evidence) or planned,
  assumed, controlled, set, literature (reference), set by a person, empty = asked; `exact: true`
  an exact value, not limits; `unit` an ELN symbol (mg, translated by A8) or a QUDT unit
  (DEG_C); `group` the group of the ELN record (`reaction_table`, `conditions`, `product_mass`,
  `yield`, `selectivity`) that a task's `determines` can name; `source` per field;
  `quantity_kind` (optional): the QUDT quantity kind when the quantity allows several - a
  concentration as `MassFraction` (5 wt%) or `MoleFraction`; without it the generator asks. The
  concentration of a substance in a phase is `quantity: concentration` with `of` (the generator asks
  it at the substance itself, without a segment of its own). The values of
  an ELN record are written there by `python generator/workflow/prefill_sheet.py
  projects/<crate_identifier>/setup.yaml` (see below).
- Description, documents, sources and observations:
  - `series: {description: ...}` - the description of the series (and of the crate's root dataset); without
    it the adapter builds one from the core files (title, ELN, record, link), without core files it is asked.
  - `document` at a planned or literature value: the document it comes from (a DOI), written to `hlo:hasSource`
    of its reference (rule 4.1; the generator asks it for the types Planned and Literature). Without it the
    question stays open - unless `none` names `reference_sources` ("no document known").
  - `none: {sources: {<category>: ...}}` - a source of its own for one category (for a decision taken later
    than the others); otherwise `none.source` holds for all.
  - A transfer may name its type where two are possible between the same phases: `<species> by <Type> from
    <phase> to <phase>` (`Sulfur dioxide by Degassing from Liquid_Phase to Gas_Phase`) - valid on every level,
    unlike the generator's full name.
  - `observes: [<phase, material or device>]` at an observation task: what it looked at - a phase, a material
    (also a stream) or a device (`sosa:hasFeatureOfInterest`); what was seen goes into its description (a colour,
    an appearance - no quantity of its own).
- `devices_source`: the source of the device list, when it is not the sheet's - e.g.
  the sheet's source plus the source of devices added later.
- `none: {categories: [...], source: ...}` - what a person explicitly says does not exist. A
  category that is missing is asked; the adapter never answers "none" on its own. Its `source`
  belongs to its categories: a "nothing else" in a value list carries it only for
  `further_values`, otherwise the sheet's source:

  | Category | Answered empty / "No" |
  |---|---|
  | `further_values` | no values beyond those of the ELN record: the lists 'for which quantities ...' hold only the ELN's, and no value has a second one |
  | `samples` | no material is a sample of another |
  | `interfaces` | no further phase interfaces between materials (the contacts to the room air the generator creates itself), no occupation states |
  | `energy_fields` | no phase generates an energy field, none was measured in the room |
  | `air_species` | no further species in the air of the room |
  | `occurrences` | nothing known about whether or how often phases, interfaces, transfers, reactions occurred |
  | `experiment_tasks` | no task that only occurred in one experiment |
  | `profiles` | no set profile of a device, no task executes a profile |
  | `task_details` | tasks use no software, aim at nothing, act on nothing, have no input values and no description beyond the sheet; a task not in the sheet uses no equipment |
  | `emptied` | no task used up or disposed of the content of a container of the inventory |

  A list that must not be empty (the input values of a calculation) is asked all the same.
- `empties` at a task: the containers of the inventory whose content the task
  used up or disposed of, per experiment - `empties: [{experiment: 2, containers: [bottle
  adiponitrile 01]}]`. The run ends the content in the material library and stops if a later
  experiment draws from it again (rule 7.17). Without it, `none: emptied` answers every such
  question empty; otherwise the generator asks.
- Tasks: `structure` of a solid phase, `functions` and `description` of a task, `performers`;
  `functions` names the purposes (rule 4.9) - only where the class leaves a choice: a
  determination, sampling, planning, recording or calibration task gets its function from its class
  and is not asked; a section (`type: task` with parts) is asked for its own purpose beyond its
  parts, `functions: []` for none;
  `type` (measurement, calculation, operation, ... - or `task` for a plain `cpo:Task`, a section
  holding other tasks); `inputs: ["<Quantity> <place>", ...]` - the input values of a calculation in
  the experiment, each matching exactly one option (`Mass Product_Phase`);
  `times: {start, end, kind}` - the start and end of a task in the experiment (per experiment
  number, `times: {1: {...}, 2: {...}}`, in a series with several); required for the
  `Experimental procedure` (rule 5.6) - and the task that determines them,
  `determines: [<task>/times]` (name, description, performers);
  `determines: [<group> or <material>/<phase>/<quantity>]` - the task that determines these values.
  Such a task is not created as a further task: the generator creates it for its value, and the
  sheet gives it its name and equipment. A task may be listed under the name of a built-in task
  (`Planning the series`) to give its `determines` or `performers`. The built-in sections of the
  procedure - `Preparation`, `Main operation`, `Work-up` (rule 7c.5a) - always exist;
  a task goes into one with `part_of: Preparation` and so on, and the task that brings a reaction about
  hangs in `Main operation` with `aims_at: [<reaction name>]` (rule 4.9). The assumptions
  the generator makes itself are entries of the assumption library, not tasks
  of the crate, and have no place in the sheet.

## Pre-filling the sheet with the values of a core file

`python generator/workflow/prefill_sheet.py projects/<crate_identifier>/setup.yaml [--dry-run]` places the
values of the core files (`interfaces/eln/sheet_values.py`) and appends them to `values`, with
their ELN source and without a reading. It only appends - comments and entries written by hand
stay as they are. It reports a value the ELN now disagrees with (the sheet keeps its own), a value
overwritten on purpose (its source not `E:` - kept), and substances that have no place in
the sheet or no library entry.

| Core file | Place in the sheet (`at` / `of`) | `group` |
|---|---|---|
| mass / volume of a reactant, reagent, solvent | phase of its uncontained stream (such a phase holds that substance only) | `reaction_table` |
| amount of a reactant, reagent, solvent | that phase, `of` the substance | `reaction_table` |
| mass of the product | phase of the sheet material holding the product | `product_mass` |
| temperature (condition) | the phase the reaction takes place in; unit only if the ELN gives one | `conditions` |
| yield, selectivity | the reaction, `of` the substance they refer to (A12) | `yield` / `selectivity` |

A substance of the core file is matched to the library through the import (PubChem answers in
`projects/<crate_identifier>/curation/pubchem/`, InChIKey), not through its name alone. While a value has
no `kind`, the lists "for which quantities ..." at its place are asked.

## Known gaps

- Conversion (95 %) has no substance it refers to in the export and is left out (rule 2.9).
