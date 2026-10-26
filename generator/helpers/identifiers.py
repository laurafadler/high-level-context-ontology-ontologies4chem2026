import re
import unicodedata
from contextlib import contextmanager


def generate_id(base_name, datagraph: dict, todo_list: list = None, scope: str = None, experiment_number: int = None) -> str:
    """Build an ID that is not yet used in the crate - by COUNTING, the first free number.

    Only for what has no content to be named after yet: the series and its experiments
    (where the number is the identity), transfers and occupation states (numbered within
    their place). Everything else is
    built by the make_*_id functions below, which never count.

    Follows the pattern '#Name_0001', '#Name_0001_SeriesSpecific',
    '#Name_0001_ExperimentSpecific_2', ... The experiment_number is only appended
    when it is passed (typically for scope hlo:ExperimentSpecific), so that the ID
    itself shows which experiment it belongs to - the same idea as in the
    library-based IDs (see generate_id_from_library_id).
    """

    # if we append a scope there is an underscore between number and scope, otherwise not
    if scope:

        prefix, scope_name = scope.split(":", 1)
        scope = str(f"_{scope_name}")
    else:
        scope = ""

    if experiment_number is not None:
        scope += f"_{experiment_number}"

    if isinstance(base_name, list):
            base_name = base_name[0]


    if ":" in base_name:

        prefix, base_name = base_name.split(":", 1)
    # Searches the datagraph for all existing IDs and makes a list of them
    # At some point I may have to search all libraries too, or I make another list in which I count for every type how many I have already, and then it only has to be read and the following number taken
    existing_ids = {entity.get("@id", "") for entity in datagraph.get("@graph", [])}

    if todo_list:
        existing_ids.update(
            entity.get("@id", "")
            for entity in todo_list
        )

    # We start counting at one and increase by one whenever we find an ID in our list that starts the same way.
    counter = 1
    while True:
        candidate = f"{CRATE_ID_PREFIX}{base_name}_{counter:04d}{scope}"
        if candidate not in existing_ids:
            # If we have found an ID that does not exist in the list yet, we return it as a string
            return candidate
        counter += 1




def generate_library_id(prefix: str, base_name, library: dict) -> str:
    """Build an ID for an entry that lives permanently in a library.

    Uses "prefix:Name_0001" rather than the "#Name_0001_Scope" style of
    generate_id. The difference is meant to be visible: a CURIE says "fixed library
    entry, stable across crate runs", a bare "#fragment" says "created during this
    run". There is also a practical reason: a bare fragment resolves relative to
    whichever document it is parsed in, so copying such a reference into another
    document silently makes it point somewhere else. A CURIE always resolves the
    same way through the @context (see the CURIE migration of the device library).

    The scope is not appended: for library entries it is already in the @type and
    would be redundant in the name.
    """
    if isinstance(base_name, list):
        base_name = base_name[0]
    base_name = base_name.split(":", 1)[-1]

    existing_ids = {entity.get("@id", "") for entity in library.get("@graph", [])}
    counter = 1
    while True:
        candidate = f"{prefix}:{base_name}_{counter:04d}"
        if candidate not in existing_ids:
            return candidate
        counter += 1


def generate_id_from_name(name: str, scope: str = None, experiment_number: int = None) -> str:
    """Build an ID from a name that is already unique, without adding a counter.

    Unlike generate_id, this appends no number of its own. It is meant for cases
    where the name is unique already because it contains the unique local name of
    another entity (for example "Temperature_GasPhase_0002", built from
    short_local_name() of a phase). Using generate_id there would add a second,
    redundant block of digits ("#Temperature_GasPhase_0002_0001_..." instead of
    "#Temperature_GasPhase_0002_...").

    'GasPhase_0002' + ExperimentSpecific + 1 -> '#GasPhase_0002_ExperimentSpecific_1'
    """
    if scope:
        _, scope_name = scope.split(":", 1)
    else:
        scope_name = ""

    entity_id = f"{CRATE_ID_PREFIX}{name}_{scope_name}" if scope_name else f"{CRATE_ID_PREFIX}{name}"

    if experiment_number is not None:
        entity_id += f"_{experiment_number}"

    return entity_id


