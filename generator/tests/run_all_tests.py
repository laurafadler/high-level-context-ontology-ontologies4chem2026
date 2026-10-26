"""
Runs every test of the generator (generator/tests/*_test.py) one after the other and reports which passed.

Each test runs in its own process from the repository root, as its docstring says, with its exit code as the
verdict (0 passed, anything else failed). The output of each test goes to a log file of its own; the console
shows one line per test with its duration, and at the end the failed ones with the tail of their log. Some
tests build copies of crates and take minutes - the whole set takes a while.

Usage (from the repository root):
    python generator/tests/run_all_tests.py [--only NAME ...] [--skip NAME ...] [--log-dir DIR]
NAME is the file name with or without "_test.py" (identifiers, phase_space_test.py). Exit code 1 if a test failed.
"""
import argparse
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parent.parent


def _name(text: str) -> str:
    return text.removesuffix(".py").removesuffix("_test")


def main():
    parser = argparse.ArgumentParser(description="Run every test of the generator and report which passed.")
    parser.add_argument("--only", nargs="+", default=[], help="run only these tests")
    parser.add_argument("--skip", nargs="+", default=[], help="leave these tests out")
    parser.add_argument("--log-dir", type=Path,
                        default=Path(os.environ.get("TEMP", "/tmp")) / "cr" / "test_logs" / datetime.now().strftime("%Y%m%d_%H%M%S"))
    args = parser.parse_args()

    tests = sorted(TESTS.glob("*_test.py"))
    known = {_name(t.name) for t in tests}
    unknown = sorted({_name(n) for n in args.only + args.skip} - known)
    if unknown:
        sys.exit(f"No such test: {', '.join(unknown)}")
    if args.only:
        tests = [t for t in tests if _name(t.name) in {_name(n) for n in args.only}]
    tests = [t for t in tests if _name(t.name) not in {_name(n) for n in args.skip}]

    args.log_dir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONIOENCODING="utf-8")
    failed, started = [], time.time()
    print(f"{len(tests)} tests, logs in {args.log_dir}")
    for test in tests:
        log = args.log_dir / f"{_name(test.name)}.txt"
        begin = time.time()
        with open(log, "w", encoding="utf-8") as out:
            code = subprocess.run([sys.executable, str(test.relative_to(ROOT))], cwd=ROOT, env=env,
                                  stdout=out, stderr=subprocess.STDOUT).returncode
        verdict = "ok    " if code == 0 else f"FAILED (exit {code})"
        print(f"  {verdict:<16} {test.name}  ({time.time() - begin:.0f} s)", flush=True)
        if code != 0:
            failed.append((test.name, log))

    print(f"\n{len(tests) - len(failed)} of {len(tests)} passed in {(time.time() - started) / 60:.1f} min.")
    for name, log in failed:
        tail = log.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-15:]
        print(f"\n--- {name} (log: {log})")
        print("\n".join("    " + line for line in tail))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
