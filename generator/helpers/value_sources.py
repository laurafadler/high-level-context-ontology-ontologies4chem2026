"""
Which quantities of an exemplar have a value - asked as lists, one per exemplar and level,
instead of a yes/no question per quantity (rule 4.2).

A quantity only REGISTERS where it comes up (request_value_sources), and once the question path
of its owner is left, the exemplar asks at most three lists:

- series level: "evidence for the whole series?", "reference for the whole series?",
  "known in the individual experiments?"
- experiment level: "evidence?", "reference?" - offering only what the series level marked as
  known in the experiments (plus quantities that never had that series question).

Then add_evidence/add_reference run for the chosen quantities, under the question path of the
quantity and without a yes/no question (confirmed=True), and the answer file only lists what
really exists.

What belongs to one exemplar is read off the question path: a quantity registers under the
path of its owner, and everything registered under the same path is one list. The lists are
asked when the question path leaves that path (the hook in helpers/user_io.py: question_path).
A series list is always asked before an experiment list, since the experiment offers only what
the series marked as known.
"""

from helpers.evidence_reference import add_evidence, add_reference
from helpers.identifiers import get_display_label
from helpers.user_io import ask_user_list, at_question_path, current_question_path, _path_exit_hooks

SERIES = "hlo:SeriesSpecific"

_pending = {}        # path (tuple) -> {"scope": ..., "items": [...], "order": n}
_flushing = False
_counter = [0]


def request_value_sources(variable: dict, entity: dict, scope: str, nr, namespace_collection: dict, datagraph: dict,
                          todo_list: list, local_todo_list: list, *, quantity: str, segment: str = None,
                          inside_segment: bool = False, offer_at_series: bool = True, gate_key=None,
                          evidence_known_cache: dict = None, evidence_types: list = None, reference_types: list = None,
                          offered: bool = True, quantity_kind: str = None, quantity_kind_options: list = None,
                          required: bool = False):
    """Register a quantity whose evidence/reference will be asked through its exemplar's lists.

    quantity: the name shown in the lists, unique within the exemplar ("temperature", "start_time").
    segment: the quantity's own question-path segment, pushed when its questions are asked -
        the same segment the quantity had before, so that every further key stays as it was.
    inside_segment: the caller is already inside that segment (the segment is then the last
        one of the current path, and the exemplar is the path above it).
    offer_at_series: at series level, may evidence/reference be given for the whole series?
    gate_key: the key of "known in the individual experiments?" in evidence_known_cache - at
        series level the answer is stored there, at experiment level it is read from there.
        None: the quantity has no such series question and is offered in every experiment.
    quantity_kind: the kind the values of this entry are given in, where it is fixed (the
        field strength of a field type).
    quantity_kind_options: the kinds the variable's property allows where there are several
        (rule 4.4) - the quantity is one entry, and the kind is asked for each value
        (helpers/evidence_reference.py: _ask_value_quantity_kind, rule 4.4).
    required: at experiment level the quantity needs a value - evidence or reference. Named in
        neither list, the run stops and says where to add it (the start of the experimental
        procedure, which orders the usage history of the devices).
    """
    # offered=False: the quantity exists, but no value is recorded at it - with a single-phase
    # material it belongs at the phase.
    if not offered:
        return
    path = list(current_question_path())
    replay = list(path)
    if inside_segment:
        path = path[:-1]
    elif segment is not None:
        replay.append(segment)
    key = tuple(path)
    if key not in _pending:
        _counter[0] += 1
        _pending[key] = {"scope": scope, "items": [], "order": _counter[0]}
    batch = _pending[key]
    if any(item["quantity"] == quantity for item in batch["items"]):
        raise ValueError(f"Two quantities named {quantity!r} register under {'/'.join(path)} - they would share one list entry.")
    batch["items"].append({
        "quantity": quantity, "variable": variable, "entity": entity, "scope": scope, "nr": nr,
        "namespace_collection": namespace_collection, "datagraph": datagraph,
        "todo_list": todo_list, "local_todo_list": local_todo_list, "replay": tuple(replay),
        "offer_at_series": offer_at_series, "gate_key": gate_key, "cache": evidence_known_cache,
        "evidence_types": evidence_types, "reference_types": reference_types,
        "quantity_kind": quantity_kind, "quantity_kind_options": quantity_kind_options, "required": required,
    })


def _known_in_experiments(item) -> bool:
    cache, key = item["cache"], item["gate_key"]
    if cache is None or key is None:
        return True
    return cache.get(key, True)


