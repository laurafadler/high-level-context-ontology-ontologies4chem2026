


from helpers.ontology_functions import check_existence, shorten_id


def set_property(entity: dict, property: str, value, namespace_collection: dict, multi: bool = False):

    # Inputs:
    # the entity the property is to be attached to,
    # the property as a string
    # value can be either a normal string, int, ... value, or a dict, i.e. an entity we want to link with this property (assumption: we have checked before that this entity exists, with the link-or-create function or find or so)
    # whether the property allows several values (multi, default false, then the value would be overwritten)


     # JSON-LD keywords
    if property == "@id":
        entity["@id"] = value
        return

    elif property == "@type":
        if isinstance(value, list):
            entity["@type"] = value
        else:
            entity.setdefault("@type", []).append(value)
        return


    # Ordinary property
    elif property.startswith("@"):
        raise ValueError(f"Property was not set: {property}.")

    property_compact = shorten_id(property, namespace_collection)

    if check_existence(property, namespace_collection, "property"):

        if isinstance(value, dict):
            entityToLink_ID = value.get("@id")
            entityToLink_ID_compact = shorten_id(
                entityToLink_ID,
                namespace_collection
            )
            value = {"@id": entityToLink_ID_compact}

        elif isinstance(value, str) and ":" in value:
            prefix = value.split(":", 1)[0]

            if prefix in namespace_collection:
                value = {"@id": value}

    if multi:
        existing = entity.setdefault(property_compact, [])
        # A single value set already becomes a list: a shared actual (the mass of a pure phase,
        # which is also that of its only molecule) gets its second context only after the first
        # was set without multi.
        if not isinstance(existing, list):
            existing = entity[property_compact] = [existing]
        if value not in existing:
            existing.append(value)
    else:
        entity[property_compact] = value


def set_literal_property(entity: dict, property: str, value, xsd_type: str, namespace_collection: dict, multi: bool = False):
    """Like set_property, but for explicitly typed JSON-LD literals
    ({"@value": ..., "@type": xsd_type}) - timestamps (xsd:dateTime) or QUDT values
    (xsd:decimal), for example.

    set_property cannot do this: a dict value is always read there as a link to
    another entity (it looks for "@id" inside).
    """
    property_compact = shorten_id(property, namespace_collection)
    literal = {"@value": str(value), "@type": xsd_type}

    if multi:
        existing = entity.setdefault(property_compact, [])
        if literal not in existing:
            existing.append(literal)
    else:
        entity[property_compact] = literal


def check_type(entity_type, namespace_collection):

    exists = False
    # If a list
    if isinstance(entity_type, list):
        for t in entity_type:

            if check_existence(t, namespace_collection, "class"):
                exists = True
            else:
                raise ValueError(f"{t} is not defined as a class in the loaded ontologies.")

    else:
        # if a single value
        if check_existence(entity_type, namespace_collection, "class"):
            exists = True

    if exists == True:
        return entity_type

    else:
        raise ValueError(f"Type check for {entity_type} failed.")


def get_type(entity):
    # Levels and value roles are no class of the thing. Lower case, because the lower-case local
    # name is compared below. "template" is hlo:Template (rule 3.11).
    excluded_types = {
        "fixed",
        "template",
        "seriesspecific",
        "experimentspecific",
        "actual",
        "evidence",
        "reference",
    }

    for entity_type in entity.get("@type", []):
        # Look only at the local name, in case a compact ID is used
        local_type = entity_type.split(":")[-1].lower()

        if local_type not in excluded_types:
            return entity_type

    return None


def set_location(entity: dict, property_name: str, holder: dict, namespace_collection: dict):
    """Record where an entity of the crate is located (cpo:location or one of its subproperties)
    together with the way back, cpo:isLocationOf on the holder.

    Only for a holder of the same level in the crate (the ambient air of the level, the device
    of the level it sits in): the energy field collection paths descend along cpo:isLocationOf,
    and a Fixed room carrying it would lead them into the devices of every level and every crate.
    The location of the ambient air in its room is therefore set with set_property alone.
    """
    # Boundary (rule 7.9): never at a library entry - the room would have no level there.
    if "hlo:Fixed" in (holder.get("@type") or []):
        raise ValueError(f"{holder['@id']} is a library entry - it must not point at what is located in it.")
    set_property(entity, property_name, holder, namespace_collection)
    set_property(holder, "cpo:isLocationOf", entity, namespace_collection, True)
