"""
What each type of library entry becomes in the libraries. One class per type of
entry_schema.yaml:

- prepare(job): everything that has to be known before anything is built - IDs, what the names point at
  (job.reference), for a substance its PubChem record. Reports through job: problem (stops), question (written
  under 'open' in the file, stops), follow_up (an entry of another type is missing, stops), note (information).
- build(job): adds the entities to job.libraries (in memory) and the links back on existing entries.

Rule 4.1 for every value: a substance's molar mass is a cpo:Parameter with a reference and the one lookup task of
the file; a container's values belong to the task that read the records of the file, or - assumed ones - to the
task that assumed them. The start time of every such task is stamped by the assumption task of the library
(rule 4.6). Persons and organizations carry no values.
"""
import json
import math
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from helpers.inventory_entries import GLASS_BODY, STEEL_BODY, Entries, container_template, content_occurrence  # noqa: E402
from helpers.units import SCALAR_UNITS_BY_QUANTITY_KIND  # noqa: E402
from helpers.library_import import chemical_entity, identifier  # noqa: E402
from interfaces.pubchem import pubchem_lookup  # noqa: E402
from entry_file import as_list, empty  # noqa: E402
from library_set import ref  # noqa: E402


def species_types(substance: dict) -> list:
    """The classes of a species in a phase: those of its substance in the Chemical Entity Library - a molecule is a
    chebi:Molecule, a material such as activated carbon only a chebi:ChemicalEntity (otherwise the molecule
    requirements would ask activated carbon for a SMILES)."""
    types = [t for t in (substance.get("@type") if isinstance(substance.get("@type"), list) else [substance.get("@type")])
             if t and t not in ("hlo:Fixed", "hlo:Template")]
    if "chebi:ChemicalEntity" not in types:
        types.append("chebi:ChemicalEntity")
    return types + ["hlo:Fixed"]


def pascal(name: str) -> str:
    """'Nickel(II) chloride hexahydrate' -> 'NickelIIChlorideHexahydrate' (the IDs of the libraries, F2)."""
    return "".join(word[:1].upper() + word[1:] for word in re.split(r"[^A-Za-z0-9]+", str(name)) if word)


class EntryType:
    library = None
    id_prefix = None

    def __init__(self):
        self.ids = {}            # entry number -> ID

    def entity_id(self, job, n: int, entry: dict) -> str | None:
        given = entry.get("id")
        if given:
            given = str(given)
            if ":" not in given:
                given = f"{self.id_prefix}:{given}"
            if not given.startswith(f"{self.id_prefix}:"):
                job.problem(f"entries[{n}].id", f"must start with '{self.id_prefix}:'")
                return None
            return given
        local = pascal(entry.get("name", ""))
        if not local or local[0].isdigit():
            job.problem(f"entries[{n}].id", f"no ID can be made from the name '{entry.get('name')}' - give one")
            return None
        return f"{self.id_prefix}:{local}"

    def prepare(self, job):
        seen = {}
        for n, entry in job.numbered():
            entity_id = self.entity_id(job, n, entry)
            if entity_id is None:
                continue
            if entity_id in seen:
                job.problem(f"entries[{n}]", f"the same ID {entity_id} as entries[{seen[entity_id]}]")
            elif job.libraries.exists(entity_id):
                job.problem(f"entries[{n}]", f"{entity_id} exists already in {job.libraries.find(entity_id)[0]} - "
                                             f"nothing is overwritten (another ID: field 'id')")
            seen[entity_id] = n
            self.ids[n] = entity_id

    def build(self, job):
        raise NotImplementedError


class Person(EntryType):
    library = "people_library.jsonld"
    id_prefix = "person"

    def prepare(self, job):
        super().prepare(job)
        self.members = {n: [job.reference("organization", o, f"entries[{n}].member_of") for o in as_list(e.get("member_of"))]
                        for n, e in job.numbered()}

    def build(self, job):
        for n, entry in job.numbered():
            person_id = self.ids[n]
            person = {"@id": person_id, "@type": ["schema:Person", "hlo:Fixed"], "schema:name": entry["name"],
                      "schema:givenName": entry["given_name"], "schema:familyName": entry["family_name"]}
            for key, prop in (("honorific_prefix", "schema:honorificPrefix"), ("orcid", "cpo:hasORCID"), ("email", "schema:email")):
                if not empty(entry.get(key)):
                    person[prop] = str(entry[key]).strip()
            if self.members[n]:
                person["org:memberOf"] = [ref(o) for o in self.members[n]]
            others = [identifier(person_id, i["system"], str(i["value"]), i.get("url")) for i in as_list(entry.get("identifiers"))]
            if others:
                person["schema:identifier"] = ref(others[0]["@id"]) if len(others) == 1 else [ref(o["@id"]) for o in others]
            person["schema:description"] = job.origin(entry.get("note"))
            job.libraries.add(self.library, [person, *others])
            for organization in self.members[n]:
                job.libraries.link(organization, "org:hasMember", person_id)


class Organization(EntryType):
    library = "organization_library.jsonld"
    id_prefix = "organization"

    def prepare(self, job):
        super().prepare(job)
        self.parents = {n: job.reference("organization", e["unit_of"], f"entries[{n}].unit_of")
                        for n, e in job.numbered() if not empty(e.get("unit_of"))}

    def build(self, job):
        for n, entry in job.numbered():
            organization_id = self.ids[n]
            organization = {"@id": organization_id, "@type": ["org:Organization", "hlo:Fixed"], "schema:name": entry["name"]}
            if not empty(entry.get("url")):
                organization["schema:url"] = str(entry["url"]).strip()
            if self.parents.get(n):
                organization["org:unitOf"] = ref(self.parents[n])
            if not empty(entry.get("note")):
                organization["rdfs:comment"] = str(entry["note"]).strip()
            organization["schema:comment"] = job.origin()
            job.libraries.add(self.library, [organization])
            if self.parents.get(n):
                job.libraries.link(self.parents[n], "org:hasUnit", organization_id)


class Substance(EntryType):
    """A substance from its PubChem record (helpers/library_import.chemical_entity). The PubChem answers are kept
    next to the entry file (<file>_pubchem.json, as pubchem_lookup.py writes them): a second run asks PubChem
    nothing that is there already."""
    library = "chemical_entity_library.jsonld"
    id_prefix = "chem"
    times_task = "task:assuming_chemical_entity_library_task_times"

    def prepare(self, job):
        super().prepare(job)
        self.records = {n: job.reference("record", e["eln_record"], f"entries[{n}].eln_record")
                        for n, e in job.numbered() if not empty(e.get("eln_record"))}
        self.rows, self.cas = {}, {}
        cache = job.path.with_name(f"{job.path.stem}_pubchem.json")
        rows = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else []
        looked_up = False
        keys = {}
        known = {e.get("cpo:hasInChIKey"): e["@id"] for e in job.libraries.entities(self.library) if e.get("cpo:hasInChIKey")}
        for n, entry in job.numbered():
            smiles = str(entry["smiles"]).strip()
            row = next((r for r in rows if r.get("query_smiles") == smiles), None)
            if row is None:
                job.note(f"entries[{n}]", f"looking up {smiles} on PubChem")
                row = pubchem_lookup.look_up(str(entry["name"]), smiles)
                rows.append(row)
                looked_up = True
            if not row.get("found"):
                job.problem(f"entries[{n}].smiles", f"PubChem knows no compound for {smiles} - a substance without a PubChem "
                                                    f"record is not made here (F12); add it by hand")
                continue
            self.rows[n] = row
            key = row["InChIKey"]
            if key in known:
                job.problem(f"entries[{n}]", f"the library has this substance already: {known[key]} (same InChIKey {key})")
            if key in keys:
                job.problem(f"entries[{n}]", f"the same substance as entries[{keys[key]}] (InChIKey {key})")
            keys[key] = n
            if row.get("ConnectivitySMILES") != smiles:
                job.note(f"entries[{n}].smiles", f"PubChem writes it {row['ConnectivitySMILES']} (CID {row['CID']}, "
                                                f"{row.get('Title')}) - mostly the same structure written another way; "
                                                f"check the record if a tautomer, isomer or salt is possible")
            if row.get("other_cids"):
                job.note(f"entries[{n}].smiles", f"PubChem found further records: {row['other_cids']}; CID {row['CID']} is used")
            self.cas[n] = self._cas(job, n, entry, row)
        if looked_up:
            cache.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            job.note("pubchem", f"answers kept in {cache.name}")

    def _cas(self, job, n: int, entry: dict, row: dict):
        """(CAS or None, sentence for the comment) - or None when the person has to choose first."""
        candidates = row.get("cas_candidates", [])
        given = None if empty(entry.get("cas")) else str(entry["cas"]).strip()
        if given == "none":
            return None, "PubChem lists no CAS number, and none is known." if not candidates else \
                f"No CAS number, although PubChem lists {', '.join(candidates)} ({job.by()})."
        if given:
            if given not in candidates:
                job.note(f"entries[{n}].cas", f"{given} is not among the CAS numbers PubChem lists ({', '.join(candidates) or 'none'}) "
                                             f"- say in 'note' where it comes from")
                return given, f"CAS {given} not from PubChem ({job.by()})."
            if len(candidates) > 1:
                return given, f"PubChem lists {len(candidates)} CAS-like numbers; {given} chosen ({job.by()})."
            return given, ""
        if len(candidates) == 1:
            return candidates[0], ""
        job.question(n, "cas", f"PubChem lists {'no CAS number' if not candidates else f'{len(candidates)} CAS-like numbers'} "
                               f"for {entry['name']} (CID {row['CID']}): write the one it is sold under into 'cas' of entries[{n}], "
                               f"or 'none'", candidates)
        return None

    def build(self, job):
        lib = Entries(self.times_task, job.stamp, job.person, f"the entries of {job.path.name}")
        task_id = f"task:looking_up_{re.sub(r'[^a-z0-9]+', '_', job.path.stem.lower()).strip('_')}"
        if job.libraries.exists(task_id):
            raise ValueError(f"{task_id} exists already - was this file written before?")
        determined = []
        for n, entry in job.numbered():
            row, (cas, cas_note) = self.rows[n], self.cas[n]
            called = entry.get("called")
            origin = job.origin(None) + (f" Called '{called}' there." if not empty(called) else "")
            note = " ".join(x for x in (cas_note, str(entry.get("note") or "").strip()) if x) or None
            determined += chemical_entity(lib, self.ids[n], row, str(called or entry["name"]), str(entry["smiles"]).strip(),
                                          self.records.get(n), task_id, cas=cas, note=note, origin=origin)
            lib.find(self.ids[n])["schema:name"] = str(entry["name"])
        lib.task(task_id, "cpo:LiteratureLookupTask", f"Looking up the substances of {job.path.name} on PubChem",
                 f"Identifiers, molecular formula and molecular weight looked up on PubChem by SMILES "
                 f"(generator/interfaces/pubchem/pubchem_lookup.py; answers in {job.path.stem}_pubchem.json); entries written "
                 f"with generator/workflow/library_entries/finish_library_entry.py from {job.relative_path}.",
                 determines=determined)
        job.libraries.add(self.library, lib.items)
        for reference in lib.stamped:
            job.libraries.link(self.times_task, "cpo:determines", reference)
        for n, record in self.records.items():
            job.libraries.link(record, "schema:about", self.ids[n])


# ----------------------------------------------------------------------------------------------
# Values with how they are known (module "value" of the schema, as the setup sheet reads them)
# ----------------------------------------------------------------------------------------------

KINDS = {"measured": ("Evidence", "hlo:Measured"), "observed": ("Evidence", "hlo:Observed"),
         "calculated": ("Evidence", "hlo:Calculated"), "literature": ("Reference", "hlo:Literature"),
         "planned": ("Reference", "hlo:Planned"), "assumed": ("Reference", "hlo:Assumed")}
QUANTITY_KINDS = {"mass": "quantitykind:Mass", "volume": "quantitykind:Volume", "length": "quantitykind:Length",
                  "temperature": "quantitykind:Temperature", "pressure": "quantitykind:Pressure",
                  "concentration": "quantitykind:AmountOfSubstanceConcentration"}
