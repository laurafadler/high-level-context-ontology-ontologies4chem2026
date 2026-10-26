"""
Counter-test of fields of the setup sheet (file type and creator, the phases at a port
crossing, the transfers of a reaction's participants, the place of elementary reactions, the document of an
occurrence statement, the occupation states of an interface): the adapter answers the keys of an answer file from the sheet, and its answer must be the one
the answer file holds - the sheet then says what the answer file said, nothing else. Only the keys of the new fields
are replayed; a key the sheet does not answer (field left out) is counted, not failed.

Run from the repository root:
    python generator/tests/sheet_replay_test.py [project ...]     (default: chemotion_example)
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "generator"))
from interfaces.eln.adapter import SetupAdapter  # noqa: E402
from helpers.user_io import option_label  # noqa: E402

NEW = ("media_object_type", "creator_kind", "creator_person", "device_side_phase", "opens_into_phase",
       "crossing_stream_phases", "location_kind", "location_interface", "reference_source")
NEW_PATTERN = re.compile(r".*/(" + "|".join(NEW) + r")$|.*/participant_transfer:[^/]+/(phase|transfer_type)$"
                         # the occupation states of an interface (section occupation_states)
                         r"|.*/phase_interface:[^/]+/occupation_state_names$"
                         r"|.*/occupation_state:[^/]+/(target_interface|is_free_site|has_bound_to|sorption_type|"
                         r"occupied_by_quick_pick|bound_to_quick_pick|(occupied_by|bound_to)_search:\d+/identifier_(field|value))$"
                         r"|series:1/occupation_state:[^/]+/occupation_state$")


def entries(path):
    """(key, question, answer) of an answer file (format keyed-v2)."""
    lines = path.read_text(encoding="utf-8").splitlines()
    i = 0
    while i < len(lines):
        if lines[i].startswith("key: "):
            key, question, j = lines[i][5:].strip(), None, i + 1
            while j < len(lines) and lines[j].startswith("    //"):
                if question is None and not lines[j].startswith("    // source:"):
                    question = lines[j][7:].strip()
                j += 1
            answer = lines[j] if j < len(lines) else ""
            yield key, question or "", "" if answer == "<empty>" else answer
            i = j
        i += 1


def options_of(question):
    """The options in the last [...] of a question, split at ', ' outside quotes."""
    found = re.findall(r"\[([^\[\]]*)\]", question)
    if not found or found[-1].startswith("hlo:"):
        return None
    return [o.strip() for o in re.split(r",\s+(?=(?:[^\"]*\"[^\"]*\")*[^\"]*$)", found[-1]) if o.strip()]


ok = True
for project in sys.argv[1:] or ["chemotion_example"]:
    folder = ROOT / "projects" / project
    adapter = SetupAdapter(folder / "setup.yaml", folder)
    same = differ = unanswered = from_open = 0
    for key, question, recorded in entries(folder / "answers.txt"):
        if not NEW_PATTERN.match(key):
            continue
        got = adapter(key=key, prompt=question, options=options_of(question), answer_type=str, required=False, stored=None)
        if key in adapter.open_answers:
            from_open += 1      # still answered in the section "open", not by a field
        if got is None:
            unanswered += 1
            print(f"  [not in the sheet] {key}")
            continue
        # Compared the way helpers/user_io.py matches an answer to its options (cpo:File is shown as File).
        if str(got[0]) == recorded or str(got[0]) == option_label(recorded):
            same += 1
        else:
            differ += 1
            print(f"  [DIFFERENT] {key}: sheet {got[0]!r}, answer file {recorded!r}")
    ok &= differ == 0
    print(f"{project}: {same} the same ({from_open} of them from the section 'open'), {differ} different, "
          f"{unanswered} not answered by the sheet")
print("ALL OK" if ok else "SOME DIFFERENT")
sys.exit(0 if ok else 1)