# Template and exemplar (rule 3.11): an exemplar of the Device Library ("device:bottle_RDY",
# bottle no. 13) specializes a template ("device:bottle_template") and takes over form, body
# and ports from it. The copies of these parts in the crate must be named after the EXEMPLAR,
# otherwise three bottles of the same template would get the same IDs. While an exemplar is
# copied, an alias therefore holds: a local name that starts with that of the template gets
# that of the exemplar ("bottle_template_opening" -> "bottle_RDY_opening"). Without an active
# alias nothing changes.
_library_aliases = []


@contextmanager
def library_name_alias(template_id: str, exemplar_id: str):
    """While the parts an exemplar takes over from its template are copied, name the copies after
    the exemplar (see above)."""
    _library_aliases.append((local_name(template_id), local_name(exemplar_id)))
    try:
        yield
    finally:
        _library_aliases.pop()


def _aliased(local: str) -> str:
    for template_local, exemplar_local in reversed(_library_aliases):
        # The exemplar itself and its own parts are already named after it - even if its name starts
        # with that of the template ("three_neck_flask_100mL_01" of the template "three_neck_flask_100mL"
        # stays as it is and does not become "..._01_01").
        if local == exemplar_local or local.startswith(exemplar_local + "_"):
            return local
        if local == template_local or local.startswith(template_local + "_"):
            return exemplar_local + local[len(template_local):]
    return local


def aliased_name(name):
    """A name taken over from a template part, named after the exemplar as its ID is ("Body material of
    glass_bottle_500mL" -> "Body material of glass_bottle_500mL_01") - otherwise two bottles of one template
    had parts of the same name, and an answer naming one of them fitted both.
    Only the template's local name as a whole word is replaced; a name already naming the exemplar stays."""
    if not isinstance(name, str):
        return name
    for template_local, exemplar_local in reversed(_library_aliases):
        name = re.sub(rf"(?<![\w-]){re.escape(template_local)}(?![\w-])", exemplar_local, name)
    return name


def generate_id_from_library_id(library_id: str, scope: str = None, experiment_number: int = None) -> str:
    """Build an ID for a series- or experiment-specific entity that specializes a
    library entry (a device, a port, ...).

    Instead of a generic counter the local name of the library ID is carried over,
    so that the ID shows which library entry it came from:

    'device:reactor001' + SeriesSpecific         -> '#reactor001_SeriesSpecific'
    'device:reactor001' + ExperimentSpecific + 2 -> '#reactor001_ExperimentSpecific_2'
    """
    local_name = _aliased(library_id.split(":", 1)[-1])
    return generate_id_from_name(local_name, scope, experiment_number)


def generate_name(id: str):
    # remove the hashtag or the namespace prefix (e.g. "environment:") at the
    # start and put spaces instead of _
    # First the crate prefix, then a library prefix - otherwise of
    # "crate:x/Stream_A" the part "x/Stream_A" with the identifier would stay in the name.
    name = strip_crate_prefix(id)
    if ":" in name:
        name = name.split(":", 1)[-1]
    return name.replace("_", " ")


def get_display_label(entity: dict) -> str:
    """Human-readable label for an entity, shown in questions instead of the raw @id.

    Uses schema:name when present (given by hand or generated - see generate_name),
    and otherwise falls back to deriving a label from the @id.

    schema:name may hold several values (chem:Molecule_0008 is both "Adiponitrile"
    and "Hexanedinitrile") - the first one wins, as in generate_id. Without that,
    the raw list would end up as an option in ask_user, and since a typed answer
    never matches a list, such a question could not be answered at all.
    """
    name = entity.get("schema:name")
    if isinstance(name, list):
        name = name[0] if name else None
    if name:
        return name
    return generate_name(entity.get("@id", ""))


