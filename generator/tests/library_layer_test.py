"""
Counter-check (rule 7.14) for the layer check in check_library_consistency.py (_layer_problems,
rule 3.8a). The real libraries hold no device with layers, so this builds two in memory - the
stirrer with a PTFE coating and vessel001 with a PTFE lining, both in the pattern of rule 3.8a -,
expects no finding for them, and then damages ONE thing per case and expects exactly the
expected problem kinds.

The two builders are also used to set up a layered device in an isolated copy for a crate test:
    python generator/tests/library_layer_test.py --apply COPY [--partial]
writes the coated stirrer and the lined vessel (with --partial: a lining with PartialCoverage)
into COPY/libraries/device_library.jsonld. Without --apply the script changes no files.

Run from the repository root:
    PYTHONPATH=. python generator/tests/library_layer_test.py
"""
import argparse
import copy
import sys
from pathlib import Path

# Runs from generator/tests/ - the generator has to be on the search path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from workflow.check_library_consistency import LIBRARY_FILES, _entities, _layer_problems
from helpers.file_handling import load_jsonld, save_jsonld


def _ref(entity_id):
    return {"@id": entity_id}


def _by_id(data: dict) -> dict:
    return {e["@id"]: e for e in _entities(data) if e.get("@id")}


def _add_layer(graph: list, by: dict, device_id: str, body_form_id: str, body_id: str, layer: str, name: str,
               chemical_entity: str, coverage: str) -> str:
    """One layer: the device's body form reaches the LayerForm, the new phase of the body material
    fills it; the core (the phase already there) and the new layer are separated by an interface."""
    form_id = f"{device_id}_Layer_{layer}"
    phase_id = f"{body_id}_{layer}Phase"
    core_id = next(r["@id"] for r in (by[body_id]["dcterms:hasPart"] if isinstance(by[body_id]["dcterms:hasPart"], list)
                                       else [by[body_id]["dcterms:hasPart"]]))
    interface_id = f"{body_id}_{layer}_Interface"
    graph += [
        {"@id": form_id, "@type": ["cpo:LayerForm", "hlo:Fixed", "hlo:Actual"],
         "cpo:hasWallThickness": _ref(f"{form_id}_WallThickness"), "cpo:hasLayerCoverage": _ref(coverage)},
        {"@id": f"{form_id}_WallThickness", "@type": ["cpo:ProcessVariable", "hlo:Fixed", "hlo:Actual"],
         "qudt:hasQuantityKind": _ref("quantitykind:Thickness")},
        {"@id": phase_id, "@type": ["cpo:SolidPhase", "hlo:Fixed"], "schema:name": name,
         "dcterms:isPartOf": _ref(body_id), "cpo:canCreateEnergyField": False,
         "cpo:hasDispersionState": _ref("cpo:Continuous"), "dcterms:hasPart": _ref(chemical_entity),
         "cpo:hasSolidStructure": _ref("cpo:Amorphous"), "cpo:fillsForm": _ref(form_id),
         "cpo:hasVolume": _ref(f"{phase_id}_Volume"), "cpo:isSeparatedByInterface": _ref(interface_id)},
        {"@id": f"{phase_id}_Volume", "@type": ["cpo:ProcessVariable", "hlo:Fixed", "hlo:Actual"],
         "qudt:hasQuantityKind": _ref("quantitykind:Volume"), "cpo:isProcessVariableOf": _ref(phase_id)},
        {"@id": interface_id, "@type": ["cpo:PhasePairInterface", "hlo:Fixed"], "schema:name": f"{name} / core Interface",
         "cpo:separatesPhases": [_ref(core_id), _ref(phase_id)]},
    ]
    body_form = by[body_form_id]
    body_form["cpo:hasLayerForm"] = [*([body_form["cpo:hasLayerForm"]] if isinstance(body_form.get("cpo:hasLayerForm"), dict)
                                       else body_form.get("cpo:hasLayerForm", [])), _ref(form_id)]
    body = by[body_id]
    parts = body["dcterms:hasPart"] if isinstance(body["dcterms:hasPart"], list) else [body["dcterms:hasPart"]]
    body["dcterms:hasPart"] = parts + [_ref(phase_id)]
    # Several phases: the material has its own volume (rule 3a.6), the core its own.
    core = by[core_id]
    if ref_of(body.get("cpo:hasVolume")) == ref_of(core.get("cpo:hasVolume")):
        body["cpo:hasVolume"] = _ref(f"{body_id}_Volume")
        graph.append({"@id": f"{body_id}_Volume", "@type": ["cpo:ProcessVariable", "hlo:Fixed", "hlo:Actual"],
                      "qudt:hasQuantityKind": _ref("quantitykind:Volume"), "cpo:isProcessVariableOf": _ref(body_id)})
    core["cpo:isSeparatedByInterface"] = _ref(interface_id)
    return phase_id


def ref_of(value):
    return value.get("@id") if isinstance(value, dict) else value


