"""
Open a completed (archived) series again, so that it can be built anew - after a change to the
generator, the setup sheet or the ontologies.

A completed series cannot be continued (helpers/crate_continuation.py: SeriesCompletedError), and a
series whose crate is missing but whose identifier the device library still records cannot be
started again (UnknownContinuationError). By hand both would be undone with `git revert` of the
"Usage history of crate ..." commits - in the right order, since two crates can touch the same
device - and by deleting crate_completed/. This script does the same from the content instead of the
history:

- every entry of the device and material libraries that points into the crate is taken out of
  cpo:hasUsageHistory, and cpo:lastUsedPurpose / cpo:lastUsedTime point at the latest entry left
  (looked up like creation/device_usage_functions.py does - in the library or in the crate the
  entry belongs to);
- an end of a content of the inventory (cpo:hasEndTime) set by this crate stops the script - it is
  rare and wants a person to look (nothing is undone silently);
- crate_completed/ of the series is deleted (it is in git; the rebuild writes it again).

The library change is committed like any change a run makes to the libraries (not in an isolated
copy - generator/workflow/isolated_run.py --reopen uses this script there).

Usage (from the repository root):
    python generator/workflow/reopen_crate.py <identifier> [<identifier> ...]
Then build again, e.g.:
    ALLOW_EARLIER_CHANGES=1 ANSWER_FILE=projects/<identifier>/answers.txt python generator/workflow/answer_driver.py \
        --in-place --setup projects/<identifier>/setup.yaml --from-sheet
Several crates anew together: build the open ones before reopening the completed ones (docs/rules_crate.md, 5.7).
"""
import argparse
import os
import shutil
import stat
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import path_definitions  # noqa: E402
from creation.device_usage_functions import _Moments, _own_prefix  # noqa: E402
from helpers.entities import ref_id, ref_ids
from helpers.file_handling import save_jsonld  # noqa: E402
from helpers.git_functions import commit_library_changes  # noqa: E402
from helpers.library_functions import load_device_libraries  # noqa: E402

USAGE_PROPERTIES = ("cpo:hasUsageHistory", "cpo:lastUsedPurpose", "cpo:lastUsedTime")


def take_out_usage(identifier: str) -> list:
    """Take the entries of this crate out of the usage histories; returns the devices changed."""
    prefix = _own_prefix(identifier)
    view, documents = load_device_libraries()
    moments = _Moments({"@graph": []}, view)
    changed = []
    for device in view.get("@graph", []):
        if str(ref_id(device.get("cpo:hasEndTime"))).startswith(prefix):
            raise SystemExit(f"{device['@id']}: its content ends in crate {identifier} (cpo:hasEndTime) - "
                             "undo that by hand, it is not taken out silently.")
        history = ref_ids(device.get("cpo:hasUsageHistory"))
        kept = [entry for entry in history if not entry.startswith(prefix)]
        points_in = any(str(ref_id(device.get(p))).startswith(prefix) for p in ("cpo:lastUsedPurpose", "cpo:lastUsedTime"))
        if kept == history and not points_in:
            continue
        changed.append(device["@id"])
        if kept:
            device["cpo:hasUsageHistory"] = [{"@id": entry} for entry in kept]
            latest = kept[-1]
            if "cpo:lastUsedPurpose" in device:
                device["cpo:lastUsedPurpose"] = {"@id": latest}
            end_time = ref_id((moments.find(latest) or {}).get("cpo:hasEndTime"))
            if end_time:
                device["cpo:lastUsedTime"] = {"@id": end_time}
            else:
                device.pop("cpo:lastUsedTime", None)
        else:
            for prop in USAGE_PROPERTIES:
                device.pop(prop, None)
    for path, document in documents.items():
        save_jsonld(document, path)
    return changed


def remove_folder(folder: Path):
    """Delete a folder - under Windows a file or folder just copied can be held for a moment (indexer, virus
    scanner) or be read-only: clear the flag and try again a few times before giving up."""
    def retry(function, path, _error):
        os.chmod(path, stat.S_IWRITE)
        for attempt in range(5):
            try:
                function(path)
                return
            except OSError:
                time.sleep(0.5 * (attempt + 1))
        function(path)
    shutil.rmtree(folder, onexc=retry)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("identifiers", nargs="+", help="identifier(s) of the series (projects/<identifier>/)")
    args = parser.parse_args()
    for identifier in args.identifiers:
        folder = path_definitions.archived_crate_folder(identifier)
        if not folder.exists():
            print(f"{identifier}: no completed crate ({folder}) - only the usage history is cleaned.")
        changed = take_out_usage(identifier)
        print(f"{identifier}: usage taken out of {len(changed)} device(s){': ' + ', '.join(changed) if changed else ''}.")
        if folder.exists():
            remove_folder(folder)
            print(f"{identifier}: {folder} deleted - build the series again.")
        if commit_library_changes(f"Reopen crate {identifier}: its usage history taken out of the libraries"):
            print(f"{identifier}: library change committed.")


if __name__ == "__main__":
    main()
