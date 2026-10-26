# Rules every crate follows

What the generator keeps to without saying so, in one place: how IDs are built, what stands in the crate
and what in the libraries, how levels, quantities, forms and transfers are modelled, how the SHACL shapes
are built and how a series is continued. The descriptions of the context requirements in the Higher Level
Ontology and the comments of the shapes refer to these rules by their number ("rule 7.16").

Words used throughout: a **level** is a library entry (`hlo:Fixed`), a series record (`hlo:SeriesSpecific`)
or an experiment record (`hlo:ExperimentSpecific`), each pointing to the one above through
`hlo:specializationOf` (the chain); in the ontology the levels are scopes (`hlo:Scope`). An **exemplar** is
a device, phase or molecule on one level. The **context level** is Device, Phase or Molecule - the kind of
thing a context requirement is about, its **context object**.

Every rule names where it sits in the code. **checkable** means: the rule can be checked automatically (as
a SHACL shape, in a consistency script or by a comparison run); **checked** says with what this is done.

New rules are added here as soon as they are decided. Whoever breaks a rule first changes this file and
gives the reason.

---

## 1. IDs and keys

1.1 **The ID and the key of an entity depend only on the entity itself and its owner**, never on
what else exists or was created before. No counter, except where the number is the identity
(experiment 2, the second value of the same quantity).
*checkable:* counter-checks with reordered lists, the crate must stay identical.

1.2 **Crate IDs have the form `crate:<identifier>/<local name>`.** The identifier is the short name
of the series (`setup/series_short_name`), `crate:` stands for `https://example.org/crate/`. Built only
through `_compose`/`crate_id` in `helpers/identifiers.py`, never by hand.
*checked:* by `check_library_consistency.py`, section "IDs in the crates" - no `#…` ID in the crate.

1.3 **A reader sees a crate ID as `#<local name>`** (questions, options, labels, answer file;
`for_display`, `option_label`). The answer file therefore does not depend on the identifier.

1.4 **Names are asked as a list, not one by one with a running number.** The name is required.
**Every entity of the crate has a `schema:name`** (RO-Crate recommends it):
where none was asked or taken over, a pass shortly before saving gives it one from the ID (`generate_name`,
`creation/root_node_functions.py: name_unnamed_entities`). Deliberately not at creation: in several places
"no name yet" means that the name is asked or taken over from the series template (tasks from values,
materials in the experiment, reactions, phases) - an early name would change these questions. Entities of
the libraries and of other crates stay untouched; no `rdfs:label` next to it.
*checked:* `hlo:Name_Shape` (every entity of the crate) and `hlo:Name_LibraryEntry_Shape` (the
library entries a person looks things up by: devices, templates, people, organizations, sites, rooms, cabinets,
substances, contents, reactions) in `shapes/DataQualityShapes.ttl`, Warning; counter-check
`generator/tests/rules_as_shapes_test.py`.

1.5 **Task keys carry the level, not the experiment number.**

1.6 **A value is named after its variable, its role and its number, not after its type:**
`<Variable>_<Evidence|Reference>_<n>`, with the level suffix of the variable at the end
(`device:vessel001_InnerDiameter_Reference_1`, `…_Reference_1_Fixed`,
`crate:…/Mass_Phase_RDY_Phase_Evidence_1_ExperimentSpecific_1`) - the same in crate and libraries
(`make_member_id`). The type is in `hlo:hasEvidenceType`/`hlo:hasReferenceType`; whoever corrects it
changes no ID. A reference mechanism, too, is the n-th reference of its Actual anchor
(`reaction:ReactionMechanism_0001_Reference_1`). The level suffix is that of the variable, not that of a
value shared across several levels: a value always hangs on the Actual of exactly one level, and the
series Actual and the experiment Actual are different entities - without
the suffix their first values would have the same name.
*checked:* in the libraries by `check_library_consistency.py`.

