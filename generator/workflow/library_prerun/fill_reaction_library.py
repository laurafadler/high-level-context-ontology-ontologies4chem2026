"""
Stand-alone script for maintaining reaction_library.jsonld, i.e. adding new fixed
reactions. Completely separate from the actual crate run (main.py), which only reads the
library and never changes it (see the module docstring of creation/reaction_functions.py).

Uses the functions for the fixed level in creation/reaction_functions.py (create_fixed_reaction,
ask_reaction_participants, ask_reaction_mechanism), which the crate run does not call.

The participants are chosen from the chemical entity library, which this script only reads: a
substance that is not there yet is added first with the entry tool (type "substance",
docs/how_to_library_entries.md; rule 2.16). Reactions with concrete substances made from a
template: workflow/library_prerun/fixed_reaction_from_template.py.

Execute: python generator/workflow/library_prerun/fill_reaction_library.py
"""

import logging
import sys
from pathlib import Path

# Runs from generator/workflow/library_prerun/ - the generator has to be on the search path.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import path_definitions
from helpers.file_handling import load_jsonld, save_jsonld
from helpers.ontology_functions import initialize_ontologies
from helpers.user_io import ask_user, question_path
from helpers.identifiers import name_list, slugify
from creation.reaction_functions import create_fixed_reaction, _all_fixed_reactions
from helpers.identifiers import get_display_label


def main():
    reaction_library = load_jsonld(path_definitions.REACTION_LIBRARY_PATH)
    chemical_entity_library = load_jsonld(path_definitions.CHEMICAL_ENTITY_LIBRARY_PATH)
    namespace_collection = initialize_ontologies()

    existing = _all_fixed_reactions(reaction_library)
    if existing:
        print(f"The reaction library currently contains {len(existing)} reaction(s):")
        for reaction in existing:
            print(f"  - {get_display_label(reaction)}")

    # todo_list/local_todo_list are needed here only for the uniqueness check of IDs
    # (see create_fixed_reaction) - Fixed reactions have no phase/rate yet, so no
    # evidence/reference placeholders either that would depend on a real to-do list.
    todo_list = []
    local_todo_list = []

    # A Fixed scope of its own (see helpers/user_io.py: question_path) - this script maintains
    # only the Reaction Library, outside any "series:1" run. The new reactions as one list of names
    # instead of "another one?" with a counter (rule 1.4): the name is the key in the question
    # path (fixed/reaction:<name>), a further reaction shifts nothing.
    with question_path("fixed", reset=True):
        reaction_names = ask_user("Which new reactions do you want to add to the reaction library? Name them, separated by ';' (leave empty for none)",
                                  answer_type=name_list, question_id="new_reaction_names")
    for reaction_name in reaction_names:
        with question_path("fixed", reset=True), question_path("reaction", slugify(reaction_name)):
            create_fixed_reaction(namespace_collection, reaction_library, chemical_entity_library, todo_list, local_todo_list, name=reaction_name)

    save_jsonld(reaction_library, path_definitions.REACTION_LIBRARY_PATH)
    print(f"\nReaction library saved as: {path_definitions.REACTION_LIBRARY_PATH}")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    main()
