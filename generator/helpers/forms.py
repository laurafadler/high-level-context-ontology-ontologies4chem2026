"""
The forms of an exemplar on every level: a device's, a device body's, a room air's.

Every quantity of an exemplar exists as its own Actual on every level on which the exemplar
exists (rule 2.1) - its dimensions, too, since a
form can change during a process. The value stays where it was determined, in the library,
and each level reaches it through hlo:specializationOf: the form of the series device
specializes the library form, the form of the experiment device the series form, and every
dimension likewise the dimension one level up.

A device body shares the form of its device at library level (the device's form describes
exactly this wall), so on every level the body gets the SAME form copy as its device
(rule 3a.11) - the caller passes that copy in shared_forms.

A hollow form carries its cavity (cpo:hasCavityForm), and the cavity carries no dimension of its
own: each of its dimensions is the very Actual the hollow form uses in the opposite role (the
inner diameter of a cup is the diameter of its cavity). The copy keeps that: the cavity of the
copy points at the copies the hollow form just made.

The parts of a form (dcterms:hasPart, the blade of a stirrer shaft) and the layers of its wall
(cpo:hasLayerForm, rule 3.8a) belong to the same owner and are copied with it, each with
dimensions of its own (rule 3a.4).
"""

from helpers.entities import find_entity, add_entity, as_list, is_library_entity, ref_id, resolve
from helpers.identifiers import make_owned_id, generate_id_from_name, short_local_name, claim_id
from helpers.properties import set_property, check_type
from helpers.process_variables import add_specializing_actual
from helpers.value_sources import request_value_sources
from helpers.ontology_functions import required_properties_of_class, cavity_counterpart, quantity_kind_of_property

# Forms of an exemplar. The cavity hangs at the hollow form itself and is made with it
# (own_form), not at the device. The property says who sets the region (cpo:definesForm) and who
# only fills it (cpo:fillsForm, rule 3a.1).
FORM_PROPERTIES = ("cpo:definesForm", "cpo:fillsForm", "cpo:hasEnvelopeForm")

# Under which name the copy of a form is made: as before "Form_...", whether set or filled,
# so that the IDs stay the same.
_ID_ROLE = {"cpo:definesForm": "Form", "cpo:fillsForm": "Form"}


def form_ref(entity: dict):
    """The form an entity takes up - the one it defines or the one it fills (never both)."""
    return entity.get("cpo:definesForm") or entity.get("cpo:fillsForm")

# What is a level marker at a form and does not belong to the form class.
_LEVEL_TYPES = ("hlo:Fixed", "hlo:SeriesSpecific", "hlo:ExperimentSpecific", "hlo:Actual")


def _lookup(entity_id: str, datagraph: dict, library: dict):
    return find_entity(datagraph, entity_id) or (find_entity(library, entity_id) if library else None)


def _offer_form_dimension(owner: dict, form_property: str, property_name: str, dimension: dict, scope: str, nr: int,
                          namespace_collection: dict, datagraph: dict, offer: dict, form_name: str = None):
    """Offer one dimension of the owner's form copy in the owner's value lists, like any other
    quantity of the owner - named after the form and the dimension ("form_inner_height",
    "envelope_form_outer_volume"), so that two forms of one owner never share an entry."""
    # form_name for a form of which an owner has several - the layers of its wall
    # ("layer_ptfe_wall_thickness" next to "form_wall_thickness" of the body form).
    role = form_name or ("envelope_form" if form_property == "cpo:hasEnvelopeForm" else "form")
    base = property_name.split(":", 1)[-1][3:]
    name = role + "".join("_" + c.lower() if c.isupper() else c for c in base)
    evidence_known_cache = offer.get("evidence_known_cache")
    # The gate "known in the experiments?" stands at the series - so on the experiment level
    # under the series counterpart of the owner.
    gate_owner = owner["@id"] if scope == "hlo:SeriesSpecific" else ref_id(owner.get("hlo:specializationOf"))
    gate_key = (gate_owner, f"{form_name or form_property}/{property_name}") if gate_owner and evidence_known_cache is not None else None
    request_value_sources(
        dimension, owner, scope, nr, namespace_collection, datagraph, offer["todo_list"], offer["local_todo_list"],
        quantity=name, segment=name,
        offer_at_series=evidence_known_cache is not None,
        gate_key=gate_key, evidence_known_cache=evidence_known_cache,
    )


