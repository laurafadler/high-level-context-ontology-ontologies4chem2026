"""
Media objects (file, image, video - all schema:MediaObject) and their columns.

The files are read from folders, not asked for (path_definitions.py): series_files_folder
holds the files of the whole series, experiment_files_folder one subfolder per experiment
whose name ends in exp<n>. Their metadata is collected fresh on every run
(get_additional_information/get_file_metadata.py) - name, type, dates, size, author, storage
location and the column headers - so a file that changed brings its new values. Still asked:
the kind of media object for an unknown file extension, the creator when the author is not
a person of the library, the reference column of a table, and the task that produced a file.

These are created UP FRONT per experiment (create_all_media_objects), not when an
individual process variable is being resolved: plain data entry (which files are there,
which column headers do they have) kept apart from the modelling decision "which column
belongs to which process variable". That decision comes later, when add_evidence and
add_reference (helpers/evidence_reference.py) let the user pick, for the evidence or
reference of a series variable, from the columns created here that are not yet linked (see
get_available_columns_for_experiment/pick_column_for_series_variable below). There the
context - which variable is being described - is immediately clear, which is why the choice
does NOT happen here.

Only tabular files get columns: a file whose first row holds headers. Every header becomes a
column; one of them is the ReferenceColumn (usually time), which every other column points
at through cpo:hasReferenceColumn.
"""

import re
from pathlib import Path

import path_definitions
from get_additional_information.get_file_metadata import collect_folder_metadata, overview_path, write_metadata_workbook
from helpers.entities import add_entity, find_entity, ask_entity_choice, find_entities_by_type, as_list
from helpers.git_functions import is_isolated_copy
from helpers.properties import set_property, set_literal_property, check_type
from helpers.identifiers import get_display_label, claim_id, make_root_id, make_owned_id, key_name, current_crate_identifier
from helpers.library_functions import find_library_item
from helpers.user_io import ask_user, question_path
from helpers.ontology_functions import find_subclasses


# Kind of media object by file extension. An extension missing here is asked.
MEDIA_OBJECT_TYPE_BY_EXTENSION = {
    **dict.fromkeys(["xlsx", "xlsm", "xls", "csv", "txt", "json", "docx", "docm", "pdf", "pptx", "pptm",
                     # The export of an ELN (a ZIP with ro-crate-metadata.json, The ELN Consortium).
                     "eln"], "cpo:File"),
    **dict.fromkeys(["png", "jpg", "jpeg", "tif", "tiff", "gif", "bmp"], "cpo:Image"),
    **dict.fromkeys(["mp4", "mov", "avi", "mkv"], "cpo:Video"),
}

# schema:encodingFormat is the MIME type (as RO-Crate requires). Deliberately a fixed table
# instead of the mimetypes module: on Windows that reads the registry, and the crate would then
# depend on the computer. An extension missing here gets no encodingFormat.
ENCODING_FORMAT_BY_EXTENSION = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12",
    "xls": "application/vnd.ms-excel",
    "csv": "text/csv",
    "txt": "text/plain",
    "json": "application/json",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "docm": "application/vnd.ms-word.document.macroEnabled.12",
    "pdf": "application/pdf",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "pptm": "application/vnd.ms-powerpoint.presentation.macroEnabled.12",
    "eln": "application/vnd.eln+zip",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "tif": "image/tiff",
    "tiff": "image/tiff",
    "gif": "image/gif",
    "bmp": "image/bmp",
    "mp4": "video/mp4",
    "mov": "video/quicktime",
    "avi": "video/x-msvideo",
    "mkv": "video/x-matroska",
}

# Subfolder of an experiment: the name ends in exp<n> or experiment<n>, optionally with
# _ - or a space before it (lab_data_for_crate_exp1, experiment_2, ...).
EXPERIMENT_FOLDER_PATTERN = re.compile(r"exp(?:eriment)?[_\- ]?(\d+)$", re.IGNORECASE)


def media_object_types(namespace_collection):
    """The subclasses of schema:MediaObject from the ontology - cpo:File, cpo:Image,
    cpo:Video.

    The root itself is left out: it only groups, it comes from schema.org, and it is never
    instantiated here.
    """
    return find_subclasses("schema:MediaObject", namespace_collection, include_root=False)


