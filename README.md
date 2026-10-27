# A high-level Context ontology

**A context ontology for chemical experiments, with SHACL shapes and a generator that describes
experiments as RO-Crates.**

This repository accompanies the talk "A high-level Context ontology" at Ontologies4Chem 2026. It is a
snapshot of an ongoing master thesis project (Laura Fadler, RWTH Aachen, SVT & University of Cambridge,
Department of Chemical Engineering and Biotechnology). It is shared so that people can look at the approach
and **comment on it** - the ontologies, the SHACL shapes, the libraries and the generator are all open for
feedback.

In short: a generator turns an ELN export (or lab files) plus a short setup/answer sheet into an RO-Crate
(`ro-crate-metadata.json`, JSON-LD). It is built on two ontologies of its own:

- **HLO** (Higher Level Ontology): levels (library entry / series / experiment), evidence and reference,
  context requirements
- **CPO** (Chemical Process Ontology): devices, materials, phases, reactions, tasks

SHACL shapes check whether a crate has the context it needs. Every answer the generator receives is
recorded together with its source in an answer file, so it is always clear where a value comes from.

Status: work in progress (October 2026). The crates validate against the RO-Crate 1.3 profile except for
the licence.

## Feedback welcome

Anything is useful - questions, "I would have modelled this differently", missing concepts, things that
are unclear.

- **Open an issue** for a concrete point (a class, a property, a shape, a crate). There is a feedback
  template; please name the file and, if possible, the term or line.
- **Use Discussions** for broader questions or ideas about the approach.

Questions I would particularly like opinions on:

1. Are the context requirements (see `docs/shape_overview.html`) the right ones for reusing a
   chemical experiment? What is missing, what is too much?
2. Does the split between library entries, series records and experiment records make sense?
3. Where do HLO and CPO overlap with existing ontologies, and where should they reuse terms instead?

## Where to start reading

- [`docs/shape_overview.html`](docs/shape_overview.html): the 89 context requirements - what each one asks,
  how its SHACL shape checks it, and a short guide to the terms. GitHub shows HTML files only as source:
  download the file and open it in a browser, or use the GitHub Pages link if it is set up for this
  repository.
- [`docs/property_overview.html`](docs/property_overview.html) and
  [`docs/property_overview/`](docs/property_overview/README.md): which properties each class has on each
  level (the Markdown version is readable directly on GitHub).
- [`docs/rules_crate.md`](docs/rules_crate.md): the rules every crate follows; the requirements and shapes
  refer to them by number ("rule 7.16").
- [`ontologies/`](ontologies/) and [`shapes/`](shapes/): the two ontologies and the SHACL shapes themselves.
- A finished crate, e.g. [`projects/hydrogenation_rdy_2026_09/crate/ro-crate-metadata.json`](projects/hydrogenation_rdy_2026_09/crate/ro-crate-metadata.json)
  (large - better downloaded than opened on GitHub).

## Example series

| Folder | What it is | Data |
|---|---|---|
| `projects/pba_synthesis/` | Prussian blue analogue synthesis on a flow setup, two of 126 planned experiments | from our group |
| `projects/hydrogenation_rdy_2026_09/` | batch hydrogenation of adiponitrile over platinum, two experiments, lab files only (no ELN) | from our group |
| `projects/amidation_ai4green_ai4_001/` | amide coupling from the public AI4Green example export of the ELN Consortium | public example |
| `projects/chemotion_example/` | two Chemotion records: reductive catalytic fractionation of spruce wood | example export from a colleague |

Each folder holds the input files (`input/`: ELN export, lab files), the crate (`crate/` or
`crate_completed/`), the setup sheet (`setup.yaml`), the answer file (`answers.txt`), curation files and
reports - so every value in a crate can be traced back to where it came from.

## Layout

```
projects/<crate_identifier>/ one folder per series (the identifier is the crate's short name)
  input/                     ELN export and lab files the crate is built from
  core/                      core files of the ELN records (neutral JSON)
  curation/                  PubChem answers, curation decisions, rule files of this series
  setup.yaml                 setup sheet: what only a person knows about the setup
  answers.txt                answer file: every answer of the generator, with its source
  crate/                     ro-crate-metadata.json and file overviews (open series)
  crate_completed/           instead of crate/ once the series is completed
  reports/                   SHACL report, coverage, key catalogue
libraries/                   the libraries (*_library.jsonld) - fixed entries the crates point to
ontologies/                  HigherLevelOntology.rdf, ChemicalProcessOntology.rdf
shapes/                      context requirements, data quality, quantity kinds, functions (SHACL)
generator/
  main.py, path_definitions.py   entry point; every path of the project
  creation/, helpers/            building the crate
  config/                        units and quantity kinds, prefix table
  interfaces/eln/                ELN reader, profiles (AI4Green, Chemotion, eLabFTW), adapter (see its README)
  interfaces/pubchem/            PubChem lookup
  workflow/                      new project, isolated copy, answer driver, SHACL, reports,
                                 library checks and entries, the two overviews in docs/
  tests/                         tests of the generator (run_all_tests.py runs every <name>_test.py)
docs/                        overviews, rules, guide for a new series, how to add library entries
```

## Running it

With Python 3.14 and `pip install -r dependencies.txt`, from the repository root:

```
# check a crate against the shapes
python generator/workflow/run_shacl.py --crate projects/hydrogenation_rdy_2026_09/crate/ro-crate-metadata.json

# check the libraries and the context requirements
python generator/workflow/run_shacl.py --libraries
python generator/workflow/check_library_consistency.py
python generator/workflow/check_context_requirements_consistency.py

# start a new series of your own (walk-through: docs/new_series_guide.md)
python generator/workflow/new_project.py <crate_identifier> [--eln <export.eln> | --experiments <n>]
```

Several tests and checks need internet access (the RO-Crate JSON-LD context, PubChem, QUDT). The
generator commits the libraries to Git at the end of a real run, so run it in
a clone of this repository, not in a downloaded ZIP.

## Notes on this snapshot

- The libraries also contain entries from series that are not published here; some usage histories
  therefore point to crates that are not in this repository.
- The crates record the Git commit of the library state they were built against. Those commits belong to
  the development repository and do not exist here.
- Comments in the libraries and curation files often say who suggested or confirmed a value (including
  "suggested by Claude Code", an AI coding assistant used during development). This provenance is kept
  on purpose.

## Licence

No licence has been chosen yet. You are welcome to read, discuss and comment on everything here; please
ask before reusing the material elsewhere.
