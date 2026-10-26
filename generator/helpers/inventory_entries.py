"""
Building blocks for library entries of the chemical inventory: a container template, a container
(exemplar) with its content, a storage cabinet (rules 3.10, 3.11).

Every function returns plain JSON-LD dicts and writes nothing. Every value comes with its
evidence or reference and a determination task, linked both ways (rule 4.1); every task has a
start, end and duration (rule 4.6), its start stamped by an assumption task of the library. The
library entry tools (workflow/library_entries/) and the inventory tool build on it, and so would an
ELN import.

The IDs follow the library: device:<name>, port:<name>_opening, material:<name>_Body /
_Content, task:<verb>_<name>.

Devices and their contents go to two libraries (rule 2.15): the device - also a container of the inventory -
to the device library, its content and what describes it (lot, receipt, preparation, certificate)
to the material library. Entries collects both and tells them apart (Entries.split).
"""
import math
from contextlib import contextmanager

GLASS = "chem:ChemicalEntity_0001"              # soda-lime glass, as for vessel001 and the vial
GLASS_DENSITY_TASK = "task:looking_up_soda_lime_glass_density"
GLASS_DENSITY = 2500                              # kg/m3, the same value as vessel001 and the vial

# The material of a container (container_template) or of a line (supply_pipe): substance, density
# with its lookup task and source, structure - and the word the texts call it by.
GLASS_BODY = {"entity": GLASS, "density": GLASS_DENSITY, "density_task": GLASS_DENSITY_TASK,
              "source": "MakeItFrom.com, toughened soda-lime glass; NIST SRM 1826b certificate (tsapps.nist.gov).",
              "density_comment": "Generic soda-lime glass, the same value as for device:vessel001 and the vial - not measured.",
              "comment": "Generic soda-lime glass, as for device:vessel001 and the vial.",
              "structure": "cpo:Amorphous", "word": "glass"}
STEEL_BODY = {"entity": "chem:ChemicalEntity_0002", "density": 8000, "density_task": "task:looking_up_stainless_steel_density",
              "source": "MakeItFrom.com, AISI 304 (S30400) stainless steel; en.wikipedia.org/wiki/Stainless_steel.",
              "density_comment": "Generic stainless steel (~8000 kg/m3), same assumption as for the other devices.",
              "comment": "Generic stainless steel, as for the other steel devices of the library - not verified against the "
                         "actual part (a gas cylinder is usually carbon steel; easy to replace).",
              "structure": "cpo:Crystalline", "word": "steel"}


def ref(entity_id):
    return {"@id": entity_id}


def decimal(value):
    return {"@value": f"{value:.12g}", "@type": "xsd:decimal"}


def date_time(value):
    return {"@value": value, "@type": "xsd:dateTime"}


class Entries:
    """Collects the entities of one library and the task every start time is stamped by."""

    def __init__(self, times_task_id: str, stamp: str, person: str, written: str = "the inventory entries"):
        self.items = []
        self.times_task_id = times_task_id
        self.stamp = stamp
        self.person = person
        self.written = written       # what was written down at the stamp, for the comment of each start time
        self.stamped = []            # start-time references the assumption task determines
        self.material_ids = set()    # what goes to the material library (Entries.split)
        self._side = "device"

    @contextmanager
    def side(self, library: str):
        """Everything added inside goes to that library: "material" (a content and what describes
        it) or "device" (the default). Nests: the innermost one counts."""
        outer, self._side = self._side, library
        try:
            yield
        finally:
            self._side = outer

    def add(self, entity):
        self.items.append(entity)
        if self._side == "material":
            self.material_ids.add(entity["@id"])
        return entity

    def split(self) -> tuple:
        """(entries for the device library, entries for the material library), each in the order added."""
        return ([e for e in self.items if e["@id"] not in self.material_ids],
                [e for e in self.items if e["@id"] in self.material_ids])

    def task(self, task_id, task_type, name, description, determines=(), inputs=(), part_of=None, extra=None):
        """A determination task with its three times: start assumed (the moment of entering),
        end and duration unknown."""
        start, end, duration = f"{task_id}_StartTime", f"{task_id}_EndTime", f"{task_id}_Duration"
        task = {"@id": task_id, "@type": [task_type, "hlo:Fixed"], "schema:name": name,
                "schema:description": description, "cpo:performedBy": [ref(self.person)],
                "cpo:hasStartTime": ref(start), "cpo:hasEndTime": ref(end), "cpo:hasDuration": ref(duration)}
        if determines:
            task["cpo:determines"] = [ref(i) for i in determines]
        if inputs:
            task["cpo:hasInputValue"] = [ref(i) for i in inputs]
        if part_of:
            task["dcterms:isPartOf"] = ref(part_of)
        task.update(extra or {})
        self.add(task)
        self.stamp_start(start)
        self.add({"@id": end, "@type": ["time:Instant", "hlo:Fixed", "hlo:Actual"]})
        self.add({"@id": duration, "@type": ["time:Duration", "hlo:Fixed", "hlo:Actual"]})
        return task

    def stamp_start(self, start_id):
        reference_id = f"{start_id}_Reference_1"
        self.add({"@id": start_id, "@type": ["time:Instant", "hlo:Fixed", "hlo:Actual"],
                  "hlo:hasReference": ref(reference_id)})
        self.add({"@id": reference_id, "@type": ["time:Instant", "hlo:Reference"],
                  "hlo:hasReferenceType": ref("hlo:Assumed"),
                  "rdfs:comment": f"No record of when this was done. Stamped with the moment {self.written} were "
                                  f"written down ({self.stamp}) - an upper bound, not the moment it happened.",
                  "rdf:value": date_time(self.stamp), "cpo:hasDeterminationTask": ref(self.times_task_id)})
        self.stamped.append(reference_id)

    def times_task(self, name, description):
        """The assumption task that stamps every start time - its own among them. Call last."""
        task_id = self.times_task_id
        self.task(task_id, "cpo:AssumptionTask", name, description)
        self.find(task_id)["cpo:determines"] = [ref(i) for i in self.stamped]

    def find(self, entity_id):
        return next(e for e in self.items if e["@id"] == entity_id)

    def value(self, actual_id, quantity_kind, role, value, unit, value_type, comment, task_id, source=None,
              kind_on_value=False, owner=None, source_file=None):
        """An Actual with one evidence (role 'Evidence') or reference (role 'Reference')."""
        member_id = f"{actual_id}_{role}_1"
        actual = {"@id": actual_id, "@type": ["cpo:ProcessVariable", "hlo:Fixed", "hlo:Actual"]}
        if not kind_on_value:
            actual["qudt:hasQuantityKind"] = ref(quantity_kind)
        if owner:
            actual["cpo:isProcessVariableOf"] = ref(owner)
        actual[f"hlo:has{role}"] = ref(member_id)
        member = {"@id": member_id, "@type": ["cpo:ProcessVariable", f"hlo:{role}"]}
        if kind_on_value:
            member["qudt:hasQuantityKind"] = ref(quantity_kind)
        member[f"hlo:has{role}Type"] = ref(value_type)
        if source:
            member["hlo:hasSource"] = source
        if source_file:
            member["hlo:hasSourceFile"] = ref(source_file)
        member["rdfs:comment"] = comment
        member["qudt:value"] = decimal(value)
        member["qudt:hasUnit"] = ref(unit)
        member["cpo:hasDeterminationTask"] = ref(task_id)
        self.add(actual)
        self.add(member)
        return member_id

    def instant(self, instant_id, role, value_type, when, comment, task_id, source=None, source_file=None):
        member_id = f"{instant_id}_{role}_1"
        self.add({"@id": instant_id, "@type": ["time:Instant", "hlo:Fixed", "hlo:Actual"], f"hlo:has{role}": ref(member_id)})
        member = {"@id": member_id, "@type": ["time:Instant", f"hlo:{role}"], f"hlo:has{role}Type": ref(value_type)}
        if source:
            member["hlo:hasSource"] = source
        if source_file:
            member["hlo:hasSourceFile"] = ref(source_file)
        member.update({"rdfs:comment": comment, "rdf:value": date_time(when), "cpo:hasDeterminationTask": ref(task_id)})
        self.add(member)
        return member_id