def _ask(path: tuple, batch: dict):
    items = batch["items"]
    scope = batch["scope"]
    subject = get_display_label(items[0]["entity"])
    with at_question_path(path):
        if scope == SERIES:
            offered = [item["quantity"] for item in items if item["offer_at_series"]]
            gated = [item for item in items if item["gate_key"] is not None and item["cache"] is not None]
            with_evidence = ask_user_list(
                f"[{scope}] For which quantities of {subject} is there direct measurement or observation evidence that holds for the whole series?",
                offered, question_id="quantities_with_evidence") if offered else []
            with_reference = ask_user_list(
                f"[{scope}] For which quantities of {subject} is there a reference or external value that holds for the whole series?",
                offered, question_id="quantities_with_reference") if offered else []
            if gated:
                known = ask_user_list(
                    f"[{scope}] For which quantities of {subject} do we know anything (evidence or reference) in the individual experiments?",
                    [item["quantity"] for item in gated], question_id="quantities_known_per_experiment")
                for item in gated:
                    item["cache"][item["gate_key"]] = item["quantity"] in known
        else:
            offered = [item["quantity"] for item in items if _known_in_experiments(item)]
            with_evidence = ask_user_list(
                f"[{scope}] For which quantities of {subject} is there direct measurement or observation evidence?",
                offered, question_id="quantities_with_evidence") if offered else []
            with_reference = ask_user_list(
                f"[{scope}] For which quantities of {subject} is there a reference or external value?",
                offered, question_id="quantities_with_reference") if offered else []
            # A required quantity without a value stops the run, instead of silently leaving a hole
            # (rule 2.9: assume nothing - an assumption is a reference of type Assumed).
            missing = [item["quantity"] for item in items if item["required"]
                       and item["quantity"] not in with_evidence and item["quantity"] not in with_reference]
            if missing:
                where = "/".join(str(segment) for segment in path)
                raise ValueError(
                    f"[{scope}] {subject} needs a value for {', '.join(missing)} (evidence, or a reference - an "
                    f"assumption is a reference of type Assumed). Name it in {where}/quantities_with_evidence or "
                    f"{where}/quantities_with_reference.")

    # Per quantity in the order of registration, evidence before reference - as before.
    for item in items:
        chosen_evidence = item["quantity"] in with_evidence
        chosen_reference = item["quantity"] in with_reference
        if not (chosen_evidence or chosen_reference):
            continue
        common = (item["variable"], item["entity"], item["scope"], item["namespace_collection"], item["datagraph"],
                  item["todo_list"], item["local_todo_list"])
        with at_question_path(item["replay"]):
            if chosen_evidence:
                add_evidence(*common, possible_evidence_types=item["evidence_types"], nr=item["nr"], confirmed=True,
                             quantity_kind=item["quantity_kind"], quantity_kind_options=item["quantity_kind_options"])
            if chosen_reference:
                add_reference(*common, possible_reference_types=item["reference_types"], nr=item["nr"], confirmed=True,
                              quantity_kind=item["quantity_kind"], quantity_kind_options=item["quantity_kind_options"])


def _flush(still_open):
    """Ask every pending exemplar whose path is no longer open - series before experiment."""
    global _flushing
    if _flushing:
        return
    _flushing = True
    try:
        while True:
            ready = [path for path in _pending
                     if still_open is None or tuple(still_open[:len(path)]) != path or len(still_open) < len(path)]
            if not ready:
                return
            # Series lists first: an experiment offers only what the series marked as known.
            ready.sort(key=lambda path: (_pending[path]["scope"] != SERIES, _pending[path]["order"]))
            path = ready[0]
            batch = _pending.pop(path)
            if batch["scope"] != SERIES:
                _ask_series_counterparts_first(batch)
            _ask(path, batch)
    finally:
        _flushing = False


def _ask_series_counterparts_first(batch: dict):
    """An experiment list needs the series answer "known in the individual experiments?". Is
    the series exemplar it depends on still pending (its path still open), it is asked now."""
    needed = {item["gate_key"] for item in batch["items"]
              if item["gate_key"] is not None and item["cache"] is not None and item["gate_key"] not in item["cache"]}
    if not needed:
        return
    for path in [path for path, pending in _pending.items() if pending["scope"] == SERIES]:
        if any(item["gate_key"] in needed for item in _pending[path]["items"]):
            _ask(path, _pending.pop(path))


def flush_all_value_sources():
    """Ask every list still pending - at the end of a run, for anything registered outside a path."""
    _flush(None)


_path_exit_hooks.append(lambda path: _flush(path))
