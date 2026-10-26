"""
Appending to a section of a setup sheet as text - so that nothing in the sheet is
rewritten: its comments and everything written by hand stay as they are. PyYAML would lose the
comments when writing the sheet back.

A section is a key at the top level ("values:", "open:") and everything up to the next one. New
entries go to its end; a section that does not exist yet is added at the end of the sheet, with its
header comment.
"""
import re
from pathlib import Path

import yaml

from helpers.safe_write import write_atomic

_TOP_KEY = re.compile(r"^[A-Za-z_]+:", flags=re.MULTILINE)


class _SheetDumper(yaml.SafeDumper):
    """Blocks, one line per field - but a list of plain values in one line ("none: [density, mass]")."""


def _list_representer(dumper, data):
    flow = all(isinstance(item, (str, int, float, bool)) or item is None for item in data)
    return dumper.represent_sequence("tag:yaml.org,2002:seq", data, flow_style=flow)


_SheetDumper.add_representer(list, _list_representer)


def render_entries(entries: list) -> str:
    """List items as YAML text, indented under their section; nested blocks, one line per field."""
    text = yaml.dump(entries, Dumper=_SheetDumper, allow_unicode=True, sort_keys=False, width=1000, default_flow_style=False)
    return "".join(("  " + line) if line.strip() else line for line in text.splitlines(keepends=True))


def append_to_section(path: Path, section: str, header: str, entries: list):
    """Append entries to the end of a section of the sheet at path (or add the section)."""
    if not entries:
        return
    text = Path(path).read_text(encoding="utf-8")
    block = render_entries(entries)
    start = re.search(rf"^{section}:", text, flags=re.MULTILINE)
    if start is None:
        text = text.rstrip("\n") + "\n\n" + header + block
    else:
        following = [m.start() for m in _TOP_KEY.finditer(text) if m.start() > start.start()]
        end = following[0] if following else len(text)
        body = text[:end].rstrip("\n") + "\n"
        # An empty section ("values: []" or "open:") gets its entries below it. Only blanks around
        # "[]", not "\s" - that took the line break along ("occurrences:  - phases: ...");
        # a comment behind "[]" stays.
        body = re.sub(rf"^({section}:)[ \t]*\[\]([ \t]*#.*)?[ \t]*$", lambda m: m.group(1) + (m.group(2) or ""),
                      body, flags=re.MULTILINE)
        text = body + block + ("\n" + text[end:] if following else "")
    # The sheet is the source of the answers and lies in OneDrive: written whole or not at all, with retries
    # (helpers/safe_write.py); as bytes, so that the line ends stay those of the text (LF).
    write_atomic(path, text.encode("utf-8"))