def container_template(lib: Entries, name, label, outer_diameter, outer_height, wall, manufacturer,
                       device_class="cpo:ChemicalContainer", single_use=False, location=None, comment=None,
                       body_kind=None, dimensions=None, openings=None):
    """A container kind (catalogue item) as a glass cup form with a cavity: catalogue outer
    dimensions and an assumed wall; inner dimensions, volumes, glass volume and mass calculated,
    as for device:vial_template. Returns the IDs other entries need, and the glass density
    reference to be added to GLASS_DENSITY_TASK.

    device_class: cpo:ChemicalContainer for a bottle of the inventory, cpo:Vessel for a reaction
    flask or a sample vial. single_use: every use is a fresh specimen taken straight from the
    template (cpo:isSingleUse, rule 3.11) - then location is where its stock is kept. body_kind:
    the material of the body (GLASS_BODY, the default, or STEEL_BODY for a gas cylinder) - its
    density reference goes to body_kind["density_task"].

    dimensions (library entries): how the three given dimensions are known, per key outer_diameter,
    outer_height, wall a dict {role, type, comment, task, source} - then no assumption task of the template is made and
    the caller's tasks determine them; without it they are assumed as before. openings: [(suffix, comment)] - more than
    the one opening port:<name>_opening (a cap with two holes). manufacturer None: none is named."""
    body_spec = body_kind or GLASS_BODY
    word, Word = body_spec["word"], body_spec["word"].capitalize()
    d = f"device:{name}"
    form, cavity = f"{d}_Form", f"{d}_Cavity"
    body, phase = f"material:{name}_Body", f"material:{name}_Body_SolidPhase"
    assume_task = f"task:assuming_{name}_dimensions"
    geometry_task = f"task:calculating_{name}_geometry"

    inner_diameter = outer_diameter - 2 * wall
    inner_height = outer_height - wall
    inner_volume = math.pi / 4 * inner_diameter ** 2 * inner_height
    outer_volume = math.pi / 4 * outer_diameter ** 2 * outer_height
    glass_volume = outer_volume - inner_volume
    glass_mass = glass_volume * body_spec["density"]

    # Template: hlo:Template AND hlo:Fixed (HLO 1.16) - everything that excludes Fixed excludes it too, without inference.
    template = {"@id": d, "@type": [device_class, "hlo:Fixed", "hlo:Template"], "schema:name": f"{label} (template)",
                "rdfs:comment": comment or (f"TEMPLATE of a container kind, not one identifiable bottle: the containers of the inventory "
                                            f"that are of this kind specialize it (hlo:specializationOf) and take over its form, body and "
                                            f"opening. Approximated as a plain {word} cup - the neck is left out."),
                "cpo:isCompositeDevice": False, "cpo:canReceivePower": False}
    if single_use:
        template["cpo:isSingleUse"] = True
    if location:
        template["cpo:locatedInsideOf"] = ref(location)
    ports = [(f"port:{name}_{suffix}", text) for suffix, text in openings] if openings else [(f"port:{name}_opening", None)]
    template["cpo:hasPort"] = ref(ports[0][0]) if len(ports) == 1 else [ref(p) for p, _ in ports]
    if manufacturer:
        template["cpo:hasManufacturer"] = ref(manufacturer)
    template.update({"cpo:madeOfMaterial": ref(body), "cpo:definesForm": ref(form), "cpo:hasEnvelopeForm": ref(form)})
    lib.add(template)
    for port_id, text in ports:
        lib.add({"@id": port_id, "@type": ["cpo:DeviceOpening", "hlo:Fixed"], "cpo:isPortOf": ref(d),
                 **({"rdfs:comment": text} if text else {})})

    lib.add({"@id": form, "@type": "cpo:CupForm",
             "rdfs:comment": f"{Word} cup of the container kind: catalogue outer dimensions ({outer_diameter * 1000:g} mm across, "
                             f"{outer_height * 1000:g} mm tall without the neck) and an assumed {wall * 1000:g} mm wall; the inner "
                             f"dimensions and both volumes follow from them.",
             "cpo:hasOuterHeight": ref(f"{d}_OuterHeight"), "cpo:hasInnerHeight": ref(f"{d}_InnerHeight"),
             "cpo:hasWallThickness": ref(f"{d}_WallThickness"), "cpo:hasInnerDiameter": ref(f"{d}_InnerDiameter"),
             "cpo:hasOuterDiameter": ref(f"{d}_OuterDiameter"), "cpo:hasInnerVolume": ref(f"{d}_InnerVolume"),
             "cpo:hasOuterVolume": ref(f"{d}_OuterVolume"), "cpo:hasCavityForm": ref(cavity),
             "cpo:hasHeightToDiameterRatio": ref(f"{form}_HeightToDiameterRatio"),
             "cpo:hasDiameterRatio": ref(f"{form}_DiameterRatio")})
    lib.add({"@id": cavity, "@type": "cpo:SolidCylinderForm",
             "rdfs:comment": "The space the container holds its content in. No numbers of its own: every parameter is the "
                             "one the cup uses in the opposite role (see cpo:hasCavityForm), as for device:vial_template_Cavity.",
             "cpo:hasDiameter": ref(f"{d}_InnerDiameter"), "cpo:hasHeight": ref(f"{d}_InnerHeight"),
             "cpo:hasOuterVolume": ref(f"{d}_InnerVolume"),
             "cpo:hasHeightToDiameterRatio": ref(f"{cavity}_HeightToDiameterRatio")})
    for ratio in (f"{form}_HeightToDiameterRatio", f"{form}_DiameterRatio", f"{cavity}_HeightToDiameterRatio"):
        lib.add({"@id": ratio, "@type": ["cpo:ProcessVariable", "hlo:Fixed", "hlo:Actual"],
                 "qudt:hasQuantityKind": ref("quantitykind:LengthRatio")})

    if dimensions:
        assumed = [lib.value(f"{d}_{key}", kind, read["role"], value, "unit:M", read["type"], read["comment"], read["task"],
                             source=read.get("source"))
                   for key, kind, value, read in (("OuterDiameter", "quantitykind:Diameter", outer_diameter, dimensions["outer_diameter"]),
                                                  ("OuterHeight", "quantitykind:Height", outer_height, dimensions["outer_height"]),
                                                  ("WallThickness", "quantitykind:Thickness", wall, dimensions["wall"]))]
    else:
        assumed = _assumed_dimensions(lib, d, label, outer_diameter, outer_height, wall, word, assume_task)

    calculations = [
        ("InnerDiameter", "Outer diameter minus twice the wall", f"{outer_diameter:g} m - 2 x {wall:g} m = {inner_diameter:.6g} m.",
         f"{d}_InnerDiameter", "quantitykind:Diameter", inner_diameter, "unit:M", [assumed[0], assumed[2]]),
        ("InnerHeight", "Outer height minus the bottom", f"{outer_height:g} m - {wall:g} m = {inner_height:.6g} m.",
         f"{d}_InnerHeight", "quantitykind:Height", inner_height, "unit:M", [assumed[1], assumed[2]]),
        ("InnerVolume", "Cylinder from the inner dimensions", f"pi/4 x ({inner_diameter:.6g} m)^2 x {inner_height:.6g} m = {inner_volume:.6g} m3.",
         f"{d}_InnerVolume", "quantitykind:Volume", inner_volume, "unit:M3", [f"{d}_InnerDiameter_Evidence_1", f"{d}_InnerHeight_Evidence_1"]),
        ("OuterVolume", "Cylinder from the outer dimensions", f"pi/4 x ({outer_diameter:g} m)^2 x {outer_height:g} m = {outer_volume:.6g} m3.",
         f"{d}_OuterVolume", "quantitykind:Volume", outer_volume, "unit:M3", [assumed[0], assumed[1]]),
        ("Body_SolidPhase_Volume", f"{Word} of the wall and bottom", f"Outer volume minus inner volume: {outer_volume:.6g} m3 - {inner_volume:.6g} m3 = {glass_volume:.6g} m3.",
         f"{phase}_Volume", "quantitykind:Volume", glass_volume, "unit:M3", [f"{d}_OuterVolume_Evidence_1", f"{d}_InnerVolume_Evidence_1"]),
        ("Body_SolidPhase_Mass", f"{Word} volume times {word} density", f"{glass_volume:.6g} m3 x {body_spec['density']} kg/m3 = {glass_mass:.6g} kg.",
         f"{phase}_Mass", "quantitykind:Mass", glass_mass, "unit:KiloGM", [f"{phase}_Volume_Evidence_1", f"{phase}_Density_Reference_1"]),
    ]
    parts = []
    for key, task_name, text, actual_id, kind, value, unit, inputs in calculations:
        task_id = f"task:calculating_{name}_{key}"
        lib.value(actual_id, kind, "Evidence", value, unit, "hlo:Calculated", text + " Assumed geometry, not measured.", task_id)
        lib.task(task_id, "cpo:CalculationTask", task_name, text, determines=[f"{actual_id}_Evidence_1"], inputs=inputs,
                 part_of=geometry_task)
        parts.append(task_id)
    lib.task(geometry_task, "cpo:Task", f"Working out the geometry of the {label.lower()}",
             "Catalogue dimensions and an assumed wall give everything else. Holds the individual calculations together.",
             extra={"dcterms:hasPart": [ref(p) for p in parts]})
    lib.find(geometry_task)["@type"] = ["cpo:Task", "hlo:Fixed"]
    del lib.find(geometry_task)["cpo:performedBy"]

    density = lib.value(f"{phase}_Density", "quantitykind:Density", "Reference", body_spec["density"], "unit:KiloGM-PER-M3",
                        "hlo:Literature", body_spec["density_comment"], body_spec["density_task"], source=body_spec["source"])
    lib.add({"@id": body, "@type": ["cpo:BodyMaterial", "hlo:Fixed"], "schema:name": f"Body material of {name}",
             "rdfs:comment": body_spec["comment"],
             "cpo:hasVolume": ref(f"{phase}_Volume"), "cpo:fillsForm": ref(form),
             "dcterms:hasPart": ref(phase), "cpo:isBodyMaterialOf": ref(d)})
    lib.add({"@id": phase, "@type": ["cpo:SolidPhase", "hlo:Fixed"], "schema:name": f"{name} Body",
             "dcterms:isPartOf": ref(body), "cpo:canCreateEnergyField": False,
             "cpo:hasDispersionState": ref("cpo:Continuous"), "cpo:hasDensity": ref(f"{phase}_Density"),
             "cpo:hasVolume": ref(f"{phase}_Volume"), "cpo:hasMass": ref(f"{phase}_Mass"),
             "dcterms:hasPart": ref(body_spec["entity"]), "cpo:fillsForm": ref(form), "cpo:hasSolidStructure": ref(body_spec["structure"])})
    return {"device": d, "cavity": cavity, "density_reference": density}