1.7 **Task names: a gerund with its object**: "Adding the
catalyst", "Logging the temperature", "Assuming the sample volume", "Working up". No imperative ("Add
catalyst"), no noun ("Pressure logging", "Work-up"), no label with a colon ("Assumption: …"). The object
may be left out where it is obvious ("Stirring", "Cooling"). Exceptions are the fixed shells (7c.5a:
"Experimental procedure", "Planning the series", "Establishing the values", "Preparation", "Main
operation", "Work-up") - their names are set. The name determines the ID of the task
(`Task_Adding_the_catalyst_…`) and its answer keys (`task:Adding_the_catalyst/…`); it is therefore fixed
before the first run - renaming it later changes IDs and keys.
*checked:* `check_sheet.py` warns (the exit code stays 0) when a task name in the
sheet does not start with a word ending in "-ing" and is not a fixed shell; counter-check in
`sheet_check_test.py`.

## 2. Crate and libraries

2.1 **The crate links to the libraries, it does not copy them.** Only what records the state at the time
of creation is copied: the Ontology Snapshot. Library entries the run has to read are fetched explicitly
with `resolve` (`helpers/entities.py`), against all libraries `main.py` registers at the start;
`find_entity` searches only the crate.
*checked:* by `check_library_consistency.py`, section "IDs in the crates" - of the
library entries, only those with the prefix `ontology:` stand in the crate.

2.2 **A library entity is not changed during a run.** No back-references (`hlo:hasSpecialization`), no
contexts (`hlo:describesContext`) on library entries. What the crate says about them stands on entities
of the crate. Whether an entity is a library entry is decided by `is_library_entity`, not by its type
(forms in the library carry no `hlo:Fixed`). That is also why a library task names no value of the crate
in `cpo:determines` (exception in 4.1).
*checked:* in every run before saving (`check_libraries_unchanged`), abort on any change, without
exception. The only place a run writes is the usage of the devices (rule 5.3): `record_device_usage`
loads the Device Library freshly from disk for it and writes into that copy, never into the registered
one. It reads the devices and their contents together (`load_device_libraries`; Device and Material
Library, 2.15) and writes each file on its own; in addition it writes the **end of a content** that an experiment used up
(7.17) - idempotent like the usage history. The run does not create new chemicals - if one is missing, it
aborts (`MissingLibraryEntryError`); new chemicals are made with an entry file of type `substance`
(`generator/workflow/library_entries/`, `docs/how_to_library_entries.md`, rule 2.16) - also before
`fill_reaction_library.py`, which only reads the chemical entity library.

2.3 **The crate names the library state it was built against.** Library list
`crate:<identifier>/LibrarySnapshot`: for every library the crate points to, the last commit of that file
and its date. The Assumption Library is always in it: its model assumptions hold in every run, also where
no value names them (inert - 3b.3).

2.4 **A run starts with committed libraries and commits what it changes in them itself.** Abort on
uncommitted changes in `libraries/`; the usageHistory is committed per experiment; only `libraries/` is
committed, only locally. Nothing is ever committed from an isolated copy.

2.5 **Libraries are added to, not overwritten** - except for the pointer `lastUsedTime`, whose earlier
state the commit keeps.

2.6 **Building a crate twice changes nothing.** Same crate, same library, no commit. To get there, the
usage history is read without the entries of this crate (5.4), and only what is not yet anywhere in the
history is appended.
*checkable:* second run, `compare_crates` identical, library unchanged.

2.7 **People, devices, substances and reactions stand only in their library.** The crate points to them
(2.1).

2.8 **Identifiers have their format.** A person stands with their organisations in
the People Library (`org:memberOf`, exactly the inverse of `org:hasMember` in the Organization Library;
likewise a unit names its parent organisation with `org:unitOf` and the parent the unit with `org:hasUnit`)
and, if available, with their ORCID as text without `https://orcid.org/`
(`cpo:hasORCID "0000-0001-7621-0889"`, at most one). The CAS number, PubChem CID, InChIKey and InChI of a substance
follow their standard format; SMILES and molecular formula are texts.
*checked:* ORCID with `hlo:Person_ORCID_Format_Shape` in `shapes/DataQualityShapes.ttl` (Warning;
counter-check: ORCID with prefix and with a wrong character 1 report each, two ORCIDs 1, no ORCID 0); the
identifiers and notations of a chemical entity with `hlo:ChemicalEntity_Format_Shape` in the same file -
the requirements ask only that a value exists (counter-check `generator/tests/molecule_requirements_test.py`).
The check digit of the CAS number is checked by `check_library_consistency.py` ("CAS numbers with a wrong
format or check digit"); that of the ORCID is checked by nobody.

2.9 **What comes from a source is taken over, not completed.** If something is
missing in an ELN export - a unit, the limiting reactant - it stays empty; no profile, adapter or pre-run
infers it by a rule. An RInChI (and any other identifier) is entered when the source brings it along,
otherwise not; it is never generated.
*Code:* `generator/interfaces/eln/profiles/ai4green.py` (temperature `unit: null`, conversion `of: null`).

2.10 **Every input says where it comes from.** Codes: E (ELN, structured), X
(extracted from HTML/free text), R (fixed translation rule), L (looked up), C (curated: a decision or an
addition from expert knowledge), D (invented for the demonstration), M (missing).
- **Answer file:** a comment line `    // source: <code>: <text>` under the key; without it the answer
  counts as unknown. `_record_answer` (`helpers/user_io.py`) keeps it as long as the answer stays the
  same. An R answer names the number of its rule (A1 …); all rules of the adapter with their text in
  `generator/interfaces/eln/README.md` (worded the same as `RULES` in `generator/interfaces/eln/adapter.py`).
  Counting: `generator/workflow/answer_coverage.py`.
  *checked:* `answer_coverage.py --strict` - exit code 1 when an answer has no source line.
- **Library:** a note on the entry (`schema:comment`) after a fixed pattern - "From the ELN
  (<System> <ID>): …", "… by curation (suggested by <who>, confirmed by <person> on <date>)",
  "Added by curation; not in the ELN … (<literature>)" - and a clear commit message. An entry from an
  ELN record is `schema:subjectOf` the record (rule 4a.3 applies accordingly), a curated addition is not.
- Graph and ontology stay untouched; the origin in the world is still said by Evidence and Reference
  (rule 4.1).

2.11 **A reaction is balanced - atoms and charge.** Checked are the templates of the
library and, with resolved placeholders, the SeriesSpecific reactions of the crates; a template with
placeholders is "not checkable", not an error. A by-product the source leaves out is added by curation
(rule 2.10), not left out.
**Templates and fixed reactions:** a reaction with placeholders that
serves only as a pattern carries `hlo:Template`; a fixed reaction with the concrete substances is made
from it with `generator/workflow/library_prerun/fixed_reaction_from_template.py` (checks the balance
before writing) and points with `hlo:specializationOf` to the template, its participants to the
template's participants - as a device exemplar to its template. The sheet names the fixed reaction (name
or ID), nothing is resolved during the run; so every experiment can have other substances, which a
placeholder (resolved once per series) does not allow. First example: the PBA formations
(`generator/workflow/library_prerun/pba_reactions.py`, also creates missing products).
**For every reaction, also at interfaces** (one concept for all crates): together with the
overall reaction the tool fixes its mechanism - a new Actual with a copy of every Reference (source, type and
determining task stay, the task determines the copy as well, rule 4.1) and fixed elementary reactions; an
elementary reaction that belongs to two mechanisms stays one. Partial reaction orders are not copied, the fixed
participant points to the value of the template. An occupation placeholder becomes a **fixed occupation state**
(`cpo:OccupationState` with adsorbate and site, without `cpo:belongsToInterface`): what is adsorbed where is chemistry
and fixed; at which interface is context of the series and is asked as before - mostly the state is already at the
interface ("Which occupation state already in this series is ...?", `_is_open_occupation_state`).
Hydrogenation: `projects/hydrogenation_rdy_2026_09/curation/archive/fixed_reactions.py`.
**Lumped reactions:** a reaction between materials that are not single species - wood,
lignin oil, pulp - is a `cpo:LumpedReaction` (beside `cpo:StoichiometricReaction`, both under `cpo:Reaction`). It has no
balanced equation, so it is not balanced: its participants have roles but no stoichiometric coefficient - none is asked,
because there is none (not an unknown one) - and it has no mechanism. It goes through the three levels like a stoichiometric
reaction; conversion, yield and selectivity are on a mass basis. At an interface the direction of a participant follows from
its role (Substrate, Reactant, Reagent leave a phase; Product, Byproduct enter one; any other role - Catalyst - moves nothing,
as a coefficient 0 would). First example: the RCF of spruce wood (`reaction:RCF_SpruceWood`,
`projects/chemotion_example/curation/archive/add_rcf_reaction.py`). Code: `creation/reaction_functions.py` (`is_lumped`).
*checked:* `check_library_consistency.py`, section "Balance of stoichiometric reactions"; a lumped reaction is reported
there only if a participant carries a coefficient after all.

2.12 **New library entries are named after their content, not after a running number:**
`chem:HOAt`, `reaction:Amidation_BenzoicAcid_Ethylamine`, participants
`<Reaction>_Participant_<Substance>`. Older entries still carry number IDs (`chem:Molecule_0001`…,
`reaction:StoichiometricReaction_0001`…). A pre-run script refuses an ID that exists already.

2.13 **What is known about occurrences stands in the sheet as a statement; times are values.**
The section `occurrences` of the setup sheet holds one statement per entry: these things (transfers per
place, interfaces, reactions, phases, energy fields) occurred so often, this is how it is known (`kind`),
this task found it out. Whoever names a kind names all known things of that kind; a kind without an entry
is asked, `[]` says "nothing known", `null` "still open" (nothing is answered from it). `experiment: all`
means: the experiments the sheet names at the time of the run. Times of tasks and occurrences stand under
`values` like any other value (`at: task:<name>`, an occurrence with `occurrence: k`), what is unknown
under `unknown`. The sheet names things readably (`Adiponitrile from RDY_Add_Phase to RDY_Phase`,
`GasVessel_Phase / L109_Air_GasPhase`); if a name fits two things, the adapter does not answer.
*checked:* `check_sheet.py` (form, missing count and reading, unknown task, open skeletons;
counter-check `generator/tests/sheet_check_test.py`), `generator/tests/sheet_names_test.py`;
touchstone: the hydrogenation sheet after the migration gives an identical crate from an empty answer file.

2.14 **One library, two files:** the Device, Material, Organization,
Chemical Entity and Reaction Library each stand in their main file (`libraries/<name>.jsonld`) and in
`libraries/details/<name>_details.jsonld`. The main file holds what it is about - devices with parts and
ports, the contents of devices (Material Library), organisations, sites, rooms and cabinets, substances, reactions with participants and placeholders -,
the details what describes them: forms, body materials and contents, values with Evidence and Reference,
tasks and their times. A reader gets both as one library (`helpers/library_files.py: read_library`, via
`load_jsonld`), a writer splits them again by `is_main_entry` (`save_jsonld`) - also what a run or a tool
newly creates. References between the files are ordinary `@id`s. The library snapshot in the crate (2.3)
names both files with their commit. People, Software, Assumption and Ontology Library stay one file. A
script that reads only the main file and writes it back byte for byte would lose the details - library
scripts read and write through `read_library`/`save_jsonld`.
*checked:* `check_library_consistency.py`; comparison run of the hydrogenation.

2.15 **Devices in the Device Library, their contents in the Material Library.**
The Device Library describes what one works with: every device - also a container of the chemical
inventory (`cpo:ChemicalContainer`, a `cpo:Vessel` with form, opening, cavity and usage history) and a
supply line -, every template and every body material. The Material Library (`libraries/material_library.jsonld`)
describes what is used up and
where it comes from: the content of a device (`cpo:MaterialVolume` with phase, species, lot, amount), its
receipt (occurrence, rule 7.17), its delivery, preparation and booking out as tasks with their transfers,
and the certificates of analysis. The two are linked both ways, across the files:
- `cpo:containsMaterial` names **only the current content** of a library device (none when it is empty),
  `cpo:materialContainedIn` only the current content names its device ("is in it now") - a content that
  was used up or disposed of no longer says where it was.
- `cpo:hasContainedMaterialHistory` lists **every content** the device has held, in the
  order filled in, like `cpo:hasUsageHistory` its uses; when each was in it, its receipt occurrence says
  (start = end of delivery or preparation, end = end of the task that used it up or disposed of it).
  Delivery and opening stay on the container (`cpo:hasDeliveryTime`, `cpo:hasOpeningTime`): only bottles
  filled in the lab are filled again, never bought ones.
- **Contents over time:** booking out a content (in a run, `empties`, or `inventory_tool.py dispose`)
  ends it (7.17) and **releases** it: the device no longer contains it, it no longer names the device
  (`helpers/inventory_state.py: release_content`); a rebuild that takes the end out again puts both links
  back at their places (`restore_content`, 5.4 - the files are byte for byte what they were). A container
  is filled again only when its last content has ended (`inventory_tool.py prepare` with `"container"`:
  the new content becomes the current one and the last of the history, the preparation enters the usage
  history). Contents of one device follow each other - a later one comes in when the earlier has ended.
- **Which content a crate draws from:** a device that has held **one** content brings that one along -
  also when it has been used up since, so that an older crate can be built again. A device that has held
  **several** brings the one that was in it when the **first experiment started**: the devices are made
  before the tasks whose times these are, so the start is read ahead
  from the answer file or the sheet (`helpers/user_io.py: known_answer`, the keys
  `series:1/experiment:<n>/task:procedure/start_time/{evidence,reference}_timestamp`) without asking or
  recording anything - the question comes later as usual. Only when no start is known yet (an
  interactive run) or no content or more than one fits, the series is asked
  (`series:1/device:<key>/library_content`). Once the times are asked, `record_device_usage` checks that
  the content was there at the start of every experiment that uses the device - came in before and not
  ended before - and **aborts** otherwise ("is there only since", "draws from it again"). **Limit:** one
  content per device and series - a container refilled between two experiments of one series cannot be
  described; split the series or use another container. A solution made up anew at the start of every
  experiment does not belong in the Material Library at all: it stands in the crate (7.17).
Library tools write each entry to its library (`helpers/inventory_entries.py`: `Entries.side`/`split`);
a run reads both as one view and writes into the file an entry comes from (2.2). The crate is not affected:
it names the files in its snapshot (2.3).
*checked:* `check_library_consistency.py` ("Devices and contents apart", "Contents of devices - current one
and history": current content not ended, contents one after the other), counter-check
`generator/tests/library_placement_test.py`; `generator/tests/content_history_test.py` (refilled
after, before and between the experiments of the hydrogenation; filling a full bottle refused); on every
level also `hlo:Content_Current_Shape` and `hlo:Content_OneDevice_Shape` (at most one current
content, named back both ways - what SHACL Core can say of it; the order in time stays in the script);
`inventory_end_test.py` (release and restore byte for byte).

2.16 **New library entries are made with the entry tools first.** Whoever needs a
library entry - by hand, in a session or for a sheet - first looks whether a type of
`generator/workflow/library_entries/` covers it (`create_library_entry.py --list`) and enters it with an entry file
(`docs/how_to_library_entries.md`). Only what no type covers (devices with parts and ports of their own, reactions,
substances PubChem does not know, supply lines) is built by a curation script in `projects/<identifier>/curation/` or
by copying a similar entry; its docstring then names the type that was missing, so that the next type to build is
known. Reason: the tools keep rule 4.1, the links in both directions and the consistency check by construction - hand
work leaves gaps (missing back-references). A curation script that has run goes into
`projects/<identifier>/curation/archive/` with a README (what it did, not to be run again); one that will be needed
again becomes a tool of the generator (`interfaces/instruments/k1_start_run_tables.py`,
`interfaces/eln/collect_chemotion_files.py`, `workflow/library_prerun/pba_reactions.py`).
*checked:* `finish_library_entry.py` writes only when `check_library_consistency.py` reports nothing new;
`generator/tests/library_entries_test.py`.

## 3. Levels, exemplars and quantities

3.1 **Everything that takes part in the process has an entity of its own on the series and on the
experiment level**, with `hlo:specializationOf` to the level above (experiment → series → Fixed). Devices,
ports, body material, phases, molecules in phases, reaction participants, forms. Structural references
point to the own copies on the same level.

3.1a **If an exemplar can bring something about, that is a phenomenon with an occurrence of its own.** A
device or a phase that *can* generate an energy field gets its field on every level - as a thing like a
form, without `hlo:Actual`, with `specializationOf` up to the field of the library if the library names
one. Whether it *occurred* in an experiment is said by the status of its occurrence, when it occurred by
the occurrence's start, end and duration (experiment level, as with transfers and reactions, 3.1b); the
field strength is an Actual.

3.1b **An occurrence is a thing, its status an Actual, the times hang on the occurrence.** Transfers,
reactions, energy fields, **phases** and **interface pairs** (a contact can come and go while both phases
are there - lid off) have one `cpo:Occurrence` per occurrence on the experiment level
(without `hlo:Actual`, ID `…_Occurrence_1`); on it `cpo:hasOccurrenceStatus` → `cpo:OccurrenceStatus`
(Actual, ID `…_Occurrence`) and
`cpo:hasStartTime`/`cpo:hasEndTime`/`cpo:hasDuration`. Whether it occurred stands as
`cpo:hasOccurrenceValue` (Occurred/NotOccurred) on Evidence or Reference of the status; neither of them
means "unknown". The default is one occurrence per experiment, status and times unknown. The coupling
across an interface (`hlo:isCoupledWith`) stays the statement that the quantities can influence each
other; when that applies is said by the occurrence of the interface.
**Exception: permanent occurrences:** if the Fixed entry already carries an
occurrence (room air phase, gravitational field of the site - status Occurred, times empty Actuals), the
levels below get none (`has_permanent_occurrence` in `helpers/time_occurrence.py`) and are not offered in
the occurrence question. That is not "unknown": it cannot be missing or occur several times there, it is
fixed one level higher and read through the chain (7.2).

3.1c **Occurrences are asked in one place, not in the value lists of the exemplars**
(`creation/occurrence_functions.py`). After the reactions every experiment asks, per kind, what something
is known about: phases, reactions and fields as one list, transfers first by place (interface or port),
then by the transfers there. For each one chosen: "How often? (0 = did not occur)". With 0 the first
occurrence gets NotOccurred, with n there are n occurrences with Occurred. The value is thereby fixed and
is not asked again on Evidence or Reference (`occurrence_value_preset`); what is asked is where the
statement comes from (Evidence, Reference or both) and, for occurrences that occurred, the list of times.
Empty list: nothing known, the one occurrence with unknown status stays. Paths:
`experiment:N/occurrences/<kind>:<name>/occurrence:<k>/status/…`, for transfers
`…/occurrences/place:<place>/transfer:<name>/…`. Occurrences 2, 3, … have numbered IDs
(`…_Occurrence_2`, `…_Occurrence_2_Status`, `…_Occurrence_2_StartTime`). The value lists of the exemplars
do not offer occurrences and times. Tasks have no occurrence: a task in the crate has taken place, its
times hang on it. Permanent fields (gravitational field) would have an occurrence with status Occurred
from the literature and empty times.

3.2 **Every quantity of an exemplar exists on every level as a `hlo:Actual` of its own, directly on the
exemplar** - even when nothing is known about its value. The Actual says "this quantity exists here". If
it is missing, that is an error, not a statement.

3.2a **A reference to something that exists already is not a quantity.** `cpo:lastUsedTime`,
`cpo:lastServicedTime`, `cpo:lastCalibratedTime` and `cpo:lastUsedPurpose` point directly to the existing
point in time or the existing task - in an earlier crate, in the experiment before or in the library (the
commissioning, 5.5). No Actual and no task of its own is created. If the target is neither in this crate
nor in the library, the crate gets a **type stub** (`add_reference_stub` in
`creation/device_functions.py`): an entity that names only the type (`cpo:Task` or `time:Instant`), the
same for purpose and points in time. So a crate passes
the requirements on its own too (Device_Information_R3, Device_Time_R1/R2); in a database with all crates
the stub would not be needed.

3.2b **`hlo:Fixed` exists only in the libraries.** No exemplar of the series or of an
experiment and none of its Actuals is Fixed at the same time - not even the Actual that takes over a
Fixed value of the library; it specialises it (3.4).
*checked:* `hlo:Level_NotFixed_Shape` in `shapes/DataQualityShapes.ttl`.

3.3 **The Actual of a level specialises the Actual of the same quantity one level higher.** Collecting
follows this chain, not the owners. Both ways therefore lead to the same Actuals: from the exemplar via
`hlo:specializationOf` to its exemplar one level higher and there to the quantity - or from the Actual
via `hlo:specializationOf` directly. And the Actual above is always that of the **same** quantity (the
temperature specialises the temperature, never the pressure). With every rebuild of levels or Actuals,
keep both ways in view.
*not checked:* not possible in SHACL Core (comparing two paths, "the same property" in general) - only as
SHACL-SPARQL, and that rules out 7.6 (GraphDB). Stays a rule without a check.

3.4 **An inherited value is carried by an empty Actual.** It specialises the value above, the value
itself stays where it was determined (`add_specializing_actual`). There is no state of its own "taken
over": whoever claims that a value holds unchanged makes an assumption - a `hlo:Reference` of type
`hlo:Assumed` with a determination task.

3.5 **What is an instance in the library stays one on every level.** Form and shell of a vessel, the
form of a device, of its body and of the phase of that body, the volume of a body and of its phase (see
3a.2).

3.6 **Literals and terms are not repeated per level** (`isCompositeDevice`, `isSingleUse`, CAS,
`hasDispersionState`, `hasReversibility`, …). They stand once and are read via `specializationOf`.
Example operating mode: `cpo:hasModeOfOperation` points directly to `cpo:Batch`/`cpo:FedBatch`/`cpo:Flow`,
chosen from `cpo:supportsOperatingMode` of the library; the same in all experiments → once on the series,
otherwise on every experiment, and the series carries all modes used.
*checked:* the literals of the library (CAS, SMILES, InChI, InChIKey, molecular formula, PubChem CID,
`isCompositeDevice`, `isSingleUse`, `canReceivePower`, `canRotate`, `isInert`, `isRadioactive`, `hasRInChI`,
`hasRInChIKey`, `supportsOperatingMode`, `hasLotNumber`, `hasLayerCoverage`): `hlo:Literal_LibraryOnly_Shape`,
never on the series or an experiment. The terms `hasDispersionState`, `hasReversibility`, `hasSorptionType`,
`hasChemicalRole`, `hasTransferType`, `hasSolidStructure` and `canCreateEnergyField` stand where they are first
said - in the library, or on the series when the library does not say them - and the generator reads them up the
chain (`helpers/entities.py: inherited_value`); `hlo:Literal_Once_*_Shape` reports a series or experiment node that
repeats one. Together these cover every literal and term that a shape reads through the chain (searched over all
`sh:path` of both shape files). Not checked for the library itself: a fixed reaction repeats roles, reversibility
and sorption type of its template (things_to_implement_after_me.md). Deliberately not checked:
`hasModeOfOperation`, which every experiment carries when the modes differ, while the series carries all of them
(above).

3.7 **`cpo:Parameter` is a constant of a definition** (molar mass of a substance). Every quantity of an
exemplar, also every dimension of a form, is a `cpo:ProcessVariable`. The range of the property in the
ontology decides.

3.8 **State variables exist on the phase and on the material, as different statements.**
The phase carries temperature and pressure as required; the material carries the state of the content as
a whole (set point, controlled variable, measurement without assignment to a phase). A value hangs where
the statement is made; the phase reaches the values of its material through a surroundings collection
path. **With a single-phase material the value hangs on the phase**, temperature and pressure of the
material stay empty and are not offered in its list.

3.8a **A layer of the wall is a phase of the body material** (not a further `madeOfMaterial`): an
enamelled steel vessel, a PTFE-coated stirrer has **one** body material with one phase per layer.
- **State:** following 3.8, a temperature that cannot be assigned to a layer stands on the material, one
  measured at exactly one layer on that layer's phase. `Device_Energy_R1/R2` require temperature/pressure
  on a phase of the body material (with two layers on both), `Device_Energy_R7/R8` collect the material as
  a whole.
- **Forms belong to the device:** the construction determines where a layer ends and how thick it is -
  unlike the filling height of the content, which the process determines. The **core** (the base phase:
  the steel of the stirrer, the glass of the vessel) fills the body form like a single-layer material;
  only **coatings/linings** have a **`cpo:LayerForm`**, which the device reaches via **`cpo:hasLayerForm`**
  on its body form (not `dcterms:hasPart` - parts cut along the geometry, layers through the
  wall thickness; only on the topmost body form, a layer on one part only is `PartialCoverage`). The layer
  phase fills its `LayerForm` (`cpo:fillsForm`), no body phase determines a form itself.
- **`LayerForm`** is not a geometry of its own but a thickness relative to the body form: its only
  dimension is `cpo:hasWallThickness` (required by **`Device_Space_R1`**, its layer shape, offered in the
  value lists of the device as `layer_<name>_wall_thickness`), plus `cpo:hasLayerCoverage` (`cpo:CompleteCoverage` /
  `cpo:PartialCoverage`, individuals of the class `cpo:LayerCoverage`) - a term on the library form, read
  through the chain (3.6). Where the layer lies is said by the order, not by the form.
- **Which layer is inside** is said by the body material with **`cpo:hasInnerLayer`**: only
  this phase touches the content (`creation/phase_functions.py: _phases_facing_contents`). If it covers
  only a part (`PartialCoverage`), the content also touches the layer below - the generator then lets all
  phases touch the content (cautious, never wrong). Without the property every phase touches the
  content. **Known limit:** with three or more layers only the innermost is known, not the order of the
  others; outer contacts are asked. Do not model the order additionally through the forms - there would be
  two sources for it.
- **Library pattern:** body form `cpo:hasLayerForm` → `LayerForm` (thickness, coverage); core
  `cpo:fillsForm` body form, coating `cpo:fillsForm` its `LayerForm`; material and every phase with a
  volume of its own (3a.6); between the layers a Fixed `PhasePairInterface`.
  `check_library_consistency.py` checks the pattern (section "Layers of device walls - rule 3.8a",
  counter-check `generator/tests/library_layer_test.py`). The crate copies the layer forms with the
  forms of the device (`helpers/forms.py: own_form`) and lets the phases fill the same forms of their
  level - it asks nothing and assumes nothing.

3.9 **Yield, conversion and selectivity hang on the reaction participant they refer to.**
`cpo:hasConversion` on participants that are consumed (role Reactant, Substrate, Reagent),
`cpo:hasYield` and `cpo:hasSelectivity` on participants that are formed (Product, Byproduct); catalyst and
intermediate get nothing (a solvent is not a participant, 3.12). Only on participants of a
`cpo:StoichiometricReaction` (elementary reactions are hypotheses), on the series **and** the experiment
level as empty Actuals, never in the Reaction Library. Quantity kind `quantitykind:DimensionlessRatio`:
the crate holds the fraction (0..1), "82 %" is converted on input, unit `unit:UNITLESS` on the value
(`generator/config/units_and_quantity_kinds.json`). For this, the participants of stoichiometric reactions
**have an experiment counterpart**: it specialises the series participant, carries the experiment Actuals (also of the partial order), repeats the species
reference (`dcterms:hasPart`), but not the roles (3.6). Code: `creation/reaction_functions.py`
(`OUTCOME_PROPERTIES_BY_ROLE`, `add_reaction_outcomes`, `copy_reaction_participants`). No requirement
asks for the values.
*checked:* `QuantityKindShapes.ttl` (quantity kind), comparison run.

3.10 **A container of the inventory brings its content along from the library.** A
bottle is a `cpo:ChemicalContainer` (⊑ `cpo:Vessel`) - in the **Device Library** like every device, with
its template (`hlo:Template`), the cabinet in the Organization Library; its content stands in the **Material Library** (2.15) (`cpo:containsMaterial` → Fixed
`MaterialVolume` with phase and species-in-the-phase like the room air), with lot (`cpo:hasLotNumber`),
manufacturer, order number (`schema:sku`), purity (concentration as Reference `Literature`, source the
certificate), initial amount (`cpo:hasMass`, label) and expiry (`cpo:hasExpiryTime`); delivery and opening
hang on the bottle (`cpo:hasDeliveryTime` = end of the delivery, `cpo:hasOpeningTime`). When it is chosen
in the series, the run does **not** ask for the content but copies and specialises it on every level like
the body material (with several contents in its history, it asks only which one - 2.15); it fills the cavity copy of this bottle (`_with_cavities`). The feed starts at the
opening of the bottle (question `flows_from_port`), the crossing at the port arises as at any port.
**Withdrawals:** the filling task names the bottle as equipment (`cpo:usedEquipment`); the usage history
(rules 5.x) then writes the procedure on the bottle per experiment, the amount withdrawn stands in the
crate. The first task of the history is the delivery (`cpo:CommissioningTask`, rule 5.5),
`cpo:lastUsedTime` points to its end until the first use. The bottle stands in a `cpo:StorageCabinet` of
the Organization Library (`cpo:locatedInsideOf`, the cabinet likewise in the room); in the crate it stands
like every device in the room air of its level (`resolve_device_room` goes via the cabinet). Code:
`creation/device_functions.py` (`library_contents`), `creation/environment_functions.py`. Library entries:
`helpers/inventory_entries.py`; gas cylinder, gas cabinet and water line
`projects/hydrogenation_rdy_2026_09/curation/archive/add_supply_test_entries.py` (the template takes the material as a parameter,
`GLASS_BODY`/`STEEL_BODY`).
*checked:* `check_library_consistency.py` (rule 4.1 for all values of the entries), SHACL, comparison run.

3.11 **Template and exemplar.** A template (`hlo:Template`, subclass of
`hlo:Fixed`; carries **both** types, so that everything that excludes Fixed excludes it too without
inference) stands for a kind of object ("glass bottle 250 mL"); an exemplar ("bottle no. 1") is a Fixed
entry that specialises it via `hlo:specializationOf`. The exemplar takes over what it does not say itself
- form, body, ports, flags -, but never its history, its location, its content and its times
(`creation/device_functions.py`: `resolve_exemplar`, `_EXEMPLAR_ONLY`). In the crate the copies of the
parts taken over are named after the **exemplar** (`bottle_x_opening_SeriesSpecific`), not after the
template - otherwise two exemplars of the same template would collide (`helpers/identifiers.py`:
`library_name_alias`). If the name of the exemplar starts with that of the template
(`three_neck_flask_100mL_01` to `three_neck_flask_100mL`), the exemplar keeps its name. Shapes: a template
stands nowhere and has no usage (exclusion `[ sh:class hlo:Template ]` in Device_Space_R2, Device_Time_R1,
Device_Information_R3; Device_Energy_R5 excludes every Fixed device, templates included - a kind of object
creates no field); a **library**
exemplar is exempt from form, shell and body (exclusion `[ sh:and ( [ sh:class hlo:Fixed ] "specialises
a hlo:Template" ) ]` in Device_Structure_R1, Device_Structure_R2, Device_Substance_R1), the template is
checked. **Fixed only:** the single-use templates (vial, syringe, cap, septum - `cpo:isSingleUse`) are
`hlo:Template` too; their crate copies specialise the template directly and must have a form of their own
(counter-check: a vial of the series without a form → three reports). Two ways of
using a template: with exemplars in the library (bottles) or - for single-use items - directly in the
crate, every use a fresh piece. A single-use template may have a location (where the stock is; through it
the crate finds the room), but a template does not need one. **Single-use or not:**
`cpo:isSingleUse true` stands only on a template and says that every use is a fresh piece
directly from it (checked by `hlo:SingleUse_OnlyTemplate_Shape`); that an entry stands for a kind is said
by `hlo:Template`. A template without the flag is used only through its exemplars and is not offered in
the device selection (`create_all_devices`). Both forms are recognised by
`helpers/context_links.py: is_exclusion` as an exclusion (7.7). The full template level - a common
superclass instead of the Fixed exceptions - stays in
[`things_to_implement_after_me.md`](things_to_implement_after_me.md).
*checked:* SHACL, `check_context_requirements_consistency.py` (check 11), comparison run.

3.12 **The solvent stands on the phase, not on the reaction.**
`cpo:hasSolvent` (⊑ `dcterms:hasPart`) points from a liquid phase to **its own** species of the same level
(3.1) - the exemplars that `dcterms:hasPart` names as well; several for a mixture, without a main solvent
(the ratio is in the amounts). The role `cpo:Solvent` is deprecated and not offered
(`find_individuals_of_class` leaves out `owl:deprecated`); a solvent that takes part in the reaction is in
addition a participant with its own coefficient. **Never inferred:** only from the source (ELN group
`solvents`, field `solvents` in the sheet) or from a person; empty means unknown. **Asked** only for a
liquid phase with at least two species, and only once its species are fixed
(`top_up_phase_concentrations`, after the transfers - at the same place where a phase with one species
becomes pure); before that "the same in every experiment?" (7c.3). **No library names a solvent**, not
even on the content of a bottle (3.10): whether a mixture serves as a solvent is decided by its use in a
series - otherwise it would be an assumption about every future use; it is asked in
every crate. Requirement: **`Phase_Substance_R8`**, an assignment (7.16) that never reports - the species
already belongs to the substance context via R1, `helpers/context_links.py` does not link it a second
time (number of links unchanged). Concept only: `supportsSolvent` in the Reaction Library, roles in the
mixture (cosolvent, additive, inert), a warning as an existence requirement. Code:
`creation/phase_functions.py` (`add_phase_solvents`), `helpers/series_statements.py`.
*checked:* `check_library_consistency.py` ("Solvents of phases": every value is `hasPart` of the phase,
liquid phases only; library and crates), SHACL, comparison run.

3.13 **Species per experiment.** A series phase
names everything the series **can** contain; an experiment phase only what occurs in **this** experiment. Which
substance occurs only in some experiments is said **once for the series**, not per phase: in the sheet
`species_per_experiment: {<substance>: [experiments], source: ...}`, in the generator the question
`experiment:<n>/absent_species` (only with more than one experiment; without the field none, adapter rule A14).
A substance absent from an experiment is left out of its phases - except the contents and bodies that a
library describes (a bottle of MnCl2 holds it whether it was used or not) - and with it its transfers, port
crossings and occupations (unless it is still in all the phases concerned), and every reaction one of whose
participants it is: such a reaction is not created in that experiment, its occurrence is not asked. Decided
against: the substance per phase (`experiments` at a species of a phase list) - the same statement at every
phase a stream carries it through, and port crossings bring it along anyway. Code:
`creation/phase_functions.py` (`ask_absent_species`, `keeps_species`), `creation/reaction_functions.py`
(`_absent_participants`), adapter `_absent_species`/`_absent_reactions`.
*checked:* `pba_synthesis`: experiment 1 without MnCl2 and the Mn/Ni product (transfers, reaction), experiment 2
without the Ni product. `hlo:Transfer_DroppedSpecies_Shape` in `shapes/DataQualityShapes.ttl`: no experiment transfer (port crossings
included) moves a species at a phase that left it out although its series phase lists it - SHACL-SPARQL, so
pyshacl only, not GraphDB; counter-check `generator/tests/absent_species_shape_test.py`.
**Empty phases are left out:** a phase of an experiment that is left
without any substance this way does not exist in that experiment - no empty phase (`Phase_Substance_R1`) - and a
material left without a phase does not exist there either (in `pba_synthesis` the charge of MnCl2 in
experiment 1). With them go what only they own (values, times, form) and the references to them (series
`hlo:hasSpecialization`, contexts, the streams at the ports); interfaces, transfers and port crossings are not
created for them. The series keeps them. A device whose every stream of the experiment was dropped and which
holds nothing but its library content (the stock bottle of MnCl2 in experiment 1) is no equipment of that
experiment's tasks, so it is not recorded as used there (usage history, rule 5.5); at the series level it stays
equipment. The experiment number of a material is read from its ID
(`..._ExperimentSpecific_<n>`), not from its position among the specializations of its series entity.
Limit: the questions about such a material at the experiment level come before it is dropped (materials are
created before the phases know their species) - their answers stay in the answer file unused; asking
`absent_species` before the materials would change the order of the whole run. Code:
`drop_empty_experiment_phases` in `creation/phase_functions.py`.
*checked:* `pba_synthesis`: experiment 1 without the Mn charge, no `Phase_Substance_R1`.

## 3a. Forms

3a.1 **A form describes a region of space, not a thing. It belongs to whoever sets the boundary of the
region** (`cpo:definesForm`); everything else that takes up exactly the same region points to the same
form with `cpo:fillsForm`. The shell of a device (`cpo:hasEnvelopeForm`) stands beside `definesForm`, not
below it. `cpo:hasForm` is only the common superproperty of the three, the generator does not write it. No
role on the form.
*checked:* `hlo:Form_DefinedOnce_Shape` in `shapes/DataQualityShapes.ttl` - every form has exactly one
thing that defines it, unless it is a cavity or part (`dcterms:hasPart`) of a form or a Reference/Evidence
value.

3a.2 **Rule A: every region of space has exactly one form entity per level; whoever fills exactly this
region points to it.** **Rule B: whoever fills only a part gets a form of its own; the shared dimensions
are the same Actuals.** From this:

| Thing | Form | |
|---|---|---|
| device | defines its form (and its shell) | |
| room (Fixed) | defines its form | |
| **material** | fills the region it sits in: the cavity of its device (content, stream in a device), the device form (body material), the room form (room air; on the series/experiment level the room air defines the copy, 3a.4) | A |
| material without a device (stream between devices) | defines a `cpo:IndeterminateForm` on every level | |
| **only non-dispersed phase of a material** | fills the same form as its material - everywhere: body material phase, room air phase, coolant in the jacket, gas in the sparger, phase of a stream between devices | A |
| gas/liquid phase next to others in a device | defines a form of its own: class and cross-section of the cavity (the same Actuals), its own filling height | B |
| solid phase next to others in a device (content, not body material) | defines a form whose class is asked | B |
| core of a layered body material (3.8a) | fills the body form of the device like a single-layer material (approximation, 3a.8) | A |
| coating/lining (3.8a) | fills its **`LayerForm`**, which the **device** defines (`cpo:hasLayerForm` on its body form); nothing asked, nothing assumed | |
| phase next to others in a stream between devices | defines an `IndeterminateForm` | B |
| phase dispersed in another phase | defines an `IndeterminateForm`: no single region, its size distribution says what is known; alone in its material it is dispersed in nothing and fills its form like any single phase | B |

3a.3 **Which dimensions a form needs is said by its class** (OWL restrictions in the CPO,
`someValuesFrom cpo:ProcessVariable`, only on the leaf classes); the generator reads them
(`required_properties_of_class`), no list in the code. Every dimension and every aspect ratio is an
Actual (3.2, 3.7); **nothing is calculated** - neither aspect ratios nor volumes from dimensions. A hollow
form carries its cavity (`cpo:hasCavityForm`), which has no dimensions of its own but shares the Actuals of
the hollow form in the opposite role (`cpo:cavityCounterpart`). `cpo:IndeterminateForm` is a statement
("the form exists, it cannot be given"), not a gap; it requires nothing.
*checked:* check 9 in `check_context_requirements_consistency.py` (restrictions ↔ form shapes). The cavity
of a hollow form is built by the generator and checked as data quality (`hlo:Cavity_SolidCylinder_Shape`,
`hlo:Cavity_Annulus_Shape`); that a cavity hangs only at a hollow form is deliberately not checked - a new hollow form class gets its cavity
restriction and its line in that check.

3a.4 **Every level has its own copy of a form**, which specialises the form of the level above, every
dimension likewise (`helpers/forms.py`, `own_form`) - together with cavity, layers (`cpo:hasLayerForm`) and
parts (`dcterms:hasPart`; the blade of the stirrer); the device offers their dimensions in
its value lists (`layer_<name>_…`, `part_<name>_…`). **Whoever creates the copy on a level defines it;
whoever gets a copy already created fills it** (`own_forms`). So the room air on the series and experiment
level defines the copy of the room form - the room is a place and has no levels -, while the body material
fills the copy of its device. `fillsForm` always points to a form of the same level.

3a.5 **The material is the sum of its phases and fills the region it sits in. Its only non-dispersed
phase fills the same form; only several phases have forms of their own** (`_material_filled_alone`,
`add_phase_form`; one rule for all materials). A phase defines a form of its own with
dimensions only next to others in a device, and that form is never hollow; outside a device there is no
geometry for the part of a phase (`IndeterminateForm`). A phase cannot know more about its form than its
material. **Consequence:** a single-phase material in a device says "the cavity is full". If it is not,
the gas space above belongs to the material as a phase of its own (the sample in the vial: `Sample_Phase`
and `Vial_Headspace_Phase`, each with its own form and filling height).

3a.6 **Volume:** a phase with a form of its own has as its volume the outer volume of that form (the same
Actual). A phase that fills its material alone and the material have **one** volume, the same Actual on
every level (`_share_material_volume`): if the material has one already (room air), the phase takes it
over, otherwise the material takes over that of the phase (body material, streams). For a body material
that is the wall volume, not the outer volume of the hollow form. **Not for a dispersed phase**, even when
it is alone: its volume is that of its particles, bubbles or droplets, that of the material the envelope
volume of the space they are spread over (bulk volume) - two quantities.

3a.7 **Every form is checked once, under whoever defines it:** forms defined by a device (with shell,
cavity, parts and layers - `cpo:hasLayerForm`, `Device_Space_R1`) by the device requirements, forms
defined by a phase - or on the series/experiment level by the room air that its air phase fills - by the
phase requirements; both start from the device or the phase (7.11). This works because the
requirements depend only on the class, not on who defines the form; if a class needs other dimensions
depending on its use, 3a has to be decided anew.

3a.8 **Deliberate approximations:** room air = room (really the room minus the devices); a device that is
flowed through (jacket, sparger, later lines) is full - a line filled only partly is not represented;
streams between devices cannot be determined until lines are devices; the core of a coated part fills the
whole body form (really the body form minus the layers, 3.8a).

3a.9 **Lines need nothing of their own:** a line is a device subclass with a tube
form (`cpo:TubeForm`) in the Device Library. It defines its form, body material and body material phase
fill it, the stream (`materialContainedIn` → line) fills its cavity, and following 3a.5 its only phase
fills it as well - the line counts as full; several phases define forms of their own with the
cross-section of the cavity. Classes: **`cpo:Pipe`** (pipe, tube, hose line - the difference lies in the
material, not in the class) and **`cpo:PipeFitting`** (coupling, union, adapter, elbow, T-piece, reducer).
First entries: the tubes of the K1 Start system in Lab 208
(`projects/pba_synthesis/curation/archive/add_k1_system.py`).
**Connections stand in the library:** two ports screwed together name
each other with **`cpo:isConnectedTo`** (symmetric, on both library ports, read via
`hlo:specializationOf`); a port that leads into the content of a device without a counterpart port
(sparger in the vessel, suction tube in the bottle) with `cpo:opensInto`. There is no stream between
connected ports: every device has its own (`materialContainedIn`), and the generator creates at the
connection exactly one crossing from the one stream into the content of the other device - at the end the
stream reaches; the end at which a stream leaves its device only if none arrives on the other side
(`creation/phase_functions.py`, `create_port_crossing_transfers`). So that the chain has no gap, every
device that is flowed through needs a cavity - for a pump and a flow controller a part of its own (pump
head, flow channel) with a tube form that carries the inlets and outlets.
*checked:* `check_library_consistency.py`, section "Joined ports name each other" (both sides, two
different devices); `hlo:Port_Joint_Shape` (both ways, every level).

3a.10 **Whether a device can take up material is said by its form:** if one of the
forms it defines has a cavity (`cpo:hasCavityForm` - cup, tube, annular jacket, closed hollow cylinder), its
content is asked (`creation/device_functions.py: device_has_cavity`). There is no flag for it besides: it
would say the same a second time.

3a.11 **The own form of a device is the one its body material fills; the shell is a second form of the
device.** The boundary of the shell is set by the device too, and for most devices the shell is the same
instance as the own form (a plain cylinder, a cuboid). Only where the shell differs (stirrer, jacket,
syringe) is it a form of its own that no material fills. Every device has a shell, also a composite device
(`Device_Structure_R2`: the shell is a form, hence Structure; its dimensions are Space, `Device_Space_R1`).
`cpo:hasEnvelopeForm` is not a subproperty of `cpo:definesForm` but stands beside it under `cpo:hasForm`, so
a differing shell cannot stand in for a missing own form, not even under RDFS inference. A device whose body no geometric
class describes, not even its main body, defines a `cpo:IndeterminateForm` (asked for nothing); its parts
(`dcterms:hasPart`) carry the dimensions. Where a main body of a simple class exists (the shaft of a
stirrer), that body is the form and the rest hangs on it as parts.
*checked:* `Device_Structure_R1` requires a `cpo:definesForm`. That the body material fills exactly this
form is checked as data quality (`hlo:BodyMaterial_FillsForm_Shape`).

## 3b. Contacts and transfers

Follows from 7c.1: the series fixes what exists.

3b.1 **Contacts are complete:** every phase borders on every phase it touches - also across material
boundaries (interface pairs). Every device standing in the air borders on the room air (created by the generator for
every device standing directly in the room air - `cpo:locatedInsideOf` its Environment - with the body phases that
face outwards, instead of asked; a device without a body, a line whose content comes from a nameless source, has
nothing that could border; a device mounted on another one stays a question; checked by
`hlo:Device_RoomAir_Contact_Shape`); an immersed sensor
on every phase it reaches through, and on the wall it is led through. Through these contacts the generator
couples the temperature and pressure of neighbouring phases (`hlo:isCoupledWith`), and a phase collects the
coupled values of its neighbours (Phase_Energy_R8/R9, over the coupling). A contact that exists only at times
belongs to it too: the gas space of a vessel that is open at times borders on the room air (vessel,
vial). Where exactly the interface lies (at the opening) is not described - that it lies
between the two phases is said by the phases.
**Within a material of the library too:** `hlo:Phase_SameMaterial_Interface_Shape`
also holds for Fixed entries, so a library material with several phases needs a Fixed `cpo:PhasePairInterface` between
them, as the layers of a body material have (3.8a). No library content has more than one phase today (a bottle holds
its content without a gas space above it; the inventory tool gives every content one phase); whoever adds
one creates the interface with it.

3b.2 **Transfers are the potential ones, not the observed ones:** whether one took place is said by its
occurrence in the experiment; where one cannot take place, the reason stands in the model (3b.3).

**The generator creates the potential transfers from a rule table** (`potential_transfers`
in `creation/phase_functions.py`) and does not ask for substances, types and directions. It interprets no
physics in doing so: whether a substance really evaporates, dissolves or melts under the conditions is said
by the occurrence alone. Every type pair of the table holds for **every substance of both phases, in both
directions**; what counts is only the states of matter (`cpo:SolidPhase`/`LiquidPhase`/`GasPhase`) and, for
gas/gas, whether a phase is dispersed.

| Interface | potential transfers (every substance of both phases) |
|---|---|
| solid / liquid | Adsorption + Desorption (from / into the liquid; the other end is the occupation of the interface), Dissolution + Solidification, Melting + Freezing |
| solid / gas | Adsorption + Desorption (from / into the gas), Sublimation + Deposition |
| liquid / gas | Absorption + Degassing **and** Vaporization + Condensation |
| liquid / liquid | Liquid Exchange (`cpo:LiquidExchange`, without a counterpart, both directions) |
| gas / gas (gas space of an open vessel / room air, bubbles / gas space) | Gas Exchange (`cpo:GasExchange`, without a counterpart, both directions) |
| solid / solid | Solid Exchange (`cpo:SolidExchange`, without counterpart, both directions): the possibility is there rather than an assumption that two solids exchange nothing. Concerns almost only interfaces without an inert side (catalyst/RDY of the hydrogenation) |
| same state, exactly one phase dispersed (bubbles, droplets, particles) | **in addition** Coalescence (dispersed → continuous) + Dispersion, for every state, not instead of the exchange: a substance can pass between the two without the bubbles, droplets or particles merging - liquid/liquid extraction is a Liquid Exchange |
| inert wall / anything | none (3b.3) |

Name and key of a transfer follow from phases, substance and type (`transfer_name`), so the answers on flow
rate, occurrence and time stay valid.

**No chain of potential transfers:** a transfer at an
interface does **not** add its substance to the target phase. Otherwise the next potential transfer would
start from there (isopropanol "solidifies" into the platinum and "sublimes" from there), and the crate
would grow with the space of possibilities instead of with knowledge (the hydrogenation crate would grow by
about 60 %). `dcterms:hasPart` of a phase is its **stated composition**: everything that
can occur in it, also what only gets into it through a reaction or a transfer (the products and NH3 in the
liquid of the hydrogenation, dissolved H2). **Whoever knows or assumes that a transfer took place names the
substance in the composition of the target phase;** then it gets its potential transfers there. Physics
comes in through the occurrences: what did not take place is stated explicitly as not occurred (also as an
assumption, one assumption task per reason), the rest stays unknown - and creates no further substances
and transfers.

**Ports are exempt from this:** through a port a phase passes as a whole, a stream drawn off carries all
substances of its phase along (not a possibility but the statement "this stream comes from that phase"). If
a substance gets into a phase this way after one of its interfaces has been described, the generator
creates the potential transfers for exactly this substance there according to the table
(`follow_up_transfers`; keys under `transfer_follow_up/`). **At ports nothing is asked,
it is followed up:** if a substance gets into the phase a stream is drawn off from, it gets its
PortCrossing (under the key it would have had from the start). Interfaces and ports take turns until no
substance arrives anywhere any more; this holds for every crate, nothing about it is tied to a set-up.

**A stream with several phases** (in the mixing zone of `pba_synthesis` liquid, precipitate and an air core
flow together): the series is asked once which of its phases cross at its ends
(`stream_port_ends:<stream>/crossing_stream_phases`, a list; the experiments take the choice over). Each
crossing phase gets its own crossing at each end, with its own phase on the device side - the key of the
stream end then names the phase as well (`port_crossing:<stream>-<port>-<phase>`). A stream with one phase
keeps the key without the phase.

3b.3 **Glass, stainless steel and PTFE are inert:** no mass transfer, not even adsorption - a deliberate
simplification that neglects adsorption on walls. It stands as `cpo:isInert true` on the substance in the
Chemical Entity Library (glass, stainless steel, PTFE, polypropylene); for a phase that consists of inert
substances only, the generator does not ask for transfers (`_phase_is_inert`). The note is the reason why
there are none; whoever removes it gets the questions back. The model rule itself stands in the
Assumption Library (`task:assuming_inert_phases_exchange_nothing`); the interfaces concerned do not point
to it (scope of the model, not a value - in the crate only via the library snapshot, 2.3).

3b.4 **What is taken off is a device of its own:** a lid, a screw cap, a septum -
not a further phase of the vessel body, otherwise unscrewing would be a phase separation. Lid and cap are
`cpo:Lid`, the septum `cpo:Septum` (part of its cap). What is led through the lid (stirrer, sparger,
sensors) borders on the lid, not on the vessel wall; the gas space borders on the lid or the septum.
Today: `device:vessel001_lid` (glass, part of the reactor, used in the hydrogenation),
`device:vial_cap_template` (PP) and `device:vial_septum_template` (PTFE), both single-use.

**A screw cap is a cup upside down** (the GL45 caps of `pba_synthesis`): one
object, a `cpo:Lid` with a wall (labware entry with `wall` instead of `inner_diameter`), its cavity taking in the
neck of the bottle - which the bottle model leaves out, so the two forms do not overlap in the model. A lid without
a wall stays a ring around its opening (the vial caps).

- **Its content** is asked per crate like that of every cavity: "Which type of material, other than the gas around
  it, does X contain?" - `Stream`, `MaterialVolume` or "Nothing but the gas around it" (no material is made; on the
  bottle that gas is the headspace). Whether a device holds something is its use, not a statement of the library.
- **Where it sits:** `cpo:locatedAt` the opening port of its bottle (Device → Port). The generator points the
  cap of each level at the port of the same level; its room is that of the bottle (`resolve_device_room` goes on
  from the port via `cpo:isPortOf`), and the climbing paths of the energy fields take `cpo:isPortOf` as a step
  up (`helpers/energy_fields.py`, `PARENT_PROPERTIES`; the three context path shapes).
- **Its ports** have no position on it - CPO 1.0 has no form of an opening (things_to_implement_after_me.md).

3b.5 **Ports: opening or connection.** The opening of a vessel (`cpo:DeviceOpening` on the vessel) is used
only with the lid taken off: charging (pouring in liquid, adding solids) and tipping out at the end. What
goes in or out while the vessel is closed runs through a connection on the lid: the sample through
`port:vessel001_lid_sampling_port` (dip tube into the liquid). Taking the lid off and putting it on are
tasks of their own ("Putting on the lid" at the end of "Charging the reactor", "Taking off the lid" at the
start of "Working up", functions Assembling/Disassembling).

3b.6 **A port that opens into the content of another device** (`cpo:opensInto` on the library port; the
outlet of the sparger opens into the vessel) has no stream behind it. The stream in the device ends
there, and its crossing goes directly into the chosen phase of that content (the bubbles), in the
direction of flow (`_port_opens_into`, `_phase_in_content_of`).

3b.7 **Dissolving a solid is a transfer and then a reaction in the liquid** (the convention for every
crate). How it works:

- **Transfer:** a solid that dissolves (a salt, a hydrate) goes into the liquid unchanged, as the same species.
  This is a `cpo:Dissolution` transfer at the interface solid/liquid.
- **Reaction:** in the liquid the species falls apart, e.g.
  `K4[Fe(CN)6]*3H2O > 4 K+ + [Fe(CN)6]4- + 3 H2O`. The reaction has `cpo:occursInPhase` the liquid.
- **The undissolved solid** is a dispersed solid phase of the same material.
- **The dissolved solid** stands in the composition of the liquid only as a species passing through: the
  transfer brings it, the reaction takes it away.
- **Conversion:** the reaction is not assumed to be complete. Its conversion stays unknown unless it was
  measured.
- **Drawing off the liquid:** a stream drawn from the liquid would carry the species along (3b.2, ports). Where
  only the ions and the solvent leave, the PortCrossings of the dissolved solid are stated as not occurred,
  with an assumption task of their own (a simplification: the dissolved solid passes through).
- **A solution made up before the series** (a stock solution) is dissolved in its preparation, which the
  inventory describes (rule 2.15, `inventory_tool.py prepare`); its content holds only the ions and the
  solvent, and the crate starts from it. In `pba_synthesis` the stock solutions are poured into the
  feed bottles, so no hydrate appears in the crate at all.
- **No reaction at the interface:** a reaction that uses up the solid at its surface is not modelled. The
  generator has no transfer for it, and the convention does not need one.

**Precipitation is the reverse case without a transfer:**

- A reaction in the liquid whose product is a solid puts the product directly into a dispersed solid phase of
  the same material, e.g. the PBA in `Mixing_Zone_Solid_Phase`.
- The reaction has `cpo:occursInPhase` the liquid. The product stands only in the solid phase.
- There is no `cpo:Solidification` transfer: the product is a solid from the start.
- Coagulation into a continuous solid happens later, in the vessel that collects the suspension or in a
  sample. There it is a phase of its own.

## 4. Values, Evidence and Reference

4.1 **A value stands on an Evidence (measured, observed, calculated) or a Reference (assumed,
literature, specification), never on the Actual.** Every value has a determination task; there is no way
in which a value comes about without a task.
**The source stands on the Reference** (`hlo:hasSource`, domain `hlo:Reference`),
never on the task that looked it up - the task says when, who and how (times, `cpo:performedBy`,
description). If a task looks up several values, every Reference carries the source. On a task, the
domain would make the task a Reference under RDFS inference. If the
source is available as a file (a certificate of analysis), the Reference names it in addition with
`hlo:hasSourceFile` (ObjectProperty, range `schema:MediaObject`) - the text in
`hlo:hasSource` stays, because `hlo:hasSource` is a DatatypeProperty and cannot point to an entity.
**The source is asked** for References of type
`hlo:Planned` and `hlo:Literature` - assumed, set and controlled values have no document they come from. In
the sheet it stands as `document` on the value; if it is missing, `none: reference_sources` says "no
document known" (with a source line of its own via `none.sources`), otherwise the question stays open. No
source stands on a task - not even on the planning that read the paper: there the DOI stands in the
description.
**Exception reaction mechanism:** a Reference mechanism of the library gets an entity
of its own on the series and experiment level (its elementary reactions get substances from the
placeholders, places and rates), but in content it is the same. Type (asked as for every Reference),
source (required) and determination task stand only on the library entry and are read via
`hlo:specializationOf` (like 3.6), not repeated per level.
**Exception file data:** the creation and modification date of a file
(`cpo:dateCreated`/`cpo:dateModified`) stay Actuals with `rdf:value` directly on them, without Evidence
and task - read from the file system, a property of the file like `cpo:fileSize`, not a statement about
the process (`_set_file_metadata` in `creation/media_object_functions.py`).
**Exception library tasks:** a value in the crate may name a task of the
library directly in `cpo:hasDeterminationTask` without that task naming it back in `cpo:determines` -
otherwise the run would have to write into the library (2.2). This holds for series and experiment values
alike; there is then no task of the crate next to it. Today only the assumptions the generator makes in
every crate (`libraries/assumption_library.jsonld`, see `LIBRARY_ASSUMPTIONS` in
`helpers/evidence_reference.py`): the amount fraction 1 of the only species of a phase names
`task:assuming_single_species_phase_is_pure`. If a value names a library task and a task of the crate, both directions
hold for it again. In the libraries themselves the exception does not apply.
**Series value and experiment value of the same quantity** each have their own task:
the task of a series value is never a template for the experiments; templates arise only from experiment
values (`_find_series_stubs`). If it is the same activity after all, the task stage merges them ("covered
by existing").
*checked:* in the libraries `check_library_consistency.py` (task in both directions, no value on the
Actual, on exactly one variable, ID after 1.6; counter-check `generator/tests/library_rule_4_1_test.py`);
in crate and libraries together `shapes/DataQualityShapes.ttl` (`hlo:Actual_NoValue_Shape`,
`hlo:Value_Variable_Shape`, `hlo:Value_Type_Shape`, `hlo:Value_DeterminationTask_Shape`,
`hlo:Value_TaskBothWays_Shape`; counter-check `generator/tests/rule_4_1_shapes_test.py`, eleven damaged
crates, all three exceptions included).

4.2 **Evidence and Reference are asked as a list per exemplar and level** (`helpers/value_sources.py`):
series - Evidence, Reference, "known in the experiments"; experiment - Evidence, Reference, only what the
series has marked as known is offered. This holds for the times and offsets of the tasks too - without
exception; times and offset of a task are created in one question path, otherwise there would be two lists
under one key.
**What the library knows already is offered too:** quantities whose value stands
on the Fixed entry (density of a body material, temperature of the room air, concentration of O₂/N₂, form
dimensions of devices and room air) get their own empty Actual with `specializationOf` and still stand in
the lists; whether the experiments know something about them is said by the series. The library value
stays where it is - a measurement or assumption on a level is added as an Evidence or Reference of its
own. Form dimensions stand in the list of whoever defines the copy of the form (`form_…`,
`envelope_form_…`), without aspect ratios and without shared dimensions (cavity).

4.3 **Every value with `qudt:value` carries exactly one unit as an IRI.** Fractions carry `unit:UNITLESS`,
percentages are converted on input. So does a value that only states a bound (`hlo:hasLowerBound`,
`hlo:hasUpperBound`), except a `time:Instant`, whose bound is a date and time.
*checked:* `hlo:Value_Unit_Shape` in `shapes/DataQualityShapes.ttl`.

4.4 **Which quantity kinds a property allows stands in the ontology, not in the code:**
`cpo:valueHasQuantityKind` on the property, inherited via `rdfs:subPropertyOf`
(`hasInnerHeight` from `hasHeight`).
- **One allowed quantity kind:** the Actual carries it, the generator sets it without asking
  (`quantity_kinds_of_property`).
- **Several allowed** (`hasFlowrate`, `hasConcentration`, `hasOccupationExtent`, `hasFieldStrength`):
  **the Actual carries none** - each would be a statement nobody made. **The kind belongs to the value
  and is asked on the value:** the quantity is an entry in the value lists like any
  other; only whoever gives an Evidence or Reference says in which kind it stands
  (`…/evidence_quantity_kind`, `…/reference_quantity_kind`), and the kind determines the choice of units.
  Two values of the same quantity may stand in different kinds (GC: amount fraction, literature: mass
  fraction). Where the kind follows from the structure, nothing is asked (the field strength from the
  field type). One Actual, whatever kinds its values stand in; coupling goes through the property.
- An Actual without values is fine: it says "this quantity exists".

*checked:* one shape per property in `shapes/QuantityKindShapes.ttl` (pure SHACL Core, so that they also
run in GraphDB), generated from the ontology with `generator/workflow/generate_quantity_kind_shapes.py`;
`--check` reports when the file is out of date after a change to `cpo:valueHasQuantityKind`.

4.5 **Units stand in `generator/config/units_and_quantity_kinds.json`**, not in the
code. New entries are only appended, order and spelling of existing ones stay (answers depend on them).
Every quantity kind the ontology assigns to a property has a choice of units there or is dimensionless. A
unit that QUDT connects to its quantity kind only through the same dimension stands in
`accepted_dimension_matches` with a reason.
*checked:* `check_library_consistency.py` (comparison with the QUDT version from the Ontology Library).

4.5a **The rate of change of a ramp step has a unit of its own:** it is the profile
quantity per time (K/min for a temperature ramp, rev/(min·s) for a speed ramp) and does not inherit the
unit of the profile. Which quantity kind the rate has stands per quantity kind of the profile in
`change_rate_quantity_kinds`; if it is missing there, the kind of the rate is asked first. As for every
value, the unit is asked after the value and only if one is given
(`helpers/profile_variables.py: change_rate_unit_options`).
*checked:* `check_library_consistency.py` (the rate quantity kinds against QUDT; when loading
`helpers/units.py`: each has a choice of units).

4.6 **Every task that is not a template carries start, end and duration, as a part task also a start
offset** - also assumptions and desk work in the libraries. Unknown is an empty
`hlo:Actual`, not a missing property; otherwise a rule would be needed for when a task gets times.
**Templates may carry times but do not have to:** a template
is a task on the series or in a library that is specialised one level below - the same activity for all
experiments, without a single point in time. The generator gives times only to the planning of the series,
because it took place once (`_wants_series_times` in `creation/task_functions.py`); all other templates on
the series have none. Library tasks such as the commissioning or looking something up are not templates
but took place once - for them the times stay required.
*checked:* `hlo:Task_Times_Experiment_Shape` (every task of an experiment, a part
task also with start offset) and `hlo:Task_Times_Library_Shape` (every library task except `hlo:Template`)
in `shapes/DataQualityShapes.ttl`, Warning; series templates and type stubs without a name excluded.
Counter-check `generator/tests/task_times_persons_shapes_test.py`.

4.7 **A task that reads off times names its time source:** if a
`cpo:MeasurementTask` or `cpo:ObservationTask` determines a point in time or a duration, it is asked where
the times come from: a fixed list (`TIME_SOURCES` in `creation/task_functions.py`, several allowed,
"Other" requires a specification), then optionally which one exactly (whose phone, which clock in which
room, which computer). The generator writes the first sentence of the description from it ("Source of the
times: …"), not a property of its own. Planned or assumed times have no clock and are not asked. The same
holds for the library tasks: `task:reading_commissioning_records` and `task:reading_maintenance_records`
start their description with the sentence (entered by hand); a library entry tool has to ask it in the
same way.
Clocks as devices of the library: [`things_to_implement_after_me.md`](things_to_implement_after_me.md).

4.8 **Software hangs on the task it was used with:** `cpo:usedSoftware` from
the task to an entry of the Software Library, asked as a list like the devices (only if the library knows
software). Through `cpo:hasDeterminationTask` every value thus says with which software it was created or
completed. Only this direction, the library is not changed (2.2). The experiment task takes over the
statement of its series template. A file that software wrote says so through its generating task
(`cpo:generatedBy` → `cpo:usedSoftware`), so there is no property for it on the file itself. Software as
an acting agent (`cpo:performedBy`) is not modelled
([`things_to_implement_after_me.md`](things_to_implement_after_me.md), self-optimizing campaigns).

4.9 **A task names its purpose, not its course:**
`cpo:realizesFunction` points to one of the 38 functions in `cpo:FunctionList` - two levels, each
selectable, the broader terms as the answer when only the kind is known. Every function has a
`skos:definition` with a source (CHMO, OBI, XDL, ORD, DEXPI; defined by us only where nothing fits, and
marked so). Which ones are offered is said by `cpo:offersFunction` on the task class (a branch brings its
narrower terms along; without a declaration that of the superclass holds). If a class offers exactly one,
the generator sets it without asking (`Determining`, `Setting` - a setting task only
specifies a value, what happens afterwards is carried by the task that executes it -, `Sampling`,
`PlanningProcedure`, `RecordingData`, `Calibrating`) - what is determined is said by the value, not by the
function. A section that only has parts is asked for its **own** purpose beyond its parts (empty allowed,
in the sheet `functions: []`) and in addition inherits the functions of its parts - so one sees at a
glance which functions a section groups (also `Determining` from a measurement in it). `ReactingChemicals` is carried by the task that brings a reaction about ("Running the
hydrogenation", "Reacting at room temperature"): it aims at the intended reaction (`cpo:aimsAt`; side
reactions not - whether they occurred is said by their occurrence) and hangs in the "Main operation",
which inherits the function; stirring, cooling, feeding in it carry their own (like a TransferTask that
aims at the crossing it brings about). The fixed shells
"Preparation", "Main operation", "Work-up" have no function of their own (7c.5a). Checked by
`shapes/FunctionShapes.ttl` (generated by `generator/workflow/generate_function_shapes.py` from
`cpo:offersFunction`; tasks with parts excluded).

4.10 **A set profile is the Reference of an Actual.** A course that was set
(ramping up, holding, ramping down) is a `cpo:ProfileVariable` with `hlo:Reference` and
`hlo:hasReferenceType hlo:Set` on the Actual it specifies - like any other set point, with a
`cpo:SettingTask` as determination task; the task that executes it points to it with
`cpo:executesProfile`. The rotational speed of a device is `cpo:hasRotationalSpeed` (QuantityKind
RotationalVelocity) and exists only where the library says `cpo:canRotate true` (like
`cpo:canReceivePower` for `cpo:hasPowerInput`). A profile never hangs on the device itself. In the sheet
the profile is a value with `steps` (`kind: set`, `executed_by`).
*checked:* Device_Energy_R4 (the rotational speed on the series and every experiment),
`QuantityKindShapes.ttl`; touchstone hydrogenation.

4.11 **An observation without a quantity is an ObservationTask with its phase:** what was seen but is not a quantity of the crate (the colour of a powder, the
look of crystals, a colour change) stands in the description of a `cpo:ObservationTask`; it points with
`sosa:hasFeatureOfInterest` to what it looked at - a phase, a material (also a stream) or a device (in the
sheet `observes`). No `sosa:hasSimpleResult`, no
new quantity. If the observation determines a point in time (the end of the reflux), it is at the same
time its determination task (Evidence `hlo:Observed`, with bounds if the point in time was not noted). A
determination task may therefore also arise freely, without a value (`free_task_types`, every kind of
determination task); normally it arises from its value.

## 4a. Files

4a.1 **A table has its header in the first row, and the header contains no numbers and no dates**.
If a number, a date or a time stands there, the row is data: the file counts as not
tabular, gets no columns, and the run says so (`get_additional_information/get_file_metadata.py:
get_headers`). No abort as with duplicate headers, because one does not change raw data of a device
afterwards. The delimiter of a CSV (comma, semicolon, tab) is recognised. A header further down (as in
`exp<n>_mass.xlsx`, header in row 3) is not found.

4a.2 **A file has at least one generating task** (`cpo:generatedBy`; the generator writes exactly one). Where it is
not known, it is assumed and said so: an ELN export
or a reaction scheme drawn in the record comes from the planning ("Planning the series"). If a device or its
software writes the file during the measurement, it is the measurement itself. If someone enters values
from several tasks into a file, it is a **`cpo:RecordingTask`** (function `cpo:RecordingData`);
the values keep their own determination tasks. Example: "Transcribing the masses into the spreadsheet"
for `exp<n>_mass.xlsx` (weighed-in amount and masses from the GC analysis). In the experiment it stands
under "Establishing the values".
*checked:* `hlo:File_GeneratedBy_Shape` (every file of the series or of an experiment, Warning).

4a.3 **A file belongs to the series or the experiment from whose folder it comes:**
`schema:about` on the file, `schema:subjectOf` on series or experiment (the CPO declares the inverse).
That is independent of `cpo:generatedBy`: there it says how the file came about, here what it belongs
to. `./` keeps listing the files as parts (RO-Crate). On the dataset `./` only the series and the files
(plus the snapshots) stand as parts, not the contexts: a context stands next to the things that describe it
and does not need to be attached anywhere.
The file is called `ro-crate-metadata.json`, and the dataset `./` names its parts with
`hasPart` (schema.org, as RO-Crate requires) instead of `dcterms:hasPart` and carries `name`,
`description` (that of the series) and `datePublished` (the run); inside the crate `dcterms:hasPart` stays
(a device and its parts - schema:hasPart is too narrow). The licence is still open. The ELN
export itself is a file of the crate (`.eln`, `cpo:File`, `application/vnd.eln+zip`), dated with its own
export date, with a description. **Every key a term of the `@context`** (RO-Crate 1.3, compact form): when
saving, `helpers/file_handling.py: add_key_terms` writes every prefixed key used as a
term into the embedded context (`"cpo:hasVolume": {"@id": "cpo:hasVolume"}`); with real addresses this
becomes a context file of its own under the same address.

4a.4 **A task that comes from files exists only in the experiments whose files name it** (Chemotion example:
an NMR only in LCJ-R5, an NREL analysis only in LCJ-R8). A file generated
by a new task brings a series template with it (`Task_for_File_<file>_...`) and its performance in the
file's experiment; the template is carried into another experiment only where a file or a value of that
experiment names it as well (its placeholder is there already). Otherwise the crate would claim a
measurement in an experiment that had none. A task of the sheet with `created_from_file: true` is such a
task.
*Code:* `creation/task_functions.py` (`_born_from_files`, in `complete_all_tasks`).
*checked:* Chemotion example: the NMR task in experiment 1 only, the NREL analysis in experiment 2 only.

4a.5 **An experiment recorded in an ELN is `schema:subjectOf` its record:** the record is the entry (`schema:Dataset`) of the Reaction Library that the library entries
imported from it already point at, so the crate leads to the ELN. Asked for each experiment
(`series:1/experiment:<n>/eln_record`, the records of the library or "No ELN record"); the adapter
answers it from `series.eln_records` (record n = experiment n, A1) by the record's `schema:identifier`
("<System> <record_id>"). A sheet without `eln_records` does not answer it - that there is no record is
said by a person (under `open`, or in the answer file; hydrogenation: "no ELN record").
*Code:* `creation/experiment_functions.py` (`ask_eln_record`), `interfaces/eln/adapter.py` (`_eln_record`).

## 5. Device history

5.1 **A device is linked only on the task in which it is actually used** (`cpo:usedEquipment`/
`cpo:usedInTask`), not in addition on the tasks above. It counts as used in every task to whose sub-tree
(`dcterms:hasPart`) this task belongs - which also gives the procedure in which it was used, from the
content and not from a name.

5.2 **`lastUsedTime` and `lastUsedPurpose` describe the state before the respective level, by time:**
an experiment points to the last entry of the history that lies **before its
start**, the series to the last one before the start of experiment 1. `lastUsedPurpose` is the task of the
entry, `lastUsedTime` its end. Entries of this crate count like all others: experiment 2 finds experiment
1 if it lay before. All direct references (3.2a), set after the task stage (`record_device_usage`) once the
times are fixed. If no entry lies before, both stay empty and the run warns (usually a contradiction to
5.5).

5.3 **The history in the library is sorted by time:** after the run the procedures of
the crate are sorted into their place in `hasUsageHistory` - usually at the end, and only then does
`lastUsedTime` (and `lastUsedPurpose`, where the library keeps it) change to the end of the new last
entry. Links into the crate, one commit per crate ("Usage history of crate …"). Single-use items
(`cpo:isSingleUse`) get nothing. Reading starts from the end: in the normal case (the experiment is
younger than everything so far) the last entry is enough. The point in time of an entry is the end of its
task, otherwise its start; it stands in the crate that entered it (open or completed), or in the library
(commissioning). **An entry without any point in time stops the run** (assume nothing silently).

5.4 **No subtracting:** a repeated run does not read the library "without the entries of this crate" - that
would go wrong as soon as another crate was entered later, which would appear as the last use before an
earlier experiment. With the sorting by time (5.3) it is unnecessary: a repeated run finds its entries in
their place and writes nothing. The restart lock (`crate_continuation.py`) too asks the current content of
the library, not its Git history.

5.5 **A new device in the Device Library starts with a `cpo:CommissioningTask`:**
setting up, unpacking, delivering - the commissioning is always the first entry in `cpo:hasUsageHistory`,
and `cpo:lastUsedTime` points to its end. So the usage history is never empty, and Device_Information_R3
and Device_Time_R1 apply from the start. Single-use items (`cpo:isSingleUse true`) get none (as in 5.3).
This holds for every new entry, whether created by hand or by an entry tool (2.16). The task stands
with the prefix `task:` in the Device Library, with start, end and duration (rule 4.6) and
`cpo:usedEquipment`; what was delivered and set up together shares one task
(`task:commissioning_reactor001` for the reactor with all its parts). In the crate a task of the library
gets no type stub (3.2a); the stub stays for references into earlier crates.
Service and calibration follow the same pattern: `cpo:ServiceTask` in `cpo:hasServiceHistory`,
`cpo:CalibrationTask` in `cpo:hasCalibrationHistory`, `cpo:lastServicedTime` and `cpo:lastCalibratedTime`
point to the **end** of the last one (like `lastUsedTime`, 5.3). They are required on every level by
Device_Time_R2 (service) and Device_Time_R3 (calibration).
*checked:* `check_library_consistency.py`, section "Usage histories start with a
commissioning": every device of the libraries (subclass of `cpo:Device`, not a template, not a single-use
item) has a history whose first entry is a `cpo:CommissioningTask`. Counter-check
`generator/tests/library_checks_test.py` (also for 1.2, 2.1, 2.8).

5.6 **The start of the procedure is required in every experiment:** as Evidence
or Reference on `cpo:hasStartTime` of the "Experimental procedure"; an assumption is a Reference of type
Assumed with a task and description of its own. If it stands in neither of the two lists, the run stops
and names the keys (`helpers/value_sources.py`: `required`). Without it the usage history (5.2, 5.3)
cannot be ordered. Hydrogenation and amidation have assumed times (demo).
*checked:* also in the finished crate, `hlo:Procedure_Start_Shape`.

5.7 **The library is the truth, a crate the state at the time it was built:** if an experiment is added
later that lies in time before crates already built, it sorts itself into the library; "last used" in the
later crates is then no longer right. An open crate is built anew (example: the balance of the
hydrogenation was last used in the amidation of 18.07.2024, which was added later), a completed one stays
as it is.
**Building several crates anew together:** the open ones first, then `reopen_crate.py` and the completed
ones - or the open ones once more at the end. Reopening takes the usage of a completed crate out of the
libraries until it is built again; an open crate built in between misses it (the balance `balance001` of
the hydrogenation then had the commissioning as `cpo:lastUsedPurpose` instead of the amidation).

## 6. Contexts

Implemented in `helpers/context_links.py`, called at the end of `main.py`.
No other part of the generator writes `hlo:describesContext` or `hlo:contextDescribedBy`; if the step
finds a link already there, the run aborts.

6.1 **Goal: a directory of the contexts that the crate brings along itself.** The shapes are not in the
crate. Whoever has only the crate should be able to read off a context aspect (e.g.
`ExperimentSpecificDeviceEnergy_Exp1`) what belongs to this context - without a SHACL tool and without
path logic. The link says nothing new, it follows at any time from shapes and data. It therefore replaces
no shape, and completeness is not its yardstick: it is meant to be readable, not to reproduce the shapes.

6.2 **The shapes are authoritative; the link is generated from them, never by hand.** Once, at the end of
the run, the generator goes through every context requirement for every one of its focus nodes in the
crate. Context level and category come from the aspect in `hlo:requirementOf` (a requirement can belong to
two aspects, e.g. `Molecule_Structure_Substance_R1`), not from its name. If a shape changes, the directory follows by itself
in the next run. A quantity that belongs to a context but is required by no shape gets it only with a
requirement. The step reads the crate with the prefix table (`generator/config/project_context.jsonld`,
which also has `schema`, `rdf`, `rdfs`) instead of the RO-Crate URL, so it needs no network. The paths are
evaluated by pyshacl (`value_nodes_from_path`); a sequence of steps the step goes through itself, step by
step, remembering the rest per node and path form - the molecules of a phase go the same way from it, as
do requirements with the same path end. Checked against the whole path in pyshacl: the same ends for all
requirements and focus nodes. Words without a prefix from
the RO-Crate context (`about`, `conformsTo`, `dateCreated`, … on root and descriptor) it does not see; no
requirement starts from there.

6.3 **Which paths count: only the existence paths** - what a requirement requires on the exemplar, also
in the branches of `sh:or` and in `sh:node` -, and the assignments (7.16). The shapes on the value belong
to them (`sh:qualifiedValueShape`, `sh:node` on a property shape): their paths continue the path from the
value. So Phase_Space_R4 requires the area only at the pair interface, and Device_Space_R1 the dimensions only at
the forms.
**The conditions hold as in SHACL, and pyshacl evaluates them** - nothing is rebuilt. A branch of `sh:or`
(likewise `sh:xone`, `sh:node`) is followed only if the node conforms to it. A value counts only if it
conforms to its value shape. Whether a node conforms to a shape is said by pyshacl itself
(`Shape.validate` with the node as focus). So Device_Information_R1 links only the Fixed device of the chain,
and Phase_Information_R4 only a Fixed material that carries a lot. A branch the node does not
conform to (missing statement) links nothing; SHACL reports that anyway. **If an exclusion branch applies
(7.7), the requirement does not hold for this node, and the whole `sh:or` links nothing** - not even
through a demand the node happens to meet (otherwise, for example, the dimensions of device forms would
stand under Phase/Space). An exclusion is what 7.7 writes as one: `[ sh:class hlo:Fixed ]`, an
`sh:not` or a condition with `sh:hasValue`. Not:
- the info collection paths (level and surroundings collection paths, 7.3 and 7.4a) - they repeat what
  stands in the crate anyway through `hlo:specializationOf` and the places, and would link every value
  many times;
- paths in `sh:not` (exclusion conditions, e.g. "the form is defined by a device").
What the value shapes check otherwise (`qudt:hasQuantityKind`) ends at a term and drops out under 6.4
anyway.

6.4 **Which end nodes: every entity at which an existence path ends** - quantities, forms, fields,
occurrences as well as exemplars (the molecules of a phase, the device of a place): they too describe the
context. **Not the intermediate links:** a value on which the requirement requires
something further (its value shape has a property with minimum count ≥ 1) lies on the way and is not
linked - the form on the way to its dimensions, the pair area to its area, the occupation state to its
extent of occupation. A pure class or quantity kind check on the value requires nothing; what is checked
this way is an end point. Not: literals (nothing can be attached to a string) and terms from ontologies
and vocabularies (quantity kinds, individuals). An entity can belong to several contexts - the temperature
of the body phase to Device/Energy and to Phase/Energy -, which is exactly what the contexts state;
`hlo:describesContext` is then a list.

6.5 **Which level: that of the focus node.** The path of a requirement on a series phase links its end
node to the series context, that on an experiment phase to the context of this experiment. If the path
reaches an entity of another level (the experiment device its series device via `hlo:specializationOf+`),
that entity gets the context of the focus node in addition. When continuing a series this is a reference
to something new and therefore allowed (7a.3).

6.6 **Which direction: both** (`hlo:describesContext` on the end node, `hlo:contextDescribedBy` on the
context), also when the end node belongs to another level. **Exception: library and earlier crates.**
Nothing is written there (2.2), only the context side (`hlo:contextDescribedBy`) - also when this crate
carries a type stub for the entity of another crate (3.2a). So a context still shows everything that
belongs to it, except the literals. A context never stands on a library entity.

## 7. Shapes

The shape side of these rules stands in the head of `shapes/ContextRequirementShapes.ttl` (its rules 1-9).
"Check n" means the checks of `check_context_requirements_consistency.py` (checks 1-12, named in its
header), which compares the requirements in the HLO with the shapes.

7.1 **Existence directly on the exemplar**, without `[sh:zeroOrMorePath hlo:specializationOf]` - a value
on another level does not fulfil the requirement. Holds for structure too.

7.2 **Literals, terms and flags are read through the chain** (fits 3.6).

7.3 **Level collection path along the Actual chain** in the same main shape, `sh:Info`, without
`minCount`, always outside `sh:or`. Not only for Actuals: also for whatever else is chained across the levels and asked for directly at the exemplar - forms, body materials, energy fields and
chemical entities (end classes `hlo:Actual`, `cpo:Form`, `cpo:MaterialVolume`, `cpo:EnergyField`,
`chebi:ChemicalEntity`; rule 3 in the head of `shapes/ContextRequirementShapes.ttl`). Only this one way,
not in addition through the chain of the owner.
*checked:* `check_context_requirements_consistency.py`.

7.4 **Follow-up reports stay silent.** The requirement that speaks up is the one for which what is
missing is the end of its path. That is a principle for building the paths, not a ban on several reports:
if several requirements report one gap, each of which shows something missing (the missing phase on the
body material for wall temperature and pressure, the missing pair area on both phases), that is fine.

7.4a **Surroundings collection path as a requirement of its own.** Where other entities around are
collected (room, site, parent device), that is a statement of its own (Device_Energy_R6-R8,
Phase_Energy_R5-R9, Molecule_Energy_R2-R4 - the eleven surroundings requirements, 7.16).

7.5 **Dimensions are ProcessVariables** (fits 3.7).

7.6 **SHACL Core only, no SPARQL** - neither `sh:sparql` nor SPARQL targets -, so that the shapes also run
in GraphDB and stay uniform. This holds for the context requirements; one data quality shape is SPARQL on
purpose, `hlo:Transfer_DroppedSpecies_Shape` (3.13), and runs only in pyshacl. Where the rule stands in the
ontology (quantity kinds, form classes), the shape is generated from it or checked against it, never copied
by hand: `generator/workflow/generate_quantity_kind_shapes.py` (4.4), check 9 (3a.3).
**All shapes assume that CPO and HLO are in the data graph** (or that RDFS inference runs over them; rule 8
in the head of `shapes/ContextRequirementShapes.ttl`): `sh:targetClass cpo:Device` finds a
`cpo:Vessel` and `sh:class cpo:Form` a `cpo:CupForm` only through `rdfs:subClassOf` in the data graph.
Without the ontologies there are no focus nodes and therefore silently no reports. `run_shacl.py` loads
them; in GraphDB they have to be loaded into the repository.
*checked:* check 10; `generator/workflow/run_shacl.py` aborts on an out-of-date generated file.

7.7 **Conditions stand in the `sh:or`:** first branch "does not apply here" (Fixed entry, non-dispersed
phase, flag not set, form defined by something else), second branch the demand - with several required
properties as a node shape of its own (`…_Demand`). Because SHACL only reports for an `sh:or` that the
focus fails, the message lists what is required. Per-use demands exclude the Fixed entry
(`[ sh:class hlo:Fixed ]`). **Every existence requirement of a phase excludes it:** what a phase in use
needs from the library, it has itself or reads through the chain, so a gap in the library is reported
there; the library entries keep their values, and the chain still reaches them. So does every molecule
requirement that asks for something per use (Molecule_Energy_R1, Information_R1, Space_R1-R5), while the
identifiers and the molar mass, which stand at the library entry, are required there too; and every device
requirement on a per-use quantity (Device_Energy_R1-R5). An exclusion has one of these forms:
`[ sh:class hlo:Fixed ]`, an `sh:not`, or
a condition on a flag or a term with `sh:hasValue` (also within an `sh:and`); the context linking reads
it off from that (6.3).
*checked:* check 11 in `check_context_requirements_consistency.py` (exclusions first, at the end at least
one demand - for every `sh:or` the context linking goes through).

7.8 **Every property shape carries its own severity** (SHACL does not inherit it from the node shape).
`sh:Info` only for collection paths: directly on the top shape, without `minCount` - inside `sh:or` a
collection path would silently fulfil the requirement.
*checked:* checks 6 and 8.

7.9 **Across the levels, paths run only upwards:** via `hlo:specializationOf`, never via
`hlo:hasSpecialization` (otherwise the value of one experiment would fulfil the requirement of another).
**Within the set-up they may run up and down** - up to what contains something, down to parts, content,
body, phases and molecules; so a reactor reaches the field of a radioactive molecule in its vessel (7.10).
Only **against a location** does no path run (`sh:inversePath` onto a location statement): going down from
the Fixed room it would reach the devices of every level. Exemplars have levels, places do not. Down into
the devices of a room it goes instead via `cpo:isLocationOf`, which the generator sets only in the crate
between entities of the same level (`set_location`; checked by `hlo:LocationInverse_SameLevel_Shape`).
**In the library, too, places do not point downwards:** the library room air stands in its room with
`cpo:locatedInsideOf`, the room does not point to it. A descent from the room would bring either all levels (inverse path) or the library
state of the devices (`isLocationOf` on Fixed entries) into every experiment; what stands in the room is
reached per level through the room air of that level. Consequence: a permanent field belongs on the room
or the site, not on the library room air - that one is reachable only via `specializationOf`.
*checked:* checks 3 and 7.

7.10 **Surroundings collection paths of the energy fields** run over exactly the lists
`PARENT_PROPERTIES` (up) and `CHILD_PROPERTIES` (down) in `helpers/energy_fields.py`, each as a repeated
alternative of its own, after `cpo:hasEnergyField` only the chain of the field.
**Every field in the room acts everywhere in it:** the descent goes from the room air
via `cpo:isLocationOf` into every device of the room and into what stands in it - the balance collects the
field of the stirrer. How strongly it acts is the value of the field, not a question of structure; the way
deliberately does not run over surfaces (contacts), because everyone who reaches the room air gets its
fields, however deeply nested.
**A stream that no device contains climbs over its ends:** `cpo:flowsFrom` and `cpo:flowsTo` stand in
`PARENT_PROPERTIES`, so the stream reaches the ports it connects, over `cpo:isPortOf` their devices and from
there room air, room and site with all their fields - every such stream touches at least one device of the
set-up (most ends are ports of devices, the others a `cpo:Source` or `cpo:Sink`). The steps go only from the
stream to its ports, so the paths of devices and of everything in a device stay as they are. Where the
transfer path matters, it is modelled as a device (tube, syringe, line - 3a.9): the stream is then
`materialContainedIn` the device.
States of the surroundings are collected by whoever experiences them, through touch: a phase the
temperature and pressure of the phases at its interfaces (Phase_Energy_R8/R9), a molecule those of its
phase (Molecule_Energy_R3/R4) - not over the whole set-up.
*checked:* check 7.

7.11 **Every requirement starts from its context object** - device, phase or molecule
(`sh:targetClass`). It thereby says that its path holds for every device, every
phase, every molecule; what lies in between is governed by conditions. From there the form requirements
follow a fixed path to the forms (device: `definesForm` and `hasEnvelopeForm`, then every cavity, part and
layer below them, however deep - one downward path; phase: `definesForm`, `fillsForm`), and per form a node
shape of its own (`…_Form`) says
"not this class" - for phases also "not defined by a phase or a material" - as an exclusion, otherwise the
demand (`…_Demand`); class and context object stand readably as
`hlo:targetFormClass`/`hlo:targetFormDefinedBy`. Likewise Phase_Space_R4 (area of every pair area) and R5
(extent of occupation of every occupation state). The price: SHACL reports the device or the phase, not
which form or which dimension is missing, and a missing pair area on both phases of the pair. If a form is
missing altogether, only the existence requirement of the thing reports (Device_Structure_R1,
Phase_Structure_R1) - rule 7.4. The forms themselves are only passed through on the way to their
dimensions (rule 6.4); every form a device has belongs to its structure context through the assignment
Device_Structure_R4 (same downward path), its dimensions to its space context.
*checked:* check 9 (context object, path, exclusions and demand per form class).

7.12 **Requirements:** ID `<context level>_<category(ies)>_R<n>` (`Device_Energy_R1`,
`Molecule_Structure_Substance_R1`), in the HLO as `hlo:ContextRequirement` with an English `rdfs:label`, a
one-sentence `rdfs:comment` (the statement) and a `schema:description` built from the same parts in every
requirement (Question, Applies to, Checks/Collects/Assigns, Reports, Not here), `hlo:requirementOf` and
`hlo:hasRequirement` symmetric, each with at least one shape. A requirement can stand under several
categories, that is belong to several aspects (InChI: Structure and Substance). Numbers are not renumbered
during a rebuild - gaps and order are aligned at the end. The order within a cluster: existence
requirements first (the more important ones first, similar ones next to each other), then surroundings,
then assignments; the kind is not part of the ID (it is the type and can change). The
overview (`docs/shape_overview.html`, generated with `generator/workflow/shape_overview/build_overview.py`)
is regenerated after every change.
*checked:* checks 1, 2, 4 and 5.

7.13 **Checks of the generator do not belong to the context requirements** but into
`shapes/DataQualityShapes.ttl` (mostly severity Violation): units (4.3), quantity kinds (4.4), exactly one
defining thing per form (3a.1), the cavity of a hollow form (3a.3), the body material that fills exactly the
form of its device (3a.11), the interface between the phases of one material (3b.1,
`hlo:Phase_SameMaterial_Interface_Shape`), the contact of a device standing in the room air with it (3b.1,
`hlo:Device_RoomAir_Contact_Shape`), start, end and duration of a phase occurrence that occurred
(`hlo:Phase_Occurrence_Times_Shape`, Warning). They say nothing about the context of an experiment, but
whether the generator built correctly.

7.14 **A report without a counter-check proves nothing.** Every new or changed shape is checked with a
deliberately damaged crate (value removed, value wrong, condition swapped); where a shape replaces existing
ones, a comparison shows that it hits the same focus nodes. `generator/workflow/run_shacl.py` counts only
the outer result (with `sh:node`, pyshacl also stores the inner one as `sh:detail`, with the default
severity Violation). Crate and libraries are checked apart: the shapes see crate, ontologies and libraries
together, but the crate check counts only results at nodes of the crate file, and `run_shacl.py --libraries`
(after editing the libraries) only those at nodes of the library files, with its own baseline - a flaw of a
library entry no longer shows up in every crate. Results at nodes of other crates - of which only type and name are
loaded, as stand-ins for what the usage histories point at - count in neither check and are named in a line of their
own: their data is checked in their own crate.

7.15 **A requirement that hits nothing in the crate is not an error** if the target does not exist there
(Device_Space_R1_SphericalShape: no spherical device). If it hits nothing although the target exists, class or path are
wrong - count after larger rebuilds.

7.16 **Three kinds of requirements.** The kind stands in the HLO: every requirement is exactly one of the
three disjoint subclasses of `hlo:ContextRequirement` - `hlo:ExistenceRequirement`,
`hlo:SurroundingsRequirement`, `hlo:AssignmentRequirement` (54 / 11 / 24 of 89 requirements). The context
linking reads the kind from the shapes; the class makes it readable without the shapes.
- **Existence:** requires something on the exemplar (severity Warning, with minimum count), often with a
  level collection path as Info (7.3). Conditions (Fixed, flag, dispersion) are its exclusions (7.7), not
  a kind of their own.
- **Surroundings:** a collection path, only `sh:Info`, without minimum count (7.4a); not linked (6.3).
- **Assignment:** what belongs to the context if it exists -
  - of a device: the tasks it is used in (Device_Information_R4), its forms and its ports
    (Device_Structure_R4/R5), the constituents of its body material (Device_Substance_R4);
  - of a phase: its library entry (Phase_Information_R3), its interfaces (Phase_Space_R6), the
    concentration, mass and amount of substance of its molecules - its composition (Phase_Substance_R4;
    required at the molecule, Molecule_Space_R2-R4), its transfers, occupation states and reactions
    (Phase_Substance_R5-R7), its solvent (Phase_Substance_R8, 3.12), its occurrences (Phase_Time_R3; that an
    occurrence that occurred has start, end and duration is checked by `hlo:Phase_Occurrence_Times_Shape` in
    the data quality shapes, 7.13), and its origin upstream (7.17): arrivals, opening, expiry and containers
    (Phase_Time_R4-R7), lots and origin tasks (Phase_Information_R4/R5);
  - of a molecule: the origin of its phase (Molecule_Time_R1-R4, Molecule_Information_R5/R6).

  A property shape with
  `sh:qualifiedValueShape [ sh:class … ]` and `sh:qualifiedMinCount 0`, severity Warning: it never reports
  anything, the class filters what the path would otherwise bring along (from the inverse path of an
  interface also the transfers there). What is assigned is the thing itself, not what hangs on it (flow
  rate, occurrence, speed) - that is reachable from it.
Where a quantity hangs on a thing that is not itself a context object (pair area, occupation state, form),
the requirement still starts from the context object (7.11); the thing in between is an intermediate link
and is not linked (6.4).
*checked:* check 12 in `check_context_requirements_consistency.py` (exactly one kind given, and it fits the
shapes: demand → existence, `sh:qualifiedMinCount 0` → assignment, only `sh:Info` → surroundings; mixed is
reported).

7.17 **Origin and age of a content.** Concerned is
the phase whose material is in a `cpo:ChemicalContainer` - bought or made in-house.
- **Everything that exists beyond one experiment stands in the chemical inventory** (its content in the
  Material Library, its container in the Device Library, 2.15) -
  bought or made in the lab, no matter for how long (not a series-wide level of its own in the crate).
- **Receipt** (the arrival in the requirement texts) = since when the content has existed in the lab: the start of an **occurrence of the content
  phase** on the Fixed entry that describes the content itself. The start is the same `time:Instant` as the
  end time of the task that brought the content (receipt) or produced it (reaction, making up - not the
  filling); through it the task and thus the origin are reachable. No properties of its own for this, no
  PROV-O. `cpo:hasDeliveryTime` points to the same point in time and stays for readability.
- The receipt occurrence is **not a permanent occurrence** like that of the room air: the experiments keep
  their own occurrence of the content phase (whether and when it existed there) - a different event, not
  chained to the receipt (`has_permanent_occurrence` does not hold for contents of a container).
- **No content of a chemical container is made in an experiment:** by its class the content belongs to the
  container and stands in the Material Library (`cpo:ChemicalContainer`), so Phase_Time_R1 has no exception for
  a content filled through the opening.
- **Requirements on the content:** existence - receipt (Phase_Time_R1) and lot (Phase_Information_R2, for
  own substances the own batch or sample number); assignment - opening (a delivered bottle can be
  unopened) and expiry (Phase_Time_R5/R6). The manufacturer is not required.
- **Receipt through the chain:** it is not a state per level but an event on the entry that describes the
  content, and is read via `hlo:specializationOf` (the entry itself is assigned by Phase_Information_R3). Occurrences are not chained,
  so Phase_Time_R1 has no level collection path (7.3) - its demand already reads up the chain.
- **Known origin of every other phase (Phase_Time_R2, existence):** every phase outside a chemical container -
  except Fixed, body material and surroundings - reaches, backwards over the transfers and up the chain (in any
  order, zero steps included), at least **one** origin: an occurrence at a Fixed entry, the receipt occurrence of a
  content or the permanent occurrence of a supply (also the room air). Every origin found is linked. R2 does not
  apply to the contents of chemical containers and does not ask for the start time: the receipt time is required
  once, at the content (R1), and a missing one is not reported again at every phase downstream (7.4). R1 and R2
  never apply to the same phase; R4 is the assignment on the same way (every origin, every phase), R2 the check.
  R2 has no collection path (the direct transfers are assigned by Phase_Substance_R5). R2 reports where a phase
  is fed only from a nameless `cpo:Source` or no transfer leads into it - where it came from is then not known.
  In the hydrogenation, hydrogen and cooling water come from the gas cylinder `device:h2_cylinder_01` and from
  the line for deionised water (`device:L109_DI_water_supply`), so R2 reports nothing there. The amidation and
  the Chemotion example report the products of their work-up (the isolated product; pulp and lignin oil): no
  transfer leads into them in the input.
- **Supply that is always there:** a line of the room as a Fixed device (`cpo:Pipe`
  with outlet, `helpers/inventory_entries.py: supply_pipe`), its content with a permanent occurrence
  without beginning and end like the room air (status assumed by an assumption task of the library). A run
  takes it over like the content of a container (3.10); its copies get no occurrence of their own
  (`has_permanent_occurrence`, the content is in no `cpo:ChemicalContainer`). A feed from the outlet
  (`from: <line>_outlet` in the sheet) thereby has an origin. Gas from a cylinder, by contrast, is a
  container of the inventory like any bottle (steel template `device:gas_cylinder_10L`, gas cabinet
  `lab:L109_GasCabinet`, receipt = delivery).
- **Origin through the transfers (layer 2):** the assignments R4-R7 start from **every** phase and first
  run backwards over the transfers (R4-R6 also up the chain, see "One walk"; R7 only on the same level,
  `[sh:zeroOrMorePath ([sh:inversePath cpo:addsToPhase] cpo:removesFromPhase)]`; zero steps = the phase itself): opening (R5), expiry (R6),
  receipt occurrence (R4, Fixed only; the assignment on the way that R2 checks) and the containers themselves (R7, only `cpo:ChemicalContainer`;
  their usage, delivery and opening are reachable from there). Transfers are potential - this is where it
  **can** have come from; from a reactor on, every phase reaches every container upstream. Because the
  contexts exist per level, layer 2 adds in the crate mainly the containers of every level and the receipt
  occurrences (also the permanent one of the room air).
- **Made in the lab** (stock solution, batch, refilling): described in the Material Library
  (`inventory_entries.prepared_container`, tool `generator/workflow/inventory_tool.py prepare`):
  `task:preparing_<name>` (`cpo:OperationTask`), per source container a Fixed `cpo:Transfer`
  (`cpo:PortCrossing`) into the new content, lot = own batch number, receipt = end of the preparation (the
  preparation determines the status). R4, R5 and R6 (and Information_R4/R5) reach the source bottles - from the
  content itself and from every phase downstream, R2 from the phases downstream -, because their way back also
  goes up the chain and over the transfers of the library; R7 not (containers of the same level). A crate of its own for a preparation should be possible but is not built. **Refilling** is a
  preparation from one source: a new content, one transfer from the old one - into a new bottle, or (2.15)
  into the same or another bottle that is there already and whose content has ended; the statements stay on
  the old content and are reachable through the transfer. The new content **takes over the lot**.
- **Booking out:** the end of a content is `cpo:hasEndTime` of its receipt occurrence - the same
  `time:Instant` as the end of the task that used it up or disposed of it (until then an empty Actual
  `<occurrence>_EndTime`). In the run: a question per experiment and task that uses a container
  (`series:1/experiment:<n>/task:<key>/empties`; in the sheet `empties` on the task, otherwise `none:
  emptied`); `record_device_usage` writes the end into the Material Library and releases the content
  (2.15), takes out its own ends beforehand (5.4) and **aborts** before writing if an experiment still withdraws after the end (from an
  earlier crate, the inventory tool or an earlier experiment of the same crate) or a content is used up
  twice. Outside a run: `inventory_tool.py dispose`. Nothing is calculated from amounts. Rebuilding a
  completed crate: take out its ends as well as its entries in `cpo:hasUsageHistory`.
- If a statement is missing in the library, R1 and Information_R2 report once per level (series and
  every experiment) - correct in substance, left as it is.
- **Expiry or re-test:** a stable substance has a re-test date instead of an
  expiry date (`cpo:hasRetestTime` on the content): until then the manufacturer guarantees the
  specification, afterwards the substance has not expired but should be checked again before use.
  Phase_Time_R6 and Molecule_Time_R3 take both (`sh:alternativePath`). Test entry: the platinum bottle has
  a re-test date instead of the expiry.
- **Certificate of analysis** as a file: a `schema:MediaObject` in the Material Library
  (`document:certificate_of_analysis_<lot>`), named by the References
  that come from it (purity, re-test date), with `hlo:hasSourceFile` (4.1). The test entries store no file;
  a real entry names it with `schema:contentUrl`.
- **Storage conditions** are not recorded: they follow from substance, lot and
  manufacturer ([`things_to_implement_after_me.md`](things_to_implement_after_me.md)).
- **One walk:** the way back is one path, `[sh:zeroOrMorePath [sh:alternativePath
  (([sh:inversePath cpo:addsToPhase] cpo:removesFromPhase) hlo:specializationOf)]]` - every step one transfer
  back or one step up the chain, in any order. Not a sequence (transfers*, chain*, transfers*): pyshacl visits
  every node of a zero-or-more path once, while it follows a sequence way by way - on a large crate the
  difference is minutes against seconds. Used by Phase_Time_R2/R4-R6, Phase_Information_R4/R5,
  Molecule_Time_R1-R3 and Molecule_Information_R5/R6.
- **Lot and origin task upstream (Phase_Information_R4/R5, assignments):** the same way as Phase_Time_R4-R6. R4 links
  the Fixed material that carries the lot (classes `cpo:MaterialRepresentation` and `hlo:Fixed`; `cpo:hasLotNumber` is a text; filter "has a lot" in `sh:not`, so that
  the link ends at the material), R5 the Fixed task that ends at the point in time at which the receipt
  occurrence starts (start, then `cpo:hasEndTime` backwards) - receipt or preparation. Information, not
  Time: the task says how and from where. Fixed keeps out the tasks of an experiment, `cpo:Task` an
  occurrence that ends at that moment (counter-checks).
- **Molecules share the origin of their phase** (`dcterms:isPartOf`); it cannot be determined more
  precisely than the phase in SHACL Core (comparing the species along the path would need SPARQL,
  [`things_to_implement_after_me.md`](things_to_implement_after_me.md) - a known limit). Their assignments go one step
  up to the phase and then its way: Molecule_Time_R1-R4 like Phase_Time_R4-R7 (arrival, opening,
  expiry, container), Molecule_Information_R5/R6 like Phase_Information_R4/R5 (lot, origin task). **Assignments
  only:** receipt and origin are required by R1 and R2 on the phase - reported again
  on every molecule, the same gap would come several times. Target `chebi:Molecule` like the other molecule
  requirements (the hydrogen atom and the active sites drop out).
*checked:* `generator/tests/origin_age_shapes_test.py` (counter-checks of the shapes),
`generator/tests/inventory_end_test.py` (booking out in the run, real runs in copies),
`check_library_consistency.py` (containers of the inventory: content, lot, occurrence with start, delivery
time = start, cabinet in a room).

The content of a device does not belong to the device context: temperature and pressure of every phase are
required by Phase_Energy_R1/R2. State variables on phase and material: rule 3.8.

## 7a. Continuing a series

7a.1 **The crate follows unambiguously from answer file, libraries and data folders.** Continuing means:
the answer file grows by one experiment, the run builds the crate anew.

7a.2 **Every crate lies in `projects/<identifier>/crate/`** with its to-do list and the metadata
overviews; a completed series in `projects/<identifier>/crate_completed/`. The identifier decides: open → continuation,
archived → abort, otherwise a new series - unless the Device Library already knows the identifier from its
commits (abort).

7a.3 **What a crate contained already stays as it was.** On an existing entity only references to newly
created entities may be added - also on a property that did not exist before (the end of experiment 1 gets
the context of experiment 2, 6.6); in addition the library list, Ontology Snapshot, root
data and, on the series, `hasNumberOfPlannedExperiments`/`isCompleted`. Every other change aborts before
saving (`check_earlier_content_kept`), wanted only with `ALLOW_EARLIER_CHANGES=1`.
*checked:* in every run that continues an open series - so also in every isolated run against the
committed crate.

7a.4 **Only the experiments conducted arise in the crate** (`setup/number_of_conducted_experiments`). The
planned number (`cpo:hasNumberOfPlannedExperiments`, missing if unknown) and `cpo:isCompleted` stand on the
series; the number conducted does not stand there separately, it is the number of its experiments. When
the number conducted reaches the planned number, the series is completed and archived.

7a.5 **`dateCreated` is that of the first run**, every further one sets `dateModified`.

7a.6 **The answer file belongs to its crate:** `projects/<identifier>/answers.txt`
(`path_definitions.answer_file_path`). `generator/workflow/isolated_run.py` and
`generator/workflow/check_library_references.py` take the file of the only open crate when none is given.

7a.7 **Renaming means building anew** (not an alias): `python
generator/workflow/rename_crate.py OLD NEW` writes the answer file under the new name, replaces every
reference `crate:OLD/…` in the libraries by `crate:NEW/…` and commits that (before the run, because the
run recognises its own entries in the usage history by the identifier, rule 5.4), builds the crate under
the new name, compares it with the old one (identical except for the library state) and only then deletes
the old crate and the old answer file. The crate is committed by hand. Only for open crates; crates of
later series that point into the old one are reported by the script - they need a run of their own.
Tested in a copy, with a counter-check (a change slipped in stops it).

## 7b. Pitfalls - look here when something strange happens

- **Correcting earlier experiments:** correct the answer (or the library), then a run with
  `ALLOW_EARLIER_CHANGES=1` (Git Bash: `ALLOW_EARLIER_CHANGES=1 python main.py`, PowerShell:
  `$env:ALLOW_EARLIER_CHANGES=1; python main.py`). The run lists every allowed change with old and new
  value. The same holds for a rebuild of the generator that changes the crate on purpose - also in the
  isolated test run.
- **Typos in the identifier** are not recognised: an unknown identifier is a new series. Only the reverse
  case is recognised - the Device Library knows the identifier from its commits ("Usage history after
  experiment n of crate <identifier>"), but there is no crate for it (deleted or moved): abort.
- **Testing a continuation in an isolated copy:** the copy has no Git. A second run in the same copy finds
  the usage of the first in the Device Library but no commit before it (rule 2.6) and aborts. Before the
  second run, reset the Device Library of the copy to the state of the project.
- **Windows path limit (260 characters):** copies in a folder with a long path fail when copying
  `output/<identifier>/file_metadata/<long file name>`. Use `isolated_run` without `--out` (temp folder) or
  a short `--out` path.
- **Only line endings changed:** `git status` reports a library as changed although nothing is staged after
  `git add` (LF on disk, `save_jsonld` writes CRLF). The generator then does not commit; when editing by
  hand, keep the line endings.
- **`OSError: [Errno 22] Invalid argument` or `PermissionError: [WinError 5]` on a file a run writes:**
  OneDrive or a virus scanner holds the file open for a moment. Everything a run writes - crate,
  libraries, answer file, to-do list, the file metadata overviews, the driver report - and the setup sheet
  (`sheet_text.py`, `close_sheet.py`) go through
  `helpers/safe_write.py`, which repeats the writing (ten attempts, about 6.5 s): `write_atomic` (complete
  `.tmp` file, then `os.replace`) for all of them except the answer file, which is written after every
  answer and therefore in place (`write_in_place`; the module says why). A new file a run writes goes the
  same way; if the error still stops a run, repeat it.
- **Run time:** if an isolated run suddenly takes much longer than before, measure first (cProfile), do
  not guess - once it was an ontology query without a cache.
- **SHACL-SPARQL shapes:** pyshacl runs the query once per focus node, and rdflib executes the patterns in
  the written order. Put the focus on few nodes and query from the bound `$this` - a quantity kind shape
  in SPARQL took 6 minutes with every ProcessVariable as focus, 5 seconds for the whole run with the
  annotated properties as focus. In addition rdflib does not see the pre-bound `$this`
  **inside** `FILTER NOT EXISTS`/`OPTIONAL`: hand it over beforehand with `BIND($this AS ?x)`. Write
  conditions like "the property allows several kinds" as a pure filter that binds nothing: as a bound pair
  the rest of the query ran per pair (30 times), as a subquery or group of its own rdflib evaluates it over
  the whole graph (over 10 minutes). Counter-check every new SPARQL shape with a deliberately broken crate -
  "0 reports" alone proves nothing - and measure the run time.
- **What the hydrogenation crate does not go through stays unchecked:** fields of devices, phases and
  radioactive molecules, measured room fields, fields that act in the whole room, further occurrences. For
  this there is the field test: isolated copy, prepare the library there (stirrer and its body phase can
  generate fields, water radioactive) and drive the driver in the copy with a rules file. It found in this
  way that a species that only a transfer brings into a phase (water → gas phase) did not get its radiation
  field on the series and that it arose in the experiment without a template (fixed in
  `top_up_phase_concentrations`). No warnings are expected at the prepared library entries:
  Device_Energy_R5, Phase_Energy_R4 and Molecule_Energy_R1 exclude library entries. **One command:** `python
  generator/tests/field_test.py` (about 12 min) creates the copy, prepares it, drives the
  driver with the fixed answers (`RULES` in the script, abort mode, `ALLOW_EARLIER_CHANGES=1`, because the
  flag of the body phase is already in the crate) and checks against fixed expectations: the expected
  warnings (with and without RDFS inference), which fields at which sources, chains, contexts (only the
  fields, nothing that hangs on them), two occurrences, and the environment paths of both experiments
  (every device, phase and molecule sees the stirrer field - also those of the streams without a device -,
  no path into the other experiment). Exit 1 on a deviation; a counter-check with a damaged crate (chain removed,
  context on a field strength) reported exactly these two. If an answer key changes, the run aborts and
  names it - then update `RULES`. When exploring new questions by hand: **runs with `--on-unknown log`
  write their stand-ins into the answer file of the copy** - after that no rule applies there any more; use
  a fresh copy for the actual run.
- **Testing layers** (rule 3.8a): `PYTHONPATH=. python generator/tests/library_layer_test.py
  --apply COPY [--partial]` writes the PTFE-coated stirrer and the PTFE-lined vessel in the pattern of 3.8a
  into the Device Library of an isolated copy (with `--partial` the lining covers only a part). Then the
  driver in the copy with `--on-unknown log`; SHACL with the libraries of the copy (call it in the copy,
  otherwise `run_shacl` loads those of the project). **Do not change the name of an existing phase:** stored
  answers name phases by their name (e.g. the interfaces between materials), a renamed phase makes them be
  discarded. Expected: SHACL 0; full lining - the content touches only the lining, the glass only jacket,
  room air and lid; partial - the content touches both; layer forms on every level with thickness, chained
  up to the library.
- **A task ID names an experiment the task does not belong to** (accepted deliberately): a
  placeholder is named after what triggered it (`Task_for_<cause>`), and its series template after the
  FIRST cause. That is why the recording task of both experiments is called
  `Task_for_File_exp1_mass.xlsx_ExperimentSpecific_…`, also in experiment 2 - it was triggered by the file
  of experiment 1. Not an error: what counts is name, level and number at the end of the ID. The same holds
  for every task that arises from a value ("Reading the times" is called
  `Task_for_Task_Cooling_StartOffset_…`). Renaming would mean migrating the keys of the answer file
  (rule 1.1).

## 7c. What the series says about all experiments

7c.1 **The series fixes what exists; the experiment says what of it happened and how much** (follows from
3.1). Phases, interfaces, transfers, feeds, reactions and materials arise on the series and are only
specialised in the experiment - there is no experiment entity of these kinds without a template. What does
not occur in every experiment stands on the series as a possibility and in the experiment as an occurrence
(NotOccurred) or as amount 0 - also for phases (3.1b). Start, end and duration are required only of
occurrences whose status says Occurred (`hlo:Phase_Occurrence_Times_Shape`, 7.13).
**Not every task of an experiment needs a template on the series:** a task that
only determines values of the experiment - the status of an occurrence (3.1b) or the times of other tasks -
has nothing on the series a template could refer to ("Watching the material go in and out", "Reading the
times from the run log").

7c.2 **The kind of a material (Stream or MaterialVolume) stands on the series.** Another material is
another set-up and a series of its own.

7c.3 **"The same in all experiments?" - Yes / No / Not known yet.** Yes asks once on the series, No and Not
known yet per experiment. Concerned: creator, experimenter, operating mode, part tasks of a group, solvents
of a liquid phase (3.12). An answer for the respective other place is a contradiction and
aborts the run before saving (`check_series_contradictions`).

7c.4 **People stand on every level themselves**, never left out: on the experiment creator and
experimenter(s), on the series its creators and, as experimenters, everyone who performed its experiments.
Several people allowed.
*checked:* `hlo:Persons_EachLevel_Shape` in `shapes/DataQualityShapes.ttl` (series
and every experiment at least one `cpo:hasCreator` and `cpo:hasExperimenter` each, Warning); counter-check
as for 4.6.

7c.4a **Who performed a task stands on the template - or on the experiments if it is not the same in
each:** if a performing person (`cpo:performedBy`) stands on the
template of the series, it holds for all experiments; if it is not the same in every experiment, it stands
on the single experiments (7c.3; in the sheet `varies: [performers]`). Inheritance is only via
`hlo:specializationOf`, never via `dcterms:hasPart`: sections carry no performers. A task that a device
performs alone ("Logging the temperature", "Controlling the pressure") has no `cpo:performedBy` - what it
did stands in `cpo:usedEquipment` (in the sheet `performers: []`; comment before `PROCEDURE_TASK_NAME` in
`creation/task_functions.py`).

7c.5 **Part tasks are linked on every level** (3.1: structural references to the own level; 5.1 reads the
sub-tree of the experiment). The template on the series names what **every** experiment contains; an
execution can have further parts. With No/Not known yet the template gets this intersection only when the
series is completed - before that, a further experiment could make it smaller. **Do not sort in
provisionally:** the template would otherwise claim something about every experiment, and
taking it out later would change earlier content (7a.3). The warning "not part of any other task" at the
end of the run therefore names such waiting templates only in an info line, as soon as all their executions
are sorted in; a warning is given only for tasks that are really free.

7c.5a **The procedure has fixed sections: Preparation, Main operation, Work-up** - like the sections of XDL
(Prep, Reaction, Workup). The generator creates them in every crate and hangs them, without asking, into
the "Experimental procedure", next to "Establishing the values"; also when empty (an empty shell is the
smaller price than a structure that looks different from crate to crate). Their names are set (not following 1.7), their answer keys fixed
(`task:preparation`, `task:main_operation`, `task:workup`). They have no function of their own, only that of
their parts. The main part is deliberately not called "Reaction": it claims no reaction; the task that
brings a reaction about hangs in it (4.9). The analysis stays where it belongs (in the hydrogenation in the
work-up). Purification as a section of its own:
[`things_to_implement_after_me.md`](things_to_implement_after_me.md).
*in the code:* `PROCEDURE_SECTION_NAMES`, `SHELL_TASKS` in `creation/task_functions.py`.

7c.6 **When completing the series**, an operating mode answered with Not known yet that was the same in all
experiments is given once on the series (3.6), otherwise it stays on the experiments. A solvent asked per
experiment (No / Not known yet) reaches the series only now: all that any experiment names, on its own
species (3.1, 3.12) - before that, a further experiment could still add one (like 7c.5). The protection from
7a.3 only reports in the completing run.

## 8. Way of working

8.1 **Every change to the generator is checked against a reference run:**
`generator/workflow/isolated_run.py`, then `generator/workflow/compare_crates.py`. Expected is only what the
change is meant to change; new questions only where intended. SHACL 0 (`generator/workflow/run_shacl.py`; after a library change
also `run_shacl.py --libraries` against its baseline),
`check_library_consistency.py` without deviations, `generator/tests/*_test.py` OK.

8.2 **The answer file is migrated, not rewritten by hand.** Name and description questions are never
answered wholesale.

8.3 **Language:** everything in the repository is English - docstrings, comments in the code, questions
to the user, outputs, documentation and commit messages.

8.4 **Namespaces:** schema.org always `http://`; every library declares every prefix it uses;
`project_context.jsonld`, the library contexts and `ontology_library.jsonld` agree.
*checked:* `check_library_consistency.py`.

8.5 **Versions:** cpo and hlo stand at **1.0** (`owl:versionInfo`, `owl:versionIRI`, `cpo:usedVersion` in
the Ontology Library) and stay there until something is published. From the publication on they count up
in hundredths (1.01, 1.02, …), a whole number only with a further publication or a large change; smaller
changes (deleting something unused, sharpening a description) count up together with the next change in
content.

8.6 **Dependencies:** which Python packages the generator needs stands with a fixed version in
`dependencies.txt` (`pip install -r dependencies.txt`). A version is raised deliberately and checked
afterwards with `compare_crates` - `helpers/context_links.py` uses internal functions of pyshacl.

## 9. Rules of the ELN import (overview)

The wording stands in the ELN README
[`generator/interfaces/eln/README.md`](../generator/interfaces/eln/README.md) - the adapter rules worded the
same as `RULES` in `generator/interfaces/eln/adapter.py`, the profile rules per ELN with their profile. Here
only which ones exist and what for; whoever changes one changes the README (and `RULES`).

| Rules | Where | What it is about |
|---|---|---|
| **A1, A3, A8, A9, A12, A14, A15** (adapter) | README, "Adapter rules"; code `RULES` | What follows from the matter itself and is therefore translated by a fixed rule (code R in the source line): one record per experiment (A1), a series with one experiment is the same everywhere (A3), ELN units as QUDT units (A8), a number from the ELN is a new scalar value (A9), a result belongs to the participant it names (A12), a substance not named under `species_per_experiment` occurs in every experiment (A14), a library content holds only the species entered there (A15). |
| A2, A4-A7, A10, A11, A13 (withdrawn) | README, table "Withdrawn" | Assumptions that the setup sheet or the Assumption Library makes instead; the numbers stay free. |
| **P-AI1 - P-AI9** (profile AI4Green) | README, "Profile rules"; `profiles/ai4green.py` | Where AI4Green keeps what: chemistry from the JSON file, roles as the ELN's word, product mass from the table, units from field or column heading, reference of yield and selectivity, no experiment date, completion, files of the export, addenda. |
| **P-EL1 - P-EL5** (profile eLabFTW) | README, "Profile rules"; `profiles/elabftw.py` | Everything from the RO-Crate graph, `temporal` as the experiment date (P-EL1), status and completion - no experiment status in eLabFTW 6 (P-EL2), free fields only through a mapping table (P-EL3), steps as `HowToStep` (P-EL4), characters of the Symbol font unchanged (P-EL5). |
| **P-CH1 - P-CH10** (profile Chemotion) | README, "Profile rules"; `profiles/chemotion.py` | Collection export read as a ZIP, not unpacked (P-CH1), experiment date from `timestamp_start` (P-CH2), completion from the status (P-CH3), substances from the link tables with target and real amount (P-CH4), 0 as empty (P-CH5), no user names in the export (P-CH6), samples without a structure (P-CH7), analysis files of reaction and samples (P-CH8), temperature, duration without unit, segments under `unmapped` (P-CH9), the inventory of a sample with `order_number` as the ELN's word (P-CH10). |
| Setup sheet | README, "Setup sheet, version 1"; `sheet_schema.yaml` | Fields of the sheet, `none` categories, occurrences and times (rule 2.13), readable names of derived things; checked by `check_sheet.py`. |

In addition the rules of this file that concern the import: 2.9 (taken over, not completed), 2.10 (origin
of every input), 2.13 (occurrences in the sheet).
