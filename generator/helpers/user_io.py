import os
from contextlib import contextmanager
from pathlib import Path

from helpers.safe_write import write_in_place
from helpers.identifiers import LIST_SEPARATOR, for_display


# ---------------------------------------------------------------------------
# Answer file with stable keys
# ---------------------------------------------------------------------------
# Allows a sequence of answers to be played back from a file instead of answering
# every question by hand in the terminal - switched on through the environment
# variable ANSWER_FILE (path to the answer file).
#
# Unlike before (a positional queue, see the Git history) every answer is stored
# under a STABLE KEY, made up of the "question path" (WHERE in the flow the
# question is asked, see question_path() below) and a "question_id" (WHICH
# question at this place, see ask_user()):
#
#     series:1/experiment:2/material:Material_In_Vessel/phase:LiquidVessel_Phase/temperature
#     series:1/task:for-Mass_Phase_RDY_Phase_Evidence_1_ExperimentSpecific/name
#
# A newly inserted question thus costs only its own key, not the whole rest of
# the file (that was the problem of the old format).
#
# The path holds the NAMES of the entities (helpers/identifiers.py: key_name), not running
# numbers - "material:Sample_In_Vial", not "material:14". A key thus depends only on the thing
# itself: an entity that comes in earlier in the flow shifts nothing (rule 1.1).
#
# Every key starts with a scope segment: "fixed" (hlo:Fixed questions, e.g. the
# choice from the Reaction Library), "series" (hlo:SeriesSpecific AND, as a nested
# "experiment:N" segment below it, hlo:ExperimentSpecific questions - see
# question_path(reset=True) for the switch to "fixed") or "setup" (the questions at
# the very start, before the scope is settled at all: short name and "How many
# experiments?", see main.py).
#
# By decision of the project a crate contains exactly one ExperimentalSeries
# (several series -> several crates) - so the segment is always exactly
# "series:1", never a counter over several series.
#
# ---------------------------------------------------------------------------
# File format (text, no library IDs in the key)
# ---------------------------------------------------------------------------
# The first non-empty line of the file is always FORMAT_HEADER (see below) - if
# it is missing, the reader stops with a clear error message (protects against
# reading an old, position-based answer file by mistake). After it, separated by
# one empty line each, one entry per key:
#
#     key: series:1/experiment:2/phase:3/temperature
#         // [hlo:ExperimentSpecific] Which temperature does Phase X have? [in degC]
#     293.15
#
# The "    // " comment line(s) right after the key line are not just decoration:
# when reading, the question text is compared with the CURRENT question text; if
# it differs (the question was reworded), there is a warning, but the stored
# answer is used all the same.
#
# Escape rule: ONLY a line that starts WITHOUT leading spaces with "key:" starts a
# new entry; only a line that starts WITHOUT leading spaces with "//" would be a
# comment outside an entry. Within an entry the answer line is simply "the first
# line after the (indented) comment lines" - it is NOT searched by its content, but
# recognized purely by its position in the entry block (separated by empty lines).
# If an answer happens to start with "    // " or "key:" itself, _save() puts a
# single space in front of it (and _load() removes it again when reading) - that is
# the only case that needs special treatment at all.
#
# An empty answer is stored as EMPTY_ANSWER_MARKER ("<empty>") (otherwise the
# answer line would be empty and would be mistaken for the end of the block).
#
# Origin (rule 2.10): below the question line a second comment line
# can stand that says where the answer comes from:
#
#     key: series:1/devices
#         // Which devices from the Device Library were used? [...]
#         // source: D: setup sheet amidation_ai4green_ai4_001_setup.yaml, devices
#     flask_50mL_01; glass_vial_20mL; balance001
#
# Codes: E (ELN, structured), X (extracted from free text), R (fixed translation rule),
# L (looked up), C (curated), D (invented for the demonstration), M (missing). It is
# written by an answer provider (set_answer_provider, e.g. interfaces/eln/adapter.py);
# without it the answer counts as unknown. It stays as long as the answer stays the
# same, even when the question line is rewritten (_record_answer).
#
# ---------------------------------------------------------------------------
# Behaviour when reading
# ---------------------------------------------------------------------------
# - Key present, answer (still) valid -> use it, do not ask.
# - Key present, answer no longer valid (e.g. the list of options has changed) ->
#   warn, discard, ask interactively once, overwrite the entry WITH the new answer.
# - Key missing -> ask interactively, a new entry is appended.
#   The rest of the file stays usable untouched - that is the actual purpose of
#   this change.
# - Key present but never asked in this run -> reported as info at the end via
#   report_unused_answer_keys(), NOT deleted (can be legitimate, e.g. when an "add
#   another?" loop was shorter this time).
# - STRICT_ANSWERS=1 (environment variable): a missing OR invalid key stops the
#   run instead of asking interactively - for automated/CI runs.
#
# Safety net against a forgotten question_path() nesting: if the same key is made
# twice in the same run, ask_user() stops at once with a clear error message,
# instead of silently overwriting an answer (see _seen_keys below).
# ---------------------------------------------------------------------------