def _assumed_dimensions(lib, d, label, outer_diameter, outer_height, wall, word, assume_task):
    """The three dimensions of a container template: catalogue values and an assumed wall."""
    assumed = [
        lib.value(f"{d}_OuterDiameter", "quantitykind:Diameter", "Reference", outer_diameter, "unit:M", "hlo:Assumed",
                  f"Catalogue outer diameter, {outer_diameter * 1000:g} mm. Nominal size, not measured.", assume_task),
        lib.value(f"{d}_OuterHeight", "quantitykind:Height", "Reference", outer_height, "unit:M", "hlo:Assumed",
                  f"Catalogue height of the body without the neck, {outer_height * 1000:g} mm. Nominal size, not measured.", assume_task),
        lib.value(f"{d}_WallThickness", "quantitykind:Thickness", "Reference", wall, "unit:M", "hlo:Assumed",
                  f"Assumed wall and bottom thickness of the {word}, {wall * 1000:g} mm; the inner dimensions follow from it.", assume_task),
    ]
    lib.task(assume_task, "cpo:AssumptionTask", f"Assuming the dimensions of the {label.lower()}",
             f"Catalogue outer dimensions and a typical wall thickness - the {word} was not measured.", determines=assumed)
    return assumed


def supply_pipe(lib: Entries, name, label, location_id, outer_diameter, wall, length, manufacturer, body_kind,
                content_label, species, installed, state_task_id, comment, state="liquid", medium="water"):
    """A supply line of a room that is always filled (rule 7.17) - the deionised water of a lab,
    or (state="gas", medium="air") its compressed air.

    A Fixed cpo:Pipe (not a template, there is one of it) with one outlet (cpo:DeviceOutlet) and a
    tube form with a cavity, as for device:sparger001: outer diameter, wall and length assumed,
    everything else calculated. Its content is described here like the room air: a liquid phase of
    the species, without mass fractions (a phase of one substance is pure, assumption library), and
    one permanent occurrence without beginning or end, whose status (occurred) state_task_id assumes.
    A stream from the outlet then has a known origin (Phase_Time_R2); a run copies the content like
    that of a container (rule 3.10), and its copies get no occurrence of their own
    (has_permanent_occurrence).

    species: [(chem id, species name)]. installed: (start, end) of its installation, assumed by
    state_task_id - the first entry of its usage history (rule 5.5). Returns the values
    state_task_id determines (the task itself is the caller's) and the density reference for
    body_kind["density_task"]."""
    d, port = f"device:{name}", f"port:{name}_outlet"
    form, cavity = f"{d}_Form", f"{d}_Cavity"
    body, body_phase = f"material:{name}_Body", f"material:{name}_Body_SolidPhase"
    content, phase = f"material:{name}_Content", f"material:{name}_Content_Phase"
    occurrence, status = f"{phase}_Occurrence", f"{phase}_OccurrenceStatus"
    commissioning = f"task:commissioning_{name}"
    assume_task, geometry_task = f"task:assuming_{name}_dimensions", f"task:calculating_{name}_geometry"
    word, Word = body_kind["word"], body_kind["word"].capitalize()

    inner_diameter = outer_diameter - 2 * wall
    inner_volume = math.pi / 4 * inner_diameter ** 2 * length
    outer_volume = math.pi / 4 * outer_diameter ** 2 * length
    body_volume = outer_volume - inner_volume
    body_mass = body_volume * body_kind["density"]

    lib.add({"@id": d, "@type": ["cpo:Pipe", "hlo:Fixed"], "schema:name": label, "rdfs:comment": comment,
             "cpo:isCompositeDevice": False, "cpo:canReceivePower": False, "cpo:locatedInsideOf": ref(location_id),
             "cpo:hasPort": ref(port), "cpo:hasManufacturer": ref(manufacturer), "cpo:madeOfMaterial": ref(body),
             "cpo:definesForm": ref(form), "cpo:hasEnvelopeForm": ref(form), "cpo:containsMaterial": ref(content),
             "cpo:hasContainedMaterialHistory": [ref(content)],
             # The first use is the installation (rule 5.5).
             "cpo:hasUsageHistory": [ref(commissioning)], "cpo:lastUsedPurpose": ref(commissioning),
             "cpo:lastUsedTime": ref(f"{commissioning}_EndTime")})
    lib.add({"@id": port, "@type": ["cpo:DeviceOutlet", "hlo:Fixed"], "cpo:isPortOf": ref(d)})

    lib.add({"@id": form, "@type": "cpo:TubeForm",
             "rdfs:comment": f"{Word} tube of the last stretch of the line in the room: assumed outer diameter "
                             f"({outer_diameter * 1000:g} mm), wall ({wall * 1000:g} mm) and length ({length:g} m); the inner "
                             f"diameter and both volumes follow from them.",
             "cpo:hasWallThickness": ref(f"{d}_WallThickness"), "cpo:hasInnerDiameter": ref(f"{d}_InnerDiameter"),
             "cpo:hasOuterDiameter": ref(f"{d}_OuterDiameter"), "cpo:hasInnerVolume": ref(f"{d}_InnerVolume"),
             "cpo:hasOuterVolume": ref(f"{d}_OuterVolume"), "cpo:hasHeight": ref(f"{d}_Height"),
             "cpo:hasCavityForm": ref(cavity), "cpo:hasHeightToDiameterRatio": ref(f"{form}_HeightToDiameterRatio"),
             "cpo:hasDiameterRatio": ref(f"{form}_DiameterRatio")})
    lib.add({"@id": cavity, "@type": "cpo:SolidCylinderForm",
             "rdfs:comment": f"The space the line holds its {medium} in. No numbers of its own: every parameter is the one the "
                             "tube uses in the opposite role (see cpo:hasCavityForm), as for device:sparger001_Cavity.",
             "cpo:hasDiameter": ref(f"{d}_InnerDiameter"), "cpo:hasHeight": ref(f"{d}_Height"),
             "cpo:hasOuterVolume": ref(f"{d}_InnerVolume"),
             "cpo:hasHeightToDiameterRatio": ref(f"{cavity}_HeightToDiameterRatio")})
    for ratio in (f"{form}_HeightToDiameterRatio", f"{form}_DiameterRatio", f"{cavity}_HeightToDiameterRatio"):
        lib.add({"@id": ratio, "@type": ["cpo:ProcessVariable", "hlo:Fixed", "hlo:Actual"],
                 "qudt:hasQuantityKind": ref("quantitykind:LengthRatio")})

    assumed = [
        lib.value(f"{d}_OuterDiameter", "quantitykind:Diameter", "Reference", outer_diameter, "unit:M", "hlo:Assumed",
                  f"Assumed outer diameter of the line, {outer_diameter * 1000:g} mm. Not measured.", assume_task),
        lib.value(f"{d}_WallThickness", "quantitykind:Thickness", "Reference", wall, "unit:M", "hlo:Assumed",
                  f"Assumed wall thickness of the {word}, {wall * 1000:g} mm; the inner diameter follows from it.", assume_task),
        lib.value(f"{d}_Height", "quantitykind:Height", "Reference", length, "unit:M", "hlo:Assumed",
                  f"Assumed length of the line in the room up to the outlet, {length:g} m. Not measured.", assume_task),
    ]
    lib.task(assume_task, "cpo:AssumptionTask", f"Assuming the dimensions of the {label.lower()}",
             f"Typical size of such a line - the {word} was not measured.", determines=assumed)

    calculations = [
        ("InnerDiameter", "Outer diameter minus twice the wall", f"{outer_diameter:g} m - 2 x {wall:g} m = {inner_diameter:.6g} m.",
         f"{d}_InnerDiameter", "quantitykind:Diameter", inner_diameter, "unit:M", [assumed[0], assumed[1]]),
        ("InnerVolume", "Cylinder from the inner diameter and the length",
         f"pi/4 x ({inner_diameter:.6g} m)^2 x {length:g} m = {inner_volume:.6g} m3.",
         f"{d}_InnerVolume", "quantitykind:Volume", inner_volume, "unit:M3", [f"{d}_InnerDiameter_Evidence_1", assumed[2]]),
        ("OuterVolume", "Cylinder from the outer diameter and the length",
         f"pi/4 x ({outer_diameter:g} m)^2 x {length:g} m = {outer_volume:.6g} m3.",
         f"{d}_OuterVolume", "quantitykind:Volume", outer_volume, "unit:M3", [assumed[0], assumed[2]]),
        ("Body_SolidPhase_Volume", f"{Word} of the wall", f"Outer volume minus inner volume: {outer_volume:.6g} m3 - {inner_volume:.6g} m3 = {body_volume:.6g} m3.",
         f"{body_phase}_Volume", "quantitykind:Volume", body_volume, "unit:M3", [f"{d}_OuterVolume_Evidence_1", f"{d}_InnerVolume_Evidence_1"]),
        ("Body_SolidPhase_Mass", f"{Word} volume times {word} density", f"{body_volume:.6g} m3 x {body_kind['density']} kg/m3 = {body_mass:.6g} kg.",
         f"{body_phase}_Mass", "quantitykind:Mass", body_mass, "unit:KiloGM", [f"{body_phase}_Volume_Evidence_1", f"{body_phase}_Density_Reference_1"]),
    ]
    parts = []
    for key, task_name, text, actual_id, quantity_kind, value, unit, inputs in calculations:
        task_id = f"task:calculating_{name}_{key}"
        lib.value(actual_id, quantity_kind, "Evidence", value, unit, "hlo:Calculated", text + " Assumed geometry, not measured.", task_id)
        lib.task(task_id, "cpo:CalculationTask", task_name, text, determines=[f"{actual_id}_Evidence_1"], inputs=inputs,
                 part_of=geometry_task)
        parts.append(task_id)
    lib.task(geometry_task, "cpo:Task", f"Working out the geometry of the {label.lower()}",
             "Assumed outer diameter, wall and length give everything else. Holds the individual calculations together.",
             extra={"dcterms:hasPart": [ref(p) for p in parts]})
    lib.find(geometry_task)["@type"] = ["cpo:Task", "hlo:Fixed"]
    del lib.find(geometry_task)["cpo:performedBy"]

    density = lib.value(f"{body_phase}_Density", "quantitykind:Density", "Reference", body_kind["density"], "unit:KiloGM-PER-M3",
                        "hlo:Literature", body_kind["density_comment"], body_kind["density_task"], source=body_kind["source"])
    lib.add({"@id": body, "@type": ["cpo:BodyMaterial", "hlo:Fixed"], "schema:name": f"Body material of {name}",
             "rdfs:comment": body_kind["comment"], "cpo:hasVolume": ref(f"{body_phase}_Volume"), "cpo:fillsForm": ref(form),
             "dcterms:hasPart": ref(body_phase), "cpo:isBodyMaterialOf": ref(d)})
    lib.add({"@id": body_phase, "@type": ["cpo:SolidPhase", "hlo:Fixed"], "schema:name": f"{name} Body",
             "dcterms:isPartOf": ref(body), "cpo:canCreateEnergyField": False,
             "cpo:hasDispersionState": ref("cpo:Continuous"), "cpo:hasDensity": ref(f"{body_phase}_Density"),
             "cpo:hasVolume": ref(f"{body_phase}_Volume"), "cpo:hasMass": ref(f"{body_phase}_Mass"),
             "dcterms:hasPart": ref(body_kind["entity"]), "cpo:fillsForm": ref(form),
             "cpo:hasSolidStructure": ref(body_kind["structure"])})

    # The content: always there like the room air - an occurrence without start and end, its status assumed.
    # It stands in the Material Library, the line itself in the Device Library (rule 2.15).
    with lib.side("material"):
        species_ids = [f"{phase}_{chem_id.split(':', 1)[1]}" for chem_id, _ in species]
        lib.add({"@id": content, "@type": ["cpo:MaterialVolume", "hlo:Fixed"], "schema:name": content_label,
                 "rdfs:comment": f"The {medium} standing in the line. It is always there: a stream from the outlet takes from it.",
                 "cpo:materialContainedIn": ref(d), "cpo:fillsForm": ref(cavity), "dcterms:hasPart": ref(phase),
                 "cpo:hasVolume": ref(f"{content}_Volume")})
        lib.add({"@id": f"{content}_Volume", "@type": ["cpo:ProcessVariable", "hlo:Fixed", "hlo:Actual"],
                 "qudt:hasQuantityKind": ref("quantitykind:Volume")})
        for species_id, (chem_id, species_name) in zip(species_ids, species):
            lib.add({"@id": species_id, "@type": ["chebi:Molecule", "chebi:ChemicalEntity", "hlo:Fixed"],
                     "schema:name": species_name, "hlo:specializationOf": ref(chem_id), "dcterms:isPartOf": ref(phase)})
        lib.add({"@id": phase, "@type": [PHASE_CLASS[state], "hlo:Fixed"], "schema:name": f"{content_label} ({state})",
                 "dcterms:isPartOf": ref(content), "cpo:canCreateEnergyField": False,
                 "cpo:hasDispersionState": ref("cpo:Continuous"), "cpo:hasVolume": ref(f"{content}_Volume"),
                 "dcterms:hasPart": [ref(s) for s in species_ids], "cpo:fillsForm": ref(cavity),
                 "cpo:hasOccurrence": ref(occurrence)})
        lib.add({"@id": occurrence, "@type": ["cpo:Occurrence", "hlo:Fixed"],
                 "rdfs:comment": f"The {medium} of the line is always there: one occurrence without beginning or end, like the room "
                                 "air. Its status says it occurred, its times are empty Actuals. Stated once here; the series and "
                                 "experiment levels have no occurrence of their own.",
                 "cpo:hasOccurrenceStatus": ref(status), "cpo:hasStartTime": ref(f"{occurrence}_StartTime"),
                 "cpo:hasEndTime": ref(f"{occurrence}_EndTime"), "cpo:hasDuration": ref(f"{occurrence}_Duration")})
        status_reference = f"{status}_Reference_1"
        lib.add({"@id": status, "@type": ["cpo:OccurrenceStatus", "hlo:Fixed", "hlo:Actual"], "hlo:hasReference": ref(status_reference)})
        lib.add({"@id": status_reference, "@type": ["cpo:OccurrenceStatus", "hlo:Reference"], "hlo:hasReferenceType": ref("hlo:Assumed"),
                 "hlo:isReferenceOf": ref(status), "rdfs:comment": "The line is always filled - an assumption about the room, not an "
                                                                  "observation during an experiment.",
                 "cpo:hasOccurrenceValue": ref("cpo:Occurred"), "cpo:hasDeterminationTask": ref(state_task_id)})
        for time_id, time_type in ((f"{occurrence}_StartTime", "time:Instant"), (f"{occurrence}_EndTime", "time:Instant"),
                                   (f"{occurrence}_Duration", "time:Duration")):
            lib.add({"@id": time_id, "@type": [time_type, "hlo:Fixed", "hlo:Actual"]})

    lib.add({"@id": commissioning, "@type": ["cpo:CommissioningTask", "hlo:Fixed"], "schema:name": f"Installing the {label.lower()}",
             "schema:description": "The line was installed with the lab; no record of when. Its first use.",
             "cpo:hasStartTime": ref(f"{commissioning}_StartTime"), "cpo:hasEndTime": ref(f"{commissioning}_EndTime"),
             "cpo:hasDuration": ref(f"{commissioning}_Duration"), "cpo:usedEquipment": [ref(d)]})
    start, end = installed
    determined = [
        status_reference,
        lib.instant(f"{commissioning}_StartTime", "Reference", "hlo:Assumed", start,
                    "Start of the installation - assumed, there is no record.", state_task_id),
        lib.instant(f"{commissioning}_EndTime", "Reference", "hlo:Assumed", end,
                    "End of the installation - assumed, there is no record.", state_task_id),
    ]
    lib.add({"@id": f"{commissioning}_Duration", "@type": ["time:Duration", "hlo:Fixed", "hlo:Actual"]})
    return determined, density


