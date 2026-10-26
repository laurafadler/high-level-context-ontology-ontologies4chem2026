"""
What the series says about all its experiments (rule
7c).

Five questions ask whether something is the same in every experiment - creator, experimenter,
the mode of operation, the sub-tasks of a grouping task, the solvent of a liquid mixture. (The kind of material is fixed at the
series: another kind of material is another set-up, and another series.) The answer decides WHERE the run asks: Yes asks once for the
series, No and "Not known yet" ask per experiment. An answer the file holds for the other place
is then never asked - and would be silently ignored. check_series_contradictions stops the run
on exactly that, before anything is saved.
"""

import re

from helpers.entities import as_list, find_entity, ref_id
from helpers.user_io import unused_answer_keys

# Ending of a key -> the question "the same for all?" that decides whether it is asked.
GOVERNED_BY = {
    "creator": "same_creator_for_all_experiments",
    "experimenter": "same_experimenter_for_all_experiments",
    "series_experimenter": "same_experimenter_for_all_experiments",
    "operation_mode": "same_operation_mode_across_experiments",
    "parts": "same_parts_in_all_experiments",
    "solvents": "same_solvent_across_experiments",
}

_EXPERIMENT_SEGMENT = re.compile(r"/experiment:\d+(?=/)")


# Series devices whose operation mode was answered with "Not known yet" - when the series is
# completed it is decided whether it belongs at the series (hoist_on_completion).
_modes_not_known_yet = []


def note_mode_not_known_yet(series_device: dict):
    """Remember a series device whose mode was answered 'Not known yet'."""
    _modes_not_known_yet.append(series_device["@id"])


# Series phases whose solvent was asked per experiment (No / Not known yet) - when the series
# is completed it names all used (hoist_on_completion, rule 7c.6).
_solvents_per_experiment = []


def note_solvents_per_experiment(series_phase: dict):
    """Remember a series phase whose solvent is asked per experiment."""
    _solvents_per_experiment.append(series_phase["@id"])


def hoist_on_completion(datagraph: dict) -> list:
    """In the run that completes the series: a mode of operation answered 'Not known yet' that
    turned out the same in every experiment is stated once, at the series device (rule 3.6 -
    the experiment devices read it through hlo:specializationOf); otherwise everything stays at
    the experiments. Returns what was hoisted.

    A solvent asked per experiment is stated at the series as every solvent any experiment
    named - what the series can contain (rule 7c.1), on its own species records (rule 3.1). Only
    now: before, another experiment could still add one (rule 7c.6).

    The people need nothing like this (every level states its own), nor do the sub-tasks (with
    the same parts in every experiment the series template already holds them all)."""
    series = [e for e in datagraph.get("@graph", []) if "cpo:ExperimentalSeries" in as_list(e.get("@type"))]
    if not series or series[0].get("cpo:isCompleted") is not True:
        return []
    hoisted = []
    for device_id in _modes_not_known_yet:
        device = find_entity(datagraph, device_id)
        experiments = [find_entity(datagraph, ref_id(ref)) for ref in as_list(device.get("hlo:hasSpecialization"))] if device else []
        modes = [ref_id(e.get("cpo:hasModeOfOperation")) for e in experiments if e is not None]
        if not modes or None in modes or len(set(modes)) != 1:
            continue
        device["cpo:hasModeOfOperation"] = {"@id": modes[0]}
        for experiment_device in experiments:
            experiment_device.pop("cpo:hasModeOfOperation", None)
        hoisted.append(f"{device_id}: mode {modes[0]} in every experiment - now stated at the series")
    for phase_id in _solvents_per_experiment:
        phase = find_entity(datagraph, phase_id)
        if phase is None:
            continue
        solvents = []
        for experiment_phase in (find_entity(datagraph, ref_id(ref)) for ref in as_list(phase.get("hlo:hasSpecialization"))):
            for solvent_id in (ref_id(ref) for ref in as_list((experiment_phase or {}).get("cpo:hasSolvent"))):
                # The exemplar of the series that this experiment exemplar specializes; an ion without
                # exemplars of its own stands on both levels with its library ID.
                record = find_entity(datagraph, solvent_id)
                series_id = ref_id(record.get("hlo:specializationOf")) if record and record.get("hlo:specializationOf") else solvent_id
                if series_id not in solvents:
                    solvents.append(series_id)
        if solvents:
            phase["cpo:hasSolvent"] = [{"@id": s} for s in solvents]
            hoisted.append(f"{phase_id}: solvents of all experiments - now stated at the series")
    for line in hoisted:
        print(f"[series] {line}")
    return hoisted


class SeriesContradictionError(RuntimeError):
    """The answer file answers a question the series-level answer made unnecessary."""


def governing_key(key: str) -> str:
    """The key of the "same in every experiment?" question that decides whether key is asked."""
    leaf = key.rsplit("/", 1)[-1]
    series_path = _EXPERIMENT_SEGMENT.sub("", key).rsplit("/", 1)[0]
    return f"{series_path}/{GOVERNED_BY[leaf]}"


def check_series_contradictions():
    """Stop when the answer file holds an answer the run did not ask because of a
    "same in every experiment?" answer."""
    problems = []
    for key in unused_answer_keys():
        leaf = key.rsplit("/", 1)[-1]
        if leaf not in GOVERNED_BY:
            continue
        where = "for one experiment" if _EXPERIMENT_SEGMENT.search(key) else "for the whole series"
        problems.append(f"{key} (answered {where}, but {governing_key(key)} decided otherwise)")
    if problems:
        raise SeriesContradictionError(
            f"The answer file contradicts itself ({len(problems)} answer(s) the run did not ask):\n  "
            + "\n  ".join(problems)
            + "\nEither remove these answers, or change the 'same in every experiment?' answer named with each - "
              "Yes asks once for the series, No and 'Not known yet' ask per experiment.")
