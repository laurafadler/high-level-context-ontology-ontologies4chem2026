"""
The libraries as one set for the library entry tools: look up what a name points at, add new
entities and links back to existing ones - in memory -, compare the consistency check before and after, and
write.

- Reads every library as one document (main file and details, rule 2.14) through load_jsonld; writes the split
  ones back through save_jsonld (byte for byte the generator's own format). The People Library is formatted by
  hand and does not survive json.dumps unchanged: new entities are inserted as text before its end (as the
  curation scripts did, add_person); changing an existing person is not supported.
- Nothing is ever overwritten: a new ID that exists in any library stops the tool.
- The consistency check (workflow/check_library_consistency.py) is run in memory on the state with the new
  entities - its loading function is replaced for that run - and its report compared with the one of the
  libraries as they are. Only findings that are new count; the list of unreferenced entries is shown, not
  counted (a new entry is unreferenced until a crate uses it).
"""
import contextlib
import copy
import io
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from helpers.file_handling import load_jsonld, save_jsonld  # noqa: E402
from helpers.library_files import is_split  # noqa: E402

PEOPLE = "people_library.jsonld"
INFORMATION_ONLY = ("Unreferenced library entries",)
_SECTION = re.compile(r"^(\S.*) \((\d+)\):$")

# What a reference of a kind points at: (library, type of the entity).
REFERENCE_KINDS = {
    "person": ("people_library.jsonld", "schema:Person"),
    "organization": ("organization_library.jsonld", "org:Organization"),
    "record": ("reaction_library.jsonld", "schema:Dataset"),
    "substance": ("chemical_entity_library.jsonld", "chebi:ChemicalEntity"),
    "template": ("device_library.jsonld", "hlo:Template"),
    "cabinet": ("organization_library.jsonld", "cpo:StorageCabinet"),
    "site": ("organization_library.jsonld", "org:Site"),
    "laboratory": ("organization_library.jsonld", "cpo:Laboratory"),
    # Where a device is kept: a laboratory or a cabinet.
    "place": ("organization_library.jsonld", ("cpo:Laboratory", "cpo:StorageCabinet")),
    # What a container filled in the lab is filled from: a device that holds something (a bottle, a line).
    "source": ("device_library.jsonld", lambda entity: bool(entity.get("cpo:containsMaterial"))),
}


def _fits(entity, entity_type) -> bool:
    if callable(entity_type):
        return entity_type(entity)
    wanted = entity_type if isinstance(entity_type, tuple) else (entity_type,)
    return any(t in _types(entity) for t in wanted)


def _types(entity) -> list:
    types = entity.get("@type", [])
    return types if isinstance(types, list) else [types]


def norm(text) -> str:
    return "".join(c for c in str(text).lower() if c.isalnum())


def ref(entity_id: str) -> dict:
    return {"@id": entity_id}


def _library_files() -> dict:
    from workflow.check_library_consistency import LIBRARY_FILES
    return dict(LIBRARY_FILES)


class IdTaken(ValueError):
    pass