PHASE_CLASS = {"solid": "cpo:SolidPhase", "liquid": "cpo:LiquidPhase", "gas": "cpo:GasPhase"}


def container(lib: Entries, name, label, template_id, cavity_id, cabinet_id, content, records_task_id,
              entered, body_word="glass"):
    """One container of the inventory (an exemplar of template_id) with its content. entered: the
    date of the test entry, for its comment; body_word: what its body is made of (glass, steel).

    content: {"label", "state" (solid/liquid/gas), "solid_structure" (for a solid), "lot", "sku", "manufacturer", "mass_kg",
    "species": [(chem id, species name, mass fraction)], "certificate", "delivered": (start,
    end), "opened", "expires" and/or "retest" (a stable substance has a re-test date instead of an
    expiry date; either may be missing), "certificate_file" (optional: the id of a schema:MediaObject
    for the certificate, made here and named by the references taken from it)} - read off the label,
    the certificate and the delivery note by the task records_task_id (one task for all containers
    entered in one sitting, rule 4.1)."""
    d = f"device:{name}"
    material = f"material:{name}_Content"
    phase = f"{material}_Phase"
    receiving = f"task:receiving_{name}"
    determined = []

    lib.add({"@id": d, "@type": ["cpo:ChemicalContainer", "hlo:Fixed"], "schema:name": label,
             "rdfs:comment": f"One container of the inventory, of the kind {template_id} (form, {body_word} and opening come "
                             f"from there). Its content is described here in the library: lot, manufacturer, purity and the "
                             f"amount delivered. Every experiment that draws from it is an entry of its usage history; "
                             f"what was drawn stands in that experiment's crate. Test entry ({entered}).",
             "hlo:specializationOf": ref(template_id), "cpo:locatedInsideOf": ref(cabinet_id),
             "cpo:containsMaterial": ref(material), "cpo:hasContainedMaterialHistory": [ref(material)],
             "cpo:hasDeliveryTime": ref(f"{receiving}_EndTime"),
             "cpo:hasOpeningTime": ref(f"{d}_OpeningTime"), "cpo:hasUsageHistory": [ref(receiving)],
             # Never used yet: it was last "used" at the delivery (rule 5.5).
             "cpo:lastUsedPurpose": ref(receiving), "cpo:lastUsedTime": ref(f"{receiving}_EndTime")})

    # Delivery, content and certificate into the Material Library (rule 2.15); the container and
    # its opening (a statement about the bottle) into the Device Library.
    with lib.side("material"):
        # The delivery is the commissioning of a bottle (rule 5.5); its end is the time of delivery.
        start, end = content["delivered"]
        receiving_task = {"@id": receiving, "@type": ["cpo:CommissioningTask", "hlo:Fixed"],
                          "schema:name": f"Receiving {label.lower()}",
                          "schema:description": "Delivery unpacked, checked against the order and put into the cabinet.",
                          "cpo:performedBy": [ref(lib.person)], "cpo:hasStartTime": ref(f"{receiving}_StartTime"),
                          "cpo:hasEndTime": ref(f"{receiving}_EndTime"), "cpo:hasDuration": ref(f"{receiving}_Duration"),
                          "cpo:usedEquipment": [ref(d)]}
        lib.add(receiving_task)
        determined.append(lib.instant(f"{receiving}_StartTime", "Evidence", "hlo:Measured", start,
                                      "Delivery received, read off the delivery note.", records_task_id))
        determined.append(lib.instant(f"{receiving}_EndTime", "Evidence", "hlo:Measured", end,
                                      "Delivery shelved, read off the delivery note. This is the delivery time of the container.",
                                      records_task_id))
        lib.add({"@id": f"{receiving}_Duration", "@type": ["time:Duration", "hlo:Fixed", "hlo:Actual"]})
        with lib.side("device"):
            determined.append(lib.instant(f"{d}_OpeningTime", "Evidence", "hlo:Observed", content["opened"],
                                          "Date written on the label by whoever opened the container first.",
                                          records_task_id))

        lib.add({"@id": material, "@type": ["cpo:MaterialVolume", "hlo:Fixed"], "schema:name": content["label"],
                 "rdfs:comment": "The content of the container as delivered. The amount is the one at delivery; what "
                                 "experiments drew from it stands in their crates.",
                 "cpo:materialContainedIn": ref(d), "cpo:fillsForm": ref(cavity_id), "dcterms:hasPart": ref(phase),
                 "cpo:hasLotNumber": content["lot"], "schema:sku": content["sku"],
                 "cpo:hasManufacturer": ref(content["manufacturer"]), "cpo:hasMass": ref(f"{material}_Mass"),
                 "cpo:hasVolume": ref(f"{material}_Volume")})
        determined.append(lib.value(f"{material}_Mass", "quantitykind:Mass", "Reference", content["mass_kg"], "unit:KiloGM",
                                    "hlo:Literature", "Net content at delivery, as printed on the label.", records_task_id,
                                    source=f"Label of lot {content['lot']}"))
        certificate_file = content.get("certificate_file")
        if certificate_file:
            lib.add({"@id": certificate_file, "@type": ["schema:MediaObject", "hlo:Fixed"],
                     "schema:name": content["certificate"], "schema:encodingFormat": "application/pdf"})
        if content.get("expires"):
            lib.find(material)["cpo:hasExpiryTime"] = ref(f"{material}_ExpiryTime")
            determined.append(lib.instant(f"{material}_ExpiryTime", "Reference", "hlo:Literature", content["expires"],
                                          "Expiry date of the lot, as printed on the label.", records_task_id,
                                          source=f"Label of lot {content['lot']}"))
        if content.get("retest"):
            lib.find(material)["cpo:hasRetestTime"] = ref(f"{material}_RetestTime")
            determined.append(lib.instant(f"{material}_RetestTime", "Reference", "hlo:Literature", content["retest"],
                                          "Re-test date of the lot, from the certificate of analysis.", records_task_id,
                                          source=content["certificate"], source_file=certificate_file))

        # Volume of the content: it is not known (the label states the mass), an empty actual says
        # "the quantity exists" - shared by the material and its only phase as for the body material.
        lib.add({"@id": f"{material}_Volume", "@type": ["cpo:ProcessVariable", "hlo:Fixed", "hlo:Actual"],
                 "qudt:hasQuantityKind": ref("quantitykind:Volume")})

        determined += _content_phase(lib, material, phase, content, cavity_id, records_task_id,
                                     "from the certificate of analysis of the lot", content["certificate"], "hlo:Literature",
                                     source_file=certificate_file)
        determined.append(content_occurrence(lib, phase, f"{receiving}_EndTime",
                                             "The content arrived with the delivery, checked against the order on receiving.",
                                             records_task_id))
    return determined


