"""
Continuing a series: new crate or continuation, protection of earlier experiments, archive
(rules 7a and 7c).

A run always builds the whole crate from the answer file, the libraries and the data folders
(variant B). Continuing a series means the answer file has grown by an experiment. What already
stood in the crate must then come out unchanged - an earlier experiment may only gain links to
what is new (a series entity gets hlo:hasSpecialization to its specialization in the new
experiment, the series and the root get the new experiment and its files as parts).

- start_crate(identifier): decides, from the folders, whether this is a new series or the
  continuation of an open one, and keeps the previous crate for the comparison. An archived
  (completed) series cannot be continued. A new series whose identifier the device library
  already knows from its usage commits, without a crate, stops the run: the series existed and
  its crate was deleted or moved. (A mistyped identifier is NOT caught this way - the library
  does not know it, and the run starts a new series.)
- check_earlier_content_kept(datagraph): before saving, compares with the previous crate.
  Deliberately changing earlier content (a corrected answer or library entry, a code change)
  needs ALLOW_EARLIER_CHANGES=1 in the environment; the run then lists every change it allowed,
  with the old and the new value.
- archive_if_completed(datagraph): a completed series moves to output/archive/<identifier>/.
"""

import os
import shutil

import path_definitions
from helpers.entities import as_list, find_entity
from helpers.file_handling import load_jsonld

ALLOW_EARLIER_CHANGES_VARIABLE = "ALLOW_EARLIER_CHANGES"

# What every run writes anew without an experiment changing: the list of libraries (new
# commits), the ontology snapshot (versions), the dates of the root, and at the series its
# state as a project (planned number, completed).
_ROOT_PROPERTIES = {"dateCreated", "dateModified", "datePublished"}
_SERIES_PROPERTIES = {"cpo:hasNumberOfPlannedExperiments", "cpo:isCompleted"}

_previous = {"crate": None, "identifier": None}


class SeriesCompletedError(RuntimeError):
    """The series is archived (completed) and cannot be continued."""


class UnknownContinuationError(RuntimeError):
    """The device library knows this identifier, but there is no crate for it."""


class EarlierContentChangedError(RuntimeError):
    """Continuing the series would change what an earlier run already recorded."""


def _identifier_used_in_device_library(identifier: str) -> bool:
    """Whether the device library records usage under this identifier now. Its current content
    counts, not its git history: usage taken out again - the crate deleted on purpose and its
    entries reverted, to build it anew - does not block the identifier."""
    prefix = f"crate:{identifier}/"
    # Devices and containers of the chemical inventory (rule 2.15): both files hold usage histories.
    for entity in (e for path in path_definitions.DEVICE_LIBRARY_PATHS for e in load_jsonld(path).get("@graph", [])):
        for prop in ("cpo:hasUsageHistory", "cpo:lastUsedTime", "cpo:lastUsedPurpose", "cpo:hasEndTime"):
            if any(str(ref).startswith(prefix) for ref in _ids(entity.get(prop))):
                return True
    return False


def start_crate(identifier: str) -> str:
    """"new" or "continued"; raises when the series cannot be written under this identifier."""
    _previous.update(crate=None, identifier=identifier)
    if path_definitions.archived_crate_folder(identifier).exists():
        raise SeriesCompletedError(
            f"The series {identifier} is completed and archived ({path_definitions.archived_crate_folder(identifier)}); "
            "it cannot be continued.")
    path = path_definitions.crate_path(identifier)
    if path.exists():
        _previous["crate"] = load_jsonld(path)
        print(f"[crate] Continuing the open series {identifier} ({path}).")
        return "continued"
    if _identifier_used_in_device_library(identifier):
        raise UnknownContinuationError(
            f"There is no crate for {identifier}, but the device library already records usage under this "
            "identifier. Is the short name mistyped (setup/series_short_name)? Or was the crate deleted? "
            "A new series needs a new identifier.")
    open_series = [p.parent.name for p in path_definitions.open_crate_paths()]
    print(f"[crate] New series {identifier}." + (f" Open series: {', '.join(open_series)}." if open_series else ""))
    return "new"


def _ids(value) -> list:
    return [v.get("@id") if isinstance(v, dict) else v for v in as_list(value)]


def _is_reference_list(value) -> bool:
    return all(isinstance(v, dict) and set(v) == {"@id"} for v in as_list(value))


