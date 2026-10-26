"""
Library entry files: the empty template of a type and the check of a filled-in file against
entry_schema.yaml. Knows nothing of the libraries - what a name points at is decided in finish_library_entry.py.

A file:
    format: library-entry-v1
    type: person
    entered_by: person:LauraFadler
    source: Given by Meng Kong on 07.10.2026.
    entries:
      - name: ...
    open:      (written by the tool: questions that came up while finishing)
    written:   (written by the tool: what went into the libraries, when)
"""
import json
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from interfaces.eln.sheet_text import append_to_section  # noqa: E402
from interfaces.pubchem.pubchem_lookup import _cas_valid  # noqa: E402

SCHEMA_PATH = Path(__file__).resolve().parent / "entry_schema.yaml"
FILE_FORMAT = "library-entry-v1"
TOOL_SECTIONS = ("open", "written")
COMMENT_COLUMN = 24

_FORMATS = {
    "cas": re.compile(r"^\d{2,7}-\d\d-\d$"),
    "orcid": re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$"),
    "email": re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$"),
    "url": re.compile(r"^https?://\S+$"),
    "smiles": re.compile(r"^\S+$"),
}


def load_schema() -> dict:
    return yaml.safe_load(SCHEMA_PATH.read_text(encoding="utf-8"))


def entry_types(schema: dict = None) -> list:
    return list((schema or load_schema())["types"])


def empty(value) -> bool:
    return value is None or value == "" or value == [] or value == {}


def as_list(value) -> list:
    if empty(value):
        return []
    return value if isinstance(value, list) else [value]


def _orcid_valid(orcid: str) -> bool:
    """ISO 7064 11,2 - the check character of an ORCID."""
    total = 0
    for char in orcid.replace("-", "")[:-1]:
        total = (total + int(char)) * 2
    check = (12 - total % 11) % 11
    return orcid[-1] == ("X" if check == 10 else str(check))


def format_problem(kind: str, value) -> str | None:
    """Why value does not have the format kind, or None."""
    text = str(value).strip()
    if not _FORMATS[kind].match(text):
        return f"is not a valid {kind}"
    if kind == "cas" and not _cas_valid(text):
        return "has a wrong CAS check digit (rule 2.8)"
    if kind == "orcid" and not _orcid_valid(text):
        return "has a wrong ORCID check character (rule 2.8)"
    return None


# ----------------------------------------------------------------------------------------------
# Template
# ----------------------------------------------------------------------------------------------

def _scalar(value) -> str:
    """A value as YAML: plain where that reads back the same, quoted otherwise."""
    if (isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.:/@()+\- ]+", value) and ": " not in value
            and yaml.safe_load(value) == value):
        return value
    return json.dumps(value, ensure_ascii=False)


def _line(indent: str, key: str, spec: dict, value=None, commented=False, item=False, cont=False) -> str:
    """One field of the template: 'key: value   # (required) doc - e.g. example'. item: the first field of a list
    item ('- '), cont: a further field of it (aligned under the first)."""
    # A commented field keeps the indentation of its key, so that removing "# " (as an editor's toggle does) leaves
    # valid YAML.
    lead = indent + ("  " if cont else "") + ("# " if commented else "") + ("- " if item else "")
    if value is not None:
        head = f"{lead}{key}: {_scalar(value)}"
    elif spec.get("list"):
        head = f"{lead}{key}: []"
    else:
        head = f"{lead}{key}:"
    words = []
    if spec.get("required"):
        when = spec.get("when")
        words.append("(required" + (" when " + ", ".join(f"{k}: {v}" for k, v in when.items()) if when else "") + ")")
    if spec.get("one_of"):
        words.append(" | ".join(map(str, spec["one_of"])) + (" -" if spec.get("doc") else ""))
    if spec.get("doc"):
        words.append(spec["doc"])
    if spec.get("example") is not None:
        words.append(("- " if spec.get("doc") else "") + f"e.g. {spec['example']}")
    comment = " ".join(words)
    return (head.ljust(COMMENT_COLUMN) + "  # " + comment).rstrip() if comment else head


def _block_lines(schema: dict, indent: str, fields: dict, commented: bool, as_item: bool, prefill: dict = None) -> list:
    """The fields of a block (an entry, a module), one line each, and the blocks inside them below. as_item: the block
    is an item of a list ('- ' before its first field). commented: the whole block is optional and not filled in."""
    prefill, lines = prefill or {}, []
    for n, (key, spec) in enumerate(fields.items()):
        value = prefill.get(key)
        nested = spec.get("list_of") or spec.get("module")
        off = commented or (not spec.get("required") and value is None)
        lines.append(_line(indent, key, spec, value=None if nested else value, commented=off,
                           item=as_item and n == 0, cont=as_item and n > 0))
        inner = indent + ("  " if as_item else "") + "  "
        if spec.get("list_of"):
            lines += _block_lines(schema, inner, schema["modules"][spec["list_of"]]["fields"], off, as_item=True)
        elif spec.get("module"):
            lines += _block_lines(schema, inner, schema["modules"][spec["module"]]["fields"], off, as_item=False)
    return lines