def _content_phase(lib: Entries, material, phase, content, cavity_id, task_id, how, source, value_type, source_file=None):
    """The single phase of a content with its species and their mass fractions (determined by
    task_id, 'how' they are known, from 'source'). Returns the values task_id determines."""
    determined = []
    species_ids = []
    for chem_id, species_name, fraction in content["species"]:
        species_id = f"{phase}_{chem_id.split(':', 1)[1]}"
        species_ids.append(species_id)
        lib.add({"@id": species_id, "@type": ["chebi:Molecule", "chebi:ChemicalEntity", "hlo:Fixed"],
                 "schema:name": species_name, "hlo:specializationOf": ref(chem_id), "dcterms:isPartOf": ref(phase),
                 "cpo:hasConcentration": ref(f"{species_id}_Concentration")})
        determined.append(lib.value(f"{species_id}_Concentration", "quantitykind:MassFraction", "Reference", fraction,
                                    "unit:UNITLESS", value_type,
                                    f"Mass fraction of {species_name.lower()} in the content, {how}.",
                                    task_id, source=source, kind_on_value=True, owner=species_id,
                                    source_file=source_file))
    lib.add({"@id": phase, "@type": [PHASE_CLASS[content["state"]], "hlo:Fixed"], "schema:name": f"{content['label']} ({content['state']})",
             "dcterms:isPartOf": ref(material), "cpo:canCreateEnergyField": False,
             "cpo:hasDispersionState": ref("cpo:Continuous"), "cpo:hasMass": ref(f"{material}_Mass"),
             "cpo:hasVolume": ref(f"{material}_Volume"),
             "dcterms:hasPart": [ref(s) for s in species_ids], "cpo:fillsForm": ref(cavity_id),
             **({"cpo:hasSolidStructure": ref(content["solid_structure"])} if content["state"] == "solid" else {})})
    return determined


