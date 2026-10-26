"""
Drive main.py without anyone typing: answers come from the answer file, and every question
the file does not know is either answered by an explicit rule or stops the run.

This replaces the one-off fill_answers.py/auto_driver.py scripts that sessions used to write
into their scratchpads. Two lessons from those scripts are built in:

- A blanket default for an open question (a name, a description) creates CONTENT, and it
  does so quietly and wrongly: "every new name question -> 'Assuming how much was drawn'"
  once gave 32 different tasks the same name. Open
  questions are therefore never answered by a default, only by a rule naming their key.
- A blind default on a choice changes the STRUCTURE: "take the first option" once turned the
  content of a vial into a stream. In the default mode
  an unknown question therefore stops the run.

It refuses to run in the project folder itself, because a run overwrites the crate, the
answer file and the to-do list. Use generator/workflow/isolated_run.py, which makes a copy and runs this
driver there (the copy carries the marker file ISOLATED_MARKER).

Rules file (JSON), a list of objects:

    [
      {"key": "series:1/experiment:*/material:14/volume/have_reference", "answer": "Yes"},
      {"key": "series:1/material:14/volume/know_evidence_per_experiment", "answer": "Yes",
       "override": true}
    ]

- "key" is matched against the full answer key with fnmatch ("*" matches across "/").
- A rule without "override" only answers questions the file has no usable answer for.
- A rule with "override": true replaces a stored answer before the run starts. Its key must
  be exact (no wildcards), so that an override cannot hit more than it names.
- A rule that never matches is reported at the end - usually a typo in the key.
- A rule may say where its answer comes from, "source": "D: invented for the demonstration"
  (rule 2.10); it is written into the answer file as a "// source:" line.

With --setup projects/<crate_identifier>/setup.yaml the adapter (interfaces/eln/adapter.py) answers first,
from the setup sheet and the ELN core files it names; the rules fill what it leaves open.

The adapter answers only what the answer file does not: a stored answer wins. After a change of the
sheet, a stored answer would therefore hide the change - a value the sheet now knows stays unknown, and
the questions it brings (the times of the task that determined it ...) are never asked. --from-sheet
leaves the stored answers out: the run starts from an empty answer file and writes it anew, every answer
from the sheet (and the rules). generator/workflow/next_step.py explores and builds that way.

Modes for a question that neither the file nor a rule answers (--on-unknown):
    abort (default)  stop the run and name the key.
    log              keep going with a recognisable stand-in, and list every stand-in in the
                     report: "No" where it is an option, otherwise the first option; 0 for a
                     number; empty for an optional text (the generator then builds its
                     automatic name); "UNANSWERED <key>" for a required text. For finding
                     out which questions a change brings up - never for a crate you keep.

Run inside an isolated copy (normally via generator/workflow/isolated_run.py):
    ANSWER_FILE=projects/<crate_identifier>/answers.txt PYTHONPATH=. python generator/workflow/answer_driver.py \
        [--setup projects/<crate_identifier>/setup.yaml [--from-sheet]] [--rules rules.json] [--on-unknown abort|log] \
        [--report driver_report.json] [--log-task-keys]
"""
import argparse
import builtins
import fnmatch
import json
import sys
import traceback
from pathlib import Path

# Runs from generator/<folder>/ - the generator has to be on the search path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from helpers.safe_write import write_atomic  # noqa: E402

ISOLATED_MARKER = ".isolated_copy"


def _load_rules(path):
    if not path:
        return []
    rules = json.loads(Path(path).read_text(encoding="utf-8"))
    for rule in rules:
        if "key" not in rule or "answer" not in rule:
            raise ValueError(f"Rule without 'key' or 'answer': {rule}")
        if rule.get("override") and any(ch in rule["key"] for ch in "*?["):
            raise ValueError(f"An override rule needs an exact key, not a pattern: {rule['key']}")
        rule["hits"] = 0
    return rules