def create_time_instant(value: str, scope: str, namespace_collection: dict, datagraph: dict, todo_list: list, entity_id: str):
    """A time:Instant as an hlo:Actual WITHOUT an evidence/reference chain.

    For machine-generated timestamps (a file's creation date, say) that count as a known
    value straight away, rather than having to be backed by a measurement or an estimate
    the way a measured process temperature does.

    entity_id is the content-based ID (helpers/identifiers.py), built by the caller from what
    the instant belongs to.
    """
    time_type = check_type("time:Instant", namespace_collection)
    entity_id = claim_id(entity_id, datagraph, todo_list)
    instant = {"@id": entity_id, "@type": [time_type, scope, "hlo:Actual"]}
    set_literal_property(instant, "rdf:value", value, "xsd:dateTime", namespace_collection)
    add_entity(datagraph, instant)
    return instant


def _normalize_name(text: str) -> str:
    return "".join(str(text).lower().split())


def person_by_author(author: str, people_library: dict):
    """The person of the library whose name (or local ID) is the author of a file, or None.

    Case and spaces do not count ("Laura Fadler" is person:LauraFadler). Only an unambiguous
    match counts - two people with the same name leave the choice to the user.
    """
    if not author or not author.strip():
        return None
    wanted = _normalize_name(author)
    matches = []
    for entity in people_library.get("@graph", []):
        entity_id = entity.get("@id", "")
        if not entity_id.startswith("person:") or "schema:Person" not in as_list(entity.get("@type")):
            continue
        if wanted in (_normalize_name(entity.get("schema:name", "")), _normalize_name(entity_id.removeprefix("person:"))):
            matches.append(entity)
    return matches[0] if len(matches) == 1 else None


def _ask_creator(mo: dict, scope: str, namespace_collection: dict, people_library: dict):
    """The creator of a file whose author is not (unambiguously) a person of the library.

    Only a person: a file that software wrote is described through the task that generated it
    (cpo:generatedBy -> cpo:usedSoftware, rule 4.8). There is no property from the file straight to
    the software - it would be a second way to say the same.
    """
    label = get_display_label(mo)
    creator_kind = ask_user(f"[{scope}] Was {label} created by a person of the people library?", ["Person", "No person/unknown"], question_id="creator_kind")
    if creator_kind == "Person":
        person = find_library_item(people_library, "person:", f"[{scope}] Which person created {label}?", question_id="creator_person",
                                   entity_type="schema:Person")
        if person:
            set_property(mo, "cpo:hasCreator", person, namespace_collection)


def _set_file_metadata(mo: dict, metadata: dict, scope: str, namespace_collection: dict, datagraph: dict, todo_list: list, people_library: dict):
    """Everything the metadata of the file says about it (see get_file_metadata)."""
    # The two points in time are actuals with the date directly at them, without evidence and task -
    # a deliberate exception from rule 4.1: read from the file system, a
    # property of the file like cpo:fileSize, not a statement about the process. The shape
    # hlo:Actual_NoValue_Shape allows exactly this case.
    created_instant = create_time_instant(metadata["Created"], scope, namespace_collection, datagraph, todo_list,
                                          entity_id=make_owned_id("DateCreated", mo["@id"]))
    set_property(mo, "cpo:dateCreated", created_instant, namespace_collection)

    # Only if the file was changed after it was created.
    if metadata["Last Modified"] != metadata["Created"]:
        modified_instant = create_time_instant(metadata["Last Modified"], scope, namespace_collection, datagraph, todo_list,
                                               entity_id=make_owned_id("DateModified", mo["@id"]))
        set_property(mo, "cpo:dateModified", modified_instant, namespace_collection)

    # fileSize in bytes; fileType is the extension, encodingFormat the MIME type.
    set_property(mo, "cpo:fileSize", int(metadata["Size (bytes)"]), namespace_collection)
    extension = metadata["File Type"]
    if extension:
        set_property(mo, "cpo:fileType", extension, namespace_collection)
    if extension in ENCODING_FORMAT_BY_EXTENSION:
        set_property(mo, "schema:encodingFormat", ENCODING_FORMAT_BY_EXTENSION[extension], namespace_collection)

    person = person_by_author(metadata["Author"], people_library)
    if person:
        set_property(mo, "cpo:hasCreator", person, namespace_collection)
    else:
        _ask_creator(mo, scope, namespace_collection, people_library)

    # Placeholder until it is settled where/how files are actually stored: the path of the file.
    set_property(mo, "cpo:hasStorageLocation", _storage_location(metadata["File Path"]), namespace_collection)


