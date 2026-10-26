from pathlib import Path

# All paths of the project - the only place where folders stand.
# The base folder is the root of the repository; the generator lies in generator/, next to it
# libraries/, ontologies/, shapes/, projects/, docs/ (overview: README.md at the root).
GENERATOR_FOLDER = Path(__file__).resolve().parent
BASE_FOLDER = GENERATOR_FOLDER.parent

# Every series has its project folder projects/<crate_identifier>/ (the identifier is the short
# name of the series, setup/series_short_name) with everything that belongs to it:
#   input/        ELN export, lab files (not versioned, see .gitignore)
#   core/         core files of the ELN records
#   curation/     PubChem answers, curation decisions, rule files
#   setup.yaml    setup sheet
#   answers.txt   answer file
#   crate/        the crate and the metadata overviews of its files (a to-do list only if something
#                 was left at the end)
#   reports/      SHACL reports, key catalogue
# A completed series lies in crate_completed/ instead of crate/ and is only read from then on.
PROJECTS_FOLDER = BASE_FOLDER / "projects"
CRATE_FILE_NAME = "ro-crate-metadata.json"
TODO_FILE_NAME = "todo_list.jsonld"
FILE_METADATA_FOLDER_NAME = "file_metadata"
_OPEN_CRATE_FOLDER_NAME = "crate"
_COMPLETED_CRATE_FOLDER_NAME = "crate_completed"


def project_folder(identifier: str) -> Path:
    """The project folder of the series with this identifier."""
    return PROJECTS_FOLDER / identifier


def crate_folder(identifier: str) -> Path:
    """The folder of the open crate with this identifier."""
    return project_folder(identifier) / _OPEN_CRATE_FOLDER_NAME


def archived_crate_folder(identifier: str) -> Path:
    """The folder of the completed (archived) crate with this identifier."""
    return project_folder(identifier) / _COMPLETED_CRATE_FOLDER_NAME


def crate_path(identifier: str) -> Path:
    return crate_folder(identifier) / CRATE_FILE_NAME


def open_crate_paths() -> list:
    """Every open crate (not the completed ones), sorted."""
    return sorted(PROJECTS_FOLDER.glob(f"*/{_OPEN_CRATE_FOLDER_NAME}/{CRATE_FILE_NAME}"))


def archived_crate_paths() -> list:
    """Every completed crate, sorted."""
    return sorted(PROJECTS_FOLDER.glob(f"*/{_COMPLETED_CRATE_FOLDER_NAME}/{CRATE_FILE_NAME}"))


def identifier_of_crate(path: Path) -> str:
    """The identifier of the series a crate file belongs to (the name of its project folder)."""
    return Path(path).resolve().parent.parent.name


def default_crate_path() -> Path:
    """For tools without an explicit crate: the only open crate. With none or several, say so."""
    paths = open_crate_paths()
    if len(paths) != 1:
        found = ", ".join(identifier_of_crate(p) for p in paths) or "none"
        raise SystemExit(f"Which crate? Open crates in {PROJECTS_FOLDER}: {found}. Pass the crate path explicitly.")
    return paths[0]


def reports_folder(identifier: str) -> Path:
    """Where the reports of a series go (SHACL, key catalogue)."""
    return project_folder(identifier) / "reports"


# Answer file and setup sheet of a series (see ANSWER_FILE/STRICT_ANSWERS in helpers/user_io.py
# and interfaces/eln/adapter.py).
def answer_file_path(identifier: str) -> Path:
    """The answer file of the series with this identifier: projects/<crate_identifier>/answers.txt
    (generator/workflow/rename_crate.py renames the whole project folder)."""
    return project_folder(identifier) / "answers.txt"


def setup_sheet_path(identifier: str) -> Path:
    return project_folder(identifier) / "setup.yaml"


def default_answer_file() -> Path:
    """For tools without an explicit answer file: the one of the only open crate."""
    return answer_file_path(identifier_of_crate(default_crate_path()))


# The files of the series (media objects), read by creation/media_object_functions.py, in the
# project folder under input/. They are only read - except for the metadata overview that a run in the project writes into
# each of the two folders (an isolated run does not).
# - series_files_folder: files for the whole series (SOPs, risk assessments, ...).
# - experiment_files_folder: one subfolder per experiment, whose name ends in exp<n>
#   (lab_data_for_crate_exp1, ...); files directly in the folder belong to no experiment.
# Note: the crate records the date of creation of the files (st_ctime = "created at this place") -
# keep the time stamps when moving the files (robocopy /COPY:DAT /DCOPY:DAT).
def series_files_folder(identifier: str) -> Path:
    return project_folder(identifier) / "input" / "additional_files_for_crate"


def experiment_files_folder(identifier: str) -> Path:
    return project_folder(identifier) / "input" / "lab_data_for_crate"


