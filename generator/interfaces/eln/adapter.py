"""
The adapter: answers the generator's questions from a setup sheet and the ELN core files it names.
It is the only part that knows the answer
keys - the core file says what the ELN says, the setup sheet what a person knows about the setup,
both in the terms of chemistry.

    ELN (.eln) -> reader + profile -> core file --+
                                                  +--> adapter --> answer keys --> generator
    person --------------------------> setup sheet +        nothing to say --> the generator asks

Every answer carries its source, "<code>: <text>" (rule 2.10: E ELN structured, X extracted from
free text, R fixed translation rule, L looked up, C curated, D invented for the demonstration,
M missing). An R answer names its rule of the table RULES below ("R: A6 - ..."); the table is
written out in interfaces/eln/README.md. A question the adapter has nothing for returns None and is
asked by the generator - nothing is inferred (rule 2.9): a temperature without a unit stays without one.

Used as an answer provider (helpers/user_io.py: set_answer_provider), normally through
    workflow/answer_driver.py --setup projects/<crate_identifier>/setup.yaml
Print the rules with (from generator/)
    python -m interfaces.eln.adapter --rules
"""
import json
import re
from pathlib import Path

import yaml

from interfaces.eln.sheet_names import (READABLE_TRANSFER, experiments_of, id_forms_of_place, interface_forms,
                                        place_matches, transfer_matches)

SHEET_FORMAT = "setup-sheet-v1"

# The fixed translation rules of the adapter (code R). Every R answer names its number; the
# table stands with the same wording in interfaces/eln/README.md (rule 2.10: it can be traced where a
# value comes from). A rule may only say what follows from the matter itself - nothing one merely
# supposes. A new rule gets the next free number, a withdrawn one stays as a gap
# (withdrawn: A2, A4, A5, A6, A7, A10, A11, A13 - see the README).
RULES = {
    "A1": "An ELN record becomes an experiment of the series; how many experiments the series has, "
          "the setup sheet says.",
    "A3": "In a series with one experiment, everything is the same in all experiments.",
    "A8": "Unit symbols of the ELN are written as QUDT units (mg -> MilliGM, mmol -> MilliMOL, "
          "mL -> MilliL, g -> GM); a percentage is passed on as '<number> %', which the generator "
          "stores as a fraction. Without a symbol there is no unit.",
    "A9": "A number taken from the ELN is a new value (not one that exists in the crate already) and "
          "a single scalar process variable (not a time series).",
    "A12": "A result of an ELN record (yield, selectivity) belongs to the reaction participant it names "
           "('of'); a result that names no substance is left out.",
    "A14": "A substance the setup sheet does not name under species_per_experiment occurs in every experiment "
           "in which its phases occur - the species lists of the sheet hold for the whole series.",
    "A15": "The content of a container or a supply line of the libraries is described by the Material Library: its "
           "phases hold no species beyond the ones entered there.",
}

# The tasks the generator creates itself stand in the key under their short ID
# (Task_procedure -> task:procedure), in the sheet under their name.
BUILT_IN_TASKS = {"procedure": "Experimental procedure", "planning": "Planning the series",
                  "establishing": "Establishing the values", "preparation": "Preparation",
                  "main_operation": "Main operation", "workup": "Work-up"}

STATES = ("solid", "liquid", "gaseous")
_STATE_ALIASES = {"gas": "gaseous"}

GATE_QUESTIONS = ("quantities_with_evidence", "quantities_with_reference", "quantities_known_per_experiment")

# The place of a value in the key: every path of "level:name" - material, phase, substance, device,
# reaction and participant, but also what the generator derives (room air, wall material, interface,
# transfer). Not the tasks: their times stand in the sheet under "times". Before it the level (experiment
# or - without - the series). The transfers the generator adds for substances that came in later are asked
# under "transfer_follow_up/" - the place is the same as for every other transfer, the segment is not
# part of it.
VALUE_PATH = r"(?:transfer_follow_up/)?(?P<path>(?!experiment:|task:)[a-z_]+:[^/]+(?:/(?!task:)[a-z_]+:[^/]+)*)"
LEVEL = r"series:1/(?:experiment:(?P<exp>\d+)/)?"
# The lists "for which quantities ..." at a place and the questions about a value (for the scaffold of
# values in workflow/open_questions.py).
VALUE_LIST_KEY = re.compile(LEVEL + VALUE_PATH + r"/quantities_(?:with_(?:evidence|reference)|known_per_experiment)")
VALUE_FIELD_KEY = re.compile(LEVEL + VALUE_PATH + r"/(?P<quantity>[a-z_]+)/(?:(?:evidence|reference):\d+/)?"
                             r"(?:(?:evidence|reference)_[a-z_]+|have_another_(?:evidence|reference))")
# The concentration of a species is asked without a segment of its own, directly at the species
# (creation/phase_functions.py: _add_species_concentration) - its questions are those of the quantity
# "concentration" of the sheet's values.
SPECIES_PATH = r"(?:transfer_follow_up/)?(?P<path>(?!experiment:|task:)(?:[a-z_]+:[^/]+/)*species:[^/]+)"
SPECIES_CONCENTRATION_KEY = re.compile(LEVEL + SPECIES_PATH + r"/(?:(?:evidence|reference):\d+/)?"
                                       r"(?:(?:evidence|reference)_[a-z_]+|have_another_(?:evidence|reference))")
# The questions about a time value (of a task or of an occurrence): point in time or duration, a second value.
TIME_QUANTITIES = ("start_time", "end_time", "duration", "start_offset")
TIME_FIELD = (r"(?P<quantity>start_time|end_time|duration|start_offset)/(?:(?:evidence|reference):(?P<idx>\d+)/)?"
              r"(?P<role>evidence|reference)_(?P<field>exists|value_type|exactness|timestamp|lower_bound|upper_bound|"
              r"duration_value|duration_unit|type|source)")
TIME_ANOTHER = (r"(?P<quantity>start_time|end_time|duration|start_offset)/(?P<role>evidence|reference):(?P<idx>\d+)/"
                r"have_another_(?:evidence|reference)")
# The occurrences of an experiment (creation/occurrence_functions.py): one list per kind, transfers by place;
# a thing is a phase, an interface, a reaction, an energy field or a transfer at a place.
OCCURRENCES = r"series:1/experiment:(?P<exp>\d+)/occurrences/"
THING = (r"(?:(?P<simple>phase|interface|reaction|energy_field):(?P<label>[^/]+)"
         r"|place:(?P<place>[^/]+)/transfer:(?P<transfer>[^/]+))")
# Field in the section "occurrences" -> kind of the thing (as in creation/occurrence_functions.py: _kind).
OCCURRENCE_FIELDS = {"phases": "phase", "interfaces": "interface", "reactions": "reaction",
                     "energy_fields": "energy_field", "transfers": "transfer"}
# Answers that can only say "none" - a question only they hit has no field of its own in the sheet.
NONE_ONLY_HANDLERS = ("_none_list", "_gate", "_no_other_value", "_no_profile")

UNIT_SYMBOLS = {"mg": "MilliGM", "g": "GM", "kg": "KiloGM", "mmol": "MilliMOL", "mol": "MOL",
                "mL": "MilliL", "ml": "MilliL", "L": "L", "%": "PERCENT",
                # Microlitre: "µL" with the micro sign, "μL" with the Greek mu, "uL".
                "µL": "MicroL", "μL": "MicroL", "uL": "MicroL",
                # Chemotion: the temperature in "°C".
                "°C": "DEG_C"}
# Units of a duration (Chemotion "3h"): the times of a task read them as A8 reads the values.
TIME_UNIT_SYMBOLS = {"h": "HR", "min": "MIN", "s": "SEC"}

# Where a value of an ELN record lands in the sheet is in interfaces/eln/sheet_values.py; the
# adapter reads the values only from the section "values" of the sheet.

# The reading of a value (kind): word -> (evidence/reference, type).
_VALUE_KINDS = {
    "measured": ("evidence", "Measured"), "calculated": ("evidence", "Calculated"),
    "observed": ("evidence", "Observed"), "planned": ("reference", "Planned"),
    "assumed": ("reference", "Assumed"), "controlled": ("reference", "Controlled"),
    "set": ("reference", "Set"), "literature": ("reference", "Literature"),
}

# What the sheet can explicitly deny under "none" ("none") - per item the questions that are then
# answered empty (or "No"). If an item is missing, the generator asks: a person may know something
# that just is not in the ELN.
NONE_CATEGORIES = {
    "further_values": "no values beyond those of the ELN record: the lists 'for which quantities ...' "
                      "hold only the ELN's, and no value has a second one",
    "samples": "no material is a sample of another",
    "interfaces": "no further phase interfaces between materials (the contacts to the room air the generator creates "
                  "itself), no occupation states",
    "energy_fields": "no phase generates an energy field, none was measured in the room",
    "air_species": "no further species in the air of the room",
    "occurrences": "nothing known about whether or how often phases, interfaces, transfers, reactions occurred",
    "experiment_tasks": "no task that only occurred in one experiment",
    "profiles": "no set profile of a device, no task executes a profile",
    "task_details": "tasks use no software, aim at nothing, act on nothing, have no input values and "
                    "no description beyond the sheet; a task not in the sheet uses no equipment",
    "emptied": "no task used up or disposed of the content of a container of the inventory",
    "reference_sources": "no document is known for a planned or literature value that does not name one "
                         "(its field 'document')",
}
_NONE_PATTERNS = (
    (r"series:1/sample_materials", "samples"),
    (r"series:1/cross_material_pairs", "interfaces"),
    (r"series:1/phase_interface:[^/]+/occupation_state_names", "interfaces"),
    (r"series:1/.*/energy_field_types", "energy_fields"),
    (r"series:1/environment:[^/]+/measured_ambient_fields", "energy_fields"),
    (r"series:1/environment:[^/]+/phase:[^/]+/species_names", "air_species"),
    (r"series:1/experiment:\d+/occurrences/(phases|interfaces|transfer_places|reactions)", "occurrences"),
    (r"series:1/experiment:\d+/extra_task_names", "experiment_tasks"),
    (r"series:1/.*/(software|aims_at|acts_on|input_values|observed)", "task_details"),
)


def _norm(text) -> str:
    """Compare names without case, spaces and special characters ("Reaction Mixture" =
    "Reaction_Mixture"), as the generator does when it claims an ID."""
    return re.sub(r"[^a-z0-9]", "", str(text).lower())


def _norm_quoted(text) -> str:
    """Like _norm, but keeps the quotes - for an option such as 'SolidPhase "Wood_Phase"'."""
    return re.sub(r'[^a-z0-9"]', "", str(text).lower())


def _as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _exact(number) -> str:
    """A number as text without losing a digit (":g" kept six - 92.49897 became 92.499);
    a whole number without ".0"."""
    if isinstance(number, bool) or not isinstance(number, (int, float)):
        return str(number)
    return str(int(number)) if float(number).is_integer() else repr(float(number))


def rule(number: str) -> str:
    """The source of an answer given by a rule of RULES: "R: A6 - <text>"."""
    return f"R: {number} - {RULES[number]}"


def _experiment_of_key(key: str):
    """The experiment a question key names (series:1/experiment:2/...), or None for a key of the series."""
    match = re.match(r"series:1/experiment:(\d+)/", str(key))
    return int(match.group(1)) if match else None


