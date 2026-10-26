# Properties per class and level

What every class has to have, should have or can have on each level – **Template, Fixed (library), Series, Experiment** – and where that is said: the shapes, the library entry schema, the setup sheet, the questions of the generator and the consistency check of the libraries; next to it how often the real data have it. Where the sources do not fit together, the class lists a gap.

Generated on demand by `python generator/workflow/property_overview/build_property_overview.py` – for instance before writing, or after larger changes of the shapes, the schemas, the libraries or the crates; `--check` says whether these files are out of date. Do not edit by hand.

Built from: the libraries and the 6 crates of the working tree, the four shape files, both schemas and the answer files of all projects.

## Legend

A cell: `status · shapes · fields · questions · checks · count`.

| Status | Meaning |
|---|---|
| **req** | required: a shape with severity Violation, a required entry or sheet field, or a check of the libraries asks for it |
| rec | recommended: a shape with severity Warning asks for it |
| ban | banned: a shape forbids it (`sh:maxCount 0`) |
| ask | asked: the generator asks for it, or an optional field of the entry schema or the sheet gives it |
| *lib* | read from the libraries (Template, Fixed): it stands in the library, but nothing above asks for it – written by an entry tool, by a generator run (usage history, `lastUsedTime`, content ends) or by a curation script; each entry names its source in its comment |
| *drv* | derived (Series, Experiment): it is in the crate, but nothing above asks for it – the generator makes it |
| – | nothing |

| Mark | Meaning |
|---|---|
| `Device_Space_R2` | a context requirement (ContextRequirementShapes.ttl); other names are shapes of DataQualityShapes.ttl / FunctionShapes.ttl |
| ↑ | met through the chain (`hlo:specializationOf`): it may stand one level higher (rule 3.6) – the count follows the chain |
| † | the shape has conditions or alternatives – listed under the table |
| ✕ | the shape forbids it |
| `E type.field` | a field of the library entry schema (`entry_schema.yaml`); `!` = required |
| `S module.field` | a field of the setup sheet (`sheet_schema.yaml`); `!` = required |
| `G question_id` | a question of the generator, from the answer files of all projects |
| `C …` | a check of `check_library_consistency.py` (assigned by hand, `overview_config.yaml`) |
| `k/n` | k of the n entities of the class on this level have it (libraries and crates together) |

Rows are properties – or the paths a shape asks for (`cpo:madeOfMaterial / dcterms:hasPart / cpo:hasTemperature`). A subclass shows only its additions: the rows a shape or source names for exactly this class and the properties only it has within its parent; the rows of the parent hold for it too, and its gaps are listed at the parent with the classes they lie in.

Levels of the data: `hlo:Template`, `hlo:Fixed`, `hlo:SeriesSpecific`, `hlo:ExperimentSpecific` in the type, otherwise the ID ending; library entries without a level take that of what points at them; the series and the entities that describe the whole crate count as Series.

## Families