def _stand_in(key, options, answer_type, required):
    """The answer used in --on-unknown log mode, and whether it is content (open text)."""
    if options:
        # Imported here like helpers.user_io in main(): only there is the project on the search path.
        from helpers.user_io import option_label
        chosen = "No" if "No" in options else options[0]
        return option_label(chosen), False
    if answer_type is int:
        return "0", False
    # A list from the options that must not stay empty (helpers/user_io.py: ask_user_list).
    if getattr(answer_type, "list_required", False) and getattr(answer_type, "list_options", None):
        from helpers.user_io import option_label
        return option_label(answer_type.list_options[0]), False
    if required:
        return f"UNANSWERED {key}", True
    return "", True


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--setup", help="setup sheet (YAML) for the adapter, which answers before the rules")
    parser.add_argument("--from-sheet", action="store_true",
                        help="leave the stored answers out: start from an empty answer file, every answer from the "
                             "sheet (needs --setup)")
    parser.add_argument("--rules", help="JSON file with answer rules (see above)")
    parser.add_argument("--on-unknown", choices=("abort", "log"), default="abort")
    parser.add_argument("--report", default="driver_report.json")
    parser.add_argument("--log-task-keys", action="store_true",
                        help="record every task question key together with the task and its cause")
    parser.add_argument("--in-place", action="store_true",
                        help="allow running outside an isolated copy (overwrites crate, answers, to-do list)")
    args = parser.parse_args()
    if args.from_sheet and not args.setup:
        parser.error("--from-sheet needs --setup: without the sheet nothing would answer.")

    import path_definitions
    if not (path_definitions.BASE_FOLDER / ISOLATED_MARKER).exists() and not args.in_place:
        sys.exit(f"Refusing to run in {path_definitions.BASE_FOLDER}: this is not an isolated copy "
                 f"(no {ISOLATED_MARKER}). Use generator/workflow/isolated_run.py, or pass --in-place deliberately.")

    # Whoever still lands in the terminal here has found a gap in the driver - rather stop loudly
    # than wait for an input that never comes.
    def _no_input(*_):
        raise RuntimeError("input() reached - the driver let a question through")
    builtins.input = _no_input

    import helpers.user_io as uio

    rules = _load_rules(args.rules)
    report = {"status": None, "adapter_answers": [], "rule_answers": [], "stand_ins": [], "overrides": [],
              "task_keys": []}

    adapter = None
    if args.setup:
        from interfaces.eln.adapter import SetupAdapter
        adapter = SetupAdapter(Path(args.setup), path_definitions.BASE_FOLDER)

    # Overrides replace stored answers before the first question comes.
    uio._load_answer_file()
    if args.from_sheet:
        uio._answer_entries.clear()
        uio._answer_order.clear()
    for rule in (r for r in rules if r.get("override")):
        entry = uio._answer_entries.get(rule["key"])
        before = entry["answer"] if entry else None
        if entry is None:
            uio._answer_entries[rule["key"]] = {"comments": [], "answer": rule["answer"]}
            uio._answer_order.append(rule["key"])
        else:
            entry["answer"] = rule["answer"]
        rule["hits"] += 1
        report["overrides"].append({"key": rule["key"], "before": before, "after": rule["answer"]})

    def provider(*, key, prompt, options, answer_type, required, stored):
        if adapter is not None:
            answered = adapter(key=key, prompt=prompt, options=options, answer_type=answer_type,
                               required=required, stored=stored)
            if answered is not None:
                report["adapter_answers"].append({"key": key, "answer": answered[0], "source": answered[1]})
                return answered
        for rule in rules:
            if not rule.get("override") and fnmatch.fnmatchcase(key, rule["key"]):
                rule["hits"] += 1
                report["rule_answers"].append({"key": key, "answer": rule["answer"], "rule": rule["key"]})
                return (rule["answer"], rule["source"]) if rule.get("source") else rule["answer"]
        if args.on_unknown == "abort":
            raise RuntimeError(f"Unknown question, no rule for it: '{key}' ({prompt})"
                               + (f" [stored answer was invalid: {stored!r}]" if stored is not None else ""))
        answer, is_content = _stand_in(key, options, answer_type, required)
        # What the sheet knows of the question, if anything (the start of a task without its other
        # times) - still a stand-in, the rest goes into the sheet.
        known = adapter.stand_in(key, options or getattr(answer_type, "list_options", None)) if adapter is not None else None
        if known is not None:
            answer, is_content = known, False
        report["stand_ins"].append({"key": key, "prompt": prompt, "options": options,
                                    "answer": answer, "open_text": is_content,
                                    "replaced_invalid": stored})
        return answer

    uio.set_answer_provider(provider)

    if args.log_task_keys:
        import creation.task_functions as task_functions
        original = task_functions.task_question_key

        def logged_task_question_key(task, datagraph=None, todo_list=None, local_todo_list=None):
            key = original(task, datagraph, todo_list, local_todo_list)
            pools = [pool for pool in (datagraph, todo_list, local_todo_list) if pool is not None]
            report["task_keys"].append({"path": uio._current_path_prefix(), "key": key,
                                        "task": task.get("@id"),
                                        "cause": task_functions._cause_of(task, pools)})
            return key
        task_functions.task_question_key = logged_task_question_key

    import main as main_module
    try:
        main_module.main()
        report["status"] = "completed"
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        report["status"] = f"stopped: {type(exc).__name__}: {exc}"

    report["unused_rules"] = [rule["key"] for rule in rules if rule["hits"] == 0]
    write_atomic(args.report, json.dumps(report, indent=1, ensure_ascii=False))

    print("\n=== answer driver ===")
    print(f"status:        {report['status']}")
    print(f"overrides:     {len(report['overrides'])}")
    if adapter is not None:
        print(f"adapter:       {len(report['adapter_answers'])}")
    print(f"rule answers:  {len(report['rule_answers'])}")
    print(f"stand-ins:     {len(report['stand_ins'])}"
          + (f" (of which open text: {sum(s['open_text'] for s in report['stand_ins'])})" if report["stand_ins"] else ""))
    if report["unused_rules"]:
        print(f"UNUSED RULES:  {len(report['unused_rules'])} - check these keys:")
        for key in report["unused_rules"]:
            print(f"    {key}")
    print(f"report:        {Path(args.report).resolve()}")
    sys.exit(0 if report["status"] == "completed" else 1)


if __name__ == "__main__":
    main()