def own_form(owner: dict, form_property: str, parent_form: dict, scope: str, nr: int, namespace_collection: dict,
             datagraph: dict, library: dict, name_owner: dict = None,
             shared_dimensions: dict = None, offer: dict = None, role: str = None, offer_name: str = None) -> dict:
    """The owner's own copy of a form at this level, with an own Actual for every dimension.

    parent_form: the form one level up (the library form for a series owner, the series form
    for an experiment owner). library: where the parent's dimensions live if they are not in
    the crate.

    If the parent form has a cavity, the copy gets its own cavity too, sharing the copied
    dimensions (shared_dimensions: parent dimension ID -> the copy on this level). Its layers
    (cpo:hasLayerForm, a coating or lining of the wall, rule 3.8a) and its parts (dcterms:hasPart)
    are copied as well, each with dimensions of its own; role names such a copy, since a form can
    have several of them, and offer_name names its dimensions in the owner's value lists
    ("layer_ptfe_wall_thickness", "part_blade_length").
    name_owner: whose name the form ID carries - the owner itself, or for a cavity the device.

    offer: {"todo_list", "local_todo_list", "evidence_known_cache"} - when given, every own
    dimension (not the aspect ratios) is offered in the owner's value lists: the
    library knows the value, but on this level there may be a measurement or an
    assumption of its own. The caller must be inside the owner's question path.
    """
    if role is None:
        role = _ID_ROLE.get(form_property) or form_property.split(":", 1)[-1]
        role = role[3:] if role.startswith("has") else role
    experiment_number = nr if scope == "hlo:ExperimentSpecific" else None
    name_owner = name_owner or owner
    form_id = claim_id(make_owned_id(role, name_owner["@id"]), datagraph)
    form_types = [t for t in as_list(parent_form.get("@type")) if t not in _LEVEL_TYPES]
    form = {"@id": form_id, "@type": form_types + [scope, "hlo:Actual"]}
    set_property(form, "hlo:specializationOf", parent_form, namespace_collection)
    # The inverse direction only at an entity of the crate - the library is not changed
    # (rule 2.2). The question is about the origin, not the type: forms of the library
    # carry no hlo:Fixed.
    if not is_library_entity(parent_form):
        set_property(parent_form, "hlo:hasSpecialization", form, namespace_collection, True)

    # Every dimension of the form above gets its own empty actual here - except for a cavity:
    # it shares the actuals its hollow form has just created on this level.
    dimensions = {}
    for property_name, value in list(parent_form.items()):
        if property_name.startswith("@") or not property_name.startswith("cpo:has"):
            continue
        refs = [v.get("@id") for v in as_list(value) if isinstance(v, dict) and v.get("@id")]
        if len(refs) != 1:
            continue
        if shared_dimensions and refs[0] in shared_dimensions:
            set_property(form, property_name, shared_dimensions[refs[0]], namespace_collection)
            continue
        dimension = _lookup(refs[0], datagraph, library)
        if dimension is None or "cpo:ProcessVariable" not in as_list(dimension.get("@type")):
            continue
        base = property_name.split(":", 1)[-1][3:]
        dimension_id = generate_id_from_name(f"{base}_{short_local_name(form_id)}", scope, experiment_number)
        # Aspect ratios (cpo:hasAspectRatio and subproperties) describe the structure,
        # the dimensions the space.
        category = "Structure" if base.endswith("Ratio") else "Space"
        dimensions[refs[0]] = add_specializing_actual(form, property_name, dimension, dimension_id, scope, nr,
                                                      namespace_collection, datagraph)
        # Not the aspect ratios - as for the phase forms (_offer_phase_form_dimensions).
        if offer is not None and category == "Space":
            # They are offered at the owner of the form (the device), also for the layers and
            # parts that hang at its body form.
            _offer_form_dimension(name_owner, form_property, property_name, dimensions[refs[0]], scope, nr,
                                  namespace_collection, datagraph, offer, form_name=offer_name)

    cavity_id = next((v.get("@id") for v in as_list(parent_form.get("cpo:hasCavityForm")) if isinstance(v, dict)), None)
    if cavity_id:
        parent_cavity = _lookup(cavity_id, datagraph, library)
        if parent_cavity is None:
            print(f"[{scope}] Note: {parent_form['@id']} points to the cavity {cavity_id}, which is not found - no own copy.")
        else:
            own_form(form, "cpo:hasCavityForm", parent_cavity, scope, nr, namespace_collection, datagraph, library,
                     name_owner=name_owner, shared_dimensions=dimensions)

    # The layers of the wall belong to the device like its body form (rule 3.8a):
    # every level gets its own copy with its thickness, the layer phases fill it.
    for layer_id in [v.get("@id") for v in as_list(parent_form.get("cpo:hasLayerForm")) if isinstance(v, dict)]:
        parent_layer = _lookup(layer_id, datagraph, library)
        if parent_layer is None:
            print(f"[{scope}] Note: {parent_form['@id']} points to the layer {layer_id}, which is not found - no own copy.")
            continue
        layer = _library_local(parent_layer, datagraph, library).split("_Layer_")[-1]
        own_form(form, "cpo:hasLayerForm", parent_layer, scope, nr, namespace_collection, datagraph, library,
                 name_owner=name_owner, offer=offer, role=f"LayerForm_{layer}", offer_name=f"layer_{layer.lower()}")

    # Likewise the parts of a form (the blade at the shaft of the stirrer) (rule 3a.4) - otherwise
    # they would stay in the library, and the requirements of the devices would not reach them in the crate.
    for part_id in [v.get("@id") for v in as_list(parent_form.get("dcterms:hasPart")) if isinstance(v, dict)]:
        parent_part = _lookup(part_id, datagraph, library)
        if parent_part is None:
            print(f"[{scope}] Note: {parent_form['@id']} points to the part {part_id}, which is not found - no own copy.")
            continue
        part = _part_name(parent_part, name_owner, datagraph, library)
        own_form(form, "dcterms:hasPart", parent_part, scope, nr, namespace_collection, datagraph, library,
                 name_owner=name_owner, offer=offer, role=f"PartForm_{part}", offer_name=f"part_{part.lower()}")

    set_property(owner, form_property, form, namespace_collection, form_property in ("cpo:hasLayerForm", "dcterms:hasPart"))
    add_entity(datagraph, form)
    return form


