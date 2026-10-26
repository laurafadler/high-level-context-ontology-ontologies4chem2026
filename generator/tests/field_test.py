"""
Field test (rule 7b of docs/rules_crate.md): the energy-field code paths the hydrogenation crate
never runs through - fields of devices, of phases and of radioactive molecules, their occurrences,
and the surroundings paths that collect them - checked against fixed expectations.

Run from the repository root:
    python generator/tests/field_test.py [--out DIR]

What it does:
1. Copies the project (like generator/workflow/isolated_run.py; without --out into a new temp folder).
2. Prepares the libraries of the copy: stirrer001 and its body phase can create an energy field,
   water (chem:Molecule_0003) is radioactive - all three WITHOUT a library field.
3. Runs generator/workflow/answer_driver.py in the copy with the answers in RULES (abort mode, so no question
   is answered by a stand-in) and ALLOW_EARLIER_CHANGES=1 (the flag of the body phase is already
   recorded in the crate).
4. Starts itself with --check inside the copy, so every path points at the copy's crate and
   libraries, and checks:
   - the driver completed with no stand-in and no unused rule;
   - SHACL (without and with RDFS inference), counted as generator/workflow/run_shacl.py counts
     (crate and libraries apart): the crate check reports nothing - no Phase_Time_R2, hydrogen and
     cooling water come from the gas cylinder and the water supply (rule 7.17); the library check of
     the copy reports nothing at the prepared entries: Device_Energy_R5, Phase_Energy_R4 and
     Molecule_Energy_R1 exclude library entries (the stirrer carries the flag but no field, and so
     do the three library entries of water); the stirrer, its body phase and every water molecule in
     use have their field. Findings at other library
     entries are not this test's business (they stand in the library baseline);
   - the fields: the stirrer has a magnetic and an electric field, its body phase a magnetic field,
     every water molecule an ionizing radiation field - on every level, and nothing else; each
     experiment field specializes the field of the series counterpart of its source; each field
     is linked to exactly the energy context of its source on its level, and what hangs off it
     (field strength, occurrences, their times) is not linked (rule 6.4);
   - the stirrer magnet field occurred twice in experiment 1;
   - the surroundings paths (Device_Energy_R6, Phase_Energy_R5, Molecule_Energy_R2): in each
     experiment every device, phase and molecule sees the stirrer magnet field of that experiment -
     also those of the streams that no device contains, which climb over their ends
     (rule 7.10) - and no path reaches a field of the other experiment.
Exit code 0 when every expectation holds, 1 otherwise. The copy is left in place for a look.

When the answer keys change (a renamed question, a new one), the run stops and names the key -
then RULES below has to follow.
"""
import argparse
import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
# The series the test runs on, named rather than "the only open crate": several crates are open.
SERIES = "hydrogenation_rdy_2026_09"
GENERATOR = PROJECT / "generator"
ISOLATED_MARKER = ".isolated_copy"

# Library file, entity, flag - deliberately without a library field, so that the Fixed entries get
# one warning each and the fields in the crate come into being without a template.
PREPARED = [
    ("device_library.jsonld", "device:stirrer001", "cpo:canCreateEnergyField"),
    ("device_library.jsonld", "material:stirrer001_Body_SolidPhase", "cpo:canCreateEnergyField"),
    ("chemical_entity_library.jsonld", "chem:Molecule_0003", "cpo:isRadioactive"),
]