def _storage_location(file_path: str) -> str:
    """Where a file lies: relative to the repository for a file inside it
    (projects/<crate_identifier>/input/...), otherwise the absolute path."""
    # The files lie in the project folder. Relative, so that crate and isolated copy name the same
    # place and the repository can move (like the libraries).
    path = Path(file_path)
    try:
        return path.resolve().relative_to(path_definitions.BASE_FOLDER.resolve()).as_posix()
    except ValueError:
        return str(path)


def _create_reference_column(file_entity: dict, header: str, scope: str, namespace_collection: dict, datagraph: dict, todo_list: list):
    column_type = check_type("cpo:ReferenceColumn", namespace_collection)
    entity_id = claim_id(make_owned_id("ReferenceColumn", file_entity["@id"]), datagraph, todo_list)
    column = {"@id": entity_id, "@type": [column_type, scope]}
    set_property(column, "cpo:hasHeader", header, namespace_collection)
    set_property(column, "dcterms:isPartOf", file_entity, namespace_collection)
    set_property(file_entity, "dcterms:hasPart", column, namespace_collection, True)
    add_entity(datagraph, column)
    return column


def _create_data_column(file_entity: dict, reference_column: dict, scope: str, namespace_collection: dict, datagraph: dict, todo_list: list, header: str):
    """One data column, named by its header."""

    column_type = check_type("cpo:Column", namespace_collection)
    entity_id = claim_id(make_owned_id(f"Column_{header}", file_entity["@id"]),
                             datagraph, todo_list, what=f"The column '{header}'")
    column = {"@id": entity_id, "@type": [column_type, scope]}
    set_property(column, "cpo:hasHeader", header, namespace_collection)
    set_property(column, "dcterms:isPartOf", file_entity, namespace_collection)
    set_property(file_entity, "dcterms:hasPart", column, namespace_collection, True)

    set_property(column, "cpo:hasReferenceColumn", reference_column, namespace_collection)
    set_property(reference_column, "cpo:isReferenceColumnFor", column, namespace_collection, True)

    add_entity(datagraph, column)
    return column


def _create_columns(file_entity: dict, headers: list, scope: str, namespace_collection: dict, datagraph: dict, todo_list: list):
    """Every header of the first row becomes a column; the user picks the reference column."""
    duplicates = sorted({header for header in headers if headers.count(header) > 1})
    if duplicates:
        raise ValueError(
            f"{get_display_label(file_entity)}: the first row holds {', '.join(repr(h) for h in duplicates)} more than "
            "once. The first row of a table must hold its column headers, each one only once - "
            "fix the file (a group row above the headers, for instance, belongs removed).")

    reference_header = ask_user(f"[{scope}] Which column of {get_display_label(file_entity)} is the reference column (usually time)?",
                                headers, question_id="reference_column_header")
    reference_column = _create_reference_column(file_entity, reference_header, scope, namespace_collection, datagraph, todo_list)
    for header in headers:
        if header != reference_header:
            _create_data_column(file_entity, reference_column, scope, namespace_collection, datagraph, todo_list, header)


def create_media_object(scope: str, nr: int, namespace_collection: dict, datagraph: dict, todo_list: list, people_library: dict, metadata: dict):
    """Create the media object for one file (one row of get_file_metadata). Every question
    about it runs under "media_object:<file name>" (helpers/identifiers.py: key_name)."""
    experiment_number = nr if scope == "hlo:ExperimentSpecific" else None
    with question_path("media_object", key_name(make_root_id("File", metadata["File Name"], scope, experiment_number))):
        return _describe_media_object(scope, nr, namespace_collection, datagraph, todo_list, people_library, metadata)


