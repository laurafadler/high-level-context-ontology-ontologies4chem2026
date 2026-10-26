"""
Creates the context aspects of a crate (series and experiment level). Which entities describe
them is not decided here: helpers/context_links.py links them from the shapes at the end of a run.
"""



from helpers.entities import find_entity, add_entity
from helpers.properties import set_property
from helpers.identifiers import crate_id
from helpers.ontology_functions import find_entity_in_ontology

def create_all_contexts(number_series: int, number_experiments: int, namespace_collection, datagraph: dict):


    level = ["Device", "Phase", "Molecule"]
    category = ["Information", "Energy", "Time", "Space", "Structure", "Substance"]

    # Series specific context
    for s in range(number_series):
        for l in level:
            for c in category:
                create_context_aspect(l, c, "SeriesSpecific", s+1, namespace_collection, datagraph)

    for e in range(number_experiments):
            for l in level:
                for c in category:
                    create_context_aspect(l, c, "ExperimentSpecific", e+1, namespace_collection, datagraph)

    # Experiment specific context

    return

def create_context_aspect(level: str, category: str, scope: str, nr: int, namespace_collection, datagraph: dict):

    # Basic Information
    # Both types need the hlo: prefix, so that they resolve to the ontology via the
    # @context. Without a prefix JSON-LD resolves relative to the URL of the document -
    # the type then depends on where the crate is loaded from, and a query for
    # hlo:ContextAspect finds not a single entity.
    # scope stays built into the entity_id without a prefix (there it is part of the
    # name, not a reference to the ontology).
    entity_type = ["hlo:ContextAspect", f"hlo:{scope}"]
    if scope == "SeriesSpecific":
        entity_id = crate_id(f"{scope}{level}{category}_Series")
    else:
        entity_id = crate_id(f"{scope}{level}{category}_Exp{nr}")

    context_aspect = {
            "@id": entity_id,
            "@type": entity_type,
        }

    # Further Information

    # Link with the fixed context aspects of the ontology

    individual_name = f"hlo:{level}{category}"

    fixed_context_aspect = find_entity_in_ontology(individual_name, namespace_collection)

    if scope == "SeriesSpecific":
        # A series context specializes only the fixed ontology entry
        set_property(context_aspect, "hlo:specializationOf", fixed_context_aspect, namespace_collection)
    else:
        # An experiment context specializes both the fixed ontology entry and the
        # matching series context -> hence multi=True here for both
        set_property(context_aspect, "hlo:specializationOf", fixed_context_aspect, namespace_collection, True)

        # Look for the matching series context (assumption: only one series per crate)
        series_context_id = crate_id(f"SeriesSpecific{level}{category}_Series")
        series_context_aspect = find_entity(datagraph, series_context_id)

        if series_context_aspect:
            set_property(context_aspect, "hlo:specializationOf", series_context_aspect, namespace_collection, True)
            set_property(series_context_aspect, "hlo:hasSpecialization", context_aspect, namespace_collection, True)





    # Write into the crate
    add_entity(datagraph, context_aspect)