def _library_local(entity: dict, datagraph: dict, library: dict) -> str:
    """The local name of the library entry an entity specializes, the same on every level
    ("device:vessel001_Layer_Lining" -> "vessel001_Layer_Lining"). The name of a layer for the IDs
    of its copies is the part after "_Layer_" ("Lining")."""
    seen = set()
    while entity.get("hlo:specializationOf") and entity["@id"] not in seen:
        seen.add(entity["@id"])
        parent = _lookup(ref_id(entity["hlo:specializationOf"]), datagraph, library)
        if parent is None:
            break
        entity = parent
    return entity["@id"].split(":", 1)[-1].split("/")[-1]


def _part_name(part_form: dict, device: dict, datagraph: dict, library: dict) -> str:
    """The name of a part form for the IDs of its copies: its library entry without the name
    of the device ("device:stirrer001_Blade" of "device:stirrer001" -> "Blade")."""
    local = _library_local(part_form, datagraph, library)
    prefix = _library_local(device, datagraph, library) + "_"
    return local[len(prefix):] if local.startswith(prefix) and len(local) > len(prefix) else local


def own_forms(owner: dict, parent: dict, scope: str, nr: int, namespace_collection: dict, datagraph: dict,
              library: dict, shared_forms: dict = None, offer: dict = None) -> dict:
    """Give the owner its own copy of every form its counterpart one level up has.

    shared_forms maps the ID of a form one level up to a copy that already exists at this
    level (the device's, for its body): the owner then links that copy instead of making its
    own. Returns the mapping for this owner - parent form ID -> own copy - so that it can be
    shared further.

    Who makes the copy on a level defines it: a thing that only fills a form one level up
    (cpo:fillsForm) but finds no copy of it on this level - the room air, whose room has no
    levels - brings the region into the experiment and defines its own copy (cpo:definesForm).
    A thing that is handed a copy (shared_forms) keeps filling it - and does not offer its
    dimensions again; they belong to whoever made the copy (offer, see own_form).
    """
    made = {}
    for form_property in FORM_PROPERTIES:
        for ref in as_list(parent.get(form_property)):
            parent_id = ref.get("@id") if isinstance(ref, dict) else ref
            if not parent_id or form_property in owner:
                continue
            # The same form under two properties (for the vessel the envelope is the form itself:
            # definesForm and hasEnvelopeForm point at one instance) - then one copy here too.
            existing = made.get(parent_id) or (shared_forms or {}).get(parent_id)
            if existing is not None:
                set_property(owner, form_property, existing, namespace_collection)
                made[parent_id] = existing
                continue
            parent_form = _lookup(parent_id, datagraph, library)
            if parent_form is None:
                print(f"[{scope}] Note: {parent['@id']} points to the form {parent_id}, which is not found - no own copy.")
                continue
            own_property = "cpo:definesForm" if form_property == "cpo:fillsForm" else form_property
            made[parent_id] = own_form(owner, own_property, parent_form, scope, nr, namespace_collection, datagraph,
                                       library, offer=offer)
    return made


