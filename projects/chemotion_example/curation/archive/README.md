# Archived curation scripts of the Chemotion example

`add_library_entries.py` and `add_inventory.py` wrote the library entries of the Chemotion example on
05.10.2026: the substances, the two records, Congjian Lin with his organizations and lab, the autoclave,
filter funnel and rotary evaporator, the hydrogen line (`add_library_entries.py`), and the wood stock, the
NREL batch and the methanol bottle with their containers (`add_inventory.py`). The entries they wrote are
in the libraries and stay there.

**Do not run them again.** Both were written before devices and materials were separated (rule 2.15,
05.10.2026 evening): `add_inventory.py` writes the containers into the old `inventory_library.jsonld` and
without `cpo:hasContainedMaterialHistory`; the entries themselves have since moved to the device and the
material library. A second run would also stop at the first entry that exists already. Paths inside the
scripts (`pubchem/`, the helpers of `add_library_entries.py`) still assume the folder `curation/`.

They are kept to show where each entry comes from (rule 2.10) and as a pattern for the curation of the next
ELN export. Archived on 07.10.2026; the last state in `curation/` is commit `45c515c`.

Known gap of the entries: `material:methanol_bottle_646377_01_Content` has no lot (`cpo:hasLotNumber`) - the
export names none; `check_library_consistency.py` reports it.

## Archived on 09.10.2026

The rest of `curation/` (Laura Fadler, 09.10.2026: phase the curation scripts out - new library entries are made
with `generator/workflow/library_entries/`, rule 2.16):

- `add_commissioning_time.py` - a commissioning time for Congjian Lin's RCF setup (autoclave, filter funnel, rotary
  evaporator), so that its usage history can be ordered in time (N26);
- `add_rcf_reaction.py` - the reductive catalytic fractionation as a `cpo:LumpedReaction` in the reaction library;
- `update_lab_location.py` - the names and comments of Congjian Lin's site and lab after the inventory of the export.

They ran once on 05.10.2026; their entries are in the libraries. **Do not run them again** - each stops at an
entry that exists or would overwrite later changes, and their paths still assume the folder `curation/`. The last
state in `curation/` is commit `c490264`.

`collect_files.py` (the files of the export into `input/`) is no curation script: it is a tool of the generator
since 09.10.2026, `generator/interfaces/eln/collect_chemotion_files.py`, and reads the records from the sheet.