_TASK = "series:1/experiment:1/task:for-EnergyField_stirrer001_MagneticField_Occurrence_2_Status_Reference_1_ExperimentSpecific/"
_OCCURRENCE = "series:1/experiment:1/occurrences/energy_field:EnergyField_stirrer001_MagneticField/"
RULES = [
    # Which fields: two for the stirrer, one for its body phase; the water fields come into being without a question
    {"key": "series:1/device:stirrer001/energy_field_types", "answer": "MagneticField;ElectricField"},
    {"key": "series:1/body_material:stirrer001_Body/phase:stirrer001_Body_SolidPhase/energy_field_types", "answer": "MagneticField"},
    {"key": "series:1/*energy_field:*/quantities_with_evidence", "answer": ""},
    {"key": "series:1/*energy_field:*/quantities_with_reference", "answer": ""},
    {"key": "series:1/*energy_field:*/quantities_known_per_experiment", "answer": ""},
    # Occurrences: the magnetic field of the stirrer twice in experiment 1 (assumed), nothing else known
    {"key": "series:1/experiment:1/occurrences/energy_fields", "answer": "EnergyField_stirrer001_MagneticField"},
    {"key": "series:1/experiment:2/occurrences/energy_fields", "answer": ""},
    {"key": _OCCURRENCE + "number_of_occurrences", "answer": "2"},
    {"key": _OCCURRENCE + "occurrence:*/status_source", "answer": "reference"},
    {"key": _OCCURRENCE + "occurrence:*/status/reference_exists", "answer": "No"},
    {"key": _OCCURRENCE + "occurrence:*/status/reference_value_type", "answer": "cpo:OccurrenceStatus"},
    {"key": _OCCURRENCE + "occurrence:*/status/reference_type", "answer": "hlo:Assumed"},
    {"key": _OCCURRENCE + "occurrence:*/status/reference:2/have_another_reference", "answer": "No"},
    # The assumption is a task of its own, the second occurrence refers to the same one
    {"key": _TASK + "covered_by_existing", "answer": "No - this is a task of its own"},
    {"key": _TASK + "name", "answer": "Assuming when the stirrer magnet was on"},
    {"key": _TASK + "description", "answer": "Field test only: the stirrer magnet is assumed to have been switched on twice, no times recorded."},
    {"key": _TASK + "equipment", "answer": ""},
    {"key": _TASK + "software", "answer": ""},
    {"key": _TASK + "performed_by_scope", "answer": "Yes"},
    {"key": _TASK + "performers", "answer": "LauraFadler"},
    {"key": _TASK + "input_values", "answer": ""},
    {"key": _TASK + "aims_at", "answer": ""},
    {"key": _TASK + "generated_media_objects", "answer": ""},
    {"key": _TASK + "quantities_with_evidence", "answer": ""},
    {"key": _TASK + "quantities_with_reference", "answer": ""},
    {"key": "series:1/experiment:1/task:for-EnergyField_stirrer001_MagneticField_Occurrence_Reference_1_ExperimentSpecific/covered_by_existing",
     "answer": "Assuming when the stirrer magnet was on"},
]

# The expected warnings of the library check: requirement -> end of the IRI of the focus node (library
# entry). None - Molecule_Energy_R1, Phase_Energy_R4 and Device_Energy_R5 exclude library entries.
EXPECTED_WARNINGS = set()
# The prepared library entries whose findings the library check looks at.
PREPARED_ENDS = {"/device/stirrer001"}
# Phase_Time_R2 reports nothing: hydrogen comes from the gas cylinder, the cooling water from the line of
# the lab (rule 7.17).


# ---------------------------------------------------------------------------
# Phase 1: copy, library, run
# ---------------------------------------------------------------------------

def _set_flag(path: Path, entity_id: str, prop: str):
    """Set a flag in a library file of the copy, keeping its line endings and final newline. The
    entry may stand in the main file or in its details (helpers/library_files.py)."""
    from helpers.library_files import details_path
    for candidate in (path, details_path(path)):
        if candidate.exists() and f'"{entity_id}"' in candidate.read_text(encoding="utf-8"):
            path = candidate
            break
    raw = path.read_bytes()
    data = json.loads(raw.decode("utf-8"))
    hits = [e for e in data["@graph"] if e.get("@id") == entity_id]
    if len(hits) != 1:
        sys.exit(f"{entity_id} found {len(hits)} times in {path.name} - the field test needs it exactly once.")
    hits[0][prop] = True
    text = json.dumps(data, indent=2, ensure_ascii=False)
    if raw.rstrip(b"\r\n") != raw:
        text += "\n"
    if b"\r\n" in raw:
        text = text.replace("\n", "\r\n")
    path.write_bytes(text.encode("utf-8"))