ANSWER_FILE_FORMAT_VERSION = "keyed-v2"
FORMAT_HEADER = f"# answer-file-format: {ANSWER_FILE_FORMAT_VERSION}"
COMMENT_PREFIX = "    // "
SOURCE_PREFIX = COMMENT_PREFIX + "source: "

# The answers to the questions "the same for all experiments?" (8). "Not known yet" behaves
# like "No" in the run; when the series is completed it is decided whether the statement
# belongs at the series.
SAME_OPTIONS = ["Yes", "No", "Not known yet"]
EMPTY_ANSWER_MARKER = "<empty>"

STRICT_ANSWERS = os.environ.get("STRICT_ANSWERS", "").strip().lower() not in ("", "0", "false")


def _normalize_for_matching(value) -> str:
    """Ignore case and spaces when matching an answer against an option, so that
    typing "Laura Fadler" matches the library ID "person:LauraFadler" (shown as
    "LauraFadler") without having to leave the space out."""
    return str(value).lower().replace(" ", "")


# ---------------------------------------------------------------------------
# Question path
# ---------------------------------------------------------------------------

_question_path_stack = []


@contextmanager
def question_path(level: str, nr=None, reset: bool = False, under: tuple = None):
    """Push a segment onto the current question path on entry and pop it again on exit
    (also on an exception, thanks to @contextmanager/finally) - see the module
    docstring above.

    "level" is the name of the level ("phase", "species", "experiment", ...).
    "nr" says which one: the name of the entity (helpers/identifiers.py: key_name) wherever
    there is one, a running number only for a genuine repetition that has nothing else to go
    by (the n-th answer of an "add another?" loop). None for pure scope markers that carry
    no count of their own, e.g. question_path("fixed").
    "reset=True" discards the question path so far and starts afresh at this point -
    for hlo:Fixed questions (see creation/reaction_functions.py), which do NOT hang
    under "series:1" even though they sit in the middle of the otherwise
    "series:1"-wide order of main.py.
    "under" names levels (e.g. ("series", "experiment")): the segment is then put directly
    below the LAST of them in the current path, dropping what lies in between - for an entity
    that is reached through several owners but belongs to none of them, like an elementary
    reaction shared by two mechanisms (creation/reaction_functions.py). Its questions then
    stand in one place, whichever owner reaches it first.
    """
    global _question_path_stack
    segment = level if nr is None else f"{level}:{nr}"
    saved_stack = _question_path_stack
    if reset:
        _question_path_stack = [segment]
    elif under:
        cut = max((i + 1 for i, part in enumerate(saved_stack) if part.split(":", 1)[0] in under), default=0)
        _question_path_stack = saved_stack[:cut] + [segment]
    else:
        _question_path_stack = saved_stack + [segment]
    try:
        yield
    finally:
        _question_path_stack = saved_stack
        for hook in _path_exit_hooks:
            hook(tuple(_question_path_stack))