def short_local_name(entity_id: str) -> str:
    """Return an entity's local name without the "#" and without the scope suffix,
    e.g. "#Stream_0003_ExperimentSpecific_2" -> "Stream_0003".

    Used to keep the IDs of derived entities readable (flowrate, volume and phase
    process variables, for instance), following the same pattern as
    "ActualTemperature_{device type}" on devices.

    A CURIE prefix is dropped just like the "#" ("reaction:ElementaryReaction_0001"
    -> "ElementaryReaction_0001"): the result is built into new IDs, and a colon in
    the middle of a name would produce a second, broken CURIE there.
    """
    local_name = strip_crate_prefix(entity_id)
    if ":" in local_name:
        local_name = local_name.split(":", 1)[-1]
    # Cut at the LAST occurrence, not at the first: a transfer ID carries the scope twice,
    # because it contains the name of its port or interface, which has its scope already
    # ("#Transfer_vessel001_opening_SeriesSpecific_0004_SeriesSpecific"). Cut at the first
    # occurrence, "Transfer_vessel001_opening" was left of it - without the counter that tells
    # the nine transfers at this port apart. All quantities derived from it thus got the same
    # ID, add_entity silently discarded the second, and several transfers pointed at ONE
    # flowrate (16 at one interface).
    cut = max(local_name.rfind("_SeriesSpecific"), local_name.rfind("_ExperimentSpecific"))
    return local_name[:cut] if cut != -1 else local_name


# ---------------------------------------------------------------------------
# Content-based IDs
# ---------------------------------------------------------------------------
# An ID says WHAT an entity is, not WHEN it was made. generate_id above counts up the first
# free number - an entity made earlier in the flow thus shifts every ID behind it and every
# answer key hanging on it. The functions here never count: they build the ID from the name,
# the library ID or the owner, and an ID that exists already is an error (claim_id), not a
# reason for a silent "_2".
#
# The basic rule: the ID and key of an entity depend only on itself and its owner - never on
# what else exists or was made before.
#
# All IDs run through _compose, so that local name and prefix stay apart. The prefix is
# "crate:<crate_identifier>/", set by set_crate_identifier at the very start of the run
# (rule 1.2): a bare "#..." ID resolves against the file it stands in and points at nothing
# from inside a library. Until set_crate_identifier has run, "#" stays - the tools and tests
# that build IDs without a run need no identifier.

CRATE_NAMESPACE_PREFIX = "crate"
CRATE_ID_PREFIX = "#"

# Identifier of a crate: it goes into every IRI, so only characters that mean nothing there.
_CRATE_IDENTIFIER_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def crate_identifier(text) -> str:
    """Validate the short name of a series as a crate identifier and return it in lower case:
    letters, digits, "_" and "-", starting with a letter or digit. Used as answer_type of ask_user,
    so that an invalid name is turned away and asked again rather than ending up in every IRI.
    """
    # Capital letters allowed, but always continued in lower case: the
    # identifier is also a folder name, and Windows/OneDrive do not tell upper from lower case there -
    # PBA_Synthesis and pba_synthesis would be the same folder, but two crates.
    identifier = str(text).strip().lower()
    if not _CRATE_IDENTIFIER_PATTERN.match(identifier):
        raise ValueError(f"{identifier!r} is not a valid crate identifier")
    return identifier


# ask_user names the type in its error message ("Please enter a valid ...").
crate_identifier.__name__ = "crate identifier (letters, digits, '_' and '-', e.g. hydrogenation_rdy_2026_09; stored in lower case)"


def set_crate_identifier(identifier: str) -> str:
    """Make every crate ID from now on "crate:<identifier>/<local name>" and return the prefix.

    Called once, before the first ID of a run is built. The prefix is read at call time by
    _compose and everything built on it, so no module keeps an old copy.
    """
    global CRATE_ID_PREFIX
    CRATE_ID_PREFIX = f"{CRATE_NAMESPACE_PREFIX}:{crate_identifier(identifier)}/"
    return CRATE_ID_PREFIX