def add_coated_stirrer(device_library: dict):
    """stirrer001: steel core fills the shaft form, a PTFE coating (complete) fills its layer form."""
    graph = device_library["@graph"]
    by = _by_id(device_library)
    _add_layer(graph, by, "device:stirrer001", "device:stirrer001_Shaft", "material:stirrer001_Body", "PTFE",
               "stirrer001 Body, PTFE coating", "chem:ChemicalEntity_0004", "cpo:CompleteCoverage")


def add_lined_vessel(device_library: dict, partial: bool = False):
    """vessel001: the glass fills the cup form, a PTFE lining fills its layer form and faces the inside."""
    graph = device_library["@graph"]
    by = _by_id(device_library)
    lining = _add_layer(graph, by, "device:vessel001", "device:vessel001_Form", "material:vessel001_Body", "Lining",
                        "vessel001 Body, PTFE lining", "chem:ChemicalEntity_0004",
                        "cpo:PartialCoverage" if partial else "cpo:CompleteCoverage")
    by["material:vessel001_Body"]["cpo:hasInnerLayer"] = _ref(lining)


def _layered_libraries():
    libraries = {name: load_jsonld(path) for name, path in LIBRARY_FILES.items()}
    add_coated_stirrer(libraries["device_library.jsonld"])
    add_lined_vessel(libraries["device_library.jsonld"])
    return libraries


def _find(libraries, entity_id):
    for data in libraries.values():
        for entity in _entities(data):
            if entity.get("@id") == entity_id:
                return entity
    raise KeyError(entity_id)


LAYER = "device:stirrer001_Layer_PTFE"
COATING = "material:stirrer001_Body_PTFEPhase"
CORE = "material:stirrer001_Body_SolidPhase"


def _no_thickness(lib):
    del _find(lib, LAYER)["cpo:hasWallThickness"]


def _no_coverage(lib):
    del _find(lib, LAYER)["cpo:hasLayerCoverage"]


def _phase_defines_form(lib):
    coating = _find(lib, COATING)
    coating["cpo:definesForm"] = coating.pop("cpo:fillsForm")


def _layer_on_part(lib):
    del _find(lib, "device:stirrer001_Shaft")["cpo:hasLayerForm"]
    _find(lib, "device:stirrer001_Blade")["cpo:hasLayerForm"] = _ref(LAYER)


def _two_cores(lib):
    _find(lib, COATING)["cpo:fillsForm"] = _ref("device:stirrer001_Shaft")


def _layer_unreached(lib):
    del _find(lib, "device:stirrer001_Shaft")["cpo:hasLayerForm"]


def _inner_layer_elsewhere(lib):
    _find(lib, "material:vessel001_Body")["cpo:hasInnerLayer"] = _ref(CORE)


CASES = [
    ("layer form without thickness", _no_thickness, {"layer form without thickness": LAYER}),
    ("layer form without coverage", _no_coverage, {"layer form without coverage": LAYER}),
    ("coating defines its own form", _phase_defines_form,
     {"layer phase defines a form of its own": COATING, "phase fills no layer form of its device": COATING}),
    ("layer at a part of the form", _layer_on_part,
     {"cpo:hasLayerForm on a form no device defines": "device:stirrer001_Blade",
      "phase fills no layer form of its device": COATING}),
    ("both phases fill the body form", _two_cores,
     {"not exactly one phase fills the body form": "material:stirrer001_Body"}),
    ("layer form not reached", _layer_unreached,
     {"layer form not reached from a device's body form": LAYER, "phase fills no layer form of its device": COATING}),
    ("inner layer of another material", _inner_layer_elsewhere,
     {"cpo:hasInnerLayer is not a phase of the material": "material:vessel001_Body"}),
]


def run_tests() -> bool:
    base = _layered_libraries()
    found = {k: v for k, v in _layer_problems(base).items() if v}
    ok = not found
    print(f"{'ok  ' if ok else 'FAIL'} correct layers: {'no finding' if ok else found}")
    for label, damage, expected in CASES:
        libraries = copy.deepcopy(base)
        damage(libraries)
        problems = {k: v for k, v in _layer_problems(libraries).items() if v}
        reported = {kind: {row[1] for row in rows} for kind, rows in problems.items()}
        wanted_kinds = set(expected)
        good = set(reported) == wanted_kinds and all(entity is None or entity in reported[kind] for kind, entity in expected.items())
        ok = ok and good
        print(f"{'ok  ' if good else 'FAIL'} {label}: {reported}")
    return ok


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", help="an isolated copy whose device library gets the layered devices")
    parser.add_argument("--partial", action="store_true", help="with --apply: the lining covers only a part")
    args = parser.parse_args()
    if args.apply:
        # Main file and details of the copy as one library, split back.
        path = Path(args.apply) / "libraries" / "device_library.jsonld"
        data = load_jsonld(path)
        add_coated_stirrer(data)
        add_lined_vessel(data, partial=args.partial)
        save_jsonld(data, path)
        print(f"layered stirrer and {'partly ' if args.partial else ''}lined vessel written to {path}")
        return
    sys.exit(0 if run_tests() else 1)


if __name__ == "__main__":
    main()