# Whoever needs to know when a path is left hooks in here - today
# helpers/value_sources.py, which asks the evidence/reference lists of an exemplar as soon
# as its path is left. A hook instead of an import: value_sources needs ask_user itself,
# an import in both directions would be circular.
_path_exit_hooks = []


def current_question_path() -> tuple:
    """The question path as it stands, to come back to it later (at_question_path)."""
    return tuple(_question_path_stack)


@contextmanager
def at_question_path(path: tuple):
    """Put the question path back to a recorded state for the duration of the block - so that
    questions asked later are keyed exactly as if they had been asked there and then."""
    global _question_path_stack
    saved_stack = _question_path_stack
    _question_path_stack = list(path)
    try:
        yield
    finally:
        _question_path_stack = saved_stack


def _current_path_prefix() -> str:
    return "/".join(_question_path_stack)


# ---------------------------------------------------------------------------
# Answer file: loading/saving
# ---------------------------------------------------------------------------

# An answer file of an old format kept the running numbers of the path in an "index:" block
# before the answers. With names in the path there is nothing to keep; such a file is refused
# (it would have to be migrated, rule 8.2).
_OLD_INDEX_PREFIX = "index:"

_answer_path = None
_answer_entries = None   # key -> {"comments": [str, ...], "answer": str}
_answer_order = None     # order in which entries are written
_seen_keys = set()       # keys made already in this run (protection against duplicates)


def _load_answer_file():
    global _answer_entries, _answer_order, _answer_path
    if _answer_entries is not None:
        return
    _answer_entries = {}
    _answer_order = []

    answer_file = os.environ.get("ANSWER_FILE")
    _answer_path = Path(answer_file) if answer_file else None
    if _answer_path is None or not _answer_path.exists():
        return

    text = _answer_path.read_text(encoding="utf-8")
    if text.strip() == "":
        return

    lines = text.splitlines()
    idx = 0
    while idx < len(lines) and lines[idx].strip() == "":
        idx += 1
    if idx >= len(lines) or lines[idx] != FORMAT_HEADER:
        raise ValueError(
            f"Answer file '{_answer_path}' does not start with '{FORMAT_HEADER}' - it is of an older "
            "format and cannot be read (see the module docstring in helpers/user_io.py)."
        )
    idx += 1

    while idx < len(lines):
        while idx < len(lines) and lines[idx].strip() == "":
            idx += 1
        if idx >= len(lines):
            break

        line = lines[idx]
        if line.startswith(_OLD_INDEX_PREFIX):
            raise ValueError(f"Answer file '{_answer_path}' still holds an 'index:' line of an older format "
                             "and cannot be read (see the module docstring in helpers/user_io.py).")
        if not line.startswith("key:"):
            raise ValueError(f"Answer file '{_answer_path}': expected a 'key: ...' line, got: {line!r}")
        key = line[len("key:"):].strip()
        idx += 1

        comments = []
        while idx < len(lines) and lines[idx].startswith(COMMENT_PREFIX):
            comments.append(lines[idx])
            idx += 1

        if idx >= len(lines) or lines[idx].strip() == "":
            raise ValueError(f"Answer file '{_answer_path}': key '{key}' has no answer line.")
        answer_line = lines[idx]
        if answer_line.startswith(" ") and (answer_line[1:].startswith(COMMENT_PREFIX) or answer_line[1:].startswith("key:")):
            answer_line = answer_line[1:]
        idx += 1

        answer = "" if answer_line.strip() == EMPTY_ANSWER_MARKER else answer_line
        if key in _answer_entries:
            raise ValueError(f"Answer file '{_answer_path}': duplicate key '{key}'.")
        _answer_entries[key] = {"comments": comments, "answer": answer}
        _answer_order.append(key)