def run(out: str = None) -> int:
    sys.path.insert(0, str(GENERATOR))
    import path_definitions
    # The same copy as isolated_run: projects/*/input/ with time stamps (the crate records the
    # date of creation of the files).
    from workflow.isolated_run import _ignored, _copy_inputs
    answers = Path("projects") / SERIES / "answers.txt"

    if out:
        copy = Path(out).resolve()
        if copy.exists():
            sys.exit(f"{copy} exists already - pick a new folder.")
        if PROJECT in copy.parents:
            sys.exit(f"{copy} lies inside the project - the next copy would copy it along.")
    else:
        copy = Path(tempfile.mkdtemp(prefix="field_test_")) / "repo"
    shutil.copytree(PROJECT, copy, ignore=_ignored)
    _copy_inputs(copy)
    (copy / ISOLATED_MARKER).write_text(f"copy of {PROJECT}\n", encoding="utf-8")
    for file_name, entity_id, prop in PREPARED:
        _set_flag(copy / "libraries" / file_name, entity_id, prop)
    (copy / "field_test_rules.json").write_text(json.dumps(RULES, indent=1), encoding="utf-8")

    env = dict(os.environ, ANSWER_FILE=str(copy / answers), PYTHONPATH=str(copy / "generator"), PYTHONIOENCODING="utf-8",
               ALLOW_EARLIER_CHANGES="1")
    env.pop("STRICT_ANSWERS", None)
    print(f"Running in {copy} ...", flush=True)
    with open(copy / "run.log", "w", encoding="utf-8") as log:
        subprocess.run([sys.executable, "generator/workflow/answer_driver.py", "--rules", "field_test_rules.json",
                        "--report", "driver_report.json"], cwd=copy, env=env, stdout=log, stderr=subprocess.STDOUT)
    result = subprocess.run([sys.executable, "generator/tests/field_test.py", "--check"], cwd=copy, env=env)
    print(f"\ncopy: {copy}\nlog:  {copy / 'run.log'}")
    return result.returncode


# ---------------------------------------------------------------------------
# Phase 2: checks, in the copy
# ---------------------------------------------------------------------------

def _as_list(value):
    return value if isinstance(value, list) else ([] if value is None else [value])


def _ids(value):
    return [v["@id"] if isinstance(v, dict) else v for v in _as_list(value)]


def _tail(iri) -> str:
    return str(iri).rsplit("/", 1)[-1]


class _Report:
    def __init__(self):
        self.failed = 0

    def check(self, good: bool, label: str, detail=""):
        print(f"{'ok  ' if good else 'FAIL'} {label}" + (f": {detail}" if detail and not good else ""))
        self.failed += not good


def _experiment(entity_id: str):
    """1, 2, ... for an experiment entity, None for a series entity."""
    match = re.search(r"_ExperimentSpecific_(\d+)$", entity_id)
    return int(match.group(1)) if match else None


