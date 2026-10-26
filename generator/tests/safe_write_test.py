"""Test for writing a file with retries (helpers/safe_write.py: write_atomic, write_in_place).

What matters: a program that holds the file open for a moment (OneDrive, "OSError: [Errno 22]
Invalid argument"; a virus scanner, "PermissionError: [WinError 5]") costs a retry, not the run;
after the last attempt the error says what happened; write_atomic leaves the old content untouched
until the new one is complete; and the text on disk is the same as before (line ends of the platform,
like Path.write_text). The answer file (helpers/user_io.py: _save_answer_file) is written in place.
It runs without the pipeline.

Run from the repository root:
    python generator/tests/safe_write_test.py
"""
# Runs from generator/tests/ - the generator has to be on the search path.
import builtins
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import helpers.safe_write as safe_write
import helpers.user_io as uio

REAL_REPLACE = os.replace
REAL_OPEN = builtins.open


def _failing_replace(failures: int, calls: list):
    """os.replace that is refused the first `failures` times, as by a virus scanner, then works."""
    def replace(source, target):
        calls.append(target)
        if len(calls) <= failures:
            raise PermissionError(13, "Access is denied")
        return REAL_REPLACE(source, target)
    return replace


def _failing_open(target: Path, failures: int, calls: list):
    """open that fails the first `failures` times for writing `target`, as under OneDrive, then works."""
    def opener(file, mode="r", *args, **kwargs):
        if Path(file) == target and "w" in mode:
            calls.append(file)
            if len(calls) <= failures:
                raise OSError(22, "Invalid argument")
        return REAL_OPEN(file, mode, *args, **kwargs)
    return opener


def run():
    ok = True

    def check(label, passed):
        nonlocal ok
        if not passed:
            ok = False
        print(f"  {label:66s} [{'OK' if passed else 'WRONG'}]")

    folder = Path(tempfile.mkdtemp(prefix="safe_write_test_"))
    text = "first line\nsecond line - ä\n"
    attempts = safe_write.ATTEMPTS

    with mock.patch("time.sleep"):
        # write_atomic: two refusals, then it works.
        target = folder / "two_failures.txt"
        target.write_text("old content\n", encoding="utf-8")
        calls = []
        with mock.patch("os.replace", side_effect=_failing_replace(2, calls)):
            safe_write.write_atomic(target, text)
        check("write_atomic, two refusals: written on the third attempt", len(calls) == 3)
        check("... the whole new content on disk", target.read_text(encoding="utf-8") == text)
        check("... no .tmp file left", not (folder / "two_failures.txt.tmp").exists())

        # write_atomic: refused every time - a clear error, the old content untouched.
        target = folder / "all_failures.txt"
        target.write_text("old content\n", encoding="utf-8")
        calls = []
        error = None
        with mock.patch("os.replace", side_effect=_failing_replace(attempts, calls)):
            try:
                safe_write.write_atomic(target, text)
            except OSError as exc:
                error = exc
        check("write_atomic, refused every time: OSError", error is not None)
        check(f"... after exactly {attempts} attempts", len(calls) == attempts)
        message = str(error)
        check("... the message names the file, the attempts and the likely cause",
              str(target) in message and f"{attempts} attempts" in message and "OneDrive" in message)
        check("... the cause is the last error", isinstance(getattr(error, "__cause__", None), OSError))
        check("... the old content untouched", target.read_text(encoding="utf-8") == "old content\n")

        # write_in_place: open fails three times (OneDrive), then it works.
        target = folder / "in_place.txt"
        target.write_text("old content\n", encoding="utf-8")
        calls = []
        with mock.patch("builtins.open", side_effect=_failing_open(target, 3, calls)):
            safe_write.write_in_place(target, text)
        check("write_in_place, three failures: written on the fourth attempt", len(calls) == 4)
        check("... the whole new content on disk", target.read_text(encoding="utf-8") == text)
        calls = []
        error = None
        with mock.patch("builtins.open", side_effect=_failing_open(target, attempts, calls)):
            try:
                safe_write.write_in_place(target, "never\n")
            except OSError as exc:
                error = exc
        check(f"write_in_place, failing every time: OSError after {attempts} attempts",
              error is not None and len(calls) == attempts and f"{attempts} attempts" in str(error))

    check("the pauses add up to less than 10 s", sum(safe_write._pause(a) for a in range(attempts - 1)) < 10)

    # The bytes on disk are those of Path.write_text (line ends of the platform).
    reference = folder / "reference.txt"
    reference.write_text(text, encoding="utf-8")
    for name, write in (("write_atomic", safe_write.write_atomic), ("write_in_place", safe_write.write_in_place)):
        written = folder / f"{name}.txt"
        write(written, text)
        check(f"{name}: same bytes as Path.write_text", written.read_bytes() == reference.read_bytes())
        write(folder / name / "sub" / "new.txt", text)
        check(f"{name}: a missing folder is created", (folder / name / "sub" / "new.txt").exists())
        data = bytes(range(256))
        write(folder / f"{name}.bin", data)
        check(f"{name}: bytes written as they are", (folder / f"{name}.bin").read_bytes() == data)

    # The answer file: one OneDrive failure while saving costs a retry, the file is complete.
    answers = folder / "answers.txt"
    uio._answer_path = answers
    uio._answer_order = ["setup/series_short_name", "series:1/experiment:1/temperature"]
    uio._answer_entries = {
        "setup/series_short_name": {"comments": ["    // Short name?"], "answer": "test"},
        "series:1/experiment:1/temperature": {"comments": ["    // Temperature? [in degC]"], "answer": ""},
    }
    expected = "\n".join([uio.FORMAT_HEADER, "",
                          "key: setup/series_short_name", "    // Short name?", "test", "",
                          "key: series:1/experiment:1/temperature", "    // Temperature? [in degC]",
                          uio.EMPTY_ANSWER_MARKER]) + "\n"
    reference.write_text(expected, encoding="utf-8")
    calls = []
    with mock.patch("time.sleep"), mock.patch("builtins.open", side_effect=_failing_open(answers, 1, calls)):
        uio._save_answer_file()
    check("answer file: written on the second attempt", len(calls) == 2)
    check("answer file: same bytes as written with Path.write_text", answers.read_bytes() == reference.read_bytes())
    check("answer file: no .tmp file", not (folder / "answers.txt.tmp").exists())

    print(f"\n{'ALL TESTS OK' if ok else 'ERRORS - see WRONG above'}")
    return ok


if __name__ == "__main__":
    raise SystemExit(0 if run() else 1)