def current_crate_identifier() -> str | None:
    """The identifier set by set_crate_identifier, or None while crate IDs are still "#..."."""
    prefix = f"{CRATE_NAMESPACE_PREFIX}:"
    if not CRATE_ID_PREFIX.startswith(prefix):
        return None
    return CRATE_ID_PREFIX[len(prefix):].rstrip("/")


def crate_id(local: str) -> str:
    """ID of a crate entity whose local name is already complete (a context, the ontology
    snapshot, the series) - the same prefix as every other crate ID."""
    return f"{CRATE_ID_PREFIX}{local}"


def strip_crate_prefix(entity_id: str) -> str:
    """The part of a crate ID after its prefix ("crate:x/Stream_A_SeriesSpecific" ->
    "Stream_A_SeriesSpecific"; an old "#..." ID loses its "#"). Other IDs come back unchanged."""
    if entity_id.startswith(CRATE_ID_PREFIX):
        return entity_id[len(CRATE_ID_PREFIX):]
    if entity_id.startswith("#"):
        return entity_id[1:]
    return entity_id


def for_display(text) -> str:
    """Text for a person: every crate ID in it shown as "#<local name>".

    The answer file stores what was typed or chosen as the person saw it. Showing crate IDs
    the way they looked before the prefix existed keeps every stored answer valid, and makes
    the answer file independent of the crate identifier - a second series can reuse it.
    """
    text = str(text)
    if CRATE_ID_PREFIX == "#":
        return text
    return text.replace(CRATE_ID_PREFIX, "#")

# Coarse kinds for named roots - deliberately not the exact class (Stream, LiquidPhase, ...),
# otherwise the ID would change as soon as somebody corrects the class. The prefix prevents a
# material and a phase called "Water" from getting the same ID.
ROOT_KINDS = ("Material", "Phase", "Task", "File")

_SCOPE_SUFFIX = {"hlo:SeriesSpecific": "SeriesSpecific", "hlo:ExperimentSpecific": "ExperimentSpecific"}
_LEVEL_SUFFIX_PATTERN = re.compile(r"_(SeriesSpecific|ExperimentSpecific)(?:_(\d+))?$")
_TRANSLITERATION = {"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss"}


class DuplicateIdError(ValueError):
    """Two entities would get the same ID - almost always two things with the same name."""


def slugify(name: str) -> str:
    """Turn a human name into the name part of an ID: letters, digits, "_", "-" and ".".

    Spaces become "_", umlauts are transliterated (ä -> ae, ß -> ss), other accents dropped
    to their base letter, everything else removed. Case is kept - the ID should read like the
    name - but uniqueness is checked without it (see claim_id). The dot stays so that a file
    keeps its recognisable name ("data_exp1.xlsx").

    "Sample In Vial" -> "Sample_In_Vial", "Wärmeträger 2" -> "Waermetraeger_2"
    """
    text = "".join(_TRANSLITERATION.get(ch, ch) for ch in str(name))
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"\s+", "_", text.strip())
    text = re.sub(r"[^A-Za-z0-9_.-]", "", text)
    text = re.sub(r"_+", "_", text).strip("_-.")
    if not text:
        raise ValueError(f"The name {name!r} leaves nothing usable for an ID - it needs at least one letter or digit.")
    return text


# Separator of EVERY list answer (name lists and choice lists). A semicolon instead of a comma,
# because labels can contain commas themselves ("determines A, B (...)").
LIST_SEPARATOR = ";"


