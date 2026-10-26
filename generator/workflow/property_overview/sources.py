"""
Where a property comes from besides the shapes: the fields of the library entry schema (column Template /
Fixed), the fields of the setup sheet (Series / Experiment), the questions the generator asked in the answer
files (every level) and the checks of check_library_consistency.py (by hand, overview_config.yaml).

Every source is a dict:
  class, row (the property), levels (set), kind ("entry", "sheet", "question", "check"),
  need ("required", "conditional", "asked", "optional", "constraint", "ban"), label (where it stands), note.
"""
import re
from collections import defaultdict
from pathlib import Path

import yaml

from common import ROOT, path_definitions

ENTRY_SCHEMA = ROOT / "generator" / "workflow" / "library_entries" / "entry_schema.yaml"
SHEET_SCHEMA = ROOT / "generator" / "interfaces" / "eln" / "sheet_schema.yaml"
CONFIG = Path(__file__).resolve().parent / "overview_config.yaml"


def load_config() -> dict:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def split_property(text: str):
    """'cpo:performedBy (preparation)' -> (['cpo:performedBy'], 'preparation');
    'hlo:hasEvidenceType, hlo:hasReferenceType' -> two properties, no hint."""
    text = str(text).strip()
    hint = None
    match = re.match(r"^(.*?)\s*\(([^)]*)\)\s*$", text)
    if match:
        text, hint = match.group(1).strip(), match.group(2).strip()
    props = [p.strip() for p in text.split(",") if p.strip()]
    return props, hint


def need_of(field: dict) -> str:
    if field.get("required") and not field.get("when"):
        return "required"
    if field.get("required"):
        return "conditional"
    if field.get("none"):
        return "asked"
    return "optional"


