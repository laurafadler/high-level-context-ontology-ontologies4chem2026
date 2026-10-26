"""
Point 8 (volume upper bound): warns when the hasVolume values of all MaterialVolumes
that a device holds through cpo:containsMaterial/materialContainedIn add up to more than its
cpo:hasInnerVolume. The inner volume is read straight from the (device) library
(through hlo:specializationOf* and cpo:definesForm) and is NOT copied into the datagraph.
Read and warn only - this blocks nothing and changes neither the datagraph nor the
library.

Deliberately kept independent of helpers/evidence_reference.py (see
check_material_volume_against_device): the number itself is created there
(create_scalar_variable), but the device_library needed here is not passed through the
whole evidence/reference machinery (dozens of call sites for all kinds of process
variables). Instead the check runs right after the hasVolume variable is created in
creation/material_functions.py, where device_library is needed and available anyway.
"""

from helpers.entities import find_entity, ref_id, as_list
from helpers.user_io import ask_user


# Volume units and their conversion into m3 stand in generator/config/units_and_quantity_kinds.json
# (helpers/units.py); check_library_consistency.py checks the factors against QUDT.
from helpers.units import VOLUME_UNIT_TO_M3


def _literal(value):
    return value.get("@value") if isinstance(value, dict) else value


def resolve_fixed_twin(entity_id: str, datagraph: dict, *library_graphs):
    """Follow hlo:specializationOf as far as needed (experiment -> series -> fixed)
    until an hlo:Fixed entity is reached.

    Series entities live in the datagraph, their fixed twin usually in a library
    (device_library, for example), so both are searched. Returns None when no Fixed
    entity can be reached.
    """
    graphs = (datagraph,) + library_graphs
    current_id = entity_id
    visited = set()

    while current_id and current_id not in visited:
        visited.add(current_id)
        current = None
        for graph in graphs:
            current = find_entity(graph, current_id)
            if current is not None:
                break
        if current is None:
            return None

        types = as_list(current.get("@type"))
        if "hlo:Fixed" in types:
            return current

        current_id = ref_id(current.get("hlo:specializationOf"))

    return None


def get_device_inner_volume(device_id: str, datagraph: dict, device_library: dict):
    """Read cpo:hasInnerVolume from a device's fixed library twin.

    Goes through cpo:definesForm -> cpo:hasInnerVolume -> hlo:hasReference (see vessel001
    in device_library.jsonld). Returns (value, unit), or None when it is not recorded.
    """
    twin = resolve_fixed_twin(device_id, datagraph, device_library)
    if twin is None:
        return None

    form = find_entity(device_library, ref_id(twin.get("cpo:definesForm")))
    if form is None:
        return None

    volume_actual = find_entity(device_library, ref_id(form.get("cpo:hasInnerVolume")))
    if volume_actual is None:
        return None

    reference = find_entity(device_library, ref_id(volume_actual.get("hlo:hasReference")))
    if reference is None:
        return None

    value = _literal(reference.get("qudt:value"))
    # Only qudt:hasUnit (rule 4.3): qudt:unit is in no library and no crate, and QUDT v3.5.2 does not
    # define it.
    unit = ref_id(reference.get("qudt:hasUnit"))
    if value is None:
        return None
    try:
        return float(value), unit
    except (TypeError, ValueError):
        return None


def _known_volume_in_m3(material: dict, datagraph: dict):
    """Read the hasVolume value already recorded for a MaterialVolume (evidence
    preferred, otherwise reference).

    Where the entry is a bound rather than an exact value (point 9), the upper bound is
    taken, which is the conservative choice ("for a series, take the maximum"). Returns
    None when there is no value yet, or no unit that is known here.
    """
    pv = find_entity(datagraph, ref_id(material.get("cpo:hasVolume")))
    if pv is None:
        return None

    for prop in ("hlo:hasEvidence", "hlo:hasReference"):
        value_entity = find_entity(datagraph, ref_id(pv.get(prop)))
        if value_entity is None:
            continue

        raw_value = value_entity.get("qudt:value")
        if raw_value is None:
            raw_value = value_entity.get("hlo:hasUpperBound")
        if raw_value is None:
            continue

        unit = ref_id(value_entity.get("qudt:hasUnit"))
        factor = VOLUME_UNIT_TO_M3.get(unit)
        if factor is None:
            continue

        try:
            return float(_literal(raw_value)) * factor
        except (TypeError, ValueError):
            continue

    return None


def check_material_volume_against_device(material: dict, datagraph: dict, device_library: dict):
    """Check whether the hasVolume values of all MaterialVolumes held by the same device
    (including `material` itself) add up to more than its cpo:hasInnerVolume.

    Only meaningful AFTER material["cpo:hasVolume"] already carries an evidence or
    reference with a value and a unit (see creation/material_functions.py, called right
    after add_phase_process_variable(material, "cpo:hasVolume", ...)). Warns only, blocks
    nothing, and does nothing at all when `material` is not held by a device or that
    device's inner volume is not recorded in the library.

    Works for phases too - pass the phase instead of `material`, as long as it also
    carries cpo:materialContainedIn and cpo:hasVolume.
    """
    device_id = ref_id(material.get("cpo:materialContainedIn"))
    if not device_id:
        return

    inner = get_device_inner_volume(device_id, datagraph, device_library)
    if inner is None:
        return
    inner_value, inner_unit = inner
    inner_factor = VOLUME_UNIT_TO_M3.get(inner_unit)
    if inner_factor is None:
        return
    inner_m3 = inner_value * inner_factor

    total_m3 = 0.0
    for candidate in datagraph.get("@graph", []):
        if "cpo:MaterialVolume" not in (candidate.get("@type") or []):
            continue
        if ref_id(candidate.get("cpo:materialContainedIn")) != device_id:
            continue
        known = _known_volume_in_m3(candidate, datagraph)
        if known is not None:
            total_m3 += known

    if total_m3 > inner_m3:
        ask_user(
            f"The entered volume(s) ({total_m3:.6g} m3 total) exceed the inner volume of "
            f"{device_id} ({inner_m3:.6g} m3). Keep this value anyway?",
            ["Yes", "No"],
            question_id="keep_volume_despite_device_limit"
        )