# Defines the Folder in which the Libraries are stored and the single paths to each library file
LIBRARY_FOLDER = BASE_FOLDER / "libraries"
DEVICE_LIBRARY_PATH = LIBRARY_FOLDER / "device_library.jsonld"
# Devices and materials apart (rule 2.15): the Device Library holds all devices - also the containers
# (cpo:ChemicalContainer) and their templates -, the Material Library their contents: what is used up
# in the lab and where it comes from (content, lot, receipt, delivery, production, booking out,
# certificates of analysis).
# Both are read together as one view (helpers/library_functions.py: load_device_libraries); a
# change lands in the file the entity comes from.
MATERIAL_LIBRARY_PATH = LIBRARY_FOLDER / "material_library.jsonld"
DEVICE_LIBRARY_PATHS = (DEVICE_LIBRARY_PATH, MATERIAL_LIBRARY_PATH)
PEOPLE_LIBRARY_PATH = LIBRARY_FOLDER / "people_library.jsonld"
ORGANIZATION_LIBRARY_PATH = LIBRARY_FOLDER / "organization_library.jsonld"
SOFTWARE_LIBRARY_PATH = LIBRARY_FOLDER / "software_library.jsonld"
REACTION_LIBRARY_PATH = LIBRARY_FOLDER / "reaction_library.jsonld"
CHEMICAL_ENTITY_LIBRARY_PATH = LIBRARY_FOLDER / "chemical_entity_library.jsonld"
# The modelling assumptions the generator makes in every crate, as fixed
# cpo:AssumptionTask entries; a value in the crate names them directly (rule 4.1, exception).
ASSUMPTION_LIBRARY_PATH = LIBRARY_FOLDER / "assumption_library.jsonld"
# Keeps a Fixed entry for every ontology/vocabulary used in the project (prefix, namespace,
# usedVersion, lastAccessDate, ontologyFile) - see creation/ontology_snapshot_functions.py.
# usedVersion/lastAccessDate cannot be determined automatically (they can stay the same over
# several runs, need not be the latest version) - update them here by hand when the version
# changes.
ONTOLOGY_LIBRARY_PATH = LIBRARY_FOLDER / "ontology_library.jsonld"

# Settings of the generator, no libraries.
CONFIG_FOLDER = GENERATOR_FOLDER / "config"

# The prefix table that goes into every crate made as its @context - loaded by
# helpers/file_handling.py as PROJECT_CONTEXT. Deliberately a file of its own and NOT part of
# the ontology_library: that documents vocabularies (with version and access date), this
# table additionally holds the local ID namespaces of the project (chem:, device:, task:, ...),
# behind which there is no ontology. Whatever is missing here stays an unresolvable IRI in
# the crate - see verify_context_completeness.
PROJECT_CONTEXT_PATH = CONFIG_FOLDER / "project_context.jsonld"

# Units and choice lists of quantity kinds (loaded by helpers/units.py). Which quantity kind a
# property has stands in the ontology instead (cpo:valueHasQuantityKind). A run asks for this
# folder to be committed too (helpers/git_functions.py: _committed_folders), so that the commit
# of a crate records which choice held.
UNITS_PATH = CONFIG_FOLDER / "units_and_quantity_kinds.json"

# Cache for downloaded external vocabularies (QUDT for the comparison in
# check_library_consistency.py). Not versioned and deliberately NOT under ontologies/ -
# workflow/run_shacl.py loads everything there into the data graph.
EXTERNAL_VOCABULARY_CACHE = BASE_FOLDER / "cache" / "external_vocabularies"


# Defines the folder in which the ontologies are stored
ONTOLOGY_FOLDER = BASE_FOLDER / "ontologies"
HLO_ONTOLOGY = ONTOLOGY_FOLDER / "HigherLevelOntology.rdf"
CPO_ONTOLOGY = ONTOLOGY_FOLDER / "ChemicalProcessOntology.rdf"


SHAPES_FOLDER = BASE_FOLDER / "shapes"
CONTEXT_SHAPES = SHAPES_FOLDER / "ContextRequirementShapes.ttl"
DATA_QUALITY_SHAPES = SHAPES_FOLDER / "DataQualityShapes.ttl"
# Generated by workflow/generate_quantity_kind_shapes.py from the ontology (rule 4.4), not by hand.
QUANTITY_KIND_SHAPES = SHAPES_FOLDER / "QuantityKindShapes.ttl"
# Generated by workflow/generate_function_shapes.py from cpo:offersFunction (rule 4.9), not by hand.
FUNCTION_SHAPES = SHAPES_FOLDER / "FunctionShapes.ttl"
SHACL_REPORT_NAME = "shacl_report.csv"
SHACL_REPORT_SUMMARIZED_NAME = "shacl_report_summarized.csv"