class LibrarySet:
    def __init__(self):
        self.paths = _library_files()
        self.docs = {name: load_jsonld(path) for name, path in self.paths.items()}
        self.new = {name: [] for name in self.paths}        # entities added, per library
        self.changed = set()                                  # libraries with a changed existing entity

    # ------------------------------------------------------------------
    # Looking up
    # ------------------------------------------------------------------

    def entities(self, name: str) -> list:
        return [e for e in self.docs[name].get("@graph", []) if isinstance(e, dict)]

    def find(self, entity_id: str):
        """(library, entity) of an ID, or (None, None)."""
        for name in self.docs:
            for entity in self.entities(name):
                if entity.get("@id") == entity_id:
                    return name, entity
        return None, None

    def exists(self, entity_id: str) -> bool:
        return self.find(entity_id)[1] is not None

    def resolve(self, kind: str, text) -> tuple:
        """(ID, None) of the entry of this kind that text names - by its ID, its ID without the prefix, or its
        name - or (None, why)."""
        library, entity_type = REFERENCE_KINDS[kind]
        wanted = norm(text)
        hits = []
        for entity in self.entities(library):
            if not _fits(entity, entity_type):
                continue
            entity_id = entity.get("@id", "")
            names = [entity.get("schema:name")] if not isinstance(entity.get("schema:name"), list) else entity["schema:name"]
            if str(text) == entity_id or wanted in {norm(entity_id.split(":", 1)[-1]), *[norm(n) for n in names if n]}:
                hits.append(entity_id)
        if len(hits) == 1:
            return hits[0], None
        if hits:
            return None, f"'{text}' fits {len(hits)} entries: {', '.join(hits)} - name the ID"
        return None, f"no {kind} '{text}' in {library}"

    # ------------------------------------------------------------------
    # Changing (in memory)
    # ------------------------------------------------------------------

    def add(self, name: str, entities: list):
        taken = {e["@id"] for n in self.docs for e in self.entities(n) if "@id" in e}
        for entity in entities:
            if entity["@id"] in taken:
                raise IdTaken(f"{entity['@id']} exists already ({self.find(entity['@id'])[0]}) - nothing is overwritten")
            taken.add(entity["@id"])
        self.docs[name]["@graph"].extend(entities)
        self.new[name].extend(entities)

    def link(self, entity_id: str, prop: str, target_id: str):
        """Add a reference to an entity - also an existing one (the other direction of a new link)."""
        name, entity = self.find(entity_id)
        if entity is None:
            raise KeyError(entity_id)
        values = entity.get(prop)
        values = [] if values is None else values if isinstance(values, list) else [values]
        if any(isinstance(v, dict) and v.get("@id") == target_id for v in values):
            return
        entity[prop] = values + [ref(target_id)]
        if entity not in self.new[name]:
            self.changed.add(name)

    def touched(self) -> list:
        return sorted({n for n, e in self.new.items() if e} | self.changed)

    # ------------------------------------------------------------------
    # Consistency check before / after
    # ------------------------------------------------------------------

    def consistency(self, current: bool = True) -> dict:
        """{section: [lines]} of check_library_consistency - on the state in memory (current) or on the files."""
        import workflow.check_library_consistency as check
        overrides = {Path(self.paths[n]).resolve(): self.docs[n] for n in self.touched()} if current else {}
        original = check.load_jsonld

        def load(path, reset=False):
            resolved = Path(path).resolve()
            return copy.deepcopy(overrides[resolved]) if resolved in overrides else original(path, reset)

        output = io.StringIO()
        check.load_jsonld = load
        try:
            with contextlib.redirect_stdout(output):
                check.main()
        finally:
            check.load_jsonld = original
        return parse_report(output.getvalue())

    # ------------------------------------------------------------------
    # Writing
    # ------------------------------------------------------------------

    def write(self) -> list:
        """Write every touched library; returns the files written."""
        written = []
        for name in self.touched():
            path = Path(self.paths[name])
            if name == PEOPLE:
                if name in self.changed:
                    raise NotImplementedError("an existing person was changed - the People Library is formatted by "
                                              "hand; change it by hand")
                insert_as_text(path, self.new[name])
            else:
                if not is_split(path):
                    # Unsplit libraries other than the People Library go through save_jsonld as well; make sure that
                    # rewrites nothing else.
                    _check_round_trip(path)
                save_jsonld(self.docs[name], path)
            written.append(path)
        return written


def parse_report(text: str) -> dict:
    sections, current = {}, None
    for line in text.splitlines():
        match = _SECTION.match(line)
        if match:
            current = sections.setdefault(match.group(1), [])
        elif current is not None and line.startswith("  ") and not line.strip().startswith("(") and line.strip() != "none":
            current.append(line.strip())
        elif not line.startswith(" "):
            current = None
    return sections


def new_findings(before: dict, after: dict) -> tuple:
    """(blocking, information): the lines of the report after that the report before does not have."""
    blocking, information = {}, {}
    for section, lines in after.items():
        added = [line for line in lines if line not in set(before.get(section, []))]
        if added:
            (information if section in INFORMATION_ONLY else blocking)[section] = added
    return blocking, information


def _check_round_trip(path: Path):
    import tempfile
    with tempfile.TemporaryDirectory() as folder:
        copy_path = Path(folder) / path.name
        save_jsonld(load_jsonld(path), copy_path)
        if copy_path.read_bytes() != path.read_bytes():
            raise RuntimeError(f"{path.name} would not be written back unchanged by save_jsonld - stopped")


def insert_as_text(path: Path, entities: list):
    """New entities before the end of the graph of a hand-formatted library (the People Library): the file stays
    as it is, byte for byte, apart from the new entities."""
    text = path.read_bytes().decode("utf-8")
    newline = "\r\n" if "\r\n" in text else "\n"
    blocks = []
    for entity in entities:
        block = "\n".join(" " * 6 + line for line in json.dumps(entity, indent=2, ensure_ascii=False).splitlines())
        blocks.append(block.replace("\n", newline))
    end = text.rstrip().rfind("]")
    last = text.rfind("}", 0, end)
    text = text[:last + 1] + "," + newline + ("," + newline).join(blocks) + text[last + 1:]
    json.loads(text)
    path.write_bytes(text.encode("utf-8"))