def name_list(text) -> list:
    """Parse a list of names separated by LIST_SEPARATOR - the answer to "which materials/phases/tasks are
    there?" (4.3). Used as answer_type of ask_user, so that an invalid list is turned
    away like an invalid number.

    Names are asked for all at once rather than one per "add another?" round: a running
    number in the question path would hand a newly inserted entity the stored name - and with
    it every answer - of the one that used to sit at that position. A name in a list is the
    entity's own key; one more entity is one more name, nothing shifts.

    Two names that would give the same ID (compared like claim_id: without case, spaces and
    special characters) are an error. An empty answer is an empty list.
    """
    names = [part.strip() for part in str(text).split(LIST_SEPARATOR)]
    names = [name for name in names if name]
    seen = {}
    for name in names:
        slug = slugify(name).lower()
        if slug in seen:
            raise ValueError(f"'{name}' and '{seen[slug]}' would name the same thing")
        seen[slug] = name
    return names


# ask_user names the type in its error message ("Please enter a valid ...").
name_list.__name__ = f"list of distinct names, separated by '{LIST_SEPARATOR}'"


def _level_suffix(scope: str, experiment_number: int) -> str:
    if scope is None:
        if experiment_number is not None:
            raise ValueError("An experiment number without a scope makes no sense.")
        return ""
    if scope not in _SCOPE_SUFFIX:
        raise ValueError(f"Unknown scope {scope!r} - expected one of {sorted(_SCOPE_SUFFIX)}.")
    if scope == "hlo:ExperimentSpecific":
        # Without a number two experiments would have the same ID.
        if experiment_number is None:
            raise ValueError("An experiment-specific ID needs the experiment number.")
        return f"_{_SCOPE_SUFFIX[scope]}_{experiment_number}"
    if experiment_number is not None:
        raise ValueError("A series-specific ID carries no experiment number.")
    return f"_{_SCOPE_SUFFIX[scope]}"


def _compose(local: str, scope: str, experiment_number: int) -> str:
    return f"{CRATE_ID_PREFIX}{local}{_level_suffix(scope, experiment_number)}"


def split_id(entity_id: str):
    """Split an ID into (local name, level, experiment number).

    "#Material_Sample_In_Vial_ExperimentSpecific_2" -> ("Material_Sample_In_Vial", "ExperimentSpecific", 2)
    "#vessel001_SeriesSpecific"                     -> ("vessel001", "SeriesSpecific", None)
    "device:vessel001"                              -> ("vessel001", None, None)

    Only the LAST level suffix is cut: an ID built from an owner that carried its own level
    keeps that one inside the local name (see short_local_name for why that matters).
    """
    if entity_id.startswith(CRATE_ID_PREFIX):
        local = entity_id[len(CRATE_ID_PREFIX):]
    elif entity_id.startswith("#"):
        local = entity_id[1:]
    elif ":" in entity_id:
        # Library CURIE: the prefix is the namespace of the library, not part of the name.
        local = entity_id.split(":", 1)[1]
    else:
        local = entity_id
    match = _LEVEL_SUFFIX_PATTERN.search(local)
    if not match:
        return local, None, None
    number = int(match.group(2)) if match.group(2) else None
    return local[:match.start()], match.group(1), number


def local_name(entity_id: str) -> str:
    """The local name of an ID, without prefix and level: the part other IDs are built from."""
    return split_id(entity_id)[0]


def level_key(entity_id: str) -> str:
    """Local name plus level, WITHOUT the experiment number - the form a task question key is
    built from (5.1): the experiment is already in the question path, the level is not.

    "#Volume_Material_X_Reference_1_ExperimentSpecific_2" -> "Volume_Material_X_Reference_1_ExperimentSpecific"
    """
    local, level, _ = split_id(entity_id)
    if level is None:
        raise ValueError(f"{entity_id!r} carries no level - a task key needs one (5.1).")
    return f"{local}_{level}"


