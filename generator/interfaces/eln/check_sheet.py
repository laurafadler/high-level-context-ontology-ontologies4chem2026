"""
Check a setup sheet against its schema (interfaces/eln/sheet_schema.yaml) - without running the
generator.

Reports, in the terms of the sheet:
- missing: a required field that is empty, also under a condition that follows from the sheet
  itself (a solid phase needs its structure, an assumption its description, a calculation its
  inputs, the experimental procedure its times, a value its reading and - a number - its unit);
- not found: a name that does not point at anything - a device, person, substance, reaction,
  function, task, phase, unit or place of a value that the libraries, the ontology or the sheet
  do not know, or an input of a calculation that is no value of the sheet;
- not allowed: a value outside the allowed ones, also a function the class of a task (its 'type') does
  not offer (cpo:offersFunction), or determined_by naming a task the generator creates itself (only the
  planning, and only of planned values);
- unknown field: a field the schema does not know (a typo, or a field the adapter would ignore);
- warning (exit code 0): a task name without a gerund (rule 1.7), and a suggestion - a fixed reaction of
  the Reaction Library the sheet does not name, all of whose reactants stand in one of its phases.

What only the generator can decide (whether it needs the functions of a task, say - it derives
many itself) is not checked here; an exploratory run shows it (generator/workflow/isolated_run.py).

Usage (from the repository root):
    python generator/interfaces/eln/check_sheet.py projects/<crate_identifier>/setup.yaml
    python generator/interfaces/eln/check_sheet.py projects/pba_synthesis/setup.yaml
Exit code 0 when nothing is reported.
"""
import argparse
import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import path_definitions  # noqa: E402

SCHEMA_PATH = Path(__file__).resolve().parent / "sheet_schema.yaml"

# The tasks the generator creates itself - the sheet may name them to give them something.
BUILT_IN_TASK_NAMES = ("Experimental procedure", "Planning the series", "Establishing the values",
                       "Preparation", "Main operation", "Work-up")


def _norm(text) -> str:
    return "".join(c for c in str(text).lower() if c.isalnum())


def _as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _empty(value) -> bool:
    return value is None or value == "" or value == [] or value == {}