def _describe_media_object(scope: str, nr: int, namespace_collection: dict, datagraph: dict, todo_list: list, people_library: dict, metadata: dict):
    name = metadata["File Name"]
    mo_type_answer = MEDIA_OBJECT_TYPE_BY_EXTENSION.get(metadata["File Type"])
    if mo_type_answer is None:
        mo_type_answer = ask_user(f"[{scope}] Is {name} a File, Image, or Video?", media_object_types(namespace_collection), question_id="media_object_type")
    mo_type_short = mo_type_answer.split(":", 1)[-1]
    mo_type = check_type(mo_type_answer, namespace_collection)
    experiment_number = nr if scope == "hlo:ExperimentSpecific" else None
    # The file name is name and ID (rule 1.1).
    entity_id = claim_id(make_root_id("File", name, scope, experiment_number), datagraph, todo_list,
                             what=f"The {mo_type_short.lower()} '{name}'")
    media_object = {"@id": entity_id, "@type": [mo_type, scope]}
    set_property(media_object, "schema:name", name, namespace_collection)
    if metadata["File Type"] == "eln":
        # RO-Crate recommends a description per file; for the ELN export it says what it is.
        set_property(media_object, "schema:description", "The export of the ELN record(s) this crate is built "
                     "from, in the .eln format of The ELN Consortium (a ZIP archive with its own ro-crate-metadata.json).",
                     namespace_collection)

    print(f"\n=== Now describing {mo_type_short} \"{get_display_label(media_object)}\" ({entity_id}, {scope}) ===")

    _set_file_metadata(media_object, metadata, scope, namespace_collection, datagraph, todo_list, people_library)

    if mo_type_answer == "cpo:File" and metadata["Headers"]:
        _create_columns(media_object, metadata["Headers"], scope, namespace_collection, datagraph, todo_list)

    add_entity(datagraph, media_object)

    # Which task produced the file? Like for the values, puts a task placeholder onto the to-do
    # list, which is described later in the task stage (see there).
    # Local import: helpers/evidence_reference.py imports this module, an import at module
    # level would be circular.
    from helpers.evidence_reference import ask_task_for_media_object
    ask_task_for_media_object(media_object, scope, nr, namespace_collection, datagraph, todo_list)

    return media_object


def read_files_folder(folder: Path) -> list:
    """The metadata of every file in folder and its subfolders, collected fresh.

    Writes the overview next to the crate (projects/<identifier>/crate/file_metadata) and, in a run in the
    project, also into the folder itself; an isolated copy leaves the folder untouched.
    """
    folder = Path(folder)
    if not folder.is_dir():
        raise FileNotFoundError(f"The folder of the files does not exist: {folder} (see path_definitions.py).")
    rows, failed = collect_folder_metadata(folder)
    if failed:
        raise RuntimeError(f"Could not read {len(failed)} file(s) in {folder} - are they open? "
                           + "; ".join(f"{name}: {reason}" for name, reason in failed))

    next_to_crate = path_definitions.crate_folder(current_crate_identifier()) / path_definitions.FILE_METADATA_FOLDER_NAME
    write_metadata_workbook(rows, next_to_crate / overview_path(folder).name)
    if not is_isolated_copy():
        write_metadata_workbook(rows, overview_path(folder))
    return rows


def experiment_files(rows: list, number_experiments: int, planned: int = None) -> dict:
    """The rows of experiment_files_folder per experiment number, from the name of their
    first-level subfolder. Files outside such a subfolder belong to no experiment and are
    left out (with a note). A subfolder for an experiment not conducted yet is left out as well
    (the crate is continued experiment by experiment); it is an error only beyond the planned
    number, when that is known."""
    by_experiment = {nr: [] for nr in range(1, number_experiments + 1)}
    for row in rows:
        subfolder = row["Folder"].split("/", 1)[0]
        match = EXPERIMENT_FOLDER_PATTERN.search(subfolder)
        if not match:
            print(f"Note: {row['Folder'] or '.'}/{row['File Name']} is not in an experiment subfolder (...exp<n>) - left out.")
            continue
        nr = int(match.group(1))
        if planned is not None and nr > planned:
            raise ValueError(f"The folder '{subfolder}' is for experiment {nr}, but the series plans only {planned} experiment(s).")
        if nr not in by_experiment:
            print(f"Note: {row['Folder']}/{row['File Name']} belongs to experiment {nr}, which is not conducted yet - left out.")
            continue
        by_experiment[nr].append(row)
    return by_experiment


