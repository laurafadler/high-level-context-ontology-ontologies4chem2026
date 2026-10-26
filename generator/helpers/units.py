"""
Units and quantity-kind choice lists, read once from generator/config/units_and_quantity_kinds.json
(path_definitions.UNITS_PATH).

Adding a unit is a data change (rule 4.5): an entry in the JSON file, checked against QUDT by
check_library_consistency.py. The modules that need a table import it from here.

Which quantity kinds a PROPERTY allows is not in this file but in the ontology
(cpo:valueHasQuantityKind, read by helpers/ontology_functions.py: quantity_kinds_of_property) -
including the choices for a concentration or a coverage. That is a statement of the model;
this file holds the units.
"""

import json

import path_definitions


def _load(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _without_comments(table: dict) -> dict:
    # Keys with "_" are comments (JSON knows none).
    return {key: value for key, value in table.items() if not key.startswith("_")}


_DATA = _load(path_definitions.UNITS_PATH)

SCALAR_UNITS_BY_QUANTITY_KIND = _without_comments(_DATA["units_by_quantity_kind"])
VOLUME_UNITS = SCALAR_UNITS_BY_QUANTITY_KIND["quantitykind:Volume"]
VOLUME_UNIT_TO_M3 = _without_comments(_DATA["volume_unit_to_m3"])
DURATION_UNITS = _DATA["duration_units"]["values"]
DIMENSIONLESS_QUANTITY_KINDS = set(_DATA["dimensionless_quantity_kinds"]["values"])
FRACTION_QUANTITY_KINDS = {
    kind: (entry["word"], tuple(entry["suffixes"]))
    for kind, entry in _without_comments(_DATA["fraction_quantity_kinds"]).items()
}
ENERGY_FIELD_QUANTITY_KIND = _without_comments(_DATA["field_strength_quantity_kinds"])
ENERGY_FIELD_STRENGTH_UNIT = _without_comments(_DATA["fixed_field_strength_units"])
CHANGE_RATE_QUANTITY_KIND = _without_comments(_DATA["change_rate_quantity_kinds"])
ACCEPTED_DIMENSION_MATCHES = {
    kind: _without_comments(units) for kind, units in _without_comments(_DATA["accepted_dimension_matches"]).items()
}

# The conversion has to know every volume unit offered, otherwise the volume check fails only
# in the middle of the run, at the newly entered unit.
if set(VOLUME_UNITS) != set(VOLUME_UNIT_TO_M3):
    raise ValueError(f"{path_definitions.UNITS_PATH.name}: the volume units {VOLUME_UNITS} and the "
                     f"conversion factors {sorted(VOLUME_UNIT_TO_M3)} must name the same units.")

# Likewise every quantity kind of a rate of change needs units to choose from, otherwise only
# the ramp step fails in the middle of the run.
_rate_kinds_without_units = sorted(set(CHANGE_RATE_QUANTITY_KIND.values()) - set(SCALAR_UNITS_BY_QUANTITY_KIND))
if _rate_kinds_without_units:
    raise ValueError(f"{path_definitions.UNITS_PATH.name}: the change rate kinds {_rate_kinds_without_units} "
                     "have no units in units_by_quantity_kind.")