| Family | Classes | Gaps (without optional fields) |
|---|---|---|
| [Devices](devices.md) | [cpo:Device](devices.md#cpodevice), [cpo:Jacket](devices.md#cpojacket), [cpo:Lid](devices.md#cpolid), [cpo:Pipe](devices.md#cpopipe), [cpo:Pump](devices.md#cpopump), [cpo:Reactor](devices.md#cporeactor), [cpo:Septum](devices.md#cposeptum), [cpo:Sparger](devices.md#cposparger), [cpo:Stirrer](devices.md#cpostirrer), [cpo:Valve](devices.md#cpovalve), [cpo:Vessel](devices.md#cpovessel), [cpo:ChemicalContainer](devices.md#cpochemicalcontainer), [sosa:Sampler](devices.md#sosasampler), [sosa:Sensor](devices.md#sosasensor), [cpo:MassFlowMeter](devices.md#cpomassflowmeter), [cpo:MassFlowController](devices.md#cpomassflowcontroller) | 8 |
| [Materials and phases](materials_and_phases.md) | [cpo:EnergyField](materials_and_phases.md#cpoenergyfield), [cpo:MaterialRepresentation](materials_and_phases.md#cpomaterialrepresentation), [cpo:MaterialVolume](materials_and_phases.md#cpomaterialvolume), [cpo:BodyMaterial](materials_and_phases.md#cpobodymaterial), [cpo:Environment](materials_and_phases.md#cpoenvironment), [cpo:Stream](materials_and_phases.md#cpostream), [cpo:Phase](materials_and_phases.md#cpophase), [cpo:GasPhase](materials_and_phases.md#cpogasphase), [cpo:LiquidPhase](materials_and_phases.md#cpoliquidphase), [cpo:SolidPhase](materials_and_phases.md#cposolidphase) | 14 |
| [Substances and reactions](substances_and_reactions.md) | [chebi:ChemicalEntity](substances_and_reactions.md#chebichemicalentity), [chebi:Atom](substances_and_reactions.md#chebiatom), [chebi:Molecule](substances_and_reactions.md#chebimolecule), [cpo:ActiveSite](substances_and_reactions.md#cpoactivesite), [cpo:OccupationState](substances_and_reactions.md#cpooccupationstate), [cpo:Placeholder](substances_and_reactions.md#cpoplaceholder), [cpo:Reaction](substances_and_reactions.md#cporeaction), [cpo:ElementaryReaction](substances_and_reactions.md#cpoelementaryreaction), [cpo:LumpedReaction](substances_and_reactions.md#cpolumpedreaction), [cpo:StoichiometricReaction](substances_and_reactions.md#cpostoichiometricreaction), [cpo:ReactionMechanism](substances_and_reactions.md#cporeactionmechanism), [cpo:ReactionParticipant](substances_and_reactions.md#cporeactionparticipant) | 16 |
| [Tasks](tasks.md) | [cpo:Task](tasks.md#cpotask), [cpo:CalibrationTask](tasks.md#cpocalibrationtask), [cpo:CommissioningTask](tasks.md#cpocommissioningtask), [cpo:DeterminationTask](tasks.md#cpodeterminationtask), [cpo:AssumptionTask](tasks.md#cpoassumptiontask), [cpo:CalculationTask](tasks.md#cpocalculationtask), [cpo:LiteratureLookupTask](tasks.md#cpoliteraturelookuptask), [cpo:MeasurementTask](tasks.md#cpomeasurementtask), [cpo:ObservationTask](tasks.md#cpoobservationtask), [cpo:OperationTask](tasks.md#cpooperationtask), [cpo:RecordingTask](tasks.md#cporecordingtask), [cpo:ServiceTask](tasks.md#cposervicetask), [cpo:SpecificationTask](tasks.md#cpospecificationtask), [cpo:ControlTask](tasks.md#cpocontroltask), [cpo:PlanningTask](tasks.md#cpoplanningtask), [cpo:SettingTask](tasks.md#cposettingtask), [cpo:TransferTask](tasks.md#cpotransfertask), [cpo:SamplingTask](tasks.md#cposamplingtask) | 11 |
| [Values and times](values_and_times.md) | [cpo:Occurrence](values_and_times.md#cpooccurrence), [cpo:OccurrenceStatus](values_and_times.md#cpooccurrencestatus), [cpo:Parameter](values_and_times.md#cpoparameter), [cpo:ProcessVariable](values_and_times.md#cpoprocessvariable), [cpo:ProfileVariable](values_and_times.md#cpoprofilevariable), [cpo:ScalarVariable](values_and_times.md#cposcalarvariable), [cpo:SeriesVariable](values_and_times.md#cposeriesvariable), [cpo:ProfileStep](values_and_times.md#cpoprofilestep), [cpo:HoldStep](values_and_times.md#cpoholdstep), [cpo:TransitionStep](values_and_times.md#cpotransitionstep), [hlo:Actual](values_and_times.md#hloactual), [hlo:Evidence](values_and_times.md#hloevidence), [hlo:Reference](values_and_times.md#hloreference), [time:Duration](values_and_times.md#timeduration), [time:Instant](values_and_times.md#timeinstant) | 18 |
| [Forms, ports and transfers](forms_ports_transfers.md) | [cpo:Form](forms_ports_transfers.md#cpoform), [cpo:AnnularShellForm](forms_ports_transfers.md#cpoannularshellform), [cpo:CuboidForm](forms_ports_transfers.md#cpocuboidform), [cpo:CylindricalForm](forms_ports_transfers.md#cpocylindricalform), [cpo:AnnulusForm](forms_ports_transfers.md#cpoannulusform), [cpo:ClosedHollowCylinderForm](forms_ports_transfers.md#cpoclosedhollowcylinderform), [cpo:CupForm](forms_ports_transfers.md#cpocupform), [cpo:SolidCylinderForm](forms_ports_transfers.md#cposolidcylinderform), [cpo:TubeForm](forms_ports_transfers.md#cpotubeform), [cpo:IndeterminateForm](forms_ports_transfers.md#cpoindeterminateform), [cpo:LayerForm](forms_ports_transfers.md#cpolayerform), [cpo:SphericalForm](forms_ports_transfers.md#cposphericalform), [cpo:Interface](forms_ports_transfers.md#cpointerface), [cpo:PhaseInterface](forms_ports_transfers.md#cpophaseinterface), [cpo:PhasePairInterface](forms_ports_transfers.md#cpophasepairinterface), [cpo:Port](forms_ports_transfers.md#cpoport), [cpo:DevicePort](forms_ports_transfers.md#cpodeviceport), [cpo:DeviceInlet](forms_ports_transfers.md#cpodeviceinlet), [cpo:DeviceOpening](forms_ports_transfers.md#cpodeviceopening), [cpo:DeviceOutlet](forms_ports_transfers.md#cpodeviceoutlet), [cpo:Sink](forms_ports_transfers.md#cposink), [cpo:Source](forms_ports_transfers.md#cposource), [cpo:Transfer](forms_ports_transfers.md#cpotransfer) | 8 |
| [Organizations and people](organizations_and_people.md) | [cpo:Room](organizations_and_people.md#cporoom), [cpo:Laboratory](organizations_and_people.md#cpolaboratory), [cpo:StorageCabinet](organizations_and_people.md#cpostoragecabinet), [org:Organization](organizations_and_people.md#orgorganization), [org:Site](organizations_and_people.md#orgsite), [schema:Person](organizations_and_people.md#schemaperson) | 2 |
| [Series, files and datasets](series_files_datasets.md) | [CreativeWork](series_files_datasets.md#creativework), [Dataset](series_files_datasets.md#dataset), [cpo:Column](series_files_datasets.md#cpocolumn), [cpo:ReferenceColumn](series_files_datasets.md#cporeferencecolumn), [cpo:ExperimentEntity](series_files_datasets.md#cpoexperimententity), [cpo:ExperimentalSeries](series_files_datasets.md#cpoexperimentalseries), [cpo:SingleExperiment](series_files_datasets.md#cposingleexperiment), [cpo:Ontology](series_files_datasets.md#cpoontology), [hlo:ContextAspect](series_files_datasets.md#hlocontextaspect), [schema:CreativeWork](series_files_datasets.md#schemacreativework), [schema:Dataset](series_files_datasets.md#schemadataset), [schema:MediaObject](series_files_datasets.md#schemamediaobject), [cpo:File](series_files_datasets.md#cpofile), [cpo:Image](series_files_datasets.md#cpoimage), [schema:PropertyValue](series_files_datasets.md#schemapropertyvalue), [schema:SoftwareApplication](series_files_datasets.md#schemasoftwareapplication) | 6 |

## Gaps

What the comparison of the sources shows (per class in the family files, under its table):

| Gap | Meaning | Number |
|---|---|---|
| Nothing supplies it | a shape asks for it on this level, no entry field, sheet field, question or check gives it, and not every entity has it | 2 |
| Short in the data | a shape asks for it and something gives it, but not every entity has it | 3 |
| Required field, no shape | an entry or sheet field requires it, but no shape and no check asks for it | 55 |
| Shape stricter than the field | a shape requires it (Violation), but the field that gives it is optional | 3 |
| Field without data | an entry or sheet field gives it, but no entity of the class has it on this level | 20 |
| Asked, not on the sheet | the generator asks for it on the series or experiment level, but no field of the sheet gives it | 0 |
| Optional field, no shape | an optional entry or sheet field gives it, no shape and no check asks for it | 178 |

### Asked for by a shape, but nothing gives it

The gaps of the kind *Nothing supplies it*, by family – a shape asks for something on a level, no person is asked for it and the generator does not always make it (k/n: of the entities the shape applies to; **bold**: severity Violation):

- **Materials and phases**: [cpo:Phase](materials_and_phases.md#cpophase) `(^cpo:addsToPhase / cpo:removesFromPhase \| hlo:specializationOf)* / cpo:hasOccurrence` (Series, 109/110); [cpo:Phase](materials_and_phases.md#cpophase) `(^cpo:addsToPhase / cpo:removesFromPhase \| hlo:specializationOf)* / cpo:hasOccurrence` (Experiment, 193/196)

## Not assigned

What the script could not place – a field without `property:`, a question without an entry in `overview_config.yaml`:

- nothing

## Sources read

- Shapes: 212 demands and constraints from ContextRequirementShapes.ttl, DataQualityShapes.ttl, FunctionShapes.ttl, QuantityKindShapes.ttl
- Library entry schema: 507 rows; setup sheet: 135 rows (+ the quantity of a value); questions: 19075 keys of the answer files → 361 rows; checks: 19
- Data: 53223 entities from `libraries/assumption_library.jsonld (with its details)`, `libraries/chemical_entity_library.jsonld (with its details)`, `libraries/device_library.jsonld (with its details)`, `libraries/material_library.jsonld (with its details)`, `libraries/ontology_library.jsonld (with its details)`, `libraries/organization_library.jsonld (with its details)`, `libraries/people_library.jsonld (with its details)`, `libraries/reaction_library.jsonld (with its details)`, `libraries/software_library.jsonld (with its details)`, `projects/amidation_ai4green_ai4_001/crate_completed/ro-crate-metadata.json`, `projects/chemotion_example/crate_completed/ro-crate-metadata.json`, `projects/fdca_cl2_elabftw_7849/crate_completed/ro-crate-metadata.json`, `projects/fdca_cl2_elabftw_7849_all_steps/crate_completed/ro-crate-metadata.json`, `projects/hydrogenation_rdy_2026_09/crate/ro-crate-metadata.json`, `projects/pba_synthesis/crate/ro-crate-metadata.json`