def option_label(option) -> str:
    """How an option is shown and matched: a crate ID as "#<local name>" (see
    helpers/identifiers.py: for_display), any other compact IRI without its prefix.
    Only a prefix of the project's prefix table counts, so a name with a colon
    ("Assumption: sample volume") is shown in full."""
    # Imported only here: helpers.file_handling in turn imports this module via
    # helpers.entities.
    from helpers.file_handling import PROJECT_CONTEXT

    text = for_display(option)
    prefix, separator, local_name = text.partition(":")
    if separator and prefix in PROJECT_CONTEXT:
        return local_name
    return text


def _format_question_text(prompt: str, options) -> str:
    if options:
        options_display = [option_label(o) for o in options]
        return f"{prompt} [{', '.join(str(o) for o in options_display)}]"
    return prompt


def _format_comment_lines(prompt: str, options) -> list:
    return [f"{COMMENT_PREFIX}{_format_question_text(prompt, options)}"]


def _save_answer_file():
    if _answer_path is None:
        return
    lines = [FORMAT_HEADER, ""]
    for key in _answer_order:
        entry = _answer_entries[key]
        lines.append(f"key: {key}")
        lines.extend(entry["comments"])
        answer_line = entry["answer"] if entry["answer"] != "" else EMPTY_ANSWER_MARKER
        if answer_line.startswith(COMMENT_PREFIX) or answer_line.startswith("key:"):
            answer_line = " " + answer_line
        lines.append(answer_line)
        lines.append("")
    # Written after every answer, in the OneDrive folder of the project - in place, with retries
    # (helpers/safe_write.py says why not through a .tmp file).
    write_in_place(_answer_path, "\n".join(lines).rstrip("\n") + "\n")


def _record_answer(key: str, prompt: str, options, answer: str, source: str = None):
    """Write an answer under its key, with the current question text and, if known, where the
    answer comes from ("<code>: <text>", see the module docstring). Without a new source, the
    source line of the stored entry is kept as long as the answer itself is the same - it would
    otherwise be lost whenever only the question text is brought up to date."""
    previous = _answer_entries.get(key)
    if source:
        source_lines = [f"{SOURCE_PREFIX}{source}"]
    elif previous is not None and previous["answer"] == answer:
        source_lines = [line for line in previous["comments"] if line.startswith(SOURCE_PREFIX)]
    else:
        source_lines = []
    _answer_entries[key] = {"comments": _format_comment_lines(prompt, options) + source_lines, "answer": answer}
    if key not in _answer_order:
        _answer_order.append(key)
    _save_answer_file()


def unused_answer_keys() -> list:
    """Keys in the answer file that were not asked in this run (so far), in file order."""
    _load_answer_file()
    return [k for k in _answer_order if k not in _seen_keys]


def report_unused_answer_keys():
    """Call at the end of a run (see main.py): reports keys that are in the answer file
    but were never asked during this run. Information only, not an error (see the module
    docstring, "Behaviour when reading")."""
    unused = unused_answer_keys()
    if unused:
        print(f"\n[answer file] {len(unused)} key(s) in the answer file were not asked in this run:")
        for k in unused:
            print(f"    {k}")


# ---------------------------------------------------------------------------
# ask_user
# ---------------------------------------------------------------------------

def _match_option(raw: str, options):
    """The option an answer stands for - by its label or its full value. An answer that fits more than one
    option (the same local name in two vocabularies, hlo:X and cpo:X) stops the run instead of quietly taking
    the first."""
    options_display = [option_label(o) for o in options]
    hits = [option for option, display in zip(options, options_display)
            if _normalize_for_matching(raw) in (_normalize_for_matching(display), _normalize_for_matching(option))]
    distinct = list(dict.fromkeys(str(h) for h in hits))
    if len(distinct) > 1:
        raise RuntimeError(f"The answer '{raw}' fits more than one option ({', '.join(distinct)}) - "
                           "write the full value (with its prefix) to say which.")
    return hits[0] if hits else None