def create_all_media_objects(namespace_collection: dict, datagraph: dict, todo_list: list, number_experiments: int, people_library: dict):
    """Runs deliberately BEFORE devices, materials, phases and reactions (see main.py):
    the evidence/reference questions for series process variables asked there later (see
    helpers/evidence_reference.py) draw on the columns created here per experiment, instead
    of describing a new file themselves.

    First the series-wide files (SOPs, for example, from series_files_folder), then the
    experiment-specific files per experiment (measurement data, from the experiment
    subfolders of experiment_files_folder).
    """
    # The files lie in the project folder of the series (projects/<crate_identifier>/input/).
    identifier = current_crate_identifier()
    series_rows = read_files_folder(path_definitions.series_files_folder(identifier))
    series = find_entities_by_type(datagraph, "cpo:ExperimentalSeries", namespace_collection)
    planned = series[0].get("cpo:hasNumberOfPlannedExperiments") if series else None
    by_experiment = experiment_files(read_files_folder(path_definitions.experiment_files_folder(identifier)), number_experiments, planned)

    experiments = find_entities_by_type(datagraph, "cpo:SingleExperiment", namespace_collection)

    print("\n--- Media Objects: Series ---")
    for row in series_rows:
        media_object = create_media_object("hlo:SeriesSpecific", None, namespace_collection, datagraph, todo_list, people_library, row)
        if series:
            _link_to_owner(media_object, series[0], namespace_collection)

    for nr, rows in by_experiment.items():
        experiment = next((e for e in experiments if e["@id"].endswith(f"SingleExperiment_{nr}")), None)
        with question_path("experiment", nr):
            print(f"\n--- Media Objects: Experiment {nr} ---")
            for row in rows:
                media_object = create_media_object("hlo:ExperimentSpecific", nr, namespace_collection, datagraph, todo_list, people_library, row)
                if experiment is not None:
                    _link_to_owner(media_object, experiment, namespace_collection)
    return []


def _link_to_owner(media_object: dict, owner: dict, namespace_collection: dict):
    """The file belongs to the series or experiment whose folder it comes from: schema:about
    on the file, schema:subjectOf on the owner. Independent of cpo:generatedBy, which says
    how the file came about (a task), not to whom it belongs."""
    # As everywhere both directions - no reasoner runs that would add the inverse.
    set_property(media_object, "schema:about", owner, namespace_collection)
    set_property(owner, "schema:subjectOf", media_object, namespace_collection, True)


# ---------------------------------------------------------------------------
# Choosing a column created already and not linked yet for a
# SeriesVariable evidence/reference (see helpers/evidence_reference.py)
# ---------------------------------------------------------------------------

def get_available_columns_for_experiment(datagraph: dict, nr: int) -> list:
    """Every cpo:Column entity (no ReferenceColumns) of media objects from experiment nr
    that is not yet assigned to a process variable through isDataReferenceFor.

    The assignment to an experiment runs through the ID (see helpers/identifiers.py:
    experiment-specific IDs always end in "_{nr}") - unlike phases, which reach their
    experiment through their material or device, columns have no structural chain of their
    own.
    """
    suffix = f"_{nr}"
    columns = []
    for candidate in datagraph.get("@graph", []):
        types = as_list(candidate.get("@type"))
        if "cpo:Column" not in types or "cpo:ReferenceColumn" in types:
            continue
        if "hlo:ExperimentSpecific" not in types:
            continue
        if "cpo:isDataReferenceFor" in candidate:
            continue
        if not candidate.get("@id", "").endswith(suffix):
            continue
        columns.append(candidate)
    return columns


def _column_candidate_label(column: dict, datagraph: dict) -> str:
    file_ref = column.get("dcterms:isPartOf")
    file_id = file_ref.get("@id") if isinstance(file_ref, dict) else file_ref
    file_entity = find_entity(datagraph, file_id) if file_id else None
    file_label = get_display_label(file_entity) if file_entity else "?"
    header = column.get("cpo:hasHeader", "?")
    return f"{file_label}: {header}"


def pick_column_for_series_variable(series_variable: dict, context_hint: str, scope: str, nr: int, namespace_collection: dict, datagraph: dict, *, question_id_prefix: str) -> bool:
    """Link series_variable (a cpo:SeriesVariable) in both directions to one of the
    columns already registered for this experiment and not yet linked
    (hasDataReference/isDataReferenceFor).

    Returns False when no suitable column exists - because no media objects have been
    recorded for this experiment yet, for instance - and leaves it to the caller to decide
    what to do about that.

    question_id_prefix is MANDATORY (see helpers/user_io.py): the only caller
    (helpers/evidence_reference.py) passes "evidence_series" or "reference_series",
    depending on whether an evidence or a reference value is being described.
    """
    candidates = get_available_columns_for_experiment(datagraph, nr)
    if not candidates:
        print(f"[{scope}] No unlinked data columns available for Experiment {nr} - describe the underlying file first (see Media Objects step).")
        return False

    column_id = ask_entity_choice(
        f"[{scope}] Which recorded column is {context_hint}?",
        candidates,
        label_fn=lambda c: _column_candidate_label(c, datagraph),
        question_id=f"{question_id_prefix}_column"
    )
    column = find_entity(datagraph, column_id)
    set_property(series_variable, "cpo:hasDataReference", column, namespace_collection)
    set_property(column, "cpo:isDataReferenceFor", series_variable, namespace_collection)
    return True
