"""
Writes a file so that a short lock by another program does not stop the run: the writing is
repeated a few times, with a growing pause, before it gives up with a clear error.

The project folder lies in OneDrive. While the sync service holds a file open, open(path, "w")
fails with "OSError: [Errno 22] Invalid argument"; a virus scanner or an indexer that has a freshly
written file open makes os.replace onto it fail with "PermissionError: [WinError 5]" (also in the
temp folder of an isolated copy). A moment later the same call works.

Two ways, by how often a file is written:
- write_atomic - completely into a neighbouring .tmp file, then moved into place with os.replace.
  os.replace is atomic: there is no moment in which the target lies half-written on disk. For the
  crate and the libraries, the to-do list, the file metadata overviews, the driver report.
- write_in_place - opened and overwritten. For the answer file, which is written anew after every
  answer (ten thousand times in a large run): measured on 15.10.2026 in the temp folder, 3000
  writes of an answer file of 300 KB took 3.4 s in place without a single failure, and 38.9 s
  with .tmp and os.replace, 4.5 % of them refused for up to 1.2 s - the scanner looks at every
  new file. A run that stops in the middle of writing it leaves the file half-written; it is in
  Git, and the next run writes it whole.

The module imports nothing of the generator, so that every helper can use it without a circular
import (helpers/entities.py imports helpers/user_io.py, and helpers/file_handling.py imports
helpers/entities.py - user_io could not import file_handling).
"""

import os
import time
from pathlib import Path

ATTEMPTS = 10


def _pause(attempt: int) -> float:
    """0.1, 0.2, 0.4, 0.8, then 1 s - about 6.5 s in all before the last attempt."""
    return min(0.1 * 2 ** attempt, 1.0)


def _write(path: Path, content) -> None:
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)


def _repeated(path: Path, action) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    last_error = None
    for attempt in range(ATTEMPTS):
        try:
            action()
            return
        except OSError as error:
            last_error = error
            if attempt < ATTEMPTS - 1:
                time.sleep(_pause(attempt))

    raise OSError(
        f"{path} could not be written even after {ATTEMPTS} attempts - last: {last_error}. "
        f"A typical reason: a sync service (OneDrive) or a virus scanner holds the file open right now."
    ) from last_error


def write_atomic(path, content) -> None:
    """Write content to path through a .tmp file and os.replace. A str is written as text in UTF-8
    with the line ends of the platform, exactly like Path.write_text; bytes as they are."""
    path = Path(path)
    temp_path = path.with_name(path.name + ".tmp")

    def action():
        _write(temp_path, content)
        os.replace(temp_path, path)
    _repeated(path, action)


def write_in_place(path, content) -> None:
    """Overwrite path with content (str or bytes, as write_atomic) - for a file written very often."""
    path = Path(path)
    _repeated(path, lambda: _write(path, content))