def key_name(entity) -> str:
    """The question-path segment of an entity (section 5): its local name without
    level and without the kind prefix - the path segment already says the kind.

    "#Material_Sample_In_Vial_ExperimentSpecific_1"  -> "Sample_In_Vial"   (material:Sample_In_Vial)
    "#vessel001_Body_SeriesSpecific"                 -> "vessel001_Body"
    frozenset of two phases (an unordered pair)      -> "A+B", sorted, so both orders agree

    Series template and experiment counterpart share it, which is what the question path wants:
    the experiment is already a segment of its own.
    """
    if isinstance(entity, (frozenset, set)):
        return "+".join(sorted(key_name(part) for part in entity))
    local = local_name(entity)
    kind, sep, rest = local.partition("_")
    if sep and kind in ROOT_KINDS and rest:
        return rest
    return local


def make_root_id(kind: str, name: str, scope: str = None, experiment_number: int = None) -> str:
    """ID of a root entity that has a name of its own: a material, a phase, a task, a file.

    make_root_id("Material", "Sample In Vial", "hlo:ExperimentSpecific", 1)
        -> "#Material_Sample_In_Vial_ExperimentSpecific_1"
    """
    if kind not in ROOT_KINDS:
        raise ValueError(f"Unknown root kind {kind!r} - expected one of {ROOT_KINDS}.")
    return _compose(f"{kind}_{slugify(name)}", scope, experiment_number)


def make_library_based_id(library_id: str, scope: str = None, experiment_number: int = None) -> str:
    """ID of an entity that specializes a library entry, named after it (as
    generate_id_from_library_id does, but through _compose).

    make_library_based_id("device:vessel001", "hlo:SeriesSpecific") -> "#vessel001_SeriesSpecific"
    """
    return _compose(_aliased(local_name(library_id)), scope, experiment_number)


def make_specialization_id(series_id: str, experiment_number: int) -> str:
    """ID of the experiment-specific counterpart of a series entity: the same local name,
    one level down - as devices already do ("#vessel001_SeriesSpecific" ->
    "#vessel001_ExperimentSpecific_2").

    make_specialization_id("#Material_Sample_In_Vial_SeriesSpecific", 2)
        -> "#Material_Sample_In_Vial_ExperimentSpecific_2"
    """
    local, level, _ = split_id(series_id)
    if level != "SeriesSpecific":
        raise ValueError(f"{series_id!r} is not a series-specific ID.")
    return _compose(local, "hlo:ExperimentSpecific", experiment_number)


def make_derived_id(role: str, owner_id: str, scope: str = None, experiment_number: int = None) -> str:
    """ID of an entity that exists once per owner - a property of it, its form, its interface.

    The role comes first, as in the IDs the crate already has ("#Mass_SolidPhase_0013_..."):
    make_derived_id("Mass", "#Phase_Sample_Phase_SeriesSpecific", "hlo:SeriesSpecific")
        -> "#Mass_Phase_Sample_Phase_SeriesSpecific"
    """
    return _compose(f"{slugify(role)}_{local_name(owner_id)}", scope, experiment_number)


def make_owned_id(role: str, owner_id: str) -> str:
    """make_derived_id on the owner's own level - for an entity that always lives where its
    owner lives (a device's power input, a file's column, a stream's source):

    make_owned_id("PowerInput", "#reactor001_ExperimentSpecific_2") -> "#PowerInput_reactor001_ExperimentSpecific_2"
    """
    _, level, number = split_id(owner_id)
    scope = f"hlo:{level}" if level else None
    if level == "SeriesSpecific":
        number = None
    return make_derived_id(role, owner_id, scope, number)