def prepared_container(lib: Entries, name, label, template_id, cavity_id, cabinet_id, content, sources, preparation,
                       container_id=None):
    """A container of the inventory filled in the lab (rule 7.17): a stock solution, a batch,
    a refill. The preparation is described here, in the inventory, not as a crate:

    - task:preparing_<name> (cpo:OperationTask; start and end with their evidence, read off the lab
      notebook by itself - preparation["start"]/["end"]), which uses the source containers and the
      new one, realizes preparation["functions"] and aims at
    - one cpo:Transfer (cpo:PortCrossing) per source: from the content phase of the source into the
      new content phase - the way material came in, so that the shapes reach the sources
      (Phase_Time_R2, R4-R7);
    - the content: material, phase and species (mass fractions known from the preparation itself,
      a reference of type Assumed unless measured), its lot (content["lot"]: the own batch number -
      for a refill the lot of the source, which the content still is),
      and its acquisition: an occurrence starting at the end of the preparation, whose status the
      preparation determines.

    sources: [{"container": "device:…", "phase": "material:…_Content_Phase", "volume_m3": optional}].
    The new container's usage history starts with its preparation (rule 5.5: its first use);
    the sources' histories are not touched here - add_usage (the writer) sorts the preparation in.

    container_id (rule 2.15): fill a container that is there already - a bottle
    that held something before - instead of a new one. Then only the content and its preparation are
    made here (name names the content); putting it into the container (its history, the current
    content) and the preparation into its usage history is the writer's (workflow/inventory_tool.py),
    as are label, template_id and cabinet_id, which are not used.
    Returns the id of the preparation task."""
    d = container_id or f"device:{name}"
    material = f"material:{name}_Content"
    phase = f"{material}_Phase"
    task = f"task:preparing_{name}"
    determined = []

    if container_id is None:
        lib.add({"@id": d, "@type": ["cpo:ChemicalContainer", "hlo:Fixed"], "schema:name": label,
                 "rdfs:comment": f"One container of the inventory, of the kind {template_id}, filled in the lab by {task} - "
                                 f"the preparation, its transfers from the source containers and the content are described "
                                 f"in the material library.",
                 "hlo:specializationOf": ref(template_id), "cpo:locatedInsideOf": ref(cabinet_id),
                 "cpo:containsMaterial": ref(material), "cpo:hasContainedMaterialHistory": [ref(material)],
                 "cpo:hasUsageHistory": [ref(task)],
                 "cpo:lastUsedPurpose": ref(task), "cpo:lastUsedTime": ref(f"{task}_EndTime")})

    # Production, transfers and content into the Material Library, the container into
    # the Device Library.
    with lib.side("material"):
        transfers = []
        for source in sources:
            source_name = source["container"].split(":", 1)[1]
            transfer = f"{phase}_from_{source_name}"
            transfers.append(transfer)
            entry = {"@id": transfer, "@type": ["cpo:Transfer", "hlo:Fixed"], "schema:name": f"From {source_name} into {name}",
                     "cpo:hasTransferType": ref("cpo:PortCrossing"), "cpo:removesFromPhase": ref(source["phase"]),
                     "cpo:addsToPhase": ref(phase), "cpo:isAimOf": ref(task)}
            if source.get("volume_m3") is not None:
                entry["cpo:hasTransferredVolume"] = ref(f"{transfer}_TransferredVolume")
                determined.append(lib.value(f"{transfer}_TransferredVolume", "quantitykind:Volume", "Evidence", source["volume_m3"],
                                            "unit:M3", "hlo:Measured", "Volume taken from the source, from the lab notebook.", task,
                                            owner=transfer))
            lib.add(entry)

        lib.add({"@id": task, "@type": ["cpo:OperationTask", "hlo:Fixed"], "schema:name": preparation["name"],
                 "schema:description": preparation["description"], "cpo:performedBy": [ref(lib.person)],
                 "cpo:hasStartTime": ref(f"{task}_StartTime"), "cpo:hasEndTime": ref(f"{task}_EndTime"),
                 "cpo:hasDuration": ref(f"{task}_Duration"),
                 "cpo:usedEquipment": [ref(s["container"]) for s in sources] + [ref(d)],
                 "cpo:realizesFunction": [ref(f) for f in preparation["functions"]],
                 "cpo:aimsAt": [ref(t) for t in transfers]})
        determined.append(lib.instant(f"{task}_StartTime", "Evidence", "hlo:Observed", preparation["start"],
                                      "Start of the preparation, from the lab notebook.", task))
        determined.append(lib.instant(f"{task}_EndTime", "Evidence", "hlo:Observed", preparation["end"],
                                      "End of the preparation, from the lab notebook. The content exists from here on.", task))
        lib.add({"@id": f"{task}_Duration", "@type": ["time:Duration", "hlo:Fixed", "hlo:Actual"]})

        lib.add({"@id": material, "@type": ["cpo:MaterialVolume", "hlo:Fixed"], "schema:name": content["label"],
                 "rdfs:comment": "The content of the container as prepared in the lab; what experiments drew from it stands in their crates.",
                 "cpo:materialContainedIn": ref(d), "cpo:fillsForm": ref(cavity_id), "dcterms:hasPart": ref(phase),
                 "cpo:hasLotNumber": content["lot"], "cpo:hasMass": ref(f"{material}_Mass"),
                 "cpo:hasVolume": ref(f"{material}_Volume")})
        for quantity, kind in (("Mass", "quantitykind:Mass"), ("Volume", "quantitykind:Volume")):
            lib.add({"@id": f"{material}_{quantity}", "@type": ["cpo:ProcessVariable", "hlo:Fixed", "hlo:Actual"],
                     "qudt:hasQuantityKind": ref(kind)})
        determined += _content_phase(lib, material, phase, content, cavity_id, task,
                                     "as made up in the preparation", None, "hlo:Assumed")
        determined.append(content_occurrence(lib, phase, f"{task}_EndTime",
                                             "The content exists since its preparation ended.", task))
        lib.find(task)["cpo:determines"] = [ref(i) for i in determined]
    return task


