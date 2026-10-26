"""
Names of things the generator derives - transfers, phase pair interfaces, places - as a person writes
them in the setup sheet.

The generator names a transfer "<species>-<type>-from-<phase>-to-<phase>" (Hydrogen-PortCrossing-from-
Sparger_Inlet_Phase-to-Sparger_Phase) and an interface by its two phases (PhasePairInterface_Phase_A_Phase_B).
In the sheet a transfer may be written readably, "<species> from <phase> to <phase>" - the type follows from
the place -, or "<species> by <Type> from <phase> to <phase>" where two types are possible, and an
interface as "A / B". Both full generator names are understood as well. Whether a
readable name is unambiguous only the generator knows (two transfers of different type between the same
phases at one interface): the adapter then answers nothing, and the exploratory run shows the question.
"""
import re

# The substance may contain hyphens (6-Iminocapronitrile); the type is one word in CamelCase.
TRANSFER_LABEL = re.compile(r"^(?P<species>.+?)-(?P<type>[A-Z][A-Za-z]*)-from-(?P<a>.+)-to-(?P<b>.+)$")
# With the kind, where several kinds are possible between the same phases (degassing
# and vaporization from the liquid into the gas): "<species> by <Type> from <phase> to <phase>".
READABLE_TRANSFER = re.compile(r"^(?P<species>.+?)(?: by (?P<type>[A-Z][A-Za-z]*))? from (?P<a>.+) to (?P<b>.+)$")
INTERFACE_PREFIX = "PhasePairInterface_"


def norm(text) -> str:
    return "".join(c for c in str(text).lower() if c.isalnum())


def transfer_matches(written, label) -> bool:
    """Whether a transfer as written in the sheet names the transfer the generator calls `label`."""
    if norm(written) == norm(label):
        return True
    readable, generated = READABLE_TRANSFER.match(str(written).strip()), TRANSFER_LABEL.match(str(label).strip())
    if not readable or not generated:
        return False
    parts = ("species", "a", "b") + (("type",) if readable.group("type") else ())
    return all(norm(readable.group(part)) == norm(generated.group(part)) for part in parts)


def _phase_ids(name) -> list:
    # A phase of the sheet is called "Phase_<name>" in the crate, a phase of the room (L109_Air_GasPhase) is not.
    return [name, f"Phase_{name}"]


def interface_forms(written) -> set:
    """Normalised generator names an interface written as "A / B" (or by its full name) may have -
    in either order of the phases, each with or without the "Phase_" of the crate ID."""
    text = str(written)
    if "/" not in text:
        return {norm(text)}
    a, b = (part.strip() for part in text.split("/", 1))
    return {norm(f"{INTERFACE_PREFIX}{x}_{y}") for first, second in ((a, b), (b, a))
            for x in _phase_ids(first) for y in _phase_ids(second)}


def place_matches(written, label) -> bool:
    """A place of transfers: a port (vessel001_opening) or an interface ("A / B" or its full name)."""
    return norm(label) in interface_forms(written)


def id_forms_of_place(written) -> list:
    """The forms a place takes in a generator ID (Transfer_<label>_<place>), lower case."""
    text = str(written)
    if "/" not in text:
        return [text.lower()]
    a, b = (part.strip() for part in text.split("/", 1))
    return [f"{INTERFACE_PREFIX}{x}_{y}".lower() for first, second in ((a, b), (b, a))
            for x in _phase_ids(first) for y in _phase_ids(second)]


def experiments_of(value, count: int) -> list:
    """The experiment numbers an entry applies to: "all" (every experiment the series has at the time of
    the run), a number, or a list of numbers."""
    if value is None or str(value).strip().lower() == "all":
        return list(range(1, count + 1))
    if isinstance(value, list):
        return [int(v) for v in value]
    return [int(value)]
