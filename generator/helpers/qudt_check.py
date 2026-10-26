"""
Checks the units and quantity kinds of the project against QUDT - the version that
libraries/ontology_library.jsonld names (cpo:hasStorageLocation of ontology:quantitykind_File
and ontology:unit_File). Used by check_library_consistency.py; read-only.

What is checked:
- every quantity kind in generator/config/units_and_quantity_kinds.json and every quantity kind the
  ontology names (cpo:valueHasQuantityKind) exists and is not
  deprecated - in QUDT, or in the ontology itself for the project's own kinds (cpo:ReactionRate);
- every unit exists, is not deprecated, and fits its quantity kind: QUDT lists it for the kind
  or for a broader kind (skos:broader), directly or from the unit's side. A unit that only has
  the same dimension vector is reported unless accepted_dimension_matches in the JSON file
  accepts it; a different dimension is an error;
- the dimensionless kinds accept unit:UNITLESS, the duration units fit quantitykind:Time, the
  fixed field-strength units fit their field's kind, the volume conversion factors match
  qudt:conversionMultiplier;
- an accepted exception that QUDT meanwhile lists properly is reported as no longer needed.

The two vocabularies (about 6 MB) are downloaded once into
path_definitions.EXTERNAL_VOCABULARY_CACHE, named after their versioned URL - a new QUDT version
in the ontology library means a new download. Without network and without a cached copy the
check is skipped with a note, it does not fail.
"""

import json
import urllib.request

from rdflib import Graph, Namespace, URIRef, Literal

import path_definitions
from helpers import units

QUDT = Namespace("http://qudt.org/schema/qudt/")
SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")
CPO = Namespace("http://www.semanticweb.org/lf576/ontologies/2026/7/ChemicalProcessOntology#")
NAMESPACES = {
    "quantitykind": "http://qudt.org/vocab/quantitykind/",
    "unit": "http://qudt.org/vocab/unit/",
    "cpo": str(CPO),
    "qkdv": "http://qudt.org/vocab/dimensionvector/",
}
UNITLESS = "unit:UNITLESS"


def _uri(compact: str) -> URIRef:
    prefix, local = compact.split(":", 1)
    return URIRef(NAMESPACES[prefix] + local)


def _compact(uri) -> str:
    text = str(uri)
    for prefix, namespace in NAMESPACES.items():
        if text.startswith(namespace):
            return f"{prefix}:{text[len(namespace):]}"
    return text


def _storage_locations() -> dict:
    with open(path_definitions.ONTOLOGY_LIBRARY_PATH, encoding="utf-8") as handle:
        library = json.load(handle)
    by_id = {entity.get("@id"): entity for entity in library.get("@graph", [])}
    return {prefix: by_id.get(f"ontology:{prefix}_File", {}).get("cpo:hasStorageLocation")
            for prefix in ("quantitykind", "unit")}


def _load_vocabulary(url: str, graph: Graph, notes: list) -> bool:
    cache = path_definitions.EXTERNAL_VOCABULARY_CACHE
    # File name from the versioned URL: https://qudt.org/3.5.2/vocab/unit -> qudt.org_3.5.2_vocab_unit.ttl
    name = url.split("://", 1)[-1].replace("/", "_") + ".ttl"
    path = cache / name
    if not path.exists():
        try:
            request = urllib.request.Request(url, headers={"Accept": "text/turtle"})
            with urllib.request.urlopen(request, timeout=120) as response:
                data = response.read()
        except OSError as error:
            notes.append(f"could not download {url} ({error}) and there is no cached copy - QUDT check skipped")
            return False
        cache.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        notes.append(f"downloaded {url} to {path.relative_to(path_definitions.BASE_FOLDER).as_posix()}")
    graph.parse(path, format="turtle")
    return True


class _Qudt:
    def __init__(self, graph: Graph):
        self.graph = graph

    def exists(self, uri) -> bool:
        return (uri, None, None) in self.graph

    def deprecated(self, uri) -> bool:
        return any(str(value).lower() == "true" for value in self.graph.objects(uri, QUDT.deprecated))

    def broader(self, kind) -> set:
        """The kind itself and every kind above it (skos:broader, transitively)."""
        found, todo = set(), [kind]
        while todo:
            current = todo.pop()
            if current in found:
                continue
            found.add(current)
            todo.extend(self.graph.objects(current, SKOS.broader))
        return found

    def listed_for(self, kind, unit) -> bool:
        # QUDT does not keep the assignment uniformly: sometimes at the quantity kind
        # (qudt:applicableUnit), sometimes at the unit (qudt:hasQuantityKind), and often only at a
        # broader kind (M3-PER-SEC hangs at VolumePerTime, not at VolumeFlowRate).
        for candidate in self.broader(kind):
            if (candidate, QUDT.applicableUnit, unit) in self.graph or (unit, QUDT.hasQuantityKind, candidate) in self.graph:
                return True
        return False

    def dimension(self, uri):
        return next(self.graph.objects(uri, QUDT.hasDimensionVector), None)