def content_occurrence(lib: Entries, phase_id, start_id, comment, records_task_id):
    """The occurrence of the content of a container in the lab (rule 7.17, Phase_Time_R1): it starts when the
    content came into the lab - at start_id, the end of the task that delivered it (receiving) or
    produced it (a reaction, making up a solution; not the filling) - and ends when it is used up
    or disposed of, unknown until then. Through the start the task is reached, and with it the
    origin. Returns the evidence of its status, which records_task_id determines."""
    # One point in time, two roles: the end of the task and the start of the occurrence point at the
    # same time:Instant (like lastServicedTime on two levels) - nothing is copied. It is no permanent
    # occurrence like that of the room air: the experiments keep their own occurrence (whether and
    # when the content was there), a different event (has_permanent_occurrence).
    occurrence = f"{phase_id}_Occurrence"
    status = f"{occurrence}_Status"
    evidence = f"{status}_Evidence_1"
    lib.find(phase_id)["cpo:hasOccurrence"] = ref(occurrence)
    lib.add({"@id": occurrence, "@type": ["cpo:Occurrence", "hlo:Fixed"],
             "rdfs:comment": "The content in the lab: from when it was delivered or produced until it is used up or "
                             "disposed of (end unknown until then).",
             "cpo:hasOccurrenceStatus": ref(status), "cpo:hasStartTime": ref(start_id),
             "cpo:hasEndTime": ref(f"{occurrence}_EndTime"), "cpo:hasDuration": ref(f"{occurrence}_Duration")})
    lib.add({"@id": status, "@type": ["cpo:OccurrenceStatus", "hlo:Fixed", "hlo:Actual"], "hlo:hasEvidence": ref(evidence)})
    lib.add({"@id": evidence, "@type": ["cpo:OccurrenceStatus", "hlo:Evidence"], "hlo:hasEvidenceType": ref("hlo:Observed"),
             "hlo:isEvidenceOf": ref(status), "rdfs:comment": comment,
             "cpo:hasOccurrenceValue": ref("cpo:Occurred"), "cpo:hasDeterminationTask": ref(records_task_id)})
    lib.add({"@id": f"{occurrence}_EndTime", "@type": ["time:Instant", "hlo:Fixed", "hlo:Actual"]})
    lib.add({"@id": f"{occurrence}_Duration", "@type": ["time:Duration", "hlo:Fixed", "hlo:Actual"]})
    return evidence


def cabinet(cabinet_id, label, room_id, comment):
    return {"@id": cabinet_id, "@type": ["cpo:StorageCabinet", "hlo:Fixed"], "schema:name": label,
            "rdfs:comment": comment, "cpo:locatedInsideOf": ref(room_id)}
