# TEST: `suite-self-test` has 8 red assertions on the current tree

## Symptom

`python3 test_suite.py` (the `suite-self-test` job) exits 1. Reproduced on
branch `work/fix-gate-native-dumpfull` with its `tools/suite.py` change
reverted, so these predate that change. The verify log for `3d3f61d6` shows the
same job failing.

The 8 failing assertions:

1. `budgets: the residue census is the residue` - census and walk disagree.
   Example: `test_nonascii_len_regression.py` census 0 vs walk 3;
   `test_polymorphic_float_regress.py` census 0 vs walk 1; and about five more
   `test_regress*` files with census 0 vs walk 1.
2. `budgets: the residue is not allowed to GROW` - 55 files carry a literal
   against a census of 48.
3. `the estate: every test file is run by something, or says why not` - about
   50 `test_*.py` files are not run by any registered spec, are not in
   `UNREGISTERED`, and are in no declared family (e.g.
   `test_regress_none_false.py`, `test_regression_socket_request_for_member.py`,
   `tools/test_control_pool.py`).
4. `formal doc index: OPEN_WORK.md's generated block is current` - the block in
   `bugs/OPEN_WORK.md` is stale.
5. `formal doc index: --check compares the tree and ignores the machine` - and
6. `formal doc index: ...the file is byte-identical afterwards` - the planted-
   document probe fails, which goes with item 4 once the generated block is
   regenerated.
7. `expect count: the counts the registry states are the ones the reader sees`
   - the reader sees `{'x86-containers': 1, 'ab-native': 1, 'formal-x86-endtoend': 1}`
   and the docs state a different set.
8. `doc status: the rule is not vacuous` - only `ab-native` is stated in any
   table row.

## Expected

All assertions green. Each is a check on a registry, census, or generated doc
that has drifted from the tree it describes.

## Next step

- Items 4-6: run `python3 tools/formal_doc_index.py --write`, then rerun the
  self-test. This is the mechanical fix.
- Items 1-2: rerun the residue census, and for each drifted file either update
  its row or drop it, per the assertion's own message.
- Item 3: add each unlisted file to a family or to `UNREGISTERED` with a reason,
  or register it.
- Items 7-8: the `doc status` and `expect count` checks are reading the docs
  tables. Compare what the tables state against the current `expect=` markers in
  `tools/suite.py` (`python3 tools/suite.py --list`).

Not checked here: whether the individual remedies would re-trip the other
checks.

## Status (2026-10-30, merge of master into work/fix-merge-fix-gate-suite-self-test)

Landed: `bugs/OPEN_WORK.md`'s generated block regenerated with
`python3 tools/formal_doc_index.py --write` (the 'Next step' above, items 4-6).
`python3 tools/formal_doc_index.py --check` now PASSes (111 documents, block
current), and `test_suite.py` has no formal-doc-index failure left.

Measured after the merge (`python3 test_suite.py`, 360 passed, 6 failed):
- items 1-2 (budgets: residue census / residue may not grow): still red. Census
  0 vs walk 1-3 on several `test_regress*` files; 55 literal files vs census 48.
- item 3 (estate): still red, 50 unregistered `test_*.py` files and
  `tools/test_control_pool.py`, `tools/test_swarm_feed.py`.
- dangling refs, BARE class: red on master's new citation
  `bugs/COMPILE_FAIL_Tools_cases_generator_analyzer.md` (3 vs ceiling 2). Needs
  `python3 tools/dangling_doc_refs.py --write-baseline` only after the citation
  is checked, not as a bulk bump.
- item 7 (expect count): still red, the reader sees
  `{'x86-containers': 1, 'ab-native': 1, 'formal-x86-endtoend': 1}`.
- item 8 (doc status): still red, only `ab-native` is stated in a table row.

Next step: items 1-3 and 7-8 as above. This is the one place the suite-self-test
red is tracked; a parallel note was deleted as a duplicate.