class Sources:
    def __init__(self, config: dict, tree):
        self.config = config
        self.tree = tree
        self.items = []
        self.unmapped = defaultdict(list)     # kind -> [label] of fields/questions without a property
        self.quantity_fields = []             # sheet fields that stand for the quantity of a value
        self.read_entry_schema()
        self.read_sheet_schema()
        self.read_questions()
        self.read_checks()

    def add(self, classes, row, levels, kind, need, label, note="", **extra):
        for cls in classes:
            self.items.append(dict({"class": cls, "row": row, "levels": set(levels), "kind": kind,
                                    "need": need, "label": label, "note": note}, **extra))

    # -- library entry schema ------------------------------------------------------------------

    def read_entry_schema(self):
        schema = yaml.safe_load(ENTRY_SCHEMA.read_text(encoding="utf-8"))
        cfg = self.config["entry"]
        modules = schema.get("modules", {})
        for name, field in schema["file"]["fields"].items():
            spec = cfg["file_fields"].get(name)
            if spec and field.get("property"):
                props, _ = split_property(field["property"])
                for prop in props:
                    self.add(spec["classes"], prop, cfg["levels"], "entry", need_of(field), f"entry file.{name}",
                             "every entry file")
        for type_name, type_spec in schema["types"].items():
            spec = cfg["types"].get(type_name)
            if spec is None:
                self.unmapped["entry type"].append(type_name)
                continue
            levels = spec.get("levels", cfg["levels"])
            for added in spec.get("adds", []):
                self.add(added.get("classes", spec["classes"]), added["property"], added.get("levels", levels),
                         "entry", "derived", f"entry {type_name} ({added.get('by', 'made by the tool')})")
            self._entry_fields(type_name, type_spec["fields"], spec["classes"], levels, spec.get("forms", []),
                               type_name, modules, cfg)

    def _entry_fields(self, label, fields, classes, levels, forms, type_name, modules, cfg, seen=()):
        for name, field in fields.items():
            here = f"{label}.{name}"
            need = need_of(field)
            text = field.get("property")
            if text:
                props, hint = split_property(text)
                target, target_levels = list(classes), list(levels)
                inverse = False
                if hint is not None:
                    hint_spec = cfg["hints"].get(hint)
                    if hint_spec is None:
                        self.unmapped["entry hint"].append(f"{here} ({hint})")
                    else:
                        target = hint_spec.get("classes", target)
                        inverse = hint_spec.get("inverse", False)
                if inverse:
                    target = cfg["inverse_targets"].get(f"{type_name}.{name}", target)
                target_levels = cfg.get("field_levels", {}).get(f"{type_name}.{name}", target_levels)
                for prop in props:
                    row_classes = target
                    if prop in self.config["form_dimensions"] and forms:
                        row_classes = forms
                    row_classes = cfg.get("field_classes", {}).get(f"{type_name}.{name}", row_classes)
                    if prop in ("@id",):
                        continue
                    self.add(row_classes, prop, target_levels, "entry", need, f"entry {here}",
                             f"hint: {hint}" if hint else "")
            elif not field.get("module") and not field.get("list_of"):
                self.unmapped["entry field"].append(here)
            module = field.get("module") or field.get("list_of")
            if module and module not in seen:
                if module == "value":
                    self._value_fields(here, levels, need)
                    continue
                mspec = cfg["modules"].get(module)
                if mspec is None:
                    self.unmapped["entry module"].append(module)
                    continue
                self._entry_fields(f"{label}.{name}", modules[module]["fields"], mspec["classes"],
                                   mspec.get("levels", levels), [], module, modules, cfg, seen + (module,))

    def _value_fields(self, label, levels, need):
        for name, props in self.config["entry"]["value_fields"].items():
            for prop in [p.strip() for p in props.split(",")]:
                cls = ["hlo:Evidence", "hlo:Reference"]
                if prop == "hlo:hasEvidenceType":
                    cls = ["hlo:Evidence"]
                elif prop == "hlo:hasReferenceType":
                    cls = ["hlo:Reference"]
                # value and kind are required in every value block - required when the value is.
                block_need = ("required" if need == "required" else "conditional") if name in ("value", "kind") else "optional"
                self.add(cls, prop, levels, "entry", block_need, f"entry {label}.{name}", "module value")

    # -- setup sheet ---------------------------------------------------------------------------

    def read_sheet_schema(self):
        schema = yaml.safe_load(SHEET_SCHEMA.read_text(encoding="utf-8"))
        cfg = self.config["sheet"]
        for module, body in schema.items():
            if not isinstance(body, dict) or "fields" not in body:
                continue
            spec = cfg["modules"].get(module)
            if spec is None:
                if any(f.get("property", "-") != "-" for f in body["fields"].values()):
                    self.unmapped["sheet module"].append(module)
                continue
            for name, field in body["fields"].items():
                here = f"sheet {module}.{name}"
                text = field.get("property")
                if text is None:
                    self.unmapped["sheet field"].append(here)
                    continue
                if text == "-":
                    continue
                if text.startswith("(quantity"):
                    self.quantity_fields.append({"label": here, "need": "asked",
                                                 "levels": spec.get("levels", cfg["levels"]),
                                                 "note": "nothing known" if "nothing" in text else ""})
                    continue
                for group in text.split(";"):
                    self._sheet_group(group, field, here, spec, cfg)

    def _sheet_group(self, text, field, here, spec, cfg):
        """One effect of a sheet field: '<property>[, <property>] (<hint>)'."""
        props, hint = split_property(text)
        classes, levels = spec["classes"], spec.get("levels", cfg["levels"])
        if hint is not None:
            hint_spec = cfg["hints"].get(hint)
            if hint_spec is None:
                self.unmapped["sheet hint"].append(f"{here} ({hint})")
            else:
                classes = hint_spec.get("classes", classes)
                levels = hint_spec.get("levels", levels)
        for prop in props:
            if prop == "@id":
                continue
            row_classes = classes
            if prop == "hlo:hasEvidenceType":
                row_classes = [c for c in classes if c != "hlo:Reference"] or classes
            if prop == "hlo:hasReferenceType":
                row_classes = [c for c in classes if c != "hlo:Evidence"] or classes
            self.add(row_classes, prop, levels, "sheet", need_of(field), here, f"hint: {hint}" if hint else "")

    # -- answer files --------------------------------------------------------------------------

    def quantity_property(self, name: str):
        """'transferredvolume' -> cpo:hasTransferredVolume; 'form_inner_diameter' -> (cpo:hasInnerDiameter, form)."""
        form = False
        key = name.lower()
        match = re.match(r"^(envelope_form_|form_|part_[a-z0-9]+_)", key)
        if match:
            key, form = key[match.end():], True
        key = key.replace("_", "")
        special = self.config["questions"]["quantity_names"].get(key)
        if special:
            return special, form
        if not hasattr(self, "_by_name"):
            self._by_name = {}
            for prop in self.tree.properties:
                local = prop.split(":", 1)[-1]
                if local.startswith("has"):
                    self._by_name.setdefault(local[3:].lower(), prop)
        return self._by_name.get(key), form

    def read_questions(self):
        cfg = self.config["questions"]
        seg_classes, containers = cfg["segments"], set(cfg["containers"])
        ids, value_ids = cfg["ids"], cfg["value_ids"]
        self.question_keys = 0
        patterns = adapter_patterns()
        self.sheet_patterns = len(patterns)
        self.unanswered_keys = defaultdict(set)       # question_id -> key patterns no sheet field answers
        found = defaultdict(lambda: {"count": 0, "projects": set(), "sheet": 0})
        for answers in sorted(path_definitions.PROJECTS_FOLDER.glob("*/answers.txt")):
            project = answers.parent.name
            for key, question in _answer_entries(answers):
                self.question_keys += 1
                by_sheet = any(p.fullmatch(key) for p in patterns)
                if not by_sheet:
                    self.unanswered_keys[key.split("/")[-1]].add(re.sub(r":[^/]+", ":<…>", key))
                for cls, prop, level, label in self._question_rows(key, question, seg_classes, containers, ids, value_ids):
                    entry = found[(cls, prop, level, label)]
                    entry["count"] += 1
                    entry["projects"].add(project)
                    entry["sheet"] += by_sheet
        for (cls, prop, level, label), entry in found.items():
            # A question the adapter answers from the setup sheet (interfaces/eln/adapter.py) has a place there.
            by_sheet = entry["sheet"] == entry["count"]
            self.add([cls], prop, [level], "question", "asked", label + (" (sheet)" if by_sheet else ""),
                     f"{entry['count']}x in {len(entry['projects'])} answer file(s)", by_sheet=by_sheet)

    def _question_rows(self, key, question, seg_classes, containers, ids, value_ids):
        parts = key.split("/")
        qid = parts[-1]
        level = "Series"
        if parts[0] == "fixed":
            level = "Fixed"
        if any(p.startswith("experiment:") for p in parts):
            level = "Experiment"
        tag = re.match(r"^\[hlo:(\w+)\]", question or "")
        if tag:
            level = {"SeriesSpecific": "Series", "ExperimentSpecific": "Experiment", "Fixed": "Fixed"}.get(tag.group(1), level)
        thing, quantity, record = None, None, None
        for part in parts[:-1]:
            kind = part.split(":", 1)[0]
            if kind in containers:
                continue
            if ":" in part:
                if kind in ("evidence", "reference"):
                    record = seg_classes[kind]
                elif kind in seg_classes:
                    thing, quantity = seg_classes[kind], None
            else:
                quantity = part
        rows = []
        label = f"question {qid}"
        if qid.startswith("quantities_"):
            q_level = "Experiment" if qid == "quantities_known_per_experiment" else level
            options = re.findall(r"\[([^\[\]]*)\]", question or "")
            for name in (options[-1].split(",") if options and not (tag and len(options) == 1) else []):
                prop, form = self.quantity_property(name.strip())
                if prop is None:
                    self.unmapped["quantity name"].append(name.strip())
                    continue
                rows.append(("cpo:Form" if form else thing, prop, q_level, label))
            return [r for r in rows if r[0]]
        role = None
        if qid in ids:
            prefixes = ()
        else:
            prefixes = ("evidence_", "reference_")
        for prefix in prefixes:
            if qid.startswith(prefix):
                role, qid_rest = prefix[:-1], qid[len(prefix):]
                break
        if role is None and record is not None:
            role, qid_rest = record.split(":")[-1].lower(), qid
        if role is not None or quantity is not None:
            if quantity is not None:
                prop, form = self.quantity_property(quantity)
                owner = "cpo:Form" if form else (thing if quantity != "status" else "cpo:Occurrence")
                if prop is None:
                    self.unmapped["quantity name"].append(quantity)
                elif owner:
                    rows.append((owner, prop, level, f"question {quantity}/…"))
            if role is not None:
                value_prop = value_ids.get(qid_rest)
                if value_prop is None:
                    self.unmapped["question"].append(qid)
                elif value_prop != "-":
                    record_class = "hlo:Evidence" if role == "evidence" else "hlo:Reference"
                    value_prop, _, moved = value_prop.partition(" @")
                    record_class = moved or record_class
                    for prop in [p.strip() for p in value_prop.split(",")]:
                        if prop == "hlo:hasEvidenceType" and record_class != "hlo:Evidence":
                            continue
                        if prop == "hlo:hasReferenceType" and record_class != "hlo:Reference":
                            continue
                        rows.append((record_class, prop, level, f"question {role}_{qid_rest}"))
            return rows
        text = ids.get(qid)
        if text is None:
            self.unmapped["question"].append(qid)
            return []
        if text == "-":
            return []
        prop, _, moved = text.partition(" @")
        cls = moved or thing
        if cls is None:
            return []
        return [(cls, prop.strip(), level, label)]

    # -- check_library_consistency.py ----------------------------------------------------------

    def read_checks(self):
        for check in self.config.get("checks", []):
            self.add([check["class"]], check["property"], check.get("levels", ["Fixed"]), "check", check["kind"],
                     f"check {check['check']}", check.get("note", ""))


def adapter_patterns() -> list:
    """The key patterns the adapter answers from a setup sheet (SetupAdapter._handlers) - the same for every sheet;
    read with the sheet of the amidation. Empty if the adapter cannot be loaded."""
    import sys
    sys.path.insert(0, str(ROOT / "generator"))
    try:
        from interfaces.eln.adapter import SetupAdapter
        project = path_definitions.PROJECTS_FOLDER / "amidation_ai4green_ai4_001"
        adapter = SetupAdapter(project / "setup.yaml", project)
        return [pattern for pattern, _ in adapter._handlers]
    except Exception as error:      # the overview stays usable without it
        print(f"[property overview] the adapter could not be read ({error}) - questions count as not on the sheet")
        return []


def _answer_entries(path):
    """(key, question) of every entry of an answer file (format keyed-v2)."""
    key, question = None, None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("key: "):
            if key is not None:
                yield key, question
            key, question = line[5:].strip(), None
        elif line.startswith("    // ") and key is not None and question is None and not line.startswith("    // source:"):
            question = line[7:].strip()
    if key is not None:
        yield key, question
