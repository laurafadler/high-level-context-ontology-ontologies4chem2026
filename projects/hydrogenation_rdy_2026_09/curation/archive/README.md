# Archived curation scripts of the hydrogenation

Laura Fadler, 09.10.2026: phase the curation scripts out - new library entries are made with
`generator/workflow/library_entries/`, fixed reactions with `generator/workflow/library_prerun/` (rules 2.11, 2.16).

- `fixed_reactions.py` (05.10.2026) - the three reactions of the hydrogenation as templates with fixed reactions
  made from them (rule 2.11);
- `migrate_to_fixed_reactions.py` (05.10.2026) - moved the sheet and the answer file from the templates to the fixed
  reactions;
- `add_supply_test_entries.py` (02.10.2026, until then in `generator/tests/`) - the test entries for the origin of
  hydrogen and cooling water: the hydrogen cylinder, its gas cabinet and the deionised water supply of Lab 109;
- `n20_make_rules.py` (29.09.2026) - the rules of N20: NH3 moves wherever H2 moves, except at the catalyst interfaces.
  Its output, `curation/n20_answer_rules.json` and `n20b_answer_rules.json` (rules for `answer_driver.py --rules`),
  is in the sheet and the answer file; the two files were removed on 15.10.2026 (last in commit `6d549c3`).
- `pressure_regulator_as_valve_20261015.py` (15.10.2026) - the pressure regulator of the hydrogen supply typed as
  `cpo:Valve` instead of a plain `cpo:Device` (Laura Fadler).

They ran once; their results are in the libraries, the sheet and the answer file. **Do not run them again** - their
paths still assume the folder `curation/`. The last state in `curation/` is commit `c490264`.