# ---------------------------------------------------------------------------
# Building a form by its class (rule 3a.3)
# ---------------------------------------------------------------------------

def _empty_actual(form: dict, property_name: str, parent_form: dict, scope: str, nr: int, namespace_collection: dict,
                  datagraph: dict) -> dict:
    """An empty Actual for one dimension of a built form: its quantity kind from the ontology,
    and, on the experiment level, linked to the same dimension of the form one level up."""
    experiment_number = nr if scope == "hlo:ExperimentSpecific" else None
    base = property_name.split(":", 1)[-1][3:]
    value_id = claim_id(generate_id_from_name(f"{base}_{short_local_name(form['@id'])}", scope, experiment_number), datagraph)
    # resolve instead of find_entity: if the form lies one level higher in the library (the layer
    # of a body material on the series level), its dimensions lie there too.
    parent_value = resolve(datagraph, ref_id(parent_form.get(property_name))) if parent_form and parent_form.get(property_name) else None
    if parent_value is not None:
        return add_specializing_actual(form, property_name, parent_value, value_id, scope, nr, namespace_collection,
                                       datagraph)
    value = {"@id": value_id, "@type": [check_type("cpo:ProcessVariable", namespace_collection), scope, "hlo:Actual"]}
    kind = quantity_kind_of_property(property_name, namespace_collection)
    if kind is not None:
        set_property(value, "qudt:hasQuantityKind", {"@id": kind}, namespace_collection)
    set_property(value, "cpo:isProcessVariableOf", form, namespace_collection)
    set_property(form, property_name, value, namespace_collection)
    add_entity(datagraph, value)
    return value


def form_class_of(form: dict):
    """The geometric class of a form (cpo:CupForm, ...) - not cpo:Form itself, not a level marker."""
    return next((t for t in as_list(form.get("@type")) if t.endswith("Form") and t != "cpo:Form"), None)