def check() -> int:
    import pyshacl
    from rdflib import Graph, Namespace, RDF
    sys.path.insert(0, str(Path.cwd() / "generator"))
    import path_definitions
    from helpers import context_links
    from workflow import run_shacl

    if not (Path.cwd() / ISOLATED_MARKER).exists():
        print("(not an isolated copy - checking the project's own crate, which has no prepared fields)")
    report = _Report()
    SH = Namespace("http://www.w3.org/ns/shacl#")

    # Driver ----------------------------------------------------------------
    driver_path = Path("driver_report.json")
    driver = json.loads(driver_path.read_text(encoding="utf-8")) if driver_path.exists() else {}
    report.check(driver.get("status") == "completed", "driver completed", driver.get("status", "no driver report"))
    report.check(driver.get("stand_ins") == [], "no stand-in answers", driver.get("stand_ins"))
    report.check(driver.get("unused_rules") == [], "every rule used", driver.get("unused_rules"))

    crate_path = path_definitions.crate_path(SERIES)
    crate = json.loads(crate_path.read_text(encoding="utf-8"))
    entities = {e["@id"]: e for e in crate["@graph"] if "@id" in e}

    # SHACL -------------------------------------------------------------------
    # Counted as in run_shacl.py: the crate check only at nodes of the crate file,
    # the library check only at nodes of the library files of the copy.
    crate_nodes, library_nodes = set(), set()
    with contextlib.redirect_stdout(io.StringIO()):
        data = run_shacl.build_data_graph(crate_path, [], crate_nodes)
        library_data = run_shacl.build_library_graph([], library_nodes)
    shapes = Graph()
    for path in (path_definitions.CONTEXT_SHAPES, path_definitions.DATA_QUALITY_SHAPES, path_definitions.QUANTITY_KIND_SHAPES,
                 path_definitions.FUNCTION_SHAPES):
        shapes.parse(str(path), format="turtle")
    shape_to_requirement = run_shacl.build_shape_to_requirement(shapes)
    prepared_ends = PREPARED_ENDS | {end for _, end in EXPECTED_WARNINGS}

    def findings(graph, nodes, inference) -> set:
        """(requirement, focus) of the outer results at the given nodes; a focus with an expected
        warning is shortened to the end of its IRI as in EXPECTED_WARNINGS."""
        _, results, _ = pyshacl.validate(graph, shacl_graph=shapes, inference=inference, advanced=True, js=False)
        details = set(results.objects(None, SH.detail))
        found = set()
        for result in results.subjects(RDF.type, SH.ValidationResult):
            focus = results.value(result, SH.focusNode)
            if result in details or focus not in nodes:
                continue
            requirement = shape_to_requirement.get(results.value(result, SH.sourceShape), "(unassigned)")
            focus = str(focus)
            found.add((requirement, next((end for r, end in EXPECTED_WARNINGS if r == requirement and focus.endswith(end)), focus)))
        return found

    for inference in ("none", "rdfs"):
        in_crate = findings(data, crate_nodes, inference)
        report.check(not in_crate, f"SHACL crate check ({inference} inference): nothing", f"unexpected {sorted(in_crate)}")
        # Only the prepared entries - what other library entries report stands in the library baseline.
        at_prepared = {(requirement, focus) for requirement, focus in findings(library_data, library_nodes, inference)
                       if any(focus.endswith(end) for end in prepared_ends)}
        report.check(at_prepared == EXPECTED_WARNINGS,
                     f"SHACL library check ({inference} inference): exactly the expected warnings at the prepared entries",
                     f"missing {sorted(EXPECTED_WARNINGS - at_prepared)}, unexpected {sorted(at_prepared - EXPECTED_WARNINGS)}")

    # Fields ------------------------------------------------------------------
    fields = {i: e for i, e in entities.items() if "cpo:hasEnergyFieldType" in e and i.startswith("crate:")}
    source_of = defaultdict(list)
    for entity in entities.values():
        for field_id in _ids(entity.get("cpo:hasEnergyField")):
            if field_id in fields:
                source_of[field_id].append(entity["@id"])

    def kind_of(source: dict) -> str:
        types = " ".join(_as_list(source.get("@type")))
        return "Molecule" if "chebi:Molecule" in types else "Phase" if "Phase" in types else "Device"

    def expected_types(source_id: str) -> set:
        """The field types an exemplar should have - by its name AND its kind, so that an occurrence
        or a time named after the exemplar (stirrer001_Body_SolidPhase_Occurrence_...) is not one."""
        tail, source = _tail(source_id), entities.get(source_id, {})
        level = r"_(SeriesSpecific|ExperimentSpecific_\d+)$"
        if re.match(r"stirrer001" + level, tail) and kind_of(source) == "Device":
            return {"cpo:MagneticField", "cpo:ElectricField"}
        if re.match(r"stirrer001_Body_SolidPhase" + level, tail) and kind_of(source) == "Phase":
            return {"cpo:MagneticField"}
        if re.match(r"Molecule_0003_.*" + level, tail) and kind_of(source) == "Molecule":
            return {"cpo:IonizingRadiation"}
        return set()

    # Every expected source has exactly its fields, and no other source has one
    sources = {i for i in entities if i.startswith("crate:") and expected_types(i)}
    by_source = defaultdict(set)
    for field_id, field in fields.items():
        for source_id in source_of.get(field_id, []):
            by_source[source_id] |= set(_ids(field.get("cpo:hasEnergyFieldType")))
    wrong = {s: sorted(by_source.get(s, set())) for s in sources | set(by_source) if by_source.get(s, set()) != expected_types(s)}
    levels = {(kind_of(entities[s]), "experiment" if _experiment(s) else "series") for s in sources}
    report.check(not wrong and len(levels) == 6,
                 f"fields: stirrer (magnetic, electric), its body phase (magnetic), every water molecule (radiation), "
                 f"on every level ({len(fields)} fields at {len(sources)} sources)", f"wrong: {wrong}, levels {sorted(levels)}")

    no_source = [f for f in fields if len(source_of.get(f, [])) != 1]
    report.check(not no_source, "every field has exactly one source", no_source[:5])

    # Chain: the experiment field specializes the field of the series source
    bad_chain = []
    for field_id, field in fields.items():
        sources_here = source_of.get(field_id, [])
        if not sources_here or _experiment(field_id) is None:
            continue
        series_source = next(iter(_ids(entities[sources_here[0]].get("hlo:specializationOf"))), None)
        parent = next(iter(_ids(field.get("hlo:specializationOf"))), None)
        if parent not in fields or source_of.get(parent) != [series_source] or \
                _ids(fields[parent].get("cpo:hasEnergyFieldType")) != _ids(field.get("cpo:hasEnergyFieldType")):
            bad_chain.append(field_id)
    report.check(not bad_chain, "every experiment field specializes the same-type field of the series counterpart of its source", bad_chain[:5])

    # Context: exactly the energy context of the source on its level, nothing of what hangs at the field
    bad_context = []
    for field_id, field in fields.items():
        if not source_of.get(field_id):
            continue
        prefix = field_id.rsplit("/", 1)[0] + "/"
        n = _experiment(field_id)
        kind = kind_of(entities[source_of[field_id][0]])
        expected = [f"{prefix}ExperimentSpecific{kind}Energy_Exp{n}" if n else f"{prefix}SeriesSpecific{kind}Energy_Series"]
        if _ids(field.get("hlo:describesContext")) != expected:
            bad_context.append((field_id, _ids(field.get("hlo:describesContext"))))
    report.check(not bad_context, "every field linked to exactly the energy context of its source on its level", bad_context[:3])

    # Only the direction away from the field - cpo:isEnergyFieldOf points back at the source, which has its
    # own context.
    hanging, frontier = set(), set(fields)
    for props in (("cpo:hasFieldStrength", "cpo:hasOccurrence"),
                  ("cpo:hasOccurrenceStatus", "cpo:hasStartTime", "cpo:hasEndTime", "cpo:hasDuration")):
        frontier = {ref for entity_id in frontier for prop in props
                    for ref in _ids(entities[entity_id].get(prop)) if ref in entities}
        hanging |= frontier
    linked = sorted(i for i in hanging if entities[i].get("hlo:describesContext"))
    report.check(bool(hanging) and not linked, f"nothing that hangs off a field is linked ({len(hanging)} entities: strength, occurrences, status, times)", linked[:5])

    magnet_1 = next((f for f in fields if _tail(f) == "EnergyField_stirrer001_MagneticField_ExperimentSpecific_1"), None)
    occurrences = _ids(fields[magnet_1].get("cpo:hasOccurrence")) if magnet_1 else []
    report.check(len(occurrences) == 2, "the stirrer magnet field occurred twice in experiment 1", occurrences)

    # Surroundings ------------------------------------------------------------
    # A stream that no device contains climbs over its ends (rule 7.10): nobody is blind.
    shapes_only = Graph()
    shapes_only.parse(str(path_definitions.CONTEXT_SHAPES), format="turtle")
    walker = context_links._Walker(shapes_only, data)
    HLO = context_links.HLO
    for name in ("Device_Energy_R6", "Phase_Energy_R5", "Molecule_Energy_R2"):
        shape = HLO[f"{name}_ContextPathShape"]
        for n, other in ((1, 2), (2, 1)):
            seen = defaultdict(set)
            for focus in walker.shape(shape).focus_nodes(data):
                if _experiment(_tail(focus)) != n:
                    continue
                seen[_tail(focus)]
                for property_shape in shapes_only.objects(shape, SH.property):
                    seen[_tail(focus)] |= {_tail(v) for v in walker.shape(property_shape).value_nodes(data, [focus]).get(focus, ())}
            magnet = f"EnergyField_stirrer001_MagneticField_ExperimentSpecific_{n}"
            blind = {f for f, values in seen.items() if magnet not in values}
            report.check(bool(seen) and not blind,
                         f"{name}, experiment {n}: all {len(seen)} focus nodes see the stirrer magnet field",
                         f"blind {sorted(blind)[:5]}")
            crossing = sorted(f for f, values in seen.items() if any(v.endswith(f"_ExperimentSpecific_{other}") for v in values))
            report.check(not crossing, f"{name}, experiment {n}: no path reaches a field of experiment {other}", crossing[:5])

    print(f"\n{'ALL OK' if not report.failed else f'{report.failed} FAILED'}")
    return 1 if report.failed else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", help="folder for the copy (must not exist yet); default: a new temp folder")
    parser.add_argument("--check", action="store_true", help="only the checks, on the crate of the current folder (used inside the copy)")
    args = parser.parse_args()
    sys.exit(check() if args.check else run(args.out))


if __name__ == "__main__":
    main()