def check_units_against_qudt() -> tuple:
    """Returns (problems, notes): problems are findings to fix, notes say what was done."""
    problems, notes = [], []
    graph = Graph()
    locations = _storage_locations()
    for prefix, url in locations.items():
        if not url:
            return [f"ontology_library.jsonld names no storage location for ontology:{prefix}_File"], notes
        if not _load_vocabulary(url, graph, notes):
            return problems, notes
    notes.append(f"checked against {', '.join(locations.values())}")
    # The own quantity kinds (cpo:ReactionRate) and the annotations stand in the ontology.
    graph.parse(path_definitions.CPO_ONTOLOGY)
    qudt = _Qudt(graph)

    # 1) Quantity kinds: exist, not deprecated.
    kinds = set(units.SCALAR_UNITS_BY_QUANTITY_KIND) | units.DIMENSIONLESS_QUANTITY_KINDS
    kinds |= set(units.FRACTION_QUANTITY_KINDS) | set(units.ENERGY_FIELD_QUANTITY_KIND.values())
    kinds |= set(units.CHANGE_RATE_QUANTITY_KIND) | set(units.CHANGE_RATE_QUANTITY_KIND.values())
    kinds |= {_compact(kind) for kind in graph.objects(None, CPO.valueHasQuantityKind)}
    for kind in sorted(kinds):
        uri = _uri(kind)
        if not qudt.exists(uri):
            problems.append(f"quantity kind {kind} does not exist in QUDT (nor in the ontology)")
        elif qudt.deprecated(uri):
            problems.append(f"quantity kind {kind} is deprecated in QUDT")

    # 2) The unit fits the quantity kind.
    accepted = units.ACCEPTED_DIMENSION_MATCHES
    used_acceptances = set()

    def check_pair(kind, unit, where):
        kind_uri, unit_uri = _uri(kind), _uri(unit)
        if not qudt.exists(unit_uri):
            problems.append(f"{where}: unit {unit} does not exist in QUDT")
            return
        if qudt.deprecated(unit_uri):
            problems.append(f"{where}: unit {unit} is deprecated in QUDT")
        if not qudt.exists(kind_uri):
            return  # reported under 1) already
        is_accepted = unit in accepted.get(kind, {})
        if qudt.listed_for(kind_uri, unit_uri):
            if is_accepted:
                problems.append(f"{where}: {unit} for {kind} is listed in accepted_dimension_matches, "
                                "but QUDT lists it for the kind anyway - the exception is no longer needed")
            return
        same_dimension = qudt.dimension(kind_uri) is not None and qudt.dimension(kind_uri) == qudt.dimension(unit_uri)
        if same_dimension and is_accepted:
            used_acceptances.add((kind, unit))
        elif same_dimension:
            problems.append(f"{where}: QUDT does not list {unit} for {kind} (same dimension only) - "
                            "use a listed unit or accept it in accepted_dimension_matches, with the reason")
        else:
            problems.append(f"{where}: {unit} does not fit {kind} - different dimension "
                            f"({_compact(qudt.dimension(unit_uri))} vs {_compact(qudt.dimension(kind_uri))})")

    for kind, unit_list in units.SCALAR_UNITS_BY_QUANTITY_KIND.items():
        for unit in unit_list:
            check_pair(kind, unit, "units_by_quantity_kind")
    for kind in sorted(units.DIMENSIONLESS_QUANTITY_KINDS):
        check_pair(kind, UNITLESS, "dimensionless_quantity_kinds")
    for unit in units.DURATION_UNITS:
        check_pair("quantitykind:Time", unit, "duration_units")
    for field_type, unit in units.ENERGY_FIELD_STRENGTH_UNIT.items():
        kind = units.ENERGY_FIELD_QUANTITY_KIND.get(field_type)
        if kind is None:
            problems.append(f"fixed_field_strength_units: {field_type} has no entry in field_strength_quantity_kinds")
        else:
            check_pair(kind, unit, "fixed_field_strength_units")

    for kind, unit_reasons in accepted.items():
        for unit in unit_reasons:
            if (kind, unit) not in used_acceptances and unit not in units.SCALAR_UNITS_BY_QUANTITY_KIND.get(kind, []):
                problems.append(f"accepted_dimension_matches: {unit} for {kind} is accepted but not offered anywhere")

    # 3) Every quantity kind the ontology ascribes to a property needs a choice of units or is
    # dimensionless - otherwise a recorded value gets no unit (rule 4.3).
    for kind in sorted({_compact(k) for k in graph.objects(None, CPO.valueHasQuantityKind)}):
        if kind not in units.SCALAR_UNITS_BY_QUANTITY_KIND and kind not in units.DIMENSIONLESS_QUANTITY_KINDS:
            problems.append(f"{kind} is the quantity kind of a property (cpo:valueHasQuantityKind), but "
                            "units_by_quantity_kind offers no unit for it and it is not dimensionless")

    # The field strength per type of field must be one of the quantity kinds the ontology allows
    # for cpo:hasFieldStrength - otherwise the run stops when the field is created.
    field_kinds = {_compact(k) for k in graph.objects(CPO.hasFieldStrength, CPO.valueHasQuantityKind)}
    for field_type, kind in units.ENERGY_FIELD_QUANTITY_KIND.items():
        if kind not in field_kinds:
            problems.append(f"field_strength_quantity_kinds: {field_type} -> {kind}, but the ontology allows only "
                            f"{', '.join(sorted(field_kinds)) or 'nothing'} for cpo:hasFieldStrength")

    # 4) Conversion factors of the volume check.
    for unit, factor in units.VOLUME_UNIT_TO_M3.items():
        multipliers = [float(value) for value in graph.objects(_uri(unit), QUDT.conversionMultiplier)
                       if isinstance(value, Literal)]
        if not multipliers:
            problems.append(f"volume_unit_to_m3: QUDT has no conversionMultiplier for {unit}")
        elif not any(abs(multiplier - factor) <= 1e-12 * max(1.0, abs(multiplier)) for multiplier in multipliers):
            problems.append(f"volume_unit_to_m3: {unit} = {factor}, QUDT says {multipliers[0]}")

    return problems, notes