def make_member_id(owner_id: str, role: str, index: int, scope: str = None, experiment_number: int = None) -> str:
    """ID of the n-th of several entities of the same role under one owner: the n-th
    evidence or reference of a variable, the n-th transfer of a species at a place, the n-th
    step of a profile.

    The number counts ALWAYS, also for the first one, and only within this owner and role -
    never "only once there is a second" (that would make the ID of the first depend on
    whether a second exists, see the Grundregel above).

    make_member_id("#Volume_Material_Sample_In_Vial_ExperimentSpecific_1", "Reference", 1,
                   "hlo:ExperimentSpecific", 1)
        -> "#Volume_Material_Sample_In_Vial_Reference_1_ExperimentSpecific_1"
    """
    if not isinstance(index, int) or isinstance(index, bool) or index < 1:
        raise ValueError(f"A member index counts from 1, got {index!r}.")
    return _compose(f"{local_name(owner_id)}_{slugify(role)}_{index}", scope, experiment_number)


def claim_id(candidate: str, datagraph: dict, *todo_lists, what: str = None) -> str:
    """Return candidate if no entity uses it yet, otherwise raise DuplicateIdError.

    Compared WITHOUT case: "Sample" and "sample" name the same thing, and two IDs that differ
    only in case are a trap for anyone reading or typing them. "what" names the thing for the
    error message ("the material 'Sample In Vial'"), so that the message says what to change.
    """
    wanted = candidate.lower()
    pools = [datagraph.get("@graph", [])] + [pool for pool in todo_lists if pool]
    for pool in pools:
        for entity in pool:
            existing = entity.get("@id", "")
            if existing.lower() == wanted:
                subject = what or candidate
                raise DuplicateIdError(
                    f"{subject} would get the ID {candidate}, but {existing} exists already. "
                    "Two entities of the same kind need different names (compared without "
                    "case and without spaces or special characters)."
                )
    return candidate


# ---------------------------------------------------------------------------
# Translating IDs (for the comparison of two crates)
# ---------------------------------------------------------------------------
# translate_id extends a mapping of IDs to derived IDs - generator/workflow/compare_crates.py
# needs it for --id-map.


def translate_id(entity_id: str, mapping: dict, _cache={}) -> str:
    """Translate an ID through a map of ROOT IDs - also an ID built from a root's local name.

    An exact entry wins. Otherwise every local name of a mapped root that appears in the ID is
    replaced, but only by roots of the same level and experiment: the derived
    "#Flowrate_Stream_0001_ExperimentSpecific_2" follows "#Stream_0001_ExperimentSpecific_2",
    not the series stream. Used in both directions - old -> new to compare crates
    (generator/workflow/compare_crates.py).
    """
    if entity_id in mapping:
        return mapping[entity_id]
    if not isinstance(entity_id, str) or not entity_id.startswith(CRATE_ID_PREFIX):
        return entity_id
    # Per level ONE regular expression over all local names (longest first), rebuilt as soon as
    # the mapping has grown.
    key = id(mapping)
    cached = _cache.get(key)
    if cached is None or cached[2] is not mapping or cached[0] != len(mapping):
        by_level = {}
        for source, target in mapping.items():
            source_local, level, number = split_id(source)
            by_level.setdefault((level, number), {})[source_local] = split_id(target)[0]
        patterns = {
            level_key_: (re.compile("(?<![A-Za-z0-9])(" + "|".join(
                re.escape(local) for local in sorted(locals_, key=len, reverse=True)) + ")(?![A-Za-z0-9])"), locals_)
            for level_key_, locals_ in by_level.items()
        }
        cached = (len(mapping), patterns, mapping)
        _cache[key] = cached
    local, level, number = split_id(entity_id)
    entry = cached[1].get((level, number))
    if entry is None and level == "SeriesSpecific" and number is not None:
        # The times of a series task carry an experiment number that means nothing on the series
        # level ("#PlanningTask_0001_StartTime_SeriesSpecific_1") - their owner is the series task
        # without a number.
        entry = cached[1].get((level, None))
    if entry is None:
        return entity_id
    pattern, locals_ = entry
    renamed = pattern.sub(lambda match: locals_[match.group(1)], local)
    if renamed == local:
        return entity_id
    return CRATE_ID_PREFIX + renamed + entity_id[len(CRATE_ID_PREFIX) + len(local):]