TO_METRE = {"unit:M": 1.0, "unit:CentiM": 0.01, "unit:MilliM": 0.001}


def _utc(raw) -> str | None:
    """A time of the file (YAML reads 2025-06-02T09:30:00Z as a datetime) as xsd:dateTime in UTC - None for a date
    without an hour or a time without a zone."""
    if isinstance(raw, datetime):
        when = raw
    elif isinstance(raw, date) or empty(raw):
        return None
    else:
        try:
            when = datetime.fromisoformat(str(raw).strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    if when.tzinfo is None:
        return None
    return when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_value(job, place: str, block: dict, quantity: str) -> dict | None:
    """A value block of the file - {value, unit, role, type, kind, source} - or None, with a problem reported."""
    raw, unit = block.get("value"), block.get("unit")
    role, value_type = KINDS[block["kind"]]
    read = {"role": role, "type": value_type, "kind": block["kind"], "source": str(block["source"]).strip(), "unit": None}
    if quantity == "time":
        when = _utc(raw)
        if when is None:
            job.problem(f"{place}.value", f"'{raw}' is no time with date, hour and zone (2025-06-02T09:30:00Z) - if only "
                                          f"the day is known, write a time and say so in 'source'")
            return None
        if not empty(unit):
            job.problem(f"{place}.unit", "a time has no unit")
            return None
        read["value"] = when
        return read
    try:
        number = float(raw)
    except (TypeError, ValueError):
        job.problem(f"{place}.value", f"'{raw}' is no number")
        return None
    if quantity == "fraction":
        if not 0 <= number <= 1 or not empty(unit):
            job.problem(place, "a mass fraction is a number from 0 to 1, without a unit")
            return None
        read.update(value=number, unit="unit:UNITLESS")
        return read
    allowed = SCALAR_UNITS_BY_QUANTITY_KIND[QUANTITY_KINDS[quantity]]
    unit_id = None if empty(unit) else (str(unit) if ":" in str(unit) else f"unit:{unit}")
    if unit_id not in allowed:
        job.problem(f"{place}.unit", f"'{unit}' - units of a {quantity}: {', '.join(u.split(':', 1)[1] for u in allowed)}")
        return None
    read.update(value=number, unit=unit_id)
    return read


def read_values(job, place: str, raw, quantity: str) -> list | None:
    """One value block or a list of them (a value known in more than one way: measured and planned) - [read, ...], or
    None with a problem reported."""
    blocks = raw if isinstance(raw, list) else [raw]
    reads = [read_value(job, place + (f"[{m}]" if len(blocks) > 1 else ""), block, quantity)
             for m, block in enumerate(blocks, start=1)]
    return None if any(r is None for r in reads) else reads


def put_values(lib, actual_id, quantity_kind, reads, what, task_of, owner=None, kind_on_value=False) -> list:
    """One Actual with one evidence or reference per read (numbered per role: _Evidence_1, _Reference_1, _Reference_2),
    each determined by task_of(read); a literature value names its source (hlo:hasSource). Returns [(member, task)]."""
    out = []
    for n, read in enumerate(reads):
        task = task_of(read)
        source = read["source"] if read["kind"] == "literature" else None
        comment = f"{what}: {read['source']}"
        if n == 0:
            member = lib.value(actual_id, quantity_kind, read["role"], read["value"], read["unit"], read["type"], comment, task,
                               source=source, kind_on_value=kind_on_value, owner=owner)
        else:
            role = read["role"]
            member = f"{actual_id}_{role}_{1 + sum(1 for r in reads[:n] if r['role'] == role)}"
            actual = lib.find(actual_id)
            before = actual.get(f"hlo:has{role}")
            actual[f"hlo:has{role}"] = ([before] if isinstance(before, dict) else before or []) + [ref(member)]
            entry = {"@id": member, "@type": ["cpo:ProcessVariable", f"hlo:{role}"]}
            if kind_on_value:
                entry["qudt:hasQuantityKind"] = ref(quantity_kind)
            entry[f"hlo:has{role}Type"] = ref(read["type"])
            if source:
                entry["hlo:hasSource"] = source
            entry.update({"rdfs:comment": comment, "qudt:value": _decimal(read["value"]), "qudt:hasUnit": ref(read["unit"]),
                          "cpo:hasDeterminationTask": ref(task)})
            lib.add(entry)
        out.append((member, task))
    return out


class FileTasks:
    """The tasks of one entry file behind its values (rule 4.1): what was read off records (labels, catalogues, lab
    notebooks: measured, observed, literature, planned), calculated, or assumed - one task each, made only when it
    determines something; their start times are stamped by the assumption task of the library (rule 4.6).
    override(read) may name another task for a value (the preparation that measured it)."""
    NAMES = {"records": ("cpo:LiteratureLookupTask", "reading", "Reading the records of {file}",
                         "Values read off labels, catalogues and lab records, as the entry file gives them."),
             "calculated": ("cpo:CalculationTask", "calculating", "Calculating the values of {file}",
                            "Values the entry file gives as calculated - how, its comment of each value says."),
             "assumed": ("cpo:AssumptionTask", "assuming", "Assuming what the records of {file} do not say",
                         "Values not recorded, taken as the entry file says - the comment of each value gives the reason.")}

    def __init__(self, job, lib):
        self.job, self.lib = job, lib
        stem = re.sub(r"[^a-z0-9]+", "_", job.path.stem.lower()).strip("_")
        self.ids = {key: f"task:{verb}_{stem}" for key, (_, verb, _, _) in self.NAMES.items()}
        for task_id in self.ids.values():
            if job.libraries.exists(task_id):
                raise ValueError(f"{task_id} exists already - was this file written before?")
        self.determined = {task_id: [] for task_id in self.ids.values()}

    def task_of(self, read) -> str:
        key = {"calculated": "calculated", "assumed": "assumed"}.get(read["kind"], "records")
        return self.ids[key]

    def note(self, pairs):
        """Remember what each task determines - pairs as put_values returns them, or (member, task)."""
        for member, task in pairs:
            self.determined.setdefault(task, []).append(member)
        return [member for member, _ in pairs]

    def instant(self, instant_id, read, what, task=None):
        task = task or self.task_of(read)
        member = self.lib.instant(instant_id, read["role"], read["type"], read["value"], f"{what}: {read['source']}", task,
                                  source=read["source"] if read["kind"] == "literature" else None)
        self.note([(member, task)])
        return member

    def finish(self):
        for key, (task_type, _, name, description) in self.NAMES.items():
            task_id = self.ids[key]
            if self.determined.get(task_id):
                self.lib.task(task_id, task_type, name.format(file=self.job.path.name),
                              f"{description} {self.job.origin()}", determines=self.determined[task_id])


def snake(name: str) -> str:
    """'Nickel(II) chloride bottle no. 1' -> 'nickel_ii_chloride_bottle_no_1' (the IDs of devices)."""
    return re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")


class Container(EntryType):
    """A container of the inventory as delivered, with its content - as helpers/inventory_entries.py: container, but
    every value from the file with how it is known (kind), optional ones left out or empty Actuals. The container goes
    to the Device Library, its content and the receipt to the Material Library (rule 2.15, Entries.side); the tasks
    that read and assumed the values to the Device Library, stamped by its assumption task."""
    library = "device_library.jsonld"
    id_prefix = "device"
    times_task = "task:assuming_device_library_task_times"
    PHASES = {"solid": "cpo:SolidPhase", "liquid": "cpo:LiquidPhase", "gas": "cpo:GasPhase"}
    STRUCTURES = {"crystalline": "cpo:Crystalline", "amorphous": "cpo:Amorphous", "semicrystalline": "cpo:SemiCrystalline"}

    def entity_id(self, job, n, entry):
        if entry.get("id"):
            return super().entity_id(job, n, entry)
        local = snake(entry.get("name", ""))
        if not local:
            job.problem(f"entries[{n}].id", "no ID can be made from the name - give one")
            return None
        return f"device:{local}"

    def prepare(self, job):
        super().prepare(job)
        self.refs, self.values = {}, {}
        for n, entry in job.numbered():
            place, content = f"entries[{n}]", entry["content"]
            refs = {"template": job.reference("template", entry["template"], f"{place}.template"),
                    "cabinet": job.reference("cabinet", entry["cabinet"], f"{place}.cabinet")}
            if refs["template"] and not job.libraries.exists(f"{refs['template']}_Cavity"):
                job.problem(f"{place}.template", f"{refs['template']} has no cavity ({refs['template']}_Cavity) - not a "
                                                 f"container template")
            if not empty(entry.get("received_by")):
                refs["received_by"] = job.reference("person", entry["received_by"], f"{place}.received_by")
            if not empty(content.get("manufacturer")):
                refs["manufacturer"] = job.reference("organization", content["manufacturer"], f"{place}.content.manufacturer")
            species = as_list(content.get("species"))
            refs["species"] = [job.reference("substance", s["substance"], f"{place}.content.species[{m}].substance")
                               for m, s in enumerate(species, start=1)]
            values = {"delivered": read_value(job, f"{place}.delivered", entry["delivered"], "time")}
            if not empty(entry.get("opened")):
                values["opened"] = read_value(job, f"{place}.opened", entry["opened"], "time")
            for key, quantity in (("mass", "mass"), ("volume", "volume"), ("expires", "time"), ("retest", "time")):
                if not empty(content.get(key)):
                    values[key] = read_value(job, f"{place}.content.{key}", content[key], quantity)
            values["fractions"] = [read_value(job, f"{place}.content.species[{m}].fraction", s["fraction"], "fraction")
                                   if not empty(s.get("fraction")) else None for m, s in enumerate(species, start=1)]
            self.refs[n], self.values[n] = refs, values
            if n in self.ids:
                local = self.ids[n].split(":", 1)[1]
                for other in (f"material:{local}_Content", f"task:receiving_{local}"):
                    if job.libraries.exists(other):
                        job.problem(place, f"{other} exists already - another name or 'id'")

    def build(self, job):
        stem = re.sub(r"[^a-z0-9]+", "_", job.path.stem.lower()).strip("_")
        records, assuming = f"task:reading_{stem}", f"task:assuming_{stem}"
        for task_id in (records, assuming):
            if job.libraries.exists(task_id):
                raise ValueError(f"{task_id} exists already - was this file written before?")
        lib = Entries(self.times_task, job.stamp, job.person, f"the entries of {job.path.name}")
        determined = {records: [], assuming: []}

        def task_of(read):
            return assuming if read["kind"] == "assumed" else records

        def source_of(read):
            return read["source"] if read["kind"] == "literature" else None

        def value(actual_id, quantity_kind, read, what, owner=None, kind_on_value=False):
            determined[task_of(read)].append(lib.value(
                actual_id, quantity_kind, read["role"], read["value"], read["unit"], read["type"], f"{what}: {read['source']}",
                task_of(read), source=source_of(read), kind_on_value=kind_on_value, owner=owner))

        def instant(instant_id, read, what):
            determined[task_of(read)].append(lib.instant(instant_id, read["role"], read["type"], read["value"],
                                                         f"{what}: {read['source']}", task_of(read), source=source_of(read)))

        for n, entry in job.numbered():
            refs, values, content = self.refs[n], self.values[n], entry["content"]
            d = self.ids[n]
            local = d.split(":", 1)[1]
            material, phase, receiving = f"material:{local}_Content", f"material:{local}_Content_Phase", f"task:receiving_{local}"
            template = refs["template"]
            cavity = f"{template}_Cavity"
            note = f"{str(entry['note']).strip()} " if not empty(entry.get("note")) else ""
            device = lib.add({
                "@id": d, "@type": ["cpo:ChemicalContainer", "hlo:Fixed"], "schema:name": str(entry["name"]),
                "rdfs:comment": f"{note}One container of the inventory, of the kind {template} (form, body and opening come from "
                                f"there). Every experiment that draws from it is an entry of its usage history; what was drawn "
                                f"stands in that experiment's crate.",
                "schema:comment": job.origin(),
                "hlo:specializationOf": ref(template), "cpo:locatedInsideOf": ref(refs["cabinet"]),
                "cpo:containsMaterial": ref(material), "cpo:hasContainedMaterialHistory": [ref(material)],
                "cpo:hasDeliveryTime": ref(f"{receiving}_EndTime"), "cpo:hasUsageHistory": [ref(receiving)],
                # Never used yet: it was last "used" at the delivery (rule 5.5).
                "cpo:lastUsedPurpose": ref(receiving), "cpo:lastUsedTime": ref(f"{receiving}_EndTime")})
            if values.get("opened"):
                device["cpo:hasOpeningTime"] = ref(f"{d}_OpeningTime")
                instant(f"{d}_OpeningTime", values["opened"], "First opened")

            with lib.side("material"):
                # The receipt is the commissioning of a container (rule 5.5); its end is the delivery time.
                receipt = lib.add({
                    "@id": receiving, "@type": ["cpo:CommissioningTask", "hlo:Fixed"], "schema:name": f"Receiving {entry['name']}",
                    "schema:description": "The delivery came into the lab and was put into the cabinet.",
                    "cpo:hasStartTime": ref(f"{receiving}_StartTime"), "cpo:hasEndTime": ref(f"{receiving}_EndTime"),
                    "cpo:hasDuration": ref(f"{receiving}_Duration"), "cpo:usedEquipment": [ref(d)]})
                if refs.get("received_by"):
                    receipt["cpo:performedBy"] = [ref(refs["received_by"])]
                delivered = values["delivered"]
                instant(f"{receiving}_StartTime", dict(delivered, kind="assumed", role="Reference", type="hlo:Assumed",
                                                       source="not recorded - taken as the delivery time"), "Start of the receipt")
                instant(f"{receiving}_EndTime", delivered, "Delivery, the time the container came into the lab")
                lib.add({"@id": f"{receiving}_Duration", "@type": ["time:Duration", "hlo:Fixed", "hlo:Actual"]})

                stuff = lib.add({
                    "@id": material, "@type": ["cpo:MaterialVolume", "hlo:Fixed"], "schema:name": str(content["label"]),
                    "rdfs:comment": "The content of the container as delivered; what experiments drew from it stands in their crates.",
                    "cpo:materialContainedIn": ref(d), "cpo:fillsForm": ref(cavity), "dcterms:hasPart": ref(phase),
                    "cpo:hasLotNumber": str(content["lot"]), "cpo:hasMass": ref(f"{material}_Mass"),
                    "cpo:hasVolume": ref(f"{material}_Volume")})
                if not empty(content.get("sku")):
                    stuff["schema:sku"] = str(content["sku"])
                if refs.get("manufacturer"):
                    stuff["cpo:hasManufacturer"] = ref(refs["manufacturer"])
                for key, kind, word in (("mass", "quantitykind:Mass", "Net mass at delivery"),
                                        ("volume", "quantitykind:Volume", "Volume at delivery")):
                    actual = f"{material}_{key.capitalize()}"
                    if values.get(key):
                        value(actual, kind, values[key], word)
                    else:   # the quantity exists, its value is not known
                        lib.add({"@id": actual, "@type": ["cpo:ProcessVariable", "hlo:Fixed", "hlo:Actual"],
                                 "qudt:hasQuantityKind": ref(kind)})
                for key, prop, word in (("expires", "ExpiryTime", "Expiry date of the lot"),
                                        ("retest", "RetestTime", "Re-test date of the lot")):
                    if values.get(key):
                        stuff[f"cpo:has{prop}"] = ref(f"{material}_{prop}")
                        instant(f"{material}_{prop}", values[key], word)

                species_ids = []
                for chem_id, fraction in zip(refs["species"], values["fractions"]):
                    species_id = f"{phase}_{chem_id.split(':', 1)[1]}"
                    species_ids.append(species_id)
                    substance = job.libraries.find(chem_id)[1]
                    name = substance.get("schema:name", chem_id)
                    species = lib.add({"@id": species_id, "@type": species_types(substance),
                                       "schema:name": name, "hlo:specializationOf": ref(chem_id), "dcterms:isPartOf": ref(phase)})
                    if fraction:
                        species["cpo:hasConcentration"] = ref(f"{species_id}_Concentration")
                        value(f"{species_id}_Concentration", "quantitykind:MassFraction", fraction,
                              f"Mass fraction of {name} in the content", owner=species_id, kind_on_value=True)
                state = content["state"]
                lib.add({"@id": phase, "@type": [self.PHASES[state], "hlo:Fixed"], "schema:name": f"{content['label']} ({state})",
                         "dcterms:isPartOf": ref(material), "cpo:canCreateEnergyField": False,
                         "cpo:hasDispersionState": ref("cpo:Continuous"), "cpo:hasMass": ref(f"{material}_Mass"),
                         "cpo:hasVolume": ref(f"{material}_Volume"), "dcterms:hasPart": [ref(s) for s in species_ids],
                         "cpo:fillsForm": ref(cavity),
                         **({"cpo:hasSolidStructure": ref(self.STRUCTURES[content["solid_structure"]])} if state == "solid" else {})})
                # The content in the lab from its delivery (Phase_Time_R1): seen arriving - unless the delivery is
                # only assumed, then that it arrived is an assumption too (as in prepared_container).
                status_task = assuming if delivered["kind"] == "assumed" else records
                member = content_occurrence(lib, phase, f"{receiving}_EndTime", "The content arrived with the delivery.",
                                            status_task)
                if status_task == assuming:
                    status = lib.find(member)
                    status_id = member.replace("_Evidence_1", "_Reference_1")
                    lib.find(member.rsplit("_Evidence_1", 1)[0]).pop("hlo:hasEvidence")
                    lib.find(member.rsplit("_Evidence_1", 1)[0])["hlo:hasReference"] = ref(status_id)
                    status.update({"@id": status_id, "@type": ["cpo:OccurrenceStatus", "hlo:Reference"],
                                   "hlo:hasReferenceType": ref("hlo:Assumed"),
                                   "hlo:isReferenceOf": status.pop("hlo:isEvidenceOf"),
                                   "rdfs:comment": "The content is taken as having arrived with the assumed delivery."})
                    status.pop("hlo:hasEvidenceType")
                    lib.material_ids.discard(member)       # renamed: it stays with the content, in the Material Library
                    lib.material_ids.add(status_id)
                    member = status_id
                determined[status_task].append(member)

        if determined[records]:
            lib.task(records, "cpo:LiteratureLookupTask", f"Reading the records of the containers of {job.path.name}",
                     f"Labels, delivery notes and certificates of the containers, read and entered with "
                     f"generator/workflow/library_entries/finish_library_entry.py from {job.relative_path}. {job.origin()}",
                     determines=determined[records])
        lib.task(assuming, "cpo:AssumptionTask", f"Assuming what the records of {job.path.name} do not say",
                 "Values the records do not give, taken as the entry file says - the comment of each value gives the reason.",
                 determines=determined[assuming])
        devices, materials = lib.split()
        job.libraries.add("device_library.jsonld", devices)
        job.libraries.add("material_library.jsonld", materials)
        for reference in lib.stamped:
            job.libraries.link(self.times_task, "cpo:determines", reference)


# ----------------------------------------------------------------------------------------------
# Sites, laboratories, cabinets (Organization Library)
# ----------------------------------------------------------------------------------------------

def _decimal(value):
    return {"@value": f"{value:.12g}", "@type": "xsd:decimal"}


class Cabinet(EntryType):
    library = "organization_library.jsonld"
    id_prefix = "lab"

    def prepare(self, job):
        super().prepare(job)
        self.rooms = {n: job.reference("laboratory", e["room"], f"entries[{n}].room") for n, e in job.numbered()}

    def build(self, job):
        for n, entry in job.numbered():
            cabinet = {"@id": self.ids[n], "@type": ["cpo:StorageCabinet", "hlo:Fixed"], "schema:name": str(entry["name"]),
                       "cpo:locatedInsideOf": ref(self.rooms[n])}
            if not empty(entry.get("note")):
                cabinet["rdfs:comment"] = str(entry["note"]).strip()
            cabinet["schema:comment"] = job.origin()
            job.libraries.add(self.library, [cabinet])


class Site(EntryType):
    """A site with its gravitational field - standard gravity from the literature (task:looking_up_standard_gravity, the
    same task as for every site) and an occurrence without beginning or end, as energyfield:EnergyField_CEB_PFD_Fixed."""
    library = "organization_library.jsonld"
    id_prefix = "site"
    gravity_task = "task:looking_up_standard_gravity"
    CODATA = "CODATA recommended values of the fundamental physical constants (NIST), standard acceleration of gravity."

    def prepare(self, job):
        super().prepare(job)
        self.organizations = {n: job.reference("organization", e["organization"], f"entries[{n}].organization")
                              for n, e in job.numbered() if not empty(e.get("organization"))}
        for n, site_id in self.ids.items():
            local = site_id.split(":", 1)[1]
            if job.libraries.exists(f"energyfield:EnergyField_{local}_Fixed"):
                job.problem(f"entries[{n}]", f"energyfield:EnergyField_{local}_Fixed exists already - another 'id'")

    def build(self, job):
        for n, entry in job.numbered():
            site_id = self.ids[n]
            local = site_id.split(":", 1)[1]
            field, strength = f"energyfield:EnergyField_{local}_Fixed", f"energyfield:FieldStrength_{local}_Fixed"
            occurrence, status = f"energyfield:Occurrence_{local}_Fixed", f"energyfield:OccurrenceStatus_{local}_Fixed"
            strength_ref, status_ref = (f"energyfield:FieldStrength_{local}_Reference_1_Fixed",
                                        f"energyfield:OccurrenceStatus_{local}_Reference_1_Fixed")
            site = {"@id": site_id, "@type": ["org:Site", "hlo:Fixed"], "schema:name": str(entry["name"])}
            if not empty(entry.get("note")):
                site["rdfs:comment"] = str(entry["note"]).strip()
            site.update({"schema:comment": job.origin(), "cpo:hasEnergyField": ref(field)})
            entities = [
                site,
                {"@id": field, "@type": ["cpo:EnergyField", "hlo:Fixed"], "rdfs:label": "Local gravitational field",
                 "cpo:isEnergyFieldOf": ref(site_id), "cpo:hasEnergyFieldType": ref("cpo:GravitationalField"),
                 "cpo:hasFieldStrength": ref(strength), "cpo:hasOccurrence": ref(occurrence)},
                {"@id": strength, "@type": ["cpo:ProcessVariable", "hlo:Fixed", "hlo:Actual"], "hlo:hasReference": ref(strength_ref)},
                {"@id": strength_ref, "@type": ["cpo:ProcessVariable", "hlo:Reference"],
                 "hlo:hasReferenceType": ref("hlo:Literature"), "hlo:hasSource": self.CODATA,
                 "rdfs:comment": "Standard gravity (CODATA), not a site-specific measurement - replace with a local value if one is measured.",
                 "qudt:hasQuantityKind": ref("quantitykind:Acceleration"), "qudt:value": _decimal(9.80665),
                 "qudt:hasUnit": ref("unit:M-PER-SEC2"), "cpo:hasDeterminationTask": ref(self.gravity_task)},
                {"@id": occurrence, "@type": ["cpo:Occurrence", "hlo:Fixed"],
                 "rdfs:comment": "The gravitational field of the site is always there: one occurrence without beginning or end. Its "
                                 "status says it occurred (from the literature), its times are empty Actuals - the quantities exist, "
                                 "a value would be pointless.",
                 "cpo:hasOccurrenceStatus": ref(status), "cpo:hasStartTime": ref(f"energyfield:Occurrence_{local}_StartTime_Fixed"),
                 "cpo:hasEndTime": ref(f"energyfield:Occurrence_{local}_EndTime_Fixed"),
                 "cpo:hasDuration": ref(f"energyfield:Occurrence_{local}_Duration_Fixed")},
                {"@id": status, "@type": ["cpo:OccurrenceStatus", "hlo:Fixed", "hlo:Actual"], "hlo:hasReference": ref(status_ref)},
                {"@id": status_ref, "@type": ["cpo:OccurrenceStatus", "hlo:Reference"],
                 "hlo:hasReferenceType": ref("hlo:Literature"), "hlo:hasSource": self.CODATA, "hlo:isReferenceOf": ref(status),
                 "rdfs:comment": "Gravity acts everywhere on Earth at all times - general physics, not an observation at this site.",
                 "cpo:hasOccurrenceValue": ref("cpo:Occurred"), "cpo:hasDeterminationTask": ref(self.gravity_task)},
                {"@id": f"energyfield:Occurrence_{local}_StartTime_Fixed", "@type": ["time:Instant", "hlo:Fixed", "hlo:Actual"]},
                {"@id": f"energyfield:Occurrence_{local}_EndTime_Fixed", "@type": ["time:Instant", "hlo:Fixed", "hlo:Actual"]},
                {"@id": f"energyfield:Occurrence_{local}_Duration_Fixed", "@type": ["time:Duration", "hlo:Fixed", "hlo:Actual"]},
            ]
            job.libraries.add(self.library, entities)
            job.libraries.link(self.gravity_task, "cpo:determines", strength_ref)
            job.libraries.link(self.gravity_task, "cpo:determines", status_ref)
            if self.organizations.get(n):
                job.libraries.link(self.organizations[n], "org:hasSite", site_id)


class Laboratory(EntryType):
    """A laboratory room as the rooms of the library are made (lab:L208): a cuboid form with its inner dimensions and
    calculated volume, the room air (cpo:Environment, one gas phase) with dry-air density and composition from the
    literature (the shared lookup tasks), temperature and pressure (given, or assumed by task:assuming_lab_air_state),
    calculated volume and mass, and an occurrence without beginning or end. The dimensions are read or assumed by the
    tasks of the file, like the values of a container."""
    library = "organization_library.jsonld"
    id_prefix = "lab"
    times_task = "task:assuming_organization_library_task_times"
    DENSITY_TASK = "task:looking_up_air_density"
    COMPOSITION_TASK = "task:looking_up_air_composition"
    AIR_STATE_TASK = "task:assuming_lab_air_state"
    AIR = (("chem:Molecule_0005", "Oxygen", 0.2314,
            "Mass fraction of oxygen in dry air - a textbook value, not measured in this room. Follows from the standard mole "
            "fractions (O2 20.946 %, N2 78.084 %, Ar 0.934 %, CO2 0.041 %) and the molar masses, giving a mean molar mass of "
            "28.97 g/mol: 0.20946 x 31.999 / 28.97 = 0.2314."),
           ("chem:Molecule_0006", "Nitrogen", 0.7551,
            "Mass fraction of nitrogen in dry air - a textbook value, not measured in this room. Same derivation as for "
            "oxygen: 0.78084 x 28.013 / 28.97 = 0.7551."))
    DENSITY = 1.2

    def prepare(self, job):
        super().prepare(job)
        self.sites, self.values = {}, {}
        for n, entry in job.numbered():
            place = f"entries[{n}]"
            self.sites[n] = job.reference("site", entry["site"], f"{place}.site")
            values = {key: read_value(job, f"{place}.{key}", entry[key], "length") for key in ("width", "length", "height")}
            for key in ("temperature", "pressure"):
                if not empty(entry.get(key)):
                    values[key] = read_value(job, f"{place}.{key}", entry[key], key)
            self.values[n] = values
            if n in self.ids:
                local = self.ids[n].split(":", 1)[1]
                if job.libraries.exists(f"environment:{local}_Air"):
                    job.problem(place, f"environment:{local}_Air exists already - another 'id'")

    def build(self, job):
        stem = re.sub(r"[^a-z0-9]+", "_", job.path.stem.lower()).strip("_")
        records, assuming = f"task:reading_{stem}", f"task:assuming_{stem}"
        for task_id in (records, assuming):
            if job.libraries.exists(task_id):
                raise ValueError(f"{task_id} exists already - was this file written before?")
        lib = Entries(self.times_task, job.stamp, job.person, f"the entries of {job.path.name}")
        determined = {records: [], assuming: []}
        shared = {self.DENSITY_TASK: [], self.COMPOSITION_TASK: [], self.AIR_STATE_TASK: []}
        calculations = []

        def given(actual_id, kind, read, what):
            task = assuming if read["kind"] == "assumed" else records
            determined[task].append(lib.value(actual_id, kind, read["role"], read["value"], read["unit"], read["type"],
                                              f"{what}: {read['source']}", task,
                                              source=read["source"] if read["kind"] == "literature" else None))
            return determined[task][-1]

        def calculated(actual_id, kind, value, unit, comment, task_id, name, inputs):
            lib.add({"@id": actual_id, "@type": ["cpo:ProcessVariable", "hlo:Fixed", "hlo:Actual"],
                     "qudt:hasQuantityKind": ref(kind), "hlo:hasEvidence": ref(f"{actual_id}_Evidence_1")})
            lib.add({"@id": f"{actual_id}_Evidence_1", "@type": ["cpo:ProcessVariable", "hlo:Evidence"],
                     "hlo:hasEvidenceType": ref("hlo:Calculated"), "rdfs:comment": comment, "qudt:value": _decimal(value),
                     "qudt:hasUnit": ref(unit), "cpo:hasDeterminationTask": ref(task_id)})
            calculations.append((task_id, name, comment, [f"{actual_id}_Evidence_1"], inputs))
            return f"{actual_id}_Evidence_1"

        def shared_value(actual_id, kind, value, unit, value_type, comment, task_id, source=None, owner=None, kind_on_value=False):
            member = lib.value(actual_id, kind, "Reference", value, unit, value_type, comment, task_id, source=source,
                               owner=owner, kind_on_value=kind_on_value)
            shared[task_id].append(member)
            return member

        for n, entry in job.numbered():
            lab_id, values, name = self.ids[n], self.values[n], str(entry["name"])
            local = lab_id.split(":", 1)[1]
            form, air, phase = f"{lab_id}_Form", f"environment:{local}_Air", f"environment:{local}_Air_GasPhase"
            room = {"@id": lab_id, "@type": ["cpo:Laboratory", "hlo:Fixed"], "schema:name": name,
                    "cpo:definesForm": ref(form), "cpo:isRoomOf": ref(self.sites[n])}
            if not empty(entry.get("note")):
                room["rdfs:comment"] = str(entry["note"]).strip()
            room["schema:comment"] = job.origin()
            lib.add(room)

            dims = [given(f"{lab_id}_{key.capitalize()}", kind, values[key], f"Inner {key} of the room")
                    for key, kind in (("width", "quantitykind:Width"), ("length", "quantitykind:Length"),
                                      ("height", "quantitykind:Height"))]
            metres = {k: values[k]["value"] * TO_METRE[values[k]["unit"]] for k in ("width", "length", "height")}
            volume = metres["width"] * metres["length"] * metres["height"]
            sizes = f"{metres['width']:g} m x {metres['length']:g} m x {metres['height']:g} m = {volume:g} m3"
            lib.add({"@id": form, "@type": ["cpo:CuboidForm"],
                     "rdfs:comment": "Shape of the room itself. Only inner dimensions are recorded: the walls of a building are not "
                                     "modelled, so the room is described by the space it encloses.",
                     "cpo:hasWidth": ref(f"{lab_id}_Width"), "cpo:hasLength": ref(f"{lab_id}_Length"),
                     "cpo:hasHeight": ref(f"{lab_id}_Height"), "cpo:hasOuterVolume": ref(f"{lab_id}_Volume"),
                     "cpo:hasWidthToLengthRatio": ref(f"{form}_WidthToLengthRatio"),
                     "cpo:hasHeightToLengthRatio": ref(f"{form}_HeightToLengthRatio")})
            for ratio in ("WidthToLengthRatio", "HeightToLengthRatio"):
                lib.add({"@id": f"{form}_{ratio}", "@type": ["cpo:ProcessVariable", "hlo:Fixed", "hlo:Actual"],
                         "qudt:hasQuantityKind": ref("quantitykind:LengthRatio")})
            room_volume = calculated(f"{lab_id}_Volume", "quantitykind:Volume", volume, "unit:M3",
                                     f"Inner volume of the room: {sizes}.", f"task:calculating_{local}_InnerVolume",
                                     f"Calculating the inner volume of {name}", dims)
            air_volume = calculated(f"{air}_Volume", "quantitykind:Volume", volume, "unit:M3",
                                    f"Volume the room air occupies - the inner volume of the room ({sizes}); anything standing "
                                    f"in the room is ignored. Shared by the air and its gas phase.",
                                    f"task:calculating_{local}_Air_Volume", f"Calculating the volume of the air in {name}",
                                    [room_volume])
            density = shared_value(f"{air}_Density", "quantitykind:Density", self.DENSITY, "unit:KiloGM-PER-M3", "hlo:Literature",
                                   "Density of dry air at about 20 degC and 1 atm (~1.2 kg/m3) - a textbook value, not measured "
                                   "in this room.", self.DENSITY_TASK, source="en.wikipedia.org/wiki/Density_of_air.")
            calculated(f"{air}_Mass", "quantitykind:Mass", volume * self.DENSITY, "unit:KiloGM",
                       f"Calculated from the room air volume ({volume:g} m3) and the density of dry air ({self.DENSITY} kg/m3): "
                       f"{volume * self.DENSITY:g} kg.", f"task:calculating_{local}_Air_Mass",
                       f"Calculating the mass of the air in {name}", [air_volume, density])
            for key, kind, default, unit, word, taken in (
                    ("temperature", "quantitykind:Temperature", 20, "unit:DEG_C", "Room temperature", "20 degC"),
                    ("pressure", "quantitykind:Pressure", 101325, "unit:PA", "Ambient pressure", "1 atm (101325 Pa)")):
                actual = f"{air}_{key.capitalize()}"
                if values.get(key):
                    given(actual, kind, values[key], f"{word} of the lab")
                else:
                    shared_value(actual, kind, default, unit, "hlo:Assumed",
                                 f"{word} of the lab, taken as {taken} - not read off an instrument. The looked-up air density "
                                 f"refers to the same condition.", self.AIR_STATE_TASK)

            species = []
            for chem_id, species_name, fraction, comment in self.AIR:
                species_id = f"{air}_{chem_id.split(':', 1)[1]}"
                species.append(species_id)
                lib.add({"@id": species_id, "@type": ["chebi:Molecule", "chebi:ChemicalEntity", "hlo:Fixed"],
                         "schema:name": species_name, "hlo:specializationOf": ref(chem_id), "dcterms:isPartOf": ref(phase),
                         "cpo:hasConcentration": ref(f"{species_id}_Concentration")})
                shared_value(f"{species_id}_Concentration", "quantitykind:MassFraction", fraction, "unit:UNITLESS",
                             "hlo:Literature", comment, self.COMPOSITION_TASK, source="en.wikipedia.org/wiki/Atmosphere_of_Earth.",
                             owner=species_id, kind_on_value=True)
            lib.add({"@id": air, "@type": ["cpo:Environment", "hlo:Fixed"], "schema:name": f"Ambient air of {name}",
                     "cpo:locatedInsideOf": ref(lab_id), "cpo:fillsForm": ref(form), "cpo:hasVolume": ref(f"{air}_Volume"),
                     "dcterms:hasPart": ref(phase)})
            occurrence, status = f"{phase}_Occurrence", f"{phase}_OccurrenceStatus"
            lib.add({"@id": phase, "@type": ["cpo:GasPhase", "hlo:Fixed"], "schema:name": f"{name} Air (Gas Phase)",
                     "dcterms:isPartOf": ref(air), "cpo:canCreateEnergyField": False, "cpo:hasDispersionState": ref("cpo:Continuous"),
                     "cpo:hasVolume": ref(f"{air}_Volume"), "cpo:hasDensity": ref(f"{air}_Density"), "cpo:hasMass": ref(f"{air}_Mass"),
                     "dcterms:hasPart": [ref(s) for s in species], "cpo:fillsForm": ref(form),
                     "cpo:hasTemperature": ref(f"{air}_Temperature"), "cpo:hasPressure": ref(f"{air}_Pressure"),
                     "cpo:hasOccurrence": ref(occurrence)})
            lib.add({"@id": occurrence, "@type": ["cpo:Occurrence", "hlo:Fixed"],
                     "rdfs:comment": "The air of the room is always there: one occurrence without beginning or end. Its status says "
                                     "it occurred, its times are empty Actuals - the quantities exist, a value would be pointless.",
                     "cpo:hasOccurrenceStatus": ref(status), "cpo:hasStartTime": ref(f"{occurrence}_StartTime"),
                     "cpo:hasEndTime": ref(f"{occurrence}_EndTime"), "cpo:hasDuration": ref(f"{occurrence}_Duration")})
            lib.add({"@id": status, "@type": ["cpo:OccurrenceStatus", "hlo:Fixed", "hlo:Actual"],
                     "hlo:hasReference": ref(f"{status}_Reference_1")})
            lib.add({"@id": f"{status}_Reference_1", "@type": ["cpo:OccurrenceStatus", "hlo:Reference"],
                     "hlo:hasReferenceType": ref("hlo:Assumed"), "hlo:isReferenceOf": ref(status),
                     "rdfs:comment": "The lab is always filled with air - an assumption about the room, not an observation during "
                                     "an experiment.",
                     "cpo:hasOccurrenceValue": ref("cpo:Occurred"), "cpo:hasDeterminationTask": ref(self.AIR_STATE_TASK)})
            shared[self.AIR_STATE_TASK].append(f"{status}_Reference_1")
            for suffix, kind in (("StartTime", "time:Instant"), ("EndTime", "time:Instant"), ("Duration", "time:Duration")):
                lib.add({"@id": f"{occurrence}_{suffix}", "@type": [kind, "hlo:Fixed", "hlo:Actual"]})

        for task_id, name, comment, results, inputs in calculations:
            lib.task(task_id, "cpo:CalculationTask", name, comment, determines=results, inputs=inputs)
        if determined[records]:
            lib.task(records, "cpo:LiteratureLookupTask", f"Reading the records of the rooms of {job.path.name}",
                     f"Room sizes and conditions as the entry file gives them, entered with "
                     f"generator/workflow/library_entries/finish_library_entry.py from {job.relative_path}. {job.origin()}",
                     determines=determined[records])
        if determined[assuming]:
            lib.task(assuming, "cpo:AssumptionTask", f"Assuming what the records of {job.path.name} do not say",
                     "Room sizes or conditions not measured, taken as the entry file says - the comment of each value gives "
                     "the reason.", determines=determined[assuming])
        job.libraries.add(self.library, lib.items)
        for task_id, references in shared.items():
            for reference in references:
                job.libraries.link(task_id, "cpo:determines", reference)
        for reference in lib.stamped:
            job.libraries.link(self.times_task, "cpo:determines", reference)
        for n in self.ids:
            job.libraries.link(self.sites[n], "cpo:hasRoom", self.ids[n])


# ----------------------------------------------------------------------------------------------
# Labware, simple devices, containers filled in the lab (Device and Material Library)
# ----------------------------------------------------------------------------------------------

def _body(word, entity, density, task, source, structure):
    return {"entity": entity, "density": density, "density_task": task, "source": source, "structure": structure, "word": word,
            "density_comment": f"Generic {word}, {density} kg/m3 - not measured.", "comment": f"Generic {word} - the grade is not known."}


# The materials a body can be made of - substance, density with its lookup task and source, structure; as GLASS_BODY and
# STEEL_BODY (helpers/inventory_entries.py) and the bodies of the K1 parts. Every lookup task is in the Device Library.
BODIES = {
    "glass": GLASS_BODY, "steel": STEEL_BODY,
    "polypropylene": _body("polypropylene", "chem:ChemicalEntity_0003", 900, "task:looking_up_polypropylene_density",
                           "Polypropylene homopolymer, 895-920 kg/m3 (en.wikipedia.org/wiki/Polypropylene).", "cpo:Crystalline"),
    "ptfe": _body("PTFE", "chem:ChemicalEntity_0004", 2200, "task:looking_up_ptfe_density",
                  "MakeItFrom.com, polytetrafluoroethylene (PTFE); en.wikipedia.org/wiki/Polytetrafluoroethylene.", "cpo:Crystalline"),
    "hdpe": _body("HDPE", "chem:HDPE", 950, "task:looking_up_hdpe_density",
                  "en.wikipedia.org/wiki/High-density_polyethylene (0.93-0.97 g/cm3).", "cpo:SemiCrystalline"),
    "aluminium": _body("aluminium", "chem:Aluminium", 2700, "task:looking_up_aluminium_density",
                       "Aluminium alloys 2660-2810 kg/m3; en.wikipedia.org/wiki/Aluminium_alloy.", "cpo:Crystalline"),
}
LABWARE_CLASSES = {"vessel": "cpo:Vessel", "chemical_container": "cpo:ChemicalContainer", "lid": "cpo:Lid", "septum": "cpo:Septum"}
DEVICE_CLASSES = {"device": "cpo:Device", "sensor": "sosa:Sensor", "vessel": "cpo:Vessel", "reactor": "cpo:Reactor",
                  "pump": "cpo:Pump", "stirrer": "cpo:Stirrer", "valve": "cpo:Valve",
                  "mass_flow_controller": "cpo:MassFlowController", "mass_flow_meter": "cpo:MassFlowMeter"}


def _metres(read) -> float:
    return read["value"] * TO_METRE[read["unit"]]


def _commissioning(lib, tasks, device_id, label, read):
    """The first entry of a device's usage history (rule 5.5): its commissioning, ended at the time the file gives; its
    start is not recorded - taken as the same moment."""
    task = f"task:commissioning_{device_id.split(':', 1)[1]}"
    lib.add({"@id": task, "@type": ["cpo:CommissioningTask", "hlo:Fixed"], "schema:name": f"Commissioning {label}",
             "schema:description": "Put into service in the lab.", "cpo:hasStartTime": ref(f"{task}_StartTime"),
             "cpo:hasEndTime": ref(f"{task}_EndTime"), "cpo:hasDuration": ref(f"{task}_Duration"), "cpo:usedEquipment": [ref(device_id)]})
    tasks.instant(f"{task}_StartTime", dict(read, kind="assumed", role="Reference", type="hlo:Assumed",
                                            source="not recorded - taken as the end of the commissioning"), "Start of the commissioning")
    tasks.instant(f"{task}_EndTime", read, "End of the commissioning, the device in service from here on")
    lib.add({"@id": f"{task}_Duration", "@type": ["time:Duration", "hlo:Fixed", "hlo:Actual"]})
    return {"cpo:hasUsageHistory": [ref(task)], "cpo:lastUsedPurpose": ref(task), "cpo:lastUsedTime": ref(f"{task}_EndTime")}


class Labware(EntryType):
    """A template of labware (helpers/inventory_entries.py: container_template - a cup with its cavity, body and
    openings) and its exemplars, each with its own place and a commissioning that starts its usage history."""
    library = "device_library.jsonld"
    id_prefix = "device"
    times_task = "task:assuming_device_library_task_times"

    def entity_id(self, job, n, entry):
        if not empty(entry.get("template")):
            return None                # only pieces of a template that is there already
        if entry.get("id"):
            return super().entity_id(job, n, entry)
        return f"device:{snake(entry.get('name', ''))}"

    def prepare(self, job):
        super().prepare(job)
        self.refs, self.values = {}, {}
        for n, entry in job.numbered():
            place = f"entries[{n}]"
            if not empty(entry.get("template")):
                self._prepare_pieces(job, n, entry, place)
                continue
            refs = {"manufacturer": job.reference("organization", entry["manufacturer"], f"{place}.manufacturer")
                    if not empty(entry.get("manufacturer")) else None,
                    "stock": job.reference("place", entry["stock_location"], f"{place}.stock_location")
                    if not empty(entry.get("stock_location")) else None,
                    "exemplars": [job.reference("place", e["location"], f"{place}.exemplars[{m}].location")
                                  for m, e in enumerate(as_list(entry.get("exemplars")), start=1)]}
            # The dimensions each kind needs: a vessel or bottle is a cup with a cavity (wall); a lid a ring around its
            # opening (inner diameter), as device:vial_cap_template - or, with a wall, a cup upside down (a screw cap, whose
            # cavity takes in the neck it sits on); a septum a solid disc, as
            # device:vial_septum_template. A crate asks for the content of a cavity - "nothing but the gas around it" is
            # an answer (creation/device_functions.py).
            lid_cup = entry["device_class"] == "lid" and not empty(entry.get("wall"))
            needed = {"lid": ("outer_diameter", "outer_height", "wall") if lid_cup else ("outer_diameter", "outer_height", "inner_diameter"),
                      "septum": ("outer_diameter", "outer_height")}.get(entry["device_class"], ("outer_diameter", "outer_height", "wall"))
            for key in ("wall", "inner_diameter"):
                if key in needed and empty(entry.get(key)):
                    job.problem(f"{place}.{key}", f"missing - a {entry['device_class']} needs it")
                elif key not in needed and not empty(entry.get(key)):
                    job.problem(f"{place}.{key}", f"a {'lid with a wall (a cup upside down)' if lid_cup else entry['device_class']} "
                                                  f"has no {key.replace('_', ' ')} - leave it out")
            values = {key: read_value(job, f"{place}.{key}", entry[key], "length") for key in needed if not empty(entry.get(key))}
            for key, read in values.items():
                if read and read["kind"] not in ("literature", "assumed"):
                    job.problem(f"{place}.{key}.kind", "a template's dimensions are catalogue values (literature) or assumed - "
                                                      "what was measured on one piece belongs to that piece")
            values["exemplars"] = [read_value(job, f"{place}.exemplars[{m}].commissioned", e["commissioned"], "time")
                                   for m, e in enumerate(as_list(entry.get("exemplars")), start=1)]
            if entry.get("single_use") is True and as_list(entry.get("exemplars")):
                job.problem(f"{place}.exemplars", "a single-use item has no exemplars - every use takes a fresh piece (rule 3.11)")
            if values.get("wall") and values.get("outer_diameter") and \
                    2 * _metres(values["wall"]) >= _metres(values["outer_diameter"]):
                job.problem(f"{place}.wall", "the wall is as thick as the piece is wide")
            if values.get("inner_diameter") and values.get("outer_diameter") and \
                    _metres(values["inner_diameter"]) >= _metres(values["outer_diameter"]):
                job.problem(f"{place}.inner_diameter", "the opening is as wide as the lid")
            self.refs[n], self.values[n] = refs, values
            if n in self.ids:
                local = self.ids[n].split(":", 1)[1]
                others = [f"{self.ids[n]}_Form", f"material:{local}_Body"]
                others += [f"port:{local}_{o['name']}" for o in as_list(entry.get("openings"))] or [f"port:{local}_opening"]
                others += self.entity_ids_of_pieces(entry)
                for other in others:
                    if job.libraries.exists(other):
                        job.problem(place, f"{other} exists already - another name or 'id'")

    def entity_ids_of_pieces(self, entry):
        return [str(e["id"]) if e.get("id") else f"device:{snake(e['name'])}" for e in as_list(entry.get("exemplars"))]

    def _prepare_pieces(self, job, n, entry, place):
        """Pieces of a template of the library: no template is made, only the exemplars."""
        self.ids.pop(n, None)          # the name names no new template
        template = job.reference("template", entry["template"], f"{place}.template")
        if not as_list(entry.get("exemplars")):
            job.problem(f"{place}.exemplars", "with 'template' the file adds pieces - name at least one")
        for key in ("device_class", "body", "outer_diameter", "outer_height", "wall", "openings", "single_use", "stock_location",
                    "manufacturer"):
            if not empty(entry.get(key)):
                job.problem(f"{place}.{key}", "belongs to the template, which is in the library already - leave it out")
        if template and job.libraries.find(template)[1].get("cpo:isSingleUse") is True:
            job.problem(f"{place}.template", f"{template} is single-use - it has no exemplars (rule 3.11)")
        self.refs[n] = {"template": template,
                        "exemplars": [job.reference("place", e["location"], f"{place}.exemplars[{m}].location")
                                      for m, e in enumerate(as_list(entry.get("exemplars")), start=1)]}
        self.values[n] = {"exemplars": [read_value(job, f"{place}.exemplars[{m}].commissioned", e["commissioned"], "time")
                                        for m, e in enumerate(as_list(entry.get("exemplars")), start=1)]}
        for other in self.entity_ids_of_pieces(entry):
            if job.libraries.exists(other):
                job.problem(place, f"{other} exists already - another name or 'id'")

    def _without_cavity(self, job, lib, tasks, local, entry, values, refs, spec):
        """A lid as a ring around its opening (cpo:AnnulusForm, as device:vial_cap_template) or a septum as a solid disc
        (cpo:SolidCylinderForm, as device:vial_septum_template): no cavity, so no crate asks for a content. The outer
        volume, the volume of the body (the ring, or the whole disc) and its mass are calculated. Returns the template's
        ID and the density reference."""
        d, form = f"device:{local}", f"device:{local}_Form"
        body, phase = f"material:{local}_Body", f"material:{local}_Body_SolidPhase"
        lid = entry["device_class"] == "lid"
        outer, height = _metres(values["outer_diameter"]), _metres(values["outer_height"])
        inner = _metres(values["inner_diameter"]) if lid else 0.0
        words = {"outer_diameter": ("OuterDiameter" if lid else "Diameter", "quantitykind:Diameter", "Outer diameter"),
                 "outer_height": ("Height", "quantitykind:Height", "Height"),
                 "inner_diameter": ("InnerDiameter", "quantitykind:Diameter", "Diameter of the opening")}
        members = {}
        for key in [k for k in ("outer_diameter", "inner_diameter", "outer_height") if k in values]:
            suffix, kind, word = words[key]
            members[key] = tasks.note(put_values(lib, f"{d}_{suffix}", kind, [values[key]], word, tasks.task_of))[0]
        outer_volume = math.pi / 4 * outer ** 2 * height
        body_volume = math.pi / 4 * (outer ** 2 - inner ** 2) * height
        mass = body_volume * spec["density"]
        density = lib.value(f"{phase}_Density", "quantitykind:Density", "Reference", spec["density"], "unit:KiloGM-PER-M3",
                            "hlo:Literature", spec["density_comment"], spec["density_task"], source=spec["source"])
        calculations = [
            ("OuterVolume", f"{d}_OuterVolume", "Cylinder from the outer diameter and the height",
             f"pi/4 x ({outer:g} m)^2 x {height:g} m = {outer_volume:.6g} m3.", outer_volume, "quantitykind:Volume", "unit:M3",
             [members["outer_diameter"], members["outer_height"]]),
            ("Body_SolidPhase_Volume", f"{phase}_Volume", "The ring around the opening" if lid else "The whole disc",
             (f"pi/4 x (({outer:g} m)^2 - ({inner:g} m)^2) x {height:g} m = {body_volume:.6g} m3 - the cap taken as a solid ring; "
              f"its top and thread are left out." if lid else f"The disc is solid: {body_volume:.6g} m3."),
             body_volume, "quantitykind:Volume", "unit:M3", list(members.values())),
            ("Body_SolidPhase_Mass", f"{phase}_Mass", f"{spec['word'].capitalize()} volume times {spec['word']} density",
             f"{body_volume:.6g} m3 x {spec['density']} kg/m3 = {mass:.6g} kg.", mass, "quantitykind:Mass", "unit:KiloGM",
             [f"{phase}_Volume_Evidence_1", density]),
        ]
        for key, actual_id, name, text, value, kind, unit, inputs in calculations:
            task_id = f"task:calculating_{local}_{key}"
            lib.value(actual_id, kind, "Evidence", value, unit, "hlo:Calculated", text, task_id)
            lib.task(task_id, "cpo:CalculationTask", name, text, determines=[f"{actual_id}_Evidence_1"], inputs=inputs)
        if lid:
            lib.add({"@id": form, "@type": "cpo:AnnulusForm",
                     "rdfs:comment": "A ring around the opening - the cap holds nothing, its openings are its ports.",
                     "cpo:hasInnerDiameter": ref(f"{d}_InnerDiameter"), "cpo:hasOuterDiameter": ref(f"{d}_OuterDiameter"),
                     "cpo:hasHeight": ref(f"{d}_Height"), "cpo:hasOuterVolume": ref(f"{d}_OuterVolume"),
                     "cpo:hasHeightToDiameterRatio": ref(f"{form}_HeightToDiameterRatio"),
                     "cpo:hasDiameterRatio": ref(f"{form}_DiameterRatio")})
            ratios = ("HeightToDiameterRatio", "DiameterRatio")
        else:
            lib.add({"@id": form, "@type": "cpo:SolidCylinderForm", "rdfs:comment": "A solid disc - the septum holds nothing.",
                     "cpo:hasDiameter": ref(f"{d}_Diameter"), "cpo:hasHeight": ref(f"{d}_Height"),
                     "cpo:hasOuterVolume": ref(f"{d}_OuterVolume"),
                     "cpo:hasHeightToDiameterRatio": ref(f"{form}_HeightToDiameterRatio")})
            ratios = ("HeightToDiameterRatio",)
        for ratio in ratios:
            lib.add({"@id": f"{form}_{ratio}", "@type": ["cpo:ProcessVariable", "hlo:Fixed", "hlo:Actual"],
                     "qudt:hasQuantityKind": ref("quantitykind:LengthRatio")})
        lib.add({"@id": body, "@type": ["cpo:BodyMaterial", "hlo:Fixed"], "schema:name": f"Body material of {local}",
                 "rdfs:comment": spec["comment"], "cpo:hasVolume": ref(f"{phase}_Volume"), "cpo:fillsForm": ref(form),
                 "dcterms:hasPart": ref(phase), "cpo:isBodyMaterialOf": ref(d)})
        lib.add({"@id": phase, "@type": ["cpo:SolidPhase", "hlo:Fixed"], "schema:name": f"{local} Body",
                 "dcterms:isPartOf": ref(body), "cpo:canCreateEnergyField": False, "cpo:hasDispersionState": ref("cpo:Continuous"),
                 "cpo:hasDensity": ref(f"{phase}_Density"), "cpo:hasVolume": ref(f"{phase}_Volume"), "cpo:hasMass": ref(f"{phase}_Mass"),
                 "dcterms:hasPart": ref(spec["entity"]), "cpo:fillsForm": ref(form), "cpo:hasSolidStructure": ref(spec["structure"])})
        ports = [(f"port:{local}_{o['name']}", o.get("note")) for o in as_list(entry.get("openings"))] or [(f"port:{local}_opening", None)]
        template = {"@id": d, "@type": [LABWARE_CLASSES[entry["device_class"]], "hlo:Fixed", "hlo:Template"],
                    "schema:name": f"{entry['name']} (template)",
                    "rdfs:comment": (str(entry["note"]).strip() + " " if not empty(entry.get("note")) else "")
                    + f"TEMPLATE of {entry['name']}, not one identifiable piece: the pieces of this kind specialize it "
                      f"(hlo:specializationOf) and take over its form, {spec['word']} and openings. "
                    + ("A ring around its opening, without a cavity." if lid else "A solid disc, without a cavity."),
                    "schema:comment": job.origin(), "cpo:isCompositeDevice": False, "cpo:canReceivePower": False}
        if entry.get("single_use") is True:
            template["cpo:isSingleUse"] = True
        if refs["stock"]:
            template["cpo:locatedInsideOf"] = ref(refs["stock"])
        template["cpo:hasPort"] = ref(ports[0][0]) if len(ports) == 1 else [ref(p) for p, _ in ports]
        if refs["manufacturer"]:
            template["cpo:hasManufacturer"] = ref(refs["manufacturer"])
        template.update({"cpo:madeOfMaterial": ref(body), "cpo:definesForm": ref(form), "cpo:hasEnvelopeForm": ref(form)})
        lib.add(template)
        for port_id, text in ports:
            lib.add({"@id": port_id, "@type": ["cpo:DeviceOpening", "hlo:Fixed"], "cpo:isPortOf": ref(d),
                     **({"rdfs:comment": text} if text else {})})
        return d, density

    def _pieces(self, job, lib, tasks, template, device_class, word, exemplars, locations, reads):
        for exemplar, location, read in zip(exemplars, locations, reads):
            d = str(exemplar["id"]) if exemplar.get("id") else f"device:{snake(exemplar['name'])}"
            device = lib.add({"@id": d, "@type": [device_class, "hlo:Fixed"], "schema:name": str(exemplar["name"]),
                              "rdfs:comment": (str(exemplar["note"]).strip() + " " if not empty(exemplar.get("note")) else "")
                              + f"One piece of the kind {template} (form, {word} and openings come from there).",
                              "schema:comment": job.origin(), "hlo:specializationOf": ref(template),
                              "cpo:locatedInsideOf": ref(location)})
            device.update(_commissioning(lib, tasks, d, str(exemplar["name"]), read))

    def build(self, job):
        lib = Entries(self.times_task, job.stamp, job.person, f"the entries of {job.path.name}")
        tasks = FileTasks(job, lib)
        densities = []
        for n, entry in job.numbered():
            refs, values = self.refs[n], self.values[n]
            if refs.get("template"):
                template = job.libraries.find(refs["template"])[1]
                device_class = next(t for t in as_list(template["@type"]) if not t.startswith("hlo:"))
                self._pieces(job, lib, tasks, refs["template"], device_class, "body", as_list(entry["exemplars"]),
                             refs["exemplars"], values["exemplars"])
                continue
            local = self.ids[n].split(":", 1)[1]
            spec = BODIES[entry["body"]]
            if entry["device_class"] == "septum" or (entry["device_class"] == "lid" and "wall" not in values):
                template, density = self._without_cavity(job, lib, tasks, local, entry, values, refs, spec)
                densities.append((spec["density_task"], density))
                self._pieces(job, lib, tasks, template, LABWARE_CLASSES[entry["device_class"]], spec["word"],
                             as_list(entry.get("exemplars")), refs["exemplars"], values["exemplars"])
                continue
            dimensions = {}
            for key, word in (("outer_diameter", "Outer diameter"), ("outer_height", "Outer height"), ("wall", "Wall and bottom thickness")):
                read = values[key]
                dimensions[key] = {"role": read["role"], "type": read["type"], "comment": f"{word}: {read['source']}",
                                   "task": tasks.task_of(read), "source": read["source"] if read["kind"] == "literature" else None}
            made = container_template(
                lib, local, str(entry["name"]), _metres(values["outer_diameter"]), _metres(values["outer_height"]),
                _metres(values["wall"]), refs["manufacturer"], device_class=LABWARE_CLASSES[entry["device_class"]],
                single_use=entry.get("single_use") is True, location=refs["stock"], body_kind=spec,
                comment=(str(entry["note"]).strip() + " " if not empty(entry.get("note")) else "")
                + f"TEMPLATE of {entry['name']}, not one identifiable piece: the pieces of this kind specialize it "
                  f"(hlo:specializationOf) and take over its form, {spec['word']} and openings. "
                + (f"A cup upside down: its cavity takes in the neck it sits on." if entry["device_class"] == "lid"
                   else f"Approximated as a plain {spec['word']} cup."),
                dimensions=dimensions, openings=[(o["name"], o.get("note")) for o in as_list(entry.get("openings"))] or None)
            lib.find(made["device"])["schema:comment"] = job.origin()
            for key in ("OuterDiameter", "OuterHeight", "WallThickness"):
                member = next(m for m in lib.items if m["@id"].startswith(f"{made['device']}_{key}_") and "hlo:Actual" not in m["@type"])
                tasks.note([(member["@id"], member["cpo:hasDeterminationTask"]["@id"])])
            densities.append((spec["density_task"], made["density_reference"]))
            self._pieces(job, lib, tasks, made["device"], LABWARE_CLASSES[entry["device_class"]], spec["word"],
                         as_list(entry.get("exemplars")), refs["exemplars"], values["exemplars"])
        tasks.finish()
        job.libraries.add(self.library, lib.items)
        for task, reference in densities:
            job.libraries.link(task, "cpo:determines", reference)
        for reference in lib.stamped:
            job.libraries.link(self.times_task, "cpo:determines", reference)


class Device(EntryType):
    """A simple device without a content (as device:balance001): its envelope form - a box or a cylinder - with its
    dimensions and the outer volume calculated, its body (density from the literature; volume from the mass, or the
    whole envelope when no mass is given), its place and a commissioning that starts its usage history."""
    library = "device_library.jsonld"
    id_prefix = "device"
    times_task = "task:assuming_device_library_task_times"

    def entity_id(self, job, n, entry):
        if entry.get("id"):
            return super().entity_id(job, n, entry)
        return f"device:{snake(entry.get('name', ''))}"

    def prepare(self, job):
        super().prepare(job)
        self.refs, self.values = {}, {}
        for n, entry in job.numbered():
            place = f"entries[{n}]"
            self.refs[n] = {"location": job.reference("place", entry["location"], f"{place}.location"),
                            "manufacturer": job.reference("organization", entry["manufacturer"], f"{place}.manufacturer")
                            if not empty(entry.get("manufacturer")) else None}
            keys = ("length", "width", "height") if entry["shape"] == "cuboid" else ("diameter", "height")
            values = {key: read_values(job, f"{place}.{key}", entry[key], "length") for key in keys}
            values["commissioned"] = read_value(job, f"{place}.commissioned", entry["commissioned"], "time")
            if not empty(entry.get("mass")):
                values["mass"] = read_values(job, f"{place}.mass", entry["mass"], "mass")
            self.values[n] = values
            if n in self.ids:
                local = self.ids[n].split(":", 1)[1]
                for other in (f"{self.ids[n]}_Form", f"material:{local}_Body", f"task:commissioning_{local}"):
                    if job.libraries.exists(other):
                        job.problem(place, f"{other} exists already - another name or 'id'")

    def build(self, job):
        lib = Entries(self.times_task, job.stamp, job.person, f"the entries of {job.path.name}")
        tasks = FileTasks(job, lib)
        densities, calculations = [], []

        def calculated(key, actual_id, kind, value, unit, name, text, inputs):
            task_id = f"task:calculating_{key}"
            member = lib.value(actual_id, kind, "Evidence", value, unit, "hlo:Calculated", text, task_id)
            calculations.append((task_id, name, text, member, inputs))
            return member

        for n, entry in job.numbered():
            refs, values = self.refs[n], self.values[n]
            d = self.ids[n]
            local, form = d.split(":", 1)[1], f"{d}_Form"
            phase, spec = f"material:{local}_Body_SolidPhase", BODIES[entry["body"]]
            dims = {}
            for key in [k for k in ("length", "width", "diameter", "height") if k in values]:
                kind = "quantitykind:Diameter" if key == "diameter" else f"quantitykind:{key.capitalize()}"
                members = tasks.note(put_values(lib, f"{d}_{key.capitalize()}", kind, values[key],
                                                f"{key.capitalize()} of the device", tasks.task_of))
                dims[key] = (_metres(values[key][0]), members[0])
            if entry["shape"] == "cuboid":
                volume = dims["length"][0] * dims["width"][0] * dims["height"][0]
                text = f"{dims['length'][0]:g} m x {dims['width'][0]:g} m x {dims['height'][0]:g} m = {volume:.6g} m3."
                lib.add({"@id": form, "@type": "cpo:CuboidForm", "rdfs:comment": "The envelope of the device - a box around it.",
                         "cpo:hasLength": ref(f"{d}_Length"), "cpo:hasWidth": ref(f"{d}_Width"), "cpo:hasHeight": ref(f"{d}_Height"),
                         "cpo:hasOuterVolume": ref(f"{d}_OuterVolume"), "cpo:hasWidthToLengthRatio": ref(f"{form}_WidthToLengthRatio"),
                         "cpo:hasHeightToLengthRatio": ref(f"{form}_HeightToLengthRatio")})
                ratios = ("WidthToLengthRatio", "HeightToLengthRatio")
                name = "Box from its three edges"
            else:
                volume = math.pi / 4 * dims["diameter"][0] ** 2 * dims["height"][0]
                text = f"pi/4 x ({dims['diameter'][0]:g} m)^2 x {dims['height'][0]:g} m = {volume:.6g} m3."
                lib.add({"@id": form, "@type": "cpo:SolidCylinderForm", "rdfs:comment": "The envelope of the device - a cylinder around it.",
                         "cpo:hasDiameter": ref(f"{d}_Diameter"), "cpo:hasHeight": ref(f"{d}_Height"),
                         "cpo:hasOuterVolume": ref(f"{d}_OuterVolume"),
                         "cpo:hasHeightToDiameterRatio": ref(f"{form}_HeightToDiameterRatio")})
                ratios = ("HeightToDiameterRatio",)
                name = "Cylinder from its diameter and height"
            for ratio in ratios:
                lib.add({"@id": f"{form}_{ratio}", "@type": ["cpo:ProcessVariable", "hlo:Fixed", "hlo:Actual"],
                         "qudt:hasQuantityKind": ref("quantitykind:LengthRatio")})
            outer = calculated(f"{local}_OuterVolume", f"{d}_OuterVolume", "quantitykind:Volume", volume, "unit:M3", name, text,
                               [m for _, m in dims.values()])

            rho = spec["density"]
            density = lib.value(f"{phase}_Density", "quantitykind:Density", "Reference", rho, "unit:KiloGM-PER-M3",
                                "hlo:Literature", spec["density_comment"], spec["density_task"], source=spec["source"])
            densities.append((spec["density_task"], density))
            if values.get("mass"):
                mass = tasks.note(put_values(lib, f"{phase}_Mass", "quantitykind:Mass", values["mass"], "Mass of the device",
                                             tasks.task_of))[0]
                kilograms = values["mass"][0]["value"] * {"unit:KiloGM": 1, "unit:GM": 1e-3, "unit:MilliGM": 1e-6}[values["mass"][0]["unit"]]
                calculated(f"{local}_Body_SolidPhase_Volume", f"{phase}_Volume", "quantitykind:Volume", kilograms / rho, "unit:M3",
                           f"Mass over {spec['word']} density",
                           f"From the mass ({kilograms:g} kg) and the {spec['word']} density ({rho} kg/m3): {kilograms / rho:.6g} m3 - "
                           f"not the envelope ({volume:.6g} m3), the device is not solid {spec['word']}.", [mass, density])
            else:
                body_volume = calculated(f"{local}_Body_SolidPhase_Volume", f"{phase}_Volume", "quantitykind:Volume", volume,
                                         "unit:M3", "The envelope taken as solid",
                                         f"No mass is known: the body is taken as filling its envelope, {volume:.6g} m3.", [outer])
                calculated(f"{local}_Body_SolidPhase_Mass", f"{phase}_Mass", "quantitykind:Mass", volume * rho, "unit:KiloGM",
                           f"{spec['word'].capitalize()} volume times {spec['word']} density",
                           f"{volume:.6g} m3 x {rho} kg/m3 = {volume * rho:.6g} kg.", [body_volume, density])
            lib.add({"@id": f"material:{local}_Body", "@type": ["cpo:BodyMaterial", "hlo:Fixed"], "schema:name": f"Body material of {local}",
                     "rdfs:comment": spec["comment"], "cpo:hasVolume": ref(f"{phase}_Volume"), "cpo:fillsForm": ref(form),
                     "dcterms:hasPart": ref(phase), "cpo:isBodyMaterialOf": ref(d)})
            lib.add({"@id": phase, "@type": ["cpo:SolidPhase", "hlo:Fixed"], "schema:name": f"{local} Body",
                     "dcterms:isPartOf": ref(f"material:{local}_Body"), "cpo:canCreateEnergyField": False,
                     "cpo:hasDispersionState": ref("cpo:Continuous"), "cpo:hasDensity": ref(f"{phase}_Density"),
                     "cpo:hasVolume": ref(f"{phase}_Volume"), "cpo:hasMass": ref(f"{phase}_Mass"),
                     "dcterms:hasPart": ref(spec["entity"]), "cpo:fillsForm": ref(form), "cpo:hasSolidStructure": ref(spec["structure"])})
            device = {"@id": d, "@type": [DEVICE_CLASSES[entry["device_class"]], "hlo:Fixed"], "schema:name": str(entry["name"])}
            if not empty(entry.get("note")):
                device["rdfs:comment"] = str(entry["note"]).strip()
            device.update({"schema:comment": job.origin(), "cpo:isCompositeDevice": False,
                           "cpo:canReceivePower": entry.get("powered") is True})
            if refs["manufacturer"]:
                device["cpo:hasManufacturer"] = ref(refs["manufacturer"])
            if not empty(entry.get("model")):
                device["schema:model"] = str(entry["model"])
            device.update({"cpo:locatedInsideOf": ref(refs["location"]), "cpo:madeOfMaterial": ref(f"material:{local}_Body"),
                           "cpo:definesForm": ref(form), "cpo:hasEnvelopeForm": ref(form)})
            lib.add(device)
            device.update(_commissioning(lib, tasks, d, str(entry["name"]), values["commissioned"]))
        for task_id, name, text, member, inputs in calculations:
            lib.task(task_id, "cpo:CalculationTask", name, text, determines=[member], inputs=inputs)
        tasks.finish()
        job.libraries.add(self.library, lib.items)
        for task, reference in densities:
            job.libraries.link(task, "cpo:determines", reference)
        for reference in lib.stamped:
            job.libraries.link(self.times_task, "cpo:determines", reference)


class PreparedContainer(EntryType):
    """A container filled in the lab, as helpers/inventory_entries.py: prepared_container - the preparation task, one
    transfer from the content of each source, the content - with every value as the file gives it: measured, observed
    or planned in the preparation (determined by the preparation task), read elsewhere, calculated or assumed (the
    tasks of the file). The preparation is sorted into the usage histories of the sources by time
    (workflow/inventory_tool.py: sort_into_history) and starts the container's own (rule 5.5)."""
    library = "device_library.jsonld"
    id_prefix = "device"
    times_task = "task:assuming_device_library_task_times"
    PHASES = Container.PHASES
    STRUCTURES = Container.STRUCTURES

    def entity_id(self, job, n, entry):
        if entry.get("id"):
            return super().entity_id(job, n, entry)
        return f"device:{snake(entry.get('name', ''))}"

    def prepare(self, job):
        super().prepare(job)
        import rdflib
        import path_definitions
        cpo = "http://www.semanticweb.org/lf576/ontologies/2026/7/ChemicalProcessOntology#"
        graph = rdflib.Graph().parse(data=path_definitions.CPO_ONTOLOGY.read_text(encoding="utf-8"), format="xml")
        functions = {str(s).split("#")[-1] for s in graph.subjects(rdflib.RDF.type, rdflib.URIRef(cpo + "Function"))}
        self.refs, self.values = {}, {}
        for n, entry in job.numbered():
            place, content = f"entries[{n}]", entry["content"]
            refs = {"template": job.reference("template", entry["template"], f"{place}.template"),
                    "cabinet": job.reference("place", entry["cabinet"], f"{place}.cabinet"),
                    "prepared_by": job.reference("person", entry["prepared_by"], f"{place}.prepared_by")
                    if not empty(entry.get("prepared_by")) else job.person,
                    "species": [job.reference("substance", s["substance"], f"{place}.content.species[{m}].substance")
                                for m, s in enumerate(as_list(content.get("species")), start=1)],
                    "sources": []}
            if refs["template"] and not job.libraries.exists(f"{refs['template']}_Cavity"):
                job.problem(f"{place}.template", f"{refs['template']} has no cavity - not a container template")
            for m, source in enumerate(as_list(entry.get("sources")), start=1):
                device = job.reference("source", source["container"], f"{place}.sources[{m}].container")
                phase = None
                if device:
                    material = job.libraries.find(job.libraries.find(device)[1]["cpo:containsMaterial"]["@id"])[1]
                    phases = [p["@id"] for p in as_list((material or {}).get("dcterms:hasPart"))]
                    if len(phases) != 1:
                        job.problem(f"{place}.sources[{m}]", f"the content of {device} has {len(phases)} phases - one is needed")
                    else:
                        phase = phases[0]
                refs["sources"].append((device, phase))
            for function in as_list(entry["preparation"]["functions"]):
                if str(function).split(":", 1)[-1] not in functions:
                    job.problem(f"{place}.preparation.functions", f"'{function}' is no function of the CPO (cpo:Function)")
            values = {"start": read_value(job, f"{place}.start", entry["start"], "time"),
                      "end": read_value(job, f"{place}.end", entry["end"], "time"),
                      "sources": [read_values(job, f"{place}.sources[{m}].volume", s["volume"], "volume")
                                  if not empty(s.get("volume")) else None for m, s in enumerate(as_list(entry.get("sources")), start=1)],
                      "species": []}
            for key in ("volume", "mass"):
                if not empty(content.get(key)):
                    values[key] = read_values(job, f"{place}.content.{key}", content[key], key)
            for m, s in enumerate(as_list(content.get("species")), start=1):
                if not empty(s.get("concentration")) and not empty(s.get("fraction")):
                    job.problem(f"{place}.content.species[{m}]", "a concentration or a mass fraction, not both")
                key = "concentration" if not empty(s.get("concentration")) else "fraction" if not empty(s.get("fraction")) else None
                values["species"].append((key, read_values(job, f"{place}.content.species[{m}].{key}", s[key], key) if key else None))
            if values["start"] and values["end"] and values["start"]["value"] > values["end"]["value"]:
                job.problem(f"{place}.end", "the preparation ends before it starts")
            self.refs[n], self.values[n] = refs, values
            if n in self.ids:
                local = self.ids[n].split(":", 1)[1]
                for other in (f"material:{local}_Content", f"task:preparing_{local}", f"task:commissioning_{local}"):
                    if job.libraries.exists(other):
                        job.problem(place, f"{other} exists already - another name or 'id'")

    def build(self, job):
        from workflow.inventory_tool import sort_into_history
        lib = Entries(self.times_task, job.stamp, job.person, f"the entries of {job.path.name}")
        tasks = FileTasks(job, lib)
        preparations = []
        for n, entry in job.numbered():
            refs, values, content = self.refs[n], self.values[n], entry["content"]
            d = self.ids[n]
            local = d.split(":", 1)[1]
            material, phase, task = f"material:{local}_Content", f"material:{local}_Content_Phase", f"task:preparing_{local}"
            cavity = f"{refs['template']}_Cavity"

            def task_of(read, task=task):
                return task if read["kind"] in ("measured", "observed", "planned") else tasks.task_of(read)

            device = {"@id": d, "@type": ["cpo:ChemicalContainer", "hlo:Fixed"], "schema:name": str(entry["name"]),
                      "rdfs:comment": (str(entry["note"]).strip() + " " if not empty(entry.get("note")) else "")
                      + f"A container filled in the lab, of the kind {refs['template']} (form, body and opening come from there). "
                        f"The preparation, its transfers from the sources and the content are described in the material library; "
                        f"every experiment that draws from it is an entry of its usage history.",
                      "schema:comment": job.origin(), "hlo:specializationOf": ref(refs["template"]),
                      "cpo:locatedInsideOf": ref(refs["cabinet"]), "cpo:containsMaterial": ref(material),
                      "cpo:hasContainedMaterialHistory": [ref(material)]}
            lib.add(device)
            # Rule 5.5: the usage history starts with a commissioning - the empty container taken into use, not recorded:
            # taken as the moment the preparation started. Then the preparation, its last use until an experiment draws.
            first = _commissioning(lib, tasks, d, str(entry["name"]),
                                   dict(values["start"], kind="assumed", role="Reference", type="hlo:Assumed",
                                        source="not recorded - the empty container taken into use when the preparation started"))
            device.update({"cpo:hasUsageHistory": first["cpo:hasUsageHistory"] + [ref(task)],
                           "cpo:lastUsedPurpose": ref(task), "cpo:lastUsedTime": ref(f"{task}_EndTime")})
            with lib.side("material"):
                transfers = []
                for source, (source_device, source_phase), reads in zip(as_list(entry["sources"]), refs["sources"], values["sources"]):
                    source_local = source_device.split(":", 1)[1]
                    transfer = f"{phase}_from_{source_local}"
                    transfers.append(transfer)
                    item = lib.add({"@id": transfer, "@type": ["cpo:Transfer", "hlo:Fixed"], "schema:name": f"From {source_local} into {local}",
                                    "cpo:hasTransferType": ref("cpo:PortCrossing"), "cpo:removesFromPhase": ref(source_phase),
                                    "cpo:addsToPhase": ref(phase), "cpo:isAimOf": ref(task)})
                    if not empty(source.get("note")):
                        item["rdfs:comment"] = str(source["note"]).strip()
                    if reads:
                        item["cpo:hasTransferredVolume"] = ref(f"{transfer}_TransferredVolume")
                        tasks.note(put_values(lib, f"{transfer}_TransferredVolume", "quantitykind:Volume", reads,
                                              f"Volume taken from {source_local}", task_of, owner=transfer))
                preparation = entry["preparation"]
                lib.add({"@id": task, "@type": ["cpo:OperationTask", "hlo:Fixed"], "schema:name": str(preparation["name"]),
                         "schema:description": str(preparation["description"]), "cpo:performedBy": [ref(refs["prepared_by"])],
                         "cpo:hasStartTime": ref(f"{task}_StartTime"), "cpo:hasEndTime": ref(f"{task}_EndTime"),
                         "cpo:hasDuration": ref(f"{task}_Duration"),
                         "cpo:usedEquipment": [ref(s) for s, _ in refs["sources"]] + [ref(d)],
                         "cpo:realizesFunction": [ref(f if ":" in str(f) else f"cpo:{f}") for f in as_list(preparation["functions"])],
                         "cpo:aimsAt": [ref(t) for t in transfers]})
                tasks.instant(f"{task}_StartTime", values["start"], "Start of the preparation", task_of(values["start"]))
                tasks.instant(f"{task}_EndTime", values["end"], "End of the preparation - the content exists from here on",
                              task_of(values["end"]))
                lib.add({"@id": f"{task}_Duration", "@type": ["time:Duration", "hlo:Fixed", "hlo:Actual"]})

                lib.add({"@id": material, "@type": ["cpo:MaterialVolume", "hlo:Fixed"], "schema:name": str(content["label"]),
                         "rdfs:comment": "The content as prepared in the lab; what experiments drew from it stands in their crates.",
                         "cpo:materialContainedIn": ref(d), "cpo:fillsForm": ref(cavity), "dcterms:hasPart": ref(phase),
                         "cpo:hasLotNumber": str(content.get("lot") or content["label"]),
                         "cpo:hasMass": ref(f"{material}_Mass"), "cpo:hasVolume": ref(f"{material}_Volume")})
                for key, kind in (("mass", "quantitykind:Mass"), ("volume", "quantitykind:Volume")):
                    if values.get(key):
                        tasks.note(put_values(lib, f"{material}_{key.capitalize()}", kind, values[key],
                                              f"{key.capitalize()} of the content", task_of))
                    else:
                        lib.add({"@id": f"{material}_{key.capitalize()}", "@type": ["cpo:ProcessVariable", "hlo:Fixed", "hlo:Actual"],
                                 "qudt:hasQuantityKind": ref(kind)})
                species_ids = []
                for chem_id, (key, reads) in zip(refs["species"], values["species"]):
                    species_id = f"{phase}_{chem_id.split(':', 1)[1]}"
                    species_ids.append(species_id)
                    substance = job.libraries.find(chem_id)[1]
                    name = substance.get("schema:name", chem_id)
                    item = lib.add({"@id": species_id, "@type": species_types(substance),
                                    "schema:name": name, "hlo:specializationOf": ref(chem_id), "dcterms:isPartOf": ref(phase)})
                    if reads:
                        item["cpo:hasConcentration"] = ref(f"{species_id}_Concentration")
                        kind = "quantitykind:AmountOfSubstanceConcentration" if key == "concentration" else "quantitykind:MassFraction"
                        tasks.note(put_values(lib, f"{species_id}_Concentration", kind, reads,
                                              f"{'Concentration' if key == 'concentration' else 'Mass fraction'} of {name}", task_of,
                                              owner=species_id, kind_on_value=True))
                state = content["state"]
                lib.add({"@id": phase, "@type": [self.PHASES[state], "hlo:Fixed"], "schema:name": f"{content['label']} ({state})",
                         "dcterms:isPartOf": ref(material), "cpo:canCreateEnergyField": False,
                         "cpo:hasDispersionState": ref("cpo:Continuous"), "cpo:hasMass": ref(f"{material}_Mass"),
                         "cpo:hasVolume": ref(f"{material}_Volume"), "dcterms:hasPart": [ref(s) for s in species_ids],
                         "cpo:fillsForm": ref(cavity),
                         **({"cpo:hasSolidStructure": ref(self.STRUCTURES[content["solid_structure"]])} if state == "solid" else {})})
                # The content in the lab from the end of its preparation (Phase_Time_R1); assumed if the end is.
                if values["end"]["kind"] == "assumed":
                    occurrence, status = f"{phase}_Occurrence", f"{phase}_Occurrence_Status"
                    lib.find(phase)["cpo:hasOccurrence"] = ref(occurrence)
                    lib.add({"@id": occurrence, "@type": ["cpo:Occurrence", "hlo:Fixed"],
                             "rdfs:comment": "The content in the lab: from the end of its preparation until it is used up or disposed "
                                             "of (end unknown until then).",
                             "cpo:hasOccurrenceStatus": ref(status), "cpo:hasStartTime": ref(f"{task}_EndTime"),
                             "cpo:hasEndTime": ref(f"{occurrence}_EndTime"), "cpo:hasDuration": ref(f"{occurrence}_Duration")})
                    lib.add({"@id": status, "@type": ["cpo:OccurrenceStatus", "hlo:Fixed", "hlo:Actual"],
                             "hlo:hasReference": ref(f"{status}_Reference_1")})
                    lib.add({"@id": f"{status}_Reference_1", "@type": ["cpo:OccurrenceStatus", "hlo:Reference"],
                             "hlo:hasReferenceType": ref("hlo:Assumed"), "hlo:isReferenceOf": ref(status),
                             "rdfs:comment": "Made before it was used - its preparation is not recorded.",
                             "cpo:hasOccurrenceValue": ref("cpo:Occurred"), "cpo:hasDeterminationTask": ref(tasks.ids["assumed"])})
                    tasks.note([(f"{status}_Reference_1", tasks.ids["assumed"])])
                    for time_id, time_type in ((f"{occurrence}_EndTime", "time:Instant"), (f"{occurrence}_Duration", "time:Duration")):
                        lib.add({"@id": time_id, "@type": [time_type, "hlo:Fixed", "hlo:Actual"]})
                else:
                    tasks.note([(content_occurrence(lib, phase, f"{task}_EndTime",
                                                    "The content exists since its preparation ended.", task), task)])
                lib.find(task)["cpo:determines"] = [ref(m) for m in tasks.determined.pop(task, [])]
            preparations.append((task, [s for s, _ in refs["sources"]]))
        tasks.finish()
        devices, materials = lib.split()
        job.libraries.add("device_library.jsonld", devices)
        job.libraries.add("material_library.jsonld", materials)
        for reference in lib.stamped:
            job.libraries.link(self.times_task, "cpo:determines", reference)
        # Into the usage history of each source, by time (rule 5.4) - as workflow/inventory_tool.py prepare does.
        view = {"@graph": job.libraries.docs["device_library.jsonld"]["@graph"] + job.libraries.docs["material_library.jsonld"]["@graph"]}
        for task, sources in preparations:
            for source in sources:
                sort_into_history(job.libraries.find(source)[1], task, view)
                job.libraries.changed.add("device_library.jsonld")


TYPES = {"person": Person, "organization": Organization, "substance": Substance, "container": Container,
         "cabinet": Cabinet, "site": Site, "laboratory": Laboratory, "labware": Labware, "device": Device,
         "prepared_container": PreparedContainer}