def template_text(entry_type: str, prefill: dict = None, head: dict = None) -> str:
    """The empty entry file of a type. prefill: values of the (first) entry; head: values of the head fields."""
    schema = load_schema()
    spec = schema["types"][entry_type]
    head = head or {}
    lines = [
        f"# Library entry: {entry_type} -> libraries/{spec['library']}",
        *[f"# {part}" for part in _wrap(spec["doc"])],
        "#",
        "# Fill in the fields without '#'. An optional field is commented out: remove its '# ' to use it.",
        "# More than one entry: copy the block under 'entries' (from '- name:') once per entry.",
        "# A value (a mass, a time) is a block: value, unit, kind and source. kind: measured (weighed, read off an",
        "# instrument), observed (written down by someone, e.g. the opening date on the label), literature (printed",
        "# by the manufacturer: label, certificate, delivery note), assumed (source then says why).",
        "# Then check it (nothing is written):",
        "#   python generator/workflow/library_entries/finish_library_entry.py <this file>",
        "# and write it into the libraries with --write.",
        "",
    ]
    for key, field in schema["file"]["fields"].items():
        value = {"format": FILE_FORMAT, "type": entry_type}.get(key, head.get(key))
        lines.append(_line("", key, field, value=value))
    lines += ["", "entries:"]
    lines += _block_lines(schema, "  ", spec["fields"], False, as_item=True, prefill=prefill)
    return "\n".join(lines) + "\n"


def _wrap(text: str, width: int = 110) -> list:
    words, lines, line = str(text).split(), [], ""
    for word in words:
        if len(line) + len(word) + 1 > width:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    return lines + ([line] if line else [])


# ----------------------------------------------------------------------------------------------
# Check
# ----------------------------------------------------------------------------------------------

class EntryFile:
    """A filled-in entry file and what is wrong with it on its own (without the libraries)."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.schema = load_schema()
        self.data = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        self.type = self.data.get("type")
        self.findings = []           # (kind, place, text)

    @property
    def spec(self) -> dict:
        return self.schema["types"][self.type]

    @property
    def entries(self) -> list:
        return [e for e in as_list(self.data.get("entries")) if isinstance(e, dict)]

    def add(self, kind: str, place: str, text: str):
        self.findings.append((kind, place, text))

    def check(self) -> list:
        """Structural findings: missing, not allowed, unknown field, format."""
        if self.data.get("format") != FILE_FORMAT:
            self.add("not allowed", "format", f"must be {FILE_FORMAT}")
        if self.type not in self.schema["types"]:
            self.add("not allowed", "type", f"'{self.type}' - known types: {', '.join(self.schema['types'])}")
            return self.findings
        self._check_fields(self.data, self.schema["file"]["fields"], "", skip=("entries", *TOOL_SECTIONS))
        if not self.entries:
            self.add("missing", "entries", "no entry")
        for n, entry in enumerate(self.entries, start=1):
            self._check_fields(entry, self.spec["fields"], f"entries[{n}].")
        return self.findings

    def _check_fields(self, data: dict, fields: dict, place: str, skip=()):
        for key in data:
            if key not in fields and key not in skip:
                self.add("unknown field", f"{place}{key}", "the schema does not know it (a typo?)")
        for key, spec in fields.items():
            value = data.get(key)
            if empty(value):
                when = spec.get("when") or {}
                if spec.get("required") and all(data.get(f) == v for f, v in when.items()):
                    self.add("missing", f"{place}{key}", spec.get("doc", "") + (f" (as {when})" if when else ""))
                continue
            if spec.get("module"):
                # A value may be known in more than one way (measured and planned): then a list of value blocks.
                blocks = value if spec["module"] == "value" and isinstance(value, list) else [value]
                for m, block in enumerate(blocks, start=1):
                    where = f"{place}{key}" + (f"[{m}]" if len(blocks) > 1 else "")
                    if not isinstance(block, dict):
                        self.add("not allowed", where, "must be a block of fields")
                    else:
                        self._check_fields(block, self.schema["modules"][spec["module"]]["fields"], f"{where}.")
                continue
            if spec.get("one_of") and value not in spec["one_of"]:
                self.add("not allowed", f"{place}{key}", f"'{value}' - allowed: {', '.join(map(str, spec['one_of']))}")
            if spec.get("list") and not isinstance(value, list):
                value = [value]
            if spec.get("list_of"):
                for m, item in enumerate(as_list(value), start=1):
                    if not isinstance(item, dict):
                        self.add("not allowed", f"{place}{key}[{m}]", "must be a block of fields")
                        continue
                    self._check_fields(item, self.schema["modules"][spec["list_of"]]["fields"], f"{place}{key}[{m}].")
                continue
            if spec.get("format"):
                for item in as_list(value):
                    if str(item).strip() in [str(a) for a in spec.get("allow", [])]:
                        continue
                    problem = format_problem(spec["format"], item)
                    if problem:
                        self.add("not allowed", f"{place}{key}", f"'{item}' {problem}")

    # ------------------------------------------------------------------
    # What the tool writes into the file
    # ------------------------------------------------------------------

    def open_questions(self) -> list:
        return [q for q in as_list(self.data.get("open")) if isinstance(q, dict)]

    def ask(self, questions: list) -> list:
        """Append the questions not yet under 'open' (one per entry and field); returns the new ones."""
        asked = {(q.get("entry"), q.get("field")) for q in self.open_questions()}
        new = [q for q in questions if (q.get("entry"), q.get("field")) not in asked]
        append_to_section(self.path, "open", "# Questions that came up while finishing (finish_library_entry.py) - answer them\n"
                                             "# in the field of the entry; the question may stay here.\nopen:\n", new)
        return new

    def record_written(self, record: dict):
        append_to_section(self.path, "written", "# Written into the libraries by finish_library_entry.py - do not write again.\n"
                                                "written:\n", [record])
