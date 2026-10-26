# Archived PBA reactions

`reaction_library_pba_chloride_templates_20261005.jsonld` holds the PBA entries of the reaction library as
they were from 05.10.2026 until 06.10.2026: the twelve templates written by `add_pba_chemistry.py` (from
potassium hexacyanoferrate and the metal(II) chlorides, with potassium chloride as by-product), their
placeholders, and the two fixed reactions made from them with `pba_reactions.py`
(`reaction:PBA_Ferrocyanide_Ni`, `reaction:PBA_Ferrocyanide_Mn_Ni`).

On 06.10.2026 Laura Fadler and Meng Kong decided to model the chemistry net-ionic: the salts are weighed in
as hydrates, dissolving one releases its ions and its water of crystallization, and the PBA forms from the
ions (`add_pba_ions.py`). The new templates and fixed reactions keep the IDs of the old ones; no crate was
built with the old ones. This file is not read by the generator - it is only kept for looking up.

The scripts as they were then: `add_pba_chemistry.py` and `pba_reactions.py` at commit `e4b29d0`.

The anhydrous salts these entries name (`chem:PotassiumFerrocyanide`, `chem:NickelIIChloride`, ...) are no longer
in the chemical entity library since 07.10.2026 (`remove_anhydrous_salts.py`); they are still in it at commit
`95cafab`.

# Archived curation scripts (09.10.2026)

Laura Fadler, 09.10.2026: phase the curation scripts out - new library entries are made with
`generator/workflow/library_entries/` (rule 2.16). Every script here ran once between 05.10. and 08.10.2026 and
its entries are in the libraries; each says in its docstring what it did and on whose word. **Do not run them
again** - most stop at an entry that exists, the others would overwrite later changes, and their paths still
assume the folder `curation/` (`ROOT = parents[3]` now points one folder too low). The last state in
`curation/` is commit `c490264`.

- `add_k1_system.py` (05.10.) - the K1 Start flow reactor system of Lab 208; `restructure_k1_reactor.py` (06.10., L9)
  cut its capillaries into sections, `move_k1_vent_to_housing.py` (08.10., N19) moved the vent to the housing.
  `add_k1_system.py` is also the pattern for devices with parts and ports of their own, which the entry tools do
  not make.
- `add_pba_chemistry.py` (05.10.) and `add_pba_ions.py` (06.10.) - the chemistry, first with salts, then net-ionic
  (see above); `remove_anhydrous_salts.py` (07.10.) took out the salts no longer used.
- `add_pba_stock.py` (07.10., L10) - the three hydrate containers and the deionised water supply of Lab 208;
  `switch_pba_manganese_to_nitrate.py` (08.10., N16) - manganese(II) nitrate instead of the chloride.
- `add_pba_stock_solutions.py`, `update_pba_ferrocyanide_stock.py`, `commission_pba_stock_bottles.py` (07.10.),
  `confirm_pba_stock_times.py` (08.10., N17) - the stock solutions, their labels, commissioning and preparation times.
- `add_pba_cap_ports.py`, `remove_pba_ring_caps.py` (08.10.) - the GL45 caps of the K1 Start, first as rings with
  ports, then taken out to be written again as cups upside down (rule 3b.4).
- `update_pba_dimensions.py` (07.10., G6/G9) and `update_pba_balance.py` (08.10., N21) - corrected dimensions, the
  balance Fisherbrand PAS214C.
- `apply_meng_answers_20261014.py` (14.10.) - Meng Kong's answers to the remaining questions: the ferrocyanide
  concentration confirmed, the manganese(II) concentration assumed as the nickel one, 500 mL stock bottles, two
  cabinets (the second one, `lab:L208_Cyanoferrate_Cabinet`, from `library_entries/cabinet_20261014_1828.yaml`), the
  dummies of the salts and the water line turned into assumptions.
- `stock_solution_cabinets_20261015.py` (15.10.) - Laura Fadler takes the assumption that each stock solution stands
  with its salt.
- `sulfuric_acid_assumed_20261015.py` (15.10.) - the bottle of dilute sulfuric acid (kind, content, lot, receipt):
  assumptions of Laura Fadler instead of placeholders to be asked of Meng Kong.

Two former scripts are tools of the generator since 09.10.2026, because the series needs them again:
`pba_reactions.py` -> `generator/workflow/library_prerun/pba_reactions.py` (fixed reactions per metal combination),
`extract_run_tables.py` -> `generator/interfaces/instruments/k1_start_run_tables.py` (the run tables of K1 logs).