def form_classes(namespace_collection: dict, hollow: bool = True) -> list:
    """The form classes a form can be built of: every subclass of cpo:Form that states which
    dimensions it needs (a restriction in the ontology), sorted - an abstract superclass such as
    cpo:CylindricalForm, or a placeholder without dimensions, is left out - and, last,
    cpo:IndeterminateForm for a shape that exists but cannot be determined (a transferred
    portion). hollow=False leaves out the classes that have a cavity - a phase is never hollow."""
    from rdflib import RDFS, URIRef
    from helpers.ontology_functions import extend_id, shorten_id
    graphs = namespace_collection.get("cpo", {}).get("graphs", [])
    form = URIRef(extend_id("cpo:Form", namespace_collection))
    found = set()
    for graph in graphs:
        for cls in graph.transitive_subjects(RDFS.subClassOf, form):
            if cls != form and isinstance(cls, URIRef):
                compact = shorten_id(cls, namespace_collection)
                required = required_properties_of_class(compact, namespace_collection)
                # Nobody chooses the layer form: the generator gives it to every layer of a body material
                # itself (rule 3.8a), for a device or another phase it does not fit.
                if compact == "cpo:LayerForm":
                    continue
                if required and (hollow or not any(p == "cpo:hasCavityForm" for p, _ in required)):
                    found.add(compact)
    # The form that cannot be determined deliberately has no restrictions and is therefore offered separately.
    return sorted(found) + ["cpo:IndeterminateForm"]


def build_form(owner: dict, form_property: str, form_class: str, scope: str, nr: int, namespace_collection: dict,
               datagraph: dict, form_id: str = None, shared: dict = None,
               parent_form: dict = None) -> dict:
    """Build a form of the given class for the owner: one Actual for every dimension and aspect
    ratio the class requires (its restrictions in the ontology, see
    required_properties_of_class), and for a hollow class its cavity, which shares the
    dimensions named by cpo:cavityCounterpart.

    shared: property -> an existing Actual this form takes over instead of making its own (a
    phase takes the diameter of the cavity it fills, and its own volume as the volume of its
    form). parent_form: the same form one level up; the new form and its own Actuals
    specialize it. Which requirements check the form follows from what defines it
    (cpo:definesForm, set by the caller through form_property). Nothing is asked - the Actuals are
    empty until a value is recorded.

    This is how a form comes about that has no counterpart in a library to be copied (own_form
    copies one that has).
    """
    shared = dict(shared or {})
    experiment_number = nr if scope == "hlo:ExperimentSpecific" else None
    form_id = form_id or claim_id(generate_id_from_name(f"Form_{short_local_name(owner['@id'])}", scope, experiment_number), datagraph)
    form = {"@id": form_id, "@type": [check_type(form_class, namespace_collection), scope, "hlo:Actual"]}
    if parent_form is not None:
        set_property(form, "hlo:specializationOf", parent_form, namespace_collection)
        if not is_library_entity(parent_form):
            set_property(parent_form, "hlo:hasSpecialization", form, namespace_collection, True)

    cavity_class = None
    for property_name, target in required_properties_of_class(form_class, namespace_collection):
        if property_name == "cpo:hasCavityForm":
            cavity_class = target
            continue
        if property_name in shared:
            set_property(form, property_name, shared[property_name], namespace_collection)
            continue
        _empty_actual(form, property_name, parent_form, scope, nr, namespace_collection, datagraph)

    if cavity_class is not None:
        cavity_shared = {}
        for property_name, _ in required_properties_of_class(form_class, namespace_collection):
            counterpart = cavity_counterpart(property_name, namespace_collection)
            if counterpart and property_name in form:
                cavity_shared[counterpart] = find_entity(datagraph, ref_id(form[property_name])) or form[property_name]
        parent_cavity = find_entity(datagraph, ref_id(parent_form.get("cpo:hasCavityForm"))) if parent_form else None
        build_form(form, "cpo:hasCavityForm", cavity_class, scope, nr, namespace_collection, datagraph, form_id=claim_id(generate_id_from_name(f"CavityForm_{short_local_name(owner['@id'])}", scope, experiment_number), datagraph),
                   shared=cavity_shared, parent_form=parent_cavity)

    set_property(owner, form_property, form, namespace_collection)
    add_entity(datagraph, form)
    return form