class SetupAdapter:
    """Answer provider built from one setup sheet. Call it like the provider of
    helpers/user_io.py; it returns (answer, source) or None."""

    def __init__(self, sheet_path: Path, project_root: Path):
        self.sheet_path = Path(sheet_path)
        self.project_root = Path(project_root)
        sheet = yaml.safe_load(self.sheet_path.read_text(encoding="utf-8"))
        if not isinstance(sheet, dict) or sheet.get("format") != SHEET_FORMAT:
            raise ValueError(f"{self.sheet_path}: not a setup sheet of format '{SHEET_FORMAT}' "
                             f"(first line 'format: {SHEET_FORMAT}').")
        self.sheet = sheet
        self.sheet_name = self.sheet_path.name
        self.default_source = sheet.get("source") or f"D: setup sheet {self.sheet_name}"

        self.series = sheet.get("series") or {}
        self.people = sheet.get("people") or {}
        for entry in _as_list(sheet.get("values")):
            word = entry.get("kind")
            if word not in (None, "") and str(word).lower() not in _VALUE_KINDS and str(word).lower() != "none":
                raise ValueError(f"{self.sheet_name}: value {entry.get('at')}/{entry.get('quantity')}: kind = {word!r}, "
                                 "expected one of " + ", ".join(_VALUE_KINDS) + " (or empty: not known)")
        none = sheet.get("none") or {}
        self.none = set(_as_list(none.get("categories")))
        unknown = self.none - set(NONE_CATEGORIES)
        if unknown:
            raise ValueError(f"{self.sheet_name}: none.categories unknown: {', '.join(sorted(unknown))} "
                             f"(known: {', '.join(NONE_CATEGORIES)})")
        self.none_source = none.get("source") or self.default_source
        # A category can have a source of its own (none: {sources: {reference_sources: ...}}) -
        # otherwise the common one holds.
        self.none_sources = dict(none.get("sources") or {})
        self.core_paths, self.cores = [], []
        # "eln_records: none" - the series has no ELN record at all: one statement in the
        # series block instead of the answer "No ELN record" per experiment under 'open'.
        records = self.series.get("eln_records")
        self.no_eln_record = isinstance(records, str) and _norm(records) == "none"
        for record in [] if self.no_eln_record else _as_list(self.series.get("eln_records")):
            # Relative to the sheet: "core/AI4Green_AI4-001.json" in the project folder.
            path = Path(record)
            if not path.is_absolute():
                path = self.sheet_path.parent / path
            self.core_paths.append(path)
            self.cores.append(json.loads(path.read_text(encoding="utf-8")))

        # Materials and uncontained streams under their normalized name; phases under (material, phase).
        self.materials = {}
        for entry in _as_list(sheet.get("materials")):
            self.materials[_norm(entry["name"])] = dict(entry, _kind="material")
        for entry in _as_list(sheet.get("uncontained_streams")):
            self.materials[_norm(entry["name"])] = dict(entry, _kind="uncontained_stream")
        self.content_of = {_norm(m["content_of"]): m for m in self.materials.values() if m.get("content_of")}
        # Devices whose cavity holds nothing but the gas around it (a cap on its bottle).
        self.empty_cavities = {_norm(d) for d in _as_list(sheet.get("empty_cavities")) if isinstance(d, str)}
        self.phases = {}
        for material in self.materials.values():
            for phase in _as_list(material.get("phases")):
                state = _STATE_ALIASES.get(str(phase.get("state", "")).lower(), str(phase.get("state", "")).lower())
                if state not in STATES:
                    raise ValueError(f"{self.sheet_name}: phase {phase.get('name')!r} of {material['name']!r} "
                                     f"has no state out of {', '.join(STATES)}.")
                self.phases[(_norm(material["name"]), _norm(phase["name"]))] = dict(phase, state=state, _material=material)

        self.chemical_library = self._load_library("chemical_entity_library.jsonld")
        self._resolve_species()
        self.reactions = _as_list(sheet.get("reactions"))
        self.reaction_ids = self._reaction_ids()
        self.tasks = {_norm(t["name"]): t for t in _as_list(sheet.get("tasks"))}
        # Settings of the devices (operation mode, profiles) and the files with their origin - each
        # under the normalized name.
        self.device_settings = {_norm(d["device"]): d for d in _as_list(sheet.get("device_settings")) if isinstance(d, dict)}
        self.files = {_norm(f["name"]): f for f in _as_list(sheet.get("files")) if isinstance(f, dict)}
        # Open questions an exploratory run wrote into the sheet (workflow/open_questions.py
        # --write-sheet) and that somebody answered: key -> entry. "answer:" without a value is
        # still open, "answer: ''" empty on purpose.
        self.open_answers = {str(e["key"]): e for e in _as_list(sheet.get("open"))
                             if isinstance(e, dict) and e.get("key") and e.get("answer") is not None}
        # (experiment, material, phase, substance or "", quantity) -> value, see _collect_values
        self.values = self._collect_values()
        # Times of tasks (at: task:<name>) and of occurrences (occurrence: k) in the section "values" and
        # the statements about occurrences (section "occurrences").
        self.time_values = self._collect_time_values()
        self.occurrence_statements = self._collect_occurrences()
        # Places at which the sheet names every quantity offered (with a value or "kind: none").
        self._complete_places = set()
        # The experiment of the question being answered (None: a key of the series) - see _time_or_occurrence_determiner.
        self._key_experiment = None

        value_path, level = VALUE_PATH, LEVEL
        self._handlers = [(re.compile(pattern), handler) for pattern, handler in (
            (r"setup/series_short_name", self._short_name),
            (r"setup/number_of_conducted_experiments", self._conducted),
            (r"setup/number_of_planned_experiments", self._planned),
            (r"setup/series_completed", self._completed),
            (r"(setup|series:1)/series_description", self._series_description),
            (r"series:1/series_(?P<role>creator|experimenter)", self._series_people),
            (r"series:1/same_(creator|experimenter)_for_all_experiments", self._same_in_one_experiment),
            (r"series:1/experiment:(?P<exp>\d+)/eln_record", self._eln_record),
            (r"series:1/experiment:(?P<exp>\d+)/absent_species", self._absent_species),
            (r"series:1/task:[^/]+/same_parts_in_all_experiments", self._same_in_one_experiment),
            (r"series:1/task:[^/]+/performed_by_scope", self._same_performers),
            (r"series:1/devices", self._devices),
            (r"series:1/device:(?P<device>[^/]+)/contained_material_type", self._contained_material_type),
            (r"series:1/device:(?P<device>[^/]+)/name", self._contained_material_name),
            (r"series:1/additional_material_names", self._additional_materials),
            (r"series:1/material:(?P<material>[^/]+)/material_type", self._material_type),
            (r"series:1/material:(?P<material>[^/]+)/(?P<state>solid|liquid|gaseous)_phase_names", self._phase_names),
            (r"series:1/material:(?P<material>[^/]+)/flows_(?P<end>from|to)_port", self._flow_port),
            (r"series:1/material:(?P<material>[^/]+)/phase:(?P<phase>[^/]+)/species_names", self._species_names),
            (r"series:1/material:(?P<material>[^/]+)/phase:(?P<phase>[^/]+)/dispersion_state", self._dispersion),
            (r"series:1/material:(?P<material>[^/]+)/phase:(?P<phase>[^/]+)/solid_structure", self._structure),
            (r"series:1/material:(?P<material>[^/]+)/phase:(?P<phase>[^/]+)/same_solvent_across_experiments", self._same_solvent),
            (r"series:1/material:(?P<material>[^/]+)/phase:(?P<phase>[^/]+)/solvents", self._solvents),
            (r"fixed/reactions", self._fixed_reactions),
            (r"series:1/reaction:(?P<reaction>[^/]+)/occurs_in_series", self._reaction_occurs),
            (r"series:1/reaction:(?P<reaction>[^/]+)/location_kind", self._reaction_location_kind),
            (r"series:1/reaction:(?P<reaction>[^/]+)/location_phase", self._reaction_location_phase),
            (r"series:1/reaction:(?P<reaction>[^/]+)/location_interface", self._reaction_location_interface),
            (r"series:1/extra_task_names", self._extra_tasks),
            # Tasks of only some experiments (field "experiments" of a task) - before "none: experiment_tasks" is read.
            (r"series:1/experiment:(?P<exp>\d+)/extra_task_names", self._experiment_tasks),
            (r"series:1/grouping_tasks", self._grouping_tasks),
            # Also per experiment: a section with "varies: [parts]" is asked per experiment.
            (r"series:1/(?:experiment:\d+/)?task:(?P<task>[^/]+)/parts", self._task_parts),
            (r"series:1/(?:experiment:\d+/)?task:(?P<task>[^/]+)/task_type", self._task_type),   # per experiment: a task of one experiment only
            (r"series:1/(experiment:\d+/)?task:(?P<task>[^/]+)/equipment", self._task_equipment),
            (r"series:1/experiment:(?P<exp>\d+)/task:(?P<task>[^/]+)/empties", self._task_empties),
            (r"series:1/(?:experiment:\d+/)?task:(?P<task>[^/]+)/functions", self._task_functions),
            (r"series:1/(experiment:\d+/)?task:(?P<task>[^/]+)/covered_by_existing", self._covered_by_existing),
            (r"series:1/(experiment:\d+/)?task:(?P<task>for-[^/]+)/name", self._determining_task_name),
            (r"series:1/(experiment:\d+/)?task:(?P<task>for_File_[^/]+)/name", self._file_task_name),
            (r"series:1/(experiment:\d+/)?task:(?P<task>[^/]+)/performers", self._task_performers),
            (r"series:1/(experiment:\d+/)?task:(?P<task>[^/]+)/executes_profile", self._executes_profile),
            (r"series:1/(experiment:(?P<exp>\d+)/)?task:(?P<task>[^/]+)/which_profile", self._which_profile),
            (r"series:1/(experiment:(?P<exp>\d+)/)?task:(?P<task>[^/]+)/generated_media_objects", self._task_files),
            (r"series:1/(experiment:\d+/)?task:(?P<task>[^/]+)/feature_of_interest", self._on_sample),
            (r"series:1/(experiment:(?P<exp>\d+)/)?task:(?P<task>[^/]+)/observed", self._observes),
            (r"series:1/device:(?P<device>[^/]+)/same_operation_mode_across_experiments", self._same_mode),
            # Which content of a device filled one after the other (rule 2.15): device_settings / content.
            (r"series:1/device:(?P<device>[^/]+)/library_content", self._library_content),
            (r"series:1/(?:experiment:(?P<exp>\d+)/)?device:(?P<device>[^/]+)/(?:experiment:(?P<exp2>\d+)/)?operation_mode",
             self._operation_mode),
            (r"series:1/(experiment:\d+/)?media_object:(?P<file>[^/]+)/generated_by_task", self._file_from_task),
            (r"series:1/(experiment:\d+/)?media_object:(?P<file>[^/]+)/which_task", self._file_which_task),
            (r"series:1/(experiment:\d+/)?media_object:(?P<file>[^/]+)/task_type", self._file_task_type),
            (r"series:1/(experiment:\d+/)?media_object:(?P<file>[^/]+)/reference_column_header", self._reference_column),
            # Questions with a field of their own: file type and creator, the phases at
            # a port crossing, the transfers of a reaction's participants, the place of its elementary reactions.
            (r"series:1/(experiment:\d+/)?media_object:(?P<file>[^/]+)/media_object_type", self._file_type),
            (r"series:1/(experiment:\d+/)?media_object:(?P<file>[^/]+)/creator_(?P<what>kind|person)", self._file_creator),
            (r"series:1/port_crossing:(?P<crossing>[^/]+)/(?P<question>device_side_phase|opens_into_phase)", self._crossing_phase),
            (r"series:1/stream_port_ends:(?P<material>[^/]+)/crossing_stream_phases", self._crossing_stream_phases),
            (r"series:1/(?:reaction:(?P<reaction>[^/]+)|elementary_reaction:(?P<elementary>[^/]+))/participant_transfer:"
             r"(?P<participant>[^/]+)/(?P<field>phase|transfer_type)", self._participant_transfer),
            (r"series:1/elementary_reaction:(?P<elementary>[^/]+)/location_(?P<field>kind|interface|phase)", self._elementary_location),
            (OCCURRENCES + THING + r"/occurrence:(?P<k>\d+)/status/(?:reference:(?P<idx>\d+)/)?reference_source",
             self._occurrence_status_document),
            # Occupation states of an interface: section occupation_states.
            (r"series:1/phase_interface:(?P<interface>[^/]+)/occupation_state_names", self._occupation_names),
            (r"series:1/phase_interface:(?P<interface>[^/]+)/occupation_state:(?P<state>[^/]+)/"
             r"(?P<field>target_interface|is_free_site|has_bound_to|sorption_type)", self._occupation_field),
            (r"series:1/phase_interface:(?P<interface>[^/]+)/occupation_state:(?P<state>[^/]+)/"
             r"(?P<role>occupied_by|bound_to)_quick_pick", self._occupation_pick),
            (r"series:1/phase_interface:(?P<interface>[^/]+)/occupation_state:(?P<state>[^/]+)/"
             r"(?P<role>occupied_by|bound_to)_search:\d+/identifier_(?P<what>field|value)", self._occupation_search),
            (r"series:1/occupation_state:(?P<library>[^/]+)/occupation_state", self._occupation_known),
            (r"series:1/sample_materials", self._sample_materials),
            (r"series:1/material:(?P<material>[^/]+)/is_sample_of", self._sample_of),
            (r"series:1/material:(?P<material>[^/]+)/phase:(?P<phase>[^/]+)/form_class", self._form),
            (r"series:1/experiment:\d+/task:(?P<task>[^/]+)/performed_by_scope", self._performed_by_person),
            # Times of the tasks: "times" at the task or values "at: task:<name>".
            (r"series:1/experiment:(?P<exp>\d+)/task:(?P<task>[^/]+)/quantities_with_(?P<role>evidence|reference)",
             self._task_time_list),
            (r"series:1/experiment:(?P<exp>\d+)/task:(?P<task>[^/]+)/" + TIME_FIELD, self._task_time_field),
            (r"series:1/experiment:(?P<exp>\d+)/task:(?P<task>[^/]+)/" + TIME_ANOTHER, self._task_time_another),
            (r"series:1/(experiment:\d+/)?task:(?P<task>[^/]+)/time_sources", self._time_sources),
            (r"series:1/(experiment:\d+/)?task:(?P<task>[^/]+)/time_source_specification", self._time_source_detail),
            (r"series:1/(experiment:\d+/)?task:(?P<task>[^/]+)/(?P<field>software|aims_at)", self._task_detail_list),
            # Occurrences: section "occurrences", their times under "values" with "occurrence: k".
            (OCCURRENCES + r"(?P<list>phases|interfaces|reactions|energy_fields|transfer_places)", self._occurrence_list),
            (OCCURRENCES + r"place:(?P<place>[^/]+)/transfers", self._occurrence_transfers),
            (OCCURRENCES + THING + r"/number_of_occurrences", self._occurrence_count),
            (OCCURRENCES + THING + r"/occurrence:(?P<k>\d+)/status_source", self._occurrence_status_source),
            (OCCURRENCES + THING + r"/occurrence:(?P<k>\d+)/status/(?:(?:evidence|reference):(?P<idx>\d+)/)?"
             r"(?P<role>evidence|reference)_(?P<field>exists|value_type|type)", self._occurrence_status_field),
            (OCCURRENCES + THING + r"/occurrence:(?P<k>\d+)/status/(?P<role>evidence|reference):(?P<idx>\d+)/"
             r"have_another_(?:evidence|reference)", self._occurrence_status_another),
            (OCCURRENCES + THING + r"/occurrence:(?P<k>\d+)/quantities_with_(?P<role>evidence|reference)", self._occurrence_time_list),
            (OCCURRENCES + THING + r"/occurrence:(?P<k>\d+)/" + TIME_FIELD, self._occurrence_time_field),
            (OCCURRENCES + THING + r"/occurrence:(?P<k>\d+)/" + TIME_ANOTHER, self._occurrence_time_another),
            (r"series:1/(experiment:\d+/)?task:(?P<task>[^/]+)/description", self._task_description),
            (r"series:1/experiment:\d+/task:(?P<task>[^/]+)/input_values", self._task_inputs),
            # At the series only "inputs: []" (the setting task of a speed profile); otherwise "none: task_details".
            (r"series:1/task:(?P<task>[^/]+)/input_values", self._series_task_inputs),
            # Values of the core file - before the general lists.
            (r"series:1/" + value_path + r"/quantities_known_per_experiment", self._gate_series_values),
            (level + value_path + r"/quantities_with_(?P<kind>evidence|reference)", self._gate_values),
            (level + value_path + r"/(?P<quantity>[a-z_]+)/(?:(?:evidence|reference):(?P<idx>\d+)/)?(?P<kind>evidence|reference)_"
             r"(?P<field>exists|type|value_type|quantity_kind|variable_kind|scalar_value|scalar_unit|bounds_unit|exactness|lower_bound|upper_bound|series_column|source)",
             self._value_field),
            (level + value_path + r"/(?P<quantity>[a-z_]+)/(?P<kind>evidence|reference):(?P<idx>\d+)/have_another_(evidence|reference)",
             self._another_value),
            # The concentration of a species: the same questions without the segment "concentration/".
            (level + SPECIES_PATH + r"/(?:(?:evidence|reference):(?P<idx>\d+)/)?(?P<kind>evidence|reference)_"
             r"(?P<field>exists|type|value_type|quantity_kind|variable_kind|scalar_value|scalar_unit|bounds_unit|exactness|lower_bound|upper_bound|series_column|source)",
             self._concentration_field),
            (level + SPECIES_PATH + r"/(?P<kind>evidence|reference):(?P<idx>\d+)/have_another_(evidence|reference)",
             self._another_concentration),
            # A profile as a value: its steps stand at the value under "steps".
            (level + value_path + r"/(?P<quantity>[a-z_]+)/(?:(?:evidence|reference):(?P<idx>\d+)/)?(?:profile_step:(?P<k>\d+)/)?"
             r"(?P<kind>evidence|reference)_profile_(?P<field>[a-z_]+)", self._profile_field),
            (r"series:1/.*/(" + "|".join(GATE_QUESTIONS) + r")", self._gate),
            (r"series:1/.*/have_another_(evidence|reference)", self._no_other_value),
            *((pattern, self._none_list(category)) for pattern, category in _NONE_PATTERNS),
        )]

    # ------------------------------------------------------------------
    # Called as an answer provider
    # ------------------------------------------------------------------

    def __call__(self, *, key, prompt, options, answer_type, required, stored):
        # A list from the options (helpers/user_io.py: ask_user_list) hands its options on
        # through the parser, not through "options".
        options = options or getattr(answer_type, "list_options", None)
        # A required list (e.g. the input values of a calculation) cannot be "nothing" - the
        # generator asks that, even if the sheet says "none".
        required = required or getattr(answer_type, "list_required", False)
        if key in self.open_answers:
            return self._open_answer(self.open_answers[key])
        self._key_experiment = _experiment_of_key(key)
        for pattern, handler in self._handlers:
            match = pattern.fullmatch(key)
            if match:
                return handler(match, options=options, prompt=prompt, required=required, answer_type=answer_type)
        return None

    def own_field(self, key) -> str | None:
        """The name of the adapter part that answers this key from a field of its own in the sheet -
        None when only "none" (or nothing) answers it. Such a question belongs in that field, not
        in the section "open" (one place per fact)."""
        self._key_experiment = _experiment_of_key(key)
        for pattern, handler in self._handlers:
            match = pattern.fullmatch(key)
            if match:
                name = getattr(handler, "__qualname__", "").replace("SetupAdapter.", "")
                if name in ("_task_time_list", "_task_time_field", "_task_time_another") and not self._task_in_sheet(match.group("task")):
                    # The times of a task the sheet does not list under "tasks" (such as an
                    # assumption task the generator derives): no field they fit into.
                    return None
                if {"material", "phase"} <= set(match.groupdict()) and self._phase(match) is None:
                    # A phase the sheet does not list (the content of a device from the Material Library,
                    # such as the compressed air of the lab supply): no field, the question belongs under 'open'.
                    return None
                return None if name.split(".")[0] in NONE_ONLY_HANDLERS else name
        return None

    def _task_in_sheet(self, key_segment) -> bool:
        """Whether the task behind a key segment is an entry of the sheet's "tasks" - only then has it
        a field "times". A built-in task always may be (the sheet names it to give it its times)."""
        if key_segment in BUILT_IN_TASKS:
            return True
        _name, task = self._sheet_task(key_segment)
        return task is not None and _norm(task.get("name")) in self.tasks

    @property
    def experiment_count(self) -> int:
        """Conducted experiments: one per core file, or - without an ELN - as the sheet says."""
        return len(self.cores) or int(self.series.get("conducted_experiments") or 0)

    def sheet_at(self, path) -> tuple:
        """(at, of) in the terms of the sheet for a key path of a value's place (the reverse of
        _collect_values) - names as the sheet writes them where it has them."""
        parts = dict(part.split(":", 1) for part in path.split("/"))
        if set(parts) - {"material", "phase", "species", "reaction", "participant", "device"}:
            return path, None
        if set(parts) == {"reaction"}:
            return self.reaction_ids.get(_norm(parts["reaction"]), {}).get("name", parts["reaction"]), None
        if "participant" in parts:
            reaction = self.reaction_ids.get(_norm(parts["reaction"]), {}).get("name", parts["reaction"])
            participant = next((e for e in self._load_library("reaction_library.jsonld").get("@graph", [])
                                if _norm(e.get("@id", "").split(":", 1)[-1]) == _norm(parts["participant"])), {})
            species = (participant.get("dcterms:hasPart") or {}).get("@id") if isinstance(participant.get("dcterms:hasPart"), dict) else None
            names = {p["_species_ids"][species] for p in self.phases.values() if species in p["_species_ids"]}
            return reaction, (names.pop() if len(names) == 1 else parts["participant"])
        if "device" in parts:
            # The content of a device is a place of its own - with its path, not under the device.
            return (parts["device"] if set(parts) == {"device"} else path), None
        if _norm(parts["material"]) not in self.materials:
            # A material the sheet does not name (content of a library device): with its
            # path, like a derived place (material:h2_cylinder_01_Content/phase:...).
            return path, None
        material = self.materials.get(_norm(parts["material"]), {}).get("name", parts["material"])
        if "phase" not in parts:
            return material, None
        phase = self.phases.get((_norm(parts["material"]), _norm(parts["phase"])), {})
        at = f"{material}/{phase.get('name', parts['phase'])}"
        if "species" not in parts:
            return at, None
        names = [n for n in phase.get("_species_ids", {}).values() if _norm(n) == _norm(parts["species"])]
        return at, (names[0] if names else parts["species"])

    def _open_answer(self, entry):
        """The answer of an open question of the sheet, as the answer file would hold it."""
        answer = entry["answer"]
        if isinstance(answer, bool):
            # YAML reads an unquoted Yes/No as a boolean.
            answer = "Yes" if answer else "No"
        elif isinstance(answer, list):
            answer = "; ".join(str(a) for a in answer)
        return str(answer), self._source(entry, "answer")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _source(self, entry, field=None) -> str:
        """The source of an answer taken from a sheet entry: its own "source" (a text for all of
        its fields, or a table per field), else the sheet's."""
        own = entry.get("source") if isinstance(entry, dict) else None
        if isinstance(own, str):
            return own
        if isinstance(own, dict) and field in own:
            return own[field]
        return self.default_source

    def _record_label(self, core=None) -> str:
        core = core or self.cores[0]
        return f"ELN {core['source']['system']} {core['source']['record_id']}"

    @staticmethod
    def _label(option) -> str:
        from helpers.user_io import option_label
        return option_label(option)

    def _option(self, options, wanted):
        """The label of the one option that names `wanted` (compared like _norm), or None."""
        hits = [self._label(o) for o in options or [] if _norm(self._label(o)) == _norm(wanted)]
        return hits[0] if len(hits) == 1 else None

    def _device_parts(self) -> set:
        """The parts (dcterms:hasPart, at any depth) of the devices the sheet lists, normed - a value or an
        'unknown' entry may stand at a part (the generator asks for them)."""
        entries = {e["@id"]: e for e in self._load_library("device_library.jsonld").get("@graph", [])
                   if str(e.get("@id", "")).startswith("device:")}
        todo = [f"device:{d}" for d in _as_list(self.sheet.get("devices")) if isinstance(d, str)]
        parts = set()
        while todo:
            for part in _as_list((entries.get(todo.pop()) or {}).get("dcterms:hasPart")):
                part_id = part.get("@id") if isinstance(part, dict) else part
                if part_id and _norm(part_id.split(":", 1)[-1]) not in parts:
                    parts.add(_norm(part_id.split(":", 1)[-1]))
                    todo.append(part_id)
        return parts

    def _load_library(self, file_name) -> dict:
        import path_definitions
        from helpers.library_files import read_library
        # Main file and details as one library.
        return read_library(path_definitions.LIBRARY_FOLDER / file_name)

    def _resolve_species(self):
        """Every species of the sheet has to name exactly one entry of the Chemical Entity Library,
        found the way the generator finds it. Otherwise the generator would start its search
        dialogue - and a name split by YAML (N,N-Dimethylformamide in [...] without quotes)
        would never be found at all. The IDs found are kept for the values (_collect_values)."""
        from creation.chemical_entity_functions import search_chemical_entities_by_name
        problems = []
        for phase in self.phases.values():
            phase["_species_ids"] = {}
            for name in _as_list(phase.get("species")):
                hits = search_chemical_entities_by_name(self.chemical_library, str(name), exclude_types=["cpo:ActiveSite"])
                if len(hits) != 1:
                    problems.append(f"'{name}' ({phase['name']}): {len(hits)} entries")
                else:
                    phase["_species_ids"][hits[0]["@id"]] = str(name)
        if problems:
            raise ValueError(f"{self.sheet_name}: species that do not name exactly one entry of the Chemical "
                             f"Entity Library (a name with a comma needs quotes): " + "; ".join(problems))

    def _reaction_ids(self) -> dict:
        """Local name of the Reaction Library ID -> sheet entry, found by the reaction's name or by its ID
        (reaction:PBA_Ferrocyanide_Ni or PBA_Ferrocyanide_Ni)."""
        wanted = {_norm(r["name"]): r for r in self.reactions}
        found = {}
        # What the library calls the reaction, per entry of the sheet - for the answer to the choice question.
        self.reaction_library_names = {}
        for entity in self._load_library("reaction_library.jsonld").get("@graph", []):
            name, local = entity.get("schema:name"), entity["@id"].split(":", 1)[-1]
            if name is not None and _norm(name) in wanted:
                entry = wanted[_norm(name)]
            elif {"cpo:StoichiometricReaction", "cpo:LumpedReaction"} & set(_as_list(entity.get("@type"))) and (
                    _norm(local) in wanted or _norm(entity["@id"]) in wanted):
                entry = wanted.get(_norm(local)) or wanted[_norm(entity["@id"])]
            else:
                continue
            found[_norm(local)] = entry
            self.reaction_library_names[_norm(entry["name"])] = name or entry["name"]
        missing = set(wanted) - {_norm(r["name"]) for r in found.values()}
        if missing:
            raise ValueError(f"{self.sheet_name}: reactions not in the Reaction Library: "
                             + ", ".join(r["name"] for r in self.reactions if _norm(r["name"]) in missing))
        return found

    def _material(self, match):
        return self.materials.get(_norm(match.group("material")))

    def _phase(self, match):
        return self.phases.get((_norm(match.group("material")), _norm(match.group("phase"))))

    def _sheet_task(self, key_segment):
        """(name, sheet entry) of the task behind a key segment: a built-in task (task:procedure),
        a task of the sheet by its name, or the task of the sheet that determines the value a
        placeholder task stands for (task:for-Mass_Phase_Product_Phase_Evidence_1_...)."""
        name = BUILT_IN_TASKS.get(key_segment, key_segment)
        task = self.tasks.get(_norm(name))
        if task is None and key_segment.startswith("for-"):
            task = self._determiner_for(key_segment)
            name = task["name"] if task else name
        if task is None and key_segment.startswith("for_File_"):
            task = self._file_task(key_segment)
            name = task["name"] if task else name
        return name, task

    def _file_task(self, key_segment):
        """The sheet task a file brings with it (task:for_File_exp1_mass.xlsx_ExperimentSpecific): the
        one its entry in "files" names under "from", if that task is marked created_from_file."""
        found = re.fullmatch(r"for_File_(?P<file>.+?)_(?:ExperimentSpecific|SeriesSpecific)", key_segment)
        file = self.files.get(_norm(found.group("file"))) if found else None
        task = self.tasks.get(_norm((file or {}).get("from") or ""))
        return task if task and task.get("created_from_file") else None

    def _value_for(self, key_segment):
        """The value a placeholder task stands for ("for-<Quantity>_..._<material, phase, participant
        or device>_<Evidence|Reference>_<n>_..."), or None."""
        segment = _norm(key_segment)
        hits = []
        for value in self.values:
            if not value["kind"]:
                continue
            parts = dict(part.split(":", 1) for part in value["place"].split("/"))
            anchor = (parts.get("participant") or parts.get("phase") or parts.get("device") or parts.get("material")
                      or value["place"].rsplit(":", 1)[-1])
            if (segment.startswith("for" + _norm(value["quantity"])) and f"{anchor}{value['kind']}{value['index']}" in segment
                    and value["anchor_extra"] in segment):
                hits.append(value)
        # The value of a substance in a phase (5 mg palladium) also fits that of the whole phase (100 mg
        # catalyst) - the more precise one wins, the one naming the substance.
        if any(v["anchor_extra"] for v in hits):
            hits = [v for v in hits if v["anchor_extra"]]
        # The task of the series stands for the same value in every experiment - one hit, not several. A
        # device value in the experiment names the experiment in its place (device:stirrer001/experiment:1).
        distinct = {(re.sub(r"/experiment:\d+$", "", v["place"]), v["quantity"], v["kind"], v["index"]) for v in hits}
        return hits[0] if len(distinct) == 1 else None

    def _determiner_for(self, key_segment):
        """The sheet task whose "determines" names the value of this placeholder task - by its group
        (reaction_table, conditions, product_mass, yield, selectivity) or as <material>/<phase>/<quantity>.
        Also the task that determined a time of a task or of an occurrence, or the status of an
        occurrence - named by determined_by at the value or at the statement of the section "occurrences"."""
        found = self._time_or_occurrence_determiner(key_segment)
        if found is not None:
            return found
        time_of = re.fullmatch(r"for-Task_(?P<task>.+)_(StartTime|EndTime)_(Evidence|Reference)_\d+_ExperimentSpecific", key_segment)
        if time_of:
            # The time of a task: determined by the task whose determines names "<task>/times".
            wanted = _norm(time_of.group("task")) + "times"
            hits = [task for task in self.tasks.values()
                    if any(_norm(target) == wanted for target in _as_list(task.get("determines")))]
            return hits[0] if len(hits) == 1 else None
        value = self._value_for(key_segment)
        if value is None:
            return None
        if value["determined_by"]:
            # Named at the value: the task of the sheet of this name - or one the sheet does not
            # describe (then only its name).
            return self.tasks.get(_norm(value["determined_by"])) or {
                "name": value["determined_by"], "source": {"name": value["sources"]["determined_by"],
                                                           "determines": value["sources"]["determined_by"]}}
        hits = [task for task in self.tasks.values()
                if any(_norm(target) in (_norm(value["group"]), value["path"]) for target in _as_list(task.get("determines")))]
        return hits[0] if len(hits) == 1 else None

    def _none_answer(self, category, answer):
        """The answer when the sheet says "none" for this category, else None (asked)."""
        if category not in self.none:
            return None
        return answer, f"{self.none_sources.get(category, self.none_source)} (none: {category})"

    def _none_list(self, category):
        def handler(match, required, **_):
            return None if required else self._none_answer(category, "")
        return handler

    def _people(self, role, options):
        """(labels, source) for the people the sheet names for a role (creator, experimenter),
        or None when it names none or one of them is not an option."""
        names = _as_list(self.people.get(role))
        labels = [self._option(options, name) for name in names]
        if not names or None in labels:
            return None
        return labels, self._source(self.people, role)

    # ------------------------------------------------------------------
    # Series
    # ------------------------------------------------------------------

    def _short_name(self, match, **_):
        return self.series["short_name"], self._source(self.series, "short_name")

    def _conducted(self, match, **_):
        if self.cores:
            return str(len(self.cores)), self._source(self.series, "eln_records")
        if not self.series.get("conducted_experiments"):
            return None
        return str(self.series["conducted_experiments"]), self._source(self.series, "conducted_experiments")

    def _planned(self, match, **_):
        planned = self.series.get("planned_experiments")
        if planned in (None, ""):
            return "", f"M: not known ({self.sheet_name} leaves planned_experiments empty)"
        return str(planned), self._source(self.series, "planned_experiments")

    def _completed(self, match, **_):
        if "completed" not in self.series:
            return None
        return ("Yes" if self.series["completed"] else "No"), self._source(self.series, "completed")

    def _series_description(self, match, **_):
        # "series: {description: ...}" in the sheet; otherwise from the core file: title and origin
        # of the record - without a core file it is asked.
        if self.series.get("description"):
            return str(self.series["description"]).strip(), self._source(self.series, "description")
        if not self.cores:
            return None
        parts = []
        for core in self.cores:
            source = core.get("source") or {}
            title = (core.get("experiment") or {}).get("title")
            record = f"{source.get('system')} {source.get('version')}, record {source.get('record_id')}"
            if source.get("record_url"):
                record += f" ({source['record_url']})"
            parts.append(f"{title} - {record}, exported as {source.get('file')}" if title else f"{record}, exported as {source.get('file')}")
        return "; ".join(parts) + ".", "E: " + ", ".join(
            f"ELN {(c.get('source') or {}).get('system')} {(c.get('source') or {}).get('record_id')}, experiment.title, source" for c in self.cores)

    def _series_people(self, match, options, **_):
        # Who planned and performed the series is said by the sheet - not the author of the record
        # (the author is the creator of the record).
        found = self._people(match.group("role"), options)
        if found is None:
            return None
        return "; ".join(found[0]), found[1]

    def _same_in_one_experiment(self, match, **_):
        if len(self.cores) == 1:
            return "Yes", rule("A3")
        # Several experiments: people and parts the sheet names for the series hold in each -
        # unless an entry says "varies: [creator | experimenter | parts]".
        key = match.group(0)
        if key.endswith(("same_creator_for_all_experiments", "same_experimenter_for_all_experiments")):
            role = "creator" if "creator" in key else "experimenter"
            if self.people.get(role) and role not in _as_list(self.people.get("varies")):
                return "Yes", self._source(self.people, role)
            return None
        task_match = re.search(r"task:([^/]+)/same_parts_in_all_experiments$", key)
        if task_match:
            name, task = self._sheet_task(task_match.group(1))
            if "parts" in _as_list((task or {}).get("varies")):
                return "No", self._source(task, "varies")
            parts = [t for t in self.tasks.values() if _norm(t.get("part_of", "")) == _norm(name)]
            if parts:
                return "Yes", self._source(parts[0], "part_of")
            if _norm(name) in map(_norm, BUILT_IN_TASKS.values()) and self.tasks:
                # A fixed shell the sheet gives no parts: none in any experiment (like _task_parts).
                return "Yes", self.default_source
        return None

    def _eln_record(self, match, options, **_):
        # Experiment n is the n-th record of the sheet (A1, series.eln_records in the order of the
        # experiments). Its entry in the Reaction Library carries "<system> <record_id>" as
        # schema:identifier (Chemotion adds the UUID in brackets). Without eln_records no answer:
        # that there is no record is said by the person ("eln_records: none"), not by its absence in the sheet.
        if self.no_eln_record:
            label = self._option(options, "No ELN record")
            return (label, self._source(self.series, "eln_records")) if label else None
        n = int(match.group("exp"))
        if not self.cores or n > len(self.cores):
            return None
        source = self.cores[n - 1].get("source") or {}
        wanted = f"{source.get('system')} {source.get('record_id')}"
        hits = [e["@id"].removeprefix("reaction:") for e in self._load_library("reaction_library.jsonld").get("@graph", [])
                if "schema:Dataset" in _as_list(e.get("@type"))
                and str(e.get("schema:identifier", "")).split(" (")[0] == wanted]
        label = self._option(options, hits[0]) if len(hits) == 1 else None
        if label is None:
            return None
        return label, f"E: ELN {wanted}, source.record_id (record {n} of series.eln_records, {rule('A1')[3:]})"

    def _absent_species(self, match, options, **_):
        # The substances of the series that do not occur in experiment n: those
        # species_per_experiment names without n. Without the field none (A14). A name that is no option
        # (no species of the series) gives no answer - the question goes under 'open' and shows the mistake.
        n = int(match.group("exp"))
        table = self.sheet.get("species_per_experiment")
        if table is None:
            return "", rule("A14")
        names = [name for name, experiments in table.items() if name != "source" and n not in _as_list(experiments)]
        labels = [self._option(options, name) for name in names]
        if None in labels:
            return None
        source = table.get("source") or self.default_source
        return "; ".join(labels), source

    def _same_performers(self, match, prompt, **_):
        # On the series level performed_by_scope asks "the same people in every experiment?".
        if not re.search(r"every experiment|each individual experiment", prompt):
            return None
        if len(self.cores) == 1:
            return "Yes", rule("A3")
        # Performers at the task of the sheet hold in every experiment, unless "varies: [performers]".
        _name, task = self._sheet_task(re.search(r"task:([^/]+)/", match.group(0)).group(1))
        if task and "performers" in _as_list(task.get("varies")):
            return "No - it differs between experiments", self._source(task, "varies")
        if task and "performers" in task and not task["performers"]:
            # Explicitly nobody: a device did it alone (a logger).
            return "Nobody - equipment did this on its own", self._source(task, "performers")
        if task and task.get("performers"):
            return "Yes", self._source(task, "performers")
        return None

    # ------------------------------------------------------------------
    # Devices, materials, phases
    # ------------------------------------------------------------------

    def _devices(self, match, **_):
        devices = _as_list(self.sheet.get("devices"))
        if not devices:
            return None
        return "; ".join(devices), self.sheet.get("devices_source") or self.default_source

    @staticmethod
    def _is_stream(material) -> bool:
        """An uncontained stream, or a material the sheet marks "kind: stream" (the content of a jacket or a sparger,
        flowing from its inlet to its outlet)."""
        return material["_kind"] == "uncontained_stream" or str(material.get("kind", "")).lower() == "stream"

    def _contained_material_type(self, match, **_):
        material = self.content_of.get(_norm(match.group("device")))
        if material is None:
            if _norm(match.group("device")) in self.empty_cavities:
                from creation.device_functions import NOTHING_BUT_SURROUNDING_GAS
                return NOTHING_BUT_SURROUNDING_GAS, self.sheet.get("empty_cavities_source") or self.default_source
            return None
        return ("Stream" if self._is_stream(material) else "MaterialVolume"), self._source(material, "content_of")

    def _contained_material_name(self, match, prompt, **_):
        material = self.content_of.get(_norm(match.group("device")))
        if material is None or ("Stream" if self._is_stream(material) else "MaterialVolume") not in prompt:
            return None
        return material["name"], self._source(material, "name")

    def _additional_materials(self, match, **_):
        extra = [m for m in self.materials.values() if not m.get("content_of")]
        return "; ".join(m["name"] for m in extra), self.default_source

    def _material_type(self, match, **_):
        material = self._material(match)
        if material is None:
            return None
        return ("Stream" if self._is_stream(material) else "MaterialVolume"), self._source(material, "name")

    def _phase_names(self, match, **_):
        material = self._material(match)
        if material is None:
            return None
        state = match.group("state")
        phases = [p for p in _as_list(material.get("phases"))
                  if _STATE_ALIASES.get(str(p.get("state")).lower(), str(p.get("state")).lower()) == state]
        # The source of the states, if the entry names one of its own - otherwise that of the sheet.
        return "; ".join(p["name"] for p in phases), self._source(material, "state")

    def _flow_port(self, match, options, **_):
        material = self._material(match)
        if material is None or not self._is_stream(material):
            return None
        end = match.group("end")
        target = material.get(end)
        if target is None:
            return None
        labels = [self._label(o) for o in options or []]
        if target == "outside":
            wanted = "New Source outside" if end == "from" else "New Sink outside"
            hits = [label for label in labels if label.startswith(wanted)]
        else:
            # A device with exactly one port, or the port itself ("flask_50mL_01_opening").
            hits = [label for label in labels if _norm(label.lstrip("#")) == _norm(f"{target}SeriesSpecific")]
            if not hits:
                hits = [label for label in labels if _norm(label.lstrip("#")).startswith(_norm(target))]
        if len(hits) != 1:
            return None
        return hits[0], self._source(material, end)

    def _species_names(self, match, **_):
        phase = self._phase(match)
        if phase is None:
            # The content of a device of the sheet that the libraries describe (a container of the inventory, a
            # supply line): nothing beyond the library (rule A15).
            material = _norm(match.group("material"))
            if material.endswith("content") and any(_norm(d) + "content" == material
                                                    for d in _as_list(self.sheet.get("devices")) if isinstance(d, str)):
                return "", rule("A15")
            return None
        return "; ".join(_as_list(phase.get("species"))), self._source(phase["_material"], "species")

    def _dispersion(self, match, **_):
        phase = self._phase(match)
        if phase is None:
            return None
        if "dispersion" not in phase:
            return None
        return str(phase["dispersion"]).capitalize(), self._source(phase["_material"], "dispersion")

    def _structure(self, match, **_):
        phase = self._phase(match)
        if phase is None or "structure" not in phase:
            return None
        return str(phase["structure"]).capitalize(), self._source(phase["_material"], "structure")

    def _same_solvent(self, match, **_):
        # The sheet names the solvents of a phase for the series; a change per experiment
        # (solvent screening) cannot be expressed in it - then the generator asks.
        phase = self._phase(match)
        if phase is None or "solvents" not in phase:
            return None
        if len(self.cores) == 1:
            return "Yes", rule("A3")
        return "Yes", self._source(phase["_material"], "solvents")

    def _solvents(self, match, **_):
        # Empty list in the sheet: explicitly not known - the answer stays empty, nothing is inferred.
        phase = self._phase(match)
        if phase is None or "solvents" not in phase:
            return None
        return "; ".join(_as_list(phase.get("solvents"))), self._source(phase["_material"], "solvents")

    # ------------------------------------------------------------------
    # Reactions
    # ------------------------------------------------------------------

    def _fixed_reactions(self, match, **_):
        if not self.reactions:
            # "reactions: []" in the sheet: explicitly none; if the field is missing, it is asked.
            if "reactions" in self.sheet and self.sheet["reactions"] == []:
                return "", self._source(self.sheet)
            return None
        return ("; ".join(self.reaction_library_names.get(_norm(r["name"]), r["name"]) for r in self.reactions),
                self._source(self.reactions[0], "name"))

    def _reaction(self, match):
        return self.reaction_ids.get(_norm(match.group("reaction")))

    def _reaction_occurs(self, match, **_):
        reaction = self._reaction(match)
        if reaction is None:
            return None
        return "Yes", self._source(reaction, "name")

    def _reaction_location_kind(self, match, options, **_):
        reaction = self._reaction(match)
        if reaction is None:
            return None
        wanted = "Bulk" if reaction.get("in_phase") else "Surface" if reaction.get("at_interface") else None
        hits = [self._label(o) for o in options or [] if self._label(o).startswith(wanted or "\0")]
        if len(hits) != 1:
            return None
        return hits[0], self._source(reaction, "in_phase")

    def _reaction_location_phase(self, match, options, **_):
        reaction = self._reaction(match)
        if reaction is None or not reaction.get("in_phase"):
            return None
        hits = [self._label(o) for o in options or [] if f'"{reaction["in_phase"]}"' in self._label(o)]
        if len(hits) != 1:
            return None
        return hits[0], self._source(reaction, "in_phase")

    def _reaction_location_interface(self, match, options, **_):
        # The interface between the two phases the sheet names (at_interface: [A, B]).
        reaction = self._reaction(match)
        phases = _as_list((reaction or {}).get("at_interface"))
        if len(phases) != 2:
            return None
        wanted = {f'"{phases[0]} / {phases[1]} ', f'"{phases[1]} / {phases[0]} '}
        hits = [self._label(o) for o in options or [] if any(w in self._label(o) for w in wanted)]
        if len(hits) != 1:
            return None
        return hits[0], self._source(reaction, "at_interface")

    # ------------------------------------------------------------------
    # Tasks
    # ------------------------------------------------------------------

    def _free_tasks(self):
        """The sheet's tasks the generator creates as "further tasks". A task that determines a value
        is not one of them: the generator creates it for that value (the mass of the product, say),
        and the sheet entry gives it its name and equipment."""
        own = list(BUILT_IN_TASKS.values())
        # A task a value names with determined_by is also created by the generator through its value.
        named = {_norm(v["determined_by"]) for v in self.values + self.time_values if v.get("determined_by")}
        # Likewise a task that establishes an occurrence (section "occurrences").
        named |= {_norm(s["determined_by"]) for s in self.occurrence_statements if s.get("determined_by")}
        # Likewise a task that comes from its file (created_from_file, section "files").
        return [t for t in self.tasks.values()
                if _norm(t["name"]) not in map(_norm, own) and not t.get("determines") and _norm(t["name"]) not in named
                and not t.get("created_from_file") and not t.get("experiments")]

    def _task_in_this_experiment(self, task) -> bool:
        """Whether a sheet task exists where the current question stands: a task with "experiments" only in those
        (not on the series level), every other task everywhere."""
        if not task.get("experiments"):
            return True
        return self._key_experiment is not None and self._key_experiment in map(int, _as_list(task["experiments"]))

    def _experiment_tasks(self, match, **_):
        """The tasks that occurred only in this experiment - the sheet tasks with "experiments" naming it. When no
        task has the field, "none: experiment_tasks" answers (or the generator asks)."""
        own = [t for t in self.tasks.values() if t.get("experiments")]
        if not own:
            return self._none_answer("experiment_tasks", "")
        here = [t for t in own if int(match.group("exp")) in map(int, _as_list(t["experiments"]))]
        return "; ".join(t["name"] for t in here), self._source((here or own)[0], "experiments")

    def _later_task_names(self) -> set:
        """The sheet tasks that come into being only with a value, an occurrence or a file of an experiment
        (normalised names) - a task with "determines" or "created_from_file", or one a value or statement
        names under determined_by."""
        named = {_norm(v["determined_by"]) for v in self.values + self.time_values if v.get("determined_by")}
        named |= {_norm(s["determined_by"]) for s in self.occurrence_statements if s.get("determined_by")}
        named |= {_norm(t["name"]) for t in self.tasks.values() if t.get("determines") or t.get("created_from_file")}
        return named

    def _extra_tasks(self, match, **_):
        names = [t["name"] for t in self._free_tasks()]
        if not names:
            return None
        return "; ".join(names), self.default_source

    def _grouping_tasks(self, match, **_):
        parents = {t.get("part_of") for t in self.tasks.values() if t.get("part_of")}
        grouping = [p for p in parents if _norm(p) not in map(_norm, BUILT_IN_TASKS.values())]
        return "; ".join(sorted(grouping)), self.default_source

    def _task_parts(self, match, options, **_):
        name, _task = self._sheet_task(match.group("task"))
        parts = [t for t in self.tasks.values() if _norm(t.get("part_of", "")) == _norm(name) and self._task_in_this_experiment(t)]
        if not parts:
            # A fixed shell the sheet gives no parts has none (the shells always exist, even
            # empty): the sheet names the parts of every section with part_of.
            if _norm(name) in map(_norm, BUILT_IN_TASKS.values()) and self.tasks:
                return "", self.default_source
            return None
        # Only tasks that exist in the run. A task that only a value or a file creates may not exist here yet
        # (on the series level, when its values stand per experiment) or not in this experiment (rule 4a.4) -
        # it is placed where it comes into being, and is rightly missing here. If another task is
        # missing, the question stays open.
        if not options:
            return "; ".join(t["name"] for t in parts), self._source(parts[0], "part_of")
        later = self._later_task_names()
        labels = []
        for t in parts:
            label = self._option(options, t["name"])
            if label is None and _norm(t["name"]) not in later:
                return None
            if label is not None:
                labels.append(label)
        return "; ".join(labels), self._source(parts[0], "part_of")

    def _task_type(self, match, options, **_):
        _name, task = self._sheet_task(match.group("task"))
        if task is None or not task.get("type"):
            return None
        # "task" is cpo:Task itself - a section without a more precise class (like "Running the hydrogenation").
        wanted = "Task" if _norm(task["type"]) == "task" else f"{task['type']}Task"
        label = self._option(options, wanted)
        if label is None:
            return None
        return label, self._source(task, "type")

    def _task_equipment(self, match, options, **_):
        _name, task = self._sheet_task(match.group("task"))
        if task is None or "equipment" not in task:
            return self._none_answer("task_details", "")
        chosen = []
        for device in _as_list(task.get("equipment")):
            label = self._option(options, f"{device}SeriesSpecific")
            if label is None and self._key_experiment is not None:
                # A task of one experiment only (field "experiments") chooses among the devices of that experiment.
                label = self._option(options, f"{device}ExperimentSpecific{self._key_experiment}") or \
                    self._option(options, f"{device}ExperimentSpecific")
            if label is None:
                return None
            chosen.append(label)
        return "; ".join(chosen), self._source(task, "equipment")

    def _task_empties(self, match, options, **_):
        # What a task used up in an experiment: "empties" at the task, per experiment.
        # Without the field answered empty only with "none: emptied", otherwise the generator asks.
        _name, task = self._sheet_task(match.group("task"))
        marks = _as_list((task or {}).get("empties"))
        if not marks:
            return self._none_answer("emptied", "")
        number = int(match.group("exp"))
        chosen = []
        for mark in marks:
            if int(mark.get("experiment", 0)) != number:
                continue
            for container in _as_list(mark.get("containers")):
                label = self._option(options, f"{container}ExperimentSpecific{number}")
                if label is None:
                    return None
                chosen.append(label)
        return "; ".join(chosen), self._source(task, "empties")

    def _task_functions(self, match, options, **_):
        _name, task = self._sheet_task(match.group("task"))
        if task is None or "functions" not in task:
            return None
        if not task["functions"]:
            # functions: [] - explicitly no purpose of its own (a section that only summarizes;
            # it is asked only for what it does beyond its parts).
            return "", self._source(task, "functions")
        labels = [self._option(options, function) for function in _as_list(task["functions"])]
        if None in labels:
            return None
        return "; ".join(labels), self._source(task, "functions")

    def _task_performers(self, match, options, **_):
        # Only who stands at the task in the sheet - not inferred from experimenter/creator.
        _name, task = self._sheet_task(match.group("task"))
        if task is None or not task.get("performers"):
            return None
        labels = [self._option(options, p) for p in _as_list(task["performers"])]
        return None if None in labels else ("; ".join(labels), self._source(task, "performers"))

    def _task_description(self, match, required, **_):
        name, task = self._sheet_task(match.group("task"))
        if task is not None and task.get("description"):
            return str(task["description"]), self._source(task, "description")
        return None if required else self._none_answer("task_details", "")

    def _task_inputs(self, match, options, required, **_):
        # The input values of a calculation in the experiment: per entry "<quantity> <place>", such as
        # "Mass Product_Phase" - if exactly one option fits (quantity first, the place in it), it holds.
        _name, task = self._sheet_task(match.group("task"))
        if task is not None and "inputs" in task and not task["inputs"] and not required:
            return "", self._source(task, "inputs")
        if task is None or not task.get("inputs"):
            return None if required else self._none_answer("task_details", "")
        chosen = []
        for entry in _as_list(task["inputs"]):
            quantity, *places = str(entry).split()
            # A time of a task is offered as "Task <name> <Quantity> Reference 1 ..." - the quantity after the task.
            task_time = "task" + _norm("".join(places)) + _norm(quantity)
            hits = [self._label(o) for o in options or []
                    if (_norm(self._label(o)).startswith(_norm(quantity)) or _norm(self._label(o)).startswith(task_time))
                    and all(_norm(place) in _norm(self._label(o)) for place in places)]
            if len(hits) > 1:
                # "Mass Catalyst_Charge_Phase" also fits the mass of a substance in it ("Mass Palladium Phase
                # Catalyst ...") - without a substance named, the value of the phase itself is meant, the shortest option.
                shortest = min(len(_norm(h)) for h in hits)
                hits = [h for h in hits if len(_norm(h)) == shortest]
            if len(hits) != 1:
                return None
            chosen.append(hits[0])
        return "; ".join(chosen), self._source(task, "inputs")

    def _series_task_inputs(self, match, options, required, **_):
        # The input values of the series template: "inputs: []" at the task means none; the inputs of a
        # calculation are named by the sheet for the experiment, at the series "none: task_details" holds.
        _name, task = self._sheet_task(match.group("task"))
        if task is not None and "inputs" in task and not task["inputs"] and not required:
            return "", self._source(task, "inputs")
        return None if required else self._none_answer("task_details", "")

    def _performed_by_person(self, match, options, **_):
        # In the experiment: "performed by a person?" - yes if the sheet names performers.
        _name, task = self._sheet_task(match.group("task"))
        if task is None or not task.get("performers"):
            return None
        label = self._option(options, "Yes")
        return (label, self._source(task, "performers")) if label else None

    def _task_times(self, task, nr: int) -> dict | None:
        """{"start_time": value, "end_time": value} and the kind word of a sheet task's times in
        experiment nr - "times: {start, end, kind}" in a series with one experiment, or per
        experiment number ("times: {1: {...}, 2: {...}}")."""
        times = (task or {}).get("times")
        if not isinstance(times, dict):
            return None
        if nr in times:
            times = times[nr]
        elif not ({"start", "end"} & set(times)) or len(self.cores) != 1:
            return None
        values = {q: times[key] for key, q in (("start", "start_time"), ("end", "end_time")) if times.get(key)}
        return {"values": values, "kind": str(times.get("kind", "")).lower()} if values else None

    # ------------------------------------------------------------------
    # Times of tasks and occurrences, statements about occurrences
    # ------------------------------------------------------------------

    @staticmethod
    def _is_time_entry(entry) -> bool:
        """A value of the section "values" that is a time of a task (at: task:<name>) or of an
        occurrence (occurrence: k) - read by _collect_time_values, not as a value of a place."""
        return isinstance(entry, dict) and (str(entry.get("at", "")).startswith("task:")
                                            or entry.get("occurrence") not in (None, ""))

    def _collect_time_values(self) -> list:
        """The times of tasks and occurrences in "values": per entry its target - ("task", name) or
        ("occurrence", at, place, k) -, experiment (0: not given), quantity (start_time, end_time,
        duration, start_offset), evidence or reference by its kind, and its number among the values of the
        same quantity and kind (the second is "evidence:2")."""
        found, counts = [], {}
        for entry in _as_list(self.sheet.get("values")):
            if not self._is_time_entry(entry):
                continue
            at = str(entry["at"])
            if entry.get("occurrence") not in (None, ""):
                target = ("occurrence", at, entry.get("place"), int(entry["occurrence"]))
            else:
                target = ("task", _norm(at.split(":", 1)[1]))
            word = str(entry.get("kind") or "").lower()
            role, value_type = _VALUE_KINDS.get(word, (None, None))
            role = "none" if word == "none" else role
            nr = int(entry["experiment"]) if entry.get("experiment") not in (None, "") else 0
            key = (target, nr, entry.get("quantity"), role)
            index = counts[key] = counts.get(key, 0) + 1
            found.append({"target": target, "nr": nr, "quantity": entry.get("quantity"), "role": role,
                          "type": value_type, "reading": word, "index": index, "value": entry.get("value"),
                          "unit": entry.get("unit"), "lower": entry.get("lower"), "upper": entry.get("upper"),
                          "exact": entry.get("exact"), "determined_by": entry.get("determined_by"),
                          "document": entry.get("document"),
                          "sources": {field: self._source(entry, field) for field in
                                      ("value", "kind", "exact", "unit", "lower", "upper", "determined_by", "document")}})
        return found

    def _in_experiment(self, nr_of_value: int, nr: int) -> bool:
        # Without an experiment a time value holds only in a series with one experiment (like "times").
        return nr_of_value == nr or (nr_of_value == 0 and self.experiment_count == 1)

    def _times_of_task(self, name, task, nr: int):
        """The time values of a task in experiment nr - from "values" (at: task:<name>) and from the short
        form "times: {start, end, kind}" at the task. None when "times" has no kind to read it by."""
        values = [v for v in self.time_values if v["target"] == ("task", _norm(name)) and self._in_experiment(v["nr"], nr)]
        legacy = self._task_times(task, nr)
        if legacy:
            if legacy["kind"] not in _VALUE_KINDS:
                return None
            role, value_type = _VALUE_KINDS[legacy["kind"]]
            source = self._source(task, "times")
            for quantity, value in legacy["values"].items():
                if not any(v["quantity"] == quantity and v["role"] == role for v in values):
                    values.append({"quantity": quantity, "role": role, "type": value_type, "reading": legacy["kind"],
                                   "index": 1, "value": value, "unit": None, "lower": None, "upper": None, "exact": True,
                                   "determined_by": None, "document": None, "sources": dict.fromkeys(
                                       ("value", "kind", "exact", "unit", "lower", "upper", "determined_by", "document"), source)})
        return values

    def _unknown_times(self, matches, nr: int) -> tuple:
        """(quantities, source) of the section "unknown" for one target and experiment - nothing is known
        of these times."""
        entries = [u for u in _as_list(self.sheet.get("unknown")) if isinstance(u, dict) and matches(u)
                   and str(u.get("experiment")) == str(nr)]
        quantities = {_norm(q) for u in entries for q in _as_list(u.get("none"))}
        return quantities, (self._source(entries[0], "none") if entries else None)

    def _time_list(self, values, unknown: set, unknown_source, options, role, fallback_source):
        """A list "for which quantities is there evidence/reference" for the times of one task or
        occurrence: complete when the sheet names every quantity offered (with a value, or in
        "unknown"), otherwise only with none: further_values."""
        if values is None or any(v["role"] is None for v in values):
            return None
        named = {_norm(v["quantity"]) for v in values} | unknown
        complete = bool(options) and all(_norm(self._label(o)) in named for o in options)
        if not values and not complete:
            # Nothing in the sheet about these times: only "none: further_values" says that there are none.
            return self._none_answer("further_values", "")
        if not complete and "further_values" not in self.none:
            return None
        chosen = list(dict.fromkeys(v["quantity"] for v in values if v["role"] == role))
        labels = [self._option(options, quantity) for quantity in chosen]
        if None in labels:
            return None
        if chosen:
            source = "; ".join(dict.fromkeys(v["sources"]["value"] for v in values if v["role"] == role))
        else:
            source = unknown_source or "; ".join(dict.fromkeys(v["sources"]["kind"] for v in values)) or fallback_source
        if not complete:
            source += f"; nothing else: {self._nothing_else_source()}"
        return "; ".join(labels), source

    def _time_field(self, values, match, options):
        """One field of a time value (exists, type, timestamp, duration ...)."""
        if values is None:
            return None
        quantity, role, field = match.group("quantity"), match.group("role"), match.group("field")
        hits = [v for v in values if v["quantity"] == quantity and v["role"] == role and v["index"] == int(match.group("idx") or 1)]
        if len(hits) != 1:
            return None
        value = hits[0]
        source = value["sources"]["value"]
        if field == "exists":
            return "No", source
        if field == "type":
            label = self._option(options, value["type"]) if value["type"] else None
            return (label, value["sources"]["kind"]) if label else None
        if field == "value_type":
            label = self._option(options, "Instant" if quantity in ("start_time", "end_time") else "Duration")
            return (label, source) if label else None
        if field == "exactness":
            lower, upper = value["lower"] is not None, value["upper"] is not None
            if not (lower or upper) and value["value"] in (None, ""):
                return None
            wanted = ("Lower and upper bound" if lower and upper else "Lower bound" if lower else "Upper bound") \
                if lower or upper else "Exact value"
            label = self._option(options, wanted)
            return (label, value["sources"]["lower" if lower else "upper" if upper else "exact"]
                    if (lower or upper or value["exact"] is not None) else source) if label else None
        if field in ("lower_bound", "upper_bound"):
            bound = value[field.split("_")[0]]
            return (str(bound), value["sources"][field.split("_")[0]]) if bound is not None else None
        if field == "timestamp":
            return (str(value["value"]), source) if value["value"] not in (None, "") else None
        if field == "duration_value":
            return (_exact(value["value"]), source) if value["value"] not in (None, "") else None
        if field == "duration_unit":
            unit = value["unit"]
            label = (self._option(options, unit) or self._option(options, TIME_UNIT_SYMBOLS.get(str(unit), ""))) if unit else None
            return (label, value["sources"]["unit"]) if label else None
        if field == "source":
            return self._document_of(value)
        return None

    def _time_another(self, values, match):
        """A further value of the same time and kind: yes when the sheet names it; no when it names this
        time at all - it names every value it knows (like the values of a place)."""
        if values is None:
            return None
        quantity, role, index = match.group("quantity"), match.group("role"), int(match.group("idx"))
        here = [v for v in values if v["quantity"] == quantity and v["role"] == role]
        following = [v for v in here if v["index"] == index]
        if following:
            return "Yes", following[0]["sources"]["value"]
        if "further_values" in self.none:
            return self._none_answer("further_values", "No")
        if here:
            # The source of the statement itself: whoever names a time value names all they know.
            return "No", here[0]["sources"]["value"]
        return self._none_answer("further_values", "No")

    # --- Times of the tasks ---

    def _task_time_context(self, match):
        name, task = self._sheet_task(match.group("task"))
        nr = int(match.group("exp"))
        return name, task, nr, self._times_of_task(name, task, nr)

    def _task_time_list(self, match, options, **_):
        # The lists "for which quantities is there ..." of the times of a task; what is unknown stands in
        # "unknown" (at: <task>, experiment, none: [start_time, ...]).
        name, task, nr, values = self._task_time_context(match)
        # Under "unknown" with the name of the task - or, for a task the generator derives, with the
        # segment of its key (at: for-Task_Cooling_StartOffset_Evidence_1_ExperimentSpecific).
        names = {_norm(name), _norm(f"task:{name}"), _norm(match.group("task"))}
        unknown, unknown_source = self._unknown_times(
            lambda u: u.get("occurrence") in (None, "") and _norm(u.get("at")) in names, nr)
        return self._time_list(values, unknown, unknown_source, options, match.group("role"), self._source(task or {}, "times"))

    def task_times_named(self, key) -> set | None:
        """The time quantities of a task the sheet names for this experiment - with a value or under
        "unknown" (normed); None if the key is no list of task times."""
        match = next((p.fullmatch(key) for p, h in self._handlers
                      if getattr(h, "__name__", "") == "_task_time_list" and p.fullmatch(key)), None)
        if match is None:
            return None
        name, _task, nr, values = self._task_time_context(match)
        names = {_norm(name), _norm(f"task:{name}"), _norm(match.group("task"))}
        unknown, _source = self._unknown_times(lambda u: u.get("occurrence") in (None, "") and _norm(u.get("at")) in names, nr)
        return {_norm(v["quantity"]) for v in values or []} | unknown

    def stand_in(self, key, options) -> str | None:
        """For an exploratory run: what the sheet knows of a question it cannot answer completely - so far
        the list of the times of a task whose other times the sheet does not name yet. The start of the
        experimental procedure is required; an empty stand-in stopped the run before the empty values for its
        end and duration were written into the sheet. It stays a stand-in:
        the times not named still get their empty values in the sheet."""
        match = next((p.fullmatch(key) for p, h in self._handlers
                      if getattr(h, "__name__", "") == "_task_time_list" and p.fullmatch(key)), None)
        if match is None:
            return None
        values = self._task_time_context(match)[3]
        if not values or any(v["role"] is None for v in values):
            return None
        chosen = list(dict.fromkeys(v["quantity"] for v in values if v["role"] == match.group("role")))
        labels = [self._option(options, quantity) for quantity in chosen]
        return "; ".join(labels) if chosen and None not in labels else None

    def _task_time_field(self, match, options, **_):
        return self._time_field(self._task_time_context(match)[3], match, options)

    def _task_time_another(self, match, **_):
        return self._time_another(self._task_time_context(match)[3], match)

    def _time_sources(self, match, options, **_):
        # Where the times of a task that reads times come from (rule 4.7): "time_source" at the task.
        _name, task = self._sheet_task(match.group("task"))
        if task is None or "time_source" not in task:
            return None
        sources = task["time_source"]
        names = [s.get("source") if isinstance(s, dict) else s for s in _as_list(sources)]
        labels = [self._option(options, n) for n in names]
        return None if None in labels or not labels else ("; ".join(labels), self._source(task, "time_source"))

    def _time_source_detail(self, match, **_):
        _name, task = self._sheet_task(match.group("task"))
        if task is None or "time_source" not in task:
            return None
        details = [s.get("detail") for s in _as_list(task["time_source"]) if isinstance(s, dict) and s.get("detail")]
        detail = task.get("time_source_detail") or ", ".join(details)
        return str(detail or ""), self._source(task, "time_source")

    def _task_detail_list(self, match, options, required, **_):
        # Software and aims of a task, if the sheet names them at the task ("software: []" = none);
        # otherwise only "none: task_details".
        _name, task = self._sheet_task(match.group("task"))
        field = match.group("field")
        if task is None or field not in task:
            return None if required else self._none_answer("task_details", "")
        names = _as_list(task[field])
        experiment = re.match(r"series:1/experiment:(\d+)/", match.group(0))
        if experiment:
            # A reaction that does not take place in this experiment (a participant is missing there,
            # species_per_experiment) is no aim of the task in it.
            absent = self._absent_reactions(int(experiment.group(1)))
            names = [n for n in names if _norm(n) not in absent]
        if not names:
            return None if required else ("", self._source(task, field))
        labels = [self._option(options, n) or self._reaction_option(options, n) or self._transfer_option(options, n)
                  for n in names]
        return None if None in labels else ("; ".join(labels), self._source(task, field))

    def _transfer_option(self, options, name):
        """The one option that stands for a transfer written readably, "<species> from <phase> to <phase>"
        - the generator's option is "Transfer <species>-<type>-from-<a>-to-<b> <place> <scope>"."""
        readable = READABLE_TRANSFER.match(str(name).strip())
        if not readable:
            return None
        kind = re.escape(_norm(readable.group("type"))) if readable.group("type") else "[a-z]+"
        start = re.compile("transfer" + re.escape(_norm(readable.group("species"))) + kind + "from"
                           + re.escape(_norm(readable.group("a"))) + "to" + re.escape(_norm(readable.group("b"))))
        hits = [self._label(o) for o in options or [] if start.match(_norm(self._label(o)))]
        return hits[0] if len(hits) == 1 else None

    def _reaction_option(self, options, name):
        """The one option that stands for a reaction named as in the sheet (its name in the Reaction Library),
        whatever form the generator gives it (StoichiometricReaction 0001 SeriesSpecific)."""
        locals_ = [local for local, entry in self.reaction_ids.items() if _norm(entry["name"]) == _norm(name)]
        hits = [self._label(o) for o in options or [] for local in locals_ if local in _norm(self._label(o))]
        if not hits:
            # The generator offers a fixed reaction under its library name ("PBA formation, potassium
            # ferrocyanide, Ni"), the sheet names it with its ID too.
            library_name = self.reaction_library_names.get(_norm(name))
            hits = [self._label(o) for o in options or [] if library_name and _norm(self._label(o)) == _norm(library_name)]
        return hits[0] if len(hits) == 1 else None

    # --- Occurrences ---

    def _collect_occurrences(self) -> list:
        """The statements of the section "occurrences": per entry the things it names (kind, name as
        written, place of a transfer), the kinds it names with an empty list (nothing known of them),
        the experiments, how often, evidence or reference and of which type, and the task that knows it."""
        statements = []
        for position, entry in enumerate(_as_list(self.sheet.get("occurrences"))):
            if not isinstance(entry, dict):
                continue
            if any(field in entry and (entry[field] is None or (isinstance(entry[field], dict)
                                                                and None in entry[field].values()))
                   for field in OCCURRENCE_FIELDS):
                continue        # a scaffold that is still open (open_questions.py): answer nothing from it
            word = str(entry.get("kind") or "").lower()
            role, value_type = _VALUE_KINDS.get(word, (None, None))
            items, empty = [], set()
            for field, kind in OCCURRENCE_FIELDS.items():
                if field not in entry:
                    continue
                if kind == "transfer":
                    places = entry[field] or {}
                    if not places:
                        empty.add("transfer")
                    for place, names in (places.items() if isinstance(places, dict) else []):
                        if not _as_list(names):
                            empty.add(("transfer", _norm(place)))
                        items += [{"kind": kind, "name": str(n), "place": str(place)} for n in _as_list(names)]
                    continue
                if not _as_list(entry[field]):
                    empty.add(kind)
                items += [{"kind": kind, "name": str(n), "place": None} for n in _as_list(entry[field])]
            count = entry.get("count")
            statements.append({
                "position": position, "entry": entry, "items": items, "empty": empty,
                "experiments": experiments_of(entry.get("experiment"), self.experiment_count),
                "count": int(count) if isinstance(count, int) and not isinstance(count, bool) else
                         (int(count) if str(count).strip().isdigit() else None),
                "role": role, "type": value_type, "determined_by": entry.get("determined_by")})
        return statements

    def _item_is(self, item, kind, label, place=None) -> bool:
        """Whether a thing named in the sheet is the thing the generator calls `label` (at `place`)."""
        if item["kind"] != kind:
            return False
        if kind == "transfer":
            return (place is None or place_matches(item["place"], place)) and transfer_matches(item["name"], label)
        if kind == "interface":
            return _norm(label) in interface_forms(item["name"])
        if kind == "reaction":
            return _norm(label) == _norm(item["name"]) or \
                _norm(self.reaction_ids.get(_norm(label), {}).get("name", "")) == _norm(item["name"])
        return _norm(label) == _norm(item["name"])

    def _thing_of(self, match) -> tuple:
        """(kind, label, place) of the thing of an occurrence key."""
        if match.group("transfer"):
            return "transfer", match.group("transfer"), match.group("place")
        return match.group("simple"), match.group("label"), None

    def _statements_naming(self, kind, label, place, nr) -> list:
        return [s for s in self.occurrence_statements if nr in s["experiments"]
                and any(self._item_is(item, kind, label, place) for item in s["items"])]

    def _statement_source(self, statements, field) -> str:
        return "; ".join(dict.fromkeys(self._source(s["entry"], field) for s in statements))

    def _occurrence_list(self, match, options, **_):
        # About which phases, interfaces, reactions, energy fields - and at which places about transfers -
        # is anything known? Whoever names a kind names all known ones of that kind; "phases: []" says: nothing.
        nr, wanted = int(match.group("exp")), match.group("list")
        kind = "transfer" if wanted == "transfer_places" else OCCURRENCE_FIELDS[wanted]
        field = "transfers" if kind == "transfer" else wanted
        statements = [s for s in self.occurrence_statements if nr in s["experiments"]
                      and (any(i["kind"] == kind for i in s["items"]) or kind in s["empty"])]
        if not statements:
            return self._none_answer("occurrences", "")
        labels = []
        absent = self._absent_reactions(nr) if kind == "reaction" else set()
        for statement in statements:
            for item in statement["items"]:
                if item["kind"] != kind:
                    continue
                if kind == "reaction" and _norm(item["name"]) in absent:
                    continue    # not created in this experiment - a participant is missing
                written = item["place"] if kind == "transfer" else item["name"]
                hits = [self._label(o) for o in options or []
                        if (place_matches(written, self._label(o)) if kind == "transfer"
                            else self._item_is(item, kind, self._label(o)))]
                if len(hits) != 1:
                    return None
                labels.append(hits[0])
        # In the order of the sheet: the generator creates the things in this order.
        source_field = "places" if kind == "transfer" and all("places" in (s["entry"].get("source") or {})
                                                            for s in statements if isinstance(s["entry"].get("source"), dict)) else field
        return "; ".join(dict.fromkeys(labels)), self._statement_source(statements, source_field)

    def _occurrence_transfers(self, match, options, **_):
        nr, place = int(match.group("exp")), match.group("place")
        statements = [s for s in self.occurrence_statements if nr in s["experiments"]
                      and any(i["kind"] == "transfer" and place_matches(i["place"], place) for i in s["items"])]
        labels = []
        for statement in statements:
            for item in statement["items"]:
                if item["kind"] != "transfer" or not place_matches(item["place"], place):
                    continue
                hits = [self._label(o) for o in options or [] if transfer_matches(item["name"], self._label(o))]
                if len(hits) != 1:
                    return None
                labels.append(hits[0])
        if not labels:
            return None
        return "; ".join(dict.fromkeys(labels)), self._statement_source(statements, "transfers")

    def _occurrence_count(self, match, **_):
        statements = self._statements_naming(*self._thing_of(match), int(match.group("exp")))
        counts = {s["count"] for s in statements}
        if not counts or None in counts:
            return None
        if len(counts) > 1:
            # Statements of different kinds may cover a different number of occurrences - planned once, occurred twice (the
            # second run of PBA experiment 2): the thing occurred as often as the largest count says, and each
            # occurrence k takes the statements whose count reaches it (_occurrence_roles). A 0 among them stays open.
            if 0 in counts:
                return None
            statements = [s for s in statements if s["count"] == max(counts)]
        return str(max(counts)), self._statement_source(statements, "count")

    def _occurrence_roles(self, match) -> list:
        """The statements about occurrence k of a thing, in their order in the sheet."""
        k = int(match.group("k"))
        return [s for s in self._statements_naming(*self._thing_of(match), int(match.group("exp")))
                if s["role"] and (s["count"] or 0) >= k or (s["count"] == 0 and k == 1)]

    def _occurrence_status_source(self, match, options, **_):
        statements = self._occurrence_roles(match)
        roles = {s["role"] for s in statements}
        if not roles or None in roles:
            return None
        wanted = "evidence and reference" if roles == {"evidence", "reference"} else roles.pop()
        label = self._option(options, wanted)
        return (label, self._statement_source(statements, "kind")) if label else None

    def _occurrence_status_field(self, match, options, **_):
        same_role = [s for s in self._occurrence_roles(match) if s["role"] == match.group("role")]
        index = int(match.group("idx") or 1)
        if len(same_role) < index:
            return None
        statement = same_role[index - 1]
        source = self._source(statement["entry"], "kind")
        field = match.group("field")
        if field == "exists":
            return "No", source
        wanted = "OccurrenceStatus" if field == "value_type" else statement["type"]
        label = self._option(options, wanted) if wanted else None
        return (label, source) if label else None

    def _occurrence_status_another(self, match, **_):
        same_role = [s for s in self._occurrence_roles(match) if s["role"] == match.group("role")]
        index = int(match.group("idx"))
        if len(same_role) >= index:
            return "Yes", self._source(same_role[index - 1]["entry"], "kind")
        if same_role:
            return "No", self._statement_source(same_role, "kind")
        return None

    def _occurrence_time_context(self, match):
        kind, label, place = self._thing_of(match)
        nr, k = int(match.group("exp")), int(match.group("k"))

        def is_this(at, at_place, occurrence) -> bool:
            if occurrence in (None, "") or int(occurrence) != k:
                return False
            prefix, _, name = str(at).partition(":")
            item = {"kind": prefix, "name": name, "place": at_place}
            return self._item_is(item, kind, label, place if at_place else None)

        values = [v for v in self.time_values if v["target"][0] == "occurrence"
                  and is_this(v["target"][1], v["target"][2], v["target"][3]) and self._in_experiment(v["nr"], nr)]
        unknown, unknown_source = self._unknown_times(lambda u: is_this(u.get("at"), u.get("place"), u.get("occurrence")), nr)
        return values, unknown, unknown_source

    def _occurrence_time_list(self, match, options, **_):
        values, unknown, unknown_source = self._occurrence_time_context(match)
        statements = self._occurrence_roles(match)
        return self._time_list(values, unknown, unknown_source, options, match.group("role"),
                               self._statement_source(statements, "kind") if statements else self.default_source)

    def _occurrence_time_field(self, match, options, **_):
        return self._time_field(self._occurrence_time_context(match)[0], match, options)

    def _occurrence_time_another(self, match, **_):
        return self._time_another(self._occurrence_time_context(match)[0], match)

    # --- the task behind a placeholder of a time or of an occurrence ---

    def _task_name_of_id(self, local) -> str | None:
        """The sheet name of a task from the local part of its ID (Cooling, Running_the_hydrogenation,
        Experimental_procedure, for_Pressure_..._Evidence_1_ExperimentSpecific)."""
        if local.startswith("for_File_"):
            # A task that comes from its file (Task_for_File_<file>_...): its name stands under "from" of
            # the entry of this file in "files".
            task = self._file_task(local)
            return task["name"] if task else None
        if local.startswith("for_"):
            name, task = self._sheet_task("for-" + local[4:])
            return name if task else None
        for name in list(self.tasks) + [_norm(n) for n in BUILT_IN_TASKS.values()]:
            if _norm(local) == name:
                return self.tasks[name]["name"] if name in self.tasks else \
                    next(n for n in BUILT_IN_TASKS.values() if _norm(n) == name)
        return None

    def _item_is_thing_id(self, item, thing) -> bool:
        """Whether a thing named in the sheet is the one in a placeholder ID ("Transfer_<label>_<place>",
        "PhasePairInterface_...", "StoichiometricReaction_0001", the ID of a phase or field)."""
        if item["kind"] == "transfer":
            if not thing.startswith("Transfer_"):
                return False
            for place in id_forms_of_place(item["place"]):
                if thing.lower().endswith("_" + place):
                    return transfer_matches(item["name"], thing[len("Transfer_"):-(len(place) + 1)])
            return False
        return self._item_is(item, item["kind"], thing)

    def _time_or_occurrence_determiner(self, key_segment):
        """The sheet task behind a placeholder for a time of a task, a time of an occurrence or the status
        of an occurrence - or None if the segment is none of these or the sheet does not say."""
        def task_named(name, sources):
            return self.tasks.get(_norm(name)) or {"name": name, "source": {"name": sources, "determines": sources}}

        def in_key_experiment(nr):
            # A placeholder is asked per experiment (series:1/experiment:2/task:for-...): only what the sheet
            # says for that experiment or for every one (0) - two experiments may name different tasks
            # (PBA: the run times of experiment 1 calculated, of experiment 2 a lower bound).
            # A key without an experiment (the series) takes every statement.
            return self._key_experiment is None or nr in (0, self._key_experiment)

        quantities = {"StartTime": "start_time", "EndTime": "end_time", "Duration": "duration", "StartOffset": "start_offset"}
        time_of_task = re.fullmatch(r"for-Task_(?P<task>.+)_(?P<q>StartTime|EndTime|Duration|StartOffset)_"
                                    r"(?P<role>Evidence|Reference)_(?P<idx>\d+)_ExperimentSpecific", key_segment)
        if time_of_task:
            name = self._task_name_of_id(time_of_task.group("task"))
            hits = [v for v in self.time_values if name and v["target"] == ("task", _norm(name)) and in_key_experiment(v["nr"])
                    and v["quantity"] == quantities[time_of_task.group("q")] and v["role"] == time_of_task.group("role").lower()
                    and v["index"] == int(time_of_task.group("idx")) and v["determined_by"]]
            named = {_norm(v["determined_by"]) for v in hits}
            return task_named(hits[0]["determined_by"], hits[0]["sources"]["determined_by"]) if len(named) == 1 else None

        time_of_occurrence = re.fullmatch(r"for-(?P<thing>.+?)_Occurrence(?:_(?P<k>\d+))?_(?P<q>StartTime|EndTime|Duration)_"
                                          r"(?P<role>Evidence|Reference)_(?P<idx>\d+)_ExperimentSpecific", key_segment)
        if time_of_occurrence:
            k = int(time_of_occurrence.group("k") or 1)
            hits = []
            for v in self.time_values:
                target = v["target"]
                if target[0] != "occurrence" or target[3] != k or not v["determined_by"] or not in_key_experiment(v["nr"]):
                    continue
                prefix, _, name = str(target[1]).partition(":")
                if (v["quantity"] == quantities[time_of_occurrence.group("q")] and v["role"] == time_of_occurrence.group("role").lower()
                        and v["index"] == int(time_of_occurrence.group("idx"))
                        and self._item_is_thing_id({"kind": prefix, "name": name, "place": target[2]}, time_of_occurrence.group("thing"))):
                    hits.append(v)
            named = {_norm(v["determined_by"]) for v in hits}
            return task_named(hits[0]["determined_by"], hits[0]["sources"]["determined_by"]) if len(named) == 1 else None

        status = re.fullmatch(r"for-(?P<thing>.+?)_Occurrence(?:_(?P<k>\d+))?(?:_Status)?_(?P<role>Evidence|Reference)_"
                              r"(?P<idx>\d+)_ExperimentSpecific", key_segment)
        if status:
            role, index, k = status.group("role").lower(), int(status.group("idx")), int(status.group("k") or 1)
            # The statements about this thing in this kind, in their order; the n-th determines the n-th value - of the
            # statements that reach occurrence k (planned once, assumed twice: the second has only the assumption).
            same = [s for s in self.occurrence_statements if s["role"] == role
                    and any(self._item_is_thing_id(item, status.group("thing")) for item in s["items"])
                    and (s["count"] is None or s["count"] >= k or (s["count"] == 0 and k == 1))]
            # The same order in each experiment - the statement that stands as the index-th in every experiment.
            chosen = {s["position"]: s for nr in range(1, self.experiment_count + 1) if in_key_experiment(nr)
                      for s in [x for x in same if nr in x["experiments"]][index - 1:index]}
            named = {_norm(s["determined_by"]) for s in chosen.values() if s["determined_by"]}
            if len(named) != 1:
                return None
            statement = next(iter(chosen.values()))
            return task_named(statement["determined_by"], self._source(statement["entry"], "determined_by"))
        return None

    def _covered_by_existing(self, match, options, **_):
        segment = match.group("task")
        if segment.startswith("for_File_"):
            # The placeholder of a file: the task its entry names under "from", if it exists
            # already - otherwise it is just coming into being from this file, a task of its own.
            task = self._file_task(segment)
            if task is None:
                return None
            from creation.task_functions import NOT_COVERED_YET
            label = self._option(options, task["name"]) or self._option(options, NOT_COVERED_YET)
            return (label, self._source(task, "created_from_file")) if label else None
        task = self._determiner_for(segment)
        if task is None:
            return None
        label = self._option(options, task["name"])
        if label is None and _norm(task["name"]) not in map(_norm, BUILT_IN_TASKS.values()):
            from creation.task_functions import NOT_COVERED_YET
            label = self._option(options, NOT_COVERED_YET)
        return (label, self._source(task, "determines")) if label else None

    def _determining_task_name(self, match, **_):
        task = self._determiner_for(match.group("task"))
        if task is None:
            return None
        return task["name"], self._source(task, "name")

    # ------------------------------------------------------------------
    # Values of the core file
    # ------------------------------------------------------------------

    def _collect_values(self) -> list:
        """The values of the section "values" of the sheet, each with the key place of its entity
        ("material:benzoicacidcharge/phase:benzoicacidphase", normalised names), its experiment
        (0: the whole series) and its number among the values of the same quantity and kind (the
        second value is "evidence:2"). Whether a value is evidence or reference, and of which type,
        its "kind" says; without it the generator asks. ELN values come into the section through
        workflow/prefill_sheet.py (interfaces/eln/sheet_values.py)."""
        values, counts = [], {}
        reactions = {_norm(r["name"]): r for r in self.reactions}
        devices = {_norm(d) for d in _as_list(self.sheet.get("devices")) if isinstance(d, str)}
        devices |= self._device_parts()    # also the parts (pump head, capillary)
        # The section "unknown" (close_sheet.py): per place and experiment the quantities of which
        # explicitly nothing is known - read like single entries with "kind: none".
        unknown = [dict({k: v for k, v in item.items() if k != "none"}, quantity=quantity, kind="none",
                        source={"kind": self._source(item, "none")})
                   for item in _as_list(self.sheet.get("unknown")) if isinstance(item, dict)
                   for quantity in _as_list(item.get("none"))]
        for entry in _as_list(self.sheet.get("values")) + unknown:
            if self._is_time_entry(entry):
                continue        # times of tasks and occurrences: _collect_time_values
            at, of = str(entry.get("at", "")), entry.get("of")
            extra = ""
            if ":" in at:
                # A place the generator derives - named in the sheet with its path
                # (environment:L109_Air/phase:L109_Air_GasPhase).
                place = self._place(at)
                species = dict(part.split(":", 1) for part in at.split("/")).get("species")
                extra = self._library_local_id(species) if species else ""
            elif _norm(at) in reactions and not of:
                place = f"reaction:{next(k for k, r in self.reaction_ids.items() if _norm(r['name']) == _norm(at))}"
            elif _norm(at) in reactions:
                species_id = self._species_id(of)
                place = self.participant_place(reactions[_norm(at)]["name"], species_id) if species_id else None
            elif _norm(at) in devices and "/" not in at:
                place = f"device:{_norm(at)}"
            else:
                material, _, phase = at.partition("/")
                place = f"material:{_norm(material)}" + (f"/phase:{_norm(phase)}" if phase else "")
                if of:
                    place += f"/species:{_norm(of)}"
                    species_id = self._species_id(of)
                    extra = _norm(species_id.split(":", 1)[-1]) if species_id else ""
            if place is None or not entry.get("quantity"):
                continue
            word = str(entry.get("kind") or "").lower()
            kind, value_type = _VALUE_KINDS.get(word, (None, None))
            # "kind: none": nothing is known of this quantity here - answers the lists, is not a value.
            kind = "none" if word == "none" else kind
            nr = int(entry["experiment"]) if entry.get("experiment") not in (None, "") else 0
            index = counts[(nr, place, entry["quantity"], kind)] = counts.get((nr, place, entry["quantity"], kind), 0) + 1
            number = entry.get("value")
            values.append({
                "nr": nr, "place": place, "quantity": entry["quantity"], "index": index, "anchor_extra": extra, "entry": entry,
                "value": number, "unit": entry.get("unit"), "column": entry.get("column"),
                "lower": entry.get("lower"), "upper": entry.get("upper"),
                "not_a_number": not isinstance(number, (int, float)) or isinstance(number, bool),
                "group": entry.get("group"), "kind": kind, "type": value_type, "reading": word,
                "steps": _as_list(entry.get("steps")), "executed_by": _as_list(entry.get("executed_by")),
                "exact": entry.get("exact"), "determined_by": entry.get("determined_by"), "document": entry.get("document"),
                "quantity_kind": entry.get("quantity_kind"),
                "path": _norm(f"{at}/{of}/{entry['quantity']}" if of else f"{at}/{entry['quantity']}"),
                "sources": {field: self._source(entry, field) for field in
                            ("value", "kind", "exact", "unit", "column", "lower", "upper", "determined_by", "steps",
                             "executed_by", "document", "quantity_kind")},
            })
        return values

    def _library_local_id(self, name) -> str:
        """The normalised local ID ("molecule0007") of the one Chemical Entity Library entry whose name
        is this one - how the generator names a substance in its placeholder tasks."""
        if not hasattr(self, "_names_to_ids"):
            self._names_to_ids = {}
            for entity in self.chemical_library.get("@graph", []):
                if entity.get("schema:name"):
                    self._names_to_ids.setdefault(_norm(entity["schema:name"]), []).append(entity["@id"])
        ids = self._names_to_ids.get(_norm(name), [])
        return _norm(ids[0].split(":", 1)[-1]) if len(ids) == 1 else ""

    def _species_id(self, name):
        """The Chemical Entity Library ID of a substance named in the sheet's phases."""
        for phase in self.phases.values():
            for species_id, species_name in phase["_species_ids"].items():
                if _norm(species_name) == _norm(name):
                    return species_id
        return None

    def participant_place(self, reaction_name, species_id):
        """The key place "reaction:<r>/participant:<p>" of a substance in a reaction of the sheet."""
        keys = [key for key, r in self.reaction_ids.items() if _norm(r["name"]) == _norm(reaction_name)]
        # A substance can take part in several reactions of the sheet (K4[Fe(CN)6] in both PBA reactions)
        # - all places per substance, the one of the named reaction is chosen.
        places = [p for p in self._participants().get(species_id, []) if keys and p.startswith(f"reaction:{keys[0]}/")]
        return places[0] if len(places) == 1 else None

    def _absent_reactions(self, nr: int) -> set:
        """The reactions of the sheet (their names, normed) that are not created in experiment nr: one of their
        participants does not occur in it (species_per_experiment)."""
        table = self.sheet.get("species_per_experiment") or {}
        absent_names = {_norm(name) for name, experiments in table.items() if name != "source" and nr not in _as_list(experiments)}
        if not absent_names:
            return set()
        species_ids = {e["@id"] for e in self._load_library("chemical_entity_library.jsonld").get("@graph", [])
                       if _norm(e.get("schema:name", "")) in absent_names}
        found = set()
        for species_id in species_ids:
            for place in self._participants().get(species_id, []):
                entry = self.reaction_ids.get(place.split("/")[0].split(":", 1)[1])
                if entry:
                    found |= {_norm(entry["name"])}
        return found

    def _participants(self) -> dict:
        """Chemical entity ID -> the places "reaction:<r>/participant:<p>" in the reactions of the sheet."""
        found = {}
        for entity in self._load_library("reaction_library.jsonld").get("@graph", []):
            reaction = (entity.get("cpo:participatesIn") or {}).get("@id", "") \
                if isinstance(entity.get("cpo:participatesIn"), dict) else ""
            part = entity.get("dcterms:hasPart")
            part = part.get("@id") if isinstance(part, dict) else None
            reaction_key = _norm(reaction.split(":", 1)[-1])
            if part and reaction_key in self.reaction_ids:
                found.setdefault(part, []).append(f"reaction:{reaction_key}/participant:{_norm(entity['@id'].split(':', 1)[-1])}")
        return found

    @staticmethod
    def _place(path) -> str:
        return "/".join(f"{level}:{_norm(name)}" for level, name in (s.split(":", 1) for s in path.split("/")))

    def _values_at(self, path, nr=None, quantity=None, kind=None) -> list:
        """The values at a key path (material:M[/phase:P[/species:S]], reaction:R/participant:P,
        device:D) - for one experiment (0: the series) or all, of one quantity and kind or all."""
        place = self._place(path)
        return [v for v in self.values if v["place"] == place and (nr is None or v["nr"] == nr)
                and (quantity is None or v["quantity"] == quantity) and (kind is None or v["kind"] == kind)]

    @staticmethod
    def _nr(match) -> int:
        return int(match.group("exp")) if match.group("exp") else 0

    def _listed(self, found, options, with_reading=False):
        """(answer, source) of a list "for which quantities ..." from the values found, or None."""
        labels = [self._option(options, q) for q in dict.fromkeys(v["quantity"] for v in found)]
        if None in labels:
            return None
        source = "; ".join(dict.fromkeys(v["sources"]["value"] for v in found))
        if with_reading:
            source += "; read as " + "; ".join(dict.fromkeys(f"{v['reading']}: {v['sources']['kind']}" for v in found))
        return "; ".join(labels), source + f"; nothing else: {self._nothing_else_source()}"

    def _covers(self, entries, options) -> bool:
        """Whether the sheet names every quantity offered here (with a value, or "kind: none") - then
        the list is complete without the sheet-wide "none: further_values"."""
        named = {_norm(v["quantity"]) for v in entries}
        return bool(options) and all(_norm(self._label(o)) in named for o in options)

    def _gate_series_values(self, match, options, **_):
        # Which quantities are known in the single experiments - "only these" is said by the sheet
        # (none: further_values), or it names every quantity offered.
        entries = [v for v in self._values_at(match.group("path")) if v["nr"] > 0]
        # A value of a device in the experiment stands under its path there (device:stirrer001/experiment:1) - it
        # says as well that the quantity is known in the experiments (the profile of the stirrer). Only real
        # values: what is called "none" there answers the lists of the experiment itself.
        here = self._place(match.group("path"))
        entries += [v for v in self.values if v["kind"] != "none" and re.fullmatch(re.escape(here) + r"/experiment:\d+", v["place"])]
        if any(v["kind"] is None for v in entries):
            return None
        found = [v for v in entries if v["kind"] != "none"]
        if "further_values" not in self.none and not self._covers(entries, options):
            return None
        if not found:
            return "", f"{self.none_source} (none: further_values)" if "further_values" in self.none else self._none_source_of(entries)
        return self._listed(found, options)

    def _nothing_else_source(self) -> str:
        """The source of "nothing else" at a place: the section "none" only where it says so itself
        (none: further_values) - otherwise the sheet, which names every value there. The source of
        "none" belongs to its categories (emptied, ...), not to every list."""
        return self.none_source if "further_values" in self.none else self.default_source

    def _none_source_of(self, entries) -> str:
        # Per source the quantities behind it - the line starts with the code letter of the source (rule
        # 2.10: "C: ... (flowrate, mass)"), not with the quantity.
        by_source = {}
        for v in entries:
            if v["kind"] == "none":
                by_source.setdefault(v["sources"]["kind"], []).append(v["quantity"])
        return "; ".join(f"{source} ({', '.join(dict.fromkeys(quantities))})" for source, quantities in by_source.items())

    def _gate_values(self, match, options, **_):
        # For which quantities there is a value of this kind - in the experiment, or for the whole series.
        at_place = self._values_at(match.group("path"), self._nr(match))
        if any(v["kind"] is None for v in at_place):
            return None
        complete = self._covers(at_place, options)
        if complete:
            self._complete_places.add((self._nr(match), self._place(match.group("path"))))
        elif at_place and "further_values" not in self.none:
            return None
        found = [v for v in at_place if v["kind"] == match.group("kind")]
        if not found:
            # The explicit statement "nothing else" (none: further_values) comes first.
            if "further_values" in self.none or not complete:
                return self._none_answer("further_values", "")
            return "", self._none_source_of(at_place) or self._nothing_else_source()
        return self._listed(found, options, with_reading=True)

    def _the_value(self, match, quantity=None):
        index = int(match.group("idx") or 1)
        quantity = quantity or match.group("quantity")
        found = [v for v in self._values_at(match.group("path"), self._nr(match), quantity, match.group("kind"))
                 if v["index"] == index]
        return found[0] if len(found) == 1 else None

    def _concentration_field(self, match, options, **_):
        # The concentration of a species (key without "concentration/").
        return self._value_field(match, options, quantity="concentration")

    def _another_concentration(self, match, **_):
        return self._another_value(match, quantity="concentration")

    def _another_value(self, match, quantity=None, **_):
        # "Another value?" - yes if the sheet names a further one; no only if it says "no further ones".
        value = self._the_value(match, quantity)
        if value is not None:
            return "Yes", value["sources"]["value"]
        if "further_values" not in self.none and (self._nr(match), self._place(match.group("path"))) in self._complete_places:
            # The source is that of the entries at this place (with code letters, rule 2.10).
            here = self._values_at(match.group("path"), self._nr(match))
            sources = "; ".join(dict.fromkeys(v["sources"]["kind" if v["kind"] == "none" else "value"] for v in here))
            return "No", f"{sources or self.default_source} - the sheet names every value here"
        return self._none_answer("further_values", "No")

    def _value_field(self, match, options, quantity=None, **_):
        value = self._the_value(match, quantity)
        if value is None:
            return None
        field = match.group("field")
        if field == "exists":
            return "No", rule("A9")
        if field == "quantity_kind":
            # Asked when the quantity allows several kinds (a concentration as a mass or a mole fraction,
            # rule 4.4): the field "quantity_kind" of the value, with or without the prefix.
            wanted = value.get("quantity_kind")
            if not wanted:
                return None
            wanted = _norm(str(wanted).split(":", 1)[-1])
            hits = [self._label(o) for o in options or [] if _norm(self._label(o).split(":", 1)[-1]) == wanted]
            return (hits[0], value["sources"]["quantity_kind"]) if len(hits) == 1 else None
        if field == "type":
            if value["type"] is None:
                return None
            label = self._option(options, value["type"])
            return (label, value["sources"]["kind"]) if label else None
        if field == "value_type":
            label = self._option(options, "ProcessVariable")
            return (label, rule("A9")) if label else None
        if field == "variable_kind":
            if value.get("steps"):
                label = self._option(options, "Profile")
                return (label, value["sources"]["steps"]) if label else None
            if value["column"]:
                label = self._option(options, "Series")
                return (label, value["sources"]["column"]) if label else None
            label = self._option(options, "Scalar")
            return (label, rule("A9")) if label else None
        if field == "series_column":
            # "<file>: <column>", as the generator offers the columns.
            label = self._option(options, value["column"]) if value["column"] else None
            return (label, value["sources"]["column"]) if label else None
        if field == "exactness":
            lower, upper = value["lower"] is not None, value["upper"] is not None
            if lower or upper:
                wanted = "Lower and upper bound" if lower and upper else "Lower bound" if lower else "Upper bound"
                label = self._option(options, wanted)
                return (label, value["sources"]["lower" if lower else "upper"]) if label else None
            if value["exact"] is not True:
                return None
            label = self._option(options, "Exact value")
            return (label, value["sources"]["exact"]) if label else None
        if field in ("lower_bound", "upper_bound"):
            bound = value[field.split("_")[0]]
            return (_exact(bound), value["sources"][field.split("_")[0]]) if bound is not None else None
        if field == "scalar_value":
            if value.get("not_a_number"):
                return None
            # Percent as the ELN states it - the generator takes "81.86 %" and stores 0.8186.
            number = _exact(value["value"]) + (" %" if value.get("unit") == "%" else "")
            return number, value["sources"]["value"]
        if field in ("scalar_unit", "bounds_unit"):
            # Rule 2.9: no unit without a unit. A symbol of the ELN (mg) is translated by A8, a QUDT unit
            # (DEG_C) was named by somebody in the sheet. Bounds (lower/upper) have a common unit
            # (bounds_unit, eLabFTW case study).
            unit = value.get("unit")
            if not unit:
                return None
            if unit in UNIT_SYMBOLS:
                label = self._option(options, UNIT_SYMBOLS[unit])
                return (label, f"{rule('A8')} '{unit}' ({value['sources']['unit']})") if label else None
            label = self._option(options, unit)
            return (label, value["sources"]["unit"]) if label else None
        if field == "source":
            return self._document_of(value)
        return None

    def _document_of(self, value):
        """The source of a planned or literature value (reference_source): the field "document"
        of the value (a DOI, a document), otherwise empty when the sheet says "none: reference_sources"."""
        if value.get("document"):
            return str(value["document"]), value["sources"]["document"]
        return self._none_answer("reference_sources", "")

    # ------------------------------------------------------------------
    # Device settings, files, samples, form
    # ------------------------------------------------------------------

    def _same_mode(self, match, options, **_):
        # An operation mode for the series ("FedBatch") or per experiment ({1: Batch, 2: Flow}).
        settings = self.device_settings.get(_norm(match.group("device")))
        if settings is None or settings.get("operation_mode") in (None, ""):
            return None
        label = self._option(options, "No" if isinstance(settings["operation_mode"], dict) else "Yes")
        return (label, self._source(settings, "operation_mode")) if label else None

    def _library_content(self, match, options, **_):
        """The content of a device that has held several (question library_content): the entry of
        device_settings names it under "content" - its ID, with or without the prefix."""
        settings = self.device_settings.get(_norm(match.group("device"))) or {}
        wanted = settings.get("content")
        if not wanted:
            return None
        wanted = _norm(str(wanted).split(":", 1)[-1])
        hits = [o for o in options or [] if _norm(self._label(o).split(":", 1)[-1]) == wanted]
        return (self._label(hits[0]), self._source(settings, "content")) if len(hits) == 1 else None

    def _operation_mode(self, match, options, **_):
        settings = self.device_settings.get(_norm(match.group("device"))) or {}
        mode = settings.get("operation_mode")
        experiment = match.group("exp") or match.group("exp2")
        if isinstance(mode, dict):
            mode = mode.get(int(experiment)) if experiment else None
        label = self._option(options, mode) if mode else None
        return (label, self._source(settings, "operation_mode")) if label else None

    def _profile_field(self, match, options, **_):
        """A question of a profile that is the value of an evidence or reference: its unit
        and quantity kind, and per step whether there is one more, its kind and its numbers - from "steps"
        at the value. What a step does not say is not known: the question takes "empty"."""
        value = self._the_value(match)
        if value is None or not value.get("steps"):
            return None
        source = value["sources"]["steps"]
        field, k = match.group("field"), match.group("k")
        if k is None:
            if field == "unit":
                unit = value.get("unit")
                label = self._option(options, UNIT_SYMBOLS.get(unit, unit)) if unit else None
                return (label, value["sources"]["unit"]) if label else None
            if field == "add_another_step":
                label = self._option(options, "Yes")
                return (label, source) if label else None
            return None
        steps, k = value["steps"], int(k)
        if field == "add_another_step":
            label = self._option(options, "Yes" if k <= len(steps) else "No")
            return (label, source) if label else None
        if k > len(steps):
            return None
        step = steps[k - 1]
        if field == "step_kind":
            label = self._option(options, str(step.get("kind", "")).capitalize())
            return (label, source) if label else None
        numbers = {"step_duration": step.get("duration"), "start_value_value": step.get("from"),
                   "end_value_value": step.get("to"), "hold_value_value": step.get("value"),
                   "change_rate_value": step.get("change_rate")}
        if field in numbers:
            return ("" if numbers[field] is None else _exact(numbers[field])), source
        if field == "change_rate_unit":
            label = self._option(options, step.get("change_rate_unit")) if step.get("change_rate_unit") else None
            return (label, source) if label else None
        return None

    def _profiles_run_by(self, task_name, nr) -> list:
        """The profile values of this level (series 0, or experiment nr) whose "executed_by" names this task.
        A value of a device in an experiment names the experiment in its place (device:stirrer001/experiment:1)."""
        def level(v):
            found = re.search(r"/experiment:(\d+)", v["place"])
            return v["nr"] or (int(found.group(1)) if found else 0)
        return [v for v in self.values if v.get("steps") and level(v) == nr
                and _norm(task_name) in {_norm(t) for t in v["executed_by"]}]

    def _executes_profile(self, match, options, **_):
        # The profile names the tasks that execute it ("executed_by: [Stirring]") - as the value names its
        # task (determined_by) and the file its own (from). A task that names no profile executes none,
        # as soon as the sheet names profiles (values with "steps").
        name, _task = self._sheet_task(match.group("task"))
        nr = int(match.group(1).split(":")[1].rstrip("/")) if match.group(1) else 0
        runs = self._profiles_run_by(name, nr)
        profiles = [v for v in self.values if v.get("steps")]
        if not runs and not profiles:
            return self._no_profile(match)
        label = self._option(options, "Yes" if runs else "No")
        source = runs[0]["sources"]["executed_by"] if runs else "; ".join(dict.fromkeys(v["sources"]["steps"] for v in profiles))
        return (label, source) if label else None

    def _which_profile(self, match, options, **_):
        name, _task = self._sheet_task(match.group("task"))
        nr = int(match.group("exp")) if match.group("exp") else 0
        runs = self._profiles_run_by(name, nr)
        if len(runs) != 1:
            return None
        value = runs[0]
        # The reference is named after its actual: "<quantity>_<device>_Reference_<n>_<level>" (rule 1.6) - at a
        # phase "<quantity>_Phase_<phase>_Reference_<n>_<level>" (the drying profile of the
        # eLabFTW case study).
        device = value["place"].split("/")[0].split(":", 1)[-1]
        phase = value["place"].split("/")[-1].split(":", 1)[-1]
        role = "Reference" if value["kind"] == "reference" else "Evidence"
        for owner in (device, f"Phase {phase}"):
            wanted = _norm(f"{value['quantity']} {owner} {role} {value['index']}")
            hits = [self._label(o) for o in options or [] if _norm(self._label(o)).startswith(wanted)
                    and not _norm(self._label(o))[len(wanted):][:1].isdigit()]
            if len(hits) == 1:
                return hits[0], value["sources"]["executed_by"]
        return None

    def _file_level(self, file) -> str:
        return str(file.get("experiment") or "")

    def _task_files(self, match, options, **_):
        # Which (further) files the task produced: those whose entry in "files" names it under "from",
        # on its level. Only if every file offered has its origin in the sheet; a task that comes from
        # its file has it already (generated_by_task).
        if not self.files:
            return None
        name, task = self._sheet_task(match.group("task"))
        offered = [self._label(o) for o in options or []]
        entries = [(label, self.files.get(_norm(label))) for label in offered]
        if any(entry is None or "from" not in entry for _label, entry in entries):
            return None
        chosen = [] if (task or {}).get("created_from_file") else [
            label for label, entry in entries
            if entry["from"] and _norm(entry["from"]) == _norm(name) and self._file_level(entry) == (match.group("exp") or "")]
        return "; ".join(chosen), "; ".join(dict.fromkeys(self._source(e, "from") for _l, e in entries)) or self.default_source

    def _file_from_task(self, match, options, **_):
        # The generator asks "produced by a task?" before there are tasks: yes only if the file brings
        # its task along (created_from_file) - a task of the procedure names its files itself later.
        entry = self.files.get(_norm(match.group("file")))
        if entry is None or "from" not in entry:
            return None
        task = self.tasks.get(_norm(entry["from"] or ""))
        brings = bool(entry["from"]) and bool(task and task.get("created_from_file"))
        label = self._option(options, "Yes" if brings else "No")
        return (label, self._source(entry, "from")) if label else None

    def _file_which_task(self, match, options, **_):
        # The same task as an earlier file with the same "from" - otherwise a new one.
        entry = self.files.get(_norm(match.group("file")))
        if entry is None or not entry.get("from"):
            return None
        earlier = [f for f in self.files.values() if f is not entry and _norm(f.get("from") or "") == _norm(entry["from"])]
        hits = [self._label(o) for o in options or []
                if any(_norm(f"File_{f['name']}") in _norm(self._label(o)) for f in earlier)]
        label = hits[0] if len(hits) == 1 else self._option(options, "Describe a new task")
        return (label, self._source(entry, "from")) if label else None

    def _file_task_type(self, match, options, **_):
        entry = self.files.get(_norm(match.group("file"))) or {}
        task = self.tasks.get(_norm(entry.get("from") or ""))
        if not task or not task.get("type"):
            return None
        label = self._option(options, "Task" if _norm(task["type"]) == "task" else f"{task['type']}Task")
        return (label, self._source(task, "type")) if label else None

    def _file_task_name(self, match, **_):
        _name, task = self._sheet_task(match.group("task"))
        return (task["name"], self._source(task, "name")) if task else None

    def _file_type(self, match, options, **_):
        # "type: Image" at the file - the option may carry the class name (cpo:Image).
        entry = self.files.get(_norm(match.group("file"))) or {}
        if not entry.get("type"):
            return None
        label = self._option(options, entry["type"]) or self._option(options, f"cpo:{entry['type']}")
        return (label, self._source(entry, "type")) if label else None

    def _file_creator(self, match, options, **_):
        # "creator: Congjian Lin" (a person of the People Library, by name or ID) or "creator: ''" - none or not
        # known.
        entry = self.files.get(_norm(match.group("file"))) or {}
        if "creator" not in entry:
            return None
        creator = str(entry["creator"] or "").strip()
        if match.group("what") == "kind":
            label = self._option(options, "Person" if creator else "No person/unknown")
        else:
            wanted = creator.split(":", 1)[-1]
            label = self._option(options, wanted) if creator else None
        return (label, self._source(entry, "creator")) if label else None

    def _stream_of_crossing(self, crossing):
        """(stream, end) of a port crossing key '<stream>-<port>': the stream of the sheet whose name starts it, and
        whether the port is its from or its to end."""
        for material in self.materials.values():
            if not self._is_stream(material) or not _norm(crossing).startswith(_norm(material["name"])):
                continue
            port = _norm(crossing[len(material["name"]) + 1:])
            for end in ("to", "from"):
                target = material.get(end)
                if target and target != "outside" and port.startswith(_norm(target)):
                    return material, end
        return None, None

    def _phase_option(self, options, phase):
        # The options name a phase as 'SolidPhase "Wood_Phase"'.
        hits = [self._label(o) for o in options or [] if f'"{_norm(phase)}"' in _norm_quoted(self._label(o))]
        return hits[0] if len(hits) == 1 else self._option(options, phase)

    def _crossing_phase(self, match, options, **_):
        # "to_phase: Wood_Phase" at the stream: the phase inside the device it enters. A stream of several
        # phases crosses per phase (key '<stream>-<port>-<stream phase>'): then per stream phase,
        # "to_phase: {Outlet_Solid_Phase: Product_Solid_Phase}". A port that opens into another device asks for the phase
        # there as well (opens_into_phase): "to_opens_into", if given - otherwise to_phase answers both.
        material, end = self._stream_of_crossing(match.group("crossing"))
        field = f"{end}_opens_into" if match.group("question") == "opens_into_phase" and material is not None and material.get(f"{end}_opens_into") else f"{end}_phase"
        if material is None or not material.get(field):
            return None
        wanted = material[field]
        if isinstance(wanted, dict):
            hits = [v for k, v in wanted.items() if k != "source" and _norm(match.group("crossing")).endswith(_norm(k))]
            if len(hits) != 1:
                return None
            wanted = hits[0]
        label = self._phase_option(options, wanted)
        return (label, self._source(material, field)) if label else None

    def _crossing_stream_phases(self, match, options, **_):
        material = self._material(match)
        if material is None or "crossing_phases" not in material:
            return None
        labels = [self._phase_option(options, p) for p in _as_list(material["crossing_phases"])]
        return None if None in labels else ("; ".join(labels), self._source(material, "crossing_phases"))

    def _reaction_entry(self, match):
        """The sheet's entry of the reaction or of the elementary reaction the key names."""
        if match.groupdict().get("reaction"):
            return self.reaction_ids.get(_norm(match.group("reaction")))
        wanted = _norm(match.groupdict().get("elementary") or "")
        for reaction in self.reactions:
            for entry in _as_list(reaction.get("elementary")):
                if _norm(entry.get("name")) == wanted or _norm(entry.get("name")).endswith(wanted) or wanted.endswith(_norm(entry.get("name"))):
                    return entry
        return None

    def _participant_transfer(self, match, options, prompt="", **_):
        # "transfers: [{participant: Hydrogen, phase: Liquid_Phase, type: Adsorption}]" at the reaction or at one of
        # its elementary reactions. The participant is named by its species - the end of the
        # participant's ID, or the species the question names.
        entry = self._reaction_entry(match)
        if entry is None:
            return None
        participant = _norm(match.group("participant"))
        hits = [t for t in _as_list(entry.get("transfers")) if isinstance(t, dict) and t.get("participant") and
                (participant.endswith(_norm(t["participant"])) or f" for {str(t['participant']).lower()}?" in str(prompt).lower())]
        if len(hits) != 1:
            return None
        transfer = hits[0]
        if match.group("field") == "phase":
            label = self._phase_option(options, transfer.get("phase") or "")
        else:
            wanted = str(transfer.get("type") or "")
            label = self._option(options, wanted) or self._option(options, f"cpo:{wanted}")
        return (label, self._source(transfer, match.group("field").replace("transfer_", ""))) if label else None

    def _elementary_location(self, match, options, **_):
        # "elementary: [{name: ..., at_interface: [Catalyst_Phase, Liquid_Phase]}]".
        entry = self._reaction_entry(match)
        if entry is None:
            return None
        field = match.group("field")
        if field == "kind":
            wanted = "interface" if entry.get("at_interface") else "phase" if entry.get("in_phase") else None
            label = next((self._label(o) for o in options or [] if wanted and wanted in self._label(o).lower()), None)
            return (label, self._source(entry, "at_interface" if wanted == "interface" else "in_phase")) if label else None
        if field == "phase":
            label = self._phase_option(options, entry.get("in_phase") or "") if entry.get("in_phase") else None
            return (label, self._source(entry, "in_phase")) if label else None
        phases = [_norm(p) for p in _as_list(entry.get("at_interface"))]
        if len(phases) != 2:
            return None
        hits = [self._label(o) for o in options or [] if all(f'"{p}' in _norm_quoted(self._label(o)) or p in _norm(self._label(o))
                                                             for p in phases)]
        return (hits[0], self._source(entry, "at_interface")) if len(hits) == 1 else None

    def _occurrence_status_document(self, match, options, **_):
        # "document: <DOI>" at an occurrence statement of kind planned or literature; without it the
        # sheet says "none: reference_sources".
        same_role = [s for s in self._occurrence_roles(match) if s["role"] == "reference"]
        index = int(match.group("idx") or 1)
        if len(same_role) < index:
            return None
        entry = same_role[index - 1]["entry"]
        if entry.get("document"):
            return str(entry["document"]), self._source(entry, "document")
        return self._none_answer("reference_sources", "")

    def _occupation_entries(self, interface=None):
        entries = [e for e in _as_list(self.sheet.get("occupation_states")) if isinstance(e, dict)]
        return [e for e in entries if interface is None or _norm(e.get("interface")) == _norm(interface)]

    def _occupation_state(self, match):
        """The entry of occupation_states the key names: its interface, and its name as the generator writes it
        into the key (slugify - "cat(H)" is catH, "cat-H" cat-H)."""
        from helpers.identifiers import slugify
        hits = [e for e in self._occupation_entries(match.group("interface")) if slugify(e.get("name", "")) == match.group("state")]
        return hits[0] if len(hits) == 1 else None

    def _occupation_names(self, match, required, **kwargs):
        # The names of the occupation states at this interface - '' none - once the sheet has the section; without
        # it, "none: interfaces".
        if "occupation_states" not in self.sheet:
            return self._none_list("interfaces")(match, required=required, **kwargs)
        entries = self._occupation_entries(match.group("interface"))
        if not entries:
            return "", self._source(self.sheet, "occupation_states")
        return "; ".join(str(e["name"]) for e in entries), self._source(entries[0], "name")

    def _occupation_field(self, match, options, **_):
        entry = self._occupation_state(match)
        if entry is None:
            return None
        field = match.group("field")
        if field == "target_interface":
            pair = [_norm(p) for p in _as_list(entry.get("pair"))]
            if not pair:
                label = self._option(options, "Whole interface")
            else:
                hits = [self._label(o) for o in options or [] if all(p in _norm(self._label(o)) for p in pair)]
                label = hits[0] if len(hits) == 1 else None
            return (label, self._source(entry, "pair")) if label else None
        if field == "is_free_site":
            return self._option(options, "No" if entry.get("occupied_by") else "Yes"), self._source(entry, "occupied_by")
        if field == "has_bound_to":
            return self._option(options, "Yes" if entry.get("bound_to") else "No"), self._source(entry, "bound_to")
        wanted = str(entry.get("sorption") or "")
        label = (self._option(options, wanted) or self._option(options, f"cpo:{wanted}")) if wanted else None
        return (label, self._source(entry, "sorption")) if label else None

    def _occupation_pick(self, match, options, **_):
        # A candidate of the interface by its label, otherwise the search in the Chemical Entity Library.
        entry = self._occupation_state(match)
        if entry is None or not entry.get(match.group("role")):
            return None
        label = self._option(options, entry[match.group("role")]) or \
            self._option(options, "Something else (search the chemical entity library)")
        return (label, self._source(entry, match.group("role"))) if label else None

    def _occupation_search(self, match, options, **_):
        # The search by name (identifier_field "Name", identifier_value the name of the entry).
        entry = self._occupation_state(match)
        if entry is None or not entry.get(match.group("role")):
            return None
        if match.group("what") == "field":
            label = self._option(options, "Name")
            return (label, self._source(entry, match.group("role"))) if label else None
        return str(entry[match.group("role")]), self._source(entry, match.group("role"))

    def _occupation_known(self, match, options, **_):
        # "library: [Adiponitrile_Pt_FreeSite]" at the entry: the placeholder of the Reaction Library is this state.
        wanted = _norm(match.group("library"))
        hits = [e for e in self._occupation_entries() if any(_norm(x).endswith(wanted) for x in _as_list(e.get("library")))]
        if len(hits) != 1:
            return None
        label = self._option(options, hits[0]["name"])
        return (label, self._source(hits[0], "library")) if label else None

    def _reference_column(self, match, options, **_):
        entry = self.files.get(_norm(match.group("file"))) or {}
        label = self._option(options, entry["reference_column"]) if entry.get("reference_column") else None
        return (label, self._source(entry, "reference_column")) if label else None

    def _sample_materials(self, match, options, **_):
        # Samples stand at their material ("sample_of: Material_In_Vessel"); if none names one,
        # "none: samples" holds.
        samples = [m for m in self.materials.values() if m.get("sample_of")]
        if not samples:
            return self._none_answer("samples", "")
        labels = [self._option(options, m["name"]) for m in samples]
        return None if None in labels else ("; ".join(labels), self._source(samples[0], "sample_of"))

    def _sample_of(self, match, options, **_):
        material = self._material(match)
        if not material or not material.get("sample_of"):
            return None
        label = self._option(options, material["sample_of"])
        return (label, self._source(material, "sample_of")) if label else None

    def _on_sample(self, match, options, **_):
        # "on_sample: Sample_In_Vial" - the task worked on the sample; "on_sample: ''" on the material itself.
        _name, task = self._sheet_task(match.group("task"))
        if task is None or "on_sample" not in task:
            return None
        from creation.task_functions import NOT_ON_A_SAMPLE
        label = self._option(options, task["on_sample"] or NOT_ON_A_SAMPLE)
        return (label, self._source(task, "on_sample")) if label else None

    def _observes(self, match, options, **_):
        # "observes: [Liquid_Phase, RDY_Add_Stream, vessel001]" - phases, materials or devices at which an
        # observation was made (sosa:hasFeatureOfInterest); without the field "none" only with
        # none: task_details. A device is called in the choice with its level ("vessel001 ExperimentSpecific 1").
        _name, task = self._sheet_task(match.group("task"))
        if task is None or "observes" not in task:
            return self._none_answer("task_details", "")
        level = f"ExperimentSpecific {match.group('exp')}" if match.group("exp") else "SeriesSpecific"
        labels = [self._option(options, thing) or self._option(options, f"{thing} {level}") for thing in _as_list(task["observes"])]
        if None in labels:
            return None
        return "; ".join(labels), self._source(task, "observes")

    def _form(self, match, options, **_):
        phase = self._phase(match)
        if phase is None or not phase.get("form"):
            return None
        label = self._option(options, phase["form"])
        return (label, self._source(phase["_material"], "form")) if label else None

    # ------------------------------------------------------------------
    # Lists "which quantities / another one?" - empty only if the sheet says "none"
    # ------------------------------------------------------------------

    def _gate(self, match, **_):
        return self._none_answer("further_values", "")

    def _no_other_value(self, match, **_):
        return self._none_answer("further_values", "No")

    def _no_profile(self, match, **_):
        return self._none_answer("profiles", "No")


if __name__ == "__main__":
    import sys
    if "--rules" in sys.argv:
        for number, text in RULES.items():
            print(f"{number:<5}{text}")
