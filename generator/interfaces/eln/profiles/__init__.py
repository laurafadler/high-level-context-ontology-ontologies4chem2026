"""ELN profiles: one module per ELN, each with matches(archive) and to_core(archive, record)."""
from interfaces.eln.profiles import ai4green, chemotion, elabftw
from interfaces.eln.reader import ElnArchive

PROFILES = [ai4green, elabftw, chemotion]


def open_export(path):
    """An ELN export to read: an .eln file (RO-Crate), or the collection export of Chemotion (a ZIP of
    its own) - each with producer(), records() and the files of a record."""
    if chemotion.is_export(path):
        return chemotion.ChemotionExport(path)
    return ElnArchive(path)


def profile_for(archive):
    for profile in PROFILES:
        if profile.matches(archive):
            return profile
    raise ValueError(f"{archive.path.name}: no profile for the ELN '{archive.producer().get('name')}'.")