def _logged_option(raw: str, options) -> str:
    """How a chosen option is written into the answer file: its full value (hlo:Observed, unit:MIN) when it is
    a term of a vocabulary - the file is a log and should be clear without the option list. A crate
    ID stays as shown (#Task_...), so that the answer file does not depend on the crate's identifier (rule 1.3);
    anything else as given."""
    matched = _match_option(raw, options) if options else None
    if not isinstance(matched, str):
        return raw
    label = option_label(matched)
    if label != matched and not for_display(matched).startswith("#"):
        return matched
    return raw


def _logged_answer(raw: str, options, answer_type) -> str:
    """The answer as the answer file keeps it - a single choice, or each part of a list of choices."""
    if options:
        return _logged_option(raw, options)
    list_options = getattr(answer_type, "list_options", None)
    if list_options and str(raw).strip():
        return f"{LIST_SEPARATOR} ".join(_logged_option(part.strip(), list_options)
                                         for part in str(raw).split(LIST_SEPARATOR) if part.strip())
    return raw


def _try_convert(raw: str, answer_type):
    if answer_type is None:
        return True, raw
    try:
        return True, answer_type(raw)
    except (TypeError, ValueError):
        return False, None



def _is_empty_answer(value, required: bool) -> bool:
    """Whether a required answer was left empty (makes sense only for open questions)."""
    return required and isinstance(value, str) and not value.strip()


# ---------------------------------------------------------------------------
# Answer provider: who supplies a missing answer when the file does not have it
# ---------------------------------------------------------------------------
# By default nobody - then the question is asked in the terminal as always. Tools (see
# generator/workflow/answer_driver.py) hook a function in here, instead of overwriting
# ask_user in every module that imported it. The same place is where a UI or an ELN
# import can supply answers later: they all write the same keys.

_answer_provider = None


def known_answer(key: str):
    """The answer a question with this key would get without anyone typing it - from the answer file,
    else from the answer provider (the setup sheet, interfaces/eln/adapter.py) -, as text, or None.
    Records nothing and asks nothing: the question itself is asked later as usual, where it belongs.
    For reading a value ahead that is needed earlier than its question (the start of an experiment
    when a device has held several contents, rule 2.15). Only for questions without options."""
    _load_answer_file()
    stored = (_answer_entries or {}).get(key)
    if stored is not None and stored["answer"].strip():
        return stored["answer"].strip()
    if _answer_provider is not None:
        try:
            provided = _answer_provider(key=key, prompt="", options=None, answer_type=None, required=False, stored=None)
        except RuntimeError:
            # A provider in abort mode (workflow/answer_driver.py) stops on a key it cannot answer - when only
            # reading ahead, that just means no answer (tests/content_history_test.py).
            return None
        if isinstance(provided, tuple):
            provided = provided[0]
        if provided not in (None, ""):
            return str(provided).strip()
    return None


def set_answer_provider(provider):
    """Register a function that supplies an answer before the terminal is asked, or None to
    remove it again.

    It is called as provider(key=..., prompt=..., options=..., answer_type=...,
    required=..., stored=...) whenever the answer file has no usable answer for a key -
    "stored" is the discarded answer when there was an invalid one, otherwise None. It
    returns the raw answer text, or None to fall through to the terminal - or a pair
    (answer text, source), where source says where the answer comes from ("E: ELN AI4Green
    AI4-001, people[0]"; rule 2.10) and is written into the answer file. An answer it
    returns goes through the same checks as a typed one; if it does not pass them the run
    stops, because asking the provider again would only return the same thing.
    """
    global _answer_provider
    _answer_provider = provider


