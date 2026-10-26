"""
Read an answer file (keyed-v2) the way the generator reads it (helpers/user_io.py: _load_answer_file):
every entry with its key, its comment lines and its answer, in file order. Used by
workflow/check_library_references.py.
"""

HEADER = "# answer-file-format: keyed-v2"
EMPTY = "<empty>"


def parse(text: str):
    """[(key, [comment lines], answer)] in file order."""
    lines = text.splitlines()
    assert lines[0] == HEADER, "not a keyed-v2 answer file"
    entries, i = [], 1
    while i < len(lines):
        if not lines[i].startswith("key: "):
            i += 1
            continue
        key = lines[i][5:]
        i += 1
        comments = []
        while i < len(lines) and lines[i].startswith("    //"):
            comments.append(lines[i])
            i += 1
        answer = lines[i] if i < len(lines) else ""
        # An answer that starts with "//" or "key:" stands with a space in front of it.
        if answer.startswith(" ") and (answer[1:].startswith("    //") or answer[1:].startswith("key:")):
            answer = answer[1:]
        entries.append((key, comments, "" if answer.strip() == EMPTY else answer))
        i += 1
    return entries