class SheetCheck:
    def __init__(self, sheet_path: Path):
        self.sheet_path = Path(sheet_path)
        self.sheet = yaml.safe_load(self.sheet_path.read_text(encoding="utf-8")) or {}
        self.schema = yaml.safe_load(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.findings = []           # (kind, place, text)
        self.none = set(_as_list((self.sheet.get("none") or {}).get("categories")))
        self._known = {}

    # ------------------------------------------------------------------
    # What exists
    # ------------------------------------------------------------------

    def known(self, kind: str) -> set:
        """Normalised names of everything a reference of this kind may point at."""
        if kind not in self._known:
            self._known[kind] = getattr(self, f"_known_{kind}")()
        return self._known[kind]

    @staticmethod
    def _graph(path: Path) -> list:
        from helpers.library_files import read_library
        return read_library(path).get("@graph", [])

    def _known_device(self) -> set:
        return {_norm(e["@id"].split(":", 1)[-1]) for path in path_definitions.DEVICE_LIBRARY_PATHS
                for e in self._graph(path) if e.get("@id", "").startswith("device:")}

    def _known_person(self) -> set:
        found = set()
        for entity in self._graph(path_definitions.PEOPLE_LIBRARY_PATH):
            if "schema:Person" in _as_list(entity.get("@type")):
                found |= {_norm(entity["@id"].split(":", 1)[-1]), _norm(entity.get("schema:name", ""))}
        return found

    def _known_reaction(self) -> set:
        # The name or the ID of a reaction (with and without "reaction:"), as the adapter accepts it.
        known = set()
        for e in self._graph(path_definitions.REACTION_LIBRARY_PATH):
            if e.get("schema:name"):
                known.add(_norm(e["schema:name"]))
            types = e.get("@type") if isinstance(e.get("@type"), list) else [e.get("@type")]
            if {"cpo:StoichiometricReaction", "cpo:LumpedReaction"} & set(types):
                known |= {_norm(e["@id"]), _norm(e["@id"].split(":", 1)[-1])}
        return known

    CPO = "http://www.semanticweb.org/lf576/ontologies/2026/7/ChemicalProcessOntology#"

    def _cpo_graph(self):
        if not hasattr(self, "_cpo"):
            import rdflib
            self._cpo = rdflib.Graph()
            self._cpo.parse(data=path_definitions.CPO_ONTOLOGY.read_text(encoding="utf-8"), format="xml")
        return self._cpo

    def _known_function(self) -> set:
        import rdflib
        graph = self._cpo_graph()
        return {_norm(str(s).split("#")[-1]) for s in graph.subjects(rdflib.RDF.type, rdflib.URIRef(self.CPO + "Function"))}

    def _offered_functions(self, task_class: str):
        """The functions a task of this CPO class can realize, normed - as creation/task_functions.py:
        offered_functions decides it: up the class hierarchy to the first class that declares
        cpo:offersFunction, then every function at or below those branches (cpo:hasBroaderFunction).
        None if the class is not in the CPO or nothing is declared (the generator then offers every function)."""
        import rdflib
        graph, cpo = self._cpo_graph(), self.CPO
        start = rdflib.URIRef(cpo + task_class)
        if (start, rdflib.RDF.type, rdflib.OWL.Class) not in graph:
            return None
        roots, seen, pending = set(), set(), [start]
        while pending:
            cls = pending.pop(0)
            if cls in seen:
                continue
            seen.add(cls)
            declared = set(graph.objects(cls, rdflib.URIRef(cpo + "offersFunction")))
            if declared:
                roots |= declared
                continue
            pending.extend(o for o in graph.objects(cls, rdflib.RDFS.subClassOf) if isinstance(o, rdflib.URIRef))
        if not roots:
            return None
        broader = rdflib.URIRef(cpo + "hasBroaderFunction")
        wanted, changed = set(roots), True
        while changed:
            changed = False
            for function, parent in graph.subject_objects(broader):
                if parent in wanted and function not in wanted:
                    wanted.add(function)
                    changed = True
        return {_norm(str(f).split("#")[-1]) for f in wanted}

    def _known_task(self) -> set:
        names = [t.get("name") for t in _as_list(self.sheet.get("tasks"))] + list(BUILT_IN_TASK_NAMES)
        # Also a task the generator creates for a value and whose name only "open" names.
        names += [e.get("answer") for e in _as_list(self.sheet.get("open")) if isinstance(e, dict)
                  and "/task:" in str(e.get("key")) and str(e.get("key")).endswith("/name")]
        return {_norm(n) for n in names if n}

    def _known_phase(self) -> set:
        return {_norm(phase.get("name")) for group in ("materials", "uncontained_streams") for material in _as_list(self.sheet.get(group))
                for phase in _as_list(material.get("phases"))}

    def _known_unit(self) -> set:
        table = json.loads(path_definitions.UNITS_PATH.read_text(encoding="utf-8"))
        return {_norm(unit.split(":", 1)[-1]) for key, units in table.get("units_by_quantity_kind", {}).items()
                if not key.startswith("_") for unit in units}

    def _known_port_end(self) -> set:
        ports = {_norm(e["@id"].split(":", 1)[-1]) for path in path_definitions.DEVICE_LIBRARY_PATHS
                 for e in self._graph(path) if e.get("@id", "").startswith("port:")}
        return self.known("device") | ports | {"outside"}

    def _known_place(self) -> set:
        places = {_norm(r.get("name")) for r in _as_list(self.sheet.get("reactions"))}
        places |= {_norm(d) for d in _as_list(self.sheet.get("devices")) if isinstance(d, str)}
        places |= self._device_parts()      # parts of the devices (dcterms:hasPart), e.g. the pump head
        places |= self.known("task")        # the times of a task in "unknown"
        for group in ("materials", "uncontained_streams"):
            for material in _as_list(self.sheet.get(group)):
                places.add(_norm(material.get("name")))
                places |= {_norm(f"{material.get('name')}/{phase.get('name')}") for phase in _as_list(material.get("phases"))}
        return places

    def _device_parts(self) -> set:
        """The parts (dcterms:hasPart, at any depth) of the devices the sheet lists - the generator writes values
        at them (open_questions.py), so they are places too."""
        entries = {e["@id"]: e for path in path_definitions.DEVICE_LIBRARY_PATHS for e in self._graph(path)
                   if e.get("@id", "").startswith("device:")}
        todo = [f"device:{d}" for d in _as_list(self.sheet.get("devices")) if isinstance(d, str)]
        parts = set()
        while todo:
            for part in _as_list((entries.get(todo.pop()) or {}).get("dcterms:hasPart")):
                part_id = part.get("@id") if isinstance(part, dict) else part
                if part_id and _norm(part_id.split(":", 1)[-1]) not in parts:
                    parts.add(_norm(part_id.split(":", 1)[-1]))
                    todo.append(part_id)
        return parts

    def _known_observable(self) -> set:
        # What an observation was made at (observes): a phase, a material (also a stream), a device.
        return self.known("phase") | self.known("material") | self.known("device")

    def _known_material(self) -> set:
        return {_norm(m.get("name")) for group in ("materials", "uncontained_streams") for m in _as_list(self.sheet.get(group))}

    def _known_substance_of_sheet(self) -> set:
        return {_norm(name) for group in ("materials", "uncontained_streams") for material in _as_list(self.sheet.get(group))
                for phase in _as_list(material.get("phases")) for name in _as_list(phase.get("species"))}

    def _species_problem(self, name) -> str | None:
        from creation.chemical_entity_functions import search_chemical_entities_by_name
        from helpers.library_files import read_library
        library = read_library(path_definitions.CHEMICAL_ENTITY_LIBRARY_PATH)
        hits = search_chemical_entities_by_name(library, str(name), exclude_types=["cpo:ActiveSite"])
        if len(hits) == 1:
            return None
        return f"names {len(hits)} entries of the Chemical Entity Library" + (" (a name with a comma needs quotes)" if not hits else "")

    def _library_id(self, name) -> str:
        """The local ID (Molecule_0007) of the one Chemical Entity Library entry a substance name names, or ''."""
        if not name:
            return ""
        from creation.chemical_entity_functions import search_chemical_entities_by_name
        if not hasattr(self, "_chemical_library"):
            from helpers.library_files import read_library
            self._chemical_library = read_library(path_definitions.CHEMICAL_ENTITY_LIBRARY_PATH)
        hits = search_chemical_entities_by_name(self._chemical_library, str(name), exclude_types=["cpo:ActiveSite"])
        if len(hits) != 1:
            # In the path of a value the name stands normalized (without brackets and commas) - compare as the adapter does.
            hits = [e for e in self._chemical_library.get("@graph", []) if _norm(e.get("schema:name", "")) == _norm(name)]
        return hits[0]["@id"].split(":", 1)[-1] if len(hits) == 1 else ""

    def _input_problem(self, item) -> str | None:
        # An input value "<quantity> <place>" as the adapter reads it (Mass Product_Phase): the calculation
        # can only use a value that exists - a value of the sheet of this quantity, in whose place (at, of)
        # every word of the place occurs. An empty value and "kind: none" do not count.
        quantity, *places = str(item).split()
        # "Evidence 1" / "Reference 1" at the end names which value is meant - not a word of the place.
        while len(places) >= 2 and places[-2].lower() in ("evidence", "reference") and places[-1].isdigit():
            places = places[:-2]
        for value in _as_list(self.sheet.get("values")):
            if not isinstance(value, dict) or _norm(value.get("kind")) == "none":
                continue
            if all(value.get(field) is None for field in ("value", "column", "lower", "upper")):
                continue
            # A substance appears in the option of the generator under its library ID (Molecule_0007).
            species = value.get("of") or dict(part.split(":", 1) for part in str(value.get("at")).split("/")
                                              if ":" in part).get("species")
            where = _norm(f"{value.get('at')}{value.get('of') or ''}{self._library_id(species)}")
            if _norm(value.get("quantity")) == _norm(quantity) and all(_norm(place) in where for place in places):
                return None
        return "points at no value of the sheet - no value of this quantity at this place (the generator offers only values it has)"

    # ------------------------------------------------------------------
    # Conditions
    # ------------------------------------------------------------------

    def _holds(self, condition: dict, entry: dict) -> bool:
        for key, wanted in condition.items():
            if key == "number":
                if not isinstance(entry.get(wanted), (int, float)) or isinstance(entry.get(wanted), bool):
                    return False
            elif key == "not_none":
                if _norm(entry.get(wanted)) == "none":
                    return False
            elif key == "missing_all":
                if any(not _empty(entry.get(name)) for name in wanted):
                    return False
            elif key == "any_filled":
                if all(_empty(entry.get(name)) for name in wanted):
                    return False
            elif key == "given":
                if entry.get(wanted) is None:
                    return False
            elif key == "missing":
                if not _empty(entry.get(wanted)):
                    return False
            elif key == "missing_or_none":
                if not _empty(entry.get(wanted)) and not (isinstance(entry.get(wanted), str) and _norm(entry.get(wanted)) == "none"):
                    return False
            elif _norm(entry.get(key)) != _norm(wanted):
                return False
        return True

    # ------------------------------------------------------------------
    # Checking
    # ------------------------------------------------------------------

    def report(self, kind: str, where: str, text: str):
        self.findings.append((kind, where, text))

    def check_module(self, module_name: str, entry, where: str):
        module = self.schema[module_name]
        if not isinstance(entry, dict):
            self.report("not allowed", where, f"expected a block of fields ({module_name})")
            return
        fields = module["fields"]
        for name in entry:
            if name not in fields and name != "source":
                self.report("unknown field", f"{where} / {name}", "not in the schema - a typo, or a field the adapter ignores")
        self._check_sources(entry, where, fields)
        if module_name == "occurrence":
            # null = still open (a scaffold of open_questions.py): fill in, or [] for "nothing known".
            for name in ("phases", "interfaces", "reactions", "energy_fields", "transfers"):
                if name in entry and entry[name] is None:
                    self.report("missing", f"{where} / {name}", "still open - name the things, or [] if nothing is known")
                elif name == "transfers" and isinstance(entry.get(name), dict):
                    for place, things in entry[name].items():
                        if things is None:
                            self.report("missing", f"{where} / transfers / {place}", "still open - name the transfers, or []")
        if module_name == "open_question" and entry.get("answer") is not None and not entry.get("source"):
            self.report("missing", f"{where} / source", "where the answer comes from (rule 2.10) - otherwise the sheet's source counts")
        for name, rule in fields.items():
            self.check_field(name, rule, entry, f"{where} / {name}" if where else name)

    def _check_sources(self, entry: dict, where: str, fields: dict):
        # An entry may also name the sources of the fields of its parts (a material the states and
        # dispersions of its phases) - that is how the adapter reads it.
        allowed = set(fields)
        for rule in fields.values():
            if "list_of" in rule:
                allowed |= set(self.schema[rule["list_of"]]["fields"])
        source = entry.get("source")
        if isinstance(source, dict):
            for name in source:
                if name not in allowed:
                    self.report("unknown field", f"{where} / source / {name}", "a source for a field the entry does not have")

    def check_field(self, name: str, rule: dict, entry: dict, where: str):
        value = entry.get(name)
        applies = self._holds(rule.get("when", {}), entry)
        if rule.get("allow_empty") and value == "":
            return
        if rule.get("allow_empty") and value is None:
            if rule.get("required") and applies:
                self.report("missing", where, f"{entry.get('question', '')[:120]} - {rule.get('doc', '')}".strip(" -"))
            return
        if _empty(value):
            if rule.get("required") and applies and rule.get("none") not in self.none:
                doc = rule.get("doc", "")
                self.report("missing", where, doc or "required")
            return
        if "module" in rule:
            self.check_module(rule["module"], value, where)
            return
        if "list_of" in rule:
            for index, item in enumerate(_as_list(value)):
                label = (item.get("name") or item.get("device")) if isinstance(item, dict) and (item.get("name") or item.get("device")) else f"[{index}]"
                if isinstance(item, dict) and item.get("about"):
                    label = f"{item['about']} [{item.get('key', '').rsplit('/', 1)[-1]}]"
                if isinstance(item, dict) and item.get("none") and item.get("at"):
                    label = f"{item['at']}{' / ' + item['of'] if item.get('of') else ''}" + (f" (experiment {item['experiment']})" if item.get("experiment") else "")
                if isinstance(item, dict) and item.get("quantity"):
                    label = f"{item.get('at')}{' / ' + item['of'] if item.get('of') else ''} / {item['quantity']}"
                self.check_module(rule["list_of"], item, f"{where} / {label}")
            return
        values = _as_list(value) if rule.get("list") else [value]
        if rule.get("in_options") and entry.get("options") and not entry.get("several"):
            # Compared without prefix: the options stand in the sheet without cpo:/hlo:/unit:, some answers with it.
            allowed = {_norm(str(o).split(":", 1)[-1]) for o in _as_list(entry["options"])}
            answer = "Yes" if value is True else "No" if value is False else str(value).split(":", 1)[-1]
            # Several answers (";") are no single choice; a name with a comma falls apart in the options.
            joined = _norm(" ".join(str(o) for o in _as_list(entry["options"])))
            if ";" not in str(answer) and _norm(answer) not in allowed and _norm(answer) not in joined:
                self.report("not allowed", where, f"{answer!r} - not one of the options")
        if "one_of" in rule:
            allowed = {_norm(v) for v in rule["one_of"]}
            for item in values:
                if _norm(item) not in allowed:
                    self.report("not allowed", where, f"{item!r} - allowed: {', '.join(map(str, rule['one_of']))}")
        if "ref" in rule:
            for item in values:
                self._check_ref(rule["ref"], item, where)

    def _check_ref(self, kind: str, item, where: str):
        if kind == "species":
            problem = self._species_problem(item)
            if problem:
                self.report("not found", where, f"{item!r} {problem}")
            return
        if kind == "input":
            problem = self._input_problem(item)
            if problem:
                self.report("not found", where, f"{item!r} {problem}")
            return
        if kind == "transfers_by_place":
            self._check_transfers(item, where)
            return
        if kind == "species_per_experiment":
            self._check_species_per_experiment(item, where)
            return
        if kind == "place" and (":" in str(item) or str(item).startswith(("for-", "for_"))):
            return      # a place or a task the generator derives - named by its name
        if kind == "port_end" and any(_norm(item).startswith(device) for device in self.known("device")):
            return      # a port of a device (also from a template, such as the opening of a bottle)
        if _norm(item) not in self.known(kind):
            what = "function of the CPO" if kind == "function" else kind.replace("_", " ")
            self.report("not found", where, f"{item!r} is no known {what}")

    def _check_species_per_experiment(self, item, where: str):
        """species_per_experiment: per substance the experiments it occurs in - a substance of
        the Chemical Entity Library, a list of experiment numbers of the series; 'source' as everywhere."""
        if not isinstance(item, dict):
            self.report("not allowed", where, "expected per substance the experiments it occurs in ({<name>: [1, 2]})")
            return
        series = self.sheet.get("series") or {}
        conducted = series.get("conducted_experiments")
        records = series.get("eln_records")
        if not isinstance(conducted, int):
            conducted = len(records) if isinstance(records, list) else None
        for name, experiments in item.items():
            if name == "source":
                continue
            problem = self._species_problem(name)
            if problem:
                self.report("not found", f"{where} / {name}", f"{name!r} {problem}")
            numbers = _as_list(experiments)
            if not numbers or not all(isinstance(n, int) and not isinstance(n, bool) and n >= 1 for n in numbers):
                self.report("not allowed", f"{where} / {name}", f"{experiments!r} - expected a list of experiment numbers ([2], [1, 3])")
            elif conducted and any(n > conducted for n in numbers):
                self.report("not allowed", f"{where} / {name}", f"{experiments!r} - the series has {conducted} experiment(s)")

    def _check_transfers(self, item, where: str):
        """"transfers" of an occurrence: per place a list of transfers, each '<species> from <phase> to
        <phase>' or the generator's name ('<species>-<Type>-from-<phase>-to-<phase>'). Whether a readable
        name is unambiguous at its place only the generator knows - the exploratory run shows it."""
        from interfaces.eln.sheet_names import READABLE_TRANSFER, TRANSFER_LABEL
        if not isinstance(item, dict):
            self.report("not allowed", where, "expected per place a list of transfers ({place: [transfer, ...]})")
            return
        for place, names in item.items():
            for name in _as_list(names):
                if not (READABLE_TRANSFER.match(str(name)) or TRANSFER_LABEL.match(str(name))):
                    self.report("not allowed", f"{where} / {place}",
                                f"{name!r} - expected '<species> from <phase> to <phase>' or the generator's name")

    # The fixed names of the generator (rule 1.7: exceptions) - they do not follow the gerund.
    FIXED_TASK_NAMES = {"experimentalprocedure", "planningtheseries", "establishingthevalues", "preparation",
                        "mainoperation", "workup"}

    def _check_task_names(self):
        """Rule 1.7: a task is named with a gerund and its object ("Adding the catalyst") - a warning, not an
        error: the run does not depend on it, but the name becomes the task's ID and keys."""
        for task in _as_list(self.sheet.get("tasks")):
            name = str(task.get("name") or "") if isinstance(task, dict) else ""
            if not name or _norm(name) in self.FIXED_TASK_NAMES:
                continue
            if not name.split()[0].lower().endswith("ing"):
                self.report("warning", f"tasks / {name}",
                            "rule 1.7: a task name starts with a gerund ('Adding the catalyst', not 'Add catalyst' or "
                            "'Catalyst addition') - the name becomes the task's ID and answer keys")

    def _check_task_functions(self):
        """A function the class of a task does not offer (cpo:offersFunction) - the generator would stop at it
        (TransferringMaterial at an operation). Only for tasks with a 'type': without
        one the generator asks the class, and the functions are checked against the answer in the run."""
        for task in _as_list(self.sheet.get("tasks")):
            if not isinstance(task, dict) or not task.get("type") or not task.get("functions"):
                continue
            task_class = "Task" if _norm(task["type"]) == "task" else f"{str(task['type']).capitalize()}Task"
            offered = self._offered_functions(task_class)
            if offered is None:
                continue
            for function in _as_list(task["functions"]):
                if _norm(function) in self.known("function") and _norm(function) not in offered:
                    self.report("not allowed", f"tasks / {task.get('name')} / functions",
                                f"{function!r} - a task of type '{task['type']}' (cpo:{task_class}) does not offer it "
                                "(cpo:offersFunction in the CPO); another type, or another function")

    # The class of the task that determines a value of this kind (hlo:determinedByTaskClass).
    TASK_CLASS_OF_KIND = {"measured": "MeasurementTask", "calculated": "CalculationTask", "observed": "ObservationTask",
                          "planned": "PlanningTask", "assumed": "AssumptionTask", "controlled": "ControlTask",
                          "set": "SettingTask", "literature": "LiteratureLookupTask"}

    def _check_built_in_determiners(self):
        """determined_by naming a task the generator creates itself: only the planning (cpo:PlanningTask)
        determines anything, and only planned values - for any other the generator creates a task of the
        value's own class and the adapter gives it the built-in name, a second "Planning the series" (Chemotion,
        a literature value)."""
        planning = _norm("Planning the series")
        for section in ("values", "occurrences"):
            for i, entry in enumerate(_as_list(self.sheet.get(section))):
                if not isinstance(entry, dict) or _norm(entry.get("determined_by")) not in map(_norm, BUILT_IN_TASK_NAMES):
                    continue
                kind = str(entry.get("kind") or "").lower()
                if _norm(entry["determined_by"]) == planning and kind in ("planned", ""):
                    continue
                place = f"{entry.get('at')} / {entry.get('quantity')}" if section == "values" else f"[{i}]"
                own = self.TASK_CLASS_OF_KIND.get(kind)
                self.report("not allowed", f"{section} / {place} / determined_by",
                            f"{entry['determined_by']!r} is created by the generator and determines "
                            + ("planned values only" if _norm(entry["determined_by"]) == planning else "no value")
                            + (f" - a value of kind '{kind}' gets a task of its own (cpo:{own}): give it a name of its own"
                               if own else ""))

    def _check_possible_reactions(self):
        """A suggestion, not an error: a fixed reaction of the Reaction Library
        (no template) the sheet does not name, whose reactants (negative coefficient) all stand in one phase of
        the sheet - together in at least one experiment (species_per_experiment). Nothing goes into the crate
        by itself; whoever fills in the sheet adds it under 'reactions' or leaves it out. Interfaces are not
        looked at. The full idea - finding reactions automatically - is an outlook of the thesis."""
        graph = self._graph(path_definitions.REACTION_LIBRARY_PATH)
        by_id = {e.get("@id"): e for e in graph}
        named = set()
        for entry in _as_list(self.sheet.get("reactions")):
            name = entry.get("name") if isinstance(entry, dict) else entry
            named.add(_norm(name))
        per_experiment = {self._library_id(name): set(_as_list(numbers))
                          for name, numbers in (self.sheet.get("species_per_experiment") or {}).items() if name != "source"}
        phases = [(f"{material.get('name')}/{phase.get('name')}", {self._library_id(s) for s in _as_list(phase.get("species"))} - {""})
                  for group in ("materials", "uncontained_streams") for material in _as_list(self.sheet.get(group))
                  if isinstance(material, dict) for phase in _as_list(material.get("phases")) if isinstance(phase, dict)]
        for reaction in graph:
            types = set(_as_list(reaction.get("@type")))
            if not types & {"cpo:StoichiometricReaction", "cpo:LumpedReaction"} or "hlo:Template" in types:
                continue
            if {_norm(reaction.get("schema:name")), _norm(reaction["@id"]), _norm(reaction["@id"].split(":", 1)[-1])} & named:
                continue
            reactants = set()
            for ref in _as_list(reaction.get("cpo:hasParticipant")):
                participant = by_id.get(ref.get("@id") if isinstance(ref, dict) else ref) or {}
                part = participant.get("dcterms:hasPart")
                if float(participant.get("cpo:hasStoichiometricCoefficient") or 0) < 0 and isinstance(part, dict):
                    reactants.add(part["@id"].split(":", 1)[-1])
            if not reactants:
                continue
            # Together in one experiment: a substance not under species_per_experiment occurs in every one.
            listed = [per_experiment[r] for r in reactants if r in per_experiment]
            if listed and not set.intersection(*listed):
                continue
            for place, species in phases:
                if reactants <= species:
                    self.report("warning", f"reactions (suggestion) / {place}",
                                f"{reaction.get('schema:name')!r} ({reaction['@id']}) could take place here - all its reactants "
                                "are in this phase; the sheet does not name it. Add it under 'reactions', or leave it out on purpose")

    def run(self) -> list:
        self.check_module("sheet", self.sheet, "")
        self._check_task_names()
        self._check_task_functions()
        self._check_built_in_determiners()
        self._check_possible_reactions()
        return self.findings


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("sheet", type=Path)
    args = parser.parse_args()
    findings = SheetCheck(args.sheet).run()
    errors = [f for f in findings if f[0] != "warning"]
    if not errors:
        print(f"{args.sheet}: nothing missing, every name found.")
    # Warnings (rule 1.7) stop nothing: exit code 0 if nothing else is missing.
    order = ("missing", "not found", "not allowed", "unknown field", "warning")
    for kind in order:
        hits = [f for f in findings if f[0] == kind]
        if hits:
            print(f"\n{kind.capitalize()} ({len(hits)}):")
            for _kind, where, text in hits:
                print(f"  {where.lstrip(' /')}\n      {text}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