def _short(value) -> str:
    import json
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= 80 else text[:77] + "..."


def _allowed_everywhere(entity_id: str) -> bool:
    return entity_id.startswith("ontology:") or entity_id.endswith("/LibrarySnapshot") or "/Library_" in entity_id


def check_earlier_content_kept(datagraph: dict):
    """Compare with the previous crate of this series; stop on any change to what it held,
    except links to new entities and what every run writes anew."""
    previous = _previous["crate"]
    if previous is None:
        return
    old = {e["@id"]: e for e in previous.get("@graph", [])}
    new = {e["@id"]: e for e in datagraph.get("@graph", [])}
    problems = []
    for entity_id, before in old.items():
        after = new.get(entity_id)
        if after is None:
            problems.append(f"{entity_id} is gone")
            continue
        if before == after or _allowed_everywhere(entity_id):
            continue
        for prop in sorted(set(before) | set(after)):
            was, now = before.get(prop), after.get(prop)
            if was == now:
                continue
            if entity_id == "./" and prop in _ROOT_PROPERTIES:
                continue
            if prop in _SERIES_PROPERTIES and "cpo:ExperimentalSeries" in as_list(after.get("@type")):
                continue
            # A property that did not exist before counts like an empty list of references (rule 7a.3): so,
            # for instance, the end of experiment 1 may get the context of experiment 2, at whose devices'
            # lastUsedTime it points (rule 6.6), without earlier content changing.
            if (was is None or _is_reference_list(was)) and now is not None and _is_reference_list(now):
                kept, added = set(_ids(was)), set(_ids(now)) - set(_ids(was))
                if kept <= set(_ids(now)) and not (added & old.keys()):
                    continue   # only references to something new added
            problems.append(f"{entity_id}: {prop} {_short(was)} -> {_short(now)}")
    if not problems:
        return
    # The run that completes the series may change earlier experiments (statements move to the
    # series, helpers/series_statements.py) - it only reports (8).
    completing = _completes_series(previous, datagraph)
    if completing or os.environ.get(ALLOW_EARLIER_CHANGES_VARIABLE, "").strip() not in ("", "0"):
        # All one by one: whoever allows a change on purpose should see what it overwrites.
        reason = "the series is completed in this run" if completing else f"allowed by {ALLOW_EARLIER_CHANGES_VARIABLE}"
        print(f"[crate] {len(problems)} change(s) to earlier content, {reason}:")
        for problem in problems:
            print(f"  {problem}")
        return
    shown = "\n  ".join(problems[:20]) + (f"\n  ... and {len(problems) - 20} more" if len(problems) > 20 else "")
    raise EarlierContentChangedError(
        f"Continuing the series would change what the crate already records ({len(problems)} change(s)):\n  {shown}\n"
        f"If that is intended (a corrected library entry or answer, a change of the generator), run again with "
        f"{ALLOW_EARLIER_CHANGES_VARIABLE}=1.")


def _completes_series(previous: dict, datagraph: dict) -> bool:
    """Whether this run completes the series: open in the previous crate, completed now."""
    def completed(graph):
        series = [e for e in graph.get("@graph", []) if "cpo:ExperimentalSeries" in as_list(e.get("@type"))]
        return bool(series) and series[0].get("cpo:isCompleted") is True
    return completed(datagraph) and not completed(previous)


def keep_creation_date(datagraph: dict, now: str):
    """The crate keeps the creation date of its first run; every later run sets dateModified."""
    root = find_entity(datagraph, "./")
    previous = _previous["crate"]
    if root is None or previous is None:
        return
    earlier_root = find_entity(previous, "./")
    if earlier_root is not None and earlier_root.get("dateCreated"):
        root["dateCreated"] = earlier_root["dateCreated"]
    root["dateModified"] = now


def archive_if_completed(datagraph: dict, identifier: str):
    """Move the folder of a completed series to the archive."""
    series = [e for e in datagraph.get("@graph", []) if "cpo:ExperimentalSeries" in as_list(e.get("@type"))]
    if not series or series[0].get("cpo:isCompleted") is not True:
        return
    source, target = path_definitions.crate_folder(identifier), path_definitions.archived_crate_folder(identifier)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(target))
    print(f"[crate] The series is completed - archived in {target}.")
