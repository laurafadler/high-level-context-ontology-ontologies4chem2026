# ELN example exports

Official examples of the ELN File Format (`.eln`, a zipped RO-Crate), used to build and test the
ELN connection (`generator/interfaces/eln/README.md`).

Source: https://github.com/TheELNConsortium/TheELNFileFormat/tree/master/examples
(downloaded 28.09.2026, unchanged, renamed).

| Export | ELN | Where | Content |
|---|---|---|---|
| `ai4green_export_workbook_2024-08-27.eln` | AI4Green 1.6.0 | `projects/amidation_ai4green_ai4_001/input/eln/` (the amidation is built from it; core file in `core/`, PubChem answers in `curation/pubchem/`) | one reaction (amidation) with reactants, reagents, solvent, product, conditions, yield; chemistry in a JSON file next to the RO-Crate, plus `.rxn` and a PDF summary |
| `elabftw/elabftw_export.eln` | eLabFTW | here | twelve experiments and resources (demo content) with people, files, steps, comments and free fields (`PropertyValue` with units) |

```
examples/elabftw/
  elabftw_export.eln
  example_eln_elabftw/                   the same export unpacked, for reading by eye only
  core_files/eLabFTW_<record id>.json    one core file per record (12)
```

Regenerate the core files (from the repository root): for an export in a project the core files go
to its `core/` folder, otherwise into `core_files/` next to the export.

```
python generator/workflow/eln_to_core.py projects/amidation_ai4green_ai4_001/input/eln/ai4green_export_workbook_2024-08-27.eln
python generator/workflow/eln_to_core.py generator/interfaces/eln/examples/elabftw/elabftw_export.eln
```

The reader works on the `.eln` file, never on the unpacked folder; the unpacked copy may be
deleted without loss. `PYTHONIOENCODING=utf-8` is needed for the eLabFTW export (a Japanese title).