def _validated(raw: str, options, answer_type, required: bool):
    """(ok, value, problem) for a raw answer - the same checks as for a typed answer."""
    if options:
        matched = _match_option(raw, options)
        if matched is None:
            return False, None, f"'{raw}' is not one of the options"
        return True, matched, None
    ok, converted = _try_convert(raw, answer_type)
    if not ok:
        return False, None, f"'{raw}' is not a valid {answer_type.__name__ if answer_type else 'value'}"
    if _is_empty_answer(converted, required):
        return False, None, "an empty answer is not allowed for this question"
    return True, converted, None



def match_option(raw: str, options):
    """The option a typed answer stands for, or None - the same matching every choice uses."""
    return _match_option(raw, options)


def ask_user_list(prompt, options, *, question_id, required=False) -> list:
    """Ask for several of the options at once, as one list - instead of an "another one?"
    loop with a running number in the question path (step 7, group C).

    The answer names the chosen options separated by LIST_SEPARATOR, each matched like a
    single choice (_match_option). Returns the chosen options in the order given; an empty
    answer is an empty list, unless required. An option named twice, or something that is
    not an option, turns the answer away like an invalid number.
    """
    def parse(text):
        chosen = []
        for part in str(text).split(LIST_SEPARATOR):
            part = part.strip()
            if not part:
                continue
            matched = _match_option(part, options)
            if matched is None:
                raise ValueError(f"'{part}' is not one of the options")
            if matched in chosen:
                raise ValueError(f"'{part}' is named twice")
            chosen.append(matched)
        if required and not chosen:
            raise ValueError("at least one has to be named")
        return chosen

    parse.__name__ = f"list of the options, separated by '{LIST_SEPARATOR}'"
    # For tools that answer without input: which options there are and whether the list may stay empty.
    parse.list_options, parse.list_required = options, required
    shown = ", ".join(option_label(o) for o in options)
    hint = f"several separated by '{LIST_SEPARATOR}'" + ("" if required else ", leave empty for none")
    return ask_user(f"{prompt} [{shown}] ({hint})", answer_type=parse, question_id=question_id)


def ask_user(prompt, options=None, answer_type=None, *, question_id, required=False):
    """Ask the user for an input.

    For a multiple-choice question "options" has to be set; otherwise the question is
    open (with an optional answer_type, int for "how many ..." questions for example).

    required=True rejects an empty answer on an open question: the question is asked again
    until something is entered, and a stored empty answer is discarded the same way an
    invalid one is. Used where a value only makes sense WITH the text - an assumption
    without a reason, for instance (see creation/task_functions.py: create_task). It has no
    effect on a multiple-choice question, where an answer always comes out of the list.

    "question_id" is MANDATORY (keyword-only, no default) - a short identifier of this
    call site, unique within its question path (see the module docstring). A call site
    without a question_id should fail immediately with a TypeError rather than quietly
    produce a broken key: with over 150 call sites that is the only guarantee that none
    is forgotten.

    Instead of being typed in, answers can be read from a file (see ANSWER_FILE at the
    top of this module). Every answer actually used is recorded in that file under its
    key (written or overwritten), no matter whether it came from the file or was just
    typed in.
    """
    if not question_id:
        raise ValueError("ask_user() requires a non-empty question_id keyword argument.")
    if not _question_path_stack:
        raise RuntimeError(
            f"ask_user(question_id={question_id!r}) has no active question_path - every "
            "question needs a scope segment (see question_path() in helpers/user_io.py)."
        )

    key = f"{_current_path_prefix()}/{question_id}"
    if key in _seen_keys:
        raise RuntimeError(
            f"Question key '{key}' was about to be asked a second time in this run - a "
            "repeatable ask_user() call site is missing its own question_path() segment "
            "(see helpers/user_io.py)."
        )
    _seen_keys.add(key)

    # Show crate IDs in the question text as in the options (see option_label) - otherwise
    # the identifier would stand in every comment line of the answer file.
    prompt = for_display(prompt)

    _load_answer_file()
    options_display_string = None
    if options:
        options_display = [option_label(o) for o in options]
        options_display_string = ", ".join(str(o) for o in options_display)

    stored = _answer_entries.get(key)
    if stored is not None:
        current_comments = _format_comment_lines(prompt, options)
        if stored["comments"][:1] != current_comments[:1]:
            # Comment lines are optional (see _load_answer_file) - an answer entered by hand often
            # has none at all.
            previous = stored["comments"][0].strip() if stored["comments"] else "(no question text recorded)"
            print(
                f"[answer file] Question text for key '{key}' has changed since this answer "
                f"was recorded - using the stored answer anyway.\n"
                f"    then: {previous}\n"
                f"    now:  {current_comments[0].strip()}"
            )
        raw = stored["answer"]
        if options:
            matched = _match_option(raw, options)
            if matched is not None:
                # The stored answer still fits - so bring the comment line up to the current question
                # text, instead of giving the warning above again in every run. The hint thus comes
                # exactly once, after that the file says what was really asked. Without that a
                # sensible warning becomes noise: switching the choice lists to the ontology sorted the
                # options alphabetically and so changed over 1200 question texts, without a single
                # answer changing.
                if stored["comments"][:1] != current_comments[:1]:
                    _record_answer(key, prompt, options, raw)
                print(f"{prompt} [{options_display_string}]: {raw}   <- from answer file [{key}]")
                return matched
            problem = f"'{raw}' is not one of [{options_display_string}]"
        else:
            ok, converted = _try_convert(raw, answer_type)
            if ok and _is_empty_answer(converted, required):
                ok, problem = False, "an empty answer is not allowed for this question"
            elif ok:
                # As in the options branch above: update the comment line, so that the hint does not
                # come back in every run. Mostly concerns answers entered by hand, which have no
                # comment line at all yet.
                if stored["comments"][:1] != current_comments[:1]:
                    _record_answer(key, prompt, options, raw)
                print(f"{prompt}: {raw}   <- from answer file [{key}]")
                return converted
            else:
                problem = f"'{raw}' is not a valid {answer_type.__name__ if answer_type else 'value'}"

        if STRICT_ANSWERS:
            raise RuntimeError(f"[--strict] Stored answer for key '{key}' is invalid ({problem}) - aborting.")
        print(f"[answer file] {problem} for key '{key}' ({prompt}) - discarding it and asking again.")

    elif STRICT_ANSWERS:
        raise RuntimeError(f"[--strict] No stored answer for key '{key}' ({prompt}) and STRICT_ANSWERS is set - aborting.")

    if _answer_provider is not None:
        provided = _answer_provider(key=key, prompt=prompt, options=options, answer_type=answer_type,
                                    required=required, stored=stored["answer"] if stored is not None else None)
        source = None
        if isinstance(provided, tuple):
            provided, source = provided
        if provided is not None:
            ok, value, problem = _validated(provided, options, answer_type, required)
            if not ok:
                raise RuntimeError(f"[answer provider] {problem} for key '{key}' ({prompt}) - aborting.")
            _record_answer(key, prompt, options, _logged_answer(provided, options, answer_type), source)
            print(f"{prompt}: {provided}   <- from answer provider [{key}]")
            return value

    if options:
        while True:
            raw = input(f"{prompt} [{options_display_string}]: ").strip()
            matched = _match_option(raw, options)
            if matched is not None:
                _record_answer(key, prompt, options, _logged_answer(raw, options, answer_type))
                return matched
            print(f"Please choose one of the following options: {options_display_string}")
    else:
        while True:
            raw = input(f"{prompt}: ").strip()
            ok, converted = _try_convert(raw, answer_type)
            if ok and _is_empty_answer(converted, required):
                print("This question has to be answered - please enter something.")
                continue
            if ok:
                _record_answer(key, prompt, options, _logged_answer(raw, options, answer_type))
                return converted
            print(f"Please enter a valid {answer_type.__name__}.")
